from __future__ import annotations

import pytest

from loopora.executor import ExecutionStopped
from loopora.recovery import RetryConfig, execute_with_recovery


def test_zero_max_retries_retries_until_success() -> None:
    attempts = 0

    def flaky() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 4:
            raise ValueError("not yet")
        return "ok"

    value, result = execute_with_recovery(flaky, RetryConfig(max_retries=0))

    assert value == "ok"
    assert result.ok is True
    assert result.attempts == 4


def test_before_attempt_can_abort_unbounded_retries() -> None:
    attempts = 0

    def always_fails() -> None:
        nonlocal attempts
        attempts += 1
        raise RuntimeError("still failing")

    def stop_after_three_attempts() -> None:
        if attempts >= 3:
            raise ExecutionStopped("stop requested")

    with pytest.raises(ExecutionStopped):
        execute_with_recovery(
            always_fails,
            RetryConfig(max_retries=0),
            before_attempt=stop_after_three_attempts,
        )
