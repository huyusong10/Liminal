from __future__ import annotations

import json
import os
import re
from pathlib import Path

_ROLLOUT_SESSION_ID_PATTERN = re.compile(
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.jsonl$",
    re.IGNORECASE,
)


def normalize_session_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def extract_session_ref(payload: object) -> dict[str, str]:
    session_id = ""
    rollout_path = ""

    for key, child in _iter_payload_fields(payload):
        normalized_key = normalize_session_key(key)
        if normalized_key == "sessionid":
            session_id = _session_id_from_value(child) or session_id
        elif normalized_key == "rolloutpath" and isinstance(child, str) and child.strip():
            rollout_path = child.strip()
        if session_id and rollout_path:
            break

    if not session_id and rollout_path:
        session_id = _session_id_from_rollout_path(rollout_path)
    return _session_ref_payload(session_id=session_id, rollout_path=rollout_path)


def _iter_payload_fields(value: object):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key, child
            yield from _iter_payload_fields(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_payload_fields(child)


def _session_id_from_value(value: object) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, dict):
        uuid_value = value.get("uuid")
        if isinstance(uuid_value, str) and uuid_value.strip():
            return uuid_value.strip()
    return ""


def _session_id_from_rollout_path(rollout_path: str) -> str:
    match = _ROLLOUT_SESSION_ID_PATTERN.search(rollout_path)
    return match.group(1) if match else ""


def _session_ref_payload(*, session_id: str, rollout_path: str) -> dict[str, str]:
    ref: dict[str, str] = {}
    if session_id:
        ref["session_id"] = session_id
    if rollout_path:
        ref["rollout_path"] = rollout_path
    return ref


def merge_session_ref(current: object, ref: dict[str, str]) -> dict:
    merged = dict(current) if isinstance(current, dict) else {}
    merged.update(ref)
    return merged


def infer_codex_session_ref_from_rollouts(
    *,
    workdir: Path,
    current_ref: object,
    started_at: float = 0.0,
    codex_home: Path | None = None,
) -> dict[str, str]:
    if isinstance(current_ref, dict) and current_ref.get("session_id"):
        return {}

    sessions_dir = (codex_home or Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))) / "sessions"
    if not sessions_dir.exists():
        return {}

    resolved_workdir = workdir.expanduser().resolve().as_posix()
    for path in _recent_rollout_paths(sessions_dir):
        try:
            stat = path.stat()
            if started_at and stat.st_mtime + 1 < started_at:
                break
            payload = _read_first_json_line(path)
        except (OSError, json.JSONDecodeError):
            continue

        if not _payload_matches_workdir(payload, resolved_workdir):
            continue
        ref = extract_session_ref(payload) or extract_session_ref({"rollout_path": str(path)})
        if ref:
            return ref
    return {}


def _recent_rollout_paths(sessions_dir: Path) -> list[Path]:
    candidates: list[tuple[float, Path]] = []
    for path in sessions_dir.rglob("rollout-*.jsonl"):
        try:
            candidates.append((path.stat().st_mtime, path))
        except OSError:
            continue
    return [path for _, path in sorted(candidates, reverse=True)[:50]]


def _read_first_json_line(path: Path) -> object:
    with path.open(encoding="utf-8") as file:
        first_line = file.readline()
    if not first_line:
        raise json.JSONDecodeError("empty rollout file", "", 0)
    return json.loads(first_line)


def _payload_matches_workdir(payload: object, resolved_workdir: str) -> bool:
    cwd = ""
    if isinstance(payload, dict):
        session_meta = payload.get("session_meta")
        cwd = str(payload.get("cwd") or (session_meta.get("cwd") if isinstance(session_meta, dict) else "") or "").strip()
    if not cwd:
        return True
    return Path(cwd).expanduser().resolve().as_posix() == resolved_workdir
