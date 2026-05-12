from __future__ import annotations

from dataclasses import dataclass

from loopora.structured_numbers import structured_optional_finite_number


@dataclass(frozen=True)
class StagnationUpdateRequest:
    stagnation: dict
    composite: float
    current_iter: int
    delta_threshold: float
    trigger_window: int
    regression_window: int


def update_stagnation(request: StagnationUpdateRequest) -> dict:
    recent = _score_values(request.stagnation.get("recent_composites"))
    deltas = _score_values(request.stagnation.get("recent_deltas"))

    if recent:
        deltas.append(round(request.composite - recent[-1], 6))
    recent.append(round(request.composite, 6))

    consecutive_low = 0
    for delta in reversed(deltas):
        if abs(delta) < request.delta_threshold:
            consecutive_low += 1
        else:
            break

    mode = "none"
    if len(deltas) >= request.regression_window and all(delta < 0 for delta in deltas[-request.regression_window:]):
        mode = "regression"
    elif consecutive_low >= request.trigger_window:
        mode = "plateau"

    return {
        **request.stagnation,
        "current_iter": request.current_iter,
        "delta_threshold": request.delta_threshold,
        "trigger_window": request.trigger_window,
        "regression_window": request.regression_window,
        "recent_composites": recent[-20:],
        "recent_deltas": deltas[-20:],
        "consecutive_low_delta": consecutive_low,
        "stagnation_mode": mode,
    }


def _score_values(value: object) -> list[float]:
    if not isinstance(value, list):
        return []
    return [score for item in value if (score := structured_optional_finite_number(item)) is not None]
