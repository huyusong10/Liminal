from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(slots=True)
class AppSettings:
    max_concurrent_runs: int = 2
    polling_interval_seconds: float = 0.5
    stop_grace_period_seconds: float = 2.0
    role_idle_timeout_seconds: float = 300.0


logger = logging.getLogger(__name__)


def app_home() -> Path:
    configured = os.environ.get("LIMINAL_HOME", "").strip()
    path = Path(configured).expanduser() if configured else Path.home() / ".liminal"
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
        logger.warning("failed to read %s; resetting settings to defaults", path)
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
        logger.warning("failed to read %s; ignoring stored recent workdirs", path)
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
        logger.warning("failed to write %s; ignoring recent workdir update", path)


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
        logger.warning("failed to write %s; continuing with in-memory defaults", path)


def _normalize_settings_payload(payload: object, *, defaults: AppSettings) -> tuple[AppSettings, bool]:
    if not isinstance(payload, dict):
        logger.warning("settings payload is not an object; resetting to defaults")
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
        logger.warning("invalid %s=%r in settings; using default %r", key, raw_value, default)
        return default

    try:
        value = int(raw_value) if integer_only else float(raw_value)
    except (TypeError, ValueError):
        logger.warning("invalid %s=%r in settings; using default %r", key, raw_value, default)
        return default

    if value < minimum:
        logger.warning("out-of-range %s=%r in settings; using default %r", key, raw_value, default)
        return default
    return value


def configure_logging() -> None:
    log_path = logs_dir() / "service.log"
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    package_logger = logging.getLogger("liminal")
    package_logger.handlers.clear()
    package_logger.setLevel(logging.INFO)
    package_logger.propagate = False
    package_logger.addHandler(file_handler)
    package_logger.addHandler(stream_handler)
