from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, TypeVar

T = TypeVar("T")


@dataclass
class RetryConfig:
    max_retries: int = 2


def execute_with_retry(fn: Callable[[], T], config: RetryConfig) -> T:
    last_exc: Exception | None = None
    for _ in range(config.max_retries + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: PERF203
            last_exc = exc
    assert last_exc is not None
    raise last_exc
