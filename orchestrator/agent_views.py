from __future__ import annotations

from pathlib import Path
from typing import Any

from orchestrator.io_contracts import write_json


def write_agent_views(base: Path, iter_id: int, verifier_verdict: dict[str, Any], stagnation: dict[str, Any]) -> None:
    agent_views = base / "state" / "agent_views"
    agent_views.mkdir(parents=True, exist_ok=True)

    failed = verifier_verdict.get("failed_case_ids", [])
    brief = {
        "current_iter": iter_id,
        "top_failures": failed[:5],
        "delta_3_iter": sum(stagnation.get("recent_deltas", [])[-3:]),
        "seed_adoption_rate": 0,
        "recommended_next_action": verifier_verdict.get("feedback_to_generator", "继续迭代"),
    }
    write_json(agent_views / "agent_brief.json", brief)

    recent = stagnation.get("recent_composites", [])
    xy = "\n".join([f"  ({i},{v})" for i, v in enumerate(recent)])
    mermaid = "\n".join([
        "xychart-beta",
        "  title \"Composite Trend\"",
        "  x-axis [0,1,2,3,4,5,6,7,8,9]",
        "  y-axis \"score\" 0 --> 1",
        f"  line [{','.join(str(v) for v in recent[-10:])}]",
    ])
    (agent_views / "score_trend.mmd").write_text(mermaid + "\n", encoding="utf-8")

    mode = stagnation.get("stagnation_mode", "none")
    flow = f"flowchart TD\n  A[iter {iter_id}] --> B[mode: {mode}]\n"
    (agent_views / "current_mode.mmd").write_text(flow, encoding="utf-8")
