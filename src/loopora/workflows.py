from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from loopora.executor import validate_command_args_text
from loopora.providers import executor_profile, normalize_executor_kind, normalize_executor_mode, normalize_reasoning_setting

ARCHETYPES = ("builder", "inspector", "gatekeeper", "guide", "custom")
LEGACY_ROLE_TO_ARCHETYPE = {
    "generator": "builder",
    "tester": "inspector",
    "verifier": "gatekeeper",
    "challenger": "guide",
    "builder": "builder",
    "inspector": "inspector",
    "gatekeeper": "gatekeeper",
    "guide": "guide",
    "custom": "custom",
}
ARCHETYPE_DISPLAY = {
    "builder": {"zh": "建造者", "en": "Builder"},
    "inspector": {"zh": "巡检者", "en": "Inspector"},
    "gatekeeper": {"zh": "守门人", "en": "GateKeeper"},
    "guide": {"zh": "向导", "en": "Guide"},
    "custom": {"zh": "自定义角色", "en": "Custom Role"},
}
LEGACY_ROLE_BY_ARCHETYPE = {
    "builder": "generator",
    "inspector": "tester",
    "gatekeeper": "verifier",
    "guide": "challenger",
}
PROMPT_FILES = {
    "builder": "builder.md",
    "inspector": "inspector.md",
    "gatekeeper": "gatekeeper.md",
    "gatekeeper-benchmark": "gatekeeper-benchmark.md",
    "guide": "guide.md",
    "custom": "custom.md",
}
PROMPT_ASSET_DIR = Path(__file__).parent / "assets" / "prompts"
ROLE_EXECUTION_FIELDS = (
    "executor_kind",
    "executor_mode",
    "command_cli",
    "command_args_text",
    "model",
    "reasoning_effort",
)


def default_role_execution_settings(executor_kind: str = "codex") -> dict[str, str]:
    profile = executor_profile(executor_kind)
    return {
        "executor_kind": profile.key,
        "executor_mode": "preset",
        "command_cli": profile.cli_name,
        "command_args_text": "",
        "model": profile.default_model,
        "reasoning_effort": profile.effort_default,
    }


def normalize_role_execution_settings(
    raw_settings: Mapping[str, Any] | None = None,
    *,
    default_executor_kind: str = "codex",
) -> dict[str, str]:
    settings = dict(raw_settings or {})
    executor_kind = normalize_executor_kind(str(settings.get("executor_kind", default_executor_kind)).strip() or default_executor_kind)
    executor_mode = normalize_executor_mode(str(settings.get("executor_mode", "preset")).strip() or "preset")
    profile = executor_profile(executor_kind)
    model = str(settings.get("model", "")).strip()
    reasoning_effort = str(settings.get("reasoning_effort", "")).strip()
    command_cli = str(settings.get("command_cli", "")).strip()
    command_args_text = str(settings.get("command_args_text", ""))

    if executor_mode == "preset":
        command_cli = profile.cli_name
        command_args_text = ""
        reasoning_effort = normalize_reasoning_setting(reasoning_effort, executor_kind=executor_kind)
        if not model and profile.default_model:
            model = profile.default_model
    else:
        command_cli = command_cli or profile.cli_name
        validate_command_args_text(command_args_text, executor_kind=executor_kind)

    return {
        "executor_kind": executor_kind,
        "executor_mode": executor_mode,
        "command_cli": command_cli,
        "command_args_text": command_args_text,
        "model": model,
        "reasoning_effort": reasoning_effort,
    }


def role_uses_execution_snapshot(role: Mapping[str, Any] | None) -> bool:
    if not isinstance(role, Mapping):
        return False
    return any(
        key in role
        for key in ("executor_kind", "executor_mode", "command_cli", "command_args_text", "reasoning_effort")
    )


def _preset_role(
    *,
    role_id: str,
    archetype: str,
    prompt_ref: str,
    role_definition_id: str,
) -> dict[str, str]:
    return {
        "id": role_id,
        "name": ARCHETYPE_DISPLAY[archetype]["en"],
        "archetype": archetype,
        "prompt_ref": prompt_ref,
        "role_definition_id": role_definition_id,
        **default_role_execution_settings(),
    }


WORKFLOW_PRESETS = {
    "build_first": {
        "roles": [
            _preset_role(role_id="builder", archetype="builder", prompt_ref=PROMPT_FILES["builder"], role_definition_id="builtin:builder"),
            _preset_role(role_id="inspector", archetype="inspector", prompt_ref=PROMPT_FILES["inspector"], role_definition_id="builtin:inspector"),
            _preset_role(role_id="gatekeeper", archetype="gatekeeper", prompt_ref=PROMPT_FILES["gatekeeper"], role_definition_id="builtin:gatekeeper"),
            _preset_role(role_id="guide", archetype="guide", prompt_ref=PROMPT_FILES["guide"], role_definition_id="builtin:guide"),
        ],
        "steps": [
            {"id": "builder_step", "role_id": "builder", "enabled": True},
            {"id": "inspector_step", "role_id": "inspector", "enabled": True},
            {"id": "gatekeeper_step", "role_id": "gatekeeper", "enabled": True, "on_pass": "finish_run"},
            {"id": "guide_step", "role_id": "guide", "enabled": True},
        ],
    },
    "inspect_first": {
        "roles": [
            _preset_role(role_id="inspector", archetype="inspector", prompt_ref=PROMPT_FILES["inspector"], role_definition_id="builtin:inspector"),
            _preset_role(role_id="builder", archetype="builder", prompt_ref=PROMPT_FILES["builder"], role_definition_id="builtin:builder"),
            _preset_role(role_id="gatekeeper", archetype="gatekeeper", prompt_ref=PROMPT_FILES["gatekeeper"], role_definition_id="builtin:gatekeeper"),
            _preset_role(role_id="guide", archetype="guide", prompt_ref=PROMPT_FILES["guide"], role_definition_id="builtin:guide"),
        ],
        "steps": [
            {"id": "inspector_step", "role_id": "inspector", "enabled": True},
            {"id": "builder_step", "role_id": "builder", "enabled": True},
            {"id": "gatekeeper_step", "role_id": "gatekeeper", "enabled": True, "on_pass": "finish_run"},
            {"id": "guide_step", "role_id": "guide", "enabled": True},
        ],
    },
    "benchmark_loop": {
        "roles": [
            _preset_role(role_id="gatekeeper", archetype="gatekeeper", prompt_ref=PROMPT_FILES["gatekeeper-benchmark"], role_definition_id="builtin:gatekeeper"),
            _preset_role(role_id="builder", archetype="builder", prompt_ref=PROMPT_FILES["builder"], role_definition_id="builtin:builder"),
        ],
        "steps": [
            {"id": "gatekeeper_step", "role_id": "gatekeeper", "enabled": True, "on_pass": "finish_run"},
            {"id": "builder_step", "role_id": "builder", "enabled": True},
        ],
    },
}

PROMPT_FRONT_MATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)


class WorkflowError(ValueError):
    """Raised when workflow or prompt files are invalid."""


def normalize_archetype(value: str | None) -> str:
    key = str(value or "").strip().lower()
    archetype = LEGACY_ROLE_TO_ARCHETYPE.get(key)
    if not archetype:
        raise WorkflowError(f"unsupported workflow archetype: {value}")
    return archetype


def normalize_role_models(role_models: dict[str, str] | None) -> dict[str, str]:
    normalized: dict[str, str] = {}
    if not role_models:
        return normalized
    for raw_role, raw_model in dict(role_models).items():
        role_key = str(raw_role).strip()
        model = str(raw_model).strip()
        if not role_key:
            raise WorkflowError("role model overrides require a role name")
        if not model:
            raise WorkflowError(f"invalid role model override: {raw_role}={raw_model}")
        archetype = LEGACY_ROLE_TO_ARCHETYPE.get(role_key.lower())
        if archetype:
            normalized[archetype] = model
            continue
        normalized[role_key] = model
    return normalized


def display_name_for_archetype(archetype: str, locale: str = "en") -> str:
    labels = ARCHETYPE_DISPLAY[normalize_archetype(archetype)]
    return labels["zh" if locale.lower().startswith("zh") else "en"]


def parse_prompt_markdown(markdown_text: str) -> tuple[dict[str, Any], str]:
    text = str(markdown_text or "").strip()
    if not text:
        raise WorkflowError("prompt markdown must not be empty")
    match = PROMPT_FRONT_MATTER_RE.match(text)
    if not match:
        raise WorkflowError("prompt markdown must start with YAML front matter")
    try:
        metadata = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        raise WorkflowError(f"invalid prompt front matter: {exc}") from exc
    if not isinstance(metadata, dict):
        raise WorkflowError("prompt front matter must decode to a mapping")
    body = match.group(2).strip()
    if not body:
        raise WorkflowError("prompt markdown body must not be empty")
    return metadata, body


def validate_prompt_markdown(markdown_text: str, *, expected_archetype: str | None = None) -> tuple[dict[str, Any], str]:
    metadata, body = parse_prompt_markdown(markdown_text)
    version = metadata.get("version")
    if version != 1:
        raise WorkflowError("prompt front matter requires version: 1")
    if "archetype" not in metadata:
        raise WorkflowError("prompt front matter requires archetype")
    archetype = normalize_archetype(str(metadata.get("archetype", "")))
    if expected_archetype and archetype != normalize_archetype(expected_archetype):
        raise WorkflowError(f"prompt archetype {archetype} does not match expected archetype {expected_archetype}")
    metadata["archetype"] = archetype
    return metadata, body


def builtin_prompt_markdown(prompt_ref: str) -> str:
    path = PROMPT_ASSET_DIR / prompt_ref
    if not path.exists():
        raise WorkflowError(f"unknown built-in prompt template: {prompt_ref}")
    return path.read_text(encoding="utf-8")


def available_prompt_templates() -> list[dict[str, str]]:
    templates = []
    for prompt_ref in sorted(PROMPT_FILES.values()):
        metadata, _ = validate_prompt_markdown(builtin_prompt_markdown(prompt_ref))
        templates.append(
            {
                "prompt_ref": prompt_ref,
                "archetype": metadata["archetype"],
            }
        )
    return templates


def builtin_prompt_files_for_workflow(workflow: dict) -> dict[str, str]:
    prompt_files: dict[str, str] = {}
    for role in workflow.get("roles", []):
        prompt_ref = str(role.get("prompt_ref", "")).strip()
        if prompt_ref and prompt_ref not in prompt_files:
            prompt_files[prompt_ref] = builtin_prompt_markdown(prompt_ref)
    return prompt_files


def preset_names() -> list[str]:
    return list(WORKFLOW_PRESETS.keys())


def build_preset_workflow(name: str = "build_first", *, role_models: dict[str, str] | None = None) -> dict:
    preset_name = str(name or "build_first").strip() or "build_first"
    if preset_name not in WORKFLOW_PRESETS:
        raise WorkflowError(f"unknown workflow preset: {preset_name}")
    overrides = normalize_role_models(role_models)
    preset = json.loads(json.dumps(WORKFLOW_PRESETS[preset_name], ensure_ascii=False))
    for role in preset["roles"]:
        override = overrides.get(role["id"]) or overrides.get(role["archetype"])
        if override:
            role["model"] = override
    return {"version": 1, "preset": preset_name, "roles": preset["roles"], "steps": preset["steps"]}


def workflow_warnings(workflow: dict) -> list[str]:
    role_by_id = {role["id"]: role for role in workflow.get("roles", [])}
    steps = [step for step in workflow.get("steps", []) if step.get("enabled", True)]
    warnings: list[str] = []
    if not has_finish_gatekeeper_step(workflow):
        warnings.append(
            "This workflow has no GateKeeper finish step, so it should be paired with round-based completion or updated before gate-based execution."
        )
    gate_before_builder = False
    gate_after_builder_without_inspector = False
    seen_builder = False
    seen_inspector_after_builder = False
    for step in steps:
        role = role_by_id.get(step["role_id"], {})
        archetype = role.get("archetype")
        if archetype == "builder":
            if any(role_by_id.get(next_step["role_id"], {}).get("archetype") == "gatekeeper" for next_step in steps if next_step["id"] == step["id"]):
                pass
            seen_builder = True
            seen_inspector_after_builder = False
        elif archetype == "inspector" and seen_builder:
            seen_inspector_after_builder = True
        elif archetype == "gatekeeper":
            if any(
                role_by_id.get(other["role_id"], {}).get("archetype") == "builder"
                for other in steps[steps.index(step) + 1 :]
            ):
                gate_before_builder = True
            if seen_builder and not seen_inspector_after_builder:
                gate_after_builder_without_inspector = True
    if gate_before_builder:
        warnings.append("GateKeeper appears before a later Builder step, so it may only judge pre-change evidence.")
    if gate_after_builder_without_inspector:
        warnings.append("GateKeeper appears after Builder without a later Inspector step, so it may judge stale evidence.")
    return warnings


def has_finish_gatekeeper_step(workflow: dict[str, Any] | None) -> bool:
    if not workflow:
        return False
    role_by_id = {
        str(role.get("id", "")).strip(): role
        for role in workflow.get("roles", [])
        if isinstance(role, dict)
    }
    for raw_step in workflow.get("steps", []):
        if not isinstance(raw_step, dict):
            continue
        if not bool(raw_step.get("enabled", True)):
            continue
        role = role_by_id.get(str(raw_step.get("role_id", "")).strip())
        if not role or role.get("archetype") != "gatekeeper":
            continue
        if str(raw_step.get("on_pass", "continue") or "continue").strip() == "finish_run":
            return True
    return False


def normalize_workflow(workflow: dict[str, Any] | None, *, role_models: dict[str, str] | None = None) -> dict:
    if workflow is None:
        normalized = build_preset_workflow("build_first", role_models=role_models)
        normalized["warnings"] = workflow_warnings(normalized)
        return normalized

    raw = dict(workflow)
    if raw.get("preset") and not raw.get("roles") and not raw.get("steps"):
        normalized = build_preset_workflow(str(raw.get("preset")), role_models=role_models)
        normalized["warnings"] = workflow_warnings(normalized)
        return normalized

    normalized_role_models = normalize_role_models(role_models)
    raw_roles = raw.get("roles")
    raw_steps = raw.get("steps")
    if not isinstance(raw_roles, list) or not raw_roles:
        raise WorkflowError("workflow requires at least one role")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise WorkflowError("workflow requires at least one step")

    roles: list[dict[str, Any]] = []
    role_ids: set[str] = set()
    for index, raw_role in enumerate(raw_roles, start=1):
        if not isinstance(raw_role, dict):
            raise WorkflowError("workflow roles must be objects")
        role_id = str(raw_role.get("id", "")).strip() or f"role_{index:03d}"
        if role_id in role_ids:
            raise WorkflowError(f"duplicate workflow role id: {role_id}")
        archetype = normalize_archetype(str(raw_role.get("archetype", "")))
        prompt_ref = str(raw_role.get("prompt_ref", "")).strip() or PROMPT_FILES[archetype]
        name = str(raw_role.get("name", "")).strip() or display_name_for_archetype(archetype, locale="en")
        model = str(raw_role.get("model", "")).strip()
        role_definition_id = str(raw_role.get("role_definition_id", "")).strip()
        override_model = normalized_role_models.get(role_id, normalized_role_models.get(archetype, ""))
        if override_model:
            model = override_model
        role_ids.add(role_id)
        role_entry = {
            "id": role_id,
            "name": name,
            "archetype": archetype,
            "prompt_ref": prompt_ref,
            "model": model,
            "role_definition_id": role_definition_id,
        }
        if role_uses_execution_snapshot(raw_role):
            execution_settings = normalize_role_execution_settings(raw_role)
            role_entry.update(execution_settings)
            if model:
                role_entry["model"] = model
        roles.append(role_entry)

    steps: list[dict[str, Any]] = []
    for index, raw_step in enumerate(raw_steps, start=1):
        if not isinstance(raw_step, dict):
            raise WorkflowError("workflow steps must be objects")
        role_id = str(raw_step.get("role_id", "")).strip()
        if role_id not in role_ids:
            raise WorkflowError(f"workflow step references unknown role_id: {role_id}")
        step_id = str(raw_step.get("id", "")).strip() or f"step_{index:03d}"
        enabled = bool(raw_step.get("enabled", True))
        role = next(item for item in roles if item["id"] == role_id)
        on_pass = str(raw_step.get("on_pass", "continue") or "continue").strip()
        model = str(raw_step.get("model", "")).strip()
        if role["archetype"] != "gatekeeper":
            on_pass = "continue"
        elif on_pass not in {"continue", "finish_run"}:
            raise WorkflowError("gatekeeper step on_pass must be continue or finish_run")
        steps.append(
            {
                "id": step_id,
                "role_id": role_id,
                "enabled": enabled,
                "on_pass": on_pass,
                "model": model,
            }
        )

    normalized = {
        "version": int(raw.get("version", 1) or 1),
        "preset": str(raw.get("preset", "")).strip(),
        "roles": roles,
        "steps": steps,
    }
    normalized["warnings"] = workflow_warnings(normalized)
    return normalized


def resolve_prompt_files(
    workflow: dict,
    provided_prompt_files: dict[str, str] | None = None,
) -> dict[str, str]:
    resolved = builtin_prompt_files_for_workflow(workflow)
    for prompt_ref, markdown_text in dict(provided_prompt_files or {}).items():
        resolved[str(prompt_ref).strip()] = str(markdown_text or "")
    for role in workflow.get("roles", []):
        prompt_ref = role["prompt_ref"]
        if prompt_ref not in resolved:
            raise WorkflowError(f"missing prompt file for role {role['id']}: {prompt_ref}")
        validate_prompt_markdown(resolved[prompt_ref], expected_archetype=role["archetype"])
    return resolved


def load_workflow_file(path: Path) -> tuple[dict[str, Any], dict[str, str]]:
    raw_text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        payload = yaml.safe_load(raw_text) or {}
    else:
        payload = json.loads(raw_text)
    if not isinstance(payload, dict):
        raise WorkflowError("workflow file must decode to an object")
    workflow = payload.get("workflow", payload)
    prompt_files = payload.get("prompt_files", {})
    if not isinstance(prompt_files, dict):
        raise WorkflowError("workflow file prompt_files must be a mapping")
    return dict(workflow), {str(key): str(value) for key, value in prompt_files.items()}
