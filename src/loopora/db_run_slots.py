from __future__ import annotations

import logging

from loopora.db_shared import logger
from loopora.diagnostics import log_event, log_exception
from loopora.utils import utc_now


class RepositoryRunSlotsMixin:
    def has_active_run_for_workdir(self, workdir: str) -> bool:
        query = """
            SELECT 1
            FROM loop_runs
            WHERE workdir = ? AND status IN ('queued', 'running')
            LIMIT 1
        """
        with self._connect() as connection:
            row = connection.execute(query, (workdir,)).fetchone()
        return row is not None

    def claim_run_slot(self, run_id: str, max_concurrent_runs: int) -> bool:
        now = utc_now()
        with self.transaction() as connection:
            run = connection.execute("SELECT * FROM loop_runs WHERE id = ?", (run_id,)).fetchone()
            if run is None:
                return False
            if run["status"] not in {"queued", "draft"}:
                return run["status"] == "running"
            if run["stop_requested"]:
                connection.execute(
                    """
                    UPDATE loop_runs
                    SET status = 'stopped', finished_at = ?, active_role = NULL, runner_pid = NULL, child_pid = NULL, updated_at = ?
                    WHERE id = ?
                    """,
                    (now, now, run_id),
                )
                log_event(
                    logger,
                    logging.INFO,
                    "db.run.slot.skip_stopped",
                    "Skipped slot claim because the run was already asked to stop",
                    run_id=run_id,
                    loop_id=run["loop_id"],
                    workdir=run["workdir"],
                )
                return False

            active_count = connection.execute(
                "SELECT COUNT(*) AS count FROM loop_runs WHERE status = 'running'"
            ).fetchone()["count"]
            if active_count >= max_concurrent_runs:
                return False

            existing_lock = connection.execute(
                "SELECT run_id FROM workdir_locks WHERE workdir = ?",
                (run["workdir"],),
            ).fetchone()
            if existing_lock and existing_lock["run_id"] != run_id:
                return False

            from loopora import db as db_module

            connection.execute(
                """
                INSERT INTO workdir_locks (workdir, run_id, acquired_at)
                VALUES (?, ?, ?)
                ON CONFLICT(workdir) DO UPDATE SET run_id = excluded.run_id, acquired_at = excluded.acquired_at
                """,
                (run["workdir"], run_id, now),
            )
            connection.execute(
                """
                UPDATE loop_runs
                SET status = 'running',
                    started_at = COALESCE(started_at, ?),
                    runner_pid = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (now, db_module.os.getpid(), now, run_id),
            )
        log_event(
            logger,
            logging.INFO,
            "db.run.slot.claimed",
            "Claimed run slot and workdir lock",
            run_id=run_id,
            loop_id=run["loop_id"],
            workdir=run["workdir"],
            max_concurrent_runs=max_concurrent_runs,
        )
        return True

    def release_run_slot(self, run_id: str) -> None:
        run = self.get_run(run_id)
        with self.transaction() as connection:
            connection.execute("DELETE FROM workdir_locks WHERE run_id = ?", (run_id,))
            connection.execute(
                "UPDATE loop_runs SET active_role = NULL, runner_pid = NULL, child_pid = NULL, updated_at = ? WHERE id = ?",
                (utc_now(), run_id),
            )
        if run:
            log_event(
                logger,
                logging.INFO,
                "db.run.slot.released",
                "Released run slot and cleared active runtime markers",
                run_id=run_id,
                loop_id=run.get("loop_id"),
                workdir=run.get("workdir"),
            )

    def send_stop_signal(self, run_id: str) -> bool:
        run = self.get_run(run_id)
        if not run:
            return False
        pid = run.get("child_pid")
        if pid in {None, ""}:
            log_event(
                logger,
                logging.INFO,
                "db.run.stop_signal_skipped",
                "Skipped stop signal because the run has no active child process",
                run_id=run_id,
                loop_id=run.get("loop_id"),
                workdir=run.get("workdir"),
                reason="missing_child_pid",
            )
            return True

        try:
            child_pid = int(pid)
        except (TypeError, ValueError):
            self.update_run(run_id, clear_child_pid=True)
            log_event(
                logger,
                logging.WARNING,
                "db.run.stop_signal_skipped",
                "Skipped stop signal because the recorded child process id is invalid",
                run_id=run_id,
                loop_id=run.get("loop_id"),
                workdir=run.get("workdir"),
                child_pid=pid,
                reason="invalid_child_pid",
            )
            return True

        from loopora import db as db_module

        try:
            db_module.os.kill(child_pid, 15)
        except ProcessLookupError:
            self.update_run(run_id, clear_child_pid=True)
            log_event(
                logger,
                logging.WARNING,
                "db.run.stop_signal_skipped",
                "Skipped stop signal because the child process is no longer running",
                run_id=run_id,
                loop_id=run.get("loop_id"),
                workdir=run.get("workdir"),
                child_pid=child_pid,
                reason="process_not_found",
            )
            return True
        except OSError as exc:
            log_exception(
                logger,
                "db.run.stop_signal_failed",
                "Failed to send stop signal to the active child process",
                error=exc,
                run_id=run_id,
                loop_id=run.get("loop_id"),
                workdir=run.get("workdir"),
                child_pid=child_pid,
            )
            return False

        log_event(
            logger,
            logging.INFO,
            "db.run.stop_signal_sent",
            "Sent stop signal to the active child process",
            run_id=run_id,
            loop_id=run.get("loop_id"),
            workdir=run.get("workdir"),
            child_pid=child_pid,
        )
        return True
