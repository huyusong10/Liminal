from __future__ import annotations

from pathlib import Path

from loopora.branding import state_dir_for_workdir
from loopora.run_artifacts import RunArtifactLayout
from loopora.service_asset_common import _normalize_role_models
from loopora.service_types import LooporaError
from loopora.workflows import WorkflowError, build_preset_workflow, prompt_asset_path, resolve_prompt_files, workflow_warnings


class ServiceLoopRecordMixin:
    def _legacy_workflow_from_loop(self, loop_or_run: dict) -> dict:
        role_models = _normalize_role_models(
            loop_or_run.get("role_models_json") or loop_or_run.get("role_models") or {}
        )
        return build_preset_workflow("build_first", role_models=role_models)

    def _prompt_dir(self, base_dir: Path) -> Path:
        return base_dir / "prompts"

    def _run_artifact_layout(self, run_dir: Path) -> RunArtifactLayout:
        return RunArtifactLayout(run_dir)

    def _persist_prompt_files(self, base_dir: Path, prompt_files: dict[str, str]) -> None:
        prompt_dir = self._prompt_dir(base_dir)
        prompt_dir.mkdir(parents=True, exist_ok=True)
        for prompt_ref, markdown_text in sorted(prompt_files.items()):
            path = prompt_asset_path(prompt_dir, prompt_ref)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(markdown_text), encoding="utf-8")

    def _read_prompt_files(self, base_dir: Path, workflow: dict) -> dict[str, str]:
        prompt_files: dict[str, str] = {}
        for role in workflow.get("roles", []):
            prompt_ref = str(role.get("prompt_ref", "")).strip()
            if not prompt_ref or prompt_ref in prompt_files:
                continue
            path = prompt_asset_path(self._prompt_dir(base_dir), prompt_ref)
            if path.exists():
                prompt_files[prompt_ref] = path.read_text(encoding="utf-8")
        return resolve_prompt_files(workflow, prompt_files)

    def _read_prompt_files_for_loop(self, workdir: str, loop_id: str, workflow: dict) -> dict[str, str]:
        loop_dir = state_dir_for_workdir(workdir) / "loops" / loop_id
        return self._read_prompt_files(loop_dir, workflow)

    def _read_prompt_files_for_run(self, run: dict) -> dict[str, str]:
        workflow = run.get("workflow_json") or self._legacy_workflow_from_loop(run)
        layout = self._run_artifact_layout(Path(run["runs_dir"]))
        return self._read_prompt_files(layout.contract_dir, workflow)

    def _hydrate_loop_files(self, loop: dict) -> dict:
        if not loop:
            return loop
        workflow = loop.get("workflow_json") or self._legacy_workflow_from_loop(loop)
        loop["workflow_json"] = workflow
        loop["workflow_warnings"] = workflow_warnings(workflow)
        if loop.get("orchestration_id"):
            loop["orchestration"] = {
                "id": loop.get("orchestration_id"),
                "name": loop.get("orchestration_name") or loop.get("orchestration_id"),
            }
        if hasattr(self, "_bundle_record_for_loop_id"):
            bundle = self._bundle_record_for_loop_id(loop["id"])
            if bundle:
                loop["bundle"] = {
                    "id": bundle["id"],
                    "name": bundle.get("name") or bundle["id"],
                }
        try:
            loop["prompt_files"] = self._read_prompt_files_for_loop(loop["workdir"], loop["id"], workflow)
        except WorkflowError:
            loop["prompt_files"] = {}
        return loop

    def _hydrate_run_files(self, run: dict) -> dict:
        if not run:
            return run
        self._reap_terminal_thread_handle(run.get("id"), status=run.get("status"))
        workflow = run.get("workflow_json") or self._legacy_workflow_from_loop(run)
        run["workflow_json"] = workflow
        run["workflow_warnings"] = workflow_warnings(workflow)
        if run.get("orchestration_id"):
            run["orchestration"] = {
                "id": run.get("orchestration_id"),
                "name": run.get("orchestration_name") or run.get("orchestration_id"),
            }
        try:
            run["prompt_files"] = self._read_prompt_files_for_run(run)
        except WorkflowError:
            run["prompt_files"] = {}
        return run

    def list_loops(self) -> list[dict]:
        self._reconcile_local_orphaned_runs()
        return [self._hydrate_loop_files(loop) for loop in self.repository.list_loops()]

    def get_loop(self, loop_id: str) -> dict:
        self._reconcile_local_orphaned_runs()
        loop = self.repository.get_loop(loop_id)
        if not loop:
            raise LooporaError(f"unknown loop: {loop_id}")
        loop = self._hydrate_loop_files(loop)
        loop["runs"] = [self._hydrate_run_files(run) for run in self.repository.list_runs_for_loop(loop_id)]
        return loop

    def get_run(self, run_id: str) -> dict:
        self._reconcile_local_orphaned_runs()
        run = self.repository.get_run(run_id)
        if not run:
            raise LooporaError(f"unknown run: {run_id}")
        loop = self.repository.get_loop(run["loop_id"])
        if loop:
            run["loop_name"] = loop["name"]
        return self._hydrate_run_files(run)

    def get_status(self, identifier: str) -> tuple[str, dict]:
        self._reconcile_local_orphaned_runs()
        found = self.repository.get_loop_or_run(identifier)
        if not found:
            raise LooporaError(f"unknown identifier: {identifier}")
        kind, payload = found
        if kind == "loop":
            payload = self._hydrate_loop_files(payload)
            payload["runs"] = [self._hydrate_run_files(run) for run in self.repository.list_runs_for_loop(payload["id"])]
        else:
            payload = self._hydrate_run_files(payload)
        return kind, payload
