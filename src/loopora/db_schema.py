from __future__ import annotations

import json
import logging
import sqlite3
from collections import defaultdict

from loopora.db_shared import logger
from loopora.diagnostics import log_event
from loopora.utils import utc_now


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
                    task_verdict_json TEXT,
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

                CREATE TABLE IF NOT EXISTS run_takeaway_projections (
                    run_id TEXT NOT NULL REFERENCES loop_runs(id) ON DELETE CASCADE,
                    source_event_id INTEGER NOT NULL REFERENCES run_events(id) ON DELETE CASCADE,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (run_id, source_event_id)
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

                CREATE TABLE IF NOT EXISTS bundle_asset_ownership (
                    bundle_id TEXT NOT NULL REFERENCES bundle_definitions(id) ON DELETE CASCADE,
                    asset_type TEXT NOT NULL CHECK (asset_type IN ('loop', 'orchestration', 'role_definition')),
                    asset_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (bundle_id, asset_type, asset_id),
                    UNIQUE (asset_type, asset_id)
                );

                CREATE TABLE IF NOT EXISTS local_asset_roots (
                    resource_type TEXT NOT NULL,
                    resource_id TEXT NOT NULL,
                    path TEXT NOT NULL,
                    workdir TEXT NOT NULL DEFAULT '',
                    owner_id TEXT NOT NULL DEFAULT '',
                    state TEXT NOT NULL DEFAULT 'active' CHECK (state IN ('active', 'cleaned', 'orphaned')),
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (resource_type, resource_id, path)
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
                    alignment_stage TEXT NOT NULL DEFAULT 'clarifying',
                    working_agreement_json TEXT NOT NULL DEFAULT '{}',
                    executor_session_ref_json TEXT NOT NULL DEFAULT '{}',
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

                CREATE INDEX IF NOT EXISTS idx_run_takeaway_projections_cutoff
                    ON run_takeaway_projections(run_id, source_event_id DESC);
                CREATE INDEX IF NOT EXISTS idx_bundle_asset_ownership_bundle
                    ON bundle_asset_ownership(bundle_id);
                CREATE INDEX IF NOT EXISTS idx_local_asset_roots_lookup
                    ON local_asset_roots(resource_type, resource_id, state);
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
            self._ensure_column(connection, "loop_runs", "task_verdict_json", "TEXT")
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
            self._ensure_column(connection, "alignment_sessions", "alignment_stage", "TEXT NOT NULL DEFAULT 'clarifying'")
            self._ensure_column(connection, "alignment_sessions", "working_agreement_json", "TEXT NOT NULL DEFAULT '{}'")
            self._ensure_column(connection, "alignment_sessions", "executor_session_ref_json", "TEXT NOT NULL DEFAULT '{}'")
            self._ensure_column(connection, "alignment_sessions", "linked_bundle_id", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "alignment_sessions", "linked_loop_id", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "alignment_sessions", "linked_run_id", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "alignment_sessions", "active_child_pid", "INTEGER")
            self._ensure_column(connection, "alignment_sessions", "stop_requested", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(connection, "alignment_sessions", "repair_attempts", "INTEGER NOT NULL DEFAULT 0")
            self._backfill_bundle_asset_ownership(connection)
            self._backfill_local_asset_roots(connection)
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

    @staticmethod
    def _bundle_asset_rows_from_record(bundle: sqlite3.Row) -> list[tuple[str, str, str]]:
        bundle_id = str(bundle["id"] or "").strip()
        rows: list[tuple[str, str, str]] = []
        loop_id = str(bundle["loop_id"] or "").strip()
        if loop_id:
            rows.append((bundle_id, "loop", loop_id))
        orchestration_id = str(bundle["orchestration_id"] or "").strip()
        if orchestration_id:
            rows.append((bundle_id, "orchestration", orchestration_id))
        try:
            role_ids = json.loads(str(bundle["role_definition_ids_json"] or "[]"))
        except json.JSONDecodeError:
            role_ids = []
        for role_id in role_ids if isinstance(role_ids, list) else []:
            normalized = str(role_id or "").strip()
            if normalized:
                rows.append((bundle_id, "role_definition", normalized))
        return rows

    @classmethod
    def _backfill_bundle_asset_ownership(cls, connection: sqlite3.Connection) -> None:
        bundles = connection.execute("SELECT * FROM bundle_definitions ORDER BY created_at ASC").fetchall()
        if not bundles:
            return
        candidate_owners: dict[tuple[str, str], list[str]] = defaultdict(list)
        for bundle in bundles:
            for bundle_id, asset_type, asset_id in cls._bundle_asset_rows_from_record(bundle):
                if cls._bundle_asset_exists(connection, asset_type, asset_id):
                    candidate_owners[(asset_type, asset_id)].append(bundle_id)
        now = utc_now()
        for (asset_type, asset_id), bundle_ids in sorted(candidate_owners.items()):
            unique_bundle_ids = sorted(set(bundle_ids))
            if len(unique_bundle_ids) != 1:
                connection.execute(
                    "DELETE FROM bundle_asset_ownership WHERE asset_type = ? AND asset_id = ?",
                    (asset_type, asset_id),
                )
                log_event(
                    logger,
                    logging.WARNING,
                    "db.bundle_ownership.backfill_conflict",
                    "Skipped conflicting bundle asset ownership during migration",
                    asset_type=asset_type,
                    asset_id=asset_id,
                    bundle_ids=unique_bundle_ids,
                )
                continue
            connection.execute(
                """
                INSERT OR IGNORE INTO bundle_asset_ownership (bundle_id, asset_type, asset_id, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (unique_bundle_ids[0], asset_type, asset_id, now),
            )

    @staticmethod
    def _bundle_asset_exists(connection: sqlite3.Connection, asset_type: str, asset_id: str) -> bool:
        table_by_type = {
            "loop": "loop_definitions",
            "orchestration": "orchestration_definitions",
            "role_definition": "role_definitions",
        }
        table = table_by_type.get(asset_type)
        if table is None:
            return False
        row = connection.execute(f"SELECT 1 FROM {table} WHERE id = ?", (asset_id,)).fetchone()
        return row is not None

    @staticmethod
    def _backfill_local_asset_roots(connection: sqlite3.Connection) -> None:
        from loopora.branding import state_dir_for_workdir
        from loopora.settings import app_home

        now = utc_now()
        run_rows = connection.execute("SELECT id, loop_id, workdir, runs_dir FROM loop_runs").fetchall()
        for run in run_rows:
            runs_dir = str(run["runs_dir"] or "").strip()
            if not runs_dir:
                continue
            connection.execute(
                """
                INSERT OR IGNORE INTO local_asset_roots
                    (resource_type, resource_id, path, workdir, owner_id, state, updated_at)
                VALUES ('run', ?, ?, ?, ?, 'active', ?)
                """,
                (run["id"], runs_dir, str(run["workdir"] or ""), str(run["loop_id"] or ""), now),
            )

        bundle_rows = connection.execute("SELECT id, workdir FROM bundle_definitions").fetchall()
        for bundle in bundle_rows:
            connection.execute(
                """
                INSERT OR IGNORE INTO local_asset_roots
                    (resource_type, resource_id, path, workdir, owner_id, state, updated_at)
                VALUES ('bundle', ?, ?, ?, ?, 'active', ?)
                """,
                (bundle["id"], str(app_home() / "bundles" / str(bundle["id"])), str(bundle["workdir"] or ""), bundle["id"], now),
            )

        session_rows = connection.execute("SELECT id, workdir FROM alignment_sessions").fetchall()
        for session in session_rows:
            session_id = str(session["id"] or "").strip()
            workdir = str(session["workdir"] or "").strip()
            root = state_dir_for_workdir(workdir) / "alignment_sessions" / session_id
            connection.execute(
                """
                INSERT OR IGNORE INTO local_asset_roots
                    (resource_type, resource_id, path, workdir, owner_id, state, updated_at)
                VALUES ('alignment_session', ?, ?, ?, ?, 'active', ?)
                """,
                (session_id, str(root), workdir, session_id, now),
            )
