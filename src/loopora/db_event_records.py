from __future__ import annotations

import json
from pathlib import Path

from loopora.db_shared import logger
from loopora.diagnostics import log_exception
from loopora.run_artifacts import RunArtifactLayout
from loopora.utils import utc_now


class RepositoryEventRecordsMixin:
    def append_event(self, run_id: str, event_type: str, payload: dict, role: str | None = None) -> dict:
        now = utc_now()
        payload_json = json.dumps(payload, ensure_ascii=False)
        with self.transaction() as connection:
            cursor = connection.execute(
                """
                INSERT INTO run_events (run_id, created_at, event_type, role, payload_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (run_id, now, event_type, role, payload_json),
            )
            row_id = cursor.lastrowid
            run = connection.execute("SELECT runs_dir FROM loop_runs WHERE id = ?", (run_id,)).fetchone()
        record = {
            "id": row_id,
            "run_id": run_id,
            "created_at": now,
            "event_type": event_type,
            "role": role,
            "payload": payload,
        }
        if run:
            try:
                layout = RunArtifactLayout(Path(run["runs_dir"]))
                from loopora import db as db_module

                db_module.append_jsonl_with_mirrors(
                    layout.timeline_events_path,
                    record,
                    mirror_paths=[layout.legacy_events_path],
                )
            except OSError:
                log_exception(
                    logger,
                    "db.run_event.mirror_failed",
                    "Failed to mirror run event to events.jsonl",
                    run_id=run_id,
                    role=role,
                    event_type=event_type,
                    runs_dir=run["runs_dir"],
                )
        return record

    def list_events(self, run_id: str, *, after_id: int = 0, limit: int = 200) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM run_events
                WHERE run_id = ? AND id > ?
                ORDER BY id ASC
                LIMIT ?
                """,
                (run_id, after_id, limit),
            ).fetchall()
        return [self._decode_row(row) for row in rows]
