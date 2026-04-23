from __future__ import annotations

from loopora.service_loop_records import ServiceLoopRecordMixin
from loopora.service_orchestration_assets import ServiceOrchestrationAssetMixin
from loopora.service_role_definition_assets import ServiceRoleDefinitionAssetMixin
from loopora.service_run_registration import ServiceRunRegistrationMixin


class ServiceAssetMixin(
    ServiceRunRegistrationMixin,
    ServiceLoopRecordMixin,
    ServiceOrchestrationAssetMixin,
    ServiceRoleDefinitionAssetMixin,
):
    """Backward-compatible aggregate mixin for loop/orchestration asset operations."""
