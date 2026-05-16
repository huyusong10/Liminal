from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
import itertools
import logging
import os
import time
from pathlib import Path

from loopora.context_flow import evidence_entry_id
from loopora.diagnostics import get_logger, log_event
from loopora.executor import ExecutionStopped
from loopora.recovery import RetryConfig
from loopora.run_artifacts import read_jsonl, read_stagnation_state
from loopora.service_types import (
    LooporaNotFoundError,
    RoleExecutionError,
    StopRequested,
    WorkspaceSafetyError,
    normalize_completion_mode,
)
from loopora.structured_booleans import structured_bool_is_true
from loopora.service_workflow_failure_handling import ServiceWorkflowFailureHandlingMixin, WorkflowExhaustionRequest
from loopora.service_workflow_iteration_state import (
    GatekeeperIterationRecordRequest,
    ServiceWorkflowIterationStateMixin,
    WorkflowGatekeeperSuccessRequest,
    WorkflowIterationCheckpointRequest,
    WorkflowStepCompletionLogRequest,
    WorkflowStepResultEntryRequest,
    WorkflowStepWriteRequest,
)
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
from loopora.workflows import normalize_workflow
from loopora.utils import read_json
from loopora.structured_numbers import structured_non_negative_int

logger = get_logger(__name__)


def _evidence_context_with_canonical_items(context_packet: dict, layout: object) -> dict:
    evidence_context = context_packet.get("evidence") if isinstance(context_packet.get("evidence"), dict) else {}
    known_ids = {str(item).strip() for item in list(evidence_context.get("known_ids") or []) if str(item).strip()}
    current_items = [item for item in list(evidence_context.get("items") or []) if isinstance(item, dict)]
    current_ids = {str(item.get("id") or "").strip() for item in current_items if str(item.get("id") or "").strip()}
    if not known_ids or known_ids.issubset(current_ids):
        return dict(evidence_context)
    canonical_items = [item for item in read_jsonl(layout.evidence_ledger_path) if isinstance(item, dict) and str(item.get("id") or "").strip() in known_ids]
    return {**dict(evidence_context), "items": canonical_items}


@dataclass
class _WorkflowRunContext:
    run_id: str
    run: dict
    run_dir: Path
    workflow: dict
    executor: object
    compiled_spec: dict
    retry_config: RetryConfig
    prompt_files: dict[str, str]
    layout: object
    run_contract: dict
    workflow_steps: list[dict]
    workflow_controls: list[dict]
    control_fire_counts: dict[str, int]
    workflow_started_at: float
    role_by_id: dict[str, dict]
    completion_mode: str
    last_gatekeeper_result: dict | None = None


@dataclass
class _WorkflowIterationState:
    iter_id: int
    previous_composite: object
    stagnation: dict
    previous_outputs_by_step: dict[str, dict]
    previous_outputs_by_role: dict[str, dict]
    previous_outputs_by_archetype: dict[str, dict]
    previous_handoffs_by_step: dict[str, dict]
    previous_handoffs_by_role: dict[str, dict]
    previous_iteration_summary: dict | None
    previous_session_refs_by_step: dict[str, dict]
    step_results: list[dict] = field(default_factory=list)
    current_outputs_by_step: dict[str, dict] = field(default_factory=dict)
    current_outputs_by_role: dict[str, dict] = field(default_factory=dict)
    current_outputs_by_archetype: dict[str, dict] = field(default_factory=dict)
    current_handoffs: list[dict] = field(default_factory=list)
    current_session_refs_by_step: dict[str, dict] = field(default_factory=dict)
    current_gatekeeper_result: dict | None = None
    current_guide_result: dict | None = None

    def snapshot(self) -> dict[str, object]:
        return {
            "current_outputs_by_step": dict(self.current_outputs_by_step),
            "current_outputs_by_role": dict(self.current_outputs_by_role),
            "current_outputs_by_archetype": dict(self.current_outputs_by_archetype),
            "current_handoffs": list(self.current_handoffs),
        }


@dataclass
class _WorkflowRunProgress:
    stagnation: dict
    last_iter_id: int = -1
    last_step_results: list[dict] = field(default_factory=list)
    previous_outputs_by_step: dict[str, dict] = field(default_factory=dict)
    previous_outputs_by_role: dict[str, dict] = field(default_factory=dict)
    previous_outputs_by_archetype: dict[str, dict] = field(default_factory=dict)
    previous_handoffs_by_step: dict[str, dict] = field(default_factory=dict)
    previous_handoffs_by_role: dict[str, dict] = field(default_factory=dict)
    previous_iteration_summary: dict | None = None
    previous_session_refs_by_step: dict[str, dict] = field(default_factory=dict)


@dataclass(frozen=True)
class _WorkflowStepRunRequest:
    context: _WorkflowRunContext
    iteration: _WorkflowIterationState
    step_order: int
    step: dict
    state_snapshot: dict[str, object]
    is_control: bool = False


def _workflow_role_error_signal(exc: Exception) -> str:
    return "role_timeout" if "timeout" in str(exc).lower() else "step_failed"


class ServiceWorkflowExecutionMixin(
    ServiceWorkflowIterationStateMixin,
    ServiceWorkflowFailureHandlingMixin,
):
    def _run_workflow_step_once(
        self,
        request: _WorkflowStepRunRequest,
    ) -> dict:
        context = request.context
        iteration = request.iteration
        step_order = request.step_order
        step = request.step
        state_snapshot = request.state_snapshot
        role = context.role_by_id[step["role_id"]]
        runtime_role = self._runtime_role_key(role)

        execution_settings = self._resolve_role_execution_settings(context.run, step, role)
        log_event(
            logger,
            logging.INFO,
            "service.workflow.step.started",
            "Starting workflow step",
            **self._run_log_context(
                context.run,
                iter=iteration.iter_id,
                step_id=step["id"],
                role=runtime_role,
                archetype=role["archetype"],
                executor_kind=execution_settings["executor_kind"],
                executor_mode=execution_settings["executor_mode"],
                model=execution_settings["model"],
                parallel_group=step.get("parallel_group"),
            ),
        )
        step_started_at = time.perf_counter()
        output, context_packet, session_ref = self._run_workflow_step(
            WorkflowStepRuntimeRequest(
                executor=context.executor,
                run=context.run,
                compiled_spec=context.compiled_spec,
                layout=context.layout,
                iter_id=iteration.iter_id,
                step=step,
                step_order=step_order,
                role=role,
                prompt_files=context.prompt_files,
                execution_settings=execution_settings,
                run_contract=context.run_contract,
                current_outputs_by_step=dict(state_snapshot["current_outputs_by_step"]),
                current_outputs_by_role=dict(state_snapshot["current_outputs_by_role"]),
                current_outputs_by_archetype=dict(state_snapshot["current_outputs_by_archetype"]),
                current_handoffs=list(state_snapshot["current_handoffs"]),
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
            )
        )
        normalized_output = self._normalize_step_output(
            StepOutputNormalizationRequest(
                archetype=role["archetype"],
                output=output,
                compiled_spec=context.compiled_spec,
                inspector_output=dict(state_snapshot["current_outputs_by_archetype"]).get("inspector"),
                evidence_context=_evidence_context_with_canonical_items(context_packet, context.layout),
                current_evidence_id=evidence_entry_id(iteration.iter_id, step_order, step["id"]),
            )
        )
        return {
            "skipped": False,
            "step_order": step_order,
            "step": step,
            "role": role,
            "runtime_role": runtime_role,
            "execution_settings": execution_settings,
            "normalized_output": normalized_output,
            "context_packet": context_packet,
            "session_ref": session_ref,
            "duration_ms": int((time.perf_counter() - step_started_at) * 1000),
        }

    def _commit_workflow_step_result(
        self,
        context: _WorkflowRunContext,
        iteration: _WorkflowIterationState,
        result: dict,
    ) -> dict | None:
        if result.get("skipped"):
            return None
        step = result["step"]
        is_control_step = bool(step.get("control_id"))
        step_order = int(result["step_order"])
        role = result["role"]
        runtime_role = result["runtime_role"]
        normalized_output = result["normalized_output"]
        handoff = self._write_workflow_step_result(
            WorkflowStepWriteRequest(
                run_id=context.run_id,
                layout=context.layout,
                iter_id=iteration.iter_id,
                step=step,
                step_order=step_order,
                role=role,
                runtime_role=runtime_role,
                normalized_output=normalized_output,
            )
        )
        iteration.current_outputs_by_step[step["id"]] = normalized_output
        iteration.current_outputs_by_role[role["id"]] = normalized_output
        if runtime_role != role["id"]:
            iteration.current_outputs_by_role[runtime_role] = normalized_output
        iteration.current_outputs_by_archetype[role["archetype"]] = normalized_output
        iteration.current_handoffs.append(handoff)
        session_ref = result.get("session_ref")
        if isinstance(session_ref, dict) and session_ref:
            iteration.current_session_refs_by_step[step["id"]] = dict(session_ref)
        iteration.step_results.append(
            self._build_workflow_step_result_entry(
                WorkflowStepResultEntryRequest(
                    step=step,
                    step_order=step_order,
                    role=role,
                    runtime_role=runtime_role,
                    execution_settings=result["execution_settings"],
                    normalized_output=normalized_output,
                    handoff=handoff,
                    context_packet=result["context_packet"],
                )
            )
        )
        self._log_workflow_step_completion(
            WorkflowStepCompletionLogRequest(
                run=context.run,
                iter_id=iteration.iter_id,
                step=step,
                runtime_role=runtime_role,
                role=role,
                duration_ms=int(result["duration_ms"]),
                normalized_output=normalized_output,
            )
        )

        if role["archetype"] in {"builder", "inspector"}:
            self._enforce_workspace_safety(context.run, context.run_dir, iteration.iter_id, role=runtime_role)

        if role["archetype"] == "gatekeeper" and not is_control_step:
            iteration.current_gatekeeper_result = normalized_output
            context.last_gatekeeper_result = normalized_output
            iteration.stagnation = self._record_gatekeeper_iteration_result(
                GatekeeperIterationRecordRequest(
                    layout=context.layout,
                    stagnation=iteration.stagnation,
                    normalized_output=normalized_output,
                    iter_id=iteration.iter_id,
                    previous_composite=iteration.previous_composite,
                    run=context.run,
                    run_id=context.run_id,
                )
            )
            if context.completion_mode == "gatekeeper" and normalized_output["passed"] and bool((step.get("action_policy") or {}).get("can_finish_run")):
                return self._finish_workflow_gatekeeper_success(
                    WorkflowGatekeeperSuccessRequest(
                        run_id=context.run_id,
                        run=context.run,
                        run_dir=context.run_dir,
                        workflow=context.workflow,
                        compiled_spec=context.compiled_spec,
                        iter_id=iteration.iter_id,
                        step=step,
                        runtime_role=runtime_role,
                        normalized_output=normalized_output,
                        stagnation=iteration.stagnation,
                        previous_composite=iteration.previous_composite,
                        layout=context.layout,
                        step_results=iteration.step_results,
                        current_outputs_by_step=iteration.current_outputs_by_step,
                        current_outputs_by_role=iteration.current_outputs_by_role,
                        current_outputs_by_archetype=iteration.current_outputs_by_archetype,
                        current_session_refs_by_step=iteration.current_session_refs_by_step,
                    )
                )
        elif role["archetype"] == "guide":
            iteration.current_guide_result = normalized_output
            self.append_run_event(
                context.run_id,
                "challenger_done",
                {
                    "iter": iteration.iter_id,
                    "mode": normalized_output.get("mode"),
                    "step_id": step["id"],
                    "role_name": role["name"],
                    "archetype": role["archetype"],
                },
                role=runtime_role,
            )
        return None

    def _run_workflow_controls_for_signal(
        self,
        context: _WorkflowRunContext,
        iteration: _WorkflowIterationState,
        signal: str,
        trigger: dict[str, object],
        snapshot: dict[str, object],
    ) -> None:
        matching_controls = matching_workflow_controls(context.workflow_controls, signal)
        if not matching_controls:
            return
        for control in matching_controls:
            control_id = str(control.get("id") or "").strip()
            max_fires = int(control.get("max_fires_per_run", 1) or 1)
            fired = int(context.control_fire_counts.get(control_id, 0) or 0)
            role_id = str((control.get("call") or {}).get("role_id") or "").strip()
            elapsed_seconds = time.monotonic() - context.workflow_started_at
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
            existing_control_count = sum(1 for item in iteration.step_results if item["step"].get("control_id"))
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
            try:
                result = self._run_workflow_step_once(
                    _WorkflowStepRunRequest(
                        context=context,
                        iteration=iteration,
                        step_order=control_order,
                        step=control_step,
                        state_snapshot=snapshot,
                        is_control=True,
                    )
                )
                finish_result = self._commit_workflow_step_result(context, iteration, result)
                evidence_id = evidence_entry_id(iteration.iter_id, control_order, control_step["id"])
                self.append_run_event(
                    context.run_id,
                    "control_completed",
                    {
                        **base_payload,
                        "status": result.get("normalized_output", {}).get("status") or result.get("normalized_output", {}).get("mode") or "completed",
                        "evidence_refs": [evidence_id],
                    },
                    role=role_id,
                )
                if finish_result is not None:
                    self.append_run_event(
                        context.run_id,
                        "control_skipped",
                        {**base_payload, "skip_reason": "control_cannot_finish_run"},
                        role=role_id,
                    )
            except Exception as exc:
                self.append_run_event(
                    context.run_id,
                    "control_failed",
                    {**base_payload, "error": str(exc)},
                    role=role_id,
                )
                if str(control.get("mode") or "") == "blocking":
                    raise

    def _run_workflow_linear_step(
        self,
        context: _WorkflowRunContext,
        iteration: _WorkflowIterationState,
        step_order: int,
        step: dict,
    ) -> dict | None:
        try:
            step_result = self._run_workflow_step_once(
                _WorkflowStepRunRequest(
                    context=context,
                    iteration=iteration,
                    step_order=step_order,
                    step=step,
                    state_snapshot=iteration.snapshot(),
                )
            )
        except RoleExecutionError as exc:
            self._run_workflow_controls_for_signal(
                context,
                iteration,
                _workflow_role_error_signal(exc),
                {
                    "reason": f"step {step.get('id')} failed",
                    "failed_step_id": step.get("id"),
                    "error": str(exc),
                    "evidence_refs": [],
                },
                iteration.snapshot(),
            )
            raise
        return self._commit_workflow_step_result(context, iteration, step_result)

    def _collect_workflow_parallel_group(
        self,
        context: _WorkflowRunContext,
        group_start: int,
        parallel_group: str,
    ) -> tuple[int, list[tuple[int, dict]]]:
        step_index = group_start
        group_items: list[tuple[int, dict]] = []
        while step_index < len(context.workflow_steps) and str(context.workflow_steps[step_index].get("parallel_group") or "").strip() == parallel_group:
            group_items.append((step_index, context.workflow_steps[step_index]))
            step_index += 1
        return step_index, group_items

    def _run_workflow_parallel_group(
        self,
        context: _WorkflowRunContext,
        iteration: _WorkflowIterationState,
        parallel_group: str,
        group_start: int,
        group_items: list[tuple[int, dict]],
    ) -> dict | None:
        group_snapshot = iteration.snapshot()
        self.append_run_event(
            context.run_id,
            "parallel_group_started",
            {
                "iter": iteration.iter_id,
                "parallel_group": parallel_group,
                "step_orders": [order for order, _step in group_items],
                "step_ids": [_step["id"] for _order, _step in group_items],
            },
        )
        log_event(
            logger,
            logging.INFO,
            "service.workflow.parallel_group.started",
            "Starting workflow parallel group",
            **self._run_log_context(
                context.run,
                iter=iteration.iter_id,
                parallel_group=parallel_group,
                step_count=len(group_items),
                group_start=group_start,
            ),
        )
        with ThreadPoolExecutor(max_workers=len(group_items)) as pool:
            futures = [
                pool.submit(
                    self._run_workflow_step_once,
                    _WorkflowStepRunRequest(
                        context=context,
                        iteration=iteration,
                        step_order=order,
                        step=group_step,
                        state_snapshot=group_snapshot,
                    ),
                )
                for order, group_step in group_items
            ]
            parallel_results = []
            for (_, group_step), future in zip(group_items, futures, strict=False):
                try:
                    parallel_results.append(future.result())
                except RoleExecutionError as exc:
                    self._run_workflow_controls_for_signal(
                        context,
                        iteration,
                        _workflow_role_error_signal(exc),
                        {
                            "reason": f"parallel step {group_step.get('id')} failed",
                            "failed_step_id": group_step.get("id"),
                            "error": str(exc),
                            "evidence_refs": [],
                        },
                        group_snapshot,
                    )
                    raise
        for result in sorted(parallel_results, key=lambda item: int(item["step_order"])):
            finish_result = self._commit_workflow_step_result(context, iteration, result)
            if finish_result is not None:
                return finish_result
        self.append_run_event(
            context.run_id,
            "parallel_group_finished",
            {
                "iter": iteration.iter_id,
                "parallel_group": parallel_group,
                "step_orders": [order for order, _step in group_items],
                "step_ids": [_step["id"] for _order, _step in group_items],
            },
        )
        return None

    def _run_workflow_iteration_steps(
        self,
        context: _WorkflowRunContext,
        iteration: _WorkflowIterationState,
    ) -> dict | None:
        step_index = 0
        while step_index < len(context.workflow_steps):
            step = context.workflow_steps[step_index]
            parallel_group = str(step.get("parallel_group") or "").strip()
            if not parallel_group:
                finish_result = self._run_workflow_linear_step(context, iteration, step_index, step)
                if finish_result is not None:
                    return finish_result
                step_index += 1
                continue

            group_start = step_index
            step_index, group_items = self._collect_workflow_parallel_group(context, group_start, parallel_group)
            finish_result = self._run_workflow_parallel_group(
                context,
                iteration,
                parallel_group,
                group_start,
                group_items,
            )
            if finish_result is not None:
                return finish_result
        return None

    def _run_workflow_iteration_controls(
        self,
        context: _WorkflowRunContext,
        iteration: _WorkflowIterationState,
    ) -> None:
        for trigger in workflow_iteration_control_triggers(iteration.current_gatekeeper_result, iteration.stagnation):
            self._run_workflow_controls_for_signal(
                context,
                iteration,
                trigger.signal,
                trigger.trigger,
                iteration.snapshot(),
            )

    def _prepare_workflow_run_context(
        self,
        run_id: str,
        run: dict,
        run_dir: Path,
        workflow: dict,
    ) -> _WorkflowRunContext:
        executor = self.executor_factory()
        compiled_spec = run["compiled_spec_json"]
        retry_config = RetryConfig(max_retries=run["max_role_retries"])
        prompt_files = self._read_prompt_files_for_run(run)
        layout = self._run_artifact_layout(run_dir)
        workflow = normalize_workflow(workflow)
        role_by_id = {role["id"]: role for role in workflow.get("roles", [])}
        workflow_steps = list(workflow.get("steps", []))
        workflow_controls = list(workflow.get("controls", []))
        completion_mode = normalize_completion_mode(run.get("completion_mode", "gatekeeper"))

        self.append_run_event(run_id, "run_started", {"status": "running"})
        self._write_summary(run_id, "running", "Resolving checks for this run.")
        compiled_spec = self._resolve_run_checks(run, executor, compiled_spec, run_dir, retry_config)
        run_contract = read_json(layout.run_contract_path)
        self._write_summary(run_id, "running", "Waiting for the first workflow iteration to complete.")
        log_event(
            logger,
            logging.INFO,
            "service.workflow.execution.started",
            "Starting workflow run execution",
            **self._run_log_context(
                run,
                completion_mode=completion_mode,
                step_count=len(workflow_steps),
                role_count=len(role_by_id),
            ),
        )
        return _WorkflowRunContext(
            run_id=run_id,
            run=run,
            run_dir=run_dir,
            workflow=workflow,
            executor=executor,
            compiled_spec=compiled_spec,
            retry_config=retry_config,
            prompt_files=prompt_files,
            layout=layout,
            run_contract=run_contract,
            workflow_steps=workflow_steps,
            workflow_controls=workflow_controls,
            control_fire_counts={},
            workflow_started_at=time.monotonic(),
            role_by_id=role_by_id,
            completion_mode=completion_mode,
        )

    def _new_workflow_run_progress(self, context: _WorkflowRunContext) -> _WorkflowRunProgress:
        return _WorkflowRunProgress(stagnation=read_stagnation_state(context.layout.timeline_stagnation_path))

    def _build_workflow_iteration_state(
        self,
        context: _WorkflowRunContext,
        progress: _WorkflowRunProgress,
        iter_id: int,
    ) -> _WorkflowIterationState:
        previous_composite = context.last_gatekeeper_result.get("composite_score") if isinstance(context.last_gatekeeper_result, dict) else None
        return _WorkflowIterationState(
            iter_id=iter_id,
            previous_composite=previous_composite,
            stagnation=progress.stagnation,
            previous_outputs_by_step=progress.previous_outputs_by_step,
            previous_outputs_by_role=progress.previous_outputs_by_role,
            previous_outputs_by_archetype=progress.previous_outputs_by_archetype,
            previous_handoffs_by_step=progress.previous_handoffs_by_step,
            previous_handoffs_by_role=progress.previous_handoffs_by_role,
            previous_iteration_summary=progress.previous_iteration_summary,
            previous_session_refs_by_step=progress.previous_session_refs_by_step,
        )

    def _log_workflow_iteration_started(
        self,
        context: _WorkflowRunContext,
        iteration: _WorkflowIterationState,
    ) -> None:
        log_event(
            logger,
            logging.INFO,
            "service.workflow.iteration.started",
            "Starting workflow iteration",
            **self._run_log_context(
                context.run,
                iter=iteration.iter_id,
                step_count=len(context.workflow_steps),
                previous_composite_score=iteration.previous_composite,
                stagnation_mode=iteration.stagnation.get("stagnation_mode", "none"),
            ),
        )

    def _checkpoint_workflow_iteration_progress(
        self,
        context: _WorkflowRunContext,
        progress: _WorkflowRunProgress,
        iteration: _WorkflowIterationState,
    ) -> None:
        (
            progress.previous_outputs_by_step,
            progress.previous_outputs_by_role,
            progress.previous_outputs_by_archetype,
            progress.previous_handoffs_by_step,
            progress.previous_handoffs_by_role,
            _previous_handoffs_by_archetype,
            progress.previous_iteration_summary,
        ) = self._checkpoint_workflow_iteration_state(
            WorkflowIterationCheckpointRequest(
                layout=context.layout,
                iter_id=iteration.iter_id,
                step_results=iteration.step_results,
                current_outputs_by_step=iteration.current_outputs_by_step,
                current_outputs_by_role=iteration.current_outputs_by_role,
                current_outputs_by_archetype=iteration.current_outputs_by_archetype,
                current_session_refs_by_step=iteration.current_session_refs_by_step,
                stagnation=iteration.stagnation,
                previous_composite=iteration.previous_composite,
                run_id=context.run_id,
            )
        )
        progress.previous_session_refs_by_step = dict(iteration.current_session_refs_by_step)
        progress.last_step_results = iteration.step_results
        progress.stagnation = iteration.stagnation
        summary = self._build_workflow_summary(
            WorkflowSummaryRequest(
                run=context.run,
                workflow=context.workflow,
                compiled_spec=context.compiled_spec,
                iter_id=iteration.iter_id,
                step_results=iteration.step_results,
                stagnation=progress.stagnation,
                exhausted=False,
                previous_composite=iteration.previous_composite,
            )
        )
        self._write_summary(context.run_id, "running", summary)
        log_event(
            logger,
            logging.INFO,
            "service.workflow.iteration.completed",
            "Completed workflow iteration",
            **self._run_log_context(
                context.run,
                iter=iteration.iter_id,
                executed_step_count=len(iteration.step_results),
                stagnation_mode=progress.stagnation.get("stagnation_mode", "none"),
                gatekeeper_passed=structured_bool_is_true(
                    iteration.current_gatekeeper_result.get("passed") if iteration.current_gatekeeper_result else None
                ),
                guide_used=iteration.current_guide_result is not None,
            ),
        )

    def _run_workflow_iteration(
        self,
        context: _WorkflowRunContext,
        progress: _WorkflowRunProgress,
        iter_id: int,
    ) -> dict | None:
        progress.last_iter_id = iter_id
        self._ensure_not_stopped(context.run_id)
        self.repository.update_run(context.run_id, current_iter=iter_id)
        iteration = self._build_workflow_iteration_state(context, progress, iter_id)
        self._log_workflow_iteration_started(context, iteration)
        finish_result = self._run_workflow_iteration_steps(context, iteration)
        if finish_result is not None:
            return finish_result
        self._run_workflow_iteration_controls(context, iteration)
        self._checkpoint_workflow_iteration_progress(context, progress, iteration)
        return None

    def _handle_workflow_execution_exception(
        self,
        run_id: str,
        run: dict,
        run_dir: Path,
        exc: BaseException,
    ) -> dict:
        if isinstance(exc, (StopRequested, ExecutionStopped)):
            return self._handle_workflow_stop(run_id, run, run_dir)
        if isinstance(exc, RoleExecutionError):
            return self._handle_workflow_role_execution_error(run_id, run, run_dir, exc)
        if isinstance(exc, WorkspaceSafetyError):
            return self._handle_workflow_workspace_safety_error(run_id, run, run_dir, exc)
        if isinstance(exc, Exception):
            return self._handle_workflow_unexpected_error(run_id, run, run_dir, exc)
        raise exc

    def _execute_workflow_run(self, run_id: str, run: dict, run_dir: Path, workflow: dict) -> dict:
        try:
            self.repository.update_run(run_id, runner_pid=os.getpid())
            self._wait_for_slot(run_id)
            run = self.repository.get_run(run_id)
            if not run:
                raise LooporaNotFoundError(f"unknown run after queue wait: {run_id}")
            if run["status"] == "stopped":
                return self._hydrate_run_files(run)

            context = self._prepare_workflow_run_context(run_id, run, run_dir, workflow)
            progress = self._new_workflow_run_progress(context)
            iteration_interval_seconds = float(context.run.get("iteration_interval_seconds", 0.0) or 0.0)
            iteration_source = itertools.count() if context.run["max_iters"] == 0 else range(context.run["max_iters"])

            for iter_id in iteration_source:
                finish_result = self._run_workflow_iteration(context, progress, iter_id)
                if finish_result is not None:
                    return finish_result
                if iteration_interval_seconds > 0 and (context.run["max_iters"] == 0 or iter_id < context.run["max_iters"] - 1):
                    self._pause_between_iterations(context.run_id, iteration_interval_seconds, iter_id)

            summary = self._build_workflow_summary(
                WorkflowSummaryRequest(
                    run=context.run,
                    workflow=context.workflow,
                    compiled_spec=context.compiled_spec,
                    iter_id=progress.last_iter_id,
                    step_results=progress.last_step_results,
                    stagnation=progress.stagnation,
                    exhausted=True,
                    previous_composite=None,
                )
            )
            return self._handle_workflow_exhaustion(
                WorkflowExhaustionRequest(
                    run_id=context.run_id,
                    run=context.run,
                    run_dir=context.run_dir,
                    completion_mode=context.completion_mode,
                    last_iter_id=progress.last_iter_id,
                    summary=summary,
                )
            )
        except (StopRequested, ExecutionStopped, RoleExecutionError, WorkspaceSafetyError) as exc:
            return self._handle_workflow_execution_exception(run_id, run, run_dir, exc)
        except Exception as exc:  # noqa: BLE001 - workflow crash boundary must persist failed run state.
            return self._handle_workflow_execution_exception(run_id, run, run_dir, exc)
        finally:
            self._cleanup_run_execution(run_id, run, phase="workflow")
