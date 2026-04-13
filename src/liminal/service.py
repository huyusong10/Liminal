from __future__ import annotations

import itertools
import json
import logging
import os
import shutil
import threading
import time
from pathlib import Path
from typing import Callable

import markdown as markdown_lib

from liminal.db import LiminalRepository
from liminal.executor import (
    CodexExecutor,
    ExecutionStopped,
    RoleRequest,
    coerce_reasoning_effort,
    executor_from_environment,
    normalize_reasoning_effort,
)
from liminal.recovery import RecoveryResult, RetryConfig, execute_with_recovery
from liminal.settings import AppSettings, app_home, db_path, load_settings
from liminal.specs import SpecError, compile_markdown_spec, read_and_compile
from liminal.stagnation import update_stagnation
from liminal.utils import append_jsonl, make_id, read_json, utc_now, write_json

logger = logging.getLogger(__name__)


class LiminalError(RuntimeError):
    """Domain error surfaced to CLI and API consumers."""


class RoleExecutionError(LiminalError):
    def __init__(self, role: str, result: RecoveryResult) -> None:
        self.role = role
        self.result = result
        super().__init__(f"role={role} failed after {result.attempts} attempts")


class StopRequested(LiminalError):
    """Raised when a user asked to stop a running loop."""


class LiminalService:
    def __init__(
        self,
        repository: LiminalRepository,
        settings: AppSettings,
        executor_factory: Callable[[], CodexExecutor] | None = None,
    ) -> None:
        self.repository = repository
        self.settings = settings
        self.executor_factory = executor_factory or executor_from_environment
        self._threads: dict[str, threading.Thread] = {}

    def create_loop(
        self,
        *,
        name: str,
        spec_path: Path,
        workdir: Path,
        model: str,
        reasoning_effort: str,
        max_iters: int,
        max_role_retries: int,
        delta_threshold: float,
        trigger_window: int,
        regression_window: int,
        role_models: dict | None = None,
    ) -> dict:
        workdir = workdir.expanduser().resolve()
        spec_path = spec_path.expanduser()
        if spec_path.exists():
            spec_path = spec_path.resolve()
        if not workdir.exists() or not workdir.is_dir():
            raise LiminalError(f"workdir does not exist: {workdir}")
        if not spec_path.exists():
            raise LiminalError(f"spec does not exist: {spec_path}")
        if max_iters < 0:
            raise LiminalError("max_iters must be >= 0")
        if max_role_retries < 0:
            raise LiminalError("max_role_retries must be >= 0")
        if trigger_window < 1:
            raise LiminalError("trigger_window must be >= 1")
        if regression_window < 1:
            raise LiminalError("regression_window must be >= 1")

        try:
            reasoning_effort = normalize_reasoning_effort(reasoning_effort)
        except ValueError as exc:
            raise LiminalError(str(exc)) from exc

        spec_markdown, compiled_spec = read_and_compile(spec_path)
        loop_id = make_id("loop")
        loop_dir = self._ensure_loop_dir(workdir, loop_id)
        persisted_spec_path = loop_dir / "spec.md"
        persisted_spec_path.write_text(spec_markdown, encoding="utf-8")
        write_json(loop_dir / "compiled_spec.json", compiled_spec)

        payload = {
            "id": loop_id,
            "name": name,
            "workdir": str(workdir),
            "spec_path": str(spec_path.resolve()),
            "spec_markdown": spec_markdown,
            "compiled_spec": compiled_spec,
            "model": model,
            "reasoning_effort": reasoning_effort,
            "max_iters": max_iters,
            "max_role_retries": max_role_retries,
            "delta_threshold": delta_threshold,
            "trigger_window": trigger_window,
            "regression_window": regression_window,
            "role_models": role_models or {},
        }
        loop = self.repository.create_loop(payload)
        self._write_recent_workdirs()
        return loop

    def start_run(self, loop_id: str) -> dict:
        loop = self.repository.get_loop(loop_id)
        if not loop:
            raise LiminalError(f"unknown loop: {loop_id}")
        if self.repository.has_active_run_for_workdir(loop["workdir"]):
            raise LiminalError(f"another active run is already using {loop['workdir']}")

        run_id = make_id("run")
        run_dir = self._ensure_run_dir(Path(loop["workdir"]), run_id)
        (run_dir / "events.jsonl").touch()
        (run_dir / "iteration_log.jsonl").touch()
        (run_dir / "summary.md").write_text("# Liminal Run Summary\n\nQueued.\n", encoding="utf-8")
        (run_dir / "compiled_spec.json").write_text(
            json.dumps(loop["compiled_spec_json"], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (run_dir / "spec.md").write_text(loop["spec_markdown"], encoding="utf-8")

        run = self.repository.create_run(
            {
                "id": run_id,
                "loop_id": loop_id,
                "workdir": loop["workdir"],
                "spec_path": loop["spec_path"],
                "spec_markdown": loop["spec_markdown"],
                "compiled_spec": loop["compiled_spec_json"],
                "model": loop["model"],
                "reasoning_effort": coerce_reasoning_effort(loop["reasoning_effort"]),
                "max_iters": loop["max_iters"],
                "max_role_retries": loop["max_role_retries"],
                "delta_threshold": loop["delta_threshold"],
                "trigger_window": loop["trigger_window"],
                "regression_window": loop["regression_window"],
                "role_models": loop["role_models_json"],
                "status": "queued",
                "runs_dir": str(run_dir),
                "summary_md": "# Liminal Run Summary\n\nQueued.\n",
            }
        )
        self.repository.append_event(run_id, "run_registered", {"loop_id": loop_id, "status": "queued"})
        return run

    def start_run_async(self, run_id: str) -> None:
        thread = threading.Thread(target=self.execute_run, args=(run_id,), daemon=True, name=f"run-{run_id}")
        self._threads[run_id] = thread
        thread.start()

    def execute_run(self, run_id: str) -> dict:
        run = self.repository.get_run(run_id)
        if not run:
            raise LiminalError(f"unknown run: {run_id}")

        self._wait_for_slot(run_id)
        run = self.repository.get_run(run_id)
        if not run:
            raise LiminalError(f"unknown run after queue wait: {run_id}")
        if run["status"] == "stopped":
            return run

        executor = self.executor_factory()
        compiled_spec = run["compiled_spec_json"]
        run_dir = Path(run["runs_dir"])
        retry_config = RetryConfig(max_retries=run["max_role_retries"])
        stagnation = read_json(run_dir / "stagnation.json")
        metrics_history_path = run_dir / "metrics_history.jsonl"
        metrics_history_path.touch(exist_ok=True)
        last_iter_id = -1
        last_verifier_result: dict | None = None

        self.repository.append_event(run_id, "run_started", {"status": "running"})
        self._write_summary(run_id, "running", "Resolving checks for this run.")

        try:
            compiled_spec = self._resolve_run_checks(run, executor, compiled_spec, run_dir, retry_config)
            self._write_summary(run_id, "running", "Waiting for the first iteration to complete.")
            iteration_source = itertools.count() if run["max_iters"] == 0 else range(run["max_iters"])
            for iter_id in iteration_source:
                last_iter_id = iter_id
                self._ensure_not_stopped(run_id)
                self.repository.update_run(run_id, current_iter=iter_id)
                generator_mode = {"value": "default"}
                tester_mode = {"value": "default"}
                verifier_mode = {"value": "default"}

                generator_result = self._execute_role(
                    run_id,
                    iter_id,
                    "generator",
                    lambda: self._run_generator(
                        executor,
                        run,
                        compiled_spec,
                        run_dir,
                        iter_id,
                        generator_mode["value"],
                    ),
                    retry_config,
                    degrade_once=lambda: self._set_mode(run_id, iter_id, "generator", generator_mode, "conservative_changes"),
                )
                append_jsonl(
                    run_dir / "iteration_log.jsonl",
                    {
                        "iter": iter_id,
                        "timestamp": utc_now(),
                        **generator_result,
                        "mode": generator_mode["value"],
                    },
                )

                tester_result = self._execute_role(
                    run_id,
                    iter_id,
                    "tester",
                    lambda: self._run_tester(
                        executor,
                        run,
                        compiled_spec,
                        run_dir,
                        iter_id,
                        tester_mode["value"],
                    ),
                    retry_config,
                    degrade_once=lambda: self._set_mode(run_id, iter_id, "tester", tester_mode, "skip_dynamic_checks"),
                )
                write_json(run_dir / "tester_output.json", tester_result)

                verifier_result = self._execute_role(
                    run_id,
                    iter_id,
                    "verifier",
                    lambda: self._run_verifier(
                        executor,
                        run,
                        compiled_spec,
                        run_dir,
                        iter_id,
                        tester_result,
                        verifier_mode["value"],
                    ),
                    retry_config,
                    degrade_once=lambda: self._set_mode(
                        run_id,
                        iter_id,
                        "verifier",
                        verifier_mode,
                        "strict_minimal_validation",
                    ),
                )
                write_json(run_dir / "verifier_verdict.json", verifier_result)
                last_verifier_result = verifier_result
                append_jsonl(
                    metrics_history_path,
                    {
                        "iter": iter_id,
                        "timestamp": utc_now(),
                        "composite": verifier_result["composite_score"],
                        "passed": verifier_result["passed"],
                        "metric_scores": verifier_result["metric_scores"],
                    },
                )
                self.repository.update_run(run_id, last_verdict=verifier_result)

                stagnation = update_stagnation(
                    stagnation,
                    verifier_result["composite_score"],
                    iter_id,
                    delta_threshold=run["delta_threshold"],
                    trigger_window=run["trigger_window"],
                    regression_window=run["regression_window"],
                )
                if stagnation["stagnation_mode"] in {"plateau", "regression"}:
                    challenger_result = self._execute_role(
                        run_id,
                        iter_id,
                        "challenger",
                        lambda: self._run_challenger(
                            executor,
                            run,
                            compiled_spec,
                            run_dir,
                            iter_id,
                            stagnation,
                        ),
                        retry_config,
                    )
                    stagnation.setdefault("challenger_triggered_at_iters", []).append(iter_id)
                    write_json(run_dir / "challenger_seed.json", challenger_result)
                    self.repository.append_event(
                        run_id,
                        "challenger_done",
                        {"iter": iter_id, "mode": challenger_result["mode"]},
                        role="challenger",
                    )
                write_json(run_dir / "stagnation.json", stagnation)

                summary = self._build_summary(run, compiled_spec, iter_id, verifier_result, stagnation)
                self._write_summary(run_id, "running", summary)

                if verifier_result["passed"]:
                    finished = self.repository.update_run(
                        run_id,
                        status="succeeded",
                        finished_at=utc_now(),
                        last_verdict=verifier_result,
                        summary_md=summary,
                    )
                    self.repository.append_event(run_id, "run_finished", {"status": "succeeded", "iter": iter_id})
                    return finished

            if run["max_iters"] != 0 and last_verifier_result is not None:
                summary = self._build_summary(
                    run,
                    compiled_spec,
                    last_iter_id,
                    last_verifier_result,
                    stagnation,
                    exhausted=True,
                )
                finished = self.repository.update_run(
                    run_id,
                    status="failed",
                    finished_at=utc_now(),
                    summary_md=summary,
                )
                self.repository.append_event(
                    run_id,
                    "run_finished",
                    {"status": "failed", "reason": "max_iters_exhausted"},
                )
                return finished
            raise LiminalError(f"run {run_id} exited without completing an iteration")
        except (StopRequested, ExecutionStopped):
            summary = "# Liminal Run Summary\n\nStopped by user.\n"
            stopped = self.repository.update_run(
                run_id,
                status="stopped",
                finished_at=utc_now(),
                summary_md=summary,
            )
            self.repository.append_event(run_id, "run_finished", {"status": "stopped"})
            return stopped
        except RoleExecutionError as exc:
            error_text = str(exc.result.error) if exc.result.error else str(exc)
            verdict = {
                "passed": False,
                "composite_score": 0.0,
                "metric_scores": {},
                "hard_constraint_violations": ["role_execution_abort"],
                "failed_check_ids": [],
                "priority_failures": [
                    {
                        "error_code": "ROLE_EXECUTION_ABORT",
                        "role": exc.role,
                        "attempts": exc.result.attempts,
                        "degraded": exc.result.degraded,
                    }
                ],
                "feedback_to_generator": "Execution aborted. Fix the failing role before retrying.",
                "verifier_confidence": "high",
            }
            write_json(run_dir / "verifier_verdict.json", verdict)
            summary = (
                "# Liminal Run Summary\n\n"
                f"Execution failed during `{exc.role}`.\n\n"
                f"Reason: `{error_text}`.\n"
            )
            failed = self.repository.update_run(
                run_id,
                status="failed",
                finished_at=utc_now(),
                error_message=error_text,
                last_verdict=verdict,
                summary_md=summary,
            )
            self.repository.append_event(
                run_id,
                "run_aborted",
                {
                    "role": exc.role,
                    "attempts": exc.result.attempts,
                    "degraded": exc.result.degraded,
                    "error": error_text,
                },
            )
            return failed
        finally:
            self.repository.release_run_slot(run_id)

    def stop_run(self, run_id: str) -> dict:
        run = self.repository.request_stop(run_id)
        if not run:
            raise LiminalError(f"unknown run: {run_id}")
        self.repository.append_event(run_id, "stop_requested", {"status": run["status"]})
        self.repository.send_stop_signal(run_id)
        return run

    def list_loops(self) -> list[dict]:
        return self.repository.list_loops()

    def get_loop(self, loop_id: str) -> dict:
        loop = self.repository.get_loop(loop_id)
        if not loop:
            raise LiminalError(f"unknown loop: {loop_id}")
        loop["runs"] = self.repository.list_runs_for_loop(loop_id)
        return loop

    def get_run(self, run_id: str) -> dict:
        run = self.repository.get_run(run_id)
        if not run:
            raise LiminalError(f"unknown run: {run_id}")
        return run

    def get_status(self, identifier: str) -> tuple[str, dict]:
        found = self.repository.get_loop_or_run(identifier)
        if not found:
            raise LiminalError(f"unknown identifier: {identifier}")
        kind, payload = found
        if kind == "loop":
            payload["runs"] = self.repository.list_runs_for_loop(payload["id"])
        return kind, payload

    def rerun(self, loop_id: str, *, background: bool = False) -> dict:
        run = self.start_run(loop_id)
        if background:
            self.start_run_async(run["id"])
            return run
        return self.execute_run(run["id"])

    def delete_loop(self, loop_id: str) -> dict:
        loop = self.get_loop(loop_id)
        active_runs = [run["id"] for run in loop["runs"] if run["status"] in {"queued", "running"}]
        if active_runs:
            raise LiminalError(f"cannot delete loop with active runs: {', '.join(active_runs)}")

        paths_to_remove = [Path(run["runs_dir"]) for run in loop["runs"]]
        paths_to_remove.append(Path(loop["workdir"]) / ".liminal" / "loops" / loop_id)

        self.repository.delete_loop(loop_id)
        for path in paths_to_remove:
            shutil.rmtree(path, ignore_errors=True)
        self._write_recent_workdirs()
        return {"id": loop_id, "deleted_runs": len(loop["runs"]), "workdir": loop["workdir"]}

    def preview_file(self, run_id: str, root: str, relative_path: str = "") -> dict:
        run = self.get_run(run_id)
        workdir = Path(run["workdir"])
        base = workdir / ".liminal" if root == "liminal" else workdir
        if root == "liminal":
            base.mkdir(parents=True, exist_ok=True)
        resolved = (base / relative_path).resolve()
        if not str(resolved).startswith(str(base.resolve())):
            raise LiminalError("requested path is outside the allowed root")
        if not resolved.exists():
            raise LiminalError(f"path does not exist: {resolved}")

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
        if suffix == ".json" or suffix == ".jsonl":
            text = raw_bytes.decode("utf-8", errors="replace")
            try:
                parsed = [json.loads(line) for line in text.splitlines() if line.strip()] if suffix == ".jsonl" else json.loads(text)
                text = json.dumps(parsed, ensure_ascii=False, indent=2)
            except json.JSONDecodeError:
                pass
        elif self._looks_binary(raw_bytes):
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
            text = raw_bytes.decode("utf-8", errors="replace")
        payload = {
            "kind": "file",
            "base": str(base),
            "path": relative_path,
            "name": resolved.name,
            "content": text,
            "is_binary": False,
            "size_bytes": len(raw_bytes),
        }
        if suffix in {".md", ".markdown"}:
            payload["rendered_html"] = markdown_lib.markdown(text, extensions=["fenced_code"])
        return payload

    def _looks_binary(self, data: bytes) -> bool:
        if not data:
            return False
        sample = data[:4096]
        if b"\x00" in sample:
            return True
        allowed = {9, 10, 13}
        suspicious = sum(1 for byte in sample if byte < 32 and byte not in allowed)
        return suspicious / len(sample) > 0.1

    def stream_events(self, run_id: str, after_id: int = 0, limit: int = 200) -> list[dict]:
        return self.repository.list_events(run_id, after_id=after_id, limit=limit)

    def _wait_for_slot(self, run_id: str) -> None:
        self.repository.update_run(run_id, status="queued", summary_md="# Liminal Run Summary\n\nQueued.\n")
        while True:
            self._ensure_not_stopped(run_id)
            if self.repository.claim_run_slot(run_id, self.settings.max_concurrent_runs):
                self.repository.update_run(run_id, started_at=utc_now(), status="running")
                return
            time.sleep(self.settings.polling_interval_seconds)

    def _resolve_run_checks(
        self,
        run: dict,
        executor: CodexExecutor,
        compiled_spec: dict,
        run_dir: Path,
        retry_config: RetryConfig,
    ) -> dict:
        checks = compiled_spec.get("checks", [])
        if checks:
            self.repository.append_event(
                run["id"],
                "checks_resolved",
                {"source": "specified", "count": len(checks)},
            )
            return compiled_spec

        planner_result = self._execute_role(
            run["id"],
            None,
            "check_planner",
            lambda: self._run_check_planner(executor, run, compiled_spec, run_dir),
            retry_config,
        )
        resolved_checks = self._normalize_generated_checks(planner_result.get("checks", []))
        if not resolved_checks:
            raise LiminalError("check planner returned no checks")

        resolved_spec = {
            **compiled_spec,
            "checks": resolved_checks,
            "check_mode": "auto_generated",
            "check_generation_notes": str(planner_result.get("generation_notes", "")).strip(),
        }
        write_json(run_dir / "compiled_spec.json", resolved_spec)
        write_json(
            run_dir / "auto_checks.json",
            {
                "generated_at": utc_now(),
                "count": len(resolved_checks),
                "notes": resolved_spec["check_generation_notes"],
                "checks": resolved_checks,
            },
        )
        self.repository.update_run(run["id"], compiled_spec=resolved_spec)
        self.repository.append_event(
            run["id"],
            "checks_resolved",
            {
                "source": "auto_generated",
                "count": len(resolved_checks),
                "notes": resolved_spec["check_generation_notes"],
            },
        )
        return resolved_spec

    def _execute_role(
        self,
        run_id: str,
        iter_id: int | None,
        role: str,
        fn: Callable[[], dict],
        retry_config: RetryConfig,
        degrade_once: Callable[[], None] | None = None,
    ) -> dict:
        started_at = time.perf_counter()

        def wrapped() -> dict:
            self.repository.update_run(run_id, active_role=role)
            start_payload = {"role": role}
            if iter_id is not None:
                start_payload["iter"] = iter_id
            self.repository.append_event(run_id, "role_started", start_payload, role=role)
            return fn()

        value, result = execute_with_recovery(wrapped, retry_config, degrade_once=degrade_once)
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        summary_payload = {
            "role": role,
            "ok": result.ok,
            "attempts": result.attempts,
            "degraded": result.degraded,
            "error": str(result.error) if result.error else None,
            "duration_ms": duration_ms,
        }
        if iter_id is not None:
            summary_payload["iter"] = iter_id
        self.repository.append_event(
            run_id,
            "role_execution_summary",
            summary_payload,
            role=role,
        )
        if not result.ok:
            raise RoleExecutionError(role, result)
        return value or {}

    def _run_generator(
        self,
        executor: CodexExecutor,
        run: dict,
        compiled_spec: dict,
        run_dir: Path,
        iter_id: int,
        mode: str,
    ) -> dict:
        output_path = run_dir / "generator_output.json"
        request = RoleRequest(
            run_id=run["id"],
            role="generator",
            prompt=self._generator_prompt(compiled_spec, Path(run["workdir"]), iter_id, mode),
            workdir=Path(run["workdir"]),
            model=run["role_models_json"].get("generator", run["model"]),
            reasoning_effort=run["reasoning_effort"],
            output_schema=GENERATOR_SCHEMA,
            output_path=output_path,
            run_dir=run_dir,
            sandbox="workspace-write",
            idle_timeout_seconds=self.settings.role_idle_timeout_seconds,
            extra_context={"iter_id": iter_id, "compiled_spec": compiled_spec},
        )
        return executor.execute(
            request,
            lambda event_type, payload: self.repository.append_event(run["id"], event_type, payload, role="generator"),
            lambda: self.repository.should_stop(run["id"]),
            lambda pid: self.repository.update_run(run["id"], child_pid=pid) if pid is not None else self.repository.update_run(run["id"], clear_child_pid=True),
        )

    def _run_check_planner(
        self,
        executor: CodexExecutor,
        run: dict,
        compiled_spec: dict,
        run_dir: Path,
    ) -> dict:
        output_path = run_dir / "check_planner_output.raw.json"
        request = RoleRequest(
            run_id=run["id"],
            role="check_planner",
            prompt=self._check_planner_prompt(compiled_spec),
            workdir=Path(run["workdir"]),
            model=run["model"],
            reasoning_effort=run["reasoning_effort"],
            output_schema=CHECK_PLANNER_SCHEMA,
            output_path=output_path,
            run_dir=run_dir,
            sandbox="read-only",
            idle_timeout_seconds=self.settings.role_idle_timeout_seconds,
            extra_context={"compiled_spec": compiled_spec},
        )
        return executor.execute(
            request,
            lambda event_type, payload: self.repository.append_event(run["id"], event_type, payload, role="check_planner"),
            lambda: self.repository.should_stop(run["id"]),
            lambda pid: self.repository.update_run(run["id"], child_pid=pid) if pid is not None else self.repository.update_run(run["id"], clear_child_pid=True),
        )

    def _run_tester(
        self,
        executor: CodexExecutor,
        run: dict,
        compiled_spec: dict,
        run_dir: Path,
        iter_id: int,
        mode: str,
    ) -> dict:
        output_path = run_dir / "tester_output.raw.json"
        request = RoleRequest(
            run_id=run["id"],
            role="tester",
            prompt=self._tester_prompt(compiled_spec, iter_id, mode),
            workdir=Path(run["workdir"]),
            model=run["role_models_json"].get("tester", run["model"]),
            reasoning_effort=run["reasoning_effort"],
            output_schema=TESTER_SCHEMA,
            output_path=output_path,
            run_dir=run_dir,
            sandbox="workspace-write",
            idle_timeout_seconds=self.settings.role_idle_timeout_seconds,
            extra_context={"iter_id": iter_id, "compiled_spec": compiled_spec},
        )
        return executor.execute(
            request,
            lambda event_type, payload: self.repository.append_event(run["id"], event_type, payload, role="tester"),
            lambda: self.repository.should_stop(run["id"]),
            lambda pid: self.repository.update_run(run["id"], child_pid=pid) if pid is not None else self.repository.update_run(run["id"], clear_child_pid=True),
        )

    def _run_verifier(
        self,
        executor: CodexExecutor,
        run: dict,
        compiled_spec: dict,
        run_dir: Path,
        iter_id: int,
        tester_output: dict,
        mode: str,
    ) -> dict:
        output_path = run_dir / "verifier_output.raw.json"
        request = RoleRequest(
            run_id=run["id"],
            role="verifier",
            prompt=self._verifier_prompt(compiled_spec, tester_output, iter_id, mode),
            workdir=Path(run["workdir"]),
            model=run["role_models_json"].get("verifier", run["model"]),
            reasoning_effort=run["reasoning_effort"],
            output_schema=VERIFIER_SCHEMA,
            output_path=output_path,
            run_dir=run_dir,
            sandbox="read-only",
            idle_timeout_seconds=self.settings.role_idle_timeout_seconds,
            extra_context={"iter_id": iter_id, "compiled_spec": compiled_spec, "tester_output": tester_output},
        )
        return executor.execute(
            request,
            lambda event_type, payload: self.repository.append_event(run["id"], event_type, payload, role="verifier"),
            lambda: self.repository.should_stop(run["id"]),
            lambda pid: self.repository.update_run(run["id"], child_pid=pid) if pid is not None else self.repository.update_run(run["id"], clear_child_pid=True),
        )

    def _run_challenger(
        self,
        executor: CodexExecutor,
        run: dict,
        compiled_spec: dict,
        run_dir: Path,
        iter_id: int,
        stagnation: dict,
    ) -> dict:
        output_path = run_dir / "challenger_output.raw.json"
        request = RoleRequest(
            run_id=run["id"],
            role="challenger",
            prompt=self._challenger_prompt(compiled_spec, stagnation, iter_id),
            workdir=Path(run["workdir"]),
            model=run["role_models_json"].get("challenger", run["model"]),
            reasoning_effort=run["reasoning_effort"],
            output_schema=CHALLENGER_SCHEMA,
            output_path=output_path,
            run_dir=run_dir,
            sandbox="read-only",
            idle_timeout_seconds=self.settings.role_idle_timeout_seconds,
            extra_context={
                "iter_id": iter_id,
                "compiled_spec": compiled_spec,
                "stagnation_mode": stagnation["stagnation_mode"],
            },
        )
        return executor.execute(
            request,
            lambda event_type, payload: self.repository.append_event(run["id"], event_type, payload, role="challenger"),
            lambda: self.repository.should_stop(run["id"]),
            lambda pid: self.repository.update_run(run["id"], child_pid=pid) if pid is not None else self.repository.update_run(run["id"], clear_child_pid=True),
        )

    def _ensure_not_stopped(self, run_id: str) -> None:
        if self.repository.should_stop(run_id):
            raise ExecutionStopped(f"run {run_id} was stopped")

    def _set_mode(self, run_id: str, iter_id: int, role: str, holder: dict[str, str], mode: str) -> None:
        holder["value"] = mode
        self.repository.append_event(run_id, "role_degraded", {"iter": iter_id, "role": role, "mode": mode}, role=role)

    def _write_summary(self, run_id: str, status: str, body: str) -> None:
        run = self.get_run(run_id)
        summary = body if body.startswith("#") else f"# Liminal Run Summary\n\nStatus: {status}\n\n{body}\n"
        Path(run["runs_dir"], "summary.md").write_text(summary, encoding="utf-8")
        self.repository.update_run(run_id, summary_md=summary)

    def _build_summary(
        self,
        run: dict,
        compiled_spec: dict,
        iter_id: int,
        verifier_result: dict,
        stagnation: dict,
        exhausted: bool = False,
    ) -> str:
        failed = verifier_result.get("failed_check_ids", [])
        if exhausted:
            status_line = "Max iterations exhausted."
        elif verifier_result["passed"]:
            status_line = "All checks passed in this iteration."
        else:
            status_line = "Still iterating."
        check_mode = compiled_spec.get("check_mode", "specified")
        return (
            "# Liminal Run Summary\n\n"
            f"- Workdir: `{run['workdir']}`\n"
            f"- Iteration: `{iter_id}`\n"
            f"- Check mode: `{check_mode}`\n"
            f"- Check count: `{len(compiled_spec.get('checks', []))}`\n"
            f"- Composite score: `{verifier_result['composite_score']}`\n"
            f"- Passed: `{verifier_result['passed']}`\n"
            f"- Stagnation mode: `{stagnation['stagnation_mode']}`\n"
            f"- Failed checks: `{', '.join(failed) if failed else 'none'}`\n\n"
            f"{status_line}\n"
        )

    def _check_planner_prompt(self, compiled_spec: dict) -> str:
        constraints = compiled_spec.get("constraints") or "No explicit constraints were provided."
        return (
            "You are the Check Planner inside Liminal.\n"
            "The spec did not provide explicit checks, so you must derive a frozen exploratory set for this run.\n"
            "Inspect the current workdir, stay close to the stated goal, and do not invent unrelated requirements.\n"
            "Generate 3 to 5 independently judgeable checks. Prefer concise titles and practical evaluation criteria.\n"
            "Do not edit files.\n"
            f"Goal:\n{compiled_spec['goal']}\n\n"
            f"Constraints:\n{constraints}\n\n"
            "Return JSON with `checks` and `generation_notes`. Each check must include `title`, `details`, `when`, `expect`, and `fail_if`. "
            "Use empty strings only when a field truly cannot be made more specific."
        )

    def _generator_prompt(self, compiled_spec: dict, workdir: Path, iter_id: int, mode: str) -> str:
        constraints = compiled_spec.get("constraints") or "No explicit constraints were provided."
        bootstrap_guidance = ""
        if iter_id == 0 and self._is_bootstrap_workspace(workdir):
            bootstrap_guidance = (
                "Workspace state:\n"
                "Only the spec is present right now, so this iteration should bootstrap the first implementation.\n"
                "Create the smallest runnable prototype from scratch in this round instead of spending the whole turn on planning.\n"
                "Prefer a minimal static entry point plus tiny supporting files when needed.\n\n"
            )
        return (
            "You are the Generator role inside Liminal.\n"
            "Goal: improve the workspace to satisfy the spec with one coherent change direction.\n"
            f"Iteration: {iter_id}\n"
            f"Mode: {mode}\n"
            f"Check mode: {compiled_spec.get('check_mode', 'specified')}\n"
            "You may edit files inside the workdir. Do not write into .liminal except for explicitly requested outputs.\n"
            f"{bootstrap_guidance}"
            f"Spec goal:\n{compiled_spec['goal']}\n\n"
            f"Checks:\n{self._render_checks(compiled_spec['checks'])}\n\n"
            f"Constraints:\n{constraints}\n\n"
            "Return JSON with attempted, abandoned, assumption, summary, and changed_files."
        )

    def _tester_prompt(self, compiled_spec: dict, iter_id: int, mode: str) -> str:
        checks = json.dumps(compiled_spec["checks"], ensure_ascii=False, indent=2)
        return (
            "You are the Tester role inside Liminal.\n"
            "Inspect the workdir, run the most relevant commands, and evaluate the listed checks.\n"
            "Do not edit source files.\n"
            f"Iteration: {iter_id}\n"
            f"Mode: {mode}\n"
            f"Checks:\n{checks}\n\n"
            "For every `check_results` item and every `dynamic_checks` item, return `id`, `title`, `status`, and `notes`.\n"
            "Return JSON with execution_summary, check_results, dynamic_checks, and tester_observations."
        )

    def _verifier_prompt(self, compiled_spec: dict, tester_output: dict, iter_id: int, mode: str) -> str:
        constraints = compiled_spec.get("constraints") or "No explicit constraints were provided."
        return (
            "You are the Verifier role inside Liminal.\n"
            "Judge the tester output conservatively against the goal, checks, and constraints.\n"
            f"Iteration: {iter_id}\n"
            f"Mode: {mode}\n"
            f"Goal:\n{compiled_spec['goal']}\n\n"
            f"Checks:\n{self._render_checks(compiled_spec['checks'])}\n\n"
            f"Constraints:\n{constraints}\n\n"
            f"Tester output:\n{json.dumps(tester_output, ensure_ascii=False, indent=2)}\n\n"
            "Inside `metric_scores`, provide exactly `check_pass_rate` and `quality_score`, each with `value`, `threshold`, and `passed`.\n"
            "For every `priority_failures` item, return `error_code` and `summary`.\n"
            "Return JSON with passed, composite_score, metric_scores, hard_constraint_violations, "
            "failed_check_ids, priority_failures, feedback_to_generator, and verifier_confidence."
        )

    def _challenger_prompt(self, compiled_spec: dict, stagnation: dict, iter_id: int) -> str:
        constraints = compiled_spec.get("constraints") or "No explicit constraints were provided."
        return (
            "You are the Challenger role inside Liminal.\n"
            "Suggest the smallest high-leverage direction change when progress stalls.\n"
            f"Iteration: {iter_id}\n"
            f"Spec goal:\n{compiled_spec['goal']}\n\n"
            f"Checks:\n{self._render_checks(compiled_spec['checks'])}\n\n"
            f"Constraints:\n{constraints}\n\n"
            f"Stagnation state:\n{json.dumps(stagnation, ensure_ascii=False, indent=2)}\n\n"
            "Inside `analysis`, return `stagnation_pattern`, `recommended_shift`, and `risk_note`.\n"
            "Return JSON with created_at_iter, mode, consumed, analysis, seed_question, and meta_note."
        )

    def _normalize_generated_checks(self, checks: list[dict]) -> list[dict]:
        normalized = []
        for index, raw_check in enumerate(checks, start=1):
            title = str(raw_check.get("title", "")).strip() or f"Exploratory check {index}"
            when = str(raw_check.get("when", "")).strip()
            expect = str(raw_check.get("expect", "")).strip()
            fail_if = str(raw_check.get("fail_if", "")).strip()
            details = str(raw_check.get("details", "")).strip()
            if not details:
                parts = []
                if when:
                    parts.append(f"When: {when}")
                if expect:
                    parts.append(f"Expect: {expect}")
                if fail_if:
                    parts.append(f"Fail if: {fail_if}")
                details = "\n".join(parts).strip()
            normalized.append(
                {
                    "id": f"check_{index:03d}",
                    "title": title,
                    "details": details or "Auto-generated exploratory check.",
                    "when": when,
                    "expect": expect,
                    "fail_if": fail_if,
                    "source": "auto_generated",
                }
            )
        return normalized

    def _render_checks(self, checks: list[dict]) -> str:
        return json.dumps(checks, ensure_ascii=False, indent=2)

    def _is_bootstrap_workspace(self, workdir: Path) -> bool:
        ignored_dirs = {".git", ".liminal", ".venv", "venv", "node_modules", "dist", "build", "__pycache__"}
        scanned_files = 0
        for root, dirs, files in os.walk(workdir):
            dirs[:] = [name for name in dirs if name not in ignored_dirs]
            for filename in files:
                if filename == ".DS_Store":
                    continue
                scanned_files += 1
                if scanned_files >= 200:
                    return False
                relative_path = (Path(root) / filename).relative_to(workdir).as_posix()
                if relative_path == "spec.md":
                    continue
                return False
        return True

    def _ensure_loop_dir(self, workdir: Path, loop_id: str) -> Path:
        path = workdir / ".liminal" / "loops" / loop_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _ensure_run_dir(self, workdir: Path, run_id: str) -> Path:
        path = workdir / ".liminal" / "runs" / run_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _write_recent_workdirs(self) -> None:
        loops = self.repository.list_loops()
        recent = []
        seen = set()
        for loop in loops:
            workdir = loop["workdir"]
            if workdir not in seen:
                recent.append(workdir)
                seen.add(workdir)
        path = app_home() / "recent_workdirs.json"
        path.write_text(json.dumps(recent[:50], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


GENERATOR_SCHEMA = {
    "type": "object",
    "required": ["attempted", "abandoned", "assumption", "summary", "changed_files"],
    "properties": {
        "attempted": {"type": "string"},
        "abandoned": {"type": "string"},
        "assumption": {"type": "string"},
        "summary": {"type": "string"},
        "changed_files": {"type": "array", "items": {"type": "string"}},
    },
    "additionalProperties": False,
}

CHECK_PLANNER_SCHEMA = {
    "type": "object",
    "required": ["checks", "generation_notes"],
    "properties": {
        "checks": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["title", "details", "when", "expect", "fail_if"],
                "properties": {
                    "title": {"type": "string"},
                    "details": {"type": "string"},
                    "when": {"type": "string"},
                    "expect": {"type": "string"},
                    "fail_if": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
        "generation_notes": {"type": "string"},
    },
    "additionalProperties": False,
}

TESTER_SCHEMA = {
    "type": "object",
    "required": ["execution_summary", "check_results", "dynamic_checks", "tester_observations"],
    "properties": {
        "execution_summary": {
            "type": "object",
            "required": ["total_checks", "passed", "failed", "errored", "total_duration_ms"],
            "properties": {
                "total_checks": {"type": "integer"},
                "passed": {"type": "integer"},
                "failed": {"type": "integer"},
                "errored": {"type": "integer"},
                "total_duration_ms": {"type": "integer"},
            },
            "additionalProperties": False,
        },
        "check_results": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "title", "status", "notes"],
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "status": {"type": "string", "enum": ["passed", "failed", "errored", "skipped"]},
                    "notes": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
        "dynamic_checks": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "title", "status", "notes"],
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "status": {"type": "string", "enum": ["passed", "failed", "errored", "skipped"]},
                    "notes": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
        "tester_observations": {"type": "string"},
    },
    "additionalProperties": False,
}

VERIFIER_SCHEMA = {
    "type": "object",
    "required": [
        "passed",
        "composite_score",
        "metric_scores",
        "hard_constraint_violations",
        "failed_check_ids",
        "priority_failures",
        "feedback_to_generator",
        "verifier_confidence",
    ],
    "properties": {
        "passed": {"type": "boolean"},
        "composite_score": {"type": "number"},
        "metric_scores": {
            "type": "object",
            "required": ["check_pass_rate", "quality_score"],
            "properties": {
                "check_pass_rate": {
                    "type": "object",
                    "required": ["value", "threshold", "passed"],
                    "properties": {
                        "value": {"type": "number"},
                        "threshold": {"type": "number"},
                        "passed": {"type": "boolean"},
                    },
                    "additionalProperties": False,
                },
                "quality_score": {
                    "type": "object",
                    "required": ["value", "threshold", "passed"],
                    "properties": {
                        "value": {"type": "number"},
                        "threshold": {"type": "number"},
                        "passed": {"type": "boolean"},
                    },
                    "additionalProperties": False,
                },
            },
            "additionalProperties": False,
        },
        "hard_constraint_violations": {"type": "array", "items": {"type": "string"}},
        "failed_check_ids": {"type": "array", "items": {"type": "string"}},
        "priority_failures": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["error_code", "summary"],
                "properties": {
                    "error_code": {"type": "string"},
                    "summary": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
        "feedback_to_generator": {"type": "string"},
        "verifier_confidence": {"type": "string", "enum": ["low", "medium", "high"]},
    },
    "additionalProperties": False,
}

CHALLENGER_SCHEMA = {
    "type": "object",
    "required": ["created_at_iter", "mode", "consumed", "analysis", "seed_question", "meta_note"],
    "properties": {
        "created_at_iter": {"type": "integer"},
        "mode": {"type": "string"},
        "consumed": {"type": "boolean"},
        "analysis": {
            "type": "object",
            "required": ["stagnation_pattern", "recommended_shift", "risk_note"],
            "properties": {
                "stagnation_pattern": {"type": "string"},
                "recommended_shift": {"type": "string"},
                "risk_note": {"type": "string"},
            },
            "additionalProperties": False,
        },
        "seed_question": {"type": "string"},
        "meta_note": {"type": "string"},
    },
    "additionalProperties": False,
}


def create_service(executor_factory: Callable[[], CodexExecutor] | None = None) -> LiminalService:
    return LiminalService(
        repository=LiminalRepository(db_path()),
        settings=load_settings(),
        executor_factory=executor_factory,
    )
