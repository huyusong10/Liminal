from __future__ import annotations

import logging

import typer

from loopora.cli_shared import (
    BackgroundOption,
    CommandArgOption,
    CommandCliOption,
    CompletionModeOption,
    DeltaThresholdOption,
    ExecutorModeOption,
    ExecutorOption,
    WorkdirOption,
    IterationIntervalOption,
    MaxItersOption,
    MaxRoleRetriesOption,
    ModelOption,
    NameOption,
    OrchestrationIdOption,
    ReasoningOption,
    RegressionWindowOption,
    RoleModelOption,
    SpecOption,
    StartOption,
    TriggerWindowOption,
    WorkflowFileOption,
    WorkflowPresetOption,
    create_and_maybe_start_loop,
    echo_json,
    handle_error,
    logger,
    get_service,
    print_loop_created,
    print_run_result,
    start_run,
)
from loopora.diagnostics import log_event
from loopora.service import LooporaError
from loopora.specs import SpecError


def register_loop_commands(loops_app: typer.Typer) -> None:
    @loops_app.command("create")
    def create_loop(
        spec: SpecOption,
        workdir: WorkdirOption,
        executor_kind: ExecutorOption = "codex",
        executor_mode: ExecutorModeOption = "preset",
        model: ModelOption = "",
        reasoning_effort: ReasoningOption = "",
        completion_mode: CompletionModeOption = "gatekeeper",
        iteration_interval_seconds: IterationIntervalOption = 0.0,
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
            loop, result = create_and_maybe_start_loop(
                spec=spec,
                workdir=workdir,
                executor_kind=executor_kind,
                executor_mode=executor_mode,
                model=model,
                reasoning_effort=reasoning_effort,
                completion_mode=completion_mode,
                iteration_interval_seconds=iteration_interval_seconds,
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
            print_loop_created(loop)
            if result is not None:
                print_run_result(result)
        except (LooporaError, SpecError, FileExistsError) as exc:
            handle_error(exc)

    @loops_app.command("list")
    def list_loops() -> None:
        """List known loop definitions."""
        try:
            service = get_service()
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
        except LooporaError as exc:
            handle_error(exc)

    @loops_app.command("status")
    def loop_status(identifier: str = typer.Argument(..., help="Loop ID or run ID.")) -> None:
        """Show status for a loop or a specific run."""
        try:
            service = get_service()
            _kind, payload = service.get_status(identifier)
            echo_json(payload)
        except LooporaError as exc:
            handle_error(exc)

    @loops_app.command("stop")
    def stop_run(run_id: str = typer.Argument(..., help="Run ID.")) -> None:
        """Request a running loop to stop."""
        try:
            service = get_service()
            run = service.stop_run(run_id)
            log_event(
                logger,
                logging.INFO,
                "cli.run.stop_requested",
                "Requested run stop from the CLI",
                run_id=run["id"],
                loop_id=run.get("loop_id"),
                status=run.get("status"),
            )
            typer.echo(f"stop requested for {run['id']} ({run['status']})")
        except LooporaError as exc:
            handle_error(exc)

    @loops_app.command("rerun")
    def rerun_loop(
        loop_id: str = typer.Argument(..., help="Loop definition ID."),
        background: BackgroundOption = False,
    ) -> None:
        """Start a new run from a saved loop definition."""
        try:
            service = get_service()
            result = start_run(service, loop_id, background=background)
            log_event(
                logger,
                logging.INFO,
                "cli.run.rerun_requested",
                "Started a rerun from the CLI",
                loop_id=loop_id,
                run_id=result["id"],
                background=background,
                status=result["status"],
            )
            print_run_result(result)
        except LooporaError as exc:
            handle_error(exc)

    @loops_app.command("delete")
    def delete_loop(loop_id: str = typer.Argument(..., help="Loop definition ID.")) -> None:
        """Delete a saved loop definition and its run artifacts."""
        try:
            service = get_service()
            result = service.delete_loop(loop_id)
            log_event(
                logger,
                logging.INFO,
                "cli.loop.deleted",
                "Deleted loop from the CLI",
                loop_id=result["id"],
                workdir=result.get("workdir"),
                deleted_run_count=result.get("deleted_runs"),
            )
            echo_json(result)
        except LooporaError as exc:
            handle_error(exc)
