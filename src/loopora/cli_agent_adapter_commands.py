from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated

import typer

from loopora.agent_web import ensure_local_web_service, web_url_for_path
from loopora.cli_shared import JsonOutputOption, call_spawn_background_worker, echo_json, get_service, handle_error
from loopora.cli_run_support import print_run_contract_summary, print_task_verdict
from loopora.service import LooporaError
from loopora.service_agent_native import AgentNativeStepClaimRequest, AgentNativeStepSubmitRequest
from loopora.service_agent_adapters import AgentBundleCandidateRequest
from loopora.workflows import WorkflowError

AdapterWorkdirOption = Annotated[
    Path,
    typer.Option(
        "--workdir",
        exists=True,
        file_okay=False,
        dir_okay=True,
        help="Project directory where the Coding Agent will work.",
    ),
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
    typer.Option(
        "--bundle-file",
        "--plan-file",
        exists=True,
        file_okay=True,
        dir_okay=False,
        help="Candidate Loop plan file produced by the Coding Agent.",
    ),
]
ResultFileOption = Annotated[
    Path,
    typer.Option("--result-file", exists=True, file_okay=True, dir_okay=False, help="JSON result produced by the host Agent for the claimed Loopora step."),
]
RunIdOption = Annotated[str, typer.Option("--run-id", help="Optional Loopora run id. Defaults to the run bound to the current host session/workdir.")]
StepIdOption = Annotated[str, typer.Option("--step-id", help="Loopora step id being submitted.")]
AdapterMessageOption = Annotated[
    str,
    typer.Option("--message", help="Short task summary for the Loop preview; required for Agent-first traceability."),
]
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
        """Install or update the Codex project entry."""
        _install_adapter("codex", workdir=workdir, json_output=json_output)

    @init_app.command("claude")
    def init_claude(workdir: AdapterWorkdirOption = Path("."), json_output: JsonOutputOption = False) -> None:
        """Install or update the Claude Code project entry."""
        _install_adapter("claude", workdir=workdir, json_output=json_output)

    @init_app.command("opencode")
    def init_opencode(workdir: AdapterWorkdirOption = Path("."), json_output: JsonOutputOption = False) -> None:
        """Install or update the OpenCode project entry."""
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
        """Remove the Loopora-managed Codex project entry."""
        _uninstall_adapter("codex", workdir=workdir, json_output=json_output)

    @uninstall_app.command("claude")
    def uninstall_claude(workdir: AdapterWorkdirOption = Path("."), json_output: JsonOutputOption = False) -> None:
        """Remove the Loopora-managed Claude Code project entry."""
        _uninstall_adapter("claude", workdir=workdir, json_output=json_output)

    @uninstall_app.command("opencode")
    def uninstall_opencode(workdir: AdapterWorkdirOption = Path("."), json_output: JsonOutputOption = False) -> None:
        """Remove the Loopora-managed OpenCode project entry."""
        _uninstall_adapter("opencode", workdir=workdir, json_output=json_output)


def _uninstall_adapter(adapter: str, *, workdir: Path, json_output: bool) -> None:
    try:
        result = get_service().uninstall_agent_adapter(adapter, workdir=workdir)
        _print_adapter_mutation_result(result, action="uninstalled", json_output=json_output)
    except LooporaError as exc:
        handle_error(exc)


def _register_agent_runtime_commands(agent_app: typer.Typer) -> None:
    _register_agent_runtime_for(agent_app, adapter="codex", help_text="Internal Codex runtime used by Loopora project entries")
    _register_agent_runtime_for(agent_app, adapter="claude", help_text="Internal Claude Code runtime used by Loopora project entries")
    _register_agent_runtime_for(agent_app, adapter="opencode", help_text="Internal OpenCode runtime used by Loopora project entries")


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
        """Validate a generated Loop plan and return the Loop preview URL."""
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
    if action == "installed":
        typer.echo(f"{label} Loopora entry is installed")
        typer.echo(f"target project: {result['workdir']}")
        _print_adapter_next_steps(label)
    else:
        typer.echo(f"{label} Loopora entry {action}: {result['status']}")
        typer.echo(f"target project: {result['workdir']}")
    _print_adapter_file_details(result)


def _print_adapter_file_details(result: dict) -> None:
    managed_files = result.get("managed_files")
    if isinstance(managed_files, list):
        typer.echo("managed files:")
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


def _print_adapter_next_steps(label: str) -> None:
    typer.echo("next:")
    typer.echo(f"- Return to {label} in this project and run /loopora-gen for the current task.")
    typer.echo("- Review the Loop preview, then run /loopora-loop to start or continue execution.")


def _print_agent_gen_result(result: dict, *, json_output: bool) -> None:
    if json_output:
        echo_json(result)
        return
    if result.get("ready"):
        typer.echo("Loopora Loop preview is ready")
    elif result.get("requires_candidate_repair"):
        typer.echo("Loopora Loop preview needs plan file repair before /loopora-loop")
        if result.get("loopora_fit_contradiction"):
            typer.echo(
                "not_fit: task summary says this looks like one-off, direct-answer, no-new-evidence, "
                "or benchmark/test-harness-only work; "
                "reframe the task with later evidence, handoff, or GateKeeper value before trying a runnable Loop"
            )
        error = _agent_gen_error_summary(result)
        if error:
            typer.echo(f"validation_error: {error}")
    elif result.get("requires_web_alignment"):
        typer.echo("Loopora Loop preview needs Web review before /loopora-loop")
        if result.get("loopora_fit_contradiction"):
            typer.echo(
                "not_fit: task summary says this looks like one-off, direct-answer, no-new-evidence, "
                "or benchmark/test-harness-only work; "
                "define later evidence, handoff, or GateKeeper value before generating a runnable Loop"
            )
    else:
        typer.echo(f"Loopora Loop preview status: {result.get('status')}")
    typer.echo(f"session_id: {result['session']['id']}")
    typer.echo(f"preview_url: {result.get('preview_url') or result.get('preview_path')}")
    _print_web_status(result)


def _agent_gen_error_summary(result: dict) -> str:
    session = result.get("session") if isinstance(result.get("session"), dict) else {}
    validation = session.get("validation") if isinstance(session.get("validation"), dict) else {}
    return str(session.get("error_message") or validation.get("error") or "").strip()


def _print_agent_loop_result(result: dict, *, json_output: bool) -> None:
    if json_output:
        echo_json(result)
        return
    run = result.get("run") if isinstance(result.get("run"), dict) else {}
    typer.echo(f"Loopora run: {run.get('id')}")
    typer.echo(f"run_status: {run.get('run_status') or run.get('status')}")
    print_run_contract_summary(run)
    if result.get("complete"):
        print_task_verdict(run.get("task_verdict") or run.get("task_verdict_json"))
    typer.echo(f"run_url: {result.get('run_url') or result.get('run_path')}")
    _print_web_status(result)
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
    print_run_contract_summary(run)
    if result.get("complete"):
        print_task_verdict(run.get("task_verdict") or run.get("task_verdict_json"))
    typer.echo(f"run_url: {result.get('run_url') or result.get('run_path')}")
    _print_web_status(result)
    next_step = result.get("next_step") if isinstance(result.get("next_step"), dict) else {}
    if result.get("complete"):
        typer.echo("agent_native: complete")
    elif next_step:
        role = next_step.get("role") if isinstance(next_step.get("role"), dict) else {}
        typer.echo(f"next_step_id: {next_step.get('step_id')}")
        typer.echo(f"next_role: {role.get('name') or role.get('id')}")
        typer.echo(f"submit_hint: {(next_step.get('submit_hint') or {}).get('command')}")


def _print_web_status(result: dict) -> None:
    web = result.get("web")
    if not isinstance(web, dict):
        return
    base_url = str(web.get("base_url") or "").strip()
    if not base_url:
        return
    if web.get("started"):
        typer.echo(f"web: started {base_url}")
    elif web.get("reused"):
        typer.echo(f"web: reused {base_url}")
    else:
        typer.echo(f"web: {base_url}")
    warning = str(web.get("warning") or "").strip()
    if warning:
        typer.echo(f"web_warning: {warning}")


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
