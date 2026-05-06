from __future__ import annotations

import json
from pathlib import Path

from loopora.task_verdicts import build_task_verdict


def _write_coverage(run_dir: Path, payload: dict) -> None:
    coverage_path = run_dir / "evidence" / "coverage.json"
    coverage_path.parent.mkdir(parents=True)
    coverage_payload = {"schema_version": 1, **payload}
    coverage_path.write_text(json.dumps(coverage_payload, ensure_ascii=False), encoding="utf-8")


def test_task_verdict_projects_coverage_targets_into_semantic_buckets(tmp_path: Path) -> None:
    run_dir = tmp_path / "run_coverage"
    _write_coverage(
        run_dir,
        {
            "summary": {"reason": "Required evidence is still incomplete."},
            "targets": [
                {"id": "done_when.check_001", "label": "Required proof", "status": "covered", "required": True},
                {"id": "fake_done.risk_001", "label": "Weak screenshot", "status": "weak"},
                {"id": "evidence.pref_001", "label": "Benchmark output", "status": "missing"},
                {"id": "gatekeeper.required_refs", "label": "Gatekeeper refs", "status": "blocked"},
            ],
            "risk_signals": ["Manual review still recommended."],
        },
    )

    task_verdict = build_task_verdict(
        {
            "status": "failed",
            "last_verdict_json": {
                "passed": False,
                "blocking_issues": ["missing_contract_evidence"],
            },
        },
        run_dir=run_dir,
    )

    assert task_verdict["status"] == "failed"
    assert task_verdict["source"] == "gatekeeper"
    assert task_verdict["summary"] == "Required evidence is still incomplete."
    buckets = task_verdict["buckets"]
    assert {item["label"] for item in buckets["proven"]} == {"Required proof"}
    assert {item["label"] for item in buckets["weak"]} == {"Weak screenshot"}
    assert {item["label"] for item in buckets["unproven"]} == {"Benchmark output"}
    assert {item["label"] for item in buckets["blocking"]} == {"Gatekeeper refs", "missing_contract_evidence"}
    assert {item["label"] for item in buckets["residual_risk"]} == {"Manual review still recommended."}


def test_task_verdict_falls_back_to_raw_evidence_when_no_projection_exists() -> None:
    task_verdict = build_task_verdict(
        {
            "status": "succeeded",
            "last_verdict_json": {
                "passed": True,
                "evidence_claims": ["The benchmark and regression suite both passed."],
                "evidence_refs": ["ev_001", "ev_001"],
            },
        }
    )

    assert task_verdict["status"] == "passed"
    assert task_verdict["source"] == "gatekeeper"
    assert [item["label"] for item in task_verdict["buckets"]["proven"]] == [
        "The benchmark and regression suite both passed.",
        "ev_001",
    ]
