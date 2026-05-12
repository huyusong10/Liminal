from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
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
from loopora.service_workflow_controls import (
    WorkflowControlPayloadRequest,
    WorkflowControlStepRequest,
    build_workflow_control_payload,
    build_workflow_control_step,
    matching_workflow_controls,
    workflow_control_after_seconds,
    workflow_iteration_control_triggers,
)
from loopora.service_workflow_support import StepOutputNormalizationRequest, WorkflowSummaryRequest
from loopora.structured_booleans import structured_bool_is_true
from loopora.structured_numbers import structured_non_negative_int
from loopora.utils import read_json, utc_now, write_json
from loopora.workflows import normalize_workflow


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


@dataclass(frozen=True)
class _AgentNativeRuntimeClaimRequest:
    kind: str
    run: dict
    state: dict[str, Any]
    context: _WorkflowRunContext
    iteration: _WorkflowIterationState
    step: dict
    step_order: int


@dataclass(frozen=True)
class _AgentNativeControlSignalRequest:
    run: dict
    context: _WorkflowRunContext
    iteration: _WorkflowIterationState
    queue: list[dict[str, Any]]
    signal: str
    trigger: dict[str, object]


@dataclass(frozen=True)
class _AgentNativeClaimInputSnapshot:
    current_outputs_by_step: dict[str, dict]
    current_outputs_by_role: dict[str, dict]
    current_outputs_by_archetype: dict[str, dict]
    current_handoffs: list[dict]
    evidence_items_snapshot: list[dict] | None = None


@dataclass(frozen=True)
class _AgentNativeStepAdvanceRequest:
    run: dict
    state: dict[str, Any]
    context: _WorkflowRunContext
    iter_id: int
    step: dict
    step_order: int
    is_control_step: bool


def _agent_native_string_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _agent_native_output_evidence_refs(output: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    refs.extend(_agent_native_string_list(output.get("evidence_refs")))
    for item in list(output.get("coverage_results") or []):
        if isinstance(item, dict):
            refs.extend(_agent_native_string_list(item.get("evidence_refs")))
    return list(dict.fromkeys(refs))


def _agent_native_known_evidence_ids(active: dict, context_packet: dict) -> set[str]:
    capsule = active.get("capsule") if isinstance(active.get("capsule"), dict) else {}
    known_ids = _agent_native_string_list(capsule.get("known_evidence_ids"))
    if not known_ids:
        evidence = context_packet.get("evidence") if isinstance(context_packet.get("evidence"), dict) else {}
        known_ids = _agent_native_string_list(evidence.get("known_ids"))
    return set(known_ids)


def _agent_native_unknown_evidence_refs(output: dict[str, Any], *, active: dict, context_packet: dict) -> list[str]:
    known_ids = _agent_native_known_evidence_ids(active, context_packet)
    return [item for item in _agent_native_output_evidence_refs(output) if item not in known_ids]


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
        iteration = self._agent_native_iteration_state(state)
        return self._agent_native_claim_runtime_step(
            _AgentNativeRuntimeClaimRequest(
                kind=kind,
                run=run,
                state=state,
                context=context,
                iteration=iteration,
                step=step,
                step_order=step_index,
            )
        )

    def _agent_native_claim_runtime_step(
        self,
        request: _AgentNativeRuntimeClaimRequest,
    ) -> dict[str, Any]:
        kind = request.kind
        run = request.run
        state = request.state
        context = request.context
        iteration = request.iteration
        step = request.step
        step_order = request.step_order
        role = context.role_by_id[step["role_id"]]
        execution_settings = self._resolve_role_execution_settings(run, step, role)
        claim_snapshot = self._agent_native_claim_input_snapshot(state, context, iteration, step, step_order)
        prepared = self._prepare_workflow_step_request(
            WorkflowStepRuntimeRequest(
                executor=context.executor,
                run=run,
                compiled_spec=context.compiled_spec,
                layout=context.layout,
                iter_id=iteration.iter_id,
                step=step,
                step_order=step_order,
                role=role,
                prompt_files=context.prompt_files,
                execution_settings=execution_settings,
                run_contract=context.run_contract,
                current_outputs_by_step=claim_snapshot.current_outputs_by_step,
                current_outputs_by_role=claim_snapshot.current_outputs_by_role,
                current_outputs_by_archetype=claim_snapshot.current_outputs_by_archetype,
                current_handoffs=claim_snapshot.current_handoffs,
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
                covered_check_count=structured_non_negative_int(iteration.stagnation.get("latest_covered_check_count")),
                missing_check_count=structured_non_negative_int(iteration.stagnation.get("latest_missing_check_count")),
                consecutive_no_required_coverage_delta=structured_non_negative_int(
                    iteration.stagnation.get("consecutive_no_required_coverage_delta")
                ),
                retry_config=context.retry_config,
                evidence_items_snapshot=claim_snapshot.evidence_items_snapshot,
            )
        )
        runtime_role = str(prepared["runtime_role"])
        role_request = prepared["role_request"]
        context_packet = prepared["context_packet"] if isinstance(prepared.get("context_packet"), dict) else {}
        evidence_context = context_packet.get("evidence") if isinstance(context_packet.get("evidence"), dict) else {}
        capsule = self._agent_native_capsule(
            kind,
            run=run,
            layout=context.layout,
            iter_id=iteration.iter_id,
            step=step,
            step_order=step_order,
            role=role,
            runtime_role=runtime_role,
            prompt=str(prepared["prompt"]),
            output_schema=role_request.output_schema,
            known_evidence_ids=[str(item) for item in list(evidence_context.get("known_ids") or []) if str(item).strip()],
        )
        state["active_step"] = {
            "claimed_at": utc_now(),
            "capsule": capsule,
            "context_packet": context_packet,
            "execution_settings": execution_settings,
            "role": role,
            "runtime_role": runtime_role,
            "step": step,
            "step_order": step_order,
            "iter_id": iteration.iter_id,
        }
        self._write_agent_native_state(context.layout, state)
        run = self.repository.update_run(run["id"], status="awaiting_agent", current_iter=iteration.iter_id, active_role=runtime_role)
        self.append_run_event(
            run["id"],
            "agent_native_step_claimed",
            {
                "adapter": kind,
                "iter": iteration.iter_id,
                "step_id": step["id"],
                "step_order": step_order,
                "role_name": role["name"],
                "archetype": role["archetype"],
                "runtime_role": runtime_role,
                "parallel_group": str(step.get("parallel_group") or ""),
                "control_id": str(step.get("control_id") or ""),
            },
            role=runtime_role,
        )
        self._agent_native_record_parallel_group_started(run, context, iteration, step, step_order)
        return {
            "adapter": kind,
            "run": self._hydrate_run_files(run),
            "run_path": f"/runs/{run['id']}",
            "next_step": capsule,
            "complete": False,
        }

    def _agent_native_claim_input_snapshot(
        self,
        state: dict[str, Any],
        context: _WorkflowRunContext,
        iteration: _WorkflowIterationState,
        step: dict,
        step_order: int,
    ) -> _AgentNativeClaimInputSnapshot:
        parallel_group = str(step.get("parallel_group") or "").strip()
        if not parallel_group:
            state["parallel_group_snapshot"] = {}
            return _AgentNativeClaimInputSnapshot(
                current_outputs_by_step=dict(iteration.current_outputs_by_step),
                current_outputs_by_role=dict(iteration.current_outputs_by_role),
                current_outputs_by_archetype=dict(iteration.current_outputs_by_archetype),
                current_handoffs=list(iteration.current_handoffs),
            )

        snapshot = self._agent_native_parallel_group_snapshot(state, context, iteration, step_order, parallel_group)
        return _AgentNativeClaimInputSnapshot(
            current_outputs_by_step=dict(snapshot.get("current_outputs_by_step") or {}),
            current_outputs_by_role=dict(snapshot.get("current_outputs_by_role") or {}),
            current_outputs_by_archetype=dict(snapshot.get("current_outputs_by_archetype") or {}),
            current_handoffs=list(snapshot.get("current_handoffs") or []),
            evidence_items_snapshot=[item for item in list(snapshot.get("evidence_items") or []) if isinstance(item, dict)],
        )

    def _agent_native_parallel_group_snapshot(
        self,
        state: dict[str, Any],
        context: _WorkflowRunContext,
        iteration: _WorkflowIterationState,
        step_order: int,
        parallel_group: str,
    ) -> dict[str, Any]:
        group_start, group_end, group_step_ids = self._agent_native_parallel_group_bounds(context.workflow_steps, step_order, parallel_group)
        existing = state.get("parallel_group_snapshot") if isinstance(state.get("parallel_group_snapshot"), dict) else {}
        if (
            existing
            and self._agent_native_int(existing.get("iter_id"), default=-1) == iteration.iter_id
            and str(existing.get("parallel_group") or "") == parallel_group
            and self._agent_native_int(existing.get("group_start"), default=-1) == group_start
            and self._agent_native_int(existing.get("group_end"), default=-1) == group_end
        ):
            return existing

        group_step_id_set = set(group_step_ids)
        group_roles = [context.role_by_id[step["role_id"]] for step in context.workflow_steps[group_start:group_end]]
        group_role_ids = {str(role["id"]) for role in group_roles}
        group_runtime_roles = {self._runtime_role_key(role) for role in group_roles}
        group_archetypes = {str(role["archetype"]) for role in group_roles}
        snapshot = {
            "iter_id": iteration.iter_id,
            "parallel_group": parallel_group,
            "group_start": group_start,
            "group_end": group_end,
            "step_ids": group_step_ids,
            "current_outputs_by_step": {
                step_id: output for step_id, output in iteration.current_outputs_by_step.items() if step_id not in group_step_id_set
            },
            "current_outputs_by_role": {
                role_id: output
                for role_id, output in iteration.current_outputs_by_role.items()
                if role_id not in group_role_ids and role_id not in group_runtime_roles
            },
            "current_outputs_by_archetype": {
                archetype: output for archetype, output in iteration.current_outputs_by_archetype.items() if archetype not in group_archetypes
            },
            "current_handoffs": [
                handoff
                for handoff in iteration.current_handoffs
                if str(((handoff.get("source") or {}) if isinstance(handoff, dict) else {}).get("step_id") or "") not in group_step_id_set
            ],
            "evidence_items": [
                item
                for item in read_jsonl(context.layout.evidence_ledger_path)
                if not (
                    isinstance(item, dict)
                    and self._agent_native_int(item.get("iter"), default=-1) == iteration.iter_id
                    and str(item.get("step_id") or "") in group_step_id_set
                )
            ],
        }
        state["parallel_group_snapshot"] = snapshot
        return snapshot

    @staticmethod
    def _agent_native_int(value: object, *, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _agent_native_parallel_group_bounds(steps: list[dict], step_order: int, parallel_group: str) -> tuple[int, int, list[str]]:
        group_start = step_order
        while group_start > 0 and str(steps[group_start - 1].get("parallel_group") or "").strip() == parallel_group:
            group_start -= 1
        group_end = step_order + 1
        while group_end < len(steps) and str(steps[group_end].get("parallel_group") or "").strip() == parallel_group:
            group_end += 1
        return group_start, group_end, [str(step["id"]) for step in steps[group_start:group_end]]

    def _agent_native_record_parallel_group_started(
        self,
        run: dict,
        context: _WorkflowRunContext,
        iteration: _WorkflowIterationState,
        step: dict,
        step_order: int,
    ) -> None:
        parallel_group = str(step.get("parallel_group") or "").strip()
        if not parallel_group:
            return
        group_start, _group_end, _group_step_ids = self._agent_native_parallel_group_bounds(
            context.workflow_steps,
            step_order,
            parallel_group,
        )
        if step_order != group_start:
            return
        self.append_run_event(
            run["id"],
            "parallel_group_started",
            self._agent_native_parallel_group_event_payload(context.workflow_steps, iteration.iter_id, step_order, parallel_group),
        )

    def _agent_native_record_parallel_group_finished(
        self,
        run: dict,
        context: _WorkflowRunContext,
        iter_id: int,
        step: dict,
        step_order: int,
    ) -> None:
        parallel_group = str(step.get("parallel_group") or "").strip()
        if not parallel_group:
            return
        next_step_order = step_order + 1
        if next_step_order < len(context.workflow_steps) and str(context.workflow_steps[next_step_order].get("parallel_group") or "").strip() == parallel_group:
            return
        self.append_run_event(
            run["id"],
            "parallel_group_finished",
            self._agent_native_parallel_group_event_payload(context.workflow_steps, iter_id, step_order, parallel_group),
        )

    def _agent_native_parallel_group_event_payload(
        self,
        steps: list[dict],
        iter_id: int,
        step_order: int,
        parallel_group: str,
    ) -> dict[str, object]:
        group_start, _group_end, group_step_ids = self._agent_native_parallel_group_bounds(steps, step_order, parallel_group)
        return {
            "iter": iter_id,
            "parallel_group": parallel_group,
            "step_orders": list(range(group_start, group_start + len(group_step_ids))),
            "step_ids": group_step_ids,
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
        if role["archetype"] != "gatekeeper":
            unknown_refs = _agent_native_unknown_evidence_refs(output, active=active, context_packet=context_packet)
            if unknown_refs:
                raise LooporaError(
                    "agent-native evidence_refs_unknown: "
                    + ", ".join(unknown_refs[:4])
                    + ("..." if len(unknown_refs) > 4 else "")
                )
        write_json(layout.step_output_raw_path(iter_id, step_order, step_id), output)
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
            "iter_id": iter_id,
        }
        finish_result = self._commit_workflow_step_result(context, iteration, result)
        is_control_step = self._agent_native_record_control_completion(run, result)
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
        state["control_fire_counts"] = dict(context.control_fire_counts)
        state["host_dispatches"] = [*list(state.get("host_dispatches") or []), host_dispatch]
        state["active_step"] = {}
        self._agent_native_advance_state_after_submit(
            _AgentNativeStepAdvanceRequest(
                run=run,
                state=state,
                context=context,
                iter_id=iter_id,
                step=step,
                step_order=step_order,
                is_control_step=is_control_step,
            )
        )
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

    def _agent_native_advance_state_after_submit(self, request: _AgentNativeStepAdvanceRequest) -> None:
        if request.is_control_step:
            queue = [item for item in list(request.state.get("control_queue") or []) if isinstance(item, dict)]
            request.state["control_queue_index"] = self._agent_native_control_queue_index(request.state, queue=queue) + 1
            request.state["step_index"] = len(request.context.workflow_steps)
            return
        self._agent_native_record_parallel_group_finished(request.run, request.context, request.iter_id, request.step, request.step_order)
        request.state["step_index"] = request.step_order + 1
        self._agent_native_update_parallel_group_snapshot_after_submit(request.state, request.context, request.step, request.step_order)

    def _agent_native_record_control_completion(self, run: dict, result: dict) -> bool:
        step = result["step"]
        if not step.get("control_id"):
            return False
        control = step.get("control") if isinstance(step.get("control"), dict) else {}
        evidence_id = evidence_entry_id(int(result["iter_id"]), int(result["step_order"]), str(step["id"]))
        normalized_output = result["normalized_output"]
        self.append_run_event(
            run["id"],
            "control_completed",
            {
                **control,
                "status": normalized_output.get("status") or normalized_output.get("mode") or "completed",
                "evidence_refs": [evidence_id],
            },
            role=str(control.get("role_id") or result["runtime_role"]),
        )
        return True

    def _agent_native_finish_iteration_or_advance(
        self,
        adapter: str,
        run: dict,
        state: dict[str, Any],
        context: _WorkflowRunContext,
    ) -> dict[str, Any]:
        layout = context.layout
        iteration = self._agent_native_iteration_state(state)
        control_claim = self._agent_native_claim_pending_control_step(adapter, run, state, context, iteration)
        if control_claim is not None:
            return control_claim
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
                "control_queue": [],
                "control_queue_index": 0,
                "control_queue_iter": None,
                "parallel_group_snapshot": {},
                "active_step": {},
                "stagnation": iteration.stagnation,
            }
        )
        self._write_agent_native_state(layout, state)
        return self.claim_agent_native_step(AgentNativeStepClaimRequest(adapter=adapter, run_id=run["id"]))

    def _agent_native_claim_pending_control_step(
        self,
        adapter: str,
        run: dict,
        state: dict[str, Any],
        context: _WorkflowRunContext,
        iteration: _WorkflowIterationState,
    ) -> dict[str, Any] | None:
        if not context.workflow_controls:
            return None
        if not self._agent_native_control_queue_iter_matches(state.get("control_queue_iter"), iteration.iter_id):
            state["control_queue"] = self._agent_native_build_control_queue(run, state, context, iteration)
            state["control_queue_index"] = 0
            state["control_queue_iter"] = iteration.iter_id
            state["control_fire_counts"] = dict(context.control_fire_counts)
            self._write_agent_native_state(context.layout, state)

        queue = [item for item in list(state.get("control_queue") or []) if isinstance(item, dict)]
        index = self._agent_native_control_queue_index(state, queue=queue)
        if index >= len(queue):
            return None
        entry = queue[index]
        step = entry.get("step") if isinstance(entry.get("step"), dict) else {}
        step_order = self._agent_native_control_queue_step_order(entry)
        if not step or step_order is None:
            state["control_queue_index"] = index + 1
            self._write_agent_native_state(context.layout, state)
            return self._agent_native_claim_pending_control_step(adapter, run, state, context, iteration)
        return self._agent_native_claim_runtime_step(
            _AgentNativeRuntimeClaimRequest(
                kind=adapter,
                run=run,
                state=state,
                context=context,
                iteration=iteration,
                step=step,
                step_order=step_order,
            )
        )

    @staticmethod
    def _agent_native_control_queue_iter_matches(value: object, iter_id: int) -> bool:
        return isinstance(value, int) and not isinstance(value, bool) and value == iter_id

    @staticmethod
    def _agent_native_control_queue_index(state: dict[str, Any], *, queue: list[dict[str, Any]]) -> int:
        if "control_queue_index" not in state or state.get("control_queue_index") is None:
            return 0
        value = state.get("control_queue_index")
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
        return len(queue)

    @staticmethod
    def _agent_native_control_queue_step_order(entry: dict[str, Any]) -> int | None:
        value = entry.get("step_order")
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
        return None

    def _agent_native_build_control_queue(
        self,
        run: dict,
        state: dict[str, Any],
        context: _WorkflowRunContext,
        iteration: _WorkflowIterationState,
    ) -> list[dict[str, Any]]:
        queue: list[dict[str, Any]] = []
        for trigger in workflow_iteration_control_triggers(iteration.current_gatekeeper_result, iteration.stagnation):
            self._agent_native_append_controls_for_signal(
                _AgentNativeControlSignalRequest(
                    run=run,
                    context=context,
                    iteration=iteration,
                    queue=queue,
                    signal=trigger.signal,
                    trigger=trigger.trigger,
                )
            )
        state["control_fire_counts"] = dict(context.control_fire_counts)
        return queue

    def _agent_native_append_controls_for_signal(
        self,
        request: _AgentNativeControlSignalRequest,
    ) -> None:
        run = request.run
        context = request.context
        iteration = request.iteration
        queue = request.queue
        signal = request.signal
        trigger = request.trigger
        matching_controls = matching_workflow_controls(context.workflow_controls, signal)
        if not matching_controls:
            return
        for control in matching_controls:
            control_id = str(control.get("id") or "").strip()
            max_fires = structured_non_negative_int(control.get("max_fires_per_run"), default=1) or 1
            fired = self._agent_native_control_fire_count(context.control_fire_counts.get(control_id), max_fires=max_fires)
            role_id = str((control.get("call") or {}).get("role_id") or "").strip()
            elapsed_seconds = self._agent_native_elapsed_seconds(run)
            base_payload = build_workflow_control_payload(
                WorkflowControlPayloadRequest(
                    control=control,
                    iter_id=iteration.iter_id,
                    signal=signal,
                    trigger=trigger,
                    elapsed_seconds=elapsed_seconds,
                )
            )
            if fired >= max_fires:
                self.append_run_event(
                    context.run_id,
                    "control_skipped",
                    {**base_payload, "skip_reason": "max_fires_per_run"},
                )
                continue
            if elapsed_seconds < workflow_control_after_seconds(base_payload["after"]):
                self.append_run_event(
                    context.run_id,
                    "control_skipped",
                    {**base_payload, "skip_reason": "after_not_elapsed"},
                )
                continue
            role = context.role_by_id.get(role_id)
            if not role:
                self.append_run_event(
                    context.run_id,
                    "control_failed",
                    {**base_payload, "error": "control role not found"},
                )
                continue
            context.control_fire_counts[control_id] = fired + 1
            existing_control_count = sum(1 for item in iteration.step_results if item["step"].get("control_id")) + len(queue)
            control_step, control_order = build_workflow_control_step(
                WorkflowControlStepRequest(
                    control=control,
                    payload=base_payload,
                    role=role,
                    workflow_step_count=len(context.workflow_steps),
                    existing_control_count=existing_control_count,
                )
            )
            self.append_run_event(context.run_id, "control_triggered", base_payload, role=role_id)
            queue.append({"step": control_step, "step_order": control_order})

    @staticmethod
    def _agent_native_control_fire_count(value: object, *, max_fires: int) -> int:
        if value is None:
            return 0
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
        return max_fires

    @staticmethod
    def _agent_native_elapsed_seconds(run: dict) -> float:
        started_at = str(run.get("started_at") or run.get("queued_at") or run.get("created_at") or "").strip()
        if not started_at:
            return 0.0
        try:
            started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        except ValueError:
            return 0.0
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        return max((datetime.now(UTC) - started.astimezone(UTC)).total_seconds(), 0.0)

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
        workflow = normalize_workflow(workflow)
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
            workflow_controls=list(workflow.get("controls", [])),
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
            "control_queue": [],
            "control_queue_index": 0,
            "control_queue_iter": None,
            "parallel_group_snapshot": {},
            "host_dispatches": [],
            "active_step": {},
        }

    @staticmethod
    def _agent_native_update_parallel_group_snapshot_after_submit(
        state: dict[str, Any],
        context: _WorkflowRunContext,
        step: dict,
        step_order: int,
    ) -> None:
        parallel_group = str(step.get("parallel_group") or "").strip()
        if not parallel_group:
            state["parallel_group_snapshot"] = {}
            return
        next_step_order = step_order + 1
        if next_step_order < len(context.workflow_steps) and str(context.workflow_steps[next_step_order].get("parallel_group") or "").strip() == parallel_group:
            return
        state["parallel_group_snapshot"] = {}

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
        known_evidence_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        context_path = layout.step_context_path(iter_id, step_order, step["id"])
        output_path = layout.step_output_raw_path(iter_id, step_order, step["id"])
        if known_evidence_ids is None:
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

    @staticmethod
    def _required_agent_native_dispatch_text(dispatch: dict[str, Any], field: str) -> str:
        value = str(dispatch.get(field) or "").strip()
        if not value:
            raise LooporaConflictError(f"agent-native host dispatch {field} is required")
        return value

    @staticmethod
    def _agent_native_dispatch_schema_version(dispatch: dict[str, Any]) -> int:
        value = dispatch.get("schema_version")
        if value is None or value == "":
            return 1
        if isinstance(value, (bool, float)):
            raise LooporaConflictError("agent-native host dispatch schema_version must be an integer")
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise LooporaConflictError("agent-native host dispatch schema_version must be an integer") from exc

    @staticmethod
    def _agent_native_role_dispatch_for_submit(active: dict[str, Any]) -> dict[str, Any]:
        capsule = active.get("capsule") if isinstance(active.get("capsule"), dict) else {}
        role_dispatch = capsule.get("role_dispatch") if isinstance(capsule.get("role_dispatch"), dict) else {}
        if not role_dispatch:
            return {}
        if not structured_bool_is_true(role_dispatch.get("required")):
            raise LooporaConflictError("agent-native role_dispatch.required must be literal true")
        if not isinstance(role_dispatch.get("inline_allowed"), bool):
            raise LooporaConflictError("agent-native role_dispatch.inline_allowed must be a literal boolean")
        return role_dispatch

    def _validate_agent_native_host_dispatch(self, context: dict[str, Any], dispatch: dict[str, Any] | None) -> dict[str, Any]:
        adapter = str(context["adapter"])
        run = context["run"]
        step_id = str(context["step_id"])
        role = context["role"]
        active = context["active"]
        role_dispatch = self._agent_native_role_dispatch_for_submit(active)
        if not role_dispatch:
            return {}
        if not isinstance(dispatch, dict) or not dispatch:
            raise LooporaConflictError("agent-native submit requires loopora_host_dispatch proof from the host native role agent")

        expected_agent = str(role_dispatch.get("target_agent") or self._agent_native_target_agent(role.get("archetype", ""))).strip()
        accepted_modes = {str(item) for item in list(role_dispatch.get("accepted_dispatch_modes") or []) if str(item).strip()}
        actual_agent = str(dispatch.get("actual_agent") or dispatch.get("agent_name") or "").strip()
        target_agent = str(dispatch.get("target_agent") or "").strip()
        dispatch_mode = str(dispatch.get("dispatch_mode") or dispatch.get("mode") or "").strip()
        if not isinstance(dispatch.get("inline"), bool):
            raise LooporaConflictError("agent-native host dispatch inline must be a literal boolean")
        inline = dispatch["inline"]

        if actual_agent != expected_agent or target_agent != expected_agent:
            raise LooporaConflictError(f"agent-native submit used {actual_agent or target_agent or 'unknown'} but expected {expected_agent}")
        if accepted_modes and dispatch_mode not in accepted_modes:
            raise LooporaConflictError(f"agent-native submit dispatch_mode must be one of {sorted(accepted_modes)}")
        if inline and not structured_bool_is_true(role_dispatch.get("inline_allowed")):
            raise LooporaConflictError("agent-native submit cannot claim inline role execution for this step")

        dispatch_run_id = self._required_agent_native_dispatch_text(dispatch, "run_id")
        dispatch_step_id = self._required_agent_native_dispatch_text(dispatch, "step_id")
        dispatch_adapter = self._required_agent_native_dispatch_text(dispatch, "adapter")
        if dispatch_run_id != str(run["id"]):
            raise LooporaConflictError("agent-native host dispatch run_id does not match the submitted run")
        if dispatch_step_id != step_id:
            raise LooporaConflictError("agent-native host dispatch step_id does not match the submitted step")
        if dispatch_adapter != adapter:
            raise LooporaConflictError("agent-native host dispatch adapter does not match the submitted adapter")

        return {
            "schema_version": self._agent_native_dispatch_schema_version(dispatch),
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
            },
            {
                "id": "coverage_results.status_uses_coverage_vocabulary",
                "severity": "hard",
                "rule": "coverage_results.status must use coverage vocabulary such as covered, weak, blocked, or missing; keep Proven, Weak, Unproven, Blocking, and Residual risk as verdict buckets or notes.",
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
