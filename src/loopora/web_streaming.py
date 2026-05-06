from __future__ import annotations


STREAM_UNAVAILABLE = "stream_unavailable"
MAX_EVENT_CURSOR_ID = 2**63 - 1


def parse_sse_last_event_id(value: object) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        cursor = int(text)
    except ValueError:
        return None
    if cursor < 0 or cursor > MAX_EVENT_CURSOR_ID:
        return None
    return cursor


def stream_error_payload(*, owner_key: str, owner_id: object, after_id: object) -> dict[str, object]:
    try:
        normalized_after_id = max(0, min(int(after_id or 0), MAX_EVENT_CURSOR_ID))
    except (TypeError, ValueError):
        normalized_after_id = 0
    return {
        owner_key: str(owner_id or ""),
        "after_id": normalized_after_id,
        "error": STREAM_UNAVAILABLE,
        "retryable": True,
    }
