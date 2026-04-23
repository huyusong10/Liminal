from __future__ import annotations

import ipaddress
import json
import re
from collections.abc import Mapping
from pathlib import Path

from fastapi import Request

from loopora.branding import APP_AUTH_COOKIE, APP_AUTH_HEADER
from loopora.markdown_tools import render_safe_markdown_html
from loopora.providers import executor_profile
from loopora.service import LooporaError, normalize_role_models
from loopora.specs import SpecError, compile_markdown_spec
from loopora.workflows import (
    ARCHETYPES,
    build_preset_workflow,
    builtin_prompt_markdown,
    builtin_prompt_markdown_by_locale,
    default_role_execution_settings,
    display_name_for_archetype,
    normalize_prompt_locale,
    normalize_workflow,
    resolve_prompt_files,
)

DEFAULT_LOOP_FORM = {
    "name": "",
    "workdir": "",
    "spec_path": "",
    "orchestration_id": "builtin:build_first",
    "completion_mode": "gatekeeper",
    "iteration_interval_seconds": 0,
    "max_iters": 8,
    "max_role_retries": 2,
    "delta_threshold": 0.005,
    "trigger_window": 4,
    "regression_window": 2,
    "start_immediately": True,
}

DEFAULT_ORCHESTRATION_FORM = {
    "name": "",
    "description": "",
    "workflow_preset": "",
    "workflow_json": "",
    "prompt_files_json": "",
}

DEFAULT_ROLE_DEFINITION_FORM = {
    "name": "",
    "description": "",
    "posture_notes": "",
    "archetype": "builder",
    "prompt_ref": "builder.md",
    "prompt_markdown": builtin_prompt_markdown("builder.md", locale="en"),
    **default_role_execution_settings(),
}

DEFAULT_BUNDLE_IMPORT_FORM = {
    "bundle_path": "",
    "bundle_yaml": "",
    "replace_bundle_id": "",
    "start_immediately": True,
}

DEFAULT_BUNDLE_DERIVE_FORM = {
    "loop_id": "",
    "name": "",
    "description": "",
    "collaboration_summary": "",
}


def _loop_payload_from_mapping(payload: Mapping[str, object]) -> tuple[dict[str, object], bool]:
    name = str(payload.get("name", "")).strip()
    workdir = str(payload.get("workdir", "")).strip()
    spec_path = str(payload.get("spec_path", "")).strip()
    executor_kind = str(payload.get("executor_kind", "codex")).strip() or "codex"
    executor_mode = str(payload.get("executor_mode", "preset")).strip() or "preset"
    try:
        profile = executor_profile(executor_kind)
    except ValueError as exc:
        raise LooporaError(str(exc)) from exc
    model = str(payload.get("model", "")).strip()
    reasoning_effort = str(payload.get("reasoning_effort", "")).strip()
    command_cli = str(payload.get("command_cli", "")).strip()
    command_args_text = str(payload.get("command_args_text", ""))
    if not name:
        raise LooporaError("name is required")
    if not workdir:
        raise LooporaError("workdir is required")
    if not spec_path:
        raise LooporaError("spec path is required")

    try:
        iteration_interval_seconds = float(payload.get("iteration_interval_seconds", 0))
        max_iters = int(payload.get("max_iters", 8))
        max_role_retries = int(payload.get("max_role_retries", 2))
        delta_threshold = float(payload.get("delta_threshold", 0.005))
        trigger_window = int(payload.get("trigger_window", 4))
        regression_window = int(payload.get("regression_window", 2))
    except (TypeError, ValueError) as exc:
        raise LooporaError("numeric loop settings must use valid numbers") from exc

    loop_kwargs = {
        "name": name,
        "spec_path": Path(spec_path),
        "workdir": Path(workdir),
        "orchestration_id": str(payload.get("orchestration_id", "")).strip() or None,
        "executor_kind": executor_kind,
        "executor_mode": executor_mode,
        "command_cli": command_cli if command_cli else profile.cli_name,
        "command_args_text": command_args_text,
        "model": model if model or profile.default_model == "" else profile.default_model,
        "reasoning_effort": reasoning_effort if reasoning_effort or profile.effort_default == "" else profile.effort_default,
        "completion_mode": str(payload.get("completion_mode", "gatekeeper")).strip() or "gatekeeper",
        "iteration_interval_seconds": iteration_interval_seconds,
        "max_iters": max_iters,
        "max_role_retries": max_role_retries,
        "delta_threshold": delta_threshold,
        "trigger_window": trigger_window,
        "regression_window": regression_window,
        "workflow": _workflow_from_mapping(payload, default_to_preset=False),
        "prompt_files": _prompt_files_from_mapping(payload),
        "role_models": _role_models_from_mapping(payload),
    }
    return loop_kwargs, _coerce_bool(payload.get("start_immediately"))


def _orchestration_payload_from_mapping(
    payload: Mapping[str, object],
    *,
    default_to_preset: bool = True,
) -> dict[str, object]:
    name = str(payload.get("name", "")).strip()
    description = str(payload.get("description", "")).strip()
    if not name:
        raise LooporaError("name is required")
    return {
        "name": name,
        "description": description,
        "workflow": _workflow_from_mapping(payload, default_to_preset=default_to_preset),
        "prompt_files": _prompt_files_from_mapping(payload),
        "role_models": _role_models_from_mapping(payload),
    }


def _role_definition_payload_from_mapping(payload: Mapping[str, object]) -> dict[str, object]:
    name = str(payload.get("name", "")).strip()
    description = str(payload.get("description", "")).strip()
    posture_notes = str(payload.get("posture_notes", ""))
    archetype = str(payload.get("archetype", "builder")).strip() or "builder"
    prompt_ref = str(payload.get("prompt_ref", "")).strip()
    prompt_markdown = str(payload.get("prompt_markdown", ""))
    executor_kind = str(payload.get("executor_kind", "codex")).strip() or "codex"
    executor_mode = str(payload.get("executor_mode", "preset")).strip() or "preset"
    command_cli = str(payload.get("command_cli", "")).strip()
    command_args_text = str(payload.get("command_args_text", ""))
    model = str(payload.get("model", "")).strip()
    reasoning_effort = str(payload.get("reasoning_effort", "")).strip()
    if not name:
        raise LooporaError("name is required")
    if not prompt_markdown.strip():
        raise LooporaError("prompt_markdown is required")
    return {
        "name": name,
        "description": description,
        "posture_notes": posture_notes,
        "archetype": archetype,
        "prompt_ref": prompt_ref,
        "prompt_markdown": prompt_markdown,
        "executor_kind": executor_kind,
        "executor_mode": executor_mode,
        "command_cli": command_cli,
        "command_args_text": command_args_text,
        "model": model,
        "reasoning_effort": reasoning_effort,
    }


def _mapping_from_json_field(value: object, *, field_name: str) -> dict[str, object]:
    if isinstance(value, Mapping):
        return dict(value)
    text = str(value or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LooporaError(f"{field_name} must be valid JSON") from exc
    if not isinstance(parsed, Mapping):
        raise LooporaError(f"{field_name} must decode to an object")
    return dict(parsed)


def _workflow_from_mapping(payload: Mapping[str, object], *, default_to_preset: bool = True) -> dict | None:
    workflow = payload.get("workflow")
    if isinstance(workflow, Mapping):
        return dict(workflow)
    workflow_json = _mapping_from_json_field(payload.get("workflow_json"), field_name="workflow_json")
    if workflow_json:
        return workflow_json
    if not default_to_preset:
        return None
    preset = str(payload.get("workflow_preset", "build_first")).strip() or "build_first"
    return build_preset_workflow(preset)


def _workflow_for_spec_template(payload: Mapping[str, object]) -> dict | None:
    workflow = payload.get("workflow")
    if isinstance(workflow, Mapping):
        workflow_mapping = dict(workflow)
        if not workflow_mapping.get("roles") and not workflow_mapping.get("steps"):
            return None
        return normalize_workflow(workflow_mapping)
    raw_workflow_json = payload.get("workflow_json")
    if isinstance(raw_workflow_json, Mapping):
        workflow_mapping = dict(raw_workflow_json)
        if not workflow_mapping.get("roles") and not workflow_mapping.get("steps"):
            return None
        return normalize_workflow(workflow_mapping)
    workflow_json = _mapping_from_json_field(payload.get("workflow_json"), field_name="workflow_json")
    if workflow_json:
        if not workflow_json.get("roles") and not workflow_json.get("steps"):
            return None
        return normalize_workflow(workflow_json)
    preset = str(payload.get("workflow_preset", "")).strip()
    if preset:
        return build_preset_workflow(preset)
    return None


def _prompt_files_from_mapping(payload: Mapping[str, object]) -> dict[str, str]:
    prompt_files = payload.get("prompt_files")
    if isinstance(prompt_files, Mapping):
        return {str(key): str(value) for key, value in dict(prompt_files).items()}
    prompt_files_json = _mapping_from_json_field(payload.get("prompt_files_json"), field_name="prompt_files_json")
    return {str(key): str(value) for key, value in prompt_files_json.items()}


def _role_models_from_mapping(payload: Mapping[str, object]) -> dict[str, str]:
    role_models = payload.get("role_models")
    if isinstance(role_models, Mapping):
        return normalize_role_models(dict(role_models))
    extracted = {}
    for role in ("builder", "inspector", "gatekeeper", "guide", "generator", "tester", "verifier", "challenger"):
        value = str(payload.get(f"role_model_{role}", "")).strip()
        if value:
            extracted[role] = value
    return normalize_role_models(extracted)


def _normalize_loop_form(values: Mapping[str, object] | None) -> dict[str, object]:
    normalized = dict(DEFAULT_LOOP_FORM)
    if not values:
        return normalized
    for key in normalized:
        if key in values:
            normalized[key] = values[key]
    normalized["start_immediately"] = _coerce_bool(normalized.get("start_immediately", True))
    return normalized


def _loop_form_is_pristine(values: Mapping[str, object] | None) -> bool:
    return _canonicalize_loop_form_for_comparison(values) == _canonicalize_loop_form_for_comparison(None)


def _canonicalize_loop_form_for_comparison(values: Mapping[str, object] | None) -> dict[str, object]:
    normalized = _normalize_loop_form(values)
    canonical = dict(normalized)
    for key in canonical:
        value = canonical[key]
        if key == "start_immediately":
            canonical[key] = _coerce_bool(value)
            continue
        if key in {"max_iters", "max_role_retries", "trigger_window", "regression_window"}:
            canonical[key] = _coerce_loop_form_number(value, integer_only=True)
            continue
        if key in {"delta_threshold", "iteration_interval_seconds"}:
            canonical[key] = _coerce_loop_form_number(value, integer_only=False)
            continue
        if isinstance(value, str):
            canonical[key] = value.strip()
    return canonical


def _coerce_loop_form_number(value: object, *, integer_only: bool) -> object:
    if isinstance(value, str) and not value.strip():
        return ""
    try:
        return int(value) if integer_only else float(value)
    except (TypeError, ValueError):
        return value


def _normalize_orchestration_form(values: Mapping[str, object] | None) -> dict[str, object]:
    normalized = dict(DEFAULT_ORCHESTRATION_FORM)
    if not values:
        normalized["workflow_json"] = json.dumps({"version": 1, "preset": "", "roles": [], "steps": []}, ensure_ascii=False, indent=2)
        normalized["prompt_files_json"] = json.dumps({}, ensure_ascii=False, indent=2)
        return normalized
    for key in normalized:
        if key in values:
            normalized[key] = values[key]
    if isinstance(normalized.get("workflow_json"), Mapping):
        normalized["workflow_json"] = json.dumps(normalized["workflow_json"], ensure_ascii=False, indent=2)
    if isinstance(normalized.get("prompt_files_json"), Mapping):
        normalized["prompt_files_json"] = json.dumps(normalized["prompt_files_json"], ensure_ascii=False, indent=2)
    if not str(normalized.get("workflow_json", "")).strip():
        preset_name = str(normalized.get("workflow_preset", "")).strip()
        if preset_name:
            workflow = build_preset_workflow(preset_name)
            normalized["workflow_json"] = json.dumps(workflow, ensure_ascii=False, indent=2)
            normalized["prompt_files_json"] = json.dumps(resolve_prompt_files(workflow), ensure_ascii=False, indent=2)
        else:
            normalized["workflow_json"] = json.dumps({"version": 1, "preset": "", "roles": [], "steps": []}, ensure_ascii=False, indent=2)
            normalized["prompt_files_json"] = json.dumps({}, ensure_ascii=False, indent=2)
    return normalized


def _normalize_role_definition_form(values: Mapping[str, object] | None, *, locale: str = "en") -> dict[str, object]:
    normalized = dict(DEFAULT_ROLE_DEFINITION_FORM)
    normalized["prompt_markdown"] = builtin_prompt_markdown("builder.md", locale=locale)
    if not values:
        return normalized
    for key in normalized:
        if key in values:
            normalized[key] = values[key]
    if "prompt_markdown" not in values:
        archetype = str(normalized.get("archetype", "builder") or "builder")
        normalized["prompt_markdown"] = builtin_prompt_markdown(_builtin_prompt_ref_for_archetype(archetype), locale=locale)
    try:
        profile = executor_profile(str(normalized.get("executor_kind", "codex")))
    except ValueError:
        profile = executor_profile("codex")
    if profile.command_only:
        normalized["executor_mode"] = "command"
    if not str(normalized.get("command_cli", "")).strip():
        normalized["command_cli"] = profile.cli_name
    return normalized


def _normalize_bundle_import_form(values: Mapping[str, object] | None) -> dict[str, object]:
    normalized = dict(DEFAULT_BUNDLE_IMPORT_FORM)
    if not values:
        return normalized
    for key in normalized:
        if key in values:
            normalized[key] = values[key]
    normalized["start_immediately"] = _coerce_bool(normalized.get("start_immediately", True))
    return normalized


def _normalize_bundle_derive_form(values: Mapping[str, object] | None) -> dict[str, object]:
    normalized = dict(DEFAULT_BUNDLE_DERIVE_FORM)
    if not values:
        return normalized
    for key in normalized:
        if key in values:
            normalized[key] = values[key]
    return normalized


def _archetype_ui_copy() -> dict[str, dict[str, str]]:
    return {
        "builder": {
            "summary_zh": "直接推进实现，适合把 spec 和 handoff 落成真实代码与文件改动。",
            "summary_en": "Pushes the implementation forward and turns specs plus handoffs into real code changes.",
            "recommendation_zh": "建议把它放在需要实际修改工作区的位置，并给它明确的主线目标。",
            "recommendation_en": "Use it where the workflow needs actual workspace edits, with a crisp main-path goal.",
            "warning_zh": "",
            "warning_en": "",
            "card_tip_zh": "",
            "card_tip_en": "",
        },
        "inspector": {
            "summary_zh": "收集证据、跑检查、整理事实，适合验证当前产出到底到了什么程度。",
            "summary_en": "Collects evidence, runs checks, and summarizes facts so the workflow knows what is truly working.",
            "recommendation_zh": "建议接在 Builder 之后，优先覆盖最关键、最可复现的用户路径。",
            "recommendation_en": "Usually works best after the Builder, starting with the most critical reproducible user paths.",
            "warning_zh": "",
            "warning_en": "",
            "card_tip_zh": "",
            "card_tip_en": "",
        },
        "gatekeeper": {
            "summary_zh": "负责做放行判断，只根据 checks、证据和风险决定是否通过。",
            "summary_en": "Owns the pass/fail decision and judges readiness strictly from checks, evidence, and risk.",
            "recommendation_zh": "建议只放一个在流程收束位，避免多个最终裁决角色相互打架。",
            "recommendation_en": "Keep one of these near the end of the workflow so there is a single clear final verdict.",
            "warning_zh": "不建议把它当成实现角色使用，它的职责是裁决，不是补做工作。",
            "warning_en": "Do not use it as an implementation role. Its job is to decide, not to compensate for missing work.",
            "card_tip_zh": "Inspector 负责收集证据和跑检查，只回答“现在发生了什么”；GateKeeper 负责基于这些证据做最终放行判断，回答“现在能不能过”。没有 GateKeeper 时，流程里就少了一个专门做通过/不通过裁决的角色。",
            "card_tip_en": "The Inspector gathers evidence and runs checks, answering “what is happening now.” The GateKeeper uses that evidence to make the final pass/fail call, answering “is this ready to pass.” Without a GateKeeper, the workflow loses its dedicated final judge.",
        },
        "guide": {
            "summary_zh": "在停滞、回退或噪音过多时提供新的方向，帮流程恢复有效推进。",
            "summary_en": "Intervenes when progress stalls or gets noisy, then suggests a tighter next direction.",
            "recommendation_zh": "建议放在流程末尾或条件分支里，用来给下一轮提供更高杠杆的突破口。",
            "recommendation_en": "Use it near the end or in recovery branches to generate the next high-leverage move.",
            "warning_zh": "",
            "warning_en": "",
            "card_tip_zh": "",
            "card_tip_en": "",
        },
        "custom": {
            "summary_zh": "最低权限的补充角色，适合做只读分析、专门观察和窄范围建议。",
            "summary_en": "A restricted support role for read-only analysis, specialized observations, and narrow recommendations.",
            "recommendation_zh": "适合安全审计、文案评审、风险盘点这类辅助任务；通常不要让它承担最终放行。",
            "recommendation_en": "Great for sidecar tasks like security review, copy critique, or risk scans; usually not for the final verdict.",
            "warning_zh": "它不能充当最终放行角色；如果选择 custom 执行工具，也只能使用直接命令模式。",
            "warning_en": "It cannot be the final pass/fail role. If you pair it with the custom executor, direct-command mode is required.",
            "card_tip_zh": "",
            "card_tip_en": "",
        },
    }


def _archetype_options() -> list[dict[str, str]]:
    labels = []
    copy = _archetype_ui_copy()
    for archetype in ARCHETYPES:
        item = copy[archetype]
        english_label = "Custom (Restricted)" if archetype == "custom" else display_name_for_archetype(archetype, locale="en")
        if archetype == "custom":
            labels.append(
                {
                    "id": archetype,
                    "label_zh": english_label,
                    "label_en": english_label,
                    **item,
                }
            )
            continue
        labels.append(
            {
                "id": archetype,
                "label_zh": english_label,
                "label_en": english_label,
                **item,
            }
        )
    return labels


def _orchestration_form_values_from_record(orchestration: Mapping[str, object]) -> dict[str, object]:
    workflow = dict(orchestration.get("workflow_json") or {})
    return {
        "name": str(orchestration.get("name", "")),
        "description": str(orchestration.get("description", "")),
        "workflow_preset": str(workflow.get("preset", "")).strip(),
        "workflow_json": json.dumps(workflow, ensure_ascii=False, indent=2),
        "prompt_files_json": json.dumps(orchestration.get("prompt_files_json") or {}, ensure_ascii=False, indent=2),
    }


def _role_definition_form_values_from_record(role_definition: Mapping[str, object], *, locale: str = "en") -> dict[str, object]:
    prompt_ref = str(role_definition.get("prompt_ref", ""))
    prompt_markdown = str(role_definition.get("prompt_markdown", ""))
    if str(role_definition.get("source", "")).strip() == "builtin" and prompt_ref:
        prompt_markdown = builtin_prompt_markdown(prompt_ref, locale=locale)
    return {
        "name": str(role_definition.get("name", "")),
        "description": str(role_definition.get("description", "")),
        "posture_notes": str(role_definition.get("posture_notes", "")),
        "archetype": str(role_definition.get("archetype", "builder") or "builder"),
        "prompt_ref": prompt_ref,
        "prompt_markdown": prompt_markdown,
        "executor_kind": str(role_definition.get("executor_kind", "codex") or "codex"),
        "executor_mode": str(role_definition.get("executor_mode", "preset") or "preset"),
        "command_cli": str(role_definition.get("command_cli", "")),
        "command_args_text": str(role_definition.get("command_args_text", "")),
        "model": str(role_definition.get("model", "")),
        "reasoning_effort": str(role_definition.get("reasoning_effort", "")),
    }


def _builtin_prompt_ref_for_archetype(archetype: str) -> str:
    return "gatekeeper.md" if archetype == "gatekeeper" else f"{archetype}.md"


def _builtin_role_templates(*, locale: str = "en") -> dict[str, dict[str, object]]:
    templates: dict[str, dict[str, object]] = {}
    for archetype in ARCHETYPES:
        prompt_ref = _builtin_prompt_ref_for_archetype(archetype)
        prompt_markdown_by_locale = builtin_prompt_markdown_by_locale(prompt_ref)
        templates[archetype] = {
            "prompt_ref": prompt_ref,
            "prompt_markdown": prompt_markdown_by_locale[normalize_prompt_locale(locale)],
            "prompt_markdown_by_locale": prompt_markdown_by_locale,
        }
    return templates


def _preferred_request_locale(request: Request) -> str:
    return _preferred_locale_from_accept_language(request.headers.get("accept-language"))


def _preferred_locale_from_accept_language(accept_language: str | None) -> str:
    header = str(accept_language or "").strip()
    if not header:
        return "en"

    candidates: list[tuple[float, int, str]] = []
    for position, raw_item in enumerate(header.split(",")):
        item = raw_item.strip()
        if not item:
            continue
        language_tag, *params = [segment.strip() for segment in item.split(";")]
        normalized_tag = str(language_tag or "").strip().lower().replace("_", "-")
        if not normalized_tag:
            continue
        if normalized_tag.startswith("zh"):
            locale = "zh"
        elif normalized_tag.startswith("en"):
            locale = "en"
        else:
            continue

        q_value = 1.0
        for param in params:
            key, sep, value = param.partition("=")
            if sep and key.strip().lower() == "q":
                try:
                    q_value = float(value.strip())
                except ValueError:
                    q_value = 0.0
                break
        if q_value <= 0:
            continue
        candidates.append((-q_value, position, locale))

    if not candidates:
        return "en"

    candidates.sort()
    return candidates[0][2]


def _spec_validation_from_markdown(markdown_text: str) -> dict[str, object]:
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


def _spec_document_payload(spec_path: Path, markdown_text: str) -> dict[str, object]:
    return {
        "ok": True,
        "path": str(spec_path.resolve()),
        "content": markdown_text,
        "rendered_html": render_safe_markdown_html(markdown_text),
        "validation": _spec_validation_from_markdown(markdown_text),
    }


def _decorate_role_definition_overview(role_definition: Mapping[str, object]) -> dict[str, object]:
    executor_kind = str(role_definition.get("executor_kind", "codex") or "codex")
    archetype = str(role_definition.get("archetype", "builder") or "builder")
    template_name = "Custom (Restricted)" if archetype.strip() == "custom" else display_name_for_archetype(
        archetype,
        locale="en",
    )
    archetype_copy = _archetype_ui_copy()[archetype]
    name = str(role_definition.get("name", "")).strip()
    normalized_name = re.sub(r"[^a-z0-9]+", "", name.lower())
    normalized_template = re.sub(r"[^a-z0-9]+", "", template_name.lower())
    return {
        **role_definition,
        "executor_label": executor_profile(executor_kind).label,
        "template_display_name": template_name,
        "show_template_meta": str(role_definition.get("source", "")).strip() == "custom" and normalized_name != normalized_template,
        "summary_zh": archetype_copy["summary_zh"],
        "summary_en": archetype_copy["summary_en"],
        "card_tip_zh": archetype_copy["card_tip_zh"],
        "card_tip_en": archetype_copy["card_tip_en"],
    }


def _build_access_state(*, bind_host: str, bind_port: int, auth_token: str | None) -> dict[str, object]:
    normalized_auth = (auth_token or "").strip() or None
    remote_access_enabled = not _is_loopback_host(bind_host)
    return {
        "bind_host": bind_host,
        "bind_port": bind_port,
        "auth_token": normalized_auth,
        "auth_enabled": bool(normalized_auth),
        "remote_access_enabled": remote_access_enabled,
        "native_dialogs_enabled": not remote_access_enabled,
    }


def _extract_request_token(request: Request) -> str | None:
    bearer = request.headers.get("authorization", "")
    if bearer.lower().startswith("bearer "):
        token = bearer.split(" ", 1)[1].strip()
        if token:
            return token

    header_token = request.headers.get(APP_AUTH_HEADER, "").strip()
    if header_token:
        return header_token

    query_token = request.query_params.get("token", "").strip()
    if query_token:
        return query_token

    cookie_token = request.cookies.get(APP_AUTH_COOKIE, "").strip()
    if cookie_token:
        return cookie_token
    return None


def _is_loopback_host(host: str) -> bool:
    normalized = (host or "").strip().lower()
    if normalized in {"localhost", "127.0.0.1", "::1"}:
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _coerce_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


__all__ = [
    "DEFAULT_BUNDLE_DERIVE_FORM",
    "DEFAULT_BUNDLE_IMPORT_FORM",
    "DEFAULT_LOOP_FORM",
    "DEFAULT_ORCHESTRATION_FORM",
    "DEFAULT_ROLE_DEFINITION_FORM",
    "_archetype_options",
    "_build_access_state",
    "_builtin_role_templates",
    "_coerce_bool",
    "_decorate_role_definition_overview",
    "_extract_request_token",
    "_loop_form_is_pristine",
    "_loop_payload_from_mapping",
    "_normalize_bundle_derive_form",
    "_normalize_bundle_import_form",
    "_normalize_loop_form",
    "_normalize_orchestration_form",
    "_normalize_role_definition_form",
    "_orchestration_form_values_from_record",
    "_orchestration_payload_from_mapping",
    "_preferred_locale_from_accept_language",
    "_preferred_request_locale",
    "_role_definition_form_values_from_record",
    "_role_definition_payload_from_mapping",
    "_spec_document_payload",
    "_workflow_for_spec_template",
]
