from __future__ import annotations

import json
import logging

from loopora.db_shared import logger
from loopora.diagnostics import log_event
from loopora.utils import utc_now


class RepositoryOrchestrationRecordsMixin:
    def create_orchestration(self, payload: dict) -> dict:
        now = utc_now()
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO orchestration_definitions (
                    id, name, description, workflow_json, prompt_files_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["id"],
                    payload["name"],
                    payload.get("description", ""),
                    json.dumps(payload["workflow"], ensure_ascii=False),
                    json.dumps(payload.get("prompt_files", {}), ensure_ascii=False),
                    now,
                    now,
                ),
            )
        orchestration = self.get_orchestration(payload["id"])
        log_event(
            logger,
            logging.INFO,
            "db.orchestration.created",
            "Persisted orchestration definition",
            orchestration_id=payload["id"],
            orchestration_name=payload["name"],
            role_count=len(payload["workflow"].get("roles", [])),
            step_count=len(payload["workflow"].get("steps", [])),
        )
        return orchestration

    def update_orchestration(self, orchestration_id: str, payload: dict) -> dict | None:
        now = utc_now()
        with self.transaction() as connection:
            row = connection.execute("SELECT 1 FROM orchestration_definitions WHERE id = ?", (orchestration_id,)).fetchone()
            if row is None:
                return None
            connection.execute(
                """
                UPDATE orchestration_definitions
                SET name = ?, description = ?, workflow_json = ?, prompt_files_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    payload["name"],
                    payload.get("description", ""),
                    json.dumps(payload["workflow"], ensure_ascii=False),
                    json.dumps(payload.get("prompt_files", {}), ensure_ascii=False),
                    now,
                    orchestration_id,
                ),
            )
        orchestration = self.get_orchestration(orchestration_id)
        log_event(
            logger,
            logging.INFO,
            "db.orchestration.updated",
            "Updated orchestration definition",
            orchestration_id=orchestration_id,
            orchestration_name=payload["name"],
            role_count=len(payload["workflow"].get("roles", [])),
            step_count=len(payload["workflow"].get("steps", [])),
        )
        return orchestration

    def get_orchestration(self, orchestration_id: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM orchestration_definitions WHERE id = ?", (orchestration_id,)).fetchone()
        return self._decode_row(row) if row else None

    def list_orchestrations(self) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM orchestration_definitions ORDER BY updated_at DESC, created_at DESC").fetchall()
        return [self._decode_row(row) for row in rows]

    def delete_orchestration(self, orchestration_id: str) -> bool:
        with self.transaction() as connection:
            row = connection.execute("SELECT 1 FROM orchestration_definitions WHERE id = ?", (orchestration_id,)).fetchone()
            if row is None:
                return False
            connection.execute("DELETE FROM orchestration_definitions WHERE id = ?", (orchestration_id,))
        log_event(
            logger,
            logging.INFO,
            "db.orchestration.deleted",
            "Deleted orchestration definition",
            orchestration_id=orchestration_id,
        )
        return True
