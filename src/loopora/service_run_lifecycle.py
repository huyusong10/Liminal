from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from loopora.branding import state_dir_for_workdir
from loopora.diagnostics import get_logger, log_event, log_exception
from loopora.file_previews import preview_existing_path
from loopora.run_observation_events import PROGRESS_EVENT_TYPES, TAKEAWAY_PROJECTION_EVENT_TYPES, TIMELINE_EVENT_TYPES
from loopora.run_takeaways import build_run_key_takeaways
from loopora.service_cleanup_diagnostics import best_effort_rmtree, record_cleanup_failure
from loopora.service_types import LooporaConflictError, LooporaError, LooporaNotFoundError, TERMINAL_RUN_STATUSES
from loopora.utils import utc_now

logger = get_logger(__name__)


class ServiceRunLifecycleMixin:
    def append_run_event(self, run_id: str, event_type: str, payload: dict, role: str | None = None) -> dict:
        event = self.repository.append_event(run_id, event_type, payload, role=role)
        if event_type in TAKEAWAY_PROJECTION_EVENT_TYPES:
            self._record_run_takeaway_projection_for_event(run_id, int(event.get("id") or 0))
        return event

    def _record_run_takeaway_projection_for_event(self, run_id: str, source_event_id: int) -> None:
        if source_event_id <= 0:
            return
        try:
            run = self.repository.get_run(run_id)
            if not run:
                return
            payload = build_run_key_takeaways(self._hydrate_run_files(run))
            self.repository.record_run_takeaway_projection(run_id, source_event_id, payload)
        except Exception as exc:
            log_exception(
                logger,
                "service.run_takeaway_projection.write_failed",
                "Failed to persist run takeaway projection",
                error=exc,
                run_id=run_id,
                source_event_id=source_event_id,
            )

    def _backfill_missing_run_takeaway_projections(self) -> None:
        if not hasattr(self.repository, "list_terminal_runs_without_takeaway_projection"):
            return
        for run in self.repository.list_terminal_runs_without_takeaway_projection(limit=5000):
            run_id = str(run.get("id") or "").strip()
            if not run_id:
                continue
            try:
                trigger_event_id = self.repository.latest_event_id_for_types(
                    run_id,
                    TAKEAWAY_PROJECTION_EVENT_TYPES,
                )
                latest_event_id = self.repository.latest_event_id(run_id)
                source_event_id = trigger_event_id or latest_event_id
                if source_event_id <= 0:
                    continue
                hydrated = self._hydrate_run_files(run)
                payload = (
                    build_run_key_takeaways(hydrated)
                    if trigger_event_id
                    else self._minimal_run_takeaway_projection(hydrated, source_event_id=source_event_id)
                )
                self.repository.record_run_takeaway_projection(run_id, source_event_id, payload)
            except Exception as exc:
                log_exception(
                    logger,
                    "service.run_takeaway_projection.backfill_failed",
                    "Failed to backfill run takeaway projection",
                    error=exc,
                    run_id=run_id,
                )

    def _reap_terminal_thread_handle(self, run_id: object, *, status: object) -> None:
        normalized_run_id = str(run_id or "").strip()
        normalized_status = str(status or "").strip()
        if not normalized_run_id or normalized_status not in TERMINAL_RUN_STATUSES:
            return
        thread = self._threads.get(normalized_run_id)
        if thread is None:
            return
        if thread.ident == threading.get_ident():
            return
        if thread.is_alive():
            thread.join(timeout=0.1)
        if not thread.is_alive():
            self._threads.pop(normalized_run_id, None)

    def start_run_async(self, run_id: str) -> None:
        self._mark_run_active(run_id)
        thread = threading.Thread(
            target=self.execute_run,
            args=(run_id,),
            daemon=True,
            name=f"run-{run_id}",
        )
        self._threads[run_id] = thread
        try:
            thread.start()
            log_event(
                logger,
                logging.INFO,
                "service.run.dispatched",
                "Dispatched run to a background thread",
                run_id=run_id,
                thread_name=thread.name,
            )
        except Exception:
            self._mark_run_inactive(run_id)
            self._threads.pop(run_id, None)
            raise

    def stop_run(self, run_id: str) -> dict:
        self._reconcile_local_orphaned_runs()
        current = self.repository.get_run(run_id)
        if not current:
            raise LooporaNotFoundError(f"unknown run: {run_id}")
        if current["status"] not in {"queued", "running"}:
            raise LooporaConflictError(f"cannot stop run in status {current['status']}")

        run = self.repository.request_stop(run_id)
        if not run:
            raise LooporaNotFoundError(f"unknown run: {run_id}")
        self.append_run_event(run_id, "stop_requested", {"status": run["status"]})
        self.repository.send_stop_signal(run_id)
        log_event(
            logger,
            logging.INFO,
            "service.run.stop.requested",
            "Requested run stop",
            **self._run_log_context(run, status=run["status"]),
        )
        return run

    def recent_run_events(
        self,
        run_id: str,
        *,
        event_types: Iterable[str] | None = None,
        max_event_id: int | None = None,
        limit: int = 200,
    ) -> list[dict]:
        self._reconcile_local_orphaned_runs()
        if not self.repository.get_run(run_id):
            raise LooporaNotFoundError(f"unknown run: {run_id}")
        return self.repository.list_recent_events(
            run_id,
            event_types=event_types,
            max_event_id=max_event_id,
            limit=limit,
        )

    def latest_run_event_id(self, run_id: str) -> int:
        self._reconcile_local_orphaned_runs()
        if not self.repository.get_run(run_id):
            raise LooporaNotFoundError(f"unknown run: {run_id}")
        return self.repository.latest_event_id(run_id)

    def run_observation_snapshot(self, run_id: str) -> dict:
        self._reconcile_local_orphaned_runs()
        snapshot = self.repository.run_observation_snapshot_rows(
            run_id,
            timeline_event_types=TIMELINE_EVENT_TYPES,
            progress_event_types=PROGRESS_EVENT_TYPES,
            timeline_limit=40,
            console_limit=160,
            progress_limit=2000,
        )
        if snapshot is None:
            raise LooporaNotFoundError(f"unknown run: {run_id}")
        run = self._hydrate_run_files(snapshot["run"])
        key_takeaways = snapshot.get("key_takeaway_projection")
        if not isinstance(key_takeaways, dict) or not key_takeaways:
            key_takeaways = self._minimal_run_takeaway_projection(run, source_event_id=snapshot["latest_event_id"])
        key_takeaways["source_event_id"] = min(
            int(key_takeaways.get("source_event_id") or 0),
            int(snapshot["latest_event_id"] or 0),
        )
        snapshot.pop("key_takeaway_projection", None)
        return {**snapshot, "run": run, "key_takeaways": key_takeaways}

    @staticmethod
    def _minimal_run_takeaway_projection(run: dict, *, source_event_id: int) -> dict:
        task_verdict = run.get("task_verdict") if isinstance(run.get("task_verdict"), dict) else {}
        return {
            "run_status": str(run.get("run_status") or run.get("status") or "").strip(),
            "task_verdict": task_verdict,
            "evidence_buckets": dict(task_verdict.get("buckets") or {}) if isinstance(task_verdict, dict) else {},
            "build_dir": str(Path(str(run.get("workdir") or "")).expanduser().resolve()) if run.get("workdir") else "",
            "log_dir": str(Path(str(run.get("runs_dir") or "")).expanduser().resolve()) if run.get("runs_dir") else "",
            "evidence_count": 0,
            "evidence_coverage": {},
            "iteration_count": 0,
            "role_conclusion_count": 0,
            "latest_display_iter": None,
            "latest_status": str(run.get("status") or "").strip(),
            "latest_summary": str(run.get("summary_md") or "").strip()[:240],
            "iterations": [],
            "source_event_id": int(source_event_id or 0),
        }

    def get_runtime_activity(self) -> dict:
        self._reconcile_local_orphaned_runs()
        active_runs = self.repository.list_active_runs()
        loop_name_by_id = {loop["id"]: loop["name"] for loop in self.repository.list_loops()}
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
        log_event(
            logger,
            logging.INFO,
            "service.run.rerun.requested",
            "Received rerun request for loop",
            loop_id=loop_id,
            background=background,
        )
        run = self.start_run(loop_id)
        if background:
            self.start_run_async(run["id"])
            return run
        return self.execute_run(run["id"])

    def delete_loop(self, loop_id: str, *, allow_bundle_owned: bool = False) -> dict:
        if not allow_bundle_owned and hasattr(self, "_bundle_record_for_loop_id"):
            bundle = self._bundle_record_for_loop_id(loop_id)
            if bundle:
                raise LooporaConflictError(
                    f"loop {loop_id} is managed by bundle {bundle['id']}; delete the bundle instead"
                )
        loop = self.get_loop(loop_id)
        active_runs = [run["id"] for run in loop["runs"] if run["status"] in {"queued", "running"}]
        if active_runs:
            raise LooporaConflictError(f"cannot delete loop with active runs: {', '.join(active_runs)}")

        paths_to_remove = [Path(run["runs_dir"]) for run in loop["runs"]]
        paths_to_remove.append(state_dir_for_workdir(loop["workdir"]) / "loops" / loop_id)

        self.repository.delete_loop(loop_id)
        for path in paths_to_remove:
            best_effort_rmtree(
                path,
                logger,
                operation="loop_artifact_delete",
                owner_id=loop_id,
                workdir=loop["workdir"],
            )
            self._mark_local_asset_cleanup_by_path(path, operation="loop_artifact_delete", owner_id=loop_id)
        self._write_recent_workdirs()
        result = {"id": loop_id, "deleted_runs": len(loop["runs"]), "workdir": loop["workdir"]}
        log_event(
            logger,
            logging.INFO,
            "service.loop.deleted",
            "Deleted loop definition and local artifacts",
            loop_id=loop_id,
            workdir=loop["workdir"],
            deleted_run_count=len(loop["runs"]),
        )
        return result

    def _mark_local_asset_cleanup_by_path(self, path: Path, *, operation: str = "local_asset_cleanup", owner_id: object = "") -> None:
        target = Path(path)
        state = "cleaned" if not target.exists() else "orphaned"
        if hasattr(self.repository, "mark_local_asset_root_state_by_path"):
            try:
                self.repository.mark_local_asset_root_state_by_path(path=target, state=state)
            except Exception as exc:
                record_cleanup_failure(
                    logger,
                    operation=f"{operation}_registry_mark",
                    resource_type="local_asset_root",
                    resource_id=target,
                    owner_id=owner_id,
                    error=exc,
                )

    def _reconcile_stale_runs(self) -> None:
        for run in self.repository.list_active_runs():
            if self._run_process_may_still_be_alive(run):
                continue
            if not self._startup_stale_run_is_recoverable(run):
                continue
            log_event(
                logger,
                logging.WARNING,
                "service.run.recovered_after_startup",
                "Recovered stale run during service startup",
                **self._run_log_context(run, runner_pid=run.get("runner_pid"), status=run.get("status")),
            )
            summary = (
                "# Loopora Run Summary\n\n"
                "This run was marked stopped when Loopora restarted because its previous worker process was no longer alive.\n"
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
            self.append_run_event(
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
        updated_at = self._parse_run_timestamp(
            run.get("updated_at") or run.get("started_at") or run.get("queued_at")
        )
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
        log_event(
            logger,
            logging.WARNING,
            "service.run.recovered_orphan",
            "Recovered local orphaned run after the worker stopped unexpectedly",
            **self._run_log_context(
                run,
                status=run.get("status"),
                runner_pid=run.get("runner_pid"),
                child_pid=run.get("child_pid"),
                updated_at=run.get("updated_at"),
            ),
        )
        summary = (
            "# Loopora Run Summary\n\n"
            "This run was marked failed because the local worker stopped unexpectedly before it could finish cleanly.\n"
        )
        child_pid = run.get("child_pid")
        if child_pid and self._pid_exists(child_pid):
            try:
                os.kill(int(child_pid), 15)
            except OSError:
                log_exception(
                    logger,
                    "service.run.orphan_child_stop_failed",
                    "Failed to stop orphaned child process",
                    run_id=run["id"],
                    loop_id=run.get("loop_id"),
                    workdir=run.get("workdir"),
                    child_pid=child_pid,
                )
        updated = self._finalize_terminal_run(
            run["id"],
            Path(run["runs_dir"]),
            status="failed",
            summary=summary,
            error_message=reason,
            final_reason="orphaned_worker",
        )
        self.repository.release_run_slot(run["id"])
        self._append_run_aborted_event(
            run["id"],
            role=run.get("active_role"),
            attempts=1,
            degraded=False,
            error_text=reason,
        )
        return updated or run

    def _should_recover_local_orphan(self, run: dict) -> bool:
        if run.get("status") not in {"queued", "running"}:
            return False
        if self._is_run_active_locally(run["id"]):
            return False
        if run.get("runner_pid") not in {None, os.getpid()}:
            return False
        updated_at = self._parse_run_timestamp(
            run.get("updated_at") or run.get("started_at") or run.get("queued_at")
        )
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
        base = state_dir_for_workdir(workdir) if root == "loopora" else workdir
        if root == "loopora":
            base.mkdir(parents=True, exist_ok=True)
        base_resolved = base.resolve()
        resolved = (base_resolved / relative_path).resolve()
        if not resolved.is_relative_to(base_resolved):
            raise LooporaError("requested path is outside the allowed root")
        if not resolved.exists():
            raise LooporaError(f"path does not exist: {resolved}")
        return preview_existing_path(base=base, relative_path=relative_path, resolved=resolved)

    def stream_events(self, run_id: str, after_id: int = 0, limit: int = 200) -> list[dict]:
        self._reconcile_local_orphaned_runs()
        if not self.repository.get_run(run_id):
            raise LooporaNotFoundError(f"unknown run: {run_id}")
        return self.repository.list_events(run_id, after_id=after_id, limit=limit)
