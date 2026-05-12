from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from os import PathLike
from pathlib import Path
from typing import Any

from loopora.branding import APP_PACKAGE
from loopora.event_redaction import redact_sensitive_text, redact_sensitive_value

LOG_SCHEMA_VERSION = 1

_TOP_LEVEL_CONTEXT_KEYS = {
    "loop_id",
    "run_id",
    "step_id",
    "role",
    "archetype",
    "orchestration_id",
    "role_definition_id",
    "workdir",
}
_MAX_STRING_LENGTH = 800
_COMPONENT_BOUNDARIES = ("settings", "db", "service", "web", "cli")


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log_event(
    logger: logging.Logger,
    level: int,
    event: str,
    message: str,
    **context: Any,
) -> None:
    logger.log(level, message, extra=_build_log_extra(event=event, context=context))


def log_exception(
    logger: logging.Logger,
    event: str,
    message: str,
    *,
    error: BaseException | None = None,
    level: int = logging.ERROR,
    **context: Any,
) -> None:
    exc_info = (type(error), error, error.__traceback__) if error is not None else True
    logger.log(
        level,
        message,
        exc_info=exc_info,
        extra=_build_log_extra(event=event, context=context),
    )


class LooporaJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "schema_version": LOG_SCHEMA_VERSION,
            "ts": _iso_timestamp(record.created),
            "level": record.levelname,
            "logger": record.name,
            "component": _component_name(record.name),
            "event": getattr(record, "event", "log.unclassified"),
            "message": redact_sensitive_text(record.getMessage()),
            "pid": record.process,
            "thread": record.threadName,
        }

        for key in sorted(_TOP_LEVEL_CONTEXT_KEYS):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = _normalize_value(value, key=key)

        context = getattr(record, "context", None)
        if isinstance(context, dict) and context:
            normalized_context = _normalize_value(context, key="context")
            if isinstance(normalized_context, dict) and normalized_context:
                payload["context"] = normalized_context

        if record.exc_info:
            exc_type, exc_value, _ = record.exc_info
            payload["error"] = {
                "type": exc_type.__name__ if exc_type is not None else type(exc_value).__name__,
                "message": redact_sensitive_text(exc_value),
                "traceback": redact_sensitive_text(self.formatException(record.exc_info)),
            }

        return json.dumps(payload, ensure_ascii=False)


def _build_log_extra(*, event: str, context: dict[str, Any]) -> dict[str, Any]:
    extra: dict[str, Any] = {"event": event}
    normalized_context: dict[str, Any] = {}

    for key, value in context.items():
        if value is None:
            continue
        normalized = _normalize_value(value, key=key)
        if key in _TOP_LEVEL_CONTEXT_KEYS:
            extra[key] = normalized
        else:
            normalized_context[key] = normalized

    if normalized_context:
        extra["context"] = normalized_context
    return extra


def _normalize_value(value: Any, *, key: str = "") -> Any:
    value = redact_sensitive_value(key, value)
    if isinstance(value, Path):
        normalized = str(value)
    elif isinstance(value, PathLike):
        normalized = str(Path(value))
    elif isinstance(value, dict):
        normalized = {str(child_key): _normalize_value(item, key=str(child_key)) for child_key, item in value.items() if item is not None}
    elif isinstance(value, (list, tuple, set)):
        normalized = [_normalize_value(item) for item in value]
    elif isinstance(value, str):
        normalized = value if len(value) <= _MAX_STRING_LENGTH else value[: _MAX_STRING_LENGTH - 1] + "…"
    elif isinstance(value, (int, float, bool)) or value is None:
        normalized = value
    else:
        normalized = str(value)
    return normalized


def _component_name(logger_name: str) -> str:
    prefix = f"{APP_PACKAGE}."
    name = logger_name[len(prefix) :] if logger_name.startswith(prefix) else logger_name
    root = name.split(".", 1)[0]
    for boundary in _COMPONENT_BOUNDARIES:
        if root == boundary or root.startswith(f"{boundary}_"):
            return boundary
    return root


def _iso_timestamp(timestamp: float) -> str:
    return (
        datetime.fromtimestamp(timestamp, tz=UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )
