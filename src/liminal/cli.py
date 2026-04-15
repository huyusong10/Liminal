from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Annotated

import typer
import uvicorn

from liminal.service import LiminalError, create_service, normalize_role_models
from liminal.settings import configure_logging
from liminal.specs import SpecError, init_spec_file, read_and_compile
from liminal.utils import utc_now
from liminal.web import _is_loopback_host, build_app
from liminal.workflows import load_workflow_file, preset_names

app = typer.Typer(help="Liminal CLI")
loops_app = typer.Typer(help="Inspect and control saved loops")
orchestrations_app = typer.Typer(help="Create and inspect orchestrations")
spec_app = typer.Typer(help="Work with Markdown loop specs")
app.add_typer(loops_app, name="loops")
app.add_typer(orchestrations_app, name="orchestrations")
app.add_typer(spec_app, name="spec")


def _handle_error(exc: Exception) -> None:
    typer.secho(str(exc), fg=typer.colors.RED, err=True)
    raise typer.Exit(code=1)


SpecOption = Annotated[Path, typer.Option(..., exists=True, help="Path to the Markdown spec.")]
WorkdirOption = Annotated[Path, typer.Option(..., exists=True, file_okay=False, dir_okay=True, help="Target workdir.")]
ExecutorOption = Annotated[str, typer.Option("--executor", help="Execution tool: codex, claude, or opencode.")]
ExecutorModeOption = Annotated[str, typer.Option("--executor-mode", help="Execution mode: preset or command.")]
ModelOption = Annotated[str, typer.Option(help="Default model or alias for the selected execution tool.")]
ReasoningOption = Annotated[str, typer.Option(help="Reasoning effort or variant for the selected execution tool.")]
CommandCliOption = Annotated[str, typer.Option("--command-cli", help="Executable to invoke in command mode. Defaults to the selected tool CLI.")]
CommandArgOption = Annotated[
    list[str] | None,
    typer.Option(
        "--command-arg",
        help="One command-mode argv template entry. Repeat once per argument. Supports placeholders like {workdir}, {schema_path}, {output_path}, {json_schema}, {sandbox}, {prompt}, {model}, and {reasoning_effort}.",
    ),
]
MaxItersOption = Annotated[int, typer.Option(min=0, help="Maximum orchestration iterations. Use 0 to keep iterating until you stop it.")]
MaxRoleRetriesOption = Annotated[int, typer.Option(min=0, help="Retries per role before aborting.")]
DeltaThresholdOption = Annotated[float, typer.Option(min=0.0, help="Plateau threshold.")]
TriggerWindowOption = Annotated[int, typer.Option(min=1, help="Plateau trigger window.")]
RegressionWindowOption = Annotated[int, typer.Option(min=1, help="Regression trigger window.")]
NameOption = Annotated[str | None, typer.Option(help="Optional loop name.")]
RoleModelOption = Annotated[
    list[str] | None,
    typer.Option(
        "--role-model",
        help="Per-role model override like builder=gpt-5.4-mini. Legacy names like generator/verifier still work.",
    ),
]
WorkflowPresetOption = Annotated[
    str,
    typer.Option(
        "--workflow-preset",
        help=f"Workflow preset: {', '.join(preset_names())}.",
    ),
]
OrchestrationIdOption = Annotated[
    str,
    typer.Option(
        "--orchestration-id",
        help="Use a saved orchestration id, such as builtin:build_first or a custom orchestration id.",
    ),
]
WorkflowFileOption = Annotated[
    Path | None,
    typer.Option(
        "--workflow-file",
        exists=True,
        file_okay=True,
        dir_okay=False,
        help="Path to a JSON or YAML workflow bundle. Supports {workflow, prompt_files} or a raw workflow object.",
    ),
]
StartOption = Annotated[bool, typer.Option("--start", help="Start a run immediately after creating the loop definition.")]
BackgroundOption = Annotated[bool, typer.Option("--background", help="Queue the run and return immediately instead of waiting for it to finish.")]
LocaleOption = Annotated[str, typer.Option("--locale", help="Template locale: zh or en.")]


def _command_args_text_from_values(values: list[str] | None) -> str:
    if not values:
        return ""
    return "\n".join(item for item in values if item.strip())


def _parse_role_models(values: list[str] | None) -> dict[str, str]:
    parsed: dict[str, str] = {}
    if not values:
        return parsed
    for item in values:
        if "=" not in item:
            raise LiminalError(f"invalid --role-model value: {item}")
        role, model = item.split("=", 1)
        parsed[role.strip()] = model.strip()
    return normalize_role_models(parsed)


def _build_loop_kwargs(
    *,
    spec: Path,
    workdir: Path,
    executor_kind: str,
    executor_mode: str,
    model: str,
    reasoning_effort: str,
    command_cli: str,
    command_arg: list[str] | None,
    max_iters: int,
    max_role_retries: int,
    delta_threshold: float,
    trigger_window: int,
    regression_window: int,
    name: str | None,
    role_model: list[str] | None,
    orchestration_id: str,
    workflow_preset: str,
    workflow_file: Path | None,
) -> dict[str, object]:
    workflow: dict | None = None
    prompt_files: dict[str, str] | None = None
    if workflow_file is not None:
        workflow, prompt_files = load_workflow_file(workflow_file)
    elif workflow_preset and not orchestration_id.strip():
        workflow = {"preset": workflow_preset}
    return {
        "name": name or workdir.resolve().name,
        "spec_path": spec,
        "workdir": workdir,
        "orchestration_id": orchestration_id.strip() or None,
        "executor_kind": executor_kind,
        "executor_mode": executor_mode,
        "command_cli": command_cli,
        "command_args_text": _command_args_text_from_values(command_arg),
        "model": model,
        "reasoning_effort": reasoning_effort,
        "max_iters": max_iters,
        "max_role_retries": max_role_retries,
        "delta_threshold": delta_threshold,
        "trigger_window": trigger_window,
        "regression_window": regression_window,
        "workflow": workflow,
        "prompt_files": prompt_files,
        "role_models": _parse_role_models(role_model),
    }


def _print_loop_created(loop: dict) -> None:
    typer.echo(f"loop: {loop['id']}")
    if loop.get("name"):
        typer.echo(f"name: {loop['name']}")
    if loop.get("workdir"):
        typer.echo(f"workdir: {loop['workdir']}")


def _print_run_result(result: dict) -> None:
    typer.echo(f"run: {result['id']}")
    typer.echo(f"status: {result['status']}")
    typer.echo(f"run_dir: {result['runs_dir']}")
    if result.get("last_verdict_json"):
        typer.echo("verdict:")
        typer.echo(json.dumps(result["last_verdict_json"], ensure_ascii=False, indent=2))


def _background_worker_command(run_id: str) -> list[str]:
    return [sys.executable, "-m", "liminal", "_execute-run", run_id]


def _spawn_background_worker(service, run: dict) -> dict:
    run_dir = Path(run["runs_dir"])
    run_dir.mkdir(parents=True, exist_ok=True)
    log_path = run_dir / "background_worker.log"
    command = _background_worker_command(run["id"])
    log_handle = log_path.open("a", encoding="utf-8")
    try:
        process = subprocess.Popen(
            command,
            cwd=run["workdir"],
            env=os.environ.copy(),
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            close_fds=True,
            start_new_session=True,
        )
    except OSError as exc:
        error_text = f"failed to spawn background worker for {run['id']}: {exc}"
        summary = (
            "# Liminal Run Summary\n\n"
            "Background execution failed before the worker could start.\n\n"
            f"Reason: `{error_text}`.\n"
        )
        service.repository.update_run(
            run["id"],
            status="failed",
            finished_at=utc_now(),
            error_message=error_text,
            summary_md=summary,
        )
        service.repository.append_event(
            run["id"],
            "run_aborted",
            {
                "role": None,
                "attempts": 1,
                "degraded": False,
                "error": error_text,
            },
        )
        raise LiminalError(error_text) from exc
    finally:
        log_handle.close()

    service.repository.update_run(run["id"], runner_pid=process.pid)
    service.repository.append_event(
        run["id"],
        "background_worker_spawned",
        {
            "pid": process.pid,
            "command": command,
            "log_path": str(log_path),
        },
    )
    return service.get_run(run["id"])


def _start_run(service, loop_id: str, *, background: bool) -> dict:
    if background:
        run = service.start_run(loop_id)
        return _spawn_background_worker(service, run)
    return service.rerun(loop_id, background=False)


def _create_and_maybe_start_loop(
    *,
    spec: Path,
    workdir: Path,
    executor_kind: str,
    executor_mode: str,
    model: str,
    reasoning_effort: str,
    command_cli: str,
    command_arg: list[str] | None,
    max_iters: int,
    max_role_retries: int,
    delta_threshold: float,
    trigger_window: int,
    regression_window: int,
    name: str | None,
    role_model: list[str] | None,
    orchestration_id: str,
    workflow_preset: str,
    workflow_file: Path | None,
    start: bool,
    background: bool,
) -> tuple[dict, dict | None]:
    if background and not start:
        raise LiminalError("--background requires --start")
    service = create_service()
    loop = service.create_loop(
        **_build_loop_kwargs(
            spec=spec,
            workdir=workdir,
            executor_kind=executor_kind,
            executor_mode=executor_mode,
            model=model,
            reasoning_effort=reasoning_effort,
            command_cli=command_cli,
            command_arg=command_arg,
            max_iters=max_iters,
            max_role_retries=max_role_retries,
            delta_threshold=delta_threshold,
            trigger_window=trigger_window,
            regression_window=regression_window,
            name=name,
            role_model=role_model,
            orchestration_id=orchestration_id,
            workflow_preset=workflow_preset,
            workflow_file=workflow_file,
        )
    )
    run = _start_run(service, loop["id"], background=background) if start else None
    return loop, run


@app.command()
def run(
    spec: SpecOption,
    workdir: WorkdirOption,
    executor_kind: ExecutorOption = "codex",
    executor_mode: ExecutorModeOption = "preset",
    model: ModelOption = "",
    reasoning_effort: ReasoningOption = "",
    command_cli: CommandCliOption = "",
    command_arg: CommandArgOption = None,
    max_iters: MaxItersOption = 8,
    max_role_retries: MaxRoleRetriesOption = 2,
    delta_threshold: DeltaThresholdOption = 0.005,
    trigger_window: TriggerWindowOption = 4,
    regression_window: RegressionWindowOption = 2,
    name: NameOption = None,
    role_model: RoleModelOption = None,
    orchestration_id: OrchestrationIdOption = "",
    workflow_preset: WorkflowPresetOption = "",
    workflow_file: WorkflowFileOption = None,
    background: BackgroundOption = False,
) -> None:
    """Create a loop definition and execute it immediately."""
    try:
        loop, result = _create_and_maybe_start_loop(
            spec=spec,
            workdir=workdir,
            executor_kind=executor_kind,
            executor_mode=executor_mode,
            model=model,
            reasoning_effort=reasoning_effort,
            command_cli=command_cli,
            command_arg=command_arg,
            max_iters=max_iters,
            max_role_retries=max_role_retries,
            delta_threshold=delta_threshold,
            trigger_window=trigger_window,
            regression_window=regression_window,
            name=name,
            role_model=role_model,
            orchestration_id=orchestration_id,
            workflow_preset=workflow_preset,
            workflow_file=workflow_file,
            start=True,
            background=background,
        )
        _print_loop_created(loop)
        if result is not None:
            _print_run_result(result)
    except (LiminalError, SpecError, FileExistsError) as exc:
        _handle_error(exc)


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Bind host."),
    port: int = typer.Option(8742, min=1, max=65535, help="Bind port."),
    auth_token: str = typer.Option("", "--auth-token", envvar="LIMINAL_AUTH_TOKEN", help="Optional token required for all web and API requests."),
    allow_unsafe_open: bool = typer.Option(False, "--allow-unsafe-open", help="Allow non-loopback hosts without an auth token. Dangerous on shared networks."),
) -> None:
    """Run the local web console."""
    configure_logging()
    if not _is_loopback_host(host) and not auth_token and not allow_unsafe_open:
        _handle_error(
            LiminalError(
                "refusing to bind a non-loopback host without protection; use --auth-token <token> or explicitly pass --allow-unsafe-open"
            )
        )
    if not _is_loopback_host(host):
        typer.secho(
            "Network mode enabled. Use absolute paths from the server machine in the Web UI; native file dialogs are disabled.",
            fg=typer.colors.YELLOW,
        )
        if auth_token:
            typer.secho(
                f"Open the UI once with ?token={auth_token} appended to the URL, or send it as Authorization: Bearer.",
                fg=typer.colors.YELLOW,
            )
    uvicorn.run(
        build_app(bind_host=host, bind_port=port, auth_token=auth_token or None),
        host=host,
        port=port,
        log_level="info",
        access_log=False,
    )


@spec_app.command("init")
def spec_init(
    path: Path = typer.Argument(..., help="Where to create the Markdown template."),
    locale: LocaleOption = "zh",
) -> None:
    """Create a starter Markdown spec."""
    try:
        created = init_spec_file(path, locale=locale)
        typer.echo(f"created: {created}")
    except (FileExistsError, OSError) as exc:
        _handle_error(exc)


@spec_app.command("validate")
def spec_validate(path: Path = typer.Argument(..., exists=True, help="Path to the Markdown spec to validate.")) -> None:
    """Validate a Markdown spec and print the resolved check mode."""
    try:
        _, compiled = read_and_compile(path)
        typer.echo(
            json.dumps(
                {
                    "ok": True,
                    "path": str(path.resolve()),
                    "check_count": len(compiled["checks"]),
                    "check_mode": compiled["check_mode"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    except (SpecError, FileNotFoundError, OSError) as exc:
        _handle_error(exc)


@loops_app.command("create")
def create_loop(
    spec: SpecOption,
    workdir: WorkdirOption,
    executor_kind: ExecutorOption = "codex",
    executor_mode: ExecutorModeOption = "preset",
    model: ModelOption = "",
    reasoning_effort: ReasoningOption = "",
    command_cli: CommandCliOption = "",
    command_arg: CommandArgOption = None,
    max_iters: MaxItersOption = 8,
    max_role_retries: MaxRoleRetriesOption = 2,
    delta_threshold: DeltaThresholdOption = 0.005,
    trigger_window: TriggerWindowOption = 4,
    regression_window: RegressionWindowOption = 2,
    name: NameOption = None,
    role_model: RoleModelOption = None,
    orchestration_id: OrchestrationIdOption = "",
    workflow_preset: WorkflowPresetOption = "",
    workflow_file: WorkflowFileOption = None,
    start: StartOption = False,
    background: BackgroundOption = False,
) -> None:
    """Create a saved loop definition, optionally starting a run immediately."""
    try:
        loop, result = _create_and_maybe_start_loop(
            spec=spec,
            workdir=workdir,
            executor_kind=executor_kind,
            executor_mode=executor_mode,
            model=model,
            reasoning_effort=reasoning_effort,
            command_cli=command_cli,
            command_arg=command_arg,
            max_iters=max_iters,
            max_role_retries=max_role_retries,
            delta_threshold=delta_threshold,
            trigger_window=trigger_window,
            regression_window=regression_window,
            name=name,
            role_model=role_model,
            orchestration_id=orchestration_id,
            workflow_preset=workflow_preset,
            workflow_file=workflow_file,
            start=start,
            background=background,
        )
        _print_loop_created(loop)
        if result is not None:
            _print_run_result(result)
    except (LiminalError, SpecError, FileExistsError) as exc:
        _handle_error(exc)


@loops_app.command("list")
def list_loops() -> None:
    """List known loop definitions."""
    try:
        service = create_service()
        loops = service.list_loops()
        if not loops:
            typer.echo("No loops found.")
            return
        for loop in loops:
            status = loop.get("latest_status") or "draft"
            typer.echo(
                f"{loop['id']}  {loop['name']}  [{status}]  "
                f"{loop['workdir']}  executor={loop.get('executor_kind', 'codex')}  model={loop['model'] or '-'}"
            )
    except LiminalError as exc:
        _handle_error(exc)


@orchestrations_app.command("list")
def list_orchestrations() -> None:
    """List saved orchestrations."""
    try:
        service = create_service()
        orchestrations = service.list_orchestrations()
        for item in orchestrations:
            typer.echo(
                f"{item['id']}  {item['name']}  "
                f"source={item.get('source', 'custom')}  "
                f"roles={len(item.get('workflow_json', {}).get('roles', []))}  "
                f"steps={len(item.get('workflow_json', {}).get('steps', []))}"
            )
    except LiminalError as exc:
        _handle_error(exc)


@orchestrations_app.command("create")
def create_orchestration(
    name: str = typer.Option(..., help="Orchestration name."),
    description: str = typer.Option("", help="Optional orchestration description."),
    workflow_preset: WorkflowPresetOption = "build_first",
    workflow_file: WorkflowFileOption = None,
) -> None:
    """Create a saved orchestration."""
    try:
        service = create_service()
        workflow: dict | None = None
        prompt_files: dict[str, str] | None = None
        if workflow_file is not None:
            workflow, prompt_files = load_workflow_file(workflow_file)
        elif workflow_preset:
            workflow = {"preset": workflow_preset}
        orchestration = service.create_orchestration(
            name=name,
            description=description,
            workflow=workflow,
            prompt_files=prompt_files,
        )
        typer.echo(json.dumps(orchestration, ensure_ascii=False, indent=2))
    except LiminalError as exc:
        _handle_error(exc)


@loops_app.command("status")
def loop_status(identifier: str = typer.Argument(..., help="Loop ID or run ID.")) -> None:
    """Show status for a loop or a specific run."""
    try:
        service = create_service()
        kind, payload = service.get_status(identifier)
        if kind == "loop":
            typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    except LiminalError as exc:
        _handle_error(exc)


@loops_app.command("stop")
def stop_run(run_id: str = typer.Argument(..., help="Run ID.")) -> None:
    """Request a running loop to stop."""
    try:
        service = create_service()
        run = service.stop_run(run_id)
        typer.echo(f"stop requested for {run['id']} ({run['status']})")
    except LiminalError as exc:
        _handle_error(exc)


@loops_app.command("rerun")
def rerun_loop(
    loop_id: str = typer.Argument(..., help="Loop definition ID."),
    background: BackgroundOption = False,
) -> None:
    """Start a new run from a saved loop definition."""
    try:
        service = create_service()
        result = _start_run(service, loop_id, background=background)
        _print_run_result(result)
    except LiminalError as exc:
        _handle_error(exc)


@app.command("_execute-run", hidden=True)
def execute_run_worker(run_id: str = typer.Argument(..., help="Run ID.")) -> None:
    """Internal helper that executes a queued run in a dedicated background process."""
    configure_logging()
    try:
        service = create_service()
        result = service.execute_run(run_id)
        _print_run_result(result)
    except (LiminalError, SpecError) as exc:
        _handle_error(exc)


@loops_app.command("delete")
def delete_loop(loop_id: str = typer.Argument(..., help="Loop definition ID.")) -> None:
    """Delete a saved loop definition and its run artifacts."""
    try:
        service = create_service()
        result = service.delete_loop(loop_id)
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
    except LiminalError as exc:
        _handle_error(exc)
