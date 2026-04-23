from __future__ import annotations

import logging

from loopora.diagnostics import log_event
from loopora.service_asset_common import logger
from loopora.service_types import LooporaError


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
        bundle = None
        previous_orchestration = None
        if hasattr(self, "_bundle_record_for_orchestration_id"):
            bundle = self._bundle_record_for_orchestration_id(orchestration_id)
            if bundle:
                previous_orchestration = self.get_orchestration(orchestration_id)
        orchestration = self._asset_call(
            self.asset_catalog.update_orchestration,
            orchestration_id,
            name=name,
            description=description,
            workflow=workflow,
            prompt_files=prompt_files,
            role_models=role_models,
        )
        if bundle and hasattr(self, "_touch_bundle_for_orchestration"):
            try:
                self._touch_bundle_for_orchestration(orchestration_id)
            except LooporaError:
                if previous_orchestration:
                    self.repository.update_orchestration(
                        orchestration_id,
                        {
                            "name": previous_orchestration["name"],
                            "description": previous_orchestration.get("description", ""),
                            "workflow": previous_orchestration.get("workflow_json") or {},
                            "prompt_files": previous_orchestration.get("prompt_files_json") or {},
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
            "service.orchestration.updated",
            "Updated orchestration definition",
            orchestration_id=orchestration["id"],
            orchestration_name=orchestration["name"],
            role_count=len(orchestration.get("workflow_json", {}).get("roles", [])),
            step_count=len(orchestration.get("workflow_json", {}).get("steps", [])),
        )
        return orchestration

    def delete_orchestration(self, orchestration_id: str, *, allow_bundle_owned: bool = False) -> dict:
        if not allow_bundle_owned and hasattr(self, "_bundle_record_for_orchestration_id"):
            bundle = self._bundle_record_for_orchestration_id(orchestration_id)
            if bundle:
                raise LooporaError(f"orchestration {orchestration_id} is managed by bundle {bundle['id']}; delete the bundle instead")
        result = self._asset_call(self.asset_catalog.delete_orchestration, orchestration_id)
        log_event(
            logger,
            logging.INFO,
            "service.orchestration.deleted",
            "Deleted orchestration definition",
            orchestration_id=orchestration_id,
        )
        return result
