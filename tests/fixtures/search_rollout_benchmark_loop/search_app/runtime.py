from __future__ import annotations

import json
from pathlib import Path

from .query_rewrite import rewrite_query
from .ranking import score_document
from .retrieval import lexical_candidates


def search_rollout(query: str, *, viewer: str = "public") -> list[dict]:
    query_terms = rewrite_query(query)
    ranked: list[dict] = []
    for doc in lexical_candidates(query_terms, viewer=viewer):
        score = score_document(doc, query_terms)
        if score <= 0:
            continue
        ranked.append({"id": doc["id"], "title": doc["title"], "score": score})
    return sorted(ranked, key=lambda item: (-item["score"], item["id"]))


def _reciprocal_rank(results: list[dict], expected_id: str) -> float:
    for index, row in enumerate(results, start=1):
        if row["id"] == expected_id:
            return 1.0 / index
    return 0.0


def run_benchmark(cases: list[dict]) -> dict:
    scores = []
    misses = []
    for case in cases:
        results = search_rollout(case["query"], viewer=case["viewer"])
        rr = _reciprocal_rank(results, case["expected_id"])
        scores.append(rr)
        if rr < 1.0:
            misses.append({"query": case["query"], "expected_id": case["expected_id"], "rr": rr})
    score = sum(scores) / len(scores)
    return {"score": score, "misses": misses, "count": len(cases)}


def write_benchmark_direction(
    benchmark_result: dict,
    holdout_result: dict,
    path: str = "reports/benchmark_direction.json",
) -> dict:
    direction = {
        "benchmark_score": benchmark_result["score"],
        "holdout_score": holdout_result["score"],
        "next_focus": "",
        "notes": "Explain whether the next round should push retrieval, reranking, or query rewrite.",
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(direction, indent=2) + "\n", encoding="utf-8")
    return direction
