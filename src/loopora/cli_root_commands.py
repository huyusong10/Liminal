from __future__ import annotations

import logging

import typer
import uvicorn

from loopora.branding import APP_AUTH_ENV
from loopora.cli_shared import (
    BackgroundOption,
    CommandArgOption,
    CommandCliOption,
    CompletionModeOption,
    DeltaThresholdOption,
    ExecutorModeOption,
    ExecutorOption,
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
    TriggerWindowOption,
    WorkdirOption,
    WorkflowFileOption,
    WorkflowPresetOption,
    create_and_maybe_start_loop,
    handle_error,
    get_service,
    logger,
    print_loop_created,
    print_run_result,
)
from loopora.diagnostics import log_event
from loopora.service import LooporaError
from loopora.settings import configure_logging
from loopora.specs import SpecError
from loopora.web import _is_loopback_host, build_app


def register_root_commands(app: typer.Typer) -> None:
    @app.callback()
    def main() -> None:
        configure_logging()

    @app.command()
    def run(
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
        background: BackgroundOption = False,
    ) -> None:
        """Create a loop definition and execute it immediately."""
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
                start=True,
                background=background,
            )
            print_loop_created(loop)
            if result is not None:
                print_run_result(result)
        except (LooporaError, SpecError, FileExistsError) as exc:
            handle_error(exc)

    @app.command()
    def serve(
        host: str = typer.Option("127.0.0.1", help="Bind host."),
        port: int = typer.Option(8742, min=1, max=65535, help="Bind port."),
        auth_token: str = typer.Option(
            "",
            "--auth-token",
            envvar=APP_AUTH_ENV,
            help="Optional token required for all web and API requests.",
        ),
        allow_unsafe_open: bool = typer.Option(False, "--allow-unsafe-open", help="Allow non-loopback hosts without an auth token. Dangerous on shared networks."),
    ) -> None:
        """Run the local web console."""
        log_event(
            logger,
            logging.INFO,
            "cli.server.starting",
            "Starting the local web console",
            bind_host=host,
            bind_port=port,
            auth_enabled=bool(auth_token),
            allow_unsafe_open=allow_unsafe_open,
        )
        if not _is_loopback_host(host) and not auth_token and not allow_unsafe_open:
            handle_error(
                LooporaError(
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

    @app.command("_execute-run", hidden=True)
    def execute_run_worker(run_id: str = typer.Argument(..., help="Run ID.")) -> None:
        """Internal helper that executes a queued run in a dedicated background process."""
        try:
            service = get_service()
            result = service.execute_run(run_id)
            log_event(
                logger,
                logging.INFO,
                "cli.background_worker.completed",
                "Background worker finished run execution",
                run_id=result["id"],
                loop_id=result.get("loop_id"),
                status=result["status"],
            )
            print_run_result(result)
        except (LooporaError, SpecError) as exc:
            handle_error(exc)
