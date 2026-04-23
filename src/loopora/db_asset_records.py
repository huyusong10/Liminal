from __future__ import annotations

from loopora.db_orchestration_records import RepositoryOrchestrationRecordsMixin
from loopora.db_role_definition_records import RepositoryRoleDefinitionRecordsMixin


class RepositoryAssetRecordsMixin(
    RepositoryRoleDefinitionRecordsMixin,
    RepositoryOrchestrationRecordsMixin,
):
    """Aggregate asset persistence behavior for orchestrations and role definitions."""
