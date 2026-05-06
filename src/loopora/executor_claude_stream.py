from __future__ import annotations

import json
from collections.abc import Callable

EmitEvent = Callable[[str, dict], None]


def handle_claude_record(record: dict, state: dict, emit_event: EmitEvent) -> None:
    record_type = record.get("type")
    if record_type == "stdout":
        emit_event("codex_event", record)
        return
    if record_type == "system":
        _handle_system_record(record, emit_event)
        return
    if record_type == "assistant":
        _handle_assistant_record(record, state, emit_event)
        return
    if record_type == "user":
        _handle_user_record(record, emit_event)
        return
    if record_type == "result":
        _handle_result_record(record, state, emit_event)
        return
    if record_type == "stream_event":
        _handle_stream_event_record(record, state, emit_event)


def summarize_claude_tool_use(name: object, raw_input: object) -> str:
    tool_name = str(name or "").strip() or "Tool"
    if tool_name == "StructuredOutput":
        return ""
    payload = raw_input if isinstance(raw_input, dict) else {}
    if tool_name == "Bash":
        command = str(payload.get("command", "")).strip()
        description = str(payload.get("description", "")).strip()
        parts = [part for part in (command, description) if part]
        return f"Tool use · Bash · {' · '.join(parts)}" if parts else "Tool use · Bash"
    preview_keys = ("file_path", "path", "pattern", "glob", "query", "description")
    preview_parts = []
    for key in preview_keys:
        value = str(payload.get(key, "")).strip()
        if value:
            preview_parts.append(f"{key}={value}")
    if not preview_parts and payload:
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        preview_parts.append(serialized)
    if preview_parts:
        return f"Tool use · {tool_name} · {' · '.join(preview_parts[:2])}"
    return f"Tool use · {tool_name}"


def summarize_claude_tool_result(record: dict) -> str:
    tool_result = record.get("tool_use_result")
    if isinstance(tool_result, dict):
        stdout = str(tool_result.get("stdout", "")).strip()
        stderr = str(tool_result.get("stderr", "")).strip()
        if stdout:
            return f"Tool result · {truncate_claude_console_preview(stdout)}"
        if stderr:
            preview = truncate_claude_console_preview(stderr)
            return f"Tool result · stderr={preview}"
        if tool_result.get("interrupted"):
            return "Tool result · interrupted"
    for content in record.get("message", {}).get("content", []) or []:
        if content.get("type") != "tool_result":
            continue
        text = str(content.get("content", "")).strip()
        if text:
            preview = truncate_claude_console_preview(text)
            return f"Tool result · {preview}"
    return ""


def truncate_claude_console_preview(text: str, *, max_chars: int = 1200, max_lines: int = 24) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        return ""
    lines = cleaned.splitlines()
    limited_lines = lines[:max_lines]
    preview = "\n".join(limited_lines)
    was_truncated = len(lines) > max_lines or len(preview) > max_chars
    if len(preview) > max_chars:
        preview = preview[:max_chars].rstrip()
    if was_truncated:
        preview = preview.rstrip()
        preview += "\n... (truncated)"
    return preview


def _handle_system_record(record: dict, emit_event: EmitEvent) -> None:
    model = record.get("model") or ""
    cli_version = record.get("claude_code_version") or ""
    summary = "Claude Code ready"
    if model:
        summary += f" · model={model}"
    if cli_version:
        summary += f" · cli={cli_version}"
    emit_event("codex_event", {"type": "stdout", "message": summary})


def _handle_assistant_record(record: dict, state: dict, emit_event: EmitEvent) -> None:
    for content in record.get("message", {}).get("content", []) or []:
        if content.get("type") == "tool_use" and content.get("name") == "StructuredOutput":
            payload = content.get("input")
            if isinstance(payload, dict):
                state["structured_output"] = payload
        elif content.get("type") == "tool_use":
            summary = summarize_claude_tool_use(content.get("name"), content.get("input"))
            if summary:
                emit_event("codex_event", {"type": "stdout", "message": summary})
        elif content.get("type") == "text" and content.get("text"):
            emit_event("codex_event", {"type": "stdout", "message": content["text"]})


def _handle_user_record(record: dict, emit_event: EmitEvent) -> None:
    summary = summarize_claude_tool_result(record)
    if summary:
        emit_event("codex_event", {"type": "stdout", "message": summary})


def _handle_result_record(record: dict, state: dict, emit_event: EmitEvent) -> None:
    structured = record.get("structured_output")
    if isinstance(structured, dict):
        state["structured_output"] = structured
    result_text = str(record.get("result", "")).strip()
    if result_text:
        emit_event("codex_event", {"type": "stdout", "message": result_text})


def _handle_stream_event_record(record: dict, state: dict, emit_event: EmitEvent) -> None:
    event = record.get("event") or {}
    event_type = event.get("type")
    if event_type == "content_block_start":
        _handle_content_block_start(event, state)
    elif event_type == "content_block_delta":
        _handle_content_block_delta(event, state)
    elif event_type == "content_block_stop":
        _handle_content_block_stop(event, state, emit_event)


def _handle_content_block_start(event: dict, state: dict) -> None:
    content_block = event.get("content_block") or {}
    index = event.get("index")
    if index is not None:
        state["blocks"][index] = {
            "kind": content_block.get("type") or "",
            "name": content_block.get("name") or "",
            "buffer": "",
        }


def _handle_content_block_delta(event: dict, state: dict) -> None:
    delta = event.get("delta") or {}
    index = event.get("index")
    block = state["blocks"].setdefault(index, {"kind": "", "name": "", "buffer": ""})
    if delta.get("type") == "thinking_delta":
        block["buffer"] += str(delta.get("thinking", ""))
    elif delta.get("type") == "text_delta":
        block["buffer"] += str(delta.get("text", ""))
    elif delta.get("type") == "input_json_delta" and block.get("name") == "StructuredOutput":
        block["buffer"] += str(delta.get("partial_json", ""))


def _handle_content_block_stop(event: dict, state: dict, emit_event: EmitEvent) -> None:
    index = event.get("index")
    block = state["blocks"].pop(index, None)
    if not block:
        return
    text = str(block.get("buffer", "")).strip()
    if block.get("name") == "StructuredOutput" and text:
        _capture_structured_output(text, state)
    elif block.get("kind") in {"thinking", "text"} and text:
        emit_event("codex_event", {"type": "stdout", "message": text})


def _capture_structured_output(text: str, state: dict) -> None:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return
    if isinstance(payload, dict):
        state["structured_output"] = payload
