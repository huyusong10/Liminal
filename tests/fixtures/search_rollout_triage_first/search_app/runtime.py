from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from .catalog import SEARCH_DOCS
from .symptoms import symptom_snapshot


def _normalize_tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _visibility_allows(doc: dict, *, viewer: str, query_terms: list[str], score: int) -> bool:
    if viewer == "employee":
        return True
    if doc["visibility"] == "public":
        return True
    # Bug: rollout triage still treats a strong lexical overlap as if it were
    # sufficient evidence to surface internal manuals to public traffic.
    return score >= 3 and len(query_terms) >= 2


def search_rollout(query: str, *, viewer: str = "public") -> list[dict]:
    query_terms = _normalize_tokens(query)
    ranked: list[dict] = []
    for doc in SEARCH_DOCS:
        haystack = Counter(_normalize_tokens(" ".join([doc["title"], doc["body"], doc["domain"]])))
        score = sum(haystack.get(term, 0) for term in query_terms)
        if score <= 0:
            continue
        if not _visibility_allows(doc, viewer=viewer, query_terms=query_terms, score=score):
            continue
        ranked.append(
            {
                "id": doc["id"],
                "title": doc["title"],
                "visibility": doc["visibility"],
                "domain": doc["domain"],
                "score": score,
            }
        )
    return sorted(ranked, key=lambda item: (-item["score"], item["id"]))


def write_triage_decision(
    path: str = "reports/triage_decision.json",
) -> dict:
    decision = {
        "chosen_blocker": "",
        "why_this_round": "Document the blocker this round will own before expanding scope.",
        "deferred_symptoms": symptom_snapshot(),
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(decision, indent=2) + "\n", encoding="utf-8")
    return decision
