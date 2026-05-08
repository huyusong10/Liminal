from __future__ import annotations

import math


def _is_real_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _string_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def has_measured_gate_evidence(metric_scores: object, metrics: object) -> bool:
    if isinstance(metric_scores, dict):
        for value in metric_scores.values():
            if not isinstance(value, dict):
                continue
            if _is_real_number(value.get("value")) and _is_real_number(value.get("threshold")):
                return True
    if isinstance(metrics, list):
        for value in metrics:
            if not isinstance(value, dict):
                continue
            if _is_real_number(value.get("value")) and _is_real_number(value.get("threshold")):
                return True
    return False


def concrete_evidence_claim_count(evidence_claims: object, *, min_length: int = 24) -> int:
    return sum(1 for item in _string_list(evidence_claims) if len(item) >= min_length)
