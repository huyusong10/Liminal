from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from loopora.branding import state_dir_for_workdir
from loopora.settings import app_home, load_recent_workdirs


@dataclass(frozen=True)
class LocalAssetDiagnosticsContext:
    service: object
    bundles: list[dict]
    alignment_sessions: list[dict]
    run_records: list[dict]
    registry_rows: list[dict]
    bundle_ids: set[str]
    alignment_session_ids: set[str]
    run_ids: set[str]


def build_local_asset_diagnostics(service) -> dict:
    bundles = service.repository.list_bundles()
    bundle_ids = _resource_ids(bundles)
    registry_rows = _local_asset_registry_rows(service.repository)
    alignment_sessions = _alignment_sessions(service.repository)
    alignment_session_ids = _resource_ids(alignment_sessions)
    loops = service.repository.list_loops()
    known_workdirs = _known_workdirs(loops, alignment_sessions, registry_rows)
    run_records = _run_records(service.repository, loops)
    run_ids = _resource_ids(run_records)

    return {
        "orphan_alignment_dirs": _orphan_alignment_dirs(registry_rows, alignment_session_ids, known_workdirs),
        "orphan_bundle_dirs": _orphan_bundle_dirs(registry_rows, bundle_ids),
        "orphan_run_dirs": _orphan_run_dirs(registry_rows, run_ids, known_workdirs),
        "record_without_dir": _records_without_dirs(
            LocalAssetDiagnosticsContext(
                service=service,
                bundles=bundles,
                alignment_sessions=alignment_sessions,
                run_records=run_records,
                registry_rows=registry_rows,
                bundle_ids=bundle_ids,
                alignment_session_ids=alignment_session_ids,
                run_ids=run_ids,
            )
        ),
    }


def _local_asset_registry_rows(repository) -> list[dict]:
    if hasattr(repository, "list_local_asset_roots"):
        return repository.list_local_asset_roots()
    return []


def _alignment_sessions(repository) -> list[dict]:
    if hasattr(repository, "list_all_alignment_sessions"):
        return repository.list_all_alignment_sessions()
    return repository.list_alignment_sessions(limit=100)


def _resource_ids(records: list[dict]) -> set[str]:
    return {str(record.get("id") or "").strip() for record in records if str(record.get("id") or "").strip()}


def _known_workdirs(loops: list[dict], alignment_sessions: list[dict], registry_rows: list[dict]) -> set[str]:
    known_workdirs = {str(loop.get("workdir") or "").strip() for loop in loops if str(loop.get("workdir") or "").strip()}
    known_workdirs.update(
        str(session.get("workdir") or "").strip()
        for session in alignment_sessions
        if str(session.get("workdir") or "").strip()
    )
    known_workdirs.update(
        str(row.get("workdir") or "").strip()
        for row in registry_rows
        if row.get("resource_type") in {"alignment_session", "run"} and str(row.get("workdir") or "").strip()
    )
    known_workdirs.update(load_recent_workdirs(limit=100))
    return known_workdirs


def _run_records(repository, loops: list[dict]) -> list[dict]:
    records = []
    for loop in loops:
        loop_id = str(loop.get("id") or "").strip()
        if loop_id:
            records.extend(repository.list_runs_for_loop(loop_id, limit=5000))
    return records


def _orphan_bundle_dirs(registry_rows: list[dict], bundle_ids: set[str]) -> list[dict]:
    orphan_bundle_dirs = []
    orphan_bundle_paths: set[str] = set()
    bundle_root = app_home() / "bundles"
    if bundle_root.exists():
        for path in sorted(item for item in bundle_root.iterdir() if item.is_dir()):
            if path.name not in bundle_ids:
                orphan_bundle_dirs.append({"bundle_id": path.name, "path": str(path)})
                orphan_bundle_paths.add(str(path))
    for row in registry_rows:
        if row.get("resource_type") != "bundle" or row.get("state") == "cleaned":
            continue
        bundle_id = str(row.get("resource_id") or "").strip()
        path = Path(str(row.get("path") or ""))
        if path.exists() and (bundle_id not in bundle_ids or row.get("state") == "orphaned"):
            normalized_path = str(path)
            if normalized_path not in orphan_bundle_paths:
                orphan_bundle_dirs.append({"bundle_id": bundle_id, "path": normalized_path})
                orphan_bundle_paths.add(normalized_path)
    return orphan_bundle_dirs


def _orphan_run_dirs(registry_rows: list[dict], run_ids: set[str], known_workdirs: set[str]) -> list[dict]:
    orphan_run_dirs = []
    orphan_run_paths: set[str] = set()
    for row in registry_rows:
        if row.get("resource_type") != "run" or row.get("state") == "cleaned":
            continue
        run_id = str(row.get("resource_id") or "").strip()
        path = Path(str(row.get("path") or ""))
        if path.exists() and (run_id not in run_ids or row.get("state") == "orphaned"):
            normalized_path = str(path)
            if normalized_path not in orphan_run_paths:
                orphan_run_dirs.append(
                    {
                        "run_id": run_id,
                        "workdir": str(row.get("workdir") or ""),
                        "path": normalized_path,
                        "source": "registry",
                    }
                )
                orphan_run_paths.add(normalized_path)
    for workdir in sorted(path for path in known_workdirs if path):
        root = state_dir_for_workdir(workdir) / "runs"
        if not root.exists():
            continue
        for path in sorted(item for item in root.iterdir() if item.is_dir()):
            if path.name in run_ids:
                continue
            normalized_path = str(path)
            if normalized_path in orphan_run_paths:
                continue
            orphan_run_dirs.append(
                {
                    "run_id": path.name,
                    "workdir": workdir,
                    "path": normalized_path,
                    "source": "recent_workdir",
                }
            )
            orphan_run_paths.add(normalized_path)
    return orphan_run_dirs


def _orphan_alignment_dirs(registry_rows: list[dict], alignment_session_ids: set[str], known_workdirs: set[str]) -> list[dict]:
    orphan_alignment_dirs = []
    orphan_alignment_paths: set[str] = set()
    for workdir in sorted(path for path in known_workdirs if path):
        root = state_dir_for_workdir(workdir) / "alignment_sessions"
        if not root.exists():
            continue
        for path in sorted(item for item in root.iterdir() if item.is_dir()):
            if path.name not in alignment_session_ids:
                orphan_alignment_dirs.append({"session_id": path.name, "workdir": workdir, "path": str(path)})
                orphan_alignment_paths.add(str(path))
    for row in registry_rows:
        if row.get("resource_type") != "alignment_session" or row.get("state") == "cleaned":
            continue
        session_id = str(row.get("resource_id") or "").strip()
        path = Path(str(row.get("path") or ""))
        if path.exists() and (session_id not in alignment_session_ids or row.get("state") == "orphaned"):
            normalized_path = str(path)
            if normalized_path not in orphan_alignment_paths:
                orphan_alignment_dirs.append(
                    {"session_id": session_id, "workdir": str(row.get("workdir") or ""), "path": normalized_path}
                )
                orphan_alignment_paths.add(normalized_path)
    return orphan_alignment_dirs


def _records_without_dirs(context: LocalAssetDiagnosticsContext) -> list[dict]:
    record_without_dir = []
    for bundle in context.bundles:
        bundle_id = str(bundle.get("id") or "").strip()
        if not bundle_id:
            continue
        bundle_dir = context.service._bundle_dir(bundle_id)
        if not bundle_dir.exists():
            record_without_dir.append({"resource_type": "bundle", "resource_id": bundle_id, "path": str(bundle_dir)})
    for session in context.alignment_sessions:
        session_id = str(session.get("id") or "").strip()
        if not session_id:
            continue
        root = _alignment_session_root(context.service, session, session_id)
        if not root.exists():
            record_without_dir.append({"resource_type": "alignment_session", "resource_id": session_id, "path": str(root)})
    for run in context.run_records:
        run_id = str(run.get("id") or "").strip()
        runs_dir = str(run.get("runs_dir") or "").strip()
        if run_id and runs_dir and not Path(runs_dir).exists():
            record_without_dir.append({"resource_type": "run", "resource_id": run_id, "path": runs_dir})
    _append_registry_records_without_dirs(
        record_without_dir=record_without_dir,
        registry_rows=context.registry_rows,
        bundle_ids=context.bundle_ids,
        alignment_session_ids=context.alignment_session_ids,
        run_ids=context.run_ids,
    )
    return record_without_dir


def _alignment_session_root(service, session: dict, session_id: str) -> Path:
    if hasattr(service, "_alignment_session_root"):
        return service._alignment_session_root(session)
    return state_dir_for_workdir(session.get("workdir", "")) / "alignment_sessions" / session_id


def _append_registry_records_without_dirs(
    *,
    record_without_dir: list[dict],
    registry_rows: list[dict],
    bundle_ids: set[str],
    alignment_session_ids: set[str],
    run_ids: set[str],
) -> None:
    record_without_dir_keys = {
        (str(item.get("resource_type") or ""), str(item.get("resource_id") or ""), str(item.get("path") or ""))
        for item in record_without_dir
    }
    for row in registry_rows:
        if row.get("state") == "cleaned":
            continue
        resource_type = str(row.get("resource_type") or "").strip()
        resource_id = str(row.get("resource_id") or "").strip()
        path = Path(str(row.get("path") or ""))
        if not resource_type or not resource_id or path.exists():
            continue
        key = (resource_type, resource_id, str(path))
        has_live_owner = _registry_record_has_live_owner(
            resource_type=resource_type,
            resource_id=resource_id,
            bundle_ids=bundle_ids,
            alignment_session_ids=alignment_session_ids,
            run_ids=run_ids,
        )
        if key in record_without_dir_keys or (row.get("state") != "active" and not has_live_owner):
            continue
        record_without_dir.append({"resource_type": resource_type, "resource_id": resource_id, "path": str(path)})
        record_without_dir_keys.add(key)


def _registry_record_has_live_owner(
    *,
    resource_type: str,
    resource_id: str,
    bundle_ids: set[str],
    alignment_session_ids: set[str],
    run_ids: set[str],
) -> bool:
    if resource_type == "bundle":
        return resource_id in bundle_ids
    if resource_type == "alignment_session":
        return resource_id in alignment_session_ids
    if resource_type == "run":
        return resource_id in run_ids
    return True
