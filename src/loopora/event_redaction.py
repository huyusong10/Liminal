from __future__ import annotations

import re
from collections.abc import Mapping

PROMPT_OMITTED = "<prompt omitted>"
JSON_SCHEMA_OMITTED = "<json schema omitted>"
SECRET_OMITTED = "<secret omitted>"
PAYLOAD_OMITTED = "<payload omitted>"
MAX_CODEX_MESSAGE_LENGTH = 4000
MAX_CODEX_ITEM_TEXT_LENGTH = 4000

_PROMPT_KEYS = {
    "compiled_prompt",
    "prompt",
    "prompt_markdown",
    "prompt_text",
    "system_prompt",
}
_JSON_SCHEMA_KEYS = {
    "input_schema",
    "json_schema",
    "output_schema",
    "schema",
    "schema_json",
}
_SECRET_KEYS = {
    "api_key",
    "apikey",
    "auth_token",
    "bearer_token",
    "password",
    "secret",
    "secret_token",
    "token",
}
_SECRET_KEY_SUFFIXES = ("_api_key", "_password", "_secret", "_token")
_SECRET_ARG_PATTERN = re.compile(
    r"(?i)(--(?:api-key|auth-token|bearer-token|password|secret(?:-token)?|token)(?:=|\s+))"
    r"(\"[^\"]*\"|'[^']*'|[^\s]+)"
)
_ENV_SECRET_PATTERN = re.compile(
    r"(?i)\b((?:OPENAI_API_KEY|ANTHROPIC_API_KEY|API_KEY|TOKEN|SECRET|PASSWORD)=)([^\s]+)"
)
_BEARER_SECRET_PATTERN = re.compile(r"(?i)\b((?:authorization:\s*)?bearer\s+)([A-Za-z0-9._~+/=-]+)")


def redact_run_event_payload(event_type: str, payload: Mapping[str, object] | None) -> dict:
    if not isinstance(payload, Mapping):
        return {}
    if str(event_type or "").strip() == "codex_event":
        return _redact_codex_event_payload(payload)
    return {
        str(key): _redact_value(str(key), value)
        for key, value in payload.items()
    }


def _redact_codex_event_payload(payload: Mapping[str, object]) -> dict:
    sanitized: dict[str, object] = {}
    omitted_keys: set[str] = set()
    passthrough_keys = {
        "type",
        "step_id",
        "step_order",
        "role",
        "role_name",
        "archetype",
        "iter",
        "prompt_omitted",
        "json_schema_omitted",
        "token_omitted",
        "command_truncated",
        "arg_count",
    }
    for key in passthrough_keys:
        if key in payload:
            sanitized[key] = _redact_container(payload[key])

    for key in ("message", "summary"):
        if key in payload:
            sanitized[key], was_truncated = _redact_preview_string(
                payload[key],
                max_length=MAX_CODEX_MESSAGE_LENGTH,
            )
            if was_truncated:
                sanitized[f"{key}_truncated"] = True

    if "error" in payload:
        sanitized["error"] = _redact_error(payload["error"])
    if "item" in payload:
        sanitized["item"] = _redact_codex_item(payload["item"])

    for raw_key in payload:
        key = str(raw_key)
        if key not in passthrough_keys and key not in {"message", "summary", "error", "item"}:
            omitted_keys.add(key)
    if omitted_keys:
        sanitized["payload_omitted"] = True
        sanitized["omitted_keys"] = sorted(omitted_keys)
    return sanitized


def _redact_error(value: object) -> object:
    if not isinstance(value, Mapping):
        message, was_truncated = _redact_preview_string(value, max_length=MAX_CODEX_MESSAGE_LENGTH)
        return {"message": message, "message_truncated": was_truncated} if was_truncated else {"message": message}
    sanitized: dict[str, object] = {}
    for key in ("message", "type", "code"):
        if key in value:
            sanitized[str(key)] = _redact_container(value[key])
    if not sanitized:
        sanitized["message"] = PAYLOAD_OMITTED
    return sanitized


def _redact_codex_item(value: object) -> dict:
    if not isinstance(value, Mapping):
        return {}
    item_type = str(value.get("type", "") or "").strip()
    sanitized: dict[str, object] = {"type": _redact_string(item_type)} if item_type else {}
    if item_type == "command_execution":
        if "command" in value:
            sanitized["command"], command_truncated = _redact_preview_string(
                value["command"],
                max_length=MAX_CODEX_MESSAGE_LENGTH,
            )
            if command_truncated:
                sanitized["command_truncated"] = True
        if "aggregated_output" in value:
            sanitized["aggregated_output"], output_truncated = _redact_preview_string(
                value["aggregated_output"],
                max_length=MAX_CODEX_ITEM_TEXT_LENGTH,
            )
            if output_truncated:
                sanitized["aggregated_output_truncated"] = True
        for key in ("exit_code", "status"):
            if key in value:
                sanitized[key] = _redact_container(value[key])
        return sanitized
    if item_type == "file_change":
        changes = value.get("changes")
        if isinstance(changes, list):
            sanitized["changes"] = [_redact_file_change(change) for change in changes if isinstance(change, Mapping)]
        return sanitized
    if item_type == "todo_list":
        items = value.get("items")
        if isinstance(items, list):
            sanitized["items"] = [_redact_todo_item(item) for item in items if isinstance(item, Mapping)]
        return sanitized
    if item_type == "agent_message":
        if "text" in value:
            sanitized["text"], text_truncated = _redact_preview_string(
                value["text"],
                max_length=MAX_CODEX_ITEM_TEXT_LENGTH,
            )
            if text_truncated:
                sanitized["text_truncated"] = True
        return sanitized
    if item_type:
        sanitized["payload_omitted"] = True
    return sanitized


def _redact_file_change(value: Mapping[str, object]) -> dict:
    sanitized: dict[str, object] = {}
    for key in ("path", "status", "operation", "kind"):
        if key in value:
            sanitized[key] = _redact_container(value[key])
    return sanitized


def _redact_todo_item(value: Mapping[str, object]) -> dict:
    sanitized: dict[str, object] = {}
    for key in ("text", "content", "title"):
        if key in value:
            sanitized[key], was_truncated = _redact_preview_string(
                value[key],
                max_length=MAX_CODEX_ITEM_TEXT_LENGTH,
            )
            if was_truncated:
                sanitized[f"{key}_truncated"] = True
    for key in ("completed", "status"):
        if key in value:
            sanitized[key] = _redact_container(value[key])
    return sanitized


def _normalized_key(key: str) -> str:
    return str(key or "").strip().lower().replace("-", "_")


def _redact_value(key: str, value: object) -> object:
    normalized_key = _normalized_key(key)
    if normalized_key in _PROMPT_KEYS:
        return PROMPT_OMITTED
    if normalized_key in _JSON_SCHEMA_KEYS:
        return JSON_SCHEMA_OMITTED
    if normalized_key in _SECRET_KEYS or normalized_key.endswith(_SECRET_KEY_SUFFIXES):
        return SECRET_OMITTED
    return _redact_container(value)


def _redact_container(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _redact_value(str(key), child) for key, child in value.items()}
    if isinstance(value, list):
        return [_redact_container(child) for child in value]
    if isinstance(value, tuple):
        return [_redact_container(child) for child in value]
    if isinstance(value, str):
        return _redact_string(value)
    return value


def _redact_string(value: str) -> str:
    redacted = _SECRET_ARG_PATTERN.sub(lambda match: f"{match.group(1)}{SECRET_OMITTED}", value)
    redacted = _ENV_SECRET_PATTERN.sub(lambda match: f"{match.group(1)}{SECRET_OMITTED}", redacted)
    return _BEARER_SECRET_PATTERN.sub(lambda match: f"{match.group(1)}{SECRET_OMITTED}", redacted)


def _redact_preview_string(value: object, *, max_length: int) -> tuple[str, bool]:
    redacted = _redact_string(str(value or ""))
    if len(redacted) <= max_length:
        return redacted, False
    suffix = "\n... <truncated>"
    return redacted[: max(0, max_length - len(suffix))].rstrip() + suffix, True
