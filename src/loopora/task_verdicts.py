from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from loopora.evidence_coverage import load_or_build_evidence_coverage_projection
from loopora.run_artifacts import RunArtifactLayout

TASK_VERDICT_STATUSES = {
    "not_evaluated",
    "passed",
    "failed",
    "insufficient_evidence",
    "passed_with_residual_risk",
}
TASK_VERDICT_SOURCES = {"gatekeeper", "rounds_completion", "run_status", "legacy"}
TERMINAL_RUN_STATUSES = {"succeeded", "failed", "stopped"}
BUCKET_KEYS = ("proven", "weak", "unproven", "blocking", "residual_risk")
TARGET_STATUS_BUCKETS = {
    "covered": "proven",
    "weak": "weak",
    "blocked": "blocking",
}


def hydrate_run_status_and_task_verdict(run: dict) -> dict:
    if not run:
        return run
    run_status = str(run.get("status") or "").strip() or "unknown"
    task_verdict = normalize_task_verdict(run.get("task_verdict_json"))
    if not task_verdict:
        legacy_source = bool(run.get("last_verdict_json"))
        task_verdict = build_task_verdict(
            {**run, "status": run_status},
            run_dir=_run_dir_for(run),
            legacy=legacy_source,
        )
    run["run_status"] = run_status
    run["task_verdict"] = task_verdict
    run["task_verdict_json"] = task_verdict
    return run


def build_task_verdict(
    run: Mapping[str, Any],
    *,
    run_dir: Path | None = None,
    final_reason: str = "",
    legacy: bool = False,
) -> dict:
    run_status = str(run.get("status") or "").strip() or "unknown"
    raw_verdict = run.get("last_verdict_json")
    if not isinstance(raw_verdict, Mapping):
        raw_verdict = {}
    coverage = _load_coverage(run, run_dir)
    buckets = _build_buckets(coverage, raw_verdict)
    source = "legacy" if legacy else "run_status"
    status = "not_evaluated"

    gatekeeper_status = _status_from_gatekeeper(raw_verdict, buckets)
    if gatekeeper_status:
        status = gatekeeper_status
        source = "legacy" if legacy else "gatekeeper"
    elif str(final_reason or "").strip() == "rounds_completed":
        status = "insufficient_evidence"
        source = "legacy" if legacy else "rounds_completion"
    elif run_status in TERMINAL_RUN_STATUSES:
        status = "not_evaluated"
        source = "legacy" if legacy else "run_status"

    summary = _summary_for(status, source, run_status, raw_verdict, coverage)
    return {
        "status": status,
        "source": source,
        "summary": summary,
        "buckets": buckets,
    }


def normalize_task_verdict(value: object) -> dict:
    if not isinstance(value, Mapping):
        return {}
    status = str(value.get("status") or "").strip()
    source = str(value.get("source") or "").strip()
    if status not in TASK_VERDICT_STATUSES or source not in TASK_VERDICT_SOURCES:
        return {}
    raw_buckets = value.get("buckets") if isinstance(value.get("buckets"), Mapping) else {}
    buckets = {
        "proven": _bucket_list(raw_buckets.get("proven")),
        "weak": _bucket_list(raw_buckets.get("weak")),
        "unproven": _bucket_list(raw_buckets.get("unproven")),
        "blocking": _bucket_list(raw_buckets.get("blocking")),
        "residual_risk": _bucket_list(raw_buckets.get("residual_risk")),
    }
    return {
        "status": status,
        "source": source,
        "summary": _clean_text(value.get("summary"), max_length=600),
        "buckets": buckets,
    }


def _run_dir_for(run: Mapping[str, Any]) -> Path | None:
    runs_dir = str(run.get("runs_dir") or "").strip()
    return Path(runs_dir) if runs_dir else None


def _load_coverage(run: Mapping[str, Any], run_dir: Path | None) -> dict:
    target_dir = run_dir or _run_dir_for(run)
    if target_dir is None:
        return {}
    try:
        return load_or_build_evidence_coverage_projection(RunArtifactLayout(target_dir))
    except (OSError, UnicodeError, ValueError):
        return {}


def _build_buckets(coverage: Mapping[str, Any], verdict: Mapping[str, Any]) -> dict[str, list[dict]]:
    buckets = _empty_buckets()
    _append_coverage_target_buckets(buckets, coverage.get("targets"))
    _append_verdict_blockers(buckets, verdict)
    _append_residual_risk_buckets(buckets, coverage.get("risk_signals"))
    if not any(buckets.values()):
        _append_legacy_evidence_buckets(buckets, verdict)
    return {key: _dedupe_bucket_items(items)[:12] for key, items in buckets.items()}


def _empty_buckets() -> dict[str, list[dict]]:
    return {key: [] for key in BUCKET_KEYS}


def _append_coverage_target_buckets(buckets: dict[str, list[dict]], targets: object) -> None:
    for target in list(targets or []):
        if not isinstance(target, Mapping):
            continue
        buckets[_bucket_for_target(target)].append(_target_bucket_item(target))


def _target_bucket_item(target: Mapping[str, Any]) -> dict:
    return {
        "id": str(target.get("id") or ""),
        "label": str(target.get("label") or target.get("id") or ""),
        "text": _clean_text(target.get("text"), max_length=240),
        "reason": _clean_text(target.get("reason"), max_length=240),
        "evidence_refs": [str(ref) for ref in list(target.get("evidence_refs") or []) if str(ref).strip()],
        "required": bool(target.get("required")),
    }


def _bucket_for_target(target: Mapping[str, Any]) -> str:
    status = str(target.get("status") or "").strip().lower()
    return TARGET_STATUS_BUCKETS.get(status, "unproven")


def _append_verdict_blockers(buckets: dict[str, list[dict]], verdict: Mapping[str, Any]) -> None:
    for blocker in _verdict_blockers(verdict):
        buckets["blocking"].append({"label": blocker, "reason": "Reported by the latest raw verdict."})


def _append_residual_risk_buckets(buckets: dict[str, list[dict]], risk_signals: object) -> None:
    for risk in list(risk_signals or []):
        text = _clean_text(risk, max_length=240)
        if text:
            buckets["residual_risk"].append({"label": text})


def _append_legacy_evidence_buckets(buckets: dict[str, list[dict]], verdict: Mapping[str, Any]) -> None:
    for claim in _string_list(verdict.get("evidence_claims")):
        buckets["proven"].append({"label": _clean_text(claim, max_length=240)})
    for ref in _string_list(verdict.get("evidence_refs")):
        buckets["proven"].append({"label": ref, "reason": "Referenced by the latest raw verdict."})


def _status_from_gatekeeper(verdict: Mapping[str, Any], buckets: Mapping[str, list[dict]]) -> str:
    if not verdict:
        return ""
    if verdict.get("passed") is True:
        return "passed"
    if verdict.get("passed") is False:
        return "failed" if buckets.get("blocking") or _verdict_blockers(verdict) else "insufficient_evidence"
    return ""


def _summary_for(
    status: str,
    source: str,
    run_status: str,
    verdict: Mapping[str, Any],
    coverage: Mapping[str, Any],
) -> str:
    summary = ""
    decision_summary = _clean_text(verdict.get("decision_summary"), max_length=600)
    if decision_summary:
        summary = decision_summary
    else:
        coverage_summary = coverage.get("summary") if isinstance(coverage.get("summary"), Mapping) else {}
        coverage_reason = _clean_text(coverage_summary.get("reason"), max_length=600)
        summary = coverage_reason or _fallback_summary_for(status, source, run_status)
    return summary


def _fallback_summary_for(status: str, source: str, run_status: str) -> str:
    status_summaries = {
        "passed": "GateKeeper found sufficient evidence for the task.",
        "passed_with_residual_risk": "GateKeeper passed the task with residual risk still visible.",
        "failed": "The latest judgment reported blocking evidence against the task.",
        "insufficient_evidence": (
            "The run reached its lifecycle boundary, but the evidence is not strong enough for a task pass."
        ),
    }
    if source == "legacy":
        return "This legacy run has no persisted task verdict; Loopora derived a compatibility verdict on read."
    return status_summaries.get(status, f"The run is {run_status}, and no evidence-based task verdict is available.")


def _verdict_blockers(verdict: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    blockers.extend(_string_list(verdict.get("blocking_issues")))
    blockers.extend(_string_list(verdict.get("hard_constraint_violations")))
    blockers.extend(_string_list(verdict.get("failed_check_ids")))
    for failure in list(verdict.get("priority_failures") or []):
        if isinstance(failure, Mapping):
            text = _clean_text(failure.get("summary") or failure.get("error_code"), max_length=240)
            if text:
                blockers.append(text)
    return list(dict.fromkeys(blockers))


def _string_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _bucket_list(value: object) -> list[dict]:
    if not isinstance(value, list):
        return []
    result: list[dict] = []
    for item in value:
        if isinstance(item, Mapping):
            result.append(dict(item))
        elif str(item).strip():
            result.append({"label": str(item).strip()})
    return result


def _dedupe_bucket_items(items: list[dict]) -> list[dict]:
    seen: set[str] = set()
    result: list[dict] = []
    for item in items:
        key = "|".join(
            [
                str(item.get("id") or ""),
                str(item.get("label") or ""),
                str(item.get("text") or ""),
                str(item.get("reason") or ""),
            ]
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _clean_text(value: object, *, max_length: int) -> str:
    text = " ".join(str(value or "").split()).strip()
    if len(text) > max_length:
        return text[: max_length - 1].rstrip() + "..."
    return text
