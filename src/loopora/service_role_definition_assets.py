from __future__ import annotations

import logging

from loopora.diagnostics import log_event
from loopora.service_asset_common import logger


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
        prompt_ref: str = "",
        executor_kind: str = "codex",
        executor_mode: str = "preset",
        command_cli: str = "",
        command_args_text: str = "",
        model: str = "",
        reasoning_effort: str = "",
    ) -> dict:
        role_definition = self._asset_call(
            self.asset_catalog.update_role_definition,
            role_definition_id,
            name=name,
            description=description,
            archetype=archetype,
            prompt_ref=prompt_ref,
            prompt_markdown=prompt_markdown,
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
            "service.role_definition.updated",
            "Updated role definition",
            role_definition_id=role_definition["id"],
            archetype=role_definition["archetype"],
            executor_kind=role_definition.get("executor_kind"),
            role_name=role_definition["name"],
        )
        return role_definition

    def delete_role_definition(self, role_definition_id: str) -> dict:
        result = self._asset_call(self.asset_catalog.delete_role_definition, role_definition_id)
        log_event(
            logger,
            logging.INFO,
            "service.role_definition.deleted",
            "Deleted role definition",
            role_definition_id=role_definition_id,
        )
        return result
