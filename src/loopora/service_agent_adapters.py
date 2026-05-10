from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loopora.agent_adapters import (
    agent_adapter_status,
    list_agent_adapter_statuses,
    install_agent_adapter,
    read_agent_binding,
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
        adapter = request.adapter
        if adapter != "codex":
            raise LooporaError(f"{adapter} adapter is not implemented yet")
        root = Path(request.workdir).expanduser().resolve()
        raw_yaml = str(request.bundle_yaml or "")
        source_path = ""
        if not raw_yaml.strip() and request.bundle_file is not None:
            bundle_path = Path(request.bundle_file).expanduser().resolve()
            try:
                raw_yaml = read_bundle_file_text(bundle_path)
            except OSError as exc:
                raise LooporaError(str(exc)) from exc
            source_path = str(bundle_path)

        session = self.create_alignment_session(
            workdir=root,
            message=request.message,
            start_immediately=not bool(raw_yaml.strip()),
            executor_kind="codex",
            executor_mode="preset",
            command_cli="",
            command_args_text="",
            model="",
            reasoning_effort="",
        )
        if raw_yaml.strip():
            candidate_path = Path(session["bundle_path"])
            candidate_path.parent.mkdir(parents=True, exist_ok=True)
            candidate_path.write_text(raw_yaml.rstrip() + "\n", encoding="utf-8")
            preview = self.sync_alignment_bundle_from_file(session["id"])
            session = preview["session"]
        existing_binding = read_agent_binding("codex", root, context_id=request.context_id)
        binding = write_agent_binding(
            "codex",
            root,
            {
                "alignment_session_id": session["id"],
                "alignment_status": session["status"],
                "bundle_path": session.get("bundle_path", ""),
                "source_path": source_path,
                "preview_path": f"/loops/new/bundle?alignment_session_id={session['id']}",
                "entry_invocations": self._append_agent_entry_invocation(
                    existing_binding,
                    action="gen",
                    entry_source=request.entry_source,
                ),
            },
            context_id=request.context_id,
        )
        return {
            "adapter": "codex",
            "workdir": str(root),
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
        if adapter != "codex":
            raise LooporaError(f"{adapter} adapter is not implemented yet")
        root = Path(workdir).expanduser().resolve()
        binding = read_agent_binding("codex", root, context_id=context_id)
        if not binding:
            raise LooporaConflictError("no READY Loopora bundle is associated with this Codex session/workdir; run /loopora-gen first")

        session_id = str(binding.get("alignment_session_id") or "").strip()
        if not session_id:
            raise LooporaConflictError("agent binding does not reference a READY Loopora bundle; run /loopora-gen first")
        session = self.get_alignment_session(session_id)
        run = self._agent_bound_run(session)
        if run is not None:
            binding = write_agent_binding(
                "codex",
                root,
                {
                    **binding,
                    "alignment_status": session["status"],
                    "linked_run_id": run["id"],
                    "run_path": f"/runs/{run['id']}",
                    "entry_invocations": self._append_agent_entry_invocation(
                        binding,
                        action="loop",
                        entry_source=entry_source,
                    ),
                },
                context_id=context_id,
            )
            return self._agent_loop_result(root, session, binding, run=run, started_new_run=False)

        if session["status"] == "ready":
            imported = self.import_alignment_bundle(session_id, start_immediately=True, execute_async=execute_async)
            session = imported["session"]
            run = imported.get("run")
            if not isinstance(run, dict):
                raise LooporaError("Loopora did not return a run for the READY bundle")
            binding = write_agent_binding(
                "codex",
                root,
                {
                    **binding,
                    "alignment_status": session["status"],
                    "linked_bundle_id": imported["bundle"]["id"],
                    "linked_loop_id": imported["bundle"].get("loop_id", ""),
                    "linked_run_id": run["id"],
                    "run_path": f"/runs/{run['id']}",
                    "entry_invocations": self._append_agent_entry_invocation(
                        binding,
                        action="loop",
                        entry_source=entry_source,
                    ),
                },
                context_id=context_id,
            )
            return self._agent_loop_result(root, session, binding, run=run, started_new_run=True)

        if session["status"] == "imported" and session.get("linked_loop_id"):
            run = self.start_run(str(session["linked_loop_id"]))
            if execute_async:
                self.start_run_async(run["id"])
            self.repository.update_alignment_session(
                session_id,
                status="running_loop",
                linked_run_id=run["id"],
            )
            self.repository.append_alignment_event(
                session_id,
                "alignment_run_started",
                {"loop_id": session.get("linked_loop_id", ""), "run_id": run["id"]},
            )
            session = self.get_alignment_session(session_id)
            binding = write_agent_binding(
                "codex",
                root,
                {
                    **binding,
                    "alignment_status": session["status"],
                    "linked_run_id": run["id"],
                    "run_path": f"/runs/{run['id']}",
                    "entry_invocations": self._append_agent_entry_invocation(
                        binding,
                        action="loop",
                        entry_source=entry_source,
                    ),
                },
                context_id=context_id,
            )
            return self._agent_loop_result(root, session, binding, run=run, started_new_run=True)

        raise LooporaConflictError(
            f"Codex session has no READY Loopora bundle (current status: {session['status']}); run /loopora-gen first"
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
    def _agent_loop_result(root: Path, session: dict, binding: dict, *, run: dict, started_new_run: bool) -> dict[str, Any]:
        return {
            "adapter": "codex",
            "workdir": str(root),
            "status": session["status"],
            "session": session,
            "binding": binding,
            "run": run,
            "run_path": f"/runs/{run['id']}",
            "started_new_run": started_new_run,
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
