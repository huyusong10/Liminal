from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated

import typer

from loopora.agent_web import ensure_local_web_service, web_url_for_path
from loopora.cli_shared import JsonOutputOption, call_spawn_background_worker, echo_json, get_service, handle_error
from loopora.cli_run_support import print_task_verdict
from loopora.service import LooporaError
from loopora.service_agent_native import AgentNativeStepClaimRequest, AgentNativeStepSubmitRequest
from loopora.service_agent_adapters import AgentBundleCandidateRequest
from loopora.workflows import WorkflowError

AdapterWorkdirOption = Annotated[
    Path,
    typer.Option("--workdir", exists=True, file_okay=False, dir_okay=True, help="Project workdir for the Coding Agent adapter."),
]
ContextIdOption = Annotated[
    str,
    typer.Option("--context-id", help="Optional host session/thread identity. Defaults to Loopora, Codex, Claude Code, or OpenCode session env vars, then workdir."),
]
EntrySourceOption = Annotated[
    str,
    typer.Option("--entry-source", hidden=True, help="Internal marker for Loopora-managed Agent entry provenance."),
]
BundleFileOption = Annotated[
    Path | None,
    typer.Option("--bundle-file", exists=True, file_okay=True, dir_okay=False, help="Candidate Loopora bundle YAML produced by the Coding Agent."),
]
ResultFileOption = Annotated[
    Path,
    typer.Option("--result-file", exists=True, file_okay=True, dir_okay=False, help="JSON result produced by the host Agent for the claimed Loopora step."),
]
RunIdOption = Annotated[str, typer.Option("--run-id", help="Optional Loopora run id. Defaults to the run bound to the current host session/workdir.")]
StepIdOption = Annotated[str, typer.Option("--step-id", help="Loopora step id being submitted.")]
AdapterMessageOption = Annotated[str, typer.Option("--message", help="Short task summary for the Loop preview.")]
NoWebOption = Annotated[bool, typer.Option("--no-web", hidden=True, help="Skip local Web service startup.")]


def register_agent_adapter_commands(
    init_app: typer.Typer,
    uninstall_app: typer.Typer,
    agent_app: typer.Typer,
) -> None:
    _register_init_commands(init_app)
    _register_uninstall_commands(uninstall_app)
    _register_agent_runtime_commands(agent_app)


def _register_init_commands(init_app: typer.Typer) -> None:
    @init_app.command("codex")
    def init_codex(workdir: AdapterWorkdirOption = Path("."), json_output: JsonOutputOption = False) -> None:
        """Install or update the project-level Codex adapter."""
        _install_adapter("codex", workdir=workdir, json_output=json_output)

    @init_app.command("claude")
    def init_claude(workdir: AdapterWorkdirOption = Path("."), json_output: JsonOutputOption = False) -> None:
        """Install or update the project-level Claude Code adapter."""
        _install_adapter("claude", workdir=workdir, json_output=json_output)

    @init_app.command("opencode")
    def init_opencode(workdir: AdapterWorkdirOption = Path("."), json_output: JsonOutputOption = False) -> None:
        """Install or update the project-level OpenCode adapter."""
        _install_adapter("opencode", workdir=workdir, json_output=json_output)


def _install_adapter(adapter: str, *, workdir: Path, json_output: bool) -> None:
    try:
        result = get_service().install_agent_adapter(adapter, workdir=workdir)
        _print_adapter_mutation_result(result, action="installed", json_output=json_output)
    except LooporaError as exc:
        handle_error(exc)


def _register_uninstall_commands(uninstall_app: typer.Typer) -> None:
    @uninstall_app.command("codex")
    def uninstall_codex(workdir: AdapterWorkdirOption = Path("."), json_output: JsonOutputOption = False) -> None:
        """Remove Loopora-managed Codex adapter files."""
        _uninstall_adapter("codex", workdir=workdir, json_output=json_output)

    @uninstall_app.command("claude")
    def uninstall_claude(workdir: AdapterWorkdirOption = Path("."), json_output: JsonOutputOption = False) -> None:
        """Remove Loopora-managed Claude Code adapter files."""
        _uninstall_adapter("claude", workdir=workdir, json_output=json_output)

    @uninstall_app.command("opencode")
    def uninstall_opencode(workdir: AdapterWorkdirOption = Path("."), json_output: JsonOutputOption = False) -> None:
        """Remove Loopora-managed OpenCode adapter files."""
        _uninstall_adapter("opencode", workdir=workdir, json_output=json_output)


def _uninstall_adapter(adapter: str, *, workdir: Path, json_output: bool) -> None:
    try:
        result = get_service().uninstall_agent_adapter(adapter, workdir=workdir)
        _print_adapter_mutation_result(result, action="uninstalled", json_output=json_output)
    except LooporaError as exc:
        handle_error(exc)


def _register_agent_runtime_commands(agent_app: typer.Typer) -> None:
    _register_agent_runtime_for(agent_app, adapter="codex", help_text="Codex adapter runtime entries used by Loopora project skills")
    _register_agent_runtime_for(agent_app, adapter="claude", help_text="Claude Code adapter runtime entries used by Loopora project skills")
    _register_agent_runtime_for(agent_app, adapter="opencode", help_text="OpenCode adapter runtime entries used by Loopora project commands")


def _register_agent_runtime_for(agent_app: typer.Typer, *, adapter: str, help_text: str) -> None:
    adapter_app = typer.Typer(help=help_text)
    agent_app.add_typer(adapter_app, name=adapter)

    @adapter_app.command("gen")
    def agent_gen(
        workdir: AdapterWorkdirOption = Path("."),
        message: AdapterMessageOption = "",
        bundle_file: BundleFileOption = None,
        context_id: ContextIdOption = "",
        entry_source: EntrySourceOption = "",
        json_output: JsonOutputOption = False,
        no_web: NoWebOption = False,
    ) -> None:
        """Validate a generated Loop candidate and return the Loop preview URL."""
        try:
            request = AgentBundleCandidateRequest(
                adapter=adapter,
                workdir=workdir,
                message=message,
                bundle_file=bundle_file,
                context_id=context_id,
                entry_source=_resolved_entry_source(entry_source),
            )
            result = get_service().create_agent_bundle_candidate(request)
            _attach_web_url(result, path_key="preview_path", url_key="preview_url", no_web=no_web)
            _print_agent_gen_result(result, json_output=json_output)
        except (LooporaError, WorkflowError) as exc:
            handle_error(exc)

    @adapter_app.command("loop")
    def agent_loop(
        workdir: AdapterWorkdirOption = Path("."),
        context_id: ContextIdOption = "",
        entry_source: EntrySourceOption = "",
        json_output: JsonOutputOption = False,
        no_web: NoWebOption = False,
    ) -> None:
        """Start or reuse the Loopora run associated with the current ready Loop preview."""
        try:
            service = get_service()
            result = service.start_agent_loop(
                adapter,
                workdir=workdir,
                context_id=context_id,
                entry_source=_resolved_entry_source(entry_source),
                execute_async=False,
            )
            _spawn_agent_loop_worker_if_needed(service, result)
            _attach_web_url(result, path_key="run_path", url_key="run_url", no_web=no_web)
            _print_agent_loop_result(result, json_output=json_output)
        except (LooporaError, WorkflowError) as exc:
            handle_error(exc)

    @adapter_app.command("next")
    def agent_next(
        workdir: AdapterWorkdirOption = Path("."),
        context_id: ContextIdOption = "",
        run_id: RunIdOption = "",
        entry_source: EntrySourceOption = "",
        json_output: JsonOutputOption = False,
        no_web: NoWebOption = False,
    ) -> None:
        """Claim the next Loopora step capsule for the host Agent to execute natively."""
        try:
            result = get_service().claim_agent_native_step(
                AgentNativeStepClaimRequest(
                    adapter=adapter,
                    workdir=workdir,
                    context_id=context_id,
                    run_id=run_id,
                    entry_source=_resolved_entry_source(entry_source),
                )
            )
            _attach_web_url(result, path_key="run_path", url_key="run_url", no_web=no_web)
            _print_agent_step_result(result, json_output=json_output)
        except (LooporaError, WorkflowError) as exc:
            handle_error(exc)

    @adapter_app.command("submit")
    def agent_submit(
        result_file: ResultFileOption,
        workdir: AdapterWorkdirOption = Path("."),
        context_id: ContextIdOption = "",
        run_id: RunIdOption = "",
        step_id: StepIdOption = "",
        entry_source: EntrySourceOption = "",
        json_output: JsonOutputOption = False,
        no_web: NoWebOption = False,
    ) -> None:
        """Submit a host Agent's structured step result back to Loopora Core."""
        try:
            result_payload, host_dispatch = _read_result_json(result_file)
            result = get_service().submit_agent_native_step(
                AgentNativeStepSubmitRequest(
                    adapter=adapter,
                    workdir=workdir,
                    context_id=context_id,
                    run_id=run_id,
                    step_id=step_id,
                    output=result_payload,
                    host_dispatch=host_dispatch,
                    entry_source=_resolved_entry_source(entry_source),
                )
            )
            _attach_web_url(result, path_key="run_path", url_key="run_url", no_web=no_web)
            _print_agent_step_result(result, json_output=json_output)
        except (LooporaError, WorkflowError) as exc:
            handle_error(exc)


def _attach_web_url(result: dict, *, path_key: str, url_key: str, no_web: bool) -> None:
    path = str(result.get(path_key) or "")
    if not path:
        return
    if no_web:
        result[url_key] = path
        return
    web = ensure_local_web_service()
    result["web"] = web
    result[url_key] = web_url_for_path(path, web=web)


def _resolved_entry_source(entry_source: str) -> str:
    return str(entry_source or "").strip() or os.environ.get("LOOPORA_AGENT_ENTRY_SOURCE", "").strip()


def _spawn_agent_loop_worker_if_needed(service, result: dict) -> None:
    if result.get("execution_plane") == "agent_native":
        return
    if not result.get("started_new_run"):
        return
    run = result.get("run")
    if not isinstance(run, dict):
        return
    spawned_run = call_spawn_background_worker(service, run)
    result["run"] = spawned_run


def _print_adapter_mutation_result(result: dict, *, action: str, json_output: bool) -> None:
    if json_output:
        echo_json(result)
        return
    label = str(result.get("label") or _adapter_label(str(result.get("adapter") or "")))
    typer.echo(f"{label} adapter {action}: {result['status']}")
    typer.echo(f"workdir: {result['workdir']}")
    managed_files = result.get("managed_files")
    if isinstance(managed_files, list):
        for item in managed_files:
            if isinstance(item, dict):
                typer.echo(f"- {item.get('path')}: {item.get('state', 'managed')}")
    removed_files = result.get("removed_files")
    if isinstance(removed_files, list) and removed_files:
        typer.echo("removed:")
        for item in removed_files:
            typer.echo(f"- {item}")
    kept_files = result.get("kept_files")
    if isinstance(kept_files, list) and kept_files:
        typer.echo("kept:")
        for item in kept_files:
            if isinstance(item, dict):
                typer.echo(f"- {item.get('path')}: {item.get('reason')}")


def _print_agent_gen_result(result: dict, *, json_output: bool) -> None:
    if json_output:
        echo_json(result)
        return
    if result.get("ready"):
        typer.echo("Loopora Loop preview is ready")
    elif result.get("requires_web_alignment"):
        typer.echo("Loopora Loop preview needs Web review before /loopora-loop")
    else:
        typer.echo(f"Loopora Loop preview status: {result.get('status')}")
    typer.echo(f"session_id: {result['session']['id']}")
    typer.echo(f"preview_url: {result.get('preview_url') or result.get('preview_path')}")


def _print_agent_loop_result(result: dict, *, json_output: bool) -> None:
    if json_output:
        echo_json(result)
        return
    run = result.get("run") if isinstance(result.get("run"), dict) else {}
    typer.echo(f"Loopora run: {run.get('id')}")
    typer.echo(f"run_status: {run.get('run_status') or run.get('status')}")
    if result.get("complete"):
        print_task_verdict(run.get("task_verdict") or run.get("task_verdict_json"))
    typer.echo(f"run_url: {result.get('run_url') or result.get('run_path')}")
    next_step = result.get("next_step") if isinstance(result.get("next_step"), dict) else {}
    if next_step:
        role = next_step.get("role") if isinstance(next_step.get("role"), dict) else {}
        typer.echo(f"next_step_id: {next_step.get('step_id')}")
        typer.echo(f"next_role: {role.get('name') or role.get('id')}")


def _print_agent_step_result(result: dict, *, json_output: bool) -> None:
    if json_output:
        echo_json(result)
        return
    run = result.get("run") if isinstance(result.get("run"), dict) else {}
    typer.echo(f"Loopora run: {run.get('id')}")
    typer.echo(f"run_status: {run.get('run_status') or run.get('status')}")
    if result.get("complete"):
        print_task_verdict(run.get("task_verdict") or run.get("task_verdict_json"))
    typer.echo(f"run_url: {result.get('run_url') or result.get('run_path')}")
    next_step = result.get("next_step") if isinstance(result.get("next_step"), dict) else {}
    if result.get("complete"):
        typer.echo("agent_native: complete")
    elif next_step:
        role = next_step.get("role") if isinstance(next_step.get("role"), dict) else {}
        typer.echo(f"next_step_id: {next_step.get('step_id')}")
        typer.echo(f"next_role: {role.get('name') or role.get('id')}")
        typer.echo(f"submit_hint: {(next_step.get('submit_hint') or {}).get('command')}")


def _read_result_json(path: Path) -> tuple[dict, dict]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LooporaError(f"result file is not valid JSON: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise LooporaError("result file must contain one JSON object")
    if "loopora_host_dispatch" in payload or "result" in payload:
        host_dispatch = payload.get("loopora_host_dispatch")
        result = payload.get("result")
        if not isinstance(host_dispatch, dict):
            raise LooporaError("result wrapper must contain loopora_host_dispatch object")
        if not isinstance(result, dict):
            raise LooporaError("result wrapper must contain result object")
        return result, host_dispatch
    return payload, {}


def _adapter_label(adapter: str) -> str:
    return {
        "codex": "Codex",
        "claude": "Claude Code",
        "opencode": "OpenCode",
    }.get(adapter, adapter or "Agent")
