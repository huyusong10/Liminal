from __future__ import annotations

import html
import re

import markdown as markdown_lib

MARKDOWN_EXTENSIONS = ("fenced_code", "tables", "sane_lists")
YAML_FRONT_MATTER_PATTERN = re.compile(r"\A---\s*\n.*?\n---\s*(?:\n|$)", re.DOTALL)


def normalize_markdown_text(markdown_text: str | None) -> str:
    return str(markdown_text or "").replace("\r\n", "\n").replace("\r", "\n")


def looks_binary(data: bytes) -> bool:
    if not data:
        return False
    sample = data[:4096]
    if b"\x00" in sample:
        return True
    allowed = {9, 10, 13}
    suspicious = sum(1 for byte in sample if byte < 32 and byte not in allowed)
    return suspicious / len(sample) > 0.1


def decode_text_bytes(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def strip_yaml_front_matter(markdown_text: str | None) -> str:
    normalized = normalize_markdown_text(markdown_text)
    return YAML_FRONT_MATTER_PATTERN.sub("", normalized, count=1)


def render_safe_markdown_html(markdown_text: str | None, *, strip_front_matter: bool = False) -> str:
    normalized = normalize_markdown_text(markdown_text)
    if strip_front_matter:
        normalized = strip_yaml_front_matter(normalized)
    return markdown_lib.markdown(
        html.escape(normalized),
        extensions=list(MARKDOWN_EXTENSIONS),
    )
