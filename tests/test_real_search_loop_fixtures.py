from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures"


@dataclass(frozen=True)
class FixtureCase:
    slug: str
    fixture_dir: str
    proof_script: str
    proof_output: str


CASES = (
    FixtureCase(
        slug="build_first",
        fixture_dir="search_rollout_build_first",
        proof_script="tests/contract/help_center_shadow_proof.py",
        proof_output="tests/evidence/help_center_shadow_proof.json",
    ),
    FixtureCase(
        slug="inspect_first",
        fixture_dir="search_rollout_inspect_first",
        proof_script="tests/contract/high_value_query_regression_proof.py",
        proof_output="tests/evidence/high_value_query_regression_proof.json",
    ),
    FixtureCase(
        slug="triage_first",
        fixture_dir="search_rollout_triage_first",
        proof_script="tests/contract/triage_blocker_proof.py",
        proof_output="tests/evidence/triage_blocker_proof.json",
    ),
    FixtureCase(
        slug="repair_loop",
        fixture_dir="search_rollout_repair_loop",
        proof_script="tests/contract/reindex_window_proof.py",
        proof_output="tests/evidence/reindex_window_proof.json",
    ),
    FixtureCase(
        slug="benchmark_loop",
        fixture_dir="search_rollout_benchmark_loop",
        proof_script="tests/contract/relevance_benchmark_proof.py",
        proof_output="tests/evidence/relevance_benchmark_proof.json",
    ),
)


def test_search_rollout_real_cli_fixtures_emit_structured_proof(tmp_path: Path) -> None:
    for case in CASES:
        fixture = FIXTURE_ROOT / case.fixture_dir
        workspace = tmp_path / case.slug
        shutil.copytree(fixture, workspace)
        subprocess.run(
            [sys.executable, case.proof_script, case.proof_output],
            cwd=workspace,
            check=True,
            capture_output=True,
            text=True,
        )
        proof = json.loads((workspace / case.proof_output).read_text(encoding="utf-8"))
        assert proof["contract"]
        assert isinstance(proof["pass"], dict)
        assert proof["pass"]
        assert not all(bool(value) for value in proof["pass"].values())
