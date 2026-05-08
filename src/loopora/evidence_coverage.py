from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Any

from loopora.evidence_support import evidence_item_is_non_supporting_gatekeeper_ref, evidence_item_is_supporting_gatekeeper_ref
from loopora.run_artifacts import RunArtifactLayout, read_jsonl
from loopora.utils import read_json, utc_now, write_json

POSITIVE_COVERAGE_STATUSES = {"passed", "pass", "ok", "success", "succeeded", "completed", "covered", "satisfied", "guarded", "verified"}
WEAK_COVERAGE_STATUSES = {"partial", "weak", "skipped", "unknown", "inconclusive"}
NEGATIVE_COVERAGE_STATUSES = {"failed", "fail", "error", "errored", "blocked", "rejected", "missing"}
REQUIRED_TARGET_KINDS = {"done_when", "gatekeeper"}
NO_RESIDUAL_RISK_MARKERS = {
    "none",
    "n/a",
    "na",
    "no residual risk",
    "no blocking residual risk",
    "no blocking residual risk was reported by gatekeeper",
    "no meaningful residual risk",
    "无",
    "无残余风险",
    "没有残余风险",
    "没有阻断残余风险",
}


def with_coverage_targets(compiled_spec: Mapping[str, Any], *, completion_mode: str = "gatekeeper") -> dict:
    spec = dict(compiled_spec)
    spec["coverage_targets"] = build_coverage_targets(spec, completion_mode=completion_mode)
    return spec


def build_coverage_targets(compiled_spec: Mapping[str, Any], *, completion_mode: str = "gatekeeper") -> list[dict]:
    targets: list[dict] = []
    for check in list(compiled_spec.get("checks") or []):
        if not isinstance(check, Mapping):
            continue
        check_id = str(check.get("id") or "").strip()
        if not check_id:
            continue
        title = str(check.get("title") or check_id).strip()
        text = str(check.get("details") or check.get("expect") or title).strip()
        targets.append(
            {
                "id": f"done_when.{check_id}",
                "kind": "done_when",
                "source_section": "Done When",
                "source_id": check_id,
                "label": title,
                "text": text,
                "required": True,
            }
        )

    for index, text in enumerate(_string_list(compiled_spec.get("fake_done_states")), start=1):
        targets.append(
            {
                "id": f"fake_done.risk_{index:03d}",
                "kind": "fake_done",
                "source_section": "Fake Done",
                "source_id": f"risk_{index:03d}",
                "label": f"Fake Done risk {index}",
                "text": text,
                "required": False,
            }
        )

    for index, text in enumerate(_string_list(compiled_spec.get("evidence_preferences")), start=1):
        targets.append(
            {
                "id": f"evidence_preference.pref_{index:03d}",
                "kind": "evidence_preference",
                "source_section": "Evidence Preferences",
                "source_id": f"pref_{index:03d}",
                "label": f"Evidence preference {index}",
                "text": text,
                "required": False,
            }
        )

    if str(completion_mode or "gatekeeper").strip().lower() == "gatekeeper":
        targets.append(
            {
                "id": "gatekeeper.finish",
                "kind": "gatekeeper",
                "source_section": "Workflow",
                "source_id": "finish",
                "label": "GateKeeper finish",
                "text": "GateKeeper may finish only after citing supporting upstream evidence refs or measured self evidence.",
                "required": True,
            }
        )
    return targets


def write_evidence_coverage_projection(layout: RunArtifactLayout) -> dict:
    projection = build_evidence_coverage_projection(layout)
    write_json(layout.evidence_coverage_path, projection)
    return projection


def load_or_build_evidence_coverage_projection(layout: RunArtifactLayout) -> dict:
    if layout.evidence_coverage_path.exists():
        try:
            payload = read_json(layout.evidence_coverage_path)
        except (OSError, UnicodeError, ValueError):
            payload = {}
        if isinstance(payload, dict) and payload.get("schema_version") == 1:
            return payload
    return build_evidence_coverage_projection(layout)


def build_evidence_coverage_projection(layout: RunArtifactLayout) -> dict:
    compiled_spec = _safe_read_json_artifact(layout.contract_compiled_spec_path)
    run_contract = _safe_read_json_artifact(layout.run_contract_path)
    completion_mode = str(run_contract.get("completion_mode") or "gatekeeper").strip().lower() or "gatekeeper"
    targets = build_coverage_targets(compiled_spec, completion_mode=completion_mode)
    ledger_exists = layout.evidence_ledger_path.exists()
    evidence_items = read_jsonl(layout.evidence_ledger_path)
    target_state = _initial_target_state(targets)
    evidence_kind_counts: Counter[str] = Counter()
    artifact_ref_count = 0
    risk_signals: list[str] = []
    latest_gatekeeper: dict = {}
    evidence_items_by_id: dict[str, Mapping[str, Any]] = {}

    if not ledger_exists:
        status = "legacy"
    elif not evidence_items:
        status = "pending"
    else:
        for item in evidence_items:
            item_projection = _collect_coverage_evidence_item(
                item,
                target_state=target_state,
                evidence_items_by_id=evidence_items_by_id,
                evidence_kind_counts=evidence_kind_counts,
            )
            if not item_projection:
                continue
            artifact_ref_count += int(item_projection.get("artifact_ref_count") or 0)
            risk = str(item_projection.get("risk") or "")
            if risk:
                risk_signals.append(risk)
            if item_projection.get("latest_gatekeeper"):
                latest_gatekeeper = dict(item_projection["latest_gatekeeper"])

        _apply_gatekeeper_target(target_state, latest_gatekeeper)
        status = _overall_coverage_status(target_state)

    target_rows = [_target_projection(row) for row in target_state.values()]
    top_gaps = _top_coverage_gaps(target_rows)
    covered_check_ids = [row["source_id"] for row in target_rows if row["kind"] == "done_when" and row["status"] == "covered"]
    missing_check_ids = [row["source_id"] for row in target_rows if row["kind"] == "done_when" and row["status"] != "covered"]
    summary = _coverage_summary(status, top_gaps)
    return {
        "schema_version": 1,
        "generated_at": utc_now(),
        "ledger_path": layout.relative(layout.evidence_ledger_path),
        "coverage_path": layout.relative(layout.evidence_coverage_path),
        "status": status,
        "summary": summary,
        "target_count": len(target_rows),
        "covered_target_count": sum(1 for row in target_rows if row["status"] == "covered"),
        "weak_target_count": sum(1 for row in target_rows if row["status"] == "weak"),
        "missing_target_count": sum(1 for row in target_rows if row["status"] == "missing"),
        "blocked_target_count": sum(1 for row in target_rows if row["status"] == "blocked"),
        "check_count": len([row for row in target_rows if row["kind"] == "done_when"]),
        "covered_check_count": len(covered_check_ids),
        "missing_check_count": len(missing_check_ids),
        "covered_check_ids": covered_check_ids,
        "missing_check_ids": missing_check_ids,
        "evidence_count": len(evidence_items),
        "evidence_kind_counts": dict(evidence_kind_counts),
        "artifact_ref_count": artifact_ref_count,
        "residual_risk_count": len(risk_signals),
        "risk_signals": list(dict.fromkeys(risk_signals))[:5],
        "latest_gatekeeper": latest_gatekeeper,
        "top_gaps": top_gaps,
        "targets": target_rows,
    }


def _safe_read_json_artifact(path) -> dict:
    try:
        payload = read_json(path)
    except (OSError, UnicodeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def summarize_evidence_coverage_projection(projection: Mapping[str, Any], *, coverage_path_available: bool = True) -> dict:
    coverage_path = str(projection.get("coverage_path") or "").strip() if coverage_path_available else ""
    return {
        "ledger_path": str(projection.get("ledger_path") or ""),
        "coverage_path": coverage_path,
        "status": str(projection.get("status") or "pending"),
        "summary": dict(projection.get("summary") or {}),
        "evidence_count": int(projection.get("evidence_count") or 0),
        "check_count": int(projection.get("check_count") or 0),
        "covered_check_count": int(projection.get("covered_check_count") or 0),
        "missing_check_count": int(projection.get("missing_check_count") or 0),
        "covered_check_ids": list(projection.get("covered_check_ids") or []),
        "missing_check_ids": list(projection.get("missing_check_ids") or []),
        "target_count": int(projection.get("target_count") or 0),
        "covered_target_count": int(projection.get("covered_target_count") or 0),
        "weak_target_count": int(projection.get("weak_target_count") or 0),
        "missing_target_count": int(projection.get("missing_target_count") or 0),
        "blocked_target_count": int(projection.get("blocked_target_count") or 0),
        "top_gaps": list(projection.get("top_gaps") or [])[:5],
        "evidence_kind_counts": dict(projection.get("evidence_kind_counts") or {}),
        "artifact_ref_count": int(projection.get("artifact_ref_count") or 0),
        "residual_risk_count": int(projection.get("residual_risk_count") or 0),
        "risk_signals": list(projection.get("risk_signals") or [])[:5],
        "latest_gatekeeper": dict(projection.get("latest_gatekeeper") or {}),
    }


def parse_target_verify_ref(value: object) -> tuple[str, str] | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.startswith("target:"):
        parts = text.split(":", 2)
        if len(parts) == 3 and parts[1].strip():
            return parts[1].strip(), parts[2].strip() or "unknown"
    if text.startswith(("check_results:", "dynamic_checks:")):
        parts = text.split(":", 2)
        if len(parts) >= 2 and parts[1].strip():
            return f"done_when.{parts[1].strip()}", parts[2].strip() if len(parts) == 3 else "unknown"
    if text.startswith("check:"):
        check_id = text.split(":", 1)[1].strip()
        if check_id:
            return f"done_when.{check_id}", "failed"
    return None


def _initial_target_state(targets: list[dict]) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for target in targets:
        target_id = str(target.get("id") or "").strip()
        if not target_id or target_id in rows:
            continue
        rows[target_id] = {
            **target,
            "status": "missing",
            "reason": "No evidence has verified this coverage target.",
            "evidence_refs": [],
            "artifact_refs": [],
        }
    return rows


def _collect_coverage_evidence_item(
    item: object,
    *,
    target_state: dict[str, dict],
    evidence_items_by_id: dict[str, Mapping[str, Any]],
    evidence_kind_counts: Counter[str],
) -> dict:
    if not isinstance(item, Mapping):
        return {}
    item_id = str(item.get("id") or "").strip()
    if item_id:
        evidence_items_by_id[item_id] = item
    kind = str(item.get("evidence_kind") or "observation").strip() or "observation"
    evidence_kind_counts[kind] += 1
    artifact_refs = item.get("artifact_refs") if isinstance(item.get("artifact_refs"), list) else []
    risk = _clean_text(item.get("residual_risk"), max_length=240)

    coverage_result_target_ids: set[str] = set()
    for coverage_result in _coverage_result_rows(item.get("coverage_results")):
        target_id = coverage_result["target_id"]
        if target_id not in target_state:
            continue
        coverage_result_target_ids.add(target_id)
        _apply_target_evidence(
            target_state[target_id],
            status=coverage_result["status"],
            item=item,
            evidence_items_by_id=evidence_items_by_id,
            target_evidence_refs=coverage_result["evidence_refs"],
        )

    for verify_ref in list(item.get("verifies") or []):
        parsed = parse_target_verify_ref(verify_ref)
        if not parsed:
            continue
        target_id, target_status = parsed
        if target_id in coverage_result_target_ids:
            continue
        if target_id in target_state:
            _apply_target_evidence(
                target_state[target_id],
                status=target_status,
                item=item,
                evidence_items_by_id=evidence_items_by_id,
                target_evidence_refs=None,
            )

    return {
        "artifact_ref_count": len(artifact_refs),
        "risk": risk if _is_meaningful_residual_risk(risk) else "",
        "latest_gatekeeper": _latest_gatekeeper_projection(item, item_id=item_id, risk=risk, evidence_items_by_id=evidence_items_by_id),
    }


def _latest_gatekeeper_projection(
    item: Mapping[str, Any],
    *,
    item_id: str,
    risk: str,
    evidence_items_by_id: Mapping[str, Mapping[str, Any]],
) -> dict:
    if str(item.get("archetype") or "").strip().lower() != "gatekeeper":
        return {}
    gatekeeper_refs = [
        str(ref).split(":", 1)[1].strip() for ref in list(item.get("verifies") or []) if str(ref).startswith("evidence:") and str(ref).split(":", 1)[1].strip()
    ]
    return {
        "id": item_id,
        "result": str(item.get("result") or "").strip(),
        "evidence_refs": gatekeeper_refs,
        "supporting_evidence_refs": _supporting_gatekeeper_refs(gatekeeper_refs, evidence_items_by_id),
        "non_supporting_evidence_refs": _non_supporting_gatekeeper_refs(gatekeeper_refs, evidence_items_by_id, current_id=item_id),
        "self_measured_evidence": _gatekeeper_has_self_measured_evidence(item, item_id=item_id, evidence_refs=gatekeeper_refs),
        "self_evidence_claim_count": _safe_int(item.get("concrete_evidence_claim_count")),
        "residual_risk": risk,
    }


def _apply_target_evidence(
    row: dict,
    *,
    status: str,
    item: Mapping[str, Any],
    evidence_items_by_id: Mapping[str, Mapping[str, Any]],
    target_evidence_refs: list[str] | None,
) -> None:
    normalized = str(status or "unknown").strip().lower()
    evidence_id = str(item.get("id") or "").strip()
    supporting_refs = _target_supporting_refs(
        item=item,
        evidence_items_by_id=evidence_items_by_id,
        target_evidence_refs=target_evidence_refs,
    )
    if normalized in NEGATIVE_COVERAGE_STATUSES:
        row["status"] = "blocked"
        row["reason"] = "Evidence reported this coverage target as blocked or failed."
    elif normalized in POSITIVE_COVERAGE_STATUSES:
        if supporting_refs:
            row["status"] = "covered"
            row["reason"] = "Supporting evidence verified this coverage target."
        else:
            row["status"] = "weak"
            row["reason"] = "Coverage was reported as positive without supporting evidence."
    elif normalized in WEAK_COVERAGE_STATUSES:
        row["status"] = "weak"
        row["reason"] = "Evidence for this coverage target is present but weak or inconclusive."
    evidence_refs = supporting_refs or ([evidence_id] if evidence_id else [])
    if evidence_refs:
        row["evidence_refs"] = list(dict.fromkeys([*list(row.get("evidence_refs") or []), *evidence_refs]))
    artifact_refs = _target_artifact_refs(item=item, supporting_refs=supporting_refs, evidence_items_by_id=evidence_items_by_id)
    if artifact_refs:
        row["artifact_refs"] = list(row.get("artifact_refs") or []) + artifact_refs[:8]


def _target_supporting_refs(
    *,
    item: Mapping[str, Any],
    evidence_items_by_id: Mapping[str, Mapping[str, Any]],
    target_evidence_refs: list[str] | None,
) -> list[str]:
    refs: list[str] = []
    evidence_id = str(item.get("id") or "").strip()
    if evidence_id and evidence_item_is_supporting_gatekeeper_ref(item):
        refs.append(evidence_id)
    if evidence_id and _gatekeeper_has_self_measured_evidence(item, item_id=evidence_id, evidence_refs=[evidence_id]):
        refs.append(evidence_id)
    related_ids = target_evidence_refs if target_evidence_refs is not None else _string_list(item.get("related_evidence_ids"))
    for related_id in related_ids:
        related_item = evidence_items_by_id.get(related_id)
        if related_item and evidence_item_is_supporting_gatekeeper_ref(related_item):
            refs.append(related_id)
    return list(dict.fromkeys(refs))


def _coverage_result_rows(value: object) -> list[dict]:
    if not isinstance(value, list):
        return []
    rows: list[dict] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        target_id = str(item.get("target_id") or "").strip()
        if not target_id or ":" in target_id:
            continue
        rows.append(
            {
                "target_id": target_id,
                "status": str(item.get("status") or "unknown").strip() or "unknown",
                "evidence_refs": _string_list(item.get("evidence_refs")),
            }
        )
    return rows


def _target_artifact_refs(
    *,
    item: Mapping[str, Any],
    supporting_refs: list[str],
    evidence_items_by_id: Mapping[str, Mapping[str, Any]],
) -> list[dict]:
    refs: list[dict] = []
    if not supporting_refs:
        return list(item.get("artifact_refs") or []) if isinstance(item.get("artifact_refs"), list) else []
    for evidence_id in supporting_refs:
        source_item = evidence_items_by_id.get(evidence_id)
        if not source_item:
            continue
        artifact_refs = source_item.get("artifact_refs") if isinstance(source_item.get("artifact_refs"), list) else []
        refs.extend(ref for ref in artifact_refs if isinstance(ref, dict))
    return refs


def _apply_gatekeeper_target(target_state: dict[str, dict], latest_gatekeeper: Mapping[str, Any]) -> None:
    row = target_state.get("gatekeeper.finish")
    if not row or not latest_gatekeeper:
        return
    result = str(latest_gatekeeper.get("result") or "").strip().lower()
    gatekeeper_id = str(latest_gatekeeper.get("id") or "").strip()
    evidence_refs = [str(item).strip() for item in list(latest_gatekeeper.get("evidence_refs") or []) if str(item).strip()]
    supporting_refs = [str(item).strip() for item in list(latest_gatekeeper.get("supporting_evidence_refs") or []) if str(item).strip()]
    non_supporting_refs = [str(item).strip() for item in list(latest_gatekeeper.get("non_supporting_evidence_refs") or []) if str(item).strip()]
    has_self_measured_evidence = bool(latest_gatekeeper.get("self_measured_evidence"))
    if result == "passed" and supporting_refs:
        row["status"] = "covered"
        row["reason"] = "GateKeeper passed with supporting upstream evidence refs."
        row["evidence_refs"] = list(dict.fromkeys([*supporting_refs, gatekeeper_id]))
    elif result == "passed" and has_self_measured_evidence:
        row["status"] = "covered"
        row["reason"] = "GateKeeper passed with measured self evidence and concrete evidence claims."
        row["evidence_refs"] = [gatekeeper_id] if gatekeeper_id else []
    elif result == "passed" and evidence_refs and non_supporting_refs and not supporting_refs:
        row["status"] = "blocked"
        row["reason"] = "GateKeeper pass cited only non-supporting upstream evidence refs."
        row["evidence_refs"] = list(dict.fromkeys([*non_supporting_refs, gatekeeper_id]))
    elif result in {"blocked", "failed", "rejected"}:
        row["status"] = "blocked"
        row["reason"] = "GateKeeper blocked the run."
        row["evidence_refs"] = [gatekeeper_id] if gatekeeper_id else []


def _supporting_gatekeeper_refs(evidence_refs: list[str], evidence_items_by_id: Mapping[str, Mapping[str, Any]]) -> list[str]:
    refs: list[str] = []
    for ref in evidence_refs:
        item = evidence_items_by_id.get(str(ref).strip())
        if not item:
            continue
        if evidence_item_is_supporting_gatekeeper_ref(item):
            refs.append(str(ref).strip())
    return list(dict.fromkeys(refs))


def _non_supporting_gatekeeper_refs(
    evidence_refs: list[str],
    evidence_items_by_id: Mapping[str, Mapping[str, Any]],
    *,
    current_id: str,
) -> list[str]:
    refs: list[str] = []
    for ref in evidence_refs:
        if str(ref).strip() == str(current_id or "").strip():
            continue
        item = evidence_items_by_id.get(str(ref).strip())
        if not item:
            continue
        if evidence_item_is_non_supporting_gatekeeper_ref(item):
            refs.append(str(ref).strip())
    return list(dict.fromkeys(refs))


def _gatekeeper_has_self_measured_evidence(item: Mapping[str, Any], *, item_id: str, evidence_refs: list[str]) -> bool:
    if not item_id or item_id not in set(evidence_refs):
        return False
    return bool(item.get("measured_evidence")) and _safe_int(item.get("concrete_evidence_claim_count")) > 0


def _safe_int(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _overall_coverage_status(target_state: Mapping[str, dict]) -> str:
    rows = list(target_state.values())
    if any(row.get("required") and row.get("status") == "blocked" for row in rows):
        return "blocked"
    if any(row.get("required") and row.get("status") != "covered" for row in rows):
        return "partial"
    if any((not row.get("required")) and row.get("status") in {"missing", "weak", "blocked"} for row in rows):
        return "weak"
    return "covered"


def _target_projection(row: Mapping[str, Any]) -> dict:
    return {
        "id": str(row.get("id") or ""),
        "kind": str(row.get("kind") or ""),
        "source_section": str(row.get("source_section") or ""),
        "source_id": str(row.get("source_id") or ""),
        "label": str(row.get("label") or ""),
        "text": str(row.get("text") or ""),
        "required": bool(row.get("required")),
        "status": str(row.get("status") or "missing"),
        "reason": str(row.get("reason") or ""),
        "evidence_refs": list(row.get("evidence_refs") or []),
        "artifact_refs": list(row.get("artifact_refs") or [])[:12],
    }


def _top_coverage_gaps(target_rows: list[dict]) -> list[dict]:
    severity = {"blocked": 0, "missing": 1, "weak": 2}
    gaps = [row for row in target_rows if row.get("status") != "covered"]
    gaps.sort(key=lambda row: (0 if row.get("required") else 1, severity.get(str(row.get("status")), 9), str(row.get("id"))))
    return [
        {
            "target_id": row["id"],
            "kind": row["kind"],
            "source_section": row["source_section"],
            "status": row["status"],
            "required": row["required"],
            "reason": row["reason"],
            "text": row["text"],
            "evidence_refs": row["evidence_refs"],
        }
        for row in gaps[:5]
    ]


def _coverage_summary(status: str, top_gaps: list[dict]) -> dict:
    if status == "covered":
        reason = "Required and advisory coverage targets have supporting evidence."
    elif status == "weak":
        reason = "Required targets are covered, but advisory evidence is incomplete."
    elif status == "partial":
        reason = "Required coverage targets still lack direct evidence."
    elif status == "blocked":
        reason = "GateKeeper or target evidence reported a blocker."
    elif status == "legacy":
        reason = "This run does not have a readable evidence ledger."
    else:
        reason = "No evidence ledger entries are available yet."
    return {
        "status": status,
        "reason": reason,
        "primary_gap": top_gaps[0] if top_gaps else {},
    }


def _string_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _clean_text(value: object, *, max_length: int = 500) -> str:
    text = " ".join(str(value or "").split()).strip()
    if len(text) > max_length:
        return text[: max_length - 1].rstrip() + "…"
    return text


def _is_meaningful_residual_risk(value: object) -> bool:
    text = _clean_text(value, max_length=240)
    normalized = text.lower().strip(" .。")
    if not normalized:
        return False
    if normalized in NO_RESIDUAL_RISK_MARKERS:
        return False
    return not (normalized.startswith("no ") and "residual risk" in normalized)
