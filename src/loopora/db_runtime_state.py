from __future__ import annotations

from loopora.db_event_records import RepositoryEventRecordsMixin
from loopora.db_local_asset_records import RepositoryLocalAssetRecordsMixin
from loopora.db_run_slots import RepositoryRunSlotsMixin
from loopora.db_run_state_records import RepositoryRunStateRecordsMixin


class RepositoryRuntimeStateMixin(
    RepositoryRunSlotsMixin,
    RepositoryRunStateRecordsMixin,
    RepositoryEventRecordsMixin,
    RepositoryLocalAssetRecordsMixin,
):
    """Aggregate runtime-state persistence behavior for loop runs."""
