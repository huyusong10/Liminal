from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass
class _CostMetrics:
    permission_digest_calls: int = 0
    embedding_calls: int = 0

    def reset(self) -> None:
        self.permission_digest_calls = 0
        self.embedding_calls = 0

    def snapshot(self) -> dict:
        return {
            "permission_digest_calls": self.permission_digest_calls,
            "embedding_calls": self.embedding_calls,
        }


_METRICS = _CostMetrics()


def reset_metrics() -> None:
    _METRICS.reset()


def permission_digest(roles: tuple[str, ...]) -> str:
    _METRICS.permission_digest_calls += 1
    payload = "|".join(sorted(roles)).encode("utf-8")
    digest = payload
    for _ in range(180):
        digest = hashlib.sha256(digest).digest()
    return digest.hex()[:20]


def chunk_embedding(text: str) -> str:
    _METRICS.embedding_calls += 1
    payload = text.lower().encode("utf-8")
    digest = payload
    for _ in range(180):
        digest = hashlib.sha256(digest).digest()
    return digest.hex()[:24]


def metrics_snapshot() -> dict:
    return _METRICS.snapshot()
