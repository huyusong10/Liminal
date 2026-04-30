from __future__ import annotations

import json
import logging

from loopora.db_shared import logger
from loopora.diagnostics import log_event
from loopora.utils import utc_now


class RepositoryRunRecordsMixin:
    def create_run(self, payload: dict) -> dict:
        now = utc_now()
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO loop_runs (
                    id, loop_id, orchestration_id, orchestration_name, workdir, spec_path, spec_markdown, compiled_spec_json,
                    executor_kind, executor_mode, command_cli, command_args_text,
                    model, reasoning_effort, completion_mode, iteration_interval_seconds,
                    max_iters, max_role_retries, delta_threshold,
                    trigger_window, regression_window, role_models_json, workflow_json, status, stop_requested,
                    current_iter, active_role, runner_pid, child_pid, queued_at, started_at,
                    finished_at, error_message, last_verdict_json, summary_md, runs_dir,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["id"],
                    payload["loop_id"],
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
                    payload["status"],
                    0,
                    0,
                    None,
                    None,
                    None,
                    now,
                    None,
                    None,
                    None,
                    None,
                    payload.get("summary_md", ""),
                    payload["runs_dir"],
                    now,
                    now,
                ),
            )
            connection.execute(
                "UPDATE loop_definitions SET latest_run_id = ?, updated_at = ? WHERE id = ?",
                (payload["id"], now, payload["loop_id"]),
            )
            connection.execute(
                """
                INSERT INTO local_asset_roots
                    (resource_type, resource_id, path, workdir, owner_id, state, updated_at)
                VALUES ('run', ?, ?, ?, ?, 'active', ?)
                ON CONFLICT(resource_type, resource_id, path) DO UPDATE SET
                    workdir = excluded.workdir,
                    owner_id = excluded.owner_id,
                    state = 'active',
                    updated_at = excluded.updated_at
                """,
                (
                    payload["id"],
                    payload["runs_dir"],
                    payload["workdir"],
                    payload["loop_id"],
                    now,
                ),
            )
        run = self.get_run(payload["id"])
        log_event(
            logger,
            logging.INFO,
            "db.run.created",
            "Persisted run record",
            run_id=payload["id"],
            loop_id=payload["loop_id"],
            orchestration_id=payload.get("orchestration_id", ""),
            workdir=payload["workdir"],
            status=payload["status"],
        )
        return run

    def get_run(self, run_id: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM loop_runs WHERE id = ?", (run_id,)).fetchone()
        return self._decode_row(row) if row else None

    def list_runs_for_loop(self, loop_id: str, limit: int = 20) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM loop_runs WHERE loop_id = ? ORDER BY created_at DESC LIMIT ?",
                (loop_id, limit),
            ).fetchall()
        return [self._decode_row(row) for row in rows]

    def list_active_runs(self) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM loop_runs WHERE status IN ('queued', 'running') ORDER BY created_at DESC"
            ).fetchall()
        return [self._decode_row(row) for row in rows]

    def list_terminal_runs_without_takeaway_projection(self, *, limit: int = 5000) -> list[dict]:
        normalized_limit = max(0, min(int(limit), 5000))
        if normalized_limit <= 0:
            return []
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT r.*
                FROM loop_runs r
                WHERE r.status IN ('succeeded', 'failed', 'stopped')
                  AND NOT EXISTS (
                    SELECT 1
                    FROM run_takeaway_projections p
                    WHERE p.run_id = r.id
                  )
                ORDER BY r.created_at DESC
                LIMIT ?
                """,
                (normalized_limit,),
            ).fetchall()
        return [self._decode_row(row) for row in rows]
