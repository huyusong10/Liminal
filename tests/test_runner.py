from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from liminal.service import LiminalError, LiminalService


def _create_loop(service, sample_spec_file: Path, sample_workdir: Path, name: str = "Demo Loop") -> dict:
    return service.create_loop(
        name=name,
        spec_path=sample_spec_file,
        workdir=sample_workdir,
        model="gpt-5.4",
        reasoning_effort="medium",
        max_iters=3,
        max_role_retries=1,
        delta_threshold=0.005,
        trigger_window=2,
        regression_window=2,
        role_models={},
    )


def test_successful_run_writes_expected_artifacts(service_factory, sample_spec_file: Path, sample_workdir: Path) -> None:
    service = service_factory(scenario="success")
    loop = _create_loop(service, sample_spec_file, sample_workdir)

    run = service.rerun(loop["id"])

    run_dir = Path(run["runs_dir"])
    assert run["status"] == "succeeded"
    assert (run_dir / "events.jsonl").exists()
    assert (run_dir / "tester_output.json").exists()
    assert (run_dir / "verifier_verdict.json").exists()
    assert (run_dir / "stagnation.json").exists()
    assert (sample_workdir / ".liminal" / "loops" / loop["id"] / "compiled_spec.json").exists()
    assert "All checks passed in this iteration." in (run_dir / "summary.md").read_text(encoding="utf-8")


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
    assert guard["role"] == "tester"
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
    compiled_spec = json.loads((run_dir / "compiled_spec.json").read_text(encoding="utf-8"))
    auto_checks = json.loads((run_dir / "auto_checks.json").read_text(encoding="utf-8"))
    tester_output = json.loads((run_dir / "tester_output.json").read_text(encoding="utf-8"))

    assert compiled_spec["check_mode"] == "auto_generated"
    assert len(compiled_spec["checks"]) >= 3
    assert auto_checks["count"] == len(compiled_spec["checks"])
    assert tester_output["execution_summary"]["total_checks"] == len(compiled_spec["checks"])
    assert tester_output["check_results"]


def test_same_workdir_concurrent_run_is_rejected(service_factory, sample_spec_file: Path, sample_workdir: Path) -> None:
    service = service_factory(scenario="success", role_delay=0.4)
    first_loop = _create_loop(service, sample_spec_file, sample_workdir, name="First")
    second_loop = _create_loop(service, sample_spec_file, sample_workdir, name="Second")

    first_run = service.start_run(first_loop["id"])
    service.start_run_async(first_run["id"])

    deadline = time.time() + 5
    while time.time() < deadline:
        status = service.get_run(first_run["id"])["status"]
        if status == "running":
            break
        time.sleep(0.05)

    with pytest.raises(LiminalError):
        service.start_run(second_loop["id"])


def test_stop_run_marks_run_stopped(service_factory, sample_spec_file: Path, sample_workdir: Path) -> None:
    service = service_factory(scenario="success", role_delay=0.5)
    loop = _create_loop(service, sample_spec_file, sample_workdir)
    run = service.start_run(loop["id"])

    thread = threading.Thread(target=service.execute_run, args=(run["id"],), daemon=True)
    thread.start()

    deadline = time.time() + 5
    while time.time() < deadline:
        current = service.get_run(run["id"])
        if current["status"] == "running":
            break
        time.sleep(0.05)

    service.stop_run(run["id"])
    thread.join(timeout=5)

    stopped = service.get_run(run["id"])
    assert stopped["status"] == "stopped"


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

    deadline = time.time() + 5
    while time.time() < deadline:
        current = service.get_run(run["id"])
        if current["status"] == "stopped":
            break
        time.sleep(0.05)

    stopped = service.get_run(run["id"])
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


def test_stop_run_rejects_finished_runs(service_factory, sample_spec_file: Path, sample_workdir: Path) -> None:
    service = service_factory(scenario="success")
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Finished Loop")
    run = service.rerun(loop["id"])

    with pytest.raises(LiminalError, match="cannot stop run in status"):
        service.stop_run(run["id"])

    events = service.repository.list_events(run["id"], after_id=0, limit=1000)
    assert all(event["event_type"] != "stop_requested" for event in events)


def test_plateau_run_records_challenger_execution_summary(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="plateau")
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Plateau Loop")

    run = service.rerun(loop["id"])

    events = service.repository.list_events(run["id"], after_id=0, limit=1000)
    challenger_summaries = [
        event for event in events
        if event["event_type"] == "role_execution_summary" and event["payload"].get("role") == "challenger"
    ]
    verifier_summaries = [
        event for event in events
        if event["event_type"] == "role_execution_summary" and event["payload"].get("role") == "verifier"
    ]

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

    restarted = LiminalService(
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

    events = restarted.repository.list_events(run["id"], after_id=0, limit=1000)
    assert any(
        event["event_type"] == "run_finished"
        and event["payload"].get("reason") == "Recovered stale run after service startup."
        for event in events
    )

    fresh_run = restarted.rerun(loop["id"])
    assert fresh_run["status"] == "succeeded"
