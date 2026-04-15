from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from liminal.web import build_app


def test_index_page_renders_with_saved_loops(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    service.create_loop(
        name="Homepage Loop",
        spec_path=sample_spec_file,
        workdir=sample_workdir,
        model="gpt-5.4",
        reasoning_effort="medium",
        max_iters=3,
        max_role_retries=1,
        delta_threshold=0.005,
        trigger_window=2,
        regression_window=2,
        role_models={},
    )

    client = TestClient(build_app(service=service))
    response = client.get("/")

    assert response.status_code == 200
    assert "Homepage Loop" in response.text
    assert "<span data-lang=\"zh\">循环</span>" in response.text
    assert "别只盯着最新一次运行" not in response.text
    assert "本地优先" not in response.text
    assert "/logo/logo-with-text-horizontal.svg" in response.text
    assert "/logo/logo.svg" in response.text
    assert "/static/app.css?v=" in response.text
    assert "/static/app.js?v=" in response.text
    assert response.text.index("/loops/new") < response.text.index("/tools")
    assert "data-open-card=" in response.text
    assert "id=\"confirm-modal\"" in response.text
    assert "id=\"loops-empty-state\" hidden" in response.text
    assert "最近更新" not in response.text


def test_run_detail_places_run_files_and_console_before_timeline(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = service.create_loop(
        name="Run Detail Loop",
        spec_path=sample_spec_file,
        workdir=sample_workdir,
        model="gpt-5.4",
        reasoning_effort="medium",
        max_iters=3,
        max_role_retries=1,
        delta_threshold=0.005,
        trigger_window=2,
        regression_window=2,
        role_models={},
    )
    run = service.rerun(loop["id"])

    client = TestClient(build_app(service=service))
    response = client.get(f"/runs/{run['id']}")

    assert response.status_code == 200
    assert "Run Detail Loop" in response.text
    assert run["id"] in response.text
    assert "hero-run-detail" in response.text
    assert response.text.index("Progress") < response.text.index("Console")
    assert response.text.index("Console") < response.text.index("Run files")
    assert response.text.index("Console") < response.text.index("Timeline")
    assert "stage-explainer" not in response.text
    assert "直播中" not in response.text
    assert "实时输出" in response.text
    assert "Original spec" in response.text
    assert "progress-live-title" in response.text
    assert "progress-runtime" in response.text
    assert "stage-chip-duration" in response.text
    assert response.text.index("stage-strip") < response.text.index("progress-live-title")
    assert "timeline-count" in response.text
    assert "progress-value" not in response.text
    assert "progress-track-shell" not in response.text
    assert "最近更新" not in response.text
    assert "还没冒出第一条具体输出" in response.text
    assert "正在收集测试证据" in response.text
    assert "正在安装依赖" in response.text
    assert "正在启动本地服务" in response.text
    assert "正在准备浏览器环境" in response.text


def test_loop_detail_uses_summary_cards_for_latest_run(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = service.create_loop(
        name="Summary Loop",
        spec_path=sample_spec_file,
        workdir=sample_workdir,
        model="gpt-5.4",
        reasoning_effort="medium",
        max_iters=3,
        max_role_retries=1,
        delta_threshold=0.005,
        trigger_window=2,
        regression_window=2,
        role_models={},
    )
    service.rerun(loop["id"])

    client = TestClient(build_app(service=service))
    response = client.get(f"/loops/{loop['id']}")

    assert response.status_code == 200
    assert "Original spec" in response.text
    assert "Ship the requested behavior." in response.text
    assert "summary-grid" in response.text
    assert "summary-card-status summary-card-status-" in response.text
    assert "hero-inline-meta" in response.text
    assert "一句话摘要" in response.text
    assert "Latest verdict" in response.text


def test_run_detail_surfaces_workspace_guard_failures(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    (sample_workdir / "notes.txt").write_text("keep me\n", encoding="utf-8")
    service = service_factory(scenario="destructive_generator")
    loop = service.create_loop(
        name="Guard Failure Loop",
        spec_path=sample_spec_file,
        workdir=sample_workdir,
        model="gpt-5.4",
        reasoning_effort="medium",
        max_iters=3,
        max_role_retries=1,
        delta_threshold=0.005,
        trigger_window=2,
        regression_window=2,
        role_models={},
    )
    run = service.rerun(loop["id"])

    client = TestClient(build_app(service=service))
    response = client.get(f"/runs/{run['id']}")

    assert response.status_code == 200
    assert "工作区安全守卫触发" in response.text
    assert "workspace_guard_triggered" in response.text


def test_tools_page_renders_skill_install_cards(service_factory) -> None:
    service = service_factory(scenario="success")

    client = TestClient(build_app(service=service))
    response = client.get("/tools")

    assert response.status_code == 200
    assert "Spec skill install" in response.text
    assert "/static/pages/tools.js?v=" in response.text
    assert "data-install-skill=\"codex\"" in response.text
    assert "data-install-skill=\"claude\"" in response.text
    assert "data-install-skill=\"opencode\"" in response.text
    assert "顺手的小外挂" in response.text


def test_new_loop_page_uses_page_scoped_script(service_factory) -> None:
    service = service_factory(scenario="success")

    client = TestClient(build_app(service=service))
    response = client.get("/loops/new")

    assert response.status_code == 200
    assert "/static/pages/new_loop.js?v=" in response.text
    assert "name=\"executor_kind\"" in response.text
    assert "name=\"executor_mode\"" in response.text
    assert "id=\"command-preview\"" in response.text
    assert "id=\"reasoning-input\"" in response.text
    assert "Claude Code" in response.text
    assert "OpenCode" in response.text
    assert "把一个想法拎进来" in response.text


def test_new_loop_page_remote_mode_explains_server_side_paths(service_factory) -> None:
    service = service_factory(scenario="success")

    client = TestClient(build_app(service=service, bind_host="0.0.0.0", auth_token="secret-token"))
    response = client.get("/loops/new?token=secret-token")

    assert response.status_code == 200
    assert "当前是网络访问模式" in response.text
    assert "服务端那台机器" in response.text
    assert "id=\"browse-workdir\" disabled" in response.text
