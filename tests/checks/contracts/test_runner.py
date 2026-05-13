from __future__ import annotations

import json
import math
import os
import shutil
import threading
import time
from pathlib import Path

import pytest

from loopora.branding import state_dir_for_workdir
from loopora.context_flow import (
    StepContextPacketRequest,
    build_step_context_packet,
    output_contract_prompt,
    render_evidence_section,
    render_iteration_section,
    system_prompt_prefix,
)
from loopora.executor import CodexExecutor, ExecutorError, FakeCodexExecutor, build_command_event_payload
from loopora.run_artifacts import RunArtifactLayout
from loopora.run_takeaways import build_run_key_takeaways
from loopora.service import LooporaError, LooporaService
from loopora.service_iteration_reporting import IterationReportContext, IterationSummaryRequest
from loopora.service_types import LooporaConflictError, LooporaNotFoundError
from loopora.service_workflow_runtime import _manifest_prompt_context
from loopora.settings import app_home, configure_logging
from loopora.workflows import prompt_asset_path
import loopora.service_cleanup_diagnostics as cleanup_diagnostics


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _step_outputs_by_archetype(run_dir: Path) -> dict[str, list[dict]]:
    outputs: dict[str, list[dict]] = {}
    for metadata_path in sorted(run_dir.glob("iterations/iter_*/steps/*/metadata.json")):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        output_path = metadata_path.parent / "output.normalized.json"
        outputs.setdefault(metadata["archetype"], []).append(
            {
                "metadata": metadata,
                "output": json.loads(output_path.read_text(encoding="utf-8")),
                "step_dir": metadata_path.parent,
            }
        )
    return outputs


def _wait_for_terminal_run(service: LooporaService, run_id: str, *, timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    current = service.get_run(run_id)
    while time.time() < deadline:
        current = service.get_run(run_id)
        if current["status"] in {"succeeded", "failed", "stopped"}:
            return current
        time.sleep(0.05)
    return current


def _join_async_run(service: LooporaService, run_id: str, *, timeout: float = 5.0) -> None:
    thread = service._threads.get(run_id)
    if thread is not None:
        thread.join(timeout=timeout)
    service.get_run(run_id)


def test_iteration_reporting_requires_literal_passed_booleans(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    compiled_spec = {
        "checks": [{"id": "check_1", "title": "Main check"}],
        "check_mode": "specified",
    }
    tester_result = service._enrich_tester_result(
        {
            "execution_summary": {"total_checks": 1, "passed": 1, "failed": 0, "errored": 0, "total_duration_ms": 1},
            "check_results": [{"id": "check_1", "title": "Main check", "status": "passed", "notes": "ok"}],
            "dynamic_checks": [],
            "tester_observations": "",
        }
    )
    verifier_result = service._enrich_verifier_result(
        {
            "passed": "true",
            "decision_summary": "Raw string pass should not be trusted.",
            "composite_score": "1.0",
            "metric_scores": {
                "check_pass_rate": {"value": 1.0, "threshold": 1.0, "passed": True},
                "quality_score": {"value": 1.0, "threshold": 0.9, "passed": "true"},
            },
            "failed_check_ids": [],
            "hard_constraint_violations": [],
            "priority_failures": [],
            "feedback_to_generator": "",
            "evidence_refs": [],
        },
        compiled_spec,
        tester_result,
    )

    assert verifier_result["passed"] is False
    assert verifier_result["composite_score"] == 0.0
    assert verifier_result["failing_metrics"] == [{"name": "quality_score", "value": 1.0, "threshold": 0.9}]
    assert "Task verdict is not ready" in verifier_result["decision_summary"]

    report = IterationReportContext(
        iter_id=0,
        generator_result={"attempted": "", "summary": "", "assumption": "", "abandoned": "", "changed_files": []},
        tester_result=tester_result,
        verifier_result=verifier_result,
        stagnation={
            "stagnation_mode": "none",
            "recent_composites": ["0.9", 0.8, True],
            "recent_deltas": ["0.1", 0.2, False],
            "consecutive_low_delta": "2",
        },
        generator_mode="default",
        tester_mode="default",
        verifier_mode="default",
        previous_composite=None,
    )
    log_entry = service._build_iteration_log_entry(report)
    summary = service._build_summary(
        IterationSummaryRequest(
            run={
                "workdir": str(sample_workdir),
                "completion_mode": "gatekeeper",
                "iteration_interval_seconds": 0.0,
            },
            compiled_spec=compiled_spec,
            report=report,
        )
    )

    assert log_entry["score"]["passed"] is False
    assert log_entry["verifier"]["passed"] is False
    assert log_entry["stagnation"]["recent_composites"] == [0.8]
    assert log_entry["stagnation"]["recent_deltas"] == [0.2]
    assert log_entry["stagnation"]["consecutive_low_delta"] == 0
    assert "- Passed: `False`" in summary
    assert "Still iterating." in summary
    assert "All checks passed in this iteration." not in summary


def test_gatekeeper_composite_score_requires_literal_number(service_factory) -> None:
    service = service_factory(scenario="success")

    gatekeeper_result = service._coerce_gatekeeper_output(
        {
            "passed": False,
            "decision_summary": "Blocked with a malformed score.",
            "composite_score": "0.95",
            "blocking_issues": ["missing proof"],
            "evidence_refs": [],
        }
    )

    assert gatekeeper_result["passed"] is False
    assert gatekeeper_result["composite_score"] == 0.0


def test_asset_call_does_not_classify_plain_unknown_validation_errors_as_not_found(service_factory) -> None:
    service = service_factory(scenario="success")

    with pytest.raises(LooporaError, match="unknown is just part of this validation message") as exc_info:
        service._asset_call(lambda: (_ for _ in ()).throw(ValueError("unknown is just part of this validation message")))

    assert not isinstance(exc_info.value, LooporaNotFoundError)


def test_loop_delete_logs_artifact_cleanup_failure(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
    monkeypatch,
) -> None:
    service = service_factory(scenario="success")
    loop = _create_loop(service, sample_spec_file, sample_workdir)
    run = service.rerun(loop["id"])
    log_calls: list[dict] = []

    def fail_rmtree(path: Path) -> None:
        if Path(path) == Path(run["runs_dir"]):
            raise OSError("run dir locked")
        return

    def capture_log_event(_logger, _level, event, message, **context):
        log_calls.append({"event": event, "message": message, "context": context})

    monkeypatch.setattr(cleanup_diagnostics.shutil, "rmtree", fail_rmtree)
    monkeypatch.setattr(cleanup_diagnostics, "log_event", capture_log_event)
    result = service.delete_loop(loop["id"])

    assert result["id"] == loop["id"]
    assert any(
        call["event"] == "service.cleanup.failed"
        and call["context"].get("operation") == "loop_artifact_delete"
        and call["context"].get("owner_id") == loop["id"]
        for call in log_calls
    )


def test_loop_delete_logs_registry_mark_failure_without_failing(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
    monkeypatch,
) -> None:
    service = service_factory(scenario="success")
    loop = _create_loop(service, sample_spec_file, sample_workdir)
    run = service.rerun(loop["id"])
    log_calls: list[dict] = []

    def fail_registry_mark(*, path: Path, state: str) -> int:
        assert state in {"cleaned", "orphaned"}
        if Path(path) == Path(run["runs_dir"]):
            raise RuntimeError("registry write failed")
        return 1

    def capture_log_event(_logger, _level, event, message, **context):
        log_calls.append({"event": event, "message": message, "context": context})

    monkeypatch.setattr(service.repository, "mark_local_asset_root_state_by_path", fail_registry_mark)
    monkeypatch.setattr(cleanup_diagnostics, "log_event", capture_log_event)
    result = service.delete_loop(loop["id"])

    assert result["id"] == loop["id"]
    assert any(
        call["event"] == "service.cleanup.failed"
        and call["context"].get("operation") == "loop_artifact_delete_registry_mark"
        and call["context"].get("owner_id") == loop["id"]
        for call in log_calls
    )


def _create_loop(
    service,
    sample_spec_file: Path,
    sample_workdir: Path,
    name: str = "Demo Loop",
    *,
    workflow: dict | None = None,
    **overrides,
) -> dict:
    payload = {
        "name": name,
        "spec_path": sample_spec_file,
        "workdir": sample_workdir,
        "model": "gpt-5.4",
        "reasoning_effort": "medium",
        "max_iters": 3,
        "max_role_retries": 1,
        "delta_threshold": 0.005,
        "trigger_window": 2,
        "regression_window": 2,
        "role_models": {},
        "workflow": workflow,
    }
    payload.update(overrides)
    return service.create_loop(**payload)


@pytest.mark.parametrize(
    "case",
    (
        ("iteration_interval_seconds", math.nan, "iteration_interval_seconds must be a finite number"),
        ("delta_threshold", math.inf, "delta_threshold must be a finite number"),
        ("max_iters", math.inf, "max_iters must be a finite number"),
        ("max_iters", False, "max_iters must be a finite number"),
        ("max_iters", 1.5, "max_iters must be an integer"),
        ("trigger_window", 1.5, "trigger_window must be an integer"),
        ("delta_threshold", -0.1, "delta_threshold must be >= 0"),
    ),
)
def test_create_loop_rejects_invalid_runtime_numbers(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
    case: tuple[str, object, str],
) -> None:
    service = service_factory(scenario="success")
    field_name, value, error_text = case

    with pytest.raises(LooporaError, match=error_text):
        _create_loop(service, sample_spec_file, sample_workdir, **{field_name: value})


def _force_run_into_legacy_mode(service: LooporaService, run_id: str) -> dict:
    with service.repository.transaction() as connection:
        connection.execute(
            "UPDATE loop_runs SET workflow_json = ? WHERE id = ?",
            (json.dumps({}, ensure_ascii=False), run_id),
        )
    return service.get_run(run_id)


def _corrupt_loop_prompt_artifact(loop: dict, prompt_ref: str) -> None:
    prompt_dir = state_dir_for_workdir(Path(loop["workdir"])) / "loops" / loop["id"] / "prompts"
    prompt_asset_path(prompt_dir, prompt_ref).write_bytes(b"\xff")


def _corrupt_run_prompt_artifact(run: dict, prompt_ref: str) -> None:
    layout = RunArtifactLayout(Path(run["runs_dir"]))
    prompt_asset_path(layout.contract_prompts_dir, prompt_ref).write_bytes(b"\xff")


def _assert_evidence_manifest(run_dir: Path) -> None:
    manifest = json.loads((run_dir / "evidence" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["manifest_path"] == "evidence/manifest.json"
    assert manifest["ledger_path"] == "evidence/ledger.jsonl"
    assert manifest["coverage_path"] == "evidence/coverage.json"
    assert manifest["claim_count"] >= 3
    assert manifest["artifact_backed_claim_count"] == manifest["claim_count"]
    assert manifest["run_artifact_claim_count"] >= 1
    assert all(claim["producer"]["step_id"] for claim in manifest["claims"])


def test_successful_run_writes_expected_artifacts(service_factory, sample_spec_file: Path, sample_workdir: Path) -> None:
    service = service_factory(scenario="success")
    loop = _create_loop(service, sample_spec_file, sample_workdir)

    run = service.rerun(loop["id"])

    run_dir = Path(run["runs_dir"])
    step_outputs = _step_outputs_by_archetype(run_dir)
    assert run["status"] == "succeeded"
    assert (run_dir / "timeline" / "events.jsonl").exists()
    assert (run_dir / "events.jsonl").exists()
    assert (run_dir / "timeline" / "stagnation.json").exists()
    assert (run_dir / "stagnation.json").exists()
    assert (run_dir / "evidence" / "ledger.jsonl").exists()
    assert (run_dir / "evidence" / "coverage.json").exists()
    assert (run_dir / "evidence" / "manifest.json").exists()
    assert (run_dir / "evidence" / "task_verdict.json").exists()
    assert (run_dir / "contract" / "compiled_spec.json").exists()
    assert (run_dir / "contract" / "workflow.json").exists()
    assert (run_dir / "contract" / "run_contract.json").exists()
    assert (run_dir / "context" / "latest_state.json").exists()
    assert (run_dir / "context" / "latest_iteration_summary.json").exists()
    assert (sample_workdir / ".loopora" / "loops" / loop["id"] / "compiled_spec.json").exists()
    frozen_workflow = json.loads((run_dir / "contract" / "workflow.json").read_text(encoding="utf-8"))
    run_contract = json.loads((run_dir / "contract" / "run_contract.json").read_text(encoding="utf-8"))
    coverage = json.loads((run_dir / "evidence" / "coverage.json").read_text(encoding="utf-8"))
    assert coverage["coverage_path"] == "evidence/coverage.json"
    assert coverage["ledger_path"] == "evidence/ledger.jsonl"
    assert coverage["status"] in {"covered", "weak"}
    assert coverage["targets"]
    _assert_evidence_manifest(run_dir)
    assert run["run_status"] == "succeeded"
    assert run["task_verdict"]["status"] == "passed"
    assert run["task_verdict"]["source"] == "gatekeeper"
    assert json.loads((run_dir / "evidence" / "task_verdict.json").read_text(encoding="utf-8")) == run["task_verdict"]
    assert run_contract["workflow"]["steps"] == [
        {
            "id": step["id"],
            "role_id": step["role_id"],
            "on_pass": step.get("on_pass", ""),
            "model": step.get("model", ""),
            "inherit_session": bool(step.get("inherit_session")),
            "extra_cli_args": step.get("extra_cli_args", ""),
            "parallel_group": step.get("parallel_group", ""),
            "inputs": step.get("inputs", {}),
            "action_policy": step.get("action_policy", {}),
        }
        for step in frozen_workflow["steps"]
    ]
    role_requests = _read_jsonl(run_dir / "context" / "role_requests.jsonl")
    builder_request = next(item for item in role_requests if item["role_archetype"] == "builder")
    inspector_request = next(item for item in role_requests if item["role_archetype"] == "inspector")
    gatekeeper_request = next(item for item in role_requests if item["role_archetype"] == "gatekeeper")
    assert builder_request["sandbox"] == "workspace-write"
    assert inspector_request["sandbox"] == "read-only"
    assert gatekeeper_request["sandbox"] == "read-only"
    assert "action_policy" in builder_request["extra_context_keys"]
    assert step_outputs["inspector"]
    assert step_outputs["gatekeeper"]
    assert any((item["step_dir"] / "prompt.md").exists() for item in step_outputs["inspector"])
    assert any((item["step_dir"] / "prompt.md").exists() for item in step_outputs["gatekeeper"])
    summary = (run_dir / "summary.md").read_text(encoding="utf-8")
    assert "All checks passed in this iteration." in summary
    assert "evidence/ledger.jsonl" in summary
    assert "timeline/iterations.jsonl" in summary


def test_builder_declared_workspace_artifacts_are_written_to_evidence_refs(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    class ChangedFileExecutor(FakeCodexExecutor):
        def _build_payload(self, request):
            payload = super()._build_payload(request)
            if request.role_archetype == "builder":
                proof_path = request.workdir / "tests" / "evidence" / "proof.json"
                proof_path.parent.mkdir(parents=True, exist_ok=True)
                proof_path.write_text('{"ok": true}\n', encoding="utf-8")
                (request.workdir / "progress.md").write_text("# Progress\n\nChanged.\n", encoding="utf-8")
                payload["changed_files"] = ["progress.md", "missing.md", "../outside.md"]
                payload["proof_files"] = ["tests/evidence/proof.json"]
            return payload

    service = service_factory(scenario="success")
    service.executor_factory = lambda: ChangedFileExecutor(scenario="success")
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Workspace Artifact Loop")

    run = service.rerun(loop["id"])

    run_dir = Path(run["runs_dir"])
    ledger = _read_jsonl(run_dir / "evidence" / "ledger.jsonl")
    builder_entry = next(item for item in ledger if item["archetype"] == "builder")
    workspace_refs = [item for item in builder_entry["artifact_refs"] if item["kind"] == "workspace"]
    assert {item["workspace_path"] for item in workspace_refs} == {
        "progress.md",
        "tests/evidence/proof.json",
    }
    assert all(Path(item["absolute_path"]).is_absolute() for item in workspace_refs)
    role_requests = _read_jsonl(run_dir / "context" / "role_requests.jsonl")
    gatekeeper_request = next(item for item in role_requests if item["role_archetype"] == "gatekeeper")
    gatekeeper_prompt = (run_dir / gatekeeper_request["prompt_path"]).read_text(encoding="utf-8")
    assert "changed-file:progress.md" in gatekeeper_prompt
    assert "proof-file:tests/evidence/proof.json" in gatekeeper_prompt
    assert f"absolute: {(sample_workdir / 'tests' / 'evidence' / 'proof.json').resolve()}" in gatekeeper_prompt
    assert "Manifest: evidence/manifest.json" in gatekeeper_prompt
    assert "Proof strength:" in gatekeeper_prompt
    assert "proof_status=direct_proof" in gatekeeper_prompt
    assert "workspace_backed=true" in gatekeeper_prompt
    manifest = json.loads((run_dir / "evidence" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["direct_proof_claim_count"] >= 1
    builder_claim = next(item for item in manifest["claims"] if item["producer"]["archetype"] == "builder")
    assert builder_claim["verification_status"] == "direct_proof"
    assert builder_claim["workspace_backed"] is True
    assert builder_claim["reproducible"] is True
    proof_ref = next(item for item in builder_claim["artifact_refs"] if item["label"] == "proof-file:tests/evidence/proof.json")
    assert proof_ref["exists"] is True
    assert proof_ref["hash_status"] == "sha256"
    assert proof_ref["sha256"]


def test_manifest_prompt_context_does_not_promote_string_booleans(tmp_path: Path) -> None:
    layout = RunArtifactLayout(tmp_path / "run_prompt")
    layout.initialize()
    (layout.evidence_manifest_path).write_text(
        json.dumps(
            {
                "claims": [
                    {
                        "id": "ev_string_bool",
                        "verification_status": "direct_proof",
                        "measured_evidence": "true",
                        "concrete_evidence_claim_count": True,
                        "artifact_count": 1,
                        "artifact_backed": "true",
                        "workspace_backed": "true",
                        "reproducible": "true",
                        "coverage_targets": [
                            {
                                "id": "done_when.check",
                                "kind": "done_when",
                                "label": "Done check",
                                "reported_status": "covered",
                                "coverage_status": "covered",
                                "required": "true",
                                "evidence_refs": ["ev_support"],
                            },
                            {
                                "id": "evidence_preference.pref_001",
                                "kind": "evidence_preference",
                                "label": "Evidence preference",
                                "reported_status": "weak",
                                "coverage_status": "weak",
                                "required": "true",
                                "evidence_refs": [],
                            },
                            "gatekeeper.finish",
                        ],
                    }
                ],
                "problems": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    _summary, claims = _manifest_prompt_context(layout, ["ev_string_bool"])

    assert claims[0]["measured_evidence"] is False
    assert claims[0]["concrete_evidence_claim_count"] == 0
    assert claims[0]["artifact_backed"] is False
    assert claims[0]["workspace_backed"] is False
    assert claims[0]["reproducible"] is False
    assert claims[0]["coverage_targets"][0] == {
        "id": "done_when.check",
        "kind": "done_when",
        "label": "Done check",
        "reported_status": "covered",
        "coverage_status": "covered",
        "required": True,
        "evidence_refs": ["ev_support"],
    }
    assert claims[0]["coverage_targets"][1]["required"] is False
    assert claims[0]["coverage_targets"][2]["id"] == "gatekeeper.finish"
    assert claims[0]["coverage_targets"][2]["required"] is True


def test_step_context_packet_preserves_manifest_claim_target_trace(tmp_path: Path) -> None:
    layout = RunArtifactLayout(tmp_path / "run_prompt")
    layout.initialize()
    packet = build_step_context_packet(
        StepContextPacketRequest(
            run_contract={"compiled_spec": {}, "workflow": {"preset": "custom"}, "completion_mode": "gatekeeper"},
            layout=layout,
            iter_id=0,
            step={"id": "gatekeeper_step", "role_id": "gatekeeper"},
            step_order=1,
            role={"id": "gatekeeper", "name": "GateKeeper", "archetype": "gatekeeper"},
            execution_settings={},
            immediate_previous_step=None,
            completed_steps_this_iteration=[],
            previous_iteration_same_step=None,
            previous_iteration_same_role=None,
            previous_iteration_summary=None,
            previous_composite=None,
            stagnation_mode="none",
            evidence_items=[
                {
                    "id": "ev_target",
                    "role_name": "Inspector",
                    "archetype": "inspector",
                    "result": "passed",
                    "claim": "Inspector covered the target.",
                    "related_evidence_ids": [],
                    "coverage_results": [],
                    "artifact_refs": [],
                }
            ],
            evidence_known_ids=["ev_target"],
            evidence_manifest_summary={"claim_count": 1, "direct_proof_claim_count": 1},
            evidence_manifest_claims=[
                {
                    "id": "ev_target",
                    "verification_status": "direct_proof",
                    "measured_evidence": True,
                    "concrete_evidence_claim_count": 1,
                    "artifact_count": 1,
                    "artifact_backed": True,
                    "workspace_backed": True,
                    "reproducible": True,
                    "coverage_targets": [
                        {
                            "id": "done_when.check",
                            "kind": "done_when",
                            "label": "Done check",
                            "reported_status": "covered",
                            "coverage_status": "covered",
                            "required": "true",
                            "evidence_refs": ["ev_target"],
                        }
                    ],
                }
            ],
        )
    )

    target_trace = packet["evidence"]["manifest_claims"][0]["coverage_targets"][0]
    assert target_trace == {
        "id": "done_when.check",
        "kind": "done_when",
        "label": "Done check",
        "reported_status": "covered",
        "coverage_status": "covered",
        "required": True,
        "evidence_refs": ["ev_target"],
    }
    prompt_section = render_evidence_section(packet["evidence"])
    assert '"id": "done_when.check"' in prompt_section
    assert '"required": true' in prompt_section


def test_command_events_do_not_persist_prompt_or_secret_markers(
    service_factory,
    sample_workdir: Path,
    tmp_path: Path,
) -> None:
    prompt_marker = "RUN_EVENT_PROMPT_SECRET_MARKER"
    token_marker = "RUN_EVENT_TOKEN_SECRET_MARKER"
    spec_path = tmp_path / "sensitive-spec.md"
    spec_path.write_text(
        f"""# Task

Ship the requested behavior with {prompt_marker}.

# Done When

- The primary experience completes successfully.

# Guardrails

- Keep changes focused.

# Success Surface

- The result remains easy for the next role to verify.

# Fake Done

- A happy-path-only result that leaves the edge path unverifiable.

# Evidence Preferences

- Prefer structured run artifacts and reproducible checks over role self-report.
""",
        encoding="utf-8",
    )

    class CommandEventExecutor(FakeCodexExecutor):
        def execute(self, request, emit_event, should_stop, set_child_pid):
            emit_event(
                "codex_event",
                build_command_event_payload(
                    request,
                    [
                        "codex",
                        "exec",
                        "--auth-token",
                        token_marker,
                        request.prompt,
                    ],
                ),
            )
            return super().execute(request, emit_event, should_stop, set_child_pid)

    service = service_factory(scenario="success")
    service.executor_factory = lambda: CommandEventExecutor(scenario="success")
    loop = _create_loop(service, spec_path, sample_workdir, max_iters=1)

    run = service.rerun(loop["id"])
    events = service.repository.list_events(run["id"])
    timeline_events = (Path(run["runs_dir"]) / "timeline" / "events.jsonl").read_text(encoding="utf-8")
    event_text = json.dumps(events, ensure_ascii=False)
    command_payloads = [event["payload"] for event in events if event["event_type"] == "codex_event" and event["payload"].get("type") == "command"]

    assert command_payloads
    assert all(payload["prompt_omitted"] for payload in command_payloads)
    assert all(payload["token_omitted"] for payload in command_payloads)
    assert prompt_marker not in event_text
    assert token_marker not in event_text
    assert prompt_marker not in timeline_events
    assert token_marker not in timeline_events


def test_successful_run_enriches_logs_and_role_outputs(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Verbose Logs Loop")

    run = service.rerun(loop["id"])

    run_dir = Path(run["runs_dir"])
    step_outputs = _step_outputs_by_archetype(run_dir)
    builder_output = step_outputs["builder"][-1]["output"]
    tester_output = step_outputs["inspector"][-1]["output"]
    verifier_verdict = step_outputs["gatekeeper"][-1]["output"]
    metrics_history = _read_jsonl(run_dir / "timeline" / "metrics.jsonl")
    evidence_ledger = _read_jsonl(run_dir / "evidence" / "ledger.jsonl")
    iteration_log = _read_jsonl(run_dir / "iteration_log.jsonl")
    latest_iteration_summary = json.loads((run_dir / "context" / "latest_iteration_summary.json").read_text(encoding="utf-8"))

    assert "frozen task contract" in builder_output["attempted"]
    assert "proof surface" in builder_output["summary"]
    assert tester_output["status_counts"]["overall"]["passed"] >= 1
    assert "failed_items" in tester_output
    assert "frozen run contract" in tester_output["tester_observations"]
    assert "Blocking or Unproven" in tester_output["tester_observations"]
    assert verifier_verdict["decision_summary"]
    assert "run lifecycle alone is not proof" in verifier_verdict["decision_summary"]
    assert verifier_verdict["evidence_refs"]
    assert verifier_verdict["evidence_claims"]
    assert "Proven:" in verifier_verdict["evidence_claims"][0]
    assert "run status separate from task verdict" in verifier_verdict["evidence_claims"][0]
    assert verifier_verdict["evidence_gate_status"] == "passed"
    assert "failing_metrics" in verifier_verdict
    assert "next_actions" in verifier_verdict
    assert metrics_history[-1]["stagnation_mode"] in {"none", "plateau", "regression"}
    assert "score_delta" in metrics_history[-1]
    assert metrics_history[-1]["evidence_refs"] == verifier_verdict["evidence_refs"]
    assert evidence_ledger
    assert {entry["archetype"] for entry in evidence_ledger} >= {"inspector", "gatekeeper"}
    assert {entry["evidence_kind"] for entry in evidence_ledger} >= {"inspection", "verdict"}
    assert step_outputs["inspector"][-1]["metadata"]["archetype"] == "inspector"

    complete_entries = [entry for entry in iteration_log if entry["phase"] == "complete"]
    assert complete_entries
    latest_entry = complete_entries[-1]
    assert latest_entry["generator"]["changed_files"] == []
    assert latest_entry["tester"]["status_counts"]["overall"]["passed"] >= 1
    assert latest_entry["verifier"]["decision_summary"]
    assert latest_entry["score"]["composite"] == verifier_verdict["composite_score"]
    assert latest_iteration_summary["score"]["composite"] == verifier_verdict["composite_score"]
    assert latest_iteration_summary["step_handoffs"]
    assert all(handoff["evidence_refs"] for handoff in latest_iteration_summary["step_handoffs"])
    assert all("parallel_group" in item for item in latest_iteration_summary["workflow"])


def test_coverage_results_cover_advisory_targets(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    class CoverageExecutor(FakeCodexExecutor):
        def _build_payload(self, request):
            payload = super()._build_payload(request)
            if request.role_archetype == "inspector":
                targets = list((request.extra_context.get("compiled_spec") or {}).get("coverage_targets") or [])
                payload["coverage_results"] = [
                    {
                        "target_id": target["id"],
                        "status": "covered",
                        "evidence_refs": [],
                        "note": "Inspector explicitly verified this advisory target.",
                    }
                    for target in targets
                    if target.get("kind") in {"fake_done", "evidence_preference"}
                ]
            return payload

    service = service_factory(scenario="success")
    service.executor_factory = lambda: CoverageExecutor(scenario="success")
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Coverage Target Loop")

    run = service.rerun(loop["id"])

    run_dir = Path(run["runs_dir"])
    coverage = json.loads((run_dir / "evidence" / "coverage.json").read_text(encoding="utf-8"))
    evidence_ledger = _read_jsonl(run_dir / "evidence" / "ledger.jsonl")
    target_status = {target["id"]: target["status"] for target in coverage["targets"]}

    assert run["status"] == "succeeded"
    assert coverage["status"] == "covered"
    assert target_status["fake_done.risk_001"] == "covered"
    assert target_status["evidence_preference.pref_001"] == "covered"
    assert any("target:fake_done.risk_001:covered" in entry["verifies"] for entry in evidence_ledger)
    assert any("target:evidence_preference.pref_001:covered" in entry["verifies"] for entry in evidence_ledger)


def test_gatekeeper_coverage_results_cover_advisory_targets(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    class GatekeeperCoverageExecutor(CodexExecutor):
        def execute(self, request, _emit_event, _should_stop, set_child_pid):
            set_child_pid(None)
            if request.role_archetype == "inspector":
                payload = {
                    "execution_summary": {
                        "total_checks": 2,
                        "passed": 2,
                        "failed": 0,
                        "errored": 0,
                        "total_duration_ms": 50,
                    },
                    "check_results": [
                        {
                            "id": "check_001",
                            "title": "Primary experience",
                            "status": "passed",
                            "notes": "Primary experience is covered.",
                        },
                        {
                            "id": "check_002",
                            "title": "Edge path",
                            "status": "passed",
                            "notes": "Edge path is covered.",
                        },
                    ],
                    "dynamic_checks": [],
                    "tester_observations": "Required Done When checks are covered.",
                    "coverage_results": [],
                }
            else:
                context_packet = request.extra_context["context_packet"]
                evidence_refs = [item["id"] for item in context_packet["evidence"]["items"]]
                targets = list((request.extra_context.get("compiled_spec") or {}).get("coverage_targets") or [])
                payload = {
                    "passed": True,
                    "decision_summary": "GateKeeper explicitly covered advisory targets before closing.",
                    "feedback_to_builder": "",
                    "blocking_issues": [],
                    "metrics": [
                        {"name": "quality_score", "value": 1.0, "threshold": 0.9, "passed": True},
                    ],
                    "failed_check_ids": [],
                    "priority_failures": [],
                    "composite_score": 1.0,
                    "evidence_refs": evidence_refs,
                    "evidence_claims": ["Inspector evidence covered the required checks."],
                    "residual_risks": [],
                    "coverage_results": [
                        {
                            "target_id": target["id"],
                            "status": "covered",
                            "evidence_refs": evidence_refs,
                            "note": "GateKeeper accepted this advisory target from the supporting inspection.",
                        }
                        for target in targets
                        if target.get("kind") in {"fake_done", "evidence_preference"}
                    ],
                }
            request.output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return payload

    service = service_factory(scenario="success")
    service.executor_factory = GatekeeperCoverageExecutor
    workflow = {
        "version": 1,
        "roles": [
            {"id": "inspector", "name": "Inspector", "archetype": "inspector", "prompt_ref": "inspector.md"},
            {"id": "gatekeeper", "name": "GateKeeper", "archetype": "gatekeeper", "prompt_ref": "gatekeeper.md"},
        ],
        "steps": [
            {"id": "inspector_step", "role_id": "inspector"},
            {"id": "gatekeeper_step", "role_id": "gatekeeper", "on_pass": "finish_run"},
        ],
    }
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="GateKeeper Coverage Target Loop", workflow=workflow)

    run = service.rerun(loop["id"])

    run_dir = Path(run["runs_dir"])
    coverage = json.loads((run_dir / "evidence" / "coverage.json").read_text(encoding="utf-8"))
    evidence_ledger = _read_jsonl(run_dir / "evidence" / "ledger.jsonl")
    target_status = {target["id"]: target["status"] for target in coverage["targets"]}
    gatekeeper_entry = next(entry for entry in evidence_ledger if entry["archetype"] == "gatekeeper")

    assert run["status"] == "succeeded"
    assert coverage["status"] == "covered"
    assert target_status["fake_done.risk_001"] == "covered"
    assert target_status["evidence_preference.pref_001"] == "covered"
    assert "target:fake_done.risk_001:covered" in gatekeeper_entry["verifies"]
    assert "target:evidence_preference.pref_001:covered" in gatekeeper_entry["verifies"]
    assert {item["target_id"] for item in gatekeeper_entry["coverage_results"]} >= {
        "fake_done.risk_001",
        "evidence_preference.pref_001",
    }
    related_refs = set(gatekeeper_entry["related_evidence_ids"])
    assert all(item["evidence_refs"] for item in gatekeeper_entry["coverage_results"])
    assert all(set(item["evidence_refs"]) <= related_refs for item in gatekeeper_entry["coverage_results"])


def test_successful_run_emits_structured_service_logs(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    configure_logging()
    service = service_factory(scenario="success")
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Diagnostic Loop")

    run = service.rerun(loop["id"])

    run_records = [json.loads(line) for line in (app_home() / "logs" / "service.log").read_text(encoding="utf-8").splitlines() if line.strip()]
    run_records = [record for record in run_records if record.get("run_id") == run["id"]]
    events = {record["event"] for record in run_records}

    assert "service.run.execution.started" in events
    assert "service.workflow.execution.started" in events
    assert "service.workflow.iteration.started" in events
    assert "service.workflow.step.completed" in events
    assert "service.run.execution.finished" in events
    finished_record = next(record for record in run_records if record["event"] == "service.run.execution.finished")
    assert finished_record["loop_id"] == loop["id"]


def test_run_persists_role_request_snapshots_and_iteration_handoff(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="plateau")
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Prompt Snapshot Loop")

    run = service.rerun(loop["id"])

    run_dir = Path(run["runs_dir"])
    role_requests = _read_jsonl(run_dir / "context" / "role_requests.jsonl")

    assert role_requests
    generator_requests = [item for item in role_requests if item["role"] == "generator"]
    assert generator_requests
    second_generator = next(item for item in generator_requests if item["iter"] == 1)
    assert "context_packet" in second_generator["extra_context_keys"]
    assert second_generator["context_summary"]["previous_iteration_summary"]["composite"] == 0.62

    prompt_path = run_dir / second_generator["prompt_path"]
    prompt_text = prompt_path.read_text(encoding="utf-8")
    assert "This is iteration 2." in prompt_text
    assert "Previous iteration summary:" in prompt_text
    assert "Repair the smallest Blocking or Unproven gap without lowering the frozen contract." in prompt_text
    assert "Immediate upstream handoff" in prompt_text


def test_loop_projection_degrades_when_prompt_artifact_is_corrupt(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Corrupt Prompt Projection Loop")
    prompt_ref = next(iter(loop["prompt_files"]))
    _corrupt_loop_prompt_artifact(loop, prompt_ref)

    listed_loop = next(item for item in service.list_loops() if item["id"] == loop["id"])
    hydrated_loop = service.get_loop(loop["id"])

    assert listed_loop["prompt_files"] == {}
    assert hydrated_loop["prompt_files"] == {}


def test_start_run_reports_corrupt_loop_prompt_artifact_as_domain_error(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Corrupt Prompt Start Loop")
    prompt_ref = next(iter(loop["prompt_files"]))
    _corrupt_loop_prompt_artifact(loop, prompt_ref)
    runs_root = state_dir_for_workdir(sample_workdir) / "runs"

    with pytest.raises(LooporaError, match="UTF-8 encoded Markdown"):
        service.start_run(loop["id"])
    assert not runs_root.exists() or not list(runs_root.iterdir())


def test_start_run_cleans_prepared_run_dir_when_registration_fails(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
    monkeypatch,
) -> None:
    service = service_factory(scenario="success")
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Registration Failure Cleanup Loop")
    captured: dict[str, Path] = {}

    def fail_create_run(payload: dict) -> dict:
        captured["run_dir"] = Path(payload["runs_dir"])
        raise LooporaConflictError("forced active run conflict")

    monkeypatch.setattr(service.repository, "create_run", fail_create_run)

    with pytest.raises(LooporaConflictError, match="forced active run conflict"):
        service.start_run(loop["id"])

    assert captured["run_dir"].parent == state_dir_for_workdir(sample_workdir) / "runs"
    assert not captured["run_dir"].exists()


def test_execute_run_fails_readably_when_run_prompt_artifact_is_corrupt(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Corrupt Run Prompt Loop")
    run = service.start_run(loop["id"])
    prompt_ref = next(iter(run["prompt_files"]))
    _corrupt_run_prompt_artifact(run, prompt_ref)

    failed_run = service.execute_run(run["id"])

    assert failed_run["status"] == "failed"
    assert "UTF-8 encoded Markdown" in failed_run["error_message"]
    assert failed_run["prompt_files"] == {}


def test_role_request_prompt_renders_workspace_visible_artifact_refs(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="plateau")
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Artifact Ref Loop")

    run = service.rerun(loop["id"])
    role_requests = _read_jsonl(Path(run["runs_dir"]) / "context" / "role_requests.jsonl")
    second_generator = next(item for item in role_requests if item["role"] == "generator" and item["iter"] == 1)
    prompt_path = Path(run["runs_dir"]) / second_generator["prompt_path"]
    prompt_text = prompt_path.read_text(encoding="utf-8")

    assert f".loopora/runs/{run['id']}/contract/run_contract.json" in prompt_text
    assert "run-local: contract/run_contract.json" in prompt_text
    assert f"absolute: {(Path(run['runs_dir']) / 'contract' / 'run_contract.json').resolve()}" in prompt_text


def test_workflow_iteration_context_recovers_corrupt_latest_state(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
    monkeypatch,
) -> None:
    service = service_factory(scenario="plateau")
    original_persist_iteration_context = service._persist_iteration_context
    persist_calls = 0

    def corrupt_latest_state_before_second_persist(request):
        nonlocal persist_calls
        persist_calls += 1
        if persist_calls == 2:
            request.layout.latest_state_path.write_text("{", encoding="utf-8")
        return original_persist_iteration_context(request)

    monkeypatch.setattr(service, "_persist_iteration_context", corrupt_latest_state_before_second_persist)
    loop = _create_loop(
        service,
        sample_spec_file,
        sample_workdir,
        name="Corrupt Latest State Loop",
        max_iters=2,
    )

    run = service.rerun(loop["id"])
    latest_state = json.loads((Path(run["runs_dir"]) / "context" / "latest_state.json").read_text(encoding="utf-8"))

    assert persist_calls == 2
    assert run["status"] == "failed"
    assert "Expecting" not in str(run.get("error_message") or "")
    assert latest_state["latest_iteration"] == 1


def test_workflow_run_recovers_corrupt_stagnation_projection(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Corrupt Stagnation Loop")
    queued = service.start_run(loop["id"])
    layout = RunArtifactLayout(Path(queued["runs_dir"]))
    layout.timeline_stagnation_path.write_text("{", encoding="utf-8")

    run = service.execute_run(queued["id"])
    stagnation = json.loads(layout.timeline_stagnation_path.read_text(encoding="utf-8"))

    assert run["status"] == "succeeded"
    assert "Expecting" not in str(run.get("error_message") or "")
    assert stagnation["stagnation_mode"] == "none"


def test_workflow_context_does_not_promote_corrupt_stagnation_counts(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    recorded_counts: list[dict] = []

    class CountRecordingExecutor(CodexExecutor):
        def execute(self, request, _emit_event, _should_stop, set_child_pid):
            set_child_pid(None)
            recorded_counts.append(
                {
                    "covered_check_count": request.extra_context["covered_check_count"],
                    "missing_check_count": request.extra_context["missing_check_count"],
                    "consecutive_no_required_coverage_delta": request.extra_context[
                        "consecutive_no_required_coverage_delta"
                    ],
                }
            )
            if request.role_archetype == "builder":
                payload = {
                    "attempted": "Prepared a candidate.",
                    "summary": "Candidate prepared.",
                    "changed_files": [],
                }
            else:
                payload = {
                    "passed": False,
                    "decision_summary": "Not enough evidence.",
                    "feedback_to_builder": "Add proof.",
                    "blocking_issues": [],
                    "metrics": [],
                    "failed_check_ids": [],
                    "priority_failures": [],
                    "composite_score": 0.0,
                    "evidence_refs": [],
                    "evidence_claims": [],
                }
            request.output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return payload

    service = service_factory(scenario="success")
    service.executor_factory = CountRecordingExecutor
    workflow = {
        "version": 1,
        "roles": [
            {"id": "builder", "name": "Builder", "archetype": "builder", "prompt_ref": "builder.md"},
            {"id": "gatekeeper", "name": "GateKeeper", "archetype": "gatekeeper", "prompt_ref": "gatekeeper.md"},
        ],
        "steps": [
            {"id": "builder_step", "role_id": "builder"},
            {"id": "gatekeeper_step", "role_id": "gatekeeper", "on_pass": "finish_run"},
        ],
    }
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Corrupt Stagnation Count Loop", workflow=workflow, max_iters=1)
    queued = service.start_run(loop["id"])
    layout = RunArtifactLayout(Path(queued["runs_dir"]))
    layout.timeline_stagnation_path.write_text(
        json.dumps(
            {
                "stagnation_mode": "none",
                "evidence_progress_mode": "stalled",
                "latest_covered_check_count": "3",
                "latest_missing_check_count": True,
                "consecutive_no_required_coverage_delta": 1.5,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    run = service.execute_run(queued["id"])

    assert run["status"] == "failed"
    assert recorded_counts
    assert recorded_counts[0] == {
        "covered_check_count": 0,
        "missing_check_count": 0,
        "consecutive_no_required_coverage_delta": 0,
    }


def _assert_runtime_contract_frozen_prefixes() -> None:
    for archetype in ["builder", "inspector", "gatekeeper", "custom", "guide"]:
        prefix = system_prompt_prefix(archetype)
        assert "Treat the run contract as frozen" in prefix
        assert "do not reinterpret or lower Task, Done When, Guardrails, Success Surface, Fake Done, Evidence Preferences, or Residual Risk" in prefix
        assert "evidence gaps or blockers" in prefix
        assert "project-local instructions, design docs, and tests" in prefix


def _assert_prompt_assets_contract_frozen(prompts: list[str], zh_prompts: list[str]) -> None:
    for prompt in prompts:
        assert "Treat the run contract as frozen" in prompt
        assert "do not reinterpret or lower Task, Done When, checks, guardrails, Success Surface, Fake Done, Evidence Preferences, or Residual Risk" in prompt
        assert "evidence gaps or blockers" in prompt
        assert "project-local instructions, design docs" in prompt
    for prompt in zh_prompts:
        assert "把 run contract 当作已冻结" in prompt
        assert "不要重新解释或降低 Task、Done When、checks、guardrails、Success Surface、Fake Done、Evidence Preferences 或 Residual Risk" in prompt
        assert "证据缺口或 blocker" in prompt
        assert "项目本地指令、design 文档或 tests" in prompt


def _runtime_prompt_assets() -> tuple[dict[str, str], dict[str, str]]:
    prompts_dir = Path(__file__).resolve().parents[3] / "src" / "loopora" / "assets" / "prompts"
    names = ["builder", "inspector", "custom", "guide", "gatekeeper", "gatekeeper-benchmark"]
    prompts = {name: (prompts_dir / f"{name}.md").read_text(encoding="utf-8") for name in names}
    zh_prompts = {name: (prompts_dir / f"{name}.zh.md").read_text(encoding="utf-8") for name in names}
    return prompts, zh_prompts


def _assert_prompt_evidence_fallback_rules(prompts: dict[str, str], zh_prompts: dict[str, str]) -> None:
    assert "smallest repeatable verification artifact" in prompts["builder"]
    assert "strongest no-install executable proof" in prompts["builder"]
    assert "最小可重复验证产物" in zh_prompts["builder"]
    assert "最强免安装可执行证明" in zh_prompts["builder"]
    assert "strongest repeatable fallback evidence" in prompts["gatekeeper"]
    assert "deterministic local proof" in prompts["gatekeeper"]
    assert "最强可重复 fallback 证据" in zh_prompts["gatekeeper"]
    assert "确定性本地证明" in zh_prompts["gatekeeper"]


def _assert_prompt_parallel_review_rules(prompts: dict[str, str], zh_prompts: dict[str, str]) -> None:
    assert "Inspector or Custom review steps will run in parallel" in prompts["builder"]
    assert "Inspector 或 Custom review step 并行检视" in zh_prompts["builder"]
    assert "parallel review group" in prompts["inspector"]
    assert "peer reviewers" in prompts["inspector"]
    assert "Custom reviewer" in prompts["inspector"]
    assert "并行 review 组" in zh_prompts["inspector"]
    assert "其他 reviewer" in zh_prompts["inspector"]
    assert "Custom reviewer" in zh_prompts["inspector"]
    assert "places you in a parallel review group" in prompts["custom"]
    assert "downstream GateKeeper can fan in" in prompts["custom"]
    assert "把你放进并行 review 组" in zh_prompts["custom"]
    assert "GateKeeper 可以和其他 review 分支一起汇总" in zh_prompts["custom"]
    assert "parallel Inspector or Custom review steps" in prompts["gatekeeper"]
    assert "all relevant review handoffs" in prompts["gatekeeper"]
    assert "并行 Inspector 或 Custom review step" in zh_prompts["gatekeeper"]
    assert "相关 review handoff" in zh_prompts["gatekeeper"]


def _assert_prompt_bucket_rules(prompts: dict[str, str], zh_prompts: dict[str, str]) -> None:
    evidence_bucket_phrase = "Proven / Weak / Unproven / Blocking / Residual risk"
    evidence_bucket_zh_phrase = "已证明 / 弱证据 / 未证明 / 阻断 / 残余风险"
    for prompt in prompts.values():
        assert evidence_bucket_phrase in prompt
    for prompt in zh_prompts.values():
        assert evidence_bucket_zh_phrase in prompt


def test_builtin_prompts_define_runtime_evidence_fallback_rules() -> None:
    prompts, zh_prompts = _runtime_prompt_assets()

    _assert_prompt_evidence_fallback_rules(prompts, zh_prompts)
    _assert_prompt_parallel_review_rules(prompts, zh_prompts)
    _assert_prompt_bucket_rules(prompts, zh_prompts)
    assert "run status is not a task pass" in prompts["gatekeeper"]
    assert "run 正常结束不等于任务通过" in zh_prompts["gatekeeper"]
    assert "downstream review steps run in a parallel_group" in system_prompt_prefix("builder")
    assert "this step is in a parallel_group" in system_prompt_prefix("inspector")
    assert "upstream reviewers ran in a parallel_group" in system_prompt_prefix("gatekeeper")
    assert "custom specialization" in system_prompt_prefix("custom")
    assert "run status separate from task verdict" in system_prompt_prefix("gatekeeper")
    _assert_runtime_contract_frozen_prefixes()
    assert "Proven, Weak, Unproven, Blocking, and Residual risk" in output_contract_prompt("inspector")
    assert "run status from task verdict" in output_contract_prompt("gatekeeper")
    assert "Blocking or Unproven gaps into the smallest repair direction" in output_contract_prompt("guide")


def test_control_runtime_frame_renders_trigger_evidence_refs() -> None:
    prompt_frame = render_iteration_section(
        {
            "iteration": {
                "iter_index": 1,
                "is_first_iteration": False,
                "previous_composite": 0.42,
                "stagnation_mode": "none",
                "evidence_progress_mode": "stalled",
                "covered_check_count": 1,
                "missing_check_count": 2,
                "consecutive_no_required_coverage_delta": 3,
            },
            "current_step": {
                "step_id": "control__guide",
                "step_order": 5,
                "role_name": "Guide",
                "archetype": "guide",
                "model": "",
                "executor_kind": "codex",
                "executor_mode": "preset",
                "parallel_group": "",
                "inputs": {"evidence_query": {"limit": 40}},
                "action_policy": {"workspace": "read_only"},
                "control": {
                    "signal": "gatekeeper_rejected",
                    "mode": "repair_guidance",
                    "reason": "GateKeeper rejected cited evidence.",
                    "trigger_evidence_refs": ["ev_000_01_inspector_step"],
                },
            },
        }
    )

    assert "- Control trigger: gatekeeper_rejected" in prompt_frame
    assert "- Control mode: repair_guidance" in prompt_frame
    assert "- Control evidence refs: [\"ev_000_01_inspector_step\"]" in prompt_frame


def test_builtin_prompt_assets_treat_run_contract_as_frozen() -> None:
    prompts_dir = Path(__file__).resolve().parents[3] / "src" / "loopora" / "assets" / "prompts"
    prompts = [
        (prompts_dir / "builder.md").read_text(encoding="utf-8"),
        (prompts_dir / "inspector.md").read_text(encoding="utf-8"),
        (prompts_dir / "custom.md").read_text(encoding="utf-8"),
        (prompts_dir / "guide.md").read_text(encoding="utf-8"),
        (prompts_dir / "gatekeeper.md").read_text(encoding="utf-8"),
        (prompts_dir / "gatekeeper-benchmark.md").read_text(encoding="utf-8"),
    ]
    zh_prompts = [
        (prompts_dir / "builder.zh.md").read_text(encoding="utf-8"),
        (prompts_dir / "inspector.zh.md").read_text(encoding="utf-8"),
        (prompts_dir / "custom.zh.md").read_text(encoding="utf-8"),
        (prompts_dir / "guide.zh.md").read_text(encoding="utf-8"),
        (prompts_dir / "gatekeeper.zh.md").read_text(encoding="utf-8"),
        (prompts_dir / "gatekeeper-benchmark.zh.md").read_text(encoding="utf-8"),
    ]

    _assert_prompt_assets_contract_frozen(prompts, zh_prompts)


def test_inspect_first_workflow_runs_inspector_before_builder(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = _create_loop(
        service,
        sample_spec_file,
        sample_workdir,
        name="Inspect First Loop",
        workflow={"preset": "inspect_first"},
    )

    run = service.rerun(loop["id"])

    assert run["status"] == "succeeded"
    assert run["workflow_json"]["preset"] == "inspect_first"
    iteration_log = [json.loads(line) for line in (Path(run["runs_dir"]) / "iteration_log.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    workflow_entry = next(entry for entry in iteration_log if entry["phase"] == "complete")
    assert [step["archetype"] for step in workflow_entry["workflow"][:3]] == ["inspector", "builder", "gatekeeper"]


def test_workflow_role_events_include_step_metadata(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = _create_loop(
        service,
        sample_spec_file,
        sample_workdir,
        name="Repair Loop Metadata",
        workflow={"preset": "repair_loop"},
    )

    run = service.rerun(loop["id"])

    events = service.repository.list_events(run["id"], after_id=0, limit=5000)
    builder_starts = [
        event
        for event in events
        if event["event_type"] == "role_started"
        and event.get("role") == "generator"
        and event["payload"].get("step_id") in {"builder_step", "builder_repair_step"}
    ]
    assert {event["payload"]["step_id"] for event in builder_starts} == {"builder_step", "builder_repair_step"}
    assert {event["payload"]["step_order"] for event in builder_starts} == {0, 4}

    repair_summary = next(
        event
        for event in events
        if event["event_type"] == "role_execution_summary" and event.get("role") == "generator" and event["payload"].get("step_id") == "builder_repair_step"
    )
    assert repair_summary["payload"]["role_name"] == "Builder"
    assert repair_summary["payload"]["archetype"] == "builder"


def test_benchmark_loop_can_finish_before_builder_runs(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    class BenchmarkPassingExecutor(CodexExecutor):
        def execute(self, request, _emit_event, _should_stop, set_child_pid):
            set_child_pid(None)
            if request.role_archetype == "gatekeeper":
                payload = {
                    "passed": True,
                    "decision_summary": "Benchmark target already satisfied.",
                    "feedback_to_builder": "No code change is required.",
                    "blocking_issues": [],
                    "metrics": [],
                    "metric_scores": {
                        "check_pass_rate": {"value": 1.0, "threshold": 1.0, "passed": True},
                        "quality_score": {"value": 1.0, "threshold": 0.9, "passed": True},
                    },
                    "failed_check_ids": [],
                    "priority_failures": [],
                    "composite_score": 1.0,
                    "evidence_refs": [],
                    "evidence_claims": ["The benchmark fixture is already satisfied by the existing project-owned proof output."],
                }
                request.output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                return payload
            raise AssertionError("Builder should not run when benchmark loop already passes.")

    service = service_factory(scenario="success")
    service.executor_factory = BenchmarkPassingExecutor
    loop = _create_loop(
        service,
        sample_spec_file,
        sample_workdir,
        name="Benchmark Loop",
        workflow={"preset": "benchmark_loop"},
    )

    run = service.rerun(loop["id"])
    run_dir = Path(run["runs_dir"])
    step_outputs = _step_outputs_by_archetype(run_dir)
    coverage = json.loads((run_dir / "evidence" / "coverage.json").read_text(encoding="utf-8"))
    ledger = _read_jsonl(run_dir / "evidence" / "ledger.jsonl")
    targets = {target["id"]: target for target in coverage["targets"]}
    gatekeeper_entry = next(item for item in ledger if item["archetype"] == "gatekeeper")

    assert run["status"] == "succeeded"
    assert "builder" not in step_outputs
    assert step_outputs["gatekeeper"][-1]["output"]["passed"] is True
    assert gatekeeper_entry["measured_evidence"] is True
    assert gatekeeper_entry["concrete_evidence_claim_count"] == 1
    assert coverage["latest_gatekeeper"]["self_measured_evidence"] is True
    assert targets["gatekeeper.finish"]["status"] == "covered"


def test_gatekeeper_pass_without_evidence_is_blocked(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    class UnsupportedPassingExecutor(CodexExecutor):
        def execute(self, request, _emit_event, _should_stop, set_child_pid):
            set_child_pid(None)
            if request.role_archetype != "gatekeeper":
                raise AssertionError("Only GateKeeper should run in this fixture.")
            payload = {
                "passed": True,
                "decision_summary": "Looks good from a quick read.",
                "feedback_to_builder": "No code change is required.",
                "blocking_issues": [],
                "metrics": [],
                "failed_check_ids": [],
                "priority_failures": [],
                "composite_score": 1.0,
            }
            request.output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return payload

    service = service_factory(scenario="success")
    service.executor_factory = UnsupportedPassingExecutor
    loop = _create_loop(
        service,
        sample_spec_file,
        sample_workdir,
        name="Unsupported Gate Loop",
        max_iters=1,
        workflow={"preset": "benchmark_loop"},
    )

    run = service.rerun(loop["id"])
    run_dir = Path(run["runs_dir"])
    gatekeeper_output = _step_outputs_by_archetype(run_dir)["gatekeeper"][-1]["output"]

    assert run["status"] == "failed"
    assert gatekeeper_output["passed"] is False
    assert "gatekeeper_pass_requires_evidence_refs" in gatekeeper_output["blocking_issues"]
    assert gatekeeper_output["evidence_gate_status"] == "blocked"


def test_gatekeeper_pass_with_claims_but_no_measured_evidence_is_blocked(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    class ClaimOnlyExecutor(CodexExecutor):
        def execute(self, request, _emit_event, _should_stop, set_child_pid):
            set_child_pid(None)
            if request.role_archetype != "gatekeeper":
                raise AssertionError("Only GateKeeper should run in this fixture.")
            payload = {
                "passed": True,
                "decision_summary": "Looks finished from the visible description.",
                "feedback_to_builder": "No code change is required.",
                "blocking_issues": [],
                "metrics": [],
                "failed_check_ids": [],
                "priority_failures": [],
                "composite_score": 1.0,
                "evidence_refs": ["self"],
                "evidence_claims": ["The task appears complete based on a prose inspection without a measured proof path."],
            }
            request.output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return payload

    service = service_factory(scenario="success")
    service.executor_factory = ClaimOnlyExecutor
    loop = _create_loop(
        service,
        sample_spec_file,
        sample_workdir,
        name="Claim Only Gate Loop",
        max_iters=1,
        workflow={"preset": "benchmark_loop"},
    )

    run = service.rerun(loop["id"])
    run_dir = Path(run["runs_dir"])
    gatekeeper_output = _step_outputs_by_archetype(run_dir)["gatekeeper"][-1]["output"]

    assert run["status"] == "failed"
    assert run["run_status"] == "failed"
    assert run["task_verdict"]["status"] == "failed"
    assert "blocking" in run["task_verdict"]["buckets"]
    assert gatekeeper_output["passed"] is False
    assert "gatekeeper_pass_requires_upstream_or_measured_evidence" in gatekeeper_output["blocking_issues"]
    assert gatekeeper_output["evidence_refs"] == ["ev_000_00_gatekeeper_step"]


def test_gatekeeper_pass_with_uncovered_required_targets_does_not_pass_task_verdict(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    class UncoveredRequiredTargetsExecutor(CodexExecutor):
        def execute(self, request, _emit_event, _should_stop, set_child_pid):
            set_child_pid(None)
            if request.role_archetype == "builder":
                payload = {
                    "attempted": "Left a generic implementation handoff.",
                    "abandoned": "",
                    "assumption": "",
                    "summary": "No required coverage target was directly verified.",
                    "changed_files": [],
                }
            elif request.role_archetype == "inspector":
                payload = {
                    "execution_summary": {
                        "total_checks": 0,
                        "passed": 0,
                        "failed": 0,
                        "errored": 0,
                        "total_duration_ms": 1,
                    },
                    "check_results": [],
                    "dynamic_checks": [],
                    "tester_observations": "This produced an upstream observation without verifying required targets.",
                    "coverage_results": [],
                }
            else:
                payload = {
                    "passed": True,
                    "decision_summary": "GateKeeper accepted a generic upstream observation.",
                    "feedback_to_builder": "",
                    "blocking_issues": [],
                    "metrics": [
                        {"name": "quality_score", "value": 1.0, "threshold": 0.9, "passed": True},
                    ],
                    "metric_scores": {
                        "quality_score": {"value": 1.0, "threshold": 0.9, "passed": True},
                    },
                    "failed_check_ids": [],
                    "priority_failures": [],
                    "composite_score": 1.0,
                    "evidence_refs": ["ev_000_01_inspector_step"],
                    "evidence_claims": ["The inspector produced an observation, but no required target was verified."],
                }
            request.output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return payload

    service = service_factory(scenario="success")
    service.executor_factory = UncoveredRequiredTargetsExecutor
    workflow = {
        "version": 1,
        "roles": [
            {"id": "builder", "name": "Builder", "archetype": "builder", "prompt_ref": "builder.md"},
            {"id": "inspector", "name": "Inspector", "archetype": "inspector", "prompt_ref": "inspector.md"},
            {"id": "gatekeeper", "name": "GateKeeper", "archetype": "gatekeeper", "prompt_ref": "gatekeeper.md"},
        ],
        "steps": [
            {"id": "builder_step", "role_id": "builder"},
            {"id": "inspector_step", "role_id": "inspector"},
            {"id": "gatekeeper_step", "role_id": "gatekeeper", "on_pass": "finish_run"},
        ],
    }
    loop = _create_loop(
        service,
        sample_spec_file,
        sample_workdir,
        name="Uncovered Required Target Loop",
        max_iters=1,
        workflow=workflow,
    )

    run = service.rerun(loop["id"])
    run_dir = Path(run["runs_dir"])
    coverage = json.loads((run_dir / "evidence" / "coverage.json").read_text(encoding="utf-8"))
    gatekeeper_output = _step_outputs_by_archetype(run_dir)["gatekeeper"][-1]["output"]

    assert run["status"] == "succeeded"
    assert gatekeeper_output["evidence_gate_status"] == "passed"
    assert coverage["status"] == "partial"
    assert run["task_verdict"]["status"] == "insufficient_evidence"
    assert run["task_verdict"]["source"] == "gatekeeper"
    events = service.stream_events(run["id"], limit=200)
    assert any(
        event["event_type"] == "run_finished"
        and event["payload"]["status"] == "succeeded"
        and event["payload"]["task_verdict_status"] == "insufficient_evidence"
        and event["payload"]["task_verdict_source"] == "gatekeeper"
        for event in events
    )


def test_gatekeeper_pass_with_residual_risk_projects_task_verdict(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    class ResidualRiskPassingExecutor(CodexExecutor):
        def execute(self, request, _emit_event, _should_stop, set_child_pid):
            set_child_pid(None)
            if request.role_archetype == "inspector":
                payload = {
                    "execution_summary": {
                        "total_checks": 2,
                        "passed": 2,
                        "failed": 0,
                        "errored": 0,
                        "total_duration_ms": 50,
                    },
                    "check_results": [
                        {
                            "id": "check_001",
                            "title": "Primary experience",
                            "status": "passed",
                            "notes": "Primary path is proven.",
                        },
                        {
                            "id": "check_002",
                            "title": "Edge path",
                            "status": "passed",
                            "notes": "Edge path is proven with a named follow-up.",
                        },
                    ],
                    "dynamic_checks": [],
                    "tester_observations": "Both required checks are covered.",
                    "coverage_results": [],
                }
            else:
                evidence_refs = [item["id"] for item in request.extra_context["context_packet"]["evidence"]["items"]]
                payload = {
                    "passed": True,
                    "decision_summary": "GateKeeper passed with a named acceptable follow-up risk.",
                    "feedback_to_builder": "",
                    "blocking_issues": [],
                    "metrics": [
                        {"name": "quality_score", "value": 1.0, "threshold": 0.9, "passed": True},
                    ],
                    "failed_check_ids": [],
                    "priority_failures": [],
                    "composite_score": 1.0,
                    "evidence_refs": evidence_refs,
                    "evidence_claims": ["The inspector evidence covers both required checks."],
                    "residual_risks": ["Manual copy polish remains a visible follow-up."],
                }
            request.output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return payload

    service = service_factory(scenario="success")
    service.executor_factory = ResidualRiskPassingExecutor
    workflow = {
        "version": 1,
        "roles": [
            {"id": "inspector", "name": "Inspector", "archetype": "inspector", "prompt_ref": "inspector.md"},
            {"id": "gatekeeper", "name": "GateKeeper", "archetype": "gatekeeper", "prompt_ref": "gatekeeper.md"},
        ],
        "steps": [
            {"id": "inspector_step", "role_id": "inspector"},
            {"id": "gatekeeper_step", "role_id": "gatekeeper", "on_pass": "finish_run"},
        ],
    }
    loop = _create_loop(
        service,
        sample_spec_file,
        sample_workdir,
        name="Residual Risk Gate Loop",
        max_iters=1,
        workflow=workflow,
    )

    run = service.rerun(loop["id"])
    run_dir = Path(run["runs_dir"])
    ledger = _read_jsonl(run_dir / "evidence" / "ledger.jsonl")
    gatekeeper_entry = next(item for item in ledger if item["archetype"] == "gatekeeper")

    assert run["status"] == "succeeded"
    assert run["task_verdict"]["status"] == "passed_with_residual_risk"
    assert run["task_verdict"]["buckets"]["residual_risk"] == [{"label": "Manual copy polish remains a visible follow-up."}]
    assert gatekeeper_entry["residual_risk"] == "Manual copy polish remains a visible follow-up."


def test_gatekeeper_pass_citing_plain_builder_handoff_is_blocked(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    class BuilderHandoffOnlyExecutor(CodexExecutor):
        def execute(self, request, _emit_event, _should_stop, set_child_pid):
            set_child_pid(None)
            if request.role_archetype == "builder":
                payload = {
                    "attempted": "Produced a candidate without proof artifacts.",
                    "abandoned": "",
                    "assumption": "",
                    "summary": "Builder says the task is done.",
                    "changed_files": [],
                    "proof_files": [],
                    "proof_artifacts": [],
                    "artifact_paths": [],
                }
            else:
                payload = {
                    "passed": True,
                    "decision_summary": "GateKeeper accepted the Builder handoff as proof.",
                    "feedback_to_builder": "",
                    "blocking_issues": [],
                    "metrics": [],
                    "failed_check_ids": [],
                    "priority_failures": [],
                    "composite_score": 1.0,
                    "evidence_refs": ["ev_000_00_builder_step"],
                    "evidence_claims": ["The Builder handoff says the task is complete."],
                }
            request.output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return payload

    service = service_factory(scenario="success")
    service.executor_factory = BuilderHandoffOnlyExecutor
    workflow = {
        "version": 1,
        "roles": [
            {"id": "builder", "name": "Builder", "archetype": "builder", "prompt_ref": "builder.md"},
            {"id": "gatekeeper", "name": "GateKeeper", "archetype": "gatekeeper", "prompt_ref": "gatekeeper.md"},
        ],
        "steps": [
            {"id": "builder_step", "role_id": "builder"},
            {"id": "gatekeeper_step", "role_id": "gatekeeper", "on_pass": "finish_run"},
        ],
    }
    loop = _create_loop(
        service,
        sample_spec_file,
        sample_workdir,
        name="Builder Handoff Only Loop",
        max_iters=1,
        workflow=workflow,
    )

    run = service.rerun(loop["id"])
    run_dir = Path(run["runs_dir"])
    coverage = json.loads((run_dir / "evidence" / "coverage.json").read_text(encoding="utf-8"))
    gatekeeper_output = _step_outputs_by_archetype(run_dir)["gatekeeper"][-1]["output"]

    assert run["status"] == "failed"
    assert run["task_verdict"]["status"] == "failed"
    assert gatekeeper_output["passed"] is False
    assert gatekeeper_output["evidence_gate_status"] == "blocked"
    assert gatekeeper_output["blocking_issues"] == ["gatekeeper_pass_refs_not_supporting_evidence"]
    assert coverage["latest_gatekeeper"]["supporting_evidence_refs"] == []
    assert coverage["latest_gatekeeper"]["non_supporting_evidence_refs"] == ["ev_000_00_builder_step"]


def test_gatekeeper_pass_citing_missing_builder_proof_artifact_is_blocked(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    proof_path = sample_workdir / "tests" / "evidence" / "proof.json"

    class MissingProofArtifactExecutor(CodexExecutor):
        def execute(self, request, _emit_event, _should_stop, set_child_pid):
            set_child_pid(None)
            if request.role_archetype == "builder":
                proof_path.parent.mkdir(parents=True, exist_ok=True)
                proof_path.write_text('{"ok": true}\n', encoding="utf-8")
                payload = {
                    "attempted": "Produced a candidate with a proof artifact.",
                    "abandoned": "",
                    "assumption": "",
                    "summary": "Builder left proof for the task.",
                    "changed_files": [],
                    "proof_files": ["tests/evidence/proof.json"],
                    "proof_artifacts": [],
                    "artifact_paths": [],
                }
            else:
                proof_path.unlink()
                payload = {
                    "passed": True,
                    "decision_summary": "GateKeeper accepted a proof artifact that is no longer available.",
                    "feedback_to_builder": "",
                    "blocking_issues": [],
                    "metrics": [],
                    "failed_check_ids": [],
                    "priority_failures": [],
                    "composite_score": 1.0,
                    "evidence_refs": ["ev_000_00_builder_step"],
                    "evidence_claims": ["The proof artifact path should remain readable at close time."],
                }
            request.output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return payload

    service = service_factory(scenario="success")
    service.executor_factory = MissingProofArtifactExecutor
    workflow = {
        "version": 1,
        "roles": [
            {"id": "builder", "name": "Builder", "archetype": "builder", "prompt_ref": "builder.md"},
            {"id": "gatekeeper", "name": "GateKeeper", "archetype": "gatekeeper", "prompt_ref": "gatekeeper.md"},
        ],
        "steps": [
            {"id": "builder_step", "role_id": "builder"},
            {"id": "gatekeeper_step", "role_id": "gatekeeper", "on_pass": "finish_run"},
        ],
    }
    loop = _create_loop(
        service,
        sample_spec_file,
        sample_workdir,
        name="Missing Proof Artifact Loop",
        max_iters=1,
        workflow=workflow,
    )

    run = service.rerun(loop["id"])
    run_dir = Path(run["runs_dir"])
    coverage = json.loads((run_dir / "evidence" / "coverage.json").read_text(encoding="utf-8"))
    manifest = json.loads((run_dir / "evidence" / "manifest.json").read_text(encoding="utf-8"))
    gatekeeper_output = _step_outputs_by_archetype(run_dir)["gatekeeper"][-1]["output"]
    builder_claim = next(item for item in manifest["claims"] if item["id"] == "ev_000_00_builder_step")

    assert run["status"] == "failed"
    assert gatekeeper_output["passed"] is False
    assert gatekeeper_output["evidence_gate_status"] == "blocked"
    assert gatekeeper_output["blocking_issues"] == ["gatekeeper_pass_refs_not_supporting_evidence"]
    assert coverage["latest_gatekeeper"]["supporting_evidence_refs"] == []
    assert coverage["latest_gatekeeper"]["non_supporting_evidence_refs"] == ["ev_000_00_builder_step"]
    assert builder_claim["verification_status"] == "run_artifact"
    assert builder_claim["workspace_backed"] is False
    assert any(problem["code"] == "claim_artifact_missing" for problem in manifest["problems"])


def test_workflow_step_can_resume_its_own_previous_session_and_append_extra_cli_args(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    recorded_requests: list[dict] = []

    class SessionAwareExecutor(CodexExecutor):
        def execute(self, request, _emit_event, _should_stop, set_child_pid):
            set_child_pid(None)
            recorded_requests.append(
                {
                    "step_id": request.step_id,
                    "iter": request.extra_context.get("iter_id"),
                    "inherit_session": request.inherit_session,
                    "resume_session_id": request.resume_session_id,
                    "extra_cli_args_text": request.extra_cli_args_text,
                    "role_archetype": request.role_archetype,
                }
            )
            if request.role_archetype == "builder":
                request.extra_context["session_ref"] = {
                    "session_id": f"builder-session-{request.extra_context.get('iter_id')}",
                }
                payload = {
                    "attempted": "Made a targeted implementation change.",
                    "summary": "Builder progressed the workspace.",
                    "changed_files": [],
                }
            else:
                payload = {
                    "passed": False,
                    "decision_summary": "Keep iterating for the contract test.",
                    "feedback_to_builder": "Continue the workflow.",
                    "blocking_issues": [],
                    "metrics": [],
                    "failed_check_ids": [],
                    "priority_failures": [],
                    "composite_score": 0.4,
                }
            request.output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return payload

    service = service_factory(scenario="success")
    service.executor_factory = SessionAwareExecutor
    loop = _create_loop(
        service,
        sample_spec_file,
        sample_workdir,
        name="Session Carry Loop",
        completion_mode="rounds",
        max_iters=2,
        workflow={
            "version": 1,
            "preset": "",
            "roles": [
                {"id": "builder", "name": "Builder", "archetype": "builder", "prompt_ref": "builder.md"},
                {"id": "gatekeeper", "name": "GateKeeper", "archetype": "gatekeeper", "prompt_ref": "gatekeeper.md"},
            ],
            "steps": [
                {
                    "id": "builder_step",
                    "role_id": "builder",
                    "inherit_session": True,
                    "extra_cli_args": "--verbose",
                },
                {
                    "id": "gatekeeper_step",
                    "role_id": "gatekeeper",
                    "on_pass": "continue",
                    "inherit_session": False,
                },
            ],
        },
    )

    run = service.rerun(loop["id"])
    role_requests = _read_jsonl(Path(run["runs_dir"]) / "context" / "role_requests.jsonl")

    assert run["status"] == "succeeded"
    builder_calls = [item for item in recorded_requests if item["step_id"] == "builder_step"]
    gatekeeper_calls = [item for item in recorded_requests if item["step_id"] == "gatekeeper_step"]
    assert [item["resume_session_id"] for item in builder_calls] == ["", "builder-session-0"]
    assert all(item["inherit_session"] is True for item in builder_calls)
    assert all(item["extra_cli_args_text"] == "--verbose" for item in builder_calls)
    assert all(item["inherit_session"] is False for item in gatekeeper_calls)
    assert all(item["resume_session_id"] == "" for item in gatekeeper_calls)

    second_builder_request = next(item for item in role_requests if item["step_id"] == "builder_step" and item["iter"] == 1)
    assert second_builder_request["inherit_session"] is True
    assert second_builder_request["resume_session_id"] == "builder-session-0"
    assert second_builder_request["extra_cli_args_text"] == "--verbose"


def test_parallel_inspection_group_fans_out_then_gatekeeper_sees_all_evidence(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    class ParallelInspectionExecutor(CodexExecutor):
        def __init__(self) -> None:
            self.barrier = threading.Barrier(2)
            self.timings: dict[str, dict[str, float]] = {}
            self.lock = threading.Lock()

        def execute(self, request, _emit_event, _should_stop, set_child_pid):
            set_child_pid(None)
            if request.role_archetype == "builder":
                payload = {
                    "attempted": "Prepared the first working slice.",
                    "summary": "Builder produced a concrete candidate for inspection.",
                    "changed_files": [],
                }
            elif request.role_archetype == "inspector":
                with self.lock:
                    self.timings[request.step_id] = {"start": time.perf_counter()}
                self.barrier.wait(timeout=2)
                time.sleep(0.1)
                with self.lock:
                    self.timings[request.step_id]["end"] = time.perf_counter()
                payload = {
                    "execution_summary": {
                        "total_checks": 1,
                        "passed": 1,
                        "failed": 0,
                        "errored": 0,
                        "total_duration_ms": 100,
                    },
                    "check_results": [
                        {
                            "id": request.step_id,
                            "title": f"{request.step_id} evidence",
                            "status": "passed",
                            "notes": "Parallel inspector collected direct evidence.",
                        }
                    ],
                    "dynamic_checks": [],
                    "tester_observations": f"{request.step_id} completed its independent inspection.",
                }
            else:
                context_packet = request.extra_context["context_packet"]
                evidence_refs = [item["id"] for item in context_packet["evidence"]["items"] if item.get("archetype") == "inspector"]
                payload = {
                    "passed": True,
                    "decision_summary": "Both inspection branches passed.",
                    "feedback_to_builder": "",
                    "blocking_issues": [],
                    "metrics": [],
                    "failed_check_ids": [],
                    "priority_failures": [],
                    "composite_score": 1.0,
                    "evidence_refs": evidence_refs,
                    "evidence_claims": [],
                }
            request.output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return payload

    executor = ParallelInspectionExecutor()
    service = service_factory(scenario="success")
    service.executor_factory = lambda: executor
    workflow = {
        "version": 1,
        "roles": [
            {"id": "builder", "name": "Builder", "archetype": "builder", "prompt_ref": "builder.md"},
            {"id": "accessibility", "name": "Accessibility Inspector", "archetype": "inspector", "prompt_ref": "inspector.md"},
            {"id": "contract", "name": "Contract Inspector", "archetype": "inspector", "prompt_ref": "inspector.md"},
            {"id": "gatekeeper", "name": "GateKeeper", "archetype": "gatekeeper", "prompt_ref": "gatekeeper.md"},
        ],
        "steps": [
            {"id": "builder_step", "role_id": "builder"},
            {"id": "accessibility_step", "role_id": "accessibility", "parallel_group": "inspection_pack"},
            {"id": "contract_step", "role_id": "contract", "parallel_group": "inspection_pack"},
            {"id": "gatekeeper_step", "role_id": "gatekeeper", "on_pass": "finish_run"},
        ],
    }
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Parallel Inspection Loop", workflow=workflow)

    run = service.rerun(loop["id"])
    run_dir = Path(run["runs_dir"])
    evidence_ledger = _read_jsonl(run_dir / "evidence" / "ledger.jsonl")
    gatekeeper_output = _step_outputs_by_archetype(run_dir)["gatekeeper"][-1]["output"]

    assert run["status"] == "succeeded"
    assert max(item["start"] for item in executor.timings.values()) < min(item["end"] for item in executor.timings.values())
    assert {entry["step_id"] for entry in evidence_ledger if entry["archetype"] == "inspector"} == {
        "accessibility_step",
        "contract_step",
    }
    assert set(gatekeeper_output["evidence_refs"]) >= {
        "ev_000_01_accessibility_step",
        "ev_000_02_contract_step",
    }
    events = service.stream_events(run["id"], limit=500)
    assert any(event["event_type"] == "parallel_group_started" for event in events)
    assert any(event["event_type"] == "parallel_group_finished" for event in events)


def test_workflow_control_records_runtime_evidence_and_respects_fire_limit(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="plateau")
    workflow = {
        "version": 1,
        "roles": [
            {"id": "builder", "name": "Builder", "archetype": "builder", "prompt_ref": "builder.md"},
            {"id": "inspector", "name": "Inspector", "archetype": "inspector", "prompt_ref": "inspector.md"},
            {"id": "guide", "name": "Guide", "archetype": "guide", "prompt_ref": "guide.md"},
            {"id": "gatekeeper", "name": "GateKeeper", "archetype": "gatekeeper", "prompt_ref": "gatekeeper.md"},
        ],
        "steps": [
            {"id": "builder_step", "role_id": "builder"},
            {"id": "inspector_step", "role_id": "inspector"},
            {"id": "gatekeeper_step", "role_id": "gatekeeper", "on_pass": "finish_run"},
        ],
        "controls": [
            {
                "id": "gatekeeper_rejection_guidance",
                "when": {"signal": "gatekeeper_rejected", "after": "0s"},
                "call": {"role_id": "guide"},
                "mode": "repair_guidance",
                "max_fires_per_run": 1,
            }
        ],
    }
    loop = _create_loop(
        service,
        sample_spec_file,
        sample_workdir,
        name="Controlled Rejection Loop",
        workflow=workflow,
        max_iters=3,
    )

    run = service.rerun(loop["id"])
    run_dir = Path(run["runs_dir"])
    events = service.stream_events(run["id"], limit=500)
    evidence_ledger = _read_jsonl(run_dir / "evidence" / "ledger.jsonl")

    assert run["status"] == "failed"
    assert [event["event_type"] for event in events].count("control_triggered") == 1
    assert [event["event_type"] for event in events].count("control_completed") == 1
    assert any(event["event_type"] == "control_skipped" for event in events)
    control_entries = [entry for entry in evidence_ledger if entry["evidence_kind"] == "control"]
    assert len(control_entries) == 1
    assert control_entries[0]["source"] == "workflow_control"
    assert "control:gatekeeper_rejected" in control_entries[0]["verifies"]


def test_workflow_control_triggers_when_required_coverage_stalls(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    class CoverageStallExecutor(CodexExecutor):
        def execute(self, request, _emit_event, _should_stop, set_child_pid):
            set_child_pid(None)
            iter_id = int(request.extra_context.get("iter_id") or 0)
            if request.role_archetype == "builder":
                payload = {
                    "attempted": "Kept changing the story without adding required proof.",
                    "abandoned": "",
                    "assumption": "",
                    "summary": "No required coverage target was verified.",
                    "changed_files": [],
                }
            elif request.role_archetype == "inspector":
                payload = {
                    "execution_summary": {
                        "total_checks": 0,
                        "passed": 0,
                        "failed": 0,
                        "errored": 0,
                        "total_duration_ms": 1,
                    },
                    "check_results": [],
                    "dynamic_checks": [],
                    "tester_observations": "No required Done When target has direct evidence yet.",
                    "coverage_results": [],
                }
            elif request.role_archetype == "guide":
                payload = {
                    "created_at_iter": iter_id,
                    "mode": "coverage_stalled",
                    "consumed": False,
                    "analysis": {
                        "recommended_shift": "Stop changing the narrative and produce one required proof target.",
                        "risk_note": "Coverage stalled while required checks remain missing.",
                    },
                    "seed_question": "Which missing Done When target can be proved next?",
                    "meta_note": "Coverage control fired.",
                }
            else:
                payload = {
                    "passed": False,
                    "decision_summary": "Composite improved, but required evidence coverage did not.",
                    "feedback_to_builder": "Produce direct proof for a required Done When target.",
                    "blocking_issues": [],
                    "metrics": [
                        {
                            "name": "quality_score",
                            "value": 0.5 + iter_id * 0.1,
                            "threshold": 0.9,
                            "passed": False,
                        }
                    ],
                    "failed_check_ids": [],
                    "priority_failures": [],
                    "composite_score": 0.5 + iter_id * 0.1,
                    "evidence_refs": [],
                    "evidence_claims": [],
                }
            request.output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return payload

    service = service_factory(scenario="success")
    service.executor_factory = CoverageStallExecutor
    workflow = {
        "version": 1,
        "roles": [
            {"id": "builder", "name": "Builder", "archetype": "builder", "prompt_ref": "builder.md"},
            {"id": "inspector", "name": "Inspector", "archetype": "inspector", "prompt_ref": "inspector.md"},
            {"id": "guide", "name": "Guide", "archetype": "guide", "prompt_ref": "guide.md"},
            {"id": "gatekeeper", "name": "GateKeeper", "archetype": "gatekeeper", "prompt_ref": "gatekeeper.md"},
        ],
        "steps": [
            {"id": "builder_step", "role_id": "builder"},
            {"id": "inspector_step", "role_id": "inspector"},
            {"id": "gatekeeper_step", "role_id": "gatekeeper", "on_pass": "finish_run"},
        ],
        "controls": [
            {
                "id": "coverage_stall_guidance",
                "when": {"signal": "no_evidence_progress", "after": "0s"},
                "call": {"role_id": "guide"},
                "mode": "repair_guidance",
                "max_fires_per_run": 1,
            }
        ],
    }
    loop = _create_loop(
        service,
        sample_spec_file,
        sample_workdir,
        name="Coverage Stall Control Loop",
        workflow=workflow,
        max_iters=2,
        trigger_window=1,
    )

    run = service.rerun(loop["id"])
    run_dir = Path(run["runs_dir"])
    stagnation = json.loads((run_dir / "timeline" / "stagnation.json").read_text(encoding="utf-8"))
    latest_iteration_summary = json.loads((run_dir / "context" / "latest_iteration_summary.json").read_text(encoding="utf-8"))
    events = service.stream_events(run["id"], limit=500)
    evidence_ledger = _read_jsonl(run_dir / "evidence" / "ledger.jsonl")
    role_requests = _read_jsonl(run_dir / "context" / "role_requests.jsonl")
    guide_request = next(item for item in role_requests if item["role_archetype"] == "guide")
    guide_prompt = (run_dir / guide_request["prompt_path"]).read_text(encoding="utf-8")
    takeaways = build_run_key_takeaways(service.get_run(run["id"]))
    latest_takeaway = takeaways["iterations"][0]

    assert run["status"] == "failed"
    assert stagnation["stagnation_mode"] == "none"
    assert stagnation["evidence_progress_mode"] == "stalled"
    assert stagnation["latest_missing_check_count"] == 2
    assert latest_iteration_summary["stagnation"]["evidence_progress_mode"] == "stalled"
    assert latest_iteration_summary["stagnation"]["covered_check_count"] == 0
    assert latest_iteration_summary["stagnation"]["missing_check_count"] == 2
    assert guide_request["context_summary"]["context_packet"]["evidence_progress_mode"] == "stalled"
    assert guide_request["context_summary"]["context_packet"]["covered_check_count"] == 0
    assert guide_request["context_summary"]["context_packet"]["missing_check_count"] == 2
    assert "Evidence progress mode: stalled" in guide_prompt
    assert "Required coverage: 0 covered, 2 missing" in guide_prompt
    assert latest_takeaway["evidence_progress_mode"] == "stalled"
    assert latest_takeaway["covered_check_count"] == 0
    assert latest_takeaway["missing_check_count"] == 2
    assert latest_takeaway["consecutive_no_required_coverage_delta"] == 1
    assert any(
        event["event_type"] == "control_triggered"
        and event["payload"]["signal"] == "no_evidence_progress"
        and "Required coverage did not improve" in event["payload"]["reason"]
        for event in events
    )
    assert any(entry["evidence_kind"] == "control" and "control:no_evidence_progress" in entry["verifies"] for entry in evidence_ledger)


@pytest.mark.parametrize("max_fires_per_run", [0, True, 1.5, "2"])
def test_workflow_run_rejects_invalid_persisted_control_fire_limit(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
    max_fires_per_run: object,
) -> None:
    service = service_factory(scenario="success")
    workflow = {
        "version": 1,
        "roles": [
            {"id": "builder", "name": "Builder", "archetype": "builder", "prompt_ref": "builder.md"},
            {"id": "guide", "name": "Guide", "archetype": "guide", "prompt_ref": "guide.md"},
            {"id": "gatekeeper", "name": "GateKeeper", "archetype": "gatekeeper", "prompt_ref": "gatekeeper.md"},
        ],
        "steps": [
            {"id": "builder_step", "role_id": "builder"},
            {"id": "gatekeeper_step", "role_id": "gatekeeper", "on_pass": "finish_run"},
        ],
        "controls": [
            {
                "id": "stale_evidence_check",
                "when": {"signal": "no_evidence_progress", "after": "0s"},
                "call": {"role_id": "guide"},
                "mode": "repair_guidance",
                "max_fires_per_run": 1,
            }
        ],
    }
    loop = _create_loop(
        service,
        sample_spec_file,
        sample_workdir,
        name="Corrupted Control Loop",
        workflow=workflow,
    )
    corrupted_workflow = json.loads(json.dumps(loop["workflow_json"]))
    corrupted_workflow["controls"][0]["max_fires_per_run"] = max_fires_per_run
    with service.repository.transaction() as connection:
        connection.execute(
            "UPDATE loop_definitions SET workflow_json = ? WHERE id = ?",
            (json.dumps(corrupted_workflow, ensure_ascii=False), loop["id"]),
        )

    run = service.rerun(loop["id"])
    events = service.stream_events(run["id"], limit=100)

    assert run["status"] == "failed"
    assert "max_fires_per_run" in run["error_message"]
    assert not any(event["event_type"] == "control_triggered" for event in events)


@pytest.mark.parametrize("limit", [True, "12"])
def test_workflow_run_rejects_invalid_persisted_evidence_query_limit(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
    limit: object,
) -> None:
    service = service_factory(scenario="success")
    workflow = {
        "version": 1,
        "roles": [
            {"id": "builder", "name": "Builder", "archetype": "builder", "prompt_ref": "builder.md"},
            {"id": "gatekeeper", "name": "GateKeeper", "archetype": "gatekeeper", "prompt_ref": "gatekeeper.md"},
        ],
        "steps": [
            {"id": "builder_step", "role_id": "builder"},
            {
                "id": "gatekeeper_step",
                "role_id": "gatekeeper",
                "inputs": {"evidence_query": {"archetypes": ["builder"], "limit": 12}},
                "on_pass": "finish_run",
            },
        ],
    }
    loop = _create_loop(
        service,
        sample_spec_file,
        sample_workdir,
        name="Corrupted Evidence Query Loop",
        workflow=workflow,
    )
    corrupted_workflow = json.loads(json.dumps(loop["workflow_json"]))
    corrupted_workflow["steps"][1]["inputs"]["evidence_query"]["limit"] = limit
    with service.repository.transaction() as connection:
        connection.execute(
            "UPDATE loop_definitions SET workflow_json = ? WHERE id = ?",
            (json.dumps(corrupted_workflow, ensure_ascii=False), loop["id"]),
        )

    run = service.rerun(loop["id"])
    events = service.stream_events(run["id"], limit=100)

    assert run["status"] == "failed"
    assert "evidence_query.limit must be an integer" in run["error_message"]
    assert not any(
        event["event_type"] == "role_execution_summary" and event["payload"].get("archetype") == "gatekeeper"
        for event in events
    )


def test_workflow_run_rejects_invalid_persisted_step_action_policy(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    workflow = {
        "version": 1,
        "roles": [
            {"id": "builder", "name": "Builder", "archetype": "builder", "prompt_ref": "builder.md"},
            {"id": "gatekeeper", "name": "GateKeeper", "archetype": "gatekeeper", "prompt_ref": "gatekeeper.md"},
        ],
        "steps": [
            {"id": "builder_step", "role_id": "builder"},
            {"id": "gatekeeper_step", "role_id": "gatekeeper", "on_pass": "finish_run"},
        ],
    }
    loop = _create_loop(
        service,
        sample_spec_file,
        sample_workdir,
        name="Corrupted Step Policy Loop",
        workflow=workflow,
    )
    corrupted_workflow = json.loads(json.dumps(loop["workflow_json"]))
    corrupted_workflow["steps"][1]["action_policy"]["workspace"] = "workspace_write"
    with service.repository.transaction() as connection:
        connection.execute(
            "UPDATE loop_definitions SET workflow_json = ? WHERE id = ?",
            (json.dumps(corrupted_workflow, ensure_ascii=False), loop["id"]),
        )

    run = service.rerun(loop["id"])
    events = service.stream_events(run["id"], limit=100)

    assert run["status"] == "failed"
    assert "only Builder steps may set action_policy.workspace=workspace_write" in run["error_message"]
    assert not any(
        event["event_type"] == "role_execution_summary" and event["payload"].get("archetype") == "gatekeeper"
        for event in events
    )


def test_step_input_policy_filters_handoffs_and_evidence_context(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    recorded_gate_context: dict = {}

    class InputPolicyExecutor(CodexExecutor):
        def execute(self, request, _emit_event, _should_stop, set_child_pid):
            set_child_pid(None)
            if request.role_archetype == "builder":
                payload = {
                    "attempted": "Built a candidate.",
                    "summary": "Builder completed the candidate.",
                    "changed_files": [],
                }
            elif request.role_archetype == "inspector":
                payload = {
                    "execution_summary": {
                        "total_checks": 1,
                        "passed": 1,
                        "failed": 0,
                        "errored": 0,
                        "total_duration_ms": 50,
                    },
                    "check_results": [
                        {
                            "id": request.step_id,
                            "title": request.step_id,
                            "status": "passed",
                            "notes": "Filtered evidence path.",
                        }
                    ],
                    "dynamic_checks": [],
                    "tester_observations": f"{request.step_id} evidence.",
                }
            else:
                context_packet = request.extra_context["context_packet"]
                recorded_gate_context.update(context_packet)
                evidence_refs = [item["id"] for item in context_packet["evidence"]["items"]]
                payload = {
                    "passed": True,
                    "decision_summary": "Filtered context was enough.",
                    "feedback_to_builder": "",
                    "blocking_issues": [],
                    "metrics": [],
                    "failed_check_ids": [],
                    "priority_failures": [],
                    "composite_score": 1.0,
                    "evidence_refs": evidence_refs,
                    "evidence_claims": [],
                }
            request.output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return payload

    service = service_factory(scenario="success")
    service.executor_factory = InputPolicyExecutor
    workflow = {
        "version": 1,
        "roles": [
            {"id": "builder", "name": "Builder", "archetype": "builder", "prompt_ref": "builder.md"},
            {"id": "ux", "name": "UX Inspector", "archetype": "inspector", "prompt_ref": "inspector.md"},
            {"id": "contract", "name": "Contract Inspector", "archetype": "inspector", "prompt_ref": "inspector.md"},
            {"id": "gatekeeper", "name": "GateKeeper", "archetype": "gatekeeper", "prompt_ref": "gatekeeper.md"},
        ],
        "steps": [
            {"id": "builder_step", "role_id": "builder"},
            {"id": "ux_step", "role_id": "ux"},
            {"id": "contract_step", "role_id": "contract"},
            {
                "id": "gatekeeper_step",
                "role_id": "gatekeeper",
                "on_pass": "finish_run",
                "inputs": {
                    "handoffs_from": ["contract_step"],
                    "evidence_query": {"archetypes": ["inspector"], "limit": 1},
                },
            },
        ],
    }
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Filtered Context Loop", workflow=workflow)

    run = service.rerun(loop["id"])

    assert run["status"] == "succeeded"
    assert [item["source"]["step_id"] for item in recorded_gate_context["upstream"]["completed_steps_this_iteration"]] == ["contract_step"]
    assert [item["step_id"] for item in recorded_gate_context["evidence"]["items"]] == ["contract_step"]
    assert recorded_gate_context["evidence"]["known_ids"] == ["ev_000_02_contract_step"]
    assert recorded_gate_context["evidence"]["manifest_summary"]["claim_count"] == 1
    assert [item["id"] for item in recorded_gate_context["evidence"]["manifest_claims"]] == ["ev_000_02_contract_step"]
    assert recorded_gate_context["evidence"]["manifest_claims"][0]["verification_status"] == "run_artifact"


def test_evidence_query_filters_canonical_ledger_before_recent_prompt_window(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    recorded_gate_context: dict = {}
    recorded_gate_prompt = ""

    class CanonicalEvidenceQueryExecutor(CodexExecutor):
        def execute(self, request, _emit_event, _should_stop, set_child_pid):
            nonlocal recorded_gate_prompt
            set_child_pid(None)
            if request.role_archetype == "inspector":
                payload = {
                    "execution_summary": {
                        "total_checks": 1,
                        "passed": 1,
                        "failed": 0,
                        "errored": 0,
                        "total_duration_ms": 50,
                    },
                    "check_results": [
                        {
                            "id": "early_inspector_evidence",
                            "title": "Early inspector evidence",
                            "status": "passed",
                            "notes": "The early inspector evidence remains the selected evidence query result.",
                        }
                    ],
                    "dynamic_checks": [],
                    "tester_observations": "Early inspector evidence.",
                    "coverage_results": [],
                }
            elif request.role_archetype == "builder":
                payload = {
                    "attempted": f"Produced filler step {request.step_id}.",
                    "summary": f"Filler step {request.step_id} completed.",
                    "changed_files": [],
                }
            else:
                context_packet = request.extra_context["context_packet"]
                recorded_gate_context.update(context_packet)
                recorded_gate_prompt = request.prompt
                payload = {
                    "passed": False,
                    "decision_summary": "The test only inspects filtered context.",
                    "feedback_to_builder": "No follow-up required for this context projection test.",
                    "blocking_issues": ["context_projection_test"],
                    "metrics": [],
                    "metric_scores": {},
                    "failed_check_ids": [],
                    "priority_failures": [],
                    "composite_score": 0.0,
                    "evidence_refs": [],
                    "evidence_claims": [],
                    "residual_risks": [],
                    "coverage_results": [],
                }
            request.output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return payload

    service = service_factory(scenario="success")
    service.executor_factory = CanonicalEvidenceQueryExecutor
    filler_steps = [{"id": f"filler_builder_{index:02d}", "role_id": "builder"} for index in range(45)]
    workflow = {
        "version": 1,
        "roles": [
            {"id": "inspector", "name": "Inspector", "archetype": "inspector", "prompt_ref": "inspector.md"},
            {"id": "builder", "name": "Builder", "archetype": "builder", "prompt_ref": "builder.md"},
            {"id": "gatekeeper", "name": "GateKeeper", "archetype": "gatekeeper", "prompt_ref": "gatekeeper.md"},
        ],
        "steps": [
            {"id": "inspector_step", "role_id": "inspector"},
            *filler_steps,
            {
                "id": "gatekeeper_step",
                "role_id": "gatekeeper",
                "on_pass": "finish_run",
                "inputs": {
                    "handoffs_from": ["inspector_step"],
                    "evidence_query": {"archetypes": ["inspector"], "limit": 1},
                },
            },
        ],
    }
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Canonical Evidence Query Loop", workflow=workflow, max_iters=1)

    service.rerun(loop["id"])

    assert [item["step_id"] for item in recorded_gate_context["evidence"]["items"]] == ["inspector_step"]
    assert recorded_gate_context["evidence"]["known_ids"] == ["ev_000_00_inspector_step"]
    assert recorded_gate_context["evidence"]["manifest_summary"]["claim_count"] == 1
    assert [item["id"] for item in recorded_gate_context["evidence"]["manifest_claims"]] == ["ev_000_00_inspector_step"]
    assert 'Known ids: ["ev_000_00_inspector_step"]' in recorded_gate_prompt
    assert "ev_000_01_filler_builder_00" not in recorded_gate_prompt


def test_gatekeeper_validates_older_known_evidence_ref_from_canonical_ledger(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    target_ref = "ev_000_00_inspector_step"

    class OlderEvidenceRefExecutor(CodexExecutor):
        def execute(self, request, _emit_event, _should_stop, set_child_pid):
            set_child_pid(None)
            iter_id = int(request.extra_context.get("iter_id") or 0)
            if request.role_archetype == "inspector":
                payload = {
                    "execution_summary": {
                        "total_checks": 2,
                        "passed": 2,
                        "failed": 0,
                        "errored": 0,
                        "total_duration_ms": 50,
                    },
                    "check_results": [
                        {
                            "id": "check_001",
                            "title": "Primary experience",
                            "status": "passed",
                            "notes": "The first run already proved the primary experience.",
                        },
                        {
                            "id": "check_002",
                            "title": "Edge path",
                            "status": "passed",
                            "notes": "The first run already proved the edge path.",
                        },
                    ],
                    "dynamic_checks": [],
                    "tester_observations": f"Inspector evidence for iteration {iter_id}.",
                    "coverage_results": [],
                }
            else:
                passed = iter_id >= 21
                payload = {
                    "passed": passed,
                    "decision_summary": "Older inspector evidence remains valid." if passed else "Keep accumulating iterations.",
                    "feedback_to_builder": "",
                    "blocking_issues": [],
                    "metrics": [
                        {"name": "quality_score", "value": 1.0 if passed else 0.4, "threshold": 0.9, "passed": passed},
                    ],
                    "failed_check_ids": [],
                    "priority_failures": [],
                    "composite_score": 1.0 if passed else 0.4,
                    "evidence_refs": [target_ref] if passed else [],
                    "evidence_claims": ["The older inspector evidence id was cited after it fell out of the prompt item summary."] if passed else [],
                }
            request.output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return payload

    service = service_factory(scenario="success")
    service.executor_factory = OlderEvidenceRefExecutor
    workflow = {
        "version": 1,
        "roles": [
            {"id": "inspector", "name": "Inspector", "archetype": "inspector", "prompt_ref": "inspector.md"},
            {"id": "gatekeeper", "name": "GateKeeper", "archetype": "gatekeeper", "prompt_ref": "gatekeeper.md"},
        ],
        "steps": [
            {"id": "inspector_step", "role_id": "inspector"},
            {"id": "gatekeeper_step", "role_id": "gatekeeper", "on_pass": "finish_run"},
        ],
    }
    loop = _create_loop(
        service,
        sample_spec_file,
        sample_workdir,
        name="Older Evidence Ref Loop",
        max_iters=22,
        workflow=workflow,
    )

    run = service.rerun(loop["id"])
    run_dir = Path(run["runs_dir"])
    gatekeeper_output = _step_outputs_by_archetype(run_dir)["gatekeeper"][-1]["output"]
    final_context = json.loads((run_dir / "iterations" / "iter_021" / "steps" / "01__gatekeeper_step" / "input.context.json").read_text(encoding="utf-8"))

    assert target_ref in final_context["evidence"]["known_ids"]
    assert target_ref not in {item["id"] for item in final_context["evidence"]["items"]}
    assert run["status"] == "succeeded"
    assert gatekeeper_output["passed"] is True
    assert gatekeeper_output["evidence_gate_status"] == "passed"
    assert gatekeeper_output["evidence_refs"] == [target_ref]


def test_triage_first_workflow_runs_inspector_then_guide_then_builder(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = _create_loop(
        service,
        sample_spec_file,
        sample_workdir,
        name="Triage First Loop",
        workflow={"preset": "triage_first"},
    )

    run = service.rerun(loop["id"])

    assert run["status"] == "succeeded"
    assert run["workflow_json"]["preset"] == "triage_first"
    assert [step["role_id"] for step in run["workflow_json"]["steps"][:4]] == ["inspector", "guide", "builder", "gatekeeper"]
    iteration_log = [json.loads(line) for line in (Path(run["runs_dir"]) / "iteration_log.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    workflow_entry = next(entry for entry in iteration_log if entry["phase"] == "complete")
    assert [step["archetype"] for step in workflow_entry["workflow"][:4]] == [
        "inspector",
        "guide",
        "builder",
        "gatekeeper",
    ]


def test_fast_lane_workflow_runs_builder_before_gatekeeper(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = _create_loop(
        service,
        sample_spec_file,
        sample_workdir,
        name="Fast Lane Loop",
        workflow={"preset": "fast_lane"},
    )

    run = service.rerun(loop["id"])

    assert run["status"] == "succeeded"
    assert run["workflow_json"]["preset"] == "fast_lane"
    iteration_log = [json.loads(line) for line in (Path(run["runs_dir"]) / "iteration_log.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    workflow_entry = next(entry for entry in iteration_log if entry["phase"] == "complete")
    assert [step["archetype"] for step in workflow_entry["workflow"][:2]] == ["builder", "gatekeeper"]


def test_workflow_step_model_override_is_used_for_role_requests(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    workflow = {
        "version": 1,
        "roles": [
            {"id": "builder", "name": "Builder", "archetype": "builder", "prompt_ref": "builder.md"},
            {"id": "gatekeeper", "name": "GateKeeper", "archetype": "gatekeeper", "prompt_ref": "gatekeeper.md"},
        ],
        "steps": [
            {"id": "builder_step", "role_id": "builder", "model": "gpt-5.4-mini"},
            {"id": "gatekeeper_step", "role_id": "gatekeeper", "on_pass": "finish_run"},
        ],
    }
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Step Model Loop", workflow=workflow)

    run = service.rerun(loop["id"])

    role_requests = _read_jsonl(Path(run["runs_dir"]) / "context" / "role_requests.jsonl")
    builder_request = next(item for item in role_requests if item.get("step_id") == "builder_step")
    assert builder_request["model"] == "gpt-5.4-mini"


def test_workflow_roles_can_use_distinct_executor_snapshots(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    workflow = {
        "version": 1,
        "roles": [
            {
                "id": "builder",
                "name": "Builder",
                "archetype": "builder",
                "prompt_ref": "builder.md",
                "executor_kind": "codex",
                "executor_mode": "preset",
                "model": "gpt-5.4-mini",
                "reasoning_effort": "high",
            },
            {
                "id": "custom_helper",
                "name": "Custom Helper",
                "archetype": "custom",
                "prompt_ref": "custom.md",
                "executor_kind": "claude",
                "executor_mode": "preset",
                "model": "",
                "reasoning_effort": "high",
            },
        ],
        "steps": [
            {"id": "builder_step", "role_id": "builder"},
            {"id": "custom_step", "role_id": "custom_helper"},
        ],
    }

    loop = _create_loop(
        service,
        sample_spec_file,
        sample_workdir,
        name="Per Role Executor Loop",
        workflow=workflow,
        completion_mode="rounds",
        max_iters=1,
    )
    run = service.rerun(loop["id"])

    role_requests = _read_jsonl(Path(run["runs_dir"]) / "context" / "role_requests.jsonl")
    builder_request = next(item for item in role_requests if item.get("step_id") == "builder_step")
    custom_request = next(item for item in role_requests if item.get("step_id") == "custom_step")

    assert builder_request["executor_kind"] == "codex"
    assert builder_request["model"] == "gpt-5.4-mini"
    assert custom_request["executor_kind"] == "claude"
    assert custom_request["role_archetype"] == "custom"


def test_custom_role_outputs_platform_takeaway_fields(service_factory, sample_spec_file: Path, sample_workdir: Path) -> None:
    class CustomTakeawayExecutor(CodexExecutor):
        def execute(self, request, _emit_event, _should_stop, set_child_pid):
            set_child_pid(None)
            if request.role_archetype == "custom":
                payload = {
                    "status": "blocked",
                    "summary": "Custom Helper found one unresolved integration assumption.",
                    "blocking_items": ["The landing copy claims analytics-backed evidence without a matching source file."],
                    "recommended_next_action": "Either add the missing evidence source or tone down the claim before GateKeeper runs.",
                    "observations": [
                        "The current draft reads as if telemetry already exists.",
                    ],
                    "recommendations": [
                        "Tighten the claim to match the current workspace evidence.",
                    ],
                    "risks": [
                        "GateKeeper may reject unsupported claims.",
                    ],
                    "handoff_note": "Pass this to Builder before the next verification step.",
                }
            else:
                payload = {
                    "passed": False,
                    "decision_summary": "The custom helper surfaced a blocker that still needs a fix.",
                    "feedback_to_builder": "Resolve the unsupported claim first.",
                    "blocking_issues": ["unsupported_claim"],
                    "metrics": [],
                    "metric_scores": {},
                    "failed_check_ids": [],
                    "priority_failures": [],
                    "composite_score": 0.35,
                    "hard_constraint_violations": [],
                    "feedback_to_generator": "Resolve the unsupported claim first.",
                }
            request.output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return payload

    service = service_factory(scenario="success")
    service.executor_factory = CustomTakeawayExecutor
    workflow = {
        "version": 1,
        "roles": [
            {"id": "custom_helper", "name": "Custom Helper", "archetype": "custom", "prompt_ref": "custom.md"},
            {"id": "gatekeeper", "name": "GateKeeper", "archetype": "gatekeeper", "prompt_ref": "gatekeeper.md"},
        ],
        "steps": [
            {"id": "custom_step", "role_id": "custom_helper"},
            {"id": "gatekeeper_step", "role_id": "gatekeeper"},
        ],
    }
    loop = _create_loop(
        service,
        sample_spec_file,
        sample_workdir,
        name="Custom Takeaway Loop",
        workflow=workflow,
        completion_mode="rounds",
        max_iters=1,
    )

    run = service.rerun(loop["id"])
    custom_handoff = json.loads((Path(run["runs_dir"]) / "iterations" / "iter_000" / "steps" / "00__custom_step" / "handoff.json").read_text(encoding="utf-8"))

    assert custom_handoff["status"] == "blocked"
    assert custom_handoff["summary"] == "Custom Helper found one unresolved integration assumption."
    assert custom_handoff["blocking_items"] == ["The landing copy claims analytics-backed evidence without a matching source file."]
    assert custom_handoff["recommended_next_action"] == ("Either add the missing evidence source or tone down the claim before GateKeeper runs.")


def test_round_completion_mode_can_finish_without_gatekeeper(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    workflow = {
        "version": 1,
        "roles": [
            {"id": "builder", "name": "Builder", "archetype": "builder", "prompt_ref": "builder.md"},
        ],
        "steps": [
            {"id": "builder_step", "role_id": "builder"},
        ],
    }
    loop = _create_loop(
        service,
        sample_spec_file,
        sample_workdir,
        name="Round Loop",
        workflow=workflow,
        completion_mode="rounds",
        max_iters=2,
    )

    run = service.rerun(loop["id"])

    assert run["status"] == "succeeded"
    assert run["run_status"] == "succeeded"
    assert run["task_verdict"]["status"] == "insufficient_evidence"
    assert run["task_verdict"]["source"] == "rounds_completion"
    iteration_log = _read_jsonl(Path(run["runs_dir"]) / "iteration_log.jsonl")
    assert len([entry for entry in iteration_log if entry["phase"] == "complete"]) == 2
    events = service.stream_events(run["id"], limit=200)
    assert any(
        event["event_type"] == "run_finished"
        and event["payload"].get("reason") == "rounds_completed"
        and event["payload"]["task_verdict_status"] == "insufficient_evidence"
        and event["payload"]["task_verdict_source"] == "rounds_completion"
        for event in events
    )


def test_failed_run_without_verdict_is_not_evaluated(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Failed Without Verdict Loop")
    run = service.start_run(loop["id"])

    service.repository.update_run(run["id"], status="failed", error_message="setup failed before evidence")
    refreshed = service.get_run(run["id"])

    assert refreshed["run_status"] == "failed"
    assert refreshed["task_verdict"]["status"] == "not_evaluated"
    assert refreshed["task_verdict"]["source"] == "run_status"


def test_iteration_interval_emits_wait_events_between_rounds(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    workflow = {
        "version": 1,
        "roles": [
            {"id": "builder", "name": "Builder", "archetype": "builder", "prompt_ref": "builder.md"},
        ],
        "steps": [
            {"id": "builder_step", "role_id": "builder"},
        ],
    }
    loop = _create_loop(
        service,
        sample_spec_file,
        sample_workdir,
        name="Timed Round Loop",
        workflow=workflow,
        completion_mode="rounds",
        max_iters=2,
        iteration_interval_seconds=0.01,
    )

    run = service.rerun(loop["id"])

    events = service.stream_events(run["id"], limit=200)
    assert any(event["event_type"] == "iteration_wait_started" for event in events)
    assert any(event["event_type"] == "iteration_wait_finished" for event in events)


def test_destructive_generator_is_blocked_by_workspace_guard(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    (sample_workdir / "notes.txt").write_text("keep me\n", encoding="utf-8")
    (sample_workdir / "src").mkdir()
    (sample_workdir / "src" / "app.js").write_text("console.log('hi')\n", encoding="utf-8")

    service = service_factory(scenario="destructive_generator")
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Guarded Loop")

    run = service.rerun(loop["id"])

    run_dir = Path(run["runs_dir"])
    guard = json.loads((run_dir / "workspace_guard.json").read_text(encoding="utf-8"))

    assert run["status"] == "failed"
    assert "workspace safety guard" in (run["error_message"] or "")
    assert guard["baseline_file_count"] == 3
    assert guard["remaining_original_file_count"] == 0
    assert guard["deleted_original_count"] == 3
    assert "progress.md" in guard["deleted_original_paths"]
    assert "Execution stopped by the workspace safety guard." in (run_dir / "summary.md").read_text(encoding="utf-8")
    events = service.stream_events(run["id"], limit=200)
    assert any(event["event_type"] == "run_aborted" for event in events)
    assert any(
        event["event_type"] == "run_finished"
        and event["payload"]["status"] == "failed"
        and event["payload"]["reason"] == "workspace_safety_guard"
        and event["payload"]["task_verdict_status"] == "failed"
        for event in events
    )


def test_workspace_guard_ignores_generated_cache_deletions(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    (sample_workdir / "src").mkdir()
    (sample_workdir / "src" / "app.py").write_text("print('keep')\n", encoding="utf-8")
    (sample_workdir / ".pytest_cache" / "v" / "cache").mkdir(parents=True)
    (sample_workdir / ".pytest_cache" / "v" / "cache" / "nodeids").write_text("[]\n", encoding="utf-8")
    (sample_workdir / ".ruff_cache").mkdir()
    (sample_workdir / ".ruff_cache" / "metadata.json").write_text("{}\n", encoding="utf-8")
    (sample_workdir / ".coverage").write_text("coverage data\n", encoding="utf-8")

    service = service_factory(scenario="success")
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Cache Cleanup Loop")
    run = service.start_run(loop["id"])
    run_dir = Path(run["runs_dir"])
    baseline = json.loads((run_dir / "contract" / "workspace_baseline.json").read_text(encoding="utf-8"))

    assert "src/app.py" in baseline["files"]
    assert "progress.md" in baseline["files"]
    assert not any(path.startswith(".pytest_cache/") for path in baseline["files"])
    assert not any(path.startswith(".ruff_cache/") for path in baseline["files"])
    assert ".coverage" not in baseline["files"]

    shutil.rmtree(sample_workdir / ".pytest_cache")
    shutil.rmtree(sample_workdir / ".ruff_cache")
    (sample_workdir / ".coverage").unlink()

    service._enforce_workspace_safety(run, run_dir, 0, role="builder")

    assert not (run_dir / "workspace_guard.json").exists()
    assert not (run_dir / "timeline" / "workspace_guard.json").exists()
    assert not any(event["event_type"] == "workspace_guard_triggered" for event in service.stream_events(run["id"], limit=10))


def test_workspace_guard_fails_closed_when_baseline_is_missing_or_malformed(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    (sample_workdir / "src").mkdir()
    (sample_workdir / "src" / "app.py").write_text("print('keep')\n", encoding="utf-8")

    service = service_factory(scenario="success")
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Missing Baseline Loop")
    run = service.start_run(loop["id"])
    run_dir = Path(run["runs_dir"])
    baseline_path = RunArtifactLayout(run_dir).workspace_baseline_path

    baseline_path.unlink()
    with pytest.raises(LooporaError, match="workspace safety baseline"):
        service._enforce_workspace_safety(run, run_dir, 0, role="builder")

    baseline_path.write_text("{not json}\n", encoding="utf-8")
    with pytest.raises(LooporaError, match="workspace safety baseline"):
        service._enforce_workspace_safety(run, run_dir, 0, role="builder")

    baseline_path.write_text('{"files": [42]}\n', encoding="utf-8")
    with pytest.raises(LooporaError, match="workspace safety baseline"):
        service._enforce_workspace_safety(run, run_dir, 0, role="builder")


def test_destructive_tester_is_blocked_by_workspace_guard(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    (sample_workdir / "notes.txt").write_text("keep me\n", encoding="utf-8")
    (sample_workdir / "src").mkdir()
    (sample_workdir / "src" / "app.js").write_text("console.log('hi')\n", encoding="utf-8")

    service = service_factory(scenario="destructive_tester")
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Guarded Tester Loop")

    run = service.rerun(loop["id"])

    run_dir = Path(run["runs_dir"])
    guard = json.loads((run_dir / "workspace_guard.json").read_text(encoding="utf-8"))

    assert run["status"] == "failed"
    assert "workspace safety guard" in (run["error_message"] or "")
    assert guard["role"] == "contract_inspector"
    assert guard["deleted_original_count"] == 3


def test_exploratory_run_generates_and_freezes_checks(
    service_factory,
    exploratory_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = _create_loop(service, exploratory_spec_file, sample_workdir, name="Exploratory Loop")

    run = service.rerun(loop["id"])

    run_dir = Path(run["runs_dir"])
    compiled_spec = json.loads((run_dir / "contract" / "compiled_spec.json").read_text(encoding="utf-8"))
    auto_checks = json.loads((run_dir / "contract" / "auto_checks.json").read_text(encoding="utf-8"))
    tester_output = json.loads((run_dir / "tester_output.json").read_text(encoding="utf-8"))

    assert compiled_spec["check_mode"] == "auto_generated"
    assert len(compiled_spec["checks"]) >= 3
    assert any(target["id"] == "done_when.check_001" for target in compiled_spec["coverage_targets"])
    assert auto_checks["count"] == len(compiled_spec["checks"])
    assert tester_output["execution_summary"]["total_checks"] == len(compiled_spec["checks"])
    assert tester_output["check_results"]


def test_generated_check_normalization_requires_object_items(service_factory) -> None:
    service = service_factory(scenario="success")

    assert service._normalize_generated_checks("not a list") == []

    checks = service._normalize_generated_checks(
        [
            "not an object",
            {
                "title": "Primary outcome",
                "details": "The run has a concrete proof path.",
                "when": "After Builder finishes.",
                "expect": "Proof is present.",
                "fail_if": "Proof is missing.",
            },
        ]
    )

    assert checks == [
        {
            "id": "check_001",
            "title": "Primary outcome",
            "details": "The run has a concrete proof path.",
            "when": "After Builder finishes.",
            "expect": "Proof is present.",
            "fail_if": "Proof is missing.",
            "source": "auto_generated",
        }
    ]


def test_same_workdir_concurrent_run_is_rejected(service_factory, sample_spec_file: Path, sample_workdir: Path) -> None:
    service = service_factory(scenario="success", role_delay=0.4)
    first_loop = _create_loop(service, sample_spec_file, sample_workdir, name="First")
    second_loop = _create_loop(service, sample_spec_file, sample_workdir, name="Second")

    first_run = service.start_run(first_loop["id"])
    service.start_run_async(first_run["id"])

    try:
        deadline = time.time() + 5
        while time.time() < deadline:
            status = service.get_run(first_run["id"])["status"]
            if status == "running":
                break
            time.sleep(0.05)

        with pytest.raises(LooporaError):
            service.start_run(second_loop["id"])
    finally:
        if service.get_run(first_run["id"])["status"] in {"queued", "running"}:
            service.stop_run(first_run["id"])
            _wait_for_terminal_run(service, first_run["id"])
        _join_async_run(service, first_run["id"])


def test_start_run_async_rejects_duplicate_local_dispatch(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success", role_delay=0.4)
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Duplicate Async Dispatch")
    run = service.start_run(loop["id"])
    service.start_run_async(run["id"])

    try:
        with pytest.raises(LooporaError, match="already executing in this process"):
            service.start_run_async(run["id"])
    finally:
        current = service.get_run(run["id"])
        if current["status"] in {"queued", "running"}:
            service.stop_run(run["id"])
            _wait_for_terminal_run(service, run["id"])
        _join_async_run(service, run["id"])


def test_execute_run_rejects_duplicate_local_worker(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success", role_delay=0.4)
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Duplicate Worker")
    run = service.start_run(loop["id"])

    thread = threading.Thread(target=service.execute_run, args=(run["id"],), daemon=True)
    thread.start()

    try:
        deadline = time.time() + 5
        while time.time() < deadline and not service._is_run_active_locally(run["id"]):
            time.sleep(0.01)

        with pytest.raises(LooporaError, match="already executing in this process"):
            service.execute_run(run["id"])
    finally:
        current = service.get_run(run["id"])
        if current["status"] in {"queued", "running"}:
            service.stop_run(run["id"])
            _wait_for_terminal_run(service, run["id"])
        thread.join(timeout=5)


def test_stop_run_marks_run_stopped(service_factory, sample_spec_file: Path, sample_workdir: Path) -> None:
    service = service_factory(scenario="success", role_delay=0.5)
    loop = _create_loop(service, sample_spec_file, sample_workdir)
    run = service.start_run(loop["id"])

    thread = threading.Thread(target=service.execute_run, args=(run["id"],), daemon=True)
    thread.start()

    deadline = time.time() + 5
    saw_generator_start = False
    while time.time() < deadline:
        current = service.get_run(run["id"])
        events = service.repository.list_events(run["id"], after_id=0, limit=50)
        saw_generator_start = any(event["event_type"] == "role_started" and event.get("role") == "generator" for event in events)
        if current["status"] == "running" and saw_generator_start:
            break
        time.sleep(0.05)

    service.stop_run(run["id"])
    thread.join(timeout=5)

    stopped = service.get_run(run["id"])
    assert stopped["status"] == "stopped"


def test_stop_requested_run_does_not_retry_the_active_role(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    class StopAwareExecutor(CodexExecutor):
        def execute(self, _request, _emit_event, should_stop, _set_child_pid):
            deadline = time.time() + 0.4
            while time.time() < deadline:
                if should_stop():
                    raise ExecutorError("terminated after stop request")
                time.sleep(0.01)
            return {
                "attempted": "noop",
                "abandoned": "",
                "assumption": "",
                "summary": "",
                "changed_files": [],
            }

    service = service_factory(scenario="success")
    service.executor_factory = StopAwareExecutor
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Stop Retry Guard")
    run = service.start_run(loop["id"])

    thread = threading.Thread(target=service.execute_run, args=(run["id"],), daemon=True)
    thread.start()

    deadline = time.time() + 5
    saw_generator_start = False
    while time.time() < deadline:
        current = service.get_run(run["id"])
        events = service.repository.list_events(run["id"], after_id=0, limit=50)
        saw_generator_start = any(event["event_type"] == "role_started" and event.get("role") == "generator" for event in events)
        if current["status"] == "running" and saw_generator_start:
            break
        time.sleep(0.05)

    service.stop_run(run["id"])
    thread.join(timeout=5)

    stopped = service.get_run(run["id"])
    assert stopped["status"] == "stopped"

    events = service.repository.list_events(run["id"], after_id=0, limit=200)
    generator_starts = [event for event in events if event["event_type"] == "role_started" and event.get("role") == "generator"]
    assert saw_generator_start is True
    assert len(generator_starts) == 1


def test_zero_max_iters_runs_until_stopped(service_factory, sample_spec_file: Path, sample_workdir: Path) -> None:
    service = service_factory(scenario="plateau", role_delay=0.02)
    loop = service.create_loop(
        name="Infinite Loop",
        spec_path=sample_spec_file,
        workdir=sample_workdir,
        model="gpt-5.4",
        reasoning_effort="medium",
        max_iters=0,
        max_role_retries=1,
        delta_threshold=0.005,
        trigger_window=2,
        regression_window=2,
        role_models={},
    )
    run = service.start_run(loop["id"])
    service.start_run_async(run["id"])

    deadline = time.time() + 5
    while time.time() < deadline:
        current = service.get_run(run["id"])
        if current["current_iter"] >= 2:
            break
        time.sleep(0.05)

    current = service.get_run(run["id"])
    assert current["status"] in {"queued", "running"}
    assert current["current_iter"] >= 2

    service.stop_run(run["id"])

    stopped = _wait_for_terminal_run(service, run["id"])
    _join_async_run(service, run["id"])
    assert stopped["status"] == "stopped"


def test_async_run_cleans_up_thread_bookkeeping(service_factory, sample_spec_file: Path, sample_workdir: Path) -> None:
    service = service_factory(scenario="success", role_delay=0.01)
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Async Loop")
    run = service.start_run(loop["id"])
    service.start_run_async(run["id"])

    deadline = time.time() + 5
    while time.time() < deadline:
        current = service.get_run(run["id"])
        if current["status"] in {"succeeded", "failed", "stopped"}:
            break
        time.sleep(0.05)

    finished = service.get_run(run["id"])
    assert finished["status"] == "succeeded"
    assert run["id"] not in service._threads


def test_execute_run_returns_terminal_run_without_active_runtime_markers(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Runtime Marker Cleanup Loop")
    run = service.start_run(loop["id"])

    finished = service.execute_run(run["id"])

    assert finished["status"] == "succeeded"
    assert finished["active_role"] is None
    assert finished["runner_pid"] is None
    assert finished["child_pid"] is None
    stored = service.repository.get_run(run["id"])
    assert stored["active_role"] is None
    assert stored["runner_pid"] is None
    assert stored["child_pid"] is None


def test_get_run_reaps_finished_thread_handle(service_factory, sample_spec_file: Path, sample_workdir: Path) -> None:
    service = service_factory(scenario="success")
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Reap Thread Loop")
    run = service.start_run(loop["id"])
    service.repository.update_run(
        run["id"],
        status="succeeded",
        finished_at="2026-04-18T11:00:00+00:00",
        summary_md="# done",
    )

    completed = threading.Thread(target=lambda: None, name="completed-run-thread")
    completed.start()
    completed.join()
    service._threads[run["id"]] = completed

    finished = service.get_run(run["id"])

    assert finished["status"] == "succeeded"
    assert run["id"] not in service._threads


def test_unexpected_run_error_marks_run_failed(service_factory, sample_spec_file: Path, sample_workdir: Path) -> None:
    service = service_factory(scenario="success")
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Crash Loop")
    run = service.start_run(loop["id"])

    def explode(*_args, **_kwargs):
        raise RuntimeError("boom")

    service._resolve_run_checks = explode  # type: ignore[method-assign]

    failed = service.execute_run(run["id"])

    assert failed["status"] == "failed"
    assert failed["error_message"] == "boom"
    summary = Path(failed["runs_dir"]) / "summary.md"
    assert "Execution crashed unexpectedly." in summary.read_text(encoding="utf-8")
    events = service.repository.list_events(run["id"], after_id=0, limit=1000)
    assert any(event["event_type"] == "run_aborted" for event in events)
    assert any(
        event["event_type"] == "run_finished"
        and event["payload"]["status"] == "failed"
        and event["payload"]["reason"] == "crashed"
        and event["payload"]["task_verdict_status"] == "not_evaluated"
        for event in events
    )


def test_legacy_gatekeeper_run_exhausts_without_crashing(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="plateau")
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Legacy Plateau Loop")
    run = service.start_run(loop["id"])
    _force_run_into_legacy_mode(service, run["id"])

    failed = service.execute_run(run["id"])

    assert failed["status"] == "failed"
    assert failed["error_message"] in {None, ""}
    events = service.repository.list_events(run["id"], after_id=0, limit=1000)
    assert any(event["event_type"] == "run_finished" and event["payload"].get("reason") == "max_iters_exhausted" for event in events)
    assert all(event["event_type"] != "run_aborted" for event in events)


def test_empty_workflow_snapshot_dispatches_to_legacy_execution(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
    monkeypatch,
) -> None:
    service = service_factory(scenario="success")
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Legacy Dispatch Loop")
    run = service.start_run(loop["id"])
    _force_run_into_legacy_mode(service, run["id"])
    original_legacy_run = service._execute_legacy_run
    dispatched = {"legacy": False}

    def record_legacy_dispatch(run_id: str, run: dict, run_dir: Path) -> dict:
        dispatched["legacy"] = True
        return original_legacy_run(run_id, run, run_dir)

    monkeypatch.setattr(service, "_execute_legacy_run", record_legacy_dispatch)

    finished = service.execute_run(run["id"])

    assert dispatched["legacy"] is True
    assert finished["status"] == "succeeded"


def test_legacy_rounds_run_finishes_after_planned_iterations(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="plateau")
    loop = _create_loop(
        service,
        sample_spec_file,
        sample_workdir,
        name="Legacy Planned Rounds Loop",
        completion_mode="rounds",
        max_iters=2,
    )
    run = service.start_run(loop["id"])
    _force_run_into_legacy_mode(service, run["id"])

    finished = service.execute_run(run["id"])

    assert finished["status"] == "succeeded"
    assert finished["error_message"] in {None, ""}
    events = service.repository.list_events(run["id"], after_id=0, limit=1000)
    assert any(event["event_type"] == "run_finished" and event["payload"].get("reason") == "rounds_completed" for event in events)
    assert all(event["event_type"] != "run_aborted" for event in events)


def test_get_run_recovers_local_orphaned_active_run(service_factory, sample_spec_file: Path, sample_workdir: Path) -> None:
    service = service_factory(scenario="success")
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Orphan Loop")
    run = service.start_run(loop["id"])
    service._local_run_orphan_grace_seconds = lambda: 0.0  # type: ignore[method-assign]
    service.repository.update_run(
        run["id"],
        status="running",
        runner_pid=os.getpid(),
        active_role="generator",
        started_at="2026-04-13T08:00:00+00:00",
    )

    service._threads.pop(run["id"], None)

    recovered = service.get_run(run["id"])

    assert recovered["status"] == "failed"
    assert recovered["runner_pid"] is None
    assert recovered["child_pid"] is None
    assert "Recovered orphaned run" in (recovered["error_message"] or "")
    assert recovered["task_verdict"]["status"] == "not_evaluated"
    events = service.repository.list_events(run["id"], after_id=0, limit=1000)
    assert any(event["event_type"] == "run_aborted" for event in events)
    assert any(
        event["event_type"] == "run_finished"
        and event["payload"]["status"] == "failed"
        and event["payload"]["reason"] == "orphaned_worker"
        and event["payload"]["task_verdict_status"] == "not_evaluated"
        for event in events
    )


def test_second_service_instance_does_not_recover_run_active_in_same_process(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Shared Process Loop")
    run = service.start_run(loop["id"])
    service.repository.update_run(
        run["id"],
        status="running",
        runner_pid=os.getpid(),
        active_role="generator",
        started_at="2026-04-13T08:00:00+00:00",
    )
    service._mark_run_active(run["id"])

    try:
        restarted = LooporaService(
            repository=service.repository,
            settings=service.settings,
            executor_factory=service.executor_factory,
        )
        restarted._local_run_orphan_grace_seconds = lambda: 0.0  # type: ignore[method-assign]

        current = restarted.get_run(run["id"])

        assert current["status"] == "running"
        assert current["error_message"] in {None, ""}
    finally:
        service._mark_run_inactive(run["id"])


def test_second_service_instance_does_not_recover_queued_run_with_same_process_pid(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Queued Shared Process Loop")
    run = service.start_run(loop["id"])
    service.repository.update_run(
        run["id"],
        status="queued",
        runner_pid=os.getpid(),
        started_at="2026-04-13T08:00:00+00:00",
    )
    service._mark_run_active(run["id"])

    try:
        restarted = LooporaService(
            repository=service.repository,
            settings=service.settings,
            executor_factory=service.executor_factory,
        )
        restarted._local_run_orphan_grace_seconds = lambda: 0.0  # type: ignore[method-assign]

        current = restarted.get_run(run["id"])

        assert current["status"] == "queued"
        assert current["error_message"] in {None, ""}
    finally:
        service._mark_run_inactive(run["id"])


def test_second_service_instance_keeps_fresh_queued_run_without_runner_pid(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Fresh Queued Loop")
    run = service.start_run(loop["id"])

    restarted = LooporaService(
        repository=service.repository,
        settings=service.settings,
        executor_factory=service.executor_factory,
    )

    current = restarted.get_run(run["id"])

    assert current["status"] == "queued"
    assert current["error_message"] in {None, ""}


def test_early_execute_run_crash_is_persisted_as_failed(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Early Crash Loop")
    run = service.start_run(loop["id"])

    service.executor_factory = lambda: (_ for _ in ()).throw(RuntimeError("executor boot failed"))  # type: ignore[assignment]

    failed = service.execute_run(run["id"])

    assert failed["status"] == "failed"
    assert failed["error_message"] == "executor boot failed"
    assert run["id"] not in LooporaService._process_active_runs
    summary = Path(failed["runs_dir"]) / "summary.md"
    assert "Execution crashed unexpectedly." in summary.read_text(encoding="utf-8")


def test_stop_run_rejects_finished_runs(service_factory, sample_spec_file: Path, sample_workdir: Path) -> None:
    service = service_factory(scenario="success")
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Finished Loop")
    run = service.rerun(loop["id"])

    with pytest.raises(LooporaError, match="cannot stop run in status"):
        service.stop_run(run["id"])

    events = service.repository.list_events(run["id"], after_id=0, limit=1000)
    assert all(event["event_type"] != "stop_requested" for event in events)


def test_plateau_run_records_challenger_execution_summary(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="plateau")
    loop = _create_loop(
        service,
        sample_spec_file,
        sample_workdir,
        name="Plateau Loop",
        workflow={"preset": "repair_loop"},
        max_iters=4,
    )

    run = service.rerun(loop["id"])

    events = service.repository.list_events(run["id"], after_id=0, limit=1000)
    challenger_summaries = [event for event in events if event["event_type"] == "role_execution_summary" and event["payload"].get("role") == "challenger"]
    verifier_summaries = [event for event in events if event["event_type"] == "role_execution_summary" and event["payload"].get("role") == "verifier"]

    assert challenger_summaries
    assert verifier_summaries
    assert all(event["payload"]["duration_ms"] >= 0 for event in challenger_summaries + verifier_summaries)


def test_service_startup_marks_stale_active_runs_stopped(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Stale Loop")
    run = service.start_run(loop["id"])
    service.repository.update_run(
        run["id"],
        status="running",
        runner_pid=999999,
        active_role="tester",
        started_at="2026-04-13T08:00:00+00:00",
    )

    restarted = LooporaService(
        repository=service.repository,
        settings=service.settings,
        executor_factory=service.executor_factory,
    )
    recovered = restarted.get_run(run["id"])

    assert recovered["status"] == "stopped"
    assert recovered["finished_at"] is not None
    assert recovered["runner_pid"] is None
    assert recovered["child_pid"] is None
    assert "Recovered stale run" in (recovered["error_message"] or "")
    assert recovered["task_verdict"]["status"] == "not_evaluated"
    assert recovered["task_verdict"]["source"] == "run_status"
    assert json.loads((Path(recovered["runs_dir"]) / "evidence" / "task_verdict.json").read_text(encoding="utf-8")) == recovered["task_verdict"]

    events = restarted.repository.list_events(run["id"], after_id=0, limit=1000)
    assert any(
        event["event_type"] == "run_finished"
        and event["payload"].get("reason") == "Recovered stale run after service startup."
        and event["payload"]["task_verdict_status"] == "not_evaluated"
        and event["payload"]["task_verdict_source"] == "run_status"
        for event in events
    )

    fresh_run = restarted.rerun(loop["id"])
    assert fresh_run["status"] == "succeeded"
