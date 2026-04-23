from __future__ import annotations

"""Scenario-driven heavy real-provider coverage for the five tutorial workflows.

These tests preserve their workspaces and Loopora run artifacts under
artifacts/real_search_loop_e2e so humans can inspect the final work later.
"""

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pytest

from loopora.db import LooporaRepository
from loopora.providers import executor_profile
from loopora.service import LooporaService
from loopora.settings import AppSettings

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures"
RESULTS_ROOT = ROOT / "artifacts" / "real_search_loop_e2e"
REAL_CLI_ENV = "LOOPORA_ENABLE_REAL_CLI_E2E"
REAL_CLI_TIMEOUT_ENV = "LOOPORA_REAL_CLI_TIMEOUT_SECONDS"
REAL_CLI_CODEX_MODEL_ENV = "LOOPORA_REAL_CLI_CODEX_MODEL"
REAL_SEARCH_RUN_ID_ENV = "LOOPORA_REAL_SEARCH_RUN_ID"
REAL_SEARCH_OUTPUT_ROOT_ENV = "LOOPORA_REAL_SEARCH_OUTPUT_ROOT"
DEFAULT_PROVIDER = "codex"
_CACHED_SUITE_OUTPUT_ROOT: Path | None = None
_CACHED_SUITE_OUTPUT_KEY: tuple[str, str, str] | None = None


@dataclass(frozen=True)
class SearchLoopCase:
    slug: str
    workflow_preset: str
    completion_mode: str
    max_iters: int
    fixture_dir: str
    proof_script: str
    proof_output: str
    expectation: str


CASES = (
    SearchLoopCase(
        slug="build_first",
        workflow_preset="build_first",
        completion_mode="gatekeeper",
        max_iters=3,
        fixture_dir="search_rollout_build_first",
        proof_script="tests/contract/help_center_shadow_proof.py",
        proof_output="tests/evidence/help_center_shadow_proof.json",
        expectation="The first help-center slice should be good enough for a real shadow-traffic decision.",
    ),
    SearchLoopCase(
        slug="inspect_first",
        workflow_preset="inspect_first",
        completion_mode="gatekeeper",
        max_iters=3,
        fixture_dir="search_rollout_inspect_first",
        proof_script="tests/contract/high_value_query_regression_proof.py",
        proof_output="tests/evidence/high_value_query_regression_proof.json",
        expectation="The loop should pin the first failing layer for the shadow regression and repair it without rewriting the whole stack.",
    ),
    SearchLoopCase(
        slug="triage_first",
        workflow_preset="triage_first",
        completion_mode="gatekeeper",
        max_iters=3,
        fixture_dir="search_rollout_triage_first",
        proof_script="tests/contract/triage_blocker_proof.py",
        proof_output="tests/evidence/triage_blocker_proof.json",
        expectation="The loop should narrow the rollout noise to the permission leak blocker and repair that blocker first.",
    ),
    SearchLoopCase(
        slug="repair_loop",
        workflow_preset="repair_loop",
        completion_mode="gatekeeper",
        max_iters=3,
        fixture_dir="search_rollout_repair_loop",
        proof_script="tests/contract/reindex_window_proof.py",
        proof_output="tests/evidence/reindex_window_proof.json",
        expectation="The loop should bring full reindexing back inside the maintenance window and leave behind a trustworthy repair review.",
    ),
    SearchLoopCase(
        slug="benchmark_loop",
        workflow_preset="benchmark_loop",
        completion_mode="gatekeeper",
        max_iters=4,
        fixture_dir="search_rollout_benchmark_loop",
        proof_script="tests/contract/relevance_benchmark_proof.py",
        proof_output="tests/evidence/relevance_benchmark_proof.json",
        expectation="The loop should use benchmark evidence to improve relevance and write down what the next optimization focus should be.",
    ),
)


def _provider_model(provider: str) -> str:
    if provider == "codex":
        override = str(os.environ.get(REAL_CLI_CODEX_MODEL_ENV, "") or "").strip()
        if override:
            return override
    return executor_profile(provider).default_model


def _require_real_provider(provider: str) -> None:
    if os.environ.get(REAL_CLI_ENV) != "1":
        pytest.skip(f"set {REAL_CLI_ENV}=1 to run the heavy real-provider workflow suite")
    cli_name = executor_profile(provider).cli_name
    if shutil.which(cli_name) is None:
        pytest.skip(f"{provider} CLI ({cli_name}) is unavailable in PATH")


def _timeout_seconds() -> float:
    return float(os.environ.get(REAL_CLI_TIMEOUT_ENV, "1800"))


def _suite_output_root() -> Path:
    global _CACHED_SUITE_OUTPUT_ROOT, _CACHED_SUITE_OUTPUT_KEY
    override = str(os.environ.get(REAL_SEARCH_OUTPUT_ROOT_ENV, "") or "").strip()
    run_id = str(os.environ.get(REAL_SEARCH_RUN_ID_ENV, "") or "").strip()
    cache_key = (str(RESULTS_ROOT.resolve()), override, run_id)
    if _CACHED_SUITE_OUTPUT_ROOT is not None and _CACHED_SUITE_OUTPUT_KEY == cache_key:
        return _CACHED_SUITE_OUTPUT_ROOT
    if override:
        root = Path(override).expanduser().resolve()
    else:
        if not run_id:
            run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        root = (RESULTS_ROOT / run_id).resolve()
    root.mkdir(parents=True, exist_ok=True)
    latest_pointer = RESULTS_ROOT / "LATEST.txt"
    latest_pointer.parent.mkdir(parents=True, exist_ok=True)
    latest_pointer.write_text(f"{root}\n", encoding="utf-8")
    _CACHED_SUITE_OUTPUT_ROOT = root
    _CACHED_SUITE_OUTPUT_KEY = cache_key
    return root


def _wait_for_terminal_run(service: LooporaService, run_id: str, *, timeout_seconds: float) -> dict:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        run = service.get_run(run_id)
        if run["status"] in {"succeeded", "failed", "stopped"}:
            return run
        time.sleep(2.0)
    raise AssertionError(f"timed out waiting for run {run_id} to finish")


def _read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _copy_fixture_workspace(case: SearchLoopCase) -> tuple[Path, Path]:
    suite_root = _suite_output_root()
    case_root = suite_root / case.slug
    workspace = case_root / "workspace"
    fixture = FIXTURE_ROOT / case.fixture_dir
    if workspace.exists():
        raise AssertionError(f"workspace already exists: {workspace}")
    case_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(fixture, workspace)
    return case_root, workspace


def _run_proof(workspace: Path, case: SearchLoopCase) -> dict:
    proof_rel = case.proof_output
    subprocess.run(
        [sys.executable, case.proof_script, proof_rel],
        cwd=workspace,
        check=True,
        capture_output=True,
        text=True,
    )
    proof_path = workspace / proof_rel
    return json.loads(proof_path.read_text(encoding="utf-8"))


def _write_case_review(
    *,
    case: SearchLoopCase,
    case_root: Path,
    workspace: Path,
    run: dict,
    proof: dict,
) -> None:
    run_dir = Path(run["runs_dir"])
    summary_path = run_dir / "summary.md"
    summary = summary_path.read_text(encoding="utf-8") if summary_path.exists() else "(missing summary.md)"
    failing = [name for name, passed in dict(proof.get("pass") or {}).items() if not passed]
    verdict = "matches expectation" if not failing and run["status"] == "succeeded" else "needs more inspection"
    review = "\n".join(
        [
            f"# {case.slug}",
            "",
            f"- Provider: {DEFAULT_PROVIDER}",
            f"- Workflow: {case.workflow_preset}",
            f"- Completion mode: {case.completion_mode}",
            f"- Run status: {run['status']}",
            f"- Verdict: {verdict}",
            f"- Expectation: {case.expectation}",
            f"- Workspace: {workspace}",
            f"- Run dir: {run_dir}",
            f"- Proof file: {workspace / case.proof_output}",
            "",
            "## Proof summary",
            "",
            str(proof.get("summary") or "-"),
            "",
            "## Failed proof checks",
            "",
            "- none" if not failing else "\n".join(f"- {name}" for name in failing),
            "",
            "## Loop summary excerpt",
            "",
            "```md",
            "\n".join(summary.splitlines()[:40]),
            "```",
            "",
        ]
    )
    (case_root / "review.md").write_text(review + "\n", encoding="utf-8")
    manifest_path = case_root.parent / "suite_manifest.json"
    current = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {"cases": {}}
    current.setdefault("cases", {})[case.slug] = {
        "workflow": case.workflow_preset,
        "completion_mode": case.completion_mode,
        "status": run["status"],
        "verdict": verdict,
        "workspace": str(workspace),
        "run_dir": str(run_dir),
        "proof_file": str(workspace / case.proof_output),
    }
    manifest_path.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")


def _start_real_case(case: SearchLoopCase) -> tuple[Path, Path, dict]:
    _require_real_provider(DEFAULT_PROVIDER)
    case_root, workspace = _copy_fixture_workspace(case)
    repository = LooporaRepository(case_root / "loopora.db")
    settings = AppSettings(
        max_concurrent_runs=1,
        polling_interval_seconds=0.2,
        stop_grace_period_seconds=1.0,
        role_idle_timeout_seconds=900.0,
    )
    service = LooporaService(repository=repository, settings=settings)
    loop = service.create_loop(
        name=f"Real search rollout · {case.slug}",
        spec_path=workspace / "spec.md",
        workdir=workspace,
        model=_provider_model(DEFAULT_PROVIDER),
        reasoning_effort=executor_profile(DEFAULT_PROVIDER).effort_default,
        max_iters=case.max_iters,
        max_role_retries=1,
        delta_threshold=0.005,
        trigger_window=2,
        regression_window=2,
        executor_kind=DEFAULT_PROVIDER,
        executor_mode="preset",
        role_models={},
        workflow={"preset": case.workflow_preset},
        completion_mode=case.completion_mode,
    )
    queued_run = service.rerun(loop["id"], background=True)
    run = _wait_for_terminal_run(service, queued_run["id"], timeout_seconds=_timeout_seconds())
    return case_root, workspace, run


def test_suite_output_root_is_stable_for_one_pytest_process(monkeypatch, tmp_path: Path) -> None:
    real_datetime = datetime

    class FakeDateTime:
        calls = 0

        @classmethod
        def now(cls, tz):
            cls.calls += 1
            second = 0 if cls.calls == 1 else 1
            return real_datetime(2026, 1, 1, 0, 0, second, tzinfo=timezone.utc)

    monkeypatch.setattr(sys.modules[__name__], "RESULTS_ROOT", tmp_path / "artifacts")
    monkeypatch.setattr(sys.modules[__name__], "datetime", FakeDateTime)
    monkeypatch.delenv(REAL_SEARCH_RUN_ID_ENV, raising=False)
    monkeypatch.delenv(REAL_SEARCH_OUTPUT_ROOT_ENV, raising=False)
    global _CACHED_SUITE_OUTPUT_ROOT, _CACHED_SUITE_OUTPUT_KEY
    _CACHED_SUITE_OUTPUT_ROOT = None
    _CACHED_SUITE_OUTPUT_KEY = None

    first = _suite_output_root()
    second = _suite_output_root()

    assert first == second
    assert first.name == "20260101T000000Z"


@pytest.mark.real_cli
@pytest.mark.parametrize("case", CASES, ids=lambda case: case.slug)
def test_real_search_rollout_examples_preserve_artifacts(case: SearchLoopCase) -> None:
    case_root, workspace, run = _start_real_case(case)
    run_dir = Path(run["runs_dir"])
    events = _read_jsonl(run_dir / "timeline" / "events.jsonl")
    proof = _run_proof(workspace, case)

    assert run["status"] == "succeeded", (run_dir / "summary.md").read_text(encoding="utf-8")
    assert any(event["event_type"] == "run_finished" for event in events)
    assert all(bool(value) for value in dict(proof.get("pass") or {}).values()), json.dumps(proof, indent=2)

    _write_case_review(case=case, case_root=case_root, workspace=workspace, run=run, proof=proof)
