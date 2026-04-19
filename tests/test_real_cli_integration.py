from __future__ import annotations

"""Heavy real-provider integration coverage.

These tests invoke real provider CLIs and external APIs. They are skipped by
default and are intended for manual verification or dedicated CI jobs, not the
default fast feedback loop.
"""

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

from loopora.db import LooporaRepository
from loopora.providers import executor_profile, normalize_executor_kind
from loopora.service import LooporaService
from loopora.settings import AppSettings

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_WORKSPACE = ROOT / "tests" / "fixtures" / "english_learning_workspace"
REAL_CLI_ENV = "LOOPORA_ENABLE_REAL_CLI_E2E"
REAL_CLI_TIMEOUT_ENV = "LOOPORA_REAL_CLI_TIMEOUT_SECONDS"
REAL_CLI_TARGETS_ENV = "LOOPORA_REAL_CLI_TARGETS"
REAL_CLI_CODEX_MODEL_ENV = "LOOPORA_REAL_CLI_CODEX_MODEL"
REAL_CLI_CLAUDE_MODEL_ENV = "LOOPORA_REAL_CLI_CLAUDE_MODEL"
REAL_CLI_OPENCODE_MODEL_ENV = "LOOPORA_REAL_CLI_OPENCODE_MODEL"
PROVIDER_ORDER = ("codex", "claude", "opencode")
PROVIDER_MODEL_ENV = {
    "codex": REAL_CLI_CODEX_MODEL_ENV,
    "claude": REAL_CLI_CLAUDE_MODEL_ENV,
    "opencode": REAL_CLI_OPENCODE_MODEL_ENV,
}
PROOF_PAIRS = (
    ("tests/contract/english-learning-smoke.mjs", "tests/evidence/english-learning-homepage-proof.json"),
    ("tests/contract/english-learning-structure.mjs", "tests/evidence/english-learning-structure-proof.json"),
)


@dataclass(frozen=True)
class RealRunArtifacts:
    provider: str
    workdir: Path
    run: dict
    run_dir: Path
    events: list[dict]
    role_requests: list[dict]
    command_events: list[dict]
    terminal_event: dict


def _read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _wait_for_terminal_run(service: LooporaService, run_id: str, *, timeout_seconds: float) -> dict:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        run = service.get_run(run_id)
        if run["status"] in {"succeeded", "failed", "stopped"}:
            return run
        time.sleep(1.0)
    raise AssertionError(f"timed out waiting for real CLI run {run_id} to finish")


def _selected_real_cli_targets() -> tuple[str, ...]:
    raw = str(os.environ.get(REAL_CLI_TARGETS_ENV, "") or "").strip()
    if not raw:
        return tuple(
            provider
            for provider in PROVIDER_ORDER
            if shutil.which(executor_profile(provider).cli_name) is not None
        )

    selected: list[str] = []
    invalid: list[str] = []
    for token in raw.split(","):
        stripped = token.strip()
        if not stripped:
            continue
        try:
            normalized = normalize_executor_kind(stripped)
        except ValueError:
            invalid.append(stripped)
            continue
        if normalized not in PROVIDER_ORDER:
            invalid.append(stripped)
            continue
        if normalized not in selected:
            selected.append(normalized)

    if invalid:
        joined = ", ".join(invalid)
        raise AssertionError(f"unsupported {REAL_CLI_TARGETS_ENV} entries: {joined}")
    return tuple(selected)


def _require_real_cli_target(provider: str) -> None:
    if os.environ.get(REAL_CLI_ENV) != "1":
        pytest.skip(f"set {REAL_CLI_ENV}=1 to run the heavy real-provider integration suite")
    if shutil.which("node") is None:
        pytest.skip("node is unavailable in PATH")
    if not FIXTURE_WORKSPACE.exists():
        pytest.skip(f"workspace fixture is missing: {FIXTURE_WORKSPACE}")

    cli_name = executor_profile(provider).cli_name
    selected = _selected_real_cli_targets()
    if provider not in selected:
        if shutil.which(cli_name) is None:
            pytest.skip(f"{provider} CLI ({cli_name}) is unavailable in PATH")
        pytest.skip(f"{provider} is not enabled by {REAL_CLI_TARGETS_ENV}")


def _provider_model(provider: str) -> str:
    env_name = PROVIDER_MODEL_ENV[provider]
    override = str(os.environ.get(env_name, "") or "").strip()
    if override:
        return override
    return executor_profile(provider).default_model


def _provider_reasoning_effort(provider: str) -> str:
    return executor_profile(provider).effort_default


def _summary_text(run_dir: Path) -> str:
    summary_path = run_dir / "summary.md"
    if not summary_path.exists():
        return "(missing summary.md)"
    return summary_path.read_text(encoding="utf-8")


def _start_real_loop(
    tmp_path: Path,
    *,
    provider: str,
    workflow_preset: str,
    completion_mode: str,
    max_iters: int,
) -> RealRunArtifacts:
    _require_real_cli_target(provider)
    workdir = tmp_path / f"{provider}-{workflow_preset}-{completion_mode}-workspace"
    shutil.copytree(FIXTURE_WORKSPACE, workdir)

    repository = LooporaRepository(tmp_path / f"{provider}-{workflow_preset}-{completion_mode}.db")
    settings = AppSettings(
        max_concurrent_runs=1,
        polling_interval_seconds=0.1,
        stop_grace_period_seconds=0.5,
        role_idle_timeout_seconds=300.0,
    )
    service = LooporaService(repository=repository, settings=settings)
    loop = service.create_loop(
        name=f"Real {provider} {workflow_preset} {completion_mode}",
        spec_path=workdir / "spec.md",
        workdir=workdir,
        model=_provider_model(provider),
        reasoning_effort=_provider_reasoning_effort(provider),
        max_iters=max_iters,
        max_role_retries=1,
        delta_threshold=0.005,
        trigger_window=2,
        regression_window=2,
        executor_kind=provider,
        executor_mode="preset",
        role_models={},
        workflow={"preset": workflow_preset},
        completion_mode=completion_mode,
    )
    queued_run = service.rerun(loop["id"], background=True)
    timeout_seconds = float(os.environ.get(REAL_CLI_TIMEOUT_ENV, "900"))
    run = _wait_for_terminal_run(service, queued_run["id"], timeout_seconds=timeout_seconds)

    run_dir = Path(run["runs_dir"])
    events = _read_jsonl(run_dir / "timeline" / "events.jsonl")
    role_requests = _read_jsonl(run_dir / "context" / "role_requests.jsonl")
    command_events = [
        event
        for event in events
        if event["event_type"] == "codex_event"
        and event.get("payload", {}).get("type") == "command"
    ]
    terminal_event = next(event for event in reversed(events) if event["event_type"] == "run_finished")
    return RealRunArtifacts(
        provider=provider,
        workdir=workdir,
        run=run,
        run_dir=run_dir,
        events=events,
        role_requests=role_requests,
        command_events=command_events,
        terminal_event=terminal_event,
    )


def _role_execution_summaries(artifacts: RealRunArtifacts, *, roles: set[str]) -> list[dict]:
    return [
        event
        for event in artifacts.events
        if event["event_type"] == "role_execution_summary"
        and event.get("role") in roles
    ]


def _command_messages(artifacts: RealRunArtifacts) -> list[str]:
    return [str(event.get("payload", {}).get("message") or "") for event in artifacts.command_events]


def _assert_common_run_health(artifacts: RealRunArtifacts, *, expected_status: str) -> None:
    summary = _summary_text(artifacts.run_dir)
    assert artifacts.run["status"] == expected_status, summary
    assert artifacts.terminal_event["payload"]["status"] == expected_status, summary
    assert not any(event["event_type"] == "run_aborted" for event in artifacts.events), summary
    assert (artifacts.run_dir / "summary.md").exists()
    assert (artifacts.run_dir / "contract" / "run_contract.json").exists()


def _assert_provider_resume_command_shape(artifacts: RealRunArtifacts) -> None:
    messages = _command_messages(artifacts)
    if artifacts.provider == "codex":
        resume_messages = [message for message in messages if "codex exec resume" in message]
        assert resume_messages, "expected a Codex resume command in the second builder iteration"
        assert not any("--cd" in message for message in resume_messages)
        assert not any("--sandbox" in message for message in resume_messages)
        assert not any("--output-schema" in message for message in resume_messages)
        return
    if artifacts.provider == "claude":
        resume_messages = [message for message in messages if message.startswith("claude ") and " --resume " in f" {message} "]
        assert resume_messages, "expected a Claude Code --resume command in the second builder iteration"
        assert not any(" --continue " in f" {message} " for message in resume_messages)
        return
    resume_messages = [message for message in messages if message.startswith("opencode run") and " --session " in f" {message} "]
    assert resume_messages, "expected an OpenCode --session command in the second builder iteration"
    assert not any(" --continue " in f" {message} " for message in resume_messages)


def _assert_proof_harnesses(workdir: Path) -> None:
    for smoke_rel, proof_rel in PROOF_PAIRS:
        smoke_path = workdir / smoke_rel
        proof_path = workdir / proof_rel
        assert smoke_path.exists(), f"missing proof harness: {smoke_rel}"
        subprocess.run(
            ["node", str(smoke_path), str(proof_path)],
            cwd=workdir,
            check=True,
            capture_output=True,
            text=True,
        )
        proof = json.loads(proof_path.read_text(encoding="utf-8"))
        assert proof.get("pass"), f"proof harness did not emit pass fields: {proof_rel}"
        assert all(bool(value) for value in proof.get("pass", {}).values())


def _requests_for_step(artifacts: RealRunArtifacts, step_id: str) -> list[dict]:
    return [item for item in artifacts.role_requests if item.get("step_id") == step_id]


@pytest.mark.real_cli
@pytest.mark.parametrize("provider", PROVIDER_ORDER)
def test_real_cli_fast_lane_gatekeeper_run_finishes_cleanly(tmp_path: Path, provider: str) -> None:
    artifacts = _start_real_loop(
        tmp_path,
        provider=provider,
        workflow_preset="fast_lane",
        completion_mode="gatekeeper",
        max_iters=1,
    )

    _assert_common_run_health(artifacts, expected_status="succeeded")
    summaries = _role_execution_summaries(artifacts, roles={"generator", "verifier"})
    messages = _command_messages(artifacts)

    assert len(summaries) >= 2, _summary_text(artifacts.run_dir)
    assert all(summary["payload"]["ok"] is True for summary in summaries), _summary_text(artifacts.run_dir)
    assert not any("unexpected argument '--cd'" in message for message in messages)
    assert artifacts.terminal_event["payload"].get("iter") == 0
    assert artifacts.terminal_event["payload"].get("reason") in {None, "gatekeeper_passed"}
    _assert_proof_harnesses(artifacts.workdir)


@pytest.mark.real_cli
@pytest.mark.parametrize("provider", PROVIDER_ORDER)
def test_real_cli_fast_lane_rounds_run_resumes_builder_without_abort(tmp_path: Path, provider: str) -> None:
    artifacts = _start_real_loop(
        tmp_path,
        provider=provider,
        workflow_preset="fast_lane",
        completion_mode="rounds",
        max_iters=2,
    )

    _assert_common_run_health(artifacts, expected_status="succeeded")
    summaries = _role_execution_summaries(artifacts, roles={"generator", "verifier"})
    builder_requests = _requests_for_step(artifacts, "builder_step")
    messages = _command_messages(artifacts)

    assert len(summaries) >= 4, _summary_text(artifacts.run_dir)
    assert all(summary["payload"]["ok"] is True for summary in summaries), _summary_text(artifacts.run_dir)
    assert len(builder_requests) >= 2
    assert builder_requests[0]["resume_session_id"] == ""
    assert builder_requests[1]["resume_session_id"]
    assert not any("unexpected argument '--cd'" in message for message in messages)
    assert artifacts.terminal_event["payload"].get("reason") == "rounds_completed"
    _assert_provider_resume_command_shape(artifacts)
    _assert_proof_harnesses(artifacts.workdir)


@pytest.mark.real_cli
def test_real_cli_repair_loop_rounds_keeps_builder_sessions_isolated_by_step(tmp_path: Path) -> None:
    artifacts = _start_real_loop(
        tmp_path,
        provider="codex",
        workflow_preset="repair_loop",
        completion_mode="rounds",
        max_iters=2,
    )

    _assert_common_run_health(artifacts, expected_status="succeeded")
    summaries = _role_execution_summaries(artifacts, roles={"generator", "tester", "challenger", "verifier"})
    builder_requests = _requests_for_step(artifacts, "builder_step")
    repair_requests = _requests_for_step(artifacts, "builder_repair_step")

    assert len(summaries) >= 8, _summary_text(artifacts.run_dir)
    assert all(summary["payload"]["ok"] is True for summary in summaries), _summary_text(artifacts.run_dir)
    assert len(builder_requests) >= 2
    assert len(repair_requests) >= 2
    assert builder_requests[0]["resume_session_id"] == ""
    assert repair_requests[0]["resume_session_id"] == ""
    assert builder_requests[1]["resume_session_id"]
    assert repair_requests[1]["resume_session_id"]
    assert builder_requests[1]["resume_session_id"] != repair_requests[1]["resume_session_id"]
    assert artifacts.terminal_event["payload"].get("reason") == "rounds_completed"
    _assert_provider_resume_command_shape(artifacts)
    _assert_proof_harnesses(artifacts.workdir)
