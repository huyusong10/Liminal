from __future__ import annotations

from loopora.executor import RoleRequest
from loopora.utils import append_jsonl, utc_now


def _truncate_summary_text(value: object, max_length: int = 220) -> str:
    text = str(value or "").strip()
    if len(text) <= max_length:
        return text
    return f"{text[: max_length - 1].rstrip()}..."


def _add_basic_context_summary(summary: dict[str, object], extra_context: dict) -> None:
    for key in ("iter_id", "step_id", "role_name", "archetype"):
        value = extra_context.get(key)
        if value is not None:
            summary[key] = value
    step_model = extra_context.get("step_model")
    if step_model:
        summary["step_model"] = step_model
    if "inherit_session" in extra_context:
        summary["inherit_session"] = bool(extra_context.get("inherit_session"))
    for key in ("extra_cli_args_text", "resume_session_id"):
        text = str(extra_context.get(key) or "").strip()
        if text:
            summary[key] = text


def _dict_context(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _add_contract_context_summary(summary: dict[str, object], extra_context: dict) -> None:
    compiled_spec = extra_context.get("compiled_spec")
    if isinstance(compiled_spec, dict):
        summary["compiled_spec"] = {
            "check_mode": compiled_spec.get("check_mode"),
            "check_count": len(compiled_spec.get("checks", [])),
        }
    context_packet = extra_context.get("context_packet")
    if isinstance(context_packet, dict):
        iteration = _dict_context(context_packet.get("iteration"))
        current_step = _dict_context(context_packet.get("current_step"))
        upstream = _dict_context(context_packet.get("upstream"))
        summary["context_packet"] = {
            "iter_index": iteration.get("iter_index"),
            "step_order": current_step.get("step_order"),
            "previous_iteration_exists": iteration.get("previous_iteration_exists"),
            "evidence_progress_mode": iteration.get("evidence_progress_mode"),
            "coverage_status": iteration.get("coverage_status"),
            "covered_check_count": iteration.get("covered_check_count"),
            "missing_check_count": iteration.get("missing_check_count"),
            "covered_check_ids": list(iteration.get("covered_check_ids") or [])[:8],
            "missing_check_ids": list(iteration.get("missing_check_ids") or [])[:8],
            "coverage_top_gaps": list(iteration.get("coverage_top_gaps") or [])[:5],
            "completed_steps_this_iteration": len(upstream.get("completed_steps_this_iteration", [])),
        }


def _add_archetype_context_summary(summary: dict[str, object], extra_context: dict) -> None:
    for key in ("current_outputs_by_archetype", "previous_outputs_by_archetype"):
        value = extra_context.get(key)
        if isinstance(value, dict) and value:
            summary[key] = sorted(value.keys())


def _previous_generator_summary(value: dict) -> dict:
    return {
        "attempted": _truncate_summary_text(value.get("attempted"), 160),
        "summary": _truncate_summary_text(value.get("summary"), 160),
    }


def _previous_tester_summary(value: dict) -> dict:
    return {
        "failed_items": [item.get("title") or item.get("id") for item in list(value.get("failed_items", []))[:4]],
        "tester_observations": _truncate_summary_text(value.get("tester_observations"), 160),
    }


def _previous_verifier_summary(value: dict) -> dict:
    return {
        "passed": value.get("passed"),
        "composite_score": value.get("composite_score"),
        "failed_check_titles": list(value.get("failed_check_titles", []))[:4],
        "next_actions": list(value.get("next_actions", []))[:4],
    }


def _previous_challenger_summary(value: dict) -> dict:
    return {
        "mode": value.get("mode"),
        "recommended_shift": _truncate_summary_text(
            _dict_context(value.get("analysis")).get("recommended_shift"),
            160,
        ),
        "seed_question": _truncate_summary_text(value.get("seed_question"), 160),
    }


def _add_previous_role_summaries(summary: dict[str, object], extra_context: dict) -> None:
    builders = (
        ("previous_generator_result", _previous_generator_summary),
        ("previous_tester_result", _previous_tester_summary),
        ("previous_verifier_result", _previous_verifier_summary),
        ("previous_challenger_result", _previous_challenger_summary),
    )
    for key, build_summary in builders:
        value = extra_context.get(key)
        if isinstance(value, dict) and value:
            summary[key] = build_summary(value)


def _add_runtime_context_summary(summary: dict[str, object], extra_context: dict) -> None:
    tester_output = extra_context.get("tester_output")
    if isinstance(tester_output, dict):
        execution_summary = _dict_context(tester_output.get("execution_summary"))
        summary["tester_output"] = {
            "passed": execution_summary.get("passed"),
            "failed": execution_summary.get("failed"),
            "dynamic_failed": len(tester_output.get("dynamic_check_failures", [])),
        }
    immediate_previous_step = extra_context.get("immediate_previous_step")
    if isinstance(immediate_previous_step, dict):
        source = _dict_context(immediate_previous_step.get("source"))
        summary["immediate_previous_step"] = {
            "step_id": source.get("step_id"),
            "role_name": source.get("role_name"),
            "status": immediate_previous_step.get("status"),
        }
    previous_iteration_summary = extra_context.get("previous_iteration_summary")
    if isinstance(previous_iteration_summary, dict):
        score = _dict_context(previous_iteration_summary.get("score"))
        stagnation = _dict_context(previous_iteration_summary.get("stagnation"))
        gatekeeper_verdict = _dict_context(previous_iteration_summary.get("gatekeeper_verdict"))
        summary["previous_iteration_summary"] = {
            "iter": previous_iteration_summary.get("iter"),
            "composite": score.get("composite"),
            "passed": score.get("passed"),
            "evidence_progress_mode": stagnation.get("evidence_progress_mode"),
            "coverage_status": stagnation.get("coverage_status"),
            "covered_check_count": stagnation.get("covered_check_count"),
            "missing_check_count": stagnation.get("missing_check_count"),
            "missing_check_ids": list(stagnation.get("missing_check_ids") or [])[:8],
            "coverage_top_gaps": list(stagnation.get("coverage_top_gaps") or [])[:5],
            "gatekeeper_blocking_count": len(gatekeeper_verdict.get("blocking_issues") or []),
            "gatekeeper_residual_risk_count": len(gatekeeper_verdict.get("residual_risks") or []),
        }
    stagnation_mode = extra_context.get("stagnation_mode")
    if stagnation_mode is not None:
        summary["stagnation_mode"] = stagnation_mode
    evidence_progress_mode = extra_context.get("evidence_progress_mode")
    if evidence_progress_mode is not None:
        summary["evidence_progress_mode"] = evidence_progress_mode


class ServiceRoleRequestMixin:
    def _record_role_request(self, run_id: str, request: RoleRequest) -> None:
        layout = self._run_artifact_layout(request.run_dir)
        request_dir = layout.context_dir / "role_requests"
        request_dir.mkdir(parents=True, exist_ok=True)
        base_name = self._role_request_basename(request)
        prompt_path = request_dir / f"{base_name}.prompt.txt"
        prompt_path.write_text(request.prompt, encoding="utf-8")
        step_prompt_path = request.output_path.parent / "prompt.md"
        step_prompt_path.parent.mkdir(parents=True, exist_ok=True)
        step_prompt_path.write_text(request.prompt, encoding="utf-8")
        payload = {
            "timestamp": utc_now(),
            "role": request.role,
            "role_archetype": request.role_archetype,
            "role_name": request.role_name,
            "step_id": request.step_id,
            "iter": request.extra_context.get("iter_id"),
            "executor_kind": request.executor_kind,
            "executor_mode": request.executor_mode,
            "inherit_session": request.inherit_session,
            "resume_session_id": request.resume_session_id,
            "extra_cli_args_text": request.extra_cli_args_text,
            "model": request.model,
            "reasoning_effort": request.reasoning_effort,
            "sandbox": request.sandbox,
            "workdir": str(request.workdir),
            "output_path": layout.relative(request.output_path),
            "prompt_path": layout.relative(prompt_path),
            "step_prompt_path": layout.relative(step_prompt_path),
            "extra_context_keys": sorted(request.extra_context.keys()),
            "context_summary": self._summarize_role_request_context(request.extra_context),
        }
        append_jsonl(layout.role_requests_path, payload)
        self.append_run_event(run_id, "role_request_prepared", payload, role=request.role)

    def _role_request_basename(self, request: RoleRequest) -> str:
        iter_id = request.extra_context.get("iter_id")
        if isinstance(iter_id, int):
            return f"iter_{iter_id:03d}_{request.role}"
        return request.role

    def _summarize_role_request_context(self, extra_context: dict) -> dict:
        summary: dict[str, object] = {}
        _add_basic_context_summary(summary, extra_context)
        _add_contract_context_summary(summary, extra_context)
        _add_archetype_context_summary(summary, extra_context)
        _add_previous_role_summaries(summary, extra_context)
        _add_runtime_context_summary(summary, extra_context)
        return summary

    @staticmethod
    def _truncate_text(value: str | None, max_length: int = 220) -> str:
        return _truncate_summary_text(value, max_length)
