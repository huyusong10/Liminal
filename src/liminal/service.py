from __future__ import annotations

import itertools
import json
import logging
import os
import shutil
import threading
import time
from datetime import datetime
from html import escape as escape_html
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
    validate_command_args_text,
)
from liminal.providers import executor_profile, normalize_executor_kind, normalize_executor_mode
from liminal.recovery import RecoveryResult, RetryConfig, execute_with_recovery
from liminal.settings import AppSettings, app_home, db_path, load_settings
from liminal.specs import SpecError, compile_markdown_spec, read_and_compile
from liminal.stagnation import update_stagnation
from liminal.utils import append_jsonl, make_id, read_json, utc_now, write_json

logger = logging.getLogger(__name__)
LOOP_ROLE_NAMES = ("generator", "tester", "verifier", "challenger")


class LiminalError(RuntimeError):
    """Domain error surfaced to CLI and API consumers."""


class RoleExecutionError(LiminalError):
    def __init__(self, role: str, result: RecoveryResult) -> None:
        self.role = role
        self.result = result
        super().__init__(f"role={role} failed after {result.attempts} attempts")


class WorkspaceSafetyError(LiminalError):
    def __init__(self, *, role: str, deleted_paths: list[str], baseline_count: int, current_count: int) -> None:
        self.role = role
        self.deleted_paths = deleted_paths
        self.baseline_count = baseline_count
        self.current_count = current_count
        preview = ", ".join(deleted_paths[:5])
        super().__init__(
            "workspace safety guard blocked a destructive rewrite: "
            f"{len(deleted_paths)} of {baseline_count} original files disappeared"
            + (f" ({preview})" if preview else "")
        )


class StopRequested(LiminalError):
    """Raised when a user asked to stop a running loop."""


def normalize_role_models(role_models: dict | None) -> dict[str, str]:
    normalized: dict[str, str] = {}
    if not role_models:
        return normalized
    for raw_role, raw_model in dict(role_models).items():
        role = str(raw_role).strip()
        model = str(raw_model).strip()
        if not role:
            raise LiminalError("role model overrides require a role name")
        if role not in LOOP_ROLE_NAMES or not model:
            raise LiminalError(f"invalid role model override: {raw_role}={raw_model}")
        normalized[role] = model
    return normalized


class LiminalService:
    _process_active_runs: set[str] = set()
    _process_active_runs_lock = threading.Lock()

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
        self._reconcile_stale_runs()

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
        executor_kind: str = "codex",
        executor_mode: str = "preset",
        command_cli: str = "",
        command_args_text: str = "",
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
            executor_kind = normalize_executor_kind(executor_kind)
            executor_mode = normalize_executor_mode(executor_mode)
            profile = executor_profile(executor_kind)
            if executor_mode == "preset":
                command_cli = ""
                command_args_text = ""
                model = model.strip() if model.strip() else profile.default_model
                reasoning_effort = normalize_reasoning_effort(reasoning_effort, executor_kind)
            else:
                command_cli = command_cli.strip() or profile.cli_name
                validate_command_args_text(command_args_text, executor_kind=executor_kind)
                model = model.strip()
                reasoning_effort = reasoning_effort.strip()
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
            "executor_kind": executor_kind,
            "executor_mode": executor_mode,
            "command_cli": command_cli,
            "command_args_text": command_args_text,
            "model": model,
            "reasoning_effort": reasoning_effort,
            "max_iters": max_iters,
            "max_role_retries": max_role_retries,
            "delta_threshold": delta_threshold,
            "trigger_window": trigger_window,
            "regression_window": regression_window,
            "role_models": normalize_role_models(role_models),
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
        write_json(run_dir / "workspace_baseline.json", self._capture_workspace_manifest(Path(loop["workdir"])))
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
                "executor_kind": loop.get("executor_kind", "codex"),
                "executor_mode": loop.get("executor_mode", "preset"),
                "command_cli": loop.get("command_cli", ""),
                "command_args_text": loop.get("command_args_text", ""),
                "model": loop["model"],
                "reasoning_effort": coerce_reasoning_effort(loop["reasoning_effort"], loop.get("executor_kind", "codex")),
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
        self._mark_run_active(run_id)
        thread = threading.Thread(target=self.execute_run, args=(run_id,), daemon=True, name=f"run-{run_id}")
        self._threads[run_id] = thread
        try:
            thread.start()
        except Exception:
            self._mark_run_inactive(run_id)
            self._threads.pop(run_id, None)
            raise

    def execute_run(self, run_id: str) -> dict:
        run = self.repository.get_run(run_id)
        if not run:
            raise LiminalError(f"unknown run: {run_id}")

        self._mark_run_active(run_id)
        run_dir = Path(run["runs_dir"])

        try:
            self.repository.update_run(run_id, runner_pid=os.getpid())
            self._wait_for_slot(run_id)
            run = self.repository.get_run(run_id)
            if not run:
                raise LiminalError(f"unknown run after queue wait: {run_id}")
            if run["status"] == "stopped":
                return run

            executor = self.executor_factory()
            compiled_spec = run["compiled_spec_json"]
            retry_config = RetryConfig(max_retries=run["max_role_retries"])
            stagnation = read_json(run_dir / "stagnation.json")
            metrics_history_path = run_dir / "metrics_history.jsonl"
            metrics_history_path.touch(exist_ok=True)
            last_iter_id = -1
            last_generator_result: dict | None = None
            last_tester_result: dict | None = None
            last_verifier_result: dict | None = None
            last_challenger_result: dict | None = None

            self.repository.append_event(run_id, "run_started", {"status": "running"})
            self._write_summary(run_id, "running", "Resolving checks for this run.")
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
                        previous_generator_result=last_generator_result,
                        previous_tester_result=last_tester_result,
                        previous_verifier_result=last_verifier_result,
                        previous_challenger_result=last_challenger_result,
                    ),
                    retry_config,
                    degrade_once=lambda: self._set_mode(run_id, iter_id, "generator", generator_mode, "conservative_changes"),
                )
                append_jsonl(
                    run_dir / "iteration_log.jsonl",
                    self._build_generator_log_entry(iter_id, generator_result, generator_mode["value"]),
                )
                self._enforce_workspace_safety(run, run_dir, iter_id, role="generator")

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
                tester_result = self._enrich_tester_result(tester_result)
                write_json(run_dir / "tester_output.json", tester_result)
                self._enforce_workspace_safety(run, run_dir, iter_id, role="tester")

                previous_composite = last_verifier_result["composite_score"] if last_verifier_result is not None else None
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
                verifier_result = self._enrich_verifier_result(verifier_result, compiled_spec, tester_result)
                write_json(run_dir / "verifier_verdict.json", verifier_result)
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
                else:
                    challenger_result = None
                write_json(run_dir / "stagnation.json", stagnation)

                append_jsonl(
                    metrics_history_path,
                    {
                        "iter": iter_id,
                        "timestamp": utc_now(),
                        "composite": verifier_result["composite_score"],
                        "score_delta": round(verifier_result["composite_score"] - previous_composite, 6)
                        if previous_composite is not None
                        else None,
                        "passed": verifier_result["passed"],
                        "metric_scores": verifier_result["metric_scores"],
                        "failed_check_ids": verifier_result.get("failed_check_ids", []),
                        "failed_check_titles": verifier_result.get("failed_check_titles", []),
                        "stagnation_mode": stagnation["stagnation_mode"],
                    },
                )
                append_jsonl(
                    run_dir / "iteration_log.jsonl",
                    self._build_iteration_log_entry(
                        iter_id,
                        generator_result,
                        tester_result,
                        verifier_result,
                        stagnation,
                        generator_mode["value"],
                        tester_mode["value"],
                        verifier_mode["value"],
                        previous_composite=previous_composite,
                        challenger_result=challenger_result,
                    ),
                )

                summary = self._build_summary(
                    run,
                    compiled_spec,
                    iter_id,
                    generator_result,
                    tester_result,
                    verifier_result,
                    stagnation,
                    generator_mode["value"],
                    tester_mode["value"],
                    verifier_mode["value"],
                    previous_composite=previous_composite,
                    challenger_result=challenger_result,
                )
                self._write_summary(run_id, "running", summary)
                last_generator_result = generator_result
                last_tester_result = tester_result
                last_verifier_result = verifier_result
                last_challenger_result = challenger_result

                if verifier_result["passed"]:
                    finished = self.repository.update_run(
                        run_id,
                        status="succeeded",
                        finished_at=utc_now(),
                        last_verdict=verifier_result,
                        summary_md=summary,
                    )
                    self._persist_summary_file(run_dir, summary)
                    self.repository.append_event(run_id, "run_finished", {"status": "succeeded", "iter": iter_id})
                    return finished

            if run["max_iters"] != 0 and last_verifier_result is not None:
                summary = self._build_summary(
                    run,
                    compiled_spec,
                    last_iter_id,
                    last_generator_result or {},
                    last_tester_result or {},
                    last_verifier_result,
                    stagnation,
                    generator_mode["value"],
                    tester_mode["value"],
                    verifier_mode["value"],
                    exhausted=True,
                    previous_composite=None,
                    challenger_result=last_challenger_result,
                )
                finished = self.repository.update_run(
                    run_id,
                    status="failed",
                    finished_at=utc_now(),
                    summary_md=summary,
                )
                self._persist_summary_file(run_dir, summary)
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
            self._persist_summary_file(run_dir, summary)
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
            self._persist_summary_file(run_dir, summary)
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
        except WorkspaceSafetyError as exc:
            error_text = str(exc)
            verdict = {
                "passed": False,
                "composite_score": 0.0,
                "metric_scores": {},
                "hard_constraint_violations": ["workspace_safety_guard"],
                "failed_check_ids": [],
                "priority_failures": [
                    {
                        "error_code": "WORKSPACE_SAFETY_GUARD",
                        "summary": "The run deleted too many original workspace files and was stopped.",
                    }
                ],
                "feedback_to_generator": (
                    "Do not bulk-delete existing user files. Keep original files in place and prefer targeted edits."
                ),
                "verifier_confidence": "high",
            }
            write_json(run_dir / "verifier_verdict.json", verdict)
            deleted_preview = ", ".join(exc.deleted_paths[:5]) if exc.deleted_paths else "none"
            summary = (
                "# Liminal Run Summary\n\n"
                "Execution stopped by the workspace safety guard.\n\n"
                f"- Original files tracked: `{exc.baseline_count}`\n"
                f"- Original files still present: `{exc.current_count}`\n"
                f"- Deleted original files: `{len(exc.deleted_paths)}`\n"
                f"- Sample deleted paths: `{deleted_preview}`\n"
            )
            failed = self.repository.update_run(
                run_id,
                status="failed",
                finished_at=utc_now(),
                error_message=error_text,
                last_verdict=verdict,
                summary_md=summary,
            )
            self._persist_summary_file(run_dir, summary)
            self.repository.append_event(
                run_id,
                "run_aborted",
                {
                    "role": exc.role,
                    "attempts": 1,
                    "degraded": False,
                    "error": error_text,
                },
            )
            return failed
        except Exception as exc:
            error_text = str(exc)
            logger.exception("run %s crashed unexpectedly", run_id)
            summary = (
                "# Liminal Run Summary\n\n"
                "Execution crashed unexpectedly.\n\n"
                f"Reason: `{error_text}`.\n"
            )
            self._persist_summary_file(run_dir, summary)
            try:
                failed = self.repository.update_run(
                    run_id,
                    status="failed",
                    finished_at=utc_now(),
                    error_message=error_text,
                    summary_md=summary,
                )
            except Exception:
                logger.exception("failed to persist crash state for %s", run_id)
                return {
                    **run,
                    "status": "failed",
                    "finished_at": utc_now(),
                    "error_message": error_text,
                    "summary_md": summary,
                }
            try:
                self.repository.append_event(
                    run_id,
                    "run_aborted",
                    {
                        "role": failed.get("active_role"),
                        "attempts": 1,
                        "degraded": False,
                        "error": error_text,
                    },
                )
            except Exception:
                logger.exception("failed to append crash event for %s", run_id)
            return failed
        finally:
            self._mark_run_inactive(run_id)
            try:
                self.repository.release_run_slot(run_id)
            except Exception:
                logger.exception("failed to release run slot for %s", run_id)
            self._threads.pop(run_id, None)

    def stop_run(self, run_id: str) -> dict:
        self._reconcile_local_orphaned_runs()
        current = self.repository.get_run(run_id)
        if not current:
            raise LiminalError(f"unknown run: {run_id}")
        if current["status"] not in {"queued", "running"}:
            raise LiminalError(f"cannot stop run in status {current['status']}")

        run = self.repository.request_stop(run_id)
        if not run:
            raise LiminalError(f"unknown run: {run_id}")
        self.repository.append_event(run_id, "stop_requested", {"status": run["status"]})
        self.repository.send_stop_signal(run_id)
        return run

    def list_loops(self) -> list[dict]:
        self._reconcile_local_orphaned_runs()
        return self.repository.list_loops()

    def get_loop(self, loop_id: str) -> dict:
        self._reconcile_local_orphaned_runs()
        loop = self.repository.get_loop(loop_id)
        if not loop:
            raise LiminalError(f"unknown loop: {loop_id}")
        loop["runs"] = self.repository.list_runs_for_loop(loop_id)
        return loop

    def get_run(self, run_id: str) -> dict:
        self._reconcile_local_orphaned_runs()
        run = self.repository.get_run(run_id)
        if not run:
            raise LiminalError(f"unknown run: {run_id}")
        loop = self.repository.get_loop(run["loop_id"])
        if loop:
            run["loop_name"] = loop["name"]
        return run

    def get_status(self, identifier: str) -> tuple[str, dict]:
        self._reconcile_local_orphaned_runs()
        found = self.repository.get_loop_or_run(identifier)
        if not found:
            raise LiminalError(f"unknown identifier: {identifier}")
        kind, payload = found
        if kind == "loop":
            payload["runs"] = self.repository.list_runs_for_loop(payload["id"])
        return kind, payload

    def get_runtime_activity(self) -> dict:
        self._reconcile_local_orphaned_runs()
        active_runs = self.repository.list_active_runs()
        loop_name_by_id = {
            loop["id"]: loop["name"]
            for loop in self.repository.list_loops()
        }
        running_count = 0
        queued_count = 0
        runs = []
        for run in active_runs:
            status = str(run.get("status") or "").strip()
            if status == "running":
                running_count += 1
            elif status == "queued":
                queued_count += 1
            runs.append(
                {
                    "id": run["id"],
                    "loop_id": run["loop_id"],
                    "loop_name": loop_name_by_id.get(run["loop_id"]) or run["loop_id"],
                    "status": status or "queued",
                    "active_role": run.get("active_role"),
                    "current_iter": run.get("current_iter"),
                    "workdir": run.get("workdir"),
                    "updated_at": run.get("updated_at"),
                }
            )
        return {
            "running_count": running_count,
            "queued_count": queued_count,
            "has_running_runs": running_count > 0,
            "has_active_runs": bool(active_runs),
            "runs": runs,
        }

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

    def _reconcile_stale_runs(self) -> None:
        for run in self.repository.list_active_runs():
            if self._run_process_may_still_be_alive(run):
                continue
            if not self._startup_stale_run_is_recoverable(run):
                continue
            logger.warning("recovering stale run %s after startup because runner pid %s is not alive", run["id"], run.get("runner_pid"))
            summary = (
                "# Liminal Run Summary\n\n"
                "This run was marked stopped when Liminal restarted because its previous worker process was no longer alive.\n"
            )
            self._persist_summary_file(Path(run["runs_dir"]), summary)
            self.repository.update_run(
                run["id"],
                status="stopped",
                finished_at=utc_now(),
                error_message="Recovered stale run after service startup.",
                summary_md=summary,
            )
            self.repository.release_run_slot(run["id"])
            self.repository.append_event(
                run["id"],
                "run_finished",
                {"status": "stopped", "reason": "Recovered stale run after service startup."},
            )

    def _run_process_may_still_be_alive(self, run: dict) -> bool:
        pid = run.get("runner_pid")
        if run.get("status") == "queued":
            return bool(pid and self._pid_exists(pid))
        return bool(pid and self._pid_exists(pid))

    def _startup_stale_run_is_recoverable(self, run: dict) -> bool:
        if run.get("runner_pid"):
            return True
        updated_at = self._parse_run_timestamp(run.get("updated_at") or run.get("started_at") or run.get("queued_at"))
        if updated_at is None:
            return False
        age_seconds = time.time() - updated_at.timestamp()
        return age_seconds >= self._local_run_orphan_grace_seconds()

    def _reconcile_local_orphaned_runs(self) -> None:
        for run in self.repository.list_active_runs():
            self._recover_local_orphaned_run(run)

    def _recover_local_orphaned_run(self, run: dict) -> dict:
        if not self._should_recover_local_orphan(run):
            return run

        reason = "Recovered orphaned run after the local worker stopped unexpectedly."
        logger.warning(
            "recovering local orphaned run %s status=%s runner_pid=%s child_pid=%s updated_at=%s",
            run["id"],
            run.get("status"),
            run.get("runner_pid"),
            run.get("child_pid"),
            run.get("updated_at"),
        )
        summary = (
            "# Liminal Run Summary\n\n"
            "This run was marked failed because the local worker stopped unexpectedly before it could finish cleanly.\n"
        )
        child_pid = run.get("child_pid")
        if child_pid and self._pid_exists(child_pid):
            try:
                os.kill(int(child_pid), 15)
            except OSError:
                logger.exception("failed to stop orphaned child process %s for run %s", child_pid, run["id"])
        self._persist_summary_file(Path(run["runs_dir"]), summary)
        updated = self.repository.update_run(
            run["id"],
            status="failed",
            finished_at=utc_now(),
            error_message=reason,
            summary_md=summary,
        )
        self.repository.release_run_slot(run["id"])
        self.repository.append_event(
            run["id"],
            "run_aborted",
            {
                "role": run.get("active_role"),
                "attempts": 1,
                "degraded": False,
                "error": reason,
            },
        )
        return updated or run

    def _should_recover_local_orphan(self, run: dict) -> bool:
        if run.get("status") not in {"queued", "running"}:
            return False
        if self._is_run_active_locally(run["id"]):
            return False
        if run.get("runner_pid") not in {None, os.getpid()}:
            return False
        updated_at = self._parse_run_timestamp(run.get("updated_at") or run.get("started_at") or run.get("queued_at"))
        if updated_at is None:
            return False
        age_seconds = time.time() - updated_at.timestamp()
        return age_seconds >= self._local_run_orphan_grace_seconds()

    def _local_run_orphan_grace_seconds(self) -> float:
        return max(
            self.settings.stop_grace_period_seconds,
            self.settings.polling_interval_seconds * 4,
            self.settings.role_idle_timeout_seconds,
            30.0,
        )

    def _mark_run_active(self, run_id: str) -> None:
        cls = type(self)
        with cls._process_active_runs_lock:
            cls._process_active_runs.add(run_id)

    def _mark_run_inactive(self, run_id: str) -> None:
        cls = type(self)
        with cls._process_active_runs_lock:
            cls._process_active_runs.discard(run_id)

    def _is_run_active_locally(self, run_id: str) -> bool:
        cls = type(self)
        with cls._process_active_runs_lock:
            return run_id in cls._process_active_runs

    @staticmethod
    def _parse_run_timestamp(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    @staticmethod
    def _pid_exists(pid: int | None) -> bool:
        if not pid:
            return False
        try:
            os.kill(int(pid), 0)
        except (ProcessLookupError, OSError):
            return False
        except PermissionError:
            return True
        return True

    def preview_file(self, run_id: str, root: str, relative_path: str = "") -> dict:
        run = self.get_run(run_id)
        workdir = Path(run["workdir"])
        base = workdir / ".liminal" if root == "liminal" else workdir
        if root == "liminal":
            base.mkdir(parents=True, exist_ok=True)
        base_resolved = base.resolve()
        resolved = (base_resolved / relative_path).resolve()
        if not resolved.is_relative_to(base_resolved):
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
            payload["rendered_html"] = markdown_lib.markdown(escape_html(text), extensions=["fenced_code"])
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
        self._reconcile_local_orphaned_runs()
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
            self._ensure_not_stopped(run_id)
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
        *,
        previous_generator_result: dict | None = None,
        previous_tester_result: dict | None = None,
        previous_verifier_result: dict | None = None,
        previous_challenger_result: dict | None = None,
    ) -> dict:
        output_path = run_dir / "generator_output.json"
        request = RoleRequest(
            run_id=run["id"],
            role="generator",
            prompt=self._generator_prompt(
                compiled_spec,
                Path(run["workdir"]),
                iter_id,
                mode,
                previous_generator_result=previous_generator_result,
                previous_tester_result=previous_tester_result,
                previous_verifier_result=previous_verifier_result,
                previous_challenger_result=previous_challenger_result,
            ),
            workdir=Path(run["workdir"]),
            executor_kind=run.get("executor_kind", "codex"),
            executor_mode=run.get("executor_mode", "preset"),
            command_cli=run.get("command_cli", ""),
            command_args_text=run.get("command_args_text", ""),
            model=run["role_models_json"].get("generator", run["model"]),
            reasoning_effort=run["reasoning_effort"],
            output_schema=GENERATOR_SCHEMA,
            output_path=output_path,
            run_dir=run_dir,
            sandbox="workspace-write",
            idle_timeout_seconds=self.settings.role_idle_timeout_seconds,
            extra_context={
                "iter_id": iter_id,
                "compiled_spec": compiled_spec,
                "previous_generator_result": previous_generator_result,
                "previous_tester_result": previous_tester_result,
                "previous_verifier_result": previous_verifier_result,
                "previous_challenger_result": previous_challenger_result,
            },
        )
        self._record_role_request(run["id"], request)
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
            executor_kind=run.get("executor_kind", "codex"),
            executor_mode=run.get("executor_mode", "preset"),
            command_cli=run.get("command_cli", ""),
            command_args_text=run.get("command_args_text", ""),
            model=run["model"],
            reasoning_effort=run["reasoning_effort"],
            output_schema=CHECK_PLANNER_SCHEMA,
            output_path=output_path,
            run_dir=run_dir,
            sandbox="read-only",
            idle_timeout_seconds=self.settings.role_idle_timeout_seconds,
            extra_context={"compiled_spec": compiled_spec},
        )
        self._record_role_request(run["id"], request)
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
            executor_kind=run.get("executor_kind", "codex"),
            executor_mode=run.get("executor_mode", "preset"),
            command_cli=run.get("command_cli", ""),
            command_args_text=run.get("command_args_text", ""),
            model=run["role_models_json"].get("tester", run["model"]),
            reasoning_effort=run["reasoning_effort"],
            output_schema=TESTER_SCHEMA,
            output_path=output_path,
            run_dir=run_dir,
            sandbox="workspace-write",
            idle_timeout_seconds=self.settings.role_idle_timeout_seconds,
            extra_context={"iter_id": iter_id, "compiled_spec": compiled_spec},
        )
        self._record_role_request(run["id"], request)
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
            executor_kind=run.get("executor_kind", "codex"),
            executor_mode=run.get("executor_mode", "preset"),
            command_cli=run.get("command_cli", ""),
            command_args_text=run.get("command_args_text", ""),
            model=run["role_models_json"].get("verifier", run["model"]),
            reasoning_effort=run["reasoning_effort"],
            output_schema=VERIFIER_SCHEMA,
            output_path=output_path,
            run_dir=run_dir,
            sandbox="read-only",
            idle_timeout_seconds=self.settings.role_idle_timeout_seconds,
            extra_context={"iter_id": iter_id, "compiled_spec": compiled_spec, "tester_output": tester_output},
        )
        self._record_role_request(run["id"], request)
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
            executor_kind=run.get("executor_kind", "codex"),
            executor_mode=run.get("executor_mode", "preset"),
            command_cli=run.get("command_cli", ""),
            command_args_text=run.get("command_args_text", ""),
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
        self._record_role_request(run["id"], request)
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
        self._persist_summary_file(Path(run["runs_dir"]), summary)
        self.repository.update_run(run_id, summary_md=summary)

    def _persist_summary_file(self, run_dir: Path, summary: str) -> None:
        run_dir.mkdir(parents=True, exist_ok=True)
        try:
            (run_dir / "summary.md").write_text(summary, encoding="utf-8")
        except OSError:
            logger.exception("failed to persist summary for run dir %s", run_dir)

    def _record_role_request(self, run_id: str, request: RoleRequest) -> None:
        request_dir = request.run_dir / "role_requests"
        request_dir.mkdir(parents=True, exist_ok=True)
        base_name = self._role_request_basename(request)
        prompt_path = request_dir / f"{base_name}.prompt.txt"
        prompt_path.write_text(request.prompt, encoding="utf-8")
        payload = {
            "timestamp": utc_now(),
            "role": request.role,
            "iter": request.extra_context.get("iter_id"),
            "executor_kind": request.executor_kind,
            "executor_mode": request.executor_mode,
            "model": request.model,
            "reasoning_effort": request.reasoning_effort,
            "sandbox": request.sandbox,
            "workdir": str(request.workdir),
            "output_path": str(request.output_path),
            "prompt_path": str(prompt_path),
            "extra_context_keys": sorted(request.extra_context.keys()),
            "context_summary": self._summarize_role_request_context(request.extra_context),
        }
        append_jsonl(request.run_dir / "role_requests.jsonl", payload)
        self.repository.append_event(run_id, "role_request_prepared", payload, role=request.role)

    def _role_request_basename(self, request: RoleRequest) -> str:
        iter_id = request.extra_context.get("iter_id")
        if isinstance(iter_id, int):
            return f"iter_{iter_id:03d}_{request.role}"
        return request.role

    def _summarize_role_request_context(self, extra_context: dict) -> dict:
        summary: dict[str, object] = {}
        iter_id = extra_context.get("iter_id")
        if iter_id is not None:
            summary["iter_id"] = iter_id
        compiled_spec = extra_context.get("compiled_spec")
        if isinstance(compiled_spec, dict):
            summary["compiled_spec"] = {
                "check_mode": compiled_spec.get("check_mode"),
                "check_count": len(compiled_spec.get("checks", [])),
            }
        previous_generator_result = extra_context.get("previous_generator_result")
        if isinstance(previous_generator_result, dict) and previous_generator_result:
            summary["previous_generator_result"] = {
                "attempted": self._truncate_text(previous_generator_result.get("attempted"), 160),
                "summary": self._truncate_text(previous_generator_result.get("summary"), 160),
            }
        previous_tester_result = extra_context.get("previous_tester_result")
        if isinstance(previous_tester_result, dict) and previous_tester_result:
            summary["previous_tester_result"] = {
                "failed_items": [
                    item.get("title") or item.get("id")
                    for item in previous_tester_result.get("failed_items", [])[:4]
                ],
                "tester_observations": self._truncate_text(previous_tester_result.get("tester_observations"), 160),
            }
        previous_verifier_result = extra_context.get("previous_verifier_result")
        if isinstance(previous_verifier_result, dict) and previous_verifier_result:
            summary["previous_verifier_result"] = {
                "passed": previous_verifier_result.get("passed"),
                "composite_score": previous_verifier_result.get("composite_score"),
                "failed_check_titles": list(previous_verifier_result.get("failed_check_titles", []))[:4],
                "next_actions": list(previous_verifier_result.get("next_actions", []))[:4],
            }
        previous_challenger_result = extra_context.get("previous_challenger_result")
        if isinstance(previous_challenger_result, dict) and previous_challenger_result:
            summary["previous_challenger_result"] = {
                "mode": previous_challenger_result.get("mode"),
                "recommended_shift": self._truncate_text(
                    (previous_challenger_result.get("analysis") or {}).get("recommended_shift"),
                    160,
                ),
                "seed_question": self._truncate_text(previous_challenger_result.get("seed_question"), 160),
            }
        tester_output = extra_context.get("tester_output")
        if isinstance(tester_output, dict):
            summary["tester_output"] = {
                "passed": tester_output.get("execution_summary", {}).get("passed"),
                "failed": tester_output.get("execution_summary", {}).get("failed"),
                "dynamic_failed": len(tester_output.get("dynamic_check_failures", [])),
            }
        stagnation_mode = extra_context.get("stagnation_mode")
        if stagnation_mode is not None:
            summary["stagnation_mode"] = stagnation_mode
        return summary

    @staticmethod
    def _truncate_text(value: str | None, max_length: int = 220) -> str:
        text = str(value or "").strip()
        if len(text) <= max_length:
            return text
        return f"{text[: max_length - 1].rstrip()}..."

    @staticmethod
    def _empty_status_counts() -> dict[str, int]:
        return {"passed": 0, "failed": 0, "errored": 0, "skipped": 0}

    def _count_statuses(self, items: list[dict]) -> dict[str, int]:
        counts = self._empty_status_counts()
        for item in items:
            status = str(item.get("status", "")).strip().lower()
            if status in counts:
                counts[status] += 1
        return counts

    def _collect_non_passing_items(self, items: list[dict], *, source: str) -> list[dict]:
        failures = []
        for item in items:
            status = str(item.get("status", "")).strip().lower()
            if status == "passed":
                continue
            failures.append(
                {
                    "id": str(item.get("id", "")).strip(),
                    "title": str(item.get("title", "")).strip(),
                    "status": status or "unknown",
                    "source": source,
                    "notes": self._truncate_text(str(item.get("notes", "")).strip(), max_length=280),
                }
            )
        return failures

    def _enrich_tester_result(self, tester_result: dict) -> dict:
        result = dict(tester_result)
        check_results = list(result.get("check_results", []))
        dynamic_checks = list(result.get("dynamic_checks", []))
        check_counts = self._count_statuses(check_results)
        dynamic_counts = self._count_statuses(dynamic_checks)
        overall_counts = {
            key: check_counts.get(key, 0) + dynamic_counts.get(key, 0)
            for key in self._empty_status_counts()
        }
        failed_items = self._collect_non_passing_items(check_results, source="specified")
        failed_items.extend(self._collect_non_passing_items(dynamic_checks, source="dynamic"))
        result["status_counts"] = {
            "check_results": check_counts,
            "dynamic_checks": dynamic_counts,
            "overall": overall_counts,
        }
        result["failed_items"] = failed_items
        result["specified_check_failures"] = [item["id"] for item in failed_items if item["source"] == "specified"]
        result["dynamic_check_failures"] = [item["id"] for item in failed_items if item["source"] == "dynamic"]
        return result

    def _build_decision_summary(self, verifier_result: dict, tester_result: dict) -> str:
        reasons: list[str] = []
        failed_check_titles = list(verifier_result.get("failed_check_titles", []))
        dynamic_failures = list(tester_result.get("dynamic_check_failures", []))
        hard_constraint_violations = list(verifier_result.get("hard_constraint_violations", []))
        failing_metrics = list(verifier_result.get("failing_metrics", []))
        priority_failures = list(verifier_result.get("priority_failures", []))
        if failed_check_titles:
            reasons.append(
                "specified checks still failing: "
                + ", ".join(failed_check_titles[:3])
                + ("..." if len(failed_check_titles) > 3 else "")
            )
        if dynamic_failures:
            reasons.append(
                f"{len(dynamic_failures)} dynamic check failure"
                + ("s remain" if len(dynamic_failures) != 1 else " remains")
            )
        if hard_constraint_violations:
            reasons.append(
                f"{len(hard_constraint_violations)} hard constraint violation"
                + ("s" if len(hard_constraint_violations) != 1 else "")
            )
        if failing_metrics:
            metric_names = [str(item.get("name", "")).strip() for item in failing_metrics if item.get("name")]
            if metric_names:
                reasons.append("failing metrics: " + ", ".join(metric_names))
        if priority_failures and not reasons:
            reasons.append(
                "priority failures reported: "
                + ", ".join(self._truncate_text(item.get("summary"), 120) for item in priority_failures[:2])
            )
        if verifier_result.get("passed"):
            return "All specified and dynamic checks passed with no blocking constraint violations."
        if not reasons:
            return "The run is not yet passing because one or more checks or metrics remain below threshold."
        return "The run is not yet passing because " + "; ".join(reasons) + "."

    def _split_action_hints(self, feedback: str | None) -> list[str]:
        text = str(feedback or "").strip()
        if not text:
            return []
        hints = []
        for raw_line in text.splitlines():
            cleaned = raw_line.strip().lstrip("-*").strip()
            if cleaned:
                hints.append(cleaned)
        return hints[:5] if hints else [text]

    def _enrich_verifier_result(self, verifier_result: dict, compiled_spec: dict, tester_result: dict) -> dict:
        result = dict(verifier_result)
        check_title_map = {str(check.get("id", "")).strip(): str(check.get("title", "")).strip() for check in compiled_spec.get("checks", [])}
        failed_check_titles = [check_title_map.get(check_id, check_id) for check_id in result.get("failed_check_ids", [])]
        failing_metrics = []
        for name, metric in (result.get("metric_scores") or {}).items():
            if metric.get("passed"):
                continue
            failing_metrics.append(
                {
                    "name": name,
                    "value": metric.get("value"),
                    "threshold": metric.get("threshold"),
                }
            )
        result["failed_check_titles"] = failed_check_titles
        result["failing_metrics"] = failing_metrics
        result["hard_constraint_violation_count"] = len(result.get("hard_constraint_violations", []))
        result["priority_failure_count"] = len(result.get("priority_failures", []))
        result["decision_summary"] = self._build_decision_summary(result, tester_result)
        result["next_actions"] = self._split_action_hints(result.get("feedback_to_generator"))
        return result

    def _format_inline_code_list(self, items: list[str], *, empty: str = "none", limit: int = 5) -> str:
        values = [str(item).strip() for item in items if str(item).strip()]
        if not values:
            return empty
        visible = [f"`{item}`" for item in values[:limit]]
        if len(values) > limit:
            visible.append(f"`+{len(values) - limit} more`")
        return ", ".join(visible)

    def _format_failure_refs(self, items: list[dict], *, limit: int = 4) -> str:
        if not items:
            return "none"
        visible = []
        for item in items[:limit]:
            label = item.get("title") or item.get("id") or "unknown"
            source = item.get("source")
            if source == "dynamic":
                label = f"{label} [dynamic]"
            visible.append(f"`{label}`")
        if len(items) > limit:
            visible.append(f"`+{len(items) - limit} more`")
        return ", ".join(visible)

    def _format_metric_refs(self, metrics: list[dict], *, limit: int = 4) -> str:
        if not metrics:
            return "none"
        visible = []
        for metric in metrics[:limit]:
            name = str(metric.get("name", "")).strip() or "unknown_metric"
            value = metric.get("value")
            threshold = metric.get("threshold")
            if value is None or threshold is None:
                visible.append(f"`{name}`")
            else:
                visible.append(f"`{name}={value}` (threshold `{threshold}`)")
        if len(metrics) > limit:
            visible.append(f"`+{len(metrics) - limit} more`")
        return ", ".join(visible)

    def _build_generator_log_entry(self, iter_id: int, generator_result: dict, mode: str) -> dict:
        return {
            "phase": "generator",
            "iter": iter_id,
            "timestamp": utc_now(),
            "mode": mode,
            "attempted": generator_result.get("attempted", ""),
            "summary": generator_result.get("summary", ""),
            "assumption": generator_result.get("assumption", ""),
            "abandoned": generator_result.get("abandoned", ""),
            "changed_files": list(generator_result.get("changed_files", [])),
        }

    def _build_iteration_log_entry(
        self,
        iter_id: int,
        generator_result: dict,
        tester_result: dict,
        verifier_result: dict,
        stagnation: dict,
        generator_mode: str,
        tester_mode: str,
        verifier_mode: str,
        *,
        previous_composite: float | None,
        challenger_result: dict | None = None,
    ) -> dict:
        entry = {
            "phase": "complete",
            "iter": iter_id,
            "timestamp": utc_now(),
            "modes": {
                "generator": generator_mode,
                "tester": tester_mode,
                "verifier": verifier_mode,
            },
            "score": {
                "composite": verifier_result.get("composite_score"),
                "delta": round(verifier_result["composite_score"] - previous_composite, 6)
                if previous_composite is not None
                else None,
                "passed": verifier_result.get("passed"),
            },
            "generator": {
                "attempted": generator_result.get("attempted", ""),
                "summary": generator_result.get("summary", ""),
                "assumption": generator_result.get("assumption", ""),
                "abandoned": generator_result.get("abandoned", ""),
                "changed_files": list(generator_result.get("changed_files", [])),
            },
            "tester": {
                "execution_summary": dict(tester_result.get("execution_summary", {})),
                "status_counts": dict(tester_result.get("status_counts", {})),
                "failed_items": list(tester_result.get("failed_items", [])),
                "tester_observations": tester_result.get("tester_observations", ""),
            },
            "verifier": {
                "passed": verifier_result.get("passed"),
                "decision_summary": verifier_result.get("decision_summary", ""),
                "failed_check_ids": list(verifier_result.get("failed_check_ids", [])),
                "failed_check_titles": list(verifier_result.get("failed_check_titles", [])),
                "failing_metrics": list(verifier_result.get("failing_metrics", [])),
                "hard_constraint_violations": list(verifier_result.get("hard_constraint_violations", [])),
                "priority_failures": list(verifier_result.get("priority_failures", [])),
                "feedback_to_generator": verifier_result.get("feedback_to_generator", ""),
                "next_actions": list(verifier_result.get("next_actions", [])),
            },
            "stagnation": {
                "mode": stagnation.get("stagnation_mode", "none"),
                "recent_composites": list(stagnation.get("recent_composites", [])),
                "recent_deltas": list(stagnation.get("recent_deltas", [])),
                "consecutive_low_delta": stagnation.get("consecutive_low_delta", 0),
            },
        }
        if challenger_result is not None:
            entry["challenger"] = {
                "mode": challenger_result.get("mode"),
                "analysis": dict(challenger_result.get("analysis", {})),
                "seed_question": challenger_result.get("seed_question", ""),
                "meta_note": challenger_result.get("meta_note", ""),
            }
        return entry

    def _build_summary(
        self,
        run: dict,
        compiled_spec: dict,
        iter_id: int,
        generator_result: dict,
        tester_result: dict,
        verifier_result: dict,
        stagnation: dict,
        generator_mode: str,
        tester_mode: str,
        verifier_mode: str,
        exhausted: bool = False,
        previous_composite: float | None = None,
        challenger_result: dict | None = None,
    ) -> str:
        failed = verifier_result.get("failed_check_titles", verifier_result.get("failed_check_ids", []))
        if exhausted:
            status_line = "Max iterations exhausted."
        elif verifier_result["passed"]:
            status_line = "All checks passed in this iteration."
        else:
            status_line = "Still iterating."
        check_mode = compiled_spec.get("check_mode", "specified")
        overall_counts = tester_result.get("status_counts", {}).get("overall", self._empty_status_counts())
        dynamic_counts = tester_result.get("status_counts", {}).get("dynamic_checks", self._empty_status_counts())
        delta_text = (
            f"`{round(verifier_result['composite_score'] - previous_composite, 6):+}`"
            if previous_composite is not None
            else "`n/a`"
        )
        lines = [
            "# Liminal Run Summary",
            "",
            f"- Workdir: `{run['workdir']}`",
            f"- Iteration: `{iter_id + 1}`",
            f"- Check mode: `{check_mode}`",
            f"- Check count: `{len(compiled_spec.get('checks', []))}`",
            f"- Composite score: `{verifier_result['composite_score']}`",
            f"- Score delta vs previous iteration: {delta_text}",
            f"- Passed: `{verifier_result['passed']}`",
            f"- Stagnation mode: `{stagnation.get('stagnation_mode', 'none')}`",
            f"- Failed checks: {self._format_inline_code_list(failed, empty='none', limit=4)}",
            (
                "- Role modes: "
                f"generator=`{generator_mode}`, tester=`{tester_mode}`, verifier=`{verifier_mode}`"
            ),
            "",
            status_line,
            "",
            "## Generator",
            f"- Attempted: {self._truncate_text(generator_result.get('attempted') or generator_result.get('summary'), 280) or 'none'}",
            f"- Changed files: {self._format_inline_code_list(list(generator_result.get('changed_files', [])))}",
            f"- Assumption: {self._truncate_text(generator_result.get('assumption'), 220) or 'none'}",
            f"- Abandoned: {self._truncate_text(generator_result.get('abandoned'), 220) or 'none'}",
            "",
            "## Tester",
            (
                "- Overall statuses: "
                f"passed=`{overall_counts['passed']}`, failed=`{overall_counts['failed']}`, "
                f"errored=`{overall_counts['errored']}`, skipped=`{overall_counts['skipped']}`"
            ),
            (
                "- Dynamic checks: "
                f"passed=`{dynamic_counts['passed']}`, failed=`{dynamic_counts['failed']}`, "
                f"errored=`{dynamic_counts['errored']}`, skipped=`{dynamic_counts['skipped']}`"
            ),
            f"- Non-passing items: {self._format_failure_refs(list(tester_result.get('failed_items', [])))}",
            f"- Observations: {self._truncate_text(tester_result.get('tester_observations'), 320) or 'none'}",
            "",
            "## Verifier",
            f"- Decision: {self._truncate_text(verifier_result.get('decision_summary'), 320) or 'none'}",
            f"- Failing metrics: {self._format_metric_refs(list(verifier_result.get('failing_metrics', [])))}",
            (
                "- Hard constraint violations: "
                f"{self._format_inline_code_list(list(verifier_result.get('hard_constraint_violations', [])), empty='none', limit=3)}"
            ),
            (
                "- Priority failures: "
                f"{self._format_inline_code_list([item.get('error_code', 'unknown') for item in verifier_result.get('priority_failures', [])], empty='none', limit=4)}"
            ),
            (
                "- Next actions: "
                f"{self._format_inline_code_list(list(verifier_result.get('next_actions', [])), empty='none', limit=3)}"
            ),
        ]
        if challenger_result is not None:
            lines.extend(
                [
                    "",
                    "## Challenger",
                    f"- Mode: `{challenger_result.get('mode', 'unknown')}`",
                    f"- Recommended shift: {self._truncate_text(challenger_result.get('analysis', {}).get('recommended_shift'), 220) or 'none'}",
                    f"- Seed question: {self._truncate_text(challenger_result.get('seed_question'), 220) or 'none'}",
                ]
            )
        lines.extend(
            [
                "",
                "## Artifacts",
                "- Inspect `tester_output.json`, `verifier_verdict.json`, `iteration_log.jsonl`, and `events.jsonl` for full details.",
            ]
        )
        return "\n".join(lines).rstrip() + "\n"

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

    def _generator_prompt(
        self,
        compiled_spec: dict,
        workdir: Path,
        iter_id: int,
        mode: str,
        *,
        previous_generator_result: dict | None = None,
        previous_tester_result: dict | None = None,
        previous_verifier_result: dict | None = None,
        previous_challenger_result: dict | None = None,
    ) -> str:
        constraints = compiled_spec.get("constraints") or "No explicit constraints were provided."
        bootstrap_guidance = ""
        action_guidance = (
            "This role must end with a concrete attempt, not only repo inspection.\n"
            "Once you have enough context to act, prefer making a focused change and/or running the most relevant existing verification, build, benchmark, or diagnosis command in the workdir.\n"
            "If the repository already contains a project-owned script that directly measures the goal, prefer using it to establish evidence in this iteration.\n"
            "If you launch a long-running project-owned command, do not wait idly for stdout alone. While it runs, inspect fresh status files, logs, reports, and intermediate artifacts so you can tell healthy progress from a harness defect.\n"
            "If those observations reveal a real process defect in the owned evaluation flow (for example stale progress snapshots, ineffective timeouts, misleading status reporting, or broken report generation), fixing that defect is in scope before the benchmark fully finishes.\n"
            "For benchmark-driven goals, prefer one real end-to-end run plus targeted harness fixes over many ad hoc spot checks.\n"
            "Do not spend the whole turn only reading files unless you are blocked by missing information that truly cannot be resolved any other way.\n\n"
        )
        if iter_id == 0 and self._is_bootstrap_workspace(workdir):
            bootstrap_guidance = (
                "Workspace state:\n"
                "Only the spec is present right now, so this iteration should bootstrap the first implementation.\n"
                "Create the smallest runnable prototype in this round instead of spending the whole turn on planning.\n"
                "Because the workspace is essentially empty, it is safe to add the first app files now; this is not permission to wipe or reset a non-empty project.\n"
                "Prefer a minimal static entry point plus tiny supporting files when needed.\n\n"
            )
        prior_iteration_feedback = self._generator_prior_iteration_feedback(
            iter_id,
            previous_generator_result=previous_generator_result,
            previous_tester_result=previous_tester_result,
            previous_verifier_result=previous_verifier_result,
            previous_challenger_result=previous_challenger_result,
        )
        return (
            "You are the Generator role inside Liminal.\n"
            "Goal: improve the workspace to satisfy the spec with one coherent change direction.\n"
            f"Iteration: {iter_id}\n"
            f"Mode: {mode}\n"
            f"Check mode: {compiled_spec.get('check_mode', 'specified')}\n"
            "You may edit files inside the workdir. Do not write into .liminal except for explicitly requested outputs.\n"
            "Treat existing non-.liminal files as user-owned. Never wipe the whole workdir, bulk-delete existing files, or reset the project from scratch.\n"
            "Prefer targeted in-place edits and additive changes. Delete a file only when that deletion is narrowly necessary to your change.\n"
            f"{action_guidance}"
            f"{bootstrap_guidance}"
            f"{prior_iteration_feedback}"
            f"Spec goal:\n{compiled_spec['goal']}\n\n"
            f"Checks:\n{self._render_checks(compiled_spec['checks'])}\n\n"
            f"Constraints:\n{constraints}\n\n"
            "Return JSON with attempted, abandoned, assumption, summary, and changed_files."
        )

    def _generator_prior_iteration_feedback(
        self,
        iter_id: int,
        *,
        previous_generator_result: dict | None = None,
        previous_tester_result: dict | None = None,
        previous_verifier_result: dict | None = None,
        previous_challenger_result: dict | None = None,
    ) -> str:
        if iter_id <= 0:
            return ""
        lines = ["Previous iteration evidence:"]
        if previous_generator_result:
            lines.append(
                f"- Last attempted: {self._truncate_text(previous_generator_result.get('attempted') or previous_generator_result.get('summary'), 220) or 'none'}"
            )
        if previous_tester_result:
            failed_items = list(previous_tester_result.get("failed_items", []))
            lines.append(
                f"- Tester observations: {self._truncate_text(previous_tester_result.get('tester_observations'), 220) or 'none'}"
            )
            lines.append(f"- Non-passing items last round: {self._format_failure_refs(failed_items)}")
        if previous_verifier_result:
            lines.append(
                f"- Verifier decision: {self._truncate_text(previous_verifier_result.get('decision_summary'), 240) or 'none'}"
            )
            lines.append(
                f"- Previous composite score: `{previous_verifier_result.get('composite_score', 'n/a')}`"
            )
            lines.append(
                "- Failed checks last round: "
                f"{self._format_inline_code_list(list(previous_verifier_result.get('failed_check_titles', []) or previous_verifier_result.get('failed_check_ids', [])), empty='none', limit=4)}"
            )
            lines.append(
                "- Next actions from verifier: "
                f"{self._format_inline_code_list(list(previous_verifier_result.get('next_actions', [])), empty='none', limit=4)}"
            )
        if previous_challenger_result:
            lines.append(
                f"- Challenger recommended shift: {self._truncate_text((previous_challenger_result.get('analysis') or {}).get('recommended_shift'), 220) or 'none'}"
            )
            lines.append(
                f"- Challenger seed question: {self._truncate_text(previous_challenger_result.get('seed_question'), 220) or 'none'}"
            )
        lines.append("Use this evidence as your starting point for the next focused improvement. Do not restart from scratch.")
        return "\n".join(lines) + "\n\n"

    def _tester_prompt(self, compiled_spec: dict, iter_id: int, mode: str) -> str:
        checks = json.dumps(compiled_spec["checks"], ensure_ascii=False, indent=2)
        return (
            "You are the Tester role inside Liminal.\n"
            "Inspect the workdir, run the most relevant commands, and evaluate the listed checks.\n"
            "Do not edit source files.\n"
            "Keep notes concise and evidence-focused. Prefer concrete commands, files, and observed outputs over restating the whole spec.\n"
            "When fresh project-owned benchmark artifacts already exist, inspect them first and reuse them as primary evidence before rerunning an expensive end-to-end flow.\n"
            "If a long-running evaluation appears stalled, confirm that with live status files, logs, or preserved artifacts instead of guessing from silent stdout alone.\n"
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
            "Keep the verdict concise and tied to direct evidence. Do not rewrite the whole spec as policy prose.\n"
            "When the main evidence comes from a project-owned benchmark or harness, treat those artifacts as primary evidence.\n"
            "Distinguish product or knowledge failures from harness-process defects, and surface harness defects as first-class failures when they block trustworthy evaluation.\n"
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

    def _capture_workspace_manifest(self, workdir: Path) -> dict:
        files = list(self._iter_user_workspace_files(workdir))
        return {
            "captured_at": utc_now(),
            "file_count": len(files),
            "files": files,
        }

    def _iter_user_workspace_files(self, workdir: Path):
        ignored_dirs = {".git", ".liminal", ".venv", "venv", "node_modules", "dist", "build", "__pycache__"}
        ignored_files = {".DS_Store"}
        for root, dirs, files in os.walk(workdir):
            dirs[:] = [name for name in dirs if name not in ignored_dirs]
            for filename in sorted(files):
                if filename in ignored_files:
                    continue
                yield (Path(root) / filename).relative_to(workdir).as_posix()

    def _enforce_workspace_safety(self, run: dict, run_dir: Path, iter_id: int, *, role: str) -> None:
        baseline = read_json(run_dir / "workspace_baseline.json")
        baseline_files = set((baseline or {}).get("files") or [])
        if not baseline_files:
            return
        current_files = set(self._iter_user_workspace_files(Path(run["workdir"])))
        deleted_original = sorted(path for path in baseline_files if path not in current_files)
        if not deleted_original:
            return

        deleted_count = len(deleted_original)
        baseline_count = len(baseline_files)
        remaining_original = baseline_count - deleted_count
        deleted_ratio = deleted_count / baseline_count if baseline_count else 0.0
        destructive = False
        if remaining_original == 0:
            destructive = True
        elif deleted_count >= 3 and deleted_ratio >= 0.8:
            destructive = True
        elif deleted_count >= 20 and deleted_ratio >= 0.5:
            destructive = True

        if not destructive:
            return

        payload = {
            "iter": iter_id,
            "role": role,
            "baseline_file_count": baseline_count,
            "remaining_original_file_count": remaining_original,
            "deleted_original_count": deleted_count,
            "deleted_original_paths": deleted_original,
            "deleted_ratio": round(deleted_ratio, 4),
        }
        write_json(run_dir / "workspace_guard.json", payload)
        self.repository.append_event(
            run["id"],
            "workspace_guard_triggered",
            payload,
            role=role,
        )
        raise WorkspaceSafetyError(
            role=role,
            deleted_paths=deleted_original,
            baseline_count=baseline_count,
            current_count=remaining_original,
        )

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
