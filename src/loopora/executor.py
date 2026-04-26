from __future__ import annotations

import json
import os
import queue
import re
import shlex
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from loopora.branding import (
    APP_STATE_DIRNAME,
    FAKE_DELAY_ENV,
    FAKE_EXECUTOR_ENV,
)
from loopora.providers import (
    coerce_reasoning_setting,
    executor_profile,
    normalize_executor_kind,
    normalize_executor_mode,
    normalize_reasoning_setting,
)
from loopora.utils import utc_now


class ExecutorError(RuntimeError):
    """Raised when a role execution fails."""


class ExecutionStopped(BaseException):
    """Raised when a run is interrupted by the user."""


@dataclass(slots=True)
class RoleRequest:
    run_id: str
    role: str
    prompt: str
    workdir: Path
    model: str
    reasoning_effort: str
    output_schema: dict
    output_path: Path
    run_dir: Path
    executor_kind: str = "codex"
    executor_mode: str = "preset"
    command_cli: str = ""
    command_args_text: str = ""
    inherit_session: bool = False
    resume_session_id: str = ""
    extra_cli_args_text: str = ""
    sandbox: str = "workspace-write"
    idle_timeout_seconds: float | None = None
    role_archetype: str = ""
    role_name: str = ""
    step_id: str = ""
    extra_context: dict = field(default_factory=dict)


class CodexExecutor:
    def execute(
        self,
        request: RoleRequest,
        emit_event: Callable[[str, dict], None],
        should_stop: Callable[[], bool],
        set_child_pid: Callable[[int | None], None],
        ) -> dict:
        raise NotImplementedError


def normalize_reasoning_effort(value: str | None, executor_kind: str = "codex") -> str:
    return normalize_reasoning_setting(value, executor_kind=executor_kind)


def coerce_reasoning_effort(value: str | None, executor_kind: str = "codex") -> str:
    return coerce_reasoning_setting(value, executor_kind=executor_kind)


def build_codex_exec_args(request: RoleRequest, schema_path: Path) -> list[str]:
    reasoning_effort = coerce_reasoning_effort(request.reasoning_effort, request.executor_kind)
    extra_args = parse_extra_cli_args_text(request.extra_cli_args_text)
    resume_session_id = request.resume_session_id.strip()
    if request.inherit_session and resume_session_id:
        args = [
            "codex",
            "exec",
            "resume",
            "--json",
            "--skip-git-repo-check",
            "--output-last-message",
            str(request.output_path),
        ]
        if request.model.strip():
            args.extend(["--model", request.model.strip()])
        args.extend(["-c", f'model_reasoning_effort="{reasoning_effort}"'])
        args.extend(extra_args)
        args.append(resume_session_id)
        args.append(request.prompt)
        return args

    args = [
        "codex",
        "exec",
        "--json",
        "--skip-git-repo-check",
        "--cd",
        str(request.workdir),
        "--sandbox",
        request.sandbox,
        "--output-schema",
        str(schema_path),
        "--output-last-message",
        str(request.output_path),
    ]
    if request.model.strip():
        args.extend(["--model", request.model.strip()])
    args.extend(["-c", f'model_reasoning_effort="{reasoning_effort}"'])
    args.extend(extra_args)
    args.append(request.prompt)
    return args


def build_claude_exec_args(request: RoleRequest) -> list[str]:
    extra_args = parse_extra_cli_args_text(request.extra_cli_args_text)
    args = ["claude", "--setting-sources", "local,project"]
    if request.inherit_session and request.resume_session_id.strip():
        args.extend(["--resume", request.resume_session_id.strip()])
    args.extend(["-p", "--output-format", "stream-json", "--include-partial-messages"])
    if not request.inherit_session:
        args.append("--no-session-persistence")
    args.extend(
        [
            "--permission-mode",
            "bypassPermissions",
            "--json-schema",
            json.dumps(request.output_schema, ensure_ascii=False),
        ]
    )
    if request.model.strip():
        args.extend(["--model", request.model.strip()])
    reasoning_effort = coerce_reasoning_effort(request.reasoning_effort, request.executor_kind)
    if reasoning_effort:
        args.extend(["--effort", reasoning_effort])
    args.extend(extra_args)
    args.append(request.prompt)
    return args


def build_opencode_exec_args(request: RoleRequest) -> list[str]:
    extra_args = parse_extra_cli_args_text(request.extra_cli_args_text)
    args = [
        "opencode",
        "run",
        "--format",
        "json",
        "--dir",
        str(request.workdir),
        "--dangerously-skip-permissions",
    ]
    if request.inherit_session:
        if request.resume_session_id.strip():
            args.extend(["--session", request.resume_session_id.strip()])
    args.extend(extra_args)
    if request.model.strip():
        args.extend(["--model", request.model.strip()])
    variant = coerce_reasoning_effort(request.reasoning_effort, request.executor_kind)
    if variant:
        args.extend(["--variant", variant])
    args.append(request.prompt)
    return args


def parse_command_args_text(value: str | None) -> list[str]:
    if not value:
        return []
    return [line.strip() for line in str(value).splitlines() if line.strip()]


def parse_extra_cli_args_text(value: str | None) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    try:
        return shlex.split(text)
    except ValueError as exc:
        raise ValueError(f"invalid extra CLI args: {exc}") from exc


def validate_extra_cli_args_text(value: str | None) -> list[str]:
    return parse_extra_cli_args_text(value)


def validate_command_args_text(command_args_text: str | None, *, executor_kind: str) -> list[str]:
    args = parse_command_args_text(command_args_text)
    if not args:
        raise ValueError("custom command arguments are required in command mode")
    joined = "\n".join(args)
    profile = executor_profile(executor_kind)
    required_placeholders = profile.command_required_placeholders
    missing = [placeholder for placeholder in required_placeholders if placeholder not in joined]
    if missing:
        joined_missing = ", ".join(missing)
        raise ValueError(f"custom command is missing required placeholders: {joined_missing}")
    return args


def build_custom_exec_args(request: RoleRequest, schema_path: Path) -> list[str]:
    cli_name = request.command_cli.strip()
    if not cli_name:
        raise ValueError("custom command executable is required in command mode")
    template_args = validate_command_args_text(request.command_args_text, executor_kind=request.executor_kind)
    extra_args = parse_extra_cli_args_text(request.extra_cli_args_text)
    replacements = {
        "{workdir}": str(request.workdir),
        "{schema_path}": str(schema_path),
        "{output_path}": str(request.output_path),
        "{prompt}": request.prompt,
        "{sandbox}": request.sandbox,
        "{json_schema}": json.dumps(request.output_schema, ensure_ascii=False),
        "{model}": request.model,
        "{reasoning_effort}": request.reasoning_effort,
        "{resume_session_id}": request.resume_session_id,
        "{alignment_session_id}": str(request.extra_context.get("alignment_session_id", "")),
        "{session_ref_json}": json.dumps(request.extra_context.get("session_ref") or {}, ensure_ascii=False),
    }
    placeholder_pattern = re.compile("|".join(re.escape(placeholder) for placeholder in replacements))
    resolved_args = []
    extra_args_consumed = False
    for template_arg in template_args:
        if template_arg.strip() == "{extra_cli_args}":
            resolved_args.extend(extra_args)
            extra_args_consumed = True
            continue
        if template_arg.strip() == "{prompt}" and extra_args and not extra_args_consumed:
            resolved_args.extend(extra_args)
            extra_args_consumed = True
        value = placeholder_pattern.sub(lambda match: replacements[match.group(0)], template_arg)
        if not value:
            if resolved_args and resolved_args[-1].startswith("-"):
                resolved_args.pop()
            continue
        resolved_args.append(value)
    if extra_args and not extra_args_consumed:
        resolved_args.extend(extra_args)
    return [cli_name, *resolved_args]


class RealCodexExecutor(CodexExecutor):
    def execute(
        self,
        request: RoleRequest,
        emit_event: Callable[[str, dict], None],
        should_stop: Callable[[], bool],
        set_child_pid: Callable[[int | None], None],
    ) -> dict:
        executor_kind = normalize_executor_kind(request.executor_kind)
        request.executor_mode = normalize_executor_mode(request.executor_mode)
        request.output_path.parent.mkdir(parents=True, exist_ok=True)
        if executor_kind == "codex":
            return self._execute_codex(request, emit_event, should_stop, set_child_pid)
        if executor_kind == "claude":
            return self._execute_claude(request, emit_event, should_stop, set_child_pid)
        if executor_kind == "opencode":
            return self._execute_opencode(request, emit_event, should_stop, set_child_pid)
        if executor_kind == "custom":
            return self._execute_custom(request, emit_event, should_stop, set_child_pid)
        raise ExecutorError(f"unsupported executor kind: {executor_kind}")

    @staticmethod
    def _normalize_session_key(value: object) -> str:
        return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())

    @classmethod
    def _extract_session_ref(cls, payload: object) -> dict[str, str]:
        session_id = ""
        rollout_path = ""

        def visit(value: object) -> None:
            nonlocal session_id, rollout_path
            if session_id and rollout_path:
                return
            if isinstance(value, dict):
                for key, child in value.items():
                    normalized_key = cls._normalize_session_key(key)
                    if normalized_key == "sessionid":
                        if isinstance(child, str) and child.strip():
                            session_id = child.strip()
                        elif isinstance(child, dict):
                            uuid_value = child.get("uuid")
                            if isinstance(uuid_value, str) and uuid_value.strip():
                                session_id = uuid_value.strip()
                    elif normalized_key == "rolloutpath" and isinstance(child, str) and child.strip():
                        rollout_path = child.strip()
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        visit(payload)
        if not session_id and rollout_path:
            match = re.search(
                r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.jsonl$",
                rollout_path,
                re.IGNORECASE,
            )
            if match:
                session_id = match.group(1)
        ref: dict[str, str] = {}
        if session_id:
            ref["session_id"] = session_id
        if rollout_path:
            ref["rollout_path"] = rollout_path
        return ref

    def _capture_session_ref(self, request: RoleRequest, payload: object) -> None:
        if not request.inherit_session:
            return
        ref = self._extract_session_ref(payload)
        if not ref:
            return
        current = request.extra_context.get("session_ref")
        merged = dict(current) if isinstance(current, dict) else {}
        merged.update(ref)
        request.extra_context["session_ref"] = merged

    def _infer_codex_session_ref(self, request: RoleRequest) -> None:
        if not request.inherit_session:
            return
        current = request.extra_context.get("session_ref")
        if isinstance(current, dict) and current.get("session_id"):
            return
        started_at = float(request.extra_context.get("_executor_started_at") or 0.0)
        codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
        sessions_dir = codex_home / "sessions"
        if not sessions_dir.exists():
            return
        candidates = sorted(sessions_dir.rglob("rollout-*.jsonl"), key=lambda path: path.stat().st_mtime, reverse=True)
        workdir = str(request.workdir.resolve())
        for path in candidates[:50]:
            try:
                stat = path.stat()
                if started_at and stat.st_mtime + 1 < started_at:
                    break
                first_line = path.read_text(encoding="utf-8").splitlines()[0]
                payload = json.loads(first_line)
            except (OSError, IndexError, json.JSONDecodeError):
                continue
            cwd = ""
            if isinstance(payload, dict):
                cwd = str(payload.get("cwd") or payload.get("session_meta", {}).get("cwd") or "").strip()
            if cwd and Path(cwd).expanduser().resolve().as_posix() != Path(workdir).as_posix():
                continue
            ref = self._extract_session_ref(payload)
            if not ref:
                ref = self._extract_session_ref({"rollout_path": str(path)})
            if not ref:
                continue
            merged = dict(current) if isinstance(current, dict) else {}
            merged.update(ref)
            request.extra_context["session_ref"] = merged
            return

    def _execute_codex(
        self,
        request: RoleRequest,
        emit_event: Callable[[str, dict], None],
        should_stop: Callable[[], bool],
        set_child_pid: Callable[[int | None], None],
    ) -> dict:
        schema_path = request.run_dir / f"{request.role}_schema.json"
        schema_path.write_text(json.dumps(request.output_schema, ensure_ascii=False, indent=2), encoding="utf-8")
        args = build_custom_exec_args(request, schema_path) if request.executor_mode == "command" else build_codex_exec_args(request, schema_path)
        if request.inherit_session:
            request.extra_context.setdefault("session_ref", {})
        return_code = self._stream_process(
            request,
            args,
            emit_event,
            should_stop,
            set_child_pid,
            line_handler=lambda line: self._handle_codex_line(line, request, emit_event),
        )

        if return_code != 0:
            raise ExecutorError(f"codex exec failed for role={request.role} exit_code={return_code}")

        if not request.output_path.exists():
            raise ExecutorError(f"codex exec did not produce an output file for role={request.role}")

        self._infer_codex_session_ref(request)
        if request.inherit_session and request.resume_session_id.strip():
            current = request.extra_context.get("session_ref")
            if not isinstance(current, dict) or not current.get("session_id"):
                request.extra_context["session_ref"] = {"session_id": request.resume_session_id.strip()}

        try:
            return json.loads(request.output_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            payload = self._parse_structured_output_from_text(request.output_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return payload
            raise ExecutorError(f"role={request.role} produced invalid JSON output") from exc

    def _execute_claude(
        self,
        request: RoleRequest,
        emit_event: Callable[[str, dict], None],
        should_stop: Callable[[], bool],
        set_child_pid: Callable[[int | None], None],
    ) -> dict:
        schema_path = request.run_dir / f"{request.role}_schema.json"
        schema_path.write_text(json.dumps(request.output_schema, ensure_ascii=False, indent=2), encoding="utf-8")
        args = build_custom_exec_args(request, schema_path) if request.executor_mode == "command" else build_claude_exec_args(request)
        if request.inherit_session:
            request.extra_context.setdefault("session_ref", {})
        state = {
            "blocks": {},
            "structured_output": None,
        }
        return_code = self._stream_process(
            request,
            args,
            emit_event,
            should_stop,
            set_child_pid,
            line_handler=lambda line: self._handle_claude_line(line, state, emit_event, request),
        )
        if return_code != 0:
            raise ExecutorError(f"claude print failed for role={request.role} exit_code={return_code}")
        payload = state.get("structured_output")
        if not isinstance(payload, dict):
            raise ExecutorError(f"claude did not produce structured output for role={request.role}")
        if request.inherit_session and request.resume_session_id.strip():
            current = request.extra_context.get("session_ref")
            if not isinstance(current, dict) or not current.get("session_id"):
                request.extra_context["session_ref"] = {"session_id": request.resume_session_id.strip()}
        request.output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return payload

    def _execute_opencode(
        self,
        request: RoleRequest,
        emit_event: Callable[[str, dict], None],
        should_stop: Callable[[], bool],
        set_child_pid: Callable[[int | None], None],
    ) -> dict:
        schema_path = request.run_dir / f"{request.role}_schema.json"
        schema_path.write_text(json.dumps(request.output_schema, ensure_ascii=False, indent=2), encoding="utf-8")
        args = build_custom_exec_args(request, schema_path) if request.executor_mode == "command" else build_opencode_exec_args(request)
        if request.inherit_session:
            request.extra_context.setdefault("session_ref", {})
        state = {
            "latest_text": "",
            "text_parts": [],
        }
        return_code = self._stream_process(
            request,
            args,
            emit_event,
            should_stop,
            set_child_pid,
            line_handler=lambda line: self._handle_opencode_line(line, state, emit_event, request),
        )
        if return_code != 0:
            raise ExecutorError(f"opencode run failed for role={request.role} exit_code={return_code}")
        payload = self._parse_structured_output_from_text(state.get("latest_text") or "\n".join(state["text_parts"]))
        if not isinstance(payload, dict):
            raise ExecutorError(f"opencode did not produce a valid JSON object for role={request.role}")
        if request.inherit_session and request.resume_session_id.strip():
            current = request.extra_context.get("session_ref")
            if not isinstance(current, dict) or not current.get("session_id"):
                request.extra_context["session_ref"] = {"session_id": request.resume_session_id.strip()}
        request.output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return payload

    def _execute_custom(
        self,
        request: RoleRequest,
        emit_event: Callable[[str, dict], None],
        should_stop: Callable[[], bool],
        set_child_pid: Callable[[int | None], None],
    ) -> dict:
        if request.executor_mode != "command":
            raise ExecutorError("custom executor only supports command mode")
        schema_path = request.run_dir / f"{request.role}_schema.json"
        schema_path.write_text(json.dumps(request.output_schema, ensure_ascii=False, indent=2), encoding="utf-8")
        args = build_custom_exec_args(request, schema_path)
        return_code = self._stream_process(
            request,
            args,
            emit_event,
            should_stop,
            set_child_pid,
            line_handler=lambda line: emit_event("codex_event", self._decode_json_line(line)),
        )
        if return_code != 0:
            raise ExecutorError(f"custom exec failed for role={request.role} exit_code={return_code}")
        if not request.output_path.exists():
            raise ExecutorError(f"custom exec did not produce an output file for role={request.role}")
        try:
            payload = json.loads(request.output_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ExecutorError(f"role={request.role} produced invalid JSON output") from exc
        if not isinstance(payload, dict):
            raise ExecutorError(f"custom exec did not produce a JSON object for role={request.role}")
        if request.inherit_session:
            self._capture_session_ref(request, payload)
            if request.resume_session_id.strip():
                current = request.extra_context.get("session_ref")
                if not isinstance(current, dict) or not current.get("session_id"):
                    request.extra_context["session_ref"] = {"session_id": request.resume_session_id.strip()}
        return payload

    def _stream_process(
        self,
        request: RoleRequest,
        args: list[str],
        emit_event: Callable[[str, dict], None],
        should_stop: Callable[[], bool],
        set_child_pid: Callable[[int | None], None],
        *,
        line_handler: Callable[[str], None],
    ) -> int:
        request.extra_context["_executor_started_at"] = time.time()
        process = subprocess.Popen(
            args,
            cwd=str(request.workdir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        set_child_pid(process.pid)
        emit_event("codex_event", {"type": "command", "message": shlex.join(args)})
        output_queue: queue.Queue[str | None] = queue.Queue()

        def pump_stdout() -> None:
            assert process.stdout is not None
            try:
                for raw_line in process.stdout:
                    output_queue.put(raw_line)
            finally:
                output_queue.put(None)

        reader = threading.Thread(target=pump_stdout, daemon=True, name=f"{request.role}-stdout")
        reader.start()
        idle_timeout_seconds = request.idle_timeout_seconds or 0.0
        last_output_at = time.monotonic()
        stream_closed = False
        try:
            while True:
                if should_stop():
                    self._terminate_process(process)
                    raise ExecutionStopped(f"run {request.run_id} stopped while {request.role} was running")
                try:
                    raw_line = output_queue.get(timeout=0.2)
                except queue.Empty:
                    raw_line = None
                else:
                    if raw_line is None:
                        stream_closed = True
                    else:
                        last_output_at = time.monotonic()
                        line = raw_line.strip()
                        if line:
                            line_handler(line)

                if idle_timeout_seconds and process.poll() is None:
                    silence_duration = time.monotonic() - last_output_at
                    if silence_duration >= idle_timeout_seconds:
                        self._terminate_process(process)
                        timeout_text = f"{idle_timeout_seconds:g}s"
                        raise ExecutorError(
                            f"role={request.role} produced no output for {timeout_text}; treating the role as stalled"
                        )

                if stream_closed and process.poll() is not None:
                    break
            return process.wait()
        finally:
            set_child_pid(None)
            reader.join(timeout=0.2)

    def _handle_codex_line(
        self,
        line: str,
        request: RoleRequest,
        emit_event: Callable[[str, dict], None],
    ) -> None:
        record = self._decode_json_line(line)
        self._capture_session_ref(request, record)
        emit_event("codex_event", record)

    @staticmethod
    def _decode_json_line(line: str) -> dict:
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            return {"type": "stdout", "message": line}

    def _handle_claude_line(
        self,
        line: str,
        state: dict,
        emit_event: Callable[[str, dict], None],
        request: RoleRequest | None = None,
    ) -> None:
        record = self._decode_json_line(line)
        if request is not None:
            self._capture_session_ref(request, record)
        if record.get("type") == "stdout":
            emit_event("codex_event", record)
            return

        if record.get("type") == "system":
            model = record.get("model") or ""
            cli_version = record.get("claude_code_version") or ""
            summary = f"Claude Code ready"
            if model:
                summary += f" · model={model}"
            if cli_version:
                summary += f" · cli={cli_version}"
            emit_event("codex_event", {"type": "stdout", "message": summary})
            return

        if record.get("type") == "assistant":
            for content in record.get("message", {}).get("content", []) or []:
                if content.get("type") == "tool_use" and content.get("name") == "StructuredOutput":
                    payload = content.get("input")
                    if isinstance(payload, dict):
                        state["structured_output"] = payload
                elif content.get("type") == "tool_use":
                    summary = self._summarize_claude_tool_use(content.get("name"), content.get("input"))
                    if summary:
                        emit_event("codex_event", {"type": "stdout", "message": summary})
                elif content.get("type") == "text" and content.get("text"):
                    emit_event("codex_event", {"type": "stdout", "message": content["text"]})
            return

        if record.get("type") == "user":
            summary = self._summarize_claude_tool_result(record)
            if summary:
                emit_event("codex_event", {"type": "stdout", "message": summary})
            return

        if record.get("type") == "result":
            structured = record.get("structured_output")
            if isinstance(structured, dict):
                state["structured_output"] = structured
            result_text = str(record.get("result", "")).strip()
            if result_text:
                emit_event("codex_event", {"type": "stdout", "message": result_text})
            return

        if record.get("type") != "stream_event":
            return

        event = record.get("event") or {}
        event_type = event.get("type")
        if event_type == "content_block_start":
            content_block = event.get("content_block") or {}
            index = event.get("index")
            if index is not None:
                state["blocks"][index] = {
                    "kind": content_block.get("type") or "",
                    "name": content_block.get("name") or "",
                    "buffer": "",
                }
            return
        if event_type == "content_block_delta":
            delta = event.get("delta") or {}
            index = event.get("index")
            block = state["blocks"].setdefault(index, {"kind": "", "name": "", "buffer": ""})
            if delta.get("type") == "thinking_delta":
                block["buffer"] += str(delta.get("thinking", ""))
            elif delta.get("type") == "text_delta":
                block["buffer"] += str(delta.get("text", ""))
            elif delta.get("type") == "input_json_delta" and block.get("name") == "StructuredOutput":
                block["buffer"] += str(delta.get("partial_json", ""))
            return
        if event_type == "content_block_stop":
            index = event.get("index")
            block = state["blocks"].pop(index, None)
            if not block:
                return
            text = str(block.get("buffer", "")).strip()
            if block.get("name") == "StructuredOutput" and text:
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    payload = None
                if isinstance(payload, dict):
                    state["structured_output"] = payload
            elif block.get("kind") in {"thinking", "text"} and text:
                emit_event("codex_event", {"type": "stdout", "message": text})

    @staticmethod
    def _summarize_claude_tool_use(name: object, raw_input: object) -> str:
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

    @staticmethod
    def _summarize_claude_tool_result(record: dict) -> str:
        tool_result = record.get("tool_use_result")
        if isinstance(tool_result, dict):
            stdout = str(tool_result.get("stdout", "")).strip()
            stderr = str(tool_result.get("stderr", "")).strip()
            if stdout:
                return f"Tool result · {RealCodexExecutor._truncate_claude_console_preview(stdout)}"
            if stderr:
                preview = RealCodexExecutor._truncate_claude_console_preview(stderr)
                return f"Tool result · stderr={preview}"
            if tool_result.get("interrupted"):
                return "Tool result · interrupted"
        for content in record.get("message", {}).get("content", []) or []:
            if content.get("type") != "tool_result":
                continue
            text = str(content.get("content", "")).strip()
            if text:
                preview = RealCodexExecutor._truncate_claude_console_preview(text)
                return f"Tool result · {preview}"
        return ""

    @staticmethod
    def _truncate_claude_console_preview(text: str, *, max_chars: int = 1200, max_lines: int = 24) -> str:
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

    def _handle_opencode_line(
        self,
        line: str,
        state: dict,
        emit_event: Callable[[str, dict], None],
        request: RoleRequest | None = None,
    ) -> None:
        record = self._decode_json_line(line)
        if request is not None:
            self._capture_session_ref(request, record)
        if record.get("type") == "stdout":
            emit_event("codex_event", record)
            return
        event_type = record.get("type")
        if event_type == "step_start":
            emit_event("codex_event", {"type": "stdout", "message": "OpenCode step started"})
            return
        if event_type == "text":
            text = str(((record.get("part") or {}).get("text") or "")).strip()
            if text:
                state["latest_text"] = text
                state["text_parts"].append(text)
                emit_event("codex_event", {"type": "stdout", "message": text})
            return
        if event_type == "step_finish":
            tokens = ((record.get("part") or {}).get("tokens") or {})
            total = tokens.get("total")
            if total is not None:
                emit_event("codex_event", {"type": "stdout", "message": f"OpenCode step finished · tokens={total}"})

    @staticmethod
    def _parse_structured_output_from_text(text: str) -> dict | None:
        candidate = str(text or "").strip()
        if not candidate:
            return None
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            start = candidate.find("{")
            end = candidate.rfind("}")
            if start == -1 or end == -1 or end <= start:
                return None
            try:
                parsed = json.loads(candidate[start : end + 1])
            except json.JSONDecodeError:
                return None
        return parsed if isinstance(parsed, dict) else None

    @staticmethod
    def _terminate_process(process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        process.send_signal(signal.SIGTERM)
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)


class FakeCodexExecutor(CodexExecutor):
    def __init__(self, scenario: str = "success", role_delay: float = 0.0) -> None:
        self.scenario = scenario
        self.role_delay = role_delay

    def execute(
        self,
        request: RoleRequest,
        emit_event: Callable[[str, dict], None],
        should_stop: Callable[[], bool],
        set_child_pid: Callable[[int | None], None],
    ) -> dict:
        set_child_pid(None)
        try:
            emit_event("codex_event", {"type": "fake_start", "role": request.role, "scenario": self.scenario})
            if self.role_delay:
                deadline = time.time() + self.role_delay
                while time.time() < deadline:
                    if should_stop():
                        raise ExecutionStopped(f"run {request.run_id} stopped while {request.role} was running")
                    time.sleep(0.05)
            payload = self._build_payload(request)
            if request.inherit_session:
                current = request.extra_context.get("session_ref")
                session_ref = dict(current) if isinstance(current, dict) else {}
                session_ref.setdefault("session_id", request.resume_session_id or f"fake-{request.run_id}-{request.role}")
                request.extra_context["session_ref"] = session_ref
            request.output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            emit_event("codex_event", {"type": "fake_complete", "role": request.role, "at": utc_now()})
            return payload
        finally:
            set_child_pid(None)

    def _build_payload(self, request: RoleRequest) -> dict:
        iter_id = int(request.extra_context.get("iter_id", 0))
        compiled_spec = request.extra_context.get("compiled_spec", {})
        checks = compiled_spec.get("checks", [])
        check_count = max(len(checks), 1)
        archetype = str(request.role_archetype or request.extra_context.get("archetype") or request.role).strip().lower()

        if self.scenario == "alignment_resume_failure" and request.role == "alignment" and request.resume_session_id:
            raise ExecutorError("simulated native resume failure")

        if request.role == "alignment" or archetype == "alignment":
            return self._build_alignment_payload(request)

        if self.scenario == "role_failure" and archetype in {"tester", "inspector"}:
            raise ExecutorError("simulated inspector failure")

        if (
            (self.scenario == "destructive_generator" and archetype in {"generator", "builder"})
            or (self.scenario == "destructive_tester" and archetype in {"tester", "inspector"})
        ):
            for child in request.workdir.iterdir():
                if child.name == APP_STATE_DIRNAME:
                    continue
                if child.is_dir():
                    for nested in sorted(child.rglob("*"), key=lambda path: len(path.parts), reverse=True):
                        if nested.is_file():
                            nested.unlink()
                        elif nested.is_dir():
                            nested.rmdir()
                    child.rmdir()
                else:
                    child.unlink()

        if archetype in {"generator", "builder"}:
            return {
                "attempted": f"Iter {iter_id}: refine workdir toward compiled goal",
                "abandoned": "Avoided multi-module changes in the same iteration.",
                "assumption": "The highest-impact gain is still in the primary path.",
                "summary": "Applied a focused change strategy.",
                "changed_files": [],
            }

        if request.role == "check_planner":
            goal = (compiled_spec.get("goal") or "the prototype").strip()
            return {
                "checks": [
                    {
                        "title": "Goal alignment",
                        "details": (
                            f"When: someone reviews the current prototype against the goal.\n"
                            f"Expect: the main flow clearly moves toward {goal}.\n"
                            "Fail if: the prototype feels unrelated, confusing, or incomplete in its primary direction."
                        ),
                        "when": "Someone evaluates the prototype as-is.",
                        "expect": f"The main flow visibly supports {goal}.",
                        "fail_if": "The current direction is confusing or disconnected from the goal.",
                    },
                    {
                        "title": "Primary interaction holds together",
                        "details": (
                            "When: a user follows the most obvious interaction path.\n"
                            "Expect: the path remains understandable from start to finish.\n"
                            "Fail if: the experience breaks, stalls, or loses its state."
                        ),
                        "when": "A user follows the most obvious path.",
                        "expect": "The path stays understandable and coherent.",
                        "fail_if": "The experience breaks, stalls, or loses its state.",
                    },
                    {
                        "title": "Prototype safety",
                        "details": (
                            "When: the user hits an incomplete or awkward edge in the prototype.\n"
                            "Expect: the interface still communicates what is happening.\n"
                            "Fail if: the prototype crashes, misleads the user, or becomes unusable."
                        ),
                        "when": "An incomplete or awkward edge appears.",
                        "expect": "The interface still communicates clearly.",
                        "fail_if": "The prototype crashes, misleads the user, or becomes unusable.",
                    },
                ],
                "generation_notes": "Generated a compact exploratory check set because the spec did not provide explicit checks.",
            }

        if archetype in {"tester", "inspector"}:
            passed_checks = min(check_count, 1 + iter_id)
            total_checks = check_count
            results = []
            for index, check in enumerate(checks, start=1):
                status = "passed" if index <= passed_checks else "failed"
                results.append(
                    {
                        "id": check["id"],
                        "title": check["title"],
                        "status": status,
                        "notes": check.get("expect") or check.get("details", ""),
                    }
                )
            return {
                "execution_summary": {
                    "total_checks": total_checks,
                    "passed": passed_checks,
                    "failed": max(total_checks - passed_checks, 0),
                    "errored": 0,
                    "total_duration_ms": 500 + iter_id * 25,
                },
                "check_results": results,
                "dynamic_checks": [],
                "tester_observations": "Fake executor evaluated the compiled Markdown checks.",
            }

        if archetype in {"verifier", "gatekeeper"}:
            tester_output = request.extra_context.get("inspector_output") or request.extra_context.get("tester_output") or {
                "execution_summary": {"total_checks": check_count, "passed": 0},
                "check_results": [],
            }
            total_checks = max(tester_output["execution_summary"]["total_checks"], 1)
            passed_checks = tester_output["execution_summary"]["passed"]
            if self.scenario == "plateau":
                composite = 0.62 if iter_id < 2 else 0.621
            else:
                composite = round(min(0.45 + iter_id * 0.25, 1.0), 3)
            failed_check_ids = [
                check["id"] for check in tester_output["check_results"] if check.get("status") != "passed"
            ]
            check_pass_rate = round(passed_checks / total_checks, 3)
            passed = composite >= 0.9 and not failed_check_ids
            return {
                "passed": passed,
                "decision_summary": "All checks passed." if passed else "The run still has failing evidence.",
                "composite_score": composite,
                "metrics": [
                    {
                        "name": "check_pass_rate",
                        "value": check_pass_rate,
                        "threshold": 0.9,
                        "passed": check_pass_rate >= 0.9,
                    },
                    {
                        "name": "quality_score",
                        "value": composite,
                        "threshold": 0.9,
                        "passed": composite >= 0.9,
                    },
                ],
                "metric_scores": {
                    "check_pass_rate": {
                        "value": check_pass_rate,
                        "threshold": 0.9,
                        "passed": check_pass_rate >= 0.9,
                    },
                    "quality_score": {
                        "value": composite,
                        "threshold": 0.9,
                        "passed": composite >= 0.9,
                    },
                },
                "blocking_issues": [],
                "hard_constraint_violations": [],
                "failed_check_ids": failed_check_ids,
                "priority_failures": [],
                "feedback_to_builder": "Improve the most visible failing checks without widening scope.",
                "feedback_to_generator": "Improve the most visible failing checks without widening scope.",
            }

        if archetype in {"challenger", "guide"}:
            return {
                "created_at_iter": iter_id,
                "mode": request.extra_context.get("stagnation_mode", "plateau"),
                "consumed": False,
                "analysis": {
                    "stagnation_pattern": "fake executor detected stalled gains",
                    "recommended_shift": "Try a smaller, more visible change in the main path.",
                    "risk_note": "Changing direction too broadly may hide whether the plateau was real.",
                },
                "seed_question": "What is the smallest testable change that breaks the plateau?",
                "meta_note": "This is a suggestion, not a command.",
            }

        if archetype == "custom":
            return {
                "status": "advisory",
                "summary": "Collected read-only evidence and prepared a scoped handoff.",
                "blocking_items": [
                    "A restricted role can guide the next move but cannot close the loop alone.",
                ],
                "recommended_next_action": "Use the strongest evidence path for the next change.",
                "observations": [
                    "The custom role stayed inside the current workspace evidence.",
                    "No write action was claimed from this restricted role.",
                ],
                "recommendations": [
                    "Use the strongest evidence path for the next change.",
                ],
                "risks": [
                    "A restricted role can guide the next move but cannot close the loop alone.",
                ],
                "handoff_note": "Pass these observations to a Builder or Inspector step.",
            }

        raise ExecutorError(f"unsupported fake role: {request.role}")

    def _build_alignment_payload(self, request: RoleRequest) -> dict:
        if self.scenario == "alignment_failure":
            raise ExecutorError("simulated alignment failure")
        if self.scenario == "alignment_question":
            return self._alignment_response(
                status="question",
                assistant_message="这次你更怕做慢，还是更怕做糙？",
                needs_user_input=True,
                bundle_yaml="",
                phase="clarifying",
            )
        mode = str(request.extra_context.get("alignment_mode", "normal"))
        alignment_stage = str(request.extra_context.get("alignment_stage", "clarifying") or "clarifying")
        if self.scenario == "alignment_premature_bundle":
            workdir = str(request.extra_context.get("target_workdir") or request.workdir)
            return self._alignment_response(
                status="bundle",
                assistant_message="我跳过对齐直接生成 bundle。",
                needs_user_input=False,
                bundle_yaml=self._alignment_bundle_yaml(workdir),
                phase="clarifying",
                ready=False,
            )
        if mode != "repair" and alignment_stage not in {"confirmed", "compiling"}:
            return self._alignment_agreement_response()
        if self.scenario == "alignment_invalid":
            return self._alignment_response(
                status="bundle",
                assistant_message="我先给出一个故意不完整的 bundle。",
                needs_user_input=False,
                bundle_yaml="version: 1\nmetadata:\n  name: Broken Alignment Bundle\n",
                phase="bundle",
                ready=True,
            )
        if self.scenario == "alignment_invalid_then_valid" and mode != "repair":
            return self._alignment_response(
                status="bundle",
                assistant_message="我先给出一个需要修复的 bundle。",
                needs_user_input=False,
                bundle_yaml="version: 1\nmetadata:\n  name: Broken Alignment Bundle\n",
                phase="bundle",
                ready=True,
            )
        if self.scenario == "alignment_semantic_invalid_then_valid" and mode != "repair":
            workdir = str(request.extra_context.get("target_workdir") or request.workdir)
            return self._alignment_response(
                status="bundle",
                assistant_message="我先给出一个语义不完整的 bundle。",
                needs_user_input=False,
                bundle_yaml=self._alignment_bundle_yaml_without_semantics(workdir),
                phase="bundle",
                ready=True,
            )
        workdir = str(request.extra_context.get("target_workdir") or request.workdir)
        return self._alignment_response(
            status="bundle",
            assistant_message="已整理成一个可导入的 Loopora bundle。",
            needs_user_input=False,
            bundle_yaml=self._alignment_bundle_yaml(workdir),
            phase="bundle",
            ready=True,
        )

    @staticmethod
    def _alignment_response(
        *,
        status: str,
        assistant_message: str,
        needs_user_input: bool,
        bundle_yaml: str,
        phase: str,
        ready: bool = False,
    ) -> dict:
        checklist = {
            "task_scope": ready,
            "success_surface": ready,
            "fake_done_risks": ready,
            "evidence_preferences": ready,
            "role_posture": ready,
            "workflow_shape": ready,
            "explicit_confirmation": ready,
        }
        return {
            "status": status,
            "assistant_message": assistant_message,
            "needs_user_input": needs_user_input,
            "bundle_yaml": bundle_yaml,
            "session_ref": {
                "session_id": "",
                "thread_id": "",
                "conversation_id": "",
                "provider": "fake",
                "raw_json": "",
            },
            "alignment_phase": phase,
            "agreement_summary": "Use a focused Builder, evidence Inspector, and strict GateKeeper." if ready else "",
            "readiness_checklist": checklist,
        }

    @staticmethod
    def _alignment_agreement_response() -> dict:
        return {
            "status": "question",
            "assistant_message": "我会按这个工作协议生成：先做聚焦实现，再收集可复现证据，最后由 GateKeeper 保守裁决。请回复“确认”后我再生成循环方案。",
            "needs_user_input": True,
            "bundle_yaml": "",
            "session_ref": {
                "session_id": "",
                "thread_id": "",
                "conversation_id": "",
                "provider": "fake",
                "raw_json": "",
            },
            "alignment_phase": "agreement",
            "agreement_summary": "Use a focused Builder, evidence Inspector, and strict GateKeeper.",
            "readiness_checklist": {
                "task_scope": True,
                "success_surface": True,
                "fake_done_risks": True,
                "evidence_preferences": True,
                "role_posture": True,
                "workflow_shape": True,
                "explicit_confirmation": False,
            },
        }

    @staticmethod
    def _alignment_bundle_yaml(workdir: str) -> str:
        return f"""version: 1
metadata:
  name: "Aligned Starter Bundle"
  description: "Bundle generated by the Web alignment flow."
  revision: 1
collaboration_summary: |
  Start with focused implementation, collect direct evidence, then let a GateKeeper close only when the task is truly done.
loop:
  name: "Aligned Starter Bundle"
  workdir: "{workdir}"
  completion_mode: "gatekeeper"
  executor_kind: "codex"
  executor_mode: "preset"
  command_cli: ""
  command_args_text: ""
  model: "gpt-5.4"
  reasoning_effort: "medium"
  iteration_interval_seconds: 0
  max_iters: 4
  max_role_retries: 1
  delta_threshold: 0.005
  trigger_window: 2
  regression_window: 2
spec:
  markdown: |
    # Task

    Ship the requested behavior with focused changes.

    # Done When

    - The primary user flow works end to end.
    - The implementation is covered by project-owned evidence.

    # Guardrails

    - Keep changes scoped to the requested behavior.

    # Success Surface

    - The result is understandable, maintainable, and easy to extend after the first pass.

    # Fake Done

    - Do not pass with only a happy-path claim and no reproducible evidence.

    # Evidence Preferences

    - Prefer project-owned checks, direct run output, and concrete artifacts before screenshots or claims.

    # Role Notes

    ## Builder Notes

    Prefer a small maintainable patch over broad rewrites.

    ## Inspector Notes

    Collect reproducible evidence and call out missing proof plainly.

    ## GateKeeper Notes

    Fail closed when Done When, fake-done risks, and evidence preferences are not all satisfied.
role_definitions:
  - key: "builder"
    name: "Focused Builder"
    description: "Implements the smallest maintainable change."
    archetype: "builder"
    prompt_ref: "builder.md"
    prompt_markdown: |
      ---
      version: 1
      archetype: builder
      ---

      Build carefully and keep the repo coherent.
    posture_notes: |
      Keep implementation narrow and leave the workspace easier to verify.
    executor_kind: "codex"
    executor_mode: "preset"
    command_cli: ""
    command_args_text: ""
    model: ""
    reasoning_effort: ""
  - key: "inspector"
    name: "Evidence Inspector"
    description: "Collects reproducible evidence before sign-off."
    archetype: "inspector"
    prompt_ref: "inspector.md"
    prompt_markdown: |
      ---
      version: 1
      archetype: inspector
      ---

      Inspect from direct evidence and report gaps plainly.
    posture_notes: |
      Prefer project-owned commands and concrete artifacts.
    executor_kind: "codex"
    executor_mode: "preset"
    command_cli: ""
    command_args_text: ""
    model: ""
    reasoning_effort: ""
  - key: "gatekeeper"
    name: "Conservative GateKeeper"
    description: "Fails closed when evidence is weak."
    archetype: "gatekeeper"
    prompt_ref: "gatekeeper.md"
    prompt_markdown: |
      ---
      version: 1
      archetype: gatekeeper
      ---

      Decide from direct evidence and do not accept vague completion claims.
    posture_notes: |
      Close only when the task and verification evidence agree.
    executor_kind: "codex"
    executor_mode: "preset"
    command_cli: ""
    command_args_text: ""
    model: ""
    reasoning_effort: ""
workflow:
  version: 1
  preset: "build_first"
  collaboration_intent: "Build one focused slice, inspect it, then fail closed unless evidence is strong."
  roles:
    - id: "builder"
      role_definition_key: "builder"
    - id: "inspector"
      role_definition_key: "inspector"
    - id: "gatekeeper"
      role_definition_key: "gatekeeper"
  steps:
    - id: "builder_step"
      role_id: "builder"
    - id: "inspector_step"
      role_id: "inspector"
    - id: "gatekeeper_step"
      role_id: "gatekeeper"
      on_pass: "finish_run"
"""

    @staticmethod
    def _alignment_bundle_yaml_without_semantics(workdir: str) -> str:
        yaml_text = FakeCodexExecutor._alignment_bundle_yaml(workdir)
        yaml_text = re.sub(
            r"\n    # Success Surface\n\n    - .+?\n(?=\n    # Fake Done)",
            "\n",
            yaml_text,
            flags=re.DOTALL,
        )
        yaml_text = re.sub(
            r"\n    # Evidence Preferences\n\n    - .+?\n(?=\n    # Role Notes)",
            "\n",
            yaml_text,
            flags=re.DOTALL,
        )
        return yaml_text


def executor_from_environment() -> CodexExecutor:
    scenario = os.environ.get(FAKE_EXECUTOR_ENV, "").strip()
    if scenario:
        delay = float(os.environ.get(FAKE_DELAY_ENV, "0").strip())
        return FakeCodexExecutor(scenario=scenario, role_delay=delay)
    return RealCodexExecutor()
