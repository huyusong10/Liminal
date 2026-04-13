from __future__ import annotations

import time
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
    assert claude_loop["model"] == "sonnet"
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


def test_api_spec_init_validate_and_delete_loop(service_factory, tmp_path: Path, sample_workdir: Path) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    spec_path = tmp_path / "created-spec.md"
    init_response = client.post("/api/specs/init", json={"path": str(spec_path), "locale": "en"})
    assert init_response.status_code == 201
    assert spec_path.exists()

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
    assert payload["check_mode"] == "auto_generate"
    assert payload["check_count"] == 0


def test_api_spec_skill_install_targets_and_install(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / ".codex"))

    client = TestClient(build_app())

    targets_response = client.get("/api/skills/liminal-spec")
    assert targets_response.status_code == 200
    targets = {item["target"]: item for item in targets_response.json()["targets"]}
    assert targets["codex"]["installed"] is False
    assert targets["claude"]["installed"] is False
    assert targets["opencode"]["installed"] is False
    assert targets["codex"]["install_paths"] == [str(tmp_path / ".codex" / "skills" / "liminal-spec" / "SKILL.md")]

    install_response = client.post("/api/skills/liminal-spec/install", json={"target": "codex"})
    assert install_response.status_code == 201
    install_payload = install_response.json()
    codex_targets = {item["target"]: item for item in install_payload["targets"]}
    assert codex_targets["codex"]["installed"] is True

    assert (tmp_path / ".codex" / "skills" / "liminal-spec" / "SKILL.md").exists()
    assert (tmp_path / ".codex" / "skills" / "liminal-spec" / "references" / "liminal-spec-format.md").exists()
    assert not (tmp_path / ".agents" / "skills" / "liminal-spec" / "SKILL.md").exists()


def test_logo_assets_are_served(service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    response = client.get("/logo/logo.svg")
    assert response.status_code == 200
    assert "image/svg+xml" in response.headers["content-type"]
