from __future__ import annotations

import json
import os
import re
import signal
import threading
from contextlib import suppress
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any

from loopora.alignment_semantics import (
    semantic_antipattern_match_is_negated,
    text_mentions_loop_fit_contradiction,
)
from loopora.agent_adapters import agent_loop_command, read_agent_binding
from loopora.alignment_guidance import load_alignment_guidance_assets
from loopora.branding import APP_STATE_DIRNAME, state_dir_for_workdir
from loopora.bundles import (
    BundleError,
    bundle_to_yaml,
    lint_alignment_bundle_generation_text,
    lint_alignment_bundle_semantics,
    load_bundle_text,
    read_bundle_file_text,
)
from loopora.diagnostics import get_logger, log_exception
from loopora.event_redaction import redact_alignment_event_payload, redact_sensitive_text, redact_sensitive_value
from loopora.evidence_coverage import load_or_build_evidence_coverage_projection, summarize_evidence_coverage_projection
from loopora.executor import ExecutionStopped, ExecutorError, RoleRequest, validate_command_args_text
from loopora.providers import executor_profile, normalize_executor_kind, normalize_executor_mode, normalize_reasoning_setting
from loopora.residual_risk_support import residual_risk_is_unmanaged
from loopora.run_artifacts import RunArtifactLayout, read_jsonl
from loopora.run_takeaways import build_judgment_contract
from loopora.service_alignment_diagnostics import (
    append_alignment_diagnostic_event,
    append_alignment_local_diagnostic_event,
    log_alignment_diagnostic_event_failure,
)
from loopora.service_alignment_legacy import ServiceAlignmentLegacyMixin
from loopora.service_cleanup_diagnostics import best_effort_rmtree, cleanup_diagnostic_payload, log_cleanup_diagnostic
from loopora.service_types import LooporaConflictError, LooporaError, LooporaNotFoundError, TERMINAL_RUN_STATUSES
from loopora.specs import SpecError, compile_markdown_spec
from loopora.structured_numbers import structured_non_negative_int
from loopora.utils import make_id, utc_now

logger = get_logger(__name__)

ALIGNMENT_ACTIVE_STATUSES = {"running", "validating", "repairing"}
ALIGNMENT_CONFIRMED_STAGES = {"confirmed", "compiling", "ready_review"}
ALIGNMENT_READINESS_KEYS = [
    "loop_fit",
    "task_scope",
    "success_surface",
    "fake_done_risks",
    "evidence_preferences",
    "execution_strategy",
    "residual_risk_policy",
    "judgment_tradeoffs",
    "local_governance",
    "role_posture",
    "workflow_shape",
    "explicit_confirmation",
]
ALIGNMENT_READINESS_EVIDENCE_KEYS = [
    "loop_fit",
    "task_scope",
    "success_surface",
    "fake_done_risks",
    "evidence_preferences",
    "execution_strategy",
    "residual_risk_policy",
    "judgment_tradeoffs",
    "local_governance",
    "role_posture",
    "workflow_shape",
    "workdir_facts",
]
ALIGNMENT_AGREEMENT_TRACEABILITY_KEYS = [
    "loop_fit",
    "task_scope",
    "success_surface",
    "fake_done_risks",
    "evidence_preferences",
    "execution_strategy",
    "residual_risk_policy",
    "judgment_tradeoffs",
    "local_governance",
    "role_posture",
    "workflow_shape",
    "workdir_facts",
]
ALIGNMENT_AGENT_ENTRY_REVIEW_ITEM_IDS = [
    "success_surface",
    "fake_done_risks",
    "evidence_preferences",
    "loop_fit",
    "execution_strategy",
    "judgment_tradeoffs",
    "residual_risk_policy",
    "local_governance",
]
ALIGNMENT_MISSING_ITEM_IDS = frozenset(
    [
        *ALIGNMENT_READINESS_KEYS,
        *ALIGNMENT_READINESS_EVIDENCE_KEYS,
        *ALIGNMENT_AGREEMENT_TRACEABILITY_KEYS,
        *ALIGNMENT_AGENT_ENTRY_REVIEW_ITEM_IDS,
        "agreement_summary",
        "open_questions",
        "readiness_checklist",
        "readiness_evidence",
    ]
)
ALIGNMENT_TRACEABILITY_GENERIC_TERMS = {
    "agent",
    "agents",
    "alignment",
    "and",
    "answer",
    "answers",
    "any",
    "artifact",
    "artifacts",
    "assumptions",
    "auditable",
    "behavior",
    "before",
    "because",
    "block",
    "blocked",
    "blocker",
    "blockers",
    "blocking",
    "bug",
    "bugs",
    "builder",
    "buckets",
    "built",
    "bundle",
    "bundles",
    "candidate",
    "carefully",
    "case",
    "cases",
    "change",
    "changes",
    "chat",
    "check",
    "checks",
    "claims",
    "clear",
    "close",
    "closed",
    "closes",
    "closure",
    "collects",
    "collaboration",
    "command",
    "complete",
    "completed",
    "completion",
    "complex",
    "concrete",
    "context",
    "correct",
    "created",
    "current",
    "direct",
    "distinguish",
    "drift",
    "during",
    "done",
    "early",
    "enough",
    "error",
    "evidence",
    "exact",
    "existing",
    "expected",
    "experience",
    "exercise",
    "exportable",
    "exposed",
    "fail",
    "failed",
    "fails",
    "facts",
    "fake-done",
    "final",
    "fit",
    "fits",
    "flow",
    "focused",
    "from",
    "future",
    "gains",
    "gaps",
    "gatekeeper",
    "gated",
    "generic",
    "goal",
    "good",
    "handle",
    "handoff",
    "handoffs",
    "happy-path-only",
    "hide",
    "hides",
    "important",
    "inspected",
    "inspector",
    "inspectors",
    "judge",
    "judged",
    "judgment",
    "keeps",
    "limited",
    "local",
    "loop",
    "loopora",
    "making",
    "means",
    "minor",
    "missing",
    "must",
    "named",
    "narrow",
    "new",
    "observed",
    "observable",
    "open",
    "open-ended",
    "only",
    "one-pass",
    "output",
    "over",
    "pass",
    "patch",
    "path",
    "polish",
    "polished-looking",
    "posture",
    "prefer",
    "preference",
    "preferences",
    "primary",
    "primary-flow",
    "produce",
    "project",
    "project-owned",
    "proof",
    "prove",
    "proven",
    "provided",
    "ready",
    "real",
    "reject",
    "remain",
    "reproducible",
    "result",
    "residual",
    "revised",
    "review",
    "risk",
    "risks",
    "role",
    "roles",
    "round",
    "rounds",
    "run",
    "run-owned",
    "scope",
    "should",
    "slice",
    "smaller",
    "snapshot",
    "specific",
    "speed",
    "stack",
    "standalone",
    "starter",
    "strongest",
    "success",
    "surface",
    "survive",
    "task",
    "tasks",
    "target",
    "test",
    "tests",
    "that",
    "the",
    "them",
    "then",
    "they",
    "through",
    "true",
    "unknown",
    "until",
    "unproven",
    "useful",
    "user",
    "user-facing",
    "vague",
    "verifiable",
    "verify",
    "verified",
    "verification",
    "wants",
    "weak",
    "when",
    "while",
    "with",
    "without",
    "work",
    "workflow",
    "workdir",
    "works",
}
ALIGNMENT_TEMPLATE_PLACEHOLDER_RE = re.compile(r"{{\s*([a-zA-Z0-9_]+)\s*}}")
ALIGNMENT_TRACEABILITY_GENERIC_CJK_TERMS = {
    "以及",
    "因为",
    "如果",
    "任务",
    "证据",
    "角色",
    "流程",
    "风险",
    "判断",
    "工作",
    "用户",
    "确认",
    "运行",
    "检查",
    "证明",
    "验证",
    "阻断",
    "完成",
    "成功",
    "失败",
    "必须",
    "优先",
    "方案",
    "服务",
    "选择",
    "使用",
    "测试",
    "命令",
    "产物",
    "主流程",
    "主流",
    "而不",
    "起来",
    "真实",
    "结果",
    "输出",
    "项目",
    "路径",
    "规则",
    "未知",
    "修复",
    "改进",
    "可见",
    "收束",
    "交接",
    "构建",
    "裁决",
    "质量",
    "偏差",
    "具体",
    "技术",
    "复退",
}
ALIGNMENT_LOOP_FIT_TRACEABILITY_GENERIC_TERMS = {
    "audit",
    "export",
    "human",
    "material",
    "plus",
    "reuse",
    "this",
}
ALIGNMENT_TRACEABILITY_CJK_STOP_CHARS = frozenset("的一是在和与或及并但而为由让把被只已未就才需能会应可其此个这那")
ALIGNMENT_AGENT_CANDIDATE_GENERIC_TERMS = {
    "agent-native",
    "already",
    "across",
    "after",
    "bind",
    "build",
    "bundle",
    "candidate",
    "claim",
    "codex",
    "control",
    "context",
    "counts",
    "coverage",
    "dispatch",
    "evidence",
    "evidence-backed",
    "elapses",
    "enforce",
    "enters",
    "exhausted",
    "fire",
    "governed",
    "host",
    "inside",
    "invented",
    "isolated",
    "iterations",
    "keep",
    "known",
    "ledger",
    "lifecycle",
    "limit",
    "malformed",
    "native",
    "non-gatekeeper",
    "outputs",
    "parallel",
    "peer",
    "plane",
    "proof",
    "ready",
    "ref",
    "refs",
    "rejection",
    "require",
    "required",
    "requires",
    "reviewers",
    "separate",
    "set",
    "skip",
    "stalled",
    "stay",
    "submit",
    "submitted",
    "surface",
    "this",
    "thread",
    "treat",
    "window",
}
ALIGNMENT_LANGUAGE_NEUTRAL_CONFIRMATIONS = {
    "确认",
    "已确认",
    "同意",
    "可以",
    "好",
    "好的",
    "没问题",
    "继续",
    "ok",
    "yes",
    "confirm",
    "approved",
    "go ahead",
    "proceed",
}
ALIGNMENT_SOURCE_ARTIFACT_REF_KEYS = ("kind", "label", "relative_path", "workspace_path", "absolute_path")
ALIGNMENT_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "status": {
            "type": "string",
            "enum": ["question", "bundle", "blocked"],
        },
        "assistant_message": {"type": "string"},
        "needs_user_input": {"type": "boolean"},
        "decision_options": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string"},
                    "label": {"type": "string"},
                    "description": {"type": "string"},
                    "recommended": {"type": "boolean"},
                    "user_reply": {"type": "string"},
                },
                "required": ["id", "label", "description", "recommended", "user_reply"],
            },
        },
        "bundle_yaml": {"type": "string"},
        "session_ref": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "session_id": {"type": "string"},
                "thread_id": {"type": "string"},
                "conversation_id": {"type": "string"},
                "provider": {"type": "string"},
                "raw_json": {"type": "string"},
            },
            "required": ["session_id", "thread_id", "conversation_id", "provider", "raw_json"],
        },
        "alignment_phase": {
            "type": "string",
            "enum": ["clarifying", "agreement", "confirmed", "bundle", "blocked"],
        },
        "agreement_summary": {"type": "string"},
        "readiness_checklist": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "task_scope": {"type": "boolean"},
                "loop_fit": {"type": "boolean"},
                "success_surface": {"type": "boolean"},
                "fake_done_risks": {"type": "boolean"},
                "evidence_preferences": {"type": "boolean"},
                "execution_strategy": {"type": "boolean"},
                "residual_risk_policy": {"type": "boolean"},
                "judgment_tradeoffs": {"type": "boolean"},
                "local_governance": {"type": "boolean"},
                "role_posture": {"type": "boolean"},
                "workflow_shape": {"type": "boolean"},
                "explicit_confirmation": {"type": "boolean"},
            },
            "required": ALIGNMENT_READINESS_KEYS,
        },
        "readiness_evidence": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "task_scope": {"type": "string"},
                "loop_fit": {"type": "string"},
                "success_surface": {"type": "string"},
                "fake_done_risks": {"type": "string"},
                "evidence_preferences": {"type": "string"},
                "execution_strategy": {"type": "string"},
                "residual_risk_policy": {"type": "string"},
                "judgment_tradeoffs": {"type": "string"},
                "local_governance": {"type": "string"},
                "role_posture": {"type": "string"},
                "workflow_shape": {"type": "string"},
                "workdir_facts": {"type": "string"},
                "open_questions": {"type": "string"},
            },
            "required": [*ALIGNMENT_READINESS_EVIDENCE_KEYS, "open_questions"],
        },
    },
    "required": [
        "status",
        "assistant_message",
        "needs_user_input",
        "decision_options",
        "bundle_yaml",
        "session_ref",
        "alignment_phase",
        "agreement_summary",
        "readiness_checklist",
        "readiness_evidence",
    ],
}


@dataclass(frozen=True)
class AlignmentExecutorSettingsRequest:
    executor_kind: str
    executor_mode: str
    command_cli: str
    command_args_text: str
    model: str
    reasoning_effort: str


def _default_alignment_executor_settings() -> AlignmentExecutorSettingsRequest:
    return AlignmentExecutorSettingsRequest(
        executor_kind="codex",
        executor_mode="preset",
        command_cli="",
        command_args_text="",
        model="",
        reasoning_effort="",
    )


@dataclass(frozen=True)
class AlignmentSessionCreateRequest:
    workdir: Path
    message: str = ""
    start_immediately: bool = True
    source_option_id: str = ""
    executor_settings: AlignmentExecutorSettingsRequest = field(default_factory=_default_alignment_executor_settings)


@dataclass(frozen=True)
class RevisionSessionOptions:
    message: str = ""
    start_immediately: bool = True
    executor_settings: AlignmentExecutorSettingsRequest = field(default_factory=_default_alignment_executor_settings)


@dataclass(frozen=True)
class RevisionAlignmentSessionRequest:
    seed_bundle: dict
    message: str
    start_immediately: bool
    source_context: dict
    linked_bundle_id: str
    linked_run_id: str
    executor_settings: AlignmentExecutorSettingsRequest


@dataclass(frozen=True)
class AlignmentExecutionState:
    mode: str = "normal"
    validation_error: str = ""
    invalid_yaml: str = ""


def _coerce_alignment_session_create_request(
    request: AlignmentSessionCreateRequest | None,
    raw_request: dict[str, object],
) -> AlignmentSessionCreateRequest:
    if request is not None:
        if raw_request:
            raise TypeError("create_alignment_session accepts either request or keyword fields, not both")
        return request
    workdir = raw_request.get("workdir")
    if workdir is None:
        raise TypeError("create_alignment_session requires workdir")
    return AlignmentSessionCreateRequest(
        workdir=workdir if isinstance(workdir, Path) else Path(str(workdir)),
        message=str(raw_request.get("message", "") or ""),
        start_immediately=_coerce_alignment_start_immediately(raw_request.get("start_immediately", True)),
        source_option_id=str(raw_request.get("source_option_id", "") or "").strip(),
        executor_settings=_alignment_executor_settings_from_raw(raw_request),
    )


def _coerce_revision_session_options(
    request: RevisionSessionOptions | None,
    raw_request: dict[str, object],
) -> RevisionSessionOptions:
    if request is not None:
        if raw_request:
            raise TypeError("revision session creation accepts either request or keyword fields, not both")
        return request
    return RevisionSessionOptions(
        message=str(raw_request.get("message", "") or ""),
        start_immediately=_coerce_alignment_start_immediately(raw_request.get("start_immediately", True)),
        executor_settings=_alignment_executor_settings_from_raw(raw_request),
    )


def _coerce_alignment_start_immediately(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _alignment_executor_settings_from_raw(raw_request: dict[str, object]) -> AlignmentExecutorSettingsRequest:
    defaults = _default_alignment_executor_settings()
    return AlignmentExecutorSettingsRequest(
        executor_kind=str(raw_request.get("executor_kind", defaults.executor_kind)),
        executor_mode=str(raw_request.get("executor_mode", defaults.executor_mode)),
        command_cli=str(raw_request.get("command_cli", defaults.command_cli)),
        command_args_text=str(raw_request.get("command_args_text", defaults.command_args_text)),
        model=str(raw_request.get("model", defaults.model)),
        reasoning_effort=str(raw_request.get("reasoning_effort", defaults.reasoning_effort)),
    )


def _governance_marker_responsibility_present(text: str, *, actor_pattern: str, action_pattern: str) -> bool:
    marker_pattern = r"agents\.md|design/readme\.md|design/|tests/|project-local|project local|项目本地|本地治理"
    segments = re.split(r"[\n.;。；]+", text)
    marker_windows: list[str] = []
    for match in re.finditer(marker_pattern, text, flags=re.I):
        start = max(0, match.start() - 180)
        end = min(len(text), match.end() + 180)
        marker_windows.append(text[start:end])
    for segment in [*segments, *marker_windows]:
        if (
            re.search(marker_pattern, segment, flags=re.I)
            and re.search(actor_pattern, segment, flags=re.I)
            and re.search(action_pattern, segment, flags=re.I)
        ):
            return True
    return False


class ServiceAlignmentMixin(ServiceAlignmentLegacyMixin):
    def create_alignment_session(
        self,
        request: AlignmentSessionCreateRequest | None = None,
        **raw_request: object,
    ) -> dict:
        request = _coerce_alignment_session_create_request(request, raw_request)
        workdir = request.workdir.expanduser().resolve()
        if not workdir.exists() or not workdir.is_dir():
            raise LooporaError(f"workdir does not exist: {workdir}")
        settings = self._normalize_alignment_executor_settings(request.executor_settings)
        source_seed = self._resolve_alignment_source_option(workdir, request.source_option_id)
        session_id = make_id("align")
        session_dir = self._alignment_session_dir(workdir, session_id)
        paths = self._alignment_artifact_paths_from_root(session_dir)
        self._ensure_alignment_artifact_dirs(session_dir)
        transcript = []
        normalized_message = str(request.message or "").strip()
        if normalized_message:
            transcript.append({"role": "user", "content": normalized_message, "created_at": utc_now()})
        session = self.repository.create_alignment_session(
            {
                "id": session_id,
                "status": "idle",
                "workdir": str(workdir),
                "bundle_path": str(paths["bundle"]),
                "transcript": transcript,
                "validation": {},
                "alignment_stage": "clarifying",
                "working_agreement": source_seed.get("working_agreement") or {},
                "executor_session_ref": {},
                "linked_bundle_id": source_seed.get("linked_bundle_id", ""),
                "linked_loop_id": source_seed.get("linked_loop_id", ""),
                "linked_run_id": source_seed.get("linked_run_id", ""),
                **settings,
            }
        )
        seed_bundle = source_seed.get("seed_bundle")
        if isinstance(seed_bundle, dict) and seed_bundle:
            paths["bundle"].write_text(bundle_to_yaml(seed_bundle), encoding="utf-8")
        self.repository.append_alignment_event(
            session_id,
            "alignment_session_created",
            {
                "status": session["status"],
                "workdir": session["workdir"],
                "executor_kind": session["executor_kind"],
            },
        )
        source_event = source_seed.get("event")
        if isinstance(source_event, dict) and source_event:
            self.repository.append_alignment_event(session_id, "alignment_source_context_selected", source_event)
        self._write_alignment_transcript_log(self.get_alignment_session(session_id))
        if normalized_message and request.start_immediately:
            self.start_alignment_session_async(session_id)
            return self.get_alignment_session(session_id)
        return self.get_alignment_session(session_id)

    def get_alignment_session(self, session_id: str) -> dict:
        session = self.repository.get_alignment_session(session_id)
        if not session:
            raise LooporaNotFoundError(f"unknown alignment session: {session_id}")
        session = self._ensure_alignment_session_layout(session)
        decorated = self._decorate_alignment_session(session)
        decorated["agent_entry_review"] = self._agent_entry_review_projection(decorated)
        decorated["agent_entry_launch"] = self._agent_entry_launch_projection(decorated)
        return decorated

    def list_alignment_sessions(self, *, limit: int = 30) -> list[dict]:
        return [self._alignment_session_summary(item) for item in self.repository.list_alignment_sessions(limit=limit)]

    def delete_alignment_session(self, session_id: str) -> bool:
        session = self.get_alignment_session(session_id)
        if session["status"] in ALIGNMENT_ACTIVE_STATUSES:
            raise LooporaConflictError("cannot delete an active alignment session")
        session_dir = self._alignment_session_root(session)
        deleted = self.repository.delete_alignment_session(session_id)
        if deleted and session_dir.name == session_id and session_dir.parent.name == "alignment_sessions":
            best_effort_rmtree(
                session_dir,
                logger,
                operation="alignment_session_delete",
                owner_id=session_id,
                on_failure=lambda payload: self._append_alignment_local_diagnostic_event(
                    session,
                    "alignment_session_cleanup_failed",
                    payload,
                ),
            )
            self._mark_local_asset_cleanup_by_path(
                session_dir,
                operation="alignment_session_delete",
                owner_id=session_id,
            )
        return deleted

    def _append_alignment_diagnostic_event(self, session_id: str, event_type: str, payload: dict) -> dict:
        return append_alignment_diagnostic_event(self, logger, session_id, event_type, payload)

    def _append_alignment_local_diagnostic_event(self, session: dict, event_type: str, payload: dict) -> None:
        append_alignment_local_diagnostic_event(self, logger, session, event_type, payload)

    @staticmethod
    def _log_alignment_diagnostic_event_failure(
        *,
        session_id: str,
        event_type: str,
        payload: dict,
        error: BaseException,
    ) -> None:
        log_alignment_diagnostic_event_failure(
            logger,
            session_id=session_id,
            event_type=event_type,
            payload=payload,
            error=error,
        )

    def append_alignment_message(self, session_id: str, message: str) -> dict:
        normalized = str(message or "").strip()
        if not normalized:
            raise LooporaError("message is required")
        session = self.get_alignment_session(session_id)
        if session["status"] in ALIGNMENT_ACTIVE_STATUSES:
            raise LooporaConflictError("alignment session is already running")
        transcript = list(session.get("transcript") or [])
        transcript.append({"role": "user", "content": normalized, "created_at": utc_now()})
        stage_updates = self._alignment_stage_updates_for_user_message(session, normalized)
        self.repository.update_alignment_session(
            session_id,
            transcript=transcript,
            error_message="",
            stop_requested=False,
            repair_attempts=0,
            finished_at=None,
            **stage_updates,
        )
        self.repository.append_alignment_event(
            session_id,
            "alignment_user_message",
            {"role": "user", "content": normalized},
        )
        if stage_updates.get("alignment_stage") == "confirmed":
            self.repository.append_alignment_event(
                session_id,
                "alignment_agreement_confirmed",
                {"alignment_stage": "confirmed"},
            )
        elif stage_updates.get("alignment_stage") == "ready_review":
            self.repository.append_alignment_event(
                session_id,
                "alignment_ready_review_started",
                {
                    "alignment_stage": "ready_review",
                    "feedback": normalized,
                    "bundle_path": session.get("bundle_path", ""),
                },
            )
        elif stage_updates.get("alignment_stage") == "clarifying" and session.get("alignment_stage") == "agreement_ready":
            self.repository.append_alignment_event(
                session_id,
                "alignment_agreement_reopened",
                {"alignment_stage": "clarifying"},
            )
        self._write_alignment_transcript_log(self.get_alignment_session(session_id))
        self.start_alignment_session_async(session_id)
        return self.get_alignment_session(session_id)

    def start_alignment_session_async(self, session_id: str) -> None:
        session = self.get_alignment_session(session_id)
        if session["status"] in ALIGNMENT_ACTIVE_STATUSES:
            raise LooporaConflictError("alignment session is already running")
        key = self._alignment_thread_key(session_id)
        thread = self._threads.get(key)
        if thread and thread.is_alive():
            raise LooporaConflictError("alignment session is already running")
        self.repository.update_alignment_session(
            session_id,
            status="running",
            stop_requested=False,
            clear_active_child_pid=True,
            finished_at=None,
            error_message="",
        )
        self.repository.append_alignment_event(session_id, "alignment_started", {"status": "running"})
        thread = threading.Thread(
            target=self._execute_alignment_session,
            args=(session_id,),
            daemon=True,
            name=f"alignment-{session_id}",
        )
        self._threads[key] = thread
        try:
            thread.start()
        except Exception:
            self._threads.pop(key, None)
            raise

    def cancel_alignment_session(self, session_id: str) -> dict:
        session = self.get_alignment_session(session_id)
        if session["status"] not in ALIGNMENT_ACTIVE_STATUSES:
            raise LooporaConflictError(f"cannot cancel alignment session in status {session['status']}")
        updated = self.repository.request_alignment_stop(session_id)
        self.repository.append_alignment_event(
            session_id,
            "alignment_cancel_requested",
            {"status": updated.get("status") if updated else session["status"]},
        )
        pid = session.get("active_child_pid")
        if pid not in {None, ""}:
            try:
                os.kill(int(pid), signal.SIGTERM)
            except (OSError, ValueError) as exc:
                diagnostic = cleanup_diagnostic_payload(
                    operation="alignment_cancel_signal",
                    resource_type="process",
                    resource_id=pid,
                    owner_id=session_id,
                    error=exc,
                    status=updated.get("status") if updated else session["status"],
                )
                log_cleanup_diagnostic(logger, **diagnostic)
                self._append_alignment_diagnostic_event(
                    session_id,
                    "alignment_cancel_signal_failed",
                    diagnostic,
                )
        return self.get_alignment_session(session_id)

    def list_alignment_events(self, session_id: str, *, after_id: int = 0, limit: int = 200) -> list[dict]:
        self.get_alignment_session(session_id)
        return self.repository.list_alignment_events(session_id, after_id=after_id, limit=limit)

    def latest_alignment_event_id(self, session_id: str) -> int:
        self.get_alignment_session(session_id)
        return self.repository.latest_alignment_event_id(session_id)

    def get_alignment_workdir_context(self, workdir: Path) -> dict:
        root = workdir.expanduser().resolve()
        context = self._alignment_workdir_context_payload(root)
        context["resolution"] = self._resolve_plan_context_from_workdir_context(context)
        return context

    def resolve_loopora_context(
        self,
        workdir: Path,
        *,
        intent: str = "plan",
        adapter: str = "",
        context_id: str = "",
        source_option_id: str = "",
    ) -> dict:
        root = workdir.expanduser().resolve()
        if not root.exists() or not root.is_dir():
            raise LooporaError(f"workdir does not exist: {root}")
        normalized_intent = str(intent or "plan").strip().lower()
        if normalized_intent == "run":
            return self._resolve_run_context(root, adapter=adapter, context_id=context_id)
        context = self._alignment_workdir_context_payload(root)
        return self._resolve_plan_context_from_workdir_context(context, source_option_id=source_option_id)

    def _alignment_workdir_context_payload(self, root: Path) -> dict:
        if not root.exists() or not root.is_dir():
            raise LooporaError(f"workdir does not exist: {root}")
        options: list[dict] = []
        seen_option_ids: set[str] = set()
        seen_bundle_paths = self._collect_alignment_session_context_options(root, options, seen_option_ids)
        seen_spec_paths = self._collect_alignment_loop_context_options(root, options, seen_option_ids)
        state_dir = state_dir_for_workdir(root)
        self._collect_alignment_filesystem_context_options(
            state_dir,
            options,
            seen_option_ids,
            seen_bundle_paths=seen_bundle_paths,
            seen_spec_paths=seen_spec_paths,
        )
        self._add_alignment_context_option(
            {
                "option_id": "regenerate",
                "action": "regenerate",
                "source_type": "none",
                "label_zh": "重新生成",
                "label_en": "Start fresh",
                "description_zh": "忽略这个目录里已有的 Loopora 产物，从当前消息重新编排。",
                "description_en": "Ignore existing Loopora artifacts in this workdir and compose from the new message.",
            },
            options,
            seen_option_ids,
        )
        has_sources = any(str(option.get("action") or "") != "regenerate" for option in options)
        bounded_options = self._bounded_alignment_context_options(options)
        return {
            "workdir": str(root),
            "state_dir": str(state_dir),
            "has_loopora_state": state_dir.exists(),
            "requires_choice": has_sources,
            "recommended_option_id": "" if has_sources else "regenerate",
            "options": bounded_options,
        }

    @staticmethod
    def _resolve_plan_context_from_workdir_context(context: dict, *, source_option_id: str = "") -> dict:
        option_id = str(source_option_id or context.get("recommended_option_id") or "").strip()
        options = [option for option in context.get("options") or [] if isinstance(option, dict)]
        selected = next((option for option in options if option.get("option_id") == option_id), None)
        base = {
            "schema_version": 1,
            "intent": "plan",
            "workdir": str(context.get("workdir") or ""),
            "state_dir": str(context.get("state_dir") or ""),
            "has_loopora_state": bool(context.get("has_loopora_state")),
            "selected_option_id": option_id,
            "requires_user_choice": False,
            "choices": [],
        }
        if selected and selected.get("action") == "regenerate":
            return {
                **base,
                "action": "create_new",
                "confidence": "explicit_fresh" if source_option_id else "no_existing_context",
                "fresh": True,
            }
        if selected and selected.get("action") == "continue_session":
            return {
                **base,
                "action": "continue_session",
                "confidence": "selected_context",
                "fresh": False,
                "selected": selected,
            }
        if selected:
            return {
                **base,
                "action": "improve_existing",
                "confidence": "selected_context",
                "fresh": False,
                "selected": selected,
            }
        if context.get("requires_choice"):
            return {
                **base,
                "action": "choose_source",
                "confidence": "ambiguous",
                "fresh": False,
                "requires_user_choice": True,
                "choices": options,
            }
        return {
            **base,
            "action": "create_new",
            "confidence": "no_existing_context",
            "fresh": True,
        }

    def get_alignment_bundle(self, session_id: str) -> dict:
        session = self.get_alignment_session(session_id)
        bundle_path = Path(session["bundle_path"])
        if not bundle_path.exists():
            return {
                "ok": False,
                "session": session,
                "yaml": "",
                "bundle": None,
                "validation": session.get("validation") or {"ok": False, "error": "bundle file does not exist"},
            }
        raw_yaml = ""
        semantic_issues: list[str] = []
        try:
            raw_yaml = read_bundle_file_text(bundle_path)
            if session["status"] in {"ready", "imported", "running_loop"}:
                bundle, normalized_yaml = self._load_validated_alignment_bundle_text(session, raw_yaml, semantic_issues)
                validation = {
                    "ok": True,
                    "error": "",
                    "bundle_path": str(bundle_path),
                    "checked_at": utc_now(),
                    "semantic_lint": {"ok": True, "issues": []},
                }
            else:
                bundle = load_bundle_text(raw_yaml)
                normalized_yaml = bundle_to_yaml(bundle)
                validation = session.get("validation") or {"ok": True, "bundle_path": str(bundle_path)}
        except (BundleError, LooporaError, OSError) as exc:
            return {
                "ok": False,
                "session": session,
                "yaml": raw_yaml,
                "bundle": None,
                "validation": {
                    "ok": False,
                    "error": str(exc),
                    "bundle_path": str(bundle_path),
                    "checked_at": utc_now(),
                    "semantic_lint": {"ok": not semantic_issues, "issues": semantic_issues},
                },
            }
        preview = self._bundle_preview_payload(
            bundle,
            source_path=str(bundle_path),
            validation=validation,
        )
        preview["session"] = session
        preview["yaml"] = normalized_yaml
        return preview

    def _load_validated_alignment_bundle_text(
        self,
        session: dict,
        bundle_yaml: str,
        semantic_issues: list[str],
    ) -> tuple[dict, str]:
        semantic_issues.extend(lint_alignment_bundle_generation_text(bundle_yaml))
        if semantic_issues:
            raise LooporaError("bundle semantic lint failed: " + "; ".join(semantic_issues))

        bundle = load_bundle_text(bundle_yaml)
        self._assert_alignment_bundle_workdir(bundle, expected_workdir=Path(session["workdir"]))
        issue_sources = (
            lint_alignment_bundle_semantics(bundle),
            self._alignment_bundle_executor_settings_issues(session, bundle),
            self._alignment_bundle_language_issues(session, bundle),
            self._alignment_bundle_workdir_fact_issues(session, bundle),
            self._alignment_improvement_bundle_issues(session, bundle),
            self._alignment_bundle_agreement_traceability_issues(session, bundle),
            self._alignment_agent_candidate_traceability_issues(session, bundle),
        )
        for issues in issue_sources:
            self._extend_unique_alignment_issues(semantic_issues, issues)
        if semantic_issues:
            raise LooporaError("bundle semantic lint failed: " + "; ".join(semantic_issues))

        return bundle, bundle_to_yaml(bundle)

    @staticmethod
    def _alignment_bundle_content_fingerprint(bundle_yaml: str) -> dict[str, Any]:
        data = bundle_yaml.encode("utf-8")
        return {"bundle_sha256": sha256(data).hexdigest(), "bundle_bytes": len(data)}

    def sync_alignment_bundle_from_file(self, session_id: str) -> dict:
        session = self.get_alignment_session(session_id)
        if session["status"] in ALIGNMENT_ACTIVE_STATUSES:
            raise LooporaConflictError("cannot sync bundle while alignment session is active")
        if session["status"] not in {"idle", "ready", "failed"}:
            raise LooporaConflictError(f"cannot sync bundle in status {session['status']}")
        bundle_path = Path(session["bundle_path"])
        if not bundle_path.exists():
            error = f"alignment bundle does not exist: {bundle_path}"
            validation = {
                "ok": False,
                "error": error,
                "bundle_path": str(bundle_path),
                "checked_at": utc_now(),
                "semantic_lint": {"ok": False, "issues": [error]},
            }
            return self._record_alignment_bundle_sync_failure(session_id, validation)

        semantic_issues: list[str] = []
        try:
            raw_yaml = read_bundle_file_text(bundle_path)
            bundle, normalized_yaml = self._load_validated_alignment_bundle_text(session, raw_yaml, semantic_issues)
            bundle_path.write_text(normalized_yaml, encoding="utf-8")
        except (BundleError, LooporaError, OSError) as exc:
            validation = {
                "ok": False,
                "error": str(exc),
                "bundle_path": str(bundle_path),
                "checked_at": utc_now(),
                "semantic_lint": {"ok": not semantic_issues, "issues": semantic_issues},
            }
            return self._record_alignment_bundle_sync_failure(session_id, validation)

        validation = {
            "ok": True,
            "error": "",
            "bundle_path": str(bundle_path),
            "checked_at": utc_now(),
            "semantic_lint": {"ok": True, "issues": []},
            **self._alignment_bundle_content_fingerprint(normalized_yaml),
        }
        self._append_alignment_system_message(
            session_id,
            zh="已重新读取 bundle.yml，并校验通过。",
            en="Reloaded bundle.yml and validation passed.",
        )
        self.repository.update_alignment_session(
            session_id,
            status="ready",
            alignment_stage="ready",
            validation=validation,
            error_message="",
            finished_at=None,
        )
        session = self.get_alignment_session(session_id)
        self._write_alignment_validation_log(session, validation)
        self._write_alignment_transcript_log(session)
        self.repository.append_alignment_event(
            session_id,
            "alignment_bundle_synced",
            validation,
        )
        preview = self._bundle_preview_payload(
            bundle,
            source_path=str(bundle_path),
            validation=validation,
        )
        preview["session"] = session
        preview["yaml"] = normalized_yaml
        return preview

    def import_alignment_bundle(self, session_id: str, *, start_immediately: bool = True, execute_async: bool = True) -> dict:
        session = self.get_alignment_session(session_id)
        if session["status"] != "ready":
            raise LooporaConflictError(f"alignment session is not READY: {session['status']}")
        if _coerce_alignment_start_immediately(start_immediately) and execute_async and self._alignment_session_has_agent_entry_candidate(session_id):
            raise LooporaConflictError("agent-first Loop previews must be started from /loopora-run so the host Agent executes the run natively")
        bundle_path = Path(session["bundle_path"])
        if not bundle_path.exists():
            raise LooporaNotFoundError(f"alignment bundle does not exist: {bundle_path}")
        semantic_issues: list[str] = []
        try:
            raw_yaml = read_bundle_file_text(bundle_path)
            _candidate_bundle, normalized_yaml = self._load_validated_alignment_bundle_text(
                session,
                raw_yaml,
                semantic_issues,
            )
            bundle_path.write_text(normalized_yaml, encoding="utf-8")
            bundle = self.import_bundle_text(normalized_yaml, imported_from_path=str(bundle_path))
        except (BundleError, LooporaError, OSError) as exc:
            error = str(exc)
            validation = {
                "ok": False,
                "error": error,
                "bundle_path": str(bundle_path),
                "checked_at": utc_now(),
                "semantic_lint": {"ok": not semantic_issues, "issues": semantic_issues},
            }
            self.repository.update_alignment_session(session_id, validation=validation, error_message=error)
            self._write_alignment_validation_log(self.get_alignment_session(session_id), validation)
            self.repository.append_alignment_event(
                session_id,
                "alignment_import_failed",
                {"error": error, "status": "ready", "semantic_lint": validation["semantic_lint"]},
            )
            if isinstance(exc, LooporaError):
                raise
            raise LooporaError(error) from exc
        validation = {
            "ok": True,
            "error": "",
            "bundle_path": str(bundle_path),
            "checked_at": utc_now(),
            "semantic_lint": {"ok": True, "issues": []},
            **self._alignment_bundle_content_fingerprint(normalized_yaml),
        }
        self.repository.update_alignment_session(
            session_id,
            status="imported",
            linked_bundle_id=bundle["id"],
            linked_loop_id=bundle.get("loop_id", ""),
            linked_run_id="",
            validation=validation,
            error_message="",
        )
        self._write_alignment_validation_log(self.get_alignment_session(session_id), validation)
        self.repository.append_alignment_event(
            session_id,
            "alignment_imported",
            {"bundle_id": bundle["id"], "loop_id": bundle.get("loop_id", "")},
        )
        run = None
        redirect_url = f"/bundles/{bundle['id']}"
        if _coerce_alignment_start_immediately(start_immediately):
            try:
                run = self.start_run(bundle["loop_id"])
                if execute_async:
                    self.start_run_async(run["id"])
            except LooporaError as exc:
                self.repository.update_alignment_session(session_id, error_message=str(exc))
                self.repository.append_alignment_event(
                    session_id,
                    "alignment_run_start_failed",
                    {"bundle_id": bundle["id"], "loop_id": bundle.get("loop_id", ""), "error": str(exc)},
                )
                raise
            self.repository.update_alignment_session(
                session_id,
                status="running_loop",
                linked_run_id=run["id"],
            )
            self.repository.append_alignment_event(
                session_id,
                "alignment_run_started",
                {"bundle_id": bundle["id"], "loop_id": bundle.get("loop_id", ""), "run_id": run["id"]},
            )
            redirect_url = f"/runs/{run['id']}"
        elif bundle.get("loop_id"):
            redirect_url = f"/loops/{bundle['loop_id']}"
        return {
            "session": self.get_alignment_session(session_id),
            "bundle": bundle,
            "loop": bundle.get("loop"),
            "run": run,
            "redirect_url": redirect_url,
        }

    def create_bundle_revision_session(
        self,
        bundle_id: str,
        request: RevisionSessionOptions | None = None,
        **raw_request: object,
    ) -> dict:
        request = _coerce_revision_session_options(request, raw_request)
        source_bundle = self.export_bundle(bundle_id)
        seed_bundle = self._revision_seed_bundle(source_bundle)
        return self._create_revision_alignment_session(
            RevisionAlignmentSessionRequest(
                seed_bundle=seed_bundle,
                message=request.message or "请先阅读这份已有 Loop 方案，和我对话改进它。先指出你需要确认的最小问题，不要直接生成。",
                start_immediately=request.start_immediately,
                source_context={
                    "mode": "improvement",
                    "source_type": "bundle",
                    "source_bundle_id": bundle_id,
                    "source_run_id": "",
                    "source_completion_mode": str(source_bundle.get("loop", {}).get("completion_mode", "") or ""),
                    "reason": "improve_imported_bundle",
                    "run_status": "",
                    "evidence_summary": [],
                    "task_verdict": {},
                    "gatekeeper_verdict": {},
                },
                linked_bundle_id=bundle_id,
                linked_run_id="",
                executor_settings=request.executor_settings,
            )
        )

    def create_run_revision_session(
        self,
        run_id: str,
        request: RevisionSessionOptions | None = None,
        **raw_request: object,
    ) -> dict:
        request = _coerce_revision_session_options(request, raw_request)
        run = self.get_run(run_id)
        loop = self.get_loop(run["loop_id"])
        source_bundle_id = str((loop.get("bundle") or {}).get("id") or "").strip()
        if source_bundle_id:
            source_bundle = self.export_bundle(source_bundle_id)
        else:
            source_bundle = self.derive_bundle_from_loop(
                run["loop_id"],
                name=str(loop.get("name") or "Run improvement base"),
                description="Derived as the improvement base for a run without an imported bundle.",
                collaboration_summary="Improvement base derived from the current loop.",
            )
        seed_bundle = self._revision_seed_bundle(source_bundle)
        return self._create_revision_alignment_session(
            RevisionAlignmentSessionRequest(
                seed_bundle=seed_bundle,
                message=request.message or "请基于这次运行的证据和守门裁决，和我对话改进 Loop 方案。先说明最可能要改的治理点，再问我最小必要问题。",
                start_immediately=request.start_immediately,
                source_context={
                    "mode": "improvement",
                    "source_type": "run",
                    "source_bundle_id": source_bundle_id,
                    "source_run_id": run_id,
                    "source_completion_mode": str(source_bundle.get("loop", {}).get("completion_mode", "") or ""),
                    "reason": "improve_from_run_evidence",
                    "run_status": str(run.get("status") or ""),
                    "artifact_paths": self._alignment_run_artifact_paths(run),
                    "judgment_contract": self._alignment_run_judgment_contract(run),
                    "coverage_summary": self._alignment_run_coverage_summary(run),
                    "evidence_summary": self._alignment_run_evidence_summary(run),
                    "task_verdict": run.get("task_verdict") or {},
                    "gatekeeper_verdict": run.get("last_verdict_json") or {},
                },
                linked_bundle_id=source_bundle_id,
                linked_run_id=run_id,
                executor_settings=request.executor_settings,
            )
        )

    def _create_revision_alignment_session(
        self,
        request: RevisionAlignmentSessionRequest,
    ) -> dict:
        seed_bundle = request.seed_bundle
        executor_settings = request.executor_settings
        workdir = Path(seed_bundle["loop"]["workdir"])
        session = self.create_alignment_session(
            workdir=workdir,
            message=request.message,
            executor_kind=executor_settings.executor_kind,
            executor_mode=executor_settings.executor_mode,
            command_cli=executor_settings.command_cli,
            command_args_text=executor_settings.command_args_text,
            model=executor_settings.model,
            reasoning_effort=executor_settings.reasoning_effort,
            start_immediately=False,
        )
        bundle_path = Path(session["bundle_path"])
        bundle_path.parent.mkdir(parents=True, exist_ok=True)
        bundle_path.write_text(bundle_to_yaml(seed_bundle), encoding="utf-8")
        redacted_source = self._redact_alignment_source_value(request.source_context)
        working_agreement = {
            "mode": "improvement",
            "source": redacted_source,
            "seed_bundle_metadata": self._redact_alignment_source_value(seed_bundle.get("metadata", {})),
        }
        self.repository.update_alignment_session(
            session["id"],
            working_agreement=working_agreement,
            linked_bundle_id=request.linked_bundle_id,
            linked_run_id=request.linked_run_id,
        )
        self.repository.append_alignment_event(
            session["id"],
            "alignment_bundle_improvement_seeded",
            {
                "source_type": redacted_source.get("source_type", "") if isinstance(redacted_source, dict) else "",
                "source_bundle_id": request.linked_bundle_id,
                "source_run_id": request.linked_run_id,
                "bundle_path": str(bundle_path),
            },
        )
        self._write_alignment_transcript_log(self.get_alignment_session(session["id"]))
        if request.start_immediately:
            self.start_alignment_session_async(session["id"])
        return self.get_alignment_session(session["id"])

    @staticmethod
    def _revision_seed_bundle(source_bundle: dict) -> dict:
        seed = json.loads(json.dumps(source_bundle, ensure_ascii=False))
        metadata = dict(seed.get("metadata") or {})
        metadata["bundle_id"] = ""
        metadata.pop("source_bundle_id", None)
        metadata.pop("revision", None)
        seed["metadata"] = metadata
        return seed

    @staticmethod
    def _alignment_run_artifact_paths(run: dict) -> dict:
        layout = RunArtifactLayout(Path(run["runs_dir"]))

        return {
            "run_contract": layout.relative(layout.run_contract_path),
            "task_verdict": layout.relative(layout.task_verdict_path),
            "evidence_ledger": layout.relative(layout.evidence_ledger_path),
            "evidence_coverage": layout.relative(layout.evidence_coverage_path),
            "evidence_manifest": layout.relative(layout.evidence_manifest_path),
        }

    @staticmethod
    def _alignment_run_judgment_contract(run: dict) -> dict:
        return build_judgment_contract(run)

    def _alignment_run_evidence_summary(self, run: dict, *, limit: int = 8) -> list[dict]:
        layout = self._run_artifact_layout(Path(run["runs_dir"]))
        if not layout.evidence_ledger_path.exists():
            return []
        items = [
            {
                "id": str(item.get("id") or ""),
                "kind": str(item.get("evidence_kind") or ""),
                "archetype": str(item.get("archetype") or ""),
                "step_id": str(item.get("step_id") or ""),
                "claim": str(item.get("claim") or "")[:500],
                "result": str(item.get("result") or ""),
                "residual_risk": str(item.get("residual_risk") or "")[:300],
                "verifies": self._alignment_source_string_list(item.get("verifies"), limit=8),
                "artifact_refs": self._alignment_source_artifact_refs(item.get("artifact_refs"), limit=6),
            }
            for item in read_jsonl(layout.evidence_ledger_path)
        ]
        return items[-limit:]

    @staticmethod
    def _alignment_source_string_list(value: object, *, limit: int) -> list[str]:
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, str)][:limit]

    @staticmethod
    def _alignment_source_artifact_refs(value: object, *, limit: int) -> list[dict]:
        if not isinstance(value, list):
            return []
        refs: list[dict] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            refs.append(
                {
                    key: item.get(key, "") if isinstance(item.get(key, ""), str) else ""
                    for key in ALIGNMENT_SOURCE_ARTIFACT_REF_KEYS
                }
            )
            if len(refs) >= limit:
                break
        return refs

    def _alignment_run_coverage_summary(self, run: dict) -> dict:
        layout = self._run_artifact_layout(Path(run["runs_dir"]))
        projection = load_or_build_evidence_coverage_projection(layout)
        summary = summarize_evidence_coverage_projection(
            projection,
            coverage_path_available=layout.evidence_coverage_path.exists(),
        )
        return {
            "ledger_path": summary.get("ledger_path", ""),
            "status": summary.get("status", ""),
            "reason": (summary.get("summary") or {}).get("reason", ""),
            "coverage_path": summary.get("coverage_path", ""),
            "evidence_count": summary.get("evidence_count", 0),
            "check_count": summary.get("check_count", 0),
            "covered_check_count": summary.get("covered_check_count", 0),
            "missing_check_count": summary.get("missing_check_count", 0),
            "covered_check_ids": list(summary.get("covered_check_ids") or [])[:20],
            "missing_check_ids": list(summary.get("missing_check_ids") or [])[:20],
            "target_count": summary.get("target_count", 0),
            "covered_target_count": summary.get("covered_target_count", 0),
            "weak_target_count": summary.get("weak_target_count", 0),
            "missing_target_count": summary.get("missing_target_count", 0),
            "blocked_target_count": summary.get("blocked_target_count", 0),
            "top_gaps": list(summary.get("top_gaps") or [])[:5],
            "evidence_kind_counts": summary.get("evidence_kind_counts") or {},
            "artifact_ref_count": summary.get("artifact_ref_count", 0),
            "residual_risk_count": summary.get("residual_risk_count", 0),
            "risk_signals": list(summary.get("risk_signals") or [])[:5],
            "latest_gatekeeper": summary.get("latest_gatekeeper") or {},
        }

    def _execute_alignment_session(self, session_id: str) -> None:
        key = self._alignment_thread_key(session_id)
        state = AlignmentExecutionState()
        try:
            while True:
                output = self._run_alignment_executor(
                    session_id,
                    mode=state.mode,
                    validation_error=state.validation_error,
                    invalid_yaml=state.invalid_yaml,
                )
                session = self.get_alignment_session(session_id)
                session = self._apply_alignment_output_stage(session_id, session, output)
                assistant_message, bundle_yaml, decision_options, missing_items = self._alignment_output_message_bundle_and_options(
                    session_id,
                    session,
                    output,
                )
                if assistant_message:
                    self._record_alignment_assistant_message(session_id, session, assistant_message, decision_options=decision_options, missing_items=missing_items)

                if bundle_yaml:
                    next_state = self._handle_alignment_bundle_candidate(session_id, bundle_yaml)
                    if next_state is None:
                        return
                    state = next_state
                    continue

                if self._alignment_needs_user_input(output) or self._alignment_blocked_output_waits_for_user(
                    output,
                    assistant_message=assistant_message,
                ):
                    self.repository.update_alignment_session(
                        session_id,
                        status="waiting_user",
                        finished_at=utc_now(),
                        clear_active_child_pid=True,
                        error_message="",
                    )
                    self.repository.append_alignment_event(
                        session_id,
                        "alignment_waiting_user",
                        {"status": "waiting_user"},
                    )
                    return
                message = assistant_message or "Agent finished without a bundle or a clarifying question."
                self._fail_alignment_session(session_id, message)
                return
        except ExecutionStopped:
            self._fail_alignment_session(session_id, "Cancelled by user.", event_type="alignment_cancelled")
        except Exception as exc:  # noqa: BLE001 - alignment worker crash boundary must persist session failure.
            log_exception(
                logger,
                "service.alignment.failed",
                "Alignment session failed",
                error=exc,
                session_id=session_id,
            )
            self._fail_alignment_session(session_id, str(exc) or type(exc).__name__)
        finally:
            self.repository.update_alignment_session(session_id, clear_active_child_pid=True)
            thread = self._threads.get(key)
            if (thread is threading.current_thread()) or (thread is not None and not thread.is_alive()):
                self._threads.pop(key, None)

    @staticmethod
    def _alignment_blocked_output_waits_for_user(output: dict, *, assistant_message: str) -> bool:
        if not assistant_message.strip():
            return False
        status = str(output.get("status", "") or "").strip().lower()
        phase = str(output.get("alignment_phase", "") or "").strip().lower()
        return status == "blocked" or phase == "blocked"

    def _alignment_output_message_bundle_and_options(self, session_id: str, session: dict, output: dict) -> tuple[str, str, list[dict], list[str] | None]:
        assistant_message = str(output.get("assistant_message", "") or "").strip()
        bundle_yaml = str(output.get("bundle_yaml", "") or "").strip()
        missing_items = self._normalize_alignment_missing_items(output.get("alignment_missing_items"))
        stage_error = self._alignment_bundle_stage_error(session, output) if bundle_yaml else ""
        if not stage_error:
            if assistant_message and self._alignment_assistant_message_language_issue(session, assistant_message):
                self.repository.append_alignment_event(
                    session_id,
                    "alignment_language_mismatch",
                    {"missing": ["assistant_message"], "surface": "assistant_message"},
                )
                assistant_message = self._fallback_alignment_assistant_message(output, has_bundle=bool(bundle_yaml))
                output["decision_options"] = self._default_alignment_decision_options(session)
            decision_options = self._visible_alignment_decision_options(session, output, has_bundle=bool(bundle_yaml))
            return assistant_message, bundle_yaml, decision_options, missing_items
        output["needs_user_input"] = True
        self.repository.append_alignment_event(
            session_id,
            "alignment_stage_blocked",
            {"status": "waiting_user", "error": stage_error},
        )
        output["decision_options"] = self._default_alignment_decision_options(session)
        return stage_error, "", self._visible_alignment_decision_options(session, output, has_bundle=False), None

    @classmethod
    def _alignment_assistant_message_language_issue(cls, session: dict, assistant_message: str) -> bool:
        return cls._alignment_generation_prefers_chinese(session) and not cls._text_has_cjk(assistant_message)

    @staticmethod
    def _fallback_alignment_assistant_message(output: dict, *, has_bundle: bool) -> str:
        if has_bundle:
            return "已整理成一个可导入的 Loopora bundle。"
        if ServiceAlignmentMixin._alignment_needs_user_input(output):
            return "我需要继续用中文对齐；请先确认一个会改变 Loop 形状的点：这次更怕结果看起来完成但证据不足，还是推进太慢？"
        return "我需要继续用中文对齐后再继续。"

    def _record_alignment_assistant_message(
        self,
        session_id: str,
        session: dict,
        assistant_message: str,
        *,
        decision_options: list[dict] | None = None,
        missing_items: list[str] | None = None,
    ) -> None:
        transcript = list(session.get("transcript") or [])
        entry = {"role": "assistant", "content": assistant_message, "created_at": utc_now()}
        normalized_options = self._normalize_alignment_decision_options(decision_options)
        if normalized_options:
            entry["decision_options"] = normalized_options
        if missing_items:
            entry["missing_items"] = missing_items
        transcript.append(entry)
        self.repository.update_alignment_session(session_id, transcript=transcript)
        self._write_alignment_transcript_log(self.get_alignment_session(session_id))
        event_payload = {"role": "assistant", "content": assistant_message}
        if normalized_options:
            event_payload["decision_options"] = normalized_options
        if missing_items:
            event_payload["missing_items"] = missing_items
        self.repository.append_alignment_event(
            session_id,
            "alignment_message",
            event_payload,
        )

    def _handle_alignment_bundle_candidate(
        self,
        session_id: str,
        bundle_yaml: str,
    ) -> AlignmentExecutionState | None:
        ok, error = self._write_and_validate_alignment_bundle(session_id, bundle_yaml)
        if ok:
            self.repository.update_alignment_session(
                session_id,
                status="ready",
                alignment_stage="ready",
                finished_at=utc_now(),
                clear_active_child_pid=True,
                error_message="",
            )
            self.repository.append_alignment_event(
                session_id,
                "alignment_ready",
                {"status": "ready", "bundle_path": self.get_alignment_session(session_id)["bundle_path"]},
            )
            return None
        session = self.get_alignment_session(session_id)
        repair_attempts = self._alignment_repair_attempts(session, invalid_default=1)
        if repair_attempts >= 1:
            self._fail_alignment_session(session_id, error)
            return None
        self.repository.update_alignment_session(
            session_id,
            status="repairing",
            repair_attempts=repair_attempts + 1,
            error_message=error,
        )
        self.repository.append_alignment_event(
            session_id,
            "alignment_repair_started",
            {"status": "repairing", "error": error},
        )
        return AlignmentExecutionState(
            mode="repair",
            validation_error=error,
            invalid_yaml=bundle_yaml,
        )

    def _run_alignment_executor(
        self,
        session_id: str,
        *,
        mode: str,
        validation_error: str = "",
        invalid_yaml: str = "",
    ) -> dict:
        session = self.get_alignment_session(session_id)
        root = self._alignment_session_root(session)
        self._ensure_alignment_artifact_dirs(root)
        attempt = self._alignment_repair_attempts(session)
        invocation_dir = self._alignment_next_invocation_dir(root, attempt, repair=mode == "repair")
        invocation_dir.mkdir(parents=True, exist_ok=True)
        output_path = invocation_dir / "output.json"
        prompt = self._build_alignment_prompt(
            session,
            mode=mode,
            validation_error=validation_error,
            invalid_yaml=invalid_yaml,
        )
        (invocation_dir / "prompt.md").write_text(prompt.rstrip() + "\n", encoding="utf-8")
        (invocation_dir / "schema.json").write_text(
            json.dumps(ALIGNMENT_RESPONSE_SCHEMA, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (invocation_dir / "stdout.log").touch(exist_ok=True)
        (invocation_dir / "stderr.log").touch(exist_ok=True)
        executor_session_ref = session.get("executor_session_ref") if isinstance(session.get("executor_session_ref"), dict) else {}
        resume_session_id = str((executor_session_ref or {}).get("session_id", "") or "").strip()
        request = RoleRequest(
            run_id=f"alignment:{session_id}",
            role="alignment",
            role_archetype="alignment",
            role_name="Bundle Alignment",
            prompt=prompt,
            workdir=Path(session["workdir"]),
            model=str(session.get("model", "") or ""),
            reasoning_effort=str(session.get("reasoning_effort", "") or ""),
            output_schema=ALIGNMENT_RESPONSE_SCHEMA,
            output_path=output_path,
            run_dir=invocation_dir,
            executor_kind=session.get("executor_kind", "codex"),
            executor_mode=session.get("executor_mode", "preset"),
            command_cli=session.get("command_cli", ""),
            command_args_text=session.get("command_args_text", ""),
            inherit_session=True,
            resume_session_id=resume_session_id,
            sandbox="read-only",
            idle_timeout_seconds=self.settings.role_idle_timeout_seconds,
            extra_context={
                "target_workdir": session["workdir"],
                "alignment_session_id": session_id,
                "alignment_mode": mode,
                "alignment_stage": session.get("alignment_stage", "clarifying"),
                "working_agreement": session.get("working_agreement") or {},
                "validation_error": validation_error,
                "session_ref": executor_session_ref or {},
                "invocation_id": invocation_dir.name,
                "prefers_chinese": self._alignment_generation_prefers_chinese(session),
            },
        )
        executor = self.executor_factory()
        output = self._execute_alignment_request_with_resume_fallback(session_id, executor, request)
        self._finalize_alignment_invocation_files(invocation_dir, output, Path(session["bundle_path"]))
        self._persist_alignment_executor_session_ref(session_id, request, output)
        return output

    def _execute_alignment_request_with_resume_fallback(self, session_id: str, executor, request: RoleRequest) -> dict:
        try:
            return self._execute_alignment_request(session_id, executor, request)
        except ExecutorError:
            if not request.resume_session_id.strip() or request.executor_kind not in {"codex", "claude", "opencode"}:
                raise
            self.repository.append_alignment_event(
                session_id,
                "alignment_native_resume_fallback",
                {
                    "executor_kind": request.executor_kind,
                    "resume_session_id": request.resume_session_id,
                    "message": "Native CLI session resume failed; retrying with Loopora transcript context.",
                },
            )
            request.inherit_session = False
            request.resume_session_id = ""
            request.extra_context["session_ref"] = {}
            return self._execute_alignment_request(session_id, executor, request)

    def _execute_alignment_request(self, session_id: str, executor, request: RoleRequest) -> dict:
        invocation_id = str(request.extra_context.get("invocation_id", "") or "")
        stdout_path = request.run_dir / "stdout.log"

        def emit_alignment_event(event_type: str, payload: dict) -> dict:
            sanitized = self._sanitize_alignment_event_payload(event_type, payload, invocation_id=invocation_id)
            if event_type == "codex_event":
                message = str(sanitized.get("message", "") or "").strip()
                if message:
                    with stdout_path.open("a", encoding="utf-8") as handle:
                        handle.write(message + "\n")
            return self.repository.append_alignment_event(
                session_id,
                event_type,
                {
                    **sanitized,
                    "alignment_status": self.get_alignment_session(session_id)["status"],
                },
            )

        return executor.execute(
            request,
            emit_alignment_event,
            lambda: self.repository.alignment_should_stop(session_id),
            lambda pid: (
                self.repository.update_alignment_session(session_id, active_child_pid=pid)
                if pid is not None
                else self.repository.update_alignment_session(session_id, clear_active_child_pid=True)
            ),
        )

    def _persist_alignment_executor_session_ref(self, session_id: str, request: RoleRequest, output: dict) -> None:
        current = request.extra_context.get("session_ref")
        session_ref = dict(current) if isinstance(current, dict) else {}
        output_ref = output.get("session_ref") if isinstance(output, dict) else None
        if isinstance(output_ref, dict):
            session_ref.update({str(key): str(value) for key, value in output_ref.items() if str(value).strip()})
        if not session_ref:
            return
        self.repository.update_alignment_session(session_id, executor_session_ref=session_ref)
        self.repository.append_alignment_event(
            session_id,
            "alignment_executor_session_ref",
            {
                "executor_kind": request.executor_kind,
                "session_ref": session_ref,
                "native_resume_available": bool(session_ref.get("session_id")),
            },
        )

    def _apply_alignment_output_stage(self, session_id: str, session: dict, output: dict) -> dict:
        phase = str(output.get("alignment_phase", "") or "").strip()
        agreement_summary = str(output.get("agreement_summary", "") or "").strip()
        checklist = output.get("readiness_checklist")
        readiness_evidence = output.get("readiness_evidence")
        if phase == "agreement" and agreement_summary:
            for issues, event_type, message in (
                (
                    self._agreement_readiness_checklist_issues(checklist),
                    "alignment_checklist_incomplete",
                    "我还不能整理确认协议；这些对齐检查还没完成：{missing}。请先问一个会改变 Loop 方案的问题。",
                ),
                (
                    self._readiness_evidence_issues(
                        output,
                        workdir_snapshot=self._alignment_workdir_snapshot(Path(session["workdir"])),
                    ),
                    "alignment_evidence_incomplete",
                    "我还不能整理确认协议；这些对齐证据还不够具体：{missing}。请先补一个会改变 Loop 方案的问题。",
                ),
                (
                    self._alignment_improvement_readiness_issues(session, output),
                    "alignment_improvement_incomplete",
                    "我还不能整理改进协议；这些基于已有方案的改进判断还不够具体：{missing}。请先补一个会改变 Loop 方案的问题。",
                ),
                (
                    self._agreement_language_issues(session, output),
                    "alignment_language_mismatch",
                    "我还不能整理确认协议；用户可见工作协议需要使用中文：{missing}。请用中文重写这些判断。",
                ),
            ):
                if issues:
                    return self._block_alignment_agreement(
                        session,
                        output,
                        event_type=event_type,
                        missing=issues,
                        message=message,
                    )
            normalized_checklist = dict(checklist) if isinstance(checklist, dict) else {}
            normalized_checklist["explicit_confirmation"] = False
            working_agreement = {
                "summary": agreement_summary,
                "readiness_checklist": normalized_checklist,
                "readiness_evidence": readiness_evidence if isinstance(readiness_evidence, dict) else {},
                "captured_at": utc_now(),
                "confirmed_at": "",
                "confirmation_message": "",
            }
            working_agreement = self._merge_alignment_improvement_context(
                session.get("working_agreement"),
                working_agreement,
            )
            output["assistant_message"] = self._visible_alignment_agreement_message(session, working_agreement)
            updated = self.repository.update_alignment_session(
                session_id,
                alignment_stage="agreement_ready",
                working_agreement=working_agreement,
            )
            self.repository.append_alignment_event(
                session_id,
                "alignment_agreement_ready",
                {"alignment_stage": "agreement_ready", "working_agreement": working_agreement},
            )
            output["needs_user_input"] = True
            output["bundle_yaml"] = ""
            output["decision_options"] = self._agreement_confirmation_decision_options(session)
            return self._decorate_alignment_session(updated)
        if phase == "clarifying":
            updated = self.repository.update_alignment_session(session_id, alignment_stage="clarifying")
            question_issues = self._alignment_clarifying_question_issues(output)
            if question_issues:
                if self._alignment_prefers_chinese(session):
                    output["assistant_message"] = (
                        "我先给一个推荐判断：默认应该优先阻断“看起来完成但证据不足”的结果，"
                        "这样后续运行不会靠漂亮叙事过关。你可以直接选推荐，也可以改成更偏速度的方向。"
                    )
                else:
                    output["assistant_message"] = (
                        "My recommended default is to block results that look done but lack evidence, so the run cannot "
                        "pass on a polished story alone. You can choose that recommendation or switch toward speed."
                    )
                output["decision_options"] = self._default_alignment_decision_options(session)
                output["needs_user_input"] = True
                output["bundle_yaml"] = ""
                self.repository.append_alignment_event(
                    session_id,
                    "alignment_question_reframed",
                    {"alignment_stage": "clarifying", "issues": question_issues},
                )
            return self._decorate_alignment_session(updated)
        return session

    def _block_alignment_agreement(
        self,
        session: dict,
        output: dict,
        *,
        event_type: str,
        missing: list[str],
        message: str,
    ) -> dict:
        session_id = str(session["id"])
        updated = self.repository.update_alignment_session(session_id, alignment_stage="clarifying")
        output["alignment_phase"] = "clarifying"
        output["agreement_summary"] = ""
        output["bundle_yaml"] = ""
        output["needs_user_input"] = True
        output["alignment_missing_items"] = missing
        output["assistant_message"] = self._alignment_block_message(
            session,
            event_type=event_type,
            missing=missing,
            fallback_zh=message,
        )
        self.repository.append_alignment_event(
            session_id,
            event_type,
            {"alignment_stage": "clarifying", "missing": missing},
        )
        return self._decorate_alignment_session(updated)

    @classmethod
    def _alignment_block_message(
        cls,
        session: dict,
        *,
        event_type: str,
        missing: list[str],
        fallback_zh: str,
    ) -> str:
        labels = ", ".join(missing)
        if cls._alignment_prefers_chinese(session):
            return fallback_zh.format(missing=labels)
        if event_type == "alignment_checklist_incomplete":
            return (
                "I can't prepare the confirmation agreement yet; these readiness checks are incomplete: "
                f"{labels}. Please answer the next Loop-shaping question first."
            )
        if event_type == "alignment_evidence_incomplete":
            return (
                "I can't prepare the confirmation agreement yet; this readiness evidence is not specific enough: "
                f"{labels}. Please answer the next Loop-shaping question first."
            )
        if event_type == "alignment_improvement_incomplete":
            return (
                "I can't prepare the improvement agreement yet; these source-based improvement judgments "
                f"are not specific enough: {labels}. Please answer the next Loop-shaping question first."
            )
        if event_type == "alignment_language_mismatch":
            return (
                "I can't prepare the confirmation agreement yet; these user-facing agreement fields need "
                f"the user's language: {labels}. Please rewrite those judgments."
            )
        return fallback_zh.format(missing=labels)

    @classmethod
    def _visible_alignment_decision_options(cls, session: dict, output: dict, *, has_bundle: bool) -> list[dict]:
        if has_bundle:
            return []
        phase = str(output.get("alignment_phase", "") or "").strip().lower()
        status = str(output.get("status", "") or "").strip().lower()
        if not cls._alignment_needs_user_input(output) and phase != "blocked" and status != "blocked":
            return []
        options = cls._normalize_alignment_decision_options(output.get("decision_options"))
        if cls._alignment_decision_options_are_visible(options):
            return options
        if phase == "agreement":
            return cls._agreement_confirmation_decision_options(session)
        if phase == "blocked" or status == "blocked":
            return cls._not_fit_alignment_decision_options(session)
        return cls._default_alignment_decision_options(session)

    @classmethod
    def _normalize_alignment_missing_items(cls, raw_items: object) -> list[str]:
        if not isinstance(raw_items, list):
            return []
        items: list[str] = []
        seen: set[str] = set()
        for raw_item in raw_items:
            item = str(raw_item or "").strip()
            if item not in ALIGNMENT_MISSING_ITEM_IDS or item in seen:
                continue
            seen.add(item)
            items.append(item)
            if len(items) >= 12:
                break
        return items

    @classmethod
    def _normalize_alignment_decision_options(cls, raw_options: object) -> list[dict]:
        if not isinstance(raw_options, list):
            return []
        options: list[dict] = []
        seen_ids: set[str] = set()
        for index, item in enumerate(raw_options[:4], start=1):
            if not isinstance(item, dict):
                continue
            label = cls._agreement_text_snippet(item.get("label"), limit=80)
            description = cls._agreement_text_snippet(item.get("description"), limit=220)
            user_reply = cls._agreement_text_snippet(item.get("user_reply"), limit=260)
            if not label or not description or not user_reply:
                continue
            option_id = str(item.get("id") or f"option_{index}").strip()
            option_id = re.sub(r"[^A-Za-z0-9_.:-]+", "-", option_id).strip("-") or f"option_{index}"
            if option_id in seen_ids:
                option_id = f"{option_id}-{index}"
            seen_ids.add(option_id)
            options.append(
                {
                    "id": option_id,
                    "label": label,
                    "description": description,
                    "recommended": item.get("recommended") is True,
                    "user_reply": user_reply,
                }
            )
        return options

    @classmethod
    def _alignment_has_recommended_decision_options(cls, output: dict) -> bool:
        options = cls._normalize_alignment_decision_options(output.get("decision_options"))
        return cls._alignment_decision_options_are_visible(options)

    @staticmethod
    def _alignment_needs_user_input(output: dict) -> bool:
        return output.get("needs_user_input") is True

    @staticmethod
    def _alignment_decision_options_are_visible(options: list[dict]) -> bool:
        return len(options) >= 2 and any(option.get("recommended") is True for option in options)

    @staticmethod
    def _default_alignment_decision_options(session: dict) -> list[dict]:
        if ServiceAlignmentMixin._alignment_prefers_chinese(session):
            return [
                {
                    "id": "evidence_first",
                    "label": "优先阻断假完成（推荐）",
                    "description": "少做一点也可以，但必须证明核心路径真的成立。",
                    "recommended": True,
                    "user_reply": "采用推荐：优先阻断看起来完成但证据不足的结果，少而真实也可以。",
                },
                {
                    "id": "speed_first",
                    "label": "优先快速推进",
                    "description": "先交一个更务实的首版，允许部分残余风险保持可见。",
                    "recommended": False,
                    "user_reply": "我选择优先快速推进，可以接受部分残余风险保持可见。",
                },
                {
                    "id": "add_judgment",
                    "label": "我补充判断",
                    "description": "我想说明另一种更重要的完成标准或风险。",
                    "recommended": False,
                    "user_reply": "我想补充另一种判断：",
                },
            ]
        return [
            {
                "id": "evidence_first",
                "label": "Block fake done (Recommended)",
                "description": "A smaller result is acceptable, but the core path must be proven.",
                "recommended": True,
                "user_reply": "Use the recommendation: block results that look done but lack evidence, even if the first version is smaller.",
            },
            {
                "id": "speed_first",
                "label": "Move faster",
                "description": "Ship a more pragmatic first pass and keep residual risks visible.",
                "recommended": False,
                "user_reply": "I choose speed first and can accept visible residual risks.",
            },
            {
                "id": "add_judgment",
                "label": "I'll add judgment",
                "description": "I want to name a different completion standard or risk.",
                "recommended": False,
                "user_reply": "I want to add another judgment:",
            },
        ]

    @staticmethod
    def _agreement_confirmation_decision_options(session: dict) -> list[dict]:
        if ServiceAlignmentMixin._alignment_prefers_chinese(session):
            return [
                {
                    "id": "confirm_agreement",
                    "label": "采用这个方向（推荐）",
                    "description": "按这份工作协议生成 Loop 方案。",
                    "recommended": True,
                    "user_reply": "确认，采用这个方向。",
                },
                {
                    "id": "adjust_agreement",
                    "label": "我想调整",
                    "description": "先修改其中一个判断，再生成方案。",
                    "recommended": False,
                    "user_reply": "我想调整这份工作协议：",
                },
            ]
        return [
            {
                "id": "confirm_agreement",
                "label": "Use this direction (Recommended)",
                "description": "Generate the Loop plan from this working agreement.",
                "recommended": True,
                "user_reply": "Confirm; use this direction.",
            },
            {
                "id": "adjust_agreement",
                "label": "I want changes",
                "description": "Revise one judgment before generating the plan.",
                "recommended": False,
                "user_reply": "I want to adjust this working agreement:",
            },
        ]

    @staticmethod
    def _not_fit_alignment_decision_options(session: dict) -> list[dict]:
        if ServiceAlignmentMixin._alignment_prefers_chinese(session):
            return [
                {
                    "id": "skip_loop",
                    "label": "先不生成 Loop（推荐）",
                    "description": "这更像一次性任务，不需要额外编排。",
                    "recommended": True,
                    "user_reply": "同意，先不生成 Loop 方案。",
                },
                {
                    "id": "still_compile",
                    "label": "仍然编排",
                    "description": "我会说明需要继承的反复判断或新证据。",
                    "recommended": False,
                    "user_reply": "仍然需要编排，因为这套判断需要被后续运行继承：",
                },
            ]
        return [
            {
                "id": "skip_loop",
                "label": "Skip Loop for now (Recommended)",
                "description": "This looks like a one-off task that does not need governance.",
                "recommended": True,
                "user_reply": "Agreed, do not generate a Loop plan for now.",
            },
            {
                "id": "still_compile",
                "label": "Still compose it",
                "description": "I will explain the repeated judgment or new evidence this run must inherit.",
                "recommended": False,
                "user_reply": "I still need a Loop because this judgment should be inherited by the run:",
            },
        ]

    @staticmethod
    def _alignment_clarifying_question_issues(output: dict) -> list[str]:
        if not ServiceAlignmentMixin._alignment_needs_user_input(output):
            return []
        message = str(output.get("assistant_message", "") or "").strip()
        if not message:
            return []
        normalized = message.lower()
        issues: list[str] = []
        mechanical_terms = (
            "yaml",
            "bundle",
            "spec",
            "role_definition",
            "role definition",
            "role_definition_key",
            "workflow",
            "parallel_group",
            "parallel group",
            "controls",
            "builder",
            "inspector",
            "gatekeeper",
            "guide",
            "配置",
            "方案文件",
            "角色",
            "工作流",
            "并行组",
        )
        config_verbs = (
            "configure",
            "set up",
            "select",
            "choose",
            "use",
            "enable",
            "add",
            "want",
            "配置",
            "选择",
            "要不要",
            "是否需要",
            "启用",
            "添加",
            "扮演",
        )
        task_risk_terms = (
            "risk",
            "afraid",
            "worry",
            "fake",
            "evidence",
            "proof",
            "trust",
            "block",
            "strict",
            "done",
            "residual",
            "progress",
            "drift",
            "风险",
            "怕",
            "担心",
            "假完成",
            "证据",
            "证明",
            "信任",
            "阻断",
            "严格",
            "完成",
            "残余",
            "进展",
            "偏差",
        )
        has_mechanics = ServiceAlignmentMixin._has_any_marker(normalized, mechanical_terms)
        has_config = ServiceAlignmentMixin._has_any_marker(normalized, config_verbs)
        has_task_risk = ServiceAlignmentMixin._has_any_marker(normalized, task_risk_terms)
        if has_mechanics and has_config and not has_task_risk:
            issues.append("mechanical_configuration_question")
        if ServiceAlignmentMixin._alignment_questionnaire_overload(message):
            issues.append("questionnaire_overload")
        generic_patterns = (
            "do you want high quality",
            "what are your preferences",
            "what preferences do you have",
            "tell me your preferences",
            "what do you prefer",
            "what quality level do you want",
            "what is your preferred collaboration style",
            "what roles do you want",
            "what role should i play",
            "你要高质量吗",
            "你有什么偏好",
            "你的偏好是什么",
            "你想要什么质量",
            "你希望质量怎么样",
            "你喜欢什么风格",
            "你希望我扮演什么角色",
            "你想要哪些角色",
        )
        if ServiceAlignmentMixin._has_any_marker(normalized, generic_patterns):
            issues.append("generic_alignment_question")
        if not ServiceAlignmentMixin._alignment_has_recommended_decision_options(output):
            issues.append("missing_recommended_decision_options")
        return issues

    @staticmethod
    def _alignment_questionnaire_overload(message: str) -> bool:
        question_marks = message.count("?") + message.count("？")
        if question_marks >= 4:
            return True
        question_lines = 0
        question_line_re = re.compile(r"^\s*(?:[-*]|\d+[.)、]|[一二三四五六七八九十]+[、.])\s*")
        question_cues = (
            "?",
            "？",
            "请说明",
            "请描述",
            "请列出",
            "what ",
            "which ",
            "whether ",
            "how ",
            "do you ",
            "would you ",
        )
        for line in message.splitlines():
            normalized_line = line.strip().lower()
            if question_line_re.match(normalized_line) and ServiceAlignmentMixin._has_any_marker(normalized_line, question_cues):
                question_lines += 1
        return question_lines >= 3

    @staticmethod
    def _alignment_bundle_stage_error(session: dict, output: dict) -> str:
        stage = str(session.get("alignment_stage", "") or "clarifying").strip()
        phase = str(output.get("alignment_phase", "") or "").strip()
        agreement_summary = str(output.get("agreement_summary", "") or "").strip()
        checklist = output.get("readiness_checklist")
        missing = [key for key in ALIGNMENT_READINESS_KEYS if isinstance(checklist, dict) and checklist.get(key) is not True]
        evidence_issues = ServiceAlignmentMixin._readiness_evidence_issues(
            output,
            workdir_snapshot=ServiceAlignmentMixin._alignment_workdir_snapshot(Path(session["workdir"])),
        )
        improvement_issues = ServiceAlignmentMixin._alignment_improvement_readiness_issues(session, output)
        language_issues = ServiceAlignmentMixin._agreement_language_issues(session, output)
        error = ""
        prefers_chinese = ServiceAlignmentMixin._alignment_prefers_chinese(session)
        if stage not in ALIGNMENT_CONFIRMED_STAGES:
            error = (
                "我还需要先完成需求对齐并得到你的明确确认，再生成 Loop 方案。"
                if prefers_chinese
                else "I need to finish alignment and get your explicit confirmation before generating the Loop plan."
            )
        elif phase != "bundle":
            error = (
                "我还需要先完成需求对齐，再生成 Loop 方案。请先确认边界、成功标准和协作方式。"
                if prefers_chinese
                else (
                    "I need to finish alignment before generating the Loop plan. Please confirm the boundary, success criteria, and collaboration shape first."
                )
            )
        elif not agreement_summary:
            error = (
                "我还需要先整理一份工作协议摘要并得到确认，然后再生成 Loop 方案。"
                if prefers_chinese
                else "I need a confirmed working agreement summary before generating the Loop plan."
            )
        elif not isinstance(checklist, dict):
            error = (
                "我还需要先补齐对齐检查清单，再生成 Loop 方案。"
                if prefers_chinese
                else "I need the alignment readiness checklist before generating the Loop plan."
            )
        elif missing:
            labels = ", ".join(missing)
            error = (
                f"我还不能直接生成 Loop 方案；对齐检查还缺：{labels}。请先补齐这些信息。"
                if prefers_chinese
                else (f"I can't generate the Loop plan yet; these readiness checks are incomplete: {labels}. Please fill in this information first.")
            )
        elif evidence_issues:
            labels = ", ".join(evidence_issues)
            error = (
                f"我还不能直接生成 Loop 方案；这些对齐证据还不够具体：{labels}。请先补齐这些信息。"
                if prefers_chinese
                else (f"I can't generate the Loop plan yet; this readiness evidence is not specific enough: {labels}. Please fill in this information first.")
            )
        elif improvement_issues:
            labels = ", ".join(improvement_issues)
            error = (
                f"我还不能直接生成 Loop 方案；这些改进判断还不够具体：{labels}。请先补齐这些信息。"
                if prefers_chinese
                else (
                    f"I can't generate the Loop plan yet; these improvement judgments are not specific enough: {labels}. Please fill in this information first."
                )
            )
        elif language_issues:
            labels = ", ".join(language_issues)
            error = f"我还不能直接生成 Loop 方案；这些用户可见对齐证据需要使用中文：{labels}。请先补齐这些信息。"
        return error

    @staticmethod
    def _agreement_readiness_checklist_issues(checklist: object) -> list[str]:
        if not isinstance(checklist, dict):
            return ["readiness_checklist"]
        return [key for key in ALIGNMENT_READINESS_KEYS if key != "explicit_confirmation" and checklist.get(key) is not True]

    @classmethod
    def _agreement_language_issues(cls, session: dict, output: dict) -> list[str]:
        if not cls._alignment_generation_prefers_chinese(session):
            return []
        issues = []
        if not cls._text_has_cjk(output.get("agreement_summary")):
            issues.append("agreement_summary")
        evidence = output.get("readiness_evidence")
        if not isinstance(evidence, dict):
            return [*issues, "readiness_evidence"]
        issues.extend(key for key in ALIGNMENT_READINESS_EVIDENCE_KEYS if not cls._text_has_cjk(evidence.get(key)))
        return issues

    @staticmethod
    def _alignment_bundle_executor_settings_issues(session: dict, bundle: dict) -> list[str]:
        expected_kind = str(session.get("executor_kind", "") or "").strip()
        expected_mode = str(session.get("executor_mode", "") or "").strip()
        if expected_kind != "custom" and expected_mode != "command":
            return []
        expected = {
            "executor_kind": expected_kind,
            "executor_mode": expected_mode,
            "command_cli": str(session.get("command_cli", "") or ""),
            "command_args_text": str(session.get("command_args_text", "") or ""),
            "model": str(session.get("model", "") or "").strip(),
            "reasoning_effort": str(session.get("reasoning_effort", "") or "").strip(),
        }
        mismatches: list[str] = []
        runtime_surfaces: list[tuple[str, dict]] = []
        if isinstance(bundle.get("loop"), dict):
            runtime_surfaces.append(("loop", bundle["loop"]))
        for role in bundle.get("role_definitions", []):
            if not isinstance(role, dict):
                continue
            role_key = str(role.get("key", "") or "role")
            runtime_surfaces.append((f"role_definition {role_key}", role))
        for surface_name, surface in runtime_surfaces:
            for field_name, expected_value in expected.items():
                actual_value = str(surface.get(field_name, "") or "")
                if field_name in {"model", "reasoning_effort"}:
                    actual_value = actual_value.strip()
                if actual_value != expected_value:
                    mismatches.append(f"{surface_name}.{field_name}")
        if not mismatches:
            return []
        return ["alignment bundle must preserve selected Web executor settings for command/custom sessions: " + ", ".join(mismatches[:8])]

    @classmethod
    def _alignment_bundle_language_issues(cls, session: dict, bundle: dict) -> list[str]:
        if not cls._alignment_generation_prefers_chinese(session):
            return []
        issues = []
        metadata = bundle.get("metadata") if isinstance(bundle.get("metadata"), dict) else {}
        loop = bundle.get("loop") if isinstance(bundle.get("loop"), dict) else {}
        field_values = {
            "metadata.name": metadata.get("name"),
            "metadata.description": metadata.get("description"),
            "loop.name": loop.get("name"),
            "collaboration_summary": bundle.get("collaboration_summary"),
            "spec.markdown": (bundle.get("spec") or {}).get("markdown") if isinstance(bundle.get("spec"), dict) else "",
            "workflow.collaboration_intent": ((bundle.get("workflow") or {}).get("collaboration_intent") if isinstance(bundle.get("workflow"), dict) else ""),
        }
        issues.extend(
            f"bundle field {field_name} must follow Chinese user language" for field_name, value in field_values.items() if not cls._text_has_cjk(value)
        )
        for role in bundle.get("role_definitions", []):
            if not isinstance(role, dict):
                continue
            key = str(role.get("key", "") or "role")
            issues.extend(
                f"bundle role_definition {key}.{field_name} must follow Chinese user language"
                for field_name in ("name", "description", "prompt_markdown", "posture_notes")
                if not cls._text_has_cjk(role.get(field_name))
            )
        return issues

    @classmethod
    def _alignment_bundle_workdir_fact_issues(cls, session: dict, bundle: dict) -> list[str]:
        workdir_snapshot = cls._alignment_workdir_snapshot(Path(session["workdir"]))
        fields: dict[str, object] = {
            "collaboration_summary": bundle.get("collaboration_summary"),
            "spec.markdown": (bundle.get("spec") or {}).get("markdown") if isinstance(bundle.get("spec"), dict) else "",
            "workflow.collaboration_intent": ((bundle.get("workflow") or {}).get("collaboration_intent") if isinstance(bundle.get("workflow"), dict) else ""),
        }
        for role in bundle.get("role_definitions", []):
            if not isinstance(role, dict):
                continue
            key = str(role.get("key", "") or "role")
            for field_name in ("description", "prompt_markdown", "posture_notes"):
                fields[f"role_definition {key}.{field_name}"] = role.get(field_name)
        return [
            f"bundle field {field_name} must not claim an observed workdir stack unsupported by Workdir Snapshot"
            for field_name, value in fields.items()
            if cls._workdir_facts_claims_unsupported_observed_stack(
                str(value or "").lower(),
                workdir_snapshot=workdir_snapshot,
            )
        ]

    @classmethod
    def _alignment_improvement_bundle_issues(cls, session: dict, bundle: dict) -> list[str]:
        agreement = session.get("working_agreement") if isinstance(session.get("working_agreement"), dict) else {}
        if str(agreement.get("mode") or "") != "improvement":
            return []
        text = cls._alignment_bundle_visible_text(bundle).lower()
        issues: list[str] = []
        if not cls._has_any_marker(
            text,
            (
                "source intent",
                "source loop",
                "source bundle",
                "source workdir",
                "source defaults",
                "source posture",
                "stable intent",
                "stable task intent",
                "existing loop",
                "existing bundle",
                "base candidate",
                "既有意图",
                "来源 loop",
                "来源 bundle",
                "来源意图",
                "稳定意图",
                "原 bundle",
            ),
        ):
            issues.append("improvement bundle must state what source intent, workdir, defaults, or posture is preserved")
        if not cls._has_any_marker(
            text,
            (
                "feedback-driven",
                "feedback",
                "run evidence",
                "evidence summary",
                "evidence gap",
                "gatekeeper verdict",
                "coverage",
                "delta",
                "反馈驱动",
                "反馈",
                "运行证据",
                "证据摘要",
                "证据缺口",
                "变化",
            ),
        ):
            issues.append("improvement bundle must state the feedback-driven governance delta")
        if not cls._has_any_marker(
            text,
            (
                "spec",
                "role",
                "roles",
                "workflow",
                "evidence",
                "gatekeeper",
                "证据",
                "角色",
                "裁决",
                "治理面",
                "任务契约",
            ),
        ):
            issues.append("improvement bundle must map the delta to spec, roles, workflow, evidence, or GateKeeper")
        source = agreement.get("source") if isinstance(agreement.get("source"), dict) else {}
        source_bundle_id = str(source.get("source_bundle_id") or "").strip()
        generated_bundle_id = str(bundle.get("metadata", {}).get("bundle_id") or "").strip()
        if source_bundle_id and generated_bundle_id == source_bundle_id:
            issues.append(
                "improvement bundle must not reuse the source bundle id as metadata.bundle_id; leave bundle_id empty or choose a new standalone candidate id"
            )
        has_run_context = str(source.get("source_type") or "") == "run" and (
            source.get("coverage_summary") or source.get("evidence_summary") or source.get("task_verdict") or source.get("gatekeeper_verdict")
        )
        if has_run_context and not cls._has_any_marker(
            text,
            (
                "run evidence",
                "coverage",
                "verdict",
                "gatekeeper verdict",
                "evidence summary",
                "运行证据",
                "覆盖",
                "裁决",
                "证据摘要",
            ),
        ):
            issues.append("improvement bundle must translate run evidence, coverage, or GateKeeper verdict into bundle changes")
        source_completion_mode = str(source.get("source_completion_mode") or "").strip().lower()
        if source_completion_mode and source_completion_mode != "gatekeeper":
            has_source_completion_mode_delta = cls._has_any_marker(
                text,
                (
                    "completion mode",
                    "completion_mode",
                    "`rounds`",
                    "rounds completion",
                    "source uses rounds",
                    "run lifecycle",
                    "lifecycle completion",
                    "source completion",
                    "完成模式",
                    "运行生命周期",
                    "生命周期收束",
                ),
            ) and cls._has_any_marker(
                text,
                (
                    "gatekeeper",
                    "task verdict",
                    "evidence-based verdict",
                    "证据裁决",
                    "loop 裁决",
                    "任务裁决",
                    "守门",
                ),
            )
            if not has_source_completion_mode_delta:
                issues.append("improvement bundle must state the source completion-mode governance delta")
        return issues

    @classmethod
    def _alignment_bundle_agreement_traceability_issues(cls, session: dict, bundle: dict) -> list[str]:
        agreement = session.get("working_agreement") if isinstance(session.get("working_agreement"), dict) else {}
        evidence = agreement.get("readiness_evidence") if isinstance(agreement.get("readiness_evidence"), dict) else {}
        bundle_text = cls._alignment_bundle_agreement_projection_text(bundle)
        normalized_bundle_text = cls._normalize_traceability_text(bundle_text)
        normalized_runtime_text = cls._normalize_traceability_text(cls._alignment_bundle_runtime_responsibility_projection_text(bundle))
        issues: list[str] = []
        if evidence:
            repeated_cjk_terms = cls._agreement_repeated_cjk_traceability_terms(evidence.values())
            for key in ALIGNMENT_AGREEMENT_TRACEABILITY_KEYS:
                terms = cls._agreement_traceability_terms(evidence.get(key))
                if key == "loop_fit":
                    terms = [term for term in terms if term not in ALIGNMENT_LOOP_FIT_TRACEABILITY_GENERIC_TERMS]
                terms.extend(term for term in repeated_cjk_terms if term in str(evidence.get(key) or "") and term not in terms)
                if key == "workdir_facts":
                    terms = [term for term in terms if "/" in term or "." in term]
                if key == "local_governance":
                    terms = [term for term in terms if "/" in term or "." in term]
                if not terms:
                    continue
                matched = [term for term in terms if cls._traceability_term_is_present(term, normalized_bundle_text=normalized_bundle_text)]
                required_matches = 1 if len(terms) < 4 else 2
                if len(matched) >= required_matches:
                    continue
                issues.append(
                    "alignment bundle must project confirmed working agreement evidence into runnable surfaces: "
                    f"{key} missing {', '.join(terms[:5])}"
                )
            issues.extend(
                cls._alignment_governance_marker_responsibility_issues(
                    evidence,
                    normalized_runtime_text=normalized_runtime_text,
                )
            )
            issues.extend(
                cls._alignment_agreement_category_projection_issues(
                    evidence,
                    normalized_bundle_text=normalized_bundle_text,
                )
            )
        workdir_snapshot = cls._alignment_workdir_snapshot(Path(session["workdir"])) if session.get("workdir") else ""
        if cls._workdir_snapshot_has_governance_markers(workdir_snapshot):
            issues.extend(
                cls._alignment_governance_marker_responsibility_issues(
                    {"workdir_snapshot": workdir_snapshot},
                    normalized_runtime_text=normalized_runtime_text,
                )
            )
        return issues

    @classmethod
    def _alignment_agreement_category_projection_issues(cls, evidence: dict, *, normalized_bundle_text: str) -> list[str]:
        category_checks = (
            (
                "success_surface",
                "success surface",
                cls._agent_candidate_success_surface_categories(
                    str(evidence.get("success_surface") or ""),
                    require_explicit_marker=False,
                ),
                1,
            ),
            (
                "fake_done_risks",
                "fake-done risks",
                cls._agent_candidate_fake_done_categories(
                    str(evidence.get("fake_done_risks") or ""),
                    require_explicit_marker=False,
                ),
                1,
            ),
            (
                "evidence_preferences",
                "evidence preferences",
                cls._agent_candidate_evidence_preference_categories(
                    str(evidence.get("evidence_preferences") or ""),
                    require_explicit_marker=False,
                ),
                1,
            ),
            (
                "execution_strategy",
                "execution strategy",
                cls._agent_candidate_execution_strategy_categories(
                    str(evidence.get("execution_strategy") or ""),
                    require_explicit_marker=False,
                ),
                2,
            ),
            (
                "residual_risk_policy",
                "residual-risk policy",
                cls._agent_candidate_residual_risk_policy_categories(
                    str(evidence.get("residual_risk_policy") or ""),
                    require_explicit_marker=False,
                ),
                1,
            ),
            (
                "judgment_tradeoffs",
                "judgment tradeoffs",
                cls._agent_candidate_tradeoff_categories(str(evidence.get("judgment_tradeoffs") or "")),
                2,
            ),
        )
        issues: list[str] = []
        for _key, label, categories, minimum_category_count in category_checks:
            if len(categories) < minimum_category_count:
                continue
            missing = [
                category_label
                for category_label, bundle_pattern in categories
                if not re.search(bundle_pattern, normalized_bundle_text, re.I)
            ]
            if not missing:
                continue
            issues.append(
                "alignment bundle must project confirmed working agreement "
                f"{label} into runnable surfaces: missing {', '.join(missing)}"
            )
        return issues

    def _alignment_agent_candidate_traceability_issues(self, session: dict, bundle: dict) -> list[str]:
        session_id = str(session.get("id") or "").strip()
        if not session_id or not self._alignment_session_has_agent_candidate_yaml(session_id):
            return []
        task_text = self._alignment_session_user_task_text(session)
        issues: list[str] = []
        if text_mentions_loop_fit_contradiction(task_text):
            issues.append(
                "agent-first candidate cannot compile a Loop when the host Agent task summary says Loopora is not fit; "
                "ask the user or use Web review before generating a runnable Loop"
            )
        normalized_bundle_text = self._normalize_traceability_text(self._alignment_bundle_agreement_projection_text(bundle))
        normalized_runtime_text = self._normalize_traceability_text(self._alignment_bundle_runtime_responsibility_projection_text(bundle))
        terms = self._agent_candidate_traceability_terms(task_text)
        if terms:
            matched = [term for term in terms if self._traceability_term_is_present(term, normalized_bundle_text=normalized_bundle_text)]
            required_matches = 1 if len(terms) < 4 else 2
            if len(matched) < required_matches:
                issues.append(
                    "agent-first candidate must project the host Agent task summary into runnable surfaces: "
                    + "missing "
                    + ", ".join(terms[:5])
                )
        issues.extend(
            self._alignment_governance_marker_responsibility_issues(
                {"agent_candidate": task_text},
                normalized_runtime_text=normalized_runtime_text,
            )
        )
        issues.extend(
            self._alignment_agent_candidate_tradeoff_issues(
                task_text,
                normalized_bundle_text=normalized_bundle_text,
            )
        )
        issues.extend(
            self._alignment_agent_candidate_execution_strategy_issues(
                task_text,
                normalized_bundle_text=normalized_bundle_text,
            )
        )
        issues.extend(
            self._alignment_agent_candidate_residual_risk_policy_issues(
                task_text,
                normalized_bundle_text=normalized_bundle_text,
            )
        )
        issues.extend(
            self._alignment_agent_candidate_success_surface_issues(
                task_text,
                normalized_bundle_text=normalized_bundle_text,
            )
        )
        issues.extend(
            self._alignment_agent_candidate_fake_done_issues(
                task_text,
                normalized_bundle_text=normalized_bundle_text,
            )
        )
        issues.extend(
            self._alignment_agent_candidate_evidence_preference_issues(
                task_text,
                normalized_bundle_text=normalized_bundle_text,
            )
        )
        return issues

    @classmethod
    def _alignment_agent_candidate_tradeoff_issues(cls, task_text: str, *, normalized_bundle_text: str) -> list[str]:
        categories = cls._agent_candidate_tradeoff_categories(task_text)
        if len(categories) < 2:
            return []
        missing = [
            label
            for label, bundle_pattern in categories
            if not re.search(bundle_pattern, normalized_bundle_text, re.I)
        ]
        if not missing:
            return []
        return [
            "agent-first candidate must project explicit host Agent judgment tradeoffs into runnable surfaces: "
            + "missing "
            + ", ".join(missing)
        ]

    @staticmethod
    def _agent_candidate_tradeoff_categories(task_text: str) -> list[tuple[str, str]]:
        text = str(task_text or "").strip()
        if not text:
            return []
        explicit_tradeoff_markers = (
            r"\b(?:proof|evidence|verify|verification)\b.{0,80}\b(?:over|before|rather than|instead of)\b.{0,80}\b(?:speed|fast|quick|polish|ui|narrative|story)\b",
            r"\b(?:speed|fast|quick|polish|ui|narrative|story)\b.{0,80}\b(?:wait|after|behind|until|rather than|instead of)\b.{0,80}\b(?:proof|evidence|verify|verification)\b",
            r"\b(?:strict|blocking|block|reject|fail closed)\b.{0,80}\b(?:over|before|rather than|instead of|beats?)\b.{0,80}\b(?:pragmatic|pragmatism|progress)\b",
            r"\b(?:pragmatic|pragmatism|progress)\b.{0,80}\b(?:wait|after|behind|until|rather than|instead of)\b.{0,80}\b(?:strict|blocking|block|reject|fail closed)\b",
            r"\b(?:prioriti[sz]e|prefer)\b.{0,80}\b(?:proof|evidence|verify|verification|blocking|fail closed)\b",
            r"\b(?:block|reject|fail closed)\b.{0,80}\b(?:fake[- ]?done|fake completion|polished-looking|narrative)\b",
            r"(?:优先|先).{0,24}(?:证明|证据|验证|阻断)",
            r"(?:证明|证据|验证|阻断).{0,24}(?:优先|先于|高于)",
            r"(?:严格|阻断|拒绝).{0,20}(?:优先|先于|高于).{0,20}(?:务实|推进|进度)",
            r"(?:务实|推进|进度).{0,20}(?:等|让位|后于).{0,20}(?:严格|阻断|拒绝)",
            r"(?:先别|不要|别).{0,16}(?:美化|润色|打磨|漂亮|界面)",
            r"(?:阻断|拒绝).{0,20}(?:假完成|漂亮叙事|证据不足)",
        )
        if not any(re.search(pattern, text, re.I) for pattern in explicit_tradeoff_markers):
            return []
        category_patterns = (
            (
                "proof/evidence",
                r"\b(?:proof|prove|proven|evidence|verify|verification)\b|证明|证据|验证|已证明",
            ),
            (
                "speed/polish",
                r"\b(?:speed|fast|quick|polish|ui|narrative|story|pretty|polished-looking)\b|速度|快速|美化|润色|打磨|界面|漂亮|叙事",
            ),
            (
                "blocking/fake-completion",
                r"\b(?:block|blocking|reject|fail closed|fake[- ]?done|fake completion|unproven|weak)\b|阻断|拒绝|假完成|未证明|弱证据|证据不足",
            ),
            (
                "pragmatic/progress",
                r"\b(?:pragmatic|pragmatism|progress)\b|务实|推进|进度",
            ),
        )
        return [(label, pattern) for label, pattern in category_patterns if re.search(pattern, text, re.I)]

    @classmethod
    def _alignment_agent_candidate_execution_strategy_issues(cls, task_text: str, *, normalized_bundle_text: str) -> list[str]:
        categories = cls._agent_candidate_execution_strategy_categories(task_text)
        if not categories:
            return []
        if len(categories) < 2 and not cls._agent_candidate_has_labeled_execution_strategy(task_text):
            return []
        missing = [
            label
            for label, bundle_pattern in categories
            if not re.search(bundle_pattern, normalized_bundle_text, re.I)
        ]
        if not missing:
            return []
        return [
            "agent-first candidate must project explicit host Agent execution strategy into runnable surfaces: "
            + "missing "
            + ", ".join(missing)
        ]

    @staticmethod
    def _agent_candidate_has_labeled_execution_strategy(task_text: str) -> bool:
        return bool(
            re.search(
                r"\b(?:execution strategy|priority|priorities|priority order|next round|next pass)\b|执行策略|优先级|下一轮|下一步",
                str(task_text or ""),
                re.I,
            )
        )

    @staticmethod
    def _agent_candidate_execution_strategy_categories(task_text: str, *, require_explicit_marker: bool = True) -> list[tuple[str, str]]:
        text = str(task_text or "").strip()
        if not text:
            return []
        explicit_strategy_markers = (
            r"\b(?:execution strategy|next round|next pass|priority|priorities)\b",
            r"\b(?:first|before|then|after|defer|prioriti[sz]e|start with|do not start|don't start|avoid)\b",
            r"(?:执行策略|下一轮|下一步|优先级|优先|先|再|然后|之后|暂缓|推迟|先别|不要先|别先)",
        )
        if require_explicit_marker and not any(re.search(pattern, text, re.I) for pattern in explicit_strategy_markers):
            return []
        category_patterns = (
            (
                "repair/root-cause",
                r"\b(?:root[- ]?cause|regression|failure|failing|bug)\b|根因|故障|失败|回归|缺陷",
            ),
            (
                "evidence/proof",
                r"\b(?:proof|prove|proven|evidence|verify|verification|audit|test|tests)\b|证明|证据|验证|审计|测试|已证明",
            ),
            (
                "scope/narrow",
                r"\b(?:scope|narrow|focused|focus|small|minimal|limit|bounded)\b|范围|收窄|聚焦|小而|最小|有限",
            ),
            (
                "expand/breadth",
                r"\b(?:expand|expansion|broaden|broad|breadth|new feature|dashboard|report)\b|扩展|扩大|铺开|宽泛|新功能|看板|报表",
            ),
            (
                "polish/ui",
                r"\b(?:polish|ui|visual|pretty|styling|copy|narrative|story)\b|美化|打磨|润色|界面|视觉|文案|叙事|漂亮",
            ),
        )
        return [(label, pattern) for label, pattern in category_patterns if re.search(pattern, text, re.I)]

    @classmethod
    def _alignment_agent_candidate_residual_risk_policy_issues(cls, task_text: str, *, normalized_bundle_text: str) -> list[str]:
        categories = cls._agent_candidate_residual_risk_policy_categories(task_text)
        if not categories:
            return []
        missing = [
            label
            for label, bundle_pattern in categories
            if not re.search(bundle_pattern, normalized_bundle_text, re.I)
        ]
        if not missing:
            return []
        return [
            "agent-first candidate must project explicit host Agent residual-risk policy into runnable surfaces: "
            + "missing "
            + ", ".join(missing)
        ]

    @staticmethod
    def _agent_candidate_residual_risk_policy_categories(task_text: str, *, require_explicit_marker: bool = True) -> list[tuple[str, str]]:
        text = str(task_text or "").strip()
        if not text:
            return []
        explicit_policy_markers = (
            r"\bresidual risks?\b",
            r"\bremaining risks?\b",
            r"残余风险",
            r"剩余风险",
        )
        if require_explicit_marker and not any(re.search(pattern, text, re.I) for pattern in explicit_policy_markers):
            return []
        no_acceptance_pattern = (
            r"\b(?:no|none|zero)\b.{0,60}\b(?:accepted|acceptable|allowed)?\s*residual risks?\b"
            r"|\b(?:do not|don't|cannot|can't|must not|never)\b.{0,60}\baccept\b.{0,60}\bresidual risks?\b"
            r"|(?:不接受|不能接受|不可接受|不允许).{0,24}残余风险"
            r"|残余风险.{0,24}(?:不接受|不能接受|不可接受|不允许)"
        )
        categories: list[tuple[str, str]] = [
            ("residual-risk", r"\bresidual risks?\b|\bremaining risks?\b|残余风险|剩余风险"),
        ]
        if re.search(no_acceptance_pattern, text, re.I):
            categories.append(
                (
                    "no-accepted-residual-risk",
                    (
                        r"\b(?:no|none|zero)\b.{0,80}\b(?:accepted|acceptable|allowed)?\s*residual risks?\b"
                        r"|\b(?:do not|don't|cannot|can't|must not|never)\b.{0,80}\baccept\b.{0,80}\bresidual risks?\b"
                        r"|(?:不接受|不能接受|不可接受|不允许).{0,30}残余风险"
                        r"|残余风险.{0,30}(?:不接受|不能接受|不可接受|不允许)"
                    ),
                )
            )
            return categories
        category_patterns = (
            (
                "acceptance",
                r"\b(?:accept|accepted|acceptable|allow|allowed|carry)\b|接受|可接受|允许|带着走",
                (
                    r"(?:\bresidual risks?\b|残余风险|剩余风险).{0,160}"
                    r"(?:\b(?:accept|accepted|acceptable|allow|allowed|carry)\b|接受|可接受|允许|带着走)"
                    r"|(?:\b(?:accept|accepted|acceptable|allow|allowed|carry)\b|接受|可接受|允许|带着走)"
                    r".{0,160}(?:\bresidual risks?\b|残余风险|剩余风险)"
                ),
            ),
            (
                "owner/follow-up",
                (
                    r"\b(?:owner|owned|assignee|follow[- ]?up|followup|ticket|tracked|tracking|"
                    r"revisit|monitor|mitigation)\b|负责人|负责|接手|接管|后续|跟进|工单|跟踪|追踪|监控|缓解"
                ),
                (
                    r"(?:\bresidual risks?\b|残余风险|剩余风险).{0,180}"
                    r"(?:\b(?:owner|owned|assignee|follow[- ]?up|followup|ticket|tracked|tracking|"
                    r"revisit|monitor|mitigation)\b|负责人|负责|接手|接管|后续|跟进|工单|跟踪|追踪|监控|缓解)"
                    r"|(?:\b(?:owner|owned|assignee|follow[- ]?up|followup|ticket|tracked|tracking|"
                    r"revisit|monitor|mitigation)\b|负责人|负责|接手|接管|后续|跟进|工单|跟踪|追踪|监控|缓解)"
                    r".{0,180}(?:\bresidual risks?\b|残余风险|剩余风险)"
                ),
            ),
            (
                "fail-closed",
                r"\b(?:fail closed|must block|must fail|block|blocking|reject)\b|失败关闭|必须阻断|必须失败|阻断|拒绝",
                (
                    r"(?:\bresidual risks?\b|残余风险|剩余风险).{0,180}"
                    r"(?:\b(?:fail closed|must block|must fail|block|blocking|reject)\b|失败关闭|必须阻断|必须失败|阻断|拒绝)"
                    r"|(?:\b(?:fail closed|must block|must fail|block|blocking|reject)\b|失败关闭|必须阻断|必须失败|阻断|拒绝)"
                    r".{0,180}(?:\bresidual risks?\b|残余风险|剩余风险)"
                ),
            ),
        )
        categories.extend(
            (label, bundle_pattern)
            for label, task_pattern, bundle_pattern in category_patterns
            if re.search(task_pattern, text, re.I)
        )
        return categories

    @classmethod
    def _alignment_agent_candidate_success_surface_issues(cls, task_text: str, *, normalized_bundle_text: str) -> list[str]:
        categories = cls._agent_candidate_success_surface_categories(task_text)
        if not categories:
            return []
        missing = [
            label
            for label, bundle_pattern in categories
            if not re.search(bundle_pattern, normalized_bundle_text, re.I)
        ]
        if not missing:
            return []
        return [
            "agent-first candidate must project explicit host Agent success criteria into runnable surfaces: "
            + "missing "
            + ", ".join(missing)
        ]

    @staticmethod
    def _agent_candidate_success_surface_categories(task_text: str, *, require_explicit_marker: bool = True) -> list[tuple[str, str]]:
        text = str(task_text or "").strip()
        if not text:
            return []
        explicit_success_markers = (
            r"\bsuccess\s+(?:means|requires|is)\b",
            r"\bdone when\b",
            r"\bcomplete when\b",
            r"\bacceptance criteria\b",
            r"\bto pass\b.{0,80}\b(?:must|needs?|should|requires?)\b",
            r"\b(?:must|needs?|should|requires?)\b.{0,80}\b(?:pass|succeed|be complete|be done)\b",
            r"成功(?:标准|意味着|要求|面)",
            r"完成(?:标准|条件|时)",
            r"验收(?:标准|条件)",
        )
        if require_explicit_marker and not any(re.search(pattern, text, re.I) for pattern in explicit_success_markers):
            return []
        categories: list[tuple[str, str]] = [
            (
                "success/done-when",
                r"\b(?:success|done when|acceptance criteria|complete when|completion criteria)\b|成功|完成标准|验收",
            ),
        ]
        category_patterns = (
            (
                "actor/user-facing-outcome",
                r"\b(?:user|customer|admin|operator|buyer|merchant|support)\b|用户|客户|管理员|运营|买家|商家|客服",
            ),
            (
                "notification/message",
                r"\b(?:notification|notify|email|message|receipt|alert)\b|通知|邮件|消息|回执|提醒",
            ),
            (
                "audit/log",
                r"\b(?:audit|auditing|audit[- ]?log|log|logs|ledger|trace|recorded|records?)\b|审计|日志|账本|记录|追踪",
            ),
            (
                "permission/auth",
                r"\b(?:permission|permissions|authorization|auth|access|role)\b|权限|授权|访问|角色",
            ),
            (
                "payment/refund/billing",
                r"\b(?:payment|payments|refund|refunds|billing|invoice|checkout)\b|支付|退款|账单|发票|结账",
            ),
            (
                "data/export/report",
                r"\b(?:data|export|download|csv|report|dashboard)\b|数据|导出|下载|报表|看板",
            ),
            (
                "accessibility/a11y",
                r"\b(?:accessibility|a11y|screen[- ]?reader|keyboard|aria|focus|wcag)\b|无障碍|可访问|读屏|屏幕阅读器|键盘|焦点",
            ),
            (
                "locale/i18n",
                r"\b(?:locale|locali[sz]ation|i18n|translation|language|chinese|english)\b|多语言|国际化|本地化|翻译|语言|中文|英文|英语",
            ),
        )
        categories.extend((label, pattern) for label, pattern in category_patterns if re.search(pattern, text, re.I))
        return categories

    @classmethod
    def _alignment_agent_candidate_fake_done_issues(cls, task_text: str, *, normalized_bundle_text: str) -> list[str]:
        categories = cls._agent_candidate_fake_done_categories(task_text)
        if not categories:
            return []
        missing = [
            label
            for label, bundle_pattern in categories
            if not re.search(bundle_pattern, normalized_bundle_text, re.I)
        ]
        if not missing:
            return []
        return [
            "agent-first candidate must project explicit host Agent fake-done risks into runnable surfaces: "
            + "missing "
            + ", ".join(missing)
        ]

    @staticmethod
    def _agent_candidate_fake_done_categories(task_text: str, *, require_explicit_marker: bool = True) -> list[tuple[str, str]]:
        text = str(task_text or "").strip()
        if not text:
            return []
        explicit_fake_done_markers = (
            r"\bfake[- ]?(?:done|completion)\b",
            r"\b(?:do not|don't|cannot|can't|must not|never)\s+pass\b",
            r"\b(?:looks|appears|seems)\s+(?:done|complete|finished|working)\b",
            r"\b(?:only|just|merely)\s+(?:a\s+)?(?:claim|screenshot|download|export|mock|stub|static)\b",
            r"\bhappy[- ]path[- ]only\b",
            r"假完成",
            r"看起来.{0,12}(?:完成|可用|通过)",
            r"(?:不能|不可|不要|不得).{0,16}(?:通过|算完成|收尾)",
        )
        if require_explicit_marker and not any(re.search(pattern, text, re.I) for pattern in explicit_fake_done_markers):
            return []
        categories: list[tuple[str, str]] = [
            (
                "fake-done/blocking",
                r"\bfake[- ]?(?:done|completion)\b|\b(?:do not|don't|cannot|can't|must not|never)\s+pass\b|假完成|阻断|不得通过|不能通过",
            ),
        ]
        category_patterns = (
            (
                "permission/audit",
                r"\b(?:permission|permissions|authorization|auth|access|audit|auditing|audit[- ]?log)\b|权限|授权|审计|日志",
                r"\b(?:permission|permissions|authorization|auth|access|audit|auditing|audit[- ]?log)\b|权限|授权|审计|日志",
            ),
            (
                "download/export-only",
                r"\b(?:csv|download|export|file)\b|下载|导出|文件",
                r"\b(?:csv|download|export|file)\b|下载|导出|文件",
            ),
            (
                "payment/refund/billing",
                (
                    r"(?:\bfake[- ]?(?:done|completion)\b(?!\s+findings)|\b(?:do not|don't|cannot|can't|must not|never)\s+pass\b|"
                    r"\b(?:only|just|merely)\b|假完成|阻断|不得通过|不能通过).{0,80}"
                    r"(?:\b(?:payment|payments|refund|refunds|billing|invoice|checkout)\b|支付|退款|账单|发票|结账)"
                    r"|(?:\b(?:payment|payments|refund|refunds|billing|invoice|checkout)\b|支付|退款|账单|发票|结账)"
                    r".{0,80}(?:\bfake[- ]?(?:done|completion)\b(?!\s+findings)|\b(?:do not|don't|cannot|can't|must not|never)\s+pass\b|"
                    r"\b(?:only|just|merely)\b|假完成|阻断|不得通过|不能通过)"
                ),
                (
                    r"(?:\bfake[- ]?(?:done|completion)\b(?!\s+findings)|\b(?:do not|don't|cannot|can't|must not|never)\s+pass\b|"
                    r"\b(?:only|just|merely)\b|假完成|不得通过|不能通过).{0,80}"
                    r"(?:\b(?:payment|payments|refund|refunds|billing|invoice|checkout)\b|支付|退款|账单|发票|结账)"
                    r"|(?:\b(?:payment|payments|refund|refunds|billing|invoice|checkout)\b|支付|退款|账单|发票|结账)"
                    r".{0,80}(?:\bfake[- ]?(?:done|completion)\b(?!\s+findings)|\b(?:do not|don't|cannot|can't|must not|never)\s+pass\b|"
                    r"\b(?:only|just|merely)\b|假完成|不得通过|不能通过)"
                ),
            ),
            (
                "data/export/report",
                (
                    r"(?:\bfake[- ]?(?:done|completion)\b(?!\s+findings)|\b(?:do not|don't|cannot|can't|must not|never)\s+pass\b|"
                    r"\b(?:only|just|merely)\b|假完成|阻断|不得通过|不能通过).{0,80}"
                    r"(?:\b(?:data|export|download|csv|report|dashboard)\b|数据|导出|下载|报表|看板)"
                    r"|(?:\b(?:data|export|download|csv|report|dashboard)\b|数据|导出|下载|报表|看板)"
                    r".{0,80}(?:\bfake[- ]?(?:done|completion)\b(?!\s+findings)|\b(?:do not|don't|cannot|can't|must not|never)\s+pass\b|"
                    r"\b(?:only|just|merely)\b|假完成|阻断|不得通过|不能通过)"
                ),
                (
                    r"(?:\bfake[- ]?(?:done|completion)\b(?!\s+findings)|\b(?:do not|don't|cannot|can't|must not|never)\s+pass\b|"
                    r"\b(?:only|just|merely)\b|假完成|不得通过|不能通过).{0,80}"
                    r"(?:\b(?:data|export|download|csv|report|dashboard)\b|数据|导出|下载|报表|看板)"
                    r"|(?:\b(?:data|export|download|csv|report|dashboard)\b|数据|导出|下载|报表|看板)"
                    r".{0,80}(?:\bfake[- ]?(?:done|completion)\b(?!\s+findings)|\b(?:do not|don't|cannot|can't|must not|never)\s+pass\b|"
                    r"\b(?:only|just|merely)\b|假完成|不得通过|不能通过)"
                ),
            ),
            (
                "visual/polish/screenshot-only",
                r"\b(?:screenshot|visual|polish|ui|pretty|polished-looking)\b|截图|视觉|界面|美化|漂亮",
                r"\b(?:screenshot|visual|polish|ui|pretty|polished-looking)\b|截图|视觉|界面|美化|漂亮",
            ),
            (
                "claim/narrative-only",
                r"\b(?:claim|claims|narrative|story|description|self[- ]?report)\b|声明|叙事|描述|自述",
                r"\b(?:claim|claims|narrative|story|description|self[- ]?report)\b|声明|叙事|描述|自述",
            ),
            (
                "happy-path-only",
                r"\bhappy[- ]?path\b|主路径|快乐路径",
                r"\bhappy[- ]?path\b|主路径|快乐路径",
            ),
            (
                "mock/static/stub-only",
                r"\b(?:mock|stub|static|placeholder|fixture)\b|模拟|桩|静态|占位",
                r"\b(?:mock|stub|static|placeholder|fixture)\b|模拟|桩|静态|占位",
            ),
            (
                "accessibility/i18n",
                r"\b(?:accessibility|a11y|screen[- ]?reader|keyboard|aria|focus|wcag|locale|locali[sz]ation|i18n|translation|language)\b|无障碍|可访问|读屏|屏幕阅读器|键盘|焦点|多语言|国际化|本地化|翻译|语言",
                r"\b(?:accessibility|a11y|screen[- ]?reader|keyboard|aria|focus|wcag|locale|locali[sz]ation|i18n|translation|language)\b|无障碍|可访问|读屏|屏幕阅读器|键盘|焦点|多语言|国际化|本地化|翻译|语言",
            ),
        )
        categories.extend((label, bundle_pattern) for label, task_pattern, bundle_pattern in category_patterns if re.search(task_pattern, text, re.I))
        return categories

    @classmethod
    def _alignment_agent_candidate_evidence_preference_issues(cls, task_text: str, *, normalized_bundle_text: str) -> list[str]:
        categories = cls._agent_candidate_evidence_preference_categories(task_text)
        if not categories:
            return []
        missing = [
            label
            for label, bundle_pattern in categories
            if not re.search(bundle_pattern, normalized_bundle_text, re.I)
        ]
        if not missing:
            return []
        return [
            "agent-first candidate must project explicit host Agent evidence preferences into runnable surfaces: "
            + "missing "
            + ", ".join(missing)
        ]

    @staticmethod
    def _agent_candidate_evidence_preference_categories(task_text: str, *, require_explicit_marker: bool = True) -> list[tuple[str, str]]:
        text = str(task_text or "").strip()
        if not text:
            return []
        explicit_evidence_markers = (
            r"\b(?:evidence|proof|verification|verify)\b.{0,80}\b(?:must|should|prefer|include|require|needs?)\b",
            r"\b(?:must|should|prefer|include|require|needs?)\b.{0,80}\b(?:evidence|proof|verification|verify)\b",
            r"证据.{0,24}(?:必须|需要|优先|包括|包含)",
            r"(?:必须|需要|优先|包括|包含).{0,24}(?:证据|证明|验证)",
        )
        if require_explicit_marker and not any(re.search(pattern, text, re.I) for pattern in explicit_evidence_markers):
            return []
        categories: list[tuple[str, str]] = [
            (
                "evidence/proof",
                r"\b(?:evidence|proof|verify|verification|verified|proven)\b|证据|证明|验证|已证明",
            ),
        ]
        category_patterns = (
            (
                "browser/journey",
                r"\b(?:browser|playwright|journey|end[- ]?to[- ]?end|e2e)\b|浏览器|旅程|端到端",
            ),
            (
                "command/test",
                r"\b(?:command|cli|script|test|tests|pytest|unit|contract|lint|typecheck)\b|命令|脚本|测试|契约|类型检查",
            ),
            (
                "audit/log",
                r"\b(?:audit|auditing|audit[- ]?log|log|logs|ledger|trace)\b|审计|日志|账本|追踪",
            ),
            (
                "permission/auth",
                r"\b(?:permission|permissions|authorization|auth|access)\b|权限|授权|访问",
            ),
            (
                "payment/refund/billing",
                r"\b(?:payment|payments|refund|refunds|billing|invoice|checkout)\b|支付|退款|账单|发票|结账",
            ),
            (
                "data/export/report",
                r"\b(?:data|export|download|csv|report|dashboard)\b|数据|导出|下载|报表|看板",
            ),
            (
                "artifact/ref",
                r"\b(?:artifact|artifacts|file|files|ref|refs|report)\b|产物|文件|引用|报告",
            ),
            (
                "accessibility/a11y",
                r"\b(?:accessibility|a11y|screen[- ]?reader|keyboard|aria|focus|wcag|axe)\b|无障碍|可访问|读屏|屏幕阅读器|键盘|焦点",
            ),
            (
                "locale/i18n",
                r"\b(?:locale|locali[sz]ation|i18n|translation|language|chinese|english)\b|多语言|国际化|本地化|翻译|语言|中文|英文|英语",
            ),
            (
                "screenshot-is-weak",
                r"\b(?:screenshot|screenshots)\b|截图",
            ),
        )
        categories.extend((label, pattern) for label, pattern in category_patterns if re.search(pattern, text, re.I))
        return categories

    def _alignment_session_has_agent_candidate_yaml(self, session_id: str) -> bool:
        return any(
            event.get("event_type") == "agent_candidate_received"
            and isinstance(event.get("payload"), dict)
            and event["payload"].get("has_candidate_yaml") is True
            for event in self.repository.list_alignment_events(session_id, limit=50)
        )

    def _alignment_session_agent_entry_candidate_event(self, session_id: str) -> dict:
        candidate_events = [
            event
            for event in self.repository.list_alignment_events(session_id, limit=50)
            if event.get("event_type") == "agent_candidate_received"
            and isinstance(event.get("payload"), dict)
            and event["payload"].get("candidate_origin") == "agent_entry"
        ]
        return candidate_events[-1] if candidate_events else {}

    def _alignment_session_agent_entry_ready_event(self, session_id: str) -> dict:
        ready_events = [
            event
            for event in self.repository.list_alignment_events(session_id, limit=50)
            if event.get("event_type") == "agent_candidate_ready_content"
            and isinstance(event.get("payload"), dict)
            and event["payload"].get("candidate_origin") == "agent_entry"
        ]
        return ready_events[-1] if ready_events else {}

    @classmethod
    def _agent_entry_review_suggested_reply(cls, session: dict, *, review_mode: str, task_message: str) -> str:
        task_anchor = cls._agreement_text_snippet(task_message, limit=520)
        if cls._alignment_prefers_chinese(session):
            if review_mode == "not_fit":
                return (
                    "请先按这次 /loopora-plan 的任务锚点重新判断是否适合 Loopora："
                    f"{task_anchor}\n"
                    "如果仍要继续，请明确后续轮次会新增哪些证据、handoff 或 GateKeeper 裁决价值；"
                    "如果不适合，请不要生成可运行 Loop。"
                )
            return (
                "请基于这次 /loopora-plan 的任务锚点继续 Web review："
                f"{task_anchor}\n"
                "推荐采用证据优先路径：先确认 Loopora fit，再把完成标准、伪完成风险、证据预期、"
                "执行策略、判断取舍、残余风险和本地治理责任整理成可确认的工作协议；"
                "确认后再生成可审查的 Loop 预览。"
            )
        if review_mode == "not_fit":
            return (
                "First re-check whether this /loopora-plan task anchor fits Loopora: "
                f"{task_anchor}\n"
                "If we should continue, explain what later evidence, handoffs, or GateKeeper judgment would add; "
                "if it does not fit, do not generate a runnable Loop."
            )
        return (
            "Continue Web review from this /loopora-plan task anchor: "
            f"{task_anchor}\n"
            "Use the evidence-first path: first confirm Loopora fit, then turn the success criteria, fake-done risks, "
            "evidence expectations, execution strategy, judgment tradeoffs, residual-risk policy, and local governance "
            "into a confirmable working agreement before generating a reviewable Loop preview."
        )

    @classmethod
    def _agent_entry_review_decision_options(cls, session: dict, *, review_mode: str, task_message: str) -> list[dict]:
        suggested_reply = cls._agent_entry_review_suggested_reply(session, review_mode=review_mode, task_message=task_message)
        task_anchor = cls._agreement_text_snippet(task_message, limit=420)
        if cls._alignment_prefers_chinese(session):
            if review_mode == "not_fit":
                return [
                    {
                        "id": "skip_loop",
                        "label": "先不生成 Loop（推荐）",
                        "description": "任务锚点更像一次性任务或已有硬检查足够，先避免把它包装成长期 Loop。",
                        "recommended": True,
                        "user_reply": f"同意，先不生成 Loop 方案。本次任务锚点：{task_anchor}",
                    },
                    {
                        "id": "reframe_as_loop",
                        "label": "重定义成长期 Loop",
                        "description": "我会说明后续证据、handoff 或 GateKeeper 裁决为什么值得保留。",
                        "recommended": False,
                        "user_reply": suggested_reply,
                    },
                ]
            return [
                {
                    "id": "continue_web_review_evidence_first",
                    "label": "按证据优先继续 Web review（推荐）",
                    "description": "把宿主 Agent 的任务锚点转成可确认工作协议，再生成 Loop 预览。",
                    "recommended": True,
                    "user_reply": suggested_reply,
                },
                {
                    "id": "recheck_loop_fit",
                    "label": "先重新判断是否需要 Loop",
                    "description": "如果这其实是一轮任务或已有检查足够，先阻止编排。",
                    "recommended": False,
                    "user_reply": (
                        "请先重新判断这个任务是否适合 Loopora，而不是直接生成 Loop。"
                        f"任务锚点：{task_anchor}"
                    ),
                },
            ]
        if review_mode == "not_fit":
            return [
                {
                    "id": "skip_loop",
                    "label": "Skip Loop (Recommended)",
                    "description": "The task anchor looks one-off or already covered by hard checks, so do not package it as a long-running Loop.",
                    "recommended": True,
                    "user_reply": f"Agreed; do not generate a Loop plan yet. Task anchor: {task_anchor}",
                },
                {
                    "id": "reframe_as_loop",
                    "label": "Reframe as a Loop",
                    "description": "I will explain why later evidence, handoffs, or GateKeeper judgment should survive.",
                    "recommended": False,
                    "user_reply": suggested_reply,
                },
            ]
        return [
            {
                "id": "continue_web_review_evidence_first",
                "label": "Continue evidence-first review (Recommended)",
                "description": "Turn the host Agent task anchor into a confirmable working agreement, then generate the Loop preview.",
                "recommended": True,
                "user_reply": suggested_reply,
            },
            {
                "id": "recheck_loop_fit",
                "label": "Re-check Loop fit",
                "description": "If this is only one pass or hard checks already decide it, block composition first.",
                "recommended": False,
                "user_reply": (
                    "Please re-check whether this task actually fits Loopora before generating a Loop. "
                    f"Task anchor: {task_anchor}"
                ),
            },
        ]

    def _alignment_session_has_agent_entry_candidate(self, session_id: str) -> bool:
        return bool(self._alignment_session_agent_entry_candidate_event(session_id))

    def _agent_entry_review_projection(self, session: dict) -> dict:
        session_id = str(session.get("id") or "").strip()
        if not session_id:
            return {}
        candidate_event = self._alignment_session_agent_entry_candidate_event(session_id)
        if not candidate_event:
            return {}
        payload = dict(candidate_event["payload"])
        requires_web_alignment = payload.get("requires_web_alignment") is True
        requires_candidate_repair = payload.get("requires_candidate_repair") is True
        loopora_fit_contradiction = payload.get("loopora_fit_contradiction") is True
        review_mode = "not_fit" if loopora_fit_contradiction else "missing_candidate_plan"
        status = str(session.get("status") or "")
        stage = str(session.get("alignment_stage") or "")
        agreement = session.get("working_agreement") if isinstance(session.get("working_agreement"), dict) else {}
        agreement_started = bool(str(agreement.get("summary") or "").strip()) or stage in {"agreement_ready", "confirmed", "compiling", "ready_review"}
        if not requires_web_alignment or status in {"ready", "imported", "running_loop"} or agreement_started:
            return {}
        task_message = self._alignment_session_user_task_text(session)[:1000]
        suggested_reply = self._agent_entry_review_suggested_reply(session, review_mode=review_mode, task_message=task_message)
        return {
            "schema_version": 1,
            "source": "agent_entry",
            "review_mode": review_mode,
            "not_runnable": status != "ready",
            "requires_web_alignment": requires_web_alignment,
            "requires_candidate_repair": requires_candidate_repair,
            "has_candidate_yaml": payload.get("has_candidate_yaml") is True,
            "loopora_fit_contradiction": loopora_fit_contradiction,
            "adapter": str(payload.get("adapter") or session.get("executor_kind") or ""),
            "entry_source": str(payload.get("entry_source") or ""),
            "source_path": str(payload.get("source_path") or ""),
            "candidate_sha256": str(payload.get("candidate_sha256") or ""),
            "candidate_bytes": structured_non_negative_int(payload.get("candidate_bytes"), default=0),
            "ready_candidate_sha256": str(payload.get("ready_candidate_sha256") or ""),
            "ready_candidate_bytes": structured_non_negative_int(payload.get("ready_candidate_bytes"), default=0),
            "task_message": task_message,
            "missing_judgment_item_ids": list(ALIGNMENT_AGENT_ENTRY_REVIEW_ITEM_IDS),
            "suggested_reply": suggested_reply,
            "decision_options": self._agent_entry_review_decision_options(session, review_mode=review_mode, task_message=task_message),
        }

    def _agent_entry_launch_projection(self, session: dict) -> dict:
        session_id = str(session.get("id") or "").strip()
        if not session_id:
            return {}
        candidate_event = self._alignment_session_agent_entry_candidate_event(session_id)
        if not candidate_event:
            return {}
        payload = dict(candidate_event["payload"])
        adapter = str(payload.get("adapter") or session.get("executor_kind") or "").strip()
        if not adapter:
            return {}
        entry_source = str(payload.get("entry_source") or "").strip()
        host_context_id = str(payload.get("host_context_id") or "").strip()
        workdir = str(session.get("workdir") or "").strip()
        loop_command = agent_loop_command(adapter, workdir, entry_source=entry_source, context_id=host_context_id)
        ready_event = self._alignment_session_agent_entry_ready_event(session_id)
        ready_payload = ready_event.get("payload") if isinstance(ready_event.get("payload"), dict) else {}
        ready_sha = str(ready_payload.get("ready_candidate_sha256") or payload.get("ready_candidate_sha256") or "").strip()
        ready_bytes = structured_non_negative_int(
            ready_payload.get("ready_candidate_bytes", payload.get("ready_candidate_bytes")),
            default=0,
        )
        return {
            "schema_version": 1,
            "source": "agent_entry",
            "adapter": adapter,
            "entry_source": entry_source,
            "host_context_id": host_context_id,
            "slash_command": "/loopora-run",
            "loop_command": loop_command,
            "workdir": workdir,
            "candidate_sha256": str(payload.get("candidate_sha256") or ""),
            "candidate_bytes": structured_non_negative_int(payload.get("candidate_bytes"), default=0),
            "ready_candidate_sha256": ready_sha,
            "ready_candidate_bytes": ready_bytes,
        }

    @staticmethod
    def _alignment_session_user_task_text(session: dict) -> str:
        transcript = session.get("transcript") if isinstance(session.get("transcript"), list) else []
        user_messages = [
            str(entry.get("content") or "").strip()
            for entry in transcript
            if isinstance(entry, dict) and entry.get("role") == "user" and str(entry.get("content") or "").strip()
        ]
        return "\n".join(user_messages[:4])

    @classmethod
    def _agent_candidate_traceability_terms(cls, value: object) -> list[str]:
        terms = cls._agreement_traceability_terms(value)
        for term in cls._agreement_cjk_traceability_terms(value):
            if term not in terms:
                terms.append(term)
        return [term for term in terms if term not in ALIGNMENT_AGENT_CANDIDATE_GENERIC_TERMS][:12]

    @classmethod
    def _alignment_governance_marker_responsibility_issues(cls, evidence: dict, *, normalized_runtime_text: str) -> list[str]:
        agreement_evidence_text = cls._normalize_traceability_text(" ".join(str(value or "") for value in evidence.values()))
        governance_markers = ("agents.md", "design/readme.md", "design/", "tests/")
        if not any(marker in agreement_evidence_text for marker in governance_markers):
            return []
        if cls._governance_marker_responsibilities_present(normalized_runtime_text):
            return []
        return [
            "alignment bundle must convert project-local governance markers into Builder reading, "
            "Inspector or Custom verification, and GateKeeper gating responsibilities"
        ]

    @staticmethod
    def _governance_marker_responsibilities_present(text: str) -> bool:
        builder_reads = _governance_marker_responsibility_present(
            text,
            actor_pattern=r"\b(?:builder|generator)\b|构建者|构建",
            action_pattern=r"\b(?:read|reads|consult|consults|follow|follows|respect|respects)\b|读取|查阅|遵守|遵循",
        )
        review_checks = _governance_marker_responsibility_present(
            text,
            actor_pattern=r"\b(?:inspector|custom|review|reviewer)\b|检查者|巡检|检查|审查|验证",
            action_pattern=r"\b(?:verify|verifies|check|checks|review|reviews|validate|validates|test|tests)\b|检查|审查|验证|测试",
        )
        gatekeeper_gates = _governance_marker_responsibility_present(
            text,
            actor_pattern=r"\b(?:gatekeeper|gate keeper|verifier)\b|守门|裁决",
            action_pattern=(
                r"\b(?:weak|unproven|blocking|block|blocks|missing|skipped|fail closed|reject|rejects)\b"
                r"|弱证据|未证明|阻断|缺少|跳过|拒绝"
            ),
        )
        return builder_reads and review_checks and gatekeeper_gates

    @classmethod
    def _agreement_traceability_terms(cls, value: object) -> list[str]:
        text = str(value or "")
        if not text.strip():
            return []
        lowered_text = text.lower()
        markers = (
            "AGENTS.md",
            "design/README.md",
            "design/",
            "tests/",
            "package.json",
            "pyproject.toml",
        )
        terms: list[str] = [marker.lower() for marker in markers if marker.lower() in lowered_text]
        normalized = cls._normalize_traceability_text(text)
        for raw_term in re.findall(r"[a-z0-9][a-z0-9_.-]{3,}", normalized):
            term = raw_term.strip("._-")
            if not term or term in ALIGNMENT_TRACEABILITY_GENERIC_TERMS:
                continue
            if re.fullmatch(r"\d+", term):
                continue
            if term not in terms:
                terms.append(term)
        return terms[:12]

    @classmethod
    def _agreement_repeated_cjk_traceability_terms(cls, values: object) -> list[str]:
        counts: dict[str, int] = {}
        order: dict[str, int] = {}
        for value in list(values or []):
            seen_in_value: set[str] = set()
            for term in cls._agreement_cjk_traceability_terms(value):
                if term in seen_in_value:
                    continue
                seen_in_value.add(term)
                counts[term] = counts.get(term, 0) + 1
                if term not in order:
                    order[term] = len(order)
        return [term for term, count in sorted(counts.items(), key=lambda item: (-item[1], order[item[0]])) if count >= 3][:12]

    @staticmethod
    def _agreement_cjk_traceability_terms(value: object) -> list[str]:
        terms: list[str] = []
        for raw_sequence in re.findall(r"[\u4e00-\u9fff]{2,}", str(value or "")):
            sequence = raw_sequence.strip("".join(ALIGNMENT_TRACEABILITY_CJK_STOP_CHARS))
            if len(sequence) < 2:
                continue
            if (
                2 <= len(sequence) <= 4
                and sequence not in ALIGNMENT_TRACEABILITY_GENERIC_CJK_TERMS
                and not any(char in ALIGNMENT_TRACEABILITY_CJK_STOP_CHARS for char in sequence)
            ):
                terms.append(sequence)
            for index in range(0, len(sequence) - 1, 2):
                term = sequence[index : index + 2]
                if term not in ALIGNMENT_TRACEABILITY_GENERIC_CJK_TERMS and not any(char in ALIGNMENT_TRACEABILITY_CJK_STOP_CHARS for char in term):
                    terms.append(term)
        return list(dict.fromkeys(terms))

    @staticmethod
    def _normalize_traceability_text(value: object) -> str:
        return re.sub(r"\s+", " ", str(value or "").lower()).strip()

    @staticmethod
    def _traceability_term_is_present(term: str, *, normalized_bundle_text: str) -> bool:
        value = str(term or "").strip().lower()
        if not value:
            return False
        if "/" in value or "." in value:
            return value in normalized_bundle_text
        return bool(re.search(rf"(?<![a-z0-9]){re.escape(value)}(?![a-z0-9])", normalized_bundle_text))

    @staticmethod
    def _alignment_bundle_visible_text(bundle: dict) -> str:
        metadata = bundle.get("metadata") if isinstance(bundle.get("metadata"), dict) else {}
        loop = bundle.get("loop") if isinstance(bundle.get("loop"), dict) else {}
        spec = bundle.get("spec") if isinstance(bundle.get("spec"), dict) else {}
        workflow = bundle.get("workflow") if isinstance(bundle.get("workflow"), dict) else {}
        parts = [
            str(metadata.get("name", "") or "") if isinstance(metadata, dict) else "",
            str(metadata.get("description", "") or "") if isinstance(metadata, dict) else "",
            str(bundle.get("collaboration_summary", "") or ""),
            str(loop.get("name", "") or "") if isinstance(loop, dict) else "",
            str(spec.get("markdown", "") or "") if isinstance(spec, dict) else "",
            str(workflow.get("collaboration_intent", "") or "") if isinstance(workflow, dict) else "",
        ]
        for role in bundle.get("role_definitions", []):
            if not isinstance(role, dict):
                continue
            parts.extend(
                [
                    str(role.get("name", "") or ""),
                    str(role.get("description", "") or ""),
                    str(role.get("prompt_markdown", "") or ""),
                    str(role.get("posture_notes", "") or ""),
                ]
            )
        return "\n".join(parts)

    @staticmethod
    def _alignment_bundle_agreement_projection_text(bundle: dict) -> str:
        spec = bundle.get("spec") if isinstance(bundle.get("spec"), dict) else {}
        workflow = bundle.get("workflow") if isinstance(bundle.get("workflow"), dict) else {}
        parts = [
            str(bundle.get("collaboration_summary", "") or ""),
            str(spec.get("markdown", "") or "") if isinstance(spec, dict) else "",
            str(workflow.get("collaboration_intent", "") or "") if isinstance(workflow, dict) else "",
        ]
        for role in bundle.get("role_definitions", []):
            if not isinstance(role, dict):
                continue
            parts.extend(
                [
                    str(role.get("description", "") or ""),
                    str(role.get("prompt_markdown", "") or ""),
                    str(role.get("posture_notes", "") or ""),
                ]
            )
        if isinstance(workflow, dict):
            workflow_projection = {
                "steps": [
                    {
                        "inputs": step.get("inputs") if isinstance(step.get("inputs"), dict) else {},
                        "action_policy": step.get("action_policy") if isinstance(step.get("action_policy"), dict) else {},
                        "control": step.get("control") if isinstance(step.get("control"), dict) else {},
                    }
                    for step in list(workflow.get("steps") or [])
                    if isinstance(step, dict)
                ],
                "controls": list(workflow.get("controls") or []) if isinstance(workflow.get("controls"), list) else [],
            }
            parts.append(json.dumps(workflow_projection, ensure_ascii=False, sort_keys=True))
        return "\n".join(parts)

    @staticmethod
    def _alignment_bundle_runtime_responsibility_projection_text(bundle: dict) -> str:
        spec_role_notes = ServiceAlignmentMixin._alignment_bundle_spec_role_notes_projection_text(bundle)
        workflow = bundle.get("workflow") if isinstance(bundle.get("workflow"), dict) else {}
        parts: list[str] = [spec_role_notes]
        for role in bundle.get("role_definitions", []):
            if not isinstance(role, dict):
                continue
            parts.extend(
                [
                    str(role.get("prompt_markdown", "") or ""),
                    str(role.get("posture_notes", "") or ""),
                    str(role.get("description", "") or ""),
                ]
            )
        if isinstance(workflow, dict):
            parts.append(str(workflow.get("collaboration_intent", "") or ""))
            workflow_projection = {
                "steps": [
                    {
                        "inputs": step.get("inputs") if isinstance(step.get("inputs"), dict) else {},
                        "action_policy": step.get("action_policy") if isinstance(step.get("action_policy"), dict) else {},
                        "control": step.get("control") if isinstance(step.get("control"), dict) else {},
                    }
                    for step in list(workflow.get("steps") or [])
                    if isinstance(step, dict)
                ],
                "controls": list(workflow.get("controls") or []) if isinstance(workflow.get("controls"), list) else [],
            }
            parts.append(json.dumps(workflow_projection, ensure_ascii=False, sort_keys=True))
        return "\n".join(parts)

    @staticmethod
    def _alignment_bundle_spec_role_notes_projection_text(bundle: dict) -> str:
        spec = bundle.get("spec") if isinstance(bundle.get("spec"), dict) else {}
        markdown = str(spec.get("markdown", "") or "") if isinstance(spec, dict) else ""
        if not markdown.strip():
            return ""
        try:
            compiled_spec = compile_markdown_spec(markdown)
        except SpecError:
            return ""
        raw_sections = compiled_spec.get("raw_sections") if isinstance(compiled_spec, dict) else {}
        return str(raw_sections.get("Role Notes") or "") if isinstance(raw_sections, dict) else ""

    @staticmethod
    def _text_has_cjk(value: object) -> bool:
        return any("\u4e00" <= char <= "\u9fff" for char in str(value or ""))

    @classmethod
    def _visible_alignment_agreement_message(cls, session: dict, working_agreement: dict) -> str:
        evidence = working_agreement.get("readiness_evidence")
        if not isinstance(evidence, dict):
            evidence = {}
        summary = cls._agreement_text_snippet(working_agreement.get("summary"), limit=360)
        values = {
            key: cls._agreement_text_snippet(evidence.get(key), limit=280)
            for key in (
                "loop_fit",
                "task_scope",
                "success_surface",
                "fake_done_risks",
                "evidence_preferences",
                "execution_strategy",
                "residual_risk_policy",
                "judgment_tradeoffs",
                "local_governance",
                "role_posture",
                "workflow_shape",
                "workdir_facts",
            )
        }
        if cls._alignment_prefers_chinese(session):
            return "\n".join(
                [
                    "请先确认这份工作协议。确认后我再生成 Loop 方案；如果任一判断不对，请直接指出要改哪一项。",
                    "",
                    f"摘要：{summary}",
                    f"为什么用 Loopora：{values['loop_fit']}",
                    f"任务范围：{values['task_scope']}",
                    f"成功面：{values['success_surface']}",
                    f"假完成风险：{values['fake_done_risks']}",
                    f"证据偏好：{values['evidence_preferences']}",
                    f"执行策略：{values['execution_strategy']}",
                    f"残余风险：{values['residual_risk_policy']}",
                    f"判断取舍：{values['judgment_tradeoffs']}",
                    f"本地治理：{values['local_governance']}",
                    f"角色姿态：{values['role_posture']}",
                    f"运行流程形状：{values['workflow_shape']}",
                    f"项目事实：{values['workdir_facts']}",
                ]
            )
        return "\n".join(
            [
                "Please confirm this working agreement. After confirmation I will generate the Loop plan; if any judgment is wrong, name the item to adjust.",
                "",
                f"Summary: {summary}",
                f"Loopora fit: {values['loop_fit']}",
                f"Task scope: {values['task_scope']}",
                f"Success surface: {values['success_surface']}",
                f"Fake-done risks: {values['fake_done_risks']}",
                f"Evidence preferences: {values['evidence_preferences']}",
                f"Execution strategy: {values['execution_strategy']}",
                f"Residual risk: {values['residual_risk_policy']}",
                f"Judgment tradeoffs: {values['judgment_tradeoffs']}",
                f"Local governance: {values['local_governance']}",
                f"Role posture: {values['role_posture']}",
                f"Run-flow shape: {values['workflow_shape']}",
                f"Project facts: {values['workdir_facts']}",
            ]
        )

    @staticmethod
    def _agreement_text_snippet(value: object, *, limit: int) -> str:
        text = " ".join(str(value or "").split())
        if len(text) <= limit:
            return text
        return text[: limit - 1].rstrip() + "…"

    @staticmethod
    def _readiness_evidence_issues(output: dict, *, workdir_snapshot: str = "") -> list[str]:
        evidence = output.get("readiness_evidence")
        if not isinstance(evidence, dict):
            return ["readiness_evidence"]
        generic_values = {
            "ok",
            "yes",
            "true",
            "done",
            "ready",
            "clear",
            "确认",
            "已确认",
            "无",
            "none",
            "n/a",
            "na",
            "unknown",
            "tbd",
        }
        issues: list[str] = []
        for key in ALIGNMENT_READINESS_EVIDENCE_KEYS:
            text = str(evidence.get(key, "") or "").strip()
            normalized = text.lower()
            if (
                len(text) < 16
                or normalized in generic_values
                or ServiceAlignmentMixin._readiness_evidence_semantic_issue(
                    key,
                    text,
                    workdir_snapshot=workdir_snapshot,
                )
            ):
                issues.append(key)
        if ServiceAlignmentMixin._open_questions_readiness_issue(evidence):
            issues.append("open_questions")
        if ServiceAlignmentMixin._readiness_evidence_bucket_projection_issue(evidence):
            issues.append("evidence_buckets")
        if ServiceAlignmentMixin._readiness_evidence_task_scoped_issue(evidence):
            issues.append("task_scoped_judgment")
        return issues

    @staticmethod
    def _readiness_evidence_bucket_projection_issue(evidence: dict) -> bool:
        text = " ".join(str(evidence.get(key, "") or "") for key in ALIGNMENT_READINESS_EVIDENCE_KEYS)
        bucket_patterns = {
            "proven": r"\bproven\b|已证明",
            "weak": r"\bweak\b|弱证据|证据薄弱",
            "unproven": r"\bunproven\b|未证明",
            "blocking": r"\bblocking\b|阻断",
            "residual": r"\bresidual risk\b|残余风险",
        }
        return not all(re.search(pattern, text, re.I) for pattern in bucket_patterns.values())

    @staticmethod
    def _readiness_evidence_task_scoped_issue(evidence: dict) -> bool:
        text = re.sub(
            r"\s+",
            " ",
            " ".join(str(evidence.get(key, "") or "") for key in ALIGNMENT_READINESS_EVIDENCE_KEYS),
        ).strip()
        patterns = (
            r"\b(?:global|permanent|always-on|chat-wide)\s+(?:user\s+)?"
            r"(?:persona|personality|preference|preferences|memory|trait|style)\b",
            r"\b(?:persona|personality|preference|preferences|style)\s+(?:memory|profile)\b",
            r"\b(?:remember|store|capture|codify)\s+(?:the\s+)?(?:user's|my)\s+"
            r"(?:persona|personality|preference|preferences|style|traits?)\b",
            r"\balways\s+(?:follow|use|prefer|behave|act|answer)\b.{0,80}\b(?:user|my)\b.{0,80}"
            r"\b(?:persona|personality|preference|preferences|style|trait)\b",
            r"全局(?:人格|偏好|记忆|画像)",
            r"永久(?:人格|偏好|记忆|画像)",
            r"(?:人格|偏好|用户画像|用户特质).{0,8}(?:记忆|长期记住|全局继承)",
            r"记住.{0,12}(?:我的|用户).{0,8}(?:偏好|人格|风格)",
            r"总是.{0,16}(?:按|遵循|使用).{0,12}(?:偏好|人格|风格)",
        )
        value = text.lower()
        for pattern in patterns:
            for match in re.finditer(pattern, value, re.I):
                if semantic_antipattern_match_is_negated(value, match.start()):
                    continue
                return True
        return False

    @staticmethod
    def _open_questions_readiness_issue(evidence: dict) -> bool:
        text = str(evidence.get("open_questions", "") or "").strip()
        if not text:
            return False
        normalized = text.lower()
        normalized_value = normalized.strip(" \t\r\n.。:：;；")
        exact_closed_values = {
            "none",
            "n/a",
            "na",
            "无",
            "没有",
        }
        closed_markers = (
            "no open questions",
            "no unresolved questions",
            "no remaining questions",
            "no remaining task-shaping questions",
            "none beyond explicit confirmation",
            "explicit confirmation only",
            "无未解决问题",
            "没有未解决问题",
            "没有开放问题",
            "没有剩余问题",
            "只等待明确确认",
            "仅等待明确确认",
        )
        confirmation_only_markers = (
            "waiting for explicit user confirmation of the working agreement",
            "waiting for explicit user confirmation of the improvement agreement",
            "waiting for user confirmation of the working agreement",
            "waiting for user confirmation of the improvement agreement",
            "等待用户明确确认这份工作协议",
            "等待用户明确确认这份改进协议",
            "等待用户确认这份工作协议",
            "等待用户确认这份改进协议",
        )
        return not (
            normalized_value in exact_closed_values
            or ServiceAlignmentMixin._has_any_marker(normalized, closed_markers)
            or ServiceAlignmentMixin._has_any_marker(normalized, confirmation_only_markers)
        )

    @staticmethod
    def _readiness_evidence_semantic_issue(key: str, text: str, *, workdir_snapshot: str = "") -> bool:
        normalized = str(text or "").lower()
        simple_checks = {
            "loop_fit": ServiceAlignmentMixin._loop_fit_evidence_contradiction_issue,
            "success_surface": ServiceAlignmentMixin._success_surface_evidence_placeholder_issue,
            "fake_done_risks": ServiceAlignmentMixin._fake_done_evidence_placeholder_issue,
            "evidence_preferences": ServiceAlignmentMixin._evidence_preference_placeholder_issue,
            "role_posture": ServiceAlignmentMixin._role_posture_placeholder_issue,
        }
        if key in simple_checks:
            return simple_checks[key](normalized)
        if key == "local_governance":
            return ServiceAlignmentMixin._local_governance_evidence_issue(
                normalized,
                workdir_snapshot=workdir_snapshot,
            )
        if key == "workdir_facts":
            return ServiceAlignmentMixin._workdir_facts_evidence_issue(normalized, workdir_snapshot=workdir_snapshot)
        if key == "residual_risk_policy":
            return residual_risk_is_unmanaged(text)
        return False

    @staticmethod
    def _loop_fit_evidence_contradiction_issue(value: str) -> bool:
        return text_mentions_loop_fit_contradiction(value)

    @staticmethod
    def _success_surface_evidence_placeholder_issue(value: str) -> bool:
        generic_patterns = (
            r"\b(?:good and useful|works? well|high[- ]quality result|successful result|good result)\b",
            r"(?:好用|有用|效果好|高质量|结果好)",
        )
        return any(re.search(pattern, value, re.I) for pattern in generic_patterns)

    @staticmethod
    def _fake_done_evidence_placeholder_issue(value: str) -> bool:
        if not re.search(r"\b(?:avoid bugs?|no bugs?|high[- ]quality|bug[- ]free)\b|避免\s*bug|高质量|没有\s*bug", value, re.I):
            return False
        concrete_risk_markers = (
            r"\b(?:claim|claims|screenshot|happy[- ]path|proof|evidence|artifact|audit|permission|export|download|unproven|weak)\b",
            r"声称|截图|happy path|证明|证据|产物|审计|权限|导出|下载|未证明|弱证据",
        )
        return not any(re.search(pattern, value, re.I) for pattern in concrete_risk_markers)

    @staticmethod
    def _evidence_preference_placeholder_issue(value: str) -> bool:
        if not re.search(r"\b(?:need proof|enough proof|feel confident|evidence is needed|needs evidence)\b|需要证明|足够证明|有信心", value, re.I):
            return False
        proof_type_markers = (
            r"\b(?:test|tests|command|browser|journey|artifact|log|audit|screenshot|fixture|trace|coverage|contract|schema|lint)\b",
            r"测试|命令|浏览器|旅程|产物|日志|审计|截图|fixture|覆盖|契约|schema|lint",
        )
        return not any(re.search(pattern, value, re.I) for pattern in proof_type_markers)

    @staticmethod
    def _role_posture_placeholder_issue(value: str) -> bool:
        if ServiceAlignmentMixin._role_posture_without_gatekeeper_judgment_issue(value):
            return True
        if not re.search(r"\b(?:use|add|configure)\s+(?:two|three|multiple|[2-9])\s+roles?\b|使用.{0,8}(?:两个|三个|多个|[2-9]\s*个).{0,6}角色", value, re.I):
            return False
        role_responsibility_markers = (
            r"\b(?:builder|inspector|guide|gatekeeper|custom|build|inspect|verify|judge|block|repair)\b",
            r"builder|inspector|guide|gatekeeper|构建|检查|验证|裁决|阻断|修复",
        )
        return not any(re.search(pattern, value, re.I) for pattern in role_responsibility_markers)

    @staticmethod
    def _role_posture_without_gatekeeper_judgment_issue(value: str) -> bool:
        mentions_role_work = re.search(
            r"\b(?:builder|inspector|guide|custom|build|inspect|verify|review|handoff)\b|构建|检查|验证|审查|交接",
            value,
            re.I,
        )
        if not mentions_role_work:
            return False
        gatekeeper_judgment = re.search(
            r"\bgatekeeper\b.{0,80}\b(?:judges?|decides?|verdict|blocks?|blockers?|closes?|finishes?|fails?[- ]closed|final|strict)\b|"
            r"\b(?:judges?|decides?|verdict|blocks?|blockers?|closes?|finishes?|fails?[- ]closed|final|strict)\b.{0,80}\bgatekeeper\b|"
            r"gatekeeper.{0,40}(?:裁决|判定|判断|阻断|收束|关闭|严格|失败关闭|最终)",
            value,
            re.I,
        )
        return gatekeeper_judgment is None

    @staticmethod
    def _local_governance_evidence_issue(text: str, *, workdir_snapshot: str = "") -> bool:
        marker_pattern = r"agents\.md|design/readme\.md|design/|tests/|project-local|project local|项目本地|本地治理"
        if not re.search(marker_pattern, text, re.I) and not ServiceAlignmentMixin._workdir_snapshot_has_governance_markers(
            workdir_snapshot
        ):
            return False
        return not ServiceAlignmentMixin._governance_marker_responsibilities_present(text)

    @staticmethod
    def _workdir_snapshot_has_governance_markers(workdir_snapshot: str) -> bool:
        snapshot = str(workdir_snapshot or "").lower()
        return any(
            marker in snapshot
            for marker in (
                "agents.md exists: yes",
                "applicable agents.md exists: yes",
                "design/ exists: yes",
                "design/readme.md exists: yes",
                "tests/ exists: yes",
            )
        )

    @staticmethod
    def _alignment_improvement_readiness_issues(session: dict, output: dict) -> list[str]:
        previous_agreement = session.get("working_agreement") if isinstance(session.get("working_agreement"), dict) else {}
        if str(previous_agreement.get("mode") or "") != "improvement":
            return []
        evidence = output.get("readiness_evidence") if isinstance(output.get("readiness_evidence"), dict) else {}
        combined = " ".join(
            [
                str(output.get("agreement_summary", "") or ""),
                *(str(evidence.get(key, "") or "") for key in ALIGNMENT_READINESS_EVIDENCE_KEYS),
            ]
        ).lower()
        issues: list[str] = []
        if not ServiceAlignmentMixin._has_any_marker(
            combined,
            (
                "preserve",
                "keep",
                "stable",
                "unchanged",
                "existing intent",
                "保留",
                "保持",
                "稳定",
                "不变",
                "既有意图",
            ),
        ):
            issues.append("improvement_preservation")
        if not ServiceAlignmentMixin._has_any_marker(
            combined,
            (
                "change",
                "revise",
                "improve",
                "adjust",
                "feedback",
                "evidence gap",
                "改进",
                "修订",
                "调整",
                "反馈",
                "证据缺口",
            ),
        ):
            issues.append("improvement_delta")
        if not ServiceAlignmentMixin._has_any_marker(
            combined,
            (
                "spec",
                "role",
                "workflow",
                "evidence",
                "gatekeeper",
                "surface",
                "roles",
                "证据",
                "角色",
                "裁决",
                "治理面",
            ),
        ):
            issues.append("improvement_surface")
        source = previous_agreement.get("source") if isinstance(previous_agreement.get("source"), dict) else {}
        has_run_context = str(source.get("source_type") or "") == "run" and (
            source.get("coverage_summary") or source.get("evidence_summary") or source.get("task_verdict") or source.get("gatekeeper_verdict")
        )
        if has_run_context and not ServiceAlignmentMixin._has_any_marker(
            combined,
            (
                "run evidence",
                "coverage",
                "verdict",
                "gatekeeper verdict",
                "evidence summary",
                "运行证据",
                "覆盖",
                "裁决",
                "证据摘要",
            ),
        ):
            issues.append("run_evidence_translation")
        source_completion_mode = str(source.get("source_completion_mode") or "").strip().lower()
        if source_completion_mode and source_completion_mode != "gatekeeper":
            has_source_completion_mode_delta = ServiceAlignmentMixin._has_any_marker(
                combined,
                (
                    "completion mode",
                    "completion_mode",
                    "`rounds`",
                    "rounds completion",
                    "source uses rounds",
                    "run lifecycle",
                    "lifecycle completion",
                    "source completion",
                    "完成模式",
                    "运行生命周期",
                    "生命周期收束",
                ),
            ) and ServiceAlignmentMixin._has_any_marker(
                combined,
                (
                    "gatekeeper",
                    "task verdict",
                    "evidence-based verdict",
                    "证据裁决",
                    "loop 裁决",
                    "任务裁决",
                    "守门",
                ),
            )
            if not has_source_completion_mode_delta:
                issues.append("improvement_completion_mode_delta")
        return issues

    @staticmethod
    def _has_any_marker(text: str, markers: tuple[str, ...]) -> bool:
        return any(marker in text for marker in markers)

    @staticmethod
    def _extend_unique_alignment_issues(issues: list[str], additions: list[str]) -> None:
        for issue in additions:
            if issue not in issues:
                issues.append(issue)

    @staticmethod
    def _workdir_facts_evidence_issue(text: str, *, workdir_snapshot: str = "") -> bool:
        has_grounding_marker = ServiceAlignmentMixin._has_any_marker(
            text,
            (
                "observed",
                "snapshot",
                "appears",
                "assumption",
                "assumed",
                "unknown",
                "uncertain",
                "cannot confirm",
                "empty",
                "观察",
                "看到",
                "快照",
                "看起来",
                "假设",
                "未知",
                "不确定",
                "无法确认",
                "空目录",
            ),
        )
        if not has_grounding_marker:
            return True
        return ServiceAlignmentMixin._workdir_facts_claims_unsupported_observed_stack(
            text,
            workdir_snapshot=workdir_snapshot,
        )

    @staticmethod
    def _workdir_facts_claims_unsupported_observed_stack(text: str, *, workdir_snapshot: str = "") -> bool:
        if not ServiceAlignmentMixin._has_any_marker(text, ("observed", "snapshot", "appears", "观察", "看到", "快照", "看起来")):
            return False
        if ServiceAlignmentMixin._has_any_marker(text, ("unknown", "uncertain", "assumption", "无法确认", "未知", "不确定", "假设")):
            return False
        snapshot = str(workdir_snapshot or "").lower()
        support_markers = {
            "package.json": ("react", "vue", "svelte", "next", "vite", "node", "npm", "pnpm", "yarn", "javascript", "typescript", "frontend", "前端"),
            "pyproject.toml": ("python", "pytest", "ruff", "uv", "fastapi", "django", "flask"),
            "requirements.txt": ("python", "pytest", "fastapi", "django", "flask"),
            "cargo.toml": ("rust", "cargo"),
            "go.mod": ("go ", "golang"),
            "tests/ exists: yes": ("test", "tests", "testing", "测试"),
        }
        unsupported_terms = []
        for marker, terms in support_markers.items():
            if marker in snapshot:
                continue
            unsupported_terms.extend(term for term in terms if term in text)
        return bool(unsupported_terms)

    @staticmethod
    def _alignment_stage_updates_for_user_message(session: dict, message: str) -> dict[str, Any]:
        stage = str(session.get("alignment_stage", "") or "clarifying")
        status = str(session.get("status", "") or "")
        if stage == "agreement_ready":
            agreement = dict(session.get("working_agreement") or {})
            checklist = dict(agreement.get("readiness_checklist") or {})
            if ServiceAlignmentMixin._message_confirms_alignment_agreement(message):
                checklist["explicit_confirmation"] = True
                agreement["readiness_checklist"] = checklist
                agreement["confirmed_at"] = utc_now()
                agreement["confirmation_message"] = message
                return {"alignment_stage": "confirmed", "working_agreement": agreement}
            checklist["explicit_confirmation"] = False
            agreement["readiness_checklist"] = checklist
            agreement["confirmed_at"] = ""
            agreement["confirmation_message"] = ""
            return {"alignment_stage": "clarifying", "working_agreement": agreement}
        if status == "ready":
            agreement = dict(session.get("working_agreement") or {})
            ready_review = dict(agreement.get("ready_review") or {})
            ready_review["feedback"] = message
            ready_review["requested_at"] = utc_now()
            ready_review["source_status"] = status
            agreement["ready_review"] = ready_review
            return {"alignment_stage": "ready_review", "working_agreement": agreement}
        if status in {"imported", "running_loop"}:
            return {
                "alignment_stage": "clarifying",
                "working_agreement": session.get("working_agreement") or {},
            }
        if status == "failed" and stage not in ALIGNMENT_CONFIRMED_STAGES:
            return {"alignment_stage": "clarifying"}
        return {}

    @staticmethod
    def _merge_alignment_improvement_context(previous: object, working_agreement: dict) -> dict:
        if not isinstance(previous, dict) or previous.get("mode") != "improvement":
            return working_agreement
        merged = dict(working_agreement)
        for key in ("mode", "source", "seed_bundle_metadata"):
            if key in previous and key not in merged:
                merged[key] = previous[key]
        return merged

    @staticmethod
    def _message_confirms_alignment_agreement(message: str) -> bool:
        normalized = str(message or "").strip().lower()
        if not normalized:
            return False
        if normalized in {"no", "nope"}:
            return False
        negative_scan = normalized
        for no_change_marker in (
            "但是不需要修改",
            "但不需要修改",
            "不过不需要修改",
            "不需要修改",
            "但是不用修改",
            "但不用修改",
            "不过不用修改",
            "不用修改",
            "但是无需修改",
            "但无需修改",
            "不过无需修改",
            "无需修改",
            "但是不需要调整",
            "但不需要调整",
            "不过不需要调整",
            "不需要调整",
            "但是不用调整",
            "但不用调整",
            "不过不用调整",
            "不用调整",
            "但是无需调整",
            "但无需调整",
            "不过无需调整",
            "无需调整",
            "但是不需要改",
            "但不需要改",
            "不过不需要改",
            "不需要改",
            "但是不用改",
            "但不用改",
            "不过不用改",
            "不用改",
            "但是无需改",
            "但无需改",
            "不过无需改",
            "无需改",
            "but no changes",
            "but no change",
            "but without changes",
            "no changes",
            "no change",
            "without changes",
        ):
            negative_scan = negative_scan.replace(no_change_marker, "")
        negative_tokens = [
            "不确认",
            "不同意",
            "不要",
            "先别",
            "不是",
            "不对",
            "但是",
            "不过",
            "但",
            "改成",
            "改为",
            "改一下",
            "增加",
            "补充",
            "添加",
            "删除",
            "去掉",
            "修改",
            "调整",
            "换成",
            "再改",
            " no",
            "not",
            " but",
            "add",
            "change",
            "delete",
            "remove",
            "revise",
            "adjust",
            "instead",
        ]
        if any(token in negative_scan for token in negative_tokens):
            return False
        confirm_tokens = [
            "确认",
            "同意",
            "可以",
            "就这样",
            "按这个",
            "没问题",
            "继续",
            "ok",
            "yes",
            "confirm",
            "approved",
            "go ahead",
            "proceed",
        ]
        return any(token in normalized for token in confirm_tokens)

    def _write_and_validate_alignment_bundle(self, session_id: str, bundle_yaml: str) -> tuple[bool, str]:
        session = self.get_alignment_session(session_id)
        bundle_path = Path(session["bundle_path"])
        bundle_path.parent.mkdir(parents=True, exist_ok=True)
        bundle_path.write_text(bundle_yaml.rstrip() + "\n", encoding="utf-8")
        session = self.repository.update_alignment_session(session_id, status="validating", alignment_stage="compiling")
        self.repository.append_alignment_event(
            session_id,
            "alignment_bundle_written",
            {
                "bundle_path": str(bundle_path),
                "size": len(bundle_yaml),
                "bundle_sha256": sha256(bundle_yaml.encode("utf-8")).hexdigest(),
            },
        )
        semantic_issues: list[str] = []
        try:
            _bundle, normalized_yaml = self._load_validated_alignment_bundle_text(session, bundle_yaml, semantic_issues)
            bundle_path.write_text(normalized_yaml, encoding="utf-8")
        except (BundleError, LooporaError) as exc:
            error = str(exc)
            validation = {
                "ok": False,
                "error": error,
                "bundle_path": str(bundle_path),
                "checked_at": utc_now(),
                "semantic_lint": {"ok": not semantic_issues, "issues": semantic_issues},
            }
            self.repository.update_alignment_session(session_id, validation=validation, error_message=error)
            self._write_alignment_validation_log(self.get_alignment_session(session_id), validation)
            self.repository.append_alignment_event(
                session_id,
                "alignment_validation_failed",
                validation,
            )
            return False, error
        validation = {
            "ok": True,
            "error": "",
            "bundle_path": str(bundle_path),
            "checked_at": utc_now(),
            "semantic_lint": {"ok": True, "issues": []},
            **self._alignment_bundle_content_fingerprint(normalized_yaml),
        }
        self.repository.update_alignment_session(session_id, validation=validation)
        self._write_alignment_validation_log(self.get_alignment_session(session_id), validation)
        self.repository.append_alignment_event(
            session_id,
            "alignment_validation_passed",
            validation,
        )
        return True, ""

    def _record_alignment_bundle_sync_failure(self, session_id: str, validation: dict) -> dict:
        error = str(validation.get("error", "") or "bundle validation failed")
        session = self._append_alignment_system_message(
            session_id,
            zh=f"重新读取 bundle.yml 失败：{error}",
            en=f"Failed to reload bundle.yml: {error}",
        )
        self.repository.update_alignment_session(
            session_id,
            status="failed",
            validation=validation,
            error_message=error,
            finished_at=utc_now(),
            clear_active_child_pid=True,
        )
        session = self.get_alignment_session(session_id)
        self._write_alignment_validation_log(session, validation)
        self._write_alignment_transcript_log(session)
        self.repository.append_alignment_event(
            session_id,
            "alignment_bundle_sync_failed",
            validation,
        )
        return {
            "ok": False,
            "session": session,
            "yaml": "",
            "bundle": None,
            "validation": validation,
        }

    def _append_alignment_system_message(self, session_id: str, *, zh: str, en: str) -> dict:
        session = self.get_alignment_session(session_id)
        transcript = list(session.get("transcript") or [])
        content = zh if self._alignment_prefers_chinese(session) else en
        transcript.append({"role": "assistant", "content": content, "created_at": utc_now()})
        self.repository.update_alignment_session(session_id, transcript=transcript)
        updated = self.get_alignment_session(session_id)
        self._write_alignment_transcript_log(updated)
        return updated

    @staticmethod
    def _alignment_prefers_chinese(session: dict) -> bool:
        text = "\n".join(
            str(item.get("content", "") or "")
            for item in (session.get("transcript") or [])
            if item.get("role") == "user" and not ServiceAlignmentMixin._message_is_language_neutral_confirmation(item.get("content"))
        )
        return ServiceAlignmentMixin._text_has_cjk(text)

    @classmethod
    def _alignment_generation_prefers_chinese(cls, session: dict) -> bool:
        agreement = session.get("working_agreement") if isinstance(session.get("working_agreement"), dict) else {}
        if str(session.get("alignment_stage") or "") == "ready_review" or isinstance(agreement.get("ready_review"), dict):
            agreement_text = cls._alignment_working_agreement_language_text(session)
            if agreement_text.strip():
                return cls._text_has_cjk(agreement_text)
        return cls._alignment_prefers_chinese(session)

    @staticmethod
    def _alignment_working_agreement_language_text(session: dict) -> str:
        agreement = session.get("working_agreement") if isinstance(session.get("working_agreement"), dict) else {}
        if not agreement:
            return ""
        language_projection = {
            "summary": agreement.get("summary", ""),
            "readiness_evidence": agreement.get("readiness_evidence") or {},
        }
        return json.dumps(language_projection, ensure_ascii=False)

    @classmethod
    def _alignment_user_language_hint(cls, session: dict) -> str:
        agreement = session.get("working_agreement") if isinstance(session.get("working_agreement"), dict) else {}
        if (str(session.get("alignment_stage") or "") == "ready_review" or isinstance(agreement.get("ready_review"), dict)) and cls._alignment_working_agreement_language_text(session).strip():
            if cls._alignment_generation_prefers_chinese(session):
                return "Chinese. Preserve the existing READY preview and working-agreement language unless the review feedback explicitly asks to translate; preserve Loopora terms unchanged."
            return "Preserve the existing READY preview and working-agreement language unless the review feedback explicitly asks to translate; preserve Loopora terms unchanged."
        if cls._alignment_prefers_chinese(session):
            return "Chinese. Keep user-facing prose in Chinese and preserve Loopora terms unchanged."
        return "Follow the user's language from the transcript and preserve Loopora terms unchanged."

    @staticmethod
    def _message_is_language_neutral_confirmation(message: object) -> bool:
        normalized = str(message or "").strip().lower()
        normalized = normalized.strip(" \t\r\n.!?。！？,，;；:：\"'“”‘’")
        return normalized in ALIGNMENT_LANGUAGE_NEUTRAL_CONFIRMATIONS

    @staticmethod
    def _add_alignment_context_option(option: dict, options: list[dict], seen_option_ids: set[str]) -> None:
        option_id = str(option.get("option_id") or "").strip()
        if not option_id or option_id in seen_option_ids:
            return
        for key in ("label_zh", "label_en", "description_zh", "description_en"):
            if key in option:
                option[key] = redact_sensitive_text(str(option.get(key) or ""))
        seen_option_ids.add(option_id)
        options.append(option)

    @staticmethod
    def _bounded_alignment_context_options(options: list[dict], *, limit: int = 20) -> list[dict]:
        if len(options) <= limit:
            return options
        regenerate = next((option for option in options if option.get("option_id") == "regenerate"), None)
        bounded = options[:limit]
        if regenerate is not None and all(option.get("option_id") != "regenerate" for option in bounded):
            bounded = [*bounded[: max(0, limit - 1)], regenerate]
        return bounded

    def _resolve_run_context(self, root: Path, *, adapter: str, context_id: str) -> dict:
        normalized_adapter = str(adapter or "").strip()
        base = {
            "schema_version": 1,
            "intent": "run",
            "workdir": str(root),
            "adapter": normalized_adapter,
            "context_id": str(context_id or "").strip(),
            "requires_user_choice": False,
            "choices": [],
        }
        if normalized_adapter:
            try:
                binding = read_agent_binding(normalized_adapter, root, context_id=context_id)
            except LooporaError as exc:
                return {
                    **base,
                    "action": "repair_agent_binding",
                    "confidence": "damaged_binding",
                    "binding_error": str(exc),
                    "message": "Agent binding is unreadable; repair it or choose a recoverable context before /loopora-run starts.",
                }
            if binding:
                return self._resolve_run_context_from_exact_binding(root, base=base, binding=binding)
        choices = self._agent_run_context_choices(root, adapter=normalized_adapter)
        if choices:
            return {
                **base,
                "action": "choose_recoverable_context",
                "confidence": "single_recoverable" if len(choices) == 1 else "ambiguous",
                "requires_user_choice": True,
                "choices": choices,
                "message": "Choose a recoverable Loopora run context before /loopora-run starts.",
            }
        return {
            **base,
            "action": "plan_first",
            "confidence": "no_binding",
            "message": "No Loopora run context is bound to this Agent session/workdir; run /loopora-plan first.",
        }

    def _resolve_run_context_from_exact_binding(self, root: Path, *, base: dict, binding: dict) -> dict:
        session_id = str(binding.get("alignment_session_id") or "").strip()
        if not session_id:
            return {
                **base,
                "action": "blocked",
                "confidence": "stale_binding",
                "binding": self._redact_agent_context_binding(binding),
                "message": "Agent binding exists but does not reference a Loop preview; run /loopora-plan again.",
            }
        try:
            session = self.get_alignment_session(session_id)
        except LooporaError:
            return {
                **base,
                "action": "blocked",
                "confidence": "stale_binding",
                "binding": self._redact_agent_context_binding(binding),
                "alignment_session_id": session_id,
                "message": "Agent binding references a missing Loop preview; run /loopora-plan again.",
            }
        if not self._same_alignment_workdir(binding.get("workdir") or session.get("workdir"), root):
            return {
                **base,
                "action": "blocked",
                "confidence": "workdir_mismatch",
                "binding": self._redact_agent_context_binding(binding),
                "alignment_session_id": session_id,
                "message": "Agent binding belongs to a different workdir; run /loopora-plan again.",
            }
        choice = self._agent_run_context_choice_from_session(session, adapter=str(base.get("adapter") or ""))
        action = "resume_run"
        if choice.get("linked_run_id"):
            action = "resume_run"
        elif choice.get("alignment_status") in {"ready", "imported"}:
            action = "start_ready_preview"
        else:
            action = "blocked"
        return {
            **base,
            "action": action,
            "confidence": "exact_binding",
            "alignment_session_id": session_id,
            "binding": self._redact_agent_context_binding(binding),
            "choice": choice,
            "message": "Exact Agent binding found.",
        }

    def _agent_run_context_choices(self, root: Path, *, adapter: str) -> list[dict]:
        list_sessions = getattr(self.repository, "list_all_alignment_sessions", None)
        sessions = list_sessions() if callable(list_sessions) else self.repository.list_alignment_sessions(limit=100)
        choices: list[dict] = []
        seen: set[str] = set()
        for session in sessions:
            if not self._same_alignment_workdir(session.get("workdir"), root):
                continue
            candidate_event = self._alignment_session_agent_entry_candidate_event(str(session.get("id") or ""))
            if not candidate_event:
                continue
            payload = candidate_event.get("payload") if isinstance(candidate_event.get("payload"), dict) else {}
            event_adapter = str(payload.get("adapter") or session.get("executor_kind") or "").strip()
            if adapter and event_adapter != adapter:
                continue
            choice = self._agent_run_context_choice_from_session(session, adapter=event_adapter, payload=payload)
            option_id = str(choice.get("option_id") or "")
            if option_id and option_id not in seen:
                choices.append(choice)
                seen.add(option_id)
        return self._bounded_alignment_context_options(choices)

    def _agent_run_context_choice_from_session(self, session: dict, *, adapter: str, payload: dict | None = None) -> dict:
        session_id = str(session.get("id") or "").strip()
        linked_run_id = str(session.get("linked_run_id") or "").strip()
        option_id = self._alignment_source_option_id("agent_run", session_id)
        entry_source = str((payload or {}).get("entry_source") or "")
        linked_run_status = ""
        next_action = "start_ready_preview"
        if linked_run_id:
            try:
                run = self.get_run(linked_run_id)
                linked_run_status = str(run.get("status") or "")
                next_action = "replay_terminal_run" if linked_run_status in TERMINAL_RUN_STATUSES else "resume_active_run"
            except LooporaError:
                next_action = "stale_linked_run"
        elif str(session.get("status") or "") not in {"ready", "imported"}:
            next_action = "preview_not_ready"
        title = self._alignment_context_title_from_session(session)
        return {
            "option_id": option_id,
            "action": next_action,
            "source_type": "agent_entry",
            "adapter": adapter,
            "alignment_session_id": session_id,
            "alignment_status": str(session.get("status") or ""),
            "linked_run_id": linked_run_id,
            "linked_run_status": linked_run_status,
            "updated_at": session.get("updated_at", ""),
            "entry_source": entry_source,
            "host_context_id": str((payload or {}).get("host_context_id") or ""),
            "next_command": f"/loopora-run option:{option_id}",
            "agent_cli_command": agent_loop_command(
                adapter,
                str(session.get("workdir") or "."),
                entry_source=entry_source,
                source_option_id=option_id,
            )
            if adapter
            else "",
            "label_zh": f"恢复 Agent 运行：{title}",
            "label_en": f"Resume Agent run: {title}",
            "description_zh": "回到这个 Agent Native Loop 的现有运行或 READY 预览；不会重新规划。",
            "description_en": "Return to this Agent Native Loop's existing run or READY preview without replanning.",
        }

    @staticmethod
    def _redact_agent_context_binding(binding: dict) -> dict:
        return {
            key: redact_sensitive_value(key, value)
            for key, value in binding.items()
            if key
            in {
                "path",
                "alignment_session_id",
                "alignment_status",
                "linked_run_id",
                "linked_loop_id",
                "linked_bundle_id",
                "workdir",
                "host_context_id",
                "context_source",
                "updated_at",
                "requires_web_alignment",
                "requires_candidate_repair",
                "loopora_fit_contradiction",
                "preview_path",
                "run_path",
            }
        }

    def _collect_alignment_session_context_options(self, root: Path, options: list[dict], seen_option_ids: set[str]) -> set[str]:
        seen_bundle_paths: set[str] = set()
        for session in self.repository.list_alignment_sessions(limit=100):
            if not self._same_alignment_workdir(session.get("workdir"), root):
                continue
            for option in self._alignment_session_context_options(session):
                self._add_alignment_context_option(option, options, seen_option_ids)
                bundle_path = str(option.get("bundle_path") or "").strip()
                if bundle_path:
                    seen_bundle_paths.add(str(Path(bundle_path).expanduser().resolve()))
        return seen_bundle_paths

    def _collect_alignment_loop_context_options(self, root: Path, options: list[dict], seen_option_ids: set[str]) -> set[str]:
        seen_spec_paths: set[str] = set()
        for loop in self.list_loops():
            if not self._same_alignment_workdir(loop.get("workdir"), root):
                continue
            spec_path = str(loop.get("spec_path") or "").strip()
            if spec_path:
                seen_spec_paths.add(str(Path(spec_path).expanduser().resolve()))
            latest_run_id = str(loop.get("latest_run_id") or "").strip()
            if latest_run_id:
                with suppress(LooporaError):
                    self._add_alignment_context_option(
                        self._alignment_run_context_option(self.get_run(latest_run_id), loop=loop),
                        options,
                        seen_option_ids,
                    )
            bundle = loop.get("bundle") if isinstance(loop.get("bundle"), dict) else {}
            bundle_id = str(bundle.get("id") or "").strip()
            option = (
                self._alignment_bundle_context_option(bundle_id, loop=loop, bundle=bundle)
                if bundle_id
                else self._alignment_loop_context_option(loop)
            )
            self._add_alignment_context_option(option, options, seen_option_ids)
        return seen_spec_paths

    def _collect_alignment_filesystem_context_options(
        self,
        state_dir: Path,
        options: list[dict],
        seen_option_ids: set[str],
        *,
        seen_bundle_paths: set[str],
        seen_spec_paths: set[str],
    ) -> None:
        if not state_dir.exists():
            return
        expected_workdir = state_dir.parent
        for bundle_path in sorted((state_dir / "alignment_sessions").glob("*/artifacts/bundle.yml"))[:20]:
            resolved_bundle_path = str(bundle_path.expanduser().resolve())
            if resolved_bundle_path in seen_bundle_paths:
                continue
            seen_bundle_paths.add(resolved_bundle_path)
            if not self._alignment_bundle_file_has_ready_validation(bundle_path, expected_workdir=expected_workdir):
                continue
            self._add_alignment_context_option(
                self._alignment_file_bundle_context_option(
                    source_session_id=bundle_path.parent.parent.name,
                    bundle_path=bundle_path,
                ),
                options,
                seen_option_ids,
            )
        for spec_path in self._alignment_workdir_spec_candidates(state_dir):
            resolved_spec = str(spec_path.expanduser().resolve())
            if resolved_spec in seen_spec_paths:
                continue
            seen_spec_paths.add(resolved_spec)
            self._add_alignment_context_option(self._alignment_spec_file_context_option(spec_path), options, seen_option_ids)

    @staticmethod
    def _alignment_bundle_file_has_ready_validation(bundle_path: Path, *, expected_workdir: Path | None = None) -> bool:
        validation_path = bundle_path.parent / "validation.json"
        try:
            payload = json.loads(validation_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return False
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            return False
        return ServiceAlignmentMixin._alignment_bundle_file_is_valid_alignment_bundle(
            bundle_path,
            expected_workdir=expected_workdir,
        )

    @staticmethod
    def _alignment_bundle_file_is_valid_alignment_bundle(
        bundle_path: Path,
        *,
        expected_workdir: Path | None = None,
    ) -> bool:
        try:
            raw_yaml = read_bundle_file_text(bundle_path)
            generation_issues = lint_alignment_bundle_generation_text(raw_yaml)
            bundle = load_bundle_text(raw_yaml)
            if expected_workdir is not None:
                ServiceAlignmentMixin._assert_alignment_bundle_workdir(bundle, expected_workdir=expected_workdir)
            semantic_issues = lint_alignment_bundle_semantics(bundle)
        except (BundleError, LooporaError, OSError):
            return False
        return not generation_issues and not semantic_issues

    @staticmethod
    def _same_alignment_workdir(candidate: object, expected: Path) -> bool:
        candidate_text = str(candidate or "").strip()
        if not candidate_text:
            return False
        try:
            return Path(candidate_text).expanduser().resolve() == expected.expanduser().resolve()
        except OSError:
            return False

    @staticmethod
    def _alignment_source_option_id(source_type: str, identifier: object) -> str:
        normalized_identifier = str(identifier or "").strip()
        if source_type == "spec_file":
            digest = sha256(normalized_identifier.encode("utf-8")).hexdigest()[:16]
            return f"spec_file:{digest}"
        safe_identifier = re.sub(r"[^A-Za-z0-9_.:-]+", "-", normalized_identifier).strip("-")
        return f"{source_type}:{safe_identifier}"

    @staticmethod
    def _alignment_context_title_from_session(session: dict) -> str:
        for entry in session.get("transcript") or []:
            if not isinstance(entry, dict) or entry.get("role") != "user":
                continue
            content = redact_sensitive_text(str(entry.get("content", "") or "").strip())
            if content:
                return content[:80]
        return str(session.get("id") or "alignment session")

    @classmethod
    def _alignment_session_context_options(cls, session: dict) -> list[dict]:
        session_id = str(session.get("id") or "").strip()
        if not session_id:
            return []
        title = cls._alignment_context_title_from_session(session)
        status = str(session.get("status") or "")
        options: list[dict] = []
        if status in {"idle", "running", "waiting_user", "ready", "failed"}:
            options.append(
                {
                    "option_id": cls._alignment_source_option_id("continue_session", session_id),
                    "action": "continue_session",
                    "source_type": "alignment_session",
                    "session_id": session_id,
                    "status": status,
                    "updated_at": session.get("updated_at", ""),
                    "label_zh": f"继续对话：{title}",
                    "label_en": f"Continue chat: {title}",
                    "description_zh": "回到这个已有对话，并把下一条消息追加到同一个对话。",
                    "description_en": "Return to this chat and append the next message to the same session.",
                }
            )
        bundle_path = Path(str(session.get("bundle_path") or ""))
        if status == "ready" and bundle_path.exists() and cls._alignment_session_has_current_ready_bundle(session, bundle_path):
            options.append(
                {
                    "option_id": cls._alignment_source_option_id("alignment_session", session_id),
                    "action": "improve",
                    "source_type": "alignment_session",
                    "source_alignment_session_id": session_id,
                    "status": status,
                    "bundle_path": str(bundle_path),
                    "updated_at": session.get("updated_at", ""),
                    "label_zh": f"基于 READY 方案改进：{title}",
                    "label_en": f"Improve READY plan: {title}",
                    "description_zh": "把这个对话的 READY 方案文件和对话摘要作为新对话的来源上下文。",
                    "description_en": "Use this session's READY plan file and conversation summary as source context for a new chat.",
                }
            )
        return options

    @classmethod
    def _alignment_session_has_current_ready_bundle(cls, session: dict, bundle_path: Path) -> bool:
        expected_workdir = Path(session["workdir"]) if session.get("workdir") else None
        validation = session.get("validation") if isinstance(session.get("validation"), dict) else {}
        if validation.get("ok") is True:
            return cls._alignment_bundle_file_is_valid_alignment_bundle(
                bundle_path,
                expected_workdir=expected_workdir,
            )
        return cls._alignment_bundle_file_has_ready_validation(bundle_path, expected_workdir=expected_workdir)

    @classmethod
    def _alignment_file_bundle_context_option(cls, *, source_session_id: str, bundle_path: Path) -> dict:
        return {
            "option_id": cls._alignment_source_option_id("alignment_session_file", bundle_path),
            "action": "improve",
            "source_type": "alignment_session_file",
            "source_alignment_session_id": source_session_id,
            "bundle_path": str(bundle_path),
            "label_zh": f"基于本地 READY 方案改进：{source_session_id}",
            "label_en": f"Improve local READY plan: {source_session_id}",
            "description_zh": "读取同目录 .loopora 中的 READY 方案文件作为来源上下文。",
            "description_en": "Read the READY plan file from this workdir's .loopora state as source context.",
        }

    @classmethod
    def _alignment_bundle_context_option(cls, bundle_id: str, *, loop: dict, bundle: dict) -> dict:
        name = str(bundle.get("name") or loop.get("name") or bundle_id)
        return {
            "option_id": cls._alignment_source_option_id("bundle", bundle_id),
            "action": "improve",
            "source_type": "bundle",
            "source_bundle_id": bundle_id,
            "source_loop_id": str(loop.get("id") or ""),
            "label_zh": f"基于已有方案改进：{name}",
            "label_en": f"Improve existing plan: {name}",
            "description_zh": "使用已导入方案文件里的任务契约、角色责任和运行流程作为候选基础。",
            "description_en": "Use the imported plan file's task contract, role responsibilities, and run flow as the candidate base.",
        }

    @classmethod
    def _alignment_loop_context_option(cls, loop: dict) -> dict:
        loop_id = str(loop.get("id") or "").strip()
        name = str(loop.get("name") or loop_id)
        return {
            "option_id": cls._alignment_source_option_id("loop", loop_id),
            "action": "improve",
            "source_type": "loop",
            "source_loop_id": loop_id,
            "label_zh": f"基于已有 Loop 改进：{name}",
            "label_en": f"Improve existing Loop: {name}",
            "description_zh": "从这个 Loop 已保存的任务契约、角色责任和运行流程派生候选方案。",
            "description_en": "Derive a candidate plan from this Loop's saved task contract, role responsibilities, and run flow.",
        }

    @classmethod
    def _alignment_run_context_option(cls, run: dict, *, loop: dict) -> dict:
        run_id = str(run.get("id") or "").strip()
        loop_name = str(loop.get("name") or run.get("loop_id") or "")
        return {
            "option_id": cls._alignment_source_option_id("run", run_id),
            "action": "improve",
            "source_type": "run",
            "source_run_id": run_id,
            "source_loop_id": str(run.get("loop_id") or loop.get("id") or ""),
            "status": str(run.get("status") or ""),
            "artifact_paths": cls._alignment_run_artifact_paths(run),
            "label_zh": f"基于最近运行证据改进：{loop_name}",
            "label_en": f"Improve from latest run evidence: {loop_name}",
            "description_zh": "把最近一次运行的 Loop 裁决、证据覆盖、守门裁决和证据路径作为改进依据。",
            "description_en": "Use the latest run's Loop verdict, evidence coverage, GateKeeper verdict, and evidence refs as improvement input.",
        }

    @classmethod
    def _alignment_spec_file_context_option(cls, spec_path: Path) -> dict:
        return {
            "option_id": cls._alignment_source_option_id("spec_file", spec_path),
            "action": "start_from_spec",
            "source_type": "spec_file",
            "spec_path": str(spec_path),
            "label_zh": f"从已有任务契约开始：{spec_path.name}",
            "label_en": f"Start from existing spec: {spec_path.name}",
            "description_zh": "把这份任务契约作为线索，但仍通过对话补齐角色责任、运行流程和证据裁决。",
            "description_en": "Use this task contract as context while the chat still fills role responsibilities, run flow, and verdict evidence.",
        }

    @staticmethod
    def _alignment_workdir_spec_candidates(state_dir: Path) -> list[Path]:
        candidates: list[Path] = []
        root_spec = state_dir / "spec.md"
        if root_spec.is_file():
            candidates.append(root_spec)
        loops_dir = state_dir / "loops"
        if loops_dir.is_dir():
            candidates.extend(path for path in sorted(loops_dir.glob("*/spec.md")) if path.is_file())
        return candidates[:20]

    @staticmethod
    def _bounded_alignment_file_text(path: Path, *, limit: int = 16000) -> str:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeError:
            return "Source file could not be read as UTF-8 text."
        except OSError as exc:
            return f"Source file could not be read: {exc}"
        text = redact_sensitive_text(text)
        if len(text) <= limit:
            return text
        return text[:limit] + "\n\n[Loopora truncated this source context for prompt size.]"

    @staticmethod
    def _alignment_transcript_source_summary(session: dict) -> list[dict]:
        entries = [entry for entry in (session.get("transcript") or []) if isinstance(entry, dict)]
        summary: list[dict] = []
        for entry in entries[-8:]:
            content = redact_sensitive_text(str(entry.get("content", "") or "").strip())
            if not content:
                continue
            summary.append(
                {
                    "role": str(entry.get("role") or ""),
                    "content": content[:600],
                    "created_at": entry.get("created_at", ""),
                }
            )
        return summary

    def _resolve_alignment_source_option(self, workdir: Path, source_option_id: str) -> dict:
        option_id = str(source_option_id or "").strip()
        if not option_id or option_id == "regenerate":
            return {}
        context = self.get_alignment_workdir_context(workdir)
        option = next((item for item in context["options"] if item.get("option_id") == option_id), None)
        if not option:
            raise LooporaError("selected workdir context is no longer available")
        if option.get("action") == "continue_session":
            raise LooporaConflictError("continue_session options must restore the existing session instead of creating a new one")
        source_type = str(option.get("source_type") or "")
        if source_type == "bundle":
            return self._source_seed_from_bundle_option(option)
        if source_type == "run":
            return self._source_seed_from_run_option(option)
        if source_type == "loop":
            return self._source_seed_from_loop_option(option)
        if source_type in {"alignment_session", "alignment_session_file"}:
            return self._source_seed_from_alignment_session_option(option)
        if source_type == "spec_file":
            return self._source_seed_from_spec_file_option(option)
        raise LooporaError(f"unsupported workdir context source: {source_type}")

    def _source_seed_from_bundle_option(self, option: dict) -> dict:
        bundle_id = str(option.get("source_bundle_id") or "").strip()
        source_bundle = self.export_bundle(bundle_id)
        source = {
            "mode": "improvement",
            "source_type": "bundle",
            "source_bundle_id": bundle_id,
            "source_loop_id": str(option.get("source_loop_id") or source_bundle.get("loop_id") or ""),
            "source_run_id": "",
            "source_completion_mode": str(source_bundle.get("loop", {}).get("completion_mode", "") or ""),
            "reason": "improve_from_workdir_context",
            "run_status": "",
            "evidence_summary": [],
            "task_verdict": {},
            "gatekeeper_verdict": {},
        }
        return self._alignment_source_seed_payload(source, seed_bundle=self._revision_seed_bundle(source_bundle), linked_bundle_id=bundle_id)

    def _source_seed_from_run_option(self, option: dict) -> dict:
        run_id = str(option.get("source_run_id") or "").strip()
        run = self.get_run(run_id)
        loop = self.get_loop(run["loop_id"])
        source_bundle_id = str((loop.get("bundle") or {}).get("id") or "").strip()
        if source_bundle_id:
            source_bundle = self.export_bundle(source_bundle_id)
        else:
            source_bundle = self.derive_bundle_from_loop(
                run["loop_id"],
                name=str(loop.get("name") or "Run improvement base"),
                description="Derived as the improvement base for a run selected from workdir context.",
                collaboration_summary="Improvement base derived from the current loop.",
            )
        source = {
            "mode": "improvement",
            "source_type": "run",
            "source_bundle_id": source_bundle_id,
            "source_loop_id": str(run.get("loop_id") or ""),
            "source_run_id": run_id,
            "source_completion_mode": str(source_bundle.get("loop", {}).get("completion_mode", "") or ""),
            "reason": "improve_from_workdir_run_evidence",
            "run_status": str(run.get("status") or ""),
            "artifact_paths": self._alignment_run_artifact_paths(run),
            "judgment_contract": self._alignment_run_judgment_contract(run),
            "coverage_summary": self._alignment_run_coverage_summary(run),
            "evidence_summary": self._alignment_run_evidence_summary(run),
            "task_verdict": run.get("task_verdict") or {},
            "gatekeeper_verdict": run.get("last_verdict_json") or {},
        }
        return self._alignment_source_seed_payload(
            source,
            seed_bundle=self._revision_seed_bundle(source_bundle),
            linked_bundle_id=source_bundle_id,
            linked_loop_id=str(run.get("loop_id") or ""),
            linked_run_id=run_id,
        )

    def _source_seed_from_loop_option(self, option: dict) -> dict:
        loop_id = str(option.get("source_loop_id") or "").strip()
        loop = self.get_loop(loop_id)
        source_bundle = self.derive_bundle_from_loop(
            loop_id,
            name=str(loop.get("name") or "Loop improvement base"),
            description="Derived as the improvement base for a Loop selected from workdir context.",
            collaboration_summary="Improvement base derived from the current loop.",
        )
        source = {
            "mode": "improvement",
            "source_type": "loop",
            "source_bundle_id": "",
            "source_loop_id": loop_id,
            "source_run_id": "",
            "source_completion_mode": str(source_bundle.get("loop", {}).get("completion_mode", "") or ""),
            "reason": "improve_from_workdir_loop",
            "source_loop_name": str(loop.get("name") or ""),
            "run_status": "",
            "evidence_summary": [],
            "task_verdict": {},
            "gatekeeper_verdict": {},
        }
        return self._alignment_source_seed_payload(source, seed_bundle=self._revision_seed_bundle(source_bundle), linked_loop_id=loop_id)

    def _source_seed_from_alignment_session_option(self, option: dict) -> dict:
        source_session_id = str(option.get("source_alignment_session_id") or "").strip()
        bundle_path = Path(str(option.get("bundle_path") or ""))
        try:
            source_session = self.get_alignment_session(source_session_id)
        except LooporaError:
            source_session = {}
        source_bundle = load_bundle_text(read_bundle_file_text(bundle_path))
        source = {
            "mode": "improvement",
            "source_type": str(option.get("source_type") or "alignment_session"),
            "source_alignment_session_id": source_session_id,
            "source_bundle_id": "",
            "source_loop_id": "",
            "source_run_id": "",
            "source_completion_mode": str(source_bundle.get("loop", {}).get("completion_mode", "") or ""),
            "reason": "improve_from_workdir_alignment_session",
            "source_status": str(source_session.get("status") or option.get("status") or ""),
            "source_bundle_path": str(bundle_path),
            "transcript_summary": self._alignment_transcript_source_summary(source_session) if source_session else [],
            "run_status": "",
            "evidence_summary": [],
            "task_verdict": {},
            "gatekeeper_verdict": {},
        }
        return self._alignment_source_seed_payload(source, seed_bundle=self._revision_seed_bundle(source_bundle))

    def _source_seed_from_spec_file_option(self, option: dict) -> dict:
        spec_path = Path(str(option.get("spec_path") or ""))
        source = {
            "mode": "selected_source",
            "source_type": "spec_file",
            "spec_path": str(spec_path),
            "reason": "start_from_workdir_spec",
            "spec_markdown": self._bounded_alignment_file_text(spec_path),
            "artifact_paths": {"spec": str(spec_path)},
        }
        return self._alignment_source_seed_payload(source)

    @staticmethod
    def _redact_alignment_source_value(value: object, *, key: str = "") -> object:
        if isinstance(value, list):
            return [ServiceAlignmentMixin._redact_alignment_source_value(item) for item in value]
        if isinstance(value, dict):
            return {
                str(child_key): ServiceAlignmentMixin._redact_alignment_source_value(item, key=str(child_key))
                for child_key, item in value.items()
            }
        return redact_sensitive_value(key, value)

    @staticmethod
    def _alignment_source_seed_payload(
        source: dict,
        *,
        seed_bundle: dict | None = None,
        linked_bundle_id: str = "",
        linked_loop_id: str = "",
        linked_run_id: str = "",
    ) -> dict:
        redacted_source = ServiceAlignmentMixin._redact_alignment_source_value(source)
        working_agreement = {
            "mode": str(source.get("mode") or "selected_source"),
            "source": redacted_source,
        }
        if isinstance(seed_bundle, dict) and seed_bundle:
            working_agreement["seed_bundle_metadata"] = ServiceAlignmentMixin._redact_alignment_source_value(seed_bundle.get("metadata", {}))
        return {
            "working_agreement": working_agreement,
            "seed_bundle": seed_bundle or {},
            "linked_bundle_id": linked_bundle_id,
            "linked_loop_id": linked_loop_id,
            "linked_run_id": linked_run_id,
            "event": {
                "source_type": redacted_source.get("source_type", "") if isinstance(redacted_source, dict) else "",
                "source_bundle_id": redacted_source.get("source_bundle_id", "") if isinstance(redacted_source, dict) else "",
                "source_loop_id": redacted_source.get("source_loop_id", "") if isinstance(redacted_source, dict) else "",
                "source_run_id": redacted_source.get("source_run_id", "") if isinstance(redacted_source, dict) else "",
                "source_alignment_session_id": redacted_source.get("source_alignment_session_id", "") if isinstance(redacted_source, dict) else "",
                "spec_path": redacted_source.get("spec_path", "") if isinstance(redacted_source, dict) else "",
                "reason": redacted_source.get("reason", "") if isinstance(redacted_source, dict) else "",
            },
        }

    @staticmethod
    def _alignment_project_boundary(root: Path) -> Path | None:
        project_markers = (".git", "pyproject.toml", "package.json", "Cargo.toml", "go.mod")
        for candidate in (root, *root.parents):
            if any((candidate / marker).exists() for marker in project_markers):
                return candidate
        return None

    @staticmethod
    def _alignment_applicable_agents_paths(root: Path) -> list[Path]:
        boundary = ServiceAlignmentMixin._alignment_project_boundary(root)
        search_dirs = [root]
        if boundary is not None:
            for parent in root.parents:
                search_dirs.append(parent)
                if parent == boundary:
                    break

        agents_paths: list[Path] = []
        seen: set[Path] = set()
        for directory in search_dirs:
            agents_path = directory / "AGENTS.md"
            if agents_path in seen or not agents_path.is_file():
                continue
            seen.add(agents_path)
            agents_paths.append(agents_path)
        return agents_paths

    @staticmethod
    def _alignment_workdir_snapshot(workdir: Path) -> str:
        try:
            root = workdir.expanduser().resolve()
            if not root.exists() or not root.is_dir():
                return f"Workdir is not an accessible directory: {root}"
            entries = sorted(root.iterdir(), key=lambda item: (item.is_file(), item.name.lower()))
        except OSError as exc:
            return f"Workdir could not be inspected: {exc}"
        visible = [item for item in entries if item.name not in {".DS_Store", APP_STATE_DIRNAME}][:40]
        workdir_appears_empty = not visible
        marker_names = {
            "README.md",
            "README.zh-CN.md",
            "package.json",
            "pyproject.toml",
            "Cargo.toml",
            "go.mod",
            "pnpm-lock.yaml",
            "uv.lock",
            "requirements.txt",
            "AGENTS.md",
        }
        markers = [item.name for item in visible if item.name in marker_names]
        design_dir = root / "design"
        design_readme = design_dir / "README.md"
        tests_dir = root / "tests"
        agents_file = root / "AGENTS.md"
        applicable_agents = ServiceAlignmentMixin._alignment_applicable_agents_paths(root)
        lines = [f"Top-level entries ({len(visible)} shown):"]
        if workdir_appears_empty:
            lines.append("Workdir appears empty. Treat technology choices as assumptions until the run verifies them.")
        for item in visible:
            suffix = "/" if item.is_dir() else ""
            lines.append(f"- {item.name}{suffix}")
        if markers:
            lines.append("Detected markers: " + ", ".join(markers))
        lines.append(f"AGENTS.md exists: {'yes' if agents_file.is_file() else 'no'}")
        lines.append(f"Applicable AGENTS.md exists: {'yes' if applicable_agents else 'no'}")
        if applicable_agents:
            agents_relpaths = [os.path.relpath(path, root) for path in applicable_agents]
            lines.append("Applicable AGENTS.md paths: " + ", ".join(agents_relpaths))
        lines.append(f"design/ exists: {'yes' if design_dir.is_dir() else 'no'}")
        lines.append(f"design/README.md exists: {'yes' if design_readme.is_file() else 'no'}")
        lines.append(f"tests/ exists: {'yes' if tests_dir.is_dir() else 'no'}")
        return "\n".join(lines)

    @staticmethod
    def _alignment_improvement_context_text(session: dict) -> str:
        agreement = session.get("working_agreement") if isinstance(session.get("working_agreement"), dict) else {}
        mode = str(agreement.get("mode") or "")
        if mode not in {"improvement", "selected_source"}:
            return ""
        source = agreement.get("source") if isinstance(agreement.get("source"), dict) else {}
        artifact_paths_text = redact_sensitive_text(json.dumps(source.get("artifact_paths") or {}, ensure_ascii=False, indent=2))
        transcript_summary_text = redact_sensitive_text(json.dumps(source.get("transcript_summary") or [], ensure_ascii=False, indent=2))
        spec_markdown = str(source.get("spec_markdown") or "")
        guidance = load_alignment_guidance_assets()
        selected_spec_markdown_block = ""
        if spec_markdown:
            selected_spec_markdown_block = ServiceAlignmentMixin._render_alignment_template(
                guidance.selected_spec_markdown_template,
                {"spec_markdown": spec_markdown},
            )
        source_values = {
            "source_type": source.get("source_type", ""),
            "source_alignment_session_id": source.get("source_alignment_session_id", ""),
            "source_bundle_id": source.get("source_bundle_id", ""),
            "source_loop_id": source.get("source_loop_id", ""),
            "source_run_id": source.get("source_run_id", ""),
            "spec_path": source.get("spec_path", ""),
            "reason": source.get("reason", ""),
            "artifact_paths_json": artifact_paths_text,
            "transcript_summary_json": transcript_summary_text,
            "selected_spec_markdown_block": selected_spec_markdown_block,
        }
        selected_context = ServiceAlignmentMixin._render_alignment_template(guidance.selected_source_context_template, source_values)
        if mode == "selected_source":
            return selected_context
        evidence_items = source.get("evidence_summary") if isinstance(source.get("evidence_summary"), list) else []
        evidence_text = redact_sensitive_text(json.dumps(evidence_items[:8], ensure_ascii=False, indent=2))
        coverage_text = redact_sensitive_text(json.dumps(source.get("coverage_summary") or {}, ensure_ascii=False, indent=2))
        judgment_contract_text = redact_sensitive_text(json.dumps(source.get("judgment_contract") or {}, ensure_ascii=False, indent=2))
        task_verdict_text = redact_sensitive_text(json.dumps(source.get("task_verdict") or {}, ensure_ascii=False, indent=2))
        verdict_text = redact_sensitive_text(json.dumps(source.get("gatekeeper_verdict") or {}, ensure_ascii=False, indent=2))
        improvement_context = ServiceAlignmentMixin._render_alignment_template(
            guidance.bundle_improvement_context_template,
            {
                **source_values,
                "run_status": source.get("run_status", ""),
                "source_completion_mode": source.get("source_completion_mode", ""),
                "judgment_contract_json": judgment_contract_text,
                "coverage_summary_json": coverage_text,
                "task_verdict_json": task_verdict_text,
                "evidence_summary_json": evidence_text,
                "gatekeeper_verdict_json": verdict_text,
            },
        )
        return selected_context + "\n\n" + improvement_context

    @staticmethod
    def _alignment_manifest_payload(session: dict) -> dict:
        transcript = [item for item in (session.get("transcript") or []) if isinstance(item, dict)]
        first_user = ""
        last_message = ""
        for entry in transcript:
            content = redact_sensitive_text(str(entry.get("content", "") or "").strip())
            if not content:
                continue
            if not first_user and entry.get("role") == "user":
                first_user = content
            last_message = content
        root = ServiceAlignmentMixin._alignment_session_root(session)
        return {
            "id": session.get("id", ""),
            "status": session.get("status", ""),
            "executor_kind": session.get("executor_kind", "codex"),
            "executor_mode": session.get("executor_mode", "preset"),
            "model": session.get("model", ""),
            "reasoning_effort": session.get("reasoning_effort", ""),
            "workdir": session.get("workdir", ""),
            "bundle_path": session.get("bundle_path", ""),
            "artifact_dir": str(root),
            "alignment_stage": session.get("alignment_stage", "clarifying"),
            "linked_bundle_id": session.get("linked_bundle_id", ""),
            "linked_loop_id": session.get("linked_loop_id", ""),
            "linked_run_id": session.get("linked_run_id", ""),
            "repair_attempts": ServiceAlignmentMixin._alignment_repair_attempts(session),
            "created_at": session.get("created_at", ""),
            "updated_at": session.get("updated_at", ""),
            "finished_at": session.get("finished_at", ""),
            "error_message": redact_sensitive_text(str(session.get("error_message", "") or "")),
            "message_count": len(transcript),
            "title": first_user[:96] if first_user else session.get("id", ""),
            "last_message": last_message[:160],
            "paths": {
                "transcript": "conversation/transcript.jsonl",
                "working_agreement": "agreement/current.json",
                "bundle": "artifacts/bundle.yml",
                "validation": "artifacts/validation.json",
                "events": "events/events.jsonl",
                "invocations": "invocations",
            },
        }

    @staticmethod
    def _write_alignment_manifest(session: dict) -> None:
        paths = ServiceAlignmentMixin._alignment_artifact_paths(session)
        ServiceAlignmentMixin._ensure_alignment_artifact_dirs(paths["root"])
        paths["manifest"].write_text(
            json.dumps(ServiceAlignmentMixin._alignment_manifest_payload(session), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _write_alignment_transcript_log(session: dict) -> None:
        paths = ServiceAlignmentMixin._alignment_artifact_paths(session)
        ServiceAlignmentMixin._ensure_alignment_artifact_dirs(paths["root"])
        transcript = list(session.get("transcript") or [])
        with paths["transcript"].open("w", encoding="utf-8") as handle:
            for entry in transcript:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        paths["agreement"].write_text(
            json.dumps(session.get("working_agreement") or {}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        ServiceAlignmentMixin._write_alignment_manifest(session)

    @staticmethod
    def _write_alignment_validation_log(session: dict, validation: dict) -> None:
        paths = ServiceAlignmentMixin._alignment_artifact_paths(session)
        ServiceAlignmentMixin._ensure_alignment_artifact_dirs(paths["root"])
        payload = json.dumps(validation, ensure_ascii=False, indent=2) + "\n"
        paths["validation"].write_text(payload, encoding="utf-8")
        attempt = ServiceAlignmentMixin._alignment_repair_attempts(session)
        invocation_dir = ServiceAlignmentMixin._alignment_latest_invocation_dir(paths["root"]) or ServiceAlignmentMixin._alignment_invocation_dir(
            paths["root"],
            attempt,
            repair=attempt > 0,
        )
        invocation_dir.mkdir(parents=True, exist_ok=True)
        (invocation_dir / "validation.json").write_text(payload, encoding="utf-8")
        ServiceAlignmentMixin._write_alignment_manifest(session)

    @staticmethod
    def _render_alignment_template(template: str, values: dict[str, object]) -> str:
        def replace(match: re.Match[str]) -> str:
            key = match.group(1)
            if key not in values:
                raise LooporaError(f"alignment prompt template references unknown value: {key}")
            return str(values[key])

        return ALIGNMENT_TEMPLATE_PLACEHOLDER_RE.sub(replace, template).strip()

    @staticmethod
    def _alignment_markdown_h2_sections(markdown_text: str) -> dict[str, str]:
        sections: dict[str, list[str]] = {}
        current_heading = ""
        for line in str(markdown_text or "").splitlines():
            if line.startswith("## "):
                current_heading = line.removeprefix("## ").strip()
                sections.setdefault(current_heading, [])
                continue
            if current_heading:
                sections[current_heading].append(line)
        return {heading: "\n".join(lines).strip() for heading, lines in sections.items()}

    @staticmethod
    def _alignment_stage_policy_text(session: dict, *, mode: str, compiler_gates: str) -> str:
        stage = str(session.get("alignment_stage", "") or "clarifying")
        sections = ServiceAlignmentMixin._alignment_markdown_h2_sections(compiler_gates)
        if mode == "repair":
            section_name = "Repair"
        elif stage == "agreement_ready":
            section_name = "Waiting For Confirmation"
        elif stage == "ready_review":
            section_name = "Ready Review"
        elif stage in ALIGNMENT_CONFIRMED_STAGES:
            section_name = "Confirmed Agreement"
        else:
            section_name = "Clarifying"
        try:
            common = sections["Common"]
            stage_policy = sections[section_name]
        except KeyError as exc:
            raise LooporaError(f"Loop compiler policy asset is missing section: {exc.args[0]}") from exc
        return "\n\n".join(part for part in (common, stage_policy) if part).strip()

    def _build_alignment_prompt(
        self,
        session: dict,
        *,
        mode: str,
        validation_error: str = "",
        invalid_yaml: str = "",
    ) -> str:
        guidance = load_alignment_guidance_assets()
        compiler_policy = guidance.compiler_policy
        product_primer = guidance.product_primer
        alignment_playbook = guidance.alignment_playbook
        quality_rubric = guidance.quality_rubric
        bundle_contract = guidance.bundle_contract
        examples = guidance.examples
        feedback_improvement = guidance.feedback_improvement
        current_bundle = ""
        bundle_path = Path(session["bundle_path"])
        if bundle_path.exists():
            try:
                current_bundle = redact_sensitive_text(read_bundle_file_text(bundle_path))
            except (BundleError, OSError) as exc:
                current_bundle = f"Current bundle file could not be read: {exc}"
        transcript_text = redact_sensitive_text(json.dumps(session.get("transcript") or [], ensure_ascii=False, indent=2))
        working_agreement_text = redact_sensitive_text(json.dumps(session.get("working_agreement") or {}, ensure_ascii=False, indent=2))
        alignment_stage = str(session.get("alignment_stage", "") or "clarifying")
        user_language_hint = self._alignment_user_language_hint(session)
        workdir_snapshot = self._alignment_workdir_snapshot(Path(session["workdir"]))
        improvement_context = self._alignment_improvement_context_text(session)
        stage_policy = self._alignment_stage_policy_text(session, mode=mode, compiler_gates=guidance.compiler_gates)
        session_context = ""
        if mode == "repair":
            session_context = self._render_alignment_template(
                guidance.repair_input_template,
                {
                    "validation_error": validation_error,
                    "invalid_yaml": invalid_yaml,
                },
            )
        elif current_bundle:
            session_context = self._render_alignment_template(
                guidance.current_bundle_template,
                {
                    "current_bundle": current_bundle,
                },
            )

        return self._render_alignment_template(
            guidance.system_prompt_template,
            {
                "bundle_path": session["bundle_path"],
                "workdir": session["workdir"],
                "executor_kind": session.get("executor_kind", "codex"),
                "executor_mode": session.get("executor_mode", "preset"),
                "command_cli": session.get("command_cli", ""),
                "command_args_text": redact_sensitive_text(str(session.get("command_args_text", "") or "")),
                "model": session.get("model", ""),
                "reasoning_effort": session.get("reasoning_effort", ""),
                "workdir_snapshot": workdir_snapshot,
                "alignment_stage": alignment_stage,
                "working_agreement_json": working_agreement_text,
                "improvement_context": improvement_context,
                "stage_policy": stage_policy,
                "product_primer": product_primer,
                "compiler_policy": compiler_policy,
                "alignment_playbook": alignment_playbook,
                "quality_rubric": quality_rubric,
                "bundle_contract": bundle_contract,
                "examples": examples,
                "feedback_improvement": feedback_improvement,
                "session_transcript_json": transcript_text,
                "session_context": session_context,
                "user_language_hint": user_language_hint,
            },
        )

    def _fail_alignment_session(self, session_id: str, error: str, *, event_type: str = "alignment_failed") -> None:
        self.repository.update_alignment_session(
            session_id,
            status="failed",
            finished_at=utc_now(),
            clear_active_child_pid=True,
            error_message=error,
        )
        self.repository.append_alignment_event(
            session_id,
            event_type,
            {"status": "failed", "error": error},
        )

    def _normalize_alignment_executor_settings(
        self,
        request: AlignmentExecutorSettingsRequest,
    ) -> dict:
        try:
            kind = normalize_executor_kind(request.executor_kind)
            profile = executor_profile(kind)
            mode = "command" if profile.command_only else normalize_executor_mode(request.executor_mode)
            if mode == "preset":
                return {
                    "executor_kind": kind,
                    "executor_mode": mode,
                    "command_cli": "",
                    "command_args_text": "",
                    "model": str(request.model or profile.default_model or "").strip(),
                    "reasoning_effort": normalize_reasoning_setting(request.reasoning_effort, executor_kind=kind),
                }
            normalized_cli = str(request.command_cli or profile.cli_name or "").strip()
            validate_command_args_text(request.command_args_text, executor_kind=kind)
            return {
                "executor_kind": kind,
                "executor_mode": mode,
                "command_cli": normalized_cli,
                "command_args_text": str(request.command_args_text or ""),
                "model": str(request.model or "").strip(),
                "reasoning_effort": str(request.reasoning_effort or "").strip(),
            }
        except ValueError as exc:
            raise LooporaError(str(exc)) from exc

    @staticmethod
    def _alignment_session_dir(workdir: Path, session_id: str) -> Path:
        return state_dir_for_workdir(workdir) / "alignment_sessions" / session_id

    @staticmethod
    def _alignment_artifact_root_from_bundle_path(bundle_path: Path) -> Path:
        bundle_path = Path(bundle_path)
        return bundle_path.parent.parent if bundle_path.parent.name == "artifacts" else bundle_path.parent

    @classmethod
    def _alignment_session_root(cls, session: dict) -> Path:
        return cls._alignment_artifact_root_from_bundle_path(Path(session["bundle_path"]))

    @staticmethod
    def _alignment_artifact_paths_from_root(root: Path) -> dict[str, Path]:
        return {
            "root": root,
            "manifest": root / "manifest.json",
            "conversation_dir": root / "conversation",
            "transcript": root / "conversation" / "transcript.jsonl",
            "agreement_dir": root / "agreement",
            "agreement": root / "agreement" / "current.json",
            "artifacts_dir": root / "artifacts",
            "bundle": root / "artifacts" / "bundle.yml",
            "validation": root / "artifacts" / "validation.json",
            "events_dir": root / "events",
            "events": root / "events" / "events.jsonl",
            "invocations_dir": root / "invocations",
            "legacy_dir": root / "legacy",
        }

    @classmethod
    def _alignment_artifact_paths(cls, session: dict) -> dict[str, Path]:
        return cls._alignment_artifact_paths_from_root(cls._alignment_session_root(session))

    @classmethod
    def _ensure_alignment_artifact_dirs(cls, root: Path) -> None:
        paths = cls._alignment_artifact_paths_from_root(root)
        for key in ("conversation_dir", "agreement_dir", "artifacts_dir", "events_dir", "invocations_dir"):
            paths[key].mkdir(parents=True, exist_ok=True)

    def _ensure_alignment_session_layout(self, session: dict) -> dict:
        bundle_path = Path(session["bundle_path"])
        root = self._alignment_artifact_root_from_bundle_path(bundle_path)
        paths = self._alignment_artifact_paths_from_root(root)
        self._ensure_alignment_artifact_dirs(root)
        if bundle_path == paths["bundle"]:
            self._write_alignment_manifest(session)
            return session

        legacy_dir = paths["legacy_dir"]
        legacy_dir.mkdir(parents=True, exist_ok=True)
        self._copy_alignment_legacy_file_aliases(root, paths)
        self._copy_alignment_legacy_prompts(root)
        self._copy_alignment_legacy_outputs(root, paths["bundle"])
        self._copy_alignment_legacy_schema(root)
        self._copy_alignment_legacy_validations(root)
        self._move_alignment_legacy_remainders(session, root, legacy_dir)
        updated = self.repository.update_alignment_session(session["id"], bundle_path=str(paths["bundle"]))
        self._write_alignment_manifest(updated)
        return updated

    @staticmethod
    def _alignment_repair_attempts(session: dict | None, *, invalid_default: int = 0) -> int:
        if not session or session.get("repair_attempts") is None:
            return 0
        return structured_non_negative_int(session.get("repair_attempts"), default=invalid_default)

    @staticmethod
    def _alignment_output_debug_payload(output: dict, bundle_path: Path) -> dict:
        payload = dict(output) if isinstance(output, dict) else {}
        bundle_yaml = str(payload.pop("bundle_yaml", "") or "")
        if bundle_yaml:
            payload["bundle_written"] = True
            payload["bundle_path"] = str(bundle_path)
            payload["bundle_sha256"] = sha256(bundle_yaml.encode("utf-8")).hexdigest()
            payload["bundle_bytes"] = len(bundle_yaml.encode("utf-8"))
        else:
            payload["bundle_written"] = False
            payload.setdefault("bundle_path", str(bundle_path))
            payload["bundle_sha256"] = ""
            payload["bundle_bytes"] = 0
        redacted_payload = ServiceAlignmentMixin._redact_alignment_source_value(payload)
        return redacted_payload if isinstance(redacted_payload, dict) else {}

    @classmethod
    def _sanitize_alignment_event_payload(cls, event_type: str, payload: dict, *, invocation_id: str = "") -> dict:
        sanitized = redact_alignment_event_payload(event_type, payload)
        if invocation_id:
            sanitized.setdefault("invocation_id", invocation_id)
        return sanitized

    @classmethod
    def _finalize_alignment_invocation_files(cls, invocation_dir: Path, output: dict, bundle_path: Path) -> None:
        schema_path = invocation_dir / "alignment_schema.json"
        if schema_path.exists() and not (invocation_dir / "schema.json").exists():
            schema_path.replace(invocation_dir / "schema.json")
        elif schema_path.exists():
            schema_path.unlink()
        (invocation_dir / "output.json").write_text(
            json.dumps(cls._alignment_output_debug_payload(output, bundle_path), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _alignment_thread_key(session_id: str) -> str:
        return f"alignment:{session_id}"

    @staticmethod
    def _assert_alignment_bundle_workdir(bundle: dict, *, expected_workdir: Path) -> None:
        actual = Path(str(bundle["loop"]["workdir"])).expanduser().resolve()
        expected = expected_workdir.expanduser().resolve()
        if actual != expected:
            raise LooporaError(f"bundle loop.workdir must be {expected}, got {actual}")

    @staticmethod
    def _decorate_alignment_session(session: dict) -> dict:
        payload = dict(session)
        payload["artifact_dir"] = str(ServiceAlignmentMixin._alignment_session_root(payload))
        payload["is_active"] = payload.get("status") in ALIGNMENT_ACTIVE_STATUSES
        payload["is_ready"] = payload.get("status") == "ready"
        payload["alignment_stage"] = str(payload.get("alignment_stage", "") or "clarifying")
        working_agreement = payload.get("working_agreement")
        if not isinstance(working_agreement, dict):
            working_agreement = {}
        payload["working_agreement"] = working_agreement
        executor_session_ref = payload.get("executor_session_ref")
        if not isinstance(executor_session_ref, dict):
            executor_session_ref = {}
        payload["executor_session_ref"] = executor_session_ref
        payload["native_resume_available"] = bool(executor_session_ref.get("session_id"))
        return payload

    @classmethod
    def _alignment_session_summary(cls, session: dict) -> dict:
        decorated = cls._decorate_alignment_session(session)
        transcript = decorated.get("transcript") or []
        first_user = ""
        last_message = ""
        for entry in transcript:
            if not isinstance(entry, dict):
                continue
            content = redact_sensitive_text(str(entry.get("content", "") or "").strip())
            if not content:
                continue
            if not first_user and entry.get("role") == "user":
                first_user = content
            last_message = content
        return {
            "id": decorated["id"],
            "status": decorated.get("status", ""),
            "workdir": decorated.get("workdir", ""),
            "executor_kind": decorated.get("executor_kind", "codex"),
            "executor_mode": decorated.get("executor_mode", "preset"),
            "alignment_stage": decorated.get("alignment_stage", "clarifying"),
            "updated_at": decorated.get("updated_at", ""),
            "created_at": decorated.get("created_at", ""),
            "linked_bundle_id": decorated.get("linked_bundle_id", ""),
            "linked_loop_id": decorated.get("linked_loop_id", ""),
            "linked_run_id": decorated.get("linked_run_id", ""),
            "message_count": len(transcript),
            "title": first_user[:96] if first_user else decorated["id"],
            "last_message": last_message[:160],
            "native_resume_available": decorated.get("native_resume_available", False),
        }
