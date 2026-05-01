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
from loopora.settings import AppSettings
from loopora.web import build_app

playwright = pytest.importorskip("playwright.sync_api")


CALCULATOR_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Calculator</title>
    <style>
      body { font-family: sans-serif; display: grid; place-items: center; min-height: 100vh; margin: 0; background: #f5efe8; }
      .calc { width: 280px; padding: 18px; border-radius: 20px; background: #1f1a14; color: #fff8ed; box-shadow: 0 18px 40px rgba(31, 26, 20, 0.22); }
      [data-testid="display"] { width: 100%; margin-bottom: 12px; padding: 14px; border: none; border-radius: 14px; font-size: 1.8rem; text-align: right; box-sizing: border-box; }
      .grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
      button { min-height: 52px; border: none; border-radius: 14px; font-size: 1rem; cursor: pointer; }
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
      const buttons = document.querySelectorAll('button');
      let expression = '';

      function updateDisplay(value) {
        display.value = value || '0';
      }

      buttons.forEach((button) => {
        button.addEventListener('click', () => {
          const value = button.textContent.trim();
          if (value === 'C') {
            expression = '';
            updateDisplay('0');
            return;
          }
          if (value === '=') {
            try {
              expression = String(Function(`return (${expression || '0'})`)());
              updateDisplay(expression);
            } catch (_) {
              expression = '';
              updateDisplay('ERR');
            }
            return;
          }
          expression += value;
          updateDisplay(expression);
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

        if request.role == "tester":
            return {
                "execution_summary": {
                    "total_checks": 2,
                    "passed": 2,
                    "failed": 0,
                    "errored": 0,
                    "total_duration_ms": 180,
                },
                "check_results": [
                    {
                        "id": "check_001",
                        "title": "Basic addition works",
                        "status": "passed",
                        "notes": "The calculator can evaluate a simple addition flow.",
                    },
                    {
                        "id": "check_002",
                        "title": "Clear resets the display",
                        "status": "passed",
                        "notes": "The clear action returns the display to zero.",
                    },
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
                "metric_scores": {
                    "check_pass_rate": {"value": 1.0, "threshold": 0.9, "passed": True},
                    "quality_score": {"value": 1.0, "threshold": 0.9, "passed": True},
                },
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
        except Exception as exc:  # pragma: no cover - startup timing dependent
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
        except Exception as exc:  # pragma: no cover - environment dependent
            pytest.skip(f"Playwright browser launch is unavailable: {exc}")
        try:
            yield browser
        finally:
            browser.close()


def open_nav_preferences(page) -> None:
    page.get_by_test_id("nav-preferences-toggle").click()
    page.get_by_test_id("nav-preferences-panel").wait_for(state="visible")


def _bundle_yaml_for_workdir(workdir: Path) -> str:
    return FakeCodexExecutor._alignment_bundle_yaml(str(workdir.expanduser().resolve()))


def _wait_for_alignment_status(service: LooporaService, session_id: str, *statuses: str, timeout: float = 10.0) -> dict:
    deadline = time.time() + timeout
    expected = set(statuses)
    while time.time() < deadline:
        session = service.get_alignment_session(session_id)
        if session["status"] in expected:
            return session
        time.sleep(0.05)
    session = service.get_alignment_session(session_id)
    raise AssertionError(f"alignment session stayed in {session['status']}, expected {sorted(expected)}")


def _wait_for_run_status(service: LooporaService, run_id: str, *statuses: str, timeout: float = 15.0) -> dict:
    deadline = time.time() + timeout
    expected = set(statuses)
    while time.time() < deadline:
        run = service.get_run(run_id)
        if run["status"] in expected:
            return run
        time.sleep(0.05)
    run = service.get_run(run_id)
    raise AssertionError(f"run stayed in {run['status']}, expected {sorted(expected)}")


def test_browser_tests_do_not_use_nested_sync_api_entrypoint() -> None:
    forbidden = "playwright.sync_api" + ".sync_playwright"
    assert forbidden not in Path(__file__).read_text(encoding="utf-8")


def _assert_preview_has_expert_tabs_and_stable_hover(page) -> None:
    page.get_by_test_id("alignment-ready-preview").wait_for(state="visible", timeout=10_000)
    assert page.get_by_test_id("alignment-spec-preview").inner_html().strip()
    page.get_by_test_id("alignment-preview-tab-roles").click()
    assert page.locator('[data-testid="alignment-role-list"] [data-testid="alignment-role-card"]').count() >= 3

    page.get_by_test_id("alignment-preview-tab-workflow").click()
    diagram = page.get_by_test_id("alignment-workflow-diagram")
    diagram.locator("svg").wait_for(state="visible", timeout=5_000)
    assert diagram.get_by_test_id("workflow-loop-node").count() >= 3
    assert page.get_by_test_id("alignment-preview-tab-yaml").count() == 0
    page.get_by_test_id("alignment-preview-tab-roles").click()
    first_role = page.locator('[data-testid="alignment-role-card"]').first
    assert first_role.evaluate("(element) => element.open") is False
    first_role.locator('[data-testid="alignment-role-toggle"]').click()
    assert first_role.evaluate("(element) => element.open") is True
    assert first_role.text_content()
    role_pre = first_role.locator("pre").first
    if role_pre.count():
        metrics = role_pre.evaluate(
            """(element) => ({
              clientHeight: element.clientHeight,
              scrollHeight: element.scrollHeight,
              overflowY: getComputedStyle(element).overflowY
            })"""
        )
        assert metrics["overflowY"] != "auto"
        assert metrics["scrollHeight"] <= metrics["clientHeight"] + 1

    page.get_by_test_id("alignment-preview-tab-workflow").click()
    node = diagram.get_by_test_id("workflow-loop-node").nth(1)
    node.scroll_into_view_if_needed()
    layout_before = page.evaluate(
        """() => {
          const rect = (element) => {
            if (!element) {
              return null;
            }
            const box = element.getBoundingClientRect();
            return {
              x: box.x,
              y: box.y,
              width: box.width,
              height: box.height,
              bottom: box.bottom,
            };
          };
          const scrollRegion = document.querySelector('[data-testid="alignment-scroll-region"]');
          const composer = document.querySelector('[data-testid="alignment-start-form"]');
          return {
            diagram: rect(document.querySelector('[data-testid="alignment-workflow-diagram"]')),
            composer: rect(composer),
            scrollHeight: scrollRegion ? scrollRegion.scrollHeight : document.documentElement.scrollHeight,
            scrollTop: scrollRegion ? scrollRegion.scrollTop : document.documentElement.scrollTop,
          };
        }"""
    )
    before = node.evaluate(
        """(element) => {
          const box = element.getBBox();
          return {x: box.x, y: box.y, width: box.width, height: box.height};
        }"""
    )
    node.hover()
    tooltip = diagram.get_by_test_id("workflow-loop-tooltip")
    tooltip.wait_for(state="visible", timeout=2_000)
    tooltip_text = tooltip.text_content() or ""
    assert "2" in tooltip_text
    assert "Inspector" in tooltip_text
    layout_after = page.evaluate(
        """() => {
          const rect = (element) => {
            if (!element) {
              return null;
            }
            const box = element.getBoundingClientRect();
            return {
              x: box.x,
              y: box.y,
              width: box.width,
              height: box.height,
              bottom: box.bottom,
            };
          };
          const scrollRegion = document.querySelector('[data-testid="alignment-scroll-region"]');
          const composer = document.querySelector('[data-testid="alignment-start-form"]');
          return {
            diagram: rect(document.querySelector('[data-testid="alignment-workflow-diagram"]')),
            composer: rect(composer),
            scrollHeight: scrollRegion ? scrollRegion.scrollHeight : document.documentElement.scrollHeight,
            scrollTop: scrollRegion ? scrollRegion.scrollTop : document.documentElement.scrollTop,
          };
        }"""
    )
    after = node.evaluate(
        """(element) => {
          const box = element.getBBox();
          return {x: box.x, y: box.y, width: box.width, height: box.height};
        }"""
    )
    assert abs(before["x"] - after["x"]) <= 0.5
    assert abs(before["y"] - after["y"]) <= 0.5
    assert abs(before["width"] - after["width"]) <= 0.5
    assert abs(before["height"] - after["height"]) <= 0.5
    assert abs(layout_before["diagram"]["height"] - layout_after["diagram"]["height"]) <= 1
    assert abs(layout_before["scrollHeight"] - layout_after["scrollHeight"]) <= 1
    assert abs(layout_before["scrollTop"] - layout_after["scrollTop"]) <= 1
    if layout_before["composer"] and layout_after["composer"]:
        assert abs(layout_before["composer"]["y"] - layout_after["composer"]["y"]) <= 1
        assert abs(layout_before["composer"]["height"] - layout_after["composer"]["height"]) <= 1


def _assert_plan_preview_has_default_summary_and_expert_tabs(page) -> None:
    page.get_by_test_id("alignment-ready-preview").wait_for(state="visible", timeout=10_000)
    page.get_by_test_id("alignment-artifact-summary").wait_for(state="visible", timeout=5_000)
    summary_text = page.get_by_test_id("alignment-artifact-summary").text_content() or ""
    assert "Task" in summary_text or "任务目标" in summary_text
    assert "Evidence" in summary_text or "证据路径" in summary_text
    assert "Verdict" in summary_text or "裁决方式" in summary_text
    assert "Workdir" in summary_text or "运行目录" in summary_text
    _assert_preview_has_expert_tabs_and_stable_hover(page)


def test_local_listener_permission_errors_become_skips() -> None:
    with pytest.raises(pytest.skip.Exception, match="local TCP listeners are unavailable"):
        _skip_if_local_listener_unavailable(PermissionError("blocked"))


def test_local_listener_other_os_errors_still_raise() -> None:
    with pytest.raises(OSError, match="boom"):
        _skip_if_local_listener_unavailable(OSError("boom"))


def test_e2e_calculator_loop_runs_and_works_in_browser(tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.md"
    spec_path.write_text(
        textwrap.dedent(
            """
            # Task

            开发一个计算器。

            # Done When

            - 用户点击 7、+、5、= 后显示 12。
            - 用户点击 C 后显示重置为 0。

            # Guardrails

            - 只需要纯前端
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    workdir = tmp_path / "calculator-workdir"
    workdir.mkdir()
    repository = LooporaRepository(tmp_path / "app.db")
    settings = AppSettings(max_concurrent_runs=1, polling_interval_seconds=0.05, stop_grace_period_seconds=0.2)
    service = LooporaService(
        repository=repository,
        settings=settings,
        executor_factory=lambda: CalculatorPrototypeExecutor(scenario="success"),
    )

    loop = service.create_loop(
        name="Calculator Browser E2E",
        spec_path=spec_path,
        workdir=workdir,
        model="gpt-5.4",
        reasoning_effort="medium",
        max_iters=1,
        max_role_retries=1,
        delta_threshold=0.005,
        trigger_window=2,
        regression_window=2,
        role_models={},
    )
    run = service.rerun(loop["id"])
    assert run["status"] == "succeeded"

    with serve_directory(workdir) as base_url:
        with launch_chromium(headless=True) as browser:
            page = browser.new_page()
            page.goto(f"{base_url}/index.html")
            page.get_by_role("button", name="7").click()
            page.get_by_role("button", name="+").click()
            page.get_by_role("button", name="5").click()
            page.get_by_role("button", name="=").click()
            assert page.locator('[data-testid="display"]').input_value() == "12"

            page.get_by_role("button", name="C").click()
            assert page.locator('[data-testid="display"]').input_value() == "0"


def test_bundle_chat_generation_preview_imports_and_runs_from_browser(tmp_path: Path) -> None:
    workdir = tmp_path / "bundle-chat-workdir"
    workdir.mkdir()
    (workdir / "README.md").write_text("# Bundle chat target\n\nStart here.\n", encoding="utf-8")
    repository = LooporaRepository(tmp_path / "app.db")
    settings = AppSettings(max_concurrent_runs=2, polling_interval_seconds=0.05, stop_grace_period_seconds=0.2)
    service = LooporaService(
        repository=repository,
        settings=settings,
        executor_factory=lambda: FakeCodexExecutor(scenario="success", role_delay=0.2),
    )

    with serve_app(build_app(service=service)) as base_url:
        with launch_chromium(headless=True) as browser:
            page = browser.new_page(viewport={"width": 1440, "height": 1100})
            try:
                page.goto(f"{base_url}/loops/new/bundle", wait_until="networkidle")
                page.get_by_test_id("alignment-empty-state").wait_for(state="visible", timeout=5_000)
                assert page.locator("#bundle-import-yaml").count() == 0
                assert page.get_by_test_id("alignment-ready-preview").is_hidden()
                assert page.get_by_test_id("alignment-live-details").is_hidden()
                page.get_by_test_id("alignment-message-input").fill("保留这条输入")
                page.get_by_test_id("alignment-message-input").press("Shift+Enter")
                page.get_by_test_id("alignment-message-input").type("先触发 workdir 提示。")
                assert "\n" in page.get_by_test_id("alignment-message-input").input_value()
                page.get_by_test_id("alignment-message-input").press("Enter")
                page.get_by_test_id("alignment-tools-menu").wait_for(state="visible", timeout=5_000)
                assert page.get_by_test_id("alignment-message-input").input_value() == "保留这条输入\n先触发 workdir 提示。"
                page.get_by_test_id("alignment-tools-close").click()
                page.get_by_test_id("alignment-tools-menu").wait_for(state="hidden", timeout=5_000)
                page.get_by_test_id("alignment-workdir-chip").click()
                page.get_by_test_id("alignment-tools-menu").wait_for(state="visible", timeout=5_000)
                page.get_by_test_id("alignment-workdir").fill(str(workdir))
                page.get_by_test_id("alignment-message-input").fill("帮我为这个仓库生成一个先小步实现、再取证验收、最后保守放行的循环方案。")
                page.get_by_test_id("alignment-send-button").click()

                page.get_by_test_id("alignment-chat").wait_for(state="visible", timeout=5_000)
                page.get_by_test_id("alignment-thinking-status").wait_for(state="visible", timeout=2_000)
                assert page.get_by_test_id("alignment-live-details").is_visible()
                assert page.get_by_test_id("alignment-live-body").is_hidden()
                before_toggle = page.get_by_test_id("alignment-start-form").bounding_box()
                page.get_by_test_id("alignment-live-toggle").click()
                page.get_by_test_id("alignment-live-body").wait_for(state="visible", timeout=5_000)
                after_toggle = page.get_by_test_id("alignment-start-form").bounding_box()
                assert before_toggle and after_toggle
                assert abs(before_toggle["y"] - after_toggle["y"]) <= 2
                agreement = _wait_for_alignment_status(
                    service,
                    service.list_alignment_sessions(limit=1)[0]["id"],
                    "waiting_user",
                )
                assert agreement["alignment_stage"] == "agreement_ready"
                page.get_by_test_id("alignment-message-input").fill("确认")
                page.get_by_test_id("alignment-send-button").click()
                page.get_by_test_id("alignment-ready-preview").wait_for(state="visible", timeout=10_000)
                session = _wait_for_alignment_status(
                    service,
                    service.list_alignment_sessions(limit=1)[0]["id"],
                    "ready",
                )
                assert session["validation"]["ok"] is True
                bundle_path = Path(session["bundle_path"])
                artifact_dir = Path(session["artifact_dir"])
                assert bundle_path.exists()
                assert bundle_path == artifact_dir / "artifacts" / "bundle.yml"
                assert (artifact_dir / "invocations" / "0001" / "prompt.md").exists()
                assert (artifact_dir / "invocations" / "0001" / "output.json").exists()
                assert (artifact_dir / "events" / "events.jsonl").exists()
                assert (artifact_dir / "conversation" / "transcript.jsonl").exists()
                assert (artifact_dir / "artifacts" / "validation.json").exists()

                transcript_text = page.get_by_test_id("alignment-transcript").text_content() or ""
                assert "循环方案" in transcript_text
                assert page.locator('[data-testid="alignment-console-output"] .console-line').count() >= 2
                assert page.get_by_test_id("alignment-history-item").count() == 1
                page.get_by_test_id("alignment-source-open-button").wait_for(state="visible", timeout=5_000)
                page.get_by_test_id("alignment-source-sync-button").wait_for(state="visible", timeout=5_000)
                sidebar_before = page.get_by_test_id("alignment-history-panel").bounding_box()
                composer_before = page.get_by_test_id("alignment-start-form").bounding_box()
                page.get_by_test_id("alignment-scroll-region").evaluate("node => { node.scrollTop = node.scrollHeight; }")
                sidebar_after = page.get_by_test_id("alignment-history-panel").bounding_box()
                composer_after = page.get_by_test_id("alignment-start-form").bounding_box()
                assert sidebar_before and sidebar_after and composer_before and composer_after
                assert abs(sidebar_before["y"] - sidebar_after["y"]) <= 2
                assert abs(composer_before["y"] - composer_after["y"]) <= 2
                _assert_plan_preview_has_default_summary_and_expert_tabs(page)
                page.get_by_test_id("alignment-new-session-button").click()
                page.get_by_test_id("alignment-ready-preview").wait_for(state="hidden", timeout=5_000)
                page.get_by_test_id("alignment-history-open").first.click()
                page.get_by_test_id("alignment-ready-preview").wait_for(state="visible", timeout=10_000)
                page.get_by_test_id("alignment-status-pill").click()
                _assert_plan_preview_has_default_summary_and_expert_tabs(page)

                page.get_by_test_id("alignment-import-run-button").click()
                page.wait_for_url("**/runs/**", wait_until="networkidle", timeout=10_000)
                run_id = page.url.rstrip("/").split("/")[-1]
                run = _wait_for_run_status(service, run_id, "succeeded", "failed", timeout=20.0)
                assert run["status"] == "succeeded"
                bundles = service.list_bundles()
                assert len(bundles) == 1
                assert bundles[0]["loop_id"] == run["loop_id"]
                assert service.get_alignment_session(session["id"])["linked_run_id"] == run_id
            finally:
                page.close()


def test_bundle_chat_shell_initial_layout_is_minimal_and_responsive(tmp_path: Path) -> None:
    repository = LooporaRepository(tmp_path / "app.db")
    settings = AppSettings(max_concurrent_runs=1, polling_interval_seconds=0.05, stop_grace_period_seconds=0.2)
    service = LooporaService(repository=repository, settings=settings)

    with serve_app(build_app(service=service)) as base_url:
        with launch_chromium(headless=True) as browser:
            for viewport in ({"width": 1440, "height": 960}, {"width": 390, "height": 844}):
                page = browser.new_page(viewport=viewport)
                page.goto(f"{base_url}/loops/new/bundle", wait_until="networkidle")
                page.get_by_test_id("alignment-empty-state").wait_for(state="visible", timeout=5_000)
                assert page.get_by_test_id("alignment-chat").is_hidden()
                assert page.get_by_test_id("alignment-ready-preview").is_hidden()
                assert page.locator("#bundle-import-yaml").count() == 0
                assert page.get_by_test_id("alignment-import-open-button").count() == 0
                assert page.get_by_test_id("alignment-tools-menu").is_hidden()
                page.get_by_test_id("alignment-workdir-chip").click()
                page.get_by_test_id("alignment-tools-menu").wait_for(state="visible", timeout=5_000)
                page.keyboard.press("Escape")
                page.get_by_test_id("alignment-tools-menu").wait_for(state="hidden", timeout=5_000)
                metrics = page.evaluate(
                    """() => ({
                      bodyWidth: document.body.scrollWidth,
                      docScrollHeight: document.documentElement.scrollHeight,
                      viewportHeight: window.innerHeight,
                      viewportWidth: window.innerWidth,
                      composer: document.querySelector('[data-testid="alignment-start-form"]').getBoundingClientRect()
                    })"""
                )
                assert metrics["bodyWidth"] <= metrics["viewportWidth"] + 1
                assert metrics["docScrollHeight"] <= metrics["viewportHeight"] + 1
                assert metrics["composer"]["left"] >= -1
                assert metrics["composer"]["right"] <= metrics["viewportWidth"] + 1
                page.close()
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page.goto(f"{base_url}/loops/new/bundle#bundle-import-form", wait_until="networkidle")
            page.wait_for_url("**/loops/new/manual#bundle-import-form", timeout=5_000)
            page.get_by_test_id("manual-bundle-import-panel").wait_for(state="visible", timeout=5_000)
            page.close()


def test_bundle_chat_history_items_can_be_deleted_from_browser(tmp_path: Path) -> None:
    workdir = tmp_path / "history-delete-workdir"
    workdir.mkdir()
    repository = LooporaRepository(tmp_path / "app.db")
    settings = AppSettings(max_concurrent_runs=1, polling_interval_seconds=0.05, stop_grace_period_seconds=0.2)
    service = LooporaService(repository=repository, settings=settings)
    session = service.create_alignment_session(
        workdir=workdir,
        message="生成一个可删除的历史会话。",
        start_immediately=False,
    )

    with serve_app(build_app(service=service)) as base_url:
        with launch_chromium(headless=True) as browser:
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            try:
                page.goto(f"{base_url}/loops/new/bundle", wait_until="networkidle")
                page.get_by_test_id("alignment-history-item").wait_for(state="visible", timeout=5_000)
                assert page.get_by_test_id("alignment-history-item").count() == 1
                page.get_by_test_id("alignment-history-delete").click()
                page.get_by_test_id("alignment-history-item").wait_for(state="detached", timeout=5_000)
                assert service.list_alignment_sessions(limit=10) == []
                assert not Path(session["artifact_dir"]).exists()
            finally:
                page.close()


def test_bundle_yaml_preview_imports_and_runs_from_browser(tmp_path: Path) -> None:
    workdir = tmp_path / "bundle-yaml-workdir"
    workdir.mkdir()
    (workdir / "README.md").write_text("# Bundle YAML target\n\nStart here.\n", encoding="utf-8")
    bundle_yaml = _bundle_yaml_for_workdir(workdir)
    repository = LooporaRepository(tmp_path / "app.db")
    settings = AppSettings(max_concurrent_runs=2, polling_interval_seconds=0.05, stop_grace_period_seconds=0.2)
    service = LooporaService(
        repository=repository,
        settings=settings,
        executor_factory=lambda: FakeCodexExecutor(scenario="success", role_delay=0.05),
    )

    with serve_app(build_app(service=service)) as base_url:
        with launch_chromium(headless=True) as browser:
            page = browser.new_page(viewport={"width": 1280, "height": 1100})
            try:
                page.goto(f"{base_url}/loops/new/manual#bundle-import-form", wait_until="networkidle")
                page.get_by_test_id("manual-bundle-import-panel").wait_for(state="visible", timeout=5_000)
                page.locator("#bundle-import-yaml").fill(bundle_yaml)
                page.get_by_test_id("bundle-preview-button").click()

                page.get_by_test_id("bundle-preview-import-button").wait_for(state="visible", timeout=10_000)
                assert page.get_by_test_id("alignment-import-run-button").count() == 0
                assert page.get_by_test_id("alignment-source-open-button").is_hidden()
                _assert_preview_has_expert_tabs_and_stable_hover(page)

                page.get_by_test_id("bundle-preview-import-button").click()
                page.wait_for_url("**/runs/**", wait_until="networkidle", timeout=10_000)
                run_id = page.url.rstrip("/").split("/")[-1]
                run = _wait_for_run_status(service, run_id, "succeeded", "failed", timeout=20.0)
                assert run["status"] == "succeeded"
                bundles = service.list_bundles()
                assert len(bundles) == 1
                assert bundles[0]["loop_id"] == run["loop_id"]
                assert service.get_loop(run["loop_id"])["bundle"]["id"] == bundles[0]["id"]
            finally:
                page.close()


def test_web_layout_brand_and_form_are_responsive_and_cleanup_created_loops(
    service_factory,
    sample_spec_file: Path,
    tmp_path: Path,
) -> None:
    service = service_factory(scenario="success")
    created_loop_ids: list[str] = []

    for index in range(3):
        workdir = tmp_path / f"layout-workdir-{index}"
        workdir.mkdir()
        (workdir / "README.md").write_text(f"# Layout fixture {index}\n", encoding="utf-8")
        loop = service.create_loop(
            name=f"Layout Loop {index + 1}",
            spec_path=sample_spec_file,
            workdir=workdir,
            model="gpt-5.4",
            reasoning_effort="medium",
            max_iters=1,
            max_role_retries=1,
            delta_threshold=0.005,
            trigger_window=2,
            regression_window=2,
            role_models={},
        )
        created_loop_ids.append(loop["id"])

    try:
        with serve_app(build_app(service=service)) as base_url:
            with launch_chromium(headless=True) as browser:
                page = browser.new_page(viewport={"width": 375, "height": 844})

                page.goto(f"{base_url}/", wait_until="networkidle")
                assert page.get_by_test_id("top-nav-brand-lockup").get_attribute("src") == "/logo/logo-with-text-horizontal.svg"

                index_mobile = page.evaluate(
                    """() => ({
                      docW: document.documentElement.scrollWidth,
                      clientW: document.documentElement.clientWidth,
                      navW: document.querySelector("[data-testid='top-nav']").scrollWidth,
                      cardCount: document.querySelectorAll("[data-testid='loop-card']").length,
                      pageStackWidth: document.querySelector(".page-stack").getBoundingClientRect().width,
                      noteCount: document.querySelectorAll("[data-testid='loop-grid-note']").length,
                      actionWidths: Array.from(document.querySelector("[data-testid='loop-card'] [data-testid='loop-card-actions']").children).map((node) => Math.round(node.getBoundingClientRect().width))
                    })"""
                )
                assert index_mobile["docW"] == index_mobile["clientW"]
                assert index_mobile["navW"] == index_mobile["clientW"]
                assert index_mobile["cardCount"] == len(created_loop_ids)
                assert index_mobile["noteCount"] == 1
                assert len(set(index_mobile["actionWidths"])) == 1

                page.set_viewport_size({"width": 1440, "height": 1200})
                page.goto(f"{base_url}/", wait_until="networkidle")
                index_desktop = page.evaluate(
                    """() => ({
                      pageStackWidth: document.querySelector(".page-stack").getBoundingClientRect().width,
                      actionWidths: Array.from(document.querySelector("[data-testid='loop-card'] [data-testid='loop-card-actions']").children).map((node) => Math.round(node.getBoundingClientRect().width))
                    })"""
                )
                assert len(set(index_desktop["actionWidths"])) == 1

                page.goto(f"{base_url}/loops/new/manual", wait_until="networkidle")
                desktop_form = page.evaluate(
                    """() => {
                      const form = document.getElementById("new-loop-form").getBoundingClientRect();
                      const hero = document.querySelector(".hero-form").getBoundingClientRect();
                      const stack = document.querySelector(".page-stack").getBoundingClientRect();
                      return {
                        docW: document.documentElement.scrollWidth,
                        clientW: document.documentElement.clientWidth,
                        formWidth: form.width,
                        heroWidth: hero.width,
                        formLeft: form.left,
                        formRight: form.right,
                        pageStackWidth: stack.width
                      };
                    }"""
                )
                assert desktop_form["docW"] == desktop_form["clientW"]
                assert desktop_form["formWidth"] >= 1180
                assert desktop_form["heroWidth"] >= 1180
                assert abs(desktop_form["pageStackWidth"] - index_desktop["pageStackWidth"]) <= 2
                left_gutter = desktop_form["formLeft"]
                right_gutter = desktop_form["clientW"] - desktop_form["formRight"]
                assert abs(left_gutter - right_gutter) <= 24

                page.goto(f"{base_url}/tools", wait_until="networkidle")
                tools_desktop = page.evaluate(
                    """() => ({
                      pageStackWidth: document.querySelector(".page-stack").getBoundingClientRect().width,
                      hasTipsButton: Boolean(document.querySelector(".help-dot--tips")),
                      tipsButtonText: document.querySelector(".help-dot--tips")?.textContent?.trim() || "",
                      nativeTitle: document.querySelector(".help-dot--tips")?.getAttribute("title")
                    })"""
                )
                assert abs(tools_desktop["pageStackWidth"] - index_desktop["pageStackWidth"]) <= 2
                assert tools_desktop["hasTipsButton"] is True
                assert tools_desktop["tipsButtonText"] == "i"
                assert tools_desktop["nativeTitle"] is None

                page.set_viewport_size({"width": 390, "height": 844})
                page.goto(f"{base_url}/loops/new/manual", wait_until="networkidle")
                mobile_form = page.evaluate(
                    """() => {
                      const form = document.getElementById("new-loop-form").getBoundingClientRect();
                      const stack = document.querySelector(".page-stack").getBoundingClientRect();
                      return {
                        docW: document.documentElement.scrollWidth,
                        clientW: document.documentElement.clientWidth,
                        formWidth: form.width,
                        formLeft: form.left,
                        formRight: form.right,
                        pageStackWidth: stack.width
                      };
                    }"""
                )
                assert mobile_form["docW"] == mobile_form["clientW"]
                assert 320 <= mobile_form["formWidth"] <= mobile_form["clientW"]
                assert mobile_form["formLeft"] >= 0
                assert mobile_form["formRight"] <= mobile_form["clientW"] + 1
                assert mobile_form["pageStackWidth"] <= mobile_form["clientW"]
    finally:
        for loop_id in list(created_loop_ids):
            try:
                service.delete_loop(loop_id)
            except Exception:
                continue
        assert service.list_loops() == []


def test_new_loop_page_restores_saved_browser_draft(tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.md"
    spec_path.write_text(
        textwrap.dedent(
            """
            # Task

            Keep an unfinished loop draft around.

            # Guardrails

            - Stay focused.
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    workdir = tmp_path / "draft-workdir"
    workdir.mkdir()
    repository = LooporaRepository(tmp_path / "app.db")
    settings = AppSettings(max_concurrent_runs=1, polling_interval_seconds=0.05, stop_grace_period_seconds=0.2)
    service = LooporaService(
        repository=repository,
        settings=settings,
        executor_factory=lambda: CalculatorPrototypeExecutor(scenario="success"),
    )

    with serve_app(build_app(service=service)) as base_url:
        with launch_chromium() as browser:
            page = browser.new_page()
            page.goto(f"{base_url}/loops/new/manual", wait_until="networkidle")
            page.locator('input[name="name"]').fill("Recovered browser draft")
            page.locator('input[name="workdir"]').fill(str(workdir))
            page.locator('input[name="spec_path"]').fill(str(spec_path))
            page.locator('select[name="orchestration_id"]').select_option("builtin:evidence_first")
            page.locator('select[name="completion_mode"]').select_option("rounds")
            page.reload(wait_until="networkidle")

            assert page.locator('input[name="name"]').input_value() == "Recovered browser draft"
            assert page.locator('input[name="workdir"]').input_value() == str(workdir)
            assert page.locator('input[name="spec_path"]').input_value() == str(spec_path)
            assert page.locator('select[name="orchestration_id"]').input_value() == "builtin:evidence_first"
            assert page.locator('select[name="completion_mode"]').input_value() == "rounds"
            assert page.locator("#draft-status").is_visible()
            assert page.locator("#clear-draft-button").is_visible()


def test_new_loop_page_does_not_restore_pristine_only_browser_defaults(tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.md"
    spec_path.write_text(
        textwrap.dedent(
            """
            # Task

            Avoid treating default form values as a real draft.
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    workdir = tmp_path / "draft-workdir"
    workdir.mkdir()
    repository = LooporaRepository(tmp_path / "app.db")
    settings = AppSettings(max_concurrent_runs=1, polling_interval_seconds=0.05, stop_grace_period_seconds=0.2)
    service = LooporaService(
        repository=repository,
        settings=settings,
        executor_factory=lambda: CalculatorPrototypeExecutor(scenario="success"),
    )

    with serve_app(build_app(service=service)) as base_url:
        with launch_chromium() as browser:
            page = browser.new_page()
            page.goto(f"{base_url}/loops/new/manual", wait_until="networkidle")
            name_input = page.locator('input[name="name"]')
            name_input.fill("Temporary draft")
            name_input.fill("")
            page.locator('input[name="workdir"]').fill(str(workdir))
            page.locator('input[name="workdir"]').fill("")
            page.locator('input[name="spec_path"]').fill(str(spec_path))
            page.locator('input[name="spec_path"]').fill("")
            page.reload(wait_until="networkidle")

            assert page.locator('input[name="name"]').input_value() == ""
            assert page.locator('input[name="workdir"]').input_value() == ""
            assert page.locator('input[name="spec_path"]').input_value() == ""
            assert page.locator("#draft-status").is_hidden()
            assert page.locator("#clear-draft-button").is_hidden()


def test_new_loop_page_can_edit_spec_in_a_markdown_workbench_modal(tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.md"
    checklist = "\n".join(f"- Keep line {index:02d} readable inside the modal body." for index in range(1, 41))
    spec_path.write_text(
        (
            textwrap.dedent(
                """
            # Task

            Update the current spec quickly.

            # Done When

            - Render headings
            - Save edits back to disk
            - Escape <script>alert("xss")</script>

            ```js
            console.log("editor");
            ```
            """
            ).strip()
            + "\n\n"
            + checklist
            + "\n"
        ),
        encoding="utf-8",
    )
    repository = LooporaRepository(tmp_path / "app.db")
    settings = AppSettings(max_concurrent_runs=1, polling_interval_seconds=0.05, stop_grace_period_seconds=0.2)
    service = LooporaService(
        repository=repository,
        settings=settings,
        executor_factory=lambda: CalculatorPrototypeExecutor(scenario="success"),
    )

    with serve_app(build_app(service=service)) as base_url:
        with launch_chromium() as browser:
            page = browser.new_page(viewport={"width": 1440, "height": 960})
            page.goto(f"{base_url}/loops/new/manual", wait_until="networkidle")
            page.locator('input[name="spec_path"]').fill(str(spec_path))
            page.get_by_test_id("spec-editor-button").click()

            modal = page.get_by_test_id("spec-editor-modal")
            assert modal.get_attribute("aria-hidden") == "false"
            assert page.get_by_test_id("spec-editor-validation-pill").is_visible()
            assert page.locator("#spec-preview-path").text_content() == str(spec_path)
            editor = page.get_by_test_id("spec-editor-input")
            assert "# Task" in editor.input_value()
            assert page.locator("#spec-editor-source-panel").is_visible()
            assert page.locator("#spec-editor-preview-panel").is_hidden()
            header_box = page.locator(".spec-preview-copy").bounding_box()
            assert header_box is not None and header_box["width"] > 320
            editor.fill("# Task\n\nUpdated from the modal.\n\n# Done When\n\n- Save to disk\n")
            page.get_by_test_id("save-spec-document-button").click()
            deadline = time.time() + 3
            while time.time() < deadline and "Updated from the modal." not in spec_path.read_text(encoding="utf-8"):
                time.sleep(0.05)
            assert "Updated from the modal." in spec_path.read_text(encoding="utf-8")
            page.get_by_test_id("spec-editor-preview-toggle-button").click()
            assert page.locator("#spec-editor-source-panel").is_hidden()
            assert page.locator("#spec-editor-preview-panel").is_visible()
            page.wait_for_function(
                "() => document.getElementById('spec-preview-content')?.textContent.includes('Updated from the modal.')"
            )
            preview_html = page.locator("#spec-preview-content").inner_html()
            assert "<script>" not in preview_html
            assert "Updated from the modal." in preview_html
            preview_metrics = page.locator("#spec-preview-content").evaluate(
                """(node) => ({
                  overflowY: window.getComputedStyle(node).overflowY,
                  clientHeight: node.clientHeight,
                  scrollHeight: node.scrollHeight,
                })"""
            )
            assert preview_metrics["overflowY"] == "auto"
            assert preview_metrics["scrollHeight"] >= preview_metrics["clientHeight"]

            page.locator("#spec-preview-close").click()
            assert modal.get_attribute("aria-hidden") == "true"


def test_run_detail_renders_sanitized_command_event_summary(tmp_path: Path) -> None:
    workdir = tmp_path / "command-event-workdir"
    workdir.mkdir()
    spec_path = tmp_path / "spec.md"
    spec_path.write_text(
        "# Task\n\nRender sanitized command events.\n\n# Done When\n\n- The command summary appears.\n",
        encoding="utf-8",
    )
    service = LooporaService(
        repository=LooporaRepository(tmp_path / "app.db"),
        settings=AppSettings(max_concurrent_runs=1, polling_interval_seconds=0.05, stop_grace_period_seconds=0.2),
        executor_factory=lambda: FakeCodexExecutor(scenario="success"),
    )
    loop = service.create_loop(
        name="Command Event Loop",
        spec_path=spec_path,
        workdir=workdir,
        model="gpt-5.4",
        reasoning_effort="medium",
        max_iters=1,
        max_role_retries=1,
        delta_threshold=0.005,
        trigger_window=2,
        regression_window=2,
        role_models={},
    )
    run = service.start_run(loop["id"])
    service.repository.append_event(
        run["id"],
        "codex_event",
        {
            "type": "command",
            "message": "codex exec '<prompt omitted>' --auth-token '<secret omitted>'",
            "prompt_omitted": True,
            "token_omitted": True,
        },
    )

    with serve_app(build_app(service=service)) as base_url:
        with launch_chromium(headless=True) as browser:
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            try:
                page.goto(f"{base_url}/runs/{run['id']}", wait_until="domcontentloaded")
                page.wait_for_function(
                    "() => ['ready', 'finished'].includes(document.querySelector('[data-testid=\"run-observation-status\"]')?.dataset.observationState)"
                )
                command_line = page.get_by_test_id("run-console-line").filter(has_text="$ codex exec")
                command_line.wait_for(state="visible", timeout=5_000)
                console_text = page.get_by_test_id("run-console-output").text_content() or ""
                assert "Command" in console_text or "命令" in console_text
                assert "<prompt omitted>" in console_text
                assert "<secret omitted>" in console_text
                assert "PROMPT_SECRET_MARKER" not in console_text
                page.set_viewport_size({"width": 390, "height": 844})
                toolbar_metrics = page.evaluate(
                    """() => {
                      const panel = document.querySelector('[data-testid="run-console-panel"]');
                      const panelBox = panel.getBoundingClientRect();
                      const controls = [
                        document.querySelector('[data-testid="console-popout-link"]'),
                        document.querySelector('[data-testid="console-expand-all"]'),
                        document.querySelector('[data-testid="console-collapse-all"]'),
                      ].filter(Boolean);
                      return {
                        pageOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
                        controlsWithinPanel: controls.every((node) => {
                          const box = node.getBoundingClientRect();
                          return box.left >= panelBox.left - 1 && box.right <= panelBox.right + 1;
                        }),
                      };
                    }"""
                )
                assert toolbar_metrics["pageOverflow"] is False
                assert toolbar_metrics["controlsWithinPanel"] is True
            finally:
                page.close()


def test_run_detail_marks_snapshot_failure_as_degraded(tmp_path: Path) -> None:
    workdir = tmp_path / "snapshot-failure-workdir"
    workdir.mkdir()
    spec_path = tmp_path / "spec.md"
    spec_path.write_text("# Task\n\nObserve degraded snapshot loading.\n", encoding="utf-8")
    service = LooporaService(
        repository=LooporaRepository(tmp_path / "app.db"),
        settings=AppSettings(max_concurrent_runs=1, polling_interval_seconds=0.05, stop_grace_period_seconds=0.2),
        executor_factory=lambda: FakeCodexExecutor(scenario="success"),
    )
    loop = service.create_loop(
        name="Snapshot Failure Loop",
        spec_path=spec_path,
        workdir=workdir,
        model="gpt-5.4",
        reasoning_effort="medium",
        max_iters=1,
        max_role_retries=1,
        delta_threshold=0.005,
        trigger_window=2,
        regression_window=2,
        role_models={},
    )
    run = service.start_run(loop["id"])

    with serve_app(build_app(service=service)) as base_url:
        with launch_chromium(headless=True) as browser:
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            try:
                page.route(
                    "**/api/runs/*/observation-snapshot",
                    lambda route: route.fulfill(
                        status=500,
                        content_type="application/json",
                        body='{"error":"forced snapshot failure"}',
                    ),
                )

                def delayed_stream(route):
                    time.sleep(0.3)
                    route.fulfill(status=204, body="")

                page.route("**/api/runs/*/stream*", delayed_stream)
                page.goto(f"{base_url}/runs/{run['id']}", wait_until="domcontentloaded")
                page.wait_for_function(
                    "() => document.querySelector('[data-testid=\"run-observation-status\"]')?.dataset.observationState === 'degraded'"
                )
                assert page.get_by_test_id("run-observation-status").is_visible()
            finally:
                page.close()


def test_new_loop_page_adapts_runtime_controls_to_selected_orchestration(tmp_path: Path) -> None:
    repository = LooporaRepository(tmp_path / "app.db")
    settings = AppSettings(max_concurrent_runs=1, polling_interval_seconds=0.05, stop_grace_period_seconds=0.2)
    service = LooporaService(
        repository=repository,
        settings=settings,
        executor_factory=lambda: CalculatorPrototypeExecutor(scenario="success"),
    )

    with serve_app(build_app(service=service)) as base_url:
        with launch_chromium() as browser:
            page = browser.new_page()
            rounds_only = service.create_orchestration(
                name="Rounds Only Compatibility",
                workflow={
                    "version": 1,
                    "roles": [
                        {"id": "builder", "name": "Builder", "archetype": "builder", "prompt_ref": "builder.md"},
                    ],
                    "steps": [
                        {"id": "builder_step", "role_id": "builder"},
                    ],
                },
            )
            page.goto(f"{base_url}/loops/new/manual", wait_until="networkidle")

            page.locator('select[name="orchestration_id"]').select_option("builtin:repair_loop")
            assert page.locator('[data-testid="loop-trigger-window-field"]').is_visible()
            assert page.locator('[data-testid="loop-regression-window-field"]').is_visible()
            assert page.locator('select[name="completion_mode"]').input_value() == "gatekeeper"

            page.locator('select[name="orchestration_id"]').select_option(rounds_only["id"])
            assert page.locator('select[name="completion_mode"]').input_value() == "rounds"
            assert page.locator("#completion-mode-note").is_visible()
            policy = page.evaluate(
                """() => {
                  const completion = document.querySelector('select[name="completion_mode"]');
                  const gatekeeperOption = completion.querySelector('option[value="gatekeeper"]');
                  return {
                    triggerHidden: document.querySelector('[data-testid="loop-trigger-window-field"]').hidden,
                    regressionHidden: document.querySelector('[data-testid="loop-regression-window-field"]').hidden,
                    gatekeeperDisabled: gatekeeperOption.disabled,
                    gatekeeperHidden: gatekeeperOption.hidden,
                    note: document.getElementById('completion-mode-note').textContent.trim()
                  };
                }"""
            )
            assert policy["triggerHidden"] is True
            assert policy["regressionHidden"] is True
            assert policy["gatekeeperDisabled"] is True
            assert policy["gatekeeperHidden"] is True
            assert "GateKeeper" in policy["note"] or "守门人" in policy["note"]


def test_role_definition_page_localizes_archetype_options_without_mixed_labels(tmp_path: Path) -> None:
    repository = LooporaRepository(tmp_path / "app.db")
    settings = AppSettings(max_concurrent_runs=1, polling_interval_seconds=0.05, stop_grace_period_seconds=0.2)
    service = LooporaService(
        repository=repository,
        settings=settings,
        executor_factory=lambda: FakeCodexExecutor(scenario="success"),
    )

    with serve_app(build_app(service=service)) as base_url:
        with launch_chromium() as browser:
            page = browser.new_page()
            page.goto(f"{base_url}/roles/new", wait_until="networkidle")

            open_nav_preferences(page)
            page.locator('button[data-set-locale="en"]').click()
            page.wait_for_function(
                "() => document.querySelector('#role-definition-archetype-input option[value=\"inspector\"]')?.textContent === 'Inspector'"
            )
            assert page.locator('#role-definition-archetype-input option[value="inspector"]').text_content() == "Inspector"

            open_nav_preferences(page)
            page.locator('button[data-set-locale="zh"]').click()
            page.wait_for_function(
                "() => document.querySelector('#role-definition-archetype-input option[value=\"inspector\"]')?.textContent === 'Inspector'"
            )
            assert page.locator('#role-definition-archetype-input option[value="inspector"]').text_content() == "Inspector"


def test_role_definition_page_updates_template_guidance_and_builtin_prompt_with_selection(tmp_path: Path) -> None:
    repository = LooporaRepository(tmp_path / "app.db")
    settings = AppSettings(max_concurrent_runs=1, polling_interval_seconds=0.05, stop_grace_period_seconds=0.2)
    service = LooporaService(
        repository=repository,
        settings=settings,
        executor_factory=lambda: FakeCodexExecutor(scenario="success"),
    )

    with serve_app(build_app(service=service)) as base_url:
        with launch_chromium() as browser:
            page = browser.new_page()
            page.goto(f"{base_url}/roles/new", wait_until="networkidle")

            open_nav_preferences(page)
            page.locator('button[data-set-locale="zh"]').click()
            page.select_option("#role-definition-archetype-input", "gatekeeper")
            page.wait_for_function(
                "() => document.querySelector('#role-definition-archetype-summary')?.textContent.includes('负责做放行判断')"
            )

            assert "负责做放行判断" in (page.locator("#role-definition-archetype-summary").text_content() or "")
            assert "建议只放一个" in (page.locator("#role-definition-archetype-recommendation").text_content() or "")
            assert "不建议把它当成实现角色" in (page.locator("#role-definition-archetype-warning").text_content() or "")
            assert "# GateKeeper Prompt" in page.locator("#role-definition-prompt-markdown-input").input_value()
            assert "你是 Loopora 内部的 GateKeeper" in (page.locator("#role-definition-prompt-markdown-preview").text_content() or "")
            assert "version: 1" not in (page.locator("#role-definition-prompt-markdown-preview").text_content() or "")
            assert "archetype: gatekeeper" not in (page.locator("#role-definition-prompt-markdown-preview").text_content() or "")

            open_nav_preferences(page)
            page.locator('button[data-set-locale="en"]').click()
            page.wait_for_function(
                "() => document.querySelector('#role-definition-archetype-summary')?.textContent.includes('Owns the pass/fail decision')"
            )

            assert page.locator('#role-definition-archetype-input option[value="gatekeeper"]').text_content() == "GateKeeper"
            assert "Owns the pass/fail decision" in (page.locator("#role-definition-archetype-summary").text_content() or "")
            assert "Keep one of these near the end of the workflow" in (page.locator("#role-definition-archetype-recommendation").text_content() or "")
            assert "Do not use it as an implementation role" in (page.locator("#role-definition-archetype-warning").text_content() or "")
            assert "# GateKeeper Prompt" in page.locator("#role-definition-prompt-markdown-input").input_value()
            assert "You are the GateKeeper inside Loopora" in (page.locator("#role-definition-prompt-markdown-preview").text_content() or "")
            assert "version: 1" not in (page.locator("#role-definition-prompt-markdown-preview").text_content() or "")
            assert "archetype: gatekeeper" not in (page.locator("#role-definition-prompt-markdown-preview").text_content() or "")


def test_existing_role_page_locks_template_and_orchestration_page_renders_loop_diagrams(tmp_path: Path) -> None:
    repository = LooporaRepository(tmp_path / "app.db")
    settings = AppSettings(max_concurrent_runs=1, polling_interval_seconds=0.05, stop_grace_period_seconds=0.2)
    service = LooporaService(
        repository=repository,
        settings=settings,
        executor_factory=lambda: FakeCodexExecutor(scenario="success"),
    )
    custom_role = service.create_role_definition(
        name="Release Builder",
        description="Ship focused release work.",
        archetype="builder",
        prompt_markdown="""---
version: 1
archetype: builder
---

Focus on scoped release work.
""",
        executor_kind="codex",
        model="gpt-5.4-mini",
        reasoning_effort="medium",
    )

    with serve_app(build_app(service=service)) as base_url:
        with launch_chromium() as browser:
            page = browser.new_page()
            page.goto(f"{base_url}/roles/{custom_role['id']}/edit", wait_until="networkidle")
            expect_disabled = page.locator("#role-definition-archetype-input")
            assert expect_disabled.is_disabled() is True

            page.goto(f"{base_url}/orchestrations", wait_until="networkidle")
            first_diagram = page.locator('[data-testid="orchestration-loop-diagram"]').first
            expect_svg = first_diagram.locator("svg")
            expect_legend = first_diagram.get_by_test_id("workflow-loop-pill")
            assert expect_svg.count() == 1
            assert expect_legend.count() >= 2

            page.goto(f"{base_url}/orchestrations/new", wait_until="networkidle")
            assert page.get_by_test_id("workflow-step-row").count() == 0
            page.select_option("#workflow-starter-select", "repair_loop")
            page.click("#load-workflow-starter-button")
            assert page.get_by_test_id("workflow-step-row").count() == 6
            builder_card = page.get_by_test_id("workflow-step-row").nth(4)
            builder_card.click(position={"x": 160, "y": 84})
            assert builder_card.get_attribute("data-active") == "true"
            builder_card.locator('[data-testid="workflow-step-settings-button"]').click()
            modal = page.locator('[data-testid="workflow-step-settings-modal"]')
            assert modal.get_attribute("aria-hidden") == "false"
            assert page.locator('[data-testid="workflow-settings-role-name"]').evaluate("node => node.tagName") == "STRONG"
            assert "Builder" in (page.locator('[data-testid="workflow-settings-role-name"]').text_content() or "")
            assert page.locator('[data-testid="workflow-settings-step-inherit-session"]').is_checked() is True
            step_model_input = page.locator('[data-testid="workflow-settings-step-model"]')
            step_model_input.fill("gpt-5.4-mini")
            step_extra_cli_args_input = page.locator('[data-testid="workflow-settings-step-extra-cli-args"]')
            step_extra_cli_args_input.fill("--verbose")
            page.click('button[data-close-workflow-settings="1"]')
            assert "gpt-5.4-mini" in (builder_card.text_content() or "")
            assert "--verbose" in (builder_card.text_content() or "")
            guide_pill = page.get_by_test_id("workflow-loop-pill").filter(has_text="Guide").first
            guide_pill.hover()
            assert page.get_by_test_id("workflow-step-row").nth(3).get_attribute("data-role-active") == "true"
            guide_pill.click()
            assert page.get_by_test_id("workflow-step-row").nth(3).get_attribute("data-active") == "true"

            inspector_card = page.get_by_test_id("workflow-step-row").nth(1)
            inspector_card.locator('[data-testid="workflow-step-settings-button"]').click()
            assert page.locator('[data-testid="workflow-settings-step-inherit-session"]').is_checked() is False
            page.click('button[data-close-workflow-settings="1"]')

            page.goto(f"{base_url}/orchestrations/builtin:build_then_parallel_review/edit", wait_until="networkidle")
            page.locator('[data-testid="workflow-step-settings-button"]').first.click()
            assert page.locator('[data-testid="workflow-step-settings-modal"]').get_attribute("aria-hidden") == "false"
            assert page.locator('[data-testid="workflow-settings-step-id"]').is_disabled() is True

            page.goto(f"{base_url}/orchestrations/new", wait_until="networkidle")
            open_nav_preferences(page)
            page.locator('button[data-set-locale="en"]').click()
            page.wait_for_function(
                "() => document.querySelector('#workflow-starter-select option[value=\"build_then_parallel_review\"]')?.textContent === 'Build + Parallel Review'"
            )
            assert page.locator('#workflow-starter-select option[value="build_then_parallel_review"]').text_content() == "Build + Parallel Review"
            page.select_option("#workflow-starter-select", "evidence_first")
            page.click("#load-workflow-starter-button")
            page.locator('[data-testid="workflow-step-settings-button"]').first.click()
            assert page.locator('[data-testid="workflow-settings-step-on-pass"] option[value="continue"]').text_content() == "Continue"
