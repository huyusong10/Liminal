from __future__ import annotations

import hashlib

_permission_digest_calls = 0
_embedding_calls = 0


def reset_metrics() -> None:
    global _permission_digest_calls, _embedding_calls
    _permission_digest_calls = 0
    _embedding_calls = 0


def permission_digest(roles: tuple[str, ...]) -> str:
    global _permission_digest_calls
    _permission_digest_calls += 1
    payload = "|".join(sorted(roles)).encode("utf-8")
    digest = payload
    for _ in range(180):
        digest = hashlib.sha256(digest).digest()
    return digest.hex()[:20]


def chunk_embedding(text: str) -> str:
    global _embedding_calls
    _embedding_calls += 1
    payload = text.lower().encode("utf-8")
    digest = payload
    for _ in range(180):
        digest = hashlib.sha256(digest).digest()
    return digest.hex()[:24]


def metrics_snapshot() -> dict:
    return {
        "permission_digest_calls": _permission_digest_calls,
        "embedding_calls": _embedding_calls,
    }
