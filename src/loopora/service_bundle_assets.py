from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import shutil

from loopora.bundles import BundleError, bundle_to_yaml, load_bundle_file, load_bundle_text, normalize_bundle
from loopora.settings import app_home
from loopora.specs import compile_markdown_spec, SpecError
from loopora.service_asset_common import _normalize_role_models
from loopora.service_types import LooporaError
from loopora.utils import make_id
from loopora.utils import write_json
from loopora.workflows import ROLE_EXECUTION_FIELDS, ROLE_POSTURE_FIELDS, has_finish_gatekeeper_step


class ServiceBundleAssetMixin:
    def _bundle_dir(self, bundle_id: str) -> Path:
        return app_home() / "bundles" / bundle_id

    def _bundle_spec_path(self, bundle_id: str) -> Path:
        return self._bundle_dir(bundle_id) / "spec.md"

    def _bundle_yaml_path(self, bundle_id: str) -> Path:
        return self._bundle_dir(bundle_id) / "bundle.yml"

    def list_bundles(self) -> list[dict]:
        return [self._hydrate_bundle_links(bundle) for bundle in self.repository.list_bundles()]

    def get_bundle(self, bundle_id: str) -> dict:
        bundle = self.repository.get_bundle(bundle_id)
        if not bundle:
            raise LooporaError(f"unknown bundle: {bundle_id}")
        return self._hydrate_bundle_links(bundle)

    def import_bundle_file(self, path: Path, *, replace_bundle_id: str | None = None) -> dict:
        try:
            bundle = load_bundle_file(path)
        except (BundleError, OSError) as exc:
            raise LooporaError(str(exc)) from exc
        return self._import_normalized_bundle(
            bundle,
            replace_bundle_id=replace_bundle_id,
            imported_from_path=str(path.expanduser().resolve()),
        )

    def import_bundle_text(
        self,
        raw_text: str,
        *,
        replace_bundle_id: str | None = None,
        imported_from_path: str = "",
    ) -> dict:
        try:
            bundle = load_bundle_text(raw_text)
        except BundleError as exc:
            raise LooporaError(str(exc)) from exc
        return self._import_normalized_bundle(
            bundle,
            replace_bundle_id=replace_bundle_id,
            imported_from_path=imported_from_path,
        )

    def export_bundle(self, bundle_id: str) -> dict:
        bundle = self.get_bundle(bundle_id)
        return self.derive_bundle_from_loop(
            bundle["loop_id"],
            bundle_id=bundle["id"],
            name=bundle["name"],
            description=str(bundle.get("description", "")),
            collaboration_summary=str(bundle.get("collaboration_summary", "")),
            source_bundle_id=str(bundle.get("source_bundle_id", "")),
            revision=int(bundle.get("revision", 1) or 1),
        )

    def export_bundle_yaml(self, bundle_id: str) -> str:
        return bundle_to_yaml(self.export_bundle(bundle_id))

    def derive_bundle_from_loop(
        self,
        loop_id: str,
        *,
        bundle_id: str = "",
        name: str | None = None,
        description: str = "",
        collaboration_summary: str = "",
        source_bundle_id: str = "",
        revision: int = 1,
    ) -> dict:
        loop = self.get_loop(loop_id)
        workflow = dict(loop.get("workflow_json") or {})
        prompt_files = dict(loop.get("prompt_files") or {})
        spec_markdown = loop.get("spec_markdown", "")
        role_definitions = []
        for role in workflow.get("roles", []):
            role_definition = None
            role_definition_id = str(role.get("role_definition_id", "") or "").strip()
            if role_definition_id:
                try:
                    role_definition = self.get_role_definition(role_definition_id)
                except LooporaError:
                    role_definition = None
            prompt_ref = str(role.get("prompt_ref", "") or (role_definition or {}).get("prompt_ref", "") or "").strip()
            prompt_markdown = str(prompt_files.get(prompt_ref, "") or "") if prompt_ref else ""
            if not prompt_markdown:
                prompt_markdown = str(role.get("prompt_markdown", "") or "")
            if not prompt_markdown and role_definition is not None:
                prompt_markdown = str(role_definition.get("prompt_markdown", "") or "")
            def snapshot_value(field: str) -> object:
                return role.get(field, "") if field in role else (role_definition or {}).get(field, "")

            role_definitions.append(
                {
                    "key": str(role.get("id", "") or "").strip(),
                    "name": str(snapshot_value("name") or "").strip(),
                    "description": str((role_definition or {}).get("description", "") or role.get("description", "") or "").strip(),
                    "archetype": str(snapshot_value("archetype") or "").strip(),
                    "prompt_ref": prompt_ref,
                    "prompt_markdown": str(prompt_markdown or ""),
                    "posture_notes": str(snapshot_value("posture_notes") or "").strip(),
                    "executor_kind": str(snapshot_value("executor_kind") or "").strip(),
                    "executor_mode": str(snapshot_value("executor_mode") or "").strip(),
                    "command_cli": str(snapshot_value("command_cli") or "").strip(),
                    "command_args_text": str(snapshot_value("command_args_text") or ""),
                    "model": str(snapshot_value("model") or "").strip(),
                    "reasoning_effort": str(snapshot_value("reasoning_effort") or "").strip(),
                }
            )

        workflow_bundle = {
            "version": int(workflow.get("version", 1) or 1),
            "preset": str(workflow.get("preset", "") or "").strip(),
            "collaboration_intent": str(workflow.get("collaboration_intent", "") or "").strip(),
            "roles": [
                {
                    "id": str(role.get("id", "") or "").strip(),
                    "role_definition_key": str(role.get("id", "") or "").strip(),
                }
                for role in workflow.get("roles", [])
            ],
            "steps": [
                {
                    "id": str(step.get("id", "") or "").strip(),
                    "role_id": str(step.get("role_id", "") or "").strip(),
                    "on_pass": str(step.get("on_pass", "continue") or "continue").strip(),
                    "model": str(step.get("model", "") or "").strip(),
                    "inherit_session": bool(step.get("inherit_session")),
                    "extra_cli_args": str(step.get("extra_cli_args", "") or "").strip(),
                }
                for step in workflow.get("steps", [])
            ],
        }
        bundle = {
            "version": 1,
            "metadata": {
                "bundle_id": bundle_id,
                "name": name or str(loop.get("name", "") or "").strip() or loop_id,
                "description": description,
                "source_bundle_id": source_bundle_id,
                "revision": int(revision or 1),
            },
            "collaboration_summary": collaboration_summary or description or str(loop.get("name", "") or "").strip(),
            "loop": {
                "name": str(loop.get("name", "") or "").strip(),
                "workdir": str(loop.get("workdir", "") or ""),
                "completion_mode": str(loop.get("completion_mode", "gatekeeper") or "gatekeeper").strip(),
                "executor_kind": str(loop.get("executor_kind", "codex") or "codex").strip(),
                "executor_mode": str(loop.get("executor_mode", "preset") or "preset").strip(),
                "command_cli": str(loop.get("command_cli", "") or "").strip(),
                "command_args_text": str(loop.get("command_args_text", "") or ""),
                "model": str(loop.get("model", "") or "").strip(),
                "reasoning_effort": str(loop.get("reasoning_effort", "") or "").strip(),
                "iteration_interval_seconds": float(loop.get("iteration_interval_seconds", 0.0) or 0.0),
                "max_iters": int(loop.get("max_iters", 8) or 8),
                "max_role_retries": int(loop.get("max_role_retries", 2) or 2),
                "delta_threshold": float(loop.get("delta_threshold", 0.005) or 0.005),
                "trigger_window": int(loop.get("trigger_window", 4) or 4),
                "regression_window": int(loop.get("regression_window", 2) or 2),
            },
            "spec": {"markdown": str(spec_markdown or "").strip()},
            "role_definitions": role_definitions,
            "workflow": workflow_bundle,
        }
        try:
            return normalize_bundle(bundle)
        except BundleError as exc:
            raise LooporaError(str(exc)) from exc

    def write_bundle_file(self, bundle_id: str, path: Path) -> Path:
        target = path.expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.export_bundle_yaml(bundle_id), encoding="utf-8")
        return target

    def update_bundle(
        self,
        bundle_id: str,
        *,
        description: str | None = None,
        collaboration_summary: str | None = None,
        spec_markdown: str | None = None,
        bump_revision: bool = True,
    ) -> dict:
        bundle = self.get_bundle(bundle_id)
        normalized_markdown = None
        if spec_markdown is not None:
            normalized_markdown = str(spec_markdown or "").strip()
            if not normalized_markdown:
                raise LooporaError("bundle spec markdown is required")
            try:
                compile_markdown_spec(normalized_markdown)
            except SpecError as exc:
                raise LooporaError(str(exc)) from exc

        snapshot = None
        if str(bundle.get("loop_id", "") or "").strip():
            snapshot = self._build_bundle_loop_snapshot(
                bundle_id,
                spec_markdown=normalized_markdown,
            )
        elif normalized_markdown is not None:
            spec_path = self._bundle_spec_path(bundle_id)
            spec_path.parent.mkdir(parents=True, exist_ok=True)
            spec_path.write_text(normalized_markdown + "\n", encoding="utf-8")

        payload = {
            "name": bundle["name"],
            "description": str(bundle.get("description", "")) if description is None else str(description or "").strip(),
            "collaboration_summary": (
                str(bundle.get("collaboration_summary", ""))
                if collaboration_summary is None
                else str(collaboration_summary or "").strip()
            ),
            "workdir": bundle.get("workdir", ""),
            "loop_id": bundle.get("loop_id", ""),
            "orchestration_id": bundle.get("orchestration_id", ""),
            "role_definition_ids": bundle.get("role_definition_ids", []),
            "source_bundle_id": bundle.get("source_bundle_id", ""),
            "revision": int(bundle.get("revision", 1) or 1) + (1 if bump_revision else 0),
            "imported_from_path": bundle.get("imported_from_path", ""),
        }
        if snapshot is not None:
            self._apply_bundle_loop_snapshot(snapshot)
        saved = self.repository.update_bundle(bundle_id, payload)
        if not saved:
            raise LooporaError(f"failed to update bundle: {bundle_id}")
        self._sync_bundle_yaml(bundle_id)
        return self.get_bundle(bundle_id)

    def update_bundle_metadata(
        self,
        bundle_id: str,
        *,
        description: str | None = None,
        collaboration_summary: str | None = None,
    ) -> dict:
        return self.update_bundle(
            bundle_id,
            description=description,
            collaboration_summary=collaboration_summary,
        )

    def update_bundle_spec_markdown(self, bundle_id: str, markdown_text: str) -> dict:
        return self.update_bundle(bundle_id, spec_markdown=markdown_text)

    def delete_bundle(self, bundle_id: str) -> dict:
        bundle = self.get_bundle(bundle_id)
        self._delete_bundle_links(bundle, delete_record=True)
        return {"id": bundle_id, "deleted": True}

    def _import_normalized_bundle(
        self,
        bundle: dict,
        *,
        replace_bundle_id: str | None = None,
        imported_from_path: str,
    ) -> dict:
        target_bundle_id = str(replace_bundle_id or bundle["metadata"].get("bundle_id") or make_id("bundle")).strip()
        existing = self.repository.get_bundle(target_bundle_id)
        if existing and not replace_bundle_id:
            raise LooporaError(f"bundle already exists: {target_bundle_id}")
        if existing:
            self._assert_bundle_links_replaceable(existing)
        bundle_dir = self._bundle_dir(target_bundle_id)
        backup_dir = self._backup_bundle_dir(bundle_dir) if existing else None
        role_definition_id_by_key: dict[str, str] = {}
        created_role_ids: list[str] = []
        orchestration_id = ""
        loop_id = ""
        saved = None
        committed = False
        prompt_ref_namespace = target_bundle_id if not existing else f"{target_bundle_id}/{make_id('revision')}"
        try:
            bundle_dir.mkdir(parents=True, exist_ok=True)
            spec_path = self._bundle_spec_path(target_bundle_id)
            spec_path.write_text(str(bundle["spec"]["markdown"]), encoding="utf-8")

            for entry in bundle["role_definitions"]:
                imported = self.create_role_definition(
                    name=entry["name"],
                    description=entry.get("description", ""),
                    archetype=entry["archetype"],
                    prompt_ref=self._imported_prompt_ref(prompt_ref_namespace, entry["key"], entry["archetype"]),
                    prompt_markdown=entry["prompt_markdown"],
                    posture_notes=entry.get("posture_notes", ""),
                    executor_kind=entry["executor_kind"],
                    executor_mode=entry["executor_mode"],
                    command_cli=entry.get("command_cli", ""),
                    command_args_text=entry.get("command_args_text", ""),
                    model=entry.get("model", ""),
                    reasoning_effort=entry.get("reasoning_effort", ""),
                )
                role_definition_id_by_key[entry["key"]] = imported["id"]
                created_role_ids.append(imported["id"])

            workflow_payload = {
                "version": bundle["workflow"]["version"],
                "preset": bundle["workflow"]["preset"],
                "collaboration_intent": bundle["workflow"].get("collaboration_intent", ""),
                "roles": [
                    {
                        "id": entry["id"],
                        "role_definition_id": role_definition_id_by_key[entry["role_definition_key"]],
                    }
                    for entry in bundle["workflow"]["roles"]
                ],
                "steps": list(bundle["workflow"]["steps"]),
            }
            orchestration = self.create_orchestration(
                name=bundle["metadata"]["name"],
                description=bundle["metadata"].get("description", ""),
                workflow=workflow_payload,
                prompt_files=None,
                role_models=None,
            )
            orchestration_id = orchestration["id"]
            loop_settings = bundle["loop"]
            loop = self.create_loop(
                name=loop_settings["name"],
                spec_path=spec_path,
                workdir=Path(loop_settings["workdir"]),
                model=loop_settings["model"],
                reasoning_effort=loop_settings["reasoning_effort"],
                max_iters=loop_settings["max_iters"],
                max_role_retries=loop_settings["max_role_retries"],
                delta_threshold=loop_settings["delta_threshold"],
                trigger_window=loop_settings["trigger_window"],
                regression_window=loop_settings["regression_window"],
                executor_kind=loop_settings["executor_kind"],
                executor_mode=loop_settings["executor_mode"],
                command_cli=loop_settings["command_cli"],
                command_args_text=loop_settings["command_args_text"],
                orchestration_id=orchestration_id,
                completion_mode=loop_settings["completion_mode"],
                iteration_interval_seconds=loop_settings["iteration_interval_seconds"],
            )
            loop_id = loop["id"]
            payload = {
                "id": target_bundle_id,
                "name": bundle["metadata"]["name"],
                "description": bundle["metadata"].get("description", ""),
                "collaboration_summary": bundle["collaboration_summary"],
                "workdir": loop_settings["workdir"],
                "loop_id": loop_id,
                "orchestration_id": orchestration_id,
                "role_definition_ids": created_role_ids,
                "source_bundle_id": bundle["metadata"].get("source_bundle_id", ""),
                "revision": int((existing or {}).get("revision", 0) or 0) + 1 if existing else int(bundle["metadata"].get("revision", 1) or 1),
                "imported_from_path": imported_from_path,
            }
            export_payload = self.derive_bundle_from_loop(
                loop_id,
                bundle_id=target_bundle_id,
                name=payload["name"],
                description=payload["description"],
                collaboration_summary=payload["collaboration_summary"],
                source_bundle_id=payload["source_bundle_id"],
                revision=payload["revision"],
            )
            self._bundle_yaml_path(target_bundle_id).write_text(bundle_to_yaml(export_payload), encoding="utf-8")
            if existing:
                saved = self.repository.update_bundle(target_bundle_id, payload)
            else:
                saved = self.repository.create_bundle(payload)
            if not saved:
                raise LooporaError(f"failed to persist bundle: {target_bundle_id}")
            if existing:
                self._delete_bundle_links(existing, delete_record=False, delete_managed_dir=False)
            committed = True
            return self.get_bundle(saved["id"])
        except Exception:
            if not committed:
                if saved is not None:
                    if existing:
                        self.repository.update_bundle(target_bundle_id, self._bundle_payload_from_record(existing))
                    else:
                        self.repository.delete_bundle(target_bundle_id)
                self._cleanup_created_bundle_assets(
                    loop_id=loop_id,
                    orchestration_id=orchestration_id,
                    role_definition_ids=created_role_ids,
                )
                self._restore_bundle_dir_after_failed_import(
                    bundle_dir=bundle_dir,
                    backup_dir=backup_dir,
                    had_existing=bool(existing),
                )
            raise
        finally:
            if backup_dir and backup_dir.exists():
                shutil.rmtree(backup_dir, ignore_errors=True)

    def _assert_bundle_links_replaceable(self, bundle: dict) -> None:
        loop_id = str(bundle.get("loop_id", "") or "").strip()
        if not loop_id:
            return
        loop = self.get_loop(loop_id)
        active_runs = [run["id"] for run in loop.get("runs", []) if run.get("status") in {"queued", "running"}]
        if active_runs:
            raise LooporaError(f"cannot replace bundle with active loop runs: {', '.join(active_runs)}")

    def _backup_bundle_dir(self, bundle_dir: Path) -> Path | None:
        if not bundle_dir.exists():
            return None
        backup_dir = bundle_dir.with_name(f"{bundle_dir.name}.{make_id('backup')}")
        shutil.copytree(bundle_dir, backup_dir)
        return backup_dir

    def _restore_bundle_dir_after_failed_import(
        self,
        *,
        bundle_dir: Path,
        backup_dir: Path | None,
        had_existing: bool,
    ) -> None:
        if had_existing:
            if backup_dir is None:
                return
            shutil.rmtree(bundle_dir, ignore_errors=True)
            shutil.copytree(backup_dir, bundle_dir)
            return
        shutil.rmtree(bundle_dir, ignore_errors=True)

    def _bundle_payload_from_record(self, bundle: dict) -> dict:
        role_definition_ids = [
            str(item).strip()
            for item in (bundle.get("role_definition_ids") or bundle.get("role_definition_ids_json") or [])
            if str(item).strip()
        ]
        return {
            "name": bundle["name"],
            "description": bundle.get("description", ""),
            "collaboration_summary": bundle.get("collaboration_summary", ""),
            "workdir": bundle.get("workdir", ""),
            "loop_id": bundle.get("loop_id", ""),
            "orchestration_id": bundle.get("orchestration_id", ""),
            "role_definition_ids": role_definition_ids,
            "source_bundle_id": bundle.get("source_bundle_id", ""),
            "revision": int(bundle.get("revision", 1) or 1),
            "imported_from_path": bundle.get("imported_from_path", ""),
        }

    def _cleanup_created_bundle_assets(
        self,
        *,
        loop_id: str,
        orchestration_id: str,
        role_definition_ids: list[str],
    ) -> None:
        if loop_id:
            try:
                self.delete_loop(loop_id, allow_bundle_owned=True)
            except LooporaError:
                pass
        if orchestration_id:
            try:
                self.delete_orchestration(orchestration_id, allow_bundle_owned=True)
            except LooporaError:
                pass
        for role_definition_id in role_definition_ids:
            try:
                self.delete_role_definition(role_definition_id, allow_bundle_owned=True)
            except LooporaError:
                continue

    def _sync_bundle_loop_snapshot(self, bundle_id: str) -> dict | None:
        snapshot = self._build_bundle_loop_snapshot(bundle_id)
        if snapshot is None:
            return None
        return self._apply_bundle_loop_snapshot(snapshot)

    def _build_bundle_loop_snapshot(
        self,
        bundle_id: str,
        *,
        spec_markdown: str | None = None,
    ) -> dict | None:
        bundle = self.repository.get_bundle(bundle_id)
        if not bundle:
            raise LooporaError(f"unknown bundle: {bundle_id}")
        loop_id = str(bundle.get("loop_id", "") or "").strip()
        if not loop_id:
            return None
        loop = self.repository.get_loop(loop_id)
        if not loop:
            raise LooporaError(f"unknown bundle loop: {loop_id}")

        spec_path = self._bundle_spec_path(bundle_id)
        if spec_markdown is None:
            if not spec_path.exists():
                raise LooporaError(f"bundle spec does not exist: {spec_path}")
            effective_spec_markdown, compiled_spec = self._read_and_compile_spec(spec_path)
        else:
            effective_spec_markdown = str(spec_markdown or "").strip() + "\n"
            compiled_spec = compile_markdown_spec(effective_spec_markdown)
        role_models = _normalize_role_models(loop.get("role_models_json") or loop.get("role_models") or {})
        resolved_orchestration = self._resolve_bundle_orchestration_for_snapshot(bundle, role_models=role_models)
        normalized_workflow = resolved_orchestration["workflow"]
        if loop.get("completion_mode") == "gatekeeper" and not has_finish_gatekeeper_step(normalized_workflow):
            raise LooporaError(
                "gatekeeper completion mode requires a GateKeeper step that can finish the run"
            )
        return {
            "bundle": bundle,
            "loop": loop,
            "loop_id": loop_id,
            "spec_path": spec_path,
            "spec_markdown": effective_spec_markdown,
            "compiled_spec": compiled_spec,
            "resolved_orchestration": resolved_orchestration,
        }

    def _apply_bundle_loop_snapshot(self, snapshot: dict) -> dict:
        loop = snapshot["loop"]
        loop_id = snapshot["loop_id"]
        spec_path = snapshot["spec_path"]
        spec_markdown = snapshot["spec_markdown"]
        compiled_spec = snapshot["compiled_spec"]
        resolved_orchestration = snapshot["resolved_orchestration"]
        self._persist_refreshed_bundle_orchestration(resolved_orchestration)

        spec_path.parent.mkdir(parents=True, exist_ok=True)
        spec_path.write_text(spec_markdown, encoding="utf-8")
        loop_dir = self._ensure_loop_dir(Path(loop["workdir"]), loop_id)
        (loop_dir / "spec.md").write_text(spec_markdown, encoding="utf-8")
        write_json(loop_dir / "compiled_spec.json", compiled_spec)
        self._persist_prompt_files(loop_dir, resolved_orchestration["prompt_files"])
        write_json(loop_dir / "workflow.json", resolved_orchestration["workflow"])

        updated = self.repository.update_loop_contract(
            loop_id,
            {
                "orchestration_id": resolved_orchestration["id"],
                "orchestration_name": resolved_orchestration["name"],
                "spec_path": str(spec_path.resolve()),
                "spec_markdown": spec_markdown,
                "compiled_spec": compiled_spec,
                "workflow": resolved_orchestration["workflow"],
            },
        )
        if not updated:
            raise LooporaError(f"failed to update bundle loop snapshot: {loop_id}")
        return self._hydrate_loop_files(updated)

    def _resolve_bundle_orchestration_for_snapshot(self, bundle: dict, *, role_models: dict) -> dict:
        orchestration_id = str(bundle.get("orchestration_id", "") or "").strip()
        if not orchestration_id:
            raise LooporaError(f"bundle {bundle['id']} has no orchestration")
        orchestration = self.get_orchestration(orchestration_id)
        workflow, prompt_files = self._refresh_bundle_role_snapshots(
            workflow=orchestration.get("workflow_json") or {},
            prompt_files=orchestration.get("prompt_files_json") or {},
            role_definition_ids=[
                str(item).strip()
                for item in (bundle.get("role_definition_ids") or bundle.get("role_definition_ids_json") or [])
                if str(item).strip()
            ],
        )
        resolved = self._asset_call(
            self.asset_catalog.resolve_orchestration_input,
            orchestration_id=orchestration_id,
            workflow=workflow,
            prompt_files=prompt_files,
            role_models=role_models,
        )
        resolved["stored_orchestration"] = orchestration
        resolved["refreshed_workflow"] = workflow
        resolved["refreshed_prompt_files"] = prompt_files
        return resolved

    def _persist_refreshed_bundle_orchestration(self, resolved_orchestration: dict) -> None:
        orchestration = resolved_orchestration.get("stored_orchestration") or {}
        orchestration_id = str(resolved_orchestration.get("id", "") or "").strip()
        if not orchestration_id:
            return
        workflow = resolved_orchestration.get("refreshed_workflow") or {}
        prompt_files = resolved_orchestration.get("refreshed_prompt_files") or {}
        if workflow == orchestration.get("workflow_json") and prompt_files == orchestration.get("prompt_files_json"):
            return
        self._asset_call(
            self.asset_catalog.update_orchestration,
            orchestration_id,
            name=orchestration["name"],
            description=orchestration.get("description", ""),
            workflow=workflow,
            prompt_files=prompt_files,
            role_models=None,
        )

    def _refresh_bundle_role_snapshots(
        self,
        *,
        workflow: dict,
        prompt_files: dict,
        role_definition_ids: list[str],
    ) -> tuple[dict, dict[str, str]]:
        refreshed_workflow = deepcopy(workflow)
        refreshed_prompt_files = dict(prompt_files or {})
        owned_role_ids = {str(item).strip() for item in role_definition_ids if str(item).strip()}
        refreshed_roles = []
        for raw_role in refreshed_workflow.get("roles", []):
            if not isinstance(raw_role, dict):
                refreshed_roles.append(raw_role)
                continue
            role = dict(raw_role)
            role_definition_id = str(role.get("role_definition_id", "") or "").strip()
            if role_definition_id in owned_role_ids:
                definition = self.get_role_definition(role_definition_id)
                for field in ("name", "archetype", "prompt_ref", *ROLE_EXECUTION_FIELDS, *ROLE_POSTURE_FIELDS):
                    role[field] = definition.get(field, "")
                prompt_ref = str(definition.get("prompt_ref", "") or "").strip()
                if prompt_ref:
                    refreshed_prompt_files[prompt_ref] = str(definition.get("prompt_markdown", "") or "")
            refreshed_roles.append(role)
        refreshed_workflow["roles"] = refreshed_roles
        return refreshed_workflow, refreshed_prompt_files

    def _imported_prompt_ref(self, bundle_id: str, role_key: str, archetype: str) -> str:
        normalized_key = "".join(char if char.isalnum() else "-" for char in role_key.lower()).strip("-") or archetype
        return f"bundles/{bundle_id}/{normalized_key}.md"

    def _hydrate_bundle_links(self, bundle: dict) -> dict:
        hydrated = dict(bundle)
        loop_id = str(hydrated.get("loop_id", "") or "").strip()
        orchestration_id = str(hydrated.get("orchestration_id", "") or "").strip()
        role_definition_ids = [str(item).strip() for item in hydrated.get("role_definition_ids_json", []) if str(item).strip()]
        hydrated["role_definition_ids"] = role_definition_ids
        hydrated["managed_dir"] = str(self._bundle_dir(hydrated["id"]))
        hydrated["bundle_yaml_path"] = str(self._bundle_yaml_path(hydrated["id"]))
        if loop_id:
            try:
                hydrated["loop"] = self.get_loop(loop_id)
            except LooporaError:
                hydrated["loop"] = None
        else:
            hydrated["loop"] = None
        if orchestration_id:
            try:
                hydrated["orchestration"] = self.get_orchestration(orchestration_id)
            except LooporaError:
                hydrated["orchestration"] = None
        else:
            hydrated["orchestration"] = None
        role_definitions = []
        for role_definition_id in role_definition_ids:
            try:
                role_definitions.append(self.get_role_definition(role_definition_id))
            except LooporaError:
                continue
        hydrated["role_definitions"] = role_definitions
        return hydrated

    def _bundle_record_for_loop_id(self, loop_id: str) -> dict | None:
        normalized = str(loop_id or "").strip()
        if not normalized:
            return None
        for bundle in self.repository.list_bundles():
            if str(bundle.get("loop_id", "") or "").strip() == normalized:
                return bundle
        return None

    def _bundle_record_for_orchestration_id(self, orchestration_id: str) -> dict | None:
        normalized = str(orchestration_id or "").strip()
        if not normalized:
            return None
        for bundle in self.repository.list_bundles():
            if str(bundle.get("orchestration_id", "") or "").strip() == normalized:
                return bundle
        return None

    def _bundle_record_for_role_definition_id(self, role_definition_id: str) -> dict | None:
        normalized = str(role_definition_id or "").strip()
        if not normalized:
            return None
        for bundle in self.repository.list_bundles():
            role_ids = [
                str(item).strip()
                for item in (bundle.get("role_definition_ids") or bundle.get("role_definition_ids_json") or [])
                if str(item).strip()
            ]
            if normalized in role_ids:
                return bundle
        return None

    def _touch_bundle_for_orchestration(self, orchestration_id: str) -> dict | None:
        bundle = self._bundle_record_for_orchestration_id(orchestration_id)
        if not bundle:
            return None
        return self.update_bundle(bundle["id"], bump_revision=True)

    def _touch_bundle_for_role_definition(self, role_definition_id: str) -> dict | None:
        bundle = self._bundle_record_for_role_definition_id(role_definition_id)
        if not bundle:
            return None
        return self.update_bundle(bundle["id"], bump_revision=True)

    def _delete_bundle_links(
        self,
        bundle: dict,
        *,
        delete_record: bool,
        delete_managed_dir: bool = True,
    ) -> None:
        loop_id = str(bundle.get("loop_id", "") or "").strip()
        orchestration_id = str(bundle.get("orchestration_id", "") or "").strip()
        role_definition_ids = [
            str(item).strip()
            for item in (bundle.get("role_definition_ids") or bundle.get("role_definition_ids_json") or [])
            if str(item).strip()
        ]
        if loop_id:
            try:
                self.delete_loop(loop_id, allow_bundle_owned=True)
            except LooporaError as exc:
                raise LooporaError(f"failed to delete bundle loop {loop_id}: {exc}") from exc
        if orchestration_id:
            try:
                self.delete_orchestration(orchestration_id, allow_bundle_owned=True)
            except LooporaError:
                pass
        for role_definition_id in role_definition_ids:
            try:
                self.delete_role_definition(role_definition_id, allow_bundle_owned=True)
            except LooporaError:
                continue
        bundle_dir = self._bundle_dir(bundle["id"])
        if delete_managed_dir and bundle_dir.exists():
            shutil.rmtree(bundle_dir, ignore_errors=True)
        if delete_record:
            self.repository.delete_bundle(bundle["id"])

    def _sync_bundle_yaml(self, bundle_id: str) -> None:
        self._bundle_yaml_path(bundle_id).parent.mkdir(parents=True, exist_ok=True)
        self._bundle_yaml_path(bundle_id).write_text(self.export_bundle_yaml(bundle_id), encoding="utf-8")
