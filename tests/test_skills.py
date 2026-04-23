from __future__ import annotations

import subprocess
from pathlib import Path


def test_loopora_task_alignment_skill_validates() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    skill_dir = repo_root / "skills" / "loopora-task-alignment"
    skill_md = skill_dir / "SKILL.md"
    bundle_contract = skill_dir / "references" / "bundle-contract.md"
    feedback_revision = skill_dir / "references" / "feedback-revision.md"

    assert skill_md.exists()
    assert bundle_contract.exists()
    assert feedback_revision.exists()
    assert "[TODO" not in skill_md.read_text(encoding="utf-8")

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
