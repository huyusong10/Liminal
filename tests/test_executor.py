from __future__ import annotations

import os
from pathlib import Path

import pytest

from loopora.executor import ExecutorError, RealCodexExecutor, RoleRequest


def test_real_executor_times_out_after_idle_period(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    codex_path = fake_bin / "codex"
    codex_path.write_text("#!/bin/sh\nsleep 5\n", encoding="utf-8")
    codex_path.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}")

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    request = RoleRequest(
        run_id="run_test",
        role="generator",
        prompt="test prompt",
        workdir=tmp_path,
        model="gpt-5.4",
        reasoning_effort="low",
        output_schema={"type": "object", "properties": {}, "additionalProperties": True},
        output_path=run_dir / "generator_output.json",
        run_dir=run_dir,
        idle_timeout_seconds=0.3,
    )

    executor = RealCodexExecutor()
    with pytest.raises(ExecutorError, match="produced no output"):
        executor.execute(
            request,
            lambda _event_type, _payload: None,
            lambda: False,
            lambda _pid: None,
        )


def test_real_executor_supports_custom_command_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    custom_path = fake_bin / "custom-tool"
    custom_path.write_text(
        "#!/bin/sh\n"
        "output=''\n"
        "while [ \"$#\" -gt 0 ]; do\n"
        "  if [ \"$1\" = \"--output\" ]; then\n"
        "    output=\"$2\"\n"
        "    shift 2\n"
        "    continue\n"
        "  fi\n"
        "  shift\n"
        "done\n"
        "printf '{\"ok\": true, \"engine\": \"custom\"}\\n' > \"$output\"\n"
        "printf 'custom wrapper complete\\n'\n",
        encoding="utf-8",
    )
    custom_path.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}")

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    request = RoleRequest(
        run_id="run_test",
        role="custom_helper",
        prompt="Emit JSON only.",
        workdir=tmp_path,
        model="",
        reasoning_effort="",
        output_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]},
        output_path=run_dir / "custom_output.json",
        run_dir=run_dir,
        executor_kind="custom",
        executor_mode="command",
        command_cli="custom-tool",
        command_args_text="--output\n{output_path}\n{prompt}\n",
    )

    emitted: list[tuple[str, dict]] = []
    executor = RealCodexExecutor()
    payload = executor.execute(
        request,
        lambda event_type, payload: emitted.append((event_type, payload)),
        lambda: False,
        lambda _pid: None,
    )

    assert payload == {"ok": True, "engine": "custom"}
    assert request.output_path.exists()
    assert ("codex_event", {"type": "stdout", "message": "custom wrapper complete"}) in emitted


def test_generator_prompt_uses_bootstrap_guidance_for_spec_only_workspace(
    service_factory,
    tmp_path: Path,
) -> None:
    service = service_factory()
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    (workdir / "spec.md").write_text("# Goal\n\nBuild something useful.\n", encoding="utf-8")
    compiled_spec = {
        "goal": "Build something useful.",
        "checks": [
            {
                "id": "check_001",
                "title": "Main flow exists",
                "details": "A visible main flow exists.",
                "when": "When the user opens the prototype.",
                "expect": "The main flow is visible.",
                "fail_if": "The page is empty.",
            }
        ],
        "constraints": "- Keep it simple.",
    }

    prompt = service._generator_prompt(compiled_spec, workdir, 0, "default")
    assert "this iteration should bootstrap the first implementation" in prompt
    assert "Create the smallest runnable prototype from scratch" not in prompt
    assert "Never wipe the whole workdir" in prompt
    assert "safe to add the first app files now" in prompt
    assert "This role must end with a concrete attempt" in prompt
    assert "prefer using it to establish evidence in this iteration" in prompt

    (workdir / "index.html").write_text("<!doctype html><title>Prototype</title>", encoding="utf-8")
    prompt_with_app = service._generator_prompt(compiled_spec, workdir, 0, "default")
    assert "this iteration should bootstrap the first implementation" not in prompt_with_app
    assert "This role must end with a concrete attempt" in prompt_with_app


def test_generator_prompt_includes_previous_iteration_feedback(service_factory, tmp_path: Path) -> None:
    service = service_factory()
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    compiled_spec = {
        "goal": "Improve the primary flow.",
        "checks": [
            {
                "id": "check_001",
                "title": "Main flow works",
                "details": "The main flow is usable.",
                "when": "When the user follows the main path.",
                "expect": "The main path succeeds.",
                "fail_if": "The path breaks.",
            }
        ],
        "constraints": "- Keep changes focused.",
    }

    prompt = service._generator_prompt(
        compiled_spec,
        workdir,
        1,
        "default",
        previous_generator_result={"attempted": "Updated the main flow copy.", "summary": "Focused on the hero section."},
        previous_tester_result={
            "failed_items": [{"id": "check_001", "title": "Main flow works", "source": "specified"}],
            "tester_observations": "The CTA still does not start the workflow.",
        },
        previous_verifier_result={
            "decision_summary": "The primary flow still stalls before completion.",
            "composite_score": 0.61,
            "failed_check_titles": ["Main flow works"],
            "next_actions": ["Make the CTA complete the core workflow."],
        },
        previous_challenger_result={
            "analysis": {"recommended_shift": "Try a smaller but end-to-end interaction fix."},
            "seed_question": "What is the smallest end-to-end fix that removes the stall?",
        },
    )

    assert "Previous iteration evidence:" in prompt
    assert "The CTA still does not start the workflow." in prompt
    assert "The primary flow still stalls before completion." in prompt
    assert "Try a smaller but end-to-end interaction fix." in prompt
    assert "Do not restart from scratch." in prompt
