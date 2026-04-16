from __future__ import annotations

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from loopora.db import LooporaRepository
from loopora.executor import FakeCodexExecutor
from loopora.service import LooporaService
from loopora.settings import AppSettings


@pytest.fixture(autouse=True)
def isolate_loopora_home(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LOOPORA_HOME", str(tmp_path / "loopora-home"))


@pytest.fixture()
def sample_spec_text() -> str:
    return """# Goal

Ship the requested behavior.

# Checks

### Main flow works

- When: The user follows the main path.
- Expect: The primary experience completes successfully.
- Fail if: The main path breaks or becomes unclear.

### Edge case stays safe

- When: The workflow hits an edge case.
- Expect: The edge path stays safe and understandable.
- Fail if: The system crashes or leaves the user stuck.

# Constraints

- Keep changes focused.
"""


@pytest.fixture()
def sample_spec_file(tmp_path: Path, sample_spec_text: str) -> Path:
    path = tmp_path / "spec.md"
    path.write_text(sample_spec_text, encoding="utf-8")
    return path


@pytest.fixture()
def exploratory_spec_text() -> str:
    return """# Goal

Build a rough prototype that proves the main interaction is promising.

# Constraints

- Stay inside the existing workspace.
- Prefer small, visible improvements over broad rewrites.
"""


@pytest.fixture()
def exploratory_spec_file(tmp_path: Path, exploratory_spec_text: str) -> Path:
    path = tmp_path / "exploratory-spec.md"
    path.write_text(exploratory_spec_text, encoding="utf-8")
    return path


@pytest.fixture()
def sample_workdir(tmp_path: Path) -> Path:
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    (workdir / "progress.md").write_text("# Progress\n\nInitial state.\n", encoding="utf-8")
    return workdir


@pytest.fixture()
def service_factory(tmp_path: Path):
    def build(*, scenario: str = "success", role_delay: float = 0.0) -> LooporaService:
        repository = LooporaRepository(tmp_path / "app.db")
        settings = AppSettings(max_concurrent_runs=2, polling_interval_seconds=0.05, stop_grace_period_seconds=0.2)
        return LooporaService(
            repository=repository,
            settings=settings,
            executor_factory=lambda: FakeCodexExecutor(scenario=scenario, role_delay=role_delay),
        )

    return build
