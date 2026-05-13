from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[3]
RUNNER = REPO_ROOT / "tests" / "probes" / "real_environment" / "run_real_probes.py"
PLAYBOOK = REPO_ROOT / "tests" / "probes" / "real_environment" / "README.md"


def _load_runner_module():
    spec = importlib.util.spec_from_file_location("run_real_probes", RUNNER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _dry_run(*args: str) -> str:
    env = os.environ.copy()
    env.pop("LOOPORA_REAL_AGENT_TARGETS", None)
    env.pop("LOOPORA_REAL_CLI_TARGETS", None)
    completed = subprocess.run(
        [sys.executable, str(RUNNER), *args, "--dry-run"],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    return completed.stdout


def test_real_probe_runner_splits_real_agent_targets_into_independent_jobs() -> None:
    output = _dry_run("--suite", "real-agent", "--agent-targets", "codex,claudecode,open-code")

    assert f"[real-probe] handbook: {PLAYBOOK}" in output
    assert "real-agent:codex" in output
    assert "LOOPORA_REAL_AGENT_TARGETS=codex" in output
    assert "real-agent:claude" in output
    assert "LOOPORA_REAL_AGENT_TARGETS=claude" in output
    assert "real-agent:opencode" in output
    assert "LOOPORA_REAL_AGENT_TARGETS=opencode" in output
    assert "tests/probes/real_environment/test_real_agent_adapter_probe.py" in output


def test_real_probe_runner_splits_real_cli_targets_into_independent_jobs() -> None:
    output = _dry_run("--suite", "real-cli", "--cli-targets", "opencode")

    assert "real-cli:opencode" in output
    assert "LOOPORA_ENABLE_REAL_CLI_PROBE=1" in output
    assert "LOOPORA_REAL_CLI_TARGETS=opencode" in output
    assert "tests/probes/real_environment/test_real_cli_probe.py" in output


def test_real_probe_runner_expands_all_suites_without_shared_targets() -> None:
    output = _dry_run("--suite", "all", "--agent-targets", "codex,claude,opencode", "--cli-targets", "codex")

    assert "real-agent:codex" in output
    assert "real-agent:claude" in output
    assert "real-agent:opencode" in output
    assert "real-cli:codex" in output
    assert "release-web" in output
    assert "LOOPORA_REAL_AGENT_TARGETS=codex" in output
    assert "LOOPORA_REAL_AGENT_TARGETS=claude" in output
    assert "LOOPORA_REAL_AGENT_TARGETS=opencode" in output
    assert "LOOPORA_REAL_CLI_TARGETS=codex" in output


def test_real_probe_runner_show_playbook_is_the_documented_entry() -> None:
    completed = subprocess.run(
        [sys.executable, str(RUNNER), "--show-playbook"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )

    assert "Loopora Real Probe Handbook" in completed.stdout
    assert "Read it before running or interpreting any real-environment probe." in completed.stdout


def test_real_probe_runner_reports_waiting_jobs(capsys) -> None:
    runner = _load_runner_module()
    exit_code = runner.run_jobs(
        [
            runner.RealProbeJob(
                name="unit:sleep",
                command=(sys.executable, "-c", "import time; time.sleep(0.7)"),
                env_updates=(),
            )
        ],
        max_parallel=1,
        status_interval=0.01,
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert f"[real-probe] handbook: {PLAYBOOK}" in output
    assert "[real-probe] log unit:sleep:" in output
    assert "[real-probe] waiting unit:sleep:" in output
    assert "log=" in output


def test_real_probe_runner_preserves_failed_job_log(capsys) -> None:
    runner = _load_runner_module()
    exit_code = runner.run_jobs(
        [
            runner.RealProbeJob(
                name="unit:fail",
                command=(sys.executable, "-c", "print('diagnostic breadcrumb'); raise SystemExit(3)"),
                env_updates=(),
            )
        ],
        max_parallel=1,
        status_interval=0,
    )

    output = capsys.readouterr().out
    assert exit_code == 3
    assert "diagnostic breadcrumb" in output
    preserved_line = next(line for line in output.splitlines() if line.startswith("[real-probe] preserved log: "))
    preserved_path = Path(preserved_line.removeprefix("[real-probe] preserved log: "))
    try:
        assert preserved_path.exists()
        assert "diagnostic breadcrumb" in preserved_path.read_text(encoding="utf-8")
    finally:
        preserved_path.unlink(missing_ok=True)
