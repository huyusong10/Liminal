from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

NON_SUPPORTING_EVIDENCE_RESULTS = {"blocked", "failed", "fail", "rejected", "error", "errored"}
SUPPORTING_REVIEW_ARCHETYPES = {"inspector", "custom"}


def evidence_item_is_supporting_gatekeeper_ref(item: Mapping[str, Any]) -> bool:
    if not isinstance(item, Mapping):
        return False
    archetype = str(item.get("archetype") or "").strip().lower()
    result = str(item.get("result") or "").strip().lower()
    if archetype == "gatekeeper" or result in NON_SUPPORTING_EVIDENCE_RESULTS:
        return False
    if archetype in SUPPORTING_REVIEW_ARCHETYPES:
        return True
    if str(item.get("evidence_kind") or "").strip().lower() == "control":
        return True
    if bool(item.get("measured_evidence")):
        return True
    return _has_proof_artifact_ref(item.get("artifact_refs"))


def evidence_item_is_non_supporting_gatekeeper_ref(item: Mapping[str, Any]) -> bool:
    return isinstance(item, Mapping) and not evidence_item_is_supporting_gatekeeper_ref(item)


def _has_proof_artifact_ref(value: object) -> bool:
    for ref in list(value or []):
        if not isinstance(ref, Mapping):
            continue
        label = str(ref.get("label") or "").strip().lower()
        if label.startswith(("proof-file:", "proof-artifact:")) and _artifact_ref_currently_exists(ref):
            return True
    return False


def _artifact_ref_currently_exists(ref: Mapping[str, Any]) -> bool:
    absolute_path = str(ref.get("absolute_path") or "").strip()
    if not absolute_path:
        return bool(str(ref.get("workspace_path") or ref.get("relative_path") or "").strip())
    try:
        return Path(absolute_path).exists()
    except OSError:
        return False
