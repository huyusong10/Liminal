from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from loopora.structured_numbers import structured_non_negative_int
from loopora.structured_booleans import structured_bool_is_true
from loopora.workflows import default_step_action_policy


@dataclass(frozen=True)
class WorkflowControlPayloadRequest:
    control: dict
    iter_id: int
    signal: str
    trigger: dict[str, object]
    elapsed_seconds: float


@dataclass(frozen=True)
class WorkflowControlStepRequest:
    control: dict
    payload: dict
    role: dict[str, Any]
    workflow_step_count: int
    existing_control_count: int


@dataclass(frozen=True)
class WorkflowControlTrigger:
    signal: str
    trigger: dict[str, object]


def workflow_control_after_seconds(value: object) -> float:
    text = str(value or "0s").strip().lower() or "0s"
    multiplier = 1.0
    if text.endswith("ms"):
        multiplier = 0.001
        text = text[:-2]
    elif text.endswith("s"):
        text = text[:-1]
    elif text.endswith("m"):
        multiplier = 60.0
        text = text[:-1]
    elif text.endswith("h"):
        multiplier = 3600.0
        text = text[:-1]
    try:
        return max(float(text) * multiplier, 0.0)
    except ValueError:
        return 0.0


def matching_workflow_controls(controls: list[dict], signal: str) -> list[dict]:
    return [control for control in controls if str((control.get("when") or {}).get("signal") or "").strip() == signal]


def workflow_iteration_control_triggers(gatekeeper_result: dict | None, stagnation: dict) -> list[WorkflowControlTrigger]:
    triggers: list[WorkflowControlTrigger] = []
    if gatekeeper_result and not structured_bool_is_true(gatekeeper_result.get("passed")):
        triggers.append(
            WorkflowControlTrigger(
                signal="gatekeeper_rejected",
                trigger={
                    "reason": "GateKeeper rejected the current evidence.",
                    "evidence_refs": list(gatekeeper_result.get("evidence_refs") or []),
                    "gatekeeper_result": gatekeeper_result,
                },
            )
        )
    stagnation_mode = str(stagnation.get("stagnation_mode", "none") or "none")
    evidence_progress_mode = str(stagnation.get("evidence_progress_mode", "none") or "none")
    if stagnation_mode != "none" or evidence_progress_mode != "none":
        missing_check_count = structured_non_negative_int(stagnation.get("latest_missing_check_count"))
        reason = (
            f"Required coverage did not improve; missing checks: {missing_check_count}."
            if evidence_progress_mode != "none"
            else f"Stagnation mode is {stagnation.get('stagnation_mode')}."
        )
        triggers.append(
            WorkflowControlTrigger(
                signal="no_evidence_progress",
                trigger={
                    "reason": reason,
                    "evidence_refs": list((gatekeeper_result or {}).get("evidence_refs") or []),
                    "stagnation_mode": stagnation_mode,
                    "evidence_progress_mode": evidence_progress_mode,
                },
            )
        )
    return triggers


def build_workflow_control_payload(request: WorkflowControlPayloadRequest) -> dict[str, object]:
    control = request.control
    trigger = request.trigger
    after = str((control.get("when") or {}).get("after") or "0s").strip() or "0s"
    return {
        "iter": request.iter_id,
        "control_id": str(control.get("id") or "").strip(),
        "signal": request.signal,
        "mode": str(control.get("mode") or "advisory"),
        "after": after,
        "elapsed_seconds": round(request.elapsed_seconds, 3),
        "role_id": str((control.get("call") or {}).get("role_id") or "").strip(),
        "reason": str(trigger.get("reason") or request.signal),
        "trigger_evidence_refs": list(trigger.get("evidence_refs") or []),
    }


def build_workflow_control_step(request: WorkflowControlStepRequest) -> tuple[dict[str, object], int]:
    control_id = str(request.control.get("id") or "").strip()
    role_id = str((request.control.get("call") or {}).get("role_id") or "").strip()
    control_order = request.workflow_step_count + 100 + request.existing_control_count
    return (
        {
            "id": f"control__{control_id}",
            "role_id": role_id,
            "on_pass": "continue",
            "model": "",
            "inherit_session": False,
            "extra_cli_args": "",
            "action_policy": default_step_action_policy(
                archetype=request.role.get("archetype"),
                on_pass="continue",
            ),
            "inputs": {
                "iteration_memory": "summary_only",
                "evidence_query": {"limit": 40},
            },
            "control_id": control_id,
            "control": request.payload,
        },
        control_order,
    )
