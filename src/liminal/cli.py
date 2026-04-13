from __future__ import annotations

import json
from pathlib import Path

import typer
import uvicorn

from liminal.service import LiminalError, create_service
from liminal.settings import configure_logging
from liminal.specs import SpecError, init_spec_file
from liminal.web import build_app

app = typer.Typer(help="Liminal CLI")
loops_app = typer.Typer(help="Inspect and control saved loops")
spec_app = typer.Typer(help="Work with Markdown loop specs")
app.add_typer(loops_app, name="loops")
app.add_typer(spec_app, name="spec")


def _handle_error(exc: Exception) -> None:
    typer.secho(str(exc), fg=typer.colors.RED, err=True)
    raise typer.Exit(code=1)


@app.command()
def run(
    spec: Path = typer.Option(..., exists=True, help="Path to the Markdown spec."),
    workdir: Path = typer.Option(..., exists=True, file_okay=False, dir_okay=True, help="Target workdir."),
    model: str = typer.Option("gpt-5.4", help="Model for Codex."),
    reasoning_effort: str = typer.Option("medium", help="Reasoning effort label stored with the run."),
    max_iters: int = typer.Option(8, min=1, help="Maximum orchestration iterations."),
    max_role_retries: int = typer.Option(2, min=0, help="Retries per role before aborting."),
    delta_threshold: float = typer.Option(0.005, min=0.0, help="Plateau threshold."),
    trigger_window: int = typer.Option(4, min=1, help="Plateau trigger window."),
    regression_window: int = typer.Option(2, min=1, help="Regression trigger window."),
    name: str | None = typer.Option(None, help="Optional loop name."),
    role_model: list[str] = typer.Option(None, "--role-model", help="Per-role model override like generator=gpt-5.4-mini."),
) -> None:
    """Create a loop definition and execute it immediately."""
    try:
        service = create_service()
        loop = service.create_loop(
            name=name or workdir.resolve().name,
            spec_path=spec,
            workdir=workdir,
            model=model,
            reasoning_effort=reasoning_effort,
            max_iters=max_iters,
            max_role_retries=max_role_retries,
            delta_threshold=delta_threshold,
            trigger_window=trigger_window,
            regression_window=regression_window,
            role_models=_parse_role_models(role_model),
        )
        result = service.rerun(loop["id"])
        typer.echo(f"loop: {loop['id']}")
        typer.echo(f"run: {result['id']}")
        typer.echo(f"status: {result['status']}")
        typer.echo(f"run_dir: {result['runs_dir']}")
        if result.get("last_verdict_json"):
            typer.echo("verdict:")
            typer.echo(json.dumps(result["last_verdict_json"], ensure_ascii=False, indent=2))
    except (LiminalError, SpecError, FileExistsError) as exc:
        _handle_error(exc)


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Bind host."),
    port: int = typer.Option(8742, min=1, max=65535, help="Bind port."),
) -> None:
    """Run the local web console."""
    configure_logging()
    uvicorn.run(build_app(), host=host, port=port, log_level="info", access_log=False)


@spec_app.command("init")
def spec_init(path: Path = typer.Argument(..., help="Where to create the Markdown template.")) -> None:
    """Create a starter Markdown spec."""
    try:
        created = init_spec_file(path)
        typer.echo(f"created: {created}")
    except (FileExistsError, OSError) as exc:
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
                f"{loop['workdir']}  model={loop['model']}"
            )
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
def rerun_loop(loop_id: str = typer.Argument(..., help="Loop definition ID.")) -> None:
    """Start a new run from a saved loop definition."""
    try:
        service = create_service()
        result = service.rerun(loop_id)
        typer.echo(f"run: {result['id']}")
        typer.echo(f"status: {result['status']}")
        typer.echo(f"run_dir: {result['runs_dir']}")
    except LiminalError as exc:
        _handle_error(exc)


def _parse_role_models(values: list[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for item in values:
        if "=" not in item:
            raise LiminalError(f"invalid --role-model value: {item}")
        role, model = item.split("=", 1)
        role = role.strip()
        model = model.strip()
        if role not in {"generator", "tester", "verifier", "challenger"} or not model:
            raise LiminalError(f"invalid --role-model value: {item}")
        parsed[role] = model
    return parsed
