from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
REAL_PROBE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "real-provider-probe.yml"


def test_github_real_probe_workflow_uses_handbook_runner_for_all_release_suites() -> None:
    workflow = REAL_PROBE_WORKFLOW.read_text(encoding="utf-8")

    assert "name: Real Probe" in workflow
    assert "tests/probes/real_environment/run_real_probes.py" in workflow
    assert "suites:" in workflow
    assert "agent_targets:" in workflow
    assert "cli_targets:" in workflow
    assert "real-agent" in workflow
    assert "real-cli" in workflow
    assert "release-web" in workflow
    assert "LOOPORA_REAL_AGENT_COMMAND_TEMPLATE" in workflow
    assert "LOOPORA_REAL_CLAUDE_AGENT_COMMAND_TEMPLATE" in workflow
    assert "LOOPORA_REAL_OPENCODE_AGENT_COMMAND_TEMPLATE" in workflow
    assert "LOOPORA_REAL_PROBE_ALLOW_MODEL_OVERRIDE" in workflow
    assert "playwright install --with-deps chromium" in workflow


def test_github_real_probe_workflow_does_not_mix_experiments_into_release_probe() -> None:
    workflow = REAL_PROBE_WORKFLOW.read_text(encoding="utf-8")

    assert "tests/experiments/real_workflows" not in workflow
    assert "LOOPORA_ENABLE_REAL_CLI_PROBE: \"1\"" not in workflow
