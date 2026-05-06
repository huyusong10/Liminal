from __future__ import annotations

import itertools
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loopora.diagnostics import get_logger, log_event, log_exception
from loopora.executor import ExecutionStopped
from loopora.recovery import RetryConfig
from loopora.service_iteration_reporting import IterationReportContext, IterationSummaryRequest
from loopora.service_role_execution import IterationRoleRunRequest, RoleExecutionRequest
from loopora.service_run_finalization import TerminalRunFinalizationRequest
from loopora.service_types import (
    LooporaError,
    LooporaNotFoundError,
    RoleExecutionError,
    StopRequested,
    WorkspaceSafetyError,
    normalize_completion_mode,
)
from loopora.stagnation import StagnationUpdateRequest, update_stagnation
from loopora.utils import append_jsonl, read_json, utc_now

logger = get_logger(__name__)


@dataclass
class LegacyExecutionContext:
    run: dict
    run_dir: Path
    executor: Any
    compiled_spec: dict
    retry_config: RetryConfig
    stagnation: dict
    metrics_history_path: Path
    completion_mode: str
    iteration_interval_seconds: float


@dataclass
class LegacyExecutionState:
    last_iter_id: int = -1
    last_generator_result: dict | None = None
    last_tester_result: dict | None = None
    last_verifier_result: dict | None = None
    last_challenger_result: dict | None = None
    last_generator_mode: str = "default"
    last_tester_mode: str = "default"
    last_verifier_mode: str = "default"


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

        return self._execute_legacy_run(run_id, run, run_dir)

    def _execute_legacy_run(self, run_id: str, run: dict, run_dir: Path) -> dict:
        try:
            run = self._legacy_run_after_queue_wait(run_id)
            if run["status"] == "stopped":
                return run

            context = self._prepare_legacy_execution_context(run_id, run, run_dir)
            return self._execute_legacy_iteration_loop(run_id, context)
        except (StopRequested, ExecutionStopped):
            return self._handle_legacy_run_stopped(run_id, run, run_dir)
        except RoleExecutionError as exc:
            return self._handle_legacy_role_execution_error(run_id, run, run_dir, exc)
        except WorkspaceSafetyError as exc:
            return self._handle_legacy_workspace_safety_error(run_id, run, run_dir, exc)
        except Exception as exc:
            return self._handle_legacy_run_crash(run_id, run, run_dir, exc)
        finally:
            self._cleanup_run_execution(run_id, run, phase="run")

    def _legacy_run_after_queue_wait(self, run_id: str) -> dict:
        self.repository.update_run(run_id, runner_pid=os.getpid())
        self._wait_for_slot(run_id)
        run = self.repository.get_run(run_id)
        if not run:
            raise LooporaNotFoundError(f"unknown run after queue wait: {run_id}")
        return run

    def _prepare_legacy_execution_context(
        self, run_id: str, run: dict, run_dir: Path
    ) -> LegacyExecutionContext:
        executor = self.executor_factory()
        retry_config = RetryConfig(max_retries=run["max_role_retries"])
        metrics_history_path = run_dir / "metrics_history.jsonl"
        metrics_history_path.touch(exist_ok=True)

        self.append_run_event(run_id, "run_started", {"status": "running"})
        self._write_summary(run_id, "running", "Resolving checks for this run.")
        compiled_spec = self._resolve_run_checks(
            run,
            executor,
            run["compiled_spec_json"],
            run_dir,
            retry_config,
        )
        self._write_summary(run_id, "running", "Waiting for the first iteration to complete.")
        return LegacyExecutionContext(
            run=run,
            run_dir=run_dir,
            executor=executor,
            compiled_spec=compiled_spec,
            retry_config=retry_config,
            stagnation=read_json(run_dir / "stagnation.json"),
            metrics_history_path=metrics_history_path,
            completion_mode=normalize_completion_mode(run.get("completion_mode", "gatekeeper")),
            iteration_interval_seconds=float(run.get("iteration_interval_seconds", 0.0) or 0.0),
        )

    def _execute_legacy_iteration_loop(
        self, run_id: str, context: LegacyExecutionContext
    ) -> dict:
        state = LegacyExecutionState()
        iteration_source = itertools.count() if context.run["max_iters"] == 0 else range(context.run["max_iters"])
        for iter_id in iteration_source:
            summary = self._run_legacy_iteration(run_id, context, state, iter_id)
            finished = self._finalize_legacy_gatekeeper_success(run_id, context, state, summary)
            if finished is not None:
                return finished
            if self._should_pause_legacy_iteration(context, iter_id):
                self._pause_between_iterations(run_id, context.iteration_interval_seconds, iter_id)

        return self._finalize_legacy_iteration_exhaustion(run_id, context, state)

    def _run_legacy_iteration(
        self,
        run_id: str,
        context: LegacyExecutionContext,
        state: LegacyExecutionState,
        iter_id: int,
    ) -> str:
        state.last_iter_id = iter_id
        self._ensure_not_stopped(run_id)
        self.repository.update_run(run_id, current_iter=iter_id)
        generator_mode = {"value": "default"}
        tester_mode = {"value": "default"}
        verifier_mode = {"value": "default"}

        generator_result = self._execute_legacy_generator(run_id, context, state, iter_id, generator_mode)
        tester_result = self._execute_legacy_tester(run_id, context, iter_id, tester_mode)
        previous_composite = (
            state.last_verifier_result["composite_score"] if state.last_verifier_result is not None else None
        )
        verifier_result = self._execute_legacy_verifier(
            run_id,
            context,
            iter_id,
            verifier_mode,
            tester_result,
        )
        context.stagnation = self._update_legacy_stagnation(context, iter_id, verifier_result)
        challenger_result = self._execute_legacy_challenger_if_needed(run_id, context, iter_id)
        self._write_json(context.run_dir / "stagnation.json", context.stagnation)
        self._record_legacy_iteration_metrics(context, iter_id, verifier_result, previous_composite)

        iteration_report = IterationReportContext(
            iter_id=iter_id,
            generator_result=generator_result,
            tester_result=tester_result,
            verifier_result=verifier_result,
            stagnation=context.stagnation,
            generator_mode=generator_mode["value"],
            tester_mode=tester_mode["value"],
            verifier_mode=verifier_mode["value"],
            previous_composite=previous_composite,
            challenger_result=challenger_result,
        )
        append_jsonl(context.run_dir / "iteration_log.jsonl", self._build_iteration_log_entry(iteration_report))
        summary = self._build_summary(
            IterationSummaryRequest(
                run=context.run,
                compiled_spec=context.compiled_spec,
                report=iteration_report,
            )
        )
        self._write_summary(run_id, "running", summary)
        state.last_generator_result = generator_result
        state.last_tester_result = tester_result
        state.last_verifier_result = verifier_result
        state.last_challenger_result = challenger_result
        state.last_generator_mode = generator_mode["value"]
        state.last_tester_mode = tester_mode["value"]
        state.last_verifier_mode = verifier_mode["value"]
        return summary

    def _execute_legacy_generator(
        self,
        run_id: str,
        context: LegacyExecutionContext,
        state: LegacyExecutionState,
        iter_id: int,
        generator_mode: dict,
    ) -> dict:
        generator_result = self._execute_role(
            RoleExecutionRequest(
                run_id=run_id,
                iter_id=iter_id,
                role="generator",
                fn=lambda iter_id=iter_id, generator_mode=generator_mode: self._run_generator(
                    IterationRoleRunRequest(
                        executor=context.executor,
                        run=context.run,
                        compiled_spec=context.compiled_spec,
                        run_dir=context.run_dir,
                        iter_id=iter_id,
                        mode=generator_mode["value"],
                        previous_generator_result=state.last_generator_result,
                        previous_tester_result=state.last_tester_result,
                        previous_verifier_result=state.last_verifier_result,
                        previous_challenger_result=state.last_challenger_result,
                    )
                ),
                retry_config=context.retry_config,
                degrade_once=lambda iter_id=iter_id, generator_mode=generator_mode: self._set_mode(
                    run_id, iter_id, "generator", generator_mode, "conservative_changes"
                ),
            ),
        )
        append_jsonl(
            context.run_dir / "iteration_log.jsonl",
            self._build_generator_log_entry(iter_id, generator_result, generator_mode["value"]),
        )
        self._enforce_workspace_safety(context.run, context.run_dir, iter_id, role="generator")
        return generator_result

    def _execute_legacy_tester(
        self,
        run_id: str,
        context: LegacyExecutionContext,
        iter_id: int,
        tester_mode: dict,
    ) -> dict:
        tester_result = self._execute_role(
            RoleExecutionRequest(
                run_id=run_id,
                iter_id=iter_id,
                role="tester",
                fn=lambda iter_id=iter_id, tester_mode=tester_mode: self._run_tester(
                    IterationRoleRunRequest(
                        executor=context.executor,
                        run=context.run,
                        compiled_spec=context.compiled_spec,
                        run_dir=context.run_dir,
                        iter_id=iter_id,
                        mode=tester_mode["value"],
                    )
                ),
                retry_config=context.retry_config,
                degrade_once=lambda iter_id=iter_id, tester_mode=tester_mode: self._set_mode(
                    run_id, iter_id, "tester", tester_mode, "skip_dynamic_checks"
                ),
            ),
        )
        tester_result = self._enrich_tester_result(tester_result)
        self._write_json(context.run_dir / "tester_output.json", tester_result)
        self._enforce_workspace_safety(context.run, context.run_dir, iter_id, role="tester")
        return tester_result

    def _execute_legacy_verifier(
        self,
        run_id: str,
        context: LegacyExecutionContext,
        iter_id: int,
        verifier_mode: dict,
        tester_result: dict,
    ) -> dict:
        verifier_result = self._execute_role(
            RoleExecutionRequest(
                run_id=run_id,
                iter_id=iter_id,
                role="verifier",
                fn=lambda iter_id=iter_id, verifier_mode=verifier_mode: self._run_verifier(
                    IterationRoleRunRequest(
                        executor=context.executor,
                        run=context.run,
                        compiled_spec=context.compiled_spec,
                        run_dir=context.run_dir,
                        iter_id=iter_id,
                        mode=verifier_mode["value"],
                        tester_output=tester_result,
                    )
                ),
                retry_config=context.retry_config,
                degrade_once=lambda iter_id=iter_id, verifier_mode=verifier_mode: self._set_mode(
                    run_id,
                    iter_id,
                    "verifier",
                    verifier_mode,
                    "strict_minimal_validation",
                ),
            ),
        )
        verifier_result = self._enrich_verifier_result(verifier_result, context.compiled_spec, tester_result)
        self._write_json(context.run_dir / "verifier_verdict.json", verifier_result)
        self.repository.update_run(run_id, last_verdict=verifier_result)
        return verifier_result

    def _update_legacy_stagnation(
        self,
        context: LegacyExecutionContext,
        iter_id: int,
        verifier_result: dict,
    ) -> dict:
        return update_stagnation(
            StagnationUpdateRequest(
                stagnation=context.stagnation,
                composite=verifier_result["composite_score"],
                current_iter=iter_id,
                delta_threshold=context.run["delta_threshold"],
                trigger_window=context.run["trigger_window"],
                regression_window=context.run["regression_window"],
            )
        )

    def _execute_legacy_challenger_if_needed(
        self,
        run_id: str,
        context: LegacyExecutionContext,
        iter_id: int,
    ) -> dict | None:
        if context.stagnation["stagnation_mode"] not in {"plateau", "regression"}:
            return None
        challenger_result = self._execute_role(
            RoleExecutionRequest(
                run_id=run_id,
                iter_id=iter_id,
                role="challenger",
                fn=lambda iter_id=iter_id, stagnation=context.stagnation: self._run_challenger(
                    IterationRoleRunRequest(
                        executor=context.executor,
                        run=context.run,
                        compiled_spec=context.compiled_spec,
                        run_dir=context.run_dir,
                        iter_id=iter_id,
                        stagnation=stagnation,
                    )
                ),
                retry_config=context.retry_config,
            ),
        )
        context.stagnation.setdefault("challenger_triggered_at_iters", []).append(iter_id)
        self._write_json(context.run_dir / "challenger_seed.json", challenger_result)
        self.append_run_event(
            run_id,
            "challenger_done",
            {"iter": iter_id, "mode": challenger_result["mode"]},
            role="challenger",
        )
        return challenger_result

    @staticmethod
    def _should_pause_legacy_iteration(context: LegacyExecutionContext, iter_id: int) -> bool:
        return context.iteration_interval_seconds > 0 and (
            context.run["max_iters"] == 0 or iter_id < context.run["max_iters"] - 1
        )

    def _record_legacy_iteration_metrics(
        self,
        context: LegacyExecutionContext,
        iter_id: int,
        verifier_result: dict,
        previous_composite: float | None,
    ) -> None:
        append_jsonl(
            context.metrics_history_path,
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
                "stagnation_mode": context.stagnation["stagnation_mode"],
            },
        )

    def _finalize_legacy_gatekeeper_success(
        self,
        run_id: str,
        context: LegacyExecutionContext,
        state: LegacyExecutionState,
        summary: str,
    ) -> dict | None:
        if context.completion_mode != "gatekeeper" or not state.last_verifier_result["passed"]:
            return None
        finished = self._finalize_terminal_run(
            TerminalRunFinalizationRequest(
                run_id=run_id,
                run_dir=context.run_dir,
                status="succeeded",
                summary=summary,
                last_verdict=state.last_verifier_result,
                final_reason="gatekeeper_passed",
            )
        )
        self.append_run_event(run_id, "run_finished", {"status": "succeeded", "iter": state.last_iter_id})
        log_event(
            logger,
            logging.INFO,
            "service.run.execution.finished",
            "Run finished successfully",
            **self._run_log_context(
                context.run,
                status="succeeded",
                iter=state.last_iter_id,
                reason="gatekeeper_passed",
            ),
        )
        return finished

    def _finalize_legacy_iteration_exhaustion(
        self,
        run_id: str,
        context: LegacyExecutionContext,
        state: LegacyExecutionState,
    ) -> dict:
        if context.run["max_iters"] == 0 or state.last_verifier_result is None:
            raise LooporaError(f"run {run_id} exited without completing an iteration")
        summary = self._build_summary(
            IterationSummaryRequest(
                run=context.run,
                compiled_spec=context.compiled_spec,
                report=IterationReportContext(
                    iter_id=state.last_iter_id,
                    generator_result=state.last_generator_result or {},
                    tester_result=state.last_tester_result or {},
                    verifier_result=state.last_verifier_result,
                    stagnation=context.stagnation,
                    generator_mode=state.last_generator_mode,
                    tester_mode=state.last_tester_mode,
                    verifier_mode=state.last_verifier_mode,
                    previous_composite=None,
                    challenger_result=state.last_challenger_result,
                ),
                exhausted=True,
            )
        )
        status = "succeeded" if context.completion_mode == "rounds" else "failed"
        reason = "rounds_completed" if context.completion_mode == "rounds" else "max_iters_exhausted"
        finished = self._finalize_terminal_run(
            TerminalRunFinalizationRequest(
                run_id=run_id,
                run_dir=context.run_dir,
                status=status,
                summary=summary,
                final_reason=reason,
            )
        )
        self.append_run_event(run_id, "run_finished", {"status": status, "reason": reason})
        log_event(
            logger,
            logging.INFO,
            "service.run.execution.finished",
            "Run reached its planned completion boundary",
            **self._run_log_context(
                context.run,
                status=status,
                iter=state.last_iter_id,
                reason=reason,
            ),
        )
        return finished

    def _handle_legacy_run_stopped(self, run_id: str, run: dict, run_dir: Path) -> dict:
        summary = "# Loopora Run Summary\n\nStopped by user.\n"
        stopped = self._finalize_terminal_run(
            TerminalRunFinalizationRequest(
                run_id=run_id,
                run_dir=run_dir,
                status="stopped",
                summary=summary,
                final_reason="stopped",
            )
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

    def _handle_legacy_role_execution_error(
        self, run_id: str, run: dict, run_dir: Path, exc: RoleExecutionError
    ) -> dict:
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
            TerminalRunFinalizationRequest(
                run_id=run_id,
                run_dir=run_dir,
                status="failed",
                summary=summary,
                error_message=error_text,
                last_verdict=verdict,
                final_reason="role_execution_abort",
            )
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

    def _handle_legacy_workspace_safety_error(
        self, run_id: str, run: dict, run_dir: Path, exc: WorkspaceSafetyError
    ) -> dict:
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
            TerminalRunFinalizationRequest(
                run_id=run_id,
                run_dir=run_dir,
                status="failed",
                summary=summary,
                error_message=error_text,
                last_verdict=verdict,
                final_reason="workspace_safety_guard",
            )
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

    def _handle_legacy_run_crash(self, run_id: str, run: dict, run_dir: Path, exc: Exception) -> dict:
        error_text = str(exc)
        log_exception(
            logger,
            "service.run.execution.crashed",
            "Run crashed unexpectedly",
            error=exc,
            **self._run_log_context(run),
        )
        return self._finalize_crashed_run(run_id, run, run_dir, error_text=error_text)
