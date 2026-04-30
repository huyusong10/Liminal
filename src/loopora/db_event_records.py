from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
import sqlite3

from loopora.db_shared import logger
from loopora.diagnostics import log_exception
from loopora.event_redaction import redact_run_event_payload
from loopora.run_artifacts import RunArtifactLayout
from loopora.utils import utc_now


class RepositoryEventRecordsMixin:
    @staticmethod
    def _recent_event_rows_for_connection(
        connection: sqlite3.Connection,
        run_id: str,
        *,
        event_types: Iterable[str] | None = None,
        max_event_id: int | None = None,
        limit: int = 200,
    ) -> list[sqlite3.Row]:
        normalized_limit = max(0, min(int(limit), 5000))
        if normalized_limit <= 0:
            return []
        types = sorted({str(event_type or "").strip() for event_type in (event_types or []) if str(event_type or "").strip()})
        params: list[object] = [run_id]
        where = "run_id = ?"
        if types:
            placeholders = ", ".join("?" for _ in types)
            where = f"{where} AND event_type IN ({placeholders})"
            params.extend(types)
        if max_event_id is not None:
            where = f"{where} AND id <= ?"
            params.append(max(0, int(max_event_id or 0)))
        params.append(normalized_limit)
        rows = connection.execute(
            f"""
            SELECT * FROM run_events
            WHERE {where}
            ORDER BY id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        return list(reversed(rows))

    def append_event(self, run_id: str, event_type: str, payload: dict, role: str | None = None) -> dict:
        now = utc_now()
        redacted_payload = redact_run_event_payload(event_type, payload)
        payload_json = json.dumps(redacted_payload, ensure_ascii=False)
        with self.transaction() as connection:
            cursor = connection.execute(
                """
                INSERT INTO run_events (run_id, created_at, event_type, role, payload_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (run_id, now, event_type, role, payload_json),
            )
            row_id = cursor.lastrowid
            run = connection.execute("SELECT * FROM loop_runs WHERE id = ?", (run_id,)).fetchone()
        record = {
            "id": row_id,
            "run_id": run_id,
            "created_at": now,
            "event_type": event_type,
            "role": role,
            "payload": redacted_payload,
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

    def list_recent_events(
        self,
        run_id: str,
        *,
        event_types: Iterable[str] | None = None,
        max_event_id: int | None = None,
        limit: int = 200,
    ) -> list[dict]:
        with self._connect() as connection:
            rows = self._recent_event_rows_for_connection(
                connection,
                run_id,
                event_types=event_types,
                max_event_id=max_event_id,
                limit=limit,
            )
        return [self._decode_row(row) for row in rows]

    def latest_event_id(self, run_id: str) -> int:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id FROM run_events
                WHERE run_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (run_id,),
            ).fetchone()
        return int(row["id"]) if row else 0

    def list_run_events_for_redaction_audit(self) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT e.*, r.runs_dir
                FROM run_events e
                JOIN loop_runs r ON r.id = e.run_id
                ORDER BY e.id ASC
                """
            ).fetchall()
        return [self._decode_row(row) for row in rows]

    def update_run_event_payload_for_redaction(self, event_id: int, payload: dict) -> bool:
        payload_json = json.dumps(payload, ensure_ascii=False)
        with self.transaction() as connection:
            cursor = connection.execute(
                "UPDATE run_events SET payload_json = ? WHERE id = ?",
                (payload_json, int(event_id)),
            )
        return cursor.rowcount > 0

    def record_run_takeaway_projection(self, run_id: str, source_event_id: int, payload: dict) -> bool:
        with self.transaction() as connection:
            run = connection.execute("SELECT * FROM loop_runs WHERE id = ?", (run_id,)).fetchone()
            if run is None:
                return False
            self._insert_takeaway_projection_for_connection(
                connection,
                run_id=run_id,
                source_event_id=int(source_event_id),
                payload=payload,
            )
        return True

    @staticmethod
    def _insert_takeaway_projection_for_connection(
        connection: sqlite3.Connection,
        *,
        run_id: str,
        source_event_id: int,
        payload: dict,
    ) -> None:
        projection = dict(payload or {})
        projection["source_event_id"] = int(source_event_id)
        connection.execute(
            """
            INSERT OR REPLACE INTO run_takeaway_projections
                (run_id, source_event_id, payload_json, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (run_id, int(source_event_id), json.dumps(projection, ensure_ascii=False), utc_now()),
        )

    @staticmethod
    def _latest_takeaway_projection_for_connection(
        connection: sqlite3.Connection,
        run_id: str,
        *,
        max_source_event_id: int,
    ) -> dict | None:
        row = connection.execute(
            """
            SELECT * FROM run_takeaway_projections
            WHERE run_id = ? AND source_event_id <= ?
            ORDER BY source_event_id DESC
            LIMIT 1
            """,
            (run_id, int(max_source_event_id)),
        ).fetchone()
        if row is None:
            return None
        try:
            payload = json.loads(str(row["payload_json"] or "{}"))
        except json.JSONDecodeError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        payload["source_event_id"] = int(row["source_event_id"])
        return payload

    def latest_event_id_for_types(self, run_id: str, event_types: Iterable[str]) -> int:
        types = sorted({str(event_type or "").strip() for event_type in event_types if str(event_type or "").strip()})
        if not types:
            return 0
        placeholders = ", ".join("?" for _ in types)
        with self._connect() as connection:
            row = connection.execute(
                f"""
                SELECT id FROM run_events
                WHERE run_id = ? AND event_type IN ({placeholders})
                ORDER BY id DESC
                LIMIT 1
                """,
                [run_id, *types],
            ).fetchone()
        return int(row["id"]) if row else 0

    def run_observation_snapshot_rows(
        self,
        run_id: str,
        *,
        timeline_event_types: Iterable[str],
        progress_event_types: Iterable[str],
        timeline_limit: int = 40,
        console_limit: int = 160,
        progress_limit: int = 2000,
    ) -> dict | None:
        with self._connect() as connection:
            connection.execute("BEGIN")
            try:
                run_row = connection.execute("SELECT * FROM loop_runs WHERE id = ?", (run_id,)).fetchone()
                if run_row is None:
                    connection.rollback()
                    return None
                latest_row = connection.execute(
                    """
                    SELECT id FROM run_events
                    WHERE run_id = ?
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (run_id,),
                ).fetchone()
                latest_event_id = int(latest_row["id"]) if latest_row else 0
                timeline_rows = self._recent_event_rows_for_connection(
                    connection,
                    run_id,
                    event_types=timeline_event_types,
                    max_event_id=latest_event_id,
                    limit=timeline_limit,
                )
                console_rows = self._recent_event_rows_for_connection(
                    connection,
                    run_id,
                    max_event_id=latest_event_id,
                    limit=console_limit,
                )
                progress_rows = self._recent_event_rows_for_connection(
                    connection,
                    run_id,
                    event_types=progress_event_types,
                    max_event_id=latest_event_id,
                    limit=progress_limit,
                )
                key_takeaway_projection = self._latest_takeaway_projection_for_connection(
                    connection,
                    run_id,
                    max_source_event_id=latest_event_id,
                )
                loop_row = connection.execute(
                    "SELECT name FROM loop_definitions WHERE id = ?",
                    (run_row["loop_id"],),
                ).fetchone()
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        run = self._decode_row(run_row)
        if loop_row:
            run["loop_name"] = loop_row["name"]
        return {
            "run": run,
            "latest_event_id": latest_event_id,
            "timeline_events": [self._decode_row(row) for row in timeline_rows],
            "console_events": [self._decode_row(row) for row in console_rows],
            "progress_events": [self._decode_row(row) for row in progress_rows],
            "key_takeaway_projection": key_takeaway_projection,
        }
