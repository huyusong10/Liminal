from __future__ import annotations

import math


def structured_non_negative_int(value: object, *, default: int = 0) -> int:
    """Return a non-negative JSON integer, rejecting bools and coerced strings."""
    if isinstance(value, bool):
        return default
    if isinstance(value, int) and value >= 0:
        return value
    return default


def structured_finite_number(value: object, *, default: float = 0.0) -> float:
    """Return a finite JSON number, rejecting bools and coerced strings."""
    normalized = structured_optional_finite_number(value)
    return default if normalized is None else normalized


def structured_optional_finite_number(value: object) -> float | None:
    """Return a finite JSON number or None when the value must fail closed."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    return None
