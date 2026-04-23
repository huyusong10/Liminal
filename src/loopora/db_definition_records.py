from __future__ import annotations

from loopora.db_loop_records import RepositoryLoopRecordsMixin
from loopora.db_run_records import RepositoryRunRecordsMixin


class RepositoryDefinitionRecordsMixin(
    RepositoryRunRecordsMixin,
    RepositoryLoopRecordsMixin,
):
    def get_loop_or_run(self, identifier: str) -> tuple[str, dict] | None:
        if loop := self.get_loop(identifier):
            return "loop", loop
        if run := self.get_run(identifier):
            return "run", run
        return None
