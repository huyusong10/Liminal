from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from liminal import cli


def test_cli_run_allows_zero_max_iters(monkeypatch, tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.md"
    spec_path.write_text("# Goal\n\nKeep going.\n", encoding="utf-8")
    workdir = tmp_path / "workdir"
    workdir.mkdir()

    calls: dict[str, object] = {}

    class FakeService:
        def create_loop(self, **kwargs):
            calls["create_loop"] = kwargs
            return {"id": "loop_test"}

        def rerun(self, loop_id: str, background: bool = False):
            calls["rerun"] = loop_id
            calls["background"] = background
            return {"id": "run_test", "status": "running", "runs_dir": str(tmp_path / "runs" / "run_test")}

    monkeypatch.setattr(cli, "create_service", lambda: FakeService())
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        [
            "run",
            "--spec",
            str(spec_path),
            "--workdir",
            str(workdir),
            "--max-iters",
            "0",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert calls["create_loop"]["max_iters"] == 0
    assert calls["rerun"] == "loop_test"
    assert calls["background"] is False


def test_cli_run_supports_command_mode_background_and_role_models(monkeypatch, tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.md"
    spec_path.write_text("# Goal\n\nKeep going.\n", encoding="utf-8")
    workdir = tmp_path / "workdir"
    workdir.mkdir()

    calls: dict[str, object] = {}

    class FakeService:
        def create_loop(self, **kwargs):
            calls["create_loop"] = kwargs
            return {"id": "loop_cmd", "name": kwargs["name"], "workdir": str(kwargs["workdir"])}

        def rerun(self, loop_id: str, background: bool = False):
            calls["rerun"] = loop_id
            calls["background"] = background
            return {"id": "run_cmd", "status": "queued", "runs_dir": str(tmp_path / "runs" / "run_cmd")}

    monkeypatch.setattr(cli, "create_service", lambda: FakeService())
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        [
            "run",
            "--spec",
            str(spec_path),
            "--workdir",
            str(workdir),
            "--executor",
            "codex",
            "--executor-mode",
            "command",
            "--command-cli",
            "codex",
            "--command-arg",
            "exec",
            "--command-arg",
            "--json",
            "--command-arg",
            "--output-schema",
            "--command-arg",
            "{schema_path}",
            "--command-arg",
            "--output-last-message",
            "--command-arg",
            "{output_path}",
            "--command-arg",
            "--model",
            "--command-arg",
            "{model}",
            "--command-arg",
            "{prompt}",
            "--model",
            "gpt-5.4-mini",
            "--role-model",
            "generator=gpt-5.4",
            "--role-model",
            "verifier=gpt-5.4-mini",
            "--background",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert calls["rerun"] == "loop_cmd"
    assert calls["background"] is True
    assert calls["create_loop"]["executor_mode"] == "command"
    assert calls["create_loop"]["command_cli"] == "codex"
    assert "{schema_path}" in calls["create_loop"]["command_args_text"]
    assert "{model}" in calls["create_loop"]["command_args_text"]
    assert calls["create_loop"]["role_models"] == {
        "generator": "gpt-5.4",
        "verifier": "gpt-5.4-mini",
    }


def test_cli_loops_create_can_save_without_starting(monkeypatch, tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.md"
    spec_path.write_text("# Goal\n\nKeep going.\n", encoding="utf-8")
    workdir = tmp_path / "workdir"
    workdir.mkdir()

    calls: dict[str, object] = {}

    class FakeService:
        def create_loop(self, **kwargs):
            calls["create_loop"] = kwargs
            return {"id": "loop_saved", "name": kwargs["name"], "workdir": str(kwargs["workdir"])}

        def rerun(self, loop_id: str, background: bool = False):
            calls["rerun"] = (loop_id, background)
            return {"id": "run_saved", "status": "queued", "runs_dir": str(tmp_path / "runs" / "run_saved")}

    monkeypatch.setattr(cli, "create_service", lambda: FakeService())
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        [
            "loops",
            "create",
            "--spec",
            str(spec_path),
            "--workdir",
            str(workdir),
            "--name",
            "Saved Loop",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert calls["create_loop"]["name"] == "Saved Loop"
    assert "rerun" not in calls


def test_cli_loops_delete_prints_json(monkeypatch) -> None:
    class FakeService:
        def delete_loop(self, loop_id: str):
            return {"id": loop_id, "deleted_runs": 2, "workdir": "/tmp/project"}

    monkeypatch.setattr(cli, "create_service", lambda: FakeService())
    runner = CliRunner()

    result = runner.invoke(cli.app, ["loops", "delete", "loop_test"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["id"] == "loop_test"
    assert payload["deleted_runs"] == 2


def test_cli_spec_init_accepts_locale_and_validate_reports_check_mode(tmp_path: Path) -> None:
    spec_path = tmp_path / "created-spec.md"
    runner = CliRunner()

    init_result = runner.invoke(cli.app, ["spec", "init", "--locale", "en", str(spec_path)])

    assert init_result.exit_code == 0, init_result.stdout
    created_text = spec_path.read_text(encoding="utf-8")
    assert "Delete the whole `# Checks` section" in created_text

    validate_result = runner.invoke(cli.app, ["spec", "validate", str(spec_path)])

    assert validate_result.exit_code == 0, validate_result.stdout
    payload = json.loads(validate_result.stdout)
    assert payload["ok"] is True
    assert payload["check_mode"] == "specified"
