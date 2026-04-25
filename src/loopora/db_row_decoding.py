from __future__ import annotations

import json
import sqlite3

from loopora.diagnostics import log_exception
from loopora.db_shared import logger


class RepositoryRowDecodingMixin:
    @staticmethod
    def _decode_json_column(row_id: object, column: str, raw_value: object) -> object:
        if not raw_value:
            return raw_value
        try:
            return json.loads(str(raw_value))
        except json.JSONDecodeError as exc:
            log_exception(
                logger,
                "db.row.decode_json_failed",
                "Failed to decode persisted JSON column; falling back to an empty object",
                error=exc,
                row_id=row_id,
                column=column,
            )
            return {}

    @staticmethod
    def _decode_row(row: sqlite3.Row | None) -> dict:
        if row is None:
            return {}
        payload = dict(row)
        for key in (
            "compiled_spec_json",
            "role_models_json",
            "workflow_json",
            "prompt_files_json",
            "last_verdict_json",
            "payload_json",
            "role_definition_ids_json",
            "transcript_json",
            "validation_json",
        ):
            if key in payload and payload[key]:
                payload[key] = RepositoryRowDecodingMixin._decode_json_column(payload.get("id"), key, payload[key])
        if "payload_json" in payload:
            payload["payload"] = payload.pop("payload_json")
        if "transcript_json" in payload:
            payload["transcript"] = payload.pop("transcript_json")
        if "validation_json" in payload:
            payload["validation"] = payload.pop("validation_json")
        payload["stop_requested"] = bool(payload.get("stop_requested", 0))
        return payload
