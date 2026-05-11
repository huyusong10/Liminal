# Loopora Test Map

The test suite protects behavior contracts, not implementation shape.

## Layers

| Layer | Scope | Preferred anchors |
| --- | --- | --- |
| L1 Contract / API | Spec compilation, bundle lifecycle, workflow normalization, run evidence, GateKeeper completion, adapter ownership | Public return values, stable IDs, canonical artifacts, status semantics, status codes, structured error semantics |
| L2 Browser / Local Integration | User journeys that require a real browser, client-side state, or local in-process service behavior | Accessible controls, visible outcomes, persisted state, files written under a real temporary workdir |
| L3 Real Environment | Opt-in release gates against real provider CLIs, real Agent host entry, or real `loopora serve` process | Provider/host capability, degradation visibility, preserved artifacts, observable user journeys |
| Scenarios | Manual exploratory journeys for a few core flows | Stable user goals, evidence boundaries, cross-entry consistency |

## Required Gates

| Gate | When | Command shape |
| --- | --- | --- |
| L1 | Every code change before commit | `uv run ruff check .` and focused `uv run pytest ...` for touched contract/API files |
| L2 | Every feature that changes a user journey, Web behavior, local files, or cross-entry state | Focused browser/local integration tests, then the default `uv run pytest -q` when feasible |
| L3 | Before release or before merging a feature that depends on real external hosts | Opt-in real-environment markers such as `real_cli`, `real_agent`, and `release_web` with required environment variables |

L3 tests may skip on ordinary developer machines, but their skip reason must name the missing environment switch or command template. Passing L1/L2 only means the feature is structurally correct in Loopora; L3 is the final proof that the real host/browser path still works.

Current L3 switches:

- Real provider CLI loop: set `LOOPORA_ENABLE_REAL_CLI_E2E=1` and, when needed, provider/model target variables used by `tests/test_real_cli_integration.py`.
- Real Coding Agent adapter: set `LOOPORA_ENABLE_REAL_AGENT_E2E=1`. For Codex, set `LOOPORA_REAL_AGENT_COMMAND_TEMPLATE`; for Claude Code, set `LOOPORA_REAL_CLAUDE_AGENT_COMMAND_TEMPLATE`; for OpenCode, set `LOOPORA_REAL_OPENCODE_AGENT_COMMAND_TEMPLATE`. All templates support `{workdir}`, `{prompt_file}`, `{bundle_file}`. Use `LOOPORA_REAL_AGENT_TARGETS=codex,claude,opencode` to choose hosts.
- Real Web process: set `LOOPORA_ENABLE_RELEASE_WEB_E2E=1` to start a real `loopora serve` process and run the browser Tools adapter journey.
- Heavy real workflow experiments: set `LOOPORA_ENABLE_REAL_WORKFLOW_EXPERIMENTS=1` when explicitly running `real_workflow_experiment` tests such as the preserved search rollout examples. These are not part of the minimal L3 release gate.

L3 uses a minimum coverage model:

- One real provider CLI smoke proves process launch, structured output parsing, artifact persistence, and resume command shape. It does not try to prove that a model can finish a large product task.
- One real Agent-host smoke per selected implemented host proves the installed Codex, Claude Code, or OpenCode entry can drive `/loopora-gen` before `/loopora-loop`, execute returned Agent-native step capsules with the host's own role/subagent mechanism, submit `loopora_host_dispatch` proof, and continue until terminal. The test prompt must not disclose the underlying `loopora agent <adapter> ...` commands, the managed entry must leave an invocation-source trail in the Core binding, and a sentinel PATH must prove Loopora did not call a nested `codex` / `claude` / `opencode` CLI from inside the host session. The fixture bundle uses the minimum terminal flow: one upstream evidence-producing step and one GateKeeper step. It should not put the run's eventual terminal state into task-level Done When; the outer test harness asserts terminal status after the Agent-native loop completes.
- One real Web-process smoke proves browser control of Codex / Claude Code / OpenCode adapter status / install / update / uninstall and visible error states against a real `loopora serve`.
- Larger realistic tasks may live as manual scenarios or `real_workflow_experiment` tests, but they should not be the default release blocker unless the feature being released is specifically about that workflow.

## Guardrails

- The default Ruff gate covers syntax/name errors and Bugbear runtime hazards; broader style-modernization scans remain opt-in cleanup work.
- Do not assert static UI copy as the main contract.
- Do not assert CSS classes, DOM nesting, or script source internals unless the behavior has no better public anchor.
- Keep language-specific checks narrow and focused on locale selection or presence of translated resources, not exact phrasing.
- Default-path UI tests should assert the core user actions: describe task, confirm loop plan, run, and inspect evidence.
- Expert terms such as `bundle`, `YAML`, `orchestration`, and `workflow controls` should be asserted only on expert paths or debug/source panels, not as required default-path copy.
- Keep legacy compatibility coverage separate from new-path quality assertions.
- Prefer one high-value journey over many tests that mirror individual implementation branches.
- Keep `tests/scenarios/` small; merge adjacent UI flows into one journey instead of adding one file per page tweak.
- When adding or pruning tests, keep the highest-value assertion at each layer and delete branch-mirror tests that only restate implementation details.
