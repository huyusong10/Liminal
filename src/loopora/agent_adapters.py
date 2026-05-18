from __future__ import annotations

import hashlib
import json
import os
import shlex
from pathlib import Path
from typing import Any

from loopora.branding import state_dir_for_workdir
from loopora.service_types import LooporaConflictError, LooporaError
from loopora.utils import utc_now

AGENT_ADAPTER_KINDS = ("codex", "claude", "opencode")
IMPLEMENTED_AGENT_ADAPTERS = {"codex", "claude", "opencode"}
ADAPTER_VERSION = 19
CODEX_ADAPTER_VERSION = ADAPTER_VERSION
CLAUDE_ADAPTER_VERSION = ADAPTER_VERSION
OPENCODE_ADAPTER_VERSION = ADAPTER_VERSION
CODEX_MANAGED_MARKER = "LOOPORA-MANAGED: codex-adapter"
CLAUDE_MANAGED_MARKER = "LOOPORA-MANAGED: claude-code-adapter"
OPENCODE_MANAGED_MARKER = "LOOPORA-MANAGED: opencode-adapter"
MANAGED_MARKERS = {
    "codex": CODEX_MANAGED_MARKER,
    "claude": CLAUDE_MANAGED_MARKER,
    "opencode": OPENCODE_MANAGED_MARKER,
}
MANAGED_MARKER = CODEX_MANAGED_MARKER
CODEX_MANIFEST_RELATIVE_PATH = ".loopora/adapters/codex/manifest.json"
CLAUDE_MANIFEST_RELATIVE_PATH = ".loopora/adapters/claude/manifest.json"
OPENCODE_MANIFEST_RELATIVE_PATH = ".loopora/adapters/opencode/manifest.json"
MANIFEST_RELATIVE_PATHS = {
    "codex": CODEX_MANIFEST_RELATIVE_PATH,
    "claude": CLAUDE_MANIFEST_RELATIVE_PATH,
    "opencode": OPENCODE_MANIFEST_RELATIVE_PATH,
}
MANIFEST_RELATIVE_PATH = CODEX_MANIFEST_RELATIVE_PATH
OBSOLETE_MANAGED_PATHS = {
    "claude": (
        ".claude/commands/loopora-gen.md",
        ".claude/commands/loopora-loop.md",
    ),
}
CLAUDE_SETTINGS_RELATIVE_PATH = ".claude/settings.json"
CLAUDE_SESSION_HOOK_RELATIVE_PATH = ".claude/hooks/loopora-session-context.py"
CLAUDE_SESSION_HOOK_SETTINGS_REF = ".claude/settings.json#hooks.SessionStart.loopora"
CLAUDE_SESSION_HOOK_COMMAND = 'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/loopora-session-context.py"'
CLAUDE_SESSION_HOOK_GROUP = {
    "matcher": "startup|resume|clear|compact",
    "hooks": [
        {
            "type": "command",
            "command": CLAUDE_SESSION_HOOK_COMMAND,
            "timeout": 5,
        }
    ],
}


def normalize_agent_adapter_kind(value: str | None) -> str:
    normalized = str(value or "").strip().lower().replace("_", "-")
    aliases = {
        "codex": "codex",
        "openai-codex": "codex",
        "claude": "claude",
        "claude-code": "claude",
        "claudecode": "claude",
        "opencode": "opencode",
        "open-code": "opencode",
    }
    if normalized in aliases:
        return aliases[normalized]
    supported = ", ".join(AGENT_ADAPTER_KINDS)
    raise LooporaError(f"unsupported agent adapter: {value!r}. Expected one of: {supported}")


def resolve_adapter_project_root(workdir: Path | str | None) -> Path:
    root = Path(workdir or ".").expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise LooporaError(f"adapter project root does not exist: {root}")
    return root


def list_agent_adapter_statuses(workdir: Path | str | None) -> list[dict[str, Any]]:
    root = resolve_adapter_project_root(workdir)
    return [agent_adapter_status(kind, root) for kind in AGENT_ADAPTER_KINDS]


def agent_adapter_status(adapter: str, workdir: Path | str | None) -> dict[str, Any]:
    kind = normalize_agent_adapter_kind(adapter)
    root = resolve_adapter_project_root(workdir)
    if kind not in IMPLEMENTED_AGENT_ADAPTERS:
        return _not_implemented_status(kind, root)
    return _managed_adapter_status(kind, root)


def install_agent_adapter(adapter: str, workdir: Path | str | None) -> dict[str, Any]:
    kind = normalize_agent_adapter_kind(adapter)
    root = resolve_adapter_project_root(workdir)
    if kind not in IMPLEMENTED_AGENT_ADAPTERS:
        raise LooporaError(f"{_adapter_label(kind)} adapter is not implemented yet")
    templates = _managed_templates(kind)
    marker = _managed_marker(kind)
    _assert_targets_are_replaceable(kind, root, templates)
    removed_obsolete_files = _remove_obsolete_managed_files(kind, root, templates)
    _assert_host_config_is_replaceable(kind, root)
    written: list[dict[str, str]] = []
    for relative_path, content in templates.items():
        target = root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        current = _read_text_or_empty(target)
        if current != content:
            target.write_text(content, encoding="utf-8")
        written.append(
            {
                "path": relative_path,
                "sha256": _sha256_text(content),
            }
        )
    _install_host_config(kind, root)
    manifest = _manifest_payload(kind, root, written)
    manifest_path = root / _manifest_relative_path(kind)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    existing_manifest, _ = _read_manifest(kind, root)
    if existing_manifest != manifest:
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    status = _managed_adapter_status(kind, root)
    return {
        "adapter": kind,
        "label": _adapter_label(kind),
        "workdir": str(root),
        "status": status["status"],
        "manifest_path": str(manifest_path),
        "managed_files": status["managed_files"],
        "managed_marker": marker,
        "removed_obsolete_files": removed_obsolete_files,
    }


def uninstall_agent_adapter(adapter: str, workdir: Path | str | None) -> dict[str, Any]:
    kind = normalize_agent_adapter_kind(adapter)
    root = resolve_adapter_project_root(workdir)
    if kind not in IMPLEMENTED_AGENT_ADAPTERS:
        raise LooporaError(f"{_adapter_label(kind)} adapter is not implemented yet")

    templates = _managed_templates(kind)
    marker = _managed_marker(kind)
    manifest_payload, manifest_error = _read_manifest(kind, root)
    manifest_paths = _manifest_paths(manifest_payload) if isinstance(manifest_payload, dict) else []
    managed_paths = sorted(set(manifest_paths) | set(templates))

    removed: list[str] = []
    kept: list[dict[str, str]] = []
    for relative_path in managed_paths:
        target = root / relative_path
        if not target.exists():
            continue
        try:
            content = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            kept.append({"path": relative_path, "reason": "unreadable"})
            continue
        manifest_hash = _manifest_hash_for_path(manifest_payload, relative_path) if isinstance(manifest_payload, dict) else ""
        template_hash = _sha256_text(templates.get(relative_path, ""))
        content_hash = _sha256_text(content)
        if marker in content or content_hash in {manifest_hash, template_hash}:
            target.unlink()
            removed.append(relative_path)
            _remove_empty_parents(root, target.parent)
        else:
            kept.append({"path": relative_path, "reason": "not_loopora_managed"})

    removed.extend(_uninstall_host_config(kind, root))

    manifest_path = root / _manifest_relative_path(kind)
    if manifest_path.exists():
        try:
            manifest_path.unlink()
            _remove_empty_parents(root, manifest_path.parent)
        except OSError as exc:
            kept.append({"path": _manifest_relative_path(kind), "reason": f"remove_failed: {exc}"})

    return {
        "adapter": kind,
        "label": _adapter_label(kind),
        "workdir": str(root),
        "status": _managed_adapter_status(kind, root)["status"],
        "removed_files": removed,
        "kept_files": kept,
        "manifest_error": manifest_error,
    }


def agent_context_binding_path(
    adapter: str,
    workdir: Path | str,
    *,
    context_id: str = "",
) -> Path:
    kind = normalize_agent_adapter_kind(adapter)
    root = resolve_adapter_project_root(workdir)
    key = agent_context_key(kind, root, context_id=context_id)
    return state_dir_for_workdir(root) / "agent_adapters" / kind / "bindings" / f"{key}.json"


def agent_context_key(adapter: str, workdir: Path | str, *, context_id: str = "") -> str:
    kind = normalize_agent_adapter_kind(adapter)
    root = resolve_adapter_project_root(workdir)
    context_identity = resolved_agent_context_id(kind, context_id=context_id)
    source = context_identity or f"workdir:{root}"
    return hashlib.sha256(f"{kind}:{source}".encode()).hexdigest()[:20]


def resolved_agent_context_id(adapter: str, *, context_id: str = "") -> str:
    kind = normalize_agent_adapter_kind(adapter)
    return (
        str(context_id or "").strip()
        or os.environ.get("LOOPORA_AGENT_SESSION_ID", "").strip()
        or _adapter_session_env(kind)
    )


def agent_context_source(adapter: str, *, context_id: str = "") -> str:
    kind = normalize_agent_adapter_kind(adapter)
    if str(context_id or "").strip():
        return "explicit"
    if os.environ.get("LOOPORA_AGENT_SESSION_ID", "").strip():
        return "loopora_env"
    if kind == "codex" and _adapter_session_env(kind):
        return "codex_env"
    if kind == "claude" and _adapter_session_env(kind):
        return "claude_env"
    if kind == "opencode" and _adapter_session_env(kind):
        return "opencode_env"
    return "workdir"


def write_agent_binding(
    adapter: str,
    workdir: Path | str,
    payload: dict[str, Any],
    *,
    context_id: str = "",
) -> dict[str, Any]:
    path = agent_context_binding_path(adapter, workdir, context_id=context_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "adapter": normalize_agent_adapter_kind(adapter),
        "workdir": str(resolve_adapter_project_root(workdir)),
        "context_key": path.stem,
        "context_source": agent_context_source(adapter, context_id=context_id),
        "host_context_id": resolved_agent_context_id(adapter, context_id=context_id),
        "updated_at": utc_now(),
        **payload,
    }
    path.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {**body, "path": str(path)}


def read_agent_binding(adapter: str, workdir: Path | str, *, context_id: str = "") -> dict[str, Any]:
    path = agent_context_binding_path(adapter, workdir, context_id=context_id)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LooporaError(f"agent binding is unreadable: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise LooporaError(f"agent binding is invalid: {path}")
    payload["path"] = str(path)
    return payload


def agent_loop_command(adapter: str, workdir: Path | str, *, entry_source: str = "", context_id: str = "") -> str:
    normalized_adapter = normalize_agent_adapter_kind(adapter)
    command_bits = [
        "loopora",
        "agent",
        normalized_adapter,
        "loop",
        "--workdir",
        shlex.quote(str(workdir)),
    ]
    normalized_context_id = str(context_id or "").strip()
    if normalized_context_id:
        command_bits.extend(["--context-id", shlex.quote(normalized_context_id)])
    normalized_entry_source = str(entry_source or "").strip()
    if normalized_entry_source:
        command_bits.extend(["--entry-source", shlex.quote(normalized_entry_source)])
    command = " ".join(command_bits)
    if normalized_entry_source:
        command = f"LOOPORA_AGENT_ENTRY_SOURCE={shlex.quote(normalized_entry_source)} {command}"
    return command


def _not_implemented_status(kind: str, root: Path) -> dict[str, Any]:
    return {
        "adapter": kind,
        "label": _adapter_label(kind),
        "workdir": str(root),
        "implemented": False,
        "status": "not_implemented",
        "summary": "Coming soon",
        "managed_files": [],
        "manifest_path": "",
        "error": "",
    }


def _managed_adapter_status(kind: str, root: Path) -> dict[str, Any]:
    templates = _managed_templates(kind)
    manifest_payload, manifest_error = _read_manifest(kind, root)
    manifest_path = root / _manifest_relative_path(kind)
    managed_files = []
    if manifest_error:
        return {
            "adapter": kind,
            "label": _adapter_label(kind),
            "workdir": str(root),
            "implemented": True,
            "status": "error",
            "summary": f"Cannot read Loopora {_adapter_label(kind)} adapter manifest",
            "managed_files": [],
            "manifest_path": str(manifest_path),
            "error": manifest_error,
        }

    manifest_exists = isinstance(manifest_payload, dict)
    unmanaged_conflicts = []
    needs_update = False
    installed_count = 0
    paths = _managed_status_paths(kind, root, manifest_payload, manifest_exists=manifest_exists, templates=templates)
    managed_marker_found = False
    for relative_path in paths:
        expected = templates.get(relative_path, "")
        file_state = _managed_file_status(kind, root, relative_path, expected, manifest_context=(manifest_payload, manifest_exists))
        file_payload = file_state["payload"]
        installed_count += int(file_state["current"])
        needs_update = needs_update or bool(file_state["needs_update"])
        managed_marker_found = managed_marker_found or bool(file_state["managed_marker"])
        if file_state["unmanaged_conflict"]:
            unmanaged_conflicts.append(relative_path)
        managed_files.append(file_payload)

    host_config_state = _host_config_status(kind, root, manifest_exists=manifest_exists)
    if host_config_state:
        managed_files.append(host_config_state["payload"])
        needs_update = needs_update or bool(host_config_state["needs_update"])
        if host_config_state["unmanaged_conflict"]:
            unmanaged_conflicts.append(host_config_state["payload"]["path"])

    if unmanaged_conflicts:
        status = "error"
        summary = f"{_adapter_label(kind)} adapter files exist but ownership is unclear"
        error = "unmanaged files: " + ", ".join(unmanaged_conflicts)
    elif manifest_exists and needs_update:
        status = "needs_update"
        summary = f"{_adapter_label(kind)} adapter is installed but needs update"
        error = ""
    elif manifest_exists and installed_count == len(templates):
        status = "installed"
        summary = f"{_adapter_label(kind)} adapter is installed"
        error = ""
    elif not manifest_exists and (installed_count == len(templates) or managed_marker_found):
        status = "needs_update"
        summary = f"{_adapter_label(kind)} adapter files exist but manifest is missing"
        error = ""
    else:
        status = "not_installed"
        summary = f"{_adapter_label(kind)} adapter is not installed"
        error = ""
    return {
        "adapter": kind,
        "label": _adapter_label(kind),
        "workdir": str(root),
        "implemented": True,
        "status": status,
        "summary": summary,
        "managed_files": managed_files,
        "manifest_path": str(manifest_path),
        "error": error,
    }


def _managed_file_status(
    kind: str,
    root: Path,
    relative_path: str,
    expected: str,
    *,
    manifest_context: tuple[dict[str, Any] | None, bool],
) -> dict[str, Any]:
    manifest_payload, manifest_exists = manifest_context
    target = root / relative_path
    expected_hash = _sha256_text(expected) if expected else ""
    payload: dict[str, Any] = {
        "path": relative_path,
        "exists": target.exists(),
        "expected_sha256": expected_hash,
        "actual_sha256": "",
        "state": "missing",
    }
    if not target.exists():
        return {
            "payload": payload,
            "current": False,
            "needs_update": manifest_exists,
            "managed_marker": False,
            "unmanaged_conflict": False,
        }

    try:
        content = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        payload["state"] = "error"
        payload["error"] = str(exc)
        return {
            "payload": payload,
            "current": False,
            "needs_update": False,
            "managed_marker": False,
            "unmanaged_conflict": True,
        }

    actual_hash = _sha256_text(content)
    payload["actual_sha256"] = actual_hash
    if expected and actual_hash == expected_hash:
        payload["state"] = "current"
        return {
            "payload": payload,
            "current": True,
            "needs_update": False,
            "managed_marker": _managed_marker(kind) in content,
            "unmanaged_conflict": False,
        }
    manifest_hash = _manifest_hash_for_path(manifest_payload, relative_path) if manifest_exists else ""
    if _managed_marker(kind) in content or (manifest_hash and actual_hash == manifest_hash):
        payload["state"] = "needs_update"
        return {
            "payload": payload,
            "current": False,
            "needs_update": True,
            "managed_marker": _managed_marker(kind) in content,
            "unmanaged_conflict": False,
        }
    payload["state"] = "unmanaged_conflict"
    return {
        "payload": payload,
        "current": False,
        "needs_update": False,
        "managed_marker": False,
        "unmanaged_conflict": True,
    }


def _manifest_payload(kind: str, root: Path, managed_files: list[dict[str, str]]) -> dict[str, Any]:
    existing_manifest, _ = _read_manifest(kind, root)
    installed_at = ""
    if isinstance(existing_manifest, dict):
        installed_at = str(existing_manifest.get("installed_at") or "").strip()
    return {
        "adapter": kind,
        "version": ADAPTER_VERSION,
        "installed_at": installed_at or utc_now(),
        "managed_files": managed_files,
    }


def _managed_status_paths(
    kind: str,
    root: Path,
    manifest_payload: dict[str, Any] | None,
    *,
    manifest_exists: bool,
    templates: dict[str, str],
) -> list[str]:
    paths = set(templates)
    if manifest_exists:
        paths.update(_manifest_paths(manifest_payload))
    for relative_path in _obsolete_managed_paths(kind):
        if relative_path in paths or (root / relative_path).exists():
            paths.add(relative_path)
    return sorted(paths)


def _obsolete_managed_paths(kind: str) -> set[str]:
    return set(OBSOLETE_MANAGED_PATHS.get(kind, ()))


def _remove_obsolete_managed_files(kind: str, root: Path, templates: dict[str, str]) -> list[str]:
    manifest_payload, _ = _read_manifest(kind, root)
    manifest_paths = set(_manifest_paths(manifest_payload)) if isinstance(manifest_payload, dict) else set()
    obsolete_paths = sorted((manifest_paths | _obsolete_managed_paths(kind)) - set(templates))
    removed: list[str] = []
    conflicts: list[str] = []
    marker = _managed_marker(kind)
    for relative_path in obsolete_paths:
        target = root / relative_path
        if not target.exists():
            continue
        try:
            content = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            conflicts.append(f"{relative_path} ({exc})")
            continue
        content_hash = _sha256_text(content)
        manifest_hash = _manifest_hash_for_path(manifest_payload, relative_path) if isinstance(manifest_payload, dict) else ""
        if marker in content or (manifest_hash and content_hash == manifest_hash):
            target.unlink()
            removed.append(relative_path)
            _remove_empty_parents(root, target.parent)
            continue
        conflicts.append(relative_path)
    if conflicts:
        raise LooporaConflictError(
            f"refusing to remove or ignore non-Loopora obsolete {_adapter_label(kind)} adapter files: "
            + ", ".join(conflicts)
        )
    return removed


def _assert_targets_are_replaceable(kind: str, root: Path, templates: dict[str, str]) -> None:
    conflicts = []
    manifest_payload, _ = _read_manifest(kind, root)
    marker = _managed_marker(kind)
    for relative_path, content in templates.items():
        target = root / relative_path
        if not target.exists():
            continue
        try:
            existing = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            conflicts.append(f"{relative_path} ({exc})")
            continue
        manifest_hash = _manifest_hash_for_path(manifest_payload, relative_path) if isinstance(manifest_payload, dict) else ""
        existing_hash = _sha256_text(existing)
        if existing == content or marker in existing or (manifest_hash and existing_hash == manifest_hash):
            continue
        conflicts.append(relative_path)
    if conflicts:
        raise LooporaConflictError(
            f"refusing to overwrite non-Loopora {_adapter_label(kind)} adapter files: " + ", ".join(conflicts)
        )


def _assert_host_config_is_replaceable(kind: str, root: Path) -> None:
    if kind != "claude":
        return
    settings_path = root / CLAUDE_SETTINGS_RELATIVE_PATH
    if not settings_path.exists():
        return
    _assert_claude_settings_can_merge_loopora_hook(_read_json_object(settings_path, label="Claude Code settings"))


def _install_host_config(kind: str, root: Path) -> None:
    if kind == "claude":
        _install_claude_session_hook(root)


def _uninstall_host_config(kind: str, root: Path) -> list[str]:
    if kind != "claude":
        return []
    return _uninstall_claude_session_hook(root)


def _host_config_status(kind: str, root: Path, *, manifest_exists: bool) -> dict[str, Any] | None:
    if kind != "claude":
        return None
    payload: dict[str, Any] = {
        "path": CLAUDE_SESSION_HOOK_SETTINGS_REF,
        "exists": (root / CLAUDE_SETTINGS_RELATIVE_PATH).exists(),
        "expected_sha256": "",
        "actual_sha256": "",
        "state": "missing",
    }
    try:
        settings = _read_claude_settings(root)
    except LooporaError as exc:
        payload["state"] = "error"
        payload["error"] = str(exc)
        return {
            "payload": payload,
            "needs_update": False,
            "unmanaged_conflict": manifest_exists,
        }
    try:
        _assert_claude_settings_can_merge_loopora_hook(settings)
    except LooporaError as exc:
        payload["state"] = "error"
        payload["error"] = str(exc)
        return {
            "payload": payload,
            "needs_update": False,
            "unmanaged_conflict": manifest_exists,
        }
    if _claude_settings_has_loopora_session_hook(settings):
        payload["state"] = "current"
        return {
            "payload": payload,
            "needs_update": False,
            "unmanaged_conflict": False,
        }
    return {
        "payload": payload,
        "needs_update": manifest_exists,
        "unmanaged_conflict": False,
    }


def _install_claude_session_hook(root: Path) -> None:
    settings = _read_claude_settings(root)
    updated = _remove_claude_session_hook(settings)
    hooks = updated.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise LooporaConflictError("refusing to update Claude Code settings because hooks is not an object")
    session_start = hooks.setdefault("SessionStart", [])
    if not isinstance(session_start, list):
        raise LooporaConflictError("refusing to update Claude Code settings because hooks.SessionStart is not a list")
    session_start.append(json.loads(json.dumps(CLAUDE_SESSION_HOOK_GROUP)))
    _write_claude_settings(root, updated)


def _uninstall_claude_session_hook(root: Path) -> list[str]:
    settings_path = root / CLAUDE_SETTINGS_RELATIVE_PATH
    if not settings_path.exists():
        return []
    settings = _read_claude_settings(root)
    updated = _remove_claude_session_hook(settings)
    if updated == settings:
        return []
    if updated:
        _write_claude_settings(root, updated)
    else:
        settings_path.unlink()
        _remove_empty_parents(root, settings_path.parent)
    return [CLAUDE_SESSION_HOOK_SETTINGS_REF]


def _read_claude_settings(root: Path) -> dict[str, Any]:
    settings_path = root / CLAUDE_SETTINGS_RELATIVE_PATH
    if not settings_path.exists():
        return {}
    return _read_json_object(settings_path, label="Claude Code settings")


def _read_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LooporaError(f"{label} is unreadable: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise LooporaConflictError(f"{label} must be a JSON object: {path}")
    return payload


def _assert_claude_settings_can_merge_loopora_hook(settings: dict[str, Any]) -> None:
    hooks = settings.get("hooks")
    if hooks is not None and not isinstance(hooks, dict):
        raise LooporaConflictError("refusing to update Claude Code settings because hooks is not an object")
    if isinstance(hooks, dict):
        session_start = hooks.get("SessionStart")
        if session_start is not None and not isinstance(session_start, list):
            raise LooporaConflictError("refusing to update Claude Code settings because hooks.SessionStart is not a list")


def _write_claude_settings(root: Path, payload: dict[str, Any]) -> None:
    settings_path = root / CLAUDE_SETTINGS_RELATIVE_PATH
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _remove_claude_session_hook(settings: dict[str, Any]) -> dict[str, Any]:
    updated = json.loads(json.dumps(settings))
    hooks = updated.get("hooks")
    if not isinstance(hooks, dict):
        return updated
    session_start = hooks.get("SessionStart")
    if not isinstance(session_start, list):
        return updated

    cleaned_groups: list[Any] = []
    for group in session_start:
        if not isinstance(group, dict):
            cleaned_groups.append(group)
            continue
        handlers = group.get("hooks")
        if not isinstance(handlers, list):
            cleaned_groups.append(group)
            continue
        cleaned_handlers = [
            handler
            for handler in handlers
            if not (isinstance(handler, dict) and str(handler.get("command") or "").strip() == CLAUDE_SESSION_HOOK_COMMAND)
        ]
        if cleaned_handlers:
            cleaned_group = dict(group)
            cleaned_group["hooks"] = cleaned_handlers
            cleaned_groups.append(cleaned_group)

    if cleaned_groups:
        hooks["SessionStart"] = cleaned_groups
    else:
        hooks.pop("SessionStart", None)
    if not hooks:
        updated.pop("hooks", None)
    return updated


def _claude_settings_has_loopora_session_hook(settings: dict[str, Any]) -> bool:
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return False
    session_start = hooks.get("SessionStart")
    if not isinstance(session_start, list):
        return False
    for group in session_start:
        if not isinstance(group, dict):
            continue
        handlers = group.get("hooks")
        if not isinstance(handlers, list):
            continue
        for handler in handlers:
            if isinstance(handler, dict) and str(handler.get("command") or "").strip() == CLAUDE_SESSION_HOOK_COMMAND:
                return True
    return False


def _read_manifest(kind: str, root: Path) -> tuple[dict[str, Any] | None, str]:
    path = root / _manifest_relative_path(kind)
    if not path.exists():
        return None, ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, str(exc)
    if not isinstance(payload, dict) or payload.get("adapter") != kind:
        return None, f"manifest is not a {_adapter_label(kind)} adapter manifest"
    return payload, ""


def _manifest_paths(manifest_payload: dict[str, Any] | None) -> list[str]:
    files = manifest_payload.get("managed_files") if isinstance(manifest_payload, dict) else []
    if not isinstance(files, list):
        return []
    paths = [str(item.get("path") or "").strip() for item in files if isinstance(item, dict)]
    return sorted(path for path in paths if path)


def _manifest_hash_for_path(manifest_payload: dict[str, Any] | None, relative_path: str) -> str:
    files = manifest_payload.get("managed_files") if isinstance(manifest_payload, dict) else []
    if not isinstance(files, list):
        return ""
    for item in files:
        if isinstance(item, dict) and item.get("path") == relative_path:
            return str(item.get("sha256") or "").strip()
    return ""


def _read_text_or_empty(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _sha256_text(value: str) -> str:
    if not value:
        return ""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _remove_empty_parents(root: Path, directory: Path) -> None:
    stop_dirs = {root, root / ".agents", root / ".codex", root / ".claude", root / ".opencode", root / ".loopora"}
    current = directory
    while current != current.parent and current not in stop_dirs:
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


def _adapter_label(kind: str) -> str:
    return {
        "codex": "Codex",
        "claude": "Claude Code",
        "opencode": "OpenCode",
    }.get(kind, kind)


def _adapter_session_env(kind: str) -> str:
    if kind == "codex":
        return os.environ.get("CODEX_SESSION_ID", "").strip() or os.environ.get("CODEX_THREAD_ID", "").strip()
    if kind == "claude":
        return os.environ.get("CLAUDE_SESSION_ID", "").strip()
    if kind == "opencode":
        return os.environ.get("OPENCODE_SESSION_ID", "").strip()
    return ""


def _managed_marker(kind: str) -> str:
    return MANAGED_MARKERS[kind]


def _manifest_relative_path(kind: str) -> str:
    return MANIFEST_RELATIVE_PATHS[kind]


def _managed_templates(kind: str) -> dict[str, str]:
    if kind == "codex":
        return _codex_managed_templates()
    if kind == "claude":
        return _claude_managed_templates()
    if kind == "opencode":
        return _opencode_managed_templates()
    raise LooporaError(f"{_adapter_label(kind)} adapter is not implemented yet")


def _codex_managed_templates() -> dict[str, str]:
    return {
        ".agents/skills/loopora-gen/SKILL.md": _codex_loopora_gen_skill(),
        ".agents/skills/loopora-loop/SKILL.md": _codex_loopora_loop_skill(),
        ".codex/agents/loopora-builder.toml": _codex_role_agent("builder"),
        ".codex/agents/loopora-inspector.toml": _codex_role_agent("inspector"),
        ".codex/agents/loopora-gatekeeper.toml": _codex_role_agent("gatekeeper"),
        ".codex/agents/loopora-guide.toml": _codex_role_agent("guide"),
        ".codex/agents/loopora-orchestrator.toml": _codex_role_agent("orchestrator"),
    }


def _claude_managed_templates() -> dict[str, str]:
    return {
        ".claude/skills/loopora-gen/SKILL.md": _claude_loopora_gen_skill(),
        ".claude/skills/loopora-loop/SKILL.md": _claude_loopora_loop_skill(),
        CLAUDE_SESSION_HOOK_RELATIVE_PATH: _claude_session_hook_script(),
        ".claude/agents/loopora-builder.md": _claude_role_agent("builder"),
        ".claude/agents/loopora-inspector.md": _claude_role_agent("inspector"),
        ".claude/agents/loopora-gatekeeper.md": _claude_role_agent("gatekeeper"),
        ".claude/agents/loopora-guide.md": _claude_role_agent("guide"),
        ".claude/agents/loopora-orchestrator.md": _claude_role_agent("orchestrator"),
    }


def _opencode_managed_templates() -> dict[str, str]:
    return {
        ".opencode/commands/loopora-gen.md": _opencode_loopora_gen_command(),
        ".opencode/commands/loopora-loop.md": _opencode_loopora_loop_command(),
        ".opencode/agents/loopora-builder.md": _opencode_role_agent("builder"),
        ".opencode/agents/loopora-inspector.md": _opencode_role_agent("inspector"),
        ".opencode/agents/loopora-gatekeeper.md": _opencode_role_agent("gatekeeper"),
        ".opencode/agents/loopora-guide.md": _opencode_role_agent("guide"),
        ".opencode/agents/loopora-orchestrator.md": _opencode_role_agent("orchestrator"),
    }


def _role_agent_description(role: str) -> str:
    return {
        "builder": "Execute Loopora Builder step capsules, make allowed workspace changes, and return structured proof-oriented output.",
        "inspector": "Execute Loopora Inspector step capsules, gather evidence, and return structured inspection output.",
        "gatekeeper": "Execute Loopora GateKeeper step capsules, judge only from routed evidence, and return the final structured verdict.",
        "guide": "Execute Loopora Guide step capsules, convert blockers or weak evidence into a minimal repair direction, and return structured guidance.",
        "orchestrator": "Dispatch Loopora step capsules to the required native role agent and preserve verifiable host dispatch metadata.",
    }.get(role, "Execute a Loopora step capsule and return structured output.")


def _role_agent_body(role: str) -> str:
    if role == "orchestrator":
        return """You are the Loopora Orchestrator agent.

You do not perform Builder, Inspector, GateKeeper, or Guide work yourself. For each Loopora next_step capsule, read next_step.role_dispatch.target_agent and invoke that exact host-native role agent or task agent. If the host cannot invoke the named agent, stop and report the missing native dispatch capability instead of submitting inline work.

Pass the full `next_step.prompt`, `next_step.judgment_contract`, `next_step.required_coverage`, `next_step.output_schema`, `next_step.action_policy`, `next_step.known_evidence_ids`, and the capsule context refs (`context_path` and `context_absolute_path`) to the target role agent. Do not summarize, trim, or rewrite that prompt or judgment projection; they contain the frozen run contract, current step context, evidence rules, and output instructions the role must execute.

Before submission, open the result template from `next_step.submit_hint.result_template_absolute_path` or `next_step.submit_hint.result_template_path`. Use its `loopora_result_contract` block as the local checklist for step id, action policy, required coverage, known evidence ids, evidence ref rules, and output schema. Keep the template's `loopora_host_dispatch`, fill only the schema-shaped `result` scaffold with the role agent's structured output, replace every `null` placeholder before submit, and save a filled copy in the outbox. Empty arrays are acceptable when the schema permits and there is no item to report; remove optional placeholder fields you do not submit. The `loopora_result_contract` helper is ignored by Loopora submit, so it may stay in the filled wrapper; do not move helper fields into `result`.

When the role agent returns, preserve its structured result and dispatch metadata. Submit the filled template wrapper; the `result` object must match next_step.output_schema exactly, while `loopora_host_dispatch.actual_agent` and `.target_agent` must both equal next_step.role_dispatch.target_agent.

After submit, treat `complete` as the run lifecycle only. If the response includes `task_next_action.kind=continue_evidence`, the task is still unproven: report the verdict, evidence focus, and `/loopora-loop` continuation command instead of claiming the task is complete.
"""
    label = role.capitalize() if role != "gatekeeper" else "GateKeeper"
    return f"""You are the Loopora {label} role agent.

Use only the step capsule provided by Loopora as the stable contract for this invocation. Respect the capsule's action_policy, judgment_contract, run contract, output schema, evidence refs, and context paths.

Return exactly one wrapper JSON object with `loopora_host_dispatch` and `result`. The `result` object must match the capsule's output_schema exactly. Do not change the frozen Loopora run contract. If the task contract is wrong or evidence is missing, report that as blocker, weak evidence, or residual risk in the structured output instead of silently relaxing the bar.

If the host provides a result template, treat its `loopora_result_contract` block as the fill guide: use only its known evidence ids, coverage target ids, action policy, and output schema, fill only the schema-shaped `result` scaffold, replace every `null` placeholder before submit, and keep helper fields out of `result`.

The `loopora_host_dispatch` object is your native-dispatch proof. Set `schema_version` to 1, `adapter` to the capsule adapter, `run_id` and `step_id` to the capsule values, `target_agent` and `actual_agent` to the exact agent name that invoked you, `dispatch_mode` to `host_subagent`, `host_task`, or `host_agent`, `inline` to false, and `attestation` to a short statement that the host invoked this named role agent rather than doing the role work inline.

Follow any evidence_rules in the capsule as hard constraints. In particular, every evidence_refs value, including coverage_results evidence_refs, must be an exact string copied from known_evidence_ids. Do not invent, suffix, split, or derive new evidence IDs. Use coverage status words such as `covered`, `weak`, `blocked`, or `missing` in coverage_results.status; keep Proven/Weak/Unproven/Blocking/Residual risk as verdict or note buckets. A GateKeeper pass must cite supporting upstream evidence already known to Loopora, and Loopora Core derives its own finish coverage after submission. For GateKeeper, use the schema's `passed` boolean and `decision_summary`; do not return a `verdict` / `task_verdict` wrapper. Put artifact labels, filenames, and finer-grained observations in evidence_claims or notes, not in evidence_refs.

Do not launch codex, claude, or opencode from inside this role. The host Agent is already the execution subject; Loopora only needs the wrapper JSON submitted back through loopora agent <adapter> submit.
"""


def _codex_role_agent(role: str) -> str:
    return f"""# {MANAGED_MARKER} version={CODEX_ADAPTER_VERSION} role={role}

name = "loopora-{role}"
description = "{_role_agent_description(role)}"
developer_instructions = \"\"\"
{_role_agent_body(role).rstrip()}
\"\"\"
"""


def _claude_role_frontmatter(role: str) -> str:
    if role == "orchestrator":
        return """tools: Task, Read, Write, Bash
maxTurns: 20"""
    if role == "builder":
        return """tools: Read, Glob, Grep, Bash, Write, Edit, MultiEdit
maxTurns: 20"""
    return """tools: Read, Glob, Grep, Bash
maxTurns: 12"""


def _claude_role_agent(role: str) -> str:
    return f"""---
name: loopora-{role}
description: "{_role_agent_description(role)}"
{_claude_role_frontmatter(role)}
---

<!-- {CLAUDE_MANAGED_MARKER} version={CLAUDE_ADAPTER_VERSION} role={role} -->

# Loopora {role.capitalize() if role != "gatekeeper" else "GateKeeper"}

{_role_agent_body(role)}
"""


def _opencode_role_frontmatter(role: str) -> str:
    if role == "orchestrator":
        return """mode: subagent
permission:
  task:
    "*": deny
    loopora-builder: allow
    loopora-inspector: allow
    loopora-gatekeeper: allow
    loopora-guide: allow"""
    return """mode: subagent
permission:
  task: deny"""


def _opencode_role_agent(role: str) -> str:
    return f"""---
description: "{_role_agent_description(role)}"
{_opencode_role_frontmatter(role)}
---

<!-- {OPENCODE_MANAGED_MARKER} version={OPENCODE_ADAPTER_VERSION} role={role} -->

# Loopora {role.capitalize() if role != "gatekeeper" else "GateKeeper"}

{_role_agent_body(role)}
"""


def _claude_session_hook_script() -> str:
    return f"""#!/usr/bin/env python3
# {CLAUDE_MANAGED_MARKER} version={CLAUDE_ADAPTER_VERSION} file=loopora-session-context
from __future__ import annotations

import json
import os
import shlex
import sys


def _main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{{}}")
    except json.JSONDecodeError:
        payload = {{}}
    if not isinstance(payload, dict):
        payload = {{}}

    session_id = str(payload.get("session_id") or "").strip()
    transcript_path = str(payload.get("transcript_path") or "").strip()
    context_id = session_id or transcript_path
    env_file = os.environ.get("CLAUDE_ENV_FILE", "").strip()
    if env_file and context_id:
        with open(env_file, "a", encoding="utf-8") as handle:
            handle.write(f"export CLAUDE_SESSION_ID={{shlex.quote(context_id)}}\\n")
            handle.write(f"export LOOPORA_AGENT_SESSION_ID={{shlex.quote(context_id)}}\\n")
        if transcript_path:
            with open(env_file, "a", encoding="utf-8") as handle:
                handle.write(f"export LOOPORA_CLAUDE_TRANSCRIPT_PATH={{shlex.quote(transcript_path)}}\\n")

    output = {{
        "hookSpecificOutput": {{
            "hookEventName": "SessionStart",
            "additionalContext": "Loopora session identity is registered for Loopora-managed commands.",
        }}
    }}
    print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
"""


def _agent_native_dispatch_guidance(adapter: str) -> str:
    if adapter != "codex":
        return ""
    return """
Codex native dispatch guidance:
- When using Codex `spawn_agent`, set `agent_type` to the exact `role_dispatch.target_agent` and omit `fork_context`; do not combine a custom agent type with a full-history fork.
- Pass only the current step capsule essentials, `next_step.judgment_contract`, `next_step.required_coverage`, `next_step.output_schema`, `next_step.action_policy`, `next_step.known_evidence_ids`, and relevant artifact paths to the role agent. Do not pass the full conversation or unrelated run history.
- Ask the role agent to return the required structured result directly. Prefer empty proof arrays over creating extra proof files unless the capsule requires an artifact.
- Wait for the role agent with a bounded timeout that is shorter than the surrounding command timeout. If native dispatch cannot complete, report that as unavailable instead of waiting indefinitely or submitting inline work.
"""


def _agent_native_loop_body(*, adapter: str, marker_source: str, context_arg: str = "") -> str:
    context_bits = f" {context_arg}" if context_arg else ""
    dispatch_guidance = _agent_native_dispatch_guidance(adapter)
    return f"""Start or reuse the Loopora-managed run for the reviewed Loop preview associated with this session or workdir.

## Required path

1. Run:

```bash
LOOPORA_AGENT_ENTRY_SOURCE={marker_source} loopora agent {adapter} loop --workdir "$PWD"{context_bits} --entry-source {marker_source} --json
```

2. Read the returned JSON, even if the command exits nonzero. If the payload has `ready: false` or `loop_recovery`, stop before dispatching any role agent:
   - `loop_recovery=finish_web_review` means the current `/loopora-gen` result needs Web review before `/loopora-loop`; report `preview_url`, `requires_web_alignment`, `loopora_fit_contradiction`, and the review focus instead of starting work.
   - `loop_recovery=repair_candidate_plan_file` means the candidate plan file failed validation; report `preview_url`, `requires_candidate_repair`, `loopora_fit_contradiction`, the source plan / preview copy paths from `binding` or `session`, and the validation / repair focus. Tell the user to repair the plan file, rerun `/loopora-gen`, and only then rerun `/loopora-loop`.
   - `loop_recovery=preview_not_ready` means the associated preview is not ready; return to `/loopora-gen` or Web review.
   Do not collapse these recovery states into a generic “run /loopora-gen first” message, and do not create a new plan implicitly from `/loopora-loop`.
3. For a runnable payload, read `run_url`, run-level `judgment_contract`, and, unless the run is already complete, `next_step` with its own `next_step.judgment_contract` projection. If `complete` is true and `task_next_action.kind` is `continue_evidence`, the run lifecycle is complete but the task is not proven; do not summarize the task as done.
4. Act as the Loopora Orchestrator. Do not perform role work inline. Read `next_step.role_dispatch.target_agent` and invoke that exact host-native role agent / task agent:
   - builder step -> `loopora-builder`
   - inspector/custom step -> `loopora-inspector`
   - gatekeeper step -> `loopora-gatekeeper`
   - guide step -> `loopora-guide`
{dispatch_guidance.rstrip()}
5. Pass the full `next_step.prompt`, `next_step.judgment_contract`, `next_step.required_coverage`, `next_step.output_schema`, `next_step.action_policy`, `next_step.known_evidence_ids`, and the capsule context refs (`next_step.context_path` and `next_step.context_absolute_path`) to the target role agent. Do not summarize, trim, or rewrite the prompt or judgment projection; they contain the frozen run contract, current step context, evidence rules, and output instructions.
6. Treat `next_step.judgment_contract`, `next_step.output_schema`, `next_step.action_policy`, `next_step.evidence_rules`, `next_step.evidence_ref_contract`, `next_step.known_evidence_ids`, and `next_step.role_dispatch` as the immutable step contract. If the host cannot invoke the required role agent, stop and report that native dispatch is unavailable rather than submitting inline work.
7. Open the result template from `next_step.submit_hint.result_template_absolute_path` or `next_step.submit_hint.result_template_path`. Do not hand-write the wrapper from memory. The template is the white-box handoff file for this step:

```json
{{
  "loopora_host_dispatch": {{ "...": "pre-filled native dispatch proof" }},
  "loopora_result_contract": {{ "...": "ignored on submit; use as the local fill guide" }},
  "result": {{ "...": null }}
}}
```

Read `loopora_result_contract.step_id`, `.role`, `.action_policy`, `.required_coverage`, `.known_evidence_ids`, `.evidence_ref_contract`, `.evidence_rules`, and `.output_schema` before filling the file. The template's `result` is a schema-shaped scaffold with invalid `null` placeholders. Replace every placeholder before submit, use empty arrays when the schema permits and there is no item to report, and remove optional placeholder fields you do not submit. The helper block is ignored by Loopora submit, so it may remain in the filled wrapper; never copy helper fields into `result`.

8. Save a filled copy under `next_step.submit_hint.result_outbox_absolute_dir` or `next_step.submit_hint.result_outbox_dir`, keeping the template available for audit. Preserve the template's `loopora_host_dispatch` exactly except for setting `actual_agent` only if the host-native role agent returned the same required target agent. Fill only the `result` object with the role agent output. The resulting wrapper should still have this shape:

```json
{{
  "loopora_host_dispatch": {{
    "schema_version": 1,
    "adapter": "{adapter}",
    "run_id": "<run-id>",
    "step_id": "<step-id>",
    "target_agent": "<next_step.role_dispatch.target_agent>",
    "actual_agent": "<same exact agent name>",
    "dispatch_mode": "host_subagent",
    "inline": false,
    "attestation": "The host invoked the named Loopora role agent for this step."
  }},
  "loopora_result_contract": {{ "...": "optional helper copied from the template; ignored on submit" }},
  "result": {{ "...": "must match next_step.output_schema exactly" }}
}}
```

For GateKeeper, `result` means `passed`, `decision_summary`, `evidence_refs`, and the other schema fields, not a `verdict` / `task_verdict` envelope. Any `evidence_refs` list must contain only exact IDs copied from the template's `loopora_result_contract.known_evidence_ids`; never create derived IDs such as `<known-id>_binding` or `<known-id>_output`.

9. Submit with `next_step.submit_hint.command` after replacing `<result-json>` with the filled result file path. If the command is unavailable, use the equivalent command below with the same `LOOPORA_AGENT_ENTRY_SOURCE` and `--entry-source` markers:

```bash
LOOPORA_AGENT_ENTRY_SOURCE={marker_source} loopora agent {adapter} submit --workdir "$PWD"{context_bits} --run-id <run-id> --step-id <step-id> --result-file <result-json> --entry-source {marker_source} --json
```

10. If the submit response returns another `next_step`, repeat native role dispatch, template fill, and submit. When `complete` is true, inspect `run.task_verdict.status` and any `task_next_action` before deciding what to report:
   - If the verdict is `passed` or `passed_with_residual_risk`, stop and report `run.run_status`, `run.task_verdict`, and `judgment_contract` separately.
   - If `task_next_action.kind` is `continue_evidence`, stop this run's role dispatch loop, but do not report the task as complete. Report `run.run_status`, `run.task_verdict`, `task_next_action.next_loop_command`, `task_next_action.guidance`, and any `task_next_action.task_verdict_summary`; tell the user that running `/loopora-loop` again in the same Agent session starts the next evidence pass with the previous verdict and coverage gaps.
   - If the verdict is anything else non-passing, fail closed: report the lifecycle/verdict split and ask the user to continue with `/loopora-loop` or adjust the Loop from the run URL instead of claiming success.

Copy the Loopora commands with `LOOPORA_AGENT_ENTRY_SOURCE` and `--entry-source`; those markers prove this run came from the Loopora-managed Agent entry.

## Boundaries

- If the command says no Loop preview is associated with this session/workdir, tell the user to run `/loopora-gen` first.
- If the command returns `loop_recovery`, report that recovery path and stop; do not proceed to role dispatch.
- Do not create a bundle implicitly from `/loopora-loop`.
- Do not bypass Loopora's bundle import, run lifecycle, evidence ledger, or GateKeeper verdict.
- Do not launch `codex`, `claude`, or `opencode` from inside this entry. The current host Agent must dispatch to the named host-native Loopora role agent and submit wrapper JSON to Loopora.
"""


def _codex_loopora_gen_skill() -> str:
    return f"""---
name: loopora-gen
description: "Use when the user invokes /loopora-gen to compile the current task goal, fake-done risks, and required evidence into a Loopora Loop preview without starting a run."
---

<!-- {MANAGED_MARKER} version={CODEX_ADAPTER_VERSION} file=loopora-gen -->

# Loopora Gen

Compile the current coding task judgment into a Loopora Loop preview: task goal, fake-done risks, required evidence, blockers, and residual-risk policy. Do not start a run.

## Required path

1. Summarize the current task, workdir, constraints, Loopora fit, local governance files, fake-done risks, evidence expectations, execution strategy, judgment tradeoffs, and residual-risk policy from the current Codex context. Loopora fit must say why one Agent pass, one review, direct chat / direct answer, one-off task handling, or benchmark/test-harness-only validation is not enough, and what later rounds will add as new evidence, handoffs, or a GateKeeper verdict. If `AGENTS.md`, `design/README.md`, `design/`, or `tests/` matter, compile them into Builder reading, Inspector / Custom verification, and GateKeeper Weak / Unproven / Blocking responsibility rather than a marker list. Execution strategy must say what to build, prove, repair, narrow, expand, or defer first; residual risk must name what can be accepted plus an owner, follow-up, or acceptance path, or say the task fails closed. Preserve task-specific categories such as notification, audit, permission, payment, export, browser journey, command evidence, owner, follow-up, and acceptance path; do not let a bundle pass merely because it repeats one or two object words from the task.
2. Check Loopora fit and judgment sufficiency before authoring a Loop plan file: Loopora fit, success surface, fake-done risks, evidence expectations, execution strategy, judgment tradeoffs, residual-risk policy, and local governance responsibilities must be explicit enough to shape `spec`, roles, workflow, evidence flow, and GateKeeper strictness. If Loopora fit is false or a missing human decision would change the Loop shape, explain that or ask one focused question; if the host cannot continue that conversation, call `loopora agent codex gen` with `--message "<non-empty short task summary>"` but without `--bundle-file` to return a Web review prefill. Do not invent human judgment just to pass validation.
3. Create a complete Loopora `version: 1` candidate plan file for that task. The plan file must express `spec`, `role_definitions`, `workflow`, evidence flow, and a GateKeeper finish step. Preserve the current task's Loopora fit reason, high-signal objects, success outcome categories, fake-done risk categories, concrete evidence modes, execution priorities, judgment tradeoffs, local governance responsibilities, and risk terms in the runnable surfaces, not only in the short CLI summary. If the current task explicitly provides a candidate plan file path, submit that file instead of reauthoring it.
4. Save a newly authored candidate plan file to a temporary file under `.loopora/agent_inbox/codex/`; if a candidate path was explicitly provided, use that path.
5. Run:

```bash
LOOPORA_AGENT_ENTRY_SOURCE=codex_project_skill loopora agent codex gen --workdir "$PWD" --message "<non-empty short task summary>" --bundle-file <candidate-plan-file> --entry-source codex_project_skill
```

6. Report the returned Loop preview URL and the `ready_review_projection` summary when present: Loopora fit, fake-done risks, evidence expectations, coverage targets, judgment projection, and closure gate. If the preview is ready, tell the user to confirm that review summary and preview URL, then run `/loopora-loop` in this same Agent session; do not start the run from Web. If validation fails, report the Loopora error and repair the plan file before trying again.

Copy the command exactly, including `LOOPORA_AGENT_ENTRY_SOURCE` and `--entry-source`; those markers bind this invocation to Loopora's Core evidence trail.

## Boundaries

- `/loopora-gen` never starts a run.
- READY is decided by Loopora Core validation, not by Codex prose.
- If the task does not need a long-running evidence-governed Loop, explain that before generating.
- If judgment is missing, do not fill it with generic best practices; ask the user or return the Web review prefill.
- If `loopora agent codex gen` returns a Web review URL instead of a ready preview, tell the user it needs Web review or more Loop setup before `/loopora-loop`.
"""


def _codex_loopora_loop_skill() -> str:
    return f"""---
name: loopora-loop
description: "Use when the user invokes /loopora-loop to start or resume the reviewed Loop preview that preserves the current task judgment and evidence requirements."
---

<!-- {MANAGED_MARKER} version={CODEX_ADAPTER_VERSION} file=loopora-loop -->

# Loopora Loop

{_agent_native_loop_body(adapter="codex", marker_source="codex_project_skill").rstrip()}
"""


def _claude_loopora_gen_skill() -> str:
    return f"""---
name: loopora-gen
description: "Compile the current Claude Code task goal, fake-done risks, and required evidence into a Loopora Loop preview without starting a run. Invoke manually as /loopora-gen."
disable-model-invocation: true
allowed-tools: "Bash(loopora agent claude gen *) Bash(LOOPORA_AGENT_ENTRY_SOURCE=claude_project_skill loopora agent claude gen *)"
---

<!-- {CLAUDE_MANAGED_MARKER} version={CLAUDE_ADAPTER_VERSION} file=loopora-gen -->

# Loopora Gen

Compile the current Claude Code task judgment into a Loopora Loop preview: task goal, fake-done risks, required evidence, blockers, and residual-risk policy. Do not start a run.

## Required path

1. Summarize the current task, workdir, constraints, Loopora fit, local governance files, fake-done risks, evidence expectations, execution strategy, judgment tradeoffs, and residual-risk policy from the current Claude Code context. Loopora fit must say why one Agent pass, one review, direct chat / direct answer, one-off task handling, or benchmark/test-harness-only validation is not enough, and what later rounds will add as new evidence, handoffs, or a GateKeeper verdict. If `AGENTS.md`, `design/README.md`, `design/`, or `tests/` matter, compile them into Builder reading, Inspector / Custom verification, and GateKeeper Weak / Unproven / Blocking responsibility rather than a marker list. Execution strategy must say what to build, prove, repair, narrow, expand, or defer first; residual risk must name what can be accepted plus an owner, follow-up, or acceptance path, or say the task fails closed. Preserve task-specific categories such as notification, audit, permission, payment, export, browser journey, command evidence, owner, follow-up, and acceptance path; do not let a bundle pass merely because it repeats one or two object words from the task.
2. Check Loopora fit and judgment sufficiency before authoring a Loop plan file: Loopora fit, success surface, fake-done risks, evidence expectations, execution strategy, judgment tradeoffs, residual-risk policy, and local governance responsibilities must be explicit enough to shape `spec`, roles, workflow, evidence flow, and GateKeeper strictness. If Loopora fit is false or a missing human decision would change the Loop shape, ask one focused question; if the host cannot continue that conversation, call `loopora agent claude gen` with `--message "<non-empty short task summary>"` but without `--bundle-file` to return a Web review prefill. Do not invent human judgment just to pass validation.
3. Create a complete Loopora `version: 1` candidate plan file for that task. The plan file must express `spec`, `role_definitions`, `workflow`, evidence flow, and a GateKeeper finish step. Preserve the current task's Loopora fit reason, high-signal objects, success outcome categories, fake-done risk categories, concrete evidence modes, execution priorities, judgment tradeoffs, local governance responsibilities, and risk terms in the runnable surfaces, not only in the short CLI summary. If the current task explicitly provides a candidate plan file path, submit that file instead of reauthoring it.
4. Save a newly authored candidate plan file to a temporary file under `.loopora/agent_inbox/claude/`; if a candidate path was explicitly provided, use that path.
5. Run:

```bash
LOOPORA_AGENT_ENTRY_SOURCE=claude_project_skill loopora agent claude gen --workdir "$PWD" --context-id "${{CLAUDE_SESSION_ID}}" --message "<non-empty short task summary>" --bundle-file <candidate-plan-file> --entry-source claude_project_skill
```

6. Report the returned Loop preview URL and the `ready_review_projection` summary when present: Loopora fit, fake-done risks, evidence expectations, coverage targets, judgment projection, and closure gate. If the preview is ready, tell the user to confirm that review summary and preview URL, then run `/loopora-loop` in this same Agent session; do not start the run from Web. If validation fails, report the Loopora error and repair the plan file before trying again.

Copy the command exactly, including `LOOPORA_AGENT_ENTRY_SOURCE`, `--context-id`, and `--entry-source`; those markers bind the current Claude Code session to Loopora's Core evidence trail.

## Boundaries

- `/loopora-gen` never starts a run.
- READY is decided by Loopora Core validation, not by Claude Code prose.
- If the task does not need a long-running evidence-governed Loop, explain that before generating.
- If judgment is missing, do not fill it with generic best practices; ask the user or return the Web review prefill.
- If `loopora agent claude gen` returns a Web review URL instead of a ready preview, tell the user it needs Web review or more Loop setup before `/loopora-loop`.
"""


def _claude_loopora_loop_skill() -> str:
    return f"""---
name: loopora-loop
description: "Start or reuse the reviewed Loop preview that preserves this Claude Code task judgment and evidence requirements. Invoke manually after /loopora-gen."
disable-model-invocation: true
allowed-tools: "Bash(loopora agent claude loop *) Bash(loopora agent claude next *) Bash(loopora agent claude submit *) Bash(LOOPORA_AGENT_ENTRY_SOURCE=claude_project_skill loopora agent claude *) Task"
---

<!-- {CLAUDE_MANAGED_MARKER} version={CLAUDE_ADAPTER_VERSION} file=loopora-loop -->

# Loopora Loop

{_agent_native_loop_body(adapter="claude", marker_source="claude_project_skill", context_arg='--context-id "${CLAUDE_SESSION_ID}"').rstrip()}
"""


def _opencode_loopora_gen_command() -> str:
    return f"""---
description: Compile the current OpenCode task goal, fake-done risks, and required evidence into a Loopora Loop preview without starting a run.
---

<!-- {OPENCODE_MANAGED_MARKER} version={OPENCODE_ADAPTER_VERSION} file=loopora-gen -->

# Loopora Gen

Compile the current OpenCode task judgment into a Loopora Loop preview: task goal, fake-done risks, required evidence, blockers, and residual-risk policy. Do not start a run.

## Arguments

`$ARGUMENTS` may contain an existing candidate plan file path. If it does, submit that file instead of authoring a different plan file.

## Required path

1. Summarize the current task, workdir, constraints, Loopora fit, local governance files, fake-done risks, evidence expectations, execution strategy, judgment tradeoffs, and residual-risk policy from the current OpenCode context. Loopora fit must say why one Agent pass, one review, direct chat / direct answer, one-off task handling, or benchmark/test-harness-only validation is not enough, and what later rounds will add as new evidence, handoffs, or a GateKeeper verdict. If `AGENTS.md`, `design/README.md`, `design/`, or `tests/` matter, compile them into Builder reading, Inspector / Custom verification, and GateKeeper Weak / Unproven / Blocking responsibility rather than a marker list. Execution strategy must say what to build, prove, repair, narrow, expand, or defer first; residual risk must name what can be accepted plus an owner, follow-up, or acceptance path, or say the task fails closed. Preserve task-specific categories such as notification, audit, permission, payment, export, browser journey, command evidence, owner, follow-up, and acceptance path; do not let a bundle pass merely because it repeats one or two object words from the task.
2. Check Loopora fit and judgment sufficiency before authoring a Loop plan file: Loopora fit, success surface, fake-done risks, evidence expectations, execution strategy, judgment tradeoffs, residual-risk policy, and local governance responsibilities must be explicit enough to shape `spec`, roles, workflow, evidence flow, and GateKeeper strictness. If Loopora fit is false or a missing human decision would change the Loop shape, ask one focused question; if the host cannot continue that conversation, call `loopora agent opencode gen` with `--message "<non-empty short task summary>"` but without `--bundle-file` to return a Web review prefill. Do not invent human judgment just to pass validation.
3. Create a complete Loopora `version: 1` candidate plan file for that task. The plan file must express `spec`, `role_definitions`, `workflow`, evidence flow, and a GateKeeper finish step. Preserve the current task's Loopora fit reason, high-signal objects, success outcome categories, fake-done risk categories, concrete evidence modes, execution priorities, judgment tradeoffs, local governance responsibilities, and risk terms in the runnable surfaces, not only in the short CLI summary. If `$ARGUMENTS` provides a candidate path, use that path.
4. Save a newly authored candidate plan file to a temporary file under `.loopora/agent_inbox/opencode/`; if a candidate path was provided, use that path.
5. Run:

```bash
LOOPORA_AGENT_ENTRY_SOURCE=opencode_project_command loopora agent opencode gen --workdir "$PWD" --context-id "${{OPENCODE_SESSION_ID:-}}" --message "<non-empty short task summary>" --bundle-file <candidate-plan-file> --entry-source opencode_project_command
```

6. Report the returned Loop preview URL and the `ready_review_projection` summary when present: Loopora fit, fake-done risks, evidence expectations, coverage targets, judgment projection, and closure gate. If the preview is ready, tell the user to confirm that review summary and preview URL, then run `/loopora-loop` in this same Agent session; do not start the run from Web. If validation fails, report the Loopora error and repair the plan file before trying again.

Copy the command exactly, including `LOOPORA_AGENT_ENTRY_SOURCE`, `--context-id`, and `--entry-source`; those markers bind this invocation to Loopora's Core evidence trail. If OpenCode does not expose `OPENCODE_SESSION_ID`, keep the flag as shown and Loopora will fall back to workdir binding.

## Boundaries

- `/loopora-gen` never starts a run.
- READY is decided by Loopora Core validation, not by OpenCode prose.
- If the task does not need a long-running evidence-governed Loop, explain that before generating.
- If judgment is missing, do not fill it with generic best practices; ask the user or return the Web review prefill.
- If `loopora agent opencode gen` returns a Web review URL instead of a ready preview, tell the user it needs Web review or more Loop setup before `/loopora-loop`.
"""


def _opencode_loopora_loop_command() -> str:
    return f"""---
description: Start or reuse the reviewed Loop preview that preserves this OpenCode task judgment and evidence requirements.
agent: loopora-orchestrator
subtask: true
---

<!-- {OPENCODE_MANAGED_MARKER} version={OPENCODE_ADAPTER_VERSION} file=loopora-loop -->

# Loopora Loop

{_agent_native_loop_body(adapter="opencode", marker_source="opencode_project_command", context_arg='--context-id "${OPENCODE_SESSION_ID:-}"').rstrip()}
"""
