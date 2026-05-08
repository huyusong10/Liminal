from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from loopora.alignment_semantics import text_mentions_loop_fit_contradiction
from loopora.executor import validate_extra_cli_args_text
from loopora.specs import SpecError, compile_markdown_spec
from loopora.workflows import (
    WorkflowError,
    default_step_execution_settings,
    normalize_prompt_ref,
    normalize_role_execution_settings,
    normalize_step_inherit_session,
    normalize_step_action_policy,
    normalize_step_inputs,
    normalize_step_on_pass,
    normalize_step_parallel_group,
    normalize_workflow_identifier,
    normalize_workflow_version,
    normalize_workflow_controls,
    validate_workflow_parallel_groups,
)

BUNDLE_VERSION = 1
BUNDLE_DEFAULT_LOOP = {
    "completion_mode": "gatekeeper",
    "executor_kind": "codex",
    "executor_mode": "preset",
    "command_cli": "",
    "command_args_text": "",
    "model": "",
    "reasoning_effort": "",
    "iteration_interval_seconds": 0.0,
    "max_iters": 8,
    "max_role_retries": 2,
    "delta_threshold": 0.005,
    "trigger_window": 4,
    "regression_window": 2,
}
ROLE_DEFINITION_KEY_RE = re.compile(r"[^a-z0-9]+")


class BundleError(ValueError):
    """Raised when a YAML bundle cannot be parsed or normalized."""


def _slugify_bundle_role_key(value: str) -> str:
    normalized = ROLE_DEFINITION_KEY_RE.sub("-", str(value or "").strip().lower()).strip("-")
    return normalized or "role"


def normalize_bundle(payload: Mapping[str, object] | None) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise BundleError("bundle payload must decode to an object")
    raw = dict(payload)
    version = _normalize_bundle_version(raw.get("version"))
    if version != BUNDLE_VERSION:
        raise BundleError(f"unsupported bundle version: {version}")

    metadata = _normalize_bundle_metadata(raw.get("metadata"))
    collaboration_summary = str(raw.get("collaboration_summary", "") or "").strip()
    if not collaboration_summary:
        raise BundleError("bundle collaboration_summary is required")
    loop = _normalize_bundle_loop(raw.get("loop"))
    spec = _normalize_bundle_spec(raw.get("spec"))
    role_definitions = _normalize_bundle_role_definitions(raw.get("role_definitions"))
    workflow = _normalize_bundle_workflow(raw.get("workflow"), role_definitions=role_definitions)
    _validate_bundle_runtime_contract(loop=loop, role_definitions=role_definitions, workflow=workflow)
    return {
        "version": version,
        "metadata": metadata,
        "collaboration_summary": collaboration_summary,
        "loop": loop,
        "spec": spec,
        "role_definitions": role_definitions,
        "workflow": workflow,
    }


def _normalize_bundle_metadata(raw_metadata: object) -> dict[str, Any]:
    if raw_metadata is None:
        metadata = {}
    elif isinstance(raw_metadata, Mapping):
        metadata = dict(raw_metadata)
    else:
        raise BundleError("bundle metadata must be an object")
    name = str(metadata.get("name", "") or "").strip()
    if not name:
        raise BundleError("bundle metadata.name is required")
    revision = _normalize_bundle_integer(
        metadata.get("revision"),
        default=1,
        field_name="bundle metadata.revision",
    )
    if revision < 1:
        raise BundleError("bundle metadata.revision must be >= 1")
    return {
        "bundle_id": str(metadata.get("bundle_id", "") or "").strip(),
        "name": name,
        "description": str(metadata.get("description", "") or "").strip(),
        "source_bundle_id": str(metadata.get("source_bundle_id", "") or "").strip(),
        "revision": revision,
    }


def _normalize_bundle_version(value: object) -> int:
    return _normalize_bundle_integer(value, default=BUNDLE_VERSION, field_name="bundle version")


def _normalize_bundle_integer(value: object, *, default: int, field_name: str) -> int:
    if value is None:
        return default
    if isinstance(value, str) and not value.strip():
        return default
    if isinstance(value, bool):
        raise BundleError(f"{field_name} must be an integer")
    if isinstance(value, float) and not value.is_integer():
        raise BundleError(f"{field_name} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise BundleError(f"{field_name} must be an integer") from exc


def _normalize_bundle_loop(raw_loop: object) -> dict[str, Any]:
    if not isinstance(raw_loop, Mapping):
        raise BundleError("bundle loop must be an object")
    payload = {**BUNDLE_DEFAULT_LOOP, **dict(raw_loop)}
    workdir = str(payload.get("workdir", "") or "").strip()
    if not workdir:
        raise BundleError("bundle loop.workdir is required")
    name = str(payload.get("name", "") or "").strip() or Path(workdir).expanduser().resolve().name
    runtime = _normalize_bundle_loop_runtime(payload)
    return {
        "name": name,
        "workdir": workdir,
        "completion_mode": str(payload.get("completion_mode", "gatekeeper") or "gatekeeper").strip() or "gatekeeper",
        "executor_kind": str(payload.get("executor_kind", "codex") or "codex").strip() or "codex",
        "executor_mode": str(payload.get("executor_mode", "preset") or "preset").strip() or "preset",
        "command_cli": str(payload.get("command_cli", "") or "").strip(),
        "command_args_text": str(payload.get("command_args_text", "") or ""),
        "model": str(payload.get("model", "") or "").strip(),
        "reasoning_effort": str(payload.get("reasoning_effort", "") or "").strip(),
        **runtime,
    }


def _normalize_bundle_loop_runtime(payload: Mapping[str, Any]) -> dict[str, int | float]:
    try:
        iteration_interval_seconds = float(_bundle_numeric_value(payload, "iteration_interval_seconds"))
        max_iters = int(_bundle_numeric_value(payload, "max_iters"))
        max_role_retries = int(_bundle_numeric_value(payload, "max_role_retries"))
        delta_threshold = float(_bundle_numeric_value(payload, "delta_threshold"))
        trigger_window = int(_bundle_numeric_value(payload, "trigger_window"))
        regression_window = int(_bundle_numeric_value(payload, "regression_window"))
    except (TypeError, ValueError, OverflowError) as exc:
        raise BundleError("bundle loop settings must use valid numbers") from exc
    if not math.isfinite(iteration_interval_seconds) or not math.isfinite(delta_threshold):
        raise BundleError("bundle loop settings must use finite numbers")
    if max_iters < 0:
        raise BundleError("bundle loop.max_iters must be >= 0")
    if max_role_retries < 0:
        raise BundleError("bundle loop.max_role_retries must be >= 0")
    if delta_threshold < 0:
        raise BundleError("bundle loop.delta_threshold must be >= 0")
    if trigger_window < 1:
        raise BundleError("bundle loop.trigger_window must be >= 1")
    if regression_window < 1:
        raise BundleError("bundle loop.regression_window must be >= 1")
    if iteration_interval_seconds < 0:
        raise BundleError("bundle loop.iteration_interval_seconds must be >= 0")
    return {
        "iteration_interval_seconds": iteration_interval_seconds,
        "max_iters": max_iters,
        "max_role_retries": max_role_retries,
        "delta_threshold": delta_threshold,
        "trigger_window": trigger_window,
        "regression_window": regression_window,
    }


def _bundle_numeric_value(payload: Mapping[str, Any], key: str) -> object:
    value = payload.get(key, BUNDLE_DEFAULT_LOOP[key])
    if value is None:
        return BUNDLE_DEFAULT_LOOP[key]
    if isinstance(value, str) and not value.strip():
        return BUNDLE_DEFAULT_LOOP[key]
    if isinstance(value, bool):
        raise BundleError("bundle loop settings must use valid numbers")
    return value


def _normalize_bundle_spec(raw_spec: object) -> dict[str, str]:
    if not isinstance(raw_spec, Mapping):
        raise BundleError("bundle spec must be an object")
    markdown = str(dict(raw_spec).get("markdown", "") or "").strip()
    if not markdown:
        raise BundleError("bundle spec.markdown is required")
    try:
        compile_markdown_spec(markdown)
    except SpecError as exc:
        raise BundleError(str(exc)) from exc
    return {"markdown": markdown}


def _normalize_bundle_role_definitions(raw_role_definitions: object) -> list[dict[str, Any]]:
    if not isinstance(raw_role_definitions, list) or not raw_role_definitions:
        raise BundleError("bundle role_definitions must be a non-empty array")
    normalized: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for index, raw_entry in enumerate(raw_role_definitions, start=1):
        normalized.append(_normalize_bundle_role_definition(raw_entry, index=index, seen_keys=seen_keys))
    return normalized


def _normalize_bundle_role_definition(
    raw_entry: object,
    *,
    index: int,
    seen_keys: set[str],
) -> dict[str, Any]:
    if not isinstance(raw_entry, Mapping):
        raise BundleError("bundle role_definitions entries must be objects")
    entry = dict(raw_entry)
    key = _normalize_bundle_role_definition_key(entry, index=index, seen_keys=seen_keys)
    name = _require_bundle_role_definition_text(entry, key=key, field_name="name")
    archetype = _require_bundle_role_definition_text(entry, key=key, field_name="archetype")
    prompt_markdown = _require_bundle_role_definition_text(entry, key=key, field_name="prompt_markdown", strip=False)
    try:
        normalized_archetype = _normalize_bundle_role_archetype(archetype, prompt_markdown=prompt_markdown)
        execution = _normalize_bundle_role_execution(entry)
    except (WorkflowError, ValueError) as exc:
        raise BundleError(str(exc)) from exc
    return {
        "key": key,
        "name": name,
        "description": str(entry.get("description", "") or "").strip(),
        "archetype": normalized_archetype,
        "prompt_ref": _normalize_bundle_role_prompt_ref(entry.get("prompt_ref"), key=key),
        "prompt_markdown": prompt_markdown,
        "posture_notes": str(entry.get("posture_notes", "") or "").strip(),
        **execution,
    }


def _normalize_bundle_role_definition_key(
    entry: Mapping[str, Any],
    *,
    index: int,
    seen_keys: set[str],
) -> str:
    raw_key = str(entry.get("key", "") or entry.get("id", "") or entry.get("name", "") or f"role-{index}")
    key = _slugify_bundle_role_key(raw_key)
    if key in seen_keys:
        raise BundleError(f"duplicate bundle role_definition key: {key}")
    seen_keys.add(key)
    return key


def _require_bundle_role_definition_text(
    entry: Mapping[str, Any],
    *,
    key: str,
    field_name: str,
    strip: bool = True,
) -> str:
    value = str(entry.get(field_name, "") or "")
    normalized = value.strip() if strip else value
    if not normalized.strip():
        raise BundleError(f"bundle role_definition {key} requires {field_name}")
    return normalized


def _normalize_bundle_role_prompt_ref(value: object, *, key: str) -> str:
    prompt_ref = str(value or "").strip()
    if not prompt_ref:
        return f"{key}.md"
    try:
        return normalize_prompt_ref(prompt_ref)
    except WorkflowError as exc:
        raise BundleError(str(exc)) from exc


def _normalize_bundle_role_archetype(archetype: str, *, prompt_markdown: str) -> str:
    from loopora.workflows import normalize_archetype, validate_prompt_markdown

    normalized_archetype = normalize_archetype(archetype)
    validate_prompt_markdown(prompt_markdown, expected_archetype=normalized_archetype)
    return normalized_archetype


def _normalize_bundle_role_execution(entry: Mapping[str, Any]) -> dict[str, str]:
    return normalize_role_execution_settings(
        {
            "executor_kind": entry.get("executor_kind", "codex"),
            "executor_mode": entry.get("executor_mode", "preset"),
            "command_cli": entry.get("command_cli", ""),
            "command_args_text": entry.get("command_args_text", ""),
            "model": entry.get("model", ""),
            "reasoning_effort": entry.get("reasoning_effort", ""),
        }
    )


def _normalize_bundle_workflow(raw_workflow: object, *, role_definitions: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(raw_workflow, Mapping):
        raise BundleError("bundle workflow must be an object")
    payload = dict(raw_workflow)
    raw_roles, raw_steps = _require_bundle_workflow_entries(payload)

    role_keys = {item["key"] for item in role_definitions}
    archetype_by_key = {item["key"]: item["archetype"] for item in role_definitions}
    roles, archetype_lookup = _normalize_bundle_workflow_roles(
        raw_roles,
        role_keys=role_keys,
        archetype_by_key=archetype_by_key,
    )
    steps = _normalize_bundle_workflow_steps(raw_steps, archetype_lookup=archetype_lookup)
    workflow_role_by_id = _bundle_workflow_role_archetypes(archetype_lookup)
    controls = _normalize_bundle_workflow_controls(payload.get("controls"), steps=steps, role_by_id=workflow_role_by_id)
    try:
        version = normalize_workflow_version(payload.get("version"), field_name="bundle workflow version")
    except WorkflowError as exc:
        raise BundleError(str(exc)) from exc
    workflow = {
        "version": version,
        "preset": str(payload.get("preset", "") or "").strip(),
        "collaboration_intent": str(payload.get("collaboration_intent", "") or "").strip(),
        "roles": roles,
        "steps": steps,
    }
    if controls:
        workflow["controls"] = controls
    return workflow


def _require_bundle_workflow_entries(payload: Mapping[str, Any]) -> tuple[list[Any], list[Any]]:
    raw_roles = payload.get("roles")
    raw_steps = payload.get("steps")
    if not isinstance(raw_roles, list) or not raw_roles:
        raise BundleError("bundle workflow.roles must be a non-empty array")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise BundleError("bundle workflow.steps must be a non-empty array")
    return raw_roles, raw_steps


def _normalize_bundle_workflow_roles(
    raw_roles: list[Any],
    *,
    role_keys: set[str],
    archetype_by_key: Mapping[str, str],
) -> tuple[list[dict[str, str]], dict[str, str]]:
    roles: list[dict[str, str]] = []
    seen_role_ids: set[str] = set()
    archetype_lookup: dict[str, str] = {}
    for index, raw_role in enumerate(raw_roles, start=1):
        role = _normalize_bundle_workflow_role(raw_role, index=index, role_keys=role_keys, seen_role_ids=seen_role_ids)
        roles.append({"id": role["id"], "role_definition_key": role["role_definition_key"]})
        archetype_lookup[role["id"]] = archetype_by_key[role["role_definition_key"]]
    return roles, archetype_lookup


def _normalize_bundle_workflow_role(
    raw_role: object,
    *,
    index: int,
    role_keys: set[str],
    seen_role_ids: set[str],
) -> dict[str, str]:
    if not isinstance(raw_role, Mapping):
        raise BundleError("bundle workflow.roles entries must be objects")
    entry = dict(raw_role)
    role_id = _bundle_workflow_identifier(
        entry.get("id") or f"role_{index:03d}",
        field_name="bundle workflow role id",
    )
    if role_id in seen_role_ids:
        raise BundleError(f"duplicate bundle workflow role id: {role_id}")
    seen_role_ids.add(role_id)
    role_key = str(entry.get("role_definition_key", "") or role_id).strip()
    if role_key not in role_keys:
        raise BundleError(f"bundle workflow role {role_id} references unknown role_definition_key: {role_key}")
    return {"id": role_id, "role_definition_key": role_key}


def _normalize_bundle_workflow_steps(
    raw_steps: list[Any],
    *,
    archetype_lookup: Mapping[str, str],
) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    seen_step_ids: set[str] = set()
    for index, raw_step in enumerate(raw_steps, start=1):
        steps.append(
            _normalize_bundle_workflow_step(
                raw_step,
                index=index,
                archetype_lookup=archetype_lookup,
                seen_step_ids=seen_step_ids,
            )
        )
    return steps


def _normalize_bundle_workflow_step(
    raw_step: object,
    *,
    index: int,
    archetype_lookup: Mapping[str, str],
    seen_step_ids: set[str],
) -> dict[str, Any]:
    if not isinstance(raw_step, Mapping):
        raise BundleError("bundle workflow.steps entries must be objects")
    entry = dict(raw_step)
    step_id = _bundle_workflow_identifier(
        entry.get("id") or f"step_{index:03d}",
        field_name="bundle workflow step id",
    )
    if step_id in seen_step_ids:
        raise BundleError(f"duplicate bundle workflow step id: {step_id}")
    seen_step_ids.add(step_id)
    role_id = _bundle_workflow_identifier(entry.get("role_id"), field_name="bundle workflow step role_id")
    if role_id not in archetype_lookup:
        raise BundleError(f"bundle workflow step references unknown role_id: {role_id}")
    return _normalize_bundle_workflow_step_payload(
        entry,
        step_id=step_id,
        role_id=role_id,
        archetype=archetype_lookup[role_id],
    )


def _normalize_bundle_workflow_step_payload(
    entry: Mapping[str, Any],
    *,
    step_id: str,
    role_id: str,
    archetype: str,
) -> dict[str, Any]:
    defaults = default_step_execution_settings(archetype=archetype)
    try:
        on_pass = normalize_step_on_pass(entry.get("on_pass"), archetype=archetype, default=defaults["on_pass"])
        inherit_session = normalize_step_inherit_session(entry.get("inherit_session"), archetype=archetype)
        action_policy = normalize_step_action_policy(
            entry.get("action_policy"),
            archetype=archetype,
            on_pass=on_pass,
        )
        extra_cli_args = str(entry.get("extra_cli_args", "") or "").strip()
        validate_extra_cli_args_text(extra_cli_args)
        parallel_group = normalize_step_parallel_group(entry.get("parallel_group"))
        inputs = normalize_step_inputs(entry.get("inputs"))
    except (WorkflowError, ValueError) as exc:
        raise BundleError(str(exc)) from exc
    step_payload = {
        "id": step_id,
        "role_id": role_id,
        "on_pass": on_pass,
        "model": str(entry.get("model", "") or "").strip(),
        "inherit_session": inherit_session,
        "extra_cli_args": extra_cli_args,
        "action_policy": action_policy,
    }
    if parallel_group:
        step_payload["parallel_group"] = parallel_group
    if inputs:
        step_payload["inputs"] = inputs
    return step_payload


def _bundle_workflow_role_archetypes(archetype_lookup: Mapping[str, str]) -> dict[str, dict[str, str]]:
    return {role_id: {"archetype": archetype} for role_id, archetype in archetype_lookup.items()}


def _normalize_bundle_workflow_controls(
    raw_controls: object,
    *,
    steps: list[dict[str, Any]],
    role_by_id: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    try:
        validate_workflow_parallel_groups(steps, role_by_id)
        return normalize_workflow_controls(raw_controls, role_by_id=role_by_id)
    except WorkflowError as exc:
        raise BundleError(str(exc)) from exc


def _bundle_workflow_identifier(value: object, *, field_name: str) -> str:
    try:
        return normalize_workflow_identifier(value, field_name=field_name)
    except WorkflowError as exc:
        raise BundleError(str(exc)) from exc


def _validate_bundle_runtime_contract(
    *,
    loop: Mapping[str, Any],
    role_definitions: list[dict[str, Any]],
    workflow: Mapping[str, Any],
) -> None:
    completion_mode = str(loop.get("completion_mode", "gatekeeper") or "gatekeeper").strip().lower()
    if completion_mode != "gatekeeper":
        return
    role_key_archetype = {item["key"]: item["archetype"] for item in role_definitions}
    workflow_role_archetype = {
        role["id"]: role_key_archetype.get(role["role_definition_key"], "") for role in workflow.get("roles", []) if isinstance(role, Mapping)
    }
    has_finishing_gatekeeper = any(
        workflow_role_archetype.get(str(step.get("role_id", ""))) == "gatekeeper" and str(step.get("on_pass", "") or "") == "finish_run"
        for step in workflow.get("steps", [])
        if isinstance(step, Mapping)
    )
    if not has_finishing_gatekeeper:
        raise BundleError("gatekeeper completion mode requires a GateKeeper step that can finish the run")


def _semantic_text_is_specific(text: object, *, min_chars: int = 48) -> bool:
    value = str(text or "").strip()
    if len(value) < min_chars:
        return False
    generic_patterns = [
        r"requested behavior",
        r"do the task",
        r"task is done",
        r"\bit works\b",
        r"make it work",
        r"works well",
        r"requested task",
        r"alignment agreement",
        r"按需求完成",
        r"完成任务",
        r"实现需求",
    ]
    lower = value.lower()
    return not any(re.search(pattern, lower) for pattern in generic_patterns)


def _semantic_text_mentions_evidence(text: object) -> bool:
    value = str(text or "").lower()
    evidence_terms = [
        "evidence",
        "proof",
        "verify",
        "verification",
        "test",
        "browser",
        "command",
        "artifact",
        "handoff",
        "blocker",
        "证据",
        "验证",
        "测试",
        "浏览器",
        "命令",
        "产物",
        "交接",
        "阻断",
    ]
    return any(term in value for term in evidence_terms)


def _semantic_text_mentions_evidence_bucket_projection(text: object) -> bool:
    value = str(text or "")
    bucket_patterns = {
        "proven": r"\bproven\b|已证明",
        "weak": r"\bweak\b|弱证据|证据薄弱",
        "unproven": r"\bunproven\b|未证明",
        "blocking": r"\bblocking\b|阻断",
        "residual": r"\bresidual risk\b|残余风险",
    }
    return all(re.search(pattern, value, re.I) for pattern in bucket_patterns.values())


def _semantic_text_mentions_personality_memory_antipattern(text: object) -> bool:
    value = re.sub(r"\s+", " ", str(text or "")).strip().lower()
    if not value:
        return False
    patterns = [
        r"\b(?:global|permanent|always-on|chat-wide)\s+(?:user\s+)?"
        r"(?:persona|personality|preference|preferences|memory|trait|style)\b",
        r"\b(?:persona|personality|preference|preferences|style)\s+(?:memory|profile)\b",
        r"\b(?:remember|store|capture|codify)\s+(?:the\s+)?(?:user's|my)\s+"
        r"(?:persona|personality|preference|preferences|style|traits?)\b",
        r"\balways\s+(?:follow|use|prefer|behave|act|answer)\b.{0,80}\b(?:user|my)\b.{0,80}"
        r"\b(?:persona|personality|preference|preferences|style|trait)\b",
        r"全局(?:人格|偏好|记忆|画像)",
        r"永久(?:人格|偏好|记忆|画像)",
        r"(?:人格|偏好|用户画像|用户特质).{0,8}(?:记忆|长期记住|全局继承)",
        r"记住.{0,12}(?:我的|用户).{0,8}(?:偏好|人格|风格)",
        r"总是.{0,16}(?:按|遵循|使用).{0,12}(?:偏好|人格|风格)",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, value, re.I):
            if _semantic_antipattern_match_is_negated(value, match.start()):
                continue
            return True
    return False


def _semantic_text_mentions_named_loopora_antipattern(text: object) -> bool:
    value = re.sub(r"\s+", " ", str(text or "")).strip().lower()
    if not value:
        return False
    patterns = [
        r"\bprompt[- ]pack\b",
        r"\brole[- ]zoo\b",
        r"\bloop[- ]script\b",
        r"\bbenchmark[- ]grinder\b",
        r"\bchat[- ]wrapper\b",
        r"提示词包|堆提示词|堆角色|循环脚本|刷基准|基准刷分|聊天壳",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, value, re.I):
            if _semantic_antipattern_match_is_negated(value, match.start()):
                continue
            return True
    return False


def _semantic_antipattern_match_is_negated(value: str, start: int) -> bool:
    context = value[max(0, start - 48) : start]
    return bool(
        re.search(
            r"do not|don't|must not|should not|never|avoid|refuse|reject|rather than|instead of|"
            r"\bnot\s+(?:a|an|as)?\s*$|\bno\s+$|不要|不能|不得|不应|不是|拒绝|避免",
            context,
            re.I,
        )
    )


def lint_alignment_bundle_semantics(bundle: Mapping[str, object]) -> list[str]:
    """Return high-signal semantic issues for Web-generated alignment bundles."""

    normalized = normalize_bundle(bundle)
    issues: list[str] = []
    issues.extend(_lint_alignment_standalone_metadata(normalized))
    issues.extend(_lint_alignment_collaboration_summary(normalized.get("collaboration_summary")))
    issues.extend(_lint_alignment_task_scoped_antipatterns(normalized))
    issues.extend(_lint_alignment_loop_fit_contradictions(normalized))
    issues.extend(_lint_alignment_completion_mode(normalized))
    issues.extend(_lint_alignment_evidence_bucket_projection(normalized))
    compiled_spec = compile_markdown_spec(str(normalized["spec"]["markdown"]))
    issues.extend(_lint_alignment_spec_semantics(compiled_spec))
    issues.extend(_lint_alignment_workflow_intent(normalized["workflow"]))
    role_by_key = {item["key"]: item for item in normalized["role_definitions"]}
    used_role_keys = _alignment_workflow_role_keys(normalized["workflow"])
    issues.extend(_lint_alignment_review_builder_inputs(normalized["workflow"], role_by_key=role_by_key))
    issues.extend(_lint_alignment_parallel_review_inputs(normalized["workflow"], role_by_key=role_by_key))
    issues.extend(_lint_alignment_builder_review_inputs(normalized["workflow"], role_by_key=role_by_key))
    issues.extend(_lint_alignment_guide_review_inputs(normalized["workflow"], role_by_key=role_by_key))
    issues.extend(_lint_alignment_builder_guide_inputs(normalized["workflow"], role_by_key=role_by_key))
    issues.extend(_lint_alignment_finishing_gatekeeper_inputs(normalized["workflow"], role_by_key=role_by_key))
    issues.extend(_lint_alignment_long_chain_gatekeeper_inputs(normalized["workflow"], role_by_key=role_by_key))
    issues.extend(_lint_alignment_review_gatekeeper_inputs(normalized["workflow"], role_by_key=role_by_key))
    issues.extend(_lint_alignment_parallel_gatekeeper_inputs(normalized["workflow"], role_by_key=role_by_key))
    issues.extend(_lint_alignment_iteration_memory_inputs(normalized["workflow"], role_by_key=role_by_key))
    issues.extend(_lint_alignment_duplicate_role_responsibilities(role_by_key, used_role_keys=used_role_keys))
    issues.extend(_lint_alignment_role_semantics(role_by_key, used_role_keys=used_role_keys))
    issues.extend(_lint_alignment_gatekeeper_semantics(normalized, role_by_key=role_by_key, used_role_keys=used_role_keys))
    if len(used_role_keys) < 2:
        issues.append("alignment bundle workflow should use at least two roles")
    return issues


def lint_alignment_bundle_generation_text(raw_text: str) -> list[str]:
    """Return raw-text issues for Web compiler generated bundle candidates."""

    issues: list[str] = []
    stripped = str(raw_text or "").strip()
    if not stripped:
        return issues
    non_empty_lines = [line.strip() for line in str(raw_text or "").splitlines() if line.strip()]
    if non_empty_lines and re.match(r"^```(?:yaml|yml)?\s*$", non_empty_lines[0], re.I):
        issues.append("Web alignment generated bundle_yaml must be one raw YAML document, not markdown-fenced output")
    if non_empty_lines and not re.match(r"^version\s*:\s*1(?:\s*(?:#.*)?)?$", non_empty_lines[0]):
        issues.append("Web alignment generated bundle_yaml must start with version: 1")
    issues.extend(lint_alignment_bundle_generation_metadata(raw_text))
    return issues


def lint_alignment_bundle_generation_metadata(raw_text: str) -> list[str]:
    """Return raw-YAML metadata issues for Web compiler generated bundle candidates."""

    try:
        payload = yaml.safe_load(raw_text) or {}
    except yaml.YAMLError:
        return []
    if not isinstance(payload, Mapping):
        return []
    metadata = payload.get("metadata")
    if not isinstance(metadata, Mapping):
        return []
    metadata_keys = {str(key).strip() for key in metadata}
    if "source_bundle_id" not in metadata_keys and "revision" not in metadata_keys:
        return []
    return [
        "Web alignment generated bundles must omit metadata.source_bundle_id and metadata.revision; "
        "source context is temporary and final bundles are standalone candidates"
    ]


def _lint_alignment_standalone_metadata(normalized: Mapping[str, Any]) -> list[str]:
    metadata = normalized.get("metadata") if isinstance(normalized.get("metadata"), Mapping) else {}
    if not str(metadata.get("source_bundle_id", "") or "").strip():
        return []
    return ["Web alignment bundles must not encode metadata.source_bundle_id; source context is temporary and final bundles are standalone candidates"]


def _lint_alignment_evidence_bucket_projection(normalized: Mapping[str, Any]) -> list[str]:
    if _semantic_text_mentions_evidence_bucket_projection(_alignment_bundle_runtime_governance_text(normalized)):
        return []
    return ["alignment bundle must project task verdict evidence into Proven, Weak, Unproven, Blocking, and Residual risk buckets"]


def _lint_alignment_completion_mode(normalized: Mapping[str, Any]) -> list[str]:
    completion_mode = str(normalized["loop"].get("completion_mode", "") or "").strip().lower()
    if completion_mode == "gatekeeper":
        return []
    return ["Web alignment bundles must use gatekeeper completion_mode so task verdict is evidence-based, not only run lifecycle completion"]


def _lint_alignment_task_scoped_antipatterns(normalized: Mapping[str, Any]) -> list[str]:
    text = _alignment_bundle_governance_text(normalized)
    issues: list[str] = []
    if _semantic_text_mentions_named_loopora_antipattern(text):
        issues.append("alignment bundle must not present prompt pack, role zoo, loop script, benchmark grinder, or chat wrapper as Loopora governance")
    if _semantic_text_mentions_personality_memory_antipattern(text):
        issues.append("alignment bundle must stay task-scoped, not personality memory or global preferences")
    return issues


def _lint_alignment_loop_fit_contradictions(normalized: Mapping[str, Any]) -> list[str]:
    if not text_mentions_loop_fit_contradiction(_alignment_bundle_governance_text(normalized)):
        return []
    return ["alignment bundle must not claim a single pass, direct chat, no-new-evidence round, or benchmark-only path is sufficient while compiling a Loop"]


def _alignment_bundle_governance_text(normalized: Mapping[str, Any]) -> str:
    metadata = normalized.get("metadata") if isinstance(normalized.get("metadata"), Mapping) else {}
    loop = normalized.get("loop") if isinstance(normalized.get("loop"), Mapping) else {}
    workflow = normalized.get("workflow") if isinstance(normalized.get("workflow"), Mapping) else {}
    spec = normalized.get("spec") if isinstance(normalized.get("spec"), Mapping) else {}
    parts = [
        str(metadata.get("name", "") or "") if isinstance(metadata, Mapping) else "",
        str(metadata.get("description", "") or "") if isinstance(metadata, Mapping) else "",
        str(normalized.get("collaboration_summary", "") or ""),
        str(loop.get("name", "") or "") if isinstance(loop, Mapping) else "",
        str(spec.get("markdown", "") or "") if isinstance(spec, Mapping) else "",
        str(workflow.get("collaboration_intent", "") or "") if isinstance(workflow, Mapping) else "",
    ]
    for role in normalized.get("role_definitions", []):
        if not isinstance(role, Mapping):
            continue
        parts.extend(
            [
                str(role.get("name", "") or ""),
                str(role.get("description", "") or ""),
                str(role.get("prompt_markdown", "") or ""),
                str(role.get("posture_notes", "") or ""),
            ]
        )
    return "\n".join(parts)


def _alignment_bundle_runtime_governance_text(normalized: Mapping[str, Any]) -> str:
    workflow = normalized.get("workflow") if isinstance(normalized.get("workflow"), Mapping) else {}
    spec = normalized.get("spec") if isinstance(normalized.get("spec"), Mapping) else {}
    parts = [
        str(normalized.get("collaboration_summary", "") or ""),
        str(spec.get("markdown", "") or "") if isinstance(spec, Mapping) else "",
        str(workflow.get("collaboration_intent", "") or "") if isinstance(workflow, Mapping) else "",
    ]
    for role in normalized.get("role_definitions", []):
        if not isinstance(role, Mapping):
            continue
        parts.extend(
            [
                str(role.get("description", "") or ""),
                str(role.get("prompt_markdown", "") or ""),
                str(role.get("posture_notes", "") or ""),
            ]
        )
    return "\n".join(parts)


def _lint_alignment_collaboration_summary(summary: object) -> list[str]:
    if not _semantic_text_is_specific(summary, min_chars=72):
        return ["collaboration_summary must explain the governance story"]
    if not _semantic_text_mentions_evidence(summary):
        return ["collaboration_summary must mention evidence, proof, verification, handoff, or blockers"]
    if not re.search(r"gatekeeper|gate keeper|裁决|阻断|签字|收束", str(summary or ""), re.I):
        return ["collaboration_summary must explain GateKeeper or final judgment posture"]
    return []


def _lint_alignment_spec_semantics(compiled_spec: Mapping[str, Any]) -> list[str]:
    issues: list[str] = []
    if not _semantic_text_is_specific(compiled_spec.get("goal"), min_chars=72):
        issues.append("spec Task must describe the concrete user-facing task")
    issues.extend(_lint_alignment_spec_contract_sections(compiled_spec))
    return issues


def _lint_alignment_spec_contract_sections(compiled_spec: Mapping[str, Any]) -> list[str]:
    return [
        *_lint_alignment_done_when_semantics(compiled_spec),
        *_lint_alignment_success_and_fake_done_semantics(compiled_spec),
        *_lint_alignment_evidence_and_risk_semantics(compiled_spec),
    ]


def _lint_alignment_done_when_semantics(compiled_spec: Mapping[str, Any]) -> list[str]:
    issues: list[str] = []
    if not compiled_spec.get("checks"):
        issues.append("spec must include at least one Done When bullet")
    return issues


def _lint_alignment_success_and_fake_done_semantics(compiled_spec: Mapping[str, Any]) -> list[str]:
    issues: list[str] = []
    if not compiled_spec.get("success_surface"):
        issues.append("spec must include at least one Success Surface bullet")
    if not compiled_spec.get("fake_done_states"):
        issues.append("spec must include at least one Fake Done bullet")
    return issues


def _lint_alignment_evidence_and_risk_semantics(compiled_spec: Mapping[str, Any]) -> list[str]:
    issues: list[str] = []
    if not compiled_spec.get("evidence_preferences"):
        issues.append("spec must include at least one Evidence Preferences bullet")
    if not str(compiled_spec.get("residual_risk", "") or "").strip():
        issues.append("spec must include Residual Risk guidance")
    return issues


def _lint_alignment_workflow_intent(workflow: Mapping[str, Any]) -> list[str]:
    intent = workflow.get("collaboration_intent", "")
    issues: list[str] = []
    if not str(intent or "").strip():
        return ["workflow.collaboration_intent is required"]
    if not _semantic_text_is_specific(intent, min_chars=64):
        issues.append("workflow.collaboration_intent must explain the task-specific judgment order")
    return issues


def _lint_alignment_parallel_review_inputs(
    workflow: Mapping[str, Any],
    *,
    role_by_key: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    steps = [step for step in workflow.get("steps", []) if isinstance(step, Mapping)]
    workflow_role_archetype = _alignment_workflow_role_archetype(workflow, role_by_key=role_by_key)
    workflow_role_key = _alignment_workflow_role_definition_key(workflow)
    review_steps_by_group: dict[str, list[tuple[str, str, tuple[str, ...]]]] = {}
    issues: list[str] = []
    for step in steps:
        step_id = str(step.get("id", "") or "").strip()
        parallel_group = str(step.get("parallel_group", "") or "").strip()
        if not parallel_group:
            continue
        role_id = str(step.get("role_id", "") or "")
        if workflow_role_archetype.get(role_id) not in {"inspector", "custom"}:
            continue
        inputs = step.get("inputs") if isinstance(step.get("inputs"), Mapping) else {}
        handoffs_from = (inputs.get("handoffs_from") if isinstance(inputs, Mapping) else []) or []
        handoff_ids = tuple(sorted(str(handoff or "").strip() for handoff in handoffs_from if str(handoff or "").strip()))
        review_steps_by_group.setdefault(parallel_group, []).append((step_id, workflow_role_key.get(role_id, ""), handoff_ids))
        if not any(str(handoff or "").strip() for handoff in handoffs_from):
            issues.append("parallel review step must name upstream handoffs in inputs.handoffs_from: " + step_id)
        if not _step_evidence_query_mentions_archetypes(step, {"builder"}):
            issues.append("parallel review step must query Builder evidence in inputs.evidence_query: " + step_id)
    for review_steps in review_steps_by_group.values():
        role_keys = [role_key for _, role_key, _ in review_steps]
        if len(role_keys) > 1 and len(set(role_keys)) < len(role_keys):
            issues.append("parallel review steps must use distinct role_definition_key values: " + ", ".join(step_id for step_id, _, _ in review_steps))
        handoff_sets = [handoffs for _, _, handoffs in review_steps if handoffs]
        if len(handoff_sets) > 1 and len(set(handoff_sets)) > 1:
            issues.append("parallel review steps must read the same upstream handoffs: " + ", ".join(step_id for step_id, _, _ in review_steps))
        role_texts = [_parallel_review_role_text(role_by_key.get(role_key)) for role_key in role_keys]
        if len(role_texts) > 1 and len(set(role_texts)) < len(role_texts):
            issues.append("parallel review role_definitions must have responsibility-specific prompt and posture: " + ", ".join(role_keys))
    return issues


def _lint_alignment_iteration_memory_inputs(
    workflow: Mapping[str, Any],
    *,
    role_by_key: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    steps = [step for step in workflow.get("steps", []) if isinstance(step, Mapping)]
    workflow_role_archetype = _alignment_workflow_role_archetype(workflow, role_by_key=role_by_key)
    issues: list[str] = []
    issues.extend(_parallel_review_iteration_memory_issues(steps, workflow_role_archetype=workflow_role_archetype))
    issues.extend(_guide_review_iteration_memory_issues(steps, workflow_role_archetype=workflow_role_archetype))
    issues.extend(_builder_review_iteration_memory_issues(steps, workflow_role_archetype=workflow_role_archetype))
    issues.extend(_builder_guide_iteration_memory_issues(steps, workflow_role_archetype=workflow_role_archetype))
    return issues


def _parallel_review_iteration_memory_issues(
    steps: list[Mapping[str, Any]],
    *,
    workflow_role_archetype: Mapping[str, str],
) -> list[str]:
    issues: list[str] = []
    for step in steps:
        step_id = str(step.get("id", "") or "").strip()
        role_id = str(step.get("role_id", "") or "")
        if not str(step.get("parallel_group", "") or "").strip():
            continue
        if workflow_role_archetype.get(role_id) not in {"inspector", "custom"}:
            continue
        if not _step_declares_iteration_memory(step):
            issues.append("parallel review step must declare inputs.iteration_memory so cross-iteration evidence flow is explicit: " + step_id)
    return issues


def _guide_review_iteration_memory_issues(
    steps: list[Mapping[str, Any]],
    *,
    workflow_role_archetype: Mapping[str, str],
) -> list[str]:
    issues: list[str] = []
    for index, step in enumerate(steps):
        if workflow_role_archetype.get(str(step.get("role_id", "") or "")) != "guide":
            continue
        review_steps = _review_steps_since_latest_builder(
            steps[:index],
            workflow_role_archetype=workflow_role_archetype,
            include_guides=False,
        )
        if review_steps and not _step_declares_iteration_memory(step):
            issues.append(
                "Guide step after review must declare inputs.iteration_memory so repair guidance can use prior iteration evidence explicitly: "
                + str(step.get("id", "") or "").strip()
            )
    return issues


def _builder_review_iteration_memory_issues(
    steps: list[Mapping[str, Any]],
    *,
    workflow_role_archetype: Mapping[str, str],
) -> list[str]:
    review_steps_since_builder: list[str] = []
    guide_seen_since_builder = False
    issues: list[str] = []
    for step in steps:
        step_id = str(step.get("id", "") or "").strip()
        archetype = workflow_role_archetype.get(str(step.get("role_id", "") or ""))
        if archetype in {"inspector", "custom"}:
            review_steps_since_builder.append(step_id)
            continue
        if archetype == "guide":
            guide_seen_since_builder = True
            continue
        if archetype != "builder":
            continue
        if review_steps_since_builder and not guide_seen_since_builder and not _step_declares_iteration_memory(step):
            issues.append(
                "Builder step after review must declare inputs.iteration_memory so evidence-first repair does not rely on ambient context: " + step_id
            )
        review_steps_since_builder = []
        guide_seen_since_builder = False
    return issues


def _builder_guide_iteration_memory_issues(
    steps: list[Mapping[str, Any]],
    *,
    workflow_role_archetype: Mapping[str, str],
) -> list[str]:
    guide_seen_since_builder = False
    issues: list[str] = []
    for step in steps:
        step_id = str(step.get("id", "") or "").strip()
        archetype = workflow_role_archetype.get(str(step.get("role_id", "") or ""))
        if archetype == "guide":
            guide_seen_since_builder = True
            continue
        if archetype != "builder":
            continue
        if guide_seen_since_builder and not _step_declares_iteration_memory(step):
            issues.append("Builder step after Guide must declare inputs.iteration_memory so repair pass does not rely on ambient context: " + step_id)
        guide_seen_since_builder = False
    return issues


def _step_declares_iteration_memory(step: Mapping[str, Any]) -> bool:
    inputs = step.get("inputs") if isinstance(step.get("inputs"), Mapping) else {}
    return bool(str(inputs.get("iteration_memory", "") if isinstance(inputs, Mapping) else "").strip())


def _lint_alignment_review_builder_inputs(
    workflow: Mapping[str, Any],
    *,
    role_by_key: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    steps = [step for step in workflow.get("steps", []) if isinstance(step, Mapping)]
    workflow_role_archetype = _alignment_workflow_role_archetype(workflow, role_by_key=role_by_key)
    previous_builder_steps: list[str] = []
    issues: list[str] = []
    for step in steps:
        step_id = str(step.get("id", "") or "").strip()
        role_id = str(step.get("role_id", "") or "")
        archetype = workflow_role_archetype.get(role_id)
        if archetype == "builder":
            previous_builder_steps.append(step_id)
            continue
        if archetype not in {"inspector", "custom"} or not previous_builder_steps:
            continue
        inputs = step.get("inputs") if isinstance(step.get("inputs"), Mapping) else {}
        handoffs_from = {str(handoff or "").strip() for handoff in (inputs.get("handoffs_from") if isinstance(inputs, Mapping) else []) or []}
        if not handoffs_from.intersection(previous_builder_steps):
            issues.append("review step after Builder must name a Builder handoff in inputs.handoffs_from: " + step_id)
        if not _step_evidence_query_mentions_archetypes(step, {"builder"}):
            issues.append("review step after Builder must query Builder evidence in inputs.evidence_query: " + step_id)
    return issues


def _parallel_review_role_text(role: Mapping[str, Any] | None) -> str:
    if not role:
        return ""
    value = "\n".join(
        [
            str(role.get("prompt_markdown", "") or ""),
            str(role.get("posture_notes", "") or ""),
        ]
    )
    return re.sub(r"\s+", " ", value).strip().lower()


def _lint_alignment_guide_review_inputs(
    workflow: Mapping[str, Any],
    *,
    role_by_key: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    steps = [step for step in workflow.get("steps", []) if isinstance(step, Mapping)]
    workflow_role_archetype = _alignment_workflow_role_archetype(workflow, role_by_key=role_by_key)
    issues: list[str] = []
    for index, step in enumerate(steps):
        if workflow_role_archetype.get(str(step.get("role_id", "") or "")) != "guide":
            continue
        review_steps = _review_steps_since_latest_builder(
            steps[:index],
            workflow_role_archetype=workflow_role_archetype,
            include_guides=False,
        )
        if not review_steps:
            continue
        step_id = str(step.get("id", "") or "").strip()
        inputs = step.get("inputs") if isinstance(step.get("inputs"), Mapping) else {}
        handoffs_from = {str(handoff or "").strip() for handoff in (inputs.get("handoffs_from") if isinstance(inputs, Mapping) else []) or []}
        missing_handoffs = [review_step_id for review_step_id, _ in review_steps if review_step_id not in handoffs_from]
        if missing_handoffs:
            issues.append("Guide step after review must include review handoffs in inputs.handoffs_from: " + step_id)
        missing_archetypes = _step_missing_evidence_query_archetypes(
            step,
            {archetype for _, archetype in review_steps},
        )
        if missing_archetypes:
            issues.append("Guide step after review must query review evidence in inputs.evidence_query: " + ", ".join(missing_archetypes))
    return issues


def _lint_alignment_builder_review_inputs(
    workflow: Mapping[str, Any],
    *,
    role_by_key: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    steps = [step for step in workflow.get("steps", []) if isinstance(step, Mapping)]
    workflow_role_archetype = _alignment_workflow_role_archetype(workflow, role_by_key=role_by_key)
    review_steps_since_builder: list[str] = []
    guide_seen_since_builder = False
    issues: list[str] = []
    for step in steps:
        step_id = str(step.get("id", "") or "").strip()
        archetype = workflow_role_archetype.get(str(step.get("role_id", "") or ""))
        if archetype in {"inspector", "custom"}:
            review_steps_since_builder.append(step_id)
            continue
        if archetype == "guide":
            guide_seen_since_builder = True
            continue
        if archetype != "builder":
            continue
        if review_steps_since_builder and not guide_seen_since_builder:
            inputs = step.get("inputs") if isinstance(step.get("inputs"), Mapping) else {}
            handoffs_from = {str(handoff or "").strip() for handoff in (inputs.get("handoffs_from") if isinstance(inputs, Mapping) else []) or []}
            missing = [review_step_id for review_step_id in review_steps_since_builder if review_step_id not in handoffs_from]
            if missing:
                issues.append("Builder step after review must include review handoffs in inputs.handoffs_from: " + step_id)
        review_steps_since_builder = []
        guide_seen_since_builder = False
    return issues


def _lint_alignment_builder_guide_inputs(
    workflow: Mapping[str, Any],
    *,
    role_by_key: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    steps = [step for step in workflow.get("steps", []) if isinstance(step, Mapping)]
    workflow_role_archetype = _alignment_workflow_role_archetype(workflow, role_by_key=role_by_key)
    guide_steps_since_builder: list[str] = []
    issues: list[str] = []
    for step in steps:
        step_id = str(step.get("id", "") or "").strip()
        archetype = workflow_role_archetype.get(str(step.get("role_id", "") or ""))
        if archetype == "guide":
            guide_steps_since_builder.append(step_id)
            continue
        if archetype != "builder":
            continue
        if not guide_steps_since_builder:
            continue
        inputs = step.get("inputs") if isinstance(step.get("inputs"), Mapping) else {}
        handoffs_from = {str(handoff or "").strip() for handoff in (inputs.get("handoffs_from") if isinstance(inputs, Mapping) else []) or []}
        if not handoffs_from.intersection(guide_steps_since_builder):
            issues.append("Builder step after Guide must name a Guide handoff in inputs.handoffs_from: " + step_id)
        guide_steps_since_builder = []
    return issues


def _lint_alignment_finishing_gatekeeper_inputs(
    workflow: Mapping[str, Any],
    *,
    role_by_key: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    workflow_role_archetype = _alignment_workflow_role_archetype(workflow, role_by_key=role_by_key)
    issues: list[str] = []
    for step in workflow.get("steps", []):
        if not isinstance(step, Mapping):
            continue
        if workflow_role_archetype.get(str(step.get("role_id", "") or "")) != "gatekeeper":
            continue
        if str(step.get("on_pass", "") or "") != "finish_run":
            continue
        step_id = str(step.get("id", "") or "").strip()
        inputs = step.get("inputs") if isinstance(step.get("inputs"), Mapping) else {}
        handoffs_from = (inputs.get("handoffs_from") if isinstance(inputs, Mapping) else []) or []
        if not any(str(handoff or "").strip() for handoff in handoffs_from):
            issues.append("finishing GateKeeper step must name upstream handoffs in inputs.handoffs_from: " + step_id)
        if not (isinstance(inputs, Mapping) and inputs.get("evidence_query")):
            issues.append("finishing GateKeeper step must query upstream evidence in inputs.evidence_query: " + step_id)
    return issues


def _lint_alignment_review_gatekeeper_inputs(
    workflow: Mapping[str, Any],
    *,
    role_by_key: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    steps = [step for step in workflow.get("steps", []) if isinstance(step, Mapping)]
    workflow_role_archetype = _alignment_workflow_role_archetype(workflow, role_by_key=role_by_key)
    issues: list[str] = []
    for index, step in enumerate(steps):
        role_id = str(step.get("role_id", "") or "")
        if workflow_role_archetype.get(role_id) != "gatekeeper":
            continue
        if str(step.get("on_pass", "") or "") != "finish_run":
            continue
        review_steps = _review_steps_since_latest_builder(
            steps[:index],
            workflow_role_archetype=workflow_role_archetype,
        )
        if not review_steps:
            continue
        inputs = step.get("inputs") if isinstance(step.get("inputs"), Mapping) else {}
        handoffs_from = {str(handoff or "").strip() for handoff in (inputs.get("handoffs_from") if isinstance(inputs, Mapping) else []) or []}
        missing_handoffs = [step_id for step_id, _ in review_steps if step_id not in handoffs_from]
        if missing_handoffs:
            issues.append("finishing GateKeeper after review must include review handoffs in inputs.handoffs_from: " + ", ".join(missing_handoffs))
        missing_archetypes = _step_missing_evidence_query_archetypes(
            step,
            {archetype for _, archetype in review_steps},
        )
        if missing_archetypes:
            issues.append("finishing GateKeeper after review must query review evidence in inputs.evidence_query: " + ", ".join(missing_archetypes))
    return issues


def _lint_alignment_long_chain_gatekeeper_inputs(
    workflow: Mapping[str, Any],
    *,
    role_by_key: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    steps = [step for step in workflow.get("steps", []) if isinstance(step, Mapping)]
    workflow_role_archetype = _alignment_workflow_role_archetype(workflow, role_by_key=role_by_key)
    issues: list[str] = []
    for index, step in enumerate(steps):
        role_id = str(step.get("role_id", "") or "")
        if workflow_role_archetype.get(role_id) != "gatekeeper":
            continue
        if str(step.get("on_pass", "") or "") != "finish_run":
            continue
        prior_steps = steps[:index]
        prior_builder_steps = [
            str(prior_step.get("id", "") or "").strip()
            for prior_step in prior_steps
            if workflow_role_archetype.get(str(prior_step.get("role_id", "") or "")) == "builder"
        ]
        if len(prior_builder_steps) < 2:
            continue
        prior_governance_handoffs = {
            str(prior_step.get("id", "") or "").strip()
            for prior_step in prior_steps
            if workflow_role_archetype.get(str(prior_step.get("role_id", "") or "")) in {"inspector", "custom", "guide"}
        }
        prior_governance_handoffs.update(prior_builder_steps[:-1])
        inputs = step.get("inputs") if isinstance(step.get("inputs"), Mapping) else {}
        handoffs_from = {str(handoff or "").strip() for handoff in (inputs.get("handoffs_from") if isinstance(inputs, Mapping) else []) or []}
        if not handoffs_from.intersection(prior_governance_handoffs):
            issues.append(
                "long-chain GateKeeper must include an earlier phase, review, or Guide handoff in inputs.handoffs_from: "
                + str(step.get("id", "") or "").strip()
            )
    return issues


def _review_steps_since_latest_builder(
    previous_steps: list[Mapping[str, Any]],
    *,
    workflow_role_archetype: Mapping[str, str],
    include_guides: bool = True,
) -> list[tuple[str, str]]:
    last_builder_index = -1
    for index, step in enumerate(previous_steps):
        if workflow_role_archetype.get(str(step.get("role_id", "") or "")) == "builder":
            last_builder_index = index
    review_steps: list[tuple[str, str]] = []
    review_archetypes = {"inspector", "custom", "guide"} if include_guides else {"inspector", "custom"}
    for step in previous_steps[last_builder_index + 1 :]:
        archetype = workflow_role_archetype.get(str(step.get("role_id", "") or ""))
        if archetype not in review_archetypes:
            continue
        step_id = str(step.get("id", "") or "").strip()
        if step_id:
            review_steps.append((step_id, archetype))
    return review_steps


def _lint_alignment_parallel_gatekeeper_inputs(
    workflow: Mapping[str, Any],
    *,
    role_by_key: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    steps = [step for step in workflow.get("steps", []) if isinstance(step, Mapping)]
    workflow_role_archetype = _alignment_workflow_role_archetype(workflow, role_by_key=role_by_key)
    parallel_review_steps = [
        (
            str(step.get("id", "") or "").strip(),
            workflow_role_archetype.get(str(step.get("role_id", "") or "")),
        )
        for step in steps
        if str(step.get("parallel_group", "") or "").strip() and workflow_role_archetype.get(str(step.get("role_id", "") or "")) in {"inspector", "custom"}
    ]
    parallel_review_step_ids = [
        str(step.get("id", "") or "").strip()
        for step in steps
        if str(step.get("parallel_group", "") or "").strip() and workflow_role_archetype.get(str(step.get("role_id", "") or "")) in {"inspector", "custom"}
    ]
    if not parallel_review_step_ids:
        return []
    issues: list[str] = []
    for step in steps:
        if workflow_role_archetype.get(str(step.get("role_id", "") or "")) != "gatekeeper":
            continue
        if str(step.get("on_pass", "") or "") != "finish_run":
            continue
        inputs = step.get("inputs") if isinstance(step.get("inputs"), Mapping) else {}
        handoffs_from = {str(handoff or "").strip() for handoff in (inputs.get("handoffs_from") if isinstance(inputs, Mapping) else []) or []}
        missing = [step_id for step_id in parallel_review_step_ids if step_id not in handoffs_from]
        if missing:
            issues.append("GateKeeper step must include every parallel review handoff in inputs.handoffs_from: " + ", ".join(missing))
        expected_archetypes = {"builder", *(archetype for _, archetype in parallel_review_steps if archetype)}
        missing_archetypes = _step_missing_evidence_query_archetypes(step, expected_archetypes)
        if missing_archetypes:
            issues.append("GateKeeper step must query Builder and parallel review evidence in inputs.evidence_query: " + ", ".join(missing_archetypes))
    return issues


def _step_evidence_query_mentions_archetypes(step: Mapping[str, Any], expected_archetypes: set[str]) -> bool:
    return not _step_missing_evidence_query_archetypes(step, expected_archetypes)


def _step_missing_evidence_query_archetypes(step: Mapping[str, Any], expected_archetypes: set[str]) -> list[str]:
    inputs = step.get("inputs") if isinstance(step.get("inputs"), Mapping) else {}
    evidence_query = inputs.get("evidence_query") if isinstance(inputs, Mapping) else {}
    archetypes = evidence_query.get("archetypes") if isinstance(evidence_query, Mapping) else []
    actual = {str(archetype or "").strip().lower() for archetype in archetypes or []}
    return sorted(expected_archetypes.difference(actual))


def _alignment_workflow_role_archetype(
    workflow: Mapping[str, Any],
    *,
    role_by_key: Mapping[str, Mapping[str, Any]],
) -> dict[str, str]:
    return {
        str(role.get("id", "") or ""): str(role_by_key.get(str(role.get("role_definition_key", "") or ""), {}).get("archetype", "") or "")
        for role in workflow.get("roles", [])
        if isinstance(role, Mapping)
    }


def _alignment_workflow_role_definition_key(workflow: Mapping[str, Any]) -> dict[str, str]:
    return {str(role.get("id", "") or ""): str(role.get("role_definition_key", "") or "") for role in workflow.get("roles", []) if isinstance(role, Mapping)}


def _alignment_workflow_role_keys(workflow: Mapping[str, Any]) -> list[object]:
    return [role.get("role_definition_key", "") for role in workflow.get("roles", []) if isinstance(role, Mapping)]


def _lint_alignment_role_semantics(
    role_by_key: Mapping[str, Mapping[str, Any]],
    *,
    used_role_keys: list[object],
) -> list[str]:
    issues: list[str] = []
    for role_key in used_role_keys:
        role = role_by_key.get(str(role_key))
        if role is None:
            continue
        if _alignment_role_name_is_generic(role):
            issues.append(f"role_definition {role['key']} must use a task-specific role name")
        if not str(role.get("posture_notes", "") or "").strip():
            issues.append(f"role_definition {role['key']} must include task-scoped posture_notes")
    return issues


def _lint_alignment_duplicate_role_responsibilities(
    role_by_key: Mapping[str, Mapping[str, Any]],
    *,
    used_role_keys: list[object],
) -> list[str]:
    responsibilities: dict[tuple[str, str], list[str]] = {}
    for raw_key in dict.fromkeys(str(key) for key in used_role_keys):
        role = role_by_key.get(raw_key)
        if not role:
            continue
        archetype = str(role.get("archetype") or "").strip()
        role_text = _parallel_review_role_text(role)
        if not archetype or not role_text:
            continue
        responsibilities.setdefault((archetype, role_text), []).append(raw_key)
    return [
        "role_definitions must have distinct task evidence responsibilities: " + ", ".join(role_keys)
        for role_keys in responsibilities.values()
        if len(role_keys) > 1
    ]


def _alignment_role_name_is_generic(role: Mapping[str, Any]) -> bool:
    name = re.sub(r"\s+", " ", str(role.get("name", "") or "")).strip().lower()
    if name in {
        "builder",
        "generator",
        "inspector",
        "tester",
        "gatekeeper",
        "gate keeper",
        "verifier",
        "guide",
        "challenger",
        "custom",
    }:
        return True
    return bool(
        re.fullmatch(
            r"(?:builder|generator|inspector|tester|gatekeeper|gate keeper|verifier|guide|challenger|agent|role)[\s#_-]*\d+",
            name,
        )
    )


def _lint_alignment_gatekeeper_semantics(
    normalized: Mapping[str, Any],
    *,
    role_by_key: Mapping[str, Mapping[str, Any]],
    used_role_keys: list[object],
) -> list[str]:
    if str(normalized["loop"].get("completion_mode", "") or "").strip().lower() != "gatekeeper":
        return []
    issues: list[str] = []
    archetypes = {role_by_key[str(role_key)]["archetype"] for role_key in used_role_keys if str(role_key) in role_by_key}
    if "gatekeeper" not in archetypes:
        issues.append("gatekeeper completion mode requires a GateKeeper role")
    return issues


def read_bundle_file_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise BundleError("bundle file must be UTF-8 encoded YAML") from exc


def load_bundle_file(path: Path) -> dict[str, Any]:
    raw_text = read_bundle_file_text(path)
    return load_bundle_text(raw_text)


def load_bundle_text(raw_text: str) -> dict[str, Any]:
    try:
        payload = yaml.safe_load(raw_text) or {}
    except yaml.YAMLError as exc:
        raise BundleError(f"invalid bundle YAML: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise BundleError("bundle YAML must decode to an object")
    return normalize_bundle(payload)


def bundle_to_yaml(bundle: Mapping[str, object]) -> str:
    normalized = normalize_bundle(bundle)
    export_payload = json.loads(json.dumps(normalized, ensure_ascii=False))
    metadata = export_payload.get("metadata")
    if isinstance(metadata, dict):
        metadata.pop("source_bundle_id", None)
        metadata.pop("revision", None)
    return yaml.safe_dump(
        export_payload,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )
