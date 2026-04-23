from __future__ import annotations

from loopora.utils import utc_now


class ServiceIterationReportingMixin:
    @staticmethod
    def _empty_status_counts() -> dict[str, int]:
        return {"passed": 0, "failed": 0, "errored": 0, "skipped": 0}

    def _count_statuses(self, items: list[dict]) -> dict[str, int]:
        counts = self._empty_status_counts()
        for item in items:
            status = str(item.get("status", "")).strip().lower()
            if status in counts:
                counts[status] += 1
        return counts

    def _collect_non_passing_items(self, items: list[dict], *, source: str) -> list[dict]:
        failures = []
        for item in items:
            status = str(item.get("status", "")).strip().lower()
            if status == "passed":
                continue
            failures.append(
                {
                    "id": str(item.get("id", "")).strip(),
                    "title": str(item.get("title", "")).strip(),
                    "status": status or "unknown",
                    "source": source,
                    "notes": self._truncate_text(str(item.get("notes", "")).strip(), max_length=280),
                }
            )
        return failures

    def _enrich_tester_result(self, tester_result: dict) -> dict:
        result = dict(tester_result)
        check_results = list(result.get("check_results", []))
        dynamic_checks = list(result.get("dynamic_checks", []))
        check_counts = self._count_statuses(check_results)
        dynamic_counts = self._count_statuses(dynamic_checks)
        overall_counts = {
            key: check_counts.get(key, 0) + dynamic_counts.get(key, 0)
            for key in self._empty_status_counts()
        }
        failed_items = self._collect_non_passing_items(check_results, source="specified")
        failed_items.extend(self._collect_non_passing_items(dynamic_checks, source="dynamic"))
        result["status_counts"] = {
            "check_results": check_counts,
            "dynamic_checks": dynamic_counts,
            "overall": overall_counts,
        }
        result["failed_items"] = failed_items
        result["specified_check_failures"] = [item["id"] for item in failed_items if item["source"] == "specified"]
        result["dynamic_check_failures"] = [item["id"] for item in failed_items if item["source"] == "dynamic"]
        return result

    def _build_decision_summary(self, verifier_result: dict, tester_result: dict) -> str:
        reasons: list[str] = []
        failed_check_titles = list(verifier_result.get("failed_check_titles", []))
        dynamic_failures = list(tester_result.get("dynamic_check_failures", []))
        hard_constraint_violations = list(verifier_result.get("hard_constraint_violations", []))
        failing_metrics = list(verifier_result.get("failing_metrics", []))
        priority_failures = list(verifier_result.get("priority_failures", []))
        if failed_check_titles:
            reasons.append(
                "specified checks still failing: "
                + ", ".join(failed_check_titles[:3])
                + ("..." if len(failed_check_titles) > 3 else "")
            )
        if dynamic_failures:
            reasons.append(
                f"{len(dynamic_failures)} dynamic check failure"
                + ("s remain" if len(dynamic_failures) != 1 else " remains")
            )
        if hard_constraint_violations:
            reasons.append(
                f"{len(hard_constraint_violations)} hard constraint violation"
                + ("s" if len(hard_constraint_violations) != 1 else "")
            )
        if failing_metrics:
            metric_names = [str(item.get("name", "")).strip() for item in failing_metrics if item.get("name")]
            if metric_names:
                reasons.append("failing metrics: " + ", ".join(metric_names))
        if priority_failures and not reasons:
            reasons.append(
                "priority failures reported: "
                + ", ".join(self._truncate_text(item.get("summary"), 120) for item in priority_failures[:2])
            )
        if verifier_result.get("passed"):
            return "All specified and dynamic checks passed with no blocking constraint violations."
        if not reasons:
            return "The run is not yet passing because one or more checks or metrics remain below threshold."
        return "The run is not yet passing because " + "; ".join(reasons) + "."

    def _split_action_hints(self, feedback: str | None) -> list[str]:
        text = str(feedback or "").strip()
        if not text:
            return []
        hints = []
        for raw_line in text.splitlines():
            cleaned = raw_line.strip().lstrip("-*").strip()
            if cleaned:
                hints.append(cleaned)
        return hints[:5] if hints else [text]

    def _enrich_verifier_result(self, verifier_result: dict, compiled_spec: dict, tester_result: dict) -> dict:
        result = dict(verifier_result)
        check_title_map = {str(check.get("id", "")).strip(): str(check.get("title", "")).strip() for check in compiled_spec.get("checks", [])}
        failed_check_titles = [check_title_map.get(check_id, check_id) for check_id in result.get("failed_check_ids", [])]
        failing_metrics = []
        for name, metric in (result.get("metric_scores") or {}).items():
            if metric.get("passed"):
                continue
            failing_metrics.append(
                {
                    "name": name,
                    "value": metric.get("value"),
                    "threshold": metric.get("threshold"),
                }
            )
        result["failed_check_titles"] = failed_check_titles
        result["failing_metrics"] = failing_metrics
        result["hard_constraint_violation_count"] = len(result.get("hard_constraint_violations", []))
        result["priority_failure_count"] = len(result.get("priority_failures", []))
        result["decision_summary"] = self._build_decision_summary(result, tester_result)
        result["next_actions"] = self._split_action_hints(result.get("feedback_to_generator"))
        return result

    def _format_inline_code_list(self, items: list[str], *, empty: str = "none", limit: int = 5) -> str:
        values = [str(item).strip() for item in items if str(item).strip()]
        if not values:
            return empty
        visible = [f"`{item}`" for item in values[:limit]]
        if len(values) > limit:
            visible.append(f"`+{len(values) - limit} more`")
        return ", ".join(visible)

    def _format_failure_refs(self, items: list[dict], *, limit: int = 4) -> str:
        if not items:
            return "none"
        visible = []
        for item in items[:limit]:
            label = item.get("title") or item.get("id") or "unknown"
            source = item.get("source")
            if source == "dynamic":
                label = f"{label} [dynamic]"
            visible.append(f"`{label}`")
        if len(items) > limit:
            visible.append(f"`+{len(items) - limit} more`")
        return ", ".join(visible)

    def _format_metric_refs(self, metrics: list[dict], *, limit: int = 4) -> str:
        if not metrics:
            return "none"
        visible = []
        for metric in metrics[:limit]:
            name = str(metric.get("name", "")).strip() or "unknown_metric"
            value = metric.get("value")
            threshold = metric.get("threshold")
            if value is None or threshold is None:
                visible.append(f"`{name}`")
            else:
                visible.append(f"`{name}={value}` (threshold `{threshold}`)")
        if len(metrics) > limit:
            visible.append(f"`+{len(metrics) - limit} more`")
        return ", ".join(visible)

    def _build_generator_log_entry(self, iter_id: int, generator_result: dict, mode: str) -> dict:
        return {
            "phase": "generator",
            "iter": iter_id,
            "timestamp": utc_now(),
            "mode": mode,
            "attempted": generator_result.get("attempted", ""),
            "summary": generator_result.get("summary", ""),
            "assumption": generator_result.get("assumption", ""),
            "abandoned": generator_result.get("abandoned", ""),
            "changed_files": list(generator_result.get("changed_files", [])),
        }

    def _build_iteration_log_entry(
        self,
        iter_id: int,
        generator_result: dict,
        tester_result: dict,
        verifier_result: dict,
        stagnation: dict,
        generator_mode: str,
        tester_mode: str,
        verifier_mode: str,
        *,
        previous_composite: float | None,
        challenger_result: dict | None = None,
    ) -> dict:
        entry = {
            "phase": "complete",
            "iter": iter_id,
            "timestamp": utc_now(),
            "modes": {
                "generator": generator_mode,
                "tester": tester_mode,
                "verifier": verifier_mode,
            },
            "score": {
                "composite": verifier_result.get("composite_score"),
                "delta": round(verifier_result["composite_score"] - previous_composite, 6)
                if previous_composite is not None
                else None,
                "passed": verifier_result.get("passed"),
            },
            "generator": {
                "attempted": generator_result.get("attempted", ""),
                "summary": generator_result.get("summary", ""),
                "assumption": generator_result.get("assumption", ""),
                "abandoned": generator_result.get("abandoned", ""),
                "changed_files": list(generator_result.get("changed_files", [])),
            },
            "tester": {
                "execution_summary": dict(tester_result.get("execution_summary", {})),
                "status_counts": dict(tester_result.get("status_counts", {})),
                "failed_items": list(tester_result.get("failed_items", [])),
                "tester_observations": tester_result.get("tester_observations", ""),
            },
            "verifier": {
                "passed": verifier_result.get("passed"),
                "decision_summary": verifier_result.get("decision_summary", ""),
                "failed_check_ids": list(verifier_result.get("failed_check_ids", [])),
                "failed_check_titles": list(verifier_result.get("failed_check_titles", [])),
                "failing_metrics": list(verifier_result.get("failing_metrics", [])),
                "hard_constraint_violations": list(verifier_result.get("hard_constraint_violations", [])),
                "priority_failures": list(verifier_result.get("priority_failures", [])),
                "feedback_to_generator": verifier_result.get("feedback_to_generator", ""),
                "next_actions": list(verifier_result.get("next_actions", [])),
            },
            "stagnation": {
                "mode": stagnation.get("stagnation_mode", "none"),
                "recent_composites": list(stagnation.get("recent_composites", [])),
                "recent_deltas": list(stagnation.get("recent_deltas", [])),
                "consecutive_low_delta": stagnation.get("consecutive_low_delta", 0),
            },
        }
        if challenger_result is not None:
            entry["challenger"] = {
                "mode": challenger_result.get("mode"),
                "analysis": dict(challenger_result.get("analysis", {})),
                "seed_question": challenger_result.get("seed_question", ""),
                "meta_note": challenger_result.get("meta_note", ""),
            }
        return entry

    def _build_summary(
        self,
        run: dict,
        compiled_spec: dict,
        iter_id: int,
        generator_result: dict,
        tester_result: dict,
        verifier_result: dict,
        stagnation: dict,
        generator_mode: str,
        tester_mode: str,
        verifier_mode: str,
        exhausted: bool = False,
        previous_composite: float | None = None,
        challenger_result: dict | None = None,
    ) -> str:
        failed = verifier_result.get("failed_check_titles", verifier_result.get("failed_check_ids", []))
        completion_mode = str(run.get("completion_mode", "gatekeeper")).strip().lower() or "gatekeeper"
        if exhausted and completion_mode == "rounds":
            status_line = "Planned rounds completed."
        elif exhausted:
            status_line = "Max iterations exhausted."
        elif verifier_result["passed"] and completion_mode == "gatekeeper":
            status_line = "All checks passed in this iteration."
        elif verifier_result["passed"]:
            status_line = "Verifier passed in this iteration, but the run stays in round-based mode."
        else:
            status_line = "Still iterating."
        check_mode = compiled_spec.get("check_mode", "specified")
        overall_counts = tester_result.get("status_counts", {}).get("overall", self._empty_status_counts())
        dynamic_counts = tester_result.get("status_counts", {}).get("dynamic_checks", self._empty_status_counts())
        delta_text = (
            f"`{round(verifier_result['composite_score'] - previous_composite, 6):+}`"
            if previous_composite is not None
            else "`n/a`"
        )
        lines = [
            "# Loopora Run Summary",
            "",
            f"- Workdir: `{run['workdir']}`",
            f"- Iteration: `{iter_id + 1}`",
            f"- Check mode: `{check_mode}`",
            f"- Check count: `{len(compiled_spec.get('checks', []))}`",
            f"- Completion mode: `{completion_mode}`",
            f"- Iteration interval seconds: `{run.get('iteration_interval_seconds', 0.0)}`",
            f"- Composite score: `{verifier_result['composite_score']}`",
            f"- Score delta vs previous iteration: {delta_text}",
            f"- Passed: `{verifier_result['passed']}`",
            f"- Stagnation mode: `{stagnation.get('stagnation_mode', 'none')}`",
            f"- Failed checks: {self._format_inline_code_list(failed, empty='none', limit=4)}",
            (
                "- Role modes: "
                f"generator=`{generator_mode}`, tester=`{tester_mode}`, verifier=`{verifier_mode}`"
            ),
            "",
            status_line,
            "",
            "## Generator",
            f"- Attempted: {self._truncate_text(generator_result.get('attempted') or generator_result.get('summary'), 280) or 'none'}",
            f"- Changed files: {self._format_inline_code_list(list(generator_result.get('changed_files', [])))}",
            f"- Assumption: {self._truncate_text(generator_result.get('assumption'), 220) or 'none'}",
            f"- Abandoned: {self._truncate_text(generator_result.get('abandoned'), 220) or 'none'}",
            "",
            "## Tester",
            (
                "- Overall statuses: "
                f"passed=`{overall_counts['passed']}`, failed=`{overall_counts['failed']}`, "
                f"errored=`{overall_counts['errored']}`, skipped=`{overall_counts['skipped']}`"
            ),
            (
                "- Dynamic checks: "
                f"passed=`{dynamic_counts['passed']}`, failed=`{dynamic_counts['failed']}`, "
                f"errored=`{dynamic_counts['errored']}`, skipped=`{dynamic_counts['skipped']}`"
            ),
            f"- Non-passing items: {self._format_failure_refs(list(tester_result.get('failed_items', [])))}",
            f"- Observations: {self._truncate_text(tester_result.get('tester_observations'), 320) or 'none'}",
            "",
            "## Verifier",
            f"- Decision: {self._truncate_text(verifier_result.get('decision_summary'), 320) or 'none'}",
            f"- Failing metrics: {self._format_metric_refs(list(verifier_result.get('failing_metrics', [])))}",
            (
                "- Hard constraint violations: "
                f"{self._format_inline_code_list(list(verifier_result.get('hard_constraint_violations', [])), empty='none', limit=3)}"
            ),
            (
                "- Priority failures: "
                f"{self._format_inline_code_list([item.get('error_code', 'unknown') for item in verifier_result.get('priority_failures', [])], empty='none', limit=4)}"
            ),
            (
                "- Next actions: "
                f"{self._format_inline_code_list(list(verifier_result.get('next_actions', [])), empty='none', limit=3)}"
            ),
        ]
        if challenger_result is not None:
            lines.extend(
                [
                    "",
                    "## Challenger",
                    f"- Mode: `{challenger_result.get('mode', 'unknown')}`",
                    f"- Recommended shift: {self._truncate_text(challenger_result.get('analysis', {}).get('recommended_shift'), 220) or 'none'}",
                    f"- Seed question: {self._truncate_text(challenger_result.get('seed_question'), 220) or 'none'}",
                ]
            )
        lines.extend(
            [
                "",
                "## Artifacts",
                "- Inspect `tester_output.json`, `verifier_verdict.json`, `iteration_log.jsonl`, and `events.jsonl` for full details.",
            ]
        )
        return "\n".join(lines).rstrip() + "\n"
