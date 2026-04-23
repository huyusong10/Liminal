from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path

from fastapi import HTTPException

from loopora.branding import strip_run_summary_title
from loopora.providers import executor_profile
from loopora.run_artifacts import list_run_artifacts
from loopora.workflows import ARCHETYPES, display_name_for_archetype, normalize_role_display_name

LEGACY_RUNTIME_ROLE_TO_ARCHETYPE = {
    "generator": "builder",
    "tester": "inspector",
    "verifier": "gatekeeper",
    "challenger": "guide",
}


def _format_timeline_event(event: dict) -> dict:
    payload = event.get("payload", {})
    role = payload.get("role") or event.get("role")
    title = event["event_type"]
    detail = ""
    duration_ms = payload.get("duration_ms")

    if event["event_type"] == "run_started":
        title = "Run started"
    elif event["event_type"] == "checks_resolved":
        source = "auto-generated" if payload.get("source") == "auto_generated" else "specified"
        title = "Checks resolved"
        detail = f"{payload.get('count', 0)} checks, {source}"
    elif event["event_type"] == "role_request_prepared":
        title = "Role request prepared"
        detail = str(payload.get("role_name") or role or "").strip()
    elif event["event_type"] == "step_context_prepared":
        title = "Step context prepared"
        detail = str(payload.get("step_id") or "").strip()
    elif event["event_type"] == "role_execution_summary":
        if payload.get("ok"):
            title = f"{role or 'role'} completed"
            parts = []
            if payload.get("attempts", 1) > 1:
                parts.append(f"attempts={payload['attempts']}")
            if payload.get("degraded"):
                parts.append("degraded")
            if duration_ms is not None:
                parts.append(f"{int(duration_ms)}ms")
            detail = ", ".join(parts) if parts else "ok"
        else:
            title = f"{role or 'role'} failed"
            parts = [str(payload.get("error", "")).strip()]
            if duration_ms is not None:
                parts.append(f"{int(duration_ms)}ms")
            detail = ", ".join(part for part in parts if part)
    elif event["event_type"] == "role_degraded":
        title = f"{role or 'role'} degraded"
        detail = str(payload.get("mode", "")).strip()
    elif event["event_type"] == "step_handoff_written":
        title = "Step handoff written"
        detail = str(payload.get("summary") or payload.get("step_id") or "").strip()
    elif event["event_type"] == "iteration_summary_written":
        title = "Iteration summary written"
        detail = str(payload.get("composite_score", "")).strip()
    elif event["event_type"] == "challenger_done":
        title = "Challenger suggested a new direction"
        detail = str(payload.get("mode", "")).strip()
    elif event["event_type"] == "iteration_wait_started":
        title = "Waiting for the next iteration"
        detail = f"{payload.get('duration_seconds', 0)}s"
    elif event["event_type"] == "iteration_wait_finished":
        title = "Iteration wait finished"
        detail = f"{payload.get('duration_seconds', 0)}s"
    elif event["event_type"] == "stop_requested":
        title = "Stop requested"
    elif event["event_type"] == "run_aborted":
        title = f"Run aborted in {payload.get('role', 'role')}"
        detail = str(payload.get("attempts", "")).strip()
    elif event["event_type"] == "workspace_guard_triggered":
        title = "Workspace safety guard triggered"
        detail = f"deleted={payload.get('deleted_original_count', 0)}"
    elif event["event_type"] == "run_finished":
        title = f"Run {payload.get('status', 'finished')}"
        reason = str(payload.get("reason", "")).strip()
        iter_id = payload.get("iter")
        if reason:
            detail = {
                "max_iters_exhausted": "max iterations exhausted",
                "rounds_completed": "planned rounds completed",
            }.get(reason, reason)
        elif iter_id is not None:
            display_iter = _display_iter(iter_id)
            detail = f"iter={display_iter}" if display_iter is not None else ""

    return {
        "id": event["id"],
        "event_type": event["event_type"],
        "created_at": event["created_at"],
        "title": title,
        "detail": detail,
        "role": event.get("role"),
        "payload": payload,
    }


def _artifact_record_or_404(run: dict, artifact_id: str) -> dict:
    for artifact in list_run_artifacts(run):
        if artifact["id"] == artifact_id:
            return artifact
    raise HTTPException(status_code=404, detail="unknown artifact")


def _display_iter(iter_value: object | None) -> int | None:
    if iter_value is None:
        return None
    try:
        return max(int(iter_value), 0) + 1
    except (TypeError, ValueError):
        return None


def _strip_markdown(value: str | None) -> str:
    text = str(value or "")
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\[(.*?)\]\((.*?)\)", r"\1", text)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.M)
    text = re.sub(r"^\s*[-*+]\s*", "", text, flags=re.M)
    text = re.sub(r"^\s*\d+\.\s*", "", text, flags=re.M)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _truncate_text(value: str, max_length: int = 140) -> str:
    if len(value) <= max_length:
        return value
    return value[: max_length - 1].rstrip() + "…"


def _summary_excerpt(summary_md: str | None) -> str:
    text = _strip_markdown(summary_md)
    text = strip_run_summary_title(text)
    return _truncate_text(text, max_length=170) if text else ""


def _safe_read_json_file(path: Path) -> dict | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _clean_takeaway_text(value: object, *, max_length: int = 240) -> str:
    text = _truncate_text(_strip_markdown(str(value or "").strip()), max_length=max_length)
    return text.strip()


def _display_role_name(name: object, *, archetype: object = "", runtime_role: object = "") -> str:
    cleaned_name = str(name or "").strip()
    cleaned_runtime = str(runtime_role or "").strip().lower()
    cleaned_archetype = str(archetype or "").strip().lower() or LEGACY_RUNTIME_ROLE_TO_ARCHETYPE.get(cleaned_runtime, "")
    normalized_name = normalize_role_display_name(cleaned_name, cleaned_archetype)
    if normalized_name:
        return normalized_name
    if cleaned_archetype in ARCHETYPES:
        return display_name_for_archetype(cleaned_archetype, locale="en")
    return cleaned_name or cleaned_runtime or "-"


def _normalize_takeaway_status(status: object) -> str:
    normalized = str(status or "").strip().lower()
    if normalized in {"passed", "completed", "blocked", "failed", "running", "advisory", "pending"}:
        return normalized
    if normalized in {"complete", "succeeded", "success"}:
        return "completed"
    if normalized in {"queued", "waiting", "idle"}:
        return "pending"
    return "pending"


def _build_role_takeaway_from_handoff(handoff: Mapping[str, object], *, composite_score: object = None) -> dict:
    source = handoff.get("source") if isinstance(handoff.get("source"), Mapping) else {}
    try:
        iter_id = int(source.get("iter", 0))
    except (TypeError, ValueError):
        iter_id = 0
    try:
        step_order = int(source.get("step_order") or 0)
    except (TypeError, ValueError):
        step_order = 0
    role_name = _display_role_name(
        source.get("role_name"),
        archetype=source.get("archetype"),
        runtime_role=source.get("runtime_role"),
    )
    blocking_items = [
        _clean_takeaway_text(item, max_length=520)
        for item in list(handoff.get("blocking_items") or [])
        if _clean_takeaway_text(item, max_length=520)
    ]
    next_action = _clean_takeaway_text(handoff.get("recommended_next_action"), max_length=520)
    return {
        "id": f"iter-{iter_id}-{str(source.get('step_id') or role_name).strip() or role_name}",
        "step_id": str(source.get("step_id") or "").strip(),
        "step_order": step_order,
        "role_name": role_name,
        "archetype": str(source.get("archetype") or "").strip().lower(),
        "status": _normalize_takeaway_status(handoff.get("status")),
        "summary": _clean_takeaway_text(handoff.get("summary"), max_length=1200),
        "blocking_item": " · ".join(blocking_items),
        "next_action": next_action,
        "composite_score": composite_score,
    }


def _build_structured_iteration_takeaways(run: dict) -> list[dict]:
    runs_dir_value = str(run.get("runs_dir") or "").strip()
    if not runs_dir_value:
        return []
    runs_dir = Path(runs_dir_value)
    if not runs_dir.exists():
        return []

    summaries_by_iter: dict[int, dict] = {}
    for summary_path in sorted(runs_dir.glob("iterations/iter_*/summary.json")):
        summary_payload = _safe_read_json_file(summary_path)
        if not summary_payload:
            continue
        try:
            iter_id = int(summary_payload.get("iter", -1))
        except (TypeError, ValueError):
            continue
        summaries_by_iter[iter_id] = summary_payload

    handoffs_by_iter: dict[int, list[dict]] = defaultdict(list)
    for handoff_path in sorted(runs_dir.glob("iterations/iter_*/steps/*/handoff.json")):
        handoff_payload = _safe_read_json_file(handoff_path)
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
        roles = [_build_role_takeaway_from_handoff(handoff, composite_score=composite_score) for handoff in handoffs]
        primary_role = next((item for item in roles if item.get("archetype") == "gatekeeper"), roles[-1] if roles else None)
        summary_text = (
            primary_role.get("summary")
            if isinstance(primary_role, Mapping)
            else ""
        ) or _clean_takeaway_text(run.get("summary_md"), max_length=220)
        passed = score_payload.get("passed")
        if passed is True:
            iteration_status = "passed"
        elif passed is False:
            iteration_status = "blocked"
        elif current_iter_id == iter_id and str(run.get("status") or "").strip() == "running":
            iteration_status = "running"
        elif roles:
            iteration_status = _normalize_takeaway_status(roles[-1].get("status"))
        else:
            iteration_status = "pending"
        iterations.append(
            {
                "iter": iter_id,
                "display_iter": _display_iter(iter_id),
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


def _build_legacy_iteration_takeaway(run: dict) -> dict | None:
    runs_dir_value = str(run.get("runs_dir") or "").strip()
    runs_dir = Path(runs_dir_value) if runs_dir_value else None
    verdict = run.get("last_verdict_json") or {}
    if not verdict and runs_dir is not None:
        verdict = _safe_read_json_file(runs_dir / "verifier_verdict.json") or _safe_read_json_file(runs_dir / "gatekeeper_verdict.json") or {}

    summary_excerpt = _summary_excerpt(run.get("summary_md"))
    roles: list[dict] = []
    priority_failures = verdict.get("priority_failures") if isinstance(verdict, Mapping) else []
    if isinstance(priority_failures, list):
        for index, failure in enumerate(priority_failures, start=1):
            if not isinstance(failure, Mapping):
                continue
            runtime_role = str(failure.get("role") or "").strip().lower()
            role_name = _display_role_name("", runtime_role=runtime_role)
            error_code = _clean_takeaway_text(failure.get("error_code"), max_length=80)
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
                    "next_action": _clean_takeaway_text(
                        verdict.get("feedback_to_builder") or verdict.get("feedback_to_generator"),
                        max_length=520,
                    ),
                    "composite_score": None,
                }
            )

    if verdict:
        blocking_note = (
            _clean_takeaway_text((verdict.get("blocking_issues") or [""])[0], max_length=140)
            or _clean_takeaway_text((verdict.get("hard_constraint_violations") or [""])[0], max_length=140)
        )
        roles.append(
            {
                "id": "legacy-gatekeeper",
                "step_id": "",
                "step_order": len(roles),
                "role_name": "GateKeeper",
                "archetype": "gatekeeper",
                "status": "passed" if verdict.get("passed") is True else "blocked",
                "summary": _clean_takeaway_text(verdict.get("decision_summary"), max_length=220) or summary_excerpt,
                "blocking_item": blocking_note,
                "next_action": _clean_takeaway_text(
                    verdict.get("feedback_to_builder") or verdict.get("feedback_to_generator"),
                    max_length=520,
                ),
                "composite_score": verdict.get("composite_score"),
            }
        )

    if not roles and not summary_excerpt:
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
        status = _normalize_takeaway_status(run_status)
    return {
        "iter": int(run.get("current_iter") or 0),
        "display_iter": _display_iter(run.get("current_iter")) or 1,
        "status": status,
        "phase": run_status,
        "summary": summary_excerpt or _clean_takeaway_text(verdict.get("decision_summary"), max_length=220),
        "timestamp": "",
        "composite_score": verdict.get("composite_score"),
        "role_count": len(roles),
        "roles": roles,
    }


def _build_run_key_takeaways(run: dict) -> dict:
    iterations = _build_structured_iteration_takeaways(run)
    if not iterations:
        legacy_iteration = _build_legacy_iteration_takeaway(run)
        if legacy_iteration:
            iterations = [legacy_iteration]
    iterations = sorted(iterations, key=lambda item: int(item.get("iter") or -1), reverse=True)
    latest = iterations[0] if iterations else None
    return {
        "build_dir": str(Path(str(run.get("workdir") or "")).expanduser().resolve()) if run.get("workdir") else "",
        "log_dir": str(Path(str(run.get("runs_dir") or "")).expanduser().resolve()) if run.get("runs_dir") else "",
        "iteration_count": len(iterations),
        "role_conclusion_count": sum(len(list(iteration.get("roles") or [])) for iteration in iterations),
        "latest_display_iter": latest.get("display_iter") if latest else None,
        "latest_status": latest.get("status") if latest else _normalize_takeaway_status(run.get("status")),
        "latest_summary": latest.get("summary") if latest else _summary_excerpt(run.get("summary_md")),
        "iterations": iterations,
    }


def _workflow_role_executor_summary(workflow: Mapping[str, object] | None, *, fallback_executor_kind: str = "codex") -> str:
    roles = workflow.get("roles", []) if isinstance(workflow, Mapping) else []
    if not isinstance(roles, list) or not roles:
        return "-"
    counts: dict[str, int] = {}
    for role in roles:
        if not isinstance(role, Mapping):
            continue
        raw_kind = str(role.get("executor_kind", "")).strip() or fallback_executor_kind
        try:
            label = executor_profile(raw_kind).label
        except ValueError:
            label = raw_kind or "-"
        counts[label] = counts.get(label, 0) + 1
    if not counts:
        return "-"
    return " · ".join(
        f"{label} x{count}" if count > 1 else label
        for label, count in counts.items()
    )


def _decorate_loop_overview(loop: dict) -> dict:
    latest_run_id = loop.get("latest_run_id")
    latest_status = loop.get("latest_status") or "draft"
    summary_excerpt = _summary_excerpt(loop.get("latest_summary_md"))
    workflow = loop.get("workflow_json") or {}
    hints = {
        "draft": ("还没有运行，先检查 spec 和工作目录。", "No run yet. Start by checking the spec and workdir."),
        "queued": ("已经进入队列，点进去看最新状态。", "Queued up. Open it to see the current state."),
        "running": ("正在推进中，点进去看实时进展。", "Actively progressing. Open it for live updates."),
        "succeeded": ("最近一次运行已经通过。", "The latest run passed."),
        "failed": ("最近一次运行失败，建议先看验证结论。", "The latest run failed. Start with the verdict."),
        "stopped": ("最近一次运行已停止。", "The latest run was stopped."),
    }
    hint_zh, hint_en = hints.get(latest_status, hints["draft"])
    bundle = loop.get("bundle") if isinstance(loop.get("bundle"), Mapping) else None
    managed_by_bundle = bool(bundle and bundle.get("id"))
    return {
        **loop,
        "role_executor_summary": _workflow_role_executor_summary(workflow, fallback_executor_kind=loop.get("executor_kind", "codex")),
        "role_count": len(workflow.get("roles", []) if isinstance(workflow, Mapping) else []),
        "step_count": len(workflow.get("steps", []) if isinstance(workflow, Mapping) else []),
        "display_iter": _display_iter(loop.get("latest_current_iter")),
        "card_href": f"/runs/{latest_run_id}" if latest_run_id else f"/loops/{loop['id']}",
        "card_hint_zh": hint_zh,
        "card_hint_en": hint_en,
        "card_excerpt": summary_excerpt,
        "managed_by_bundle": managed_by_bundle,
        "bundle_id": str((bundle or {}).get("id", "") or "").strip(),
        "bundle_name": str((bundle or {}).get("name", "") or "").strip(),
    }


def _decorate_run_overview(run: dict) -> dict:
    workflow = run.get("workflow_json") or {}
    return {
        **run,
        "role_executor_summary": _workflow_role_executor_summary(workflow, fallback_executor_kind=run.get("executor_kind", "codex")),
        "display_iter": _display_iter(run.get("current_iter")),
        "summary_excerpt": _summary_excerpt(run.get("summary_md")),
    }


def _progress_stage_seed(run: Mapping[str, object] | None) -> list[dict[str, str]]:
    workflow = run.get("workflow_json") if isinstance(run, Mapping) else {}
    roles = workflow.get("roles", []) if isinstance(workflow, Mapping) else []
    steps = workflow.get("steps", []) if isinstance(workflow, Mapping) else []
    role_by_id = {
        str(role.get("id") or "").strip(): role
        for role in roles
        if isinstance(role, Mapping) and str(role.get("id") or "").strip()
    }

    stages = [
        {
            "key": "checks",
            "label": "Checks",
            "kind": "checks",
        }
    ]
    for step in steps:
        if not isinstance(step, Mapping):
            continue
        step_id = str(step.get("id") or "").strip()
        if not step_id:
            continue
        role = role_by_id.get(str(step.get("role_id") or "").strip(), {})
        archetype = str(role.get("archetype") or "").strip()
        fallback_name = display_name_for_archetype(archetype, locale="en") if archetype else step_id
        label = normalize_role_display_name(str(role.get("name") or "").strip(), archetype) or fallback_name
        stages.append(
            {
                "key": f"step:{step_id}",
                "label": label,
                "kind": "workflow_step",
            }
        )
    stages.append(
        {
            "key": "finished",
            "label": "Done",
            "kind": "finished",
        }
    )
    return [
        {
            **stage,
            "sequence": index + 1,
        }
        for index, stage in enumerate(stages)
    ]


def _build_run_summary_snapshot(run: dict) -> dict:
    verdict = run.get("last_verdict_json") or {}
    failed_count = len(verdict.get("failed_check_ids") or [])
    composite_score = verdict.get("composite_score")
    passed = verdict.get("passed")
    if passed is True:
        verdict_title = ("最新结论：已通过", "Latest verdict: passed")
        verdict_note = ("关键 checks 都已通过，可以继续扩展目标。", "All key checks are passing. You can safely expand the target.")
    elif passed is False:
        verdict_title = ("最新结论：未通过", "Latest verdict: not passed")
        verdict_note = (
            f"还有 {failed_count} 条 checks 没过，优先看失败点。",
            f"{failed_count} check(s) are still failing. Start with the misses.",
        )
    else:
        verdict_title = ("还没有结论", "No verdict yet")
        verdict_note = ("GateKeeper 产出后这里会更新。", "This updates once the GateKeeper produces a verdict.")

    status_notes = {
        "queued": ("运行已创建，正在等待执行。", "The run is created and waiting to start."),
        "running": ("当前 run 正在推进，下面的摘要会持续更新。", "This run is in progress and the summary will keep updating."),
        "succeeded": ("这次 run 已顺利结束。", "This run finished successfully."),
        "failed": ("这次 run 已失败结束。", "This run finished with a failure."),
        "stopped": ("这次 run 已被手动停止。", "This run was stopped manually."),
        "draft": ("运行还没有真正开始。", "The run has not started yet."),
    }
    status = run.get("status") or "draft"
    status_note = status_notes.get(status, status_notes["draft"])

    return {
        "display_iter": _display_iter(run.get("current_iter")),
        "summary_excerpt": _summary_excerpt(run.get("summary_md")),
        "summary_empty_zh": "还没有稳定输出。",
        "summary_empty_en": "No substantial output yet.",
        "status_note_zh": status_note[0],
        "status_note_en": status_note[1],
        "verdict_title_zh": verdict_title[0],
        "verdict_title_en": verdict_title[1],
        "verdict_note_zh": verdict_note[0],
        "verdict_note_en": verdict_note[1],
        "failed_count": failed_count,
        "composite_score": composite_score,
    }


__all__ = [
    "LEGACY_RUNTIME_ROLE_TO_ARCHETYPE",
    "_artifact_record_or_404",
    "_build_run_key_takeaways",
    "_build_run_summary_snapshot",
    "_decorate_loop_overview",
    "_decorate_run_overview",
    "_display_iter",
    "_format_timeline_event",
    "_progress_stage_seed",
]
