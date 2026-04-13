from __future__ import annotations

import os
from pathlib import Path

import pytest

from liminal.executor import ExecutorError, RealCodexExecutor, RoleRequest


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

    (workdir / "index.html").write_text("<!doctype html><title>Prototype</title>", encoding="utf-8")
    prompt_with_app = service._generator_prompt(compiled_spec, workdir, 0, "default")
    assert "this iteration should bootstrap the first implementation" not in prompt_with_app
