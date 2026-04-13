from __future__ import annotations

import hashlib
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

SPEC_SKILL_SLUG = "liminal-spec"

TARGET_DOCS = {
    "codex": "https://developers.openai.com/codex/skills",
    "claude": "https://code.claude.com/docs/en/skills",
    "opencode": "https://opencode.ai/docs/skills/",
}

TARGET_LABELS = {
    "codex": "Codex",
    "claude": "Claude Code",
    "opencode": "OpenCode",
}

IGNORED_SKILL_ARTIFACTS = {".DS_Store", "__pycache__"}


@dataclass(frozen=True)
class SkillBundle:
    slug: str
    name: str
    description: str
    source_dir: Path


def _home() -> Path:
    return Path.home()


def _codex_home() -> Path:
    raw = os.environ.get("CODEX_HOME", "").strip()
    if raw:
        return Path(raw).expanduser()
    return _home() / ".codex"


def _parse_frontmatter(skill_path: Path) -> tuple[str, str]:
    lines = skill_path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError(f"missing frontmatter in {skill_path}")

    metadata: dict[str, str] = {}
    for line in lines[1:]:
        stripped = line.strip()
        if stripped == "---":
            break
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip()

    name = metadata.get("name", "").strip()
    description = metadata.get("description", "").strip()
    if not name or not description:
        raise ValueError(f"incomplete frontmatter in {skill_path}")
    return name, description


def _load_spec_skill_bundle() -> SkillBundle:
    source_dir = Path(__file__).parent / "assets" / SPEC_SKILL_SLUG
    skill_path = source_dir / "SKILL.md"
    name, description = _parse_frontmatter(skill_path)
    return SkillBundle(
        slug=SPEC_SKILL_SLUG,
        name=name,
        description=description,
        source_dir=source_dir,
    )


def _target_paths(target: str, bundle: SkillBundle) -> list[Path]:
    if target == "codex":
        return [_codex_home() / "skills" / bundle.name]
    if target == "claude":
        return [_home() / ".claude" / "skills" / bundle.name]
    if target == "opencode":
        return [_home() / ".config" / "opencode" / "skills" / bundle.name]
    raise ValueError(f"unsupported skill target: {target}")


def _copy_bundle(source_dir: Path, target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    for source in source_dir.rglob("*"):
        relative = source.relative_to(source_dir)
        destination = target_dir / relative
        if source.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def _remove_target_dir(target_dir: Path) -> None:
    if not target_dir.exists():
        return
    if target_dir.is_dir():
        shutil.rmtree(target_dir)
        return
    target_dir.unlink()


def _bundle_digest(root: Path) -> str | None:
    if not root.exists():
        return None
    digest = hashlib.sha256()
    file_count = 0
    for file_path in sorted(path for path in root.rglob("*") if path.is_file()):
        if any(part in IGNORED_SKILL_ARTIFACTS for part in file_path.parts):
            continue
        relative = file_path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_path.read_bytes())
        digest.update(b"\0")
        file_count += 1
    if file_count == 0:
        return None
    return digest.hexdigest()


def _install_state(bundle: SkillBundle, install_path: Path) -> str:
    skill_file = install_path / "SKILL.md"
    if not skill_file.exists():
        return "missing"
    source_digest = _bundle_digest(bundle.source_dir)
    installed_digest = _bundle_digest(install_path)
    if source_digest and installed_digest and source_digest == installed_digest:
        return "installed"
    return "stale"


def list_spec_skill_targets() -> list[dict]:
    bundle = _load_spec_skill_bundle()
    targets = []
    for target in ("codex", "claude", "opencode"):
        install_paths = _target_paths(target, bundle)
        install_state = "missing"
        existing_paths = [path / "SKILL.md" for path in install_paths if (path / "SKILL.md").exists()]
        if install_paths:
            install_state = _install_state(bundle, install_paths[0])
        targets.append(
            {
                "target": target,
                "label": TARGET_LABELS[target],
                "docs_url": TARGET_DOCS[target],
                "skill_name": bundle.name,
                "skill_description": bundle.description,
                "install_paths": [str(path / "SKILL.md") for path in install_paths],
                "installed_paths": [str(path) for path in existing_paths],
                "installed": install_state == "installed",
                "install_state": install_state,
            }
        )
    return targets


def install_spec_skill(target: str) -> dict:
    bundle = _load_spec_skill_bundle()
    install_paths = _target_paths(target, bundle)
    written_paths: list[str] = []
    replaced_existing = False
    for path in install_paths:
        if path.exists():
            replaced_existing = True
            _remove_target_dir(path)
        _copy_bundle(bundle.source_dir, path)
        written_paths.append(str(path / "SKILL.md"))
    return {
        "target": target,
        "label": TARGET_LABELS[target],
        "docs_url": TARGET_DOCS[target],
        "skill_name": bundle.name,
        "written_paths": written_paths,
        "action": "reinstalled" if replaced_existing else "installed",
        "requires_restart": True,
    }
