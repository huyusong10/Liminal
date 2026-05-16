from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PUBLIC_READER_DOCS = (
    ROOT / "README.md",
    ROOT / "README.zh-CN.md",
    ROOT / "HUMAN-SHAPED-LOOP.md",
    ROOT / "HUMAN-SHAPED-LOOP.zh-CN.md",
)
CHINESE_PUBLIC_READER_DOCS = (
    ROOT / "README.zh-CN.md",
    ROOT / "HUMAN-SHAPED-LOOP.zh-CN.md",
)
INLINE_REVIEW_NOTE_PATTERN = re.compile(
    r"（[^）]*(?:一点也|这个图|这里可能|看看怎么|有点突兀|受到质疑|吸引力|不是它能干什么|拒绝和阻断|不够好理解|不要出现|请巡检|用户很容易看不懂|太冗长|不适合做最后总结|简化|去掉)[^）]*）"
)
CHINESE_PUBLIC_INTERNAL_TERM_PATTERN = re.compile(
    r"\b(?:happy path|proof harness|run contract|step capsule|judgment_contract|required coverage|GateKeeper|blocking issue|workflow handoff|run status|task verdict|READY)\b|benchmark",
    re.IGNORECASE,
)


def test_public_reader_docs_do_not_ship_inline_review_notes() -> None:
    for doc in PUBLIC_READER_DOCS:
        text = doc.read_text(encoding="utf-8")
        leaked_notes = INLINE_REVIEW_NOTE_PATTERN.findall(text)

        assert not leaked_notes, f"{doc.relative_to(ROOT)} exposes inline review notes: {leaked_notes[:3]}"


def test_chinese_public_reader_docs_use_reader_level_runtime_language() -> None:
    for doc in CHINESE_PUBLIC_READER_DOCS:
        text = doc.read_text(encoding="utf-8")
        internal_terms = sorted(set(CHINESE_PUBLIC_INTERNAL_TERM_PATTERN.findall(text)))

        assert not internal_terms, f"{doc.relative_to(ROOT)} exposes internal runtime terms: {internal_terms[:5]}"
