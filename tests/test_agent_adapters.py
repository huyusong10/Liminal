from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner
import yaml

from loopora import cli
import loopora.agent_web as agent_web
from loopora.executor_fake_payloads import alignment_bundle_yaml
from loopora.service_agent_adapters import AgentBundleCandidateRequest
from loopora.service_agent_native import AgentNativeStepSubmitRequest
from loopora.service_types import LooporaConflictError, LooporaError
from loopora.run_artifacts import RunArtifactLayout, read_jsonl
from loopora.web import build_app
from loopora.workflows import WorkflowError


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


def _alignment_bundle_yaml_with_gatekeeper_control(
    workdir: Path,
    *,
    after: str = "0s",
    signal: str = "gatekeeper_rejected",
    control_id: str = "gatekeeper_repair",
    trigger_window: int | None = None,
) -> str:
    payload = yaml.safe_load(alignment_bundle_yaml(str(workdir.resolve())))
    if trigger_window is not None:
        payload["loop"]["trigger_window"] = trigger_window
    payload["role_definitions"].append(
        {
            "key": "repair-guide",
            "name": "Repair Guide",
            "description": "Turns a rejected verdict into a narrow repair direction.",
            "archetype": "guide",
            "prompt_ref": "guide.md",
            "prompt_markdown": (
                "---\n"
                "version: 1\n"
                "archetype: guide\n"
                "---\n\n"
                "Read the rejected GateKeeper verdict and provide one narrow repair direction without changing the workspace."
            ),
            "posture_notes": "Prefer the smallest evidence-producing repair over broad re-planning.",
            "executor_kind": "codex",
            "executor_mode": "preset",
            "command_cli": "",
            "command_args_text": "",
            "model": "",
            "reasoning_effort": "",
        }
    )
    payload["workflow"]["roles"].append({"id": "repair_guide", "role_definition_key": "repair-guide"})
    payload["workflow"]["controls"] = [
        {
            "id": control_id,
            "when": {"signal": signal, "after": after},
            "call": {"role_id": "repair_guide"},
            "mode": "repair_guidance",
            "max_fires_per_run": 1,
        }
    ]
    return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)


def _alignment_bundle_yaml_with_peer_visible_parallel_review_inputs(workdir: Path) -> str:
    payload = yaml.safe_load(alignment_bundle_yaml(str(workdir.resolve())))
    for step in list(payload["workflow"]["steps"]):
        if str(step.get("parallel_group") or "").strip():
            step["inputs"] = {
                "handoffs_from": ["builder_step", "contract_inspection_step"],
                "evidence_query": {"archetypes": ["builder", "inspector"], "limit": 12},
                "iteration_memory": "summary_only",
            }
    return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)


def _claude_settings_has_loopora_session_hook(settings: dict) -> bool:
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return False
    session_start = hooks.get("SessionStart")
    if not isinstance(session_start, list):
        return False
    for group in session_start:
        if not isinstance(group, dict):
            continue
        handlers = group.get("hooks")
        if not isinstance(handlers, list):
            continue
        if any(
            isinstance(handler, dict)
            and str(handler.get("command") or "").strip() == 'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/loopora-session-context.py"'
            for handler in handlers
        ):
            return True
    return False


def _agent_native_step_output(step: dict) -> dict:
    step_id = str(step["step_id"])
    role = step.get("role") if isinstance(step.get("role"), dict) else {}
    archetype = str(role.get("archetype") or "")
    if archetype == "inspector" or "inspection" in step_id:
        return {
            "execution_summary": {"total_checks": 1, "passed": 1, "failed": 0, "errored": 0, "total_duration_ms": 1},
            "check_results": [
                {
                    "id": "agent_native_path",
                    "title": "Agent-native path",
                    "status": "passed",
                    "notes": "The host Agent submitted structured inspection evidence through Loopora Core.",
                }
            ],
            "dynamic_checks": [],
            "tester_observations": "The Agent-native adapter path produced structured inspection evidence.",
            "coverage_results": [],
        }
    if archetype == "gatekeeper" or "gatekeeper" in step_id:
        evidence_refs = [
            str(item)
            for item in list(step.get("known_evidence_ids") or [])
            if str(item).strip() and "gatekeeper" not in str(item)
        ]
        return {
            "passed": True,
            "decision_summary": "Agent-native adapter path passed with inspector evidence.",
            "feedback_to_builder": "",
            "blocking_issues": [],
            "metrics": [{"name": "quality_score", "value": 1.0, "threshold": 0.9, "passed": True}],
            "failed_check_ids": [],
            "priority_failures": [],
            "composite_score": 1.0,
            "evidence_refs": evidence_refs[-4:],
            "evidence_claims": ["The inspector evidence confirms the host Agent submitted a structured result."],
            "residual_risks": [],
            "coverage_results": [],
        }
    if archetype == "guide":
        return {
            "created_at_iter": int(step.get("iter") or 0),
            "mode": "repair_guidance",
            "consumed": False,
            "analysis": {
                "recommended_shift": "Add direct evidence for the rejected Done When target.",
                "risk_note": "GateKeeper rejected the current evidence set.",
            },
            "seed_question": "Which missing proof can Builder produce next?",
            "meta_note": "Agent-native workflow control fired.",
        }
    return {
        "attempted": "Prepared the workspace under the Loopora Agent-native capsule.",
        "abandoned": "",
        "assumption": "The unit test simulates host-native role execution without launching a nested Agent CLI.",
        "summary": "Builder produced a structured handoff for downstream inspection.",
        "changed_files": [],
        "proof_files": [],
        "proof_artifacts": [],
        "artifact_paths": [],
    }


def _agent_native_rejected_gatekeeper_output(step: dict) -> dict:
    output = _agent_native_step_output(step)
    output.update(
        {
            "passed": False,
            "decision_summary": "The task still lacks required evidence.",
            "feedback_to_builder": "Produce direct proof for the primary user flow.",
            "blocking_issues": ["missing_primary_flow_evidence"],
            "composite_score": 0.42,
            "metrics": [{"name": "quality_score", "value": 0.42, "threshold": 0.9, "passed": False}],
            "evidence_claims": [],
        }
    )
    return output


def _drive_agent_native_until_archetype(service, result: dict, *, adapter: str, workdir: Path, archetype: str) -> dict:
    while True:
        step = result["next_step"]
        if step["role"]["archetype"] == archetype:
            return result
        result = service.submit_agent_native_step(
            AgentNativeStepSubmitRequest(
                adapter=adapter,
                workdir=workdir,
                run_id=str(step["run_id"]),
                step_id=str(step["step_id"]),
                output=_agent_native_step_output(step),
                host_dispatch=_agent_native_host_dispatch(adapter, step),
                entry_source=f"{adapter}_project_skill" if adapter != "opencode" else "opencode_project_command",
            )
        )


def _agent_native_host_dispatch(adapter: str, step: dict) -> dict:
    role_dispatch = step.get("role_dispatch") if isinstance(step.get("role_dispatch"), dict) else {}
    target_agent = str(role_dispatch.get("target_agent") or "")
    return {
        "schema_version": 1,
        "adapter": adapter,
        "run_id": str(step["run_id"]),
        "step_id": str(step["step_id"]),
        "target_agent": target_agent,
        "actual_agent": target_agent,
        "dispatch_mode": "host_subagent",
        "inline": False,
        "attestation": "The test simulates host-native role agent dispatch without launching a nested Agent CLI.",
    }


def _drive_agent_native_run_to_success(service, *, adapter: str, started: dict, workdir: Path, context_id: str = "") -> dict:
    result = started
    seen_steps = []
    while not result.get("complete"):
        step = result.get("next_step")
        assert isinstance(step, dict)
        step_id = str(step["step_id"])
        role = step.get("role") if isinstance(step.get("role"), dict) else {}
        role_dispatch = step.get("role_dispatch") if isinstance(step.get("role_dispatch"), dict) else {}
        assert role_dispatch.get("required") is True
        assert role_dispatch.get("inline_allowed") is False
        assert role_dispatch.get("target_agent")
        if role.get("archetype") == "gatekeeper":
            evidence_rule_ids = {
                str(item.get("id"))
                for item in list(step.get("evidence_rules") or [])
                if isinstance(item, dict)
            }
            assert "evidence_refs.must_be_exact_known_ids" in evidence_rule_ids
            assert "gatekeeper.pass_requires_supporting_upstream_evidence" in evidence_rule_ids
            assert "gatekeeper.finish_coverage_is_core_derived" in evidence_rule_ids
            assert step.get("evidence_ref_contract", {}).get("unknown_ids_are_blocking") is True
        seen_steps.append(step_id)
        result = service.submit_agent_native_step(
            AgentNativeStepSubmitRequest(
                adapter=adapter,
                workdir=workdir,
                context_id=context_id,
                run_id=str(step["run_id"]),
                step_id=step_id,
                output=_agent_native_step_output(step),
                host_dispatch=_agent_native_host_dispatch(adapter, step),
                entry_source=f"{adapter}_project_skill" if adapter != "opencode" else "opencode_project_command",
            )
        )
    assert seen_steps[0] == "builder_step"
    assert any("gatekeeper" in item for item in seen_steps)
    assert result["run"]["status"] == "succeeded"
    return result


def _assert_claude_managed_install(workdir: Path, skill_paths: dict[str, Path]) -> tuple[Path, str]:
    gen_skill = skill_paths["gen"].read_text(encoding="utf-8")
    loop_skill = skill_paths["loop"].read_text(encoding="utf-8")
    settings = json.loads((workdir / ".claude" / "settings.json").read_text(encoding="utf-8"))
    gen_command = workdir / ".claude" / "commands" / "loopora-gen.md"
    loop_command = workdir / ".claude" / "commands" / "loopora-loop.md"
    session_hook = workdir / ".claude" / "hooks" / "loopora-session-context.py"
    builder_agent = workdir / ".claude" / "agents" / "loopora-builder.md"
    orchestrator_agent = workdir / ".claude" / "agents" / "loopora-orchestrator.md"
    assert "LOOPORA-MANAGED: claude-code-adapter" in gen_skill
    assert gen_command.exists()
    assert loop_command.exists()
    assert session_hook.exists()
    assert builder_agent.exists()
    assert orchestrator_agent.exists()
    assert "CLAUDE_SESSION_ID" in session_hook.read_text(encoding="utf-8")
    assert _claude_settings_has_loopora_session_hook(settings)
    assert "disable-model-invocation: true" in gen_skill
    assert "allowed-tools:" in gen_skill
    assert "LOOPORA_AGENT_ENTRY_SOURCE=claude_project_skill" in gen_skill
    assert 'loopora agent claude gen --workdir "$PWD"' in gen_skill
    assert '--context-id "${CLAUDE_SESSION_ID}"' in gen_skill
    assert "--entry-source claude_project_skill" in gen_skill
    assert "LOOPORA_AGENT_ENTRY_SOURCE=claude_project_skill" in loop_skill
    assert 'loopora agent claude loop --workdir "$PWD"' in loop_skill
    assert "loopora agent claude submit" in loop_skill
    assert "Task" in loop_skill
    assert "loopora_host_dispatch" in loop_skill
    assert "role_dispatch.target_agent" in loop_skill
    assert '--context-id "${CLAUDE_SESSION_ID}"' in loop_skill
    assert "--entry-source claude_project_skill" in loop_skill
    builder_agent_text = builder_agent.read_text(encoding="utf-8")
    orchestrator_agent_text = orchestrator_agent.read_text(encoding="utf-8")
    assert "Loopora Builder" in builder_agent_text
    assert "tools: Read, Glob, Grep, Bash, Write, Edit, MultiEdit" in builder_agent_text
    assert "Loopora Orchestrator" in orchestrator_agent_text
    assert "tools: Task, Read, Write, Bash" in orchestrator_agent_text
    manifest_path = workdir / ".loopora" / "adapters" / "claude" / "manifest.json"
    assert manifest_path.exists()
    first_manifest = manifest_path.read_text(encoding="utf-8")
    assert {item["path"] for item in json.loads(first_manifest)["managed_files"]} == {
        ".claude/commands/loopora-gen.md",
        ".claude/commands/loopora-loop.md",
        ".claude/skills/loopora-gen/SKILL.md",
        ".claude/skills/loopora-loop/SKILL.md",
        ".claude/hooks/loopora-session-context.py",
        ".claude/agents/loopora-builder.md",
        ".claude/agents/loopora-inspector.md",
        ".claude/agents/loopora-gatekeeper.md",
        ".claude/agents/loopora-guide.md",
        ".claude/agents/loopora-orchestrator.md",
    }
    return manifest_path, first_manifest


def _assert_opencode_managed_install(workdir: Path, command_paths: dict[str, Path]) -> tuple[Path, str]:
    gen_command = command_paths["gen"].read_text(encoding="utf-8")
    loop_command = command_paths["loop"].read_text(encoding="utf-8")
    builder_agent = workdir / ".opencode" / "agents" / "loopora-builder.md"
    orchestrator_agent = workdir / ".opencode" / "agents" / "loopora-orchestrator.md"
    assert "LOOPORA-MANAGED: opencode-adapter" in gen_command
    assert builder_agent.exists()
    assert orchestrator_agent.exists()
    assert "description:" in gen_command
    assert "agent: build" in gen_command
    assert "$ARGUMENTS" in gen_command
    assert "LOOPORA_AGENT_ENTRY_SOURCE=opencode_project_command" in gen_command
    assert 'loopora agent opencode gen --workdir "$PWD"' in gen_command
    assert '--context-id "${OPENCODE_SESSION_ID:-}"' in gen_command
    assert "--entry-source opencode_project_command" in gen_command
    assert "LOOPORA_AGENT_ENTRY_SOURCE=opencode_project_command" in loop_command
    assert "agent: loopora-orchestrator" in loop_command
    assert "subtask: true" in loop_command
    assert 'loopora agent opencode loop --workdir "$PWD"' in loop_command
    assert "loopora agent opencode submit" in loop_command
    assert "loopora_host_dispatch" in loop_command
    assert "role_dispatch.target_agent" in loop_command
    assert '--context-id "${OPENCODE_SESSION_ID:-}"' in loop_command
    assert "--entry-source opencode_project_command" in loop_command
    builder_agent_text = builder_agent.read_text(encoding="utf-8")
    orchestrator_agent_text = orchestrator_agent.read_text(encoding="utf-8")
    assert "Loopora Builder" in builder_agent_text
    assert "mode: subagent" in builder_agent_text
    assert "task: deny" in builder_agent_text
    assert "Loopora Orchestrator" in orchestrator_agent_text
    assert "mode: subagent" in orchestrator_agent_text
    assert "loopora-builder: allow" in orchestrator_agent_text
    manifest_path = workdir / ".loopora" / "adapters" / "opencode" / "manifest.json"
    assert manifest_path.exists()
    first_manifest = manifest_path.read_text(encoding="utf-8")
    assert {item["path"] for item in json.loads(first_manifest)["managed_files"]} == {
        ".opencode/commands/loopora-gen.md",
        ".opencode/commands/loopora-loop.md",
        ".opencode/agents/loopora-builder.md",
        ".opencode/agents/loopora-inspector.md",
        ".opencode/agents/loopora-gatekeeper.md",
        ".opencode/agents/loopora-guide.md",
        ".opencode/agents/loopora-orchestrator.md",
    }
    return manifest_path, first_manifest


def _assert_codex_managed_install(workdir: Path, skill_paths: dict[str, Path]) -> tuple[Path, str]:
    codex_builder_agent = workdir / ".codex" / "agents" / "loopora-builder.toml"
    codex_orchestrator_agent = workdir / ".codex" / "agents" / "loopora-orchestrator.toml"
    assert codex_builder_agent.exists()
    assert codex_orchestrator_agent.exists()
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
    assert "loopora agent codex submit" in loop_skill
    assert "loopora-builder" in loop_skill
    assert "loopora_host_dispatch" in loop_skill
    assert "role_dispatch.target_agent" in loop_skill
    assert "Codex native dispatch guidance" in loop_skill
    assert "omit `fork_context`" in loop_skill
    assert "bounded timeout" in loop_skill
    assert "--entry-source codex_project_skill" in loop_skill
    codex_builder_agent_text = codex_builder_agent.read_text(encoding="utf-8")
    assert "loopora-builder" in codex_builder_agent_text
    assert 'developer_instructions = """' in codex_builder_agent_text
    assert '\ninstructions = """' not in codex_builder_agent_text
    assert "Loopora Orchestrator" in codex_orchestrator_agent.read_text(encoding="utf-8")
    manifest_path = workdir / ".loopora" / "adapters" / "codex" / "manifest.json"
    assert manifest_path.exists()
    first_manifest = manifest_path.read_text(encoding="utf-8")
    manifest_payload = json.loads(first_manifest)
    assert {item["path"] for item in manifest_payload["managed_files"]} == {
        ".agents/skills/loopora-gen/SKILL.md",
        ".agents/skills/loopora-loop/SKILL.md",
        ".codex/agents/loopora-builder.toml",
        ".codex/agents/loopora-inspector.toml",
        ".codex/agents/loopora-gatekeeper.toml",
        ".codex/agents/loopora-guide.toml",
        ".codex/agents/loopora-orchestrator.toml",
    }
    assert all(len(item["sha256"]) == 64 for item in manifest_payload["managed_files"])
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
    manifest_path, first_manifest = _assert_codex_managed_install(workdir, skill_paths)

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
    assert (workdir / ".agents").exists()
    assert (workdir / ".codex").exists()
    assert (workdir / ".loopora").exists()
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
    claude_settings.parent.mkdir()
    claude_md.write_text("# User Claude instructions\n", encoding="utf-8")
    claude_settings.write_text('{"permissions": {"allow": []}}\n', encoding="utf-8")
    runner = CliRunner()

    first_install = runner.invoke(cli.app, ["init", "claude", "--workdir", str(workdir), "--json"])

    assert first_install.exit_code == 0, first_install.stdout
    assert json.loads(first_install.stdout)["status"] == "installed"
    skill_paths = _claude_skill_paths(workdir)
    assert skill_paths["gen"].exists()
    assert skill_paths["loop"].exists()
    manifest_path, first_manifest = _assert_claude_managed_install(workdir, skill_paths)
    assert claude_md.read_text(encoding="utf-8") == "# User Claude instructions\n"
    settings_after_install = json.loads(claude_settings.read_text(encoding="utf-8"))
    assert settings_after_install["permissions"] == {"allow": []}
    assert _claude_settings_has_loopora_session_hook(settings_after_install)

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
    assert not (workdir / ".claude" / "hooks" / "loopora-session-context.py").exists()
    assert claude_md.exists()
    assert claude_settings.exists()
    settings_after_uninstall = json.loads(claude_settings.read_text(encoding="utf-8"))
    assert settings_after_uninstall == {"permissions": {"allow": []}}


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


def test_agent_bundle_candidate_rejects_missing_workdir(service_factory, tmp_path: Path) -> None:
    service = service_factory(scenario="success")

    with pytest.raises(LooporaError, match="adapter project root does not exist"):
        service.create_agent_bundle_candidate(
            AgentBundleCandidateRequest(
                adapter="codex",
                workdir=tmp_path / "missing-project",
                message="Prepare a Loop for a project that is not present.",
                bundle_yaml=alignment_bundle_yaml(str(tmp_path / "missing-project")),
            )
        )


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


def test_claude_adapter_status_reports_needs_update_for_missing_managed_session_hook(service_factory, tmp_path: Path) -> None:
    service = service_factory(scenario="success")
    workdir = tmp_path / "project"
    workdir.mkdir()

    service.install_agent_adapter("claude", workdir=workdir)
    settings_path = workdir / ".claude" / "settings.json"
    settings_path.write_text(json.dumps({"permissions": {"allow": []}}) + "\n", encoding="utf-8")

    status = service.get_agent_adapter("claude", workdir=workdir)

    assert status["status"] == "needs_update"
    assert any(item["path"] == ".claude/settings.json#hooks.SessionStart.loopora" and item["state"] == "missing" for item in status["managed_files"])


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
    assert started["execution_plane"] == "agent_native"
    assert started["run"]["status"] == "awaiting_agent"
    assert started["next_step"]["step_id"] == "builder_step"
    assert started["session"]["status"] == "running_loop"
    assert [item["action"] for item in started["binding"]["entry_invocations"][-2:]] == ["gen", "loop"]
    assert {item["entry_source"] for item in started["binding"]["entry_invocations"][-2:]} == {"codex_project_skill"}
    final = _drive_agent_native_run_to_success(service, adapter="codex", started=started, workdir=sample_workdir)
    assert final["complete"] is True


def test_agent_native_parallel_group_peer_context_uses_group_start_snapshot(
    service_factory,
    tmp_path: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    bundle_file = tmp_path / "bundle.yml"
    bundle_file.write_text(_alignment_bundle_yaml_with_peer_visible_parallel_review_inputs(sample_workdir), encoding="utf-8")
    service.create_agent_bundle_candidate(
        AgentBundleCandidateRequest(
            adapter="codex",
            workdir=sample_workdir,
            message="Keep agent-native parallel reviewers isolated from peer outputs.",
            bundle_file=bundle_file,
            entry_source="codex_project_skill",
        )
    )
    result = service.start_agent_loop("codex", workdir=sample_workdir, entry_source="codex_project_skill", execute_async=False)
    builder_step = result["next_step"]
    result = service.submit_agent_native_step(
        AgentNativeStepSubmitRequest(
            adapter="codex",
            workdir=sample_workdir,
            run_id=str(builder_step["run_id"]),
            step_id=str(builder_step["step_id"]),
            output=_agent_native_step_output(builder_step),
            host_dispatch=_agent_native_host_dispatch("codex", builder_step),
            entry_source="codex_project_skill",
        )
    )

    first_peer_step = result["next_step"]
    assert first_peer_step["step_id"] == "contract_inspection_step"
    result = service.submit_agent_native_step(
        AgentNativeStepSubmitRequest(
            adapter="codex",
            workdir=sample_workdir,
            run_id=str(first_peer_step["run_id"]),
            step_id=str(first_peer_step["step_id"]),
            output=_agent_native_step_output(first_peer_step),
            host_dispatch=_agent_native_host_dispatch("codex", first_peer_step),
            entry_source="codex_project_skill",
        )
    )

    second_peer_step = result["next_step"]
    assert second_peer_step["step_id"] == "evidence_inspection_step"
    second_peer_context = json.loads(Path(second_peer_step["context_absolute_path"]).read_text(encoding="utf-8"))
    second_peer_handoff_steps = [item["source"]["step_id"] for item in second_peer_context["upstream"]["completed_steps_this_iteration"]]

    assert second_peer_handoff_steps == ["builder_step"]
    assert second_peer_context["evidence"]["known_ids"] == ["ev_000_00_builder_step"]
    assert second_peer_step["known_evidence_ids"] == ["ev_000_00_builder_step"]

    result = service.submit_agent_native_step(
        AgentNativeStepSubmitRequest(
            adapter="codex",
            workdir=sample_workdir,
            run_id=str(second_peer_step["run_id"]),
            step_id=str(second_peer_step["step_id"]),
            output=_agent_native_step_output(second_peer_step),
            host_dispatch=_agent_native_host_dispatch("codex", second_peer_step),
            entry_source="codex_project_skill",
        )
    )

    gatekeeper_step = result["next_step"]
    assert gatekeeper_step["step_id"] == "gatekeeper_step"
    gatekeeper_context = json.loads(Path(gatekeeper_step["context_absolute_path"]).read_text(encoding="utf-8"))
    gatekeeper_handoff_steps = [item["source"]["step_id"] for item in gatekeeper_context["upstream"]["completed_steps_this_iteration"]]

    assert gatekeeper_handoff_steps == ["contract_inspection_step", "evidence_inspection_step"]
    assert {
        "ev_000_01_contract_inspection_step",
        "ev_000_02_evidence_inspection_step",
    }.issubset(set(gatekeeper_context["evidence"]["known_ids"]))
    events = service.stream_events(str(gatekeeper_step["run_id"]), limit=200)
    assert any(
        event["event_type"] == "parallel_group_started"
        and event["payload"]["parallel_group"] == "inspection_pack"
        and event["payload"]["step_ids"] == ["contract_inspection_step", "evidence_inspection_step"]
        for event in events
    )
    assert any(
        event["event_type"] == "parallel_group_finished"
        and event["payload"]["parallel_group"] == "inspection_pack"
        and event["payload"]["step_ids"] == ["contract_inspection_step", "evidence_inspection_step"]
        for event in events
    )


def test_agent_native_submit_requires_matching_host_dispatch_proof(
    service_factory,
    tmp_path: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    bundle_file = tmp_path / "bundle.yml"
    bundle_file.write_text(alignment_bundle_yaml(str(sample_workdir.resolve())), encoding="utf-8")
    service.create_agent_bundle_candidate(
        AgentBundleCandidateRequest(
            adapter="codex",
            workdir=sample_workdir,
            message="Require native role dispatch proof.",
            bundle_file=bundle_file,
            entry_source="codex_project_skill",
        )
    )
    started = service.start_agent_loop("codex", workdir=sample_workdir, entry_source="codex_project_skill", execute_async=False)
    step = started["next_step"]
    raw_output_path = RunArtifactLayout(Path(started["run"]["runs_dir"])).step_output_raw_path(
        int(step["iter"]),
        int(step["step_order"]),
        str(step["step_id"]),
    )

    with pytest.raises(LooporaConflictError, match="loopora_host_dispatch"):
        service.submit_agent_native_step(
            AgentNativeStepSubmitRequest(
                adapter="codex",
                workdir=sample_workdir,
                run_id=str(step["run_id"]),
                step_id=str(step["step_id"]),
                output=_agent_native_step_output(step),
                entry_source="codex_project_skill",
            )
        )
    assert not raw_output_path.exists()

    for field in ("adapter", "run_id", "step_id"):
        incomplete_dispatch = _agent_native_host_dispatch("codex", step)
        incomplete_dispatch.pop(field)
        with pytest.raises(LooporaConflictError, match=rf"{field} is required"):
            service.submit_agent_native_step(
                AgentNativeStepSubmitRequest(
                    adapter="codex",
                    workdir=sample_workdir,
                    run_id=str(step["run_id"]),
                    step_id=str(step["step_id"]),
                    output=_agent_native_step_output(step),
                    host_dispatch=incomplete_dispatch,
                    entry_source="codex_project_skill",
                )
            )
        assert not raw_output_path.exists()

    bad_dispatch = _agent_native_host_dispatch("codex", step)
    bad_dispatch["actual_agent"] = "loopora-gatekeeper"
    with pytest.raises(LooporaConflictError, match="expected loopora-builder"):
        service.submit_agent_native_step(
            AgentNativeStepSubmitRequest(
                adapter="codex",
                workdir=sample_workdir,
                run_id=str(step["run_id"]),
                step_id=str(step["step_id"]),
                output=_agent_native_step_output(step),
                host_dispatch=bad_dispatch,
                entry_source="codex_project_skill",
            )
        )
    assert not raw_output_path.exists()


def test_agent_native_host_dispatch_requires_literal_role_dispatch_booleans(service_factory) -> None:
    service = service_factory(scenario="success")
    context = {
        "adapter": "codex",
        "run": {"id": "run_agent"},
        "step_id": "builder_step",
        "role": {"archetype": "builder"},
        "active": {
            "capsule": {
                "role_dispatch": {
                    "required": "true",
                    "target_agent": "loopora-builder",
                    "inline_allowed": False,
                    "accepted_dispatch_modes": ["host_subagent"],
                }
            }
        },
    }

    with pytest.raises(LooporaConflictError, match="required must be literal true"):
        service._validate_agent_native_host_dispatch(context, None)

    context["active"]["capsule"]["role_dispatch"] = {
        "required": True,
        "target_agent": "loopora-builder",
        "inline_allowed": "false",
        "accepted_dispatch_modes": ["host_subagent"],
    }
    with pytest.raises(LooporaConflictError, match="inline_allowed must be a literal boolean"):
        service._validate_agent_native_host_dispatch(
            context,
            {
                "schema_version": 1,
                "adapter": "codex",
                "run_id": "run_agent",
                "step_id": "builder_step",
                "target_agent": "loopora-builder",
                "actual_agent": "loopora-builder",
                "dispatch_mode": "host_subagent",
                "inline": False,
            },
        )

    context["active"]["capsule"]["role_dispatch"] = {
        "required": True,
        "target_agent": "loopora-builder",
        "inline_allowed": False,
        "accepted_dispatch_modes": ["host_subagent"],
    }
    missing_inline_dispatch = {
        "schema_version": 1,
        "adapter": "codex",
        "run_id": "run_agent",
        "step_id": "builder_step",
        "target_agent": "loopora-builder",
        "actual_agent": "loopora-builder",
        "dispatch_mode": "host_subagent",
    }
    with pytest.raises(LooporaConflictError, match="inline must be a literal boolean"):
        service._validate_agent_native_host_dispatch(context, missing_inline_dispatch)

    string_inline_dispatch = {**missing_inline_dispatch, "inline": "false"}
    with pytest.raises(LooporaConflictError, match="inline must be a literal boolean"):
        service._validate_agent_native_host_dispatch(context, string_inline_dispatch)

    with pytest.raises(LooporaConflictError, match="cannot claim inline"):
        service._validate_agent_native_host_dispatch(
            context,
            {
                "schema_version": 1,
                "adapter": "codex",
                "run_id": "run_agent",
                "step_id": "builder_step",
                "target_agent": "loopora-builder",
                "actual_agent": "loopora-builder",
                "dispatch_mode": "host_subagent",
                "inline": True,
            },
        )

    with pytest.raises(LooporaConflictError, match="schema_version must be an integer"):
        service._validate_agent_native_host_dispatch(
            context,
            {
                "schema_version": "latest",
                "adapter": "codex",
                "run_id": "run_agent",
                "step_id": "builder_step",
                "target_agent": "loopora-builder",
                "actual_agent": "loopora-builder",
                "dispatch_mode": "host_subagent",
                "inline": False,
            },
        )

    for schema_version in (True, 1.5):
        dispatch = {
            "schema_version": schema_version,
            "adapter": "codex",
            "run_id": "run_agent",
            "step_id": "builder_step",
            "target_agent": "loopora-builder",
            "actual_agent": "loopora-builder",
            "dispatch_mode": "host_subagent",
            "inline": False,
        }
        with pytest.raises(LooporaConflictError, match="schema_version must be an integer"):
            service._validate_agent_native_host_dispatch(context, dispatch)


def test_agent_native_gatekeeper_blocks_unknown_coverage_result_refs(
    service_factory,
    tmp_path: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    bundle_file = tmp_path / "bundle.yml"
    bundle_file.write_text(alignment_bundle_yaml(str(sample_workdir.resolve())), encoding="utf-8")
    service.create_agent_bundle_candidate(
        AgentBundleCandidateRequest(
            adapter="codex",
            workdir=sample_workdir,
            message="Require coverage target evidence refs to stay inside the known evidence set.",
            bundle_file=bundle_file,
            entry_source="codex_project_skill",
        )
    )
    result = service.start_agent_loop("codex", workdir=sample_workdir, entry_source="codex_project_skill", execute_async=False)
    result = _drive_agent_native_until_archetype(service, result, adapter="codex", workdir=sample_workdir, archetype="gatekeeper")
    step = result["next_step"]

    gatekeeper_output = _agent_native_step_output(step)
    gatekeeper_output["coverage_results"] = [
        {
            "target_id": "fake_done.risk_001",
            "status": "covered",
            "evidence_refs": ["invented_ev"],
            "note": "This target-level evidence ref is not from known_evidence_ids.",
        }
    ]
    result = service.submit_agent_native_step(
        AgentNativeStepSubmitRequest(
            adapter="codex",
            workdir=sample_workdir,
            run_id=str(step["run_id"]),
            step_id=str(step["step_id"]),
            output=gatekeeper_output,
            host_dispatch=_agent_native_host_dispatch("codex", step),
            entry_source="codex_project_skill",
        )
    )

    assert result["complete"] is False
    assert result["next_step"]["step_id"] == "builder_step"
    layout = RunArtifactLayout(Path(result["run"]["runs_dir"]))
    normalized_gatekeeper_output = json.loads(
        layout.step_output_normalized_path(int(step["iter"]), int(step["step_order"]), str(step["step_id"])).read_text(encoding="utf-8")
    )
    assert normalized_gatekeeper_output["passed"] is False
    assert normalized_gatekeeper_output["blocking_issues"] == ["gatekeeper_coverage_evidence_refs_unknown: invented_ev"]


def test_agent_native_rejects_non_gatekeeper_unknown_coverage_result_refs(
    service_factory,
    tmp_path: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    bundle_file = tmp_path / "bundle.yml"
    bundle_file.write_text(alignment_bundle_yaml(str(sample_workdir.resolve())), encoding="utf-8")
    service.create_agent_bundle_candidate(
        AgentBundleCandidateRequest(
            adapter="codex",
            workdir=sample_workdir,
            message="Reject invented evidence refs before non-GateKeeper output enters the ledger.",
            bundle_file=bundle_file,
            entry_source="codex_project_skill",
        )
    )
    result = service.start_agent_loop("codex", workdir=sample_workdir, entry_source="codex_project_skill", execute_async=False)
    result = _drive_agent_native_until_archetype(service, result, adapter="codex", workdir=sample_workdir, archetype="inspector")
    step = result["next_step"]

    inspector_output = _agent_native_step_output(step)
    inspector_output["coverage_results"] = [
        {
            "target_id": "fake_done.risk_001",
            "status": "covered",
            "evidence_refs": ["invented_ev"],
            "note": "The ref is not copied from known_evidence_ids.",
        }
    ]
    with pytest.raises(LooporaError, match="agent-native evidence_refs_unknown: invented_ev"):
        service.submit_agent_native_step(
            AgentNativeStepSubmitRequest(
                adapter="codex",
                workdir=sample_workdir,
                run_id=str(step["run_id"]),
                step_id=str(step["step_id"]),
                output=inspector_output,
                host_dispatch=_agent_native_host_dispatch("codex", step),
                entry_source="codex_project_skill",
            )
        )

    layout = RunArtifactLayout(Path(result["run"]["runs_dir"]))
    assert not layout.step_output_raw_path(int(step["iter"]), int(step["step_order"]), str(step["step_id"])).exists()
    ledger = read_jsonl(layout.evidence_ledger_path)
    assert not any(item.get("step_id") == step["step_id"] for item in ledger)


def test_agent_native_gatekeeper_pass_with_missing_required_coverage_keeps_task_verdict_insufficient(
    service_factory,
    tmp_path: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    bundle_file = tmp_path / "bundle.yml"
    bundle_file.write_text(alignment_bundle_yaml(str(sample_workdir.resolve())), encoding="utf-8")
    service.create_agent_bundle_candidate(
        AgentBundleCandidateRequest(
            adapter="codex",
            workdir=sample_workdir,
            message="Keep agent-native lifecycle success separate from evidence-backed task proof.",
            bundle_file=bundle_file,
            entry_source="codex_project_skill",
        )
    )
    started = service.start_agent_loop("codex", workdir=sample_workdir, entry_source="codex_project_skill", execute_async=False)

    final = _drive_agent_native_run_to_success(service, adapter="codex", started=started, workdir=sample_workdir)

    run = final["run"]
    task_verdict = run["task_verdict"]
    assert run["status"] == "succeeded"
    assert run["last_verdict_json"]["passed"] is True
    assert task_verdict["status"] == "insufficient_evidence"
    assert task_verdict["source"] == "gatekeeper"
    assert "Required coverage" in task_verdict["summary"]
    assert json.loads((Path(run["runs_dir"]) / "evidence" / "task_verdict.json").read_text(encoding="utf-8")) == task_verdict


def test_agent_native_gatekeeper_rejection_claims_workflow_control(
    service_factory,
    tmp_path: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    bundle_file = tmp_path / "bundle.yml"
    bundle_file.write_text(_alignment_bundle_yaml_with_gatekeeper_control(sample_workdir), encoding="utf-8")
    service.create_agent_bundle_candidate(
        AgentBundleCandidateRequest(
            adapter="codex",
            workdir=sample_workdir,
            message="Run a GateKeeper rejection control in the host Agent plane.",
            bundle_file=bundle_file,
            entry_source="codex_project_skill",
        )
    )
    result = service.start_agent_loop("codex", workdir=sample_workdir, entry_source="codex_project_skill", execute_async=False)
    result = _drive_agent_native_until_archetype(service, result, adapter="codex", workdir=sample_workdir, archetype="gatekeeper")
    step = result["next_step"]
    gatekeeper_output = _agent_native_rejected_gatekeeper_output(step)
    result = service.submit_agent_native_step(
        AgentNativeStepSubmitRequest(
            adapter="codex",
            workdir=sample_workdir,
            run_id=str(step["run_id"]),
            step_id=str(step["step_id"]),
            output=gatekeeper_output,
            host_dispatch=_agent_native_host_dispatch("codex", step),
            entry_source="codex_project_skill",
        )
    )

    control_step = result["next_step"]
    assert result["complete"] is False
    assert control_step["step_id"] == "control__gatekeeper_repair"
    assert control_step["role"]["archetype"] == "guide"
    assert control_step["role_dispatch"]["target_agent"] == "loopora-guide"

    result = service.submit_agent_native_step(
        AgentNativeStepSubmitRequest(
            adapter="codex",
            workdir=sample_workdir,
            run_id=str(control_step["run_id"]),
            step_id=str(control_step["step_id"]),
            output=_agent_native_step_output(control_step),
            host_dispatch=_agent_native_host_dispatch("codex", control_step),
            entry_source="codex_project_skill",
        )
    )

    assert result["complete"] is False
    assert result["next_step"]["step_id"] == "builder_step"
    run_id = str(result["run"]["id"])
    run_dir = Path(result["run"]["runs_dir"])
    events = service.stream_events(run_id, limit=300)
    evidence_ledger = read_jsonl(run_dir / "evidence" / "ledger.jsonl")

    assert not any(event["event_type"] == "agent_native_controls_deferred" for event in events)
    assert any(
        event["event_type"] == "control_triggered"
        and event["payload"]["signal"] == "gatekeeper_rejected"
        and event["payload"]["control_id"] == "gatekeeper_repair"
        for event in events
    )
    assert any(
        event["event_type"] == "control_completed"
        and event["payload"]["signal"] == "gatekeeper_rejected"
        and event["payload"]["evidence_refs"]
        for event in events
    )
    assert any(entry["evidence_kind"] == "control" and "control:gatekeeper_rejected" in entry["verifies"] for entry in evidence_ledger)


def test_agent_native_submit_revalidates_persisted_workflow_controls(
    service_factory,
    tmp_path: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    bundle_file = tmp_path / "bundle.yml"
    bundle_file.write_text(_alignment_bundle_yaml_with_gatekeeper_control(sample_workdir), encoding="utf-8")
    service.create_agent_bundle_candidate(
        AgentBundleCandidateRequest(
            adapter="codex",
            workdir=sample_workdir,
            message="Reject corrupted persisted workflow controls before accepting an Agent-native step result.",
            bundle_file=bundle_file,
            entry_source="codex_project_skill",
        )
    )
    started = service.start_agent_loop("codex", workdir=sample_workdir, entry_source="codex_project_skill", execute_async=False)
    step = started["next_step"]
    corrupted_workflow = json.loads(json.dumps(started["run"]["workflow_json"]))
    corrupted_workflow["controls"][0]["max_fires_per_run"] = 0
    with service.repository.transaction() as connection:
        connection.execute(
            "UPDATE loop_runs SET workflow_json = ? WHERE id = ?",
            (json.dumps(corrupted_workflow, ensure_ascii=False), started["run"]["id"]),
        )

    with pytest.raises(WorkflowError, match="max_fires_per_run"):
        service.submit_agent_native_step(
            AgentNativeStepSubmitRequest(
                adapter="codex",
                workdir=sample_workdir,
                run_id=str(step["run_id"]),
                step_id=str(step["step_id"]),
                output=_agent_native_step_output(step),
                host_dispatch=_agent_native_host_dispatch("codex", step),
                entry_source="codex_project_skill",
            )
        )

    events = service.stream_events(str(started["run"]["id"]), limit=100)
    assert not any(event["event_type"] == "agent_native_step_submitted" for event in events)


def test_agent_native_submit_revalidates_persisted_workflow_inputs(
    service_factory,
    tmp_path: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    bundle_file = tmp_path / "bundle.yml"
    bundle_file.write_text(alignment_bundle_yaml(str(sample_workdir.resolve())), encoding="utf-8")
    service.create_agent_bundle_candidate(
        AgentBundleCandidateRequest(
            adapter="codex",
            workdir=sample_workdir,
            message="Reject corrupted persisted workflow inputs before accepting an Agent-native step result.",
            bundle_file=bundle_file,
            entry_source="codex_project_skill",
        )
    )
    started = service.start_agent_loop("codex", workdir=sample_workdir, entry_source="codex_project_skill", execute_async=False)
    step = started["next_step"]
    raw_output_path = RunArtifactLayout(Path(started["run"]["runs_dir"])).step_output_raw_path(
        int(step["iter"]),
        int(step["step_order"]),
        str(step["step_id"]),
    )
    corrupted_workflow = json.loads(json.dumps(started["run"]["workflow_json"]))
    corrupted_workflow["steps"][1]["inputs"]["evidence_query"]["archetypes"].append(False)
    with service.repository.transaction() as connection:
        connection.execute(
            "UPDATE loop_runs SET workflow_json = ? WHERE id = ?",
            (json.dumps(corrupted_workflow, ensure_ascii=False), started["run"]["id"]),
        )

    with pytest.raises(WorkflowError, match="must contain only strings"):
        service.submit_agent_native_step(
            AgentNativeStepSubmitRequest(
                adapter="codex",
                workdir=sample_workdir,
                run_id=str(step["run_id"]),
                step_id=str(step["step_id"]),
                output=_agent_native_step_output(step),
                host_dispatch=_agent_native_host_dispatch("codex", step),
                entry_source="codex_project_skill",
            )
        )
    assert not raw_output_path.exists()


def test_agent_native_workflow_control_skip_records_after_not_elapsed_event(
    service_factory,
    tmp_path: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    bundle_file = tmp_path / "bundle.yml"
    bundle_file.write_text(_alignment_bundle_yaml_with_gatekeeper_control(sample_workdir, after="1h"), encoding="utf-8")
    service.create_agent_bundle_candidate(
        AgentBundleCandidateRequest(
            adapter="codex",
            workdir=sample_workdir,
            message="Skip an agent-native GateKeeper rejection control before its after window elapses.",
            bundle_file=bundle_file,
            entry_source="codex_project_skill",
        )
    )
    result = service.start_agent_loop("codex", workdir=sample_workdir, entry_source="codex_project_skill", execute_async=False)
    result = _drive_agent_native_until_archetype(service, result, adapter="codex", workdir=sample_workdir, archetype="gatekeeper")
    step = result["next_step"]

    result = service.submit_agent_native_step(
        AgentNativeStepSubmitRequest(
            adapter="codex",
            workdir=sample_workdir,
            run_id=str(step["run_id"]),
            step_id=str(step["step_id"]),
            output=_agent_native_rejected_gatekeeper_output(step),
            host_dispatch=_agent_native_host_dispatch("codex", step),
            entry_source="codex_project_skill",
        )
    )

    assert result["complete"] is False
    assert result["next_step"]["step_id"] == "builder_step"
    events = service.stream_events(str(result["run"]["id"]), limit=300)

    assert not any(event["event_type"] == "agent_native_controls_deferred" for event in events)
    assert not any(event["event_type"] == "control_triggered" for event in events)
    assert not any(event["event_type"] == "control_completed" for event in events)
    assert any(
        event["event_type"] == "control_skipped"
        and event["payload"]["signal"] == "gatekeeper_rejected"
        and event["payload"]["control_id"] == "gatekeeper_repair"
        and event["payload"]["skip_reason"] == "after_not_elapsed"
        for event in events
    )


def test_agent_native_workflow_control_respects_fire_limit_across_iterations(
    service_factory,
    tmp_path: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    bundle_file = tmp_path / "bundle.yml"
    bundle_file.write_text(_alignment_bundle_yaml_with_gatekeeper_control(sample_workdir), encoding="utf-8")
    service.create_agent_bundle_candidate(
        AgentBundleCandidateRequest(
            adapter="codex",
            workdir=sample_workdir,
            message="Enforce an agent-native workflow control fire limit across iterations.",
            bundle_file=bundle_file,
            entry_source="codex_project_skill",
        )
    )
    result = service.start_agent_loop("codex", workdir=sample_workdir, entry_source="codex_project_skill", execute_async=False)
    result = _drive_agent_native_until_archetype(service, result, adapter="codex", workdir=sample_workdir, archetype="gatekeeper")
    first_gatekeeper_step = result["next_step"]
    result = service.submit_agent_native_step(
        AgentNativeStepSubmitRequest(
            adapter="codex",
            workdir=sample_workdir,
            run_id=str(first_gatekeeper_step["run_id"]),
            step_id=str(first_gatekeeper_step["step_id"]),
            output=_agent_native_rejected_gatekeeper_output(first_gatekeeper_step),
            host_dispatch=_agent_native_host_dispatch("codex", first_gatekeeper_step),
            entry_source="codex_project_skill",
        )
    )

    first_control_step = result["next_step"]
    result = service.submit_agent_native_step(
        AgentNativeStepSubmitRequest(
            adapter="codex",
            workdir=sample_workdir,
            run_id=str(first_control_step["run_id"]),
            step_id=str(first_control_step["step_id"]),
            output=_agent_native_step_output(first_control_step),
            host_dispatch=_agent_native_host_dispatch("codex", first_control_step),
            entry_source="codex_project_skill",
        )
    )

    assert result["next_step"]["step_id"] == "builder_step"
    result = _drive_agent_native_until_archetype(service, result, adapter="codex", workdir=sample_workdir, archetype="gatekeeper")
    second_gatekeeper_step = result["next_step"]
    result = service.submit_agent_native_step(
        AgentNativeStepSubmitRequest(
            adapter="codex",
            workdir=sample_workdir,
            run_id=str(second_gatekeeper_step["run_id"]),
            step_id=str(second_gatekeeper_step["step_id"]),
            output=_agent_native_rejected_gatekeeper_output(second_gatekeeper_step),
            host_dispatch=_agent_native_host_dispatch("codex", second_gatekeeper_step),
            entry_source="codex_project_skill",
        )
    )

    assert result["complete"] is False
    assert result["next_step"]["step_id"] == "builder_step"
    run_id = str(result["run"]["id"])
    run_dir = Path(result["run"]["runs_dir"])
    events = service.stream_events(run_id, limit=500)
    evidence_ledger = read_jsonl(run_dir / "evidence" / "ledger.jsonl")

    assert [event["event_type"] for event in events].count("control_triggered") == 1
    assert [event["event_type"] for event in events].count("control_completed") == 1
    assert any(
        event["event_type"] == "control_skipped"
        and event["payload"]["signal"] == "gatekeeper_rejected"
        and event["payload"]["control_id"] == "gatekeeper_repair"
        and event["payload"]["skip_reason"] == "max_fires_per_run"
        for event in events
    )
    control_entries = [entry for entry in evidence_ledger if entry["evidence_kind"] == "control"]
    assert len(control_entries) == 1
    assert "control:gatekeeper_rejected" in control_entries[0]["verifies"]


def test_agent_native_malformed_control_fire_count_fails_closed(
    service_factory,
    tmp_path: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    bundle_file = tmp_path / "bundle.yml"
    bundle_file.write_text(_alignment_bundle_yaml_with_gatekeeper_control(sample_workdir), encoding="utf-8")
    service.create_agent_bundle_candidate(
        AgentBundleCandidateRequest(
            adapter="codex",
            workdir=sample_workdir,
            message="Treat malformed local control fire counts as already exhausted.",
            bundle_file=bundle_file,
            entry_source="codex_project_skill",
        )
    )
    result = service.start_agent_loop("codex", workdir=sample_workdir, entry_source="codex_project_skill", execute_async=False)
    result = _drive_agent_native_until_archetype(service, result, adapter="codex", workdir=sample_workdir, archetype="gatekeeper")
    first_gatekeeper_step = result["next_step"]
    result = service.submit_agent_native_step(
        AgentNativeStepSubmitRequest(
            adapter="codex",
            workdir=sample_workdir,
            run_id=str(first_gatekeeper_step["run_id"]),
            step_id=str(first_gatekeeper_step["step_id"]),
            output=_agent_native_rejected_gatekeeper_output(first_gatekeeper_step),
            host_dispatch=_agent_native_host_dispatch("codex", first_gatekeeper_step),
            entry_source="codex_project_skill",
        )
    )
    first_control_step = result["next_step"]
    result = service.submit_agent_native_step(
        AgentNativeStepSubmitRequest(
            adapter="codex",
            workdir=sample_workdir,
            run_id=str(first_control_step["run_id"]),
            step_id=str(first_control_step["step_id"]),
            output=_agent_native_step_output(first_control_step),
            host_dispatch=_agent_native_host_dispatch("codex", first_control_step),
            entry_source="codex_project_skill",
        )
    )

    state_path = Path(result["run"]["runs_dir"]) / "agent_native" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["control_fire_counts"]["gatekeeper_repair"] = "1"
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    result = _drive_agent_native_until_archetype(service, result, adapter="codex", workdir=sample_workdir, archetype="gatekeeper")
    second_gatekeeper_step = result["next_step"]
    result = service.submit_agent_native_step(
        AgentNativeStepSubmitRequest(
            adapter="codex",
            workdir=sample_workdir,
            run_id=str(second_gatekeeper_step["run_id"]),
            step_id=str(second_gatekeeper_step["step_id"]),
            output=_agent_native_rejected_gatekeeper_output(second_gatekeeper_step),
            host_dispatch=_agent_native_host_dispatch("codex", second_gatekeeper_step),
            entry_source="codex_project_skill",
        )
    )

    events = service.stream_events(str(result["run"]["id"]), limit=500)

    assert result["complete"] is False
    assert result["next_step"]["step_id"] == "builder_step"
    assert [event["event_type"] for event in events].count("control_triggered") == 1
    assert any(
        event["event_type"] == "control_skipped"
        and event["payload"]["control_id"] == "gatekeeper_repair"
        and event["payload"]["skip_reason"] == "max_fires_per_run"
        for event in events
    )


def test_agent_native_no_evidence_progress_control_claims_stalled_context(
    service_factory,
    tmp_path: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    bundle_file = tmp_path / "bundle.yml"
    bundle_file.write_text(
        _alignment_bundle_yaml_with_gatekeeper_control(
            sample_workdir,
            signal="no_evidence_progress",
            control_id="coverage_stall_guidance",
            trigger_window=1,
        ),
        encoding="utf-8",
    )
    service.create_agent_bundle_candidate(
        AgentBundleCandidateRequest(
            adapter="codex",
            workdir=sample_workdir,
            message="Surface stalled required evidence coverage in the host Agent plane.",
            bundle_file=bundle_file,
            entry_source="codex_project_skill",
        )
    )
    result = service.start_agent_loop("codex", workdir=sample_workdir, entry_source="codex_project_skill", execute_async=False)

    result = _drive_agent_native_until_archetype(service, result, adapter="codex", workdir=sample_workdir, archetype="gatekeeper")
    first_gatekeeper_step = result["next_step"]
    result = service.submit_agent_native_step(
        AgentNativeStepSubmitRequest(
            adapter="codex",
            workdir=sample_workdir,
            run_id=str(first_gatekeeper_step["run_id"]),
            step_id=str(first_gatekeeper_step["step_id"]),
            output=_agent_native_rejected_gatekeeper_output(first_gatekeeper_step),
            host_dispatch=_agent_native_host_dispatch("codex", first_gatekeeper_step),
            entry_source="codex_project_skill",
        )
    )
    assert result["next_step"]["step_id"] == "builder_step"

    result = _drive_agent_native_until_archetype(service, result, adapter="codex", workdir=sample_workdir, archetype="gatekeeper")
    second_gatekeeper_step = result["next_step"]
    result = service.submit_agent_native_step(
        AgentNativeStepSubmitRequest(
            adapter="codex",
            workdir=sample_workdir,
            run_id=str(second_gatekeeper_step["run_id"]),
            step_id=str(second_gatekeeper_step["step_id"]),
            output=_agent_native_rejected_gatekeeper_output(second_gatekeeper_step),
            host_dispatch=_agent_native_host_dispatch("codex", second_gatekeeper_step),
            entry_source="codex_project_skill",
        )
    )

    control_step = result["next_step"]
    assert control_step["step_id"] == "control__coverage_stall_guidance"
    assert control_step["role"]["archetype"] == "guide"
    control_context = json.loads(Path(control_step["context_absolute_path"]).read_text(encoding="utf-8"))
    assert control_context["iteration"]["evidence_progress_mode"] == "stalled"
    assert control_context["iteration"]["covered_check_count"] == 0
    assert control_context["iteration"]["missing_check_count"] == 2
    assert control_context["iteration"]["consecutive_no_required_coverage_delta"] == 1
    assert control_context["current_step"]["control"]["signal"] == "no_evidence_progress"

    result = service.submit_agent_native_step(
        AgentNativeStepSubmitRequest(
            adapter="codex",
            workdir=sample_workdir,
            run_id=str(control_step["run_id"]),
            step_id=str(control_step["step_id"]),
            output=_agent_native_step_output(control_step),
            host_dispatch=_agent_native_host_dispatch("codex", control_step),
            entry_source="codex_project_skill",
        )
    )

    assert result["complete"] is False
    assert result["next_step"]["step_id"] == "builder_step"
    run_id = str(result["run"]["id"])
    run_dir = Path(result["run"]["runs_dir"])
    events = service.stream_events(run_id, limit=500)
    evidence_ledger = read_jsonl(run_dir / "evidence" / "ledger.jsonl")

    assert any(
        event["event_type"] == "control_triggered"
        and event["payload"]["signal"] == "no_evidence_progress"
        and "Required coverage did not improve" in event["payload"]["reason"]
        for event in events
    )
    assert any(entry["evidence_kind"] == "control" and "control:no_evidence_progress" in entry["verifies"] for entry in evidence_ledger)


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
    assert started["execution_plane"] == "agent_native"
    assert started["run"]["status"] == "awaiting_agent"
    assert started["next_step"]["step_id"] == "builder_step"
    assert [item["action"] for item in started["binding"]["entry_invocations"][-2:]] == ["gen", "loop"]
    assert {item["entry_source"] for item in started["binding"]["entry_invocations"][-2:]} == {"claude_project_skill"}
    final = _drive_agent_native_run_to_success(
        service,
        adapter="claude",
        started=started,
        workdir=sample_workdir,
        context_id="claude-session-a",
    )
    assert final["complete"] is True


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
    assert started["execution_plane"] == "agent_native"
    assert started["run"]["status"] == "awaiting_agent"
    assert started["next_step"]["step_id"] == "builder_step"
    assert [item["action"] for item in started["binding"]["entry_invocations"][-2:]] == ["gen", "loop"]
    assert {item["entry_source"] for item in started["binding"]["entry_invocations"][-2:]} == {"opencode_project_command"}
    final = _drive_agent_native_run_to_success(service, adapter="opencode", started=started, workdir=sample_workdir)
    assert final["complete"] is True


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
    assert started["execution_plane"] == "agent_native"
    assert started["run"]["status"] == "awaiting_agent"


@pytest.mark.parametrize("adapter", ["codex", "claude", "opencode"])
def test_cli_agent_loop_does_not_spawn_nested_worker_for_agent_native(adapter: str, monkeypatch, tmp_path: Path) -> None:
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
                "execution_plane": "agent_native",
                "run": {
                    "id": "run_agent",
                    "status": "awaiting_agent",
                    "runs_dir": str(run_dir),
                    "workdir": str(workdir),
                },
                "run_path": "/runs/run_agent",
                "started_new_run": True,
                "next_step": {"step_id": "builder_step", "role": {"name": "Builder"}},
            }

    monkeypatch.setattr(cli, "create_service", FakeService)

    def fake_spawn_background_worker(_service, run: dict) -> dict:
        raise AssertionError(f"agent-native loop must not spawn a nested worker for {run['id']}")

    monkeypatch.setattr(cli, "_spawn_background_worker", fake_spawn_background_worker)
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        ["agent", adapter, "loop", "--workdir", str(workdir), "--context-id", "thread-1", "--no-web"],
    )

    assert result.exit_code == 0, result.stdout
    assert calls["adapter"] == adapter
    assert calls["workdir"] == workdir
    assert calls["context_id"] == "thread-1"
    assert calls["entry_source"] == ""
    assert calls["execute_async"] is False
    assert "run_url: /runs/run_agent" in result.stdout
    assert "next_step_id: builder_step" in result.stdout


def test_cli_agent_submit_prints_terminal_task_verdict(monkeypatch, tmp_path: Path) -> None:
    workdir = tmp_path / "project"
    workdir.mkdir()
    result_file = tmp_path / "result.json"
    result_file.write_text(
        json.dumps(
            {
                "loopora_host_dispatch": {
                    "adapter": "codex",
                    "run_id": "run_terminal",
                    "step_id": "gatekeeper_step",
                    "target_agent": "loopora-gatekeeper",
                    "actual_agent": "loopora-gatekeeper",
                    "dispatch_mode": "host_subagent",
                    "inline": False,
                },
                "result": {"passed": True},
            }
        ),
        encoding="utf-8",
    )

    class FakeService:
        def submit_agent_native_step(self, _request: AgentNativeStepSubmitRequest):
            return {
                "run": {
                    "id": "run_terminal",
                    "status": "succeeded",
                    "run_status": "succeeded",
                    "task_verdict": {
                        "status": "insufficient_evidence",
                        "source": "gatekeeper",
                        "summary": "Required coverage still lacks direct evidence.",
                    },
                },
                "run_path": "/runs/run_terminal",
                "next_step": None,
                "complete": True,
            }

    monkeypatch.setattr(cli, "create_service", FakeService)
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        [
            "agent",
            "codex",
            "submit",
            "--workdir",
            str(workdir),
            "--run-id",
            "run_terminal",
            "--step-id",
            "gatekeeper_step",
            "--result-file",
            str(result_file),
            "--no-web",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "run_status: succeeded" in result.stdout
    assert "task_verdict: insufficient_evidence" in result.stdout
    assert "task_verdict_source: gatekeeper" in result.stdout
    assert "task_verdict_summary: Required coverage still lacks direct evidence." in result.stdout
    assert "agent_native: complete" in result.stdout


def test_cli_agent_submit_reports_workflow_errors_without_traceback(monkeypatch, tmp_path: Path) -> None:
    workdir = tmp_path / "project"
    workdir.mkdir()
    result_file = tmp_path / "result.json"
    result_file.write_text(
        json.dumps(
            {
                "loopora_host_dispatch": {
                    "adapter": "codex",
                    "run_id": "run_test",
                    "step_id": "builder_step",
                    "target_agent": "loopora-builder",
                    "actual_agent": "loopora-builder",
                    "dispatch_mode": "host_subagent",
                    "inline": False,
                },
                "result": {"summary": "unreachable"},
            }
        ),
        encoding="utf-8",
    )

    class FakeService:
        def submit_agent_native_step(self, _request: AgentNativeStepSubmitRequest):
            raise WorkflowError("workflow control max_fires_per_run must be between 1 and 20")

    monkeypatch.setattr(cli, "create_service", FakeService)
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        [
            "agent",
            "codex",
            "submit",
            "--workdir",
            str(workdir),
            "--run-id",
            "run_corrupt",
            "--step-id",
            "builder_step",
            "--result-file",
            str(result_file),
            "--no-web",
        ],
    )

    assert result.exit_code == 1
    assert "max_fires_per_run" in _error_text(result)
    assert "Traceback" not in _error_text(result)


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
