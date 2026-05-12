from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER = REPO_ROOT / "tests" / "run_l3_parallel.py"
PLAYBOOK = REPO_ROOT / "tests" / "l3" / "README.md"


def _load_runner_module():
    spec = importlib.util.spec_from_file_location("run_l3_parallel", RUNNER)
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


def test_l3_parallel_runner_splits_real_agent_targets_into_independent_jobs() -> None:
    output = _dry_run("--suite", "real-agent", "--agent-targets", "codex,claudecode,open-code")

    assert f"[l3] handbook: {PLAYBOOK}" in output
    assert "real-agent:codex" in output
    assert "LOOPORA_REAL_AGENT_TARGETS=codex" in output
    assert "real-agent:claude" in output
    assert "LOOPORA_REAL_AGENT_TARGETS=claude" in output
    assert "real-agent:opencode" in output
    assert "LOOPORA_REAL_AGENT_TARGETS=opencode" in output
    assert "tests/test_real_agent_adapter_e2e.py" in output


def test_l3_parallel_runner_splits_real_cli_targets_into_independent_jobs() -> None:
    output = _dry_run("--suite", "real-cli", "--cli-targets", "opencode")

    assert "real-cli:opencode" in output
    assert "LOOPORA_ENABLE_REAL_CLI_E2E=1" in output
    assert "LOOPORA_REAL_CLI_TARGETS=opencode" in output
    assert "tests/test_real_cli_integration.py" in output


def test_l3_parallel_runner_expands_all_suites_without_shared_targets() -> None:
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


def test_l3_parallel_runner_show_playbook_is_the_documented_entry() -> None:
    completed = subprocess.run(
        [sys.executable, str(RUNNER), "--show-playbook"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )

    assert "Loopora L3 Agent Handbook" in completed.stdout
    assert "Read it before running or interpreting any L3 test." in completed.stdout


def test_l3_parallel_runner_reports_waiting_jobs(capsys) -> None:
    runner = _load_runner_module()
    exit_code = runner.run_jobs(
        [
                runner.L3Job(
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
    assert f"[l3] handbook: {PLAYBOOK}" in output
    assert "[l3] log unit:sleep:" in output
    assert "[l3] waiting unit:sleep:" in output
    assert "log=" in output


def test_l3_parallel_runner_preserves_failed_job_log(capsys) -> None:
    runner = _load_runner_module()
    exit_code = runner.run_jobs(
        [
            runner.L3Job(
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
    preserved_line = next(line for line in output.splitlines() if line.startswith("[l3] preserved log: "))
    preserved_path = Path(preserved_line.removeprefix("[l3] preserved log: "))
    try:
        assert preserved_path.exists()
        assert "diagnostic breadcrumb" in preserved_path.read_text(encoding="utf-8")
    finally:
        preserved_path.unlink(missing_ok=True)
