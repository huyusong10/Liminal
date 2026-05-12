from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SAFE_FILENAME_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._- ")
SENSITIVE_REDIRECT_QUERY_KEYS = {"token"}


def safe_local_return_path(value: object) -> str | None:
    target = str(value or "").strip()
    if not target:
        return None
    if "\\" in target or any(ord(char) < 32 or ord(char) == 127 for char in target):
        return None
    parts = urlsplit(target)
    if parts.scheme or parts.netloc:
        return None
    if not parts.path.startswith("/") or parts.path.startswith("//"):
        return None
    return urlunsplit(("", "", parts.path or "/", _safe_redirect_query(parts.query), parts.fragment))


def with_query_params(url: str, **params: object) -> str:
    parts = urlsplit(url)
    query = {
        key: value
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in SENSITIVE_REDIRECT_QUERY_KEYS
    }
    for key, value in params.items():
        if value is None:
            continue
        if key.lower() in SENSITIVE_REDIRECT_QUERY_KEYS:
            continue
        query[key] = str(value)
    return urlunsplit(("", "", parts.path or "/", urlencode(query), parts.fragment))


def _safe_redirect_query(query: str) -> str:
    return urlencode(
        [
            (key, value)
            for key, value in parse_qsl(query, keep_blank_values=True)
            if key.lower() not in SENSITIVE_REDIRECT_QUERY_KEYS
        ]
    )


def safe_attachment_filename(filename: object, *, default: str = "download") -> str:
    raw = str(filename or "").strip() or default
    cleaned = "".join(char if char in SAFE_FILENAME_CHARS else "-" for char in raw)
    cleaned = re.sub(r"\s*-\s*", "-", cleaned)
    cleaned = re.sub(r"-{2,}", "-", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .-_")
    return cleaned or default


def attachment_content_disposition(filename: object, *, default: str = "download") -> str:
    return f'attachment; filename="{safe_attachment_filename(filename, default=default)}"'
