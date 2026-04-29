from __future__ import annotations

import io
import tomllib
import zipfile
from pathlib import Path

from loopora.skills import task_alignment_installer


REQUIRED_SKILL_FILES = {
    "SKILL.md",
    "agents/openai.yaml",
    "references/product-primer.md",
    "references/alignment-playbook.md",
    "references/quality-rubric.md",
    "references/bundle-contract.md",
    "references/feedback-improvement.md",
    "references/examples.md",
}


def _relative_files(root: Path) -> list[str]:
    return sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and path.name != ".DS_Store"
    )


def test_loopora_task_alignment_skill_validates() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    skill_dir = repo_root / "skills" / "loopora-task-alignment"

    for relative_path in REQUIRED_SKILL_FILES:
        assert (skill_dir / relative_path).exists()
    skill_text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    assert "[TODO" not in skill_text
    assert "product-primer.md" in skill_text
    assert "task-judgment interviewer" in skill_text
    assert "parallel_group" in skill_text
    assert "feedback-improvement.md" in skill_text
    primer_text = (skill_dir / "references" / "product-primer.md").read_text(encoding="utf-8")
    assert "local-first platform for composing, running, and observing long-running AI Agent tasks" in primer_text
    assert "Execution roles can be narrow" in primer_text
    assert "optional user-directed capability" in (
        skill_dir / "references" / "feedback-improvement.md"
    ).read_text(encoding="utf-8")
    assert "Contract Inspector" in (skill_dir / "references" / "examples.md").read_text(encoding="utf-8")
    assert "inputs.handoffs_from" in (skill_dir / "references" / "alignment-playbook.md").read_text(encoding="utf-8")
    assert "bounded parallel inspection" in (skill_dir / "references" / "quality-rubric.md").read_text(encoding="utf-8")
    assert (
        "Builder -> [Contract Inspector + Evidence Inspector] -> GateKeeper"
        in (skill_dir / "references" / "bundle-contract.md").read_text(encoding="utf-8")
    )


def test_task_alignment_packaged_skill_matches_repo_copy(monkeypatch, tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    repo_skill_dir = repo_root / "skills" / task_alignment_installer.TASK_ALIGNMENT_SKILL_SLUG
    packaged_skill_dir = (
        Path(task_alignment_installer.__file__).parent
        / "assets"
        / task_alignment_installer.TASK_ALIGNMENT_SKILL_SLUG
    )

    assert _relative_files(packaged_skill_dir) == _relative_files(repo_skill_dir)
    for relative_path in _relative_files(repo_skill_dir):
        assert (packaged_skill_dir / relative_path).read_bytes() == (repo_skill_dir / relative_path).read_bytes()

    monkeypatch.setattr(task_alignment_installer, "_repo_root_skill_dir", lambda: tmp_path / "missing-skill")
    bundle = task_alignment_installer.load_task_alignment_skill_bundle()
    assert bundle.source_dir == packaged_skill_dir

    archive_name, archive_bytes = task_alignment_installer.build_task_alignment_skill_archive()
    assert archive_name == f"{task_alignment_installer.TASK_ALIGNMENT_SKILL_SLUG}.zip"
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        names = set(archive.namelist())
    for relative_path in REQUIRED_SKILL_FILES:
        assert f"{task_alignment_installer.TASK_ALIGNMENT_SKILL_SLUG}/{relative_path}" in names


def test_runtime_assets_are_declared_for_package_data() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
    package_data = set(pyproject["tool"]["setuptools"]["package-data"]["loopora"])

    assert "assets/prompts/*.md" in package_data
    assert "assets/spec_practices/*.md" in package_data
    assert "skills/assets/*/SKILL.md" in package_data
    assert "skills/assets/*/agents/*.yaml" in package_data
    assert "skills/assets/*/references/*.md" in package_data
