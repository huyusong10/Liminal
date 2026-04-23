from __future__ import annotations

import logging

from loopora.db_shared import logger
from loopora.diagnostics import log_event
from loopora.utils import utc_now


class RepositoryRoleDefinitionRecordsMixin:
    def create_role_definition(self, payload: dict) -> dict:
        now = utc_now()
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO role_definitions (
                    id, name, description, archetype, prompt_ref, prompt_markdown,
                    executor_kind, executor_mode, command_cli, command_args_text, model, reasoning_effort,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["id"],
                    payload["name"],
                    payload.get("description", ""),
                    payload["archetype"],
                    payload["prompt_ref"],
                    payload["prompt_markdown"],
                    payload.get("executor_kind", "codex"),
                    payload.get("executor_mode", "preset"),
                    payload.get("command_cli", "codex"),
                    payload.get("command_args_text", ""),
                    payload.get("model", ""),
                    payload.get("reasoning_effort", "medium"),
                    now,
                    now,
                ),
            )
        role_definition = self.get_role_definition(payload["id"])
        log_event(
            logger,
            logging.INFO,
            "db.role_definition.created",
            "Persisted role definition",
            role_definition_id=payload["id"],
            archetype=payload["archetype"],
            executor_kind=payload.get("executor_kind", "codex"),
            role_name=payload["name"],
        )
        return role_definition

    def update_role_definition(self, role_definition_id: str, payload: dict) -> dict | None:
        now = utc_now()
        with self.transaction() as connection:
            row = connection.execute("SELECT 1 FROM role_definitions WHERE id = ?", (role_definition_id,)).fetchone()
            if row is None:
                return None
            connection.execute(
                """
                UPDATE role_definitions
                SET name = ?, description = ?, archetype = ?, prompt_ref = ?, prompt_markdown = ?,
                    executor_kind = ?, executor_mode = ?, command_cli = ?, command_args_text = ?, model = ?, reasoning_effort = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    payload["name"],
                    payload.get("description", ""),
                    payload["archetype"],
                    payload["prompt_ref"],
                    payload["prompt_markdown"],
                    payload.get("executor_kind", "codex"),
                    payload.get("executor_mode", "preset"),
                    payload.get("command_cli", "codex"),
                    payload.get("command_args_text", ""),
                    payload.get("model", ""),
                    payload.get("reasoning_effort", "medium"),
                    now,
                    role_definition_id,
                ),
            )
        role_definition = self.get_role_definition(role_definition_id)
        log_event(
            logger,
            logging.INFO,
            "db.role_definition.updated",
            "Updated role definition",
            role_definition_id=role_definition_id,
            archetype=payload["archetype"],
            executor_kind=payload.get("executor_kind", "codex"),
            role_name=payload["name"],
        )
        return role_definition

    def get_role_definition(self, role_definition_id: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM role_definitions WHERE id = ?", (role_definition_id,)).fetchone()
        return self._decode_row(row) if row else None

    def list_role_definitions(self) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM role_definitions ORDER BY updated_at DESC, created_at DESC").fetchall()
        return [self._decode_row(row) for row in rows]

    def delete_role_definition(self, role_definition_id: str) -> bool:
        with self.transaction() as connection:
            row = connection.execute("SELECT 1 FROM role_definitions WHERE id = ?", (role_definition_id,)).fetchone()
            if row is None:
                return False
            connection.execute("DELETE FROM role_definitions WHERE id = ?", (role_definition_id,))
        log_event(
            logger,
            logging.INFO,
            "db.role_definition.deleted",
            "Deleted role definition",
            role_definition_id=role_definition_id,
        )
        return True
