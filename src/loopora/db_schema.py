from __future__ import annotations

import logging
import sqlite3

from loopora.db_shared import logger
from loopora.diagnostics import log_event


class RepositorySchemaMixin:
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
                    posture_notes TEXT NOT NULL DEFAULT '',
                    executor_kind TEXT NOT NULL DEFAULT 'codex',
                    executor_mode TEXT NOT NULL DEFAULT 'preset',
                    command_cli TEXT NOT NULL DEFAULT 'codex',
                    command_args_text TEXT NOT NULL DEFAULT '',
                    model TEXT NOT NULL DEFAULT '',
                    reasoning_effort TEXT NOT NULL DEFAULT 'medium',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS bundle_definitions (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    collaboration_summary TEXT NOT NULL DEFAULT '',
                    workdir TEXT NOT NULL DEFAULT '',
                    loop_id TEXT NOT NULL DEFAULT '',
                    orchestration_id TEXT NOT NULL DEFAULT '',
                    role_definition_ids_json TEXT NOT NULL DEFAULT '[]',
                    source_bundle_id TEXT NOT NULL DEFAULT '',
                    revision INTEGER NOT NULL DEFAULT 1,
                    imported_from_path TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS alignment_sessions (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    executor_kind TEXT NOT NULL DEFAULT 'codex',
                    executor_mode TEXT NOT NULL DEFAULT 'preset',
                    command_cli TEXT NOT NULL DEFAULT '',
                    command_args_text TEXT NOT NULL DEFAULT '',
                    model TEXT NOT NULL DEFAULT '',
                    reasoning_effort TEXT NOT NULL DEFAULT 'medium',
                    workdir TEXT NOT NULL,
                    bundle_path TEXT NOT NULL,
                    transcript_json TEXT NOT NULL DEFAULT '[]',
                    validation_json TEXT NOT NULL DEFAULT '{}',
                    linked_bundle_id TEXT NOT NULL DEFAULT '',
                    linked_loop_id TEXT NOT NULL DEFAULT '',
                    linked_run_id TEXT NOT NULL DEFAULT '',
                    active_child_pid INTEGER,
                    stop_requested INTEGER NOT NULL DEFAULT 0,
                    repair_attempts INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    finished_at TEXT,
                    error_message TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS alignment_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL REFERENCES alignment_sessions(id),
                    created_at TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL
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
            self._ensure_column(connection, "role_definitions", "posture_notes", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "role_definitions", "reasoning_effort", "TEXT NOT NULL DEFAULT 'medium'")
            self._ensure_column(connection, "alignment_sessions", "executor_mode", "TEXT NOT NULL DEFAULT 'preset'")
            self._ensure_column(connection, "alignment_sessions", "command_cli", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "alignment_sessions", "command_args_text", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "alignment_sessions", "linked_bundle_id", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "alignment_sessions", "linked_loop_id", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "alignment_sessions", "linked_run_id", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "alignment_sessions", "active_child_pid", "INTEGER")
            self._ensure_column(connection, "alignment_sessions", "stop_requested", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(connection, "alignment_sessions", "repair_attempts", "INTEGER NOT NULL DEFAULT 0")
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
