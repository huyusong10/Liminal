from __future__ import annotations

import socket
import textwrap
import threading
import time
import urllib.request
from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import uvicorn

from loopora.db import LooporaRepository
from loopora.executor import FakeCodexExecutor, RoleRequest
from loopora.service import LooporaService
from loopora.service_agent_adapters import AgentBundleCandidateRequest
from loopora.settings import AppSettings
from loopora.web import build_app

playwright = pytest.importorskip("playwright.sync_api")
pytestmark = pytest.mark.journey


CALCULATOR_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Calculator</title>
    <style>
      body { font-family: sans-serif; display: grid; place-items: center; min-height: 100vh; margin: 0; background: #f5efe8; }
      .calc { width: 280px; padding: 18px; border-radius: 16px; background: #1f1a14; color: #fff8ed; }
      [data-testid="display"] { width: 100%; margin-bottom: 12px; padding: 14px; border: none; border-radius: 12px; font-size: 1.8rem; text-align: right; box-sizing: border-box; }
      .grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
      button { min-height: 52px; border: none; border-radius: 12px; font-size: 1rem; cursor: pointer; }
      .op { background: #f0b35d; }
      .eq { background: #57ba8a; }
      .clear { background: #ea8a7f; }
    </style>
  </head>
  <body>
    <main class="calc">
      <input data-testid="display" value="0" readonly aria-label="display" />
      <div class="grid">
        <button class="clear" type="button">C</button>
        <button type="button">(</button>
        <button type="button">)</button>
        <button class="op" type="button">/</button>
        <button type="button">7</button>
        <button type="button">8</button>
        <button type="button">9</button>
        <button class="op" type="button">*</button>
        <button type="button">4</button>
        <button type="button">5</button>
        <button type="button">6</button>
        <button class="op" type="button">-</button>
        <button type="button">1</button>
        <button type="button">2</button>
        <button type="button">3</button>
        <button class="op" type="button">+</button>
        <button type="button">0</button>
        <button type="button">.</button>
        <button class="eq" type="button">=</button>
      </div>
    </main>
    <script>
      const display = document.querySelector('[data-testid="display"]');
      let expression = '';
      document.querySelectorAll('button').forEach((button) => {
        button.addEventListener('click', () => {
          const value = button.textContent.trim();
          if (value === 'C') {
            expression = '';
            display.value = '0';
          } else if (value === '=') {
            expression = String(Function(`return (${expression || '0'})`)());
            display.value = expression;
          } else {
            expression += value;
            display.value = expression;
          }
        });
      });
    </script>
  </body>
</html>
"""


class CalculatorPrototypeExecutor(FakeCodexExecutor):
    def _build_payload(self, request: RoleRequest) -> dict:
        if request.role == "generator":
            (request.workdir / "index.html").write_text(CALCULATOR_HTML, encoding="utf-8")
            return {
                "attempted": "Created a browser-ready calculator prototype.",
                "abandoned": "Skipped backend features and history storage.",
                "assumption": "A single-file calculator is enough for the prototype goal.",
                "summary": "Added a static calculator app with clickable buttons and a live display.",
                "changed_files": ["index.html"],
            }
        if request.role_archetype == "inspector":
            return {
                "execution_summary": {"total_checks": 2, "passed": 2, "failed": 0, "errored": 0},
                "check_results": [
                    {"id": "check_001", "title": "Basic addition works", "status": "passed"},
                    {"id": "check_002", "title": "Clear resets the display", "status": "passed"},
                ],
                "dynamic_checks": [],
                "tester_observations": "The generated calculator is ready for browser verification.",
            }
        if request.role == "verifier":
            context_packet = request.extra_context.get("context_packet") if isinstance(request.extra_context, dict) else {}
            evidence_refs = [
                str(item.get("id"))
                for item in list((context_packet.get("evidence") or {}).get("items") or [])
                if isinstance(item, dict) and str(item.get("id") or "").strip()
            ][-3:]
            return {
                "passed": True,
                "composite_score": 1.0,
                "metric_scores": {"check_pass_rate": {"value": 1.0, "threshold": 0.9, "passed": True}},
                "hard_constraint_violations": [],
                "failed_check_ids": [],
                "priority_failures": [],
                "feedback_to_generator": "The prototype satisfies the requested calculator scope.",
                "evidence_refs": evidence_refs,
                "evidence_claims": [],
            }
        return super()._build_payload(request)


def _skip_if_local_listener_unavailable(exc: OSError) -> None:
    if isinstance(exc, PermissionError) or getattr(exc, "errno", None) in {1, 13}:
        pytest.skip(f"local TCP listeners are unavailable in this environment: {exc}")
    raise exc


def _reserve_local_port() -> tuple[str, int]:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()
    except OSError as exc:  # pragma: no cover - environment dependent
        _skip_if_local_listener_unavailable(exc)


@contextmanager
def serve_directory(path: Path):
    handler = partial(SimpleHTTPRequestHandler, directory=str(path))
    try:
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    except OSError as exc:  # pragma: no cover - environment dependent
        _skip_if_local_listener_unavailable(exc)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@contextmanager
def serve_app(app):
    host, port = _reserve_local_port()
    config = uvicorn.Config(app, host=host, port=port, log_level="warning", ws="none")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base_url = f"http://{host}:{port}"
    deadline = time.time() + 5
    last_error = None

    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{base_url}/", timeout=0.5) as response:
                if response.status == 200:
                    break
        except OSError as exc:  # pragma: no cover - startup timing dependent
            last_error = exc
            time.sleep(0.05)
    else:  # pragma: no cover - environment dependent
        server.should_exit = True
        thread.join(timeout=5)
        raise RuntimeError(f"app server did not start: {last_error}")

    try:
        yield base_url
    finally:
        server.should_exit = True
        thread.join(timeout=5)


@contextmanager
def launch_chromium(**kwargs):
    with playwright.sync_playwright() as playwright_driver:
        try:
            browser = playwright_driver.chromium.launch(**kwargs)
        except playwright.Error as exc:  # pragma: no cover - environment dependent
            pytest.skip(f"Playwright browser launch is unavailable: {exc}")
        try:
            yield browser
        finally:
            browser.close()


def _service(tmp_path: Path, *, executor_factory=None) -> LooporaService:
    repository = LooporaRepository(tmp_path / "app.db")
    settings = AppSettings(max_concurrent_runs=2, polling_interval_seconds=0.05, stop_grace_period_seconds=0.2)
    return LooporaService(
        repository=repository,
        settings=settings,
        executor_factory=executor_factory or (lambda: FakeCodexExecutor(scenario="success")),
    )


def _create_loop(service: LooporaService, spec_path: Path, workdir: Path) -> dict:
    return service.create_loop(
        name="Browser Journey Loop",
        spec_path=spec_path,
        workdir=workdir,
        model="",
        reasoning_effort="",
        max_iters=1,
        max_role_retries=1,
        delta_threshold=0.005,
        trigger_window=2,
        regression_window=2,
        role_models={},
    )


def _assert_no_horizontal_overflow(page) -> None:
    metrics = page.evaluate(
        """() => ({
          docW: document.documentElement.scrollWidth,
          clientW: document.documentElement.clientWidth,
          bodyW: document.body.scrollWidth,
        })"""
    )
    assert metrics["docW"] <= metrics["clientW"] + 1
    assert metrics["bodyW"] <= metrics["clientW"] + 1


def test_browser_tests_do_not_use_nested_sync_api_entrypoint() -> None:
    forbidden = "playwright.sync_api" + ".sync_playwright"
    assert forbidden not in Path(__file__).read_text(encoding="utf-8")


def test_local_listener_error_classification() -> None:
    with pytest.raises(pytest.skip.Exception, match="local TCP listeners are unavailable"):
        _skip_if_local_listener_unavailable(PermissionError("blocked"))
    with pytest.raises(OSError, match="boom"):
        _skip_if_local_listener_unavailable(OSError("boom"))


def test_browser_calculator_loop_runs_and_generated_app_works(tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.md"
    spec_path.write_text(
        textwrap.dedent(
            """
            # Task

            开发一个计算器。

            # Done When

            - 用户点击 7、+、5、= 后显示 12。
            - 用户点击 C 后显示重置为 0。
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    workdir = tmp_path / "calculator-workdir"
    workdir.mkdir()
    service = _service(tmp_path, executor_factory=lambda: CalculatorPrototypeExecutor(scenario="success"))

    loop = _create_loop(service, spec_path, workdir)
    run = service.rerun(loop["id"])

    assert run["status"] == "succeeded"
    assert service.get_run(run["id"])["task_verdict"]["status"] in {"passed", "passed_with_residual_risk"}
    with serve_directory(workdir) as base_url, launch_chromium(headless=True) as browser:
        page = browser.new_page()
        page.goto(f"{base_url}/index.html")
        page.get_by_role("button", name="7").click()
        page.get_by_role("button", name="+").click()
        page.get_by_role("button", name="5").click()
        page.get_by_role("button", name="=").click()
        assert page.locator('[data-testid="display"]').input_value() == "12"
        page.get_by_role("button", name="C").click()
        assert page.locator('[data-testid="display"]').input_value() == "0"


def test_browser_core_web_surfaces_render_without_overflow(tmp_path: Path) -> None:
    service = _service(tmp_path)
    workdir = tmp_path / "web-workdir"
    workdir.mkdir()
    spec_path = tmp_path / "spec.md"
    spec_path.write_text("# Task\n\nKeep the web surface reachable.\n", encoding="utf-8")
    loop = _create_loop(service, spec_path, workdir)
    run = service.rerun(loop["id"])

    with serve_app(build_app(service=service)) as base_url, launch_chromium(headless=True) as browser:
        page = browser.new_page(viewport={"width": 390, "height": 844})
        for path, testid in (
            ("/", "home-workbench"),
            ("/loops/new/bundle", "alignment-start-form"),
            ("/loops/new/manual", "manual-compose-section"),
            (f"/loops/{loop['id']}", "loop-detail-page"),
            (f"/runs/{run['id']}", "run-detail-page"),
        ):
            page.goto(f"{base_url}{path}", wait_until="domcontentloaded")
            page.get_by_test_id(testid).wait_for(state="visible", timeout=10_000)
            _assert_no_horizontal_overflow(page)


def test_browser_agent_native_handoff_stays_on_loopora_loop_path(tmp_path: Path) -> None:
    service = _service(tmp_path)
    workdir = tmp_path / "agent-native-workdir"
    workdir.mkdir()
    (workdir / "progress.md").write_text("# Progress\n\nInitial state.\n", encoding="utf-8")
    bundle_file = tmp_path / "agent-bundle.yml"
    bundle_file.write_text(FakeCodexExecutor._alignment_bundle_yaml(str(workdir.resolve())), encoding="utf-8")
    service.create_agent_bundle_candidate(
        AgentBundleCandidateRequest(
            adapter="codex",
            workdir=workdir,
            message=(
                "Ship the focused starter experience. The primary user flow must work end to end, "
                "use project-owned evidence, avoid happy-path claim only, keep a clear handoff, "
                "and let GateKeeper reject weak proof."
            ),
            bundle_file=bundle_file,
            entry_source="codex_project_skill",
        )
    )
    started = service.start_agent_loop("codex", workdir=workdir, entry_source="codex_project_skill", execute_async=False)

    with serve_app(build_app(service=service)) as base_url, launch_chromium(headless=True) as browser:
        page = browser.new_page()
        page.goto(f"{base_url}/loops/{started['run']['loop_id']}", wait_until="domcontentloaded")
        page.get_by_test_id("loop-agent-entry-copy-command").wait_for(state="visible", timeout=10_000)
        assert "/loopora-loop" in page.text_content("body")
        assert page.locator('form[action^="/api/loops/"]').count() == 0

        page.goto(f"{base_url}/runs/{started['run']['id']}", wait_until="domcontentloaded")
        page.get_by_test_id("agent-handoff-copy-submit").wait_for(state="visible", timeout=10_000)
        assert "/loopora-loop" in page.text_content("body")
