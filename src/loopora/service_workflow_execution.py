from __future__ import annotations

import itertools
import logging
import os
import time
from pathlib import Path

from loopora.diagnostics import get_logger, log_event
from loopora.executor import ExecutionStopped
from loopora.recovery import RetryConfig
from loopora.run_artifacts import INITIAL_STAGNATION_STATE
from loopora.service_types import LooporaError, RoleExecutionError, StopRequested, WorkspaceSafetyError, normalize_completion_mode
from loopora.service_workflow_failure_handling import ServiceWorkflowFailureHandlingMixin
from loopora.service_workflow_iteration_state import ServiceWorkflowIterationStateMixin
from loopora.utils import read_json

logger = get_logger(__name__)


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

                for step_order, step in enumerate(workflow_steps):
                    role = role_by_id[step["role_id"]]
                    runtime_role = self._runtime_role_key(role)
                    if role["archetype"] == "guide" and stagnation.get("stagnation_mode", "none") == "none":
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
                        continue

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
                        current_outputs_by_step=current_outputs_by_step,
                        current_outputs_by_role=current_outputs_by_role,
                        current_outputs_by_archetype=current_outputs_by_archetype,
                        current_handoffs=current_handoffs,
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
                        inspector_output=current_outputs_by_archetype.get("inspector"),
                    )
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
                    if isinstance(session_ref, dict) and session_ref:
                        current_session_refs_by_step[step["id"]] = dict(session_ref)
                    step_duration_ms = int((time.perf_counter() - step_started_at) * 1000)
                    step_results.append(
                        self._build_workflow_step_result_entry(
                            step=step,
                            step_order=step_order,
                            role=role,
                            runtime_role=runtime_role,
                            execution_settings=execution_settings,
                            normalized_output=normalized_output,
                            handoff=handoff,
                            context_packet=context_packet,
                        )
                    )
                    self._log_workflow_step_completion(
                        run=run,
                        iter_id=iter_id,
                        step=step,
                        runtime_role=runtime_role,
                        role=role,
                        duration_ms=step_duration_ms,
                        normalized_output=normalized_output,
                    )

                    if role["archetype"] in {"builder", "inspector"}:
                        self._enforce_workspace_safety(run, run_dir, iter_id, role=runtime_role)

                    if role["archetype"] == "gatekeeper":
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
                            and step.get("on_pass") == "finish_run"
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
