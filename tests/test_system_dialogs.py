from __future__ import annotations

import subprocess
from pathlib import Path

import loopora.system_dialogs as system_dialogs


def test_reveal_path_uses_finder_on_macos(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "demo"
    target.mkdir()
    calls: list[list[str]] = []

    def fake_run(command, capture_output, text, check):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(system_dialogs.sys, "platform", "darwin")
    monkeypatch.setattr(system_dialogs.subprocess, "run", fake_run)

    revealed = system_dialogs.reveal_path(str(target))

    assert revealed == str(target.resolve())
    assert calls
    assert calls[0][:2] == ["osascript", "-e"]
    assert "Finder" in calls[0][2]


def test_reveal_path_uses_startfile_on_windows(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "demo"
    target.mkdir()
    opened: list[str] = []

    def fake_startfile(path: str) -> None:
        opened.append(path)

    monkeypatch.setattr(system_dialogs.sys, "platform", "win32")
    monkeypatch.setattr(system_dialogs.os, "startfile", fake_startfile, raising=False)

    revealed = system_dialogs.reveal_path(str(target))

    assert revealed == str(target.resolve())
    assert opened == [str(target.resolve())]


def test_reveal_path_uses_xdg_open_on_linux(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "demo"
    target.mkdir()
    calls: list[list[str]] = []

    def fake_run(command, capture_output, text, check):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(system_dialogs.sys, "platform", "linux")
    monkeypatch.setattr(system_dialogs.subprocess, "run", fake_run)

    revealed = system_dialogs.reveal_path(str(target))

    assert revealed == str(target.resolve())
    assert calls == [["xdg-open", str(target.resolve())]]
