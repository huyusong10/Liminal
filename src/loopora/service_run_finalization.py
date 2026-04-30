from __future__ import annotations

from pathlib import Path

from loopora.diagnostics import get_logger, log_exception
from loopora.task_verdicts import build_task_verdict
from loopora.utils import utc_now, write_json

logger = get_logger(__name__)


class ServiceRunFinalizationMixin:
    def _write_summary(self, run_id: str, status: str, body: str) -> None:
        run = self.get_run(run_id)
        summary = body if body.startswith("#") else f"# Loopora Run Summary\n\nStatus: {status}\n\n{body}\n"
        self._persist_summary_file(Path(run["runs_dir"]), summary)
        self.repository.update_run(run_id, summary_md=summary)

    def _persist_summary_file(self, run_dir: Path, summary: str) -> None:
        run_dir.mkdir(parents=True, exist_ok=True)
        try:
            (run_dir / "summary.md").write_text(summary, encoding="utf-8")
        except OSError:
            log_exception(
                logger,
                "service.run.summary.persist_failed",
                "Failed to persist run summary file",
                runs_dir=run_dir,
            )

    def _write_run_verdict_files(self, run_dir: Path, verdict: dict, *, include_gatekeeper: bool = False) -> None:
        if include_gatekeeper:
            write_json(run_dir / "gatekeeper_verdict.json", verdict)
        write_json(run_dir / "verifier_verdict.json", verdict)

    def _append_run_aborted_event(
        self,
        run_id: str,
        *,
        role: str | None,
        attempts: int,
        degraded: bool,
        error_text: str,
    ) -> None:
        self.append_run_event(
            run_id,
            "run_aborted",
            {
                "role": role,
                "attempts": attempts,
                "degraded": degraded,
                "error": error_text,
            },
        )

    def _finalize_terminal_run(
        self,
        run_id: str,
        run_dir: Path,
        *,
        status: str,
        summary: str,
        error_message: str | None = None,
        last_verdict: dict | None = None,
        final_reason: str = "",
        hydrate: bool = False,
    ) -> dict:
        self._persist_summary_file(run_dir, summary)
        existing_run = self.repository.get_run(run_id) or {}
        task_verdict = build_task_verdict(
            {
                **existing_run,
                "status": status,
                "last_verdict_json": last_verdict
                if last_verdict is not None
                else existing_run.get("last_verdict_json"),
            },
            run_dir=run_dir,
            final_reason=final_reason,
        )
        result = self.repository.update_run(
            run_id,
            status=status,
            finished_at=utc_now(),
            error_message=error_message,
            last_verdict=last_verdict,
            task_verdict=task_verdict,
            summary_md=summary,
        )
        return self._hydrate_run_files(result) if hydrate else result

    def _finalize_crashed_run(
        self,
        run_id: str,
        run: dict,
        run_dir: Path,
        *,
        error_text: str,
        hydrate: bool = False,
    ) -> dict:
        summary = (
            "# Loopora Run Summary\n\n"
            "Execution crashed unexpectedly.\n\n"
            f"Reason: `{error_text}`.\n"
        )
        self._persist_summary_file(run_dir, summary)
        try:
            task_verdict = build_task_verdict(
                {**run, "status": "failed"},
                run_dir=run_dir,
                final_reason="crashed",
            )
            failed = self.repository.update_run(
                run_id,
                status="failed",
                finished_at=utc_now(),
                error_message=error_text,
                task_verdict=task_verdict,
                summary_md=summary,
            )
        except Exception:
            log_exception(
                logger,
                "service.run.execution.crash_state_persist_failed",
                "Failed to persist crashed run state",
                **self._run_log_context(run),
            )
            return {
                **run,
                "status": "failed",
                "finished_at": utc_now(),
                "error_message": error_text,
                "summary_md": summary,
            }
        try:
            self._append_run_aborted_event(
                run_id,
                role=failed.get("active_role"),
                attempts=1,
                degraded=False,
                error_text=error_text,
            )
        except Exception:
            log_exception(
                logger,
                "service.run.execution.crash_event_append_failed",
                "Failed to append crash event after a run crash",
                **self._run_log_context(run),
            )
        return self._hydrate_run_files(failed) if hydrate else failed

    def _cleanup_run_execution(self, run_id: str, run: dict | None, *, phase: str) -> None:
        self._mark_run_inactive(run_id)
        try:
            self.repository.release_run_slot(run_id)
        except Exception:
            log_exception(
                logger,
                "service.run.slot_release_failed",
                f"Failed to release run slot during {phase} cleanup",
                run_id=run_id,
                loop_id=run.get("loop_id") if run else None,
                workdir=run.get("workdir") if run else None,
            )
        self._threads.pop(run_id, None)
