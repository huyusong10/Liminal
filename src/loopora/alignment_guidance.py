from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AlignmentGuidanceAssets:
    source_dir: Path
    system_prompt_template: str
    compiler_gates: str
    compiler_policy: str
    product_primer: str
    alignment_playbook: str
    quality_rubric: str
    bundle_contract: str
    examples: str
    feedback_improvement: str
    repair_input_template: str
    current_bundle_template: str
    selected_source_context_template: str
    selected_spec_markdown_template: str
    bundle_improvement_context_template: str


def alignment_guidance_dir() -> Path:
    return Path(__file__).resolve().parent / "assets" / "alignment"


def _read_guidance_asset(source_dir: Path, name: str) -> str:
    return (source_dir / name).read_text(encoding="utf-8")


def load_alignment_guidance_assets() -> AlignmentGuidanceAssets:
    source_dir = alignment_guidance_dir()
    return AlignmentGuidanceAssets(
        source_dir=source_dir,
        system_prompt_template=_read_guidance_asset(source_dir, "system-prompt.md"),
        compiler_gates=_read_guidance_asset(source_dir, "compiler-gates.md"),
        compiler_policy=_read_guidance_asset(source_dir, "compiler-policy.md"),
        product_primer=_read_guidance_asset(source_dir, "product-primer.md"),
        alignment_playbook=_read_guidance_asset(source_dir, "alignment-playbook.md"),
        quality_rubric=_read_guidance_asset(source_dir, "quality-rubric.md"),
        bundle_contract=_read_guidance_asset(source_dir, "bundle-contract.md"),
        examples=_read_guidance_asset(source_dir, "examples.md"),
        feedback_improvement=_read_guidance_asset(source_dir, "feedback-improvement.md"),
        repair_input_template=_read_guidance_asset(source_dir, "repair-input.md"),
        current_bundle_template=_read_guidance_asset(source_dir, "current-bundle.md"),
        selected_source_context_template=_read_guidance_asset(source_dir, "selected-source-context.md"),
        selected_spec_markdown_template=_read_guidance_asset(source_dir, "selected-spec-markdown.md"),
        bundle_improvement_context_template=_read_guidance_asset(source_dir, "bundle-improvement-context.md"),
    )
