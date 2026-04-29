from __future__ import annotations

from loopora.context_flow import build_iteration_summary, derive_latest_state
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
        archetype: str,
        output: dict,
        *,
        compiled_spec: dict,
        inspector_output: dict | None,
        evidence_context: dict | None = None,
        current_evidence_id: str = "",
    ) -> dict:
        if archetype == "inspector":
            return self._enrich_tester_result(output)
        if archetype == "gatekeeper":
            gatekeeper_output = self._coerce_gatekeeper_output(
                output,
                evidence_context=evidence_context,
                current_evidence_id=current_evidence_id,
            )
            return self._enrich_verifier_result(gatekeeper_output, compiled_spec, inspector_output or {})
        return dict(output)

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
        known_evidence_by_id = {
            str(item.get("id") or "").strip(): item
            for item in list((evidence_context or {}).get("items") or [])
            if isinstance(item, dict) and str(item.get("id") or "").strip()
        }
        known_evidence_ids = {
            str(item.get("id") or "").strip()
            for item in list((evidence_context or {}).get("items") or [])
            if isinstance(item, dict) and str(item.get("id") or "").strip()
        }
        known_evidence_ids.update(_string_list((evidence_context or {}).get("known_ids")))
        current_evidence_id = str(current_evidence_id or "").strip()
        if current_evidence_id:
            evidence_refs = [current_evidence_id if item == "self" else item for item in evidence_refs]
        metric_scores = result.get("metric_scores")
        if not isinstance(metric_scores, dict):
            metric_scores = {}
            for metric in list(result.get("metrics", [])):
                name = str(metric.get("name", "")).strip()
                if not name:
                    continue
                metric_scores[name] = {
                    "value": metric.get("value"),
                    "threshold": metric.get("threshold"),
                    "passed": bool(metric.get("passed")),
                }
        composite_score = result.get("composite_score")
        if composite_score is None:
            quality_metric = metric_scores.get("quality_score")
            composite_score = (
                quality_metric.get("value")
                if isinstance(quality_metric, dict)
                else (1.0 if result.get("passed") else 0.0)
            )
        if not result.get("metrics"):
            result["metrics"] = [
                {
                    "name": name,
                    "value": value.get("value"),
                    "threshold": value.get("threshold"),
                    "passed": value.get("passed"),
                }
                for name, value in metric_scores.items()
            ]
        result["passed"] = bool(result.get("passed", False))
        invalid_refs = [
            item for item in evidence_refs if item != current_evidence_id and item not in known_evidence_ids
        ]
        concrete_claims = [item for item in evidence_claims if len(item) >= 24]
        if result["passed"]:
            has_measured_evidence = _has_measured_gate_evidence(metric_scores, result.get("metrics"))
            if not evidence_refs and current_evidence_id and concrete_claims and has_measured_evidence:
                evidence_refs = [current_evidence_id]
            invalid_refs = [
                item for item in evidence_refs if item != current_evidence_id and item not in known_evidence_ids
            ]
            supporting_refs = [
                item
                for item in evidence_refs
                if item != current_evidence_id
                and item in known_evidence_ids
                and str(known_evidence_by_id.get(item, {}).get("archetype") or "").strip().lower() != "gatekeeper"
            ]
            if invalid_refs:
                blocking_issues.append(
                    "gatekeeper_evidence_refs_unknown: "
                    + ", ".join(invalid_refs[:4])
                    + ("..." if len(invalid_refs) > 4 else "")
                )
                result["passed"] = False
            elif not evidence_refs:
                blocking_issues.append("gatekeeper_pass_requires_evidence_refs")
                result["passed"] = False
            elif not supporting_refs and not has_measured_evidence:
                blocking_issues.append("gatekeeper_pass_requires_upstream_or_measured_evidence")
                result["passed"] = False
        if not result["passed"] and float(composite_score or 0.0) >= 0.9 and blocking_issues:
            composite_score = 0.89
        result["decision_summary"] = str(result.get("decision_summary") or "").strip() or (
            "The workflow still needs more evidence." if not result["passed"] else "All checks passed."
        )
        result["feedback_to_builder"] = feedback
        result["feedback_to_generator"] = feedback
        result["blocking_issues"] = blocking_issues
        result["hard_constraint_violations"] = blocking_issues
        result["metric_scores"] = metric_scores
        result["composite_score"] = float(composite_score or 0.0)
        result["evidence_refs"] = evidence_refs
        result["evidence_claims"] = evidence_claims
        result["evidence_gate_status"] = "passed" if result["passed"] else ("blocked" if blocking_issues else "not_passed")
        result.setdefault("failed_check_ids", [])
        result.setdefault("priority_failures", [])
        return result

    def _write_step_outputs(
        self,
        layout: RunArtifactLayout,
        iter_id: int,
        step: dict,
        step_order: int,
        role: dict,
        runtime_role: str,
        output: dict,
        handoff: dict,
    ) -> None:
        step_dir = layout.step_dir(iter_id, step_order, step["id"])
        step_dir.mkdir(parents=True, exist_ok=True)
        write_json(layout.step_output_normalized_path(iter_id, step_order, step["id"]), output)
        write_json(
            layout.step_metadata_path(iter_id, step_order, step["id"]),
            {
                "step_id": step["id"],
                "step_order": step_order,
                "role_id": role["id"],
                "role_name": role["name"],
                "runtime_role": runtime_role,
                "archetype": role["archetype"],
                "iter": iter_id,
                "inherit_session": bool(step.get("inherit_session")),
                "extra_cli_args": str(step.get("extra_cli_args") or ""),
                "parallel_group": str(step.get("parallel_group") or ""),
                "inputs": dict(step.get("inputs") or {}),
                "action_policy": dict(step.get("action_policy") or {}),
                "control_id": str(step.get("control_id") or ""),
                "control": dict(step.get("control") or {}) if isinstance(step.get("control"), dict) else {},
            },
        )
        write_json(layout.step_handoff_path(iter_id, step_order, step["id"]), handoff)

        for alias_path in layout.legacy_role_output_paths(role["archetype"]):
            write_json(alias_path, output)

    def _persist_iteration_context(
        self,
        *,
        layout: RunArtifactLayout,
        run_id: str,
        iter_id: int,
        step_results: list[dict],
        stagnation: dict,
        previous_composite: float | None,
    ) -> dict:
        iteration_summary = build_iteration_summary(
            layout=layout,
            iter_id=iter_id,
            step_results=step_results,
            stagnation=stagnation,
            previous_composite=previous_composite,
            timestamp=utc_now(),
        )
        write_json(layout.iteration_summary_path(iter_id), iteration_summary)
        append_jsonl_with_mirrors(layout.timeline_iterations_path, iteration_summary)
        latest_state = derive_latest_state(read_json(layout.latest_state_path), iteration_summary)
        write_json(layout.latest_iteration_summary_path, iteration_summary)
        write_json(layout.latest_state_path, latest_state)
        self.repository.append_event(
            run_id,
            "iteration_summary_written",
            {
                "iter": iter_id,
                "summary_path": layout.relative(layout.iteration_summary_path(iter_id)),
                "latest_state_path": layout.relative(layout.latest_state_path),
                "executed_step_count": len(step_results),
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
        run: dict,
        workflow: dict,
        compiled_spec: dict,
        iter_id: int,
        step_results: list[dict],
        stagnation: dict,
        *,
        exhausted: bool,
        previous_composite: float | None,
    ) -> str:
        gatekeeper_output = next(
            (item["output"] for item in reversed(step_results) if item["role"]["archetype"] == "gatekeeper"),
            {},
        )
        completion_mode = str(run.get("completion_mode", "gatekeeper")).strip().lower() or "gatekeeper"
        status_line = (
            "Planned rounds completed."
            if exhausted and completion_mode == "rounds"
            else "Max iterations exhausted."
            if exhausted
            else "Still iterating."
        )
        if gatekeeper_output.get("passed") and completion_mode == "gatekeeper":
            status_line = "All checks passed in this iteration."
        elif gatekeeper_output.get("passed"):
            status_line = "GateKeeper passed in this iteration, but the run stays in round-based mode."
        delta_text = (
            f"`{round(gatekeeper_output['composite_score'] - previous_composite, 6):+}`"
            if previous_composite is not None and gatekeeper_output.get("composite_score") is not None
            else "`n/a`"
        )
        lines = [
            "# Loopora Run Summary",
            "",
            f"- Workdir: `{run['workdir']}`",
            f"- Iteration: `{iter_id + 1 if iter_id >= 0 else 0}`",
            f"- Workflow preset: `{workflow.get('preset') or 'custom'}`",
            f"- Check mode: `{compiled_spec.get('check_mode', 'specified')}`",
            f"- Check count: `{len(compiled_spec.get('checks', []))}`",
            f"- Completion mode: `{completion_mode}`",
            f"- Iteration interval seconds: `{run.get('iteration_interval_seconds', 0.0)}`",
            f"- Composite score: `{gatekeeper_output.get('composite_score', 'n/a')}`",
            f"- Score delta vs previous iteration: {delta_text}",
            f"- Passed: `{gatekeeper_output.get('passed', False)}`",
            f"- Stagnation mode: `{stagnation.get('stagnation_mode', 'none')}`",
            "",
            status_line,
        ]
        for item in step_results:
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
