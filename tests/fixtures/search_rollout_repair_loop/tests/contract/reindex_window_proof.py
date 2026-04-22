from __future__ import annotations

import json
import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from search_stack import MAINTENANCE_WINDOW_SECONDS, build_reindex_dataset, full_reindex


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python tests/contract/reindex_window_proof.py <proof-output-path>")

    workspace_root = Path.cwd()
    proof_path = (workspace_root / sys.argv[1]).resolve()
    review_path = workspace_root / "reports" / "reindex_repair_review.json"
    design_path = workspace_root / "design" / "reindex_contract.md"
    metrics = full_reindex(build_reindex_dataset())
    review = json.loads(review_path.read_text(encoding="utf-8")) if review_path.exists() else {}
    design_text = design_path.read_text(encoding="utf-8").lower() if design_path.exists() else ""
    review_notes = str(review.get("notes") or "").lower()

    checks = {
        "inside_maintenance_window": metrics["total_seconds"] <= MAINTENANCE_WINDOW_SECONDS,
        "permission_digest_calls_reduced": metrics["permission_digest_calls"] <= metrics["unique_acl_count"] + 8,
        "embedding_calls_reduced": metrics["embedding_calls"] <= metrics["unique_chunk_count"] + 8,
        "repair_review_written": review_path.exists(),
        "repair_review_marks_window": review.get("meets_window") is True,
        "repair_review_metrics_match_workspace": dict(review.get("metrics") or {}) == metrics,
        "repair_review_mentions_bottlenecks": any(
            phrase in review_notes
            for phrase in ("acl", "permission", "chunk", "embedding", "bottleneck")
        ),
        "design_contract_written": design_path.exists(),
        "design_contract_mentions_window": "maintenance window" in design_text and "bottleneck" in design_text,
    }
    payload = {
        "contract": "reindex-window-proof",
        "generated_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
        "pass": checks,
        "metrics": metrics,
        "summary": "Full reindex is back inside the maintenance window."
        if all(checks.values())
        else "Full reindex still violates the maintenance window or lacks a trustworthy repair review.",
    }
    proof_path.parent.mkdir(parents=True, exist_ok=True)
    proof_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
