from __future__ import annotations

from dataclasses import asdict, dataclass

EXECUTOR_KINDS = ("codex", "claude", "opencode")
EXECUTOR_KIND_ALIASES = {
    "codex": "codex",
    "openai-codex": "codex",
    "claude": "claude",
    "claudecode": "claude",
    "claude-code": "claude",
    "claude_code": "claude",
    "opencode": "opencode",
    "open-code": "opencode",
    "open_code": "opencode",
}
EXECUTOR_MODES = ("preset", "command")


@dataclass(frozen=True, slots=True)
class ExecutorProfile:
    key: str
    label: str
    label_zh: str
    cli_name: str
    default_model: str
    model_placeholder_zh: str
    model_placeholder_en: str
    model_help_zh: str
    model_help_en: str
    effort_label_zh: str
    effort_label_en: str
    effort_help_zh: str
    effort_help_en: str
    effort_options: tuple[str, ...]
    effort_default: str
    effort_optional: bool = False
    preset_effort_visible: bool = True
    command_args_template: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


EXECUTOR_PROFILES: dict[str, ExecutorProfile] = {
    "codex": ExecutorProfile(
        key="codex",
        label="Codex",
        label_zh="Codex",
        cli_name="codex",
        default_model="gpt-5.4",
        model_placeholder_zh="gpt-5.4",
        model_placeholder_en="gpt-5.4",
        model_help_zh="使用本机 Codex CLI。模型名通常是 OpenAI 的编码模型，例如 gpt-5.4。",
        model_help_en="Uses the local Codex CLI. The model is typically an OpenAI coding model such as gpt-5.4.",
        effort_label_zh="推理强度",
        effort_label_en="Reasoning effort",
        effort_help_zh="Codex 支持 low、medium、high、xhigh。",
        effort_help_en="Codex supports low, medium, high, and xhigh.",
        effort_options=("low", "medium", "high", "xhigh"),
        effort_default="medium",
        command_args_template=(
            "exec",
            "--json",
            "--skip-git-repo-check",
            "--cd",
            "{workdir}",
            "--sandbox",
            "{sandbox}",
            "--output-schema",
            "{schema_path}",
            "--output-last-message",
            "{output_path}",
            "--model",
            "gpt-5.4",
            "-c",
            'model_reasoning_effort="medium"',
            "{prompt}",
        ),
    ),
    "claude": ExecutorProfile(
        key="claude",
        label="Claude Code",
        label_zh="Claude Code",
        cli_name="claude",
        default_model="",
        model_placeholder_zh="留空使用 Claude Code 当前默认模型，或填 sonnet / opus / 完整模型名",
        model_placeholder_en="Leave blank to use the current Claude Code default, or enter sonnet / opus / a full model name",
        model_help_zh="使用本机 Claude Code CLI。默认留空更稳妥；也可以显式填 sonnet / opus，或完整模型名。",
        model_help_en="Uses the local Claude Code CLI. Leaving the model blank is the safest default; you can also set sonnet / opus or a full model name explicitly.",
        effort_label_zh="推理强度",
        effort_label_en="Effort",
        effort_help_zh="Claude Code 支持 low、medium、high、max。旧的 xhigh 会自动映射为 max。",
        effort_help_en="Claude Code supports low, medium, high, and max. Legacy xhigh is mapped to max.",
        effort_options=("low", "medium", "high", "max"),
        effort_default="medium",
        command_args_template=(
            "--setting-sources",
            "local,project",
            "-p",
            "--output-format",
            "stream-json",
            "--include-partial-messages",
            "--no-session-persistence",
            "--permission-mode",
            "bypassPermissions",
            "--json-schema",
            "{json_schema}",
            "--model",
            "{model}",
            "--effort",
            "medium",
            "{prompt}",
        ),
    ),
    "opencode": ExecutorProfile(
        key="opencode",
        label="OpenCode",
        label_zh="OpenCode",
        cli_name="opencode",
        default_model="",
        model_placeholder_zh="provider/model，留空则使用 OpenCode 当前默认模型",
        model_placeholder_en="provider/model, or leave blank to use the current OpenCode default",
        model_help_zh="使用本机 OpenCode CLI。模型名格式通常是 provider/model，例如 anthropic/claude-sonnet-4-20250514。",
        model_help_en="Uses the local OpenCode CLI. The model is usually provider/model, for example anthropic/claude-sonnet-4-20250514.",
        effort_label_zh="Variant（可选）",
        effort_label_en="Variant (optional)",
        effort_help_zh="OpenCode 走 provider-specific variant。可留空使用默认，也可以填 high、max、minimal、xhigh 等。",
        effort_help_en="OpenCode uses provider-specific variants. Leave it blank for the default, or set values like high, max, minimal, or xhigh.",
        effort_options=("", "high", "max", "minimal", "low", "medium", "xhigh", "none"),
        effort_default="",
        effort_optional=True,
        preset_effort_visible=False,
        command_args_template=(
            "run",
            "--format",
            "json",
            "--dir",
            "{workdir}",
            "--dangerously-skip-permissions",
            "{prompt}",
        ),
    ),
}

_CODEX_ALIASES = {"minimal": "low"}
_CLAUDE_ALIASES = {"minimal": "low", "xhigh": "max"}
_OPENCODE_BLANK_ALIASES = {"auto", "default"}


def normalize_executor_kind(value: str | None) -> str:
    normalized = (value or "codex").strip().lower()
    if normalized in EXECUTOR_KIND_ALIASES:
        return EXECUTOR_KIND_ALIASES[normalized]
    supported = ", ".join(EXECUTOR_KINDS)
    raise ValueError(f"unsupported executor kind: {value!r}. Expected one of: {supported}")


def executor_profile(kind: str | None) -> ExecutorProfile:
    normalized = normalize_executor_kind(kind)
    return EXECUTOR_PROFILES[normalized]


def list_executor_profiles() -> list[dict[str, object]]:
    return [EXECUTOR_PROFILES[key].to_dict() for key in EXECUTOR_KINDS]


def normalize_executor_mode(value: str | None) -> str:
    normalized = (value or "preset").strip().lower()
    if normalized in EXECUTOR_MODES:
        return normalized
    supported = ", ".join(EXECUTOR_MODES)
    raise ValueError(f"unsupported executor mode: {value!r}. Expected one of: {supported}")


def normalize_reasoning_setting(value: str | None, *, executor_kind: str) -> str:
    profile = executor_profile(executor_kind)
    raw = (value or "").strip().lower()
    if profile.key == "codex":
        normalized = _CODEX_ALIASES.get(raw or profile.effort_default, raw or profile.effort_default)
        if normalized not in profile.effort_options:
            supported = ", ".join(profile.effort_options)
            raise ValueError(f"unsupported reasoning effort for Codex: {value!r}. Expected one of: {supported}")
        return normalized
    if profile.key == "claude":
        normalized = _CLAUDE_ALIASES.get(raw or profile.effort_default, raw or profile.effort_default)
        if normalized not in profile.effort_options:
            supported = ", ".join(profile.effort_options)
            raise ValueError(f"unsupported reasoning effort for Claude Code: {value!r}. Expected one of: {supported}")
        return normalized
    if not raw or raw in _OPENCODE_BLANK_ALIASES:
        return ""
    return raw


def coerce_reasoning_setting(value: str | None, *, executor_kind: str) -> str:
    profile = executor_profile(executor_kind)
    try:
        return normalize_reasoning_setting(value, executor_kind=executor_kind)
    except ValueError:
        return profile.effort_default
