from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from loopora.db_shared import logger
from loopora.diagnostics import log_event
from loopora.utils import utc_now


@dataclass(frozen=True, kw_only=True)
class RunUpdate:
    status: str | None = None
    current_iter: int | None = None
    active_role: str | None = None
    runner_pid: int | None = None
    child_pid: int | None = None
    started_at: str | None = None
    finished_at: str | None = None
    error_message: str | None = None
    last_verdict: dict | None = None
    task_verdict: dict | None = None
    compiled_spec: dict | None = None
    summary_md: str | None = None
    clear_child_pid: bool = False


class RepositoryRunStateRecordsMixin:
    def update_run(
        self,
        run_id: str,
        update: RunUpdate | None = None,
        **raw_update: Any,
    ) -> dict:
        run_update = _coerce_run_update(update, raw_update)
        updates = _run_update_columns(run_update)
        row = self._persist_run_update(run_id, updates)
        decoded = self._decode_row(row) if row else {}
        self._log_run_update(run_id, decoded=decoded, updates=updates)
        return decoded

    def _persist_run_update(self, run_id: str, updates: dict[str, object]) -> object:
        assignments = ", ".join(f"{column} = ?" for column in updates)
        values = [*updates.values(), run_id]
        with self.transaction() as connection:
            connection.execute(f"UPDATE loop_runs SET {assignments} WHERE id = ?", values)
            row = connection.execute("SELECT * FROM loop_runs WHERE id = ?", (run_id,)).fetchone()
            if row:
                connection.execute(
                    "UPDATE loop_definitions SET updated_at = ? WHERE id = ?",
                    (utc_now(), row["loop_id"]),
                )
        return row

    def _log_run_update(self, run_id: str, *, decoded: dict, updates: dict[str, object]) -> None:
        interesting_fields = _interesting_run_update_fields(updates)
        if not decoded or not interesting_fields:
            return
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


def _coerce_run_update(update: RunUpdate | None, raw_update: dict[str, Any]) -> RunUpdate:
    if update is not None and raw_update:
        raise TypeError("run update cannot mix object and keyword fields")
    return update or RunUpdate(**raw_update)


def _run_update_columns(update: RunUpdate) -> dict[str, object]:
    updates: dict[str, object] = {"updated_at": utc_now()}
    for field in (
        "status",
        "current_iter",
        "active_role",
        "runner_pid",
        "child_pid",
        "started_at",
        "finished_at",
        "error_message",
    ):
        value = getattr(update, field)
        if value is not None:
            updates[field] = value
    if update.clear_child_pid:
        updates["child_pid"] = None
    serialized_fields = {
        "last_verdict": "last_verdict_json",
        "task_verdict": "task_verdict_json",
        "compiled_spec": "compiled_spec_json",
    }
    for field, column in serialized_fields.items():
        value = getattr(update, field)
        if value is not None:
            updates[column] = json.dumps(value, ensure_ascii=False)
    if update.summary_md is not None:
        updates["summary_md"] = update.summary_md
    return updates


def _interesting_run_update_fields(updates: Mapping[str, object]) -> dict[str, object]:
    return {
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
