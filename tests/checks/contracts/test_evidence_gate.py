from __future__ import annotations

import math

from loopora.evidence_gate import concrete_evidence_claim_count, has_measured_gate_evidence


def test_measured_gate_evidence_requires_real_numeric_value_and_threshold() -> None:
    assert has_measured_gate_evidence(
        {
            "quality_score": {
                "value": 1.0,
                "threshold": 0.9,
                "passed": True,
            }
        },
        [],
    )
    assert not has_measured_gate_evidence(
        {
            "quality_score": {
                "value": True,
                "threshold": False,
                "passed": True,
            }
        },
        [],
    )
    assert not has_measured_gate_evidence(
        {
            "quality_score": {
                "value": math.nan,
                "threshold": 0.9,
                "passed": False,
            }
        },
        [],
    )


def test_concrete_evidence_claim_count_ignores_short_or_empty_claims() -> None:
    assert concrete_evidence_claim_count(["short", "", "The benchmark fixture produced a durable proof artifact."]) == 1
