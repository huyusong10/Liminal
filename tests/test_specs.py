from __future__ import annotations

import pytest

from loopora.specs import SpecError, compile_markdown_spec, render_spec_template, resolve_role_note


def test_compile_markdown_spec_extracts_sections(sample_spec_text: str) -> None:
    compiled = compile_markdown_spec(sample_spec_text)
    assert compiled["goal"] == "Ship the requested behavior."
    assert compiled["check_mode"] == "specified"
    assert len(compiled["checks"]) == 2
    assert compiled["checks"][0]["id"] == "check_001"
    assert compiled["checks"][1]["expect"] == "The edge path stays safe and understandable."
    assert compiled["constraints"] == "- Keep changes focused."
    assert compiled["success_surface"] == [
        "The result remains easy for the next role to verify.",
        "The surrounding contract stays clear enough to revise safely.",
    ]
    assert compiled["fake_done_states"] == [
        "A happy-path-only result that leaves the edge path unverifiable.",
    ]
    assert compiled["evidence_preferences"] == [
        "Prefer structured run artifacts and reproducible checks over role self-report.",
    ]
    target_ids = [item["id"] for item in compiled["coverage_targets"]]
    assert target_ids == [
        "done_when.check_001",
        "done_when.check_002",
        "fake_done.risk_001",
        "evidence_preference.pref_001",
        "gatekeeper.finish",
    ]
    assert compiled["coverage_targets"][0]["required"] is True
    assert compiled["coverage_targets"][2]["required"] is False
    assert "unverifiable completion should fail closed" in compiled["residual_risk"]
    assert compiled["role_notes"]["builder"] == "Move the workspace toward a verifiable state with focused edits."


def test_compile_markdown_spec_allows_missing_checks_for_exploration(exploratory_spec_text: str) -> None:
    compiled = compile_markdown_spec(exploratory_spec_text)
    assert compiled["goal"] == "Build a rough prototype that proves the main interaction is promising."
    assert compiled["check_mode"] == "auto_generated"
    assert compiled["checks"] == []
    assert [item["id"] for item in compiled["coverage_targets"]] == ["gatekeeper.finish"]


def test_compile_markdown_spec_requires_task() -> None:
    with pytest.raises(SpecError, match="missing top-level sections: Task"):
        compile_markdown_spec("# Guardrails\n\nOnly guardrails.\n")


def test_compile_markdown_spec_rejects_legacy_sections() -> None:
    with pytest.raises(SpecError, match="legacy spec headings"):
        compile_markdown_spec("# Goal\n\nLegacy.\n")


def test_compile_markdown_spec_ignores_html_comments_inside_sections() -> None:
    compiled = compile_markdown_spec(
        """# Task

<!-- temporary note -->
Ship the requested behavior.

# Guardrails

<!-- keep files -->
- Preserve existing files.
"""
    )
    assert compiled["goal"] == "Ship the requested behavior."
    assert compiled["constraints"] == "- Preserve existing files."


def test_resolve_role_note_matches_role_name_and_archetype(sample_spec_text: str) -> None:
    compiled = compile_markdown_spec(sample_spec_text)
    assert resolve_role_note(compiled, role_name="Builder") == "Move the workspace toward a verifiable state with focused edits."
    assert resolve_role_note(compiled, role_name="Release Builder", archetype="builder") == "Move the workspace toward a verifiable state with focused edits."


def test_render_spec_template_renders_unique_role_note_sections() -> None:
    template = render_spec_template(
        locale="en",
        workflow={
            "version": 1,
            "roles": [
                {"id": "builder", "name": "Builder", "archetype": "builder", "prompt_ref": "builder.md"},
                {"id": "gatekeeper", "name": "GateKeeper", "archetype": "gatekeeper", "prompt_ref": "gatekeeper.md"},
            ],
            "steps": [
                {"id": "builder_step", "role_id": "builder"},
                {"id": "builder_retry", "role_id": "builder"},
                {"id": "gatekeeper_step", "role_id": "gatekeeper"},
            ],
        },
    )

    assert "# Task" in template
    assert "# Done When" in template
    assert "# Guardrails" in template
    assert "# Role Notes" in template
    assert template.count("## Builder Notes") == 1
    assert template.count("## GateKeeper Notes") == 1


def test_compile_markdown_spec_extracts_task_contract_sections() -> None:
    compiled = compile_markdown_spec(
        """# Task

Ship the requested behavior without creating a maintenance mess.

# Done When

- The primary flow works end to end.

# Guardrails

- Keep changes focused.

# Success Surface

- The surrounding structure stays understandable.
- The implementation is easy to extend next round.

# Fake Done

- A patch that passes the happy path but leaves obvious duplication behind.

# Evidence Preferences

- Prefer real project commands and reproducible tests over screenshots alone.

# Residual Risk

Minor copy polish can wait, but structural regressions should fail closed.
"""
    )

    assert compiled["success_surface"] == [
        "The surrounding structure stays understandable.",
        "The implementation is easy to extend next round.",
    ]
    assert compiled["fake_done_states"] == [
        "A patch that passes the happy path but leaves obvious duplication behind.",
    ]
    assert compiled["evidence_preferences"] == [
        "Prefer real project commands and reproducible tests over screenshots alone.",
    ]
    assert {item["id"] for item in compiled["coverage_targets"]} >= {
        "done_when.check_001",
        "fake_done.risk_001",
        "evidence_preference.pref_001",
        "gatekeeper.finish",
    }
    assert compiled["residual_risk"] == "Minor copy polish can wait, but structural regressions should fail closed."
