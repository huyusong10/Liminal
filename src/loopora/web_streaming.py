from __future__ import annotations

import re


STREAM_UNAVAILABLE = "stream_unavailable"
MAX_EVENT_CURSOR_ID = 2**63 - 1
EVENT_CURSOR_TEXT_RE = re.compile(r"^\d+$")


def bounded_event_cursor(value: object, *, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int) and 0 <= value <= MAX_EVENT_CURSOR_ID:
        return value
    return default


def parse_sse_last_event_id(value: object) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    if not EVENT_CURSOR_TEXT_RE.fullmatch(text):
        return None
    cursor = int(text)
    if cursor < 0 or cursor > MAX_EVENT_CURSOR_ID:
        return None
    return cursor


def stream_error_payload(*, owner_key: str, owner_id: object, after_id: object) -> dict[str, object]:
    return {
        owner_key: str(owner_id or ""),
        "after_id": bounded_event_cursor(after_id),
        "error": STREAM_UNAVAILABLE,
        "retryable": True,
    }
