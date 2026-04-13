from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from liminal.utils import append_jsonl, utc_now


class LiminalRepository:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
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
        with self.transaction() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS loop_definitions (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
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
                    max_iters INTEGER NOT NULL,
                    max_role_retries INTEGER NOT NULL,
                    delta_threshold REAL NOT NULL,
                    trigger_window INTEGER NOT NULL,
                    regression_window INTEGER NOT NULL,
                    role_models_json TEXT NOT NULL,
                    latest_run_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS loop_runs (
                    id TEXT PRIMARY KEY,
                    loop_id TEXT NOT NULL REFERENCES loop_definitions(id),
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
                    max_iters INTEGER NOT NULL,
                    max_role_retries INTEGER NOT NULL,
                    delta_threshold REAL NOT NULL,
                    trigger_window INTEGER NOT NULL,
                    regression_window INTEGER NOT NULL,
                    role_models_json TEXT NOT NULL,
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
                """
            )
            self._ensure_column(connection, "loop_definitions", "executor_kind", "TEXT NOT NULL DEFAULT 'codex'")
            self._ensure_column(connection, "loop_definitions", "executor_mode", "TEXT NOT NULL DEFAULT 'preset'")
            self._ensure_column(connection, "loop_definitions", "command_cli", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "loop_definitions", "command_args_text", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "loop_runs", "executor_kind", "TEXT NOT NULL DEFAULT 'codex'")
            self._ensure_column(connection, "loop_runs", "executor_mode", "TEXT NOT NULL DEFAULT 'preset'")
            self._ensure_column(connection, "loop_runs", "command_cli", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "loop_runs", "command_args_text", "TEXT NOT NULL DEFAULT ''")

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
                    id, name, workdir, spec_path, spec_markdown, compiled_spec_json,
                    executor_kind, executor_mode, command_cli, command_args_text,
                    model, reasoning_effort, max_iters, max_role_retries, delta_threshold,
                    trigger_window, regression_window, role_models_json, latest_run_id,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
                """,
                (
                    payload["id"],
                    payload["name"],
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
                    payload["max_iters"],
                    payload["max_role_retries"],
                    payload["delta_threshold"],
                    payload["trigger_window"],
                    payload["regression_window"],
                    json.dumps(payload.get("role_models", {}), ensure_ascii=False),
                    now,
                    now,
                ),
            )
        return self.get_loop(payload["id"])

    def create_run(self, payload: dict) -> dict:
        now = utc_now()
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO loop_runs (
                    id, loop_id, workdir, spec_path, spec_markdown, compiled_spec_json,
                    executor_kind, executor_mode, command_cli, command_args_text,
                    model, reasoning_effort, max_iters, max_role_retries, delta_threshold,
                    trigger_window, regression_window, role_models_json, status, stop_requested,
                    current_iter, active_role, runner_pid, child_pid, queued_at, started_at,
                    finished_at, error_message, last_verdict_json, summary_md, runs_dir,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, NULL, NULL, NULL, ?, NULL, NULL, NULL, NULL, ?, ?, ?, ?)
                """,
                (
                    payload["id"],
                    payload["loop_id"],
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
                    payload["max_iters"],
                    payload["max_role_retries"],
                    payload["delta_threshold"],
                    payload["trigger_window"],
                    payload["regression_window"],
                    json.dumps(payload.get("role_models", {}), ensure_ascii=False),
                    payload["status"],
                    now,
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
        return self.get_run(payload["id"])

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
            append_jsonl(Path(run["runs_dir"]) / "events.jsonl", record)
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
        return self._decode_row(row) if row else {}

    def request_stop(self, run_id: str) -> dict | None:
        with self.transaction() as connection:
            connection.execute(
                "UPDATE loop_runs SET stop_requested = 1, updated_at = ? WHERE id = ?",
                (utc_now(), run_id),
            )
            row = connection.execute("SELECT * FROM loop_runs WHERE id = ?", (run_id,)).fetchone()
        return self._decode_row(row) if row else None

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
        return True

    def release_run_slot(self, run_id: str) -> None:
        with self.transaction() as connection:
            connection.execute("DELETE FROM workdir_locks WHERE run_id = ?", (run_id,))
            connection.execute(
                "UPDATE loop_runs SET active_role = NULL, runner_pid = NULL, child_pid = NULL, updated_at = ? WHERE id = ?",
                (utc_now(), run_id),
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
        return True

    @staticmethod
    def _decode_row(row: sqlite3.Row | None) -> dict:
        if row is None:
            return {}
        payload = dict(row)
        for key in ("compiled_spec_json", "role_models_json", "last_verdict_json", "payload_json"):
            if key in payload and payload[key]:
                payload[key] = json.loads(payload[key])
        if "payload_json" in payload:
            payload["payload"] = payload.pop("payload_json")
        payload["stop_requested"] = bool(payload.get("stop_requested", 0))
        return payload
