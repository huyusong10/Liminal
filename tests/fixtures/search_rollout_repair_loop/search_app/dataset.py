from __future__ import annotations

MAINTENANCE_WINDOW_SECONDS = 2.4
CHUNK_TEMPLATES = [
    "hybrid retrieval pipeline emits lexical and dense candidates for the same search query",
    "help center freshness jobs batch updates into the same shard family for rollout",
    "permission bitmaps are rebuilt from acl groups during index materialization",
    "reranking features are recalculated for duplicate content blocks during reindex",
    "shadow rollout dashboards compare lexical parity with hybrid scoring outputs",
    "employee-only manuals reuse the same rollout checklist text across many documents",
]
ACL_GROUPS = [
    ("public",),
    ("public", "billing"),
    ("employee",),
    ("employee", "search-admin"),
]


def build_reindex_dataset(size: int = 180) -> list[dict]:
    records: list[dict] = []
    for index in range(size):
        acl = ACL_GROUPS[index % len(ACL_GROUPS)]
        body = " || ".join(
            [
                CHUNK_TEMPLATES[index % len(CHUNK_TEMPLATES)],
                CHUNK_TEMPLATES[(index + 1) % len(CHUNK_TEMPLATES)],
                CHUNK_TEMPLATES[index % len(CHUNK_TEMPLATES)],
                CHUNK_TEMPLATES[(index + 2) % len(CHUNK_TEMPLATES)],
            ]
        )
        records.append(
            {
                "id": f"doc-{index:03d}",
                "roles": acl,
                "body": body,
            }
        )
    return records
