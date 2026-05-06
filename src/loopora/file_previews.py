from __future__ import annotations

import json
from pathlib import Path

from loopora.markdown_tools import decode_text_bytes, looks_binary, render_safe_markdown_html

MAX_FILE_PREVIEW_BYTES = 1_000_000
MAX_DIRECTORY_PREVIEW_ENTRIES = 1_000


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
    try:
        is_directory = resolved.is_dir()
    except OSError:
        is_directory = False
    if is_directory:
        return _preview_directory(base=base, relative_path=relative_path, resolved=resolved)

    suffix = resolved.suffix.lower()
    try:
        size_bytes = resolved.stat().st_size
    except OSError:
        return _preview_unreadable_file(base=base, relative_path=relative_path, resolved=resolved)
    if size_bytes > MAX_FILE_PREVIEW_BYTES:
        return _preview_oversized_file(base=base, relative_path=relative_path, resolved=resolved, size_bytes=size_bytes)
    try:
        raw_bytes = resolved.read_bytes()
    except OSError:
        return _preview_unreadable_file(
            base=base,
            relative_path=relative_path,
            resolved=resolved,
            size_bytes=size_bytes,
        )
    return _preview_file(base=base, relative_path=relative_path, resolved=resolved, suffix=suffix, raw_bytes=raw_bytes)


def _preview_directory(*, base: Path, relative_path: str, resolved: Path) -> dict:
    entries = []
    entries_truncated = False
    try:
        for index, child in enumerate(resolved.iterdir()):
            if index >= MAX_DIRECTORY_PREVIEW_ENTRIES:
                entries_truncated = True
                break
            try:
                child_is_dir = child.is_dir()
            except OSError:
                child_is_dir = False
            entries.append(
                {
                    "name": child.name,
                    "path": str(child.relative_to(base)),
                    "is_dir": child_is_dir,
                }
            )
    except OSError:
        return _preview_unreadable_directory(base=base, relative_path=relative_path, resolved=resolved)
    entries.sort(key=lambda item: (not item["is_dir"], item["name"].lower()))
    return {"kind": "directory", "base": str(base), "path": relative_path, "entries": entries, "entries_truncated": entries_truncated}


def _preview_unreadable_directory(*, base: Path, relative_path: str, resolved: Path) -> dict:
    return {
        "kind": "directory",
        "base": str(base),
        "path": relative_path,
        "name": resolved.name,
        "entries": [],
        "entries_truncated": False,
        "preview_error": "directory could not be read",
    }


def _preview_unreadable_file(
    *,
    base: Path,
    relative_path: str,
    resolved: Path,
    size_bytes: int = 0,
) -> dict:
    return {
        "kind": "file",
        "base": str(base),
        "path": relative_path,
        "name": resolved.name,
        "content": "",
        "is_binary": False,
        "size_bytes": size_bytes,
        "preview_error": "file could not be read",
    }


def _preview_oversized_file(*, base: Path, relative_path: str, resolved: Path, size_bytes: int) -> dict:
    return {
        "kind": "file",
        "base": str(base),
        "path": relative_path,
        "name": resolved.name,
        "content": "",
        "is_binary": False,
        "size_bytes": size_bytes,
        "preview_omitted": True,
        "preview_error": f"file is too large to preview; maximum size is {MAX_FILE_PREVIEW_BYTES} bytes",
    }


def _preview_file(*, base: Path, relative_path: str, resolved: Path, suffix: str, raw_bytes: bytes) -> dict:
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
