from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]


def _run_node(script: str) -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required for static JS module checks")
    subprocess.run([node, "-e", script], cwd=ROOT, text=True, check=True)


def test_run_detail_static_assets_keep_semantic_hooks_without_layout_contracts() -> None:
    template = (ROOT / "src" / "loopora" / "templates" / "run_detail.html").read_text(encoding="utf-8")
    renderer = (ROOT / "src" / "loopora" / "static" / "pages" / "run_detail_render.js").read_text(encoding="utf-8")
    console = (ROOT / "src" / "loopora" / "static" / "pages" / "run_detail_console.js").read_text(encoding="utf-8")
    page_script = (ROOT / "src" / "loopora" / "static" / "pages" / "run_detail.js").read_text(encoding="utf-8")

    for kind in ("target", "context", "capsule", "template", "outbox", "submit"):
        assert f'data-agent-handoff-copy="{kind}"' in template
        assert f'data-testid="agent-handoff-copy-{kind}"' in template

    for stable_marker in (
        'data-testid="agent-handoff-contract"',
        'data-testid="agent-handoff-continuation"',
        "result_file_contract",
        "known_evidence_count",
        "replace null placeholders",
        "navigator.clipboard.writeText(value)",
    ):
        assert stable_marker in template + renderer + page_script

    for verdict_marker in (
        "Task verdict",
        "not_evaluated",
        "insufficient_evidence",
        "Unproven evidence verdict recorded",
    ):
        assert verdict_marker in template + renderer + console


def test_run_detail_console_projector_preserves_core_event_semantics() -> None:
    _run_node(
        r"""
const fs = require("fs");
const vm = require("vm");
const source = fs.readFileSync("src/loopora/static/pages/run_detail_console.js", "utf8");
const context = {window: {LooporaUI: {translateStatus: (status) => `status:${status}`}}};
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

function assert(condition, message, value) {
  if (!condition) throw new Error(`${message}: ${JSON.stringify(value)}`);
}

const commandLines = projector.buildConsoleLines({
  event_type: "codex_event",
  created_at: "2026-04-30T00:00:00Z",
  role: "builder",
  payload: {type: "command", message: "uv run pytest -q"},
});
assert(commandLines.length === 1 && commandLines[0].channel === "command", "command projection failed", commandLines);

const fileLines = projector.buildConsoleLines({
  event_type: "codex_event",
  created_at: "2026-04-30T00:00:00Z",
  role: "builder",
  payload: {type: "item.completed", item: {type: "file_change", changes: [{path: "src/app.py"}]}},
});
assert(fileLines.length === 1 && fileLines[0].channel === "file", "file projection failed", fileLines);

const terminalLines = projector.buildConsoleLines({
  event_type: "run_finished",
  created_at: "2026-04-30T00:00:00Z",
  payload: {status: "succeeded", task_verdict_status: "insufficient_evidence", task_verdict_summary: "Required coverage still lacks direct evidence."},
});
assert(
  terminalLines.length === 1 &&
  terminalLines[0].tone === "warning" &&
  terminalLines[0].summary.includes("Task verdict insufficient_evidence"),
  "terminal verdict projection failed",
  terminalLines
);

const acceptedLines = projector.buildConsoleLines({
  event_type: "run_result_accepted",
  created_at: "2026-04-30T00:00:01Z",
  payload: {status: "succeeded", task_verdict_status: "insufficient_evidence"},
});
assert(
  acceptedLines.length === 1 &&
  acceptedLines[0].tone === "warning" &&
  acceptedLines[0].summary.includes("Unproven evidence verdict recorded") &&
  !acceptedLines[0].summary.includes("accepted"),
  "accepted insufficient evidence projection failed",
  acceptedLines
);
"""
    )


def test_web_orchestration_editor_keeps_parallel_review_advanced_entry() -> None:
    template = (ROOT / "src" / "loopora" / "templates" / "new_orchestration.html").read_text(encoding="utf-8")
    page_script = (ROOT / "src" / "loopora" / "static" / "pages" / "new_orchestration.js").read_text(encoding="utf-8")

    assert 'data-testid="workflow-settings-step-parallel-group"' in template
    assert 'data-step-field="parallel_group"' in template
    assert "canStepUseParallelGroup" in page_script
    assert 'field === "parallel_group"' in page_script
