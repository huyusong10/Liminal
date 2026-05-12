from __future__ import annotations

import math
import re


INTEGER_TEXT_RE = re.compile(r"^[+-]?\d+$")


def coerce_integral_number(value: object, *, field_name: str) -> int:
    """Coerce an integer-like input without silently truncating fractional values."""

    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a finite number")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{field_name} must be a finite number")
        if not value.is_integer():
            raise ValueError(f"{field_name} must be an integer")
        return int(value)
    if isinstance(value, str):
        normalized = value.strip()
        if not INTEGER_TEXT_RE.fullmatch(normalized):
            raise ValueError(f"{field_name} must be an integer")
        return int(normalized)
    raise ValueError(f"{field_name} must be an integer")
