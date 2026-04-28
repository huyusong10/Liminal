from __future__ import annotations

import io
import json
import re
import time
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from loopora.bundles import bundle_to_yaml
from loopora.settings import app_home, configure_logging
from loopora.web_url_utils import safe_attachment_filename, safe_local_return_path, with_query_params
import loopora.web as web_module
from loopora.web import build_app


def _read_service_log_records() -> list[dict]:
    return [
        json.loads(line)
        for line in (app_home() / "logs" / "service.log").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_web_url_helpers_keep_redirects_and_filenames_local() -> None:
    assert safe_local_return_path("/bundles/bundle-1?tab=roles#surface") == "/bundles/bundle-1?tab=roles#surface"
    assert safe_local_return_path("https://example.test/bundles/1") is None
    assert safe_local_return_path("//example.test/bundles/1") is None
    assert safe_local_return_path("bundles/1") is None
    assert safe_local_return_path("/bundles\\example.test") is None
    assert safe_local_return_path("/bundles/1\r\nLocation: https://example.test") is None
    assert with_query_params("/bundles/bundle-1?tab=roles#surface", surface_updated="workflow") == (
        "/bundles/bundle-1?tab=roles&surface_updated=workflow#surface"
    )
    assert safe_attachment_filename('Bad/Name" \r\n injected.yml') == "Bad-Name-injected.yml"


def test_api_loop_creation_run_preview_and_stream(
    service_factory,
    sample_spec_file: Path,
    sample_spec_text: str,
    sample_workdir: Path,
) -> None:
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

    loopora_dir = client.get(f"/api/files?run_id={run_id}&root=loopora")
    assert loopora_dir.status_code == 200
    assert loopora_dir.json()["kind"] == "directory"

    invalid_root = client.get(f"/api/files?run_id={run_id}&root=archive")
    assert invalid_root.status_code == 422

    artifacts = client.get(f"/api/runs/{run_id}/artifacts")
    assert artifacts.status_code == 200
    artifact_payload = artifacts.json()
    assert any(item["id"] == "original-spec" and item["available"] for item in artifact_payload)
    assert any(item["id"] == "summary" and item["available"] for item in artifact_payload)
    assert any(item["id"] == "evidence-ledger" and item["available"] for item in artifact_payload)

    original_spec_artifact = client.get(f"/api/runs/{run_id}/artifacts/original-spec")
    assert original_spec_artifact.status_code == 200
    assert original_spec_artifact.json()["kind"] == "file"
    assert original_spec_artifact.json()["content"] == sample_spec_text

    summary_artifact = client.get(f"/api/runs/{run_id}/artifacts/summary")
    assert summary_artifact.status_code == 200
    assert summary_artifact.json()["kind"] == "file"
    assert "Loopora Run Summary" in summary_artifact.json()["content"]

    latest_state_artifact = client.get(f"/api/runs/{run_id}/artifacts/latest-state")
    assert latest_state_artifact.status_code == 200
    assert latest_state_artifact.json()["kind"] == "file"
    assert "\"latest_iteration\"" in latest_state_artifact.json()["content"]

    evidence_artifact = client.get(f"/api/runs/{run_id}/artifacts/evidence-ledger")
    assert evidence_artifact.status_code == 200
    assert evidence_artifact.json()["kind"] == "file"
    assert "gatekeeper" in evidence_artifact.json()["content"]

    binary_path = sample_workdir / ".DS_Store"
    binary_path.write_bytes(b"\x00\x01\x02binary-data")
    binary_preview = client.get(f"/api/files?run_id={run_id}&root=workdir&path=.DS_Store")
    assert binary_preview.status_code == 200
    assert binary_preview.json()["kind"] == "file"
    assert binary_preview.json()["is_binary"] is True

    bad_path = client.get(f"/api/files?run_id={run_id}&root=workdir&path=../secret.txt")
    assert bad_path.status_code == 400

    sibling_dir = sample_workdir.parent / "workdir-shadow"
    sibling_dir.mkdir()
    (sibling_dir / "secret.txt").write_text("nope", encoding="utf-8")
    sneaky_path = client.get(f"/api/files?run_id={run_id}&root=workdir&path=../workdir-shadow/secret.txt")
    assert sneaky_path.status_code == 400

    unsafe_md = sample_workdir / "unsafe.md"
    unsafe_md.write_text("# Title\n\n<script>alert('xss')</script>\n", encoding="utf-8")
    unsafe_preview = client.get(f"/api/files?run_id={run_id}&root=workdir&path=unsafe.md")
    assert unsafe_preview.status_code == 200
    assert "<script>" not in unsafe_preview.json()["rendered_html"]
    assert "&lt;script&gt;alert" in unsafe_preview.json()["rendered_html"]

    events = client.get(f"/api/runs/{run_id}/events")
    assert events.status_code == 200
    event_payload = events.json()
    assert event_payload

    with client.stream("GET", f"/api/runs/{run_id}/stream") as stream_response:
        assert stream_response.status_code == 200
        body = "".join(chunk.decode() if isinstance(chunk, bytes) else chunk for chunk in stream_response.iter_text())
    assert "run_finished" in body or "keep-alive" in body

    latest_event_id = event_payload[-1]["id"]
    with client.stream("GET", f"/api/runs/{run_id}/stream?after_id={latest_event_id}") as stream_response:
        assert stream_response.status_code == 200
        delta_body = "".join(chunk.decode() if isinstance(chunk, bytes) else chunk for chunk in stream_response.iter_text())
    assert "run_started" not in delta_body

    reconnect_from = event_payload[0]["id"]
    with client.stream(
        "GET",
        f"/api/runs/{run_id}/stream",
        headers={"Last-Event-ID": str(reconnect_from)},
    ) as stream_response:
        assert stream_response.status_code == 200
        reconnect_body = "".join(chunk.decode() if isinstance(chunk, bytes) else chunk for chunk in stream_response.iter_text())
    assert f"id: {reconnect_from}\n" not in reconnect_body


def test_api_run_key_takeaways_returns_iteration_role_conclusions(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = service.create_loop(
        name="Takeaway Loop",
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
    run = service.rerun(loop["id"])

    client = TestClient(build_app(service=service))
    response = client.get(f"/api/runs/{run['id']}/key-takeaways")

    assert response.status_code == 200
    payload = response.json()
    assert payload["build_dir"] == str(sample_workdir.resolve())
    assert payload["log_dir"].endswith(f"/.loopora/runs/{run['id']}")
    assert payload["iteration_count"] >= 1
    assert payload["role_conclusion_count"] >= 2
    latest_iteration = payload["iterations"][0]
    assert latest_iteration["display_iter"] >= 1
    assert latest_iteration["summary"]
    role_names = {item["role_name"] for item in latest_iteration["roles"]}
    assert "Builder" in role_names
    assert "GateKeeper" in role_names
    gatekeeper = next(item for item in latest_iteration["roles"] if item["role_name"] == "GateKeeper")
    assert gatekeeper["composite_score"] is not None


def test_api_reveal_path_uses_native_host_shortcut(monkeypatch, service_factory, sample_workdir: Path) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))
    called: list[str] = []

    def fake_reveal(path: str) -> str:
        called.append(path)
        return path

    monkeypatch.setattr(web_module, "reveal_path", fake_reveal)
    response = client.post("/api/system/reveal-path", json={"path": str(sample_workdir)})

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert called == [str(sample_workdir)]


def test_api_json_endpoints_reject_invalid_json_body(service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    response = client.post(
        "/api/markdown/render",
        content="{",
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 400
    assert "invalid JSON body" in response.json()["error"]


def test_api_json_endpoints_require_object_bodies(service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    response = client.post("/api/markdown/render", json=["not", "an", "object"])

    assert response.status_code == 400
    assert response.json()["error"] == "request body must be a JSON object"


def test_api_file_preview_reports_json_parse_errors(service_factory, sample_spec_file: Path, sample_workdir: Path) -> None:
    service = service_factory(scenario="success")
    loop = service.create_loop(
        name="JSON Preview Loop",
        spec_path=sample_spec_file,
        workdir=sample_workdir,
        model="gpt-5.4",
        reasoning_effort="medium",
        max_iters=1,
        max_role_retries=1,
        delta_threshold=0.005,
        trigger_window=2,
        regression_window=2,
        role_models={},
    )
    run = service.start_run(loop["id"])
    broken_json_path = sample_workdir / "broken.json"
    broken_json_path.write_text("{\n", encoding="utf-8")

    client = TestClient(build_app(service=service))
    response = client.get(f"/api/files?run_id={run['id']}&root=workdir&path=broken.json")

    assert response.status_code == 200
    payload = response.json()
    assert payload["kind"] == "file"
    assert payload["content"] == "{\n"
    assert payload["parse_error"]


def test_api_file_preview_keeps_valid_jsonl_lines_when_some_are_broken(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = service.create_loop(
        name="JSONL Preview Loop",
        spec_path=sample_spec_file,
        workdir=sample_workdir,
        model="gpt-5.4",
        reasoning_effort="medium",
        max_iters=1,
        max_role_retries=1,
        delta_threshold=0.005,
        trigger_window=2,
        regression_window=2,
        role_models={},
    )
    run = service.start_run(loop["id"])
    log_path = sample_workdir / "events.jsonl"
    log_path.write_text('{"event":"good"}\n{\n{"event":"also-good"}\n', encoding="utf-8")

    client = TestClient(build_app(service=service))
    response = client.get(f"/api/files?run_id={run['id']}&root=workdir&path=events.jsonl")

    assert response.status_code == 200
    payload = response.json()
    assert payload["kind"] == "file"
    assert '"event": "good"' in payload["content"]
    assert '"event": "also-good"' in payload["content"]
    assert payload["jsonl_parse_errors"] == [{"line": 2, "error": "Expecting property name enclosed in double quotes"}]


def test_api_run_events_and_stream_require_a_real_run(service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    events_response = client.get("/api/runs/missing-run/events")
    assert events_response.status_code == 400
    assert "unknown run" in events_response.json()["error"]

    stream_response = client.get("/api/runs/missing-run/stream")
    assert stream_response.status_code == 400
    assert "unknown run" in stream_response.json()["error"]


def test_api_runtime_activity_reports_running_runs(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success", role_delay=0.4)
    loop = service.create_loop(
        name="Runtime Activity Loop",
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
    run = service.start_run(loop["id"])
    service.start_run_async(run["id"])

    deadline = time.time() + 5
    while time.time() < deadline:
        current = service.get_run(run["id"])
        if current["status"] == "running":
            break
        time.sleep(0.05)

    client = TestClient(build_app(service=service))
    response = client.get("/api/runtime/activity")

    assert response.status_code == 200
    payload = response.json()
    assert payload["running_count"] >= 1
    assert payload["has_running_runs"] is True
    assert any(item["id"] == run["id"] and item["loop_name"] == "Runtime Activity Loop" for item in payload["runs"])

    service.stop_run(run["id"])


def test_api_run_stream_emits_stream_error_on_backend_failure() -> None:
    class FlakyService:
        def get_run(self, run_id: str) -> dict:
            return {"id": run_id, "status": "running", "loop_id": "loop_test"}

        def stream_events(self, run_id: str, after_id: int = 0, limit: int = 200) -> list[dict]:
            raise RuntimeError("database unavailable")

    client = TestClient(build_app(service=FlakyService()))

    with client.stream("GET", "/api/runs/run_test/stream") as response:
        assert response.status_code == 200
        body = "".join(chunk.decode() if isinstance(chunk, bytes) else chunk for chunk in response.iter_text())

    assert "event: stream_error" in body
    assert "database unavailable" in body


def test_api_run_stream_logs_invalid_resume_cursor_and_keeps_request_cursor() -> None:
    configure_logging()
    captured: dict[str, int] = {}

    class CursorAwareService:
        def get_run(self, run_id: str) -> dict:
            return {"id": run_id, "status": "succeeded", "loop_id": "loop_test"}

        def stream_events(self, run_id: str, after_id: int = 0, limit: int = 200) -> list[dict]:
            captured["after_id"] = after_id
            return []

    client = TestClient(build_app(service=CursorAwareService()))

    with client.stream(
        "GET",
        "/api/runs/run_test/stream?after_id=7",
        headers={"Last-Event-ID": "not-a-number"},
    ) as response:
        assert response.status_code == 200
        assert "".join(chunk.decode() if isinstance(chunk, bytes) else chunk for chunk in response.iter_text()) == ""

    assert captured["after_id"] == 7
    record = next(
        item
        for item in _read_service_log_records()
        if item["event"] == "web.run_stream.resume_cursor_invalid"
    )
    assert record["run_id"] == "run_test"
    assert record["context"]["after_id"] == 7
    assert record["context"]["invalid_last_event_id"] == "not-a-number"


def test_web_logs_completed_requests(service_factory) -> None:
    configure_logging()
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    response = client.get("/tutorial")

    assert response.status_code == 200
    records = _read_service_log_records()
    record = next(
        item
        for item in records
        if item["event"] == "web.request.completed"
        and item["context"]["request_path"] == "/tutorial"
    )
    assert record["context"]["status_code"] == 200
    assert record["context"]["duration_ms"] >= 0


def test_api_stop_run_rejects_finished_runs(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = service.create_loop(
        name="Finished Loop",
        spec_path=sample_spec_file,
        workdir=sample_workdir,
        model="gpt-5.4",
        reasoning_effort="medium",
        max_iters=2,
        max_role_retries=1,
        delta_threshold=0.005,
        trigger_window=2,
        regression_window=2,
        role_models={},
    )
    run = service.rerun(loop["id"])
    client = TestClient(build_app(service=service))

    response = client.post(f"/api/runs/{run['id']}/stop")

    assert response.status_code == 400
    assert "cannot stop run in status" in response.json()["error"]


def test_api_loop_creation_supports_provider_specific_defaults(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    claude_response = client.post(
        "/api/loops",
        json={
            "name": "Claude Loop",
            "spec_path": str(sample_spec_file),
            "workdir": str(sample_workdir),
            "executor_kind": "claude",
            "model": "",
            "reasoning_effort": "xhigh",
            "max_iters": 3,
            "max_role_retries": 1,
            "delta_threshold": 0.005,
            "trigger_window": 2,
            "regression_window": 2,
            "start_immediately": False,
        },
    )
    assert claude_response.status_code == 201
    claude_loop = claude_response.json()["loop"]
    assert claude_loop["executor_kind"] == "claude"
    assert claude_loop["model"] == ""
    assert claude_loop["reasoning_effort"] == "max"

    opencode_response = client.post(
        "/api/loops",
        json={
            "name": "OpenCode Loop",
            "spec_path": str(sample_spec_file),
            "workdir": str(sample_workdir),
            "executor_kind": "opencode",
            "model": "",
            "reasoning_effort": "default",
            "max_iters": 3,
            "max_role_retries": 1,
            "delta_threshold": 0.005,
            "trigger_window": 2,
            "regression_window": 2,
            "start_immediately": False,
        },
    )
    assert opencode_response.status_code == 201
    opencode_loop = opencode_response.json()["loop"]
    assert opencode_loop["executor_kind"] == "opencode"
    assert opencode_loop["model"] == ""
    assert opencode_loop["reasoning_effort"] == ""


def test_api_loop_creation_rejects_invalid_numeric_settings(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    response = client.post(
        "/api/loops",
        json={
            "name": "Broken Loop",
            "spec_path": str(sample_spec_file),
            "workdir": str(sample_workdir),
            "max_iters": "abc",
        },
    )

    assert response.status_code == 400
    assert "numeric loop settings" in response.json()["error"]


def test_api_loop_creation_supports_command_mode(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    response = client.post(
        "/api/loops",
        json={
            "name": "Command Loop",
            "spec_path": str(sample_spec_file),
            "workdir": str(sample_workdir),
            "executor_kind": "codex",
            "executor_mode": "command",
            "command_cli": "codex",
            "command_args_text": "\n".join(
                [
                    "exec",
                    "--json",
                    "--cd",
                    "{workdir}",
                    "--sandbox",
                    "{sandbox}",
                    "--output-schema",
                    "{schema_path}",
                    "--output-last-message",
                    "{output_path}",
                    "{prompt}",
                ]
            ),
            "model": "",
            "reasoning_effort": "",
            "max_iters": 3,
            "max_role_retries": 1,
            "delta_threshold": 0.005,
            "trigger_window": 2,
            "regression_window": 2,
            "start_immediately": False,
        },
    )

    assert response.status_code == 201
    loop = response.json()["loop"]
    assert loop["executor_mode"] == "command"
    assert loop["command_cli"] == "codex"
    assert "{schema_path}" in loop["command_args_text"]


def test_api_loop_creation_accepts_role_model_overrides(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    response = client.post(
        "/api/loops",
        json={
            "name": "Role Models Loop",
            "spec_path": str(sample_spec_file),
            "workdir": str(sample_workdir),
            "executor_kind": "codex",
            "model": "gpt-5.4",
            "reasoning_effort": "medium",
            "role_models": {
                "generator": "gpt-5.4-mini",
                "verifier": "gpt-5.4",
            },
            "max_iters": 3,
            "max_role_retries": 1,
            "delta_threshold": 0.005,
            "trigger_window": 2,
            "regression_window": 2,
            "start_immediately": False,
        },
    )

    assert response.status_code == 201
    loop = response.json()["loop"]
    assert loop["role_models_json"] == {
        "builder": "gpt-5.4-mini",
        "gatekeeper": "gpt-5.4",
    }


def test_prompt_template_download_and_validation_endpoints(service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    template_response = client.get("/api/prompts/templates/builder.md")
    assert template_response.status_code == 200
    markdown_text = template_response.text
    assert "archetype: builder" in markdown_text

    localized_template_response = client.get("/api/prompts/templates/builder.md?locale=zh")
    assert localized_template_response.status_code == 200
    assert "# Builder Prompt" in localized_template_response.text
    assert "archetype: builder" in localized_template_response.text

    validation_response = client.post(
        "/api/prompts/validate",
        json={
            "markdown": markdown_text,
            "archetype": "builder",
        },
    )
    assert validation_response.status_code == 200
    assert validation_response.json()["ok"] is True

    mismatch_response = client.post(
        "/api/prompts/validate",
        json={
            "markdown": markdown_text,
            "archetype": "gatekeeper",
        },
    )
    assert mismatch_response.status_code == 200
    assert mismatch_response.json()["ok"] is False


def test_api_can_create_orchestration_and_use_it_for_loop(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    orchestration_response = client.post(
        "/api/orchestrations",
        json={
            "name": "Custom Inspect First",
            "description": "Inspector before Builder.",
            "workflow": {"preset": "inspect_first"},
        },
    )
    assert orchestration_response.status_code == 201
    orchestration = orchestration_response.json()["orchestration"]
    assert orchestration["name"] == "Custom Inspect First"
    assert orchestration["workflow_json"]["preset"] == "inspect_first"

    list_response = client.get("/api/orchestrations")
    assert list_response.status_code == 200
    assert any(item["id"] == orchestration["id"] for item in list_response.json())

    update_response = client.put(
        f"/api/orchestrations/{orchestration['id']}",
        json={
            "name": "Custom Build First",
            "description": "Updated description.",
            "workflow": {"preset": "build_first"},
        },
    )
    assert update_response.status_code == 200
    updated_orchestration = update_response.json()["orchestration"]
    assert updated_orchestration["name"] == "Custom Build First"
    assert updated_orchestration["workflow_json"]["preset"] == "build_first"

    loop_response = client.post(
        "/api/loops",
        json={
            "name": "Uses Custom Orchestration",
            "spec_path": str(sample_spec_file),
            "workdir": str(sample_workdir),
            "orchestration_id": updated_orchestration["id"],
            "executor_kind": "codex",
            "model": "gpt-5.4",
            "reasoning_effort": "medium",
            "max_iters": 3,
            "max_role_retries": 1,
            "delta_threshold": 0.005,
            "trigger_window": 2,
            "regression_window": 2,
            "start_immediately": False,
        },
    )
    assert loop_response.status_code == 201
    loop = loop_response.json()["loop"]
    assert loop["orchestration"]["id"] == updated_orchestration["id"]
    assert loop["orchestration"]["name"] == "Custom Build First"
    assert loop["workflow_json"]["preset"] == "build_first"


def test_api_orchestration_hydrates_role_snapshots_from_role_definition_id(service_factory) -> None:
    service = service_factory(scenario="success")
    role_definition = service.create_role_definition(
        name="Release Builder",
        description="Ships focused release work.",
        archetype="builder",
        prompt_ref="release-builder.md",
        prompt_markdown="""---
version: 1
archetype: builder
---

Focus on safe release work.
""",
        executor_kind="claude",
        executor_mode="preset",
        model="gpt-5.4-mini",
        reasoning_effort="high",
    )
    client = TestClient(build_app(service=service))

    response = client.post(
        "/api/orchestrations",
        json={
            "name": "Uses Role Definition Snapshot",
            "description": "Hydrates missing role fields from a role definition.",
            "workflow": {
                "version": 1,
                "roles": [
                    {"id": "builder", "role_definition_id": role_definition["id"]},
                ],
                "steps": [
                    {"id": "builder_step", "role_id": "builder"},
                ],
            },
        },
    )

    assert response.status_code == 201
    orchestration = response.json()["orchestration"]
    builder_role = orchestration["workflow_json"]["roles"][0]
    assert builder_role["name"] == "Release Builder"
    assert builder_role["prompt_ref"] == "release-builder.md"
    assert builder_role["executor_kind"] == "claude"
    assert builder_role["model"] == "gpt-5.4-mini"
    assert orchestration["prompt_files_json"]["release-builder.md"].startswith("---\nversion: 1")


def test_api_orchestration_rejects_unknown_role_definition_ids(service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    response = client.post(
        "/api/orchestrations",
        json={
            "name": "Broken Role Definition Reference",
            "description": "Should fail fast.",
            "workflow": {
                "version": 1,
                "roles": [
                    {"id": "builder", "role_definition_id": "role_missing"},
                ],
                "steps": [
                    {"id": "builder_step", "role_id": "builder"},
                ],
            },
        },
    )

    assert response.status_code == 400
    assert "unknown role definition: role_missing" in response.json()["error"]


def test_api_orchestration_rejects_conflicting_role_definition_snapshot_fields(service_factory) -> None:
    service = service_factory(scenario="success")
    role_definition = service.create_role_definition(
        name="Release Builder",
        description="Ships focused release work.",
        archetype="builder",
        prompt_ref="release-builder.md",
        prompt_markdown="""---
version: 1
archetype: builder
---

Focus on safe release work.
""",
        executor_kind="claude",
        executor_mode="preset",
        model="gpt-5.4-mini",
        reasoning_effort="high",
    )
    client = TestClient(build_app(service=service))

    response = client.post(
        "/api/orchestrations",
        json={
            "name": "Conflicting Role Snapshot",
            "description": "Should fail when snapshot fields conflict with the role definition.",
            "workflow": {
                "version": 1,
                "roles": [
                    {
                        "id": "builder",
                        "role_definition_id": role_definition["id"],
                        "model": "gpt-5.4",
                    },
                ],
                "steps": [
                    {"id": "builder_step", "role_id": "builder"},
                ],
            },
        },
    )

    assert response.status_code == 400
    assert f"conflicts with role_definition_id {role_definition['id']} on model" in response.json()["error"]


def test_api_orchestration_rejects_conflicting_prompt_files_for_role_definition_id(service_factory) -> None:
    service = service_factory(scenario="success")
    role_definition = service.create_role_definition(
        name="Release Builder",
        description="Ships focused release work.",
        archetype="builder",
        prompt_ref="release-builder.md",
        prompt_markdown="""---
version: 1
archetype: builder
---

Focus on safe release work.
""",
        executor_kind="claude",
        executor_mode="preset",
        model="gpt-5.4-mini",
        reasoning_effort="high",
    )
    client = TestClient(build_app(service=service))

    response = client.post(
        "/api/orchestrations",
        json={
            "name": "Conflicting Role Prompt Snapshot",
            "description": "Should fail when prompt_files override a role definition prompt.",
            "workflow": {
                "version": 1,
                "roles": [
                    {
                        "id": "builder",
                        "role_definition_id": role_definition["id"],
                    },
                ],
                "steps": [
                    {"id": "builder_step", "role_id": "builder"},
                ],
            },
            "prompt_files": {
                "release-builder.md": """---
version: 1
archetype: builder
---

Focus on risky release work.
""",
            },
        },
    )

    assert response.status_code == 400
    assert f"conflicts with role_definition_id {role_definition['id']} on prompt_markdown" in response.json()["error"]


def test_api_orchestration_update_preserves_existing_prompt_files_when_omitted(service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    create_response = client.post(
        "/api/orchestrations",
        json={
            "name": "Custom Builder Flow",
            "description": "Uses a custom builder prompt.",
            "workflow": {
                "version": 1,
                "roles": [
                    {"id": "builder", "archetype": "builder", "prompt_ref": "custom-builder.md"},
                ],
                "steps": [
                    {"id": "builder_step", "role_id": "builder"},
                ],
            },
            "prompt_files": {
                "custom-builder.md": """---
version: 1
archetype: builder
---

Keep the builder prompt stable.
""",
            },
        },
    )
    assert create_response.status_code == 201
    orchestration_id = create_response.json()["orchestration"]["id"]

    update_response = client.put(
        f"/api/orchestrations/{orchestration_id}",
        json={
            "name": "Custom Builder Flow v2",
            "description": "Workflow changed, prompt payload omitted.",
            "workflow": {
                "version": 1,
                "roles": [
                    {"id": "builder", "archetype": "builder", "prompt_ref": "custom-builder.md"},
                ],
                "steps": [
                    {"id": "builder_retry_step", "role_id": "builder"},
                ],
            },
        },
    )

    assert update_response.status_code == 200
    orchestration = update_response.json()["orchestration"]
    assert orchestration["name"] == "Custom Builder Flow v2"
    assert orchestration["workflow_json"]["steps"][0]["id"] == "builder_retry_step"
    assert orchestration["prompt_files_json"]["custom-builder.md"].startswith("---\nversion: 1")


def test_api_orchestration_update_prunes_unused_prompt_files(service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    create_response = client.post(
        "/api/orchestrations",
        json={
            "name": "Custom Builder Flow",
            "description": "Uses a custom builder prompt.",
            "workflow": {
                "version": 1,
                "roles": [
                    {"id": "builder", "archetype": "builder", "prompt_ref": "custom-builder.md"},
                ],
                "steps": [
                    {"id": "builder_step", "role_id": "builder"},
                ],
            },
            "prompt_files": {
                "custom-builder.md": """---
version: 1
archetype: builder
---

Keep the builder prompt stable.
""",
            },
        },
    )
    assert create_response.status_code == 201
    orchestration_id = create_response.json()["orchestration"]["id"]

    update_response = client.put(
        f"/api/orchestrations/{orchestration_id}",
        json={
            "name": "Builtin Builder Flow",
            "description": "Now uses the built-in builder prompt.",
            "workflow": {
                "version": 1,
                "roles": [
                    {"id": "builder", "archetype": "builder", "prompt_ref": "builder.md"},
                ],
                "steps": [
                    {"id": "builder_step", "role_id": "builder"},
                ],
            },
        },
    )

    assert update_response.status_code == 200
    orchestration = update_response.json()["orchestration"]
    assert orchestration["workflow_json"]["roles"][0]["prompt_ref"] == "builder.md"
    assert list(orchestration["prompt_files_json"].keys()) == ["builder.md"]
    assert "custom-builder.md" not in orchestration["prompt_files_json"]


def test_api_orchestration_rejects_shared_prompt_ref_with_mismatched_archetype(service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    response = client.post(
        "/api/orchestrations",
        json={
            "name": "Shared Prompt Ref Mismatch",
            "description": "Should fail when one prompt ref is reused across incompatible archetypes.",
            "workflow": {
                "version": 1,
                "roles": [
                    {"id": "builder", "archetype": "builder", "prompt_ref": "shared.md"},
                    {"id": "inspector", "archetype": "inspector", "prompt_ref": "shared.md"},
                ],
                "steps": [
                    {"id": "builder_step", "role_id": "builder"},
                    {"id": "inspector_step", "role_id": "inspector"},
                ],
            },
            "prompt_files": {
                "shared.md": """---
version: 1
archetype: builder
---

Keep the builder prompt stable.
""",
            },
        },
    )

    assert response.status_code == 400
    assert "prompt archetype builder does not match expected archetype inspector" in response.json()["error"]


def test_api_orchestration_rejects_unsafe_prompt_ref_paths(service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    response = client.post(
        "/api/orchestrations",
        json={
            "name": "Unsafe Prompt Ref",
            "description": "Should fail when a prompt ref escapes the asset root.",
            "workflow": {
                "version": 1,
                "roles": [
                    {"id": "builder", "archetype": "builder", "prompt_ref": "../escape.md"},
                ],
                "steps": [
                    {"id": "builder_step", "role_id": "builder"},
                ],
            },
            "prompt_files": {
                "../escape.md": """---
version: 1
archetype: builder
---

This should never be written outside prompts/.
""",
            },
        },
    )

    assert response.status_code == 400
    assert "prompt_ref must be a safe relative path" in response.json()["error"]


def test_api_orchestration_rejects_invalid_prompt_file_keys(service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    response = client.post(
        "/api/orchestrations",
        json={
            "name": "Unsafe Prompt Files",
            "description": "Should reject invalid prompt_files keys instead of ignoring them.",
            "workflow": {
                "version": 1,
                "roles": [
                    {"id": "builder", "archetype": "builder", "prompt_ref": "builder.md"},
                ],
                "steps": [
                    {"id": "builder_step", "role_id": "builder"},
                ],
            },
            "prompt_files": {
                "../escape.md": """---
version: 1
archetype: builder
---

This key should be rejected instead of silently dropped.
""",
            },
        },
    )

    assert response.status_code == 400
    assert "prompt_ref must be a safe relative path" in response.json()["error"]


def test_api_get_orchestration_sanitizes_invalid_persisted_prompt_file_keys(service_factory) -> None:
    service = service_factory(scenario="success")
    service.repository.create_orchestration(
        {
            "id": "orch_legacy",
            "name": "Legacy Builder Flow",
            "description": "Contains stale invalid prompt file keys.",
            "workflow": {
                "version": 1,
                "roles": [
                    {"id": "builder", "archetype": "builder", "prompt_ref": "builder.md"},
                ],
                "steps": [
                    {"id": "builder_step", "role_id": "builder"},
                ],
            },
            "prompt_files": {
                "../escape.md": """---
version: 1
archetype: builder
---

Legacy invalid key.
""",
                "builder.md": """---
version: 1
archetype: builder
---

Legit builder prompt.
""",
            },
        }
    )
    client = TestClient(build_app(service=service))

    response = client.get("/api/orchestrations/orch_legacy")

    assert response.status_code == 200
    orchestration = response.json()
    assert list(orchestration["prompt_files_json"].keys()) == ["builder.md"]


def test_builtin_orchestration_form_route_is_read_only(service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    builtin = service.get_orchestration("builtin:build_first")
    custom_before = [item for item in service.list_orchestrations() if item["source"] == "custom"]

    response = client.post(
        "/orchestrations/builtin:build_first/edit",
        data={
            "name": "Attempted Custom Copy",
            "description": "Should not be created from the built-in edit route.",
            "workflow_preset": "build_first",
            "workflow_json": json.dumps(builtin["workflow_json"], ensure_ascii=False),
            "prompt_files_json": json.dumps(builtin["prompt_files_json"], ensure_ascii=False),
        },
    )

    assert response.status_code == 200
    assert "built-in orchestrations are read-only" in response.text
    custom_after = [item for item in service.list_orchestrations() if item["source"] == "custom"]
    assert custom_after == custom_before


def test_blank_orchestration_form_does_not_fall_back_to_build_first(service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    response = client.post(
        "/orchestrations/new",
        data={
            "name": "Blank Starter",
            "description": "Should stay blank until steps are added.",
            "workflow_json": json.dumps({"version": 1, "preset": "", "roles": [], "steps": []}, ensure_ascii=False),
            "prompt_files_json": json.dumps({}, ensure_ascii=False),
        },
    )

    assert response.status_code == 200
    assert "workflow requires at least one role" in response.text
    custom_records = [item for item in service.list_orchestrations() if item["source"] == "custom"]
    assert custom_records == []


def test_api_can_create_round_based_loop_without_gatekeeper(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    response = client.post(
        "/api/loops",
        json={
            "name": "Round Builder Loop",
            "spec_path": str(sample_spec_file),
            "workdir": str(sample_workdir),
            "executor_kind": "codex",
            "model": "gpt-5.4",
            "reasoning_effort": "medium",
            "completion_mode": "rounds",
            "iteration_interval_seconds": 0.1,
            "max_iters": 2,
            "max_role_retries": 1,
            "delta_threshold": 0.005,
            "trigger_window": 2,
            "regression_window": 2,
            "workflow": {
                "version": 1,
                "roles": [
                    {"id": "builder", "name": "Builder", "archetype": "builder", "prompt_ref": "builder.md"},
                ],
                "steps": [
                    {"id": "builder_step", "role_id": "builder"},
                ],
            },
            "start_immediately": False,
        },
    )

    assert response.status_code == 201
    loop = response.json()["loop"]
    assert loop["completion_mode"] == "rounds"
    assert loop["iteration_interval_seconds"] == 0.1
    assert loop["workflow_json"]["steps"][0]["role_id"] == "builder"


def test_api_rejects_gatekeeper_mode_without_finish_gatekeeper(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    response = client.post(
        "/api/loops",
        json={
            "name": "Invalid Gate Loop",
            "spec_path": str(sample_spec_file),
            "workdir": str(sample_workdir),
            "executor_kind": "codex",
            "model": "gpt-5.4",
            "reasoning_effort": "medium",
            "completion_mode": "gatekeeper",
            "max_iters": 2,
            "max_role_retries": 1,
            "delta_threshold": 0.005,
            "trigger_window": 2,
            "regression_window": 2,
            "workflow": {
                "version": 1,
                "roles": [
                    {"id": "builder", "name": "Builder", "archetype": "builder", "prompt_ref": "builder.md"},
                ],
                "steps": [
                    {"id": "builder_step", "role_id": "builder"},
                ],
            },
            "start_immediately": False,
        },
    )

    assert response.status_code == 400
    assert "gatekeeper completion mode" in response.json()["error"]


def test_api_rejects_duplicate_workflow_step_ids(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    response = client.post(
        "/api/loops",
        json={
            "name": "Duplicate Step Loop",
            "spec_path": str(sample_spec_file),
            "workdir": str(sample_workdir),
            "executor_kind": "codex",
            "model": "gpt-5.4",
            "reasoning_effort": "medium",
            "completion_mode": "rounds",
            "max_iters": 2,
            "max_role_retries": 1,
            "delta_threshold": 0.005,
            "trigger_window": 2,
            "regression_window": 2,
            "workflow": {
                "version": 1,
                "roles": [
                    {"id": "builder", "name": "Builder", "archetype": "builder", "prompt_ref": "builder.md"},
                    {"id": "inspector", "name": "Inspector", "archetype": "inspector", "prompt_ref": "inspector.md"},
                ],
                "steps": [
                    {"id": "shared_step", "role_id": "builder"},
                    {"id": "shared_step", "role_id": "inspector"},
                ],
            },
            "start_immediately": False,
        },
    )

    assert response.status_code == 400
    assert "duplicate workflow step id" in response.json()["error"]


def test_api_normalizes_boolean_like_workflow_step_session_flags(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    response = client.post(
        "/api/loops",
        json={
            "name": "Session Flag Loop",
            "spec_path": str(sample_spec_file),
            "workdir": str(sample_workdir),
            "executor_kind": "codex",
            "model": "gpt-5.4",
            "reasoning_effort": "medium",
            "completion_mode": "rounds",
            "max_iters": 2,
            "max_role_retries": 1,
            "delta_threshold": 0.005,
            "trigger_window": 2,
            "regression_window": 2,
            "workflow": {
                "version": 1,
                "roles": [
                    {"id": "builder", "name": "Builder", "archetype": "builder", "prompt_ref": "builder.md"},
                    {"id": "inspector", "name": "Inspector", "archetype": "inspector", "prompt_ref": "inspector.md"},
                ],
                "steps": [
                    {"id": "builder_step", "role_id": "builder", "inherit_session": "false"},
                    {"id": "inspector_step", "role_id": "inspector", "inherit_session": "true"},
                ],
            },
            "start_immediately": False,
        },
    )

    assert response.status_code == 201
    steps = response.json()["loop"]["workflow_json"]["steps"]
    assert steps[0]["inherit_session"] is False
    assert steps[1]["inherit_session"] is True


def test_api_rejects_invalid_workflow_step_session_flag(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    response = client.post(
        "/api/loops",
        json={
            "name": "Invalid Session Flag Loop",
            "spec_path": str(sample_spec_file),
            "workdir": str(sample_workdir),
            "executor_kind": "codex",
            "model": "gpt-5.4",
            "reasoning_effort": "medium",
            "completion_mode": "rounds",
            "max_iters": 2,
            "max_role_retries": 1,
            "delta_threshold": 0.005,
            "trigger_window": 2,
            "regression_window": 2,
            "workflow": {
                "version": 1,
                "roles": [
                    {"id": "builder", "name": "Builder", "archetype": "builder", "prompt_ref": "builder.md"},
                ],
                "steps": [
                    {"id": "builder_step", "role_id": "builder", "inherit_session": "sometimes"},
                ],
            },
            "start_immediately": False,
        },
    )

    assert response.status_code == 400
    assert "inherit_session must be a boolean" in response.json()["error"]


def test_api_rejects_finish_run_for_non_gatekeeper_steps(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    response = client.post(
        "/api/loops",
        json={
            "name": "Invalid On Pass Loop",
            "spec_path": str(sample_spec_file),
            "workdir": str(sample_workdir),
            "executor_kind": "codex",
            "model": "gpt-5.4",
            "reasoning_effort": "medium",
            "completion_mode": "rounds",
            "max_iters": 2,
            "max_role_retries": 1,
            "delta_threshold": 0.005,
            "trigger_window": 2,
            "regression_window": 2,
            "workflow": {
                "version": 1,
                "roles": [
                    {"id": "builder", "name": "Builder", "archetype": "builder", "prompt_ref": "builder.md"},
                ],
                "steps": [
                    {"id": "builder_step", "role_id": "builder", "on_pass": "finish_run"},
                ],
            },
            "start_immediately": False,
        },
    )

    assert response.status_code == 400
    assert "non-gatekeeper steps only support on_pass=continue" in response.json()["error"]


def test_api_role_definition_crud(service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    create_response = client.post(
        "/api/role-definitions",
        json={
            "name": "Release Builder",
            "description": "Ship focused release changes.",
            "posture_notes": "Prefer maintainability evidence before calling this ready.",
            "archetype": "builder",
            "prompt_markdown": """---
version: 1
archetype: builder
---

Focus on scoped release work.
""",
            "executor_kind": "claude",
            "executor_mode": "preset",
            "model": "",
            "reasoning_effort": "high",
        },
    )
    assert create_response.status_code == 201
    role_definition = create_response.json()["role_definition"]
    assert role_definition["name"] == "Release Builder"
    assert role_definition["archetype"] == "builder"
    assert role_definition["executor_kind"] == "claude"
    assert role_definition["reasoning_effort"] == "high"
    assert role_definition["posture_notes"] == "Prefer maintainability evidence before calling this ready."
    assert role_definition["prompt_ref"].endswith(".md")
    generated_prompt_ref = role_definition["prompt_ref"]

    list_response = client.get("/api/role-definitions")
    assert list_response.status_code == 200
    assert any(item["id"] == role_definition["id"] for item in list_response.json())

    update_response = client.put(
        f"/api/role-definitions/{role_definition['id']}",
        json={
            "name": "Release Builder v2",
            "description": "Updated role definition.",
            "posture_notes": "Tighten the evidence bar for refactors.",
            "archetype": "builder",
            "prompt_markdown": """---
version: 1
archetype: builder
---

Focus on scoped release work with tighter release constraints.
""",
            "executor_kind": "codex",
            "executor_mode": "command",
            "command_cli": "codex",
                "command_args_text": "\n".join(
                    [
                        "exec",
                        "--json",
                        "--cd",
                        "{workdir}",
                        "--output-schema",
                        "{schema_path}",
                        "--output-last-message",
                        "{output_path}",
                        "{prompt}",
                    ]
                ),
            "model": "gpt-5.4",
            "reasoning_effort": "",
        },
    )
    assert update_response.status_code == 200
    updated_role_definition = update_response.json()["role_definition"]
    assert updated_role_definition["name"] == "Release Builder v2"
    assert updated_role_definition["executor_mode"] == "command"
    assert updated_role_definition["model"] == "gpt-5.4"
    assert updated_role_definition["posture_notes"] == "Tighten the evidence bar for refactors."
    assert updated_role_definition["prompt_ref"] == generated_prompt_ref

    invalid_update_response = client.put(
        f"/api/role-definitions/{role_definition['id']}",
        json={
            "name": "Release Inspector",
            "description": "Should fail.",
            "archetype": "inspector",
            "prompt_markdown": """---
version: 1
archetype: inspector
---

Inspect release work instead.
""",
            "executor_kind": "codex",
            "executor_mode": "preset",
            "model": "",
            "reasoning_effort": "medium",
        },
    )
    assert invalid_update_response.status_code == 400
    assert "saved role definitions cannot change archetype" in invalid_update_response.json()["error"]

    delete_response = client.delete(f"/api/role-definitions/{role_definition['id']}")
    assert delete_response.status_code == 200
    assert delete_response.json()["deleted"] is True


def test_api_bundles_import_export_and_delete(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = service.create_loop(
        name="Bundle Export Source",
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
    bundle_yaml = bundle_to_yaml(
        service.derive_bundle_from_loop(
            loop["id"],
            name="Imported Bundle",
            description="Bundle import from API.",
            collaboration_summary="Prefer evidence before declaring done.",
        )
    )

    client = TestClient(build_app(service=service))
    preview_response = client.post("/api/bundles/preview", json={"bundle_yaml": bundle_yaml})
    assert preview_response.status_code == 200
    preview = preview_response.json()
    assert preview["ok"] is True
    assert preview["metadata"]["name"] == "Imported Bundle"
    assert preview["bundle"]["loop"]["workdir"] == str(sample_workdir.resolve())
    assert preview["roles"]
    assert preview["workflow_preview"]["steps"]
    assert preview["spec_rendered_html"].strip()

    import_response = client.post("/api/bundles/import", json={"bundle_yaml": bundle_yaml})

    assert import_response.status_code == 201
    bundle = import_response.json()["bundle"]
    assert bundle["name"] == "Imported Bundle"
    assert bundle["collaboration_summary"] == "Prefer evidence before declaring done."

    list_response = client.get("/api/bundles")
    assert list_response.status_code == 200
    assert any(item["id"] == bundle["id"] for item in list_response.json())

    get_response = client.get(f"/api/bundles/{bundle['id']}")
    assert get_response.status_code == 200
    assert get_response.json()["id"] == bundle["id"]

    export_response = client.get(f"/api/bundles/{bundle['id']}/export")
    assert export_response.status_code == 200
    assert "Imported Bundle" in export_response.text
    assert "Prefer evidence before declaring done." in export_response.text
    assert export_response.headers["content-type"].startswith("application/yaml")

    delete_response = client.delete(f"/api/bundles/{bundle['id']}")
    assert delete_response.status_code == 200
    assert delete_response.json()["deleted"] is True

    missing_response = client.get(f"/api/bundles/{bundle['id']}")
    assert missing_response.status_code == 400
    assert "unknown bundle" in missing_response.json()["error"]


def test_api_bundles_derive_returns_bundle_payload(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = service.create_loop(
        name="Bundle Derive Source",
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
    client = TestClient(build_app(service=service))

    response = client.post(
        "/api/bundles/derive",
        json={
            "loop_id": loop["id"],
            "name": "Derived Bundle",
            "description": "Derived from existing assets.",
            "collaboration_summary": "Treat fake done states as blockers.",
        },
    )

    assert response.status_code == 200
    bundle = response.json()["bundle"]
    assert bundle["metadata"]["name"] == "Derived Bundle"
    assert bundle["collaboration_summary"] == "Treat fake done states as blockers."
    assert bundle["workflow"]["roles"]
    assert bundle["role_definitions"]


def test_api_task_alignment_skill_install_targets_and_install(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / ".codex"))

    client = TestClient(build_app())

    targets_response = client.get("/api/skills/loopora-task-alignment")
    assert targets_response.status_code == 200
    targets = {item["target"]: item for item in targets_response.json()["targets"]}
    assert targets["codex"]["installed"] is False
    assert targets["codex"]["install_state"] == "missing"
    assert targets["claude"]["installed"] is False
    assert targets["opencode"]["installed"] is False
    assert targets["codex"]["install_paths"] == [
        str(tmp_path / ".codex" / "skills" / "loopora-task-alignment" / "SKILL.md")
    ]

    install_response = client.post("/api/skills/loopora-task-alignment/install", json={"target": "codex"})
    assert install_response.status_code == 201
    install_payload = install_response.json()
    assert install_payload["result"]["action"] == "installed"
    codex_targets = {item["target"]: item for item in install_payload["targets"]}
    assert codex_targets["codex"]["installed"] is True
    assert codex_targets["codex"]["install_state"] == "installed"

    skill_dir = tmp_path / ".codex" / "skills" / "loopora-task-alignment"
    skill_path = skill_dir / "SKILL.md"
    contract_path = skill_dir / "references" / "bundle-contract.md"
    agent_path = skill_dir / "agents" / "openai.yaml"
    original_skill_text = skill_path.read_text(encoding="utf-8")

    assert skill_path.exists()
    assert contract_path.exists()
    assert agent_path.exists()

    skill_path.write_text("tampered", encoding="utf-8")
    stale_file = skill_dir / "stale-note.txt"
    stale_file.write_text("old", encoding="utf-8")

    stale_targets_response = client.get("/api/skills/loopora-task-alignment")
    assert stale_targets_response.status_code == 200
    stale_targets = {item["target"]: item for item in stale_targets_response.json()["targets"]}
    assert stale_targets["codex"]["installed"] is False
    assert stale_targets["codex"]["install_state"] == "stale"

    reinstall_response = client.post("/api/skills/loopora-task-alignment/install", json={"target": "codex"})
    assert reinstall_response.status_code == 201
    reinstall_payload = reinstall_response.json()
    assert reinstall_payload["result"]["action"] == "reinstalled"
    refreshed_targets = {item["target"]: item for item in reinstall_payload["targets"]}
    assert refreshed_targets["codex"]["installed"] is True
    assert refreshed_targets["codex"]["install_state"] == "installed"
    assert skill_path.read_text(encoding="utf-8") == original_skill_text
    assert not stale_file.exists()


def test_api_task_alignment_skill_bundle_download_returns_zip(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / ".codex"))

    client = TestClient(build_app())
    response = client.get("/api/skills/loopora-task-alignment/download")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["content-disposition"] == 'attachment; filename="loopora-task-alignment.zip"'

    archive = zipfile.ZipFile(io.BytesIO(response.content))
    names = set(archive.namelist())
    assert "loopora-task-alignment/SKILL.md" in names
    assert "loopora-task-alignment/references/product-primer.md" in names
    assert "loopora-task-alignment/references/alignment-playbook.md" in names
    assert "loopora-task-alignment/references/quality-rubric.md" in names
    assert "loopora-task-alignment/references/bundle-contract.md" in names
    assert "loopora-task-alignment/references/examples.md" in names
    assert "loopora-task-alignment/agents/openai.yaml" in names


def test_bundle_form_import_and_edit_flow(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = service.create_loop(
        name="Bundle Form Source",
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
    bundle_yaml = bundle_to_yaml(
        service.derive_bundle_from_loop(
            loop["id"],
            name="Form Bundle",
            description="Imported through the HTML form.",
            collaboration_summary="Prefer compact but convincing evidence.",
        )
    )

    client = TestClient(build_app(service=service))
    import_response = client.post("/bundles/import", data={"bundle_yaml": bundle_yaml}, follow_redirects=False)

    assert import_response.status_code == 303
    bundle_location = import_response.headers["location"]
    bundle_id = bundle_location.rsplit("/", 1)[-1]
    bundle = service.get_bundle(bundle_id)
    assert bundle["name"] == "Form Bundle"

    edit_response = client.post(
        f"/bundles/{bundle_id}/edit",
        data={
            "description": "Updated bundle description.",
            "collaboration_summary": "Take fake done seriously.",
            "spec_markdown": "# Task\n\nShip the update.\n\n# Done When\n- It works.\n",
        },
        follow_redirects=False,
    )

    assert edit_response.status_code == 303
    updated_bundle = service.get_bundle(bundle_id)
    assert updated_bundle["description"] == "Updated bundle description."
    assert updated_bundle["collaboration_summary"] == "Take fake done seriously."
    spec_path = app_home() / "bundles" / bundle_id / "spec.md"
    assert spec_path.read_text(encoding="utf-8").startswith("# Task")


def test_bundle_derive_form_encodes_query_values(service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    response = client.post(
        "/bundles/derive",
        data={
            "loop_id": "loop&id=shadow",
            "name": "Bundle & Review",
            "description": "Use A&B evidence.",
            "collaboration_summary": "No query leakage.",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == (
        "/bundles/derive/export?"
        "loop_id=loop%26id%3Dshadow&"
        "name=Bundle+%26+Review&"
        "description=Use+A%26B+evidence.&"
        "collaboration_summary=No+query+leakage."
    )


def test_create_loop_page_imports_bundle_as_loop_creation_flow(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    source_loop = service.create_loop(
        name="Create Page Bundle Source",
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
    bundle_yaml = bundle_to_yaml(
        service.derive_bundle_from_loop(
            source_loop["id"],
            name="Create Page Bundle",
            description="Imported from the unified create loop page.",
            collaboration_summary="Create loop and bundle import share one entry.",
        )
    )

    client = TestClient(build_app(service=service))
    import_response = client.post(
        "/loops/new/import-bundle",
        data={"bundle_yaml": bundle_yaml, "start_immediately": ""},
        follow_redirects=False,
    )

    assert import_response.status_code == 303
    assert import_response.headers["location"].startswith("/loops/")
    imported_bundle = next(bundle for bundle in service.list_bundles() if bundle["name"] == "Create Page Bundle")
    assert import_response.headers["location"] == f"/loops/{imported_bundle['loop_id']}"
    assert service.get_loop(imported_bundle["loop_id"])["name"] == "Create Page Bundle Source"


def test_api_bundle_update_bumps_revision(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = service.create_loop(
        name="Bundle Update Source",
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
    imported = service.import_bundle_text(
        bundle_to_yaml(
            service.derive_bundle_from_loop(
                loop["id"],
                name="API Update Bundle",
                description="Before API update.",
                collaboration_summary="Original collaboration summary.",
            )
        )
    )

    client = TestClient(build_app(service=service))
    response = client.put(
        f"/api/bundles/{imported['id']}",
        json={
            "description": "After API update.",
            "collaboration_summary": "Updated collaboration summary.",
            "spec_markdown": "# Task\n\nUpdated.\n\n# Done When\n- Ready.\n",
        },
    )

    assert response.status_code == 200
    bundle = response.json()["bundle"]
    assert bundle["description"] == "After API update."
    assert bundle["collaboration_summary"] == "Updated collaboration summary."
    assert bundle["revision"] == imported["revision"] + 1


def test_bundle_owned_surface_edit_redirects_back_to_bundle_detail(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = service.create_loop(
        name="Bundle Redirect Source",
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
    imported = service.import_bundle_text(
        bundle_to_yaml(
            service.derive_bundle_from_loop(
                loop["id"],
                name="Redirect Bundle",
                description="Bundle redirect test.",
                collaboration_summary="Return to the bundle detail after local surface edits.",
            )
        )
    )
    orchestration = imported["orchestration"]
    role_definition = imported["role_definitions"][0]
    client = TestClient(build_app(service=service))

    orchestration_response = client.post(
        f"/orchestrations/{orchestration['id']}/edit?return_to=/bundles/{imported['id']}",
        data={
            "name": orchestration["name"],
            "description": "Workflow tuned from bundle detail.",
            "workflow_json": json.dumps(orchestration["workflow_json"], ensure_ascii=False, indent=2),
            "prompt_files_json": json.dumps(orchestration["prompt_files_json"], ensure_ascii=False, indent=2),
        },
        follow_redirects=False,
    )
    assert orchestration_response.status_code == 303
    assert orchestration_response.headers["location"] == f"/bundles/{imported['id']}?surface_updated=workflow"

    role_response = client.post(
        f"/roles/{role_definition['id']}/edit?return_to=/bundles/{imported['id']}",
        data={
            "name": role_definition["name"],
            "description": role_definition["description"],
            "archetype": role_definition["archetype"],
            "prompt_ref": role_definition["prompt_ref"],
            "prompt_markdown": role_definition["prompt_markdown"],
            "posture_notes": "Tighten this role from the bundle detail flow.",
            "executor_kind": role_definition["executor_kind"],
            "executor_mode": role_definition["executor_mode"],
            "command_cli": role_definition["command_cli"],
            "command_args_text": role_definition["command_args_text"],
            "model": role_definition["model"],
            "reasoning_effort": role_definition["reasoning_effort"],
        },
        follow_redirects=False,
    )
    assert role_response.status_code == 303
    assert role_response.headers["location"] == f"/bundles/{imported['id']}?surface_updated=role%3A{role_definition['id']}"


def test_bundle_surface_return_to_rejects_external_redirects(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = service.create_loop(
        name="Unsafe Return Source",
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
    imported = service.import_bundle_text(
        bundle_to_yaml(
            service.derive_bundle_from_loop(
                loop["id"],
                name="Unsafe Return Bundle",
                description="Return target safety.",
                collaboration_summary="Do not redirect outside the local console.",
            )
        )
    )
    orchestration = imported["orchestration"]
    role_definition = imported["role_definitions"][0]
    client = TestClient(build_app(service=service))

    orchestration_page = client.get(f"/orchestrations/{orchestration['id']}/edit?return_to=https://evil.example/phish")
    assert orchestration_page.status_code == 200
    assert "https://evil.example" not in orchestration_page.text

    orchestration_response = client.post(
        f"/orchestrations/{orchestration['id']}/edit?return_to=https://evil.example/phish",
        data={
            "name": orchestration["name"],
            "description": "Workflow tuned from an unsafe return target.",
            "workflow_json": json.dumps(orchestration["workflow_json"], ensure_ascii=False, indent=2),
            "prompt_files_json": json.dumps(orchestration["prompt_files_json"], ensure_ascii=False, indent=2),
        },
        follow_redirects=False,
    )
    assert orchestration_response.status_code == 303
    assert orchestration_response.headers["location"] == f"/orchestrations/{orchestration['id']}/edit?saved=1"

    role_page = client.get(f"/roles/{role_definition['id']}/edit?return_to=//evil.example/phish")
    assert role_page.status_code == 200
    assert "evil.example" not in role_page.text

    role_response = client.post(
        f"/roles/{role_definition['id']}/edit?return_to=//evil.example/phish",
        data={
            "name": role_definition["name"],
            "description": role_definition["description"],
            "archetype": role_definition["archetype"],
            "prompt_ref": role_definition["prompt_ref"],
            "prompt_markdown": role_definition["prompt_markdown"],
            "posture_notes": "Ignore the external return target.",
            "executor_kind": role_definition["executor_kind"],
            "executor_mode": role_definition["executor_mode"],
            "command_cli": role_definition["command_cli"],
            "command_args_text": role_definition["command_args_text"],
            "model": role_definition["model"],
            "reasoning_effort": role_definition["reasoning_effort"],
        },
        follow_redirects=False,
    )
    assert role_response.status_code == 303
    assert role_response.headers["location"] == f"/roles/{role_definition['id']}/edit?saved=1"


def test_bundle_export_sanitizes_download_filename(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = service.create_loop(
        name="Filename Source",
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
    imported = service.import_bundle_text(
        bundle_to_yaml(
            service.derive_bundle_from_loop(
                loop["id"],
                name='Bad/Name" \r\n injected',
                description="Filename safety.",
                collaboration_summary="Export headers stay parseable.",
            )
        )
    )
    client = TestClient(build_app(service=service))

    response = client.get(f"/api/bundles/{imported['id']}/export")

    assert response.status_code == 200
    disposition = response.headers["content-disposition"]
    assert disposition == 'attachment; filename="Bad-Name-injected.yml"'
    assert "\n" not in disposition
    assert "\r" not in disposition
    assert "/" not in disposition


def test_api_role_definition_rejects_custom_executor_preset_mode(service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    response = client.post(
        "/api/role-definitions",
        json={
            "name": "Custom Wrapper",
            "description": "Wrapper role.",
            "archetype": "custom",
            "prompt_markdown": """---
version: 1
archetype: custom
---

Observe and summarize.
""",
            "executor_kind": "custom",
            "executor_mode": "preset",
            "command_cli": "wrapper",
            "command_args_text": "--output\n{output_path}\n{prompt}\n",
            "model": "",
            "reasoning_effort": "",
        },
    )

    assert response.status_code == 400
    assert "only supports command mode" in response.json()["error"]


def test_api_role_definition_rejects_unsafe_prompt_ref(service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    response = client.post(
        "/api/role-definitions",
        json={
            "name": "Escaping Builder",
            "description": "Should fail when prompt_ref escapes the asset root.",
            "archetype": "builder",
            "prompt_ref": "../escape.md",
            "prompt_markdown": """---
version: 1
archetype: builder
---

Keep prompt refs inside prompts/.
""",
            "executor_kind": "codex",
            "executor_mode": "preset",
            "model": "gpt-5.4-mini",
            "reasoning_effort": "medium",
        },
    )

    assert response.status_code == 400
    assert "prompt_ref must be a safe relative path" in response.json()["error"]


def test_api_spec_init_validate_and_delete_loop(service_factory, tmp_path: Path, sample_workdir: Path) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    spec_path = tmp_path / "created-spec.md"
    init_response = client.post(
        "/api/specs/init",
        json={"path": str(spec_path), "locale": "en", "workflow_preset": "build_first"},
    )
    assert init_response.status_code == 201
    assert spec_path.exists()
    created_text = spec_path.read_text(encoding="utf-8")
    assert "delete `# Done When`" in created_text
    assert "preserve existing user files" in created_text
    assert "# Task" in created_text
    assert "# Done When" in created_text
    assert "# Guardrails" in created_text
    assert "# Role Notes" in created_text
    assert "## Builder Notes" in created_text
    assert "## Inspector Notes" in created_text
    assert "## GateKeeper Notes" in created_text
    assert "## Guide Notes" in created_text

    validate_response = client.get("/api/specs/validate", params={"path": str(spec_path)})
    assert validate_response.status_code == 200
    assert validate_response.json()["ok"] is True
    assert validate_response.json()["check_mode"] == "specified"

    loop = service.create_loop(
        name="Delete Me",
        spec_path=spec_path,
        workdir=sample_workdir,
        model="gpt-5.4",
        reasoning_effort="xhigh",
        max_iters=3,
        max_role_retries=1,
        delta_threshold=0.005,
        trigger_window=2,
        regression_window=2,
        role_models={},
    )

    delete_response = client.delete(f"/api/loops/{loop['id']}")
    assert delete_response.status_code == 200
    assert delete_response.json()["id"] == loop["id"]
    assert service.list_loops() == []


def test_api_spec_template_accepts_workflow_json_mapping(service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    response = client.post(
        "/api/specs/template",
        json={
            "locale": "en",
            "workflow_json": {
                "version": 1,
                "roles": [
                    {"id": "builder", "name": "Builder", "archetype": "builder", "prompt_ref": "builder.md"},
                    {"id": "gatekeeper", "name": "GateKeeper", "archetype": "gatekeeper", "prompt_ref": "gatekeeper.md"},
                ],
                "steps": [
                    {"id": "build", "role_id": "builder"},
                    {"id": "gate", "role_id": "gatekeeper", "on_pass": "finish_run"},
                ],
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert "# Task" in payload["content"]
    assert "## Builder Notes" in payload["content"]
    assert "## GateKeeper Notes" in payload["content"]
    assert [item["role_name"] for item in payload["role_note_sections"]] == ["Builder", "GateKeeper"]
    assert "<h1>Task</h1>" in payload["rendered_html"]


def test_api_spec_validate_reports_auto_generated_check_mode(tmp_path: Path, service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    spec_path = tmp_path / "exploratory-spec.md"
    spec_path.write_text(
        "# Task\n\nExplore a promising prototype direction.\n\n# Guardrails\n\n- Stay focused.\n",
        encoding="utf-8",
    )

    validate_response = client.get("/api/specs/validate", params={"path": str(spec_path)})
    assert validate_response.status_code == 200
    payload = validate_response.json()
    assert payload["ok"] is True
    assert payload["check_mode"] == "auto_generated"
    assert payload["check_count"] == 0


def test_api_spec_validate_rejects_legacy_headings(tmp_path: Path, service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    spec_path = tmp_path / "legacy-spec.md"
    spec_path.write_text("# Goal\n\nLegacy format.\n", encoding="utf-8")

    response = client.get("/api/specs/validate", params={"path": str(spec_path)})

    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert "legacy spec headings" in response.json()["error"]


def test_api_spec_preview_returns_rendered_read_only_markdown(tmp_path: Path, service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    spec_path = tmp_path / "preview-spec.md"
    spec_path.write_text(
        "# Task\n\nShip a preview.\n\n# Done When\n\n- Render headings\n- Escape <script>alert('xss')</script>\n\n```js\nconsole.log('ok')\n```\n",
        encoding="utf-8",
    )

    preview_response = client.get("/api/specs/preview", params={"path": str(spec_path)})

    assert preview_response.status_code == 200
    payload = preview_response.json()
    assert payload["ok"] is True
    assert payload["path"] == str(spec_path.resolve())
    assert "# Task" in payload["content"]
    assert "<h1>Task</h1>" in payload["rendered_html"]
    assert "<script>" not in payload["rendered_html"]
    assert "&lt;script&gt;alert" in payload["rendered_html"]
    assert 'class="language-js"' in payload["rendered_html"]
    assert "console.log" in payload["rendered_html"]


def test_api_spec_document_returns_content_rendering_and_validation(tmp_path: Path, service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    spec_path = tmp_path / "editable-spec.md"
    spec_path.write_text(
        "# Task\n\nKeep editing local.\n\n# Done When\n\n- The disk file updates after save.\n- The rendered preview updates too.\n",
        encoding="utf-8",
    )

    response = client.get("/api/specs/document", params={"path": str(spec_path)})

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["path"] == str(spec_path.resolve())
    assert payload["content"].startswith("# Task")
    assert "<h1>Task</h1>" in payload["rendered_html"]
    assert payload["validation"]["ok"] is True
    assert payload["validation"]["check_count"] == 2
    assert payload["validation"]["check_mode"] == "specified"


def test_api_spec_document_save_writes_file_and_returns_validation(tmp_path: Path, service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    spec_path = tmp_path / "editable-spec.md"
    spec_path.write_text("# Task\n\nInitial\n", encoding="utf-8")

    response = client.put(
        "/api/specs/document",
        json={
            "path": str(spec_path),
            "content": "# Task\r\n\r\nSaved copy.\r\n\r\n# Done When\r\n\r\n- The file matches the editor after save.\r\n",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["content"] == "# Task\n\nSaved copy.\n\n# Done When\n\n- The file matches the editor after save.\n"
    assert spec_path.read_text(encoding="utf-8") == payload["content"]
    assert payload["validation"]["ok"] is True
    assert payload["validation"]["check_count"] == 1
    assert "<h1>Done When</h1>" in payload["rendered_html"]


def test_api_markdown_render_can_strip_prompt_front_matter(service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    response = client.post(
        "/api/markdown/render",
        json={
            "markdown": "---\nversion: 1\narchetype: builder\n---\n\n# Prompt Body\n\nShip the change.\n",
            "strip_front_matter": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert "<h1>Prompt Body</h1>" in payload["rendered_html"]
    assert "version: 1" not in payload["rendered_html"]
    assert "archetype: builder" not in payload["rendered_html"]
    assert "Ship the change." in payload["rendered_html"]


def test_logo_assets_are_served(service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    response = client.get("/logo/logo.svg")
    assert response.status_code == 200
    assert "image/svg+xml" in response.headers["content-type"]


def test_network_mode_requires_auth_token_and_sets_cookie(service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service, bind_host="0.0.0.0", auth_token="secret-token"))

    unauthorized = client.get("/")
    assert unauthorized.status_code == 401
    assert "Auth token required" in unauthorized.text

    unsupported_header = client.get("/", headers={"X-Other-Token": "secret-token"})
    assert unsupported_header.status_code == 401

    authorized = client.get("/?token=secret-token")
    assert authorized.status_code == 200
    assert client.cookies.get("loopora_auth") == "secret-token"

    api_response = client.get("/api/loops")
    assert api_response.status_code == 200


def test_network_mode_auth_page_uses_request_locale_and_shared_styles(service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service, bind_host="0.0.0.0", auth_token="secret-token"))

    unauthorized = client.get("/", headers={"Accept-Language": "zh-CN;q=0.1,en-US;q=0.9"})

    assert unauthorized.status_code == 401
    assert re.search(r'<html\s+lang="en"\s+data-locale="en"\s+data-theme="light"\s*>', unauthorized.text)
    assert "loopora:theme" in unauthorized.text
    assert "loopora:locale" in unauthorized.text
    assert "/static/app.css?v=" in unauthorized.text
    assert "<style>" not in unauthorized.text
    assert 'data-testid="auth-card"' in unauthorized.text
    assert 'data-testid="auth-copy-stack"' in unauthorized.text
    assert "Loopora · Auth token required" in unauthorized.text
    assert "Auth token required" in unauthorized.text
    assert "需要访问令牌" in unauthorized.text
    assert "X-Loopora-Token" in unauthorized.text
    assert "X-Other-Token" not in unauthorized.text
    assert 'class="auth-logo" src="/logo/logo-with-text-horizontal.svg" alt="" aria-hidden="true"' in unauthorized.text

    css = client.get("/static/app.css?token=secret-token")
    assert css.status_code == 200
    assert ".auth-shell {" in css.text
    assert ".auth-card {" in css.text
    assert ".auth-copy-stack {" in css.text
    assert "[data-theme=\"dark\"] .auth-card {" in css.text
    assert "html[data-theme=\"dark\"] .auth-logo {" in css.text


def test_preferred_locale_from_accept_language_respects_q_values_and_supported_locales() -> None:
    assert web_module._preferred_locale_from_accept_language("zh-CN;q=0.1,en-US;q=0.9") == "en"
    assert web_module._preferred_locale_from_accept_language("en-US;q=0.1,zh-CN;q=0.9") == "zh"
    assert web_module._preferred_locale_from_accept_language("fr-FR,zh-CN;q=0.8,en-US;q=0.6") == "zh"
    assert web_module._preferred_locale_from_accept_language("fr-FR,de-DE;q=0.8") == "en"
    assert web_module._preferred_locale_from_accept_language("en-US;q=0,zh-CN;q=0.6") == "zh"


def test_network_mode_disables_native_dialog_endpoints(service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service, bind_host="0.0.0.0", auth_token="secret-token"))

    response = client.get("/api/system/pick-directory?token=secret-token")
    assert response.status_code == 400
    assert "native dialogs are disabled in network mode" in response.json()["error"]

    reveal = client.post("/api/system/reveal-path?token=secret-token", json={"path": "/tmp"})
    assert reveal.status_code == 400
    assert "native dialogs are disabled in network mode" in reveal.json()["error"]
