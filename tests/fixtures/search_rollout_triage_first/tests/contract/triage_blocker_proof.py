from __future__ import annotations

import json
import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from search_stack import RELEASE_BLOCKER_ORDER, search_rollout


def _top_id(query: str, *, viewer: str = "public") -> str:
    results = search_rollout(query, viewer=viewer)
    return str(results[0]["id"]) if results else ""


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python tests/contract/triage_blocker_proof.py <proof-output-path>")

    workspace_root = Path.cwd()
    proof_path = (workspace_root / sys.argv[1]).resolve()
    report_path = workspace_root / "reports" / "triage_decision.json"
    design_path = workspace_root / "design" / "rollout_triage.md"
    decision = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
    design_text = design_path.read_text(encoding="utf-8").lower() if design_path.exists() else ""

    checks = {
        "public_permission_leak_closed": _top_id("shadow rollout checklist", viewer="public") == "",
        "employee_visibility_preserved": _top_id("shadow rollout checklist", viewer="employee") == "manual_shadow_rollout_checklist",
        "triage_decision_written": report_path.exists(),
        "triage_decision_picks_primary_blocker": decision.get("chosen_blocker") == RELEASE_BLOCKER_ORDER[0],
        "triage_decision_lists_deferred_symptoms": len(decision.get("deferred_symptoms") or []) >= 2,
        "design_contract_written": design_path.exists(),
        "design_contract_mentions_triage": "triage" in design_text and "permission" in design_text,
    }
    payload = {
        "contract": "triage-blocker-proof",
        "generated_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
        "pass": checks,
        "summary": "The rollout blocker was narrowed and repaired for this round."
        if all(checks.values())
        else "The rollout blocker is still unclear or unresolved.",
    }
    proof_path.parent.mkdir(parents=True, exist_ok=True)
    proof_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
