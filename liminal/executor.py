from __future__ import annotations

import json
import os
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

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
    sandbox: str = "workspace-write"
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
        ]
        prompt = request.prompt
        if request.reasoning_effort:
            prompt += f"\n\nReasoning effort preference: {request.reasoning_effort}."
        args.append(prompt)

        process = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        set_child_pid(process.pid)
        try:
            assert process.stdout is not None
            for raw_line in process.stdout:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    payload = {"type": "stdout", "message": line}
                emit_event("codex_event", payload)
                if should_stop():
                    self._terminate_process(process)
                    raise ExecutionStopped(f"run {request.run_id} stopped while {request.role} was running")

            return_code = process.wait()
        finally:
            set_child_pid(None)

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
        case_count = max(len(compiled_spec.get("cases", [])), 1)

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

        if request.role == "tester":
            passed_cases = min(case_count, 1 + iter_id)
            total_cases = case_count
            results = []
            for index, case in enumerate(compiled_spec.get("cases", []), start=1):
                status = "passed" if index <= passed_cases else "failed"
                results.append(
                    {
                        "id": case["id"],
                        "title": case["title"],
                        "status": status,
                        "notes": case["expected_result"] or case["description"],
                    }
                )
            return {
                "execution_summary": {
                    "total_cases": total_cases,
                    "passed": passed_cases,
                    "failed": max(total_cases - passed_cases, 0),
                    "errored": 0,
                    "total_duration_ms": 500 + iter_id * 25,
                },
                "case_results": results,
                "dynamic_cases": [],
                "tester_observations": "Fake executor evaluated the compiled Markdown cases.",
            }

        if request.role == "verifier":
            tester_output = request.extra_context["tester_output"]
            total_cases = max(tester_output["execution_summary"]["total_cases"], 1)
            passed_cases = tester_output["execution_summary"]["passed"]
            if self.scenario == "plateau":
                composite = 0.62 if iter_id < 2 else 0.621
            else:
                composite = round(min(0.45 + iter_id * 0.25, 1.0), 3)
            failed_case_ids = [
                case["id"] for case in tester_output["case_results"] if case.get("status") != "passed"
            ]
            edge_case_coverage = round(passed_cases / total_cases, 3)
            passed = composite >= 0.9 and not failed_case_ids
            return {
                "passed": passed,
                "composite_score": composite,
                "metric_scores": {
                    "case_pass_rate": {
                        "value": edge_case_coverage,
                        "threshold": 0.9,
                        "passed": edge_case_coverage >= 0.9,
                    },
                    "quality_score": {
                        "value": composite,
                        "threshold": 0.9,
                        "passed": composite >= 0.9,
                    },
                },
                "hard_constraint_violations": [],
                "failed_case_ids": failed_case_ids,
                "priority_failures": [],
                "feedback_to_generator": "Improve the most visible failing cases without widening scope.",
                "verifier_confidence": "high",
            }

        if request.role == "challenger":
            return {
                "created_at_iter": iter_id,
                "mode": request.extra_context.get("stagnation_mode", "plateau"),
                "consumed": False,
                "analysis": {"stagnation_pattern": "fake executor detected stalled gains"},
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
