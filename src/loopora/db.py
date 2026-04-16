from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from loopora.diagnostics import get_logger, log_event, log_exception
from loopora.utils import append_jsonl, utc_now

logger = get_logger(__name__)


class LooporaRepository:
    def __init__(self, path: Path) -> None:
        self.path = path.expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self, *, configure_journal_mode: bool = False) -> sqlite3.Connection:
        for attempt in range(3):
            connection: sqlite3.Connection | None = None
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                connection = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("PRAGMA busy_timeout=30000")
                if configure_journal_mode:
                    connection.execute("PRAGMA journal_mode=WAL").fetchone()
                return connection
            except sqlite3.OperationalError as exc:
                if connection is not None:
                    connection.close()
                retryable = self._is_retryable_connect_error(exc)
                attempt_number = attempt + 1
                if attempt == 2 or not retryable:
                    log_exception(
                        logger,
                        "db.connect.failed",
                        "Database connection failed",
                        error=exc,
                        path=self.path,
                        attempt=attempt_number,
                        configure_journal_mode=configure_journal_mode,
                        retryable=retryable,
                    )
                    raise
                sleep_seconds = 0.1 * attempt_number
                log_event(
                    logger,
                    logging.WARNING,
                    "db.connect.retry",
                    "Retrying database connection after a transient failure",
                    path=self.path,
                    attempt=attempt_number,
                    configure_journal_mode=configure_journal_mode,
                    retryable=True,
                    sleep_seconds=sleep_seconds,
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                )
                time.sleep(sleep_seconds)
        raise AssertionError("sqlite connection retry loop exited unexpectedly")

    @staticmethod
    def _is_retryable_connect_error(exc: sqlite3.OperationalError) -> bool:
        message = str(exc).lower()
        return any(
            marker in message
            for marker in (
                "unable to open database file",
                "database is locked",
                "disk i/o error",
            )
        )

    @contextmanager
    def transaction(self, *, configure_journal_mode: bool = False) -> Iterator[sqlite3.Connection]:
        connection = self._connect(configure_journal_mode=configure_journal_mode)
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _init_db(self) -> None:
        with self.transaction(configure_journal_mode=True) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS loop_definitions (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    orchestration_id TEXT NOT NULL DEFAULT '',
                    orchestration_name TEXT NOT NULL DEFAULT '',
                    workdir TEXT NOT NULL,
                    spec_path TEXT NOT NULL,
                    spec_markdown TEXT NOT NULL,
                    compiled_spec_json TEXT NOT NULL,
                    executor_kind TEXT NOT NULL DEFAULT 'codex',
                    executor_mode TEXT NOT NULL DEFAULT 'preset',
                    command_cli TEXT NOT NULL DEFAULT '',
                    command_args_text TEXT NOT NULL DEFAULT '',
                    model TEXT NOT NULL,
                    reasoning_effort TEXT NOT NULL,
                    completion_mode TEXT NOT NULL DEFAULT 'gatekeeper',
                    iteration_interval_seconds REAL NOT NULL DEFAULT 0,
                    max_iters INTEGER NOT NULL,
                    max_role_retries INTEGER NOT NULL,
                    delta_threshold REAL NOT NULL,
                    trigger_window INTEGER NOT NULL,
                    regression_window INTEGER NOT NULL,
                    role_models_json TEXT NOT NULL,
                    workflow_json TEXT NOT NULL DEFAULT '{}',
                    latest_run_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS loop_runs (
                    id TEXT PRIMARY KEY,
                    loop_id TEXT NOT NULL REFERENCES loop_definitions(id),
                    orchestration_id TEXT NOT NULL DEFAULT '',
                    orchestration_name TEXT NOT NULL DEFAULT '',
                    workdir TEXT NOT NULL,
                    spec_path TEXT NOT NULL,
                    spec_markdown TEXT NOT NULL,
                    compiled_spec_json TEXT NOT NULL,
                    executor_kind TEXT NOT NULL DEFAULT 'codex',
                    executor_mode TEXT NOT NULL DEFAULT 'preset',
                    command_cli TEXT NOT NULL DEFAULT '',
                    command_args_text TEXT NOT NULL DEFAULT '',
                    model TEXT NOT NULL,
                    reasoning_effort TEXT NOT NULL,
                    completion_mode TEXT NOT NULL DEFAULT 'gatekeeper',
                    iteration_interval_seconds REAL NOT NULL DEFAULT 0,
                    max_iters INTEGER NOT NULL,
                    max_role_retries INTEGER NOT NULL,
                    delta_threshold REAL NOT NULL,
                    trigger_window INTEGER NOT NULL,
                    regression_window INTEGER NOT NULL,
                    role_models_json TEXT NOT NULL,
                    workflow_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL,
                    stop_requested INTEGER NOT NULL DEFAULT 0,
                    current_iter INTEGER NOT NULL DEFAULT 0,
                    active_role TEXT,
                    runner_pid INTEGER,
                    child_pid INTEGER,
                    queued_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    error_message TEXT,
                    last_verdict_json TEXT,
                    summary_md TEXT,
                    runs_dir TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS run_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL REFERENCES loop_runs(id),
                    created_at TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    role TEXT,
                    payload_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS workdir_locks (
                    workdir TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES loop_runs(id),
                    acquired_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS orchestration_definitions (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    workflow_json TEXT NOT NULL,
                    prompt_files_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS role_definitions (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    archetype TEXT NOT NULL,
                    prompt_ref TEXT NOT NULL,
                    prompt_markdown TEXT NOT NULL,
                    executor_kind TEXT NOT NULL DEFAULT 'codex',
                    executor_mode TEXT NOT NULL DEFAULT 'preset',
                    command_cli TEXT NOT NULL DEFAULT 'codex',
                    command_args_text TEXT NOT NULL DEFAULT '',
                    model TEXT NOT NULL DEFAULT '',
                    reasoning_effort TEXT NOT NULL DEFAULT 'medium',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            self._ensure_column(connection, "loop_definitions", "orchestration_id", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "loop_definitions", "orchestration_name", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "loop_runs", "orchestration_id", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "loop_runs", "orchestration_name", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "loop_definitions", "executor_kind", "TEXT NOT NULL DEFAULT 'codex'")
            self._ensure_column(connection, "loop_definitions", "executor_mode", "TEXT NOT NULL DEFAULT 'preset'")
            self._ensure_column(connection, "loop_definitions", "command_cli", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "loop_definitions", "command_args_text", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "loop_runs", "executor_kind", "TEXT NOT NULL DEFAULT 'codex'")
            self._ensure_column(connection, "loop_runs", "executor_mode", "TEXT NOT NULL DEFAULT 'preset'")
            self._ensure_column(connection, "loop_runs", "command_cli", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "loop_runs", "command_args_text", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "loop_definitions", "workflow_json", "TEXT NOT NULL DEFAULT '{}'")
            self._ensure_column(connection, "loop_runs", "workflow_json", "TEXT NOT NULL DEFAULT '{}'")
            self._ensure_column(connection, "loop_definitions", "completion_mode", "TEXT NOT NULL DEFAULT 'gatekeeper'")
            self._ensure_column(connection, "loop_runs", "completion_mode", "TEXT NOT NULL DEFAULT 'gatekeeper'")
            self._ensure_column(connection, "loop_definitions", "iteration_interval_seconds", "REAL NOT NULL DEFAULT 0")
            self._ensure_column(connection, "loop_runs", "iteration_interval_seconds", "REAL NOT NULL DEFAULT 0")
            self._ensure_column(connection, "role_definitions", "executor_kind", "TEXT NOT NULL DEFAULT 'codex'")
            self._ensure_column(connection, "role_definitions", "executor_mode", "TEXT NOT NULL DEFAULT 'preset'")
            self._ensure_column(connection, "role_definitions", "command_cli", "TEXT NOT NULL DEFAULT 'codex'")
            self._ensure_column(connection, "role_definitions", "command_args_text", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "role_definitions", "reasoning_effort", "TEXT NOT NULL DEFAULT 'medium'")
        log_event(
            logger,
            logging.INFO,
            "db.schema.ready",
            "Database schema is ready",
            path=self.path,
        )

    @staticmethod
    def _ensure_column(connection: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        columns = {
            row["name"]
            for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

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

    def get_loop(self, loop_id: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM loop_definitions WHERE id = ?", (loop_id,)).fetchone()
        return self._decode_row(row) if row else None

    def get_run(self, run_id: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM loop_runs WHERE id = ?", (run_id,)).fetchone()
        return self._decode_row(row) if row else None

    def get_loop_or_run(self, identifier: str) -> tuple[str, dict] | None:
        if loop := self.get_loop(identifier):
            return "loop", loop
        if run := self.get_run(identifier):
            return "run", run
        return None

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
                append_jsonl(Path(run["runs_dir"]) / "events.jsonl", record)
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
                (now, os.getpid(), now, run_id),
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

    def active_run_count(self) -> int:
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM loop_runs WHERE status = 'running'").fetchone()
        return int(row["count"]) if row else 0

    def send_stop_signal(self, run_id: str) -> bool:
        run = self.get_run(run_id)
        if not run:
            return False
        pid = run.get("child_pid")
        if pid:
            try:
                os.kill(int(pid), 15)
            except ProcessLookupError:
                pass
        log_event(
            logger,
            logging.INFO,
            "db.run.stop_signal_sent",
            "Sent stop signal to the active child process when present",
            run_id=run_id,
            loop_id=run.get("loop_id"),
            workdir=run.get("workdir"),
            child_pid=pid,
        )
        return True

    @staticmethod
    def _decode_row(row: sqlite3.Row | None) -> dict:
        if row is None:
            return {}
        payload = dict(row)
        for key in ("compiled_spec_json", "role_models_json", "workflow_json", "prompt_files_json", "last_verdict_json", "payload_json"):
            if key in payload and payload[key]:
                payload[key] = json.loads(payload[key])
        if "payload_json" in payload:
            payload["payload"] = payload.pop("payload_json")
        payload["stop_requested"] = bool(payload.get("stop_requested", 0))
        return payload
