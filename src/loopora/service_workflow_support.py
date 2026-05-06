from __future__ import annotations

from dataclasses import dataclass

from loopora.context_flow import IterationSummaryContext, build_iteration_summary, derive_latest_state
from loopora.run_artifacts import RunArtifactLayout, append_jsonl_with_mirrors
from loopora.service_prompts import BUILDER_SCHEMA, CUSTOM_SCHEMA, GATEKEEPER_SCHEMA, GUIDE_SCHEMA, INSPECTOR_SCHEMA
from loopora.utils import read_json, utc_now, write_json
from loopora.workflows import LEGACY_ROLE_BY_ARCHETYPE


def _string_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _has_measured_gate_evidence(metric_scores: object, metrics: object) -> bool:
    if isinstance(metric_scores, dict):
        for value in metric_scores.values():
            if not isinstance(value, dict):
                continue
            if isinstance(value.get("value"), (int, float)) and isinstance(value.get("threshold"), (int, float)):
                return True
    if isinstance(metrics, list):
        for value in metrics:
            if not isinstance(value, dict):
                continue
            if isinstance(value.get("value"), (int, float)) and isinstance(value.get("threshold"), (int, float)):
                return True
    return False


@dataclass(frozen=True)
class GatekeeperEvidenceContext:
    known_by_id: dict[str, dict]
    known_ids: set[str]
    current_id: str


@dataclass
class GatekeeperEvidenceGateState:
    result: dict
    evidence_refs: list[str]
    evidence_claims: list[str]
    metric_scores: dict
    context: GatekeeperEvidenceContext
    blocking_issues: list[str]


@dataclass(frozen=True)
class GatekeeperResultFields:
    feedback: str
    blocking_issues: list[str]
    metric_scores: dict
    composite_score: object
    evidence_refs: list[str]
    evidence_claims: list[str]


@dataclass(frozen=True)
class StepOutputNormalizationRequest:
    archetype: str
    output: dict
    compiled_spec: dict
    inspector_output: dict | None
    evidence_context: dict | None = None
    current_evidence_id: str = ""


@dataclass(frozen=True)
class StepOutputsWriteRequest:
    layout: RunArtifactLayout
    iter_id: int
    step: dict
    step_order: int
    role: dict
    runtime_role: str
    output: dict
    handoff: dict


@dataclass(frozen=True)
class IterationContextPersistRequest:
    layout: RunArtifactLayout
    run_id: str
    iter_id: int
    step_results: list[dict]
    stagnation: dict
    previous_composite: float | None


@dataclass(frozen=True)
class WorkflowSummaryRequest:
    run: dict
    workflow: dict
    compiled_spec: dict
    iter_id: int
    step_results: list[dict]
    stagnation: dict
    exhausted: bool
    previous_composite: float | None


def _gatekeeper_evidence_context(evidence_context: dict | None, current_evidence_id: str) -> GatekeeperEvidenceContext:
    known_by_id = {
        str(item.get("id") or "").strip(): item
        for item in list((evidence_context or {}).get("items") or [])
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    }
    known_ids = set(known_by_id)
    known_ids.update(_string_list((evidence_context or {}).get("known_ids")))
    return GatekeeperEvidenceContext(
        known_by_id=known_by_id,
        known_ids=known_ids,
        current_id=str(current_evidence_id or "").strip(),
    )


def _expand_self_evidence_refs(evidence_refs: list[str], context: GatekeeperEvidenceContext) -> list[str]:
    if not context.current_id:
        return evidence_refs
    return [context.current_id if item == "self" else item for item in evidence_refs]


def _metric_scores_from_result(result: dict) -> dict:
    metric_scores = result.get("metric_scores")
    if isinstance(metric_scores, dict):
        return metric_scores
    return _metric_scores_from_metrics(result.get("metrics"))


def _metric_scores_from_metrics(metrics: object) -> dict:
    metric_scores = {}
    for metric in list(metrics or []):
        if not isinstance(metric, dict):
            continue
        name = str(metric.get("name", "")).strip()
        if not name:
            continue
        metric_scores[name] = {
            "value": metric.get("value"),
            "threshold": metric.get("threshold"),
            "passed": bool(metric.get("passed")),
        }
    return metric_scores


def _composite_score_for_result(result: dict, metric_scores: dict) -> object:
    composite_score = result.get("composite_score")
    if composite_score is not None:
        return composite_score
    quality_metric = metric_scores.get("quality_score")
    if isinstance(quality_metric, dict):
        return quality_metric.get("value")
    return 1.0 if result.get("passed") else 0.0


def _metric_rows_from_scores(metric_scores: dict) -> list[dict]:
    return [
        {
            "name": name,
            "value": value.get("value"),
            "threshold": value.get("threshold"),
            "passed": value.get("passed"),
        }
        for name, value in metric_scores.items()
        if isinstance(value, dict)
    ]


def _invalid_evidence_refs(evidence_refs: list[str], context: GatekeeperEvidenceContext) -> list[str]:
    return [item for item in evidence_refs if item != context.current_id and item not in context.known_ids]


def _supporting_upstream_refs(evidence_refs: list[str], context: GatekeeperEvidenceContext) -> list[str]:
    return [
        item
        for item in evidence_refs
        if item != context.current_id
        and item in context.known_ids
        and str(context.known_by_id.get(item, {}).get("archetype") or "").strip().lower() != "gatekeeper"
    ]


def _invalid_ref_blocker(invalid_refs: list[str]) -> str:
    return (
        "gatekeeper_evidence_refs_unknown: "
        + ", ".join(invalid_refs[:4])
        + ("..." if len(invalid_refs) > 4 else "")
    )


def _apply_gatekeeper_evidence_gate(state: GatekeeperEvidenceGateState) -> list[str]:
    if not state.result["passed"]:
        return state.evidence_refs
    has_measured_evidence = _has_measured_gate_evidence(state.metric_scores, state.result.get("metrics"))
    concrete_claims = [item for item in state.evidence_claims if len(item) >= 24]
    evidence_refs = state.evidence_refs
    if not evidence_refs and state.context.current_id and concrete_claims and has_measured_evidence:
        evidence_refs = [state.context.current_id]

    invalid_refs = _invalid_evidence_refs(evidence_refs, state.context)
    supporting_refs = _supporting_upstream_refs(evidence_refs, state.context)
    if invalid_refs:
        state.blocking_issues.append(_invalid_ref_blocker(invalid_refs))
        state.result["passed"] = False
    elif not evidence_refs:
        state.blocking_issues.append("gatekeeper_pass_requires_evidence_refs")
        state.result["passed"] = False
    elif not supporting_refs and not has_measured_evidence:
        state.blocking_issues.append("gatekeeper_pass_requires_upstream_or_measured_evidence")
        state.result["passed"] = False
    return evidence_refs


def _adjust_blocked_composite_score(composite_score: object, result: dict, blocking_issues: list[str]) -> object:
    if not result["passed"] and float(composite_score or 0.0) >= 0.9 and blocking_issues:
        return 0.89
    return composite_score


def _populate_gatekeeper_result(result: dict, fields: GatekeeperResultFields) -> dict:
    result["decision_summary"] = str(result.get("decision_summary") or "").strip() or (
        "The workflow still needs more evidence." if not result["passed"] else "All checks passed."
    )
    result["feedback_to_builder"] = fields.feedback
    result["feedback_to_generator"] = fields.feedback
    result["blocking_issues"] = fields.blocking_issues
    result["hard_constraint_violations"] = fields.blocking_issues
    result["metric_scores"] = fields.metric_scores
    result["composite_score"] = float(fields.composite_score or 0.0)
    result["evidence_refs"] = fields.evidence_refs
    result["evidence_claims"] = fields.evidence_claims
    result["evidence_gate_status"] = "passed" if result["passed"] else (
        "blocked" if fields.blocking_issues else "not_passed"
    )
    result.setdefault("failed_check_ids", [])
    result.setdefault("priority_failures", [])
    return result


class ServiceWorkflowSupportMixin:
    def _output_schema_for_archetype(self, archetype: str) -> dict:
        if archetype == "builder":
            return BUILDER_SCHEMA
        if archetype == "inspector":
            return INSPECTOR_SCHEMA
        if archetype == "gatekeeper":
            return GATEKEEPER_SCHEMA
        if archetype == "custom":
            return CUSTOM_SCHEMA
        return GUIDE_SCHEMA

    def _normalize_step_output(
        self,
        request: StepOutputNormalizationRequest,
    ) -> dict:
        if request.archetype == "inspector":
            return self._enrich_tester_result(request.output)
        if request.archetype == "gatekeeper":
            gatekeeper_output = self._coerce_gatekeeper_output(
                request.output,
                evidence_context=request.evidence_context,
                current_evidence_id=request.current_evidence_id,
            )
            return self._enrich_verifier_result(gatekeeper_output, request.compiled_spec, request.inspector_output or {})
        return dict(request.output)

    def _coerce_gatekeeper_output(
        self,
        output: dict,
        *,
        evidence_context: dict | None = None,
        current_evidence_id: str = "",
    ) -> dict:
        result = dict(output)
        feedback = str(result.get("feedback_to_builder") or result.get("feedback_to_generator") or "").strip()
        blocking_issues = _string_list(result.get("blocking_issues") or result.get("hard_constraint_violations"))
        evidence_refs = _string_list(result.get("evidence_refs") or result.get("evidence_item_ids"))
        evidence_claims = _string_list(result.get("evidence_claims") or result.get("evidence_summary"))
        gate_context = _gatekeeper_evidence_context(evidence_context, current_evidence_id)
        evidence_refs = _expand_self_evidence_refs(evidence_refs, gate_context)
        metric_scores = _metric_scores_from_result(result)
        composite_score = _composite_score_for_result(result, metric_scores)
        if not result.get("metrics"):
            result["metrics"] = _metric_rows_from_scores(metric_scores)
        result["passed"] = bool(result.get("passed", False))
        evidence_refs = _apply_gatekeeper_evidence_gate(
            GatekeeperEvidenceGateState(
                result=result,
                evidence_refs=evidence_refs,
                evidence_claims=evidence_claims,
                metric_scores=metric_scores,
                context=gate_context,
                blocking_issues=blocking_issues,
            )
        )
        composite_score = _adjust_blocked_composite_score(composite_score, result, blocking_issues)
        return _populate_gatekeeper_result(
            result,
            GatekeeperResultFields(
                feedback=feedback,
                blocking_issues=blocking_issues,
                metric_scores=metric_scores,
                composite_score=composite_score,
                evidence_refs=evidence_refs,
                evidence_claims=evidence_claims,
            ),
        )

    def _write_step_outputs(
        self,
        request: StepOutputsWriteRequest,
    ) -> None:
        step_dir = request.layout.step_dir(request.iter_id, request.step_order, request.step["id"])
        step_dir.mkdir(parents=True, exist_ok=True)
        write_json(
            request.layout.step_output_normalized_path(request.iter_id, request.step_order, request.step["id"]),
            request.output,
        )
        write_json(
            request.layout.step_metadata_path(request.iter_id, request.step_order, request.step["id"]),
            {
                "step_id": request.step["id"],
                "step_order": request.step_order,
                "role_id": request.role["id"],
                "role_name": request.role["name"],
                "runtime_role": request.runtime_role,
                "archetype": request.role["archetype"],
                "iter": request.iter_id,
                "inherit_session": bool(request.step.get("inherit_session")),
                "extra_cli_args": str(request.step.get("extra_cli_args") or ""),
                "parallel_group": str(request.step.get("parallel_group") or ""),
                "inputs": dict(request.step.get("inputs") or {}),
                "action_policy": dict(request.step.get("action_policy") or {}),
                "control_id": str(request.step.get("control_id") or ""),
                "control": dict(request.step.get("control") or {})
                if isinstance(request.step.get("control"), dict)
                else {},
            },
        )
        write_json(
            request.layout.step_handoff_path(request.iter_id, request.step_order, request.step["id"]),
            request.handoff,
        )

        for alias_path in request.layout.legacy_role_output_paths(request.role["archetype"]):
            write_json(alias_path, request.output)

    def _persist_iteration_context(
        self,
        request: IterationContextPersistRequest,
    ) -> dict:
        iteration_summary = build_iteration_summary(
            IterationSummaryContext(
                layout=request.layout,
                iter_id=request.iter_id,
                step_results=request.step_results,
                stagnation=request.stagnation,
                previous_composite=request.previous_composite,
                timestamp=utc_now(),
            )
        )
        write_json(request.layout.iteration_summary_path(request.iter_id), iteration_summary)
        append_jsonl_with_mirrors(request.layout.timeline_iterations_path, iteration_summary)
        latest_state = derive_latest_state(read_json(request.layout.latest_state_path), iteration_summary)
        write_json(request.layout.latest_iteration_summary_path, iteration_summary)
        write_json(request.layout.latest_state_path, latest_state)
        self.append_run_event(
            request.run_id,
            "iteration_summary_written",
            {
                "iter": request.iter_id,
                "summary_path": request.layout.relative(request.layout.iteration_summary_path(request.iter_id)),
                "latest_state_path": request.layout.relative(request.layout.latest_state_path),
                "executed_step_count": len(request.step_results),
                "composite_score": iteration_summary["score"]["composite"],
                "passed": iteration_summary["score"]["passed"],
            },
        )
        return iteration_summary

    def _build_workflow_iteration_entry(
        self,
        iter_id: int,
        step_results: list[dict],
        stagnation: dict,
        *,
        previous_composite: float | None,
    ) -> dict:
        by_archetype = {item["role"]["archetype"]: item["output"] for item in step_results}
        gatekeeper_output = by_archetype.get("gatekeeper", {})
        entry = {
            "phase": "complete",
            "iter": iter_id,
            "timestamp": utc_now(),
            "workflow": [
                {
                    "step_id": item["step"]["id"],
                    "role_id": item["role"]["id"],
                    "runtime_role": item.get("runtime_role"),
                    "role_name": item["role"]["name"],
                    "archetype": item["role"]["archetype"],
                    "model": item.get("resolved_model") or "",
                    "parallel_group": str(item["step"].get("parallel_group") or ""),
                }
                for item in step_results
            ],
            "builder": by_archetype.get("builder", {}),
            "inspector": by_archetype.get("inspector", {}),
            "gatekeeper": gatekeeper_output,
            "guide": by_archetype.get("guide", {}),
            "evidence": {
                "gatekeeper_refs": list(gatekeeper_output.get("evidence_refs", [])),
                "gatekeeper_status": gatekeeper_output.get("evidence_gate_status"),
            },
            "score": {
                "composite": gatekeeper_output.get("composite_score"),
                "delta": round(gatekeeper_output["composite_score"] - previous_composite, 6)
                if previous_composite is not None and gatekeeper_output.get("composite_score") is not None
                else None,
                "passed": gatekeeper_output.get("passed"),
            },
            "stagnation": {
                "mode": stagnation.get("stagnation_mode", "none"),
                "recent_composites": list(stagnation.get("recent_composites", [])),
                "recent_deltas": list(stagnation.get("recent_deltas", [])),
                "consecutive_low_delta": stagnation.get("consecutive_low_delta", 0),
            },
        }
        entry["generator"] = entry["builder"]
        entry["tester"] = entry["inspector"]
        entry["verifier"] = entry["gatekeeper"]
        if entry["guide"]:
            entry["challenger"] = entry["guide"]
        return entry

    def _build_workflow_summary(
        self,
        request: WorkflowSummaryRequest,
    ) -> str:
        gatekeeper_output = next(
            (item["output"] for item in reversed(request.step_results) if item["role"]["archetype"] == "gatekeeper"),
            {},
        )
        completion_mode = str(request.run.get("completion_mode", "gatekeeper")).strip().lower() or "gatekeeper"
        status_line = (
            "Planned rounds completed."
            if request.exhausted and completion_mode == "rounds"
            else "Max iterations exhausted."
            if request.exhausted
            else "Still iterating."
        )
        if gatekeeper_output.get("passed") and completion_mode == "gatekeeper":
            status_line = "All checks passed in this iteration."
        elif gatekeeper_output.get("passed"):
            status_line = "GateKeeper passed in this iteration, but the run stays in round-based mode."
        delta_text = (
            f"`{round(gatekeeper_output['composite_score'] - request.previous_composite, 6):+}`"
            if request.previous_composite is not None and gatekeeper_output.get("composite_score") is not None
            else "`n/a`"
        )
        lines = [
            "# Loopora Run Summary",
            "",
            f"- Workdir: `{request.run['workdir']}`",
            f"- Iteration: `{request.iter_id + 1 if request.iter_id >= 0 else 0}`",
            f"- Workflow preset: `{request.workflow.get('preset') or 'custom'}`",
            f"- Check mode: `{request.compiled_spec.get('check_mode', 'specified')}`",
            f"- Check count: `{len(request.compiled_spec.get('checks', []))}`",
            f"- Completion mode: `{completion_mode}`",
            f"- Iteration interval seconds: `{request.run.get('iteration_interval_seconds', 0.0)}`",
            f"- Composite score: `{gatekeeper_output.get('composite_score', 'n/a')}`",
            f"- Score delta vs previous iteration: {delta_text}",
            f"- Passed: `{gatekeeper_output.get('passed', False)}`",
            f"- Stagnation mode: `{request.stagnation.get('stagnation_mode', 'none')}`",
            "",
            status_line,
        ]
        for item in request.step_results:
            role = item["role"]
            output = item["output"]
            heading = {
                "builder": "Generator / Builder",
                "inspector": "Tester / Inspector",
                "gatekeeper": "Verifier / GateKeeper",
                "guide": "Challenger / Guide",
                "custom": "Restricted Custom Role",
            }.get(role["archetype"], role["name"])
            lines.extend(
                [
                    "",
                    f"## {heading}",
                    f"- Archetype: `{role['archetype']}`",
                    f"- Summary: {self._summary_line_for_step(role['archetype'], output)}",
                ]
            )
        lines.extend(
            [
                "",
                "## Artifacts",
                "- Inspect `evidence/ledger.jsonl`, `contract/workflow.json`, `timeline/iterations.jsonl`, `timeline/events.jsonl`, and `iterations/` for full details.",
            ]
        )
        return "\n".join(lines).rstrip() + "\n"

    def _summary_line_for_step(self, archetype: str, output: dict) -> str:
        if archetype == "builder":
            return self._truncate_text(output.get("attempted") or output.get("summary"), 280) or "none"
        if archetype == "inspector":
            return self._truncate_text(output.get("tester_observations"), 280) or "none"
        if archetype == "gatekeeper":
            return self._truncate_text(output.get("decision_summary"), 280) or "none"
        if archetype == "custom":
            return self._truncate_text(output.get("summary") or output.get("handoff_note"), 280) or "none"
        return self._truncate_text(output.get("seed_question") or output.get("meta_note"), 280) or "none"

    def _runtime_role_key(self, role: dict) -> str:
        if role.get("id") == role.get("archetype"):
            return LEGACY_ROLE_BY_ARCHETYPE.get(role["archetype"], role["id"])
        return role["id"]
