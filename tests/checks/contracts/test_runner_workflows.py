from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from loopora.executor import CodexExecutor
from loopora.run_takeaways import build_run_key_takeaways

from runner_helpers import (
    _create_loop,
    _read_jsonl,
    _step_outputs_by_archetype,
)


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


def test_loop_rejects_gatekeeper_residual_risk_when_contract_disallows_acceptance(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    class DisallowedResidualRiskExecutor(CodexExecutor):
        def execute(self, request, _emit_event, _should_stop, set_child_pid):
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
                            "id": "check_001",
                            "title": "Primary experience",
                            "status": "passed",
                            "notes": "Primary path is proven.",
                        },
                    ],
                    "dynamic_checks": [],
                    "tester_observations": "The required check is covered.",
                    "coverage_results": [],
                }
            else:
                evidence_refs = [item["id"] for item in request.extra_context["context_packet"]["evidence"]["items"]]
                payload = {
                    "passed": True,
                    "decision_summary": "GateKeeper accepted a managed residual risk.",
                    "feedback_to_builder": "",
                    "blocking_issues": [],
                    "metrics": [
                        {"name": "quality_score", "value": 1.0, "threshold": 0.9, "passed": True},
                    ],
                    "failed_check_ids": [],
                    "priority_failures": [],
                    "composite_score": 1.0,
                    "evidence_refs": evidence_refs,
                    "evidence_claims": ["The inspector evidence covers the required check."],
                    "residual_risks": ["Manual billing export remains visible as a follow-up owned by Support."],
                }
            request.output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return payload

    service = service_factory(scenario="success")
    service.executor_factory = DisallowedResidualRiskExecutor
    spec_file = sample_spec_file.with_name("no_residual_risk_spec.md")
    spec_file.write_text(
        sample_spec_file.read_text(encoding="utf-8").replace(
            "Minor copy polish can wait, but unverifiable completion should fail closed.",
            "No residual risk is acceptable; any remaining risk must fail closed.",
        ),
        encoding="utf-8",
    )
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
        spec_file,
        sample_workdir,
        name="No Residual Risk Gate Loop",
        max_iters=1,
        workflow=workflow,
    )

    run = service.rerun(loop["id"])
    run_dir = Path(run["runs_dir"])
    gatekeeper_output = _step_outputs_by_archetype(run_dir)["gatekeeper"][-1]["output"]

    assert run["status"] == "failed"
    assert run["task_verdict"]["status"] == "failed"
    assert gatekeeper_output["passed"] is False
    assert gatekeeper_output["blocking_issues"] == ["gatekeeper_pass_violates_no_residual_risk_policy"]
    assert gatekeeper_output["residual_risks"] == ["Manual billing export remains visible as a follow-up owned by Support."]


def test_round_mode_carries_gatekeeper_residual_risk_into_next_iteration_prompt(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    second_builder_prompt = ""
    second_builder_context: dict = {}

    class ResidualRiskCarryForwardExecutor(CodexExecutor):
        def execute(self, request, _emit_event, _should_stop, set_child_pid):
            nonlocal second_builder_prompt, second_builder_context
            set_child_pid(None)
            iter_id = request.extra_context["iter_id"]
            if request.role_archetype == "builder":
                if iter_id == 1:
                    second_builder_prompt = request.prompt
                    second_builder_context = request.extra_context["context_packet"]
                payload = {
                    "attempted": "Built the primary slice.",
                    "summary": "Builder changed only the focused primary slice.",
                    "changed_files": [],
                    "proof_files": [],
                    "proof_artifacts": [],
                    "artifact_paths": [],
                }
            elif request.role_archetype == "inspector":
                payload = {
                    "execution_summary": {
                        "total_checks": 1,
                        "passed": 1,
                        "failed": 0,
                        "errored": 0,
                        "total_duration_ms": 20,
                    },
                    "check_results": [
                        {
                            "id": "primary_slice_check",
                            "title": "Primary slice check",
                            "status": "passed",
                            "notes": "Inspector produced direct evidence for the primary slice.",
                        }
                    ],
                    "dynamic_checks": [],
                    "tester_observations": "Inspector evidence covers the primary slice.",
                    "coverage_results": [],
                }
            else:
                context_packet = request.extra_context["context_packet"]
                evidence_refs = [
                    item["id"]
                    for item in context_packet["evidence"]["items"]
                    if item.get("archetype") == "inspector"
                ]
                payload = {
                    "passed": True,
                    "decision_summary": "GateKeeper passed with a managed residual risk in round mode.",
                    "feedback_to_builder": "Keep the named residual risk visible while continuing the next round.",
                    "blocking_issues": [],
                    "hard_constraint_violations": [],
                    "metrics": [],
                    "metric_scores": {
                        "check_pass_rate": {"value": 1.0, "threshold": 0.9, "passed": True},
                        "quality_score": {"value": 1.0, "threshold": 0.9, "passed": True},
                    },
                    "failed_check_ids": [],
                    "priority_failures": [],
                    "composite_score": 1.0,
                    "evidence_refs": evidence_refs,
                    "evidence_claims": ["Inspector proof covers the primary slice."],
                    "residual_risks": ["Manual copy polish remains visible as a follow-up owned by docs."],
                    "coverage_results": [],
                }
            request.output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return payload

    service = service_factory(scenario="success")
    service.executor_factory = ResidualRiskCarryForwardExecutor
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
            {"id": "gatekeeper_step", "role_id": "gatekeeper"},
        ],
    }
    loop = _create_loop(
        service,
        sample_spec_file,
        sample_workdir,
        name="Residual Risk Carry Forward Loop",
        workflow=workflow,
        completion_mode="rounds",
        max_iters=2,
    )

    run = service.rerun(loop["id"])
    run_dir = Path(run["runs_dir"])
    first_iteration_summary = json.loads((run_dir / "iterations" / "iter_000" / "summary.json").read_text(encoding="utf-8"))
    role_requests = _read_jsonl(run_dir / "context" / "role_requests.jsonl")
    second_builder_request = next(item for item in role_requests if item["role_archetype"] == "builder" and item["iter"] == 1)

    assert second_builder_prompt
    assert first_iteration_summary["gatekeeper_verdict"]["residual_risks"] == [
        "Manual copy polish remains visible as a follow-up owned by docs."
    ]
    assert second_builder_context["upstream"]["previous_iteration_summary"]["gatekeeper_verdict"]["residual_risks"] == [
        "Manual copy polish remains visible as a follow-up owned by docs."
    ]
    assert 'GateKeeper residual risks: ["Manual copy polish remains visible as a follow-up owned by docs."]' in second_builder_prompt
    assert "residual_risk=Manual copy polish remains visible as a follow-up owned by docs." in second_builder_prompt
    assert second_builder_request["context_summary"]["previous_iteration_summary"]["gatekeeper_residual_risk_count"] == 1


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
    assert latest_iteration_summary["stagnation"]["coverage_status"] == "blocked"
    assert latest_iteration_summary["stagnation"]["covered_check_count"] == 0
    assert latest_iteration_summary["stagnation"]["missing_check_count"] == 2
    assert latest_iteration_summary["stagnation"]["missing_check_ids"] == ["check_001", "check_002"]
    assert any(item["target_id"] == "done_when.check_001" for item in latest_iteration_summary["stagnation"]["coverage_top_gaps"])
    assert guide_request["context_summary"]["context_packet"]["evidence_progress_mode"] == "stalled"
    assert guide_request["context_summary"]["context_packet"]["coverage_status"] == "blocked"
    assert guide_request["context_summary"]["context_packet"]["covered_check_count"] == 0
    assert guide_request["context_summary"]["context_packet"]["missing_check_count"] == 2
    assert guide_request["context_summary"]["context_packet"]["missing_check_ids"] == ["check_001", "check_002"]
    assert any(item["target_id"] == "done_when.check_001" for item in guide_request["context_summary"]["context_packet"]["coverage_top_gaps"])
    assert "Evidence progress mode: stalled" in guide_prompt
    assert 'Missing required check ids: ["check_001", "check_002"]' in guide_prompt
    assert '"target_id": "done_when.check_001"' in guide_prompt
    assert "Required coverage: 0 covered, 2 missing" in guide_prompt
    assert latest_takeaway["evidence_progress_mode"] == "stalled"
    assert latest_takeaway["coverage_status"] == "blocked"
    assert latest_takeaway["covered_check_count"] == 0
    assert latest_takeaway["missing_check_count"] == 2
    assert latest_takeaway["missing_check_ids"] == ["check_001", "check_002"]
    assert any(item["target_id"] == "done_when.check_001" for item in latest_takeaway["coverage_top_gaps"])
    assert latest_takeaway["consecutive_no_required_coverage_delta"] == 1
    assert any(
        event["event_type"] == "control_triggered"
        and event["payload"]["signal"] == "no_evidence_progress"
        and "Required coverage did not improve" in event["payload"]["reason"]
        for event in events
    )
    assert any(entry["evidence_kind"] == "control" and "control:no_evidence_progress" in entry["verifies"] for entry in evidence_ledger)


@pytest.mark.parametrize("max_fires_per_run", [0, True, "2"])
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
    assert not any(event["event_type"] == "role_execution_summary" and event["payload"].get("archetype") == "gatekeeper" for event in events)


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
    assert not any(event["event_type"] == "role_execution_summary" and event["payload"].get("archetype") == "gatekeeper" for event in events)


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
    assert "gatekeeper_support=supporting" in recorded_gate_prompt
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
