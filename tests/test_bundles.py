from __future__ import annotations

import json
import logging
from pathlib import Path
from textwrap import dedent

import pytest

from loopora.bundles import bundle_to_yaml
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
    assert summary["risks"]
    assert summary["evidence"]
    assert summary["gatekeeper"]["enabled"] is True
    assert summary["gatekeeper"]["requires_evidence_refs"] is True
    assert summary["workflow"]["step_count"] == 3
    assert summary["controls"][0]["signal"] == "gatekeeper_rejected"
    assert summary["controls"][0]["role_name"] == "Evidence Inspector"


def test_bundle_preview_rejects_spec_markdown_that_cannot_compile(service_factory, sample_workdir: Path) -> None:
    service = service_factory(scenario="success")
    invalid_yaml = _bundle_yaml(sample_workdir).replace("## Builder Notes", "Builder notes without a subheading")

    with pytest.raises(LooporaError, match="Role Notes"):
        service.preview_bundle_text(invalid_yaml)


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

    def fail_create_role_definition(*args, **kwargs):
        raise LooporaError("forced role import failure")

    def fail_rmtree(path: Path) -> None:
        raise OSError(f"cannot remove {Path(path).name}")

    service.create_role_definition = fail_create_role_definition
    monkeypatch.setattr(cleanup_diagnostics.shutil, "rmtree", fail_rmtree)

    with caplog.at_level(logging.WARNING, logger="loopora.service_bundle_assets"):
        with pytest.raises(LooporaError, match="forced role import failure"):
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

    def fail_create_role_definition(*args, **kwargs):
        raise LooporaError("forced role import failure")

    def fail_rmtree(path: Path) -> None:
        raise OSError(f"cannot remove {Path(path).name}")

    def fail_log_event(*args, **kwargs) -> None:
        raise RuntimeError("cleanup log sink down")

    service.create_role_definition = fail_create_role_definition
    monkeypatch.setattr(cleanup_diagnostics.shutil, "rmtree", fail_rmtree)
    monkeypatch.setattr(cleanup_diagnostics, "log_event", fail_log_event)
    try:
        with pytest.raises(LooporaError, match="forced role import failure"):
            service.import_bundle_text(_bundle_yaml(sample_workdir))
    finally:
        service.create_role_definition = original_create_role_definition


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

    def fail_replace_bundle_graph(bundle_id: str, payload: dict) -> bool:
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

    with pytest.raises(LooporaError, match="action_policy.can_finish_run=true requires on_pass=finish_run"):
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
