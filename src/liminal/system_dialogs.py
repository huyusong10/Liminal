from __future__ import annotations

import subprocess
import sys
from pathlib import Path


class SystemDialogError(RuntimeError):
    """Raised when the host cannot open a native file dialog."""


def pick_directory(start_path: str | None = None) -> str | None:
    return _run_dialog("directory", start_path=start_path)


def pick_file(start_path: str | None = None) -> str | None:
    return _run_dialog("file", start_path=start_path)


def pick_save_file(start_path: str | None = None, *, default_name: str = "spec.md") -> str | None:
    return _run_dialog("save", start_path=start_path, default_name=default_name)


def _run_dialog(kind: str, *, start_path: str | None = None, default_name: str = "spec.md") -> str | None:
    if sys.platform == "darwin":
        return _run_osascript_dialog(kind, start_path=start_path, default_name=default_name)
    return _run_tk_dialog(kind, start_path=start_path, default_name=default_name)


def _run_osascript_dialog(kind: str, *, start_path: str | None, default_name: str) -> str | None:
    prompt_map = {
        "directory": "Select a workdir",
        "file": "Select a spec file",
        "save": "Choose where to create the spec template",
    }
    location = _dialog_location(start_path, for_file=(kind == "file"))
    clauses = [f'with prompt "{_escape_applescript(prompt_map[kind])}"']
    if location is not None:
        clauses.append(f'default location POSIX file "{_escape_applescript(str(location))}"')
    if kind == "save":
        clauses.append(f'default name "{_escape_applescript(default_name)}"')
        script = f'POSIX path of (choose file name {" ".join(clauses)})'
    elif kind == "file":
        script = f'POSIX path of (choose file {" ".join(clauses)})'
    else:
        script = f'POSIX path of (choose folder {" ".join(clauses)})'
    return _run_osascript(script)


def _run_osascript(script: str) -> str | None:
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        output = result.stdout.strip()
        return str(Path(output).expanduser().resolve()) if output else None

    stderr = f"{result.stderr}\n{result.stdout}".lower()
    if "-128" in stderr or "user canceled" in stderr or "cancelled" in stderr:
        return None
    raise SystemDialogError(result.stderr.strip() or "native dialog failed")


def _run_tk_dialog(kind: str, *, start_path: str | None, default_name: str) -> str | None:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as exc:  # pragma: no cover - platform dependent
        raise SystemDialogError("native dialogs are unavailable in this environment") from exc

    initial = _dialog_location(start_path, for_file=(kind == "file"))
    root = None
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        if kind == "directory":
            selected = filedialog.askdirectory(initialdir=str(initial) if initial else None)
        elif kind == "file":
            selected = filedialog.askopenfilename(
                initialdir=str(initial) if initial else None,
                filetypes=[("Markdown", "*.md"), ("All files", "*.*")],
            )
        else:
            selected = filedialog.asksaveasfilename(
                initialdir=str(initial) if initial else None,
                initialfile=default_name,
                defaultextension=".md",
                filetypes=[("Markdown", "*.md"), ("All files", "*.*")],
            )
    except Exception as exc:  # pragma: no cover - platform dependent
        raise SystemDialogError("failed to open a native dialog") from exc
    finally:  # pragma: no branch - best effort cleanup
        try:
            root.destroy()
        except Exception:
            pass

    return str(Path(selected).expanduser().resolve()) if selected else None


def _dialog_location(start_path: str | None, *, for_file: bool) -> Path | None:
    if not start_path:
        return None
    path = Path(start_path).expanduser()
    if path.exists():
        if path.is_dir():
            return path
        return path.parent if for_file else path.parent
    if path.suffix:
        return path.parent
    return path


def _escape_applescript(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
