from __future__ import annotations

from pathlib import Path

from loopora.context_flow import (
    IterationSummaryContext,
    StepResultContext,
    build_iteration_summary,
    build_step_handoff,
    render_handoff_list_section,
    render_previous_iteration_summary,
)
from loopora.run_artifacts import RunArtifactLayout
from loopora.service_workflow_support import ServiceWorkflowSupportMixin, WorkflowSummaryRequest
from loopora.stagnation import StagnationUpdateRequest, update_stagnation


def test_gatekeeper_output_rejects_unknown_evidence_refs() -> None:
    output = ServiceWorkflowSupportMixin()._coerce_gatekeeper_output(
        {
            "passed": True,
            "decision_summary": "Looks good.",
            "composite_score": 1.0,
            "evidence_refs": ["missing_ev"],
            "evidence_claims": ["A concrete claim that still points to an unknown evidence ref."],
        },
        evidence_context={"items": [{"id": "known_ev", "archetype": "inspector"}]},
        current_evidence_id="ev_gatekeeper",
    )

    assert output["passed"] is False
    assert output["composite_score"] == 0.89
    assert output["evidence_gate_status"] == "blocked"
    assert output["blocking_issues"] == ["gatekeeper_evidence_refs_unknown: missing_ev"]


def test_previous_iteration_summary_keeps_blocking_items_as_next_round_inputs() -> None:
    handoff = {
        "source": {
            "step_order": 1,
            "role_name": "GateKeeper",
            "archetype": "gatekeeper",
        },
        "status": "blocked",
        "summary": "Evidence is still weak.",
        "blocking_items": ["permission proof missing", "audit trail unproven"],
        "evidence_refs": ["ev_000_01_gatekeeper"],
        "recommended_next_action": "Produce direct permission and audit evidence.",
    }
    summary = {
        "iter": 0,
        "workflow": [{"step_id": "builder_step"}, {"step_id": "gatekeeper_step"}],
        "step_handoffs": [handoff],
        "score": {"composite": 0.42, "delta": None, "passed": False},
        "stagnation": {
            "mode": "none",
            "evidence_progress_mode": "stalled",
            "covered_check_count": 0,
            "missing_check_count": 2,
            "consecutive_no_required_coverage_delta": 1,
        },
    }

    rendered = render_previous_iteration_summary(summary)

    assert 'blocking=["permission proof missing", "audit trail unproven"]' in rendered
    assert "evidence=[\"ev_000_01_gatekeeper\"]" in rendered
    assert "next=Produce direct permission and audit evidence." in rendered


def test_completed_handoff_list_keeps_blocking_items_for_downstream_roles() -> None:
    rendered = render_handoff_list_section(
        "Completed steps in this iteration",
        [
            {
                "source": {
                    "step_order": 0,
                    "role_name": "Contract Inspector",
                    "archetype": "inspector",
                },
                "status": "blocked",
                "summary": "Authorization check did not run.",
                "blocking_items": ["authorization coverage missing"],
                "evidence_refs": ["ev_000_00_inspector"],
                "recommended_next_action": "Run the authorization proof before GateKeeper.",
            }
        ],
        empty_text="No earlier steps have completed in this iteration yet.",
    )

    assert 'blocking=["authorization coverage missing"]' in rendered
    assert "evidence=[\"ev_000_00_inspector\"]" in rendered
    assert "next=Run the authorization proof before GateKeeper." in rendered


def test_gatekeeper_handoff_projects_blocking_issues_and_hard_constraints(tmp_path: Path) -> None:
    layout = RunArtifactLayout(tmp_path / "run")
    layout.initialize()

    handoff = build_step_handoff(
        StepResultContext(
            layout=layout,
            iter_id=0,
            step={"id": "gatekeeper_step"},
            step_order=2,
            role={"id": "gatekeeper", "name": "GateKeeper", "archetype": "gatekeeper"},
            runtime_role="gatekeeper",
            output={
                "passed": False,
                "decision_summary": "Primary-flow evidence is not sufficient.",
                "feedback_to_builder": "Produce direct primary-flow proof before asking for closure.",
                "blocking_issues": ["primary_flow_unproven"],
                "hard_constraint_violations": ["audit_chain_missing"],
                "failed_check_ids": ["done_when.check_001"],
                "priority_failures": [{"summary": "Payment failure path has no traceable handoff."}],
            },
        )
    )

    assert handoff["status"] == "blocked"
    assert handoff["blocking_items"] == [
        "primary_flow_unproven",
        "audit_chain_missing",
        "done_when.check_001",
        "Payment failure path has no traceable handoff.",
    ]
    assert handoff["recommended_next_action"] == "Produce direct primary-flow proof before asking for closure."


def test_gatekeeper_output_rejects_unknown_coverage_result_evidence_refs() -> None:
    output = ServiceWorkflowSupportMixin()._coerce_gatekeeper_output(
        {
            "passed": True,
            "decision_summary": "The top-level verdict cites real evidence, but target coverage cites an invented ref.",
            "composite_score": 1.0,
            "evidence_refs": ["known_ev"],
            "evidence_claims": ["A concrete claim that cites the known upstream inspection evidence."],
            "coverage_results": [
                {
                    "target_id": "fake_done.risk_001",
                    "status": "covered",
                    "evidence_refs": ["invented_ev"],
                    "note": "This target-specific evidence ref is not in the known evidence set.",
                }
            ],
        },
        evidence_context={
            "items": [
                {
                    "id": "known_ev",
                    "archetype": "inspector",
                    "result": "passed",
                    "verifies": ["check_results:known_ev_check:passed"],
                }
            ]
        },
        current_evidence_id="ev_gatekeeper",
    )

    assert output["passed"] is False
    assert output["composite_score"] == 0.89
    assert output["evidence_gate_status"] == "blocked"
    assert output["blocking_issues"] == ["gatekeeper_coverage_evidence_refs_unknown: invented_ev"]


def test_gatekeeper_output_allows_first_gate_measured_evidence_claim() -> None:
    output = ServiceWorkflowSupportMixin()._coerce_gatekeeper_output(
        {
            "passed": True,
            "decision_summary": "",
            "metric_scores": {
                "quality_score": {"value": 0.95, "threshold": 0.9, "passed": True},
            },
            "evidence_claims": ["Measured benchmark evidence satisfied the first GateKeeper pass."],
        },
        evidence_context={"items": []},
        current_evidence_id="ev_gatekeeper",
    )

    assert output["passed"] is True
    assert output["decision_summary"] == "All checks passed."
    assert output["evidence_refs"] == ["ev_gatekeeper"]
    assert output["evidence_gate_status"] == "passed"


def test_gatekeeper_output_requires_literal_boolean_pass() -> None:
    output = ServiceWorkflowSupportMixin()._coerce_gatekeeper_output(
        {
            "passed": "true",
            "decision_summary": "Looks good.",
            "metric_scores": {
                "quality_score": {"value": 0.95, "threshold": 0.9, "passed": "true"},
            },
            "evidence_claims": ["Measured benchmark evidence satisfied the first GateKeeper pass."],
        },
        evidence_context={"items": []},
        current_evidence_id="ev_gatekeeper",
    )

    assert output["passed"] is False
    assert output["metric_scores"]["quality_score"]["passed"] is False
    assert output["metrics"][0]["passed"] is False
    assert output["evidence_refs"] == []
    assert output["evidence_gate_status"] == "not_passed"


def test_gatekeeper_output_default_composite_requires_literal_boolean_pass() -> None:
    output = ServiceWorkflowSupportMixin()._coerce_gatekeeper_output(
        {
            "passed": "true",
            "decision_summary": "A string pass should not set the fallback score.",
            "evidence_claims": ["String boolean values are not measured proof."],
        },
        evidence_context={"items": []},
        current_evidence_id="ev_gatekeeper",
    )

    assert output["passed"] is False
    assert output["composite_score"] == 0.0
    assert output["evidence_gate_status"] == "not_passed"


def test_workflow_summary_requires_literal_gatekeeper_passed_boolean(tmp_path: Path) -> None:
    class WorkflowSupportHarness(ServiceWorkflowSupportMixin):
        @staticmethod
        def _truncate_text(value: str | None, max_length: int = 220) -> str:
            return str(value or "")[:max_length]

    service = WorkflowSupportHarness()
    gatekeeper_step_result = {
        "step": {"id": "gatekeeper_step"},
        "step_order": 0,
        "role": {"id": "gatekeeper", "name": "GateKeeper", "archetype": "gatekeeper"},
        "runtime_role": "verifier",
        "output": {
            "passed": "true",
            "decision_summary": "String pass must remain blocked in summary projections.",
            "composite_score": 1.0,
            "evidence_refs": [],
        },
    }

    entry = service._build_workflow_iteration_entry(
        0,
        [gatekeeper_step_result],
        {"stagnation_mode": "none"},
        previous_composite=None,
    )
    summary = service._build_workflow_summary(
        WorkflowSummaryRequest(
            run={"workdir": str(tmp_path), "completion_mode": "gatekeeper", "iteration_interval_seconds": 0.0},
            workflow={"preset": "custom"},
            compiled_spec={"checks": [], "check_mode": "specified"},
            iter_id=0,
            step_results=[gatekeeper_step_result],
            stagnation={"stagnation_mode": "none"},
            exhausted=False,
            previous_composite=None,
        )
    )

    assert entry["score"]["passed"] is False
    assert "- Passed: `False`" in summary
    assert "Still iterating." in summary
    assert "All checks passed in this iteration." not in summary


def test_iteration_summaries_require_literal_score_numbers(tmp_path: Path) -> None:
    layout = RunArtifactLayout(tmp_path / "run")
    layout.initialize()
    gatekeeper_step_result = {
        "step": {"id": "gatekeeper_step"},
        "step_order": 0,
        "role": {"id": "gatekeeper", "name": "GateKeeper", "archetype": "gatekeeper"},
        "runtime_role": "verifier",
        "output": {
            "passed": False,
            "decision_summary": "String scores should not enter iteration context.",
            "composite_score": "0.95",
            "evidence_refs": [],
        },
        "handoff": {"status": "failed", "source": {"step_order": 0, "step_id": "gatekeeper_step"}},
    }
    stagnation = {
        "stagnation_mode": "plateau",
        "recent_composites": ["0.7", 0.8, True],
        "recent_deltas": ["0.1", 0.2, False],
        "consecutive_low_delta": "2",
    }
    service = ServiceWorkflowSupportMixin()

    legacy_entry = service._build_workflow_iteration_entry(
        0,
        [gatekeeper_step_result],
        stagnation,
        previous_composite=0.4,
    )
    summary = build_iteration_summary(
        IterationSummaryContext(
            layout=layout,
            iter_id=0,
            step_results=[gatekeeper_step_result],
            stagnation=stagnation,
            previous_composite=0.4,
            timestamp="2026-01-01T00:00:00Z",
        )
    )

    assert legacy_entry["score"]["composite"] is None
    assert legacy_entry["score"]["delta"] is None
    assert legacy_entry["stagnation"]["recent_composites"] == [0.8]
    assert legacy_entry["stagnation"]["recent_deltas"] == [0.2]
    assert legacy_entry["stagnation"]["consecutive_low_delta"] == 0
    assert summary["score"]["composite"] is None
    assert summary["score"]["delta"] is None
    assert summary["stagnation"]["recent_composites"] == [0.8]
    assert summary["stagnation"]["recent_deltas"] == [0.2]
    assert summary["stagnation"]["consecutive_low_delta"] == 0


def test_stagnation_update_requires_literal_score_history() -> None:
    stagnation = update_stagnation(
        StagnationUpdateRequest(
            stagnation={
                "recent_composites": ["0.7", 0.8, True],
                "recent_deltas": ["0.1", 0.2, False],
            },
            composite=0.81,
            current_iter=1,
            delta_threshold=0.05,
            trigger_window=2,
            regression_window=2,
        )
    )

    assert stagnation["recent_composites"] == [0.8, 0.81]
    assert stagnation["recent_deltas"] == [0.2, 0.01]
    assert stagnation["consecutive_low_delta"] == 1
    assert stagnation["stagnation_mode"] == "none"


def test_gatekeeper_output_normalizes_metric_row_booleans() -> None:
    output = ServiceWorkflowSupportMixin()._coerce_gatekeeper_output(
        {
            "passed": False,
            "decision_summary": "The measured check did not pass.",
            "metrics": [
                {"name": "quality_score", "value": 0.8, "threshold": 0.9, "passed": "false"},
            ],
            "evidence_claims": ["Measured benchmark evidence did not satisfy the first GateKeeper pass."],
        },
        evidence_context={"items": []},
        current_evidence_id="ev_gatekeeper",
    )

    assert output["passed"] is False
    assert output["metric_scores"]["quality_score"]["passed"] is False
    assert output["metrics"] == [{"name": "quality_score", "value": 0.8, "threshold": 0.9, "passed": False}]


def test_gatekeeper_output_rejects_string_measured_evidence_as_supporting_ref() -> None:
    output = ServiceWorkflowSupportMixin()._coerce_gatekeeper_output(
        {
            "passed": True,
            "decision_summary": "The Builder measured this.",
            "composite_score": 1.0,
            "evidence_refs": ["builder_ev"],
            "evidence_claims": ["A concrete claim that incorrectly treats string measured evidence as proof."],
        },
        evidence_context={
            "items": [
                {
                    "id": "builder_ev",
                    "archetype": "builder",
                    "evidence_kind": "handoff",
                    "result": "completed",
                    "measured_evidence": "true",
                    "artifact_refs": [],
                }
            ]
        },
        current_evidence_id="ev_gatekeeper",
    )

    assert output["passed"] is False
    assert output["evidence_gate_status"] == "blocked"
    assert output["blocking_issues"] == ["gatekeeper_pass_refs_not_supporting_evidence"]


def test_gatekeeper_output_rejects_blocked_upstream_refs_as_supporting_evidence() -> None:
    output = ServiceWorkflowSupportMixin()._coerce_gatekeeper_output(
        {
            "passed": True,
            "decision_summary": "Looks good.",
            "composite_score": 1.0,
            "evidence_refs": ["blocked_ev"],
            "evidence_claims": ["A concrete claim that incorrectly treats blocked evidence as support."],
            "metric_scores": {
                "quality_score": {"value": 1.0, "threshold": 0.9, "passed": True},
            },
        },
        evidence_context={"items": [{"id": "blocked_ev", "archetype": "inspector", "result": "blocked"}]},
        current_evidence_id="ev_gatekeeper",
    )

    assert output["passed"] is False
    assert output["composite_score"] == 0.89
    assert output["evidence_gate_status"] == "blocked"
    assert output["blocking_issues"] == ["gatekeeper_pass_refs_not_supporting_evidence"]


def test_gatekeeper_output_rejects_plain_builder_handoff_as_supporting_evidence() -> None:
    output = ServiceWorkflowSupportMixin()._coerce_gatekeeper_output(
        {
            "passed": True,
            "decision_summary": "The Builder says the task is done.",
            "composite_score": 1.0,
            "evidence_refs": ["builder_ev"],
            "evidence_claims": ["A concrete claim that incorrectly treats Builder self-report as proof."],
        },
        evidence_context={
            "items": [
                {
                    "id": "builder_ev",
                    "archetype": "builder",
                    "evidence_kind": "handoff",
                    "result": "completed",
                    "artifact_refs": [],
                }
            ]
        },
        current_evidence_id="ev_gatekeeper",
    )

    assert output["passed"] is False
    assert output["composite_score"] == 0.89
    assert output["evidence_gate_status"] == "blocked"
    assert output["blocking_issues"] == ["gatekeeper_pass_refs_not_supporting_evidence"]


def test_gatekeeper_output_rejects_plain_inspector_observation_as_supporting_evidence() -> None:
    output = ServiceWorkflowSupportMixin()._coerce_gatekeeper_output(
        {
            "passed": True,
            "decision_summary": "The Inspector says the task is done.",
            "composite_score": 1.0,
            "evidence_refs": ["inspector_ev"],
            "evidence_claims": ["A concrete claim that incorrectly treats reviewer self-report as proof."],
        },
        evidence_context={
            "items": [
                {
                    "id": "inspector_ev",
                    "archetype": "inspector",
                    "evidence_kind": "inspection",
                    "result": "passed",
                    "artifact_refs": [],
                    "verifies": [],
                }
            ]
        },
        current_evidence_id="ev_gatekeeper",
    )

    assert output["passed"] is False
    assert output["composite_score"] == 0.89
    assert output["evidence_gate_status"] == "blocked"
    assert output["blocking_issues"] == ["gatekeeper_pass_refs_not_supporting_evidence"]


def test_gatekeeper_output_allows_inspector_structured_check_as_supporting_evidence() -> None:
    output = ServiceWorkflowSupportMixin()._coerce_gatekeeper_output(
        {
            "passed": True,
            "decision_summary": "The Inspector ran a structured proof check.",
            "composite_score": 1.0,
            "evidence_refs": ["inspector_ev"],
            "evidence_claims": ["The structured inspection check verified the required proof boundary."],
        },
        evidence_context={
            "items": [
                {
                    "id": "inspector_ev",
                    "archetype": "inspector",
                    "evidence_kind": "inspection",
                    "result": "passed",
                    "artifact_refs": [],
                    "verifies": ["check_results:required_proof:passed"],
                }
            ]
        },
        current_evidence_id="ev_gatekeeper",
    )

    assert output["passed"] is True
    assert output["evidence_gate_status"] == "passed"
    assert output["evidence_refs"] == ["inspector_ev"]


def test_gatekeeper_output_rejects_unmanaged_residual_risk_on_pass() -> None:
    output = ServiceWorkflowSupportMixin()._coerce_gatekeeper_output(
        {
            "passed": True,
            "decision_summary": "The proof is covered, with some residual risk.",
            "composite_score": 1.0,
            "evidence_refs": ["inspector_ev"],
            "evidence_claims": ["The structured inspection check verified the required proof boundary."],
            "residual_risks": ["Some residual risk remains."],
        },
        evidence_context={
            "items": [
                {
                    "id": "inspector_ev",
                    "archetype": "inspector",
                    "evidence_kind": "inspection",
                    "result": "passed",
                    "artifact_refs": [],
                    "verifies": ["check_results:required_proof:passed"],
                }
            ]
        },
        current_evidence_id="ev_gatekeeper",
    )

    assert output["passed"] is False
    assert output["composite_score"] == 0.89
    assert output["evidence_gate_status"] == "blocked"
    assert output["blocking_issues"] == ["gatekeeper_pass_has_unmanaged_residual_risk"]
    assert output["residual_risks"] == ["Some residual risk remains."]


def test_gatekeeper_output_rejects_manual_visible_residual_risk_without_management_on_pass() -> None:
    output = ServiceWorkflowSupportMixin()._coerce_gatekeeper_output(
        {
            "passed": True,
            "decision_summary": "The proof is covered, but a manual risk remains visible.",
            "composite_score": 1.0,
            "evidence_refs": ["inspector_ev"],
            "evidence_claims": ["The structured inspection check verified the required proof boundary."],
            "residual_risks": ["Ownerless manual billing export remains visible."],
        },
        evidence_context={
            "items": [
                {
                    "id": "inspector_ev",
                    "archetype": "inspector",
                    "evidence_kind": "inspection",
                    "result": "passed",
                    "artifact_refs": [],
                    "verifies": ["check_results:required_proof:passed"],
                }
            ]
        },
        current_evidence_id="ev_gatekeeper",
    )

    assert output["passed"] is False
    assert output["composite_score"] == 0.89
    assert output["evidence_gate_status"] == "blocked"
    assert output["blocking_issues"] == ["gatekeeper_pass_has_unmanaged_residual_risk"]
    assert output["residual_risks"] == ["Ownerless manual billing export remains visible."]


def test_gatekeeper_output_rejects_residual_risk_when_contract_disallows_acceptance_on_pass() -> None:
    output = ServiceWorkflowSupportMixin()._coerce_gatekeeper_output(
        {
            "passed": True,
            "decision_summary": "The proof is covered, with an accepted follow-up risk.",
            "composite_score": 1.0,
            "evidence_refs": ["inspector_ev"],
            "evidence_claims": ["The structured inspection check verified the required proof boundary."],
            "residual_risks": ["Manual billing export remains visible as a follow-up owned by Support."],
        },
        evidence_context={
            "items": [
                {
                    "id": "inspector_ev",
                    "archetype": "inspector",
                    "evidence_kind": "inspection",
                    "result": "passed",
                    "artifact_refs": [],
                    "verifies": ["check_results:required_proof:passed"],
                }
            ]
        },
        current_evidence_id="ev_gatekeeper",
        compiled_spec={"residual_risk": "No residual risk is acceptable; any remaining risk must fail closed."},
    )

    assert output["passed"] is False
    assert output["composite_score"] == 0.89
    assert output["evidence_gate_status"] == "blocked"
    assert output["blocking_issues"] == ["gatekeeper_pass_violates_no_residual_risk_policy"]
    assert output["residual_risks"] == ["Manual billing export remains visible as a follow-up owned by Support."]


def test_gatekeeper_output_rejects_negated_residual_risk_with_exception_on_pass() -> None:
    output = ServiceWorkflowSupportMixin()._coerce_gatekeeper_output(
        {
            "passed": True,
            "decision_summary": "The proof is covered, with an exception hidden behind no blocking residual risk wording.",
            "composite_score": 1.0,
            "evidence_refs": ["inspector_ev"],
            "evidence_claims": ["The structured inspection check verified the required proof boundary."],
            "residual_risks": ["No blocking residual risk except untested billing export."],
        },
        evidence_context={
            "items": [
                {
                    "id": "inspector_ev",
                    "archetype": "inspector",
                    "evidence_kind": "inspection",
                    "result": "passed",
                    "artifact_refs": [],
                    "verifies": ["check_results:required_proof:passed"],
                }
            ]
        },
        current_evidence_id="ev_gatekeeper",
    )

    assert output["passed"] is False
    assert output["evidence_gate_status"] == "blocked"
    assert output["blocking_issues"] == ["gatekeeper_pass_has_unmanaged_residual_risk"]
    assert output["residual_risks"] == ["No blocking residual risk except untested billing export."]


def test_gatekeeper_output_allows_measured_self_evidence_with_plain_builder_context() -> None:
    output = ServiceWorkflowSupportMixin()._coerce_gatekeeper_output(
        {
            "passed": True,
            "decision_summary": "The Builder handoff is visible, but GateKeeper also measured the result.",
            "composite_score": 1.0,
            "evidence_refs": ["builder_ev"],
            "evidence_claims": ["Measured GateKeeper evidence independently satisfied the pass threshold."],
            "metric_scores": {
                "quality_score": {"value": 1.0, "threshold": 0.9, "passed": True},
            },
        },
        evidence_context={
            "items": [
                {
                    "id": "builder_ev",
                    "archetype": "builder",
                    "evidence_kind": "handoff",
                    "result": "completed",
                    "artifact_refs": [],
                }
            ]
        },
        current_evidence_id="ev_gatekeeper",
    )

    assert output["passed"] is True
    assert output["evidence_gate_status"] == "passed"
    assert output["evidence_refs"] == ["builder_ev", "ev_gatekeeper"]


def test_gatekeeper_output_allows_builder_proof_artifact_as_supporting_evidence(tmp_path: Path) -> None:
    proof_path = tmp_path / "project" / "tests" / "evidence" / "proof.json"
    proof_path.parent.mkdir(parents=True)
    proof_path.write_text('{"ok": true}\n', encoding="utf-8")

    output = ServiceWorkflowSupportMixin()._coerce_gatekeeper_output(
        {
            "passed": True,
            "decision_summary": "The Builder left a proof artifact.",
            "composite_score": 1.0,
            "evidence_refs": ["builder_ev"],
            "evidence_claims": ["The proof artifact is available for downstream review."],
        },
        evidence_context={
            "items": [
                {
                    "id": "builder_ev",
                    "archetype": "builder",
                    "evidence_kind": "handoff",
                    "result": "completed",
                    "artifact_refs": [
                        {
                            "kind": "workspace",
                            "label": "proof-file:tests/evidence/proof.json",
                            "relative_path": "tests/evidence/proof.json",
                            "workspace_path": "tests/evidence/proof.json",
                            "absolute_path": str(proof_path),
                        }
                    ],
                }
            ]
        },
        current_evidence_id="ev_gatekeeper",
    )

    assert output["passed"] is True
    assert output["evidence_gate_status"] == "passed"
    assert output["evidence_refs"] == ["builder_ev"]


def test_gatekeeper_output_rejects_missing_builder_proof_artifact_as_supporting_evidence(tmp_path: Path) -> None:
    missing_proof_path = tmp_path / "project" / "tests" / "evidence" / "proof.json"

    output = ServiceWorkflowSupportMixin()._coerce_gatekeeper_output(
        {
            "passed": True,
            "decision_summary": "The Builder cited a proof artifact that is no longer available.",
            "composite_score": 1.0,
            "evidence_refs": ["builder_ev"],
            "evidence_claims": ["The proof artifact path should still be readable before GateKeeper closes."],
        },
        evidence_context={
            "items": [
                {
                    "id": "builder_ev",
                    "archetype": "builder",
                    "evidence_kind": "handoff",
                    "result": "completed",
                    "artifact_refs": [
                        {
                            "kind": "workspace",
                            "label": "proof-file:tests/evidence/proof.json",
                            "relative_path": "tests/evidence/proof.json",
                            "workspace_path": "tests/evidence/proof.json",
                            "absolute_path": str(missing_proof_path),
                        }
                    ],
                }
            ]
        },
        current_evidence_id="ev_gatekeeper",
    )

    assert output["passed"] is False
    assert output["composite_score"] == 0.89
    assert output["evidence_gate_status"] == "blocked"
    assert output["blocking_issues"] == ["gatekeeper_pass_refs_not_supporting_evidence"]
