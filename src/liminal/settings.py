from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(slots=True)
class AppSettings:
    max_concurrent_runs: int = 2
    polling_interval_seconds: float = 0.5
    stop_grace_period_seconds: float = 2.0
    role_idle_timeout_seconds: float = 300.0


def app_home() -> Path:
    path = Path.home() / ".liminal"
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


def load_settings() -> AppSettings:
    path = settings_path()
    if not path.exists():
        save_settings(AppSettings())
    payload = json.loads(path.read_text(encoding="utf-8"))
    return AppSettings(**payload)


def save_settings(settings: AppSettings) -> None:
    path = settings_path()
    path.write_text(json.dumps(asdict(settings), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def configure_logging() -> None:
    log_path = logs_dir() / "service.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
