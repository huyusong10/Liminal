from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path

from .revisions import HELP_CENTER_REVISIONS, pick_current_revision


def _normalize_tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def ingest_revisions() -> list[dict]:
    return [dict(item) for item in HELP_CENTER_REVISIONS]


def build_shadow_index() -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for revision in ingest_revisions():
        grouped[revision["canonical_id"]].append(revision)

    rows: list[dict] = []
    for canonical_id, revisions in grouped.items():
        current = pick_current_revision(revisions)
        rows.append(
            {
                "id": canonical_id,
                "title": current["title"],
                "body": current["body"],
                "visibility": current["visibility"],
                "revision": current["revision"],
                "tokens": Counter(_normalize_tokens(current["title"] + " " + current["body"])),
            }
        )
    return rows


def search_help_center_shadow(query: str, *, viewer: str = "public") -> list[dict]:
    query_terms = _normalize_tokens(query)
    if not query_terms:
        return []

    ranked: list[dict] = []
    for row in build_shadow_index():
        if viewer != "employee" and row["visibility"] != "public":
            continue
        score = sum(row["tokens"].get(term, 0) for term in query_terms)
        if score <= 0:
            continue
        ranked.append(
            {
                "id": row["id"],
                "title": row["title"],
                "body": row["body"],
                "revision": row["revision"],
                "score": score,
            }
        )
    return sorted(ranked, key=lambda item: (-item["score"], item["id"]))


def write_root_cause_report(
    path: str = "reports/high_value_query_root_cause.md",
) -> Path:
    report_path = Path(path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        "# Root cause placeholder\n\nDocument the first failing layer before shipping a repair.\n",
        encoding="utf-8",
    )
    return report_path
