from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path
from typing import Any, NotRequired, TypedDict

from loopora.branding import strip_run_summary_title
from loopora.evidence_coverage import load_or_build_evidence_coverage_projection, summarize_evidence_coverage_projection
from loopora.run_artifacts import RunArtifactLayout, read_jsonl
from loopora.service_bundle_control_summary import (
    build_execution_strategy_trace,
    build_judgment_tradeoff_trace,
    build_loop_fit_trace,
    build_runtime_local_governance_trace,
)
from loopora.structured_numbers import structured_non_negative_int
from loopora.task_verdicts import BUCKET_KEYS, normalize_task_verdict
from loopora.workflows import ARCHETYPES, display_name_for_archetype, normalize_role_display_name

LEGACY_RUNTIME_ROLE_TO_ARCHETYPE = {
    "generator": "builder",
    "tester": "inspector",
    "verifier": "gatekeeper",
    "challenger": "guide",
}
EVIDENCE_COVERAGE_COUNT_FIELDS = (
    "evidence_count",
    "check_count",
    "covered_check_count",
    "missing_check_count",
    "target_count",
    "covered_target_count",
    "weak_target_count",
    "missing_target_count",
    "blocked_target_count",
    "artifact_ref_count",
    "residual_risk_count",
)
EVIDENCE_COVERAGE_STATUSES = {"pending", "covered", "weak", "partial", "blocked", "legacy"}
EVIDENCE_MANIFEST_COUNT_FIELDS = (
    "claim_count",
    "artifact_backed_claim_count",
    "workspace_backed_claim_count",
    "direct_proof_claim_count",
    "workspace_artifact_claim_count",
    "run_artifact_claim_count",
    "ledger_only_claim_count",
    "unverified_claim_count",
)


class RunTakeawayProjection(TypedDict):
    run_status: str
    task_verdict: dict[str, Any]
    task_verdict_path: str
    judgment_contract: dict[str, Any]
    evidence_buckets: dict[str, Any]
    build_dir: str
    log_dir: str
    evidence_count: int
    evidence_coverage: dict[str, Any]
    evidence_manifest: dict[str, Any]
    iteration_count: int
    role_conclusion_count: int
    latest_display_iter: int | None
    latest_status: str
    latest_summary: str
    iterations: list[dict[str, Any]]
    source_event_id: NotRequired[int]


def display_iter(iter_value: object | None) -> int | None:
    if iter_value is None:
        return None
    normalized = _int_value(iter_value, default=None)
    if normalized is None:
        return None
    return normalized + 1


def strip_markdown(value: str | None) -> str:
    text = str(value or "")
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\[(.*?)\]\((.*?)\)", r"\1", text)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.M)
    text = re.sub(r"^\s*[-*+]\s*", "", text, flags=re.M)
    text = re.sub(r"^\s*\d+\.\s*", "", text, flags=re.M)
    return re.sub(r"\s+", " ", text).strip()


def truncate_text(value: str, max_length: int = 140) -> str:
    if len(value) <= max_length:
        return value
    return value[: max_length - 1].rstrip() + "…"


def summary_excerpt(summary_md: str | None) -> str:
    text = strip_markdown(summary_md)
    text = strip_run_summary_title(text)
    return truncate_text(text, max_length=170) if text else ""


def safe_read_json_file(path: Path) -> dict | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def clean_takeaway_text(value: object, *, max_length: int = 240) -> str:
    if not isinstance(value, str):
        return ""
    text = truncate_text(strip_markdown(value.strip()), max_length=max_length)
    return text.strip()


def _string_value(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def display_role_name(name: object, *, archetype: object = "", runtime_role: object = "") -> str:
    cleaned_name = _string_value(name)
    cleaned_runtime = _string_value(runtime_role).lower()
    cleaned_archetype = _string_value(archetype).lower() or LEGACY_RUNTIME_ROLE_TO_ARCHETYPE.get(cleaned_runtime, "")
    normalized_name = normalize_role_display_name(cleaned_name, cleaned_archetype)
    if normalized_name:
        return normalized_name
    if cleaned_archetype in ARCHETYPES:
        return display_name_for_archetype(cleaned_archetype, locale="en")
    return cleaned_name or cleaned_runtime or "-"


def normalize_takeaway_status(status: object) -> str:
    normalized = str(status or "").strip().lower()
    if normalized in {"passed", "completed", "blocked", "failed", "running", "advisory", "pending"}:
        return normalized
    if normalized in {"complete", "succeeded", "success"}:
        return "completed"
    if normalized in {"queued", "waiting", "idle"}:
        return "pending"
    return "pending"


def build_role_takeaway_from_handoff(handoff: Mapping[str, object], *, composite_score: object = None) -> dict:
    source = handoff.get("source") if isinstance(handoff.get("source"), Mapping) else {}
    iter_id = _int_value(source.get("iter"), default=0) or 0
    step_order = _int_value(source.get("step_order"), default=0) or 0
    role_name = display_role_name(
        source.get("role_name"),
        archetype=source.get("archetype"),
        runtime_role=source.get("runtime_role"),
    )
    blocking_items = [clean_takeaway_text(item, max_length=520) for item in _string_list(handoff.get("blocking_items"))]
    next_action = clean_takeaway_text(handoff.get("recommended_next_action"), max_length=520)
    step_id = _string_value(source.get("step_id"))
    return {
        "id": f"iter-{iter_id}-{step_id or role_name}",
        "step_id": step_id,
        "step_order": step_order,
        "role_name": role_name,
        "archetype": _string_value(source.get("archetype")).lower(),
        "status": normalize_takeaway_status(handoff.get("status")),
        "summary": clean_takeaway_text(handoff.get("summary"), max_length=1200),
        "blocking_item": " · ".join(blocking_items),
        "next_action": next_action,
        "evidence_refs": _string_list(handoff.get("evidence_refs")),
        "composite_score": composite_score,
    }


ACTIVE_TAKEAWAY_RUN_STATUSES = {"queued", "running", "awaiting_agent", "stopping"}


def build_structured_iteration_takeaways(run: dict, *, current_coverage: Mapping[str, Any] | None = None) -> list[dict]:
    runs_dir_value = str(run.get("runs_dir") or "").strip()
    if not runs_dir_value:
        return []
    runs_dir = Path(runs_dir_value)
    if not runs_dir.exists():
        return []

    summaries_by_iter = _iteration_summaries_by_iter(runs_dir)
    handoffs_by_iter = _iteration_handoffs_by_iter(runs_dir)
    iter_ids = sorted(set(summaries_by_iter) | set(handoffs_by_iter))
    current_iter_id = _current_iter_id(run)

    return [
        _build_structured_iteration_takeaway(
            run,
            iter_id=iter_id,
            summary_payload=summaries_by_iter.get(iter_id) or {},
            handoffs=sorted(
                handoffs_by_iter.get(iter_id, []),
                key=_handoff_step_order,
            ),
            current_coverage=current_coverage if iter_id == current_iter_id else None,
        )
        for iter_id in iter_ids
    ]


def _iteration_summaries_by_iter(runs_dir: Path) -> dict[int, dict]:
    summaries_by_iter: dict[int, dict] = {}
    for summary_path in sorted(runs_dir.glob("iterations/iter_*/summary.json")):
        summary_payload = safe_read_json_file(summary_path)
        if not summary_payload:
            continue
        iter_id = _int_value(summary_payload.get("iter"), default=-1)
        if iter_id >= 0:
            summaries_by_iter[iter_id] = summary_payload
    return summaries_by_iter


def _iteration_handoffs_by_iter(runs_dir: Path) -> dict[int, list[dict]]:
    handoffs_by_iter: dict[int, list[dict]] = defaultdict(list)
    for handoff_path in sorted(runs_dir.glob("iterations/iter_*/steps/*/handoff.json")):
        handoff_payload = safe_read_json_file(handoff_path)
        if not handoff_payload:
            continue
        source = handoff_payload.get("source") if isinstance(handoff_payload.get("source"), Mapping) else {}
        iter_id = _int_value(source.get("iter"), default=-1)
        if iter_id >= 0:
            handoffs_by_iter[iter_id].append(handoff_payload)
    return handoffs_by_iter


def _current_iter_id(run: Mapping[str, Any]) -> int | None:
    current_iter = run.get("current_iter")
    return _int_value(current_iter, default=None) if current_iter is not None else None


def _terminal_task_verdict(run: Mapping[str, Any]) -> Mapping[str, Any]:
    verdict = run.get("task_verdict") if isinstance(run.get("task_verdict"), Mapping) else run.get("task_verdict_json")
    return verdict if isinstance(verdict, Mapping) else {}


def _terminal_task_verdict_status_for_iteration(
    run: Mapping[str, Any],
    *,
    iter_id: int,
    current_iter_id: int | None,
) -> str:
    if current_iter_id != iter_id:
        return ""
    run_status = str(run.get("status") or "").strip().lower()
    if run_status in {"", "queued", "running", "awaiting_agent", "stopping"}:
        return ""
    verdict_status = str(_terminal_task_verdict(run).get("status") or "").strip().lower()
    return {
        "failed": "failed",
        "insufficient_evidence": "blocked",
        "passed_with_residual_risk": "completed",
        "passed": "passed",
    }.get(verdict_status, "")


def _terminal_task_verdict_summary_for_iteration(
    run: Mapping[str, Any],
    *,
    iter_id: int,
    current_iter_id: int | None,
) -> str:
    if current_iter_id != iter_id:
        return ""
    run_status = str(run.get("status") or "").strip().lower()
    if run_status in {"", "queued", "running", "awaiting_agent", "stopping"}:
        return ""
    verdict = _terminal_task_verdict(run)
    verdict_status = str(verdict.get("status") or "").strip().lower()
    summary = clean_takeaway_text(verdict.get("summary"), max_length=220)
    if verdict_status == "insufficient_evidence":
        return f"Task verdict insufficient evidence: {summary}" if summary else "Task verdict is still insufficient."
    if verdict_status == "failed":
        return f"Task verdict failed: {summary}" if summary else "Task verdict failed."
    if verdict_status == "passed_with_residual_risk":
        return f"Task verdict passed with residual risk: {summary}" if summary else "Task verdict passed with residual risk."
    return ""


def _int_value(value: object, *, default: int | None) -> int | None:
    if default is None:
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
        return None
    return structured_non_negative_int(value, default=default)


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _coverage_gap_list(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        target_id = str(item.get("target_id") or "").strip()
        if not target_id:
            continue
        rows.append(
            {
                "target_id": target_id,
                "kind": str(item.get("kind") or "").strip(),
                "source_section": str(item.get("source_section") or "").strip(),
                "status": str(item.get("status") or "missing").strip() or "missing",
                "required": item.get("required") is True,
                "reason": str(item.get("reason") or "").strip(),
                "text": str(item.get("text") or "").strip(),
                "evidence_refs": _string_list(item.get("evidence_refs")),
            }
        )
    return rows[:5]


def _handoff_step_order(handoff: Mapping[str, object]) -> int:
    source = handoff.get("source") if isinstance(handoff.get("source"), Mapping) else {}
    return structured_non_negative_int(source.get("step_order"))


def _build_structured_iteration_takeaway(
    run: Mapping[str, Any],
    *,
    iter_id: int,
    summary_payload: Mapping[str, Any],
    handoffs: list[dict],
    current_coverage: Mapping[str, Any] | None = None,
) -> dict:
    current_iter_id = _current_iter_id(run)
    score_payload = summary_payload.get("score") if isinstance(summary_payload.get("score"), Mapping) else {}
    stagnation_payload = summary_payload.get("stagnation") if isinstance(summary_payload.get("stagnation"), Mapping) else {}
    coverage_fallback = current_coverage if isinstance(current_coverage, Mapping) and not stagnation_payload else {}
    composite_score = score_payload.get("composite")
    roles = [build_role_takeaway_from_handoff(handoff, composite_score=composite_score) for handoff in handoffs]
    primary_role = _primary_role_takeaway(roles)
    summary_text = (
        _terminal_task_verdict_summary_for_iteration(run, iter_id=iter_id, current_iter_id=current_iter_id)
        or (primary_role.get("summary") if isinstance(primary_role, Mapping) else "")
        or clean_takeaway_text(run.get("summary_md"), max_length=220)
    )
    return {
        "iter": iter_id,
        "display_iter": display_iter(iter_id),
        "status": _structured_iteration_status(
            run,
            roles=roles,
            score_payload=score_payload,
            iter_id=iter_id,
            current_iter_id=current_iter_id,
        ),
        "phase": str(summary_payload.get("phase") or "").strip(),
        "summary": summary_text,
        "timestamp": str(summary_payload.get("timestamp") or "").strip(),
        "composite_score": composite_score,
        "stagnation_mode": str(stagnation_payload.get("mode") or "none"),
        "evidence_progress_mode": str(
            stagnation_payload.get("evidence_progress_mode")
            or coverage_fallback.get("evidence_progress_mode")
            or "none"
        ),
        "coverage_status": str(stagnation_payload.get("coverage_status") or coverage_fallback.get("status") or "pending"),
        "covered_check_count": _int_value(
            stagnation_payload.get("covered_check_count", coverage_fallback.get("covered_check_count")),
            default=0,
        ),
        "missing_check_count": _int_value(
            stagnation_payload.get("missing_check_count", coverage_fallback.get("missing_check_count")),
            default=0,
        ),
        "covered_check_ids": _string_list(stagnation_payload.get("covered_check_ids") or coverage_fallback.get("covered_check_ids")),
        "missing_check_ids": _string_list(stagnation_payload.get("missing_check_ids") or coverage_fallback.get("missing_check_ids")),
        "coverage_top_gaps": _coverage_gap_list(stagnation_payload.get("coverage_top_gaps") or coverage_fallback.get("top_gaps")),
        "consecutive_no_required_coverage_delta": _int_value(
            stagnation_payload.get("consecutive_no_required_coverage_delta"),
            default=0,
        ),
        "role_count": len(roles),
        "roles": roles,
    }


def _primary_role_takeaway(roles: list[dict]) -> dict | None:
    return next((item for item in roles if item.get("archetype") == "gatekeeper"), roles[-1] if roles else None)


def _structured_iteration_status(
    run: Mapping[str, Any],
    *,
    roles: list[dict],
    score_payload: Mapping[str, Any],
    iter_id: int,
    current_iter_id: int | None,
) -> str:
    terminal_status = _terminal_task_verdict_status_for_iteration(run, iter_id=iter_id, current_iter_id=current_iter_id)
    if terminal_status:
        return terminal_status
    passed = score_payload.get("passed")
    status = "pending"
    if passed is True:
        status = "passed"
    elif passed is False:
        status = "blocked"
    elif current_iter_id == iter_id and str(run.get("status") or "").strip().lower() in ACTIVE_TAKEAWAY_RUN_STATUSES:
        status = "running"
    elif roles:
        status = normalize_takeaway_status(roles[-1].get("status"))
    return status


def build_legacy_iteration_takeaway(run: dict) -> dict | None:
    runs_dir_value = str(run.get("runs_dir") or "").strip()
    runs_dir = Path(runs_dir_value) if runs_dir_value else None
    verdict = _legacy_verdict(run, runs_dir)
    excerpt = summary_excerpt(run.get("summary_md"))
    roles = _legacy_failure_roles(verdict)
    if verdict:
        roles.append(_legacy_gatekeeper_role(verdict, step_order=len(roles), excerpt=excerpt))

    if not roles and not excerpt:
        return None

    run_status = str(run.get("status") or "").strip().lower()
    iter_id = _int_value(run.get("current_iter"), default=0) or 0
    return {
        "iter": iter_id,
        "display_iter": display_iter(iter_id) or 1,
        "status": _legacy_iteration_status(run_status, verdict, roles),
        "phase": run_status,
        "summary": excerpt or clean_takeaway_text(verdict.get("decision_summary"), max_length=220),
        "timestamp": "",
        "composite_score": verdict.get("composite_score"),
        "stagnation_mode": "none",
        "evidence_progress_mode": "none",
        "coverage_status": "pending",
        "covered_check_count": 0,
        "missing_check_count": 0,
        "covered_check_ids": [],
        "missing_check_ids": [],
        "coverage_top_gaps": [],
        "consecutive_no_required_coverage_delta": 0,
        "role_count": len(roles),
        "roles": roles,
    }


def _legacy_verdict(run: Mapping[str, Any], runs_dir: Path | None) -> Mapping[str, Any]:
    verdict = run.get("last_verdict_json") if isinstance(run.get("last_verdict_json"), Mapping) else {}
    if verdict or runs_dir is None:
        return verdict
    return safe_read_json_file(runs_dir / "verifier_verdict.json") or safe_read_json_file(runs_dir / "gatekeeper_verdict.json") or {}


def _legacy_failure_roles(verdict: Mapping[str, Any]) -> list[dict]:
    priority_failures = verdict.get("priority_failures") if isinstance(verdict.get("priority_failures"), list) else []
    return [
        _legacy_failure_role(failure, index=index, verdict=verdict) for index, failure in enumerate(priority_failures, start=1) if isinstance(failure, Mapping)
    ]


def _legacy_failure_role(failure: Mapping[str, Any], *, index: int, verdict: Mapping[str, Any]) -> dict:
    runtime_role = _string_value(failure.get("role")).lower()
    return {
        "id": f"legacy-failure-{index}",
        "step_id": "",
        "step_order": index - 1,
        "role_name": display_role_name("", runtime_role=runtime_role),
        "archetype": LEGACY_RUNTIME_ROLE_TO_ARCHETYPE.get(runtime_role, ""),
        "status": "failed",
        "summary": "Execution aborted before this role could produce a stable handoff.",
        "blocking_item": " · ".join(_legacy_failure_support_bits(failure)),
        "next_action": _legacy_feedback(verdict),
        "composite_score": None,
    }


def _legacy_failure_support_bits(failure: Mapping[str, Any]) -> list[str]:
    support_bits = []
    error_code = clean_takeaway_text(failure.get("error_code"), max_length=80)
    attempts = _int_value(failure.get("attempts"), default=None)
    degraded = failure.get("degraded") is True
    if error_code:
        support_bits.append(error_code)
    if attempts is not None:
        support_bits.append(f"attempts={attempts}")
    if degraded:
        support_bits.append("degraded")
    return support_bits


def _legacy_gatekeeper_role(verdict: Mapping[str, Any], *, step_order: int, excerpt: str) -> dict:
    return {
        "id": "legacy-gatekeeper",
        "step_id": "",
        "step_order": step_order,
        "role_name": "GateKeeper",
        "archetype": "gatekeeper",
        "status": "passed" if verdict.get("passed") is True else "blocked",
        "summary": clean_takeaway_text(verdict.get("decision_summary"), max_length=220) or excerpt,
        "blocking_item": _legacy_blocking_note(verdict),
        "next_action": _legacy_feedback(verdict),
        "composite_score": verdict.get("composite_score"),
    }


def _legacy_blocking_note(verdict: Mapping[str, Any]) -> str:
    for item in [
        *_legacy_verdict_string_list(verdict.get("blocking_issues")),
        *_legacy_verdict_string_list(verdict.get("hard_constraint_violations")),
    ]:
        text = clean_takeaway_text(item, max_length=140)
        if text:
            return text
    return ""


def _legacy_verdict_string_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _legacy_feedback(verdict: Mapping[str, Any]) -> str:
    return clean_takeaway_text(
        verdict.get("feedback_to_builder") or verdict.get("feedback_to_generator"),
        max_length=520,
    )


def _legacy_iteration_status(run_status: str, verdict: Mapping[str, Any], roles: list[dict]) -> str:
    status = normalize_takeaway_status(run_status)
    if verdict.get("passed") is True:
        status = "passed"
    elif run_status == "running":
        status = "running"
    elif roles and roles[0].get("status") == "failed":
        status = "failed"
    elif verdict:
        status = "blocked"
    return status


def empty_evidence_coverage() -> dict[str, Any]:
    return {
        "ledger_path": "",
        "coverage_path": "",
        "status": "pending",
        "summary": {},
        "evidence_count": 0,
        "check_count": 0,
        "covered_check_count": 0,
        "missing_check_count": 0,
        "covered_check_ids": [],
        "missing_check_ids": [],
        "target_count": 0,
        "covered_target_count": 0,
        "weak_target_count": 0,
        "missing_target_count": 0,
        "blocked_target_count": 0,
        "top_gaps": [],
        "evidence_kind_counts": {},
        "artifact_ref_count": 0,
        "residual_risk_count": 0,
        "risk_signals": [],
        "latest_gatekeeper": {},
    }


def empty_evidence_manifest() -> dict[str, Any]:
    return {
        "manifest_path": "",
        "claim_count": 0,
        "artifact_backed_claim_count": 0,
        "workspace_backed_claim_count": 0,
        "direct_proof_claim_count": 0,
        "workspace_artifact_claim_count": 0,
        "run_artifact_claim_count": 0,
        "ledger_only_claim_count": 0,
        "unverified_claim_count": 0,
        "problem_count": 0,
        "problems": [],
    }


def empty_judgment_contract() -> dict[str, Any]:
    return {
        "contract_path": "",
        "source_bundle": {},
        "collaboration_summary": "",
        "loop_fit_reasons": [],
        "goal": "",
        "constraints": "",
        "check_mode": "",
        "check_count": 0,
        "completion_mode": "",
        "workflow_preset": "",
        "workflow_collaboration_intent": "",
        "judgment_tradeoffs": [],
        "execution_strategy": [],
        "local_governance": [],
        "role_postures": [],
        "coverage_targets": [],
        "success_surface": [],
        "fake_done_states": [],
        "evidence_preferences": [],
        "residual_risk": "",
        "inherited_from_run_id": "",
    }


def build_minimal_run_takeaway_projection(
    run: Mapping[str, Any],
    *,
    source_event_id: int | None = None,
) -> RunTakeawayProjection:
    raw_task_verdict = run.get("task_verdict") if isinstance(run.get("task_verdict"), Mapping) else {}
    task_verdict = normalize_task_verdict(raw_task_verdict)
    projection: RunTakeawayProjection = {
        "run_status": str(run.get("run_status") or run.get("status") or "").strip(),
        "task_verdict": dict(task_verdict),
        "task_verdict_path": "",
        "judgment_contract": build_judgment_contract(run),
        "evidence_buckets": _normalize_takeaway_evidence_buckets(raw_task_verdict.get("buckets")),
        "build_dir": str(Path(str(run.get("workdir") or "")).expanduser().resolve()) if run.get("workdir") else "",
        "log_dir": str(Path(str(run.get("runs_dir") or "")).expanduser().resolve()) if run.get("runs_dir") else "",
        "evidence_count": 0,
        "evidence_coverage": empty_evidence_coverage(),
        "evidence_manifest": empty_evidence_manifest(),
        "iteration_count": 0,
        "role_conclusion_count": 0,
        "latest_display_iter": None,
        "latest_status": str(run.get("status") or "").strip(),
        "latest_summary": str(run.get("summary_md") or "").strip()[:240],
        "iterations": [],
    }
    if source_event_id is not None:
        projection["source_event_id"] = _int_value(source_event_id, default=0) or 0
    return projection


def normalize_run_takeaway_projection_shape(
    run: Mapping[str, Any],
    projection: Mapping[str, Any],
    *,
    source_event_id: int | None = None,
) -> RunTakeawayProjection:
    normalized = build_minimal_run_takeaway_projection(
        run,
        source_event_id=source_event_id if source_event_id is not None else _int_value(projection.get("source_event_id"), default=None),
    )
    _apply_takeaway_scalar_projection_fields(normalized, projection)
    _apply_takeaway_task_verdict_projection_fields(normalized, projection)
    _apply_takeaway_judgment_contract_projection_fields(normalized, projection)
    _apply_takeaway_evidence_projection_fields(normalized, projection)
    _apply_takeaway_iteration_projection_fields(normalized, projection)
    return normalized


def _apply_takeaway_scalar_projection_fields(normalized: RunTakeawayProjection, projection: Mapping[str, Any]) -> None:
    if projection.get("run_status") is not None:
        normalized["run_status"] = str(projection.get("run_status") or "").strip()
    if projection.get("build_dir") is not None:
        normalized["build_dir"] = str(projection.get("build_dir") or "")
    if projection.get("log_dir") is not None:
        normalized["log_dir"] = str(projection.get("log_dir") or "")
    if projection.get("latest_status") is not None:
        normalized["latest_status"] = str(projection.get("latest_status") or "")
    if projection.get("latest_summary") is not None:
        normalized["latest_summary"] = str(projection.get("latest_summary") or "")
    if projection.get("task_verdict_path") is not None:
        normalized["task_verdict_path"] = str(projection.get("task_verdict_path") or "")
    if projection.get("source_event_id") is not None:
        normalized["source_event_id"] = _int_value(projection.get("source_event_id"), default=0) or 0


def _apply_takeaway_task_verdict_projection_fields(normalized: RunTakeawayProjection, projection: Mapping[str, Any]) -> None:
    raw_task_verdict = projection.get("task_verdict") if isinstance(projection.get("task_verdict"), Mapping) else {}
    task_verdict = normalize_task_verdict(raw_task_verdict)
    if task_verdict:
        normalized["task_verdict"] = task_verdict
        normalized["evidence_buckets"] = _normalize_takeaway_evidence_buckets(raw_task_verdict.get("buckets"))
    if isinstance(projection.get("evidence_buckets"), Mapping):
        normalized["evidence_buckets"] = _normalize_takeaway_evidence_buckets(projection.get("evidence_buckets"))


def _normalize_takeaway_evidence_buckets(value: object) -> dict[str, list[dict]]:
    if not isinstance(value, Mapping):
        return {}
    buckets: dict[str, list[dict]] = {}
    for key in BUCKET_KEYS:
        if key in value:
            buckets[key] = _takeaway_bucket_list(value.get(key))
    return buckets


def _takeaway_bucket_list(value: object) -> list[dict]:
    if not isinstance(value, list):
        return []
    result: list[dict] = []
    for item in value:
        if isinstance(item, Mapping):
            result.append(dict(item))
        elif isinstance(item, str) and item.strip():
            result.append({"label": item.strip()})
    return result


def _apply_takeaway_judgment_contract_projection_fields(normalized: RunTakeawayProjection, projection: Mapping[str, Any]) -> None:
    if isinstance(projection.get("judgment_contract"), Mapping):
        normalized["judgment_contract"] = _normalize_judgment_contract_payload(projection.get("judgment_contract"))


def _apply_takeaway_evidence_projection_fields(normalized: RunTakeawayProjection, projection: Mapping[str, Any]) -> None:
    normalized["evidence_count"] = _int_value(projection.get("evidence_count"), default=normalized["evidence_count"]) or 0
    if isinstance(projection.get("evidence_coverage"), Mapping):
        normalized["evidence_coverage"] = _normalize_evidence_coverage_payload(projection.get("evidence_coverage"))
    if isinstance(projection.get("evidence_manifest"), Mapping):
        normalized["evidence_manifest"] = _normalize_evidence_manifest_payload(projection.get("evidence_manifest"))


def _apply_takeaway_iteration_projection_fields(normalized: RunTakeawayProjection, projection: Mapping[str, Any]) -> None:
    normalized["iteration_count"] = _int_value(projection.get("iteration_count"), default=normalized["iteration_count"]) or 0
    normalized["role_conclusion_count"] = _int_value(projection.get("role_conclusion_count"), default=normalized["role_conclusion_count"]) or 0
    normalized["latest_display_iter"] = _int_value(projection.get("latest_display_iter"), default=normalized["latest_display_iter"])
    if isinstance(projection.get("iterations"), list):
        normalized["iterations"] = [dict(item) for item in projection.get("iterations") or [] if isinstance(item, Mapping)]


def build_task_verdict_artifact_path(run: dict) -> str:
    runs_dir_value = str(run.get("runs_dir") or "").strip()
    if not runs_dir_value:
        return ""
    layout = RunArtifactLayout(Path(runs_dir_value))
    return layout.relative(layout.task_verdict_path) if layout.task_verdict_path.exists() else ""


def build_evidence_coverage(run: dict) -> dict[str, Any]:
    runs_dir_value = str(run.get("runs_dir") or "").strip()
    if not runs_dir_value:
        return empty_evidence_coverage()

    layout = RunArtifactLayout(Path(runs_dir_value))
    projection = load_or_build_evidence_coverage_projection(layout)
    return summarize_evidence_coverage_projection(
        projection,
        coverage_path_available=layout.evidence_coverage_path.exists(),
    )


def _normalize_evidence_coverage_payload(value: object) -> dict[str, Any]:
    raw = value if isinstance(value, Mapping) else {}
    normalized = empty_evidence_coverage()
    normalized["ledger_path"] = _string_value(raw.get("ledger_path"))
    normalized["coverage_path"] = _string_value(raw.get("coverage_path"))
    normalized["status"] = _normalize_evidence_coverage_status(raw.get("status"))
    normalized["summary"] = dict(raw.get("summary") or {}) if isinstance(raw.get("summary"), Mapping) else {}
    for field in EVIDENCE_COVERAGE_COUNT_FIELDS:
        normalized[field] = _int_value(raw.get(field), default=0) or 0
    normalized["covered_check_ids"] = _string_list(raw.get("covered_check_ids"))
    normalized["missing_check_ids"] = _string_list(raw.get("missing_check_ids"))
    normalized["top_gaps"] = [dict(item) for item in list(raw.get("top_gaps") or []) if isinstance(item, Mapping)][:5]
    normalized["evidence_kind_counts"] = dict(raw.get("evidence_kind_counts") or {}) if isinstance(raw.get("evidence_kind_counts"), Mapping) else {}
    normalized["risk_signals"] = _string_list(raw.get("risk_signals"))[:5]
    normalized["latest_gatekeeper"] = dict(raw.get("latest_gatekeeper") or {}) if isinstance(raw.get("latest_gatekeeper"), Mapping) else {}
    return normalized


def _normalize_evidence_coverage_status(value: object) -> str:
    status = _string_value(value).lower()
    return status if status in EVIDENCE_COVERAGE_STATUSES else "pending"


def _normalize_evidence_manifest_payload(value: object, *, default_manifest_path: str = "") -> dict[str, Any]:
    raw = value if isinstance(value, Mapping) else {}
    normalized = empty_evidence_manifest()
    normalized["manifest_path"] = _string_value(raw.get("manifest_path")) or default_manifest_path
    for field in EVIDENCE_MANIFEST_COUNT_FIELDS:
        normalized[field] = _int_value(raw.get(field), default=0) or 0
    problems = [dict(item) for item in list(raw.get("problems") or []) if isinstance(item, Mapping)]
    normalized["problem_count"] = len(problems) if isinstance(raw.get("problems"), list) else (_int_value(raw.get("problem_count"), default=0) or 0)
    normalized["problems"] = [
        {
            "code": _string_value(item.get("code")),
            "claim_id": _string_value(item.get("claim_id")),
            "severity": _string_value(item.get("severity")),
            "message": _string_value(item.get("message")),
        }
        for item in problems[:4]
    ]
    return normalized


def build_evidence_manifest(run: dict) -> dict[str, Any]:
    runs_dir_value = str(run.get("runs_dir") or "").strip()
    if not runs_dir_value:
        return empty_evidence_manifest()

    layout = RunArtifactLayout(Path(runs_dir_value))
    manifest = safe_read_json_file(layout.evidence_manifest_path)
    if not manifest:
        return empty_evidence_manifest()
    return _normalize_evidence_manifest_payload(
        manifest,
        default_manifest_path=layout.relative(layout.evidence_manifest_path),
    )


def build_judgment_contract(run: Mapping[str, Any]) -> dict[str, Any]:
    runs_dir_value = str(run.get("runs_dir") or "").strip()
    if not runs_dir_value:
        return empty_judgment_contract()

    layout = RunArtifactLayout(Path(runs_dir_value))
    run_contract = safe_read_json_file(layout.run_contract_path)
    if not run_contract:
        return empty_judgment_contract()
    return _normalize_judgment_contract_payload(
        run_contract,
        default_contract_path=layout.relative(layout.run_contract_path),
    )


def _normalize_judgment_contract_payload(value: object, *, default_contract_path: str = "") -> dict[str, Any]:
    raw = value if isinstance(value, Mapping) else {}
    compiled_spec = raw.get("compiled_spec") if isinstance(raw.get("compiled_spec"), Mapping) else raw
    workflow = raw.get("workflow") if isinstance(raw.get("workflow"), Mapping) else raw
    normalized = empty_judgment_contract()
    normalized["contract_path"] = _string_value(raw.get("contract_path")) or default_contract_path
    normalized["source_bundle"] = _normalize_judgment_source_bundle(raw.get("source_bundle"))
    normalized["collaboration_summary"] = clean_takeaway_text(raw.get("collaboration_summary"), max_length=600)
    normalized["loop_fit_reasons"] = _takeaway_text_list(
        raw.get("loop_fit_reasons") or build_loop_fit_trace(raw.get("collaboration_summary"))
    )
    normalized["goal"] = clean_takeaway_text(raw.get("goal") or compiled_spec.get("goal"), max_length=600)
    normalized["constraints"] = clean_takeaway_text(raw.get("constraints") or compiled_spec.get("constraints"), max_length=600)
    normalized["check_mode"] = clean_takeaway_text(raw.get("check_mode") or compiled_spec.get("check_mode"), max_length=80)
    normalized["check_count"] = structured_non_negative_int(raw.get("check_count"), default=len(list(compiled_spec.get("checks") or [])))
    normalized["completion_mode"] = clean_takeaway_text(raw.get("completion_mode"), max_length=80)
    normalized["workflow_preset"] = clean_takeaway_text(raw.get("workflow_preset") or workflow.get("preset"), max_length=120)
    normalized["workflow_collaboration_intent"] = clean_takeaway_text(
        raw.get("workflow_collaboration_intent") or workflow.get("collaboration_intent"),
        max_length=600,
    )
    normalized["judgment_tradeoffs"] = _takeaway_text_list(
        raw.get("judgment_tradeoffs")
        or build_judgment_tradeoff_trace(
            collaboration_summary=raw.get("collaboration_summary"),
            raw_sections=compiled_spec.get("raw_sections") if isinstance(compiled_spec, Mapping) else {},
            roles=workflow.get("roles") if isinstance(workflow, Mapping) else [],
            workflow=workflow,
        )
    )
    normalized["execution_strategy"] = _takeaway_text_list(
        raw.get("execution_strategy")
        or build_execution_strategy_trace(
            collaboration_summary=raw.get("collaboration_summary"),
            raw_sections=compiled_spec.get("raw_sections") if isinstance(compiled_spec, Mapping) else {},
            roles=workflow.get("roles") if isinstance(workflow, Mapping) else [],
            workflow=workflow,
        )
    )
    if "local_governance" in raw:
        normalized["local_governance"] = _takeaway_text_list(raw.get("local_governance"))
    else:
        normalized["local_governance"] = _takeaway_text_list(
            build_runtime_local_governance_trace(
                raw_sections=compiled_spec.get("raw_sections") if isinstance(compiled_spec, Mapping) else {},
                roles=workflow.get("roles") if isinstance(workflow, Mapping) else [],
                workflow=workflow,
            )
        )
    normalized["role_postures"] = _role_posture_takeaway_list(raw.get("role_postures") or workflow.get("roles"))
    normalized["coverage_targets"] = _takeaway_mapping_list(raw.get("coverage_targets") or compiled_spec.get("coverage_targets"))
    normalized["success_surface"] = _takeaway_text_list(raw.get("success_surface") or compiled_spec.get("success_surface"))
    normalized["fake_done_states"] = _takeaway_text_list(raw.get("fake_done_states") or compiled_spec.get("fake_done_states"))
    normalized["evidence_preferences"] = _takeaway_text_list(raw.get("evidence_preferences") or compiled_spec.get("evidence_preferences"))
    normalized["residual_risk"] = clean_takeaway_text(raw.get("residual_risk") or compiled_spec.get("residual_risk"), max_length=600)
    normalized["inherited_from_run_id"] = _string_value(raw.get("inherited_from_run_id"))
    continuation_context = raw.get("continuation_context") if isinstance(raw.get("continuation_context"), Mapping) else None
    if continuation_context:
        normalized["inherited_from_run_id"] = _string_value(continuation_context.get("previous_run_id")) or normalized["inherited_from_run_id"]
    return normalized


def _normalize_judgment_source_bundle(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    bundle_id = _string_value(value.get("id"))
    if not bundle_id:
        return {}
    source = {
        "id": bundle_id,
        "name": clean_takeaway_text(value.get("name"), max_length=240),
        "revision": structured_non_negative_int(value.get("revision")),
        "source_bundle_id": _string_value(value.get("source_bundle_id")),
        "imported_from_path": _string_value(value.get("imported_from_path")),
    }
    bundle_sha256 = _string_value(value.get("bundle_sha256"))
    bundle_bytes = structured_non_negative_int(value.get("bundle_bytes"))
    bundle_yaml_path = _string_value(value.get("bundle_yaml_path"))
    if bundle_sha256:
        source["bundle_sha256"] = bundle_sha256
    if bundle_bytes:
        source["bundle_bytes"] = bundle_bytes
    if bundle_yaml_path:
        source["bundle_yaml_path"] = bundle_yaml_path
    return source


def _takeaway_text_list(value: object, *, max_items: int = 4, max_length: int = 240) -> list[str]:
    if not isinstance(value, list):
        return []
    texts = [clean_takeaway_text(item, max_length=max_length) for item in value]
    return [text for text in texts if text][:max_items]


def _takeaway_mapping_list(value: object, *, max_items: int = 40) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)][:max_items]


def _role_posture_takeaway_list(value: object, *, max_items: int = 6, max_length: int = 300) -> list[str]:
    if not isinstance(value, list):
        return []
    summaries: list[str] = []
    for item in value:
        if isinstance(item, Mapping):
            posture = clean_takeaway_text(item.get("posture_notes"), max_length=max_length)
            if not posture:
                continue
            role_name = clean_takeaway_text(item.get("role_name") or item.get("name"), max_length=80)
            archetype = clean_takeaway_text(item.get("archetype"), max_length=40)
            label = role_name or archetype
            if label and archetype and archetype not in label.lower():
                label = f"{label} ({archetype})"
            summaries.append(f"{label}: {posture}" if label else posture)
            continue
        text = clean_takeaway_text(item, max_length=max_length)
        if text:
            summaries.append(text)
    return summaries[:max_items]


def build_run_key_takeaways(run: dict) -> RunTakeawayProjection:
    evidence_coverage = build_evidence_coverage(run)
    iterations = build_structured_iteration_takeaways(run, current_coverage=evidence_coverage)
    if not iterations:
        legacy_iteration = build_legacy_iteration_takeaway(run)
        if legacy_iteration:
            iterations = [legacy_iteration]
    iterations = sorted(iterations, key=_iteration_sort_key, reverse=True)
    latest = iterations[0] if iterations else None
    evidence_count = 0
    runs_dir_value = str(run.get("runs_dir") or "").strip()
    if runs_dir_value:
        evidence_count = len(read_jsonl(RunArtifactLayout(Path(runs_dir_value)).evidence_ledger_path))
    evidence_manifest = build_evidence_manifest(run)
    projection = build_minimal_run_takeaway_projection(run)
    projection.update(
        {
            "task_verdict_path": build_task_verdict_artifact_path(run),
            "judgment_contract": build_judgment_contract(run),
            "evidence_count": evidence_count,
            "evidence_coverage": evidence_coverage,
            "evidence_manifest": evidence_manifest,
            "iteration_count": len(iterations),
            "role_conclusion_count": sum(len(list(iteration.get("roles") or [])) for iteration in iterations),
            "latest_display_iter": latest.get("display_iter") if latest else None,
            "latest_status": latest.get("status") if latest else normalize_takeaway_status(run.get("status")),
            "latest_summary": latest.get("summary") if latest else summary_excerpt(run.get("summary_md")),
            "iterations": iterations,
        }
    )
    return projection


def _iteration_sort_key(item: Mapping[str, Any]) -> int:
    iter_id = _int_value(item.get("iter"), default=None)
    return iter_id if iter_id is not None else -1


_build_run_key_takeaways = build_run_key_takeaways
_build_evidence_coverage = build_evidence_coverage
_build_evidence_manifest = build_evidence_manifest
_display_iter = display_iter
_summary_excerpt = summary_excerpt
