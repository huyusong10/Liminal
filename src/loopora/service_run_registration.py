from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from loopora.context_flow import RunContractSnapshotRequest, build_run_contract_snapshot
from loopora.diagnostics import log_event
from loopora.evidence_coverage import with_coverage_targets, write_evidence_coverage_projection
from loopora.executor import coerce_reasoning_effort, normalize_reasoning_effort, validate_command_args_text
from loopora.providers import executor_profile, normalize_executor_kind, normalize_executor_mode
from loopora.run_artifacts import INITIAL_STAGNATION_STATE, write_json_with_mirrors, write_text_with_mirrors
from loopora.service_asset_common import _normalize_role_models, logger
from loopora.service_types import LooporaConflictError, LooporaError, LooporaNotFoundError, normalize_completion_mode
from loopora.utils import make_id, write_json
from loopora.workflows import has_finish_gatekeeper_step


@dataclass(frozen=True, kw_only=True)
class LoopCreateRequest:
    name: str
    spec_path: Path
    workdir: Path
    model: str
    reasoning_effort: str
    max_iters: int
    max_role_retries: int
    delta_threshold: float
    trigger_window: int
    regression_window: int
    executor_kind: str = "codex"
    executor_mode: str = "preset"
    command_cli: str = ""
    command_args_text: str = ""
    workflow: dict | None = None
    prompt_files: dict | None = None
    orchestration_id: str | None = None
    role_models: dict | None = None
    completion_mode: str = "gatekeeper"
    iteration_interval_seconds: float = 0.0


@dataclass(frozen=True, kw_only=True)
class LoopDefinitionFiles:
    workdir: Path
    loop_id: str
    spec_markdown: str
    compiled_spec: dict
    prompt_files: dict
    workflow: dict


@dataclass(frozen=True, kw_only=True)
class ResolvedLoopCreate:
    request: LoopCreateRequest
    loop_id: str
    spec_markdown: str
    compiled_spec: dict
    resolved_orchestration: dict
    workflow: dict


def _coerce_loop_create_request(
    request: LoopCreateRequest | None,
    raw_request: dict[str, Any],
) -> LoopCreateRequest:
    if request is not None and raw_request:
        raise TypeError("loop create request cannot mix object and keyword fields")
    return request or LoopCreateRequest(**raw_request)


def _normalize_loop_create_request(request: LoopCreateRequest) -> LoopCreateRequest:
    workdir, spec_path = _normalize_loop_paths(request.workdir, request.spec_path)
    _validate_loop_limits(request)
    return replace(
        request,
        workdir=workdir,
        spec_path=spec_path,
        **_normalize_loop_executor_settings(request),
    )


def _normalize_loop_paths(workdir: Path, spec_path: Path) -> tuple[Path, Path]:
    normalized_workdir = workdir.expanduser().resolve()
    normalized_spec_path = spec_path.expanduser()
    if normalized_spec_path.exists():
        normalized_spec_path = normalized_spec_path.resolve()
    if not normalized_workdir.exists() or not normalized_workdir.is_dir():
        raise LooporaError(f"workdir does not exist: {normalized_workdir}")
    if not normalized_spec_path.exists():
        raise LooporaError(f"spec does not exist: {normalized_spec_path}")
    return normalized_workdir, normalized_spec_path


def _validate_loop_limits(request: LoopCreateRequest) -> None:
    if request.max_iters < 0:
        raise LooporaError("max_iters must be >= 0")
    if request.max_role_retries < 0:
        raise LooporaError("max_role_retries must be >= 0")
    if request.iteration_interval_seconds < 0:
        raise LooporaError("iteration_interval_seconds must be >= 0")
    if request.trigger_window < 1:
        raise LooporaError("trigger_window must be >= 1")
    if request.regression_window < 1:
        raise LooporaError("regression_window must be >= 1")


def _normalize_loop_executor_settings(request: LoopCreateRequest) -> dict[str, str]:
    try:
        executor_kind = normalize_executor_kind(request.executor_kind)
        executor_mode = normalize_executor_mode(request.executor_mode)
        profile = executor_profile(executor_kind)
        if profile.command_only and executor_mode != "command":
            raise ValueError(f"{profile.label} only supports command mode")
        if executor_mode == "preset":
            return {
                "executor_kind": executor_kind,
                "executor_mode": executor_mode,
                "command_cli": "",
                "command_args_text": "",
                "model": request.model.strip() if request.model.strip() else profile.default_model,
                "reasoning_effort": normalize_reasoning_effort(request.reasoning_effort, executor_kind),
                "completion_mode": normalize_completion_mode(request.completion_mode),
            }
        command_cli = request.command_cli.strip() or profile.cli_name
        validate_command_args_text(request.command_args_text, executor_kind=executor_kind)
        return {
            "executor_kind": executor_kind,
            "executor_mode": executor_mode,
            "command_cli": command_cli,
            "command_args_text": request.command_args_text,
            "model": request.model.strip(),
            "reasoning_effort": request.reasoning_effort.strip(),
            "completion_mode": normalize_completion_mode(request.completion_mode),
        }
    except ValueError as exc:
        raise LooporaError(str(exc)) from exc


def _loop_create_payload(resolved: ResolvedLoopCreate) -> dict:
    request = resolved.request
    return {
        "id": resolved.loop_id,
        "name": request.name,
        "workdir": str(request.workdir),
        "spec_path": str(request.spec_path.resolve()),
        "spec_markdown": resolved.spec_markdown,
        "compiled_spec": resolved.compiled_spec,
        "executor_kind": request.executor_kind,
        "executor_mode": request.executor_mode,
        "command_cli": request.command_cli,
        "command_args_text": request.command_args_text,
        "model": request.model,
        "reasoning_effort": request.reasoning_effort,
        "completion_mode": request.completion_mode,
        "iteration_interval_seconds": request.iteration_interval_seconds,
        "max_iters": request.max_iters,
        "max_role_retries": request.max_role_retries,
        "delta_threshold": request.delta_threshold,
        "trigger_window": request.trigger_window,
        "regression_window": request.regression_window,
        "orchestration_id": resolved.resolved_orchestration["id"],
        "orchestration_name": resolved.resolved_orchestration["name"],
        "role_models": _normalize_role_models(request.role_models),
        "workflow": resolved.workflow,
    }


class ServiceRunRegistrationMixin:
    def create_loop(
        self,
        request: LoopCreateRequest | None = None,
        **raw_request: Any,
    ) -> dict:
        loop_request = _coerce_loop_create_request(request, raw_request)
        self._log_loop_create_requested(loop_request)
        normalized_request = _normalize_loop_create_request(loop_request)
        resolved_orchestration = self._resolve_loop_orchestration(normalized_request)
        normalized_workflow = resolved_orchestration["workflow"]
        self._validate_loop_completion_workflow(
            completion_mode=normalized_request.completion_mode,
            workflow=normalized_workflow,
        )
        spec_markdown, compiled_spec = self._read_loop_spec_with_coverage(
            normalized_request.spec_path,
            completion_mode=normalized_request.completion_mode,
        )
        loop_id = make_id("loop")
        self._persist_loop_definition_files(
            LoopDefinitionFiles(
                workdir=normalized_request.workdir,
                loop_id=loop_id,
                spec_markdown=spec_markdown,
                compiled_spec=compiled_spec,
                prompt_files=resolved_orchestration["prompt_files"],
                workflow=normalized_workflow,
            )
        )

        loop = self.repository.create_loop(
            _loop_create_payload(
                ResolvedLoopCreate(
                    request=normalized_request,
                    loop_id=loop_id,
                    spec_markdown=spec_markdown,
                    compiled_spec=compiled_spec,
                    resolved_orchestration=resolved_orchestration,
                    workflow=normalized_workflow,
                )
            )
        )
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

    def _log_loop_create_requested(self, request: LoopCreateRequest) -> None:
        log_event(
            logger,
            logging.INFO,
            "service.loop.create.requested",
            "Received loop creation request",
            workdir=request.workdir,
            spec_path=request.spec_path,
            orchestration_id=request.orchestration_id,
            completion_mode=request.completion_mode,
            max_iters=request.max_iters,
            executor_kind=request.executor_kind,
            executor_mode=request.executor_mode,
        )

    def _resolve_loop_orchestration(self, request: LoopCreateRequest) -> dict:
        return self._asset_call(
            self.asset_catalog.resolve_orchestration_input,
            orchestration_id=request.orchestration_id,
            workflow=request.workflow,
            prompt_files=request.prompt_files,
            role_models=request.role_models,
        )

    @staticmethod
    def _validate_loop_completion_workflow(*, completion_mode: str, workflow: dict) -> None:
        if completion_mode == "gatekeeper" and not has_finish_gatekeeper_step(workflow):
            raise LooporaError("gatekeeper completion mode requires a GateKeeper step that can finish the run")

    def _read_loop_spec_with_coverage(self, spec_path: Path, *, completion_mode: str) -> tuple[str, dict]:
        spec_markdown, compiled_spec = self._read_and_compile_spec(spec_path)
        return spec_markdown, with_coverage_targets(compiled_spec, completion_mode=completion_mode)

    def _persist_loop_definition_files(self, snapshot: LoopDefinitionFiles) -> None:
        loop_dir = self._ensure_loop_dir(snapshot.workdir, snapshot.loop_id)
        (loop_dir / "spec.md").write_text(snapshot.spec_markdown, encoding="utf-8")
        write_json(loop_dir / "compiled_spec.json", snapshot.compiled_spec)
        self._persist_prompt_files(loop_dir, snapshot.prompt_files)
        write_json(loop_dir / "workflow.json", snapshot.workflow)

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
            RunContractSnapshotRequest(
                run={
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
