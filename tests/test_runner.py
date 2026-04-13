from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from liminal.service import LiminalError


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
