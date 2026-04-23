from __future__ import annotations

import logging

import typer

from loopora.diagnostics import get_logger, log_event
from loopora.service import create_service as _default_create_service

logger = get_logger(__name__)


def handle_error(exc: Exception) -> None:
    log_event(
        logger,
        logging.ERROR,
        "cli.command.failed",
        "CLI command failed",
        error_type=type(exc).__name__,
        error_message=str(exc),
    )
    typer.secho(str(exc), fg=typer.colors.RED, err=True)
    raise typer.Exit(code=1)


def echo_json(payload: object) -> None:
    import json

    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


def get_service():
    import loopora.cli as cli_module

    factory = getattr(cli_module, "create_service", _default_create_service)
    return factory()


def call_spawn_background_worker(service, run: dict) -> dict:
    import loopora.cli as cli_module

    from loopora.cli_run_support import spawn_background_worker

    callback = getattr(cli_module, "_spawn_background_worker", spawn_background_worker)
    return callback(service, run)
