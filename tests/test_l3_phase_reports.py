from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_CLI_TEST = REPO_ROOT / "tests" / "test_real_cli_integration.py"
RELEASE_WEB_TEST = REPO_ROOT / "tests" / "test_release_web_e2e.py"


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_real_cli_phase_report_projects_model_resume_and_artifacts(tmp_path: Path) -> None:
    module = _load_module(REAL_CLI_TEST, "real_cli_l3")
    workdir = tmp_path / "work"
    workdir.mkdir()
    run_dir = workdir / ".loopora" / "runs" / "run_123"
    (run_dir / "contract").mkdir(parents=True)
    (run_dir / "summary.md").write_text("summary", encoding="utf-8")
    (run_dir / "contract" / "run_contract.json").write_text("{}", encoding="utf-8")
    artifacts = module.RealRunArtifacts(
        provider="opencode",
        workdir=workdir,
        run={"id": "run_123", "status": "succeeded", "runs_dir": str(run_dir)},
        run_dir=run_dir,
        events=[
            {"id": 1, "event_type": "role_execution_summary", "role": "generator"},
            {"id": 2, "event_type": "role_execution_summary", "role": "generator"},
        ],
        role_requests=[
            {"step_id": "builder_step", "role_id": "builder", "resume_session_id": ""},
            {"step_id": "builder_step", "role_id": "builder", "resume_session_id": "sess_123"},
        ],
        command_events=[
            {
                "id": 1,
                "event_type": "codex_event",
                "payload": {"type": "command", "message": "opencode run --model minimax-token-plan/MiniMax-M2.7 prompt"},
            },
            {
                "id": 2,
                "event_type": "codex_event",
                "payload": {"type": "command", "message": "opencode run --session sess_123 --model minimax-token-plan/MiniMax-M2.7 prompt"},
            },
        ],
        terminal_event={"payload": {"status": "succeeded", "reason": "rounds_completed"}},
    )

    report, report_path = module._write_real_cli_phase_report(
        module.RealCliPhaseReportInput(
            provider="opencode",
            workdir=workdir,
            model="minimax-token-plan/MiniMax-M2.7",
            run=artifacts.run,
            artifacts=artifacts,
        )
    )

    assert report_path == workdir / ".loopora" / "l3" / "real-cli-phase-report.json"
    assert report_path.exists()
    assert report["phase_statuses"]["model_observed"]["ok"] is True
    assert report["phase_statuses"]["resume_session_observed"]["ok"] is True
    assert report["phase_statuses"]["resume_command_shape_observed"]["ok"] is True
    assert report["phase_statuses"]["artifacts_persisted"]["ok"] is True


def test_real_cli_default_model_policy_requires_explicit_override(monkeypatch) -> None:
    module = _load_module(REAL_CLI_TEST, "real_cli_l3_policy")
    monkeypatch.delenv(module.L3_MODEL_OVERRIDE_ENV, raising=False)

    with pytest.raises(AssertionError):
        module._assert_real_cli_model_policy("claude", "other-model")

    monkeypatch.setenv(module.L3_MODEL_OVERRIDE_ENV, "1")
    module._assert_real_cli_model_policy("claude", "other-model")


def test_release_web_phase_report_projects_adapter_state_matrix(tmp_path: Path) -> None:
    module = _load_module(RELEASE_WEB_TEST, "release_web_l3")
    workdir = tmp_path / "release-web-workdir"
    workdir.mkdir()
    events: list[dict] = []

    for adapter in module.ADAPTERS:
        paths = module.AdapterPaths(
            workdir=workdir,
            gen_skill=workdir / adapter / "loopora-gen.md",
            loop_skill=workdir / adapter / "loopora-loop.md",
        )
        paths.gen_skill.parent.mkdir(parents=True, exist_ok=True)
        paths.gen_skill.write_text("managed", encoding="utf-8")
        paths.loop_skill.write_text("managed", encoding="utf-8")
        module._record_release_web_event(
            events,
            module.ReleaseWebEventInput(adapter=adapter, phase="initial", state="not_installed", paths=paths),
        )
        module._record_release_web_event(
            events,
            module.ReleaseWebEventInput(adapter=adapter, phase="install", state="installed", paths=paths),
        )
        module._record_release_web_event(
            events,
            module.ReleaseWebEventInput(adapter=adapter, phase="drift", state="needs_update", paths=paths),
        )
        module._record_release_web_event(
            events,
            module.ReleaseWebEventInput(adapter=adapter, phase="conflict", state="error", paths=paths, preserved=True),
        )

    report, report_path = module._write_release_web_phase_report(
        module.ReleaseWebPhaseReportInput(
            workdir=workdir,
            base_url="http://127.0.0.1:12345",
            command=["python", "-m", "loopora", "serve"],
            events=events,
            server_ready=True,
        )
    )

    assert report_path == workdir / ".loopora" / "l3" / "release-web-phase-report.json"
    assert report_path.exists()
    assert report["phase_statuses"]["server_ready"]["ok"] is True
    for adapter in module.ADAPTERS:
        assert report["phase_statuses"][f"{adapter}_states_observed"]["ok"] is True
        assert report["phase_statuses"][f"{adapter}_conflict_preserved"]["ok"] is True
