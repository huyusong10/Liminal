from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from loopora.branding import state_dir_for_workdir
from loopora.service_types import LooporaConflictError, LooporaError
from loopora.utils import utc_now

AGENT_ADAPTER_KINDS = ("codex", "claude", "opencode")
IMPLEMENTED_AGENT_ADAPTERS = {"codex", "claude", "opencode"}
ADAPTER_VERSION = 1
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
    explicit = (
        str(context_id or "").strip()
        or os.environ.get("LOOPORA_AGENT_SESSION_ID", "").strip()
        or _adapter_session_env(kind)
    )
    source = explicit or f"workdir:{root}"
    return hashlib.sha256(f"{kind}:{source}".encode()).hexdigest()[:20]


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
    paths = sorted(set(_manifest_paths(manifest_payload)) | set(templates)) if manifest_exists else sorted(templates)
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
    stop_dirs = {root, root / ".agents", root / ".claude", root / ".opencode", root / ".loopora"}
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
    }


def _claude_managed_templates() -> dict[str, str]:
    return {
        ".claude/skills/loopora-gen/SKILL.md": _claude_loopora_gen_skill(),
        ".claude/skills/loopora-loop/SKILL.md": _claude_loopora_loop_skill(),
    }


def _opencode_managed_templates() -> dict[str, str]:
    return {
        ".opencode/commands/loopora-gen.md": _opencode_loopora_gen_command(),
        ".opencode/commands/loopora-loop.md": _opencode_loopora_loop_command(),
    }


def _codex_loopora_gen_skill() -> str:
    return f"""---
name: loopora-gen
description: "Use when the user invokes /loopora-gen, asks to generate a Loopora candidate Loop from the current coding task, or wants the Codex session to compile a READY Loopora bundle without starting a run."
---

<!-- {MANAGED_MARKER} version={CODEX_ADAPTER_VERSION} file=loopora-gen -->

# Loopora Gen

Compile the current coding task into a Loopora candidate Loop. Do not start a run.

## Required path

1. Summarize the current task, workdir, constraints, local governance files, fake-done risks, evidence expectations, and residual-risk policy from the current Codex context.
2. Create a complete Loopora `version: 1` bundle YAML for that task. The bundle must express `spec`, `role_definitions`, `workflow`, evidence flow, and a GateKeeper finish step. If the current task explicitly provides a candidate bundle YAML path, submit that file instead of reauthoring it.
3. Save newly authored candidate YAML to a temporary file under `.loopora/agent_inbox/codex/`; if a candidate path was explicitly provided, use that path.
4. Run:

```bash
LOOPORA_AGENT_ENTRY_SOURCE=codex_project_skill loopora agent codex gen --workdir "$PWD" --message "<short task summary>" --bundle-file <candidate-yaml-path> --entry-source codex_project_skill
```

5. Report the returned candidate Loop URL. If validation fails, report the Loopora error and fix the YAML before trying again.

Copy the command exactly, including `LOOPORA_AGENT_ENTRY_SOURCE` and `--entry-source`; those markers bind this invocation to Loopora's Core evidence trail.

## Boundaries

- `/loopora-gen` never starts a run.
- READY is decided by Loopora Core validation, not by Codex prose.
- If the task does not need a long-running evidence-governed Loop, explain that before generating.
- If `loopora agent codex gen` returns a non-READY Web alignment URL, tell the user it needs Web confirmation or more alignment before `/loopora-loop`.
"""


def _codex_loopora_loop_skill() -> str:
    return f"""---
name: loopora-loop
description: "Use when the user invokes /loopora-loop or asks Codex to start or resume the Loopora-managed Loop for the current coding task after /loopora-gen has produced a READY bundle."
---

<!-- {MANAGED_MARKER} version={CODEX_ADAPTER_VERSION} file=loopora-loop -->

# Loopora Loop

Start or reuse the Loopora-managed run for the READY bundle associated with this Codex session or workdir.

## Required path

Run:

```bash
LOOPORA_AGENT_ENTRY_SOURCE=codex_project_skill loopora agent codex loop --workdir "$PWD" --entry-source codex_project_skill
```

Then report the returned run or Loop URL and continue work under the Loopora governance context shown there.

Copy the command exactly, including `LOOPORA_AGENT_ENTRY_SOURCE` and `--entry-source`; those markers prove this run came from the Loopora-managed Codex entry.

## Boundaries

- If the command says no READY bundle is associated with this session/workdir, tell the user to run `/loopora-gen` first.
- Do not create a bundle implicitly from `/loopora-loop`.
- Do not bypass Loopora's bundle import, run lifecycle, evidence ledger, or GateKeeper verdict.
"""


def _claude_loopora_gen_skill() -> str:
    return f"""---
name: loopora-gen
description: "Generate a Loopora candidate Loop from the current Claude Code task without starting a run. Invoke manually as /loopora-gen."
disable-model-invocation: true
allowed-tools: "Bash(loopora agent claude gen *) Bash(LOOPORA_AGENT_ENTRY_SOURCE=claude_project_skill loopora agent claude gen *)"
---

<!-- {CLAUDE_MANAGED_MARKER} version={CLAUDE_ADAPTER_VERSION} file=loopora-gen -->

# Loopora Gen

Compile the current Claude Code task into a Loopora candidate Loop. Do not start a run.

## Required path

1. Summarize the current task, workdir, constraints, local governance files, fake-done risks, evidence expectations, and residual-risk policy from the current Claude Code context.
2. Create a complete Loopora `version: 1` bundle YAML for that task. The bundle must express `spec`, `role_definitions`, `workflow`, evidence flow, and a GateKeeper finish step. If the current task explicitly provides a candidate bundle YAML path, submit that file instead of reauthoring it.
3. Save newly authored candidate YAML to a temporary file under `.loopora/agent_inbox/claude/`; if a candidate path was explicitly provided, use that path.
4. Run:

```bash
LOOPORA_AGENT_ENTRY_SOURCE=claude_project_skill loopora agent claude gen --workdir "$PWD" --context-id "${{CLAUDE_SESSION_ID}}" --message "<short task summary>" --bundle-file <candidate-yaml-path> --entry-source claude_project_skill
```

5. Report the returned candidate Loop URL. If validation fails, report the Loopora error and fix the YAML before trying again.

Copy the command exactly, including `LOOPORA_AGENT_ENTRY_SOURCE`, `--context-id`, and `--entry-source`; those markers bind the current Claude Code session to Loopora's Core evidence trail.

## Boundaries

- `/loopora-gen` never starts a run.
- READY is decided by Loopora Core validation, not by Claude Code prose.
- If the task does not need a long-running evidence-governed Loop, explain that before generating.
- If `loopora agent claude gen` returns a non-READY Web alignment URL, tell the user it needs Web confirmation or more alignment before `/loopora-loop`.
"""


def _claude_loopora_loop_skill() -> str:
    return f"""---
name: loopora-loop
description: "Start or reuse the Loopora-managed run for the READY bundle associated with this Claude Code task. Invoke manually after /loopora-gen."
disable-model-invocation: true
allowed-tools: "Bash(loopora agent claude loop *) Bash(LOOPORA_AGENT_ENTRY_SOURCE=claude_project_skill loopora agent claude loop *)"
---

<!-- {CLAUDE_MANAGED_MARKER} version={CLAUDE_ADAPTER_VERSION} file=loopora-loop -->

# Loopora Loop

Start or reuse the Loopora-managed run for the READY bundle associated with this Claude Code session or workdir.

## Required path

Run:

```bash
LOOPORA_AGENT_ENTRY_SOURCE=claude_project_skill loopora agent claude loop --workdir "$PWD" --context-id "${{CLAUDE_SESSION_ID}}" --entry-source claude_project_skill
```

Then report the returned run or Loop URL and continue work under the Loopora governance context shown there.

Copy the command exactly, including `LOOPORA_AGENT_ENTRY_SOURCE`, `--context-id`, and `--entry-source`; those markers prove this run came from the Loopora-managed Claude Code entry.

## Boundaries

- If the command says no READY bundle is associated with this session/workdir, tell the user to run `/loopora-gen` first.
- Do not create a bundle implicitly from `/loopora-loop`.
- Do not bypass Loopora's bundle import, run lifecycle, evidence ledger, or GateKeeper verdict.
"""


def _opencode_loopora_gen_command() -> str:
    return f"""---
description: Generate a Loopora candidate Loop from the current OpenCode task without starting a run.
agent: build
---

<!-- {OPENCODE_MANAGED_MARKER} version={OPENCODE_ADAPTER_VERSION} file=loopora-gen -->

# Loopora Gen

Compile the current OpenCode task into a Loopora candidate Loop. Do not start a run.

## Arguments

`$ARGUMENTS` may contain an existing candidate bundle YAML path. If it does, submit that file instead of authoring a different bundle.

## Required path

1. Summarize the current task, workdir, constraints, local governance files, fake-done risks, evidence expectations, and residual-risk policy from the current OpenCode context.
2. Create a complete Loopora `version: 1` bundle YAML for that task. The bundle must express `spec`, `role_definitions`, `workflow`, evidence flow, and a GateKeeper finish step. If `$ARGUMENTS` provides a candidate path, use that path.
3. Save newly authored candidate YAML to a temporary file under `.loopora/agent_inbox/opencode/`; if a candidate path was provided, use that path.
4. Run:

```bash
LOOPORA_AGENT_ENTRY_SOURCE=opencode_project_command loopora agent opencode gen --workdir "$PWD" --context-id "${{OPENCODE_SESSION_ID:-}}" --message "<short task summary>" --bundle-file <candidate-yaml-path> --entry-source opencode_project_command
```

5. Report the returned candidate Loop URL. If validation fails, report the Loopora error and fix the YAML before trying again.

Copy the command exactly, including `LOOPORA_AGENT_ENTRY_SOURCE`, `--context-id`, and `--entry-source`; those markers bind this invocation to Loopora's Core evidence trail. If OpenCode does not expose `OPENCODE_SESSION_ID`, keep the flag as shown and Loopora will fall back to workdir binding.

## Boundaries

- `/loopora-gen` never starts a run.
- READY is decided by Loopora Core validation, not by OpenCode prose.
- If the task does not need a long-running evidence-governed Loop, explain that before generating.
- If `loopora agent opencode gen` returns a non-READY Web alignment URL, tell the user it needs Web confirmation or more alignment before `/loopora-loop`.
"""


def _opencode_loopora_loop_command() -> str:
    return f"""---
description: Start or reuse the Loopora-managed run for the READY bundle associated with this OpenCode task.
agent: build
---

<!-- {OPENCODE_MANAGED_MARKER} version={OPENCODE_ADAPTER_VERSION} file=loopora-loop -->

# Loopora Loop

Start or reuse the Loopora-managed run for the READY bundle associated with this OpenCode session or workdir.

## Required path

Run:

```bash
LOOPORA_AGENT_ENTRY_SOURCE=opencode_project_command loopora agent opencode loop --workdir "$PWD" --context-id "${{OPENCODE_SESSION_ID:-}}" --entry-source opencode_project_command
```

Then report the returned run or Loop URL and continue work under the Loopora governance context shown there.

Copy the command exactly, including `LOOPORA_AGENT_ENTRY_SOURCE`, `--context-id`, and `--entry-source`; those markers prove this run came from the Loopora-managed OpenCode command.

## Boundaries

- If the command says no READY bundle is associated with this session/workdir, tell the user to run `/loopora-gen` first.
- Do not create a bundle implicitly from `/loopora-loop`.
- Do not bypass Loopora's bundle import, run lifecycle, evidence ledger, or GateKeeper verdict.
"""
