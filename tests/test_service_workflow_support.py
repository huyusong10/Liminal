from __future__ import annotations

from loopora.service_workflow_support import ServiceWorkflowSupportMixin


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
