from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import itertools
import logging
import os
import time
from pathlib import Path

from loopora.context_flow import evidence_entry_id
from loopora.diagnostics import get_logger, log_event
from loopora.executor import ExecutionStopped
from loopora.recovery import RetryConfig
from loopora.run_artifacts import INITIAL_STAGNATION_STATE
from loopora.service_types import LooporaError, RoleExecutionError, StopRequested, WorkspaceSafetyError, normalize_completion_mode
from loopora.service_workflow_failure_handling import ServiceWorkflowFailureHandlingMixin
from loopora.service_workflow_iteration_state import ServiceWorkflowIterationStateMixin
from loopora.workflows import default_step_action_policy
from loopora.utils import read_json

logger = get_logger(__name__)


def _workflow_control_after_seconds(value: object) -> float:
    text = str(value or "0s").strip().lower() or "0s"
    multiplier = 1.0
    if text.endswith("ms"):
        multiplier = 0.001
        text = text[:-2]
    elif text.endswith("s"):
        text = text[:-1]
    elif text.endswith("m"):
        multiplier = 60.0
        text = text[:-1]
    elif text.endswith("h"):
        multiplier = 3600.0
        text = text[:-1]
    try:
        return max(float(text) * multiplier, 0.0)
    except ValueError:
        return 0.0


class ServiceWorkflowExecutionMixin(
    ServiceWorkflowIterationStateMixin,
    ServiceWorkflowFailureHandlingMixin,
):
    def _execute_workflow_run(self, run_id: str, run: dict, run_dir: Path, workflow: dict) -> dict:
        try:
            self.repository.update_run(run_id, runner_pid=os.getpid())
            self._wait_for_slot(run_id)
            run = self.repository.get_run(run_id)
            if not run:
                raise LooporaError(f"unknown run after queue wait: {run_id}")
            if run["status"] == "stopped":
                return self._hydrate_run_files(run)

            executor = self.executor_factory()
            compiled_spec = run["compiled_spec_json"]
            retry_config = RetryConfig(max_retries=run["max_role_retries"])
            prompt_files = self._read_prompt_files_for_run(run)
            layout = self._run_artifact_layout(run_dir)
            stagnation = read_json(layout.timeline_stagnation_path) or dict(INITIAL_STAGNATION_STATE)
            workflow_steps = list(workflow.get("steps", []))
            workflow_controls = list(workflow.get("controls", []) or [])
            control_fire_counts: dict[str, int] = {}
            workflow_started_at = time.monotonic()
            role_by_id = {role["id"]: role for role in workflow.get("roles", [])}
            completion_mode = normalize_completion_mode(run.get("completion_mode", "gatekeeper"))
            iteration_interval_seconds = float(run.get("iteration_interval_seconds", 0.0) or 0.0)
            iteration_source = itertools.count() if run["max_iters"] == 0 else range(run["max_iters"])

            last_iter_id = -1
            last_step_results: list[dict] = []
            run_contract = read_json(layout.run_contract_path)
            previous_outputs_by_step: dict[str, dict] = {}
            previous_outputs_by_role: dict[str, dict] = {}
            previous_outputs_by_archetype: dict[str, dict] = {}
            previous_handoffs_by_step: dict[str, dict] = {}
            previous_handoffs_by_role: dict[str, dict] = {}
            previous_iteration_summary: dict | None = None
            previous_session_refs_by_step: dict[str, dict] = {}
            last_gatekeeper_result: dict | None = None

            self.repository.append_event(run_id, "run_started", {"status": "running"})
            self._write_summary(run_id, "running", "Resolving checks for this run.")
            compiled_spec = self._resolve_run_checks(run, executor, compiled_spec, run_dir, retry_config)
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

            for iter_id in iteration_source:
                last_iter_id = iter_id
                self._ensure_not_stopped(run_id)
                self.repository.update_run(run_id, current_iter=iter_id)
                previous_composite = (
                    last_gatekeeper_result.get("composite_score")
                    if isinstance(last_gatekeeper_result, dict)
                    else None
                )
                step_results: list[dict] = []
                current_outputs_by_step: dict[str, dict] = {}
                current_outputs_by_role: dict[str, dict] = {}
                current_outputs_by_archetype: dict[str, dict] = {}
                current_handoffs: list[dict] = []
                current_session_refs_by_step: dict[str, dict] = {}
                current_gatekeeper_result: dict | None = None
                current_guide_result: dict | None = None
                log_event(
                    logger,
                    logging.INFO,
                    "service.workflow.iteration.started",
                    "Starting workflow iteration",
                    **self._run_log_context(
                        run,
                        iter=iter_id,
                        step_count=len(workflow_steps),
                        previous_composite_score=previous_composite,
                        stagnation_mode=stagnation.get("stagnation_mode", "none"),
                    ),
                )

                def run_step_once(
                    step_order: int,
                    step: dict,
                    *,
                    state_snapshot: dict[str, object],
                    is_control: bool = False,
                ) -> dict:
                    role = role_by_id[step["role_id"]]
                    runtime_role = self._runtime_role_key(role)
                    if (
                        not is_control
                        and role["archetype"] == "guide"
                        and stagnation.get("stagnation_mode", "none") == "none"
                    ):
                        log_event(
                            logger,
                            logging.INFO,
                            "service.workflow.step.skipped",
                            "Skipped guide step because the run is not currently stagnating",
                            **self._run_log_context(
                                run,
                                iter=iter_id,
                                step_id=step["id"],
                                role=runtime_role,
                                archetype=role["archetype"],
                                stagnation_mode=stagnation.get("stagnation_mode", "none"),
                            ),
                        )
                        return {"skipped": True, "step_order": step_order, "step": step, "role": role}

                    execution_settings = self._resolve_role_execution_settings(run, step, role)
                    log_event(
                        logger,
                        logging.INFO,
                        "service.workflow.step.started",
                        "Starting workflow step",
                        **self._run_log_context(
                            run,
                            iter=iter_id,
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
                        executor,
                        run,
                        compiled_spec,
                        layout,
                        iter_id,
                        step,
                        step_order,
                        role,
                        prompt_files,
                        execution_settings=execution_settings,
                        run_contract=run_contract,
                        current_outputs_by_step=dict(state_snapshot["current_outputs_by_step"]),
                        current_outputs_by_role=dict(state_snapshot["current_outputs_by_role"]),
                        current_outputs_by_archetype=dict(state_snapshot["current_outputs_by_archetype"]),
                        current_handoffs=list(state_snapshot["current_handoffs"]),
                        previous_outputs_by_step=previous_outputs_by_step,
                        previous_outputs_by_role=previous_outputs_by_role,
                        previous_outputs_by_archetype=previous_outputs_by_archetype,
                        previous_handoffs_by_step=previous_handoffs_by_step,
                        previous_handoffs_by_role=previous_handoffs_by_role,
                        previous_iteration_summary=previous_iteration_summary,
                        previous_session_refs_by_step=previous_session_refs_by_step,
                        previous_composite=previous_composite,
                        stagnation_mode=stagnation.get("stagnation_mode", "none"),
                        retry_config=retry_config,
                    )
                    normalized_output = self._normalize_step_output(
                        role["archetype"],
                        output,
                        compiled_spec=compiled_spec,
                        inspector_output=dict(state_snapshot["current_outputs_by_archetype"]).get("inspector"),
                        evidence_context=context_packet.get("evidence"),
                        current_evidence_id=evidence_entry_id(iter_id, step_order, step["id"]),
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

                def commit_step_result(result: dict) -> dict | None:
                    nonlocal current_gatekeeper_result
                    nonlocal current_guide_result
                    nonlocal last_gatekeeper_result
                    nonlocal stagnation
                    if result.get("skipped"):
                        return None
                    step = result["step"]
                    is_control_step = bool(step.get("control_id"))
                    step_order = int(result["step_order"])
                    role = result["role"]
                    runtime_role = result["runtime_role"]
                    normalized_output = result["normalized_output"]
                    handoff = self._write_workflow_step_result(
                        run_id=run_id,
                        layout=layout,
                        iter_id=iter_id,
                        step=step,
                        step_order=step_order,
                        role=role,
                        runtime_role=runtime_role,
                        normalized_output=normalized_output,
                    )
                    current_outputs_by_step[step["id"]] = normalized_output
                    current_outputs_by_role[role["id"]] = normalized_output
                    if runtime_role != role["id"]:
                        current_outputs_by_role[runtime_role] = normalized_output
                    current_outputs_by_archetype[role["archetype"]] = normalized_output
                    current_handoffs.append(handoff)
                    session_ref = result.get("session_ref")
                    if isinstance(session_ref, dict) and session_ref:
                        current_session_refs_by_step[step["id"]] = dict(session_ref)
                    step_results.append(
                        self._build_workflow_step_result_entry(
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
                    self._log_workflow_step_completion(
                        run=run,
                        iter_id=iter_id,
                        step=step,
                        runtime_role=runtime_role,
                        role=role,
                        duration_ms=int(result["duration_ms"]),
                        normalized_output=normalized_output,
                    )

                    if role["archetype"] in {"builder", "inspector"}:
                        self._enforce_workspace_safety(run, run_dir, iter_id, role=runtime_role)

                    if role["archetype"] == "gatekeeper" and not is_control_step:
                        current_gatekeeper_result = normalized_output
                        last_gatekeeper_result = normalized_output
                        stagnation = self._record_gatekeeper_iteration_result(
                            layout=layout,
                            stagnation=stagnation,
                            normalized_output=normalized_output,
                            iter_id=iter_id,
                            previous_composite=previous_composite,
                            run=run,
                            run_id=run_id,
                        )
                        if (
                            completion_mode == "gatekeeper"
                            and normalized_output["passed"]
                            and bool((step.get("action_policy") or {}).get("can_finish_run"))
                        ):
                            return self._finish_workflow_gatekeeper_success(
                                run_id=run_id,
                                run=run,
                                run_dir=run_dir,
                                workflow=workflow,
                                compiled_spec=compiled_spec,
                                iter_id=iter_id,
                                step=step,
                                runtime_role=runtime_role,
                                normalized_output=normalized_output,
                                stagnation=stagnation,
                                previous_composite=previous_composite,
                                layout=layout,
                                step_results=step_results,
                                current_outputs_by_step=current_outputs_by_step,
                                current_outputs_by_role=current_outputs_by_role,
                                current_outputs_by_archetype=current_outputs_by_archetype,
                                current_session_refs_by_step=current_session_refs_by_step,
                            )
                    elif role["archetype"] == "guide":
                        current_guide_result = normalized_output
                        self.repository.append_event(
                            run_id,
                            "challenger_done",
                            {
                                "iter": iter_id,
                                "mode": normalized_output.get("mode"),
                                "step_id": step["id"],
                                "role_name": role["name"],
                                "archetype": role["archetype"],
                            },
                            role=runtime_role,
                        )
                    return None

                def state_snapshot() -> dict[str, object]:
                    return {
                        "current_outputs_by_step": dict(current_outputs_by_step),
                        "current_outputs_by_role": dict(current_outputs_by_role),
                        "current_outputs_by_archetype": dict(current_outputs_by_archetype),
                        "current_handoffs": list(current_handoffs),
                    }

                def run_controls_for_signal(signal: str, trigger: dict[str, object], snapshot: dict[str, object]) -> None:
                    matching_controls = [
                        control
                        for control in workflow_controls
                        if str((control.get("when") or {}).get("signal") or "").strip() == signal
                    ]
                    if not matching_controls:
                        return
                    for control in matching_controls:
                        control_id = str(control.get("id") or "").strip()
                        max_fires = int(control.get("max_fires_per_run", 1) or 1)
                        fired = int(control_fire_counts.get(control_id, 0) or 0)
                        role_id = str((control.get("call") or {}).get("role_id") or "").strip()
                        after = str((control.get("when") or {}).get("after") or "0s").strip() or "0s"
                        elapsed_seconds = time.monotonic() - workflow_started_at
                        base_payload = {
                            "iter": iter_id,
                            "control_id": control_id,
                            "signal": signal,
                            "mode": str(control.get("mode") or "advisory"),
                            "after": after,
                            "elapsed_seconds": round(elapsed_seconds, 3),
                            "role_id": role_id,
                            "reason": str(trigger.get("reason") or signal),
                            "trigger_evidence_refs": list(trigger.get("evidence_refs") or []),
                        }
                        if fired >= max_fires:
                            self.repository.append_event(
                                run_id,
                                "control_skipped",
                                {**base_payload, "skip_reason": "max_fires_per_run"},
                            )
                            continue
                        if elapsed_seconds < _workflow_control_after_seconds(after):
                            self.repository.append_event(
                                run_id,
                                "control_skipped",
                                {**base_payload, "skip_reason": "after_not_elapsed"},
                            )
                            continue
                        role = role_by_id.get(role_id)
                        if not role:
                            self.repository.append_event(
                                run_id,
                                "control_failed",
                                {**base_payload, "error": "control role not found"},
                            )
                            continue
                        control_fire_counts[control_id] = fired + 1
                        control_order = len(workflow_steps) + 100 + sum(1 for item in step_results if item["step"].get("control_id"))
                        control_step = {
                            "id": f"control__{control_id}",
                            "role_id": role_id,
                            "on_pass": "continue",
                            "model": "",
                            "inherit_session": False,
                            "extra_cli_args": "",
                            "action_policy": default_step_action_policy(
                                archetype=role.get("archetype"),
                                on_pass="continue",
                            ),
                            "inputs": {
                                "iteration_memory": "summary_only",
                                "evidence_query": {"limit": 40},
                            },
                            "control_id": control_id,
                            "control": base_payload,
                        }
                        self.repository.append_event(run_id, "control_triggered", base_payload, role=role_id)
                        try:
                            result = run_step_once(
                                control_order,
                                control_step,
                                state_snapshot=snapshot,
                                is_control=True,
                            )
                            finish_result = commit_step_result(result)
                            evidence_id = evidence_entry_id(iter_id, control_order, control_step["id"])
                            self.repository.append_event(
                                run_id,
                                "control_completed",
                                {
                                    **base_payload,
                                    "status": result.get("normalized_output", {}).get("status")
                                    or result.get("normalized_output", {}).get("mode")
                                    or "completed",
                                    "evidence_refs": [evidence_id],
                                },
                                role=role_id,
                            )
                            if finish_result is not None:
                                self.repository.append_event(
                                    run_id,
                                    "control_skipped",
                                    {**base_payload, "skip_reason": "control_cannot_finish_run"},
                                    role=role_id,
                                )
                        except Exception as exc:
                            self.repository.append_event(
                                run_id,
                                "control_failed",
                                {**base_payload, "error": str(exc)},
                                role=role_id,
                            )
                            if str(control.get("mode") or "") == "blocking":
                                raise

                step_index = 0
                while step_index < len(workflow_steps):
                    step = workflow_steps[step_index]
                    parallel_group = str(step.get("parallel_group") or "").strip()
                    if not parallel_group:
                        try:
                            step_result = run_step_once(step_index, step, state_snapshot=state_snapshot())
                        except RoleExecutionError as exc:
                            run_controls_for_signal(
                                "role_timeout" if "timeout" in str(exc).lower() else "step_failed",
                                {
                                    "reason": f"step {step.get('id')} failed",
                                    "failed_step_id": step.get("id"),
                                    "error": str(exc),
                                    "evidence_refs": [],
                                },
                                state_snapshot(),
                            )
                            raise
                        finish_result = commit_step_result(
                            step_result
                        )
                        if finish_result is not None:
                            return finish_result
                        step_index += 1
                        continue

                    group_start = step_index
                    group_items: list[tuple[int, dict]] = []
                    while (
                        step_index < len(workflow_steps)
                        and str(workflow_steps[step_index].get("parallel_group") or "").strip() == parallel_group
                    ):
                        group_items.append((step_index, workflow_steps[step_index]))
                        step_index += 1
                    group_snapshot = state_snapshot()
                    self.repository.append_event(
                        run_id,
                        "parallel_group_started",
                        {
                            "iter": iter_id,
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
                            run,
                            iter=iter_id,
                            parallel_group=parallel_group,
                            step_count=len(group_items),
                            group_start=group_start,
                        ),
                    )
                    with ThreadPoolExecutor(max_workers=len(group_items)) as pool:
                        futures = [
                            pool.submit(run_step_once, order, group_step, state_snapshot=group_snapshot)
                            for order, group_step in group_items
                        ]
                        parallel_results = []
                        for (order, group_step), future in zip(group_items, futures, strict=False):
                            try:
                                parallel_results.append(future.result())
                            except RoleExecutionError as exc:
                                run_controls_for_signal(
                                    "role_timeout" if "timeout" in str(exc).lower() else "step_failed",
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
                        finish_result = commit_step_result(result)
                        if finish_result is not None:
                            return finish_result
                    self.repository.append_event(
                        run_id,
                        "parallel_group_finished",
                        {
                            "iter": iter_id,
                            "parallel_group": parallel_group,
                            "step_orders": [order for order, _step in group_items],
                            "step_ids": [_step["id"] for _order, _step in group_items],
                        },
                    )

                if current_gatekeeper_result and not bool(current_gatekeeper_result.get("passed")):
                    run_controls_for_signal(
                        "gatekeeper_rejected",
                        {
                            "reason": "GateKeeper rejected the current evidence.",
                            "evidence_refs": list(current_gatekeeper_result.get("evidence_refs") or []),
                            "gatekeeper_result": current_gatekeeper_result,
                        },
                        state_snapshot(),
                    )
                if str(stagnation.get("stagnation_mode", "none") or "none") != "none":
                    run_controls_for_signal(
                        "no_evidence_progress",
                        {
                            "reason": f"Stagnation mode is {stagnation.get('stagnation_mode')}.",
                            "evidence_refs": list((current_gatekeeper_result or {}).get("evidence_refs") or []),
                        },
                        state_snapshot(),
                    )

                (
                    previous_outputs_by_step,
                    previous_outputs_by_role,
                    previous_outputs_by_archetype,
                    previous_handoffs_by_step,
                    previous_handoffs_by_role,
                    _previous_handoffs_by_archetype,
                    previous_iteration_summary,
                ) = self._checkpoint_workflow_iteration_state(
                    layout=layout,
                    iter_id=iter_id,
                    step_results=step_results,
                    current_outputs_by_step=current_outputs_by_step,
                    current_outputs_by_role=current_outputs_by_role,
                    current_outputs_by_archetype=current_outputs_by_archetype,
                    current_session_refs_by_step=current_session_refs_by_step,
                    stagnation=stagnation,
                    previous_composite=previous_composite,
                    run_id=run_id,
                )
                previous_session_refs_by_step = dict(current_session_refs_by_step)
                last_step_results = step_results
                summary = self._build_workflow_summary(
                    run,
                    workflow,
                    compiled_spec,
                    iter_id,
                    step_results,
                    stagnation,
                    exhausted=False,
                    previous_composite=previous_composite,
                )
                self._write_summary(run_id, "running", summary)
                log_event(
                    logger,
                    logging.INFO,
                    "service.workflow.iteration.completed",
                    "Completed workflow iteration",
                    **self._run_log_context(
                        run,
                        iter=iter_id,
                        executed_step_count=len(step_results),
                        stagnation_mode=stagnation.get("stagnation_mode", "none"),
                        gatekeeper_passed=bool(
                            current_gatekeeper_result and current_gatekeeper_result.get("passed")
                        ),
                        guide_used=current_guide_result is not None,
                    ),
                )
                if iteration_interval_seconds > 0 and (
                    run["max_iters"] == 0 or iter_id < run["max_iters"] - 1
                ):
                    self._pause_between_iterations(run_id, iteration_interval_seconds, iter_id)

            summary = self._build_workflow_summary(
                run,
                workflow,
                compiled_spec,
                last_iter_id,
                last_step_results,
                stagnation,
                exhausted=True,
                previous_composite=None,
            )
            return self._handle_workflow_exhaustion(
                run_id,
                run,
                run_dir,
                completion_mode=completion_mode,
                last_iter_id=last_iter_id,
                summary=summary,
            )
        except (StopRequested, ExecutionStopped):
            return self._handle_workflow_stop(run_id, run, run_dir)
        except RoleExecutionError as exc:
            return self._handle_workflow_role_execution_error(run_id, run, run_dir, exc)
        except WorkspaceSafetyError as exc:
            return self._handle_workflow_workspace_safety_error(run_id, run, run_dir, exc)
        except Exception as exc:
            return self._handle_workflow_unexpected_error(run_id, run, run_dir, exc)
        finally:
            self._cleanup_run_execution(run_id, run, phase="workflow")
