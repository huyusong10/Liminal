from __future__ import annotations

import json
from pathlib import Path

from loopora.task_verdicts import build_task_verdict, normalize_task_verdict


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
                {
                    "id": "done_when.check_001",
                    "label": "Required proof",
                    "status": "covered",
                    "required": True,
                    "artifact_refs": [{"kind": "workspace", "workspace_path": "proof.md"}],
                },
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
    assert buckets["proven"][0]["artifact_refs"] == [{"kind": "workspace", "workspace_path": "proof.md"}]
    assert {item["label"] for item in buckets["weak"]} == {"Weak screenshot"}
    assert {item["label"] for item in buckets["unproven"]} == {"Benchmark output"}
    assert {item["label"] for item in buckets["blocking"]} == {"Gatekeeper refs", "missing_contract_evidence"}
    assert {item["label"] for item in buckets["residual_risk"]} == {"Manual review still recommended."}


def test_task_verdict_drops_malformed_coverage_trace_shapes(tmp_path: Path) -> None:
    run_dir = tmp_path / "run_malformed_coverage_trace"
    _write_coverage(
        run_dir,
        {
            "summary": {"reason": "Required target is covered."},
            "targets": [
                {
                    "id": "done_when.check_001",
                    "label": "Required proof",
                    "status": "covered",
                    "required": True,
                    "evidence_refs": "ev_001",
                    "artifact_refs": {"kind": "workspace", "workspace_path": "proof.md"},
                }
            ],
            "risk_signals": "Manual review still recommended.",
        },
    )

    task_verdict = build_task_verdict(
        {
            "status": "succeeded",
            "last_verdict_json": {"passed": True},
        },
        run_dir=run_dir,
    )

    buckets = task_verdict["buckets"]
    assert task_verdict["status"] == "passed"
    assert buckets["proven"][0]["evidence_refs"] == []
    assert buckets["proven"][0]["artifact_refs"] == []
    assert buckets["residual_risk"] == []


def test_normalize_task_verdict_drops_non_string_bucket_items() -> None:
    task_verdict = normalize_task_verdict(
        {
            "status": "failed",
            "source": "gatekeeper",
            "summary": "Stored verdict should keep only stable bucket entries.",
            "buckets": {
                "blocking": [True, 7, "real blocker", {"label": "structured blocker"}],
                "residual_risk": [False],
            },
        }
    )

    assert task_verdict["buckets"]["blocking"] == [
        {"label": "real blocker"},
        {"label": "structured blocker"},
    ]
    assert task_verdict["buckets"]["residual_risk"] == []


def test_task_verdict_falls_back_to_raw_evidence_when_no_projection_exists() -> None:
    task_verdict = build_task_verdict(
        {
            "status": "succeeded",
            "last_verdict_json": {
                "passed": True,
                "evidence_claims": ["The benchmark and regression suite both passed."],
                "evidence_refs": ["ev_001", "ev_001"],
            },
        },
        legacy=True,
    )

    assert task_verdict["status"] == "passed"
    assert task_verdict["source"] == "legacy"
    assert [item["label"] for item in task_verdict["buckets"]["proven"]] == [
        "The benchmark and regression suite both passed.",
        "ev_001",
    ]


def test_task_verdict_does_not_pass_nonlegacy_gatekeeper_without_coverage_projection() -> None:
    task_verdict = build_task_verdict(
        {
            "status": "succeeded",
            "last_verdict_json": {
                "passed": True,
                "decision_summary": "Raw GateKeeper passed, but coverage projection is unavailable.",
                "evidence_refs": ["ev_001"],
            },
        }
    )

    assert task_verdict["status"] == "insufficient_evidence"
    assert task_verdict["source"] == "gatekeeper"


def test_task_verdict_does_not_reuse_summary_from_malformed_gatekeeper_pass() -> None:
    task_verdict = build_task_verdict(
        {
            "status": "succeeded",
            "last_verdict_json": {
                "passed": "true",
                "decision_summary": "GateKeeper says this passed from a string-shaped verdict.",
            },
        }
    )

    assert task_verdict["status"] == "not_evaluated"
    assert task_verdict["source"] == "run_status"
    assert task_verdict["summary"] == "The run is succeeded, and no evidence-based task verdict is available."


def test_task_verdict_distinguishes_gatekeeper_pass_with_residual_risk(tmp_path: Path) -> None:
    run_dir = tmp_path / "run_residual_risk"
    _write_coverage(
        run_dir,
        {
            "summary": {"reason": "GateKeeper accepted the named residual risk."},
            "targets": [
                {"id": "done_when.check_001", "label": "Required proof", "status": "covered", "required": True},
                {"id": "gatekeeper.finish", "label": "GateKeeper finish", "status": "covered", "required": True},
            ],
            "risk_signals": ["Manual billing export remains a visible follow-up."],
            "latest_gatekeeper": {
                "id": "ev_gatekeeper",
                "result": "passed",
                "residual_risk": "Manual billing export remains a visible follow-up.",
            },
        },
    )

    task_verdict = build_task_verdict(
        {
            "status": "succeeded",
            "last_verdict_json": {
                "passed": True,
                "decision_summary": "GateKeeper passed with a named follow-up risk.",
            },
        },
        run_dir=run_dir,
    )

    assert task_verdict["status"] == "passed_with_residual_risk"
    assert task_verdict["source"] == "gatekeeper"
    assert task_verdict["summary"] == "GateKeeper passed with a named follow-up risk."
    assert [item["label"] for item in task_verdict["buckets"]["residual_risk"]] == ["Manual billing export remains a visible follow-up."]


def test_task_verdict_projects_raw_gatekeeper_residual_risks_into_bucket(tmp_path: Path) -> None:
    run_dir = tmp_path / "run_raw_residual_risk"
    _write_coverage(
        run_dir,
        {
            "summary": {"reason": "Required evidence is covered."},
            "targets": [
                {"id": "done_when.check_001", "label": "Required proof", "status": "covered", "required": True},
                {"id": "gatekeeper.finish", "label": "GateKeeper finish", "status": "covered", "required": True},
            ],
            "risk_signals": [],
        },
    )

    task_verdict = build_task_verdict(
        {
            "status": "succeeded",
            "last_verdict_json": {
                "passed": True,
                "decision_summary": "GateKeeper accepted a visible follow-up risk.",
                "residual_risks": ["Manual copy polish remains visible."],
            },
        },
        run_dir=run_dir,
    )

    assert task_verdict["status"] == "passed_with_residual_risk"
    assert [item["label"] for item in task_verdict["buckets"]["residual_risk"]] == ["Manual copy polish remains visible."]


def test_task_verdict_drops_non_string_raw_verdict_list_items(tmp_path: Path) -> None:
    run_dir = tmp_path / "run_non_string_raw_verdict_items"
    _write_coverage(
        run_dir,
        {
            "summary": {"reason": "Required evidence is covered."},
            "targets": [
                {"id": "done_when.check_001", "label": "Required proof", "status": "covered", "required": True},
                {"id": "gatekeeper.finish", "label": "GateKeeper finish", "status": "covered", "required": True},
            ],
            "risk_signals": [],
        },
    )

    passed_verdict = build_task_verdict(
        {
            "status": "succeeded",
            "last_verdict_json": {
                "passed": True,
                "residual_risks": [True, 7],
            },
        },
        run_dir=run_dir,
    )
    failed_verdict = build_task_verdict(
        {
            "status": "failed",
            "last_verdict_json": {
                "passed": False,
                "blocking_issues": [True, "real_blocker"],
                "hard_constraint_violations": [7],
                "failed_check_ids": [False],
            },
        },
        run_dir=run_dir,
    )

    assert passed_verdict["status"] == "passed"
    assert passed_verdict["buckets"]["residual_risk"] == []
    assert [item["label"] for item in failed_verdict["buckets"]["blocking"]] == ["real_blocker"]


def test_task_verdict_keeps_pass_when_only_historical_residual_risk_exists(tmp_path: Path) -> None:
    run_dir = tmp_path / "run_historical_residual_risk"
    _write_coverage(
        run_dir,
        {
            "summary": {"reason": "GateKeeper passed after earlier risk was resolved."},
            "targets": [
                {"id": "done_when.check_001", "label": "Required proof", "status": "covered", "required": True},
                {"id": "gatekeeper.finish", "label": "GateKeeper finish", "status": "covered", "required": True},
            ],
            "risk_signals": ["Earlier blocked iteration named a risk that is no longer part of the final pass."],
            "latest_gatekeeper": {
                "id": "ev_gatekeeper",
                "result": "passed",
                "residual_risk": "No blocking residual risk was reported by GateKeeper.",
            },
        },
    )

    task_verdict = build_task_verdict(
        {
            "status": "succeeded",
            "last_verdict_json": {
                "passed": True,
                "decision_summary": "GateKeeper passed without accepted residual risk.",
            },
        },
        run_dir=run_dir,
    )

    assert task_verdict["status"] == "passed"
    assert task_verdict["source"] == "gatekeeper"
    assert [item["label"] for item in task_verdict["buckets"]["residual_risk"]] == [
        "Earlier blocked iteration named a risk that is no longer part of the final pass."
    ]


def test_task_verdict_keeps_pass_when_gatekeeper_reports_no_residual_risk_marker(tmp_path: Path) -> None:
    run_dir = tmp_path / "run_no_residual_risk_marker"
    _write_coverage(
        run_dir,
        {
            "summary": {"reason": "GateKeeper passed with no accepted residual risk."},
            "targets": [
                {"id": "done_when.check_001", "label": "Required proof", "status": "covered", "required": True},
                {"id": "gatekeeper.finish", "label": "GateKeeper finish", "status": "covered", "required": True},
            ],
            "risk_signals": [],
            "latest_gatekeeper": {
                "id": "ev_gatekeeper",
                "result": "passed",
                "residual_risk": "无残余风险",
            },
        },
    )

    task_verdict = build_task_verdict(
        {
            "status": "succeeded",
            "last_verdict_json": {
                "passed": True,
                "decision_summary": "GateKeeper passed without accepted residual risk.",
            },
        },
        run_dir=run_dir,
    )

    assert task_verdict["status"] == "passed"
    assert task_verdict["buckets"]["residual_risk"] == []


def test_task_verdict_does_not_pass_when_required_coverage_is_missing(tmp_path: Path) -> None:
    run_dir = tmp_path / "run_missing_required_coverage"
    _write_coverage(
        run_dir,
        {
            "summary": {"reason": "Required coverage targets still lack direct evidence."},
            "targets": [
                {"id": "done_when.check_001", "label": "Required proof", "status": "missing", "required": True},
                {"id": "gatekeeper.finish", "label": "GateKeeper finish", "status": "covered", "required": True},
            ],
            "risk_signals": [],
            "latest_gatekeeper": {
                "id": "ev_gatekeeper",
                "result": "passed",
                "evidence_refs": ["ev_inspector"],
                "residual_risk": "",
            },
        },
    )

    task_verdict = build_task_verdict(
        {
            "status": "succeeded",
            "last_verdict_json": {
                "passed": True,
                "decision_summary": "GateKeeper passed from an upstream evidence ref.",
                "evidence_refs": ["ev_inspector"],
            },
        },
        run_dir=run_dir,
    )

    assert task_verdict["status"] == "insufficient_evidence"
    assert task_verdict["source"] == "gatekeeper"
    assert task_verdict["summary"] == "Required coverage targets still lack direct evidence."
    assert [item["label"] for item in task_verdict["buckets"]["unproven"]] == ["Required proof"]


def test_task_verdict_treats_intrinsic_required_targets_as_required_when_marker_is_malformed(tmp_path: Path) -> None:
    run_dir = tmp_path / "run_malformed_required_marker"
    _write_coverage(
        run_dir,
        {
            "summary": {"reason": "A Done When target is still missing."},
            "targets": [
                {
                    "id": "done_when.check_001",
                    "kind": "done_when",
                    "label": "Required proof",
                    "status": "missing",
                    "required": "true",
                },
                {
                    "id": "gatekeeper.finish",
                    "kind": "gatekeeper",
                    "label": "GateKeeper finish",
                    "status": "covered",
                    "required": False,
                },
            ],
            "risk_signals": [],
        },
    )

    task_verdict = build_task_verdict(
        {
            "status": "succeeded",
            "last_verdict_json": {
                "passed": True,
                "decision_summary": "GateKeeper passed, but a required target marker was malformed.",
                "evidence_refs": ["ev_inspector"],
            },
        },
        run_dir=run_dir,
    )

    assert task_verdict["status"] == "insufficient_evidence"
    assert [item["label"] for item in task_verdict["buckets"]["unproven"]] == ["Required proof"]
    assert task_verdict["buckets"]["unproven"][0]["required"] is True


def test_task_verdict_fails_when_required_coverage_is_blocked_after_gatekeeper_pass(tmp_path: Path) -> None:
    run_dir = tmp_path / "run_blocked_required_coverage"
    _write_coverage(
        run_dir,
        {
            "summary": {"reason": "GateKeeper or target evidence reported a blocker."},
            "targets": [
                {"id": "done_when.check_001", "label": "Required proof", "status": "blocked", "required": True},
                {"id": "gatekeeper.finish", "label": "GateKeeper finish", "status": "covered", "required": True},
            ],
            "risk_signals": [],
            "latest_gatekeeper": {
                "id": "ev_gatekeeper",
                "result": "passed",
                "evidence_refs": ["ev_inspector"],
                "residual_risk": "",
            },
        },
    )

    task_verdict = build_task_verdict(
        {
            "status": "succeeded",
            "last_verdict_json": {
                "passed": True,
                "decision_summary": "GateKeeper passed from an upstream evidence ref.",
                "evidence_refs": ["ev_inspector"],
            },
        },
        run_dir=run_dir,
    )

    assert task_verdict["status"] == "failed"
    assert task_verdict["source"] == "gatekeeper"
    assert [item["label"] for item in task_verdict["buckets"]["blocking"]] == ["Required proof"]


def test_task_verdict_fails_when_gatekeeper_finish_coverage_is_blocked_after_gatekeeper_pass(tmp_path: Path) -> None:
    run_dir = tmp_path / "run_blocked_gatekeeper_finish"
    _write_coverage(
        run_dir,
        {
            "summary": {"reason": "GateKeeper pass cited only non-supporting upstream evidence refs."},
            "targets": [
                {"id": "done_when.check_001", "label": "Required proof", "status": "covered", "required": True},
                {"id": "gatekeeper.finish", "label": "GateKeeper finish", "status": "blocked", "required": True},
            ],
            "risk_signals": [],
            "latest_gatekeeper": {
                "id": "ev_gatekeeper",
                "result": "passed",
                "evidence_refs": ["ev_blocked"],
                "supporting_evidence_refs": [],
                "non_supporting_evidence_refs": ["ev_blocked"],
                "residual_risk": "",
            },
        },
    )

    task_verdict = build_task_verdict(
        {
            "status": "succeeded",
            "last_verdict_json": {
                "passed": True,
                "decision_summary": "GateKeeper tried to pass from a blocked inspection.",
                "evidence_refs": ["ev_blocked"],
            },
        },
        run_dir=run_dir,
    )

    assert task_verdict["status"] == "failed"
    assert task_verdict["source"] == "gatekeeper"
    assert [item["label"] for item in task_verdict["buckets"]["blocking"]] == ["GateKeeper finish"]
