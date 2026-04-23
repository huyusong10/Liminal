from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from loopora.workflows import (
    WorkflowError,
    default_step_execution_settings,
    normalize_prompt_ref,
    normalize_role_execution_settings,
    normalize_step_inherit_session,
    normalize_step_on_pass,
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
    version = int(raw.get("version", BUNDLE_VERSION) or BUNDLE_VERSION)
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
    return {
        "bundle_id": str(metadata.get("bundle_id", "") or "").strip(),
        "name": name,
        "description": str(metadata.get("description", "") or "").strip(),
        "source_bundle_id": str(metadata.get("source_bundle_id", "") or "").strip(),
        "revision": int(metadata.get("revision", 1) or 1),
    }


def _normalize_bundle_loop(raw_loop: object) -> dict[str, Any]:
    if not isinstance(raw_loop, Mapping):
        raise BundleError("bundle loop must be an object")
    payload = {**BUNDLE_DEFAULT_LOOP, **dict(raw_loop)}
    workdir = str(payload.get("workdir", "") or "").strip()
    if not workdir:
        raise BundleError("bundle loop.workdir is required")
    name = str(payload.get("name", "") or "").strip() or Path(workdir).expanduser().resolve().name
    try:
        iteration_interval_seconds = float(payload.get("iteration_interval_seconds", 0.0) or 0.0)
        max_iters = int(payload.get("max_iters", 8) or 8)
        max_role_retries = int(payload.get("max_role_retries", 2) or 2)
        delta_threshold = float(payload.get("delta_threshold", 0.005) or 0.005)
        trigger_window = int(payload.get("trigger_window", 4) or 4)
        regression_window = int(payload.get("regression_window", 2) or 2)
    except (TypeError, ValueError) as exc:
        raise BundleError("bundle loop settings must use valid numbers") from exc
    if max_iters < 0:
        raise BundleError("bundle loop.max_iters must be >= 0")
    if max_role_retries < 0:
        raise BundleError("bundle loop.max_role_retries must be >= 0")
    if trigger_window < 1:
        raise BundleError("bundle loop.trigger_window must be >= 1")
    if regression_window < 1:
        raise BundleError("bundle loop.regression_window must be >= 1")
    if iteration_interval_seconds < 0:
        raise BundleError("bundle loop.iteration_interval_seconds must be >= 0")
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
        "iteration_interval_seconds": iteration_interval_seconds,
        "max_iters": max_iters,
        "max_role_retries": max_role_retries,
        "delta_threshold": delta_threshold,
        "trigger_window": trigger_window,
        "regression_window": regression_window,
    }


def _normalize_bundle_spec(raw_spec: object) -> dict[str, str]:
    if not isinstance(raw_spec, Mapping):
        raise BundleError("bundle spec must be an object")
    markdown = str(dict(raw_spec).get("markdown", "") or "").strip()
    if not markdown:
        raise BundleError("bundle spec.markdown is required")
    return {"markdown": markdown}


def _normalize_bundle_role_definitions(raw_role_definitions: object) -> list[dict[str, Any]]:
    if not isinstance(raw_role_definitions, list) or not raw_role_definitions:
        raise BundleError("bundle role_definitions must be a non-empty array")
    normalized: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for index, raw_entry in enumerate(raw_role_definitions, start=1):
        if not isinstance(raw_entry, Mapping):
            raise BundleError("bundle role_definitions entries must be objects")
        entry = dict(raw_entry)
        raw_key = str(entry.get("key", "") or entry.get("id", "") or entry.get("name", "") or f"role-{index}")
        key = _slugify_bundle_role_key(raw_key)
        if key in seen_keys:
            raise BundleError(f"duplicate bundle role_definition key: {key}")
        seen_keys.add(key)
        name = str(entry.get("name", "") or "").strip()
        if not name:
            raise BundleError(f"bundle role_definition {key} requires name")
        archetype = str(entry.get("archetype", "") or "").strip()
        if not archetype:
            raise BundleError(f"bundle role_definition {key} requires archetype")
        prompt_markdown = str(entry.get("prompt_markdown", "") or "")
        if not prompt_markdown.strip():
            raise BundleError(f"bundle role_definition {key} requires prompt_markdown")
        prompt_ref = str(entry.get("prompt_ref", "") or "").strip()
        if prompt_ref:
            try:
                prompt_ref = normalize_prompt_ref(prompt_ref)
            except WorkflowError as exc:
                raise BundleError(str(exc)) from exc
        else:
            prompt_ref = f"{key}.md"
        try:
            execution = normalize_role_execution_settings(
                {
                    "executor_kind": entry.get("executor_kind", "codex"),
                    "executor_mode": entry.get("executor_mode", "preset"),
                    "command_cli": entry.get("command_cli", ""),
                    "command_args_text": entry.get("command_args_text", ""),
                    "model": entry.get("model", ""),
                    "reasoning_effort": entry.get("reasoning_effort", ""),
                }
            )
            from loopora.workflows import normalize_archetype, validate_prompt_markdown

            normalized_archetype = normalize_archetype(archetype)
            validate_prompt_markdown(prompt_markdown, expected_archetype=normalized_archetype)
        except (WorkflowError, ValueError) as exc:
            raise BundleError(str(exc)) from exc
        normalized.append(
            {
                "key": key,
                "name": name,
                "description": str(entry.get("description", "") or "").strip(),
                "archetype": normalized_archetype,
                "prompt_ref": prompt_ref,
                "prompt_markdown": prompt_markdown,
                "posture_notes": str(entry.get("posture_notes", "") or "").strip(),
                **execution,
            }
        )
    return normalized


def _normalize_bundle_workflow(raw_workflow: object, *, role_definitions: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(raw_workflow, Mapping):
        raise BundleError("bundle workflow must be an object")
    payload = dict(raw_workflow)
    raw_roles = payload.get("roles")
    raw_steps = payload.get("steps")
    if not isinstance(raw_roles, list) or not raw_roles:
        raise BundleError("bundle workflow.roles must be a non-empty array")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise BundleError("bundle workflow.steps must be a non-empty array")

    role_keys = {item["key"] for item in role_definitions}
    archetype_by_key = {item["key"]: item["archetype"] for item in role_definitions}
    roles: list[dict[str, str]] = []
    seen_role_ids: set[str] = set()
    archetype_lookup: dict[str, str] = {}
    for index, raw_role in enumerate(raw_roles, start=1):
        if not isinstance(raw_role, Mapping):
            raise BundleError("bundle workflow.roles entries must be objects")
        entry = dict(raw_role)
        role_id = str(entry.get("id", "") or "").strip() or f"role_{index:03d}"
        if role_id in seen_role_ids:
            raise BundleError(f"duplicate bundle workflow role id: {role_id}")
        seen_role_ids.add(role_id)
        role_key = str(entry.get("role_definition_key", "") or role_id).strip()
        if role_key not in role_keys:
            raise BundleError(f"bundle workflow role {role_id} references unknown role_definition_key: {role_key}")
        roles.append({"id": role_id, "role_definition_key": role_key})
        archetype_lookup[role_id] = archetype_by_key[role_key]

    steps: list[dict[str, Any]] = []
    seen_step_ids: set[str] = set()
    for index, raw_step in enumerate(raw_steps, start=1):
        if not isinstance(raw_step, Mapping):
            raise BundleError("bundle workflow.steps entries must be objects")
        entry = dict(raw_step)
        step_id = str(entry.get("id", "") or "").strip() or f"step_{index:03d}"
        if step_id in seen_step_ids:
            raise BundleError(f"duplicate bundle workflow step id: {step_id}")
        seen_step_ids.add(step_id)
        role_id = str(entry.get("role_id", "") or "").strip()
        if role_id not in archetype_lookup:
            raise BundleError(f"bundle workflow step references unknown role_id: {role_id}")
        archetype = archetype_lookup[role_id]
        defaults = default_step_execution_settings(archetype=archetype)
        try:
            on_pass = normalize_step_on_pass(entry.get("on_pass"), archetype=archetype, default=defaults["on_pass"])
            inherit_session = normalize_step_inherit_session(entry.get("inherit_session"), archetype=archetype)
            from loopora.executor import validate_extra_cli_args_text

            extra_cli_args = str(entry.get("extra_cli_args", "") or "").strip()
            validate_extra_cli_args_text(extra_cli_args)
        except (WorkflowError, ValueError) as exc:
            raise BundleError(str(exc)) from exc
        steps.append(
            {
                "id": step_id,
                "role_id": role_id,
                "on_pass": on_pass,
                "model": str(entry.get("model", "") or "").strip(),
                "inherit_session": inherit_session,
                "extra_cli_args": extra_cli_args,
            }
        )
    return {
        "version": int(payload.get("version", 1) or 1),
        "preset": str(payload.get("preset", "") or "").strip(),
        "collaboration_intent": str(payload.get("collaboration_intent", "") or "").strip(),
        "roles": roles,
        "steps": steps,
    }


def load_bundle_file(path: Path) -> dict[str, Any]:
    raw_text = path.read_text(encoding="utf-8")
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
    return yaml.safe_dump(
        json.loads(json.dumps(normalized, ensure_ascii=False)),
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )
