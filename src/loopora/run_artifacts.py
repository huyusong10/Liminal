from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from loopora.utils import append_jsonl, ensure_parent, write_json

RUN_ARTIFACT_SPECS = (
    {
        "id": "summary",
        "relative_path": "summary.md",
        "label_zh": "运行摘要",
        "label_en": "Summary",
        "description_zh": "当前 run 的摘要结论。",
        "description_en": "The current run summary.",
    },
    {
        "id": "original-spec",
        "relative_path": "contract/spec.md",
        "label_zh": "原始 Spec",
        "label_en": "Original spec",
        "description_zh": "这次 run 开始时冻结保存的原始 Markdown spec。",
        "description_en": "The original Markdown spec snapshot frozen at the start of this run.",
    },
    {
        "id": "compiled-spec",
        "relative_path": "contract/compiled_spec.json",
        "label_zh": "编译后 Spec",
        "label_en": "Compiled spec",
        "description_zh": "本次 run 实际使用的 Task、checks、Guardrails 和 role notes。",
        "description_en": "The Task, checks, Guardrails, and role notes used by this run.",
    },
    {
        "id": "workflow-manifest",
        "relative_path": "contract/workflow.json",
        "label_zh": "工作流清单",
        "label_en": "Workflow manifest",
        "description_zh": "这次 run 冻结下来的 workflow 定义。",
        "description_en": "The workflow definition frozen for this run.",
    },
    {
        "id": "run-contract",
        "relative_path": "contract/run_contract.json",
        "label_zh": "运行契约",
        "label_en": "Run contract",
        "description_zh": "本次 run 冻结的完整运行时契约与稳定引用。",
        "description_en": "The frozen runtime contract and stable references for this run.",
    },
    {
        "id": "latest-state",
        "relative_path": "context/latest_state.json",
        "label_zh": "最新状态索引",
        "label_en": "Latest state",
        "description_zh": "当前 run 的最新 step、role 和轮次引用索引。",
        "description_en": "The latest step, role, and iteration references for this run.",
    },
    {
        "id": "latest-iteration-summary",
        "relative_path": "context/latest_iteration_summary.json",
        "label_zh": "最新轮次摘要",
        "label_en": "Latest iteration summary",
        "description_zh": "最近一轮的结构化摘要与得分信息。",
        "description_en": "The latest iteration summary and score details.",
    },
    {
        "id": "timeline-events",
        "relative_path": "timeline/events.jsonl",
        "label_zh": "事件时间线",
        "label_en": "Timeline events",
        "description_zh": "run 事件流的 canonical 时间线。",
        "description_en": "The canonical event timeline for this run.",
    },
    {
        "id": "timeline-iterations",
        "relative_path": "timeline/iterations.jsonl",
        "label_zh": "轮次时间线",
        "label_en": "Timeline iterations",
        "description_zh": "每轮结构化摘要的 canonical 时间线。",
        "description_en": "The canonical iteration summary timeline for this run.",
    },
    {
        "id": "timeline-metrics",
        "relative_path": "timeline/metrics.jsonl",
        "label_zh": "指标时间线",
        "label_en": "Timeline metrics",
        "description_zh": "每轮分数与停滞信息的 canonical 时间线。",
        "description_en": "The canonical metric timeline for this run.",
    },
    {
        "id": "evidence-ledger",
        "relative_path": "evidence/ledger.jsonl",
        "label_zh": "证据账本",
        "label_en": "Evidence ledger",
        "description_zh": "本次 run 的 canonical 证据账本，记录证明了什么、没证明什么，以及结论对应的 artifact。",
        "description_en": "The canonical evidence ledger for this run: what was proven, what remains unproven, and which artifacts support each claim.",
    },
)

STEP_ARTIFACT_FILENAMES = {
    "input.context.json",
    "prompt.md",
    "output.raw.json",
    "output.normalized.json",
    "handoff.json",
    "metadata.json",
}

INITIAL_STAGNATION_STATE = {
    "stagnation_mode": "none",
    "recent_composites": [],
    "recent_deltas": [],
    "consecutive_low_delta": 0,
}

INITIAL_LATEST_STATE = {
    "latest_iteration": None,
    "latest_by_step": {},
    "latest_by_role": {},
    "latest_by_archetype": {},
    "latest_gatekeeper": None,
    "latest_summary_path": "",
}


@dataclass(frozen=True)
class RunArtifactLayout:
    run_dir: Path

    @property
    def workdir_path(self) -> Path:
        try:
            return self.run_dir.parents[2]
        except IndexError:
            return self.run_dir.parent

    @property
    def summary_path(self) -> Path:
        return self.run_dir / "summary.md"

    @property
    def contract_dir(self) -> Path:
        return self.run_dir / "contract"

    @property
    def contract_spec_path(self) -> Path:
        return self.contract_dir / "spec.md"

    @property
    def contract_compiled_spec_path(self) -> Path:
        return self.contract_dir / "compiled_spec.json"

    @property
    def contract_workflow_path(self) -> Path:
        return self.contract_dir / "workflow.json"

    @property
    def run_contract_path(self) -> Path:
        return self.contract_dir / "run_contract.json"

    @property
    def contract_auto_checks_path(self) -> Path:
        return self.contract_dir / "auto_checks.json"

    @property
    def workspace_baseline_path(self) -> Path:
        return self.contract_dir / "workspace_baseline.json"

    @property
    def contract_prompts_dir(self) -> Path:
        return self.contract_dir / "prompts"

    @property
    def context_dir(self) -> Path:
        return self.run_dir / "context"

    @property
    def role_requests_path(self) -> Path:
        return self.context_dir / "role_requests.jsonl"

    @property
    def latest_state_path(self) -> Path:
        return self.context_dir / "latest_state.json"

    @property
    def latest_iteration_summary_path(self) -> Path:
        return self.context_dir / "latest_iteration_summary.json"

    @property
    def check_planner_dir(self) -> Path:
        return self.context_dir / "check_planner"

    @property
    def check_planner_output_raw_path(self) -> Path:
        return self.check_planner_dir / "output.raw.json"

    @property
    def check_planner_prompt_path(self) -> Path:
        return self.check_planner_dir / "prompt.md"

    @property
    def timeline_dir(self) -> Path:
        return self.run_dir / "timeline"

    @property
    def timeline_events_path(self) -> Path:
        return self.timeline_dir / "events.jsonl"

    @property
    def timeline_iterations_path(self) -> Path:
        return self.timeline_dir / "iterations.jsonl"

    @property
    def timeline_metrics_path(self) -> Path:
        return self.timeline_dir / "metrics.jsonl"

    @property
    def timeline_stagnation_path(self) -> Path:
        return self.timeline_dir / "stagnation.json"

    @property
    def timeline_workspace_guard_path(self) -> Path:
        return self.timeline_dir / "workspace_guard.json"

    @property
    def evidence_dir(self) -> Path:
        return self.run_dir / "evidence"

    @property
    def evidence_ledger_path(self) -> Path:
        return self.evidence_dir / "ledger.jsonl"

    @property
    def iterations_dir(self) -> Path:
        return self.run_dir / "iterations"

    @property
    def legacy_events_path(self) -> Path:
        return self.run_dir / "events.jsonl"

    @property
    def legacy_iterations_path(self) -> Path:
        return self.run_dir / "iteration_log.jsonl"

    @property
    def legacy_metrics_path(self) -> Path:
        return self.run_dir / "metrics_history.jsonl"

    @property
    def legacy_auto_checks_path(self) -> Path:
        return self.run_dir / "auto_checks.json"

    @property
    def legacy_workspace_guard_path(self) -> Path:
        return self.run_dir / "workspace_guard.json"

    def contract_prompt_path(self, prompt_ref: str) -> Path:
        return self.contract_prompts_dir / prompt_ref

    def iteration_dir(self, iter_id: int) -> Path:
        return self.iterations_dir / f"iter_{iter_id:03d}"

    def iteration_summary_path(self, iter_id: int) -> Path:
        return self.iteration_dir(iter_id) / "summary.json"

    def step_dir(self, iter_id: int, step_order: int, step_id: str) -> Path:
        return self.iteration_dir(iter_id) / "steps" / f"{step_order:02d}__{step_id}"

    def step_metadata_path(self, iter_id: int, step_order: int, step_id: str) -> Path:
        return self.step_dir(iter_id, step_order, step_id) / "metadata.json"

    def step_context_path(self, iter_id: int, step_order: int, step_id: str) -> Path:
        return self.step_dir(iter_id, step_order, step_id) / "input.context.json"

    def step_prompt_path(self, iter_id: int, step_order: int, step_id: str) -> Path:
        return self.step_dir(iter_id, step_order, step_id) / "prompt.md"

    def step_output_raw_path(self, iter_id: int, step_order: int, step_id: str) -> Path:
        return self.step_dir(iter_id, step_order, step_id) / "output.raw.json"

    def step_output_normalized_path(self, iter_id: int, step_order: int, step_id: str) -> Path:
        return self.step_dir(iter_id, step_order, step_id) / "output.normalized.json"

    def step_handoff_path(self, iter_id: int, step_order: int, step_id: str) -> Path:
        return self.step_dir(iter_id, step_order, step_id) / "handoff.json"

    def relative(self, path: Path) -> str:
        return path.relative_to(self.run_dir).as_posix()

    def workspace_relative(self, path: Path) -> str:
        try:
            return path.relative_to(self.workdir_path).as_posix()
        except ValueError:
            return path.resolve().as_posix()

    def initialize(self) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.contract_prompts_dir.mkdir(parents=True, exist_ok=True)
        self.context_dir.mkdir(parents=True, exist_ok=True)
        self.check_planner_dir.mkdir(parents=True, exist_ok=True)
        self.timeline_dir.mkdir(parents=True, exist_ok=True)
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self.iterations_dir.mkdir(parents=True, exist_ok=True)
        for path in (
            self.timeline_events_path,
            self.timeline_iterations_path,
            self.timeline_metrics_path,
            self.evidence_ledger_path,
            self.legacy_events_path,
            self.legacy_iterations_path,
            self.legacy_metrics_path,
            self.role_requests_path,
        ):
            ensure_parent(path)
            path.touch(exist_ok=True)
        if not self.timeline_stagnation_path.exists():
            write_json(self.timeline_stagnation_path, dict(INITIAL_STAGNATION_STATE))
        if not self.latest_state_path.exists():
            write_json(self.latest_state_path, dict(INITIAL_LATEST_STATE))

    def legacy_role_output_paths(self, archetype: str) -> list[Path]:
        if archetype == "builder":
            return [self.run_dir / "builder_output.json", self.run_dir / "generator_output.json"]
        if archetype == "inspector":
            return [self.run_dir / "inspector_output.json", self.run_dir / "tester_output.json"]
        if archetype == "gatekeeper":
            return [self.run_dir / "gatekeeper_verdict.json", self.run_dir / "verifier_verdict.json"]
        if archetype == "guide":
            return [self.run_dir / "guide_output.json", self.run_dir / "challenger_seed.json"]
        return []


def artifact_ref(layout: RunArtifactLayout, path: Path, *, kind: str, label: str = "") -> dict[str, str]:
    return {
        "kind": kind,
        "label": label,
        "relative_path": layout.relative(path),
        "workspace_path": layout.workspace_relative(path),
        "absolute_path": str(path.resolve()),
    }


def append_jsonl_with_mirrors(path: Path, payload: dict, *, mirror_paths: Iterable[Path] = ()) -> None:
    append_jsonl(path, payload)
    for mirror_path in mirror_paths:
        if mirror_path == path:
            continue
        append_jsonl(mirror_path, payload)


def write_json_with_mirrors(path: Path, payload: dict, *, mirror_paths: Iterable[Path] = ()) -> None:
    write_json(path, payload)
    for mirror_path in mirror_paths:
        if mirror_path == path:
            continue
        write_json(mirror_path, payload)


def write_text_with_mirrors(path: Path, text: str, *, mirror_paths: Iterable[Path] = ()) -> None:
    ensure_parent(path)
    path.write_text(text, encoding="utf-8")
    for mirror_path in mirror_paths:
        if mirror_path == path:
            continue
        ensure_parent(mirror_path)
        mirror_path.write_text(text, encoding="utf-8")


def read_jsonl(path: Path, *, limit: int | None = None) -> list[dict]:
    if not path.exists() or not path.is_file():
        return []
    records: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        if isinstance(payload, dict):
            records.append(payload)
    if limit is not None and limit >= 0:
        return records[-limit:]
    return records


def list_run_artifacts(run: dict) -> list[dict]:
    layout = RunArtifactLayout(Path(run["runs_dir"]))
    artifacts: list[dict] = []
    for artifact in RUN_ARTIFACT_SPECS:
        path = layout.run_dir / artifact["relative_path"]
        artifacts.append(
            {
                **artifact,
                "filename": artifact["relative_path"],
                "path": str(path),
                "available": path.exists(),
            }
        )
    if layout.contract_prompts_dir.exists():
        for prompt_path in sorted(path for path in layout.contract_prompts_dir.rglob("*.md") if path.is_file()):
            relative_path = layout.relative(prompt_path)
            artifacts.append(
                {
                    "id": f"prompt-{artifact_slug(relative_path)}",
                    "filename": relative_path,
                    "relative_path": relative_path,
                    "label_zh": f"Prompt · {prompt_path.name}",
                    "label_en": f"Prompt · {prompt_path.name}",
                    "description_zh": "这次 run 冻结保存的角色 Prompt Markdown。",
                    "description_en": "The role prompt Markdown frozen for this run.",
                    "path": str(prompt_path),
                    "available": True,
                }
            )
    if layout.iterations_dir.exists():
        for artifact_path in sorted(layout.iterations_dir.rglob("*")):
            if not artifact_path.is_file() or artifact_path.name not in STEP_ARTIFACT_FILENAMES:
                continue
            relative_path = layout.relative(artifact_path)
            label_prefix = "Step prompt" if artifact_path.name == "prompt.md" else "Step artifact"
            label_prefix_zh = "步骤 Prompt" if artifact_path.name == "prompt.md" else "步骤产物"
            artifacts.append(
                {
                    "id": f"step-{artifact_slug(relative_path)}",
                    "filename": relative_path,
                    "relative_path": relative_path,
                    "label_zh": f"{label_prefix_zh} · {relative_path}",
                    "label_en": f"{label_prefix} · {relative_path}",
                    "description_zh": "按 step 冻结保存的上下文、Prompt、元数据或输出快照。",
                    "description_en": "A step-scoped context, prompt, metadata, or output snapshot.",
                    "path": str(artifact_path),
                    "available": True,
                }
            )
    return artifacts


def artifact_slug(relative_path: str) -> str:
    return relative_path.replace("/", "-").replace("\\", "-").replace(".", "-")
