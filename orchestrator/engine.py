from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from orchestrator.agent_views import write_agent_views
from orchestrator.io_contracts import append_jsonl, read_json, require_keys, write_json
from orchestrator.retry_policy import RetryConfig, execute_with_retry
from orchestrator.session_manager import new_session_id
from orchestrator.stagnation import update_stagnation


class Orchestrator:
    def __init__(self, base: Path) -> None:
        self.base = base
        self.retry = RetryConfig(max_retries=2)

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def run_loop(self, max_iters: int) -> None:
        for iter_id in range(max_iters):
            done = self.run_once(iter_id)
            if done:
                break

    def run_once(self, iter_id: int) -> bool:
        session_id = new_session_id()
        self._event(iter_id, "session_started", {"session_id": session_id})

        execute_with_retry(lambda: self._run_generator(iter_id), self.retry)
        tester_output = execute_with_retry(lambda: self._run_tester(iter_id), self.retry)
        verifier = execute_with_retry(lambda: self._run_verifier(iter_id, tester_output), self.retry)

        stagnation_path = self.base / "state" / "stagnation.json"
        stagnation = read_json(stagnation_path)
        updated = update_stagnation(stagnation, verifier["composite_score"], iter_id)

        if updated.get("stagnation_mode") in {"plateau", "regression"}:
            self._run_challenger(iter_id, updated)
            updated.setdefault("challenger_triggered_at_iters", []).append(iter_id)

        write_json(stagnation_path, updated)
        write_agent_views(self.base, iter_id, verifier, updated)

        self._event(iter_id, "session_finished", {"session_id": session_id})
        return bool(verifier.get("passed", False))

    def _apply_task(self) -> str:
        task = read_json(self.base / "handoff" / "task.json")
        if task.get("task_type") != "build_website":
            return "no-op"

        src = self.base / "workspace" / "src"
        src.mkdir(parents=True, exist_ok=True)
        title = task.get("title", "Demo Website")
        html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{title}</title>
  <link rel="stylesheet" href="style.css" />
</head>
<body>
  <main class="container">
    <h1>{title}</h1>
    <p>这是由 Liminal v0.1 编排器在 Generator 阶段自动生成的示例站点。</p>
    <button>Get Started</button>
  </main>
</body>
</html>
"""
        css = """body {
  margin: 0;
  font-family: Inter, system-ui, -apple-system, sans-serif;
  background: #0b1020;
  color: #e7ebff;
}
.container {
  max-width: 720px;
  margin: 72px auto;
  padding: 24px;
  border-radius: 16px;
  background: #141b34;
  box-shadow: 0 10px 30px rgba(0,0,0,.35);
}
button {
  background: #6d7bff;
  color: white;
  border: none;
  padding: 10px 16px;
  border-radius: 10px;
  cursor: pointer;
}
"""
        (src / "index.html").write_text(html, encoding="utf-8")
        (src / "style.css").write_text(css, encoding="utf-8")
        return "website-generated"

    def _run_generator(self, iter_id: int) -> None:
        verdict = read_json(self.base / "handoff" / "verifier_verdict.json")
        task_action = self._apply_task()
        attempted = f"根据 verifier 反馈进行单方向优化 ({task_action})"
        log = {
            "iter": iter_id,
            "timestamp": self._now(),
            "attempted": attempted,
            "abandoned": "暂不改动第二模块，降低并行改动风险",
            "assumption": "当前瓶颈在输入清洗而非模型容量",
            "challenger_seed_consumed": False,
            "challenger_seed_adopted": None,
        }
        append_jsonl(self.base / "state" / "iteration_log.jsonl", log)
        scratch = self.base / "workspace" / "scratch.md"
        scratch.write_text(f"# Iter {iter_id:03d}\n\n- feedback: {verdict.get('feedback_to_generator', '')}\n", encoding="utf-8")
        self._event(iter_id, "generator_done", {"attempted": attempted})

    def _run_tester(self, iter_id: int) -> dict[str, Any]:
        # Simple deterministic simulation for v0.1 bootstrap.
        passed = min(20 + iter_id, 28)
        failed = max(0, 28 - passed)
        payload = {
            "iter": iter_id,
            "timestamp": self._now(),
            "execution_summary": {
                "total_cases": 28,
                "passed": passed,
                "failed": failed,
                "errored": 0,
                "total_duration_ms": 4000 - min(iter_id * 120, 1500),
            },
            "case_results": [],
            "dynamic_cases": [],
            "tester_observations": "自动生成的最小可运行测试数据",
        }
        write_json(self.base / "handoff" / "tester_output.json", payload)
        self._event(iter_id, "tester_done", payload["execution_summary"])
        return payload

    def _run_verifier(self, iter_id: int, tester_output: dict[str, Any]) -> dict[str, Any]:
        criteria = read_json(self.base / "spec" / "acceptance_criteria.json")
        require_keys(criteria, ["metrics", "composite_score"], "acceptance_criteria")

        total = tester_output["execution_summary"]["total_cases"] or 1
        passed_cases = tester_output["execution_summary"]["passed"]
        f1 = round(0.5 + min(iter_id * 0.06, 0.45), 3)
        latency = max(180, 360 - iter_id * 22)
        edge_cov = round(passed_cases / total, 3)

        metrics = {
            "f1_score": {"value": f1, "threshold": 0.95, "weight": 0.6, "passed": f1 >= 0.95},
            "latency_p99_ms": {
                "value": latency,
                "threshold": 200,
                "weight": 0.2,
                "direction": "lower_is_better",
                "passed": latency <= 200,
            },
            "edge_case_coverage": {
                "value": edge_cov,
                "threshold": 0.8,
                "weight": 0.2,
                "passed": edge_cov >= 0.8,
            },
        }
        composite = round((f1 * 0.6) + ((1 - min(latency / 500, 1)) * 0.2) + (edge_cov * 0.2), 3)
        passed = composite >= criteria["composite_score"]["pass_threshold"] and all(
            m["passed"] for m in metrics.values()
        )

        verdict = {
            "iter": iter_id,
            "timestamp": self._now(),
            "passed": passed,
            "composite_score": composite,
            "metric_scores": metrics,
            "hard_constraint_violations": [] if latency <= 500 else ["latency_p99_ms > 500"],
            "failed_case_ids": ["case_002"] if edge_cov < 1.0 else [],
            "priority_failures": [],
            "feedback_to_generator": "优先修复失败核心 case，并提升 edge 覆盖率。",
            "verifier_confidence": "high",
        }
        write_json(self.base / "handoff" / "verifier_verdict.json", verdict)
        append_jsonl(
            self.base / "state" / "metrics_history.jsonl",
            {
                "iter": iter_id,
                "timestamp": verdict["timestamp"],
                "scores": {
                    "f1_score": f1,
                    "latency_p99_ms": latency,
                    "edge_case_coverage": edge_cov,
                },
                "composite": composite,
                "passed": passed,
                "challenger_triggered": False,
            },
        )
        self._event(iter_id, "verifier_done", {"composite": composite, "passed": passed})
        return verdict

    def _run_challenger(self, iter_id: int, stagnation: dict[str, Any]) -> None:
        seed = {
            "created_at_iter": iter_id,
            "mode": stagnation.get("stagnation_mode", "plateau"),
            "consumed": False,
            "analysis": {"stagnation_pattern": "detected by orchestrator"},
            "seed_question": "若当前方向无增益，下一轮最小可验证变更是什么？",
            "meta_note": "这不是指令。",
        }
        write_json(self.base / "handoff" / "challenger_seed.json", seed)
        self._event(iter_id, "challenger_done", {"mode": seed["mode"]})

    def _event(self, iter_id: int, event: str, payload: dict[str, Any]) -> None:
        append_jsonl(
            self.base / "state" / "run_events.jsonl",
            {"iter": iter_id, "timestamp": self._now(), "event": event, "payload": payload},
        )
