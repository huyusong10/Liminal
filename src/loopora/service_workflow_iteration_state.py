from __future__ import annotations

import logging
from pathlib import Path

from loopora.context_flow import build_step_evidence_entry, build_step_handoff
from loopora.diagnostics import get_logger, log_event
from loopora.evidence_coverage import write_evidence_coverage_projection
from loopora.run_artifacts import append_jsonl_with_mirrors, write_json_with_mirrors
from loopora.stagnation import update_stagnation
from loopora.utils import append_jsonl, utc_now

logger = get_logger(__name__)


class ServiceWorkflowIterationStateMixin:
    def _checkpoint_workflow_iteration_state(
        self,
        *,
        layout,
        iter_id: int,
        step_results: list[dict],
        current_outputs_by_step: dict[str, dict],
        current_outputs_by_role: dict[str, dict],
        current_outputs_by_archetype: dict[str, dict],
        current_session_refs_by_step: dict[str, dict],
        stagnation: dict,
        previous_composite: float | None,
        run_id: str,
    ) -> tuple[dict[str, dict], dict[str, dict], dict[str, dict], dict[str, dict], dict[str, dict], dict[str, dict], dict | None]:
        previous_outputs_by_step = dict(current_outputs_by_step)
        previous_outputs_by_role = dict(current_outputs_by_role)
        previous_outputs_by_archetype = dict(current_outputs_by_archetype)
        previous_handoffs_by_step = {item["step"]["id"]: item["handoff"] for item in step_results}
        previous_handoffs_by_role = {item["role"]["id"]: item["handoff"] for item in step_results}
        previous_handoffs_by_archetype = {item["role"]["archetype"]: item["handoff"] for item in step_results}
        append_jsonl(
            layout.legacy_iterations_path,
            self._build_workflow_iteration_entry(
                iter_id,
                step_results,
                stagnation,
                previous_composite=previous_composite,
            ),
        )
        previous_iteration_summary = self._persist_iteration_context(
            layout=layout,
            run_id=run_id,
            iter_id=iter_id,
            step_results=step_results,
            stagnation=stagnation,
            previous_composite=previous_composite,
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
        *,
        layout,
        stagnation: dict,
        normalized_output: dict,
        iter_id: int,
        previous_composite: float | None,
        run: dict,
        run_id: str,
    ) -> dict:
        stagnation = update_stagnation(
            stagnation,
            normalized_output["composite_score"],
            iter_id,
            delta_threshold=run["delta_threshold"],
            trigger_window=run["trigger_window"],
            regression_window=run["regression_window"],
        )
        write_json_with_mirrors(
            layout.timeline_stagnation_path,
            stagnation,
            mirror_paths=[layout.run_dir / "stagnation.json"],
        )
        append_jsonl_with_mirrors(
            layout.timeline_metrics_path,
            {
                "iter": iter_id,
                "timestamp": utc_now(),
                "composite": normalized_output["composite_score"],
                "score_delta": round(normalized_output["composite_score"] - previous_composite, 6)
                if previous_composite is not None
                else None,
                "passed": normalized_output["passed"],
                "metric_scores": normalized_output.get("metric_scores", {}),
                "failed_check_ids": normalized_output.get("failed_check_ids", []),
                "failed_check_titles": normalized_output.get("failed_check_titles", []),
                "evidence_refs": normalized_output.get("evidence_refs", []),
                "evidence_gate_status": normalized_output.get("evidence_gate_status", ""),
                "stagnation_mode": stagnation["stagnation_mode"],
            },
            mirror_paths=[layout.legacy_metrics_path],
        )
        self.repository.update_run(run_id, last_verdict=normalized_output)
        return stagnation

    def _write_workflow_step_result(
        self,
        *,
        run_id: str,
        layout,
        iter_id: int,
        step: dict,
        step_order: int,
        role: dict,
        runtime_role: str,
        normalized_output: dict,
    ) -> dict:
        handoff = build_step_handoff(
            layout=layout,
            iter_id=iter_id,
            step=step,
            step_order=step_order,
            role=role,
            runtime_role=runtime_role,
            output=normalized_output,
        )
        evidence_entry = build_step_evidence_entry(
            layout=layout,
            iter_id=iter_id,
            step=step,
            step_order=step_order,
            role=role,
            runtime_role=runtime_role,
            output=normalized_output,
            handoff=handoff,
        )
        handoff["evidence_refs"] = [evidence_entry["id"]]
        append_jsonl_with_mirrors(layout.evidence_ledger_path, evidence_entry)
        coverage_projection = write_evidence_coverage_projection(layout)
        self._write_step_outputs(
            layout,
            iter_id,
            step,
            step_order,
            role,
            runtime_role,
            normalized_output,
            handoff,
        )
        self.append_run_event(
            run_id,
            "step_handoff_written",
            {
                "iter": iter_id,
                "step_id": step["id"],
                "step_order": step_order,
                "role_name": role["name"],
                "archetype": role["archetype"],
                "handoff_path": layout.relative(layout.step_handoff_path(iter_id, step_order, step["id"])),
                "evidence_ledger_path": layout.relative(layout.evidence_ledger_path),
                "evidence_coverage_path": coverage_projection.get("coverage_path", ""),
                "evidence_refs": handoff["evidence_refs"],
                "status": handoff["status"],
                "summary": handoff["summary"],
                "blocking_count": len(handoff["blocking_items"]),
            },
            role=runtime_role,
        )
        return handoff

    def _build_workflow_step_result_entry(
        self,
        *,
        step: dict,
        step_order: int,
        role: dict,
        runtime_role: str,
        execution_settings: dict,
        normalized_output: dict,
        handoff: dict,
        context_packet: dict,
    ) -> dict:
        return {
            "step": step,
            "step_order": step_order,
            "role": role,
            "runtime_role": runtime_role,
            "resolved_model": execution_settings["model"],
            "resolved_executor_kind": execution_settings["executor_kind"],
            "output": normalized_output,
            "handoff": handoff,
            "context_packet": context_packet,
        }

    def _log_workflow_step_completion(
        self,
        *,
        run: dict,
        iter_id: int,
        step: dict,
        runtime_role: str,
        role: dict,
        duration_ms: int,
        normalized_output: dict,
    ) -> None:
        log_event(
            logger,
            logging.INFO,
            "service.workflow.step.completed",
            "Completed workflow step",
            **self._run_log_context(
                run,
                iter=iter_id,
                step_id=step["id"],
                role=runtime_role,
                archetype=role["archetype"],
                duration_ms=duration_ms,
                passed=normalized_output.get("passed"),
                composite_score=normalized_output.get("composite_score"),
            ),
        )

    def _finish_workflow_gatekeeper_success(
        self,
        *,
        run_id: str,
        run: dict,
        run_dir: Path,
        workflow: dict,
        compiled_spec: dict,
        iter_id: int,
        step: dict,
        runtime_role: str,
        normalized_output: dict,
        stagnation: dict,
        previous_composite: float | None,
        layout,
        step_results: list[dict],
        current_outputs_by_step: dict[str, dict],
        current_outputs_by_role: dict[str, dict],
        current_outputs_by_archetype: dict[str, dict],
        current_session_refs_by_step: dict[str, dict],
    ) -> dict:
        self._checkpoint_workflow_iteration_state(
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
        finished = self._finalize_terminal_run(
            run_id,
            run_dir,
            status="succeeded",
            summary=summary,
            last_verdict=normalized_output,
            final_reason="gatekeeper_passed",
            hydrate=True,
        )
        self.append_run_event(run_id, "run_finished", {"status": "succeeded", "iter": iter_id})
        log_event(
            logger,
            logging.INFO,
            "service.run.execution.finished",
            "Workflow run finished successfully",
            **self._run_log_context(
                run,
                status="succeeded",
                iter=iter_id,
                reason="gatekeeper_passed",
                step_id=step["id"],
                role=runtime_role,
            ),
        )
        return finished
