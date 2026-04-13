from __future__ import annotations

import json
import os
import queue
import shlex
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from liminal.providers import (
    coerce_reasoning_setting,
    normalize_executor_kind,
    normalize_executor_mode,
    normalize_reasoning_setting,
)
from liminal.utils import utc_now


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
    sandbox: str = "workspace-write"
    idle_timeout_seconds: float | None = None
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
    args.extend(["-c", f'model_reasoning_effort="{reasoning_effort}"', request.prompt])
    return args


def build_claude_exec_args(request: RoleRequest) -> list[str]:
    args = [
        "claude",
        "-p",
        "--output-format",
        "stream-json",
        "--include-partial-messages",
        "--no-session-persistence",
        "--permission-mode",
        "bypassPermissions",
        "--json-schema",
        json.dumps(request.output_schema, ensure_ascii=False),
    ]
    if request.model.strip():
        args.extend(["--model", request.model.strip()])
    reasoning_effort = coerce_reasoning_effort(request.reasoning_effort, request.executor_kind)
    if reasoning_effort:
        args.extend(["--effort", reasoning_effort])
    args.append(request.prompt)
    return args


def build_opencode_exec_args(request: RoleRequest) -> list[str]:
    args = [
        "opencode",
        "run",
        "--format",
        "json",
        "--dir",
        str(request.workdir),
        "--dangerously-skip-permissions",
    ]
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


def validate_command_args_text(command_args_text: str | None, *, executor_kind: str) -> list[str]:
    args = parse_command_args_text(command_args_text)
    if not args:
        raise ValueError("custom command arguments are required in command mode")
    joined = "\n".join(args)
    required_placeholders = {
        "codex": ("{prompt}", "{output_path}"),
        "claude": ("{prompt}",),
        "opencode": ("{prompt}",),
    }[normalize_executor_kind(executor_kind)]
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
    replacements = {
        "{workdir}": str(request.workdir),
        "{schema_path}": str(schema_path),
        "{output_path}": str(request.output_path),
        "{prompt}": request.prompt,
        "{sandbox}": request.sandbox,
        "{json_schema}": json.dumps(request.output_schema, ensure_ascii=False),
        "{model}": request.model,
        "{reasoning_effort}": request.reasoning_effort,
    }
    resolved_args = []
    for template_arg in template_args:
        value = template_arg
        for placeholder, replacement in replacements.items():
            value = value.replace(placeholder, replacement)
        resolved_args.append(value)
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
        raise ExecutorError(f"unsupported executor kind: {executor_kind}")

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
        return_code = self._stream_process(
            request,
            args,
            emit_event,
            should_stop,
            set_child_pid,
            line_handler=lambda line: emit_event("codex_event", self._decode_json_line(line)),
        )

        if return_code != 0:
            raise ExecutorError(f"codex exec failed for role={request.role} exit_code={return_code}")

        if not request.output_path.exists():
            raise ExecutorError(f"codex exec did not produce an output file for role={request.role}")

        try:
            return json.loads(request.output_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
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
            line_handler=lambda line: self._handle_claude_line(line, state, emit_event),
        )
        if return_code != 0:
            raise ExecutorError(f"claude print failed for role={request.role} exit_code={return_code}")
        payload = state.get("structured_output")
        if not isinstance(payload, dict):
            raise ExecutorError(f"claude did not produce structured output for role={request.role}")
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
            line_handler=lambda line: self._handle_opencode_line(line, state, emit_event),
        )
        if return_code != 0:
            raise ExecutorError(f"opencode run failed for role={request.role} exit_code={return_code}")
        payload = self._parse_structured_output_from_text(state.get("latest_text") or "\n".join(state["text_parts"]))
        if not isinstance(payload, dict):
            raise ExecutorError(f"opencode did not produce a valid JSON object for role={request.role}")
        request.output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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
    ) -> None:
        record = self._decode_json_line(line)
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
                elif content.get("type") == "text" and content.get("text"):
                    emit_event("codex_event", {"type": "stdout", "message": content["text"]})
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

    def _handle_opencode_line(
        self,
        line: str,
        state: dict,
        emit_event: Callable[[str, dict], None],
    ) -> None:
        record = self._decode_json_line(line)
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

        if self.scenario == "role_failure" and request.role == "tester":
            raise ExecutorError("simulated tester failure")

        if request.role == "generator":
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

        if request.role == "tester":
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

        if request.role == "verifier":
            tester_output = request.extra_context["tester_output"]
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
                "composite_score": composite,
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
                "hard_constraint_violations": [],
                "failed_check_ids": failed_check_ids,
                "priority_failures": [],
                "feedback_to_generator": "Improve the most visible failing checks without widening scope.",
                "verifier_confidence": "high",
            }

        if request.role == "challenger":
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

        raise ExecutorError(f"unsupported fake role: {request.role}")


def executor_from_environment() -> CodexExecutor:
    scenario = os.environ.get("LIMINAL_FAKE_EXECUTOR", "").strip()
    if scenario:
        delay = float(os.environ.get("LIMINAL_FAKE_DELAY", "0"))
        return FakeCodexExecutor(scenario=scenario, role_delay=delay)
    return RealCodexExecutor()
