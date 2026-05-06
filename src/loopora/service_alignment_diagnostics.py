from __future__ import annotations

import json

from loopora.service_cleanup_diagnostics import cleanup_diagnostic_payload, log_cleanup_diagnostic
from loopora.utils import utc_now


def append_alignment_diagnostic_event(service, logger, session_id: str, event_type: str, payload: dict) -> dict:
    try:
        return service.repository.append_alignment_event(session_id, event_type, payload)
    except Exception as exc:
        log_alignment_diagnostic_event_failure(
            logger,
            session_id=session_id,
            event_type=event_type,
            payload=payload,
            error=exc,
        )
        return {}


def append_alignment_local_diagnostic_event(service, logger, session: dict, event_type: str, payload: dict) -> None:
    try:
        paths = service._alignment_artifact_paths(session)
        service._ensure_alignment_artifact_dirs(paths["root"])
        event = {
            "id": None,
            "session_id": session["id"],
            "created_at": utc_now(),
            "event_type": event_type,
            "payload": payload,
        }
        with paths["events"].open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception as exc:
        log_alignment_diagnostic_event_failure(
            logger,
            session_id=session.get("id", ""),
            event_type=event_type,
            payload=payload,
            error=exc,
        )


def log_alignment_diagnostic_event_failure(
    logger,
    *,
    session_id: str,
    event_type: str,
    payload: dict,
    error: BaseException,
) -> None:
    original_operation = str(payload.get("operation") or "alignment_diagnostic")
    diagnostic = cleanup_diagnostic_payload(
        operation=f"{original_operation}_event_write",
        resource_type="alignment_event",
        resource_id=event_type,
        owner_id=session_id,
        error=error,
        original_operation=original_operation,
    )
    log_cleanup_diagnostic(logger, **diagnostic)
