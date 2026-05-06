from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
import re
import shutil

from loopora.bundles import BundleError, bundle_to_yaml, load_bundle_file, load_bundle_text, normalize_bundle
from loopora.diagnostics import get_logger
from loopora.evidence_coverage import with_coverage_targets
from loopora.markdown_tools import render_safe_markdown_html
from loopora.service_bundle_control_summary import build_bundle_control_summary, preview_list_items
from loopora.service_bundle_graph_preflight import BundleGraphLinks, bundle_graph_links, preflight_bundle_graph_delete
from loopora.service_cleanup_diagnostics import best_effort_rmtree, cleanup_diagnostic_payload, log_cleanup_diagnostic
from loopora.settings import app_home
from loopora.specs import compile_markdown_spec, SpecError
from loopora.service_asset_common import _normalize_role_models
from loopora.service_types import LooporaConflictError, LooporaError, LooporaNotFoundError
from loopora.service_local_asset_diagnostics import build_local_asset_diagnostics
from loopora.utils import make_id
from loopora.utils import write_json
from loopora.workflows import ROLE_EXECUTION_FIELDS, ROLE_POSTURE_FIELDS, has_finish_gatekeeper_step

logger = get_logger(__name__)


@dataclass(frozen=True)
class BundleImportTarget:
    target_bundle_id: str
    existing: dict | None
    old_local_paths: list[Path]
    bundle_dir: Path
    backup_dir: Path | None
    prompt_ref_namespace: str
    imported_from_path: str


@dataclass
class BundleImportRollbackState:
    target: BundleImportTarget
    created_role_ids: list[str] = field(default_factory=list)
    orchestration_id: str = ""
    loop_id: str = ""
    saved: object | None = None
    committed: bool = False


@dataclass(frozen=True)
class BundleDeriveRequest:
    loop_id: str
    bundle_id: str = ""
    name: str | None = None
    description: str = ""
    collaboration_summary: str = ""
    source_bundle_id: str = ""
    revision: int = 1


def _bundle_role_definition_key(value: object) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return normalized or "role"


def _role_snapshot_value(role: dict, role_definition: dict | None, field: str) -> object:
    return role.get(field, "") if field in role else (role_definition or {}).get(field, "")


def _derive_bundle_request_from_args(
    request: BundleDeriveRequest | str,
    raw_request: dict[str, object],
) -> BundleDeriveRequest:
    if isinstance(request, BundleDeriveRequest):
        if raw_request:
            raise TypeError("bundle derive request object cannot be combined with keyword fields")
        return request

    fields = dict(raw_request)
    derive_request = BundleDeriveRequest(
        loop_id=request,
        bundle_id=fields.pop("bundle_id", ""),
        name=fields.pop("name", None),
        description=fields.pop("description", ""),
        collaboration_summary=fields.pop("collaboration_summary", ""),
        source_bundle_id=fields.pop("source_bundle_id", ""),
        revision=fields.pop("revision", 1),
    )
    if fields:
        unexpected_fields = ", ".join(sorted(fields))
        raise TypeError(f"unexpected bundle derive request fields: {unexpected_fields}")
    return derive_request


class ServiceBundleAssetMixin:
    def _bundle_dir(self, bundle_id: str) -> Path:
        return app_home() / "bundles" / bundle_id

    def _bundle_spec_path(self, bundle_id: str) -> Path:
        return self._bundle_dir(bundle_id) / "spec.md"

    def _bundle_yaml_path(self, bundle_id: str) -> Path:
        return self._bundle_dir(bundle_id) / "bundle.yml"

    def list_bundles(self) -> list[dict]:
        return [self._hydrate_bundle_links(bundle) for bundle in self.repository.list_bundles()]

    def local_asset_diagnostics(self) -> dict:
        return build_local_asset_diagnostics(self)

    def list_bundle_governance_cards(self) -> list[dict]:
        cards = []
        for bundle in self.list_bundles():
            try:
                exported_bundle = self.export_bundle(bundle["id"])
                governance_summary = self._bundle_governance_summary(exported_bundle)
            except LooporaError:
                governance_summary = self._empty_bundle_governance_summary()
            cards.append({**bundle, "governance_summary": governance_summary})
        return cards

    def get_bundle(self, bundle_id: str) -> dict:
        bundle = self.repository.get_bundle(bundle_id)
        if not bundle:
            raise LooporaNotFoundError(f"unknown bundle: {bundle_id}")
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

    def preview_bundle_file(self, path: Path) -> dict:
        resolved_path = path.expanduser().resolve()
        try:
            bundle = load_bundle_file(resolved_path)
        except (BundleError, OSError) as exc:
            raise LooporaError(str(exc)) from exc
        return self._bundle_preview_payload(bundle, source_path=str(resolved_path))

    def preview_bundle_text(self, raw_text: str) -> dict:
        try:
            bundle = load_bundle_text(raw_text)
        except BundleError as exc:
            raise LooporaError(str(exc)) from exc
        return self._bundle_preview_payload(bundle)

    def export_bundle(self, bundle_id: str) -> dict:
        bundle = self.get_bundle(bundle_id)
        return self.derive_bundle_from_loop(
            bundle["loop_id"],
            bundle_id=bundle["id"],
            name=bundle["name"],
            description=str(bundle.get("description", "")),
            collaboration_summary=str(bundle.get("collaboration_summary", "")),
        )

    def export_bundle_yaml(self, bundle_id: str) -> str:
        return bundle_to_yaml(self.export_bundle(bundle_id))

    def get_bundle_revision_summary(self, bundle_id: str) -> dict:
        self.get_bundle(bundle_id)
        return self._bundle_revision_summary()

    def get_bundle_governance_summary(self, bundle_id: str) -> dict:
        return self._bundle_governance_summary(self.export_bundle(bundle_id))

    def _bundle_preview_payload(
        self,
        bundle: dict,
        *,
        source_path: str = "",
        validation: dict | None = None,
    ) -> dict:
        normalized_yaml = bundle_to_yaml(bundle)
        return {
            "ok": True,
            "yaml": normalized_yaml,
            "source_path": source_path,
            "bundle": bundle,
            "metadata": bundle["metadata"],
            "spec_rendered_html": render_safe_markdown_html(bundle["spec"]["markdown"]),
            "roles": bundle["role_definitions"],
            "workflow_preview": self._bundle_workflow_preview(bundle),
            "control_summary": self._bundle_control_summary(bundle),
            "validation": validation or {"ok": True, "error": "", "source_path": source_path},
        }

    @staticmethod
    def _bundle_workflow_preview(bundle: dict) -> dict:
        role_by_key = {role["key"]: role for role in bundle["role_definitions"]}
        preview_roles = []
        for role in bundle["workflow"]["roles"]:
            role_definition = role_by_key.get(role["role_definition_key"], {})
            preview_roles.append(
                {
                    **role,
                    "name": role_definition.get("name", role["id"]),
                    "archetype": role_definition.get("archetype", "custom"),
                    "description": role_definition.get("description", ""),
                    "posture_notes": role_definition.get("posture_notes", ""),
                }
            )
        return {
            **bundle["workflow"],
            "roles": preview_roles,
            "steps": list(bundle["workflow"]["steps"]),
        }

    @staticmethod
    def _bundle_control_summary(bundle: dict) -> dict:
        return build_bundle_control_summary(bundle)

    def _bundle_governance_summary(self, bundle: dict) -> dict:
        try:
            compiled_spec = compile_markdown_spec(str(bundle.get("spec", {}).get("markdown") or ""))
        except SpecError:
            compiled_spec = {"raw_sections": {}, "checks": []}
        raw_sections = compiled_spec.get("raw_sections") if isinstance(compiled_spec, dict) else {}
        if not isinstance(raw_sections, dict):
            raw_sections = {}
        control_summary = self._bundle_control_summary(bundle)
        gatekeeper = dict(control_summary.get("gatekeeper") or {})
        evidence_preferences = preview_list_items(str(raw_sections.get("Evidence Preferences") or ""), limit=3)
        if not evidence_preferences:
            evidence_preferences = list(control_summary.get("evidence") or [])[:3]
        return {
            "failure_modes": preview_list_items(
                str(raw_sections.get("Fake Done") or "") + "\n" + str(raw_sections.get("Residual Risk") or ""),
                limit=3,
            ),
            "evidence_style": evidence_preferences,
            "workflow_shape": str((control_summary.get("workflow") or {}).get("summary") or "").strip(),
            "workflow_step_count": int((control_summary.get("workflow") or {}).get("step_count") or 0),
            "parallel_groups": list((control_summary.get("workflow") or {}).get("parallel_groups") or []),
            "gatekeeper": {
                "enabled": bool(gatekeeper.get("enabled")),
                "roles": list(gatekeeper.get("roles") or []),
                "finish_steps": list(gatekeeper.get("finish_steps") or []),
                "strictness": "evidence_refs_required" if gatekeeper.get("enabled") else "not_configured",
            },
        }

    @staticmethod
    def _empty_bundle_governance_summary() -> dict:
        return {
            "failure_modes": [],
            "evidence_style": [],
            "workflow_shape": "",
            "workflow_step_count": 0,
            "parallel_groups": [],
            "gatekeeper": {
                "enabled": False,
                "roles": [],
                "finish_steps": [],
                "strictness": "unavailable",
            },
        }

    @staticmethod
    def _bundle_revision_summary() -> dict:
        return {
            "revision": 1,
            "source_bundle_id": "",
            "source_bundle": None,
            "lineage_state": "not_tracked",
            "can_compare": False,
            "surface_deltas": [],
        }

    def derive_bundle_from_loop(self, request: BundleDeriveRequest | str, **raw_request: object) -> dict:
        request = _derive_bundle_request_from_args(request, raw_request)
        loop_id = request.loop_id
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

            role_definitions.append(
                {
                    "key": _bundle_role_definition_key(role.get("id", "")),
                    "name": str(_role_snapshot_value(role, role_definition, "name") or "").strip(),
                    "description": str((role_definition or {}).get("description", "") or role.get("description", "") or "").strip(),
                    "archetype": str(_role_snapshot_value(role, role_definition, "archetype") or "").strip(),
                    "prompt_ref": prompt_ref,
                    "prompt_markdown": str(prompt_markdown or ""),
                    "posture_notes": str(_role_snapshot_value(role, role_definition, "posture_notes") or "").strip(),
                    "executor_kind": str(_role_snapshot_value(role, role_definition, "executor_kind") or "").strip(),
                    "executor_mode": str(_role_snapshot_value(role, role_definition, "executor_mode") or "").strip(),
                    "command_cli": str(_role_snapshot_value(role, role_definition, "command_cli") or "").strip(),
                    "command_args_text": str(_role_snapshot_value(role, role_definition, "command_args_text") or ""),
                    "model": str(_role_snapshot_value(role, role_definition, "model") or "").strip(),
                    "reasoning_effort": str(_role_snapshot_value(role, role_definition, "reasoning_effort") or "").strip(),
                }
            )

        workflow_bundle = {
            "version": int(workflow.get("version", 1) or 1),
            "preset": str(workflow.get("preset", "") or "").strip(),
            "collaboration_intent": str(workflow.get("collaboration_intent", "") or "").strip(),
            "roles": [
                {
                    "id": str(role.get("id", "") or "").strip(),
                    "role_definition_key": _bundle_role_definition_key(role.get("id", "")),
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
                    "action_policy": deepcopy(step.get("action_policy") or {}),
                    **(
                        {"parallel_group": str(step.get("parallel_group", "") or "").strip()}
                        if str(step.get("parallel_group", "") or "").strip()
                        else {}
                    ),
                    **({"inputs": deepcopy(step.get("inputs"))} if isinstance(step.get("inputs"), dict) and step.get("inputs") else {}),
                }
                for step in workflow.get("steps", [])
            ],
        }
        if workflow.get("controls"):
            workflow_bundle["controls"] = deepcopy(workflow.get("controls") or [])
        bundle = {
            "version": 1,
            "metadata": {
                "bundle_id": request.bundle_id,
                "name": request.name or str(loop.get("name", "") or "").strip() or loop_id,
                "description": request.description,
            },
            "collaboration_summary": (
                request.collaboration_summary or request.description or str(loop.get("name", "") or "").strip()
            ),
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
        bump_revision: bool = True,  # noqa: ARG002 - retained for compatibility; revisions are not tracked.
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
            "source_bundle_id": "",
            "revision": int(bundle.get("revision", 1) or 1),
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
        self._delete_bundle_links(bundle)
        return {"id": bundle_id, "deleted": True}

    def _import_normalized_bundle(
        self,
        bundle: dict,
        *,
        replace_bundle_id: str | None = None,
        imported_from_path: str,
    ) -> dict:
        target = self._prepare_bundle_import_target(
            bundle,
            replace_bundle_id=replace_bundle_id,
            imported_from_path=imported_from_path,
        )
        state = BundleImportRollbackState(target=target)
        try:
            target.bundle_dir.mkdir(parents=True, exist_ok=True)
            spec_path = self._write_imported_bundle_spec(target.target_bundle_id, bundle)
            role_definition_id_by_key = self._create_imported_bundle_roles(
                bundle,
                prompt_ref_namespace=target.prompt_ref_namespace,
                created_role_ids=state.created_role_ids,
            )
            workflow_payload = self._bundle_import_workflow_payload(bundle, role_definition_id_by_key)
            orchestration = self.create_orchestration(
                name=bundle["metadata"]["name"],
                description=bundle["metadata"].get("description", ""),
                workflow=workflow_payload,
                prompt_files=None,
                role_models=None,
            )
            state.orchestration_id = orchestration["id"]
            loop_settings = bundle["loop"]
            loop = self._create_imported_bundle_loop(
                loop_settings,
                spec_path=spec_path,
                orchestration_id=state.orchestration_id,
            )
            state.loop_id = loop["id"]
            payload = self._bundle_import_payload(target, bundle, loop_settings, state)
            self._write_imported_bundle_yaml(target.target_bundle_id, payload, state.loop_id)
            if target.existing:
                state.saved = self.repository.replace_bundle_graph(target.target_bundle_id, payload)
                state.saved = self.repository.get_bundle(target.target_bundle_id) if state.saved else None
            else:
                state.saved = self.repository.create_bundle(payload)
            if not state.saved:
                raise LooporaError(f"failed to persist bundle: {target.target_bundle_id}")
            if target.existing:
                self._delete_replaced_bundle_artifact_paths(target.target_bundle_id, target.old_local_paths)
            state.committed = True
            return self.get_bundle(state.saved["id"])
        except Exception:
            self._rollback_failed_bundle_import(state)
            raise
        finally:
            self._cleanup_bundle_import_backup_dir(target)

    def _prepare_bundle_import_target(
        self,
        bundle: dict,
        *,
        replace_bundle_id: str | None,
        imported_from_path: str,
    ) -> BundleImportTarget:
        target_bundle_id = str(replace_bundle_id or bundle["metadata"].get("bundle_id") or make_id("bundle")).strip()
        existing = self.repository.get_bundle(target_bundle_id)
        if existing and not replace_bundle_id:
            raise LooporaConflictError(f"bundle already exists: {target_bundle_id}")
        old_local_paths = self._preflight_existing_bundle_graph(existing) if existing else []
        bundle_dir = self._bundle_dir(target_bundle_id)
        backup_dir = self._backup_bundle_dir(bundle_dir) if existing else None
        prompt_ref_namespace = target_bundle_id if not existing else f"{target_bundle_id}/{make_id('replace')}"
        return BundleImportTarget(
            target_bundle_id=target_bundle_id,
            existing=existing,
            old_local_paths=old_local_paths,
            bundle_dir=bundle_dir,
            backup_dir=backup_dir,
            prompt_ref_namespace=prompt_ref_namespace,
            imported_from_path=imported_from_path,
        )

    def _bundle_import_payload(
        self,
        target: BundleImportTarget,
        bundle: dict,
        loop_settings: dict,
        state: BundleImportRollbackState,
    ) -> dict:
        return {
            "id": target.target_bundle_id,
            "name": bundle["metadata"]["name"],
            "description": bundle["metadata"].get("description", ""),
            "collaboration_summary": bundle["collaboration_summary"],
            "workdir": loop_settings["workdir"],
            "loop_id": state.loop_id,
            "orchestration_id": state.orchestration_id,
            "role_definition_ids": state.created_role_ids,
            "source_bundle_id": "",
            "revision": int((target.existing or {}).get("revision", 1) or 1) if target.existing else 1,
            "imported_from_path": target.imported_from_path,
        }

    def _rollback_failed_bundle_import(self, state: BundleImportRollbackState) -> None:
        if state.committed:
            return
        target = state.target
        if state.saved is not None:
            if target.existing:
                self.repository.update_bundle(target.target_bundle_id, self._bundle_payload_from_record(target.existing))
            else:
                self.repository.delete_bundle(target.target_bundle_id)
        self._cleanup_created_bundle_assets(
            owner_id=target.target_bundle_id,
            loop_id=state.loop_id,
            orchestration_id=state.orchestration_id,
            role_definition_ids=state.created_role_ids,
        )
        self._restore_bundle_dir_after_failed_import(
            bundle_dir=target.bundle_dir,
            backup_dir=target.backup_dir,
            had_existing=bool(target.existing),
        )

    def _cleanup_bundle_import_backup_dir(self, target: BundleImportTarget) -> None:
        if not target.backup_dir or not target.backup_dir.exists():
            return
        try:
            shutil.rmtree(target.backup_dir)
        except OSError as exc:
            self._record_bundle_cleanup_failure(
                operation="bundle_backup_cleanup",
                resource_type="path",
                resource_id=target.backup_dir,
                owner_id=target.target_bundle_id,
                error=exc,
            )

    def _write_imported_bundle_spec(self, target_bundle_id: str, bundle: dict) -> Path:
        spec_path = self._bundle_spec_path(target_bundle_id)
        spec_path.write_text(str(bundle["spec"]["markdown"]), encoding="utf-8")
        return spec_path

    def _create_imported_bundle_roles(
        self,
        bundle: dict,
        *,
        prompt_ref_namespace: str,
        created_role_ids: list[str],
    ) -> dict[str, str]:
        role_definition_id_by_key: dict[str, str] = {}
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
        return role_definition_id_by_key

    @staticmethod
    def _bundle_import_workflow_payload(bundle: dict, role_definition_id_by_key: dict[str, str]) -> dict:
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
        if bundle["workflow"].get("controls"):
            workflow_payload["controls"] = deepcopy(bundle["workflow"].get("controls") or [])
        return workflow_payload

    def _create_imported_bundle_loop(self, loop_settings: dict, *, spec_path: Path, orchestration_id: str) -> dict:
        return self.create_loop(
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

    def _write_imported_bundle_yaml(self, target_bundle_id: str, payload: dict, loop_id: str) -> None:
        export_payload = self.derive_bundle_from_loop(
            loop_id,
            bundle_id=target_bundle_id,
            name=payload["name"],
            description=payload["description"],
            collaboration_summary=payload["collaboration_summary"],
        )
        self._bundle_yaml_path(target_bundle_id).write_text(bundle_to_yaml(export_payload), encoding="utf-8")

    def _delete_replaced_bundle_artifact_paths(self, target_bundle_id: str, old_local_paths: list[Path]) -> None:
        for path in old_local_paths:
            best_effort_rmtree(
                path,
                logger,
                operation="bundle_replaced_artifact_delete",
                owner_id=target_bundle_id,
            )
            self._mark_local_asset_cleanup_by_path(
                path,
                operation="bundle_replaced_artifact_delete",
                owner_id=target_bundle_id,
            )

    def _assert_bundle_links_replaceable(self, bundle: dict) -> None:
        self._preflight_existing_bundle_graph(bundle)

    def _preflight_existing_bundle_graph(self, bundle: dict) -> list[Path]:
        return self._preflight_bundle_graph_delete(bundle, links=bundle_graph_links(bundle))

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
            best_effort_rmtree(
                bundle_dir,
                logger,
                operation="bundle_failed_import_restore",
                owner_id=bundle_dir.name,
            )
            try:
                shutil.copytree(backup_dir, bundle_dir)
            except OSError as exc:
                self._record_bundle_cleanup_failure(
                    operation="bundle_failed_import_restore",
                    resource_type="path",
                    resource_id=bundle_dir,
                    owner_id=bundle_dir.name,
                    error=exc,
                )
            return
        best_effort_rmtree(
            bundle_dir,
            logger,
            operation="bundle_failed_import_cleanup",
            owner_id=bundle_dir.name,
        )
        self._mark_local_asset_cleanup_by_path(
            bundle_dir,
            operation="bundle_failed_import_cleanup",
            owner_id=bundle_dir.name,
        )

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
        owner_id: str,
        loop_id: str,
        orchestration_id: str,
        role_definition_ids: list[str],
    ) -> None:
        if loop_id:
            try:
                self.delete_loop(loop_id, allow_bundle_owned=True)
            except Exception as exc:  # noqa: BLE001 - rollback cleanup must preserve the original import failure.
                self._record_bundle_cleanup_failure(
                    operation="bundle_import_rollback",
                    resource_type="loop",
                    resource_id=loop_id,
                    owner_id=owner_id,
                    error=exc,
                )
        if orchestration_id:
            try:
                self.delete_orchestration(orchestration_id, allow_bundle_owned=True)
            except Exception as exc:  # noqa: BLE001 - rollback cleanup must preserve the original import failure.
                self._record_bundle_cleanup_failure(
                    operation="bundle_import_rollback",
                    resource_type="orchestration",
                    resource_id=orchestration_id,
                    owner_id=owner_id,
                    error=exc,
                )
        for role_definition_id in role_definition_ids:
            try:
                self.delete_role_definition(role_definition_id, allow_bundle_owned=True)
            except Exception as exc:  # noqa: BLE001 - rollback cleanup must preserve the original import failure.
                self._record_bundle_cleanup_failure(
                    operation="bundle_import_rollback",
                    resource_type="role_definition",
                    resource_id=role_definition_id,
                    owner_id=owner_id,
                    error=exc,
                )
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
            raise LooporaNotFoundError(f"unknown bundle: {bundle_id}")
        loop_id = str(bundle.get("loop_id", "") or "").strip()
        if not loop_id:
            return None
        loop = self.repository.get_loop(loop_id)
        if not loop:
            raise LooporaNotFoundError(f"unknown bundle loop: {loop_id}")

        spec_path = self._bundle_spec_path(bundle_id)
        if spec_markdown is None:
            if not spec_path.exists():
                raise LooporaError(f"bundle spec does not exist: {spec_path}")
            effective_spec_markdown, compiled_spec = self._read_and_compile_spec(spec_path)
        else:
            effective_spec_markdown = str(spec_markdown or "").strip() + "\n"
            compiled_spec = compile_markdown_spec(effective_spec_markdown)
        compiled_spec = with_coverage_targets(
            compiled_spec,
            completion_mode=str(loop.get("completion_mode", "gatekeeper")),
        )
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
        return self.update_bundle(bundle["id"])

    def _touch_bundle_for_role_definition(self, role_definition_id: str) -> dict | None:
        bundle = self._bundle_record_for_role_definition_id(role_definition_id)
        if not bundle:
            return None
        return self.update_bundle(bundle["id"])

    def _delete_bundle_links(
        self,
        bundle: dict,
        *,
        delete_managed_dir: bool = True,
    ) -> None:
        links = bundle_graph_links(bundle)
        local_paths = self._preflight_bundle_graph_delete(bundle, links=links)
        deleted = self.repository.delete_bundle_graph(bundle["id"])
        if not deleted:
            raise LooporaError(f"failed to delete bundle: {bundle['id']}")
        self._delete_bundle_link_artifact_paths(bundle["id"], local_paths)
        self._delete_bundle_managed_dir(bundle["id"], delete_managed_dir=delete_managed_dir)

    def _delete_bundle_link_artifact_paths(self, bundle_id: str, local_paths: list[Path]) -> None:
        for path in local_paths:
            best_effort_rmtree(
                path,
                logger,
                operation="bundle_link_artifact_delete",
                owner_id=bundle_id,
            )
            self._mark_local_asset_cleanup_by_path(
                path,
                operation="bundle_link_artifact_delete",
                owner_id=bundle_id,
            )

    def _delete_bundle_managed_dir(self, bundle_id: str, *, delete_managed_dir: bool) -> None:
        if not delete_managed_dir:
            return
        bundle_dir = self._bundle_dir(bundle_id)
        if bundle_dir.exists():
            best_effort_rmtree(
                bundle_dir,
                logger,
                operation="bundle_managed_dir_delete",
                owner_id=bundle_id,
            )
        self._mark_local_asset_cleanup_by_path(
            bundle_dir,
            operation="bundle_managed_dir_delete",
            owner_id=bundle_id,
        )

    def _preflight_bundle_graph_delete(
        self,
        bundle: dict,
        *,
        links: BundleGraphLinks,
    ) -> list[Path]:
        return preflight_bundle_graph_delete(self.repository, bundle, links)

    def _sync_bundle_yaml(self, bundle_id: str) -> None:
        self._bundle_yaml_path(bundle_id).parent.mkdir(parents=True, exist_ok=True)
        self._bundle_yaml_path(bundle_id).write_text(self.export_bundle_yaml(bundle_id), encoding="utf-8")

    @staticmethod
    def _record_bundle_cleanup_failure(
        *,
        operation: str,
        resource_type: str,
        resource_id: object,
        owner_id: object,
        error: BaseException,
    ) -> None:
        payload = cleanup_diagnostic_payload(
            operation=operation,
            resource_type=resource_type,
            resource_id=resource_id,
            owner_id=owner_id,
            error=error,
        )
        log_cleanup_diagnostic(logger, **payload)
