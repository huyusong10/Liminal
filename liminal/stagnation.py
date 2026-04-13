from __future__ import annotations


def update_stagnation(
    stagnation: dict,
    composite: float,
    current_iter: int,
    *,
    delta_threshold: float,
    trigger_window: int,
    regression_window: int,
) -> dict:
    recent = list(stagnation.get("recent_composites", []))
    deltas = list(stagnation.get("recent_deltas", []))

    if recent:
        deltas.append(round(composite - recent[-1], 6))
    recent.append(round(composite, 6))

    consecutive_low = 0
    for delta in reversed(deltas):
        if abs(delta) < delta_threshold:
            consecutive_low += 1
        else:
            break

    mode = "none"
    if len(deltas) >= regression_window and all(delta < 0 for delta in deltas[-regression_window:]):
        mode = "regression"
    elif consecutive_low >= trigger_window:
        mode = "plateau"

    return {
        **stagnation,
        "current_iter": current_iter,
        "delta_threshold": delta_threshold,
        "trigger_window": trigger_window,
        "regression_window": regression_window,
        "recent_composites": recent[-20:],
        "recent_deltas": deltas[-20:],
        "consecutive_low_delta": consecutive_low,
        "stagnation_mode": mode,
    }
