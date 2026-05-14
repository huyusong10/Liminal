from __future__ import annotations

import tomllib
from pathlib import Path

from loopora.alignment_guidance import alignment_guidance_dir, load_alignment_guidance_assets


def _assert_contains_all(text: str, snippets: tuple[str, ...]) -> None:
    missing = [snippet for snippet in snippets if snippet not in text]
    assert missing == []


def test_alignment_guidance_assets_are_internal_compiler_material() -> None:
    source_dir = alignment_guidance_dir()
    assert source_dir.exists()
    assert not (Path(__file__).resolve().parents[3] / "skills" / "loopora-task-alignment").exists()

    assets = load_alignment_guidance_assets()
    assert assets.source_dir == source_dir
    _assert_contains_all(
        assets.system_prompt_template,
        (
            "You are Loopora's built-in Web Loop alignment agent",
            "Important output discipline",
            "{{bundle_path}}",
            "{{stage_policy}}",
            "{{session_transcript_json}}",
        ),
    )
    _assert_contains_all(
        assets.compiler_gates,
        (
            "Current compiler gate: clarifying",
            "Current compiler gate: confirmed agreement",
            "Before asking the user, answer anything you can from the transcript",
        ),
    )
    _assert_contains_all(
        assets.compiler_policy,
        (
            "internal compiler flow",
            "not an external Skill workflow",
            "The background Agent drives semantic conversation",
            "Loopora backend owns phase acceptance",
            "Repairable issues may be fixed by the Agent",
            "Human-required issues must go back to conversation",
            "branch-aware pressure testing",
            "answer everything you can from the transcript",
            "Follow the user's chosen or corrected branch",
            "Agent as conversation driver",
            "Backend as compiler guard",
        ),
    )


def test_alignment_guidance_preserves_product_and_bundle_contracts() -> None:
    assets = load_alignment_guidance_assets()
    _assert_contains_all(
        assets.product_primer,
        (
            "local-first platform for composing human-shaped governance loops",
            "human-in-the-loop -> human-shaped loop",
            "compile the user's task judgment into a runnable Loop candidate",
        ),
    )
    _assert_contains_all(
        assets.alignment_playbook,
        (
            "Loopora fit gate",
            "Branch-aware pressure test",
            "confirm the working agreement, review the READY Loop",
            "agreement-to-bundle traceability checklist",
            "long-chain phase workflow",
            "Do not use arbitrary DAG language",
        ),
    )
    assert "confirm Loop" not in assets.alignment_playbook
    _assert_contains_all(
        assets.bundle_contract,
        (
            "raw YAML document",
            "version: 1",
            "GateKeeper",
            "Proven, Weak, Unproven, Blocking, or Residual risk",
            "Default Web compiler bundles",
            "Do not emit nested Loops, arbitrary branch syntax",
        ),
    )


def test_alignment_guidance_is_packaged_without_skill_assets() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    package_data = pyproject["tool"]["setuptools"]["package-data"]["loopora"]
    assert "assets/alignment/*.md" in package_data
    assert not any(str(item).startswith("skills/assets") for item in package_data)


def test_alignment_system_prompt_text_lives_in_markdown_assets() -> None:
    service_source = (Path(__file__).resolve().parents[3] / "src" / "loopora" / "service_alignment.py").read_text(encoding="utf-8")
    for snippet in (
        "You are Loopora's built-in Web Loop alignment agent.",
        "Important output discipline:",
        "Current compiler gate: confirmed agreement.",
        "The previous bundle failed Loopora's hard validator.",
        "Selected Loopora Source Context",
        "Bundle Improvement Context",
    ):
        assert snippet not in service_source

    assets = load_alignment_guidance_assets()
    _assert_contains_all(
        "\n".join(
            (
                assets.system_prompt_template,
                assets.compiler_gates,
                assets.repair_input_template,
                assets.current_bundle_template,
                assets.selected_source_context_template,
                assets.bundle_improvement_context_template,
            )
        ),
        (
            "You are Loopora's built-in Web Loop alignment agent.",
            "Important output discipline:",
            "Current compiler gate: confirmed agreement.",
            "The previous bundle failed Loopora's hard validator.",
            "Selected Loopora Source Context",
            "Bundle Improvement Context",
        ),
    )
