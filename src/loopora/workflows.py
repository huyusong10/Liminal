from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from loopora.executor import validate_command_args_text
from loopora.executor import validate_extra_cli_args_text
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
    "builder": {"zh": "Builder", "en": "Builder"},
    "inspector": {"zh": "Inspector", "en": "Inspector"},
    "gatekeeper": {"zh": "GateKeeper", "en": "GateKeeper"},
    "guide": {"zh": "Guide", "en": "Guide"},
    "custom": {"zh": "Custom Role", "en": "Custom Role"},
}
ARCHETYPE_DISPLAY_ALIASES = {
    "builder": {"建造者", "generator", "builder"},
    "inspector": {"巡检者", "tester", "inspector"},
    "gatekeeper": {"守门人", "verifier", "gatekeeper"},
    "guide": {"向导", "challenger", "guide"},
    "custom": {"自定义角色", "custom role", "custom"},
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
SPEC_PRACTICE_ASSET_DIR = Path(__file__).parent / "assets" / "spec_practices"
ROLE_EXECUTION_FIELDS = (
    "executor_kind",
    "executor_mode",
    "command_cli",
    "command_args_text",
    "model",
    "reasoning_effort",
)
ROLE_POSTURE_FIELDS = ("posture_notes",)
STEP_EXECUTION_FIELDS = (
    "on_pass",
    "model",
    "inherit_session",
    "extra_cli_args",
    "parallel_group",
    "inputs",
    "action_policy",
)
PARALLEL_GROUP_ARCHETYPES = {"inspector", "custom"}
STEP_INPUT_KEYS = {"handoffs_from", "evidence_query", "iteration_memory"}
STEP_ACTION_POLICY_KEYS = {"workspace", "can_block", "can_finish_run"}
STEP_ACTION_POLICY_WORKSPACES = {"read_only", "workspace_write"}
STEP_ITERATION_MEMORY_POLICIES = {"default", "none", "same_step", "same_role", "summary_only"}
WORKFLOW_CONTROL_SIGNALS = {"no_evidence_progress", "role_timeout", "step_failed", "gatekeeper_rejected"}
WORKFLOW_CONTROL_MODES = {"advisory", "blocking", "repair_guidance"}
WORKFLOW_CONTROL_ARCHETYPES = {"inspector", "guide", "gatekeeper"}
WORKFLOW_SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")
WORKFLOW_CONTROL_AFTER_RE = re.compile(r"^\d+(?:\.\d+)?(?:ms|s|m|h)?$")


def normalize_prompt_locale(value: str | None) -> str:
    return "zh" if str(value or "").strip().lower().startswith("zh") else "en"


def normalize_prompt_ref(value: str | None) -> str:
    prompt_ref = str(value or "").strip()
    if not prompt_ref:
        raise WorkflowError("prompt_ref is required")
    normalized = prompt_ref.replace("\\", "/")
    parts = normalized.split("/")
    if normalized.startswith("/") or any(not part or part in {".", ".."} for part in parts):
        raise WorkflowError("prompt_ref must be a safe relative path")
    return PurePosixPath(*parts).as_posix()


def normalize_workflow_identifier(value: object, *, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise WorkflowError(f"{field_name} is required")
    if not WORKFLOW_SAFE_IDENTIFIER_RE.fullmatch(normalized):
        raise WorkflowError(f"{field_name} must use letters, numbers, dot, underscore, or dash")
    return normalized


def prompt_asset_path(root: Path, prompt_ref: str) -> Path:
    normalized_prompt_ref = normalize_prompt_ref(prompt_ref)
    return root.joinpath(*PurePosixPath(normalized_prompt_ref).parts)


def localized_prompt_ref(prompt_ref: str, locale: str | None = None) -> str:
    normalized_prompt_ref = normalize_prompt_ref(prompt_ref)
    normalized_locale = normalize_prompt_locale(locale)
    if normalized_locale != "zh":
        return normalized_prompt_ref
    path = PurePosixPath(normalized_prompt_ref)
    localized_prompt_ref = path.with_name(f"{path.stem}.zh{path.suffix}").as_posix()
    localized_path = prompt_asset_path(PROMPT_ASSET_DIR, localized_prompt_ref)
    return localized_prompt_ref if localized_path.exists() else normalized_prompt_ref


def default_role_execution_settings(executor_kind: str = "codex") -> dict[str, str]:
    profile = executor_profile(executor_kind)
    default_mode = "command" if profile.command_only else "preset"
    return {
        "executor_kind": profile.key,
        "executor_mode": default_mode,
        "command_cli": profile.cli_name,
        "command_args_text": "\n".join(profile.command_args_template) if default_mode == "command" else "",
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

    if profile.command_only and executor_mode != "command":
        raise ValueError(f"{profile.label} only supports command mode")

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
        for key in ("executor_kind", "executor_mode", "command_cli", "command_args_text", "model", "reasoning_effort")
    )


def default_step_inherit_session(archetype: str | None) -> bool:
    normalized_archetype = LEGACY_ROLE_TO_ARCHETYPE.get(str(archetype or "").strip().lower(), "")
    return normalized_archetype == "builder"


def normalize_step_inherit_session(value: Any, *, archetype: str | None = None) -> bool:
    default = default_step_inherit_session(archetype)
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise WorkflowError("workflow step inherit_session must be a boolean")


def normalize_step_policy_boolean(value: Any, *, field_name: str, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise WorkflowError(f"workflow step action_policy.{field_name} must be a boolean")


def normalize_step_on_pass(
    value: Any,
    *,
    archetype: str | None = None,
    default: str = "continue",
) -> str:
    normalized_archetype = LEGACY_ROLE_TO_ARCHETYPE.get(str(archetype or "").strip().lower(), "")
    normalized_default = str(default or "continue").strip() or "continue"
    normalized_value = str(value if value is not None else normalized_default).strip() or normalized_default
    if normalized_archetype != "gatekeeper":
        if normalized_value != "continue":
            raise WorkflowError("non-gatekeeper steps only support on_pass=continue")
        return "continue"
    if normalized_value not in {"continue", "finish_run"}:
        raise WorkflowError("gatekeeper step on_pass must be continue or finish_run")
    return normalized_value


def _normalize_string_list(value: Any, *, field_name: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        normalized = value.strip()
        return [normalized] if normalized else []
    if not isinstance(value, list):
        raise WorkflowError(f"{field_name} must be a string or array of strings")
    result: list[str] = []
    for item in value:
        normalized = str(item or "").strip()
        if normalized:
            result.append(normalized)
    return result


def normalize_step_parallel_group(value: Any) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    return normalize_workflow_identifier(normalized, field_name="workflow step parallel_group")


def normalize_step_inputs(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise WorkflowError("workflow step inputs must be an object")
    unknown_keys = sorted(str(key) for key in value.keys() if str(key) not in STEP_INPUT_KEYS)
    if unknown_keys:
        raise WorkflowError(f"workflow step inputs contains unknown keys: {', '.join(unknown_keys)}")

    result: dict[str, Any] = {}
    handoffs_from = _normalize_string_list(value.get("handoffs_from"), field_name="workflow step inputs.handoffs_from")
    if handoffs_from:
        result["handoffs_from"] = handoffs_from

    evidence_query = value.get("evidence_query")
    if evidence_query is not None:
        if not isinstance(evidence_query, Mapping):
            raise WorkflowError("workflow step inputs.evidence_query must be an object")
        query_unknown = sorted(
            str(key)
            for key in evidence_query.keys()
            if str(key) not in {"archetypes", "verifies", "limit"}
        )
        if query_unknown:
            raise WorkflowError(
                f"workflow step inputs.evidence_query contains unknown keys: {', '.join(query_unknown)}"
            )
        query: dict[str, Any] = {}
        archetypes = _normalize_string_list(
            evidence_query.get("archetypes"),
            field_name="workflow step inputs.evidence_query.archetypes",
        )
        invalid_archetypes = [item for item in archetypes if item not in ARCHETYPES]
        if invalid_archetypes:
            raise WorkflowError(
                "workflow step inputs.evidence_query.archetypes contains unknown archetypes: "
                + ", ".join(invalid_archetypes)
            )
        if archetypes:
            query["archetypes"] = archetypes
        verifies = _normalize_string_list(
            evidence_query.get("verifies"),
            field_name="workflow step inputs.evidence_query.verifies",
        )
        if verifies:
            query["verifies"] = verifies
        raw_limit = evidence_query.get("limit")
        if raw_limit is not None:
            try:
                limit = int(raw_limit)
            except (TypeError, ValueError) as exc:
                raise WorkflowError("workflow step inputs.evidence_query.limit must be an integer") from exc
            if limit < 1 or limit > 100:
                raise WorkflowError("workflow step inputs.evidence_query.limit must be between 1 and 100")
            query["limit"] = limit
        if query:
            result["evidence_query"] = query

    iteration_memory = str(value.get("iteration_memory") or "").strip().lower()
    if iteration_memory == "all":
        iteration_memory = "default"
    if iteration_memory:
        if iteration_memory not in STEP_ITERATION_MEMORY_POLICIES:
            raise WorkflowError(
                "workflow step inputs.iteration_memory must be default, none, same_step, same_role, or summary_only"
            )
        if iteration_memory != "default":
            result["iteration_memory"] = iteration_memory

    return result


def default_step_action_policy(*, archetype: str | None = None, on_pass: str = "continue") -> dict[str, Any]:
    normalized_archetype = LEGACY_ROLE_TO_ARCHETYPE.get(str(archetype or "").strip().lower(), "")
    if normalized_archetype == "builder":
        return {"workspace": "workspace_write", "can_block": False, "can_finish_run": False}
    if normalized_archetype == "inspector":
        return {"workspace": "read_only", "can_block": True, "can_finish_run": False}
    if normalized_archetype == "gatekeeper":
        return {
            "workspace": "read_only",
            "can_block": True,
            "can_finish_run": str(on_pass or "continue").strip() == "finish_run",
        }
    return {"workspace": "read_only", "can_block": False, "can_finish_run": False}


def normalize_step_action_policy(
    value: Any,
    *,
    archetype: str | None = None,
    on_pass: str = "continue",
) -> dict[str, Any]:
    normalized_archetype = LEGACY_ROLE_TO_ARCHETYPE.get(str(archetype or "").strip().lower(), "")
    defaults = default_step_action_policy(archetype=normalized_archetype, on_pass=on_pass)
    if value is None:
        policy = dict(defaults)
    else:
        if not isinstance(value, Mapping):
            raise WorkflowError("workflow step action_policy must be an object")
        unknown_keys = sorted(str(key) for key in value.keys() if str(key) not in STEP_ACTION_POLICY_KEYS)
        if unknown_keys:
            raise WorkflowError(f"workflow step action_policy contains unknown keys: {', '.join(unknown_keys)}")
        raw_workspace = str(value.get("workspace", defaults["workspace"]) or defaults["workspace"]).strip().lower()
        raw_workspace = raw_workspace.replace("-", "_")
        if raw_workspace in {"readonly", "read"}:
            raw_workspace = "read_only"
        elif raw_workspace in {"write", "workspace"}:
            raw_workspace = "workspace_write"
        if raw_workspace not in STEP_ACTION_POLICY_WORKSPACES:
            raise WorkflowError("workflow step action_policy.workspace must be read_only or workspace_write")
        policy = {
            "workspace": raw_workspace,
            "can_block": normalize_step_policy_boolean(
                value.get("can_block"),
                field_name="can_block",
                default=bool(defaults["can_block"]),
            ),
            "can_finish_run": normalize_step_policy_boolean(
                value.get("can_finish_run"),
                field_name="can_finish_run",
                default=bool(defaults["can_finish_run"]),
            ),
        }

    if policy["workspace"] == "workspace_write" and normalized_archetype != "builder":
        raise WorkflowError("only Builder steps may set action_policy.workspace=workspace_write in v1")
    if policy["can_finish_run"] and normalized_archetype != "gatekeeper":
        raise WorkflowError("only GateKeeper steps may set action_policy.can_finish_run=true")
    if policy["can_finish_run"] and str(on_pass or "continue").strip() != "finish_run":
        raise WorkflowError("action_policy.can_finish_run=true requires on_pass=finish_run")
    return policy


def normalize_workflow_controls(value: Any, *, role_by_id: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise WorkflowError("workflow.controls must be an array")
    result: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, raw_control in enumerate(value, start=1):
        if not isinstance(raw_control, Mapping):
            raise WorkflowError("workflow.controls entries must be objects")
        unknown_keys = sorted(
            str(key)
            for key in raw_control.keys()
            if str(key) not in {"id", "when", "call", "mode", "max_fires_per_run"}
        )
        if unknown_keys:
            raise WorkflowError(f"workflow control contains unknown keys: {', '.join(unknown_keys)}")
        control_id = normalize_workflow_identifier(
            raw_control.get("id") or f"control_{index:03d}",
            field_name="workflow control id",
        )
        if control_id in seen_ids:
            raise WorkflowError(f"duplicate workflow control id: {control_id}")
        seen_ids.add(control_id)

        when = raw_control.get("when")
        if not isinstance(when, Mapping):
            raise WorkflowError(f"workflow control {control_id} requires when")
        when_unknown = sorted(str(key) for key in when.keys() if str(key) not in {"signal", "after"})
        if when_unknown:
            raise WorkflowError(f"workflow control {control_id}.when contains unknown keys: {', '.join(when_unknown)}")
        signal = str(when.get("signal") or "").strip()
        if signal not in WORKFLOW_CONTROL_SIGNALS:
            raise WorkflowError(
                "workflow control when.signal must be one of: " + ", ".join(sorted(WORKFLOW_CONTROL_SIGNALS))
            )
        after = str(when.get("after") or "0s").strip() or "0s"
        if not WORKFLOW_CONTROL_AFTER_RE.match(after):
            raise WorkflowError("workflow control when.after must be an elapsed duration such as 30s, 20m, or 1h")

        call = raw_control.get("call")
        if not isinstance(call, Mapping):
            raise WorkflowError(f"workflow control {control_id} requires call")
        call_unknown = sorted(str(key) for key in call.keys() if str(key) not in {"role_id"})
        if call_unknown:
            raise WorkflowError(f"workflow control {control_id}.call contains unknown keys: {', '.join(call_unknown)}")
        role_id = str(call.get("role_id") or "").strip()
        role = role_by_id.get(role_id)
        if role is None:
            raise WorkflowError(f"workflow control {control_id} references unknown role_id: {role_id}")
        archetype = str(role.get("archetype") or "").strip()
        if archetype not in WORKFLOW_CONTROL_ARCHETYPES:
            raise WorkflowError("workflow controls may only call Inspector, Guide, or GateKeeper roles")

        mode = str(raw_control.get("mode") or "advisory").strip()
        if mode not in WORKFLOW_CONTROL_MODES:
            raise WorkflowError("workflow control mode must be advisory, blocking, or repair_guidance")
        try:
            max_fires = int(raw_control.get("max_fires_per_run", 1) or 1)
        except (TypeError, ValueError) as exc:
            raise WorkflowError("workflow control max_fires_per_run must be an integer") from exc
        if max_fires < 1 or max_fires > 20:
            raise WorkflowError("workflow control max_fires_per_run must be between 1 and 20")

        result.append(
            {
                "id": control_id,
                "when": {"signal": signal, "after": after},
                "call": {"role_id": role_id},
                "mode": mode,
                "max_fires_per_run": max_fires,
            }
        )
    return result


def default_step_execution_settings(*, archetype: str | None = None) -> dict[str, Any]:
    normalized_archetype = LEGACY_ROLE_TO_ARCHETYPE.get(str(archetype or "").strip().lower(), "")
    return {
        "on_pass": "finish_run" if normalized_archetype == "gatekeeper" else "continue",
        "model": "",
        "inherit_session": default_step_inherit_session(normalized_archetype) if normalized_archetype else False,
        "extra_cli_args": "",
    }


def _preset_role(
    *,
    role_id: str,
    archetype: str,
    prompt_ref: str,
    role_definition_id: str,
    name: str = "",
    posture_notes: str = "",
) -> dict[str, str]:
    return {
        "id": role_id,
        "name": name or ARCHETYPE_DISPLAY[archetype]["en"],
        "archetype": archetype,
        "prompt_ref": prompt_ref,
        "role_definition_id": role_definition_id,
        "posture_notes": posture_notes,
        **default_role_execution_settings(),
    }


def _workflow_preset_definition(
    *,
    label_zh: str,
    label_en: str,
    description_zh: str,
    description_en: str,
    scenario_zh: str,
    scenario_en: str,
    choice_zh: str = "",
    choice_en: str = "",
    decision_zh: str = "",
    decision_en: str = "",
    visible: bool = True,
    roles: list[dict[str, str]],
    steps: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "label_zh": label_zh,
        "label_en": label_en,
        "description_zh": description_zh,
        "description_en": description_en,
        "scenario_zh": scenario_zh,
        "scenario_en": scenario_en,
        "choice_zh": choice_zh,
        "choice_en": choice_en,
        "decision_zh": decision_zh,
        "decision_en": decision_en,
        "visible": visible,
        "workflow": {
            "collaboration_intent": decision_en,
            "roles": roles,
            "steps": steps,
        },
    }


def _preset_step(
    *,
    step_id: str,
    role_id: str,
    archetype: str,
    on_pass: str | None = None,
    model: str = "",
    inherit_session: bool | None = None,
    extra_cli_args: str = "",
    parallel_group: str = "",
    inputs: dict[str, Any] | None = None,
    action_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    defaults = default_step_execution_settings(archetype=archetype)
    normalized_on_pass = normalize_step_on_pass(
        on_pass,
        archetype=archetype,
        default=defaults["on_pass"],
    )
    step = {
        "id": step_id,
        "role_id": role_id,
        "on_pass": normalized_on_pass,
        "model": model,
        "inherit_session": normalize_step_inherit_session(
            inherit_session,
            archetype=archetype,
        ),
        "extra_cli_args": str(extra_cli_args or ""),
        "action_policy": normalize_step_action_policy(
            action_policy,
            archetype=archetype,
            on_pass=normalized_on_pass,
        ),
    }
    normalized_parallel_group = normalize_step_parallel_group(parallel_group)
    if normalized_parallel_group:
        step["parallel_group"] = normalized_parallel_group
    normalized_inputs = normalize_step_inputs(inputs)
    if normalized_inputs:
        step["inputs"] = normalized_inputs
    return step


DEFAULT_WORKFLOW_PRESET = "build_then_parallel_review"


WORKFLOW_PRESETS = {
    "build_then_parallel_review": _workflow_preset_definition(
        label_zh="构建后并行检视",
        label_en="Build + Parallel Review",
        description_zh="Builder -> [Contract Inspector + Evidence Inspector] -> GateKeeper",
        description_en="Builder -> [Contract Inspector + Evidence Inspector] -> GateKeeper",
        scenario_zh="适合目标已经足够清楚，但误差风险来自多个方向的长任务：一个 AI Agent 可以先推进实现，之后由两个检视视角并行检查用户契约和可复验证据，再由 GateKeeper 汇总裁决。",
        scenario_en="Best when the target is clear but error risk comes from multiple directions: one AI Agent can push the implementation, two inspection perspectives can review contract and evidence in parallel, and GateKeeper can make the final call.",
        choice_zh="默认选它，因为它把人类常做的“先让 Agent 干活，再从不同角度复查，再决定能不能收工”外化成可运行的治理结构。",
        choice_en="Choose this by default because it externalizes the common human loop: let the agent build, review from more than one angle, then decide whether the task can close.",
        decision_zh="先构建可检查产物，再用并行检视降低单一 reviewer 漏看风险，最后由 GateKeeper 基于汇总证据收束。",
        decision_en="Build an inspectable result first, reduce single-reviewer blind spots through parallel inspection, then let GateKeeper close from the gathered evidence.",
        roles=[
            _preset_role(
                role_id="builder",
                archetype="builder",
                prompt_ref=PROMPT_FILES["builder"],
                role_definition_id="builtin:builder",
                posture_notes="Create a concrete, inspectable result and leave a concise handoff for multiple reviewers.",
            ),
            _preset_role(
                role_id="contract_inspector",
                name="Contract Inspector",
                archetype="inspector",
                prompt_ref=PROMPT_FILES["inspector"],
                role_definition_id="builtin:inspector",
                posture_notes="Check whether the result satisfies the task contract, guardrails, and fake-done risks.",
            ),
            _preset_role(
                role_id="evidence_inspector",
                name="Evidence Inspector",
                archetype="inspector",
                prompt_ref=PROMPT_FILES["inspector"],
                role_definition_id="builtin:inspector",
                posture_notes="Collect reproducible proof that the main path works, and call out weak or missing evidence.",
            ),
            _preset_role(
                role_id="gatekeeper",
                archetype="gatekeeper",
                prompt_ref=PROMPT_FILES["gatekeeper"],
                role_definition_id="builtin:gatekeeper",
                posture_notes="Pass only when contract and evidence inspection both support closing the loop.",
            ),
        ],
        steps=[
            _preset_step(step_id="builder_step", role_id="builder", archetype="builder"),
            _preset_step(
                step_id="contract_inspection_step",
                role_id="contract_inspector",
                archetype="inspector",
                parallel_group="inspection_pack",
                inputs={
                    "handoffs_from": ["builder_step"],
                    "evidence_query": {"archetypes": ["builder"], "limit": 12},
                    "iteration_memory": "summary_only",
                },
            ),
            _preset_step(
                step_id="evidence_inspection_step",
                role_id="evidence_inspector",
                archetype="inspector",
                parallel_group="inspection_pack",
                inputs={
                    "handoffs_from": ["builder_step"],
                    "evidence_query": {"archetypes": ["builder"], "limit": 12},
                    "iteration_memory": "summary_only",
                },
            ),
            _preset_step(
                step_id="gatekeeper_step",
                role_id="gatekeeper",
                archetype="gatekeeper",
                on_pass="finish_run",
                inputs={
                    "handoffs_from": ["contract_inspection_step", "evidence_inspection_step"],
                    "evidence_query": {"archetypes": ["builder", "inspector"], "limit": 24},
                },
            ),
        ],
    ),
    "evidence_first": _workflow_preset_definition(
        label_zh="先取证再构建",
        label_en="Evidence First",
        description_zh="Inspector -> Builder -> GateKeeper",
        description_en="Inspector -> Builder -> GateKeeper",
        scenario_zh="适合失败层、风险面或真实完成标准还不稳的任务。先让 Inspector 建立事实和证据边界，再让 Builder 针对已确认的缺口推进，最后由 GateKeeper 判断是否收束。",
        scenario_en="Best when the failure layer, risk surface, or success standard is still uncertain. Inspector grounds the facts first, Builder acts against the confirmed gap, and GateKeeper decides whether the loop can close.",
        choice_zh="选它，而不是默认并行检视，因为现在最稀缺的是事实边界；先写代码容易把误差放大。",
        choice_en="Choose this over the default parallel review when the scarce thing is the factual boundary; coding first would amplify error.",
        decision_zh="先建立证据边界，再推进实现，避免 Builder 在错误层面上加速。",
        decision_en="Ground the evidence boundary before implementation so Builder does not accelerate in the wrong layer.",
        roles=[
            _preset_role(
                role_id="inspector",
                archetype="inspector",
                prompt_ref=PROMPT_FILES["inspector"],
                role_definition_id="builtin:inspector",
                posture_notes="Identify the first trustworthy evidence boundary and separate facts from assumptions before implementation.",
            ),
            _preset_role(
                role_id="builder",
                archetype="builder",
                prompt_ref=PROMPT_FILES["builder"],
                role_definition_id="builtin:builder",
                posture_notes="Act only on the grounded evidence slice and avoid widening the repair target.",
            ),
            _preset_role(
                role_id="gatekeeper",
                archetype="gatekeeper",
                prompt_ref=PROMPT_FILES["gatekeeper"],
                role_definition_id="builtin:gatekeeper",
                posture_notes="Judge the final result against the same evidence path that shaped the implementation.",
            ),
        ],
        steps=[
            _preset_step(step_id="inspector_step", role_id="inspector", archetype="inspector"),
            _preset_step(
                step_id="builder_step",
                role_id="builder",
                archetype="builder",
                inputs={"handoffs_from": ["inspector_step"], "iteration_memory": "summary_only"},
            ),
            _preset_step(
                step_id="gatekeeper_step",
                role_id="gatekeeper",
                archetype="gatekeeper",
                on_pass="finish_run",
                inputs={
                    "handoffs_from": ["inspector_step", "builder_step"],
                    "evidence_query": {"archetypes": ["inspector", "builder"], "limit": 20},
                },
            ),
        ],
    ),
    "benchmark_gate": _workflow_preset_definition(
        label_zh="基准门禁",
        label_en="Benchmark Gate",
        description_zh="Benchmark Inspector -> Builder -> Regression Inspector -> GateKeeper",
        description_en="Benchmark Inspector -> Builder -> Regression Inspector -> GateKeeper",
        scenario_zh="适合已经有 benchmark、contract test 或可重复度量的任务。先读取基准事实，再推进最小修复，随后复查同一证据路径，最后让 GateKeeper 基于指标和残余风险裁决。",
        scenario_en="Best when a benchmark, contract test, or repeatable measurement already exists. Read the baseline first, make the smallest repair, re-check the same evidence path, and let GateKeeper decide from metric evidence plus residual risk.",
        choice_zh="选它时，说明你信任可重复测量多于直觉判断；它比默认流程更适合性能、检索、回归和质量门禁类任务。",
        choice_en="Choose this when repeatable measurement is more trustworthy than intuition; it fits performance, retrieval, regression, and quality-gate tasks better than the default.",
        decision_zh="把基准证据放在实现前后两端，避免用不同证据口径宣称进步。",
        decision_en="Put benchmark evidence on both sides of implementation so progress is not claimed through a different evidence standard.",
        roles=[
            _preset_role(
                role_id="benchmark_inspector",
                name="Benchmark Inspector",
                archetype="inspector",
                prompt_ref=PROMPT_FILES["inspector"],
                role_definition_id="builtin:inspector",
                posture_notes="Read the existing benchmark or contract proof first and identify the highest-leverage failing signal.",
            ),
            _preset_role(
                role_id="builder",
                archetype="builder",
                prompt_ref=PROMPT_FILES["builder"],
                role_definition_id="builtin:builder",
                posture_notes="Make the smallest change that targets the benchmark-backed blocker without changing the evidence standard.",
            ),
            _preset_role(
                role_id="regression_inspector",
                name="Regression Inspector",
                archetype="inspector",
                prompt_ref=PROMPT_FILES["inspector"],
                role_definition_id="builtin:inspector",
                posture_notes="Re-run or inspect the same evidence path and surface regressions or measurement gaps.",
            ),
            _preset_role(
                role_id="gatekeeper",
                archetype="gatekeeper",
                prompt_ref=PROMPT_FILES["gatekeeper"],
                role_definition_id="builtin:gatekeeper",
                posture_notes="Pass only when the repeatable evidence improves enough and residual risk is explicitly acceptable.",
            ),
        ],
        steps=[
            _preset_step(step_id="benchmark_inspection_step", role_id="benchmark_inspector", archetype="inspector"),
            _preset_step(
                step_id="builder_step",
                role_id="builder",
                archetype="builder",
                inputs={"handoffs_from": ["benchmark_inspection_step"], "iteration_memory": "summary_only"},
            ),
            _preset_step(
                step_id="regression_inspection_step",
                role_id="regression_inspector",
                archetype="inspector",
                inputs={
                    "handoffs_from": ["benchmark_inspection_step", "builder_step"],
                    "evidence_query": {"archetypes": ["inspector", "builder"], "limit": 20},
                },
            ),
            _preset_step(
                step_id="gatekeeper_step",
                role_id="gatekeeper",
                archetype="gatekeeper",
                on_pass="finish_run",
                inputs={
                    "handoffs_from": ["benchmark_inspection_step", "regression_inspection_step"],
                    "evidence_query": {"archetypes": ["inspector", "builder"], "limit": 24},
                },
            ),
        ],
    ),
    "build_first": _workflow_preset_definition(
        label_zh="先构建，再验收",
        label_en="Build First",
        description_zh="Builder -> Inspector -> GateKeeper -> Guide",
        description_en="Builder -> Inspector -> GateKeeper -> Guide",
        scenario_zh="适合端到端目标已经明确，但如果没有 loop，人类会在每接上一层之后都回来确认“第一条完整路径到底能不能作为基线”的长程任务。",
        scenario_en="Best for long tasks where the end-to-end target is already clear, but without a loop humans would keep coming back after every partial hookup to decide whether the first full path is finally baseline-worthy.",
        choice_zh="选它，而不是 Inspect First 或 Triage First，因为现在真正稀缺的不是更多诊断，而是第一条能让人少回来确认的完整路径。",
        choice_en="Choose this over Inspect First or Triage First when the scarce thing is not more diagnosis, but the first complete path that can spare humans repeated check-ins.",
        decision_zh="先让 Builder 跑出第一条完整路径，别让人类在每一层接通后都回来确认。",
        decision_en="Let Builder land the first complete path before humans have to re-check every newly connected layer.",
        visible=False,
        roles=[
            _preset_role(role_id="builder", archetype="builder", prompt_ref=PROMPT_FILES["builder"], role_definition_id="builtin:builder"),
            _preset_role(role_id="inspector", archetype="inspector", prompt_ref=PROMPT_FILES["inspector"], role_definition_id="builtin:inspector"),
            _preset_role(role_id="gatekeeper", archetype="gatekeeper", prompt_ref=PROMPT_FILES["gatekeeper"], role_definition_id="builtin:gatekeeper"),
            _preset_role(role_id="guide", archetype="guide", prompt_ref=PROMPT_FILES["guide"], role_definition_id="builtin:guide"),
        ],
        steps=[
            _preset_step(step_id="builder_step", role_id="builder", archetype="builder"),
            _preset_step(step_id="inspector_step", role_id="inspector", archetype="inspector"),
            _preset_step(step_id="gatekeeper_step", role_id="gatekeeper", archetype="gatekeeper", on_pass="finish_run"),
            _preset_step(step_id="guide_step", role_id="guide", archetype="guide"),
        ],
    ),
    "inspect_first": _workflow_preset_definition(
        label_zh="先巡检，再构建",
        label_en="Inspect First",
        description_zh="Inspector -> Builder -> GateKeeper -> Guide",
        description_en="Inspector -> Builder -> GateKeeper -> Guide",
        scenario_zh="适合失败面已经出现，但如果没有 loop，人类会反复回来追问“你到底在修哪一层”的长程排障任务。",
        scenario_en="Best for long debugging work where the failure shape is visible, but without a loop humans would keep coming back to ask which layer the repair is actually targeting.",
        choice_zh="选它，而不是 Build First，因为现在真正稀缺的是证据，不是更多代码；也不是 Triage First，因为失败路径已经收敛，只差把根因钉住。",
        choice_en="Choose this over Build First when the scarce thing is evidence rather than more code, and over Triage First when the failing path is already narrowed but the root cause still is not.",
        decision_zh="先让 Inspector 把根因证据钉住，别让人类反复回来纠正 Builder 在修哪一层。",
        decision_en="Let Inspector pin down root-cause evidence before humans have to keep correcting which layer Builder is touching.",
        visible=False,
        roles=[
            _preset_role(role_id="inspector", archetype="inspector", prompt_ref=PROMPT_FILES["inspector"], role_definition_id="builtin:inspector"),
            _preset_role(role_id="builder", archetype="builder", prompt_ref=PROMPT_FILES["builder"], role_definition_id="builtin:builder"),
            _preset_role(role_id="gatekeeper", archetype="gatekeeper", prompt_ref=PROMPT_FILES["gatekeeper"], role_definition_id="builtin:gatekeeper"),
            _preset_role(role_id="guide", archetype="guide", prompt_ref=PROMPT_FILES["guide"], role_definition_id="builtin:guide"),
        ],
        steps=[
            _preset_step(step_id="inspector_step", role_id="inspector", archetype="inspector"),
            _preset_step(step_id="builder_step", role_id="builder", archetype="builder"),
            _preset_step(step_id="gatekeeper_step", role_id="gatekeeper", archetype="gatekeeper", on_pass="finish_run"),
            _preset_step(step_id="guide_step", role_id="guide", archetype="guide"),
        ],
    ),
    "benchmark_loop": _workflow_preset_definition(
        label_zh="基准先行",
        label_en="Benchmark Loop",
        description_zh="GateKeeper (benchmark) -> Builder",
        description_en="GateKeeper (benchmark) -> Builder",
        scenario_zh="适合下一步必须由最新 benchmark 决定，否则人类会在每次评测后重新回来分配优化方向的长期任务。",
        scenario_en="Best when the next move must come from the latest benchmark, otherwise humans end up returning after every evaluation to reassign the optimization direction.",
        choice_zh="选它，而不是 Build First 或 Repair Loop，因为这里真正稀缺的是最新测量结果，而不是人的直觉判断。",
        choice_en="Choose this over Build First or Repair Loop when the scarce thing is the newest measured result, not another round of human intuition.",
        decision_zh="先读 benchmark，再决定下一步，好让人类不用在每轮评测后手动重排方向。",
        decision_en="Read the benchmark first so humans do not have to manually reshuffle the next move after every evaluation.",
        visible=False,
        roles=[
            _preset_role(role_id="gatekeeper", archetype="gatekeeper", prompt_ref=PROMPT_FILES["gatekeeper-benchmark"], role_definition_id="builtin:gatekeeper"),
            _preset_role(role_id="builder", archetype="builder", prompt_ref=PROMPT_FILES["builder"], role_definition_id="builtin:builder"),
        ],
        steps=[
            _preset_step(step_id="gatekeeper_step", role_id="gatekeeper", archetype="gatekeeper", on_pass="finish_run"),
            _preset_step(step_id="builder_step", role_id="builder", archetype="builder"),
        ],
    ),
    "quality_gate": _workflow_preset_definition(
        label_zh="质量闸门",
        label_en="Quality Gate",
        description_zh="Builder -> Inspector -> GateKeeper(finish)",
        description_en="Builder -> Inspector -> GateKeeper(finish)",
        scenario_zh="适合发布前最后一轮收口：Builder 补完已知缺口，Inspector 按验收点检查，GateKeeper 给出可发或不可发判断。",
        scenario_en="Best for the final release pass: Builder closes known gaps, Inspector checks the acceptance surface, and GateKeeper makes the release call.",
        choice_zh="当实现已经基本齐了，只差最后一轮交付与放行判断时才选它。它不是默认核心流程，只保留给兼容旧流程或少数发布前场景。",
        choice_en="Use this only when the implementation is already nearly complete and the remaining job is a final release decision. It stays for compatibility, not as a default core flow.",
        visible=False,
        roles=[
            _preset_role(role_id="builder", archetype="builder", prompt_ref=PROMPT_FILES["builder"], role_definition_id="builtin:builder"),
            _preset_role(role_id="inspector", archetype="inspector", prompt_ref=PROMPT_FILES["inspector"], role_definition_id="builtin:inspector"),
            _preset_role(role_id="gatekeeper", archetype="gatekeeper", prompt_ref=PROMPT_FILES["gatekeeper"], role_definition_id="builtin:gatekeeper"),
        ],
        steps=[
            _preset_step(step_id="builder_step", role_id="builder", archetype="builder"),
            _preset_step(step_id="inspector_step", role_id="inspector", archetype="inspector"),
            _preset_step(step_id="gatekeeper_step", role_id="gatekeeper", archetype="gatekeeper", on_pass="finish_run"),
        ],
    ),
    "triage_first": _workflow_preset_definition(
        label_zh="先诊断再推进",
        label_en="Triage First",
        description_zh="Inspector -> Guide -> Builder -> GateKeeper(finish)",
        description_en="Inspector -> Guide -> Builder -> GateKeeper(finish)",
        scenario_zh="适合现象很多、方向还散，如果没有 loop，人类会不断回来决定这轮到底在解决什么的长程任务。",
        scenario_en="Best for long tasks where symptoms are numerous and direction is still diffuse, so without a loop humans would keep returning just to decide what this round is actually solving.",
        choice_zh="选它，而不是 Inspect First，因为现在连本轮主问题都还没定义清楚；先让 Inspector 和 Guide 把这轮该修的切片收出来，才能减少人类反复定方向。",
        choice_en="Choose this over Inspect First when this round's main problem is still undefined and Inspector plus Guide must first carve out the slice worth fixing, so humans do not have to keep redefining the direction.",
        decision_zh="先把本轮问题收窄成一个切片，别让人类反复回来决定“这轮到底修什么”。",
        decision_en="Narrow this round to one repair slice before humans have to keep returning to decide what the round is even about.",
        visible=False,
        roles=[
            _preset_role(role_id="inspector", archetype="inspector", prompt_ref=PROMPT_FILES["inspector"], role_definition_id="builtin:inspector"),
            _preset_role(role_id="guide", archetype="guide", prompt_ref=PROMPT_FILES["guide"], role_definition_id="builtin:guide"),
            _preset_role(role_id="builder", archetype="builder", prompt_ref=PROMPT_FILES["builder"], role_definition_id="builtin:builder"),
            _preset_role(role_id="gatekeeper", archetype="gatekeeper", prompt_ref=PROMPT_FILES["gatekeeper"], role_definition_id="builtin:gatekeeper"),
        ],
        steps=[
            _preset_step(step_id="inspector_step", role_id="inspector", archetype="inspector"),
            _preset_step(step_id="guide_step", role_id="guide", archetype="guide"),
            _preset_step(step_id="builder_step", role_id="builder", archetype="builder"),
            _preset_step(step_id="gatekeeper_step", role_id="gatekeeper", archetype="gatekeeper", on_pass="finish_run"),
        ],
    ),
    "repair_loop": _workflow_preset_definition(
        label_zh="修复回路",
        label_en="Repair Loop",
        description_zh="Builder -> [Regression Inspector + Contract Inspector] -> Guide -> Builder -> GateKeeper",
        description_en="Builder -> [Regression Inspector + Contract Inspector] -> Guide -> Builder -> GateKeeper",
        scenario_zh="适合从一开始就知道一轮修复不够，如果没有 loop，人类会在每轮后重新进来判断第二轮怎么修的长程任务。",
        scenario_en="Best for long tasks where you already know one repair pass will not be enough, so without a loop humans would have to re-enter after each round to decide how the next repair should change.",
        choice_zh="当你已经预期一轮修复不够，而且第一轮改动本身就是下一轮证据来源时选择它。",
        choice_en="Choose this when you already expect one pass not to be enough, and when the first code change is itself the only way to surface the next evidence.",
        decision_zh="先打一轮，再用复查结果决定第二轮，减少人类在每轮后重新指路。",
        decision_en="Ship the first repair, then let fresh evidence shape the second one so humans do not have to keep stepping back in to redirect it.",
        roles=[
            _preset_role(role_id="builder", archetype="builder", prompt_ref=PROMPT_FILES["builder"], role_definition_id="builtin:builder"),
            _preset_role(
                role_id="regression_inspector",
                name="Regression Inspector",
                archetype="inspector",
                prompt_ref=PROMPT_FILES["inspector"],
                role_definition_id="builtin:inspector",
                posture_notes="Compare the latest attempt against the pre-repair evidence and identify the strongest remaining regression.",
            ),
            _preset_role(
                role_id="contract_inspector",
                name="Contract Inspector",
                archetype="inspector",
                prompt_ref=PROMPT_FILES["inspector"],
                role_definition_id="builtin:inspector",
                posture_notes="Check whether the repair still respects the task contract, guardrails, and fake-done risks.",
            ),
            _preset_role(role_id="guide", archetype="guide", prompt_ref=PROMPT_FILES["guide"], role_definition_id="builtin:guide"),
            _preset_role(role_id="gatekeeper", archetype="gatekeeper", prompt_ref=PROMPT_FILES["gatekeeper"], role_definition_id="builtin:gatekeeper"),
        ],
        steps=[
            _preset_step(step_id="builder_step", role_id="builder", archetype="builder"),
            _preset_step(
                step_id="regression_inspection_step",
                role_id="regression_inspector",
                archetype="inspector",
                parallel_group="repair_review",
                inputs={
                    "handoffs_from": ["builder_step"],
                    "evidence_query": {"archetypes": ["builder"], "limit": 12},
                    "iteration_memory": "summary_only",
                },
            ),
            _preset_step(
                step_id="contract_inspection_step",
                role_id="contract_inspector",
                archetype="inspector",
                parallel_group="repair_review",
                inputs={
                    "handoffs_from": ["builder_step"],
                    "evidence_query": {"archetypes": ["builder"], "limit": 12},
                    "iteration_memory": "summary_only",
                },
            ),
            _preset_step(
                step_id="guide_step",
                role_id="guide",
                archetype="guide",
                inputs={"handoffs_from": ["regression_inspection_step", "contract_inspection_step"]},
            ),
            _preset_step(
                step_id="builder_repair_step",
                role_id="builder",
                archetype="builder",
                inputs={"handoffs_from": ["guide_step"], "iteration_memory": "same_step"},
            ),
            _preset_step(
                step_id="gatekeeper_step",
                role_id="gatekeeper",
                archetype="gatekeeper",
                on_pass="finish_run",
                inputs={
                    "handoffs_from": ["regression_inspection_step", "contract_inspection_step", "builder_repair_step"],
                    "evidence_query": {"archetypes": ["inspector", "builder"], "limit": 24},
                },
            ),
        ],
    ),
    "fast_lane": _workflow_preset_definition(
        label_zh="快速通道",
        label_en="Fast Lane",
        description_zh="Builder -> GateKeeper(finish)",
        description_en="Builder -> GateKeeper(finish)",
        scenario_zh="适合范围不大但很紧急的热修：让 Builder 快速修掉，再由 GateKeeper 立刻判断，同时把证据链留下来。",
        scenario_en="Best for narrow but urgent hotfixes where Builder can patch quickly, GateKeeper can judge immediately, and the team still wants the evidence trail.",
        choice_zh="它更像兼容旧用法的短回路，不再作为默认核心流程推荐；如果任务真这么短，很多时候直接单次执行更合适。",
        choice_en="This stays mainly as a compatibility short loop, not a default core flow. If the task is really that short, a one-shot run is often better.",
        visible=False,
        roles=[
            _preset_role(role_id="builder", archetype="builder", prompt_ref=PROMPT_FILES["builder"], role_definition_id="builtin:builder"),
            _preset_role(role_id="gatekeeper", archetype="gatekeeper", prompt_ref=PROMPT_FILES["gatekeeper"], role_definition_id="builtin:gatekeeper"),
        ],
        steps=[
            _preset_step(step_id="builder_step", role_id="builder", archetype="builder"),
            _preset_step(step_id="gatekeeper_step", role_id="gatekeeper", archetype="gatekeeper", on_pass="finish_run"),
        ],
    ),
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


def normalize_role_display_name(name: str | None, archetype: str | None = None) -> str:
    raw_name = str(name or "").strip()
    if not raw_name:
        return ""
    if archetype:
        normalized_archetype = normalize_archetype(archetype)
        canonical = display_name_for_archetype(normalized_archetype, locale="en")
        aliases = {alias.lower() for alias in ARCHETYPE_DISPLAY_ALIASES.get(normalized_archetype, set())}
        lowered = raw_name.lower()
        if lowered == canonical.lower() or lowered in aliases:
            return canonical
        return raw_name
    lowered = raw_name.lower()
    for candidate in ARCHETYPES:
        canonical = display_name_for_archetype(candidate, locale="en")
        aliases = {alias.lower() for alias in ARCHETYPE_DISPLAY_ALIASES.get(candidate, set())}
        if lowered == canonical.lower() or lowered in aliases:
            return canonical
    return raw_name


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


def builtin_prompt_markdown(prompt_ref: str, *, locale: str | None = None) -> str:
    path = prompt_asset_path(PROMPT_ASSET_DIR, localized_prompt_ref(prompt_ref, locale))
    if not path.exists():
        raise WorkflowError(f"unknown built-in prompt template: {prompt_ref}")
    return path.read_text(encoding="utf-8")


def builtin_prompt_markdown_by_locale(prompt_ref: str) -> dict[str, str]:
    return {
        "en": builtin_prompt_markdown(prompt_ref, locale="en"),
        "zh": builtin_prompt_markdown(prompt_ref, locale="zh"),
    }


def builtin_spec_practice(name: str, *, locale: str | None = None) -> dict[str, str]:
    preset_name = str(name or "").strip()
    if preset_name not in WORKFLOW_PRESETS:
        raise WorkflowError(f"unknown workflow preset: {name}")
    normalized_locale = normalize_prompt_locale(locale)
    localized_path = SPEC_PRACTICE_ASSET_DIR / f"{preset_name}.zh.md"
    default_path = SPEC_PRACTICE_ASSET_DIR / f"{preset_name}.md"
    path = localized_path if normalized_locale == "zh" and localized_path.exists() else default_path
    if not path.exists():
        raise WorkflowError(f"missing built-in spec practice: {preset_name}")
    markdown_text = path.read_text(encoding="utf-8").strip()
    match = PROMPT_FRONT_MATTER_RE.match(markdown_text)
    if not match:
        raise WorkflowError(f"invalid built-in spec practice: {preset_name}")
    try:
        metadata = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        raise WorkflowError(f"invalid built-in spec practice front matter: {preset_name}") from exc
    if not isinstance(metadata, dict):
        raise WorkflowError(f"built-in spec practice front matter must decode to a mapping: {preset_name}")
    summary = str(metadata.get("summary", "")).strip()
    practice_markdown = match.group(2).strip()
    if not summary or not practice_markdown:
        raise WorkflowError(f"built-in spec practice requires summary and markdown body: {preset_name}")
    return {"summary": summary, "markdown": practice_markdown}


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


def preset_names(*, include_hidden: bool = False) -> list[str]:
    names: list[str] = []
    for preset_name, preset in WORKFLOW_PRESETS.items():
        if include_hidden or bool(preset.get("visible", True)):
            names.append(preset_name)
    return names


def workflow_preset_copy(name: str) -> dict[str, str]:
    preset_name = str(name or DEFAULT_WORKFLOW_PRESET).strip() or DEFAULT_WORKFLOW_PRESET
    preset = WORKFLOW_PRESETS.get(preset_name)
    if not preset:
        raise WorkflowError(f"unknown workflow preset: {name}")
    practice_en = builtin_spec_practice(preset_name, locale="en")
    practice_zh = builtin_spec_practice(preset_name, locale="zh")
    return {
        "label_zh": str(preset["label_zh"]),
        "label_en": str(preset["label_en"]),
        "description_zh": str(preset["description_zh"]),
        "description_en": str(preset["description_en"]),
        "scenario_zh": str(preset["scenario_zh"]),
        "scenario_en": str(preset["scenario_en"]),
        "choice_zh": str(preset.get("choice_zh", "")),
        "choice_en": str(preset.get("choice_en", "")),
        "decision_zh": str(preset.get("decision_zh", "")),
        "decision_en": str(preset.get("decision_en", "")),
        "visible": "true" if bool(preset.get("visible", True)) else "false",
        "spec_practice_summary_zh": practice_zh["summary"],
        "spec_practice_summary_en": practice_en["summary"],
        "spec_practice_markdown_zh": practice_zh["markdown"],
        "spec_practice_markdown_en": practice_en["markdown"],
    }


def workflow_preset_options(*, include_hidden: bool = False) -> list[dict[str, str]]:
    return [
        {
            "id": preset_name,
            **workflow_preset_copy(preset_name),
        }
        for preset_name in preset_names(include_hidden=include_hidden)
    ]


def build_preset_workflow(name: str = DEFAULT_WORKFLOW_PRESET, *, role_models: dict[str, str] | None = None) -> dict:
    preset_name = str(name or DEFAULT_WORKFLOW_PRESET).strip() or DEFAULT_WORKFLOW_PRESET
    if preset_name not in WORKFLOW_PRESETS:
        raise WorkflowError(f"unknown workflow preset: {preset_name}")
    overrides = normalize_role_models(role_models)
    preset = json.loads(json.dumps(WORKFLOW_PRESETS[preset_name]["workflow"], ensure_ascii=False))
    for role in preset["roles"]:
        override = overrides.get(role["id"]) or overrides.get(role["archetype"])
        if override:
            role["model"] = override
    workflow = {
        "version": 1,
        "preset": preset_name,
        "collaboration_intent": str(preset.get("collaboration_intent", "") or ""),
        "roles": preset["roles"],
        "steps": preset["steps"],
    }
    if preset.get("controls"):
        workflow["controls"] = list(preset.get("controls") or [])
    return workflow


def workflow_warnings(workflow: dict) -> list[str]:
    role_by_id = {role["id"]: role for role in workflow.get("roles", [])}
    steps = list(workflow.get("steps", []))
    warnings: list[str] = []
    if not has_finish_gatekeeper_step(workflow):
        warnings.append(
            "This workflow has no GateKeeper finish step, so it should be paired with round-based completion or updated before gate-based execution."
        )
    gate_before_builder = False
    gate_after_builder_without_inspector = False
    seen_builder = False
    seen_inspector_after_builder = False
    for index, step in enumerate(steps):
        role = role_by_id.get(step["role_id"], {})
        archetype = role.get("archetype")
        if archetype == "builder":
            seen_builder = True
            seen_inspector_after_builder = False
        elif archetype == "inspector" and seen_builder:
            seen_inspector_after_builder = True
        elif archetype == "gatekeeper":
            if any(
                role_by_id.get(other["role_id"], {}).get("archetype") == "builder"
                for other in steps[index + 1 :]
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
        role = role_by_id.get(str(raw_step.get("role_id", "")).strip())
        if not role or role.get("archetype") != "gatekeeper":
            continue
        if str(raw_step.get("on_pass", "continue") or "continue").strip() == "finish_run":
            return True
    return False


def validate_workflow_parallel_groups(steps: list[dict[str, Any]], role_by_id: dict[str, dict[str, Any]]) -> None:
    seen_closed_groups: set[str] = set()
    active_group = ""
    for step in steps:
        group = str(step.get("parallel_group") or "").strip()
        role = role_by_id.get(str(step.get("role_id") or ""))
        archetype = str((role or {}).get("archetype") or "")
        if not group:
            if active_group:
                seen_closed_groups.add(active_group)
                active_group = ""
            continue
        if group in seen_closed_groups and group != active_group:
            raise WorkflowError("workflow parallel_group steps must be contiguous")
        if active_group and group != active_group:
            seen_closed_groups.add(active_group)
        active_group = group
        action_policy = step.get("action_policy") if isinstance(step.get("action_policy"), Mapping) else {}
        if str(action_policy.get("workspace") or "").strip() == "workspace_write":
            raise WorkflowError("workflow parallel_group steps must be read-only")
        if bool(action_policy.get("can_finish_run")):
            raise WorkflowError("workflow parallel_group steps may not finish runs")
        if archetype not in PARALLEL_GROUP_ARCHETYPES:
            raise WorkflowError("workflow parallel_group currently supports inspector and custom steps only")
    if active_group:
        seen_closed_groups.add(active_group)

    counts: dict[str, int] = {}
    for step in steps:
        group = str(step.get("parallel_group") or "").strip()
        if group:
            counts[group] = counts.get(group, 0) + 1
    singletons = [group for group, count in counts.items() if count < 2]
    if singletons:
        raise WorkflowError("workflow parallel_group must contain at least two contiguous steps")


def normalize_workflow(workflow: dict[str, Any] | None, *, role_models: dict[str, str] | None = None) -> dict:
    if workflow is None:
        normalized = build_preset_workflow(DEFAULT_WORKFLOW_PRESET, role_models=role_models)
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
        role_id = normalize_workflow_identifier(
            raw_role.get("id") or f"role_{index:03d}",
            field_name="workflow role id",
        )
        if role_id in role_ids:
            raise WorkflowError(f"duplicate workflow role id: {role_id}")
        archetype = normalize_archetype(str(raw_role.get("archetype", "")))
        prompt_ref = normalize_prompt_ref(raw_role.get("prompt_ref") or PROMPT_FILES[archetype])
        raw_name = str(raw_role.get("name", "")).strip()
        name = normalize_role_display_name(raw_name, archetype) or display_name_for_archetype(archetype, locale="en")
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
            "posture_notes": str(raw_role.get("posture_notes", "") or "").strip(),
        }
        if role_uses_execution_snapshot(raw_role):
            execution_settings = normalize_role_execution_settings(raw_role)
            role_entry.update(execution_settings)
            if model:
                role_entry["model"] = model
        roles.append(role_entry)

    steps: list[dict[str, Any]] = []
    step_ids: set[str] = set()
    for index, raw_step in enumerate(raw_steps, start=1):
        if not isinstance(raw_step, dict):
            raise WorkflowError("workflow steps must be objects")
        role_id = normalize_workflow_identifier(raw_step.get("role_id"), field_name="workflow step role_id")
        if role_id not in role_ids:
            raise WorkflowError(f"workflow step references unknown role_id: {role_id}")
        step_id = normalize_workflow_identifier(
            raw_step.get("id") or f"step_{index:03d}",
            field_name="workflow step id",
        )
        if step_id in step_ids:
            raise WorkflowError(f"duplicate workflow step id: {step_id}")
        role = next(item for item in roles if item["id"] == role_id)
        on_pass = normalize_step_on_pass(
            raw_step.get("on_pass"),
            archetype=role["archetype"],
            default="continue",
        )
        model = str(raw_step.get("model", "")).strip()
        inherit_session = normalize_step_inherit_session(
            raw_step.get("inherit_session"),
            archetype=role["archetype"],
        )
        extra_cli_args = str(raw_step.get("extra_cli_args", "") or "").strip()
        validate_extra_cli_args_text(extra_cli_args)
        step_entry = {
            "id": step_id,
            "role_id": role_id,
            "on_pass": on_pass,
            "model": model,
            "inherit_session": inherit_session,
            "extra_cli_args": extra_cli_args,
            "action_policy": normalize_step_action_policy(
                raw_step.get("action_policy"),
                archetype=role["archetype"],
                on_pass=on_pass,
            ),
        }
        parallel_group = normalize_step_parallel_group(raw_step.get("parallel_group"))
        if parallel_group:
            step_entry["parallel_group"] = parallel_group
        inputs = normalize_step_inputs(raw_step.get("inputs"))
        if inputs:
            step_entry["inputs"] = inputs
        steps.append(step_entry)
        step_ids.add(step_id)
    role_by_id = {role["id"]: role for role in roles}
    validate_workflow_parallel_groups(steps, role_by_id)
    controls = normalize_workflow_controls(raw.get("controls"), role_by_id=role_by_id)

    normalized = {
        "version": int(raw.get("version", 1) or 1),
        "preset": str(raw.get("preset", "")).strip(),
        "collaboration_intent": str(raw.get("collaboration_intent", "") or "").strip(),
        "roles": roles,
        "steps": steps,
    }
    if controls:
        normalized["controls"] = controls
    normalized["warnings"] = workflow_warnings(normalized)
    return normalized


def resolve_prompt_files(
    workflow: dict,
    provided_prompt_files: dict[str, str] | None = None,
) -> dict[str, str]:
    provided: dict[str, str] = {}
    for prompt_ref, markdown_text in dict(provided_prompt_files or {}).items():
        candidate = str(prompt_ref).strip()
        if not candidate:
            continue
        normalized_prompt_ref = normalize_prompt_ref(candidate)
        provided[normalized_prompt_ref] = str(markdown_text or "")
    resolved: dict[str, str] = {}
    for role in workflow.get("roles", []):
        prompt_ref = role["prompt_ref"]
        if prompt_ref not in resolved:
            if prompt_ref in provided:
                resolved[prompt_ref] = provided[prompt_ref]
            else:
                try:
                    resolved[prompt_ref] = builtin_prompt_markdown(prompt_ref)
                except WorkflowError as exc:
                    raise WorkflowError(f"missing prompt file for role {role['id']}: {prompt_ref}") from exc
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
