from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from liminal.web import build_app


def test_api_loop_creation_run_preview_and_stream(service_factory, sample_spec_file: Path, sample_workdir: Path) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    response = client.post(
        "/api/loops",
        json={
            "name": "API Loop",
            "spec_path": str(sample_spec_file),
            "workdir": str(sample_workdir),
            "model": "gpt-5.4",
            "reasoning_effort": "medium",
            "max_iters": 3,
            "max_role_retries": 1,
            "delta_threshold": 0.005,
            "trigger_window": 2,
            "regression_window": 2,
            "start_immediately": True,
        },
    )
    assert response.status_code == 201
    payload = response.json()
    run_id = payload["run"]["id"]

    deadline = time.time() + 5
    while time.time() < deadline:
        run_response = client.get(f"/api/runs/{run_id}")
        assert run_response.status_code == 200
        if run_response.json()["status"] == "succeeded":
            break
        time.sleep(0.05)

    explorer = client.get(f"/api/files?run_id={run_id}&root=workdir")
    assert explorer.status_code == 200
    assert explorer.json()["kind"] == "directory"

    liminal_dir = client.get(f"/api/files?run_id={run_id}&root=liminal")
    assert liminal_dir.status_code == 200
    assert liminal_dir.json()["kind"] == "directory"

    bad_path = client.get(f"/api/files?run_id={run_id}&root=workdir&path=../secret.txt")
    assert bad_path.status_code == 400

    events = client.get(f"/api/runs/{run_id}/events")
    assert events.status_code == 200
    assert events.json()

    with client.stream("GET", f"/api/runs/{run_id}/stream") as stream_response:
        assert stream_response.status_code == 200
        body = "".join(chunk.decode() if isinstance(chunk, bytes) else chunk for chunk in stream_response.iter_text())
    assert "run_finished" in body or "keep-alive" in body
