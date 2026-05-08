from __future__ import annotations

import json
from pathlib import Path

from loopora.evidence_manifest import build_evidence_manifest_projection
from loopora.run_artifacts import RunArtifactLayout


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_ledger(path: Path, items: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in items), encoding="utf-8")


def test_manifest_target_index_uses_coverage_evidence_refs_for_derived_targets(tmp_path: Path) -> None:
    layout = RunArtifactLayout(tmp_path / "run_manifest")
    layout.initialize()
    _write_json(layout.run_contract_path, {"completion_mode": "gatekeeper"})
    _write_json(
        layout.evidence_coverage_path,
        {
            "schema_version": 1,
            "targets": [
                {
                    "id": "gatekeeper.finish",
                    "kind": "gatekeeper",
                    "label": "GateKeeper finish",
                    "status": "covered",
                    "required": True,
                    "evidence_refs": ["ev_gatekeeper"],
                }
            ],
        },
    )
    _write_ledger(
        layout.evidence_ledger_path,
        [
            {
                "id": "ev_gatekeeper",
                "archetype": "gatekeeper",
                "evidence_kind": "verdict",
                "source": "verdict",
                "method": "gatekeeper_verdict",
                "result": "passed",
                "claim": "GateKeeper passed from measured self evidence.",
                "verifies": ["evidence:ev_gatekeeper"],
                "related_evidence_ids": [],
                "artifact_refs": [],
                "measured_evidence": True,
                "concrete_evidence_claim_count": 1,
            }
        ],
    )

    manifest = build_evidence_manifest_projection(layout)

    gatekeeper_claim = manifest["claims"][0]
    gatekeeper_target = manifest["targets"][0]
    assert manifest["ledger_only_claim_count"] == 1
    assert manifest["run_artifact_claim_count"] == 0
    assert gatekeeper_claim["measured_evidence"] is True
    assert gatekeeper_claim["concrete_evidence_claim_count"] == 1
    assert gatekeeper_target["claim_refs"] == ["ev_gatekeeper"]


def test_manifest_target_index_prioritizes_coverage_target_artifacts(tmp_path: Path) -> None:
    layout = RunArtifactLayout(tmp_path / "run_manifest")
    layout.initialize()
    proof_ref = {
        "kind": "workspace",
        "label": "proof-file:tests/evidence/proof.json",
        "relative_path": "tests/evidence/proof.json",
        "workspace_path": "tests/evidence/proof.json",
        "absolute_path": str(tmp_path / "project" / "tests" / "evidence" / "proof.json"),
        "exists": True,
    }
    role_output_ref = {
        "kind": "role-output",
        "label": "gatekeeper-output",
        "relative_path": ".loopora/runs/run_manifest/iterations/iter_000/steps/01__gatekeeper/output.json",
        "workspace_path": ".loopora/runs/run_manifest/iterations/iter_000/steps/01__gatekeeper/output.json",
        "absolute_path": str(tmp_path / "run_manifest" / "iterations" / "iter_000" / "steps" / "01__gatekeeper" / "output.json"),
    }
    _write_json(layout.run_contract_path, {"completion_mode": "gatekeeper"})
    _write_json(
        layout.evidence_coverage_path,
        {
            "schema_version": 1,
            "targets": [
                {
                    "id": "done_when.check_001",
                    "kind": "done_when",
                    "label": "Required proof",
                    "status": "covered",
                    "required": True,
                    "evidence_refs": ["ev_supporting"],
                    "artifact_refs": [proof_ref],
                }
            ],
        },
    )
    _write_ledger(
        layout.evidence_ledger_path,
        [
            {
                "id": "ev_supporting",
                "archetype": "inspector",
                "evidence_kind": "inspection",
                "source": "check_execution",
                "method": "inspection",
                "result": "passed",
                "claim": "Inspector left the proof artifact.",
                "verifies": [],
                "related_evidence_ids": [],
                "artifact_refs": [proof_ref],
            },
            {
                "id": "ev_gatekeeper",
                "archetype": "gatekeeper",
                "evidence_kind": "verdict",
                "source": "verdict",
                "method": "gatekeeper_verdict",
                "result": "passed",
                "claim": "GateKeeper reported target coverage from the inspector proof.",
                "verifies": ["target:done_when.check_001:covered", "evidence:ev_supporting"],
                "coverage_results": [
                    {
                        "target_id": "done_when.check_001",
                        "status": "covered",
                        "evidence_refs": ["ev_supporting"],
                        "note": "Covered by inspector proof.",
                    }
                ],
                "related_evidence_ids": ["ev_supporting"],
                "artifact_refs": [role_output_ref],
            },
        ],
    )

    manifest = build_evidence_manifest_projection(layout)

    target = manifest["targets"][0]
    assert target["claim_refs"] == ["ev_gatekeeper", "ev_supporting"]
    assert target["artifact_refs"][0]["label"] == "proof-file:tests/evidence/proof.json"
