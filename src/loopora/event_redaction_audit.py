from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loopora.event_redaction import redact_alignment_event_payload, redact_run_event_payload
from loopora.branding import state_dir_for_workdir
from loopora.run_artifacts import RunArtifactLayout
from loopora.settings import load_recent_workdirs


def audit_event_redaction(repository, *, fix: bool = False) -> dict:
    run_db_report = _audit_db_events(repository, fix=fix)
    timeline_report = _audit_timeline_files(repository, fix=fix)
    alignment_db_report = _audit_alignment_db_events(repository, fix=fix)
    alignment_file_report = _audit_alignment_event_files(repository, fix=fix)
    return {
        "mode": "fix" if fix else "dry-run",
        "db_events": run_db_report,
        "timeline_files": timeline_report,
        "alignment_db_events": alignment_db_report,
        "alignment_event_files": alignment_file_report,
        "fixed": int(run_db_report["fixed"])
        + int(timeline_report["fixed"])
        + int(alignment_db_report["fixed"])
        + int(alignment_file_report["fixed"]),
        "suspect": int(run_db_report["suspect"])
        + int(timeline_report["suspect"])
        + int(alignment_db_report["suspect"])
        + int(alignment_file_report["suspect"]),
        "unfixable": [
            *run_db_report["unfixable"],
            *timeline_report["unfixable"],
            *alignment_db_report["unfixable"],
            *alignment_file_report["unfixable"],
        ],
    }


def audit_run_event_redaction(repository, *, fix: bool = False) -> dict:
    return audit_event_redaction(repository, fix=fix)


def _audit_db_events(repository, *, fix: bool) -> dict:
    scanned = 0
    suspect = 0
    fixed = 0
    samples = []
    unfixable = []
    for event in repository.list_run_events_for_redaction_audit():
        scanned += 1
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        redacted = redact_run_event_payload(str(event.get("event_type") or ""), payload)
        if _canonical(redacted) == _canonical(payload):
            continue
        suspect += 1
        samples.append(_event_sample("db", event, redacted))
        if fix:
            if repository.update_run_event_payload_for_redaction(int(event["id"]), redacted):
                fixed += 1
            else:
                unfixable.append({"source": "db", "event_id": event.get("id"), "reason": "update_failed"})
    return {
        "scanned": scanned,
        "suspect": suspect,
        "fixed": fixed,
        "samples": samples[:20],
        "unfixable": unfixable,
    }


def _audit_timeline_files(repository, *, fix: bool) -> dict:
    scanned_files = 0
    scanned_events = 0
    suspect = 0
    fixed = 0
    samples = []
    unfixable = []
    seen_paths: set[Path] = set()
    for runs_dir in _candidate_run_dirs(repository):
        layout = RunArtifactLayout(Path(runs_dir))
        for path in (layout.timeline_events_path, layout.legacy_events_path):
            if path in seen_paths:
                continue
            seen_paths.add(path)
            if not path.exists():
                continue
            scanned_files += 1
            file_report = _audit_event_jsonl_file(path, fix=fix, redactor=redact_run_event_payload, sample_source="timeline")
            scanned_events += file_report["scanned"]
            suspect += file_report["suspect"]
            fixed += file_report["fixed"]
            samples.extend(file_report["samples"])
            unfixable.extend(file_report["unfixable"])
    return {
        "scanned_files": scanned_files,
        "scanned_events": scanned_events,
        "suspect": suspect,
        "fixed": fixed,
        "samples": samples[:20],
        "unfixable": unfixable,
    }


def _candidate_run_dirs(repository) -> list[Path]:
    candidates: list[Path] = []
    seen: set[Path] = set()

    for event in repository.list_run_events_for_redaction_audit():
        _add_candidate_path(candidates, seen, event.get("runs_dir"))

    if hasattr(repository, "list_local_asset_roots"):
        for row in repository.list_local_asset_roots(resource_type="run", states={"active", "orphaned"}):
            _add_candidate_path(candidates, seen, row.get("path"))

    for workdir in load_recent_workdirs(limit=100):
        root = state_dir_for_workdir(workdir) / "runs"
        if not root.exists():
            continue
        for run_dir in sorted(item for item in root.iterdir() if item.is_dir()):
            _add_candidate_path(candidates, seen, run_dir)

    return candidates


def _audit_alignment_db_events(repository, *, fix: bool) -> dict:
    scanned = 0
    suspect = 0
    fixed = 0
    samples = []
    unfixable = []
    if not hasattr(repository, "list_alignment_events_for_redaction_audit"):
        return {"scanned": 0, "suspect": 0, "fixed": 0, "samples": [], "unfixable": []}
    for event in repository.list_alignment_events_for_redaction_audit():
        scanned += 1
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        redacted = redact_alignment_event_payload(str(event.get("event_type") or ""), payload)
        if _canonical(redacted) == _canonical(payload):
            continue
        suspect += 1
        samples.append(_event_sample("alignment_db", event, redacted))
        if fix:
            if repository.update_alignment_event_payload_for_redaction(int(event["id"]), redacted):
                fixed += 1
            else:
                unfixable.append({"source": "alignment_db", "event_id": event.get("id"), "reason": "update_failed"})
    return {
        "scanned": scanned,
        "suspect": suspect,
        "fixed": fixed,
        "samples": samples[:20],
        "unfixable": unfixable,
    }


def _audit_alignment_event_files(repository, *, fix: bool) -> dict:
    scanned_files = 0
    scanned_events = 0
    suspect = 0
    fixed = 0
    samples = []
    unfixable = []
    seen_paths: set[Path] = set()
    for session_dir in _candidate_alignment_session_dirs(repository):
        path = Path(session_dir) / "events" / "events.jsonl"
        if path in seen_paths:
            continue
        seen_paths.add(path)
        if not path.exists():
            continue
        scanned_files += 1
        file_report = _audit_event_jsonl_file(
            path,
            fix=fix,
            redactor=redact_alignment_event_payload,
            sample_source="alignment_file",
        )
        scanned_events += file_report["scanned"]
        suspect += file_report["suspect"]
        fixed += file_report["fixed"]
        samples.extend(file_report["samples"])
        unfixable.extend(file_report["unfixable"])
    return {
        "scanned_files": scanned_files,
        "scanned_events": scanned_events,
        "suspect": suspect,
        "fixed": fixed,
        "samples": samples[:20],
        "unfixable": unfixable,
    }


def _candidate_alignment_session_dirs(repository) -> list[Path]:
    candidates: list[Path] = []
    seen: set[Path] = set()

    if hasattr(repository, "list_alignment_events_for_redaction_audit"):
        for event in repository.list_alignment_events_for_redaction_audit():
            bundle_path = str(event.get("bundle_path") or "").strip()
            if bundle_path:
                _add_candidate_path(candidates, seen, _alignment_event_artifact_root(Path(bundle_path)))

    if hasattr(repository, "list_local_asset_roots"):
        for row in repository.list_local_asset_roots(resource_type="alignment_session", states={"active", "orphaned"}):
            _add_candidate_path(candidates, seen, row.get("path"))

    for workdir in load_recent_workdirs(limit=100):
        root = state_dir_for_workdir(workdir) / "alignment_sessions"
        if not root.exists():
            continue
        for session_dir in sorted(item for item in root.iterdir() if item.is_dir()):
            _add_candidate_path(candidates, seen, session_dir)

    return candidates


def _add_candidate_path(candidates: list[Path], seen: set[Path], path: object) -> None:
    text = str(path or "").strip()
    if not text:
        return
    candidate = Path(text).expanduser()
    if candidate in seen:
        return
    seen.add(candidate)
    candidates.append(candidate)


def _alignment_event_artifact_root(bundle_path: Path) -> Path:
    return bundle_path.parent.parent if bundle_path.parent.name == "artifacts" else bundle_path.parent


def _audit_event_jsonl_file(path: Path, *, fix: bool, redactor, sample_source: str) -> dict:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        return {
            "scanned": 0,
            "suspect": 0,
            "fixed": 0,
            "samples": [],
            "unfixable": [
                {
                    "source": sample_source,
                    "path": str(path),
                    "reason": "read_failed",
                    "error_type": type(exc).__name__,
                }
            ],
        }
    next_lines: list[str] = []
    scanned = 0
    suspect = 0
    fixed = 0
    pending_fixed = 0
    samples = []
    unfixable = []
    changed = False
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            next_lines.append(line)
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            unfixable.append({"source": sample_source, "path": str(path), "line": line_number, "reason": "invalid_json"})
            next_lines.append(line)
            continue
        scanned += 1
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        redacted = redactor(str(event.get("event_type") or ""), payload)
        if _canonical(redacted) == _canonical(payload):
            next_lines.append(line)
            continue
        suspect += 1
        samples.append(_event_sample(sample_source, event, redacted, path=path, line=line_number))
        if fix:
            event["payload"] = redacted
            next_lines.append(json.dumps(event, ensure_ascii=False))
            pending_fixed += 1
            changed = True
        else:
            next_lines.append(line)
    if fix and changed:
        try:
            path.write_text("\n".join(next_lines) + ("\n" if next_lines else ""), encoding="utf-8")
        except OSError as exc:
            unfixable.append(
                {
                    "source": sample_source,
                    "path": str(path),
                    "reason": "write_failed",
                    "error_type": type(exc).__name__,
                }
            )
        else:
            fixed = pending_fixed
    return {
        "scanned": scanned,
        "suspect": suspect,
        "fixed": fixed,
        "samples": samples,
        "unfixable": unfixable,
    }


def _event_sample(source: str, event: dict, redacted: dict, *, path: Path | None = None, line: int | None = None) -> dict:
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    changed_keys = sorted({str(key) for key in set(payload) | set(redacted) if payload.get(key) != redacted.get(key)})
    sample: dict[str, Any] = {
        "source": source,
        "event_id": event.get("id"),
        "run_id": event.get("run_id"),
        "session_id": event.get("session_id"),
        "event_type": event.get("event_type"),
        "changed_keys": changed_keys,
    }
    if path is not None:
        sample["path"] = str(path)
    if line is not None:
        sample["line"] = line
    return sample


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
