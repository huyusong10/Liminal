from __future__ import annotations

import json
import logging
import os
import shutil
import signal
import threading
from hashlib import sha256
from pathlib import Path
from typing import Any

from loopora.branding import state_dir_for_workdir
from loopora.bundles import BundleError, bundle_to_yaml, lint_alignment_bundle_semantics, load_bundle_text
from loopora.diagnostics import get_logger, log_event, log_exception
from loopora.executor import ExecutionStopped, ExecutorError, RoleRequest, validate_command_args_text
from loopora.providers import executor_profile, normalize_executor_kind, normalize_executor_mode, normalize_reasoning_setting
from loopora.service_types import LooporaError
from loopora.skills.task_alignment_installer import load_task_alignment_skill_bundle
from loopora.utils import make_id, utc_now

logger = get_logger(__name__)

ALIGNMENT_ACTIVE_STATUSES = {"running", "validating", "repairing"}
ALIGNMENT_CONFIRMED_STAGES = {"confirmed", "compiling"}
ALIGNMENT_READINESS_KEYS = [
    "task_scope",
    "success_surface",
    "fake_done_risks",
    "evidence_preferences",
    "role_posture",
    "workflow_shape",
    "explicit_confirmation",
]
ALIGNMENT_READINESS_EVIDENCE_KEYS = [
    "task_scope",
    "success_surface",
    "fake_done_risks",
    "evidence_preferences",
    "role_posture",
    "workflow_shape",
    "workdir_facts",
]
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
                "success_surface": {"type": "boolean"},
                "fake_done_risks": {"type": "boolean"},
                "evidence_preferences": {"type": "boolean"},
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
                "success_surface": {"type": "string"},
                "fake_done_risks": {"type": "string"},
                "evidence_preferences": {"type": "string"},
                "role_posture": {"type": "string"},
                "workflow_shape": {"type": "string"},
                "workdir_facts": {"type": "string"},
                "open_questions": {"type": "string"},
            },
            "required": ALIGNMENT_READINESS_EVIDENCE_KEYS + ["open_questions"],
        },
    },
    "required": [
        "status",
        "assistant_message",
        "needs_user_input",
        "bundle_yaml",
        "session_ref",
        "alignment_phase",
        "agreement_summary",
        "readiness_checklist",
        "readiness_evidence",
    ],
}


class ServiceAlignmentMixin:
    def create_alignment_session(
        self,
        *,
        workdir: Path,
        message: str = "",
        executor_kind: str = "codex",
        executor_mode: str = "preset",
        command_cli: str = "",
        command_args_text: str = "",
        model: str = "",
        reasoning_effort: str = "",
        start_immediately: bool = True,
    ) -> dict:
        workdir = workdir.expanduser().resolve()
        if not workdir.exists() or not workdir.is_dir():
            raise LooporaError(f"workdir does not exist: {workdir}")
        settings = self._normalize_alignment_executor_settings(
            executor_kind=executor_kind,
            executor_mode=executor_mode,
            command_cli=command_cli,
            command_args_text=command_args_text,
            model=model,
            reasoning_effort=reasoning_effort,
        )
        session_id = make_id("align")
        session_dir = self._alignment_session_dir(workdir, session_id)
        paths = self._alignment_artifact_paths_from_root(session_dir)
        self._ensure_alignment_artifact_dirs(session_dir)
        transcript = []
        normalized_message = str(message or "").strip()
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
                "working_agreement": {},
                "executor_session_ref": {},
                **settings,
            }
        )
        self.repository.append_alignment_event(
            session_id,
            "alignment_session_created",
            {
                "status": session["status"],
                "workdir": session["workdir"],
                "executor_kind": session["executor_kind"],
            },
        )
        self._write_alignment_transcript_log(self.get_alignment_session(session_id))
        if normalized_message and start_immediately:
            self.start_alignment_session_async(session_id)
            return self.get_alignment_session(session_id)
        return self.get_alignment_session(session_id)

    def get_alignment_session(self, session_id: str) -> dict:
        session = self.repository.get_alignment_session(session_id)
        if not session:
            raise LooporaError(f"unknown alignment session: {session_id}")
        session = self._ensure_alignment_session_layout(session)
        return self._decorate_alignment_session(session)

    def list_alignment_sessions(self, *, limit: int = 30) -> list[dict]:
        return [self._alignment_session_summary(item) for item in self.repository.list_alignment_sessions(limit=limit)]

    def delete_alignment_session(self, session_id: str) -> bool:
        session = self.get_alignment_session(session_id)
        if session["status"] in ALIGNMENT_ACTIVE_STATUSES:
            raise LooporaError("cannot delete an active alignment session")
        session_dir = self._alignment_session_root(session)
        deleted = self.repository.delete_alignment_session(session_id)
        if deleted and session_dir.name == session_id and session_dir.parent.name == "alignment_sessions":
            shutil.rmtree(session_dir, ignore_errors=True)
        return deleted

    def append_alignment_message(self, session_id: str, message: str) -> dict:
        normalized = str(message or "").strip()
        if not normalized:
            raise LooporaError("message is required")
        session = self.get_alignment_session(session_id)
        if session["status"] in ALIGNMENT_ACTIVE_STATUSES:
            raise LooporaError("alignment session is already running")
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
            raise LooporaError("alignment session is already running")
        key = self._alignment_thread_key(session_id)
        thread = self._threads.get(key)
        if thread and thread.is_alive():
            raise LooporaError("alignment session is already running")
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
            raise LooporaError(f"cannot cancel alignment session in status {session['status']}")
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
            except (OSError, ValueError):
                pass
        return self.get_alignment_session(session_id)

    def list_alignment_events(self, session_id: str, *, after_id: int = 0, limit: int = 200) -> list[dict]:
        self.get_alignment_session(session_id)
        return self.repository.list_alignment_events(session_id, after_id=after_id, limit=limit)

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
        raw_yaml = bundle_path.read_text(encoding="utf-8")
        try:
            bundle = load_bundle_text(raw_yaml)
        except BundleError as exc:
            return {
                "ok": False,
                "session": session,
                "yaml": raw_yaml,
                "bundle": None,
                "validation": {"ok": False, "error": str(exc), "bundle_path": str(bundle_path)},
            }
        normalized_yaml = bundle_to_yaml(bundle)
        preview = self._bundle_preview_payload(
            bundle,
            source_path=str(bundle_path),
            validation=session.get("validation") or {"ok": True, "bundle_path": str(bundle_path)},
        )
        preview["session"] = session
        preview["yaml"] = normalized_yaml
        return preview

    def sync_alignment_bundle_from_file(self, session_id: str) -> dict:
        session = self.get_alignment_session(session_id)
        if session["status"] in ALIGNMENT_ACTIVE_STATUSES:
            raise LooporaError("cannot sync bundle while alignment session is active")
        if session["status"] not in {"ready", "failed"}:
            raise LooporaError(f"cannot sync bundle in status {session['status']}")
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

        raw_yaml = bundle_path.read_text(encoding="utf-8")
        semantic_issues: list[str] = []
        try:
            bundle = load_bundle_text(raw_yaml)
            self._assert_alignment_bundle_workdir(bundle, expected_workdir=Path(session["workdir"]))
            semantic_issues = lint_alignment_bundle_semantics(bundle)
            if semantic_issues:
                raise LooporaError("bundle semantic lint failed: " + "; ".join(semantic_issues))
            normalized_yaml = bundle_to_yaml(bundle)
            bundle_path.write_text(normalized_yaml, encoding="utf-8")
        except (BundleError, LooporaError) as exc:
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

    def import_alignment_bundle(self, session_id: str, *, start_immediately: bool = True) -> dict:
        session = self.get_alignment_session(session_id)
        if session["status"] != "ready":
            raise LooporaError(f"alignment session is not READY: {session['status']}")
        bundle_path = Path(session["bundle_path"])
        if not bundle_path.exists():
            raise LooporaError(f"alignment bundle does not exist: {bundle_path}")
        raw_yaml = bundle_path.read_text(encoding="utf-8")
        try:
            bundle = self.import_bundle_text(raw_yaml, imported_from_path=str(bundle_path))
        except LooporaError as exc:
            self.repository.update_alignment_session(session_id, error_message=str(exc))
            self.repository.append_alignment_event(
                session_id,
                "alignment_import_failed",
                {"error": str(exc), "status": "ready"},
            )
            raise
        self.repository.update_alignment_session(
            session_id,
            status="imported",
            linked_bundle_id=bundle["id"],
            linked_loop_id=bundle.get("loop_id", ""),
            linked_run_id="",
            error_message="",
        )
        self.repository.append_alignment_event(
            session_id,
            "alignment_imported",
            {"bundle_id": bundle["id"], "loop_id": bundle.get("loop_id", "")},
        )
        run = None
        redirect_url = f"/bundles/{bundle['id']}"
        if start_immediately:
            try:
                run = self.start_run(bundle["loop_id"])
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

    def _execute_alignment_session(self, session_id: str) -> None:
        key = self._alignment_thread_key(session_id)
        mode = "normal"
        validation_error = ""
        invalid_yaml = ""
        try:
            while True:
                output = self._run_alignment_executor(
                    session_id,
                    mode=mode,
                    validation_error=validation_error,
                    invalid_yaml=invalid_yaml,
                )
                session = self.get_alignment_session(session_id)
                session = self._apply_alignment_output_stage(session_id, session, output)
                assistant_message = str(output.get("assistant_message", "") or "").strip()
                bundle_yaml = str(output.get("bundle_yaml", "") or "").strip()
                stage_error = self._alignment_bundle_stage_error(session, output) if bundle_yaml else ""
                if stage_error:
                    assistant_message = stage_error
                    bundle_yaml = ""
                    output["needs_user_input"] = True
                    self.repository.append_alignment_event(
                        session_id,
                        "alignment_stage_blocked",
                        {"status": "waiting_user", "error": stage_error},
                    )
                if assistant_message:
                    transcript = list(session.get("transcript") or [])
                    transcript.append({"role": "assistant", "content": assistant_message, "created_at": utc_now()})
                    self.repository.update_alignment_session(session_id, transcript=transcript)
                    self._write_alignment_transcript_log(self.get_alignment_session(session_id))
                    self.repository.append_alignment_event(
                        session_id,
                        "alignment_message",
                        {"role": "assistant", "content": assistant_message},
                    )

                if bundle_yaml:
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
                        return
                    session = self.get_alignment_session(session_id)
                    if int(session.get("repair_attempts", 0) or 0) < 1:
                        self.repository.update_alignment_session(
                            session_id,
                            status="repairing",
                            repair_attempts=int(session.get("repair_attempts", 0) or 0) + 1,
                            error_message=error,
                        )
                        self.repository.append_alignment_event(
                            session_id,
                            "alignment_repair_started",
                            {"status": "repairing", "error": error},
                        )
                        mode = "repair"
                        validation_error = error
                        invalid_yaml = bundle_yaml
                        continue
                    self._fail_alignment_session(session_id, error)
                    return

                if bool(output.get("needs_user_input")):
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
        except Exception as exc:
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
            if thread is threading.current_thread():
                self._threads.pop(key, None)
            elif thread and not thread.is_alive():
                self._threads.pop(key, None)

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
        attempt = int(session.get("repair_attempts", 0) or 0)
        invocation_dir = self._alignment_invocation_dir(root, attempt, repair=mode == "repair")
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
            sanitized = self._sanitize_alignment_event_payload(payload, invocation_id=invocation_id)
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
            lambda pid: self.repository.update_alignment_session(session_id, active_child_pid=pid)
            if pid is not None
            else self.repository.update_alignment_session(session_id, clear_active_child_pid=True),
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
            evidence_issues = self._readiness_evidence_issues(output)
            if evidence_issues:
                updated = self.repository.update_alignment_session(session_id, alignment_stage="clarifying")
                output["alignment_phase"] = "clarifying"
                output["agreement_summary"] = ""
                output["bundle_yaml"] = ""
                output["needs_user_input"] = True
                missing = ", ".join(evidence_issues)
                output["assistant_message"] = (
                    "我还不能整理确认协议；这些对齐证据还不够具体："
                    f"{missing}。请先补一个会改变循环方案的问题。"
                )
                self.repository.append_alignment_event(
                    session_id,
                    "alignment_evidence_incomplete",
                    {"alignment_stage": "clarifying", "missing": evidence_issues},
                )
                return self._decorate_alignment_session(updated)
            working_agreement = {
                "summary": agreement_summary,
                "readiness_checklist": checklist if isinstance(checklist, dict) else {},
                "readiness_evidence": readiness_evidence if isinstance(readiness_evidence, dict) else {},
                "captured_at": utc_now(),
                "confirmed_at": "",
                "confirmation_message": "",
            }
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
            return self._decorate_alignment_session(updated)
        if phase == "clarifying" and session.get("alignment_stage") not in ALIGNMENT_CONFIRMED_STAGES:
            updated = self.repository.update_alignment_session(session_id, alignment_stage="clarifying")
            return self._decorate_alignment_session(updated)
        return session

    @staticmethod
    def _alignment_bundle_stage_error(session: dict, output: dict) -> str:
        stage = str(session.get("alignment_stage", "") or "clarifying").strip()
        if stage not in ALIGNMENT_CONFIRMED_STAGES:
            return "我还需要先完成需求对齐并得到你的明确确认，再生成循环方案。"
        phase = str(output.get("alignment_phase", "") or "").strip()
        agreement_summary = str(output.get("agreement_summary", "") or "").strip()
        checklist = output.get("readiness_checklist")
        if phase != "bundle":
            return "我还需要先完成需求对齐，再生成循环方案。请先确认任务边界、成功标准和协作方式。"
        if not agreement_summary:
            return "我还需要先整理一份工作协议摘要并得到确认，然后再生成循环方案。"
        if not isinstance(checklist, dict):
            return "我还需要先补齐对齐检查清单，再生成循环方案。"
        missing = [key for key in ALIGNMENT_READINESS_KEYS if checklist.get(key) is not True]
        if missing:
            labels = ", ".join(missing)
            return f"我还不能直接生成循环方案；对齐检查还缺：{labels}。请先补齐这些信息。"
        evidence_issues = ServiceAlignmentMixin._readiness_evidence_issues(output)
        if evidence_issues:
            labels = ", ".join(evidence_issues)
            return f"我还不能直接生成循环方案；这些对齐证据还不够具体：{labels}。请先补齐这些信息。"
        return ""

    @staticmethod
    def _readiness_evidence_issues(output: dict) -> list[str]:
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
            if len(text) < 16 or normalized in generic_values:
                issues.append(key)
        return issues

    @staticmethod
    def _alignment_stage_updates_for_user_message(session: dict, message: str) -> dict[str, Any]:
        stage = str(session.get("alignment_stage", "") or "clarifying")
        status = str(session.get("status", "") or "")
        if stage == "agreement_ready":
            agreement = dict(session.get("working_agreement") or {})
            if ServiceAlignmentMixin._message_confirms_alignment_agreement(message):
                agreement["confirmed_at"] = utc_now()
                agreement["confirmation_message"] = message
                return {"alignment_stage": "confirmed", "working_agreement": agreement}
            agreement["confirmed_at"] = ""
            agreement["confirmation_message"] = ""
            return {"alignment_stage": "clarifying", "working_agreement": agreement}
        if status in {"ready", "imported", "running_loop"}:
            return {"alignment_stage": "clarifying", "working_agreement": {}}
        if status == "failed" and stage not in ALIGNMENT_CONFIRMED_STAGES:
            return {"alignment_stage": "clarifying"}
        return {}

    @staticmethod
    def _message_confirms_alignment_agreement(message: str) -> bool:
        normalized = str(message or "").strip().lower()
        if not normalized:
            return False
        if normalized in {"no", "nope"}:
            return False
        negative_tokens = ["不确认", "不同意", "不要", "先别", "不是", "但是", "不过", " no", "not", " but", "change", "revise"]
        if any(token in normalized for token in negative_tokens):
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
            bundle = load_bundle_text(bundle_yaml)
            self._assert_alignment_bundle_workdir(bundle, expected_workdir=Path(session["workdir"]))
            semantic_issues = lint_alignment_bundle_semantics(bundle)
            if semantic_issues:
                raise LooporaError("bundle semantic lint failed: " + "; ".join(semantic_issues))
            normalized_yaml = bundle_to_yaml(bundle)
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
        return self.get_alignment_session(session_id)

    @staticmethod
    def _alignment_prefers_chinese(session: dict) -> bool:
        text = "\n".join(str(item.get("content", "") or "") for item in (session.get("transcript") or []))
        return any("\u4e00" <= char <= "\u9fff" for char in text)

    @classmethod
    def _alignment_user_language_hint(cls, session: dict) -> str:
        if cls._alignment_prefers_chinese(session):
            return "Chinese. Keep user-facing prose in Chinese and preserve Loopora terms unchanged."
        return "Follow the user's language from the transcript and preserve Loopora terms unchanged."

    @staticmethod
    def _alignment_workdir_snapshot(workdir: Path) -> str:
        try:
            root = workdir.expanduser().resolve()
            if not root.exists() or not root.is_dir():
                return f"Workdir is not an accessible directory: {root}"
            entries = sorted(root.iterdir(), key=lambda item: (item.is_file(), item.name.lower()))
        except OSError as exc:
            return f"Workdir could not be inspected: {exc}"
        visible = [item for item in entries if item.name not in {".DS_Store"}][:40]
        if not visible:
            return "Workdir appears empty. Treat technology choices as assumptions until the run verifies them."
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
        tests_dir = root / "tests"
        lines = [f"Top-level entries ({len(visible)} shown):"]
        for item in visible:
            suffix = "/" if item.is_dir() else ""
            lines.append(f"- {item.name}{suffix}")
        if markers:
            lines.append("Detected markers: " + ", ".join(markers))
        lines.append(f"design/ exists: {'yes' if design_dir.is_dir() else 'no'}")
        lines.append(f"tests/ exists: {'yes' if tests_dir.is_dir() else 'no'}")
        return "\n".join(lines)

    @staticmethod
    def _alignment_manifest_payload(session: dict) -> dict:
        transcript = [item for item in (session.get("transcript") or []) if isinstance(item, dict)]
        first_user = ""
        last_message = ""
        for entry in transcript:
            content = str(entry.get("content", "") or "").strip()
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
            "repair_attempts": int(session.get("repair_attempts", 0) or 0),
            "created_at": session.get("created_at", ""),
            "updated_at": session.get("updated_at", ""),
            "finished_at": session.get("finished_at", ""),
            "error_message": session.get("error_message", ""),
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
        attempt = int(session.get("repair_attempts", 0) or 0)
        invocation_dir = ServiceAlignmentMixin._alignment_invocation_dir(
            paths["root"],
            attempt,
            repair=attempt > 0,
        )
        invocation_dir.mkdir(parents=True, exist_ok=True)
        (invocation_dir / "validation.json").write_text(payload, encoding="utf-8")
        ServiceAlignmentMixin._write_alignment_manifest(session)

    def _build_alignment_prompt(
        self,
        session: dict,
        *,
        mode: str,
        validation_error: str = "",
        invalid_yaml: str = "",
    ) -> str:
        source_dir = load_task_alignment_skill_bundle().source_dir
        skill_text = (source_dir / "SKILL.md").read_text(encoding="utf-8")
        alignment_playbook = (source_dir / "references" / "alignment-playbook.md").read_text(encoding="utf-8")
        quality_rubric = (source_dir / "references" / "quality-rubric.md").read_text(encoding="utf-8")
        bundle_contract = (source_dir / "references" / "bundle-contract.md").read_text(encoding="utf-8")
        revision_guide = (source_dir / "references" / "feedback-revision.md").read_text(encoding="utf-8")
        examples = (source_dir / "references" / "examples.md").read_text(encoding="utf-8")
        current_bundle = ""
        bundle_path = Path(session["bundle_path"])
        if bundle_path.exists():
            current_bundle = bundle_path.read_text(encoding="utf-8")
        transcript_text = json.dumps(session.get("transcript") or [], ensure_ascii=False, indent=2)
        working_agreement_text = json.dumps(session.get("working_agreement") or {}, ensure_ascii=False, indent=2)
        alignment_stage = str(session.get("alignment_stage", "") or "clarifying")
        user_language_hint = self._alignment_user_language_hint(session)
        workdir_snapshot = self._alignment_workdir_snapshot(Path(session["workdir"]))
        repair_text = ""
        if mode == "repair":
            repair_text = f"""
## Repair Input

The previous bundle failed Loopora's hard validator.

Treat semantic lint failures as posture gaps, not as YAML trivia. Repair the task contract, role posture, workflow intent, and evidence path together.

Validation error:
{validation_error}

Previous invalid YAML:
```yaml
{invalid_yaml}
```
"""
        elif current_bundle:
            repair_text = f"""
## Current Bundle

The session already has a bundle. If the latest user message asks for optimization or revision, revise the bundle holistically.

```yaml
{current_bundle}
```
"""

        return f"""
You are Loopora's built-in Web bundle alignment agent.

The user is using an internal Web flow, so do not ask them to install or invoke a Skill manually.
Use the Skill text and bundle contract below as instructions embedded in this prompt.

You must return one JSON object matching the provided schema:
- `status`: "question" if you need user input, "bundle" if `bundle_yaml` is complete, or "blocked" if you cannot proceed.
- `assistant_message`: a concise user-facing reply or question.
- `needs_user_input`: true only when the user should answer before a bundle can be generated.
- `bundle_yaml`: a complete single-file Loopora YAML bundle when ready; otherwise an empty string.
- `session_ref`: always include an object with string fields `session_id`, `thread_id`, `conversation_id`, `provider`, and `raw_json`; use empty strings when you do not have a value.
- `alignment_phase`: one of "clarifying", "agreement", "confirmed", "bundle", or "blocked".
- `agreement_summary`: the current working agreement summary; empty until you have enough stable information to summarize.
- `readiness_checklist`: booleans for `task_scope`, `success_surface`, `fake_done_risks`, `evidence_preferences`, `role_posture`, `workflow_shape`, and `explicit_confirmation`.
- `readiness_evidence`: concrete prose evidence for `task_scope`, `success_surface`, `fake_done_risks`, `evidence_preferences`, `role_posture`, `workflow_shape`, `workdir_facts`, and `open_questions`. These strings explain why the checklist is true or what is still missing.

Important output discipline:
- Do not write files yourself.
- Do not claim READY.
- If the bundle is ready, put the full YAML in `bundle_yaml`; Loopora will write `{session["bundle_path"]}` and validate it.
- The bundle `loop.workdir` must be exactly `{session["workdir"]}`.
- Loopora compiles `spec.markdown` during validation: `# Done When`, `# Success Surface`, `# Fake Done`, and `# Evidence Preferences` must use top-level `-` bullets when present; `# Role Notes` must use `## <Role Name> Notes` subheadings.
- Preserve task-scoped dialogue. Ask focused questions that change the bundle shape, success criteria, evidence strategy, or role posture.
- You are a task-judgment interviewer and harness compiler, not a YAML generator. Never optimize for ending the interview quickly.
- A boolean checklist is not enough. Every true readiness item must be supported by specific `readiness_evidence`.
- Use the workdir snapshot as observed context. Do not invent facts that are not in the transcript or snapshot; label uncertain items as assumptions.

Language discipline:
- User language hint: `{user_language_hint}`.
- Match the user's natural language for `assistant_message`, `agreement_summary`, `collaboration_summary`, `spec.markdown` prose, role descriptions, `posture_notes`, and `workflow.collaboration_intent`.
- Preserve Loopora domain terms exactly: `spec`, `roles`, `workflow`, `bundle`, `Builder`, `Inspector`, `GateKeeper`, `Guide`, `workdir`, `READY`.
- Do not translate YAML keys, role archetypes, or section headings required by the bundle contract, such as `# Task`, `# Done When`, `# Success Surface`, `# Fake Done`, `# Evidence Preferences`, and `# Role Notes`.
- If the user writes Chinese, the user-facing content should be Chinese while the Loopora terms above remain unchanged.

Alignment stage gate:
- Do not generate a bundle in the first assistant turn, even if the user's initial request looks detailed.
- Move through these stages: clarify the task -> summarize the working agreement -> wait for explicit user confirmation -> generate the bundle.
- The backend stage below is authoritative. Do not infer confirmation yourself.
- If backend stage is `clarifying`, ask a focused question or produce an `agreement` phase summary; do not include bundle YAML.
- If backend stage is `agreement_ready`, wait for the user to confirm or revise the agreement; do not include bundle YAML.
- If backend stage is `confirmed` or `compiling`, you may generate or repair the bundle when the checklist is complete.
- Explicit confirmation is necessary but not sufficient. Only generate a bundle when every `readiness_checklist` item is true.
- Explicit confirmation is also not sufficient without concrete `readiness_evidence` for every bundle-shaping dimension.
- If any checklist item is false, set `status` to "question", `needs_user_input` to true, `bundle_yaml` to "", and ask the next smallest useful question.
- If any readiness evidence item is vague, generic, or missing, ask the next smallest useful question even when the user asks you to generate.
- When you are ready to ask for confirmation, set `alignment_phase` to "agreement", `status` to "question", `needs_user_input` to true, put the summary in `agreement_summary`, and leave `bundle_yaml` empty.
- Only after a prior assistant turn has presented that working agreement and the user has confirmed it may you set `alignment_phase` to "bundle" and include `bundle_yaml`.
- For fresh implementation tasks, default to a Builder -> Inspector -> GateKeeper workflow unless the user has a clear reason for a different shape.
- If `loop.completion_mode` is "gatekeeper", the bundle must include a GateKeeper role and at least one GateKeeper workflow step with `on_pass: "finish_run"`.

## Target Runtime

- Workdir: `{session["workdir"]}`
- Session bundle path: `{session["bundle_path"]}`
- Executor kind for the generated loop default: `{session.get("executor_kind", "codex")}`
- Model default: `{session.get("model", "")}`
- Reasoning effort default: `{session.get("reasoning_effort", "")}`

## Workdir Snapshot

This is a lightweight Loopora-provided snapshot. Treat it as observed context, not as a complete repository audit.

```text
{workdir_snapshot}
```

## Backend Alignment State

- Stage: `{alignment_stage}`
- Working agreement:

```json
{working_agreement_text}
```

## Embedded Skill

{skill_text}

## Alignment Playbook

{alignment_playbook}

## Alignment Quality Rubric

{quality_rubric}

## Embedded Bundle Contract

{bundle_contract}

## Revision Guide

{revision_guide}

## Alignment Examples

{examples}

## Session Transcript

```json
{transcript_text}
```

{repair_text}
""".strip()

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
        *,
        executor_kind: str,
        executor_mode: str,
        command_cli: str,
        command_args_text: str,
        model: str,
        reasoning_effort: str,
    ) -> dict:
        try:
            kind = normalize_executor_kind(executor_kind)
            profile = executor_profile(kind)
            mode = "command" if profile.command_only else normalize_executor_mode(executor_mode)
            if mode == "preset":
                return {
                    "executor_kind": kind,
                    "executor_mode": mode,
                    "command_cli": "",
                    "command_args_text": "",
                    "model": str(model or profile.default_model or "").strip(),
                    "reasoning_effort": normalize_reasoning_setting(reasoning_effort, executor_kind=kind),
                }
            normalized_cli = str(command_cli or profile.cli_name or "").strip()
            validate_command_args_text(command_args_text, executor_kind=kind)
            return {
                "executor_kind": kind,
                "executor_mode": mode,
                "command_cli": normalized_cli,
                "command_args_text": str(command_args_text or ""),
                "model": str(model or "").strip(),
                "reasoning_effort": str(reasoning_effort or "").strip(),
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
        moves: list[tuple[Path, Path]] = [
            (root / "bundle.yml", paths["bundle"]),
            (root / "transcript.jsonl", paths["transcript"]),
            (root / "working_agreement.json", paths["agreement"]),
            (root / "validation.json", paths["validation"]),
        ]
        for source, target in moves:
            if source.exists() and not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
        for prompt_path in sorted(root.glob("alignment_prompt_*.md")):
            attempt = self._alignment_attempt_from_legacy_path(prompt_path)
            invocation_dir = self._alignment_invocation_dir(root, attempt, repair=False)
            invocation_dir.mkdir(parents=True, exist_ok=True)
            target = invocation_dir / "prompt.md"
            if not target.exists():
                shutil.copy2(prompt_path, target)
        for output_path in sorted(root.glob("alignment_output_*.json")):
            attempt = self._alignment_attempt_from_legacy_path(output_path)
            invocation_dir = self._alignment_invocation_dir(root, attempt, repair=False)
            invocation_dir.mkdir(parents=True, exist_ok=True)
            target = invocation_dir / "output.json"
            if not target.exists():
                try:
                    payload = json.loads(output_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    shutil.copy2(output_path, target)
                else:
                    target.write_text(
                        json.dumps(self._alignment_output_debug_payload(payload, paths["bundle"]), ensure_ascii=False, indent=2)
                        + "\n",
                        encoding="utf-8",
                    )
        legacy_schema = root / "alignment_schema.json"
        if legacy_schema.exists():
            invocation_dir = self._alignment_invocation_dir(root, 0, repair=False)
            invocation_dir.mkdir(parents=True, exist_ok=True)
            target = invocation_dir / "schema.json"
            if not target.exists():
                shutil.copy2(legacy_schema, target)
        for validation_path in sorted(root.glob("validation_*.json")):
            attempt = self._alignment_attempt_from_legacy_path(validation_path)
            invocation_dir = self._alignment_invocation_dir(root, attempt, repair=False)
            invocation_dir.mkdir(parents=True, exist_ok=True)
            target = invocation_dir / "validation.json"
            if not target.exists():
                shutil.copy2(validation_path, target)
        for source in root.iterdir():
            if source.name in {"conversation", "agreement", "artifacts", "events", "invocations", "legacy"}:
                continue
            if source.name == ".DS_Store":
                continue
            target = legacy_dir / source.name
            if target.exists():
                continue
            try:
                shutil.move(str(source), str(target))
            except OSError:
                pass
        updated = self.repository.update_alignment_session(session["id"], bundle_path=str(paths["bundle"]))
        self._write_alignment_manifest(updated)
        return updated

    @staticmethod
    def _alignment_attempt_from_legacy_path(path: Path) -> int:
        stem = path.stem
        try:
            return max(0, int(stem.rsplit("_", 1)[-1]))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _alignment_invocation_dir(root: Path, attempt: int, *, repair: bool) -> Path:
        suffix = "-repair" if repair else ""
        return root / "invocations" / f"{int(attempt) + 1:04d}{suffix}"

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
        return payload

    @staticmethod
    def _truncate_alignment_event_text(value: str, *, limit: int = 2000) -> str:
        text = str(value or "")
        if len(text) <= limit:
            return text
        return text[:limit] + f"\n... [truncated {len(text) - limit} chars]"

    @classmethod
    def _sanitize_alignment_event_payload(cls, payload: dict, *, invocation_id: str = "") -> dict:
        sanitized = dict(payload) if isinstance(payload, dict) else {}
        if invocation_id:
            sanitized.setdefault("invocation_id", invocation_id)
        for key in ("prompt", "json_schema", "bundle_yaml"):
            if key in sanitized:
                sanitized[f"{key}_omitted"] = True
                sanitized.pop(key, None)
        if sanitized.get("type") == "command" and "message" in sanitized:
            sanitized["message"] = cls._truncate_alignment_event_text(sanitized["message"], limit=500)
            sanitized["command_truncated"] = True
        elif "message" in sanitized:
            sanitized["message"] = cls._truncate_alignment_event_text(sanitized["message"])
        if "error" in sanitized:
            sanitized["error"] = cls._truncate_alignment_event_text(sanitized["error"])
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
            content = str(entry.get("content", "") or "").strip()
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
