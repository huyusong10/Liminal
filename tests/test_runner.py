from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import pytest

from loopora.executor import CodexExecutor, ExecutorError
from loopora.service import LooporaError, LooporaService


def _read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _step_outputs_by_archetype(run_dir: Path) -> dict[str, list[dict]]:
    outputs: dict[str, list[dict]] = {}
    for metadata_path in sorted(run_dir.glob("steps/iter_*/*/metadata.json")):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        output_path = metadata_path.parent / "output.normalized.json"
        outputs.setdefault(metadata["archetype"], []).append(
            {
                "metadata": metadata,
                "output": json.loads(output_path.read_text(encoding="utf-8")),
                "step_dir": metadata_path.parent,
            }
        )
    return outputs


def _create_loop(
    service,
    sample_spec_file: Path,
    sample_workdir: Path,
    name: str = "Demo Loop",
    *,
    workflow: dict | None = None,
    **overrides,
) -> dict:
    payload = {
        "name": name,
        "spec_path": sample_spec_file,
        "workdir": sample_workdir,
        "model": "gpt-5.4",
        "reasoning_effort": "medium",
        "max_iters": 3,
        "max_role_retries": 1,
        "delta_threshold": 0.005,
        "trigger_window": 2,
        "regression_window": 2,
        "role_models": {},
        "workflow": workflow,
    }
    payload.update(overrides)
    return service.create_loop(**payload)


def test_successful_run_writes_expected_artifacts(service_factory, sample_spec_file: Path, sample_workdir: Path) -> None:
    service = service_factory(scenario="success")
    loop = _create_loop(service, sample_spec_file, sample_workdir)

    run = service.rerun(loop["id"])

    run_dir = Path(run["runs_dir"])
    step_outputs = _step_outputs_by_archetype(run_dir)
    assert run["status"] == "succeeded"
    assert (run_dir / "events.jsonl").exists()
    assert (run_dir / "stagnation.json").exists()
    assert (sample_workdir / ".loopora" / "loops" / loop["id"] / "compiled_spec.json").exists()
    assert step_outputs["inspector"]
    assert step_outputs["gatekeeper"]
    assert any((item["step_dir"] / "prompt.md").exists() for item in step_outputs["inspector"])
    assert any((item["step_dir"] / "prompt.md").exists() for item in step_outputs["gatekeeper"])
    summary = (run_dir / "summary.md").read_text(encoding="utf-8")
    assert "All checks passed in this iteration." in summary
    assert "iteration_log.jsonl" in summary


def test_successful_run_enriches_logs_and_role_outputs(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Verbose Logs Loop")

    run = service.rerun(loop["id"])

    run_dir = Path(run["runs_dir"])
    step_outputs = _step_outputs_by_archetype(run_dir)
    tester_output = step_outputs["inspector"][-1]["output"]
    verifier_verdict = step_outputs["gatekeeper"][-1]["output"]
    metrics_history = _read_jsonl(run_dir / "metrics_history.jsonl")
    iteration_log = _read_jsonl(run_dir / "iteration_log.jsonl")

    assert tester_output["status_counts"]["overall"]["passed"] >= 1
    assert "failed_items" in tester_output
    assert verifier_verdict["decision_summary"]
    assert "failing_metrics" in verifier_verdict
    assert "next_actions" in verifier_verdict
    assert metrics_history[-1]["stagnation_mode"] in {"none", "plateau", "regression"}
    assert "score_delta" in metrics_history[-1]

    complete_entries = [entry for entry in iteration_log if entry["phase"] == "complete"]
    assert complete_entries
    latest_entry = complete_entries[-1]
    assert latest_entry["generator"]["changed_files"] == []
    assert latest_entry["tester"]["status_counts"]["overall"]["passed"] >= 1
    assert latest_entry["verifier"]["decision_summary"]
    assert latest_entry["score"]["composite"] == verifier_verdict["composite_score"]


def test_run_persists_role_request_snapshots_and_iteration_handoff(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="plateau")
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Prompt Snapshot Loop")

    run = service.rerun(loop["id"])

    run_dir = Path(run["runs_dir"])
    role_requests = _read_jsonl(run_dir / "role_requests.jsonl")

    assert role_requests
    generator_requests = [item for item in role_requests if item["role"] == "generator"]
    assert generator_requests
    second_generator = next(item for item in generator_requests if item["iter"] == 1)
    assert "previous_verifier_result" in second_generator["extra_context_keys"]
    assert second_generator["context_summary"]["previous_verifier_result"]["composite_score"] == 0.62

    prompt_path = Path(second_generator["prompt_path"])
    prompt_text = prompt_path.read_text(encoding="utf-8")
    assert "Previous iteration evidence:" in prompt_text
    assert "Improve the most visible failing checks without widening scope." in prompt_text
    assert "Use this evidence as your starting point" in prompt_text


def test_inspect_first_workflow_runs_inspector_before_builder(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = _create_loop(
        service,
        sample_spec_file,
        sample_workdir,
        name="Inspect First Loop",
        workflow={"preset": "inspect_first"},
    )

    run = service.rerun(loop["id"])

    assert run["status"] == "succeeded"
    assert run["workflow_json"]["preset"] == "inspect_first"
    iteration_log = [
        json.loads(line)
        for line in (Path(run["runs_dir"]) / "iteration_log.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    workflow_entry = next(entry for entry in iteration_log if entry["phase"] == "complete")
    assert [step["archetype"] for step in workflow_entry["workflow"][:3]] == ["inspector", "builder", "gatekeeper"]


def test_benchmark_loop_can_finish_before_builder_runs(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    class BenchmarkPassingExecutor(CodexExecutor):
        def execute(self, request, emit_event, should_stop, set_child_pid):
            set_child_pid(None)
            if request.role_archetype == "gatekeeper":
                payload = {
                    "passed": True,
                    "decision_summary": "Benchmark target already satisfied.",
                    "feedback_to_builder": "No code change is required.",
                    "confidence": "high",
                    "blocking_issues": [],
                    "metrics": [],
                    "failed_check_ids": [],
                    "priority_failures": [],
                    "composite_score": 1.0,
                }
                request.output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                return payload
            raise AssertionError("Builder should not run when benchmark loop already passes.")

    service = service_factory(scenario="success")
    service.executor_factory = lambda: BenchmarkPassingExecutor()
    loop = _create_loop(
        service,
        sample_spec_file,
        sample_workdir,
        name="Benchmark Loop",
        workflow={"preset": "benchmark_loop"},
    )

    run = service.rerun(loop["id"])
    run_dir = Path(run["runs_dir"])
    step_outputs = _step_outputs_by_archetype(run_dir)

    assert run["status"] == "succeeded"
    assert "builder" not in step_outputs
    assert step_outputs["gatekeeper"][-1]["output"]["passed"] is True


def test_workflow_step_model_override_is_used_for_role_requests(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    workflow = {
        "version": 1,
        "roles": [
            {"id": "builder", "name": "Builder", "archetype": "builder", "prompt_ref": "builder.md"},
            {"id": "gatekeeper", "name": "GateKeeper", "archetype": "gatekeeper", "prompt_ref": "gatekeeper.md"},
        ],
        "steps": [
            {"id": "builder_step", "role_id": "builder", "enabled": True, "model": "gpt-5.4-mini"},
            {"id": "gatekeeper_step", "role_id": "gatekeeper", "enabled": True, "on_pass": "finish_run"},
        ],
    }
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Step Model Loop", workflow=workflow)

    run = service.rerun(loop["id"])

    role_requests = _read_jsonl(Path(run["runs_dir"]) / "role_requests.jsonl")
    builder_request = next(item for item in role_requests if item.get("step_id") == "builder_step")
    assert builder_request["model"] == "gpt-5.4-mini"


def test_workflow_roles_can_use_distinct_executor_snapshots(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    workflow = {
        "version": 1,
        "roles": [
            {
                "id": "builder",
                "name": "Builder",
                "archetype": "builder",
                "prompt_ref": "builder.md",
                "executor_kind": "codex",
                "executor_mode": "preset",
                "model": "gpt-5.4-mini",
                "reasoning_effort": "high",
            },
            {
                "id": "custom_helper",
                "name": "Custom Helper",
                "archetype": "custom",
                "prompt_ref": "custom.md",
                "executor_kind": "claude",
                "executor_mode": "preset",
                "model": "",
                "reasoning_effort": "high",
            },
        ],
        "steps": [
            {"id": "builder_step", "role_id": "builder", "enabled": True},
            {"id": "custom_step", "role_id": "custom_helper", "enabled": True},
        ],
    }

    loop = _create_loop(
        service,
        sample_spec_file,
        sample_workdir,
        name="Per Role Executor Loop",
        workflow=workflow,
        completion_mode="rounds",
        max_iters=1,
    )
    run = service.rerun(loop["id"])

    role_requests = _read_jsonl(Path(run["runs_dir"]) / "role_requests.jsonl")
    builder_request = next(item for item in role_requests if item.get("step_id") == "builder_step")
    custom_request = next(item for item in role_requests if item.get("step_id") == "custom_step")

    assert builder_request["executor_kind"] == "codex"
    assert builder_request["model"] == "gpt-5.4-mini"
    assert custom_request["executor_kind"] == "claude"
    assert custom_request["role_archetype"] == "custom"


def test_round_completion_mode_can_finish_without_gatekeeper(
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
            {"id": "builder_step", "role_id": "builder", "enabled": True},
        ],
    }
    loop = _create_loop(
        service,
        sample_spec_file,
        sample_workdir,
        name="Round Loop",
        workflow=workflow,
        completion_mode="rounds",
        max_iters=2,
    )

    run = service.rerun(loop["id"])

    assert run["status"] == "succeeded"
    iteration_log = _read_jsonl(Path(run["runs_dir"]) / "iteration_log.jsonl")
    assert len([entry for entry in iteration_log if entry["phase"] == "complete"]) == 2
    events = service.stream_events(run["id"], limit=200)
    assert any(
        event["event_type"] == "run_finished" and event["payload"].get("reason") == "rounds_completed"
        for event in events
    )


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
            {"id": "builder_step", "role_id": "builder", "enabled": True},
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

    with pytest.raises(LooporaError):
        service.start_run(second_loop["id"])


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
        saw_generator_start = any(
            event["event_type"] == "role_started" and event.get("role") == "generator"
            for event in events
        )
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
        def execute(self, request, emit_event, should_stop, set_child_pid):
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
    service.executor_factory = lambda: StopAwareExecutor()
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Stop Retry Guard")
    run = service.start_run(loop["id"])

    thread = threading.Thread(target=service.execute_run, args=(run["id"],), daemon=True)
    thread.start()

    deadline = time.time() + 5
    saw_generator_start = False
    while time.time() < deadline:
        current = service.get_run(run["id"])
        events = service.repository.list_events(run["id"], after_id=0, limit=50)
        saw_generator_start = any(
            event["event_type"] == "role_started" and event.get("role") == "generator"
            for event in events
        )
        if current["status"] == "running" and saw_generator_start:
            break
        time.sleep(0.05)

    service.stop_run(run["id"])
    thread.join(timeout=5)

    stopped = service.get_run(run["id"])
    assert stopped["status"] == "stopped"

    events = service.repository.list_events(run["id"], after_id=0, limit=200)
    generator_starts = [
        event
        for event in events
        if event["event_type"] == "role_started" and event.get("role") == "generator"
    ]
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
    events = service.repository.list_events(run["id"], after_id=0, limit=1000)
    assert any(event["event_type"] == "run_aborted" for event in events)


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

    events = restarted.repository.list_events(run["id"], after_id=0, limit=1000)
    assert any(
        event["event_type"] == "run_finished"
        and event["payload"].get("reason") == "Recovered stale run after service startup."
        for event in events
    )

    fresh_run = restarted.rerun(loop["id"])
    assert fresh_run["status"] == "succeeded"
