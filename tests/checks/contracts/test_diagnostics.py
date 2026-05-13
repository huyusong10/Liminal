from __future__ import annotations

import json
import logging

import pytest

from loopora.diagnostics import LooporaJsonFormatter, get_logger, log_event, log_exception
from loopora.event_redaction import redact_sensitive_text
from loopora.settings import app_home, configure_logging
import loopora.service_cleanup_diagnostics as cleanup_diagnostics


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
    assert payload["component"] == "tests"
    assert payload["loop_id"] == "loop_test"
    assert payload["run_id"] == "run_test"
    assert payload["context"]["detail"] == "ready"


@pytest.mark.parametrize(
    ("logger_name", "expected_component"),
    (
        ("loopora.service_run_registration", "service"),
        ("loopora.db_run_records", "db"),
        ("loopora.web_route_errors", "web"),
        ("loopora.cli_run_support", "cli"),
        ("loopora.settings", "settings"),
        ("loopora.tests.diagnostics", "tests"),
    ),
)
def test_json_formatter_maps_component_to_stable_boundary(logger_name: str, expected_component: str) -> None:
    logger = get_logger(logger_name)
    record = logger.makeRecord(
        logger.name,
        logging.INFO,
        __file__,
        1,
        "Boundary mapping works",
        (),
        None,
        extra={"event": "test.logging.component_boundary"},
    )

    payload = json.loads(LooporaJsonFormatter().format(record))

    assert payload["component"] == expected_component
    assert payload["logger"] == logger_name


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
            private_key="PRIVATE_KEY_SECRET_MARKER",
            headers={
                "Authorization": "Bearer HEADER_SECRET_MARKER",
                "Cookie": "COOKIE_SECRET_MARKER",
                "private-key": "NESTED_PRIVATE_KEY_SECRET_MARKER",
            },
            oauth={
                "accessToken": "ACCESS_TOKEN_SECRET_MARKER",
                "bearerToken": "BEARER_TOKEN_SECRET_MARKER",
                "clientSecret": "CLIENT_SECRET_MARKER",
            },
        )

    log_text = (app_home() / "logs" / "service.log").read_text(encoding="utf-8")
    assert "TOKEN_SECRET_MARKER" not in log_text
    assert "CONTEXT_TOKEN_SECRET_MARKER" not in log_text
    assert "HEADER_SECRET_MARKER" not in log_text
    assert "COOKIE_SECRET_MARKER" not in log_text
    assert "PRIVATE_KEY_SECRET_MARKER" not in log_text
    assert "NESTED_PRIVATE_KEY_SECRET_MARKER" not in log_text
    assert "ACCESS_TOKEN_SECRET_MARKER" not in log_text
    assert "BEARER_TOKEN_SECRET_MARKER" not in log_text
    assert "CLIENT_SECRET_MARKER" not in log_text
    assert "ERROR_SECRET_MARKER" not in log_text

    payload = next(item for item in _read_service_log_records() if item["event"] == "test.logging.secret")
    assert payload["message"] == "Starting command --token <secret omitted>"
    assert payload["context"]["auth_token"] == "<secret omitted>"
    assert payload["context"]["private_key"] == "<secret omitted>"
    assert payload["context"]["headers"]["Authorization"] == "<secret omitted>"
    assert payload["context"]["headers"]["Cookie"] == "<secret omitted>"
    assert payload["context"]["headers"]["private-key"] == "<secret omitted>"
    assert payload["context"]["oauth"]["accessToken"] == "<secret omitted>"
    assert payload["context"]["oauth"]["bearerToken"] == "<secret omitted>"
    assert payload["context"]["oauth"]["clientSecret"] == "<secret omitted>"
    assert payload["error"]["message"] == "failed with Authorization: <secret omitted>"


def test_json_formatter_redacts_manually_attached_context_before_write() -> None:
    logger = get_logger("loopora.tests.manual_formatter")
    record = logger.makeRecord(
        logger.name,
        logging.WARNING,
        __file__,
        123,
        "Manual command --token MESSAGE_SECRET_MARKER",
        (),
        None,
        extra={
            "event": "test.logging.manual_secret",
            "workdir": "Cookie: sid=WORKDIR_SECRET_MARKER",
            "context": {
                "auth_token": "CONTEXT_TOKEN_SECRET_MARKER",
                "headers": {
                    "Authorization": "Bearer HEADER_SECRET_MARKER",
                    "Cookie": "sid=COOKIE_SECRET_MARKER",
                },
                "refreshToken": "REFRESH_TOKEN_SECRET_MARKER",
                "nested": ["x-api-key: NESTED_SECRET_MARKER"],
            },
        },
    )

    payload = json.loads(LooporaJsonFormatter().format(record))
    log_text = json.dumps(payload, ensure_ascii=False)

    assert "MESSAGE_SECRET_MARKER" not in log_text
    assert "WORKDIR_SECRET_MARKER" not in log_text
    assert "CONTEXT_TOKEN_SECRET_MARKER" not in log_text
    assert "HEADER_SECRET_MARKER" not in log_text
    assert "COOKIE_SECRET_MARKER" not in log_text
    assert "REFRESH_TOKEN_SECRET_MARKER" not in log_text
    assert "NESTED_SECRET_MARKER" not in log_text
    assert payload["message"] == "Manual command --token <secret omitted>"
    assert payload["workdir"] == "Cookie: <secret omitted>"
    assert payload["context"]["auth_token"] == "<secret omitted>"
    assert payload["context"]["refreshToken"] == "<secret omitted>"
    assert payload["context"]["headers"]["Authorization"] == "<secret omitted>"
    assert payload["context"]["headers"]["Cookie"] == "<secret omitted>"
    assert payload["context"]["nested"] == ["x-api-key: <secret omitted>"]


def test_sensitive_text_redacts_common_secret_aliases() -> None:
    redacted = redact_sensitive_text(
        "\n".join(
            [
                "tool --private-key PRIVATE_KEY_SECRET_MARKER --client-secret=CLIENT_SECRET_MARKER --x-api-key X_API_KEY_SECRET_MARKER",
                "tool --x-loopora-token LOOPORA_TOKEN_SECRET_MARKER",
                "tool --access-token ACCESS_TOKEN_FLAG_SECRET_MARKER --refresh-token REFRESH_TOKEN_FLAG_SECRET_MARKER --id-token ID_TOKEN_FLAG_SECRET_MARKER --session-token SESSION_TOKEN_FLAG_SECRET_MARKER",
                "tool --proxy-authorization PROXY_AUTH_FLAG_SECRET_MARKER --set-cookie=SET_COOKIE_FLAG_SECRET_MARKER --cookie COOKIE_FLAG_SECRET_MARKER",
                "tool --authorization AUTHORIZATION_FLAG_SECRET_MARKER",
                "PRIVATE_KEY=ENV_PRIVATE_KEY_SECRET_MARKER CLIENT_SECRET=ENV_CLIENT_SECRET_MARKER",
                "Proxy-Authorization: Basic PROXY_AUTH_SECRET_MARKER",
            ]
        )
    )

    assert "PRIVATE_KEY_SECRET_MARKER" not in redacted
    assert "CLIENT_SECRET_MARKER" not in redacted
    assert "X_API_KEY_SECRET_MARKER" not in redacted
    assert "LOOPORA_TOKEN_SECRET_MARKER" not in redacted
    assert "ACCESS_TOKEN_FLAG_SECRET_MARKER" not in redacted
    assert "REFRESH_TOKEN_FLAG_SECRET_MARKER" not in redacted
    assert "ID_TOKEN_FLAG_SECRET_MARKER" not in redacted
    assert "SESSION_TOKEN_FLAG_SECRET_MARKER" not in redacted
    assert "PROXY_AUTH_FLAG_SECRET_MARKER" not in redacted
    assert "SET_COOKIE_FLAG_SECRET_MARKER" not in redacted
    assert "COOKIE_FLAG_SECRET_MARKER" not in redacted
    assert "AUTHORIZATION_FLAG_SECRET_MARKER" not in redacted
    assert "ENV_PRIVATE_KEY_SECRET_MARKER" not in redacted
    assert "ENV_CLIENT_SECRET_MARKER" not in redacted
    assert "PROXY_AUTH_SECRET_MARKER" not in redacted
    assert redacted.count("<secret omitted>") == 15


def test_best_effort_rmtree_logs_unexpected_cleanup_exception(monkeypatch, tmp_path) -> None:
    target = tmp_path / "cleanup-target"
    target.mkdir()
    log_calls: list[dict] = []

    def fail_rmtree(path) -> None:
        assert path == target
        raise RuntimeError("cleanup adapter crashed")

    def capture_log_event(_logger, _level, event, message, **context):
        log_calls.append({"event": event, "message": message, "context": context})

    monkeypatch.setattr(cleanup_diagnostics.shutil, "rmtree", fail_rmtree)
    monkeypatch.setattr(cleanup_diagnostics, "log_event", capture_log_event)

    removed = cleanup_diagnostics.best_effort_rmtree(
        target,
        logging.getLogger("loopora.tests.cleanup"),
        operation="test_cleanup",
        owner_id="owner-1",
    )

    assert removed is False
    assert any(
        call["event"] == "service.cleanup.failed"
        and call["context"].get("operation") == "test_cleanup"
        and call["context"].get("resource_type") == "path"
        and call["context"].get("resource_id") == str(target)
        and call["context"].get("owner_id") == "owner-1"
        and call["context"].get("error_type") == "RuntimeError"
        for call in log_calls
    )
