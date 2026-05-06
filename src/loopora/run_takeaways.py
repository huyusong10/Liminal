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
from loopora.workflows import ARCHETYPES, display_name_for_archetype, normalize_role_display_name

LEGACY_RUNTIME_ROLE_TO_ARCHETYPE = {
    "generator": "builder",
    "tester": "inspector",
    "verifier": "gatekeeper",
    "challenger": "guide",
}


class RunTakeawayProjection(TypedDict):
    run_status: str
    task_verdict: dict[str, Any]
    evidence_buckets: dict[str, Any]
    build_dir: str
    log_dir: str
    evidence_count: int
    evidence_coverage: dict[str, Any]
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
    try:
        return max(int(iter_value), 0) + 1
    except (TypeError, ValueError):
        return None


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
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def clean_takeaway_text(value: object, *, max_length: int = 240) -> str:
    text = truncate_text(strip_markdown(str(value or "").strip()), max_length=max_length)
    return text.strip()


def display_role_name(name: object, *, archetype: object = "", runtime_role: object = "") -> str:
    cleaned_name = str(name or "").strip()
    cleaned_runtime = str(runtime_role or "").strip().lower()
    cleaned_archetype = str(archetype or "").strip().lower() or LEGACY_RUNTIME_ROLE_TO_ARCHETYPE.get(cleaned_runtime, "")
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
    try:
        iter_id = int(source.get("iter", 0))
    except (TypeError, ValueError):
        iter_id = 0
    try:
        step_order = int(source.get("step_order") or 0)
    except (TypeError, ValueError):
        step_order = 0
    role_name = display_role_name(
        source.get("role_name"),
        archetype=source.get("archetype"),
        runtime_role=source.get("runtime_role"),
    )
    blocking_items = [
        clean_takeaway_text(item, max_length=520)
        for item in list(handoff.get("blocking_items") or [])
        if clean_takeaway_text(item, max_length=520)
    ]
    next_action = clean_takeaway_text(handoff.get("recommended_next_action"), max_length=520)
    return {
        "id": f"iter-{iter_id}-{str(source.get('step_id') or role_name).strip() or role_name}",
        "step_id": str(source.get("step_id") or "").strip(),
        "step_order": step_order,
        "role_name": role_name,
        "archetype": str(source.get("archetype") or "").strip().lower(),
        "status": normalize_takeaway_status(handoff.get("status")),
        "summary": clean_takeaway_text(handoff.get("summary"), max_length=1200),
        "blocking_item": " · ".join(blocking_items),
        "next_action": next_action,
        "evidence_refs": [
            str(item).strip()
            for item in list(handoff.get("evidence_refs") or [])
            if str(item).strip()
        ],
        "composite_score": composite_score,
    }


def build_structured_iteration_takeaways(run: dict) -> list[dict]:
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
            current_iter_id=current_iter_id,
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


def _int_value(value: object, *, default: int | None) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _handoff_step_order(handoff: Mapping[str, object]) -> int:
    source = handoff.get("source") if isinstance(handoff.get("source"), Mapping) else {}
    return int(source.get("step_order") or 0)


def _build_structured_iteration_takeaway(
    run: Mapping[str, Any],
    *,
    iter_id: int,
    summary_payload: Mapping[str, Any],
    handoffs: list[dict],
    current_iter_id: int | None,
) -> dict:
    score_payload = summary_payload.get("score") if isinstance(summary_payload.get("score"), Mapping) else {}
    composite_score = score_payload.get("composite")
    roles = [build_role_takeaway_from_handoff(handoff, composite_score=composite_score) for handoff in handoffs]
    primary_role = _primary_role_takeaway(roles)
    summary_text = (
        primary_role.get("summary")
        if isinstance(primary_role, Mapping)
        else ""
    ) or clean_takeaway_text(run.get("summary_md"), max_length=220)
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
    passed = score_payload.get("passed")
    status = "pending"
    if passed is True:
        status = "passed"
    elif passed is False:
        status = "blocked"
    elif current_iter_id == iter_id and str(run.get("status") or "").strip() == "running":
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
    return {
        "iter": int(run.get("current_iter") or 0),
        "display_iter": display_iter(run.get("current_iter")) or 1,
        "status": _legacy_iteration_status(run_status, verdict, roles),
        "phase": run_status,
        "summary": excerpt or clean_takeaway_text(verdict.get("decision_summary"), max_length=220),
        "timestamp": "",
        "composite_score": verdict.get("composite_score"),
        "role_count": len(roles),
        "roles": roles,
    }


def _legacy_verdict(run: Mapping[str, Any], runs_dir: Path | None) -> Mapping[str, Any]:
    verdict = run.get("last_verdict_json") if isinstance(run.get("last_verdict_json"), Mapping) else {}
    if verdict or runs_dir is None:
        return verdict
    return safe_read_json_file(runs_dir / "verifier_verdict.json") or safe_read_json_file(
        runs_dir / "gatekeeper_verdict.json"
    ) or {}


def _legacy_failure_roles(verdict: Mapping[str, Any]) -> list[dict]:
    priority_failures = verdict.get("priority_failures") if isinstance(verdict.get("priority_failures"), list) else []
    return [
        _legacy_failure_role(failure, index=index, verdict=verdict)
        for index, failure in enumerate(priority_failures, start=1)
        if isinstance(failure, Mapping)
    ]


def _legacy_failure_role(failure: Mapping[str, Any], *, index: int, verdict: Mapping[str, Any]) -> dict:
    runtime_role = str(failure.get("role") or "").strip().lower()
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
    attempts = failure.get("attempts")
    degraded = bool(failure.get("degraded"))
    if error_code:
        support_bits.append(error_code)
    if attempts not in {None, ""}:
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
    return (
        clean_takeaway_text((verdict.get("blocking_issues") or [""])[0], max_length=140)
        or clean_takeaway_text((verdict.get("hard_constraint_violations") or [""])[0], max_length=140)
    )


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


def build_minimal_run_takeaway_projection(
    run: Mapping[str, Any],
    *,
    source_event_id: int | None = None,
) -> RunTakeawayProjection:
    task_verdict = run.get("task_verdict") if isinstance(run.get("task_verdict"), Mapping) else {}
    projection: RunTakeawayProjection = {
        "run_status": str(run.get("run_status") or run.get("status") or "").strip(),
        "task_verdict": dict(task_verdict),
        "evidence_buckets": dict(task_verdict.get("buckets") or {}) if isinstance(task_verdict, Mapping) else {},
        "build_dir": str(Path(str(run.get("workdir") or "")).expanduser().resolve()) if run.get("workdir") else "",
        "log_dir": str(Path(str(run.get("runs_dir") or "")).expanduser().resolve()) if run.get("runs_dir") else "",
        "evidence_count": 0,
        "evidence_coverage": empty_evidence_coverage(),
        "iteration_count": 0,
        "role_conclusion_count": 0,
        "latest_display_iter": None,
        "latest_status": str(run.get("status") or "").strip(),
        "latest_summary": str(run.get("summary_md") or "").strip()[:240],
        "iterations": [],
    }
    if source_event_id is not None:
        projection["source_event_id"] = int(source_event_id or 0)
    return projection


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


def build_run_key_takeaways(run: dict) -> RunTakeawayProjection:
    iterations = build_structured_iteration_takeaways(run)
    if not iterations:
        legacy_iteration = build_legacy_iteration_takeaway(run)
        if legacy_iteration:
            iterations = [legacy_iteration]
    iterations = sorted(iterations, key=lambda item: int(item.get("iter") or -1), reverse=True)
    latest = iterations[0] if iterations else None
    evidence_count = 0
    runs_dir_value = str(run.get("runs_dir") or "").strip()
    if runs_dir_value:
        evidence_count = len(read_jsonl(RunArtifactLayout(Path(runs_dir_value)).evidence_ledger_path))
    evidence_coverage = build_evidence_coverage(run)
    projection = build_minimal_run_takeaway_projection(run)
    projection.update(
        {
            "evidence_count": evidence_count,
            "evidence_coverage": evidence_coverage,
            "iteration_count": len(iterations),
            "role_conclusion_count": sum(len(list(iteration.get("roles") or [])) for iteration in iterations),
            "latest_display_iter": latest.get("display_iter") if latest else None,
            "latest_status": latest.get("status") if latest else normalize_takeaway_status(run.get("status")),
            "latest_summary": latest.get("summary") if latest else summary_excerpt(run.get("summary_md")),
            "iterations": iterations,
        }
    )
    return projection


_build_run_key_takeaways = build_run_key_takeaways
_build_evidence_coverage = build_evidence_coverage
_display_iter = display_iter
_summary_excerpt = summary_excerpt
