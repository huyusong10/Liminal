from __future__ import annotations

from pathlib import Path

from loopora.service import LooporaError, normalize_role_models
from loopora.workflows import (
    PROMPT_FILES,
    builtin_prompt_markdown,
    load_workflow_file,
    normalize_archetype,
    normalize_role_display_name,
)


def command_args_text_from_values(values: list[str] | None) -> str:
    if not values:
        return ""
    return "\n".join(item for item in values if item.strip())


def parse_role_models(values: list[str] | None) -> dict[str, str]:
    parsed: dict[str, str] = {}
    if not values:
        return parsed
    for item in values:
        if "=" not in item:
            raise LooporaError(f"invalid --role-model value: {item}")
        role, model = item.split("=", 1)
        parsed[role.strip()] = model.strip()
    return normalize_role_models(parsed)


def workflow_bundle_from_entity(entity: dict[str, object]) -> tuple[dict | None, dict[str, str]]:
    workflow = entity.get("workflow_json") or None
    prompt_files = entity.get("prompt_files_json") or entity.get("prompt_files") or {}
    if isinstance(prompt_files, dict):
        return workflow, dict(prompt_files)
    return workflow, {}


def resolve_workflow_bundle(
    *,
    workflow_file: Path | None,
    workflow_preset: str,
    fallback_workflow: dict | None = None,
    fallback_prompt_files: dict[str, str] | None = None,
) -> tuple[dict | None, dict[str, str]]:
    workflow = fallback_workflow
    prompt_files = dict(fallback_prompt_files or {})
    if workflow_file is not None:
        loaded_workflow, loaded_prompt_files = load_workflow_file(workflow_file)
        return loaded_workflow, dict(loaded_prompt_files or {})
    if workflow_preset.strip():
        return {"preset": workflow_preset.strip()}, {}
    return workflow, prompt_files


def read_prompt_markdown(
    *,
    prompt_file: Path | None,
    prompt_template: str,
    locale: str,
    archetype: str,
    fallback: str = "",
) -> str:
    if prompt_file is not None:
        return prompt_file.read_text(encoding="utf-8")
    if prompt_template.strip():
        return builtin_prompt_markdown(prompt_template.strip(), locale=locale)
    if fallback:
        return fallback
    normalized_archetype = normalize_archetype(archetype)
    return builtin_prompt_markdown(PROMPT_FILES[normalized_archetype], locale=locale)


def build_role_definition_kwargs(
    *,
    archetype: str,
    prompt_file: Path | None,
    prompt_template: str,
    locale: str,
    posture_notes: str,
    executor_kind: str,
    executor_mode: str,
    command_cli: str,
    command_arg: list[str] | None,
    model: str,
    reasoning_effort: str,
    fallback: dict[str, object] | None = None,
) -> dict[str, str]:
    current = fallback or {}
    normalized_archetype = normalize_archetype(archetype or str(current.get("archetype", "builder") or "builder"))
    prompt_markdown = read_prompt_markdown(
        prompt_file=prompt_file,
        prompt_template=prompt_template,
        locale=locale,
        archetype=normalized_archetype,
        fallback=str(current.get("prompt_markdown", "")),
    )
    return {
        "archetype": normalized_archetype,
        "prompt_markdown": prompt_markdown,
        "posture_notes": posture_notes if posture_notes else str(current.get("posture_notes", "")),
        "executor_kind": executor_kind or str(current.get("executor_kind", "codex") or "codex"),
        "executor_mode": executor_mode or str(current.get("executor_mode", "preset") or "preset"),
        "command_cli": command_cli or str(current.get("command_cli", "")),
        "command_args_text": command_args_text_from_values(command_arg)
        if command_arg is not None
        else str(current.get("command_args_text", "")),
        "model": model or str(current.get("model", "")),
        "reasoning_effort": reasoning_effort or str(current.get("reasoning_effort", "")),
    }


def build_loop_kwargs(
    *,
    spec: Path,
    workdir: Path,
    executor_kind: str,
    executor_mode: str,
    model: str,
    reasoning_effort: str,
    completion_mode: str,
    iteration_interval_seconds: float,
    command_cli: str,
    command_arg: list[str] | None,
    max_iters: int,
    max_role_retries: int,
    delta_threshold: float,
    trigger_window: int,
    regression_window: int,
    name: str | None,
    role_model: list[str] | None,
    orchestration_id: str,
    workflow_preset: str,
    workflow_file: Path | None,
) -> dict[str, object]:
    workflow: dict | None = None
    prompt_files: dict[str, str] | None = None
    if workflow_file is not None:
        workflow, prompt_files = load_workflow_file(workflow_file)
    elif workflow_preset and not orchestration_id.strip():
        workflow = {"preset": workflow_preset}
    return {
        "name": name or workdir.resolve().name,
        "spec_path": spec,
        "workdir": workdir,
        "orchestration_id": orchestration_id.strip() or None,
        "executor_kind": executor_kind,
        "executor_mode": executor_mode,
        "command_cli": command_cli,
        "command_args_text": command_args_text_from_values(command_arg),
        "model": model,
        "reasoning_effort": reasoning_effort,
        "completion_mode": completion_mode,
        "iteration_interval_seconds": iteration_interval_seconds,
        "max_iters": max_iters,
        "max_role_retries": max_role_retries,
        "delta_threshold": delta_threshold,
        "trigger_window": trigger_window,
        "regression_window": regression_window,
        "workflow": workflow,
        "prompt_files": prompt_files,
        "role_models": parse_role_models(role_model),
    }
