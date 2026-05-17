from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from loopora.web import build_app


def test_run_detail_page_css_owns_progress_surface_rules() -> None:
    root = Path(__file__).resolve().parents[3]
    app_css = (root / "src" / "loopora" / "static" / "app.css").read_text(encoding="utf-8")
    run_detail_css = (root / "src" / "loopora" / "static" / "pages" / "run_detail.css").read_text(encoding="utf-8")

    for selector in [".progress-live-card", ".stage-loop-shell", ".stage-chip", ".highlight-grid"]:
        assert selector not in app_css
        assert selector in run_detail_css


def test_run_detail_progress_caption_uses_product_language() -> None:
    root = Path(__file__).resolve().parents[3]
    source = (root / "src" / "loopora" / "static" / "pages" / "run_detail_render.js").read_text(encoding="utf-8")

    assert "No fake percentage here anymore" not in source
    assert "虚假的百分比" not in source
    assert "guessed completion percentage" in source
    assert "stage timing" in source


def test_run_detail_progress_uses_run_flow_language() -> None:
    root = Path(__file__).resolve().parents[3]
    source = (root / "src" / "loopora" / "static" / "pages" / "run_detail_progress.js").read_text(
        encoding="utf-8"
    )

    assert "placed in the workflow" not in source
    assert "placed in the run flow" in source


def test_run_detail_agent_handoff_exposes_copyable_unclipped_values() -> None:
    root = Path(__file__).resolve().parents[3]
    template = (root / "src" / "loopora" / "templates" / "run_detail.html").read_text(encoding="utf-8")
    css = (root / "src" / "loopora" / "static" / "pages" / "run_detail.css").read_text(encoding="utf-8")
    renderer = (root / "src" / "loopora" / "static" / "pages" / "run_detail_render.js").read_text(encoding="utf-8")
    page_script = (root / "src" / "loopora" / "static" / "pages" / "run_detail.js").read_text(encoding="utf-8")

    for kind in ("target", "context", "capsule", "template", "outbox", "submit"):
        assert f'data-agent-handoff-copy="{kind}"' in template
        assert f'data-testid="agent-handoff-copy-{kind}"' in template
    assert "agent-handoff-outbox" in renderer
    assert "result_outbox_absolute_dir" in renderer
    assert 'data-testid="agent-handoff-contract"' in template
    for field_id in ("agent-handoff-result-contract", "agent-handoff-known-evidence", "agent-handoff-fill-rule"):
        assert field_id in template
        assert field_id in renderer
    assert "result_file_contract" in renderer
    assert "known_evidence_count" in renderer
    assert "replace null placeholders" in renderer
    assert 'data-testid="agent-handoff-continuation"' in template
    assert "renderAgentContinuation(step.continuation)" in renderer
    assert "agent-handoff-continuation-focus" in renderer
    assert "button.dataset.copyValue = copyValue" in renderer
    assert "navigator.clipboard.writeText(value)" in page_script
    assert re.search(r"\.agent-handoff-item code\s*{[\s\S]*?white-space:\s*pre-wrap;", css)
    assert re.search(r"\.agent-handoff-item code\s*{[\s\S]*?overflow-wrap:\s*anywhere;", css)
    assert re.search(r"\.agent-handoff-continuation-focus li\s*{[\s\S]*?overflow-wrap:\s*anywhere;", css)
    assert not re.search(r"\.agent-handoff-item code\s*{[\s\S]*?text-overflow:\s*ellipsis;", css)


def test_run_detail_console_projector_maps_core_events_without_dom() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required for static JS module checks")
    root = Path(__file__).resolve().parents[3]
    script = r"""
const fs = require("fs");
const vm = require("vm");
const source = fs.readFileSync("src/loopora/static/pages/run_detail_console.js", "utf8");
const context = {
  window: {LooporaUI: {translateStatus: (status) => `status:${status}`}},
};
vm.createContext(context);
vm.runInContext(source, context);
const projector = context.window.LooporaRunDetailConsole.createConsoleEventProjector({
  buildConsoleEntry: (event, options) => ({eventType: event.event_type, ...options}),
  localeText: (_zh, en) => en,
  prettyConsoleJson: (value) => JSON.stringify(value, null, 2),
  resolvedPayloadRoleName: () => "Builder",
  buildContextDetail: (payload) => `step=${payload.step_id || "-"}`,
  displayIter: (value) => Number(value) + 1,
  formatDurationMs: (value) => `${value}ms`,
  translateStatus: (status) => `status:${status}`,
});
const commandLines = projector.buildConsoleLines({
  event_type: "codex_event",
  created_at: "2026-04-30T00:00:00Z",
  role: "builder",
  payload: {type: "command", message: "uv run pytest -q"},
});
if (commandLines.length !== 1 || commandLines[0].channel !== "command" || !commandLines[0].text.includes("uv run pytest")) {
  throw new Error(`command projection failed: ${JSON.stringify(commandLines)}`);
}
const fileLines = projector.buildConsoleLines({
  event_type: "codex_event",
  created_at: "2026-04-30T00:00:00Z",
  role: "builder",
  payload: {type: "item.completed", item: {type: "file_change", changes: [{path: "src/app.py"}]}},
});
if (fileLines.length !== 1 || fileLines[0].channel !== "file" || !fileLines[0].summary.includes("app.py")) {
  throw new Error(`file projection failed: ${JSON.stringify(fileLines)}`);
}
const runFinishedLines = projector.buildConsoleLines({
  event_type: "run_finished",
  created_at: "2026-04-30T00:00:00Z",
  payload: {status: "succeeded", task_verdict_status: "insufficient_evidence", task_verdict_summary: "Required coverage still lacks direct evidence."},
});
if (
  runFinishedLines.length !== 1 ||
  runFinishedLines[0].tone !== "warning" ||
  !runFinishedLines[0].summary.includes("Task verdict insufficient_evidence") ||
  !runFinishedLines[0].summary.includes("Verdict summary Required coverage still lacks direct evidence.")
) {
  throw new Error(`run finished console projection failed: ${JSON.stringify(runFinishedLines)}`);
}
const unevaluatedRunFinishedLines = projector.buildConsoleLines({
  event_type: "run_finished",
  created_at: "2026-04-30T00:00:00Z",
  payload: {status: "succeeded"},
});
if (
  unevaluatedRunFinishedLines.length !== 1 ||
  unevaluatedRunFinishedLines[0].tone !== "warning" ||
  !unevaluatedRunFinishedLines[0].summary.includes("Task verdict not_evaluated")
) {
  throw new Error(`run finished console projection promoted missing verdict: ${JSON.stringify(unevaluatedRunFinishedLines)}`);
}
const acceptedInsufficientLines = projector.buildConsoleLines({
  event_type: "run_result_accepted",
  created_at: "2026-04-30T00:00:01Z",
  payload: {status: "succeeded", task_verdict_status: "insufficient_evidence"},
});
if (
  acceptedInsufficientLines.length !== 1 ||
  acceptedInsufficientLines[0].tone !== "warning" ||
  !acceptedInsufficientLines[0].summary.includes("Unproven evidence verdict recorded") ||
  acceptedInsufficientLines[0].summary.includes("accepted")
) {
  throw new Error(`accepted evidence console projection masked insufficient evidence: ${JSON.stringify(acceptedInsufficientLines)}`);
}
const acceptedUnevaluatedLines = projector.buildConsoleLines({
  event_type: "run_result_accepted",
  created_at: "2026-04-30T00:00:02Z",
  payload: {status: "succeeded", task_verdict_status: "not_evaluated"},
});
if (
  acceptedUnevaluatedLines.length !== 1 ||
  acceptedUnevaluatedLines[0].tone !== "warning" ||
  !acceptedUnevaluatedLines[0].summary.includes("Unevaluated evidence verdict recorded") ||
  acceptedUnevaluatedLines[0].summary.includes("Evidence verdict recorded")
) {
  throw new Error(`accepted evidence console projection masked unevaluated verdict: ${JSON.stringify(acceptedUnevaluatedLines)}`);
}
const zhProjector = context.window.LooporaRunDetailConsole.createConsoleEventProjector({
  buildConsoleEntry: (event, options) => ({eventType: event.event_type, ...options}),
  localeText: (zh, _en) => zh,
  prettyConsoleJson: (value) => JSON.stringify(value, null, 2),
  resolvedPayloadRoleName: () => "Builder",
  buildContextDetail: (payload) => `step=${payload.step_id || "-"}`,
  displayIter: (value) => Number(value) + 1,
  formatDurationMs: (value) => `${value}ms`,
  translateStatus: (status) => `status:${status}`,
});
const zhRunFinishedLines = zhProjector.buildConsoleLines({
  event_type: "run_finished",
  created_at: "2026-04-30T00:00:00Z",
  payload: {status: "succeeded", task_verdict_status: "insufficient_evidence", task_verdict_summary: "证据仍缺少审计路径。"},
});
if (
  zhRunFinishedLines.length !== 1 ||
  !zhRunFinishedLines[0].summary.includes("Loop 裁决 insufficient_evidence") ||
  !zhRunFinishedLines[0].summary.includes("裁决摘要 证据仍缺少审计路径。") ||
  zhRunFinishedLines[0].summary.includes("任务裁决")
) {
  throw new Error(`Chinese run finished console projection used the wrong verdict term: ${JSON.stringify(zhRunFinishedLines)}`);
}
const stringOkLines = projector.buildConsoleLines({
  event_type: "role_execution_summary",
  created_at: "2026-04-30T00:00:00Z",
  role: "builder",
  payload: {ok: "false", attempts: 1, error: "failed as string"},
});
if (
  stringOkLines.length !== 1 ||
  stringOkLines[0].tone !== "error" ||
  stringOkLines[0].channel !== "error" ||
  !stringOkLines[0].summary.includes("failed as string")
) {
  throw new Error(`string ok console projection failed closed incorrectly: ${JSON.stringify(stringOkLines)}`);
}
const malformedSuccessLines = projector.buildConsoleLines({
  event_type: "role_execution_summary",
  created_at: "2026-04-30T00:00:00Z",
  role: "builder",
  payload: {ok: true, attempts: "3", duration_ms: "42"},
});
if (
  malformedSuccessLines.length !== 1 ||
  malformedSuccessLines[0].summary.includes("attempts=3") ||
  malformedSuccessLines[0].summary.includes("42ms")
) {
  throw new Error(`console promoted malformed numeric role summary fields: ${JSON.stringify(malformedSuccessLines)}`);
}
const stringPassedIterationLines = projector.buildConsoleLines({
  event_type: "iteration_summary_written",
  created_at: "2026-04-30T00:00:00Z",
  payload: {passed: "true", composite_score: 1},
});
if (stringPassedIterationLines.length !== 1 || stringPassedIterationLines[0].tone !== "system") {
  throw new Error(`string passed iteration projection did not fail closed: ${JSON.stringify(stringPassedIterationLines)}`);
}
"""
    subprocess.run([node, "-e", script], cwd=root, check=True)


def test_run_console_uses_loop_verdict_term_for_zh_terminal_summary() -> None:
    root = Path(__file__).resolve().parents[3]

    for path in [
        root / "src" / "loopora" / "static" / "pages" / "run_detail_console.js",
        root / "src" / "loopora" / "static" / "pages" / "run_console.js",
        root / "src" / "loopora" / "static" / "pages" / "run_detail_timeline.js",
    ]:
        source = path.read_text(encoding="utf-8")
        assert "Loop 裁决" in source
        assert "任务裁决" not in source

    for path in [
        root / "src" / "loopora" / "static" / "pages" / "run_detail_console.js",
        root / "src" / "loopora" / "static" / "pages" / "run_console.js",
    ]:
        source = path.read_text(encoding="utf-8")
        assert "recordedVerdictSummary(payload)" in source
        assert "Unproven evidence verdict recorded" in source
        assert "Unevaluated evidence verdict recorded" in source
        assert 'payload.task_verdict_status || "not_evaluated"' in source
        assert "run_result_accepted" in source
        assert "tone: runFinishedTone(payload)" in source

    observation_source = (
        root / "src" / "loopora" / "static" / "pages" / "run_detail_observation.js"
    ).read_text(encoding="utf-8")
    assert 'payload.task_verdict_status || currentTaskVerdictStatus || "not_evaluated"' in observation_source


def test_tools_local_asset_diagnostics_use_default_plan_file_language() -> None:
    root = Path(__file__).resolve().parents[3]
    tools_template = (root / "src" / "loopora" / "templates" / "tools.html").read_text(encoding="utf-8")
    tools_script = (root / "src" / "loopora" / "static" / "pages" / "tools.js").read_text(encoding="utf-8")
    default_surface = f"{tools_template}\n{tools_script}"

    assert "Alignment orphan dirs" not in default_surface
    assert "Alignment orphan directories" not in default_surface
    assert 'localeText("Session", "Session")' not in default_surface
    assert "Bundle orphan dirs" not in default_surface
    assert "Bundle orphan directories" not in default_surface
    assert 'localeText("方案包", "Bundle")' not in default_surface
    assert "Conversation orphan dirs" in default_surface
    assert "Conversation orphan directories" in default_surface
    assert 'localeText("对话", "Conversation")' in default_surface
    assert "Plan file orphan dirs" in default_surface
    assert "Plan file orphan directories" in default_surface
    assert 'localeText("方案包", "Plan file")' in default_surface
    assert 'data-testid="local-assets-toggle"' in default_surface
    assert "Review maintenance details" in default_surface
    assert "Hide maintenance details" in default_surface
    assert "main workflow" not in default_surface
    assert "Start from the Coding Agent you already use" in default_surface
    assert "wake lock and local asset health sit below" in default_surface
    assert "Agent working project directory" in default_surface
    assert "Path to the project where the Agent will work" in default_surface
    assert "leave blank only when the server was started from that target project" in default_surface
    assert 'data-testid="agent-adapter-handoff"' in default_surface
    assert 'data-testid="agent-adapter-judgment-brief"' in default_surface
    assert "Give /loopora-gen the task judgment, not just a task title." in default_surface
    assert "task goal, fake-done risk, and required evidence" in default_surface
    assert "Review READY Loop preview" in default_surface
    assert "same Agent session" in default_surface
    assert "Entry files:" in default_surface
    assert 'data-copy-value="/loopora-gen"' in default_surface
    assert 'data-copy-value="/loopora-loop"' in default_surface
    assert "Blank uses the server current directory; refresh to show the effective target" not in default_surface


def test_manual_import_surface_uses_plan_file_language() -> None:
    root = Path(__file__).resolve().parents[3]
    new_loop_template = (root / "src" / "loopora" / "templates" / "new_loop.html").read_text(encoding="utf-8")
    import_script = (root / "src" / "loopora" / "static" / "pages" / "bundle_import.js").read_text(encoding="utf-8")
    import_surface = f"{new_loop_template}\n{import_script}"

    for forbidden in [
        "Import Existing Bundle / YAML",
        "bundle file or YAML",
        "Bundle path",
        "Replace bundle id",
        "Bundle YAML",
        "Provide a bundle path",
        "Bundle preview failed",
        "/absolute/path/to/bundle.yml",
        "Recorded by the workflow runtime.",
        'localeText("流程判断", "Workflow")',
        'localeText("流程", "workflow")',
    ]:
        assert forbidden not in import_surface
    assert "Import existing plan file" in import_surface
    assert "Plan file path" in import_surface
    assert "Replace plan id" in import_surface
    assert "Plan file content" in import_surface
    assert "Provide a plan file path or paste plan file content." in import_surface
    assert "Plan file preview failed." in import_surface
    assert "/absolute/path/to/plan.yml" in import_surface
    assert "Recorded during the run flow." in import_surface
    assert 'localeText("运行流程", "Run flow")' in import_surface


def test_manual_loop_surface_uses_flow_language_for_default_copy() -> None:
    root = Path(__file__).resolve().parents[3]
    new_loop_template = (root / "src" / "loopora" / "templates" / "new_loop.html").read_text(encoding="utf-8")
    new_loop_script = (root / "src" / "loopora" / "static" / "pages" / "new_loop.js").read_text(encoding="utf-8")
    manual_surface = f"{new_loop_template}\n{new_loop_script}"

    for forbidden in [
        "Generate from orchestration",
        ">Orchestration<",
        ">Orchestrations<",
        "Choose orchestration",
        "No orchestration is available yet",
        "Choose an orchestration first",
        "The selected orchestration is",
        "This orchestration has no finish-on-pass",
    ]:
        assert forbidden not in manual_surface
    assert "Generate from flow" in manual_surface
    assert ">Run flow<" in manual_surface
    assert ">Flow library<" in manual_surface
    assert "Choose flow" in manual_surface
    assert "No flow is available yet" in manual_surface
    assert "Choose a flow first" in manual_surface
    assert "The selected flow is" in manual_surface


def test_compose_workspace_uses_conversation_language_for_default_copy() -> None:
    root = Path(__file__).resolve().parents[3]
    new_loop_template = (root / "src" / "loopora" / "templates" / "new_loop.html").read_text(encoding="utf-8")
    alignment_script = (root / "src" / "loopora" / "static" / "pages" / "alignment.js").read_text(
        encoding="utf-8"
    )
    compose_surface = f"{new_loop_template}\n{alignment_script}"

    for forbidden in [
        "对齐中",
        "启动对齐失败",
        "对齐事件分组",
        "Alignment event lanes",
        "对齐执行器配置方式",
        "Alignment executor configuration mode",
        "align that judgment",
        'localeText("流程判断", "Workflow")',
    ]:
        assert forbidden not in compose_surface
    assert "编排中" in compose_surface
    assert "Failed to start conversation." in compose_surface
    assert "Conversation event lanes" in compose_surface
    assert "Conversation executor configuration mode" in compose_surface
    assert "shape that judgment into a candidate Loop" in compose_surface
    assert 'localeText("运行流程", "Run flow")' in compose_surface


def test_tutorial_decision_tree_kicker_is_bilingual() -> None:
    root = Path(__file__).resolve().parents[3]
    template = (root / "src" / "loopora" / "templates" / "tutorial.html").read_text(encoding="utf-8")

    assert 'data-testid="tutorial-decision-tree-kicker"' in template
    assert re.search(
        r'<div class="tutorial-decision-tree-kicker" data-testid="tutorial-decision-tree-kicker">\s*'
        r'<span data-lang="zh">构建 · 检查 · 守门 · 引导</span>\s*'
        r'<span data-lang="en">Build · Inspect · Gate · Guide</span>\s*'
        r"</div>",
        template,
    )
    assert 'data-testid="tutorial-decision-tree-kicker">构建' not in template


def test_tutorial_default_copy_uses_flow_language() -> None:
    root = Path(__file__).resolve().parents[3]
    template = (root / "src" / "loopora" / "templates" / "tutorial.html").read_text(encoding="utf-8")

    for forbidden in [
        "workflow names",
        "workflow shape",
        "Choose the workflow",
        "Closer workflow fit",
        "which workflow matches",
        "memorize workflows",
        "Browse workflow examples",
        "Workflow example",
        "how this workflow turns",
        "posture",
        "姿态",
    ]:
        assert forbidden not in template
    assert "run-flow timing" in template
    assert "flow names" in template
    assert "choose the flow shape" in template
    assert "Choose the flow that" in template
    assert "Closer flow fit" in template
    assert "which flow matches this judgment" in template
    assert "Browse flow examples" in template
    assert "Flow example" in template
    assert "See how it carries judgment" in template


def test_chinese_visible_copy_uses_loop_as_stable_object_word() -> None:
    root = Path(__file__).resolve().parents[3]
    paths = [
        root / "src" / "loopora" / "templates" / "tutorial.html",
        root / "src" / "loopora" / "static" / "pages" / "new_loop.js",
        root / "src" / "loopora" / "static" / "pages" / "new_orchestration.js",
    ]

    for path in paths:
        source = path.read_text(encoding="utf-8")
        zh_template_strings = re.findall(r'data-lang="zh">([^<]*)<', source)
        zh_locale_strings = re.findall(r'localeText\("([^"]*)"', source)
        lowercase_loop_leaks = []
        for text in [*zh_template_strings, *zh_locale_strings]:
            text_without_commands = re.sub(r"/loopora-(?:gen|loop)\b", "", text)
            if re.search(r"\bloop\b", text_without_commands):
                lowercase_loop_leaks.append(text)
        assert not lowercase_loop_leaks, f"{path} leaks lowercase loop in Chinese visible copy: {lowercase_loop_leaks}"


def test_bundle_detail_uses_flow_language_for_chinese_governance_copy() -> None:
    root = Path(__file__).resolve().parents[3]
    bundle_detail_template = (root / "src" / "loopora" / "templates" / "bundle_detail.html").read_text(
        encoding="utf-8"
    )

    assert not re.findall(r'data-lang="zh">[^<]*workflow[^<]*<', bundle_detail_template, flags=re.IGNORECASE)
    assert '<span data-lang="en">Workflow</span>' not in bundle_detail_template
    assert "流程风险" in bundle_detail_template
    assert "流程提醒" in bundle_detail_template
    assert "运行流程" in bundle_detail_template
    assert "Run flow" in bundle_detail_template
    assert "{{ diagnostic.title_zh or diagnostic.title }}" in bundle_detail_template
    assert "{{ diagnostic.title_en or diagnostic.title }}" in bundle_detail_template
    assert "{{ diagnostic.message_zh or diagnostic.message }}" in bundle_detail_template
    assert "{{ diagnostic.message_en or diagnostic.message }}" in bundle_detail_template
    assert "<strong>{{ diagnostic.title }}</strong>" not in bundle_detail_template
    assert "<p>{{ diagnostic.message }}</p>" not in bundle_detail_template


def test_bundle_list_exposes_success_surface_governance_card() -> None:
    root = Path(__file__).resolve().parents[3]
    bundles_template = (root / "src" / "loopora" / "templates" / "bundles.html").read_text(encoding="utf-8")

    assert 'data-testid="bundle-governance-success"' in bundles_template
    assert "governance.success_surface" in bundles_template
    assert "Success surface" in bundles_template
    assert "成功面" in bundles_template
    assert 'data-testid="bundle-governance-coverage"' in bundles_template
    assert "governance.coverage_summary" in bundles_template
    assert "Coverage targets" in bundles_template
    assert "覆盖目标" in bundles_template
    assert 'data-testid="bundle-governance-residual-risk"' in bundles_template
    assert "governance.residual_risk_policy" in bundles_template
    assert "Residual risk" in bundles_template
    assert "残余风险" in bundles_template
    assert 'data-testid="bundle-governance-execution-strategy"' in bundles_template
    assert "governance.execution_strategy" in bundles_template
    assert "Execution strategy" in bundles_template
    assert "执行策略" in bundles_template
    assert 'data-testid="bundle-governance-tradeoffs"' in bundles_template
    assert "governance.judgment_tradeoffs" in bundles_template
    assert "Tradeoffs" in bundles_template
    assert "判断取舍" in bundles_template
    assert 'data-testid="bundle-governance-local"' in bundles_template
    assert "governance.local_governance" in bundles_template
    assert "Local governance" in bundles_template
    assert "本地治理" in bundles_template


def test_run_detail_projectors_map_progress_timeline_and_takeaways_without_dom() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required for static JS module checks")
    root = Path(__file__).resolve().parents[3]
    script = r"""
const fs = require("fs");
const vm = require("vm");
const context = {
  window: {},
  Date,
  Number,
  String,
  Map,
  Array,
  Math,
};
vm.createContext(context);
for (const file of [
  "src/loopora/static/pages/run_detail_progress_time.js",
  "src/loopora/static/pages/run_detail_progress_activity.js",
  "src/loopora/static/pages/run_detail_progress.js",
  "src/loopora/static/pages/run_detail_timeline.js",
  "src/loopora/static/pages/run_detail_takeaways.js",
  "src/loopora/static/pages/run_detail_render.js",
]) {
  vm.runInContext(fs.readFileSync(file, "utf8"), context);
}
const timeHelpers = context.window.LooporaRunDetailProgressTime.createProgressTimeHelpers({localeText: (_zh, en) => en});
if (timeHelpers.formatDurationMs(12) !== "12ms" || timeHelpers.formatDurationMs("12") !== "") {
  throw new Error("duration formatter did not require literal numeric input");
}
const progressEvents = [
  {id: 1, event_type: "checks_resolved", created_at: "2026-04-30T00:00:01Z", payload: {source: "specified"}},
  {id: 2, event_type: "role_started", created_at: "2026-04-30T00:00:02Z", role: "generator", payload: {role: "generator", step_id: "builder_step", iter: 0}},
];
const run = {
  status: "running",
  active_role: "generator",
  current_iter: 0,
  started_at: "2026-04-30T00:00:00Z",
  workflow_json: {
    roles: [{id: "builder", archetype: "builder", name: "Builder"}],
    steps: [{id: "builder_step", role_id: "builder"}],
  },
};
const progress = context.window.LooporaRunDetailProgress.createProgressProjector({
  localeText: (_zh, en) => en,
  parseTimestamp: (value) => Date.parse(value || ""),
  formatDuration: () => "1s",
  formatRelativeAge: () => "now",
  formatAbsoluteDate: (value) => value || "",
  stripMarkdown: (value) => String(value || ""),
  truncateText: (value) => String(value || ""),
  displayIter: (value) => Number(value) + 1,
  translateStatus: (status) => `status:${status}`,
  translateRole: (role) => `role:${role}`,
  normalizeRoleName: (name) => name,
  getCurrentRun: () => run,
  getProgressEvents: () => progressEvents,
  getConsoleEvents: () => [],
});
if (progress.getCurrentStage(run) !== "step:builder_step") {
  throw new Error(`progress stage mismatch: ${progress.getCurrentStage(run)}`);
}
const agentNativeProgress = context.window.LooporaRunDetailProgress.createProgressProjector({
  localeText: (_zh, en) => en,
  parseTimestamp: (value) => Date.parse(value || ""),
  formatDuration: () => "1s",
  formatRelativeAge: () => "now",
  formatAbsoluteDate: (value) => value || "",
  stripMarkdown: (value) => String(value || ""),
  truncateText: (value) => String(value || ""),
  displayIter: (value) => Number(value) + 1,
  translateStatus: (status) => `status:${status}`,
  translateRole: (role) => `role:${role}`,
  normalizeRoleName: (name) => name,
  getCurrentRun: () => ({...run, status: "awaiting_agent"}),
  getProgressEvents: () => [
    {
      id: 1,
      event_type: "step_context_prepared",
      created_at: "2026-04-30T00:00:02Z",
      role: "generator",
      payload: {role: "generator", role_name: "Builder", step_id: "builder_step", iter: 0},
    },
    {
      id: 2,
      event_type: "agent_native_step_claimed",
      created_at: "2026-04-30T00:00:03Z",
      role: "generator",
      payload: {role: "generator", role_name: "Builder", step_id: "builder_step", iter: 0},
    },
  ],
  getConsoleEvents: () => [],
});
const awaitingRun = {...run, status: "awaiting_agent"};
if (agentNativeProgress.getCurrentStage(awaitingRun) !== "step:builder_step") {
  throw new Error(`agent-native awaiting run stayed on checks: ${agentNativeProgress.getCurrentStage(awaitingRun)}`);
}
const agentNativeSnapshots = agentNativeProgress.getStageSnapshots(awaitingRun);
if (agentNativeSnapshots.checks.state !== "complete" || agentNativeSnapshots["step:builder_step"].state !== "current") {
  throw new Error(`agent-native stage snapshots hide active step: ${JSON.stringify(agentNativeSnapshots)}`);
}
if (progress.getProgressStages(run).filter((stage) => stage.kind === "workflow_step").length !== 1) {
  throw new Error("workflow step projection missing");
}
const terminalStage = progress.getProgressStages(run).find((stage) => stage.kind === "finished");
if (!terminalStage || terminalStage.title !== "Run closed" || terminalStage.chipLabel !== "Run closed") {
  throw new Error(`run closure stage used task-completion wording: ${JSON.stringify(terminalStage)}`);
}
const queuedDetail = progress.describeLiveWork({...run, status: "queued"}).detail;
if (queuedDetail.includes("executor") || !queuedDetail.includes("run slot")) {
  throw new Error(`queued progress hint leaked executor language: ${queuedDetail}`);
}
const installHint = context.window.LooporaRunDetailProgressActivity.createProgressActivityProjector({
  localeText: (_zh, en) => en,
  truncateText: (value) => String(value || ""),
  stripMarkdown: (value) => String(value || ""),
  activityHintKey: () => "builder",
}).commandProgressHint("uv sync", "step:builder_step", run);
if (!installHint.title.includes("Installing dependencies")) {
  throw new Error(`command hint projection failed: ${JSON.stringify(installHint)}`);
}
const timeline = context.window.LooporaRunDetailTimeline.createTimelineProjector({
  localeText: (_zh, en) => en,
  escapeHtml: (value) => String(value || ""),
  formatClock: () => "00:00:00",
  formatAbsoluteDate: () => "date",
  formatDurationMs: (value) => `${value}ms`,
  displayIter: (value) => Number(value) + 1,
  resolvedPayloadRoleName: () => "Builder",
  translateRole: (role) => `role:${role}`,
  translateStatus: (status) => `status:${status}`,
});
const formatted = timeline.formatTimelineEvent({event_type: "role_execution_summary", role: "generator", payload: {ok: true, duration_ms: 12}});
if (!formatted.title.includes("role:generator") || !formatted.detail.includes("12ms")) {
  throw new Error(`timeline projection failed: ${JSON.stringify(formatted)}`);
}
const malformedChecksTimeline = timeline.formatTimelineEvent({event_type: "checks_resolved", payload: {count: "7"}});
if (malformedChecksTimeline.detail.includes("7 checks")) {
  throw new Error(`timeline promoted malformed check count: ${JSON.stringify(malformedChecksTimeline)}`);
}
const malformedSuccessTimeline = timeline.formatTimelineEvent({event_type: "role_execution_summary", role: "generator", payload: {ok: true, attempts: "2", degraded: "false", duration_ms: "12"}});
if (malformedSuccessTimeline.detail.includes("attempts=2") || malformedSuccessTimeline.detail.includes("degraded") || malformedSuccessTimeline.detail.includes("12ms")) {
  throw new Error(`timeline promoted malformed role summary fields: ${JSON.stringify(malformedSuccessTimeline)}`);
}
const stringOkTimeline = timeline.formatTimelineEvent({event_type: "role_execution_summary", role: "generator", payload: {ok: "false", error: "failed as string"}});
if (!stringOkTimeline.title.includes("failed")) {
  throw new Error(`string ok timeline projection did not fail closed: ${JSON.stringify(stringOkTimeline)}`);
}
const stringOkTone = timeline.timelineTone({event_type: "role_execution_summary", payload: {ok: "false"}});
if (stringOkTone !== "danger") {
  throw new Error(`string ok timeline tone did not fail closed: ${stringOkTone}`);
}
const runFinished = timeline.formatTimelineEvent({event_type: "run_finished", payload: {status: "succeeded", task_verdict_status: "insufficient_evidence", task_verdict_summary: "Required coverage still lacks direct evidence.", iter: 1}});
if (!runFinished.detail.includes("Task verdict insufficient_evidence") || !runFinished.detail.includes("Verdict summary Required coverage still lacks direct evidence.")) {
  throw new Error(`run finished verdict projection failed: ${JSON.stringify(runFinished)}`);
}
const acceptedTimeline = timeline.formatTimelineEvent({event_type: "run_result_accepted", payload: {status: "succeeded", task_verdict_status: "passed", judgment_contract_summary: "Prefer proof before closure.", loop_fit_reasons: ["Future rounds keep proof alive."], execution_strategy: ["Prove focused path before polish."], local_governance: ["GateKeeper treats skipped AGENTS.md checks as Blocking."], role_postures: ["GateKeeper: Fail closed when evidence is weak."], judgment_tradeoffs: ["Proof beats polish."], success_surface: ["Support admin can approve a refund."], fake_done_states: ["CSV export without permission audit is fake done."], evidence_preferences: ["Use browser journey and audit log evidence."], residual_risk: "No residual risk is acceptable."}});
if (acceptedTimeline.title !== "Passing evidence verdict recorded" || !acceptedTimeline.detail.includes("Task verdict passed") || !acceptedTimeline.detail.includes("Judgment Prefer proof before closure.") || !acceptedTimeline.detail.includes("Fit Future rounds keep proof alive.") || !acceptedTimeline.detail.includes("Strategy Prove focused path before polish.") || !acceptedTimeline.detail.includes("Local governance GateKeeper treats skipped AGENTS.md checks") || !acceptedTimeline.detail.includes("Role posture GateKeeper: Fail closed") || !acceptedTimeline.detail.includes("Tradeoff Proof beats polish.") || !acceptedTimeline.detail.includes("Success Support admin can approve a refund.") || !acceptedTimeline.detail.includes("Fake done CSV export without permission audit is fake done.") || !acceptedTimeline.detail.includes("Evidence Use browser journey and audit log evidence.") || !acceptedTimeline.detail.includes("Residual risk No residual risk is acceptable.")) {
  throw new Error(`accepted timeline judgment projection failed: ${JSON.stringify(acceptedTimeline)}`);
}
const unprovenAcceptedTimeline = timeline.formatTimelineEvent({event_type: "run_result_accepted", payload: {status: "succeeded", task_verdict_status: "insufficient_evidence"}});
if (unprovenAcceptedTimeline.title !== "Unproven evidence verdict recorded" || unprovenAcceptedTimeline.title.includes("accepted")) {
  throw new Error(`unproven recorded verdict timeline projection accepted completion: ${JSON.stringify(unprovenAcceptedTimeline)}`);
}
const unevaluatedAcceptedTimeline = timeline.formatTimelineEvent({event_type: "run_result_accepted", payload: {status: "failed", task_verdict_status: "not_evaluated"}});
if (unevaluatedAcceptedTimeline.title !== "Unevaluated evidence verdict recorded" || unevaluatedAcceptedTimeline.title === "Evidence verdict recorded") {
  throw new Error(`unevaluated recorded verdict timeline projection was generic: ${JSON.stringify(unevaluatedAcceptedTimeline)}`);
}
const acceptedUnevaluatedTone = timeline.timelineTone({event_type: "run_result_accepted", payload: {status: "succeeded", task_verdict_status: "not_evaluated"}});
if (acceptedUnevaluatedTone !== "warning") {
  throw new Error(`accepted unevaluated timeline tone failed closed incorrectly: ${acceptedUnevaluatedTone}`);
}
const acceptedWarningTone = timeline.timelineTone({event_type: "run_result_accepted", payload: {status: "succeeded", task_verdict_status: "insufficient_evidence"}});
if (acceptedWarningTone !== "warning") {
  throw new Error(`accepted insufficient evidence timeline tone failed: ${acceptedWarningTone}`);
}
const acceptedPassedTone = timeline.timelineTone({event_type: "run_result_accepted", payload: {status: "succeeded", task_verdict_status: "passed"}});
if (acceptedPassedTone !== "success") {
  throw new Error(`accepted passed timeline tone failed: ${acceptedPassedTone}`);
}
const zhTimeline = context.window.LooporaRunDetailTimeline.createTimelineProjector({
  localeText: (zh, _en) => zh,
  escapeHtml: (value) => String(value || ""),
  formatClock: () => "00:00:00",
  formatAbsoluteDate: () => "date",
  formatDurationMs: (value) => `${value}ms`,
  displayIter: (value) => Number(value) + 1,
  resolvedPayloadRoleName: () => "Builder",
  translateRole: (role) => `role:${role}`,
  translateStatus: (status) => `status:${status}`,
});
const zhRunFinished = zhTimeline.formatTimelineEvent({event_type: "run_finished", payload: {status: "succeeded", task_verdict_status: "insufficient_evidence", task_verdict_summary: "证据仍缺少审计路径。", iter: 1}});
if (!zhRunFinished.detail.includes("Loop 裁决 insufficient_evidence") || !zhRunFinished.detail.includes("裁决摘要 证据仍缺少审计路径。") || zhRunFinished.detail.includes("任务裁决")) {
  throw new Error(`Chinese run finished timeline projection used the wrong verdict term: ${JSON.stringify(zhRunFinished)}`);
}
const malformedRunFinished = timeline.formatTimelineEvent({event_type: "run_finished", payload: {status: "succeeded", iter: "3"}});
if (malformedRunFinished.detail.includes("Iter 4") || !malformedRunFinished.detail.includes("Task verdict not_evaluated")) {
  throw new Error(`timeline promoted malformed run iter: ${JSON.stringify(malformedRunFinished)}`);
}
const unevaluatedRunFinishedTone = timeline.timelineTone({event_type: "run_finished", payload: {status: "succeeded"}});
if (unevaluatedRunFinishedTone !== "warning") {
  throw new Error(`run finished missing verdict tone promoted lifecycle success: ${unevaluatedRunFinishedTone}`);
}
const runFinishedTone = timeline.timelineTone({event_type: "run_finished", payload: {status: "succeeded", task_verdict_status: "insufficient_evidence"}});
if (runFinishedTone !== "warning") {
  throw new Error(`run finished verdict tone failed: ${runFinishedTone}`);
}
const parallelStarted = timeline.formatTimelineEvent({event_type: "parallel_group_started", payload: {parallel_group: "inspection_pack", step_ids: ["inspect_a", "inspect_b"]}});
if (parallelStarted.title !== "Parallel review started" || !parallelStarted.detail.includes("2 steps")) {
  throw new Error(`parallel group timeline projection failed: ${JSON.stringify(parallelStarted)}`);
}
const takeaways = context.window.LooporaRunDetailTakeaways.createTakeawayProjector({
  localeText: (_zh, en) => en,
  escapeHtml: (value) => String(value || ""),
  formatAbsoluteDate: () => "date",
});
const snapshot = {
  task_verdict: {
    status: "passed",
    summary: "ok",
    buckets: {
      proven: [
        {text: "done", evidence_refs: ["ev_001"], artifact_refs: [{kind: "workspace", workspace_path: "proof.md"}]},
        {text: "same proof", evidence_refs: ["ev_001"], artifact_refs: [{kind: "workspace", workspace_path: "proof.md"}]},
      ],
    },
  },
  task_verdict_path: "evidence/task_verdict.json",
  judgment_contract: {
    contract_path: "contract/run_contract.json",
    source_bundle: {id: "bundle_run", name: "Run Detail Bundle", revision: 3, bundle_sha256: "abcdef1234567890", imported_from_path: "/tmp/loopora/bundle.yml"},
    collaboration_summary: "Prefer proof before closure.",
    workflow_collaboration_intent: "Route review evidence before closure.",
    loop_fit_reasons: ["Future rounds keep proof alive."],
    execution_strategy: ["Prove focused path before polish."],
    local_governance: ["GateKeeper treats skipped AGENTS.md checks as Blocking."],
    role_postures: ["GateKeeper: Fail closed when evidence is weak."],
    judgment_tradeoffs: ["Proof beats polish when evidence is weak."],
    success_surface: ["Checkout instrumentation records the buyer action."],
    fake_done_states: ["A story without audit evidence is fake done."],
    evidence_preferences: ["Use reproducible checks."],
    residual_risk: "Manual billing export remains a Support-owned follow-up.",
  },
  evidence_coverage: {coverage_path: "evidence/coverage.json", evidence_count: 1, summary: {reason: "covered"}},
  evidence_manifest: {manifest_path: "evidence/manifest.json", claim_count: 2, direct_proof_claim_count: 1, workspace_artifact_claim_count: 0, run_artifact_claim_count: 1, ledger_only_claim_count: 1, unverified_claim_count: 0},
  iterations: [{iter: 0, display_iter: 1, status: "passed", role_count: 1, roles: []}],
};
if (!takeaways.evidenceOutcome(snapshot, run).title.includes("Passed")) {
  throw new Error("takeaway outcome projection failed");
}
const coverageHtml = takeaways.evidenceCoverageHtml(snapshot, "run_1");
if (!coverageHtml.includes("View trace")) {
  throw new Error("takeaway coverage html projection failed");
}
if (!coverageHtml.includes("View verdict")) {
  throw new Error("takeaway task verdict html projection failed");
}
if (!(coverageHtml.indexOf("Verdict status") < coverageHtml.indexOf("Proven") && coverageHtml.indexOf("Proven") < coverageHtml.indexOf("Weak") && coverageHtml.indexOf("Weak") < coverageHtml.indexOf("Unproven") && coverageHtml.indexOf("Unproven") < coverageHtml.indexOf("Blocking") && coverageHtml.indexOf("Blocking") < coverageHtml.indexOf("Residual risk") && coverageHtml.indexOf("Residual risk") < coverageHtml.indexOf("Proof strength") && coverageHtml.indexOf("Proof strength") < coverageHtml.indexOf("Judgment contract"))) {
  throw new Error("takeaway evidence bucket order should put verdict and evidence buckets before trace material");
}
if (!coverageHtml.includes("View contract") || !coverageHtml.includes("Source plan: Run Detail Bundle") || !coverageHtml.includes("rev 3") || !coverageHtml.includes("sha abcdef123456") || !coverageHtml.includes("Fit: Future rounds keep proof alive.") || !coverageHtml.includes("Success: Checkout instrumentation records the buyer action.") || !coverageHtml.includes("Fake done: A story without audit evidence is fake done.") || !coverageHtml.includes("Evidence: Use reproducible checks.") || !coverageHtml.includes("Residual risk: Manual billing export remains a Support-owned follow-up.")) {
  throw new Error("takeaway judgment contract html projection failed");
}
if (coverageHtml.includes("/tmp/loopora/bundle.yml") || coverageHtml.includes("Prefer proof before closure.") || coverageHtml.includes("Route review evidence before closure.") || coverageHtml.includes("Execution strategy: Prove focused path") || coverageHtml.includes("Local governance: GateKeeper treats skipped AGENTS.md checks") || coverageHtml.includes("Role posture: GateKeeper: Fail closed") || coverageHtml.includes("Tradeoff: Proof beats polish")) {
  throw new Error("takeaway judgment contract summary should stay compact on the run detail first screen");
}
if (!coverageHtml.includes("View manifest") || !coverageHtml.includes("Direct 1")) {
  throw new Error("takeaway manifest html projection failed");
}
if (!coverageHtml.includes("1 evidence ref") || !coverageHtml.includes("1 artifact")) {
  throw new Error("takeaway bucket trace count projection failed");
}
const malformedCoverageHtml = takeaways.evidenceCoverageHtml({
  task_verdict: {status: "not_evaluated", buckets: {}},
  evidence_coverage: {evidence_count: "4", covered_check_count: "2", check_count: "3"},
  evidence_manifest: {manifest_path: "evidence/manifest.json", claim_count: "5", direct_proof_claim_count: "2"},
}, "run_1");
if (malformedCoverageHtml.includes("Direct 2") || malformedCoverageHtml.includes("2/5") || malformedCoverageHtml.includes("4 evidence")) {
  throw new Error(`takeaway promoted malformed evidence counts: ${malformedCoverageHtml}`);
}
const unmanagedRiskHtml = takeaways.evidenceCoverageHtml({
  task_verdict: {
    status: "passed",
    buckets: {
      weak: [{text: "Some residual risk remains."}],
      residual_risk: [],
    },
  },
  evidence_coverage: {residual_risk_count: 1},
}, "run_1");
if (
  !unmanagedRiskHtml.includes("Some residual risk remains.") ||
  !/Residual risk<\/span>\s*<strong>0<\/strong>/.test(unmanagedRiskHtml)
) {
  throw new Error(`unmanaged residual risk should stay weak instead of falling back to residual count: ${unmanagedRiskHtml}`);
}
const legacyBucketSnapshot = {
  task_verdict: {
    status: "failed",
    summary: "",
    buckets: {
      blocking: [],
      residual_risk: [],
    },
  },
  evidence_buckets: {
    blocking: [{text: "permission audit is blocked"}],
    residual_risk: [{label: "Support owns the manual export follow-up"}],
  },
  evidence_coverage: {status: "blocked", blocked_target_count: 1},
  evidence_manifest: {},
  iterations: [],
};
const legacyBucketHtml = takeaways.evidenceCoverageHtml(legacyBucketSnapshot, "run_1");
const legacyBucketOutcome = takeaways.evidenceOutcome(legacyBucketSnapshot, run);
if (
  !legacyBucketHtml.includes("permission audit is blocked") ||
  !legacyBucketHtml.includes("Support owns the manual export follow-up") ||
  !legacyBucketOutcome.detail.includes("permission audit is blocked")
) {
  throw new Error(`legacy evidence bucket fallback failed: ${legacyBucketHtml} ${JSON.stringify(legacyBucketOutcome)}`);
}
const stalledIterationHtml = takeaways.renderTakeawayIterationCard({
  iter: 1,
  display_iter: 2,
  status: "blocked",
  summary: "Evidence did not move.",
  composite_score: 0.7,
  evidence_progress_mode: "stalled",
  covered_check_count: 0,
  missing_check_count: 2,
  consecutive_no_required_coverage_delta: 1,
  role_count: 1,
  roles: [],
}, {evidence_count: 4});
if (!stalledIterationHtml.includes("Evidence progress stalled") || !stalledIterationHtml.includes("Coverage 0 covered / 2 missing")) {
  throw new Error(`takeaway evidence-progress projection failed: ${stalledIterationHtml}`);
}
const activePartialIterationHtml = takeaways.renderTakeawayIterationCard({
  iter: 0,
  display_iter: 1,
  status: "running",
  summary: "Builder produced a structured handoff for downstream inspection.",
  coverage_status: "partial",
  covered_check_count: 0,
  missing_check_count: 2,
  role_count: 1,
  roles: [{role_name: "Focused Builder", step_order: 0, status: "completed"}],
}, {evidence_count: 1});
if (
  !activePartialIterationHtml.includes("This round is still moving") ||
  !activePartialIterationHtml.includes("Coverage 0 covered / 2 missing") ||
  activePartialIterationHtml.includes("This round finished")
) {
  throw new Error(`active partial iteration takeaway overstated completion: ${activePartialIterationHtml}`);
}
const malformedIterationHtml = takeaways.renderTakeawayIterationCard({
  display_iter: "2",
  status: "blocked",
  evidence_progress_mode: "stalled",
  covered_check_count: "1",
  missing_check_count: "2",
  consecutive_no_required_coverage_delta: "3",
  role_count: "4",
  roles: [{role_name: "Builder", step_order: "8", status: "passed"}],
}, {evidence_count: "5"});
if (
  malformedIterationHtml.includes("Iter 2") ||
  malformedIterationHtml.includes("Coverage 1 covered / 2 missing") ||
  malformedIterationHtml.includes("4 role") ||
  malformedIterationHtml.includes(">09<")
) {
  throw new Error(`takeaway promoted malformed iteration counts: ${malformedIterationHtml}`);
}
const residualSnapshot = {
  task_verdict: {
    status: "passed_with_residual_risk",
    summary: "",
    buckets: {proven: [{text: "done"}], residual_risk: [{text: "manual billing export remains"}]},
  },
  evidence_coverage: {coverage_path: "evidence/coverage.json", residual_risk_count: 1, summary: {reason: "accepted risk"}},
  evidence_manifest: {},
  iterations: [],
};
const residualOutcome = takeaways.evidenceOutcome(residualSnapshot, run);
if (residualOutcome.soft || !residualOutcome.title.includes("Passed with residual risk") || !residualOutcome.detail.includes("manual billing export")) {
  throw new Error(`residual-risk takeaway outcome failed: ${JSON.stringify(residualOutcome)}`);
}
const residualCoverageHtml = takeaways.evidenceCoverageHtml(residualSnapshot, "run_1");
if (!residualCoverageHtml.includes("Residual risk") || !residualCoverageHtml.includes("manual billing export")) {
  throw new Error("residual-risk evidence card projection failed");
}
const zhTakeaways = context.window.LooporaRunDetailTakeaways.createTakeawayProjector({
  localeText: (zh, _en) => zh,
  escapeHtml: (value) => String(value || ""),
  formatAbsoluteDate: () => "date",
});
if (zhTakeaways.takeawayMeta({}) !== "角色交接写出来后，这里会自动更新。") {
  throw new Error(`Chinese takeaway meta leaked internal handoff wording: ${zhTakeaways.takeawayMeta({})}`);
}
const render = context.window.LooporaRunDetailRender.createRenderProjector({
  localeText: (_zh, en) => en,
  takeawayProjector: takeaways,
  timelineProjector: timeline,
  formatAbsoluteDate: () => "date",
});
const verdictSummary = render.summarizeTaskVerdict({
  status: "passed_with_residual_risk",
  source: "gatekeeper",
  buckets: {proven: [{}], weak: [{}], unproven: [], blocking: [], residual_risk: [{text: "manual billing export remains"}, {}]},
});
if (
  !verdictSummary.title.includes("Passed with residual risk") ||
  !verdictSummary.detail.includes("manual billing export remains") ||
  !verdictSummary.meta.includes("proven 1") ||
  !verdictSummary.meta.includes("weak 1") ||
  !verdictSummary.meta.includes("residual risk 2")
) {
  throw new Error(`render verdict projection failed: ${JSON.stringify(verdictSummary)}`);
}
const passedSummary = render.summarizeTaskVerdict({
  status: "passed",
  source: "gatekeeper",
  buckets: {proven: [{text: "main flow verified"}]},
});
if (!passedSummary.detail.includes("main flow verified") || passedSummary.detail.includes("No evidence-based task verdict")) {
  throw new Error(`render passed fallback failed: ${JSON.stringify(passedSummary)}`);
}
const latestSummary = render.summarizeLatestEvent([{event_type: "run_finished", created_at: "2026-04-30T00:00:00Z", payload: {status: "succeeded"}}]);
if (!latestSummary.title.includes("Run finished") || latestSummary.meta !== "date") {
  throw new Error(`render latest event projection failed: ${JSON.stringify(latestSummary)}`);
}
"""
    subprocess.run([node, "-e", script], cwd=root, check=True)


def test_run_detail_projector_defaults_escape_dynamic_html() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required for static JS module checks")
    root = Path(__file__).resolve().parents[3]
    script = r"""
const fs = require("fs");
const vm = require("vm");
const context = {
  window: {},
  Date,
  Number,
  String,
  Array,
};
vm.createContext(context);
for (const file of [
  "src/loopora/static/pages/run_detail_timeline.js",
  "src/loopora/static/pages/run_detail_takeaways.js",
]) {
  vm.runInContext(fs.readFileSync(file, "utf8"), context);
}
const timeline = context.window.LooporaRunDetailTimeline.createTimelineProjector({
  localeText: (_zh, en) => en,
  formatClock: () => "00:00:00",
  formatAbsoluteDate: () => "date",
});
const timelineHtml = timeline.renderTimelineItem({
  event_type: "step_handoff_written",
  created_at: "2026-04-30T00:00:00Z",
  payload: {summary: "<img src=x onerror=alert(1)>&'\""},
});
if (timelineHtml.includes("<img src=x") || !timelineHtml.includes("&lt;img src=x")) {
  throw new Error(`timeline default escape failed: ${timelineHtml}`);
}
if (!timelineHtml.includes("&amp;") || !timelineHtml.includes("&#39;") || !timelineHtml.includes("&quot;")) {
  throw new Error(`timeline escaped entities missing: ${timelineHtml}`);
}
const takeaways = context.window.LooporaRunDetailTakeaways.createTakeawayProjector({
  localeText: (_zh, en) => en,
  formatAbsoluteDate: () => "date",
});
const iterationHtml = takeaways.renderTakeawayIterationCard({
  display_iter: "<b>1</b>",
  status: "passed\"><svg onload=alert(1)>",
  summary: "<script>alert(1)</script>",
  role_count: 1,
  roles: [{
    role_name: "<b>Builder</b>",
    status: "failed\" onclick=\"alert(1)",
    summary: "<img src=x onerror=alert(1)>",
    blocking_item: "<stop>",
  }],
}, {evidence_count: 1});
for (const unsafe of ["<script>", "<img src=x", "<b>Builder", "<svg onload"]) {
  if (iterationHtml.includes(unsafe)) {
    throw new Error(`takeaway default escape leaked ${unsafe}: ${iterationHtml}`);
  }
}
for (const escaped of ["&lt;script&gt;", "&lt;img src=x", "&lt;b&gt;Builder", "&quot;", "&lt;stop&gt;"]) {
  if (!iterationHtml.includes(escaped)) {
    throw new Error(`takeaway default escape missing ${escaped}: ${iterationHtml}`);
  }
}
for (const file of [
  "src/loopora/static/pages/run_detail_timeline.js",
  "src/loopora/static/pages/run_detail_takeaways.js",
  "src/loopora/static/pages/run_detail_render.js",
]) {
  const source = fs.readFileSync(file, "utf8");
  if (source.includes("deps.escapeHtml || ((value) => String(value || \"\"))")) {
    throw new Error(`unsafe escape fallback remains in ${file}`);
  }
  if (!source.includes("deps.escapeHtml || defaultEscapeHtml")) {
    throw new Error(`default escape fallback is not wired in ${file}`);
  }
}
"""
    subprocess.run([node, "-e", script], cwd=root, check=True)


def test_run_detail_observation_projector_handles_snapshot_dedupe_and_stream_state() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required for static JS module checks")
    root = Path(__file__).resolve().parents[3]
    script = r"""
const fs = require("fs");
const vm = require("vm");
const context = {window: {}};
vm.createContext(context);
vm.runInContext(fs.readFileSync("src/loopora/static/pages/run_detail_observation.js", "utf8"), context);
const observation = context.window.LooporaRunDetailObservation;
const merged = observation.mergeSnapshotState(
  {currentRun: {id: "run_1", status: "running"}, lastEventId: 7},
  {
    run: {id: "run_1", status: "running"},
    latest_event_id: 12,
    timeline_events: Array.from({length: 45}, (_, index) => ({id: index + 1})),
    console_events: Array.from({length: 170}, (_, index) => ({id: index + 1})),
    progress_events: Array.from({length: 2010}, (_, index) => ({id: index + 1})),
    key_takeaways: {run_status: "running"},
    current_agent_step: {step_id: "builder_step", target_agent: "loopora-builder"},
  }
);
if (merged.lastEventId !== 12 || merged.timelineRecords.length !== 40 || merged.consoleEventRecords.length !== 160 || merged.progressEventRecords.length !== 2000) {
  throw new Error(`snapshot normalization failed: ${JSON.stringify(merged)}`);
}
if (merged.currentAgentStep.step_id !== "builder_step" || merged.currentAgentStep.target_agent !== "loopora-builder") {
  throw new Error(`current agent step projection was not preserved: ${JSON.stringify(merged.currentAgentStep)}`);
}
const malformedSnapshot = observation.mergeSnapshotState(
  {currentRun: {id: "run_1", status: "running"}, lastEventId: 7},
  {run: {id: "run_1", status: "running"}, latest_event_id: "12", timeline_events: []}
);
if (malformedSnapshot.lastEventId !== 7) {
  throw new Error(`snapshot promoted malformed latest_event_id: ${JSON.stringify(malformedSnapshot)}`);
}
const deduped = observation.appendUniqueEvent([{id: 1}, {id: 2}], {id: 2}, 10);
if (deduped.length !== 2) {
  throw new Error(`duplicate event was appended: ${JSON.stringify(deduped)}`);
}
const updatedRun = observation.applyRunEvent({status: "running", active_role: "generator"}, {
  event_type: "run_finished",
  created_at: "2026-04-30T00:00:00Z",
  payload: {status: "succeeded", iter: 2, task_verdict_status: "insufficient_evidence", task_verdict_source: "gatekeeper", task_verdict_summary: "Required coverage still lacks direct evidence."},
});
if (updatedRun.status !== "succeeded" || updatedRun.active_role !== null || updatedRun.current_iter !== 2) {
  throw new Error(`run event state failed: ${JSON.stringify(updatedRun)}`);
}
if (updatedRun.task_verdict.status !== "insufficient_evidence" || updatedRun.task_verdict.source !== "gatekeeper" || updatedRun.task_verdict.summary !== "Required coverage still lacks direct evidence.") {
  throw new Error(`run event task verdict was not merged: ${JSON.stringify(updatedRun)}`);
}
const malformedIterRun = observation.applyRunEvent({status: "running", active_role: "generator", current_iter: 1}, {
  event_type: "run_finished",
  created_at: "2026-04-30T00:00:00Z",
  payload: {status: "succeeded", iter: "2"},
});
if (malformedIterRun.current_iter !== 1) {
  throw new Error(`run event promoted malformed iter: ${JSON.stringify(malformedIterRun)}`);
}
if (observation.streamFailureState({run: {status: "running"}, failureCount: 4}) !== "stream-stale") {
  throw new Error("stream stale threshold failed");
}
if (observation.shouldReconnect({status: "stopped"})) {
  throw new Error("terminal run should not reconnect");
}
"""
    subprocess.run([node, "-e", script], cwd=root, check=True)


def test_run_detail_state_and_stream_controller_handle_reliability_edges() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required for static JS module checks")
    root = Path(__file__).resolve().parents[3]
    script = r"""
const fs = require("fs");
const vm = require("vm");
const context = {
  window: {},
  Number,
  Array,
  Math,
};
vm.createContext(context);
for (const file of [
  "src/loopora/static/pages/run_detail_observation.js",
  "src/loopora/static/pages/run_detail_state.js",
  "src/loopora/static/pages/run_detail_stream.js",
  "src/loopora/static/pages/run_detail_scheduler.js",
]) {
  vm.runInContext(fs.readFileSync(file, "utf8"), context);
}
const observation = context.window.LooporaRunDetailObservation;
const store = context.window.LooporaRunDetailState.createRunDetailState({
  currentRun: {id: "run_1", status: "running"},
  lastEventId: 5,
  observationState: "loading",
}, {observation});
const merged = store.mergeSnapshot({
  run: {id: "run_1", status: "running"},
  latest_event_id: 7,
  timeline_events: [{id: 7, event_type: "run_started"}],
  console_events: [{id: 7, event_type: "run_started"}],
  progress_events: [{id: 7, event_type: "run_started"}],
  current_agent_step: {step_id: "builder_step"},
});
if (merged.lastEventId !== 7 || merged.observationState !== "ready" || merged.currentAgentStep.step_id !== "builder_step") {
  throw new Error(`snapshot state failed: ${JSON.stringify(merged)}`);
}
const duplicate = store.applyStreamEvent({id: 7, event_type: "role_started", payload: {role: "generator"}});
if (!duplicate.duplicate || duplicate.state.lastEventId !== 7) {
  throw new Error(`duplicate stream event was not suppressed: ${JSON.stringify(duplicate)}`);
}
const malformedId = store.applyStreamEvent({id: "8", event_type: "role_started", payload: {role: "generator"}});
if (!malformedId.duplicate || malformedId.state.lastEventId !== 7) {
  throw new Error(`malformed stream event id was not suppressed: ${JSON.stringify(malformedId)}`);
}
const applied = store.applyStreamEvent({id: 8, event_type: "run_finished", created_at: "2026-04-30T00:00:00Z", payload: {status: "succeeded", task_verdict_status: "insufficient_evidence", task_verdict_summary: "Audit proof is missing."}});
if (applied.duplicate || applied.state.currentRun.status !== "succeeded" || applied.state.currentRun.task_verdict.status !== "insufficient_evidence" || applied.state.currentRun.task_verdict.summary !== "Audit proof is missing." || applied.state.lastEventId !== 8) {
  throw new Error(`stream event state failed: ${JSON.stringify(applied)}`);
}
const states = [];
const delays = [];
const controller = context.window.LooporaRunDetailStream.createStreamController({
  observation,
  retryDelays: [1000, 2000, 5000, 10000],
  getRun: () => ({status: "running"}),
  setObservationState: (state) => states.push(state),
  scheduleReconnect: (delay) => delays.push(delay),
});
let result = controller.markFailure("stream_error");
if (!result.counted || result.failureCount !== 1 || states[states.length - 1] !== "stream-error" || delays[delays.length - 1] !== 1000) {
  throw new Error(`stream_error failure state failed: ${JSON.stringify(result)}`);
}
result = controller.markFailure("connection");
if (result.counted || controller.getFailureCount() !== 1) {
  throw new Error(`stream_error/onerror double count was not suppressed: ${JSON.stringify(result)}`);
}
controller.markFailure("connection");
controller.markFailure("connection");
controller.markFailure("connection");
if (controller.getFailureCount() !== 4 || states[states.length - 1] !== "stream-stale") {
  throw new Error(`stream stale state failed: ${JSON.stringify({states, count: controller.getFailureCount()})}`);
}
const terminalStates = [];
const terminalController = context.window.LooporaRunDetailStream.createStreamController({
  observation,
  getRun: () => ({status: "succeeded"}),
  setObservationState: (state) => terminalStates.push(state),
  scheduleReconnect: () => { throw new Error("terminal run should not reconnect"); },
});
const terminalResult = terminalController.markFailure("connection");
if (terminalResult.reconnect || terminalStates[terminalStates.length - 1] !== "finished") {
  throw new Error(`terminal stream failure state failed: ${JSON.stringify(terminalResult)}`);
}
const timers = [];
const cleared = [];
let intervalId = 100;
const scheduler = context.window.LooporaRunDetailScheduler.createScheduler({
  windowRef: {
    setTimeout: (callback, delay) => {
      timers.push({type: "timeout", callback, delay});
      return timers.length;
    },
    clearTimeout: (id) => cleared.push(["timeout", id]),
    setInterval: (callback, delay) => {
      timers.push({type: "interval", callback, delay});
      intervalId += 1;
      return intervalId;
    },
    clearInterval: (id) => cleared.push(["interval", id]),
  },
  documentRef: {visibilityState: "visible"},
  fetchRun: () => Promise.resolve(),
  isActive: () => true,
  onHeartbeat: () => {},
});
scheduler.scheduleRunRefresh({refreshTakeaways: true});
if (!scheduler.snapshot().hasRefreshTimer || !scheduler.snapshot().takeawayRefreshQueued) {
  throw new Error(`scheduler refresh queue failed: ${JSON.stringify(scheduler.snapshot())}`);
}
scheduler.syncLiveRefreshers();
if (!scheduler.snapshot().hasPollTimer || !scheduler.snapshot().hasHeartbeatTimer) {
  throw new Error(`scheduler live timers failed: ${JSON.stringify(scheduler.snapshot())}`);
}
scheduler.clear();
if (scheduler.snapshot().hasRefreshTimer || scheduler.snapshot().hasPollTimer || scheduler.snapshot().hasHeartbeatTimer) {
  throw new Error(`scheduler clear failed: ${JSON.stringify(scheduler.snapshot())}`);
}
"""
    subprocess.run([node, "-e", script], cwd=root, check=True)


def _assert_alignment_agent_review_bridge_assets(alignment_css: str, alignment_js: str) -> None:
    assert ".alignment-agent-review-bridge {" in alignment_css
    assert "alignment-agent-review-bridge" in alignment_js
    assert "missing_judgment_item_ids" in alignment_js
    assert "candidate plan file" in alignment_js
    assert "This is not a runnable Loop yet" in alignment_js


def _assert_alignment_ready_preview_summary_layout(alignment_css: str) -> None:
    decision_risk_rule = re.search(r"\.alignment-decision-risk \{(?P<body>.*?)\n\}", alignment_css, re.S)
    assert decision_risk_rule
    assert "grid-template-columns: minmax(0, 1fr);" in alignment_css
    assert "justify-content: flex-start;" in alignment_css
    assert "overflow-wrap: break-word;" in decision_risk_rule.group("body")
    assert "overflow-wrap: anywhere;" not in decision_risk_rule.group("body")
    assert ".alignment-review-gate {" in alignment_css
    assert ".alignment-review-gate-confirm {" in alignment_css
    assert "#alignment-import-run-button[disabled]" in alignment_css


def _assert_alignment_static_asset_regressions(client: TestClient) -> None:
    alignment_css_response = client.get("/static/pages/alignment.css")
    assert alignment_css_response.status_code == 200
    alignment_css = alignment_css_response.text
    _assert_alignment_css_static_asset_regressions(alignment_css)

    alignment_js_response = client.get("/static/pages/alignment.js")
    assert alignment_js_response.status_code == 200
    alignment_js = alignment_js_response.text
    _assert_alignment_js_static_asset_regressions(alignment_css, alignment_js)

    bundle_import_js_response = client.get("/static/pages/bundle_import.js")
    assert bundle_import_js_response.status_code == 200
    _assert_bundle_import_static_asset_regressions(bundle_import_js_response.text)


def _assert_alignment_css_static_asset_regressions(alignment_css: str) -> None:
    assert ".alignment-chat {" in alignment_css
    assert ".bundle-chat-shell {" in alignment_css
    assert ".alignment-working-card {" in alignment_css
    assert ".alignment-decision-options {" in alignment_css
    assert ".alignment-decision-option {" in alignment_css
    _assert_alignment_ready_preview_summary_layout(alignment_css)
    assert ".alignment-history-item.is-running" in alignment_css
    assert "alignmentPulse" not in alignment_css
    assert "alignmentTrace" not in alignment_css


def _assert_alignment_js_static_asset_regressions(alignment_css: str, alignment_js: str) -> None:
    assert "/api/alignments/workdir-context" in alignment_js
    assert "source_option_id" in alignment_js
    assert "alignment-decision-options" in alignment_js
    _assert_alignment_agent_review_bridge_assets(alignment_css, alignment_js)
    assert "decision_options" in alignment_js
    assert "recommended: option.recommended === true" in alignment_js
    assert "recommended: Boolean(option.recommended)" not in alignment_js
    assert "const mapped = item.mapped === true;" in alignment_js
    assert "const mapped = Boolean(item.mapped);" not in alignment_js
    assert "gatekeeper.enabled === true" in alignment_js
    assert "gatekeeper.enabled)" not in alignment_js
    assert "summary?.gatekeeper?.enabled ?" not in alignment_js
    assert 'status === "failed" && String(session.bundle_path || "").trim()' in alignment_js
    assert "allowImport: false" in alignment_js
    assert 'readyPreview.dataset.previewState = allowLinkedRun ? "linked-run" : (allowReadyRun ? "ready" : "repair");' in alignment_js
    assert 'status === "running_loop" && String(session.linked_run_id || "").trim()' in alignment_js
    assert 'importRunButton.dataset.launchAction === "open-linked-run"' in alignment_js
    assert "alignment-agent-launch-copy-cli" in alignment_js
    assert "data-agent-entry-command-value" in alignment_js
    assert "data-alignment-agent-command-copy" in alignment_js
    assert ".alignment-agent-launch-command-row" in alignment_css
    assert "Loop 已在 Agent 中运行" in alignment_js
    assert "打开当前运行" in alignment_js
    assert "readyReviewGateRequired()" in alignment_js
    assert "Confirm review before creating and running." in alignment_js
    assert "READY only means the plan passed hard validation" in alignment_js
    assert "Plan file needs repair before running" in alignment_js
    _assert_alignment_run_directory_language(alignment_js)
    _assert_ready_preview_control_summary(alignment_js)
    _assert_diagnostic_localization_contract(alignment_js)


def _assert_bundle_import_static_asset_regressions(bundle_import_js: str) -> None:
    assert "const mapped = item.mapped === true;" in bundle_import_js
    assert "const mapped = Boolean(item.mapped);" not in bundle_import_js
    assert "summary?.gatekeeper?.enabled === true" in bundle_import_js
    _assert_ready_preview_control_summary(bundle_import_js)
    assert 'label: localeText("残余风险", "Residual risk")' in bundle_import_js
    assert "listSnippet(summary.residual_risk_policy)" in bundle_import_js
    assert 'label: localeText("本地治理", "Local governance")' in bundle_import_js
    assert "listSnippet(summary.local_governance)" in bundle_import_js
    _assert_diagnostic_localization_contract(bundle_import_js)
    assert 'local_governance: localeText("本地治理", "Local governance")' in bundle_import_js
    assert "gatekeeper.enabled === true" in bundle_import_js


def _assert_diagnostic_localization_contract(script: str) -> None:
    assert "localizedDiagnosticText(item, \"title\")" in script
    assert "localizedDiagnosticText(item, \"message\")" in script
    assert 'item?.[`${field}_zh`]' in script
    assert 'item?.[`${field}_en`]' in script


def _assert_alignment_run_directory_language(script: str) -> None:
    assert "选择运行目录" in script
    assert "Choose run directory" in script
    assert "选择 workdir" not in script
    assert "运行的 workdir" not in script
    assert "This workdir has Loopora artifacts" not in script
    assert "This run directory has Loopora artifacts" in script


def _assert_ready_preview_control_summary(script: str) -> None:
    assert "renderControlSummary(summary)" in script
    assert 'label: localeText("Loopora 适配", "Loopora fit")' in script
    assert "listSnippet(summary.loop_fit_reasons)" in script
    assert 'label: localeText("成功面", "Success")' in script
    assert "listSnippet(summary.success_surface)" in script
    assert 'label: localeText("假完成", "Fake done")' in script
    assert "listSnippet(summary.fake_done_risks)" in script
    assert 'label: localeText("证据偏好", "Evidence preferences")' in script
    assert "listSnippet(summary.evidence_preferences)" in script
    assert 'label: localeText("执行策略", "Execution strategy")' in script
    assert "listSnippet(summary.execution_strategy)" in script
    assert 'label: localeText("判断取舍", "Tradeoffs")' in script
    assert "listSnippet(summary.judgment_tradeoffs)" in script
    assert 'label: localeText("角色姿态", "Role posture")' in script
    assert "listSnippet(summary.role_postures)" in script


def _assert_run_event_ok_static_regressions(client: TestClient) -> None:
    expected_snippets = {
        "/static/pages/run_detail_progress.js": ["attempt.ok = payload.ok === true;"],
        "/static/pages/run_detail_progress_activity.js": ["const ok = payload.ok === true;"],
        "/static/pages/run_detail_console.js": [
            "const ok = payload.ok === true;",
            "payload.passed === true ? \"success\" : \"system\"",
        ],
        "/static/pages/run_detail_timeline.js": ["payload.ok === true ? \"success\" : \"danger\""],
        "/static/pages/run_console.js": [
            "const ok = payload.ok === true;",
            "payload.passed === true ? \"success\" : \"system\"",
        ],
    }
    for path, snippets in expected_snippets.items():
        response = client.get(path)
        assert response.status_code == 200
        for snippet in snippets:
            assert snippet in response.text
    for path in expected_snippets:
        assert "Boolean(payload.ok)" not in client.get(path).text


def test_static_css_keeps_preview_timeline_and_mobile_nav_regressions_covered(service_factory) -> None:
    service = service_factory(scenario="success")

    client = TestClient(build_app(service=service))
    response = client.get("/static/app.css")

    assert response.status_code == 200
    css = response.text
    assert ".markdown-workbench {" in css
    assert ".timeline-event {" in css
    assert ".console-focus-shell--immersive {" in css
    assert "@keyframes runningSweep" not in css
    assert "@keyframes pulseGlow" not in css
    for page_selector in (".alignment-", ".bundle-chat-", ".workflow-editor-", ".workflow-loop-"):
        assert page_selector not in css
    _assert_alignment_static_asset_regressions(client)
    _assert_run_event_ok_static_regressions(client)
    workflow_css_response = client.get("/static/pages/workflow_editor.css")
    assert workflow_css_response.status_code == 200
    workflow_css = workflow_css_response.text
    assert ".workflow-loop-map {" in workflow_css
    assert ".workflow-editor-panel {" in workflow_css
    run_detail_css_response = client.get("/static/pages/run_detail.css")
    assert run_detail_css_response.status_code == 200
    run_detail_css = run_detail_css_response.text
    assert re.search(
        r"\.stage-loop-shell\.is-empty \.stage-loop-connector,\s*\.stage-loop-shell\.is-empty \.stage-loop-arcs\s*{[\s\S]*?display:\s*none;", run_detail_css
    )
    assert re.search(
        r"\.stage-loop-shell\.is-empty \.stage-loop-track::before,\s*\.stage-loop-shell\.is-empty \.stage-loop-steps::before,\s*\.stage-loop-shell\.is-empty \.stage-loop-steps::after\s*{[\s\S]*?display:\s*none;",
        run_detail_css,
    )
    assert "body:not(.ui-mounted)" not in css
    assert "body.ui-mounted .hero" not in css


def test_new_orchestration_script_parses_boolean_like_step_session_flags() -> None:
    script = (Path(__file__).resolve().parents[3] / "src" / "loopora" / "static" / "pages" / "new_orchestration.js").read_text(
        encoding="utf-8"
    )

    assert "function coerceWorkflowBoolean" in script
    assert '["0", "false", "no", "off"].includes(normalized)' in script
    assert "inherit_session: coerceWorkflowBoolean(step.inherit_session" in script
    assert "settingsStepInheritSessionInput.checked = coerceWorkflowBoolean(step.inherit_session, false);" in script
    assert "step.inherit_session = coerceWorkflowBoolean(rawValue, false);" in script
    assert "inherit_session: Boolean(" not in script
    assert "settingsStepInheritSessionInput.checked = Boolean(" not in script
    assert "step.inherit_session = Boolean(" not in script


def test_role_definition_script_keeps_bilingual_text_updates_safe() -> None:
    script = (Path(__file__).resolve().parents[3] / "src" / "loopora" / "static" / "pages" / "new_role_definition.js").read_text(encoding="utf-8")

    assert "function setBilingualText" in script
    assert "replaceChildren(zhNode, enNode)" in script
    assert "function setBilingualHtml" not in script
    assert "setBilingualHtml(" not in script
    assert 'innerHTML = `<span data-lang="zh"' not in script


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
    assert "data-toggle-nav-menu" in script
    assert "[data-testid='loop-grid-note']" in script
    assert "[data-testid='bundle-grid-note']" in script
    assert "Unable to delete this plan." in script
    assert "Unable to delete this bundle." not in script
    assert 'setAttribute("title", title)' not in script
    assert 'removeAttribute("title")' in script
    assert 'succeeded: "正常结束"' in script
    assert 'succeeded: "finished normally"' in script
    assert 'succeeded: "已完成"' not in script
    assert 'succeeded: "succeeded"' not in script
    assert "ui-mounted" not in script
