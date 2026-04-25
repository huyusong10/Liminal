from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from loopora.web import build_app


def _wait_for_status(service, session_id: str, *statuses: str, timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    expected = set(statuses)
    while time.time() < deadline:
        session = service.get_alignment_session(session_id)
        if session["status"] in expected:
            return session
        time.sleep(0.05)
    session = service.get_alignment_session(session_id)
    raise AssertionError(f"alignment session stayed in {session['status']}, expected {sorted(expected)}")


def test_alignment_service_writes_validates_previews_imports_and_runs(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="Build a focused starter experience.",
    )
    session = _wait_for_status(service, created["id"], "ready")

    bundle_path = Path(session["bundle_path"])
    assert bundle_path == sample_workdir / ".loopora" / "alignment_sessions" / session["id"] / "bundle.yml"
    assert bundle_path.exists()
    assert session["validation"]["ok"] is True

    preview = service.get_alignment_bundle(session["id"])
    assert preview["ok"] is True
    assert preview["bundle"]["loop"]["workdir"] == str(sample_workdir.resolve())
    assert preview["workflow_preview"]["roles"][0]["name"] == "Focused Builder"
    assert "Ship the requested behavior" in preview["spec_rendered_html"]

    imported = service.import_alignment_bundle(session["id"], start_immediately=True)
    assert imported["bundle"]["loop_id"]
    assert imported["run"]["id"]
    final_session = service.get_alignment_session(session["id"])
    assert final_session["status"] == "running_loop"
    assert final_session["linked_bundle_id"] == imported["bundle"]["id"]
    assert final_session["linked_loop_id"] == imported["bundle"]["loop_id"]
    assert final_session["linked_run_id"] == imported["run"]["id"]


def test_alignment_service_waits_for_user_question(service_factory, sample_workdir: Path) -> None:
    service = service_factory(scenario="alignment_question")

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="I need help shaping this task.",
    )
    session = _wait_for_status(service, created["id"], "waiting_user")

    assert session["transcript"][-1]["role"] == "assistant"
    assert "做慢" in session["transcript"][-1]["content"]
    assert not Path(session["bundle_path"]).exists()


def test_alignment_service_repairs_invalid_bundle_once(service_factory, sample_workdir: Path) -> None:
    service = service_factory(scenario="alignment_invalid_then_valid")

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="Generate a bundle, and recover if the first draft is malformed.",
    )
    session = _wait_for_status(service, created["id"], "ready")

    assert session["repair_attempts"] == 1
    assert session["validation"]["ok"] is True
    events = service.list_alignment_events(session["id"])
    assert any(event["event_type"] == "alignment_repair_started" for event in events)


def test_alignment_service_fails_after_invalid_repair(service_factory, sample_workdir: Path) -> None:
    service = service_factory(scenario="alignment_invalid")

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="Generate a bundle that remains invalid.",
    )
    session = _wait_for_status(service, created["id"], "failed")

    assert session["repair_attempts"] == 1
    assert session["validation"]["ok"] is False
    assert "collaboration_summary" in session["error_message"]


def test_alignment_service_normalizes_custom_command_settings(service_factory, sample_workdir: Path) -> None:
    service = service_factory(scenario="success")

    session = service.create_alignment_session(
        workdir=sample_workdir,
        executor_kind="custom",
        executor_mode="preset",
        command_cli="my-aligner",
        command_args_text="{prompt}\n--output\n{output_path}",
        start_immediately=False,
    )

    assert session["executor_kind"] == "custom"
    assert session["executor_mode"] == "command"
    assert session["command_cli"] == "my-aligner"
    assert session["model"] == ""
    assert session["reasoning_effort"] == ""


def test_alignment_api_covers_session_events_bundle_and_import(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    response = client.post(
        "/api/alignments/sessions",
        json={"workdir": str(sample_workdir), "message": "Create a runnable bundle."},
    )
    assert response.status_code == 201
    session_id = response.json()["session"]["id"]
    _wait_for_status(service, session_id, "ready")

    session_response = client.get(f"/api/alignments/sessions/{session_id}")
    assert session_response.status_code == 200
    assert session_response.json()["session"]["status"] == "ready"

    events_response = client.get(f"/api/alignments/sessions/{session_id}/events")
    assert events_response.status_code == 200
    assert any(event["event_type"] == "alignment_ready" for event in events_response.json())

    with client.stream("GET", f"/api/alignments/sessions/{session_id}/stream") as stream_response:
        assert stream_response.status_code == 200
        body = "".join(chunk.decode() if isinstance(chunk, bytes) else chunk for chunk in stream_response.iter_text())
    assert "alignment_ready" in body

    bundle_response = client.get(f"/api/alignments/sessions/{session_id}/bundle")
    assert bundle_response.status_code == 200
    bundle_payload = bundle_response.json()
    assert bundle_payload["ok"] is True
    assert bundle_payload["workflow_preview"]["roles"][0]["archetype"] == "builder"

    import_response = client.post(
        f"/api/alignments/sessions/{session_id}/import",
        json={"start_immediately": False},
    )
    assert import_response.status_code == 201
    assert import_response.json()["bundle"]["id"]
    assert import_response.json()["session"]["status"] == "imported"


def test_alignment_api_rejects_busy_messages_and_allows_continue_after_cancel(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success", role_delay=0.4)
    client = TestClient(build_app(service=service))

    response = client.post(
        "/api/alignments/sessions",
        json={"workdir": str(sample_workdir), "message": "Start slowly."},
    )
    assert response.status_code == 201
    session_id = response.json()["session"]["id"]

    busy = client.post(f"/api/alignments/sessions/{session_id}/messages", json={"message": "Too soon."})
    assert busy.status_code == 400
    assert "already running" in busy.json()["error"]

    cancelled = client.post(f"/api/alignments/sessions/{session_id}/cancel")
    assert cancelled.status_code == 200
    _wait_for_status(service, session_id, "failed")

    continued = client.post(f"/api/alignments/sessions/{session_id}/messages", json={"message": "Continue after cancel."})
    assert continued.status_code == 200
    assert continued.json()["session"]["status"] == "running"
