from __future__ import annotations


def structured_bool_is_true(value: object) -> bool:
    """Return true only for literal booleans from structured JSON contracts."""
    return value is True
