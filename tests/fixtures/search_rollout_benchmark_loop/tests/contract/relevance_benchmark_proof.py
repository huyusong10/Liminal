from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from search_stack import BENCHMARK_CASES, HOLDOUT_CASES, run_benchmark, search_rollout


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python tests/contract/relevance_benchmark_proof.py <proof-output-path>")

    workspace_root = Path.cwd()
    proof_path = (workspace_root / sys.argv[1]).resolve()
    report_path = workspace_root / "reports" / "benchmark_direction.json"
    design_path = workspace_root / "design" / "hybrid_search.md"
    benchmark = run_benchmark(BENCHMARK_CASES)
    holdout = run_benchmark(HOLDOUT_CASES)
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
    design_text = design_path.read_text(encoding="utf-8").lower() if design_path.exists() else ""

    checks = {
        "benchmark_target_met": benchmark["score"] >= 0.95,
        "holdout_target_met": holdout["score"] >= 0.95,
        "direction_report_written": report_path.exists(),
        "direction_report_has_next_focus": str(report.get("next_focus") or "") in {"retrieval", "reranking", "query_rewrite"},
        "direction_report_scores_match_workspace": abs(float(report.get("benchmark_score") or 0.0) - benchmark["score"]) < 1e-9
        and abs(float(report.get("holdout_score") or 0.0) - holdout["score"]) < 1e-9,
        "public_visibility_contract_preserved": "manual_shadow_rollout_checklist"
        not in {row["id"] for row in search_rollout("shadow rollout checklist", viewer="public")},
        "employee_visibility_contract_preserved": "manual_shadow_rollout_checklist"
        in {row["id"] for row in search_rollout("shadow rollout checklist", viewer="employee")},
        "design_contract_written": design_path.exists(),
        "design_contract_mentions_benchmark": "benchmark" in design_text and "hybrid search" in design_text,
    }
    payload = {
        "contract": "relevance-benchmark-proof",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "pass": checks,
        "benchmark": benchmark,
        "holdout": holdout,
        "summary": "Benchmark-driven relevance goals are met for this round."
        if all(checks.values())
        else "Benchmark-driven relevance goals are still below the release line or undocumented.",
    }
    proof_path.parent.mkdir(parents=True, exist_ok=True)
    proof_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
