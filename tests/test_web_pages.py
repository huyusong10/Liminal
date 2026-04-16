from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from loopora.web import build_app


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
    assert "<span data-lang=\"zh\">已创建</span>" in response.text
    assert "别只盯着最新一次运行" not in response.text
    assert "本地优先" not in response.text
    assert "/logo/logo-with-text-horizontal-light.svg" in response.text
    assert "page-stack" in response.text
    assert "loop-grid-note" in response.text
    assert "循环总览" not in response.text
    assert "/static/app.css?v=" in response.text
    assert "/static/app.js?v=" in response.text
    assert response.text.index("/loops/new") < response.text.index("/tools")
    assert response.text.index("/orchestrations") < response.text.index("/tools")
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
    assert "console-popout-link" in response.text
    assert "全屏终端" in response.text


def test_run_console_page_renders_fullscreen_console_view(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = service.create_loop(
        name="Fullscreen Console Loop",
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
    response = client.get(f"/runs/{run['id']}/console")

    assert response.status_code == 200
    assert "Fullscreen Console Loop" in response.text
    assert "console-focus-shell" in response.text
    assert "console-focus-output" in response.text
    assert "/static/pages/run_console.js?v=" in response.text


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
    assert "wake-lock-toggle" in response.text
    assert "Prevent sleep while running" in response.text
    assert "help-dot--tips" in response.text
    assert "/api/skills/loopora-spec/download" in response.text
    assert "下载 Skill 包" in response.text


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
    assert "name=\"orchestration_id\"" in response.text
    assert "name=\"role_model_builder\"" in response.text
    assert "name=\"role_model_gatekeeper\"" in response.text
    assert "Manage orchestrations" in response.text
    assert "workflow-json-input" not in response.text
    assert "Claude Code" in response.text
    assert "OpenCode" in response.text
    assert "新建一条 loop" in response.text
    assert "inline-hint-link" in response.text
    assert "Spec Skill" in response.text


def test_new_loop_page_surfaces_recent_workdirs_and_browser_draft_controls(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
    tmp_path: Path,
    monkeypatch,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    second_workdir = tmp_path / "second-workdir"
    second_workdir.mkdir()
    service = service_factory(scenario="success")
    service.create_loop(
        name="Recent Loop A",
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
    service.create_loop(
        name="Recent Loop B",
        spec_path=sample_spec_file,
        workdir=second_workdir,
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
    response = client.get("/loops/new")

    assert response.status_code == 200
    assert 'data-restore-draft="true"' in response.text
    assert 'id="draft-status"' in response.text
    assert 'id="clear-draft-button"' in response.text
    assert 'id="pristine-loop-form-json"' in response.text
    assert 'list="recent-workdir-options"' in response.text
    assert f'data-fill-workdir="{sample_workdir}"' in response.text
    assert f'data-fill-workdir="{second_workdir}"' in response.text
    assert "Recent workdirs" in response.text


def test_new_loop_page_keeps_draft_restore_enabled_for_default_equivalent_query_values(service_factory) -> None:
    service = service_factory(scenario="success")

    client = TestClient(build_app(service=service))
    response = client.get(
        "/loops/new"
        "?orchestration_id=builtin:build_first"
        "&executor_kind=codex"
        "&executor_mode=preset"
        "&command_cli=codex"
        "&model=gpt-5.4"
        "&reasoning_effort=medium"
        "&max_iters=8"
        "&max_role_retries=2"
        "&delta_threshold=0.005"
        "&trigger_window=4"
        "&regression_window=2"
        "&start_immediately=1"
    )

    assert response.status_code == 200
    assert 'data-restore-draft="true"' in response.text


def test_new_loop_page_disables_draft_restore_for_non_default_query_values(service_factory) -> None:
    service = service_factory(scenario="success")

    client = TestClient(build_app(service=service))
    response = client.get("/loops/new?workdir=/tmp/demo")

    assert response.status_code == 200
    assert 'data-restore-draft="false"' in response.text


def test_deleting_loop_refreshes_recent_workdir_suggestions(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
    tmp_path: Path,
) -> None:
    service = service_factory(scenario="success")
    second_workdir = tmp_path / "second-workdir"
    second_workdir.mkdir()

    deleted_loop = service.create_loop(
        name="Delete Me",
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
    service.create_loop(
        name="Keep Me",
        spec_path=sample_spec_file,
        workdir=second_workdir,
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

    before_delete = client.get("/loops/new")
    assert before_delete.status_code == 200
    assert f'data-fill-workdir="{sample_workdir}"' in before_delete.text
    assert f'data-fill-workdir="{second_workdir}"' in before_delete.text

    delete_response = client.delete(f"/api/loops/{deleted_loop['id']}")
    assert delete_response.status_code == 200

    after_delete = client.get("/loops/new")
    assert after_delete.status_code == 200
    assert f'data-fill-workdir="{sample_workdir}"' not in after_delete.text
    assert f'data-fill-workdir="{second_workdir}"' in after_delete.text


def test_orchestrations_pages_render_as_top_level_feature(service_factory) -> None:
    service = service_factory(scenario="success")

    client = TestClient(build_app(service=service))
    list_response = client.get("/orchestrations")
    assert list_response.status_code == 200
    assert "流程编排" in list_response.text
    assert "Build First" in list_response.text
    assert "Create orchestration" in list_response.text
    assert 'data-open-card="/orchestrations/builtin:build_first/edit"' in list_response.text
    assert "Create loop" not in list_response.text

    new_response = client.get("/orchestrations/new")
    assert new_response.status_code == 200
    assert "/static/pages/new_orchestration.js?v=" in new_response.text
    assert "name=\"workflow_preset\"" in new_response.text
    assert "id=\"workflow-json-input\"" in new_response.text
    assert "id=\"prompt-files-json-input\"" in new_response.text
    assert "把这个想法交给它持续推进" not in new_response.text

    builtin_edit_response = client.get("/orchestrations/builtin:build_first/edit")
    assert builtin_edit_response.status_code == 200
    assert "保存为新编排" in builtin_edit_response.text
    assert "先构建，再验收 / Build First" in builtin_edit_response.text

    orchestration = service.create_orchestration(name="Custom", workflow={"preset": "inspect_first"})
    custom_edit_response = client.get(f"/orchestrations/{orchestration['id']}/edit")
    assert custom_edit_response.status_code == 200
    assert f'action="/orchestrations/{orchestration["id"]}/edit"' in custom_edit_response.text
    assert "保存修改" in custom_edit_response.text


def test_new_loop_page_remote_mode_explains_server_side_paths(service_factory) -> None:
    service = service_factory(scenario="success")

    client = TestClient(build_app(service=service, bind_host="0.0.0.0", auth_token="secret-token"))
    response = client.get("/loops/new?token=secret-token")

    assert response.status_code == 200
    assert "当前是网络访问模式" in response.text
    assert "服务端那台机器" in response.text
    assert "id=\"browse-workdir\" disabled" in response.text


def test_static_css_keeps_preview_timeline_and_mobile_nav_regressions_covered(service_factory) -> None:
    service = service_factory(scenario="success")

    client = TestClient(build_app(service=service))
    response = client.get("/static/app.css")

    assert response.status_code == 200
    css = response.text
    assert ".preview-box {" in css
    assert "white-space: pre-wrap;" in css
    assert ".timeline-event {" in css
    assert ".timeline-empty {" in css
    assert ".summary-card-head {" in css
    assert ".console-focus-panel {" in css
    assert ".top-nav-brand-lockup {" in css
    assert ".page-stack {" in css
    assert ".card-actions--loop {" in css
    assert ".help-dot--tips {" in css
    assert ".inline-hint-link {" in css
    assert ".skill-download-card {" in css
    assert ".workflow-toolbar {" in css
    assert ".workflow-editor-section {" in css
    assert ".workflow-empty-state {" in css
    assert re.search(r"@media \(max-width: 640px\)\s*{[\s\S]*?\.top-nav\s*{[\s\S]*?flex-wrap:\s*wrap;", css)
    assert re.search(r"@media \(max-width: 640px\)\s*{[\s\S]*?\.top-nav-links\s*{[\s\S]*?overflow-x:\s*auto;", css)
    assert re.search(r"@media \(max-width: 640px\)\s*{[\s\S]*?\.card-actions--loop,\s*\.card-actions--loop-compact\s*{[\s\S]*?grid-template-columns:\s*repeat\(2, minmax\(0, 1fr\)\);", css)
    assert re.search(r"@media \(max-width: 1120px\)\s*{[\s\S]*?\.form-grid,[\s\S]*?\.executor-config-grid,[\s\S]*?grid-template-columns:\s*1fr;", css)
