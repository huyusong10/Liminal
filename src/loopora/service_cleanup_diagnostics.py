from __future__ import annotations

import logging
from contextlib import suppress
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from os import PathLike
from pathlib import Path
import shutil
from typing import Any, TypeVar

from loopora.diagnostics import log_event

DEFAULT_CLEANUP_FAILURE_MESSAGE = "Non-critical cleanup operation failed"
T = TypeVar("T")


@dataclass(frozen=True)
class CleanupFailureRequest:
    operation: str
    resource_type: str
    resource_id: object
    error: BaseException
    owner_id: object = ""
    message: str = DEFAULT_CLEANUP_FAILURE_MESSAGE
    context: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BestEffortRmtreeRequest:
    operation: str
    owner_id: object = ""
    on_failure: Callable[[dict[str, object]], object] | None = None
    missing_ok: bool = True
    context: Mapping[str, Any] = field(default_factory=dict)


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
    except Exception:  # noqa: BLE001 - diagnostic logging must never raise into cleanup paths.
        with suppress(Exception):
            logger.warning("Cleanup diagnostic logging failed")


def record_cleanup_failure(
    logger,
    request: CleanupFailureRequest | None = None,
    **raw_request: Any,
) -> dict[str, object]:
    request = _cleanup_failure_request_from_kwargs(raw_request) if request is None else _validated_request(request, raw_request)
    payload = cleanup_diagnostic_payload(
        operation=request.operation,
        resource_type=request.resource_type,
        resource_id=request.resource_id,
        owner_id=request.owner_id,
        error=request.error,
        **request.context,
    )
    log_cleanup_diagnostic(logger, message=request.message, **payload)
    return payload


def best_effort_rmtree(
    path: Path,
    logger,
    request: BestEffortRmtreeRequest | None = None,
    **raw_request: Any,
) -> bool:
    request = _rmtree_request_from_kwargs(raw_request) if request is None else _validated_request(request, raw_request)
    target = Path(path)
    if request.missing_ok and not target.exists():
        return False
    try:
        shutil.rmtree(target)
        return True
    except Exception as exc:  # noqa: BLE001 - cleanup failures are diagnostic-only at this boundary.
        payload = record_cleanup_failure(
            logger,
            CleanupFailureRequest(
                operation=request.operation,
                resource_type="path",
                resource_id=target,
                owner_id=request.owner_id,
                error=exc,
                context=request.context,
            ),
        )
        if request.on_failure is not None:
            try:
                request.on_failure(payload)
            except Exception as callback_exc:  # noqa: BLE001 - diagnostic callbacks are best-effort.
                record_cleanup_failure(
                    logger,
                    CleanupFailureRequest(
                        operation=f"{request.operation}_diagnostic_callback",
                        resource_type="diagnostic_callback",
                        resource_id=request.operation,
                        owner_id=request.owner_id,
                        error=callback_exc,
                        context={"original_operation": request.operation},
                    ),
                )
        return False


def _pop_required(raw_request: dict[str, Any], field_name: str) -> Any:
    try:
        return raw_request.pop(field_name)
    except KeyError as exc:
        raise TypeError(f"missing required cleanup request field: {field_name}") from exc


def _validated_request(request: T, raw_request: dict[str, Any]) -> T:
    if raw_request:
        raise TypeError("cleanup request object cannot be combined with keyword fields")
    return request


def _cleanup_failure_request_from_kwargs(raw_request: dict[str, Any]) -> CleanupFailureRequest:
    context = dict(raw_request)
    return CleanupFailureRequest(
        operation=_pop_required(context, "operation"),
        resource_type=_pop_required(context, "resource_type"),
        resource_id=_pop_required(context, "resource_id"),
        owner_id=context.pop("owner_id", ""),
        error=_pop_required(context, "error"),
        message=context.pop("message", DEFAULT_CLEANUP_FAILURE_MESSAGE),
        context=context,
    )


def _rmtree_request_from_kwargs(raw_request: dict[str, Any]) -> BestEffortRmtreeRequest:
    context = dict(raw_request)
    return BestEffortRmtreeRequest(
        operation=_pop_required(context, "operation"),
        owner_id=context.pop("owner_id", ""),
        on_failure=context.pop("on_failure", None),
        missing_ok=bool(context.pop("missing_ok", True)),
        context=context,
    )


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
