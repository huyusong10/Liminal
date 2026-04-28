from __future__ import annotations

import subprocess
from pathlib import Path


def test_loopora_task_alignment_skill_validates() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    skill_dir = repo_root / "skills" / "loopora-task-alignment"
    skill_md = skill_dir / "SKILL.md"
    alignment_playbook = skill_dir / "references" / "alignment-playbook.md"
    quality_rubric = skill_dir / "references" / "quality-rubric.md"
    bundle_contract = skill_dir / "references" / "bundle-contract.md"
    feedback_revision = skill_dir / "references" / "feedback-revision.md"
    examples = skill_dir / "references" / "examples.md"

    assert skill_md.exists()
    assert alignment_playbook.exists()
    assert quality_rubric.exists()
    assert bundle_contract.exists()
    assert feedback_revision.exists()
    assert examples.exists()
    skill_text = skill_md.read_text(encoding="utf-8")
    assert "[TODO" not in skill_text
    assert "task-judgment interviewer" in skill_text
    assert "parallel_group" in skill_text
    assert "Contract Inspector" in examples.read_text(encoding="utf-8")
    assert "inputs.handoffs_from" in alignment_playbook.read_text(encoding="utf-8")
    assert "bounded parallel inspection" in quality_rubric.read_text(encoding="utf-8")
    assert "Builder -> [Contract Inspector + Evidence Inspector] -> GateKeeper" in bundle_contract.read_text(encoding="utf-8")

    result = subprocess.run(
        [
            "python",
            "/Users/hys/.codex/skills/.system/skill-creator/scripts/quick_validate.py",
            str(skill_dir),
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
