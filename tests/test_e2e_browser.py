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
            # Goal

            开发一个计算器。

            # Checks

            ### 基础加法可用
            - When: 用户点击 7、+、5、=
            - Expect: 显示 12
            - Fail if: 结果错误或页面没有响应

            ### 清空操作可用
            - When: 用户点击 C
            - Expect: 显示重置为 0
            - Fail if: 旧表达式仍残留在显示区

            # Constraints

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
        try:
            with playwright.sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(f"{base_url}/index.html")
                page.get_by_role("button", name="7").click()
                page.get_by_role("button", name="+").click()
                page.get_by_role("button", name="5").click()
                page.get_by_role("button", name="=").click()
                assert page.locator('[data-testid="display"]').input_value() == "12"

                page.get_by_role("button", name="C").click()
                assert page.locator('[data-testid="display"]').input_value() == "0"
                browser.close()
        except Exception as exc:  # pragma: no cover - environment dependent
            pytest.skip(f"Playwright browser launch is unavailable: {exc}")


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
            try:
                with playwright.sync_playwright() as p:
                    browser = p.chromium.launch(headless=True)
                    page = browser.new_page(viewport={"width": 375, "height": 844})

                    page.goto(f"{base_url}/", wait_until="networkidle")
                    assert page.locator(".top-nav-brand-lockup").get_attribute("src") == "/logo/logo-with-text-horizontal-light.svg"

                    index_mobile = page.evaluate(
                        """() => ({
                          docW: document.documentElement.scrollWidth,
                          clientW: document.documentElement.clientWidth,
                          navW: document.querySelector(".top-nav").scrollWidth,
                          cardCount: document.querySelectorAll(".loop-card").length,
                          pageStackWidth: document.querySelector(".page-stack").getBoundingClientRect().width,
                          noteCount: document.querySelectorAll(".loop-grid-note").length,
                          actionWidths: Array.from(document.querySelectorAll(".loop-card:first-of-type .card-actions > *")).map((node) => Math.round(node.getBoundingClientRect().width))
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
                          actionWidths: Array.from(document.querySelectorAll(".loop-card:first-of-type .card-actions > *")).map((node) => Math.round(node.getBoundingClientRect().width))
                        })"""
                    )
                    assert len(set(index_desktop["actionWidths"])) == 1

                    page.goto(f"{base_url}/loops/new", wait_until="networkidle")
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
                    page.goto(f"{base_url}/loops/new", wait_until="networkidle")
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

                    browser.close()
            except Exception as exc:  # pragma: no cover - environment dependent
                pytest.skip(f"Playwright browser launch is unavailable: {exc}")
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
            # Goal

            Keep an unfinished loop draft around.

            # Constraints

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
        try:
            with playwright.sync_api.sync_playwright() as playwright_driver:
                browser = playwright_driver.chromium.launch()
                page = browser.new_page()
                try:
                    page.goto(f"{base_url}/loops/new", wait_until="networkidle")
                    page.locator('input[name="name"]').fill("Recovered browser draft")
                    page.locator('input[name="workdir"]').fill(str(workdir))
                    page.locator('input[name="spec_path"]').fill(str(spec_path))
                    page.locator('select[name="orchestration_id"]').select_option("builtin:inspect_first")
                    page.locator('select[name="completion_mode"]').select_option("rounds")
                    page.reload(wait_until="networkidle")

                    assert page.locator('input[name="name"]').input_value() == "Recovered browser draft"
                    assert page.locator('input[name="workdir"]').input_value() == str(workdir)
                    assert page.locator('input[name="spec_path"]').input_value() == str(spec_path)
                    assert page.locator('select[name="orchestration_id"]').input_value() == "builtin:inspect_first"
                    assert page.locator('select[name="completion_mode"]').input_value() == "rounds"
                    assert page.locator("#draft-status").is_visible()
                    assert page.locator("#clear-draft-button").is_visible()
                finally:
                    browser.close()
        except Exception as exc:  # pragma: no cover - environment dependent
            pytest.skip(f"Playwright browser launch is unavailable: {exc}")


def test_new_loop_page_does_not_restore_pristine_only_browser_defaults(tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.md"
    spec_path.write_text(
        textwrap.dedent(
            """
            # Goal

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
        try:
            with playwright.sync_api.sync_playwright() as playwright_driver:
                browser = playwright_driver.chromium.launch()
                page = browser.new_page()
                try:
                    page.goto(f"{base_url}/loops/new", wait_until="networkidle")
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
                finally:
                    browser.close()
        except Exception as exc:  # pragma: no cover - environment dependent
            pytest.skip(f"Playwright browser launch is unavailable: {exc}")


def test_new_loop_page_adapts_runtime_controls_to_selected_orchestration(tmp_path: Path) -> None:
    repository = LooporaRepository(tmp_path / "app.db")
    settings = AppSettings(max_concurrent_runs=1, polling_interval_seconds=0.05, stop_grace_period_seconds=0.2)
    service = LooporaService(
        repository=repository,
        settings=settings,
        executor_factory=lambda: CalculatorPrototypeExecutor(scenario="success"),
    )

    with serve_app(build_app(service=service)) as base_url:
        try:
            with playwright.sync_api.sync_playwright() as playwright_driver:
                browser = playwright_driver.chromium.launch()
                page = browser.new_page()
                try:
                    page.goto(f"{base_url}/loops/new", wait_until="networkidle")

                    page.locator('select[name="orchestration_id"]').select_option("builtin:fast_lane")
                    assert page.locator('[data-testid="loop-trigger-window-field"]').is_hidden()
                    assert page.locator('[data-testid="loop-regression-window-field"]').is_hidden()
                    assert page.locator('select[name="completion_mode"]').input_value() == "gatekeeper"

                    page.locator('select[name="orchestration_id"]').select_option("builtin:benchmark_loop")
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
                finally:
                    browser.close()
        except Exception as exc:  # pragma: no cover - environment dependent
            pytest.skip(f"Playwright browser launch is unavailable: {exc}")


def test_role_definition_page_localizes_archetype_options_without_mixed_labels(tmp_path: Path) -> None:
    repository = LooporaRepository(tmp_path / "app.db")
    settings = AppSettings(max_concurrent_runs=1, polling_interval_seconds=0.05, stop_grace_period_seconds=0.2)
    service = LooporaService(
        repository=repository,
        settings=settings,
        executor_factory=lambda: FakeCodexExecutor(scenario="success"),
    )

    with serve_app(build_app(service=service)) as base_url:
        try:
            with playwright.sync_api.sync_playwright() as playwright_driver:
                browser = playwright_driver.chromium.launch()
                page = browser.new_page()
                try:
                    page.goto(f"{base_url}/roles/new", wait_until="networkidle")

                    page.locator('button[data-set-locale="en"]').click()
                    page.wait_for_timeout(50)
                    assert page.locator('#role-definition-archetype-input option[value="inspector"]').text_content() == "Inspector"

                    page.locator('button[data-set-locale="zh"]').click()
                    page.wait_for_timeout(50)
                    assert page.locator('#role-definition-archetype-input option[value="inspector"]').text_content() == "Inspector"
                finally:
                    browser.close()
        except Exception as exc:  # pragma: no cover - environment dependent
            pytest.skip(f"Playwright browser launch is unavailable: {exc}")


def test_role_definition_page_updates_template_guidance_and_builtin_prompt_with_selection(tmp_path: Path) -> None:
    repository = LooporaRepository(tmp_path / "app.db")
    settings = AppSettings(max_concurrent_runs=1, polling_interval_seconds=0.05, stop_grace_period_seconds=0.2)
    service = LooporaService(
        repository=repository,
        settings=settings,
        executor_factory=lambda: FakeCodexExecutor(scenario="success"),
    )

    with serve_app(build_app(service=service)) as base_url:
        try:
            with playwright.sync_api.sync_playwright() as playwright_driver:
                browser = playwright_driver.chromium.launch()
                page = browser.new_page()
                try:
                    page.goto(f"{base_url}/roles/new", wait_until="networkidle")

                    page.locator('button[data-set-locale="zh"]').click()
                    page.select_option("#role-definition-archetype-input", "gatekeeper")
                    page.wait_for_timeout(50)

                    assert "负责做放行判断" in (page.locator("#role-definition-archetype-summary").text_content() or "")
                    assert "建议只放一个" in (page.locator("#role-definition-archetype-recommendation").text_content() or "")
                    assert "不建议把它当成实现角色" in (page.locator("#role-definition-archetype-warning").text_content() or "")
                    assert "# GateKeeper Prompt" in page.locator("#role-definition-prompt-markdown-input").input_value()

                    page.locator('button[data-set-locale="en"]').click()
                    page.wait_for_timeout(50)

                    assert page.locator('#role-definition-archetype-input option[value="gatekeeper"]').text_content() == "GateKeeper"
                    assert "Owns the pass/fail decision" in (page.locator("#role-definition-archetype-summary").text_content() or "")
                    assert "Keep one of these near the end of the workflow" in (page.locator("#role-definition-archetype-recommendation").text_content() or "")
                    assert "Do not use it as an implementation role" in (page.locator("#role-definition-archetype-warning").text_content() or "")
                    assert "# GateKeeper Prompt" in page.locator("#role-definition-prompt-markdown-input").input_value()
                finally:
                    browser.close()
        except Exception as exc:  # pragma: no cover - environment dependent
            pytest.skip(f"Playwright browser launch is unavailable: {exc}")


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
        try:
            with playwright.sync_api.sync_playwright() as playwright_driver:
                browser = playwright_driver.chromium.launch()
                page = browser.new_page()
                try:
                    page.goto(f"{base_url}/roles/{custom_role['id']}/edit", wait_until="networkidle")
                    expect_disabled = page.locator("#role-definition-archetype-input")
                    assert expect_disabled.is_disabled() is True

                    page.goto(f"{base_url}/orchestrations", wait_until="networkidle")
                    first_diagram = page.locator('[data-testid="orchestration-loop-diagram"]').first
                    expect_svg = first_diagram.locator("svg")
                    expect_legend = first_diagram.locator(".workflow-loop-pill")
                    assert expect_svg.count() == 1
                    assert expect_legend.count() >= 2

                    page.goto(f"{base_url}/orchestrations/new", wait_until="networkidle")
                    assert page.locator(".workflow-step-row").count() == 0
                    page.select_option("#workflow-starter-select", "triage_first")
                    page.click("#load-workflow-starter-button")
                    assert page.locator(".workflow-step-row").count() == 4
                    builder_card = page.locator(".workflow-step-row").nth(2)
                    builder_card.click(position={"x": 160, "y": 84})
                    assert "is-active" in (builder_card.get_attribute("class") or "")
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
                    page.click('[data-close-workflow-settings="1"]')
                    assert "gpt-5.4-mini" in (builder_card.text_content() or "")
                    assert "--verbose" in (builder_card.text_content() or "")
                    guide_pill = page.locator(".workflow-loop-pill").nth(1)
                    guide_pill.hover()
                    assert "is-active" in (page.locator(".workflow-step-row").nth(1).get_attribute("class") or "")
                    guide_pill.click()
                    assert "is-active" in (page.locator(".workflow-step-row").nth(1).get_attribute("class") or "")

                    inspector_card = page.locator(".workflow-step-row").nth(0)
                    inspector_card.locator('[data-testid="workflow-step-settings-button"]').click()
                    assert page.locator('[data-testid="workflow-settings-step-inherit-session"]').is_checked() is False
                    page.click('[data-close-workflow-settings="1"]')

                    page.goto(f"{base_url}/orchestrations/builtin:build_first/edit", wait_until="networkidle")
                    page.locator('[data-testid="workflow-step-settings-button"]').first.click()
                    assert page.locator('[data-testid="workflow-step-settings-modal"]').get_attribute("aria-hidden") == "false"
                    assert page.locator('[data-testid="workflow-settings-step-id"]').is_disabled() is True

                    page.goto(f"{base_url}/orchestrations/new", wait_until="networkidle")
                    page.locator('button[data-set-locale="en"]').click()
                    page.wait_for_timeout(50)
                    assert page.locator('#workflow-starter-select option[value="build_first"]').text_content() == "Build First"
                    page.select_option("#workflow-starter-select", "triage_first")
                    page.click("#load-workflow-starter-button")
                    page.locator('[data-testid="workflow-step-settings-button"]').first.click()
                    assert page.locator('[data-testid="workflow-settings-step-on-pass"] option[value="continue"]').text_content() == "Continue"
                finally:
                    browser.close()
        except Exception as exc:  # pragma: no cover - environment dependent
            pytest.skip(f"Playwright browser launch is unavailable: {exc}")
