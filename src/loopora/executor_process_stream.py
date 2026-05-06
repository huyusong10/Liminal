from __future__ import annotations

import queue
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

_NO_LINE = object()


class ProcessStreamStopped(RuntimeError):
    """Raised when the caller requests stop while the child process is active."""


class ProcessStreamIdleTimeout(RuntimeError):
    """Raised when the child process produces no output before the idle deadline."""


@dataclass(slots=True)
class ProcessStreamContext:
    run_id: str
    role: str
    workdir: Path
    idle_timeout_seconds: float | None


@dataclass(slots=True)
class ProcessStreamCallbacks:
    emit_event: Callable[[str, dict], None]
    should_stop: Callable[[], bool]
    set_child_pid: Callable[[int | None], None]
    line_handler: Callable[[str], None]
    terminate_process: Callable[[subprocess.Popen[str]], None]


def stream_process(
    *,
    context: ProcessStreamContext,
    args: list[str],
    command_event_payload: dict,
    callbacks: ProcessStreamCallbacks,
) -> int:
    process = subprocess.Popen(
        args,
        cwd=str(context.workdir),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    callbacks.set_child_pid(process.pid)
    callbacks.emit_event("codex_event", command_event_payload)
    output_queue = _start_stdout_reader(process, context.role)
    idle_timeout_seconds = context.idle_timeout_seconds or 0.0
    last_output_at = time.monotonic()
    stream_closed = False
    try:
        while True:
            if callbacks.should_stop():
                callbacks.terminate_process(process)
                raise ProcessStreamStopped(f"run {context.run_id} stopped while {context.role} was running")

            raw_line = _next_stream_line(output_queue)
            if raw_line is None:
                stream_closed = True
            elif raw_line is not _NO_LINE:
                last_output_at = time.monotonic()
                _handle_stream_line(raw_line, callbacks.line_handler)

            _raise_if_idle_timeout_elapsed(
                process=process,
                context=context,
                idle_timeout_seconds=idle_timeout_seconds,
                last_output_at=last_output_at,
                terminate_process=callbacks.terminate_process,
            )

            if stream_closed and process.poll() is not None:
                break
        return process.wait()
    finally:
        callbacks.set_child_pid(None)
        output_queue.reader.join(timeout=0.2)


@dataclass(slots=True)
class _OutputQueue:
    lines: queue.Queue[str | None]
    reader: threading.Thread


def _start_stdout_reader(process: subprocess.Popen[str], role: str) -> _OutputQueue:
    output_queue: queue.Queue[str | None] = queue.Queue()

    def pump_stdout() -> None:
        assert process.stdout is not None
        try:
            for raw_line in process.stdout:
                output_queue.put(raw_line)
        finally:
            output_queue.put(None)

    reader = threading.Thread(target=pump_stdout, daemon=True, name=f"{role}-stdout")
    reader.start()
    return _OutputQueue(lines=output_queue, reader=reader)


def _next_stream_line(output_queue: _OutputQueue) -> str | None | object:
    try:
        return output_queue.lines.get(timeout=0.2)
    except queue.Empty:
        return _NO_LINE


def _handle_stream_line(raw_line: str, line_handler: Callable[[str], None]) -> None:
    line = raw_line.strip()
    if line:
        line_handler(line)


def _raise_if_idle_timeout_elapsed(
    *,
    process: subprocess.Popen[str],
    context: ProcessStreamContext,
    idle_timeout_seconds: float,
    last_output_at: float,
    terminate_process: Callable[[subprocess.Popen[str]], None],
) -> None:
    if not idle_timeout_seconds or process.poll() is not None:
        return
    silence_duration = time.monotonic() - last_output_at
    if silence_duration < idle_timeout_seconds:
        return
    terminate_process(process)
    timeout_text = f"{idle_timeout_seconds:g}s"
    raise ProcessStreamIdleTimeout(
        f"role={context.role} produced no output for {timeout_text}; treating the role as stalled"
    )
