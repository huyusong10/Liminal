from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

from loopora.db import LooporaRepository
from loopora.settings import app_home, configure_logging


def _read_service_log_records() -> list[dict]:
    return [
        json.loads(line)
        for line in (app_home() / "logs" / "service.log").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _create_run(repository: LooporaRepository, tmp_path: Path, *, run_id: str = "run_test", status: str = "queued") -> dict:
    workdir = tmp_path / f"{run_id}-workdir"
    workdir.mkdir()
    spec_path = tmp_path / f"{run_id}-spec.md"
    spec_markdown = "# Task\n\nShip it.\n"
    spec_path.write_text(spec_markdown, encoding="utf-8")
    loop = repository.create_loop(
        {
            "id": f"loop_{run_id}",
            "name": f"Loop {run_id}",
            "workdir": str(workdir),
            "spec_path": str(spec_path),
            "spec_markdown": spec_markdown,
            "compiled_spec": {"goal": "Ship it.", "checks": [], "constraints": "", "role_notes": {}},
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
    run_dir = workdir / ".loopora" / "runs" / run_id
    run_dir.mkdir(parents=True)
    return repository.create_run(
        {
            "id": run_id,
            "loop_id": loop["id"],
            "workdir": str(workdir),
            "spec_path": str(spec_path),
            "spec_markdown": spec_markdown,
            "compiled_spec": {"goal": "Ship it.", "checks": [], "constraints": "", "role_notes": {}},
            "model": "gpt-5.4",
            "reasoning_effort": "medium",
            "max_iters": 1,
            "max_role_retries": 1,
            "delta_threshold": 0.1,
            "trigger_window": 1,
            "regression_window": 1,
            "role_models": {},
            "status": status,
            "runs_dir": str(run_dir),
            "summary_md": "# Loopora Run Summary\n\nQueued.\n",
        }
    )


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
    records = _read_service_log_records()
    retry_record = next(record for record in records if record["event"] == "db.connect.retry")
    assert retry_record["context"]["attempt"] == 1
    assert retry_record["context"]["retryable"] is True


def test_append_event_tolerates_jsonl_mirror_failures(tmp_path: Path, monkeypatch) -> None:
    repository = LooporaRepository(tmp_path / "app.db")
    _create_run(repository, tmp_path)

    monkeypatch.setattr(
        "loopora.db.append_jsonl_with_mirrors",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )

    event = repository.append_event("run_test", "run_started", {"status": "running"})

    assert event["event_type"] == "run_started"
    stored = repository.list_events("run_test")
    assert len(stored) == 1
    assert stored[0]["payload"]["status"] == "running"


def test_append_event_does_not_write_takeaway_projection(tmp_path: Path) -> None:
    repository = LooporaRepository(tmp_path / "app.db")
    run = _create_run(repository, tmp_path, run_id="run_projection_boundary", status="running")

    event = repository.append_event(run["id"], "run_finished", {"status": "succeeded"})

    assert event["event_type"] == "run_finished"
    with repository._connect() as connection:
        row = connection.execute(
            "SELECT 1 FROM run_takeaway_projections WHERE run_id = ?",
            (run["id"],),
        ).fetchone()
    assert row is None


def test_append_event_redacts_sensitive_payload_before_storage_and_mirrors(tmp_path: Path) -> None:
    repository = LooporaRepository(tmp_path / "app.db")
    run = _create_run(repository, tmp_path, run_id="run_sensitive_event", status="running")

    event = repository.append_event(
        run["id"],
        "codex_event",
        {
            "type": "stdout",
            "prompt": "PROMPT_SECRET_MARKER",
            "output_schema": {"properties": {"SCHEMA_SECRET_MARKER": {"type": "string"}}},
            "message": "tool --auth-token TOKEN_SECRET_MARKER Authorization: Bearer BEARER_SECRET_MARKER",
            "nested": {
                "api_key": "API_KEY_SECRET_MARKER",
                "safe": "keep me",
            },
        },
    )

    stored = repository.list_events(run["id"])[0]
    timeline_text = (Path(run["runs_dir"]) / "timeline" / "events.jsonl").read_text(encoding="utf-8")
    combined_text = json.dumps([event, stored], ensure_ascii=False) + timeline_text

    assert event["payload"]["payload_omitted"] is True
    assert set(event["payload"]["omitted_keys"]) == {"nested", "output_schema", "prompt"}
    assert "PROMPT_SECRET_MARKER" not in combined_text
    assert "SCHEMA_SECRET_MARKER" not in combined_text
    assert "TOKEN_SECRET_MARKER" not in combined_text
    assert "BEARER_SECRET_MARKER" not in combined_text
    assert "API_KEY_SECRET_MARKER" not in combined_text


def test_append_codex_event_keeps_safe_shape_and_drops_raw_item_details(tmp_path: Path) -> None:
    repository = LooporaRepository(tmp_path / "app.db")
    run = _create_run(repository, tmp_path, run_id="run_codex_raw_event", status="running")
    long_output = "visible output\n" + ("x" * 5000)

    event = repository.append_event(
        run["id"],
        "codex_event",
        {
            "type": "item.completed",
            "message": long_output,
            "input": {"prompt": "RAW_PROMPT_MARKER"},
            "item": {
                "type": "file_change",
                "changes": [
                    {
                        "path": "src/app.py",
                        "diff": "RAW_DIFF_MARKER",
                        "content": "RAW_CONTENT_MARKER",
                    }
                ],
            },
            "step_id": "builder_step",
            "role_name": "Builder",
            "archetype": "builder",
        },
    )

    stored = repository.list_events(run["id"])[0]
    timeline_text = (Path(run["runs_dir"]) / "timeline" / "events.jsonl").read_text(encoding="utf-8")
    combined_text = json.dumps([event, stored], ensure_ascii=False) + timeline_text

    assert event["payload"]["type"] == "item.completed"
    assert event["payload"]["step_id"] == "builder_step"
    assert event["payload"]["message_truncated"] is True
    assert event["payload"]["payload_omitted"] is True
    assert event["payload"]["omitted_keys"] == ["input"]
    assert event["payload"]["item"] == {"type": "file_change", "changes": [{"path": "src/app.py"}]}
    assert "visible output" in event["payload"]["message"]
    assert "RAW_PROMPT_MARKER" not in combined_text
    assert "RAW_DIFF_MARKER" not in combined_text
    assert "RAW_CONTENT_MARKER" not in combined_text


def test_send_stop_signal_clears_stale_child_pid_and_logs_warning(tmp_path: Path, monkeypatch) -> None:
    configure_logging()
    repository = LooporaRepository(tmp_path / "app.db")
    run = _create_run(repository, tmp_path, run_id="run_stale", status="running")
    repository.update_run(run["id"], child_pid=999999)

    def missing_process(_pid: int, _signal: int) -> None:
        raise ProcessLookupError

    monkeypatch.setattr("loopora.db.os.kill", missing_process)

    assert repository.send_stop_signal(run["id"]) is True

    refreshed = repository.get_run(run["id"])
    assert refreshed["child_pid"] is None
    record = next(
        item
        for item in _read_service_log_records()
        if item["event"] == "db.run.stop_signal_skipped" and item["run_id"] == run["id"]
    )
    assert record["level"] == "WARNING"
    assert record["context"]["child_pid"] == 999999
    assert record["context"]["reason"] == "process_not_found"


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


def test_corrupted_run_json_columns_fall_back_to_empty_objects(tmp_path: Path) -> None:
    repository = LooporaRepository(tmp_path / "app.db")
    run = _create_run(repository, tmp_path, run_id="run_corrupt", status="running")

    with repository.transaction() as connection:
        connection.execute(
            "UPDATE loop_runs SET last_verdict_json = ?, task_verdict_json = ?, workflow_json = ? WHERE id = ?",
            ("{", "{", "{", run["id"]),
        )

    refreshed = repository.get_run(run["id"])

    assert refreshed["last_verdict_json"] == {}
    assert refreshed["task_verdict_json"] == {}
    assert refreshed["workflow_json"] == {}


def test_run_schema_persists_task_verdict_separately_from_raw_verdict(tmp_path: Path) -> None:
    repository = LooporaRepository(tmp_path / "app.db")
    run = _create_run(repository, tmp_path, run_id="run_task_verdict", status="running")

    with repository.transaction() as connection:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(loop_runs)").fetchall()}
    assert "task_verdict_json" in columns

    repository.update_run(
        run["id"],
        status="succeeded",
        last_verdict={"passed": True, "decision_summary": "Raw GateKeeper pass."},
        task_verdict={
            "status": "passed",
            "source": "gatekeeper",
            "summary": "Evidence-backed task pass.",
            "buckets": {
                "proven": [],
                "weak": [],
                "unproven": [],
                "blocking": [],
                "residual_risk": [],
            },
        },
    )

    refreshed = repository.get_run(run["id"])

    assert refreshed["last_verdict_json"]["decision_summary"] == "Raw GateKeeper pass."
    assert refreshed["task_verdict_json"]["summary"] == "Evidence-backed task pass."


def test_corrupted_event_payload_json_falls_back_to_empty_object(tmp_path: Path) -> None:
    repository = LooporaRepository(tmp_path / "app.db")
    run = _create_run(repository, tmp_path, run_id="run_event_corrupt", status="running")
    event = repository.append_event(run["id"], "run_started", {"status": "running"})

    with repository.transaction() as connection:
        connection.execute(
            "UPDATE run_events SET payload_json = ? WHERE id = ?",
            ("{", event["id"]),
        )

    events = repository.list_events(run["id"])

    assert len(events) == 1
    assert events[0]["payload"] == {}
