from __future__ import annotations

from pathlib import Path

from loopora.markdown_tools import render_safe_markdown_html
from loopora.specs import SpecError, compile_markdown_spec
from loopora.workflows import load_workflow_file, normalize_role_display_name, normalize_workflow

from loopora.cli_common import get_service


def spec_validation_from_markdown(markdown_text: str) -> dict[str, object]:
    try:
        compiled = compile_markdown_spec(markdown_text)
    except SpecError as exc:
        return {
            "ok": False,
            "error": str(exc),
            "check_count": 0,
            "check_mode": "",
        }
    return {
        "ok": True,
        "error": "",
        "check_count": len(compiled["checks"]),
        "check_mode": compiled["check_mode"],
    }


def spec_document_payload(path: Path, markdown_text: str) -> dict[str, object]:
    return {
        "ok": True,
        "path": str(path.resolve()),
        "content": markdown_text,
        "rendered_html": render_safe_markdown_html(markdown_text),
        "validation": spec_validation_from_markdown(markdown_text),
    }


def resolve_spec_template_workflow(
    *,
    orchestration_id: str,
    workflow_preset: str,
    workflow_file: Path | None,
) -> dict | None:
    if workflow_file is not None:
        workflow, _ = load_workflow_file(workflow_file)
        return normalize_workflow(workflow) if workflow else None
    if orchestration_id.strip():
        orchestration = get_service().get_orchestration(orchestration_id.strip())
        workflow = orchestration.get("workflow_json") or None
        return normalize_workflow(workflow) if workflow else None
    if workflow_preset.strip():
        return normalize_workflow({"preset": workflow_preset.strip()})
    return None


def role_note_sections_for_workflow(workflow: dict | None) -> list[dict[str, str]]:
    if not workflow:
        return []
    sections: list[dict[str, str]] = []
    seen: set[str] = set()
    for role in workflow.get("roles", []):
        if not isinstance(role, dict):
            continue
        label = normalize_role_display_name(role.get("name"), archetype=role.get("archetype")) or str(role.get("name", "")).strip()
        normalized = label.lower()
        if not label or normalized in seen:
            continue
        seen.add(normalized)
        sections.append({"heading": f"{label} Notes", "role_name": label})
    return sections
