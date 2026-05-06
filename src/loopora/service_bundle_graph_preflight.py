from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from loopora.branding import state_dir_for_workdir
from loopora.service_types import LooporaConflictError


@dataclass(frozen=True)
class BundleGraphLinks:
    loop_id: str
    orchestration_id: str
    role_definition_ids: list[str]


def bundle_graph_links(bundle: dict) -> BundleGraphLinks:
    return BundleGraphLinks(
        loop_id=str(bundle.get("loop_id", "") or "").strip(),
        orchestration_id=str(bundle.get("orchestration_id", "") or "").strip(),
        role_definition_ids=[
            str(item).strip()
            for item in (bundle.get("role_definition_ids") or bundle.get("role_definition_ids_json") or [])
            if str(item).strip()
        ],
    )


def preflight_bundle_graph_delete(repository, bundle: dict, links: BundleGraphLinks) -> list[Path]:
    bundle_id = bundle["id"]
    expected_assets = _expected_bundle_assets(links)
    _assert_assets_owned_by_bundle(repository, bundle_id, expected_assets)

    paths: list[Path] = []
    loop = repository.get_loop(links.loop_id) if links.loop_id else None
    if loop:
        paths.extend(_preflight_loop_delete(repository, bundle_id, links, loop))

    orchestration = repository.get_orchestration(links.orchestration_id) if links.orchestration_id else None
    if links.orchestration_id:
        _assert_orchestration_not_shared(repository, bundle_id, links)

    if orchestration and links.role_definition_ids:
        _assert_roles_belong_to_orchestration(bundle_id, links.orchestration_id, links.role_definition_ids, orchestration)
    _assert_roles_not_shared_by_external_orchestrations(repository, bundle_id, links)
    return paths


def loop_artifact_dir_for_record(loop: dict) -> Path:
    return state_dir_for_workdir(loop["workdir"]) / "loops" / loop["id"]


def _expected_bundle_assets(links: BundleGraphLinks) -> list[tuple[str, str]]:
    assets: list[tuple[str, str]] = []
    if links.loop_id:
        assets.append(("loop", links.loop_id))
    if links.orchestration_id:
        assets.append(("orchestration", links.orchestration_id))
    assets.extend(("role_definition", role_definition_id) for role_definition_id in links.role_definition_ids)
    return assets


def _assert_assets_owned_by_bundle(repository, bundle_id: str, assets: list[tuple[str, str]]) -> None:
    for asset_type, asset_id in assets:
        owner_id = repository.get_bundle_asset_owner(asset_type, asset_id)
        if owner_id == bundle_id:
            continue
        reason = "unowned" if not owner_id else f"owned by {owner_id}"
        raise LooporaConflictError(f"bundle {bundle_id} cannot delete {asset_type} {asset_id}: asset is {reason}")


def _preflight_loop_delete(repository, bundle_id: str, links: BundleGraphLinks, loop: dict) -> list[Path]:
    linked_orchestration_id = str(loop.get("orchestration_id", "") or "").strip()
    if links.orchestration_id and linked_orchestration_id and linked_orchestration_id != links.orchestration_id:
        raise LooporaConflictError(
            f"bundle {bundle_id} loop {links.loop_id} points at orchestration {linked_orchestration_id}, "
            f"not {links.orchestration_id}"
        )

    runs = repository.list_runs_for_loop(links.loop_id, limit=5000)
    active_runs = [str(run["id"]) for run in runs if run.get("status") in {"queued", "running"}]
    if active_runs:
        raise LooporaConflictError(f"cannot delete bundle with active loop runs: {', '.join(active_runs)}")

    paths = [Path(run["runs_dir"]) for run in runs if str(run.get("runs_dir") or "").strip()]
    paths.append(loop_artifact_dir_for_record(loop))
    return paths


def _assert_orchestration_not_shared(repository, bundle_id: str, links: BundleGraphLinks) -> None:
    shared_loop_ids = [
        str(loop_record.get("id") or "").strip()
        for loop_record in repository.list_loops()
        if str(loop_record.get("orchestration_id") or "").strip() == links.orchestration_id
        and str(loop_record.get("id") or "").strip() != links.loop_id
    ]
    if not shared_loop_ids:
        return
    raise LooporaConflictError(
        f"bundle {bundle_id} cannot delete orchestration {links.orchestration_id}; "
        f"it is referenced by loops: {', '.join(shared_loop_ids)}"
    )


def _assert_roles_belong_to_orchestration(
    bundle_id: str,
    orchestration_id: str,
    role_definition_ids: list[str],
    orchestration: dict,
) -> None:
    workflow = orchestration.get("workflow_json") or {}
    referenced_role_ids = _workflow_role_definition_ids(workflow)
    unexpected = sorted(role_id for role_id in role_definition_ids if role_id not in referenced_role_ids)
    if referenced_role_ids and unexpected:
        raise LooporaConflictError(
            f"bundle {bundle_id} role definitions are not owned by orchestration {orchestration_id}: "
            f"{', '.join(unexpected)}"
        )


def _assert_roles_not_shared_by_external_orchestrations(
    repository,
    bundle_id: str,
    links: BundleGraphLinks,
) -> None:
    role_ids = set(links.role_definition_ids)
    if not role_ids:
        return

    external_orchestrations = []
    for candidate in repository.list_orchestrations():
        candidate_id = str(candidate.get("id") or "").strip()
        if candidate_id == links.orchestration_id:
            continue
        if role_ids & _workflow_role_definition_ids(candidate.get("workflow_json") or {}):
            external_orchestrations.append(candidate_id)
    if external_orchestrations:
        raise LooporaConflictError(
            f"bundle {bundle_id} cannot delete shared role definitions; "
            f"referenced by orchestrations: {', '.join(sorted(external_orchestrations))}"
        )


def _workflow_role_definition_ids(workflow: dict) -> set[str]:
    return {
        str(role.get("role_definition_id", "") or "").strip()
        for role in workflow.get("roles", [])
        if isinstance(role, dict)
    }
