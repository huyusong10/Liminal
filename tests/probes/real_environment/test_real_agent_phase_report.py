from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
REAL_AGENT_TEST = REPO_ROOT / "tests" / "probes" / "real_environment" / "test_real_agent_adapter_probe.py"


def _load_real_agent_module():
    spec = importlib.util.spec_from_file_location("real_agent_probe", REAL_AGENT_TEST)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def test_real_agent_phase_report_summarizes_real_probe_milestones(tmp_path: Path) -> None:
    module = _load_real_agent_module()
    workdir = tmp_path / "work"
    workdir.mkdir()
    state_dir = workdir / ".loopora"
    run_id = "run_123"
    run_dir = state_dir / "runs" / run_id
    sentinel_log = tmp_path / "sentinel.log"
    candidate = state_dir / "agent_inbox" / "opencode" / "conversation-candidate.yml"
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_text("version: 1\nmetadata:\n  name: phase report\n", encoding="utf-8")
    _write_json(
        state_dir / "alignment_sessions" / "align_ready" / "artifacts" / "validation.json",
        {"ok": True, "error": "", "semantic_lint": {"ok": True, "issues": []}},
    )
    _write_json(
        state_dir / "agent_adapters" / "opencode" / "bindings" / "ctx.json",
        {
            "adapter": "opencode",
            "alignment_status": "running_loop",
            "linked_bundle_id": "bundle_123",
            "linked_loop_id": "loop_123",
            "linked_run_id": run_id,
            "run_path": f"/runs/{run_id}",
            "execution_plane": "agent_native",
            "entry_invocations": [
                {"action": "gen", "entry_source": "opencode_project_command"},
                {"action": "loop", "entry_source": "opencode_project_command"},
            ],
        },
    )
    _write_jsonl(
        run_dir / "events.jsonl",
        [
            {"id": 1, "event_type": "agent_native_step_claimed", "payload": {"step_id": "builder_step"}},
            {"id": 2, "event_type": "agent_native_step_submitted", "payload": {"step_id": "builder_step"}},
            {"id": 3, "event_type": "agent_native_step_claimed", "payload": {"step_id": "gatekeeper_step"}},
            {"id": 4, "event_type": "agent_native_step_submitted", "payload": {"step_id": "gatekeeper_step"}},
            {"id": 5, "event_type": "run_finished", "payload": {"status": "succeeded", "task_verdict_status": "passed"}},
        ],
    )
    _write_json(run_dir / "agent_native" / "state.json", {"status": "completed", "host_dispatches": []})
    _write_json(run_dir / "evidence" / "coverage.json", {"status": "covered", "covered_check_count": 3, "missing_check_ids": []})
    _write_json(run_dir / "evidence" / "task_verdict.json", {"status": "passed", "source": "gatekeeper", "summary": "passed"})
    _write_json(
        run_dir / "iterations" / "iter_000" / "steps" / "01__gatekeeper_step" / "output.normalized.json",
        {"passed": True, "evidence_gate_status": "passed", "evidence_refs": ["ev_000_00_builder_step"]},
    )

    report, report_path = module._write_real_probe_phase_report(
        adapter="opencode",
        workdir=workdir,
        activity_snapshots=[{"running_count": 1, "queued_count": 0, "runs": [{"id": run_id, "status": "awaiting_agent"}]}],
        sentinel_log=sentinel_log,
        command='opencode run --api-key AGENT_PHASE_SECRET_MARKER --model "minimax-token-plan/MiniMax-M2.7" "...prompt..."',
    )

    assert report_path == workdir / ".loopora" / "real-probes" / "real-agent-phase-report.json"
    assert report_path.exists()
    phases = report["phase_statuses"]
    assert phases["candidate_file_created"]["ok"] is True
    assert phases["gen_invocation_observed"]["ok"] is True
    assert phases["ready_validation_observed"]["ok"] is True
    assert phases["loop_invocation_observed"]["ok"] is True
    assert phases["runtime_activity_observed_run"]["ok"] is True
    assert phases["builder_submitted"]["ok"] is True
    assert phases["gatekeeper_submitted"]["ok"] is True
    assert phases["task_verdict_passed"]["ok"] is True
    assert report["diagnostics"]["task_verdict"]["status"] == "passed"
    assert "minimax-token-plan/MiniMax-M2.7" in report["command_preview"]
    assert "AGENT_PHASE_SECRET_MARKER" not in json.dumps(report, ensure_ascii=False)
    assert "--api-key <secret omitted>" in report["command_preview"]
    assert report["model_policy"]["default_model_observed"] is True


def test_real_agent_phase_report_formats_compact_failure(tmp_path: Path) -> None:
    module = _load_real_agent_module()
    report = {
        "adapter": "opencode",
        "workdir": str(tmp_path),
        "phase_statuses": {"candidate_file_created": {"ok": False}},
        "diagnostics": {"binding": {}, "alignment_validations": [], "coverage": {}, "task_verdict": {}, "events_tail": [], "sentinel_log": {}},
    }
    message = module._format_real_probe_diagnostic_failure("boom", report=report, report_path=tmp_path / "phase.json")

    assert "boom" in message
    assert "Real probe phase report:" in message
    assert "candidate_file_created" in message


def test_real_agent_default_model_policy_requires_explicit_override(monkeypatch) -> None:
    module = _load_real_agent_module()
    monkeypatch.delenv(module.REAL_PROBE_MODEL_OVERRIDE_ENV, raising=False)

    with pytest.raises(AssertionError):
        module._assert_real_agent_command_model_policy("opencode", "opencode run --model other-model")

    monkeypatch.setenv(module.REAL_PROBE_MODEL_OVERRIDE_ENV, "1")
    module._assert_real_agent_command_model_policy("opencode", "opencode run --model other-model")
