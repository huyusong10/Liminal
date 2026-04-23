from __future__ import annotations

import logging

from loopora.diagnostics import log_event
from loopora.service_asset_common import logger


class ServiceOrchestrationAssetMixin:
    def list_orchestrations(self) -> list[dict]:
        return self._asset_call(self.asset_catalog.list_orchestrations)

    def get_orchestration(self, orchestration_id: str) -> dict:
        self._reconcile_local_orphaned_runs()
        return self._asset_call(self.asset_catalog.get_orchestration, orchestration_id)

    def create_orchestration(
        self,
        *,
        name: str,
        description: str = "",
        workflow: dict | None = None,
        prompt_files: dict | None = None,
        role_models: dict | None = None,
    ) -> dict:
        orchestration = self._asset_call(
            self.asset_catalog.create_orchestration,
            name=name,
            description=description,
            workflow=workflow,
            prompt_files=prompt_files,
            role_models=role_models,
        )
        log_event(
            logger,
            logging.INFO,
            "service.orchestration.created",
            "Created orchestration definition",
            orchestration_id=orchestration["id"],
            orchestration_name=orchestration["name"],
            role_count=len(orchestration.get("workflow_json", {}).get("roles", [])),
            step_count=len(orchestration.get("workflow_json", {}).get("steps", [])),
        )
        return orchestration

    def update_orchestration(
        self,
        orchestration_id: str,
        *,
        name: str,
        description: str = "",
        workflow: dict | None = None,
        prompt_files: dict | None = None,
        role_models: dict | None = None,
    ) -> dict:
        orchestration = self._asset_call(
            self.asset_catalog.update_orchestration,
            orchestration_id,
            name=name,
            description=description,
            workflow=workflow,
            prompt_files=prompt_files,
            role_models=role_models,
        )
        log_event(
            logger,
            logging.INFO,
            "service.orchestration.updated",
            "Updated orchestration definition",
            orchestration_id=orchestration["id"],
            orchestration_name=orchestration["name"],
            role_count=len(orchestration.get("workflow_json", {}).get("roles", [])),
            step_count=len(orchestration.get("workflow_json", {}).get("steps", [])),
        )
        return orchestration

    def delete_orchestration(self, orchestration_id: str) -> dict:
        result = self._asset_call(self.asset_catalog.delete_orchestration, orchestration_id)
        log_event(
            logger,
            logging.INFO,
            "service.orchestration.deleted",
            "Deleted orchestration definition",
            orchestration_id=orchestration_id,
        )
        return result
