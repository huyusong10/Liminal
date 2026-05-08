from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path

from loopora.context_flow import StepEvidenceEntryRequest, StepResultContext, build_step_evidence_entry, build_step_handoff
from loopora.diagnostics import get_logger, log_event
from loopora.evidence_coverage import write_evidence_coverage_projection
from loopora.evidence_manifest import write_evidence_manifest_projection
from loopora.run_artifacts import append_jsonl_with_mirrors, write_json_with_mirrors
from loopora.service_run_finalization import TerminalRunFinalizationRequest
from loopora.service_workflow_support import IterationContextPersistRequest, StepOutputsWriteRequest, WorkflowSummaryRequest
from loopora.stagnation import StagnationUpdateRequest, update_stagnation
from loopora.utils import append_jsonl, read_json, utc_now

logger = get_logger(__name__)


@dataclass(frozen=True)
class WorkflowIterationCheckpointRequest:
    layout: object
    iter_id: int
    step_results: list[dict]
    current_outputs_by_step: dict[str, dict]
    current_outputs_by_role: dict[str, dict]
    current_outputs_by_archetype: dict[str, dict]
    current_session_refs_by_step: dict[str, dict]
    stagnation: dict
    previous_composite: float | None
    run_id: str


@dataclass(frozen=True)
class GatekeeperIterationRecordRequest:
    layout: object
    stagnation: dict
    normalized_output: dict
    iter_id: int
    previous_composite: float | None
    run: dict
    run_id: str


@dataclass(frozen=True)
class WorkflowStepWriteRequest:
    run_id: str
    layout: object
    iter_id: int
    step: dict
    step_order: int
    role: dict
    runtime_role: str
    normalized_output: dict


@dataclass(frozen=True)
class WorkflowStepResultEntryRequest:
    step: dict
    step_order: int
    role: dict
    runtime_role: str
    execution_settings: dict
    normalized_output: dict
    handoff: dict
    context_packet: dict


@dataclass(frozen=True)
class WorkflowStepCompletionLogRequest:
    run: dict
    iter_id: int
    step: dict
    runtime_role: str
    role: dict
    duration_ms: int
    normalized_output: dict


@dataclass(frozen=True)
class WorkflowGatekeeperSuccessRequest:
    run_id: str
    run: dict
    run_dir: Path
    workflow: dict
    compiled_spec: dict
    iter_id: int
    step: dict
    runtime_role: str
    normalized_output: dict
    stagnation: dict
    previous_composite: float | None
    layout: object
    step_results: list[dict]
    current_outputs_by_step: dict[str, dict]
    current_outputs_by_role: dict[str, dict]
    current_outputs_by_archetype: dict[str, dict]
    current_session_refs_by_step: dict[str, dict]


class ServiceWorkflowIterationStateMixin:
    def _checkpoint_workflow_iteration_state(
        self,
        request: WorkflowIterationCheckpointRequest,
    ) -> tuple[dict[str, dict], dict[str, dict], dict[str, dict], dict[str, dict], dict[str, dict], dict[str, dict], dict | None]:
        previous_outputs_by_step = dict(request.current_outputs_by_step)
        previous_outputs_by_role = dict(request.current_outputs_by_role)
        previous_outputs_by_archetype = dict(request.current_outputs_by_archetype)
        previous_handoffs_by_step = {item["step"]["id"]: item["handoff"] for item in request.step_results}
        previous_handoffs_by_role = {item["role"]["id"]: item["handoff"] for item in request.step_results}
        previous_handoffs_by_archetype = {item["role"]["archetype"]: item["handoff"] for item in request.step_results}
        append_jsonl(
            request.layout.legacy_iterations_path,
            self._build_workflow_iteration_entry(
                request.iter_id,
                request.step_results,
                request.stagnation,
                previous_composite=request.previous_composite,
            ),
        )
        previous_iteration_summary = self._persist_iteration_context(
            IterationContextPersistRequest(
                layout=request.layout,
                run_id=request.run_id,
                iter_id=request.iter_id,
                step_results=request.step_results,
                stagnation=request.stagnation,
                previous_composite=request.previous_composite,
            )
        )
        return (
            previous_outputs_by_step,
            previous_outputs_by_role,
            previous_outputs_by_archetype,
            previous_handoffs_by_step,
            previous_handoffs_by_role,
            previous_handoffs_by_archetype,
            previous_iteration_summary,
        )

    def _record_gatekeeper_iteration_result(
        self,
        request: GatekeeperIterationRecordRequest,
    ) -> dict:
        stagnation = update_stagnation(
            StagnationUpdateRequest(
                stagnation=request.stagnation,
                composite=request.normalized_output["composite_score"],
                current_iter=request.iter_id,
                delta_threshold=request.run["delta_threshold"],
                trigger_window=request.run["trigger_window"],
                regression_window=request.run["regression_window"],
            )
        )
        stagnation = self._update_evidence_progress_stagnation(request, stagnation)
        write_json_with_mirrors(
            request.layout.timeline_stagnation_path,
            stagnation,
            mirror_paths=[request.layout.run_dir / "stagnation.json"],
        )
        append_jsonl_with_mirrors(
            request.layout.timeline_metrics_path,
            {
                "iter": request.iter_id,
                "timestamp": utc_now(),
                "composite": request.normalized_output["composite_score"],
                "score_delta": round(
                    request.normalized_output["composite_score"] - request.previous_composite,
                    6,
                )
                if request.previous_composite is not None
                else None,
                "passed": request.normalized_output["passed"],
                "metric_scores": request.normalized_output.get("metric_scores", {}),
                "failed_check_ids": request.normalized_output.get("failed_check_ids", []),
                "failed_check_titles": request.normalized_output.get("failed_check_titles", []),
                "evidence_refs": request.normalized_output.get("evidence_refs", []),
                "evidence_gate_status": request.normalized_output.get("evidence_gate_status", ""),
                "stagnation_mode": stagnation["stagnation_mode"],
                "evidence_progress_mode": stagnation.get("evidence_progress_mode", "none"),
                "covered_check_count": stagnation.get("latest_covered_check_count", 0),
                "missing_check_count": stagnation.get("latest_missing_check_count", 0),
            },
            mirror_paths=[request.layout.legacy_metrics_path],
        )
        self.repository.update_run(request.run_id, last_verdict=request.normalized_output)
        return stagnation

    @staticmethod
    def _update_evidence_progress_stagnation(
        request: GatekeeperIterationRecordRequest,
        stagnation: dict,
    ) -> dict:
        try:
            coverage = read_json(request.layout.evidence_coverage_path)
        except (OSError, UnicodeError, ValueError):
            coverage = {}
        if not isinstance(coverage, dict):
            coverage = {}
        covered_checks = int(coverage.get("covered_check_count") or 0)
        missing_checks = int(coverage.get("missing_check_count") or 0)
        recent_counts = list(stagnation.get("recent_covered_check_counts", []))
        no_progress = bool(recent_counts) and covered_checks <= int(recent_counts[-1] or 0)
        consecutive_no_progress = int(stagnation.get("consecutive_no_required_coverage_delta") or 0)
        consecutive_no_progress = consecutive_no_progress + 1 if no_progress and missing_checks > 0 else 0
        evidence_progress_mode = "stalled" if missing_checks > 0 and consecutive_no_progress >= int(request.run.get("trigger_window") or 1) else "none"
        return {
            **stagnation,
            "recent_covered_check_counts": [*recent_counts, covered_checks][-20:],
            "latest_covered_check_count": covered_checks,
            "latest_missing_check_count": missing_checks,
            "consecutive_no_required_coverage_delta": consecutive_no_progress,
            "evidence_progress_mode": evidence_progress_mode,
        }

    def _write_workflow_step_result(
        self,
        request: WorkflowStepWriteRequest,
    ) -> dict:
        step_result = StepResultContext(
            layout=request.layout,
            iter_id=request.iter_id,
            step=request.step,
            step_order=request.step_order,
            role=request.role,
            runtime_role=request.runtime_role,
            output=request.normalized_output,
        )
        handoff = build_step_handoff(step_result)
        evidence_entry = build_step_evidence_entry(StepEvidenceEntryRequest(result=step_result, handoff=handoff))
        handoff["evidence_refs"] = [evidence_entry["id"]]
        self._write_step_outputs(
            StepOutputsWriteRequest(
                layout=request.layout,
                iter_id=request.iter_id,
                step=request.step,
                step_order=request.step_order,
                role=request.role,
                runtime_role=request.runtime_role,
                output=request.normalized_output,
                handoff=handoff,
            )
        )
        append_jsonl_with_mirrors(request.layout.evidence_ledger_path, evidence_entry)
        coverage_projection = write_evidence_coverage_projection(request.layout)
        manifest_projection = write_evidence_manifest_projection(
            request.layout,
            coverage_projection=coverage_projection,
        )
        self.append_run_event(
            request.run_id,
            "step_handoff_written",
            {
                "iter": request.iter_id,
                "step_id": request.step["id"],
                "step_order": request.step_order,
                "role_name": request.role["name"],
                "archetype": request.role["archetype"],
                "handoff_path": request.layout.relative(request.layout.step_handoff_path(request.iter_id, request.step_order, request.step["id"])),
                "evidence_ledger_path": request.layout.relative(request.layout.evidence_ledger_path),
                "evidence_coverage_path": coverage_projection.get("coverage_path", ""),
                "evidence_manifest_path": manifest_projection.get("manifest_path", ""),
                "evidence_refs": handoff["evidence_refs"],
                "status": handoff["status"],
                "summary": handoff["summary"],
                "blocking_count": len(handoff["blocking_items"]),
            },
            role=request.runtime_role,
        )
        return handoff

    def _build_workflow_step_result_entry(
        self,
        request: WorkflowStepResultEntryRequest,
    ) -> dict:
        return {
            "step": request.step,
            "step_order": request.step_order,
            "role": request.role,
            "runtime_role": request.runtime_role,
            "resolved_model": request.execution_settings["model"],
            "resolved_executor_kind": request.execution_settings["executor_kind"],
            "output": request.normalized_output,
            "handoff": request.handoff,
            "context_packet": request.context_packet,
        }

    def _log_workflow_step_completion(
        self,
        request: WorkflowStepCompletionLogRequest,
    ) -> None:
        log_event(
            logger,
            logging.INFO,
            "service.workflow.step.completed",
            "Completed workflow step",
            **self._run_log_context(
                request.run,
                iter=request.iter_id,
                step_id=request.step["id"],
                role=request.runtime_role,
                archetype=request.role["archetype"],
                duration_ms=request.duration_ms,
                passed=request.normalized_output.get("passed"),
                composite_score=request.normalized_output.get("composite_score"),
            ),
        )

    def _finish_workflow_gatekeeper_success(
        self,
        request: WorkflowGatekeeperSuccessRequest,
    ) -> dict:
        self._checkpoint_workflow_iteration_state(
            WorkflowIterationCheckpointRequest(
                layout=request.layout,
                iter_id=request.iter_id,
                step_results=request.step_results,
                current_outputs_by_step=request.current_outputs_by_step,
                current_outputs_by_role=request.current_outputs_by_role,
                current_outputs_by_archetype=request.current_outputs_by_archetype,
                current_session_refs_by_step=request.current_session_refs_by_step,
                stagnation=request.stagnation,
                previous_composite=request.previous_composite,
                run_id=request.run_id,
            )
        )
        summary = self._build_workflow_summary(
            WorkflowSummaryRequest(
                run=request.run,
                workflow=request.workflow,
                compiled_spec=request.compiled_spec,
                iter_id=request.iter_id,
                step_results=request.step_results,
                stagnation=request.stagnation,
                exhausted=False,
                previous_composite=request.previous_composite,
            )
        )
        finished = self._finalize_terminal_run(
            TerminalRunFinalizationRequest(
                run_id=request.run_id,
                run_dir=request.run_dir,
                status="succeeded",
                summary=summary,
                last_verdict=request.normalized_output,
                final_reason="gatekeeper_passed",
                hydrate=True,
            )
        )
        self.append_run_event(request.run_id, "run_finished", {"status": "succeeded", "iter": request.iter_id})
        log_event(
            logger,
            logging.INFO,
            "service.run.execution.finished",
            "Workflow run finished successfully",
            **self._run_log_context(
                request.run,
                status="succeeded",
                iter=request.iter_id,
                reason="gatekeeper_passed",
                step_id=request.step["id"],
                role=request.runtime_role,
            ),
        )
        return finished
