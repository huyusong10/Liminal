from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner
import yaml

from loopora import cli
from loopora import cli_agent_adapter_commands
import loopora.agent_adapters as agent_adapters
import loopora.agent_web as agent_web
from loopora.bundles import bundle_to_yaml, load_bundle_text
from loopora.executor_fake_payloads import alignment_bundle_yaml
from loopora.service_agent_adapters import AgentBundleCandidateRequest
from loopora.service_agent_native import AgentNativeStepClaimRequest, AgentNativeStepSubmitRequest, ServiceAgentNativeMixin
from loopora.service_types import LooporaConflictError, LooporaError
from loopora.run_artifacts import RunArtifactLayout, read_jsonl
from loopora.web import build_app
from loopora.workflows import WorkflowError


def _error_text(result) -> str:
    try:
        return result.stderr
    except ValueError:
        return result.output


def _candidate_digest(bundle_text: str) -> tuple[str, int]:
    normalized = bundle_text.rstrip() + "\n" if bundle_text.strip() else ""
    data = normalized.encode("utf-8")
    return (hashlib.sha256(data).hexdigest(), len(data)) if data else ("", 0)


def _ready_candidate_digest(bundle_text: str) -> tuple[str, int]:
    return _candidate_digest(bundle_to_yaml(load_bundle_text(bundle_text)))


def _wait_for_alignment_status(service, session_id: str, *statuses: str, timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    expected = set(statuses)
    while time.time() < deadline:
        session = service.get_alignment_session(session_id)
        if session["status"] in expected:
            return session
        time.sleep(0.05)
    session = service.get_alignment_session(session_id)
    raise AssertionError(f"alignment session stayed in {session['status']}, expected {sorted(expected)}")


def _assert_cli_handoff_contract_paths(
    stdout: str,
    *,
    capsule_fragment: str,
    template_fragment: str,
    outbox_fragment: str,
) -> None:
    assert "next_capsule_path:" in stdout
    assert capsule_fragment in stdout
    assert "result_template_path:" in stdout
    assert template_fragment in stdout
    assert "result_outbox_dir:" in stdout
    assert outbox_fragment in stdout


def _assert_cli_list(output: str, key: str, *items: str) -> None:
    assert f"{key}:\n" in output
    assert f"{key}: [" not in output
    for item in items:
        assert f"- {item}" in output


def _assert_missing_candidate_agent_review(review: dict, *, task_message: str) -> None:
    assert review["source"] == "agent_entry"
    assert review["review_mode"] == "missing_candidate_plan"
    assert review["requires_web_alignment"] is True
    assert review["requires_candidate_repair"] is False
    assert review["has_candidate_yaml"] is False
    assert review["not_runnable"] is True
    assert review["adapter"] == "codex"
    assert review["entry_source"] == "codex_project_skill"
    assert review["task_message"] == task_message
    assert task_message in review["suggested_reply"]
    assert review["decision_options"][0]["id"] == "continue_web_review_evidence_first"
    assert review["decision_options"][0]["recommended"] is True
    assert task_message in review["decision_options"][0]["user_reply"]
    assert review["decision_options"][1]["id"] == "recheck_loop_fit"
    assert review["missing_judgment_item_ids"] == [
        "success_surface",
        "fake_done_risks",
        "evidence_preferences",
        "loop_fit",
        "execution_strategy",
        "judgment_tradeoffs",
        "residual_risk_policy",
        "local_governance",
    ]


def _assert_not_fit_agent_review(review: dict) -> None:
    assert review["source"] == "agent_entry"
    assert review["review_mode"] == "not_fit"
    assert review["requires_web_alignment"] is True
    assert review["loopora_fit_contradiction"] is True
    assert review["not_runnable"] is True
    assert review["decision_options"][0]["id"] == "skip_loop"
    assert review["decision_options"][0]["recommended"] is True
    assert review["decision_options"][1]["id"] == "reframe_as_loop"


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
    if archetype == "guide":
        return {
            "created_at_iter": int(step.get("iter") or 0),
            "mode": "repair_guidance",
            "consumed": False,
            "analysis": {
                "stagnation_pattern": "gatekeeper_rejected",
                "recommended_shift": "Add direct evidence for the rejected Done When target.",
                "risk_note": "GateKeeper rejected the current evidence set.",
            },
            "seed_question": "Which missing proof can Builder produce next?",
            "meta_note": "Agent-native workflow control fired.",
        }
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
            "feedback_to_generator": "",
            "blocking_issues": [],
            "metrics": [{"name": "quality_score", "value": 1.0, "threshold": 0.9, "passed": True}],
            "metric_scores": {
                "check_pass_rate": {"value": 1.0, "threshold": 1.0, "passed": True},
                "quality_score": {"value": 1.0, "threshold": 0.9, "passed": True},
            },
            "hard_constraint_violations": [],
            "failed_check_ids": [],
            "priority_failures": [],
            "composite_score": 1.0,
            "evidence_refs": evidence_refs[-4:],
            "evidence_claims": ["The inspector evidence confirms the host Agent submitted a structured result."],
            "residual_risks": [],
            "coverage_results": [],
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
            "feedback_to_generator": "Produce direct proof for the primary user flow.",
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
    assert result["judgment_contract"]["contract_path"] == "contract/run_contract.json"
    return result


def test_agent_native_result_template_uses_schema_shaped_null_scaffold() -> None:
    template = ServiceAgentNativeMixin._agent_native_result_template(
        {
            "adapter": "codex",
            "run_id": "run-scaffold",
            "step_id": "builder_step",
            "role_dispatch": {"target_agent": "loopora-builder"},
            "output_schema": {
                "type": "object",
                "required": ["summary", "checks", "nested"],
                "properties": {
                    "summary": {"type": "string"},
                    "checks": {"type": "array", "items": {"type": "string"}},
                    "nested": {
                        "type": "object",
                        "required": ["status"],
                        "properties": {
                            "status": {"type": "string", "enum": ["covered", "weak"]},
                            "notes": {"type": "array", "items": {"type": "string"}},
                        },
                        "additionalProperties": False,
                    },
                    "optional_flag": {"type": "boolean"},
                },
                "additionalProperties": False,
            },
        }
    )

    assert template["loopora_result_contract"]["result_is_schema_shaped_scaffold"] is True
    assert template["loopora_result_contract"]["replace_null_placeholders_before_submit"] is True
    assert template["result"] == {
        "summary": None,
        "checks": [None],
        "nested": {"status": None, "notes": [None]},
        "optional_flag": None,
    }


def _assert_claude_gen_entry(gen_skill: str, gen_command_text: str) -> None:
    assert "disable-model-invocation: true" in gen_skill
    assert "allowed-tools:" in gen_skill
    assert "LOOPORA_AGENT_ENTRY_SOURCE=claude_project_skill" in gen_skill
    assert 'loopora agent claude gen --workdir "$PWD"' in gen_skill
    assert '--context-id "${CLAUDE_SESSION_ID}"' in gen_skill
    assert "--entry-source claude_project_skill" in gen_skill
    assert "Compile the current Claude Code task goal, fake-done risks, and required evidence" in gen_skill
    assert "Compile the current Claude Code task judgment into a Loopora Loop preview" in gen_skill
    assert "Compile the current Claude Code task goal, fake-done risks, and required evidence" in gen_command_text
    for snippet in (
        '--message "<non-empty short task summary>"',
        'with `--message "<non-empty short task summary>"` but without `--bundle-file`',
        "Loopora fit must say why one Agent pass, one review, direct chat / direct answer, one-off task handling, or benchmark/test-harness-only validation is not enough",
        "new evidence, handoffs, or a GateKeeper verdict",
        "compile them into Builder reading, Inspector / Custom verification, and GateKeeper Weak / Unproven / Blocking responsibility rather than a marker list",
        "Loopora fit reason, high-signal objects, success outcome categories, fake-done risk categories, concrete evidence modes, execution priorities, judgment tradeoffs, local governance responsibilities, and risk terms",
        "Check Loopora fit and judgment sufficiency before authoring a Loop plan file",
        "If Loopora fit is false",
        "ask one focused question",
        "return a Web review prefill",
        "execution strategy",
        "what to build, prove, repair, narrow, expand, or defer first",
        "judgment tradeoffs",
        "local governance responsibilities",
        "owner, follow-up, or acceptance path",
        "do not let a bundle pass merely because it repeats one or two object words from the task",
        "Do not invent human judgment just to pass validation",
        "ready_review_projection",
        "confirm that review summary and preview URL",
        "do not start the run from Web",
        "repair the plan file",
        "Loop preview",
        "Web review",
    ):
        assert snippet in gen_skill
    assert "authoring YAML" not in gen_skill
    assert "fix the YAML" not in gen_skill
    assert "YAML" not in gen_skill
    assert "Web alignment URL" not in gen_skill


def _assert_claude_loop_entry(loop_skill: str, loop_command_text: str) -> None:
    assert "reviewed Loop preview" in loop_skill
    assert "preserves this Claude Code task judgment and evidence requirements" in loop_skill
    assert "preserves this Claude Code task judgment and evidence requirements" in loop_command_text
    assert "confirmed Loop preview" not in loop_skill
    assert "READY bundle" not in loop_skill
    assert "LOOPORA_AGENT_ENTRY_SOURCE=claude_project_skill" in loop_skill
    assert 'loopora agent claude loop --workdir "$PWD"' in loop_skill
    assert "loopora agent claude submit" in loop_skill
    assert "Task" in loop_skill
    for snippet in (
        "loopora_host_dispatch",
        "role_dispatch.target_agent",
        "judgment_contract",
        "next_step.judgment_contract",
        "next_step.required_coverage",
        "next_step.output_schema",
        "next_step.action_policy",
        "next_step.known_evidence_ids",
        "next_step.submit_hint.result_template_absolute_path",
        "Read the returned JSON, even if the command exits nonzero",
        "`loop_recovery=finish_web_review`",
        "`loop_recovery=repair_candidate_plan_file`",
        "Do not collapse these recovery states into a generic",
        "If the command returns `loop_recovery`, report that recovery path and stop",
        "loopora_result_contract",
        "Do not hand-write the wrapper from memory",
        "Fill only the `result` object",
        "next_step.submit_hint.command",
        "run.task_verdict",
        "task_next_action",
        "task_next_action.kind",
        "task_next_action.next_loop_command",
        "continue_evidence",
        "next_step.prompt",
        "next_step.context_absolute_path",
    ):
        assert snippet in loop_skill
    assert '--context-id "${CLAUDE_SESSION_ID}"' in loop_skill
    assert "--entry-source claude_project_skill" in loop_skill


def _assert_claude_agent_prompts(builder_agent: Path, orchestrator_agent: Path) -> None:
    builder_agent_text = builder_agent.read_text(encoding="utf-8")
    orchestrator_agent_text = orchestrator_agent.read_text(encoding="utf-8")
    assert "Loopora Builder" in builder_agent_text
    assert "tools: Read, Glob, Grep, Bash, Write, Edit, MultiEdit" in builder_agent_text
    assert "Loopora Orchestrator" in orchestrator_agent_text
    assert "tools: Task, Read, Write, Bash" in orchestrator_agent_text
    for snippet in (
        "next_step.judgment_contract",
        "next_step.prompt",
        "next_step.output_schema",
        "next_step.action_policy",
        "next_step.known_evidence_ids",
        "next_step.submit_hint.result_template_absolute_path",
        "loopora_result_contract",
        "schema-shaped `result` scaffold",
        "replace every `null` placeholder",
        "task_next_action.kind=continue_evidence",
        "context_absolute_path",
    ):
        assert snippet in orchestrator_agent_text


def _assert_claude_manifest(manifest_path: Path) -> str:
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
    return first_manifest


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
    for path in (gen_command, loop_command, session_hook, builder_agent, orchestrator_agent):
        assert path.exists()
    assert "CLAUDE_SESSION_ID" in session_hook.read_text(encoding="utf-8")
    assert _claude_settings_has_loopora_session_hook(settings)
    _assert_claude_gen_entry(gen_skill, gen_command.read_text(encoding="utf-8"))
    assert "READY bundle" not in gen_skill
    _assert_claude_loop_entry(loop_skill, loop_command.read_text(encoding="utf-8"))
    _assert_claude_agent_prompts(builder_agent, orchestrator_agent)
    manifest_path = workdir / ".loopora" / "adapters" / "claude" / "manifest.json"
    return manifest_path, _assert_claude_manifest(manifest_path)


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
    assert "Compile the current OpenCode task goal, fake-done risks, and required evidence" in gen_command
    assert "Compile the current OpenCode task judgment into a Loopora Loop preview" in gen_command
    for snippet in (
        '--message "<non-empty short task summary>"',
        'with `--message "<non-empty short task summary>"` but without `--bundle-file`',
        "Loopora fit must say why one Agent pass, one review, direct chat / direct answer, one-off task handling, or benchmark/test-harness-only validation is not enough",
        "new evidence, handoffs, or a GateKeeper verdict",
        "compile them into Builder reading, Inspector / Custom verification, and GateKeeper Weak / Unproven / Blocking responsibility rather than a marker list",
        "Loopora fit reason, high-signal objects, success outcome categories, fake-done risk categories, concrete evidence modes, execution priorities, judgment tradeoffs, local governance responsibilities, and risk terms",
        "Check Loopora fit and judgment sufficiency before authoring a Loop plan file",
        "If Loopora fit is false",
        "ask one focused question",
        "return a Web review prefill",
        "execution strategy",
        "what to build, prove, repair, narrow, expand, or defer first",
        "judgment tradeoffs",
        "local governance responsibilities",
        "owner, follow-up, or acceptance path",
        "do not let a bundle pass merely because it repeats one or two object words from the task",
        "Do not invent human judgment just to pass validation",
        "ready_review_projection",
        "confirm that review summary and preview URL",
        "do not start the run from Web",
        "repair the plan file",
        "Loop preview",
        "Web review",
    ):
        assert snippet in gen_command
    assert "authoring YAML" not in gen_command
    assert "fix the YAML" not in gen_command
    assert "YAML" not in gen_command
    assert "reviewed Loop preview" in loop_command
    assert "preserves this OpenCode task judgment and evidence requirements" in loop_command
    assert "confirmed Loop preview" not in loop_command
    assert "READY bundle" not in gen_command
    assert "READY bundle" not in loop_command
    assert "LOOPORA_AGENT_ENTRY_SOURCE=opencode_project_command" in loop_command
    assert "agent: loopora-orchestrator" in loop_command
    assert "subtask: true" in loop_command
    assert 'loopora agent opencode loop --workdir "$PWD"' in loop_command
    assert "loopora agent opencode submit" in loop_command
    for snippet in (
        "loopora_host_dispatch",
        "role_dispatch.target_agent",
        "judgment_contract",
        "next_step.judgment_contract",
        "next_step.required_coverage",
        "next_step.output_schema",
        "next_step.action_policy",
        "next_step.known_evidence_ids",
        "next_step.submit_hint.result_template_absolute_path",
        "Read the returned JSON, even if the command exits nonzero",
        "`loop_recovery=finish_web_review`",
        "`loop_recovery=repair_candidate_plan_file`",
        "Do not collapse these recovery states into a generic",
        "If the command returns `loop_recovery`, report that recovery path and stop",
        "loopora_result_contract",
        "Do not hand-write the wrapper from memory",
        "Fill only the `result` object",
        "next_step.submit_hint.command",
        "run.task_verdict",
        "task_next_action",
        "task_next_action.kind",
        "task_next_action.next_loop_command",
        "continue_evidence",
        "next_step.prompt",
        "next_step.context_absolute_path",
    ):
        assert snippet in loop_command
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
    for snippet in (
        "next_step.judgment_contract",
        "next_step.prompt",
        "next_step.output_schema",
        "next_step.action_policy",
        "next_step.known_evidence_ids",
        "next_step.submit_hint.result_template_absolute_path",
        "loopora_result_contract",
        "schema-shaped `result` scaffold",
        "replace every `null` placeholder",
        "task_next_action.kind=continue_evidence",
        "context_absolute_path",
    ):
        assert snippet in orchestrator_agent_text
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
    assert "compile the current task goal, fake-done risks, and required evidence" in gen_skill
    assert "Compile the current coding task judgment into a Loopora Loop preview" in gen_skill
    for snippet in (
        '--message "<non-empty short task summary>"',
        'with `--message "<non-empty short task summary>"` but without `--bundle-file`',
        "Loopora fit must say why one Agent pass, one review, direct chat / direct answer, one-off task handling, or benchmark/test-harness-only validation is not enough",
        "new evidence, handoffs, or a GateKeeper verdict",
        "compile them into Builder reading, Inspector / Custom verification, and GateKeeper Weak / Unproven / Blocking responsibility rather than a marker list",
        "Loopora fit reason, high-signal objects, success outcome categories, fake-done risk categories, concrete evidence modes, execution priorities, judgment tradeoffs, local governance responsibilities, and risk terms",
        "Check Loopora fit and judgment sufficiency before authoring a Loop plan file",
        "If Loopora fit is false",
        "ask one focused question",
        "return a Web review prefill",
        "execution strategy",
        "what to build, prove, repair, narrow, expand, or defer first",
        "judgment tradeoffs",
        "local governance responsibilities",
        "owner, follow-up, or acceptance path",
        "do not let a bundle pass merely because it repeats one or two object words from the task",
        "Do not invent human judgment just to pass validation",
        "ready_review_projection",
        "confirm that review summary and preview URL",
        "do not start the run from Web",
        "repair the plan file",
        "Loop preview",
        "Web review",
    ):
        assert snippet in gen_skill
    assert "authoring YAML" not in gen_skill
    assert "fix the YAML" not in gen_skill
    assert "YAML" not in gen_skill
    assert "reviewed Loop preview" in loop_skill
    assert "preserves the current task judgment and evidence requirements" in loop_skill
    assert "confirmed Loop preview" not in loop_skill
    assert "READY bundle" not in gen_skill
    assert "READY bundle" not in loop_skill
    assert "name: loopora-loop" in loop_skill
    assert "LOOPORA_AGENT_ENTRY_SOURCE=codex_project_skill" in loop_skill
    assert 'loopora agent codex loop --workdir "$PWD"' in loop_skill
    assert "loopora agent codex submit" in loop_skill
    assert "loopora-builder" in loop_skill
    for snippet in (
        "loopora_host_dispatch",
        "role_dispatch.target_agent",
        "judgment_contract",
        "next_step.judgment_contract",
        "next_step.required_coverage",
        "next_step.output_schema",
        "next_step.action_policy",
        "next_step.known_evidence_ids",
        "next_step.submit_hint.result_template_absolute_path",
        "Read the returned JSON, even if the command exits nonzero",
        "`loop_recovery=finish_web_review`",
        "`loop_recovery=repair_candidate_plan_file`",
        "Do not collapse these recovery states into a generic",
        "If the command returns `loop_recovery`, report that recovery path and stop",
        "loopora_result_contract",
        "Do not hand-write the wrapper from memory",
        "Fill only the `result` object",
        "next_step.submit_hint.command",
        "run.task_verdict",
        "task_next_action",
        "task_next_action.kind",
        "task_next_action.next_loop_command",
        "continue_evidence",
        "next_step.prompt",
        "next_step.context_absolute_path",
    ):
        assert snippet in loop_skill
    assert "Codex native dispatch guidance" in loop_skill
    assert "omit `fork_context`" in loop_skill
    assert "bounded timeout" in loop_skill
    assert "--entry-source codex_project_skill" in loop_skill
    codex_builder_agent_text = codex_builder_agent.read_text(encoding="utf-8")
    assert "loopora-builder" in codex_builder_agent_text
    assert 'developer_instructions = """' in codex_builder_agent_text
    assert '\ninstructions = """' not in codex_builder_agent_text
    codex_orchestrator_agent_text = codex_orchestrator_agent.read_text(encoding="utf-8")
    assert "Loopora Orchestrator" in codex_orchestrator_agent_text
    for snippet in (
        "next_step.judgment_contract",
        "next_step.prompt",
        "next_step.output_schema",
        "next_step.action_policy",
        "next_step.known_evidence_ids",
        "next_step.submit_hint.result_template_absolute_path",
        "loopora_result_contract",
        "schema-shaped `result` scaffold",
        "replace every `null` placeholder",
        "task_next_action.kind=continue_evidence",
        "context_absolute_path",
    ):
        assert snippet in codex_orchestrator_agent_text
    manifest_path = workdir / ".loopora" / "adapters" / "codex" / "manifest.json"
    assert manifest_path.exists()
    first_manifest = manifest_path.read_text(encoding="utf-8")
    manifest_payload = json.loads(first_manifest)
    assert manifest_payload["version"] == agent_adapters.ADAPTER_VERSION
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


@pytest.mark.parametrize(
    ("adapter", "label"),
    [
        ("codex", "Codex"),
        ("claude", "Claude Code"),
        ("opencode", "OpenCode"),
    ],
)
def test_cli_adapter_install_human_output_points_to_agent_next_steps(tmp_path: Path, adapter: str, label: str) -> None:
    workdir = tmp_path / adapter
    workdir.mkdir()
    runner = CliRunner()

    result = runner.invoke(cli.app, ["init", adapter, "--workdir", str(workdir)])

    assert result.exit_code == 0, result.stdout
    assert f"{label} Loopora entry is installed" in result.stdout
    assert f"target project: {workdir.resolve()}" in result.stdout
    assert "next:" in result.stdout
    assert f"Return to {label} in this project" in result.stdout
    assert "task goal, fake-done risk, and required evidence" in result.stdout
    assert "/loopora-gen" in result.stdout
    assert "READY Loop preview" in result.stdout
    assert "/loopora-loop" in result.stdout
    assert "same Agent session" in result.stdout
    assert "observe evidence, gaps, and verdicts" in result.stdout
    assert "managed files:" in result.stdout
    assert result.stdout.index("next:") < result.stdout.index("managed files:")
    assert "adapter installed" not in result.stdout
    assert "YAML bundle" not in result.stdout


def test_cli_codex_adapter_install_conflict_guides_recovery_without_overwriting(tmp_path: Path) -> None:
    workdir = tmp_path / "project"
    conflict = workdir / ".agents" / "skills" / "loopora-gen" / "SKILL.md"
    conflict.parent.mkdir(parents=True)
    conflict.write_text("# User-owned Codex entry\n", encoding="utf-8")
    runner = CliRunner()

    result = runner.invoke(cli.app, ["init", "codex", "--workdir", str(workdir)])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert conflict.read_text(encoding="utf-8") == "# User-owned Codex entry\n"
    assert not (workdir / ".loopora" / "adapters" / "codex" / "manifest.json").exists()
    error_text = _error_text(result)
    assert "Codex Loopora entry was not installed." in error_text
    assert f"target project: {workdir.resolve()}" in error_text
    assert "left the project unchanged" in error_text
    assert "conflicting files:" in error_text
    assert ".agents/skills/loopora-gen/SKILL.md" in error_text
    assert "recovery:" in error_text
    assert "Inspect the listed file or config" in error_text
    assert "move or rename it" in error_text
    assert "loopora init codex --workdir" in error_text
    assert "refusing to overwrite" not in error_text
    assert "cli.command.failed" not in error_text


def test_cli_codex_loop_requires_ready_bundle(tmp_path: Path) -> None:
    workdir = tmp_path / "project"
    workdir.mkdir()
    runner = CliRunner()

    result = runner.invoke(cli.app, ["agent", "codex", "loop", "--workdir", str(workdir), "--no-web"])

    assert result.exit_code == 1
    error_text = _error_text(result)
    assert "/loopora-gen" in error_text
    assert "ready Loop preview" in error_text
    assert "READY Loopora bundle" not in error_text


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
    error_text = _error_text(result)
    assert "/loopora-gen" in error_text
    assert "ready Loop preview" in error_text
    assert "READY Loopora bundle" not in error_text


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
    error_text = _error_text(result)
    assert "/loopora-gen" in error_text
    assert "ready Loop preview" in error_text
    assert "READY Loopora bundle" not in error_text


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


def test_agent_bundle_candidate_without_yaml_opens_prefill_without_starting_alignment(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")

    generated = service.create_agent_bundle_candidate(
        AgentBundleCandidateRequest(
            adapter="codex",
            workdir=sample_workdir,
            message="Prepare a governed implementation loop from the host Agent context.",
            entry_source="codex_project_skill",
        )
    )

    assert generated["ready"] is False
    assert generated["status"] == "idle"
    assert generated["requires_web_alignment"] is True
    assert generated["requires_candidate_repair"] is False
    assert generated["candidate_sha256"] == ""
    assert generated["candidate_bytes"] == 0
    assert generated["ready_candidate_sha256"] == ""
    assert generated["ready_candidate_bytes"] == 0
    _assert_missing_candidate_agent_review(
        generated["session"]["agent_entry_review"],
        task_message="Prepare a governed implementation loop from the host Agent context.",
    )
    transcript = generated["session"]["transcript"]
    assert transcript[0]["content"] == "Prepare a governed implementation loop from the host Agent context."
    assert transcript[-1]["role"] == "assistant"
    assert "Web review" in transcript[-1]["content"]
    assert "not a runnable Loop yet" in transcript[-1]["content"]
    assert "candidate plan file" in transcript[-1]["content"]
    assert "candidate YAML" not in transcript[-1]["content"]
    assert "Loopora fit" in transcript[-1]["content"]
    assert "execution strategy" in transcript[-1]["content"]
    assert "judgment tradeoffs" in transcript[-1]["content"]
    assert "local governance responsibilities" in transcript[-1]["content"]
    assert generated["binding"]["requires_web_alignment"] is True
    assert generated["binding"]["requires_candidate_repair"] is False
    assert generated["binding"]["candidate_sha256"] == ""
    assert generated["binding"]["candidate_bytes"] == 0
    assert generated["binding"]["ready_candidate_sha256"] == ""
    assert generated["binding"]["ready_candidate_bytes"] == 0
    assert generated["preview_path"].startswith("/loops/new/bundle?alignment_session_id=")
    transcript_log = Path(generated["session"]["artifact_dir"]) / "conversation" / "transcript.jsonl"
    assert "Web review" in transcript_log.read_text(encoding="utf-8")
    events = service.list_alignment_events(generated["session"]["id"])
    candidate_event = next(event for event in events if event["event_type"] == "agent_candidate_received")
    assert candidate_event["payload"]["has_candidate_yaml"] is False
    assert candidate_event["payload"]["requires_web_alignment"] is True
    assert candidate_event["payload"]["requires_candidate_repair"] is False
    assert candidate_event["payload"]["candidate_sha256"] == ""
    assert candidate_event["payload"]["candidate_bytes"] == 0

    service.append_alignment_message(
        generated["session"]["id"],
        generated["session"]["agent_entry_review"]["suggested_reply"],
    )
    agreement = _wait_for_alignment_status(service, generated["session"]["id"], "waiting_user")
    assert agreement["alignment_stage"] == "agreement_ready"
    assert agreement.get("agent_entry_review", {}) == {}
    assert candidate_event["payload"]["ready_candidate_sha256"] == ""
    assert candidate_event["payload"]["ready_candidate_bytes"] == 0
    assert not any(event["event_type"] == "alignment_started" for event in events)
    with pytest.raises(LooporaConflictError) as excinfo:
        service.start_agent_loop("codex", workdir=sample_workdir, entry_source="codex_project_skill", execute_async=False)
    assert "needs Web review before /loopora-loop" in str(excinfo.value)
    assert "/loopora-gen" in str(excinfo.value)


def test_agent_bundle_candidate_without_yaml_uses_chinese_prefill_message(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")

    generated = service.create_agent_bundle_candidate(
        AgentBundleCandidateRequest(
            adapter="codex",
            workdir=sample_workdir,
            message="为退款自助流程准备一个需要多轮证据治理的 Loop。",
            entry_source="codex_project_skill",
        )
    )

    message = generated["session"]["transcript"][-1]["content"]
    assert "候选方案文件" in message
    assert "不会伪装成可运行 Loop" in message
    assert "执行策略" in message
    assert "判断取舍" in message
    assert "本地治理责任" in message
    assert "candidate plan file" not in message


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("This is a one-off task; no Loopora loop is needed.", "one-off fix"),
        ("这是一次性任务，不要长期循环，直接处理完即可。", "不需要后续新证据"),
        ("The stable proof harness already fully captures the judgment.", "benchmark/test-harness-only path"),
    ],
)
def test_agent_bundle_candidate_without_yaml_explains_not_fit_prefill(
    service_factory,
    sample_workdir: Path,
    message: str,
    expected: str,
) -> None:
    service = service_factory(scenario="success")

    generated = service.create_agent_bundle_candidate(
        AgentBundleCandidateRequest(
            adapter="codex",
            workdir=sample_workdir,
            message=message,
            entry_source="codex_project_skill",
        )
    )

    transcript_message = generated["session"]["transcript"][-1]["content"]
    assert generated["ready"] is False
    assert generated["requires_web_alignment"] is True
    assert generated["requires_candidate_repair"] is False
    assert generated["loopora_fit_contradiction"] is True
    assert generated["binding"]["loopora_fit_contradiction"] is True
    _assert_not_fit_agent_review(generated["session"]["agent_entry_review"])
    assert "Web review" in transcript_message
    assert "not a runnable Loop yet" in transcript_message or "不会伪装成可运行 Loop" in transcript_message
    assert expected in transcript_message
    assert "success criteria" not in transcript_message
    events = service.list_alignment_events(generated["session"]["id"])
    candidate_event = next(event for event in events if event["event_type"] == "agent_candidate_received")
    assert candidate_event["payload"]["has_candidate_yaml"] is False
    assert candidate_event["payload"]["loopora_fit_contradiction"] is True
    with pytest.raises(LooporaConflictError) as excinfo:
        service.start_agent_loop("codex", workdir=sample_workdir, entry_source="codex_project_skill", execute_async=False)
    assert "needs Web review before /loopora-loop" in str(excinfo.value)
    assert "one-off, direct-answer, no-new-evidence, or benchmark/test-harness-only" in str(excinfo.value)
    assert "GateKeeper value" in str(excinfo.value)


def test_agent_bundle_candidate_without_yaml_requires_task_summary(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")

    with pytest.raises(LooporaError, match="--message task summary"):
        service.create_agent_bundle_candidate(
            AgentBundleCandidateRequest(
                adapter="codex",
                workdir=sample_workdir,
                entry_source="codex_project_skill",
            )
        )


def test_agent_loop_clears_web_review_requirement_after_fallback_becomes_ready(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    generated = service.create_agent_bundle_candidate(
        AgentBundleCandidateRequest(
            adapter="codex",
            workdir=sample_workdir,
            message="Prepare a governed implementation loop from the host Agent context.",
            entry_source="codex_project_skill",
        )
    )
    assert generated["binding"]["requires_web_alignment"] is True
    Path(generated["session"]["bundle_path"]).write_text(alignment_bundle_yaml(str(sample_workdir.resolve())), encoding="utf-8")
    synced = service.sync_alignment_bundle_from_file(generated["session"]["id"])
    assert synced["session"]["status"] == "ready"
    assert synced["session"].get("agent_entry_review", {}) == {}

    started = service.start_agent_loop("codex", workdir=sample_workdir, entry_source="codex_project_skill", execute_async=False)

    assert started["execution_plane"] == "agent_native"
    assert started["started_new_run"] is True
    assert started["session"].get("agent_entry_review", {}) == {}
    assert started["binding"]["requires_web_alignment"] is False
    assert started["binding"]["alignment_status"] == "running_loop"
    assert started["binding"]["linked_run_id"] == started["run"]["id"]


def test_agent_loop_clears_not_fit_fallback_after_web_review_becomes_ready(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    generated = service.create_agent_bundle_candidate(
        AgentBundleCandidateRequest(
            adapter="codex",
            workdir=sample_workdir,
            message="There is no need for a Loopora loop here; just answer directly.",
            entry_source="codex_project_skill",
        )
    )
    assert generated["binding"]["requires_web_alignment"] is True
    assert generated["binding"]["loopora_fit_contradiction"] is True
    Path(generated["session"]["bundle_path"]).write_text(alignment_bundle_yaml(str(sample_workdir.resolve())), encoding="utf-8")
    synced = service.sync_alignment_bundle_from_file(generated["session"]["id"])
    assert synced["session"]["status"] == "ready"
    assert synced["session"].get("agent_entry_review", {}) == {}

    started = service.start_agent_loop("codex", workdir=sample_workdir, entry_source="codex_project_skill", execute_async=False)

    assert started["execution_plane"] == "agent_native"
    assert started["started_new_run"] is True
    assert started["session"].get("agent_entry_review", {}) == {}
    assert started["binding"]["requires_web_alignment"] is False
    assert started["binding"]["loopora_fit_contradiction"] is False
    events = service.list_alignment_events(generated["session"]["id"])
    candidate_event = next(event for event in events if event["event_type"] == "agent_candidate_received")
    assert candidate_event["payload"]["loopora_fit_contradiction"] is True


def test_cli_agent_gen_without_bundle_reports_web_alignment_needed(sample_workdir: Path) -> None:
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
            "--entry-source",
            "codex_project_skill",
            "--no-web",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "Loopora Loop preview needs Web review" in result.stdout
    assert "not_fit:" not in result.stdout
    assert "review_status: not runnable; no candidate plan file was submitted" in result.stdout
    assert "review_focus:" in result.stdout
    assert "Success surface:" in result.stdout
    assert "Fake-done risks:" in result.stdout
    assert "Evidence expectations:" in result.stdout
    assert "next_review_step: open the preview URL" in result.stdout
    assert "Web alignment" not in result.stdout
    assert "preview_url: /loops/new/bundle?alignment_session_id=" in result.stdout
    assert "candidate_url:" not in result.stdout


def test_cli_agent_gen_reports_auto_started_web_review_url(sample_workdir: Path, monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setattr(
        cli_agent_adapter_commands,
        "ensure_local_web_service",
        lambda: {"base_url": "http://127.0.0.1:9876", "reused": False, "started": True, "port": 9876},
    )

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
            "--entry-source",
            "codex_project_skill",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "Loopora Loop preview needs Web review" in result.stdout
    assert "review_status: not runnable; no candidate plan file was submitted" in result.stdout
    assert "review_focus:" in result.stdout
    assert "preview_url: http://127.0.0.1:9876/loops/new/bundle?alignment_session_id=" in result.stdout
    assert "web: started http://127.0.0.1:9876" in result.stdout


def test_cli_agent_loop_after_web_review_fallback_reprints_review_url_and_focus(sample_workdir: Path, monkeypatch) -> None:
    runner = CliRunner()
    gen_result = runner.invoke(
        cli.app,
        [
            "agent",
            "codex",
            "gen",
            "--workdir",
            str(sample_workdir),
            "--message",
            "Prepare a governed implementation loop with later evidence and GateKeeper review.",
            "--entry-source",
            "codex_project_skill",
            "--no-web",
        ],
    )
    monkeypatch.setattr(
        cli_agent_adapter_commands,
        "ensure_local_web_service",
        lambda: {"base_url": "http://127.0.0.1:9988", "reused": False, "started": True, "port": 9988},
    )

    loop_result = runner.invoke(cli.app, ["agent", "codex", "loop", "--workdir", str(sample_workdir)])

    assert gen_result.exit_code == 0, gen_result.stdout
    assert loop_result.exit_code == 1
    output_text = loop_result.output
    assert "loop_recovery: finish the current Web review before /loopora-loop can start" in output_text
    assert "review_status: not runnable; no candidate plan file was submitted" in output_text
    assert "review_focus:" in output_text
    assert "Success surface:" in output_text
    assert "Fake-done risks:" in output_text
    assert "Evidence expectations:" in output_text
    assert "next_review_step: open the preview URL" in output_text
    assert "preview_url: http://127.0.0.1:9988/loops/new/bundle?alignment_session_id=" in output_text
    assert "web: started http://127.0.0.1:9988" in output_text
    assert "Traceback" not in output_text
    assert _error_text(loop_result) == ""
    assert "cli.command.failed" not in output_text
    assert "current status: idle" not in output_text


def test_cli_agent_loop_json_after_web_review_fallback_returns_structured_recovery(sample_workdir: Path) -> None:
    runner = CliRunner()
    gen_result = runner.invoke(
        cli.app,
        [
            "agent",
            "codex",
            "gen",
            "--workdir",
            str(sample_workdir),
            "--message",
            "Prepare a governed implementation loop with later evidence and GateKeeper review.",
            "--entry-source",
            "codex_project_skill",
            "--no-web",
        ],
    )

    loop_result = runner.invoke(
        cli.app,
        ["agent", "codex", "loop", "--workdir", str(sample_workdir), "--no-web", "--json"],
    )

    assert gen_result.exit_code == 0, gen_result.stdout
    assert loop_result.exit_code == 1
    assert _error_text(loop_result) == ""
    payload = json.loads(loop_result.stdout)
    assert payload["ready"] is False
    assert payload["requires_web_alignment"] is True
    assert payload["requires_candidate_repair"] is False
    assert payload["loop_recovery"] == "finish_web_review"
    assert payload["preview_url"].startswith("/loops/new/bundle?alignment_session_id=")
    assert payload["binding"]["candidate_entry_source"] == "codex_project_skill"


def test_cli_agent_gen_without_bundle_reports_not_fit_fallback(sample_workdir: Path) -> None:
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
            "There is no need for a Loopora loop here; just answer directly.",
            "--entry-source",
            "codex_project_skill",
            "--no-web",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "Loopora Loop preview needs Web review" in result.stdout
    assert "not_fit:" in result.stdout
    assert "review_status: not runnable; Loopora fit needs to be redefined" in result.stdout
    assert "review_focus:" in result.stdout
    assert "Loopora fit: define later evidence, handoffs, or GateKeeper value" in result.stdout
    assert "one-off, direct-answer, no-new-evidence, or benchmark/test-harness-only work" in result.stdout
    assert "GateKeeper value" in result.stdout
    assert "preview_url: /loops/new/bundle?alignment_session_id=" in result.stdout


def test_cli_agent_gen_without_bundle_json_reports_not_fit_fallback(sample_workdir: Path) -> None:
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
            "There is no need for a Loopora loop here; just answer directly.",
            "--entry-source",
            "codex_project_skill",
            "--no-web",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["ready"] is False
    assert payload["requires_web_alignment"] is True
    assert payload["requires_candidate_repair"] is False
    assert payload["loopora_fit_contradiction"] is True
    assert payload["binding"]["loopora_fit_contradiction"] is True
    assert payload["preview_url"].startswith("/loops/new/bundle?alignment_session_id=")


def test_cli_agent_gen_without_bundle_rejects_missing_task_summary(sample_workdir: Path) -> None:
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        [
            "agent",
            "codex",
            "gen",
            "--workdir",
            str(sample_workdir),
            "--entry-source",
            "codex_project_skill",
            "--no-web",
        ],
    )

    assert result.exit_code == 1
    assert "--message task summary" in _error_text(result)


def test_agent_adapter_preview_fallback_uses_web_review_language() -> None:
    root = Path(__file__).resolve().parents[3]
    sources = "\n".join(
        [
            (root / "src" / "loopora" / "agent_adapters.py").read_text(encoding="utf-8"),
            (root / "src" / "loopora" / "cli_agent_adapter_commands.py").read_text(encoding="utf-8"),
        ]
    )

    assert "Web review" in sources
    assert "Web alignment URL" not in sources
    assert "needs Web alignment" not in sources
    assert "more alignment before" not in sources


def test_cli_codex_gen_accepts_ready_bundle_without_starting_run(tmp_path: Path, sample_workdir: Path) -> None:
    bundle_file = tmp_path / "bundle.yml"
    bundle_text = alignment_bundle_yaml(str(sample_workdir.resolve()))
    expected_sha, expected_bytes = _candidate_digest(bundle_text)
    expected_ready_sha, expected_ready_bytes = _ready_candidate_digest(bundle_text)
    bundle_file.write_text(bundle_text, encoding="utf-8")
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
            "Ship contract inspection for implementation handoff.",
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
    assert payload["requires_web_alignment"] is False
    assert payload["requires_candidate_repair"] is False
    assert payload["candidate_sha256"] == expected_sha
    assert payload["candidate_bytes"] == expected_bytes
    assert payload["ready_candidate_sha256"] == expected_ready_sha
    assert payload["ready_candidate_bytes"] == expected_ready_bytes
    assert payload["binding"]["candidate_sha256"] == expected_sha
    assert payload["binding"]["candidate_bytes"] == expected_bytes
    assert payload["binding"]["ready_candidate_sha256"] == expected_ready_sha
    assert payload["binding"]["ready_candidate_bytes"] == expected_ready_bytes
    assert payload["session"].get("agent_entry_review", {}) == {}
    assert payload["session"]["agent_entry_launch"]["ready_candidate_sha256"] == expected_ready_sha
    assert payload["session"]["agent_entry_launch"]["ready_candidate_bytes"] == expected_ready_bytes
    review = payload["ready_review_projection"]
    assert "Future iterations stay anchored" in review["loopora_fit_reasons"][0]
    assert "happy-path claim" in review["fake_done_risks"][0]
    assert "project-owned checks" in review["evidence_preferences"][0]
    assert review["coverage"]["check_count"] == 2
    assert review["coverage"]["target_count"] >= review["coverage"]["check_count"]
    assert review["traceability"]["mapped_count"] == review["traceability"]["required_count"]
    assert review["gatekeeper"]["enabled"] is True
    assert review["gatekeeper"]["requires_evidence_refs"] is True
    assert payload["preview_url"].startswith("/loops/new/bundle?alignment_session_id=")
    assert "run" not in payload


def test_cli_agent_gen_ready_output_points_back_to_same_agent_loop(tmp_path: Path, sample_workdir: Path) -> None:
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
            "Ship contract inspection for implementation handoff.",
            "--bundle-file",
            str(bundle_file),
            "--entry-source",
            "codex_project_skill",
            "--no-web",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "Loopora Loop preview is ready" in result.stdout
    assert "next_agent_step: review the preview URL, then run /loopora-loop in this same Agent session" in result.stdout
    assert "ready_review:" in result.stdout
    assert "loopora_fit:" in result.stdout
    assert "fake_done_risks:" in result.stdout
    assert "evidence_preferences:" in result.stdout
    assert "coverage_targets: 2 checks /" in result.stdout
    assert "judgment_projection: 13/13 mapped" in result.stdout
    assert "closure_gate: GateKeeper (evidence_refs_required)" in result.stdout
    assert "review_before_loop: confirm the preview carries these judgments before running /loopora-loop" in result.stdout
    assert "preview_url: /loops/new/bundle?alignment_session_id=" in result.stdout
    assert "run_url:" not in result.stdout
    assert "Loopora run:" not in result.stdout


def test_cli_agent_gen_rejects_candidate_bundle_without_task_summary(tmp_path: Path, sample_workdir: Path) -> None:
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
            "--bundle-file",
            str(bundle_file),
            "--no-web",
        ],
    )

    assert result.exit_code == 1
    assert "--message task summary" in _error_text(result)


def test_cli_agent_gen_with_invalid_candidate_reports_repair_before_loop(tmp_path: Path, sample_workdir: Path) -> None:
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
            "Build a governed refund self-service flow with authorization, audit, and payment failure evidence.",
            "--bundle-file",
            str(bundle_file),
            "--no-web",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "Loopora Loop preview needs plan file repair before /loopora-loop" in result.stdout
    assert "needs candidate repair" not in result.stdout
    assert "validation_error:" in result.stdout
    assert "plan_file_to_repair:" in result.stdout
    assert "preview_plan_copy:" in result.stdout
    assert "repair_focus:" in result.stdout
    assert "next_repair_step:" in result.stdout
    assert "host Agent task summary" in result.stdout
    assert "preview_url: /loops/new/bundle?alignment_session_id=" in result.stdout


def test_cli_agent_loop_reports_candidate_repair_state_after_failed_gen(
    tmp_path: Path,
    sample_workdir: Path,
) -> None:
    bundle_file = tmp_path / "bundle.yml"
    bundle_file.write_text(alignment_bundle_yaml(str(sample_workdir.resolve())), encoding="utf-8")
    runner = CliRunner()

    gen_result = runner.invoke(
        cli.app,
        [
            "agent",
            "codex",
            "gen",
            "--workdir",
            str(sample_workdir),
            "--message",
            "Build a governed refund self-service flow with authorization, audit, and payment failure evidence.",
            "--bundle-file",
            str(bundle_file),
            "--no-web",
        ],
    )
    loop_result = runner.invoke(cli.app, ["agent", "codex", "loop", "--workdir", str(sample_workdir), "--no-web"])

    assert gen_result.exit_code == 0, gen_result.stdout
    assert loop_result.exit_code == 1
    output_text = loop_result.output
    error_text = _error_text(loop_result)
    assert "loop_recovery: repair the current plan file before /loopora-loop can start" in output_text
    assert error_text == ""
    assert "plan_file_to_repair:" in output_text
    assert "preview_plan_copy:" in output_text
    assert "repair_focus:" in output_text
    assert "preview_url: /loops/new/bundle?alignment_session_id=" in output_text
    assert "next_repair_step: repair the candidate plan file, rerun /loopora-gen" in output_text
    assert "project the task objects from --message" in output_text


def test_cli_agent_gen_with_candidate_not_fit_reports_reframe_before_loop(
    tmp_path: Path,
    sample_workdir: Path,
) -> None:
    bundle_file = tmp_path / "bundle.yml"
    bundle_file.write_text(alignment_bundle_yaml(str(sample_workdir.resolve())), encoding="utf-8")
    runner = CliRunner()

    gen_result = runner.invoke(
        cli.app,
        [
            "agent",
            "codex",
            "gen",
            "--workdir",
            str(sample_workdir),
            "--message",
            "There is no need for a Loopora loop here; just answer directly.",
            "--bundle-file",
            str(bundle_file),
            "--no-web",
        ],
    )
    loop_result = runner.invoke(cli.app, ["agent", "codex", "loop", "--workdir", str(sample_workdir), "--no-web"])

    assert gen_result.exit_code == 0, gen_result.stdout
    assert "Loopora Loop preview needs plan file repair before /loopora-loop" in gen_result.stdout
    assert "not_fit:" in gen_result.stdout
    assert "reframe the task with later evidence, handoff, or GateKeeper value" in gen_result.stdout
    assert "Loopora is not fit" in gen_result.stdout
    assert loop_result.exit_code == 1
    error_text = _error_text(loop_result)
    assert error_text == ""
    assert "loop_recovery: repair the current plan file before /loopora-loop can start" in loop_result.output
    assert "not_fit:" in loop_result.output
    assert "one-off, direct-answer, no-new-evidence, or benchmark/test-harness-only" in loop_result.output
    assert "GateKeeper value" in loop_result.output
    assert "next_repair_step: repair the candidate plan file, rerun /loopora-gen" in loop_result.output


def test_cli_agent_gen_uses_repair_flag_when_candidate_status_is_not_failed(
    monkeypatch,
    tmp_path: Path,
) -> None:
    workdir = tmp_path / "project"
    workdir.mkdir()

    class FakeService:
        def create_agent_bundle_candidate(self, request: AgentBundleCandidateRequest) -> dict:
            assert request.adapter == "codex"
            assert request.workdir == workdir
            assert request.message == "Repair this candidate without pretending it is runnable."
            return {
                "ready": False,
                "status": "blocked",
                "requires_web_alignment": False,
                "requires_candidate_repair": True,
                "session": {
                    "id": "session_repair",
                    "error_message": "candidate is missing required audit evidence",
                },
                "preview_path": "/loops/new/bundle?alignment_session_id=session_repair",
            }

    monkeypatch.setattr(cli, "create_service", FakeService)
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        [
            "agent",
            "codex",
            "gen",
            "--workdir",
            str(workdir),
            "--message",
            "Repair this candidate without pretending it is runnable.",
            "--no-web",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "Loopora Loop preview needs plan file repair before /loopora-loop" in result.stdout
    assert "needs candidate repair" not in result.stdout
    assert "validation_error: candidate is missing required audit evidence" in result.stdout
    assert "Loopora Loop preview status: blocked" not in result.stdout


def test_agent_bundle_candidate_rejects_task_context_mismatch(
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
            message="Build a governed refund self-service flow with authorization, audit, and payment failure evidence.",
            bundle_file=bundle_file,
            entry_source="codex_project_skill",
        )
    )

    assert generated["ready"] is False
    assert generated["status"] == "failed"
    assert generated["requires_web_alignment"] is False
    assert generated["requires_candidate_repair"] is True
    assert generated["ready_candidate_sha256"] == ""
    assert generated["ready_candidate_bytes"] == 0
    assert generated["binding"]["requires_web_alignment"] is False
    assert generated["binding"]["requires_candidate_repair"] is True
    assert generated["binding"]["ready_candidate_sha256"] == ""
    assert generated["binding"]["ready_candidate_bytes"] == 0
    assert generated["session"].get("agent_entry_review", {}) == {}
    assert "host Agent task summary" in generated["session"]["error_message"]
    assert "refund" in generated["session"]["error_message"]
    assert "audit" in generated["session"]["error_message"]
    candidate_event = next(
        event for event in service.list_alignment_events(generated["session"]["id"]) if event["event_type"] == "agent_candidate_received"
    )
    assert candidate_event["payload"]["requires_candidate_repair"] is False
    assert candidate_event["payload"]["ready_candidate_sha256"] == ""
    assert candidate_event["payload"]["ready_candidate_bytes"] == 0
    assert any(
        event["event_type"] == "alignment_bundle_sync_failed"
        and "host Agent task summary" in event["payload"].get("error", "")
        for event in service.list_alignment_events(generated["session"]["id"])
    )


def test_agent_bundle_candidate_repair_session_keeps_web_plan_previewable(
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
            message="Build a governed refund self-service flow with authorization, audit, and payment failure evidence.",
            bundle_file=bundle_file,
            entry_source="codex_project_skill",
        )
    )

    assert generated["ready"] is False
    assert generated["requires_candidate_repair"] is True
    client = TestClient(build_app(service=service))
    response = client.get(f"/api/alignments/sessions/{generated['session']['id']}/bundle")

    assert response.status_code == 200
    preview = response.json()
    assert preview["ok"] is True
    assert preview["session"]["status"] == "failed"
    assert preview["source_path"] == generated["session"]["bundle_path"]
    assert preview["validation"]["ok"] is False
    assert "host Agent task summary" in preview["validation"]["error"]
    assert preview["control_summary"]["coverage"]["target_count"] >= preview["control_summary"]["coverage"]["check_count"]
    assert preview["traceability"] == preview["control_summary"]["traceability"]


def test_agent_bundle_candidate_rejects_host_summary_that_says_loopora_not_fit(
    service_factory,
    tmp_path: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    (sample_workdir / "AGENTS.md").write_text("Project rules.\n", encoding="utf-8")
    (sample_workdir / "design").mkdir(exist_ok=True)
    (sample_workdir / "design" / "README.md").write_text("# Design\n", encoding="utf-8")
    (sample_workdir / "tests").mkdir(exist_ok=True)
    bundle_file = tmp_path / "bundle.yml"
    bundle_file.write_text(alignment_bundle_yaml(str(sample_workdir.resolve())), encoding="utf-8")

    generated = service.create_agent_bundle_candidate(
        AgentBundleCandidateRequest(
            adapter="codex",
            workdir=sample_workdir,
            message=(
                "Fix a README typo. One Agent pass plus one human review is enough, "
                "and later rounds will create no new evidence."
            ),
            bundle_file=bundle_file,
            entry_source="codex_project_skill",
        )
    )

    assert generated["ready"] is False
    assert generated["status"] == "failed"
    assert "Loopora is not fit" in generated["session"]["error_message"]
    assert any(
        event["event_type"] == "alignment_bundle_sync_failed"
        and "Loopora is not fit" in event["payload"].get("error", "")
        for event in service.list_alignment_events(generated["session"]["id"])
    )


def test_agent_bundle_candidate_rejects_chinese_host_summary_that_says_loopora_not_fit(
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
            message="修一个 README 错字。一次 Agent 执行加人工 review 已经足够，后续不会产生新证据。",
            bundle_file=bundle_file,
            entry_source="codex_project_skill",
        )
    )

    assert generated["ready"] is False
    assert generated["status"] == "failed"
    assert generated["requires_candidate_repair"] is True
    assert "Loopora is not fit" in generated["session"]["error_message"]


def test_agent_bundle_candidate_rejects_chinese_benchmark_only_host_summary(
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
            message="现有基准已经完全覆盖这次判断，直接跑基准就够了，不需要 Loopora。",
            bundle_file=bundle_file,
            entry_source="codex_project_skill",
        )
    )

    assert generated["ready"] is False
    assert generated["status"] == "failed"
    assert generated["requires_candidate_repair"] is True
    assert "Loopora is not fit" in generated["session"]["error_message"]


def test_agent_bundle_candidate_rejects_chinese_no_loop_host_summary(
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
            message="不用 Loopora，直接让 Agent 做完再人工看一眼就行。",
            bundle_file=bundle_file,
            entry_source="codex_project_skill",
        )
    )

    assert generated["ready"] is False
    assert generated["status"] == "failed"
    assert generated["requires_candidate_repair"] is True
    assert "Loopora is not fit" in generated["session"]["error_message"]


def test_agent_bundle_candidate_rejects_chinese_single_round_host_summary(
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
            message="这个任务跑一遍就行，不需要多轮，之后我人工确认即可。",
            bundle_file=bundle_file,
            entry_source="codex_project_skill",
        )
    )

    assert generated["ready"] is False
    assert generated["status"] == "failed"
    assert generated["requires_candidate_repair"] is True
    assert "Loopora is not fit" in generated["session"]["error_message"]


@pytest.mark.parametrize(
    "message",
    [
        "这是一次性任务，不要长期循环。直接处理完即可。",
        "This is a one-off task; no Loopora loop is needed.",
        "There is no need for a Loopora loop here; just answer directly.",
        "A direct answer is enough; no future iteration will add proof.",
        "Just fix it once and I will review it manually.",
        "The stable proof harness already fully captures the judgment.",
        "现有契约测试已经完全覆盖这次判断，直接跑测试就够了。",
    ],
)
def test_agent_bundle_candidate_rejects_one_off_host_summary_variants(
    service_factory,
    tmp_path: Path,
    sample_workdir: Path,
    message: str,
) -> None:
    service = service_factory(scenario="success")
    bundle_file = tmp_path / "bundle.yml"
    bundle_file.write_text(alignment_bundle_yaml(str(sample_workdir.resolve())), encoding="utf-8")

    generated = service.create_agent_bundle_candidate(
        AgentBundleCandidateRequest(
            adapter="codex",
            workdir=sample_workdir,
            message=message,
            bundle_file=bundle_file,
            entry_source="codex_project_skill",
        )
    )

    assert generated["ready"] is False
    assert generated["status"] == "failed"
    assert generated["requires_candidate_repair"] is True
    assert generated["loopora_fit_contradiction"] is True
    assert generated["binding"]["loopora_fit_contradiction"] is True
    assert "Loopora is not fit" in generated["session"]["error_message"]
    candidate_event = next(
        event for event in service.list_alignment_events(generated["session"]["id"]) if event["event_type"] == "agent_candidate_received"
    )
    assert candidate_event["payload"]["loopora_fit_contradiction"] is True


def test_agent_bundle_candidate_rejects_governance_markers_without_runtime_responsibilities(
    service_factory,
    tmp_path: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    bundle = yaml.safe_load(alignment_bundle_yaml(str(sample_workdir.resolve())))
    bundle["collaboration_summary"] += " AGENTS.md, design/README.md, design/, and tests/ are project-local governance markers."
    bundle_file = tmp_path / "bundle.yml"
    bundle_file.write_text(yaml.safe_dump(bundle, sort_keys=False, allow_unicode=True), encoding="utf-8")

    generated = service.create_agent_bundle_candidate(
        AgentBundleCandidateRequest(
            adapter="codex",
            workdir=sample_workdir,
            message=(
                "Build the focused starter experience while following AGENTS.md, design/README.md, design/, "
                "and tests/ as runtime governance inputs."
            ),
            bundle_file=bundle_file,
            entry_source="codex_project_skill",
        )
    )

    assert generated["ready"] is False
    assert generated["status"] == "failed"
    assert "project-local governance markers" in generated["session"]["error_message"]
    assert "Builder reading" in generated["session"]["error_message"]


def test_agent_bundle_candidate_uses_workdir_snapshot_for_governance_markers(
    service_factory,
    tmp_path: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    bundle_file = tmp_path / "bundle.yml"
    bundle_file.write_text(alignment_bundle_yaml(str(sample_workdir.resolve())), encoding="utf-8")
    (sample_workdir / "AGENTS.md").write_text("Project rules.\n", encoding="utf-8")
    (sample_workdir / "design").mkdir(exist_ok=True)
    (sample_workdir / "design" / "README.md").write_text("# Design\n", encoding="utf-8")
    (sample_workdir / "tests").mkdir(exist_ok=True)

    generated = service.create_agent_bundle_candidate(
        AgentBundleCandidateRequest(
            adapter="codex",
            workdir=sample_workdir,
            message=(
                "Build the focused starter experience in the target workdir with small, maintainable changes "
                "that preserve the primary user flow."
            ),
            bundle_file=bundle_file,
            entry_source="codex_project_skill",
        )
    )

    assert generated["ready"] is False
    assert generated["status"] == "failed"
    assert "project-local governance markers" in generated["session"]["error_message"]


def test_agent_bundle_candidate_uses_parent_agents_file_as_governance_marker(
    service_factory,
    tmp_path: Path,
) -> None:
    service = service_factory(scenario="success")
    project = tmp_path / "project"
    workdir = project / "packages" / "app"
    workdir.mkdir(parents=True)
    (project / ".git").mkdir()
    (project / "AGENTS.md").write_text("Project rules.\n", encoding="utf-8")
    bundle_file = tmp_path / "bundle.yml"
    bundle_file.write_text(alignment_bundle_yaml(str(workdir.resolve())), encoding="utf-8")

    generated = service.create_agent_bundle_candidate(
        AgentBundleCandidateRequest(
            adapter="codex",
            workdir=workdir,
            message=(
                "Build the focused starter experience in the target workdir with small, maintainable changes "
                "that preserve the primary user flow."
            ),
            bundle_file=bundle_file,
            entry_source="codex_project_skill",
        )
    )

    assert generated["ready"] is False
    assert generated["status"] == "failed"
    assert "project-local governance markers" in generated["session"]["error_message"]


def test_agent_bundle_candidate_accepts_governance_markers_as_role_responsibilities(
    service_factory,
    tmp_path: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    bundle = yaml.safe_load(alignment_bundle_yaml(str(sample_workdir.resolve())))
    role_by_key = {role["key"]: role for role in bundle["role_definitions"]}
    role_by_key["builder"]["prompt_markdown"] += (
        "\n\nRead AGENTS.md, design/README.md, design/, and tests/ before changing code, "
        "and follow those project-local governance contracts in the Builder handoff."
    )
    role_by_key["contract-inspector"]["prompt_markdown"] += (
        "\n\nInspector must verify AGENTS.md, design/README.md, design/, and tests/ were followed, "
        "and must mark skipped local governance as weak or missing evidence."
    )
    role_by_key["gatekeeper"]["prompt_markdown"] += (
        "\n\nGateKeeper treats skipped AGENTS.md, design/README.md, design/, or tests/ responsibilities "
        "as Weak, Unproven, or Blocking before accepting the run."
    )
    bundle_file = tmp_path / "bundle.yml"
    bundle_file.write_text(yaml.safe_dump(bundle, sort_keys=False, allow_unicode=True), encoding="utf-8")

    generated = service.create_agent_bundle_candidate(
        AgentBundleCandidateRequest(
            adapter="codex",
            workdir=sample_workdir,
            message=(
                "Build the focused starter experience while following AGENTS.md, design/README.md, design/, "
                "and tests/ as runtime governance inputs."
            ),
            bundle_file=bundle_file,
            entry_source="codex_project_skill",
        )
    )

    assert generated["ready"] is True
    assert generated["status"] == "ready"


def test_agent_bundle_candidate_rejects_residual_risk_policy_missing_owner_path(
    service_factory,
    tmp_path: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    bundle = yaml.safe_load(alignment_bundle_yaml(str(sample_workdir.resolve())))
    bundle["spec"]["markdown"] = bundle["spec"]["markdown"].replace(
        "Accept minor polish gaps only when they are explicitly named and tracked as an owned follow-up; fail closed on unproven primary-flow behavior or weak verification evidence.",
        "Accept manual billing export as residual risk only when explicitly named; fail closed on unproven primary-flow behavior or weak verification evidence.",
    )
    bundle_file = tmp_path / "bundle.yml"
    bundle_file.write_text(yaml.safe_dump(bundle, sort_keys=False, allow_unicode=True), encoding="utf-8")

    generated = service.create_agent_bundle_candidate(
        AgentBundleCandidateRequest(
            adapter="codex",
            workdir=sample_workdir,
            message=(
                "Accept manual billing export as a residual risk only when Support owns the follow-up; "
                "unverified primary flow must fail closed."
            ),
            bundle_file=bundle_file,
            entry_source="codex_project_skill",
        )
    )

    assert generated["ready"] is False
    assert generated["status"] == "failed"
    assert "residual-risk policy" in generated["session"]["error_message"]
    assert "owner/follow-up" in generated["session"]["error_message"]


def test_agent_bundle_candidate_rejects_chinese_residual_risk_missing_owner_path(
    service_factory,
    tmp_path: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    bundle = yaml.safe_load(alignment_bundle_yaml(str(sample_workdir.resolve())))
    bundle["spec"]["markdown"] = bundle["spec"]["markdown"].replace(
        "Accept minor polish gaps only when they are explicitly named and tracked as an owned follow-up; fail closed on unproven primary-flow behavior or weak verification evidence.",
        "Accept manual billing export as residual risk only when explicitly named; fail closed on unproven primary-flow behavior or weak verification evidence.",
    )
    bundle_file = tmp_path / "bundle.yml"
    bundle_file.write_text(yaml.safe_dump(bundle, sort_keys=False, allow_unicode=True), encoding="utf-8")

    generated = service.create_agent_bundle_candidate(
        AgentBundleCandidateRequest(
            adapter="codex",
            workdir=sample_workdir,
            message="残余风险：手动账单导出只有客服负责人跟进工单时才可接受；未验证主流程必须失败关闭。",
            bundle_file=bundle_file,
            entry_source="codex_project_skill",
        )
    )

    assert generated["ready"] is False
    assert generated["status"] == "failed"
    assert "residual-risk policy" in generated["session"]["error_message"]
    assert "owner/follow-up" in generated["session"]["error_message"]


def test_agent_bundle_candidate_accepts_residual_risk_policy_in_runtime_surfaces(
    service_factory,
    tmp_path: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    bundle = yaml.safe_load(alignment_bundle_yaml(str(sample_workdir.resolve())))
    bundle["spec"]["markdown"] = bundle["spec"]["markdown"].replace(
        "Accept minor polish gaps only when they are explicitly named and tracked as an owned follow-up; fail closed on unproven primary-flow behavior or weak verification evidence.",
        (
            "Accept manual billing export as residual risk only when Support owns the follow-up; "
            "fail closed on unproven primary-flow behavior or weak verification evidence."
        ),
    )
    role_by_key = {role["key"]: role for role in bundle["role_definitions"]}
    role_by_key["gatekeeper"]["posture_notes"] += (
        " Confirm Support owns the manual billing export follow-up before accepting it as residual risk."
    )
    bundle_file = tmp_path / "bundle.yml"
    bundle_file.write_text(yaml.safe_dump(bundle, sort_keys=False, allow_unicode=True), encoding="utf-8")

    generated = service.create_agent_bundle_candidate(
        AgentBundleCandidateRequest(
            adapter="codex",
            workdir=sample_workdir,
            message=(
                "Accept manual billing export as a residual risk only when Support owns the follow-up; "
                "unverified primary flow must fail closed."
            ),
            bundle_file=bundle_file,
            entry_source="codex_project_skill",
        )
    )

    assert generated["ready"] is True
    assert generated["status"] == "ready"


def test_agent_bundle_candidate_rejects_no_accepted_residual_risk_policy_relaxed_in_bundle(
    service_factory,
    tmp_path: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    bundle = yaml.safe_load(alignment_bundle_yaml(str(sample_workdir.resolve())))
    bundle["spec"]["markdown"] = bundle["spec"]["markdown"].replace(
        "Accept minor polish gaps only when they are explicitly named and tracked as an owned follow-up; fail closed on unproven primary-flow behavior or weak verification evidence.",
        "Accept unproven billing export as residual risk when explicitly named; fail closed on weak verification evidence.",
    )
    bundle_file = tmp_path / "bundle.yml"
    bundle_file.write_text(yaml.safe_dump(bundle, sort_keys=False, allow_unicode=True), encoding="utf-8")

    generated = service.create_agent_bundle_candidate(
        AgentBundleCandidateRequest(
            adapter="codex",
            workdir=sample_workdir,
            message="No residual risk is acceptable; unproven billing export must fail closed.",
            bundle_file=bundle_file,
            entry_source="codex_project_skill",
        )
    )

    assert generated["ready"] is False
    assert generated["status"] == "failed"
    assert "residual-risk policy" in generated["session"]["error_message"]
    assert "no-accepted-residual-risk" in generated["session"]["error_message"]


def test_agent_bundle_candidate_rejects_explicit_success_criteria_missing_from_runtime_surfaces(
    service_factory,
    tmp_path: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    bundle = yaml.safe_load(alignment_bundle_yaml(str(sample_workdir.resolve())))
    bundle["spec"]["markdown"] = bundle["spec"]["markdown"].replace(
        "Ship the focused starter experience in the target workdir with small, maintainable changes that preserve the primary user flow.",
        "Ship the refund approval path so Support admin can approve a refund and audit log records the actor.",
    )
    bundle_file = tmp_path / "bundle.yml"
    bundle_file.write_text(yaml.safe_dump(bundle, sort_keys=False, allow_unicode=True), encoding="utf-8")

    generated = service.create_agent_bundle_candidate(
        AgentBundleCandidateRequest(
            adapter="codex",
            workdir=sample_workdir,
            message=(
                "Success means Support admin can approve a refund, audit log records the actor, "
                "and customer receives an email notification."
            ),
            bundle_file=bundle_file,
            entry_source="codex_project_skill",
        )
    )

    assert generated["ready"] is False
    assert generated["status"] == "failed"
    assert "success criteria" in generated["session"]["error_message"]
    assert "notification/message" in generated["session"]["error_message"]


def test_agent_bundle_candidate_rejects_chinese_success_criteria_missing_from_runtime_surfaces(
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
            message="成功标准：客服可以批准退款，审计日志记录操作者，并且客户收到通知邮件。",
            bundle_file=bundle_file,
            entry_source="codex_project_skill",
        )
    )

    assert generated["ready"] is False
    assert generated["status"] == "failed"
    assert "success criteria" in generated["session"]["error_message"]
    assert "notification/message" in generated["session"]["error_message"]
    assert "退款" in generated["session"]["error_message"]


def test_agent_bundle_candidate_accepts_explicit_success_criteria_in_runtime_surfaces(
    service_factory,
    tmp_path: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    bundle = yaml.safe_load(alignment_bundle_yaml(str(sample_workdir.resolve())))
    bundle["spec"]["markdown"] = bundle["spec"]["markdown"].replace(
        "Ship the focused starter experience in the target workdir with small, maintainable changes that preserve the primary user flow.",
        (
            "Ship the refund approval path so Support admin can approve a refund, audit log records the actor, "
            "and the customer receives an email notification."
        ),
    )
    bundle["workflow"]["collaboration_intent"] += (
        " GateKeeper must verify the refund approval, audit log record, and customer email notification before finishing."
    )
    bundle_file = tmp_path / "bundle.yml"
    bundle_file.write_text(yaml.safe_dump(bundle, sort_keys=False, allow_unicode=True), encoding="utf-8")

    generated = service.create_agent_bundle_candidate(
        AgentBundleCandidateRequest(
            adapter="codex",
            workdir=sample_workdir,
            message=(
                "Success means Support admin can approve a refund, audit log records the actor, "
                "and customer receives an email notification."
            ),
            bundle_file=bundle_file,
            entry_source="codex_project_skill",
        )
    )

    assert generated["ready"] is True
    assert generated["status"] == "ready"


def test_agent_bundle_candidate_rejects_accessibility_and_locale_success_criteria_missing_from_runtime_surfaces(
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
            message=(
                "Success means keyboard users can complete checkout, screen reader labels are available, "
                "and Chinese and English variants preserve the same action."
            ),
            bundle_file=bundle_file,
            entry_source="codex_project_skill",
        )
    )

    assert generated["ready"] is False
    assert generated["status"] == "failed"
    assert "success criteria" in generated["session"]["error_message"]
    assert "accessibility/a11y" in generated["session"]["error_message"]
    assert "locale/i18n" in generated["session"]["error_message"]


def test_agent_bundle_candidate_accepts_accessibility_and_locale_success_criteria_in_runtime_surfaces(
    service_factory,
    tmp_path: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    bundle = yaml.safe_load(alignment_bundle_yaml(str(sample_workdir.resolve())))
    bundle["spec"]["markdown"] = bundle["spec"]["markdown"].replace(
        "Ship the focused starter experience in the target workdir with small, maintainable changes that preserve the primary user flow.",
        (
            "Ship the checkout path so keyboard users can complete checkout, screen reader labels are available, "
            "and Chinese and English variants preserve the same action."
        ),
    )
    bundle["workflow"]["collaboration_intent"] += (
        " Inspector verifies keyboard access, screen reader labels, and Chinese and English action parity before GateKeeper closes."
    )
    bundle_file = tmp_path / "bundle.yml"
    bundle_file.write_text(yaml.safe_dump(bundle, sort_keys=False, allow_unicode=True), encoding="utf-8")

    generated = service.create_agent_bundle_candidate(
        AgentBundleCandidateRequest(
            adapter="codex",
            workdir=sample_workdir,
            message=(
                "Success means keyboard users can complete checkout, screen reader labels are available, "
                "and Chinese and English variants preserve the same action."
            ),
            bundle_file=bundle_file,
            entry_source="codex_project_skill",
        )
    )

    assert generated["ready"] is True
    assert generated["status"] == "ready"


def test_agent_bundle_candidate_rejects_explicit_fake_done_risk_missing_from_runtime_surfaces(
    service_factory,
    tmp_path: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    bundle = yaml.safe_load(alignment_bundle_yaml(str(sample_workdir.resolve())))
    bundle["spec"]["markdown"] = bundle["spec"]["markdown"].replace(
        "Ship the focused starter experience in the target workdir with small, maintainable changes that preserve the primary user flow.",
        "Ship the billing export in the target workdir with small, maintainable changes that preserve the primary user flow.",
    )
    bundle_file = tmp_path / "bundle.yml"
    bundle_file.write_text(yaml.safe_dump(bundle, sort_keys=False, allow_unicode=True), encoding="utf-8")

    generated = service.create_agent_bundle_candidate(
        AgentBundleCandidateRequest(
            adapter="codex",
            workdir=sample_workdir,
            message=(
                "Build the billing export. Fake done is a CSV download that omits permission audit; "
                "do not pass until permission audit proof exists."
            ),
            bundle_file=bundle_file,
            entry_source="codex_project_skill",
        )
    )

    assert generated["ready"] is False
    assert generated["status"] == "failed"
    assert "fake-done risks" in generated["session"]["error_message"]
    assert "permission/audit" in generated["session"]["error_message"]


def test_agent_bundle_candidate_accepts_explicit_fake_done_risk_in_runtime_surfaces(
    service_factory,
    tmp_path: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    bundle = yaml.safe_load(alignment_bundle_yaml(str(sample_workdir.resolve())))
    bundle["spec"]["markdown"] = bundle["spec"]["markdown"].replace(
        "Ship the focused starter experience in the target workdir with small, maintainable changes that preserve the primary user flow.",
        "Ship the billing export in the target workdir with small, maintainable changes that preserve the primary user flow.",
    )
    bundle["spec"]["markdown"] += (
        "\n\nFake Done: A CSV download that omits permission audit is not done; "
        "GateKeeper must block until permission audit proof exists."
    )
    role_by_key = {role["key"]: role for role in bundle["role_definitions"]}
    role_by_key["gatekeeper"]["posture_notes"] += (
        " Treat any billing CSV download without permission audit proof as fake done."
    )
    bundle_file = tmp_path / "bundle.yml"
    bundle_file.write_text(yaml.safe_dump(bundle, sort_keys=False, allow_unicode=True), encoding="utf-8")

    generated = service.create_agent_bundle_candidate(
        AgentBundleCandidateRequest(
            adapter="codex",
            workdir=sample_workdir,
            message=(
                "Build the billing export. Fake done is a CSV download that omits permission audit; "
                "do not pass until permission audit proof exists."
            ),
            bundle_file=bundle_file,
            entry_source="codex_project_skill",
        )
    )

    assert generated["ready"] is True
    assert generated["status"] == "ready"


def test_agent_bundle_candidate_rejects_payment_fake_done_missing_from_runtime_surfaces(
    service_factory,
    tmp_path: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    bundle = yaml.safe_load(alignment_bundle_yaml(str(sample_workdir.resolve())))
    bundle["spec"]["markdown"] = bundle["spec"]["markdown"].replace(
        "Ship the focused starter experience in the target workdir with small, maintainable changes that preserve the primary user flow.",
        "Ship the refund payment path in the target workdir with small, maintainable changes.",
    )
    bundle_file = tmp_path / "bundle.yml"
    bundle_file.write_text(yaml.safe_dump(bundle, sort_keys=False, allow_unicode=True), encoding="utf-8")

    generated = service.create_agent_bundle_candidate(
        AgentBundleCandidateRequest(
            adapter="codex",
            workdir=sample_workdir,
            message=(
                "Build the refund payment path. Fake done is marking refund success without "
                "payment-provider failure replay or billing ledger proof."
            ),
            bundle_file=bundle_file,
            entry_source="codex_project_skill",
        )
    )

    assert generated["ready"] is False
    assert generated["status"] == "failed"
    assert "fake-done risks" in generated["session"]["error_message"]
    assert "payment/refund/billing" in generated["session"]["error_message"]


def test_agent_bundle_candidate_accepts_payment_fake_done_in_runtime_surfaces(
    service_factory,
    tmp_path: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    bundle = yaml.safe_load(alignment_bundle_yaml(str(sample_workdir.resolve())))
    bundle["spec"]["markdown"] = bundle["spec"]["markdown"].replace(
        "Ship the focused starter experience in the target workdir with small, maintainable changes that preserve the primary user flow.",
        "Ship the refund payment path in the target workdir with small, maintainable changes.",
    )
    bundle["spec"]["markdown"] += (
        "\n\nFake Done: Marking refund success without payment-provider failure replay "
        "or billing ledger proof is fake done."
    )
    role_by_key = {role["key"]: role for role in bundle["role_definitions"]}
    role_by_key["gatekeeper"]["posture_notes"] += (
        " Treat any refund success without payment failure replay and billing ledger proof as fake done."
    )
    bundle_file = tmp_path / "bundle.yml"
    bundle_file.write_text(yaml.safe_dump(bundle, sort_keys=False, allow_unicode=True), encoding="utf-8")

    generated = service.create_agent_bundle_candidate(
        AgentBundleCandidateRequest(
            adapter="codex",
            workdir=sample_workdir,
            message=(
                "Build the refund payment path. Fake done is marking refund success without "
                "payment-provider failure replay or billing ledger proof."
            ),
            bundle_file=bundle_file,
            entry_source="codex_project_skill",
        )
    )

    assert generated["ready"] is True
    assert generated["status"] == "ready"


def test_agent_bundle_candidate_rejects_accessibility_and_locale_fake_done_risk_missing_from_runtime_surfaces(
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
            message=(
                "Build checkout. Fake done is an English-only flow that looks complete but has no keyboard "
                "or screen reader proof."
            ),
            bundle_file=bundle_file,
            entry_source="codex_project_skill",
        )
    )

    assert generated["ready"] is False
    assert generated["status"] == "failed"
    assert "fake-done risks" in generated["session"]["error_message"]
    assert "accessibility/i18n" in generated["session"]["error_message"]


def test_agent_bundle_candidate_rejects_explicit_evidence_preferences_missing_from_runtime_surfaces(
    service_factory,
    tmp_path: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    bundle = yaml.safe_load(alignment_bundle_yaml(str(sample_workdir.resolve())))
    bundle["spec"]["markdown"] = bundle["spec"]["markdown"].replace(
        "Ship the focused starter experience in the target workdir with small, maintainable changes that preserve the primary user flow.",
        "Ship the checkout instrumentation in the target workdir with small, maintainable changes.",
    )
    bundle_file = tmp_path / "bundle.yml"
    bundle_file.write_text(yaml.safe_dump(bundle, sort_keys=False, allow_unicode=True), encoding="utf-8")

    generated = service.create_agent_bundle_candidate(
        AgentBundleCandidateRequest(
            adapter="codex",
            workdir=sample_workdir,
            message=(
                "Build checkout instrumentation. Evidence must include a browser journey and audit log command output "
                "before GateKeeper can pass."
            ),
            bundle_file=bundle_file,
            entry_source="codex_project_skill",
        )
    )

    assert generated["ready"] is False
    assert generated["status"] == "failed"
    assert "evidence preferences" in generated["session"]["error_message"]
    assert "audit/log" in generated["session"]["error_message"]


def test_agent_bundle_candidate_accepts_explicit_evidence_preferences_in_runtime_surfaces(
    service_factory,
    tmp_path: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    bundle = yaml.safe_load(alignment_bundle_yaml(str(sample_workdir.resolve())))
    bundle["spec"]["markdown"] = bundle["spec"]["markdown"].replace(
        "Ship the focused starter experience in the target workdir with small, maintainable changes that preserve the primary user flow.",
        "Ship the checkout instrumentation in the target workdir with small, maintainable changes.",
    )
    bundle["spec"]["markdown"] += (
        "\n\nEvidence Preference: Require a browser journey plus audit log command output before GateKeeper can pass."
    )
    role_by_key = {role["key"]: role for role in bundle["role_definitions"]}
    role_by_key["evidence-inspector"]["prompt_markdown"] += (
        "\n\nCollect browser journey evidence and audit log command output for checkout instrumentation."
    )
    role_by_key["gatekeeper"]["posture_notes"] += (
        " Pass only with browser journey proof and audit log command evidence."
    )
    bundle_file = tmp_path / "bundle.yml"
    bundle_file.write_text(yaml.safe_dump(bundle, sort_keys=False, allow_unicode=True), encoding="utf-8")

    generated = service.create_agent_bundle_candidate(
        AgentBundleCandidateRequest(
            adapter="codex",
            workdir=sample_workdir,
            message=(
                "Build checkout instrumentation. Evidence must include a browser journey and audit log command output "
                "before GateKeeper can pass."
            ),
            bundle_file=bundle_file,
            entry_source="codex_project_skill",
        )
    )

    assert generated["ready"] is True
    assert generated["status"] == "ready"


def test_agent_bundle_candidate_rejects_payment_evidence_preferences_missing_from_runtime_surfaces(
    service_factory,
    tmp_path: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    bundle = yaml.safe_load(alignment_bundle_yaml(str(sample_workdir.resolve())))
    bundle_file = tmp_path / "bundle.yml"
    bundle_file.write_text(yaml.safe_dump(bundle, sort_keys=False, allow_unicode=True), encoding="utf-8")

    generated = service.create_agent_bundle_candidate(
        AgentBundleCandidateRequest(
            adapter="codex",
            workdir=sample_workdir,
            message=(
                "Build the refund payment flow. Evidence must include payment-provider failure replay "
                "and billing ledger command output before GateKeeper can pass."
            ),
            bundle_file=bundle_file,
            entry_source="codex_project_skill",
        )
    )

    assert generated["ready"] is False
    assert generated["status"] == "failed"
    assert "evidence preferences" in generated["session"]["error_message"]
    assert "payment/refund/billing" in generated["session"]["error_message"]


def test_agent_bundle_candidate_accepts_payment_evidence_preferences_in_runtime_surfaces(
    service_factory,
    tmp_path: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    bundle = yaml.safe_load(alignment_bundle_yaml(str(sample_workdir.resolve())))
    bundle["spec"]["markdown"] = bundle["spec"]["markdown"].replace(
        "Ship the focused starter experience in the target workdir with small, maintainable changes that preserve the primary user flow.",
        "Ship the refund payment flow in the target workdir with small, maintainable changes.",
    )
    bundle["spec"]["markdown"] += (
        "\n\nEvidence Preference: Require payment-provider failure replay and billing ledger command output before GateKeeper can pass."
    )
    role_by_key = {role["key"]: role for role in bundle["role_definitions"]}
    role_by_key["evidence-inspector"]["prompt_markdown"] += (
        "\n\nCollect payment-provider failure replay evidence and billing ledger command output."
    )
    role_by_key["gatekeeper"]["posture_notes"] += (
        " Pass only with payment failure replay proof and billing ledger evidence."
    )
    bundle_file = tmp_path / "bundle.yml"
    bundle_file.write_text(yaml.safe_dump(bundle, sort_keys=False, allow_unicode=True), encoding="utf-8")

    generated = service.create_agent_bundle_candidate(
        AgentBundleCandidateRequest(
            adapter="codex",
            workdir=sample_workdir,
            message=(
                "Build the refund payment flow. Evidence must include payment-provider failure replay "
                "and billing ledger command output before GateKeeper can pass."
            ),
            bundle_file=bundle_file,
            entry_source="codex_project_skill",
        )
    )

    assert generated["ready"] is True
    assert generated["status"] == "ready"


def test_agent_bundle_candidate_rejects_accessibility_and_locale_evidence_preferences_missing_from_runtime_surfaces(
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
            message=(
                "Build checkout. Evidence must include keyboard navigation proof, a screen reader label check, "
                "and Chinese and English locale verification before GateKeeper can pass."
            ),
            bundle_file=bundle_file,
            entry_source="codex_project_skill",
        )
    )

    assert generated["ready"] is False
    assert generated["status"] == "failed"
    assert "evidence preferences" in generated["session"]["error_message"]
    assert "accessibility/a11y" in generated["session"]["error_message"]
    assert "locale/i18n" in generated["session"]["error_message"]


def test_agent_bundle_candidate_rejects_explicit_tradeoff_missing_from_runtime_surfaces(
    service_factory,
    tmp_path: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    bundle = yaml.safe_load(alignment_bundle_yaml(str(sample_workdir.resolve())))
    bundle["collaboration_summary"] = bundle["collaboration_summary"].replace(
        "Prefer a smaller proven flow over polished but unproven breadth, and let GateKeeper reject speed or surface completeness when evidence is weak. ",
        "",
    )
    bundle["spec"]["markdown"] = bundle["spec"]["markdown"].replace("Accept minor polish gaps", "Accept minor follow-up gaps")
    bundle_file = tmp_path / "bundle.yml"
    bundle_file.write_text(yaml.safe_dump(bundle, sort_keys=False, allow_unicode=True), encoding="utf-8")

    generated = service.create_agent_bundle_candidate(
        AgentBundleCandidateRequest(
            adapter="codex",
            workdir=sample_workdir,
            message=(
                "Prioritize proof over speed: block polished-looking fake completion until evidence proves "
                "the primary flow."
            ),
            bundle_file=bundle_file,
            entry_source="codex_project_skill",
        )
    )

    assert generated["ready"] is False
    assert generated["status"] == "failed"
    assert "judgment tradeoffs" in generated["session"]["error_message"]
    assert "speed/polish" in generated["session"]["error_message"]


def test_agent_bundle_candidate_accepts_explicit_tradeoff_in_runtime_surfaces(
    service_factory,
    tmp_path: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    bundle = yaml.safe_load(alignment_bundle_yaml(str(sample_workdir.resolve())))
    bundle["spec"]["markdown"] += (
        "\n\nTradeoff: prioritize proof over speed; UI polish must wait until primary-flow evidence is Proven."
    )
    bundle["workflow"]["collaboration_intent"] += (
        " GateKeeper should block polished-looking fake completion when proof is weak."
    )
    role_by_key = {role["key"]: role for role in bundle["role_definitions"]}
    role_by_key["gatekeeper"]["posture_notes"] += (
        " Reject speed-first or polish-first closure unless direct evidence proves the primary flow."
    )
    bundle_file = tmp_path / "bundle.yml"
    bundle_file.write_text(yaml.safe_dump(bundle, sort_keys=False, allow_unicode=True), encoding="utf-8")

    generated = service.create_agent_bundle_candidate(
        AgentBundleCandidateRequest(
            adapter="codex",
            workdir=sample_workdir,
            message=(
                "Prioritize proof over speed: block polished-looking fake completion until evidence proves "
                "the primary flow."
            ),
            bundle_file=bundle_file,
            entry_source="codex_project_skill",
        )
    )

    assert generated["ready"] is True
    assert generated["status"] == "ready"


def test_agent_bundle_candidate_rejects_pragmatic_progress_tradeoff_missing_from_runtime_surfaces(
    service_factory,
    tmp_path: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    bundle = yaml.safe_load(alignment_bundle_yaml(str(sample_workdir.resolve())))
    bundle_file = tmp_path / "bundle.yml"
    bundle_file.write_text(yaml.safe_dump(bundle, sort_keys=False, allow_unicode=True), encoding="utf-8")

    generated = service.create_agent_bundle_candidate(
        AgentBundleCandidateRequest(
            adapter="codex",
            workdir=sample_workdir,
            message="Prefer strict blocking over pragmatic progress when evidence is weak.",
            bundle_file=bundle_file,
            entry_source="codex_project_skill",
        )
    )

    assert generated["ready"] is False
    assert generated["status"] == "failed"
    assert "judgment tradeoffs" in generated["session"]["error_message"]
    assert "pragmatic/progress" in generated["session"]["error_message"]


def test_agent_bundle_candidate_accepts_pragmatic_progress_tradeoff_in_runtime_surfaces(
    service_factory,
    tmp_path: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    bundle = yaml.safe_load(alignment_bundle_yaml(str(sample_workdir.resolve())))
    bundle["spec"]["markdown"] += "\n\nTradeoff: strict blocking beats pragmatic progress when evidence is weak."
    bundle_file = tmp_path / "bundle.yml"
    bundle_file.write_text(yaml.safe_dump(bundle, sort_keys=False, allow_unicode=True), encoding="utf-8")

    generated = service.create_agent_bundle_candidate(
        AgentBundleCandidateRequest(
            adapter="codex",
            workdir=sample_workdir,
            message="Prefer strict blocking over pragmatic progress when evidence is weak.",
            bundle_file=bundle_file,
            entry_source="codex_project_skill",
        )
    )

    assert generated["ready"] is True
    assert generated["status"] == "ready"


def test_agent_bundle_candidate_rejects_explicit_execution_strategy_missing_from_runtime_surfaces(
    service_factory,
    tmp_path: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    bundle = yaml.safe_load(alignment_bundle_yaml(str(sample_workdir.resolve())))
    bundle["spec"]["markdown"] = bundle["spec"]["markdown"].replace(
        "Ship the focused starter experience in the target workdir with small, maintainable changes that preserve the primary user flow.",
        "Ship the billing refund path in the target workdir with small, maintainable changes.",
    )
    bundle_file = tmp_path / "bundle.yml"
    bundle_file.write_text(yaml.safe_dump(bundle, sort_keys=False, allow_unicode=True), encoding="utf-8")

    generated = service.create_agent_bundle_candidate(
        AgentBundleCandidateRequest(
            adapter="codex",
            workdir=sample_workdir,
            message=(
                "Ship the billing refund path. Execution strategy: first repair the root cause before "
                "expanding dashboards or polishing UI."
            ),
            bundle_file=bundle_file,
            entry_source="codex_project_skill",
        )
    )

    assert generated["ready"] is False
    assert generated["status"] == "failed"
    assert "execution strategy" in generated["session"]["error_message"]
    assert "repair/root-cause" in generated["session"]["error_message"]


def test_agent_bundle_candidate_rejects_labeled_single_execution_strategy_missing_from_runtime_surfaces(
    service_factory,
    tmp_path: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    bundle = yaml.safe_load(alignment_bundle_yaml(str(sample_workdir.resolve())))
    bundle["spec"]["markdown"] = bundle["spec"]["markdown"].replace(
        "Ship the focused starter experience in the target workdir with small, maintainable changes that preserve the primary user flow.",
        "Ship the billing refund path in the target workdir with small, maintainable changes.",
    )
    bundle_file = tmp_path / "bundle.yml"
    bundle_file.write_text(yaml.safe_dump(bundle, sort_keys=False, allow_unicode=True), encoding="utf-8")

    generated = service.create_agent_bundle_candidate(
        AgentBundleCandidateRequest(
            adapter="codex",
            workdir=sample_workdir,
            message="Ship the billing refund path. Execution strategy: first repair the root cause.",
            bundle_file=bundle_file,
            entry_source="codex_project_skill",
        )
    )

    assert generated["ready"] is False
    assert generated["status"] == "failed"
    assert "execution strategy" in generated["session"]["error_message"]
    assert "repair/root-cause" in generated["session"]["error_message"]


def test_agent_bundle_candidate_accepts_explicit_execution_strategy_in_runtime_surfaces(
    service_factory,
    tmp_path: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    bundle = yaml.safe_load(alignment_bundle_yaml(str(sample_workdir.resolve())))
    bundle["spec"]["markdown"] = bundle["spec"]["markdown"].replace(
        "Ship the focused starter experience in the target workdir with small, maintainable changes that preserve the primary user flow.",
        "Ship the billing refund path in the target workdir with small, maintainable changes.",
    )
    bundle["spec"]["markdown"] += (
        "\n\nExecution Strategy: first repair the root cause, then consider dashboard expansion or UI polish."
    )
    bundle["workflow"]["collaboration_intent"] += (
        " Builder should repair the root cause before any dashboard expansion or UI polish."
    )
    bundle_file = tmp_path / "bundle.yml"
    bundle_file.write_text(yaml.safe_dump(bundle, sort_keys=False, allow_unicode=True), encoding="utf-8")

    generated = service.create_agent_bundle_candidate(
        AgentBundleCandidateRequest(
            adapter="codex",
            workdir=sample_workdir,
            message=(
                "Ship the billing refund path. Execution strategy: first repair the root cause before "
                "expanding dashboards or polishing UI."
            ),
            bundle_file=bundle_file,
            entry_source="codex_project_skill",
        )
    )

    assert generated["ready"] is True
    assert generated["status"] == "ready"


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
    assert payload["candidate_origin"] == "agent_entry"
    assert payload["candidate_entry_source"] == "claude_project_skill"
    assert payload["ready"] is True
    assert payload["status"] == "ready"
    assert payload["host_context_id"] == "claude-session-a"
    assert payload["binding"]["context_source"] == "explicit"
    assert payload["binding"]["host_context_id"] == "claude-session-a"
    assert payload["binding"]["candidate_origin"] == "agent_entry"
    assert payload["binding"]["candidate_adapter"] == "claude"
    assert payload["binding"]["candidate_entry_source"] == "claude_project_skill"
    assert payload["binding"]["entry_invocations"][-1]["entry_source"] == "claude_project_skill"
    assert payload["preview_url"].startswith("/loops/new/bundle?alignment_session_id=")
    assert "run" not in payload


def test_agent_loop_after_web_imported_candidate_still_uses_agent_native(
    service_factory,
    monkeypatch,
    tmp_path: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    bundle_file = tmp_path / "bundle.yml"
    bundle_text = alignment_bundle_yaml(str(sample_workdir.resolve()))
    expected_sha, expected_bytes = _candidate_digest(bundle_text)
    expected_ready_sha, expected_ready_bytes = _ready_candidate_digest(bundle_text)
    bundle_file.write_text(bundle_text, encoding="utf-8")

    generated = service.create_agent_bundle_candidate(
        AgentBundleCandidateRequest(
            adapter="codex",
            workdir=sample_workdir,
            message="Prepare a governed implementation loop.",
            bundle_file=bundle_file,
            entry_source="codex_project_skill",
        )
    )
    assert generated["candidate_sha256"] == expected_sha
    assert generated["candidate_bytes"] == expected_bytes
    assert generated["ready_candidate_sha256"] == expected_ready_sha
    assert generated["ready_candidate_bytes"] == expected_ready_bytes
    assert generated["binding"]["ready_candidate_sha256"] == expected_ready_sha
    assert generated["binding"]["ready_candidate_bytes"] == expected_ready_bytes
    assert generated["session"]["agent_entry_launch"]["ready_candidate_sha256"] == expected_ready_sha
    assert generated["session"]["agent_entry_launch"]["ready_candidate_bytes"] == expected_ready_bytes
    candidate_event = next(
        event for event in service.list_alignment_events(generated["session"]["id"]) if event["event_type"] == "agent_candidate_received"
    )
    assert candidate_event["payload"]["candidate_sha256"] == expected_sha
    assert candidate_event["payload"]["candidate_bytes"] == expected_bytes
    ready_event = next(
        event for event in service.list_alignment_events(generated["session"]["id"]) if event["event_type"] == "agent_candidate_ready_content"
    )
    assert ready_event["payload"]["candidate_sha256"] == expected_sha
    assert ready_event["payload"]["candidate_bytes"] == expected_bytes
    assert ready_event["payload"]["ready_candidate_sha256"] == expected_ready_sha
    assert ready_event["payload"]["ready_candidate_bytes"] == expected_ready_bytes
    ready_path = Path(generated["session"]["bundle_path"])
    ready_bundle = yaml.safe_load(ready_path.read_text(encoding="utf-8"))
    ready_bundle["metadata"]["description"] = "Imported from the current reviewed file after a valid local edit."
    ready_path.write_text(yaml.safe_dump(ready_bundle, sort_keys=False, allow_unicode=True), encoding="utf-8")
    expected_import_sha, expected_import_bytes = _ready_candidate_digest(ready_path.read_text(encoding="utf-8"))
    assert expected_import_sha != expected_ready_sha
    imported = service.import_alignment_bundle(generated["session"]["id"], start_immediately=False)
    assert imported["session"]["status"] == "imported"
    assert imported["session"]["linked_loop_id"]
    assert not imported["session"].get("linked_run_id")

    def fail_nested_worker(run_id: str) -> None:
        raise AssertionError(f"Agent-first imported sessions must not start a headless worker for {run_id}")

    monkeypatch.setattr(service, "start_run_async", fail_nested_worker)

    started = service.start_agent_loop(
        "codex",
        workdir=sample_workdir,
        entry_source="codex_project_skill",
        execute_async=True,
    )

    assert started["execution_plane"] == "agent_native"
    assert started["started_new_run"] is True
    assert started["run"]["status"] == "awaiting_agent"
    assert started["binding"]["execution_plane"] == "agent_native"
    assert started["binding"]["linked_run_id"] == started["run"]["id"]
    assert started["binding"]["ready_candidate_sha256"] == expected_import_sha
    assert started["binding"]["ready_candidate_bytes"] == expected_import_bytes
    assert started["next_step"]["execution_plane"] == "agent_native"


def test_web_import_cannot_headless_start_agent_first_preview(
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
            message="Prepare a governed implementation loop.",
            bundle_file=bundle_file,
            entry_source="codex_project_skill",
        )
    )

    with pytest.raises(LooporaConflictError, match="agent-first Loop previews must be started from /loopora-loop"):
        service.import_alignment_bundle(generated["session"]["id"], start_immediately=True, execute_async=True)

    blocked_session = service.get_alignment_session(generated["session"]["id"])
    assert blocked_session["status"] == "ready"
    assert not blocked_session.get("linked_run_id")
    assert service.list_bundles() == []

    started = service.start_agent_loop(
        "codex",
        workdir=sample_workdir,
        entry_source="codex_project_skill",
        execute_async=True,
    )

    assert started["execution_plane"] == "agent_native"
    assert started["run"]["status"] == "awaiting_agent"
    assert started["next_step"]["execution_plane"] == "agent_native"
    assert (Path(started["run"]["runs_dir"]) / "agent_native" / "state.json").exists()


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
    assert payload["candidate_origin"] == "agent_entry"
    assert payload["candidate_entry_source"] == "opencode_project_command"
    assert payload["ready"] is True
    assert payload["status"] == "ready"
    assert payload["host_context_id"] == ""
    assert payload["binding"]["context_source"] == "workdir"
    assert payload["binding"]["host_context_id"] == ""
    assert payload["binding"]["candidate_origin"] == "agent_entry"
    assert payload["binding"]["candidate_adapter"] == "opencode"
    assert payload["binding"]["candidate_entry_source"] == "opencode_project_command"
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
    (sample_workdir / "AGENTS.md").write_text("Project rules.\n", encoding="utf-8")
    (sample_workdir / "design").mkdir(exist_ok=True)
    (sample_workdir / "design" / "README.md").write_text("# Design\n", encoding="utf-8")
    (sample_workdir / "tests").mkdir(exist_ok=True)
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
    assert started["judgment_contract"]["contract_path"] == "contract/run_contract.json"
    assert "Prefer a smaller proven flow" in started["judgment_contract"]["collaboration_summary"]
    assert started["judgment_contract"]["judgment_tradeoffs"]
    assert started["judgment_contract"]["execution_strategy"]
    assert started["judgment_contract"]["local_governance"]
    assert started["judgment_contract"]["role_postures"]
    assert started["judgment_contract"]["completion_mode"] == "gatekeeper"
    assert any(target["id"] == "done_when.check_001" for target in started["judgment_contract"]["coverage_targets"])
    source_bundle = started["judgment_contract"]["source_bundle"]
    exported_bundle_yaml = service.export_bundle_yaml(started["binding"]["linked_bundle_id"])
    exported_bundle_data = exported_bundle_yaml.encode("utf-8")
    assert source_bundle["id"] == started["binding"]["linked_bundle_id"]
    assert source_bundle["bundle_sha256"] == hashlib.sha256(exported_bundle_data).hexdigest()
    assert source_bundle["bundle_bytes"] == len(exported_bundle_data)
    assert Path(source_bundle["bundle_yaml_path"]).exists()
    next_step_prompt = started["next_step"]["prompt"]
    assert "Bundle collaboration summary:" in next_step_prompt
    assert "Prefer a smaller proven flow over polished but unproven breadth" in next_step_prompt
    assert "Execution strategy:" in next_step_prompt
    assert "Local governance:" in next_step_prompt
    assert "Role postures:" in next_step_prompt
    assert "GateKeeper treats skipped local governance" in next_step_prompt
    assert "run-local: contract/run_contract.json" in next_step_prompt
    assert Path(started["next_step"]["context_absolute_path"]).exists()
    assert started["session"]["status"] == "running_loop"
    assert [item["action"] for item in started["binding"]["entry_invocations"][-2:]] == ["gen", "loop"]
    assert {item["entry_source"] for item in started["binding"]["entry_invocations"][-2:]} == {"codex_project_skill"}
    final = _drive_agent_native_run_to_success(service, adapter="codex", started=started, workdir=sample_workdir)
    assert final["complete"] is True


def test_agent_native_step_capsule_projects_full_judgment_contract(
    service_factory,
    tmp_path: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    (sample_workdir / "AGENTS.md").write_text("Project rules.\n", encoding="utf-8")
    (sample_workdir / "design").mkdir(exist_ok=True)
    (sample_workdir / "design" / "README.md").write_text("# Design\n", encoding="utf-8")
    (sample_workdir / "tests").mkdir(exist_ok=True)
    bundle_file = tmp_path / "bundle.yml"
    bundle_file.write_text(alignment_bundle_yaml(str(sample_workdir.resolve())), encoding="utf-8")
    service.create_agent_bundle_candidate(
        AgentBundleCandidateRequest(
            adapter="codex",
            workdir=sample_workdir,
            message="Ship the focused starter experience.",
            bundle_file=bundle_file,
            entry_source="codex_project_skill",
        )
    )
    started = service.start_agent_loop("codex", workdir=sample_workdir, entry_source="codex_project_skill", execute_async=False)
    step_judgment_contract = started["next_step"]["judgment_contract"]
    context_contract = json.loads(Path(started["next_step"]["context_absolute_path"]).read_text(encoding="utf-8"))["contract"]
    snapshot_contract = service.run_observation_snapshot(started["run"]["id"])["key_takeaways"]["judgment_contract"]

    assert step_judgment_contract["contract_path"] == started["judgment_contract"]["contract_path"]
    assert snapshot_contract["contract_path"] == started["judgment_contract"]["contract_path"]
    assert snapshot_contract["loop_fit_reasons"] == started["judgment_contract"]["loop_fit_reasons"]
    assert snapshot_contract["execution_strategy"] == started["judgment_contract"]["execution_strategy"]
    assert snapshot_contract["local_governance"] == started["judgment_contract"]["local_governance"]
    assert snapshot_contract["role_postures"] == started["judgment_contract"]["role_postures"]
    assert step_judgment_contract["collaboration_summary"].startswith(
        started["judgment_contract"]["collaboration_summary"].removesuffix("…")
    )
    assert step_judgment_contract["contract_path"] == context_contract["path"]
    assert step_judgment_contract["collaboration_summary"] == context_contract["collaboration_summary"]
    assert step_judgment_contract["loop_fit_reasons"] == context_contract["loop_fit_reasons"]
    assert step_judgment_contract["judgment_tradeoffs"] == context_contract["judgment_tradeoffs"]
    assert step_judgment_contract["execution_strategy"] == context_contract["execution_strategy"]
    assert step_judgment_contract["local_governance"] == context_contract["local_governance"]
    assert step_judgment_contract["role_postures"]
    assert context_contract["role_postures"]
    assert any("Keep implementation narrow" in item for item in step_judgment_contract["role_postures"])
    assert any(item["posture_notes"].startswith("Keep implementation narrow") for item in context_contract["role_postures"])
    assert step_judgment_contract["coverage_targets"] == context_contract["coverage_targets"]
    assert step_judgment_contract["success_surface"] == context_contract["success_surface"]
    assert step_judgment_contract["fake_done_states"] == context_contract["fake_done_states"]
    assert step_judgment_contract["evidence_preferences"] == context_contract["evidence_preferences"]
    assert step_judgment_contract["residual_risk"] == context_contract["residual_risk"]
    assert step_judgment_contract["completion_mode"] == context_contract["completion_mode"]

    state_path = RunArtifactLayout(Path(started["run"]["runs_dir"])).run_dir / "agent_native" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["active_step"]["capsule"].pop("judgment_contract", None)
    for field, replacement in {
        "judgment_tradeoffs": [],
        "execution_strategy": [],
        "local_governance": [],
        "success_surface": [],
        "fake_done_states": [],
        "evidence_preferences": [],
        "residual_risk": "",
    }.items():
        state["active_step"]["context_packet"]["contract"][field] = replacement
    state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    claimed = service.claim_agent_native_step(
        AgentNativeStepClaimRequest(adapter="codex", workdir=sample_workdir, run_id=started["run"]["id"])
    )
    assert claimed["next_step"]["judgment_contract"]["contract_path"] == claimed["judgment_contract"]["contract_path"]
    for field in (
        "judgment_tradeoffs",
        "execution_strategy",
        "local_governance",
        "success_surface",
        "fake_done_states",
        "evidence_preferences",
        "residual_risk",
    ):
        assert claimed["next_step"]["judgment_contract"][field] == started["judgment_contract"][field]
    assert claimed["next_step"]["judgment_contract"]["coverage_targets"] == context_contract["coverage_targets"]
    persisted_state = json.loads(state_path.read_text(encoding="utf-8"))
    assert persisted_state["active_step"]["capsule"]["judgment_contract"] == claimed["next_step"]["judgment_contract"]


def test_agent_native_capsule_judgment_contract_falls_back_when_context_is_trimmed(tmp_path: Path) -> None:
    layout = RunArtifactLayout(tmp_path / "runs" / "run_capsule_fallback")
    layout.initialize()
    layout.run_contract_path.write_text(
        json.dumps(
            {
                "collaboration_summary": "Keep frozen judgment stronger than stale context.",
                "loop_fit_reasons": ["Later role handoffs need the same proof bar."],
                "judgment_tradeoffs": ["Evidence beats fast closure."],
                "execution_strategy": ["Prove inherited governance before polishing."],
                "local_governance": ["GateKeeper treats skipped AGENTS.md checks as Blocking."],
                "success_surface": ["Admin can complete the audited action."],
                "fake_done_states": ["Summary-only evidence is fake done."],
                "evidence_preferences": ["Require command output and audit artifacts."],
                "residual_risk": "No unmanaged residual risk is acceptable.",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    contract = ServiceAgentNativeMixin._agent_native_capsule_judgment_contract(
        {"runs_dir": str(layout.run_dir)},
        {
            "contract": {
                "path": "contract/run_contract.json",
                "judgment_tradeoffs": [],
                "execution_strategy": [],
                "local_governance": [],
                "success_surface": [],
                "fake_done_states": [],
                "evidence_preferences": [],
                "residual_risk": "",
            }
        },
    )

    assert contract["judgment_tradeoffs"] == ["Evidence beats fast closure."]
    assert contract["execution_strategy"] == ["Prove inherited governance before polishing."]
    assert contract["local_governance"] == ["GateKeeper treats skipped AGENTS.md checks as Blocking."]
    assert contract["success_surface"] == ["Admin can complete the audited action."]
    assert contract["fake_done_states"] == ["Summary-only evidence is fake done."]
    assert contract["evidence_preferences"] == ["Require command output and audit artifacts."]
    assert contract["residual_risk"] == "No unmanaged residual risk is acceptable."


def test_agent_loop_revalidates_ready_bundle_file_before_start(
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
            message="Ship a ready bundle, but fail closed if the artifact changes after validation.",
            bundle_file=bundle_file,
            entry_source="codex_project_skill",
        )
    )
    ready_path = Path(generated["session"]["bundle_path"])
    ready_bundle = yaml.safe_load(ready_path.read_text(encoding="utf-8"))
    ready_bundle["spec"]["markdown"] = ready_bundle["spec"]["markdown"].replace(
        "Accept minor polish gaps only when they are explicitly named and tracked as an owned follow-up; fail closed on unproven primary-flow behavior or weak verification evidence.",
        "Some risk is fine.",
    )
    assert "Some risk is fine." in ready_bundle["spec"]["markdown"]
    ready_path.write_text(yaml.safe_dump(ready_bundle, sort_keys=False, allow_unicode=True), encoding="utf-8")

    with pytest.raises(LooporaError, match="Residual Risk guidance"):
        service.start_agent_loop("codex", workdir=sample_workdir, entry_source="codex_project_skill", execute_async=False)

    session = service.get_alignment_session(generated["session"]["id"])
    assert session["status"] == "ready"
    assert session["validation"]["ok"] is False
    assert any(
        event["event_type"] == "alignment_import_failed"
        and "Residual Risk guidance" in event["payload"].get("error", "")
        for event in service.list_alignment_events(session["id"])
    )


def test_agent_loop_refreshes_ready_hash_after_valid_bundle_file_change(
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
    original_ready_sha = generated["binding"]["ready_candidate_sha256"]
    ready_path = Path(generated["session"]["bundle_path"])
    ready_bundle = yaml.safe_load(ready_path.read_text(encoding="utf-8"))
    ready_bundle["metadata"]["description"] = "Run from a valid canonical edit made after the first preview."
    ready_path.write_text(yaml.safe_dump(ready_bundle, sort_keys=False, allow_unicode=True), encoding="utf-8")
    expected_ready_sha, expected_ready_bytes = _ready_candidate_digest(ready_path.read_text(encoding="utf-8"))
    assert expected_ready_sha != original_ready_sha

    started = service.start_agent_loop("codex", workdir=sample_workdir, entry_source="codex_project_skill", execute_async=False)

    assert started["binding"]["ready_candidate_sha256"] == expected_ready_sha
    assert started["binding"]["ready_candidate_bytes"] == expected_ready_bytes
    assert started["session"]["validation"]["bundle_sha256"] == expected_ready_sha
    assert started["session"]["validation"]["bundle_bytes"] == expected_ready_bytes


def test_agent_native_claim_rejects_corrupted_active_capsule(
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
            message="Do not turn corrupted active capsules into partial execution contracts.",
            bundle_file=bundle_file,
            entry_source="codex_project_skill",
        )
    )
    started = service.start_agent_loop("codex", workdir=sample_workdir, entry_source="codex_project_skill", execute_async=False)
    state_path = RunArtifactLayout(Path(started["run"]["runs_dir"])).run_dir / "agent_native" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["active_step"]["capsule"] = "not-a-capsule-object"
    state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(LooporaError, match="active step capsule is invalid"):
        service.claim_agent_native_step(
            AgentNativeStepClaimRequest(adapter="codex", workdir=sample_workdir, run_id=started["run"]["id"])
        )


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
    assert builder_step["action_policy"] == {
        "workspace": "workspace_write",
        "can_block": False,
        "can_finish_run": False,
    }
    assert builder_step["role"]["prompt_ref"].endswith("builder.md")
    assert "Keep implementation narrow" in builder_step["role"]["posture_notes"]
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
    assert first_peer_step["action_policy"] == {
        "workspace": "read_only",
        "can_block": True,
        "can_finish_run": False,
    }
    assert first_peer_step["role"]["prompt_ref"].endswith("inspector.md")
    assert "contract-level proof" in first_peer_step["role"]["posture_notes"]
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
    assert gatekeeper_step["action_policy"] == {
        "workspace": "read_only",
        "can_block": True,
        "can_finish_run": True,
    }
    assert gatekeeper_step["role"]["prompt_ref"].endswith("gatekeeper.md")
    assert "Close only when" in gatekeeper_step["role"]["posture_notes"]
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


def test_agent_native_submit_rejects_read_only_workspace_claims_and_schema_mismatches(
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
            message="Ship the focused starter experience.",
            bundle_file=bundle_file,
            entry_source="codex_project_skill",
        )
    )
    started = service.start_agent_loop("codex", workdir=sample_workdir, entry_source="codex_project_skill", execute_async=False)
    inspector_result = _drive_agent_native_until_archetype(
        service,
        started,
        adapter="codex",
        workdir=sample_workdir,
        archetype="inspector",
    )
    step = inspector_result["next_step"]
    raw_output_path = RunArtifactLayout(Path(inspector_result["run"]["runs_dir"])).step_output_raw_path(
        int(step["iter"]),
        int(step["step_order"]),
        str(step["step_id"]),
    )

    workspace_claim_output = _agent_native_step_output(step)
    workspace_claim_output["changed_files"] = ["README.md"]
    with pytest.raises(LooporaConflictError, match="read-only step cannot claim workspace artifact fields"):
        service.submit_agent_native_step(
            AgentNativeStepSubmitRequest(
                adapter="codex",
                workdir=sample_workdir,
                run_id=str(step["run_id"]),
                step_id=str(step["step_id"]),
                output=workspace_claim_output,
                host_dispatch=_agent_native_host_dispatch("codex", step),
                entry_source="codex_project_skill",
            )
        )
    assert not raw_output_path.exists()

    extra_field_output = _agent_native_step_output(step)
    extra_field_output["unexpected_workspace_story"] = "I also edited files."
    with pytest.raises(LooporaConflictError, match=r"unexpected_workspace_story is not allowed"):
        service.submit_agent_native_step(
            AgentNativeStepSubmitRequest(
                adapter="codex",
                workdir=sample_workdir,
                run_id=str(step["run_id"]),
                step_id=str(step["step_id"]),
                output=extra_field_output,
                host_dispatch=_agent_native_host_dispatch("codex", step),
                entry_source="codex_project_skill",
            )
        )
    assert not raw_output_path.exists()

    missing_required_output = _agent_native_step_output(step)
    missing_required_output.pop("coverage_results")
    with pytest.raises(LooporaConflictError, match=r"coverage_results is required"):
        service.submit_agent_native_step(
            AgentNativeStepSubmitRequest(
                adapter="codex",
                workdir=sample_workdir,
                run_id=str(step["run_id"]),
                step_id=str(step["step_id"]),
                output=missing_required_output,
                host_dispatch=_agent_native_host_dispatch("codex", step),
                entry_source="codex_project_skill",
            )
        )
    assert not raw_output_path.exists()

    wrong_type_output = _agent_native_step_output(step)
    wrong_type_output["execution_summary"]["total_checks"] = "one"
    with pytest.raises(LooporaConflictError, match=r"execution_summary\.total_checks expected integer"):
        service.submit_agent_native_step(
            AgentNativeStepSubmitRequest(
                adapter="codex",
                workdir=sample_workdir,
                run_id=str(step["run_id"]),
                step_id=str(step["step_id"]),
                output=wrong_type_output,
                host_dispatch=_agent_native_host_dispatch("codex", step),
                entry_source="codex_project_skill",
            )
        )
    assert not raw_output_path.exists()

    invalid_enum_output = _agent_native_step_output(step)
    invalid_enum_output["check_results"][0]["status"] = "ok"
    with pytest.raises(LooporaConflictError, match=r"check_results\[0\]\.status must be one of"):
        service.submit_agent_native_step(
            AgentNativeStepSubmitRequest(
                adapter="codex",
                workdir=sample_workdir,
                run_id=str(step["run_id"]),
                step_id=str(step["step_id"]),
                output=invalid_enum_output,
                host_dispatch=_agent_native_host_dispatch("codex", step),
                entry_source="codex_project_skill",
            )
        )
    assert not raw_output_path.exists()

    invalid_coverage_status_output = _agent_native_step_output(step)
    invalid_coverage_status_output["coverage_results"] = [
        {
            "target_id": "done_when.check_001",
            "status": "proven",
            "evidence_refs": [],
            "note": "Proven belongs in verdict buckets or notes, not coverage_results.status.",
        }
    ]
    with pytest.raises(LooporaConflictError, match=r"coverage_results\[0\]\.status must be one of"):
        service.submit_agent_native_step(
            AgentNativeStepSubmitRequest(
                adapter="codex",
                workdir=sample_workdir,
                run_id=str(step["run_id"]),
                step_id=str(step["step_id"]),
                output=invalid_coverage_status_output,
                host_dispatch=_agent_native_host_dispatch("codex", step),
                entry_source="codex_project_skill",
            )
        )
    assert not raw_output_path.exists()

    unknown_coverage_target_output = _agent_native_step_output(step)
    unknown_coverage_target_output["coverage_results"] = [
        {
            "target_id": "invented.target_999",
            "status": "covered",
            "evidence_refs": [],
            "note": "The host must not invent a target outside the frozen judgment contract.",
        }
    ]
    with pytest.raises(LooporaConflictError, match=r"coverage_results_unknown_target_id: invented\.target_999"):
        service.submit_agent_native_step(
            AgentNativeStepSubmitRequest(
                adapter="codex",
                workdir=sample_workdir,
                run_id=str(step["run_id"]),
                step_id=str(step["step_id"]),
                output=unknown_coverage_target_output,
                host_dispatch=_agent_native_host_dispatch("codex", step),
                entry_source="codex_project_skill",
            )
        )
    assert not raw_output_path.exists()


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

    context["active"]["capsule"]["role_dispatch"] = {}
    with pytest.raises(LooporaConflictError, match="role_dispatch is required"):
        service._validate_agent_native_host_dispatch(context, None)

    context["active"]["capsule"]["role_dispatch"] = {
        "required": True,
        "target_agent": "loopora-builder",
        "inline_allowed": False,
        "accepted_dispatch_modes": ["host_subagent"],
    }
    with pytest.raises(LooporaConflictError, match="requires loopora_host_dispatch"):
        service._validate_agent_native_host_dispatch(context, None)

    context["active"]["capsule"]["role_dispatch"] = {
        "required": True,
        "target_agent": "loopora-builder",
        "inline_allowed": False,
        "accepted_dispatch_modes": ["host_subagent"],
    }
    with pytest.raises(LooporaConflictError, match="requires loopora_host_dispatch"):
        service._validate_agent_native_host_dispatch(context, {})

    context["active"]["capsule"]["role_dispatch"] = {
        "required": "true",
        "target_agent": "loopora-builder",
        "inline_allowed": False,
        "accepted_dispatch_modes": ["host_subagent"],
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
        "inline_allowed": False,
        "accepted_dispatch_modes": ["host_subagent"],
    }
    with pytest.raises(LooporaConflictError, match="target_agent is required"):
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
        "accepted_dispatch_modes": [],
    }
    with pytest.raises(LooporaConflictError, match="accepted_dispatch_modes"):
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

    for schema_version in (True, 1.5, "1"):
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


def test_agent_native_output_contract_requires_capsule_output_schema(service_factory) -> None:
    service = service_factory(scenario="success")

    with pytest.raises(LooporaConflictError, match="output_schema is required"):
        service._validate_agent_native_step_output_contract(
            {"summary": "This malformed capsule should fail closed."},
            active={"capsule": {"action_policy": {"workspace": "read_only"}}},
        )


@pytest.mark.parametrize(
    ("missing_field", "message"),
    [
        ("judgment_contract", "judgment_contract is required"),
        ("required_coverage", "required_coverage is required"),
        ("action_policy", "action_policy is required"),
    ],
)
def test_agent_native_output_contract_requires_frozen_capsule_objects(
    service_factory,
    missing_field: str,
    message: str,
) -> None:
    service = service_factory(scenario="success")
    capsule = {
        "output_schema": {"type": "object", "required": ["summary"], "properties": {"summary": {"type": "string"}}},
        "judgment_contract": {"goal": "Keep the role tied to the reviewed Loop."},
        "required_coverage": {"status": "pending"},
        "action_policy": {"workspace": "read_only", "can_block": True, "can_finish_run": False},
        "known_evidence_ids": [],
    }
    capsule.pop(missing_field)

    with pytest.raises(LooporaConflictError, match=message):
        service._validate_agent_native_step_output_contract(
            {"summary": "This malformed capsule should fail closed."},
            active={"capsule": capsule},
        )


def test_agent_native_output_contract_requires_known_evidence_id_closed_set(service_factory) -> None:
    service = service_factory(scenario="success")
    capsule = {
        "output_schema": {"type": "object", "required": ["summary"], "properties": {"summary": {"type": "string"}}},
        "judgment_contract": {"goal": "Keep evidence refs inside the capsule."},
        "required_coverage": {"status": "pending"},
        "action_policy": {"workspace": "read_only", "can_block": True, "can_finish_run": False},
    }

    with pytest.raises(LooporaConflictError, match="known_evidence_ids must be a list"):
        service._validate_agent_native_step_output_contract(
            {"summary": "This malformed capsule should fail closed."},
            active={"capsule": capsule},
        )

    capsule["known_evidence_ids"] = [123]
    with pytest.raises(LooporaConflictError, match="known_evidence_ids must contain strings"):
        service._validate_agent_native_step_output_contract(
            {"summary": "This malformed capsule should fail closed."},
            active={"capsule": capsule},
        )


@pytest.mark.parametrize(
    ("action_policy", "message"),
    [
        ({"workspace": "workspace-write", "can_block": True, "can_finish_run": False}, "action_policy.workspace"),
        ({"workspace": "read_only", "can_block": "true", "can_finish_run": False}, "action_policy.can_block"),
        ({"workspace": "read_only", "can_block": True, "can_finish_run": "false"}, "action_policy.can_finish_run"),
    ],
)
def test_agent_native_output_contract_rejects_malformed_action_policy(
    service_factory,
    action_policy: dict,
    message: str,
) -> None:
    service = service_factory(scenario="success")
    capsule = {
        "output_schema": {"type": "object", "required": ["summary"], "properties": {"summary": {"type": "string"}}},
        "judgment_contract": {"goal": "Keep permissions literal and inspectable."},
        "required_coverage": {"status": "pending"},
        "action_policy": action_policy,
        "known_evidence_ids": [],
    }

    with pytest.raises(LooporaConflictError, match=message):
        service._validate_agent_native_step_output_contract(
            {"summary": "This malformed capsule should fail closed."},
            active={"capsule": capsule},
        )


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


def test_agent_native_gatekeeper_blocks_unknown_top_level_evidence_refs(
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
    gatekeeper_output["evidence_refs"] = ["invented_ev"]
    gatekeeper_output["coverage_results"] = []
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
    assert normalized_gatekeeper_output["blocking_issues"] == ["gatekeeper_evidence_refs_unknown: invented_ev"]


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


def test_agent_native_known_evidence_ids_empty_capsule_stays_closed(
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
            message="Ship the focused starter experience.",
            bundle_file=bundle_file,
            entry_source="codex_project_skill",
        )
    )
    result = service.start_agent_loop("codex", workdir=sample_workdir, entry_source="codex_project_skill", execute_async=False)
    result = _drive_agent_native_until_archetype(service, result, adapter="codex", workdir=sample_workdir, archetype="inspector")
    step = result["next_step"]
    layout = RunArtifactLayout(Path(result["run"]["runs_dir"]))
    state_path = layout.run_dir / "agent_native" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert "ev_000_00_builder_step" in state["active_step"]["context_packet"]["evidence"]["known_ids"]
    state["active_step"]["capsule"]["known_evidence_ids"] = []
    state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

    inspector_output = _agent_native_step_output(step)
    inspector_output["coverage_results"] = [
        {
            "target_id": "fake_done.risk_001",
            "status": "covered",
            "evidence_refs": ["ev_000_00_builder_step"],
            "note": "The ref exists in context but not in the capsule closed set.",
        }
    ]

    with pytest.raises(LooporaError, match="agent-native evidence_refs_unknown: ev_000_00_builder_step"):
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
    assert final["task_next_action"]["kind"] == "continue_evidence"
    assert final["task_next_action"]["task_verdict_status"] == "insufficient_evidence"
    assert final["task_next_action"]["next_loop_command"] == "/loopora-loop"
    assert "Run lifecycle is complete, but the task is not proven" in final["task_next_action"]["guidance"]
    agent_entry_start = service.agent_entry_loop_start_projection(run["loop_id"])
    assert agent_entry_start["next_loop_action"] == "start_next_run_for_unproven_verdict"
    assert agent_entry_start["continuation_summary"]["previous_run_id"] == run["id"]
    assert agent_entry_start["continuation_summary"]["previous_task_verdict"]["status"] == "insufficient_evidence"
    assert agent_entry_start["continuation_summary"]["coverage"]["missing_check_count"] > 0
    assert agent_entry_start["continuation_summary"]["next_focus"]
    assert json.loads((Path(run["runs_dir"]) / "evidence" / "task_verdict.json").read_text(encoding="utf-8")) == task_verdict


def test_agent_loop_restarts_after_terminal_insufficient_evidence(
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
    previous_run = final["run"]

    continued = service.start_agent_loop("codex", workdir=sample_workdir, entry_source="codex_project_skill", execute_async=False)

    assert previous_run["status"] == "succeeded"
    assert previous_run["task_verdict"]["status"] == "insufficient_evidence"
    assert continued["started_new_run"] is True
    assert continued["complete"] is False
    assert continued["run"]["id"] != previous_run["id"]
    assert continued["run"]["status"] == "awaiting_agent"
    assert continued["run"]["loop_id"] == previous_run["loop_id"]
    assert continued["next_step"]["execution_plane"] == "agent_native"
    context_packet = json.loads(Path(continued["next_step"]["context_absolute_path"]).read_text(encoding="utf-8"))
    capsule = json.loads(Path(continued["next_step"]["capsule_absolute_path"]).read_text(encoding="utf-8"))
    continuation = context_packet["continuation"]
    assert continuation["previous_run_id"] == previous_run["id"]
    assert continuation["previous_task_verdict"]["status"] == "insufficient_evidence"
    assert continuation["previous_task_verdict_path"].endswith("evidence/task_verdict.json")
    assert continuation["coverage"]["missing_check_count"] > 0
    assert any(gap["target_id"] == "done_when.check_001" for gap in continuation["coverage"]["top_gaps"])
    assert capsule["continuation"]["previous_run_id"] == previous_run["id"]
    assert previous_run["id"] in continued["next_step"]["prompt"]
    assert "insufficient_evidence" in continued["next_step"]["prompt"]
    client = TestClient(build_app(service=service))
    snapshot_response = client.get(f"/api/runs/{continued['run']['id']}/observation-snapshot")
    assert snapshot_response.status_code == 200
    current_step = snapshot_response.json()["current_agent_step"]
    assert current_step["continuation"]["previous_run_id"] == previous_run["id"]
    assert current_step["continuation"]["previous_task_verdict"]["status"] == "insufficient_evidence"
    assert current_step["continuation"]["coverage"]["missing_check_count"] > 0
    assert current_step["continuation"]["next_focus"]
    session = service.get_alignment_session(started["session"]["id"])
    assert session["linked_run_id"] == continued["run"]["id"]
    assert continued["binding"]["linked_run_id"] == continued["run"]["id"]
    assert service.get_run(previous_run["id"])["task_verdict"]["status"] == "insufficient_evidence"


def test_agent_loop_replays_terminal_passed_task_verdict(
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
    previous_run = final["run"]
    service.repository.update_run(
        previous_run["id"],
        task_verdict={
            "status": "passed",
            "source": "gatekeeper",
            "summary": "Required coverage has direct evidence.",
            "buckets": {"proven": [], "weak": [], "unproven": [], "blocking": [], "residual_risk": []},
        },
    )

    continued = service.start_agent_loop("codex", workdir=sample_workdir, entry_source="codex_project_skill", execute_async=False)

    assert continued["started_new_run"] is False
    assert continued["complete"] is True
    assert continued["task_next_action"] == {}
    assert continued["run"]["id"] == previous_run["id"]
    assert continued["next_step"] is None
    session = service.get_alignment_session(started["session"]["id"])
    assert session["linked_run_id"] == previous_run["id"]
    assert len(service.get_loop(previous_run["loop_id"])["runs"]) == 1


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
    assert control_context["iteration"]["coverage_status"] == "blocked"
    assert control_context["iteration"]["covered_check_count"] == 0
    assert control_context["iteration"]["missing_check_count"] == 2
    assert control_context["iteration"]["missing_check_ids"] == ["check_001", "check_002"]
    assert any(item["target_id"] == "done_when.check_001" for item in control_context["iteration"]["coverage_top_gaps"])
    assert control_context["iteration"]["consecutive_no_required_coverage_delta"] == 1
    assert control_context["current_step"]["control"]["signal"] == "no_evidence_progress"
    assert control_step["required_coverage"]["status"] == "blocked"
    assert control_step["required_coverage"]["evidence_progress_mode"] == "stalled"
    assert control_step["required_coverage"]["missing_check_ids"] == ["check_001", "check_002"]
    assert any(item["target_id"] == "done_when.check_001" for item in control_step["required_coverage"]["top_gaps"])
    assert 'Missing required check ids: ["check_001", "check_002"]' in control_step["prompt"]

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
    assert generated["candidate_origin"] == "agent_entry"
    assert generated["candidate_entry_source"] == "claude_project_skill"
    assert generated["host_context_id"] == "claude-session-a"
    assert generated["ready"] is True
    assert generated["binding"]["context_source"] == "explicit"
    assert generated["binding"]["host_context_id"] == "claude-session-a"
    assert generated["binding"]["candidate_origin"] == "agent_entry"
    assert generated["binding"]["candidate_adapter"] == "claude"
    assert generated["binding"]["candidate_entry_source"] == "claude_project_skill"
    assert generated["binding"]["entry_invocations"][-1]["entry_source"] == "claude_project_skill"
    candidate_events = service.list_alignment_events(generated["session"]["id"], limit=20)
    assert any(
        event["event_type"] == "agent_candidate_received"
        and event["payload"]["candidate_origin"] == "agent_entry"
        and event["payload"]["adapter"] == "claude"
        and event["payload"]["entry_source"] == "claude_project_skill"
        and event["payload"]["host_context_id"] == "claude-session-a"
        and event["payload"]["has_candidate_yaml"] is True
        for event in candidate_events
    )

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
    assert generated["host_context_id"] == ""
    assert generated["binding"]["context_source"] == "workdir"
    assert generated["binding"]["host_context_id"] == ""
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

    generated = service.create_agent_bundle_candidate(
        AgentBundleCandidateRequest(
            adapter="codex",
            workdir=sample_workdir,
            message="Bind this READY bundle to one Codex thread.",
            bundle_file=bundle_file,
            context_id="thread-a",
        )
    )
    assert generated["host_context_id"] == "thread-a"
    assert generated["binding"]["host_context_id"] == "thread-a"

    with pytest.raises(LooporaConflictError, match="/loopora-gen"):
        service.start_agent_loop("codex", workdir=sample_workdir, context_id="thread-b", execute_async=False)

    started = service.start_agent_loop("codex", workdir=sample_workdir, context_id="thread-a", execute_async=False)

    assert started["started_new_run"] is True
    assert started["binding"]["context_source"] == "explicit"
    assert started["binding"]["host_context_id"] == "thread-a"
    assert started["execution_plane"] == "agent_native"
    assert started["run"]["status"] == "awaiting_agent"


def test_agent_native_observation_snapshot_projects_current_handoff(
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
            message="Ship the focused starter experience with evidence gaps visible.",
            bundle_file=bundle_file,
            context_id="thread-handoff",
            entry_source="codex_project_skill",
        )
    )

    started = service.start_agent_loop(
        "codex",
        workdir=sample_workdir,
        context_id="thread-handoff",
        entry_source="codex_project_skill",
        execute_async=False,
    )
    snapshot = service.run_observation_snapshot(started["run"]["id"])

    current_step = snapshot["current_agent_step"]
    _assert_agent_native_observation_current_step(current_step)
    _assert_agent_native_observation_artifacts(service, current_step, started, sample_workdir)


def _assert_agent_native_observation_current_step(current_step: dict) -> None:
    assert current_step["step_id"] == "builder_step"
    assert current_step["role"]["name"] == "Focused Builder"
    assert current_step["target_agent"] == "loopora-builder"
    assert current_step["action_policy"]["workspace"] == "workspace_write"
    assert current_step["required_coverage"]["missing_check_count"] == 2
    assert current_step["required_coverage"]["top_gaps"][0]["target_id"] == "done_when.check_001"
    assert current_step["context_path"].endswith("input.context.json")
    assert current_step["capsule_path"].endswith("capsule.json")
    assert current_step["submit_hint"]["result_template_path"].endswith(".result.template.json")
    assert current_step["submit_hint"]["result_outbox_dir"].endswith(".loopora/agent_outbox/codex")
    assert current_step["submit_hint"]["result_outbox_absolute_dir"].endswith(".loopora/agent_outbox/codex")
    assert current_step["submit_hint"]["result_file_contract"] == (
        "Write one wrapper JSON object with loopora_host_dispatch and a schema-shaped result; "
        "replace null placeholders before submit."
    )
    assert isinstance(current_step["known_evidence_count"], int)
    assert "loopora agent codex submit" in current_step["submit_hint"]["command"]
    assert current_step["submit_hint"]["command"].startswith("LOOPORA_AGENT_ENTRY_SOURCE=codex_project_skill ")
    assert "--entry-source codex_project_skill" in current_step["submit_hint"]["command"]
    assert "prompt" not in current_step
    assert "output_schema" not in current_step


def _assert_agent_native_observation_artifacts(service, current_step: dict, started: dict, sample_workdir: Path) -> None:
    capsule_path = Path(current_step["capsule_absolute_path"])
    template_path = Path(current_step["submit_hint"]["result_template_absolute_path"])
    assert capsule_path.exists()
    assert template_path.exists()
    capsule = json.loads(capsule_path.read_text(encoding="utf-8"))
    assert capsule["step_id"] == "builder_step"
    assert capsule["entry_source"] == "codex_project_skill"
    assert capsule["role_dispatch"]["target_agent"] == "loopora-builder"
    assert capsule["submit_hint"]["command"].startswith("LOOPORA_AGENT_ENTRY_SOURCE=codex_project_skill ")
    assert "--entry-source codex_project_skill" in capsule["submit_hint"]["command"]
    assert "prompt" in capsule
    assert "output_schema" in capsule
    template = json.loads(template_path.read_text(encoding="utf-8"))
    assert template["loopora_host_dispatch"]["run_id"] == started["run"]["id"]
    assert template["loopora_host_dispatch"]["step_id"] == "builder_step"
    assert template["loopora_host_dispatch"]["actual_agent"] == "loopora-builder"
    assert template["loopora_host_dispatch"]["inline"] is False
    assert template["loopora_result_contract"]["ignored_on_submit"] is True
    assert template["loopora_result_contract"]["result_must_match_output_schema"] is True
    assert template["loopora_result_contract"]["result_is_schema_shaped_scaffold"] is True
    assert template["loopora_result_contract"]["result_scaffold_uses_null_placeholders"] is True
    assert template["loopora_result_contract"]["replace_null_placeholders_before_submit"] is True
    assert template["loopora_result_contract"]["step_id"] == "builder_step"
    assert template["loopora_result_contract"]["role"]["name"] == "Focused Builder"
    assert template["loopora_result_contract"]["action_policy"]["workspace"] == "workspace_write"
    assert template["loopora_result_contract"]["required_coverage"]["missing_check_count"] == 2
    assert template["loopora_result_contract"]["required_coverage"]["top_gaps"][0]["target_id"] == "done_when.check_001"
    assert "known_evidence_ids" in template["loopora_result_contract"]
    assert template["loopora_result_contract"]["evidence_ref_contract"]["must_copy_exact_ids"] is True
    assert template["loopora_result_contract"]["output_schema"]["required"] == capsule["output_schema"]["required"]
    assert "prompt" not in template["loopora_result_contract"]
    assert "judgment_contract" not in template["loopora_result_contract"]
    assert template["result"] == {
        "attempted": None,
        "abandoned": None,
        "assumption": None,
        "summary": None,
        "changed_files": [None],
        "proof_files": [None],
        "proof_artifacts": [None],
        "artifact_paths": [None],
    }
    with pytest.raises(
        LooporaConflictError,
        match=r"agent-native result does not match output_schema: \$\.attempted expected string, got null",
    ):
        service.submit_agent_native_step(
            AgentNativeStepSubmitRequest(
                adapter="codex",
                workdir=sample_workdir,
                context_id="thread-handoff",
                run_id=started["run"]["id"],
                step_id="builder_step",
                output=template["result"],
                host_dispatch=template["loopora_host_dispatch"],
                entry_source="codex_project_skill",
            )
        )
    assert not Path(capsule["result_output_path"]).is_absolute()
    assert not (Path(started["run"]["runs_dir"]) / capsule["result_output_path"]).exists()

    layout = RunArtifactLayout(Path(started["run"]["runs_dir"]))
    role_requests = read_jsonl(layout.role_requests_path)
    assert role_requests[-1]["context_path"].endswith("input.context.json")
    claimed = [event for event in read_jsonl(layout.legacy_events_path) if event["event_type"] == "agent_native_step_claimed"][-1]
    assert claimed["payload"]["target_agent"] == "loopora-builder"
    assert claimed["payload"]["capsule_path"].endswith("capsule.json")
    assert claimed["payload"]["result_template_path"].endswith(".result.template.json")


def test_agent_native_takeaways_keep_active_iteration_open_after_role_handoff(
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
            message="Ship the focused starter experience with evidence gaps visible.",
            bundle_file=bundle_file,
            context_id="thread-active-takeaway",
        )
    )
    started = service.start_agent_loop("codex", workdir=sample_workdir, context_id="thread-active-takeaway", execute_async=False)
    builder_step = started["next_step"]

    result = service.submit_agent_native_step(
        AgentNativeStepSubmitRequest(
            adapter="codex",
            workdir=sample_workdir,
            context_id="thread-active-takeaway",
            run_id=str(builder_step["run_id"]),
            step_id=str(builder_step["step_id"]),
            output=_agent_native_step_output(builder_step),
            host_dispatch=_agent_native_host_dispatch("codex", builder_step),
            entry_source="codex_project_skill",
        )
    )
    snapshot = service.run_observation_snapshot(result["run"]["id"])
    iterations = snapshot["key_takeaways"]["iterations"]

    assert result["run"]["status"] == "awaiting_agent"
    assert result["next_step"]["step_id"] == "contract_inspection_step"
    assert len(iterations) == 1
    active_iteration = iterations[0]
    assert active_iteration["status"] == "running"
    assert active_iteration["summary"] == "Builder produced a structured handoff for downstream inspection."
    assert active_iteration["role_count"] == 1
    assert active_iteration["roles"][0]["status"] == "completed"
    assert active_iteration["coverage_status"] == "partial"
    assert active_iteration["missing_check_count"] == 2
    assert active_iteration["coverage_top_gaps"][0]["target_id"] == "done_when.check_001"


def test_agent_context_binding_path_hashes_untrusted_context_id(sample_workdir: Path) -> None:
    binding_path = agent_adapters.agent_context_binding_path(
        "codex",
        sample_workdir,
        context_id="../thread-a\nwith/slashes",
    )

    assert binding_path.parent.name == "bindings"
    assert binding_path.name.endswith(".json")
    assert "/" not in binding_path.stem
    assert ".." not in binding_path.stem
    assert "thread-a" not in binding_path.name


def test_agent_loop_rejects_binding_to_different_workdir_session(
    service_factory,
    tmp_path: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    other_workdir = tmp_path / "other-project"
    other_workdir.mkdir()
    bundle_file = tmp_path / "other-bundle.yml"
    bundle_file.write_text(alignment_bundle_yaml(str(other_workdir.resolve())), encoding="utf-8")
    generated = service.create_agent_bundle_candidate(
        AgentBundleCandidateRequest(
            adapter="codex",
            workdir=other_workdir,
            message="Bind this READY bundle to the other project only.",
            bundle_file=bundle_file,
        )
    )
    agent_adapters.write_agent_binding(
        "codex",
        sample_workdir,
        {
            "alignment_session_id": generated["session"]["id"],
            "alignment_status": "ready",
            "bundle_path": generated["session"]["bundle_path"],
            "preview_path": f"/loops/new/bundle?alignment_session_id={generated['session']['id']}",
        },
    )

    with pytest.raises(LooporaConflictError, match="different workdir"):
        service.start_agent_loop("codex", workdir=sample_workdir, execute_async=False)


@pytest.mark.parametrize("adapter", ["codex", "claude", "opencode"])
def test_cli_agent_loop_does_not_spawn_nested_worker_for_agent_native(adapter: str, monkeypatch, tmp_path: Path) -> None:
    workdir = tmp_path / "project"
    workdir.mkdir()
    run_dir = tmp_path / "run"
    layout = RunArtifactLayout(run_dir)
    layout.initialize()
    _write_agent_native_cli_contract(layout)
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
                "next_step": {
                    "step_id": "builder_step",
                    "role": {"name": "Builder"},
                    "role_dispatch": {"target_agent": "loopora-builder"},
                    "action_policy": {"workspace": "workspace_write", "can_block": False, "can_finish_run": False},
                    "required_coverage": {
                        "status": "pending",
                        "covered_check_count": 0,
                        "missing_check_count": 2,
                        "top_gaps": [
                            {"target_id": "done_when.check_001", "text": "Support admin can approve a refund."},
                            {"target_id": "gatekeeper.finish", "text": "GateKeeper needs supporting evidence refs."},
                        ],
                    },
                    "continuation": {
                        "active": True,
                        "previous_run_id": "run_previous",
                        "previous_task_verdict": {"status": "insufficient_evidence"},
                        "coverage": {"covered_check_count": 1, "missing_check_count": 2},
                        "next_focus": ["done_when.check_001: Support admin path still lacks direct proof."],
                    },
                    "known_evidence_count": 3,
                    "context_absolute_path": str(run_dir / "iterations" / "iter_000" / "steps" / "00__builder_step" / "input.context.json"),
                    "capsule_absolute_path": str(run_dir / "iterations" / "iter_000" / "steps" / "00__builder_step" / "capsule.json"),
                    "submit_hint": {
                        "command": "loopora agent codex submit --run-id run_agent --step-id builder_step",
                        "result_file_contract": "Write one wrapper JSON object with loopora_host_dispatch and a schema-shaped result; replace null placeholders before submit.",
                        "result_template_absolute_path": str(
                            workdir / ".loopora" / "agent_outbox" / "codex" / "run_agent__builder_step.result.template.json"
                        ),
                        "result_outbox_absolute_dir": str(workdir / ".loopora" / "agent_outbox" / "codex"),
                    },
                },
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
    _assert_agent_native_cli_output(result.stdout, layout)


def _write_agent_native_cli_contract(layout: RunArtifactLayout) -> None:
    layout.run_contract_path.write_text(
        json.dumps(
            {
                "source_bundle": {
                    "id": "bundle_agent",
                    "name": "Agent Native Refund Bundle",
                    "revision": 2,
                    "source_bundle_id": "",
                    "imported_from_path": "/tmp/loopora/bundle.yml",
                },
                "collaboration_summary": "Prefer frozen judgment over lifecycle optimism.",
                "loop_fit_reasons": ["Future Agent rounds keep the same proof bar active."],
                "judgment_tradeoffs": ["Evidence beats fast closure."],
                "execution_strategy": ["Prove the refund path first, then expand after audit evidence is strong."],
                "local_governance": ["GateKeeper treats skipped AGENTS.md checks as Blocking."],
                "role_postures": [{"role_name": "GateKeeper", "archetype": "gatekeeper", "posture_notes": "Fail closed when evidence is weak."}],
                "completion_mode": "gatekeeper",
                "workflow": {
                    "preset": "build_then_parallel_review",
                    "collaboration_intent": "Parallel review must feed GateKeeper before closure.",
                },
                "compiled_spec": {
                    "check_mode": "specified",
                    "checks": [{"id": "check_001"}, {"id": "check_002"}],
                    "coverage_targets": [
                        {"id": "done_when.check_001", "required": True},
                        {"id": "gatekeeper.finish", "required": True},
                    ],
                    "success_surface": ["Support admin can approve a refund."],
                    "fake_done_states": ["CSV export without permission audit is fake done."],
                    "evidence_preferences": ["Require browser journey and audit log command evidence."],
                    "residual_risk": "No residual risk is acceptable.",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _assert_agent_native_cli_output(stdout: str, layout: RunArtifactLayout) -> None:
    assert f"run_contract_path: {layout.run_contract_path}" in stdout
    assert "source_plan: Agent Native Refund Bundle (bundle_agent, rev 2)" in stdout
    assert "source_plan_path: /tmp/loopora/bundle.yml" in stdout
    assert 'source_plan: {"id":' not in stdout
    assert "judgment_contract_summary: Prefer frozen judgment over lifecycle optimism." in stdout
    assert "check_mode: specified" in stdout
    assert "completion_mode: gatekeeper" in stdout
    assert "workflow_preset: build_then_parallel_review" in stdout
    assert "workflow_collaboration_intent: Parallel review must feed GateKeeper before closure." in stdout
    assert "check_count: 2" in stdout
    _assert_cli_list(stdout, "coverage_targets", "done_when.check_001 (required)", "gatekeeper.finish (required)")
    _assert_cli_list(stdout, "loop_fit_reasons", "Future Agent rounds keep the same proof bar active.")
    _assert_cli_list(stdout, "judgment_tradeoffs", "Evidence beats fast closure.")
    _assert_cli_list(
        stdout,
        "execution_strategy",
        "Prove the refund path first, then expand after audit evidence is strong.",
    )
    _assert_cli_list(stdout, "local_governance", "GateKeeper treats skipped AGENTS.md checks as Blocking.")
    _assert_cli_list(stdout, "role_postures", "GateKeeper: Fail closed when evidence is weak.")
    _assert_cli_list(stdout, "success_surface", "Support admin can approve a refund.")
    _assert_cli_list(stdout, "fake_done_states", "CSV export without permission audit is fake done.")
    _assert_cli_list(stdout, "evidence_preferences", "Require browser journey and audit log command evidence.")
    assert "residual_risk: No residual risk is acceptable." in stdout
    assert "run_url: /runs/run_agent" in stdout
    assert "next_step_id: builder_step" in stdout
    assert "next_target_agent: loopora-builder" in stdout
    assert "continuation_previous_run: run_previous" in stdout
    assert "continuation_task_verdict: insufficient_evidence" in stdout
    assert "continuation_required_coverage: 1 covered / 2 missing" in stdout
    assert "continuation_next_focus:" in stdout
    assert "- done_when.check_001: Support admin path still lacks direct proof." in stdout
    assert "next_action_policy: workspace_write" in stdout
    assert "required_coverage: pending; required checks 0 covered / 2 missing" in stdout
    assert "top_coverage_gaps:" in stdout
    assert "- done_when.check_001: Support admin can approve a refund." in stdout
    assert "next_context_path:" in stdout
    assert "input.context.json" in stdout
    assert "known_evidence_count: 3" in stdout
    assert "result_template_contract: Write one wrapper JSON object with loopora_host_dispatch and a schema-shaped result; replace null placeholders before submit." in stdout
    assert "result_template_fill: open the template, replace null placeholders in result, keep loopora_host_dispatch, then submit the filled copy" in stdout
    _assert_cli_handoff_contract_paths(
        stdout,
        capsule_fragment="capsule.json",
        template_fragment="run_agent__builder_step.result.template.json",
        outbox_fragment=".loopora/agent_outbox/codex",
    )
    assert "submit_hint: loopora agent codex submit --run-id run_agent --step-id builder_step" in stdout


def test_cli_agent_loop_terminal_unproven_reports_lifecycle_without_complete(monkeypatch, tmp_path: Path) -> None:
    workdir = tmp_path / "project"
    workdir.mkdir()
    layout = RunArtifactLayout(tmp_path / "runs" / "run_terminal_loop")
    layout.initialize()
    layout.run_contract_path.write_text(
        json.dumps(
            {
                "collaboration_summary": "Keep terminal replay honest about evidence.",
                "loop_fit_reasons": ["A later Agent pass can add missing proof."],
                "judgment_tradeoffs": ["Never equate run lifecycle with task proof."],
                "execution_strategy": ["Continue from the missing audit evidence."],
                "local_governance": ["Record the task verdict before another pass."],
                "role_postures": [
                    {
                        "role_name": "GateKeeper",
                        "archetype": "gatekeeper",
                        "posture_notes": "Report unproven evidence as unproven.",
                    }
                ],
                "success_surface": ["Audit evidence proves the user-visible flow."],
                "fake_done_states": ["A succeeded run with missing evidence is not done."],
                "evidence_preferences": ["Use project-owned checks and artifact paths."],
                "residual_risk": "No residual risk may hide missing audit proof.",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    class FakeService:
        def start_agent_loop(self, _adapter: str, *, workdir: Path, context_id: str = "", entry_source: str = "", execute_async: bool = True):
            _ = (workdir, context_id, entry_source, execute_async)
            return {
                "execution_plane": "agent_native",
                "run": {
                    "id": "run_terminal_loop",
                    "status": "succeeded",
                    "run_status": "succeeded",
                    "runs_dir": str(layout.run_dir),
                    "task_verdict": {
                        "status": "insufficient_evidence",
                        "source": "gatekeeper",
                        "summary": "Audit proof is still missing.",
                    },
                },
                "run_path": "/runs/run_terminal_loop",
                "started_new_run": False,
                "complete": True,
                "task_next_action": {
                    "kind": "continue_evidence",
                    "next_loop_command": "/loopora-loop",
                    "guidance": "Run lifecycle is complete, but the task is not proven.",
                    "task_verdict_summary": "Audit proof is still missing.",
                },
            }

    monkeypatch.setattr(cli, "create_service", FakeService)
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        ["agent", "codex", "loop", "--workdir", str(workdir), "--context-id", "thread-1", "--no-web"],
    )

    assert result.exit_code == 0, result.stdout
    assert "run_status: succeeded" in result.stdout
    assert f"run_contract_path: {layout.run_contract_path}" in result.stdout
    assert "task_verdict: insufficient_evidence" in result.stdout
    assert "task_next_action: Run lifecycle is complete, but the task is not proven." in result.stdout
    assert "next_loop_command: /loopora-loop" in result.stdout
    assert "next_evidence_focus: Audit proof is still missing." in result.stdout
    assert "agent_native: lifecycle_closed_task_unproven" in result.stdout
    assert "agent_native_task_verdict: insufficient_evidence" in result.stdout
    assert "agent_native: complete" not in result.stdout


def test_cli_agent_next_prints_run_contract_for_intermediate_capsule(monkeypatch, tmp_path: Path) -> None:
    workdir = tmp_path / "project"
    workdir.mkdir()
    layout = RunArtifactLayout(tmp_path / "runs" / "run_next")
    layout.initialize()
    layout.run_contract_path.write_text(
        json.dumps(
            {
                "collaboration_summary": "Keep intermediate capsules tied to frozen judgment.",
                "loop_fit_reasons": ["The next role needs the same proof bar as the first role."],
                "judgment_tradeoffs": ["Do not trade evidence coverage for fast handoff."],
                "execution_strategy": ["Claim the next proof gap before expanding scope."],
                "local_governance": ["Next role checks design and tests before submitting."],
                "role_postures": [
                    {
                        "role_name": "Inspector",
                        "archetype": "inspector",
                        "posture_notes": "Reject handoffs without evidence refs.",
                    }
                ],
                "completion_mode": "gatekeeper",
                "workflow": {
                    "preset": "repair_loop",
                    "collaboration_intent": "Inspector proof gaps must shape the repair loop.",
                },
                "compiled_spec": {
                    "check_mode": "specified",
                    "checks": [{"id": "check_001"}],
                    "coverage_targets": [
                        {"id": "done_when.check_001", "required": True},
                        {"id": "gatekeeper.finish", "required": True},
                    ],
                },
                "success_surface": ["Support can trace the refund authorization path."],
                "fake_done_states": ["A handoff without evidence refs is fake done."],
                "evidence_preferences": ["Use command output and audit artifacts."],
                "residual_risk": "Only documented support handoff risk may remain.",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    class FakeService:
        def claim_agent_native_step(self, request: AgentNativeStepClaimRequest):
            assert request.adapter == "codex"
            assert request.workdir == workdir
            assert request.run_id == "run_next"
            return {
                "run": {
                    "id": "run_next",
                    "status": "awaiting_agent",
                    "run_status": "awaiting_agent",
                    "runs_dir": str(layout.run_dir),
                },
                "run_path": "/runs/run_next",
                "next_step": {
                    "step_id": "inspector_step",
                    "role": {"name": "Inspector"},
                    "role_dispatch": {"target_agent": "loopora-inspector"},
                    "action_policy": {"workspace": "read_only", "can_block": True, "can_finish_run": False},
                    "required_coverage": {
                        "status": "weak",
                        "covered_check_count": 1,
                        "missing_check_count": 1,
                        "top_gaps": [
                            {"target_id": "done_when.check_001", "text": "Authorization proof is still weak."},
                        ],
                    },
                    "known_evidence_count": 4,
                    "context_path": "iterations/iter_000/steps/01__inspector_step/input.context.json",
                    "capsule_path": "iterations/iter_000/steps/01__inspector_step/capsule.json",
                    "submit_hint": {
                        "command": "loopora agent codex submit --run-id run_next",
                        "result_file_contract": "Write one wrapper JSON object with loopora_host_dispatch and a schema-shaped result; replace null placeholders before submit.",
                        "result_template_path": ".loopora/agent_outbox/codex/run_next__inspector_step.result.template.json",
                        "result_outbox_dir": ".loopora/agent_outbox/codex",
                    },
                },
                "complete": False,
            }

    monkeypatch.setattr(cli, "create_service", FakeService)
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        [
            "agent",
            "codex",
            "next",
            "--workdir",
            str(workdir),
            "--run-id",
            "run_next",
            "--no-web",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "run_status: awaiting_agent" in result.stdout
    assert f"run_contract_path: {layout.run_contract_path}" in result.stdout
    assert "judgment_contract_summary: Keep intermediate capsules tied to frozen judgment." in result.stdout
    assert "check_mode: specified" in result.stdout
    assert "completion_mode: gatekeeper" in result.stdout
    assert "workflow_preset: repair_loop" in result.stdout
    assert "workflow_collaboration_intent: Inspector proof gaps must shape the repair loop." in result.stdout
    assert "check_count: 1" in result.stdout
    _assert_cli_list(result.stdout, "coverage_targets", "done_when.check_001 (required)", "gatekeeper.finish (required)")
    _assert_cli_list(result.stdout, "loop_fit_reasons", "The next role needs the same proof bar as the first role.")
    _assert_cli_list(result.stdout, "judgment_tradeoffs", "Do not trade evidence coverage for fast handoff.")
    _assert_cli_list(result.stdout, "execution_strategy", "Claim the next proof gap before expanding scope.")
    _assert_cli_list(result.stdout, "local_governance", "Next role checks design and tests before submitting.")
    _assert_cli_list(result.stdout, "role_postures", "Inspector: Reject handoffs without evidence refs.")
    _assert_cli_list(result.stdout, "success_surface", "Support can trace the refund authorization path.")
    _assert_cli_list(result.stdout, "fake_done_states", "A handoff without evidence refs is fake done.")
    _assert_cli_list(result.stdout, "evidence_preferences", "Use command output and audit artifacts.")
    assert "residual_risk: Only documented support handoff risk may remain." in result.stdout
    assert "next_step_id: inspector_step" in result.stdout
    assert "next_role: Inspector" in result.stdout
    assert "next_target_agent: loopora-inspector" in result.stdout
    assert "next_action_policy: read_only, can_block" in result.stdout
    assert "required_coverage: weak; required checks 1 covered / 1 missing" in result.stdout
    assert "- done_when.check_001: Authorization proof is still weak." in result.stdout
    assert "next_context_path: iterations/iter_000/steps/01__inspector_step/input.context.json" in result.stdout
    assert "known_evidence_count: 4" in result.stdout
    assert "result_template_contract: Write one wrapper JSON object with loopora_host_dispatch and a schema-shaped result; replace null placeholders before submit." in result.stdout
    assert "result_template_fill: open the template, replace null placeholders in result, keep loopora_host_dispatch, then submit the filled copy" in result.stdout
    _assert_cli_handoff_contract_paths(
        result.stdout,
        capsule_fragment="iterations/iter_000/steps/01__inspector_step/capsule.json",
        template_fragment=".loopora/agent_outbox/codex/run_next__inspector_step.result.template.json",
        outbox_fragment=".loopora/agent_outbox/codex",
    )
    assert "submit_hint: loopora agent codex submit --run-id run_next" in result.stdout


def test_cli_agent_submit_prints_terminal_task_verdict(monkeypatch, tmp_path: Path) -> None:
    workdir = tmp_path / "project"
    workdir.mkdir()
    layout = RunArtifactLayout(tmp_path / "runs" / "run_terminal")
    layout.initialize()
    layout.run_contract_path.write_text(
        json.dumps(
            {
                "collaboration_summary": "Keep the evidence standard frozen through terminal submit.",
                "loop_fit_reasons": ["Later role outputs can drift without the frozen contract."],
                "judgment_tradeoffs": ["Direct proof beats narrative confidence."],
                "execution_strategy": ["Collect audit evidence before terminal closure."],
                "local_governance": ["Inspector verifies tests/ evidence before terminal closure."],
                "role_postures": [
                    {
                        "role_name": "GateKeeper",
                        "archetype": "gatekeeper",
                        "posture_notes": "Separate run success from task proof.",
                    }
                ],
                "success_surface": ["Checkout instrumentation records the buyer action."],
                "fake_done_states": ["A story without audit evidence is fake done."],
                "evidence_preferences": ["Audit log command output is required."],
                "residual_risk": "Manual billing export remains a Support-owned follow-up.",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
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
                    "runs_dir": str(layout.run_dir),
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
            "--entry-source",
            "codex_project_skill",
            "--no-web",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "run_status: succeeded" in result.stdout
    assert f"run_contract_path: {layout.run_contract_path}" in result.stdout
    assert "judgment_contract_summary: Keep the evidence standard frozen through terminal submit." in result.stdout
    _assert_cli_list(result.stdout, "loop_fit_reasons", "Later role outputs can drift without the frozen contract.")
    _assert_cli_list(result.stdout, "judgment_tradeoffs", "Direct proof beats narrative confidence.")
    _assert_cli_list(result.stdout, "execution_strategy", "Collect audit evidence before terminal closure.")
    _assert_cli_list(result.stdout, "local_governance", "Inspector verifies tests/ evidence before terminal closure.")
    _assert_cli_list(result.stdout, "role_postures", "GateKeeper: Separate run success from task proof.")
    _assert_cli_list(result.stdout, "success_surface", "Checkout instrumentation records the buyer action.")
    _assert_cli_list(result.stdout, "fake_done_states", "A story without audit evidence is fake done.")
    _assert_cli_list(result.stdout, "evidence_preferences", "Audit log command output is required.")
    assert "residual_risk: Manual billing export remains a Support-owned follow-up." in result.stdout
    assert "task_verdict: insufficient_evidence" in result.stdout
    assert "task_verdict_source: gatekeeper" in result.stdout
    assert "task_verdict_summary: Required coverage still lacks direct evidence." in result.stdout
    assert "task_next_action: run lifecycle is complete but the task is not proven" in result.stdout
    assert "run /loopora-loop again in this Agent session to start the next evidence pass" in result.stdout
    assert "next_loop_command: /loopora-loop" in result.stdout
    assert "next_plan_action: open run_url and use Improve plan with evidence if the Loop itself needs adjustment" in result.stdout
    assert "next_evidence_focus: Required coverage still lacks direct evidence." in result.stdout
    assert "agent_native: lifecycle_closed_task_unproven" in result.stdout
    assert "agent_native_task_verdict: insufficient_evidence" in result.stdout
    assert "agent_native: complete" not in result.stdout


def test_cli_agent_submit_json_preserves_terminal_task_next_action(monkeypatch, tmp_path: Path) -> None:
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
                "task_next_action": {
                    "kind": "continue_evidence",
                    "reason": "run_lifecycle_complete_task_not_proven",
                    "task_verdict_status": "insufficient_evidence",
                    "next_loop_command": "/loopora-loop",
                    "guidance": "Run lifecycle is complete, but the task is not proven.",
                },
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
            "--entry-source",
            "codex_project_skill",
            "--no-web",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["complete"] is True
    assert payload["run"]["task_verdict"]["status"] == "insufficient_evidence"
    assert payload["task_next_action"]["kind"] == "continue_evidence"
    assert payload["task_next_action"]["next_loop_command"] == "/loopora-loop"


def test_cli_agent_submit_schema_error_prints_result_repair_guidance(monkeypatch, tmp_path: Path) -> None:
    workdir = tmp_path / "project"
    workdir.mkdir()
    layout = RunArtifactLayout(tmp_path / "runs" / "run_schema")
    layout.initialize()
    (layout.run_dir / "agent_native").mkdir(parents=True, exist_ok=True)
    (layout.run_dir / "agent_native" / "state.json").write_text(
        json.dumps(
            {
                "active_step": {
                    "capsule": {
                        "step_id": "gatekeeper_step",
                        "role": {"name": "GateKeeper", "id": "gatekeeper", "archetype": "gatekeeper"},
                        "role_dispatch": {"target_agent": "loopora-gatekeeper"},
                        "context_absolute_path": str(layout.step_context_path(0, 3, "gatekeeper_step")),
                        "known_evidence_ids": ["ev_000_00_builder_step", "ev_000_01_inspector_step"],
                        "output_schema": {
                            "type": "object",
                            "properties": {
                                "priority_failures": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "required": ["error_code", "summary"],
                                        "properties": {
                                            "error_code": {"type": "string"},
                                            "summary": {"type": "string"},
                                        },
                                    },
                                }
                            },
                        },
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    result_file = tmp_path / "bad-result.json"
    result_file.write_text(
        json.dumps(
            {
                "loopora_host_dispatch": {
                    "adapter": "codex",
                    "run_id": "run_schema",
                    "step_id": "gatekeeper_step",
                    "target_agent": "loopora-gatekeeper",
                    "actual_agent": "loopora-gatekeeper",
                    "dispatch_mode": "host_subagent",
                    "inline": False,
                },
                "result": {"priority_failures": ["required evidence gap"]},
            }
        ),
        encoding="utf-8",
    )

    class FakeService:
        def submit_agent_native_step(self, _request: AgentNativeStepSubmitRequest):
            raise LooporaConflictError("agent-native result does not match output_schema: $.priority_failures[0] expected object, got string")

        def get_run(self, run_id: str):
            assert run_id == "run_schema"
            return {"id": "run_schema", "runs_dir": str(layout.run_dir)}

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
            "run_schema",
            "--step-id",
            "gatekeeper_step",
            "--result-file",
            str(result_file),
            "--entry-source",
            "codex_project_skill",
            "--no-web",
        ],
    )

    error_text = _error_text(result)
    assert result.exit_code == 1
    assert "submit_repair: result JSON needs repair before this Loopora step can advance" in error_text
    assert f"result_file_to_repair: {result_file}" in error_text
    assert "active_step_id: gatekeeper_step" in error_text
    assert "active_role: GateKeeper" in error_text
    assert "active_target_agent: loopora-gatekeeper" in error_text
    assert "$.priority_failures[0] must be an object with required fields: error_code, summary" in error_text
    assert (
        'schema_lookup: LOOPORA_AGENT_ENTRY_SOURCE=codex_project_skill loopora agent codex next --workdir "$PWD" '
        "--run-id run_schema --json --entry-source codex_project_skill"
    ) in error_text
    assert "Traceback" not in error_text


def test_cli_agent_submit_invalid_json_prints_result_file_repair_guidance(monkeypatch, tmp_path: Path) -> None:
    workdir = tmp_path / "project"
    workdir.mkdir()
    layout = RunArtifactLayout(tmp_path / "runs" / "run_bad_json")
    layout.initialize()
    (layout.run_dir / "agent_native").mkdir(parents=True, exist_ok=True)
    (layout.run_dir / "agent_native" / "state.json").write_text(
        json.dumps(
            {
                "active_step": {
                    "capsule": {
                        "step_id": "builder_step",
                        "role": {"name": "Builder", "id": "builder", "archetype": "builder"},
                        "role_dispatch": {"target_agent": "loopora-builder"},
                        "context_absolute_path": str(layout.step_context_path(0, 0, "builder_step")),
                        "output_schema": {"type": "object", "required": ["summary"], "properties": {"summary": {"type": "string"}}},
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    result_file = tmp_path / "bad-json.result.json"
    result_file.write_text('{"loopora_host_dispatch": ', encoding="utf-8")

    class FakeService:
        def get_run(self, run_id: str):
            assert run_id == "run_bad_json"
            return {"id": "run_bad_json", "runs_dir": str(layout.run_dir)}

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
            "run_bad_json",
            "--step-id",
            "builder_step",
            "--result-file",
            str(result_file),
            "--entry-source",
            "codex_project_skill",
            "--no-web",
        ],
    )

    error_text = _error_text(result)
    assert result.exit_code == 1
    assert "submit_repair: result JSON needs repair before this Loopora step can advance" in error_text
    assert f"result_file_to_repair: {result_file}" in error_text
    assert "active_step_id: builder_step" in error_text
    assert "active_role: Builder" in error_text
    assert "active_target_agent: loopora-builder" in error_text
    assert "fix JSON syntax" in error_text
    assert (
        'schema_lookup: LOOPORA_AGENT_ENTRY_SOURCE=codex_project_skill loopora agent codex next --workdir "$PWD" '
        "--run-id run_bad_json --json --entry-source codex_project_skill"
    ) in error_text
    assert "Traceback" not in error_text


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
