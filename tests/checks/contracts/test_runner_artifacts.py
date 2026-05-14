from __future__ import annotations

import json
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
from loopora.executor import CodexExecutor, FakeCodexExecutor, build_command_event_payload
from loopora.run_artifacts import RunArtifactLayout
from loopora.service import LooporaError
from loopora.service_types import LooporaConflictError
from loopora.service_workflow_runtime import _manifest_prompt_context
from loopora.settings import app_home, configure_logging

from runner_helpers import (
    _assert_evidence_manifest,
    _assert_prompt_assets_contract_frozen,
    _assert_prompt_bucket_rules,
    _assert_prompt_evidence_fallback_rules,
    _assert_prompt_parallel_review_rules,
    _assert_runtime_contract_frozen_prefixes,
    _corrupt_loop_prompt_artifact,
    _corrupt_run_prompt_artifact,
    _create_loop,
    _read_jsonl,
    _runtime_prompt_assets,
    _step_outputs_by_archetype,
)


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
                    "consecutive_no_required_coverage_delta": request.extra_context["consecutive_no_required_coverage_delta"],
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


def test_builtin_prompts_define_runtime_evidence_fallback_rules() -> None:
    prompts, zh_prompts = _runtime_prompt_assets()

    _assert_prompt_evidence_fallback_rules(prompts, zh_prompts)
    _assert_prompt_parallel_review_rules(prompts, zh_prompts)
    _assert_prompt_bucket_rules(prompts, zh_prompts)
    assert "run status is not a task pass" in prompts["gatekeeper"]
    assert "run 正常结束不等于任务通过" in zh_prompts["gatekeeper"]
    assert "用稳定证据桶组织 Loop 裁决" in zh_prompts["gatekeeper"]
    assert "用稳定证据桶组织任务裁决" not in zh_prompts["gatekeeper"]
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
    assert '- Control evidence refs: ["ev_000_01_inspector_step"]' in prompt_frame


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
