from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

import pytest

from loopora.db import LooporaRepository
from loopora.db_event_records import RunObservationSnapshotRowsRequest
from loopora.db_schema import CURRENT_SCHEMA_VERSION
from loopora.service_types import LooporaConflictError
from loopora.settings import app_home, configure_logging
import loopora.db_row_decoding as row_decoding
import loopora.run_artifacts as run_artifacts


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


def _schema_user_version(path: Path) -> int:
    with sqlite3.connect(path) as connection:
        return int(connection.execute("PRAGMA user_version").fetchone()[0])


def test_repository_initializes_schema_user_version(tmp_path: Path) -> None:
    target = tmp_path / "app.db"

    LooporaRepository(target)
    LooporaRepository(target)

    assert _schema_user_version(target) == CURRENT_SCHEMA_VERSION


def test_repository_migrates_version_zero_schema_and_preserves_rows(tmp_path: Path) -> None:
    target = tmp_path / "app.db"
    with sqlite3.connect(target) as connection:
        connection.execute("CREATE TABLE loop_definitions (id TEXT PRIMARY KEY, name TEXT NOT NULL)")
        connection.execute("INSERT INTO loop_definitions (id, name) VALUES ('loop_legacy', 'Legacy Loop')")
        connection.execute("PRAGMA user_version = 0")

    LooporaRepository(target)

    with sqlite3.connect(target) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(loop_definitions)").fetchall()}
        row = connection.execute("SELECT id, name FROM loop_definitions WHERE id = 'loop_legacy'").fetchone()
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])

    assert "orchestration_id" in columns
    assert row == ("loop_legacy", "Legacy Loop")
    assert version == CURRENT_SCHEMA_VERSION


def test_create_run_rejects_second_active_run_for_workdir(tmp_path: Path) -> None:
    repository = LooporaRepository(tmp_path / "app.db")
    first_run = _create_run(repository, tmp_path, run_id="run_active_first", status="queued")
    workdir = Path(first_run["workdir"])
    spec_path = tmp_path / "second-spec.md"
    spec_markdown = "# Task\n\nShip it again.\n"
    spec_path.write_text(spec_markdown, encoding="utf-8")
    second_loop = repository.create_loop(
        {
            "id": "loop_active_second",
            "name": "Loop Active Second",
            "workdir": str(workdir),
            "spec_path": str(spec_path),
            "spec_markdown": spec_markdown,
            "compiled_spec": {"goal": "Ship it again.", "checks": [], "constraints": "", "role_notes": {}},
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
    second_run_dir = workdir / ".loopora" / "runs" / "run_active_second"
    second_run_dir.mkdir(parents=True)

    with pytest.raises(LooporaConflictError, match="another active run is already using"):
        repository.create_run(
            {
                "id": "run_active_second",
                "loop_id": second_loop["id"],
                "workdir": str(workdir),
                "spec_path": str(spec_path),
                "spec_markdown": spec_markdown,
                "compiled_spec": {"goal": "Ship it again.", "checks": [], "constraints": "", "role_notes": {}},
                "model": "gpt-5.4",
                "reasoning_effort": "medium",
                "max_iters": 1,
                "max_role_retries": 1,
                "delta_threshold": 0.1,
                "trigger_window": 1,
                "regression_window": 1,
                "role_models": {},
                "status": "queued",
                "runs_dir": str(second_run_dir),
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


def test_append_event_tolerates_runtime_jsonl_mirror_failures(tmp_path: Path, monkeypatch) -> None:
    configure_logging()
    repository = LooporaRepository(tmp_path / "app.db")
    _create_run(repository, tmp_path, run_id="run_runtime_mirror_failure")

    monkeypatch.setattr(
        "loopora.db.append_jsonl_with_mirrors",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("mirror helper crashed")),
    )

    event = repository.append_event("run_runtime_mirror_failure", "run_started", {"status": "running"})

    assert event["event_type"] == "run_started"
    stored = repository.list_events("run_runtime_mirror_failure")
    assert len(stored) == 1
    assert stored[0]["payload"]["status"] == "running"
    record = next(item for item in _read_service_log_records() if item["event"] == "db.run_event.mirror_failed")
    assert record["error"]["type"] == "RuntimeError"
    assert record["run_id"] == "run_runtime_mirror_failure"
    assert record["context"]["event_type"] == "run_started"


def test_run_artifact_json_mirror_runtime_failure_preserves_canonical(tmp_path: Path, monkeypatch) -> None:
    configure_logging()
    canonical_path = tmp_path / "canonical" / "state.json"
    mirror_path = tmp_path / "legacy" / "state.json"
    original_write_json = run_artifacts.write_json

    def fail_legacy_write(path: Path, payload: dict) -> None:
        if Path(path) == mirror_path:
            raise RuntimeError("legacy mirror adapter crashed")
        original_write_json(path, payload)

    monkeypatch.setattr(run_artifacts, "write_json", fail_legacy_write)

    run_artifacts.write_json_with_mirrors(canonical_path, {"ok": True}, mirror_paths=[mirror_path])

    assert json.loads(canonical_path.read_text(encoding="utf-8")) == {"ok": True}
    assert not mirror_path.exists()
    record = next(item for item in _read_service_log_records() if item["event"] == "run_artifact.mirror_write_failed")
    assert record["error"]["type"] == "RuntimeError"
    assert record["context"]["operation"] == "write_json"
    assert record["context"]["canonical_path"] == str(canonical_path)
    assert record["context"]["mirror_path"] == str(mirror_path)


def test_list_events_normalizes_cursor_and_limit_before_sqlite(tmp_path: Path) -> None:
    repository = LooporaRepository(tmp_path / "app.db")
    _create_run(repository, tmp_path)
    for index in range(3):
        repository.append_event("run_test", "progress", {"index": index})

    assert [event["payload"]["index"] for event in repository.list_events("run_test", after_id=-10, limit=2)] == [0, 1]
    assert [event["payload"]["index"] for event in repository.list_events("run_test", after_id=True, limit=2)] == [0, 1]
    assert [event["payload"]["index"] for event in repository.list_events("run_test", after_id="1", limit=2)] == [0, 1]
    assert repository.list_events("run_test", limit=0) == []
    assert repository.list_events("run_test", limit=-1) == []
    assert repository.list_events("run_test", limit=True) == []
    assert repository.list_events("run_test", limit="2") == []


def test_takeaway_projection_source_event_id_requires_integer_sequence(tmp_path: Path) -> None:
    repository = LooporaRepository(tmp_path / "app.db")
    run = _create_run(repository, tmp_path, run_id="run_projection_source_event", status="succeeded")
    event = repository.append_event(run["id"], "run_finished", {"status": "succeeded"})
    boolean_source_event_id = True

    assert repository.record_run_takeaway_projection(run["id"], boolean_source_event_id, {"run_status": "failed"}) is False
    assert repository.record_run_takeaway_projection(run["id"], str(event["id"]), {"run_status": "failed"}) is False
    assert repository.record_run_takeaway_projection(run["id"], event["id"], {"run_status": "succeeded"}) is True

    snapshot = repository.run_observation_snapshot_rows(
        RunObservationSnapshotRowsRequest(
            run_id=run["id"],
            timeline_event_types=["run_finished"],
            progress_event_types=[],
        )
    )

    assert snapshot["key_takeaway_projection"] == {"run_status": "succeeded", "source_event_id": event["id"]}


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


def test_takeaway_projection_shape_mismatch_degrades_with_diagnostic(tmp_path: Path, monkeypatch) -> None:
    repository = LooporaRepository(tmp_path / "app.db")
    run = _create_run(repository, tmp_path, run_id="run_projection_shape", status="succeeded")
    event = repository.append_event(run["id"], "run_finished", {"status": "succeeded"})
    repository.record_run_takeaway_projection(run["id"], event["id"], {"run_status": "succeeded"})
    log_calls: list[dict] = []

    def capture_log_event(_logger, _level, event_name, _message, **context):
        log_calls.append({"event": event_name, "context": context})

    monkeypatch.setattr(row_decoding, "log_event", capture_log_event)
    with repository.transaction() as connection:
        connection.execute(
            "UPDATE run_takeaway_projections SET payload_json = ? WHERE run_id = ? AND source_event_id = ?",
            ("[]", run["id"], event["id"]),
        )

    snapshot = repository.run_observation_snapshot_rows(
        RunObservationSnapshotRowsRequest(
            run_id=run["id"],
            timeline_event_types=["run_finished"],
            progress_event_types=[],
        )
    )

    assert snapshot["key_takeaway_projection"] == {"source_event_id": event["id"]}
    assert any(
        call["event"] == "db.row.decode_json_shape_mismatch"
        and call["context"]["column"] == "payload_json"
        and call["context"]["expected_type"] == "dict"
        and call["context"]["actual_type"] == "list"
        for call in log_calls
    )


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


def test_append_event_redacts_auth_and_cookie_headers(tmp_path: Path) -> None:
    repository = LooporaRepository(tmp_path / "app.db")
    run = _create_run(repository, tmp_path, run_id="run_sensitive_headers", status="running")

    event = repository.append_event(
        run["id"],
        "web_diagnostic",
        {
            "headers": {
                "Authorization": "Basic HEADER_AUTH_SECRET_MARKER",
                "Cookie": "session=HEADER_COOKIE_SECRET_MARKER",
            },
            "message": (
                "curl -H 'Authorization: Basic INLINE_AUTH_SECRET_MARKER' "
                "-H 'Cookie: session=INLINE_COOKIE_SECRET_MARKER'"
            ),
        },
    )

    stored = repository.list_events(run["id"])[0]
    timeline_text = (Path(run["runs_dir"]) / "timeline" / "events.jsonl").read_text(encoding="utf-8")
    combined_text = json.dumps([event, stored], ensure_ascii=False) + timeline_text

    assert event["payload"]["headers"]["Authorization"] == "<secret omitted>"
    assert event["payload"]["headers"]["Cookie"] == "<secret omitted>"
    assert "HEADER_AUTH_SECRET_MARKER" not in combined_text
    assert "HEADER_COOKIE_SECRET_MARKER" not in combined_text
    assert "INLINE_AUTH_SECRET_MARKER" not in combined_text
    assert "INLINE_COOKIE_SECRET_MARKER" not in combined_text


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


def test_corrupted_array_json_columns_fall_back_to_empty_lists(tmp_path: Path) -> None:
    repository = LooporaRepository(tmp_path / "app.db")
    workdir = tmp_path / "bundle-workdir"
    workdir.mkdir()
    bundle = repository.create_bundle(
        {
            "id": "bundle_corrupt_arrays",
            "name": "Corrupt Arrays",
            "workdir": str(workdir),
            "role_definition_ids": ["role_builder", "role_gatekeeper"],
        }
    )
    session = repository.create_alignment_session(
        {
            "id": "alignment_corrupt_arrays",
            "workdir": str(workdir),
            "bundle_path": str(workdir / ".loopora" / "alignment_sessions" / "alignment_corrupt_arrays" / "artifacts" / "bundle.yml"),
            "transcript": [{"role": "user", "content": "Build this."}],
        }
    )

    with repository.transaction() as connection:
        connection.execute(
            "UPDATE bundle_definitions SET role_definition_ids_json = ? WHERE id = ?",
            ("{", bundle["id"]),
        )
        connection.execute(
            "UPDATE alignment_sessions SET transcript_json = ? WHERE id = ?",
            ("{", session["id"]),
        )

    assert repository.get_bundle(bundle["id"])["role_definition_ids_json"] == []
    assert repository.get_alignment_session(session["id"])["transcript"] == []


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


def test_json_column_shape_mismatches_fall_back_to_declared_defaults(tmp_path: Path) -> None:
    repository = LooporaRepository(tmp_path / "app.db")
    run = _create_run(repository, tmp_path, run_id="run_shape_mismatch", status="running")
    event = repository.append_event(run["id"], "run_started", {"status": "running"})
    workdir = tmp_path / "shape-bundle-workdir"
    workdir.mkdir()
    bundle = repository.create_bundle(
        {
            "id": "bundle_shape_mismatch",
            "name": "Shape Mismatch",
            "workdir": str(workdir),
            "role_definition_ids": ["role_builder"],
        }
    )
    session = repository.create_alignment_session(
        {
            "id": "alignment_shape_mismatch",
            "workdir": str(workdir),
            "bundle_path": str(workdir / ".loopora" / "alignment_sessions" / "alignment_shape_mismatch" / "artifacts" / "bundle.yml"),
            "transcript": [{"role": "user", "content": "Build this."}],
            "validation": {"ready": False},
        }
    )

    with repository.transaction() as connection:
        connection.execute(
            "UPDATE loop_runs SET workflow_json = ? WHERE id = ?",
            ("[]", run["id"]),
        )
        connection.execute(
            "UPDATE run_events SET payload_json = ? WHERE id = ?",
            ("[]", event["id"]),
        )
        connection.execute(
            "UPDATE bundle_definitions SET role_definition_ids_json = ? WHERE id = ?",
            ('{"role": "role_builder"}', bundle["id"]),
        )
        connection.execute(
            "UPDATE alignment_sessions SET transcript_json = ?, validation_json = ? WHERE id = ?",
            ('{"role": "user"}', "[]", session["id"]),
        )

    assert repository.get_run(run["id"])["workflow_json"] == {}
    assert repository.list_events(run["id"])[0]["payload"] == {}
    assert repository.get_bundle(bundle["id"])["role_definition_ids_json"] == []
    refreshed_session = repository.get_alignment_session(session["id"])
    assert refreshed_session["transcript"] == []
    assert refreshed_session["validation"] == {}
