from __future__ import annotations

from pathlib import Path

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
