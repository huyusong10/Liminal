from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from loopora.settings import logs_dir

DEFAULT_AGENT_WEB_HOST = "127.0.0.1"
DEFAULT_AGENT_WEB_PORT = 8742
AGENT_WEB_HOST_ENV = "LOOPORA_AGENT_WEB_HOST"
AGENT_WEB_PORT_ENV = "LOOPORA_AGENT_WEB_PORT"
AGENT_WEB_PID_FILE_ENV = "LOOPORA_AGENT_WEB_PID_FILE"


def ensure_local_web_service(*, host: str = DEFAULT_AGENT_WEB_HOST, preferred_port: int = DEFAULT_AGENT_WEB_PORT) -> dict[str, object]:
    selected_host = str(os.environ.get(AGENT_WEB_HOST_ENV) or host)
    selected_port = _agent_web_port_from_env(preferred_port)
    for port in range(selected_port, min(selected_port + 25, 65536)):
        base_url = f"http://{selected_host}:{port}"
        if _loopora_web_responds(base_url):
            return {"base_url": base_url, "reused": True, "started": False, "port": port}
        if _port_is_available(selected_host, port):
            process = _start_web_process(host=selected_host, port=port)
            _write_agent_web_pid_file(process.pid)
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline:
                if _loopora_web_responds(base_url):
                    return {
                        "base_url": base_url,
                        "reused": False,
                        "started": True,
                        "port": port,
                        "pid": process.pid,
                    }
                time.sleep(0.1)
            return {
                "base_url": base_url,
                "reused": False,
                "started": True,
                "port": port,
                "pid": process.pid,
                "warning": "web service was started but did not respond before timeout",
            }
    return {
        "base_url": f"http://{selected_host}:{selected_port}",
        "reused": False,
        "started": False,
        "port": selected_port,
        "warning": "no available Loopora Web port was found",
    }


def web_url_for_path(path: str, *, web: dict[str, object]) -> str:
    base_url = str(web.get("base_url") or f"http://{DEFAULT_AGENT_WEB_HOST}:{DEFAULT_AGENT_WEB_PORT}").rstrip("/")
    normalized_path = "/" + str(path or "/").lstrip("/")
    return base_url + normalized_path


def _loopora_web_responds(base_url: str) -> bool:
    try:
        with urlopen(f"{base_url}/api/runtime/activity", timeout=0.35) as response:
            if int(response.status) != 200:
                return False
            payload = json.loads(response.read().decode("utf-8"))
            return isinstance(payload, dict) and {"running_count", "queued_count", "runs"}.issubset(payload)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError, URLError, TimeoutError):
        return False


def _port_is_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        return sock.connect_ex((host, port)) != 0


def _start_web_process(*, host: str, port: int) -> subprocess.Popen:
    log_dir = logs_dir()
    stdout_path = log_dir / "agent-web.stdout.log"
    stderr_path = log_dir / "agent-web.stderr.log"
    env = dict(os.environ)
    cwd = Path.cwd()
    with stdout_path.open("a", encoding="utf-8") as stdout_handle, stderr_path.open("a", encoding="utf-8") as stderr_handle:
        return subprocess.Popen(
            [sys.executable, "-m", "loopora", "serve", "--host", host, "--port", str(port)],
            cwd=str(cwd),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=stdout_handle,
            stderr=stderr_handle,
            start_new_session=True,
        )


def _agent_web_port_from_env(default: int) -> int:
    raw = str(os.environ.get(AGENT_WEB_PORT_ENV) or "").strip()
    if not raw:
        return default
    try:
        port = int(raw)
    except ValueError:
        return default
    if 1 <= port <= 65535:
        return port
    return default


def _write_agent_web_pid_file(pid: int) -> None:
    raw_path = str(os.environ.get(AGENT_WEB_PID_FILE_ENV) or "").strip()
    if not raw_path:
        return
    path = Path(raw_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{pid}\n", encoding="utf-8")
