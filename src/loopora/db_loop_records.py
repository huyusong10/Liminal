from __future__ import annotations

import json
import logging

from loopora.db_shared import logger
from loopora.diagnostics import log_event
from loopora.utils import utc_now


class RepositoryLoopRecordsMixin:
    def create_loop(self, payload: dict) -> dict:
        now = utc_now()
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO loop_definitions (
                    id, name, orchestration_id, orchestration_name, workdir, spec_path, spec_markdown, compiled_spec_json,
                    executor_kind, executor_mode, command_cli, command_args_text,
                    model, reasoning_effort, completion_mode, iteration_interval_seconds,
                    max_iters, max_role_retries, delta_threshold,
                    trigger_window, regression_window, role_models_json, workflow_json, latest_run_id,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
                """,
                (
                    payload["id"],
                    payload["name"],
                    payload.get("orchestration_id", ""),
                    payload.get("orchestration_name", ""),
                    payload["workdir"],
                    payload["spec_path"],
                    payload["spec_markdown"],
                    json.dumps(payload["compiled_spec"], ensure_ascii=False),
                    payload.get("executor_kind", "codex"),
                    payload.get("executor_mode", "preset"),
                    payload.get("command_cli", ""),
                    payload.get("command_args_text", ""),
                    payload["model"],
                    payload["reasoning_effort"],
                    payload.get("completion_mode", "gatekeeper"),
                    payload.get("iteration_interval_seconds", 0.0),
                    payload["max_iters"],
                    payload["max_role_retries"],
                    payload["delta_threshold"],
                    payload["trigger_window"],
                    payload["regression_window"],
                    json.dumps(payload.get("role_models", {}), ensure_ascii=False),
                    json.dumps(payload.get("workflow", {}), ensure_ascii=False),
                    now,
                    now,
                ),
            )
        loop = self.get_loop(payload["id"])
        log_event(
            logger,
            logging.INFO,
            "db.loop.created",
            "Persisted loop definition",
            loop_id=payload["id"],
            orchestration_id=payload.get("orchestration_id", ""),
            workdir=payload["workdir"],
            loop_name=payload["name"],
        )
        return loop

    def get_loop(self, loop_id: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM loop_definitions WHERE id = ?", (loop_id,)).fetchone()
        return self._decode_row(row) if row else None

    def list_loops(self) -> list[dict]:
        query = """
            SELECT
                l.*,
                r.status AS latest_status,
                r.current_iter AS latest_current_iter,
                r.started_at AS latest_started_at,
                r.finished_at AS latest_finished_at,
                r.updated_at AS latest_run_updated_at,
                r.summary_md AS latest_summary_md,
                r.last_verdict_json AS latest_verdict_json
            FROM loop_definitions l
            LEFT JOIN loop_runs r ON r.id = l.latest_run_id
            ORDER BY l.updated_at DESC
        """
        with self._connect() as connection:
            rows = connection.execute(query).fetchall()
        return [self._decode_row(row) for row in rows]

    def delete_loop(self, loop_id: str) -> bool:
        with self.transaction() as connection:
            row = connection.execute("SELECT 1 FROM loop_definitions WHERE id = ?", (loop_id,)).fetchone()
            if row is None:
                return False
            connection.execute(
                "DELETE FROM run_events WHERE run_id IN (SELECT id FROM loop_runs WHERE loop_id = ?)",
                (loop_id,),
            )
            connection.execute(
                "DELETE FROM workdir_locks WHERE run_id IN (SELECT id FROM loop_runs WHERE loop_id = ?)",
                (loop_id,),
            )
            connection.execute("DELETE FROM loop_runs WHERE loop_id = ?", (loop_id,))
            connection.execute("DELETE FROM loop_definitions WHERE id = ?", (loop_id,))
        log_event(
            logger,
            logging.INFO,
            "db.loop.deleted",
            "Deleted loop definition and related records",
            loop_id=loop_id,
        )
        return True
