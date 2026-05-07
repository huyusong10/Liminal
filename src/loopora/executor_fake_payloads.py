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


@dataclass(frozen=True)
class AlignmentPayloadState:
    mode: str
    alignment_stage: str
    workdir: str
    prefers_chinese: bool
    is_improvement: bool


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
    working_agreement = request.extra_context.get("working_agreement") if isinstance(request.extra_context.get("working_agreement"), dict) else {}
    state = AlignmentPayloadState(
        mode=str(request.extra_context.get("alignment_mode", "normal")),
        alignment_stage=str(request.extra_context.get("alignment_stage", "clarifying") or "clarifying"),
        workdir=str(request.extra_context.get("target_workdir") or request.workdir),
        prefers_chinese=bool(request.extra_context.get("prefers_chinese")),
        is_improvement=str(working_agreement.get("mode") or "") == "improvement",
    )
    payload = _alignment_preconfirmation_payload(
        scenario,
        state=state,
    )
    if payload is not None:
        return payload
    payload = _alignment_bundle_payload_for_scenario(
        scenario,
        mode=state.mode,
        workdir=state.workdir,
    )
    if payload is not None:
        return payload
    return alignment_default_bundle_response(
        state.workdir,
        prefers_chinese=state.prefers_chinese,
        is_improvement=state.is_improvement,
        use_generic_bundle=scenario == "alignment_improvement_generic_bundle",
    )


def _alignment_preconfirmation_payload(
    scenario: str,
    *,
    state: AlignmentPayloadState,
) -> dict | None:
    payload = _alignment_preconfirmation_scenario_payload(scenario, workdir=state.workdir)
    if payload is not None:
        return payload
    if state.mode != "repair" and state.alignment_stage not in {
        "confirmed",
        "compiling",
    }:
        return _alignment_preconfirmation_agreement_payload_for_scenario(
            scenario,
            prefers_chinese=state.prefers_chinese,
            is_improvement=state.is_improvement,
        )
    return None


def _alignment_preconfirmation_scenario_payload(scenario: str, *, workdir: str) -> dict | None:
    status = "question"
    assistant_message = ""
    needs_user_input = True
    bundle_yaml = ""
    phase = "clarifying"
    if scenario == "alignment_question":
        assistant_message = "这次你更怕做慢，还是更怕做糙？"
    elif scenario == "alignment_not_fit":
        status = "blocked"
        assistant_message = "这看起来一次 Agent 执行加一次人工 review 就够了；如果你仍想用 Loopora，请说明会反复出现的判断或新证据。"
        phase = "blocked"
    elif scenario == "alignment_not_fit_without_needs_user_input":
        status = "blocked"
        assistant_message = "这看起来一次 Agent 执行加一次人工 review 就够了；如果你仍想用 Loopora，请说明会反复出现的判断或新证据。"
        needs_user_input = False
        phase = "blocked"
    elif scenario == "alignment_mechanical_question":
        assistant_message = "你要不要配置两个 Inspector、一个 GateKeeper 和 workflow controls？"
    elif scenario == "alignment_generic_preference_question":
        assistant_message = "你有什么偏好？你想要高质量还是快一点？"
    elif scenario == "alignment_questionnaire_overload":
        assistant_message = (
            "请先回答这些问题：\n"
            "1. 你想完成什么任务？\n"
            "2. 你希望什么证据能证明完成？\n"
            "3. 你能接受哪些残余风险？\n"
            "4. 你希望角色怎么分工？"
        )
    elif scenario == "alignment_english_clarifying_message_for_chinese_user":
        assistant_message = "What evidence should prove completion before I compile the Loop?"
    elif scenario == "alignment_premature_bundle":
        status = "bundle"
        assistant_message = "我跳过对齐直接生成 bundle。"
        needs_user_input = False
        bundle_yaml = alignment_bundle_yaml(workdir)
    else:
        return None
    return alignment_response(
        status=status,
        assistant_message=assistant_message,
        needs_user_input=needs_user_input,
        bundle_yaml=bundle_yaml,
        phase=phase,
    )


def _alignment_preconfirmation_agreement_payload_for_scenario(
    scenario: str,
    *,
    prefers_chinese: bool,
    is_improvement: bool,
) -> dict:
    if is_improvement and scenario != "alignment_improvement_missing_delta":
        payload = alignment_chinese_improvement_agreement_response() if prefers_chinese else alignment_improvement_agreement_response()
    else:
        payload = alignment_chinese_agreement_response() if prefers_chinese else alignment_agreement_response()
    if scenario == "alignment_hidden_agreement_message":
        payload["assistant_message"] = "Please confirm."
    elif scenario == "alignment_incomplete_agreement_checklist":
        payload["readiness_checklist"]["workflow_shape"] = False
        payload["assistant_message"] = "请确认这份还没完成 workflow 判断的协议。"
    elif scenario == "alignment_unresolved_open_questions":
        payload["readiness_evidence"]["open_questions"] = (
            "Need the user to decide whether browser evidence or test output should persuade GateKeeper."
        )
        payload["assistant_message"] = "Please confirm; the evidence choice is still open."
    elif scenario == "alignment_english_agreement_for_chinese_user":
        payload = alignment_agreement_response()
        payload["assistant_message"] = "Please confirm."
    elif scenario == "alignment_survive_chat_loop_fit_readiness_evidence":
        payload["readiness_evidence"]["loop_fit"] = (
            "This is not one Agent pass plus human review because the judgment should survive one chat "
            "as run evidence, export, reuse, and audit material for future rounds."
        )
    elif scenario == "alignment_missing_evidence_bucket_readiness_evidence":
        payload["readiness_evidence"]["evidence_preferences"] = (
            "The strongest evidence is direct command output, tests, or concrete artifacts created by the project."
        )
    return payload


def _alignment_bundle_payload_for_scenario(
    scenario: str,
    *,
    mode: str,
    workdir: str,
) -> dict | None:
    payload: dict | None = None
    if scenario == "alignment_invalid":
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
    elif scenario == "alignment_bundle_unsupported_observed_workdir_claim":
        payload = alignment_response(
            status="bundle",
            assistant_message="I prepared a bundle with an unsupported observed workdir claim.",
            needs_user_input=False,
            bundle_yaml=alignment_bundle_yaml_with_unsupported_observed_workdir_claim(workdir),
            phase="bundle",
        )
    elif scenario == "alignment_chinese_readiness_evidence":
        payload = alignment_response(
            status="bundle",
            assistant_message="我已用中文整理成一个可导入的 Loopora bundle。",
            needs_user_input=False,
            bundle_yaml=alignment_chinese_bundle_yaml(workdir),
            phase="bundle",
        )
        payload["agreement_summary"] = "使用聚焦 Builder、证据 Inspector 和严格 GateKeeper 来推进这个 Loop。"
        payload["readiness_evidence"] = alignment_chinese_readiness_evidence()
    elif scenario == "alignment_english_bundle_prose_for_chinese_user":
        payload = alignment_response(
            status="bundle",
            assistant_message="我准备了一个 bundle，但正文仍然是英文。",
            needs_user_input=False,
            bundle_yaml=alignment_bundle_yaml(workdir),
            phase="bundle",
        )
        payload["agreement_summary"] = "使用聚焦 Builder、证据 Inspector 和严格 GateKeeper 来推进这个 Loop。"
        payload["readiness_evidence"] = alignment_chinese_readiness_evidence()
    elif scenario == "alignment_english_visible_bundle_names_for_chinese_user":
        payload = alignment_response(
            status="bundle",
            assistant_message="我准备了一个中文 bundle，但可见名称仍然是英文。",
            needs_user_input=False,
            bundle_yaml=alignment_chinese_bundle_yaml_with_english_visible_names(workdir),
            phase="bundle",
        )
        payload["agreement_summary"] = "使用聚焦 Builder、证据 Inspector 和严格 GateKeeper 来推进这个 Loop。"
        payload["readiness_evidence"] = alignment_chinese_readiness_evidence()
    elif scenario == "alignment_english_assistant_message_for_chinese_bundle":
        payload = alignment_response(
            status="bundle",
            assistant_message="I prepared an importable Loopora bundle.",
            needs_user_input=False,
            bundle_yaml=alignment_chinese_bundle_yaml(workdir),
            phase="bundle",
        )
        payload["agreement_summary"] = "使用聚焦 Builder、证据 Inspector 和严格 GateKeeper 来推进这个 Loop。"
        payload["readiness_evidence"] = alignment_chinese_readiness_evidence()
    elif scenario == "alignment_english_bundle_for_chinese_user":
        payload = alignment_response(
            status="bundle",
            assistant_message="I prepared an importable Loopora bundle.",
            needs_user_input=False,
            bundle_yaml=alignment_bundle_yaml(workdir),
            phase="bundle",
        )
    else:
        payload = _alignment_readiness_issue_payload_for_scenario(scenario, workdir=workdir)
    return payload


def _alignment_readiness_issue_payload_for_scenario(scenario: str, *, workdir: str) -> dict | None:
    if scenario == "alignment_generated_lineage_metadata":
        return alignment_response(
            status="bundle",
            assistant_message="I prepared a bundle but encoded source lineage metadata.",
            needs_user_input=False,
            bundle_yaml=alignment_bundle_yaml_with_lineage_metadata(workdir),
            phase="bundle",
        )
    if scenario == "alignment_markdown_fenced_bundle":
        return alignment_response(
            status="bundle",
            assistant_message="I prepared a fenced bundle.",
            needs_user_input=False,
            bundle_yaml=f"```yaml\n{alignment_bundle_yaml(workdir)}```",
            phase="bundle",
        )
    if scenario == "alignment_missing_readiness_evidence":
        payload = alignment_response(
            status="bundle",
            assistant_message="我勾选了 checklist 但没有给出具体证据。",
            needs_user_input=False,
            bundle_yaml=alignment_bundle_yaml(workdir),
            phase="bundle",
        )
        payload["readiness_evidence"] = {
            "loop_fit": "ok",
            "task_scope": "ok",
            "success_surface": "ok",
            "fake_done_risks": "ok",
            "evidence_preferences": "ok",
            "residual_risk_policy": "ok",
            "judgment_tradeoffs": "ok",
            "role_posture": "ok",
            "workflow_shape": "ok",
            "workdir_facts": "ok",
            "open_questions": "",
        }
        return payload
    issue = _alignment_readiness_issue_for_scenario(scenario)
    if issue is None:
        return None
    field, evidence_text, assistant_message = issue
    payload = alignment_response(
        status="bundle",
        assistant_message=assistant_message,
        needs_user_input=False,
        bundle_yaml=alignment_bundle_yaml(workdir),
        phase="bundle",
    )
    payload["readiness_evidence"][field] = evidence_text
    return payload


def _alignment_readiness_issue_for_scenario(scenario: str) -> tuple[str, str, str] | None:
    issues = {
        "alignment_missing_residual_risk_readiness_evidence": (
            "residual_risk_policy",
            "",
            "我生成了 bundle，但没有说明残余风险策略。",
        ),
        "alignment_missing_loop_fit_readiness_evidence": (
            "loop_fit",
            "",
            "我生成了 bundle，但没有说明为什么需要 Loopora。",
        ),
        "alignment_vague_loop_fit_readiness_evidence": (
            "loop_fit",
            "This is a complex and important task with many parts to handle well.",
            "我生成了 bundle，但只说任务复杂。",
        ),
        "alignment_vague_task_scope_readiness_evidence": (
            "task_scope",
            "The task scope is clear enough to handle well.",
            "我生成了 bundle，但任务范围没有交付物或边界。",
        ),
        "alignment_vague_success_surface_readiness_evidence": (
            "success_surface",
            "The final result should be good and useful for the user.",
            "我生成了 bundle，但成功面没有可观察结果或证据面。",
        ),
        "alignment_single_marker_loop_fit_readiness_evidence": (
            "loop_fit",
            "This task needs human review before the user accepts the final result.",
            "我生成了 bundle，但只提到人工 review，没有说明 Loop 价值。",
        ),
        "alignment_loop_fit_without_new_evidence_readiness_evidence": (
            "loop_fit",
            "One Agent pass plus review is not enough because fake-done risk and GateKeeper judgment matter.",
            "我生成了 bundle，但没有说明后续轮次会产生什么新证据。",
        ),
        "alignment_vague_residual_risk_readiness_evidence": (
            "residual_risk_policy",
            "Some remaining risk is probably fine for this task.",
            "我生成了 bundle，但残余风险策略很泛。",
        ),
        "alignment_invented_workdir_facts_readiness_evidence": (
            "workdir_facts",
            "This is a React frontend app with existing browser tests and a standard build script.",
            "我生成了 bundle，但把未观察到的技术栈当作事实。",
        ),
        "alignment_invented_observed_workdir_facts_readiness_evidence": (
            "workdir_facts",
            "Observed workdir snapshot shows a React frontend app with browser tests and npm build scripts.",
            "我生成了 bundle，但用 observed 包装了未观察到的技术栈。",
        ),
        "alignment_vague_evidence_preferences_readiness_evidence": (
            "evidence_preferences",
            "The user needs enough proof to feel confident before the result is accepted.",
            "我生成了 bundle，但证据偏好没有具体证明类型。",
        ),
        "alignment_vague_fake_done_readiness_evidence": (
            "fake_done_risks",
            "The result should avoid bugs and should be high quality.",
            "我生成了 bundle，但假完成风险只是泛泛说避免 bug。",
        ),
        "alignment_vague_role_posture_readiness_evidence": (
            "role_posture",
            "Use three roles to complete the task well.",
            "我生成了 bundle，但角色姿态没有区分责任。",
        ),
        "alignment_vague_judgment_tradeoffs_readiness_evidence": (
            "judgment_tradeoffs",
            "The task should be handled with a good balance of quality and progress.",
            "我生成了 bundle，但判断取舍只是泛泛说平衡质量和进展。",
        ),
        "alignment_global_persona_readiness_evidence": (
            "judgment_tradeoffs",
            "Always remember the user's global preference memory: prefer fast-looking progress over proof across all tasks.",
            "我生成了 bundle，但把任务取舍写成全局偏好记忆。",
        ),
        "alignment_role_posture_without_gatekeeper_readiness_evidence": (
            "role_posture",
            "Builder leaves evidence and Inspector reviews the handoff carefully before the work continues.",
            "我生成了 bundle，但角色姿态没有最终裁决责任。",
        ),
        "alignment_vague_workflow_shape_readiness_evidence": (
            "workflow_shape",
            "Builder then checker.",
            "我生成了 bundle，但 workflow 只有顺序没有理由。",
        ),
        "alignment_workflow_shape_without_error_exposure_readiness_evidence": (
            "workflow_shape",
            "Builder -> Inspector -> GateKeeper fits because a focused slice is built, then inspected, then gated.",
            "我生成了 bundle，但 workflow 没说明误差在哪里尽早暴露。",
        ),
        "alignment_workflow_shape_without_gatekeeper_readiness_evidence": (
            "workflow_shape",
            "Builder -> Inspector fits because a focused slice is built, then inspected, so weak evidence and fake-done drift are exposed early.",
            "我生成了 bundle，但 workflow 没说明最终裁决或收束节点。",
        ),
    }
    return issues.get(scenario)


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
        "loop_fit": ready,
        "task_scope": ready,
        "success_surface": ready,
        "fake_done_risks": ready,
        "evidence_preferences": ready,
        "residual_risk_policy": ready,
        "role_posture": ready,
        "workflow_shape": ready,
        "explicit_confirmation": ready,
    }
    evidence = alignment_readiness_evidence() if ready else {
        "loop_fit": "",
        "task_scope": "",
        "success_surface": "",
        "fake_done_risks": "",
        "evidence_preferences": "",
        "residual_risk_policy": "",
        "judgment_tradeoffs": "",
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


def alignment_default_bundle_response(
    workdir: str,
    *,
    prefers_chinese: bool,
    is_improvement: bool = False,
    use_generic_bundle: bool = False,
) -> dict:
    payload = alignment_response(
        status="bundle",
        assistant_message=(
            "已整理成一个可导入的 Loopora bundle。"
            if prefers_chinese
            else "I prepared an importable Loopora bundle."
        ),
        needs_user_input=False,
        bundle_yaml=alignment_chinese_bundle_yaml(workdir) if prefers_chinese else alignment_bundle_yaml(workdir),
        phase="bundle",
    )
    if prefers_chinese:
        payload["agreement_summary"] = "使用聚焦 Builder、证据 Inspector 和严格 GateKeeper 来生成这个 Loop 方案。"
        payload["readiness_evidence"] = alignment_chinese_readiness_evidence()
    if is_improvement:
        payload["agreement_summary"] = (
            "保留既有 Loop 的稳定意图，并基于反馈修订证据、角色和 GateKeeper 裁决。"
            if prefers_chinese
            else "Preserve the source Loop's stable intent while changing evidence, role posture, and GateKeeper judgment from feedback."
        )
        payload["readiness_evidence"] = (
            alignment_chinese_improvement_readiness_evidence()
            if prefers_chinese
            else alignment_improvement_readiness_evidence()
        )
        if not use_generic_bundle:
            payload["bundle_yaml"] = (
                alignment_chinese_improvement_bundle_yaml(workdir)
                if prefers_chinese
                else alignment_improvement_bundle_yaml(workdir)
            )
    return payload


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
            "loop_fit": True,
            "task_scope": True,
            "success_surface": True,
            "fake_done_risks": True,
            "evidence_preferences": True,
            "residual_risk_policy": True,
            "role_posture": True,
            "workflow_shape": True,
            "explicit_confirmation": False,
        },
        "readiness_evidence": alignment_readiness_evidence(
            open_questions="Waiting for explicit user confirmation of the working agreement."
        ),
    }


def alignment_chinese_agreement_response() -> dict:
    payload = alignment_agreement_response()
    payload["agreement_summary"] = "使用聚焦 Builder、证据 Inspector 和严格 GateKeeper 来推进这个 Loop。"
    payload["readiness_evidence"] = alignment_chinese_readiness_evidence(
        open_questions="等待用户明确确认这份工作协议。"
    )
    return payload


def alignment_improvement_agreement_response() -> dict:
    payload = alignment_agreement_response()
    payload["assistant_message"] = "Please confirm this improvement agreement; I will preserve the stable source Loop and revise only the feedback-driven governance surfaces."
    payload["agreement_summary"] = (
        "Preserve the existing Loop's stable task intent and workdir, then change the evidence, role posture, and GateKeeper strictness that feedback shows are weak."
    )
    payload["readiness_evidence"] = alignment_improvement_readiness_evidence(
        open_questions="Waiting for explicit user confirmation of the improvement agreement."
    )
    return payload


def alignment_chinese_improvement_agreement_response() -> dict:
    payload = alignment_chinese_agreement_response()
    payload["assistant_message"] = "请确认这份改进协议；我会保留既有 Loop 的稳定意图，只修订反馈指向的治理面。"
    payload["agreement_summary"] = "保留既有 Loop 的稳定任务意图和 workdir，并基于反馈改进证据、角色姿态和 GateKeeper 严格度。"
    payload["readiness_evidence"] = alignment_chinese_improvement_readiness_evidence(
        open_questions="等待用户明确确认这份改进协议。"
    )
    return payload


def alignment_readiness_evidence(*, open_questions: str = "") -> dict:
    return {
        "loop_fit": "The task is fit for Loopora because future rounds must produce evidence and GateKeeper judgment, not only a one-pass answer.",
        "task_scope": "The user wants a focused starter experience, not an open-ended role or workflow exercise.",
        "success_surface": "Success means the primary user flow works end to end and can be verified from project-owned evidence.",
        "fake_done_risks": "The loop should reject vague completion claims, happy-path-only work, and output without reproducible proof.",
        "evidence_preferences": "The strongest evidence is direct command output, tests, or concrete artifacts created by the project. Final evidence should distinguish Proven, Weak, Unproven, Blocking, and Residual risk buckets before GateKeeper closes.",
        "residual_risk_policy": "Minor polish gaps may remain only when named; unproven primary-flow behavior or weak verification must block closure.",
        "judgment_tradeoffs": "Prefer a smaller real flow with proof over a polished-looking result without evidence; reject speed gains when they hide fake-done risk.",
        "role_posture": "Builder keeps the patch narrow, Inspector collects evidence, and GateKeeper fails closed on weak proof.",
        "workflow_shape": "Builder -> Inspector -> GateKeeper fits because a focused slice is built, then inspected, then gated so weak evidence and fake-done drift are exposed early before closure.",
        "workdir_facts": "Observed workdir context is limited to the provided target path; exact stack facts are unknown and must be verified during the run.",
        "open_questions": open_questions,
    }


def alignment_improvement_readiness_evidence(*, open_questions: str = "") -> dict:
    return {
        "loop_fit": "The revision still fits Loopora because source feedback and future rounds need new evidence plus GateKeeper judgment, not only a one-pass edit.",
        "task_scope": "Preserve the source bundle's focused starter deliverable, workdir, and executor defaults; change only feedback-driven governance surfaces inside that boundary.",
        "success_surface": "Success means the revised standalone bundle keeps the existing user-facing goal while making evidence gaps observable and verifiable.",
        "fake_done_risks": "Reject a revision that only polishes wording, drops stable source intent, or claims improvement without translating feedback into spec, roles, workflow, or GateKeeper checks.",
        "evidence_preferences": "Use the source bundle plus run evidence, coverage summary, evidence summary, or GateKeeper verdict as proof before changing the Loop. The revision should preserve a final evidence projection across Proven, Weak, Unproven, Blocking, and Residual risk buckets.",
        "residual_risk_policy": "Stable intent, workdir, and executor defaults may remain unchanged; unaddressed feedback, missing evidence translation, or weaker GateKeeper strictness must block closure.",
        "judgment_tradeoffs": "Prefer preserving stable source intent over broad rewrites, but reject a superficially unchanged bundle if feedback shows evidence or GateKeeper strictness must change.",
        "role_posture": "Preserve useful Builder caution, change Inspector responsibilities around evidence gaps, and keep GateKeeper strict with clear blockers and handoffs.",
        "workflow_shape": "Preserve the basic Builder -> Inspector -> GateKeeper order unless feedback requires bounded parallel inspection; change inputs and handoffs because evidence gaps need explicit review and early exposure before GateKeeper closure.",
        "workdir_facts": "Observed source context is the current bundle or run evidence snapshot; exact stack facts remain unknown assumptions until roles verify them.",
        "open_questions": open_questions,
    }


def alignment_chinese_readiness_evidence(*, open_questions: str = "") -> dict:
    return {
        "loop_fit": "这项任务适合 Loopora，因为不是一次 Agent 加人工 review 就够；后续轮次需要新证据和 GateKeeper 裁决。",
        "task_scope": "用户要的是聚焦的 starter experience，而不是开放式角色设定或泛泛流程练习。",
        "success_surface": "成功意味着主流程端到端可用，并能由项目自己的证据验证。",
        "fake_done_risks": "循环应拒绝看起来完成、只覆盖 happy path、没有可复现证明的声称。",
        "evidence_preferences": "优先使用测试、命令输出、项目产物和角色交接作为证明；最终证据必须区分已证明、弱证据、未证明、阻断和残余风险。",
        "residual_risk_policy": "可接受的残余风险必须明确说明；主流程未验证或证据薄弱必须阻断。",
        "judgment_tradeoffs": "优先选择有证据的小而真实主流程，而不是看起来更完整但缺少 proof 的结果；如果速度会隐藏假完成风险，就应拒绝速度收益。",
        "role_posture": "Builder 聚焦构建，Inspector 收集证据，GateKeeper 严格依据交接与证据裁决。",
        "workflow_shape": "先由 Builder 实现，再由 Inspector 检查证据，最后 GateKeeper 裁决，因为信息流需要逐步收敛，并让证据薄弱、偏差或假完成尽早暴露。",
        "workdir_facts": "已观察到的工作区事实只限当前目标路径；具体技术栈仍未知，运行时必须验证。",
        "open_questions": open_questions,
    }


def alignment_chinese_improvement_readiness_evidence(*, open_questions: str = "") -> dict:
    return {
        "loop_fit": "这次修订仍适合 Loopora，因为不是一次编辑就够；已有反馈和后续轮次需要新证据与 GateKeeper 裁决。",
        "task_scope": "保留来源 bundle 的聚焦交付物、workdir 和 executor 默认值，只在反馈指向的治理面内调整边界。",
        "success_surface": "成功意味着修订后的独立 bundle 保持既有用户目标，同时让证据缺口可观察、可验证。",
        "fake_done_risks": "应拒绝只润色文案、丢掉稳定来源意图，或没有把反馈转成 spec、roles、workflow、GateKeeper 检查的改进声称。",
        "evidence_preferences": "优先使用来源 bundle、运行证据、coverage summary、evidence summary 或 GateKeeper verdict 来证明哪些 Loop 面需要改；修订后仍要区分已证明、弱证据、未证明、阻断和残余风险。",
        "residual_risk_policy": "稳定意图、workdir 和 executor 默认值可以保持不变；未处理的反馈、缺少证据转译或更弱的 GateKeeper 严格度必须阻断。",
        "judgment_tradeoffs": "优先保留来源 Loop 的稳定意图，而不是为了显得变化大而重写；但如果反馈证明证据或 GateKeeper 严格度不足，就应拒绝只保持原样的改进。",
        "role_posture": "保留 Builder 的有用谨慎，调整 Inspector 对证据缺口的责任，并让 GateKeeper 继续用清晰 blocker 和 handoff 严格裁决。",
        "workflow_shape": "保留 Builder -> Inspector -> GateKeeper 的基本顺序，除非反馈要求有界并行检查；因为证据缺口需要显式 review，所以要调整 inputs 和 handoffs，让偏差或证据薄弱在 GateKeeper 收束前提前暴露。",
        "workdir_facts": "已观察到的来源上下文是当前 bundle 或 run evidence 快照；具体技术栈仍是未知假设，需由后续角色验证。",
        "open_questions": open_questions,
    }


def alignment_bundle_yaml(workdir: str) -> str:
    return f"""version: 1
metadata:
  name: "Aligned Starter Bundle"
  description: "Bundle generated by the Web alignment flow."
collaboration_summary: |
  Project the working agreement into a spec task contract for the focused starter slice, role handoffs from Builder / Inspectors / GateKeeper, and a workflow that routes evidence before final judgment. Prefer a smaller proven flow over polished but unproven breadth, and let GateKeeper reject speed or surface completeness when evidence is weak. GateKeeper closes only when the spec, role evidence, and workflow handoffs prove the task is truly done. Evidence projection must distinguish Proven direct run proof, Weak indirect evidence, Unproven promised surfaces, Blocking fake-done findings, and visible Residual risk.
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

    Ship the focused starter experience in the target workdir with small, maintainable changes that preserve the primary user flow.

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
    - Final evidence should be bucketed as Proven, Weak, Unproven, Blocking, or Residual risk instead of flattened into one summary.

    # Residual Risk

    Accept minor polish gaps only when they are explicitly named; fail closed on unproven primary-flow behavior or weak verification evidence.

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
  - key: "contract-inspector"
    name: "Contract Inspector"
    description: "Checks the task contract, guardrails, fake-done risks, and residual-risk stance."
    archetype: "inspector"
    prompt_ref: "inspector.md"
    prompt_markdown: |
      ---
      version: 1
      archetype: inspector
      ---

      Inspect the Builder handoff against Done When, Guardrails, Fake Done, Evidence Preferences, and Residual Risk. Your handoff must identify contract mismatches, missing proof, and any blocker that should prevent GateKeeper from finishing.
    posture_notes: |
      Prefer contract-level proof over broad confidence; block when the delivered slice does not match the agreed scope or leaves fake-done risk unresolved.
    executor_kind: "codex"
    executor_mode: "preset"
    command_cli: ""
    command_args_text: ""
    model: ""
    reasoning_effort: ""
  - key: "evidence-inspector"
    name: "Evidence Inspector"
    description: "Collects reproducible evidence before sign-off."
    archetype: "inspector"
    prompt_ref: "inspector.md"
    prompt_markdown: |
      ---
      version: 1
      archetype: inspector
      ---

      Inspect from direct evidence, project-owned commands, and concrete artifacts. Your handoff must identify the strongest proof, missing proof, and any blocker that should prevent GateKeeper from finishing.
    posture_notes: |
      Prefer reproducible run output and concrete artifacts; block vague completion claims, screenshots without context, or unverified happy paths.
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
  collaboration_intent: "Build one focused starter slice, inspect the contract and evidence in parallel so weak evidence, drift, or fake done surface early, then let GateKeeper finish only when both inspection branches support the task contract."
  roles:
    - id: "builder"
      role_definition_key: "builder"
    - id: "contract_inspector"
      role_definition_key: "contract-inspector"
    - id: "evidence_inspector"
      role_definition_key: "evidence-inspector"
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
        iteration_memory: "summary_only"
    - id: "evidence_inspection_step"
      role_id: "evidence_inspector"
      parallel_group: "inspection_pack"
      inputs:
        handoffs_from: ["builder_step"]
        evidence_query:
          archetypes: ["builder"]
          limit: 12
        iteration_memory: "summary_only"
    - id: "gatekeeper_step"
      role_id: "gatekeeper"
      on_pass: "finish_run"
      inputs:
        handoffs_from: ["contract_inspection_step", "evidence_inspection_step"]
        evidence_query:
          archetypes: ["inspector", "builder"]
          limit: 24
"""


def alignment_chinese_bundle_yaml(workdir: str) -> str:
    yaml_text = alignment_bundle_yaml(workdir)
    replacements = {
        '  name: "Aligned Starter Bundle"': '  name: "对齐 Starter Bundle"',
        '  description: "Bundle generated by the Web alignment flow."': (
            '  description: "由 Web alignment flow 生成的 bundle。"'
        ),
        (
            "  Project the working agreement into a spec task contract for the focused starter slice, role handoffs from Builder / Inspectors / GateKeeper, and a workflow that routes evidence before final judgment. Prefer a smaller proven flow over polished but unproven breadth, and let GateKeeper reject speed or surface completeness when evidence is weak. GateKeeper closes only when the spec, role evidence, and workflow handoffs prove the task is truly done. Evidence projection must distinguish Proven direct run proof, Weak indirect evidence, Unproven promised surfaces, Blocking fake-done findings, and visible Residual risk.\n"
        ): (
            "  将工作协议投影到 spec 任务契约、Builder / Inspector / GateKeeper 角色交接，以及先汇集证据再裁决的 workflow。优先选择小而已证明的主流程，而不是打磨充分但未证明的宽泛功能；证据薄弱时让 GateKeeper 拒绝速度或表面完整性。GateKeeper 只有在任务契约、角色证据和 workflow handoff 都证明真实完成时才收束。证据投影必须区分已证明的直接运行证据、弱证据、未证明的承诺面、阻断类假完成，以及可见残余风险。\n"
        ),
        (
            "    Ship the focused starter experience in the target workdir with small, maintainable changes that preserve the primary user flow."
        ): (
            "    在目标 workdir 中交付聚焦的 starter experience，用小而可维护的改动保住主流程，并留下能让 Inspector 和 GateKeeper 验证真实完成的证据路径。"
        ),
        "    - The primary user flow works end to end.": "    - 主流程可以端到端运行。",
        "    - The implementation is covered by project-owned evidence.": "    - 实现有项目内证据覆盖。",
        "    - Keep changes scoped to the requested behavior.": "    - 改动保持在本次请求边界内。",
        (
            "    - The primary user flow is understandable, maintainable, and easy to extend after the first pass."
        ): "    - 主流程可理解、可维护，并且首轮后容易继续扩展。",
        "    - Do not pass with only a happy-path claim and no reproducible evidence.": (
            "    - 只有 happy path 声称、没有可复现证据时不得通过。"
        ),
        "    - Do not pass if the implementation lacks a handoff that explains what evidence was collected.": (
            "    - 缺少说明已收集证据的 handoff 时不得通过。"
        ),
        "    - Prefer project-owned checks, direct run output, and concrete artifacts before screenshots or claims.": (
            "    - 优先使用项目内检查、直接运行输出和具体产物，而不是截图或口头声称。"
        ),
        "    - Each role should leave a clear handoff note explaining what was changed, inspected, or blocked.": (
            "    - 每个角色都要留下清晰 handoff，说明改了什么、检查了什么或阻断了什么。"
        ),
        "    - Final evidence should be bucketed as Proven, Weak, Unproven, Blocking, or Residual risk instead of flattened into one summary.": (
            "    - 最终证据应区分为已证明、弱证据、未证明、阻断或残余风险，而不是压平成一段总结。"
        ),
        (
            "    Accept minor polish gaps only when they are explicitly named; fail closed on unproven primary-flow behavior or weak verification evidence."
        ): (
            "    只有明确点名的轻微 polish 缺口可以保留；主流程行为未证明或验证证据薄弱时必须 fail closed。"
        ),
        '    name: "Focused Builder"': '    name: "聚焦 Builder"',
        '    name: "Contract Inspector"': '    name: "契约 Inspector"',
        '    name: "Evidence Inspector"': '    name: "证据 Inspector"',
        '    name: "Conservative GateKeeper"': '    name: "审慎 GateKeeper"',
        "    Prefer a small maintainable patch over broad rewrites.": "    优先小而可维护的 patch，不做宽泛重写。",
        "    Collect reproducible evidence and call out missing proof plainly.": (
            "    收集可复现证据，并直接指出缺失的证明。"
        ),
        "    Fail closed when Done When, fake-done risks, and evidence preferences are not all satisfied.": (
            "    Done When、fake-done 风险和证据偏好没有同时满足时必须 fail closed。"
        ),
        '    description: "Implements the smallest maintainable change."': (
            '    description: "实现最小且可维护的变更。"'
        ),
        '    description: "Checks the task contract, guardrails, fake-done risks, and residual-risk stance."': (
            '    description: "检查任务契约、guardrails、fake-done 风险和残余风险姿态。"'
        ),
        '    description: "Collects reproducible evidence before sign-off."': (
            '    description: "在签字前收集可复现证据。"'
        ),
        '    description: "Fails closed when evidence is weak."': '    description: "证据薄弱时 fail closed。"',
        (
            "      Build the focused starter slice carefully and keep the repo coherent. Leave a handoff that names the changed behavior, the verification evidence, and any blocker that should stop Inspector or GateKeeper."
        ): (
            "      谨慎实现聚焦 starter slice，并保持 repo 一致。留下 handoff，点名变更行为、验证证据，以及应该阻止 Inspector 或 GateKeeper 的 blocker。"
        ),
        (
            "      Keep implementation narrow and leave the workspace easier to verify; prefer concrete evidence over broad feature spread."
        ): (
            "      保持实现收窄，让 workspace 更容易验证；优先具体证据和清晰 handoff，而不是铺开很多无法证明的功能。"
        ),
        (
            "      Inspect the Builder handoff against Done When, Guardrails, Fake Done, Evidence Preferences, and Residual Risk. Your handoff must identify contract mismatches, missing proof, and any blocker that should prevent GateKeeper from finishing."
        ): (
            "      根据 Done When、Guardrails、Fake Done、Evidence Preferences 和 Residual Risk 检查 Builder handoff。你的 handoff 必须指出契约不匹配、缺失证明，以及应阻止 GateKeeper 收束的 blocker。"
        ),
        (
            "      Prefer contract-level proof over broad confidence; block when the delivered slice does not match the agreed scope or leaves fake-done risk unresolved."
        ): (
            "      优先契约级证明，而不是泛泛信心；交付 slice 不符合约定范围或 fake-done 风险未解决时必须 block。"
        ),
        (
            "      Inspect from direct evidence, project-owned commands, and concrete artifacts. Your handoff must identify the strongest proof, missing proof, and any blocker that should prevent GateKeeper from finishing."
        ): (
            "      从直接证据、项目内命令和具体产物检查。你的 handoff 必须指出最强证明、缺失证明，以及应阻止 GateKeeper 收束的 blocker。"
        ),
        (
            "      Prefer reproducible run output and concrete artifacts; block vague completion claims, screenshots without context, or unverified happy paths."
        ): (
            "      优先可复现运行输出和具体产物；阻断空泛完成声称、缺上下文截图或未验证 happy path，并说明哪类证据还缺失。"
        ),
        (
            "      Decide from direct evidence and do not accept vague completion claims. Finish only when the Builder and Inspector handoffs prove the task contract; otherwise block with the smallest next repair."
        ): (
            "      只根据直接证据裁决，不接受空泛完成声称。只有 Builder 和 Inspector handoff 证明任务契约时才 finish；否则用最小下一步修复来 block。"
        ),
        (
            "      Close only when the task and verification evidence agree; fail closed when handoff evidence is missing or weak."
        ): (
            "      只有任务和验证证据一致时才收束；handoff evidence 缺失、薄弱或没有覆盖主流程时必须 fail closed。"
        ),
        (
            '  collaboration_intent: "Build one focused starter slice, inspect the contract and evidence in parallel so weak evidence, drift, or fake done surface early, then let GateKeeper finish only when both inspection branches support the task contract."'
        ): (
            '  collaboration_intent: "先构建一个聚焦 starter slice，再并行检查契约和证据，让证据薄弱、偏差或假完成提前暴露；只有两条检查分支都支持任务契约时，GateKeeper 才能 finish。"'
        ),
    }
    for old, new in replacements.items():
        yaml_text = yaml_text.replace(old, new)
    return yaml_text


def alignment_chinese_bundle_yaml_with_english_visible_names(workdir: str) -> str:
    yaml_text = alignment_chinese_bundle_yaml(workdir)
    replacements = {
        '  name: "对齐 Starter Bundle"': '  name: "Aligned Starter Bundle"',
        '  description: "由 Web alignment flow 生成的 bundle。"': (
            '  description: "Bundle generated by the Web alignment flow."'
        ),
        '    name: "聚焦 Builder"': '    name: "Focused Builder"',
        '    name: "契约 Inspector"': '    name: "Contract Inspector"',
        '    name: "证据 Inspector"': '    name: "Evidence Inspector"',
        '    name: "审慎 GateKeeper"': '    name: "Conservative GateKeeper"',
    }
    for old, new in replacements.items():
        yaml_text = yaml_text.replace(old, new)
    return yaml_text


def alignment_improvement_bundle_yaml(workdir: str) -> str:
    yaml_text = alignment_bundle_yaml(workdir)
    return yaml_text.replace(
        (
            "  Project the working agreement into a spec task contract for the focused starter slice, "
            "role handoffs from Builder / Inspectors / GateKeeper, and a workflow that routes evidence "
            "before final judgment. Prefer a smaller proven flow over polished but unproven breadth, "
            "and let GateKeeper reject speed or surface completeness when evidence is weak. GateKeeper "
            "closes only when the spec, role evidence, and workflow handoffs prove the task is truly done. "
            "Evidence projection must distinguish Proven direct run proof, Weak indirect evidence, Unproven "
            "promised surfaces, Blocking fake-done findings, and visible Residual risk.\n"
        ),
        (
            "  Preserve the source Loop's stable task intent, workdir, and useful role posture while "
            "changing the feedback-driven governance delta across spec, roles, workflow, evidence "
            "expectations, and GateKeeper strictness. Run evidence, coverage, evidence summary, and "
            "GateKeeper verdict should drive which claims become Proven, Weak, Unproven, Blocking, "
            "or visible Residual risk.\n"
        ),
    ).replace(
        "    - Prefer project-owned checks, direct run output, and concrete artifacts before screenshots or claims.\n",
        "    - Preserve source intent, but tighten evidence expectations from feedback, run evidence, coverage, and GateKeeper verdict before screenshots or claims.\n",
    ).replace(
        '  collaboration_intent: "Build one focused starter slice, inspect the contract and evidence in parallel so weak evidence, drift, or fake done surface early, then let GateKeeper finish only when both inspection branches support the task contract."',
        '  collaboration_intent: "Preserve the source Loop shape where it still fits, but route the feedback-driven evidence delta through parallel contract and evidence review so evidence gaps surface early before GateKeeper closes."',
    )


def alignment_chinese_improvement_bundle_yaml(workdir: str) -> str:
    yaml_text = alignment_chinese_bundle_yaml(workdir)
    return yaml_text.replace(
        (
            "  将工作协议投影到 spec 任务契约、Builder / Inspector / GateKeeper 角色交接，以及先汇集证据再裁决的 workflow。"
            "优先选择小而已证明的主流程，而不是打磨充分但未证明的宽泛功能；证据薄弱时让 GateKeeper 拒绝速度或表面完整性。"
            "GateKeeper 只有在任务契约、角色证据和 workflow handoff 都证明真实完成时才收束。"
            "证据投影必须区分已证明的直接运行证据、弱证据、未证明的承诺面、阻断类假完成，以及可见残余风险。\n"
        ),
        (
            "  保留来源 Loop 的稳定任务意图、workdir 和有用角色姿态，同时把反馈驱动的治理变化投影到 spec、roles、workflow、证据期望和 GateKeeper 严格度。"
            "运行证据、coverage、evidence summary 和 GateKeeper verdict 应决定哪些 claim 进入已证明、弱证据、未证明、阻断或可见残余风险。\n"
        ),
    ).replace(
        "    - 优先使用项目内检查、直接运行输出和具体产物，而不是截图或口头声称。\n",
        "    - 保留来源意图，但根据反馈、运行证据、coverage 和 GateKeeper verdict 收紧证据期望，而不是依赖截图或口头声称。\n",
    ).replace(
        '  collaboration_intent: "先构建一个聚焦 starter slice，再并行检查契约和证据，让证据薄弱、偏差或假完成提前暴露；只有两条检查分支都支持任务契约时，GateKeeper 才能 finish。"',
        '  collaboration_intent: "保留来源 Loop 中仍然有效的形状，但把反馈驱动的证据变化通过并行契约和证据 review 暴露出来，再路由到 GateKeeper 收束。"',
    )


def alignment_bundle_yaml_with_unsupported_observed_workdir_claim(workdir: str) -> str:
    yaml_text = alignment_bundle_yaml(workdir)
    return yaml_text.replace(
        (
            "    Ship the focused starter experience in the target workdir with small, maintainable changes that preserve the primary user flow."
        ),
        (
            "    Observed Workdir Snapshot shows a React frontend app with npm build scripts. "
            "Ship the focused starter experience with small, maintainable changes."
        ),
    )


def alignment_bundle_yaml_with_lineage_metadata(workdir: str) -> str:
    return alignment_bundle_yaml(workdir).replace(
        '  description: "Bundle generated by the Web alignment flow."\n',
        '  description: "Bundle generated by the Web alignment flow."\n'
        '  source_bundle_id: "source_bundle_old"\n'
        "  revision: 2\n",
        1,
    )


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
        "attempted": f"Iter {iter_id}: refine workdir against the frozen task contract",
        "abandoned": "Did not widen scope or lower Done When to make the iteration look complete.",
        "assumption": "The highest-impact gain is still the primary path with evidence Inspector can verify.",
        "summary": "Applied a focused change strategy and left the proof surface for Inspector and GateKeeper.",
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
                "notes": _fake_check_notes(check, status),
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
        "tester_observations": (
            "Fake executor evaluated the compiled Markdown checks against the frozen run contract; "
            "passed checks move toward Proven only through traceable evidence, while failed checks stay "
            "Blocking or Unproven for GateKeeper."
        ),
        "coverage_results": [],
    }


def _fake_check_notes(check: dict, status: str) -> str:
    base = str(check.get("expect") or check.get("details") or "").strip()
    if status == "passed":
        suffix = "Fake evidence treats this as Proven only through the inspector evidence ledger."
    else:
        suffix = "This remains Blocking or Unproven until a later Builder repair produces new proof."
    return f"{base} {suffix}".strip()


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
    evidence_claims = _fake_gatekeeper_evidence_claims(
        passed=passed,
        evidence_refs=evidence_refs,
        failed_check_ids=failed_check_ids,
    )
    return {
        "passed": passed,
        "decision_summary": (
            "Task verdict passes from upstream evidence refs; the run lifecycle alone is not proof."
            if passed
            else "Task verdict is not ready because Weak, Unproven, or Blocking evidence remains."
        ),
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
        "feedback_to_builder": "Repair the smallest Blocking or Unproven gap without lowering the frozen contract.",
        "feedback_to_generator": "Repair the smallest Blocking or Unproven gap without lowering the frozen contract.",
        "evidence_refs": evidence_refs if passed else [],
        "evidence_claims": evidence_claims,
    }


def _fake_gatekeeper_evidence_claims(
    *,
    passed: bool,
    evidence_refs: list[str],
    failed_check_ids: list[str],
) -> list[str]:
    if passed:
        joined_refs = ", ".join(evidence_refs) if evidence_refs else "measured gate metrics"
        return [
            (
                "Proven: GateKeeper cited upstream evidence refs "
                f"({joined_refs}) and kept run status separate from task verdict."
            )
        ]
    if failed_check_ids:
        joined_checks = ", ".join(failed_check_ids[:4])
        return [
            (
                "Blocking: compiled checks remain unpassed "
                f"({joined_checks}), so the task contract cannot be lowered to close the run."
            )
        ]
    return ["Unproven: quality evidence is still below the GateKeeper threshold."]


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
            "stagnation_pattern": "fake executor detected stalled gains with Weak or Unproven evidence.",
            "recommended_shift": "Try the smallest repair or proof that turns one Blocking or Unproven gap into Proven evidence.",
            "risk_note": "Changing direction too broadly may hide Residual risk or silently lower the frozen contract.",
        },
        "seed_question": "What is the smallest testable change that breaks the plateau?",
        "meta_note": "This is a suggestion, not a command.",
    }


def _custom_payload() -> dict:
    return {
        "status": "advisory",
        "summary": "Collected read-only evidence against the frozen contract and prepared a scoped handoff.",
        "blocking_items": [
            "A restricted role can guide the next move but cannot close the loop alone.",
        ],
        "recommended_next_action": "Use the strongest evidence path for the next change without lowering Done When.",
        "observations": [
            "The custom role stayed inside the current workspace evidence.",
            "No write action was claimed from this restricted role.",
        ],
        "recommendations": [
            "Use the strongest evidence path for the next change without lowering Done When.",
        ],
        "risks": [
            "A restricted role can guide the next move but cannot close the loop alone.",
        ],
        "handoff_note": "Pass these observations to a Builder or Inspector step.",
    }
