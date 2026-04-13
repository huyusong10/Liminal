from __future__ import annotations

import pytest

from liminal.specs import SpecError, compile_markdown_spec


def test_compile_markdown_spec_extracts_sections(sample_spec_text: str) -> None:
    compiled = compile_markdown_spec(sample_spec_text)
    assert compiled["goal"] == "Ship the requested behavior."
    assert len(compiled["cases"]) == 2
    assert compiled["cases"][0]["id"] == "case_001"
    assert compiled["cases"][1]["expected_result"] == "- The edge path stays safe."


def test_compile_markdown_spec_requires_all_sections() -> None:
    with pytest.raises(SpecError):
        compile_markdown_spec("# Goal\n\nOnly goal.\n")
