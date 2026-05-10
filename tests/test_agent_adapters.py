from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from loopora import cli
import loopora.agent_web as agent_web
from loopora.executor_fake_payloads import alignment_bundle_yaml
from loopora.service_agent_adapters import AgentBundleCandidateRequest
from loopora.service_types import LooporaConflictError
from loopora.web import build_app


def _error_text(result) -> str:
    try:
        return result.stderr
    except ValueError:
        return result.output


def _codex_skill_paths(workdir: Path) -> dict[str, Path]:
    return {
        "gen": workdir / ".agents" / "skills" / "loopora-gen" / "SKILL.md",
        "loop": workdir / ".agents" / "skills" / "loopora-loop" / "SKILL.md",
    }


def _claude_skill_paths(workdir: Path) -> dict[str, Path]:
    return {
        "gen": workdir / ".claude" / "skills" / "loopora-gen" / "SKILL.md",
        "loop": workdir / ".claude" / "skills" / "loopora-loop" / "SKILL.md",
    }


def _opencode_command_paths(workdir: Path) -> dict[str, Path]:
    return {
        "gen": workdir / ".opencode" / "commands" / "loopora-gen.md",
        "loop": workdir / ".opencode" / "commands" / "loopora-loop.md",
    }


def _assert_claude_managed_install(workdir: Path, skill_paths: dict[str, Path]) -> tuple[Path, str]:
    gen_skill = skill_paths["gen"].read_text(encoding="utf-8")
    loop_skill = skill_paths["loop"].read_text(encoding="utf-8")
    assert "LOOPORA-MANAGED: claude-code-adapter" in gen_skill
    assert "disable-model-invocation: true" in gen_skill
    assert "allowed-tools:" in gen_skill
    assert "LOOPORA_AGENT_ENTRY_SOURCE=claude_project_skill" in gen_skill
    assert 'loopora agent claude gen --workdir "$PWD"' in gen_skill
    assert '--context-id "${CLAUDE_SESSION_ID}"' in gen_skill
    assert "--entry-source claude_project_skill" in gen_skill
    assert "LOOPORA_AGENT_ENTRY_SOURCE=claude_project_skill" in loop_skill
    assert 'loopora agent claude loop --workdir "$PWD"' in loop_skill
    assert '--context-id "${CLAUDE_SESSION_ID}"' in loop_skill
    assert "--entry-source claude_project_skill" in loop_skill
    manifest_path = workdir / ".loopora" / "adapters" / "claude" / "manifest.json"
    assert manifest_path.exists()
    first_manifest = manifest_path.read_text(encoding="utf-8")
    assert {item["path"] for item in json.loads(first_manifest)["managed_files"]} == {
        ".claude/skills/loopora-gen/SKILL.md",
        ".claude/skills/loopora-loop/SKILL.md",
    }
    return manifest_path, first_manifest


def _assert_opencode_managed_install(workdir: Path, command_paths: dict[str, Path]) -> tuple[Path, str]:
    gen_command = command_paths["gen"].read_text(encoding="utf-8")
    loop_command = command_paths["loop"].read_text(encoding="utf-8")
    assert "LOOPORA-MANAGED: opencode-adapter" in gen_command
    assert "description:" in gen_command
    assert "agent: build" in gen_command
    assert "$ARGUMENTS" in gen_command
    assert "LOOPORA_AGENT_ENTRY_SOURCE=opencode_project_command" in gen_command
    assert 'loopora agent opencode gen --workdir "$PWD"' in gen_command
    assert '--context-id "${OPENCODE_SESSION_ID:-}"' in gen_command
    assert "--entry-source opencode_project_command" in gen_command
    assert "LOOPORA_AGENT_ENTRY_SOURCE=opencode_project_command" in loop_command
    assert 'loopora agent opencode loop --workdir "$PWD"' in loop_command
    assert '--context-id "${OPENCODE_SESSION_ID:-}"' in loop_command
    assert "--entry-source opencode_project_command" in loop_command
    manifest_path = workdir / ".loopora" / "adapters" / "opencode" / "manifest.json"
    assert manifest_path.exists()
    first_manifest = manifest_path.read_text(encoding="utf-8")
    assert {item["path"] for item in json.loads(first_manifest)["managed_files"]} == {
        ".opencode/commands/loopora-gen.md",
        ".opencode/commands/loopora-loop.md",
    }
    return manifest_path, first_manifest


def test_cli_codex_adapter_install_uninstall_are_idempotent(tmp_path: Path) -> None:
    workdir = tmp_path / "project"
    workdir.mkdir()
    runner = CliRunner()

    first_install = runner.invoke(cli.app, ["init", "codex", "--workdir", str(workdir), "--json"])
    assert first_install.exit_code == 0, first_install.stdout
    assert json.loads(first_install.stdout)["status"] == "installed"
    skill_paths = _codex_skill_paths(workdir)
    assert skill_paths["gen"].exists()
    assert skill_paths["loop"].exists()
    gen_skill = skill_paths["gen"].read_text(encoding="utf-8")
    loop_skill = skill_paths["loop"].read_text(encoding="utf-8")
    assert "LOOPORA-MANAGED: codex-adapter" in gen_skill
    assert "name: loopora-gen" in gen_skill
    assert "LOOPORA_AGENT_ENTRY_SOURCE=codex_project_skill" in gen_skill
    assert 'loopora agent codex gen --workdir "$PWD"' in gen_skill
    assert "--bundle-file" in gen_skill
    assert "--entry-source codex_project_skill" in gen_skill
    assert "name: loopora-loop" in loop_skill
    assert "LOOPORA_AGENT_ENTRY_SOURCE=codex_project_skill" in loop_skill
    assert 'loopora agent codex loop --workdir "$PWD"' in loop_skill
    assert "--entry-source codex_project_skill" in loop_skill
    manifest_path = workdir / ".loopora" / "adapters" / "codex" / "manifest.json"
    assert manifest_path.exists()
    first_manifest = manifest_path.read_text(encoding="utf-8")
    manifest_payload = json.loads(first_manifest)
    assert {item["path"] for item in manifest_payload["managed_files"]} == {
        ".agents/skills/loopora-gen/SKILL.md",
        ".agents/skills/loopora-loop/SKILL.md",
    }
    assert all(len(item["sha256"]) == 64 for item in manifest_payload["managed_files"])

    second_install = runner.invoke(cli.app, ["init", "codex", "--workdir", str(workdir), "--json"])

    assert second_install.exit_code == 0, second_install.stdout
    assert json.loads(second_install.stdout)["status"] == "installed"
    assert manifest_path.read_text(encoding="utf-8") == first_manifest

    first_uninstall = runner.invoke(cli.app, ["uninstall", "codex", "--workdir", str(workdir), "--json"])
    second_uninstall = runner.invoke(cli.app, ["uninstall", "codex", "--workdir", str(workdir), "--json"])

    assert first_uninstall.exit_code == 0, first_uninstall.stdout
    assert second_uninstall.exit_code == 0, second_uninstall.stdout
    assert json.loads(first_uninstall.stdout)["status"] == "not_installed"
    assert json.loads(second_uninstall.stdout)["status"] == "not_installed"
    assert not skill_paths["gen"].exists()
    assert not skill_paths["loop"].exists()
    assert not (workdir / ".loopora" / "adapters" / "codex" / "manifest.json").exists()


def test_cli_codex_loop_requires_ready_bundle(tmp_path: Path) -> None:
    workdir = tmp_path / "project"
    workdir.mkdir()
    runner = CliRunner()

    result = runner.invoke(cli.app, ["agent", "codex", "loop", "--workdir", str(workdir), "--no-web"])

    assert result.exit_code == 1
    assert "/loopora-gen" in _error_text(result)


def test_cli_claude_adapter_install_uninstall_are_idempotent_and_preserve_user_config(tmp_path: Path) -> None:
    workdir = tmp_path / "project"
    workdir.mkdir()
    claude_md = workdir / "CLAUDE.md"
    claude_settings = workdir / ".claude" / "settings.json"
    claude_command = workdir / ".claude" / "commands" / "loopora-gen.md"
    claude_settings.parent.mkdir()
    claude_command.parent.mkdir()
    claude_md.write_text("# User Claude instructions\n", encoding="utf-8")
    claude_settings.write_text('{"permissions": {"allow": []}}\n', encoding="utf-8")
    claude_command.write_text("# User-owned command\n", encoding="utf-8")
    runner = CliRunner()

    first_install = runner.invoke(cli.app, ["init", "claude", "--workdir", str(workdir), "--json"])

    assert first_install.exit_code == 0, first_install.stdout
    assert json.loads(first_install.stdout)["status"] == "installed"
    skill_paths = _claude_skill_paths(workdir)
    assert skill_paths["gen"].exists()
    assert skill_paths["loop"].exists()
    manifest_path, first_manifest = _assert_claude_managed_install(workdir, skill_paths)
    assert claude_md.read_text(encoding="utf-8") == "# User Claude instructions\n"
    assert claude_settings.read_text(encoding="utf-8") == '{"permissions": {"allow": []}}\n'
    assert claude_command.read_text(encoding="utf-8") == "# User-owned command\n"

    second_install = runner.invoke(cli.app, ["init", "claude", "--workdir", str(workdir), "--json"])

    assert second_install.exit_code == 0, second_install.stdout
    assert manifest_path.read_text(encoding="utf-8") == first_manifest

    first_uninstall = runner.invoke(cli.app, ["uninstall", "claude", "--workdir", str(workdir), "--json"])
    second_uninstall = runner.invoke(cli.app, ["uninstall", "claude", "--workdir", str(workdir), "--json"])

    assert first_uninstall.exit_code == 0, first_uninstall.stdout
    assert second_uninstall.exit_code == 0, second_uninstall.stdout
    assert json.loads(first_uninstall.stdout)["status"] == "not_installed"
    assert json.loads(second_uninstall.stdout)["status"] == "not_installed"
    assert not skill_paths["gen"].exists()
    assert not skill_paths["loop"].exists()
    assert claude_md.exists()
    assert claude_settings.exists()
    assert claude_command.exists()


def test_cli_claude_loop_requires_ready_bundle(tmp_path: Path) -> None:
    workdir = tmp_path / "project"
    workdir.mkdir()
    runner = CliRunner()

    result = runner.invoke(cli.app, ["agent", "claude", "loop", "--workdir", str(workdir), "--no-web"])

    assert result.exit_code == 1
    assert "/loopora-gen" in _error_text(result)


def test_cli_opencode_adapter_install_uninstall_are_idempotent_and_preserve_user_config(tmp_path: Path) -> None:
    workdir = tmp_path / "project"
    workdir.mkdir()
    opencode_json = workdir / "opencode.json"
    opencode_project_json = workdir / ".opencode" / "opencode.jsonc"
    opencode_agent = workdir / ".opencode" / "agents" / "review.md"
    opencode_project_json.parent.mkdir()
    opencode_agent.parent.mkdir()
    opencode_json.write_text('{"model": "user/model"}\n', encoding="utf-8")
    opencode_project_json.write_text('{"permission": {"bash": "ask"}}\n', encoding="utf-8")
    opencode_agent.write_text("# User-owned OpenCode agent\n", encoding="utf-8")
    runner = CliRunner()

    first_install = runner.invoke(cli.app, ["init", "opencode", "--workdir", str(workdir), "--json"])

    assert first_install.exit_code == 0, first_install.stdout
    assert json.loads(first_install.stdout)["status"] == "installed"
    command_paths = _opencode_command_paths(workdir)
    assert command_paths["gen"].exists()
    assert command_paths["loop"].exists()
    manifest_path, first_manifest = _assert_opencode_managed_install(workdir, command_paths)
    assert opencode_json.read_text(encoding="utf-8") == '{"model": "user/model"}\n'
    assert opencode_project_json.read_text(encoding="utf-8") == '{"permission": {"bash": "ask"}}\n'
    assert opencode_agent.read_text(encoding="utf-8") == "# User-owned OpenCode agent\n"

    second_install = runner.invoke(cli.app, ["init", "opencode", "--workdir", str(workdir), "--json"])

    assert second_install.exit_code == 0, second_install.stdout
    assert manifest_path.read_text(encoding="utf-8") == first_manifest

    first_uninstall = runner.invoke(cli.app, ["uninstall", "opencode", "--workdir", str(workdir), "--json"])
    second_uninstall = runner.invoke(cli.app, ["uninstall", "opencode", "--workdir", str(workdir), "--json"])

    assert first_uninstall.exit_code == 0, first_uninstall.stdout
    assert second_uninstall.exit_code == 0, second_uninstall.stdout
    assert json.loads(first_uninstall.stdout)["status"] == "not_installed"
    assert json.loads(second_uninstall.stdout)["status"] == "not_installed"
    assert not command_paths["gen"].exists()
    assert not command_paths["loop"].exists()
    assert opencode_json.exists()
    assert opencode_project_json.exists()
    assert opencode_agent.exists()


def test_cli_opencode_loop_requires_ready_bundle(tmp_path: Path) -> None:
    workdir = tmp_path / "project"
    workdir.mkdir()
    runner = CliRunner()

    result = runner.invoke(cli.app, ["agent", "opencode", "loop", "--workdir", str(workdir), "--no-web"])

    assert result.exit_code == 1
    assert "/loopora-gen" in _error_text(result)


def test_cli_codex_gen_accepts_ready_bundle_without_starting_run(tmp_path: Path, sample_workdir: Path) -> None:
    bundle_file = tmp_path / "bundle.yml"
    bundle_file.write_text(alignment_bundle_yaml(str(sample_workdir.resolve())), encoding="utf-8")
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        [
            "agent",
            "codex",
            "gen",
            "--workdir",
            str(sample_workdir),
            "--message",
            "Prepare a governed implementation loop.",
            "--bundle-file",
            str(bundle_file),
            "--no-web",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["ready"] is True
    assert payload["status"] == "ready"
    assert payload["preview_url"].startswith("/loops/new/bundle?alignment_session_id=")
    assert "run" not in payload


def test_cli_claude_gen_accepts_ready_bundle_without_starting_run(tmp_path: Path, sample_workdir: Path) -> None:
    bundle_file = tmp_path / "bundle.yml"
    bundle_file.write_text(alignment_bundle_yaml(str(sample_workdir.resolve())), encoding="utf-8")
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        [
            "agent",
            "claude",
            "gen",
            "--workdir",
            str(sample_workdir),
            "--message",
            "Prepare a governed implementation loop.",
            "--bundle-file",
            str(bundle_file),
            "--context-id",
            "claude-session-a",
            "--entry-source",
            "claude_project_skill",
            "--no-web",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["adapter"] == "claude"
    assert payload["ready"] is True
    assert payload["status"] == "ready"
    assert payload["binding"]["context_source"] == "explicit"
    assert payload["binding"]["entry_invocations"][-1]["entry_source"] == "claude_project_skill"
    assert payload["preview_url"].startswith("/loops/new/bundle?alignment_session_id=")
    assert "run" not in payload


def test_cli_agent_runtime_accepts_managed_entry_source_from_env(monkeypatch, tmp_path: Path, sample_workdir: Path) -> None:
    bundle_file = tmp_path / "bundle.yml"
    bundle_file.write_text(alignment_bundle_yaml(str(sample_workdir.resolve())), encoding="utf-8")
    monkeypatch.setenv("LOOPORA_AGENT_ENTRY_SOURCE", "claude_project_skill")
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        [
            "agent",
            "claude",
            "gen",
            "--workdir",
            str(sample_workdir),
            "--message",
            "Prepare a governed implementation loop.",
            "--bundle-file",
            str(bundle_file),
            "--context-id",
            "claude-session-a",
            "--no-web",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["binding"]["entry_invocations"][-1]["entry_source"] == "claude_project_skill"


def test_cli_opencode_gen_accepts_ready_bundle_without_starting_run(monkeypatch, tmp_path: Path, sample_workdir: Path) -> None:
    bundle_file = tmp_path / "bundle.yml"
    bundle_file.write_text(alignment_bundle_yaml(str(sample_workdir.resolve())), encoding="utf-8")
    monkeypatch.setenv("CODEX_SESSION_ID", "codex-thread-must-not-bind-opencode")
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        [
            "agent",
            "opencode",
            "gen",
            "--workdir",
            str(sample_workdir),
            "--message",
            "Prepare a governed implementation loop.",
            "--bundle-file",
            str(bundle_file),
            "--entry-source",
            "opencode_project_command",
            "--no-web",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["adapter"] == "opencode"
    assert payload["ready"] is True
    assert payload["status"] == "ready"
    assert payload["binding"]["context_source"] == "workdir"
    assert payload["binding"]["entry_invocations"][-1]["entry_source"] == "opencode_project_command"
    assert payload["preview_url"].startswith("/loops/new/bundle?alignment_session_id=")
    assert "run" not in payload


def test_codex_adapter_install_does_not_touch_user_configuration(service_factory, tmp_path: Path) -> None:
    service = service_factory(scenario="success")
    workdir = tmp_path / "project"
    workdir.mkdir()
    agents = workdir / "AGENTS.md"
    codex_config = workdir / ".codex" / "config.toml"
    codex_config.parent.mkdir()
    agents.write_text("# User project rules\n", encoding="utf-8")
    codex_config.write_text("model = \"user-choice\"\n", encoding="utf-8")

    service.install_agent_adapter("codex", workdir=workdir)
    service.uninstall_agent_adapter("codex", workdir=workdir)

    assert agents.read_text(encoding="utf-8") == "# User project rules\n"
    assert codex_config.read_text(encoding="utf-8") == "model = \"user-choice\"\n"


def test_codex_adapter_refuses_unowned_target_files(service_factory, tmp_path: Path) -> None:
    service = service_factory(scenario="success")
    workdir = tmp_path / "project"
    custom_skill = workdir / ".agents" / "skills" / "loopora-gen" / "SKILL.md"
    custom_skill.parent.mkdir(parents=True)
    custom_skill.write_text("# User-owned skill\n", encoding="utf-8")

    with pytest.raises(LooporaConflictError):
        service.install_agent_adapter("codex", workdir=workdir)

    assert custom_skill.read_text(encoding="utf-8") == "# User-owned skill\n"


def test_claude_adapter_refuses_unowned_target_files(service_factory, tmp_path: Path) -> None:
    service = service_factory(scenario="success")
    workdir = tmp_path / "project"
    custom_skill = workdir / ".claude" / "skills" / "loopora-gen" / "SKILL.md"
    custom_skill.parent.mkdir(parents=True)
    custom_skill.write_text("# User-owned Claude skill\n", encoding="utf-8")

    with pytest.raises(LooporaConflictError):
        service.install_agent_adapter("claude", workdir=workdir)

    assert custom_skill.read_text(encoding="utf-8") == "# User-owned Claude skill\n"


def test_opencode_adapter_refuses_unowned_target_files(service_factory, tmp_path: Path) -> None:
    service = service_factory(scenario="success")
    workdir = tmp_path / "project"
    custom_command = workdir / ".opencode" / "commands" / "loopora-gen.md"
    custom_command.parent.mkdir(parents=True)
    custom_command.write_text("# User-owned OpenCode command\n", encoding="utf-8")

    with pytest.raises(LooporaConflictError):
        service.install_agent_adapter("opencode", workdir=workdir)

    assert custom_command.read_text(encoding="utf-8") == "# User-owned OpenCode command\n"


def test_codex_adapter_status_reports_needs_update_for_managed_drift(service_factory, tmp_path: Path) -> None:
    service = service_factory(scenario="success")
    workdir = tmp_path / "project"
    workdir.mkdir()

    service.install_agent_adapter("codex", workdir=workdir)
    skill_path = workdir / ".agents" / "skills" / "loopora-gen" / "SKILL.md"
    skill_path.write_text(skill_path.read_text(encoding="utf-8") + "\n<!-- locally stale managed file -->\n", encoding="utf-8")

    status = service.get_agent_adapter("codex", workdir=workdir)

    assert status["status"] == "needs_update"
    assert any(item["path"].endswith("loopora-gen/SKILL.md") and item["state"] == "needs_update" for item in status["managed_files"])


def test_codex_adapter_status_reports_error_for_manifest_tracked_user_edit_without_marker(service_factory, tmp_path: Path) -> None:
    service = service_factory(scenario="success")
    workdir = tmp_path / "project"
    workdir.mkdir()

    service.install_agent_adapter("codex", workdir=workdir)
    skill_path = workdir / ".agents" / "skills" / "loopora-gen" / "SKILL.md"
    skill_path.write_text("# User edited this file after install\n", encoding="utf-8")

    status = service.get_agent_adapter("codex", workdir=workdir)

    assert status["status"] == "error"
    assert "loopora-gen/SKILL.md" in status["error"]
    with pytest.raises(LooporaConflictError):
        service.install_agent_adapter("codex", workdir=workdir)
    assert skill_path.read_text(encoding="utf-8") == "# User edited this file after install\n"


def test_claude_adapter_status_reports_needs_update_for_managed_drift(service_factory, tmp_path: Path) -> None:
    service = service_factory(scenario="success")
    workdir = tmp_path / "project"
    workdir.mkdir()

    service.install_agent_adapter("claude", workdir=workdir)
    skill_path = workdir / ".claude" / "skills" / "loopora-gen" / "SKILL.md"
    skill_path.write_text(skill_path.read_text(encoding="utf-8") + "\n<!-- locally stale managed file -->\n", encoding="utf-8")

    status = service.get_agent_adapter("claude", workdir=workdir)

    assert status["status"] == "needs_update"
    assert any(item["path"].endswith("loopora-gen/SKILL.md") and item["state"] == "needs_update" for item in status["managed_files"])


def test_opencode_adapter_status_reports_needs_update_for_managed_drift(service_factory, tmp_path: Path) -> None:
    service = service_factory(scenario="success")
    workdir = tmp_path / "project"
    workdir.mkdir()

    service.install_agent_adapter("opencode", workdir=workdir)
    command_path = workdir / ".opencode" / "commands" / "loopora-gen.md"
    command_path.write_text(command_path.read_text(encoding="utf-8") + "\n<!-- locally stale managed file -->\n", encoding="utf-8")

    status = service.get_agent_adapter("opencode", workdir=workdir)

    assert status["status"] == "needs_update"
    assert any(item["path"].endswith("loopora-gen.md") and item["state"] == "needs_update" for item in status["managed_files"])


def test_codex_agent_gen_validates_ready_bundle_and_loop_starts_run(
    service_factory,
    tmp_path: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    bundle_file = tmp_path / "bundle.yml"
    bundle_file.write_text(alignment_bundle_yaml(str(sample_workdir.resolve())), encoding="utf-8")

    generated = service.create_agent_bundle_candidate(
        AgentBundleCandidateRequest(
            adapter="codex",
            workdir=sample_workdir,
            message="Ship the focused starter experience.",
            bundle_file=bundle_file,
            entry_source="codex_project_skill",
        )
    )

    assert generated["ready"] is True
    assert generated["status"] == "ready"
    assert generated["preview_path"].startswith("/loops/new/bundle?alignment_session_id=")
    assert generated["binding"]["entry_invocations"][-1]["action"] == "gen"
    assert generated["binding"]["entry_invocations"][-1]["entry_source"] == "codex_project_skill"

    started = service.start_agent_loop("codex", workdir=sample_workdir, entry_source="codex_project_skill", execute_async=False)

    assert started["run"]["id"]
    assert started["run_path"] == f"/runs/{started['run']['id']}"
    assert started["started_new_run"] is True
    assert started["session"]["status"] == "running_loop"
    assert [item["action"] for item in started["binding"]["entry_invocations"][-2:]] == ["gen", "loop"]
    assert {item["entry_source"] for item in started["binding"]["entry_invocations"][-2:]} == {"codex_project_skill"}


def test_claude_agent_gen_validates_ready_bundle_and_loop_starts_run(
    service_factory,
    tmp_path: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    bundle_file = tmp_path / "bundle.yml"
    bundle_file.write_text(alignment_bundle_yaml(str(sample_workdir.resolve())), encoding="utf-8")

    generated = service.create_agent_bundle_candidate(
        AgentBundleCandidateRequest(
            adapter="claude",
            workdir=sample_workdir,
            message="Ship the focused starter experience.",
            bundle_file=bundle_file,
            context_id="claude-session-a",
            entry_source="claude_project_skill",
        )
    )

    assert generated["adapter"] == "claude"
    assert generated["ready"] is True
    assert generated["binding"]["context_source"] == "explicit"
    assert generated["binding"]["entry_invocations"][-1]["entry_source"] == "claude_project_skill"

    started = service.start_agent_loop("claude", workdir=sample_workdir, context_id="claude-session-a", entry_source="claude_project_skill", execute_async=False)

    assert started["adapter"] == "claude"
    assert started["run"]["id"]
    assert started["started_new_run"] is True
    assert [item["action"] for item in started["binding"]["entry_invocations"][-2:]] == ["gen", "loop"]
    assert {item["entry_source"] for item in started["binding"]["entry_invocations"][-2:]} == {"claude_project_skill"}


def test_opencode_agent_gen_validates_ready_bundle_and_loop_starts_run(
    service_factory,
    monkeypatch,
    tmp_path: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    bundle_file = tmp_path / "bundle.yml"
    bundle_file.write_text(alignment_bundle_yaml(str(sample_workdir.resolve())), encoding="utf-8")
    monkeypatch.setenv("CODEX_SESSION_ID", "codex-thread-must-not-bind-opencode")

    generated = service.create_agent_bundle_candidate(
        AgentBundleCandidateRequest(
            adapter="opencode",
            workdir=sample_workdir,
            message="Ship the focused starter experience.",
            bundle_file=bundle_file,
            entry_source="opencode_project_command",
        )
    )

    assert generated["adapter"] == "opencode"
    assert generated["ready"] is True
    assert generated["binding"]["context_source"] == "workdir"
    assert generated["binding"]["entry_invocations"][-1]["entry_source"] == "opencode_project_command"

    started = service.start_agent_loop("opencode", workdir=sample_workdir, entry_source="opencode_project_command", execute_async=False)

    assert started["adapter"] == "opencode"
    assert started["run"]["id"]
    assert started["started_new_run"] is True
    assert [item["action"] for item in started["binding"]["entry_invocations"][-2:]] == ["gen", "loop"]
    assert {item["entry_source"] for item in started["binding"]["entry_invocations"][-2:]} == {"opencode_project_command"}


def test_codex_agent_binding_is_scoped_by_host_context(service_factory, tmp_path: Path, sample_workdir: Path) -> None:
    service = service_factory(scenario="success")
    bundle_file = tmp_path / "bundle.yml"
    bundle_file.write_text(alignment_bundle_yaml(str(sample_workdir.resolve())), encoding="utf-8")

    service.create_agent_bundle_candidate(
        AgentBundleCandidateRequest(
            adapter="codex",
            workdir=sample_workdir,
            message="Bind this READY bundle to one Codex thread.",
            bundle_file=bundle_file,
            context_id="thread-a",
        )
    )

    with pytest.raises(LooporaConflictError, match="/loopora-gen"):
        service.start_agent_loop("codex", workdir=sample_workdir, context_id="thread-b", execute_async=False)

    started = service.start_agent_loop("codex", workdir=sample_workdir, context_id="thread-a", execute_async=False)

    assert started["started_new_run"] is True
    assert started["binding"]["context_source"] == "explicit"


def test_cli_codex_loop_spawns_background_worker(monkeypatch, tmp_path: Path) -> None:
    workdir = tmp_path / "project"
    workdir.mkdir()
    run_dir = tmp_path / "run"
    calls: dict[str, object] = {}

    class FakeService:
        def start_agent_loop(self, adapter: str, *, workdir: Path, context_id: str = "", entry_source: str = "", execute_async: bool = True):
            calls["adapter"] = adapter
            calls["workdir"] = workdir
            calls["context_id"] = context_id
            calls["entry_source"] = entry_source
            calls["execute_async"] = execute_async
            return {
                "run": {
                    "id": "run_agent",
                    "status": "queued",
                    "runs_dir": str(run_dir),
                    "workdir": str(workdir),
                },
                "run_path": "/runs/run_agent",
                "started_new_run": True,
            }

    monkeypatch.setattr(cli, "create_service", FakeService)

    def fake_spawn_background_worker(_service, run: dict) -> dict:
        calls["spawned_run_id"] = run["id"]
        return {**run, "runner_pid": 1234}

    monkeypatch.setattr(cli, "_spawn_background_worker", fake_spawn_background_worker)
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        ["agent", "codex", "loop", "--workdir", str(workdir), "--context-id", "thread-1", "--no-web"],
    )

    assert result.exit_code == 0, result.stdout
    assert calls["adapter"] == "codex"
    assert calls["workdir"] == workdir
    assert calls["context_id"] == "thread-1"
    assert calls["entry_source"] == ""
    assert calls["execute_async"] is False
    assert calls["spawned_run_id"] == "run_agent"
    assert "run_url: /runs/run_agent" in result.stdout


def test_agent_adapter_web_api_reports_status_and_mutates_implemented_hosts(service_factory, tmp_path: Path) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))
    workdir = tmp_path / "project"
    workdir.mkdir()

    status_response = client.get("/api/agent-adapters", params={"workdir": str(workdir)})
    assert status_response.status_code == 200
    payload = status_response.json()
    statuses = {item["adapter"]: item["status"] for item in payload["adapters"]}
    assert statuses == {
        "codex": "not_installed",
        "claude": "not_installed",
        "opencode": "not_installed",
    }

    install_response = client.post("/api/agent-adapters/codex/install", json={"workdir": str(workdir)})
    assert install_response.status_code == 200
    assert install_response.json()["status"] == "installed"
    assert (workdir / ".agents" / "skills" / "loopora-gen" / "SKILL.md").exists()

    uninstall_response = client.post("/api/agent-adapters/codex/uninstall", json={"workdir": str(workdir)})
    assert uninstall_response.status_code == 200
    assert uninstall_response.json()["status"] == "not_installed"
    assert not (workdir / ".agents" / "skills" / "loopora-gen" / "SKILL.md").exists()

    claude_install_response = client.post("/api/agent-adapters/claude/install", json={"workdir": str(workdir)})
    assert claude_install_response.status_code == 200
    assert claude_install_response.json()["status"] == "installed"
    assert (workdir / ".claude" / "skills" / "loopora-gen" / "SKILL.md").exists()

    opencode_install_response = client.post("/api/agent-adapters/opencode/install", json={"workdir": str(workdir)})
    assert opencode_install_response.status_code == 200
    assert opencode_install_response.json()["status"] == "installed"
    assert (workdir / ".opencode" / "commands" / "loopora-gen.md").exists()


def test_agent_adapter_web_api_reports_invalid_json(service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    invalid_json = client.post(
        "/api/agent-adapters/codex/install",
        content="{",
        headers={"content-type": "application/json"},
    )
    non_object = client.post("/api/agent-adapters/codex/uninstall", json=["not", "an", "object"])

    assert invalid_json.status_code == 400
    assert "invalid JSON body" in invalid_json.json()["error"]
    assert non_object.status_code == 400
    assert non_object.json()["error"] == "request body must be a JSON object"


def test_agent_web_health_check_requires_loopora_runtime_payload(monkeypatch) -> None:
    class FakeResponse:
        status = 200

        def __init__(self, body: bytes) -> None:
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _tb) -> None:
            return None

        def read(self) -> bytes:
            return self.body

    monkeypatch.setattr(agent_web, "urlopen", lambda *_args, **_kwargs: FakeResponse(b'{"hello": true}'))
    assert agent_web._loopora_web_responds("http://127.0.0.1:8742") is False

    monkeypatch.setattr(
        agent_web,
        "urlopen",
        lambda *_args, **_kwargs: FakeResponse(b'{"running_count": 0, "queued_count": 0, "runs": []}'),
    )
    assert agent_web._loopora_web_responds("http://127.0.0.1:8742") is True
