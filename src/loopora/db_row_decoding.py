from __future__ import annotations

import json
import logging
import sqlite3

from loopora.diagnostics import log_event, log_exception
from loopora.db_shared import logger


_JSON_COLUMN_TYPES: dict[str, type[dict] | type[list]] = {
    "compiled_spec_json": dict,
    "role_models_json": dict,
    "workflow_json": dict,
    "prompt_files_json": dict,
    "last_verdict_json": dict,
    "task_verdict_json": dict,
    "payload_json": dict,
    "role_definition_ids_json": list,
    "transcript_json": list,
    "validation_json": dict,
    "working_agreement_json": dict,
    "executor_session_ref_json": dict,
}


class RepositoryRowDecodingMixin:
    @staticmethod
    def _default_json_column_value(column: str) -> dict | list:
        if RepositoryRowDecodingMixin._expected_json_column_type(column) is list:
            return []
        return {}

    @staticmethod
    def _expected_json_column_type(column: str) -> type[dict] | type[list]:
        return _JSON_COLUMN_TYPES.get(column, dict)

    @staticmethod
    def _decode_json_column(row_id: object, column: str, raw_value: object) -> object:
        default_value = RepositoryRowDecodingMixin._default_json_column_value(column)
        if raw_value is None or raw_value == "":
            return default_value
        try:
            decoded = json.loads(str(raw_value))
        except json.JSONDecodeError as exc:
            log_exception(
                logger,
                "db.row.decode_json_failed",
                "Failed to decode persisted JSON column; falling back to the column default",
                error=exc,
                row_id=row_id,
                column=column,
                default_type=type(default_value).__name__,
            )
            return default_value
        expected_type = RepositoryRowDecodingMixin._expected_json_column_type(column)
        if not isinstance(decoded, expected_type):
            log_event(
                logger,
                logging.WARNING,
                "db.row.decode_json_shape_mismatch",
                "Decoded persisted JSON column with unexpected shape; falling back to the column default",
                row_id=row_id,
                column=column,
                expected_type=expected_type.__name__,
                actual_type=type(decoded).__name__,
            )
            return default_value
        return decoded

    @staticmethod
    def _decode_row(row: sqlite3.Row | None) -> dict:
        if row is None:
            return {}
        payload = dict(row)
        for key in _JSON_COLUMN_TYPES:
            if key in payload:
                payload[key] = RepositoryRowDecodingMixin._decode_json_column(payload.get("id"), key, payload[key])
        if "payload_json" in payload:
            payload["payload"] = payload.pop("payload_json")
        if "transcript_json" in payload:
            payload["transcript"] = payload.pop("transcript_json")
        if "validation_json" in payload:
            payload["validation"] = payload.pop("validation_json")
        if "working_agreement_json" in payload:
            payload["working_agreement"] = payload.pop("working_agreement_json")
        if "executor_session_ref_json" in payload:
            payload["executor_session_ref"] = payload.pop("executor_session_ref_json")
        payload["stop_requested"] = bool(payload.get("stop_requested", 0))
        return payload
