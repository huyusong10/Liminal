from __future__ import annotations

from collections.abc import Mapping

from fastapi import HTTPException

from loopora.providers import executor_profile
from loopora.run_artifacts import list_run_artifacts
from loopora.run_takeaways import (
    LEGACY_RUNTIME_ROLE_TO_ARCHETYPE,
    build_evidence_coverage as _build_evidence_coverage,
    build_run_key_takeaways as _build_run_key_takeaways,
    display_iter as _display_iter,
    summary_excerpt as _summary_excerpt,
)
from loopora.workflows import display_name_for_archetype, normalize_role_display_name

SIMPLE_TIMELINE_TITLES = {
    "run_started": "Run started",
    "stop_requested": "Stop requested",
}

CONTROL_TIMELINE_TITLES = {
    "control_triggered": "Control triggered",
    "control_completed": "Control completed",
    "control_failed": "Control failed",
    "control_skipped": "Control skipped",
}


def _format_timeline_event(event: dict) -> dict:
    payload = event.get("payload", {})
    role = payload.get("role") or event.get("role")
    formatter = TIMELINE_EVENT_FORMATTERS.get(event["event_type"])
    if formatter:
        title, detail = formatter(payload, role, event["event_type"])
    else:
        title = SIMPLE_TIMELINE_TITLES.get(event["event_type"], event["event_type"])
        detail = ""

    return {
        "id": event["id"],
        "event_type": event["event_type"],
        "created_at": event["created_at"],
        "title": title,
        "detail": detail,
        "role": event.get("role"),
        "payload": payload,
    }


def _format_checks_resolved(payload: Mapping[str, object], role: object, event_type: str) -> tuple[str, str]:
    source = "auto-generated" if payload.get("source") == "auto_generated" else "specified"
    return "Checks resolved", f"{payload.get('count', 0)} checks, {source}"


def _format_role_request_prepared(payload: Mapping[str, object], role: object, event_type: str) -> tuple[str, str]:
    return "Role request prepared", str(payload.get("role_name") or role or "").strip()


def _format_step_context_prepared(payload: Mapping[str, object], role: object, event_type: str) -> tuple[str, str]:
    return "Step context prepared", str(payload.get("step_id") or "").strip()


def _format_role_execution_summary(payload: Mapping[str, object], role: object, event_type: str) -> tuple[str, str]:
    duration_ms = payload.get("duration_ms")
    if payload.get("ok"):
        return f"{role or 'role'} completed", _role_execution_success_detail(payload, duration_ms)
    return f"{role or 'role'} failed", _role_execution_failure_detail(payload, duration_ms)


def _role_execution_success_detail(payload: Mapping[str, object], duration_ms: object) -> str:
    parts = []
    if payload.get("attempts", 1) > 1:
        parts.append(f"attempts={payload['attempts']}")
    if payload.get("degraded"):
        parts.append("degraded")
    if duration_ms is not None:
        parts.append(f"{int(duration_ms)}ms")
    return ", ".join(parts) if parts else "ok"


def _role_execution_failure_detail(payload: Mapping[str, object], duration_ms: object) -> str:
    parts = [str(payload.get("error", "")).strip()]
    if duration_ms is not None:
        parts.append(f"{int(duration_ms)}ms")
    return ", ".join(part for part in parts if part)


def _format_role_degraded(payload: Mapping[str, object], role: object, event_type: str) -> tuple[str, str]:
    return f"{role or 'role'} degraded", str(payload.get("mode", "")).strip()


def _format_step_handoff_written(payload: Mapping[str, object], role: object, event_type: str) -> tuple[str, str]:
    return "Step handoff written", str(payload.get("summary") or payload.get("step_id") or "").strip()


def _format_control_event(payload: Mapping[str, object], role: object, event_type: str) -> tuple[str, str]:
    detail = " -> ".join(
        item
        for item in [
            str(payload.get("signal") or "").strip(),
            str(payload.get("role_id") or role or "").strip(),
        ]
        if item
    )
    return CONTROL_TIMELINE_TITLES[event_type], detail


def _format_iteration_summary_written(payload: Mapping[str, object], role: object, event_type: str) -> tuple[str, str]:
    return "Iteration summary written", str(payload.get("composite_score", "")).strip()


def _format_challenger_done(payload: Mapping[str, object], role: object, event_type: str) -> tuple[str, str]:
    return "Challenger suggested a new direction", str(payload.get("mode", "")).strip()


def _format_iteration_wait_started(payload: Mapping[str, object], role: object, event_type: str) -> tuple[str, str]:
    return "Waiting for the next iteration", f"{payload.get('duration_seconds', 0)}s"


def _format_iteration_wait_finished(payload: Mapping[str, object], role: object, event_type: str) -> tuple[str, str]:
    return "Iteration wait finished", f"{payload.get('duration_seconds', 0)}s"


def _format_run_aborted(payload: Mapping[str, object], role: object, event_type: str) -> tuple[str, str]:
    return f"Run aborted in {payload.get('role', 'role')}", str(payload.get("attempts", "")).strip()


def _format_workspace_guard_triggered(payload: Mapping[str, object], role: object, event_type: str) -> tuple[str, str]:
    return "Workspace safety guard triggered", f"deleted={payload.get('deleted_original_count', 0)}"


def _format_run_finished(payload: Mapping[str, object], role: object, event_type: str) -> tuple[str, str]:
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
    else:
        detail = ""
    return title, detail


TIMELINE_EVENT_FORMATTERS = {
    "checks_resolved": _format_checks_resolved,
    "role_request_prepared": _format_role_request_prepared,
    "step_context_prepared": _format_step_context_prepared,
    "role_execution_summary": _format_role_execution_summary,
    "role_degraded": _format_role_degraded,
    "step_handoff_written": _format_step_handoff_written,
    "iteration_summary_written": _format_iteration_summary_written,
    "challenger_done": _format_challenger_done,
    "iteration_wait_started": _format_iteration_wait_started,
    "iteration_wait_finished": _format_iteration_wait_finished,
    "run_aborted": _format_run_aborted,
    "workspace_guard_triggered": _format_workspace_guard_triggered,
    "run_finished": _format_run_finished,
    **{event_type: _format_control_event for event_type in CONTROL_TIMELINE_TITLES},
}


def _artifact_record_or_404(run: dict, artifact_id: str) -> dict:
    for artifact in list_run_artifacts(run):
        if artifact["id"] == artifact_id:
            return artifact
    raise HTTPException(status_code=404, detail="unknown artifact")


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
    task_verdict = loop.get("latest_task_verdict_json") if isinstance(loop.get("latest_task_verdict_json"), Mapping) else {}
    task_status = str(task_verdict.get("status") or "").strip()
    hints = {
        "draft": ("还没有运行，先检查 Loop 契约和工作目录。", "No run yet. Start by checking the spec and workdir."),
        "queued": ("已经进入队列，点进去看最新状态。", "Queued up. Open it to see the current state."),
        "running": ("正在推进中，点进去看实时进展。", "Actively progressing. Open it for live updates."),
        "succeeded": ("最近一次运行已结束，点进去看 Loop 裁决。", "The latest run finished. Open it for the task verdict."),
        "failed": ("最近一次运行失败，建议先看运行状态和 Loop 裁决。", "The latest run failed. Start with run status and task verdict."),
        "stopped": ("最近一次运行已停止。", "The latest run was stopped."),
    }
    hint_zh, hint_en = hints.get(latest_status, hints["draft"])
    if latest_status == "succeeded" and task_status in {"passed", "passed_with_residual_risk"}:
        hint_zh, hint_en = ("最近一次 Loop 裁决已通过。", "The latest task verdict passed.")
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
    task_verdict = run.get("task_verdict") if isinstance(run.get("task_verdict"), Mapping) else {}
    raw_verdict = run.get("last_verdict_json") or {}
    buckets = task_verdict.get("buckets") if isinstance(task_verdict.get("buckets"), Mapping) else {}
    failed_count = len(buckets.get("blocking") or raw_verdict.get("failed_check_ids") or [])
    composite_score = raw_verdict.get("composite_score")
    task_status = str(task_verdict.get("status") or "not_evaluated")
    if task_status in {"passed", "passed_with_residual_risk"}:
        verdict_title = ("Loop 裁决：已通过", "Task verdict: passed")
        verdict_note = (task_verdict.get("summary") or "证据支持本次 Loop 结论。", task_verdict.get("summary") or "Evidence supports the task conclusion.")
    elif task_status == "failed":
        verdict_title = ("Loop 裁决：未通过", "Task verdict: failed")
        verdict_note = (
            task_verdict.get("summary") or f"还有 {failed_count} 个阻断项，优先看证据桶。",
            task_verdict.get("summary") or f"{failed_count} blocker(s) remain. Start with the evidence buckets.",
        )
    elif task_status == "insufficient_evidence":
        verdict_title = ("Loop 裁决：证据不足", "Task verdict: insufficient evidence")
        verdict_note = (task_verdict.get("summary") or "运行已到边界，但证据还不足以证明 Loop 通过。", task_verdict.get("summary") or "The run reached its boundary, but evidence is not strong enough for a task pass.")
    else:
        verdict_title = ("Loop 裁决：未评估", "Task verdict: not evaluated")
        verdict_note = (task_verdict.get("summary") or "还没有可用的证据裁决。", task_verdict.get("summary") or "No evidence-based task verdict is available yet.")

    status_notes = {
        "queued": ("运行已创建，正在等待执行。", "The run is created and waiting to start."),
        "running": ("当前运行正在推进，下面的摘要会持续更新。", "This run is in progress and the summary will keep updating."),
        "succeeded": ("这次运行已顺利结束。", "This run finished successfully."),
        "failed": ("这次运行已失败结束。", "This run finished with a failure."),
        "stopped": ("这次运行已被手动停止。", "This run was stopped manually."),
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
    "_build_evidence_coverage",
    "_progress_stage_seed",
]
