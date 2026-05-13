from __future__ import annotations

import json
from pathlib import Path

from loopora.evidence_coverage import (
    _overall_coverage_status,
    _top_coverage_gaps,
    build_evidence_coverage_projection,
    summarize_evidence_coverage_projection,
)
from loopora.run_artifacts import RunArtifactLayout


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_ledger(path: Path, items: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in items), encoding="utf-8")


def _coverage_layout(tmp_path: Path) -> RunArtifactLayout:
    layout = RunArtifactLayout(tmp_path / "run_coverage")
    layout.initialize()
    _write_json(
        layout.contract_compiled_spec_path,
        {
            "checks": [
                {
                    "id": "check_001",
                    "title": "Required proof",
                    "details": "The required proof is verified.",
                }
            ]
        },
    )
    _write_json(layout.run_contract_path, {"completion_mode": "gatekeeper"})
    return layout


def test_coverage_required_status_requires_literal_boolean() -> None:
    rows = {
        "advisory_string_required": {
            "id": "advisory_string_required",
            "kind": "fake_done",
            "source_section": "Fake Done",
            "source_id": "risk_001",
            "label": "Advisory risk",
            "text": "String required should remain advisory.",
            "required": "true",
            "status": "blocked",
            "reason": "Advisory target is blocked.",
            "evidence_refs": [],
        }
    }

    assert _overall_coverage_status(rows) == "weak"

    gaps = _top_coverage_gaps(
        [
            {
                **rows["advisory_string_required"],
                "artifact_refs": [],
            },
            {
                "id": "literal_required",
                "kind": "done_when",
                "source_section": "Done When",
                "source_id": "check_001",
                "label": "Required proof",
                "text": "Literal required stays first.",
                "required": True,
                "status": "missing",
                "reason": "Missing.",
                "evidence_refs": [],
                "artifact_refs": [],
            },
        ]
    )

    assert gaps[0]["target_id"] == "literal_required"
    assert gaps[1]["target_id"] == "advisory_string_required"
    assert gaps[1]["required"] is False


def test_coverage_summary_requires_integer_counts() -> None:
    summary = summarize_evidence_coverage_projection(
        {
            "status": "partial",
            "evidence_count": True,
            "check_count": "2",
            "covered_check_count": 1.5,
            "missing_check_count": 1,
            "target_count": 4,
            "covered_target_count": "1",
            "weak_target_count": True,
            "missing_target_count": 2,
            "blocked_target_count": 0,
            "artifact_ref_count": "3",
            "residual_risk_count": True,
        }
    )

    assert summary["evidence_count"] == 0
    assert summary["check_count"] == 0
    assert summary["covered_check_count"] == 0
    assert summary["missing_check_count"] == 1
    assert summary["target_count"] == 4
    assert summary["covered_target_count"] == 0
    assert summary["weak_target_count"] == 0
    assert summary["missing_target_count"] == 2
    assert summary["blocked_target_count"] == 0
    assert summary["artifact_ref_count"] == 0
    assert summary["residual_risk_count"] == 0


def test_coverage_summary_drops_malformed_collection_shapes() -> None:
    summary = summarize_evidence_coverage_projection(
        {
            "status": "partial",
            "summary": "not a mapping",
            "covered_check_ids": "check_001",
            "missing_check_ids": ["check_002", 7, True],
            "top_gaps": [
                "not a gap",
                {"target_id": "done_when.check_001", "status": "missing"},
            ],
            "evidence_kind_counts": ["builder", "gatekeeper"],
            "risk_signals": "manual review needed",
            "latest_gatekeeper": "not a mapping",
        }
    )

    assert summary["summary"] == {}
    assert summary["covered_check_ids"] == []
    assert summary["missing_check_ids"] == ["check_002"]
    assert summary["top_gaps"] == [{"target_id": "done_when.check_001", "status": "missing"}]
    assert summary["evidence_kind_counts"] == {}
    assert summary["risk_signals"] == []
    assert summary["latest_gatekeeper"] == {}


def test_coverage_treats_intrinsic_required_targets_as_required_when_marker_is_malformed() -> None:
    rows = {
        "done_when.check_001": {
            "id": "done_when.check_001",
            "kind": "done_when",
            "source_section": "Done When",
            "source_id": "check_001",
            "label": "Required proof",
            "text": "Malformed required marker must not downgrade this target.",
            "required": "true",
            "status": "missing",
            "reason": "Missing.",
            "evidence_refs": [],
        },
        "gatekeeper.finish": {
            "id": "gatekeeper.finish",
            "kind": "gatekeeper",
            "source_section": "Workflow",
            "source_id": "finish",
            "label": "GateKeeper finish",
            "text": "Malformed required marker must not downgrade this target.",
            "required": False,
            "status": "covered",
            "reason": "Covered.",
            "evidence_refs": [],
        },
    }

    assert _overall_coverage_status(rows) == "partial"

    gaps = _top_coverage_gaps([{**row, "artifact_refs": []} for row in rows.values()])

    assert gaps[0]["target_id"] == "done_when.check_001"
    assert gaps[0]["required"] is True


def test_coverage_blocks_gatekeeper_finish_when_pass_cites_only_non_supporting_evidence(tmp_path: Path) -> None:
    layout = _coverage_layout(tmp_path)
    _write_ledger(
        layout.evidence_ledger_path,
        [
            {
                "id": "ev_blocked",
                "archetype": "inspector",
                "evidence_kind": "inspection",
                "result": "blocked",
                "claim": "The requested proof is blocked.",
            },
            {
                "id": "ev_gatekeeper",
                "archetype": "gatekeeper",
                "evidence_kind": "verdict",
                "result": "passed",
                "claim": "GateKeeper tried to pass from the blocked inspection.",
                "verifies": ["evidence:ev_blocked"],
            },
        ],
    )

    projection = build_evidence_coverage_projection(layout)

    targets = {target["id"]: target for target in projection["targets"]}
    assert projection["status"] == "blocked"
    assert targets["gatekeeper.finish"]["status"] == "blocked"
    assert targets["gatekeeper.finish"]["reason"] == "GateKeeper pass cited only non-supporting upstream evidence refs."
    assert targets["gatekeeper.finish"]["evidence_refs"] == ["ev_blocked", "ev_gatekeeper"]
    assert projection["latest_gatekeeper"]["supporting_evidence_refs"] == []
    assert projection["latest_gatekeeper"]["non_supporting_evidence_refs"] == ["ev_blocked"]


def test_coverage_blocks_gatekeeper_finish_when_pass_cites_plain_builder_handoff(tmp_path: Path) -> None:
    layout = _coverage_layout(tmp_path)
    _write_ledger(
        layout.evidence_ledger_path,
        [
            {
                "id": "ev_builder",
                "archetype": "builder",
                "evidence_kind": "handoff",
                "result": "completed",
                "claim": "Builder says the required proof is complete.",
                "verifies": ["target:done_when.check_001:covered"],
                "artifact_refs": [],
            },
            {
                "id": "ev_gatekeeper",
                "archetype": "gatekeeper",
                "evidence_kind": "verdict",
                "result": "passed",
                "claim": "GateKeeper tried to pass from a Builder handoff without proof.",
                "verifies": ["evidence:ev_builder"],
            },
        ],
    )

    projection = build_evidence_coverage_projection(layout)

    targets = {target["id"]: target for target in projection["targets"]}
    assert projection["status"] == "blocked"
    assert targets["done_when.check_001"]["status"] == "weak"
    assert targets["done_when.check_001"]["reason"] == "Coverage was reported as positive without supporting evidence."
    assert targets["gatekeeper.finish"]["status"] == "blocked"
    assert targets["gatekeeper.finish"]["evidence_refs"] == ["ev_builder", "ev_gatekeeper"]
    assert projection["latest_gatekeeper"]["supporting_evidence_refs"] == []
    assert projection["latest_gatekeeper"]["non_supporting_evidence_refs"] == ["ev_builder"]


def test_coverage_accepts_gatekeeper_finish_when_pass_has_supporting_ref(tmp_path: Path) -> None:
    layout = _coverage_layout(tmp_path)
    _write_ledger(
        layout.evidence_ledger_path,
        [
            {
                "id": "ev_supporting",
                "archetype": "inspector",
                "evidence_kind": "inspection",
                "result": "passed",
                "claim": "The required proof is covered.",
                "verifies": ["target:done_when.check_001:covered"],
            },
            {
                "id": "ev_blocked",
                "archetype": "inspector",
                "evidence_kind": "inspection",
                "result": "blocked",
                "claim": "An earlier inspection found a stale blocker.",
            },
            {
                "id": "ev_gatekeeper",
                "archetype": "gatekeeper",
                "evidence_kind": "verdict",
                "result": "passed",
                "claim": "GateKeeper passed from the supporting inspection while preserving the stale blocker ref.",
                "verifies": ["evidence:ev_blocked", "evidence:ev_supporting"],
            },
        ],
    )

    projection = build_evidence_coverage_projection(layout)

    targets = {target["id"]: target for target in projection["targets"]}
    assert projection["status"] == "covered"
    assert targets["gatekeeper.finish"]["status"] == "covered"
    assert targets["gatekeeper.finish"]["evidence_refs"] == ["ev_supporting", "ev_gatekeeper"]
    assert projection["latest_gatekeeper"]["supporting_evidence_refs"] == ["ev_supporting"]
    assert projection["latest_gatekeeper"]["non_supporting_evidence_refs"] == ["ev_blocked"]


def test_coverage_downgrades_positive_target_report_without_supporting_evidence(tmp_path: Path) -> None:
    layout = _coverage_layout(tmp_path)
    _write_ledger(
        layout.evidence_ledger_path,
        [
            {
                "id": "ev_gatekeeper",
                "archetype": "gatekeeper",
                "evidence_kind": "verdict",
                "result": "passed",
                "claim": "GateKeeper marked the target covered without supporting refs.",
                "verifies": ["target:done_when.check_001:covered"],
                "related_evidence_ids": [],
            },
        ],
    )

    projection = build_evidence_coverage_projection(layout)

    targets = {target["id"]: target for target in projection["targets"]}
    assert projection["status"] == "partial"
    assert targets["done_when.check_001"]["status"] == "weak"
    assert targets["done_when.check_001"]["reason"] == "Coverage was reported as positive without supporting evidence."
    assert targets["done_when.check_001"]["evidence_refs"] == ["ev_gatekeeper"]


def test_coverage_accepts_gatekeeper_target_report_with_supporting_related_evidence(tmp_path: Path) -> None:
    layout = _coverage_layout(tmp_path)
    _write_ledger(
        layout.evidence_ledger_path,
        [
            {
                "id": "ev_supporting",
                "archetype": "inspector",
                "evidence_kind": "inspection",
                "result": "passed",
                "claim": "Inspector verified the target evidence.",
                "artifact_refs": [
                    {
                        "kind": "workspace",
                        "label": "proof-file:tests/evidence/proof.json",
                        "relative_path": "tests/evidence/proof.json",
                        "workspace_path": "tests/evidence/proof.json",
                        "absolute_path": str(tmp_path / "project" / "tests" / "evidence" / "proof.json"),
                    }
                ],
            },
            {
                "id": "ev_gatekeeper",
                "archetype": "gatekeeper",
                "evidence_kind": "verdict",
                "result": "passed",
                "claim": "GateKeeper marked the target covered from the supporting inspection.",
                "verifies": ["target:done_when.check_001:covered"],
                "related_evidence_ids": ["ev_supporting"],
            },
        ],
    )

    projection = build_evidence_coverage_projection(layout)

    targets = {target["id"]: target for target in projection["targets"]}
    assert targets["done_when.check_001"]["status"] == "covered"
    assert targets["done_when.check_001"]["evidence_refs"] == ["ev_supporting"]
    assert targets["done_when.check_001"]["artifact_refs"][0]["label"] == "proof-file:tests/evidence/proof.json"


def test_coverage_treats_proven_result_status_as_positive_alias(tmp_path: Path) -> None:
    layout = _coverage_layout(tmp_path)
    _write_ledger(
        layout.evidence_ledger_path,
        [
            {
                "id": "ev_supporting",
                "archetype": "inspector",
                "evidence_kind": "inspection",
                "result": "passed",
                "claim": "Inspector verified the target evidence.",
                "verifies": ["target:done_when.check_001:covered"],
            },
            {
                "id": "ev_gatekeeper",
                "archetype": "gatekeeper",
                "evidence_kind": "verdict",
                "result": "passed",
                "claim": "GateKeeper used the task verdict bucket word in coverage_results.",
                "verifies": ["evidence:ev_supporting"],
                "coverage_results": [
                    {
                        "target_id": "done_when.check_001",
                        "status": "proven",
                        "evidence_refs": ["ev_supporting"],
                        "note": "Proven is accepted as a positive alias but projected as covered.",
                    }
                ],
            },
        ],
    )

    projection = build_evidence_coverage_projection(layout)

    targets = {target["id"]: target for target in projection["targets"]}
    assert projection["status"] == "covered"
    assert targets["done_when.check_001"]["status"] == "covered"
    assert targets["done_when.check_001"]["evidence_refs"] == ["ev_supporting"]


def test_coverage_results_keep_support_refs_scoped_to_each_target(tmp_path: Path) -> None:
    layout = _coverage_layout(tmp_path)
    proof_path = tmp_path / "project" / "tests" / "evidence" / "proof.json"
    proof_path.parent.mkdir(parents=True)
    proof_path.write_text('{"ok": true}\n', encoding="utf-8")
    _write_json(
        layout.contract_compiled_spec_path,
        {
            "checks": [
                {"id": "check_001", "title": "Target A", "details": "Target A has proof."},
                {"id": "check_002", "title": "Target B", "details": "Target B still lacks proof."},
            ]
        },
    )
    _write_ledger(
        layout.evidence_ledger_path,
        [
            {
                "id": "ev_supporting",
                "archetype": "inspector",
                "evidence_kind": "inspection",
                "result": "passed",
                "claim": "Inspector verified only target A.",
                "artifact_refs": [
                    {
                        "kind": "workspace",
                        "label": "proof-file:tests/evidence/proof.json",
                        "relative_path": "tests/evidence/proof.json",
                        "workspace_path": "tests/evidence/proof.json",
                        "absolute_path": str(proof_path),
                    }
                ],
            },
            {
                "id": "ev_gatekeeper",
                "archetype": "gatekeeper",
                "evidence_kind": "verdict",
                "result": "passed",
                "claim": "GateKeeper reported two targets but cited proof for only one.",
                "verifies": [
                    "target:done_when.check_001:covered",
                    "target:done_when.check_002:covered",
                    "evidence:ev_supporting",
                ],
                "related_evidence_ids": ["ev_supporting"],
                "coverage_results": [
                    {
                        "target_id": "done_when.check_001",
                        "status": "covered",
                        "evidence_refs": ["ev_supporting"],
                        "note": "Target A is backed by the inspector proof.",
                    },
                    {
                        "target_id": "done_when.check_002",
                        "status": "covered",
                        "evidence_refs": [],
                        "note": "Target B was reported without proof.",
                    },
                ],
            },
        ],
    )

    projection = build_evidence_coverage_projection(layout)

    targets = {target["id"]: target for target in projection["targets"]}
    assert projection["status"] == "partial"
    assert targets["done_when.check_001"]["status"] == "covered"
    assert targets["done_when.check_001"]["evidence_refs"] == ["ev_supporting"]
    assert targets["done_when.check_001"]["artifact_refs"][0]["label"] == "proof-file:tests/evidence/proof.json"
    assert targets["done_when.check_002"]["status"] == "weak"
    assert targets["done_when.check_002"]["reason"] == "Coverage was reported as positive without supporting evidence."
    assert targets["done_when.check_002"]["evidence_refs"] == ["ev_gatekeeper"]
    assert targets["done_when.check_002"]["artifact_refs"] == []


def test_coverage_accepts_gatekeeper_finish_when_pass_cites_builder_proof_artifact(tmp_path: Path) -> None:
    layout = _coverage_layout(tmp_path)
    proof_path = tmp_path / "project" / "tests" / "evidence" / "proof.json"
    proof_path.parent.mkdir(parents=True)
    proof_path.write_text('{"ok": true}\n', encoding="utf-8")
    _write_ledger(
        layout.evidence_ledger_path,
        [
            {
                "id": "ev_builder",
                "archetype": "builder",
                "evidence_kind": "handoff",
                "result": "completed",
                "claim": "Builder left a proof artifact for the required target.",
                "verifies": ["target:done_when.check_001:covered"],
                "artifact_refs": [
                    {
                        "kind": "workspace",
                        "label": "proof-file:tests/evidence/proof.json",
                        "relative_path": "tests/evidence/proof.json",
                        "workspace_path": "tests/evidence/proof.json",
                        "absolute_path": str(proof_path),
                    }
                ],
            },
            {
                "id": "ev_gatekeeper",
                "archetype": "gatekeeper",
                "evidence_kind": "verdict",
                "result": "passed",
                "claim": "GateKeeper passed from the Builder proof artifact.",
                "verifies": ["evidence:ev_builder"],
            },
        ],
    )

    projection = build_evidence_coverage_projection(layout)

    targets = {target["id"]: target for target in projection["targets"]}
    assert projection["status"] == "covered"
    assert targets["gatekeeper.finish"]["status"] == "covered"
    assert targets["gatekeeper.finish"]["evidence_refs"] == ["ev_builder", "ev_gatekeeper"]
    assert projection["latest_gatekeeper"]["supporting_evidence_refs"] == ["ev_builder"]
    assert projection["latest_gatekeeper"]["non_supporting_evidence_refs"] == []


def test_coverage_blocks_gatekeeper_finish_when_builder_proof_artifact_is_missing(tmp_path: Path) -> None:
    layout = _coverage_layout(tmp_path)
    missing_proof_path = tmp_path / "project" / "tests" / "evidence" / "proof.json"
    _write_ledger(
        layout.evidence_ledger_path,
        [
            {
                "id": "ev_builder",
                "archetype": "builder",
                "evidence_kind": "handoff",
                "result": "completed",
                "claim": "Builder cited a proof artifact that no longer exists.",
                "verifies": ["target:done_when.check_001:covered"],
                "artifact_refs": [
                    {
                        "kind": "workspace",
                        "label": "proof-file:tests/evidence/proof.json",
                        "relative_path": "tests/evidence/proof.json",
                        "workspace_path": "tests/evidence/proof.json",
                        "absolute_path": str(missing_proof_path),
                    }
                ],
            },
            {
                "id": "ev_gatekeeper",
                "archetype": "gatekeeper",
                "evidence_kind": "verdict",
                "result": "passed",
                "claim": "GateKeeper tried to pass from a missing Builder proof artifact.",
                "verifies": ["evidence:ev_builder"],
            },
        ],
    )

    projection = build_evidence_coverage_projection(layout)

    targets = {target["id"]: target for target in projection["targets"]}
    assert projection["status"] == "blocked"
    assert targets["gatekeeper.finish"]["status"] == "blocked"
    assert targets["gatekeeper.finish"]["evidence_refs"] == ["ev_builder", "ev_gatekeeper"]
    assert projection["latest_gatekeeper"]["supporting_evidence_refs"] == []
    assert projection["latest_gatekeeper"]["non_supporting_evidence_refs"] == ["ev_builder"]


def test_coverage_ignores_explicit_no_residual_risk_markers(tmp_path: Path) -> None:
    layout = _coverage_layout(tmp_path)
    _write_ledger(
        layout.evidence_ledger_path,
        [
            {
                "id": "ev_supporting",
                "archetype": "inspector",
                "evidence_kind": "inspection",
                "result": "passed",
                "claim": "The required proof is covered.",
                "verifies": ["target:done_when.check_001:covered"],
            },
            {
                "id": "ev_gatekeeper",
                "archetype": "gatekeeper",
                "evidence_kind": "verdict",
                "result": "passed",
                "claim": "GateKeeper passed without accepted residual risk.",
                "verifies": ["evidence:ev_supporting"],
                "residual_risk": "None",
            },
        ],
    )

    projection = build_evidence_coverage_projection(layout)

    assert projection["status"] == "covered"
    assert projection["residual_risk_count"] == 0
    assert projection["risk_signals"] == []
    assert projection["latest_gatekeeper"]["residual_risk"] == "None"


def test_coverage_accepts_gatekeeper_finish_when_pass_has_measured_self_evidence(tmp_path: Path) -> None:
    layout = _coverage_layout(tmp_path)
    _write_ledger(
        layout.evidence_ledger_path,
        [
            {
                "id": "ev_check",
                "archetype": "inspector",
                "evidence_kind": "inspection",
                "result": "passed",
                "claim": "The required proof is covered.",
                "verifies": ["target:done_when.check_001:covered"],
            },
            {
                "id": "ev_gatekeeper",
                "archetype": "gatekeeper",
                "evidence_kind": "verdict",
                "result": "passed",
                "claim": "GateKeeper passed from its measured benchmark result.",
                "verifies": ["evidence:ev_gatekeeper"],
                "measured_evidence": True,
                "concrete_evidence_claim_count": 1,
            },
        ],
    )

    projection = build_evidence_coverage_projection(layout)

    targets = {target["id"]: target for target in projection["targets"]}
    assert projection["status"] == "covered"
    assert targets["gatekeeper.finish"]["status"] == "covered"
    assert targets["gatekeeper.finish"]["reason"] == "GateKeeper passed with measured self evidence and concrete evidence claims."
    assert targets["gatekeeper.finish"]["evidence_refs"] == ["ev_gatekeeper"]
    assert projection["latest_gatekeeper"]["supporting_evidence_refs"] == []
    assert projection["latest_gatekeeper"]["non_supporting_evidence_refs"] == []
    assert projection["latest_gatekeeper"]["self_measured_evidence"] is True
    assert projection["latest_gatekeeper"]["self_evidence_claim_count"] == 1


def test_coverage_does_not_accept_gatekeeper_self_ref_without_measured_evidence(tmp_path: Path) -> None:
    layout = _coverage_layout(tmp_path)
    _write_ledger(
        layout.evidence_ledger_path,
        [
            {
                "id": "ev_check",
                "archetype": "inspector",
                "evidence_kind": "inspection",
                "result": "passed",
                "claim": "The required proof is covered.",
                "verifies": ["target:done_when.check_001:covered"],
            },
            {
                "id": "ev_gatekeeper",
                "archetype": "gatekeeper",
                "evidence_kind": "verdict",
                "result": "passed",
                "claim": "GateKeeper passed from a prose-only self report.",
                "verifies": ["evidence:ev_gatekeeper"],
                "measured_evidence": False,
                "concrete_evidence_claim_count": 1,
            },
        ],
    )

    projection = build_evidence_coverage_projection(layout)

    targets = {target["id"]: target for target in projection["targets"]}
    assert projection["status"] == "partial"
    assert targets["gatekeeper.finish"]["status"] == "missing"
    assert targets["gatekeeper.finish"]["evidence_refs"] == []
    assert projection["latest_gatekeeper"]["self_measured_evidence"] is False
    assert projection["latest_gatekeeper"]["self_evidence_claim_count"] == 1


def test_coverage_does_not_accept_string_measured_evidence(tmp_path: Path) -> None:
    layout = _coverage_layout(tmp_path)
    _write_ledger(
        layout.evidence_ledger_path,
        [
            {
                "id": "ev_gatekeeper",
                "archetype": "gatekeeper",
                "evidence_kind": "verdict",
                "result": "passed",
                "claim": "GateKeeper passed from a string-shaped measured evidence marker.",
                "verifies": ["evidence:ev_gatekeeper"],
                "measured_evidence": "true",
                "concrete_evidence_claim_count": 1,
            },
        ],
    )

    projection = build_evidence_coverage_projection(layout)

    targets = {target["id"]: target for target in projection["targets"]}
    assert projection["status"] == "partial"
    assert targets["gatekeeper.finish"]["status"] == "missing"
    assert targets["gatekeeper.finish"]["evidence_refs"] == []
    assert projection["latest_gatekeeper"]["self_measured_evidence"] is False


def test_coverage_does_not_accept_boolean_concrete_evidence_claim_count(tmp_path: Path) -> None:
    layout = _coverage_layout(tmp_path)
    _write_ledger(
        layout.evidence_ledger_path,
        [
            {
                "id": "ev_gatekeeper",
                "archetype": "gatekeeper",
                "evidence_kind": "verdict",
                "result": "passed",
                "claim": "GateKeeper passed from a boolean-shaped evidence claim count.",
                "verifies": ["evidence:ev_gatekeeper"],
                "measured_evidence": True,
                "concrete_evidence_claim_count": True,
            },
        ],
    )

    projection = build_evidence_coverage_projection(layout)

    targets = {target["id"]: target for target in projection["targets"]}
    assert projection["status"] == "partial"
    assert targets["gatekeeper.finish"]["status"] == "missing"
    assert targets["gatekeeper.finish"]["evidence_refs"] == []
    assert projection["latest_gatekeeper"]["self_measured_evidence"] is False
    assert projection["latest_gatekeeper"]["self_evidence_claim_count"] == 0
