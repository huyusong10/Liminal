from __future__ import annotations

import logging
from os import PathLike
from pathlib import Path
import shutil
from typing import Any

from loopora.diagnostics import log_event


def cleanup_diagnostic_payload(
    *,
    operation: str,
    resource_type: str,
    resource_id: object,
    owner_id: object = "",
    error: BaseException,
    **context: Any,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "operation": str(operation or "").strip(),
        "resource_type": str(resource_type or "").strip(),
        "resource_id": str(resource_id or "").strip(),
        "owner_id": str(owner_id or "").strip(),
        "error_type": type(error).__name__,
        "error_message": str(error),
    }
    for key, value in context.items():
        if value is not None:
            payload[key] = _json_safe_value(value)
    return payload


def log_cleanup_diagnostic(logger, *, message: str = "Non-critical cleanup operation failed", **payload: object) -> None:
    try:
        log_event(
            logger,
            logging.WARNING,
            "service.cleanup.failed",
            message,
            **payload,
        )
    except Exception:
        try:
            logger.warning("Cleanup diagnostic logging failed")
        except Exception:
            pass


def record_cleanup_failure(
    logger,
    *,
    operation: str,
    resource_type: str,
    resource_id: object,
    owner_id: object = "",
    error: BaseException,
    message: str = "Non-critical cleanup operation failed",
    **context: Any,
) -> dict[str, object]:
    payload = cleanup_diagnostic_payload(
        operation=operation,
        resource_type=resource_type,
        resource_id=resource_id,
        owner_id=owner_id,
        error=error,
        **context,
    )
    log_cleanup_diagnostic(logger, message=message, **payload)
    return payload


def best_effort_rmtree(
    path: Path,
    logger,
    *,
    operation: str,
    owner_id: object = "",
    on_failure=None,
    missing_ok: bool = True,
    **context: Any,
) -> bool:
    target = Path(path)
    if missing_ok and not target.exists():
        return False
    try:
        shutil.rmtree(target)
        return True
    except OSError as exc:
        payload = record_cleanup_failure(
            logger,
            operation=operation,
            resource_type="path",
            resource_id=target,
            owner_id=owner_id,
            error=exc,
            **context,
        )
        if on_failure is not None:
            try:
                on_failure(payload)
            except Exception as callback_exc:
                record_cleanup_failure(
                    logger,
                    operation=f"{operation}_diagnostic_callback",
                    resource_type="diagnostic_callback",
                    resource_id=operation,
                    owner_id=owner_id,
                    error=callback_exc,
                    original_operation=operation,
                )
        return False


def _json_safe_value(value: object) -> object:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, PathLike):
        return str(Path(value))
    if isinstance(value, dict):
        return {str(key): _json_safe_value(item) for key, item in value.items() if item is not None}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
