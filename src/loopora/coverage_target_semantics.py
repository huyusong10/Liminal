from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from loopora.structured_booleans import structured_bool_is_true

REQUIRED_TARGET_KINDS = {"done_when", "gatekeeper"}


def coverage_target_is_required(target: Mapping[str, Any], *, target_id: str | None = None) -> bool:
    normalized_id = str(target_id if target_id is not None else target.get("id") or "").strip()
    kind = str(target.get("kind") or "").strip()
    return (
        structured_bool_is_true(target.get("required"))
        or kind in REQUIRED_TARGET_KINDS
        or normalized_id.startswith("done_when.")
        or normalized_id == "gatekeeper.finish"
    )
