from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "Loopora"
LEGACY_APP_NAME = "Liminal"
APP_SLUG = "loopora"
LEGACY_APP_SLUG = "liminal"
APP_PACKAGE = APP_SLUG

APP_STATE_DIRNAME = ".loopora"
LEGACY_APP_STATE_DIRNAME = ".liminal"

APP_HOME_ENV = "LOOPORA_HOME"
LEGACY_APP_HOME_ENV = "LIMINAL_HOME"
APP_AUTH_ENV = "LOOPORA_AUTH_TOKEN"
LEGACY_APP_AUTH_ENV = "LIMINAL_AUTH_TOKEN"
APP_AUTH_COOKIE = "loopora_auth"
LEGACY_APP_AUTH_COOKIE = "liminal_auth"
APP_AUTH_HEADER = "x-loopora-token"
LEGACY_APP_AUTH_HEADER = "x-liminal-token"

FAKE_EXECUTOR_ENV = "LOOPORA_FAKE_EXECUTOR"
LEGACY_FAKE_EXECUTOR_ENV = "LIMINAL_FAKE_EXECUTOR"
FAKE_DELAY_ENV = "LOOPORA_FAKE_DELAY"
LEGACY_FAKE_DELAY_ENV = "LIMINAL_FAKE_DELAY"

SPEC_SKILL_SLUG = "loopora-spec"
LEGACY_SPEC_SKILL_SLUG = "liminal-spec"

RUN_SUMMARY_TITLE = "Loopora Run Summary"
LEGACY_RUN_SUMMARY_TITLE = "Liminal Run Summary"

FILE_ROOT_QUERY_PATTERN = rf"^(workdir|{APP_SLUG}|{LEGACY_APP_SLUG})$"


def app_home_path() -> Path:
    for env_name in (APP_HOME_ENV, LEGACY_APP_HOME_ENV):
        configured = os.environ.get(env_name, "").strip()
        if configured:
            return Path(configured).expanduser()

    default_path = Path.home() / APP_STATE_DIRNAME
    legacy_path = Path.home() / LEGACY_APP_STATE_DIRNAME
    if default_path.exists() or not legacy_path.exists():
        return default_path
    return legacy_path


def state_dir_for_workdir(workdir: str | Path) -> Path:
    base_dir = Path(workdir)
    default_path = base_dir / APP_STATE_DIRNAME
    legacy_path = base_dir / LEGACY_APP_STATE_DIRNAME
    if default_path.exists() or not legacy_path.exists():
        return default_path
    return legacy_path


def normalize_file_root(root: str) -> str:
    return APP_SLUG if root == LEGACY_APP_SLUG else root


def strip_run_summary_title(text: str) -> str:
    normalized = text.removeprefix(RUN_SUMMARY_TITLE)
    if normalized != text:
        return normalized.strip()
    return text.removeprefix(LEGACY_RUN_SUMMARY_TITLE).strip()
