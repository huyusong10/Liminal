from __future__ import annotations

TITLE_WEIGHT = 2.0
BODY_WEIGHT = 1.0
TAG_WEIGHT = 1.0


def score_document(doc: dict, query_terms: list[str]) -> float:
    score = 0.0
    for term in query_terms:
        score += doc["title_tokens"].count(term) * TITLE_WEIGHT
        score += doc["body_tokens"].count(term) * BODY_WEIGHT
        score += doc["tag_tokens"].count(term) * TAG_WEIGHT
    return score
