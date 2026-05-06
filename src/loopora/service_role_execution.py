from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from loopora.diagnostics import get_logger, log_event
from loopora.evidence_coverage import with_coverage_targets, write_evidence_coverage_projection
from loopora.executor import CodexExecutor, ExecutionStopped, RoleRequest
from loopora.recovery import RetryConfig, execute_with_recovery
from loopora.run_artifacts import write_json_with_mirrors
from loopora.service_prompts import (
    CHECK_PLANNER_SCHEMA,
    CHALLENGER_SCHEMA,
    GENERATOR_SCHEMA,
    TESTER_SCHEMA,
    VERIFIER_SCHEMA,
    GeneratorPromptRequest,
)
from loopora.service_types import LooporaError, RoleExecutionError
from loopora.utils import read_json, utc_now

logger = get_logger(__name__)


@dataclass(frozen=True)
class RoleExecutionRequest:
    run_id: str
    iter_id: int | None
    role: str
    fn: Callable[[], dict]
    retry_config: RetryConfig
    degrade_once: Callable[[], None] | None = None
    event_context: Mapping[str, object] | None = None


@dataclass(frozen=True)
class IterationRoleRunRequest:
    executor: CodexExecutor
    run: dict
    compiled_spec: dict
    run_dir: Path
    iter_id: int
    mode: str = "default"
    previous_generator_result: dict | None = None
    previous_tester_result: dict | None = None
    previous_verifier_result: dict | None = None
    previous_challenger_result: dict | None = None
    tester_output: dict | None = None
    stagnation: dict | None = None


class ServiceRoleExecutionMixin:
    def _pause_between_iterations(self, run_id: str, duration_seconds: float, iter_id: int) -> None:
        if duration_seconds <= 0:
            return
        log_event(
            logger,
            logging.INFO,
            "service.run.iteration_wait.started",
            "Starting the configured wait between iterations",
            run_id=run_id,
            iter=iter_id,
            duration_seconds=duration_seconds,
        )
        self.append_run_event(
            run_id,
            "iteration_wait_started",
            {"iter": iter_id, "duration_seconds": duration_seconds},
        )
        deadline = time.monotonic() + duration_seconds
        while True:
            self._ensure_not_stopped(run_id)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(max(self.settings.polling_interval_seconds, 0.05), remaining))
        self.append_run_event(
            run_id,
            "iteration_wait_finished",
            {"iter": iter_id, "duration_seconds": duration_seconds},
        )
        log_event(
            logger,
            logging.INFO,
            "service.run.iteration_wait.finished",
            "Finished the configured wait between iterations",
            run_id=run_id,
            iter=iter_id,
            duration_seconds=duration_seconds,
        )

    def _wait_for_slot(self, run_id: str) -> None:
        self.repository.update_run(run_id, status="queued", summary_md="# Loopora Run Summary\n\nQueued.\n")
        waiting_started_at = time.perf_counter()
        waiting_logged = False
        while True:
            self._ensure_not_stopped(run_id)
            if self.repository.claim_run_slot(run_id, self.settings.max_concurrent_runs):
                self.repository.update_run(run_id, started_at=utc_now(), status="running")
                log_event(
                    logger,
                    logging.INFO,
                    "service.run.slot.acquired",
                    "Acquired a run slot and started execution",
                    run_id=run_id,
                    wait_duration_ms=int((time.perf_counter() - waiting_started_at) * 1000),
                    max_concurrent_runs=self.settings.max_concurrent_runs,
                )
                return
            if not waiting_logged:
                waiting_logged = True
                log_event(
                    logger,
                    logging.INFO,
                    "service.run.slot.waiting",
                    "Run is waiting for a free slot or workdir lock",
                    run_id=run_id,
                    polling_interval_seconds=self.settings.polling_interval_seconds,
                    max_concurrent_runs=self.settings.max_concurrent_runs,
                )
            time.sleep(self.settings.polling_interval_seconds)

    def _resolve_run_checks(
        self,
        run: dict,
        executor: CodexExecutor,
        compiled_spec: dict,
        run_dir: Path,
        retry_config: RetryConfig,
    ) -> dict:
        layout = self._run_artifact_layout(run_dir)
        checks = compiled_spec.get("checks", [])
        if checks:
            self.append_run_event(
                run["id"],
                "checks_resolved",
                {"source": "specified", "count": len(checks)},
            )
            log_event(
                logger,
                logging.INFO,
                "service.run.checks.resolved",
                "Run checks were resolved from the user-provided spec",
                **self._run_log_context(run, source="specified", check_count=len(checks)),
            )
            return compiled_spec

        planner_result = self._execute_role(
            RoleExecutionRequest(
                run_id=run["id"],
                iter_id=None,
                role="check_planner",
                fn=lambda: self._run_check_planner(executor, run, compiled_spec, run_dir),
                retry_config=retry_config,
            )
        )
        resolved_checks = self._normalize_generated_checks(planner_result.get("checks", []))
        if not resolved_checks:
            raise LooporaError("check planner returned no checks")

        resolved_spec = with_coverage_targets(
            {
                **compiled_spec,
                "checks": resolved_checks,
                "check_mode": "auto_generated",
                "check_generation_notes": str(planner_result.get("generation_notes", "")).strip(),
            },
            completion_mode=str(run.get("completion_mode", "gatekeeper")),
        )
        write_json_with_mirrors(layout.contract_compiled_spec_path, resolved_spec)
        write_json_with_mirrors(
            layout.contract_auto_checks_path,
            {
                "generated_at": utc_now(),
                "count": len(resolved_checks),
                "notes": resolved_spec["check_generation_notes"],
                "checks": resolved_checks,
            },
            mirror_paths=[layout.legacy_auto_checks_path],
        )
        run_contract = read_json(layout.run_contract_path)
        if run_contract:
            run_contract["compiled_spec"] = resolved_spec
            write_json_with_mirrors(layout.run_contract_path, run_contract)
        write_evidence_coverage_projection(layout)
        self.repository.update_run(run["id"], compiled_spec=resolved_spec)
        self.append_run_event(
            run["id"],
            "checks_resolved",
            {
                "source": "auto_generated",
                "count": len(resolved_checks),
                "notes": resolved_spec["check_generation_notes"],
            },
        )
        log_event(
            logger,
            logging.INFO,
            "service.run.checks.resolved",
            "Run checks were generated automatically for exploratory execution",
            **self._run_log_context(
                run,
                source="auto_generated",
                check_count=len(resolved_checks),
                notes=resolved_spec["check_generation_notes"],
            ),
        )
        return resolved_spec

    def _execute_role(
        self,
        request: RoleExecutionRequest,
    ) -> dict:
        started_at = time.perf_counter()
        log_context = {"run_id": request.run_id, "role": request.role}
        if request.iter_id is not None:
            log_context["iter"] = request.iter_id
        context_payload = dict(request.event_context or {})
        log_event(
            logger,
            logging.INFO,
            "service.role.execution.started",
            "Starting role execution",
            **log_context,
        )

        def wrapped() -> dict:
            self._ensure_not_stopped(request.run_id)
            self.repository.update_run(request.run_id, active_role=request.role)
            start_payload = {"role": request.role, **context_payload}
            if request.iter_id is not None:
                start_payload["iter"] = request.iter_id
            self.append_run_event(request.run_id, "role_started", start_payload, role=request.role)
            return request.fn()

        value, result = execute_with_recovery(wrapped, request.retry_config, degrade_once=request.degrade_once)
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        summary_payload = {
            "role": request.role,
            **context_payload,
            "ok": result.ok,
            "attempts": result.attempts,
            "degraded": result.degraded,
            "error": str(result.error) if result.error else None,
            "duration_ms": duration_ms,
        }
        if request.iter_id is not None:
            summary_payload["iter"] = request.iter_id
        self.append_run_event(
            request.run_id,
            "role_execution_summary",
            summary_payload,
            role=request.role,
        )
        log_event(
            logger,
            logging.INFO if result.ok else logging.ERROR,
            "service.role.execution.completed",
            "Role execution finished",
            run_id=request.run_id,
            **summary_payload,
        )
        if not result.ok:
            raise RoleExecutionError(request.role, result)
        return value or {}

    def _role_request_defaults(self, run: dict, run_dir: Path, *, model: str) -> dict:
        return {
            "workdir": Path(run["workdir"]),
            "executor_kind": run.get("executor_kind", "codex"),
            "executor_mode": run.get("executor_mode", "preset"),
            "command_cli": run.get("command_cli", ""),
            "command_args_text": run.get("command_args_text", ""),
            "model": model,
            "reasoning_effort": run["reasoning_effort"],
            "run_dir": run_dir,
            "idle_timeout_seconds": self.settings.role_idle_timeout_seconds,
        }

    def _execute_request(self, executor: CodexExecutor, run: dict, request: RoleRequest) -> dict:
        self._record_role_request(run["id"], request)
        return executor.execute(
            request,
            lambda event_type, payload: self.append_run_event(run["id"], event_type, payload, role=request.role),
            lambda: self.repository.should_stop(run["id"]),
            lambda pid: self.repository.update_run(run["id"], child_pid=pid)
            if pid is not None
            else self.repository.update_run(run["id"], clear_child_pid=True),
        )

    def _run_generator(self, request: IterationRoleRunRequest) -> dict:
        role_request = RoleRequest(
            run_id=request.run["id"],
            role="generator",
            prompt=self._generator_prompt(
                GeneratorPromptRequest(
                    compiled_spec=request.compiled_spec,
                    workdir=Path(request.run["workdir"]),
                    iter_id=request.iter_id,
                    mode=request.mode,
                    previous_generator_result=request.previous_generator_result,
                    previous_tester_result=request.previous_tester_result,
                    previous_verifier_result=request.previous_verifier_result,
                    previous_challenger_result=request.previous_challenger_result,
                )
            ),
            output_schema=GENERATOR_SCHEMA,
            output_path=request.run_dir / "generator_output.json",
            sandbox="workspace-write",
            extra_context={
                "iter_id": request.iter_id,
                "compiled_spec": request.compiled_spec,
                "previous_generator_result": request.previous_generator_result,
                "previous_tester_result": request.previous_tester_result,
                "previous_verifier_result": request.previous_verifier_result,
                "previous_challenger_result": request.previous_challenger_result,
            },
            **self._role_request_defaults(
                request.run,
                request.run_dir,
                model=request.run["role_models_json"].get("generator", request.run["model"]),
            ),
        )
        return self._execute_request(request.executor, request.run, role_request)

    def _run_check_planner(
        self,
        executor: CodexExecutor,
        run: dict,
        compiled_spec: dict,
        run_dir: Path,
    ) -> dict:
        layout = self._run_artifact_layout(run_dir)
        request = RoleRequest(
            run_id=run["id"],
            role="check_planner",
            prompt=self._check_planner_prompt(compiled_spec),
            output_schema=CHECK_PLANNER_SCHEMA,
            output_path=layout.check_planner_output_raw_path,
            sandbox="read-only",
            extra_context={"compiled_spec": compiled_spec},
            **self._role_request_defaults(run, run_dir, model=run["model"]),
        )
        return self._execute_request(executor, run, request)

    def _run_tester(self, request: IterationRoleRunRequest) -> dict:
        role_request = RoleRequest(
            run_id=request.run["id"],
            role="tester",
            prompt=self._tester_prompt(request.compiled_spec, request.iter_id, request.mode),
            output_schema=TESTER_SCHEMA,
            output_path=request.run_dir / "tester_output.raw.json",
            sandbox="workspace-write",
            extra_context={"iter_id": request.iter_id, "compiled_spec": request.compiled_spec},
            **self._role_request_defaults(
                request.run,
                request.run_dir,
                model=request.run["role_models_json"].get("tester", request.run["model"]),
            ),
        )
        return self._execute_request(request.executor, request.run, role_request)

    def _run_verifier(self, request: IterationRoleRunRequest) -> dict:
        tester_output = request.tester_output or {}
        role_request = RoleRequest(
            run_id=request.run["id"],
            role="verifier",
            prompt=self._verifier_prompt(request.compiled_spec, tester_output, request.iter_id, request.mode),
            output_schema=VERIFIER_SCHEMA,
            output_path=request.run_dir / "verifier_output.raw.json",
            sandbox="read-only",
            extra_context={"iter_id": request.iter_id, "compiled_spec": request.compiled_spec, "tester_output": tester_output},
            **self._role_request_defaults(
                request.run,
                request.run_dir,
                model=request.run["role_models_json"].get("verifier", request.run["model"]),
            ),
        )
        return self._execute_request(request.executor, request.run, role_request)

    def _run_challenger(self, request: IterationRoleRunRequest) -> dict:
        stagnation = request.stagnation or {}
        role_request = RoleRequest(
            run_id=request.run["id"],
            role="challenger",
            prompt=self._challenger_prompt(request.compiled_spec, stagnation, request.iter_id),
            output_schema=CHALLENGER_SCHEMA,
            output_path=request.run_dir / "challenger_output.raw.json",
            sandbox="read-only",
            extra_context={
                "iter_id": request.iter_id,
                "compiled_spec": request.compiled_spec,
                "stagnation_mode": stagnation["stagnation_mode"],
            },
            **self._role_request_defaults(
                request.run,
                request.run_dir,
                model=request.run["role_models_json"].get("challenger", request.run["model"]),
            ),
        )
        return self._execute_request(request.executor, request.run, role_request)

    def _ensure_not_stopped(self, run_id: str) -> None:
        if self.repository.should_stop(run_id):
            raise ExecutionStopped(f"run {run_id} was stopped")

    def _set_mode(self, run_id: str, iter_id: int, role: str, holder: dict[str, str], mode: str) -> None:
        holder["value"] = mode
        self.append_run_event(run_id, "role_degraded", {"iter": iter_id, "role": role, "mode": mode}, role=role)
        log_event(
            logger,
            logging.WARNING,
            "service.role.execution.degraded",
            "Role execution switched to a degraded mode after retries",
            run_id=run_id,
            iter=iter_id,
            role=role,
            mode=mode,
        )
