from __future__ import annotations

import logging
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import typer

from loopora.branding import RUN_SUMMARY_TITLE
from loopora.cli_common import call_spawn_background_worker, get_service, logger
from loopora.cli_workflow_support import LoopBuildRequest, build_loop_kwargs
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
        service.append_run_event(
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
    service.append_run_event(
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


@dataclass(frozen=True)
class LoopCreateRequest(LoopBuildRequest):
    start: bool
    background: bool


def create_and_maybe_start_loop(request: LoopCreateRequest) -> tuple[dict, dict | None]:
    if request.background and not request.start:
        raise LooporaError("--background requires --start")
    log_event(
        logger,
        logging.INFO,
        "cli.loop.create.requested",
        "CLI requested loop creation",
        workdir=request.workdir,
        spec_path=request.spec,
        orchestration_id=request.orchestration_id,
        start=request.start,
        background=request.background,
        completion_mode=request.completion_mode,
    )
    service = get_service()
    loop = service.create_loop(**build_loop_kwargs(request))
    run = start_run(service, loop["id"], background=request.background) if request.start else None
    log_event(
        logger,
        logging.INFO,
        "cli.loop.create.completed",
        "CLI created loop successfully",
        loop_id=loop["id"],
        workdir=loop.get("workdir"),
        run_id=run.get("id") if run else None,
        start=request.start,
        background=request.background,
    )
    return loop, run
