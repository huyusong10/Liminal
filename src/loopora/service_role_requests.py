from __future__ import annotations

from loopora.executor import RoleRequest
from loopora.utils import append_jsonl, utc_now


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
        self.repository.append_event(run_id, "role_request_prepared", payload, role=request.role)

    def _role_request_basename(self, request: RoleRequest) -> str:
        iter_id = request.extra_context.get("iter_id")
        if isinstance(iter_id, int):
            return f"iter_{iter_id:03d}_{request.role}"
        return request.role

    def _summarize_role_request_context(self, extra_context: dict) -> dict:
        summary: dict[str, object] = {}
        iter_id = extra_context.get("iter_id")
        if iter_id is not None:
            summary["iter_id"] = iter_id
        step_id = extra_context.get("step_id")
        if step_id is not None:
            summary["step_id"] = step_id
        role_name = extra_context.get("role_name")
        if role_name is not None:
            summary["role_name"] = role_name
        archetype = extra_context.get("archetype")
        if archetype is not None:
            summary["archetype"] = archetype
        step_model = extra_context.get("step_model")
        if step_model:
            summary["step_model"] = step_model
        if "inherit_session" in extra_context:
            summary["inherit_session"] = bool(extra_context.get("inherit_session"))
        extra_cli_args_text = str(extra_context.get("extra_cli_args_text") or "").strip()
        if extra_cli_args_text:
            summary["extra_cli_args_text"] = extra_cli_args_text
        resume_session_id = str(extra_context.get("resume_session_id") or "").strip()
        if resume_session_id:
            summary["resume_session_id"] = resume_session_id
        compiled_spec = extra_context.get("compiled_spec")
        if isinstance(compiled_spec, dict):
            summary["compiled_spec"] = {
                "check_mode": compiled_spec.get("check_mode"),
                "check_count": len(compiled_spec.get("checks", [])),
            }
        context_packet = extra_context.get("context_packet")
        if isinstance(context_packet, dict):
            summary["context_packet"] = {
                "iter_index": context_packet.get("iteration", {}).get("iter_index"),
                "step_order": context_packet.get("current_step", {}).get("step_order"),
                "previous_iteration_exists": context_packet.get("iteration", {}).get("previous_iteration_exists"),
                "completed_steps_this_iteration": len(
                    context_packet.get("upstream", {}).get("completed_steps_this_iteration", [])
                ),
            }
        current_outputs_by_archetype = extra_context.get("current_outputs_by_archetype")
        if isinstance(current_outputs_by_archetype, dict) and current_outputs_by_archetype:
            summary["current_outputs_by_archetype"] = sorted(current_outputs_by_archetype.keys())
        previous_outputs_by_archetype = extra_context.get("previous_outputs_by_archetype")
        if isinstance(previous_outputs_by_archetype, dict) and previous_outputs_by_archetype:
            summary["previous_outputs_by_archetype"] = sorted(previous_outputs_by_archetype.keys())
        previous_generator_result = extra_context.get("previous_generator_result")
        if isinstance(previous_generator_result, dict) and previous_generator_result:
            summary["previous_generator_result"] = {
                "attempted": self._truncate_text(previous_generator_result.get("attempted"), 160),
                "summary": self._truncate_text(previous_generator_result.get("summary"), 160),
            }
        previous_tester_result = extra_context.get("previous_tester_result")
        if isinstance(previous_tester_result, dict) and previous_tester_result:
            summary["previous_tester_result"] = {
                "failed_items": [
                    item.get("title") or item.get("id")
                    for item in previous_tester_result.get("failed_items", [])[:4]
                ],
                "tester_observations": self._truncate_text(previous_tester_result.get("tester_observations"), 160),
            }
        previous_verifier_result = extra_context.get("previous_verifier_result")
        if isinstance(previous_verifier_result, dict) and previous_verifier_result:
            summary["previous_verifier_result"] = {
                "passed": previous_verifier_result.get("passed"),
                "composite_score": previous_verifier_result.get("composite_score"),
                "failed_check_titles": list(previous_verifier_result.get("failed_check_titles", []))[:4],
                "next_actions": list(previous_verifier_result.get("next_actions", []))[:4],
            }
        previous_challenger_result = extra_context.get("previous_challenger_result")
        if isinstance(previous_challenger_result, dict) and previous_challenger_result:
            summary["previous_challenger_result"] = {
                "mode": previous_challenger_result.get("mode"),
                "recommended_shift": self._truncate_text(
                    (previous_challenger_result.get("analysis") or {}).get("recommended_shift"),
                    160,
                ),
                "seed_question": self._truncate_text(previous_challenger_result.get("seed_question"), 160),
            }
        tester_output = extra_context.get("tester_output")
        if isinstance(tester_output, dict):
            summary["tester_output"] = {
                "passed": tester_output.get("execution_summary", {}).get("passed"),
                "failed": tester_output.get("execution_summary", {}).get("failed"),
                "dynamic_failed": len(tester_output.get("dynamic_check_failures", [])),
            }
        immediate_previous_step = extra_context.get("immediate_previous_step")
        if isinstance(immediate_previous_step, dict):
            summary["immediate_previous_step"] = {
                "step_id": immediate_previous_step.get("source", {}).get("step_id"),
                "role_name": immediate_previous_step.get("source", {}).get("role_name"),
                "status": immediate_previous_step.get("status"),
            }
        previous_iteration_summary = extra_context.get("previous_iteration_summary")
        if isinstance(previous_iteration_summary, dict):
            summary["previous_iteration_summary"] = {
                "iter": previous_iteration_summary.get("iter"),
                "composite": previous_iteration_summary.get("score", {}).get("composite"),
                "passed": previous_iteration_summary.get("score", {}).get("passed"),
            }
        stagnation_mode = extra_context.get("stagnation_mode")
        if stagnation_mode is not None:
            summary["stagnation_mode"] = stagnation_mode
        return summary

    @staticmethod
    def _truncate_text(value: str | None, max_length: int = 220) -> str:
        text = str(value or "").strip()
        if len(text) <= max_length:
            return text
        return f"{text[: max_length - 1].rstrip()}..."
