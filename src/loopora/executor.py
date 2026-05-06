from __future__ import annotations

import json
import os
import re
import shlex
import signal
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from collections.abc import Callable

from loopora.branding import (
    FAKE_DELAY_ENV,
    FAKE_EXECUTOR_ENV,
)
from loopora.executor_claude_stream import (
    handle_claude_record,
    summarize_claude_tool_result,
    summarize_claude_tool_use,
    truncate_claude_console_preview,
)
from loopora.executor_fake_payloads import (
    FakePayloadError,
    alignment_agreement_response,
    alignment_bundle_yaml,
    alignment_bundle_yaml_without_semantics,
    alignment_readiness_evidence,
    build_alignment_payload,
    build_fake_payload,
)
from loopora.executor_process_stream import (
    ProcessStreamCallbacks,
    ProcessStreamContext,
    ProcessStreamIdleTimeout,
    ProcessStreamStopped,
    stream_process,
)
from loopora.executor_session_refs import (
    extract_session_ref,
    infer_codex_session_ref_from_rollouts,
    merge_session_ref,
    normalize_session_key,
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


COMMAND_EVENT_PREVIEW_LIMIT = 500
_SENSITIVE_ARG_NAMES = {
    "--api-key",
    "--auth-token",
    "--bearer-token",
    "--password",
    "--secret",
    "--secret-token",
    "--token",
}


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


@dataclass(frozen=True, slots=True)
class ExecutorProcessRequest:
    request: RoleRequest
    args: list[str]
    emit_event: Callable[[str, dict], None]
    should_stop: Callable[[], bool]
    set_child_pid: Callable[[int | None], None]
    line_handler: Callable[[str], None]


def normalize_reasoning_effort(value: str | None, executor_kind: str = "codex") -> str:
    return normalize_reasoning_setting(value, executor_kind=executor_kind)


def coerce_reasoning_effort(value: str | None, executor_kind: str = "codex") -> str:
    return coerce_reasoning_setting(value, executor_kind=executor_kind)


def build_command_event_payload(request: RoleRequest, args: list[str]) -> dict:
    schema_json = json.dumps(request.output_schema, ensure_ascii=False)
    prompt = str(request.prompt or "")
    sanitized_args: list[str] = []
    prompt_omitted = False
    json_schema_omitted = False
    token_omitted = False
    omit_next_value = False

    for raw_arg in args:
        arg = str(raw_arg)
        if omit_next_value:
            sanitized_args.append("<secret omitted>")
            token_omitted = True
            omit_next_value = False
            continue

        flag_name = arg.split("=", 1)[0].strip().lower()
        if flag_name in _SENSITIVE_ARG_NAMES:
            if "=" in arg:
                sanitized_args.append(f"{arg.split('=', 1)[0]}=<secret omitted>")
                token_omitted = True
            else:
                sanitized_args.append(arg)
                omit_next_value = True
            continue

        if prompt and prompt in arg:
            arg = arg.replace(prompt, "<prompt omitted>")
            prompt_omitted = True
        if schema_json and schema_json in arg:
            arg = arg.replace(schema_json, "<json schema omitted>")
            json_schema_omitted = True
        sanitized_args.append(arg)

    if omit_next_value:
        sanitized_args.append("<secret omitted>")
        token_omitted = True

    message = shlex.join(sanitized_args)
    command_truncated = len(message) > COMMAND_EVENT_PREVIEW_LIMIT
    if command_truncated:
        message = message[: COMMAND_EVENT_PREVIEW_LIMIT - 1].rstrip() + "…"

    return {
        "type": "command",
        "message": message,
        "prompt_omitted": prompt_omitted,
        "json_schema_omitted": json_schema_omitted,
        "token_omitted": token_omitted,
        "command_truncated": command_truncated,
        "arg_count": len(args),
    }


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
        return normalize_session_key(value)

    @classmethod
    def _extract_session_ref(cls, payload: object) -> dict[str, str]:
        return extract_session_ref(payload)

    def _capture_session_ref(self, request: RoleRequest, payload: object) -> None:
        if not request.inherit_session:
            return
        ref = self._extract_session_ref(payload)
        if not ref:
            return
        request.extra_context["session_ref"] = merge_session_ref(request.extra_context.get("session_ref"), ref)

    def _infer_codex_session_ref(self, request: RoleRequest) -> None:
        if not request.inherit_session:
            return
        current = request.extra_context.get("session_ref")
        started_at = float(request.extra_context.get("_executor_started_at") or 0.0)
        ref = infer_codex_session_ref_from_rollouts(
            workdir=request.workdir,
            current_ref=current,
            started_at=started_at,
        )
        if ref:
            request.extra_context["session_ref"] = merge_session_ref(current, ref)

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
            ExecutorProcessRequest(
                request=request,
                args=args,
                emit_event=emit_event,
                should_stop=should_stop,
                set_child_pid=set_child_pid,
                line_handler=lambda line: self._handle_codex_line(line, request, emit_event),
            )
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
            ExecutorProcessRequest(
                request=request,
                args=args,
                emit_event=emit_event,
                should_stop=should_stop,
                set_child_pid=set_child_pid,
                line_handler=lambda line: self._handle_claude_line(line, state, emit_event, request),
            )
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
            ExecutorProcessRequest(
                request=request,
                args=args,
                emit_event=emit_event,
                should_stop=should_stop,
                set_child_pid=set_child_pid,
                line_handler=lambda line: self._handle_opencode_line(line, state, emit_event, request),
            )
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
            ExecutorProcessRequest(
                request=request,
                args=args,
                emit_event=emit_event,
                should_stop=should_stop,
                set_child_pid=set_child_pid,
                line_handler=lambda line: emit_event("codex_event", self._decode_json_line(line)),
            )
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

    def _stream_process(self, process_request: ExecutorProcessRequest) -> int:
        request = process_request.request
        request.extra_context["_executor_started_at"] = time.time()
        try:
            return stream_process(
                context=ProcessStreamContext(
                    run_id=request.run_id,
                    role=request.role,
                    workdir=request.workdir,
                    idle_timeout_seconds=request.idle_timeout_seconds,
                ),
                args=process_request.args,
                command_event_payload=build_command_event_payload(request, process_request.args),
                callbacks=ProcessStreamCallbacks(
                    emit_event=process_request.emit_event,
                    should_stop=process_request.should_stop,
                    set_child_pid=process_request.set_child_pid,
                    line_handler=process_request.line_handler,
                    terminate_process=self._terminate_process,
                ),
            )
        except ProcessStreamStopped as exc:
            raise ExecutionStopped(str(exc)) from exc
        except ProcessStreamIdleTimeout as exc:
            raise ExecutorError(str(exc)) from exc

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
        handle_claude_record(record, state, emit_event)

    @staticmethod
    def _summarize_claude_tool_use(name: object, raw_input: object) -> str:
        return summarize_claude_tool_use(name, raw_input)

    @staticmethod
    def _summarize_claude_tool_result(record: dict) -> str:
        return summarize_claude_tool_result(record)

    @staticmethod
    def _truncate_claude_console_preview(text: str, *, max_chars: int = 1200, max_lines: int = 24) -> str:
        return truncate_claude_console_preview(text, max_chars=max_chars, max_lines=max_lines)

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
            text = str((record.get("part") or {}).get("text") or "").strip()
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
        try:
            return build_fake_payload(self.scenario, request)
        except FakePayloadError as exc:
            raise ExecutorError(str(exc)) from exc

    def _build_alignment_payload(self, request: RoleRequest) -> dict:
        try:
            return build_alignment_payload(self.scenario, request)
        except FakePayloadError as exc:
            raise ExecutorError(str(exc)) from exc

    @staticmethod
    def _alignment_agreement_response() -> dict:
        return alignment_agreement_response()

    @staticmethod
    def _alignment_readiness_evidence(*, open_questions: str = "") -> dict:
        return alignment_readiness_evidence(open_questions=open_questions)

    @staticmethod
    def _alignment_bundle_yaml(workdir: str) -> str:
        return alignment_bundle_yaml(workdir)

    @staticmethod
    def _alignment_bundle_yaml_without_semantics(workdir: str) -> str:
        return alignment_bundle_yaml_without_semantics(workdir)


def executor_from_environment() -> CodexExecutor:
    scenario = os.environ.get(FAKE_EXECUTOR_ENV, "").strip()
    if scenario:
        delay = float(os.environ.get(FAKE_DELAY_ENV, "0").strip())
        return FakeCodexExecutor(scenario=scenario, role_delay=delay)
    return RealCodexExecutor()
