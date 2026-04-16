from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

from loopora.branding import APP_PACKAGE, app_home_path
from loopora.diagnostics import LooporaJsonFormatter, get_logger, log_event


@dataclass(slots=True)
class AppSettings:
    max_concurrent_runs: int = 2
    polling_interval_seconds: float = 0.5
    stop_grace_period_seconds: float = 2.0
    role_idle_timeout_seconds: float = 300.0


logger = get_logger(__name__)


def app_home() -> Path:
    path = app_home_path()
    path.mkdir(parents=True, exist_ok=True)
    return path


def logs_dir() -> Path:
    path = app_home() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def settings_path() -> Path:
    return app_home() / "settings.json"


def db_path() -> Path:
    return app_home() / "app.db"


def recent_workdirs_path() -> Path:
    return app_home() / "recent_workdirs.json"


def load_settings() -> AppSettings:
    path = settings_path()
    defaults = AppSettings()
    if not path.exists():
        _persist_settings_best_effort(defaults, path=path)
        return defaults
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log_event(
            logger,
            logging.WARNING,
            "settings.load.reset_defaults",
            "Failed to read settings file; resetting to defaults",
            app_home=app_home(),
            path=path,
        )
        _persist_settings_best_effort(defaults, path=path)
        return defaults

    settings, should_rewrite = _normalize_settings_payload(payload, defaults=defaults)
    if should_rewrite:
        _persist_settings_best_effort(settings, path=path)
    return settings


def save_settings(settings: AppSettings) -> None:
    path = settings_path()
    path.write_text(json.dumps(asdict(settings), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_recent_workdirs(limit: int = 50) -> list[str]:
    path = recent_workdirs_path()
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log_event(
            logger,
            logging.WARNING,
            "settings.recent_workdirs.read_failed",
            "Failed to read recent workdirs; ignoring stored entries",
            app_home=app_home(),
            path=path,
        )
        return []
    if not isinstance(payload, list):
        return []
    return _normalize_recent_workdirs(payload, limit=limit)


def save_recent_workdirs(workdirs: Iterable[str], limit: int = 50) -> None:
    recent = _normalize_recent_workdirs(workdirs, limit=limit)
    path = recent_workdirs_path()
    try:
        path.write_text(
            json.dumps(recent, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError:
        log_event(
            logger,
            logging.WARNING,
            "settings.recent_workdirs.write_failed",
            "Failed to write recent workdirs; update ignored",
            app_home=app_home(),
            path=path,
        )


def _normalize_recent_workdirs(workdirs: Iterable[object], *, limit: int) -> list[str]:
    recent = []
    seen = set()
    for item in workdirs:
        value = _normalize_recent_workdir_entry(item)
        if not value or value in seen:
            continue
        recent.append(value)
        seen.add(value)
        if len(recent) >= limit:
            break
    return recent


def _normalize_recent_workdir_entry(item: object) -> str:
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, os.PathLike):
        return os.fspath(item).strip()
    return ""


def _persist_settings_best_effort(settings: AppSettings, *, path: Path) -> None:
    try:
        path.write_text(json.dumps(asdict(settings), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError:
        log_event(
            logger,
            logging.WARNING,
            "settings.persist.write_failed",
            "Failed to persist settings; continuing with in-memory defaults",
            app_home=app_home(),
            path=path,
        )


def _normalize_settings_payload(payload: object, *, defaults: AppSettings) -> tuple[AppSettings, bool]:
    if not isinstance(payload, dict):
        log_event(
            logger,
            logging.WARNING,
            "settings.normalize.invalid_payload",
            "Settings payload is not an object; resetting to defaults",
            payload_type=type(payload).__name__,
        )
        return defaults, True

    normalized: dict[str, float | int] = {}
    should_rewrite = False

    max_concurrent_runs = _coerce_setting_number(
        payload,
        key="max_concurrent_runs",
        default=defaults.max_concurrent_runs,
        integer_only=True,
        minimum=1,
    )
    if max_concurrent_runs != payload.get("max_concurrent_runs"):
        should_rewrite = True
    normalized["max_concurrent_runs"] = int(max_concurrent_runs)

    polling_interval_seconds = _coerce_setting_number(
        payload,
        key="polling_interval_seconds",
        default=defaults.polling_interval_seconds,
        integer_only=False,
        minimum=0.001,
    )
    if polling_interval_seconds != payload.get("polling_interval_seconds"):
        should_rewrite = True
    normalized["polling_interval_seconds"] = polling_interval_seconds

    stop_grace_period_seconds = _coerce_setting_number(
        payload,
        key="stop_grace_period_seconds",
        default=defaults.stop_grace_period_seconds,
        integer_only=False,
        minimum=0.0,
    )
    if stop_grace_period_seconds != payload.get("stop_grace_period_seconds"):
        should_rewrite = True
    normalized["stop_grace_period_seconds"] = stop_grace_period_seconds

    role_idle_timeout_seconds = _coerce_setting_number(
        payload,
        key="role_idle_timeout_seconds",
        default=defaults.role_idle_timeout_seconds,
        integer_only=False,
        minimum=0.001,
    )
    if role_idle_timeout_seconds != payload.get("role_idle_timeout_seconds"):
        should_rewrite = True
    normalized["role_idle_timeout_seconds"] = role_idle_timeout_seconds

    expected_keys = set(normalized)
    if set(payload) != expected_keys:
        should_rewrite = True

    return AppSettings(**normalized), should_rewrite


def _coerce_setting_number(
    payload: dict[str, object],
    *,
    key: str,
    default: int | float,
    integer_only: bool,
    minimum: float,
) -> int | float:
    raw_value = payload.get(key, default)
    if isinstance(raw_value, bool):
        log_event(
            logger,
            logging.WARNING,
            "settings.normalize.invalid_value",
            "Invalid boolean-like settings value; using default",
            setting_key=key,
            raw_value=raw_value,
            default_value=default,
        )
        return default

    try:
        value = int(raw_value) if integer_only else float(raw_value)
    except (TypeError, ValueError):
        log_event(
            logger,
            logging.WARNING,
            "settings.normalize.invalid_value",
            "Invalid settings value; using default",
            setting_key=key,
            raw_value=raw_value,
            default_value=default,
        )
        return default

    if value < minimum:
        log_event(
            logger,
            logging.WARNING,
            "settings.normalize.out_of_range",
            "Out-of-range settings value; using default",
            setting_key=key,
            raw_value=raw_value,
            default_value=default,
            minimum=minimum,
        )
        return default
    return value


def configure_logging() -> None:
    log_path = logs_dir() / "service.log"
    formatter = LooporaJsonFormatter()
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    stream_handler.setLevel(logging.WARNING)
    file_handler.set_name("loopora-file")
    stream_handler.set_name("loopora-stream")

    package_logger = logging.getLogger(APP_PACKAGE)
    for handler in package_logger.handlers:
        handler.close()
    package_logger.handlers.clear()
    package_logger.setLevel(logging.INFO)
    package_logger.propagate = False
    package_logger.addHandler(file_handler)
    package_logger.addHandler(stream_handler)
    log_event(
        logger,
        logging.INFO,
        "logging.configured",
        "Structured diagnostic logging configured",
        path=log_path,
    )
