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
