from __future__ import annotations

from pathlib import Path

import pytest

from loopora.asset_catalog import WorkflowAssetCatalog
from loopora.db import LooporaRepository


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

    builtin_role = next(item for item in role_definitions if item["id"] == "builtin:builder")
    custom_role = next(item for item in role_definitions if item["id"] == role_definition["id"])
    builtin_orchestration = next(item for item in orchestrations if item["id"] == "builtin:build_first")
    custom_orchestration = next(item for item in orchestrations if item["id"] == orchestration["id"])

    assert builtin_role["source"] == "builtin"
    assert builtin_role["editable"] is False
    assert builtin_role["deletable"] is False
    assert custom_role["source"] == "custom"
    assert custom_role["editable"] is True
    assert custom_role["deletable"] is True
    assert custom_role["executor_kind"] == "claude"

    assert builtin_orchestration["source"] == "builtin"
    assert builtin_orchestration["workflow_json"]["preset"] == "build_first"
    assert custom_orchestration["source"] == "custom"
    assert custom_orchestration["workflow_json"]["preset"] == "inspect_first"
    assert isinstance(custom_orchestration["workflow_warnings"], list)


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
