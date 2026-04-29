from __future__ import annotations

import logging
from pathlib import Path

from loopora.diagnostics import get_logger, log_event, log_exception
from loopora.executor import ExecutionStopped
from loopora.service_types import RoleExecutionError, StopRequested, WorkspaceSafetyError

logger = get_logger(__name__)


class ServiceWorkflowFailureHandlingMixin:
    def _handle_workflow_exhaustion(
        self,
        run_id: str,
        run: dict,
        run_dir: Path,
        *,
        completion_mode: str,
        last_iter_id: int,
        summary: str,
    ) -> dict:
        final_status = "succeeded" if completion_mode == "rounds" else "failed"
        final_reason = "rounds_completed" if completion_mode == "rounds" else "max_iters_exhausted"
        finished = self._finalize_terminal_run(
            run_id,
            run_dir,
            status=final_status,
            summary=summary,
            final_reason=final_reason,
            hydrate=True,
        )
        self.repository.append_event(
            run_id,
            "run_finished",
            {"status": final_status, "reason": final_reason, "iter": last_iter_id},
        )
        log_event(
            logger,
            logging.INFO,
            "service.run.execution.finished",
            "Workflow run reached its final state",
            **self._run_log_context(
                run,
                status=final_status,
                iter=last_iter_id,
                reason=final_reason,
            ),
        )
        return finished

    def _handle_workflow_stop(self, run_id: str, run: dict, run_dir: Path) -> dict:
        summary = "# Loopora Run Summary\n\nStopped by user.\n"
        stopped = self._finalize_terminal_run(
            run_id,
            run_dir,
            status="stopped",
            summary=summary,
            final_reason="stopped",
            hydrate=True,
        )
        self.repository.append_event(run_id, "run_finished", {"status": "stopped"})
        log_event(
            logger,
            logging.INFO,
            "service.run.execution.stopped",
            "Workflow run stopped before completion",
            **self._run_log_context(run, status="stopped"),
        )
        return stopped

    def _handle_workflow_role_execution_error(
        self,
        run_id: str,
        run: dict,
        run_dir: Path,
        exc: RoleExecutionError,
    ) -> dict:
        error_text = str(exc.result.error) if exc.result.error else str(exc)
        verdict = {
            "passed": False,
            "decision_summary": "A workflow step aborted before the run could finish.",
            "composite_score": 0.0,
            "metrics": [],
            "metric_scores": {},
            "blocking_issues": ["role_execution_abort"],
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
            "feedback_to_builder": "Fix the failing workflow step before retrying.",
            "feedback_to_generator": "Fix the failing workflow step before retrying.",
        }
        self._write_run_verdict_files(run_dir, verdict, include_gatekeeper=True)
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
            hydrate=True,
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
            "Workflow run aborted because a step could not complete successfully",
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

    def _handle_workflow_workspace_safety_error(
        self,
        run_id: str,
        run: dict,
        run_dir: Path,
        exc: WorkspaceSafetyError,
    ) -> dict:
        error_text = str(exc)
        verdict = {
            "passed": False,
            "decision_summary": "The workspace safety guard stopped the run.",
            "composite_score": 0.0,
            "metrics": [],
            "metric_scores": {},
            "blocking_issues": ["workspace_safety_guard"],
            "hard_constraint_violations": ["workspace_safety_guard"],
            "failed_check_ids": [],
            "priority_failures": [
                {
                    "error_code": "WORKSPACE_SAFETY_GUARD",
                    "summary": "The run deleted too many original workspace files and was stopped.",
                }
            ],
            "feedback_to_builder": "Do not bulk-delete existing user files. Prefer narrow in-place edits.",
            "feedback_to_generator": "Do not bulk-delete existing user files. Prefer narrow in-place edits.",
        }
        self._write_run_verdict_files(run_dir, verdict, include_gatekeeper=True)
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
            hydrate=True,
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
            "Workflow run aborted by the workspace safety guard",
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

    def _handle_workflow_unexpected_error(
        self,
        run_id: str,
        run: dict,
        run_dir: Path,
        exc: Exception,
    ) -> dict:
        error_text = str(exc)
        log_exception(
            logger,
            "service.run.execution.crashed",
            "Workflow run crashed unexpectedly",
            error=exc,
            **self._run_log_context(run),
        )
        return self._finalize_crashed_run(run_id, run, run_dir, error_text=error_text, hydrate=True)
