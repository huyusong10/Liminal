from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request

import pytest


pytestmark = pytest.mark.release_web

ENABLE_ENV = "LOOPORA_ENABLE_RELEASE_WEB_PROBE"
TIMEOUT_ENV = "LOOPORA_RELEASE_WEB_TIMEOUT_SECONDS"
REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
ADAPTERS = ("codex", "claude", "opencode")


@dataclass(frozen=True)
class AdapterPaths:
    workdir: Path
    gen_skill: Path
    loop_skill: Path | None = None


@dataclass(frozen=True)
class ReleaseWebAdapterFixtures:
    workdir: Path
    codex_paths: AdapterPaths
    claude_paths: AdapterPaths
    opencode_paths: AdapterPaths
    codex_conflict: AdapterPaths
    claude_conflict: AdapterPaths
    opencode_conflict: AdapterPaths


@dataclass(frozen=True)
class ReleaseWebEventInput:
    adapter: str
    phase: str
    state: str
    paths: AdapterPaths
    preserved: bool | None = None


@dataclass(frozen=True)
class ReleaseWebPhaseReportInput:
    workdir: Path
    base_url: str
    command: list[str]
    events: list[dict]
    server_ready: bool
    process: subprocess.Popen | None = None
    error: object | None = None


def _release_web_adapter_fixtures(tmp_path: Path) -> ReleaseWebAdapterFixtures:
    workdir = tmp_path / "release-web-workdir"
    workdir.mkdir()
    conflict_workdir = tmp_path / "release-web-conflict-workdir"
    conflict_workdir.mkdir()
    claude_conflict_workdir = tmp_path / "release-web-claude-conflict-workdir"
    claude_conflict_workdir.mkdir()
    opencode_conflict_workdir = tmp_path / "release-web-opencode-conflict-workdir"
    opencode_conflict_workdir.mkdir()
    conflict_skill = conflict_workdir / ".agents" / "skills" / "loopora-gen" / "SKILL.md"
    conflict_skill.parent.mkdir(parents=True)
    conflict_skill.write_text("# User-owned codex Loopora-looking skill\n", encoding="utf-8")
    claude_conflict_skill = claude_conflict_workdir / ".claude" / "skills" / "loopora-gen" / "SKILL.md"
    claude_conflict_skill.parent.mkdir(parents=True)
    claude_conflict_skill.write_text("# User-owned claude Loopora-looking skill\n", encoding="utf-8")
    opencode_conflict_command = opencode_conflict_workdir / ".opencode" / "commands" / "loopora-gen.md"
    opencode_conflict_command.parent.mkdir(parents=True)
    opencode_conflict_command.write_text("# User-owned opencode Loopora-looking skill\n", encoding="utf-8")
    return ReleaseWebAdapterFixtures(
        workdir=workdir,
        codex_paths=AdapterPaths(
            workdir=workdir,
            gen_skill=workdir / ".agents" / "skills" / "loopora-gen" / "SKILL.md",
            loop_skill=workdir / ".agents" / "skills" / "loopora-loop" / "SKILL.md",
        ),
        claude_paths=AdapterPaths(
            workdir=workdir,
            gen_skill=workdir / ".claude" / "skills" / "loopora-gen" / "SKILL.md",
            loop_skill=workdir / ".claude" / "skills" / "loopora-loop" / "SKILL.md",
        ),
        opencode_paths=AdapterPaths(
            workdir=workdir,
            gen_skill=workdir / ".opencode" / "commands" / "loopora-gen.md",
            loop_skill=workdir / ".opencode" / "commands" / "loopora-loop.md",
        ),
        codex_conflict=AdapterPaths(workdir=conflict_workdir, gen_skill=conflict_skill),
        claude_conflict=AdapterPaths(workdir=claude_conflict_workdir, gen_skill=claude_conflict_skill),
        opencode_conflict=AdapterPaths(workdir=opencode_conflict_workdir, gen_skill=opencode_conflict_command),
    )


def _require_release_web_enabled() -> None:
    if os.environ.get(ENABLE_ENV) != "1":
        pytest.skip(f"set {ENABLE_ENV}=1 to run the real loopora serve browser release-profile probe")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_loopora_server(base_url: str, process: subprocess.Popen, *, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate(timeout=1)
            raise AssertionError(f"loopora serve exited early\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}")
        try:
            with urllib.request.urlopen(f"{base_url}/api/runtime/activity", timeout=1) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if {"running_count", "queued_count", "runs"} <= set(payload):
                return
        except Exception as exc:  # noqa: BLE001 - readiness probe should keep retrying transient server failures.
            last_error = str(exc)
        time.sleep(0.2)
    raise AssertionError(f"Timed out waiting for loopora serve at {base_url}: {last_error}")


def _wait_for_path_state(path: Path, *, exists: bool, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists() is exists:
            return
        time.sleep(0.05)
    state = "exist" if exists else "be removed"
    raise AssertionError(f"Timed out waiting for {path} to {state}")


def _phase_report_path(workdir: Path) -> Path:
    return workdir / ".loopora" / "real-probes" / "release-web-phase-report.json"


def _file_state(path: Path | None) -> dict:
    if path is None:
        return {"path": "", "exists": False}
    return {
        "path": str(path),
        "exists": path.exists(),
        "size_bytes": path.stat().st_size if path.exists() else 0,
    }


def _record_release_web_event(events: list[dict], inputs: ReleaseWebEventInput) -> None:
    events.append(
        {
            "adapter": inputs.adapter,
            "phase": inputs.phase,
            "state": inputs.state,
            "workdir": str(inputs.paths.workdir),
            "gen_skill": _file_state(inputs.paths.gen_skill),
            "loop_skill": _file_state(inputs.paths.loop_skill),
            "preserved_user_file": inputs.preserved,
        }
    )


def _build_release_web_phase_report(inputs: ReleaseWebPhaseReportInput) -> dict:
    statuses: dict[str, dict] = {"server_ready": {"ok": inputs.server_ready}}
    for adapter in ADAPTERS:
        states = [str(item.get("state") or "") for item in inputs.events if item.get("adapter") == adapter]
        statuses[f"{adapter}_states_observed"] = {
            "ok": {"not_installed", "installed", "needs_update", "error"} <= set(states),
            "states": states,
        }
        statuses[f"{adapter}_conflict_preserved"] = {
            "ok": any(item.get("adapter") == adapter and item.get("phase") == "conflict" and item.get("preserved_user_file") is True for item in inputs.events)
        }
    return {
        "schema_version": 1,
        "suite": "release-web",
        "workdir": str(inputs.workdir),
        "base_url": inputs.base_url,
        "command": inputs.command,
        "phase_statuses": statuses,
        "diagnostics": {
            "server_process": {"returncode": inputs.process.poll() if inputs.process is not None else None},
            "events": inputs.events,
            "error": str(inputs.error or "")[:700],
        },
    }


def _write_release_web_phase_report(inputs: ReleaseWebPhaseReportInput) -> tuple[dict, Path]:
    report = _build_release_web_phase_report(inputs)
    path = _phase_report_path(inputs.workdir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report, path


def _format_release_web_failure(message: object, *, report: dict, report_path: Path) -> str:
    compact = {
        "suite": report.get("suite"),
        "base_url": report.get("base_url"),
        "phase_statuses": report.get("phase_statuses"),
        "events_tail": ((report.get("diagnostics") or {}).get("events") or [])[-8:],
    }
    return f"{message}\n\nReal probe phase report: {report_path}\n{json.dumps(compact, ensure_ascii=False, indent=2)}"


def _expect_adapter_state(sync_api, page, adapter: str, state: str) -> None:
    sync_api.expect(page.locator(f'[data-agent-adapter-status="{adapter}"]')).to_have_attribute(
        "data-agent-adapter-state",
        state,
        timeout=5_000,
    )


def _select_adapter_workdir(page, workdir: Path) -> None:
    page.get_by_test_id("agent-adapter-workdir").fill(str(workdir))
    page.get_by_test_id("agent-adapter-refresh").click()


def _exercise_adapter_install_update_uninstall(sync_api, page, *, adapter: str, paths: AdapterPaths, events: list[dict]) -> None:
    if paths.loop_skill is None:
        raise AssertionError("loop skill path is required for install/update/uninstall coverage")
    _select_adapter_workdir(page, paths.workdir)
    _expect_adapter_state(sync_api, page, adapter, "not_installed")
    _record_release_web_event(events, ReleaseWebEventInput(adapter=adapter, phase="initial", state="not_installed", paths=paths))

    page.get_by_test_id(f"agent-adapter-install-{adapter}").click()
    _wait_for_path_state(paths.gen_skill, exists=True)
    _wait_for_path_state(paths.loop_skill, exists=True)
    _expect_adapter_state(sync_api, page, adapter, "installed")
    _record_release_web_event(events, ReleaseWebEventInput(adapter=adapter, phase="install", state="installed", paths=paths))

    paths.gen_skill.write_text(paths.gen_skill.read_text(encoding="utf-8") + "\n<!-- managed drift for release web probe -->\n", encoding="utf-8")
    page.get_by_test_id("agent-adapter-refresh").click()
    _expect_adapter_state(sync_api, page, adapter, "needs_update")
    _record_release_web_event(events, ReleaseWebEventInput(adapter=adapter, phase="drift", state="needs_update", paths=paths))

    page.get_by_test_id(f"agent-adapter-install-{adapter}").click()
    _expect_adapter_state(sync_api, page, adapter, "installed")
    assert "managed drift for release web probe" not in paths.gen_skill.read_text(encoding="utf-8")
    _record_release_web_event(events, ReleaseWebEventInput(adapter=adapter, phase="repair", state="installed", paths=paths))

    page.get_by_test_id(f"agent-adapter-uninstall-{adapter}").click()
    _wait_for_path_state(paths.gen_skill, exists=False)
    _wait_for_path_state(paths.loop_skill, exists=False)
    _expect_adapter_state(sync_api, page, adapter, "not_installed")
    _record_release_web_event(events, ReleaseWebEventInput(adapter=adapter, phase="uninstall", state="not_installed", paths=paths))


def _exercise_adapter_conflict_error(sync_api, page, *, adapter: str, paths: AdapterPaths, events: list[dict]) -> None:
    _select_adapter_workdir(page, paths.workdir)
    _expect_adapter_state(sync_api, page, adapter, "error")
    page.get_by_test_id(f"agent-adapter-install-{adapter}").click()
    sync_api.expect(page.get_by_test_id("agent-adapter-status")).to_be_visible(timeout=5_000)
    preserved = paths.gen_skill.read_text(encoding="utf-8") == f"# User-owned {adapter} Loopora-looking skill\n"
    _record_release_web_event(events, ReleaseWebEventInput(adapter=adapter, phase="conflict", state="error", paths=paths, preserved=preserved))
    assert preserved


def test_release_web_tools_can_manage_agent_adapters_in_real_server(tmp_path: Path, monkeypatch) -> None:
    _require_release_web_enabled()
    sync_api = pytest.importorskip("playwright.sync_api")
    timeout = float(os.environ.get(TIMEOUT_ENV, "30"))
    loopora_home = tmp_path / "loopora-home"
    monkeypatch.setenv("LOOPORA_HOME", str(loopora_home))
    env = os.environ.copy()
    env["LOOPORA_HOME"] = str(loopora_home)
    env["PYTHONPATH"] = f"{SRC_ROOT}{os.pathsep}{env.get('PYTHONPATH', '')}".rstrip(os.pathsep)
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    command = [sys.executable, "-m", "loopora", "serve", "--host", "127.0.0.1", "--port", str(port)]
    process = subprocess.Popen(
        command,
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    fixtures = _release_web_adapter_fixtures(tmp_path)
    events: list[dict] = []
    server_ready = False

    try:
        _wait_for_loopora_server(base_url, process, timeout=timeout)
        server_ready = True
        with sync_api.sync_playwright() as playwright_driver:
            browser = playwright_driver.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            try:
                page.goto(f"{base_url}/tools", wait_until="networkidle")
                _exercise_adapter_install_update_uninstall(
                    sync_api,
                    page,
                    adapter="codex",
                    paths=fixtures.codex_paths,
                    events=events,
                )
                _exercise_adapter_install_update_uninstall(
                    sync_api,
                    page,
                    adapter="claude",
                    paths=fixtures.claude_paths,
                    events=events,
                )
                _exercise_adapter_install_update_uninstall(
                    sync_api,
                    page,
                    adapter="opencode",
                    paths=fixtures.opencode_paths,
                    events=events,
                )
                _exercise_adapter_conflict_error(sync_api, page, adapter="codex", paths=fixtures.codex_conflict, events=events)
                _exercise_adapter_conflict_error(sync_api, page, adapter="claude", paths=fixtures.claude_conflict, events=events)
                _exercise_adapter_conflict_error(sync_api, page, adapter="opencode", paths=fixtures.opencode_conflict, events=events)
                _write_release_web_phase_report(
                    ReleaseWebPhaseReportInput(
                        workdir=fixtures.workdir,
                        base_url=base_url,
                        command=command,
                        events=events,
                        server_ready=server_ready,
                        process=process,
                    )
                )
            finally:
                page.close()
                browser.close()
    except AssertionError as exc:
        report, report_path = _write_release_web_phase_report(
            ReleaseWebPhaseReportInput(
                workdir=fixtures.workdir,
                base_url=base_url,
                command=command,
                events=events,
                server_ready=server_ready,
                process=process,
                error=exc,
            )
        )
        raise AssertionError(_format_release_web_failure(exc, report=report, report_path=report_path)) from None
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
