from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from loopora.executor_process_stream import ProcessStreamCallbacks, ProcessStreamContext, stream_process


def test_stream_process_terminates_child_when_stdout_pipe_is_missing(tmp_path: Path, monkeypatch) -> None:
    child_pids: list[int | None] = []
    terminated_pids: list[int] = []
    emitted_events: list[tuple[str, dict]] = []

    class FakeProcess:
        pid = 12345
        stdout = None

        def poll(self):
            return None

    fake_process = FakeProcess()
    monkeypatch.setattr(
        "loopora.executor_process_stream.subprocess.Popen",
        lambda *_args, **_kwargs: fake_process,
    )

    with pytest.raises(RuntimeError, match="stdout pipe was not configured"):
        stream_process(
            context=ProcessStreamContext(
                run_id="run_test",
                role="tester",
                workdir=tmp_path,
                idle_timeout_seconds=None,
            ),
            args=["missing-stdout"],
            command_event_payload={"type": "command", "message": "missing stdout"},
            callbacks=ProcessStreamCallbacks(
                emit_event=lambda event_type, payload: emitted_events.append((event_type, payload)),
                should_stop=lambda: False,
                set_child_pid=child_pids.append,
                line_handler=lambda _line: None,
                terminate_process=lambda process: terminated_pids.append(process.pid),
            ),
        )

    assert terminated_pids == [fake_process.pid]
    assert child_pids == []
    assert emitted_events == []


def test_stream_process_terminates_child_when_event_callback_fails(tmp_path: Path) -> None:
    child_pids: list[int | None] = []
    terminated_pids: list[int] = []

    def terminate_process(process: subprocess.Popen[str]) -> None:
        terminated_pids.append(process.pid)
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)

    def fail_on_event(_event_type: str, _payload: dict) -> None:
        raise RuntimeError("event failed")

    with pytest.raises(RuntimeError, match="event failed"):
        stream_process(
            context=ProcessStreamContext(
                run_id="run_test",
                role="tester",
                workdir=tmp_path,
                idle_timeout_seconds=None,
            ),
            args=[
                sys.executable,
                "-c",
                "import time; time.sleep(30)",
            ],
            command_event_payload={"type": "command", "message": "python"},
            callbacks=ProcessStreamCallbacks(
                emit_event=fail_on_event,
                should_stop=lambda: False,
                set_child_pid=child_pids.append,
                line_handler=lambda _line: None,
                terminate_process=terminate_process,
            ),
        )

    assert child_pids[0] is not None
    assert child_pids[-1] is None
    assert terminated_pids == [child_pids[0]]


def test_stream_process_terminates_child_when_line_handler_fails(tmp_path: Path) -> None:
    child_pids: list[int | None] = []
    terminated_pids: list[int] = []

    def terminate_process(process: subprocess.Popen[str]) -> None:
        terminated_pids.append(process.pid)
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)

    def fail_on_line(_line: str) -> None:
        raise RuntimeError("handler failed")

    with pytest.raises(RuntimeError, match="handler failed"):
        stream_process(
            context=ProcessStreamContext(
                run_id="run_test",
                role="tester",
                workdir=tmp_path,
                idle_timeout_seconds=None,
            ),
            args=[
                sys.executable,
                "-c",
                "import time; print('ready', flush=True); time.sleep(30)",
            ],
            command_event_payload={"type": "command", "message": "python"},
            callbacks=ProcessStreamCallbacks(
                emit_event=lambda _event_type, _payload: None,
                should_stop=lambda: False,
                set_child_pid=child_pids.append,
                line_handler=fail_on_line,
                terminate_process=terminate_process,
            ),
        )

    assert child_pids[0] is not None
    assert child_pids[-1] is None
    assert terminated_pids == [child_pids[0]]
