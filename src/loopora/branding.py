from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "Loopora"
APP_SLUG = "loopora"
APP_PACKAGE = APP_SLUG

APP_STATE_DIRNAME = ".loopora"

APP_HOME_ENV = "LOOPORA_HOME"
APP_AUTH_ENV = "LOOPORA_AUTH_TOKEN"
APP_AUTH_COOKIE = "loopora_auth"
APP_AUTH_HEADER = "x-loopora-token"

FAKE_EXECUTOR_ENV = "LOOPORA_FAKE_EXECUTOR"
FAKE_DELAY_ENV = "LOOPORA_FAKE_DELAY"

SPEC_SKILL_SLUG = "loopora-spec"

RUN_SUMMARY_TITLE = "Loopora Run Summary"
FILE_ROOT_QUERY_PATTERN = rf"^(workdir|{APP_SLUG})$"


def app_home_path() -> Path:
    configured = os.environ.get(APP_HOME_ENV, "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / APP_STATE_DIRNAME


def state_dir_for_workdir(workdir: str | Path) -> Path:
    base_dir = Path(workdir)
    return base_dir / APP_STATE_DIRNAME


def strip_run_summary_title(text: str) -> str:
    normalized = text.removeprefix(RUN_SUMMARY_TITLE)
    return normalized.strip() if normalized != text else text.strip()
