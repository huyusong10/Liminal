from __future__ import annotations

import json
import os
import shutil
import threading
import time
from pathlib import Path

import pytest

from loopora.executor import CodexExecutor, ExecutorError
from loopora.run_artifacts import RunArtifactLayout
from loopora.service import LooporaError, LooporaService

from runner_helpers import (
    _create_loop,
    _force_run_into_legacy_mode,
    _join_async_run,
    _wait_for_terminal_run,
)


def test_failed_run_without_verdict_is_not_evaluated(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Failed Without Verdict Loop")
    run = service.start_run(loop["id"])

    service.repository.update_run(run["id"], status="failed", error_message="setup failed before evidence")
    refreshed = service.get_run(run["id"])

    assert refreshed["run_status"] == "failed"
    assert refreshed["task_verdict"]["status"] == "not_evaluated"
    assert refreshed["task_verdict"]["source"] == "run_status"


def test_iteration_interval_emits_wait_events_between_rounds(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    workflow = {
        "version": 1,
        "roles": [
            {"id": "builder", "name": "Builder", "archetype": "builder", "prompt_ref": "builder.md"},
        ],
        "steps": [
            {"id": "builder_step", "role_id": "builder"},
        ],
    }
    loop = _create_loop(
        service,
        sample_spec_file,
        sample_workdir,
        name="Timed Round Loop",
        workflow=workflow,
        completion_mode="rounds",
        max_iters=2,
        iteration_interval_seconds=0.01,
    )

    run = service.rerun(loop["id"])

    events = service.stream_events(run["id"], limit=200)
    assert any(event["event_type"] == "iteration_wait_started" for event in events)
    assert any(event["event_type"] == "iteration_wait_finished" for event in events)


def test_destructive_generator_is_blocked_by_workspace_guard(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    (sample_workdir / "notes.txt").write_text("keep me\n", encoding="utf-8")
    (sample_workdir / "src").mkdir()
    (sample_workdir / "src" / "app.js").write_text("console.log('hi')\n", encoding="utf-8")

    service = service_factory(scenario="destructive_generator")
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Guarded Loop")

    run = service.rerun(loop["id"])

    run_dir = Path(run["runs_dir"])
    guard = json.loads((run_dir / "workspace_guard.json").read_text(encoding="utf-8"))

    assert run["status"] == "failed"
    assert "workspace safety guard" in (run["error_message"] or "")
    assert guard["baseline_file_count"] == 3
    assert guard["remaining_original_file_count"] == 0
    assert guard["deleted_original_count"] == 3
    assert "progress.md" in guard["deleted_original_paths"]
    assert "Execution stopped by the workspace safety guard." in (run_dir / "summary.md").read_text(encoding="utf-8")
    events = service.stream_events(run["id"], limit=200)
    assert any(event["event_type"] == "run_aborted" for event in events)
    assert any(
        event["event_type"] == "run_finished"
        and event["payload"]["status"] == "failed"
        and event["payload"]["reason"] == "workspace_safety_guard"
        and event["payload"]["task_verdict_status"] == "failed"
        for event in events
    )


def test_workspace_guard_ignores_generated_cache_deletions(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    (sample_workdir / "src").mkdir()
    (sample_workdir / "src" / "app.py").write_text("print('keep')\n", encoding="utf-8")
    (sample_workdir / ".pytest_cache" / "v" / "cache").mkdir(parents=True)
    (sample_workdir / ".pytest_cache" / "v" / "cache" / "nodeids").write_text("[]\n", encoding="utf-8")
    (sample_workdir / ".ruff_cache").mkdir()
    (sample_workdir / ".ruff_cache" / "metadata.json").write_text("{}\n", encoding="utf-8")
    (sample_workdir / ".coverage").write_text("coverage data\n", encoding="utf-8")

    service = service_factory(scenario="success")
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Cache Cleanup Loop")
    run = service.start_run(loop["id"])
    run_dir = Path(run["runs_dir"])
    baseline = json.loads((run_dir / "contract" / "workspace_baseline.json").read_text(encoding="utf-8"))

    assert "src/app.py" in baseline["files"]
    assert "progress.md" in baseline["files"]
    assert not any(path.startswith(".pytest_cache/") for path in baseline["files"])
    assert not any(path.startswith(".ruff_cache/") for path in baseline["files"])
    assert ".coverage" not in baseline["files"]

    shutil.rmtree(sample_workdir / ".pytest_cache")
    shutil.rmtree(sample_workdir / ".ruff_cache")
    (sample_workdir / ".coverage").unlink()

    service._enforce_workspace_safety(run, run_dir, 0, role="builder")

    assert not (run_dir / "workspace_guard.json").exists()
    assert not (run_dir / "timeline" / "workspace_guard.json").exists()
    assert not any(event["event_type"] == "workspace_guard_triggered" for event in service.stream_events(run["id"], limit=10))


def test_workspace_guard_fails_closed_when_baseline_is_missing_or_malformed(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    (sample_workdir / "src").mkdir()
    (sample_workdir / "src" / "app.py").write_text("print('keep')\n", encoding="utf-8")

    service = service_factory(scenario="success")
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Missing Baseline Loop")
    run = service.start_run(loop["id"])
    run_dir = Path(run["runs_dir"])
    baseline_path = RunArtifactLayout(run_dir).workspace_baseline_path

    baseline_path.unlink()
    with pytest.raises(LooporaError, match="workspace safety baseline"):
        service._enforce_workspace_safety(run, run_dir, 0, role="builder")

    baseline_path.write_text("{not json}\n", encoding="utf-8")
    with pytest.raises(LooporaError, match="workspace safety baseline"):
        service._enforce_workspace_safety(run, run_dir, 0, role="builder")

    baseline_path.write_text('{"files": [42]}\n', encoding="utf-8")
    with pytest.raises(LooporaError, match="workspace safety baseline"):
        service._enforce_workspace_safety(run, run_dir, 0, role="builder")


def test_destructive_tester_is_blocked_by_workspace_guard(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    (sample_workdir / "notes.txt").write_text("keep me\n", encoding="utf-8")
    (sample_workdir / "src").mkdir()
    (sample_workdir / "src" / "app.js").write_text("console.log('hi')\n", encoding="utf-8")

    service = service_factory(scenario="destructive_tester")
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Guarded Tester Loop")

    run = service.rerun(loop["id"])

    run_dir = Path(run["runs_dir"])
    guard = json.loads((run_dir / "workspace_guard.json").read_text(encoding="utf-8"))

    assert run["status"] == "failed"
    assert "workspace safety guard" in (run["error_message"] or "")
    assert guard["role"] == "contract_inspector"
    assert guard["deleted_original_count"] == 3


def test_exploratory_run_generates_and_freezes_checks(
    service_factory,
    exploratory_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = _create_loop(service, exploratory_spec_file, sample_workdir, name="Exploratory Loop")

    run = service.rerun(loop["id"])

    run_dir = Path(run["runs_dir"])
    compiled_spec = json.loads((run_dir / "contract" / "compiled_spec.json").read_text(encoding="utf-8"))
    auto_checks = json.loads((run_dir / "contract" / "auto_checks.json").read_text(encoding="utf-8"))
    tester_output = json.loads((run_dir / "tester_output.json").read_text(encoding="utf-8"))

    assert compiled_spec["check_mode"] == "auto_generated"
    assert len(compiled_spec["checks"]) >= 3
    assert any(target["id"] == "done_when.check_001" for target in compiled_spec["coverage_targets"])
    assert auto_checks["count"] == len(compiled_spec["checks"])
    assert tester_output["execution_summary"]["total_checks"] == len(compiled_spec["checks"])
    assert tester_output["check_results"]


def test_generated_check_normalization_requires_object_items(service_factory) -> None:
    service = service_factory(scenario="success")

    assert service._normalize_generated_checks("not a list") == []

    checks = service._normalize_generated_checks(
        [
            "not an object",
            {
                "title": "Primary outcome",
                "details": "The run has a concrete proof path.",
                "when": "After Builder finishes.",
                "expect": "Proof is present.",
                "fail_if": "Proof is missing.",
            },
        ]
    )

    assert checks == [
        {
            "id": "check_001",
            "title": "Primary outcome",
            "details": "The run has a concrete proof path.",
            "when": "After Builder finishes.",
            "expect": "Proof is present.",
            "fail_if": "Proof is missing.",
            "source": "auto_generated",
        }
    ]


def test_same_workdir_concurrent_run_is_rejected(service_factory, sample_spec_file: Path, sample_workdir: Path) -> None:
    service = service_factory(scenario="success", role_delay=0.4)
    first_loop = _create_loop(service, sample_spec_file, sample_workdir, name="First")
    second_loop = _create_loop(service, sample_spec_file, sample_workdir, name="Second")

    first_run = service.start_run(first_loop["id"])
    service.start_run_async(first_run["id"])

    try:
        deadline = time.time() + 5
        while time.time() < deadline:
            status = service.get_run(first_run["id"])["status"]
            if status == "running":
                break
            time.sleep(0.05)

        with pytest.raises(LooporaError):
            service.start_run(second_loop["id"])
    finally:
        if service.get_run(first_run["id"])["status"] in {"queued", "running"}:
            service.stop_run(first_run["id"])
            _wait_for_terminal_run(service, first_run["id"])
        _join_async_run(service, first_run["id"])


def test_start_run_async_rejects_duplicate_local_dispatch(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success", role_delay=0.4)
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Duplicate Async Dispatch")
    run = service.start_run(loop["id"])
    service.start_run_async(run["id"])

    try:
        with pytest.raises(LooporaError, match="already executing in this process"):
            service.start_run_async(run["id"])
    finally:
        current = service.get_run(run["id"])
        if current["status"] in {"queued", "running"}:
            service.stop_run(run["id"])
            _wait_for_terminal_run(service, run["id"])
        _join_async_run(service, run["id"])


def test_execute_run_rejects_duplicate_local_worker(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success", role_delay=0.4)
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Duplicate Worker")
    run = service.start_run(loop["id"])

    thread = threading.Thread(target=service.execute_run, args=(run["id"],), daemon=True)
    thread.start()

    try:
        deadline = time.time() + 5
        while time.time() < deadline and not service._is_run_active_locally(run["id"]):
            time.sleep(0.01)

        with pytest.raises(LooporaError, match="already executing in this process"):
            service.execute_run(run["id"])
    finally:
        current = service.get_run(run["id"])
        if current["status"] in {"queued", "running"}:
            service.stop_run(run["id"])
            _wait_for_terminal_run(service, run["id"])
        thread.join(timeout=5)


def test_stop_run_marks_run_stopped(service_factory, sample_spec_file: Path, sample_workdir: Path) -> None:
    service = service_factory(scenario="success", role_delay=0.5)
    loop = _create_loop(service, sample_spec_file, sample_workdir)
    run = service.start_run(loop["id"])

    thread = threading.Thread(target=service.execute_run, args=(run["id"],), daemon=True)
    thread.start()

    deadline = time.time() + 5
    saw_generator_start = False
    while time.time() < deadline:
        current = service.get_run(run["id"])
        events = service.repository.list_events(run["id"], after_id=0, limit=50)
        saw_generator_start = any(event["event_type"] == "role_started" and event.get("role") == "generator" for event in events)
        if current["status"] == "running" and saw_generator_start:
            break
        time.sleep(0.05)

    service.stop_run(run["id"])
    thread.join(timeout=5)

    stopped = service.get_run(run["id"])
    assert stopped["status"] == "stopped"


def test_stop_requested_run_does_not_retry_the_active_role(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    class StopAwareExecutor(CodexExecutor):
        def execute(self, _request, _emit_event, should_stop, _set_child_pid):
            deadline = time.time() + 0.4
            while time.time() < deadline:
                if should_stop():
                    raise ExecutorError("terminated after stop request")
                time.sleep(0.01)
            return {
                "attempted": "noop",
                "abandoned": "",
                "assumption": "",
                "summary": "",
                "changed_files": [],
            }

    service = service_factory(scenario="success")
    service.executor_factory = StopAwareExecutor
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Stop Retry Guard")
    run = service.start_run(loop["id"])

    thread = threading.Thread(target=service.execute_run, args=(run["id"],), daemon=True)
    thread.start()

    deadline = time.time() + 5
    saw_generator_start = False
    while time.time() < deadline:
        current = service.get_run(run["id"])
        events = service.repository.list_events(run["id"], after_id=0, limit=50)
        saw_generator_start = any(event["event_type"] == "role_started" and event.get("role") == "generator" for event in events)
        if current["status"] == "running" and saw_generator_start:
            break
        time.sleep(0.05)

    service.stop_run(run["id"])
    thread.join(timeout=5)

    stopped = service.get_run(run["id"])
    assert stopped["status"] == "stopped"

    events = service.repository.list_events(run["id"], after_id=0, limit=200)
    generator_starts = [event for event in events if event["event_type"] == "role_started" and event.get("role") == "generator"]
    assert saw_generator_start is True
    assert len(generator_starts) == 1


def test_zero_max_iters_runs_until_stopped(service_factory, sample_spec_file: Path, sample_workdir: Path) -> None:
    service = service_factory(scenario="plateau", role_delay=0.02)
    loop = service.create_loop(
        name="Infinite Loop",
        spec_path=sample_spec_file,
        workdir=sample_workdir,
        model="gpt-5.4",
        reasoning_effort="medium",
        max_iters=0,
        max_role_retries=1,
        delta_threshold=0.005,
        trigger_window=2,
        regression_window=2,
        role_models={},
    )
    run = service.start_run(loop["id"])
    service.start_run_async(run["id"])

    deadline = time.time() + 5
    while time.time() < deadline:
        current = service.get_run(run["id"])
        if current["current_iter"] >= 2:
            break
        time.sleep(0.05)

    current = service.get_run(run["id"])
    assert current["status"] in {"queued", "running"}
    assert current["current_iter"] >= 2

    service.stop_run(run["id"])

    stopped = _wait_for_terminal_run(service, run["id"])
    _join_async_run(service, run["id"])
    assert stopped["status"] == "stopped"


def test_async_run_cleans_up_thread_bookkeeping(service_factory, sample_spec_file: Path, sample_workdir: Path) -> None:
    service = service_factory(scenario="success", role_delay=0.01)
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Async Loop")
    run = service.start_run(loop["id"])
    service.start_run_async(run["id"])

    deadline = time.time() + 5
    while time.time() < deadline:
        current = service.get_run(run["id"])
        if current["status"] in {"succeeded", "failed", "stopped"}:
            break
        time.sleep(0.05)

    finished = service.get_run(run["id"])
    assert finished["status"] == "succeeded"
    assert run["id"] not in service._threads


def test_execute_run_returns_terminal_run_without_active_runtime_markers(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Runtime Marker Cleanup Loop")
    run = service.start_run(loop["id"])

    finished = service.execute_run(run["id"])

    assert finished["status"] == "succeeded"
    assert finished["active_role"] is None
    assert finished["runner_pid"] is None
    assert finished["child_pid"] is None
    stored = service.repository.get_run(run["id"])
    assert stored["active_role"] is None
    assert stored["runner_pid"] is None
    assert stored["child_pid"] is None


def test_get_run_reaps_finished_thread_handle(service_factory, sample_spec_file: Path, sample_workdir: Path) -> None:
    service = service_factory(scenario="success")
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Reap Thread Loop")
    run = service.start_run(loop["id"])
    service.repository.update_run(
        run["id"],
        status="succeeded",
        finished_at="2026-04-18T11:00:00+00:00",
        summary_md="# done",
    )

    completed = threading.Thread(target=lambda: None, name="completed-run-thread")
    completed.start()
    completed.join()
    service._threads[run["id"]] = completed

    finished = service.get_run(run["id"])

    assert finished["status"] == "succeeded"
    assert run["id"] not in service._threads


def test_unexpected_run_error_marks_run_failed(service_factory, sample_spec_file: Path, sample_workdir: Path) -> None:
    service = service_factory(scenario="success")
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Crash Loop")
    run = service.start_run(loop["id"])

    def explode(*_args, **_kwargs):
        raise RuntimeError("boom")

    service._resolve_run_checks = explode  # type: ignore[method-assign]

    failed = service.execute_run(run["id"])

    assert failed["status"] == "failed"
    assert failed["error_message"] == "boom"
    summary = Path(failed["runs_dir"]) / "summary.md"
    assert "Execution crashed unexpectedly." in summary.read_text(encoding="utf-8")
    events = service.repository.list_events(run["id"], after_id=0, limit=1000)
    assert any(event["event_type"] == "run_aborted" for event in events)
    assert any(
        event["event_type"] == "run_finished"
        and event["payload"]["status"] == "failed"
        and event["payload"]["reason"] == "crashed"
        and event["payload"]["task_verdict_status"] == "not_evaluated"
        for event in events
    )


def test_legacy_gatekeeper_run_exhausts_without_crashing(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="plateau")
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Legacy Plateau Loop")
    run = service.start_run(loop["id"])
    _force_run_into_legacy_mode(service, run["id"])

    failed = service.execute_run(run["id"])

    assert failed["status"] == "failed"
    assert failed["error_message"] in {None, ""}
    events = service.repository.list_events(run["id"], after_id=0, limit=1000)
    assert any(event["event_type"] == "run_finished" and event["payload"].get("reason") == "max_iters_exhausted" for event in events)
    assert all(event["event_type"] != "run_aborted" for event in events)


def test_empty_workflow_snapshot_dispatches_to_legacy_execution(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
    monkeypatch,
) -> None:
    service = service_factory(scenario="success")
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Legacy Dispatch Loop")
    run = service.start_run(loop["id"])
    _force_run_into_legacy_mode(service, run["id"])
    original_legacy_run = service._execute_legacy_run
    dispatched = {"legacy": False}

    def record_legacy_dispatch(run_id: str, run: dict, run_dir: Path) -> dict:
        dispatched["legacy"] = True
        return original_legacy_run(run_id, run, run_dir)

    monkeypatch.setattr(service, "_execute_legacy_run", record_legacy_dispatch)

    finished = service.execute_run(run["id"])

    assert dispatched["legacy"] is True
    assert finished["status"] == "succeeded"


def test_legacy_rounds_run_finishes_after_planned_iterations(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="plateau")
    loop = _create_loop(
        service,
        sample_spec_file,
        sample_workdir,
        name="Legacy Planned Rounds Loop",
        completion_mode="rounds",
        max_iters=2,
    )
    run = service.start_run(loop["id"])
    _force_run_into_legacy_mode(service, run["id"])

    finished = service.execute_run(run["id"])

    assert finished["status"] == "succeeded"
    assert finished["error_message"] in {None, ""}
    events = service.repository.list_events(run["id"], after_id=0, limit=1000)
    assert any(event["event_type"] == "run_finished" and event["payload"].get("reason") == "rounds_completed" for event in events)
    assert all(event["event_type"] != "run_aborted" for event in events)


def test_get_run_recovers_local_orphaned_active_run(service_factory, sample_spec_file: Path, sample_workdir: Path) -> None:
    service = service_factory(scenario="success")
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Orphan Loop")
    run = service.start_run(loop["id"])
    service._local_run_orphan_grace_seconds = lambda: 0.0  # type: ignore[method-assign]
    service.repository.update_run(
        run["id"],
        status="running",
        runner_pid=os.getpid(),
        active_role="generator",
        started_at="2026-04-13T08:00:00+00:00",
    )

    service._threads.pop(run["id"], None)

    recovered = service.get_run(run["id"])

    assert recovered["status"] == "failed"
    assert recovered["runner_pid"] is None
    assert recovered["child_pid"] is None
    assert "Recovered orphaned run" in (recovered["error_message"] or "")
    assert recovered["task_verdict"]["status"] == "not_evaluated"
    events = service.repository.list_events(run["id"], after_id=0, limit=1000)
    assert any(event["event_type"] == "run_aborted" for event in events)
    assert any(
        event["event_type"] == "run_finished"
        and event["payload"]["status"] == "failed"
        and event["payload"]["reason"] == "orphaned_worker"
        and event["payload"]["task_verdict_status"] == "not_evaluated"
        for event in events
    )


def test_second_service_instance_does_not_recover_run_active_in_same_process(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Shared Process Loop")
    run = service.start_run(loop["id"])
    service.repository.update_run(
        run["id"],
        status="running",
        runner_pid=os.getpid(),
        active_role="generator",
        started_at="2026-04-13T08:00:00+00:00",
    )
    service._mark_run_active(run["id"])

    try:
        restarted = LooporaService(
            repository=service.repository,
            settings=service.settings,
            executor_factory=service.executor_factory,
        )
        restarted._local_run_orphan_grace_seconds = lambda: 0.0  # type: ignore[method-assign]

        current = restarted.get_run(run["id"])

        assert current["status"] == "running"
        assert current["error_message"] in {None, ""}
    finally:
        service._mark_run_inactive(run["id"])


def test_second_service_instance_does_not_recover_queued_run_with_same_process_pid(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Queued Shared Process Loop")
    run = service.start_run(loop["id"])
    service.repository.update_run(
        run["id"],
        status="queued",
        runner_pid=os.getpid(),
        started_at="2026-04-13T08:00:00+00:00",
    )
    service._mark_run_active(run["id"])

    try:
        restarted = LooporaService(
            repository=service.repository,
            settings=service.settings,
            executor_factory=service.executor_factory,
        )
        restarted._local_run_orphan_grace_seconds = lambda: 0.0  # type: ignore[method-assign]

        current = restarted.get_run(run["id"])

        assert current["status"] == "queued"
        assert current["error_message"] in {None, ""}
    finally:
        service._mark_run_inactive(run["id"])


def test_second_service_instance_keeps_fresh_queued_run_without_runner_pid(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Fresh Queued Loop")
    run = service.start_run(loop["id"])

    restarted = LooporaService(
        repository=service.repository,
        settings=service.settings,
        executor_factory=service.executor_factory,
    )

    current = restarted.get_run(run["id"])

    assert current["status"] == "queued"
    assert current["error_message"] in {None, ""}


def test_early_execute_run_crash_is_persisted_as_failed(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Early Crash Loop")
    run = service.start_run(loop["id"])

    service.executor_factory = lambda: (_ for _ in ()).throw(RuntimeError("executor boot failed"))  # type: ignore[assignment]

    failed = service.execute_run(run["id"])

    assert failed["status"] == "failed"
    assert failed["error_message"] == "executor boot failed"
    assert run["id"] not in LooporaService._process_active_runs
    summary = Path(failed["runs_dir"]) / "summary.md"
    assert "Execution crashed unexpectedly." in summary.read_text(encoding="utf-8")


def test_stop_run_rejects_finished_runs(service_factory, sample_spec_file: Path, sample_workdir: Path) -> None:
    service = service_factory(scenario="success")
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Finished Loop")
    run = service.rerun(loop["id"])

    with pytest.raises(LooporaError, match="cannot stop run in status"):
        service.stop_run(run["id"])

    events = service.repository.list_events(run["id"], after_id=0, limit=1000)
    assert all(event["event_type"] != "stop_requested" for event in events)


def test_plateau_run_records_challenger_execution_summary(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="plateau")
    loop = _create_loop(
        service,
        sample_spec_file,
        sample_workdir,
        name="Plateau Loop",
        workflow={"preset": "repair_loop"},
        max_iters=4,
    )

    run = service.rerun(loop["id"])

    events = service.repository.list_events(run["id"], after_id=0, limit=1000)
    challenger_summaries = [event for event in events if event["event_type"] == "role_execution_summary" and event["payload"].get("role") == "challenger"]
    verifier_summaries = [event for event in events if event["event_type"] == "role_execution_summary" and event["payload"].get("role") == "verifier"]

    assert challenger_summaries
    assert verifier_summaries
    assert all(event["payload"]["duration_ms"] >= 0 for event in challenger_summaries + verifier_summaries)


def test_service_startup_marks_stale_active_runs_stopped(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Stale Loop")
    run = service.start_run(loop["id"])
    service.repository.update_run(
        run["id"],
        status="running",
        runner_pid=999999,
        active_role="tester",
        started_at="2026-04-13T08:00:00+00:00",
    )

    restarted = LooporaService(
        repository=service.repository,
        settings=service.settings,
        executor_factory=service.executor_factory,
    )
    recovered = restarted.get_run(run["id"])

    assert recovered["status"] == "stopped"
    assert recovered["finished_at"] is not None
    assert recovered["runner_pid"] is None
    assert recovered["child_pid"] is None
    assert "Recovered stale run" in (recovered["error_message"] or "")
    assert recovered["task_verdict"]["status"] == "not_evaluated"
    assert recovered["task_verdict"]["source"] == "run_status"
    assert json.loads((Path(recovered["runs_dir"]) / "evidence" / "task_verdict.json").read_text(encoding="utf-8")) == recovered["task_verdict"]

    events = restarted.repository.list_events(run["id"], after_id=0, limit=1000)
    assert any(
        event["event_type"] == "run_finished"
        and event["payload"].get("reason") == "Recovered stale run after service startup."
        and event["payload"]["task_verdict_status"] == "not_evaluated"
        and event["payload"]["task_verdict_source"] == "run_status"
        for event in events
    )

    fresh_run = restarted.rerun(loop["id"])
    assert fresh_run["status"] == "succeeded"
