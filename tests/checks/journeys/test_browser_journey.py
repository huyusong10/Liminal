from __future__ import annotations

import json
import re
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

from loopora.branding import state_dir_for_workdir
from loopora.db import LooporaRepository
from loopora.executor import FakeCodexExecutor, RoleRequest
from loopora.service import LooporaService
from loopora.service_types import LooporaError
from loopora.settings import AppSettings, app_home
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

        if request.role_archetype == "inspector":
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


def open_nav_preferences(page) -> None:
    if page.get_by_test_id("nav-preferences-toggle").count():
        page.get_by_test_id("nav-preferences-toggle").click()
        page.get_by_test_id("nav-preferences-panel").wait_for(state="visible")
        return
    if page.get_by_test_id("nav-display-toggle").count():
        page.get_by_test_id("nav-display-toggle").click()
        page.get_by_test_id("nav-display-panel").wait_for(state="visible")
        return
    page.get_by_test_id("nav-display-controls").wait_for(state="visible")


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


def _wait_for_run_detail_page(page, *, timeout: int = 10_000) -> str:
    page.wait_for_url("**/runs/**", wait_until="domcontentloaded", timeout=timeout)
    page.get_by_test_id("run-detail-page").wait_for(state="visible", timeout=timeout)
    return page.url.rstrip("/").split("/")[-1]


def _layout_guard_metrics(page, selectors: str | None = None) -> dict:
    audited_selectors = selectors or ",".join(
        [
            "h1",
            "h2",
            "h3",
            "p",
            "a",
            "button",
            "label",
            "span",
            "strong",
            "code",
            "pre",
            "input",
            "textarea",
            "select",
            ".form-grid",
            ".input-with-action",
            ".timeline-item",
            ".run-history-item",
            ".status-pill",
        ]
    )
    return page.evaluate(
        """({selectors}) => {
          const viewportWidth = window.innerWidth;
          const isVisible = (node) => {
            const rect = node.getBoundingClientRect();
            const style = getComputedStyle(node);
            return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
          };
          const isStableSurfaceNode = (node) => (
            !node.closest("[data-testid='top-nav']")
            && node.getAttribute("aria-hidden") !== "true"
            && !node.closest("[aria-hidden='true']")
          );
          const escapedNodes = Array.from(document.querySelectorAll(selectors))
            .filter((node) => isVisible(node) && isStableSurfaceNode(node))
            .filter((node) => {
              const rect = node.getBoundingClientRect();
              return rect.left < -1 || rect.right > viewportWidth + 1;
            });
          const tallTextNodes = Array.from(document.querySelectorAll("h1,h2,h3,p,a,button,label,span,strong"))
            .filter((node) => isVisible(node) && isStableSurfaceNode(node))
            .filter((node) => {
              const text = (node.innerText || node.textContent || "").trim();
              const rect = node.getBoundingClientRect();
              return text.length >= 2 && rect.width < 88 && rect.height > Math.max(54, rect.width * 2.25);
            });
          return {
            docW: document.documentElement.scrollWidth,
            clientW: document.documentElement.clientWidth,
            bodyW: document.body.scrollWidth,
            nonNavEscapes: escapedNodes.length,
            escapedSamples: escapedNodes.slice(0, 5).map((node) => {
              const rect = node.getBoundingClientRect();
              return {
                tag: node.tagName,
                testid: node.getAttribute("data-testid") || "",
                text: (node.innerText || node.textContent || "").trim().slice(0, 40),
                left: Math.round(rect.left),
                right: Math.round(rect.right),
                width: Math.round(rect.width),
              };
            }),
            tallTextCount: tallTextNodes.length,
            tallTextSamples: tallTextNodes.slice(0, 5).map((node) => {
              const rect = node.getBoundingClientRect();
              return {
                tag: node.tagName,
                testid: node.getAttribute("data-testid") || "",
                text: (node.innerText || node.textContent || "").trim().slice(0, 40),
                width: Math.round(rect.width),
                height: Math.round(rect.height),
              };
            }),
          };
        }""",
        {"selectors": audited_selectors},
    )


def test_browser_tests_do_not_use_nested_sync_api_entrypoint() -> None:
    forbidden = "playwright.sync_api" + ".sync_playwright"
    assert forbidden not in Path(__file__).read_text(encoding="utf-8")


def _assert_preview_has_expert_tabs_and_stable_hover(page) -> None:
    page.get_by_test_id("alignment-ready-preview").wait_for(state="visible", timeout=10_000)
    diagram = page.get_by_test_id("alignment-workflow-diagram")
    diagram.locator("svg").wait_for(state="visible", timeout=5_000)
    assert diagram.get_by_test_id("workflow-loop-node").count() >= 3
    page.get_by_test_id("alignment-preview-tab-spec").click()
    assert page.get_by_test_id("alignment-spec-preview").inner_html().strip()
    page.get_by_test_id("alignment-preview-tab-roles").click()
    assert page.locator('[data-testid="alignment-role-list"] [data-testid="alignment-role-card"]').count() >= 3

    assert page.get_by_test_id("alignment-preview-tab-workflow").count() == 0
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
    page.get_by_test_id("alignment-workflow-diagram").locator("svg").wait_for(state="visible", timeout=5_000)
    page.get_by_test_id("alignment-artifact-summary").wait_for(state="visible", timeout=5_000)
    summary_text = page.get_by_test_id("alignment-artifact-summary").text_content() or ""
    assert "Risk" in summary_text or "风险" in summary_text
    assert "Evidence" in summary_text or "证据" in summary_text
    assert "Judgment" in summary_text or "判断" in summary_text
    assert "Verdict" in summary_text or "裁决" in summary_text
    assert "Workdir" in summary_text or "目录" in summary_text
    page.get_by_test_id("alignment-judgment-map").wait_for(state="visible", timeout=5_000)
    assert page.get_by_test_id("alignment-preview-tab-spec").get_attribute("aria-selected") == "true"
    assert page.get_by_test_id("alignment-spec-preview").is_visible()
    _assert_preview_has_expert_tabs_and_stable_hover(page)


def test_local_listener_permission_errors_become_skips() -> None:
    with pytest.raises(pytest.skip.Exception, match="local TCP listeners are unavailable"):
        _skip_if_local_listener_unavailable(PermissionError("blocked"))


def test_local_listener_other_os_errors_still_raise() -> None:
    with pytest.raises(OSError, match="boom"):
        _skip_if_local_listener_unavailable(OSError("boom"))


def test_browser_journey_calculator_loop_runs_and_works(tmp_path: Path) -> None:
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
        name="Calculator Browser journey",
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


def _browser_alignment_service(tmp_path: Path, workdir_name: str, *, role_delay: float) -> tuple[LooporaService, Path]:
    workdir = tmp_path / workdir_name
    workdir.mkdir()
    (workdir / "README.md").write_text("# Bundle chat target\n\nStart here.\n", encoding="utf-8")
    repository = LooporaRepository(tmp_path / "app.db")
    settings = AppSettings(max_concurrent_runs=2, polling_interval_seconds=0.05, stop_grace_period_seconds=0.2)
    service = LooporaService(
        repository=repository,
        settings=settings,
        executor_factory=lambda: FakeCodexExecutor(scenario="success", role_delay=role_delay),
    )
    return service, workdir


def _latest_alignment_session_id(service: LooporaService) -> str:
    return service.list_alignment_sessions(limit=1)[0]["id"]


def _prepare_alignment_request_from_browser(page, base_url: str, workdir: Path) -> None:
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


def _assert_alignment_running_shell(page) -> None:
    page.get_by_test_id("alignment-chat").wait_for(state="visible", timeout=5_000)
    assert page.get_by_test_id("alignment-thinking-status").is_hidden()
    page.get_by_test_id("alignment-working-card").wait_for(state="visible", timeout=2_000)
    assert page.get_by_test_id("alignment-status-pill").get_attribute("data-status") in {"running", "validating", "repairing"}
    assert page.get_by_test_id("alignment-send-button").get_attribute("data-action") == "cancel"
    assert page.get_by_test_id("alignment-live-toggle").get_attribute("data-status") in {"running", "validating", "repairing"}
    page.locator('[data-testid="alignment-history-item"].is-running').wait_for(state="visible", timeout=5_000)
    running_history_text = page.locator('[data-testid="alignment-history-item"].is-running').first.text_content() or ""
    assert re.search(r"\b\d+\s*s\b", running_history_text) is None
    assert page.get_by_test_id("alignment-live-details").is_visible()
    assert page.get_by_test_id("alignment-live-body").is_hidden()
    live_toggle_text = page.get_by_test_id("alignment-live-toggle").text_content() or ""
    assert "正在处理" not in live_toggle_text
    assert "Agent 正在执行" not in live_toggle_text
    before_toggle = page.get_by_test_id("alignment-start-form").bounding_box()
    page.get_by_test_id("alignment-live-toggle").click()
    page.get_by_test_id("alignment-live-body").wait_for(state="visible", timeout=5_000)
    after_toggle = page.get_by_test_id("alignment-start-form").bounding_box()
    assert before_toggle
    assert after_toggle
    assert abs(before_toggle["y"] - after_toggle["y"]) <= 2


def _confirm_alignment_ready_from_browser(page, service: LooporaService) -> dict:
    agreement = _wait_for_alignment_status(service, _latest_alignment_session_id(service), "waiting_user")
    assert agreement["alignment_stage"] == "agreement_ready"
    recommended = page.get_by_test_id("alignment-decision-option").filter(has_text=re.compile("采用这个方向|Use this direction")).first
    recommended.wait_for(state="visible", timeout=5_000)
    recommended.click()
    page.get_by_test_id("alignment-ready-preview").wait_for(state="visible", timeout=10_000)
    session = _wait_for_alignment_status(service, _latest_alignment_session_id(service), "ready")
    assert session["validation"]["ok"] is True
    return session


def _assert_alignment_artifacts_and_transcript(page, session: dict) -> None:
    bundle_path = Path(session["bundle_path"])
    artifact_dir = Path(session["artifact_dir"])
    assert bundle_path.exists()
    assert bundle_path == artifact_dir / "artifacts" / "bundle.yml"
    for artifact_path in (
        artifact_dir / "invocations" / "0001" / "prompt.md",
        artifact_dir / "invocations" / "0001" / "output.json",
        artifact_dir / "events" / "events.jsonl",
        artifact_dir / "conversation" / "transcript.jsonl",
        artifact_dir / "artifacts" / "validation.json",
    ):
        assert artifact_path.exists()

    transcript_text = page.get_by_test_id("alignment-transcript").text_content() or ""
    assert "循环方案" in transcript_text
    assert page.locator('[data-testid="alignment-console-output"] .console-line').count() >= 2
    assert page.get_by_test_id("alignment-history-item").count() == 1
    page.get_by_test_id("alignment-source-open-button").wait_for(state="visible", timeout=5_000)
    page.get_by_test_id("alignment-source-sync-button").wait_for(state="visible", timeout=5_000)


def _assert_alignment_preview_surfaces_remain_stable(page) -> None:
    sidebar_before = page.get_by_test_id("alignment-history-panel").bounding_box()
    composer_before = page.get_by_test_id("alignment-start-form").bounding_box()
    page.get_by_test_id("alignment-scroll-region").evaluate("node => { node.scrollTop = node.scrollHeight; }")
    sidebar_after = page.get_by_test_id("alignment-history-panel").bounding_box()
    composer_after = page.get_by_test_id("alignment-start-form").bounding_box()
    assert sidebar_before
    assert sidebar_after
    assert composer_before
    assert composer_after
    assert abs(sidebar_before["y"] - sidebar_after["y"]) <= 2
    assert abs(composer_before["y"] - composer_after["y"]) <= 2
    _assert_plan_preview_has_default_summary_and_expert_tabs(page)
    page.get_by_test_id("alignment-new-session-button").click()
    page.get_by_test_id("alignment-ready-preview").wait_for(state="hidden", timeout=5_000)
    page.get_by_test_id("alignment-history-open").first.click()
    page.get_by_test_id("alignment-ready-preview").wait_for(state="visible", timeout=10_000)
    page.get_by_test_id("alignment-status-pill").click()
    _assert_plan_preview_has_default_summary_and_expert_tabs(page)


def _import_alignment_preview_and_assert_run(page, service: LooporaService, session: dict) -> None:
    page.get_by_test_id("alignment-import-run-button").click()
    run_id = _wait_for_run_detail_page(page)
    run = _wait_for_run_status(service, run_id, "succeeded", "failed", timeout=20.0)
    assert run["status"] == "succeeded"
    bundles = service.list_bundles()
    assert len(bundles) == 1
    assert bundles[0]["loop_id"] == run["loop_id"]
    assert service.get_alignment_session(session["id"])["linked_run_id"] == run_id


def test_bundle_chat_generation_preview_imports_and_runs_from_browser(tmp_path: Path) -> None:
    service, workdir = _browser_alignment_service(tmp_path, "bundle-chat-workdir", role_delay=0.2)

    with serve_app(build_app(service=service)) as base_url, launch_chromium(headless=True) as browser:
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        try:
            _prepare_alignment_request_from_browser(page, base_url, workdir)
            _assert_alignment_running_shell(page)
            session = _confirm_alignment_ready_from_browser(page, service)
            _assert_alignment_artifacts_and_transcript(page, session)
            _assert_alignment_preview_surfaces_remain_stable(page)
            _import_alignment_preview_and_assert_run(page, service, session)
        finally:
            page.close()


def test_bundle_chat_requires_workdir_context_choice_when_loopora_state_exists(tmp_path: Path) -> None:
    service, workdir = _browser_alignment_service(tmp_path, "context-choice-workdir", role_delay=0.0)
    state_dir = state_dir_for_workdir(workdir)
    state_dir.mkdir()
    (state_dir / "spec.md").write_text("# Task\n\n编排一个同目录已有 spec 的 Loop。\n", encoding="utf-8")

    with serve_app(build_app(service=service)) as base_url, launch_chromium(headless=True) as browser:
        page = browser.new_page(viewport={"width": 1280, "height": 920})
        try:
            page.goto(f"{base_url}/loops/new/bundle", wait_until="networkidle")
            page.get_by_test_id("alignment-message-input").fill("继续这个目录中的工作流。")
            page.evaluate("document.getElementById('alignment-workdir-chip').click()")
            page.get_by_test_id("alignment-tools-menu").wait_for(state="visible", timeout=5_000)
            page.get_by_test_id("alignment-workdir").fill(str(workdir))
            page.locator('[data-testid="alignment-workdir-context-option"]').first.wait_for(state="visible", timeout=5_000)
            assert page.locator('input[name="alignment_source_option"]').count() >= 2

            page.get_by_test_id("alignment-tools-close").click()
            page.get_by_test_id("alignment-tools-menu").wait_for(state="hidden", timeout=5_000)
            page.evaluate("document.getElementById('alignment-start-form').requestSubmit()")
            page.locator("#alignment-error").wait_for(state="visible", timeout=5_000)
            assert service.list_alignment_sessions(limit=10) == []

            page.get_by_test_id("alignment-tools-menu").wait_for(state="visible", timeout=5_000)
            page.locator('input[name="alignment_source_option"][value="regenerate"]').check()
            page.evaluate("document.getElementById('alignment-start-form').requestSubmit()")
            page.get_by_test_id("alignment-chat").wait_for(state="visible", timeout=5_000)
            session = _wait_for_alignment_status(service, _latest_alignment_session_id(service), "waiting_user")
            assert session["working_agreement"].get("mode") != "selected_source"
        finally:
            page.close()


def _create_missing_ready_alignment_session(service: LooporaService, tmp_path: Path) -> tuple[dict, Path]:
    missing_bundle_workdir = tmp_path / "missing-ready-bundle"
    missing_bundle_workdir.mkdir()
    missing_bundle_session = service.create_alignment_session(
        workdir=missing_bundle_workdir,
        message="生成一个会缺失源文件的方案。",
        start_immediately=False,
    )
    service.repository.update_alignment_session(
        missing_bundle_session["id"],
        status="ready",
        alignment_stage="ready",
        validation={"ok": False, "error": "bundle file does not exist"},
    )
    return missing_bundle_session, missing_bundle_workdir


def _assert_bundle_shell_layout_for_viewport(browser, base_url: str, viewport: dict[str, int]) -> None:
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
          composer: document.querySelector('[data-testid="alignment-start-form"]').getBoundingClientRect(),
          chipHeights: Array.from(document.querySelectorAll(".alignment-chip")).map((chip) => Math.round(chip.getBoundingClientRect().height))
        })"""
    )
    assert metrics["bodyWidth"] <= metrics["viewportWidth"] + 1
    assert metrics["docScrollHeight"] <= metrics["viewportHeight"] + 1
    assert metrics["composer"]["left"] >= -1
    assert metrics["composer"]["right"] <= metrics["viewportWidth"] + 1
    assert min(metrics["chipHeights"]) >= 34

    page.get_by_test_id("alignment-message-input").focus()
    focus_metrics = page.evaluate(
        """() => {
          const composer = document.querySelector(".alignment-composer-box");
          const shadow = getComputedStyle(composer).boxShadow;
          return {hasFocusRing: shadow !== "none" && shadow.includes("0px 0px 0px 3px")};
        }"""
    )
    assert focus_metrics["hasFocusRing"] is True

    page.goto(f"{base_url}/loops/new/manual#bundle-import-form", wait_until="networkidle")
    page.get_by_test_id("manual-bundle-import-panel").wait_for(state="visible", timeout=5_000)
    assert page.get_by_test_id("loop-create-form").is_hidden()
    _assert_manual_import_layout(page)
    _assert_manual_form_layout(page, base_url)
    page.close()


def _assert_manual_import_layout(page) -> None:
    manual_metrics = page.evaluate(
        """() => {
          const box = (selector) => {
            const element = document.querySelector(selector);
            if (!element) return null;
            const rect = element.getBoundingClientRect();
            return {left: rect.left, right: rect.right, width: rect.width, height: rect.height};
          };
          return {
            bodyWidth: document.body.scrollWidth,
            docScrollHeight: document.documentElement.scrollHeight,
            viewportHeight: window.innerHeight,
            viewportWidth: window.innerWidth,
            activeModes: Array.from(document.querySelectorAll('[data-compose-mode-link].is-active')).map((link) => link.dataset.composeModeLink),
            sidebar: box('[data-testid="alignment-history-panel"]'),
            main: box('[data-testid="loop-manual-compose-panel"]'),
            importPanel: box('[data-testid="manual-bundle-import-panel"]'),
            contentGap: box('[data-testid="manual-bundle-import-panel"]').left - box('[data-testid="loop-manual-compose-panel"]').left,
            tallTextCount: Array.from(document.querySelectorAll('h1,h2,p,a,button,label')).filter((element) => {
              const rect = element.getBoundingClientRect();
              return rect.width > 0 && rect.height > rect.width * 2.2;
            }).length,
          };
        }"""
    )
    assert manual_metrics["bodyWidth"] <= manual_metrics["viewportWidth"] + 1
    assert manual_metrics["docScrollHeight"] <= manual_metrics["viewportHeight"] + 1
    assert manual_metrics["activeModes"] == ["import"]
    assert manual_metrics["importPanel"]["width"] >= min(300, manual_metrics["viewportWidth"] - 80)
    assert manual_metrics["contentGap"] <= 80
    assert manual_metrics["tallTextCount"] == 0
    if manual_metrics["viewportWidth"] >= 900:
        assert manual_metrics["main"]["left"] >= manual_metrics["sidebar"]["right"] - 1


def _assert_manual_form_layout(page, base_url: str) -> None:
    page.goto(f"{base_url}/loops/new/manual#manual-loop-form", wait_until="networkidle")
    page.get_by_test_id("loop-create-form").wait_for(state="visible", timeout=5_000)
    assert page.get_by_test_id("manual-bundle-import-panel").is_hidden()
    assert page.evaluate(
        """() => Array.from(document.querySelectorAll('[data-compose-mode-link].is-active')).map((link) => link.dataset.composeModeLink)"""
    ) == ["manual"]
    assert page.evaluate("""() => Math.round(document.querySelector(".inline-hint-link").getBoundingClientRect().height)""") >= 32
    manual_surface_metrics = _layout_guard_metrics(page)
    form_metrics = page.evaluate(
        """() => {
          const form = document.getElementById("new-loop-form");
          return {formScrollWidth: form.scrollWidth, formClientWidth: form.clientWidth};
        }"""
    )
    assert form_metrics["formScrollWidth"] <= form_metrics["formClientWidth"] + 1
    assert manual_surface_metrics["docW"] == manual_surface_metrics["clientW"]
    assert manual_surface_metrics["bodyW"] <= manual_surface_metrics["clientW"] + 1
    assert manual_surface_metrics["nonNavEscapes"] == 0, manual_surface_metrics["escapedSamples"]
    assert manual_surface_metrics["tallTextCount"] == 0, manual_surface_metrics["tallTextSamples"]


def _assert_missing_ready_bundle_preview_error(browser, base_url: str, session: dict, workdir: Path) -> None:
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    page.goto(f"{base_url}/loops/new/bundle?alignment_session_id={session['id']}", wait_until="networkidle")
    page.get_by_test_id("alignment-ready-preview").wait_for(state="visible", timeout=5_000)
    page.get_by_test_id("alignment-workdir-chip").click()
    page.get_by_test_id("alignment-tools-menu").wait_for(state="visible", timeout=5_000)
    assert page.get_by_test_id("alignment-workdir").input_value() == str(workdir)
    page.keyboard.press("Escape")
    page.get_by_test_id("alignment-tools-menu").wait_for(state="hidden", timeout=5_000)
    error_metrics = page.evaluate(
        """() => {
          const preview = document.querySelector('[data-testid="alignment-ready-preview"]');
          const title = document.getElementById('alignment-artifact-name');
          const kicker = document.getElementById('bundle-preview-title');
          const button = document.getElementById('alignment-import-run-button');
          const titleBox = title.getBoundingClientRect();
          const kickerBox = kicker.getBoundingClientRect();
          const previewBox = preview.getBoundingClientRect();
          return {
            state: preview.dataset.previewState,
            buttonHidden: button.hidden,
            previewWidth: previewBox.width,
            titleWidth: titleBox.width,
            kickerWidth: kickerBox.width,
            tallTextCount: [title, kicker].filter((element) => {
              const rect = element.getBoundingClientRect();
              return rect.width > 0 && rect.height > rect.width * 2.2;
            }).length,
          };
        }"""
    )
    assert error_metrics["state"] == "error"
    assert error_metrics["buttonHidden"] is True
    assert error_metrics["previewWidth"] >= 560
    assert error_metrics["titleWidth"] >= 240
    assert error_metrics["kickerWidth"] >= 100
    assert error_metrics["tallTextCount"] == 0
    page.close()


def _assert_legacy_bundle_import_anchor_redirect(browser, base_url: str) -> None:
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    page.goto(f"{base_url}/loops/new/bundle#bundle-import-form", wait_until="networkidle")
    page.wait_for_url("**/loops/new/manual#bundle-import-form", timeout=5_000)
    page.get_by_test_id("manual-bundle-import-panel").wait_for(state="visible", timeout=5_000)
    page.close()


def test_bundle_chat_shell_initial_layout_is_minimal_and_responsive(tmp_path: Path) -> None:
    repository = LooporaRepository(tmp_path / "app.db")
    settings = AppSettings(max_concurrent_runs=1, polling_interval_seconds=0.05, stop_grace_period_seconds=0.2)
    service = LooporaService(repository=repository, settings=settings)
    missing_bundle_session, missing_bundle_workdir = _create_missing_ready_alignment_session(service, tmp_path)

    with serve_app(build_app(service=service)) as base_url, launch_chromium(headless=True) as browser:
        for viewport in ({"width": 1440, "height": 960}, {"width": 390, "height": 844}):
            _assert_bundle_shell_layout_for_viewport(browser, base_url, viewport)
        _assert_missing_ready_bundle_preview_error(browser, base_url, missing_bundle_session, missing_bundle_workdir)
        _assert_legacy_bundle_import_anchor_redirect(browser, base_url)


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

    with serve_app(build_app(service=service)) as base_url, launch_chromium(headless=True) as browser:
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


def test_tools_local_asset_diagnostics_reveals_problem_paths_from_browser(tmp_path: Path) -> None:
    workdir = tmp_path / "tools-diagnostics-workdir"
    workdir.mkdir()
    spec_path = tmp_path / "spec.md"
    spec_path.write_text(
        """# Task

Keep diagnostics reachable.

# Done When

- Local asset problems can be inspected.
""",
        encoding="utf-8",
    )
    repository = LooporaRepository(tmp_path / "app.db")
    settings = AppSettings(max_concurrent_runs=1, polling_interval_seconds=0.05, stop_grace_period_seconds=0.2)
    service = LooporaService(repository=repository, settings=settings)
    service.create_loop(
        name="Diagnostics Browser Loop",
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
    orphan_alignment_dir = state_dir_for_workdir(workdir) / "alignment_sessions" / "align_browser_orphan"
    orphan_alignment_dir.mkdir(parents=True)
    orphan_bundle_dir = app_home() / "bundles" / "bundle_browser_orphan"
    orphan_bundle_dir.mkdir(parents=True)
    captured_reveal_paths: list[str] = []

    with serve_app(build_app(service=service)) as base_url, launch_chromium(headless=True) as browser:
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        try:
            page.route(
                "**/api/system/reveal-path",
                lambda route: (
                    captured_reveal_paths.append(str(json.loads(route.request.post_data or "{}").get("path", ""))),
                    route.fulfill(status=200, content_type="application/json", body='{"ok": true, "path": ""}'),
                ),
            )
            page.goto(f"{base_url}/tools", wait_until="networkidle")
            page.get_by_test_id("local-assets-issue").first.wait_for(state="visible", timeout=5_000)
            assert page.get_by_test_id("local-assets-details").is_visible()
            assert page.get_by_test_id("local-assets-reveal-button").count() >= 2
            assert "do not delete files" in (page.get_by_test_id("local-assets-details").text_content() or "")
            page.locator('[data-local-assets-kind="orphan_alignment_dirs"] [data-testid="local-assets-reveal-button"]').first.click()
            page.get_by_test_id("local-assets-status").wait_for(state="visible", timeout=5_000)
            assert captured_reveal_paths[-1] == str(orphan_alignment_dir)
        finally:
            page.close()


def _wait_for_path_state(path: Path, *, exists: bool, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists() is exists:
            return
        time.sleep(0.05)
    state = "exist" if exists else "be removed"
    raise AssertionError(f"Timed out waiting for {path} to {state}")


def _exercise_browser_adapter_install_uninstall(page, adapter: str, gen_skill: Path, loop_skill: Path) -> None:
    playwright.expect(page.locator(f'[data-agent-adapter-status="{adapter}"]')).to_have_attribute(
        "data-agent-adapter-state",
        "not_installed",
        timeout=5_000,
    )
    page.get_by_test_id(f"agent-adapter-install-{adapter}").click()
    _wait_for_path_state(gen_skill, exists=True)
    _wait_for_path_state(loop_skill, exists=True)
    playwright.expect(page.locator(f'[data-agent-adapter-status="{adapter}"]')).to_have_attribute(
        "data-agent-adapter-state",
        "installed",
        timeout=5_000,
    )
    page.get_by_test_id(f"agent-adapter-uninstall-{adapter}").click()
    _wait_for_path_state(gen_skill, exists=False)
    _wait_for_path_state(loop_skill, exists=False)
    playwright.expect(page.locator(f'[data-agent-adapter-status="{adapter}"]')).to_have_attribute(
        "data-agent-adapter-state",
        "not_installed",
        timeout=5_000,
    )


def _exercise_browser_adapter_conflict(page, adapter: str, gen_skill: Path, content: str) -> None:
    gen_skill.parent.mkdir(parents=True, exist_ok=True)
    gen_skill.write_text(content, encoding="utf-8")
    page.get_by_test_id("agent-adapter-refresh").click()
    playwright.expect(page.locator(f'[data-agent-adapter-status="{adapter}"]')).to_have_attribute(
        "data-agent-adapter-state",
        "error",
        timeout=5_000,
    )
    page.get_by_test_id(f"agent-adapter-install-{adapter}").click()
    page.get_by_test_id("agent-adapter-status").wait_for(state="visible", timeout=5_000)
    assert gen_skill.read_text(encoding="utf-8") == content


def test_tools_agent_adapter_installs_uninstalls_target_project_from_browser(tmp_path: Path) -> None:
    workdir = tmp_path / "agent-adapter-workdir"
    workdir.mkdir()
    user_agents = workdir / "AGENTS.md"
    user_codex_config = workdir / ".codex" / "config.toml"
    user_claude_md = workdir / "CLAUDE.md"
    user_claude_settings = workdir / ".claude" / "settings.json"
    user_opencode_json = workdir / "opencode.json"
    user_opencode_project_json = workdir / ".opencode" / "opencode.jsonc"
    user_agents.write_text("# User rules stay untouched\n", encoding="utf-8")
    user_codex_config.parent.mkdir()
    user_codex_config.write_text('model = "user-model"\n', encoding="utf-8")
    user_claude_settings.parent.mkdir()
    user_claude_md.write_text("# User Claude rules stay untouched\n", encoding="utf-8")
    user_claude_settings.write_text('{"permissions": {"allow": []}}\n', encoding="utf-8")
    user_opencode_project_json.parent.mkdir()
    user_opencode_json.write_text('{"model": "user/model"}\n', encoding="utf-8")
    user_opencode_project_json.write_text('{"permission": {"bash": "ask"}}\n', encoding="utf-8")
    gen_skill = workdir / ".agents" / "skills" / "loopora-gen" / "SKILL.md"
    loop_skill = workdir / ".agents" / "skills" / "loopora-loop" / "SKILL.md"
    claude_gen_skill = workdir / ".claude" / "skills" / "loopora-gen" / "SKILL.md"
    claude_loop_skill = workdir / ".claude" / "skills" / "loopora-loop" / "SKILL.md"
    opencode_gen_command = workdir / ".opencode" / "commands" / "loopora-gen.md"
    opencode_loop_command = workdir / ".opencode" / "commands" / "loopora-loop.md"
    repository = LooporaRepository(tmp_path / "app.db")
    settings = AppSettings(max_concurrent_runs=1, polling_interval_seconds=0.05, stop_grace_period_seconds=0.2)
    service = LooporaService(repository=repository, settings=settings)

    with serve_app(build_app(service=service)) as base_url, launch_chromium(headless=True) as browser:
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        try:
            page.goto(f"{base_url}/tools", wait_until="networkidle")
            page.get_by_test_id("agent-adapter-workdir").fill(str(workdir))
            page.get_by_test_id("agent-adapter-refresh").click()
            _exercise_browser_adapter_install_uninstall(page, "codex", gen_skill, loop_skill)
            assert user_agents.read_text(encoding="utf-8") == "# User rules stay untouched\n"
            assert user_codex_config.read_text(encoding="utf-8") == 'model = "user-model"\n'
            assert user_claude_md.read_text(encoding="utf-8") == "# User Claude rules stay untouched\n"
            assert json.loads(user_claude_settings.read_text(encoding="utf-8")) == {"permissions": {"allow": []}}
            assert user_opencode_json.read_text(encoding="utf-8") == '{"model": "user/model"}\n'
            assert user_opencode_project_json.read_text(encoding="utf-8") == '{"permission": {"bash": "ask"}}\n'

            _exercise_browser_adapter_install_uninstall(page, "claude", claude_gen_skill, claude_loop_skill)
            assert user_claude_md.read_text(encoding="utf-8") == "# User Claude rules stay untouched\n"
            assert json.loads(user_claude_settings.read_text(encoding="utf-8")) == {"permissions": {"allow": []}}

            _exercise_browser_adapter_install_uninstall(page, "opencode", opencode_gen_command, opencode_loop_command)
            assert user_opencode_json.read_text(encoding="utf-8") == '{"model": "user/model"}\n'
            assert user_opencode_project_json.read_text(encoding="utf-8") == '{"permission": {"bash": "ask"}}\n'

            _exercise_browser_adapter_conflict(page, "codex", gen_skill, "# User-owned Codex skill\n")
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

    with serve_app(build_app(service=service)) as base_url, launch_chromium(headless=True) as browser:
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
            run_id = _wait_for_run_detail_page(page)
            run = _wait_for_run_status(service, run_id, "succeeded", "failed", timeout=20.0)
            assert run["status"] == "succeeded"
            bundles = service.list_bundles()
            assert len(bundles) == 1
            assert bundles[0]["loop_id"] == run["loop_id"]
            assert service.get_loop(run["loop_id"])["bundle"]["id"] == bundles[0]["id"]
        finally:
            page.close()


def _create_layout_loops(service: LooporaService, sample_spec_file: Path, tmp_path: Path) -> list[str]:
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
    return created_loop_ids


def _assert_index_mobile_layout(page, base_url: str, created_loop_ids: list[str]) -> None:
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


def _assert_index_desktop_layout(page, base_url: str) -> dict:
    page.set_viewport_size({"width": 1440, "height": 1200})
    page.goto(f"{base_url}/", wait_until="networkidle")
    index_desktop = page.evaluate(
        """() => ({
          clientW: document.documentElement.clientWidth,
          pageStackWidth: document.querySelector(".page-stack").getBoundingClientRect().width,
          actionWidths: Array.from(document.querySelector("[data-testid='loop-card'] [data-testid='loop-card-actions']").children).map((node) => Math.round(node.getBoundingClientRect().width))
        })"""
    )
    assert len(set(index_desktop["actionWidths"])) == 1
    assert index_desktop["pageStackWidth"] < index_desktop["clientW"]
    return index_desktop


def _assert_desktop_nav_and_display_panel(page, base_url: str) -> None:
    page.goto(f"{base_url}/tutorial", wait_until="networkidle")
    nav_desktop = page.evaluate(
        """() => {
          const ids = [
            "nav-loops-link",
            "nav-compose-link",
            "nav-resource-toggle",
            "nav-tools-link",
            "nav-tutorial-link",
          ];
          const items = ids.map((testid) => {
            const element = document.querySelector(`[data-testid='${testid}']`);
            const rect = element.getBoundingClientRect();
            const style = getComputedStyle(element);
            return {
              testid,
              width: Math.round(rect.width),
              height: Math.round(rect.height),
              background: style.backgroundColor,
              boxShadow: style.boxShadow,
            };
          });
          const resource = document.querySelector("[data-testid='nav-resource-toggle']");
          const resourceBox = resource.getBoundingClientRect();
          const caretBox = resource.querySelector(".nav-menu-caret").getBoundingClientRect();
          const display = document.querySelector("[data-testid='nav-display-toggle']");
          const displayControls = document.querySelector("[data-testid='nav-display-controls']");
          const displayBox = display.getBoundingClientRect();
          resource.click();
          const openBox = resource.getBoundingClientRect();
          display.click();
          const displayPanel = document.querySelector("[data-testid='nav-display-panel']");
          const themeSwitch = document.querySelector("[data-testid='theme-switch']").getBoundingClientRect();
          const localeSwitch = document.querySelector("[data-testid='locale-switch']").getBoundingClientRect();
          return {
            widths: items.map((item) => item.width),
            heights: items.map((item) => item.height),
            resourceBackground: items.find((item) => item.testid === "nav-resource-toggle").background,
            toolsBackground: items.find((item) => item.testid === "nav-tools-link").background,
            resourceShadow: items.find((item) => item.testid === "nav-resource-toggle").boxShadow,
            caretWidth: Math.round(caretBox.width),
            widthAfterOpen: Math.round(openBox.width),
            widthBeforeOpen: Math.round(resourceBox.width),
            expanded: resource.getAttribute("aria-expanded"),
            panelHidden: document.querySelector("[data-testid='nav-resource-panel']").hidden,
            displayWidth: Math.round(displayBox.width),
            displayControlsWidth: Math.round(displayControls.getBoundingClientRect().width),
            displayExpanded: display.getAttribute("aria-expanded"),
            displayPanelHidden: displayPanel.hidden,
            themeSwitchWidth: Math.round(themeSwitch.width),
            localeSwitchWidth: Math.round(localeSwitch.width),
          };
        }"""
    )
    assert len(set(nav_desktop["widths"])) == 1
    assert len(set(nav_desktop["heights"])) == 1
    assert nav_desktop["resourceBackground"] == nav_desktop["toolsBackground"]
    assert nav_desktop["resourceShadow"] == "none"
    assert nav_desktop["caretWidth"] >= 5
    assert abs(nav_desktop["widthAfterOpen"] - nav_desktop["widthBeforeOpen"]) <= 1
    assert nav_desktop["expanded"] == "false"
    assert nav_desktop["panelHidden"] is True
    assert nav_desktop["displayWidth"] <= 40
    assert nav_desktop["displayControlsWidth"] <= 44
    assert nav_desktop["displayExpanded"] == "true"
    assert nav_desktop["displayPanelHidden"] is False
    assert 160 <= nav_desktop["themeSwitchWidth"] <= 240
    assert 120 <= nav_desktop["localeSwitchWidth"] <= 220


def _assert_nav_item_state_for_viewports(page, base_url: str) -> None:
    for width, height, theme in ((390, 844, "light"), (1440, 1200, "dark")):
        page.set_viewport_size({"width": width, "height": height})
        page.goto(f"{base_url}/tutorial", wait_until="networkidle")
        page.evaluate(
            """(themeName) => {
              window.localStorage.setItem("loopora:theme", themeName);
              document.documentElement.setAttribute("data-theme", themeName);
            }""",
            theme,
        )
        nav_state = page.evaluate(
            """() => {
              const ids = [
                "nav-loops-link",
                "nav-compose-link",
                "nav-resource-toggle",
                "nav-tools-link",
                "nav-tutorial-link",
              ];
              const items = ids.map((testid) => {
                const element = document.querySelector(`[data-testid='${testid}']`);
                const rect = element.getBoundingClientRect();
                const style = getComputedStyle(element);
                return {
                  testid,
                  width: Math.round(rect.width),
                  height: Math.round(rect.height),
                  background: style.backgroundColor,
                  boxShadow: style.boxShadow,
                };
              });
              return {
                widths: items.map((item) => item.width),
                heights: items.map((item) => item.height),
                resourceBackground: items.find((item) => item.testid === "nav-resource-toggle").background,
                toolsBackground: items.find((item) => item.testid === "nav-tools-link").background,
                resourceShadow: items.find((item) => item.testid === "nav-resource-toggle").boxShadow,
              };
            }"""
        )
        assert len(set(nav_state["widths"])) == 1
        assert len(set(nav_state["heights"])) == 1
        assert nav_state["resourceBackground"] == nav_state["toolsBackground"]
        assert nav_state["resourceShadow"] == "none"
    page.evaluate(
        """() => {
          window.localStorage.setItem("loopora:theme", "light");
          document.documentElement.setAttribute("data-theme", "light");
        }"""
    )


def _assert_top_nav_heights_stable(page, base_url: str) -> None:
    nav_heights_by_viewport: dict[int, list[int]] = {}
    for width, height in ((1440, 1200), (900, 700), (390, 844)):
        page.set_viewport_size({"width": width, "height": height})
        heights = []
        for path in ("/", "/loops/new/bundle", "/loops/new/manual#manual-loop-form", "/tutorial"):
            page.goto(f"{base_url}{path}", wait_until="networkidle")
            if path.startswith("/loops/new/manual"):
                page.get_by_test_id("loop-create-form").wait_for(state="visible", timeout=5_000)
            heights.append(round(page.get_by_test_id("top-nav").bounding_box()["height"]))
        nav_heights_by_viewport[width] = heights
    for heights in nav_heights_by_viewport.values():
        assert max(heights) - min(heights) <= 1


def _assert_desktop_manual_form_layout(page, base_url: str) -> dict:
    page.set_viewport_size({"width": 1440, "height": 1200})
    page.goto(f"{base_url}/loops/new/manual#manual-loop-form", wait_until="networkidle")
    page.get_by_test_id("loop-create-form").wait_for(state="visible", timeout=5_000)
    desktop_form = page.evaluate(
        """() => {
          const form = document.getElementById("new-loop-form").getBoundingClientRect();
          const main = document.querySelector("[data-testid='loop-manual-compose-panel']").getBoundingClientRect();
          const sidebar = document.querySelector("[data-testid='alignment-history-panel']").getBoundingClientRect();
          const stack = document.querySelector(".page-stack").getBoundingClientRect();
          return {
            docW: document.documentElement.scrollWidth,
            clientW: document.documentElement.clientWidth,
            formWidth: form.width,
            formLeft: form.left,
            formRight: form.right,
            mainWidth: main.width,
            mainLeft: main.left,
            mainRight: main.right,
            sidebarRight: sidebar.right,
            pageStackWidth: stack.width
          };
        }"""
    )
    assert desktop_form["docW"] == desktop_form["clientW"]
    assert desktop_form["formWidth"] >= 980
    assert desktop_form["mainWidth"] >= 1080
    assert desktop_form["mainLeft"] >= desktop_form["sidebarRight"] - 1
    assert desktop_form["pageStackWidth"] == desktop_form["clientW"]
    left_gutter = desktop_form["formLeft"] - desktop_form["mainLeft"]
    right_gutter = desktop_form["mainRight"] - desktop_form["formRight"]
    assert abs(left_gutter - right_gutter) <= 24
    return desktop_form


def _assert_tools_page_width_and_tip_button(page, base_url: str, reference_stack_width: float) -> None:
    page.goto(f"{base_url}/tools", wait_until="networkidle")
    tools_desktop = page.evaluate(
        """() => ({
          pageStackWidth: document.querySelector(".page-stack").getBoundingClientRect().width,
          hasTipsButton: Boolean(document.querySelector(".help-dot--tips")),
          tipsButtonText: document.querySelector(".help-dot--tips")?.textContent?.trim() || "",
          nativeTitle: document.querySelector(".help-dot--tips")?.getAttribute("title"),
          tipsButtonWidth: Math.round(document.querySelector(".help-dot--tips")?.getBoundingClientRect().width || 0),
          tipsButtonHeight: Math.round(document.querySelector(".help-dot--tips")?.getBoundingClientRect().height || 0)
        })"""
    )
    assert abs(tools_desktop["pageStackWidth"] - reference_stack_width) <= 2
    assert tools_desktop["hasTipsButton"] is True
    assert tools_desktop["tipsButtonText"] == "i"
    assert tools_desktop["nativeTitle"] is None
    assert tools_desktop["tipsButtonWidth"] >= 24
    assert tools_desktop["tipsButtonHeight"] >= 24


def _assert_shared_page_stack_widths(page, base_url: str, service: LooporaService, loop_id: str, reference_width: float) -> None:
    layout_run = service.start_run(loop_id)
    service.repository.append_event(layout_run["id"], "run_started", {"status": "queued"})
    service.repository.update_run(layout_run["id"], status="succeeded")
    for path, testid in (
        ("/bundles", "bundles-page"),
        ("/roles", "role-definitions-page"),
        ("/orchestrations", "orchestrations-page"),
        ("/tutorial", "tutorial-page"),
        (f"/loops/{loop_id}", "loop-detail-page"),
        (f"/runs/{layout_run['id']}", "run-detail-page"),
    ):
        page.goto(f"{base_url}{path}", wait_until="networkidle")
        page.get_by_test_id(testid).wait_for(state="visible", timeout=5_000)
        page_width = page.get_by_test_id(testid).bounding_box()["width"]
        assert abs(page_width - reference_width) <= 2


def _assert_wide_manual_form_layout(page, base_url: str, reference_width: float) -> None:
    page.set_viewport_size({"width": 1920, "height": 1200})
    page.goto(f"{base_url}/loops/new/manual#manual-loop-form", wait_until="networkidle")
    page.get_by_test_id("loop-create-form").wait_for(state="visible", timeout=5_000)
    wide_form = page.evaluate(
        """() => {
          const form = document.getElementById("new-loop-form").getBoundingClientRect();
          const main = document.querySelector("[data-testid='loop-manual-compose-panel']").getBoundingClientRect();
          const stack = document.querySelector(".page-stack").getBoundingClientRect();
          return {
            clientW: document.documentElement.clientWidth,
            formWidth: form.width,
            formLeft: form.left,
            formRight: form.right,
            mainLeft: main.left,
            mainRight: main.right,
            pageStackWidth: stack.width
          };
        }"""
    )
    assert wide_form["pageStackWidth"] == wide_form["clientW"]
    assert wide_form["formWidth"] <= reference_width + 1
    wide_left_gutter = wide_form["formLeft"] - wide_form["mainLeft"]
    wide_right_gutter = wide_form["mainRight"] - wide_form["formRight"]
    assert abs(wide_left_gutter - wide_right_gutter) <= 24


def _assert_mobile_manual_form_layout(page, base_url: str) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{base_url}/loops/new/manual#manual-loop-form", wait_until="networkidle")
    page.get_by_test_id("loop-create-form").wait_for(state="visible", timeout=5_000)
    page.evaluate(
        """() => {
          window.localStorage.setItem("loopora:locale", "en");
          document.documentElement.setAttribute("data-locale", "en");
          document.documentElement.setAttribute("lang", "en");
        }"""
    )
    mobile_form = page.evaluate(
        """() => {
          const formElement = document.getElementById("new-loop-form");
          const form = formElement.getBoundingClientRect();
          const stack = document.querySelector(".page-stack").getBoundingClientRect();
          return {
            docW: document.documentElement.scrollWidth,
            clientW: document.documentElement.clientWidth,
            formScrollWidth: formElement.scrollWidth,
            formClientWidth: formElement.clientWidth,
            formWidth: form.width,
            formLeft: form.left,
            formRight: form.right,
            pageStackWidth: stack.width
          };
        }"""
    )
    assert mobile_form["docW"] == mobile_form["clientW"]
    assert 300 <= mobile_form["formWidth"] <= mobile_form["clientW"]
    assert mobile_form["formLeft"] >= 0
    assert mobile_form["formRight"] <= mobile_form["clientW"] + 1
    assert mobile_form["pageStackWidth"] <= mobile_form["clientW"]
    assert mobile_form["formScrollWidth"] <= mobile_form["formClientWidth"] + 1
    mobile_form_surface = _layout_guard_metrics(page)
    assert mobile_form_surface["nonNavEscapes"] == 0, mobile_form_surface["escapedSamples"]
    assert mobile_form_surface["tallTextCount"] == 0, mobile_form_surface["tallTextSamples"]


def _assert_mobile_orchestration_layout(page, base_url: str) -> None:
    page.goto(f"{base_url}/orchestrations/new", wait_until="networkidle")
    page.get_by_test_id("orchestration-editor-form").wait_for(state="visible", timeout=5_000)
    page.evaluate(
        """() => {
          window.localStorage.setItem("loopora:locale", "en");
          document.documentElement.setAttribute("data-locale", "en");
          document.documentElement.setAttribute("lang", "en");
        }"""
    )
    orchestration_mobile = _layout_guard_metrics(
        page,
        ".orchestration-header-grid,.orchestration-meta-field,.workflow-toolbar-inline,label,input,textarea,select,button,a",
    )
    assert orchestration_mobile["docW"] == orchestration_mobile["clientW"]
    assert orchestration_mobile["bodyW"] <= orchestration_mobile["clientW"] + 1
    assert orchestration_mobile["nonNavEscapes"] == 0, orchestration_mobile["escapedSamples"]
    assert orchestration_mobile["tallTextCount"] == 0, orchestration_mobile["tallTextSamples"]


def _assert_mobile_loop_detail_layout(page, base_url: str, loop_id: str) -> None:
    page.goto(f"{base_url}/loops/{loop_id}", wait_until="networkidle")
    page.get_by_test_id("loop-detail-history-panel").wait_for(state="visible", timeout=5_000)
    loop_detail_mobile = _layout_guard_metrics(
        page,
        ".timeline-item,.run-history-item,.loop-detail-history-time,.status-pill,code,pre,a,button,label,span,strong",
    )
    assert loop_detail_mobile["docW"] == loop_detail_mobile["clientW"]
    assert loop_detail_mobile["bodyW"] <= loop_detail_mobile["clientW"] + 1
    assert loop_detail_mobile["nonNavEscapes"] == 0, loop_detail_mobile["escapedSamples"]
    assert loop_detail_mobile["tallTextCount"] == 0, loop_detail_mobile["tallTextSamples"]


def test_web_layout_brand_and_form_are_responsive_and_cleanup_created_loops(
    service_factory,
    sample_spec_file: Path,
    tmp_path: Path,
) -> None:
    service = service_factory(scenario="success")
    created_loop_ids = _create_layout_loops(service, sample_spec_file, tmp_path)

    try:
        with serve_app(build_app(service=service)) as base_url, launch_chromium(headless=True) as browser:
            page = browser.new_page(viewport={"width": 375, "height": 844})
            _assert_index_mobile_layout(page, base_url, created_loop_ids)
            index_desktop = _assert_index_desktop_layout(page, base_url)
            _assert_desktop_nav_and_display_panel(page, base_url)
            _assert_nav_item_state_for_viewports(page, base_url)
            _assert_top_nav_heights_stable(page, base_url)
            _assert_desktop_manual_form_layout(page, base_url)
            _assert_tools_page_width_and_tip_button(page, base_url, index_desktop["pageStackWidth"])
            _assert_shared_page_stack_widths(page, base_url, service, created_loop_ids[0], index_desktop["pageStackWidth"])
            _assert_wide_manual_form_layout(page, base_url, index_desktop["pageStackWidth"])
            _assert_mobile_manual_form_layout(page, base_url)
            _assert_mobile_orchestration_layout(page, base_url)
            _assert_mobile_loop_detail_layout(page, base_url, created_loop_ids[0])
    finally:
        cleanup_errors = []
        for loop_id in list(created_loop_ids):
            try:
                service.delete_loop(loop_id)
            except LooporaError as exc:
                cleanup_errors.append(f"{loop_id}: {exc}")
        assert cleanup_errors == []
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

    with serve_app(build_app(service=service)) as base_url, launch_chromium() as browser:
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

    with serve_app(build_app(service=service)) as base_url, launch_chromium() as browser:
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

    with serve_app(build_app(service=service)) as base_url, launch_chromium() as browser:
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
        assert header_box is not None
        assert header_box["width"] > 320
        editor.fill("# Task\n\nUpdated from the modal.\n\n# Done When\n\n- Save to disk\n")
        page.get_by_test_id("save-spec-document-button").click()
        deadline = time.time() + 3
        while time.time() < deadline and "Updated from the modal." not in spec_path.read_text(encoding="utf-8"):
            time.sleep(0.05)
        assert "Updated from the modal." in spec_path.read_text(encoding="utf-8")
        page.get_by_test_id("spec-editor-preview-toggle-button").click()
        assert page.locator("#spec-editor-source-panel").is_hidden()
        assert page.locator("#spec-editor-preview-panel").is_visible()
        page.wait_for_function("() => document.getElementById('spec-preview-content')?.textContent.includes('Updated from the modal.')")
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

    with serve_app(build_app(service=service)) as base_url, launch_chromium(headless=True) as browser:
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

    with serve_app(build_app(service=service)) as base_url, launch_chromium(headless=True) as browser:
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
            page.wait_for_function("() => document.querySelector('[data-testid=\"run-observation-status\"]')?.dataset.observationState === 'degraded'")
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

    with serve_app(build_app(service=service)) as base_url, launch_chromium() as browser:
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
        assert "GateKeeper" in policy["note"] or "守门者" in policy["note"]


def test_role_definition_page_localizes_archetype_options_without_mixed_labels(tmp_path: Path) -> None:
    repository = LooporaRepository(tmp_path / "app.db")
    settings = AppSettings(max_concurrent_runs=1, polling_interval_seconds=0.05, stop_grace_period_seconds=0.2)
    service = LooporaService(
        repository=repository,
        settings=settings,
        executor_factory=lambda: FakeCodexExecutor(scenario="success"),
    )

    with serve_app(build_app(service=service)) as base_url, launch_chromium() as browser:
        page = browser.new_page()
        page.goto(f"{base_url}/roles/new", wait_until="networkidle")

        open_nav_preferences(page)
        page.locator('button[data-set-locale="en"]').click()
        page.wait_for_function("() => document.querySelector('#role-definition-archetype-input option[value=\"inspector\"]')?.textContent === 'Inspector'")
        assert page.locator('#role-definition-archetype-input option[value="inspector"]').text_content() == "Inspector"

        open_nav_preferences(page)
        page.locator('button[data-set-locale="zh"]').click()
        page.wait_for_function("() => document.querySelector('#role-definition-archetype-input option[value=\"inspector\"]')?.textContent === '巡检者'")
        assert page.locator('#role-definition-archetype-input option[value="inspector"]').text_content() == "巡检者"


def test_role_definition_page_updates_template_guidance_and_builtin_prompt_with_selection(tmp_path: Path) -> None:
    repository = LooporaRepository(tmp_path / "app.db")
    settings = AppSettings(max_concurrent_runs=1, polling_interval_seconds=0.05, stop_grace_period_seconds=0.2)
    service = LooporaService(
        repository=repository,
        settings=settings,
        executor_factory=lambda: FakeCodexExecutor(scenario="success"),
    )

    with serve_app(build_app(service=service)) as base_url, launch_chromium() as browser:
        page = browser.new_page()
        page.goto(f"{base_url}/roles/new", wait_until="networkidle")

        open_nav_preferences(page)
        page.locator('button[data-set-locale="zh"]').click()
        page.select_option("#role-definition-archetype-input", "gatekeeper")
        page.wait_for_function("() => document.querySelector('#role-definition-archetype-summary')?.textContent.includes('负责做放行判断')")

        assert "负责做放行判断" in (page.locator("#role-definition-archetype-summary").text_content() or "")
        assert "建议只放一个" in (page.locator("#role-definition-archetype-recommendation").text_content() or "")
        assert "不建议把它当成实现角色" in (page.locator("#role-definition-archetype-warning").text_content() or "")
        assert "# GateKeeper Prompt" in page.locator("#role-definition-prompt-markdown-input").input_value()
        assert "你是 Loopora 内部的 GateKeeper" in (page.locator("#role-definition-prompt-markdown-preview").text_content() or "")
        assert "version: 1" not in (page.locator("#role-definition-prompt-markdown-preview").text_content() or "")
        assert "archetype: gatekeeper" not in (page.locator("#role-definition-prompt-markdown-preview").text_content() or "")

        open_nav_preferences(page)
        page.locator('button[data-set-locale="en"]').click()
        page.wait_for_function("() => document.querySelector('#role-definition-archetype-summary')?.textContent.includes('Owns the pass/fail decision')")

        assert page.locator('#role-definition-archetype-input option[value="gatekeeper"]').text_content() == "GateKeeper"
        assert "Owns the pass/fail decision" in (page.locator("#role-definition-archetype-summary").text_content() or "")
        assert "Keep one of these near the end of the workflow" in (page.locator("#role-definition-archetype-recommendation").text_content() or "")
        assert "Do not use it as an implementation role" in (page.locator("#role-definition-archetype-warning").text_content() or "")
        assert "# GateKeeper Prompt" in page.locator("#role-definition-prompt-markdown-input").input_value()
        assert "You are the GateKeeper inside Loopora" in (page.locator("#role-definition-prompt-markdown-preview").text_content() or "")
        assert "version: 1" not in (page.locator("#role-definition-prompt-markdown-preview").text_content() or "")
        assert "archetype: gatekeeper" not in (page.locator("#role-definition-prompt-markdown-preview").text_content() or "")


def _role_lock_service(tmp_path: Path) -> tuple[LooporaService, dict]:
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
    return service, custom_role


def _assert_custom_role_archetype_locked(page, base_url: str, custom_role_id: str) -> None:
    page.goto(f"{base_url}/roles/{custom_role_id}/edit", wait_until="networkidle")
    expect_disabled = page.locator("#role-definition-archetype-input")
    assert expect_disabled.is_disabled() is True


def _assert_orchestration_loop_diagram_styles(page, base_url: str) -> None:
    page.goto(f"{base_url}/orchestrations", wait_until="networkidle")
    first_diagram = page.locator('[data-testid="orchestration-loop-diagram"]').first
    expect_svg = first_diagram.locator("svg")
    expect_legend = first_diagram.get_by_test_id("workflow-loop-pill")
    assert expect_svg.count() == 1
    assert expect_legend.count() >= 2
    assert first_diagram.get_by_test_id("workflow-loop-parallel-group").count() >= 1
    diagram_styles = first_diagram.evaluate(
        """(diagram) => {
          const segment = diagram.querySelector(".workflow-loop-segment");
          const node = diagram.querySelector(".workflow-loop-node circle:not(.workflow-loop-node-hit)");
          const label = diagram.querySelector(".workflow-loop-node-label");
          const badge = diagram.querySelector(".workflow-loop-center-badge rect");
          const parallelRing = diagram.querySelector(".workflow-loop-node.is-parallel .workflow-loop-node-parallel-ring");
          const svg = diagram.querySelector("svg").getBoundingClientRect();
          return {
            segmentStrokeWidth: getComputedStyle(segment).strokeWidth,
            segmentFill: getComputedStyle(segment).fill,
            segmentStroke: getComputedStyle(segment).stroke,
            nodeStrokeWidth: getComputedStyle(node).strokeWidth,
            labelFill: getComputedStyle(label).fill,
            badgeFill: getComputedStyle(badge).fill,
            parallelRingStrokeWidth: getComputedStyle(parallelRing).strokeWidth,
            svgWidth: Math.round(svg.width),
            svgHeight: Math.round(svg.height)
          };
        }"""
    )
    assert diagram_styles["segmentStrokeWidth"] == "2.6px"
    assert diagram_styles["segmentFill"] == "none"
    assert diagram_styles["segmentStroke"] != "rgb(0, 0, 0)"
    assert diagram_styles["nodeStrokeWidth"] == "3px"
    assert diagram_styles["labelFill"] != "rgb(0, 0, 0)"
    assert diagram_styles["badgeFill"] != "rgb(0, 0, 0)"
    assert diagram_styles["parallelRingStrokeWidth"] == "2px"
    assert diagram_styles["svgWidth"] >= 240
    assert 120 <= diagram_styles["svgHeight"] <= 260


def _load_repair_loop_starter(page, base_url: str) -> None:
    page.goto(f"{base_url}/orchestrations/new", wait_until="networkidle")
    assert page.get_by_test_id("workflow-step-row").count() == 0
    page.select_option("#workflow-starter-select", "repair_loop")
    page.click("#load-workflow-starter-button")
    assert page.get_by_test_id("workflow-step-row").count() == 6
    assert page.get_by_test_id("workflow-loop-parallel-group").count() >= 1


def _assert_parallel_group_editor(page) -> None:
    first_inspector_card = page.get_by_test_id("workflow-step-row").nth(1)
    first_inspector_card.locator('[data-testid="workflow-step-settings-button"]').click()
    parallel_group_input = page.locator('[data-testid="workflow-settings-step-parallel-group"]')
    assert parallel_group_input.is_disabled() is False
    assert parallel_group_input.input_value() == "repair_review"
    parallel_group_input.fill("repair_review_alt")
    page.click('button[data-close-workflow-settings="1"]')
    page.wait_for_function("() => document.querySelector('[data-testid=\"workflow-step-settings-modal\"]')?.getAttribute('aria-hidden') === 'true'")
    second_inspector_card = page.get_by_test_id("workflow-step-row").nth(2)
    second_inspector_card.locator('[data-testid="workflow-step-settings-button"]').click()
    parallel_group_input = page.locator('[data-testid="workflow-settings-step-parallel-group"]')
    assert parallel_group_input.input_value() == "repair_review"
    parallel_group_input.fill("repair_review_alt")
    page.click('button[data-close-workflow-settings="1"]')
    page.wait_for_function("() => document.querySelector('[data-testid=\"workflow-step-settings-modal\"]')?.getAttribute('aria-hidden') === 'true'")
    assert "parallel:repair_review_alt" in (first_inspector_card.text_content() or "")
    assert "parallel:repair_review_alt" in (second_inspector_card.text_content() or "")


def _assert_builder_step_settings_editor(page) -> None:
    builder_card = page.get_by_test_id("workflow-step-row").nth(4)
    builder_card.click(position={"x": 160, "y": 84})
    assert builder_card.get_attribute("data-active") == "true"
    builder_card.locator('[data-testid="workflow-step-settings-button"]').click()
    modal = page.locator('[data-testid="workflow-step-settings-modal"]')
    assert modal.get_attribute("aria-hidden") == "false"
    assert page.locator('[data-testid="workflow-settings-role-name"]').evaluate("node => node.tagName") == "STRONG"
    assert "Builder" in (page.locator('[data-testid="workflow-settings-role-name"]').text_content() or "")
    assert page.locator('[data-testid="workflow-settings-step-inherit-session"]').is_checked() is True
    page.locator('[data-testid="workflow-settings-step-model"]').fill("gpt-5.4-mini")
    page.locator('[data-testid="workflow-settings-step-extra-cli-args"]').fill("--verbose")
    page.click('button[data-close-workflow-settings="1"]')
    page.wait_for_function("() => document.querySelector('[data-testid=\"workflow-step-settings-modal\"]')?.getAttribute('aria-hidden') === 'true'")
    assert "gpt-5.4-mini" in (builder_card.text_content() or "")
    assert "--verbose" in (builder_card.text_content() or "")


def _assert_loop_pill_selects_step(page) -> None:
    guide_pill = page.get_by_test_id("workflow-loop-pill").filter(has_text="Guide").first
    guide_pill.hover()
    assert page.get_by_test_id("workflow-step-row").nth(3).get_attribute("data-role-active") == "true"
    guide_pill.click()
    assert page.get_by_test_id("workflow-step-row").nth(3).get_attribute("data-active") == "true"


def _assert_inspector_inherit_session_default(page) -> None:
    inspector_card = page.get_by_test_id("workflow-step-row").nth(1)
    inspector_card.locator('[data-testid="workflow-step-settings-button"]').click()
    assert page.locator('[data-testid="workflow-settings-step-inherit-session"]').is_checked() is False
    page.click('button[data-close-workflow-settings="1"]')
    page.wait_for_function("() => document.querySelector('[data-testid=\"workflow-step-settings-modal\"]')?.getAttribute('aria-hidden') === 'true'")


def _assert_invalid_control_limit_validation(page) -> None:
    page.locator("#workflow-controls-json-input").fill(
        json.dumps(
            [
                {
                    "id": "bad_check",
                    "when": {"signal": "no_evidence_progress", "after": "0s"},
                    "call": {"role_id": "guide"},
                    "mode": "repair_guidance",
                    "max_fires_per_run": "not-a-number",
                }
            ],
            indent=2,
        )
    )
    page.locator('input[name="name"]').click()
    page.wait_for_function("() => JSON.parse(document.querySelector('#workflow-controls-json-input').value)[0].max_fires_per_run === 'not-a-number'")

    page.locator('input[name="name"]').fill("Invalid Control Limit")
    page.locator("#workflow-controls-json-input").fill(
        json.dumps(
            [
                {
                    "id": "disabled_check",
                    "when": {"signal": "no_evidence_progress", "after": "0s"},
                    "call": {"role_id": "guide"},
                    "mode": "repair_guidance",
                    "max_fires_per_run": 0,
                }
            ],
            indent=2,
        )
    )
    page.locator('input[name="name"]').click()
    page.wait_for_function("() => JSON.parse(document.querySelector('#workflow-controls-json-input').value)[0].max_fires_per_run === 0")
    assert "0" in (page.get_by_test_id("workflow-control-row").locator(".workflow-chip").last.text_content() or "")
    page.get_by_test_id("save-orchestration-button").click()
    page.wait_for_selector("#form-error:not([hidden])")
    assert "max_fires_per_run" in (page.locator("#form-error").text_content() or "")


def _assert_new_orchestration_editor_interactions(page, base_url: str) -> None:
    _load_repair_loop_starter(page, base_url)
    _assert_parallel_group_editor(page)
    _assert_builder_step_settings_editor(page)
    _assert_loop_pill_selects_step(page)
    _assert_inspector_inherit_session_default(page)
    _assert_invalid_control_limit_validation(page)


def _assert_builtin_orchestration_step_settings_locked(page, base_url: str) -> None:
    page.goto(f"{base_url}/orchestrations/builtin:build_then_parallel_review/edit", wait_until="networkidle")
    page.locator('[data-testid="workflow-step-settings-button"]').first.click()
    assert page.locator('[data-testid="workflow-step-settings-modal"]').get_attribute("aria-hidden") == "false"
    assert page.locator('[data-testid="workflow-settings-step-id"]').is_disabled() is True


def _assert_orchestration_starter_english_labels(page, base_url: str) -> None:
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


def test_existing_role_page_locks_template_and_orchestration_page_renders_loop_diagrams(tmp_path: Path) -> None:
    service, custom_role = _role_lock_service(tmp_path)

    with serve_app(build_app(service=service)) as base_url, launch_chromium() as browser:
        page = browser.new_page()
        _assert_custom_role_archetype_locked(page, base_url, custom_role["id"])
        _assert_orchestration_loop_diagram_styles(page, base_url)
        _assert_new_orchestration_editor_interactions(page, base_url)
        _assert_builtin_orchestration_step_settings_locked(page, base_url)
        _assert_orchestration_starter_english_labels(page, base_url)
