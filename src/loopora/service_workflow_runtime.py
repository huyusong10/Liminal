from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from loopora.context_flow import (
    StepContextPacketRequest,
    build_step_context_packet,
    normalize_manifest_claim_coverage_targets,
    render_step_prompt,
)
from loopora.evidence_coverage import load_or_build_evidence_coverage_projection, summarize_evidence_coverage_projection
from loopora.executor import CodexExecutor, RoleRequest, coerce_reasoning_effort, normalize_reasoning_effort, validate_command_args_text
from loopora.providers import executor_profile, normalize_executor_kind, normalize_executor_mode
from loopora.recovery import RetryConfig
from loopora.run_artifacts import RunArtifactLayout, read_jsonl
from loopora.service_role_execution import RoleExecutionRequest
from loopora.service_types import LooporaError
from loopora.structured_booleans import structured_bool_is_true
from loopora.structured_numbers import structured_non_negative_int
from loopora.utils import read_json, write_json
from loopora.workflows import (
    WorkflowError,
    normalize_step_evidence_limit,
    role_uses_execution_snapshot,
)


@dataclass(frozen=True)
class WorkflowStepRuntimeRequest:
    executor: CodexExecutor
    run: dict
    compiled_spec: dict
    layout: RunArtifactLayout
    iter_id: int
    step: dict
    step_order: int
    role: dict
    prompt_files: dict[str, str]
    execution_settings: dict[str, object]
    run_contract: dict
    current_outputs_by_step: dict[str, dict]
    current_outputs_by_role: dict[str, dict]
    current_outputs_by_archetype: dict[str, dict]
    current_handoffs: list[dict]
    previous_outputs_by_step: dict[str, dict]
    previous_outputs_by_role: dict[str, dict]
    previous_outputs_by_archetype: dict[str, dict]
    previous_handoffs_by_step: dict[str, dict]
    previous_handoffs_by_role: dict[str, dict]
    previous_iteration_summary: dict | None
    previous_session_refs_by_step: dict[str, dict]
    previous_composite: float | None
    stagnation_mode: str
    evidence_progress_mode: str
    covered_check_count: int
    missing_check_count: int
    consecutive_no_required_coverage_delta: int
    retry_config: RetryConfig
    evidence_items_snapshot: list[dict] | None = None


def _manifest_prompt_context(layout: RunArtifactLayout, known_ids: list[str]) -> tuple[dict, list[dict]]:
    summary = _empty_manifest_prompt_summary()
    try:
        manifest = read_json(layout.evidence_manifest_path)
    except (OSError, UnicodeError, ValueError):
        return summary, []
    if not isinstance(manifest, dict):
        return summary, []
    allowed_ids = {str(item).strip() for item in known_ids if str(item).strip()}
    problem_codes_by_claim: dict[str, list[str]] = {}
    for problem in list(manifest.get("problems") or []):
        if not isinstance(problem, dict):
            continue
        claim_id = str(problem.get("claim_id") or "").strip()
        code = str(problem.get("code") or "").strip()
        if claim_id and code:
            problem_codes_by_claim.setdefault(claim_id, []).append(code)
    claims = []
    for claim in list(manifest.get("claims") or []):
        if not isinstance(claim, dict):
            continue
        claim_id = str(claim.get("id") or "").strip()
        if not claim_id or claim_id not in allowed_ids:
            continue
        claims.append(
            {
                "id": claim_id,
                "verification_status": str(claim.get("verification_status") or "ledger_only").strip(),
                "measured_evidence": structured_bool_is_true(claim.get("measured_evidence")),
                "concrete_evidence_claim_count": _safe_int(claim.get("concrete_evidence_claim_count")),
                "artifact_count": _safe_int(claim.get("artifact_count")),
                "artifact_backed": structured_bool_is_true(claim.get("artifact_backed")),
                "workspace_backed": structured_bool_is_true(claim.get("workspace_backed")),
                "reproducible": structured_bool_is_true(claim.get("reproducible")),
                "coverage_targets": normalize_manifest_claim_coverage_targets(claim.get("coverage_targets")),
                "problem_codes": problem_codes_by_claim.get(claim_id, [])[:8],
            }
        )
    summary = {
        "claim_count": len(claims),
        "direct_proof_claim_count": sum(1 for claim in claims if claim["verification_status"] == "direct_proof"),
        "workspace_artifact_claim_count": sum(1 for claim in claims if claim["verification_status"] == "workspace_artifact"),
        "run_artifact_claim_count": sum(1 for claim in claims if claim["verification_status"] == "run_artifact"),
        "ledger_only_claim_count": sum(1 for claim in claims if claim["verification_status"] == "ledger_only"),
        "unverified_claim_count": sum(1 for claim in claims if claim["verification_status"] == "unverified"),
        "problem_count": sum(len(claim["problem_codes"]) for claim in claims),
    }
    return summary, claims[-40:]


def _empty_manifest_prompt_summary() -> dict:
    return {
        "claim_count": 0,
        "direct_proof_claim_count": 0,
        "workspace_artifact_claim_count": 0,
        "run_artifact_claim_count": 0,
        "ledger_only_claim_count": 0,
        "unverified_claim_count": 0,
        "problem_count": 0,
    }


def _safe_int(value: object) -> int:
    return structured_non_negative_int(value)


class ServiceWorkflowRuntimeMixin:
    def _step_inputs(self, step: dict) -> dict:
        inputs = step.get("inputs")
        return dict(inputs) if isinstance(inputs, dict) else {}

    def _matches_handoff_selector(self, handoff: dict, selector: str) -> bool:
        source = handoff.get("source") if isinstance(handoff, dict) else {}
        if not isinstance(source, dict):
            return False
        normalized = str(selector or "").strip()
        return normalized in {
            str(source.get("step_id") or "").strip(),
            str(source.get("role_id") or "").strip(),
            str(source.get("runtime_role") or "").strip(),
            str(source.get("archetype") or "").strip(),
            str(source.get("role_name") or "").strip(),
        }

    def _filter_handoffs_for_step(self, step: dict, handoffs: list[dict]) -> list[dict]:
        inputs = self._step_inputs(step)
        selectors = [str(item).strip() for item in list(inputs.get("handoffs_from") or []) if str(item).strip()]
        if not selectors:
            return list(handoffs)
        return [handoff for handoff in handoffs if any(self._matches_handoff_selector(handoff, selector) for selector in selectors)]

    def _iteration_memory_for_step(
        self,
        step: dict,
        *,
        previous_iteration_same_step: dict | None,
        previous_iteration_same_role: dict | None,
        previous_iteration_summary: dict | None,
    ) -> tuple[dict | None, dict | None, dict | None]:
        policy = str(self._step_inputs(step).get("iteration_memory") or "default").strip().lower()
        if policy == "none":
            return None, None, None
        if policy == "same_step":
            return previous_iteration_same_step, None, None
        if policy == "same_role":
            return None, previous_iteration_same_role, None
        if policy == "summary_only":
            return None, None, previous_iteration_summary
        return previous_iteration_same_step, previous_iteration_same_role, previous_iteration_summary

    def _filter_evidence_for_step(self, step: dict, evidence_items: list[dict]) -> list[dict]:
        inputs = self._step_inputs(step)
        query = inputs.get("evidence_query") if isinstance(inputs.get("evidence_query"), dict) else {}
        archetypes = {str(item).strip() for item in list(query.get("archetypes") or []) if str(item).strip()}
        verifies = [str(item).strip().lower() for item in list(query.get("verifies") or []) if str(item).strip()]
        filtered: list[dict] = []
        for item in evidence_items:
            if not isinstance(item, dict):
                continue
            if archetypes and str(item.get("archetype") or "").strip() not in archetypes:
                continue
            if verifies:
                verify_text = " ".join(str(value) for value in list(item.get("verifies") or [])).lower()
                if not any(needle in verify_text for needle in verifies):
                    continue
            filtered.append(item)
        limit = normalize_step_evidence_limit(query.get("limit")) or 40
        return filtered[-limit:]

    def _step_declares_evidence_query(self, step: dict) -> bool:
        inputs = self._step_inputs(step)
        query = inputs.get("evidence_query")
        return isinstance(query, dict) and bool(query)

    @staticmethod
    def _evidence_known_ids(evidence_items: list[dict]) -> list[str]:
        return [str(item.get("id")) for item in evidence_items if isinstance(item, dict) and str(item.get("id") or "").strip()]

    def _prepare_workflow_step_request(
        self,
        request: WorkflowStepRuntimeRequest,
    ) -> dict[str, object]:
        runtime_request = request
        run = runtime_request.run
        layout = runtime_request.layout
        iter_id = runtime_request.iter_id
        step = runtime_request.step
        step_order = runtime_request.step_order
        role = runtime_request.role
        execution_settings = runtime_request.execution_settings
        step_dir = layout.step_dir(iter_id, step_order, step["id"])
        step_dir.mkdir(parents=True, exist_ok=True)
        output_path = layout.step_output_raw_path(iter_id, step_order, step["id"])
        prompt_metadata, prompt_body = self._parse_runtime_prompt(
            runtime_request.prompt_files[role["prompt_ref"]],
            expected_archetype=role["archetype"],
        )
        runtime_role = self._runtime_role_key(role)
        all_evidence_items = (
            list(runtime_request.evidence_items_snapshot)
            if runtime_request.evidence_items_snapshot is not None
            else read_jsonl(layout.evidence_ledger_path)
        )
        current_handoffs_for_step = self._filter_handoffs_for_step(step, runtime_request.current_handoffs)
        (
            previous_iteration_same_step_for_step,
            previous_iteration_same_role_for_step,
            previous_iteration_summary_for_step,
        ) = self._iteration_memory_for_step(
            step,
            previous_iteration_same_step=runtime_request.previous_handoffs_by_step.get(step["id"]),
            previous_iteration_same_role=runtime_request.previous_handoffs_by_role.get(role["id"]),
            previous_iteration_summary=runtime_request.previous_iteration_summary,
        )
        declares_evidence_query = self._step_declares_evidence_query(step)
        if declares_evidence_query:
            evidence_items = self._filter_evidence_for_step(step, all_evidence_items)
            evidence_known_ids = self._evidence_known_ids(evidence_items)
        else:
            evidence_items = all_evidence_items[-40:]
            evidence_known_ids = self._evidence_known_ids(all_evidence_items)
        evidence_manifest_summary, evidence_manifest_claims = _manifest_prompt_context(layout, evidence_known_ids)
        evidence_coverage_summary = summarize_evidence_coverage_projection(
            load_or_build_evidence_coverage_projection(layout),
            coverage_path_available=layout.evidence_coverage_path.exists(),
        )
        context_packet = build_step_context_packet(
            StepContextPacketRequest(
                run_contract=runtime_request.run_contract,
                layout=layout,
                iter_id=iter_id,
                step=step,
                step_order=step_order,
                role=role,
                execution_settings=execution_settings,
                immediate_previous_step=current_handoffs_for_step[-1] if current_handoffs_for_step else None,
                completed_steps_this_iteration=current_handoffs_for_step,
                previous_iteration_same_step=previous_iteration_same_step_for_step,
                previous_iteration_same_role=previous_iteration_same_role_for_step,
                previous_iteration_summary=previous_iteration_summary_for_step,
                previous_composite=runtime_request.previous_composite,
                stagnation_mode=runtime_request.stagnation_mode,
                evidence_progress_mode=runtime_request.evidence_progress_mode,
                covered_check_count=runtime_request.covered_check_count,
                missing_check_count=runtime_request.missing_check_count,
                consecutive_no_required_coverage_delta=runtime_request.consecutive_no_required_coverage_delta,
                evidence_coverage_summary=evidence_coverage_summary,
                evidence_items=evidence_items,
                evidence_known_ids=evidence_known_ids,
                evidence_manifest_summary=evidence_manifest_summary,
                evidence_manifest_claims=evidence_manifest_claims,
            )
        )
        context_path = layout.step_context_path(iter_id, step_order, step["id"])
        write_json(context_path, context_packet)
        self.append_run_event(
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
                "completed_steps_this_iteration": len(current_handoffs_for_step),
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
            compiled_spec=runtime_request.compiled_spec,
        )
        resume_session_ref = runtime_request.previous_session_refs_by_step.get(step["id"]) if execution_settings["inherit_session"] else None
        role_request = RoleRequest(
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
            sandbox=self._sandbox_for_action_policy(step.get("action_policy")),
            idle_timeout_seconds=self.settings.role_idle_timeout_seconds,
            extra_context={
                "iter_id": iter_id,
                "compiled_spec": runtime_request.compiled_spec,
                "archetype": role["archetype"],
                "step_id": step["id"],
                "role_name": role["name"],
                "action_policy": dict(step.get("action_policy") or {}),
                "step_model": execution_settings["step_model"],
                "inherit_session": bool(execution_settings["inherit_session"]),
                "extra_cli_args_text": str(execution_settings["extra_cli_args_text"]),
                "resume_session_id": str((resume_session_ref or {}).get("session_id", "")),
                "executor_kind": execution_settings["executor_kind"],
                "executor_mode": execution_settings["executor_mode"],
                "legacy_role": runtime_role,
                "context_packet": context_packet,
                "immediate_previous_step": context_packet["upstream"]["immediate_previous_step"],
                "previous_iteration_summary": previous_iteration_summary_for_step,
                "current_outputs_by_step": runtime_request.current_outputs_by_step,
                "current_outputs_by_role": runtime_request.current_outputs_by_role,
                "current_outputs_by_archetype": runtime_request.current_outputs_by_archetype,
                "previous_outputs_by_step": runtime_request.previous_outputs_by_step,
                "previous_outputs_by_role": runtime_request.previous_outputs_by_role,
                "previous_outputs_by_archetype": runtime_request.previous_outputs_by_archetype,
                "inspector_output": runtime_request.current_outputs_by_archetype.get("inspector"),
                "tester_output": runtime_request.current_outputs_by_archetype.get("inspector"),
                "previous_builder_result": runtime_request.previous_outputs_by_archetype.get("builder"),
                "previous_generator_result": runtime_request.previous_outputs_by_archetype.get("builder"),
                "previous_inspector_result": runtime_request.previous_outputs_by_archetype.get("inspector"),
                "previous_tester_result": runtime_request.previous_outputs_by_archetype.get("inspector"),
                "previous_gatekeeper_result": runtime_request.previous_outputs_by_archetype.get("gatekeeper"),
                "previous_verifier_result": runtime_request.previous_outputs_by_archetype.get("gatekeeper"),
                "previous_guide_result": runtime_request.previous_outputs_by_archetype.get("guide"),
                "previous_challenger_result": runtime_request.previous_outputs_by_archetype.get("guide"),
                "stagnation_mode": runtime_request.stagnation_mode,
                "evidence_progress_mode": runtime_request.evidence_progress_mode,
                "covered_check_count": runtime_request.covered_check_count,
                "missing_check_count": runtime_request.missing_check_count,
                "consecutive_no_required_coverage_delta": runtime_request.consecutive_no_required_coverage_delta,
            },
        )
        self._record_role_request(run["id"], role_request)
        return {
            "context_packet": context_packet,
            "role_request": role_request,
            "prompt": prompt_text,
            "output_path": output_path,
            "runtime_role": runtime_role,
        }

    def _run_workflow_step(
        self,
        request: WorkflowStepRuntimeRequest,
    ) -> tuple[dict, dict, dict]:
        runtime_request = request
        run = runtime_request.run
        iter_id = runtime_request.iter_id
        step = runtime_request.step
        step_order = runtime_request.step_order
        role = runtime_request.role
        prepared = self._prepare_workflow_step_request(request)
        context_packet = prepared["context_packet"]
        role_request = prepared["role_request"]
        runtime_role = str(prepared["runtime_role"])

        def execute_request() -> dict:
            return runtime_request.executor.execute(
                role_request,
                lambda event_type, payload: self.append_run_event(
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
                lambda pid: (
                    self.repository.update_run(run["id"], child_pid=pid) if pid is not None else self.repository.update_run(run["id"], clear_child_pid=True)
                ),
            )

        output = self._execute_role(
            RoleExecutionRequest(
                run_id=run["id"],
                iter_id=iter_id,
                role=runtime_role,
                fn=execute_request,
                retry_config=runtime_request.retry_config,
                event_context={
                    "step_id": step["id"],
                    "step_order": step_order,
                    "role_name": role["name"],
                    "archetype": role["archetype"],
                },
            )
        )
        session_ref = role_request.extra_context.get("session_ref")
        if not isinstance(session_ref, dict):
            session_ref = {}
        elif not session_ref.get("session_id") and role_request.resume_session_id.strip():
            session_ref = {
                **session_ref,
                "session_id": role_request.resume_session_id.strip(),
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

    def _parse_runtime_prompt(self, prompt_markdown: str, *, expected_archetype: str) -> tuple[dict, str]:
        try:
            from loopora.workflows import validate_prompt_markdown

            return validate_prompt_markdown(prompt_markdown, expected_archetype=expected_archetype)
        except WorkflowError as exc:
            raise LooporaError(str(exc)) from exc

    def _sandbox_for_action_policy(self, action_policy: dict | None) -> str:
        policy = action_policy if isinstance(action_policy, dict) else {}
        if str(policy.get("workspace") or "").strip() == "workspace_write":
            return "workspace-write"
        return "read-only"
