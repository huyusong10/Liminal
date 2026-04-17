from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from loopora.web import build_app


def _assert_has_testid(html: str, testid: str) -> None:
    assert f'data-testid="{testid}"' in html


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
    assert "/logo/logo-with-text-horizontal-light.svg" in response.text
    assert "page-stack" in response.text
    assert "loop-grid-note" in response.text
    assert 'data-theme="light"' in response.text
    assert "loopora:theme" in response.text
    assert "loopora:locale" in response.text
    assert response.text.index("loopora:theme") < response.text.index("/static/app.css?v=")
    assert response.text.index("loopora:locale") < response.text.index("/static/app.css?v=")
    assert "/static/app.css?v=" in response.text
    assert "/static/app.js?v=" in response.text
    _assert_has_testid(response.text, "top-nav")
    _assert_has_testid(response.text, "nav-created-link")
    _assert_has_testid(response.text, "nav-create-loop-link")
    _assert_has_testid(response.text, "nav-orchestrations-link")
    _assert_has_testid(response.text, "nav-role-definitions-link")
    _assert_has_testid(response.text, "nav-tools-link")
    _assert_has_testid(response.text, "nav-preferences")
    _assert_has_testid(response.text, "nav-preferences-toggle")
    _assert_has_testid(response.text, "nav-preferences-panel")
    _assert_has_testid(response.text, "theme-switch")
    _assert_has_testid(response.text, "theme-light-button")
    _assert_has_testid(response.text, "theme-dark-button")
    _assert_has_testid(response.text, "locale-switch")
    assert "data-open-card=" in response.text
    assert "id=\"confirm-modal\"" in response.text
    assert "id=\"loops-empty-state\" hidden" in response.text


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
    assert "console-filters" in response.text
    assert "console-expand-all" in response.text
    assert "console-collapse-all" in response.text


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
    assert "console-focus-filters" in response.text
    assert "console-focus-expand-all" in response.text
    assert "console-focus-collapse-all" in response.text
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
    _assert_has_testid(response.text, "loop-create-page")
    _assert_has_testid(response.text, "loop-create-form")
    _assert_has_testid(response.text, "nav-orchestrations-link")
    _assert_has_testid(response.text, "nav-role-definitions-link")
    _assert_has_testid(response.text, "workdir-browse-button")
    _assert_has_testid(response.text, "spec-template-button")
    _assert_has_testid(response.text, "loop-orchestration-input")
    _assert_has_testid(response.text, "loop-completion-mode-input")
    _assert_has_testid(response.text, "loop-iteration-interval-input")
    assert "name=\"executor_kind\"" not in response.text
    assert "name=\"executor_mode\"" not in response.text
    assert "name=\"orchestration_id\"" in response.text
    assert "name=\"completion_mode\"" in response.text
    assert "name=\"iteration_interval_seconds\"" in response.text
    assert "Role runtime reminder" in response.text
    assert "workflow-json-input" not in response.text
    assert "角色定义" in response.text
    _assert_has_testid(response.text, "nav-tutorial-link")


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
    _assert_has_testid(list_response.text, "orchestrations-page")
    _assert_has_testid(list_response.text, "orchestrations-intro-copy")
    _assert_has_testid(list_response.text, "nav-orchestrations-link")
    assert "Orchestrations" in list_response.text
    assert 'data-open-card="/orchestrations/builtin:build_first/edit"' in list_response.text
    assert "Create loop" not in list_response.text
    _assert_has_testid(list_response.text, "orchestration-loop-diagram")
    assert "/static/pages/workflow_diagram.js?v=" in list_response.text
    assert "/static/pages/orchestrations.js?v=" in list_response.text

    new_response = client.get("/orchestrations/new")
    assert new_response.status_code == 200
    assert "/static/pages/new_orchestration.js?v=" in new_response.text
    assert "/static/pages/workflow_diagram.js?v=" in new_response.text
    _assert_has_testid(new_response.text, "orchestration-editor-page")
    _assert_has_testid(new_response.text, "orchestration-editor-form")
    _assert_has_testid(new_response.text, "workflow-preset-input")
    _assert_has_testid(new_response.text, "workflow-json-input")
    _assert_has_testid(new_response.text, "prompt-files-json-input")
    _assert_has_testid(new_response.text, "role-definition-select")
    _assert_has_testid(new_response.text, "add-role-from-definition-button")
    _assert_has_testid(new_response.text, "workflow-roles-list")
    _assert_has_testid(new_response.text, "workflow-steps-list")
    _assert_has_testid(new_response.text, "workflow-loop-preview-panel")
    _assert_has_testid(new_response.text, "workflow-loop-preview")
    _assert_has_testid(new_response.text, "save-orchestration-button")
    assert "role-definitions-json" in new_response.text

    builtin_edit_response = client.get("/orchestrations/builtin:build_first/edit")
    assert builtin_edit_response.status_code == 200
    assert "默认编排是固定的" in builtin_edit_response.text
    _assert_has_testid(builtin_edit_response.text, "orchestration-editor-form")
    assert 'data-readonly="true"' in builtin_edit_response.text
    assert 'name="name" value="Build First" required readonly' in builtin_edit_response.text
    assert 'id="workflow-preset-input" name="workflow_preset" data-testid="workflow-preset-input" disabled' in builtin_edit_response.text
    assert 'id="save-orchestration-button"' not in builtin_edit_response.text
    assert '/orchestrations/new?workflow_preset=build_first' in builtin_edit_response.text

    orchestration = service.create_orchestration(name="Custom", workflow={"preset": "inspect_first"})
    custom_edit_response = client.get(f"/orchestrations/{orchestration['id']}/edit")
    assert custom_edit_response.status_code == 200
    _assert_has_testid(custom_edit_response.text, "orchestration-editor-form")
    assert f'action="/orchestrations/{orchestration["id"]}/edit"' in custom_edit_response.text
    assert 'data-readonly="false"' in custom_edit_response.text


def test_role_definitions_pages_render_as_top_level_feature(service_factory) -> None:
    service = service_factory(scenario="success")
    service.create_role_definition(
        name="Release Builder",
        description="Ship focused release changes.",
        archetype="builder",
        prompt_ref="release-builder.md",
        prompt_markdown="""---
version: 1
archetype: builder
---

Focus on scoped release work.
""",
        executor_kind="claude",
        model="gpt-5.4-mini",
        reasoning_effort="high",
    )

    client = TestClient(build_app(service=service))
    list_response = client.get("/roles")
    assert list_response.status_code == 200
    _assert_has_testid(list_response.text, "role-definitions-page")
    _assert_has_testid(list_response.text, "role-definitions-intro-copy")
    _assert_has_testid(list_response.text, "create-role-definition-link")
    _assert_has_testid(list_response.text, "role-definitions-list")
    _assert_has_testid(list_response.text, "builtin-role-templates-list")
    assert "Role Definitions" in list_response.text
    assert "Release Builder" in list_response.text
    assert "/roles/new" in list_response.text
    assert 'data-role-definition-id="' in list_response.text
    assert "Saved custom roles" in list_response.text
    assert "Built-in role templates" in list_response.text
    assert "Built-in template" in list_response.text
    assert "Built-in template · builder" not in list_response.text
    assert 'class="loop-grid role-card-grid"' in list_response.text

    new_response = client.get("/roles/new")
    assert new_response.status_code == 200
    _assert_has_testid(new_response.text, "role-definition-editor-page")
    _assert_has_testid(new_response.text, "role-definition-editor-form")
    _assert_has_testid(new_response.text, "role-definition-executor-kind-input")
    _assert_has_testid(new_response.text, "role-definition-executor-mode-input")
    _assert_has_testid(new_response.text, "role-definition-executor-mode-switch")
    _assert_has_testid(new_response.text, "role-definition-mode-preset-button")
    _assert_has_testid(new_response.text, "role-definition-mode-command-button")
    _assert_has_testid(new_response.text, "role-definition-model-input")
    _assert_has_testid(new_response.text, "role-definition-reasoning-input")
    _assert_has_testid(new_response.text, "role-definition-command-cli-input")
    _assert_has_testid(new_response.text, "role-definition-command-args-input")
    _assert_has_testid(new_response.text, "role-definition-command-preview")
    _assert_has_testid(new_response.text, "role-definition-prompt-markdown-input")
    _assert_has_testid(new_response.text, "role-definition-archetype-guide")
    _assert_has_testid(new_response.text, "save-role-definition-button")
    assert "Final command preview" in new_response.text
    assert "Custom Command" in new_response.text
    assert "Prompt file name" not in new_response.text
    assert "巡检者 / Inspector" not in new_response.text
    assert "Pushes the implementation forward" in new_response.text
    assert "Use it where the workflow needs actual workspace edits" in new_response.text

    zh_response = client.get("/roles/new", headers={"accept-language": "zh-CN,zh;q=0.9"})
    assert zh_response.status_code == 200
    assert "直接推进实现" in zh_response.text
    assert "你是 Loopora 内部的建造者" in zh_response.text

    builtin_edit_response = client.get("/roles/builtin:builder/edit")
    assert builtin_edit_response.status_code == 200
    _assert_has_testid(builtin_edit_response.text, "role-definition-editor-form")
    assert "保存为新角色" in builtin_edit_response.text
    assert 'id="role-definition-archetype-input" disabled' in builtin_edit_response.text
    custom_role = next(item for item in service.list_role_definitions() if item["source"] == "custom")
    custom_edit_response = client.get(f"/roles/{custom_role['id']}/edit")
    assert custom_edit_response.status_code == 200
    assert 'id="role-definition-archetype-input" disabled' in custom_edit_response.text
    assert "Save changes" in custom_edit_response.text


def test_tutorial_page_is_available_from_top_level_navigation(service_factory) -> None:
    service = service_factory(scenario="success")

    client = TestClient(build_app(service=service))
    response = client.get("/tutorial")

    assert response.status_code == 200
    _assert_has_testid(response.text, "tutorial-page")
    _assert_has_testid(response.text, "nav-tutorial-link")
    _assert_has_testid(response.text, "tutorial-context-flow-panel")
    assert "角色定义" in response.text
    assert "流程编排" in response.text
    assert "创建循环" in response.text
    assert "上下文如何在流程里流转" in response.text
    assert "How context moves through a workflow" in response.text
    assert "contract/run_contract.json" in response.text
    assert "iterations/iter_000/steps/00__builder/input.context.json" in response.text
    assert "context/latest_iteration_summary.json" in response.text


def test_new_loop_page_remote_mode_explains_server_side_paths(service_factory) -> None:
    service = service_factory(scenario="success")

    client = TestClient(build_app(service=service, bind_host="0.0.0.0", auth_token="secret-token"))
    response = client.get("/loops/new?token=secret-token")

    assert response.status_code == 200
    _assert_has_testid(response.text, "remote-path-callout")
    assert 'id="browse-workdir"' in response.text
    assert 'aria-disabled="true"' in response.text


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
    assert ".workflow-loop-map {" in css
    assert ".workflow-loop-segment {" in css
    assert ".tutorial-context-grid {" in css
    assert ".tutorial-context-detail-grid {" in css
    assert ".nav-preferences-panel {" in css
    assert ".nav-preferences-toggle {" in css
    assert ".role-card-grid {" in css
    assert ".top-nav .nav-preferences-toggle {" in css
    assert "@keyframes pageRiseIn {" in css
    assert "@keyframes loopTraceIn {" in css
    assert ".workflow-toolbar {" in css
    assert ".workflow-editor-section {" in css
    assert ".workflow-empty-state {" in css
    assert "body:not(.ui-mounted)" not in css
    assert "body.ui-mounted .hero" not in css
    assert re.search(r"\.top-nav-link:hover\s*{\s*color:\s*var\(--nav-ink\);\s*transform:\s*translateY\(-1px\);\s*}", css)
    assert re.search(r"\.top-nav-link.active\s*{\s*color:\s*var\(--nav-ink\);\s*}", css)
    assert re.search(r"\.top-nav \.nav-preferences-toggle\s*{\s*[\s\S]*?color:\s*var\(--nav-ink\);", css)
    assert re.search(r"@media \(max-width: 1360px\)\s*{[\s\S]*?\.top-nav\s*{[\s\S]*?flex-wrap:\s*wrap;", css)
    assert re.search(r"@media \(max-width: 1360px\)\s*{[\s\S]*?\.top-nav-links\s*{[\s\S]*?display:\s*grid;[\s\S]*?grid-template-columns:\s*repeat\(3, minmax\(0, 1fr\)\);", css)
    assert re.search(r"@media \(max-width: 860px\)\s*{[\s\S]*?\.top-nav-links\s*{[\s\S]*?grid-template-columns:\s*repeat\(2, minmax\(0, 1fr\)\);", css)
    assert re.search(r"@media \(max-width: 640px\)\s*{[\s\S]*?\.card-actions--loop,\s*\.card-actions--loop-compact\s*{[\s\S]*?grid-template-columns:\s*repeat\(2, minmax\(0, 1fr\)\);", css)
    assert re.search(r"@media \(max-width: 1120px\)\s*{[\s\S]*?\.form-grid,[\s\S]*?\.executor-config-grid,[\s\S]*?grid-template-columns:\s*1fr;", css)


def test_static_app_js_bootstraps_theme_and_locale_without_mount_flash(service_factory) -> None:
    service = service_factory(scenario="success")

    client = TestClient(build_app(service=service))
    response = client.get("/static/app.js")

    assert response.status_code == 200
    script = response.text
    assert "function readSavedTheme()" in script
    assert "setTheme(currentTheme(), {persist: false});" in script
    assert "setLocale(currentLocale(), {persist: false});" in script
    assert "function bindNavPreferences()" in script
    assert "data-toggle-nav-preferences" in script
    assert "ui-mounted" not in script
