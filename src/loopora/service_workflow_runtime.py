from __future__ import annotations

from pathlib import Path

from loopora.context_flow import build_step_context_packet, output_contract_prompt, render_step_prompt, system_prompt_prefix
from loopora.executor import CodexExecutor, RoleRequest, coerce_reasoning_effort, normalize_reasoning_effort, validate_command_args_text
from loopora.providers import executor_profile, normalize_executor_kind, normalize_executor_mode
from loopora.recovery import RetryConfig
from loopora.run_artifacts import RunArtifactLayout
from loopora.service_types import LooporaError
from loopora.utils import write_json
from loopora.workflows import WorkflowError, role_uses_execution_snapshot


class ServiceWorkflowRuntimeMixin:
    def _run_workflow_step(
        self,
        executor: CodexExecutor,
        run: dict,
        compiled_spec: dict,
        layout: RunArtifactLayout,
        iter_id: int,
        step: dict,
        step_order: int,
        role: dict,
        prompt_files: dict[str, str],
        execution_settings: dict[str, object],
        *,
        run_contract: dict,
        current_outputs_by_step: dict[str, dict],
        current_outputs_by_role: dict[str, dict],
        current_outputs_by_archetype: dict[str, dict],
        current_handoffs: list[dict],
        previous_outputs_by_step: dict[str, dict],
        previous_outputs_by_role: dict[str, dict],
        previous_outputs_by_archetype: dict[str, dict],
        previous_handoffs_by_step: dict[str, dict],
        previous_handoffs_by_role: dict[str, dict],
        previous_iteration_summary: dict | None,
        previous_session_refs_by_step: dict[str, dict],
        previous_composite: float | None,
        stagnation_mode: str,
        retry_config: RetryConfig,
    ) -> tuple[dict, dict, dict]:
        step_dir = layout.step_dir(iter_id, step_order, step["id"])
        step_dir.mkdir(parents=True, exist_ok=True)
        output_path = layout.step_output_raw_path(iter_id, step_order, step["id"])
        prompt_metadata, prompt_body = self._parse_runtime_prompt(
            prompt_files[role["prompt_ref"]],
            expected_archetype=role["archetype"],
        )
        runtime_role = self._runtime_role_key(role)
        context_packet = build_step_context_packet(
            run_contract=run_contract,
            layout=layout,
            iter_id=iter_id,
            step=step,
            step_order=step_order,
            role=role,
            execution_settings=execution_settings,
            immediate_previous_step=current_handoffs[-1] if current_handoffs else None,
            completed_steps_this_iteration=current_handoffs,
            previous_iteration_same_step=previous_handoffs_by_step.get(step["id"]),
            previous_iteration_same_role=previous_handoffs_by_role.get(role["id"]),
            previous_iteration_summary=previous_iteration_summary,
            previous_composite=previous_composite,
            stagnation_mode=stagnation_mode,
        )
        context_path = layout.step_context_path(iter_id, step_order, step["id"])
        write_json(context_path, context_packet)
        self.repository.append_event(
            run["id"],
            "step_context_prepared",
            {
                "iter": iter_id,
                "step_id": step["id"],
                "step_order": step_order,
                "role_name": role["name"],
                "archetype": role["archetype"],
                "context_path": layout.relative(context_path),
                "previous_iteration_exists": context_packet["iteration"]["previous_iteration_exists"],
                "completed_steps_this_iteration": len(current_handoffs),
                "immediate_previous_step_id": (
                    context_packet["upstream"]["immediate_previous_step"]["source"]["step_id"]
                    if context_packet["upstream"]["immediate_previous_step"]
                    else None
                ),
            },
            role=runtime_role,
        )
        prompt_text = render_step_prompt(
            role=role,
            prompt_label=str(prompt_metadata.get("label", role["name"])),
            prompt_body=prompt_body,
            packet=context_packet,
            compiled_spec=compiled_spec,
        )
        resume_session_ref = previous_session_refs_by_step.get(step["id"]) if execution_settings["inherit_session"] else None
        request = RoleRequest(
            run_id=run["id"],
            role=runtime_role,
            role_archetype=role["archetype"],
            role_name=role["name"],
            step_id=step["id"],
            prompt=prompt_text,
            workdir=Path(run["workdir"]),
            executor_kind=execution_settings["executor_kind"],
            executor_mode=execution_settings["executor_mode"],
            command_cli=execution_settings["command_cli"],
            command_args_text=execution_settings["command_args_text"],
            inherit_session=bool(execution_settings["inherit_session"]),
            resume_session_id=str((resume_session_ref or {}).get("session_id", "")),
            extra_cli_args_text=str(execution_settings["extra_cli_args_text"]),
            model=execution_settings["model"],
            reasoning_effort=execution_settings["reasoning_effort"],
            output_schema=self._output_schema_for_archetype(role["archetype"]),
            output_path=output_path,
            run_dir=layout.run_dir,
            sandbox=self._sandbox_for_archetype(role["archetype"]),
            idle_timeout_seconds=self.settings.role_idle_timeout_seconds,
            extra_context={
                "iter_id": iter_id,
                "compiled_spec": compiled_spec,
                "archetype": role["archetype"],
                "step_id": step["id"],
                "role_name": role["name"],
                "step_model": execution_settings["step_model"],
                "inherit_session": bool(execution_settings["inherit_session"]),
                "extra_cli_args_text": str(execution_settings["extra_cli_args_text"]),
                "resume_session_id": str((resume_session_ref or {}).get("session_id", "")),
                "executor_kind": execution_settings["executor_kind"],
                "executor_mode": execution_settings["executor_mode"],
                "legacy_role": runtime_role,
                "context_packet": context_packet,
                "immediate_previous_step": context_packet["upstream"]["immediate_previous_step"],
                "previous_iteration_summary": previous_iteration_summary,
                "current_outputs_by_step": current_outputs_by_step,
                "current_outputs_by_role": current_outputs_by_role,
                "current_outputs_by_archetype": current_outputs_by_archetype,
                "previous_outputs_by_step": previous_outputs_by_step,
                "previous_outputs_by_role": previous_outputs_by_role,
                "previous_outputs_by_archetype": previous_outputs_by_archetype,
                "inspector_output": current_outputs_by_archetype.get("inspector"),
                "tester_output": current_outputs_by_archetype.get("inspector"),
                "previous_builder_result": previous_outputs_by_archetype.get("builder"),
                "previous_generator_result": previous_outputs_by_archetype.get("builder"),
                "previous_inspector_result": previous_outputs_by_archetype.get("inspector"),
                "previous_tester_result": previous_outputs_by_archetype.get("inspector"),
                "previous_gatekeeper_result": previous_outputs_by_archetype.get("gatekeeper"),
                "previous_verifier_result": previous_outputs_by_archetype.get("gatekeeper"),
                "previous_guide_result": previous_outputs_by_archetype.get("guide"),
                "previous_challenger_result": previous_outputs_by_archetype.get("guide"),
                "stagnation_mode": stagnation_mode,
            },
        )
        self._record_role_request(run["id"], request)

        def execute_request() -> dict:
            return executor.execute(
                request,
                lambda event_type, payload: self.repository.append_event(
                    run["id"],
                    event_type,
                    {
                        **payload,
                        "step_id": step["id"],
                        "step_order": step_order,
                        "role_name": role["name"],
                        "archetype": role["archetype"],
                    },
                    role=runtime_role,
                ),
                lambda: self.repository.should_stop(run["id"]),
                lambda pid: self.repository.update_run(run["id"], child_pid=pid)
                if pid is not None
                else self.repository.update_run(run["id"], clear_child_pid=True),
            )

        output = self._execute_role(
            run["id"],
            iter_id,
            runtime_role,
            execute_request,
            retry_config,
            event_context={
                "step_id": step["id"],
                "step_order": step_order,
                "role_name": role["name"],
                "archetype": role["archetype"],
            },
        )
        session_ref = request.extra_context.get("session_ref")
        if not isinstance(session_ref, dict):
            session_ref = {}
        elif not session_ref.get("session_id") and request.resume_session_id.strip():
            session_ref = {
                **session_ref,
                "session_id": request.resume_session_id.strip(),
            }
        return output, context_packet, session_ref

    def _resolve_role_execution_settings(self, run: dict, step: dict, role: dict) -> dict[str, object]:
        step_model = str(step.get("model") or "").strip()
        step_inherit_session = bool(step.get("inherit_session"))
        step_extra_cli_args = str(step.get("extra_cli_args") or "").strip()
        role_model = str(role.get("model") or "").strip()

        if role_uses_execution_snapshot(role):
            executor_kind = normalize_executor_kind(role.get("executor_kind", "codex"))
            executor_mode = normalize_executor_mode(role.get("executor_mode", "preset"))
            profile = executor_profile(executor_kind)
            reasoning_effort = str(role.get("reasoning_effort") or "").strip()
            if profile.command_only and executor_mode != "command":
                raise LooporaError(f"{profile.label} only supports command mode")
            if executor_mode == "preset":
                return {
                    "executor_kind": executor_kind,
                    "executor_mode": executor_mode,
                    "command_cli": "",
                    "command_args_text": "",
                    "model": step_model or role_model or profile.default_model,
                    "reasoning_effort": normalize_reasoning_effort(reasoning_effort, executor_kind),
                    "step_model": step_model,
                    "inherit_session": step_inherit_session,
                    "extra_cli_args_text": step_extra_cli_args,
                }
            command_args_text = str(role.get("command_args_text") or "")
            validate_command_args_text(command_args_text, executor_kind=executor_kind)
            return {
                "executor_kind": executor_kind,
                "executor_mode": executor_mode,
                "command_cli": str(role.get("command_cli") or "").strip() or profile.cli_name,
                "command_args_text": command_args_text,
                "model": step_model or role_model,
                "reasoning_effort": reasoning_effort,
                "step_model": step_model,
                "inherit_session": step_inherit_session,
                "extra_cli_args_text": step_extra_cli_args,
            }

        executor_kind = normalize_executor_kind(run.get("executor_kind", "codex"))
        executor_mode = normalize_executor_mode(run.get("executor_mode", "preset"))
        profile = executor_profile(executor_kind)
        if profile.command_only and executor_mode != "command":
            raise LooporaError(f"{profile.label} only supports command mode")
        if executor_mode == "preset":
            return {
                "executor_kind": executor_kind,
                "executor_mode": executor_mode,
                "command_cli": "",
                "command_args_text": "",
                "model": step_model or role_model or str(run.get("model") or "") or profile.default_model,
                "reasoning_effort": coerce_reasoning_effort(run.get("reasoning_effort", ""), executor_kind),
                "step_model": step_model,
                "inherit_session": step_inherit_session,
                "extra_cli_args_text": step_extra_cli_args,
            }

        command_args_text = str(run.get("command_args_text") or "")
        validate_command_args_text(command_args_text, executor_kind=executor_kind)
        return {
            "executor_kind": executor_kind,
            "executor_mode": executor_mode,
            "command_cli": str(run.get("command_cli") or "").strip() or profile.cli_name,
            "command_args_text": command_args_text,
            "model": step_model or role_model or str(run.get("model") or ""),
            "reasoning_effort": str(run.get("reasoning_effort") or "").strip(),
            "step_model": step_model,
            "inherit_session": step_inherit_session,
            "extra_cli_args_text": step_extra_cli_args,
        }

    def _build_step_prompt(
        self,
        role: dict,
        compiled_spec: dict,
        prompt_markdown: str,
        iter_id: int,
        *,
        current_outputs_by_role: dict[str, dict],
        current_outputs_by_archetype: dict[str, dict],
        previous_outputs_by_archetype: dict[str, dict],
    ) -> str:
        prompt_metadata, prompt_body = self._parse_runtime_prompt(prompt_markdown, expected_archetype=role["archetype"])
        return render_step_prompt(
            role=role,
            prompt_label=str(prompt_metadata.get("label", role["name"])),
            prompt_body=prompt_body,
            packet={
                "contract": {
                    "path": "contract/run_contract.json",
                    "goal": str(compiled_spec.get("goal") or "").strip(),
                    "constraints": str(compiled_spec.get("constraints") or "No explicit constraints were provided.").strip(),
                    "check_mode": str(compiled_spec.get("check_mode") or "specified"),
                    "check_count": len(compiled_spec.get("checks") or []),
                    "completion_mode": "gatekeeper",
                    "workflow_preset": "custom",
                },
                "iteration": {
                    "iter_index": iter_id,
                    "is_first_iteration": iter_id == 0,
                    "previous_iteration_exists": bool(previous_outputs_by_archetype),
                    "previous_composite": None,
                    "stagnation_mode": "none",
                },
                "current_step": {
                    "step_id": role.get("id") or role["name"],
                    "step_order": 0,
                    "role_id": role.get("id") or role["name"],
                    "role_name": role["name"],
                    "archetype": role["archetype"],
                    "model": "",
                    "executor_kind": "",
                    "executor_mode": "",
                },
                "upstream": {
                    "immediate_previous_step": None,
                    "completed_steps_this_iteration": [],
                    "previous_iteration_same_step": None,
                    "previous_iteration_same_role": None,
                    "previous_iteration_summary": None,
                },
                "artifacts": [],
            },
            compiled_spec=compiled_spec,
        )

    def _system_prompt_prefix(self, archetype: str) -> str:
        return system_prompt_prefix(archetype)

    def _output_contract_prompt(self, archetype: str) -> str:
        return output_contract_prompt(archetype)

    def _parse_runtime_prompt(self, prompt_markdown: str, *, expected_archetype: str) -> tuple[dict, str]:
        try:
            from loopora.workflows import validate_prompt_markdown

            return validate_prompt_markdown(prompt_markdown, expected_archetype=expected_archetype)
        except WorkflowError as exc:
            raise LooporaError(str(exc)) from exc

    def _sandbox_for_archetype(self, archetype: str) -> str:
        if archetype == "builder":
            return "workspace-write"
        if archetype == "inspector":
            return "workspace-write"
        return "read-only"
