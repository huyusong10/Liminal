from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import signal
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

from loopora.branding import state_dir_for_workdir
from loopora.bundles import bundle_to_yaml
from loopora.db import LooporaRepository
from loopora.service import LooporaService
from loopora.service_types import TERMINAL_RUN_STATUSES
from loopora.settings import AppSettings
from loopora.workflows import builtin_prompt_markdown


pytestmark = pytest.mark.real_agent

ENABLE_ENV = "LOOPORA_ENABLE_REAL_AGENT_E2E"
COMMAND_TEMPLATE_ENV = "LOOPORA_REAL_AGENT_COMMAND_TEMPLATE"
CLAUDE_COMMAND_TEMPLATE_ENV = "LOOPORA_REAL_CLAUDE_AGENT_COMMAND_TEMPLATE"
OPENCODE_COMMAND_TEMPLATE_ENV = "LOOPORA_REAL_OPENCODE_AGENT_COMMAND_TEMPLATE"
TARGETS_ENV = "LOOPORA_REAL_AGENT_TARGETS"
TIMEOUT_ENV = "LOOPORA_REAL_AGENT_TIMEOUT_SECONDS"
AGENT_TARGETS = ("codex", "claude", "opencode")
REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"


def _selected_real_agent_targets() -> set[str]:
    raw = str(os.environ.get(TARGETS_ENV, "") or "").strip()
    if not raw:
        return set(AGENT_TARGETS)
    selected = {item.strip().lower().replace("_", "-") for item in raw.split(",") if item.strip()}
    aliases = {"claude-code": "claude", "claudecode": "claude", "open-code": "opencode"}
    normalized = {aliases.get(item, item) for item in selected}
    invalid = sorted(normalized - set(AGENT_TARGETS))
    if invalid:
        raise AssertionError(f"unsupported {TARGETS_ENV} entries: {', '.join(invalid)}")
    return normalized


def _template_env_for_adapter(adapter: str) -> str:
    return {
        "claude": CLAUDE_COMMAND_TEMPLATE_ENV,
        "opencode": OPENCODE_COMMAND_TEMPLATE_ENV,
    }.get(adapter, COMMAND_TEMPLATE_ENV)


def _require_real_agent_template(adapter: str) -> str:
    if os.environ.get(ENABLE_ENV) != "1":
        pytest.skip(f"set {ENABLE_ENV}=1 to run the real Agent adapter release gate")
    if adapter not in _selected_real_agent_targets():
        pytest.skip(f"{adapter} is not enabled by {TARGETS_ENV}")
    env_name = _template_env_for_adapter(adapter)
    template = os.environ.get(env_name, "").strip()
    if not template:
        pytest.skip(
            f"set {env_name} to a shell command template for the real {adapter} Agent host; "
            "available placeholders: {workdir}, {prompt_file}, {bundle_file}"
        )
    return template


def _write_nested_agent_sentinels(tmp_path: Path) -> tuple[Path, Path]:
    sentinel_dir = tmp_path / "nested-agent-sentinels"
    sentinel_dir.mkdir()
    log_path = tmp_path / "nested-agent-sentinel.log"
    for name in AGENT_TARGETS:
        script = sentinel_dir / name
        script.write_text(
            "#!/bin/sh\n"
            f'echo "$0 $@" >> {shlex.quote(str(log_path))}\n'
            "exit 86\n",
            encoding="utf-8",
        )
        script.chmod(0o755)
    return sentinel_dir, log_path


def _write_loopora_wrapper(tmp_path: Path, *, sentinel_dir: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    wrapper = bin_dir / "loopora"
    wrapper.write_text(
        "#!/bin/sh\n"
        f'PATH="{sentinel_dir}:$PATH" PYTHONPATH="{SRC_ROOT}${{PYTHONPATH:+:$PYTHONPATH}}" exec "{sys.executable}" -m loopora "$@"\n',
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    return bin_dir


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_agent_web(base_url: str, *, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{base_url}/api/runtime/activity", timeout=1) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if {"running_count", "queued_count", "runs"} <= set(payload):
                return
        except Exception as exc:  # noqa: BLE001 - readiness probe should tolerate transient startup failures.
            last_error = str(exc)
        time.sleep(0.2)
    raise AssertionError(f"Timed out waiting for Agent-started Loopora Web at {base_url}: {last_error}")


def _terminate_pid_file(pid_file: Path) -> None:
    if not pid_file.exists():
        return
    raw_pid = pid_file.read_text(encoding="utf-8").strip()
    if not raw_pid:
        return
    try:
        pid = int(raw_pid)
    except ValueError:
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.1)
    os.kill(pid, signal.SIGKILL)


def _binding_payloads(adapter: str, workdir: Path) -> list[dict]:
    bindings_dir = state_dir_for_workdir(workdir) / "agent_adapters" / adapter / "bindings"
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(bindings_dir.glob("*.json"))]


def _wait_for_run_binding(adapter: str, workdir: Path, *, timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    last_payloads: list[dict] = []
    while time.monotonic() < deadline:
        last_payloads = _binding_payloads(adapter, workdir)
        for payload in last_payloads:
            if str(payload.get("linked_run_id") or "").strip():
                return payload
        time.sleep(0.5)
    raise AssertionError(f"Timed out waiting for a {adapter} adapter run binding; last payloads={last_payloads!r}")


def _loopora_service(loopora_home: Path) -> LooporaService:
    return LooporaService(
        repository=LooporaRepository(loopora_home / "app.db"),
        settings=AppSettings(max_concurrent_runs=1, polling_interval_seconds=0.1, stop_grace_period_seconds=0.5),
    )


def _wait_for_terminal_run(loopora_home: Path, run_id: str, *, timeout: float) -> dict:
    service = _loopora_service(loopora_home)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = service.get_run(run_id)
        if run["status"] in TERMINAL_RUN_STATUSES:
            return run
        time.sleep(0.5)
    run = service.get_run(run_id)
    if run["status"] in {"queued", "running", "awaiting_agent"}:
        service.stop_run(run_id)
    raise AssertionError(f"Timed out waiting for Agent-started run {run_id} to finish; last status={run['status']}")


def _write_custom_executor(workdir: Path) -> Path:
    script = workdir / "loopora_agent_release_executor.py"
    script.write_text(
        """from __future__ import annotations

import json
from pathlib import Path
import sys

role = sys.argv[1]
output_path = Path(sys.argv[2])
_prompt = sys.argv[3]
if role == "gatekeeper":
    payload = {
        "passed": True,
        "decision_summary": "Agent adapter release gate passed with supporting upstream Builder evidence.",
        "feedback_to_builder": "",
        "blocking_issues": [],
        "metrics": [{"name": "quality_score", "value": 1.0, "threshold": 0.9, "passed": True}],
        "failed_check_ids": [],
        "priority_failures": [],
        "composite_score": 1.0,
        "evidence_refs": ["ev_000_00_builder_step"],
        "evidence_claims": ["The upstream Builder evidence confirms the managed run binding and structured result."],
        "residual_risks": [],
        "coverage_results": [],
    }
else:
    payload = {
        "attempted": "Verified the Loopora Agent adapter can start a managed run.",
        "abandoned": "No product changes were needed for this release gate.",
        "assumption": "The release gate only needs a deterministic terminal run after /loopora-loop.",
        "summary": "Custom executor wrote a structured Builder result for the Agent adapter release gate.",
        "changed_files": [],
    }
output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\\n", encoding="utf-8")
print(json.dumps({"type": "stdout", "message": f"loopora-agent-release-executor complete: {role}"}))
""",
        encoding="utf-8",
    )
    return script


def _agent_label(adapter: str) -> str:
    return {
        "codex": "Codex",
        "claude": "Claude Code",
        "opencode": "OpenCode",
    }.get(adapter, adapter)


def _entry_source(adapter: str) -> str:
    if adapter == "opencode":
        return "opencode_project_command"
    return f"{adapter}_project_skill"


def _entry_file_hint(adapter: str) -> str:
    if adapter == "claude":
        return ".claude/skills/loopora-gen/SKILL.md and .claude/skills/loopora-loop/SKILL.md"
    if adapter == "opencode":
        return ".opencode/commands/loopora-gen.md and .opencode/commands/loopora-loop.md"
    return ".agents/skills/loopora-gen/SKILL.md and .agents/skills/loopora-loop/SKILL.md"


def _assert_managed_gen_before_loop(adapter: str, entry_invocations: list[dict]) -> None:
    expected_source = _entry_source(adapter)
    normalized = [(item.get("action"), item.get("entry_source")) for item in entry_invocations if isinstance(item, dict)]
    managed_gen_indexes = [index for index, item in enumerate(normalized) if item == ("gen", expected_source)]
    assert managed_gen_indexes, normalized
    assert any(item == ("loop", expected_source) for item in normalized[managed_gen_indexes[0] + 1 :]), normalized
    assert normalized[-1] == ("loop", expected_source)


def _agent_release_bundle_yaml(workdir: Path, executor_script: Path, *, adapter: str) -> str:
    def role_execution(role: str) -> dict:
        return {
            "executor_kind": "custom",
            "executor_mode": "command",
            "command_cli": sys.executable,
            "command_args_text": f"{executor_script}\n{role}\n{{output_path}}\n{{prompt}}",
            "model": "",
            "reasoning_effort": "",
        }

    loop_execution = {
        "executor_kind": "custom",
        "executor_mode": "command",
        "command_cli": sys.executable,
        "command_args_text": f"{executor_script}\nbuilder\n{{output_path}}\n{{prompt}}",
        "model": "",
        "reasoning_effort": "",
    }
    bundle = {
        "version": 1,
        "metadata": {
            "name": "Agent Adapter Release Gate",
            "description": f"Deterministic bundle used by the real {_agent_label(adapter)} host L3 gate.",
        },
        "collaboration_summary": (
            f"Use deterministic proof evidence to show that {_agent_label(adapter)} can drive Loopora's installed Agent entry and that /loopora-loop "
            "starts a Loopora-managed run without depending on another long-running model task; GateKeeper makes the final judgment from upstream Builder evidence."
        ),
        "loop": {
            "name": "Agent Adapter Release Gate",
            "workdir": str(workdir.resolve()),
            "completion_mode": "gatekeeper",
            **loop_execution,
            "model": "",
            "reasoning_effort": "",
            "iteration_interval_seconds": 0,
            "max_iters": 1,
            "max_role_retries": 1,
            "delta_threshold": 0.005,
            "trigger_window": 2,
            "regression_window": 2,
        },
        "spec": {
            "markdown": """# Task

Prepare a verifiable release gate showing that a user can invoke Loopora from the Coding Agent and receive a managed run URL.

# Done When

- The Agent entry creates a managed run binding with a run URL.
- The Builder step writes a structured result that GateKeeper can inspect.

# Success Surface

- The release gate proves the Coding Agent can call Loopora Agent entry points, observe a Loopora-managed run URL, and submit Agent-native step results.

# Guardrails

- Do not edit user-owned Agent host or Loopora configuration.

# Fake Done

- Reporting a URL without creating a managed run binding.

# Evidence Preferences

- Prefer deterministic upstream evidence generated inside the Loopora run.

# Residual Risk

This gate does not prove product task quality; it only proves the Agent adapter entry boundary. The outer L3 harness, not this Loop contract, asserts the final run status after GateKeeper submission.
""",
        },
        "role_definitions": [
            {
                "key": "builder",
                "name": "Agent Release Builder",
                "description": "Runs a deterministic custom command.",
                "archetype": "builder",
                "prompt_ref": "builder.md",
                "prompt_markdown": builtin_prompt_markdown("builder.md"),
                "posture_notes": "This role exists only to make the Agent adapter L3 run deterministic and quick.",
                **role_execution("builder"),
            },
            {
                "key": "gatekeeper",
                "name": "Agent Release GateKeeper",
                "description": "Closes the deterministic Agent adapter gate.",
                "archetype": "gatekeeper",
                "prompt_ref": "gatekeeper.md",
                "prompt_markdown": builtin_prompt_markdown("gatekeeper.md"),
                "posture_notes": "Pass only when upstream Builder evidence is present.",
                **role_execution("gatekeeper"),
            },
        ],
        "workflow": {
            "version": 1,
            "preset": "custom",
            "collaboration_intent": "Use deterministic evidence, handoff, and GateKeeper closure after the real Agent host invokes /loopora-loop.",
            "roles": [
                {"id": "builder", "role_definition_key": "builder"},
                {"id": "gatekeeper", "role_definition_key": "gatekeeper"},
            ],
            "steps": [
                {"id": "builder_step", "role_id": "builder"},
                {
                    "id": "gatekeeper_step",
                    "role_id": "gatekeeper",
                    "on_pass": "finish_run",
                    "inputs": {"handoffs_from": ["builder_step"], "evidence_query": {"archetypes": ["builder"], "limit": 4}},
                },
            ],
        },
    }
    return bundle_to_yaml(bundle)


@pytest.mark.parametrize("adapter", AGENT_TARGETS)
def test_real_agent_host_can_drive_loopora_gen_then_loop(adapter: str, tmp_path: Path, monkeypatch) -> None:
    template = _require_real_agent_template(adapter)
    timeout = float(os.environ.get(TIMEOUT_ENV, "180"))
    loopora_home = tmp_path / "loopora-home"
    monkeypatch.setenv("LOOPORA_HOME", str(loopora_home))
    sentinel_dir, sentinel_log = _write_nested_agent_sentinels(tmp_path)
    bin_dir = _write_loopora_wrapper(tmp_path, sentinel_dir=sentinel_dir)
    env = os.environ.copy()
    env["LOOPORA_HOME"] = str(loopora_home)
    env["PYTHONPATH"] = f"{SRC_ROOT}{os.pathsep}{env.get('PYTHONPATH', '')}".rstrip(os.pathsep)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    agent_web_port = _free_port()
    agent_web_pid_file = tmp_path / "agent-web.pid"
    agent_web_url = f"http://127.0.0.1:{agent_web_port}"
    env["LOOPORA_AGENT_WEB_PORT"] = str(agent_web_port)
    env["LOOPORA_AGENT_WEB_PID_FILE"] = str(agent_web_pid_file)

    workdir = tmp_path / f"real-{adapter}-agent-workdir"
    workdir.mkdir()
    (workdir / "README.md").write_text("# Real Agent adapter release fixture\n", encoding="utf-8")
    executor_script = _write_custom_executor(workdir)
    bundle_file = workdir / "loopora-agent-candidate.yml"
    bundle_file.write_text(_agent_release_bundle_yaml(workdir, executor_script, adapter=adapter), encoding="utf-8")
    prompt_file = workdir / "loopora-agent-release-prompt.md"
    prompt_file.write_text(
        f"""# Loopora Agent Adapter Release Gate

Use the Loopora {_agent_label(adapter)} project entry installed in this workdir. If this non-interactive host does not expose native slash commands directly, inspect the installed project entry files and follow their instructions.

Current task: prove the installed Loopora Agent entry can generate a READY candidate and then start a managed run.

A deterministic candidate bundle YAML is available at `{bundle_file}`. Use that file as the candidate bundle for `/loopora-gen`; do not author a different bundle.

Before invoking anything, read these installed project entry files: `{_entry_file_hint(adapter)}`. Use them as the only source for shell command syntax, and preserve their provenance markers exactly.

Required order:

1. Invoke `/loopora-gen` or the installed `loopora-gen` project entry semantics.
2. Only after the candidate is READY, invoke `/loopora-loop` or the installed `loopora-loop` project entry semantics.
3. Continue the installed Agent-native loop path until Loopora returns `complete: true`. For each returned step capsule, use the host's native role/subagent mechanism named by `role_dispatch.target_agent`, write one wrapper JSON result with `loopora_host_dispatch` and `result`, follow any `evidence_rules`, `evidence_ref_contract`, and `role_dispatch`, and submit it as instructed by the installed entry.
4. Return a short summary with the candidate URL, run URL, and terminal run status.

The Loopora bundle intentionally does not make "the run is terminal" a task-level Done When item; this pytest harness checks terminal status after the host finishes the Agent-native loop.
For every result file, use the installed entry's wrapper format: top-level `loopora_host_dispatch` plus top-level `result`. The `result` object must use the exact top-level keys required by the step capsule's `output_schema`. For GateKeeper, write `passed`, `decision_summary`, `metrics`, `metric_scores`, `evidence_refs`, `evidence_claims`, and the other schema fields inside `result`; do not use a `verdict` or `task_verdict` envelope. In `loopora_host_dispatch`, set both `target_agent` and `actual_agent` to the exact `role_dispatch.target_agent`, set `dispatch_mode` to `host_subagent`, `host_task`, or `host_agent`, and set `inline` to false. Every `evidence_refs` list, including inside `coverage_results`, must contain only exact strings copied from `known_evidence_ids`. If `known_evidence_ids` contains only `ev_000_00_builder_step`, use only `ev_000_00_builder_step`; do not invent suffixes such as `_binding`, `_output`, `_preference`, or `_fake_done_risk`. Artifact labels and file names belong in evidence_claims or notes.

Do not edit user-owned config files.
Do not invent a direct Loopora CLI command from this prompt; follow the installed project entry instructions when a shell command is needed.
Do not invoke codex, claude, or opencode from inside this Agent session; this release gate must prove the host Agent itself performs the role work.
""",
        encoding="utf-8",
    )

    try:
        install = subprocess.run(
            ["loopora", "init", adapter, "--workdir", str(workdir)],
            cwd=workdir,
            env=env,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        assert install.returncode == 0, install.stderr or install.stdout

        command = template.format(
            workdir=shlex.quote(str(workdir)),
            prompt_file=shlex.quote(str(prompt_file)),
            bundle_file=shlex.quote(str(bundle_file)),
        )
        completed = subprocess.run(command, cwd=workdir, env=env, shell=True, text=True, capture_output=True, timeout=timeout, check=False)
        assert completed.returncode == 0, completed.stderr or completed.stdout
        _wait_for_agent_web(agent_web_url, timeout=10)
        binding = _wait_for_run_binding(adapter, workdir, timeout=30)
        assert binding["adapter"] == adapter
        assert binding["linked_run_id"]
        assert str(binding["run_path"]).startswith("/runs/")
        entry_invocations = binding.get("entry_invocations")
        assert isinstance(entry_invocations, list)
        _assert_managed_gen_before_loop(adapter, entry_invocations)
        final_run = _wait_for_terminal_run(loopora_home, str(binding["linked_run_id"]), timeout=30)
        assert final_run["status"] == "succeeded"
        assert not sentinel_log.exists(), sentinel_log.read_text(encoding="utf-8") if sentinel_log.exists() else ""
    finally:
        _terminate_pid_file(agent_web_pid_file)
