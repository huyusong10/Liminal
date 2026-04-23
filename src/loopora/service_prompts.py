from __future__ import annotations

import json
from pathlib import Path

from loopora.specs import resolve_role_note


class ServiceRunPromptMixin:
    def _check_planner_prompt(self, compiled_spec: dict) -> str:
        constraints = compiled_spec.get("constraints") or "No explicit constraints were provided."
        return (
            "You are the Check Planner inside Loopora.\n"
            "The spec did not provide explicit checks, so you must derive a frozen exploratory set for this run.\n"
            "Inspect the current workdir, stay close to the stated goal, and do not invent unrelated requirements.\n"
            "Generate 3 to 5 independently judgeable checks. Prefer concise titles and practical evaluation criteria.\n"
            "Do not edit files.\n"
            f"Goal:\n{compiled_spec['goal']}\n\n"
            f"Constraints:\n{constraints}\n\n"
            "Return JSON with `checks` and `generation_notes`. Each check must include `title`, `details`, `when`, `expect`, and `fail_if`. "
            "Use empty strings only when a field truly cannot be made more specific."
        )

    def _role_note_block(self, compiled_spec: dict, *, role_name: str, archetype: str) -> str:
        role_note = resolve_role_note(compiled_spec, role_name=role_name, archetype=archetype)
        if not role_note:
            return ""
        return f"Role notes for this role:\n{role_note}\n\n"

    def _generator_prompt(
        self,
        compiled_spec: dict,
        workdir: Path,
        iter_id: int,
        mode: str,
        *,
        previous_generator_result: dict | None = None,
        previous_tester_result: dict | None = None,
        previous_verifier_result: dict | None = None,
        previous_challenger_result: dict | None = None,
    ) -> str:
        constraints = compiled_spec.get("constraints") or "No explicit constraints were provided."
        role_note = self._role_note_block(compiled_spec, role_name="Builder", archetype="builder")
        bootstrap_guidance = ""
        action_guidance = (
            "This role must end with a concrete attempt, not only repo inspection.\n"
            "Once you have enough context to act, prefer making a focused change and/or running the most relevant existing verification, build, benchmark, or diagnosis command in the workdir.\n"
            "If the repository already contains a project-owned script that directly measures the goal, prefer using it to establish evidence in this iteration.\n"
            "If you launch a long-running project-owned command, do not wait idly for stdout alone. While it runs, inspect fresh status files, logs, reports, and intermediate artifacts so you can tell healthy progress from a harness defect.\n"
            "If those observations reveal a real process defect in the owned evaluation flow (for example stale progress snapshots, ineffective timeouts, misleading status reporting, or broken report generation), fixing that defect is in scope before the benchmark fully finishes.\n"
            "For benchmark-driven goals, prefer one real end-to-end run plus targeted harness fixes over many ad hoc spot checks.\n"
            "Do not spend the whole turn only reading files unless you are blocked by missing information that truly cannot be resolved any other way.\n\n"
        )
        if iter_id == 0 and self._is_bootstrap_workspace(workdir):
            bootstrap_guidance = (
                "Workspace state:\n"
                "Only the spec is present right now, so this iteration should bootstrap the first implementation.\n"
                "Create the smallest runnable prototype in this round instead of spending the whole turn on planning.\n"
                "Because the workspace is essentially empty, it is safe to add the first app files now; this is not permission to wipe or reset a non-empty project.\n"
                "Prefer a minimal static entry point plus tiny supporting files when needed.\n\n"
            )
        prior_iteration_feedback = self._generator_prior_iteration_feedback(
            iter_id,
            previous_generator_result=previous_generator_result,
            previous_tester_result=previous_tester_result,
            previous_verifier_result=previous_verifier_result,
            previous_challenger_result=previous_challenger_result,
        )
        return (
            "You are the Generator role inside Loopora.\n"
            "Goal: improve the workspace to satisfy the spec with one coherent change direction.\n"
            f"Iteration: {iter_id}\n"
            f"Mode: {mode}\n"
            f"Check mode: {compiled_spec.get('check_mode', 'specified')}\n"
            "You may edit files inside the workdir. Do not write into .loopora except for explicitly requested outputs.\n"
            "Treat existing non-.loopora files as user-owned. Never wipe the whole workdir, bulk-delete existing files, or reset the project from scratch.\n"
            "Prefer targeted in-place edits and additive changes. Delete a file only when that deletion is narrowly necessary to your change.\n"
            f"{action_guidance}"
            f"{bootstrap_guidance}"
            f"{prior_iteration_feedback}"
            f"Spec goal:\n{compiled_spec['goal']}\n\n"
            f"Checks:\n{self._render_checks(compiled_spec['checks'])}\n\n"
            f"Constraints:\n{constraints}\n\n"
            f"{role_note}"
            "Return JSON with attempted, abandoned, assumption, summary, and changed_files."
        )

    def _generator_prior_iteration_feedback(
        self,
        iter_id: int,
        *,
        previous_generator_result: dict | None = None,
        previous_tester_result: dict | None = None,
        previous_verifier_result: dict | None = None,
        previous_challenger_result: dict | None = None,
    ) -> str:
        if iter_id <= 0:
            return ""
        lines = ["Previous iteration evidence:"]
        if previous_generator_result:
            lines.append(
                f"- Last attempted: {self._truncate_text(previous_generator_result.get('attempted') or previous_generator_result.get('summary'), 220) or 'none'}"
            )
        if previous_tester_result:
            failed_items = list(previous_tester_result.get("failed_items", []))
            lines.append(
                f"- Tester observations: {self._truncate_text(previous_tester_result.get('tester_observations'), 220) or 'none'}"
            )
            lines.append(f"- Non-passing items last round: {self._format_failure_refs(failed_items)}")
        if previous_verifier_result:
            lines.append(
                f"- Verifier decision: {self._truncate_text(previous_verifier_result.get('decision_summary'), 240) or 'none'}"
            )
            lines.append(
                f"- Previous composite score: `{previous_verifier_result.get('composite_score', 'n/a')}`"
            )
            lines.append(
                "- Failed checks last round: "
                f"{self._format_inline_code_list(list(previous_verifier_result.get('failed_check_titles', []) or previous_verifier_result.get('failed_check_ids', [])), empty='none', limit=4)}"
            )
            lines.append(
                "- Next actions from verifier: "
                f"{self._format_inline_code_list(list(previous_verifier_result.get('next_actions', [])), empty='none', limit=4)}"
            )
        if previous_challenger_result:
            lines.append(
                f"- Challenger recommended shift: {self._truncate_text((previous_challenger_result.get('analysis') or {}).get('recommended_shift'), 220) or 'none'}"
            )
            lines.append(
                f"- Challenger seed question: {self._truncate_text(previous_challenger_result.get('seed_question'), 220) or 'none'}"
            )
        lines.append("Use this evidence as your starting point for the next focused improvement. Do not restart from scratch.")
        return "\n".join(lines) + "\n\n"

    def _tester_prompt(self, compiled_spec: dict, iter_id: int, mode: str) -> str:
        checks = json.dumps(compiled_spec["checks"], ensure_ascii=False, indent=2)
        role_note = self._role_note_block(compiled_spec, role_name="Inspector", archetype="inspector")
        return (
            "You are the Tester role inside Loopora.\n"
            "Inspect the workdir, run the most relevant commands, and evaluate the listed checks.\n"
            "Do not edit source files.\n"
            "Keep notes concise and evidence-focused. Prefer concrete commands, files, and observed outputs over restating the whole spec.\n"
            "When fresh project-owned benchmark artifacts already exist, inspect them first and reuse them as primary evidence before rerunning an expensive end-to-end flow.\n"
            "If a long-running evaluation appears stalled, confirm that with live status files, logs, or preserved artifacts instead of guessing from silent stdout alone.\n"
            f"Iteration: {iter_id}\n"
            f"Mode: {mode}\n"
            f"Checks:\n{checks}\n\n"
            f"{role_note}"
            "For every `check_results` item and every `dynamic_checks` item, return `id`, `title`, `status`, and `notes`.\n"
            "Return JSON with execution_summary, check_results, dynamic_checks, and tester_observations."
        )

    def _verifier_prompt(self, compiled_spec: dict, tester_output: dict, iter_id: int, mode: str) -> str:
        constraints = compiled_spec.get("constraints") or "No explicit constraints were provided."
        role_note = self._role_note_block(compiled_spec, role_name="GateKeeper", archetype="gatekeeper")
        return (
            "You are the Verifier role inside Loopora.\n"
            "Judge the tester output conservatively against the goal, checks, and constraints.\n"
            "Keep the verdict concise and tied to direct evidence. Do not rewrite the whole spec as policy prose.\n"
            "When the main evidence comes from a project-owned benchmark or harness, treat those artifacts as primary evidence.\n"
            "Distinguish product or knowledge failures from harness-process defects, and surface harness defects as first-class failures when they block trustworthy evaluation.\n"
            f"Iteration: {iter_id}\n"
            f"Mode: {mode}\n"
            f"Goal:\n{compiled_spec['goal']}\n\n"
            f"Checks:\n{self._render_checks(compiled_spec['checks'])}\n\n"
            f"Constraints:\n{constraints}\n\n"
            f"{role_note}"
            f"Tester output:\n{json.dumps(tester_output, ensure_ascii=False, indent=2)}\n\n"
            "Inside `metric_scores`, provide exactly `check_pass_rate` and `quality_score`, each with `value`, `threshold`, and `passed`.\n"
            "For every `priority_failures` item, return `error_code` and `summary`.\n"
            "Return JSON with passed, composite_score, metric_scores, hard_constraint_violations, "
            "failed_check_ids, priority_failures, and feedback_to_generator."
        )

    def _challenger_prompt(self, compiled_spec: dict, stagnation: dict, iter_id: int) -> str:
        constraints = compiled_spec.get("constraints") or "No explicit constraints were provided."
        role_note = self._role_note_block(compiled_spec, role_name="Guide", archetype="guide")
        return (
            "You are the Challenger role inside Loopora.\n"
            "Suggest the smallest high-leverage direction change when progress stalls.\n"
            f"Iteration: {iter_id}\n"
            f"Spec goal:\n{compiled_spec['goal']}\n\n"
            f"Checks:\n{self._render_checks(compiled_spec['checks'])}\n\n"
            f"Constraints:\n{constraints}\n\n"
            f"{role_note}"
            f"Stagnation state:\n{json.dumps(stagnation, ensure_ascii=False, indent=2)}\n\n"
            "Inside `analysis`, return `stagnation_pattern`, `recommended_shift`, and `risk_note`.\n"
            "Return JSON with created_at_iter, mode, consumed, analysis, seed_question, and meta_note."
        )

    def _normalize_generated_checks(self, checks: list[dict]) -> list[dict]:
        normalized = []
        for index, raw_check in enumerate(checks, start=1):
            title = str(raw_check.get("title", "")).strip() or f"Exploratory check {index}"
            when = str(raw_check.get("when", "")).strip()
            expect = str(raw_check.get("expect", "")).strip()
            fail_if = str(raw_check.get("fail_if", "")).strip()
            details = str(raw_check.get("details", "")).strip()
            if not details:
                parts = []
                if when:
                    parts.append(f"When: {when}")
                if expect:
                    parts.append(f"Expect: {expect}")
                if fail_if:
                    parts.append(f"Fail if: {fail_if}")
                details = "\n".join(parts).strip()
            normalized.append(
                {
                    "id": f"check_{index:03d}",
                    "title": title,
                    "details": details or "Auto-generated exploratory check.",
                    "when": when,
                    "expect": expect,
                    "fail_if": fail_if,
                    "source": "auto_generated",
                }
            )
        return normalized

    def _render_checks(self, checks: list[dict]) -> str:
        return json.dumps(checks, ensure_ascii=False, indent=2)


GENERATOR_SCHEMA = {
    "type": "object",
    "required": ["attempted", "abandoned", "assumption", "summary", "changed_files"],
    "properties": {
        "attempted": {"type": "string"},
        "abandoned": {"type": "string"},
        "assumption": {"type": "string"},
        "summary": {"type": "string"},
        "changed_files": {"type": "array", "items": {"type": "string"}},
    },
    "additionalProperties": False,
}

CHECK_PLANNER_SCHEMA = {
    "type": "object",
    "required": ["checks", "generation_notes"],
    "properties": {
        "checks": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["title", "details", "when", "expect", "fail_if"],
                "properties": {
                    "title": {"type": "string"},
                    "details": {"type": "string"},
                    "when": {"type": "string"},
                    "expect": {"type": "string"},
                    "fail_if": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
        "generation_notes": {"type": "string"},
    },
    "additionalProperties": False,
}

TESTER_SCHEMA = {
    "type": "object",
    "required": ["execution_summary", "check_results", "dynamic_checks", "tester_observations"],
    "properties": {
        "execution_summary": {
            "type": "object",
            "required": ["total_checks", "passed", "failed", "errored", "total_duration_ms"],
            "properties": {
                "total_checks": {"type": "integer"},
                "passed": {"type": "integer"},
                "failed": {"type": "integer"},
                "errored": {"type": "integer"},
                "total_duration_ms": {"type": "integer"},
            },
            "additionalProperties": False,
        },
        "check_results": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "title", "status", "notes"],
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "status": {"type": "string", "enum": ["passed", "failed", "errored", "skipped"]},
                    "notes": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
        "dynamic_checks": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "title", "status", "notes"],
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "status": {"type": "string", "enum": ["passed", "failed", "errored", "skipped"]},
                    "notes": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
        "tester_observations": {"type": "string"},
    },
    "additionalProperties": False,
}

VERIFIER_SCHEMA = {
    "type": "object",
    "required": [
        "passed",
        "decision_summary",
        "composite_score",
        "metrics",
        "metric_scores",
        "blocking_issues",
        "hard_constraint_violations",
        "failed_check_ids",
        "priority_failures",
        "feedback_to_builder",
        "feedback_to_generator",
    ],
    "properties": {
        "passed": {"type": "boolean"},
        "decision_summary": {"type": "string"},
        "composite_score": {"type": "number"},
        "metrics": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "value", "threshold", "passed"],
                "properties": {
                    "name": {"type": "string"},
                    "value": {"type": "number"},
                    "threshold": {"type": "number"},
                    "passed": {"type": "boolean"},
                },
                "additionalProperties": False,
            },
        },
        "metric_scores": {
            "type": "object",
            "required": ["check_pass_rate", "quality_score"],
            "properties": {
                "check_pass_rate": {
                    "type": "object",
                    "required": ["value", "threshold", "passed"],
                    "properties": {
                        "value": {"type": "number"},
                        "threshold": {"type": "number"},
                        "passed": {"type": "boolean"},
                    },
                    "additionalProperties": False,
                },
                "quality_score": {
                    "type": "object",
                    "required": ["value", "threshold", "passed"],
                    "properties": {
                        "value": {"type": "number"},
                        "threshold": {"type": "number"},
                        "passed": {"type": "boolean"},
                    },
                    "additionalProperties": False,
                },
            },
            "additionalProperties": False,
        },
        "blocking_issues": {"type": "array", "items": {"type": "string"}},
        "hard_constraint_violations": {"type": "array", "items": {"type": "string"}},
        "failed_check_ids": {"type": "array", "items": {"type": "string"}},
        "priority_failures": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["error_code", "summary"],
                "properties": {
                    "error_code": {"type": "string"},
                    "summary": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
        "feedback_to_builder": {"type": "string"},
        "feedback_to_generator": {"type": "string"},
    },
    "additionalProperties": False,
}

CHALLENGER_SCHEMA = {
    "type": "object",
    "required": ["created_at_iter", "mode", "consumed", "analysis", "seed_question", "meta_note"],
    "properties": {
        "created_at_iter": {"type": "integer"},
        "mode": {"type": "string"},
        "consumed": {"type": "boolean"},
        "analysis": {
            "type": "object",
            "required": ["stagnation_pattern", "recommended_shift", "risk_note"],
            "properties": {
                "stagnation_pattern": {"type": "string"},
                "recommended_shift": {"type": "string"},
                "risk_note": {"type": "string"},
            },
            "additionalProperties": False,
        },
        "seed_question": {"type": "string"},
        "meta_note": {"type": "string"},
    },
    "additionalProperties": False,
}

CUSTOM_SCHEMA = {
    "type": "object",
    "required": [
        "status",
        "summary",
        "blocking_items",
        "recommended_next_action",
        "observations",
        "recommendations",
        "risks",
        "handoff_note",
    ],
    "properties": {
        "status": {"type": "string"},
        "summary": {"type": "string"},
        "blocking_items": {"type": "array", "items": {"type": "string"}},
        "recommended_next_action": {"type": "string"},
        "observations": {"type": "array", "items": {"type": "string"}},
        "recommendations": {"type": "array", "items": {"type": "string"}},
        "risks": {"type": "array", "items": {"type": "string"}},
        "handoff_note": {"type": "string"},
    },
    "additionalProperties": False,
}

BUILDER_SCHEMA = GENERATOR_SCHEMA
INSPECTOR_SCHEMA = TESTER_SCHEMA
GATEKEEPER_SCHEMA = VERIFIER_SCHEMA
GUIDE_SCHEMA = CHALLENGER_SCHEMA
