from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loopora.agent_adapters import (
    agent_adapter_status,
    agent_loop_command,
    list_agent_adapter_statuses,
    install_agent_adapter,
    normalize_agent_adapter_kind,
    read_agent_binding,
    resolve_adapter_project_root,
    resolved_agent_context_id,
    uninstall_agent_adapter,
    write_agent_binding,
)
from loopora.alignment_semantics import text_mentions_loop_fit_contradiction
from loopora.bundles import BundleError, read_bundle_file_text
from loopora.evidence_coverage import summarize_evidence_coverage_projection
from loopora.run_takeaways import build_judgment_contract
from loopora.service_types import LooporaConflictError, LooporaError, LooporaNotFoundError, TERMINAL_RUN_STATUSES
from loopora.structured_numbers import structured_non_negative_int
from loopora.task_verdicts import normalize_task_verdict
from loopora.utils import read_json, utc_now, write_json


PASSING_TASK_VERDICT_STATUSES = frozenset({"passed", "passed_with_residual_risk"})


@dataclass(frozen=True)
class AgentBundleCandidateRequest:
    adapter: str
    workdir: Path | str
    message: str = ""
    bundle_yaml: str = ""
    bundle_file: Path | str | None = None
    context_id: str = ""
    entry_source: str = ""


@dataclass(frozen=True)
class _AgentLoopStartContext:
    adapter: str
    root: Path
    session_id: str
    context_id: str
    entry_source: str
    binding_extra: dict[str, Any] | None = None


def _normalized_candidate_yaml(raw_yaml: str) -> str:
    return raw_yaml.rstrip() + "\n" if raw_yaml.strip() else ""


def _candidate_yaml_provenance(candidate_text: str) -> dict[str, Any]:
    if not candidate_text:
        return {"candidate_sha256": "", "candidate_bytes": 0}
    data = candidate_text.encode("utf-8")
    return {"candidate_sha256": hashlib.sha256(data).hexdigest(), "candidate_bytes": len(data)}


def _ready_candidate_yaml_provenance(session: dict) -> dict[str, Any]:
    empty = {"ready_candidate_sha256": "", "ready_candidate_bytes": 0}
    if str(session.get("status") or "") != "ready":
        return empty
    try:
        candidate_text = _normalized_candidate_yaml(read_bundle_file_text(Path(session.get("bundle_path", ""))))
    except (BundleError, OSError, ValueError):
        return empty
    if not candidate_text:
        return empty
    data = candidate_text.encode("utf-8")
    return {"ready_candidate_sha256": hashlib.sha256(data).hexdigest(), "ready_candidate_bytes": len(data)}


def _ready_candidate_yaml_provenance_from_validation(session: dict) -> dict[str, Any]:
    validation = session.get("validation") if isinstance(session, dict) else {}
    if not isinstance(validation, dict):
        return {}
    digest = str(validation.get("bundle_sha256") or "").strip()
    try:
        byte_count = int(validation.get("bundle_bytes") or 0)
    except (TypeError, ValueError):
        byte_count = 0
    if not digest or byte_count <= 0:
        return {}
    return {"ready_candidate_sha256": digest, "ready_candidate_bytes": byte_count}


def _first_review_items(value: object, *, limit: int = 2) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()][:limit]


def agent_entry_loop_command(
    adapter: str,
    workdir: Path | str,
    entry_source: str = "",
    *,
    context_id: str = "",
) -> str:
    return agent_loop_command(adapter, workdir, entry_source=entry_source, context_id=context_id)


def _agent_entry_loop_projection_messages(next_loop_action: str) -> dict[str, str]:
    if next_loop_action == "start_next_run_for_unproven_verdict":
        return {
            "message_zh": (
                "上一轮已经到达终态，但 Loop 裁决仍未证明任务通过；回到同一个 Agent 执行 /loopora-loop "
                "会基于这份已审查 Loop 开启下一轮，继续补齐证据缺口。"
            ),
            "message_en": (
                "The previous run reached a terminal lifecycle state, but the task verdict is still not proven; "
                "run /loopora-loop in the same Agent to start the next run from this reviewed Loop and keep closing evidence gaps."
            ),
        }
    return {
        "message_zh": (
            "这个 Loop 来自当前 Coding Agent 的 /loopora-gen；继续运行必须回到同一个 Agent 执行 /loopora-loop，"
            "避免 Web 悄悄切到后台 headless worker。"
        ),
        "message_en": (
            "This Loop came from the current Coding Agent via /loopora-gen; continue it from the same Agent "
            "with /loopora-loop so Web does not silently switch to a headless worker."
        ),
    }


class ServiceAgentAdapterMixin:
    def list_agent_adapters(self, *, workdir: Path | str | None = None) -> list[dict[str, Any]]:
        return list_agent_adapter_statuses(workdir or Path.cwd())

    def get_agent_adapter(self, adapter: str, *, workdir: Path | str | None = None) -> dict[str, Any]:
        return agent_adapter_status(adapter, workdir or Path.cwd())

    def install_agent_adapter(self, adapter: str, *, workdir: Path | str | None = None) -> dict[str, Any]:
        return install_agent_adapter(adapter, workdir or Path.cwd())

    def uninstall_agent_adapter(self, adapter: str, *, workdir: Path | str | None = None) -> dict[str, Any]:
        return uninstall_agent_adapter(adapter, workdir or Path.cwd())

    def create_agent_bundle_candidate(self, request: AgentBundleCandidateRequest) -> dict[str, Any]:
        adapter = normalize_agent_adapter_kind(request.adapter)
        if adapter not in {"codex", "claude", "opencode"}:
            raise LooporaError(f"{adapter} adapter is not implemented yet")
        root = resolve_adapter_project_root(request.workdir)
        entry_source = str(request.entry_source or "").strip() or "direct_cli"
        raw_yaml = str(request.bundle_yaml or "")
        source_path = ""
        if not raw_yaml.strip() and request.bundle_file is not None:
            bundle_path = Path(request.bundle_file).expanduser().resolve()
            try:
                raw_yaml = read_bundle_file_text(bundle_path)
            except OSError as exc:
                raise LooporaError(str(exc)) from exc
            source_path = str(bundle_path)
        candidate_text = _normalized_candidate_yaml(raw_yaml)
        candidate_provenance = _candidate_yaml_provenance(candidate_text)
        task_message = str(request.message or "").strip()
        if not task_message:
            raise LooporaError("agent candidate requires --message task summary for traceability")
        loopora_fit_contradiction = text_mentions_loop_fit_contradiction(task_message)
        host_context_id = resolved_agent_context_id(adapter, context_id=request.context_id)

        session = self.create_alignment_session(
            workdir=root,
            message=task_message,
            start_immediately=False,
            executor_kind=adapter,
            executor_mode="preset",
            command_cli="",
            command_args_text="",
            model="",
            reasoning_effort="",
        )
        self.repository.append_alignment_event(
            session["id"],
            "agent_candidate_received",
            {
                "candidate_origin": "agent_entry",
                "adapter": adapter,
                "entry_source": entry_source,
                "host_context_id": host_context_id,
                "has_candidate_yaml": bool(candidate_text),
                "requires_web_alignment": not bool(candidate_text),
                "requires_candidate_repair": False,
                "loopora_fit_contradiction": loopora_fit_contradiction,
                "source_path": source_path,
                **candidate_provenance,
                "ready_candidate_sha256": "",
                "ready_candidate_bytes": 0,
            },
        )
        if candidate_text:
            candidate_path = Path(session["bundle_path"])
            candidate_path.parent.mkdir(parents=True, exist_ok=True)
            candidate_path.write_text(candidate_text, encoding="utf-8")
            preview = self.sync_alignment_bundle_from_file(session["id"])
            session = preview["session"]
        elif loopora_fit_contradiction:
            session = self._append_alignment_system_message(
                session["id"],
                zh=(
                    "Loopora 已把这次 /loopora-gen 打开为 Web review：宿主 Agent 没有提交候选方案文件，"
                    "而任务摘要已经说明这更像一次性处理、直接回答、不需要后续新证据，"
                    "或稳定 benchmark / proof harness 已足够裁决的工作，"
                    "所以这里不会伪装成可运行 Loop。若你仍想把范围改成可治理的长期 Loop，"
                    "请先补充为什么需要后续证据、handoff 或 GateKeeper 裁决。"
                ),
                en=(
                    "Loopora opened this /loopora-gen result as Web review because the host Agent did not submit "
                    "a candidate plan file, and the task summary says this is closer to a one-off fix, direct answer, "
                    "benchmark/test-harness-only path, or work where later rounds add no new evidence. This is not a runnable Loop yet. If you still "
                    "want to reshape it into a governed Loop, first explain what later evidence, handoffs, or "
                    "GateKeeper judgment would add."
                ),
            )
        else:
            session = self._append_alignment_system_message(
                session["id"],
                zh=(
                    "Loopora 已把这次 /loopora-gen 打开为 Web review：宿主 Agent 没有提交候选方案文件，"
                    "所以这里不会伪装成可运行 Loop。请继续确认或补充成功标准、伪完成风险、证据预期、"
                    "Loopora fit、执行策略、判断取舍、残余风险和本地治理责任，然后再生成可审查的 Loop 预览。"
                ),
                en=(
                    "Loopora opened this /loopora-gen result as Web review because the host Agent did not submit "
                    "a candidate plan file, so this is not a runnable Loop yet. Continue by confirming or filling "
                    "in the success criteria, fake-done risks, evidence expectations, Loopora fit, execution strategy, "
                    "judgment tradeoffs, residual-risk policy, and local governance responsibilities before "
                    "generating a reviewable Loop preview."
                ),
            )
        requires_candidate_repair = bool(candidate_text) and session["status"] != "ready"
        ready_candidate_provenance = _ready_candidate_yaml_provenance(session)
        if ready_candidate_provenance["ready_candidate_sha256"]:
            self.repository.append_alignment_event(
                session["id"],
                "agent_candidate_ready_content",
                {
                    "candidate_origin": "agent_entry",
                    "adapter": adapter,
                    "entry_source": entry_source,
                    "host_context_id": host_context_id,
                    "source_path": source_path,
                    **candidate_provenance,
                    **ready_candidate_provenance,
                },
            )
            session = self.get_alignment_session(session["id"])
        existing_binding = read_agent_binding(adapter, root, context_id=request.context_id)
        binding = write_agent_binding(
            adapter,
            root,
            {
                "alignment_session_id": session["id"],
                "alignment_status": session["status"],
                "bundle_path": session.get("bundle_path", ""),
                "candidate_origin": "agent_entry",
                "candidate_adapter": adapter,
                "candidate_entry_source": entry_source,
                "host_context_id": host_context_id,
                "requires_web_alignment": not bool(candidate_text),
                "requires_candidate_repair": requires_candidate_repair,
                "loopora_fit_contradiction": loopora_fit_contradiction,
                "source_path": source_path,
                **candidate_provenance,
                **ready_candidate_provenance,
                "preview_path": f"/loops/new/bundle?alignment_session_id={session['id']}",
                "entry_invocations": self._append_agent_entry_invocation(
                    existing_binding,
                    action="gen",
                    entry_source=entry_source,
                ),
            },
            context_id=request.context_id,
        )
        return {
            "adapter": adapter,
            "workdir": str(root),
            "candidate_origin": "agent_entry",
            "candidate_entry_source": entry_source,
            "host_context_id": host_context_id,
            "requires_web_alignment": not bool(candidate_text),
            "requires_candidate_repair": requires_candidate_repair,
            "loopora_fit_contradiction": loopora_fit_contradiction,
            **candidate_provenance,
            **ready_candidate_provenance,
            "status": session["status"],
            "ready": session["status"] == "ready",
            "ready_review_projection": self._agent_ready_review_projection(session) if session["status"] == "ready" else {},
            "session": session,
            "binding": binding,
            "preview_path": f"/loops/new/bundle?alignment_session_id={session['id']}",
        }

    def _agent_ready_review_projection(self, session: dict) -> dict[str, Any]:
        try:
            preview = self.get_alignment_bundle(str(session.get("id") or ""))
        except (LooporaError, BundleError, OSError, ValueError):
            return {}
        summary = preview.get("control_summary") if isinstance(preview, dict) else {}
        if not isinstance(summary, dict):
            return {}
        coverage = summary.get("coverage") if isinstance(summary.get("coverage"), dict) else {}
        traceability = summary.get("traceability") if isinstance(summary.get("traceability"), dict) else {}
        diagnostics = [dict(item) for item in list(summary.get("diagnostics") or []) if isinstance(item, dict)]
        gatekeeper = summary.get("gatekeeper") if isinstance(summary.get("gatekeeper"), dict) else {}
        return {
            "loopora_fit_reasons": _first_review_items(summary.get("loop_fit_reasons")),
            "success_surface": _first_review_items(summary.get("success_surface")),
            "fake_done_risks": _first_review_items(summary.get("fake_done_risks")),
            "evidence_preferences": _first_review_items(summary.get("evidence_preferences")),
            "execution_strategy": _first_review_items(summary.get("execution_strategy")),
            "judgment_tradeoffs": _first_review_items(summary.get("judgment_tradeoffs")),
            "residual_risk_policy": _first_review_items(summary.get("residual_risk_policy"), limit=1),
            "local_governance": _first_review_items(summary.get("local_governance"), limit=1),
            "coverage": {
                "check_count": structured_non_negative_int(coverage.get("check_count"), default=0),
                "target_count": structured_non_negative_int(coverage.get("target_count"), default=0),
                "required_target_count": structured_non_negative_int(coverage.get("required_target_count"), default=0),
            },
            "traceability": {
                "mapped_count": structured_non_negative_int(traceability.get("mapped_count"), default=0),
                "required_count": structured_non_negative_int(traceability.get("required_count"), default=0),
            },
            "gatekeeper": {
                "enabled": gatekeeper.get("enabled") is True,
                "requires_evidence_refs": gatekeeper.get("requires_evidence_refs") is True,
            },
            "diagnostic_count": len([item for item in diagnostics if str(item.get("severity") or "") != "info"]),
        }

    def start_agent_loop(
        self,
        adapter: str,
        *,
        workdir: Path | str,
        context_id: str = "",
        entry_source: str = "",
        execute_async: bool = True,
    ) -> dict[str, Any]:
        execute_async = bool(execute_async)
        adapter = normalize_agent_adapter_kind(adapter)
        if adapter not in {"codex", "claude", "opencode"}:
            raise LooporaError(f"{adapter} adapter is not implemented yet")
        root = resolve_adapter_project_root(workdir)
        binding = read_agent_binding(adapter, root, context_id=context_id)
        if not binding:
            raise LooporaConflictError(
                f"no ready Loop preview is associated with this {_adapter_label_for_error(adapter)} session/workdir; run /loopora-gen first"
            )

        session_id = str(binding.get("alignment_session_id") or "").strip()
        if not session_id:
            raise LooporaConflictError("agent binding does not reference a ready Loop preview; run /loopora-gen first")
        session = self.get_alignment_session(session_id)
        self._assert_agent_binding_matches_workdir(binding, session, expected_workdir=root)
        start_context = _AgentLoopStartContext(
            adapter=adapter,
            root=root,
            session_id=session_id,
            context_id=context_id,
            entry_source=entry_source,
        )
        run = self._agent_bound_run(session)
        if run is not None:
            return self._start_agent_loop_from_existing_run(start_context, session, binding, run)

        if session["status"] == "ready":
            return self._start_agent_loop_from_ready_session(start_context, binding)

        if session["status"] == "imported" and session.get("linked_loop_id"):
            return self._start_agent_loop_from_imported_session(start_context, session, binding)

        unready_error = self._agent_loop_unready_error(adapter, binding, session)
        if unready_error:
            raise LooporaConflictError(unready_error)
        raise LooporaConflictError(
            f"{_adapter_label_for_error(adapter)} session has no ready Loop preview (current status: {session['status']}); run /loopora-gen first"
        )

    def _start_agent_loop_from_existing_run(
        self,
        start_context: _AgentLoopStartContext,
        session: dict[str, Any],
        binding: dict[str, Any],
        run: dict[str, Any],
    ) -> dict[str, Any]:
        started_new_run = False
        if self._terminal_agent_run_needs_next_pass(run):
            native, session = self._start_next_agent_native_run(start_context, session, run)
            started_new_run = True
        else:
            native = self._agent_native_projection_for_run(start_context, run)
        binding = self._write_agent_loop_running_binding(start_context, binding, session, native)
        return self._agent_loop_result_from_native(start_context, session, binding, native, started_new_run=started_new_run)

    def _start_agent_loop_from_ready_session(
        self,
        start_context: _AgentLoopStartContext,
        binding: dict[str, Any],
    ) -> dict[str, Any]:
        imported = self.import_alignment_bundle(start_context.session_id, start_immediately=True, execute_async=False)
        session = imported["session"]
        run = imported.get("run")
        if not isinstance(run, dict):
            raise LooporaError("Loopora did not return a run for the ready Loop preview")
        native = self.prepare_agent_native_run(start_context.adapter, run["id"], entry_source=start_context.entry_source)
        ready_context = _AgentLoopStartContext(
            adapter=start_context.adapter,
            root=start_context.root,
            session_id=start_context.session_id,
            context_id=start_context.context_id,
            entry_source=start_context.entry_source,
            binding_extra={"linked_bundle_id": imported["bundle"]["id"], "linked_loop_id": imported["bundle"].get("loop_id", "")},
        )
        binding = self._write_agent_loop_running_binding(ready_context, binding, session, native)
        return self._agent_loop_result_from_native(start_context, session, binding, native, started_new_run=True)

    def _start_agent_loop_from_imported_session(
        self,
        start_context: _AgentLoopStartContext,
        session: dict[str, Any],
        binding: dict[str, Any],
    ) -> dict[str, Any]:
        run = self.start_run(str(session["linked_loop_id"]))
        native = self.prepare_agent_native_run(start_context.adapter, run["id"], entry_source=start_context.entry_source)
        self.repository.update_alignment_session(start_context.session_id, status="running_loop", linked_run_id=native["run"]["id"])
        self.repository.append_alignment_event(start_context.session_id, "alignment_run_started", {"loop_id": session.get("linked_loop_id", ""), "run_id": run["id"]})
        session = self.get_alignment_session(start_context.session_id)
        binding = self._write_agent_loop_running_binding(start_context, binding, session, native)
        return self._agent_loop_result_from_native(start_context, session, binding, native, started_new_run=True)

    def _start_next_agent_native_run(
        self,
        start_context: _AgentLoopStartContext,
        session: dict[str, Any],
        previous_run: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        loop_id = str(session.get("linked_loop_id") or previous_run.get("loop_id") or "").strip()
        if not loop_id:
            raise LooporaConflictError("agent binding has no linked Loop for the next /loopora-loop run")
        run = self.start_run(loop_id)
        self._seed_agent_native_continuation_context(run, previous_run)
        native = self.prepare_agent_native_run(start_context.adapter, run["id"], entry_source=start_context.entry_source)
        self.repository.update_alignment_session(start_context.session_id, status="running_loop", linked_run_id=native["run"]["id"])
        self.repository.append_alignment_event(
            start_context.session_id,
            "alignment_run_started",
            {
                "loop_id": loop_id,
                "run_id": native["run"]["id"],
                "reason": "terminal_task_verdict_requires_next_run",
                "previous_run_id": previous_run["id"],
                "previous_task_verdict_status": self._task_verdict_status_for_run(previous_run),
            },
        )
        return native, self.get_alignment_session(start_context.session_id)

    def _agent_native_projection_for_run(self, start_context: _AgentLoopStartContext, run: dict[str, Any]) -> dict[str, Any]:
        if run["status"] in TERMINAL_RUN_STATUSES:
            return {"run": run, "next_step": None, "complete": True}
        return self.prepare_agent_native_run(start_context.adapter, run["id"], entry_source=start_context.entry_source)

    def _write_agent_loop_running_binding(
        self,
        start_context: _AgentLoopStartContext,
        binding: dict[str, Any],
        session: dict[str, Any],
        native: dict[str, Any],
    ) -> dict[str, Any]:
        ready_candidate_provenance = _ready_candidate_yaml_provenance_from_validation(session)
        return write_agent_binding(
            start_context.adapter,
            start_context.root,
            {
                **binding,
                **ready_candidate_provenance,
                **(start_context.binding_extra or {}),
                "alignment_status": session["status"],
                "requires_web_alignment": False,
                "requires_candidate_repair": False,
                "loopora_fit_contradiction": False,
                "linked_run_id": native["run"]["id"],
                "run_path": f"/runs/{native['run']['id']}",
                "execution_plane": "agent_native",
                "entry_invocations": self._append_agent_entry_invocation(binding, action="loop", entry_source=start_context.entry_source),
            },
            context_id=start_context.context_id,
        )

    def _agent_loop_result_from_native(
        self,
        start_context: _AgentLoopStartContext,
        session: dict[str, Any],
        binding: dict[str, Any],
        native: dict[str, Any],
        *,
        started_new_run: bool,
    ) -> dict[str, Any]:
        return self._agent_loop_result(
            start_context.adapter,
            start_context.root,
            session,
            binding,
            {
                "run": native["run"],
                "started_new_run": started_new_run,
                "next_step": native.get("next_step"),
                "complete": native.get("complete", False),
            },
        )

    def agent_entry_loop_start_projection(self, loop_id: str) -> dict[str, Any]:
        normalized_loop_id = str(loop_id or "").strip()
        if not normalized_loop_id:
            return {}
        loop = self.get_loop(normalized_loop_id)
        for session in self._agent_entry_sessions_for_loop(normalized_loop_id):
            candidate_event = self._alignment_session_agent_entry_candidate_event(str(session.get("id") or ""))
            if not candidate_event:
                continue
            payload = candidate_event.get("payload") if isinstance(candidate_event.get("payload"), dict) else {}
            adapter = self._agent_entry_projection_adapter(payload, session)
            if not adapter:
                continue
            workdir = str(session.get("workdir") or loop.get("workdir") or "").strip()
            entry_source = str(payload.get("entry_source") or "").strip()
            host_context_id = str(payload.get("host_context_id") or "").strip()
            linked_state = self._agent_entry_projection_linked_run_state(session)
            messages = _agent_entry_loop_projection_messages(linked_state["next_loop_action"])
            return {
                "schema_version": 1,
                "source": "agent_entry",
                "requires_agent_native": True,
                "execution_plane": "agent_native",
                "slash_command": "/loopora-loop",
                "adapter": adapter,
                "entry_source": entry_source,
                "host_context_id": host_context_id,
                "workdir": workdir,
                "loop_command": agent_entry_loop_command(adapter, workdir, entry_source, context_id=host_context_id),
                "alignment_session_id": str(session.get("id") or "").strip(),
                "alignment_status": str(session.get("status") or "").strip(),
                **linked_state,
                **messages,
            }
        return {}

    def _agent_entry_projection_adapter(self, payload: dict[str, Any], session: dict[str, Any]) -> str:
        adapter = str(payload.get("adapter") or session.get("executor_kind") or "").strip()
        if not adapter:
            return ""
        try:
            return normalize_agent_adapter_kind(adapter)
        except LooporaError:
            return ""

    def _agent_entry_projection_linked_run_state(self, session: dict[str, Any]) -> dict[str, Any]:
        linked_run_id = str(session.get("linked_run_id") or "").strip()
        state: dict[str, Any] = {
            "linked_run_id": linked_run_id,
            "linked_run_status": "",
            "linked_task_verdict_status": "",
            "next_loop_action": "start_or_continue",
            "continuation_summary": {},
        }
        if not linked_run_id:
            return state
        try:
            linked_run = self.get_run(linked_run_id)
        except LooporaNotFoundError:
            return state
        state["linked_run_status"] = str(linked_run.get("status") or "")
        state["linked_task_verdict_status"] = self._task_verdict_status_for_run(linked_run)
        if self._terminal_agent_run_needs_next_pass(linked_run):
            state["next_loop_action"] = "start_next_run_for_unproven_verdict"
            state["continuation_summary"] = self._agent_entry_continuation_summary(linked_run)
        elif state["linked_run_status"] in TERMINAL_RUN_STATUSES:
            state["next_loop_action"] = "replay_terminal_pass"
        else:
            state["next_loop_action"] = "continue_active_run"
        return state

    def _agent_entry_continuation_summary(self, run: dict) -> dict[str, Any]:
        continuation = self._agent_native_continuation_context_for_terminal_run(run)
        coverage = continuation.get("coverage") if isinstance(continuation.get("coverage"), dict) else {}
        verdict = continuation.get("previous_task_verdict") if isinstance(continuation.get("previous_task_verdict"), dict) else {}
        buckets = verdict.get("buckets") if isinstance(verdict.get("buckets"), dict) else {}
        return {
            "reason": str(continuation.get("reason") or "").strip(),
            "previous_run_id": str(continuation.get("previous_run_id") or "").strip(),
            "previous_run_status": str(continuation.get("previous_run_status") or "").strip(),
            "previous_task_verdict": verdict,
            "coverage": {
                "status": str(coverage.get("status") or "").strip(),
                "covered_check_count": self._non_negative_int(coverage.get("covered_check_count")),
                "missing_check_count": self._non_negative_int(coverage.get("missing_check_count")),
                "target_count": self._non_negative_int(coverage.get("target_count")),
                "covered_target_count": self._non_negative_int(coverage.get("covered_target_count")),
                "weak_target_count": self._non_negative_int(coverage.get("weak_target_count")),
                "missing_target_count": self._non_negative_int(coverage.get("missing_target_count")),
                "blocked_target_count": self._non_negative_int(coverage.get("blocked_target_count")),
                "missing_check_ids": self._string_list(coverage.get("missing_check_ids"), limit=8),
                "top_gaps": self._list_of_dicts(coverage.get("top_gaps"), limit=4),
            },
            "next_focus": self._string_list(continuation.get("next_focus"), limit=5),
            "focus_blocking": self._string_list(
                [self._bucket_focus_text(item) for item in self._list_of_dicts(buckets.get("blocking"), limit=4)],
                limit=4,
            ),
            "focus_unproven": self._string_list(
                [self._bucket_focus_text(item) for item in self._list_of_dicts(buckets.get("unproven"), limit=4)],
                limit=4,
            ),
            "focus_weak": self._string_list(
                [self._bucket_focus_text(item) for item in self._list_of_dicts(buckets.get("weak"), limit=4)],
                limit=4,
            ),
            "previous_task_verdict_path": str(continuation.get("previous_task_verdict_path") or "").strip(),
            "previous_evidence_coverage_path": str(continuation.get("previous_evidence_coverage_path") or "").strip(),
        }

    def _agent_entry_sessions_for_loop(self, loop_id: str) -> list[dict[str, Any]]:
        list_sessions = getattr(self.repository, "list_all_alignment_sessions", None)
        if not callable(list_sessions):
            return []
        normalized_loop_id = str(loop_id or "").strip()
        return [
            session
            for session in list_sessions()
            if str(session.get("linked_loop_id") or "").strip() == normalized_loop_id
        ]

    def _seed_agent_native_continuation_context(self, run: dict, previous_run: dict) -> None:
        layout = self._run_artifact_layout(Path(run["runs_dir"]))
        continuation = self._agent_native_continuation_context_for_terminal_run(previous_run)
        continuation_path = layout.context_dir / "continuation_context.json"
        write_json(continuation_path, continuation)

        run_contract = self._read_json_object(layout.run_contract_path)
        if run_contract:
            run_contract["continuation_context"] = continuation
            write_json(layout.run_contract_path, run_contract)

        self.append_run_event(
            run["id"],
            "run_continuation_context_seeded",
            {
                "previous_run_id": continuation["previous_run_id"],
                "previous_run_status": continuation["previous_run_status"],
                "previous_task_verdict_status": continuation["previous_task_verdict"]["status"],
                "missing_check_count": continuation["coverage"]["missing_check_count"],
                "top_gap_count": len(continuation["coverage"]["top_gaps"]),
                "continuation_context_path": layout.relative(continuation_path),
            },
        )

    def _agent_native_continuation_context_for_terminal_run(self, previous_run: dict) -> dict[str, Any]:
        previous_layout = self._run_artifact_layout(Path(previous_run["runs_dir"]))
        task_verdict = self._task_verdict_context_for_run(previous_run, previous_layout)
        coverage = self._coverage_context_for_run(previous_layout)
        return {
            "active": True,
            "reason": "terminal_task_verdict_requires_next_run",
            "previous_run_id": str(previous_run.get("id") or "").strip(),
            "previous_run_path": f"/runs/{previous_run.get('id')}",
            "previous_run_status": str(previous_run.get("status") or "").strip(),
            "previous_task_verdict": task_verdict,
            "previous_task_verdict_path": str(previous_layout.task_verdict_path.resolve()) if previous_layout.task_verdict_path.exists() else "",
            "previous_evidence_coverage_path": str(previous_layout.evidence_coverage_path.resolve())
            if previous_layout.evidence_coverage_path.exists()
            else "",
            "coverage": coverage,
            "next_focus": self._agent_native_continuation_focus(task_verdict, coverage),
        }

    def _task_verdict_context_for_run(self, run: dict, layout) -> dict[str, Any]:
        task_verdict = normalize_task_verdict(run.get("task_verdict") or run.get("task_verdict_json"))
        if not task_verdict and layout.task_verdict_path.exists():
            task_verdict = normalize_task_verdict(self._read_json_object(layout.task_verdict_path))
        buckets = task_verdict.get("buckets") if isinstance(task_verdict.get("buckets"), dict) else {}
        return {
            "status": str(task_verdict.get("status") or "").strip(),
            "source": str(task_verdict.get("source") or "").strip(),
            "summary": str(task_verdict.get("summary") or "").strip(),
            "buckets": {
                "proven": self._list_of_dicts(buckets.get("proven")),
                "weak": self._list_of_dicts(buckets.get("weak")),
                "unproven": self._list_of_dicts(buckets.get("unproven")),
                "blocking": self._list_of_dicts(buckets.get("blocking")),
                "residual_risk": self._list_of_dicts(buckets.get("residual_risk")),
            },
        }

    def _coverage_context_for_run(self, layout) -> dict[str, Any]:
        coverage_projection = self._read_json_object(layout.evidence_coverage_path)
        coverage_summary = summarize_evidence_coverage_projection(
            coverage_projection,
            coverage_path_available=layout.evidence_coverage_path.exists(),
        )
        return {
            "status": str(coverage_summary.get("status") or "pending"),
            "covered_check_count": self._non_negative_int(coverage_summary.get("covered_check_count")),
            "missing_check_count": self._non_negative_int(coverage_summary.get("missing_check_count")),
            "target_count": self._non_negative_int(coverage_summary.get("target_count")),
            "covered_target_count": self._non_negative_int(coverage_summary.get("covered_target_count")),
            "weak_target_count": self._non_negative_int(coverage_summary.get("weak_target_count")),
            "missing_target_count": self._non_negative_int(coverage_summary.get("missing_target_count")),
            "blocked_target_count": self._non_negative_int(coverage_summary.get("blocked_target_count")),
            "covered_check_ids": self._string_list(coverage_summary.get("covered_check_ids"), limit=20),
            "missing_check_ids": self._string_list(coverage_summary.get("missing_check_ids"), limit=20),
            "top_gaps": self._list_of_dicts(coverage_summary.get("top_gaps"), limit=5),
        }

    @classmethod
    def _agent_native_continuation_focus(cls, task_verdict: dict, coverage: dict) -> list[str]:
        focus: list[str] = []
        summary = str(task_verdict.get("summary") or "").strip()
        if summary:
            focus.append(summary)
        buckets = task_verdict.get("buckets") if isinstance(task_verdict.get("buckets"), dict) else {}
        for bucket_name in ("blocking", "unproven", "weak"):
            for item in cls._list_of_dicts(buckets.get(bucket_name), limit=4):
                text = cls._bucket_focus_text(item)
                if text:
                    focus.append(text)
        for gap in cls._list_of_dicts(coverage.get("top_gaps"), limit=5):
            target_id = str(gap.get("target_id") or "").strip()
            text = str(gap.get("text") or gap.get("reason") or "").strip()
            if target_id or text:
                focus.append(f"{target_id}: {text}".strip(": "))
        return cls._dedupe_strings(focus, limit=8)

    @staticmethod
    def _bucket_focus_text(item: dict) -> str:
        return str(
            item.get("summary")
            or item.get("text")
            or item.get("label")
            or item.get("reason")
            or item.get("id")
            or ""
        ).strip()

    @staticmethod
    def _read_json_object(path: Path) -> dict:
        try:
            payload = read_json(path)
        except (OSError, UnicodeError, ValueError):
            return {}
        return dict(payload) if isinstance(payload, dict) else {}

    @staticmethod
    def _string_list(value: object, *, limit: int | None = None) -> list[str]:
        if not isinstance(value, list):
            return []
        items = [str(item).strip() for item in value if str(item).strip()]
        return items[:limit] if limit is not None else items

    @staticmethod
    def _list_of_dicts(value: object, *, limit: int | None = None) -> list[dict]:
        if not isinstance(value, list):
            return []
        items = [dict(item) for item in value if isinstance(item, dict)]
        return items[:limit] if limit is not None else items

    @staticmethod
    def _non_negative_int(value: object) -> int:
        if isinstance(value, bool):
            return 0
        try:
            integer = int(value)
        except (TypeError, ValueError):
            return 0
        return max(0, integer)

    @staticmethod
    def _dedupe_strings(values: list[str], *, limit: int) -> list[str]:
        seen: set[str] = set()
        deduped: list[str] = []
        for value in values:
            text = str(value or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            deduped.append(text)
            if len(deduped) >= limit:
                break
        return deduped

    def _agent_bound_run(self, session: dict) -> dict | None:
        run_id = str(session.get("linked_run_id") or "").strip()
        if not run_id:
            return None
        try:
            run = self.get_run(run_id)
        except LooporaNotFoundError:
            return None
        if run["status"] not in TERMINAL_RUN_STATUSES:
            return run
        return run

    @staticmethod
    def _task_verdict_status_for_run(run: dict) -> str:
        verdict = run.get("task_verdict") if isinstance(run.get("task_verdict"), dict) else run.get("task_verdict_json")
        if not isinstance(verdict, dict):
            return ""
        return str(verdict.get("status") or "").strip()

    @classmethod
    def _terminal_agent_run_needs_next_pass(cls, run: dict) -> bool:
        if str(run.get("status") or "").strip() not in TERMINAL_RUN_STATUSES:
            return False
        return cls._task_verdict_status_for_run(run) not in PASSING_TASK_VERDICT_STATUSES

    @staticmethod
    def _assert_agent_binding_matches_workdir(binding: dict, session: dict, *, expected_workdir: Path) -> None:
        expected = expected_workdir.expanduser().resolve()
        binding_workdir = str(binding.get("workdir") or "").strip()
        if binding_workdir and Path(binding_workdir).expanduser().resolve() != expected:
            raise LooporaConflictError("agent binding belongs to a different workdir; run /loopora-gen again")
        session_workdir = str(session.get("workdir") or "").strip()
        if not session_workdir or Path(session_workdir).expanduser().resolve() != expected:
            raise LooporaConflictError("agent binding references a Loop preview from a different workdir; run /loopora-gen again")

    @staticmethod
    def _agent_loop_result(adapter: str, root: Path, session: dict, binding: dict, run_result: dict[str, Any]) -> dict[str, Any]:
        run = run_result["run"]
        return {
            "adapter": adapter,
            "workdir": str(root),
            "status": session["status"],
            "session": session,
            "binding": binding,
            "run": run,
            "judgment_contract": build_judgment_contract(run),
            "run_path": f"/runs/{run['id']}",
            "started_new_run": bool(run_result["started_new_run"]),
            "execution_plane": "agent_native",
            "next_step": run_result.get("next_step"),
            "complete": bool(run_result.get("complete", False)),
            "task_next_action": run_result.get("task_next_action") if isinstance(run_result.get("task_next_action"), dict) else {},
        }

    @staticmethod
    def _agent_loop_unready_error(adapter: str, binding: dict, session: dict) -> str:
        label = _adapter_label_for_error(adapter)
        status = str(session.get("status") or "").strip() or "unknown"
        if binding.get("requires_candidate_repair"):
            validation = session.get("validation") if isinstance(session.get("validation"), dict) else {}
            error = str(session.get("error_message") or validation.get("error") or "").strip()
            detail = f": {error}" if error else ""
            if binding.get("loopora_fit_contradiction"):
                return (
                    f"{label} Loop preview is blocked before /loopora-loop because the task summary looked one-off, "
                    f"direct-answer, no-new-evidence, or benchmark/test-harness-only (current status: {status}); define later evidence, handoff, "
                    f"or GateKeeper value, then rerun /loopora-gen with a reframed or repaired candidate{detail}"
                )
            return (
                f"{label} Loop preview needs plan file repair before /loopora-loop "
                f"(current status: {status}); rerun /loopora-gen with a repaired candidate or continue Web review{detail}"
            )
        if binding.get("requires_web_alignment"):
            if binding.get("loopora_fit_contradiction"):
                return (
                    f"{label} Loop preview needs Web review before /loopora-loop "
                    f"(current status: {status}); the task summary looked one-off, direct-answer, no-new-evidence, or benchmark/test-harness-only, "
                    "so define later evidence, handoff, or GateKeeper value in /loopora-gen or Web review first"
                )
            return (
                f"{label} Loop preview needs Web review before /loopora-loop "
                f"(current status: {status}); continue /loopora-gen or Web review first"
            )
        return ""

    @staticmethod
    def _append_agent_entry_invocation(binding: dict[str, Any], *, action: str, entry_source: str) -> list[dict[str, str]]:
        existing = binding.get("entry_invocations") if isinstance(binding, dict) else []
        invocations = [item for item in existing if isinstance(item, dict)] if isinstance(existing, list) else []
        source = str(entry_source or "").strip() or "direct_cli"
        next_invocations = [
            {
                "action": str(item.get("action") or ""),
                "entry_source": str(item.get("entry_source") or ""),
                "at": str(item.get("at") or ""),
            }
            for item in invocations
            if item.get("action")
        ]
        next_invocations.append({"action": action, "entry_source": source, "at": utc_now()})
        return next_invocations[-20:]


def _adapter_label_for_error(adapter: str) -> str:
    return {
        "codex": "Codex",
        "claude": "Claude Code",
        "opencode": "OpenCode",
    }.get(adapter, adapter)
