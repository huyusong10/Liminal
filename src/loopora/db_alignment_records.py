from __future__ import annotations

import json
import logging
from pathlib import Path

from loopora.db_shared import logger
from loopora.diagnostics import log_event
from loopora.utils import utc_now


class RepositoryAlignmentRecordsMixin:
    def create_alignment_session(self, payload: dict) -> dict:
        now = utc_now()
        transcript_json = json.dumps(payload.get("transcript", []), ensure_ascii=False)
        validation_json = json.dumps(payload.get("validation", {}), ensure_ascii=False)
        working_agreement_json = json.dumps(payload.get("working_agreement", {}), ensure_ascii=False)
        executor_session_ref_json = json.dumps(payload.get("executor_session_ref", {}), ensure_ascii=False)
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO alignment_sessions (
                    id, status, executor_kind, executor_mode, command_cli, command_args_text,
                    model, reasoning_effort, workdir, bundle_path, transcript_json, validation_json,
                    alignment_stage, working_agreement_json, executor_session_ref_json,
                    linked_bundle_id, linked_loop_id, linked_run_id, active_child_pid, stop_requested,
                    repair_attempts, created_at, updated_at, finished_at, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["id"],
                    payload.get("status", "idle"),
                    payload.get("executor_kind", "codex"),
                    payload.get("executor_mode", "preset"),
                    payload.get("command_cli", ""),
                    payload.get("command_args_text", ""),
                    payload.get("model", ""),
                    payload.get("reasoning_effort", ""),
                    payload["workdir"],
                    payload["bundle_path"],
                    transcript_json,
                    validation_json,
                    payload.get("alignment_stage", "clarifying"),
                    working_agreement_json,
                    executor_session_ref_json,
                    payload.get("linked_bundle_id", ""),
                    payload.get("linked_loop_id", ""),
                    payload.get("linked_run_id", ""),
                    payload.get("active_child_pid"),
                    1 if payload.get("stop_requested") else 0,
                    int(payload.get("repair_attempts", 0) or 0),
                    now,
                    now,
                    payload.get("finished_at"),
                    payload.get("error_message", ""),
                ),
            )
            session_root = self._alignment_event_artifact_root(Path(payload["bundle_path"]))
            connection.execute(
                """
                INSERT INTO local_asset_roots
                    (resource_type, resource_id, path, workdir, owner_id, state, updated_at)
                VALUES ('alignment_session', ?, ?, ?, ?, 'active', ?)
                ON CONFLICT(resource_type, resource_id, path) DO UPDATE SET
                    workdir = excluded.workdir,
                    owner_id = excluded.owner_id,
                    state = 'active',
                    updated_at = excluded.updated_at
                """,
                (
                    payload["id"],
                    str(session_root),
                    payload["workdir"],
                    payload["id"],
                    now,
                ),
            )
        session = self.get_alignment_session(payload["id"])
        log_event(
            logger,
            logging.INFO,
            "db.alignment.created",
            "Persisted alignment session",
            session_id=payload["id"],
            workdir=payload["workdir"],
            status=session.get("status") if session else payload.get("status", "idle"),
        )
        return session

    def get_alignment_session(self, session_id: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM alignment_sessions WHERE id = ?", (session_id,)).fetchone()
        return self._decode_row(row) if row else None

    def update_alignment_session(self, session_id: str, **fields) -> dict:
        updates: dict[str, object] = {"updated_at": utc_now()}
        json_fields = {
            "transcript": "transcript_json",
            "validation": "validation_json",
            "working_agreement": "working_agreement_json",
            "executor_session_ref": "executor_session_ref_json",
        }
        passthrough_fields = {
            "status",
            "executor_kind",
            "executor_mode",
            "command_cli",
            "command_args_text",
            "model",
            "reasoning_effort",
            "workdir",
            "bundle_path",
            "alignment_stage",
            "linked_bundle_id",
            "linked_loop_id",
            "linked_run_id",
            "active_child_pid",
            "repair_attempts",
            "finished_at",
            "error_message",
        }
        for key, column in json_fields.items():
            if key in fields:
                updates[column] = json.dumps(fields[key], ensure_ascii=False)
        for key in passthrough_fields:
            if key in fields:
                updates[key] = fields[key]
        if "stop_requested" in fields:
            updates["stop_requested"] = 1 if fields["stop_requested"] else 0
        if fields.get("clear_active_child_pid"):
            updates["active_child_pid"] = None

        assignments = ", ".join(f"{column} = ?" for column in updates)
        values = list(updates.values()) + [session_id]
        with self.transaction() as connection:
            connection.execute(f"UPDATE alignment_sessions SET {assignments} WHERE id = ?", values)
            row = connection.execute("SELECT * FROM alignment_sessions WHERE id = ?", (session_id,)).fetchone()
        decoded = self._decode_row(row) if row else {}
        interesting = {
            key: value
            for key, value in fields.items()
            if key
            in {
                "status",
                "active_child_pid",
                "linked_bundle_id",
                "linked_loop_id",
                "linked_run_id",
                "repair_attempts",
                "finished_at",
                "error_message",
                "stop_requested",
                "executor_session_ref",
                "alignment_stage",
                "working_agreement",
            }
        }
        if decoded and interesting:
            log_event(
                logger,
                logging.INFO,
                "db.alignment.updated",
                "Persisted alignment session update",
                session_id=session_id,
                workdir=decoded.get("workdir"),
                **interesting,
            )
        return decoded

    def list_alignment_sessions(self, *, limit: int = 30) -> list[dict]:
        safe_limit = max(1, min(int(limit or 30), 100))
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM alignment_sessions
                ORDER BY updated_at DESC, created_at DESC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
        return [self._decode_row(row) for row in rows]

    def list_all_alignment_sessions(self) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM alignment_sessions
                ORDER BY updated_at DESC, created_at DESC
                """
            ).fetchall()
        return [self._decode_row(row) for row in rows]

    def delete_alignment_session(self, session_id: str) -> bool:
        with self.transaction() as connection:
            connection.execute("DELETE FROM alignment_events WHERE session_id = ?", (session_id,))
            cursor = connection.execute("DELETE FROM alignment_sessions WHERE id = ?", (session_id,))
        deleted = cursor.rowcount > 0
        if deleted:
            log_event(
                logger,
                logging.INFO,
                "db.alignment.deleted",
                "Deleted alignment session",
                session_id=session_id,
            )
        return deleted

    def append_alignment_event(self, session_id: str, event_type: str, payload: dict) -> dict:
        now = utc_now()
        payload_json = json.dumps(payload, ensure_ascii=False)
        with self.transaction() as connection:
            cursor = connection.execute(
                """
                INSERT INTO alignment_events (session_id, created_at, event_type, payload_json)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, now, event_type, payload_json),
            )
            row_id = cursor.lastrowid
            session_row = connection.execute(
                "SELECT bundle_path FROM alignment_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
        event = {
            "id": row_id,
            "session_id": session_id,
            "created_at": now,
            "event_type": event_type,
            "payload": payload,
        }
        if session_row:
            self._append_alignment_event_artifact(self._alignment_event_artifact_root(Path(str(session_row["bundle_path"]))), event)
        return event

    @staticmethod
    def _alignment_event_artifact_root(bundle_path: Path) -> Path:
        return bundle_path.parent.parent if bundle_path.parent.name == "artifacts" else bundle_path.parent

    @staticmethod
    def _truncate_alignment_event_artifact_text(value: object, *, limit: int = 2000) -> str:
        text = str(value or "")
        if len(text) <= limit:
            return text
        return text[:limit] + f"\n... [truncated {len(text) - limit} chars]"

    @classmethod
    def _alignment_event_artifact_payload(cls, event: dict) -> dict:
        payload = dict(event.get("payload") or {})
        for key in ("prompt", "json_schema", "bundle_yaml"):
            if key in payload:
                payload[f"{key}_omitted"] = True
                payload.pop(key, None)
        if payload.get("type") == "command" and "message" in payload:
            payload["message"] = cls._truncate_alignment_event_artifact_text(payload["message"], limit=500)
            payload["command_truncated"] = True
        elif "message" in payload:
            payload["message"] = cls._truncate_alignment_event_artifact_text(payload["message"])
        if "error" in payload:
            payload["error"] = cls._truncate_alignment_event_artifact_text(payload["error"])
        return {**event, "payload": payload}

    @classmethod
    def _append_alignment_event_artifact(cls, session_dir: Path, event: dict) -> None:
        try:
            events_dir = session_dir / "events"
            events_dir.mkdir(parents=True, exist_ok=True)
            with (events_dir / "events.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(cls._alignment_event_artifact_payload(event), ensure_ascii=False) + "\n")
        except OSError:
            return

    def list_alignment_events(self, session_id: str, *, after_id: int = 0, limit: int = 200) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM alignment_events
                WHERE session_id = ? AND id > ?
                ORDER BY id ASC
                LIMIT ?
                """,
                (session_id, after_id, limit),
            ).fetchall()
        return [self._decode_row(row) for row in rows]

    def request_alignment_stop(self, session_id: str) -> dict | None:
        with self.transaction() as connection:
            connection.execute(
                "UPDATE alignment_sessions SET stop_requested = 1, updated_at = ? WHERE id = ?",
                (utc_now(), session_id),
            )
            row = connection.execute("SELECT * FROM alignment_sessions WHERE id = ?", (session_id,)).fetchone()
        return self._decode_row(row) if row else None

    def alignment_should_stop(self, session_id: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT stop_requested FROM alignment_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
        return bool(row["stop_requested"]) if row else True
