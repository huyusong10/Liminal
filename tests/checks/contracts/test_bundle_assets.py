from __future__ import annotations

from pathlib import Path

from loopora.bundles import load_bundle_text
from loopora.executor_fake_payloads import alignment_bundle_yaml
from loopora.service_bundle_control_summary import _traceability_projection


def test_bundle_governance_cards_project_contract_controls(service_factory, sample_workdir: Path) -> None:
    service = service_factory(scenario="success")
    imported = service.import_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))

    card = next(item for item in service.list_bundle_governance_cards() if item["id"] == imported["id"])
    governance = card["governance_summary"]

    assert governance["failure_modes"]
    assert governance["evidence_style"]
    assert governance["workflow_step_count"] >= 1
    assert governance["workflow_shape"]
    assert governance["gatekeeper"]["enabled"] is True
    assert governance["gatekeeper"]["strictness"] == "evidence_refs_required"


def test_bundle_governance_summary_requires_literal_gatekeeper_enabled(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))

    service._bundle_control_summary = lambda _bundle: {
        "risks": [],
        "evidence": ["GateKeeper evidence refs"],
        "workflow": {"summary": "Builder -> GateKeeper", "step_count": 2, "parallel_groups": []},
        "gatekeeper": {"enabled": "false", "roles": ["GateKeeper"], "finish_steps": ["gatekeeper_step"]},
    }

    governance = service._bundle_governance_summary(bundle)

    assert governance["gatekeeper"]["enabled"] is False
    assert governance["gatekeeper"]["strictness"] == "not_configured"


def test_bundle_traceability_requires_literal_gatekeeper_enabled() -> None:
    traceability = _traceability_projection(
        {
            "bundle": {},
            "raw_sections": {},
            "roles": [],
            "workflow": {},
            "workflow_projection": {},
            "gatekeeper": {"enabled": "true", "roles": ["GateKeeper"], "finish_steps": ["gatekeeper_step"]},
            "controls": [],
        }
    )

    gatekeeper_item = next(item for item in traceability["items"] if item["key"] == "gatekeeper_closure")
    assert gatekeeper_item["mapped"] is False
    assert "gatekeeper_closure" in traceability["missing"]
