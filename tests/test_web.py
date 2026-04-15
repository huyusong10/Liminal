from __future__ import annotations

import io
import time
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from liminal.web import build_app


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

    liminal_dir = client.get(f"/api/files?run_id={run_id}&root=liminal")
    assert liminal_dir.status_code == 200
    assert liminal_dir.json()["kind"] == "directory"

    artifacts = client.get(f"/api/runs/{run_id}/artifacts")
    assert artifacts.status_code == 200
    artifact_payload = artifacts.json()
    assert any(item["id"] == "original-spec" and item["available"] for item in artifact_payload)
    assert any(item["id"] == "summary" and item["available"] for item in artifact_payload)

    original_spec_artifact = client.get(f"/api/runs/{run_id}/artifacts/original-spec")
    assert original_spec_artifact.status_code == 200
    assert original_spec_artifact.json()["kind"] == "file"
    assert original_spec_artifact.json()["content"] == sample_spec_text

    summary_artifact = client.get(f"/api/runs/{run_id}/artifacts/summary")
    assert summary_artifact.status_code == 200
    assert summary_artifact.json()["kind"] == "file"
    assert "Liminal Run Summary" in summary_artifact.json()["content"]

    challenger_artifact = client.get(f"/api/runs/{run_id}/artifacts/challenger-seed")
    assert challenger_artifact.status_code == 200
    assert challenger_artifact.json()["kind"] == "missing"

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
    assert f"id: {event_payload[-1]['id']}\n" in reconnect_body


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
        "generator": "gpt-5.4-mini",
        "verifier": "gpt-5.4",
    }


def test_api_spec_init_validate_and_delete_loop(service_factory, tmp_path: Path, sample_workdir: Path) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    spec_path = tmp_path / "created-spec.md"
    init_response = client.post("/api/specs/init", json={"path": str(spec_path), "locale": "en"})
    assert init_response.status_code == 201
    assert spec_path.exists()
    created_text = spec_path.read_text(encoding="utf-8")
    assert "Delete the whole `# Checks` section" in created_text
    assert "preserve existing user files" in created_text
    assert "# Goal" in created_text
    assert "# Checks" in created_text
    assert "# Constraints" in created_text

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


def test_api_spec_validate_reports_auto_generated_check_mode(tmp_path: Path, service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    spec_path = tmp_path / "exploratory-spec.md"
    spec_path.write_text(
        "# Goal\n\nExplore a promising prototype direction.\n\n# Constraints\n\n- Stay focused.\n",
        encoding="utf-8",
    )

    validate_response = client.get("/api/specs/validate", params={"path": str(spec_path)})
    assert validate_response.status_code == 200
    payload = validate_response.json()
    assert payload["ok"] is True
    assert payload["check_mode"] == "auto_generated"
    assert payload["check_count"] == 0


def test_api_spec_skill_install_targets_and_install(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / ".codex"))

    client = TestClient(build_app())

    targets_response = client.get("/api/skills/liminal-spec")
    assert targets_response.status_code == 200
    targets = {item["target"]: item for item in targets_response.json()["targets"]}
    assert targets["codex"]["installed"] is False
    assert targets["codex"]["install_state"] == "missing"
    assert targets["claude"]["installed"] is False
    assert targets["opencode"]["installed"] is False
    assert targets["codex"]["install_paths"] == [str(tmp_path / ".codex" / "skills" / "liminal-spec" / "SKILL.md")]

    install_response = client.post("/api/skills/liminal-spec/install", json={"target": "codex"})
    assert install_response.status_code == 201
    install_payload = install_response.json()
    assert install_payload["result"]["action"] == "installed"
    codex_targets = {item["target"]: item for item in install_payload["targets"]}
    assert codex_targets["codex"]["installed"] is True
    assert codex_targets["codex"]["install_state"] == "installed"

    skill_dir = tmp_path / ".codex" / "skills" / "liminal-spec"
    skill_path = skill_dir / "SKILL.md"
    reference_path = skill_dir / "references" / "liminal-spec-format.md"
    original_skill_text = skill_path.read_text(encoding="utf-8")

    assert skill_path.exists()
    assert reference_path.exists()
    assert not (tmp_path / ".agents" / "skills" / "liminal-spec" / "SKILL.md").exists()

    skill_path.write_text("tampered", encoding="utf-8")
    stale_file = skill_dir / "stale-note.txt"
    stale_file.write_text("old", encoding="utf-8")

    stale_targets_response = client.get("/api/skills/liminal-spec")
    assert stale_targets_response.status_code == 200
    stale_targets = {item["target"]: item for item in stale_targets_response.json()["targets"]}
    assert stale_targets["codex"]["installed"] is False
    assert stale_targets["codex"]["install_state"] == "stale"

    reinstall_response = client.post("/api/skills/liminal-spec/install", json={"target": "codex"})
    assert reinstall_response.status_code == 201
    reinstall_payload = reinstall_response.json()
    assert reinstall_payload["result"]["action"] == "reinstalled"
    refreshed_targets = {item["target"]: item for item in reinstall_payload["targets"]}
    assert refreshed_targets["codex"]["installed"] is True
    assert refreshed_targets["codex"]["install_state"] == "installed"
    assert skill_path.read_text(encoding="utf-8") == original_skill_text
    assert not stale_file.exists()


def test_api_spec_skill_bundle_download_returns_zip(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / ".codex"))

    client = TestClient(build_app())
    response = client.get("/api/skills/liminal-spec/download")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["content-disposition"] == 'attachment; filename="liminal-spec.zip"'

    archive = zipfile.ZipFile(io.BytesIO(response.content))
    names = set(archive.namelist())
    assert "liminal-spec/SKILL.md" in names
    assert "liminal-spec/references/liminal-spec-format.md" in names


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

    authorized = client.get("/?token=secret-token")
    assert authorized.status_code == 200
    assert client.cookies.get("liminal_auth") == "secret-token"

    api_response = client.get("/api/loops")
    assert api_response.status_code == 200


def test_network_mode_disables_native_dialog_endpoints(service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service, bind_host="0.0.0.0", auth_token="secret-token"))

    response = client.get("/api/system/pick-directory?token=secret-token")
    assert response.status_code == 400
    assert "native dialogs are disabled in network mode" in response.json()["error"]
