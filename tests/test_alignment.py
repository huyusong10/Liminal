from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from loopora.bundles import bundle_to_yaml
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


def _confirm_alignment_agreement(service, session_id: str, *final_statuses: str) -> dict:
    agreement = _wait_for_status(service, session_id, "waiting_user")
    assert agreement["alignment_stage"] == "agreement_ready"
    assert agreement["working_agreement"]["summary"]
    assert agreement["working_agreement"]["readiness_evidence"]["task_scope"]
    service.append_alignment_message(session_id, "确认")
    return _wait_for_status(service, session_id, *(final_statuses or ("ready",)))


def test_alignment_service_writes_validates_previews_imports_and_runs(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="Build a focused starter experience.",
    )
    session = _confirm_alignment_agreement(service, created["id"])

    bundle_path = Path(session["bundle_path"])
    artifact_root = sample_workdir / ".loopora" / "alignment_sessions" / session["id"]
    assert bundle_path == artifact_root / "artifacts" / "bundle.yml"
    assert bundle_path.exists()
    assert session["validation"]["ok"] is True
    assert (artifact_root / "manifest.json").exists()
    assert (artifact_root / "conversation" / "transcript.jsonl").exists()
    assert (artifact_root / "agreement" / "current.json").exists()
    assert (artifact_root / "artifacts" / "validation.json").exists()
    assert (artifact_root / "events" / "events.jsonl").exists()
    invocation_dir = artifact_root / "invocations" / "0001"
    assert (invocation_dir / "prompt.md").exists()
    assert (invocation_dir / "schema.json").exists()
    assert (invocation_dir / "output.json").exists()
    assert (invocation_dir / "stdout.log").exists()
    assert (invocation_dir / "stderr.log").exists()
    invocation_output = json.loads((invocation_dir / "output.json").read_text(encoding="utf-8"))
    assert "bundle_yaml" not in invocation_output
    assert invocation_output["bundle_written"] is True
    assert invocation_output["bundle_path"] == str(bundle_path)
    manifest = json.loads((artifact_root / "manifest.json").read_text(encoding="utf-8"))
    assert "transcript" not in manifest
    assert "validation" not in manifest
    assert "working_agreement" not in manifest
    assert "Build a focused starter experience." in (artifact_root / "conversation" / "transcript.jsonl").read_text(encoding="utf-8")
    assert session["alignment_stage"] == "ready"

    preview = service.get_alignment_bundle(session["id"])
    assert preview["ok"] is True
    assert preview["bundle"]["loop"]["workdir"] == str(sample_workdir.resolve())
    assert preview["workflow_preview"]["roles"][0]["name"] == "Focused Builder"
    assert preview["control_summary"]["gatekeeper"]["requires_evidence_refs"] is True
    assert "Ship the focused starter experience" in preview["spec_rendered_html"]

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
    assert session["native_resume_available"] is True
    assert session["executor_session_ref"]["session_id"]


def test_alignment_prompt_and_source_sync_follow_user_language(service_factory, sample_workdir: Path) -> None:
    service = service_factory(scenario="success")

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="请帮我生成一个中文任务的循环方案。",
    )
    session = _confirm_alignment_agreement(service, created["id"])
    artifact_root = Path(session["artifact_dir"])
    prompt_text = (artifact_root / "invocations" / "0001" / "prompt.md").read_text(encoding="utf-8")

    assert "User language hint: `Chinese" in prompt_text
    assert "Assume you know nothing about Loopora except what is embedded below." in prompt_text
    assert "Loopora Product Primer" in prompt_text
    assert "local-first platform for composing, running, and observing long-running AI Agent tasks" in prompt_text
    assert "Preserve Loopora domain terms exactly" in prompt_text
    assert "Alignment Playbook" in prompt_text
    assert "Alignment Quality Rubric" in prompt_text
    assert "Workdir Snapshot" in prompt_text
    synced = service.sync_alignment_bundle_from_file(session["id"])

    assert synced["ok"] is True
    refreshed = service.get_alignment_session(session["id"])
    assert "已重新读取 bundle.yml" in refreshed["transcript"][-1]["content"]


def test_alignment_service_blocks_premature_bundle_output(service_factory, sample_workdir: Path) -> None:
    service = service_factory(scenario="alignment_premature_bundle")

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="Build a starter experience.",
    )
    session = _wait_for_status(service, created["id"], "waiting_user")

    assert not Path(session["bundle_path"]).exists()
    assert "对齐" in session["transcript"][-1]["content"]
    events = service.list_alignment_events(created["id"])
    assert any(event["event_type"] == "alignment_stage_blocked" for event in events)


def test_alignment_service_blocks_bundle_without_readiness_evidence(service_factory, sample_workdir: Path) -> None:
    service = service_factory(scenario="alignment_missing_readiness_evidence")

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="Build a starter experience, but do not explain the posture evidence.",
    )
    _wait_for_status(service, created["id"], "waiting_user")
    service.append_alignment_message(created["id"], "确认")
    session = _wait_for_status(service, created["id"], "waiting_user")

    assert not Path(session["bundle_path"]).exists()
    assert "对齐证据" in session["transcript"][-1]["content"]
    events = service.list_alignment_events(created["id"])
    assert any(event["event_type"] == "alignment_stage_blocked" for event in events)


def test_alignment_service_reuses_executor_session_ref_between_turns(service_factory, sample_workdir: Path) -> None:
    service = service_factory(scenario="alignment_question")

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="I need help shaping this task.",
    )
    first = _wait_for_status(service, created["id"], "waiting_user")
    first_session_id = first["executor_session_ref"]["session_id"]

    service.append_alignment_message(created["id"], "更怕做糙。")
    second = _wait_for_status(service, created["id"], "waiting_user")

    assert second["executor_session_ref"]["session_id"] == first_session_id
    events = service.list_alignment_events(created["id"])
    assert any(event["event_type"] == "alignment_executor_session_ref" for event in events)


def test_alignment_service_falls_back_when_native_resume_fails(service_factory, sample_workdir: Path) -> None:
    service = service_factory(scenario="alignment_resume_failure")

    session = service.create_alignment_session(
        workdir=sample_workdir,
        message="Generate a bundle after resume trouble.",
        start_immediately=False,
    )
    service.repository.update_alignment_session(session["id"], executor_session_ref={"session_id": "stale-session"})
    service.start_alignment_session_async(session["id"])
    _wait_for_status(service, session["id"], "waiting_user")
    service.repository.update_alignment_session(
        session["id"],
        alignment_stage="confirmed",
        working_agreement={"summary": "Confirmed test agreement.", "confirmed_at": "test"},
    )
    service.start_alignment_session_async(session["id"])
    ready = _wait_for_status(service, session["id"], "ready")

    assert ready["validation"]["ok"] is True
    events = service.list_alignment_events(session["id"])
    assert any(event["event_type"] == "alignment_native_resume_fallback" for event in events)


def test_alignment_service_repairs_invalid_bundle_once(service_factory, sample_workdir: Path) -> None:
    service = service_factory(scenario="alignment_invalid_then_valid")

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="Generate a bundle, and recover if the first draft is malformed.",
    )
    session = _confirm_alignment_agreement(service, created["id"])

    assert session["repair_attempts"] == 1
    assert session["validation"]["ok"] is True
    events = service.list_alignment_events(session["id"])
    assert any(event["event_type"] == "alignment_repair_started" for event in events)


def test_alignment_service_repairs_semantically_incomplete_bundle_once(service_factory, sample_workdir: Path) -> None:
    service = service_factory(scenario="alignment_semantic_invalid_then_valid")

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="Generate a semantically complete bundle.",
    )
    session = _confirm_alignment_agreement(service, created["id"])

    assert session["repair_attempts"] == 1
    assert session["validation"]["ok"] is True
    failed_events = [
        event for event in service.list_alignment_events(created["id"]) if event["event_type"] == "alignment_validation_failed"
    ]
    assert failed_events
    assert "semantic lint" in failed_events[0]["payload"]["error"]


def test_alignment_service_fails_after_invalid_repair(service_factory, sample_workdir: Path) -> None:
    service = service_factory(scenario="alignment_invalid")

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="Generate a bundle that remains invalid.",
    )
    session = _confirm_alignment_agreement(service, created["id"], "failed")

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
    _wait_for_status(service, session_id, "waiting_user")
    confirm_response = client.post(f"/api/alignments/sessions/{session_id}/messages", json={"message": "确认"})
    assert confirm_response.status_code == 200
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

    list_response = client.get("/api/alignments/sessions")
    assert list_response.status_code == 200
    assert list_response.json()["sessions"][0]["id"] == session_id
    assert list_response.json()["sessions"][0]["native_resume_available"] is True

    bundle_response = client.get(f"/api/alignments/sessions/{session_id}/bundle")
    assert bundle_response.status_code == 200
    bundle_payload = bundle_response.json()
    assert bundle_payload["ok"] is True
    assert bundle_payload["workflow_preview"]["roles"][0]["archetype"] == "builder"

    bundle_path = Path(service.get_alignment_session(session_id)["bundle_path"])
    bundle_path.write_text(
        bundle_path.read_text(encoding="utf-8").replace("Aligned Starter Bundle", "Synced Starter Bundle", 1),
        encoding="utf-8",
    )
    sync_response = client.post(f"/api/alignments/sessions/{session_id}/bundle/sync")
    assert sync_response.status_code == 200
    sync_payload = sync_response.json()
    assert sync_payload["ok"] is True
    assert sync_payload["metadata"]["name"] == "Synced Starter Bundle"
    assert sync_payload["session"]["status"] == "ready"
    assert any(
        event["event_type"] == "alignment_bundle_synced"
        for event in service.list_alignment_events(session_id)
    )

    import_response = client.post(
        f"/api/alignments/sessions/{session_id}/import",
        json={"start_immediately": False},
    )
    assert import_response.status_code == 201
    assert import_response.json()["bundle"]["id"]
    assert import_response.json()["session"]["status"] == "imported"

    delete_response = client.delete(f"/api/alignments/sessions/{session_id}")
    assert delete_response.status_code == 200
    assert delete_response.json()["deleted"] is True
    assert client.get(f"/api/alignments/sessions/{session_id}").status_code == 400
    assert client.get("/api/alignments/sessions").json()["sessions"] == []


def test_alignment_improvement_session_can_start_from_existing_bundle(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = service.create_loop(
        name="Improvement Source Loop",
        spec_path=sample_spec_file,
        workdir=sample_workdir,
        model="gpt-5.4-mini",
        reasoning_effort="medium",
        max_iters=2,
        max_role_retries=1,
        delta_threshold=0.005,
        trigger_window=2,
        regression_window=2,
        role_models={},
    )
    source = service.import_bundle_text(
        bundle_to_yaml(
            service.derive_bundle_from_loop(
                loop["id"],
                name="Improvement Source Bundle",
                description="Start from an existing bundle.",
                collaboration_summary="Prefer evidence before changing posture.",
            )
        )
    )

    session = service.create_bundle_revision_session(source["id"], start_immediately=False)

    agreement = session["working_agreement"]
    assert agreement["mode"] == "improvement"
    assert agreement["source"]["source_type"] == "bundle"
    assert agreement["source"]["source_bundle_id"] == source["id"]
    assert agreement["source"]["source_run_id"] == ""
    preview = service.get_alignment_bundle(session["id"])
    assert preview["ok"] is True
    assert preview["bundle"]["metadata"]["source_bundle_id"] == source["id"]
    assert preview["bundle"]["metadata"]["revision"] == source["revision"] + 1
    events = service.list_alignment_events(session["id"])
    assert any(event["event_type"] == "alignment_bundle_improvement_seeded" for event in events)


def test_alignment_improvement_session_can_start_from_run_evidence(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = service.create_loop(
        name="Run Evidence Source Loop",
        spec_path=sample_spec_file,
        workdir=sample_workdir,
        model="gpt-5.4-mini",
        reasoning_effort="medium",
        max_iters=2,
        max_role_retries=1,
        delta_threshold=0.005,
        trigger_window=2,
        regression_window=2,
        role_models={},
    )
    source = service.import_bundle_text(
        bundle_to_yaml(
            service.derive_bundle_from_loop(
                loop["id"],
                name="Run Evidence Source Bundle",
                description="Start from run evidence.",
                collaboration_summary="Use GateKeeper evidence to improve the plan.",
            )
        )
    )
    run = service.rerun(source["loop_id"])

    session = service.create_run_revision_session(run["id"], start_immediately=False)

    agreement = session["working_agreement"]
    assert agreement["mode"] == "improvement"
    assert agreement["source"]["source_type"] == "run"
    assert agreement["source"]["source_bundle_id"] == source["id"]
    assert agreement["source"]["source_run_id"] == run["id"]
    assert "coverage_summary" in agreement["source"]
    assert "gatekeeper_verdict" in agreement["source"]
    preview = service.get_alignment_bundle(session["id"])
    assert preview["ok"] is True
    assert preview["bundle"]["metadata"]["source_bundle_id"] == source["id"]


def test_alignment_api_creates_improvement_sessions_from_bundle_and_run(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = service.create_loop(
        name="API Improvement Source Loop",
        spec_path=sample_spec_file,
        workdir=sample_workdir,
        model="gpt-5.4-mini",
        reasoning_effort="medium",
        max_iters=2,
        max_role_retries=1,
        delta_threshold=0.005,
        trigger_window=2,
        regression_window=2,
        role_models={},
    )
    source = service.import_bundle_text(
        bundle_to_yaml(
            service.derive_bundle_from_loop(
                loop["id"],
                name="API Improvement Source Bundle",
                description="API improvement source.",
                collaboration_summary="Keep the source posture visible.",
            )
        )
    )
    run = service.rerun(source["loop_id"])
    client = TestClient(build_app(service=service))

    bundle_response = client.post(f"/api/bundles/{source['id']}/revise", json={"start_immediately": False})
    assert bundle_response.status_code == 201
    bundle_payload = bundle_response.json()
    assert bundle_payload["redirect_url"] == (
        f"/loops/new/bundle?alignment_session_id={bundle_payload['session']['id']}"
    )
    assert bundle_payload["session"]["working_agreement"]["mode"] == "improvement"
    assert bundle_payload["session"]["working_agreement"]["source"]["source_type"] == "bundle"
    assert bundle_payload["session"]["working_agreement"]["source"]["source_bundle_id"] == source["id"]

    run_response = client.post(f"/api/runs/{run['id']}/revise", json={"start_immediately": False})
    assert run_response.status_code == 201
    run_payload = run_response.json()
    assert run_payload["redirect_url"] == f"/loops/new/bundle?alignment_session_id={run_payload['session']['id']}"
    assert run_payload["session"]["working_agreement"]["mode"] == "improvement"
    assert run_payload["session"]["working_agreement"]["source"]["source_type"] == "run"
    assert run_payload["session"]["working_agreement"]["source"]["source_run_id"] == run["id"]


def test_alignment_service_lazily_migrates_legacy_flat_artifacts(service_factory, sample_workdir: Path) -> None:
    service = service_factory(scenario="success")
    session_id = "align_legacy"
    legacy_root = sample_workdir / ".loopora" / "alignment_sessions" / session_id
    legacy_root.mkdir(parents=True)
    legacy_bundle = legacy_root / "bundle.yml"
    legacy_bundle.write_text("version: 1\nmetadata:\n  name: Legacy\n  revision: 1\n", encoding="utf-8")
    (legacy_root / "transcript.jsonl").write_text(
        json.dumps({"role": "user", "content": "Legacy prompt"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (legacy_root / "working_agreement.json").write_text('{"summary":"Legacy agreement"}\n', encoding="utf-8")
    (legacy_root / "validation.json").write_text('{"ok":true}\n', encoding="utf-8")
    (legacy_root / "alignment_prompt_0.md").write_text("legacy prompt\n", encoding="utf-8")
    (legacy_root / "alignment_schema.json").write_text("{}\n", encoding="utf-8")
    (legacy_root / "alignment_output_0.json").write_text(
        json.dumps({"assistant_message": "done", "bundle_yaml": "raw yaml"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    service.repository.create_alignment_session(
        {
            "id": session_id,
            "status": "ready",
            "workdir": str(sample_workdir),
            "bundle_path": str(legacy_bundle),
            "transcript": [{"role": "user", "content": "Legacy prompt", "created_at": "now"}],
            "validation": {"ok": True},
            "alignment_stage": "ready",
            "working_agreement": {"summary": "Legacy agreement"},
            "executor_session_ref": {},
        }
    )

    migrated = service.get_alignment_session(session_id)
    root = Path(migrated["artifact_dir"])

    assert Path(migrated["bundle_path"]) == root / "artifacts" / "bundle.yml"
    assert (root / "artifacts" / "bundle.yml").exists()
    assert (root / "conversation" / "transcript.jsonl").exists()
    assert (root / "agreement" / "current.json").exists()
    assert (root / "artifacts" / "validation.json").exists()
    output = json.loads((root / "invocations" / "0001" / "output.json").read_text(encoding="utf-8"))
    assert "bundle_yaml" not in output
    assert output["bundle_sha256"]
    assert (root / "legacy" / "bundle.yml").exists()


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
