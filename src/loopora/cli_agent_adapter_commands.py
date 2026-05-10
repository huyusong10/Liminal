from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

import typer

from loopora.agent_web import ensure_local_web_service, web_url_for_path
from loopora.cli_shared import JsonOutputOption, call_spawn_background_worker, echo_json, get_service, handle_error
from loopora.service import LooporaError
from loopora.service_agent_adapters import AgentBundleCandidateRequest

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
AdapterMessageOption = Annotated[str, typer.Option("--message", help="Short task summary for the candidate Loop.")]
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
        """Validate a generated candidate bundle and return the READY preview URL."""
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
        except LooporaError as exc:
            handle_error(exc)

    @adapter_app.command("loop")
    def agent_loop(
        workdir: AdapterWorkdirOption = Path("."),
        context_id: ContextIdOption = "",
        entry_source: EntrySourceOption = "",
        json_output: JsonOutputOption = False,
        no_web: NoWebOption = False,
    ) -> None:
        """Start or reuse the Loopora run associated with the current READY bundle."""
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
        except LooporaError as exc:
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
        typer.echo("Loopora candidate READY")
    else:
        typer.echo(f"Loopora candidate status: {result.get('status')}")
    typer.echo(f"session_id: {result['session']['id']}")
    typer.echo(f"candidate_url: {result.get('preview_url') or result.get('preview_path')}")


def _print_agent_loop_result(result: dict, *, json_output: bool) -> None:
    if json_output:
        echo_json(result)
        return
    run = result.get("run") if isinstance(result.get("run"), dict) else {}
    typer.echo(f"Loopora run: {run.get('id')}")
    typer.echo(f"run_status: {run.get('status')}")
    typer.echo(f"run_url: {result.get('run_url') or result.get('run_path')}")


def _adapter_label(adapter: str) -> str:
    return {
        "codex": "Codex",
        "claude": "Claude Code",
        "opencode": "OpenCode",
    }.get(adapter, adapter or "Agent")
