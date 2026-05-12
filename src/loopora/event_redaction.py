from __future__ import annotations

import re
from collections.abc import Mapping

PROMPT_OMITTED = "<prompt omitted>"
JSON_SCHEMA_OMITTED = "<json schema omitted>"
SECRET_OMITTED = "<secret omitted>"
PAYLOAD_OMITTED = "<payload omitted>"
MAX_CODEX_MESSAGE_LENGTH = 4000
MAX_CODEX_ITEM_TEXT_LENGTH = 4000
MAX_ALIGNMENT_EVENT_TEXT_LENGTH = 2000
MAX_ALIGNMENT_COMMAND_MESSAGE_LENGTH = 500
_CODEX_PASSTHROUGH_KEYS = {
    "type",
    "step_id",
    "step_order",
    "role",
    "role_name",
    "archetype",
    "iter",
    "invocation_id",
    "alignment_status",
    "prompt_omitted",
    "json_schema_omitted",
    "token_omitted",
    "command_truncated",
    "message_truncated",
    "summary_truncated",
    "payload_omitted",
    "omitted_keys",
    "arg_count",
}
_CODEX_PREVIEW_KEYS = ("message", "summary")
_CODEX_STRUCTURED_KEYS = {"error", "item"}

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
_ALIGNMENT_OMITTED_KEYS = _PROMPT_KEYS | _JSON_SCHEMA_KEYS | {"bundle_yaml"}
_SECRET_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "auth_token",
    "bearer_token",
    "cookie",
    "password",
    "private_key",
    "privatekey",
    "secret",
    "secret_token",
    "set_cookie",
    "token",
}
_SECRET_KEY_SUFFIXES = ("_api_key", "_authorization", "_cookie", "_password", "_private_key", "_secret", "_token")
_SECRET_COMPACT_KEY_SUFFIXES = (
    "apikey",
    "authorization",
    "authtoken",
    "bearertoken",
    "clientsecret",
    "cookie",
    "password",
    "privatekey",
    "secret",
    "secrettoken",
    "setcookie",
    "token",
)
_SECRET_ARG_PATTERN = re.compile(
    r"(?i)(--(?:access[-_]token|api[-_]key|auth(?:orization|[-_]token)|bearer[-_]token|client[-_]secret|cookie|id[-_]token|password|private[-_]key|proxy[-_]authorization|refresh[-_]token|secret(?:[-_]token)?|session[-_]token|set[-_]cookie|token|x[-_](?:api[-_]key|loopora[-_]token))(?:=|\s+))"
    r"(<secret omitted>|\"[^\"]*\"|'[^']*'|[^\s]+)"
)
_ENV_SECRET_PATTERN = re.compile(
    r"(?i)\b(([A-Z0-9_]*(?:API_KEY|AUTH_TOKEN|BEARER_TOKEN|CLIENT_SECRET|PRIVATE_KEY|TOKEN|SECRET|PASSWORD))=)(<secret omitted>|[^\s]+)"
)
_BEARER_SECRET_PATTERN = re.compile(r"(?i)\b((?:authorization:\s*)?bearer\s+)([A-Za-z0-9._~+/=-]+)")
_HEADER_SECRET_PATTERN = re.compile(
    r"(?i)\b((?:authorization|proxy-authorization|cookie|set-cookie|x-api-key|x-loopora-token):\s*)([^\r\n]+)"
)


def redact_run_event_payload(event_type: str, payload: Mapping[str, object] | None) -> dict:
    if not isinstance(payload, Mapping):
        return {}
    if str(event_type or "").strip() == "codex_event":
        return _redact_codex_event_payload(payload)
    return {
        str(key): _redact_value(str(key), value)
        for key, value in payload.items()
    }


def redact_alignment_event_payload(event_type: str, payload: Mapping[str, object] | None) -> dict:
    if not isinstance(payload, Mapping):
        return {}
    sanitized = (
        _redact_codex_event_payload(payload)
        if str(event_type or "").strip() == "codex_event"
        else _redact_alignment_mapping(payload)
    )
    return _truncate_alignment_event_payload(sanitized)


def redact_sensitive_value(key: str, value: object) -> object:
    return _redact_value(str(key), value)


def redact_sensitive_text(value: object) -> str:
    return _redact_string(str(value or ""))


def _redact_codex_event_payload(payload: Mapping[str, object]) -> dict:
    sanitized: dict[str, object] = {}
    for key in _CODEX_PASSTHROUGH_KEYS:
        if key in payload:
            sanitized[key] = _redact_container(payload[key])

    for key in _CODEX_PREVIEW_KEYS:
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

    omitted_keys = _codex_omitted_payload_keys(payload)
    if omitted_keys:
        sanitized["payload_omitted"] = True
        sanitized["omitted_keys"] = omitted_keys
    return sanitized


def _codex_omitted_payload_keys(payload: Mapping[str, object]) -> list[str]:
    allowed_keys = _CODEX_PASSTHROUGH_KEYS | set(_CODEX_PREVIEW_KEYS) | _CODEX_STRUCTURED_KEYS
    return sorted(str(key) for key in payload if str(key) not in allowed_keys)


def _redact_alignment_mapping(payload: Mapping[str, object]) -> dict:
    sanitized: dict[str, object] = {}
    for key, value in payload.items():
        normalized_key = _normalized_key(str(key))
        if normalized_key in _ALIGNMENT_OMITTED_KEYS:
            sanitized[f"{key}_omitted"] = True
            continue
        sanitized[str(key)] = _redact_value(str(key), value)
    return sanitized


def _truncate_alignment_event_payload(payload: dict) -> dict:
    sanitized = dict(payload)
    if "message" in sanitized:
        message_limit = (
            MAX_ALIGNMENT_COMMAND_MESSAGE_LENGTH
            if sanitized.get("type") == "command"
            else MAX_ALIGNMENT_EVENT_TEXT_LENGTH
        )
        sanitized["message"] = _truncate_alignment_event_text(sanitized["message"], limit=message_limit)
        if sanitized.get("type") == "command":
            sanitized["command_truncated"] = True
    if "error" in sanitized:
        sanitized["error"] = _truncate_alignment_event_text(sanitized["error"], limit=MAX_ALIGNMENT_EVENT_TEXT_LENGTH)
    return sanitized


def _truncate_alignment_event_text(value: object, *, limit: int) -> str:
    text = _redact_string(str(value or ""))
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [truncated {len(text) - limit} chars]"


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
        _redact_command_execution_item(value, sanitized)
    elif item_type == "file_change":
        _redact_file_change_item(value, sanitized)
    elif item_type == "todo_list":
        _redact_todo_list_item(value, sanitized)
    elif item_type == "agent_message":
        _redact_agent_message_item(value, sanitized)
    elif item_type:
        sanitized["payload_omitted"] = True
    return sanitized


def _redact_command_execution_item(value: Mapping[str, object], sanitized: dict[str, object]) -> None:
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


def _redact_file_change_item(value: Mapping[str, object], sanitized: dict[str, object]) -> None:
    changes = value.get("changes")
    if isinstance(changes, list):
        sanitized["changes"] = [_redact_file_change(change) for change in changes if isinstance(change, Mapping)]


def _redact_todo_list_item(value: Mapping[str, object], sanitized: dict[str, object]) -> None:
    items = value.get("items")
    if isinstance(items, list):
        sanitized["items"] = [_redact_todo_item(item) for item in items if isinstance(item, Mapping)]


def _redact_agent_message_item(value: Mapping[str, object], sanitized: dict[str, object]) -> None:
    if "text" not in value:
        return
    sanitized["text"], text_truncated = _redact_preview_string(
        value["text"],
        max_length=MAX_CODEX_ITEM_TEXT_LENGTH,
    )
    if text_truncated:
        sanitized["text_truncated"] = True


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
    if _is_secret_key(normalized_key):
        return SECRET_OMITTED
    return _redact_container(value)


def _is_secret_key(normalized_key: str) -> bool:
    compact_key = re.sub(r"[^a-z0-9]+", "", normalized_key)
    return (
        normalized_key in _SECRET_KEYS
        or normalized_key.endswith(_SECRET_KEY_SUFFIXES)
        or compact_key.endswith(_SECRET_COMPACT_KEY_SUFFIXES)
    )


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
    redacted = _BEARER_SECRET_PATTERN.sub(lambda match: f"{match.group(1)}{SECRET_OMITTED}", redacted)
    return _HEADER_SECRET_PATTERN.sub(lambda match: f"{match.group(1)}{SECRET_OMITTED}", redacted)


def _redact_preview_string(value: object, *, max_length: int) -> tuple[str, bool]:
    redacted = _redact_string(str(value or ""))
    if len(redacted) <= max_length:
        return redacted, False
    suffix = "\n... <truncated>"
    return redacted[: max(0, max_length - len(suffix))].rstrip() + suffix, True
