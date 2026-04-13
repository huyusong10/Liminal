from __future__ import annotations

from typing import Any


def update_stagnation(stagnation: dict[str, Any], composite: float, current_iter: int) -> dict[str, Any]:
    recent = stagnation.get("recent_composites", [])
    deltas = stagnation.get("recent_deltas", [])
    threshold = float(stagnation.get("delta_threshold", 0.005))
    trigger_window = int(stagnation.get("trigger_window", 4))
    regression_window = int(stagnation.get("regression_window", 2))

    if recent:
        delta = composite - recent[-1]
        deltas.append(round(delta, 6))
    recent.append(round(composite, 6))

    consecutive_low = 0
    for d in reversed(deltas):
        if abs(d) < threshold:
            consecutive_low += 1
        else:
            break

    mode = "none"
    if len(deltas) >= regression_window and all(d < 0 for d in deltas[-regression_window:]):
        mode = "regression"
    elif consecutive_low >= trigger_window:
        mode = "plateau"

    return {
        **stagnation,
        "current_iter": current_iter,
        "recent_composites": recent[-20:],
        "recent_deltas": deltas[-20:],
        "consecutive_low_delta": consecutive_low,
        "stagnation_mode": mode,
    }
