from __future__ import annotations

import json
from pathlib import Path

from loopora.markdown_tools import decode_text_bytes, looks_binary, render_safe_markdown_html


def _parse_jsonl_preview(text: str) -> tuple[list[object], list[dict[str, object]]]:
    parsed_items: list[object] = []
    parse_errors: list[dict[str, object]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            parsed_items.append(json.loads(line))
        except json.JSONDecodeError as exc:
            parse_errors.append(
                {
                    "line": line_number,
                    "error": exc.msg,
                }
            )
    return parsed_items, parse_errors


def preview_existing_path(*, base: Path, relative_path: str, resolved: Path) -> dict:
    if resolved.is_dir():
        entries = []
        for child in sorted(resolved.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
            entries.append(
                {
                    "name": child.name,
                    "path": str(child.relative_to(base)),
                    "is_dir": child.is_dir(),
                }
            )
        return {"kind": "directory", "base": str(base), "path": relative_path, "entries": entries}

    suffix = resolved.suffix.lower()
    raw_bytes = resolved.read_bytes()
    if suffix in {".json", ".jsonl"}:
        text = decode_text_bytes(raw_bytes)
        parse_error: str | None = None
        jsonl_parse_errors: list[dict[str, object]] = []
        try:
            if suffix == ".jsonl":
                parsed, jsonl_parse_errors = _parse_jsonl_preview(text)
            else:
                parsed = json.loads(text)
            text = json.dumps(parsed, ensure_ascii=False, indent=2)
        except json.JSONDecodeError as exc:
            parse_error = exc.msg
    elif looks_binary(raw_bytes):
        return {
            "kind": "file",
            "base": str(base),
            "path": relative_path,
            "name": resolved.name,
            "is_binary": True,
            "size_bytes": len(raw_bytes),
            "content": "",
        }
    else:
        text = decode_text_bytes(raw_bytes)
        parse_error = None
        jsonl_parse_errors = []

    payload = {
        "kind": "file",
        "base": str(base),
        "path": relative_path,
        "name": resolved.name,
        "content": text,
        "is_binary": False,
        "size_bytes": len(raw_bytes),
    }
    if suffix == ".json" and parse_error:
        payload["parse_error"] = parse_error
    if suffix == ".jsonl" and jsonl_parse_errors:
        payload["jsonl_parse_errors"] = jsonl_parse_errors
    if suffix in {".md", ".markdown"}:
        payload["rendered_html"] = render_safe_markdown_html(text)
    return payload


__all__ = ["preview_existing_path"]
