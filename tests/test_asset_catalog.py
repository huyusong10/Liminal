from __future__ import annotations

from pathlib import Path

import pytest

from loopora.asset_catalog import AssetCatalogNotFoundError, WorkflowAssetCatalog
from loopora.db import LooporaRepository
from loopora.workflows import WorkflowError, default_role_execution_settings


def _prompt_markdown(archetype: str, body: str) -> str:
    return f"""---
version: 1
archetype: {archetype}
---

{body}
"""


def test_asset_catalog_lists_builtin_and_custom_assets_with_stable_flags(tmp_path: Path) -> None:
    repository = LooporaRepository(tmp_path / "app.db")
    catalog = WorkflowAssetCatalog(repository)

    role_definition = catalog.create_role_definition(
        name="Release Builder",
        description="Ships focused release work.",
        archetype="builder",
        prompt_ref="release-builder.md",
        prompt_markdown=_prompt_markdown("builder", "Focus on release work."),
        executor_kind="claude",
        model="gpt-5.4-mini",
        reasoning_effort="high",
    )
    orchestration = catalog.create_orchestration(
        name="Custom Inspect First",
        description="Inspector before Builder.",
        workflow={"preset": "inspect_first"},
    )

    role_definitions = catalog.list_role_definitions()
    orchestrations = catalog.list_orchestrations()
    builtin_orchestrations = [item for item in orchestrations if item["source"] == "builtin"]

    builtin_role = next(item for item in role_definitions if item["id"] == "builtin:builder")
    custom_role = next(item for item in role_definitions if item["id"] == role_definition["id"])
    builtin_orchestration = next(item for item in orchestrations if item["id"] == "builtin:build_then_parallel_review")
    custom_orchestration = next(item for item in orchestrations if item["id"] == orchestration["id"])

    assert builtin_role["source"] == "builtin"
    assert builtin_role["editable"] is False
    assert builtin_role["deletable"] is False
    assert custom_role["source"] == "custom"
    assert custom_role["editable"] is True
    assert custom_role["deletable"] is True
    assert custom_role["executor_kind"] == "claude"

    assert builtin_orchestration["source"] == "builtin"
    assert builtin_orchestration["workflow_json"]["preset"] == "build_then_parallel_review"
    assert builtin_orchestration["workflow_json"]["steps"][0]["inherit_session"] is True
    assert builtin_orchestration["workflow_json"]["steps"][1]["inherit_session"] is False
    assert builtin_orchestration["workflow_json"]["steps"][0]["extra_cli_args"] == ""
    assert builtin_orchestration["scenario_zh"]
    assert builtin_orchestration["scenario_en"]
    for item in builtin_orchestrations:
        assert item["spec_practice_summary_zh"].startswith("场景：")
        assert item["spec_practice_summary_en"].startswith("Scenario:")
        assert "## 场景" in item["spec_practice_markdown_zh"]
        assert "## 需求" in item["spec_practice_markdown_zh"]
        assert "## 适合这个流程，因为" in item["spec_practice_markdown_zh"]
        assert "## 为什么不是其他流程" in item["spec_practice_markdown_zh"]
        assert "## 为什么不直接交给 AI Agent" in item["spec_practice_markdown_zh"]
        assert "## 示例 spec" in item["spec_practice_markdown_zh"]
        assert "## Scenario" in item["spec_practice_markdown_en"]
        assert "## Request" in item["spec_practice_markdown_en"]
        assert "## Why this workflow fits" in item["spec_practice_markdown_en"]
        assert "## Why not the other workflows" in item["spec_practice_markdown_en"]
        assert "## Why not just let an AI Agent do it" in item["spec_practice_markdown_en"]
        assert "## Example spec" in item["spec_practice_markdown_en"]
        assert "# Task" in item["spec_practice_markdown_zh"]
        assert "# Task" in item["spec_practice_markdown_en"]
        assert "# Role Notes" in item["spec_practice_markdown_zh"]
        assert "# Role Notes" in item["spec_practice_markdown_en"]
        assert "Builder Notes" in item["spec_practice_markdown_zh"]
        assert "Builder Notes" in item["spec_practice_markdown_en"]
        assert "GateKeeper Notes" in item["spec_practice_markdown_zh"]
        assert "GateKeeper Notes" in item["spec_practice_markdown_en"]
    assert len(builtin_orchestrations) == 4
    assert any(item["id"] == "builtin:evidence_first" for item in builtin_orchestrations)
    assert any(item["id"] == "builtin:benchmark_gate" for item in builtin_orchestrations)
    assert all(item["id"] != "builtin:fast_lane" for item in builtin_orchestrations)
    assert all(item["id"] != "builtin:quality_gate" for item in builtin_orchestrations)
    assert all(item["id"] != "builtin:build_first" for item in builtin_orchestrations)
    assert custom_orchestration["source"] == "custom"
    assert custom_orchestration["workflow_json"]["preset"] == "inspect_first"
    assert isinstance(custom_orchestration["workflow_warnings"], list)

    hidden_fast_lane = catalog.get_orchestration("builtin:fast_lane")
    hidden_quality_gate = catalog.get_orchestration("builtin:quality_gate")
    hidden_build_first = catalog.get_orchestration("builtin:build_first")
    assert hidden_fast_lane["name"] == "Fast Lane"
    assert hidden_fast_lane["workflow_json"]["preset"] == "fast_lane"
    assert hidden_quality_gate["name"] == "Quality Gate"
    assert hidden_quality_gate["workflow_json"]["preset"] == "quality_gate"
    assert hidden_build_first["name"] == "Build First"
    assert hidden_build_first["workflow_json"]["preset"] == "build_first"


def test_asset_catalog_resolves_builtin_orchestration_input_and_applies_role_overrides(tmp_path: Path) -> None:
    repository = LooporaRepository(tmp_path / "app.db")
    catalog = WorkflowAssetCatalog(repository)

    resolved = catalog.resolve_orchestration_input(
        orchestration_id="builtin:inspect_first",
        workflow=None,
        prompt_files=None,
        role_models={"builder": "gpt-5.4-mini"},
    )

    builder_role = next(role for role in resolved["workflow"]["roles"] if role["id"] == "builder")

    assert resolved["id"] == "builtin:inspect_first"
    assert resolved["name"] == "Inspect First"
    assert resolved["workflow"]["preset"] == "inspect_first"
    assert builder_role["model"] == "gpt-5.4-mini"
    assert "builder.md" in resolved["prompt_files"]


def test_asset_catalog_persists_role_execution_defaults_for_model_only_snapshots(tmp_path: Path) -> None:
    repository = LooporaRepository(tmp_path / "app.db")
    catalog = WorkflowAssetCatalog(repository)

    orchestration = catalog.create_orchestration(
        name="Model Override Workflow",
        description="Carries role-level model overrides.",
        workflow={
            "version": 1,
            "roles": [
                {"id": "builder", "archetype": "builder", "prompt_ref": "builder.md", "model": "gpt-5.4-mini"},
            ],
            "steps": [
                {"id": "builder_step", "role_id": "builder"},
            ],
        },
    )

    builder_role = orchestration["workflow_json"]["roles"][0]
    defaults = default_role_execution_settings()

    assert builder_role["model"] == "gpt-5.4-mini"
    assert builder_role["executor_kind"] == defaults["executor_kind"]
    assert builder_role["executor_mode"] == defaults["executor_mode"]
    assert builder_role["command_cli"] == defaults["command_cli"]
    assert builder_role["reasoning_effort"] == defaults["reasoning_effort"]


def test_asset_catalog_hydrates_role_snapshots_from_role_definition_id(tmp_path: Path) -> None:
    repository = LooporaRepository(tmp_path / "app.db")
    catalog = WorkflowAssetCatalog(repository)
    role_definition = catalog.create_role_definition(
        name="Release Builder",
        description="Ships focused release work.",
        archetype="builder",
        prompt_ref="release-builder.md",
        prompt_markdown=_prompt_markdown("builder", "Focus on safe release work."),
        executor_kind="claude",
        model="gpt-5.4-mini",
        reasoning_effort="high",
    )

    resolved = catalog.resolve_orchestration_input(
        orchestration_id=None,
        workflow={
            "version": 1,
            "roles": [
                {"id": "builder", "role_definition_id": role_definition["id"]},
            ],
            "steps": [
                {"id": "builder_step", "role_id": "builder"},
            ],
        },
        prompt_files=None,
        role_models=None,
    )

    builder_role = resolved["workflow"]["roles"][0]
    assert builder_role["name"] == "Release Builder"
    assert builder_role["archetype"] == "builder"
    assert builder_role["prompt_ref"] == "release-builder.md"
    assert builder_role["executor_kind"] == "claude"
    assert builder_role["model"] == "gpt-5.4-mini"
    assert builder_role["reasoning_effort"] == "high"
    assert resolved["prompt_files"]["release-builder.md"].startswith("---\nversion: 1")


def test_asset_catalog_hydrates_role_posture_notes_from_role_definition_id(tmp_path: Path) -> None:
    repository = LooporaRepository(tmp_path / "app.db")
    catalog = WorkflowAssetCatalog(repository)
    role_definition = catalog.create_role_definition(
        name="Focused Builder",
        description="Ships focused release work.",
        archetype="builder",
        prompt_ref="focused-builder.md",
        prompt_markdown=_prompt_markdown("builder", "Focus on safe release work."),
        posture_notes="Treat maintainability debt as first-class in this task.",
    )

    resolved = catalog.resolve_orchestration_input(
        orchestration_id=None,
        workflow={
            "version": 1,
            "roles": [
                {"id": "builder", "role_definition_id": role_definition["id"]},
            ],
            "steps": [
                {"id": "builder_step", "role_id": "builder"},
            ],
        },
        prompt_files=None,
        role_models=None,
    )

    assert resolved["workflow"]["roles"][0]["posture_notes"] == "Treat maintainability debt as first-class in this task."


def test_asset_catalog_allows_task_scoped_posture_notes_with_role_definition_id(tmp_path: Path) -> None:
    repository = LooporaRepository(tmp_path / "app.db")
    catalog = WorkflowAssetCatalog(repository)
    role_definition = catalog.create_role_definition(
        name="Focused Builder",
        description="Ships focused release work.",
        archetype="builder",
        prompt_ref="focused-builder.md",
        prompt_markdown=_prompt_markdown("builder", "Focus on safe release work."),
        posture_notes="Treat maintainability debt as first-class in this task.",
    )

    resolved = catalog.resolve_orchestration_input(
        orchestration_id=None,
        workflow={
            "version": 1,
            "roles": [
                {
                    "id": "builder",
                    "role_definition_id": role_definition["id"],
                    "posture_notes": "Create an inspectable handoff for two reviewers.",
                },
            ],
            "steps": [
                {"id": "builder_step", "role_id": "builder"},
            ],
        },
        prompt_files=None,
        role_models=None,
    )

    assert resolved["workflow"]["roles"][0]["posture_notes"] == "Create an inspectable handoff for two reviewers."


def test_asset_catalog_allows_workflow_role_label_with_role_definition_id(tmp_path: Path) -> None:
    repository = LooporaRepository(tmp_path / "app.db")
    catalog = WorkflowAssetCatalog(repository)
    role_definition = catalog.create_role_definition(
        name="Generic Inspector",
        description="Checks evidence.",
        archetype="inspector",
        prompt_ref="generic-inspector.md",
        prompt_markdown=_prompt_markdown("inspector", "Inspect the result."),
    )

    resolved = catalog.resolve_orchestration_input(
        orchestration_id=None,
        workflow={
            "version": 1,
            "roles": [
                {
                    "id": "contract_inspector",
                    "name": "Contract Inspector",
                    "role_definition_id": role_definition["id"],
                },
            ],
            "steps": [
                {"id": "contract_inspection_step", "role_id": "contract_inspector"},
            ],
        },
        prompt_files=None,
        role_models=None,
    )

    assert resolved["workflow"]["roles"][0]["name"] == "Contract Inspector"
    assert resolved["workflow"]["roles"][0]["archetype"] == "inspector"


def test_asset_catalog_rejects_unknown_role_definition_ids_in_workflow(tmp_path: Path) -> None:
    repository = LooporaRepository(tmp_path / "app.db")
    catalog = WorkflowAssetCatalog(repository)

    with pytest.raises(AssetCatalogNotFoundError, match="unknown role definition: role_missing"):
        catalog.resolve_orchestration_input(
            orchestration_id=None,
            workflow={
                "version": 1,
                "roles": [
                    {"id": "builder", "role_definition_id": "role_missing"},
                ],
                "steps": [
                    {"id": "builder_step", "role_id": "builder"},
                ],
            },
            prompt_files=None,
            role_models=None,
        )


def test_asset_catalog_rejects_conflicting_role_snapshot_fields_for_role_definition_id(tmp_path: Path) -> None:
    repository = LooporaRepository(tmp_path / "app.db")
    catalog = WorkflowAssetCatalog(repository)
    role_definition = catalog.create_role_definition(
        name="Release Builder",
        description="Ships focused release work.",
        archetype="builder",
        prompt_ref="release-builder.md",
        prompt_markdown=_prompt_markdown("builder", "Focus on safe release work."),
        executor_kind="claude",
        model="gpt-5.4-mini",
        reasoning_effort="high",
    )

    with pytest.raises(
        WorkflowError,
        match=f"workflow role builder conflicts with role_definition_id {role_definition['id']} on model",
    ):
        catalog.resolve_orchestration_input(
            orchestration_id=None,
            workflow={
                "version": 1,
                "roles": [
                    {
                        "id": "builder",
                        "role_definition_id": role_definition["id"],
                        "model": "gpt-5.4",
                    },
                ],
                "steps": [
                    {"id": "builder_step", "role_id": "builder"},
                ],
            },
            prompt_files=None,
            role_models=None,
        )


def test_asset_catalog_rejects_conflicting_prompt_files_for_role_definition_id(tmp_path: Path) -> None:
    repository = LooporaRepository(tmp_path / "app.db")
    catalog = WorkflowAssetCatalog(repository)
    role_definition = catalog.create_role_definition(
        name="Release Builder",
        description="Ships focused release work.",
        archetype="builder",
        prompt_ref="release-builder.md",
        prompt_markdown=_prompt_markdown("builder", "Focus on safe release work."),
        executor_kind="claude",
        model="gpt-5.4-mini",
        reasoning_effort="high",
    )

    with pytest.raises(
        WorkflowError,
        match=f"workflow role builder conflicts with role_definition_id {role_definition['id']} on prompt_markdown",
    ):
        catalog.resolve_orchestration_input(
            orchestration_id=None,
            workflow={
                "version": 1,
                "roles": [
                    {
                        "id": "builder",
                        "role_definition_id": role_definition["id"],
                    },
                ],
                "steps": [
                    {"id": "builder_step", "role_id": "builder"},
                ],
            },
            prompt_files={
                "release-builder.md": _prompt_markdown("builder", "Focus on risky release work."),
            },
            role_models=None,
        )


def test_asset_catalog_update_preserves_existing_workflow_and_prompt_files_when_omitted(tmp_path: Path) -> None:
    repository = LooporaRepository(tmp_path / "app.db")
    catalog = WorkflowAssetCatalog(repository)
    orchestration = catalog.create_orchestration(
        name="Custom Builder Flow",
        description="Uses a custom builder prompt.",
        workflow={
            "version": 1,
            "roles": [
                {"id": "builder", "archetype": "builder", "prompt_ref": "custom-builder.md"},
            ],
            "steps": [
                {"id": "builder_step", "role_id": "builder"},
            ],
        },
        prompt_files={
            "custom-builder.md": _prompt_markdown("builder", "Keep the builder prompt stable."),
        },
    )

    updated = catalog.update_orchestration(
        orchestration["id"],
        name="Renamed Builder Flow",
        description="Updated description only.",
        workflow=None,
        prompt_files=None,
        role_models=None,
    )

    assert updated["name"] == "Renamed Builder Flow"
    assert updated["workflow_json"]["roles"][0]["prompt_ref"] == "custom-builder.md"
    assert updated["workflow_json"]["steps"][0]["id"] == "builder_step"
    assert updated["prompt_files_json"]["custom-builder.md"].startswith("---\nversion: 1")


def test_asset_catalog_update_prunes_prompt_files_not_used_by_current_workflow(tmp_path: Path) -> None:
    repository = LooporaRepository(tmp_path / "app.db")
    catalog = WorkflowAssetCatalog(repository)
    orchestration = catalog.create_orchestration(
        name="Custom Builder Flow",
        description="Uses a custom builder prompt.",
        workflow={
            "version": 1,
            "roles": [
                {"id": "builder", "archetype": "builder", "prompt_ref": "custom-builder.md"},
            ],
            "steps": [
                {"id": "builder_step", "role_id": "builder"},
            ],
        },
        prompt_files={
            "custom-builder.md": _prompt_markdown("builder", "Keep the builder prompt stable."),
        },
    )

    updated = catalog.update_orchestration(
        orchestration["id"],
        name="Builtin Builder Flow",
        description="Now uses the built-in builder prompt.",
        workflow={
            "version": 1,
            "roles": [
                {"id": "builder", "archetype": "builder", "prompt_ref": "builder.md"},
            ],
            "steps": [
                {"id": "builder_step", "role_id": "builder"},
            ],
        },
        prompt_files=None,
        role_models=None,
    )

    assert updated["workflow_json"]["roles"][0]["prompt_ref"] == "builder.md"
    assert list(updated["prompt_files_json"].keys()) == ["builder.md"]
    assert "custom-builder.md" not in updated["prompt_files_json"]


def test_asset_catalog_rejects_invalid_prompt_file_keys(tmp_path: Path) -> None:
    repository = LooporaRepository(tmp_path / "app.db")
    catalog = WorkflowAssetCatalog(repository)

    with pytest.raises(WorkflowError, match="prompt_ref must be a safe relative path"):
        catalog.create_orchestration(
            name="Unsafe Prompt Files",
            description="Should reject invalid prompt_files keys instead of ignoring them.",
            workflow={
                "version": 1,
                "roles": [
                    {"id": "builder", "archetype": "builder", "prompt_ref": "builder.md"},
                ],
                "steps": [
                    {"id": "builder_step", "role_id": "builder"},
                ],
            },
            prompt_files={
                "../escape.md": _prompt_markdown("builder", "This should never be silently dropped."),
            },
        )


def test_asset_catalog_sanitizes_invalid_persisted_prompt_file_keys(tmp_path: Path) -> None:
    repository = LooporaRepository(tmp_path / "app.db")
    repository.create_orchestration(
        {
            "id": "orch_legacy",
            "name": "Legacy Builder Flow",
            "description": "Contains stale invalid prompt file keys.",
            "workflow": {
                "version": 1,
                "roles": [
                    {"id": "builder", "archetype": "builder", "prompt_ref": "builder.md"},
                ],
                "steps": [
                    {"id": "builder_step", "role_id": "builder"},
                ],
            },
            "prompt_files": {
                "../escape.md": _prompt_markdown("builder", "Legacy invalid key."),
                "builder.md": _prompt_markdown("builder", "Legit builder prompt."),
            },
        }
    )
    catalog = WorkflowAssetCatalog(repository)

    orchestration = catalog.get_orchestration("orch_legacy")
    resolved = catalog.resolve_orchestration_input(
        orchestration_id="orch_legacy",
        workflow=None,
        prompt_files=None,
        role_models=None,
    )

    assert list(orchestration["prompt_files_json"].keys()) == ["builder.md"]
    assert list(resolved["prompt_files"].keys()) == ["builder.md"]


def test_asset_catalog_role_definition_crud_normalizes_archetypes_and_protects_builtins(tmp_path: Path) -> None:
    repository = LooporaRepository(tmp_path / "app.db")
    catalog = WorkflowAssetCatalog(repository)

    created = catalog.create_role_definition(
        name="Legacy Generator",
        description="Uses the legacy alias on input.",
        archetype="generator",
        prompt_markdown=_prompt_markdown("builder", "Keep changes scoped."),
        executor_kind="codex",
        model="gpt-5.4-mini",
    )

    assert created["archetype"] == "builder"
    assert created["prompt_ref"].endswith(".md")
    original_prompt_ref = created["prompt_ref"]

    updated = catalog.update_role_definition(
        created["id"],
        name="Legacy Generator v2",
        description="Updated description.",
        archetype="builder",
        prompt_markdown=_prompt_markdown("builder", "Keep changes very scoped."),
        executor_kind="opencode",
        model="gpt-5.4",
        reasoning_effort="max",
    )
    assert updated["name"] == "Legacy Generator v2"
    assert updated["model"] == "gpt-5.4"
    assert updated["executor_kind"] == "opencode"
    assert updated["prompt_ref"] == original_prompt_ref

    with pytest.raises(ValueError, match="saved role definitions cannot change archetype"):
        catalog.update_role_definition(
            created["id"],
            name="Legacy Generator v3",
            description="Should fail.",
            archetype="inspector",
            prompt_markdown=_prompt_markdown("inspector", "Inspect instead of building."),
            executor_kind="codex",
            model="",
        )

    with pytest.raises(ValueError, match="saved role definitions cannot change prompt_ref"):
        catalog.update_role_definition(
            created["id"],
            name="Legacy Generator v4",
            description="Should fail.",
            archetype="builder",
            prompt_ref="renamed-builder.md",
            prompt_markdown=_prompt_markdown("builder", "Keep changes scoped."),
            executor_kind="codex",
            model="",
        )

    with pytest.raises(ValueError, match="built-in role definitions cannot be updated in place"):
        catalog.update_role_definition(
            "builtin:builder",
            name="Nope",
            description="",
            archetype="builder",
            prompt_markdown=_prompt_markdown("builder", "Should fail."),
            model="",
        )

    deleted = catalog.delete_role_definition(created["id"])
    assert deleted == {"id": created["id"], "deleted": True}


def test_asset_catalog_rejects_duplicate_role_definition_prompt_refs(tmp_path: Path) -> None:
    repository = LooporaRepository(tmp_path / "app.db")
    catalog = WorkflowAssetCatalog(repository)

    with pytest.raises(ValueError, match="prompt_ref already in use: builder.md"):
        catalog.create_role_definition(
            name="Custom Builder Alias",
            description="Should not shadow the built-in builder prompt ref.",
            archetype="builder",
            prompt_ref="builder.md",
            prompt_markdown=_prompt_markdown("builder", "Use a custom builder prompt."),
            executor_kind="codex",
            model="gpt-5.4-mini",
        )

    created = catalog.create_role_definition(
        name="Release Builder",
        description="Ships focused release work.",
        archetype="builder",
        prompt_ref="release-builder.md",
        prompt_markdown=_prompt_markdown("builder", "Focus on safe release work."),
        executor_kind="claude",
        model="gpt-5.4-mini",
    )

    with pytest.raises(ValueError, match="prompt_ref already in use: release-builder.md"):
        catalog.create_role_definition(
            name="Another Release Builder",
            description="Should not reuse the same prompt ref.",
            archetype="builder",
            prompt_ref="release-builder.md",
            prompt_markdown=_prompt_markdown("builder", "Use a different release strategy."),
            executor_kind="claude",
            model="gpt-5.4",
        )

    assert created["prompt_ref"] == "release-builder.md"


def test_asset_catalog_rejects_unsafe_role_definition_prompt_ref(tmp_path: Path) -> None:
    repository = LooporaRepository(tmp_path / "app.db")
    catalog = WorkflowAssetCatalog(repository)

    with pytest.raises(ValueError, match="prompt_ref must be a safe relative path"):
        catalog.create_role_definition(
            name="Escaping Builder",
            description="Should not write outside the prompt asset root.",
            archetype="builder",
            prompt_ref="../escape.md",
            prompt_markdown=_prompt_markdown("builder", "Keep prompt refs inside the asset root."),
            executor_kind="codex",
            model="gpt-5.4-mini",
        )


def test_asset_catalog_rejects_custom_executor_preset_mode(tmp_path: Path) -> None:
    repository = LooporaRepository(tmp_path / "app.db")
    catalog = WorkflowAssetCatalog(repository)

    with pytest.raises(ValueError, match="only supports command mode"):
        catalog.create_role_definition(
            name="Custom Wrapper",
            description="Uses a wrapper command.",
            archetype="custom",
            prompt_ref="custom-wrapper.md",
            prompt_markdown=_prompt_markdown("custom", "Observe and summarize."),
            executor_kind="custom",
            executor_mode="preset",
            command_cli="wrapper",
            command_args_text="--output\n{output_path}\n{prompt}\n",
        )
