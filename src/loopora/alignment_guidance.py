from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AlignmentGuidanceAssets:
    source_dir: Path
    compiler_policy: str
    product_primer: str
    alignment_playbook: str
    quality_rubric: str
    bundle_contract: str
    examples: str
    feedback_improvement: str


def alignment_guidance_dir() -> Path:
    return Path(__file__).resolve().parent / "assets" / "alignment"


def _read_guidance_asset(source_dir: Path, name: str) -> str:
    return (source_dir / name).read_text(encoding="utf-8")


def load_alignment_guidance_assets() -> AlignmentGuidanceAssets:
    source_dir = alignment_guidance_dir()
    return AlignmentGuidanceAssets(
        source_dir=source_dir,
        compiler_policy=_read_guidance_asset(source_dir, "compiler-policy.md"),
        product_primer=_read_guidance_asset(source_dir, "product-primer.md"),
        alignment_playbook=_read_guidance_asset(source_dir, "alignment-playbook.md"),
        quality_rubric=_read_guidance_asset(source_dir, "quality-rubric.md"),
        bundle_contract=_read_guidance_asset(source_dir, "bundle-contract.md"),
        examples=_read_guidance_asset(source_dir, "examples.md"),
        feedback_improvement=_read_guidance_asset(source_dir, "feedback-improvement.md"),
    )
