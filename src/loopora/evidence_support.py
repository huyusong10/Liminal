from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from loopora.structured_booleans import structured_bool_is_true

NON_SUPPORTING_EVIDENCE_RESULTS = {"blocked", "failed", "fail", "rejected", "error", "errored"}
SUPPORTING_EVIDENCE_RESULTS = {"passed", "pass", "ok", "success", "succeeded", "completed", "covered", "satisfied", "guarded", "verified", "proven"}
SUPPORTING_REVIEW_ARCHETYPES = {"inspector", "custom"}


def evidence_item_is_supporting_gatekeeper_ref(item: Mapping[str, Any]) -> bool:
    if not isinstance(item, Mapping):
        return False
    archetype = str(item.get("archetype") or "").strip().lower()
    result = str(item.get("result") or "").strip().lower()
    if archetype == "gatekeeper" or result in NON_SUPPORTING_EVIDENCE_RESULTS:
        return False
    if archetype in SUPPORTING_REVIEW_ARCHETYPES and _has_supporting_review_verify_ref(item.get("verifies")):
        return True
    if str(item.get("evidence_kind") or "").strip().lower() == "control":
        return True
    if structured_bool_is_true(item.get("measured_evidence")):
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


def _has_supporting_review_verify_ref(value: object) -> bool:
    return any(_verify_ref_has_supporting_status(ref) for ref in list(value or []))


def _verify_ref_has_supporting_status(value: object) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if text.startswith("target:"):
        parts = text.split(":", 2)
        return len(parts) == 3 and parts[2].strip().lower() in SUPPORTING_EVIDENCE_RESULTS
    if text.startswith(("check_results:", "dynamic_checks:")):
        parts = text.split(":", 2)
        return len(parts) == 3 and parts[2].strip().lower() in SUPPORTING_EVIDENCE_RESULTS
    return False


def _artifact_ref_currently_exists(ref: Mapping[str, Any]) -> bool:
    absolute_path = str(ref.get("absolute_path") or "").strip()
    if not absolute_path:
        return False
    try:
        return Path(absolute_path).exists()
    except OSError:
        return False
