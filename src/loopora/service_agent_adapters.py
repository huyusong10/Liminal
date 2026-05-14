from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loopora.agent_adapters import (
    agent_adapter_status,
    list_agent_adapter_statuses,
    install_agent_adapter,
    normalize_agent_adapter_kind,
    read_agent_binding,
    resolve_adapter_project_root,
    uninstall_agent_adapter,
    write_agent_binding,
)
from loopora.bundles import read_bundle_file_text
from loopora.service_types import LooporaConflictError, LooporaError, LooporaNotFoundError, TERMINAL_RUN_STATUSES
from loopora.utils import utc_now


@dataclass(frozen=True)
class AgentBundleCandidateRequest:
    adapter: str
    workdir: Path | str
    message: str = ""
    bundle_yaml: str = ""
    bundle_file: Path | str | None = None
    context_id: str = ""
    entry_source: str = ""


def _normalized_candidate_yaml(raw_yaml: str) -> str:
    return raw_yaml.rstrip() + "\n" if raw_yaml.strip() else ""


def _candidate_yaml_provenance(candidate_text: str) -> dict[str, Any]:
    if not candidate_text:
        return {"candidate_sha256": "", "candidate_bytes": 0}
    data = candidate_text.encode("utf-8")
    return {"candidate_sha256": hashlib.sha256(data).hexdigest(), "candidate_bytes": len(data)}


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
        if candidate_text and not task_message:
            raise LooporaError("agent candidate bundle requires --message task summary for traceability")

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
                "has_candidate_yaml": bool(candidate_text),
                "requires_web_alignment": not bool(candidate_text),
                "source_path": source_path,
                **candidate_provenance,
            },
        )
        if candidate_text:
            candidate_path = Path(session["bundle_path"])
            candidate_path.parent.mkdir(parents=True, exist_ok=True)
            candidate_path.write_text(candidate_text, encoding="utf-8")
            preview = self.sync_alignment_bundle_from_file(session["id"])
            session = preview["session"]
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
                "requires_web_alignment": not bool(candidate_text),
                "source_path": source_path,
                **candidate_provenance,
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
            "requires_web_alignment": not bool(candidate_text),
            **candidate_provenance,
            "status": session["status"],
            "ready": session["status"] == "ready",
            "session": session,
            "binding": binding,
            "preview_path": f"/loops/new/bundle?alignment_session_id={session['id']}",
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
        run = self._agent_bound_run(session)
        if run is not None:
            native = (
                {"run": run, "next_step": None, "complete": True}
                if run["status"] in TERMINAL_RUN_STATUSES
                else self.prepare_agent_native_run(adapter, run["id"], entry_source=entry_source)
            )
            binding = write_agent_binding(
                adapter,
                root,
                {
                    **binding,
                    "alignment_status": session["status"],
                    "linked_run_id": native["run"]["id"],
                    "run_path": f"/runs/{native['run']['id']}",
                    "execution_plane": "agent_native",
                    "entry_invocations": self._append_agent_entry_invocation(
                        binding,
                        action="loop",
                        entry_source=entry_source,
                    ),
                },
                context_id=context_id,
            )
            return self._agent_loop_result(
                adapter,
                root,
                session,
                binding,
                {
                    "run": native["run"],
                    "started_new_run": False,
                    "next_step": native.get("next_step"),
                    "complete": native.get("complete", False),
                },
            )

        if session["status"] == "ready":
            imported = self.import_alignment_bundle(session_id, start_immediately=True, execute_async=False)
            session = imported["session"]
            run = imported.get("run")
            if not isinstance(run, dict):
                raise LooporaError("Loopora did not return a run for the ready Loop preview")
            native = self.prepare_agent_native_run(adapter, run["id"], entry_source=entry_source)
            binding = write_agent_binding(
                adapter,
                root,
                {
                    **binding,
                    "alignment_status": session["status"],
                    "linked_bundle_id": imported["bundle"]["id"],
                    "linked_loop_id": imported["bundle"].get("loop_id", ""),
                    "linked_run_id": native["run"]["id"],
                    "run_path": f"/runs/{native['run']['id']}",
                    "execution_plane": "agent_native",
                    "entry_invocations": self._append_agent_entry_invocation(
                        binding,
                        action="loop",
                        entry_source=entry_source,
                    ),
                },
                context_id=context_id,
            )
            return self._agent_loop_result(
                adapter,
                root,
                session,
                binding,
                {
                    "run": native["run"],
                    "started_new_run": True,
                    "next_step": native.get("next_step"),
                    "complete": native.get("complete", False),
                },
            )

        if session["status"] == "imported" and session.get("linked_loop_id"):
            run = self.start_run(str(session["linked_loop_id"]))
            native = self.prepare_agent_native_run(adapter, run["id"], entry_source=entry_source)
            self.repository.update_alignment_session(
                session_id,
                status="running_loop",
                linked_run_id=native["run"]["id"],
            )
            self.repository.append_alignment_event(
                session_id,
                "alignment_run_started",
                {"loop_id": session.get("linked_loop_id", ""), "run_id": run["id"]},
            )
            session = self.get_alignment_session(session_id)
            binding = write_agent_binding(
                adapter,
                root,
                {
                    **binding,
                    "alignment_status": session["status"],
                    "linked_run_id": native["run"]["id"],
                    "run_path": f"/runs/{native['run']['id']}",
                    "execution_plane": "agent_native",
                    "entry_invocations": self._append_agent_entry_invocation(
                        binding,
                        action="loop",
                        entry_source=entry_source,
                    ),
                },
                context_id=context_id,
            )
            return self._agent_loop_result(
                adapter,
                root,
                session,
                binding,
                {
                    "run": native["run"],
                    "started_new_run": True,
                    "next_step": native.get("next_step"),
                    "complete": native.get("complete", False),
                },
            )

        raise LooporaConflictError(
            f"{_adapter_label_for_error(adapter)} session has no ready Loop preview (current status: {session['status']}); run /loopora-gen first"
        )

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
    def _agent_loop_result(adapter: str, root: Path, session: dict, binding: dict, run_result: dict[str, Any]) -> dict[str, Any]:
        run = run_result["run"]
        return {
            "adapter": adapter,
            "workdir": str(root),
            "status": session["status"],
            "session": session,
            "binding": binding,
            "run": run,
            "run_path": f"/runs/{run['id']}",
            "started_new_run": bool(run_result["started_new_run"]),
            "execution_plane": "agent_native",
            "next_step": run_result.get("next_step"),
            "complete": bool(run_result.get("complete", False)),
        }

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
