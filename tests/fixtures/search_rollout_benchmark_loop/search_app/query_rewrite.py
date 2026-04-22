from __future__ import annotations

import re

QUERY_SYNONYMS: dict[str, list[str]] = {}


def normalize_tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def rewrite_query(query: str) -> list[str]:
    tokens = normalize_tokens(query)
    expanded = list(tokens)
    for token in tokens:
        expanded.extend(QUERY_SYNONYMS.get(token, []))
    return expanded
