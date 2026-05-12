from __future__ import annotations

TIMELINE_EVENT_TYPES = {
    "run_started",
    "checks_resolved",
    "role_request_prepared",
    "parallel_group_started",
    "parallel_group_finished",
    "step_context_prepared",
    "role_execution_summary",
    "step_handoff_written",
    "control_triggered",
    "control_completed",
    "control_failed",
    "control_skipped",
    "iteration_summary_written",
    "role_degraded",
    "challenger_done",
    "iteration_wait_started",
    "iteration_wait_finished",
    "workspace_guard_triggered",
    "stop_requested",
    "run_result_accepted",
    "run_aborted",
    "run_finished",
}

PROGRESS_EVENT_TYPES = {
    "checks_resolved",
    "role_started",
    "role_request_prepared",
    "parallel_group_started",
    "parallel_group_finished",
    "step_context_prepared",
    "role_execution_summary",
    "step_handoff_written",
    "control_triggered",
    "control_completed",
    "control_failed",
    "control_skipped",
    "run_aborted",
    "run_finished",
}

TAKEAWAY_PROJECTION_EVENT_TYPES = {
    "checks_resolved",
    "step_handoff_written",
    "control_completed",
    "control_failed",
    "iteration_summary_written",
    "workspace_guard_triggered",
    "run_aborted",
    "run_finished",
}
