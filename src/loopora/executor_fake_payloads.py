from __future__ import annotations

from dataclasses import dataclass
import re

from loopora.branding import APP_STATE_DIRNAME


class FakePayloadError(RuntimeError):
    """Raised when the fake executor scenario should fail like a provider failure."""


@dataclass(frozen=True)
class FakePayloadContext:
    iter_id: int
    compiled_spec: dict
    checks: list[dict]
    check_count: int
    archetype: str


def build_fake_payload(scenario: str, request) -> dict:
    context = _fake_payload_context(request)
    _raise_for_fake_provider_failure(scenario, request, context)
    if request.role == "alignment" or context.archetype == "alignment":
        return build_alignment_payload(scenario, request)
    if _should_destructively_clear_workdir(scenario, context.archetype):
        _clear_workdir_for_destructive_fake(request)
    payload = _role_payload(scenario, request, context)
    if payload is None:
        raise FakePayloadError(f"unsupported fake role: {request.role}")
    return payload


def _fake_payload_context(request) -> FakePayloadContext:
    compiled_spec = request.extra_context.get("compiled_spec", {})
    checks = compiled_spec.get("checks", [])
    return FakePayloadContext(
        iter_id=int(request.extra_context.get("iter_id", 0)),
        compiled_spec=compiled_spec,
        checks=checks,
        check_count=max(len(checks), 1),
        archetype=str(request.role_archetype or request.extra_context.get("archetype") or request.role).strip().lower(),
    )


def _raise_for_fake_provider_failure(scenario: str, request, context: FakePayloadContext) -> None:
    if scenario == "alignment_resume_failure" and request.role == "alignment" and request.resume_session_id:
        raise FakePayloadError("simulated native resume failure")
    if scenario == "role_failure" and context.archetype in {"tester", "inspector"}:
        raise FakePayloadError("simulated inspector failure")


def _role_payload(scenario: str, request, context: FakePayloadContext) -> dict | None:
    if context.archetype in {"generator", "builder"}:
        payload = _builder_payload(context.iter_id)
    elif request.role == "check_planner":
        payload = _check_planner_payload(context.compiled_spec)
    elif context.archetype in {"tester", "inspector"}:
        payload = _tester_payload(context.iter_id, context.checks, context.check_count)
    elif context.archetype in {"verifier", "gatekeeper"}:
        payload = _verifier_payload(scenario, context.iter_id, request, context.check_count)
    elif context.archetype in {"challenger", "guide"}:
        payload = _challenger_payload(context.iter_id, request)
    elif context.archetype == "custom":
        payload = _custom_payload()
    else:
        payload = None
    return payload


def build_alignment_payload(scenario: str, request) -> dict:
    if scenario == "alignment_failure":
        raise FakePayloadError("simulated alignment failure")
    mode = str(request.extra_context.get("alignment_mode", "normal"))
    alignment_stage = str(request.extra_context.get("alignment_stage", "clarifying") or "clarifying")
    workdir = str(request.extra_context.get("target_workdir") or request.workdir)
    if scenario == "alignment_question":
        payload = alignment_response(
            status="question",
            assistant_message="这次你更怕做慢，还是更怕做糙？",
            needs_user_input=True,
            bundle_yaml="",
            phase="clarifying",
        )
    elif scenario == "alignment_premature_bundle":
        payload = alignment_response(
            status="bundle",
            assistant_message="我跳过对齐直接生成 bundle。",
            needs_user_input=False,
            bundle_yaml=alignment_bundle_yaml(workdir),
            phase="clarifying",
        )
    elif mode != "repair" and alignment_stage not in {"confirmed", "compiling"}:
        payload = alignment_agreement_response()
    elif scenario == "alignment_invalid":
        payload = alignment_response(
            status="bundle",
            assistant_message="我先给出一个故意不完整的 bundle。",
            needs_user_input=False,
            bundle_yaml="version: 1\nmetadata:\n  name: Broken Alignment Bundle\n",
            phase="bundle",
        )
    elif scenario == "alignment_invalid_then_valid" and mode != "repair":
        payload = alignment_response(
            status="bundle",
            assistant_message="我先给出一个需要修复的 bundle。",
            needs_user_input=False,
            bundle_yaml="version: 1\nmetadata:\n  name: Broken Alignment Bundle\n",
            phase="bundle",
        )
    elif scenario == "alignment_semantic_invalid_then_valid" and mode != "repair":
        payload = alignment_response(
            status="bundle",
            assistant_message="我先给出一个语义不完整的 bundle。",
            needs_user_input=False,
            bundle_yaml=alignment_bundle_yaml_without_semantics(workdir),
            phase="bundle",
        )
    elif scenario == "alignment_missing_readiness_evidence":
        payload = alignment_response(
            status="bundle",
            assistant_message="我勾选了 checklist 但没有给出具体证据。",
            needs_user_input=False,
            bundle_yaml=alignment_bundle_yaml(workdir),
            phase="bundle",
        )
        payload["readiness_evidence"] = {
            "task_scope": "ok",
            "success_surface": "ok",
            "fake_done_risks": "ok",
            "evidence_preferences": "ok",
            "role_posture": "ok",
            "workflow_shape": "ok",
            "workdir_facts": "ok",
            "open_questions": "",
        }
    else:
        payload = alignment_response(
            status="bundle",
            assistant_message="已整理成一个可导入的 Loopora bundle。",
            needs_user_input=False,
            bundle_yaml=alignment_bundle_yaml(workdir),
            phase="bundle",
        )
    return payload


def alignment_response(
    *,
    status: str,
    assistant_message: str,
    needs_user_input: bool,
    bundle_yaml: str,
    phase: str,
) -> dict:
    ready = phase == "bundle"
    checklist = {
        "task_scope": ready,
        "success_surface": ready,
        "fake_done_risks": ready,
        "evidence_preferences": ready,
        "role_posture": ready,
        "workflow_shape": ready,
        "explicit_confirmation": ready,
    }
    evidence = alignment_readiness_evidence() if ready else {
        "task_scope": "",
        "success_surface": "",
        "fake_done_risks": "",
        "evidence_preferences": "",
        "role_posture": "",
        "workflow_shape": "",
        "workdir_facts": "",
        "open_questions": "Need more task-shaping answers before compiling the loop plan.",
    }
    return {
        "status": status,
        "assistant_message": assistant_message,
        "needs_user_input": needs_user_input,
        "bundle_yaml": bundle_yaml,
        "session_ref": {
            "session_id": "",
            "thread_id": "",
            "conversation_id": "",
            "provider": "fake",
            "raw_json": "",
        },
        "alignment_phase": phase,
        "agreement_summary": "Use a focused Builder, evidence Inspector, and strict GateKeeper." if ready else "",
        "readiness_checklist": checklist,
        "readiness_evidence": evidence,
    }


def alignment_agreement_response() -> dict:
    return {
        "status": "question",
        "assistant_message": "我会按这个工作协议生成：先做聚焦实现，再收集可复现证据，最后由守门者保守裁决。请回复“确认”后我再生成 Loop 方案。",
        "needs_user_input": True,
        "bundle_yaml": "",
        "session_ref": {
            "session_id": "",
            "thread_id": "",
            "conversation_id": "",
            "provider": "fake",
            "raw_json": "",
        },
        "alignment_phase": "agreement",
        "agreement_summary": "Use a focused Builder, evidence Inspector, and strict GateKeeper.",
        "readiness_checklist": {
            "task_scope": True,
            "success_surface": True,
            "fake_done_risks": True,
            "evidence_preferences": True,
            "role_posture": True,
            "workflow_shape": True,
            "explicit_confirmation": False,
        },
        "readiness_evidence": alignment_readiness_evidence(
            open_questions="Waiting for explicit user confirmation of the working agreement."
        ),
    }


def alignment_readiness_evidence(*, open_questions: str = "") -> dict:
    return {
        "task_scope": "The user wants a focused starter experience, not an open-ended role or workflow exercise.",
        "success_surface": "Success means the primary user flow works end to end and can be verified from project-owned evidence.",
        "fake_done_risks": "The loop should reject vague completion claims, happy-path-only work, and output without reproducible proof.",
        "evidence_preferences": "The strongest evidence is direct command output, tests, or concrete artifacts created by the project.",
        "role_posture": "Builder keeps the patch narrow, Inspector collects evidence, and GateKeeper fails closed on weak proof.",
        "workflow_shape": "Builder -> Inspector -> GateKeeper fits because a focused slice is built, then inspected, then gated.",
        "workdir_facts": "The fake executor treats the provided workdir as the target project and leaves exact stack facts to the run.",
        "open_questions": open_questions,
    }


def alignment_bundle_yaml(workdir: str) -> str:
    return f"""version: 1
metadata:
  name: "Aligned Starter Bundle"
  description: "Bundle generated by the Web alignment flow."
  revision: 1
collaboration_summary: |
  Start with focused implementation, collect direct evidence, then let a GateKeeper close only when the task is truly done.
loop:
  name: "Aligned Starter Bundle"
  workdir: "{workdir}"
  completion_mode: "gatekeeper"
  executor_kind: "codex"
  executor_mode: "preset"
  command_cli: ""
  command_args_text: ""
  model: ""
  reasoning_effort: "medium"
  iteration_interval_seconds: 0
  max_iters: 4
  max_role_retries: 1
  delta_threshold: 0.005
  trigger_window: 2
  regression_window: 2
spec:
  markdown: |
    # Task

    Ship the focused starter experience described in the alignment agreement with small, maintainable changes in the target workdir.

    # Done When

    - The primary user flow works end to end.
    - The implementation is covered by project-owned evidence.

    # Guardrails

    - Keep changes scoped to the requested behavior.

    # Success Surface

    - The primary user flow is understandable, maintainable, and easy to extend after the first pass.

    # Fake Done

    - Do not pass with only a happy-path claim and no reproducible evidence.
    - Do not pass if the implementation lacks a handoff that explains what evidence was collected.

    # Evidence Preferences

    - Prefer project-owned checks, direct run output, and concrete artifacts before screenshots or claims.
    - Each role should leave a clear handoff note explaining what was changed, inspected, or blocked.

    # Role Notes

    ## Builder Notes

    Prefer a small maintainable patch over broad rewrites.

    ## Inspector Notes

    Collect reproducible evidence and call out missing proof plainly.

    ## GateKeeper Notes

    Fail closed when Done When, fake-done risks, and evidence preferences are not all satisfied.
role_definitions:
  - key: "builder"
    name: "Focused Builder"
    description: "Implements the smallest maintainable change."
    archetype: "builder"
    prompt_ref: "builder.md"
    prompt_markdown: |
      ---
      version: 1
      archetype: builder
      ---

      Build the focused starter slice carefully and keep the repo coherent. Leave a handoff that names the changed behavior, the verification evidence, and any blocker that should stop Inspector or GateKeeper.
    posture_notes: |
      Keep implementation narrow and leave the workspace easier to verify; prefer concrete evidence over broad feature spread.
    executor_kind: "codex"
    executor_mode: "preset"
    command_cli: ""
    command_args_text: ""
    model: ""
    reasoning_effort: ""
  - key: "inspector"
    name: "Evidence Inspector"
    description: "Collects reproducible evidence before sign-off."
    archetype: "inspector"
    prompt_ref: "inspector.md"
    prompt_markdown: |
      ---
      version: 1
      archetype: inspector
      ---

      Inspect from direct evidence and report gaps plainly. Your handoff must identify the strongest proof, missing proof, and any blocker that should prevent GateKeeper from finishing.
    posture_notes: |
      Prefer project-owned commands and concrete artifacts; block vague completion claims or unverified happy paths.
    executor_kind: "codex"
    executor_mode: "preset"
    command_cli: ""
    command_args_text: ""
    model: ""
    reasoning_effort: ""
  - key: "gatekeeper"
    name: "Conservative GateKeeper"
    description: "Fails closed when evidence is weak."
    archetype: "gatekeeper"
    prompt_ref: "gatekeeper.md"
    prompt_markdown: |
      ---
      version: 1
      archetype: gatekeeper
      ---

      Decide from direct evidence and do not accept vague completion claims. Finish only when the Builder and Inspector handoffs prove the task contract; otherwise block with the smallest next repair.
    posture_notes: |
      Close only when the task and verification evidence agree; fail closed when handoff evidence is missing or weak.
    executor_kind: "codex"
    executor_mode: "preset"
    command_cli: ""
    command_args_text: ""
    model: ""
    reasoning_effort: ""
workflow:
  version: 1
  preset: "build_then_parallel_review"
  collaboration_intent: "Build one focused starter slice, inspect the contract and evidence in parallel, then let GateKeeper finish only when both inspection branches support the task contract."
  roles:
    - id: "builder"
      role_definition_key: "builder"
    - id: "contract_inspector"
      role_definition_key: "inspector"
      name: "Contract Inspector"
    - id: "evidence_inspector"
      role_definition_key: "inspector"
      name: "Evidence Inspector"
    - id: "gatekeeper"
      role_definition_key: "gatekeeper"
  steps:
    - id: "builder_step"
      role_id: "builder"
    - id: "contract_inspection_step"
      role_id: "contract_inspector"
      parallel_group: "inspection_pack"
      inputs:
        handoffs_from: ["builder_step"]
        evidence_query:
          archetypes: ["builder"]
          limit: 12
    - id: "evidence_inspection_step"
      role_id: "evidence_inspector"
      parallel_group: "inspection_pack"
      inputs:
        handoffs_from: ["builder_step"]
        evidence_query:
          archetypes: ["builder"]
          limit: 12
    - id: "gatekeeper_step"
      role_id: "gatekeeper"
      on_pass: "finish_run"
      inputs:
        handoffs_from: ["contract_inspection_step", "evidence_inspection_step"]
        evidence_query:
          archetypes: ["inspector", "builder"]
          limit: 24
"""


def alignment_bundle_yaml_without_semantics(workdir: str) -> str:
    yaml_text = alignment_bundle_yaml(workdir)
    yaml_text = re.sub(
        r"\n    # Success Surface\n\n    - .+?\n(?=\n    # Fake Done)",
        "\n",
        yaml_text,
        flags=re.DOTALL,
    )
    return re.sub(
        r"\n    # Evidence Preferences\n\n    - .+?\n(?=\n    # Role Notes)",
        "\n",
        yaml_text,
        flags=re.DOTALL,
    )


def _should_destructively_clear_workdir(scenario: str, archetype: str) -> bool:
    return (scenario == "destructive_generator" and archetype in {"generator", "builder"}) or (
        scenario == "destructive_tester" and archetype in {"tester", "inspector"}
    )


def _clear_workdir_for_destructive_fake(request) -> None:
    for child in request.workdir.iterdir():
        if child.name == APP_STATE_DIRNAME:
            continue
        if child.is_dir():
            for nested in sorted(child.rglob("*"), key=lambda path: len(path.parts), reverse=True):
                if nested.is_file():
                    nested.unlink()
                elif nested.is_dir():
                    nested.rmdir()
            child.rmdir()
        else:
            child.unlink()


def _builder_payload(iter_id: int) -> dict:
    return {
        "attempted": f"Iter {iter_id}: refine workdir toward compiled goal",
        "abandoned": "Avoided multi-module changes in the same iteration.",
        "assumption": "The highest-impact gain is still in the primary path.",
        "summary": "Applied a focused change strategy.",
        "changed_files": [],
    }


def _check_planner_payload(compiled_spec: dict) -> dict:
    goal = (compiled_spec.get("goal") or "the prototype").strip()
    return {
        "checks": [
            {
                "title": "Goal alignment",
                "details": (
                    f"When: someone reviews the current prototype against the goal.\n"
                    f"Expect: the main flow clearly moves toward {goal}.\n"
                    "Fail if: the prototype feels unrelated, confusing, or incomplete in its primary direction."
                ),
                "when": "Someone evaluates the prototype as-is.",
                "expect": f"The main flow visibly supports {goal}.",
                "fail_if": "The current direction is confusing or disconnected from the goal.",
            },
            {
                "title": "Primary interaction holds together",
                "details": (
                    "When: a user follows the most obvious interaction path.\n"
                    "Expect: the path remains understandable from start to finish.\n"
                    "Fail if: the experience breaks, stalls, or loses its state."
                ),
                "when": "A user follows the most obvious path.",
                "expect": "The path stays understandable and coherent.",
                "fail_if": "The experience breaks, stalls, or loses its state.",
            },
            {
                "title": "Prototype safety",
                "details": (
                    "When: the user hits an incomplete or awkward edge in the prototype.\n"
                    "Expect: the interface still communicates what is happening.\n"
                    "Fail if: the prototype crashes, misleads the user, or becomes unusable."
                ),
                "when": "An incomplete or awkward edge appears.",
                "expect": "The interface still communicates clearly.",
                "fail_if": "The prototype crashes, misleads the user, or becomes unusable.",
            },
        ],
        "generation_notes": "Generated a compact exploratory check set because the spec did not provide explicit checks.",
    }


def _tester_payload(iter_id: int, checks: list[dict], check_count: int) -> dict:
    passed_checks = min(check_count, 1 + iter_id)
    total_checks = check_count
    results = []
    for index, check in enumerate(checks, start=1):
        status = "passed" if index <= passed_checks else "failed"
        results.append(
            {
                "id": check["id"],
                "title": check["title"],
                "status": status,
                "notes": check.get("expect") or check.get("details", ""),
            }
        )
    return {
        "execution_summary": {
            "total_checks": total_checks,
            "passed": passed_checks,
            "failed": max(total_checks - passed_checks, 0),
            "errored": 0,
            "total_duration_ms": 500 + iter_id * 25,
        },
        "check_results": results,
        "dynamic_checks": [],
        "tester_observations": "Fake executor evaluated the compiled Markdown checks.",
        "coverage_results": [],
    }


def _verifier_payload(scenario: str, iter_id: int, request, check_count: int) -> dict:
    tester_output = request.extra_context.get("inspector_output") or request.extra_context.get("tester_output") or {
        "execution_summary": {"total_checks": check_count, "passed": 0},
        "check_results": [],
    }
    total_checks = max(tester_output["execution_summary"]["total_checks"], 1)
    passed_checks = tester_output["execution_summary"]["passed"]
    composite = 0.62 if scenario == "plateau" and iter_id < 2 else 0.621 if scenario == "plateau" else round(min(0.45 + iter_id * 0.25, 1.0), 3)
    failed_check_ids = [check["id"] for check in tester_output["check_results"] if check.get("status") != "passed"]
    check_pass_rate = round(passed_checks / total_checks, 3)
    passed = composite >= 0.9 and not failed_check_ids
    evidence_refs = _evidence_refs(request)
    return {
        "passed": passed,
        "decision_summary": "All checks passed." if passed else "The run still has failing evidence.",
        "composite_score": composite,
        "metrics": [
            {
                "name": "check_pass_rate",
                "value": check_pass_rate,
                "threshold": 0.9,
                "passed": check_pass_rate >= 0.9,
            },
            {
                "name": "quality_score",
                "value": composite,
                "threshold": 0.9,
                "passed": composite >= 0.9,
            },
        ],
        "metric_scores": {
            "check_pass_rate": {
                "value": check_pass_rate,
                "threshold": 0.9,
                "passed": check_pass_rate >= 0.9,
            },
            "quality_score": {
                "value": composite,
                "threshold": 0.9,
                "passed": composite >= 0.9,
            },
        },
        "blocking_issues": [],
        "hard_constraint_violations": [],
        "failed_check_ids": failed_check_ids,
        "priority_failures": [],
        "feedback_to_builder": "Improve the most visible failing checks without widening scope.",
        "feedback_to_generator": "Improve the most visible failing checks without widening scope.",
        "evidence_refs": evidence_refs if passed else [],
        "evidence_claims": [],
    }


def _evidence_refs(request) -> list[str]:
    context_packet = request.extra_context.get("context_packet") if isinstance(request.extra_context, dict) else {}
    evidence_items = []
    if isinstance(context_packet, dict):
        evidence_items = list((context_packet.get("evidence") or {}).get("items") or [])
    return [str(item.get("id")) for item in evidence_items if isinstance(item, dict) and str(item.get("id") or "").strip()][-3:]


def _challenger_payload(iter_id: int, request) -> dict:
    return {
        "created_at_iter": iter_id,
        "mode": request.extra_context.get("stagnation_mode", "plateau"),
        "consumed": False,
        "analysis": {
            "stagnation_pattern": "fake executor detected stalled gains",
            "recommended_shift": "Try a smaller, more visible change in the main path.",
            "risk_note": "Changing direction too broadly may hide whether the plateau was real.",
        },
        "seed_question": "What is the smallest testable change that breaks the plateau?",
        "meta_note": "This is a suggestion, not a command.",
    }


def _custom_payload() -> dict:
    return {
        "status": "advisory",
        "summary": "Collected read-only evidence and prepared a scoped handoff.",
        "blocking_items": [
            "A restricted role can guide the next move but cannot close the loop alone.",
        ],
        "recommended_next_action": "Use the strongest evidence path for the next change.",
        "observations": [
            "The custom role stayed inside the current workspace evidence.",
            "No write action was claimed from this restricted role.",
        ],
        "recommendations": [
            "Use the strongest evidence path for the next change.",
        ],
        "risks": [
            "A restricted role can guide the next move but cannot close the loop alone.",
        ],
        "handoff_note": "Pass these observations to a Builder or Inspector step.",
    }
