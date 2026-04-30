from __future__ import annotations


STREAM_UNAVAILABLE = "stream_unavailable"


def stream_error_payload(*, owner_key: str, owner_id: object, after_id: object) -> dict[str, object]:
    try:
        normalized_after_id = max(0, int(after_id or 0))
    except (TypeError, ValueError):
        normalized_after_id = 0
    return {
        owner_key: str(owner_id or ""),
        "after_id": normalized_after_id,
        "error": STREAM_UNAVAILABLE,
        "retryable": True,
    }
