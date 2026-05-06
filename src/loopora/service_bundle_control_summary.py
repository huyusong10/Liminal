from __future__ import annotations

import re

from loopora.specs import SpecError, compile_markdown_spec


def preview_list_items(markdown_text: str, *, limit: int = 4) -> list[str]:
    items = []
    for line in str(markdown_text or "").splitlines():
        cleaned = re.sub(r"^\s*[-*]\s+", "", line).strip()
        cleaned = re.sub(r"^\s*\d+[.)]\s+", "", cleaned).strip()
        if not cleaned or cleaned.startswith("#"):
            continue
        items.append(cleaned)
        if len(items) >= limit:
            break
    if items:
        return items
    compact = re.sub(r"\s+", " ", str(markdown_text or "")).strip()
    return [compact[:180]] if compact else []


def build_bundle_control_summary(bundle: dict) -> dict:
    compiled_spec = _compile_bundle_spec(bundle)
    raw_sections = _raw_sections(compiled_spec)
    roles = list(bundle.get("role_definitions") or [])
    workflow = dict(bundle.get("workflow") or {})
    steps = list(workflow.get("steps") or [])
    role_lookup = _role_lookup(roles=roles, workflow_roles=list(workflow.get("roles") or []))
    gatekeeper = _gatekeeper_projection(steps, role_lookup)

    return {
        "risks": preview_list_items(
            str(raw_sections.get("Fake Done") or "") + "\n" + str(raw_sections.get("Residual Risk") or ""),
            limit=4,
        ),
        "evidence": _evidence_titles(compiled_spec),
        "workflow": _workflow_projection(steps, role_lookup),
        "gatekeeper": gatekeeper,
        "controls": _control_summaries(workflow, role_lookup),
    }


def _compile_bundle_spec(bundle: dict) -> dict:
    try:
        compiled_spec = compile_markdown_spec(str(bundle.get("spec", {}).get("markdown") or ""))
    except SpecError:
        return {"raw_sections": {}}
    return compiled_spec if isinstance(compiled_spec, dict) else {"raw_sections": {}}


def _raw_sections(compiled_spec: dict) -> dict:
    raw_sections = compiled_spec.get("raw_sections")
    return raw_sections if isinstance(raw_sections, dict) else {}


def _evidence_titles(compiled_spec: dict) -> list[str]:
    return [
        str(check.get("title") or "").strip()
        for check in list(compiled_spec.get("checks") or [])[:4]
        if isinstance(check, dict) and str(check.get("title") or "").strip()
    ]


def _role_lookup(*, roles: list[dict], workflow_roles: list[dict]) -> dict:
    role_definition_by_key = {str(role.get("key") or ""): role for role in roles if isinstance(role, dict)}
    workflow_role_by_id = {
        str(role.get("id") or ""): role
        for role in workflow_roles
        if isinstance(role, dict) and str(role.get("id") or "").strip()
    }
    return {
        "role_definition_by_key": role_definition_by_key,
        "workflow_role_by_id": workflow_role_by_id,
    }


def _role_for_step(step: dict, role_lookup: dict) -> dict:
    workflow_role = role_lookup["workflow_role_by_id"].get(str(step.get("role_id") or ""), {})
    return role_lookup["role_definition_by_key"].get(str(workflow_role.get("role_definition_key") or ""), {})


def _step_label(step: dict, role_lookup: dict) -> str:
    role = _role_for_step(step, role_lookup)
    return str(role.get("name") or step.get("role_id") or step.get("id") or "").strip()


def _workflow_projection(steps: list[dict], role_lookup: dict) -> dict:
    return {
        "step_count": len(steps),
        "parallel_groups": _parallel_groups(steps),
        "summary": " -> ".join(item for item in _grouped_step_labels(steps, role_lookup) if item),
    }


def _parallel_groups(steps: list[dict]) -> list[str]:
    return sorted(
        {
            str(step.get("parallel_group") or "").strip()
            for step in steps
            if str(step.get("parallel_group") or "").strip()
        }
    )


def _grouped_step_labels(steps: list[dict], role_lookup: dict) -> list[str]:
    grouped_steps: list[str] = []
    index = 0
    while index < len(steps):
        step = steps[index]
        group = str(step.get("parallel_group") or "").strip()
        if group:
            grouped = []
            while index < len(steps) and str(steps[index].get("parallel_group") or "").strip() == group:
                grouped.append(_step_label(steps[index], role_lookup))
                index += 1
            grouped_steps.append("[" + " + ".join(item for item in grouped if item) + "]")
            continue
        grouped_steps.append(_step_label(step, role_lookup))
        index += 1
    return grouped_steps


def _gatekeeper_projection(steps: list[dict], role_lookup: dict) -> dict:
    gatekeeper_steps = [
        step
        for step in steps
        if str(_role_for_step(step, role_lookup).get("archetype") or "").strip().lower() == "gatekeeper"
    ]
    return {
        "enabled": bool(gatekeeper_steps),
        "roles": _gatekeeper_role_names(gatekeeper_steps, role_lookup),
        "finish_steps": [
            str(step.get("id") or "").strip()
            for step in gatekeeper_steps
            if str(step.get("on_pass") or "").strip() == "finish_run"
        ],
        "requires_evidence_refs": True,
    }


def _gatekeeper_role_names(gatekeeper_steps: list[dict], role_lookup: dict) -> list[str]:
    gatekeeper_roles = []
    for step in gatekeeper_steps:
        role_name = _step_label(step, role_lookup)
        if role_name and role_name not in gatekeeper_roles:
            gatekeeper_roles.append(role_name)
    return gatekeeper_roles


def _control_summaries(workflow: dict, role_lookup: dict) -> list[dict]:
    control_summaries = []
    for control in list(workflow.get("controls") or []):
        if not isinstance(control, dict):
            continue
        role_id = str((control.get("call") or {}).get("role_id") or "").strip()
        workflow_role = role_lookup["workflow_role_by_id"].get(role_id, {})
        role_definition = role_lookup["role_definition_by_key"].get(str(workflow_role.get("role_definition_key") or ""), {})
        control_summaries.append(
            {
                "id": str(control.get("id") or "").strip(),
                "signal": str((control.get("when") or {}).get("signal") or "").strip(),
                "after": str((control.get("when") or {}).get("after") or "").strip(),
                "role_id": role_id,
                "role_name": str(role_definition.get("name") or role_id).strip(),
                "role_archetype": str(role_definition.get("archetype") or "").strip(),
                "mode": str(control.get("mode") or "").strip(),
                "max_fires_per_run": _control_max_fires_per_run(control.get("max_fires_per_run")),
            }
        )
    return control_summaries


def _control_max_fires_per_run(value: object) -> int | str:
    if value is None or value == "":
        return 1
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return str(value).strip()
