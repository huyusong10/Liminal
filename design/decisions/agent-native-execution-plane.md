# Agent-Native Execution Plane

## Status

Accepted.

## Context

Loopora originally grew around a headless runner: Core registered a run, then a local worker called provider executors for each role step. That path is still useful for CI, automation, custom commands and legacy runs.

The current README makes the Coding Agent the recommended first-use path. In that path, the user is already inside Codex, Claude Code or OpenCode, and the host Agent should remain the execution subject. If `/loopora-loop` starts provider CLI subprocesses behind that host, Loopora becomes a nested Agent runner and loses the product boundary described by Human-Shaped Loop: Loopora should hold the Loop state, evidence and verdict while the current Agent advances the task under that governance structure.

## Decision

Loopora keeps two explicit execution planes:

| Plane | Execution subject | Stable entry |
| --- | --- | --- |
| `agent_native` | Current Coding Agent and its native subagent / task mechanism | `/loopora-gen`, `/loopora-loop`, `loopora agent <adapter> next/submit` |
| `headless` | Loopora worker invoking executor subprocesses | `loopora loops run`, background worker, CI and custom automation |

Agent-first `/loopora-loop` must create or reuse an `agent_native` run. It may register the run and return an execution capsule, but it must not spawn Codex, Claude Code or OpenCode CLI subprocesses to simulate role work.

The execution capsule is the handoff contract between Loopora Core and the host Agent. It must carry the full step prompt, target native role agent, frozen `judgment_contract`, required coverage summary, context refs, evidence rules and output schema. The host may choose the native subagent / task mechanism, but it must not reconstruct these fields from memory or from a shortened prompt.

The headless path remains a first-class automation path. It uses the executor subsystem, structured output contracts, timeout handling and legacy compatibility rules. It is not the default implementation of the Agent-first entry.

## Consequences

- Bundle `executor_kind` / `executor_mode` stay in assets for compatibility, Web alignment defaults and headless fallback, but they do not cause nested provider CLI execution in an Agent-first run.
- `agent_native` runs can be `awaiting_agent`; this is an active run lifecycle state, not a terminal result and not a hidden background worker.
- Host submissions must carry dispatch proof, and Core remains the evidence, handoff, coverage and GateKeeper verdict fact source.
- Agent-native execution preserves the same human judgment contract as headless execution: bundle judgment freezes into the run contract, then projects into every step capsule and terminal observation surface.
- Web can observe both execution planes, but user-facing status must distinguish an Agent-native run waiting for host work from a headless worker actively running.

## Validation

- `tests/checks/contracts/test_agent_adapters.py` covers `/loopora-gen -> /loopora-loop`, READY binding, imported-session handoff, `agent_native` state, dispatch proof, frozen `next_step.judgment_contract`, required coverage, no inline submit, control capsules and CLI behavior that does not spawn a nested worker.
- `tests/checks/contracts/test_runner_artifacts.py` covers the typed StepContextPacket contract that feeds the capsule.
- `tests/probes/real_environment/run_real_probes.py --suite real-agent` is the release-profile real-host check for managed Agent entries.
- `tests/probes/real_environment/run_real_probes.py --suite real-cli` keeps the explicit headless/provider CLI boundary covered separately.
