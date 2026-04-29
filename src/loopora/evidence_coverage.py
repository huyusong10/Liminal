from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Any

from loopora.run_artifacts import RunArtifactLayout, read_jsonl
from loopora.utils import read_json, utc_now, write_json

POSITIVE_COVERAGE_STATUSES = {"passed", "pass", "ok", "success", "succeeded", "completed", "covered", "satisfied", "guarded", "verified"}
WEAK_COVERAGE_STATUSES = {"partial", "weak", "skipped", "unknown", "inconclusive"}
NEGATIVE_COVERAGE_STATUSES = {"failed", "fail", "error", "errored", "blocked", "rejected", "missing"}
REQUIRED_TARGET_KINDS = {"done_when", "gatekeeper"}


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
                "text": "GateKeeper may finish only after citing upstream evidence ledger refs.",
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
        except Exception:
            payload = {}
        if isinstance(payload, dict) and payload.get("schema_version") == 1:
            return payload
    return build_evidence_coverage_projection(layout)


def build_evidence_coverage_projection(layout: RunArtifactLayout) -> dict:
    compiled_spec = read_json(layout.contract_compiled_spec_path)
    run_contract = read_json(layout.run_contract_path)
    completion_mode = str(run_contract.get("completion_mode") or "gatekeeper").strip().lower() or "gatekeeper"
    targets = build_coverage_targets(compiled_spec, completion_mode=completion_mode)
    ledger_exists = layout.evidence_ledger_path.exists()
    evidence_items = read_jsonl(layout.evidence_ledger_path)
    target_state = _initial_target_state(targets)
    evidence_kind_counts: Counter[str] = Counter()
    artifact_ref_count = 0
    risk_signals: list[str] = []
    latest_gatekeeper: dict = {}

    if not ledger_exists:
        status = "legacy"
    elif not evidence_items:
        status = "pending"
    else:
        for item in evidence_items:
            if not isinstance(item, Mapping):
                continue
            item_id = str(item.get("id") or "").strip()
            kind = str(item.get("evidence_kind") or "observation").strip() or "observation"
            evidence_kind_counts[kind] += 1
            artifact_refs = item.get("artifact_refs") if isinstance(item.get("artifact_refs"), list) else []
            artifact_ref_count += len(artifact_refs)
            risk = _clean_text(item.get("residual_risk"), max_length=240)
            if _is_meaningful_residual_risk(risk):
                risk_signals.append(risk)

            for verify_ref in list(item.get("verifies") or []):
                parsed = parse_target_verify_ref(verify_ref)
                if not parsed:
                    continue
                target_id, target_status = parsed
                if target_id in target_state:
                    _apply_target_evidence(
                        target_state[target_id],
                        status=target_status,
                        evidence_id=item_id,
                        item=item,
                    )

            if str(item.get("archetype") or "").strip().lower() == "gatekeeper":
                gatekeeper_refs = [
                    str(ref).split(":", 1)[1].strip()
                    for ref in list(item.get("verifies") or [])
                    if str(ref).startswith("evidence:") and str(ref).split(":", 1)[1].strip()
                ]
                latest_gatekeeper = {
                    "id": item_id,
                    "result": str(item.get("result") or "").strip(),
                    "evidence_refs": gatekeeper_refs,
                    "residual_risk": risk,
                }

        _apply_gatekeeper_target(target_state, latest_gatekeeper)
        status = _overall_coverage_status(target_state)

    target_rows = [_target_projection(row) for row in target_state.values()]
    top_gaps = _top_coverage_gaps(target_rows)
    covered_check_ids = [
        row["source_id"]
        for row in target_rows
        if row["kind"] == "done_when" and row["status"] == "covered"
    ]
    missing_check_ids = [
        row["source_id"]
        for row in target_rows
        if row["kind"] == "done_when" and row["status"] != "covered"
    ]
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


def _apply_target_evidence(row: dict, *, status: str, evidence_id: str, item: Mapping[str, Any]) -> None:
    normalized = str(status or "unknown").strip().lower()
    if normalized in NEGATIVE_COVERAGE_STATUSES:
        row["status"] = "blocked"
        row["reason"] = "Evidence reported this coverage target as blocked or failed."
    elif normalized in POSITIVE_COVERAGE_STATUSES:
        row["status"] = "covered"
        row["reason"] = "Evidence verified this coverage target."
    elif normalized in WEAK_COVERAGE_STATUSES:
        row["status"] = "weak"
        row["reason"] = "Evidence for this coverage target is present but weak or inconclusive."
    if evidence_id:
        row["evidence_refs"] = list(dict.fromkeys([*list(row.get("evidence_refs") or []), evidence_id]))
    artifact_refs = item.get("artifact_refs") if isinstance(item.get("artifact_refs"), list) else []
    if artifact_refs:
        row["artifact_refs"] = list(row.get("artifact_refs") or []) + artifact_refs[:8]


def _apply_gatekeeper_target(target_state: dict[str, dict], latest_gatekeeper: Mapping[str, Any]) -> None:
    row = target_state.get("gatekeeper.finish")
    if not row or not latest_gatekeeper:
        return
    result = str(latest_gatekeeper.get("result") or "").strip().lower()
    evidence_refs = [str(item).strip() for item in list(latest_gatekeeper.get("evidence_refs") or []) if str(item).strip()]
    if result == "passed" and evidence_refs:
        row["status"] = "covered"
        row["reason"] = "GateKeeper passed with upstream evidence refs."
        row["evidence_refs"] = list(dict.fromkeys([*evidence_refs, str(latest_gatekeeper.get("id") or "").strip()]))
    elif result in {"blocked", "failed", "rejected"}:
        row["status"] = "blocked"
        row["reason"] = "GateKeeper blocked the run."
        gatekeeper_id = str(latest_gatekeeper.get("id") or "").strip()
        row["evidence_refs"] = [gatekeeper_id] if gatekeeper_id else []


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
    text = _clean_text(value, max_length=240).lower()
    if not text:
        return False
    return text not in {
        "no blocking residual risk was reported by gatekeeper.",
        "no blocking residual risk was reported by gatekeeper",
    }
