from __future__ import annotations

import json
import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from search_stack import search_help_center


def _top_id(query: str, *, viewer: str = "public") -> str:
    results = search_help_center(query, viewer=viewer)
    return str(results[0]["id"]) if results else ""


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python tests/contract/help_center_shadow_proof.py <proof-output-path>")

    workspace_root = Path.cwd()
    proof_path = (workspace_root / sys.argv[1]).resolve()
    report_path = workspace_root / "reports" / "help_center_shadow_decision.json"
    design_path = workspace_root / "design" / "help_center_shadow.md"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
    design_text = design_path.read_text(encoding="utf-8") if design_path.exists() else ""

    checks = {
        "rotate_personal_token_query": _top_id("rotate personal token") == "hc_rotate_personal_token",
        "saml_sign_in_domain_query": _top_id("saml sign-in domain") == "hc_saml_domain_claim",
        "billing_export_csv_query": _top_id("billing export csv") == "hc_billing_export_csv",
        "employee_only_doc_hidden_from_public": _top_id("search permission rollout checklist", viewer="public") == "",
        "employee_only_doc_visible_to_employee": _top_id("search permission rollout checklist", viewer="employee") == "hc_search_permissions_runbook",
        "shadow_report_written": report_path.exists(),
        "shadow_report_ready": report.get("ready_for_shadow") is True,
        "shadow_report_lists_queries": set(report.get("representative_queries") or [])
        >= {"rotate personal token", "saml sign-in domain", "billing export csv"},
        "design_contract_written": design_path.exists(),
        "design_contract_mentions_shadow": "shadow" in design_text.lower() and "help center" in design_text.lower(),
    }

    payload = {
        "contract": "help-center-shadow-proof",
        "generated_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
        "pass": checks,
        "summary": "Help-center slice is shadow-ready." if all(checks.values()) else "Help-center slice is not ready for shadow traffic yet.",
    }

    proof_path.parent.mkdir(parents=True, exist_ok=True)
    proof_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
