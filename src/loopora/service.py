from __future__ import annotations

import threading
from typing import Callable

from loopora.asset_catalog import WorkflowAssetCatalog
from loopora.db import LooporaRepository
from loopora.executor import CodexExecutor, executor_from_environment
from loopora.service_assets import ServiceAssetMixin
from loopora.service_iteration_reporting import ServiceIterationReportingMixin
from loopora.service_legacy_execution import ServiceLegacyExecutionMixin
from loopora.service_prompts import (
    CHALLENGER_SCHEMA,
    CHECK_PLANNER_SCHEMA,
    GENERATOR_SCHEMA,
    TESTER_SCHEMA,
    VERIFIER_SCHEMA,
    ServiceRunPromptMixin,
)
from loopora.service_role_execution import ServiceRoleExecutionMixin
from loopora.service_run_lifecycle import ServiceRunLifecycleMixin
from loopora.service_role_requests import ServiceRoleRequestMixin
from loopora.service_run_finalization import ServiceRunFinalizationMixin
from loopora.service_types import LooporaError
from loopora.service_workflow_execution import ServiceWorkflowExecutionMixin
from loopora.service_workflow_support import ServiceWorkflowSupportMixin
from loopora.service_workflow_runtime import ServiceWorkflowRuntimeMixin
from loopora.service_workspace import ServiceWorkspaceMixin
from loopora.settings import AppSettings, configure_logging, db_path, load_settings
from loopora.workflows import (
    ARCHETYPES,
    WorkflowError,
    normalize_role_models as workflow_normalize_role_models,
)

LOOP_ROLE_NAMES = ARCHETYPES


def normalize_role_models(role_models: dict | None) -> dict[str, str]:
    try:
        return workflow_normalize_role_models(role_models)
    except WorkflowError as exc:
        raise LooporaError(str(exc)) from exc


class LooporaService(
    ServiceAssetMixin,
    ServiceLegacyExecutionMixin,
    ServiceRunPromptMixin,
    ServiceWorkflowSupportMixin,
    ServiceWorkflowRuntimeMixin,
    ServiceWorkflowExecutionMixin,
    ServiceRunFinalizationMixin,
    ServiceRoleRequestMixin,
    ServiceIterationReportingMixin,
    ServiceRoleExecutionMixin,
    ServiceRunLifecycleMixin,
    ServiceWorkspaceMixin,
):
    _process_active_runs: set[str] = set()
    _process_active_runs_lock = threading.Lock()

    def __init__(
        self,
        repository: LooporaRepository,
        settings: AppSettings,
        executor_factory: Callable[[], CodexExecutor] | None = None,
    ) -> None:
        self.repository = repository
        self.asset_catalog = WorkflowAssetCatalog(repository)
        self.settings = settings
        self.executor_factory = executor_factory or executor_from_environment
        self._threads: dict[str, threading.Thread] = {}
        self._reconcile_stale_runs()

    def _loop_log_context(self, loop: dict | None, **context) -> dict[str, object]:
        payload = dict(context)
        if loop:
            payload.setdefault("loop_id", loop.get("id"))
            payload.setdefault("workdir", loop.get("workdir"))
            payload.setdefault("orchestration_id", loop.get("orchestration_id"))
        return payload

    def _run_log_context(self, run: dict | None, **context) -> dict[str, object]:
        payload = dict(context)
        if run:
            payload.setdefault("run_id", run.get("id"))
            payload.setdefault("loop_id", run.get("loop_id"))
            payload.setdefault("workdir", run.get("workdir"))
            payload.setdefault("orchestration_id", run.get("orchestration_id"))
        return payload

    def _asset_call(self, callback: Callable, *args, **kwargs):
        try:
            return callback(*args, **kwargs)
        except (WorkflowError, ValueError) as exc:
            raise LooporaError(str(exc)) from exc


def create_service(executor_factory: Callable[[], CodexExecutor] | None = None) -> LooporaService:
    configure_logging()
    return LooporaService(
        repository=LooporaRepository(db_path()),
        settings=load_settings(),
        executor_factory=executor_factory,
    )
