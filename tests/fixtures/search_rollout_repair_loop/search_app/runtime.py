from __future__ import annotations

import json
import time
from pathlib import Path

from .costs import chunk_embedding, metrics_snapshot, permission_digest, reset_metrics
from .dataset import MAINTENANCE_WINDOW_SECONDS, build_reindex_dataset


def _split_chunks(body: str) -> list[str]:
    return [chunk.strip() for chunk in body.split("||") if chunk.strip()]


def full_reindex(records: list[dict] | None = None) -> dict:
    data = list(records or build_reindex_dataset())
    reset_metrics()
    started_at = time.perf_counter()
    index_rows: list[dict] = []
    unique_chunks: set[str] = set()
    unique_acl_groups: set[tuple[str, ...]] = set()

    for record in data:
        roles = tuple(record["roles"])
        unique_acl_groups.add(tuple(sorted(roles)))
        for chunk in _split_chunks(record["body"]):
            unique_chunks.add(chunk)
            # Bottleneck 1: duplicate ACL work is recomputed for every row.
            # Bottleneck 2: duplicate chunk embeddings are also recomputed.
            index_rows.append(
                {
                    "doc_id": record["id"],
                    "acl_digest": permission_digest(roles),
                    "embedding": chunk_embedding(chunk),
                }
            )

    elapsed = time.perf_counter() - started_at
    return {
        "total_seconds": elapsed,
        "maintenance_window_seconds": MAINTENANCE_WINDOW_SECONDS,
        **metrics_snapshot(),
        "index_rows": len(index_rows),
        "unique_chunk_count": len(unique_chunks),
        "unique_acl_count": len(unique_acl_groups),
    }


def write_reindex_repair_review(
    metrics: dict,
    path: str = "reports/reindex_repair_review.json",
) -> dict:
    review = {
        "meets_window": False,
        "metrics": metrics,
        "notes": "Document the first bottleneck, the second bottleneck, and why the final state is inside the maintenance window.",
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(review, indent=2) + "\n", encoding="utf-8")
    return review
