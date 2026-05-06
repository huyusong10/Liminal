from __future__ import annotations

import json
import logging

from loopora.diagnostics import get_logger, log_event, log_exception
from loopora.settings import app_home, configure_logging


def _read_service_log_records() -> list[dict]:
    log_path = app_home() / "logs" / "service.log"
    return [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_configure_logging_writes_structured_json_lines() -> None:
    configure_logging()
    logger = get_logger("loopora.tests.diagnostics")

    log_event(
        logger,
        logging.INFO,
        "test.logging.recorded",
        "Structured logging works",
        loop_id="loop_test",
        run_id="run_test",
        detail="ready",
    )

    payload = next(item for item in _read_service_log_records() if item["event"] == "test.logging.recorded")

    assert payload["schema_version"] == 1
    assert payload["component"] == "tests.diagnostics"
    assert payload["loop_id"] == "loop_test"
    assert payload["run_id"] == "run_test"
    assert payload["context"]["detail"] == "ready"


def test_exception_logging_includes_error_payload() -> None:
    configure_logging()
    logger = get_logger("loopora.tests.diagnostics")

    try:
        raise RuntimeError("boom")
    except RuntimeError as exc:
        log_exception(
            logger,
            "test.logging.crashed",
            "Structured exception logging works",
            error=exc,
            loop_id="loop_test",
        )

    payload = next(item for item in _read_service_log_records() if item["event"] == "test.logging.crashed")

    assert payload["loop_id"] == "loop_test"
    assert payload["error"]["type"] == "RuntimeError"
    assert payload["error"]["message"] == "boom"
    assert "RuntimeError: boom" in payload["error"]["traceback"]


def test_structured_logging_redacts_sensitive_values_before_write() -> None:
    configure_logging()
    logger = get_logger("loopora.tests.diagnostics")

    try:
        raise RuntimeError("failed with Authorization: Bearer ERROR_SECRET_MARKER")
    except RuntimeError as exc:
        log_exception(
            logger,
            "test.logging.secret",
            "Starting command --token TOKEN_SECRET_MARKER",
            error=exc,
            auth_token="CONTEXT_TOKEN_SECRET_MARKER",
            headers={
                "Authorization": "Bearer HEADER_SECRET_MARKER",
                "Cookie": "COOKIE_SECRET_MARKER",
            },
        )

    log_text = (app_home() / "logs" / "service.log").read_text(encoding="utf-8")
    assert "TOKEN_SECRET_MARKER" not in log_text
    assert "CONTEXT_TOKEN_SECRET_MARKER" not in log_text
    assert "HEADER_SECRET_MARKER" not in log_text
    assert "COOKIE_SECRET_MARKER" not in log_text
    assert "ERROR_SECRET_MARKER" not in log_text

    payload = next(item for item in _read_service_log_records() if item["event"] == "test.logging.secret")
    assert payload["message"] == "Starting command --token <secret omitted>"
    assert payload["context"]["auth_token"] == "<secret omitted>"
    assert payload["context"]["headers"]["Authorization"] == "<secret omitted>"
    assert payload["context"]["headers"]["Cookie"] == "<secret omitted>"
    assert payload["error"]["message"] == "failed with Authorization: <secret omitted>"
