from __future__ import annotations

import itertools
import logging
import os
from pathlib import Path

from loopora.diagnostics import get_logger, log_event, log_exception
from loopora.executor import ExecutionStopped
from loopora.recovery import RetryConfig
from loopora.run_artifacts import INITIAL_STAGNATION_STATE
from loopora.service_types import (
    LooporaError,
    LooporaNotFoundError,
    RoleExecutionError,
    StopRequested,
    WorkspaceSafetyError,
    normalize_completion_mode,
)
from loopora.stagnation import update_stagnation
from loopora.utils import append_jsonl, read_json, utc_now

logger = get_logger(__name__)


class ServiceLegacyExecutionMixin:
    def execute_run(self, run_id: str) -> dict:
        run = self.repository.get_run(run_id)
        if not run:
            raise LooporaNotFoundError(f"unknown run: {run_id}")

        log_event(
            logger,
            logging.INFO,
            "service.run.execution.started",
            "Starting run execution",
            **self._run_log_context(
                run,
                completion_mode=run.get("completion_mode"),
                max_iters=run.get("max_iters"),
            ),
        )
        self._mark_run_active(run_id)
        run_dir = Path(run["runs_dir"])
        workflow = self._normalized_workflow_from_record(run)
        if workflow:
            return self._execute_workflow_run(run_id, run, run_dir, workflow)

        try:
            self.repository.update_run(run_id, runner_pid=os.getpid())
            self._wait_for_slot(run_id)
            run = self.repository.get_run(run_id)
            if not run:
                raise LooporaNotFoundError(f"unknown run after queue wait: {run_id}")
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

            self.append_run_event(run_id, "run_started", {"status": "running"})
            self._write_summary(run_id, "running", "Resolving checks for this run.")
            compiled_spec = self._resolve_run_checks(run, executor, compiled_spec, run_dir, retry_config)
            self._write_summary(run_id, "running", "Waiting for the first iteration to complete.")
            completion_mode = normalize_completion_mode(run.get("completion_mode", "gatekeeper"))
            iteration_interval_seconds = float(run.get("iteration_interval_seconds", 0.0) or 0.0)
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
                    degrade_once=lambda: self._set_mode(
                        run_id, iter_id, "generator", generator_mode, "conservative_changes"
                    ),
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
                    degrade_once=lambda: self._set_mode(
                        run_id, iter_id, "tester", tester_mode, "skip_dynamic_checks"
                    ),
                )
                tester_result = self._enrich_tester_result(tester_result)
                self._write_json(run_dir / "tester_output.json", tester_result)
                self._enforce_workspace_safety(run, run_dir, iter_id, role="tester")

                previous_composite = (
                    last_verifier_result["composite_score"] if last_verifier_result is not None else None
                )
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
                self._write_json(run_dir / "verifier_verdict.json", verifier_result)
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
                    self._write_json(run_dir / "challenger_seed.json", challenger_result)
                    self.append_run_event(
                        run_id,
                        "challenger_done",
                        {"iter": iter_id, "mode": challenger_result["mode"]},
                        role="challenger",
                    )
                else:
                    challenger_result = None
                self._write_json(run_dir / "stagnation.json", stagnation)

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

                if completion_mode == "gatekeeper" and verifier_result["passed"]:
                    finished = self._finalize_terminal_run(
                        run_id,
                        run_dir,
                        status="succeeded",
                        summary=summary,
                        last_verdict=verifier_result,
                        final_reason="gatekeeper_passed",
                    )
                    self.append_run_event(run_id, "run_finished", {"status": "succeeded", "iter": iter_id})
                    log_event(
                        logger,
                        logging.INFO,
                        "service.run.execution.finished",
                        "Run finished successfully",
                        **self._run_log_context(
                            run,
                            status="succeeded",
                            iter=iter_id,
                            reason="gatekeeper_passed",
                        ),
                    )
                    return finished
                if iteration_interval_seconds > 0 and (
                    run["max_iters"] == 0 or iter_id < run["max_iters"] - 1
                ):
                    self._pause_between_iterations(run_id, iteration_interval_seconds, iter_id)

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
                finished = self._finalize_terminal_run(
                    run_id,
                    run_dir,
                    status="succeeded" if completion_mode == "rounds" else "failed",
                    summary=summary,
                    final_reason="rounds_completed" if completion_mode == "rounds" else "max_iters_exhausted",
                )
                self.append_run_event(
                    run_id,
                    "run_finished",
                    {
                        "status": "succeeded" if completion_mode == "rounds" else "failed",
                        "reason": "rounds_completed"
                        if completion_mode == "rounds"
                        else "max_iters_exhausted",
                    },
                )
                log_event(
                    logger,
                    logging.INFO,
                    "service.run.execution.finished",
                    "Run reached its planned completion boundary",
                    **self._run_log_context(
                        run,
                        status="succeeded" if completion_mode == "rounds" else "failed",
                        iter=last_iter_id,
                        reason="rounds_completed"
                        if completion_mode == "rounds"
                        else "max_iters_exhausted",
                    ),
                )
                return finished
            raise LooporaError(f"run {run_id} exited without completing an iteration")
        except (StopRequested, ExecutionStopped):
            summary = "# Loopora Run Summary\n\nStopped by user.\n"
            stopped = self._finalize_terminal_run(
                run_id,
                run_dir,
                status="stopped",
                summary=summary,
                final_reason="stopped",
            )
            self.append_run_event(run_id, "run_finished", {"status": "stopped"})
            log_event(
                logger,
                logging.INFO,
                "service.run.execution.stopped",
                "Run stopped before completion",
                **self._run_log_context(run, status="stopped"),
            )
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
            }
            self._write_run_verdict_files(run_dir, verdict)
            summary = (
                "# Loopora Run Summary\n\n"
                f"Execution failed during `{exc.role}`.\n\n"
                f"Reason: `{error_text}`.\n"
            )
            failed = self._finalize_terminal_run(
                run_id,
                run_dir,
                status="failed",
                summary=summary,
                error_message=error_text,
                last_verdict=verdict,
                final_reason="role_execution_abort",
            )
            self._append_run_aborted_event(
                run_id,
                role=exc.role,
                attempts=exc.result.attempts,
                degraded=exc.result.degraded,
                error_text=error_text,
            )
            log_event(
                logger,
                logging.ERROR,
                "service.run.execution.aborted",
                "Run aborted because a role could not complete successfully",
                **self._run_log_context(
                    run,
                    status="failed",
                    role=exc.role,
                    attempts=exc.result.attempts,
                    degraded=exc.result.degraded,
                    error_message=error_text,
                ),
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
            }
            self._write_run_verdict_files(run_dir, verdict)
            deleted_preview = ", ".join(exc.deleted_paths[:5]) if exc.deleted_paths else "none"
            summary = (
                "# Loopora Run Summary\n\n"
                "Execution stopped by the workspace safety guard.\n\n"
                f"- Original files tracked: `{exc.baseline_count}`\n"
                f"- Original files still present: `{exc.current_count}`\n"
                f"- Deleted original files: `{len(exc.deleted_paths)}`\n"
                f"- Sample deleted paths: `{deleted_preview}`\n"
            )
            failed = self._finalize_terminal_run(
                run_id,
                run_dir,
                status="failed",
                summary=summary,
                error_message=error_text,
                last_verdict=verdict,
                final_reason="workspace_safety_guard",
            )
            self._append_run_aborted_event(
                run_id,
                role=exc.role,
                attempts=1,
                degraded=False,
                error_text=error_text,
            )
            log_event(
                logger,
                logging.ERROR,
                "service.run.execution.workspace_guard_blocked",
                "Run aborted by the workspace safety guard",
                **self._run_log_context(
                    run,
                    status="failed",
                    role=exc.role,
                    deleted_original_count=len(exc.deleted_paths),
                    baseline_file_count=exc.baseline_count,
                    remaining_original_file_count=exc.current_count,
                ),
            )
            return failed
        except Exception as exc:
            error_text = str(exc)
            log_exception(
                logger,
                "service.run.execution.crashed",
                "Run crashed unexpectedly",
                error=exc,
                **self._run_log_context(run),
            )
            return self._finalize_crashed_run(run_id, run, run_dir, error_text=error_text)
        finally:
            self._cleanup_run_execution(run_id, run, phase="run")
