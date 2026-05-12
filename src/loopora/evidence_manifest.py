from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from loopora.coverage_target_semantics import coverage_target_is_required
from loopora.evidence_coverage import parse_target_verify_ref
from loopora.run_artifacts import RunArtifactLayout, read_jsonl
from loopora.structured_booleans import structured_bool_is_true
from loopora.structured_numbers import structured_non_negative_int
from loopora.utils import read_json, utc_now, write_json

MAX_HASH_BYTES = 10 * 1024 * 1024


def write_evidence_manifest_projection(layout: RunArtifactLayout, *, coverage_projection: Mapping[str, Any] | None = None) -> dict:
    projection = build_evidence_manifest_projection(layout, coverage_projection=coverage_projection)
    write_json(layout.evidence_manifest_path, projection)
    return projection


def build_evidence_manifest_projection(
    layout: RunArtifactLayout,
    *,
    coverage_projection: Mapping[str, Any] | None = None,
) -> dict:
    run_contract = _safe_read_json_artifact(layout.run_contract_path)
    coverage = dict(coverage_projection or _safe_read_json_artifact(layout.evidence_coverage_path))
    targets_by_id = {
        str(target.get("id") or "").strip(): target
        for target in list(coverage.get("targets") or [])
        if isinstance(target, Mapping) and str(target.get("id") or "").strip()
    }
    claims = [
        _claim_manifest(item, layout=layout, targets_by_id=targets_by_id) for item in read_jsonl(layout.evidence_ledger_path) if isinstance(item, Mapping)
    ]
    target_index = _target_index(targets_by_id, claims)
    return {
        "schema_version": 1,
        "generated_at": utc_now(),
        "manifest_path": layout.relative(layout.evidence_manifest_path),
        "ledger_path": layout.relative(layout.evidence_ledger_path),
        "coverage_path": layout.relative(layout.evidence_coverage_path),
        "run_contract_path": layout.relative(layout.run_contract_path),
        "completion_mode": str(run_contract.get("completion_mode") or "gatekeeper"),
        "claim_count": len(claims),
        "artifact_backed_claim_count": sum(1 for claim in claims if claim["artifact_backed"]),
        "workspace_backed_claim_count": sum(1 for claim in claims if claim["workspace_backed"]),
        "direct_proof_claim_count": sum(1 for claim in claims if claim["verification_status"] == "direct_proof"),
        "workspace_artifact_claim_count": sum(1 for claim in claims if claim["verification_status"] == "workspace_artifact"),
        "run_artifact_claim_count": sum(1 for claim in claims if claim["verification_status"] == "run_artifact"),
        "ledger_only_claim_count": sum(1 for claim in claims if claim["verification_status"] == "ledger_only"),
        "unverified_claim_count": sum(1 for claim in claims if claim["verification_status"] == "unverified"),
        "claims": claims,
        "targets": target_index,
        "problems": _manifest_problems(claims),
    }


def _claim_manifest(item: Mapping[str, Any], *, layout: RunArtifactLayout, targets_by_id: Mapping[str, Mapping[str, Any]]) -> dict:
    artifact_refs = [_artifact_manifest(ref) for ref in list(item.get("artifact_refs") or []) if isinstance(ref, Mapping)]
    coverage_targets = _coverage_target_refs(item, targets_by_id)
    workspace_backed = any(ref.get("kind") == "workspace" and ref.get("exists") for ref in artifact_refs)
    artifact_backed = any(ref.get("exists") for ref in artifact_refs)
    proof_backed = any(_is_proof_ref(ref) and ref.get("exists") for ref in artifact_refs)
    verification_status = _verification_status(
        result=str(item.get("result") or ""),
        artifact_backed=artifact_backed,
        workspace_backed=workspace_backed,
        proof_backed=proof_backed,
    )
    return {
        "id": str(item.get("id") or "").strip(),
        "claim": str(item.get("claim") or "").strip(),
        "producer": {
            "iter": _safe_int(item.get("iter")),
            "step_id": str(item.get("step_id") or "").strip(),
            "step_order": _safe_int(item.get("step_order")),
            "role_id": str(item.get("role_id") or "").strip(),
            "role_name": str(item.get("role_name") or "").strip(),
            "runtime_role": str(item.get("runtime_role") or "").strip(),
            "archetype": str(item.get("archetype") or "").strip(),
        },
        "evidence_kind": str(item.get("evidence_kind") or "").strip(),
        "source": str(item.get("source") or "").strip(),
        "method": str(item.get("method") or "").strip(),
        "result": str(item.get("result") or "").strip(),
        "verifies": [str(value).strip() for value in list(item.get("verifies") or []) if str(value).strip()],
        "coverage_results": _manifest_coverage_results(item.get("coverage_results")),
        "coverage_targets": coverage_targets,
        "related_evidence_ids": [str(value).strip() for value in list(item.get("related_evidence_ids") or []) if str(value).strip()][:20],
        "artifact_refs": artifact_refs,
        "artifact_count": len(artifact_refs),
        "workspace_artifact_count": sum(1 for ref in artifact_refs if ref.get("kind") == "workspace"),
        "artifact_backed": artifact_backed,
        "workspace_backed": workspace_backed,
        "measured_evidence": structured_bool_is_true(item.get("measured_evidence")),
        "concrete_evidence_claim_count": _safe_int(item.get("concrete_evidence_claim_count")),
        "verification_status": verification_status,
        "reproducible": verification_status in {"direct_proof", "workspace_artifact"},
        "residual_risk": str(item.get("residual_risk") or "").strip(),
        "manifest_ref": f"{layout.relative(layout.evidence_manifest_path)}#{str(item.get('id') or '').strip()}",
    }


def _artifact_manifest(ref: Mapping[str, Any]) -> dict:
    absolute_path = str(ref.get("absolute_path") or "").strip()
    file_state = _artifact_file_state(absolute_path)
    return {
        "kind": str(ref.get("kind") or "").strip(),
        "label": str(ref.get("label") or "").strip(),
        "relative_path": str(ref.get("relative_path") or "").strip(),
        "workspace_path": str(ref.get("workspace_path") or "").strip(),
        "absolute_path": absolute_path,
        **file_state,
    }


def _artifact_file_state(absolute_path: str) -> dict:
    if not absolute_path:
        return {"exists": False, "size_bytes": None, "sha256": "", "hash_status": "missing_path"}
    try:
        path = Path(absolute_path)
        stat = path.stat()
    except OSError:
        return {"exists": False, "size_bytes": None, "sha256": "", "hash_status": "missing"}
    if not path.is_file():
        return {"exists": True, "size_bytes": stat.st_size, "sha256": "", "hash_status": "not_file"}
    if stat.st_size > MAX_HASH_BYTES:
        return {"exists": True, "size_bytes": stat.st_size, "sha256": "", "hash_status": "too_large"}
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return {"exists": True, "size_bytes": stat.st_size, "sha256": "", "hash_status": "unreadable"}
    return {"exists": True, "size_bytes": stat.st_size, "sha256": digest, "hash_status": "sha256"}


def _coverage_target_refs(item: Mapping[str, Any], targets_by_id: Mapping[str, Mapping[str, Any]]) -> list[dict]:
    refs = []
    seen: set[str] = set()
    for coverage_result in _manifest_coverage_results(item.get("coverage_results")):
        target_id = coverage_result["target_id"]
        if target_id in seen:
            continue
        seen.add(target_id)
        target = targets_by_id.get(target_id, {})
        refs.append(
            {
                "id": target_id,
                "kind": str(target.get("kind") or "").strip(),
                "label": str(target.get("label") or target_id).strip(),
                "reported_status": coverage_result["status"],
                "coverage_status": str(target.get("status") or "missing").strip(),
                "required": coverage_target_is_required(target, target_id=target_id),
                "evidence_refs": coverage_result["evidence_refs"],
            }
        )
    for verify_ref in list(item.get("verifies") or []):
        parsed = parse_target_verify_ref(verify_ref)
        if not parsed:
            continue
        target_id, reported_status = parsed
        if target_id in seen:
            continue
        seen.add(target_id)
        target = targets_by_id.get(target_id, {})
        refs.append(
            {
                "id": target_id,
                "kind": str(target.get("kind") or "").strip(),
                "label": str(target.get("label") or target_id).strip(),
                "reported_status": str(reported_status or "unknown").strip(),
                "coverage_status": str(target.get("status") or "missing").strip(),
                "required": coverage_target_is_required(target, target_id=target_id),
                "evidence_refs": [],
            }
        )
    return refs


def _manifest_coverage_results(value: object) -> list[dict]:
    if not isinstance(value, list):
        return []
    results: list[dict] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        target_id = str(item.get("target_id") or "").strip()
        if not target_id or ":" in target_id:
            continue
        results.append(
            {
                "target_id": target_id,
                "status": str(item.get("status") or "unknown").strip() or "unknown",
                "evidence_refs": [str(value).strip() for value in list(item.get("evidence_refs") or []) if str(value).strip()][:20],
                "note": str(item.get("note") or "").strip()[:400],
            }
        )
    return results[:20]


def _verification_status(
    *,
    result: str,
    artifact_backed: bool,
    workspace_backed: bool,
    proof_backed: bool,
) -> str:
    normalized_result = result.strip().lower()
    if normalized_result in {"blocked", "failed", "rejected"}:
        return "unverified"
    if proof_backed:
        return "direct_proof"
    if workspace_backed:
        return "workspace_artifact"
    if artifact_backed:
        return "run_artifact"
    return "ledger_only"


def _is_proof_ref(ref: Mapping[str, Any]) -> bool:
    label = str(ref.get("label") or "").lower()
    workspace_path = str(ref.get("workspace_path") or "").lower()
    return label.startswith(("proof-file:", "proof-artifact:")) or "/evidence/" in f"/{workspace_path}"


def _target_index(targets_by_id: Mapping[str, Mapping[str, Any]], claims: list[dict]) -> list[dict]:
    claims_by_target: dict[str, list[str]] = {}
    artifacts_by_target: dict[str, list[dict]] = {}
    claims_by_id = {str(claim.get("id") or "").strip(): claim for claim in claims if str(claim.get("id") or "").strip()}
    for target_id, target in targets_by_id.items():
        target_artifacts = [_artifact_manifest(ref) for ref in list(target.get("artifact_refs") or []) if isinstance(ref, Mapping)]
        if target_artifacts:
            artifacts_by_target.setdefault(target_id, []).extend(dict(ref) for ref in target_artifacts[:8])
    for claim in claims:
        claim_id = str(claim.get("id") or "").strip()
        for target_ref in claim.get("coverage_targets") or []:
            target_id = str(target_ref.get("id") or "").strip()
            if not target_id:
                continue
            claims_by_target.setdefault(target_id, []).append(claim_id)
            artifacts_by_target.setdefault(target_id, []).extend(list(claim.get("artifact_refs") or [])[:4])
    rows = []
    for target_id, target in targets_by_id.items():
        for evidence_ref in list(target.get("evidence_refs") or []):
            claim = claims_by_id.get(str(evidence_ref or "").strip())
            if not claim:
                continue
            claims_by_target.setdefault(target_id, []).append(str(claim.get("id") or "").strip())
            artifacts_by_target.setdefault(target_id, []).extend(list(claim.get("artifact_refs") or [])[:4])
        rows.append(
            {
                "id": target_id,
                "kind": str(target.get("kind") or "").strip(),
                "label": str(target.get("label") or target_id).strip(),
                "status": str(target.get("status") or "missing").strip(),
                "required": coverage_target_is_required(target, target_id=target_id),
                "claim_refs": list(dict.fromkeys(claims_by_target.get(target_id, []))),
                "artifact_refs": _dedupe_artifact_refs(artifacts_by_target.get(target_id, []))[:8],
            }
        )
    return rows


def _dedupe_artifact_refs(value: object) -> list[dict]:
    refs: list[dict] = []
    seen: set[tuple[str, str, str, str]] = set()
    for ref in list(value or []):
        if not isinstance(ref, Mapping):
            continue
        key = (
            str(ref.get("label") or "").strip(),
            str(ref.get("absolute_path") or "").strip(),
            str(ref.get("workspace_path") or "").strip(),
            str(ref.get("relative_path") or "").strip(),
        )
        if key in seen:
            continue
        seen.add(key)
        refs.append(dict(ref))
    return refs


def _manifest_problems(claims: list[dict]) -> list[dict]:
    problems = []
    for claim in claims:
        claim_id = str(claim.get("id") or "").strip()
        if claim.get("verification_status") == "ledger_only":
            problems.append(
                {
                    "code": "claim_without_artifact",
                    "claim_id": claim_id,
                    "severity": "weak",
                    "message": "Evidence claim has no artifact refs.",
                }
            )
        missing_artifacts = [
            str(ref.get("label") or ref.get("relative_path") or "").strip() for ref in claim.get("artifact_refs") or [] if not ref.get("exists")
        ]
        if missing_artifacts:
            problems.append(
                {
                    "code": "claim_artifact_missing",
                    "claim_id": claim_id,
                    "severity": "weak",
                    "message": "Evidence claim references missing artifacts.",
                    "artifacts": missing_artifacts[:6],
                }
            )
    return problems[:40]


def _safe_read_json_artifact(path: Path) -> dict:
    try:
        payload = read_json(path)
    except (OSError, UnicodeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _safe_int(value: object) -> int:
    return structured_non_negative_int(value)
