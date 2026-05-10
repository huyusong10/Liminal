from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request

import pytest


pytestmark = pytest.mark.release_web

ENABLE_ENV = "LOOPORA_ENABLE_RELEASE_WEB_E2E"
TIMEOUT_ENV = "LOOPORA_RELEASE_WEB_TIMEOUT_SECONDS"
REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"


def _require_release_web_enabled() -> None:
    if os.environ.get(ENABLE_ENV) != "1":
        pytest.skip(f"set {ENABLE_ENV}=1 to run the real loopora serve browser release gate")


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


def _expect_adapter_state(sync_api, page, adapter: str, state: str) -> None:
    sync_api.expect(page.locator(f'[data-agent-adapter-status="{adapter}"]')).to_have_attribute(
        "data-agent-adapter-state",
        state,
        timeout=5_000,
    )


def _select_adapter_workdir(page, workdir: Path) -> None:
    page.get_by_test_id("agent-adapter-workdir").fill(str(workdir))
    page.get_by_test_id("agent-adapter-refresh").click()


def _assert_future_adapters_are_reserved(sync_api, page) -> None:
    _expect_adapter_state(sync_api, page, "claude", "not_implemented")
    _expect_adapter_state(sync_api, page, "opencode", "not_implemented")
    assert page.get_by_test_id("agent-adapter-install-claude").is_disabled()
    assert page.get_by_test_id("agent-adapter-install-opencode").is_disabled()


def _exercise_codex_install_update_uninstall(sync_api, page, *, workdir: Path, gen_skill: Path, loop_skill: Path) -> None:
    _select_adapter_workdir(page, workdir)
    _assert_future_adapters_are_reserved(sync_api, page)
    _expect_adapter_state(sync_api, page, "codex", "not_installed")

    page.get_by_test_id("agent-adapter-install-codex").click()
    _wait_for_path_state(gen_skill, exists=True)
    _wait_for_path_state(loop_skill, exists=True)
    _expect_adapter_state(sync_api, page, "codex", "installed")

    gen_skill.write_text(gen_skill.read_text(encoding="utf-8") + "\n<!-- managed drift for release web gate -->\n", encoding="utf-8")
    page.get_by_test_id("agent-adapter-refresh").click()
    _expect_adapter_state(sync_api, page, "codex", "needs_update")

    page.get_by_test_id("agent-adapter-install-codex").click()
    _expect_adapter_state(sync_api, page, "codex", "installed")
    assert "managed drift for release web gate" not in gen_skill.read_text(encoding="utf-8")

    page.get_by_test_id("agent-adapter-uninstall-codex").click()
    _wait_for_path_state(gen_skill, exists=False)
    _wait_for_path_state(loop_skill, exists=False)
    _expect_adapter_state(sync_api, page, "codex", "not_installed")


def _exercise_codex_conflict_error(sync_api, page, *, workdir: Path, conflict_skill: Path) -> None:
    _select_adapter_workdir(page, workdir)
    _expect_adapter_state(sync_api, page, "codex", "error")
    page.get_by_test_id("agent-adapter-install-codex").click()
    sync_api.expect(page.get_by_test_id("agent-adapter-status")).to_be_visible(timeout=5_000)
    assert conflict_skill.read_text(encoding="utf-8") == "# User-owned Loopora-looking skill\n"


def test_release_web_tools_can_manage_codex_adapter_in_real_server(tmp_path: Path, monkeypatch) -> None:
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
    process = subprocess.Popen(
        [sys.executable, "-m", "loopora", "serve", "--host", "127.0.0.1", "--port", str(port)],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    workdir = tmp_path / "release-web-workdir"
    workdir.mkdir()
    conflict_workdir = tmp_path / "release-web-conflict-workdir"
    conflict_workdir.mkdir()
    gen_skill = workdir / ".agents" / "skills" / "loopora-gen" / "SKILL.md"
    loop_skill = workdir / ".agents" / "skills" / "loopora-loop" / "SKILL.md"
    conflict_skill = conflict_workdir / ".agents" / "skills" / "loopora-gen" / "SKILL.md"
    conflict_skill.parent.mkdir(parents=True)
    conflict_skill.write_text("# User-owned Loopora-looking skill\n", encoding="utf-8")

    try:
        _wait_for_loopora_server(base_url, process, timeout=timeout)
        with sync_api.sync_playwright() as playwright_driver:
            browser = playwright_driver.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            try:
                page.goto(f"{base_url}/tools", wait_until="networkidle")
                _exercise_codex_install_update_uninstall(sync_api, page, workdir=workdir, gen_skill=gen_skill, loop_skill=loop_skill)
                _exercise_codex_conflict_error(sync_api, page, workdir=conflict_workdir, conflict_skill=conflict_skill)
            finally:
                page.close()
                browser.close()
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
