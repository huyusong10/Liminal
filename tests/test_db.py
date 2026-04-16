from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

from loopora.db import LooporaRepository
from loopora.settings import app_home, configure_logging


def test_repository_retries_transient_open_errors(tmp_path: Path, monkeypatch, caplog) -> None:
    target = tmp_path / "app.db"
    real_connect = sqlite3.connect
    attempts = {"count": 0}
    configure_logging()
    caplog.set_level(logging.WARNING, logger="loopora")

    def flaky_connect(*args, **kwargs):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise sqlite3.OperationalError("unable to open database file")
        return real_connect(*args, **kwargs)

    monkeypatch.setattr("loopora.db.sqlite3.connect", flaky_connect)
    monkeypatch.setattr("loopora.db.time.sleep", lambda _: None)

    repository = LooporaRepository(target)

    assert attempts["count"] >= 2
    assert repository.path == target
    assert repository.path.exists()
    records = [
        json.loads(line)
        for line in (app_home() / "logs" / "service.log").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    retry_record = next(record for record in records if record["event"] == "db.connect.retry")
    assert retry_record["context"]["attempt"] == 1
    assert retry_record["context"]["retryable"] is True


def test_append_event_tolerates_jsonl_mirror_failures(tmp_path: Path, monkeypatch) -> None:
    repository = LooporaRepository(tmp_path / "app.db")
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    loop = repository.create_loop(
        {
            "id": "loop_test",
            "name": "Loop",
            "workdir": str(workdir),
            "spec_path": str(tmp_path / "spec.md"),
            "spec_markdown": "# Goal\n\nShip it.\n",
            "compiled_spec": {"goal": "Ship it.", "checks": [], "constraints": ""},
            "model": "gpt-5.4",
            "reasoning_effort": "medium",
            "max_iters": 1,
            "max_role_retries": 1,
            "delta_threshold": 0.1,
            "trigger_window": 1,
            "regression_window": 1,
            "role_models": {},
        }
    )
    run_dir = workdir / ".loopora" / "runs" / "run_test"
    run_dir.mkdir(parents=True)
    repository.create_run(
        {
            "id": "run_test",
            "loop_id": loop["id"],
            "workdir": str(workdir),
            "spec_path": str(tmp_path / "spec.md"),
            "spec_markdown": "# Goal\n\nShip it.\n",
            "compiled_spec": {"goal": "Ship it.", "checks": [], "constraints": ""},
            "model": "gpt-5.4",
            "reasoning_effort": "medium",
            "max_iters": 1,
            "max_role_retries": 1,
            "delta_threshold": 0.1,
            "trigger_window": 1,
            "regression_window": 1,
            "role_models": {},
            "status": "queued",
            "runs_dir": str(run_dir),
            "summary_md": "# Loopora Run Summary\n\nQueued.\n",
        }
    )

    monkeypatch.setattr("loopora.db.append_jsonl", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk full")))

    event = repository.append_event("run_test", "run_started", {"status": "running"})

    assert event["event_type"] == "run_started"
    stored = repository.list_events("run_test")
    assert len(stored) == 1
    assert stored[0]["payload"]["status"] == "running"


def test_role_definition_crud_round_trips_through_repository(tmp_path: Path) -> None:
    repository = LooporaRepository(tmp_path / "app.db")

    created = repository.create_role_definition(
        {
            "id": "role_release_builder",
            "name": "Release Builder",
            "description": "Ship release work.",
            "archetype": "builder",
            "prompt_ref": "release-builder.md",
            "prompt_markdown": "---\nversion: 1\narchetype: builder\n---\n\nFocus on release work.\n",
            "executor_kind": "claude",
            "executor_mode": "preset",
            "command_cli": "claude",
            "command_args_text": "",
            "model": "gpt-5.4-mini",
            "reasoning_effort": "high",
        }
    )

    assert created["name"] == "Release Builder"
    assert created["archetype"] == "builder"
    assert created["executor_kind"] == "claude"

    updated = repository.update_role_definition(
        created["id"],
        {
            "name": "Release Builder v2",
            "description": "Ship release work safely.",
            "archetype": "builder",
            "prompt_ref": "release-builder.md",
            "prompt_markdown": "---\nversion: 1\narchetype: builder\n---\n\nFocus on safe release work.\n",
            "executor_kind": "codex",
            "executor_mode": "command",
            "command_cli": "codex",
            "command_args_text": "exec\n{prompt}\n",
            "model": "gpt-5.4",
            "reasoning_effort": "",
        },
    )
    assert updated is not None
    assert updated["name"] == "Release Builder v2"
    assert updated["executor_mode"] == "command"

    listed = repository.list_role_definitions()
    assert len(listed) == 1
    assert listed[0]["model"] == "gpt-5.4"

    assert repository.delete_role_definition(created["id"]) is True
    assert repository.get_role_definition(created["id"]) is None
