from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
import re

from loopora.db import LooporaRepository
from loopora.utils import make_id
from loopora.workflows import (
    ARCHETYPES,
    ROLE_EXECUTION_FIELDS,
    ROLE_POSTURE_FIELDS,
    WorkflowError,
    build_preset_workflow,
    builtin_prompt_markdown,
    default_role_execution_settings,
    display_name_for_archetype,
    normalize_role_execution_settings,
    normalize_archetype,
    normalize_prompt_ref,
    normalize_workflow,
    preset_names,
    resolve_prompt_files,
    validate_prompt_markdown,
    workflow_preset_copy,
    workflow_warnings,
)


class AssetCatalogError(ValueError):
    """Base error for workflow asset catalog validation failures."""


class AssetCatalogNotFoundError(AssetCatalogError):
    """Raised when a stable role definition or orchestration asset is missing."""


@dataclass(frozen=True, kw_only=True)
class RoleDefinitionPayloadInput:
    name: str
    archetype: str
    prompt_markdown: str
    description: str = ""
    posture_notes: str = ""
    prompt_ref: str = ""
    executor_kind: str = "codex"
    executor_mode: str = "preset"
    command_cli: str = ""
    command_args_text: str = ""
    model: str = ""
    reasoning_effort: str = ""
    role_definition_id: str = ""
    existing_prompt_ref: str = ""


@dataclass(frozen=True)
class RoleSnapshotDefinition:
    role: dict
    definition: dict
    role_definition_id: str
    role_label: str


@dataclass(frozen=True, kw_only=True)
class OrchestrationPayloadInput:
    name: str
    description: str = ""
    workflow: dict | None = None
    prompt_files: dict | None = None
    role_models: dict | None = None


def _required_role_definition_field(fields: dict[str, object], field: str) -> object:
    try:
        return fields.pop(field)
    except KeyError as exc:
        raise TypeError(f"missing role definition field: {field}") from exc


def _role_definition_payload_input_from_args(
    request: RoleDefinitionPayloadInput | None,
    raw_payload: dict[str, object],
    *,
    role_definition_id: str,
    existing_prompt_ref: str = "",
) -> RoleDefinitionPayloadInput:
    if request is not None:
        if raw_payload:
            raise TypeError("role definition request object cannot be combined with keyword fields")
        return replace(
            request,
            role_definition_id=role_definition_id,
            existing_prompt_ref=existing_prompt_ref,
        )

    fields = dict(raw_payload)
    payload_input = RoleDefinitionPayloadInput(
        name=_required_role_definition_field(fields, "name"),
        archetype=_required_role_definition_field(fields, "archetype"),
        prompt_markdown=_required_role_definition_field(fields, "prompt_markdown"),
        description=fields.pop("description", ""),
        posture_notes=fields.pop("posture_notes", ""),
        prompt_ref=fields.pop("prompt_ref", ""),
        executor_kind=fields.pop("executor_kind", "codex"),
        executor_mode=fields.pop("executor_mode", "preset"),
        command_cli=fields.pop("command_cli", ""),
        command_args_text=fields.pop("command_args_text", ""),
        model=fields.pop("model", ""),
        reasoning_effort=fields.pop("reasoning_effort", ""),
        role_definition_id=role_definition_id,
        existing_prompt_ref=existing_prompt_ref,
    )
    if fields:
        unexpected_fields = ", ".join(sorted(fields))
        raise TypeError(f"unexpected role definition fields: {unexpected_fields}")
    return payload_input


def _orchestration_payload_input_from_args(
    request: OrchestrationPayloadInput | None,
    raw_payload: dict[str, object],
) -> OrchestrationPayloadInput:
    if request is not None:
        if raw_payload:
            raise TypeError("orchestration request object cannot be combined with keyword fields")
        return request

    fields = dict(raw_payload)
    try:
        name = fields.pop("name")
    except KeyError as exc:
        raise TypeError("missing orchestration field: name") from exc
    payload_input = OrchestrationPayloadInput(
        name=name,
        description=fields.pop("description", ""),
        workflow=fields.pop("workflow", None),
        prompt_files=fields.pop("prompt_files", None),
        role_models=fields.pop("role_models", None),
    )
    if fields:
        unexpected_fields = ", ".join(sorted(fields))
        raise TypeError(f"unexpected orchestration fields: {unexpected_fields}")
    return payload_input


def _workflow_parallel_groups(workflow: dict | None) -> list[str]:
    if not isinstance(workflow, dict):
        return []
    counts: dict[str, int] = {}
    for step in list(workflow.get("steps") or []):
        if not isinstance(step, dict):
            continue
        group = str(step.get("parallel_group") or "").strip()
        if group:
            counts[group] = counts.get(group, 0) + 1
    return [group for group, count in counts.items() if count >= 2]


class WorkflowAssetCatalog:
    """Owns orchestration and role-definition asset records."""

    def __init__(self, repository: LooporaRepository) -> None:
        self.repository = repository
        self._builtin_orchestrations = self._build_builtin_orchestration_records()
        self._builtin_role_definitions = self._build_builtin_role_definition_records()

    def _clone_records(self, records: list[dict]) -> list[dict]:
        return [deepcopy(record) for record in records]

    def _build_builtin_orchestration_records(self) -> list[dict]:
        records = []
        for preset_name in preset_names(include_hidden=True):
            workflow = build_preset_workflow(preset_name)
            prompt_files = resolve_prompt_files(workflow)
            copy = workflow_preset_copy(preset_name)
            parallel_groups = _workflow_parallel_groups(workflow)
            records.append(
                {
                    "id": f"builtin:{preset_name}",
                    "name": copy["label_en"],
                    "description": copy["description_en"],
                    "description_zh": copy["description_zh"],
                    "description_en": copy["description_en"],
                    "scenario_zh": copy["scenario_zh"],
                    "scenario_en": copy["scenario_en"],
                    "choice_zh": copy["choice_zh"],
                    "choice_en": copy["choice_en"],
                    "decision_zh": copy["decision_zh"],
                    "decision_en": copy["decision_en"],
                    "spec_practice_summary_zh": copy["spec_practice_summary_zh"],
                    "spec_practice_summary_en": copy["spec_practice_summary_en"],
                    "spec_practice_markdown_zh": copy["spec_practice_markdown_zh"],
                    "spec_practice_markdown_en": copy["spec_practice_markdown_en"],
                    "visible": copy["visible"] == "true",
                    "source": "builtin",
                    "preset": preset_name,
                    "editable": False,
                    "deletable": False,
                    "workflow_json": workflow,
                    "parallel_groups": parallel_groups,
                    "parallel_group_count": len(parallel_groups),
                    "prompt_files_json": prompt_files,
                    "workflow_warnings": workflow_warnings(workflow),
                }
            )
        return records

    def _build_builtin_role_definition_records(self) -> list[dict]:
        descriptions = {
            "builder": "Edits the workspace and pushes implementation forward.",
            "inspector": "Collects evidence, checks, and benchmark results.",
            "gatekeeper": "Decides whether the evidence is strong enough to pass.",
            "guide": "Suggests the next direction when progress stalls.",
            "custom": "A low-permission custom support role that can read, analyze, and recommend, but cannot close the run.",
        }
        records = []
        for archetype in ARCHETYPES:
            prompt_ref = {
                "gatekeeper": "gatekeeper.md",
            }.get(archetype, f"{archetype}.md")
            default_name = display_name_for_archetype(archetype, locale="en")
            if archetype == "custom":
                default_name = "Custom (Restricted)"
            records.append(
                {
                    "id": f"builtin:{archetype}",
                    "name": default_name,
                    "description": descriptions.get(archetype, ""),
                    "archetype": archetype,
                    "prompt_ref": prompt_ref,
                    "prompt_markdown": builtin_prompt_markdown(prompt_ref),
                    "posture_notes": "",
                    **default_role_execution_settings(),
                    "source": "builtin",
                    "editable": False,
                    "deletable": False,
                }
            )
        return records

    @staticmethod
    def _auto_prompt_ref(*, name: str, archetype: str, role_definition_id: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", str(name).strip().lower()).strip("-")
        if not slug:
            slug = archetype
        suffix = str(role_definition_id).split("_")[-1]
        return f"{slug}-{suffix}.md"

    def _decorate_orchestration(self, record: dict, *, source: str) -> dict:
        decorated = dict(record)
        decorated["prompt_files_json"] = self._sanitize_persisted_prompt_files(decorated.get("prompt_files_json"))
        decorated["source"] = source
        decorated["editable"] = source == "custom"
        decorated["deletable"] = source == "custom"
        decorated["workflow_warnings"] = workflow_warnings(decorated.get("workflow_json") or {})
        decorated["parallel_groups"] = _workflow_parallel_groups(decorated.get("workflow_json"))
        decorated["parallel_group_count"] = len(decorated["parallel_groups"])
        return decorated

    def _decorate_role_definition(self, record: dict, *, source: str) -> dict:
        decorated = dict(record)
        decorated["source"] = source
        decorated["editable"] = source == "custom"
        decorated["deletable"] = source == "custom"
        return decorated

    @staticmethod
    def _canonical_role_snapshot_field(field: str, value: object) -> object:
        if field == "archetype":
            return normalize_archetype(str(value or ""))
        if field == "prompt_ref":
            raw_prompt_ref = str(value or "").strip()
            return normalize_prompt_ref(raw_prompt_ref) if raw_prompt_ref else ""
        if field == "command_args_text":
            return str(value or "")
        return str(value or "").strip()

    @staticmethod
    def _canonical_prompt_markdown(markdown: object) -> str:
        return str(markdown or "").replace("\r\n", "\n").replace("\r", "\n").strip()

    @staticmethod
    def _sanitize_persisted_prompt_files(prompt_files: object) -> dict[str, str]:
        sanitized: dict[str, str] = {}
        for prompt_ref, markdown_text in dict(prompt_files or {}).items():
            candidate = str(prompt_ref).strip()
            if not candidate:
                continue
            try:
                normalized_prompt_ref = normalize_prompt_ref(candidate)
            except WorkflowError:
                continue
            sanitized[normalized_prompt_ref] = str(markdown_text or "")
        return sanitized

    def _hydrate_workflow_role_snapshots(
        self,
        workflow: dict | None,
        prompt_files: dict | None,
    ) -> tuple[dict | None, dict[str, str] | None]:
        if workflow is None:
            return None, dict(prompt_files or {}) if prompt_files is not None else None

        hydrated_workflow = deepcopy(workflow)
        raw_roles = hydrated_workflow.get("roles")
        if not isinstance(raw_roles, list):
            return hydrated_workflow, dict(prompt_files or {}) if prompt_files is not None else None

        hydrated_prompt_files = dict(prompt_files or {})
        hydrated_workflow["roles"] = self._hydrate_workflow_roles(raw_roles, hydrated_prompt_files)
        return hydrated_workflow, hydrated_prompt_files


    def _hydrate_workflow_roles(
        self,
        raw_roles: list,
        hydrated_prompt_files: dict[str, str],
    ) -> list[object]:
        return [
            self._hydrate_workflow_role_snapshot(raw_role, hydrated_prompt_files=hydrated_prompt_files)
            for raw_role in raw_roles
        ]

    def _hydrate_workflow_role_snapshot(
        self,
        raw_role: object,
        *,
        hydrated_prompt_files: dict[str, str],
    ) -> object:
        if not isinstance(raw_role, dict):
            return raw_role
        role = dict(raw_role)
        role_definition_id = str(role.get("role_definition_id", "")).strip()
        if not role_definition_id:
            return role

        snapshot = self._role_snapshot_definition(role, role_definition_id=role_definition_id)
        self._hydrate_role_snapshot_fields(snapshot)
        self._hydrate_role_prompt_file(snapshot, hydrated_prompt_files=hydrated_prompt_files)
        return role

    def _role_snapshot_definition(self, role: dict, *, role_definition_id: str) -> RoleSnapshotDefinition:
        return RoleSnapshotDefinition(
            role=role,
            definition=self.get_role_definition(role_definition_id),
            role_definition_id=role_definition_id,
            role_label=str(role.get("id", "")).strip() or role_definition_id,
        )

    def _hydrate_role_snapshot_fields(self, snapshot: RoleSnapshotDefinition) -> None:
        for field in ("archetype", "prompt_ref", *ROLE_EXECUTION_FIELDS):
            self._hydrate_role_snapshot_field(snapshot, field=field)
        if "name" not in snapshot.role:
            snapshot.role["name"] = snapshot.definition.get("name", "")
        for field in ROLE_POSTURE_FIELDS:
            if field not in snapshot.role:
                snapshot.role[field] = snapshot.definition.get(field, "")

    def _hydrate_role_snapshot_field(self, snapshot: RoleSnapshotDefinition, *, field: str) -> None:
        if field in snapshot.role:
            provided_value = self._canonical_role_snapshot_field(field, snapshot.role.get(field))
            expected_value = self._canonical_role_snapshot_field(field, snapshot.definition.get(field))
            if provided_value != expected_value:
                raise WorkflowError(
                    f"workflow role {snapshot.role_label} conflicts with role_definition_id "
                    f"{snapshot.role_definition_id} on {field}"
                )
        if field not in snapshot.role:
            snapshot.role[field] = snapshot.definition.get(field, "")

    def _hydrate_role_prompt_file(
        self,
        snapshot: RoleSnapshotDefinition,
        *,
        hydrated_prompt_files: dict[str, str],
    ) -> None:
        prompt_ref = str(snapshot.role.get("prompt_ref", "")).strip()
        if not prompt_ref:
            return
        prompt_markdown = str(snapshot.definition.get("prompt_markdown", ""))
        if prompt_ref not in hydrated_prompt_files:
            if prompt_markdown:
                hydrated_prompt_files[prompt_ref] = prompt_markdown
            return
        provided_prompt_markdown = hydrated_prompt_files[prompt_ref]
        if prompt_markdown and self._canonical_prompt_markdown(provided_prompt_markdown) != self._canonical_prompt_markdown(prompt_markdown):
            raise WorkflowError(
                f"workflow role {snapshot.role_label} conflicts with role_definition_id "
                f"{snapshot.role_definition_id} on prompt_markdown"
            )

    def _normalize_role_definition_payload(self, payload_input: RoleDefinitionPayloadInput) -> dict:
        normalized = {
            "name": str(payload_input.name).strip(),
            "description": str(payload_input.description).strip(),
            "prompt_markdown": str(payload_input.prompt_markdown),
            "posture_notes": str(payload_input.posture_notes or "").strip(),
        }
        if not normalized["name"]:
            raise ValueError("name is required")
        normalized["archetype"] = normalize_archetype(payload_input.archetype)
        resolved_prompt_ref = (
            str(payload_input.prompt_ref).strip()
            or str(payload_input.existing_prompt_ref).strip()
            or self._auto_prompt_ref(
                name=normalized["name"],
                archetype=normalized["archetype"],
                role_definition_id=payload_input.role_definition_id,
            )
        )
        normalized["prompt_ref"] = normalize_prompt_ref(resolved_prompt_ref)
        validate_prompt_markdown(normalized["prompt_markdown"], expected_archetype=normalized["archetype"])
        normalized.update(
            normalize_role_execution_settings(
                {
                    "executor_kind": payload_input.executor_kind,
                    "executor_mode": payload_input.executor_mode,
                    "command_cli": payload_input.command_cli,
                    "command_args_text": payload_input.command_args_text,
                    "model": payload_input.model,
                    "reasoning_effort": payload_input.reasoning_effort,
                }
            )
        )
        return normalized

    def _ensure_unique_role_definition_prompt_ref(
        self,
        prompt_ref: str,
        *,
        exclude_role_definition_id: str = "",
    ) -> None:
        try:
            normalized_prompt_ref = normalize_prompt_ref(prompt_ref)
        except WorkflowError as exc:
            raise ValueError(str(exc)) from exc
        excluded_id = str(exclude_role_definition_id or "").strip()
        for record in self._builtin_role_definitions:
            if record["id"] != excluded_id and str(record.get("prompt_ref", "")).strip() == normalized_prompt_ref:
                raise ValueError(f"prompt_ref already in use: {normalized_prompt_ref}")
        for record in self.repository.list_role_definitions():
            if record["id"] != excluded_id and str(record.get("prompt_ref", "")).strip() == normalized_prompt_ref:
                raise ValueError(f"prompt_ref already in use: {normalized_prompt_ref}")

    def list_role_definitions(self) -> list[dict]:
        custom_records = [
            self._decorate_role_definition(record, source="custom")
            for record in self.repository.list_role_definitions()
        ]
        return custom_records + self._clone_records(self._builtin_role_definitions)

    def get_role_definition(self, role_definition_id: str) -> dict:
        definition_key = str(role_definition_id or "").strip()
        if not definition_key:
            raise ValueError("role_definition_id is required")
        if definition_key.startswith("builtin:"):
            for record in self._builtin_role_definitions:
                if record["id"] == definition_key:
                    return deepcopy(record)
            raise AssetCatalogNotFoundError(f"unknown built-in role definition: {definition_key}")
        record = self.repository.get_role_definition(definition_key)
        if not record:
            raise AssetCatalogNotFoundError(f"unknown role definition: {definition_key}")
        return self._decorate_role_definition(record, source="custom")

    def create_role_definition(
        self,
        request: RoleDefinitionPayloadInput | None = None,
        **raw_payload: object,
    ) -> dict:
        role_definition_id = make_id("role")
        payload_input = _role_definition_payload_input_from_args(
            request,
            raw_payload,
            role_definition_id=role_definition_id,
        )
        payload = self._normalize_role_definition_payload(payload_input)
        self._ensure_unique_role_definition_prompt_ref(payload["prompt_ref"])
        role_definition = self.repository.create_role_definition(
            {
                "id": role_definition_id,
                **payload,
            }
        )
        return self._decorate_role_definition(role_definition, source="custom")

    def update_role_definition(
        self,
        role_definition_id: str,
        request: RoleDefinitionPayloadInput | None = None,
        **raw_payload: object,
    ) -> dict:
        existing = self.get_role_definition(role_definition_id)
        if existing.get("source") == "builtin":
            raise ValueError("built-in role definitions cannot be updated in place")
        existing_prompt_ref = str(existing.get("prompt_ref", "")).strip()
        payload_input = _role_definition_payload_input_from_args(
            request,
            raw_payload,
            role_definition_id=role_definition_id,
            existing_prompt_ref=existing_prompt_ref,
        )
        normalized_archetype = normalize_archetype(payload_input.archetype)
        if normalized_archetype != str(existing.get("archetype", "")).strip():
            raise ValueError("saved role definitions cannot change archetype")
        normalized_prompt_ref = str(payload_input.prompt_ref).strip() or existing_prompt_ref
        if normalized_prompt_ref != existing_prompt_ref:
            raise ValueError("saved role definitions cannot change prompt_ref")
        payload = self._normalize_role_definition_payload(
            replace(
                payload_input,
                archetype=normalized_archetype,
                prompt_ref=normalized_prompt_ref,
            )
        )
        self._ensure_unique_role_definition_prompt_ref(
            payload["prompt_ref"],
            exclude_role_definition_id=role_definition_id,
        )
        updated = self.repository.update_role_definition(role_definition_id, payload)
        if not updated:
            raise AssetCatalogNotFoundError(f"unknown role definition: {role_definition_id}")
        return self._decorate_role_definition(updated, source="custom")

    def delete_role_definition(self, role_definition_id: str) -> dict:
        existing = self.get_role_definition(role_definition_id)
        if existing.get("source") == "builtin":
            raise ValueError("built-in role definitions cannot be deleted")
        if not self.repository.delete_role_definition(role_definition_id):
            raise AssetCatalogNotFoundError(f"unknown role definition: {role_definition_id}")
        return {"id": role_definition_id, "deleted": True}

    def list_orchestrations(self) -> list[dict]:
        custom_records = [
            self._decorate_orchestration(record, source="custom")
            for record in self.repository.list_orchestrations()
        ]
        builtin_records = [
            record
            for record in self._builtin_orchestrations
            if bool(record.get("visible", True))
        ]
        return self._clone_records(builtin_records) + custom_records

    def get_orchestration(self, orchestration_id: str) -> dict:
        orchestration_key = str(orchestration_id or "").strip()
        if not orchestration_key:
            raise ValueError("orchestration_id is required")
        if orchestration_key.startswith("builtin:"):
            for record in self._builtin_orchestrations:
                if record["id"] == orchestration_key:
                    return deepcopy(record)
            raise AssetCatalogNotFoundError(f"unknown built-in orchestration: {orchestration_key.split(':', 1)[1]}")
        record = self.repository.get_orchestration(orchestration_key)
        if not record:
            raise AssetCatalogNotFoundError(f"unknown orchestration: {orchestration_key}")
        return self._decorate_orchestration(record, source="custom")

    def resolve_orchestration_input(
        self,
        *,
        orchestration_id: str | None,
        workflow: dict | None,
        prompt_files: dict | None,
        role_models: dict | None,
    ) -> dict:
        if orchestration_id and workflow is None and not prompt_files:
            orchestration = self.get_orchestration(orchestration_id)
            hydrated_workflow, hydrated_prompt_files = self._hydrate_workflow_role_snapshots(
                orchestration["workflow_json"],
                orchestration.get("prompt_files_json") or {},
            )
            normalized_workflow = normalize_workflow(hydrated_workflow, role_models=role_models)
            resolved_prompt_files = resolve_prompt_files(
                normalized_workflow,
                hydrated_prompt_files,
            )
            return {
                "id": orchestration["id"],
                "name": orchestration["name"],
                "workflow": normalized_workflow,
                "prompt_files": resolved_prompt_files,
            }

        hydrated_workflow, hydrated_prompt_files = self._hydrate_workflow_role_snapshots(workflow, prompt_files)
        normalized_workflow = normalize_workflow(hydrated_workflow, role_models=role_models)
        resolved_prompt_files = resolve_prompt_files(normalized_workflow, hydrated_prompt_files)
        derived_id = str(orchestration_id or "").strip()
        derived_name = ""
        if derived_id:
            try:
                derived_name = self.get_orchestration(derived_id)["name"]
            except AssetCatalogNotFoundError:
                derived_name = ""
        if not derived_id and normalized_workflow.get("preset"):
            derived_id = f"builtin:{normalized_workflow['preset']}"
            derived_name = next(
                (
                    record["name"]
                    for record in self._builtin_orchestrations
                    if record["id"] == derived_id
                ),
                normalized_workflow["preset"],
            )
        return {
            "id": derived_id,
            "name": derived_name,
            "workflow": normalized_workflow,
            "prompt_files": resolved_prompt_files,
        }

    def create_orchestration(
        self,
        *,
        name: str,
        description: str = "",
        workflow: dict | None = None,
        prompt_files: dict | None = None,
        role_models: dict | None = None,
    ) -> dict:
        normalized_name = str(name or "").strip()
        if not normalized_name:
            raise ValueError("name is required")
        resolved = self.resolve_orchestration_input(
            orchestration_id=None,
            workflow=workflow,
            prompt_files=prompt_files,
            role_models=role_models,
        )
        orchestration = self.repository.create_orchestration(
            {
                "id": make_id("orch"),
                "name": normalized_name,
                "description": str(description or "").strip(),
                "workflow": resolved["workflow"],
                "prompt_files": resolved["prompt_files"],
            }
        )
        return self._decorate_orchestration(orchestration, source="custom")

    def update_orchestration(
        self,
        orchestration_id: str,
        request: OrchestrationPayloadInput | None = None,
        **raw_payload: object,
    ) -> dict:
        current = self.get_orchestration(orchestration_id)
        if current.get("source") == "builtin":
            raise ValueError("built-in orchestrations cannot be updated")
        payload_input = _orchestration_payload_input_from_args(request, raw_payload)
        normalized_name = str(payload_input.name or "").strip()
        if not normalized_name:
            raise ValueError("name is required")
        current_workflow = deepcopy(current.get("workflow_json") or {})
        current_prompt_files = dict(current.get("prompt_files_json") or {})
        effective_workflow = payload_input.workflow if payload_input.workflow is not None else current_workflow
        effective_prompt_files = dict(current_prompt_files)
        effective_prompt_files.update(dict(payload_input.prompt_files or {}))
        resolved = self.resolve_orchestration_input(
            orchestration_id=None,
            workflow=effective_workflow,
            prompt_files=effective_prompt_files,
            role_models=payload_input.role_models,
        )
        orchestration = self.repository.update_orchestration(
            orchestration_id,
            {
                "name": normalized_name,
                "description": str(payload_input.description or "").strip(),
                "workflow": resolved["workflow"],
                "prompt_files": resolved["prompt_files"],
            },
        )
        if not orchestration:
            raise AssetCatalogNotFoundError(f"unknown orchestration: {orchestration_id}")
        return self._decorate_orchestration(orchestration, source="custom")

    def delete_orchestration(self, orchestration_id: str) -> dict:
        orchestration = self.get_orchestration(orchestration_id)
        if orchestration.get("source") == "builtin":
            raise ValueError("built-in orchestrations cannot be deleted")
        if not self.repository.delete_orchestration(orchestration_id):
            raise AssetCatalogNotFoundError(f"unknown orchestration: {orchestration_id}")
        return orchestration
