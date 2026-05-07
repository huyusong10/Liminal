from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from loopora.executor import (
    EXECUTOR_OUTPUT_MAX_BYTES,
    ExecutorError,
    RealCodexExecutor,
    RoleRequest,
    build_command_event_payload,
)
from loopora.executor_session_refs import extract_session_ref, infer_codex_session_ref_from_rollouts


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


def test_real_executor_rejects_oversized_custom_output(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    script = (
        "import sys; "
        "from pathlib import Path; "
        f"Path(sys.argv[1]).write_text('{{\"blob\":\"' + ('x' * {EXECUTOR_OUTPUT_MAX_BYTES + 1}) + '\"}}', "
        "encoding='utf-8')"
    )
    request = RoleRequest(
        run_id="run_test",
        role="custom_helper",
        prompt="Emit JSON only.",
        workdir=tmp_path,
        model="",
        reasoning_effort="",
        output_schema={"type": "object", "properties": {"blob": {"type": "string"}}, "required": ["blob"]},
        output_path=run_dir / "custom_output.json",
        run_dir=run_dir,
        executor_kind="custom",
        executor_mode="command",
        command_cli=sys.executable,
        command_args_text=f"-c\n{script}\n{{output_path}}\n{{prompt}}\n",
    )

    executor = RealCodexExecutor()
    with pytest.raises(ExecutorError, match="output file is too large"):
        executor.execute(
            request,
            lambda _event_type, _payload: None,
            lambda: False,
            lambda _pid: None,
        )


def test_real_executor_rejects_non_utf8_custom_output(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    script = "import sys; from pathlib import Path; Path(sys.argv[1]).write_bytes(b'\\xff')"
    request = RoleRequest(
        run_id="run_test",
        role="custom_helper",
        prompt="Emit JSON only.",
        workdir=tmp_path,
        model="",
        reasoning_effort="",
        output_schema={"type": "object", "properties": {}, "additionalProperties": True},
        output_path=run_dir / "custom_output.json",
        run_dir=run_dir,
        executor_kind="custom",
        executor_mode="command",
        command_cli=sys.executable,
        command_args_text=f"-c\n{script}\n{{output_path}}\n{{prompt}}\n",
    )

    executor = RealCodexExecutor()
    with pytest.raises(ExecutorError, match="non-UTF-8 output"):
        executor.execute(
            request,
            lambda _event_type, _payload: None,
            lambda: False,
            lambda _pid: None,
        )


def test_command_event_payload_redacts_prompt_schema_and_secret_values(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    request = RoleRequest(
        run_id="run_test",
        role="custom_helper",
        prompt="PROMPT_SECRET_MARKER write the whole plan",
        workdir=tmp_path,
        model="",
        reasoning_effort="",
        output_schema={
            "type": "object",
            "properties": {"SCHEMA_SECRET_MARKER": {"type": "string"}},
        },
        output_path=run_dir / "custom_output.json",
        run_dir=run_dir,
    )
    schema_text = '{"type": "object", "properties": {"SCHEMA_SECRET_MARKER": {"type": "string"}}}'

    payload = build_command_event_payload(
        request,
        [
            "custom-tool",
            "--json-schema",
            schema_text,
            "--auth-token",
            "TOKEN_SECRET_MARKER",
            "prefix PROMPT_SECRET_MARKER write the whole plan",
        ],
    )

    assert payload["type"] == "command"
    assert payload["prompt_omitted"] is True
    assert payload["json_schema_omitted"] is True
    assert payload["token_omitted"] is True
    assert payload["command_truncated"] is False
    assert "PROMPT_SECRET_MARKER" not in payload["message"]
    assert "SCHEMA_SECRET_MARKER" not in payload["message"]
    assert "TOKEN_SECRET_MARKER" not in payload["message"]
    assert "<prompt omitted>" in payload["message"]
    assert "<json schema omitted>" in payload["message"]
    assert "<secret omitted>" in payload["message"]


def test_real_codex_executor_can_parse_resume_output_without_schema(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    codex_path = fake_bin / "codex"
    codex_path.write_text(
        "#!/bin/sh\n"
        "output=''\n"
        "while [ \"$#\" -gt 0 ]; do\n"
        "  if [ \"$1\" = \"--output-last-message\" ]; then\n"
        "    output=\"$2\"\n"
        "    shift 2\n"
        "    continue\n"
        "  fi\n"
        "  shift\n"
        "done\n"
        "printf '```json\\n{\"ok\": true, \"mode\": \"resume\"}\\n```\\n' > \"$output\"\n"
        "printf '{\"type\":\"stdout\",\"message\":\"resume ok\"}\\n'\n",
        encoding="utf-8",
    )
    codex_path.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}")

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    request = RoleRequest(
        run_id="run_test",
        role="generator",
        prompt="Return JSON only.",
        workdir=tmp_path,
        model="gpt-5.4",
        reasoning_effort="medium",
        output_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]},
        output_path=run_dir / "generator_output.json",
        run_dir=run_dir,
        inherit_session=True,
        resume_session_id="session-123",
    )

    emitted: list[tuple[str, dict]] = []
    executor = RealCodexExecutor()
    payload = executor.execute(
        request,
        lambda event_type, payload: emitted.append((event_type, payload)),
        lambda: False,
        lambda _pid: None,
    )

    assert payload == {"ok": True, "mode": "resume"}
    assert ("codex_event", {"type": "stdout", "message": "resume ok"}) in emitted


def test_executor_session_ref_extracts_nested_session_payload() -> None:
    payload = {
        "type": "event",
        "data": {
            "sessionId": {"uuid": "11111111-2222-4333-8444-555555555555"},
            "rolloutPath": "/tmp/rollout-11111111-2222-4333-8444-555555555555.jsonl",
        },
    }

    assert extract_session_ref(payload) == {
        "session_id": "11111111-2222-4333-8444-555555555555",
        "rollout_path": "/tmp/rollout-11111111-2222-4333-8444-555555555555.jsonl",
    }


def test_executor_session_ref_infers_codex_rollout_and_skips_invalid_candidates(tmp_path: Path) -> None:
    workdir = tmp_path / "workspace"
    workdir.mkdir()
    sessions_dir = tmp_path / "codex-home" / "sessions"
    sessions_dir.mkdir(parents=True)
    (sessions_dir / "rollout-invalid.jsonl").mkdir()
    session_id = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    rollout_path = sessions_dir / f"rollout-{session_id}.jsonl"
    rollout_path.write_text(f'{{"cwd": "{workdir}", "type": "session_meta"}}\n', encoding="utf-8")

    assert infer_codex_session_ref_from_rollouts(
        workdir=workdir,
        current_ref={},
        codex_home=tmp_path / "codex-home",
    ) == {
        "session_id": session_id,
        "rollout_path": str(rollout_path),
    }


def test_generator_prompt_uses_bootstrap_guidance_for_spec_only_workspace(
    service_factory,
    tmp_path: Path,
) -> None:
    service = service_factory()
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    (workdir / "spec.md").write_text("# Task\n\nBuild something useful.\n", encoding="utf-8")
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


def test_challenger_prompt_uses_evidence_buckets_for_repair_direction(service_factory) -> None:
    service = service_factory()
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

    prompt = service._challenger_prompt(
        compiled_spec,
        {"stagnation_mode": "plateau", "recent_composites": [0.62, 0.63]},
        2,
    )

    assert "Proven, Weak, Unproven, Blocking, and Residual risk" in prompt
    assert "Turn Blocking or Unproven gaps into the next smallest proof or fix" in prompt
    assert "keep Residual risk visible" in prompt


def test_legacy_runtime_prompts_treat_run_contract_as_frozen(service_factory, tmp_path: Path) -> None:
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
    tester_output = {
        "execution_summary": "The flow still breaks.",
        "check_results": [],
        "dynamic_checks": [],
        "tester_observations": "No passing proof.",
    }
    prompts = [
        service._check_planner_prompt(compiled_spec),
        service._generator_prompt(compiled_spec, workdir, 0, "default"),
        service._tester_prompt(compiled_spec, 0, "default"),
        service._verifier_prompt(compiled_spec, tester_output, 0, "default"),
        service._challenger_prompt(compiled_spec, {"stagnation_mode": "plateau"}, 1),
    ]

    for prompt in prompts:
        assert "Treat the run contract as frozen" in prompt
        assert "do not reinterpret or lower the Task, Done When, checks, or guardrails" in prompt
        assert "evidence gap, blocker, or Loop-adjustment recommendation" in prompt
        assert "project-local instructions, design docs, and tests" in prompt
