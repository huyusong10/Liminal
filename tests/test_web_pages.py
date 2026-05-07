from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from loopora.bundles import bundle_to_yaml
from loopora.web import build_app


def _assert_has_testid(html: str, testid: str) -> None:
    assert f'data-testid="{testid}"' in html


def _assert_has_testids(html: str, *testids: str) -> None:
    for testid in testids:
        _assert_has_testid(html, testid)


def _assert_testids_in_order(html: str, *testids: str) -> None:
    positions = []
    for testid in testids:
        marker = f'data-testid="{testid}"'
        assert marker in html
        positions.append(html.index(marker))
    assert positions == sorted(positions)


def _assert_initial_locale(html: str, locale: str) -> None:
    lang = "zh-CN" if locale == "zh" else locale
    assert re.search(rf'<html\s+lang="{lang}"\s+data-locale="{locale}"\s+data-theme="light"\s*>', html)


def test_run_detail_page_css_owns_progress_surface_rules() -> None:
    root = Path(__file__).resolve().parents[1]
    app_css = (root / "src" / "loopora" / "static" / "app.css").read_text(encoding="utf-8")
    run_detail_css = (root / "src" / "loopora" / "static" / "pages" / "run_detail.css").read_text(encoding="utf-8")

    for selector in [".progress-live-card", ".stage-loop-shell", ".stage-chip", ".highlight-grid"]:
        assert selector not in app_css
        assert selector in run_detail_css


def test_run_detail_console_projector_maps_core_events_without_dom() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required for static JS module checks")
    root = Path(__file__).resolve().parents[1]
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
"""
    subprocess.run([node, "-e", script], cwd=root, check=True)


def test_run_detail_projectors_map_progress_timeline_and_takeaways_without_dom() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required for static JS module checks")
    root = Path(__file__).resolve().parents[1]
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
if (progress.getProgressStages(run).filter((stage) => stage.kind === "workflow_step").length !== 1) {
  throw new Error("workflow step projection missing");
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
const takeaways = context.window.LooporaRunDetailTakeaways.createTakeawayProjector({
  localeText: (_zh, en) => en,
  escapeHtml: (value) => String(value || ""),
  formatAbsoluteDate: () => "date",
});
const snapshot = {
  task_verdict: {status: "passed", summary: "ok", buckets: {proven: [{text: "done"}]}},
  evidence_coverage: {coverage_path: "evidence/coverage.json", evidence_count: 1, summary: {reason: "covered"}},
  iterations: [{iter: 0, display_iter: 1, status: "passed", role_count: 1, roles: []}],
};
if (!takeaways.evidenceOutcome(snapshot, run).title.includes("Passed")) {
  throw new Error("takeaway outcome projection failed");
}
if (!takeaways.evidenceCoverageHtml(snapshot, "run_1").includes("View trace")) {
  throw new Error("takeaway coverage html projection failed");
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
const verdictSummary = render.summarizeTaskVerdict({status: "passed", source: "gatekeeper", buckets: {proven: [{}]}});
if (!verdictSummary.title.includes("Passed") || !verdictSummary.meta.includes("proven 1")) {
  throw new Error(`render verdict projection failed: ${JSON.stringify(verdictSummary)}`);
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
    root = Path(__file__).resolve().parents[1]
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
    root = Path(__file__).resolve().parents[1]
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
  }
);
if (merged.lastEventId !== 12 || merged.timelineRecords.length !== 40 || merged.consoleEventRecords.length !== 160 || merged.progressEventRecords.length !== 2000) {
  throw new Error(`snapshot normalization failed: ${JSON.stringify(merged)}`);
}
const deduped = observation.appendUniqueEvent([{id: 1}, {id: 2}], {id: 2}, 10);
if (deduped.length !== 2) {
  throw new Error(`duplicate event was appended: ${JSON.stringify(deduped)}`);
}
const updatedRun = observation.applyRunEvent({status: "running", active_role: "generator"}, {
  event_type: "run_finished",
  created_at: "2026-04-30T00:00:00Z",
  payload: {status: "succeeded", iter: 2},
});
if (updatedRun.status !== "succeeded" || updatedRun.active_role !== null || updatedRun.current_iter !== 2) {
  throw new Error(`run event state failed: ${JSON.stringify(updatedRun)}`);
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
    root = Path(__file__).resolve().parents[1]
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
});
if (merged.lastEventId !== 7 || merged.observationState !== "ready") {
  throw new Error(`snapshot state failed: ${JSON.stringify(merged)}`);
}
const duplicate = store.applyStreamEvent({id: 7, event_type: "role_started", payload: {role: "generator"}});
if (!duplicate.duplicate || duplicate.state.lastEventId !== 7) {
  throw new Error(`duplicate stream event was not suppressed: ${JSON.stringify(duplicate)}`);
}
const applied = store.applyStreamEvent({id: 8, event_type: "run_finished", created_at: "2026-04-30T00:00:00Z", payload: {status: "succeeded"}});
if (applied.duplicate || applied.state.currentRun.status !== "succeeded" || applied.state.lastEventId !== 8) {
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


def _assert_display_bootstrap_precedes_css(html: str) -> None:
    assert "loopora:theme" in html
    assert "loopora:locale" in html
    assert html.index("loopora:theme") < html.index("/static/app.css?v=")
    assert html.index("loopora:locale") < html.index("/static/app.css?v=")


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
    assert "/logo/logo-with-text-horizontal.svg" in response.text
    _assert_initial_locale(response.text, "en")
    _assert_display_bootstrap_precedes_css(response.text)
    assert "/static/app.css?v=" in response.text
    assert "/static/app.js?v=" in response.text
    assert "/static/pages/run_detail.css?v=" not in response.text
    assert "/static/pages/orchestration.css?v=" not in response.text
    assert "/static/pages/workflow_editor.css?v=" not in response.text
    assert "/static/pages/alignment.css?v=" not in response.text
    _assert_has_testids(
        response.text,
        "top-nav",
        "nav-loops-link",
        "nav-compose-link",
        "nav-resource-menu",
        "nav-resource-toggle",
        "nav-resource-panel",
        "nav-resources-menu",
        "nav-menu-bundles-link",
        "nav-menu-roles-link",
        "nav-menu-orchestrations-link",
        "nav-tools-link",
        "nav-tutorial-link",
        "nav-display-controls",
        "nav-display-toggle",
        "nav-display-panel",
        "theme-switch",
        "theme-light-button",
        "theme-dark-button",
        "locale-switch",
        "home-workbench",
        "home-activity-section",
        "home-saved-loops-section",
    )
    assert 'class="nav-menu-caret"' in response.text
    assert 'data-testid="home-compose-primary-link"' not in response.text
    assert 'data-testid="home-compose-entry"' not in response.text
    assert 'data-testid="home-compose-workbench-link"' not in response.text
    assert 'data-testid="home-expert-create-links"' not in response.text
    assert 'data-testid="nav-runs-link"' not in response.text
    assert 'data-testid="nav-create-loop-menu"' not in response.text
    assert 'data-testid="home-alignment-form"' not in response.text
    assert 'data-testid="nav-created-link"' not in response.text
    assert 'data-testid="nav-role-definitions-link"' not in response.text
    assert 'data-testid="nav-orchestrations-link"' not in response.text
    assert 'data-testid="nav-new-task-link"' not in response.text
    assert 'data-testid="nav-plans-link"' not in response.text
    assert "方案库" not in response.text
    assert "新建任务" not in response.text
    assert "创建是低频动作" not in response.text
    assert "Loop 工作台" in response.text
    assert "对话编排 Loop" not in response.text
    assert 'href="/loops/new/bundle"' in response.text
    assert 'action="/loops/new/bundle"' not in response.text
    assert "data-open-card=" in response.text
    assert "id=\"confirm-modal\"" in response.text
    assert "id=\"loops-empty-state\" hidden" in response.text

    zh_response = client.get("/", headers={"accept-language": "zh-CN,zh;q=0.9"})
    assert zh_response.status_code == 200
    _assert_initial_locale(zh_response.text, "zh")
    _assert_has_testids(zh_response.text, "top-nav", "theme-switch", "locale-switch")


def test_index_page_shell_prefers_primary_request_locale_on_first_paint(service_factory) -> None:
    service = service_factory(scenario="success")

    client = TestClient(build_app(service=service))
    response = client.get("/", headers={"Accept-Language": "zh-CN;q=0.1,en-US;q=0.9"})

    assert response.status_code == 200
    _assert_initial_locale(response.text, "en")
    _assert_display_bootstrap_precedes_css(response.text)


def test_runs_list_redirects_to_loop_workbench_activity(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = service.create_loop(
        name="Observation Loop",
        spec_path=sample_spec_file,
        workdir=sample_workdir,
        model="gpt-5.4",
        reasoning_effort="medium",
        max_iters=2,
        max_role_retries=1,
        delta_threshold=0.005,
        trigger_window=2,
        regression_window=2,
        role_models={},
    )
    service.rerun(loop["id"])

    client = TestClient(build_app(service=service))
    response = client.get("/runs", headers={"accept-language": "zh-CN,zh;q=0.9"}, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/#activity"


def test_run_detail_places_takeaways_and_console_before_timeline(
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
    assert "/static/pages/run_detail_progress.js?v=" in response.text
    assert "/static/pages/run_detail_progress_time.js?v=" in response.text
    assert "/static/pages/run_detail_progress_activity.js?v=" in response.text
    assert "/static/pages/run_detail_observation.js?v=" in response.text
    assert "/static/pages/run_detail_state.js?v=" in response.text
    assert "/static/pages/run_detail_stream.js?v=" in response.text
    assert "/static/pages/run_detail_api.js?v=" in response.text
    assert "/static/pages/run_detail_scheduler.js?v=" in response.text
    assert "/static/pages/run_detail_timeline.js?v=" in response.text
    assert "/static/pages/run_detail_takeaways.js?v=" in response.text
    assert "/static/pages/run_detail_render.js?v=" in response.text
    assert "/static/pages/run_detail_console.js?v=" in response.text
    assert "/static/pages/run_detail.js?v=" in response.text
    assert "/static/pages/run_detail.css?v=" in response.text
    script_order = [
        "/static/pages/run_detail_console.js?v=",
        "/static/pages/run_detail_observation.js?v=",
        "/static/pages/run_detail_state.js?v=",
        "/static/pages/run_detail_stream.js?v=",
        "/static/pages/run_detail_api.js?v=",
        "/static/pages/run_detail_scheduler.js?v=",
        "/static/pages/run_detail_progress_time.js?v=",
        "/static/pages/run_detail_progress_activity.js?v=",
        "/static/pages/run_detail_progress.js?v=",
        "/static/pages/run_detail_timeline.js?v=",
        "/static/pages/run_detail_takeaways.js?v=",
        "/static/pages/run_detail_render.js?v=",
        "/static/pages/run_detail.js?v=",
    ]
    assert [response.text.index(script) for script in script_order] == sorted(
        response.text.index(script) for script in script_order
    )
    assert "window.LOOPORA_RUN_DETAIL" in response.text
    assert "timelineEvents" not in response.text
    assert "consoleEvents" not in response.text
    assert "progressEvents" not in response.text
    assert "keyTakeaways" not in response.text
    assert "latestEventId" not in response.text
    _assert_has_testid(response.text, "run-evidence-outcome")
    _assert_has_testid(response.text, "run-observation-status")
    assert 'data-observation-state="loading"' in response.text
    _assert_has_testid(response.text, "run-improve-chat-button")
    _assert_has_testid(response.text, "run-evidence-improve-button")
    assert f'/runs/{run["id"]}/revise' in response.text
    _assert_testids_in_order(
        response.text,
        "run-takeaway-panel",
        "run-progress-panel",
        "run-console-panel",
        "run-timeline-panel",
    )
    _assert_testids_in_order(response.text, "run-stage-strip", "run-progress-live-card")
    assert 'data-testid="loop-detail-spec-preview"' not in response.text
    _assert_has_testids(
        response.text,
        "run-stage-loop-shell",
        "run-progress-live-card",
        "run-console-output",
        "run-timeline-panel",
    )


def test_run_detail_collapses_empty_workflow_lane(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = service.create_loop(
        name="Empty Workflow Run",
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

    with service.repository.transaction() as connection:
        connection.execute(
            "UPDATE loop_runs SET workflow_json = ? WHERE id = ?",
            (json.dumps({"roles": [], "steps": []}, ensure_ascii=False), run["id"]),
        )

    client = TestClient(build_app(service=service))
    response = client.get(f"/runs/{run['id']}")

    assert response.status_code == 200
    assert re.search(r'data-testid="run-stage-loop-shell"[^>]*data-workflow-empty="true"', response.text)
    _assert_has_testid(response.text, "run-stage-loop-empty")
    assert 'data-stage-kind="workflow_step"' not in response.text
    _assert_has_testids(
        response.text,
        "console-popout-link",
        "console-filters",
        "console-expand-all",
        "console-collapse-all",
        "takeaway-iteration-select",
        "takeaway-iteration-view",
        "takeaway-open-build",
        "takeaway-open-logs",
    )


def test_run_detail_empty_workflow_lane_uses_request_locale_on_first_paint(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = service.create_loop(
        name="Localized Empty Workflow Run",
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

    with service.repository.transaction() as connection:
        connection.execute(
            "UPDATE loop_runs SET workflow_json = ? WHERE id = ?",
            (json.dumps({"roles": [], "steps": []}, ensure_ascii=False), run["id"]),
        )

    client = TestClient(build_app(service=service))
    response = client.get(
        f"/runs/{run['id']}",
        headers={"Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"},
    )

    assert response.status_code == 200
    _assert_initial_locale(response.text, "zh")
    assert re.search(r'data-testid="run-stage-loop-shell"[^>]*data-workflow-empty="true"', response.text)
    _assert_has_testid(response.text, "run-stage-loop-empty")


def test_run_detail_progress_stages_follow_workflow_snapshot(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = service.create_loop(
        name="Repair Flow Loop",
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
        workflow={"preset": "repair_loop"},
    )
    run = service.rerun(loop["id"])

    client = TestClient(build_app(service=service))
    response = client.get(f"/runs/{run['id']}")

    assert response.status_code == 200
    assert 'data-stage="checks"' in response.text
    assert 'data-stage="step:builder_step"' in response.text
    assert 'data-stage="step:regression_inspection_step"' in response.text
    assert 'data-stage="step:contract_inspection_step"' in response.text
    assert 'data-stage="step:guide_step"' in response.text
    assert 'data-stage="step:builder_repair_step"' in response.text
    assert 'data-stage="step:gatekeeper_step"' in response.text
    assert 'data-stage="finished"' in response.text
    _assert_has_testid(response.text, "run-stage-loop-shell")
    assert 'data-stage="generator"' not in response.text
    assert 'data-stage="tester"' not in response.text
    assert 'data-stage="verifier"' not in response.text
    assert 'data-stage="challenger"' not in response.text


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
    response = client.get(
        f"/runs/{run['id']}/console",
        headers={"Accept-Language": "zh-CN;q=0.1,en-US;q=0.9"},
    )

    assert response.status_code == 200
    _assert_initial_locale(response.text, "en")
    _assert_display_bootstrap_precedes_css(response.text)
    assert "console-focus-shell" in response.text
    assert "console-shell-immersive" in response.text
    assert "console-focus-output" in response.text
    assert "console-focus-topbar" in response.text
    assert "console-focus-back" in response.text
    assert "Fullscreen Console Loop · Console" in response.text
    assert "console-focus-filters" not in response.text
    assert "console-focus-expand-all" not in response.text
    assert "console-focus-collapse-all" not in response.text
    assert "console-focus-meta-row" not in response.text
    assert "console-focus-status" not in response.text
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
    _assert_has_testid(response.text, "loop-detail-config-panel")
    _assert_has_testid(response.text, "loop-detail-spec-panel")
    _assert_has_testid(response.text, "loop-detail-history-panel")
    _assert_has_testid(response.text, "loop-detail-summary-panel")
    assert "Original spec" in response.text
    assert "Ship the requested behavior." in response.text
    assert response.text.index("Configuration") < response.text.index("Original spec")
    assert response.text.index("Original spec") < response.text.index("Run history")
    assert response.text.index("Run history") < response.text.index("Latest summary")
    assert "summary-grid" in response.text
    assert "summary-card-status summary-card-status-" in response.text
    assert "hero-inline-meta" in response.text
    assert "loop-detail-copy" in response.text
    assert "loop-detail-spec-shell" in response.text
    _assert_has_testid(response.text, "loop-detail-spec-workbench")
    assert "loop-detail-spec-path" in response.text
    assert "loop-detail-spec-source" in response.text
    assert "loop-detail-spec-preview" in response.text
    assert "markdown-workbench-grid" in response.text
    assert "loop-detail-history-meta" in response.text
    assert "loop-detail-history-time" in response.text
    assert "artifact-copy" not in response.text
    assert "artifact-preview-shell" not in response.text
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
    assert "window.LOOPORA_RUN_DETAIL" in response.text
    assert "workspace_guard_triggered" not in response.text
    snapshot = client.get(f"/api/runs/{run['id']}/observation-snapshot")
    assert snapshot.status_code == 200
    snapshot_payload = snapshot.json()
    assert any(event["event_type"] == "workspace_guard_triggered" for event in snapshot_payload["timeline_events"])
    assert "deleted_original_count" in json.dumps(snapshot_payload, ensure_ascii=False)


def test_tools_page_renders_wake_lock_panel(service_factory) -> None:
    service = service_factory(scenario="success")

    client = TestClient(build_app(service=service))
    response = client.get("/tools")

    assert response.status_code == 200
    assert '<title>Tools</title>' in response.text
    assert "/static/pages/tools.js?v=" in response.text
    assert "handy side tools" in response.text
    assert "wake-lock-toggle" in response.text
    assert 'data-testid="local-assets-diagnostics-panel"' in response.text
    assert 'data-local-assets-count="orphan_alignment_dirs"' in response.text
    assert 'data-local-assets-count="orphan_run_dirs"' in response.text
    assert 'data-testid="local-assets-details"' in response.text
    assert "Prevent sleep while running" in response.text
    assert "help-dot--tips" in response.text
    assert 'aria-label="Show tip: The page only requests a wake lock while a run is actively executing, and releases it automatically when nothing is running. It works best while this Tools tab stays visible, and retries automatically if the browser or system releases the wake lock."' in response.text
    assert ">i</button>" in response.text
    assert "Alignment skill install" not in response.text
    assert "loopora-task-alignment" not in response.text
    assert 'data-install-skill="codex"' not in response.text
    assert "/api/skills/loopora-task-alignment/download" not in response.text

    zh_response = client.get("/tools", headers={"accept-language": "zh-CN,zh;q=0.9"})
    assert zh_response.status_code == 200
    assert '<title>工具</title>' in zh_response.text
    assert "运行辅助和本机维护" in zh_response.text
    assert "下载技能包" not in zh_response.text
    assert 'aria-label="查看提示：只会在检测到有运行正在执行时请求浏览器保持屏幕唤醒，没有运行中的 Loop 会自动释放。保持这个工具页标签可见时更稳；如果浏览器或系统回收防休眠锁，页面也会在重新可见后自动重试。"' in zh_response.text


def _assert_new_loop_choice_page(html: str) -> None:
    _assert_has_testids(
        html,
        "loop-create-page",
        "loop-create-choice-page",
        "loop-create-bundle-choice",
        "loop-create-manual-choice",
        "loop-create-bundle-link",
        "loop-create-manual-link",
    )
    assert "/static/pages/new_loop.js?v=" not in html
    assert "/static/pages/alignment.js?v=" not in html
    assert "/static/pages/workflow_editor.css?v=" in html
    assert "/static/pages/alignment.css?v=" in html
    assert 'href="/loops/new/bundle"' in html
    assert 'href="/loops/new/manual#manual-loop-form"' in html
    assert '<title>Create Loop</title>' in html


def _assert_bundle_compose_page(html: str) -> None:
    assert "/static/pages/alignment.js?v=" in html
    assert "/static/pages/workflow_diagram.js?v=" in html
    assert "/static/pages/workflow_editor.css?v=" in html
    assert "/static/pages/alignment.css?v=" in html
    assert "/static/pages/new_loop.js?v=" not in html
    _assert_has_testids(
        html,
        "loop-create-page",
        "alignment-history-panel",
        "loop-compose-shell",
        "alignment-secondary-paths",
        "alignment-path-chat",
        "alignment-path-import",
        "alignment-path-manual",
        "alignment-history-list",
        "loop-alignment-panel",
        "alignment-scroll-region",
        "alignment-empty-state",
        "alignment-start-form",
        "alignment-tools-menu",
        "alignment-tools-close",
        "alignment-workdir-panel",
        "alignment-advanced-panel",
        "alignment-executor-kind",
        "alignment-executor-mode-switch",
        "alignment-mode-preset-button",
        "alignment-mode-command-button",
        "alignment-executor-mode-input",
        "alignment-message-input",
        "alignment-chat",
        "alignment-thinking-status",
        "alignment-live-details",
        "alignment-live-summary-meta",
        "alignment-ready-preview",
        "alignment-artifact-stage",
        "alignment-artifact-summary",
        "alignment-judgment-map",
        "alignment-diagnostics-strip",
        "alignment-preview-tabs",
        "alignment-preview-tab-spec",
        "alignment-preview-tab-roles",
        "alignment-workflow-diagram",
        "alignment-import-run-button",
        "alignment-source-open-button",
        "alignment-source-sync-button",
    )
    for artifact_anchor in (
        'id="alignment-artifact-risk"',
        'id="alignment-artifact-evidence"',
        'id="alignment-artifact-judgment"',
        'id="alignment-artifact-verdict"',
        'id="alignment-artifact-workdir"',
    ):
        assert artifact_anchor in html
    for removed_surface in (
        'data-testid="alignment-preview-tab-yaml"',
        'data-testid="alignment-import-open-button"',
        'data-testid="alignment-import-panel"',
        'data-testid="nav-create-loop-menu"',
        'data-testid="loop-bundle-import-form"',
        'data-testid="alignment-advanced-chip"',
        'action="/loops/new/bundle/import-bundle"',
        'name="bundle_yaml"',
    ):
        assert removed_surface not in html
    assert 'data-compose-mode="bundle"' in html
    assert 'placeholder="Leave blank for Codex CLI default"' in html
    assert "{resume_session_id}" in html
    assert '<title>Loop Composer</title>' in html


def _assert_prefilled_bundle_compose_page(html: str) -> None:
    assert ">Advance this Loop</textarea>" in html
    assert 'value="/tmp/loopora-demo"' in html


def _assert_manual_compose_page(html: str) -> None:
    assert "/static/pages/new_loop.js?v=" in html
    assert "/static/markdown_workbench.js?v=" in html
    assert "/static/pages/bundle_import.js?v=" in html
    assert "/static/pages/alignment.js?v=" not in html
    _assert_has_testids(
        html,
        "loop-compose-shell",
        "alignment-history-panel",
        "alignment-secondary-paths",
        "alignment-path-chat",
        "alignment-path-import",
        "alignment-path-manual",
        "alignment-history-list",
        "loop-manual-compose-panel",
        "compose-mode-scroll",
        "manual-compose-section",
        "manual-bundle-import-panel",
        "loop-bundle-import-form",
        "bundle-preview-button",
        "bundle-preview-import-button",
        "alignment-judgment-map",
        "alignment-diagnostics-strip",
        "alignment-source-open-button",
        "loop-create-form",
        "nav-menu-orchestrations-link",
        "nav-menu-roles-link",
        "workdir-browse-button",
        "spec-editor-button",
        "spec-template-button",
        "spec-editor-modal",
        "spec-editor-preview-toggle-button",
        "save-spec-document-button",
        "spec-editor-validation-pill",
        "spec-editor-workbench",
        "loop-orchestration-input",
        "loop-completion-mode-input",
        "loop-completion-mode-field",
        "loop-trigger-window-field",
        "loop-regression-window-field",
        "loop-iteration-interval-input",
        "loop-orchestration-panel-tip",
        "loop-completion-mode-tip",
        "loop-trigger-window-tip",
        "loop-regression-window-tip",
    )
    assert 'data-compose-mode="manual"' in html
    assert 'data-compose-mode-section="import"' in html
    assert re.search(r'data-compose-mode-section="import"[^>]*hidden', html)
    assert 'data-compose-mode-section="manual"' in html
    assert 'data-testid="alignment-preview-tab-yaml"' not in html
    assert "name=\"executor_kind\"" not in html
    assert "name=\"executor_mode\"" not in html
    assert "name=\"orchestration_id\"" in html
    assert "name=\"completion_mode\"" in html
    assert 'action="/loops/new/manual/import-bundle"' in html
    assert 'name="bundle_yaml"' in html
    assert 'name="replace_bundle_id"' in html
    assert "name=\"iteration_interval_seconds\"" in html
    for spec_editor_marker in (
        "id=\"edit-spec\"",
        "id=\"toggle-spec-preview\"",
        "id=\"spec-editor-input\"",
        "id=\"spec-preview-content\"",
    ):
        assert spec_editor_marker in html
    for present_text in (
        "Spec editor",
        "Generate from orchestration",
        "Manual Expert Mode",
        'class="panel-header workflow-editor-header"',
        'class="card-actions card-actions-compact"',
        '<title>Create Loop Manually</title>',
        'data-label-zh="守门裁决"',
        ">GateKeeper</option>",
        ">Rounds</option>",
        'aria-label="Show tip:',
        "角色定义",
    ):
        assert present_text in html
    for removed_text in (
        "Role runtime reminder",
        "Spec reminder",
        "Extra tools",
        'data-testid="loop-spec-practice-hint"',
        "workflow-json-input",
    ):
        assert removed_text not in html


def _assert_zh_manual_compose_page(html: str) -> None:
    assert '<title>手动编排 Loop</title>' in html
    assert "手动编排" in html
    assert 'aria-label="查看提示：' in html
    zh_completion_mode = html.split('id="completion-mode-input"', 1)[1].split("</select>", 1)[0]
    assert ">守门裁决</option>" in zh_completion_mode
    assert ">轮次推进</option>" in zh_completion_mode
    assert ">GateKeeper</option>" not in zh_completion_mode
    assert ">Rounds</option>" not in zh_completion_mode


def test_new_loop_page_uses_page_scoped_script(service_factory) -> None:
    service = service_factory(scenario="success")

    client = TestClient(build_app(service=service))
    response = client.get("/loops/new")

    assert response.status_code == 200
    _assert_new_loop_choice_page(response.text)

    bundle_response = client.get("/loops/new/bundle")
    assert bundle_response.status_code == 200
    _assert_bundle_compose_page(bundle_response.text)

    prefilled_bundle_response = client.get(
        "/loops/new/bundle?alignment_message=Advance%20this%20Loop&alignment_workdir=%2Ftmp%2Floopora-demo"
    )
    assert prefilled_bundle_response.status_code == 200
    _assert_prefilled_bundle_compose_page(prefilled_bundle_response.text)

    manual_response = client.get("/loops/new/manual")
    assert manual_response.status_code == 200
    _assert_manual_compose_page(manual_response.text)

    zh_response = client.get("/loops/new/manual", headers={"accept-language": "zh-CN,zh;q=0.9"})
    assert zh_response.status_code == 200
    _assert_zh_manual_compose_page(zh_response.text)


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
    response = client.get("/loops/new/manual")

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
        "/loops/new/manual"
        "?orchestration_id=builtin:build_then_parallel_review"
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
    response = client.get("/loops/new/manual?workdir=/tmp/demo")

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

    before_delete = client.get("/loops/new/manual")
    assert before_delete.status_code == 200
    assert f'data-fill-workdir="{sample_workdir}"' in before_delete.text
    assert f'data-fill-workdir="{second_workdir}"' in before_delete.text

    delete_response = client.delete(f"/api/loops/{deleted_loop['id']}")
    assert delete_response.status_code == 200

    after_delete = client.get("/loops/new/manual")
    assert after_delete.status_code == 200
    assert f'data-fill-workdir="{sample_workdir}"' not in after_delete.text
    assert f'data-fill-workdir="{second_workdir}"' in after_delete.text


def _assert_orchestrations_list_page(html: str) -> None:
    _assert_has_testids(
        html,
        "orchestrations-page",
        "orchestrations-intro-copy",
        "nav-menu-orchestrations-link",
        "custom-orchestrations-list",
        "builtin-orchestrations-list",
        "builtin-orchestrations-tip",
        "builtin-orchestration-scenario",
        "orchestration-loop-diagram",
    )
    for expected in (
        '<title>Orchestrations</title>',
        "Orchestrations",
        'data-open-card="/orchestrations/builtin:build_then_parallel_review/edit"',
        'class="page-stack page-stack--catalog"',
        "/static/pages/workflow_editor.css?v=",
        "/static/pages/workflow_diagram.js?v=",
        "/static/pages/orchestrations.js?v=",
        "适用场景",
        'class="loop-card-link"',
        'class="card-actions card-actions-compact"',
        'tabindex="-1"',
        'aria-hidden="true"',
        'aria-label="Show tip: Built-in starters are read-only.',
    ):
        assert expected in html
    for removed in (
        "Create loop",
        "点进去可以查看结构，并从这个预设派生一个新的自定义编排。",
        'data-testid="builtin-orchestration-spec-practice-summary"',
        'data-testid="builtin-orchestration-spec-practice-link"',
        "Fast Lane",
        "Quality Gate",
    ):
        assert removed not in html
    assert html.count('data-testid="builtin-orchestrations-tip"') == 1
    custom_section = re.search(r'<section class="panel" data-testid="custom-orchestrations-list">(.*?)</section>', html, re.S)
    assert custom_section is not None
    assert "loop-card-glance--scenario" not in custom_section.group(1)
    assert "适用场景" not in custom_section.group(1)


def _assert_zh_orchestrations_list_page(html: str) -> None:
    assert '<title>流程编排</title>' in html
    assert 'aria-label="查看提示：内置预设本身是只读的；打开后可以查看结构，并从这个默认流程派生一个新的自定义编排。"' in html


def _assert_new_orchestration_page(html: str) -> None:
    for expected in (
        "/static/pages/new_orchestration.js?v=",
        "/static/pages/workflow_diagram.js?v=",
        "/static/pages/workflow_editor.css?v=",
        "/static/pages/orchestration.css?v=",
        'class="panel-header workflow-editor-header workflow-editor-header-tight"',
        'class="workflow-editor-section workflow-map-panel"',
        'class="workflow-editor-section workflow-steps-panel"',
        'class="workflow-toolbar workflow-toolbar-compact"',
        "role-definitions-json",
        '<title>Save orchestration</title>',
        'data-label-zh="空白开始"',
    ):
        assert expected in html
    _assert_has_testids(
        html,
        "orchestration-editor-page",
        "orchestration-editor-form",
        "workflow-starter-select",
        "load-workflow-starter-button",
        "workflow-json-input",
        "prompt-files-json-input",
        "role-definition-select",
        "add-step-button",
        "workflow-steps-list",
        "workflow-loop-preview-panel",
        "workflow-loop-preview",
        "workflow-step-settings-modal",
        "save-orchestration-button",
        "workflow-settings-role-name",
        "workflow-settings-step-inherit-session",
        "workflow-settings-step-extra-cli-args",
    )
    for removed in (
        "data-role-field=",
        'data-testid="workflow-settings-step-enabled"',
        'data-testid="workflow-role-inspector-panel"',
        'data-testid="workflow-role-inspector"',
        'data-testid="workflow-preset-input"',
        'data-testid="workflow-roles-list"',
        'option value="build_then_parallel_review" selected',
        "空白开始 / Start blank",
    ):
        assert removed not in html


def _assert_zh_new_orchestration_page(html: str) -> None:
    assert '<title>保存编排</title>' in html
    assert 'data-label-zh="空白开始"' in html
    assert ">空白开始</option>" in html
    assert 'data-label-zh="构建后并行检视"' in html
    assert "构建后并行检视" in html
    assert "空白开始 / Start blank" not in html
    assert "构建后并行检视 / Build + Parallel Review" not in html
    zh_on_pass_markup = html.split('id="workflow-settings-step-on-pass"', 1)[1].split("</select>", 1)[0]
    assert ">继续后续步骤</option>" in zh_on_pass_markup
    assert ">通过后结束流程</option>" in zh_on_pass_markup
    assert ">Continue</option>" not in zh_on_pass_markup
    assert ">Finish run</option>" not in zh_on_pass_markup


def _assert_builtin_orchestration_edit_page(html: str) -> None:
    for expected in (
        "默认编排是固定的",
        'data-readonly="true"',
        'name="name" value="Build + Parallel Review" required readonly',
        'id="workflow-starter-select" data-testid="workflow-starter-select" disabled',
        "/orchestrations/new?workflow_preset=build_then_parallel_review",
        "Real scenario example",
        "two independent evidence views",
        "Build the first inspectable result",
        "# Task",
    ):
        assert expected in html
    _assert_has_testids(
        html,
        "orchestration-editor-form",
        "open-orchestration-spec-practice-modal-button",
        "orchestration-spec-practice-modal",
        "orchestration-spec-practice-preview-shell",
        "orchestration-spec-practice-preview",
    )
    assert 'id="save-orchestration-button"' not in html
    assert 'data-testid="orchestration-spec-practice-curated"' not in html
    assert 'data-testid="orchestration-spec-practice-template-workbench"' not in html


def _assert_custom_orchestration_edit_page(html: str, orchestration_id: str) -> None:
    _assert_has_testids(
        html,
        "orchestration-editor-form",
        "open-orchestration-spec-practice-modal-button",
        "orchestration-spec-practice-modal",
        "orchestration-spec-practice-preview-shell",
        "orchestration-spec-practice-preview",
    )
    assert f'action="/orchestrations/{orchestration_id}/edit"' in html
    assert 'data-readonly="false"' in html
    assert 'data-testid="orchestration-spec-practice-curated"' not in html
    assert 'data-testid="orchestration-spec-practice-template-workbench"' not in html


def test_orchestrations_pages_render_as_resource_library_feature(service_factory) -> None:
    service = service_factory(scenario="success")
    service.create_orchestration(name="Release Flow", workflow={"preset": "inspect_first"})

    client = TestClient(build_app(service=service))
    list_response = client.get("/orchestrations")
    assert list_response.status_code == 200
    _assert_orchestrations_list_page(list_response.text)

    zh_list_response = client.get("/orchestrations", headers={"accept-language": "zh-CN,zh;q=0.9"})
    assert zh_list_response.status_code == 200
    _assert_zh_orchestrations_list_page(zh_list_response.text)

    new_response = client.get("/orchestrations/new")
    assert new_response.status_code == 200
    _assert_new_orchestration_page(new_response.text)

    zh_new_response = client.get("/orchestrations/new", headers={"accept-language": "zh-CN,zh;q=0.9"})
    assert zh_new_response.status_code == 200
    _assert_zh_new_orchestration_page(zh_new_response.text)

    builtin_edit_response = client.get("/orchestrations/builtin:build_then_parallel_review/edit")
    assert builtin_edit_response.status_code == 200
    _assert_builtin_orchestration_edit_page(builtin_edit_response.text)

    orchestration = service.create_orchestration(name="Custom", workflow={"preset": "inspect_first"})
    custom_edit_response = client.get(f"/orchestrations/{orchestration['id']}/edit")
    assert custom_edit_response.status_code == 200
    _assert_custom_orchestration_edit_page(custom_edit_response.text, orchestration["id"])


def _create_release_builder_role(service) -> None:
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


def _assert_role_definitions_list_page(html: str) -> None:
    _assert_has_testids(
        html,
        "role-definitions-page",
        "role-definitions-intro-copy",
        "create-role-definition-link",
        "role-definitions-list",
        "builtin-role-templates-list",
        "builtin-role-templates-tip",
        "gatekeeper-role-tip",
    )
    for expected in (
        '<title>Role Definitions</title>',
        "Role Definitions",
        "Release Builder",
        "/roles/new",
        'data-role-definition-id="',
        "Saved custom roles",
        "Built-in role templates",
        "Built-in template",
        'class="page-stack page-stack--catalog"',
        'class="loop-grid role-card-grid role-card-grid--definitions"',
        'class="loop-card-link"',
        'class="card-actions card-actions-compact"',
        'tabindex="-1"',
        'aria-hidden="true"',
        'aria-label="Show tip: Built-in templates are read-only.',
        'aria-label="Show tip:',
        "GateKeeper uses that evidence to make the final pass/fail call",
    ):
        assert expected in html
    assert "Built-in template · builder" not in html
    assert "点进去会以这个模板为基础，派生一个新的团队角色版本。" not in html
    assert html.count('data-testid="builtin-role-templates-tip"') == 1
    assert html.count('data-testid="gatekeeper-role-tip"') == 1


def _assert_zh_role_definitions_list_page(html: str) -> None:
    assert '<title>角色定义</title>' in html
    assert 'aria-label="查看提示：内置模板本身是只读的；打开后会以它为基础派生一个新的团队角色版本，而不是直接修改默认模板。"' in html
    assert 'aria-label="查看提示：' in html


def _assert_new_role_definition_page(html: str) -> None:
    _assert_has_testids(
        html,
        "role-definition-editor-page",
        "role-definition-editor-form",
        "role-definition-executor-kind-input",
        "role-definition-executor-mode-input",
        "role-definition-executor-mode-switch",
        "role-definition-mode-preset-button",
        "role-definition-mode-command-button",
        "role-definition-model-input",
        "role-definition-reasoning-input",
        "role-definition-command-cli-input",
        "role-definition-command-args-input",
        "role-definition-command-preview",
        "role-definition-prompt-workbench",
        "role-definition-posture-notes-input",
        "role-definition-prompt-markdown-input",
        "role-definition-prompt-markdown-preview",
        "role-definition-archetype-guide",
        "save-role-definition-button",
    )
    for expected in (
        'class="panel-header workflow-editor-header role-execution-header"',
        'class="executor-config-grid"',
        "/static/markdown_workbench.js?v=",
        "Final command preview",
        "Custom Command",
        "Pushes the implementation forward",
        "Use it where the workflow needs actual workspace edits",
        '<title>Save role</title>',
        'aria-label="Execution mode switch"',
        'id="role-definition-archetype-summary">',
        '<span data-lang="zh">直接推进实现，适合把 Loop 契约和交接记录落成真实代码与文件改动。</span>',
        '<span data-lang="en">Pushes the implementation forward and turns specs plus handoffs into real code changes.</span>',
        "task-scoped collaboration posture",
    ):
        assert expected in html
    assert "Prompt file name" not in html
    assert "巡检者 / Inspector" not in html


def _assert_zh_new_role_definition_page(html: str) -> None:
    for expected in (
        '<title>保存角色</title>',
        'aria-label="执行模式切换"',
        "直接推进实现",
        'data-label-zh="构建者"',
        ">构建者</option>",
        'data-label-zh="巡检者"',
        "你是 Loopora 内部的 Builder",
    ):
        assert expected in html


def _assert_role_definition_edit_pages(client: TestClient, service) -> None:
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


def test_role_definitions_pages_render_as_top_level_feature(service_factory) -> None:
    service = service_factory(scenario="success")
    _create_release_builder_role(service)

    client = TestClient(build_app(service=service))
    list_response = client.get("/roles")
    assert list_response.status_code == 200
    _assert_role_definitions_list_page(list_response.text)

    zh_list_response = client.get("/roles", headers={"accept-language": "zh-CN,zh;q=0.9"})
    assert zh_list_response.status_code == 200
    _assert_zh_role_definitions_list_page(zh_list_response.text)

    new_response = client.get("/roles/new")
    assert new_response.status_code == 200
    _assert_new_role_definition_page(new_response.text)

    zh_response = client.get("/roles/new", headers={"accept-language": "zh-CN,zh;q=0.9"})
    assert zh_response.status_code == 200
    _assert_zh_new_role_definition_page(zh_response.text)
    _assert_role_definition_edit_pages(client, service)


def _import_web_bundle(service, sample_spec_file: Path, sample_workdir: Path) -> dict:
    loop = service.create_loop(
        name="Bundle Page Loop",
        spec_path=sample_spec_file,
        workdir=sample_workdir,
        model="gpt-5.4-mini",
        reasoning_effort="medium",
        max_iters=2,
        max_role_retries=1,
        delta_threshold=0.005,
        trigger_window=2,
        regression_window=2,
        role_models={},
    )
    return service.import_bundle_text(
        bundle_to_yaml(
            service.derive_bundle_from_loop(
                loop["id"],
                name="Web Bundle",
                description="Bundle detail page test.",
                collaboration_summary="Prefer evidence and visible proof.",
            )
        )
    )


def _assert_bundles_list_page(html: str) -> None:
    _assert_has_testids(html, "bundles-page", "bundles-create-loop-link", "bundle-derive-form", "bundle-list", "bundle-count")
    assert 'data-testid="nav-plans-link"' not in html
    assert not re.search(r'<a class="top-nav-link\s+active" href="/loops/new/bundle" data-testid="nav-new-task-link"', html)
    for expected in (
        "Imported Plans",
        "Plan Packages",
        "Web Bundle",
        'data-delete-bundle="',
        "/api/bundles/",
        'id="bundle-grid"',
    ):
        assert expected in html
    assert 'data-testid="bundle-import-form"' not in html
    assert 'action="/bundles/import"' not in html


def _assert_bundle_detail_page(html: str, bundle_id: str) -> None:
    _assert_has_testids(
        html,
        "bundle-detail-page",
        "bundle-detail-form",
        "bundle-spec-preview",
        "bundle-yaml-preview",
        "bundle-replace-yaml-link",
        "bundle-improve-chat-button",
    )
    for expected in (
        "Web Bundle",
        "Prefer evidence and visible proof.",
        f"/bundles/{bundle_id}/edit",
        f"/bundles/{bundle_id}/revise",
        f"/api/bundles/{bundle_id}/export",
        f"?return_to=/bundles/{bundle_id}",
        f"/loops/new/manual?replace_bundle_id={bundle_id}#bundle-import-form",
        "Current plan source",
        "Expert details: source file and YAML",
        "bundle-surface-grid",
        "bundle-surface-card--wide",
    ):
        assert expected in html
    assert 'style="margin-top: 1rem;"' not in html


def _assert_bundle_revision_routes(client: TestClient, bundle_id: str) -> None:
    revision_target_response = client.get(f"/loops/new?replace_bundle_id={bundle_id}", follow_redirects=False)
    assert revision_target_response.status_code == 303
    assert revision_target_response.headers["location"] == f"/loops/new/manual?replace_bundle_id={bundle_id}#bundle-import-form"

    revision_target_page = client.get(f"/loops/new/manual?replace_bundle_id={bundle_id}")
    assert revision_target_page.status_code == 200
    _assert_has_testid(revision_target_page.text, "bundle-replace-target-note")

    legacy_revision_response = client.get(f"/bundles?replace_bundle_id={bundle_id}", follow_redirects=False)
    assert legacy_revision_response.status_code == 303
    assert legacy_revision_response.headers["location"] == f"/loops/new/manual?replace_bundle_id={bundle_id}#bundle-import-form"

    encoded_revision_response = client.get("/bundles?replace_bundle_id=bundle%26revision%3D2", follow_redirects=False)
    assert encoded_revision_response.status_code == 303
    assert encoded_revision_response.headers["location"] == "/loops/new/manual?replace_bundle_id=bundle%26revision%3D2#bundle-import-form"


def test_new_loop_compat_redirects_strip_auth_token_from_forwarded_query(service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service, bind_host="0.0.0.0", auth_token="secret-token"))

    response = client.get("/loops/new?token=secret-token&workdir=/tmp/demo", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/loops/new/manual?workdir=%2Ftmp%2Fdemo#manual-loop-form"
    assert "secret-token" not in response.headers["location"]
    assert client.cookies.get("loopora_auth") == "secret-token"


def test_bundles_pages_render_list_and_detail(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    imported = _import_web_bundle(service, sample_spec_file, sample_workdir)

    client = TestClient(build_app(service=service))

    list_response = client.get("/bundles")
    assert list_response.status_code == 200
    _assert_bundles_list_page(list_response.text)

    detail_response = client.get(f"/bundles/{imported['id']}")
    assert detail_response.status_code == 200
    _assert_bundle_detail_page(detail_response.text, imported["id"])
    _assert_bundle_revision_routes(client, imported["id"])


def test_bundle_detail_page_tolerates_unreadable_spec_file(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    imported = _import_web_bundle(service, sample_spec_file, sample_workdir)
    service._bundle_spec_path(imported["id"]).write_bytes(b"\xff")
    client = TestClient(build_app(service=service))

    response = client.get(f"/bundles/{imported['id']}")

    assert response.status_code == 200
    _assert_has_testid(response.text, "bundle-detail-page")
    assert "bundle spec file could not be read" in response.text


def test_index_page_uses_bundle_delete_for_bundle_managed_loops(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = service.create_loop(
        name="Bundle Owned Source",
        spec_path=sample_spec_file,
        workdir=sample_workdir,
        model="gpt-5.4-mini",
        reasoning_effort="medium",
        max_iters=2,
        max_role_retries=1,
        delta_threshold=0.005,
        trigger_window=2,
        regression_window=2,
        role_models={},
    )
    imported = service.import_bundle_text(
        bundle_to_yaml(
            service.derive_bundle_from_loop(
                loop["id"],
                name="Managed Bundle",
                description="Managed loop test.",
                collaboration_summary="Bundle-managed loop should delete through bundle lifecycle.",
            )
        )
    )

    client = TestClient(build_app(service=service))
    response = client.get("/")

    assert response.status_code == 200
    assert f'data-delete-bundle="{imported["id"]}"' in response.text
    assert 'Delete Plan' in response.text
    assert "managed by plan" in response.text
    zh_response = client.get("/", headers={"accept-language": "zh-CN,zh;q=0.9"})
    assert "删除方案包" in zh_response.text
    assert "这条 Loop 由方案包" in zh_response.text


def _assert_tutorial_page(html: str) -> None:
    assert '<title>Tutorial</title>' in html
    _assert_has_testids(
        html,
        "tutorial-page",
        "nav-tutorial-link",
        "tutorial-guide-panel",
        "tutorial-core-spec",
        "tutorial-core-workflow",
        "tutorial-core-bundle",
        "tutorial-core-loop",
        "tutorial-decision-tree-panel",
        "tutorial-workflow-scenarios-panel",
        "tutorial-actions-panel",
        "tutorial-decision-tree-canvas",
        "tutorial-decision-tree-kicker",
        "tutorial-decision-tree-primary-question",
        "tutorial-decision-tree-secondary-question",
        "tutorial-decision-tree-flow-stack",
        "tutorial-decision-tree-stop-card",
        "tutorial-spec-practice-modal",
        "tutorial-spec-practice-preview",
    )
    for expected in (
        'class="page-stack tutorial-page-stack"',
        "human-shaped loop",
        "task-scoped judgment",
        "Build + Parallel Review",
        "Evidence First",
        "Benchmark Gate",
        "Repair Loop",
        'data-open-tutorial-spec-practice="builtin:build_then_parallel_review"',
        'data-open-tutorial-spec-practice="builtin:evidence_first"',
        'id="tutorial-spec-practices-json"',
        "/static/pages/tutorial.js?v=",
        "/tools",
        "/orchestrations",
        "/loops/new/bundle",
        "/loops/new/manual",
        "Generate Loop Plan",
        "Manual Expert Mode",
    ):
        assert expected in html
    for removed in (
        "Build First",
        "Inspect First",
        "Triage First",
        "Benchmark Loop",
        "Fast Lane",
        "Quality Gate",
        "tutorial-decision-tree-copy",
        "tutorial-decision-tree-image",
        'data-testid="tutorial-context-flow-panel"',
        'data-testid="tutorial-flow-examples-panel"',
    ):
        assert removed not in html


def _assert_zh_tutorial_page(html: str) -> None:
    _assert_initial_locale(html, "zh")
    _assert_has_testid(html, "tutorial-page")


def test_tutorial_page_is_available_from_top_navigation(service_factory) -> None:
    service = service_factory(scenario="success")

    client = TestClient(build_app(service=service))
    response = client.get("/tutorial")

    assert response.status_code == 200
    _assert_tutorial_page(response.text)

    zh_response = client.get("/tutorial", headers={"accept-language": "zh-CN,zh;q=0.9"})
    assert zh_response.status_code == 200
    _assert_zh_tutorial_page(zh_response.text)


def test_new_loop_page_remote_mode_explains_server_side_paths(service_factory) -> None:
    service = service_factory(scenario="success")

    client = TestClient(build_app(service=service, bind_host="0.0.0.0", auth_token="secret-token"))
    response = client.get("/loops/new/manual?token=secret-token")

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
    assert ".markdown-workbench {" in css
    assert ".timeline-event {" in css
    assert ".console-focus-shell--immersive {" in css
    assert "@keyframes runningSweep" not in css
    assert "@keyframes pulseGlow" not in css
    for page_selector in (".alignment-", ".bundle-chat-", ".workflow-editor-", ".workflow-loop-"):
        assert page_selector not in css
    alignment_css_response = client.get("/static/pages/alignment.css")
    assert alignment_css_response.status_code == 200
    alignment_css = alignment_css_response.text
    assert ".alignment-chat {" in alignment_css
    assert ".bundle-chat-shell {" in alignment_css
    assert ".alignment-working-card {" in alignment_css
    assert ".alignment-history-item.is-running" in alignment_css
    workflow_css_response = client.get("/static/pages/workflow_editor.css")
    assert workflow_css_response.status_code == 200
    workflow_css = workflow_css_response.text
    assert ".workflow-loop-map {" in workflow_css
    assert ".workflow-editor-panel {" in workflow_css
    run_detail_css_response = client.get("/static/pages/run_detail.css")
    assert run_detail_css_response.status_code == 200
    run_detail_css = run_detail_css_response.text
    assert re.search(r"\.stage-loop-shell\.is-empty \.stage-loop-connector,\s*\.stage-loop-shell\.is-empty \.stage-loop-arcs\s*{[\s\S]*?display:\s*none;", run_detail_css)
    assert re.search(r"\.stage-loop-shell\.is-empty \.stage-loop-track::before,\s*\.stage-loop-shell\.is-empty \.stage-loop-steps::before,\s*\.stage-loop-shell\.is-empty \.stage-loop-steps::after\s*{[\s\S]*?display:\s*none;", run_detail_css)
    assert "body:not(.ui-mounted)" not in css
    assert "body.ui-mounted .hero" not in css


def test_role_definition_script_keeps_bilingual_text_updates_safe() -> None:
    script = (Path(__file__).resolve().parents[1] / "src" / "loopora" / "static" / "pages" / "new_role_definition.js").read_text(encoding="utf-8")

    assert "function setBilingualText" in script
    assert "replaceChildren(zhNode, enNode)" in script
    assert "function setBilingualHtml" not in script
    assert "setBilingualHtml(" not in script
    assert "innerHTML = `<span data-lang=\"zh\"" not in script


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
    assert "Unable to delete this bundle." in script
    assert 'setAttribute("title", title)' not in script
    assert 'removeAttribute("title")' in script
    assert "ui-mounted" not in script
