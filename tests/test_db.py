from __future__ import annotations

import sqlite3
from pathlib import Path

from loopora.db import LooporaRepository


def test_repository_retries_transient_open_errors(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "app.db"
    real_connect = sqlite3.connect
    attempts = {"count": 0}

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
