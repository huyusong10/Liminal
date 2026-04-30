from __future__ import annotations

import logging

from loopora.diagnostics import log_event
from loopora.service_asset_common import logger
from loopora.service_types import LooporaConflictError, LooporaError


class ServiceRoleDefinitionAssetMixin:
    def list_role_definitions(self) -> list[dict]:
        return self._asset_call(self.asset_catalog.list_role_definitions)

    def get_role_definition(self, role_definition_id: str) -> dict:
        return self._asset_call(self.asset_catalog.get_role_definition, role_definition_id)

    def create_role_definition(
        self,
        *,
        name: str,
        description: str = "",
        archetype: str,
        prompt_markdown: str,
        posture_notes: str = "",
        prompt_ref: str = "",
        executor_kind: str = "codex",
        executor_mode: str = "preset",
        command_cli: str = "",
        command_args_text: str = "",
        model: str = "",
        reasoning_effort: str = "",
    ) -> dict:
        role_definition = self._asset_call(
            self.asset_catalog.create_role_definition,
            name=name,
            description=description,
            archetype=archetype,
            prompt_ref=prompt_ref,
            prompt_markdown=prompt_markdown,
            posture_notes=posture_notes,
            executor_kind=executor_kind,
            executor_mode=executor_mode,
            command_cli=command_cli,
            command_args_text=command_args_text,
            model=model,
            reasoning_effort=reasoning_effort,
        )
        log_event(
            logger,
            logging.INFO,
            "service.role_definition.created",
            "Created role definition",
            role_definition_id=role_definition["id"],
            archetype=role_definition["archetype"],
            executor_kind=role_definition.get("executor_kind"),
            role_name=role_definition["name"],
        )
        return role_definition

    def update_role_definition(
        self,
        role_definition_id: str,
        *,
        name: str,
        description: str = "",
        archetype: str,
        prompt_markdown: str,
        posture_notes: str = "",
        prompt_ref: str = "",
        executor_kind: str = "codex",
        executor_mode: str = "preset",
        command_cli: str = "",
        command_args_text: str = "",
        model: str = "",
        reasoning_effort: str = "",
    ) -> dict:
        bundle = None
        previous_role_definition = None
        if hasattr(self, "_bundle_record_for_role_definition_id"):
            bundle = self._bundle_record_for_role_definition_id(role_definition_id)
            if bundle:
                previous_role_definition = self.get_role_definition(role_definition_id)
        role_definition = self._asset_call(
            self.asset_catalog.update_role_definition,
            role_definition_id,
            name=name,
            description=description,
            archetype=archetype,
            prompt_ref=prompt_ref,
            prompt_markdown=prompt_markdown,
            posture_notes=posture_notes,
            executor_kind=executor_kind,
            executor_mode=executor_mode,
            command_cli=command_cli,
            command_args_text=command_args_text,
            model=model,
            reasoning_effort=reasoning_effort,
        )
        if bundle and hasattr(self, "_touch_bundle_for_role_definition"):
            try:
                self._touch_bundle_for_role_definition(role_definition_id)
            except LooporaError:
                if previous_role_definition:
                    self.repository.update_role_definition(
                        role_definition_id,
                        {
                            "name": previous_role_definition["name"],
                            "description": previous_role_definition.get("description", ""),
                            "archetype": previous_role_definition["archetype"],
                            "prompt_ref": previous_role_definition["prompt_ref"],
                            "prompt_markdown": previous_role_definition["prompt_markdown"],
                            "posture_notes": previous_role_definition.get("posture_notes", ""),
                            "executor_kind": previous_role_definition.get("executor_kind", "codex"),
                            "executor_mode": previous_role_definition.get("executor_mode", "preset"),
                            "command_cli": previous_role_definition.get("command_cli", ""),
                            "command_args_text": previous_role_definition.get("command_args_text", ""),
                            "model": previous_role_definition.get("model", ""),
                            "reasoning_effort": previous_role_definition.get("reasoning_effort", ""),
                        },
                    )
                    if hasattr(self, "_sync_bundle_loop_snapshot"):
                        try:
                            self._sync_bundle_loop_snapshot(bundle["id"])
                        except LooporaError:
                            pass
                raise
        log_event(
            logger,
            logging.INFO,
            "service.role_definition.updated",
            "Updated role definition",
            role_definition_id=role_definition["id"],
            archetype=role_definition["archetype"],
            executor_kind=role_definition.get("executor_kind"),
            role_name=role_definition["name"],
        )
        return role_definition

    def delete_role_definition(self, role_definition_id: str, *, allow_bundle_owned: bool = False) -> dict:
        if not allow_bundle_owned and hasattr(self, "_bundle_record_for_role_definition_id"):
            bundle = self._bundle_record_for_role_definition_id(role_definition_id)
            if bundle:
                raise LooporaConflictError(
                    f"role definition {role_definition_id} is managed by bundle {bundle['id']}; delete the bundle instead"
                )
        result = self._asset_call(self.asset_catalog.delete_role_definition, role_definition_id)
        log_event(
            logger,
            logging.INFO,
            "service.role_definition.deleted",
            "Deleted role definition",
            role_definition_id=role_definition_id,
        )
        return result
