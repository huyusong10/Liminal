from __future__ import annotations

import os
from pathlib import Path

from loopora.branding import APP_STATE_DIRNAME, state_dir_for_workdir
from loopora.run_artifacts import write_json_with_mirrors
from loopora.service_types import LooporaError, WorkspaceSafetyError
from loopora.utils import read_json, utc_now
from loopora.settings import save_recent_workdirs

WORKSPACE_USER_FILE_IGNORED_DIRS = {
    ".git",
    APP_STATE_DIRNAME,
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    "__pycache__",
    ".cache",
    ".mypy_cache",
    ".nox",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".parcel-cache",
    ".next",
    ".nuxt",
    ".vite",
    "htmlcov",
}

WORKSPACE_USER_FILE_IGNORED_FILES = {".DS_Store", ".coverage", "coverage.xml"}


class ServiceWorkspaceMixin:
    def _is_bootstrap_workspace(self, workdir: Path) -> bool:
        scanned_files = 0
        for root, dirs, files in os.walk(workdir):
            dirs[:] = [name for name in dirs if name not in WORKSPACE_USER_FILE_IGNORED_DIRS]
            for filename in files:
                if filename in WORKSPACE_USER_FILE_IGNORED_FILES:
                    continue
                scanned_files += 1
                if scanned_files >= 200:
                    return False
                relative_path = (Path(root) / filename).relative_to(workdir).as_posix()
                if relative_path == "spec.md":
                    continue
                return False
        return True

    def _capture_workspace_manifest(self, workdir: Path) -> dict:
        files = list(self._iter_user_workspace_files(workdir))
        return {
            "captured_at": utc_now(),
            "file_count": len(files),
            "files": files,
        }

    def _iter_user_workspace_files(self, workdir: Path):
        for root, dirs, files in os.walk(workdir):
            dirs[:] = [name for name in dirs if name not in WORKSPACE_USER_FILE_IGNORED_DIRS]
            for filename in sorted(files):
                if filename in WORKSPACE_USER_FILE_IGNORED_FILES:
                    continue
                yield (Path(root) / filename).relative_to(workdir).as_posix()

    def _enforce_workspace_safety(self, run: dict, run_dir: Path, iter_id: int, *, role: str) -> None:
        layout = self._run_artifact_layout(run_dir)
        baseline_files = self._read_workspace_baseline_files(layout.workspace_baseline_path)
        if not baseline_files:
            return
        current_files = set(self._iter_user_workspace_files(Path(run["workdir"])))
        deleted_original = sorted(path for path in baseline_files if path not in current_files)
        if not deleted_original:
            return

        deleted_count = len(deleted_original)
        baseline_count = len(baseline_files)
        remaining_original = baseline_count - deleted_count
        deleted_ratio = deleted_count / baseline_count if baseline_count else 0.0
        destructive = False
        if remaining_original == 0 or (deleted_count >= 3 and deleted_ratio >= 0.8) or (deleted_count >= 20 and deleted_ratio >= 0.5):
            destructive = True

        if not destructive:
            return

        payload = {
            "iter": iter_id,
            "role": role,
            "baseline_file_count": baseline_count,
            "remaining_original_file_count": remaining_original,
            "deleted_original_count": deleted_count,
            "deleted_original_paths": deleted_original,
            "deleted_ratio": round(deleted_ratio, 4),
        }
        write_json_with_mirrors(
            layout.timeline_workspace_guard_path,
            payload,
            mirror_paths=[layout.legacy_workspace_guard_path],
        )
        self.append_run_event(
            run["id"],
            "workspace_guard_triggered",
            payload,
            role=role,
        )
        raise WorkspaceSafetyError(
            role=role,
            deleted_paths=deleted_original,
            baseline_count=baseline_count,
            current_count=remaining_original,
        )

    @staticmethod
    def _read_workspace_baseline_files(path: Path) -> set[str]:
        try:
            baseline = read_json(path)
        except (OSError, UnicodeError, ValueError) as exc:
            raise LooporaError(f"workspace safety baseline could not be read: {path}") from exc
        if not isinstance(baseline, dict) or "files" not in baseline:
            raise LooporaError(f"workspace safety baseline is missing or malformed: {path}")
        files = baseline.get("files")
        if not isinstance(files, list):
            raise LooporaError(f"workspace safety baseline is missing or malformed: {path}")
        normalized_files = {str(item).strip() for item in files if isinstance(item, str) and str(item).strip()}
        if len(normalized_files) != len(files):
            raise LooporaError(f"workspace safety baseline is missing or malformed: {path}")
        return normalized_files

    def _ensure_loop_dir(self, workdir: Path, loop_id: str) -> Path:
        path = state_dir_for_workdir(workdir) / "loops" / loop_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _ensure_run_dir(self, workdir: Path, run_id: str) -> Path:
        path = state_dir_for_workdir(workdir) / "runs" / run_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _write_recent_workdirs(self) -> None:
        loops = self.repository.list_loops()
        save_recent_workdirs(loop["workdir"] for loop in loops)
