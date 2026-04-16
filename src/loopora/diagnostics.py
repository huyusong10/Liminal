from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from os import PathLike
from pathlib import Path
from typing import Any

from loopora.branding import APP_PACKAGE

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
            "message": record.getMessage(),
            "pid": record.process,
            "thread": record.threadName,
        }

        for key in sorted(_TOP_LEVEL_CONTEXT_KEYS):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value

        context = getattr(record, "context", None)
        if isinstance(context, dict) and context:
            payload["context"] = context

        if record.exc_info:
            exc_type, exc_value, _ = record.exc_info
            payload["error"] = {
                "type": exc_type.__name__ if exc_type is not None else type(exc_value).__name__,
                "message": str(exc_value),
                "traceback": self.formatException(record.exc_info),
            }

        return json.dumps(payload, ensure_ascii=False)


def _build_log_extra(*, event: str, context: dict[str, Any]) -> dict[str, Any]:
    extra: dict[str, Any] = {"event": event}
    normalized_context: dict[str, Any] = {}

    for key, value in context.items():
        if value is None:
            continue
        normalized = _normalize_value(value)
        if key in _TOP_LEVEL_CONTEXT_KEYS:
            extra[key] = normalized
        else:
            normalized_context[key] = normalized

    if normalized_context:
        extra["context"] = normalized_context
    return extra


def _normalize_value(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, PathLike):
        return str(Path(value))
    if isinstance(value, dict):
        return {str(key): _normalize_value(item) for key, item in value.items() if item is not None}
    if isinstance(value, (list, tuple, set)):
        return [_normalize_value(item) for item in value]
    if isinstance(value, str):
        return value if len(value) <= _MAX_STRING_LENGTH else value[: _MAX_STRING_LENGTH - 1] + "…"
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)


def _component_name(logger_name: str) -> str:
    prefix = f"{APP_PACKAGE}."
    if logger_name.startswith(prefix):
        return logger_name[len(prefix) :]
    return logger_name


def _iso_timestamp(timestamp: float) -> str:
    return (
        datetime.fromtimestamp(timestamp, tz=timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )
