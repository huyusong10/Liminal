from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loopora.event_redaction import redact_run_event_payload
from loopora.branding import state_dir_for_workdir
from loopora.run_artifacts import RunArtifactLayout
from loopora.settings import load_recent_workdirs


def audit_run_event_redaction(repository, *, fix: bool = False) -> dict:
    db_report = _audit_db_events(repository, fix=fix)
    timeline_report = _audit_timeline_files(repository, fix=fix)
    return {
        "mode": "fix" if fix else "dry-run",
        "db_events": db_report,
        "timeline_files": timeline_report,
        "fixed": int(db_report["fixed"]) + int(timeline_report["fixed"]),
        "suspect": int(db_report["suspect"]) + int(timeline_report["suspect"]),
        "unfixable": [*db_report["unfixable"], *timeline_report["unfixable"]],
    }


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
            file_report = _audit_timeline_file(path, fix=fix)
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

    def add(path: object) -> None:
        text = str(path or "").strip()
        if not text:
            return
        candidate = Path(text).expanduser()
        if candidate in seen:
            return
        seen.add(candidate)
        candidates.append(candidate)

    for event in repository.list_run_events_for_redaction_audit():
        add(event.get("runs_dir"))

    if hasattr(repository, "list_local_asset_roots"):
        for row in repository.list_local_asset_roots(resource_type="run", states={"active", "orphaned"}):
            add(row.get("path"))

    for workdir in load_recent_workdirs(limit=100):
        root = state_dir_for_workdir(workdir) / "runs"
        if not root.exists():
            continue
        for run_dir in sorted(item for item in root.iterdir() if item.is_dir()):
            add(run_dir)

    return candidates


def _audit_timeline_file(path: Path, *, fix: bool) -> dict:
    lines = path.read_text(encoding="utf-8").splitlines()
    next_lines: list[str] = []
    scanned = 0
    suspect = 0
    fixed = 0
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
            unfixable.append({"source": "timeline", "path": str(path), "line": line_number, "reason": "invalid_json"})
            next_lines.append(line)
            continue
        scanned += 1
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        redacted = redact_run_event_payload(str(event.get("event_type") or ""), payload)
        if _canonical(redacted) == _canonical(payload):
            next_lines.append(line)
            continue
        suspect += 1
        samples.append(_event_sample("timeline", event, redacted, path=path, line=line_number))
        if fix:
            event["payload"] = redacted
            next_lines.append(json.dumps(event, ensure_ascii=False))
            fixed += 1
            changed = True
        else:
            next_lines.append(line)
    if fix and changed:
        path.write_text("\n".join(next_lines) + ("\n" if next_lines else ""), encoding="utf-8")
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
