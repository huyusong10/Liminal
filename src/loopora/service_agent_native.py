from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loopora.agent_adapters import normalize_agent_adapter_kind, read_agent_binding
from loopora.context_flow import evidence_entry_id
from loopora.recovery import RetryConfig
from loopora.run_artifacts import INITIAL_STAGNATION_STATE, read_jsonl
from loopora.service_types import ACTIVE_RUN_STATUSES, LooporaConflictError, LooporaError, LooporaNotFoundError, TERMINAL_RUN_STATUSES, normalize_completion_mode
from loopora.service_workflow_execution import (
    _WorkflowIterationState,
    _WorkflowRunContext,
    _evidence_context_with_canonical_items,
)
from loopora.service_workflow_failure_handling import WorkflowExhaustionRequest
from loopora.service_workflow_iteration_state import WorkflowIterationCheckpointRequest
from loopora.service_workflow_runtime import WorkflowStepRuntimeRequest
from loopora.service_workflow_support import StepOutputNormalizationRequest, WorkflowSummaryRequest
from loopora.utils import read_json, utc_now, write_json
from loopora.workflows import normalize_workflow_controls


@dataclass(frozen=True)
class AgentNativeStepClaimRequest:
    adapter: str
    workdir: Path | str | None = None
    context_id: str = ""
    run_id: str = ""
    entry_source: str = ""


@dataclass(frozen=True)
class AgentNativeStepSubmitRequest:
    adapter: str
    output: dict[str, Any]
    host_dispatch: dict[str, Any] | None = None
    workdir: Path | str | None = None
    context_id: str = ""
    run_id: str = ""
    step_id: str = ""
    session_ref: dict[str, Any] | None = None
    entry_source: str = ""


class ServiceAgentNativeMixin:
    def prepare_agent_native_run(
        self,
        adapter: str,
        run_id: str,
        *,
        entry_source: str = "",
    ) -> dict[str, Any]:
        kind = normalize_agent_adapter_kind(adapter)
        run = self.get_run(run_id)
        if run["status"] in TERMINAL_RUN_STATUSES:
            return {"run": run, "next_step": None, "complete": True}
        if run["status"] not in ACTIVE_RUN_STATUSES:
            raise LooporaConflictError(f"cannot prepare agent-native run in status {run['status']}")

        layout = self._run_artifact_layout(Path(run["runs_dir"]))
        state = self._agent_native_state(layout, adapter=kind, run=run)
        summary = "# Loopora Run Summary\n\nAwaiting host Agent step execution.\n"
        update: dict[str, Any] = {
            "status": "awaiting_agent",
            "summary_md": summary,
        }
        if not run.get("started_at"):
            update["started_at"] = utc_now()
        run = self.repository.update_run(run_id, **update)
        self._persist_summary_file(Path(run["runs_dir"]), summary)
        self.append_run_event(
            run_id,
            "agent_native_run_prepared",
            {
                "adapter": kind,
                "execution_plane": "agent_native",
                "entry_source": str(entry_source or "").strip(),
            },
        )
        self._write_agent_native_state(layout, state)
        next_result = self.claim_agent_native_step(
            AgentNativeStepClaimRequest(
                adapter=kind,
                run_id=run_id,
                entry_source=entry_source,
            )
        )
        return {
            "run": next_result["run"],
            "next_step": next_result.get("next_step"),
            "complete": bool(next_result.get("complete")),
        }

    def claim_agent_native_step(self, request: AgentNativeStepClaimRequest) -> dict[str, Any]:
        kind = normalize_agent_adapter_kind(request.adapter)
        run = self._agent_native_resolve_run(kind, workdir=request.workdir, context_id=request.context_id, run_id=request.run_id)
        if run["status"] in TERMINAL_RUN_STATUSES:
            return {
                "adapter": kind,
                "run": run,
                "run_path": f"/runs/{run['id']}",
                "next_step": None,
                "complete": True,
            }
        if run["status"] not in ACTIVE_RUN_STATUSES:
            raise LooporaConflictError(f"cannot claim agent-native step in status {run['status']}")

        layout = self._run_artifact_layout(Path(run["runs_dir"]))
        state = self._agent_native_state(layout, adapter=kind, run=run)
        active = state.get("active_step") if isinstance(state.get("active_step"), dict) else {}
        if active and active.get("capsule"):
            return {
                "adapter": kind,
                "run": run,
                "run_path": f"/runs/{run['id']}",
                "next_step": active["capsule"],
                "complete": False,
            }

        context = self._agent_native_run_context(run, state)
        step_index = int(state.get("step_index") or 0)
        if step_index >= len(context.workflow_steps):
            return self._agent_native_finish_iteration_or_advance(kind, run, state, context)

        step = context.workflow_steps[step_index]
        role = context.role_by_id[step["role_id"]]
        iteration = self._agent_native_iteration_state(state)
        execution_settings = self._resolve_role_execution_settings(run, step, role)
        prepared = self._prepare_workflow_step_request(
            WorkflowStepRuntimeRequest(
                executor=context.executor,
                run=run,
                compiled_spec=context.compiled_spec,
                layout=context.layout,
                iter_id=iteration.iter_id,
                step=step,
                step_order=step_index,
                role=role,
                prompt_files=context.prompt_files,
                execution_settings=execution_settings,
                run_contract=context.run_contract,
                current_outputs_by_step=iteration.current_outputs_by_step,
                current_outputs_by_role=iteration.current_outputs_by_role,
                current_outputs_by_archetype=iteration.current_outputs_by_archetype,
                current_handoffs=iteration.current_handoffs,
                previous_outputs_by_step=iteration.previous_outputs_by_step,
                previous_outputs_by_role=iteration.previous_outputs_by_role,
                previous_outputs_by_archetype=iteration.previous_outputs_by_archetype,
                previous_handoffs_by_step=iteration.previous_handoffs_by_step,
                previous_handoffs_by_role=iteration.previous_handoffs_by_role,
                previous_iteration_summary=iteration.previous_iteration_summary,
                previous_session_refs_by_step=iteration.previous_session_refs_by_step,
                previous_composite=iteration.previous_composite,
                stagnation_mode=iteration.stagnation.get("stagnation_mode", "none"),
                evidence_progress_mode=iteration.stagnation.get("evidence_progress_mode", "none"),
                covered_check_count=int(iteration.stagnation.get("latest_covered_check_count") or 0),
                missing_check_count=int(iteration.stagnation.get("latest_missing_check_count") or 0),
                consecutive_no_required_coverage_delta=int(iteration.stagnation.get("consecutive_no_required_coverage_delta") or 0),
                retry_config=context.retry_config,
            )
        )
        runtime_role = str(prepared["runtime_role"])
        role_request = prepared["role_request"]
        capsule = self._agent_native_capsule(
            kind,
            run=run,
            layout=layout,
            iter_id=iteration.iter_id,
            step=step,
            step_order=step_index,
            role=role,
            runtime_role=runtime_role,
            prompt=str(prepared["prompt"]),
            output_schema=role_request.output_schema,
        )
        state["active_step"] = {
            "claimed_at": utc_now(),
            "capsule": capsule,
            "context_packet": prepared["context_packet"],
            "execution_settings": execution_settings,
            "role": role,
            "runtime_role": runtime_role,
            "step": step,
            "step_order": step_index,
            "iter_id": iteration.iter_id,
        }
        self._write_agent_native_state(layout, state)
        run = self.repository.update_run(run["id"], status="awaiting_agent", current_iter=iteration.iter_id, active_role=runtime_role)
        self.append_run_event(
            run["id"],
            "agent_native_step_claimed",
            {
                "adapter": kind,
                "iter": iteration.iter_id,
                "step_id": step["id"],
                "step_order": step_index,
                "role_name": role["name"],
                "archetype": role["archetype"],
                "runtime_role": runtime_role,
                "parallel_group": str(step.get("parallel_group") or ""),
            },
            role=runtime_role,
        )
        return {
            "adapter": kind,
            "run": self._hydrate_run_files(run),
            "run_path": f"/runs/{run['id']}",
            "next_step": capsule,
            "complete": False,
        }

    def submit_agent_native_step(self, request: AgentNativeStepSubmitRequest) -> dict[str, Any]:
        kind = normalize_agent_adapter_kind(request.adapter)
        run = self._agent_native_resolve_run(kind, workdir=request.workdir, context_id=request.context_id, run_id=request.run_id)
        if run["status"] in TERMINAL_RUN_STATUSES:
            raise LooporaConflictError(f"cannot submit agent-native step for terminal run {run['id']}")
        if run["status"] not in ACTIVE_RUN_STATUSES:
            raise LooporaConflictError(f"cannot submit agent-native step in status {run['status']}")
        output = request.output if isinstance(request.output, dict) else {}
        if not output:
            raise LooporaError("agent-native step result must be a JSON object")

        layout = self._run_artifact_layout(Path(run["runs_dir"]))
        state = self._agent_native_state(layout, adapter=kind, run=run)
        active = state.get("active_step") if isinstance(state.get("active_step"), dict) else {}
        if not active:
            raise LooporaConflictError("no agent-native step is currently claimed; run next first")
        step = active.get("step") if isinstance(active.get("step"), dict) else {}
        step_id = str(request.step_id or step.get("id") or "").strip()
        if not step_id or step_id != str(step.get("id") or "").strip():
            raise LooporaConflictError("submitted step_id does not match the claimed agent-native step")

        iter_id = int(active.get("iter_id") or state.get("iter_id") or 0)
        step_order = int(active.get("step_order") or state.get("step_index") or 0)
        write_json(layout.step_output_raw_path(iter_id, step_order, step_id), output)

        context = self._agent_native_run_context(run, state)
        iteration = self._agent_native_iteration_state(state)
        role = active.get("role") if isinstance(active.get("role"), dict) else context.role_by_id[step["role_id"]]
        runtime_role = str(active.get("runtime_role") or self._runtime_role_key(role))
        context_packet = active.get("context_packet") if isinstance(active.get("context_packet"), dict) else {}
        host_dispatch = self._validate_agent_native_host_dispatch(
            {
                "adapter": kind,
                "run": run,
                "step_id": step_id,
                "role": role,
                "active": active,
            },
            request.host_dispatch,
        )
        normalized_output = self._normalize_step_output(
            StepOutputNormalizationRequest(
                archetype=role["archetype"],
                output=output,
                compiled_spec=context.compiled_spec,
                inspector_output=dict(iteration.current_outputs_by_archetype).get("inspector"),
                evidence_context=_evidence_context_with_canonical_items(context_packet, context.layout),
                current_evidence_id=evidence_entry_id(iter_id, step_order, step_id),
            )
        )
        submitted_session_ref = request.session_ref if isinstance(request.session_ref, dict) else {}
        if not submitted_session_ref and isinstance(output.get("session_ref"), dict):
            submitted_session_ref = output["session_ref"]
        result = {
            "skipped": False,
            "step_order": step_order,
            "step": step,
            "role": role,
            "runtime_role": runtime_role,
            "execution_settings": active.get("execution_settings") if isinstance(active.get("execution_settings"), dict) else {},
            "normalized_output": normalized_output,
            "context_packet": context_packet,
            "session_ref": submitted_session_ref,
            "duration_ms": 0,
        }
        finish_result = self._commit_workflow_step_result(context, iteration, result)
        self.append_run_event(
            run["id"],
            "agent_native_step_submitted",
            {
                "adapter": kind,
                "iter": iter_id,
                "step_id": step_id,
                "step_order": step_order,
                "role_name": role["name"],
                "archetype": role["archetype"],
                "entry_source": str(request.entry_source or "").strip(),
                "host_dispatch": host_dispatch,
            },
            role=runtime_role,
        )

        state.update(self._state_from_iteration(iteration))
        host_dispatches = list(state.get("host_dispatches") or [])
        host_dispatches.append(host_dispatch)
        state["host_dispatches"] = host_dispatches
        state["active_step"] = {}
        state["step_index"] = step_order + 1
        self._write_agent_native_state(layout, state)
        if finish_result is not None:
            state["status"] = "complete"
            self._write_agent_native_state(layout, state)
            self.repository.release_run_slot(run["id"])
            return {
                "adapter": kind,
                "run": finish_result,
                "run_path": f"/runs/{run['id']}",
                "next_step": None,
                "complete": True,
            }
        return self.claim_agent_native_step(
            AgentNativeStepClaimRequest(
                adapter=kind,
                run_id=run["id"],
                entry_source=request.entry_source,
            )
        )

    def _agent_native_finish_iteration_or_advance(
        self,
        adapter: str,
        run: dict,
        state: dict[str, Any],
        context: _WorkflowRunContext,
    ) -> dict[str, Any]:
        layout = context.layout
        iteration = self._agent_native_iteration_state(state)
        if context.workflow_controls:
            self.append_run_event(
                run["id"],
                "agent_native_controls_deferred",
                {
                    "iter": iteration.iter_id,
                    "control_count": len(context.workflow_controls),
                    "reason": "agent_native_controls_not_implemented",
                },
            )
        checkpoint = self._checkpoint_workflow_iteration_state(
            WorkflowIterationCheckpointRequest(
                layout=layout,
                iter_id=iteration.iter_id,
                step_results=iteration.step_results,
                current_outputs_by_step=iteration.current_outputs_by_step,
                current_outputs_by_role=iteration.current_outputs_by_role,
                current_outputs_by_archetype=iteration.current_outputs_by_archetype,
                current_session_refs_by_step=iteration.current_session_refs_by_step,
                stagnation=iteration.stagnation,
                previous_composite=iteration.previous_composite,
                run_id=run["id"],
            )
        )
        (
            previous_outputs_by_step,
            previous_outputs_by_role,
            previous_outputs_by_archetype,
            previous_handoffs_by_step,
            previous_handoffs_by_role,
            _previous_handoffs_by_archetype,
            previous_iteration_summary,
        ) = checkpoint
        summary = self._build_workflow_summary(
            WorkflowSummaryRequest(
                run=run,
                workflow=context.workflow,
                compiled_spec=context.compiled_spec,
                iter_id=iteration.iter_id,
                step_results=iteration.step_results,
                stagnation=iteration.stagnation,
                exhausted=False,
                previous_composite=iteration.previous_composite,
            )
        )
        self._write_summary(run["id"], "awaiting_agent", summary)
        max_iters = int(run.get("max_iters") or 0)
        next_iter = iteration.iter_id + 1
        if max_iters > 0 and next_iter >= max_iters:
            exhausted_summary = self._build_workflow_summary(
                WorkflowSummaryRequest(
                    run=run,
                    workflow=context.workflow,
                    compiled_spec=context.compiled_spec,
                    iter_id=iteration.iter_id,
                    step_results=iteration.step_results,
                    stagnation=iteration.stagnation,
                    exhausted=True,
                    previous_composite=iteration.previous_composite,
                )
            )
            finished = self._handle_workflow_exhaustion(
                WorkflowExhaustionRequest(
                    run_id=run["id"],
                    run=run,
                    run_dir=Path(run["runs_dir"]),
                    completion_mode=normalize_completion_mode(run.get("completion_mode", "gatekeeper")),
                    last_iter_id=iteration.iter_id,
                    summary=exhausted_summary,
                )
            )
            self.repository.release_run_slot(run["id"])
            state["status"] = "complete"
            self._write_agent_native_state(layout, state)
            return {
                "adapter": adapter,
                "run": finished,
                "run_path": f"/runs/{run['id']}",
                "next_step": None,
                "complete": True,
            }

        state.update(
            {
                "iter_id": next_iter,
                "step_index": 0,
                "previous_composite": (
                    iteration.current_gatekeeper_result.get("composite_score")
                    if isinstance(iteration.current_gatekeeper_result, dict)
                    else iteration.previous_composite
                ),
                "previous_outputs_by_step": previous_outputs_by_step,
                "previous_outputs_by_role": previous_outputs_by_role,
                "previous_outputs_by_archetype": previous_outputs_by_archetype,
                "previous_handoffs_by_step": previous_handoffs_by_step,
                "previous_handoffs_by_role": previous_handoffs_by_role,
                "previous_iteration_summary": previous_iteration_summary,
                "previous_session_refs_by_step": dict(iteration.current_session_refs_by_step),
                "current_outputs_by_step": {},
                "current_outputs_by_role": {},
                "current_outputs_by_archetype": {},
                "current_handoffs": [],
                "current_session_refs_by_step": {},
                "current_gatekeeper_result": None,
                "current_guide_result": None,
                "step_results": [],
                "active_step": {},
                "stagnation": iteration.stagnation,
            }
        )
        self._write_agent_native_state(layout, state)
        return self.claim_agent_native_step(AgentNativeStepClaimRequest(adapter=adapter, run_id=run["id"]))

    def _agent_native_resolve_run(
        self,
        adapter: str,
        *,
        workdir: Path | str | None,
        context_id: str,
        run_id: str,
    ) -> dict:
        resolved_run_id = str(run_id or "").strip()
        if not resolved_run_id:
            if workdir is None:
                raise LooporaError("agent-native run lookup requires --run-id or --workdir")
            binding = read_agent_binding(adapter, workdir, context_id=context_id)
            resolved_run_id = str(binding.get("linked_run_id") or "").strip()
        if not resolved_run_id:
            raise LooporaConflictError("no Loopora run is associated with this agent session/workdir; run /loopora-loop first")
        try:
            return self.get_run(resolved_run_id)
        except LooporaNotFoundError:
            raise

    def _agent_native_run_context(self, run: dict, state: dict[str, Any]) -> _WorkflowRunContext:
        layout = self._run_artifact_layout(Path(run["runs_dir"]))
        workflow = run.get("workflow_json") or read_json(layout.contract_workflow_path)
        role_by_id = {role["id"]: role for role in workflow.get("roles", [])}
        return _WorkflowRunContext(
            run_id=run["id"],
            run=run,
            run_dir=Path(run["runs_dir"]),
            workflow=workflow,
            executor=self.executor_factory(),
            compiled_spec=run["compiled_spec_json"],
            retry_config=RetryConfig(max_retries=run["max_role_retries"]),
            prompt_files=self._read_prompt_files_for_run(run),
            layout=layout,
            run_contract=read_json(layout.run_contract_path),
            workflow_steps=list(workflow.get("steps", [])),
            workflow_controls=normalize_workflow_controls(workflow.get("controls"), role_by_id=role_by_id),
            control_fire_counts=dict(state.get("control_fire_counts") or {}),
            workflow_started_at=0.0,
            role_by_id=role_by_id,
            completion_mode=normalize_completion_mode(run.get("completion_mode", "gatekeeper")),
            last_gatekeeper_result=state.get("current_gatekeeper_result") if isinstance(state.get("current_gatekeeper_result"), dict) else None,
        )

    def _agent_native_iteration_state(self, state: dict[str, Any]) -> _WorkflowIterationState:
        return _WorkflowIterationState(
            iter_id=int(state.get("iter_id") or 0),
            previous_composite=state.get("previous_composite"),
            stagnation=dict(state.get("stagnation") or INITIAL_STAGNATION_STATE),
            previous_outputs_by_step=dict(state.get("previous_outputs_by_step") or {}),
            previous_outputs_by_role=dict(state.get("previous_outputs_by_role") or {}),
            previous_outputs_by_archetype=dict(state.get("previous_outputs_by_archetype") or {}),
            previous_handoffs_by_step=dict(state.get("previous_handoffs_by_step") or {}),
            previous_handoffs_by_role=dict(state.get("previous_handoffs_by_role") or {}),
            previous_iteration_summary=state.get("previous_iteration_summary") if isinstance(state.get("previous_iteration_summary"), dict) else None,
            previous_session_refs_by_step=dict(state.get("previous_session_refs_by_step") or {}),
            step_results=list(state.get("step_results") or []),
            current_outputs_by_step=dict(state.get("current_outputs_by_step") or {}),
            current_outputs_by_role=dict(state.get("current_outputs_by_role") or {}),
            current_outputs_by_archetype=dict(state.get("current_outputs_by_archetype") or {}),
            current_handoffs=list(state.get("current_handoffs") or []),
            current_session_refs_by_step=dict(state.get("current_session_refs_by_step") or {}),
            current_gatekeeper_result=state.get("current_gatekeeper_result") if isinstance(state.get("current_gatekeeper_result"), dict) else None,
            current_guide_result=state.get("current_guide_result") if isinstance(state.get("current_guide_result"), dict) else None,
        )

    def _state_from_iteration(self, iteration: _WorkflowIterationState) -> dict[str, Any]:
        return {
            "iter_id": iteration.iter_id,
            "previous_composite": iteration.previous_composite,
            "stagnation": iteration.stagnation,
            "previous_outputs_by_step": iteration.previous_outputs_by_step,
            "previous_outputs_by_role": iteration.previous_outputs_by_role,
            "previous_outputs_by_archetype": iteration.previous_outputs_by_archetype,
            "previous_handoffs_by_step": iteration.previous_handoffs_by_step,
            "previous_handoffs_by_role": iteration.previous_handoffs_by_role,
            "previous_iteration_summary": iteration.previous_iteration_summary,
            "previous_session_refs_by_step": iteration.previous_session_refs_by_step,
            "step_results": iteration.step_results,
            "current_outputs_by_step": iteration.current_outputs_by_step,
            "current_outputs_by_role": iteration.current_outputs_by_role,
            "current_outputs_by_archetype": iteration.current_outputs_by_archetype,
            "current_handoffs": iteration.current_handoffs,
            "current_session_refs_by_step": iteration.current_session_refs_by_step,
            "current_gatekeeper_result": iteration.current_gatekeeper_result,
            "current_guide_result": iteration.current_guide_result,
        }

    def _agent_native_state(self, layout, *, adapter: str, run: dict) -> dict[str, Any]:
        path = self._agent_native_state_path(layout)
        if path.exists():
            try:
                payload = read_json(path)
            except (OSError, UnicodeError, ValueError) as exc:
                raise LooporaError(f"agent-native state is unreadable: {path}: {exc}") from exc
            if isinstance(payload, dict) and payload:
                return payload
        return {
            "version": 1,
            "execution_plane": "agent_native",
            "adapter": adapter,
            "run_id": run["id"],
            "status": "awaiting_agent",
            "iter_id": 0,
            "step_index": 0,
            "previous_composite": None,
            "stagnation": dict(INITIAL_STAGNATION_STATE),
            "previous_outputs_by_step": {},
            "previous_outputs_by_role": {},
            "previous_outputs_by_archetype": {},
            "previous_handoffs_by_step": {},
            "previous_handoffs_by_role": {},
            "previous_iteration_summary": None,
            "previous_session_refs_by_step": {},
            "current_outputs_by_step": {},
            "current_outputs_by_role": {},
            "current_outputs_by_archetype": {},
            "current_handoffs": [],
            "current_session_refs_by_step": {},
            "current_gatekeeper_result": None,
            "current_guide_result": None,
            "step_results": [],
            "control_fire_counts": {},
            "host_dispatches": [],
            "active_step": {},
        }

    def _write_agent_native_state(self, layout, state: dict[str, Any]) -> None:
        write_json(self._agent_native_state_path(layout), state)

    @staticmethod
    def _agent_native_state_path(layout) -> Path:
        return layout.run_dir / "agent_native" / "state.json"

    def _agent_native_capsule(  # noqa: PLR0913 - capsule fields are the public step contract projection.
        self,
        adapter: str,
        *,
        run: dict,
        layout,
        iter_id: int,
        step: dict,
        step_order: int,
        role: dict,
        runtime_role: str,
        prompt: str,
        output_schema: dict,
    ) -> dict[str, Any]:
        context_path = layout.step_context_path(iter_id, step_order, step["id"])
        output_path = layout.step_output_raw_path(iter_id, step_order, step["id"])
        known_evidence_ids = [
            str(item.get("id"))
            for item in read_jsonl(layout.evidence_ledger_path)
            if isinstance(item, dict) and str(item.get("id") or "").strip()
        ]
        target_agent = self._agent_native_target_agent(role["archetype"])
        return {
            "execution_plane": "agent_native",
            "adapter": adapter,
            "run_id": run["id"],
            "run_path": f"/runs/{run['id']}",
            "iter": iter_id,
            "step_id": step["id"],
            "step_order": step_order,
            "parallel_group": str(step.get("parallel_group") or ""),
            "role": {
                "id": role["id"],
                "name": role["name"],
                "archetype": role["archetype"],
                "runtime_role": runtime_role,
            },
            "role_dispatch": {
                "required": True,
                "dispatch_contract": "host_native_subagent",
                "target_agent": target_agent,
                "target_role_archetype": role["archetype"],
                "inline_allowed": False,
                "proof_field": "loopora_host_dispatch",
                "result_field": "result",
                "accepted_dispatch_modes": ["host_subagent", "host_task", "host_agent"],
            },
            "action_policy": dict(step.get("action_policy") or {}),
            "prompt": prompt,
            "output_schema": output_schema,
            "evidence_rules": self._agent_native_evidence_rules(role["archetype"]),
            "evidence_ref_contract": {
                "allowed_ids_field": "known_evidence_ids",
                "unknown_ids_are_blocking": True,
                "must_copy_exact_ids": True,
            },
            "context_path": layout.relative(context_path),
            "context_absolute_path": str(context_path.resolve()),
            "result_output_path": layout.relative(output_path),
            "submit_hint": {
                "command": f"loopora agent {adapter} submit --workdir \"$PWD\" --run-id {run['id']} --step-id {step['id']} --result-file <result-json>",
                "result_file_contract": "Write one wrapper JSON object with loopora_host_dispatch and result; result must match output_schema.",
            },
            "known_evidence_ids": known_evidence_ids,
        }

    @staticmethod
    def _agent_native_target_agent(archetype: str) -> str:
        normalized = str(archetype or "").strip().lower()
        if normalized == "builder":
            return "loopora-builder"
        if normalized == "gatekeeper":
            return "loopora-gatekeeper"
        if normalized == "guide":
            return "loopora-guide"
        return "loopora-inspector"

    def _validate_agent_native_host_dispatch(self, context: dict[str, Any], dispatch: dict[str, Any] | None) -> dict[str, Any]:
        adapter = str(context["adapter"])
        run = context["run"]
        step_id = str(context["step_id"])
        role = context["role"]
        active = context["active"]
        capsule = active.get("capsule") if isinstance(active.get("capsule"), dict) else {}
        role_dispatch = capsule.get("role_dispatch") if isinstance(capsule.get("role_dispatch"), dict) else {}
        if not role_dispatch.get("required"):
            return {}
        if not isinstance(dispatch, dict) or not dispatch:
            raise LooporaConflictError("agent-native submit requires loopora_host_dispatch proof from the host native role agent")

        expected_agent = str(role_dispatch.get("target_agent") or self._agent_native_target_agent(role.get("archetype", ""))).strip()
        accepted_modes = {str(item) for item in list(role_dispatch.get("accepted_dispatch_modes") or []) if str(item).strip()}
        actual_agent = str(dispatch.get("actual_agent") or dispatch.get("agent_name") or "").strip()
        target_agent = str(dispatch.get("target_agent") or "").strip()
        dispatch_mode = str(dispatch.get("dispatch_mode") or dispatch.get("mode") or "").strip()
        inline = bool(dispatch.get("inline") is True)

        if actual_agent != expected_agent or target_agent != expected_agent:
            raise LooporaConflictError(f"agent-native submit used {actual_agent or target_agent or 'unknown'} but expected {expected_agent}")
        if accepted_modes and dispatch_mode not in accepted_modes:
            raise LooporaConflictError(f"agent-native submit dispatch_mode must be one of {sorted(accepted_modes)}")
        if inline and not bool(role_dispatch.get("inline_allowed")):
            raise LooporaConflictError("agent-native submit cannot claim inline role execution for this step")

        dispatch_run_id = str(dispatch.get("run_id") or "").strip()
        dispatch_step_id = str(dispatch.get("step_id") or "").strip()
        dispatch_adapter = str(dispatch.get("adapter") or "").strip()
        if dispatch_run_id and dispatch_run_id != str(run["id"]):
            raise LooporaConflictError("agent-native host dispatch run_id does not match the submitted run")
        if dispatch_step_id and dispatch_step_id != step_id:
            raise LooporaConflictError("agent-native host dispatch step_id does not match the submitted step")
        if dispatch_adapter and dispatch_adapter != adapter:
            raise LooporaConflictError("agent-native host dispatch adapter does not match the submitted adapter")

        return {
            "schema_version": int(dispatch.get("schema_version") or 1),
            "adapter": adapter,
            "run_id": str(run["id"]),
            "step_id": step_id,
            "target_agent": expected_agent,
            "actual_agent": actual_agent,
            "dispatch_mode": dispatch_mode,
            "inline": inline,
            "attestation": str(dispatch.get("attestation") or "").strip(),
        }

    @staticmethod
    def _agent_native_evidence_rules(archetype: str) -> list[dict[str, str]]:
        base_rules = [
            {
                "id": "evidence_refs.must_be_exact_known_ids",
                "severity": "hard",
                "rule": "Every evidence_refs value, including coverage_results evidence_refs, must be copied exactly from known_evidence_ids. Do not invent, suffix, split, or derive new evidence IDs.",
            }
        ]
        if archetype == "inspector":
            return [
                *base_rules,
                {
                    "id": "inspector.coverage_requires_current_evidence",
                    "severity": "hard",
                    "rule": "Mark coverage passed only when current upstream evidence already proves it.",
                },
                {
                    "id": "inspector.no_future_terminal_claim",
                    "severity": "hard",
                    "rule": "Do not mark a future terminal run state as passed before GateKeeper has completed.",
                },
            ]
        if archetype == "gatekeeper":
            return [
                *base_rules,
                {
                    "id": "gatekeeper.pass_requires_supporting_upstream_evidence",
                    "severity": "hard",
                    "rule": "A pass must cite supporting upstream evidence_refs from known_evidence_ids.",
                },
                {
                    "id": "gatekeeper.blocked_refs_do_not_support_pass",
                    "severity": "hard",
                    "rule": "Evidence from blocked, failed, rejected, or errored steps cannot support a pass.",
                },
                {
                    "id": "gatekeeper.finish_coverage_is_core_derived",
                    "severity": "hard",
                    "rule": "Do not add a passed gatekeeper.finish coverage row; Loopora Core derives finish coverage from the submitted verdict.",
                },
            ]
        if archetype == "builder":
            return [
                *base_rules,
                {
                    "id": "builder.proof_artifacts_strengthen_evidence",
                    "severity": "advisory",
                    "rule": "When possible, include concrete proof_files or proof_artifacts so downstream GateKeeper evidence is supportable.",
                },
            ]
        return base_rules
