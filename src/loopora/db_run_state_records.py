from __future__ import annotations

import json
import logging

from loopora.db_shared import logger
from loopora.diagnostics import log_event
from loopora.utils import utc_now


class RepositoryRunStateRecordsMixin:
    def update_run(
        self,
        run_id: str,
        *,
        status: str | None = None,
        current_iter: int | None = None,
        active_role: str | None = None,
        runner_pid: int | None = None,
        child_pid: int | None = None,
        started_at: str | None = None,
        finished_at: str | None = None,
        error_message: str | None = None,
        last_verdict: dict | None = None,
        compiled_spec: dict | None = None,
        summary_md: str | None = None,
        clear_child_pid: bool = False,
    ) -> dict:
        updates: dict[str, object] = {"updated_at": utc_now()}
        if status is not None:
            updates["status"] = status
        if current_iter is not None:
            updates["current_iter"] = current_iter
        if active_role is not None:
            updates["active_role"] = active_role
        if runner_pid is not None:
            updates["runner_pid"] = runner_pid
        if child_pid is not None:
            updates["child_pid"] = child_pid
        if clear_child_pid:
            updates["child_pid"] = None
        if started_at is not None:
            updates["started_at"] = started_at
        if finished_at is not None:
            updates["finished_at"] = finished_at
        if error_message is not None:
            updates["error_message"] = error_message
        if last_verdict is not None:
            updates["last_verdict_json"] = json.dumps(last_verdict, ensure_ascii=False)
        if compiled_spec is not None:
            updates["compiled_spec_json"] = json.dumps(compiled_spec, ensure_ascii=False)
        if summary_md is not None:
            updates["summary_md"] = summary_md

        assignments = ", ".join(f"{column} = ?" for column in updates)
        values = list(updates.values()) + [run_id]
        with self.transaction() as connection:
            connection.execute(f"UPDATE loop_runs SET {assignments} WHERE id = ?", values)
            row = connection.execute("SELECT * FROM loop_runs WHERE id = ?", (run_id,)).fetchone()
            if row:
                connection.execute(
                    "UPDATE loop_definitions SET updated_at = ? WHERE id = ?",
                    (utc_now(), row["loop_id"]),
                )
        decoded = self._decode_row(row) if row else {}
        interesting_fields = {
            key: updates[key]
            for key in (
                "status",
                "current_iter",
                "active_role",
                "runner_pid",
                "child_pid",
                "started_at",
                "finished_at",
                "error_message",
            )
            if key in updates
        }
        if decoded and interesting_fields:
            log_event(
                logger,
                logging.INFO,
                "db.run.updated",
                "Persisted run state update",
                run_id=run_id,
                loop_id=decoded.get("loop_id"),
                workdir=decoded.get("workdir"),
                **interesting_fields,
            )
        return decoded

    def request_stop(self, run_id: str) -> dict | None:
        with self.transaction() as connection:
            connection.execute(
                "UPDATE loop_runs SET stop_requested = 1, updated_at = ? WHERE id = ?",
                (utc_now(), run_id),
            )
            row = connection.execute("SELECT * FROM loop_runs WHERE id = ?", (run_id,)).fetchone()
        decoded = self._decode_row(row) if row else None
        if decoded:
            log_event(
                logger,
                logging.INFO,
                "db.run.stop_requested",
                "Persisted stop request for run",
                run_id=run_id,
                loop_id=decoded.get("loop_id"),
                workdir=decoded.get("workdir"),
            )
        return decoded

    def should_stop(self, run_id: str) -> bool:
        with self._connect() as connection:
            row = connection.execute("SELECT stop_requested FROM loop_runs WHERE id = ?", (run_id,)).fetchone()
        return bool(row["stop_requested"]) if row else True

    def active_run_count(self) -> int:
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM loop_runs WHERE status = 'running'").fetchone()
        return int(row["count"]) if row else 0
