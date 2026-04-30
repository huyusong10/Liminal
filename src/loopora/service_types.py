from __future__ import annotations

from loopora.recovery import RecoveryResult

COMPLETION_MODES = ("gatekeeper", "rounds")
TERMINAL_RUN_STATUSES = frozenset({"succeeded", "failed", "stopped"})


class LooporaError(RuntimeError):
    """Domain error surfaced to CLI and API consumers."""

    status_code = 400


class LooporaNotFoundError(LooporaError):
    """Raised when a stable domain resource cannot be found."""

    status_code = 404


class LooporaConflictError(LooporaError):
    """Raised when a request conflicts with active lifecycle state."""

    status_code = 409


class RoleExecutionError(LooporaError):
    def __init__(self, role: str, result: RecoveryResult) -> None:
        self.role = role
        self.result = result
        super().__init__(f"role={role} failed after {result.attempts} attempts")


class WorkspaceSafetyError(LooporaError):
    def __init__(self, *, role: str, deleted_paths: list[str], baseline_count: int, current_count: int) -> None:
        self.role = role
        self.deleted_paths = deleted_paths
        self.baseline_count = baseline_count
        self.current_count = current_count
        preview = ", ".join(deleted_paths[:5])
        super().__init__(
            "workspace safety guard blocked a destructive rewrite: "
            f"{len(deleted_paths)} of {baseline_count} original files disappeared"
            + (f" ({preview})" if preview else "")
        )


class StopRequested(LooporaError):
    """Raised when a user asked to stop a running loop."""


def normalize_completion_mode(value: str | None) -> str:
    mode = str(value or "gatekeeper").strip().lower() or "gatekeeper"
    if mode not in COMPLETION_MODES:
        raise LooporaError(f"unsupported completion mode: {value}")
    return mode
