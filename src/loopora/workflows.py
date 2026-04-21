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
STEP_EXECUTION_FIELDS = (
    "on_pass",
    "model",
    "inherit_session",
    "extra_cli_args",
)


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
) -> dict[str, str]:
    return {
        "id": role_id,
        "name": ARCHETYPE_DISPLAY[archetype]["en"],
        "archetype": archetype,
        "prompt_ref": prompt_ref,
        "role_definition_id": role_definition_id,
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
) -> dict[str, Any]:
    defaults = default_step_execution_settings(archetype=archetype)
    return {
        "id": step_id,
        "role_id": role_id,
        "on_pass": normalize_step_on_pass(
            on_pass,
            archetype=archetype,
            default=defaults["on_pass"],
        ),
        "model": model,
        "inherit_session": normalize_step_inherit_session(
            inherit_session,
            archetype=archetype,
        ),
        "extra_cli_args": str(extra_cli_args or ""),
    }


WORKFLOW_PRESETS = {
    "build_first": _workflow_preset_definition(
        label_zh="先构建，再验收",
        label_en="Build First",
        description_zh="Builder -> Inspector -> GateKeeper -> Guide",
        description_en="Builder -> Inspector -> GateKeeper -> Guide",
        scenario_zh="适合目标已经明确，应该先让 Builder 把第一版真正跑起来，再由 Inspector 补证据、GateKeeper 收口，只有卡住时才需要 Guide 指方向的任务。",
        scenario_en="Best when the target is already clear and Builder should get the first real integration slice working before Inspector, GateKeeper, and Guide take over.",
        choice_zh="选它，而不是 Inspect First 或 Triage First，因为现在真正缺的不是更多诊断，而是第一条能跑通的真实路径。",
        choice_en="Choose this over Inspect First or Triage First when the missing piece is not more diagnosis, but the first real working slice.",
        decision_zh="Builder 先把第一条真实可用的路径跑起来。",
        decision_en="Builder should land the first real working slice.",
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
        scenario_zh="适合还不能急着改代码，得先让 Inspector 把失败现状和证据摸清，再交给 Builder 修、GateKeeper 判断的排障或接手任务。",
        scenario_en="Best when Builder should not touch code yet and Inspector must first pin down the failure with evidence before Builder repairs it and GateKeeper closes the loop.",
        choice_zh="选它，而不是 Build First，因为现在最缺的是证据；也不是 Triage First，因为失败路径已经大致清楚，只差把根因钉住。",
        choice_en="Choose this over Build First when evidence is missing, and over Triage First when the failing path is already known but the root cause is not.",
        decision_zh="Inspector 先把失败证据和根因钉住。",
        decision_en="Inspector should pin down failure evidence and root cause first.",
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
        scenario_zh="适合每一轮都要先看 benchmark 或评测结果，再决定 Builder 下一步怎么改的长期优化任务。",
        scenario_en="Best when every round should begin with a benchmark or evaluation result, and Builder should only optimize against the latest measured outcome.",
        choice_zh="选它，而不是 Build First 或 Repair Loop，因为这里决定下一步的不是直觉，而是最新分数和评测结果。",
        choice_en="Choose this over Build First or Repair Loop when the next move must be decided by the latest score, not by intuition.",
        decision_zh="先看 GateKeeper 的 benchmark 结果，再决定 Builder 下一步。",
        decision_en="Let GateKeeper read the benchmark before Builder moves again.",
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
        scenario_zh="适合问题还说不清楚，得先让 Inspector 收拢现状，再由 Guide 给出推进方向，最后交给 Builder 修、GateKeeper 收口的任务。",
        scenario_en="Best when the problem is still fuzzy, Inspector must narrow it down, Guide must turn that diagnosis into a concrete next move, and only then should Builder and GateKeeper act.",
        choice_zh="选它，而不是 Inspect First，因为这里连问题定义都还没收窄；先让 Guide 把模糊现状翻成行动方向更重要。",
        choice_en="Choose this over Inspect First when even the problem statement is still fuzzy and Guide needs to turn diagnosis into the first concrete move.",
        decision_zh="先让 Inspector 和 Guide 把问题收窄成一个可行动的方向。",
        decision_en="Let Inspector and Guide narrow the problem into one actionable direction.",
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
        description_zh="Builder -> Inspector -> Guide -> Builder -> GateKeeper(finish)",
        description_en="Builder -> Inspector -> Guide -> Builder -> GateKeeper(finish)",
        scenario_zh="适合一轮修复大概率不够的顽固问题：Builder 先打一轮，Inspector 和 Guide 看剩余缺口，再做第二轮修复和最终裁决。",
        scenario_en="Best when one repair pass is unlikely to be enough, so Builder needs a first pass before Inspector and Guide shape the second one and GateKeeper makes the final call.",
        choice_zh="选它，而不是 Build First，因为你已经预期一轮修复不够；也不是 Inspect First，因为第一轮改动本身就是拿下一轮证据的必要前提。",
        choice_en="Choose this over Build First when you already expect one repair pass not to be enough, and over Inspect First when the first code change is itself required to expose the next evidence.",
        decision_zh="Builder 修一轮后，再用复查结果决定第二轮怎么修。",
        decision_en="Use the first Builder pass to shape a second, evidence-backed repair pass.",
        roles=[
            _preset_role(role_id="builder", archetype="builder", prompt_ref=PROMPT_FILES["builder"], role_definition_id="builtin:builder"),
            _preset_role(role_id="inspector", archetype="inspector", prompt_ref=PROMPT_FILES["inspector"], role_definition_id="builtin:inspector"),
            _preset_role(role_id="guide", archetype="guide", prompt_ref=PROMPT_FILES["guide"], role_definition_id="builtin:guide"),
            _preset_role(role_id="gatekeeper", archetype="gatekeeper", prompt_ref=PROMPT_FILES["gatekeeper"], role_definition_id="builtin:gatekeeper"),
        ],
        steps=[
            _preset_step(step_id="builder_step", role_id="builder", archetype="builder"),
            _preset_step(step_id="inspector_step", role_id="inspector", archetype="inspector"),
            _preset_step(step_id="guide_step", role_id="guide", archetype="guide"),
            _preset_step(step_id="builder_repair_step", role_id="builder", archetype="builder"),
            _preset_step(step_id="gatekeeper_step", role_id="gatekeeper", archetype="gatekeeper", on_pass="finish_run"),
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
    preset_name = str(name or "build_first").strip() or "build_first"
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


def build_preset_workflow(name: str = "build_first", *, role_models: dict[str, str] | None = None) -> dict:
    preset_name = str(name or "build_first").strip() or "build_first"
    if preset_name not in WORKFLOW_PRESETS:
        raise WorkflowError(f"unknown workflow preset: {preset_name}")
    overrides = normalize_role_models(role_models)
    preset = json.loads(json.dumps(WORKFLOW_PRESETS[preset_name]["workflow"], ensure_ascii=False))
    for role in preset["roles"]:
        override = overrides.get(role["id"]) or overrides.get(role["archetype"])
        if override:
            role["model"] = override
    return {"version": 1, "preset": preset_name, "roles": preset["roles"], "steps": preset["steps"]}


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
        role_id = str(raw_step.get("role_id", "")).strip()
        if role_id not in role_ids:
            raise WorkflowError(f"workflow step references unknown role_id: {role_id}")
        step_id = str(raw_step.get("id", "")).strip() or f"step_{index:03d}"
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
        steps.append(
            {
                "id": step_id,
                "role_id": role_id,
                "on_pass": on_pass,
                "model": model,
                "inherit_session": inherit_session,
                "extra_cli_args": extra_cli_args,
            }
        )
        step_ids.add(step_id)

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
