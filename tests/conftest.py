from __future__ import annotations

from pathlib import Path

import pytest

from liminal.db import LiminalRepository
from liminal.executor import FakeCodexExecutor
from liminal.service import LiminalService
from liminal.settings import AppSettings


@pytest.fixture()
def sample_spec_text() -> str:
    return """# Goal

Ship the requested behavior.

# Cases

### Case 1: Main flow

- Scenario: The main path should work.

### Case 2: Edge case

- Scenario: The loop should handle an edge case.

# Expected Results

### Case 1: Main flow

- The primary output is correct.

### Case 2: Edge case

- The edge path stays safe.

# Acceptance

- Both cases should pass.

# Constraints

- Keep changes focused.
"""


@pytest.fixture()
def sample_spec_file(tmp_path: Path, sample_spec_text: str) -> Path:
    path = tmp_path / "spec.md"
    path.write_text(sample_spec_text, encoding="utf-8")
    return path


@pytest.fixture()
def sample_workdir(tmp_path: Path) -> Path:
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    (workdir / "progress.md").write_text("# Progress\n\nInitial state.\n", encoding="utf-8")
    return workdir


@pytest.fixture()
def service_factory(tmp_path: Path):
    def build(*, scenario: str = "success", role_delay: float = 0.0) -> LiminalService:
        repository = LiminalRepository(tmp_path / "app.db")
        settings = AppSettings(max_concurrent_runs=2, polling_interval_seconds=0.05, stop_grace_period_seconds=0.2)
        return LiminalService(
            repository=repository,
            settings=settings,
            executor_factory=lambda: FakeCodexExecutor(scenario=scenario, role_delay=role_delay),
        )

    return build
