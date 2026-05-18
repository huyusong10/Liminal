# Loopora Real Probe Handbook

This handbook is the entry point for real probes. Read it before running or interpreting any real-environment probe.

A real probe is not just executable pytest code. It is a release-profile workflow for real Agent hosts, real provider CLIs, real local services, and the Agent or human who has to interpret failures. The code asserts stable contracts; this handbook explains how to operate the probe and how to read the evidence it produces.

## 1. What Real Probes Prove

Real probes protect the real-environment boundary that deterministic contract and journey checks cannot prove:

| Suite | Proof target | Hard contract |
| --- | --- | --- |
| `real-agent` | Real Codex / Claude Code / OpenCode host entries | Conversation brief becomes a host-created candidate bundle; `/loopora-plan` happens before `/loopora-run`; runtime activity observes the linked run; Agent-native role claim/submit happens; evidence-backed task verdict passes; nested host CLI sentinels stay silent. |
| `real-cli` | Real provider CLI execution | Provider process launches, structured outputs are parsed, artifacts persist, and resume command shape remains valid. |
| `release-web` | Real `loopora serve` process and browser path | Web Tools can observe adapter status and drive install/update/uninstall/error states against a real local service. |

Use larger realistic workflows only as manual scenarios or explicitly marked experiments. They should not become the default release-profile blocker unless the feature being released is about that workflow.

The old Agent-first adapter scenario is now split by evidence type: this handbook and the real-agent probe cover stable hard invariants, while `tests/reviews/cases/agent-native-behavior.md` reviews recorded phase reports for fuzzy Agent-native behavior such as whether the host experience reads like a managed Loop instead of an inline shortcut.

Design-to-evidence traceability:

| Design clause | Suite | Hard assertion | Evidence artifact |
| --- | --- | --- | --- |
| Agent entry must be handbook-first and managed-entry driven | `real-agent` | Candidate file is host-created, and binding records managed `/loopora-plan` before `/loopora-run` | `.loopora/real-probes/real-agent-phase-report.json`, adapter binding JSON, alignment validation JSON |
| Agent-native role work must not be faked inline or by nested host CLI | `real-agent` | Builder and GateKeeper are claimed/submitted, dispatch is non-inline, actual agent matches target agent, and sentinel CLI log stays absent | Run events, `agent_native/state.json`, role outputs, sentinel log path |
| GateKeeper pass must be backed by upstream evidence | `real-agent` | Builder leaves supporting proof, GateKeeper cites exact known evidence, run succeeds with task verdict `passed` | Evidence ledger, coverage projection, task verdict projection, role outputs |
| Provider real probe only proves the executor boundary | `real-cli` | Real CLI launches, structured outputs persist, second round has resume session, and provider resume argv shape is valid | `.loopora/real-probes/real-cli-phase-report.json`, run events, role request JSONL, run contract |
| Web real probe proves real service/browser adapter management | `release-web` | `not_installed`, `installed`, `needs_update`, and `error` states are observable without overwriting user-owned files | `.loopora/real-probes/release-web-phase-report.json`, browser status attributes, adapter files |

## 2. How To Run

Prefer the real probe runner over direct pytest invocation because the runner encodes the parallelism, handbook notice, waiting behavior, and log preservation policy:

```bash
python tests/probes/real_environment/run_real_probes.py --show-playbook
python tests/probes/real_environment/run_real_probes.py --suite real-agent --agent-targets codex,claude,opencode --max-parallel 3
python tests/probes/real_environment/run_real_probes.py --suite real-cli --cli-targets codex,claude,opencode --max-parallel 3
python tests/probes/real_environment/run_real_probes.py --suite all --max-parallel 3
```

Agent-host command templates are required for `real-agent`:

```bash
export LOOPORA_REAL_AGENT_COMMAND_TEMPLATE='codex exec --cd {workdir} --skip-git-repo-check "$(cat {prompt_file})"'
export LOOPORA_REAL_CLAUDE_AGENT_COMMAND_TEMPLATE='claude -p --dangerously-skip-permissions "$(cat {prompt_file})"'
export LOOPORA_REAL_OPENCODE_AGENT_COMMAND_TEMPLATE='opencode run --dir {workdir} --dangerously-skip-permissions "$(cat {prompt_file})"'
```

Provider defaults belong to the real host CLI configuration, not the release probe. The ordinary release path should not pass `--model`, `--effort`, `--variant`, or Codex `model_reasoning_effort` for Claude Code, OpenCode, or Codex.

Default external configuration delegation is a hard release-path assertion:

- `real-agent` rejects command templates containing `--model`, `--effort`, `--variant`, or `model_reasoning_effort` unless an explicit override validation is enabled.
- `real-cli` leaves the bundle model and reasoning effort blank unless an explicit provider model env var is set.
- To intentionally run an external configuration override, set `LOOPORA_REAL_PROBE_ALLOW_MODEL_OVERRIDE=1` and make the override explicit in the command template or provider model env var. Do not use this exemption for an ordinary release check.

## 3. Parallelism

Codex, Claude Code, and OpenCode targets are independent. Run them in parallel whenever the local machine and provider quotas can handle it.

The runner creates one pytest subprocess per selected target. Each job gets its own target env var value, temporary workspace, Loopora home, Web port, binding state, and log file. Parallelism is a scheduling optimization only; it must not weaken the hard assertions inside a target.

## 4. Waiting Behavior

Do not treat quiet stdout as proof of progress or failure.

The runner prints a heartbeat for long-running jobs. Each heartbeat includes elapsed time and the live log path. Real probe harnesses also write compact phase reports inside the temporary workdir or Loopora state dir; on assertion failure, pytest includes the relevant path and a compact summary when available.

While a job is still running, inspect evidence rather than waiting blindly:

1. Process command line: confirm the intended host and model are actually running.
2. Phase report: inspect `.loopora/real-probes/*-phase-report.json` for the latest process, model, artifact, and state projection.
3. Candidate bundle path: confirm the host created `.loopora/agent_inbox/<adapter>/conversation-candidate.yml`.
4. Alignment validation: inspect `.loopora/alignment_sessions/*/artifacts/validation.json`.
5. Binding: inspect `.loopora/agent_adapters/<adapter>/bindings/*.json` for `gen` before `loop`, linked bundle, linked loop, and linked run.
6. Runtime activity: confirm the linked run appears while non-terminal.
7. Run events: tail `.loopora/runs/<run-id>/events.jsonl`.
8. Agent-native state: inspect `.loopora/runs/<run-id>/agent_native/state.json`.
9. Evidence: inspect `evidence/ledger.jsonl`, `evidence/coverage.json`, and `evidence/task_verdict.json`.
10. Role outputs: inspect `iterations/iter_*/steps/*/output.raw.json` and `output.normalized.json`.
11. Sentinel log: confirm no nested `codex`, `claude`, or `opencode` command was invoked from inside the run.

Soft waiting signal: a phase takes longer than expected but new artifacts or events are still appearing. Keep observing.

Hard waiting signal: the job reaches its timeout, the host exits non-zero, the linked run fails terminally, or a required contract is missing. Then use the preserved log and artifacts to diagnose.

## 5. What Is A Test Assertion

Only stable facts should fail a real probe:

- The host must create the candidate bundle from the conversation requirements; the harness must not prewrite it or embed a complete candidate YAML for the host to copy.
- Managed entry provenance must show `/loopora-plan` before `/loopora-run`.
- Runtime activity must observe the linked run before terminal completion.
- Builder and GateKeeper must both have context, role request, claim, and submit events.
- `loopora_host_dispatch.inline` must be `false`, and `actual_agent` must match `target_agent`.
- Builder must leave supporting evidence such as a proof file or measured evidence; a plain handoff self-report must not support GateKeeper pass.
- GateKeeper must cite exact known evidence IDs.
- Run lifecycle must finish `succeeded`, and task verdict must be `passed`.
- Nested host CLI sentinels must remain silent.
- Default host model and reasoning configuration must be delegated to the real host unless `LOOPORA_REAL_PROBE_ALLOW_MODEL_OVERRIDE=1` is set for an intentional override run.

Do not make these fuzzy observations into hard assertions unless they become stable product contracts:

- How many `/loopora-plan` attempts happened before READY.
- Whether host stdout is quiet for a while.
- Provider dashboard call counts.
- Exact model prose, timing, or validation repair wording.
- Temporary `weak` or `partial` coverage before terminal GateKeeper submission.

## 6. Failure Triage Order

Read failure artifacts in this order:

1. Runner summary and preserved log path.
2. Pytest assertion failure and the compact phase report printed below it.
3. Full `.loopora/real-probes/real-agent-phase-report.json`.
4. Binding invocation order and linked run ID.
5. Validation files for candidate bundle failures.
6. Run event tail for the last stable phase.
7. GateKeeper raw and normalized output.
8. Coverage and task verdict projections.
9. Sentinel log and process command line.

Common diagnoses:

| Symptom | Likely cause | First place to inspect |
| --- | --- | --- |
| No candidate bundle | Host did not follow the conversation-to-bundle step | Host log and prompt file |
| READY never appears | Candidate bundle semantic lint or schema failure | Alignment validation JSON |
| Run exists but no role submit | Host did not continue the Agent-native loop | Agent-native state and run events |
| GateKeeper pass is rewritten to block | Cited evidence is unknown or non-supporting | Normalized GateKeeper output and evidence coverage |
| Run succeeded but task verdict is not passed | Required coverage is missing or blocked | `evidence/task_verdict.json` and `coverage.json` |
| Provider dashboard looks idle | The host may have skipped the real model or used a different route | Process command line, host log, command template |

## 7. Timeout Defaults

Use generous real-environment timeouts. A single Agent-host target may need several minutes because the host must read entry files, create a candidate, validate it, start a service, and run two role submissions.

Recommended defaults:

- Real Agent target timeout: `LOOPORA_REAL_AGENT_TIMEOUT_SECONDS=900`.
- Real CLI target timeout: `LOOPORA_REAL_CLI_TIMEOUT_SECONDS=600`.
- Runner heartbeat: `LOOPORA_REAL_PROBE_STATUS_INTERVAL_SECONDS=30`.
- Parallel target count: up to `3` for Codex / Claude Code / OpenCode when quotas allow it.

These are operating defaults, not task success criteria. The hard success criteria are the artifacts, events, evidence, and terminal task verdict.
