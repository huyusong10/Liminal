from __future__ import annotations

import pytest

from liminal.specs import SpecError, compile_markdown_spec


def test_compile_markdown_spec_extracts_sections(sample_spec_text: str) -> None:
    compiled = compile_markdown_spec(sample_spec_text)
    assert compiled["goal"] == "Ship the requested behavior."
    assert compiled["check_mode"] == "specified"
    assert len(compiled["checks"]) == 2
    assert compiled["checks"][0]["id"] == "check_001"
    assert compiled["checks"][1]["expect"] == "The edge path stays safe and understandable."


def test_compile_markdown_spec_allows_missing_checks_for_exploration(exploratory_spec_text: str) -> None:
    compiled = compile_markdown_spec(exploratory_spec_text)
    assert compiled["goal"] == "Build a rough prototype that proves the main interaction is promising."
    assert compiled["check_mode"] == "auto_generated"
    assert compiled["checks"] == []


def test_compile_markdown_spec_requires_goal() -> None:
    with pytest.raises(SpecError):
        compile_markdown_spec("# Constraints\n\nOnly constraints.\n")


def test_compile_markdown_spec_ignores_html_comments_inside_sections() -> None:
    compiled = compile_markdown_spec(
        """# Goal

<!-- temporary note -->
Ship the requested behavior.

# Constraints

<!-- keep files -->
- Preserve existing files.
"""
    )
    assert compiled["goal"] == "Ship the requested behavior."
    assert compiled["constraints"] == "- Preserve existing files."
