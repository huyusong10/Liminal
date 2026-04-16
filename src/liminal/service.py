from __future__ import annotations

import itertools
import json
import logging
import os
import shutil
import threading
import time
from datetime import datetime
from html import escape as escape_html
from pathlib import Path
from typing import Callable

import markdown as markdown_lib

from liminal.db import LiminalRepository
from liminal.executor import (
    CodexExecutor,
    ExecutionStopped,
    RoleRequest,
    coerce_reasoning_effort,
    executor_from_environment,
    normalize_reasoning_effort,
    validate_command_args_text,
)
from liminal.providers import executor_profile, normalize_executor_kind, normalize_executor_mode
from liminal.recovery import RecoveryResult, RetryConfig, execute_with_recovery
from liminal.settings import AppSettings, app_home, db_path, load_settings, save_recent_workdirs
from liminal.specs import SpecError, compile_markdown_spec, read_and_compile
from liminal.stagnation import update_stagnation
from liminal.utils import append_jsonl, make_id, read_json, utc_now, write_json
from liminal.workflows import (
    ARCHETYPES,
    LEGACY_ROLE_BY_ARCHETYPE,
    LEGACY_ROLE_TO_ARCHETYPE,
    WorkflowError,
    build_preset_workflow,
    display_name_for_archetype,
    normalize_role_models as workflow_normalize_role_models,
    normalize_workflow,
    preset_names,
    resolve_prompt_files,
    workflow_warnings,
)

logger = logging.getLogger(__name__)
LOOP_ROLE_NAMES = ARCHETYPES


class LiminalError(RuntimeError):
    """Domain error surfaced to CLI and API consumers."""


class RoleExecutionError(LiminalError):
    def __init__(self, role: str, result: RecoveryResult) -> None:
        self.role = role
        self.result = result
        super().__init__(f"role={role} failed after {result.attempts} attempts")


class WorkspaceSafetyError(LiminalError):
    def __init__(self, *, role: str, deleted_paths: list[str], baseline_count: int, current_count: int) -> None:
        self.role = role
        self.deleted_paths = deleted_paths
        self.baseline_count = baseline_count
        self.current_count = current_count
        preview = ", ".join(deleted_paths[:5])
        super().__init__(
            "workspace safety guard blocked a destructive rewrite: "
            f"{len(deleted_paths)} of {baseline_count} original files disappeared"
            + (f" ({preview})" if preview else "")
        )


class StopRequested(LiminalError):
    """Raised when a user asked to stop a running loop."""


def normalize_role_models(role_models: dict | None) -> dict[str, str]:
    try:
        return workflow_normalize_role_models(role_models)
    except WorkflowError as exc:
        raise LiminalError(str(exc)) from exc


class LiminalService:
    _process_active_runs: set[str] = set()
    _process_active_runs_lock = threading.Lock()

    def __init__(
        self,
        repository: LiminalRepository,
        settings: AppSettings,
        executor_factory: Callable[[], CodexExecutor] | None = None,
    ) -> None:
        self.repository = repository
        self.settings = settings
        self.executor_factory = executor_factory or executor_from_environment
        self._threads: dict[str, threading.Thread] = {}
        self._reconcile_stale_runs()

    def create_loop(
        self,
        *,
        name: str,
        spec_path: Path,
        workdir: Path,
        model: str,
        reasoning_effort: str,
        max_iters: int,
        max_role_retries: int,
        delta_threshold: float,
        trigger_window: int,
        regression_window: int,
        executor_kind: str = "codex",
        executor_mode: str = "preset",
        command_cli: str = "",
        command_args_text: str = "",
        workflow: dict | None = None,
        prompt_files: dict | None = None,
        orchestration_id: str | None = None,
        role_models: dict | None = None,
    ) -> dict:
        workdir = workdir.expanduser().resolve()
        spec_path = spec_path.expanduser()
        if spec_path.exists():
            spec_path = spec_path.resolve()
        if not workdir.exists() or not workdir.is_dir():
            raise LiminalError(f"workdir does not exist: {workdir}")
        if not spec_path.exists():
            raise LiminalError(f"spec does not exist: {spec_path}")
        if max_iters < 0:
            raise LiminalError("max_iters must be >= 0")
        if max_role_retries < 0:
            raise LiminalError("max_role_retries must be >= 0")
        if trigger_window < 1:
            raise LiminalError("trigger_window must be >= 1")
        if regression_window < 1:
            raise LiminalError("regression_window must be >= 1")

        try:
            executor_kind = normalize_executor_kind(executor_kind)
            executor_mode = normalize_executor_mode(executor_mode)
            profile = executor_profile(executor_kind)
            if executor_mode == "preset":
                command_cli = ""
                command_args_text = ""
                model = model.strip() if model.strip() else profile.default_model
                reasoning_effort = normalize_reasoning_effort(reasoning_effort, executor_kind)
            else:
                command_cli = command_cli.strip() or profile.cli_name
                validate_command_args_text(command_args_text, executor_kind=executor_kind)
                model = model.strip()
                reasoning_effort = reasoning_effort.strip()
        except ValueError as exc:
            raise LiminalError(str(exc)) from exc

        resolved_orchestration = self._resolve_orchestration_input(
            orchestration_id=orchestration_id,
            workflow=workflow,
            prompt_files=prompt_files,
            role_models=role_models,
        )
        normalized_workflow = resolved_orchestration["workflow"]
        resolved_prompt_files = resolved_orchestration["prompt_files"]

        spec_markdown, compiled_spec = read_and_compile(spec_path)
        loop_id = make_id("loop")
        loop_dir = self._ensure_loop_dir(workdir, loop_id)
        persisted_spec_path = loop_dir / "spec.md"
        persisted_spec_path.write_text(spec_markdown, encoding="utf-8")
        write_json(loop_dir / "compiled_spec.json", compiled_spec)
        self._persist_prompt_files(loop_dir, resolved_prompt_files)
        write_json(loop_dir / "workflow.json", normalized_workflow)

        payload = {
            "id": loop_id,
            "name": name,
            "workdir": str(workdir),
            "spec_path": str(spec_path.resolve()),
            "spec_markdown": spec_markdown,
            "compiled_spec": compiled_spec,
            "executor_kind": executor_kind,
            "executor_mode": executor_mode,
            "command_cli": command_cli,
            "command_args_text": command_args_text,
            "model": model,
            "reasoning_effort": reasoning_effort,
            "max_iters": max_iters,
            "max_role_retries": max_role_retries,
            "delta_threshold": delta_threshold,
            "trigger_window": trigger_window,
            "regression_window": regression_window,
            "orchestration_id": resolved_orchestration["id"],
            "orchestration_name": resolved_orchestration["name"],
            "role_models": normalize_role_models(role_models),
            "workflow": normalized_workflow,
        }
        loop = self.repository.create_loop(payload)
        self._write_recent_workdirs()
        return self._hydrate_loop_files(loop)

    def start_run(self, loop_id: str) -> dict:
        loop = self.repository.get_loop(loop_id)
        if not loop:
            raise LiminalError(f"unknown loop: {loop_id}")
        if self.repository.has_active_run_for_workdir(loop["workdir"]):
            raise LiminalError(f"another active run is already using {loop['workdir']}")

        run_id = make_id("run")
        run_dir = self._ensure_run_dir(Path(loop["workdir"]), run_id)
        (run_dir / "events.jsonl").touch()
        (run_dir / "iteration_log.jsonl").touch()
        (run_dir / "summary.md").write_text("# Liminal Run Summary\n\nQueued.\n", encoding="utf-8")
        write_json(run_dir / "workspace_baseline.json", self._capture_workspace_manifest(Path(loop["workdir"])))
        (run_dir / "compiled_spec.json").write_text(
            json.dumps(loop["compiled_spec_json"], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (run_dir / "spec.md").write_text(loop["spec_markdown"], encoding="utf-8")
        workflow = loop.get("workflow_json") or self._legacy_workflow_from_loop(loop)
        write_json(run_dir / "workflow.json", workflow)
        self._persist_prompt_files(run_dir, self._read_prompt_files_for_loop(loop["workdir"], loop["id"], workflow))

        run = self.repository.create_run(
            {
                "id": run_id,
                "loop_id": loop_id,
                "workdir": loop["workdir"],
                "spec_path": loop["spec_path"],
                "spec_markdown": loop["spec_markdown"],
                "compiled_spec": loop["compiled_spec_json"],
                "executor_kind": loop.get("executor_kind", "codex"),
                "executor_mode": loop.get("executor_mode", "preset"),
                "command_cli": loop.get("command_cli", ""),
                "command_args_text": loop.get("command_args_text", ""),
                "model": loop["model"],
                "reasoning_effort": coerce_reasoning_effort(loop["reasoning_effort"], loop.get("executor_kind", "codex")),
                "max_iters": loop["max_iters"],
                "max_role_retries": loop["max_role_retries"],
                "delta_threshold": loop["delta_threshold"],
                "trigger_window": loop["trigger_window"],
                "regression_window": loop["regression_window"],
                "orchestration_id": loop.get("orchestration_id", ""),
                "orchestration_name": loop.get("orchestration_name", ""),
                "role_models": loop["role_models_json"],
                "workflow": workflow,
                "status": "queued",
                "runs_dir": str(run_dir),
                "summary_md": "# Liminal Run Summary\n\nQueued.\n",
            }
        )
        self.repository.append_event(run_id, "run_registered", {"loop_id": loop_id, "status": "queued"})
        return self._hydrate_run_files(run)

    def _legacy_workflow_from_loop(self, loop_or_run: dict) -> dict:
        role_models = normalize_role_models(loop_or_run.get("role_models_json") or loop_or_run.get("role_models") or {})
        return build_preset_workflow("build_first", role_models=role_models)

    def _builtin_orchestration_records(self) -> list[dict]:
        labels = {
            "build_first": "Build First",
            "inspect_first": "Inspect First",
            "benchmark_loop": "Benchmark Loop",
        }
        descriptions = {
            "build_first": "Builder -> Inspector -> GateKeeper -> Guide",
            "inspect_first": "Inspector -> Builder -> GateKeeper -> Guide",
            "benchmark_loop": "GateKeeper (benchmark) -> Builder",
        }
        records = []
        for preset_name in preset_names():
            workflow = build_preset_workflow(preset_name)
            prompt_files = resolve_prompt_files(workflow)
            records.append(
                {
                    "id": f"builtin:{preset_name}",
                    "name": labels.get(preset_name, preset_name),
                    "description": descriptions.get(preset_name, ""),
                    "source": "builtin",
                    "preset": preset_name,
                    "editable": False,
                    "deletable": False,
                    "workflow_json": workflow,
                    "prompt_files_json": prompt_files,
                    "workflow_warnings": workflow_warnings(workflow),
                }
            )
        return records

    def _resolve_orchestration(self, orchestration_id: str) -> dict:
        orchestration_key = str(orchestration_id or "").strip()
        if not orchestration_key:
            raise LiminalError("orchestration_id is required")
        if orchestration_key.startswith("builtin:"):
            preset_name = orchestration_key.split(":", 1)[1]
            for record in self._builtin_orchestration_records():
                if record["id"] == orchestration_key:
                    return record
            raise LiminalError(f"unknown built-in orchestration: {preset_name}")
        record = self.repository.get_orchestration(orchestration_key)
        if not record:
            raise LiminalError(f"unknown orchestration: {orchestration_key}")
        record["source"] = "custom"
        record["editable"] = True
        record["deletable"] = True
        record["workflow_warnings"] = workflow_warnings(record.get("workflow_json") or {})
        return record

    def _resolve_orchestration_input(
        self,
        *,
        orchestration_id: str | None,
        workflow: dict | None,
        prompt_files: dict | None,
        role_models: dict | None,
    ) -> dict:
        try:
            if orchestration_id and workflow is None and not prompt_files:
                orchestration = self._resolve_orchestration(orchestration_id)
                normalized_workflow = normalize_workflow(orchestration["workflow_json"], role_models=role_models)
                resolved_prompt_files = resolve_prompt_files(normalized_workflow, orchestration.get("prompt_files_json") or {})
                return {
                    "id": orchestration["id"],
                    "name": orchestration["name"],
                    "workflow": normalized_workflow,
                    "prompt_files": resolved_prompt_files,
                }
            normalized_workflow = normalize_workflow(workflow, role_models=role_models)
            resolved_prompt_files = resolve_prompt_files(normalized_workflow, prompt_files)
        except WorkflowError as exc:
            raise LiminalError(str(exc)) from exc
        derived_id = str(orchestration_id or "").strip()
        derived_name = ""
        if derived_id:
            try:
                existing = self._resolve_orchestration(derived_id)
                derived_name = existing["name"]
            except LiminalError:
                derived_name = ""
        if not derived_id and normalized_workflow.get("preset"):
            derived_id = f"builtin:{normalized_workflow['preset']}"
            derived_name = next(
                (record["name"] for record in self._builtin_orchestration_records() if record["id"] == derived_id),
                normalized_workflow["preset"],
            )
        return {
            "id": derived_id,
            "name": derived_name,
            "workflow": normalized_workflow,
            "prompt_files": resolved_prompt_files,
        }

    def _prompt_dir(self, base_dir: Path) -> Path:
        return base_dir / "prompts"

    def _persist_prompt_files(self, base_dir: Path, prompt_files: dict[str, str]) -> None:
        prompt_dir = self._prompt_dir(base_dir)
        prompt_dir.mkdir(parents=True, exist_ok=True)
        for prompt_ref, markdown_text in sorted(prompt_files.items()):
            path = prompt_dir / prompt_ref
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(markdown_text), encoding="utf-8")

    def _read_prompt_files(self, base_dir: Path, workflow: dict) -> dict[str, str]:
        prompt_files: dict[str, str] = {}
        for role in workflow.get("roles", []):
            prompt_ref = str(role.get("prompt_ref", "")).strip()
            if not prompt_ref or prompt_ref in prompt_files:
                continue
            path = self._prompt_dir(base_dir) / prompt_ref
            if path.exists():
                prompt_files[prompt_ref] = path.read_text(encoding="utf-8")
        return resolve_prompt_files(workflow, prompt_files)

    def _read_prompt_files_for_loop(self, workdir: str, loop_id: str, workflow: dict) -> dict[str, str]:
        loop_dir = Path(workdir) / ".liminal" / "loops" / loop_id
        return self._read_prompt_files(loop_dir, workflow)

    def _read_prompt_files_for_run(self, run: dict) -> dict[str, str]:
        workflow = run.get("workflow_json") or self._legacy_workflow_from_loop(run)
        return self._read_prompt_files(Path(run["runs_dir"]), workflow)

    def _hydrate_loop_files(self, loop: dict) -> dict:
        if not loop:
            return loop
        workflow = loop.get("workflow_json") or self._legacy_workflow_from_loop(loop)
        loop["workflow_json"] = workflow
        loop["workflow_warnings"] = workflow_warnings(workflow)
        if loop.get("orchestration_id"):
            loop["orchestration"] = {
                "id": loop.get("orchestration_id"),
                "name": loop.get("orchestration_name") or loop.get("orchestration_id"),
            }
        try:
            loop["prompt_files"] = self._read_prompt_files_for_loop(loop["workdir"], loop["id"], workflow)
        except WorkflowError:
            loop["prompt_files"] = {}
        return loop

    def _hydrate_run_files(self, run: dict) -> dict:
        if not run:
            return run
        workflow = run.get("workflow_json") or self._legacy_workflow_from_loop(run)
        run["workflow_json"] = workflow
        run["workflow_warnings"] = workflow_warnings(workflow)
        if run.get("orchestration_id"):
            run["orchestration"] = {
                "id": run.get("orchestration_id"),
                "name": run.get("orchestration_name") or run.get("orchestration_id"),
            }
        try:
            run["prompt_files"] = self._read_prompt_files_for_run(run)
        except WorkflowError:
            run["prompt_files"] = {}
        return run

    def start_run_async(self, run_id: str) -> None:
        self._mark_run_active(run_id)
        thread = threading.Thread(target=self.execute_run, args=(run_id,), daemon=True, name=f"run-{run_id}")
        self._threads[run_id] = thread
        try:
            thread.start()
        except Exception:
            self._mark_run_inactive(run_id)
            self._threads.pop(run_id, None)
            raise

    def execute_run(self, run_id: str) -> dict:
        run = self.repository.get_run(run_id)
        if not run:
            raise LiminalError(f"unknown run: {run_id}")

        self._mark_run_active(run_id)
        run_dir = Path(run["runs_dir"])
        workflow = run.get("workflow_json") or self._legacy_workflow_from_loop(run)
        if workflow:
            return self._execute_workflow_run(run_id, run, run_dir, workflow)

        try:
            self.repository.update_run(run_id, runner_pid=os.getpid())
            self._wait_for_slot(run_id)
            run = self.repository.get_run(run_id)
            if not run:
                raise LiminalError(f"unknown run after queue wait: {run_id}")
            if run["status"] == "stopped":
                return run

            executor = self.executor_factory()
            compiled_spec = run["compiled_spec_json"]
            retry_config = RetryConfig(max_retries=run["max_role_retries"])
            stagnation = read_json(run_dir / "stagnation.json")
            metrics_history_path = run_dir / "metrics_history.jsonl"
            metrics_history_path.touch(exist_ok=True)
            last_iter_id = -1
            last_generator_result: dict | None = None
            last_tester_result: dict | None = None
            last_verifier_result: dict | None = None
            last_challenger_result: dict | None = None

            self.repository.append_event(run_id, "run_started", {"status": "running"})
            self._write_summary(run_id, "running", "Resolving checks for this run.")
            compiled_spec = self._resolve_run_checks(run, executor, compiled_spec, run_dir, retry_config)
            self._write_summary(run_id, "running", "Waiting for the first iteration to complete.")
            iteration_source = itertools.count() if run["max_iters"] == 0 else range(run["max_iters"])
            for iter_id in iteration_source:
                last_iter_id = iter_id
                self._ensure_not_stopped(run_id)
                self.repository.update_run(run_id, current_iter=iter_id)
                generator_mode = {"value": "default"}
                tester_mode = {"value": "default"}
                verifier_mode = {"value": "default"}

                generator_result = self._execute_role(
                    run_id,
                    iter_id,
                    "generator",
                    lambda: self._run_generator(
                        executor,
                        run,
                        compiled_spec,
                        run_dir,
                        iter_id,
                        generator_mode["value"],
                        previous_generator_result=last_generator_result,
                        previous_tester_result=last_tester_result,
                        previous_verifier_result=last_verifier_result,
                        previous_challenger_result=last_challenger_result,
                    ),
                    retry_config,
                    degrade_once=lambda: self._set_mode(run_id, iter_id, "generator", generator_mode, "conservative_changes"),
                )
                append_jsonl(
                    run_dir / "iteration_log.jsonl",
                    self._build_generator_log_entry(iter_id, generator_result, generator_mode["value"]),
                )
                self._enforce_workspace_safety(run, run_dir, iter_id, role="generator")

                tester_result = self._execute_role(
                    run_id,
                    iter_id,
                    "tester",
                    lambda: self._run_tester(
                        executor,
                        run,
                        compiled_spec,
                        run_dir,
                        iter_id,
                        tester_mode["value"],
                    ),
                    retry_config,
                    degrade_once=lambda: self._set_mode(run_id, iter_id, "tester", tester_mode, "skip_dynamic_checks"),
                )
                tester_result = self._enrich_tester_result(tester_result)
                write_json(run_dir / "tester_output.json", tester_result)
                self._enforce_workspace_safety(run, run_dir, iter_id, role="tester")

                previous_composite = last_verifier_result["composite_score"] if last_verifier_result is not None else None
                verifier_result = self._execute_role(
                    run_id,
                    iter_id,
                    "verifier",
                    lambda: self._run_verifier(
                        executor,
                        run,
                        compiled_spec,
                        run_dir,
                        iter_id,
                        tester_result,
                        verifier_mode["value"],
                    ),
                    retry_config,
                    degrade_once=lambda: self._set_mode(
                        run_id,
                        iter_id,
                        "verifier",
                        verifier_mode,
                        "strict_minimal_validation",
                    ),
                )
                verifier_result = self._enrich_verifier_result(verifier_result, compiled_spec, tester_result)
                write_json(run_dir / "verifier_verdict.json", verifier_result)
                self.repository.update_run(run_id, last_verdict=verifier_result)

                stagnation = update_stagnation(
                    stagnation,
                    verifier_result["composite_score"],
                    iter_id,
                    delta_threshold=run["delta_threshold"],
                    trigger_window=run["trigger_window"],
                    regression_window=run["regression_window"],
                )
                if stagnation["stagnation_mode"] in {"plateau", "regression"}:
                    challenger_result = self._execute_role(
                        run_id,
                        iter_id,
                        "challenger",
                        lambda: self._run_challenger(
                            executor,
                            run,
                            compiled_spec,
                            run_dir,
                            iter_id,
                            stagnation,
                        ),
                        retry_config,
                    )
                    stagnation.setdefault("challenger_triggered_at_iters", []).append(iter_id)
                    write_json(run_dir / "challenger_seed.json", challenger_result)
                    self.repository.append_event(
                        run_id,
                        "challenger_done",
                        {"iter": iter_id, "mode": challenger_result["mode"]},
                            role="challenger",
                        )
                else:
                    challenger_result = None
                write_json(run_dir / "stagnation.json", stagnation)

                append_jsonl(
                    metrics_history_path,
                    {
                        "iter": iter_id,
                        "timestamp": utc_now(),
                        "composite": verifier_result["composite_score"],
                        "score_delta": round(verifier_result["composite_score"] - previous_composite, 6)
                        if previous_composite is not None
                        else None,
                        "passed": verifier_result["passed"],
                        "metric_scores": verifier_result["metric_scores"],
                        "failed_check_ids": verifier_result.get("failed_check_ids", []),
                        "failed_check_titles": verifier_result.get("failed_check_titles", []),
                        "stagnation_mode": stagnation["stagnation_mode"],
                    },
                )
                append_jsonl(
                    run_dir / "iteration_log.jsonl",
                    self._build_iteration_log_entry(
                        iter_id,
                        generator_result,
                        tester_result,
                        verifier_result,
                        stagnation,
                        generator_mode["value"],
                        tester_mode["value"],
                        verifier_mode["value"],
                        previous_composite=previous_composite,
                        challenger_result=challenger_result,
                    ),
                )

                summary = self._build_summary(
                    run,
                    compiled_spec,
                    iter_id,
                    generator_result,
                    tester_result,
                    verifier_result,
                    stagnation,
                    generator_mode["value"],
                    tester_mode["value"],
                    verifier_mode["value"],
                    previous_composite=previous_composite,
                    challenger_result=challenger_result,
                )
                self._write_summary(run_id, "running", summary)
                last_generator_result = generator_result
                last_tester_result = tester_result
                last_verifier_result = verifier_result
                last_challenger_result = challenger_result

                if verifier_result["passed"]:
                    finished = self.repository.update_run(
                        run_id,
                        status="succeeded",
                        finished_at=utc_now(),
                        last_verdict=verifier_result,
                        summary_md=summary,
                    )
                    self._persist_summary_file(run_dir, summary)
                    self.repository.append_event(run_id, "run_finished", {"status": "succeeded", "iter": iter_id})
                    return finished

            if run["max_iters"] != 0 and last_verifier_result is not None:
                summary = self._build_summary(
                    run,
                    compiled_spec,
                    last_iter_id,
                    last_generator_result or {},
                    last_tester_result or {},
                    last_verifier_result,
                    stagnation,
                    generator_mode["value"],
                    tester_mode["value"],
                    verifier_mode["value"],
                    exhausted=True,
                    previous_composite=None,
                    challenger_result=last_challenger_result,
                )
                finished = self.repository.update_run(
                    run_id,
                    status="failed",
                    finished_at=utc_now(),
                    summary_md=summary,
                )
                self._persist_summary_file(run_dir, summary)
                self.repository.append_event(
                    run_id,
                    "run_finished",
                    {"status": "failed", "reason": "max_iters_exhausted"},
                )
                return finished
            raise LiminalError(f"run {run_id} exited without completing an iteration")
        except (StopRequested, ExecutionStopped):
            summary = "# Liminal Run Summary\n\nStopped by user.\n"
            stopped = self.repository.update_run(
                run_id,
                status="stopped",
                finished_at=utc_now(),
                summary_md=summary,
            )
            self._persist_summary_file(run_dir, summary)
            self.repository.append_event(run_id, "run_finished", {"status": "stopped"})
            return stopped
        except RoleExecutionError as exc:
            error_text = str(exc.result.error) if exc.result.error else str(exc)
            verdict = {
                "passed": False,
                "composite_score": 0.0,
                "metric_scores": {},
                "hard_constraint_violations": ["role_execution_abort"],
                "failed_check_ids": [],
                "priority_failures": [
                    {
                        "error_code": "ROLE_EXECUTION_ABORT",
                        "role": exc.role,
                        "attempts": exc.result.attempts,
                        "degraded": exc.result.degraded,
                    }
                ],
                "feedback_to_generator": "Execution aborted. Fix the failing role before retrying.",
                "verifier_confidence": "high",
            }
            write_json(run_dir / "verifier_verdict.json", verdict)
            summary = (
                "# Liminal Run Summary\n\n"
                f"Execution failed during `{exc.role}`.\n\n"
                f"Reason: `{error_text}`.\n"
            )
            failed = self.repository.update_run(
                run_id,
                status="failed",
                finished_at=utc_now(),
                error_message=error_text,
                last_verdict=verdict,
                summary_md=summary,
            )
            self._persist_summary_file(run_dir, summary)
            self.repository.append_event(
                run_id,
                "run_aborted",
                {
                    "role": exc.role,
                    "attempts": exc.result.attempts,
                    "degraded": exc.result.degraded,
                    "error": error_text,
                },
            )
            return failed
        except WorkspaceSafetyError as exc:
            error_text = str(exc)
            verdict = {
                "passed": False,
                "composite_score": 0.0,
                "metric_scores": {},
                "hard_constraint_violations": ["workspace_safety_guard"],
                "failed_check_ids": [],
                "priority_failures": [
                    {
                        "error_code": "WORKSPACE_SAFETY_GUARD",
                        "summary": "The run deleted too many original workspace files and was stopped.",
                    }
                ],
                "feedback_to_generator": (
                    "Do not bulk-delete existing user files. Keep original files in place and prefer targeted edits."
                ),
                "verifier_confidence": "high",
            }
            write_json(run_dir / "verifier_verdict.json", verdict)
            deleted_preview = ", ".join(exc.deleted_paths[:5]) if exc.deleted_paths else "none"
            summary = (
                "# Liminal Run Summary\n\n"
                "Execution stopped by the workspace safety guard.\n\n"
                f"- Original files tracked: `{exc.baseline_count}`\n"
                f"- Original files still present: `{exc.current_count}`\n"
                f"- Deleted original files: `{len(exc.deleted_paths)}`\n"
                f"- Sample deleted paths: `{deleted_preview}`\n"
            )
            failed = self.repository.update_run(
                run_id,
                status="failed",
                finished_at=utc_now(),
                error_message=error_text,
                last_verdict=verdict,
                summary_md=summary,
            )
            self._persist_summary_file(run_dir, summary)
            self.repository.append_event(
                run_id,
                "run_aborted",
                {
                    "role": exc.role,
                    "attempts": 1,
                    "degraded": False,
                    "error": error_text,
                },
            )
            return failed
        except Exception as exc:
            error_text = str(exc)
            logger.exception("run %s crashed unexpectedly", run_id)
            summary = (
                "# Liminal Run Summary\n\n"
                "Execution crashed unexpectedly.\n\n"
                f"Reason: `{error_text}`.\n"
            )
            self._persist_summary_file(run_dir, summary)
            try:
                failed = self.repository.update_run(
                    run_id,
                    status="failed",
                    finished_at=utc_now(),
                    error_message=error_text,
                    summary_md=summary,
                )
            except Exception:
                logger.exception("failed to persist crash state for %s", run_id)
                return {
                    **run,
                    "status": "failed",
                    "finished_at": utc_now(),
                    "error_message": error_text,
                    "summary_md": summary,
                }
            try:
                self.repository.append_event(
                    run_id,
                    "run_aborted",
                    {
                        "role": failed.get("active_role"),
                        "attempts": 1,
                        "degraded": False,
                        "error": error_text,
                    },
                )
            except Exception:
                logger.exception("failed to append crash event for %s", run_id)
            return failed
        finally:
            self._mark_run_inactive(run_id)
            try:
                self.repository.release_run_slot(run_id)
            except Exception:
                logger.exception("failed to release run slot for %s", run_id)
            self._threads.pop(run_id, None)

    def _execute_workflow_run(self, run_id: str, run: dict, run_dir: Path, workflow: dict) -> dict:
        try:
            self.repository.update_run(run_id, runner_pid=os.getpid())
            self._wait_for_slot(run_id)
            run = self.repository.get_run(run_id)
            if not run:
                raise LiminalError(f"unknown run after queue wait: {run_id}")
            if run["status"] == "stopped":
                return self._hydrate_run_files(run)

            executor = self.executor_factory()
            compiled_spec = run["compiled_spec_json"]
            retry_config = RetryConfig(max_retries=run["max_role_retries"])
            prompt_files = self._read_prompt_files_for_run(run)
            stagnation = read_json(run_dir / "stagnation.json")
            metrics_history_path = run_dir / "metrics_history.jsonl"
            metrics_history_path.touch(exist_ok=True)
            last_iter_id = -1
            previous_outputs_by_archetype: dict[str, dict] = {}
            last_gatekeeper_result: dict | None = None

            self.repository.append_event(run_id, "run_started", {"status": "running"})
            self._write_summary(run_id, "running", "Resolving checks for this run.")
            compiled_spec = self._resolve_run_checks(run, executor, compiled_spec, run_dir, retry_config)
            self._write_summary(run_id, "running", "Waiting for the first workflow iteration to complete.")

            enabled_steps = [step for step in workflow.get("steps", []) if step.get("enabled", True)]
            role_by_id = {role["id"]: role for role in workflow.get("roles", [])}
            iteration_source = itertools.count() if run["max_iters"] == 0 else range(run["max_iters"])

            for iter_id in iteration_source:
                last_iter_id = iter_id
                self._ensure_not_stopped(run_id)
                self.repository.update_run(run_id, current_iter=iter_id)
                step_results: list[dict] = []
                current_outputs_by_archetype: dict[str, dict] = {}
                current_outputs_by_role: dict[str, dict] = {}
                current_gatekeeper_result: dict | None = None
                current_guide_result: dict | None = None
                previous_composite = (
                    last_gatekeeper_result.get("composite_score")
                    if isinstance(last_gatekeeper_result, dict)
                    else None
                )

                for step in enabled_steps:
                    role = role_by_id[step["role_id"]]
                    runtime_role = self._runtime_role_key(role)
                    if role["archetype"] == "guide" and stagnation.get("stagnation_mode", "none") == "none":
                        continue
                    output = self._run_workflow_step(
                        executor,
                        run,
                        compiled_spec,
                        run_dir,
                        iter_id,
                        step,
                        role,
                        prompt_files,
                        current_outputs_by_role=current_outputs_by_role,
                        current_outputs_by_archetype=current_outputs_by_archetype,
                        previous_outputs_by_archetype=previous_outputs_by_archetype,
                        retry_config=retry_config,
                    )
                    normalized_output = self._normalize_step_output(
                        role["archetype"],
                        output,
                        compiled_spec=compiled_spec,
                        inspector_output=current_outputs_by_archetype.get("inspector"),
                    )
                    self._write_step_outputs(run_dir, iter_id, step, role, normalized_output)
                    current_outputs_by_role[role["id"]] = normalized_output
                    current_outputs_by_role[runtime_role] = normalized_output
                    current_outputs_by_archetype[role["archetype"]] = normalized_output
                    step_results.append(
                        {
                            "step": step,
                            "role": role,
                            "runtime_role": runtime_role,
                            "output": normalized_output,
                        }
                    )

                    if role["archetype"] in {"builder", "inspector"}:
                        self._enforce_workspace_safety(run, run_dir, iter_id, role=runtime_role)

                    if role["archetype"] == "gatekeeper":
                        current_gatekeeper_result = normalized_output
                        last_gatekeeper_result = normalized_output
                        self.repository.update_run(run_id, last_verdict=normalized_output)
                        stagnation = update_stagnation(
                            stagnation,
                            normalized_output["composite_score"],
                            iter_id,
                            delta_threshold=run["delta_threshold"],
                            trigger_window=run["trigger_window"],
                            regression_window=run["regression_window"],
                        )
                        write_json(run_dir / "stagnation.json", stagnation)
                        append_jsonl(
                            metrics_history_path,
                            {
                                "iter": iter_id,
                                "timestamp": utc_now(),
                                "composite": normalized_output["composite_score"],
                                "score_delta": round(normalized_output["composite_score"] - previous_composite, 6)
                                if previous_composite is not None
                                else None,
                                "passed": normalized_output["passed"],
                                "metric_scores": normalized_output.get("metric_scores", {}),
                                "failed_check_ids": normalized_output.get("failed_check_ids", []),
                                "failed_check_titles": normalized_output.get("failed_check_titles", []),
                                "stagnation_mode": stagnation["stagnation_mode"],
                            },
                        )
                        if normalized_output["passed"] and step.get("on_pass") == "finish_run":
                            previous_outputs_by_archetype = dict(current_outputs_by_archetype)
                            append_jsonl(
                                run_dir / "iteration_log.jsonl",
                                self._build_workflow_iteration_entry(
                                    iter_id,
                                    step_results,
                                    stagnation,
                                    previous_composite=previous_composite,
                                ),
                            )
                            summary = self._build_workflow_summary(
                                run,
                                workflow,
                                compiled_spec,
                                iter_id,
                                step_results,
                                stagnation,
                                exhausted=False,
                                previous_composite=previous_composite,
                            )
                            finished = self.repository.update_run(
                                run_id,
                                status="succeeded",
                                finished_at=utc_now(),
                                last_verdict=normalized_output,
                                summary_md=summary,
                            )
                            self._persist_summary_file(run_dir, summary)
                            self.repository.append_event(run_id, "run_finished", {"status": "succeeded", "iter": iter_id})
                            return self._hydrate_run_files(finished)
                    elif role["archetype"] == "guide":
                        current_guide_result = normalized_output
                        self.repository.append_event(
                            run_id,
                            "challenger_done",
                            {
                                "iter": iter_id,
                                "mode": normalized_output.get("mode"),
                                "step_id": step["id"],
                                "role_name": role["name"],
                                "archetype": role["archetype"],
                            },
                            role=runtime_role,
                        )

                previous_outputs_by_archetype = dict(current_outputs_by_archetype)
                append_jsonl(
                    run_dir / "iteration_log.jsonl",
                    self._build_workflow_iteration_entry(
                        iter_id,
                        step_results,
                        stagnation,
                        previous_composite=previous_composite,
                    ),
                )
                summary = self._build_workflow_summary(
                    run,
                    workflow,
                    compiled_spec,
                    iter_id,
                    step_results,
                    stagnation,
                    exhausted=False,
                    previous_composite=previous_composite,
                )
                self._write_summary(run_id, "running", summary)

            summary = self._build_workflow_summary(
                run,
                workflow,
                compiled_spec,
                last_iter_id,
                step_results if "step_results" in locals() else [],
                stagnation,
                exhausted=True,
                previous_composite=None,
            )
            failed = self.repository.update_run(
                run_id,
                status="failed",
                finished_at=utc_now(),
                summary_md=summary,
            )
            self._persist_summary_file(run_dir, summary)
            self.repository.append_event(
                run_id,
                "run_finished",
                {"status": "failed", "reason": "max_iters_exhausted"},
            )
            return self._hydrate_run_files(failed)
        except (StopRequested, ExecutionStopped):
            summary = "# Liminal Run Summary\n\nStopped by user.\n"
            stopped = self.repository.update_run(
                run_id,
                status="stopped",
                finished_at=utc_now(),
                summary_md=summary,
            )
            self._persist_summary_file(run_dir, summary)
            self.repository.append_event(run_id, "run_finished", {"status": "stopped"})
            return self._hydrate_run_files(stopped)
        except RoleExecutionError as exc:
            error_text = str(exc.result.error) if exc.result.error else str(exc)
            verdict = {
                "passed": False,
                "decision_summary": "A workflow step aborted before the run could finish.",
                "composite_score": 0.0,
                "metrics": [],
                "metric_scores": {},
                "blocking_issues": ["role_execution_abort"],
                "hard_constraint_violations": ["role_execution_abort"],
                "failed_check_ids": [],
                "priority_failures": [
                    {
                        "error_code": "ROLE_EXECUTION_ABORT",
                        "role": exc.role,
                        "attempts": exc.result.attempts,
                        "degraded": exc.result.degraded,
                    }
                ],
                "feedback_to_builder": "Fix the failing workflow step before retrying.",
                "feedback_to_generator": "Fix the failing workflow step before retrying.",
                "confidence": "high",
                "verifier_confidence": "high",
            }
            write_json(run_dir / "gatekeeper_verdict.json", verdict)
            write_json(run_dir / "verifier_verdict.json", verdict)
            summary = (
                "# Liminal Run Summary\n\n"
                f"Execution failed during `{exc.role}`.\n\n"
                f"Reason: `{error_text}`.\n"
            )
            failed = self.repository.update_run(
                run_id,
                status="failed",
                finished_at=utc_now(),
                error_message=error_text,
                last_verdict=verdict,
                summary_md=summary,
            )
            self._persist_summary_file(run_dir, summary)
            self.repository.append_event(
                run_id,
                "run_aborted",
                {
                    "role": exc.role,
                    "attempts": exc.result.attempts,
                    "degraded": exc.result.degraded,
                    "error": error_text,
                },
            )
            return self._hydrate_run_files(failed)
        except WorkspaceSafetyError as exc:
            error_text = str(exc)
            verdict = {
                "passed": False,
                "decision_summary": "The workspace safety guard stopped the run.",
                "composite_score": 0.0,
                "metrics": [],
                "metric_scores": {},
                "blocking_issues": ["workspace_safety_guard"],
                "hard_constraint_violations": ["workspace_safety_guard"],
                "failed_check_ids": [],
                "priority_failures": [
                    {
                        "error_code": "WORKSPACE_SAFETY_GUARD",
                        "summary": "The run deleted too many original workspace files and was stopped.",
                    }
                ],
                "feedback_to_builder": "Do not bulk-delete existing user files. Prefer narrow in-place edits.",
                "feedback_to_generator": "Do not bulk-delete existing user files. Prefer narrow in-place edits.",
                "confidence": "high",
                "verifier_confidence": "high",
            }
            write_json(run_dir / "gatekeeper_verdict.json", verdict)
            write_json(run_dir / "verifier_verdict.json", verdict)
            deleted_preview = ", ".join(exc.deleted_paths[:5]) if exc.deleted_paths else "none"
            summary = (
                "# Liminal Run Summary\n\n"
                "Execution stopped by the workspace safety guard.\n\n"
                f"- Original files tracked: `{exc.baseline_count}`\n"
                f"- Original files still present: `{exc.current_count}`\n"
                f"- Deleted original files: `{len(exc.deleted_paths)}`\n"
                f"- Sample deleted paths: `{deleted_preview}`\n"
            )
            failed = self.repository.update_run(
                run_id,
                status="failed",
                finished_at=utc_now(),
                error_message=error_text,
                last_verdict=verdict,
                summary_md=summary,
            )
            self._persist_summary_file(run_dir, summary)
            self.repository.append_event(
                run_id,
                "run_aborted",
                {
                    "role": exc.role,
                    "attempts": 1,
                    "degraded": False,
                    "error": error_text,
                },
            )
            return self._hydrate_run_files(failed)
        except Exception as exc:
            error_text = str(exc)
            logger.exception("run %s crashed unexpectedly", run_id)
            summary = (
                "# Liminal Run Summary\n\n"
                "Execution crashed unexpectedly.\n\n"
                f"Reason: `{error_text}`.\n"
            )
            self._persist_summary_file(run_dir, summary)
            failed = self.repository.update_run(
                run_id,
                status="failed",
                finished_at=utc_now(),
                error_message=error_text,
                summary_md=summary,
            )
            self.repository.append_event(
                run_id,
                "run_aborted",
                {
                    "role": failed.get("active_role"),
                    "attempts": 1,
                    "degraded": False,
                    "error": error_text,
                },
            )
            return self._hydrate_run_files(failed)
        finally:
            self._mark_run_inactive(run_id)
            try:
                self.repository.release_run_slot(run_id)
            except Exception:
                logger.exception("failed to release run slot for %s", run_id)
            self._threads.pop(run_id, None)

    def _run_workflow_step(
        self,
        executor: CodexExecutor,
        run: dict,
        compiled_spec: dict,
        run_dir: Path,
        iter_id: int,
        step: dict,
        role: dict,
        prompt_files: dict[str, str],
        *,
        current_outputs_by_role: dict[str, dict],
        current_outputs_by_archetype: dict[str, dict],
        previous_outputs_by_archetype: dict[str, dict],
        retry_config: RetryConfig,
    ) -> dict:
        step_dir = run_dir / "steps" / f"iter_{iter_id:03d}" / step["id"]
        step_dir.mkdir(parents=True, exist_ok=True)
        output_path = step_dir / "output.raw.json"
        prompt_text = self._build_step_prompt(
            role,
            compiled_spec,
            prompt_files[role["prompt_ref"]],
            iter_id,
            current_outputs_by_role=current_outputs_by_role,
            current_outputs_by_archetype=current_outputs_by_archetype,
            previous_outputs_by_archetype=previous_outputs_by_archetype,
        )
        request = RoleRequest(
            run_id=run["id"],
            role=self._runtime_role_key(role),
            role_archetype=role["archetype"],
            role_name=role["name"],
            step_id=step["id"],
            prompt=prompt_text,
            workdir=Path(run["workdir"]),
            executor_kind=run.get("executor_kind", "codex"),
            executor_mode=run.get("executor_mode", "preset"),
            command_cli=run.get("command_cli", ""),
            command_args_text=run.get("command_args_text", ""),
            model=str(role.get("model") or run["model"]),
            reasoning_effort=run["reasoning_effort"],
            output_schema=self._output_schema_for_archetype(role["archetype"]),
            output_path=output_path,
            run_dir=run_dir,
            sandbox=self._sandbox_for_archetype(role["archetype"]),
            idle_timeout_seconds=self.settings.role_idle_timeout_seconds,
            extra_context={
                "iter_id": iter_id,
                "compiled_spec": compiled_spec,
                "archetype": role["archetype"],
                "step_id": step["id"],
                "role_name": role["name"],
                "legacy_role": self._runtime_role_key(role),
                "current_outputs_by_role": current_outputs_by_role,
                "current_outputs_by_archetype": current_outputs_by_archetype,
                "previous_outputs_by_archetype": previous_outputs_by_archetype,
                "inspector_output": current_outputs_by_archetype.get("inspector"),
                "tester_output": current_outputs_by_archetype.get("inspector"),
                "previous_builder_result": previous_outputs_by_archetype.get("builder"),
                "previous_generator_result": previous_outputs_by_archetype.get("builder"),
                "previous_inspector_result": previous_outputs_by_archetype.get("inspector"),
                "previous_tester_result": previous_outputs_by_archetype.get("inspector"),
                "previous_gatekeeper_result": previous_outputs_by_archetype.get("gatekeeper"),
                "previous_verifier_result": previous_outputs_by_archetype.get("gatekeeper"),
                "previous_guide_result": previous_outputs_by_archetype.get("guide"),
                "previous_challenger_result": previous_outputs_by_archetype.get("guide"),
                "stagnation_mode": read_json(run_dir / "stagnation.json").get("stagnation_mode", "none"),
            },
        )
        self._record_role_request(run["id"], request)

        def execute_request() -> dict:
            return executor.execute(
                request,
                lambda event_type, payload: self.repository.append_event(
                    run["id"],
                    event_type,
                    {
                        **payload,
                        "step_id": step["id"],
                        "role_name": role["name"],
                        "archetype": role["archetype"],
                    },
                    role=role["id"],
                ),
                lambda: self.repository.should_stop(run["id"]),
                lambda pid: self.repository.update_run(run["id"], child_pid=pid)
                if pid is not None
                else self.repository.update_run(run["id"], clear_child_pid=True),
            )

        return self._execute_role(run["id"], iter_id, self._runtime_role_key(role), execute_request, retry_config)

    def _build_step_prompt(
        self,
        role: dict,
        compiled_spec: dict,
        prompt_markdown: str,
        iter_id: int,
        *,
        current_outputs_by_role: dict[str, dict],
        current_outputs_by_archetype: dict[str, dict],
        previous_outputs_by_archetype: dict[str, dict],
    ) -> str:
        prompt_metadata, prompt_body = self._parse_runtime_prompt(prompt_markdown, expected_archetype=role["archetype"])
        constraints = compiled_spec.get("constraints") or "No explicit constraints were provided."
        sections = [
            f"You are {role['name']} inside Liminal.",
            self._system_prompt_prefix(role["archetype"]),
            prompt_body,
            f"Iteration: {iter_id}",
            f"Prompt template: {prompt_metadata.get('label', role['name'])}",
            f"Goal:\n{compiled_spec.get('goal', '').strip()}",
            f"Checks:\n{self._render_checks(compiled_spec.get('checks', []))}",
            f"Constraints:\n{constraints}",
            (
                "Previous iteration evidence:\n"
                + json.dumps(previous_outputs_by_archetype, ensure_ascii=False, indent=2)
                + "\nUse this evidence as your starting point for the next change."
                if previous_outputs_by_archetype
                else ""
            ),
            "Current workflow evidence:",
            json.dumps(
                {
                    "current_outputs_by_role": current_outputs_by_role,
                    "current_outputs_by_archetype": current_outputs_by_archetype,
                    "previous_outputs_by_archetype": previous_outputs_by_archetype,
                },
                ensure_ascii=False,
                indent=2,
            ),
            self._output_contract_prompt(role["archetype"]),
        ]
        return "\n\n".join(section for section in sections if section.strip()).strip()

    def _system_prompt_prefix(self, archetype: str) -> str:
        if archetype == "builder":
            return (
                "System safety rules:\n"
                "- You may edit files inside the workdir.\n"
                "- Preserve existing non-.liminal files and avoid destructive rewrites.\n"
                "- Prefer focused, incremental changes over broad resets."
            )
        if archetype == "inspector":
            return (
                "System safety rules:\n"
                "- Collect evidence with project-owned commands, files, and artifacts.\n"
                "- Prefer concrete commands and observations.\n"
                "- Do not rewrite source files as part of inspection."
            )
        if archetype == "gatekeeper":
            return (
                "System safety rules:\n"
                "- Decide conservatively from direct evidence.\n"
                "- When evidence is weak, fail closed and explain what is missing.\n"
                "- Keep the verdict short and operational."
            )
        return (
            "System safety rules:\n"
            "- Suggest the smallest useful direction change.\n"
            "- Do not act like a second GateKeeper.\n"
            "- Keep the advice grounded in the current evidence."
        )

    def _output_contract_prompt(self, archetype: str) -> str:
        if archetype == "builder":
            return "Return JSON with attempted, abandoned, assumption, summary, and changed_files."
        if archetype == "inspector":
            return "Return JSON with execution_summary, check_results, dynamic_checks, and tester_observations."
        if archetype == "gatekeeper":
            return (
                "Return JSON with passed, decision_summary, feedback_to_builder, confidence, blocking_issues, metrics, "
                "failed_check_ids, priority_failures, and composite_score."
            )
        return "Return JSON with created_at_iter, mode, consumed, analysis, seed_question, and meta_note."

    def _parse_runtime_prompt(self, prompt_markdown: str, *, expected_archetype: str) -> tuple[dict, str]:
        try:
            from liminal.workflows import validate_prompt_markdown

            return validate_prompt_markdown(prompt_markdown, expected_archetype=expected_archetype)
        except WorkflowError as exc:
            raise LiminalError(str(exc)) from exc

    def _sandbox_for_archetype(self, archetype: str) -> str:
        if archetype == "builder":
            return "workspace-write"
        if archetype == "inspector":
            return "workspace-write"
        return "read-only"

    def _output_schema_for_archetype(self, archetype: str) -> dict:
        if archetype == "builder":
            return BUILDER_SCHEMA
        if archetype == "inspector":
            return INSPECTOR_SCHEMA
        if archetype == "gatekeeper":
            return GATEKEEPER_SCHEMA
        return GUIDE_SCHEMA

    def _normalize_step_output(
        self,
        archetype: str,
        output: dict,
        *,
        compiled_spec: dict,
        inspector_output: dict | None,
    ) -> dict:
        if archetype == "inspector":
            return self._enrich_tester_result(output)
        if archetype == "gatekeeper":
            gatekeeper_output = self._coerce_gatekeeper_output(output)
            return self._enrich_verifier_result(gatekeeper_output, compiled_spec, inspector_output or {})
        return dict(output)

    def _coerce_gatekeeper_output(self, output: dict) -> dict:
        result = dict(output)
        feedback = str(result.get("feedback_to_builder") or result.get("feedback_to_generator") or "").strip()
        confidence = str(result.get("confidence") or result.get("verifier_confidence") or "medium").strip() or "medium"
        blocking_issues = list(result.get("blocking_issues") or result.get("hard_constraint_violations") or [])
        metric_scores = result.get("metric_scores")
        if not isinstance(metric_scores, dict):
            metric_scores = {}
            for metric in list(result.get("metrics", [])):
                name = str(metric.get("name", "")).strip()
                if not name:
                    continue
                metric_scores[name] = {
                    "value": metric.get("value"),
                    "threshold": metric.get("threshold"),
                    "passed": bool(metric.get("passed")),
                }
        composite_score = result.get("composite_score")
        if composite_score is None:
            quality_metric = metric_scores.get("quality_score")
            composite_score = quality_metric.get("value") if isinstance(quality_metric, dict) else (1.0 if result.get("passed") else 0.0)
        if not result.get("metrics"):
            result["metrics"] = [
                {
                    "name": name,
                    "value": value.get("value"),
                    "threshold": value.get("threshold"),
                    "passed": value.get("passed"),
                }
                for name, value in metric_scores.items()
            ]
        result["passed"] = bool(result.get("passed", False))
        result["decision_summary"] = str(result.get("decision_summary") or "").strip() or (
            "The workflow still needs more evidence." if not result["passed"] else "All checks passed."
        )
        result["feedback_to_builder"] = feedback
        result["feedback_to_generator"] = feedback
        result["confidence"] = confidence
        result["verifier_confidence"] = confidence
        result["blocking_issues"] = blocking_issues
        result["hard_constraint_violations"] = blocking_issues
        result["metric_scores"] = metric_scores
        result["composite_score"] = float(composite_score or 0.0)
        result.setdefault("failed_check_ids", [])
        result.setdefault("priority_failures", [])
        return result

    def _write_step_outputs(self, run_dir: Path, iter_id: int, step: dict, role: dict, output: dict) -> None:
        step_dir = run_dir / "steps" / f"iter_{iter_id:03d}" / step["id"]
        step_dir.mkdir(parents=True, exist_ok=True)
        write_json(step_dir / "output.normalized.json", output)
        write_json(
            step_dir / "metadata.json",
            {
                "step_id": step["id"],
                "role_id": role["id"],
                "role_name": role["name"],
                "archetype": role["archetype"],
                "iter": iter_id,
            },
        )

        alias_paths = []
        if role["archetype"] == "builder":
            alias_paths = [run_dir / "builder_output.json", run_dir / "generator_output.json"]
        elif role["archetype"] == "inspector":
            alias_paths = [run_dir / "inspector_output.json", run_dir / "tester_output.json"]
        elif role["archetype"] == "gatekeeper":
            alias_paths = [run_dir / "gatekeeper_verdict.json", run_dir / "verifier_verdict.json"]
        elif role["archetype"] == "guide":
            alias_paths = [run_dir / "guide_output.json", run_dir / "challenger_seed.json"]
        for alias_path in alias_paths:
            write_json(alias_path, output)

    def _build_workflow_iteration_entry(
        self,
        iter_id: int,
        step_results: list[dict],
        stagnation: dict,
        *,
        previous_composite: float | None,
    ) -> dict:
        by_archetype = {
            item["role"]["archetype"]: item["output"]
            for item in step_results
        }
        gatekeeper_output = by_archetype.get("gatekeeper", {})
        entry = {
            "phase": "complete",
            "iter": iter_id,
            "timestamp": utc_now(),
            "workflow": [
                {
                    "step_id": item["step"]["id"],
                    "role_id": item["role"]["id"],
                    "runtime_role": item.get("runtime_role"),
                    "role_name": item["role"]["name"],
                    "archetype": item["role"]["archetype"],
                }
                for item in step_results
            ],
            "builder": by_archetype.get("builder", {}),
            "inspector": by_archetype.get("inspector", {}),
            "gatekeeper": gatekeeper_output,
            "guide": by_archetype.get("guide", {}),
            "score": {
                "composite": gatekeeper_output.get("composite_score"),
                "delta": round(gatekeeper_output["composite_score"] - previous_composite, 6)
                if previous_composite is not None and gatekeeper_output.get("composite_score") is not None
                else None,
                "passed": gatekeeper_output.get("passed"),
            },
            "stagnation": {
                "mode": stagnation.get("stagnation_mode", "none"),
                "recent_composites": list(stagnation.get("recent_composites", [])),
                "recent_deltas": list(stagnation.get("recent_deltas", [])),
                "consecutive_low_delta": stagnation.get("consecutive_low_delta", 0),
            },
        }
        entry["generator"] = entry["builder"]
        entry["tester"] = entry["inspector"]
        entry["verifier"] = entry["gatekeeper"]
        if entry["guide"]:
            entry["challenger"] = entry["guide"]
        return entry

    def _build_workflow_summary(
        self,
        run: dict,
        workflow: dict,
        compiled_spec: dict,
        iter_id: int,
        step_results: list[dict],
        stagnation: dict,
        *,
        exhausted: bool,
        previous_composite: float | None,
    ) -> str:
        gatekeeper_output = next((item["output"] for item in reversed(step_results) if item["role"]["archetype"] == "gatekeeper"), {})
        status_line = "Max iterations exhausted." if exhausted else "Still iterating."
        if gatekeeper_output.get("passed"):
            status_line = "All checks passed in this iteration."
        delta_text = (
            f"`{round(gatekeeper_output['composite_score'] - previous_composite, 6):+}`"
            if previous_composite is not None and gatekeeper_output.get("composite_score") is not None
            else "`n/a`"
        )
        lines = [
            "# Liminal Run Summary",
            "",
            f"- Workdir: `{run['workdir']}`",
            f"- Iteration: `{iter_id + 1 if iter_id >= 0 else 0}`",
            f"- Workflow preset: `{workflow.get('preset') or 'custom'}`",
            f"- Check mode: `{compiled_spec.get('check_mode', 'specified')}`",
            f"- Check count: `{len(compiled_spec.get('checks', []))}`",
            f"- Composite score: `{gatekeeper_output.get('composite_score', 'n/a')}`",
            f"- Score delta vs previous iteration: {delta_text}",
            f"- Passed: `{gatekeeper_output.get('passed', False)}`",
            f"- Stagnation mode: `{stagnation.get('stagnation_mode', 'none')}`",
            "",
            status_line,
        ]
        for item in step_results:
            role = item["role"]
            output = item["output"]
            heading = {
                "builder": "Generator / Builder",
                "inspector": "Tester / Inspector",
                "gatekeeper": "Verifier / GateKeeper",
                "guide": "Challenger / Guide",
            }.get(role["archetype"], role["name"])
            lines.extend(
                [
                    "",
                    f"## {heading}",
                    f"- Archetype: `{role['archetype']}`",
                    f"- Summary: {self._summary_line_for_step(role['archetype'], output)}",
                ]
            )
        lines.extend(
            [
                "",
                "## Artifacts",
                "- Inspect `workflow.json`, `iteration_log.jsonl`, `events.jsonl`, and the `steps/` directory for full details.",
            ]
        )
        return "\n".join(lines).rstrip() + "\n"

    def _summary_line_for_step(self, archetype: str, output: dict) -> str:
        if archetype == "builder":
            return self._truncate_text(output.get("attempted") or output.get("summary"), 280) or "none"
        if archetype == "inspector":
            return self._truncate_text(output.get("tester_observations"), 280) or "none"
        if archetype == "gatekeeper":
            return self._truncate_text(output.get("decision_summary"), 280) or "none"
        return self._truncate_text(output.get("seed_question") or output.get("meta_note"), 280) or "none"

    def _runtime_role_key(self, role: dict) -> str:
        if role.get("id") == role.get("archetype"):
            return LEGACY_ROLE_BY_ARCHETYPE.get(role["archetype"], role["id"])
        return role["id"]

    def stop_run(self, run_id: str) -> dict:
        self._reconcile_local_orphaned_runs()
        current = self.repository.get_run(run_id)
        if not current:
            raise LiminalError(f"unknown run: {run_id}")
        if current["status"] not in {"queued", "running"}:
            raise LiminalError(f"cannot stop run in status {current['status']}")

        run = self.repository.request_stop(run_id)
        if not run:
            raise LiminalError(f"unknown run: {run_id}")
        self.repository.append_event(run_id, "stop_requested", {"status": run["status"]})
        self.repository.send_stop_signal(run_id)
        return run

    def list_loops(self) -> list[dict]:
        self._reconcile_local_orphaned_runs()
        return [self._hydrate_loop_files(loop) for loop in self.repository.list_loops()]

    def list_orchestrations(self) -> list[dict]:
        builtins = self._builtin_orchestration_records()
        custom = []
        for record in self.repository.list_orchestrations():
            record["source"] = "custom"
            record["editable"] = True
            record["deletable"] = True
            record["workflow_warnings"] = workflow_warnings(record.get("workflow_json") or {})
            custom.append(record)
        return [*builtins, *custom]

    def get_orchestration(self, orchestration_id: str) -> dict:
        self._reconcile_local_orphaned_runs()
        return self._resolve_orchestration(orchestration_id)

    def create_orchestration(
        self,
        *,
        name: str,
        description: str = "",
        workflow: dict | None = None,
        prompt_files: dict | None = None,
        role_models: dict | None = None,
    ) -> dict:
        if not str(name or "").strip():
            raise LiminalError("name is required")
        resolved = self._resolve_orchestration_input(
            orchestration_id=None,
            workflow=workflow,
            prompt_files=prompt_files,
            role_models=role_models,
        )
        orchestration = self.repository.create_orchestration(
            {
                "id": make_id("orch"),
                "name": str(name).strip(),
                "description": str(description or "").strip(),
                "workflow": resolved["workflow"],
                "prompt_files": resolved["prompt_files"],
            }
        )
        orchestration["source"] = "custom"
        orchestration["editable"] = True
        orchestration["deletable"] = True
        orchestration["workflow_warnings"] = workflow_warnings(orchestration.get("workflow_json") or {})
        return orchestration

    def update_orchestration(
        self,
        orchestration_id: str,
        *,
        name: str,
        description: str = "",
        workflow: dict | None = None,
        prompt_files: dict | None = None,
        role_models: dict | None = None,
    ) -> dict:
        current = self.get_orchestration(orchestration_id)
        if current.get("source") == "builtin":
            raise LiminalError("built-in orchestrations cannot be updated")
        if not str(name or "").strip():
            raise LiminalError("name is required")
        resolved = self._resolve_orchestration_input(
            orchestration_id=None,
            workflow=workflow,
            prompt_files=prompt_files,
            role_models=role_models,
        )
        orchestration = self.repository.update_orchestration(
            orchestration_id,
            {
                "name": str(name).strip(),
                "description": str(description or "").strip(),
                "workflow": resolved["workflow"],
                "prompt_files": resolved["prompt_files"],
            },
        )
        if not orchestration:
            raise LiminalError(f"unknown orchestration: {orchestration_id}")
        orchestration["source"] = "custom"
        orchestration["editable"] = True
        orchestration["deletable"] = True
        orchestration["workflow_warnings"] = workflow_warnings(orchestration.get("workflow_json") or {})
        return orchestration

    def delete_orchestration(self, orchestration_id: str) -> dict:
        orchestration = self.get_orchestration(orchestration_id)
        if orchestration.get("source") == "builtin":
            raise LiminalError("built-in orchestrations cannot be deleted")
        if not self.repository.delete_orchestration(orchestration_id):
            raise LiminalError(f"unknown orchestration: {orchestration_id}")
        return orchestration

    def get_loop(self, loop_id: str) -> dict:
        self._reconcile_local_orphaned_runs()
        loop = self.repository.get_loop(loop_id)
        if not loop:
            raise LiminalError(f"unknown loop: {loop_id}")
        loop = self._hydrate_loop_files(loop)
        loop["runs"] = [self._hydrate_run_files(run) for run in self.repository.list_runs_for_loop(loop_id)]
        return loop

    def get_run(self, run_id: str) -> dict:
        self._reconcile_local_orphaned_runs()
        run = self.repository.get_run(run_id)
        if not run:
            raise LiminalError(f"unknown run: {run_id}")
        loop = self.repository.get_loop(run["loop_id"])
        if loop:
            run["loop_name"] = loop["name"]
        return self._hydrate_run_files(run)

    def get_status(self, identifier: str) -> tuple[str, dict]:
        self._reconcile_local_orphaned_runs()
        found = self.repository.get_loop_or_run(identifier)
        if not found:
            raise LiminalError(f"unknown identifier: {identifier}")
        kind, payload = found
        if kind == "loop":
            payload = self._hydrate_loop_files(payload)
            payload["runs"] = [self._hydrate_run_files(run) for run in self.repository.list_runs_for_loop(payload["id"])]
        else:
            payload = self._hydrate_run_files(payload)
        return kind, payload

    def get_runtime_activity(self) -> dict:
        self._reconcile_local_orphaned_runs()
        active_runs = self.repository.list_active_runs()
        loop_name_by_id = {
            loop["id"]: loop["name"]
            for loop in self.repository.list_loops()
        }
        running_count = 0
        queued_count = 0
        runs = []
        for run in active_runs:
            status = str(run.get("status") or "").strip()
            if status == "running":
                running_count += 1
            elif status == "queued":
                queued_count += 1
            runs.append(
                {
                    "id": run["id"],
                    "loop_id": run["loop_id"],
                    "loop_name": loop_name_by_id.get(run["loop_id"]) or run["loop_id"],
                    "status": status or "queued",
                    "active_role": run.get("active_role"),
                    "current_iter": run.get("current_iter"),
                    "workdir": run.get("workdir"),
                    "updated_at": run.get("updated_at"),
                }
            )
        return {
            "running_count": running_count,
            "queued_count": queued_count,
            "has_running_runs": running_count > 0,
            "has_active_runs": bool(active_runs),
            "runs": runs,
        }

    def rerun(self, loop_id: str, *, background: bool = False) -> dict:
        run = self.start_run(loop_id)
        if background:
            self.start_run_async(run["id"])
            return run
        return self.execute_run(run["id"])

    def delete_loop(self, loop_id: str) -> dict:
        loop = self.get_loop(loop_id)
        active_runs = [run["id"] for run in loop["runs"] if run["status"] in {"queued", "running"}]
        if active_runs:
            raise LiminalError(f"cannot delete loop with active runs: {', '.join(active_runs)}")

        paths_to_remove = [Path(run["runs_dir"]) for run in loop["runs"]]
        paths_to_remove.append(Path(loop["workdir"]) / ".liminal" / "loops" / loop_id)

        self.repository.delete_loop(loop_id)
        for path in paths_to_remove:
            shutil.rmtree(path, ignore_errors=True)
        self._write_recent_workdirs()
        return {"id": loop_id, "deleted_runs": len(loop["runs"]), "workdir": loop["workdir"]}

    def _reconcile_stale_runs(self) -> None:
        for run in self.repository.list_active_runs():
            if self._run_process_may_still_be_alive(run):
                continue
            if not self._startup_stale_run_is_recoverable(run):
                continue
            logger.warning("recovering stale run %s after startup because runner pid %s is not alive", run["id"], run.get("runner_pid"))
            summary = (
                "# Liminal Run Summary\n\n"
                "This run was marked stopped when Liminal restarted because its previous worker process was no longer alive.\n"
            )
            self._persist_summary_file(Path(run["runs_dir"]), summary)
            self.repository.update_run(
                run["id"],
                status="stopped",
                finished_at=utc_now(),
                error_message="Recovered stale run after service startup.",
                summary_md=summary,
            )
            self.repository.release_run_slot(run["id"])
            self.repository.append_event(
                run["id"],
                "run_finished",
                {"status": "stopped", "reason": "Recovered stale run after service startup."},
            )

    def _run_process_may_still_be_alive(self, run: dict) -> bool:
        pid = run.get("runner_pid")
        if run.get("status") == "queued":
            return bool(pid and self._pid_exists(pid))
        return bool(pid and self._pid_exists(pid))

    def _startup_stale_run_is_recoverable(self, run: dict) -> bool:
        if run.get("runner_pid"):
            return True
        updated_at = self._parse_run_timestamp(run.get("updated_at") or run.get("started_at") or run.get("queued_at"))
        if updated_at is None:
            return False
        age_seconds = time.time() - updated_at.timestamp()
        return age_seconds >= self._local_run_orphan_grace_seconds()

    def _reconcile_local_orphaned_runs(self) -> None:
        for run in self.repository.list_active_runs():
            self._recover_local_orphaned_run(run)

    def _recover_local_orphaned_run(self, run: dict) -> dict:
        if not self._should_recover_local_orphan(run):
            return run

        reason = "Recovered orphaned run after the local worker stopped unexpectedly."
        logger.warning(
            "recovering local orphaned run %s status=%s runner_pid=%s child_pid=%s updated_at=%s",
            run["id"],
            run.get("status"),
            run.get("runner_pid"),
            run.get("child_pid"),
            run.get("updated_at"),
        )
        summary = (
            "# Liminal Run Summary\n\n"
            "This run was marked failed because the local worker stopped unexpectedly before it could finish cleanly.\n"
        )
        child_pid = run.get("child_pid")
        if child_pid and self._pid_exists(child_pid):
            try:
                os.kill(int(child_pid), 15)
            except OSError:
                logger.exception("failed to stop orphaned child process %s for run %s", child_pid, run["id"])
        self._persist_summary_file(Path(run["runs_dir"]), summary)
        updated = self.repository.update_run(
            run["id"],
            status="failed",
            finished_at=utc_now(),
            error_message=reason,
            summary_md=summary,
        )
        self.repository.release_run_slot(run["id"])
        self.repository.append_event(
            run["id"],
            "run_aborted",
            {
                "role": run.get("active_role"),
                "attempts": 1,
                "degraded": False,
                "error": reason,
            },
        )
        return updated or run

    def _should_recover_local_orphan(self, run: dict) -> bool:
        if run.get("status") not in {"queued", "running"}:
            return False
        if self._is_run_active_locally(run["id"]):
            return False
        if run.get("runner_pid") not in {None, os.getpid()}:
            return False
        updated_at = self._parse_run_timestamp(run.get("updated_at") or run.get("started_at") or run.get("queued_at"))
        if updated_at is None:
            return False
        age_seconds = time.time() - updated_at.timestamp()
        return age_seconds >= self._local_run_orphan_grace_seconds()

    def _local_run_orphan_grace_seconds(self) -> float:
        return max(
            self.settings.stop_grace_period_seconds,
            self.settings.polling_interval_seconds * 4,
            self.settings.role_idle_timeout_seconds,
            30.0,
        )

    def _mark_run_active(self, run_id: str) -> None:
        cls = type(self)
        with cls._process_active_runs_lock:
            cls._process_active_runs.add(run_id)

    def _mark_run_inactive(self, run_id: str) -> None:
        cls = type(self)
        with cls._process_active_runs_lock:
            cls._process_active_runs.discard(run_id)

    def _is_run_active_locally(self, run_id: str) -> bool:
        cls = type(self)
        with cls._process_active_runs_lock:
            return run_id in cls._process_active_runs

    @staticmethod
    def _parse_run_timestamp(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    @staticmethod
    def _pid_exists(pid: int | None) -> bool:
        if not pid:
            return False
        try:
            os.kill(int(pid), 0)
        except (ProcessLookupError, OSError):
            return False
        except PermissionError:
            return True
        return True

    def preview_file(self, run_id: str, root: str, relative_path: str = "") -> dict:
        run = self.get_run(run_id)
        workdir = Path(run["workdir"])
        base = workdir / ".liminal" if root == "liminal" else workdir
        if root == "liminal":
            base.mkdir(parents=True, exist_ok=True)
        base_resolved = base.resolve()
        resolved = (base_resolved / relative_path).resolve()
        if not resolved.is_relative_to(base_resolved):
            raise LiminalError("requested path is outside the allowed root")
        if not resolved.exists():
            raise LiminalError(f"path does not exist: {resolved}")

        if resolved.is_dir():
            entries = []
            for child in sorted(resolved.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
                entries.append(
                    {
                        "name": child.name,
                        "path": str(child.relative_to(base)),
                        "is_dir": child.is_dir(),
                    }
                )
            return {"kind": "directory", "base": str(base), "path": relative_path, "entries": entries}

        suffix = resolved.suffix.lower()
        raw_bytes = resolved.read_bytes()
        if suffix == ".json" or suffix == ".jsonl":
            text = raw_bytes.decode("utf-8", errors="replace")
            try:
                parsed = [json.loads(line) for line in text.splitlines() if line.strip()] if suffix == ".jsonl" else json.loads(text)
                text = json.dumps(parsed, ensure_ascii=False, indent=2)
            except json.JSONDecodeError:
                pass
        elif self._looks_binary(raw_bytes):
            return {
                "kind": "file",
                "base": str(base),
                "path": relative_path,
                "name": resolved.name,
                "is_binary": True,
                "size_bytes": len(raw_bytes),
                "content": "",
            }
        else:
            text = raw_bytes.decode("utf-8", errors="replace")
        payload = {
            "kind": "file",
            "base": str(base),
            "path": relative_path,
            "name": resolved.name,
            "content": text,
            "is_binary": False,
            "size_bytes": len(raw_bytes),
        }
        if suffix in {".md", ".markdown"}:
            payload["rendered_html"] = markdown_lib.markdown(escape_html(text), extensions=["fenced_code"])
        return payload

    def _looks_binary(self, data: bytes) -> bool:
        if not data:
            return False
        sample = data[:4096]
        if b"\x00" in sample:
            return True
        allowed = {9, 10, 13}
        suspicious = sum(1 for byte in sample if byte < 32 and byte not in allowed)
        return suspicious / len(sample) > 0.1

    def stream_events(self, run_id: str, after_id: int = 0, limit: int = 200) -> list[dict]:
        self._reconcile_local_orphaned_runs()
        return self.repository.list_events(run_id, after_id=after_id, limit=limit)

    def _wait_for_slot(self, run_id: str) -> None:
        self.repository.update_run(run_id, status="queued", summary_md="# Liminal Run Summary\n\nQueued.\n")
        while True:
            self._ensure_not_stopped(run_id)
            if self.repository.claim_run_slot(run_id, self.settings.max_concurrent_runs):
                self.repository.update_run(run_id, started_at=utc_now(), status="running")
                return
            time.sleep(self.settings.polling_interval_seconds)

    def _resolve_run_checks(
        self,
        run: dict,
        executor: CodexExecutor,
        compiled_spec: dict,
        run_dir: Path,
        retry_config: RetryConfig,
    ) -> dict:
        checks = compiled_spec.get("checks", [])
        if checks:
            self.repository.append_event(
                run["id"],
                "checks_resolved",
                {"source": "specified", "count": len(checks)},
            )
            return compiled_spec

        planner_result = self._execute_role(
            run["id"],
            None,
            "check_planner",
            lambda: self._run_check_planner(executor, run, compiled_spec, run_dir),
            retry_config,
        )
        resolved_checks = self._normalize_generated_checks(planner_result.get("checks", []))
        if not resolved_checks:
            raise LiminalError("check planner returned no checks")

        resolved_spec = {
            **compiled_spec,
            "checks": resolved_checks,
            "check_mode": "auto_generated",
            "check_generation_notes": str(planner_result.get("generation_notes", "")).strip(),
        }
        write_json(run_dir / "compiled_spec.json", resolved_spec)
        write_json(
            run_dir / "auto_checks.json",
            {
                "generated_at": utc_now(),
                "count": len(resolved_checks),
                "notes": resolved_spec["check_generation_notes"],
                "checks": resolved_checks,
            },
        )
        self.repository.update_run(run["id"], compiled_spec=resolved_spec)
        self.repository.append_event(
            run["id"],
            "checks_resolved",
            {
                "source": "auto_generated",
                "count": len(resolved_checks),
                "notes": resolved_spec["check_generation_notes"],
            },
        )
        return resolved_spec

    def _execute_role(
        self,
        run_id: str,
        iter_id: int | None,
        role: str,
        fn: Callable[[], dict],
        retry_config: RetryConfig,
        degrade_once: Callable[[], None] | None = None,
    ) -> dict:
        started_at = time.perf_counter()

        def wrapped() -> dict:
            self._ensure_not_stopped(run_id)
            self.repository.update_run(run_id, active_role=role)
            start_payload = {"role": role}
            if iter_id is not None:
                start_payload["iter"] = iter_id
            self.repository.append_event(run_id, "role_started", start_payload, role=role)
            return fn()

        value, result = execute_with_recovery(wrapped, retry_config, degrade_once=degrade_once)
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        summary_payload = {
            "role": role,
            "ok": result.ok,
            "attempts": result.attempts,
            "degraded": result.degraded,
            "error": str(result.error) if result.error else None,
            "duration_ms": duration_ms,
        }
        if iter_id is not None:
            summary_payload["iter"] = iter_id
        self.repository.append_event(
            run_id,
            "role_execution_summary",
            summary_payload,
            role=role,
        )
        if not result.ok:
            raise RoleExecutionError(role, result)
        return value or {}

    def _run_generator(
        self,
        executor: CodexExecutor,
        run: dict,
        compiled_spec: dict,
        run_dir: Path,
        iter_id: int,
        mode: str,
        *,
        previous_generator_result: dict | None = None,
        previous_tester_result: dict | None = None,
        previous_verifier_result: dict | None = None,
        previous_challenger_result: dict | None = None,
    ) -> dict:
        output_path = run_dir / "generator_output.json"
        request = RoleRequest(
            run_id=run["id"],
            role="generator",
            prompt=self._generator_prompt(
                compiled_spec,
                Path(run["workdir"]),
                iter_id,
                mode,
                previous_generator_result=previous_generator_result,
                previous_tester_result=previous_tester_result,
                previous_verifier_result=previous_verifier_result,
                previous_challenger_result=previous_challenger_result,
            ),
            workdir=Path(run["workdir"]),
            executor_kind=run.get("executor_kind", "codex"),
            executor_mode=run.get("executor_mode", "preset"),
            command_cli=run.get("command_cli", ""),
            command_args_text=run.get("command_args_text", ""),
            model=run["role_models_json"].get("generator", run["model"]),
            reasoning_effort=run["reasoning_effort"],
            output_schema=GENERATOR_SCHEMA,
            output_path=output_path,
            run_dir=run_dir,
            sandbox="workspace-write",
            idle_timeout_seconds=self.settings.role_idle_timeout_seconds,
            extra_context={
                "iter_id": iter_id,
                "compiled_spec": compiled_spec,
                "previous_generator_result": previous_generator_result,
                "previous_tester_result": previous_tester_result,
                "previous_verifier_result": previous_verifier_result,
                "previous_challenger_result": previous_challenger_result,
            },
        )
        self._record_role_request(run["id"], request)
        return executor.execute(
            request,
            lambda event_type, payload: self.repository.append_event(run["id"], event_type, payload, role="generator"),
            lambda: self.repository.should_stop(run["id"]),
            lambda pid: self.repository.update_run(run["id"], child_pid=pid) if pid is not None else self.repository.update_run(run["id"], clear_child_pid=True),
        )

    def _run_check_planner(
        self,
        executor: CodexExecutor,
        run: dict,
        compiled_spec: dict,
        run_dir: Path,
    ) -> dict:
        output_path = run_dir / "check_planner_output.raw.json"
        request = RoleRequest(
            run_id=run["id"],
            role="check_planner",
            prompt=self._check_planner_prompt(compiled_spec),
            workdir=Path(run["workdir"]),
            executor_kind=run.get("executor_kind", "codex"),
            executor_mode=run.get("executor_mode", "preset"),
            command_cli=run.get("command_cli", ""),
            command_args_text=run.get("command_args_text", ""),
            model=run["model"],
            reasoning_effort=run["reasoning_effort"],
            output_schema=CHECK_PLANNER_SCHEMA,
            output_path=output_path,
            run_dir=run_dir,
            sandbox="read-only",
            idle_timeout_seconds=self.settings.role_idle_timeout_seconds,
            extra_context={"compiled_spec": compiled_spec},
        )
        self._record_role_request(run["id"], request)
        return executor.execute(
            request,
            lambda event_type, payload: self.repository.append_event(run["id"], event_type, payload, role="check_planner"),
            lambda: self.repository.should_stop(run["id"]),
            lambda pid: self.repository.update_run(run["id"], child_pid=pid) if pid is not None else self.repository.update_run(run["id"], clear_child_pid=True),
        )

    def _run_tester(
        self,
        executor: CodexExecutor,
        run: dict,
        compiled_spec: dict,
        run_dir: Path,
        iter_id: int,
        mode: str,
    ) -> dict:
        output_path = run_dir / "tester_output.raw.json"
        request = RoleRequest(
            run_id=run["id"],
            role="tester",
            prompt=self._tester_prompt(compiled_spec, iter_id, mode),
            workdir=Path(run["workdir"]),
            executor_kind=run.get("executor_kind", "codex"),
            executor_mode=run.get("executor_mode", "preset"),
            command_cli=run.get("command_cli", ""),
            command_args_text=run.get("command_args_text", ""),
            model=run["role_models_json"].get("tester", run["model"]),
            reasoning_effort=run["reasoning_effort"],
            output_schema=TESTER_SCHEMA,
            output_path=output_path,
            run_dir=run_dir,
            sandbox="workspace-write",
            idle_timeout_seconds=self.settings.role_idle_timeout_seconds,
            extra_context={"iter_id": iter_id, "compiled_spec": compiled_spec},
        )
        self._record_role_request(run["id"], request)
        return executor.execute(
            request,
            lambda event_type, payload: self.repository.append_event(run["id"], event_type, payload, role="tester"),
            lambda: self.repository.should_stop(run["id"]),
            lambda pid: self.repository.update_run(run["id"], child_pid=pid) if pid is not None else self.repository.update_run(run["id"], clear_child_pid=True),
        )

    def _run_verifier(
        self,
        executor: CodexExecutor,
        run: dict,
        compiled_spec: dict,
        run_dir: Path,
        iter_id: int,
        tester_output: dict,
        mode: str,
    ) -> dict:
        output_path = run_dir / "verifier_output.raw.json"
        request = RoleRequest(
            run_id=run["id"],
            role="verifier",
            prompt=self._verifier_prompt(compiled_spec, tester_output, iter_id, mode),
            workdir=Path(run["workdir"]),
            executor_kind=run.get("executor_kind", "codex"),
            executor_mode=run.get("executor_mode", "preset"),
            command_cli=run.get("command_cli", ""),
            command_args_text=run.get("command_args_text", ""),
            model=run["role_models_json"].get("verifier", run["model"]),
            reasoning_effort=run["reasoning_effort"],
            output_schema=VERIFIER_SCHEMA,
            output_path=output_path,
            run_dir=run_dir,
            sandbox="read-only",
            idle_timeout_seconds=self.settings.role_idle_timeout_seconds,
            extra_context={"iter_id": iter_id, "compiled_spec": compiled_spec, "tester_output": tester_output},
        )
        self._record_role_request(run["id"], request)
        return executor.execute(
            request,
            lambda event_type, payload: self.repository.append_event(run["id"], event_type, payload, role="verifier"),
            lambda: self.repository.should_stop(run["id"]),
            lambda pid: self.repository.update_run(run["id"], child_pid=pid) if pid is not None else self.repository.update_run(run["id"], clear_child_pid=True),
        )

    def _run_challenger(
        self,
        executor: CodexExecutor,
        run: dict,
        compiled_spec: dict,
        run_dir: Path,
        iter_id: int,
        stagnation: dict,
    ) -> dict:
        output_path = run_dir / "challenger_output.raw.json"
        request = RoleRequest(
            run_id=run["id"],
            role="challenger",
            prompt=self._challenger_prompt(compiled_spec, stagnation, iter_id),
            workdir=Path(run["workdir"]),
            executor_kind=run.get("executor_kind", "codex"),
            executor_mode=run.get("executor_mode", "preset"),
            command_cli=run.get("command_cli", ""),
            command_args_text=run.get("command_args_text", ""),
            model=run["role_models_json"].get("challenger", run["model"]),
            reasoning_effort=run["reasoning_effort"],
            output_schema=CHALLENGER_SCHEMA,
            output_path=output_path,
            run_dir=run_dir,
            sandbox="read-only",
            idle_timeout_seconds=self.settings.role_idle_timeout_seconds,
            extra_context={
                "iter_id": iter_id,
                "compiled_spec": compiled_spec,
                "stagnation_mode": stagnation["stagnation_mode"],
            },
        )
        self._record_role_request(run["id"], request)
        return executor.execute(
            request,
            lambda event_type, payload: self.repository.append_event(run["id"], event_type, payload, role="challenger"),
            lambda: self.repository.should_stop(run["id"]),
            lambda pid: self.repository.update_run(run["id"], child_pid=pid) if pid is not None else self.repository.update_run(run["id"], clear_child_pid=True),
        )

    def _ensure_not_stopped(self, run_id: str) -> None:
        if self.repository.should_stop(run_id):
            raise ExecutionStopped(f"run {run_id} was stopped")

    def _set_mode(self, run_id: str, iter_id: int, role: str, holder: dict[str, str], mode: str) -> None:
        holder["value"] = mode
        self.repository.append_event(run_id, "role_degraded", {"iter": iter_id, "role": role, "mode": mode}, role=role)

    def _write_summary(self, run_id: str, status: str, body: str) -> None:
        run = self.get_run(run_id)
        summary = body if body.startswith("#") else f"# Liminal Run Summary\n\nStatus: {status}\n\n{body}\n"
        self._persist_summary_file(Path(run["runs_dir"]), summary)
        self.repository.update_run(run_id, summary_md=summary)

    def _persist_summary_file(self, run_dir: Path, summary: str) -> None:
        run_dir.mkdir(parents=True, exist_ok=True)
        try:
            (run_dir / "summary.md").write_text(summary, encoding="utf-8")
        except OSError:
            logger.exception("failed to persist summary for run dir %s", run_dir)

    def _record_role_request(self, run_id: str, request: RoleRequest) -> None:
        request_dir = request.run_dir / "role_requests"
        request_dir.mkdir(parents=True, exist_ok=True)
        base_name = self._role_request_basename(request)
        prompt_path = request_dir / f"{base_name}.prompt.txt"
        prompt_path.write_text(request.prompt, encoding="utf-8")
        step_prompt_path = request.output_path.parent / "prompt.md"
        step_prompt_path.parent.mkdir(parents=True, exist_ok=True)
        step_prompt_path.write_text(request.prompt, encoding="utf-8")
        payload = {
            "timestamp": utc_now(),
            "role": request.role,
            "role_archetype": request.role_archetype,
            "role_name": request.role_name,
            "step_id": request.step_id,
            "iter": request.extra_context.get("iter_id"),
            "executor_kind": request.executor_kind,
            "executor_mode": request.executor_mode,
            "model": request.model,
            "reasoning_effort": request.reasoning_effort,
            "sandbox": request.sandbox,
            "workdir": str(request.workdir),
            "output_path": str(request.output_path),
            "prompt_path": str(prompt_path),
            "step_prompt_path": str(step_prompt_path),
            "extra_context_keys": sorted(request.extra_context.keys()),
            "context_summary": self._summarize_role_request_context(request.extra_context),
        }
        append_jsonl(request.run_dir / "role_requests.jsonl", payload)
        self.repository.append_event(run_id, "role_request_prepared", payload, role=request.role)

    def _role_request_basename(self, request: RoleRequest) -> str:
        iter_id = request.extra_context.get("iter_id")
        if isinstance(iter_id, int):
            return f"iter_{iter_id:03d}_{request.role}"
        return request.role

    def _summarize_role_request_context(self, extra_context: dict) -> dict:
        summary: dict[str, object] = {}
        iter_id = extra_context.get("iter_id")
        if iter_id is not None:
            summary["iter_id"] = iter_id
        step_id = extra_context.get("step_id")
        if step_id is not None:
            summary["step_id"] = step_id
        role_name = extra_context.get("role_name")
        if role_name is not None:
            summary["role_name"] = role_name
        archetype = extra_context.get("archetype")
        if archetype is not None:
            summary["archetype"] = archetype
        compiled_spec = extra_context.get("compiled_spec")
        if isinstance(compiled_spec, dict):
            summary["compiled_spec"] = {
                "check_mode": compiled_spec.get("check_mode"),
                "check_count": len(compiled_spec.get("checks", [])),
            }
        current_outputs_by_archetype = extra_context.get("current_outputs_by_archetype")
        if isinstance(current_outputs_by_archetype, dict) and current_outputs_by_archetype:
            summary["current_outputs_by_archetype"] = sorted(current_outputs_by_archetype.keys())
        previous_outputs_by_archetype = extra_context.get("previous_outputs_by_archetype")
        if isinstance(previous_outputs_by_archetype, dict) and previous_outputs_by_archetype:
            summary["previous_outputs_by_archetype"] = sorted(previous_outputs_by_archetype.keys())
        previous_generator_result = extra_context.get("previous_generator_result")
        if isinstance(previous_generator_result, dict) and previous_generator_result:
            summary["previous_generator_result"] = {
                "attempted": self._truncate_text(previous_generator_result.get("attempted"), 160),
                "summary": self._truncate_text(previous_generator_result.get("summary"), 160),
            }
        previous_tester_result = extra_context.get("previous_tester_result")
        if isinstance(previous_tester_result, dict) and previous_tester_result:
            summary["previous_tester_result"] = {
                "failed_items": [
                    item.get("title") or item.get("id")
                    for item in previous_tester_result.get("failed_items", [])[:4]
                ],
                "tester_observations": self._truncate_text(previous_tester_result.get("tester_observations"), 160),
            }
        previous_verifier_result = extra_context.get("previous_verifier_result")
        if isinstance(previous_verifier_result, dict) and previous_verifier_result:
            summary["previous_verifier_result"] = {
                "passed": previous_verifier_result.get("passed"),
                "composite_score": previous_verifier_result.get("composite_score"),
                "failed_check_titles": list(previous_verifier_result.get("failed_check_titles", []))[:4],
                "next_actions": list(previous_verifier_result.get("next_actions", []))[:4],
            }
        previous_challenger_result = extra_context.get("previous_challenger_result")
        if isinstance(previous_challenger_result, dict) and previous_challenger_result:
            summary["previous_challenger_result"] = {
                "mode": previous_challenger_result.get("mode"),
                "recommended_shift": self._truncate_text(
                    (previous_challenger_result.get("analysis") or {}).get("recommended_shift"),
                    160,
                ),
                "seed_question": self._truncate_text(previous_challenger_result.get("seed_question"), 160),
            }
        tester_output = extra_context.get("tester_output")
        if isinstance(tester_output, dict):
            summary["tester_output"] = {
                "passed": tester_output.get("execution_summary", {}).get("passed"),
                "failed": tester_output.get("execution_summary", {}).get("failed"),
                "dynamic_failed": len(tester_output.get("dynamic_check_failures", [])),
            }
        stagnation_mode = extra_context.get("stagnation_mode")
        if stagnation_mode is not None:
            summary["stagnation_mode"] = stagnation_mode
        return summary

    @staticmethod
    def _truncate_text(value: str | None, max_length: int = 220) -> str:
        text = str(value or "").strip()
        if len(text) <= max_length:
            return text
        return f"{text[: max_length - 1].rstrip()}..."

    @staticmethod
    def _empty_status_counts() -> dict[str, int]:
        return {"passed": 0, "failed": 0, "errored": 0, "skipped": 0}

    def _count_statuses(self, items: list[dict]) -> dict[str, int]:
        counts = self._empty_status_counts()
        for item in items:
            status = str(item.get("status", "")).strip().lower()
            if status in counts:
                counts[status] += 1
        return counts

    def _collect_non_passing_items(self, items: list[dict], *, source: str) -> list[dict]:
        failures = []
        for item in items:
            status = str(item.get("status", "")).strip().lower()
            if status == "passed":
                continue
            failures.append(
                {
                    "id": str(item.get("id", "")).strip(),
                    "title": str(item.get("title", "")).strip(),
                    "status": status or "unknown",
                    "source": source,
                    "notes": self._truncate_text(str(item.get("notes", "")).strip(), max_length=280),
                }
            )
        return failures

    def _enrich_tester_result(self, tester_result: dict) -> dict:
        result = dict(tester_result)
        check_results = list(result.get("check_results", []))
        dynamic_checks = list(result.get("dynamic_checks", []))
        check_counts = self._count_statuses(check_results)
        dynamic_counts = self._count_statuses(dynamic_checks)
        overall_counts = {
            key: check_counts.get(key, 0) + dynamic_counts.get(key, 0)
            for key in self._empty_status_counts()
        }
        failed_items = self._collect_non_passing_items(check_results, source="specified")
        failed_items.extend(self._collect_non_passing_items(dynamic_checks, source="dynamic"))
        result["status_counts"] = {
            "check_results": check_counts,
            "dynamic_checks": dynamic_counts,
            "overall": overall_counts,
        }
        result["failed_items"] = failed_items
        result["specified_check_failures"] = [item["id"] for item in failed_items if item["source"] == "specified"]
        result["dynamic_check_failures"] = [item["id"] for item in failed_items if item["source"] == "dynamic"]
        return result

    def _build_decision_summary(self, verifier_result: dict, tester_result: dict) -> str:
        reasons: list[str] = []
        failed_check_titles = list(verifier_result.get("failed_check_titles", []))
        dynamic_failures = list(tester_result.get("dynamic_check_failures", []))
        hard_constraint_violations = list(verifier_result.get("hard_constraint_violations", []))
        failing_metrics = list(verifier_result.get("failing_metrics", []))
        priority_failures = list(verifier_result.get("priority_failures", []))
        if failed_check_titles:
            reasons.append(
                "specified checks still failing: "
                + ", ".join(failed_check_titles[:3])
                + ("..." if len(failed_check_titles) > 3 else "")
            )
        if dynamic_failures:
            reasons.append(
                f"{len(dynamic_failures)} dynamic check failure"
                + ("s remain" if len(dynamic_failures) != 1 else " remains")
            )
        if hard_constraint_violations:
            reasons.append(
                f"{len(hard_constraint_violations)} hard constraint violation"
                + ("s" if len(hard_constraint_violations) != 1 else "")
            )
        if failing_metrics:
            metric_names = [str(item.get("name", "")).strip() for item in failing_metrics if item.get("name")]
            if metric_names:
                reasons.append("failing metrics: " + ", ".join(metric_names))
        if priority_failures and not reasons:
            reasons.append(
                "priority failures reported: "
                + ", ".join(self._truncate_text(item.get("summary"), 120) for item in priority_failures[:2])
            )
        if verifier_result.get("passed"):
            return "All specified and dynamic checks passed with no blocking constraint violations."
        if not reasons:
            return "The run is not yet passing because one or more checks or metrics remain below threshold."
        return "The run is not yet passing because " + "; ".join(reasons) + "."

    def _split_action_hints(self, feedback: str | None) -> list[str]:
        text = str(feedback or "").strip()
        if not text:
            return []
        hints = []
        for raw_line in text.splitlines():
            cleaned = raw_line.strip().lstrip("-*").strip()
            if cleaned:
                hints.append(cleaned)
        return hints[:5] if hints else [text]

    def _enrich_verifier_result(self, verifier_result: dict, compiled_spec: dict, tester_result: dict) -> dict:
        result = dict(verifier_result)
        check_title_map = {str(check.get("id", "")).strip(): str(check.get("title", "")).strip() for check in compiled_spec.get("checks", [])}
        failed_check_titles = [check_title_map.get(check_id, check_id) for check_id in result.get("failed_check_ids", [])]
        failing_metrics = []
        for name, metric in (result.get("metric_scores") or {}).items():
            if metric.get("passed"):
                continue
            failing_metrics.append(
                {
                    "name": name,
                    "value": metric.get("value"),
                    "threshold": metric.get("threshold"),
                }
            )
        result["failed_check_titles"] = failed_check_titles
        result["failing_metrics"] = failing_metrics
        result["hard_constraint_violation_count"] = len(result.get("hard_constraint_violations", []))
        result["priority_failure_count"] = len(result.get("priority_failures", []))
        result["decision_summary"] = self._build_decision_summary(result, tester_result)
        result["next_actions"] = self._split_action_hints(result.get("feedback_to_generator"))
        return result

    def _format_inline_code_list(self, items: list[str], *, empty: str = "none", limit: int = 5) -> str:
        values = [str(item).strip() for item in items if str(item).strip()]
        if not values:
            return empty
        visible = [f"`{item}`" for item in values[:limit]]
        if len(values) > limit:
            visible.append(f"`+{len(values) - limit} more`")
        return ", ".join(visible)

    def _format_failure_refs(self, items: list[dict], *, limit: int = 4) -> str:
        if not items:
            return "none"
        visible = []
        for item in items[:limit]:
            label = item.get("title") or item.get("id") or "unknown"
            source = item.get("source")
            if source == "dynamic":
                label = f"{label} [dynamic]"
            visible.append(f"`{label}`")
        if len(items) > limit:
            visible.append(f"`+{len(items) - limit} more`")
        return ", ".join(visible)

    def _format_metric_refs(self, metrics: list[dict], *, limit: int = 4) -> str:
        if not metrics:
            return "none"
        visible = []
        for metric in metrics[:limit]:
            name = str(metric.get("name", "")).strip() or "unknown_metric"
            value = metric.get("value")
            threshold = metric.get("threshold")
            if value is None or threshold is None:
                visible.append(f"`{name}`")
            else:
                visible.append(f"`{name}={value}` (threshold `{threshold}`)")
        if len(metrics) > limit:
            visible.append(f"`+{len(metrics) - limit} more`")
        return ", ".join(visible)

    def _build_generator_log_entry(self, iter_id: int, generator_result: dict, mode: str) -> dict:
        return {
            "phase": "generator",
            "iter": iter_id,
            "timestamp": utc_now(),
            "mode": mode,
            "attempted": generator_result.get("attempted", ""),
            "summary": generator_result.get("summary", ""),
            "assumption": generator_result.get("assumption", ""),
            "abandoned": generator_result.get("abandoned", ""),
            "changed_files": list(generator_result.get("changed_files", [])),
        }

    def _build_iteration_log_entry(
        self,
        iter_id: int,
        generator_result: dict,
        tester_result: dict,
        verifier_result: dict,
        stagnation: dict,
        generator_mode: str,
        tester_mode: str,
        verifier_mode: str,
        *,
        previous_composite: float | None,
        challenger_result: dict | None = None,
    ) -> dict:
        entry = {
            "phase": "complete",
            "iter": iter_id,
            "timestamp": utc_now(),
            "modes": {
                "generator": generator_mode,
                "tester": tester_mode,
                "verifier": verifier_mode,
            },
            "score": {
                "composite": verifier_result.get("composite_score"),
                "delta": round(verifier_result["composite_score"] - previous_composite, 6)
                if previous_composite is not None
                else None,
                "passed": verifier_result.get("passed"),
            },
            "generator": {
                "attempted": generator_result.get("attempted", ""),
                "summary": generator_result.get("summary", ""),
                "assumption": generator_result.get("assumption", ""),
                "abandoned": generator_result.get("abandoned", ""),
                "changed_files": list(generator_result.get("changed_files", [])),
            },
            "tester": {
                "execution_summary": dict(tester_result.get("execution_summary", {})),
                "status_counts": dict(tester_result.get("status_counts", {})),
                "failed_items": list(tester_result.get("failed_items", [])),
                "tester_observations": tester_result.get("tester_observations", ""),
            },
            "verifier": {
                "passed": verifier_result.get("passed"),
                "decision_summary": verifier_result.get("decision_summary", ""),
                "failed_check_ids": list(verifier_result.get("failed_check_ids", [])),
                "failed_check_titles": list(verifier_result.get("failed_check_titles", [])),
                "failing_metrics": list(verifier_result.get("failing_metrics", [])),
                "hard_constraint_violations": list(verifier_result.get("hard_constraint_violations", [])),
                "priority_failures": list(verifier_result.get("priority_failures", [])),
                "feedback_to_generator": verifier_result.get("feedback_to_generator", ""),
                "next_actions": list(verifier_result.get("next_actions", [])),
            },
            "stagnation": {
                "mode": stagnation.get("stagnation_mode", "none"),
                "recent_composites": list(stagnation.get("recent_composites", [])),
                "recent_deltas": list(stagnation.get("recent_deltas", [])),
                "consecutive_low_delta": stagnation.get("consecutive_low_delta", 0),
            },
        }
        if challenger_result is not None:
            entry["challenger"] = {
                "mode": challenger_result.get("mode"),
                "analysis": dict(challenger_result.get("analysis", {})),
                "seed_question": challenger_result.get("seed_question", ""),
                "meta_note": challenger_result.get("meta_note", ""),
            }
        return entry

    def _build_summary(
        self,
        run: dict,
        compiled_spec: dict,
        iter_id: int,
        generator_result: dict,
        tester_result: dict,
        verifier_result: dict,
        stagnation: dict,
        generator_mode: str,
        tester_mode: str,
        verifier_mode: str,
        exhausted: bool = False,
        previous_composite: float | None = None,
        challenger_result: dict | None = None,
    ) -> str:
        failed = verifier_result.get("failed_check_titles", verifier_result.get("failed_check_ids", []))
        if exhausted:
            status_line = "Max iterations exhausted."
        elif verifier_result["passed"]:
            status_line = "All checks passed in this iteration."
        else:
            status_line = "Still iterating."
        check_mode = compiled_spec.get("check_mode", "specified")
        overall_counts = tester_result.get("status_counts", {}).get("overall", self._empty_status_counts())
        dynamic_counts = tester_result.get("status_counts", {}).get("dynamic_checks", self._empty_status_counts())
        delta_text = (
            f"`{round(verifier_result['composite_score'] - previous_composite, 6):+}`"
            if previous_composite is not None
            else "`n/a`"
        )
        lines = [
            "# Liminal Run Summary",
            "",
            f"- Workdir: `{run['workdir']}`",
            f"- Iteration: `{iter_id + 1}`",
            f"- Check mode: `{check_mode}`",
            f"- Check count: `{len(compiled_spec.get('checks', []))}`",
            f"- Composite score: `{verifier_result['composite_score']}`",
            f"- Score delta vs previous iteration: {delta_text}",
            f"- Passed: `{verifier_result['passed']}`",
            f"- Stagnation mode: `{stagnation.get('stagnation_mode', 'none')}`",
            f"- Failed checks: {self._format_inline_code_list(failed, empty='none', limit=4)}",
            (
                "- Role modes: "
                f"generator=`{generator_mode}`, tester=`{tester_mode}`, verifier=`{verifier_mode}`"
            ),
            "",
            status_line,
            "",
            "## Generator",
            f"- Attempted: {self._truncate_text(generator_result.get('attempted') or generator_result.get('summary'), 280) or 'none'}",
            f"- Changed files: {self._format_inline_code_list(list(generator_result.get('changed_files', [])))}",
            f"- Assumption: {self._truncate_text(generator_result.get('assumption'), 220) or 'none'}",
            f"- Abandoned: {self._truncate_text(generator_result.get('abandoned'), 220) or 'none'}",
            "",
            "## Tester",
            (
                "- Overall statuses: "
                f"passed=`{overall_counts['passed']}`, failed=`{overall_counts['failed']}`, "
                f"errored=`{overall_counts['errored']}`, skipped=`{overall_counts['skipped']}`"
            ),
            (
                "- Dynamic checks: "
                f"passed=`{dynamic_counts['passed']}`, failed=`{dynamic_counts['failed']}`, "
                f"errored=`{dynamic_counts['errored']}`, skipped=`{dynamic_counts['skipped']}`"
            ),
            f"- Non-passing items: {self._format_failure_refs(list(tester_result.get('failed_items', [])))}",
            f"- Observations: {self._truncate_text(tester_result.get('tester_observations'), 320) or 'none'}",
            "",
            "## Verifier",
            f"- Decision: {self._truncate_text(verifier_result.get('decision_summary'), 320) or 'none'}",
            f"- Failing metrics: {self._format_metric_refs(list(verifier_result.get('failing_metrics', [])))}",
            (
                "- Hard constraint violations: "
                f"{self._format_inline_code_list(list(verifier_result.get('hard_constraint_violations', [])), empty='none', limit=3)}"
            ),
            (
                "- Priority failures: "
                f"{self._format_inline_code_list([item.get('error_code', 'unknown') for item in verifier_result.get('priority_failures', [])], empty='none', limit=4)}"
            ),
            (
                "- Next actions: "
                f"{self._format_inline_code_list(list(verifier_result.get('next_actions', [])), empty='none', limit=3)}"
            ),
        ]
        if challenger_result is not None:
            lines.extend(
                [
                    "",
                    "## Challenger",
                    f"- Mode: `{challenger_result.get('mode', 'unknown')}`",
                    f"- Recommended shift: {self._truncate_text(challenger_result.get('analysis', {}).get('recommended_shift'), 220) or 'none'}",
                    f"- Seed question: {self._truncate_text(challenger_result.get('seed_question'), 220) or 'none'}",
                ]
            )
        lines.extend(
            [
                "",
                "## Artifacts",
                "- Inspect `tester_output.json`, `verifier_verdict.json`, `iteration_log.jsonl`, and `events.jsonl` for full details.",
            ]
        )
        return "\n".join(lines).rstrip() + "\n"

    def _check_planner_prompt(self, compiled_spec: dict) -> str:
        constraints = compiled_spec.get("constraints") or "No explicit constraints were provided."
        return (
            "You are the Check Planner inside Liminal.\n"
            "The spec did not provide explicit checks, so you must derive a frozen exploratory set for this run.\n"
            "Inspect the current workdir, stay close to the stated goal, and do not invent unrelated requirements.\n"
            "Generate 3 to 5 independently judgeable checks. Prefer concise titles and practical evaluation criteria.\n"
            "Do not edit files.\n"
            f"Goal:\n{compiled_spec['goal']}\n\n"
            f"Constraints:\n{constraints}\n\n"
            "Return JSON with `checks` and `generation_notes`. Each check must include `title`, `details`, `when`, `expect`, and `fail_if`. "
            "Use empty strings only when a field truly cannot be made more specific."
        )

    def _generator_prompt(
        self,
        compiled_spec: dict,
        workdir: Path,
        iter_id: int,
        mode: str,
        *,
        previous_generator_result: dict | None = None,
        previous_tester_result: dict | None = None,
        previous_verifier_result: dict | None = None,
        previous_challenger_result: dict | None = None,
    ) -> str:
        constraints = compiled_spec.get("constraints") or "No explicit constraints were provided."
        bootstrap_guidance = ""
        action_guidance = (
            "This role must end with a concrete attempt, not only repo inspection.\n"
            "Once you have enough context to act, prefer making a focused change and/or running the most relevant existing verification, build, benchmark, or diagnosis command in the workdir.\n"
            "If the repository already contains a project-owned script that directly measures the goal, prefer using it to establish evidence in this iteration.\n"
            "If you launch a long-running project-owned command, do not wait idly for stdout alone. While it runs, inspect fresh status files, logs, reports, and intermediate artifacts so you can tell healthy progress from a harness defect.\n"
            "If those observations reveal a real process defect in the owned evaluation flow (for example stale progress snapshots, ineffective timeouts, misleading status reporting, or broken report generation), fixing that defect is in scope before the benchmark fully finishes.\n"
            "For benchmark-driven goals, prefer one real end-to-end run plus targeted harness fixes over many ad hoc spot checks.\n"
            "Do not spend the whole turn only reading files unless you are blocked by missing information that truly cannot be resolved any other way.\n\n"
        )
        if iter_id == 0 and self._is_bootstrap_workspace(workdir):
            bootstrap_guidance = (
                "Workspace state:\n"
                "Only the spec is present right now, so this iteration should bootstrap the first implementation.\n"
                "Create the smallest runnable prototype in this round instead of spending the whole turn on planning.\n"
                "Because the workspace is essentially empty, it is safe to add the first app files now; this is not permission to wipe or reset a non-empty project.\n"
                "Prefer a minimal static entry point plus tiny supporting files when needed.\n\n"
            )
        prior_iteration_feedback = self._generator_prior_iteration_feedback(
            iter_id,
            previous_generator_result=previous_generator_result,
            previous_tester_result=previous_tester_result,
            previous_verifier_result=previous_verifier_result,
            previous_challenger_result=previous_challenger_result,
        )
        return (
            "You are the Generator role inside Liminal.\n"
            "Goal: improve the workspace to satisfy the spec with one coherent change direction.\n"
            f"Iteration: {iter_id}\n"
            f"Mode: {mode}\n"
            f"Check mode: {compiled_spec.get('check_mode', 'specified')}\n"
            "You may edit files inside the workdir. Do not write into .liminal except for explicitly requested outputs.\n"
            "Treat existing non-.liminal files as user-owned. Never wipe the whole workdir, bulk-delete existing files, or reset the project from scratch.\n"
            "Prefer targeted in-place edits and additive changes. Delete a file only when that deletion is narrowly necessary to your change.\n"
            f"{action_guidance}"
            f"{bootstrap_guidance}"
            f"{prior_iteration_feedback}"
            f"Spec goal:\n{compiled_spec['goal']}\n\n"
            f"Checks:\n{self._render_checks(compiled_spec['checks'])}\n\n"
            f"Constraints:\n{constraints}\n\n"
            "Return JSON with attempted, abandoned, assumption, summary, and changed_files."
        )

    def _generator_prior_iteration_feedback(
        self,
        iter_id: int,
        *,
        previous_generator_result: dict | None = None,
        previous_tester_result: dict | None = None,
        previous_verifier_result: dict | None = None,
        previous_challenger_result: dict | None = None,
    ) -> str:
        if iter_id <= 0:
            return ""
        lines = ["Previous iteration evidence:"]
        if previous_generator_result:
            lines.append(
                f"- Last attempted: {self._truncate_text(previous_generator_result.get('attempted') or previous_generator_result.get('summary'), 220) or 'none'}"
            )
        if previous_tester_result:
            failed_items = list(previous_tester_result.get("failed_items", []))
            lines.append(
                f"- Tester observations: {self._truncate_text(previous_tester_result.get('tester_observations'), 220) or 'none'}"
            )
            lines.append(f"- Non-passing items last round: {self._format_failure_refs(failed_items)}")
        if previous_verifier_result:
            lines.append(
                f"- Verifier decision: {self._truncate_text(previous_verifier_result.get('decision_summary'), 240) or 'none'}"
            )
            lines.append(
                f"- Previous composite score: `{previous_verifier_result.get('composite_score', 'n/a')}`"
            )
            lines.append(
                "- Failed checks last round: "
                f"{self._format_inline_code_list(list(previous_verifier_result.get('failed_check_titles', []) or previous_verifier_result.get('failed_check_ids', [])), empty='none', limit=4)}"
            )
            lines.append(
                "- Next actions from verifier: "
                f"{self._format_inline_code_list(list(previous_verifier_result.get('next_actions', [])), empty='none', limit=4)}"
            )
        if previous_challenger_result:
            lines.append(
                f"- Challenger recommended shift: {self._truncate_text((previous_challenger_result.get('analysis') or {}).get('recommended_shift'), 220) or 'none'}"
            )
            lines.append(
                f"- Challenger seed question: {self._truncate_text(previous_challenger_result.get('seed_question'), 220) or 'none'}"
            )
        lines.append("Use this evidence as your starting point for the next focused improvement. Do not restart from scratch.")
        return "\n".join(lines) + "\n\n"

    def _tester_prompt(self, compiled_spec: dict, iter_id: int, mode: str) -> str:
        checks = json.dumps(compiled_spec["checks"], ensure_ascii=False, indent=2)
        return (
            "You are the Tester role inside Liminal.\n"
            "Inspect the workdir, run the most relevant commands, and evaluate the listed checks.\n"
            "Do not edit source files.\n"
            "Keep notes concise and evidence-focused. Prefer concrete commands, files, and observed outputs over restating the whole spec.\n"
            "When fresh project-owned benchmark artifacts already exist, inspect them first and reuse them as primary evidence before rerunning an expensive end-to-end flow.\n"
            "If a long-running evaluation appears stalled, confirm that with live status files, logs, or preserved artifacts instead of guessing from silent stdout alone.\n"
            f"Iteration: {iter_id}\n"
            f"Mode: {mode}\n"
            f"Checks:\n{checks}\n\n"
            "For every `check_results` item and every `dynamic_checks` item, return `id`, `title`, `status`, and `notes`.\n"
            "Return JSON with execution_summary, check_results, dynamic_checks, and tester_observations."
        )

    def _verifier_prompt(self, compiled_spec: dict, tester_output: dict, iter_id: int, mode: str) -> str:
        constraints = compiled_spec.get("constraints") or "No explicit constraints were provided."
        return (
            "You are the Verifier role inside Liminal.\n"
            "Judge the tester output conservatively against the goal, checks, and constraints.\n"
            "Keep the verdict concise and tied to direct evidence. Do not rewrite the whole spec as policy prose.\n"
            "When the main evidence comes from a project-owned benchmark or harness, treat those artifacts as primary evidence.\n"
            "Distinguish product or knowledge failures from harness-process defects, and surface harness defects as first-class failures when they block trustworthy evaluation.\n"
            f"Iteration: {iter_id}\n"
            f"Mode: {mode}\n"
            f"Goal:\n{compiled_spec['goal']}\n\n"
            f"Checks:\n{self._render_checks(compiled_spec['checks'])}\n\n"
            f"Constraints:\n{constraints}\n\n"
            f"Tester output:\n{json.dumps(tester_output, ensure_ascii=False, indent=2)}\n\n"
            "Inside `metric_scores`, provide exactly `check_pass_rate` and `quality_score`, each with `value`, `threshold`, and `passed`.\n"
            "For every `priority_failures` item, return `error_code` and `summary`.\n"
            "Return JSON with passed, composite_score, metric_scores, hard_constraint_violations, "
            "failed_check_ids, priority_failures, feedback_to_generator, and verifier_confidence."
        )

    def _challenger_prompt(self, compiled_spec: dict, stagnation: dict, iter_id: int) -> str:
        constraints = compiled_spec.get("constraints") or "No explicit constraints were provided."
        return (
            "You are the Challenger role inside Liminal.\n"
            "Suggest the smallest high-leverage direction change when progress stalls.\n"
            f"Iteration: {iter_id}\n"
            f"Spec goal:\n{compiled_spec['goal']}\n\n"
            f"Checks:\n{self._render_checks(compiled_spec['checks'])}\n\n"
            f"Constraints:\n{constraints}\n\n"
            f"Stagnation state:\n{json.dumps(stagnation, ensure_ascii=False, indent=2)}\n\n"
            "Inside `analysis`, return `stagnation_pattern`, `recommended_shift`, and `risk_note`.\n"
            "Return JSON with created_at_iter, mode, consumed, analysis, seed_question, and meta_note."
        )

    def _normalize_generated_checks(self, checks: list[dict]) -> list[dict]:
        normalized = []
        for index, raw_check in enumerate(checks, start=1):
            title = str(raw_check.get("title", "")).strip() or f"Exploratory check {index}"
            when = str(raw_check.get("when", "")).strip()
            expect = str(raw_check.get("expect", "")).strip()
            fail_if = str(raw_check.get("fail_if", "")).strip()
            details = str(raw_check.get("details", "")).strip()
            if not details:
                parts = []
                if when:
                    parts.append(f"When: {when}")
                if expect:
                    parts.append(f"Expect: {expect}")
                if fail_if:
                    parts.append(f"Fail if: {fail_if}")
                details = "\n".join(parts).strip()
            normalized.append(
                {
                    "id": f"check_{index:03d}",
                    "title": title,
                    "details": details or "Auto-generated exploratory check.",
                    "when": when,
                    "expect": expect,
                    "fail_if": fail_if,
                    "source": "auto_generated",
                }
            )
        return normalized

    def _render_checks(self, checks: list[dict]) -> str:
        return json.dumps(checks, ensure_ascii=False, indent=2)

    def _is_bootstrap_workspace(self, workdir: Path) -> bool:
        ignored_dirs = {".git", ".liminal", ".venv", "venv", "node_modules", "dist", "build", "__pycache__"}
        scanned_files = 0
        for root, dirs, files in os.walk(workdir):
            dirs[:] = [name for name in dirs if name not in ignored_dirs]
            for filename in files:
                if filename == ".DS_Store":
                    continue
                scanned_files += 1
                if scanned_files >= 200:
                    return False
                relative_path = (Path(root) / filename).relative_to(workdir).as_posix()
                if relative_path == "spec.md":
                    continue
                return False
        return True

    def _capture_workspace_manifest(self, workdir: Path) -> dict:
        files = list(self._iter_user_workspace_files(workdir))
        return {
            "captured_at": utc_now(),
            "file_count": len(files),
            "files": files,
        }

    def _iter_user_workspace_files(self, workdir: Path):
        ignored_dirs = {".git", ".liminal", ".venv", "venv", "node_modules", "dist", "build", "__pycache__"}
        ignored_files = {".DS_Store"}
        for root, dirs, files in os.walk(workdir):
            dirs[:] = [name for name in dirs if name not in ignored_dirs]
            for filename in sorted(files):
                if filename in ignored_files:
                    continue
                yield (Path(root) / filename).relative_to(workdir).as_posix()

    def _enforce_workspace_safety(self, run: dict, run_dir: Path, iter_id: int, *, role: str) -> None:
        baseline = read_json(run_dir / "workspace_baseline.json")
        baseline_files = set((baseline or {}).get("files") or [])
        if not baseline_files:
            return
        current_files = set(self._iter_user_workspace_files(Path(run["workdir"])))
        deleted_original = sorted(path for path in baseline_files if path not in current_files)
        if not deleted_original:
            return

        deleted_count = len(deleted_original)
        baseline_count = len(baseline_files)
        remaining_original = baseline_count - deleted_count
        deleted_ratio = deleted_count / baseline_count if baseline_count else 0.0
        destructive = False
        if remaining_original == 0:
            destructive = True
        elif deleted_count >= 3 and deleted_ratio >= 0.8:
            destructive = True
        elif deleted_count >= 20 and deleted_ratio >= 0.5:
            destructive = True

        if not destructive:
            return

        payload = {
            "iter": iter_id,
            "role": role,
            "baseline_file_count": baseline_count,
            "remaining_original_file_count": remaining_original,
            "deleted_original_count": deleted_count,
            "deleted_original_paths": deleted_original,
            "deleted_ratio": round(deleted_ratio, 4),
        }
        write_json(run_dir / "workspace_guard.json", payload)
        self.repository.append_event(
            run["id"],
            "workspace_guard_triggered",
            payload,
            role=role,
        )
        raise WorkspaceSafetyError(
            role=role,
            deleted_paths=deleted_original,
            baseline_count=baseline_count,
            current_count=remaining_original,
        )

    def _ensure_loop_dir(self, workdir: Path, loop_id: str) -> Path:
        path = workdir / ".liminal" / "loops" / loop_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _ensure_run_dir(self, workdir: Path, run_id: str) -> Path:
        path = workdir / ".liminal" / "runs" / run_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _write_recent_workdirs(self) -> None:
        loops = self.repository.list_loops()
        save_recent_workdirs(loop["workdir"] for loop in loops)


GENERATOR_SCHEMA = {
    "type": "object",
    "required": ["attempted", "abandoned", "assumption", "summary", "changed_files"],
    "properties": {
        "attempted": {"type": "string"},
        "abandoned": {"type": "string"},
        "assumption": {"type": "string"},
        "summary": {"type": "string"},
        "changed_files": {"type": "array", "items": {"type": "string"}},
    },
    "additionalProperties": False,
}

CHECK_PLANNER_SCHEMA = {
    "type": "object",
    "required": ["checks", "generation_notes"],
    "properties": {
        "checks": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["title", "details", "when", "expect", "fail_if"],
                "properties": {
                    "title": {"type": "string"},
                    "details": {"type": "string"},
                    "when": {"type": "string"},
                    "expect": {"type": "string"},
                    "fail_if": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
        "generation_notes": {"type": "string"},
    },
    "additionalProperties": False,
}

TESTER_SCHEMA = {
    "type": "object",
    "required": ["execution_summary", "check_results", "dynamic_checks", "tester_observations"],
    "properties": {
        "execution_summary": {
            "type": "object",
            "required": ["total_checks", "passed", "failed", "errored", "total_duration_ms"],
            "properties": {
                "total_checks": {"type": "integer"},
                "passed": {"type": "integer"},
                "failed": {"type": "integer"},
                "errored": {"type": "integer"},
                "total_duration_ms": {"type": "integer"},
            },
            "additionalProperties": False,
        },
        "check_results": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "title", "status", "notes"],
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "status": {"type": "string", "enum": ["passed", "failed", "errored", "skipped"]},
                    "notes": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
        "dynamic_checks": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "title", "status", "notes"],
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "status": {"type": "string", "enum": ["passed", "failed", "errored", "skipped"]},
                    "notes": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
        "tester_observations": {"type": "string"},
    },
    "additionalProperties": False,
}

VERIFIER_SCHEMA = {
    "type": "object",
    "required": [
        "passed",
        "decision_summary",
        "composite_score",
        "metrics",
        "metric_scores",
        "blocking_issues",
        "hard_constraint_violations",
        "failed_check_ids",
        "priority_failures",
        "feedback_to_builder",
        "feedback_to_generator",
        "confidence",
        "verifier_confidence",
    ],
    "properties": {
        "passed": {"type": "boolean"},
        "decision_summary": {"type": "string"},
        "composite_score": {"type": "number"},
        "metrics": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "value", "threshold", "passed"],
                "properties": {
                    "name": {"type": "string"},
                    "value": {"type": "number"},
                    "threshold": {"type": "number"},
                    "passed": {"type": "boolean"},
                },
                "additionalProperties": False,
            },
        },
        "metric_scores": {
            "type": "object",
            "required": ["check_pass_rate", "quality_score"],
            "properties": {
                "check_pass_rate": {
                    "type": "object",
                    "required": ["value", "threshold", "passed"],
                    "properties": {
                        "value": {"type": "number"},
                        "threshold": {"type": "number"},
                        "passed": {"type": "boolean"},
                    },
                    "additionalProperties": False,
                },
                "quality_score": {
                    "type": "object",
                    "required": ["value", "threshold", "passed"],
                    "properties": {
                        "value": {"type": "number"},
                        "threshold": {"type": "number"},
                        "passed": {"type": "boolean"},
                    },
                    "additionalProperties": False,
                },
            },
            "additionalProperties": False,
        },
        "blocking_issues": {"type": "array", "items": {"type": "string"}},
        "hard_constraint_violations": {"type": "array", "items": {"type": "string"}},
        "failed_check_ids": {"type": "array", "items": {"type": "string"}},
        "priority_failures": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["error_code", "summary"],
                "properties": {
                    "error_code": {"type": "string"},
                    "summary": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
        "feedback_to_builder": {"type": "string"},
        "feedback_to_generator": {"type": "string"},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "verifier_confidence": {"type": "string", "enum": ["low", "medium", "high"]},
    },
    "additionalProperties": False,
}

CHALLENGER_SCHEMA = {
    "type": "object",
    "required": ["created_at_iter", "mode", "consumed", "analysis", "seed_question", "meta_note"],
    "properties": {
        "created_at_iter": {"type": "integer"},
        "mode": {"type": "string"},
        "consumed": {"type": "boolean"},
        "analysis": {
            "type": "object",
            "required": ["stagnation_pattern", "recommended_shift", "risk_note"],
            "properties": {
                "stagnation_pattern": {"type": "string"},
                "recommended_shift": {"type": "string"},
                "risk_note": {"type": "string"},
            },
            "additionalProperties": False,
        },
        "seed_question": {"type": "string"},
        "meta_note": {"type": "string"},
    },
    "additionalProperties": False,
}

BUILDER_SCHEMA = GENERATOR_SCHEMA
INSPECTOR_SCHEMA = TESTER_SCHEMA
GATEKEEPER_SCHEMA = VERIFIER_SCHEMA
GUIDE_SCHEMA = CHALLENGER_SCHEMA


def create_service(executor_factory: Callable[[], CodexExecutor] | None = None) -> LiminalService:
    return LiminalService(
        repository=LiminalRepository(db_path()),
        settings=load_settings(),
        executor_factory=executor_factory,
    )
