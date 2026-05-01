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
    text = re.sub(r"\s+", " ", text).strip()
    return text


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

    summaries_by_iter: dict[int, dict] = {}
    for summary_path in sorted(runs_dir.glob("iterations/iter_*/summary.json")):
        summary_payload = safe_read_json_file(summary_path)
        if not summary_payload:
            continue
        try:
            iter_id = int(summary_payload.get("iter", -1))
        except (TypeError, ValueError):
            continue
        summaries_by_iter[iter_id] = summary_payload

    handoffs_by_iter: dict[int, list[dict]] = defaultdict(list)
    for handoff_path in sorted(runs_dir.glob("iterations/iter_*/steps/*/handoff.json")):
        handoff_payload = safe_read_json_file(handoff_path)
        if not handoff_payload:
            continue
        source = handoff_payload.get("source") if isinstance(handoff_payload.get("source"), Mapping) else {}
        try:
            iter_id = int(source.get("iter", -1))
        except (TypeError, ValueError):
            continue
        if iter_id < 0:
            continue
        handoffs_by_iter[iter_id].append(handoff_payload)

    iter_ids = sorted(set(summaries_by_iter) | set(handoffs_by_iter))
    current_iter = run.get("current_iter")
    try:
        current_iter_id = int(current_iter) if current_iter is not None else None
    except (TypeError, ValueError):
        current_iter_id = None

    iterations: list[dict] = []
    for iter_id in iter_ids:
        summary_payload = summaries_by_iter.get(iter_id) or {}
        score_payload = summary_payload.get("score") if isinstance(summary_payload.get("score"), Mapping) else {}
        composite_score = score_payload.get("composite")
        handoffs = sorted(
            handoffs_by_iter.get(iter_id, []),
            key=lambda item: int(((item.get("source") if isinstance(item.get("source"), Mapping) else {}) or {}).get("step_order") or 0),
        )
        roles = [build_role_takeaway_from_handoff(handoff, composite_score=composite_score) for handoff in handoffs]
        primary_role = next((item for item in roles if item.get("archetype") == "gatekeeper"), roles[-1] if roles else None)
        summary_text = (
            primary_role.get("summary")
            if isinstance(primary_role, Mapping)
            else ""
        ) or clean_takeaway_text(run.get("summary_md"), max_length=220)
        passed = score_payload.get("passed")
        if passed is True:
            iteration_status = "passed"
        elif passed is False:
            iteration_status = "blocked"
        elif current_iter_id == iter_id and str(run.get("status") or "").strip() == "running":
            iteration_status = "running"
        elif roles:
            iteration_status = normalize_takeaway_status(roles[-1].get("status"))
        else:
            iteration_status = "pending"
        iterations.append(
            {
                "iter": iter_id,
                "display_iter": display_iter(iter_id),
                "status": iteration_status,
                "phase": str(summary_payload.get("phase") or "").strip(),
                "summary": summary_text,
                "timestamp": str(summary_payload.get("timestamp") or "").strip(),
                "composite_score": composite_score,
                "role_count": len(roles),
                "roles": roles,
            }
        )
    return iterations


def build_legacy_iteration_takeaway(run: dict) -> dict | None:
    runs_dir_value = str(run.get("runs_dir") or "").strip()
    runs_dir = Path(runs_dir_value) if runs_dir_value else None
    verdict = run.get("last_verdict_json") or {}
    if not verdict and runs_dir is not None:
        verdict = safe_read_json_file(runs_dir / "verifier_verdict.json") or safe_read_json_file(runs_dir / "gatekeeper_verdict.json") or {}

    excerpt = summary_excerpt(run.get("summary_md"))
    roles: list[dict] = []
    priority_failures = verdict.get("priority_failures") if isinstance(verdict, Mapping) else []
    if isinstance(priority_failures, list):
        for index, failure in enumerate(priority_failures, start=1):
            if not isinstance(failure, Mapping):
                continue
            runtime_role = str(failure.get("role") or "").strip().lower()
            role_name = display_role_name("", runtime_role=runtime_role)
            error_code = clean_takeaway_text(failure.get("error_code"), max_length=80)
            attempts = failure.get("attempts")
            degraded = bool(failure.get("degraded"))
            support_bits = []
            if error_code:
                support_bits.append(error_code)
            if attempts not in {None, ""}:
                support_bits.append(f"attempts={attempts}")
            if degraded:
                support_bits.append("degraded")
            roles.append(
                {
                    "id": f"legacy-failure-{index}",
                    "step_id": "",
                    "step_order": index - 1,
                    "role_name": role_name,
                    "archetype": LEGACY_RUNTIME_ROLE_TO_ARCHETYPE.get(runtime_role, ""),
                    "status": "failed",
                    "summary": "Execution aborted before this role could produce a stable handoff.",
                    "blocking_item": " · ".join(support_bits),
                    "next_action": clean_takeaway_text(
                        verdict.get("feedback_to_builder") or verdict.get("feedback_to_generator"),
                        max_length=520,
                    ),
                    "composite_score": None,
                }
            )

    if verdict:
        blocking_note = (
            clean_takeaway_text((verdict.get("blocking_issues") or [""])[0], max_length=140)
            or clean_takeaway_text((verdict.get("hard_constraint_violations") or [""])[0], max_length=140)
        )
        roles.append(
            {
                "id": "legacy-gatekeeper",
                "step_id": "",
                "step_order": len(roles),
                "role_name": "GateKeeper",
                "archetype": "gatekeeper",
                "status": "passed" if verdict.get("passed") is True else "blocked",
                "summary": clean_takeaway_text(verdict.get("decision_summary"), max_length=220) or excerpt,
                "blocking_item": blocking_note,
                "next_action": clean_takeaway_text(
                    verdict.get("feedback_to_builder") or verdict.get("feedback_to_generator"),
                    max_length=520,
                ),
                "composite_score": verdict.get("composite_score"),
            }
        )

    if not roles and not excerpt:
        return None

    run_status = str(run.get("status") or "").strip().lower()
    if verdict.get("passed") is True:
        status = "passed"
    elif run_status == "running":
        status = "running"
    elif roles and roles[0].get("status") == "failed":
        status = "failed"
    elif verdict:
        status = "blocked"
    else:
        status = normalize_takeaway_status(run_status)
    return {
        "iter": int(run.get("current_iter") or 0),
        "display_iter": display_iter(run.get("current_iter")) or 1,
        "status": status,
        "phase": run_status,
        "summary": excerpt or clean_takeaway_text(verdict.get("decision_summary"), max_length=220),
        "timestamp": "",
        "composite_score": verdict.get("composite_score"),
        "role_count": len(roles),
        "roles": roles,
    }


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
