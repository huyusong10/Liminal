from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from loopora import cli
from loopora.bundles import bundle_to_yaml
from loopora.settings import app_home


def test_cli_run_allows_zero_max_iters(monkeypatch, tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.md"
    spec_path.write_text("# Task\n\nKeep going.\n", encoding="utf-8")
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


def test_cli_loop_creation_emits_structured_logs(monkeypatch, tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.md"
    spec_path.write_text("# Task\n\nKeep going.\n", encoding="utf-8")
    workdir = tmp_path / "workdir"
    workdir.mkdir()

    class FakeService:
        def create_loop(self, **kwargs):
            return {"id": "loop_logged", "name": kwargs["name"], "workdir": str(kwargs["workdir"])}

        def rerun(self, loop_id: str, background: bool = False):
            raise AssertionError("loop creation without --start should not rerun")

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
            "Logged Loop",
        ],
    )

    assert result.exit_code == 0, result.stdout
    records = [
        json.loads(line)
        for line in (app_home() / "logs" / "service.log").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    created_record = next(item for item in records if item["event"] == "cli.loop.create.completed")
    assert created_record["loop_id"] == "loop_logged"
    assert created_record["context"]["start"] is False


def test_cli_run_supports_command_mode_background_and_role_models(monkeypatch, tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.md"
    spec_path.write_text("# Task\n\nKeep going.\n", encoding="utf-8")
    workdir = tmp_path / "workdir"
    workdir.mkdir()

    calls: dict[str, object] = {}

    class FakeService:
        def create_loop(self, **kwargs):
            calls["create_loop"] = kwargs
            return {"id": "loop_cmd", "name": kwargs["name"], "workdir": str(kwargs["workdir"])}

        def start_run(self, loop_id: str):
            calls["start_run"] = loop_id
            return {
                "id": "run_cmd",
                "status": "queued",
                "runs_dir": str(tmp_path / "runs" / "run_cmd"),
                "workdir": str(workdir),
            }

        def rerun(self, loop_id: str, background: bool = False):
            raise AssertionError("background CLI path should not call service.rerun()")

    monkeypatch.setattr(cli, "create_service", lambda: FakeService())

    def fake_spawn_background_worker(_service, run: dict):
        calls["spawned_run_id"] = run["id"]
        return run

    monkeypatch.setattr(cli, "_spawn_background_worker", fake_spawn_background_worker)
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
    assert calls["start_run"] == "loop_cmd"
    assert calls["spawned_run_id"] == "run_cmd"
    assert calls["create_loop"]["executor_mode"] == "command"
    assert calls["create_loop"]["command_cli"] == "codex"
    assert "{schema_path}" in calls["create_loop"]["command_args_text"]
    assert "{model}" in calls["create_loop"]["command_args_text"]
    assert calls["create_loop"]["role_models"] == {
        "builder": "gpt-5.4",
        "gatekeeper": "gpt-5.4-mini",
    }


def test_cli_run_supports_round_completion_and_iteration_interval(monkeypatch, tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.md"
    spec_path.write_text("# Task\n\nKeep going.\n", encoding="utf-8")
    workdir = tmp_path / "workdir"
    workdir.mkdir()

    calls: dict[str, object] = {}

    class FakeService:
        def create_loop(self, **kwargs):
            calls["create_loop"] = kwargs
            return {"id": "loop_rounds"}

        def rerun(self, loop_id: str, background: bool = False):
            calls["rerun"] = loop_id
            return {"id": "run_rounds", "status": "succeeded", "runs_dir": str(tmp_path / "runs" / "run_rounds")}

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
            "--completion-mode",
            "rounds",
            "--iteration-interval-seconds",
            "60",
            "--max-iters",
            "2",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert calls["create_loop"]["completion_mode"] == "rounds"
    assert calls["create_loop"]["iteration_interval_seconds"] == 60.0
    assert calls["rerun"] == "loop_rounds"


def test_cli_loops_rerun_background_spawns_worker(monkeypatch, tmp_path: Path) -> None:
    calls: dict[str, object] = {}

    class FakeService:
        def start_run(self, loop_id: str):
            calls["start_run"] = loop_id
            return {
                "id": "run_background",
                "status": "queued",
                "runs_dir": str(tmp_path / "runs" / "run_background"),
                "workdir": str(tmp_path / "workdir"),
            }

        def rerun(self, loop_id: str, background: bool = False):
            raise AssertionError("background CLI path should not call service.rerun()")

    monkeypatch.setattr(cli, "create_service", lambda: FakeService())

    def fake_spawn_background_worker(_service, run: dict):
        calls["spawned"] = run["id"]
        return run

    monkeypatch.setattr(cli, "_spawn_background_worker", fake_spawn_background_worker)
    runner = CliRunner()

    result = runner.invoke(cli.app, ["loops", "rerun", "loop_saved", "--background"])

    assert result.exit_code == 0, result.stdout
    assert calls["start_run"] == "loop_saved"
    assert calls["spawned"] == "run_background"


def test_cli_loops_create_can_save_without_starting(monkeypatch, tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.md"
    spec_path.write_text("# Task\n\nKeep going.\n", encoding="utf-8")
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


def test_cli_loops_create_accepts_orchestration_id(monkeypatch, tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.md"
    spec_path.write_text("# Task\n\nKeep going.\n", encoding="utf-8")
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    calls: dict[str, object] = {}

    class FakeService:
        def create_loop(self, **kwargs):
            calls["create_loop"] = kwargs
            return {"id": "loop_saved", "name": kwargs["name"], "workdir": str(kwargs["workdir"])}

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
            "--orchestration-id",
            "builtin:inspect_first",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert calls["create_loop"]["orchestration_id"] == "builtin:inspect_first"
    assert calls["create_loop"]["workflow"] is None


def test_cli_orchestrations_create_and_list(monkeypatch) -> None:
    calls: dict[str, object] = {}

    class FakeService:
        def create_orchestration(self, **kwargs):
            calls["create_orchestration"] = kwargs
            return {"id": "orch_1", "name": kwargs["name"], "workflow_json": {"roles": [], "steps": []}}

        def list_orchestrations(self):
            return [
                {"id": "builtin:build_first", "name": "Build First", "source": "builtin", "workflow_json": {"roles": [1], "steps": [1]}},
                {"id": "orch_1", "name": "Custom", "source": "custom", "workflow_json": {"roles": [1, 2], "steps": [1, 2]}},
            ]

    monkeypatch.setattr(cli, "create_service", lambda: FakeService())
    runner = CliRunner()

    create_result = runner.invoke(cli.app, ["orchestrations", "create", "--name", "Custom", "--workflow-preset", "inspect_first"])
    assert create_result.exit_code == 0, create_result.stdout
    assert calls["create_orchestration"]["name"] == "Custom"
    assert calls["create_orchestration"]["workflow"] == {"preset": "inspect_first"}

    list_result = runner.invoke(cli.app, ["orchestrations", "list"])
    assert list_result.exit_code == 0, list_result.stdout
    assert "builtin:build_first" in list_result.stdout
    assert "orch_1" in list_result.stdout


def test_cli_orchestrations_get_update_derive_and_delete(monkeypatch) -> None:
    calls: dict[str, object] = {}

    current = {
        "id": "orch_1",
        "name": "Current",
        "description": "Saved orchestration",
        "workflow_json": {"preset": "inspect_first"},
        "prompt_files_json": {"builder.md": "---\nversion: 1\narchetype: builder\n---\nBuilder body\n"},
        "role_models_json": {"builder": "gpt-5.4-mini"},
    }

    class FakeService:
        def get_orchestration(self, orchestration_id: str):
            calls.setdefault("get_ids", []).append(orchestration_id)
            if orchestration_id == "builtin:build_first":
                return {
                    "id": "builtin:build_first",
                    "name": "Build First",
                    "description": "Built-in",
                    "workflow_json": {"preset": "build_first"},
                    "prompt_files_json": {},
                    "role_models_json": {},
                }
            return current

        def update_orchestration(self, orchestration_id: str, **kwargs):
            calls["update"] = (orchestration_id, kwargs)
            return {"id": orchestration_id, **kwargs, "workflow_json": kwargs["workflow"]}

        def create_orchestration(self, **kwargs):
            calls.setdefault("create", []).append(kwargs)
            return {"id": "orch_new", **kwargs, "workflow_json": kwargs["workflow"]}

        def delete_orchestration(self, orchestration_id: str):
            calls["delete"] = orchestration_id
            return {"id": orchestration_id, "deleted": True}

    monkeypatch.setattr(cli, "create_service", lambda: FakeService())
    runner = CliRunner()

    get_result = runner.invoke(cli.app, ["orchestrations", "get", "orch_1"])
    assert get_result.exit_code == 0, get_result.stdout
    assert json.loads(get_result.stdout)["id"] == "orch_1"

    update_result = runner.invoke(cli.app, ["orchestrations", "update", "orch_1", "--name", "Updated", "--workflow-preset", "repair_loop"])
    assert update_result.exit_code == 0, update_result.stdout
    update_id, update_kwargs = calls["update"]
    assert update_id == "orch_1"
    assert update_kwargs["name"] == "Updated"
    assert update_kwargs["workflow"] == {"preset": "repair_loop"}

    derive_result = runner.invoke(cli.app, ["orchestrations", "derive", "builtin:build_first", "--name", "Derived"])
    assert derive_result.exit_code == 0, derive_result.stdout
    assert calls["create"][-1]["name"] == "Derived"
    assert calls["create"][-1]["workflow"] == {"preset": "build_first"}

    delete_result = runner.invoke(cli.app, ["orchestrations", "delete", "orch_1"])
    assert delete_result.exit_code == 0, delete_result.stdout
    assert calls["delete"] == "orch_1"


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


def test_cli_roles_list_get_create_update_derive_and_delete(monkeypatch, tmp_path: Path) -> None:
    calls: dict[str, object] = {}
    prompt_path = tmp_path / "builder.md"
    prompt_path.write_text("---\nversion: 1\narchetype: builder\n---\nBuilder body\n", encoding="utf-8")

    current = {
        "id": "role_custom",
        "name": "Custom Builder",
        "description": "Saved builder",
        "archetype": "builder",
        "prompt_ref": "custom-builder.md",
        "prompt_markdown": "---\nversion: 1\narchetype: builder\n---\nCurrent builder body\n",
        "executor_kind": "codex",
        "executor_mode": "preset",
        "command_cli": "codex",
        "command_args_text": "",
        "model": "gpt-5.4-mini",
        "reasoning_effort": "medium",
    }

    class FakeService:
        def list_role_definitions(self):
            return [
                {"id": "builtin:builder", "name": "Builder", "source": "builtin", "archetype": "builder", "executor_kind": "codex"},
                {"id": "role_custom", "name": "Custom Builder", "source": "custom", "archetype": "builder", "executor_kind": "codex"},
            ]

        def get_role_definition(self, role_definition_id: str):
            calls.setdefault("get_ids", []).append(role_definition_id)
            if role_definition_id == "builtin:builder":
                return {
                    "id": "builtin:builder",
                    "name": "Builder",
                    "description": "Built-in",
                    "archetype": "builder",
                    "prompt_ref": "builder.md",
                    "prompt_markdown": "---\nversion: 1\narchetype: builder\n---\nBuiltin builder body\n",
                    "executor_kind": "codex",
                    "executor_mode": "preset",
                    "command_cli": "codex",
                    "command_args_text": "",
                    "model": "gpt-5.4",
                    "reasoning_effort": "medium",
                }
            return current

        def create_role_definition(self, **kwargs):
            calls.setdefault("create", []).append(kwargs)
            return {"id": "role_new", **kwargs}

        def update_role_definition(self, role_definition_id: str, **kwargs):
            calls["update"] = (role_definition_id, kwargs)
            return {"id": role_definition_id, **kwargs}

        def delete_role_definition(self, role_definition_id: str):
            calls["delete"] = role_definition_id
            return {"id": role_definition_id, "deleted": True}

    monkeypatch.setattr(cli, "create_service", lambda: FakeService())
    runner = CliRunner()

    list_result = runner.invoke(cli.app, ["roles", "list"])
    assert list_result.exit_code == 0, list_result.stdout
    assert "builtin:builder" in list_result.stdout

    get_result = runner.invoke(cli.app, ["roles", "get", "role_custom"])
    assert get_result.exit_code == 0, get_result.stdout
    assert json.loads(get_result.stdout)["id"] == "role_custom"

    create_result = runner.invoke(cli.app, ["roles", "create", "--name", "New Builder", "--archetype", "builder", "--prompt-file", str(prompt_path)])
    assert create_result.exit_code == 0, create_result.stdout
    assert calls["create"][0]["name"] == "New Builder"
    assert "Builder body" in calls["create"][0]["prompt_markdown"]

    update_result = runner.invoke(cli.app, ["roles", "update", "role_custom", "--name", "Updated Builder", "--prompt-file", str(prompt_path)])
    assert update_result.exit_code == 0, update_result.stdout
    update_id, update_kwargs = calls["update"]
    assert update_id == "role_custom"
    assert update_kwargs["name"] == "Updated Builder"
    assert update_kwargs["prompt_ref"] == "custom-builder.md"

    derive_result = runner.invoke(cli.app, ["roles", "derive", "builtin:builder", "--name", "Derived Builder"])
    assert derive_result.exit_code == 0, derive_result.stdout
    assert calls["create"][-1]["name"] == "Derived Builder"
    assert calls["create"][-1]["archetype"] == "builder"

    delete_result = runner.invoke(cli.app, ["roles", "delete", "role_custom"])
    assert delete_result.exit_code == 0, delete_result.stdout
    assert calls["delete"] == "role_custom"


def test_cli_spec_init_accepts_locale_and_validate_reports_check_mode(tmp_path: Path) -> None:
    spec_path = tmp_path / "created-spec.md"
    runner = CliRunner()

    init_result = runner.invoke(cli.app, ["spec", "init", "--locale", "en", str(spec_path)])

    assert init_result.exit_code == 0, init_result.stdout
    created_text = spec_path.read_text(encoding="utf-8")
    assert "# Task" in created_text
    assert "# Done When" in created_text
    assert "# Guardrails" in created_text
    assert "# Role Notes" in created_text
    assert "delete `# Done When`" in created_text

    validate_result = runner.invoke(cli.app, ["spec", "validate", str(spec_path)])

    assert validate_result.exit_code == 0, validate_result.stdout
    payload = json.loads(validate_result.stdout)
    assert payload["ok"] is True
    assert payload["check_mode"] == "specified"


def test_cli_spec_init_accepts_workflow_preset(tmp_path: Path) -> None:
    spec_path = tmp_path / "repair-loop-spec.md"
    runner = CliRunner()

    result = runner.invoke(cli.app, ["spec", "init", "--locale", "en", "--workflow-preset", "repair_loop", str(spec_path)])

    assert result.exit_code == 0, result.stdout
    created_text = spec_path.read_text(encoding="utf-8")
    assert "## Builder Notes" in created_text
    assert "## Inspector Notes" in created_text
    assert "## Guide Notes" in created_text
    assert "## GateKeeper Notes" in created_text
    assert created_text.count("## Builder Notes") == 1


def test_cli_spec_template_read_and_write(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    spec_path = tmp_path / "spec.md"
    source_path = tmp_path / "source.md"
    source_path.write_text("# Task\n\nUpdated task.\n", encoding="utf-8")

    class FakeService:
        def get_orchestration(self, orchestration_id: str):
            assert orchestration_id == "builtin:repair_loop"
            return {"workflow_json": {"preset": "repair_loop"}}

    monkeypatch.setattr(cli, "create_service", lambda: FakeService())

    template_result = runner.invoke(
        cli.app,
        ["spec", "template", "--locale", "en", "--orchestration-id", "builtin:repair_loop", "--json"],
    )
    assert template_result.exit_code == 0, template_result.stdout
    template_payload = json.loads(template_result.stdout)
    assert "# Task" in template_payload["markdown"]
    assert any(item["heading"] == "Builder Notes" for item in template_payload["role_note_sections"])

    write_result = runner.invoke(cli.app, ["spec", "write", str(spec_path), "--from-file", str(source_path)])
    assert write_result.exit_code == 0, write_result.stdout
    write_payload = json.loads(write_result.stdout)
    assert write_payload["validation"]["ok"] is True

    read_result = runner.invoke(cli.app, ["spec", "read", str(spec_path)])
    assert read_result.exit_code == 0, read_result.stdout
    read_payload = json.loads(read_result.stdout)
    assert read_payload["content"] == "# Task\n\nUpdated task.\n"
    assert read_payload["validation"]["ok"] is True


def test_cli_prompts_list_template_and_validate(tmp_path: Path) -> None:
    runner = CliRunner()
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("---\nversion: 1\narchetype: builder\n---\nPrompt body.\n", encoding="utf-8")

    list_result = runner.invoke(cli.app, ["prompts", "list"])
    assert list_result.exit_code == 0, list_result.stdout
    assert any(item["prompt_ref"] == "builder.md" for item in json.loads(list_result.stdout))

    template_result = runner.invoke(cli.app, ["prompts", "template", "builder.md", "--locale", "en"])
    assert template_result.exit_code == 0, template_result.stdout
    assert "version: 1" in template_result.stdout

    validate_result = runner.invoke(cli.app, ["prompts", "validate", str(prompt_path), "--archetype", "builder"])
    assert validate_result.exit_code == 0, validate_result.stdout
    payload = json.loads(validate_result.stdout)
    assert payload["ok"] is True
    assert payload["metadata"]["archetype"] == "builder"


def test_cli_bundles_import_export_derive_and_delete(monkeypatch, tmp_path: Path) -> None:
    calls: dict[str, object] = {}
    runner = CliRunner()
    bundle_path = tmp_path / "task-bundle.yml"
    bundle_path.write_text(
        bundle_to_yaml(
            {
                "version": 1,
                "metadata": {"name": "CLI Bundle", "description": "", "revision": 1},
                "collaboration_summary": "Prefer evidence over rush.",
                "loop": {
                    "name": "CLI Bundle Loop",
                    "workdir": str(tmp_path / "workdir"),
                    "completion_mode": "gatekeeper",
                    "executor_kind": "codex",
                    "executor_mode": "preset",
                    "command_cli": "codex",
                    "command_args_text": "",
                    "model": "",
                    "reasoning_effort": "",
                    "iteration_interval_seconds": 0,
                    "max_iters": 2,
                    "max_role_retries": 1,
                    "delta_threshold": 0.005,
                    "trigger_window": 2,
                    "regression_window": 2,
                },
                "spec": {"markdown": "# Task\n\nShip the change.\n\n# Done When\n- It works.\n"},
                "role_definitions": [
                    {
                        "key": "builder",
                        "name": "Builder",
                        "description": "",
                        "archetype": "builder",
                        "prompt_ref": "builder.md",
                        "prompt_markdown": "---\nversion: 1\narchetype: builder\n---\nBuild it.\n",
                        "posture_notes": "Favor maintainability when possible.",
                        "executor_kind": "codex",
                        "executor_mode": "preset",
                        "command_cli": "codex",
                        "command_args_text": "",
                        "model": "",
                        "reasoning_effort": "",
                    },
                    {
                        "key": "gatekeeper",
                        "name": "GateKeeper",
                        "description": "",
                        "archetype": "gatekeeper",
                        "prompt_ref": "gatekeeper.md",
                        "prompt_markdown": "---\nversion: 1\narchetype: gatekeeper\n---\nJudge it.\n",
                        "posture_notes": "Close only on real evidence.",
                        "executor_kind": "codex",
                        "executor_mode": "preset",
                        "command_cli": "codex",
                        "command_args_text": "",
                        "model": "",
                        "reasoning_effort": "",
                    },
                ],
                "workflow": {
                    "version": 1,
                    "preset": "",
                    "collaboration_intent": "Verify before sign-off.",
                    "roles": [
                        {"id": "builder", "role_definition_key": "builder"},
                        {"id": "gatekeeper", "role_definition_key": "gatekeeper"},
                    ],
                    "steps": [
                        {"id": "builder_step", "role_id": "builder", "on_pass": "continue"},
                        {"id": "gatekeeper_step", "role_id": "gatekeeper", "on_pass": "finish_run"},
                    ],
                },
            }
        ),
        encoding="utf-8",
    )

    class FakeService:
        def import_bundle_file(self, path: Path, *, replace_bundle_id=None):
            calls["import"] = {"path": str(path), "replace_bundle_id": replace_bundle_id}
            return {"id": "bundle_cli", "name": "CLI Bundle"}

        def export_bundle_yaml(self, bundle_id: str):
            calls["export"] = bundle_id
            return "version: 1\nmetadata:\n  name: CLI Bundle\n"

        def write_bundle_file(self, bundle_id: str, path: Path):
            calls["write"] = {"bundle_id": bundle_id, "path": str(path)}
            path.write_text("version: 1\nmetadata:\n  name: CLI Bundle\n", encoding="utf-8")
            return path

        def derive_bundle_from_loop(self, loop_id: str, **kwargs):
            calls["derive"] = {"loop_id": loop_id, **kwargs}
            return {
                "version": 1,
                "metadata": {"name": kwargs.get("name") or "Derived CLI Bundle", "description": "", "revision": 1},
                "collaboration_summary": kwargs.get("collaboration_summary") or "Derived from an existing loop.",
                "loop": {
                    "name": "Derived CLI Bundle",
                    "workdir": str(tmp_path / "workdir"),
                    "completion_mode": "gatekeeper",
                    "executor_kind": "codex",
                    "executor_mode": "preset",
                    "command_cli": "codex",
                    "command_args_text": "",
                    "model": "",
                    "reasoning_effort": "",
                    "iteration_interval_seconds": 0,
                    "max_iters": 2,
                    "max_role_retries": 1,
                    "delta_threshold": 0.005,
                    "trigger_window": 2,
                    "regression_window": 2,
                },
                "spec": {"markdown": "# Task\n\nDerived.\n\n# Done When\n- Ready.\n"},
                "role_definitions": [
                    {
                        "key": "builder",
                        "name": "Builder",
                        "description": "",
                        "archetype": "builder",
                        "prompt_ref": "builder.md",
                        "prompt_markdown": "---\nversion: 1\narchetype: builder\n---\nBuild it.\n",
                        "posture_notes": "",
                        "executor_kind": "codex",
                        "executor_mode": "preset",
                        "command_cli": "codex",
                        "command_args_text": "",
                        "model": "",
                        "reasoning_effort": "",
                    },
                    {
                        "key": "gatekeeper",
                        "name": "GateKeeper",
                        "description": "",
                        "archetype": "gatekeeper",
                        "prompt_ref": "gatekeeper.md",
                        "prompt_markdown": "---\nversion: 1\narchetype: gatekeeper\n---\nJudge it.\n",
                        "posture_notes": "",
                        "executor_kind": "codex",
                        "executor_mode": "preset",
                        "command_cli": "codex",
                        "command_args_text": "",
                        "model": "",
                        "reasoning_effort": "",
                    },
                ],
                "workflow": {
                    "version": 1,
                    "preset": "",
                    "collaboration_intent": "",
                    "roles": [
                        {"id": "builder", "role_definition_key": "builder"},
                        {"id": "gatekeeper", "role_definition_key": "gatekeeper"},
                    ],
                    "steps": [
                        {"id": "builder_step", "role_id": "builder", "on_pass": "continue"},
                        {"id": "gatekeeper_step", "role_id": "gatekeeper", "on_pass": "finish_run"},
                    ],
                },
            }

        def delete_bundle(self, bundle_id: str):
            calls["delete"] = bundle_id
            return {"id": bundle_id, "deleted": True}

    monkeypatch.setattr(cli, "create_service", lambda: FakeService())

    import_result = runner.invoke(
        cli.app,
        ["bundles", "import", str(bundle_path), "--replace-bundle-id", "bundle_old"],
    )
    assert import_result.exit_code == 0, import_result.stdout
    assert calls["import"] == {"path": str(bundle_path), "replace_bundle_id": "bundle_old"}

    export_path = tmp_path / "exported.yml"
    export_result = runner.invoke(cli.app, ["bundles", "export", "bundle_cli", "--output", str(export_path)])
    assert export_result.exit_code == 0, export_result.stdout
    assert calls["write"] == {"bundle_id": "bundle_cli", "path": str(export_path)}
    assert export_path.read_text(encoding="utf-8").startswith("version: 1")

    derive_result = runner.invoke(
        cli.app,
        ["bundles", "derive", "loop_saved", "--name", "Derived CLI Bundle"],
    )
    assert derive_result.exit_code == 0, derive_result.stdout
    assert calls["derive"]["loop_id"] == "loop_saved"
    assert calls["derive"]["name"] == "Derived CLI Bundle"
    assert "Derived CLI Bundle" in derive_result.stdout

    delete_result = runner.invoke(cli.app, ["bundles", "delete", "bundle_cli"])
    assert delete_result.exit_code == 0, delete_result.stdout
    assert calls["delete"] == "bundle_cli"
