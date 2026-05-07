from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from textwrap import dedent

import pytest

from loopora.bundles import (
    bundle_to_yaml,
    lint_alignment_bundle_generation_metadata,
    lint_alignment_bundle_generation_text,
    lint_alignment_bundle_semantics,
    load_bundle_text,
)
from loopora.executor_fake_payloads import alignment_bundle_yaml
from loopora.service import LooporaError
from loopora.service_types import LooporaConflictError
from loopora.settings import app_home, configure_logging
import loopora.service_cleanup_diagnostics as cleanup_diagnostics


def _bundle_yaml(workdir: Path, *, collaboration_summary: str = "Prefer evidence before rushing forward.") -> str:
    return dedent(
        f"""
        version: 1
        metadata:
          name: "Guided Inspect First"
          description: "Bundle created from task-scoped alignment."
        collaboration_summary: |
          {collaboration_summary}
        loop:
          name: "Guided Inspect First"
          workdir: "{workdir}"
          completion_mode: "gatekeeper"
          executor_kind: "codex"
          executor_mode: "preset"
          model: "gpt-5.4"
          reasoning_effort: "medium"
          max_iters: 4
          max_role_retries: 1
          delta_threshold: 0.005
          trigger_window: 2
          regression_window: 2
        spec:
          markdown: |
            # Task

            Ship the requested behavior without creating brittle structure.

            # Done When

            - The primary experience completes successfully.
            - The edge path stays safe and understandable.

            # Guardrails

            - Keep changes focused.

            # Success Surface

            - The implementation stays maintainable for the next round.

            # Fake Done

            - A patch that only fixes the happy path while leaving obvious duplication behind.

            # Evidence Preferences

            - Prefer real project commands and reproducible tests over screenshots alone.

            # Residual Risk

            Minor copy polish can wait, but structural regressions should fail closed.

            # Role Notes

            ## Builder Notes

            Keep the implementation narrow and verifiable.
        role_definitions:
          - key: "builder"
            name: "Focused Builder"
            description: "Implements the smallest maintainable change."
            archetype: "builder"
            prompt_markdown: |
              ---
              version: 1
              archetype: builder
              ---

              Build carefully and keep the repo coherent.
            posture_notes: |
              Treat maintainability debt as first-class in this task.
          - key: "inspector"
            name: "Evidence Inspector"
            description: "Collects reproducible evidence."
            archetype: "inspector"
            prompt_markdown: |
              ---
              version: 1
              archetype: inspector
              ---

              Collect evidence conservatively.
            posture_notes: |
              Prefer project-owned commands and primary artifacts.
          - key: "gatekeeper"
            name: "Conservative GateKeeper"
            description: "Fails closed when evidence is weak."
            archetype: "gatekeeper"
            prompt_markdown: |
              ---
              version: 1
              archetype: gatekeeper
              ---

              Judge from direct evidence only.
            posture_notes: |
              Do not pass brittle fixes just because the happy path moved.
        workflow:
          version: 1
          preset: "inspect_first"
          collaboration_intent: "Start with evidence, then commit to one repair slice."
          roles:
            - id: "inspector"
              role_definition_key: "inspector"
            - id: "builder"
              role_definition_key: "builder"
            - id: "gatekeeper"
              role_definition_key: "gatekeeper"
          steps:
            - id: "inspector_step"
              role_id: "inspector"
            - id: "builder_step"
              role_id: "builder"
            - id: "gatekeeper_step"
              role_id: "gatekeeper"
              on_pass: "finish_run"
        """
    ).strip() + "\n"


def test_service_imports_and_exports_bundle_round_trip(service_factory, sample_workdir: Path) -> None:
    service = service_factory(scenario="success")

    imported = service.import_bundle_text(_bundle_yaml(sample_workdir))

    assert imported["name"] == "Guided Inspect First"
    assert imported["loop"] is not None
    assert imported["orchestration"] is not None
    assert len(imported["role_definitions"]) == 3

    exported = service.export_bundle(imported["id"])

    assert exported["collaboration_summary"].startswith("Prefer evidence")
    assert exported["workflow"]["collaboration_intent"] == "Start with evidence, then commit to one repair slice."
    assert exported["spec"]["markdown"].startswith("# Task")
    assert exported["role_definitions"][0]["posture_notes"]

    rerun = service.rerun(imported["loop_id"])
    assert rerun["status"] == "succeeded"


@pytest.mark.parametrize(
    ("yaml_line", "error_text"),
    (
        ('  delta_threshold: "inf"', "bundle loop settings must use finite numbers"),
        ("  delta_threshold: -0.1", "bundle loop.delta_threshold must be >= 0"),
    ),
)
def test_bundle_import_rejects_invalid_loop_runtime_numbers(
    service_factory,
    sample_workdir: Path,
    yaml_line: str,
    error_text: str,
) -> None:
    service = service_factory(scenario="success")
    yaml_text = _bundle_yaml(sample_workdir).replace("  delta_threshold: 0.005", yaml_line)

    with pytest.raises(LooporaError, match=error_text):
        service.import_bundle_text(yaml_text)


def test_bundle_import_preserves_zero_loop_runtime_numbers(service_factory, sample_workdir: Path) -> None:
    service = service_factory(scenario="success")
    yaml_text = (
        _bundle_yaml(sample_workdir)
        .replace("  max_iters: 4", "  max_iters: 0")
        .replace("  max_role_retries: 1", "  max_role_retries: 0")
        .replace("  delta_threshold: 0.005", "  delta_threshold: 0")
    )

    imported = service.import_bundle_text(yaml_text)

    assert imported["loop"]["max_iters"] == 0
    assert imported["loop"]["max_role_retries"] == 0
    assert imported["loop"]["delta_threshold"] == 0.0
    exported = service.export_bundle(imported["id"])
    assert exported["loop"]["max_iters"] == 0
    assert exported["loop"]["max_role_retries"] == 0
    assert exported["loop"]["delta_threshold"] == 0.0


def test_bundle_round_trip_preserves_parallel_groups_and_step_inputs(service_factory, sample_workdir: Path) -> None:
    service = service_factory(scenario="success")
    yaml_text = _bundle_yaml(sample_workdir).replace(
        '  - key: "gatekeeper"\n'
        '    name: "Conservative GateKeeper"',
        '  - key: "semantic-inspector"\n'
        '    name: "Semantic Inspector"\n'
        '    description: "Checks task posture and fake-done risk."\n'
        '    archetype: "inspector"\n'
        '    prompt_markdown: |\n'
        '      ---\n'
        '      version: 1\n'
        '      archetype: inspector\n'
        '      ---\n\n'
        '      Inspect semantic task fit and evidence gaps.\n'
        '    posture_notes: |\n'
        '      Prefer task-specific fake-done evidence over generic checklist confidence.\n'
        '  - key: "gatekeeper"\n'
        '    name: "Conservative GateKeeper"',
    ).replace(
        '  roles:\n'
        '    - id: "inspector"\n'
        '      role_definition_key: "inspector"\n'
        '    - id: "builder"\n'
        '      role_definition_key: "builder"\n'
        '    - id: "gatekeeper"\n'
        '      role_definition_key: "gatekeeper"\n'
        '  steps:\n'
        '    - id: "inspector_step"\n'
        '      role_id: "inspector"\n'
        '    - id: "builder_step"\n'
        '      role_id: "builder"\n'
        '    - id: "gatekeeper_step"\n'
        '      role_id: "gatekeeper"\n'
        '      on_pass: "finish_run"',
        '  roles:\n'
        '    - id: "builder"\n'
        '      role_definition_key: "builder"\n'
        '    - id: "inspector"\n'
        '      role_definition_key: "inspector"\n'
        '    - id: "semantic"\n'
        '      role_definition_key: "semantic-inspector"\n'
        '    - id: "gatekeeper"\n'
        '      role_definition_key: "gatekeeper"\n'
        '  steps:\n'
        '    - id: "builder_step"\n'
        '      role_id: "builder"\n'
        '    - id: "inspector_step"\n'
        '      role_id: "inspector"\n'
        '      parallel_group: "inspection_pack"\n'
        '      inputs:\n'
        '        handoffs_from: ["builder_step"]\n'
        '        evidence_query:\n'
        '          archetypes: ["builder"]\n'
        '          limit: 8\n'
        '    - id: "semantic_step"\n'
        '      role_id: "semantic"\n'
        '      parallel_group: "inspection_pack"\n'
        '    - id: "gatekeeper_step"\n'
        '      role_id: "gatekeeper"\n'
        '      on_pass: "finish_run"\n'
        '      inputs:\n'
        '        handoffs_from: ["inspector_step", "semantic_step"]',
    )

    imported = service.import_bundle_text(yaml_text)
    exported = service.export_bundle(imported["id"])
    steps = exported["workflow"]["steps"]

    assert steps[1]["parallel_group"] == "inspection_pack"
    assert steps[1]["inputs"]["handoffs_from"] == ["builder_step"]
    assert steps[1]["inputs"]["evidence_query"] == {"archetypes": ["builder"], "limit": 8}
    assert steps[2]["parallel_group"] == "inspection_pack"
    assert steps[3]["inputs"] == {"handoffs_from": ["inspector_step", "semantic_step"]}


def _has_cleanup_record(caplog, *, operation: str, resource_type: str, owner_id: str | None = None) -> bool:
    records = [
        {
            "event": getattr(record, "event", ""),
            "context": getattr(record, "context", {}) or {},
        }
        for record in caplog.records
    ]
    log_path = app_home() / "logs" / "service.log"
    if log_path.exists():
        records.extend(
            json.loads(line)
            for line in log_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    return any(
        record.get("event") == "service.cleanup.failed"
        and (record.get("context") or {}).get("operation") == operation
        and (record.get("context") or {}).get("resource_type") == resource_type
        and (owner_id is None or (record.get("context") or {}).get("owner_id") == owner_id)
        for record in records
    )


def test_bundle_round_trip_preserves_explicit_step_action_policy(service_factory, sample_workdir: Path) -> None:
    service = service_factory(scenario="success")
    yaml_text = _bundle_yaml(sample_workdir).replace(
        '    - id: "inspector_step"\n'
        '      role_id: "inspector"\n'
        '    - id: "builder_step"\n'
        '      role_id: "builder"\n',
        '    - id: "inspector_step"\n'
        '      role_id: "inspector"\n'
        "      action_policy:\n"
        '        workspace: "read_only"\n'
        "        can_block: false\n"
        "        can_finish_run: false\n"
        '    - id: "builder_step"\n'
        '      role_id: "builder"\n'
        "      action_policy:\n"
        '        workspace: "workspace_write"\n'
        "        can_block: false\n"
        "        can_finish_run: false\n",
    )

    imported = service.import_bundle_text(yaml_text)
    exported = service.export_bundle(imported["id"])
    policies = {step["id"]: step["action_policy"] for step in exported["workflow"]["steps"]}

    assert policies["inspector_step"] == {
        "workspace": "read_only",
        "can_block": False,
        "can_finish_run": False,
    }
    assert policies["builder_step"] == {
        "workspace": "workspace_write",
        "can_block": False,
        "can_finish_run": False,
    }


def test_bundle_round_trip_preserves_workflow_controls(service_factory, sample_workdir: Path) -> None:
    service = service_factory(scenario="success")
    yaml_text = _bundle_yaml(sample_workdir).replace(
        '      on_pass: "finish_run"\n',
        '      on_pass: "finish_run"\n'
        "  controls:\n"
        '    - id: "gatekeeper_rejection_review"\n'
        "      when:\n"
        '        signal: "gatekeeper_rejected"\n'
        '        after: "0s"\n'
        "      call:\n"
        '        role_id: "inspector"\n'
        '      mode: "advisory"\n'
        "      max_fires_per_run: 1\n",
    )

    imported = service.import_bundle_text(yaml_text)
    exported = service.export_bundle(imported["id"])

    assert exported["workflow"]["controls"] == [
        {
            "id": "gatekeeper_rejection_review",
            "when": {"signal": "gatekeeper_rejected", "after": "0s"},
            "call": {"role_id": "inspector"},
            "mode": "advisory",
            "max_fires_per_run": 1,
        }
    ]


def test_bundle_rejects_controls_that_call_builders(service_factory, sample_workdir: Path) -> None:
    service = service_factory(scenario="success")
    yaml_text = _bundle_yaml(sample_workdir).replace(
        '      on_pass: "finish_run"\n',
        '      on_pass: "finish_run"\n'
        "  controls:\n"
        '    - id: "implicit_repair"\n'
        "      when:\n"
        '        signal: "step_failed"\n'
        '        after: "0s"\n'
        "      call:\n"
        '        role_id: "builder"\n',
    )

    with pytest.raises(LooporaError, match="controls may only call Inspector, Guide, or GateKeeper"):
        service.preview_bundle_text(yaml_text)


def test_bundle_rejects_zero_workflow_control_max_fires(service_factory, sample_workdir: Path) -> None:
    service = service_factory(scenario="success")
    yaml_text = _bundle_yaml(sample_workdir).replace(
        '      on_pass: "finish_run"\n',
        '      on_pass: "finish_run"\n'
        "  controls:\n"
        '    - id: "disabled_review"\n'
        "      when:\n"
        '        signal: "gatekeeper_rejected"\n'
        '        after: "0s"\n'
        "      call:\n"
        '        role_id: "inspector"\n'
        '      mode: "advisory"\n'
        "      max_fires_per_run: 0\n",
    )

    with pytest.raises(LooporaError, match="control max_fires_per_run must be between 1 and 20"):
        service.preview_bundle_text(yaml_text)


def test_bundle_preview_projects_error_control_summary(service_factory, sample_workdir: Path) -> None:
    service = service_factory(scenario="success")

    yaml_text = _bundle_yaml(sample_workdir).replace(
        '      on_pass: "finish_run"\n',
        '      on_pass: "finish_run"\n'
        "  controls:\n"
        '    - id: "gatekeeper_rejection_review"\n'
        "      when:\n"
        '        signal: "gatekeeper_rejected"\n'
        '        after: "0s"\n'
        "      call:\n"
        '        role_id: "inspector"\n'
        '      mode: "advisory"\n',
    )
    preview = service.preview_bundle_text(yaml_text)

    summary = preview["control_summary"]
    traceability = summary["traceability"]
    assert summary["risks"]
    assert summary["evidence"]
    assert summary["gatekeeper"]["enabled"] is True
    assert summary["gatekeeper"]["requires_evidence_refs"] is True
    assert summary["workflow"]["step_count"] == 3
    assert summary["controls"][0]["signal"] == "gatekeeper_rejected"
    assert summary["controls"][0]["role_name"] == "Evidence Inspector"
    assert preview["diagnostics"] == summary["diagnostics"]
    assert {item["code"] for item in summary["diagnostics"]} >= {
        "gatekeeper_missing_handoff_fan_in",
        "gatekeeper_missing_evidence_fan_in",
    }
    assert preview["traceability"] == traceability
    assert traceability["mapped_count"] == traceability["required_count"]
    assert "spec.markdown#Fake Done" in traceability["surfaces"]
    assert "workflow.controls[]" in traceability["surfaces"]


def test_bundle_preview_warns_about_legacy_guide_and_weak_builder_handoff(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    yaml_text = (
        _bundle_yaml(sample_workdir)
        .replace(
            "  - key: \"gatekeeper\"\n",
            "  - key: \"guide\"\n"
            "    name: \"Repair Guide\"\n"
            "    description: \"Narrows the next move from upstream evidence.\"\n"
            "    archetype: \"guide\"\n"
            "    prompt_markdown: |\n"
            "      ---\n"
            "      version: 1\n"
            "      archetype: guide\n"
            "      ---\n\n"
            "      Guide the next repair slice.\n"
            "    posture_notes: |\n"
            "      Turn weak or unproven evidence into a smaller repair direction.\n"
            "  - key: \"gatekeeper\"\n",
        )
        .replace(
            "    - id: \"builder\"\n      role_definition_key: \"builder\"\n",
            "    - id: \"guide\"\n"
            "      role_definition_key: \"guide\"\n"
            "    - id: \"builder\"\n"
            "      role_definition_key: \"builder\"\n",
        )
        .replace(
            "    - id: \"builder_step\"\n      role_id: \"builder\"\n",
            "    - id: \"guide_step\"\n"
            "      role_id: \"guide\"\n"
            "    - id: \"builder_step\"\n"
            "      role_id: \"builder\"\n",
        )
    )

    preview = service.preview_bundle_text(yaml_text)

    codes = {item["code"] for item in preview["diagnostics"]}
    assert "guide_missing_upstream_handoff" in codes
    assert "guide_missing_upstream_evidence" in codes
    assert "builder_missing_guide_handoff" in codes


def test_bundle_control_summary_does_not_hide_invalid_fire_limit_projection(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    yaml_text = _bundle_yaml(sample_workdir).replace(
        '      on_pass: "finish_run"\n',
        '      on_pass: "finish_run"\n'
        "  controls:\n"
        '    - id: "gatekeeper_rejection_review"\n'
        "      when:\n"
        '        signal: "gatekeeper_rejected"\n'
        '        after: "0s"\n'
        "      call:\n"
        '        role_id: "inspector"\n'
        '      mode: "advisory"\n',
    )
    bundle = service.preview_bundle_text(yaml_text)["bundle"]
    bundle["workflow"]["controls"][0]["max_fires_per_run"] = 0

    assert service._bundle_control_summary(bundle)["controls"][0]["max_fires_per_run"] == 0

    bundle["workflow"]["controls"][0]["max_fires_per_run"] = "not-a-number"
    assert service._bundle_control_summary(bundle)["controls"][0]["max_fires_per_run"] == "not-a-number"


def test_bundle_preview_rejects_spec_markdown_that_cannot_compile(service_factory, sample_workdir: Path) -> None:
    service = service_factory(scenario="success")
    invalid_yaml = _bundle_yaml(sample_workdir).replace("## Builder Notes", "Builder notes without a subheading")

    with pytest.raises(LooporaError, match="Role Notes"):
        service.preview_bundle_text(invalid_yaml)


def test_alignment_semantic_lint_requires_residual_risk(sample_workdir: Path) -> None:
    valid_bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    assert "spec must include Residual Risk guidance" not in lint_alignment_bundle_semantics(valid_bundle)

    yaml_without_residual_risk = re.sub(
        r"\n    # Residual Risk\n\n    .+?(?=\n\n    # Role Notes)",
        "\n",
        alignment_bundle_yaml(str(sample_workdir.resolve())),
        flags=re.DOTALL,
    )
    issues = lint_alignment_bundle_semantics(load_bundle_text(yaml_without_residual_risk))

    assert "spec must include Residual Risk guidance" in issues


def test_alignment_semantic_lint_accepts_alternate_residual_risk_prose(sample_workdir: Path) -> None:
    valid_bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    assert "spec Residual Risk must say what can remain visible and what must block" not in lint_alignment_bundle_semantics(valid_bundle)

    yaml_with_generic_residual_risk = re.sub(
        r"\n    # Residual Risk\n\n    .+?(?=\n\n    # Role Notes)",
        "\n    # Residual Risk\n\n    Some remaining risk is probably fine for this task.",
        alignment_bundle_yaml(str(sample_workdir.resolve())),
        flags=re.DOTALL,
    )
    issues = lint_alignment_bundle_semantics(load_bundle_text(yaml_with_generic_residual_risk))

    assert "spec Residual Risk must say what can remain visible and what must block" not in issues


def test_alignment_semantic_lint_requires_summary_governance_story(sample_workdir: Path) -> None:
    valid_bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    assert "collaboration_summary must explain the governance story" not in lint_alignment_bundle_semantics(valid_bundle)

    yaml_without_governance_summary = re.sub(
        r"collaboration_summary: \|\n(?:  .+\n)+loop:",
        'collaboration_summary: "Build the requested task."\nloop:',
        alignment_bundle_yaml(str(sample_workdir.resolve())),
    )
    issues = lint_alignment_bundle_semantics(load_bundle_text(yaml_without_governance_summary))

    assert "collaboration_summary must explain the governance story" in issues


def test_alignment_semantic_lint_accepts_concise_summary_without_surface_keywords(sample_workdir: Path) -> None:
    valid_bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    assert not any("project judgment across spec, roles, and workflow" in issue for issue in lint_alignment_bundle_semantics(valid_bundle))

    yaml_without_surface_projection = re.sub(
        r"collaboration_summary: \|\n(?:  .+\n)+loop:",
        (
            "collaboration_summary: |\n"
            "  Collect reproducible evidence and let GateKeeper block weak proof before closing the task.\n"
            "loop:"
        ),
        alignment_bundle_yaml(str(sample_workdir.resolve())),
    )
    issues = lint_alignment_bundle_semantics(load_bundle_text(yaml_without_surface_projection))

    assert "collaboration_summary must project judgment across spec, roles, and workflow" not in issues


def test_alignment_semantic_lint_accepts_summary_that_names_surfaces_without_mapping_verbs(sample_workdir: Path) -> None:
    valid_bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    assert not any("maps onto spec, roles, and workflow" in issue for issue in lint_alignment_bundle_semantics(valid_bundle))

    yaml_with_surface_list_only = re.sub(
        r"collaboration_summary: \|\n(?:  .+\n)+loop:",
        (
            "collaboration_summary: |\n"
            "  The spec, roles, and workflow all support evidence collection, "
            "handoff review, and GateKeeper final judgment for this concrete starter task.\n"
            "loop:"
        ),
        alignment_bundle_yaml(str(sample_workdir.resolve())),
    )
    issues = lint_alignment_bundle_semantics(load_bundle_text(yaml_with_surface_list_only))

    assert "collaboration_summary must explain how judgment maps onto spec, roles, and workflow" not in issues


def test_alignment_semantic_lint_accepts_chinese_summary_surface_projection(sample_workdir: Path) -> None:
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    bundle["collaboration_summary"] = (
        "把工作协议投影到任务契约、角色和 workflow：spec 承载成功面、假完成和残余风险，"
        "角色负责 Builder、Inspector、GateKeeper 的证据交接，workflow 安排并行检查、信息流和 GateKeeper 裁决。"
    )

    assert not any("collaboration_summary" in issue for issue in lint_alignment_bundle_semantics(bundle))


@pytest.mark.parametrize(
    "generic_task",
    [
        "Do the task.",
        "Ship the focused starter experience described only by the alignment agreement.",
    ],
)
def test_alignment_semantic_lint_requires_specific_task_contract(sample_workdir: Path, generic_task: str) -> None:
    valid_bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    assert "spec Task must describe the concrete user-facing task" not in lint_alignment_bundle_semantics(valid_bundle)

    yaml_with_generic_task = re.sub(
        r"\n    # Task\n\n    .+?(?=\n\n    # Done When)",
        f"\n    # Task\n\n    {generic_task}",
        alignment_bundle_yaml(str(sample_workdir.resolve())),
        flags=re.DOTALL,
    )
    issues = lint_alignment_bundle_semantics(load_bundle_text(yaml_with_generic_task))

    assert "spec Task must describe the concrete user-facing task" in issues


def test_alignment_semantic_lint_requires_done_when_checks(sample_workdir: Path) -> None:
    valid_bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    assert "spec must include at least one Done When bullet" not in lint_alignment_bundle_semantics(valid_bundle)

    yaml_without_done_when = re.sub(
        r"\n    # Done When\n\n    - .+?(?=\n\n    # Guardrails)",
        "",
        alignment_bundle_yaml(str(sample_workdir.resolve())),
        flags=re.DOTALL,
    )
    issues = lint_alignment_bundle_semantics(load_bundle_text(yaml_without_done_when))

    assert "spec must include at least one Done When bullet" in issues


def test_alignment_semantic_lint_accepts_alternate_done_when_wording(sample_workdir: Path) -> None:
    valid_bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    assert "spec Done When must contain concrete, judgeable success checks" not in lint_alignment_bundle_semantics(valid_bundle)

    yaml_with_generic_done_when = re.sub(
        r"\n    # Done When\n\n    - .+?(?=\n\n    # Guardrails)",
        "\n    # Done When\n\n    - It works.\n    - The task is done.",
        alignment_bundle_yaml(str(sample_workdir.resolve())),
        flags=re.DOTALL,
    )
    issues = lint_alignment_bundle_semantics(load_bundle_text(yaml_with_generic_done_when))

    assert "spec Done When must contain concrete, judgeable success checks" not in issues


def test_alignment_semantic_lint_accepts_alternate_success_surface_wording(sample_workdir: Path) -> None:
    valid_bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    assert "spec Success Surface must name an observable, runnable, or checkable result" not in lint_alignment_bundle_semantics(valid_bundle)

    yaml_with_generic_success_surface = re.sub(
        r"\n    # Success Surface\n\n    - .+?(?=\n\n    # Fake Done)",
        "\n    # Success Surface\n\n    - The result is high quality and useful.",
        alignment_bundle_yaml(str(sample_workdir.resolve())),
        flags=re.DOTALL,
    )
    issues = lint_alignment_bundle_semantics(load_bundle_text(yaml_with_generic_success_surface))

    assert "spec Success Surface must name an observable, runnable, or checkable result" not in issues


def test_alignment_semantic_lint_accepts_alternate_evidence_preference_wording(sample_workdir: Path) -> None:
    valid_bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    assert "spec Evidence Preferences must name a concrete proof type" not in lint_alignment_bundle_semantics(valid_bundle)

    yaml_with_generic_evidence = re.sub(
        r"\n    # Evidence Preferences\n\n    - .+?(?=\n\n    # Residual Risk)",
        "\n    # Evidence Preferences\n\n    - Need enough evidence before accepting the result.",
        alignment_bundle_yaml(str(sample_workdir.resolve())),
        flags=re.DOTALL,
    )
    issues = lint_alignment_bundle_semantics(load_bundle_text(yaml_with_generic_evidence))

    assert "spec Evidence Preferences must name a concrete proof type" not in issues


def test_alignment_semantic_lint_requires_evidence_bucket_projection(sample_workdir: Path) -> None:
    valid_bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    assert not any("must project task verdict evidence" in issue for issue in lint_alignment_bundle_semantics(valid_bundle))

    yaml_without_bucket_projection = (
        alignment_bundle_yaml(str(sample_workdir.resolve()))
        .replace(
            " Evidence projection must distinguish Proven direct run proof, Weak indirect evidence, "
            "Unproven promised surfaces, Blocking fake-done findings, and visible Residual risk.",
            "",
        )
        .replace(
            "    - Final evidence should be bucketed as Proven, Weak, Unproven, Blocking, "
            "or Residual risk instead of flattened into one summary.\n",
            "",
        )
    )
    issues = lint_alignment_bundle_semantics(load_bundle_text(yaml_without_bucket_projection))

    assert (
        "alignment bundle must project task verdict evidence into Proven, Weak, Unproven, "
        "Blocking, and Residual risk buckets"
    ) in issues


def test_alignment_semantic_lint_requires_gatekeeper_completion_mode(sample_workdir: Path) -> None:
    valid_bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    assert not any("must use gatekeeper completion_mode" in issue for issue in lint_alignment_bundle_semantics(valid_bundle))

    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    bundle["loop"]["completion_mode"] = "rounds"
    issues = lint_alignment_bundle_semantics(bundle)

    assert (
        "Web alignment bundles must use gatekeeper completion_mode so task verdict is evidence-based, "
        "not only run lifecycle completion"
    ) in issues


def test_alignment_generated_metadata_omits_lineage_fields(sample_workdir: Path) -> None:
    valid_yaml = alignment_bundle_yaml(str(sample_workdir.resolve()))
    assert lint_alignment_bundle_generation_text(valid_yaml) == []
    assert lint_alignment_bundle_generation_metadata(valid_yaml) == []

    lineage_yaml = valid_yaml.replace(
        '  description: "Bundle generated by the Web alignment flow."\n',
        '  description: "Bundle generated by the Web alignment flow."\n'
        '  source_bundle_id: "source_bundle_old"\n'
        "  revision: 2\n",
        1,
    )

    assert lint_alignment_bundle_generation_metadata(lineage_yaml) == [
        "Web alignment generated bundles must omit metadata.source_bundle_id and metadata.revision; "
        "source context is temporary and final bundles are standalone candidates"
    ]
    semantic_issues = lint_alignment_bundle_semantics(load_bundle_text(lineage_yaml))
    assert (
        "Web alignment bundles must not encode metadata.source_bundle_id; "
        "source context is temporary and final bundles are standalone candidates"
    ) in semantic_issues


def test_alignment_generated_bundle_text_must_be_raw_yaml(sample_workdir: Path) -> None:
    valid_yaml = alignment_bundle_yaml(str(sample_workdir.resolve()))
    yaml_with_internal_fence = valid_yaml.replace(
        "Leave concrete handoffs and evidence references for downstream review.",
        "Leave concrete handoffs and evidence references for downstream review.\n\n      ```text\n      internal example\n      ```",
        1,
    )

    fenced_issues = lint_alignment_bundle_generation_text(f"```yaml\n{valid_yaml}```")
    prefixed_issues = lint_alignment_bundle_generation_text("Here is the bundle:\n" + valid_yaml)
    comment_prefixed_issues = lint_alignment_bundle_generation_text("# Here is the bundle\n" + valid_yaml)

    assert lint_alignment_bundle_generation_text(yaml_with_internal_fence) == []
    assert "Web alignment generated bundle_yaml must be one raw YAML document, not markdown-fenced output" in fenced_issues
    assert "Web alignment generated bundle_yaml must start with version: 1" in fenced_issues
    assert prefixed_issues == ["Web alignment generated bundle_yaml must start with version: 1"]
    assert comment_prefixed_issues == ["Web alignment generated bundle_yaml must start with version: 1"]


def test_alignment_semantic_lint_does_not_hard_block_judgment_tradeoff_wording(sample_workdir: Path) -> None:
    valid_bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    assert not any("must project judgment tradeoffs" in issue for issue in lint_alignment_bundle_semantics(valid_bundle))

    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    bundle["collaboration_summary"] = (
        "Project the working agreement into spec, roles, and workflow: spec carries the concrete task "
        "contract and evidence needs, roles own Builder / Inspector / GateKeeper handoffs, and workflow "
        "routes proof before final GateKeeper judgment."
    )
    bundle["spec"]["markdown"] = (
        bundle["spec"]["markdown"]
        .replace("Prefer project-owned checks", "Use project-owned checks")
        .replace("Prefer a small maintainable patch over broad rewrites.", "Keep the patch small, maintainable, and verifiable.")
        .replace("Fail closed when", "Treat as a blocker when")
        .replace("fail closed on", "treat as a blocker for")
    )
    for role in bundle["role_definitions"]:
        if role["key"] == "builder":
            role["posture_notes"] = (
                "Keep implementation narrow and leave a verifiable handoff with changed behavior, command evidence, "
                "and blockers for later review."
            )
        elif role["key"] == "contract-inspector":
            role["posture_notes"] = (
                "Inspect the delivered slice against agreed scope and report unresolved fake-done risk as a blocker "
                "with concrete evidence references."
            )
        elif role["key"] == "evidence-inspector":
            role["posture_notes"] = (
                "Collect direct run output, concrete artifacts, and missing-proof blockers in a clear handoff for "
                "GateKeeper review."
            )
        elif role["key"] == "gatekeeper":
            role["posture_notes"] = (
                "Block missing handoff evidence and close only after the task contract and verification evidence agree."
            )

    issues = lint_alignment_bundle_semantics(bundle)

    assert not any("must project judgment tradeoffs" in issue for issue in issues)


def test_alignment_semantic_lint_rejects_personality_memory_bundle(sample_workdir: Path) -> None:
    valid_bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    assert not any("personality memory" in issue for issue in lint_alignment_bundle_semantics(valid_bundle))

    valid_bundle["collaboration_summary"] = (
        "This bundle maps the user's permanent preference memory into spec, roles, and workflow "
        "so Builder always follows the user's global personality, Inspector gathers browser "
        "and test evidence, and GateKeeper signs off only after that evidence supports the "
        "preferred behavior."
    )
    issues = lint_alignment_bundle_semantics(valid_bundle)

    assert "alignment bundle must stay task-scoped, not personality memory or global preferences" in issues


@pytest.mark.parametrize(
    "antipattern_phrase",
    [
        "prompt pack",
        "role zoo",
        "loop script",
        "benchmark grinder",
        "chat wrapper",
    ],
)
def test_alignment_semantic_lint_rejects_named_loopora_antipatterns(
    sample_workdir: Path,
    antipattern_phrase: str,
) -> None:
    valid_bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    assert not any("prompt pack" in issue for issue in lint_alignment_bundle_semantics(valid_bundle))

    valid_bundle["collaboration_summary"] = (
        f"This {antipattern_phrase} maps the user's task into spec, roles, and workflow. "
        "Builder follows the role prose, Inspector gathers browser and test evidence, "
        "and GateKeeper signs off only after proof supports the promised task surface."
    )
    issues = lint_alignment_bundle_semantics(valid_bundle)

    assert (
        "alignment bundle must not present prompt pack, role zoo, loop script, "
        "benchmark grinder, or chat wrapper as Loopora governance"
    ) in issues


def test_alignment_semantic_lint_allows_antipatterns_named_as_fake_done_risks(sample_workdir: Path) -> None:
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    bundle["collaboration_summary"] += (
        " The spec also avoids prompt pack and personality memory failures by keeping "
        "the judgment task-scoped and evidence-owned."
    )

    issues = lint_alignment_bundle_semantics(bundle)

    assert not any("prompt pack" in issue for issue in issues)
    assert not any("personality memory" in issue for issue in issues)


def test_alignment_semantic_lint_accepts_alternate_fake_done_wording(
    sample_workdir: Path,
) -> None:
    valid_bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    assert "spec Fake Done must name a shallow or false-completion risk" not in lint_alignment_bundle_semantics(valid_bundle)

    yaml_with_generic_fake_done = re.sub(
        r"\n    # Fake Done\n\n    - .+?(?=\n\n    # Evidence Preferences)",
        "\n    # Fake Done\n\n    - Avoid bugs and low quality results.",
        alignment_bundle_yaml(str(sample_workdir.resolve())),
        flags=re.DOTALL,
    )
    issues = lint_alignment_bundle_semantics(load_bundle_text(yaml_with_generic_fake_done))

    assert "spec Fake Done must name a shallow or false-completion risk" not in issues


def test_alignment_semantic_lint_does_not_hard_block_workflow_intent_wording(
    sample_workdir: Path,
) -> None:
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    assert not any("workflow.collaboration_intent" in issue for issue in lint_alignment_bundle_semantics(bundle))

    bundle["workflow"]["collaboration_intent"] = (
        "Coordinate the task-specific starter implementation across the selected roles, "
        "keeping the work focused and manageable for this Loop."
    )
    issues = lint_alignment_bundle_semantics(bundle)

    assert not any("workflow.collaboration_intent must explain evidence flow" in issue for issue in issues)
    assert not any("workflow.collaboration_intent must explain final GateKeeper" in issue for issue in issues)
    assert not any("workflow.collaboration_intent must explain where weak evidence" in issue for issue in issues)

    bundle["workflow"]["collaboration_intent"] = (
        "Build the starter implementation, inspect evidence from the Builder handoff, "
        "and let GateKeeper finish when verification supports the task contract."
    )
    issues = lint_alignment_bundle_semantics(bundle)

    assert not any("workflow.collaboration_intent must explain where weak evidence" in issue for issue in issues)


def test_alignment_semantic_lint_does_not_hard_block_parallel_rationale_wording(
    sample_workdir: Path,
) -> None:
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    assert "workflow.collaboration_intent must explain why bounded parallel inspection is needed" not in lint_alignment_bundle_semantics(bundle)

    bundle["workflow"]["collaboration_intent"] = (
        "Build one focused starter slice, inspect evidence from the Builder handoff, "
        "then let GateKeeper finish only when inspection evidence supports the task contract."
    )
    issues = lint_alignment_bundle_semantics(bundle)

    assert "workflow.collaboration_intent must explain why bounded parallel inspection is needed" not in issues


def test_alignment_semantic_lint_requires_parallel_review_to_read_upstream_handoffs(
    sample_workdir: Path,
) -> None:
    valid_bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    assert not any("parallel review step must name upstream handoffs" in issue for issue in lint_alignment_bundle_semantics(valid_bundle))

    yaml_with_missing_parallel_handoff_input = alignment_bundle_yaml(str(sample_workdir.resolve())).replace(
        'handoffs_from: ["builder_step"]',
        "handoffs_from: []",
        1,
    )
    issues = lint_alignment_bundle_semantics(load_bundle_text(yaml_with_missing_parallel_handoff_input))

    assert (
        "parallel review step must name upstream handoffs in inputs.handoffs_from: "
        "contract_inspection_step"
    ) in issues


def test_alignment_semantic_lint_requires_review_after_builder_to_read_builder_inputs(
    sample_workdir: Path,
) -> None:
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    steps_by_id = {step["id"]: step for step in bundle["workflow"]["steps"]}
    steps_by_id["contract_inspection_step"].pop("parallel_group")
    steps_by_id["evidence_inspection_step"].pop("parallel_group")
    assert not any("review step after Builder" in issue for issue in lint_alignment_bundle_semantics(bundle))

    steps_by_id["contract_inspection_step"].pop("inputs")
    issues = lint_alignment_bundle_semantics(bundle)

    assert (
        "review step after Builder must name a Builder handoff in inputs.handoffs_from: "
        "contract_inspection_step"
    ) in issues
    assert (
        "review step after Builder must query Builder evidence in inputs.evidence_query: "
        "contract_inspection_step"
    ) in issues


def test_alignment_semantic_lint_requires_custom_after_builder_to_read_builder_inputs(
    sample_workdir: Path,
) -> None:
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    _make_contract_inspector_custom_review(bundle)
    steps_by_id = {step["id"]: step for step in bundle["workflow"]["steps"]}
    steps_by_id["contract_inspection_step"].pop("parallel_group")
    steps_by_id["evidence_inspection_step"].pop("parallel_group")
    steps_by_id["gatekeeper_step"]["inputs"]["evidence_query"]["archetypes"].append("custom")
    assert not any("review step after Builder" in issue for issue in lint_alignment_bundle_semantics(bundle))

    steps_by_id["contract_inspection_step"].pop("inputs")
    issues = lint_alignment_bundle_semantics(bundle)

    assert (
        "review step after Builder must name a Builder handoff in inputs.handoffs_from: "
        "contract_inspection_step"
    ) in issues
    assert (
        "review step after Builder must query Builder evidence in inputs.evidence_query: "
        "contract_inspection_step"
    ) in issues


def test_alignment_semantic_lint_requires_parallel_review_to_read_same_upstream_handoff(
    sample_workdir: Path,
) -> None:
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    assert not any("same upstream handoffs" in issue for issue in lint_alignment_bundle_semantics(bundle))
    steps_by_id = {step["id"]: step for step in bundle["workflow"]["steps"]}
    steps_by_id["evidence_inspection_step"]["inputs"]["handoffs_from"] = ["contract_inspection_step"]
    issues = lint_alignment_bundle_semantics(bundle)

    assert (
        "parallel review steps must read the same upstream handoffs: "
        "contract_inspection_step, evidence_inspection_step"
    ) in issues


def test_alignment_semantic_lint_requires_parallel_review_to_query_builder_evidence(
    sample_workdir: Path,
) -> None:
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    assert not any(
        "parallel review step must query Builder evidence" in issue
        for issue in lint_alignment_bundle_semantics(bundle)
    )
    steps_by_id = {step["id"]: step for step in bundle["workflow"]["steps"]}
    steps_by_id["contract_inspection_step"]["inputs"].pop("evidence_query")
    issues = lint_alignment_bundle_semantics(bundle)

    assert (
        "parallel review step must query Builder evidence in inputs.evidence_query: "
        "contract_inspection_step"
    ) in issues


def test_alignment_semantic_lint_requires_parallel_review_iteration_memory(
    sample_workdir: Path,
) -> None:
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    assert not any(
        "parallel review step must declare inputs.iteration_memory" in issue
        for issue in lint_alignment_bundle_semantics(bundle)
    )
    steps_by_id = {step["id"]: step for step in bundle["workflow"]["steps"]}
    steps_by_id["contract_inspection_step"]["inputs"].pop("iteration_memory")

    issues = lint_alignment_bundle_semantics(bundle)

    assert (
        "parallel review step must declare inputs.iteration_memory so cross-iteration evidence flow is explicit: "
        "contract_inspection_step"
    ) in issues


def test_alignment_semantic_lint_requires_parallel_review_to_use_distinct_role_definitions(
    sample_workdir: Path,
) -> None:
    valid_bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    assert not any("distinct role_definition_key" in issue for issue in lint_alignment_bundle_semantics(valid_bundle))

    yaml_with_shared_parallel_role_definition = alignment_bundle_yaml(str(sample_workdir.resolve())).replace(
        'role_definition_key: "contract-inspector"',
        'role_definition_key: "evidence-inspector"',
        1,
    )
    issues = lint_alignment_bundle_semantics(load_bundle_text(yaml_with_shared_parallel_role_definition))

    assert (
        "parallel review steps must use distinct role_definition_key values: "
        "contract_inspection_step, evidence_inspection_step"
    ) in issues


def test_alignment_semantic_lint_requires_parallel_review_to_have_distinct_posture(
    sample_workdir: Path,
) -> None:
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    assert not any(
        "responsibility-specific prompt and posture" in issue
        for issue in lint_alignment_bundle_semantics(bundle)
    )
    role_by_key = {role["key"]: role for role in bundle["role_definitions"]}
    role_by_key["contract-inspector"]["name"] = role_by_key["evidence-inspector"]["name"]
    role_by_key["contract-inspector"]["description"] = role_by_key["evidence-inspector"]["description"]
    role_by_key["contract-inspector"]["prompt_markdown"] = role_by_key["evidence-inspector"]["prompt_markdown"]
    role_by_key["contract-inspector"]["posture_notes"] = role_by_key["evidence-inspector"]["posture_notes"]
    issues = lint_alignment_bundle_semantics(bundle)

    assert (
        "parallel review role_definitions must have responsibility-specific prompt and posture: "
        "contract-inspector, evidence-inspector"
    ) in issues


def test_alignment_semantic_lint_rejects_generic_role_names(sample_workdir: Path) -> None:
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    assert not any("task-specific role name" in issue for issue in lint_alignment_bundle_semantics(bundle))
    role_by_key = {role["key"]: role for role in bundle["role_definitions"]}
    role_by_key["contract-inspector"]["name"] = "Inspector 1"
    role_by_key["evidence-inspector"]["name"] = "Inspector 2"
    issues = lint_alignment_bundle_semantics(bundle)

    assert "role_definition contract-inspector must use a task-specific role name" in issues
    assert "role_definition evidence-inspector must use a task-specific role name" in issues


def test_alignment_semantic_lint_does_not_hard_block_role_responsibility_wording(
    sample_workdir: Path,
) -> None:
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    assert not any("responsibility" in issue for issue in lint_alignment_bundle_semantics(bundle))
    role_by_key = {role["key"]: role for role in bundle["role_definitions"]}

    generic_role_text = {
        "description": "Maintains evidence handoffs for downstream roles.",
        "posture_notes": "Prefer concrete evidence and clear handoffs over broad confidence.",
    }
    role_by_key["builder"].update(generic_role_text)
    role_by_key["builder"]["prompt_markdown"] = """---
version: 1
archetype: builder
---

Leave reproducible evidence, handoff notes, and blockers for downstream roles."""
    role_by_key["contract-inspector"].update(generic_role_text)
    role_by_key["contract-inspector"]["prompt_markdown"] = """---
version: 1
archetype: inspector
---

Collect direct evidence and leave blockers for GateKeeper."""
    role_by_key["gatekeeper"].update(generic_role_text)
    role_by_key["gatekeeper"]["prompt_markdown"] = """---
version: 1
archetype: gatekeeper
---

Read upstream evidence and leave a handoff for the next round."""

    issues = lint_alignment_bundle_semantics(bundle)

    assert not any("must describe Builder construction" in issue for issue in issues)
    assert not any("must describe Inspector inspection" in issue for issue in issues)
    assert not any("must describe GateKeeper final judgment" in issue for issue in issues)


def test_alignment_semantic_lint_uses_graph_contract_for_custom_review_roles(
    sample_workdir: Path,
) -> None:
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    role_by_key = {role["key"]: role for role in bundle["role_definitions"]}
    role_by_key["contract-inspector"]["archetype"] = "custom"
    role_by_key["contract-inspector"]["prompt_markdown"] = role_by_key["contract-inspector"][
        "prompt_markdown"
    ].replace("archetype: inspector", "archetype: custom")

    issues = lint_alignment_bundle_semantics(bundle)

    assert not any("Custom read-only specialized review" in issue for issue in issues)
    assert "finishing GateKeeper after review must query review evidence in inputs.evidence_query: custom" in issues


def _add_repair_guide_flow(bundle: dict) -> dict:
    bundle["role_definitions"].append(
        {
            "key": "repair-guide",
            "name": "Repair Direction Guide",
            "description": "Turns inspection evidence into a focused repair direction.",
            "archetype": "guide",
            "prompt_ref": "repair-guide.md",
            "prompt_markdown": """---
version: 1
archetype: guide
---

Use the inspection evidence to narrow the next Builder step. Leave a handoff that names the repair direction, the evidence behind it, and the scope that must not expand.""",
            "posture_notes": "Narrow the repair target from review evidence instead of offering broad advice.",
            "executor_kind": "codex",
            "executor_mode": "preset",
            "command_cli": "",
            "command_args_text": "",
            "model": "",
            "reasoning_effort": "",
        }
    )
    bundle["workflow"]["roles"].append(
        {"id": "repair_guide", "role_definition_key": "repair-guide"}
    )
    gatekeeper_step = bundle["workflow"]["steps"][-1]
    bundle["workflow"]["steps"].insert(
        -1,
        {
            "id": "repair_guide_step",
            "role_id": "repair_guide",
            "inputs": {
                "handoffs_from": ["contract_inspection_step", "evidence_inspection_step"],
                "evidence_query": {"archetypes": ["inspector"], "limit": 12},
                "iteration_memory": "summary_only",
            },
            "on_pass": "continue",
        },
    )
    gatekeeper_step["inputs"]["handoffs_from"].append("repair_guide_step")
    gatekeeper_step["inputs"]["evidence_query"]["archetypes"].append("guide")
    return bundle


def test_alignment_semantic_lint_does_not_hard_block_guide_prompt_wording(
    sample_workdir: Path,
) -> None:
    bundle = _add_repair_guide_flow(load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve()))))
    assert not any("role_definition repair-guide" in issue for issue in lint_alignment_bundle_semantics(bundle))

    guide_role = next(role for role in bundle["role_definitions"] if role["key"] == "repair-guide")
    guide_role["description"] = "Maintains evidence handoffs for downstream roles."
    guide_role["prompt_markdown"] = """---
version: 1
archetype: guide
---

Read upstream evidence and leave a clear handoff for downstream roles."""
    guide_role["posture_notes"] = "Prefer concrete evidence and clear handoffs over broad confidence."

    issues = lint_alignment_bundle_semantics(bundle)

    assert not any("role_definition repair-guide must describe Guide" in issue for issue in issues)


def test_alignment_semantic_lint_requires_guide_after_review_to_read_review_inputs(
    sample_workdir: Path,
) -> None:
    bundle = _add_repair_guide_flow(load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve()))))
    assert not any("Guide step after review" in issue for issue in lint_alignment_bundle_semantics(bundle))
    steps_by_id = {step["id"]: step for step in bundle["workflow"]["steps"]}
    steps_by_id["repair_guide_step"]["inputs"]["handoffs_from"] = ["builder_step"]
    steps_by_id["repair_guide_step"]["inputs"].pop("evidence_query")

    issues = lint_alignment_bundle_semantics(bundle)

    assert (
        "Guide step after review must include review handoffs in inputs.handoffs_from: "
        "repair_guide_step"
    ) in issues
    assert (
        "Guide step after review must query review evidence in inputs.evidence_query: "
        "inspector"
    ) in issues


def _make_contract_inspector_custom_review(bundle: dict) -> None:
    role_by_key = {role["key"]: role for role in bundle["role_definitions"]}
    contract_role = role_by_key["contract-inspector"]
    contract_role["archetype"] = "custom"
    contract_role["prompt_markdown"] = contract_role["prompt_markdown"].replace(
        "archetype: inspector",
        "archetype: custom",
    )
    contract_role["prompt_markdown"] += (
        "\n\n      Act as a read-only specialized Custom reviewer for contract evidence; "
        "do not edit files, and leave a focused handoff."
    )
    contract_role["posture_notes"] += (
        " As a low-permission Custom reviewer, provide only specialized contract review signal."
    )


def test_alignment_semantic_lint_treats_custom_as_review_before_builder(
    sample_workdir: Path,
) -> None:
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    _make_contract_inspector_custom_review(bundle)
    bundle["workflow"]["steps"].insert(
        0,
        {
            "id": "preflight_custom_review_step",
            "role_id": "contract_inspector",
            "on_pass": "continue",
        },
    )
    steps_by_id = {step["id"]: step for step in bundle["workflow"]["steps"]}
    steps_by_id["builder_step"]["inputs"] = {
        "handoffs_from": ["preflight_custom_review_step"],
        "iteration_memory": "summary_only",
    }
    steps_by_id["gatekeeper_step"]["inputs"]["evidence_query"]["archetypes"].append("custom")
    assert not any("Builder step after review" in issue for issue in lint_alignment_bundle_semantics(bundle))

    steps_by_id["builder_step"]["inputs"] = {"handoffs_from": []}
    issues = lint_alignment_bundle_semantics(bundle)

    assert (
        "Builder step after review must include review handoffs in inputs.handoffs_from: "
        "builder_step"
    ) in issues
    assert (
        "Builder step after review must declare inputs.iteration_memory so evidence-first repair does not rely on ambient context: "
        "builder_step"
    ) in issues


def test_alignment_semantic_lint_treats_custom_as_review_before_gatekeeper(
    sample_workdir: Path,
) -> None:
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    _make_contract_inspector_custom_review(bundle)
    steps_by_id = {step["id"]: step for step in bundle["workflow"]["steps"]}
    steps_by_id["contract_inspection_step"].pop("parallel_group")
    steps_by_id["evidence_inspection_step"].pop("parallel_group")
    steps_by_id["gatekeeper_step"]["inputs"]["handoffs_from"] = ["evidence_inspection_step"]
    steps_by_id["gatekeeper_step"]["inputs"]["evidence_query"]["archetypes"] = ["builder", "inspector"]

    issues = lint_alignment_bundle_semantics(bundle)

    assert (
        "finishing GateKeeper after review must include review handoffs in inputs.handoffs_from: "
        "contract_inspection_step"
    ) in issues
    assert (
        "finishing GateKeeper after review must query review evidence in inputs.evidence_query: "
        "custom"
    ) in issues


def test_alignment_semantic_lint_requires_guide_after_review_iteration_memory(
    sample_workdir: Path,
) -> None:
    bundle = _add_repair_guide_flow(load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve()))))
    steps_by_id = {step["id"]: step for step in bundle["workflow"]["steps"]}
    steps_by_id["repair_guide_step"]["inputs"].pop("iteration_memory")

    issues = lint_alignment_bundle_semantics(bundle)

    assert (
        "Guide step after review must declare inputs.iteration_memory so repair guidance can use prior iteration evidence explicitly: "
        "repair_guide_step"
    ) in issues


def test_alignment_semantic_lint_requires_builder_after_guide_to_read_guide_handoff(
    sample_workdir: Path,
) -> None:
    bundle = _add_repair_guide_flow(load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve()))))
    gatekeeper_step = bundle["workflow"]["steps"].pop()
    bundle["workflow"]["steps"].append(
        {
            "id": "builder_repair_step",
            "role_id": "builder",
            "inputs": {
                "handoffs_from": ["builder_step"],
                "iteration_memory": "same_step",
            },
            "on_pass": "continue",
        }
    )
    gatekeeper_step["inputs"]["handoffs_from"].append("builder_repair_step")
    bundle["workflow"]["steps"].append(gatekeeper_step)

    issues = lint_alignment_bundle_semantics(bundle)

    assert (
        "Builder step after Guide must name a Guide handoff in inputs.handoffs_from: "
        "builder_repair_step"
    ) in issues


def test_alignment_semantic_lint_requires_builder_after_guide_iteration_memory(
    sample_workdir: Path,
) -> None:
    bundle = _add_repair_guide_flow(load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve()))))
    gatekeeper_step = bundle["workflow"]["steps"].pop()
    bundle["workflow"]["steps"].append(
        {
            "id": "builder_repair_step",
            "role_id": "builder",
            "inputs": {
                "handoffs_from": ["repair_guide_step"],
            },
            "on_pass": "continue",
        }
    )
    gatekeeper_step["inputs"]["handoffs_from"].append("builder_repair_step")
    bundle["workflow"]["steps"].append(gatekeeper_step)

    issues = lint_alignment_bundle_semantics(bundle)

    assert (
        "Builder step after Guide must declare inputs.iteration_memory so repair pass does not rely on ambient context: "
        "builder_repair_step"
    ) in issues


def test_alignment_semantic_lint_requires_builder_after_review_to_read_review_handoff(
    sample_workdir: Path,
) -> None:
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    bundle["workflow"]["steps"].insert(
        0,
        {
            "id": "preflight_inspection_step",
            "role_id": "contract_inspector",
            "on_pass": "continue",
        },
    )
    steps_by_id = {step["id"]: step for step in bundle["workflow"]["steps"]}
    steps_by_id["builder_step"]["inputs"] = {
        "handoffs_from": ["preflight_inspection_step"],
        "iteration_memory": "summary_only",
    }
    assert not any("Builder step after review" in issue for issue in lint_alignment_bundle_semantics(bundle))

    steps_by_id["builder_step"]["inputs"]["handoffs_from"] = []
    issues = lint_alignment_bundle_semantics(bundle)

    assert (
        "Builder step after review must include review handoffs in inputs.handoffs_from: "
        "builder_step"
    ) in issues


def test_alignment_semantic_lint_requires_builder_after_review_iteration_memory(
    sample_workdir: Path,
) -> None:
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    bundle["workflow"]["steps"].insert(
        0,
        {
            "id": "preflight_inspection_step",
            "role_id": "contract_inspector",
            "on_pass": "continue",
        },
    )
    steps_by_id = {step["id"]: step for step in bundle["workflow"]["steps"]}
    steps_by_id["builder_step"]["inputs"] = {
        "handoffs_from": ["preflight_inspection_step"],
    }

    issues = lint_alignment_bundle_semantics(bundle)

    assert (
        "Builder step after review must declare inputs.iteration_memory so evidence-first repair does not rely on ambient context: "
        "builder_step"
    ) in issues


def test_alignment_semantic_lint_requires_gatekeeper_to_read_parallel_handoffs(sample_workdir: Path) -> None:
    valid_bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    assert not any("parallel review handoff" in issue for issue in lint_alignment_bundle_semantics(valid_bundle))

    yaml_with_missing_parallel_handoff = alignment_bundle_yaml(str(sample_workdir.resolve())).replace(
        'handoffs_from: ["contract_inspection_step", "evidence_inspection_step"]',
        'handoffs_from: ["evidence_inspection_step"]',
        1,
    )
    issues = lint_alignment_bundle_semantics(load_bundle_text(yaml_with_missing_parallel_handoff))

    assert (
        "GateKeeper step must include every parallel review handoff in inputs.handoffs_from: "
        "contract_inspection_step"
    ) in issues


def test_alignment_semantic_lint_requires_finishing_gatekeeper_to_read_handoff_and_evidence(
    sample_workdir: Path,
) -> None:
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    assert not any("finishing GateKeeper step" in issue for issue in lint_alignment_bundle_semantics(bundle))
    steps_by_id = {step["id"]: step for step in bundle["workflow"]["steps"]}
    steps_by_id["gatekeeper_step"].pop("inputs")
    issues = lint_alignment_bundle_semantics(bundle)

    assert (
        "finishing GateKeeper step must name upstream handoffs in inputs.handoffs_from: "
        "gatekeeper_step"
    ) in issues
    assert (
        "finishing GateKeeper step must query upstream evidence in inputs.evidence_query: "
        "gatekeeper_step"
    ) in issues


def test_alignment_semantic_lint_requires_gatekeeper_after_review_to_read_review_evidence(
    sample_workdir: Path,
) -> None:
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    assert not any("GateKeeper after review" in issue for issue in lint_alignment_bundle_semantics(bundle))
    steps_by_id = {step["id"]: step for step in bundle["workflow"]["steps"]}
    steps_by_id["contract_inspection_step"].pop("parallel_group")
    steps_by_id["evidence_inspection_step"].pop("parallel_group")
    steps_by_id["gatekeeper_step"]["inputs"]["handoffs_from"] = ["builder_step"]
    steps_by_id["gatekeeper_step"]["inputs"]["evidence_query"]["archetypes"] = ["builder"]

    issues = lint_alignment_bundle_semantics(bundle)

    assert (
        "finishing GateKeeper after review must include review handoffs in inputs.handoffs_from: "
        "contract_inspection_step, evidence_inspection_step"
    ) in issues
    assert (
        "finishing GateKeeper after review must query review evidence in inputs.evidence_query: "
        "inspector"
    ) in issues


def test_alignment_semantic_lint_requires_gatekeeper_to_query_builder_and_inspector_evidence(
    sample_workdir: Path,
) -> None:
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    assert not any(
        "GateKeeper step must query Builder and parallel review evidence" in issue
        for issue in lint_alignment_bundle_semantics(bundle)
    )
    steps_by_id = {step["id"]: step for step in bundle["workflow"]["steps"]}
    steps_by_id["gatekeeper_step"]["inputs"]["evidence_query"]["archetypes"] = ["inspector"]
    issues = lint_alignment_bundle_semantics(bundle)

    assert (
        "GateKeeper step must query Builder and parallel review evidence in inputs.evidence_query: "
        "builder"
    ) in issues


def test_alignment_semantic_lint_gatekeeper_fan_in_counts_parallel_custom_review_steps(
    sample_workdir: Path,
) -> None:
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    role_by_key = {role["key"]: role for role in bundle["role_definitions"]}
    role_by_key["contract-inspector"]["archetype"] = "custom"
    role_by_key["evidence-inspector"]["archetype"] = "custom"
    role_by_key["contract-inspector"]["prompt_markdown"] = role_by_key["contract-inspector"][
        "prompt_markdown"
    ].replace("archetype: inspector", "archetype: custom")
    role_by_key["evidence-inspector"]["prompt_markdown"] = role_by_key["evidence-inspector"][
        "prompt_markdown"
    ].replace("archetype: inspector", "archetype: custom")
    role_by_key["contract-inspector"]["prompt_markdown"] += (
        "\n\n      Act as a read-only specialized Custom reviewer for contract evidence; "
        "do not edit files, and leave a focused handoff."
    )
    role_by_key["contract-inspector"]["posture_notes"] += (
        " As a low-permission Custom reviewer, provide only specialized review signal."
    )
    role_by_key["evidence-inspector"]["prompt_markdown"] += (
        "\n\n      Act as a read-only specialized Custom reviewer for evidence quality; "
        "do not edit files, and leave a focused handoff."
    )
    role_by_key["evidence-inspector"]["posture_notes"] += (
        " As a low-permission Custom reviewer, provide only specialized evidence signal."
    )
    steps_by_id = {step["id"]: step for step in bundle["workflow"]["steps"]}
    steps_by_id["gatekeeper_step"]["inputs"]["handoffs_from"] = []
    steps_by_id["gatekeeper_step"]["inputs"]["evidence_query"]["archetypes"] = ["builder"]

    issues = lint_alignment_bundle_semantics(bundle)

    assert (
        "GateKeeper step must include every parallel review handoff in inputs.handoffs_from: "
        "contract_inspection_step, evidence_inspection_step"
    ) in issues
    assert (
        "GateKeeper step must query Builder and parallel review evidence in inputs.evidence_query: "
        "custom"
    ) in issues


def _long_chain_multi_builder_bundle(workdir: Path) -> dict:
    bundle = load_bundle_text(alignment_bundle_yaml(str(workdir.resolve())))
    role_defaults = {
        "executor_kind": "codex",
        "executor_mode": "preset",
        "command_cli": "",
        "command_args_text": "",
        "model": "",
        "reasoning_effort": "",
    }

    def role(
        key: str,
        name: str,
        archetype: str,
        body: str,
        posture: str,
    ) -> dict:
        return {
            "key": key,
            "name": name,
            "description": body,
            "archetype": archetype,
            "prompt_ref": f"{key}.md",
            "prompt_markdown": f"""---
version: 1
archetype: {archetype}
---

{body} Leave a handoff that names Proven, Weak, Unproven, Blocking, and Residual risk evidence for downstream roles.""",
            "posture_notes": posture,
            **role_defaults,
        }

    bundle["metadata"]["name"] = "Search Long-Chain Bundle"
    bundle["loop"]["name"] = "Search Long-Chain Bundle"
    bundle["collaboration_summary"] = (
        "Compile the search refactor into a long-chain workflow because query rewriting, retrieval, "
        "ranking, regression review, and evidence hardening each create distinct artifacts, handoffs, "
        "and proof targets. GateKeeper must judge from phase evidence rather than only the final "
        "Builder story, separating Proven, Weak, Unproven, Blocking, and Residual risk claims."
    )
    bundle["role_definitions"] = [
        role(
            "baseline-inspector",
            "Search Baseline Inspector",
            "inspector",
            "Inspect the current search behavior and pin the first reproducible baseline before implementation.",
            "Treat unsupported baseline claims as Unproven and identify the first proof path the Builders must preserve.",
        ),
        role(
            "query-builder",
            "Query Rewrite Builder",
            "builder",
            "Implement only the query rewrite phase and preserve a narrow evidence handoff for retrieval work.",
            "Move query rewrite behavior toward Proven without changing retrieval or ranking standards silently.",
        ),
        role(
            "retrieval-builder",
            "Retrieval Builder",
            "builder",
            "Implement only the retrieval phase from the query handoff and leave concrete retrieval evidence.",
            "Preserve the query phase contract while producing a distinct retrieval artifact and proof target.",
        ),
        role(
            "ranking-builder",
            "Ranking Builder",
            "builder",
            "Implement only the ranking phase from retrieval evidence and avoid masking recall regressions.",
            "Prefer maintainable ranking progress over metric theater; expose weak proof instead of broad claims.",
        ),
        role(
            "regression-inspector",
            "Search Regression Inspector",
            "inspector",
            "Review query, retrieval, and ranking handoffs against the baseline and search regressions.",
            "Mark regressions as Blocking, thin evidence as Weak, and unsupported phase claims as Unproven.",
        ),
        role(
            "evidence-hardening-builder",
            "Evidence Hardening Builder",
            "builder",
            "Add only missing proof or harness support requested by regression review.",
            "Do not widen product scope; turn review gaps into durable evidence that GateKeeper can inspect.",
        ),
        role(
            "search-gatekeeper",
            "Search Evidence GateKeeper",
            "gatekeeper",
            "Judge the long-chain search refactor from baseline, phase, regression, and evidence-hardening handoffs.",
            "Finish only when critical phase claims are Proven or acceptable Residual risk, and fail closed on Blocking gaps.",
        ),
    ]
    bundle["workflow"] = {
        "version": 1,
        "preset": "",
        "collaboration_intent": (
            "Use a long-chain phase workflow because the search task has distinct query, retrieval, ranking, "
            "regression, and evidence-hardening proof targets. Each Builder owns one phase handoff; "
            "Regression Inspector checks phase evidence before Evidence Hardening Builder repairs proof gaps; "
            "GateKeeper fans in baseline, regression, and final evidence so weak evidence, drift, or fake done "
            "surface before closure."
        ),
        "roles": [
            {"id": "baseline_inspector", "role_definition_key": "baseline-inspector"},
            {"id": "query_builder", "role_definition_key": "query-builder"},
            {"id": "retrieval_builder", "role_definition_key": "retrieval-builder"},
            {"id": "ranking_builder", "role_definition_key": "ranking-builder"},
            {"id": "regression_inspector", "role_definition_key": "regression-inspector"},
            {"id": "evidence_hardening_builder", "role_definition_key": "evidence-hardening-builder"},
            {"id": "gatekeeper", "role_definition_key": "search-gatekeeper"},
        ],
        "steps": [
            {"id": "baseline_inspection_step", "role_id": "baseline_inspector", "on_pass": "continue"},
            {
                "id": "query_builder_step",
                "role_id": "query_builder",
                "inputs": {"handoffs_from": ["baseline_inspection_step"], "iteration_memory": "summary_only"},
                "on_pass": "continue",
            },
            {
                "id": "retrieval_builder_step",
                "role_id": "retrieval_builder",
                "inputs": {"handoffs_from": ["query_builder_step"], "iteration_memory": "same_step"},
                "on_pass": "continue",
            },
            {
                "id": "ranking_builder_step",
                "role_id": "ranking_builder",
                "inputs": {"handoffs_from": ["retrieval_builder_step"], "iteration_memory": "same_step"},
                "on_pass": "continue",
            },
            {
                "id": "regression_inspection_step",
                "role_id": "regression_inspector",
                "inputs": {
                    "handoffs_from": [
                        "query_builder_step",
                        "retrieval_builder_step",
                        "ranking_builder_step",
                    ],
                    "evidence_query": {"archetypes": ["builder"], "limit": 30},
                    "iteration_memory": "summary_only",
                },
                "on_pass": "continue",
            },
            {
                "id": "evidence_hardening_builder_step",
                "role_id": "evidence_hardening_builder",
                "inputs": {"handoffs_from": ["regression_inspection_step"], "iteration_memory": "same_step"},
                "on_pass": "continue",
            },
            {
                "id": "gatekeeper_step",
                "role_id": "gatekeeper",
                "inputs": {
                    "handoffs_from": [
                        "baseline_inspection_step",
                        "regression_inspection_step",
                        "evidence_hardening_builder_step",
                    ],
                    "evidence_query": {"archetypes": ["builder", "inspector"], "limit": 40},
                },
                "on_pass": "finish_run",
            },
        ],
    }
    return load_bundle_text(bundle_to_yaml(bundle))


def test_alignment_semantic_lint_accepts_long_chain_multi_builder_workflows(
    sample_workdir: Path,
) -> None:
    bundle = _long_chain_multi_builder_bundle(sample_workdir)

    issues = lint_alignment_bundle_semantics(bundle)

    assert issues == []


def test_alignment_semantic_lint_requires_long_chain_gatekeeper_to_read_phase_handoffs(
    sample_workdir: Path,
) -> None:
    bundle = _long_chain_multi_builder_bundle(sample_workdir)
    steps_by_id = {step["id"]: step for step in bundle["workflow"]["steps"]}
    steps_by_id["gatekeeper_step"]["inputs"]["handoffs_from"] = ["evidence_hardening_builder_step"]

    issues = lint_alignment_bundle_semantics(bundle)

    assert (
        "long-chain GateKeeper must include an earlier phase, review, or Guide handoff in inputs.handoffs_from: "
        "gatekeeper_step"
    ) in issues


def test_alignment_semantic_lint_does_not_hard_block_control_risk_wording(
    sample_workdir: Path,
) -> None:
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    bundle["workflow"]["controls"] = [
        {
            "id": "gatekeeper_rejection_review",
            "when": {"signal": "gatekeeper_rejected", "after": "0s"},
            "call": {"role_id": "contract_inspector"},
            "mode": "advisory",
            "max_fires_per_run": 1,
        }
    ]
    issues = lint_alignment_bundle_semantics(bundle)

    assert not any("workflow control gatekeeper_rejection_review" in issue for issue in issues)

    bundle["workflow"]["collaboration_intent"] += (
        " If repeated GateKeeper rejection shows evidence drift, route the Contract Inspector "
        "back in before another finish attempt."
    )
    assert not any("workflow control gatekeeper_rejection_review" in issue for issue in lint_alignment_bundle_semantics(bundle))


@pytest.mark.parametrize(
    ("yaml_edit", "message"),
    [
        (lambda text: text.replace("version: 1", "version: 0", 1), "unsupported bundle version: 0"),
        (lambda text: text.replace("version: 1", "version: not-a-number", 1), "bundle version must be an integer"),
        (
            lambda text: text.replace(
                '  description: "Bundle created from task-scoped alignment."',
                '  description: "Bundle created from task-scoped alignment."\n  revision: 0',
                1,
            ),
            r"bundle metadata\.revision must be >= 1",
        ),
        (
            lambda text: text.replace("workflow:\n  version: 1", "workflow:\n  version: 0", 1),
            "unsupported bundle workflow version: 0",
        ),
        (
            lambda text: text.replace("workflow:\n  version: 1", "workflow:\n  version: false", 1),
            "bundle workflow version must be an integer",
        ),
    ],
)
def test_bundle_preview_rejects_invalid_explicit_versions(
    service_factory,
    sample_workdir: Path,
    yaml_edit,
    message: str,
) -> None:
    service = service_factory(scenario="success")

    with pytest.raises(LooporaError, match=message):
        service.preview_bundle_text(yaml_edit(_bundle_yaml(sample_workdir)))


def test_bundle_preview_rejects_task_contract_list_sections_without_bullets(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    invalid_yaml = _bundle_yaml(sample_workdir).replace(
        "- The implementation stays maintainable for the next round.",
        "The implementation stays maintainable for the next round.",
    )

    with pytest.raises(LooporaError, match="Success Surface"):
        service.preview_bundle_text(invalid_yaml)


@pytest.mark.parametrize(
    ("yaml_edit", "message"),
    [
        (lambda text: text.replace('id: "inspector"', 'id: "inspect/or"', 1), "bundle workflow role id"),
        (lambda text: text.replace('id: "builder_step"', 'id: "../builder_step"', 1), "bundle workflow step id"),
        (
            lambda text: text.replace(
                'role_id: "inspector"\n    - id: "builder_step"',
                'role_id: "inspector"\n      parallel_group: "review/pack"\n    - id: "builder_step"',
                1,
            ),
            "workflow step parallel_group",
        ),
        (
            lambda text: text.replace(
                '      on_pass: "finish_run"\n',
                '      on_pass: "finish_run"\n'
                "  controls:\n"
                '    - id: "control/escape"\n'
                "      when:\n"
                '        signal: "gatekeeper_rejected"\n'
                "      call:\n"
                '        role_id: "inspector"\n',
            ),
            "workflow control id",
        ),
    ],
)
def test_bundle_preview_rejects_unsafe_workflow_identifiers(
    service_factory,
    sample_workdir: Path,
    yaml_edit,
    message: str,
) -> None:
    service = service_factory(scenario="success")
    invalid_yaml = yaml_edit(_bundle_yaml(sample_workdir))

    with pytest.raises(LooporaError, match=message):
        service.preview_bundle_text(invalid_yaml)


def test_bundle_preview_rejects_gatekeeper_mode_without_finishing_gatekeeper_step(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    invalid_yaml = _bundle_yaml(sample_workdir).replace('on_pass: "finish_run"', 'on_pass: "continue"')

    with pytest.raises(LooporaError, match="GateKeeper step"):
        service.preview_bundle_text(invalid_yaml)


def test_bundle_delete_cleans_imported_group_but_keeps_unrelated_assets(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    manual_role = service.create_role_definition(
        name="Manual Builder",
        description="Unrelated role",
        archetype="builder",
        prompt_markdown=dedent(
            """\
            ---
            version: 1
            archetype: builder
            ---

            Keep going.
            """
        ),
    )
    manual_orchestration = service.create_orchestration(
        name="Manual Flow",
        workflow={"preset": "build_first"},
    )
    manual_loop = service.create_loop(
        name="Manual Loop",
        spec_path=sample_spec_file,
        workdir=sample_workdir,
        model="gpt-5.4",
        reasoning_effort="medium",
        max_iters=3,
        max_role_retries=1,
        delta_threshold=0.005,
        trigger_window=2,
        regression_window=2,
        orchestration_id=manual_orchestration["id"],
    )

    other_workdir = sample_workdir.parent / "bundle-workdir"
    other_workdir.mkdir()
    imported = service.import_bundle_text(_bundle_yaml(other_workdir))

    deleted = service.delete_bundle(imported["id"])

    assert deleted == {"id": imported["id"], "deleted": True}
    assert service.get_role_definition(manual_role["id"])["name"] == "Manual Builder"
    assert service.get_orchestration(manual_orchestration["id"])["name"] == "Manual Flow"
    assert service.get_loop(manual_loop["id"])["name"] == "Manual Loop"
    with pytest.raises(LooporaError, match="unknown bundle"):
        service.get_bundle(imported["id"])


def test_bundle_delete_logs_noncritical_managed_dir_cleanup_failure(
    service_factory,
    sample_workdir: Path,
    monkeypatch,
    caplog,
) -> None:
    service = service_factory(scenario="success")
    configure_logging()
    imported = service.import_bundle_text(_bundle_yaml(sample_workdir))
    original_rmtree = cleanup_diagnostics.shutil.rmtree

    def fail_bundle_dir_rmtree(path: Path) -> None:
        if Path(path).name == imported["id"]:
            raise OSError("forced managed dir cleanup failure")
        original_rmtree(path)

    monkeypatch.setattr(cleanup_diagnostics.shutil, "rmtree", fail_bundle_dir_rmtree)
    with caplog.at_level(logging.WARNING, logger="loopora.service_bundle_assets"):
        deleted = service.delete_bundle(imported["id"])

    assert deleted == {"id": imported["id"], "deleted": True}
    assert _has_cleanup_record(
        caplog,
        operation="bundle_managed_dir_delete",
        resource_type="path",
        owner_id=imported["id"],
    )


def test_bundle_failed_import_cleanup_logs_and_preserves_original_error(
    service_factory,
    sample_workdir: Path,
    monkeypatch,
    caplog,
) -> None:
    service = service_factory(scenario="success")
    configure_logging()
    original_create_role_definition = service.create_role_definition

    def fail_create_role_definition(*_args, **_kwargs):
        raise LooporaError("forced role import failure")

    def fail_rmtree(path: Path) -> None:
        raise OSError(f"cannot remove {Path(path).name}")

    service.create_role_definition = fail_create_role_definition
    monkeypatch.setattr(cleanup_diagnostics.shutil, "rmtree", fail_rmtree)

    with caplog.at_level(logging.WARNING, logger="loopora.service_bundle_assets"), pytest.raises(LooporaError, match="forced role import failure"):
        service.import_bundle_text(_bundle_yaml(sample_workdir))

    service.create_role_definition = original_create_role_definition
    assert _has_cleanup_record(caplog, operation="bundle_failed_import_cleanup", resource_type="path")


def test_bundle_failed_import_cleanup_diagnostic_failure_preserves_original_error(
    service_factory,
    sample_workdir: Path,
    monkeypatch,
) -> None:
    service = service_factory(scenario="success")
    original_create_role_definition = service.create_role_definition

    def fail_create_role_definition(*_args, **_kwargs):
        raise LooporaError("forced role import failure")

    def fail_rmtree(path: Path) -> None:
        raise OSError(f"cannot remove {Path(path).name}")

    def fail_log_event(*_args, **_kwargs) -> None:
        raise RuntimeError("cleanup log sink down")

    service.create_role_definition = fail_create_role_definition
    monkeypatch.setattr(cleanup_diagnostics.shutil, "rmtree", fail_rmtree)
    monkeypatch.setattr(cleanup_diagnostics, "log_event", fail_log_event)
    try:
        with pytest.raises(LooporaError, match="forced role import failure"):
            service.import_bundle_text(_bundle_yaml(sample_workdir))
    finally:
        service.create_role_definition = original_create_role_definition


def test_bundle_import_rollback_diagnostics_preserve_original_error_for_unexpected_cleanup_failure(
    service_factory,
    sample_workdir: Path,
    monkeypatch,
    caplog,
) -> None:
    service = service_factory(scenario="success")
    configure_logging()

    def fail_after_graph_creation(*_args, **_kwargs):
        raise LooporaError("forced import failure after graph creation")

    def fail_delete_loop(*_args, **_kwargs):
        raise RuntimeError("rollback loop deletion failed")

    monkeypatch.setattr(service, "derive_bundle_from_loop", fail_after_graph_creation)
    monkeypatch.setattr(service, "delete_loop", fail_delete_loop)

    with caplog.at_level(logging.WARNING, logger="loopora.service_bundle_assets"), pytest.raises(
        LooporaError,
        match="forced import failure after graph creation",
    ):
        service.import_bundle_text(_bundle_yaml(sample_workdir))

    assert _has_cleanup_record(caplog, operation="bundle_import_rollback", resource_type="loop")


def test_bundle_delete_keeps_managed_dir_and_records_when_graph_delete_fails(
    service_factory,
    sample_workdir: Path,
    monkeypatch,
) -> None:
    service = service_factory(scenario="success")
    imported = service.import_bundle_text(_bundle_yaml(sample_workdir))
    bundle_dir = service._bundle_dir(imported["id"])
    assert bundle_dir.exists()
    loop_id = imported["loop_id"]
    orchestration_id = imported["orchestration_id"]
    role_definition_ids = list(imported["role_definition_ids"])

    def fail_delete_bundle_graph(bundle_id: str) -> bool:
        if bundle_id == imported["id"]:
            raise LooporaError("bundle graph delete failed")
        return True

    monkeypatch.setattr(service.repository, "delete_bundle_graph", fail_delete_bundle_graph)
    with pytest.raises(LooporaError, match="bundle graph delete failed"):
        service.delete_bundle(imported["id"])

    assert bundle_dir.exists()
    assert service.repository.get_bundle(imported["id"]) is not None
    assert service.repository.get_loop(loop_id) is not None
    assert service.repository.get_orchestration(orchestration_id) is not None
    assert all(service.repository.get_role_definition(role_id) is not None for role_id in role_definition_ids)


def test_bundle_delete_refuses_unowned_linked_assets(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    imported = service.import_bundle_text(_bundle_yaml(sample_workdir))
    bundle_dir = service._bundle_dir(imported["id"])

    with service.repository.transaction() as connection:
        connection.execute(
            "DELETE FROM bundle_asset_ownership WHERE bundle_id = ? AND asset_type = 'loop'",
            (imported["id"],),
        )

    with pytest.raises(LooporaConflictError, match="asset is unowned"):
        service.delete_bundle(imported["id"])

    assert bundle_dir.exists()
    assert service.repository.get_bundle(imported["id"]) is not None
    assert service.repository.get_loop(imported["loop_id"]) is not None


@pytest.mark.parametrize(
    ("asset_kind", "table_name", "expected_error"),
    [
        ("loop", "loop_definitions", "linked loop"),
        ("orchestration", "orchestration_definitions", "linked orchestration"),
        ("role_definition", "role_definitions", "linked role definitions"),
    ],
)
def test_bundle_delete_refuses_missing_linked_assets(
    service_factory,
    sample_workdir: Path,
    asset_kind: str,
    table_name: str,
    expected_error: str,
) -> None:
    service = service_factory(scenario="success")
    imported = service.import_bundle_text(_bundle_yaml(sample_workdir))
    bundle_dir = service._bundle_dir(imported["id"])
    asset_id = (
        imported["role_definition_ids"][0]
        if asset_kind == "role_definition"
        else imported[f"{asset_kind}_id"]
    )

    with service.repository.transaction() as connection:
        connection.execute(f"DELETE FROM {table_name} WHERE id = ?", (asset_id,))

    with pytest.raises(LooporaConflictError, match=expected_error):
        service.delete_bundle(imported["id"])

    assert bundle_dir.exists()
    assert service.repository.get_bundle(imported["id"]) is not None


def test_bundle_delete_refuses_active_linked_runs(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    imported = service.import_bundle_text(_bundle_yaml(sample_workdir))
    bundle_dir = service._bundle_dir(imported["id"])
    run = service.start_run(imported["loop_id"])

    with pytest.raises(LooporaConflictError, match="active loop runs"):
        service.delete_bundle(imported["id"])

    assert bundle_dir.exists()
    assert service.repository.get_bundle(imported["id"]) is not None
    assert service.repository.get_run(run["id"])["status"] == "queued"


def test_bundle_delete_refuses_orchestration_referenced_by_external_loop(
    service_factory,
    sample_workdir: Path,
    sample_spec_file: Path,
) -> None:
    service = service_factory(scenario="success")
    imported = service.import_bundle_text(_bundle_yaml(sample_workdir))
    external_workdir = sample_workdir.parent / "external-loop-workdir"
    external_workdir.mkdir()
    external_loop = service.create_loop(
        name="External Loop",
        spec_path=sample_spec_file,
        workdir=external_workdir,
        model="gpt-5.4",
        reasoning_effort="medium",
        max_iters=3,
        max_role_retries=1,
        delta_threshold=0.005,
        trigger_window=2,
        regression_window=2,
        orchestration_id=imported["orchestration_id"],
    )

    with pytest.raises(LooporaConflictError, match="referenced by loops"):
        service.delete_bundle(imported["id"])

    assert service.repository.get_bundle(imported["id"]) is not None
    assert service.repository.get_loop(external_loop["id"]) is not None


def test_bundle_delete_refuses_role_definitions_referenced_by_external_orchestration(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    imported = service.import_bundle_text(_bundle_yaml(sample_workdir))
    role_definition_id = imported["role_definition_ids"][0]
    external_orchestration = service.create_orchestration(
        name="External Role Consumer",
        workflow={
            "preset": "custom",
            "roles": [{"id": "external_builder", "role_definition_id": role_definition_id}],
            "steps": [{"id": "external_step", "role_id": "external_builder"}],
        },
    )

    with pytest.raises(LooporaConflictError, match="shared role definitions"):
        service.delete_bundle(imported["id"])

    assert service.repository.get_bundle(imported["id"]) is not None
    assert service.repository.get_orchestration(external_orchestration["id"]) is not None


def test_bundle_replace_updates_plan_without_advancing_revision(service_factory, sample_workdir: Path) -> None:
    service = service_factory(scenario="success")
    imported = service.import_bundle_text(_bundle_yaml(sample_workdir))

    revised = service.import_bundle_text(
        _bundle_yaml(
            sample_workdir,
            collaboration_summary="Prefer maintainability over shallow pass signals.",
        ),
        replace_bundle_id=imported["id"],
    )

    assert revised["id"] == imported["id"]
    assert revised["revision"] == imported["revision"]
    assert revised["source_bundle_id"] == ""
    exported = service.export_bundle(revised["id"])
    assert exported["collaboration_summary"].startswith("Prefer maintainability")


def test_bundle_governance_cards_project_contract_controls(service_factory, sample_workdir: Path) -> None:
    service = service_factory(scenario="success")
    imported = service.import_bundle_text(_bundle_yaml(sample_workdir))

    card = next(item for item in service.list_bundle_governance_cards() if item["id"] == imported["id"])
    governance = card["governance_summary"]

    assert governance["failure_modes"]
    assert governance["evidence_style"]
    assert governance["workflow_step_count"] == 3
    assert governance["workflow_shape"]
    assert governance["gatekeeper"]["enabled"] is True
    assert governance["gatekeeper"]["strictness"] == "evidence_refs_required"


def test_legacy_bundle_lineage_metadata_imports_but_new_exports_omit_lineage(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    source = service.import_bundle_text(_bundle_yaml(sample_workdir))
    legacy_yaml = _bundle_yaml(
        sample_workdir,
        collaboration_summary="Prefer stronger evidence coverage before revising again.",
    ).replace(
        'metadata:\n  name: "Guided Inspect First"\n  description: "Bundle created from task-scoped alignment."',
        'metadata:\n'
        '  name: "Guided Inspect First Revision"\n'
        '  description: "Bundle revision with tighter evidence language."\n'
        f'  source_bundle_id: "{source["id"]}"\n'
        f'  revision: {source["revision"] + 1}',
    ).replace(
        "- The implementation stays maintainable for the next round.",
        "- The implementation stays maintainable for the next round.\n"
        "            - Evidence coverage is visible before another revision starts.",
    )
    imported = service.import_bundle_text(legacy_yaml)
    exported_yaml = bundle_to_yaml(service.export_bundle(imported["id"]))
    summary = service.get_bundle_revision_summary(imported["id"])

    assert imported["source_bundle_id"] == ""
    assert imported["revision"] == 1
    assert "source_bundle_id" not in exported_yaml
    assert "revision:" not in exported_yaml
    assert summary["lineage_state"] == "not_tracked"
    assert summary["source_bundle_id"] == ""
    assert summary["can_compare"] is False
    assert summary["surface_deltas"] == []


def test_failed_bundle_replace_preserves_existing_bundle(service_factory, sample_workdir: Path) -> None:
    service = service_factory(scenario="success")
    imported = service.import_bundle_text(_bundle_yaml(sample_workdir))
    original_loop_id = imported["loop_id"]
    original_orchestration_id = imported["orchestration_id"]
    original_role_ids = list(imported["role_definition_ids"])
    original_custom_role_count = len(
        [role for role in service.list_role_definitions() if role["source"] == "custom"]
    )
    original_custom_orchestration_count = len(
        [orchestration for orchestration in service.list_orchestrations() if orchestration["source"] == "custom"]
    )
    original_loop_count = len(service.list_loops())
    missing_workdir = sample_workdir.parent / "missing-workdir"

    with pytest.raises(LooporaError, match="workdir does not exist"):
        service.import_bundle_text(
            _bundle_yaml(
                missing_workdir,
                collaboration_summary="This replacement should not destroy the old bundle.",
            ),
            replace_bundle_id=imported["id"],
        )

    preserved = service.get_bundle(imported["id"])
    assert preserved["loop_id"] == original_loop_id
    assert preserved["orchestration_id"] == original_orchestration_id
    assert preserved["role_definition_ids"] == original_role_ids
    assert service.get_loop(original_loop_id)["id"] == original_loop_id
    assert service.get_orchestration(original_orchestration_id)["id"] == original_orchestration_id
    assert [role["id"] for role in preserved["role_definitions"]] == original_role_ids
    assert service.export_bundle(imported["id"])["collaboration_summary"].startswith("Prefer evidence")
    assert (
        len([role for role in service.list_role_definitions() if role["source"] == "custom"])
        == original_custom_role_count
    )
    assert (
        len(
            [
                orchestration
                for orchestration in service.list_orchestrations()
                if orchestration["source"] == "custom"
            ]
        )
        == original_custom_orchestration_count
    )
    assert len(service.list_loops()) == original_loop_count


def test_bundle_replace_rolls_back_when_graph_transaction_fails(service_factory, sample_workdir: Path) -> None:
    service = service_factory(scenario="success")
    imported = service.import_bundle_text(_bundle_yaml(sample_workdir))
    original_loop_id = imported["loop_id"]
    original_orchestration_id = imported["orchestration_id"]
    original_role_ids = list(imported["role_definition_ids"])
    original_custom_role_count = len(
        [role for role in service.list_role_definitions() if role["source"] == "custom"]
    )

    def fail_replace_bundle_graph(bundle_id: str, _payload: dict) -> bool:
        if bundle_id == imported["id"]:
            raise LooporaError("forced graph transaction failure")
        return True

    service.repository.replace_bundle_graph = fail_replace_bundle_graph
    with pytest.raises(LooporaError, match="forced graph transaction failure"):
        service.import_bundle_text(
            _bundle_yaml(
                sample_workdir,
                collaboration_summary="This replacement should roll back after save.",
            ),
            replace_bundle_id=imported["id"],
        )

    preserved = service.get_bundle(imported["id"])
    assert preserved["revision"] == imported["revision"]
    assert preserved["loop_id"] == original_loop_id
    assert preserved["orchestration_id"] == original_orchestration_id
    assert preserved["role_definition_ids"] == original_role_ids
    assert service.export_bundle(imported["id"])["collaboration_summary"].startswith("Prefer evidence")
    assert (
        len([role for role in service.list_role_definitions() if role["source"] == "custom"])
        == original_custom_role_count
    )


def test_bundle_owned_assets_cannot_be_deleted_individually(service_factory, sample_workdir: Path) -> None:
    service = service_factory(scenario="success")
    imported = service.import_bundle_text(_bundle_yaml(sample_workdir))
    role_definition = imported["role_definitions"][0]
    orchestration = imported["orchestration"]

    with pytest.raises(LooporaError, match=f"bundle {imported['id']}"):
        service.delete_loop(imported["loop_id"])
    with pytest.raises(LooporaError, match=f"bundle {imported['id']}"):
        service.delete_orchestration(orchestration["id"])
    with pytest.raises(LooporaError, match=f"bundle {imported['id']}"):
        service.delete_role_definition(role_definition["id"])


def test_imported_role_definition_changes_update_bundle_without_revision_bump(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    imported = service.import_bundle_text(_bundle_yaml(sample_workdir))
    role_definition = imported["role_definitions"][0]

    updated_role = service.update_role_definition(
        role_definition["id"],
        name=role_definition["name"],
        description=role_definition["description"],
        archetype=role_definition["archetype"],
        prompt_ref=role_definition["prompt_ref"],
        prompt_markdown=role_definition["prompt_markdown"],
        posture_notes="Raise the refactor bar before passing this work.",
        executor_kind=role_definition["executor_kind"],
        executor_mode=role_definition["executor_mode"],
        command_cli=role_definition["command_cli"],
        command_args_text=role_definition["command_args_text"],
        model=role_definition["model"],
        reasoning_effort=role_definition["reasoning_effort"],
    )

    refreshed = service.get_bundle(imported["id"])
    exported = service.export_bundle(imported["id"])
    exported_role = next(item for item in exported["role_definitions"] if item["name"] == updated_role["name"])

    assert updated_role["posture_notes"] == "Raise the refactor bar before passing this work."
    assert refreshed["revision"] == imported["revision"]
    assert "Raise the refactor bar" in exported_role["posture_notes"]


def test_imported_orchestration_changes_update_bundle_without_revision_bump(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    imported = service.import_bundle_text(_bundle_yaml(sample_workdir))
    orchestration = imported["orchestration"]
    workflow = dict(orchestration["workflow_json"])
    workflow["collaboration_intent"] = "Inspect first, then only ship maintainable changes."

    updated_orchestration = service.update_orchestration(
        orchestration["id"],
        name=orchestration["name"],
        description=orchestration["description"],
        workflow=workflow,
        prompt_files=orchestration["prompt_files_json"],
        role_models=orchestration.get("role_models_json"),
    )

    refreshed = service.get_bundle(imported["id"])
    exported = service.export_bundle(imported["id"])

    assert updated_orchestration["workflow_json"]["collaboration_intent"].startswith("Inspect first")
    assert refreshed["revision"] == imported["revision"]
    assert exported["workflow"]["collaboration_intent"].startswith("Inspect first")


def test_bundle_spec_edit_updates_runnable_loop_snapshot(service_factory, sample_workdir: Path) -> None:
    service = service_factory(scenario="success")
    imported = service.import_bundle_text(_bundle_yaml(sample_workdir))
    revised_spec = dedent(
        """\
        # Task

        Ship the requested behavior and explicitly remove nearby duplication.

        # Done When

        - The primary experience completes successfully.
        - The refactor-sensitive path is covered by reproducible evidence.

        # Guardrails

        - Keep changes focused.
        """
    )

    service.update_bundle_spec_markdown(imported["id"], revised_spec)

    loop = service.get_loop(imported["loop_id"])
    assert "explicitly remove nearby duplication" in loop["spec_markdown"]
    run = service.start_run(imported["loop_id"])
    assert "explicitly remove nearby duplication" in run["spec_markdown"]


def test_bundle_role_definition_edit_updates_runnable_loop_snapshot(service_factory, sample_workdir: Path) -> None:
    service = service_factory(scenario="success")
    imported = service.import_bundle_text(_bundle_yaml(sample_workdir))
    role_definition = next(role for role in imported["role_definitions"] if role["archetype"] == "builder")
    revised_prompt = role_definition["prompt_markdown"] + "\nRefuse shallow fixes that dodge refactoring evidence.\n"

    service.update_role_definition(
        role_definition["id"],
        name=role_definition["name"],
        description=role_definition["description"],
        archetype=role_definition["archetype"],
        prompt_ref=role_definition["prompt_ref"],
        prompt_markdown=revised_prompt,
        posture_notes="Raise the refactor bar before passing this work.",
        executor_kind=role_definition["executor_kind"],
        executor_mode=role_definition["executor_mode"],
        command_cli=role_definition["command_cli"],
        command_args_text=role_definition["command_args_text"],
        model=role_definition["model"],
        reasoning_effort=role_definition["reasoning_effort"],
    )

    loop = service.get_loop(imported["loop_id"])
    builder_role = next(role for role in loop["workflow_json"]["roles"] if role["role_definition_id"] == role_definition["id"])
    assert builder_role["posture_notes"] == "Raise the refactor bar before passing this work."
    assert "Refuse shallow fixes" in loop["prompt_files"][role_definition["prompt_ref"]]
    run = service.start_run(imported["loop_id"])
    assert "Refuse shallow fixes" in run["prompt_files"][role_definition["prompt_ref"]]


def test_bundle_orchestration_edit_updates_runnable_loop_snapshot(service_factory, sample_workdir: Path) -> None:
    service = service_factory(scenario="success")
    imported = service.import_bundle_text(_bundle_yaml(sample_workdir))
    orchestration = imported["orchestration"]
    workflow = dict(orchestration["workflow_json"])
    workflow["collaboration_intent"] = "Inspect refactor risk before allowing implementation to pass."

    service.update_orchestration(
        orchestration["id"],
        name=orchestration["name"],
        description=orchestration["description"],
        workflow=workflow,
        prompt_files=orchestration["prompt_files_json"],
        role_models=orchestration.get("role_models_json"),
    )

    loop = service.get_loop(imported["loop_id"])
    assert loop["workflow_json"]["collaboration_intent"].startswith("Inspect refactor risk")
    run = service.start_run(imported["loop_id"])
    assert run["workflow_json"]["collaboration_intent"].startswith("Inspect refactor risk")


def test_invalid_bundle_orchestration_edit_rolls_back_asset_and_bundle(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    imported = service.import_bundle_text(_bundle_yaml(sample_workdir))
    orchestration = imported["orchestration"]
    workflow = dict(orchestration["workflow_json"])
    workflow["steps"] = [dict(step) for step in workflow["steps"]]
    workflow["steps"][-1]["on_pass"] = "continue"

    with pytest.raises(LooporaError, match=r"action_policy\.can_finish_run=true requires on_pass=finish_run"):
        service.update_orchestration(
            orchestration["id"],
            name=orchestration["name"],
            description=orchestration["description"],
            workflow=workflow,
            prompt_files=orchestration["prompt_files_json"],
            role_models=orchestration.get("role_models_json"),
        )

    preserved_bundle = service.get_bundle(imported["id"])
    preserved_orchestration = service.get_orchestration(orchestration["id"])
    preserved_loop = service.get_loop(imported["loop_id"])
    assert preserved_bundle["revision"] == imported["revision"]
    assert preserved_orchestration["workflow_json"]["steps"][-1]["on_pass"] == "finish_run"
    assert preserved_loop["workflow_json"]["steps"][-1]["on_pass"] == "finish_run"


def test_bundle_orchestration_update_rollback_snapshot_failure_logs_and_preserves_original_error(
    service_factory,
    sample_workdir: Path,
    monkeypatch,
    caplog,
) -> None:
    service = service_factory(scenario="success")
    configure_logging()
    imported = service.import_bundle_text(_bundle_yaml(sample_workdir))
    orchestration = imported["orchestration"]
    workflow = dict(orchestration["workflow_json"])
    workflow["collaboration_intent"] = "This edit should roll back after bundle touch fails."

    def fail_touch_bundle(orchestration_id: str):
        assert orchestration_id == orchestration["id"]
        raise LooporaError("forced orchestration bundle touch failure")

    def fail_snapshot_sync(bundle_id: str):
        assert bundle_id == imported["id"]
        raise RuntimeError("rollback snapshot sync failed")

    monkeypatch.setattr(service, "_touch_bundle_for_orchestration", fail_touch_bundle)
    monkeypatch.setattr(service, "_sync_bundle_loop_snapshot", fail_snapshot_sync)

    with caplog.at_level(logging.WARNING, logger="loopora.service_bundle_assets"), pytest.raises(
        LooporaError,
        match="forced orchestration bundle touch failure",
    ):
        service.update_orchestration(
            orchestration["id"],
            name=orchestration["name"],
            description=orchestration["description"],
            workflow=workflow,
            prompt_files=orchestration["prompt_files_json"],
            role_models=orchestration.get("role_models_json"),
        )

    preserved_orchestration = service.get_orchestration(orchestration["id"])
    assert preserved_orchestration["workflow_json"]["collaboration_intent"] == orchestration["workflow_json"]["collaboration_intent"]
    assert _has_cleanup_record(
        caplog,
        operation="bundle_asset_update_rollback",
        resource_type="loop",
        owner_id=imported["id"],
    )


def test_bundle_role_update_rollback_snapshot_failure_logs_and_preserves_original_error(
    service_factory,
    sample_workdir: Path,
    monkeypatch,
    caplog,
) -> None:
    service = service_factory(scenario="success")
    configure_logging()
    imported = service.import_bundle_text(_bundle_yaml(sample_workdir))
    role_definition = next(role for role in imported["role_definitions"] if role["archetype"] == "builder")

    def fail_touch_bundle(role_definition_id: str):
        assert role_definition_id == role_definition["id"]
        raise LooporaError("forced role bundle touch failure")

    def fail_snapshot_sync(bundle_id: str):
        assert bundle_id == imported["id"]
        raise RuntimeError("rollback snapshot sync failed")

    monkeypatch.setattr(service, "_touch_bundle_for_role_definition", fail_touch_bundle)
    monkeypatch.setattr(service, "_sync_bundle_loop_snapshot", fail_snapshot_sync)

    with caplog.at_level(logging.WARNING, logger="loopora.service_bundle_assets"), pytest.raises(LooporaError, match="forced role bundle touch failure"):
        service.update_role_definition(
            role_definition["id"],
            name=role_definition["name"],
            description=role_definition["description"],
            archetype=role_definition["archetype"],
            prompt_ref=role_definition["prompt_ref"],
            prompt_markdown=role_definition["prompt_markdown"] + "\nThis edit should roll back.\n",
            posture_notes="This posture should roll back.",
            executor_kind=role_definition["executor_kind"],
            executor_mode=role_definition["executor_mode"],
            command_cli=role_definition["command_cli"],
            command_args_text=role_definition["command_args_text"],
            model=role_definition["model"],
            reasoning_effort=role_definition["reasoning_effort"],
        )

    preserved_role = service.get_role_definition(role_definition["id"])
    assert preserved_role["prompt_markdown"] == role_definition["prompt_markdown"]
    assert preserved_role["posture_notes"] == role_definition["posture_notes"]
    assert _has_cleanup_record(
        caplog,
        operation="bundle_asset_update_rollback",
        resource_type="loop",
        owner_id=imported["id"],
    )


def test_derive_bundle_uses_saved_loop_spec_snapshot(
    service_factory,
    sample_spec_file: Path,
    sample_spec_text: str,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = service.create_loop(
        name="Manual Loop",
        spec_path=sample_spec_file,
        workdir=sample_workdir,
        model="gpt-5.4",
        reasoning_effort="medium",
        max_iters=3,
        max_role_retries=1,
        delta_threshold=0.005,
        trigger_window=2,
        regression_window=2,
        orchestration_id="builtin:build_first",
    )
    sample_spec_file.write_text(
        "# Task\n\nThis external source file changed after loop creation.\n",
        encoding="utf-8",
    )

    derived = service.derive_bundle_from_loop(loop["id"], name="Derived From Saved Snapshot")

    assert derived["spec"]["markdown"] == sample_spec_text.strip()


def test_derive_bundle_keeps_role_definition_keys_consistent(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = service.create_loop(
        name="Parallel Review Loop",
        spec_path=sample_spec_file,
        workdir=sample_workdir,
        model="gpt-5.4",
        reasoning_effort="medium",
        max_iters=3,
        max_role_retries=1,
        delta_threshold=0.005,
        trigger_window=2,
        regression_window=2,
        orchestration_id="builtin:build_then_parallel_review",
    )

    derived = service.derive_bundle_from_loop(loop["id"], name="Derived Parallel Review")

    role_definition_keys = {role["key"] for role in derived["role_definitions"]}
    workflow_keys = {role["role_definition_key"] for role in derived["workflow"]["roles"]}
    assert workflow_keys <= role_definition_keys
    assert "contract-inspector" in role_definition_keys
    assert "evidence-inspector" in role_definition_keys


def test_derive_bundle_uses_saved_loop_workflow_and_prompt_snapshot(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    builder_prompt = dedent(
        """\
        ---
        version: 1
        archetype: builder
        ---

        Original builder prompt.
        """
    )
    gatekeeper_prompt = dedent(
        """\
        ---
        version: 1
        archetype: gatekeeper
        ---

        Original gatekeeper prompt.
        """
    )
    builder = service.create_role_definition(
        name="Manual Builder",
        description="Original builder role.",
        archetype="builder",
        prompt_markdown=builder_prompt,
    )
    gatekeeper = service.create_role_definition(
        name="Manual GateKeeper",
        description="Original gatekeeper role.",
        archetype="gatekeeper",
        prompt_markdown=gatekeeper_prompt,
    )
    orchestration = service.create_orchestration(
        name="Manual Flow",
        workflow={
            "version": 1,
            "collaboration_intent": "Original collaboration intent.",
            "roles": [
                {"id": "builder", "role_definition_id": builder["id"]},
                {"id": "gatekeeper", "role_definition_id": gatekeeper["id"]},
            ],
            "steps": [
                {"id": "build", "role_id": "builder"},
                {"id": "gate", "role_id": "gatekeeper", "on_pass": "finish_run"},
            ],
        },
    )
    loop = service.create_loop(
        name="Manual Loop",
        spec_path=sample_spec_file,
        workdir=sample_workdir,
        model="gpt-5.4",
        reasoning_effort="medium",
        max_iters=3,
        max_role_retries=1,
        delta_threshold=0.005,
        trigger_window=2,
        regression_window=2,
        orchestration_id=orchestration["id"],
    )
    changed_workflow = dict(orchestration["workflow_json"])
    changed_workflow["collaboration_intent"] = "Changed live orchestration intent."
    service.update_orchestration(
        orchestration["id"],
        name=orchestration["name"],
        description=orchestration["description"],
        workflow=changed_workflow,
        prompt_files=orchestration["prompt_files_json"],
    )
    service.update_role_definition(
        builder["id"],
        name=builder["name"],
        description=builder["description"],
        archetype=builder["archetype"],
        prompt_ref=builder["prompt_ref"],
        prompt_markdown=builder_prompt.replace("Original", "Changed live"),
        posture_notes=builder["posture_notes"],
        executor_kind=builder["executor_kind"],
        executor_mode=builder["executor_mode"],
        command_cli=builder["command_cli"],
        command_args_text=builder["command_args_text"],
        model=builder["model"],
        reasoning_effort=builder["reasoning_effort"],
    )

    derived = service.derive_bundle_from_loop(loop["id"], name="Derived From Saved Snapshot")
    derived_builder = next(role for role in derived["role_definitions"] if role["key"] == "builder")

    assert derived["workflow"]["collaboration_intent"] == "Original collaboration intent."
    assert "Original builder prompt." in derived_builder["prompt_markdown"]
    assert "Changed live" not in derived_builder["prompt_markdown"]
