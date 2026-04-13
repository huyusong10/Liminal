from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8").strip()
    return json.loads(text) if text else {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def require_keys(payload: dict[str, Any], keys: list[str], name: str) -> None:
    missing = [k for k in keys if k not in payload]
    if missing:
        raise ValueError(f"{name} missing keys: {missing}")


def validate_acceptance_criteria(payload: dict[str, Any]) -> None:
    require_keys(payload, ["metrics", "composite_score", "hard_constraints"], "acceptance_criteria")
    metrics = payload["metrics"]
    for metric in ["f1_score", "latency_p99_ms", "edge_case_coverage"]:
        if metric not in metrics:
            raise ValueError(f"acceptance_criteria missing metric: {metric}")
        require_keys(metrics[metric], ["weight", "pass_threshold"], f"metric:{metric}")
    require_keys(payload["composite_score"], ["formula", "pass_threshold"], "composite_score")


def validate_tester_output(payload: dict[str, Any]) -> None:
    require_keys(payload, ["iter", "timestamp", "execution_summary", "case_results", "dynamic_cases"], "tester_output")
    require_keys(
        payload["execution_summary"],
        ["total_cases", "passed", "failed", "errored", "total_duration_ms"],
        "tester_output.execution_summary",
    )
    for case in payload.get("case_results", []):
        require_keys(case, ["id", "category", "status", "duration_ms"], "tester_output.case_results[]")


def validate_verifier_verdict(payload: dict[str, Any]) -> None:
    require_keys(
        payload,
        [
            "iter",
            "timestamp",
            "passed",
            "composite_score",
            "metric_scores",
            "hard_constraint_violations",
            "failed_case_ids",
            "feedback_to_generator",
        ],
        "verifier_verdict",
    )
