from __future__ import annotations

import pytest

from loopora.workflows import (
    WorkflowError,
    build_preset_workflow,
    default_step_action_policy,
    default_role_execution_settings,
    normalize_workflow,
    preset_names,
    resolve_prompt_files,
    workflow_warnings,
    load_workflow_file,
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


def test_normalize_workflow_adds_default_step_action_policies() -> None:
    workflow = normalize_workflow(
        {
            "version": 1,
            "roles": [
                {"id": "builder", "archetype": "builder", "prompt_ref": "builder.md"},
                {"id": "inspector", "archetype": "inspector", "prompt_ref": "inspector.md"},
                {"id": "gatekeeper", "archetype": "gatekeeper", "prompt_ref": "gatekeeper.md"},
                {"id": "guide", "archetype": "guide", "prompt_ref": "guide.md"},
                {"id": "custom", "archetype": "custom", "prompt_ref": "custom.md"},
            ],
            "steps": [
                {"id": "builder_step", "role_id": "builder"},
                {"id": "inspector_step", "role_id": "inspector"},
                {"id": "gatekeeper_step", "role_id": "gatekeeper", "on_pass": "finish_run"},
                {"id": "guide_step", "role_id": "guide"},
                {"id": "custom_step", "role_id": "custom"},
            ],
        }
    )

    policies = {step["id"]: step["action_policy"] for step in workflow["steps"]}
    assert policies["builder_step"] == {
        "workspace": "workspace_write",
        "can_block": False,
        "can_finish_run": False,
    }
    assert policies["inspector_step"] == {
        "workspace": "read_only",
        "can_block": True,
        "can_finish_run": False,
    }
    assert policies["gatekeeper_step"] == {
        "workspace": "read_only",
        "can_block": True,
        "can_finish_run": True,
    }
    assert policies["guide_step"] == {
        "workspace": "read_only",
        "can_block": False,
        "can_finish_run": False,
    }
    assert policies["custom_step"] == {
        "workspace": "read_only",
        "can_block": False,
        "can_finish_run": False,
    }


def test_default_gatekeeper_action_policy_only_finishes_when_step_finishes_run() -> None:
    assert default_step_action_policy(archetype="gatekeeper", on_pass="continue") == {
        "workspace": "read_only",
        "can_block": True,
        "can_finish_run": False,
    }
    assert default_step_action_policy(archetype="gatekeeper", on_pass="finish_run")["can_finish_run"] is True


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


def test_visible_workflow_presets_are_curated_governance_shapes() -> None:
    assert preset_names() == [
        "build_then_parallel_review",
        "evidence_first",
        "benchmark_gate",
        "repair_loop",
    ]

    default_workflow = normalize_workflow(None)
    assert default_workflow["preset"] == "build_then_parallel_review"
    assert [step.get("parallel_group", "") for step in default_workflow["steps"]] == [
        "",
        "inspection_pack",
        "inspection_pack",
        "",
    ]
    assert default_workflow["steps"][-1]["inputs"]["handoffs_from"] == [
        "contract_inspection_step",
        "evidence_inspection_step",
    ]


def test_normalize_workflow_preserves_collaboration_intent() -> None:
    workflow = normalize_workflow(
        {
            "version": 1,
            "preset": "inspect_first",
            "collaboration_intent": "Start with evidence, then commit to one repair slice.",
            "roles": [
                {"id": "inspector", "archetype": "inspector", "prompt_ref": "inspector.md"},
                {"id": "builder", "archetype": "builder", "prompt_ref": "builder.md"},
            ],
            "steps": [
                {"id": "inspector_step", "role_id": "inspector"},
                {"id": "builder_step", "role_id": "builder"},
            ],
        }
    )

    assert workflow["collaboration_intent"] == "Start with evidence, then commit to one repair slice."


def test_normalize_workflow_preserves_parallel_group_and_step_inputs() -> None:
    workflow = normalize_workflow(
        {
            "version": 1,
            "roles": [
                {"id": "builder", "archetype": "builder", "prompt_ref": "builder.md"},
                {"id": "accessibility_inspector", "archetype": "inspector", "prompt_ref": "inspector.md"},
                {"id": "contract_inspector", "archetype": "inspector", "prompt_ref": "inspector.md"},
                {"id": "gatekeeper", "archetype": "gatekeeper", "prompt_ref": "gatekeeper.md"},
            ],
            "steps": [
                {"id": "builder_step", "role_id": "builder"},
                {
                    "id": "accessibility_step",
                    "role_id": "accessibility_inspector",
                    "parallel_group": "inspection_pack",
                    "inputs": {
                        "handoffs_from": ["builder_step"],
                        "evidence_query": {"archetypes": ["builder"], "limit": 12},
                        "iteration_memory": "summary_only",
                    },
                },
                {
                    "id": "contract_step",
                    "role_id": "contract_inspector",
                    "parallel_group": "inspection_pack",
                },
                {
                    "id": "gatekeeper_step",
                    "role_id": "gatekeeper",
                    "on_pass": "finish_run",
                    "inputs": {"handoffs_from": ["accessibility_step", "contract_step"]},
                },
            ],
        }
    )

    assert workflow["steps"][1]["parallel_group"] == "inspection_pack"
    assert workflow["steps"][1]["inputs"] == {
        "handoffs_from": ["builder_step"],
        "evidence_query": {"archetypes": ["builder"], "limit": 12},
        "iteration_memory": "summary_only",
    }
    assert workflow["steps"][2]["parallel_group"] == "inspection_pack"
    assert workflow["steps"][3]["inputs"] == {"handoffs_from": ["accessibility_step", "contract_step"]}


def test_normalize_workflow_preserves_control_triggers() -> None:
    workflow = normalize_workflow(
        {
            "version": 1,
            "roles": [
                {"id": "builder", "archetype": "builder", "prompt_ref": "builder.md"},
                {"id": "guide", "archetype": "guide", "prompt_ref": "guide.md"},
                {"id": "gatekeeper", "archetype": "gatekeeper", "prompt_ref": "gatekeeper.md"},
            ],
            "steps": [
                {"id": "builder_step", "role_id": "builder"},
                {"id": "gatekeeper_step", "role_id": "gatekeeper", "on_pass": "finish_run"},
            ],
            "controls": [
                {
                    "id": "stale_evidence_check",
                    "when": {"signal": "no_evidence_progress", "after": "20m"},
                    "call": {"role_id": "guide"},
                    "mode": "repair_guidance",
                    "max_fires_per_run": 1,
                }
            ],
        }
    )

    assert workflow["controls"] == [
        {
            "id": "stale_evidence_check",
            "when": {"signal": "no_evidence_progress", "after": "20m"},
            "call": {"role_id": "guide"},
            "mode": "repair_guidance",
            "max_fires_per_run": 1,
        }
    ]


def test_normalize_workflow_rejects_builder_control_targets() -> None:
    with pytest.raises(WorkflowError, match="controls may only call Inspector, Guide, or GateKeeper"):
        normalize_workflow(
            {
                "version": 1,
                "roles": [
                    {"id": "builder", "archetype": "builder", "prompt_ref": "builder.md"},
                    {"id": "gatekeeper", "archetype": "gatekeeper", "prompt_ref": "gatekeeper.md"},
                ],
                "steps": [
                    {"id": "builder_step", "role_id": "builder"},
                    {"id": "gatekeeper_step", "role_id": "gatekeeper", "on_pass": "finish_run"},
                ],
                "controls": [
                    {
                        "id": "bad_repair",
                        "when": {"signal": "step_failed", "after": "0s"},
                        "call": {"role_id": "builder"},
                    }
                ],
            }
        )


def test_normalize_workflow_rejects_unknown_control_signals() -> None:
    with pytest.raises(WorkflowError, match="when.signal"):
        normalize_workflow(
            {
                "version": 1,
                "roles": [
                    {"id": "guide", "archetype": "guide", "prompt_ref": "guide.md"},
                ],
                "steps": [
                    {"id": "guide_step", "role_id": "guide"},
                ],
                "controls": [
                    {
                        "id": "generic_timer",
                        "when": {"signal": "cron", "after": "20m"},
                        "call": {"role_id": "guide"},
                    }
                ],
            }
        )


def test_workflow_file_can_express_controls(tmp_path) -> None:
    workflow_file = tmp_path / "workflow.yml"
    workflow_file.write_text(
        """
        workflow:
          version: 1
          roles:
            - id: builder
              archetype: builder
              prompt_ref: builder.md
            - id: guide
              archetype: guide
              prompt_ref: guide.md
          steps:
            - id: builder_step
              role_id: builder
          controls:
            - id: stale_check
              when:
                signal: no_evidence_progress
                after: 20m
              call:
                role_id: guide
              mode: repair_guidance
        """,
        encoding="utf-8",
    )

    workflow, _prompt_files = load_workflow_file(workflow_file)
    normalized = normalize_workflow(workflow)

    assert normalized["controls"][0]["id"] == "stale_check"
    assert normalized["controls"][0]["mode"] == "repair_guidance"


def test_normalize_workflow_rejects_write_roles_inside_parallel_groups() -> None:
    with pytest.raises(WorkflowError, match="parallel_group steps must be read-only"):
        normalize_workflow(
            {
                "version": 1,
                "roles": [
                    {"id": "builder_a", "archetype": "builder", "prompt_ref": "builder.md"},
                    {"id": "builder_b", "archetype": "builder", "prompt_ref": "builder.md"},
                ],
                "steps": [
                    {"id": "builder_a_step", "role_id": "builder_a", "parallel_group": "builders"},
                    {"id": "builder_b_step", "role_id": "builder_b", "parallel_group": "builders"},
                ],
            }
        )


def test_normalize_workflow_rejects_non_builder_workspace_write() -> None:
    with pytest.raises(WorkflowError, match="only Builder steps may set action_policy.workspace=workspace_write"):
        normalize_workflow(
            {
                "version": 1,
                "roles": [
                    {"id": "inspector", "archetype": "inspector", "prompt_ref": "inspector.md"},
                ],
                "steps": [
                    {
                        "id": "inspector_step",
                        "role_id": "inspector",
                        "action_policy": {"workspace": "workspace_write"},
                    },
                ],
            }
        )


def test_normalize_workflow_rejects_non_gatekeeper_finish_permission() -> None:
    with pytest.raises(WorkflowError, match="only GateKeeper steps may set action_policy.can_finish_run=true"):
        normalize_workflow(
            {
                "version": 1,
                "roles": [
                    {"id": "builder", "archetype": "builder", "prompt_ref": "builder.md"},
                ],
                "steps": [
                    {
                        "id": "builder_step",
                        "role_id": "builder",
                        "action_policy": {
                            "workspace": "workspace_write",
                            "can_finish_run": True,
                        },
                    },
                ],
            }
        )


def test_normalize_workflow_rejects_parallel_finish_permissions() -> None:
    with pytest.raises(WorkflowError, match="parallel_group steps may not finish runs"):
        normalize_workflow(
            {
                "version": 1,
                "roles": [
                    {"id": "gatekeeper", "archetype": "gatekeeper", "prompt_ref": "gatekeeper.md"},
                    {"id": "inspector", "archetype": "inspector", "prompt_ref": "inspector.md"},
                ],
                "steps": [
                    {
                        "id": "gatekeeper_step",
                        "role_id": "gatekeeper",
                        "on_pass": "finish_run",
                        "parallel_group": "review_pack",
                    },
                    {"id": "inspector_step", "role_id": "inspector", "parallel_group": "review_pack"},
                ],
            }
        )


def test_normalize_workflow_requires_parallel_group_steps_to_be_contiguous() -> None:
    with pytest.raises(WorkflowError, match="parallel_group steps must be contiguous"):
        normalize_workflow(
            {
                "version": 1,
                "roles": [
                    {"id": "inspector_a", "archetype": "inspector", "prompt_ref": "inspector.md"},
                    {"id": "inspector_b", "archetype": "inspector", "prompt_ref": "inspector.md"},
                    {"id": "inspector_c", "archetype": "inspector", "prompt_ref": "inspector.md"},
                ],
                "steps": [
                    {"id": "a", "role_id": "inspector_a", "parallel_group": "pack"},
                    {"id": "b", "role_id": "inspector_b", "parallel_group": "other"},
                    {"id": "c", "role_id": "inspector_c", "parallel_group": "pack"},
                ],
            }
        )


def test_normalize_workflow_rejects_unknown_input_policy_keys() -> None:
    with pytest.raises(WorkflowError, match="workflow step inputs contains unknown keys"):
        normalize_workflow(
            {
                "version": 1,
                "roles": [
                    {"id": "inspector", "archetype": "inspector", "prompt_ref": "inspector.md"},
                ],
                "steps": [
                    {"id": "inspector_step", "role_id": "inspector", "inputs": {"hidden_context": True}},
                ],
            }
        )


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
