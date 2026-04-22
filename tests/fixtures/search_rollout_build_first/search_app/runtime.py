from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from .catalog import HELP_CENTER_DOCS


def _normalize_tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def ingest_help_center_slice() -> list[dict]:
    return [dict(item) for item in HELP_CENTER_DOCS if item["domain"] == "help_center"]


def build_hybrid_index(records: list[dict]) -> list[dict]:
    """Build a searchable help-center slice.

    The rollout currently still behaves like a title-only keyword search. Replace
    this placeholder with a real searchable slice that can support representative
    help-center queries and employee-only filtering.
    """

    return [
        {
            "id": record["id"],
            "title": record["title"],
            "visibility": record["visibility"],
            "tokens": Counter(_normalize_tokens(record["title"])),
        }
        for record in records
    ]


def search_help_center(query: str, *, viewer: str = "public") -> list[dict]:
    records = ingest_help_center_slice()
    index = build_hybrid_index(records)
    query_terms = _normalize_tokens(query)
    if not query_terms:
        return []

    ranked: list[dict] = []
    for item in index:
        if viewer != "employee" and item["visibility"] != "public":
            continue
        score = sum(item["tokens"].get(term, 0) for term in query_terms)
        if score <= 0:
            continue
        ranked.append(
            {
                "id": item["id"],
                "title": item["title"],
                "score": score,
                "visibility": item["visibility"],
            }
        )

    return sorted(ranked, key=lambda row: (-row["score"], row["title"]))


def write_shadow_readiness_report(
    path: str = "reports/help_center_shadow_decision.json",
) -> dict:
    report = {
        "slice": "help_center",
        "ready_for_shadow": False,
        "representative_queries": [],
        "notes": "Replace this placeholder once the first end-to-end help-center slice is real.",
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report
