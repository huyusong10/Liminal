#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import time


REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
REAL_PROBE_PLAYBOOK = REPO_ROOT / "tests" / "probes" / "real_environment" / "README.md"
SUITES = ("real-agent", "real-cli", "release-web")
HOST_TARGETS = ("codex", "claude", "opencode")
TARGET_ALIASES = {
    "claude-code": "claude",
    "claudecode": "claude",
    "claude_code": "claude",
    "open-code": "opencode",
    "open_code": "opencode",
}


@dataclass(frozen=True, slots=True)
class RealProbeJob:
    name: str
    command: tuple[str, ...]
    env_updates: tuple[tuple[str, str], ...]


@dataclass(slots=True)
class RunningJob:
    job: RealProbeJob
    process: subprocess.Popen[str]
    output_path: Path
    started_at: float
    last_status_at: float


def _split_csv(raw: str | None) -> list[str]:
    return [item.strip() for item in str(raw or "").split(",") if item.strip()]


def _normalize_targets(raw: str | None, *, default: tuple[str, ...], label: str) -> tuple[str, ...]:
    tokens = _split_csv(raw) or list(default)
    normalized: list[str] = []
    invalid: list[str] = []
    for token in tokens:
        lowered = token.strip().lower().replace("_", "-")
        lowered_items = list(default) if lowered == "all" else [TARGET_ALIASES.get(lowered, lowered)]
        for item in lowered_items:
            if item not in HOST_TARGETS:
                invalid.append(token)
                continue
            if item not in normalized:
                normalized.append(item)
    if invalid:
        raise SystemExit(f"unsupported {label}: {', '.join(invalid)}")
    return tuple(normalized)


def _normalize_suites(raw_values: list[str] | None) -> tuple[str, ...]:
    if not raw_values:
        return SUITES
    normalized: list[str] = []
    invalid: list[str] = []
    for raw in raw_values:
        for token in _split_csv(raw):
            lowered = token.lower()
            candidates = list(SUITES) if lowered == "all" else [lowered]
            for candidate in candidates:
                if candidate not in SUITES:
                    invalid.append(token)
                    continue
                if candidate not in normalized:
                    normalized.append(candidate)
    if invalid:
        raise SystemExit(f"unsupported --suite: {', '.join(invalid)}")
    return tuple(normalized)


def _extra_pytest_args(raw: list[str]) -> tuple[str, ...]:
    if raw and raw[0] == "--":
        raw = raw[1:]
    return tuple(raw)


def _pytest_command(test_path: str, extra_args: tuple[str, ...]) -> tuple[str, ...]:
    return (sys.executable, "-m", "pytest", "-q", "-ra", test_path, *extra_args)


def build_jobs(args: argparse.Namespace, *, base_env: dict[str, str] | None = None) -> list[RealProbeJob]:
    env = base_env or os.environ
    extra_args = _extra_pytest_args(args.pytest_args)
    suites = _normalize_suites(args.suite)
    jobs: list[RealProbeJob] = []

    if "real-agent" in suites:
        raw_targets = args.agent_targets or env.get("LOOPORA_REAL_AGENT_TARGETS")
        jobs.extend(
            [
                RealProbeJob(
                    name=f"real-agent:{target}",
                    command=_pytest_command("tests/probes/real_environment/test_real_agent_adapter_probe.py", extra_args),
                    env_updates=(
                        ("LOOPORA_ENABLE_REAL_AGENT_PROBE", "1"),
                        ("LOOPORA_REAL_AGENT_TARGETS", target),
                    ),
                )
                for target in _normalize_targets(raw_targets, default=HOST_TARGETS, label="agent targets")
            ]
        )

    if "real-cli" in suites:
        raw_targets = args.cli_targets or env.get("LOOPORA_REAL_CLI_TARGETS")
        jobs.extend(
            [
                RealProbeJob(
                    name=f"real-cli:{target}",
                    command=_pytest_command("tests/probes/real_environment/test_real_cli_probe.py", extra_args),
                    env_updates=(
                        ("LOOPORA_ENABLE_REAL_CLI_PROBE", "1"),
                        ("LOOPORA_REAL_CLI_TARGETS", target),
                    ),
                )
                for target in _normalize_targets(raw_targets, default=HOST_TARGETS, label="CLI targets")
            ]
        )

    if "release-web" in suites:
        jobs.append(
            RealProbeJob(
                name="release-web",
                command=_pytest_command("tests/probes/real_environment/test_release_web_probe.py", extra_args),
                env_updates=(("LOOPORA_ENABLE_RELEASE_WEB_PROBE", "1"),),
            )
        )

    return jobs


def _job_env(job: RealProbeJob) -> dict[str, str]:
    env = os.environ.copy()
    env.update(dict(job.env_updates))
    env["PYTHONPATH"] = f"{SRC_ROOT}{os.pathsep}{env.get('PYTHONPATH', '')}".rstrip(os.pathsep)
    env["LOOPORA_REAL_PROBE_PLAYBOOK_PATH"] = str(REAL_PROBE_PLAYBOOK)
    return env


def _format_command(command: tuple[str, ...]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def _print_dry_run(jobs: list[RealProbeJob]) -> None:
    _print_playbook_notice()
    for job in jobs:
        env_text = " ".join(f"{key}={shlex.quote(value)}" for key, value in job.env_updates)
        print(f"{job.name}\t{env_text}\t{_format_command(job.command)}")


def _print_playbook_notice() -> None:
    print(f"[real-probe] handbook: {REAL_PROBE_PLAYBOOK}")
    print("[real-probe] entry: read the handbook before choosing suites, waiting, or interpreting failures.")


def _status_interval_seconds(value: float) -> float:
    if value < 0:
        raise SystemExit("--status-interval-seconds must be non-negative")
    return value


def _report_waiting_jobs(running: list[RunningJob], *, now: float, status_interval: float) -> None:
    if status_interval <= 0:
        return
    for item in running:
        if now - item.last_status_at < status_interval:
            continue
        item.last_status_at = now
        duration = now - item.started_at
        print(f"[real-probe] waiting {item.job.name}: {duration:.1f}s log={item.output_path}", flush=True)


def _finish_job(item: RunningJob, *, keep_logs: bool) -> int:
    return_code = int(item.process.returncode or 0)
    duration = time.monotonic() - item.started_at
    output = item.output_path.read_text(encoding="utf-8", errors="replace")
    status = "passed" if return_code == 0 else f"failed exit={return_code}"
    print(f"\n[real-probe] {item.job.name} {status} in {duration:.1f}s")
    if output.strip():
        print(output.rstrip())
    if return_code != 0 or keep_logs:
        print(f"[real-probe] preserved log: {item.output_path}")
    else:
        item.output_path.unlink(missing_ok=True)
    return return_code


def run_jobs(jobs: list[RealProbeJob], *, max_parallel: int, status_interval: float = 30.0, keep_logs: bool = False) -> int:
    if max_parallel < 1:
        raise SystemExit("--max-parallel must be at least 1")
    _status_interval_seconds(status_interval)
    _print_playbook_notice()
    pending = list(jobs)
    running: list[RunningJob] = []
    exit_code = 0

    while pending or running:
        while pending and len(running) < max_parallel:
            job = pending.pop(0)
            with tempfile.NamedTemporaryFile(
                "w", prefix=f"loopora-real-probe-{job.name.replace(':', '-')}-", suffix=".log", encoding="utf-8", delete=False
            ) as output_file:
                output_path = Path(output_file.name)
                process = subprocess.Popen(
                    job.command,
                    cwd=REPO_ROOT,
                    env=_job_env(job),
                    stdout=output_file,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
            now = time.monotonic()
            running.append(RunningJob(job=job, process=process, output_path=output_path, started_at=now, last_status_at=now))
            print(f"[real-probe] started {job.name}: {_format_command(job.command)}", flush=True)
            print(f"[real-probe] log {job.name}: {output_path}", flush=True)

        completed_indexes = [index for index, item in enumerate(running) if item.process.poll() is not None]
        if not completed_indexes:
            _report_waiting_jobs(running, now=time.monotonic(), status_interval=status_interval)
            time.sleep(0.5)
            continue

        for index in reversed(completed_indexes):
            item = running.pop(index)
            return_code = _finish_job(item, keep_logs=keep_logs)
            if return_code != 0:
                exit_code = return_code if exit_code == 0 else exit_code

    return exit_code


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run independent Loopora real-environment probes in parallel. Read tests/probes/real_environment/README.md before using this runner."
    )
    parser.add_argument("--suite", action="append", help="Real probe suite to run: real-agent, real-cli, release-web, or all. Repeatable or comma-separated.")
    parser.add_argument("--agent-targets", help="Comma-separated real Agent targets. Defaults to LOOPORA_REAL_AGENT_TARGETS or codex,claude,opencode.")
    parser.add_argument("--cli-targets", help="Comma-separated real CLI targets. Defaults to LOOPORA_REAL_CLI_TARGETS or codex,claude,opencode.")
    parser.add_argument(
        "--max-parallel",
        type=int,
        default=int(os.environ.get("LOOPORA_REAL_PROBE_MAX_PARALLEL", "3")),
        help="Maximum concurrent pytest subprocesses.",
    )
    parser.add_argument(
        "--status-interval-seconds",
        type=float,
        default=float(os.environ.get("LOOPORA_REAL_PROBE_STATUS_INTERVAL_SECONDS", "30")),
        help="Heartbeat interval for running jobs. Use 0 to disable waiting heartbeats.",
    )
    parser.add_argument("--keep-logs", action="store_true", help="Preserve per-job runner logs even for passing jobs. Failing logs are always preserved.")
    parser.add_argument("--show-playbook", action="store_true", help="Print the real probe handbook and exit.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned subprocesses without running pytest.")
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER, help="Extra pytest arguments after --, for example: -- -s")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(list(argv or sys.argv[1:]))
    if args.show_playbook:
        print(REAL_PROBE_PLAYBOOK.read_text(encoding="utf-8"), end="")
        return 0
    jobs = build_jobs(args)
    if not jobs:
        print("[real-probe] no jobs selected")
        return 0
    if args.dry_run:
        _print_dry_run(jobs)
        return 0
    return run_jobs(jobs, max_parallel=min(args.max_parallel, len(jobs)), status_interval=args.status_interval_seconds, keep_logs=args.keep_logs)


if __name__ == "__main__":
    raise SystemExit(main())
