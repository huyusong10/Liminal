from __future__ import annotations

from loopora.service_iteration_reporting import ServiceIterationReportingMixin
from loopora.service_role_requests import ServiceRoleRequestMixin
from loopora.service_run_finalization import ServiceRunFinalizationMixin


class ServiceRunReportingMixin(
    ServiceRunFinalizationMixin,
    ServiceRoleRequestMixin,
    ServiceIterationReportingMixin,
):
    """Backward-compatible aggregate mixin for reporting-related helpers."""
