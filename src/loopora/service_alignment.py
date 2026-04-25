from __future__ import annotations

import json
import logging
import os
import signal
import threading
from pathlib import Path
from typing import Any

from loopora.branding import state_dir_for_workdir
from loopora.bundles import BundleError, bundle_to_yaml, load_bundle_text
from loopora.diagnostics import get_logger, log_event, log_exception
from loopora.executor import ExecutionStopped, ExecutorError, RoleRequest, validate_command_args_text
from loopora.providers import executor_profile, normalize_executor_kind, normalize_executor_mode, normalize_reasoning_setting
from loopora.service_types import LooporaError
from loopora.skills.task_alignment_installer import load_task_alignment_skill_bundle
from loopora.utils import make_id, utc_now

logger = get_logger(__name__)

ALIGNMENT_ACTIVE_STATUSES = {"running", "validating", "repairing"}
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
    },
    "required": ["status", "assistant_message", "needs_user_input", "bundle_yaml"],
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
        session_dir.mkdir(parents=True, exist_ok=True)
        transcript = []
        normalized_message = str(message or "").strip()
        if normalized_message:
            transcript.append({"role": "user", "content": normalized_message, "created_at": utc_now()})
        session = self.repository.create_alignment_session(
            {
                "id": session_id,
                "status": "idle",
                "workdir": str(workdir),
                "bundle_path": str(session_dir / "bundle.yml"),
                "transcript": transcript,
                "validation": {},
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
        if normalized_message and start_immediately:
            self.start_alignment_session_async(session_id)
            return self.get_alignment_session(session_id)
        return session

    def get_alignment_session(self, session_id: str) -> dict:
        session = self.repository.get_alignment_session(session_id)
        if not session:
            raise LooporaError(f"unknown alignment session: {session_id}")
        return self._decorate_alignment_session(session)

    def append_alignment_message(self, session_id: str, message: str) -> dict:
        normalized = str(message or "").strip()
        if not normalized:
            raise LooporaError("message is required")
        session = self.get_alignment_session(session_id)
        if session["status"] in ALIGNMENT_ACTIVE_STATUSES:
            raise LooporaError("alignment session is already running")
        transcript = list(session.get("transcript") or [])
        transcript.append({"role": "user", "content": normalized, "created_at": utc_now()})
        self.repository.update_alignment_session(
            session_id,
            transcript=transcript,
            error_message="",
            stop_requested=False,
            repair_attempts=0,
            finished_at=None,
        )
        self.repository.append_alignment_event(
            session_id,
            "alignment_user_message",
            {"role": "user", "content": normalized},
        )
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
                assistant_message = str(output.get("assistant_message", "") or "").strip()
                if assistant_message:
                    transcript = list(session.get("transcript") or [])
                    transcript.append({"role": "assistant", "content": assistant_message, "created_at": utc_now()})
                    self.repository.update_alignment_session(session_id, transcript=transcript)
                    self.repository.append_alignment_event(
                        session_id,
                        "alignment_message",
                        {"role": "assistant", "content": assistant_message},
                    )

                bundle_yaml = str(output.get("bundle_yaml", "") or "").strip()
                if bundle_yaml:
                    ok, error = self._write_and_validate_alignment_bundle(session_id, bundle_yaml)
                    if ok:
                        self.repository.update_alignment_session(
                            session_id,
                            status="ready",
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
        session_dir = Path(session["bundle_path"]).parent
        session_dir.mkdir(parents=True, exist_ok=True)
        output_path = session_dir / f"alignment_output_{int(session.get('repair_attempts', 0) or 0)}.json"
        prompt = self._build_alignment_prompt(
            session,
            mode=mode,
            validation_error=validation_error,
            invalid_yaml=invalid_yaml,
        )
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
            run_dir=session_dir,
            executor_kind=session.get("executor_kind", "codex"),
            executor_mode=session.get("executor_mode", "preset"),
            command_cli=session.get("command_cli", ""),
            command_args_text=session.get("command_args_text", ""),
            sandbox="read-only",
            idle_timeout_seconds=self.settings.role_idle_timeout_seconds,
            extra_context={
                "target_workdir": session["workdir"],
                "alignment_session_id": session_id,
                "alignment_mode": mode,
                "validation_error": validation_error,
            },
        )
        executor = self.executor_factory()
        return executor.execute(
            request,
            lambda event_type, payload: self.repository.append_alignment_event(
                session_id,
                event_type,
                {
                    **payload,
                    "alignment_status": self.get_alignment_session(session_id)["status"],
                },
            ),
            lambda: self.repository.alignment_should_stop(session_id),
            lambda pid: self.repository.update_alignment_session(session_id, active_child_pid=pid)
            if pid is not None
            else self.repository.update_alignment_session(session_id, clear_active_child_pid=True),
        )

    def _write_and_validate_alignment_bundle(self, session_id: str, bundle_yaml: str) -> tuple[bool, str]:
        session = self.get_alignment_session(session_id)
        bundle_path = Path(session["bundle_path"])
        bundle_path.parent.mkdir(parents=True, exist_ok=True)
        bundle_path.write_text(bundle_yaml.rstrip() + "\n", encoding="utf-8")
        self.repository.update_alignment_session(session_id, status="validating")
        self.repository.append_alignment_event(
            session_id,
            "alignment_bundle_written",
            {"bundle_path": str(bundle_path), "size": len(bundle_yaml)},
        )
        try:
            bundle = load_bundle_text(bundle_yaml)
            self._assert_alignment_bundle_workdir(bundle, expected_workdir=Path(session["workdir"]))
            normalized_yaml = bundle_to_yaml(bundle)
            bundle_path.write_text(normalized_yaml, encoding="utf-8")
        except (BundleError, LooporaError) as exc:
            error = str(exc)
            validation = {"ok": False, "error": error, "bundle_path": str(bundle_path), "checked_at": utc_now()}
            self.repository.update_alignment_session(session_id, validation=validation, error_message=error)
            self.repository.append_alignment_event(
                session_id,
                "alignment_validation_failed",
                validation,
            )
            return False, error
        validation = {"ok": True, "error": "", "bundle_path": str(bundle_path), "checked_at": utc_now()}
        self.repository.update_alignment_session(session_id, validation=validation)
        self.repository.append_alignment_event(
            session_id,
            "alignment_validation_passed",
            validation,
        )
        return True, ""

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
        bundle_contract = (source_dir / "references" / "bundle-contract.md").read_text(encoding="utf-8")
        revision_guide = (source_dir / "references" / "feedback-revision.md").read_text(encoding="utf-8")
        current_bundle = ""
        bundle_path = Path(session["bundle_path"])
        if bundle_path.exists():
            current_bundle = bundle_path.read_text(encoding="utf-8")
        transcript_text = json.dumps(session.get("transcript") or [], ensure_ascii=False, indent=2)
        repair_text = ""
        if mode == "repair":
            repair_text = f"""
## Repair Input

The previous bundle failed Loopora's hard validator.

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

Important output discipline:
- Do not write files yourself.
- Do not claim READY.
- If the bundle is ready, put the full YAML in `bundle_yaml`; Loopora will write `{session["bundle_path"]}` and validate it.
- The bundle `loop.workdir` must be exactly `{session["workdir"]}`.
- Preserve task-scoped dialogue. Ask only questions that change the bundle shape.
- When the user has already provided enough information, generate the bundle instead of over-interviewing.

## Target Runtime

- Workdir: `{session["workdir"]}`
- Session bundle path: `{session["bundle_path"]}`
- Executor kind for the generated loop default: `{session.get("executor_kind", "codex")}`
- Model default: `{session.get("model", "")}`
- Reasoning effort default: `{session.get("reasoning_effort", "")}`

## Embedded Skill

{skill_text}

## Embedded Bundle Contract

{bundle_contract}

## Revision Guide

{revision_guide}

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
        payload["artifact_dir"] = str(Path(payload["bundle_path"]).parent)
        payload["is_active"] = payload.get("status") in ALIGNMENT_ACTIVE_STATUSES
        payload["is_ready"] = payload.get("status") == "ready"
        return payload
