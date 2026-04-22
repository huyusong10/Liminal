from __future__ import annotations

RELEASE_BLOCKER_ORDER = [
    "public_permission_leak",
    "zero_result_regression",
    "stale_results",
    "ranking_drift",
]


def symptom_snapshot() -> list[str]:
    return [
        "stale_results",
        "ranking_drift",
        "filter_mismatch",
        "public_permission_leak",
    ]
