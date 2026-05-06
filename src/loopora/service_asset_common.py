from __future__ import annotations


from loopora.diagnostics import get_logger
from loopora.service_types import LooporaError
from loopora.workflows import WorkflowError, normalize_role_models as workflow_normalize_role_models

logger = get_logger(__name__)


def _normalize_role_models(role_models: dict | None) -> dict[str, str]:
    try:
        return workflow_normalize_role_models(role_models)
    except WorkflowError as exc:
        raise LooporaError(str(exc)) from exc


def record_bundle_asset_update_rollback_failure(service: object, bundle: dict, error: BaseException) -> None:
    recorder = getattr(service, "_record_bundle_cleanup_failure", None)
    if recorder is None:
        return
    recorder(
        operation="bundle_asset_update_rollback",
        resource_type="loop",
        resource_id=bundle.get("loop_id", ""),
        owner_id=bundle.get("id", ""),
        error=error,
    )
