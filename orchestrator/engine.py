from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from orchestrator.agent_views import write_agent_views
from orchestrator.io_contracts import (
    append_jsonl,
    read_json,
    validate_acceptance_criteria,
    validate_tester_output,
    validate_verifier_verdict,
    write_json,
)
from orchestrator.retry_policy import RecoveryResult, RetryConfig, execute_with_recovery
from orchestrator.session_manager import new_session_id
from orchestrator.stagnation import update_stagnation


class RoleExecutionError(RuntimeError):
    def __init__(self, role: str, result: RecoveryResult) -> None:
        self.role = role
        self.result = result
        super().__init__(f"role={role} failed after {result.attempts} attempts (degraded={result.degraded})")


class Orchestrator:
    def __init__(self, base: Path) -> None:
        self.base = base
        self.retry = RetryConfig(max_retries=2)
        self.generator_mode = "default"
        self.tester_mode = "default"
        self.verifier_mode = "default"

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def run_loop(self, max_iters: int) -> None:
        for iter_id in range(max_iters):
            done = self.run_once(iter_id)
            if done:
                break

    def _execute_role(
        self,
        iter_id: int,
        role: str,
        fn: Callable[[], Any],
        degrade_once: Callable[[], None] | None = None,
    ) -> Any:
        value, result = execute_with_recovery(fn=fn, config=self.retry, degrade_once=degrade_once)
        self._event(
            iter_id,
            "role_execution_summary",
            {
                "role": role,
                "ok": result.ok,
                "attempts": result.attempts,
                "degraded": result.degraded,
                "error": str(result.error) if result.error else None,
            },
        )
        if not result.ok:
            raise RoleExecutionError(role=role, result=result)
        return value

    def run_once(self, iter_id: int) -> bool:
        session_id = new_session_id()
        self._event(iter_id, "session_started", {"session_id": session_id})

        try:
            self._execute_role(iter_id, "generator", lambda: self._run_generator(iter_id), self._degrade_generator)
            tester_output = self._execute_role(iter_id, "tester", lambda: self._run_tester(iter_id), self._degrade_tester)
            verifier = self._execute_role(
                iter_id,
                "verifier",
                lambda: self._run_verifier(iter_id, tester_output),
                self._degrade_verifier,
            )
        except RoleExecutionError as err:
            self._handle_abort(iter_id, err)
            self._event(iter_id, "session_finished", {"session_id": session_id, "aborted": True})
            return True

        stagnation_path = self.base / "state" / "stagnation.json"
        stagnation = read_json(stagnation_path)
        updated = update_stagnation(stagnation, verifier["composite_score"], iter_id)

        if updated.get("stagnation_mode") in {"plateau", "regression"}:
            self._run_challenger(iter_id, updated)
            updated.setdefault("challenger_triggered_at_iters", []).append(iter_id)

        write_json(stagnation_path, updated)
        write_agent_views(self.base, iter_id, verifier, updated)

        self._event(iter_id, "session_finished", {"session_id": session_id, "aborted": False})
        return bool(verifier.get("passed", False))

    def _degrade_generator(self) -> None:
        self.generator_mode = "conservative_changes"

    def _degrade_tester(self) -> None:
        self.tester_mode = "skip_dynamic_cases"

    def _degrade_verifier(self) -> None:
        self.verifier_mode = "strict_minimal_validation"

    def _handle_abort(self, iter_id: int, err: RoleExecutionError) -> None:
        payload = {
            "iter": iter_id,
            "timestamp": self._now(),
            "passed": False,
            "composite_score": 0.0,
            "metric_scores": {},
            "hard_constraint_violations": ["orchestrator_abort"],
            "failed_case_ids": [],
            "priority_failures": [
                {
                    "error_code": "ROLE_EXECUTION_ABORT",
                    "role": err.role,
                    "attempts": err.result.attempts,
                    "degraded": err.result.degraded,
                    "detail": str(err.result.error) if err.result.error else "unknown",
                }
            ],
            "feedback_to_generator": "执行已中止：请先修复运行错误后重试。",
            "verifier_confidence": "high",
        }
        write_json(self.base / "handoff" / "verifier_verdict.json", payload)
        self._event(
            iter_id,
            "run_aborted",
            {
                "error_code": "ROLE_EXECUTION_ABORT",
                "role": err.role,
                "attempts": err.result.attempts,
                "degraded": err.result.degraded,
            },
        )

    def _apply_task(self) -> str:
        task = read_json(self.base / "handoff" / "task.json")
        if task.get("task_type") != "build_website":
            return "no-op"

        src = self.base / "workspace" / "src"
        src.mkdir(parents=True, exist_ok=True)
        title = task.get("title", "Demo Website")
        html = f"""<!doctype html>
<html lang=\"zh-CN\">
<head>
  <meta charset=\"UTF-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
  <title>{title}</title>
  <link rel=\"stylesheet\" href=\"style.css\" />
</head>
<body>
  <main class=\"container\">
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
        attempted = f"根据 verifier 反馈进行单方向优化 ({task_action}, mode={self.generator_mode})"
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
        self._event(iter_id, "generator_done", {"attempted": attempted, "mode": self.generator_mode})

    def _run_tester(self, iter_id: int) -> dict[str, Any]:
        passed_total = min(20 + iter_id, 28)
        failed_total = max(0, 28 - passed_total)
        case_001_pass = iter_id >= 2
        case_002_pass = iter_id >= 8
        case_results = [
            {
                "id": "case_001",
                "category": "core",
                "weight": 1.0,
                "status": "passed" if case_001_pass else "failed",
                "duration_ms": 80,
                "actual_output": "HELLO WORLD" if case_001_pass else "hello world",
            },
            {
                "id": "case_002",
                "category": "edge",
                "weight": 0.8,
                "status": "passed" if case_002_pass else "failed",
                "duration_ms": 50,
                "actual_output": {"error": "empty input"} if case_002_pass else {},
            },
        ]
        dynamic_cases = [] if self.tester_mode == "skip_dynamic_cases" else [{"id": "dyn_001", "status": "passed"}]
        payload = {
            "iter": iter_id,
            "timestamp": self._now(),
            "execution_summary": {
                "total_cases": 28,
                "passed": passed_total,
                "failed": failed_total,
                "errored": 0,
                "total_duration_ms": 4000 - min(iter_id * 120, 1500),
            },
            "case_results": case_results,
            "dynamic_cases": dynamic_cases,
            "tester_observations": f"自动生成测试数据(mode={self.tester_mode})",
        }
        validate_tester_output(payload)
        write_json(self.base / "handoff" / "tester_output.json", payload)
        self._event(iter_id, "tester_done", {**payload["execution_summary"], "mode": self.tester_mode})
        return payload

    def _run_verifier(self, iter_id: int, tester_output: dict[str, Any]) -> dict[str, Any]:
        criteria = read_json(self.base / "spec" / "acceptance_criteria.json")
        validate_acceptance_criteria(criteria)

        total = tester_output["execution_summary"]["total_cases"] or 1
        passed_cases = tester_output["execution_summary"]["passed"]
        f1 = round(0.5 + min(iter_id * 0.06, 0.45), 3)
        latency = max(180, 360 - iter_id * 22)
        edge_cov = round(passed_cases / total, 3)

        metrics_cfg = criteria["metrics"]
        metrics = {
            "f1_score": {
                "value": f1,
                "threshold": metrics_cfg["f1_score"]["pass_threshold"],
                "weight": metrics_cfg["f1_score"]["weight"],
                "passed": f1 >= metrics_cfg["f1_score"]["pass_threshold"],
            },
            "latency_p99_ms": {
                "value": latency,
                "threshold": metrics_cfg["latency_p99_ms"]["pass_threshold"],
                "weight": metrics_cfg["latency_p99_ms"]["weight"],
                "direction": "lower_is_better",
                "passed": latency <= metrics_cfg["latency_p99_ms"]["pass_threshold"],
            },
            "edge_case_coverage": {
                "value": edge_cov,
                "threshold": metrics_cfg["edge_case_coverage"]["pass_threshold"],
                "weight": metrics_cfg["edge_case_coverage"]["weight"],
                "passed": edge_cov >= metrics_cfg["edge_case_coverage"]["pass_threshold"],
            },
        }

        normalized_f1 = min(f1 / metrics["f1_score"]["threshold"], 1.0)
        normalized_latency = min(metrics["latency_p99_ms"]["threshold"] / max(latency, 1), 1.0)
        normalized_edge = min(edge_cov / metrics["edge_case_coverage"]["threshold"], 1.0)
        composite = round(
            (normalized_f1 * metrics["f1_score"]["weight"])
            + (normalized_latency * metrics["latency_p99_ms"]["weight"])
            + (normalized_edge * metrics["edge_case_coverage"]["weight"]),
            3,
        )

        failed_case_ids = [c["id"] for c in tester_output.get("case_results", []) if c.get("status") != "passed"]
        core_failed = any(
            c.get("category") == "core" and c.get("status") != "passed"
            for c in tester_output.get("case_results", [])
        )

        hard_violations: list[str] = []
        if latency > 500:
            hard_violations.append("latency_p99_ms > 500")
        if core_failed:
            hard_violations.append("core cases must all pass")

        passed = (
            composite >= criteria["composite_score"]["pass_threshold"]
            and all(m["passed"] for m in metrics.values())
            and not hard_violations
        )

        verdict = {
            "iter": iter_id,
            "timestamp": self._now(),
            "passed": passed,
            "composite_score": composite,
            "metric_scores": metrics,
            "hard_constraint_violations": hard_violations,
            "failed_case_ids": failed_case_ids,
            "priority_failures": [],
            "feedback_to_generator": "优先修复核心失败用例并保持低延迟。",
            "verifier_confidence": "high" if self.verifier_mode == "default" else "medium",
        }
        validate_verifier_verdict(verdict)
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
        self._event(iter_id, "verifier_done", {"composite": composite, "passed": passed, "mode": self.verifier_mode})
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
