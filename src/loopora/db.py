from __future__ import annotations

import logging
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from loopora.db_schema import RepositorySchemaMixin
from loopora.diagnostics import get_logger, log_event, log_exception
from loopora.db_asset_records import RepositoryAssetRecordsMixin
from loopora.db_definition_records import RepositoryDefinitionRecordsMixin
from loopora.db_row_decoding import RepositoryRowDecodingMixin
from loopora.db_runtime_state import RepositoryRuntimeStateMixin
from loopora.run_artifacts import append_jsonl_with_mirrors

logger = get_logger(__name__)


class LooporaRepository(
    RepositorySchemaMixin,
    RepositoryRuntimeStateMixin,
    RepositoryDefinitionRecordsMixin,
    RepositoryAssetRecordsMixin,
    RepositoryRowDecodingMixin,
):
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
