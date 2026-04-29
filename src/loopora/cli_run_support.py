from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

import typer

from loopora.branding import RUN_SUMMARY_TITLE
from loopora.cli_common import call_spawn_background_worker, get_service, logger
from loopora.cli_workflow_support import build_loop_kwargs
from loopora.diagnostics import log_event, log_exception
from loopora.service import LooporaError
from loopora.utils import utc_now


def print_loop_created(loop: dict) -> None:
    typer.echo(f"loop: {loop['id']}")
    if loop.get("name"):
        typer.echo(f"name: {loop['name']}")
    if loop.get("workdir"):
        typer.echo(f"workdir: {loop['workdir']}")


def print_run_result(result: dict) -> None:
    from loopora.cli_common import echo_json

    typer.echo(f"run: {result['id']}")
    typer.echo(f"run_status: {result.get('run_status') or result['status']}")
    typer.echo(f"run_dir: {result['runs_dir']}")
    task_verdict = result.get("task_verdict") or result.get("task_verdict_json")
    if task_verdict:
        typer.echo(f"task_verdict: {task_verdict.get('status', 'not_evaluated')}")
        if task_verdict.get("source"):
            typer.echo(f"task_verdict_source: {task_verdict['source']}")
        if task_verdict.get("summary"):
            typer.echo(f"task_verdict_summary: {task_verdict['summary']}")
    if result.get("last_verdict_json"):
        typer.echo("raw_last_verdict_json:")
        echo_json(result["last_verdict_json"])


def background_worker_command(run_id: str) -> list[str]:
    return [sys.executable, "-m", "loopora", "_execute-run", run_id]


def spawn_background_worker(service, run: dict) -> dict:
    run_dir = Path(run["runs_dir"])
    run_dir.mkdir(parents=True, exist_ok=True)
    log_path = run_dir / "background_worker.log"
    command = background_worker_command(run["id"])
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
            f"# {RUN_SUMMARY_TITLE}\n\n"
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
        log_exception(
            logger,
            "cli.background_worker.spawn_failed",
            "Failed to spawn background worker",
            error=exc,
            run_id=run["id"],
            workdir=run.get("workdir"),
            log_path=log_path,
            command=command,
        )
        raise LooporaError(error_text) from exc
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
    log_event(
        logger,
        logging.INFO,
        "cli.background_worker.spawned",
        "Spawned background worker for run",
        run_id=run["id"],
        workdir=run.get("workdir"),
        worker_pid=process.pid,
        log_path=log_path,
        command=command,
    )
    return service.get_run(run["id"])


def start_run(service, loop_id: str, *, background: bool) -> dict:
    if background:
        run = service.start_run(loop_id)
        return call_spawn_background_worker(service, run)
    return service.rerun(loop_id, background=False)


def create_and_maybe_start_loop(
    *,
    spec: Path,
    workdir: Path,
    executor_kind: str,
    executor_mode: str,
    model: str,
    reasoning_effort: str,
    completion_mode: str,
    iteration_interval_seconds: float,
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
        raise LooporaError("--background requires --start")
    log_event(
        logger,
        logging.INFO,
        "cli.loop.create.requested",
        "CLI requested loop creation",
        workdir=workdir,
        spec_path=spec,
        orchestration_id=orchestration_id,
        start=start,
        background=background,
        completion_mode=completion_mode,
    )
    service = get_service()
    loop = service.create_loop(
        **build_loop_kwargs(
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
        )
    )
    run = start_run(service, loop["id"], background=background) if start else None
    log_event(
        logger,
        logging.INFO,
        "cli.loop.create.completed",
        "CLI created loop successfully",
        loop_id=loop["id"],
        workdir=loop.get("workdir"),
        run_id=run.get("id") if run else None,
        start=start,
        background=background,
    )
    return loop, run
