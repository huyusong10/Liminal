from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from search_stack import search_help_center_shadow


def _top_result(query: str) -> dict:
    results = search_help_center_shadow(query)
    return dict(results[0]) if results else {}


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python tests/contract/high_value_query_regression_proof.py <proof-output-path>")

    workspace_root = Path.cwd()
    proof_path = (workspace_root / sys.argv[1]).resolve()
    report_path = workspace_root / "reports" / "high_value_query_root_cause.md"
    design_path = workspace_root / "design" / "high_value_query_regression.md"
    report_text = report_path.read_text(encoding="utf-8").lower() if report_path.exists() else ""
    design_text = design_path.read_text(encoding="utf-8").lower() if design_path.exists() else ""

    rotate = _top_result("rotate personal token")
    saml = _top_result("saml sign-in domain")
    checks = {
        "rotate_query_hits_latest_revision": rotate.get("id") == "hc_rotate_personal_token"
        and rotate.get("revision") == 2
        and "personal access token" in str(rotate.get("body", "")).lower(),
        "saml_query_hits_latest_revision": saml.get("id") == "hc_saml_domain_claim"
        and saml.get("revision") == 2
        and "verification record" in str(saml.get("body", "")).lower(),
        "root_cause_report_written": report_path.exists(),
        "root_cause_report_mentions_revision_selection": any(
            phrase in report_text
            for phrase in (
                "revision selection",
                "latest revision",
                "freshness",
                "stale revision",
            )
        ),
        "design_contract_written": design_path.exists(),
        "design_contract_mentions_regression": "regression" in design_text and "revision" in design_text,
    }
    payload = {
        "contract": "high-value-query-regression-proof",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "pass": checks,
        "summary": "High-value query regression is repaired at the first failing layer."
        if all(checks.values())
        else "The shadow regression is still unresolved or undocumented.",
    }
    proof_path.parent.mkdir(parents=True, exist_ok=True)
    proof_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
