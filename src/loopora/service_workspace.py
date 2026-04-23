from __future__ import annotations

import os
from pathlib import Path

from loopora.branding import APP_STATE_DIRNAME, state_dir_for_workdir
from loopora.run_artifacts import write_json_with_mirrors
from loopora.service_types import WorkspaceSafetyError
from loopora.utils import read_json, utc_now
from loopora.settings import save_recent_workdirs


class ServiceWorkspaceMixin:
    def _is_bootstrap_workspace(self, workdir: Path) -> bool:
        ignored_dirs = {".git", APP_STATE_DIRNAME, ".venv", "venv", "node_modules", "dist", "build", "__pycache__"}
        scanned_files = 0
        for root, dirs, files in os.walk(workdir):
            dirs[:] = [name for name in dirs if name not in ignored_dirs]
            for filename in files:
                if filename == ".DS_Store":
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
        ignored_dirs = {".git", APP_STATE_DIRNAME, ".venv", "venv", "node_modules", "dist", "build", "__pycache__"}
        ignored_files = {".DS_Store"}
        for root, dirs, files in os.walk(workdir):
            dirs[:] = [name for name in dirs if name not in ignored_dirs]
            for filename in sorted(files):
                if filename in ignored_files:
                    continue
                yield (Path(root) / filename).relative_to(workdir).as_posix()

    def _enforce_workspace_safety(self, run: dict, run_dir: Path, iter_id: int, *, role: str) -> None:
        layout = self._run_artifact_layout(run_dir)
        baseline = read_json(layout.workspace_baseline_path)
        baseline_files = set((baseline or {}).get("files") or [])
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
        if remaining_original == 0:
            destructive = True
        elif deleted_count >= 3 and deleted_ratio >= 0.8:
            destructive = True
        elif deleted_count >= 20 and deleted_ratio >= 0.5:
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
        self.repository.append_event(
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
