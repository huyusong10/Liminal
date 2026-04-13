from __future__ import annotations

import json
import os
import queue
import signal
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from liminal.utils import utc_now

SUPPORTED_REASONING_EFFORTS = ("low", "medium", "high", "xhigh")
_LEGACY_REASONING_ALIASES = {"minimal": "low"}


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


def normalize_reasoning_effort(value: str | None) -> str:
    normalized = (value or "medium").strip().lower()
    normalized = _LEGACY_REASONING_ALIASES.get(normalized, normalized)
    if normalized not in SUPPORTED_REASONING_EFFORTS:
        supported = ", ".join(SUPPORTED_REASONING_EFFORTS)
        raise ValueError(f"unsupported reasoning effort: {value!r}. Expected one of: {supported}")
    return normalized


def coerce_reasoning_effort(value: str | None) -> str:
    try:
        return normalize_reasoning_effort(value)
    except ValueError:
        return "medium"


class RealCodexExecutor(CodexExecutor):
    def execute(
        self,
        request: RoleRequest,
        emit_event: Callable[[str, dict], None],
        should_stop: Callable[[], bool],
        set_child_pid: Callable[[int | None], None],
    ) -> dict:
        schema_path = request.run_dir / f"{request.role}_schema.json"
        schema_path.write_text(json.dumps(request.output_schema, ensure_ascii=False, indent=2), encoding="utf-8")
        request.output_path.parent.mkdir(parents=True, exist_ok=True)
        reasoning_effort = coerce_reasoning_effort(request.reasoning_effort)

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
            "--model",
            request.model,
            "-c",
            f'model_reasoning_effort="{reasoning_effort}"',
        ]
        args.append(request.prompt)

        process = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        set_child_pid(process.pid)
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
                        if not line:
                            continue
                        try:
                            payload = json.loads(line)
                        except json.JSONDecodeError:
                            payload = {"type": "stdout", "message": line}
                        emit_event("codex_event", payload)

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

            return_code = process.wait()
        finally:
            set_child_pid(None)
            reader.join(timeout=0.2)

        if return_code != 0:
            raise ExecutorError(f"codex exec failed for role={request.role} exit_code={return_code}")

        if not request.output_path.exists():
            raise ExecutorError(f"codex exec did not produce an output file for role={request.role}")

        try:
            return json.loads(request.output_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ExecutorError(f"role={request.role} produced invalid JSON output") from exc

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
