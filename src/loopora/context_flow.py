from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from loopora.evidence_gate import concrete_evidence_claim_count, has_measured_gate_evidence
from loopora.specs import resolve_role_note

from loopora.run_artifacts import RunArtifactLayout, artifact_ref
from loopora.utils import utc_now


@dataclass(frozen=True)
class RunContractSnapshotRequest:
    run: dict
    compiled_spec: dict
    workflow: dict
    prompt_files: dict[str, str]
    workspace_baseline: dict
    layout: RunArtifactLayout


@dataclass(frozen=True)
class StepContextPacketRequest:
    run_contract: dict
    layout: RunArtifactLayout
    iter_id: int
    step: dict
    step_order: int
    role: dict
    execution_settings: dict[str, str]
    immediate_previous_step: dict | None
    completed_steps_this_iteration: list[dict]
    previous_iteration_same_step: dict | None
    previous_iteration_same_role: dict | None
    previous_iteration_summary: dict | None
    previous_composite: float | None
    stagnation_mode: str
    evidence_progress_mode: str = "none"
    covered_check_count: int = 0
    missing_check_count: int = 0
    consecutive_no_required_coverage_delta: int = 0
    evidence_items: list[dict] | None = None
    evidence_known_ids: list[str] | None = None
    evidence_manifest_summary: dict | None = None
    evidence_manifest_claims: list[dict] | None = None


@dataclass(frozen=True)
class StepResultContext:
    layout: RunArtifactLayout
    iter_id: int
    step: dict
    step_order: int
    role: dict
    runtime_role: str
    output: dict


@dataclass(frozen=True)
class StepEvidenceEntryRequest:
    result: StepResultContext
    handoff: dict


@dataclass(frozen=True)
class IterationSummaryContext:
    layout: RunArtifactLayout
    iter_id: int
    step_results: list[dict]
    stagnation: dict
    previous_composite: float | None
    timestamp: str


ARTIFACT_REF_SCHEMA = {
    "type": "object",
    "required": ["kind", "label", "relative_path", "workspace_path", "absolute_path"],
    "properties": {
        "kind": {"type": "string"},
        "label": {"type": "string"},
        "relative_path": {"type": "string"},
        "workspace_path": {"type": "string"},
        "absolute_path": {"type": "string"},
    },
    "additionalProperties": False,
}

EVIDENCE_COVERAGE_RESULT_SCHEMA = {
    "type": "object",
    "required": ["target_id", "status", "evidence_refs", "note"],
    "properties": {
        "target_id": {"type": "string"},
        "status": {"type": "string"},
        "evidence_refs": {"type": "array", "items": {"type": "string"}},
        "note": {"type": "string"},
    },
    "additionalProperties": False,
}

STEP_HANDOFF_SCHEMA = {
    "type": "object",
    "required": [
        "source",
        "status",
        "summary",
        "blocking_items",
        "recommended_next_action",
        "evidence_refs",
        "artifact_refs",
    ],
    "properties": {
        "source": {
            "type": "object",
            "required": ["iter", "step_id", "step_order", "role_id", "role_name", "runtime_role", "archetype"],
            "properties": {
                "iter": {"type": "integer"},
                "step_id": {"type": "string"},
                "step_order": {"type": "integer"},
                "role_id": {"type": "string"},
                "role_name": {"type": "string"},
                "runtime_role": {"type": "string"},
                "archetype": {"type": "string"},
            },
            "additionalProperties": False,
        },
        "status": {"type": "string"},
        "summary": {"type": "string"},
        "blocking_items": {"type": "array", "items": {"type": "string"}},
        "recommended_next_action": {"type": "string"},
        "evidence_refs": {"type": "array", "items": {"type": "string"}},
        "artifact_refs": {"type": "array", "items": ARTIFACT_REF_SCHEMA},
    },
    "additionalProperties": False,
}

EVIDENCE_ITEM_SCHEMA = {
    "type": "object",
    "required": [
        "id",
        "timestamp",
        "iter",
        "step_id",
        "step_order",
        "role_id",
        "role_name",
        "runtime_role",
        "archetype",
        "evidence_kind",
        "source",
        "method",
        "claim",
        "result",
        "verifies",
        "related_evidence_ids",
        "coverage_results",
        "measured_evidence",
        "concrete_evidence_claim_count",
        "residual_risk",
        "artifact_refs",
    ],
    "properties": {
        "id": {"type": "string"},
        "timestamp": {"type": "string"},
        "iter": {"type": "integer"},
        "step_id": {"type": "string"},
        "step_order": {"type": "integer"},
        "role_id": {"type": "string"},
        "role_name": {"type": "string"},
        "runtime_role": {"type": "string"},
        "archetype": {"type": "string"},
        "evidence_kind": {"type": "string"},
        "source": {"type": "string"},
        "method": {"type": "string"},
        "claim": {"type": "string"},
        "result": {"type": "string"},
        "verifies": {"type": "array", "items": {"type": "string"}},
        "related_evidence_ids": {"type": "array", "items": {"type": "string"}},
        "coverage_results": {"type": "array", "items": EVIDENCE_COVERAGE_RESULT_SCHEMA},
        "measured_evidence": {"type": "boolean"},
        "concrete_evidence_claim_count": {"type": "integer"},
        "residual_risk": {"type": "string"},
        "artifact_refs": {"type": "array", "items": ARTIFACT_REF_SCHEMA},
    },
    "additionalProperties": False,
}

EVIDENCE_MANIFEST_SUMMARY_SCHEMA = {
    "type": "object",
    "required": [
        "claim_count",
        "direct_proof_claim_count",
        "workspace_artifact_claim_count",
        "run_artifact_claim_count",
        "ledger_only_claim_count",
        "unverified_claim_count",
        "problem_count",
    ],
    "properties": {
        "claim_count": {"type": "integer"},
        "direct_proof_claim_count": {"type": "integer"},
        "workspace_artifact_claim_count": {"type": "integer"},
        "run_artifact_claim_count": {"type": "integer"},
        "ledger_only_claim_count": {"type": "integer"},
        "unverified_claim_count": {"type": "integer"},
        "problem_count": {"type": "integer"},
    },
    "additionalProperties": False,
}

EVIDENCE_MANIFEST_CLAIM_SCHEMA = {
    "type": "object",
    "required": [
        "id",
        "verification_status",
        "measured_evidence",
        "concrete_evidence_claim_count",
        "artifact_count",
        "artifact_backed",
        "workspace_backed",
        "reproducible",
        "coverage_targets",
        "problem_codes",
    ],
    "properties": {
        "id": {"type": "string"},
        "verification_status": {"type": "string"},
        "measured_evidence": {"type": "boolean"},
        "concrete_evidence_claim_count": {"type": "integer"},
        "artifact_count": {"type": "integer"},
        "artifact_backed": {"type": "boolean"},
        "workspace_backed": {"type": "boolean"},
        "reproducible": {"type": "boolean"},
        "coverage_targets": {"type": "array", "items": {"type": "string"}},
        "problem_codes": {"type": "array", "items": {"type": "string"}},
    },
    "additionalProperties": False,
}

STEP_CONTEXT_PACKET_SCHEMA = {
    "type": "object",
    "required": ["contract", "iteration", "current_step", "upstream", "evidence", "artifacts"],
    "properties": {
        "contract": {
            "type": "object",
            "required": [
                "path",
                "goal",
                "constraints",
                "check_mode",
                "check_count",
                "completion_mode",
                "workflow_preset",
                "workflow_collaboration_intent",
                "coverage_targets",
                "success_surface",
                "fake_done_states",
                "evidence_preferences",
                "residual_risk",
            ],
            "properties": {
                "path": {"type": "string"},
                "goal": {"type": "string"},
                "constraints": {"type": "string"},
                "check_mode": {"type": "string"},
                "check_count": {"type": "integer"},
                "completion_mode": {"type": "string"},
                "workflow_preset": {"type": "string"},
                "workflow_collaboration_intent": {"type": "string"},
                "coverage_targets": {"type": "array", "items": {"type": "object"}},
                "success_surface": {"type": "array", "items": {"type": "string"}},
                "fake_done_states": {"type": "array", "items": {"type": "string"}},
                "evidence_preferences": {"type": "array", "items": {"type": "string"}},
                "residual_risk": {"type": "string"},
            },
            "additionalProperties": False,
        },
        "iteration": {
            "type": "object",
            "required": [
                "iter_index",
                "is_first_iteration",
                "previous_iteration_exists",
                "previous_composite",
                "stagnation_mode",
                "evidence_progress_mode",
                "covered_check_count",
                "missing_check_count",
                "consecutive_no_required_coverage_delta",
            ],
            "properties": {
                "iter_index": {"type": "integer"},
                "is_first_iteration": {"type": "boolean"},
                "previous_iteration_exists": {"type": "boolean"},
                "previous_composite": {"type": ["number", "null"]},
                "stagnation_mode": {"type": "string"},
                "evidence_progress_mode": {"type": "string"},
                "covered_check_count": {"type": "integer"},
                "missing_check_count": {"type": "integer"},
                "consecutive_no_required_coverage_delta": {"type": "integer"},
            },
            "additionalProperties": False,
        },
        "current_step": {
            "type": "object",
            "required": [
                "step_id",
                "step_order",
                "role_id",
                "role_name",
                "archetype",
                "model",
                "executor_kind",
                "executor_mode",
                "parallel_group",
                "inputs",
                "action_policy",
                "control",
            ],
            "properties": {
                "step_id": {"type": "string"},
                "step_order": {"type": "integer"},
                "role_id": {"type": "string"},
                "role_name": {"type": "string"},
                "archetype": {"type": "string"},
                "model": {"type": "string"},
                "executor_kind": {"type": "string"},
                "executor_mode": {"type": "string"},
                "parallel_group": {"type": "string"},
                "inputs": {"type": "object"},
                "action_policy": {
                    "type": "object",
                    "required": ["workspace", "can_block", "can_finish_run"],
                    "properties": {
                        "workspace": {"type": "string"},
                        "can_block": {"type": "boolean"},
                        "can_finish_run": {"type": "boolean"},
                    },
                    "additionalProperties": False,
                },
                "control": {"type": "object"},
            },
            "additionalProperties": False,
        },
        "upstream": {
            "type": "object",
            "required": [
                "immediate_previous_step",
                "completed_steps_this_iteration",
                "previous_iteration_same_step",
                "previous_iteration_same_role",
                "previous_iteration_summary",
            ],
            "properties": {
                "immediate_previous_step": {"anyOf": [STEP_HANDOFF_SCHEMA, {"type": "null"}]},
                "completed_steps_this_iteration": {"type": "array", "items": STEP_HANDOFF_SCHEMA},
                "previous_iteration_same_step": {"anyOf": [STEP_HANDOFF_SCHEMA, {"type": "null"}]},
                "previous_iteration_same_role": {"anyOf": [STEP_HANDOFF_SCHEMA, {"type": "null"}]},
                "previous_iteration_summary": {"type": ["object", "null"]},
            },
            "additionalProperties": False,
        },
        "evidence": {
            "type": "object",
            "required": [
                "ledger_path",
                "manifest_path",
                "coverage_path",
                "items",
                "known_ids",
                "manifest_summary",
                "manifest_claims",
            ],
            "properties": {
                "ledger_path": {"type": "string"},
                "manifest_path": {"type": "string"},
                "coverage_path": {"type": "string"},
                "items": {"type": "array", "items": EVIDENCE_ITEM_SCHEMA},
                "known_ids": {"type": "array", "items": {"type": "string"}},
                "manifest_summary": EVIDENCE_MANIFEST_SUMMARY_SCHEMA,
                "manifest_claims": {"type": "array", "items": EVIDENCE_MANIFEST_CLAIM_SCHEMA},
            },
            "additionalProperties": False,
        },
        "artifacts": {"type": "array", "items": ARTIFACT_REF_SCHEMA},
    },
    "additionalProperties": False,
}

ITERATION_SUMMARY_SCHEMA = {
    "type": "object",
    "required": ["phase", "iter", "timestamp", "workflow", "step_handoffs", "score", "stagnation", "latest_refs"],
    "properties": {
        "phase": {"type": "string"},
        "iter": {"type": "integer"},
        "timestamp": {"type": "string"},
        "workflow": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "step_id",
                    "role_id",
                    "role_name",
                    "runtime_role",
                    "archetype",
                    "model",
                    "status",
                    "parallel_group",
                ],
                "properties": {
                    "step_id": {"type": "string"},
                    "role_id": {"type": "string"},
                    "role_name": {"type": "string"},
                    "runtime_role": {"type": "string"},
                    "archetype": {"type": "string"},
                    "model": {"type": "string"},
                    "status": {"type": "string"},
                    "parallel_group": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
        "step_handoffs": {"type": "array", "items": STEP_HANDOFF_SCHEMA},
        "score": {
            "type": "object",
            "required": ["composite", "delta", "passed"],
            "properties": {
                "composite": {"type": ["number", "null"]},
                "delta": {"type": ["number", "null"]},
                "passed": {"type": ["boolean", "null"]},
            },
            "additionalProperties": False,
        },
        "stagnation": {
            "type": "object",
            "required": [
                "mode",
                "evidence_progress_mode",
                "recent_composites",
                "recent_deltas",
                "consecutive_low_delta",
                "covered_check_count",
                "missing_check_count",
                "consecutive_no_required_coverage_delta",
            ],
            "properties": {
                "mode": {"type": "string"},
                "evidence_progress_mode": {"type": "string"},
                "recent_composites": {"type": "array", "items": {"type": "number"}},
                "recent_deltas": {"type": "array", "items": {"type": "number"}},
                "consecutive_low_delta": {"type": "integer"},
                "covered_check_count": {"type": "integer"},
                "missing_check_count": {"type": "integer"},
                "consecutive_no_required_coverage_delta": {"type": "integer"},
            },
            "additionalProperties": False,
        },
        "latest_refs": {
            "type": "object",
            "required": ["summary_path", "latest_gatekeeper", "latest_by_step", "latest_by_role", "latest_by_archetype"],
            "properties": {
                "summary_path": {"type": "string"},
                "latest_gatekeeper": {"type": ["string", "null"]},
                "latest_by_step": {"type": "object"},
                "latest_by_role": {"type": "object"},
                "latest_by_archetype": {"type": "object"},
            },
            "additionalProperties": False,
        },
    },
    "additionalProperties": False,
}

LATEST_STATE_SCHEMA = {
    "type": "object",
    "required": [
        "latest_iteration",
        "latest_by_step",
        "latest_by_role",
        "latest_by_archetype",
        "latest_gatekeeper",
        "latest_summary_path",
    ],
    "properties": {
        "latest_iteration": {"type": ["integer", "null"]},
        "latest_by_step": {"type": "object"},
        "latest_by_role": {"type": "object"},
        "latest_by_archetype": {"type": "object"},
        "latest_gatekeeper": {"type": ["string", "null"]},
        "latest_summary_path": {"type": "string"},
    },
    "additionalProperties": False,
}


def build_run_contract_snapshot(request: RunContractSnapshotRequest) -> dict:
    run = request.run
    layout = request.layout
    return {
        "run_id": run["id"],
        "loop_id": run.get("loop_id"),
        "workdir": str(run.get("workdir") or ""),
        "completion_mode": str(run.get("completion_mode") or "gatekeeper"),
        "max_iters": int(run.get("max_iters") or 0),
        "max_role_retries": int(run.get("max_role_retries") or 0),
        "delta_threshold": float(run.get("delta_threshold") or 0.0),
        "trigger_window": int(run.get("trigger_window") or 0),
        "regression_window": int(run.get("regression_window") or 0),
        "iteration_interval_seconds": float(run.get("iteration_interval_seconds") or 0.0),
        "executor": {
            "kind": str(run.get("executor_kind") or "codex"),
            "mode": str(run.get("executor_mode") or "preset"),
            "model": str(run.get("model") or ""),
            "reasoning_effort": str(run.get("reasoning_effort") or ""),
        },
        "compiled_spec": request.compiled_spec,
        "workflow": {
            "preset": str(request.workflow.get("preset") or "custom"),
            "collaboration_intent": str(request.workflow.get("collaboration_intent") or "").strip(),
            "roles": [
                {
                    "id": str(role.get("id") or ""),
                    "name": str(role.get("name") or ""),
                    "archetype": str(role.get("archetype") or ""),
                    "prompt_ref": str(role.get("prompt_ref") or ""),
                    "posture_notes": str(role.get("posture_notes") or "").strip(),
                }
                for role in request.workflow.get("roles", [])
            ],
            "steps": [
                {
                    "id": str(step.get("id") or ""),
                    "role_id": str(step.get("role_id") or ""),
                    "on_pass": str(step.get("on_pass") or ""),
                    "model": str(step.get("model") or ""),
                    "inherit_session": bool(step.get("inherit_session")),
                    "extra_cli_args": str(step.get("extra_cli_args") or ""),
                    "parallel_group": str(step.get("parallel_group") or ""),
                    "inputs": dict(step.get("inputs") or {}),
                    "action_policy": dict(step.get("action_policy") or {}),
                }
                for step in request.workflow.get("steps", [])
            ],
            "controls": list(request.workflow.get("controls") or []),
        },
        "prompt_refs": sorted(request.prompt_files.keys()),
        "workspace_baseline": {
            "file_count": int(request.workspace_baseline.get("file_count") or 0),
            "artifact": artifact_ref(layout, layout.workspace_baseline_path, kind="workspace", label="workspace-baseline"),
        },
        "artifacts": {
            "summary": artifact_ref(layout, layout.summary_path, kind="summary", label="summary"),
            "compiled_spec": artifact_ref(layout, layout.contract_compiled_spec_path, kind="contract", label="compiled-spec"),
            "workflow": artifact_ref(layout, layout.contract_workflow_path, kind="contract", label="workflow"),
            "run_contract": artifact_ref(layout, layout.run_contract_path, kind="contract", label="run-contract"),
            "latest_state": artifact_ref(layout, layout.latest_state_path, kind="state", label="latest-state"),
            "latest_iteration_summary": artifact_ref(
                layout,
                layout.latest_iteration_summary_path,
                kind="state",
                label="latest-iteration-summary",
            ),
            "timeline_events": artifact_ref(layout, layout.timeline_events_path, kind="timeline", label="timeline-events"),
            "timeline_iterations": artifact_ref(
                layout,
                layout.timeline_iterations_path,
                kind="timeline",
                label="timeline-iterations",
            ),
            "timeline_metrics": artifact_ref(layout, layout.timeline_metrics_path, kind="timeline", label="timeline-metrics"),
            "evidence_ledger": artifact_ref(layout, layout.evidence_ledger_path, kind="evidence", label="evidence-ledger"),
            "evidence_coverage": artifact_ref(layout, layout.evidence_coverage_path, kind="evidence", label="evidence-coverage"),
            "evidence_manifest": artifact_ref(layout, layout.evidence_manifest_path, kind="evidence", label="evidence-manifest"),
        },
    }


def build_step_context_packet(request: StepContextPacketRequest) -> dict:
    run_contract = request.run_contract
    layout = request.layout
    step = request.step
    role = request.role
    compiled_spec = run_contract.get("compiled_spec") or {}
    workflow_snapshot = run_contract.get("workflow") or {}
    return {
        "contract": {
            "path": layout.relative(layout.run_contract_path),
            "goal": str(compiled_spec.get("goal") or "").strip(),
            "constraints": str(compiled_spec.get("constraints") or "No explicit constraints were provided.").strip(),
            "check_mode": str(compiled_spec.get("check_mode") or "specified"),
            "check_count": len(compiled_spec.get("checks") or []),
            "completion_mode": str(run_contract.get("completion_mode") or "gatekeeper"),
            "workflow_preset": str(workflow_snapshot.get("preset") or "custom"),
            "workflow_collaboration_intent": str(workflow_snapshot.get("collaboration_intent") or "").strip(),
            "coverage_targets": list(compiled_spec.get("coverage_targets") or []),
            "success_surface": list(compiled_spec.get("success_surface") or []),
            "fake_done_states": list(compiled_spec.get("fake_done_states") or []),
            "evidence_preferences": list(compiled_spec.get("evidence_preferences") or []),
            "residual_risk": str(compiled_spec.get("residual_risk") or "").strip(),
        },
        "iteration": {
            "iter_index": int(request.iter_id),
            "is_first_iteration": request.iter_id == 0,
            "previous_iteration_exists": request.iter_id > 0,
            "previous_composite": request.previous_composite,
            "stagnation_mode": str(request.stagnation_mode or "none"),
            "evidence_progress_mode": str(request.evidence_progress_mode or "none"),
            "covered_check_count": _int_value(request.covered_check_count),
            "missing_check_count": _int_value(request.missing_check_count),
            "consecutive_no_required_coverage_delta": _int_value(request.consecutive_no_required_coverage_delta),
        },
        "current_step": {
            "step_id": str(step["id"]),
            "step_order": int(request.step_order),
            "role_id": str(role["id"]),
            "role_name": str(role["name"]),
            "archetype": str(role["archetype"]),
            "model": str(request.execution_settings.get("model") or ""),
            "executor_kind": str(request.execution_settings.get("executor_kind") or ""),
            "executor_mode": str(request.execution_settings.get("executor_mode") or ""),
            "parallel_group": str(step.get("parallel_group") or ""),
            "inputs": dict(step.get("inputs") or {}),
            "action_policy": dict(step.get("action_policy") or {}),
            "control": dict(step.get("control") or {}) if isinstance(step.get("control"), dict) else {},
        },
        "upstream": {
            "immediate_previous_step": request.immediate_previous_step,
            "completed_steps_this_iteration": list(request.completed_steps_this_iteration),
            "previous_iteration_same_step": request.previous_iteration_same_step,
            "previous_iteration_same_role": request.previous_iteration_same_role,
            "previous_iteration_summary": request.previous_iteration_summary,
        },
        "evidence": {
            "ledger_path": layout.relative(layout.evidence_ledger_path),
            "manifest_path": layout.relative(layout.evidence_manifest_path),
            "coverage_path": layout.relative(layout.evidence_coverage_path),
            "items": _normalize_evidence_items(request.evidence_items),
            "known_ids": list(request.evidence_known_ids or []),
            "manifest_summary": _normalize_manifest_summary(request.evidence_manifest_summary),
            "manifest_claims": _normalize_manifest_claims(request.evidence_manifest_claims),
        },
        "artifacts": [
            artifact_ref(layout, layout.run_contract_path, kind="contract", label="run-contract"),
            artifact_ref(layout, layout.latest_state_path, kind="state", label="latest-state"),
            artifact_ref(layout, layout.latest_iteration_summary_path, kind="state", label="latest-iteration-summary"),
            artifact_ref(layout, layout.timeline_events_path, kind="timeline", label="timeline-events"),
            artifact_ref(layout, layout.timeline_iterations_path, kind="timeline", label="timeline-iterations"),
            artifact_ref(layout, layout.timeline_metrics_path, kind="timeline", label="timeline-metrics"),
            artifact_ref(layout, layout.evidence_ledger_path, kind="evidence", label="evidence-ledger"),
            artifact_ref(layout, layout.evidence_coverage_path, kind="evidence", label="evidence-coverage"),
            artifact_ref(layout, layout.evidence_manifest_path, kind="evidence", label="evidence-manifest"),
        ],
    }


def build_step_handoff(result: StepResultContext) -> dict:
    layout = result.layout
    step = result.step
    role = result.role
    output = result.output
    summary = ""
    blocking_items: list[str] = []
    recommended_next_action = ""
    status = "completed"
    archetype = str(role["archetype"])

    if archetype == "builder":
        summary = _clean_text(output.get("summary") or output.get("attempted")) or "Builder completed its change pass."
        abandoned = _clean_text(output.get("abandoned"))
        if abandoned:
            blocking_items.append(abandoned)
        recommended_next_action = _clean_text(output.get("assumption")) or "Validate the visible change with inspection."
    elif archetype == "inspector":
        summary = _clean_text(output.get("tester_observations")) or "Inspector collected workspace evidence."
        blocking_items = _inspector_blockers(output)
        recommended_next_action = (
            "Address the failing checks with the strongest direct evidence." if blocking_items else "Pass the evidence bundle to GateKeeper for a verdict."
        )
        status = "blocked" if blocking_items else "completed"
    elif archetype == "gatekeeper":
        summary = _clean_text(output.get("decision_summary")) or "GateKeeper evaluated the current evidence."
        blocking_items = _gatekeeper_blockers(output)
        recommended_next_action = (
            _clean_text(output.get("feedback_to_builder") or output.get("feedback_to_generator")) or "Continue only after the blocking issues are resolved."
        )
        status = "passed" if bool(output.get("passed")) else "blocked"
    elif archetype == "guide":
        analysis = output.get("analysis") if isinstance(output.get("analysis"), dict) else {}
        summary = _clean_text(analysis.get("recommended_shift") or output.get("meta_note")) or "Guide proposed a direction shift."
        risk_note = _clean_text(analysis.get("risk_note"))
        if risk_note:
            blocking_items.append(risk_note)
        recommended_next_action = (
            _clean_text(output.get("seed_question") or analysis.get("recommended_shift")) or "Use the guidance as the next experiment seed."
        )
        status = "advisory"
    else:
        summary = _clean_text(output.get("summary") or output.get("handoff_note")) or "Custom role prepared a scoped handoff."
        blocking_items = [item for item in _string_list(output.get("blocking_items")) if item]
        if not blocking_items:
            blocking_items = [item for item in _string_list(output.get("risks")) if item]
        recommended_next_action = (
            _clean_text(output.get("recommended_next_action"))
            or _clean_text((_string_list(output.get("recommendations")) or [""])[0] or output.get("handoff_note"))
            or "Use this handoff in a Builder or Inspector step."
        )
        status = _clean_text(output.get("status")).lower() or "advisory"

    artifact_refs = [
        artifact_ref(
            layout,
            layout.step_output_raw_path(result.iter_id, result.step_order, step["id"]),
            kind="step",
            label="output-raw",
        ),
        artifact_ref(
            layout,
            layout.step_output_normalized_path(result.iter_id, result.step_order, step["id"]),
            kind="step",
            label="output-normalized",
        ),
        artifact_ref(
            layout,
            layout.step_metadata_path(result.iter_id, result.step_order, step["id"]),
            kind="step",
            label="metadata",
        ),
    ]
    artifact_refs.extend(_output_workspace_artifact_refs(layout, output))

    return {
        "source": {
            "iter": int(result.iter_id),
            "step_id": str(step["id"]),
            "step_order": int(result.step_order),
            "role_id": str(role["id"]),
            "role_name": str(role["name"]),
            "runtime_role": str(result.runtime_role),
            "archetype": archetype,
        },
        "status": status,
        "summary": summary,
        "blocking_items": blocking_items,
        "recommended_next_action": recommended_next_action,
        "evidence_refs": [],
        "artifact_refs": artifact_refs,
    }


def _output_workspace_artifact_refs(layout: RunArtifactLayout, output: dict) -> list[dict[str, str]]:
    fields = (
        ("changed_files", "changed-file"),
        ("generated_files", "generated-file"),
        ("proof_files", "proof-file"),
        ("proof_artifacts", "proof-artifact"),
        ("artifact_paths", "artifact"),
    )
    refs: list[dict[str, str]] = []
    seen: set[str] = set()
    for field_name, label_prefix in fields:
        for value in _string_list(output.get(field_name)):
            ref = _workspace_artifact_ref(layout, value, label_prefix=label_prefix)
            if not ref or ref["absolute_path"] in seen:
                continue
            refs.append(ref)
            seen.add(ref["absolute_path"])
    return refs[:20]


def _workspace_artifact_ref(layout: RunArtifactLayout, value: str, *, label_prefix: str) -> dict[str, str] | None:
    cleaned = str(value or "").strip()
    if not cleaned or "\x00" in cleaned:
        return None
    candidate = Path(cleaned)
    workdir = layout.workdir_path.resolve()
    try:
        resolved = candidate.resolve() if candidate.is_absolute() else (workdir / candidate).resolve()
    except (OSError, RuntimeError, ValueError):
        return None
    try:
        workspace_path = resolved.relative_to(workdir).as_posix()
    except ValueError:
        return None
    try:
        if not resolved.exists():
            return None
    except OSError:
        return None
    return {
        "kind": "workspace",
        "label": f"{label_prefix}:{workspace_path}",
        "relative_path": workspace_path,
        "workspace_path": workspace_path,
        "absolute_path": str(resolved),
    }


def evidence_entry_id(iter_id: int, step_order: int, step_id: str) -> str:
    cleaned_step = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in str(step_id))
    return f"ev_{int(iter_id):03d}_{int(step_order):02d}_{cleaned_step}"


def build_step_evidence_entry(request: StepEvidenceEntryRequest) -> dict:
    result = request.result
    step = result.step
    step_order = result.step_order
    role = result.role
    output = result.output
    handoff = request.handoff
    archetype = str(role["archetype"])
    verifies = _evidence_verifies(archetype, output)
    related_evidence_ids = _string_list(output.get("evidence_refs"))
    for coverage_result in list(output.get("coverage_results") or []):
        if isinstance(coverage_result, dict):
            related_evidence_ids.extend(_string_list(coverage_result.get("evidence_refs")))
    if evidence_entry_id(result.iter_id, step_order, step["id"]) in related_evidence_ids:
        related_evidence_ids = [item for item in related_evidence_ids if item != evidence_entry_id(result.iter_id, step_order, step["id"])]
    evidence_claims = _string_list(output.get("evidence_claims"))
    claim = _clean_text(output.get("decision_summary") if archetype == "gatekeeper" else handoff.get("summary"))
    if evidence_claims:
        claim = " ".join([claim, "Evidence:", "; ".join(evidence_claims[:4])]).strip()
    residual_risk = _evidence_residual_risk(archetype, output, handoff)
    control = step.get("control") if isinstance(step.get("control"), dict) else {}
    is_control = bool(step.get("control_id") or control)
    if is_control:
        signal = str(control.get("signal") or "").strip()
        reason = _clean_text(control.get("reason")) or f"Workflow control `{signal or 'control'}` ran."
        trigger_refs = _string_list(control.get("trigger_evidence_refs"))
        related_evidence_ids = list(dict.fromkeys([*trigger_refs, *related_evidence_ids]))[:20]
        claim = f"{reason} {claim}".strip()
        verifies = list(dict.fromkeys([f"control:{signal}", *verifies]))[:20]
    return {
        "id": evidence_entry_id(result.iter_id, step_order, step["id"]),
        "timestamp": utc_now(),
        "iter": int(result.iter_id),
        "step_id": str(step["id"]),
        "step_order": int(step_order),
        "role_id": str(role["id"]),
        "role_name": str(role["name"]),
        "runtime_role": str(result.runtime_role),
        "archetype": archetype,
        "evidence_kind": "control" if is_control else _evidence_kind(archetype),
        "source": "workflow_control" if is_control else _evidence_source(archetype),
        "method": f"workflow_control:{control.get('signal', '')}" if is_control else _evidence_method(archetype),
        "claim": claim or "This step produced a workflow handoff.",
        "result": _clean_text(handoff.get("status")) or "completed",
        "verifies": verifies,
        "related_evidence_ids": related_evidence_ids,
        "coverage_results": _evidence_coverage_results(output.get("coverage_results")),
        "measured_evidence": has_measured_gate_evidence(output.get("metric_scores"), output.get("metrics")),
        "concrete_evidence_claim_count": concrete_evidence_claim_count(evidence_claims),
        "residual_risk": residual_risk,
        "artifact_refs": list(handoff.get("artifact_refs") or []),
    }


def _evidence_method(archetype: str) -> str:
    return {
        "builder": "implementation_handoff",
        "inspector": "inspection",
        "gatekeeper": "gatekeeper_verdict",
        "guide": "stagnation_guidance",
        "custom": "supporting_observation",
    }.get(archetype, "workflow_handoff")


def _evidence_kind(archetype: str) -> str:
    return {
        "builder": "handoff",
        "inspector": "inspection",
        "gatekeeper": "verdict",
        "guide": "advisory",
        "custom": "observation",
    }.get(archetype, "observation")


def _evidence_source(archetype: str) -> str:
    return {
        "builder": "workspace_change",
        "inspector": "check_execution",
        "gatekeeper": "verdict",
        "guide": "stagnation_analysis",
        "custom": "supporting_role",
    }.get(archetype, "role_output")


def _evidence_verifies(archetype: str, output: dict) -> list[str]:
    refs: list[str] = []
    refs.extend(_coverage_result_verify_refs(output.get("coverage_results")))
    if archetype == "inspector":
        for bucket_name in ("check_results", "dynamic_checks"):
            for item in output.get(bucket_name, []) or []:
                if not isinstance(item, dict):
                    continue
                item_id = str(item.get("id") or item.get("title") or "").strip()
                status = str(item.get("status") or "").strip()
                if item_id:
                    refs.append(f"{bucket_name}:{item_id}:{status or 'unknown'}")
    elif archetype == "gatekeeper":
        refs.extend(f"check:{item}" for item in _string_list(output.get("failed_check_ids")))
        refs.extend(f"evidence:{item}" for item in _string_list(output.get("evidence_refs")))
    else:
        refs.extend(_string_list(output.get("changed_files")))
        refs.extend(_string_list(output.get("observations")))
    return refs[:20]


def _coverage_result_verify_refs(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    refs: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        target_id = str(item.get("target_id") or "").strip()
        if not target_id or ":" in target_id:
            continue
        status = str(item.get("status") or "unknown").strip() or "unknown"
        refs.append(f"target:{target_id}:{status}")
    return refs


def _evidence_coverage_results(value: object) -> list[dict]:
    if not isinstance(value, list):
        return []
    results: list[dict] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        target_id = str(item.get("target_id") or "").strip()
        if not target_id or ":" in target_id:
            continue
        results.append(
            {
                "target_id": target_id,
                "status": _clean_text(item.get("status")) or "unknown",
                "evidence_refs": _string_list(item.get("evidence_refs"))[:20],
                "note": _clean_text(item.get("note"))[:400],
            }
        )
    return results[:20]


def _evidence_residual_risk(archetype: str, output: dict, handoff: dict) -> str:
    risks: list[str] = []
    risks.extend(_string_list(output.get("residual_risks")))
    risks.extend(_string_list(output.get("hard_constraint_violations")))
    risks.extend(_string_list(output.get("blocking_issues")))
    if not risks:
        risks.extend(_string_list(handoff.get("blocking_items")))
    if archetype == "gatekeeper" and not risks and output.get("passed") is True:
        return "No blocking residual risk was reported by GateKeeper."
    return "; ".join(risks[:6])


def build_iteration_summary(context: IterationSummaryContext) -> dict:
    layout = context.layout
    iter_id = context.iter_id
    step_results = context.step_results
    stagnation = context.stagnation
    gatekeeper_handoff = next(
        (item["handoff"] for item in reversed(step_results) if item["role"]["archetype"] == "gatekeeper"),
        None,
    )
    gatekeeper_output = next(
        (item["output"] for item in reversed(step_results) if item["role"]["archetype"] == "gatekeeper"),
        {},
    )
    latest_by_step = {
        item["step"]["id"]: layout.relative(layout.step_handoff_path(iter_id, int(item["step_order"]), item["step"]["id"])) for item in step_results
    }
    latest_by_role = {
        item["role"]["id"]: layout.relative(layout.step_handoff_path(iter_id, int(item["step_order"]), item["step"]["id"])) for item in step_results
    }
    latest_by_archetype = {
        item["role"]["archetype"]: layout.relative(layout.step_handoff_path(iter_id, int(item["step_order"]), item["step"]["id"])) for item in step_results
    }
    composite = gatekeeper_output.get("composite_score")
    delta = round(float(composite) - float(context.previous_composite), 6) if composite is not None and context.previous_composite is not None else None
    return {
        "phase": "complete",
        "iter": int(iter_id),
        "timestamp": context.timestamp,
        "workflow": [
            {
                "step_id": str(item["step"]["id"]),
                "role_id": str(item["role"]["id"]),
                "role_name": str(item["role"]["name"]),
                "runtime_role": str(item["runtime_role"]),
                "archetype": str(item["role"]["archetype"]),
                "model": str(item.get("resolved_model") or ""),
                "status": str(item["handoff"]["status"]),
                "parallel_group": str(item["step"].get("parallel_group") or ""),
            }
            for item in step_results
        ],
        "step_handoffs": [item["handoff"] for item in step_results],
        "score": {
            "composite": composite,
            "delta": delta,
            "passed": gatekeeper_output.get("passed"),
        },
        "stagnation": {
            "mode": str(stagnation.get("stagnation_mode", "none")),
            "evidence_progress_mode": str(stagnation.get("evidence_progress_mode", "none") or "none"),
            "recent_composites": [float(value) for value in list(stagnation.get("recent_composites", [])) if value is not None],
            "recent_deltas": [float(value) for value in list(stagnation.get("recent_deltas", [])) if value is not None],
            "consecutive_low_delta": int(stagnation.get("consecutive_low_delta", 0) or 0),
            "covered_check_count": _int_value(stagnation.get("latest_covered_check_count")),
            "missing_check_count": _int_value(stagnation.get("latest_missing_check_count")),
            "consecutive_no_required_coverage_delta": _int_value(stagnation.get("consecutive_no_required_coverage_delta")),
        },
        "latest_refs": {
            "summary_path": layout.relative(layout.iteration_summary_path(iter_id)),
            "latest_gatekeeper": (
                layout.relative(layout.step_handoff_path(iter_id, gatekeeper_handoff["source"]["step_order"], gatekeeper_handoff["source"]["step_id"]))
                if gatekeeper_handoff
                else None
            ),
            "latest_by_step": latest_by_step,
            "latest_by_role": latest_by_role,
            "latest_by_archetype": latest_by_archetype,
        },
    }


def derive_latest_state(previous_state: dict, iteration_summary: dict) -> dict:
    latest_by_step = dict(previous_state.get("latest_by_step") or {})
    latest_by_step.update(iteration_summary["latest_refs"]["latest_by_step"])
    latest_by_role = dict(previous_state.get("latest_by_role") or {})
    latest_by_role.update(iteration_summary["latest_refs"]["latest_by_role"])
    latest_by_archetype = dict(previous_state.get("latest_by_archetype") or {})
    latest_by_archetype.update(iteration_summary["latest_refs"]["latest_by_archetype"])
    latest_gatekeeper = iteration_summary["latest_refs"].get("latest_gatekeeper")
    if latest_gatekeeper is None:
        latest_gatekeeper = previous_state.get("latest_gatekeeper")
    return {
        "latest_iteration": iteration_summary["iter"],
        "latest_by_step": latest_by_step,
        "latest_by_role": latest_by_role,
        "latest_by_archetype": latest_by_archetype,
        "latest_gatekeeper": latest_gatekeeper,
        "latest_summary_path": iteration_summary["latest_refs"]["summary_path"],
    }


def render_step_prompt(
    *,
    role: dict,
    prompt_label: str,
    prompt_body: str,
    packet: dict,
    compiled_spec: dict,
) -> str:
    role_note = resolve_role_note(
        compiled_spec,
        role_name=str(role.get("name") or ""),
        archetype=str(role.get("archetype") or ""),
    )
    role_posture = str(role.get("posture_notes", "") or "").strip()
    role_guidance = _combine_role_guidance(role_note, role_posture)
    sections = [
        f"You are {role['name']} inside Loopora.",
        system_prompt_prefix(role["archetype"]),
        output_contract_prompt(role["archetype"]),
        prompt_body.strip(),
        render_run_contract_section(packet["contract"], compiled_spec),
        render_role_note_section(role_guidance),
        render_iteration_section(packet),
        render_handoff_section(
            "Immediate upstream handoff",
            packet["upstream"]["immediate_previous_step"],
            empty_text="No previous step has completed in this iteration yet.",
        ),
        render_handoff_list_section(
            "Completed steps in this iteration",
            packet["upstream"]["completed_steps_this_iteration"],
            empty_text="No earlier steps have completed in this iteration yet.",
        ),
        render_handoff_section(
            "Previous iteration · same step",
            packet["upstream"]["previous_iteration_same_step"],
            empty_text="This step has no previous-iteration handoff yet.",
        ),
        render_handoff_section(
            "Previous iteration · same role",
            packet["upstream"]["previous_iteration_same_role"],
            empty_text="This role has no previous-iteration handoff yet.",
        ),
        render_previous_iteration_summary(packet["upstream"]["previous_iteration_summary"]),
        render_evidence_section(packet.get("evidence") or {}),
        render_artifact_refs(packet["artifacts"]),
        f"Prompt template: {prompt_label}",
    ]
    return "\n\n".join(section for section in sections if str(section).strip()).strip()


def system_prompt_prefix(archetype: str) -> str:
    if archetype == "builder":
        return (
            "System safety rules:\n"
            "- You may edit files inside the workdir.\n"
            "- Preserve existing non-.loopora files and avoid destructive rewrites.\n"
            "- Prefer focused, incremental changes over broad resets.\n"
            "- Treat project-local instructions, design docs, and tests as contract and evidence inputs when they exist.\n"
            "- Treat the run contract as frozen: do not reinterpret or lower Task, Done When, or Guardrails; "
            "surface contract problems as evidence gaps or blockers instead.\n"
            "- In the handoff, name which claim moved toward Proven and what remains Weak, Unproven, Blocking, or Residual risk."
        )
    if archetype == "inspector":
        return (
            "System safety rules:\n"
            "- Collect evidence with project-owned commands, files, and artifacts.\n"
            "- Prefer concrete commands and observations.\n"
            "- Treat project-local instructions, design docs, and tests as contract and evidence inputs when they exist.\n"
            "- Classify important observations as Proven, Weak, Unproven, Blocking, or Residual risk when that helps downstream judgment.\n"
            "- Treat the run contract as frozen: do not reinterpret or lower Task, Done When, or Guardrails; "
            "surface contract problems as evidence gaps or blockers instead.\n"
            "- Do not rewrite source files as part of inspection."
        )
    if archetype == "gatekeeper":
        return (
            "System safety rules:\n"
            "- Decide conservatively from direct evidence.\n"
            "- When evidence is weak, fail closed and explain what is missing.\n"
            "- Treat project-local instructions, design docs, and tests as contract and evidence inputs when they exist.\n"
            "- Keep run status separate from task verdict, and organize the verdict as Proven, Weak, Unproven, Blocking, or Residual risk.\n"
            "- Treat the run contract as frozen: do not reinterpret or lower Task, Done When, or Guardrails; "
            "surface contract problems as evidence gaps or blockers instead.\n"
            "- Keep the verdict short and operational."
        )
    if archetype == "custom":
        return (
            "System safety rules:\n"
            "- You are a low-permission supporting role.\n"
            "- Read the workspace and evidence, but do not claim write actions or final authority.\n"
            "- Prefer concrete observations and next-step recommendations.\n"
            "- Treat project-local instructions, design docs, and tests as contract and evidence inputs when they exist.\n"
            "- Mark specialized observations as Proven, Weak, Unproven, Blocking, or Residual risk when useful.\n"
            "- Treat the run contract as frozen: do not reinterpret or lower Task, Done When, or Guardrails; "
            "surface contract problems as evidence gaps or blockers instead.\n"
            "- Always return a stable takeaway with status, summary, blocking_items, and recommended_next_action."
        )
    return (
        "System safety rules:\n"
        "- Suggest the smallest useful direction change.\n"
        "- Do not act like a second GateKeeper.\n"
        "- Turn Blocking or Unproven gaps into a smaller proof or repair direction while keeping Residual risk visible.\n"
        "- Treat project-local instructions, design docs, and tests as contract and evidence inputs when they exist.\n"
        "- Treat the run contract as frozen: do not reinterpret or lower Task, Done When, or Guardrails; "
        "surface contract problems as evidence gaps or blockers instead.\n"
        "- Keep the advice grounded in the current evidence."
    )


def output_contract_prompt(archetype: str) -> str:
    if archetype == "builder":
        return (
            "Output contract: return JSON with attempted, abandoned, assumption, summary, changed_files, "
            "proof_files, proof_artifacts, and artifact_paths. Use empty arrays for proof_files, "
            "proof_artifacts, and artifact_paths when no proof artifact was created."
        )
    if archetype == "inspector":
        return (
            "Output contract: return JSON with execution_summary, check_results, dynamic_checks, tester_observations, "
            "and coverage_results. Use an empty coverage_results list unless you can explicitly verify or reject coverage target ids. "
            "Inside execution_summary, return total_checks, passed, failed, errored, and total_duration_ms. "
            "For every check_results item and dynamic_checks item, return id, title, status, and notes. "
            "For every coverage_results item, return target_id, status, evidence_refs, and note. "
            "Use notes to distinguish Proven, Weak, Unproven, Blocking, and Residual risk evidence."
        )
    if archetype == "gatekeeper":
        return (
            "Output contract: return JSON with passed, decision_summary, composite_score, metrics, metric_scores, "
            "blocking_issues, hard_constraint_violations, failed_check_ids, priority_failures, feedback_to_builder, "
            "feedback_to_generator, evidence_refs, evidence_claims, residual_risks, and coverage_results. "
            "Use empty arrays for metrics, blocking_issues, hard_constraint_violations, failed_check_ids, "
            "priority_failures, evidence_refs, evidence_claims, residual_risks, and coverage_results when there are no items. "
            "Metrics rows must include name, value, threshold, and passed. Inside metric_scores, provide exactly "
            "check_pass_rate and quality_score, each with value, threshold, and passed. Priority failures must include error_code and summary. "
            "For every coverage_results item, return target_id, status, evidence_refs, and note. "
            "A pass must cite supporting upstream evidence_refs from the Evidence ledger; a plain Builder handoff is not support unless it carries a proof artifact or measured evidence. If this is the first gate in the workflow, "
            "claims alone are not enough; provide concrete metric_scores tied to the evidence you inspected. "
            "The decision_summary should separate run status from task verdict and name any Weak, Unproven, Blocking, or Residual risk evidence."
        )
    if archetype == "custom":
        return (
            "Output contract: return JSON with status, summary, blocking_items, recommended_next_action, "
            "observations, recommendations, risks, and handoff_note."
        )
    return (
        "Output contract: return JSON with created_at_iter, mode, consumed, analysis, seed_question, and meta_note. "
        "Inside analysis, turn Blocking or Unproven gaps into the smallest repair direction, strengthen Weak evidence only when it changes the decision, "
        "and keep Residual risk visible."
    )


def render_run_contract_section(contract: dict, compiled_spec: dict) -> str:
    constraints = contract.get("constraints") or "No explicit constraints were provided."
    success_surface = json.dumps(contract.get("success_surface") or [], ensure_ascii=False, indent=2)
    fake_done_states = json.dumps(contract.get("fake_done_states") or [], ensure_ascii=False, indent=2)
    evidence_preferences = json.dumps(contract.get("evidence_preferences") or [], ensure_ascii=False, indent=2)
    coverage_targets = json.dumps(contract.get("coverage_targets") or [], ensure_ascii=False, indent=2)
    workflow_collaboration_intent = str(contract.get("workflow_collaboration_intent") or "No explicit workflow collaboration intent was provided.").strip()
    residual_risk = str(contract.get("residual_risk") or "No explicit residual-risk stance was provided.").strip()
    return (
        "Run contract summary:\n"
        f"- Completion mode: {contract.get('completion_mode')}\n"
        f"- Workflow preset: {contract.get('workflow_preset')}\n"
        f"- Workflow collaboration intent: {workflow_collaboration_intent}\n"
        f"- Check mode: {contract.get('check_mode')}\n"
        f"- Check count: {contract.get('check_count')}\n\n"
        f"Goal:\n{contract.get('goal', '').strip()}\n\n"
        f"Checks:\n{json.dumps(compiled_spec.get('checks', []), ensure_ascii=False, indent=2)}\n\n"
        f"Constraints:\n{constraints}\n\n"
        f"Coverage targets:\n{coverage_targets}\n\n"
        f"Success surface:\n{success_surface}\n\n"
        f"Fake done states:\n{fake_done_states}\n\n"
        f"Evidence preferences:\n{evidence_preferences}\n\n"
        f"Residual risk:\n{residual_risk}"
    )


def render_role_note_section(role_note: str) -> str:
    if not str(role_note or "").strip():
        return ""
    return f"Role notes for the current role:\n{str(role_note).strip()}"


def _combine_role_guidance(spec_role_note: str, role_posture: str) -> str:
    parts: list[str] = []
    if str(role_posture or "").strip():
        parts.append(f"Role definition posture:\n{str(role_posture).strip()}")
    if str(spec_role_note or "").strip():
        parts.append(f"Spec role notes:\n{str(spec_role_note).strip()}")
    return "\n\n".join(parts).strip()


def _int_value(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def render_iteration_section(packet: dict) -> str:
    iteration = packet["iteration"]
    current_step = packet["current_step"]
    iter_display = int(iteration["iter_index"]) + 1
    step_display = int(current_step["step_order"]) + 1
    if iteration["is_first_iteration"]:
        previous_line = "This is the first iteration, so there is no previous iteration result."
    else:
        previous_line = (
            f"This is iteration {iter_display}. Reference the previous iteration result before continuing. "
            f"Previous composite score: {iteration['previous_composite']}."
        )
    control = current_step.get("control") if isinstance(current_step.get("control"), dict) else {}
    action_policy = current_step.get("action_policy") if isinstance(current_step.get("action_policy"), dict) else {}
    control_lines = ""
    if control:
        control_lines = (
            f"- Control trigger: {control.get('signal') or 'unknown'}\n"
            f"- Control mode: {control.get('mode') or 'advisory'}\n"
            f"- Control reason: {control.get('reason') or 'runtime control check'}\n"
        )
    return (
        "Current execution frame:\n"
        f"- Iteration: {iter_display}\n"
        f"- Step: {step_display}\n"
        f"- Step id: {current_step['step_id']}\n"
        f"- Role: {current_step['role_name']} ({current_step['archetype']})\n"
        f"- Model: {current_step['model'] or 'default'}\n"
        f"- Executor: {current_step['executor_kind']} / {current_step['executor_mode']}\n"
        f"- Parallel group: {current_step.get('parallel_group') or 'none'}\n"
        f"- Input policy: {json.dumps(current_step.get('inputs') or {}, ensure_ascii=False)}\n"
        f"- Action policy: {json.dumps(action_policy, ensure_ascii=False)}\n"
        f"{control_lines}"
        f"- Stagnation mode: {iteration['stagnation_mode']}\n"
        f"- Evidence progress mode: {iteration['evidence_progress_mode']}\n"
        f"- Required coverage: {iteration['covered_check_count']} covered, {iteration['missing_check_count']} missing\n"
        f"- Consecutive iterations without required coverage delta: {iteration['consecutive_no_required_coverage_delta']}\n\n"
        f"{previous_line}"
    )


def render_handoff_section(title: str, handoff: dict | None, *, empty_text: str) -> str:
    if not handoff:
        return f"{title}:\n- {empty_text}"
    source = handoff["source"]
    return (
        f"{title}:\n"
        f"- From: {source['role_name']} ({source['archetype']})\n"
        f"- Step: {source['step_id']}\n"
        f"- Status: {handoff['status']}\n"
        f"- Summary: {handoff['summary']}\n"
        f"- Blocking items: {json.dumps(handoff['blocking_items'], ensure_ascii=False)}\n"
        f"- Evidence refs: {json.dumps(handoff.get('evidence_refs', []), ensure_ascii=False)}\n"
        f"- Recommended next action: {handoff['recommended_next_action']}"
    )


def render_handoff_list_section(title: str, handoffs: list[dict], *, empty_text: str) -> str:
    if not handoffs:
        return f"{title}:\n- {empty_text}"
    lines = [f"{title}:"]
    for handoff in handoffs:
        source = handoff["source"]
        lines.append(
            f"- {source['step_order'] + 1}. {source['role_name']} ({source['archetype']}) :: {handoff['status']} :: {handoff['summary']}"
            f" :: evidence={json.dumps(handoff.get('evidence_refs', []), ensure_ascii=False)}"
        )
    return "\n".join(lines)


def render_previous_iteration_summary(summary: dict | None) -> str:
    if not summary:
        return "Previous iteration summary:\n- No previous iteration summary is available yet."
    lines = [
        "Previous iteration summary:\n"
        f"- Iteration: {int(summary['iter']) + 1}\n"
        f"- Composite score: {summary['score']['composite']}\n"
        f"- Score delta: {summary['score']['delta']}\n"
        f"- Passed: {summary['score']['passed']}\n"
        f"- Stagnation mode: {summary['stagnation']['mode']}\n"
        f"- Evidence progress mode: {summary['stagnation']['evidence_progress_mode']}\n"
        f"- Required coverage: {summary['stagnation']['covered_check_count']} covered, {summary['stagnation']['missing_check_count']} missing\n"
        f"- Consecutive iterations without required coverage delta: {summary['stagnation']['consecutive_no_required_coverage_delta']}\n"
        f"- Step count: {len(summary['workflow'])}"
    ]
    for handoff in list(summary.get("step_handoffs", []))[:6]:
        source = handoff.get("source", {})
        lines.append(
            f"- Previous step {source.get('step_order', 0) + 1} :: {source.get('role_name', '-')}"
            f" :: {handoff.get('status', '-')}"
            f" :: {handoff.get('summary', '-')}"
            f" :: evidence={json.dumps(handoff.get('evidence_refs', []), ensure_ascii=False)}"
            f" :: next={handoff.get('recommended_next_action', '-')}"
        )
    return "\n".join(lines)


def render_evidence_section(evidence: dict) -> str:
    items = list(evidence.get("items") or [])
    ledger_path = str(evidence.get("ledger_path") or "").strip()
    manifest_path = str(evidence.get("manifest_path") or "").strip()
    coverage_path = str(evidence.get("coverage_path") or "").strip()
    manifest_summary = evidence.get("manifest_summary") if isinstance(evidence.get("manifest_summary"), dict) else {}
    manifest_claims = _manifest_claims_by_id(evidence.get("manifest_claims"))
    lines = ["Evidence ledger:"]
    if ledger_path:
        lines.append(f"- Path: {ledger_path}")
    if manifest_path:
        lines.append(f"- Manifest: {manifest_path}")
    if coverage_path:
        lines.append(f"- Coverage: {coverage_path}")
    summary_line = _manifest_summary_prompt_line(manifest_summary)
    if summary_line:
        lines.append(summary_line)
    known_ids = [str(item).strip() for item in list(evidence.get("known_ids") or []) if str(item).strip()]
    if known_ids:
        lines.append(f"- Known ids: {json.dumps(known_ids[-40:], ensure_ascii=False)}")
    if not items:
        lines.append("- No evidence items have been written yet.")
        return "\n".join(lines)
    for item in items[-12:]:
        lines.extend(_evidence_item_prompt_lines(item, manifest_claims))
    return "\n".join(lines)


def _evidence_item_prompt_lines(item: object, manifest_claims: dict[str, dict]) -> list[str]:
    if not isinstance(item, dict):
        return []
    lines = [f"- {item.get('id', '-')}: {item.get('role_name', '-')} ({item.get('archetype', '-')}) ::{item.get('result', '-')} :: {item.get('claim', '-')}"]
    lines.extend(_manifest_claim_prompt_lines(manifest_claims.get(str(item.get("id") or "").strip())))
    related = item.get("related_evidence_ids") if isinstance(item.get("related_evidence_ids"), list) else []
    if related:
        lines.append(f"  related={json.dumps(related, ensure_ascii=False)}")
    coverage_results = _evidence_item_prompt_coverage_results(item.get("coverage_results"))
    if coverage_results:
        lines.append(f"  coverage_results={json.dumps(coverage_results, ensure_ascii=False)}")
    artifacts = _artifact_ref_prompt_paths(item.get("artifact_refs"))
    if artifacts:
        lines.append(f"  artifacts={json.dumps(artifacts, ensure_ascii=False)}")
    return lines


def _evidence_item_prompt_coverage_results(value: object) -> list[dict]:
    if not isinstance(value, list):
        return []
    rows: list[dict] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        target_id = str(item.get("target_id") or "").strip()
        if not target_id:
            continue
        rows.append(
            {
                "target_id": target_id,
                "status": str(item.get("status") or "").strip(),
                "evidence_refs": _string_list(item.get("evidence_refs"))[:8],
            }
        )
    return rows[:8]


def _manifest_claims_by_id(value: object) -> dict[str, dict]:
    return {str(claim.get("id") or "").strip(): claim for claim in list(value or []) if isinstance(claim, dict) and str(claim.get("id") or "").strip()}


def _normalize_evidence_items(value: object) -> list[dict]:
    if not isinstance(value, list):
        return []
    items: list[dict] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        normalized = dict(item)
        normalized["coverage_results"] = _evidence_coverage_results(normalized.get("coverage_results"))
        items.append(normalized)
    return items


def _manifest_summary_prompt_line(summary: dict) -> str:
    if not summary:
        return ""
    return (
        "- Proof strength: "
        f"claims={_int_value(summary.get('claim_count'))}, "
        f"direct_proof={_int_value(summary.get('direct_proof_claim_count'))}, "
        f"workspace_artifact={_int_value(summary.get('workspace_artifact_claim_count'))}, "
        f"run_artifact={_int_value(summary.get('run_artifact_claim_count'))}, "
        f"ledger_only={_int_value(summary.get('ledger_only_claim_count'))}, "
        f"unverified={_int_value(summary.get('unverified_claim_count'))}, "
        f"problems={_int_value(summary.get('problem_count'))}"
    )


def _manifest_claim_prompt_lines(claim: dict | None) -> list[str]:
    if not isinstance(claim, dict):
        return []
    lines = [
        "  "
        f"proof_status={claim.get('verification_status') or 'unknown'} "
        f"measured={_prompt_bool(claim.get('measured_evidence'))} "
        f"concrete_claims={_int_value(claim.get('concrete_evidence_claim_count'))} "
        f"artifact_backed={_prompt_bool(claim.get('artifact_backed'))} "
        f"workspace_backed={_prompt_bool(claim.get('workspace_backed'))} "
        f"reproducible={_prompt_bool(claim.get('reproducible'))} "
        f"coverage_targets={json.dumps(list(claim.get('coverage_targets') or [])[:8], ensure_ascii=False)}"
    ]
    problem_codes = [str(code).strip() for code in list(claim.get("problem_codes") or []) if str(code).strip()]
    if problem_codes:
        lines.append(f"  proof_problems={json.dumps(problem_codes[:8], ensure_ascii=False)}")
    return lines


def _normalize_manifest_summary(value: object) -> dict:
    source = value if isinstance(value, dict) else {}
    return {
        "claim_count": _int_value(source.get("claim_count")),
        "direct_proof_claim_count": _int_value(source.get("direct_proof_claim_count")),
        "workspace_artifact_claim_count": _int_value(source.get("workspace_artifact_claim_count")),
        "run_artifact_claim_count": _int_value(source.get("run_artifact_claim_count")),
        "ledger_only_claim_count": _int_value(source.get("ledger_only_claim_count")),
        "unverified_claim_count": _int_value(source.get("unverified_claim_count")),
        "problem_count": _int_value(source.get("problem_count")),
    }


def _normalize_manifest_claims(value: object) -> list[dict]:
    rows: list[dict] = []
    for claim in list(value or []):
        if not isinstance(claim, dict):
            continue
        claim_id = str(claim.get("id") or "").strip()
        if not claim_id:
            continue
        rows.append(
            {
                "id": claim_id,
                "verification_status": str(claim.get("verification_status") or "ledger_only").strip(),
                "measured_evidence": bool(claim.get("measured_evidence")),
                "concrete_evidence_claim_count": _int_value(claim.get("concrete_evidence_claim_count")),
                "artifact_count": _int_value(claim.get("artifact_count")),
                "artifact_backed": bool(claim.get("artifact_backed")),
                "workspace_backed": bool(claim.get("workspace_backed")),
                "reproducible": bool(claim.get("reproducible")),
                "coverage_targets": [str(item).strip() for item in list(claim.get("coverage_targets") or []) if str(item).strip()][:20],
                "problem_codes": [str(item).strip() for item in list(claim.get("problem_codes") or []) if str(item).strip()][:20],
            }
        )
    return rows[:40]


def _prompt_bool(value: object) -> str:
    return "true" if bool(value) else "false"


def _artifact_ref_prompt_paths(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    paths: list[str] = []
    refs = [ref for ref in value if isinstance(ref, dict)]
    refs = [
        *[ref for ref in refs if str(ref.get("kind") or "").strip() == "workspace"],
        *[ref for ref in refs if str(ref.get("kind") or "").strip() != "workspace"],
    ]
    for ref in refs:
        label = str(ref.get("label") or ref.get("kind") or "artifact").strip()
        workspace_path = str(ref.get("workspace_path") or "").strip()
        relative_path = str(ref.get("relative_path") or "").strip()
        absolute_path = str(ref.get("absolute_path") or "").strip()
        if not workspace_path and not relative_path:
            continue
        if workspace_path and relative_path and workspace_path != relative_path:
            path_text = f"{label}: {workspace_path} (run-local: {relative_path})"
        else:
            path_text = f"{label}: {workspace_path or relative_path}"
        if absolute_path:
            path_text = f"{path_text} (absolute: {absolute_path})"
        paths.append(path_text)
        if len(paths) >= 4:
            break
    return paths


def render_artifact_refs(refs: list[dict]) -> str:
    lines = ["Artifact refs:"]
    for ref in refs:
        workspace_path = str(ref.get("workspace_path") or ref.get("relative_path") or "").strip()
        relative_path = str(ref.get("relative_path") or "").strip()
        absolute_path = str(ref.get("absolute_path") or "").strip()
        if relative_path and workspace_path and workspace_path != relative_path:
            path_text = f"- {ref['label']}: {workspace_path} (run-local: {relative_path})"
        else:
            path_text = f"- {ref['label']}: {workspace_path or relative_path}"
        if absolute_path:
            path_text = f"{path_text} (absolute: {absolute_path})"
        lines.append(path_text)
    return "\n".join(lines)


def _clean_text(value: object) -> str:
    return str(value or "").strip()


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _inspector_blockers(output: dict) -> list[str]:
    blockers = []
    failed_items = output.get("failed_items")
    if isinstance(failed_items, list):
        blockers.extend(str(item.get("title") or item.get("id") or "").strip() for item in failed_items if item)
    for bucket_name in ("check_results", "dynamic_checks"):
        for item in output.get(bucket_name, []) or []:
            if str(item.get("status") or "").strip() == "passed":
                continue
            blocker = str(item.get("title") or item.get("id") or "").strip()
            if blocker:
                blockers.append(blocker)
    return blockers


def _gatekeeper_blockers(output: dict) -> list[str]:
    blockers = [item for item in _string_list(output.get("failed_check_ids")) if item]
    priority_failures = output.get("priority_failures")
    if isinstance(priority_failures, list):
        blockers.extend(str(item.get("summary") or item.get("error_code") or "").strip() for item in priority_failures if isinstance(item, dict))
    return [item for item in blockers if item]
