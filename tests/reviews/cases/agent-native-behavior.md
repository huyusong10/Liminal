---
id: agent-native-behavior
title: Agent Native Behavior Review
targets: []
---

Review a real or recorded Agent-host run for whether the host behaves like a Loopora-managed Agent path rather than an inline shortcut.

Look for:

- The host creating the candidate bundle from the conversation brief instead of relying on a prewritten candidate.
- `/loopora-gen` preceding `/loopora-loop` through the managed entry surface, with provenance visible in binding evidence.
- Role work being claimed and submitted through the host-native role/subagent mechanism instead of silently completed inline.
- Builder evidence being concrete enough for GateKeeper to cite, and GateKeeper citing known evidence rather than a self-report.
- The host avoiding nested calls to its own CLI from inside the Loopora run.
- Failure triage evidence being understandable without watching stdout live.

Hard invariants that are stable and machine-checkable belong in real probes. This case is for the surrounding judgment: whether the run still reads like the intended Agent-native product experience.
