from __future__ import annotations

import logging
from pathlib import Path

from loopora.context_flow import build_run_contract_snapshot
from loopora.diagnostics import log_event
from loopora.evidence_coverage import with_coverage_targets, write_evidence_coverage_projection
from loopora.executor import coerce_reasoning_effort, normalize_reasoning_effort, validate_command_args_text
from loopora.providers import executor_profile, normalize_executor_kind, normalize_executor_mode
from loopora.run_artifacts import INITIAL_STAGNATION_STATE, write_json_with_mirrors, write_text_with_mirrors
from loopora.service_asset_common import _normalize_role_models, logger
from loopora.service_types import LooporaConflictError, LooporaError, LooporaNotFoundError, normalize_completion_mode
from loopora.utils import make_id, write_json
from loopora.workflows import has_finish_gatekeeper_step


class ServiceRunRegistrationMixin:
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
        completion_mode: str = "gatekeeper",
        iteration_interval_seconds: float = 0.0,
    ) -> dict:
        log_event(
            logger,
            logging.INFO,
            "service.loop.create.requested",
            "Received loop creation request",
            workdir=workdir,
            spec_path=spec_path,
            orchestration_id=orchestration_id,
            completion_mode=completion_mode,
            max_iters=max_iters,
            executor_kind=executor_kind,
            executor_mode=executor_mode,
        )
        workdir = workdir.expanduser().resolve()
        spec_path = spec_path.expanduser()
        if spec_path.exists():
            spec_path = spec_path.resolve()
        if not workdir.exists() or not workdir.is_dir():
            raise LooporaError(f"workdir does not exist: {workdir}")
        if not spec_path.exists():
            raise LooporaError(f"spec does not exist: {spec_path}")
        if max_iters < 0:
            raise LooporaError("max_iters must be >= 0")
        if max_role_retries < 0:
            raise LooporaError("max_role_retries must be >= 0")
        if iteration_interval_seconds < 0:
            raise LooporaError("iteration_interval_seconds must be >= 0")
        if trigger_window < 1:
            raise LooporaError("trigger_window must be >= 1")
        if regression_window < 1:
            raise LooporaError("regression_window must be >= 1")

        try:
            executor_kind = normalize_executor_kind(executor_kind)
            executor_mode = normalize_executor_mode(executor_mode)
            profile = executor_profile(executor_kind)
            if profile.command_only and executor_mode != "command":
                raise ValueError(f"{profile.label} only supports command mode")
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
            completion_mode = normalize_completion_mode(completion_mode)
        except ValueError as exc:
            raise LooporaError(str(exc)) from exc

        resolved_orchestration = self._asset_call(
            self.asset_catalog.resolve_orchestration_input,
            orchestration_id=orchestration_id,
            workflow=workflow,
            prompt_files=prompt_files,
            role_models=role_models,
        )
        normalized_workflow = resolved_orchestration["workflow"]
        resolved_prompt_files = resolved_orchestration["prompt_files"]
        if completion_mode == "gatekeeper" and not has_finish_gatekeeper_step(normalized_workflow):
            raise LooporaError(
                "gatekeeper completion mode requires a GateKeeper step that can finish the run"
            )

        spec_markdown, compiled_spec = self._read_and_compile_spec(spec_path)
        compiled_spec = with_coverage_targets(compiled_spec, completion_mode=completion_mode)
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
            "completion_mode": completion_mode,
            "iteration_interval_seconds": iteration_interval_seconds,
            "max_iters": max_iters,
            "max_role_retries": max_role_retries,
            "delta_threshold": delta_threshold,
            "trigger_window": trigger_window,
            "regression_window": regression_window,
            "orchestration_id": resolved_orchestration["id"],
            "orchestration_name": resolved_orchestration["name"],
            "role_models": _normalize_role_models(role_models),
            "workflow": normalized_workflow,
        }
        loop = self.repository.create_loop(payload)
        self._write_recent_workdirs()
        log_event(
            logger,
            logging.INFO,
            "service.loop.created",
            "Created loop definition",
            **self._loop_log_context(
                loop,
                spec_path=loop["spec_path"],
                loop_name=loop["name"],
                completion_mode=loop["completion_mode"],
            ),
        )
        return self._hydrate_loop_files(loop)

    @staticmethod
    def _read_and_compile_spec(spec_path: Path) -> tuple[str, dict]:
        from loopora.specs import read_and_compile

        return read_and_compile(spec_path)

    def start_run(self, loop_id: str) -> dict:
        loop = self.repository.get_loop(loop_id)
        if not loop:
            raise LooporaNotFoundError(f"unknown loop: {loop_id}")
        log_event(
            logger,
            logging.INFO,
            "service.run.start.requested",
            "Received run start request",
            **self._loop_log_context(loop),
        )
        if self.repository.has_active_run_for_workdir(loop["workdir"]):
            raise LooporaConflictError(f"another active run is already using {loop['workdir']}")

        run_id = make_id("run")
        run_dir = self._ensure_run_dir(Path(loop["workdir"]), run_id)
        workflow = loop.get("workflow_json") or self._legacy_workflow_from_loop(loop)
        layout = self._run_artifact_layout(run_dir)
        layout.initialize()
        queued_summary = "# Loopora Run Summary\n\nQueued.\n"
        workspace_baseline = self._capture_workspace_manifest(Path(loop["workdir"]))
        prompt_files = self._read_prompt_files_for_loop(loop["workdir"], loop["id"], workflow)
        write_text_with_mirrors(layout.summary_path, queued_summary)
        write_json_with_mirrors(layout.workspace_baseline_path, workspace_baseline)
        write_json_with_mirrors(
            layout.timeline_stagnation_path,
            dict(INITIAL_STAGNATION_STATE),
            mirror_paths=[layout.run_dir / "stagnation.json"],
        )
        compiled_spec = with_coverage_targets(
            loop["compiled_spec_json"],
            completion_mode=str(loop.get("completion_mode", "gatekeeper")),
        )
        write_json_with_mirrors(layout.contract_compiled_spec_path, compiled_spec)
        write_text_with_mirrors(layout.contract_spec_path, loop["spec_markdown"])
        write_json_with_mirrors(layout.contract_workflow_path, workflow)
        self._persist_prompt_files(layout.contract_dir, prompt_files)

        run_contract = build_run_contract_snapshot(
            {
                "id": run_id,
                "loop_id": loop_id,
                "workdir": loop["workdir"],
                "completion_mode": loop.get("completion_mode", "gatekeeper"),
                "max_iters": loop["max_iters"],
                "max_role_retries": loop["max_role_retries"],
                "delta_threshold": loop["delta_threshold"],
                "trigger_window": loop["trigger_window"],
                "regression_window": loop["regression_window"],
                "iteration_interval_seconds": loop.get("iteration_interval_seconds", 0.0),
                "executor_kind": loop.get("executor_kind", "codex"),
                "executor_mode": loop.get("executor_mode", "preset"),
                "model": loop["model"],
                "reasoning_effort": coerce_reasoning_effort(
                    loop["reasoning_effort"],
                    loop.get("executor_kind", "codex"),
                ),
            },
            compiled_spec=compiled_spec,
            workflow=workflow,
            prompt_files=prompt_files,
            workspace_baseline=workspace_baseline,
            layout=layout,
        )
        write_json_with_mirrors(layout.run_contract_path, run_contract)
        write_evidence_coverage_projection(layout)

        run = self.repository.create_run(
            {
                "id": run_id,
                "loop_id": loop_id,
                "workdir": loop["workdir"],
                "spec_path": loop["spec_path"],
                "spec_markdown": loop["spec_markdown"],
                "compiled_spec": compiled_spec,
                "executor_kind": loop.get("executor_kind", "codex"),
                "executor_mode": loop.get("executor_mode", "preset"),
                "command_cli": loop.get("command_cli", ""),
                "command_args_text": loop.get("command_args_text", ""),
                "model": loop["model"],
                "reasoning_effort": coerce_reasoning_effort(
                    loop["reasoning_effort"],
                    loop.get("executor_kind", "codex"),
                ),
                "completion_mode": loop.get("completion_mode", "gatekeeper"),
                "iteration_interval_seconds": loop.get("iteration_interval_seconds", 0.0),
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
                "summary_md": queued_summary,
            }
        )
        self.append_run_event(run_id, "run_registered", {"loop_id": loop_id, "status": "queued"})
        log_event(
            logger,
            logging.INFO,
            "service.run.registered",
            "Registered queued run",
            **self._run_log_context(run, status=run["status"]),
        )
        return self._hydrate_run_files(run)
