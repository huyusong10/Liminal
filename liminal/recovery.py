from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, TypeVar

T = TypeVar("T")
_SENTINEL = object()


@dataclass(slots=True)
class RetryConfig:
    max_retries: int = 2


@dataclass(slots=True)
class RecoveryResult:
    ok: bool
    attempts: int
    degraded: bool
    error: Exception | None = None


def execute_with_recovery(
    fn: Callable[[], T],
    config: RetryConfig,
    degrade_once: Callable[[], None] | None = None,
) -> tuple[T | None, RecoveryResult]:
    attempts = 0
    degraded = False
    last_exc: Exception | None = None

    def attempt_cycle() -> T | object:
        nonlocal attempts, last_exc
        for _ in range(config.max_retries + 1):
            attempts += 1
            try:
                return fn()
            except Exception as exc:  # noqa: PERF203
                last_exc = exc
        return _SENTINEL

    value = attempt_cycle()
    if value is not _SENTINEL:
        return value, RecoveryResult(ok=True, attempts=attempts, degraded=degraded)

    if degrade_once is not None:
        degrade_once()
        degraded = True
        value = attempt_cycle()
        if value is not _SENTINEL:
            return value, RecoveryResult(ok=True, attempts=attempts, degraded=degraded)

    return None, RecoveryResult(ok=False, attempts=attempts, degraded=degraded, error=last_exc)
