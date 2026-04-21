from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from loopora.workflows import build_preset_workflow, display_name_for_archetype, normalize_role_display_name, normalize_workflow

REQUIRED_SECTIONS = ["Task"]
HTML_COMMENT_PATTERN = re.compile(r"<!--.*?-->", re.DOTALL)
BULLET_ITEM_PATTERN = re.compile(r"^\s*[-*]\s+(.+?)\s*$", re.MULTILINE)
ROLE_NOTE_HEADING_PATTERN = re.compile(r"^## (.+?)\s*$", re.MULTILINE)
ROLE_NOTES_SUFFIX_RE = re.compile(r"\s+notes\s*$", re.IGNORECASE)

GENERIC_ROLE_NOTE_COPY = {
    "zh": "补充当前角色执行这个任务时应优先关注的重点、证据偏好或工作方式。不要在这里新增真正的通过条件。",
    "en": "Add the priorities, evidence preferences, or working style this role should keep in mind for this task. Do not add hidden pass/fail criteria here.",
}

ROLE_NOTE_DEFAULTS = {
    "builder": {
        "zh": "优先做聚焦、原地的小改动，把任务尽快推进到可验证的状态。",
        "en": "Prefer focused in-place changes that move the task quickly toward a verifiable state.",
    },
    "inspector": {
        "zh": "优先收集最关键、最可复现的证据，不要把模糊推测包装成确定结论。",
        "en": "Start with the most important reproducible evidence, and do not present guesses as certain findings.",
    },
    "gatekeeper": {
        "zh": "只有在 Done When 和 Guardrails 都有直接证据支撑时才放行；证据偏弱时宁可保守。",
        "en": "Only pass when Done When and Guardrails are backed by direct evidence; stay conservative when evidence is weak.",
    },
    "guide": {
        "zh": "在停滞或回退时，优先给出最小但高杠杆的方向调整，不要变成第二个 GateKeeper。",
        "en": "When progress stalls or regresses, suggest the smallest high-leverage direction change instead of acting like a second GateKeeper.",
    },
    "custom": {
        "zh": "保持只读辅助角色定位，优先给出具体观察和窄范围建议。",
        "en": "Stay in a read-only supporting role and focus on concrete observations plus narrow recommendations.",
    },
}


class SpecError(ValueError):
    """Raised when a Markdown spec cannot be compiled."""


def spec_template(locale: str = "zh", workflow: dict[str, Any] | None = None) -> str:
    return render_spec_template(locale=locale, workflow=workflow)


def render_spec_template(locale: str = "zh", workflow: dict[str, Any] | None = None) -> str:
    use_zh = locale.lower().startswith("zh")
    normalized_workflow = {"version": 1, "preset": "", "roles": [], "steps": []}
    if workflow:
        roles = workflow.get("roles") if isinstance(workflow, dict) else None
        steps = workflow.get("steps") if isinstance(workflow, dict) else None
        preset_name = str(workflow.get("preset", "")).strip() if isinstance(workflow, dict) else ""
        if isinstance(roles, list) and isinstance(steps, list) and (roles or steps):
            normalized_workflow = normalize_workflow(workflow)
        elif preset_name:
            normalized_workflow = build_preset_workflow(preset_name)
    role_note_sections = _render_role_note_sections(normalized_workflow, locale="zh" if use_zh else "en")
    if use_zh:
        return (
            "<!--\n"
            "这段提示看完就可以删。\n\n"
            "必填：\n"
            "- 保留 `# Task`。如果删掉，spec 校验会直接失败。\n\n"
            "可选：\n"
            "- 如果你还不想固定成功条件，可以先删掉整个 `# Done When`，Loopora 会在 run 开始时自动生成并冻结一组 checks。\n"
            "- 如果暂时没有额外边界，可以删掉 `# Guardrails` 里的占位项。\n"
            "- `# Role Notes` 只会附加到对应角色的 prompt，不会变成隐藏的通过标准。\n"
            "-->\n\n"
            "# Task\n\n"
            "用一句到两句话写清这次 run 最终要完成什么。\n\n"
            "# Done When\n\n"
            "- 写一条最关键、可判定的成功结果\n"
            "- 再写 1 到 2 条需要保住的结果或证据\n\n"
            "# Guardrails\n\n"
            "- 不允许破坏什么\n"
            "- 哪些目录或接口必须保留\n"
            "- 是否必须保留现有用户文件\n"
            "- 是否要求原地小改、避免大范围重写\n\n"
            "# Role Notes\n\n"
            "如果当前流程已经确定，可以按角色补充一些工作方式提示。这里的内容只会附加到对应角色的 prompt，"
            "不会变成隐藏的通过标准。\n\n"
            f"{role_note_sections}".rstrip()
            + "\n"
        )
    return (
        "<!--\n"
        "Delete this note whenever you want.\n\n"
        "Required:\n"
        "- Keep `# Task`. If you delete it, spec validation fails.\n\n"
        "Optional:\n"
        "- If you are not ready to lock success criteria yet, delete `# Done When` and Loopora will auto-generate plus freeze checks at run start.\n"
        "- If there are no extra boundaries yet, remove the placeholder bullets inside `# Guardrails`.\n"
        "- `# Role Notes` only adjusts role prompts. It does not change pass/fail rules.\n"
        "-->\n\n"
        "# Task\n\n"
        "Describe in one or two sentences what this run should accomplish.\n\n"
        "# Done When\n\n"
        "- State the most important judgeable success outcome\n"
        "- Add 1 to 2 more outcomes or evidence requirements if they matter\n\n"
        "# Guardrails\n\n"
        "- Say what must not be broken\n"
        "- Say which directories or interfaces must be preserved\n"
        "- Say whether you must preserve existing user files\n"
        "- Say whether focused in-place edits are preferred over broad rewrites\n\n"
        "# Role Notes\n\n"
        "If the workflow is already chosen, add role-specific working notes here. These notes are appended to the matching "
        "role prompt only and never become hidden pass/fail rules.\n\n"
        f"{role_note_sections}".rstrip()
        + "\n"
    )


def init_spec_file(path: Path, *, locale: str = "zh") -> Path:
    return init_spec_file_for_workflow(path, locale=locale, workflow=None)


def init_spec_file_for_workflow(path: Path, *, locale: str = "zh", workflow: dict[str, Any] | None = None) -> Path:
    if path.exists():
        raise FileExistsError(f"spec already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_spec_template(locale=locale, workflow=workflow), encoding="utf-8")
    return path


def compile_markdown_spec(markdown_text: str) -> dict:
    cleaned_markdown = _strip_html_comments(markdown_text)
    sections = _split_sections(cleaned_markdown)
    _reject_legacy_sections(sections)
    missing = [section for section in REQUIRED_SECTIONS if not sections.get(section)]
    if missing:
        raise SpecError(f"missing top-level sections: {', '.join(missing)}")

    done_when_section = sections.get("Done When", "")
    checks = _extract_done_when_checks(done_when_section)
    if done_when_section.strip() and not checks:
        raise SpecError("`# Done When` must contain at least one top-level bullet item")
    role_notes = _extract_role_notes(sections.get("Role Notes", ""))

    compiled_checks = []
    for index, check in enumerate(checks, start=1):
        compiled_checks.append(
            {
                "id": f"check_{index:03d}",
                "title": check["title"],
                "details": check["body"],
                "when": check["when"],
                "expect": check["expect"],
                "fail_if": check["fail_if"],
                "source": "specified",
            }
        )

    return {
        "goal": sections["Task"].strip(),
        "constraints": sections.get("Guardrails", "").strip(),
        "checks": compiled_checks,
        "check_mode": "specified" if compiled_checks else "auto_generated",
        "role_notes": role_notes,
        "raw_sections": {key: value.strip() for key, value in sections.items()},
    }


def read_and_compile(path: Path) -> tuple[str, dict]:
    markdown_text = path.read_text(encoding="utf-8")
    return markdown_text, compile_markdown_spec(markdown_text)


def resolve_role_note(compiled_spec: dict[str, Any], *, role_name: str, archetype: str | None = None) -> str:
    role_notes = compiled_spec.get("role_notes")
    if not isinstance(role_notes, dict):
        return ""
    normalized_name = normalize_role_display_name(role_name, archetype=archetype) or str(role_name or "").strip()
    exact_candidates = [candidate.lower() for candidate in (normalized_name, str(role_name or "").strip()) if candidate]
    for candidate in exact_candidates:
        if candidate in role_notes:
            return str(role_notes[candidate]).strip()
    if archetype:
        archetype_label = display_name_for_archetype(archetype, locale="en").lower()
        if archetype_label in role_notes:
            return str(role_notes[archetype_label]).strip()
    return ""


def _split_sections(markdown_text: str) -> dict[str, str]:
    pattern = re.compile(r"^# (.+?)\s*$", re.MULTILINE)
    matches = list(pattern.finditer(markdown_text))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        name = match.group(1).strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown_text)
        sections[name] = markdown_text[start:end].strip()
    return sections


def _strip_html_comments(markdown_text: str) -> str:
    return HTML_COMMENT_PATTERN.sub("", markdown_text)


def _extract_done_when_checks(section_text: str) -> list[dict[str, str]]:
    matches = list(BULLET_ITEM_PATTERN.finditer(section_text))
    checks: list[dict[str, str]] = []
    for index, match in enumerate(matches, start=1):
        body = match.group(1).strip()
        title = _short_check_title(body, index=index)
        checks.append(
            {
                "title": title,
                "body": body,
                "when": "Someone evaluates the latest workspace state against the run contract.",
                "expect": body,
                "fail_if": f"The workspace still does not satisfy this outcome: {body}",
            }
        )
    return checks


def _short_check_title(body: str, *, index: int) -> str:
    clean = re.sub(r"\s+", " ", body).strip(" .")
    if not clean:
        return f"Done When item {index}"
    words = clean.split(" ")
    if len(words) <= 8:
        return clean
    return " ".join(words[:8]).rstrip(" ,.;:") + "..."


def _extract_role_notes(section_text: str) -> dict[str, str]:
    matches = list(ROLE_NOTE_HEADING_PATTERN.finditer(section_text))
    if section_text.strip() and not matches:
        raise SpecError("`# Role Notes` must use `## <Role Name> Notes` subheadings")
    notes: dict[str, str] = {}
    for index, match in enumerate(matches):
        title = match.group(1).strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(section_text)
        body = section_text[start:end].strip()
        if not body:
            continue
        normalized_title = _normalize_role_note_heading(title)
        if not normalized_title:
            raise SpecError("role note subheadings must look like `## <Role Name> Notes`")
        notes[normalized_title] = body
    return notes


def _normalize_role_note_heading(title: str) -> str:
    trimmed = str(title or "").strip()
    without_suffix = ROLE_NOTES_SUFFIX_RE.sub("", trimmed).strip()
    if not without_suffix or without_suffix == trimmed:
        return ""
    return without_suffix.lower()


def _reject_legacy_sections(sections: dict[str, str]) -> None:
    legacy = [name for name in ("Goal", "Checks", "Constraints") if name in sections]
    if legacy:
        raise SpecError(
            "legacy spec headings are no longer supported; use `# Task`, `# Done When`, `# Guardrails`, and `# Role Notes`"
        )


def _render_role_note_sections(workflow: dict[str, Any], *, locale: str) -> str:
    sections: list[str] = []
    seen: set[str] = set()
    roles = workflow.get("roles") if isinstance(workflow, dict) else []
    if not isinstance(roles, list):
        roles = []
    for role in roles:
        if not isinstance(role, dict):
            continue
        archetype = str(role.get("archetype") or "").strip()
        title = normalize_role_display_name(role.get("name"), archetype=archetype) or str(role.get("name") or "").strip()
        if not title or title.lower() in seen:
            continue
        seen.add(title.lower())
        note_copy = ROLE_NOTE_DEFAULTS.get(archetype, GENERIC_ROLE_NOTE_COPY)["zh" if locale == "zh" else "en"]
        sections.append(f"## {title} Notes\n\n{note_copy}")
    if sections:
        return "\n\n".join(sections)
    fallback = ROLE_NOTE_DEFAULTS["builder"]["zh" if locale == "zh" else "en"]
    return f"## Builder Notes\n\n{fallback}"
