from __future__ import annotations

from .catalog import SEARCH_DOCS
from .query_rewrite import normalize_tokens


def lexical_candidates(query_terms: list[str], *, viewer: str) -> list[dict]:
    candidates: list[dict] = []
    for doc in SEARCH_DOCS:
        if viewer != "employee" and doc["visibility"] != "public":
            continue
        title_tokens = normalize_tokens(doc["title"])
        body_tokens = normalize_tokens(doc["body"])
        tag_tokens = list(doc["tags"])
        candidates.append(
            {
                "id": doc["id"],
                "title": doc["title"],
                "visibility": doc["visibility"],
                "title_tokens": title_tokens,
                "body_tokens": body_tokens,
                "tag_tokens": tag_tokens,
            }
        )
    return candidates
