from __future__ import annotations

import pytest

from loopora.workflows import (
    WorkflowError,
    build_preset_workflow,
    default_role_execution_settings,
    normalize_workflow,
    resolve_prompt_files,
    workflow_warnings,
)


def test_normalize_workflow_rejects_duplicate_step_ids() -> None:
    with pytest.raises(WorkflowError, match="duplicate workflow step id: shared_step"):
        normalize_workflow(
            {
                "version": 1,
                "roles": [
                    {"id": "builder", "archetype": "builder", "prompt_ref": "builder.md"},
                    {"id": "gatekeeper", "archetype": "gatekeeper", "prompt_ref": "gatekeeper.md"},
                ],
                "steps": [
                    {"id": "shared_step", "role_id": "builder"},
                    {"id": "shared_step", "role_id": "gatekeeper", "on_pass": "finish_run"},
                ],
            }
        )


def test_normalize_workflow_parses_boolean_like_step_session_flags() -> None:
    workflow = normalize_workflow(
        {
            "version": 1,
            "roles": [
                {"id": "builder", "archetype": "builder", "prompt_ref": "builder.md"},
                {"id": "inspector", "archetype": "inspector", "prompt_ref": "inspector.md"},
            ],
            "steps": [
                {"id": "builder_step", "role_id": "builder", "inherit_session": "false"},
                {"id": "inspector_step", "role_id": "inspector", "inherit_session": "true"},
            ],
        }
    )

    assert workflow["steps"][0]["inherit_session"] is False
    assert workflow["steps"][1]["inherit_session"] is True


def test_normalize_workflow_materializes_execution_defaults_when_role_only_overrides_model() -> None:
    workflow = normalize_workflow(
        {
            "version": 1,
            "roles": [
                {"id": "builder", "archetype": "builder", "prompt_ref": "builder.md", "model": "gpt-5.4-mini"},
            ],
            "steps": [
                {"id": "builder_step", "role_id": "builder"},
            ],
        }
    )

    builder = workflow["roles"][0]
    defaults = default_role_execution_settings()

    assert builder["model"] == "gpt-5.4-mini"
    assert builder["executor_kind"] == defaults["executor_kind"]
    assert builder["executor_mode"] == defaults["executor_mode"]
    assert builder["command_cli"] == defaults["command_cli"]
    assert builder["reasoning_effort"] == defaults["reasoning_effort"]


def test_normalize_workflow_rejects_finish_run_for_non_gatekeeper_steps() -> None:
    with pytest.raises(WorkflowError, match="non-gatekeeper steps only support on_pass=continue"):
        normalize_workflow(
            {
                "version": 1,
                "roles": [
                    {"id": "builder", "archetype": "builder", "prompt_ref": "builder.md"},
                ],
                "steps": [
                    {"id": "builder_step", "role_id": "builder", "on_pass": "finish_run"},
                ],
            }
        )


def test_normalize_workflow_rejects_invalid_gatekeeper_on_pass_values() -> None:
    with pytest.raises(WorkflowError, match="gatekeeper step on_pass must be continue or finish_run"):
        normalize_workflow(
            {
                "version": 1,
                "roles": [
                    {"id": "gatekeeper", "archetype": "gatekeeper", "prompt_ref": "gatekeeper.md"},
                ],
                "steps": [
                    {"id": "gatekeeper_step", "role_id": "gatekeeper", "on_pass": "halt"},
                ],
            }
        )


def test_normalize_workflow_rejects_invalid_step_session_flag_values() -> None:
    with pytest.raises(WorkflowError, match="workflow step inherit_session must be a boolean"):
        normalize_workflow(
            {
                "version": 1,
                "roles": [
                    {"id": "builder", "archetype": "builder", "prompt_ref": "builder.md"},
                ],
                "steps": [
                    {"id": "builder_step", "role_id": "builder", "inherit_session": "sometimes"},
                ],
            }
        )


def test_normalize_workflow_rejects_unsafe_prompt_ref_paths() -> None:
    with pytest.raises(WorkflowError, match="prompt_ref must be a safe relative path"):
        normalize_workflow(
            {
                "version": 1,
                "roles": [
                    {"id": "builder", "archetype": "builder", "prompt_ref": "../escape.md"},
                ],
                "steps": [
                    {"id": "builder_step", "role_id": "builder"},
                ],
            }
        )


def test_workflow_warnings_cover_stale_and_prechange_gatekeeper_paths() -> None:
    benchmark_loop = build_preset_workflow("benchmark_loop")
    fast_lane = build_preset_workflow("fast_lane")

    assert workflow_warnings(benchmark_loop) == [
        "GateKeeper appears before a later Builder step, so it may only judge pre-change evidence."
    ]
    assert workflow_warnings(fast_lane) == [
        "GateKeeper appears after Builder without a later Inspector step, so it may judge stale evidence."
    ]


def test_resolve_prompt_files_drops_unused_entries() -> None:
    workflow = normalize_workflow(
        {
            "version": 1,
            "roles": [
                {"id": "builder", "archetype": "builder", "prompt_ref": "custom-builder.md"},
            ],
            "steps": [
                {"id": "builder_step", "role_id": "builder"},
            ],
        }
    )

    resolved = resolve_prompt_files(
        workflow,
        {
            "custom-builder.md": """---
version: 1
archetype: builder
---

Keep the builder prompt stable.
""",
            "unused.md": """---
version: 1
archetype: inspector
---

This prompt should be dropped.
""",
        },
    )

    assert resolved == {
        "custom-builder.md": """---
version: 1
archetype: builder
---

Keep the builder prompt stable.
""",
    }


def test_resolve_prompt_files_rejects_invalid_prompt_file_keys() -> None:
    workflow = normalize_workflow(
        {
            "version": 1,
            "roles": [
                {"id": "builder", "archetype": "builder", "prompt_ref": "builder.md"},
            ],
            "steps": [
                {"id": "builder_step", "role_id": "builder"},
            ],
        }
    )

    with pytest.raises(WorkflowError, match="prompt_ref must be a safe relative path"):
        resolve_prompt_files(
            workflow,
            {
                "../escape.md": """---
version: 1
archetype: builder
---

This key should be rejected instead of silently dropped.
""",
            },
        )


def test_resolve_prompt_files_rejects_shared_prompt_ref_with_mismatched_archetype() -> None:
    workflow = normalize_workflow(
        {
            "version": 1,
            "roles": [
                {"id": "builder", "archetype": "builder", "prompt_ref": "shared.md"},
                {"id": "inspector", "archetype": "inspector", "prompt_ref": "shared.md"},
            ],
            "steps": [
                {"id": "builder_step", "role_id": "builder"},
                {"id": "inspector_step", "role_id": "inspector"},
            ],
        }
    )

    with pytest.raises(
        WorkflowError,
        match="prompt archetype builder does not match expected archetype inspector",
    ):
        resolve_prompt_files(
            workflow,
            {
                "shared.md": """---
version: 1
archetype: builder
---

Keep the builder prompt stable.
""",
            },
        )
