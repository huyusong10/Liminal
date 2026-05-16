from __future__ import annotations

from pathlib import Path

from loopora.bundles import load_bundle_text
from loopora.executor_fake_payloads import alignment_bundle_yaml
from loopora.service_bundle_control_summary import _traceability_projection, build_bundle_control_summary, build_execution_strategy_trace


def _add_project_local_governance_responsibilities(bundle: dict) -> dict:
    role_by_key = {role["key"]: role for role in bundle["role_definitions"]}
    role_by_key["builder"]["prompt_markdown"] += (
        "\n\nRead AGENTS.md, design/README.md, design/, and tests/ before changing code, "
        "and follow those project-local governance contracts in the Builder handoff."
    )
    role_by_key["contract-inspector"]["prompt_markdown"] += (
        "\n\nInspector must verify AGENTS.md, design/README.md, design/, and tests/ were followed, "
        "and must mark skipped local governance as weak or missing evidence."
    )
    role_by_key["gatekeeper"]["prompt_markdown"] += (
        "\n\nGateKeeper treats skipped AGENTS.md, design/README.md, design/, or tests/ responsibilities "
        "as Weak, Unproven, or Blocking before accepting the run."
    )
    return bundle


def test_bundle_governance_cards_project_contract_controls(service_factory, sample_workdir: Path) -> None:
    service = service_factory(scenario="success")
    imported = service.import_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))

    card = next(item for item in service.list_bundle_governance_cards() if item["id"] == imported["id"])
    governance = card["governance_summary"]

    assert governance["success_surface"]
    assert governance["loop_fit_reasons"]
    assert any("primary user flow is understandable" in item for item in governance["success_surface"])
    assert governance["failure_modes"]
    assert governance["evidence_style"]
    assert governance["coverage_summary"]
    assert governance["coverage_targets"]
    assert governance["residual_risk_policy"]
    assert any("fail closed" in item for item in governance["residual_risk_policy"])
    assert governance["execution_strategy"]
    assert any("smaller proven flow" in item for item in governance["judgment_tradeoffs"])
    assert governance["workflow_step_count"] >= 1
    assert governance["workflow_shape"]
    assert governance["gatekeeper"]["enabled"] is True
    assert governance["gatekeeper"]["strictness"] == "evidence_refs_required"


def test_bundle_control_summary_coverage_respects_completion_mode(sample_workdir: Path) -> None:
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    bundle["loop"]["completion_mode"] = "rounds"

    summary = build_bundle_control_summary(bundle)
    target_ids = [target["id"] for target in summary["coverage"]["targets"]]

    assert "gatekeeper.finish" not in target_ids
    assert any(target_id.startswith("done_when.") for target_id in target_ids)


def test_execution_strategy_trace_accepts_priority_language() -> None:
    traces = build_execution_strategy_trace(
        collaboration_summary=(
            "Execution priorities: focused implementation, permission proof, audit repair, "
            "and only later UI polish."
        )
    )

    assert any("Execution priorities" in item for item in traces)


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


def test_bundle_control_summary_projects_explicit_judgment_tradeoffs(sample_workdir: Path) -> None:
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))

    summary = build_bundle_control_summary(bundle)
    loop_fit_item = next(item for item in summary["traceability"]["items"] if item["key"] == "loop_fit")
    success_item = next(item for item in summary["traceability"]["items"] if item["key"] == "success_surface")
    fake_done_item = next(item for item in summary["traceability"]["items"] if item["key"] == "fake_done_risks")
    evidence_item = next(item for item in summary["traceability"]["items"] if item["key"] == "evidence_preferences")
    tradeoff_item = next(item for item in summary["traceability"]["items"] if item["key"] == "judgment_tradeoffs")
    role_item = next(item for item in summary["traceability"]["items"] if item["key"] == "role_posture")

    assert any("Future iterations stay anchored" in item for item in summary["loop_fit_reasons"])
    assert loop_fit_item["mapped"] is True
    assert any("Future iterations stay anchored" in item for item in loop_fit_item["evidence"])
    assert "loop_fit" not in summary["traceability"]["missing"]
    assert any("primary user flow is understandable" in item for item in summary["success_surface"])
    assert any("happy-path claim" in item for item in summary["fake_done_risks"])
    assert any("project-owned checks" in item for item in summary["evidence_preferences"])
    assert success_item["mapped"] is True
    assert fake_done_item["mapped"] is True
    assert evidence_item["mapped"] is True
    assert "success_surface" not in summary["traceability"]["missing"]
    assert "fake_done_risks" not in summary["traceability"]["missing"]
    assert "evidence_preferences" not in summary["traceability"]["missing"]
    assert any("smaller proven flow" in item for item in summary["judgment_tradeoffs"])
    assert tradeoff_item["mapped"] is True
    assert "judgment_tradeoffs" not in summary["traceability"]["missing"]
    assert any("Focused Builder (builder): Keep implementation narrow" in item for item in summary["role_postures"])
    assert role_item["mapped"] is True
    assert "role_posture" not in summary["traceability"]["missing"]


def test_bundle_control_summary_does_not_treat_done_when_as_success_surface(sample_workdir: Path) -> None:
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    bundle["spec"]["markdown"] = bundle["spec"]["markdown"].replace(
        "\n# Success Surface\n\n"
        "- The primary user flow is understandable, maintainable, and easy to extend after the first pass.\n",
        "\n",
    )

    summary = build_bundle_control_summary(bundle)
    success_item = next(item for item in summary["traceability"]["items"] if item["key"] == "success_surface")

    assert summary["success_surface"] == []
    assert success_item["mapped"] is False
    assert success_item["surfaces"] == ["spec.markdown#Success Surface"]
    assert "success_surface" in summary["traceability"]["missing"]


def test_bundle_control_summary_projects_residual_risk_policy(sample_workdir: Path) -> None:
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))

    summary = build_bundle_control_summary(bundle)
    residual_item = next(item for item in summary["traceability"]["items"] if item["key"] == "residual_risk_policy")

    assert any("fail closed" in item for item in summary["residual_risk_policy"])
    assert residual_item["mapped"] is True
    assert "residual_risk_policy" not in summary["traceability"]["missing"]


def test_bundle_control_summary_does_not_map_unmanaged_residual_risk_policy(sample_workdir: Path) -> None:
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    bundle["spec"]["markdown"] = bundle["spec"]["markdown"].replace(
        "Accept minor polish gaps only when they are explicitly named and tracked as an owned follow-up; fail closed on unproven primary-flow behavior or weak verification evidence.",
        "Some risk is fine.",
    )

    summary = build_bundle_control_summary(bundle)
    residual_item = next(item for item in summary["traceability"]["items"] if item["key"] == "residual_risk_policy")

    assert summary["residual_risk_policy"] == []
    assert residual_item["mapped"] is False
    assert "residual_risk_policy" in summary["traceability"]["missing"]
    assert any(item["code"] == "residual_risk_unmanaged" for item in summary["diagnostics"])

    bundle["spec"]["markdown"] = bundle["spec"]["markdown"].replace(
        "Some risk is fine.",
        "有些风险可以接受。",
    )

    summary = build_bundle_control_summary(bundle)
    residual_item = next(item for item in summary["traceability"]["items"] if item["key"] == "residual_risk_policy")

    assert summary["residual_risk_policy"] == []
    assert residual_item["mapped"] is False
    assert "residual_risk_policy" in summary["traceability"]["missing"]


def test_bundle_control_summary_does_not_treat_role_names_as_posture(sample_workdir: Path) -> None:
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    for role in bundle["role_definitions"]:
        role["description"] = ""
        role["posture_notes"] = ""
        role["prompt_markdown"] = "---\nversion: 1\narchetype: " + role["archetype"] + "\n---\n"

    summary = build_bundle_control_summary(bundle)
    role_item = next(item for item in summary["traceability"]["items"] if item["key"] == "role_posture")

    assert role_item["mapped"] is False
    assert role_item["evidence"] == []
    assert summary["role_postures"] == []
    assert "role_posture" in summary["traceability"]["missing"]


def test_bundle_control_summary_projects_local_governance_responsibilities(sample_workdir: Path) -> None:
    bundle = _add_project_local_governance_responsibilities(
        load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    )

    summary = build_bundle_control_summary(bundle)
    local_item = next(item for item in summary["traceability"]["items"] if item["key"] == "local_governance")

    assert any("Read AGENTS.md" in item for item in summary["local_governance"])
    assert any("Inspector must verify AGENTS.md" in item for item in summary["local_governance"])
    assert any("GateKeeper treats skipped AGENTS.md" in item for item in summary["local_governance"])
    assert "collaboration_summary" not in local_item["surfaces"]
    assert "spec.markdown#Role Notes" in local_item["surfaces"]
    assert local_item["mapped"] is True
    assert "local_governance" not in summary["traceability"]["missing"]


def test_bundle_control_summary_keeps_complete_local_governance_chain_when_builder_mentions_repeat(
    sample_workdir: Path,
) -> None:
    bundle = _add_project_local_governance_responsibilities(
        load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    )
    role_by_key = {role["key"]: role for role in bundle["role_definitions"]}
    for index in range(6):
        role_by_key["builder"]["prompt_markdown"] += (
            f"\n\nBuilder reads AGENTS.md and design/README.md before editing phase {index}."
        )

    summary = build_bundle_control_summary(bundle)
    local_item = next(item for item in summary["traceability"]["items"] if item["key"] == "local_governance")

    assert any("Builder reads AGENTS.md" in item for item in local_item["evidence"])
    assert any("Inspector must verify AGENTS.md" in item for item in local_item["evidence"])
    assert any("GateKeeper treats skipped AGENTS.md" in item for item in local_item["evidence"])
    assert local_item["mapped"] is True


def test_bundle_control_summary_does_not_map_marker_lists_as_local_governance(sample_workdir: Path) -> None:
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    bundle["collaboration_summary"] += " AGENTS.md, design/README.md, design/, and tests/ are visible markers."

    summary = build_bundle_control_summary(bundle)
    local_item = next(item for item in summary["traceability"]["items"] if item["key"] == "local_governance")

    assert summary["local_governance"] == []
    assert local_item["mapped"] is False
    assert "local_governance" in summary["traceability"]["missing"]


def test_bundle_control_summary_requires_complete_local_governance_chain(sample_workdir: Path) -> None:
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    role_by_key = {role["key"]: role for role in bundle["role_definitions"]}
    role_by_key["builder"]["prompt_markdown"] += (
        "\n\nBuilder reads AGENTS.md and design/README.md before changing code."
    )

    summary = build_bundle_control_summary(bundle)
    local_item = next(item for item in summary["traceability"]["items"] if item["key"] == "local_governance")

    assert summary["local_governance"] == []
    assert local_item["mapped"] is False
    assert "local_governance" in summary["traceability"]["missing"]


def test_bundle_control_summary_does_not_map_summary_only_local_governance_chain(sample_workdir: Path) -> None:
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    bundle["collaboration_summary"] += (
        "\nBuilder reads AGENTS.md and design/README.md before editing. "
        "Inspector verifies AGENTS.md and tests/ obligations against the result. "
        "GateKeeper treats skipped AGENTS.md or tests/ evidence as Weak, Unproven, or Blocking."
    )

    summary = build_bundle_control_summary(bundle)
    local_item = next(item for item in summary["traceability"]["items"] if item["key"] == "local_governance")

    assert summary["local_governance"] == []
    assert local_item["mapped"] is False
    assert "local_governance" in summary["traceability"]["missing"]


def test_bundle_governance_summary_projects_local_governance(service_factory, sample_workdir: Path) -> None:
    service = service_factory(scenario="success")
    bundle = _add_project_local_governance_responsibilities(
        load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    )

    governance = service._bundle_governance_summary(bundle)

    assert any("Read AGENTS.md" in item for item in governance["local_governance"])


def test_bundle_governance_summary_omits_summary_only_local_governance(service_factory, sample_workdir: Path) -> None:
    service = service_factory(scenario="success")
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    bundle["collaboration_summary"] += (
        "\nBuilder reads AGENTS.md and design/README.md before editing. "
        "Inspector verifies AGENTS.md and tests/ obligations against the result. "
        "GateKeeper treats skipped AGENTS.md or tests/ evidence as Weak, Unproven, or Blocking."
    )

    governance = service._bundle_governance_summary(bundle)

    assert governance["local_governance"] == []


def test_bundle_governance_summary_omits_unmanaged_residual_risk(service_factory, sample_workdir: Path) -> None:
    service = service_factory(scenario="success")
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    bundle["spec"]["markdown"] = bundle["spec"]["markdown"].replace(
        "Accept minor polish gaps only when they are explicitly named and tracked as an owned follow-up; fail closed on unproven primary-flow behavior or weak verification evidence.",
        "Some risk is fine.",
    )

    governance = service._bundle_governance_summary(bundle)

    assert governance["residual_risk_policy"] == []


def test_bundle_control_summary_projects_strict_vs_pragmatic_tradeoff() -> None:
    traceability = _traceability_projection(
        {
            "bundle": {
                "collaboration_summary": "Strict blocking beats pragmatic progress when evidence is weak.",
            },
            "raw_sections": {"Task": "Do the work.", "Evidence Preferences": "Collect evidence."},
            "roles": [{"name": "Builder", "archetype": "builder", "posture_notes": "Build the slice."}],
            "workflow": {"collaboration_intent": "Builder then GateKeeper."},
            "workflow_projection": {"summary": "Builder -> GateKeeper"},
            "gatekeeper": {"enabled": True, "roles": ["GateKeeper"], "finish_steps": ["gatekeeper_step"]},
            "controls": [],
        }
    )

    tradeoff_item = next(item for item in traceability["items"] if item["key"] == "judgment_tradeoffs")
    assert tradeoff_item["mapped"] is True
    assert tradeoff_item["evidence"] == ["Strict blocking beats pragmatic progress when evidence is weak."]
    assert "judgment_tradeoffs" not in traceability["missing"]


def test_bundle_control_summary_prioritizes_task_specific_tradeoffs(sample_workdir: Path) -> None:
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    bundle["spec"]["markdown"] += "\n\nTradeoff: strict blocking beats pragmatic progress when evidence is weak."

    summary = build_bundle_control_summary(bundle)

    assert any("strict blocking beats pragmatic progress" in item for item in summary["judgment_tradeoffs"])
    assert len(summary["judgment_tradeoffs"]) <= 4


def test_bundle_control_summary_does_not_invent_tradeoff_projection() -> None:
    traceability = _traceability_projection(
        {
            "bundle": {"collaboration_summary": "Use the available plan surfaces."},
            "raw_sections": {"Task": "Do the work.", "Evidence Preferences": "Collect evidence."},
            "roles": [{"name": "Builder", "archetype": "builder", "posture_notes": "Build the slice."}],
            "workflow": {"collaboration_intent": "Builder then GateKeeper."},
            "workflow_projection": {"summary": "Builder -> GateKeeper"},
            "gatekeeper": {"enabled": True, "roles": ["GateKeeper"], "finish_steps": ["gatekeeper_step"]},
            "controls": [],
        }
    )

    tradeoff_item = next(item for item in traceability["items"] if item["key"] == "judgment_tradeoffs")
    assert tradeoff_item["mapped"] is False
    assert "judgment_tradeoffs" in traceability["missing"]
