# Loopora Verification Map

Loopora verification is organized by two independent questions:

- Verification type: what kind of evidence proves the behavior?
- Run profile: when should that evidence be collected?

Older labels such as L1/L2/L3 are no longer the primary taxonomy. They mixed execution cost with evidence meaning and did not describe review-only or experiment-style cases well.

## Verification Types

| Type | Directory | What It Proves | Result Shape |
| --- | --- | --- | --- |
| Contract Checks | `tests/checks/contracts/` | Stable public contracts, data semantics, schema behavior, CLI/API boundaries, static asset contracts | Deterministic pytest pass/fail |
| Journey Checks | `tests/checks/journeys/` | User-visible local flows that need browser, templates, client state, or in-process Web behavior | Deterministic pytest pass/fail plus local artifacts when useful |
| Real Probes | `tests/probes/real_environment/` | Real provider CLIs, real Agent hosts, or a real `loopora serve` process still satisfy the minimal external-boundary contract | Opt-in pytest pass/fail plus phase reports |
| Review Cases | `tests/reviews/` | Fuzzy visual, semantic, expression, and experience quality that code can help capture but should not pretend to judge alone | Screenshots, reports, machine hints, human/agent review |
| Scenarios | `tests/scenarios/` | Manual exploratory journeys through stable product goals | Playbook steps and evidence boundaries |
| Experiments | `tests/experiments/` | High-cost or research-like real workflows that preserve evidence but are not default gates | Opt-in artifacts and analysis |

## Run Profiles

| Profile | When | Typical Entry |
| --- | --- | --- |
| `default-fast` | Every normal code change before commit | `uv run ruff check .` and `uv run pytest -q tests/checks/contracts` |
| `focused` | A touched module has a nearby contract or journey check | Focused pytest path under `tests/checks/contracts/` or `tests/checks/journeys/` |
| `journey` | A touched UI flow, CI container job, or release profile needs rendered/user-flow evidence | `uv run pytest -q tests/checks/journeys` |
| `opt-in` | A user/reviewer asks for visual, semantic, real-host, or exploratory evidence | `tests/reviews/run.py`, `tests/probes/real_environment/run_real_probes.py`, or a scenario playbook |
| `release` | Before shipping changes that depend on real external hosts or browser/server integration | Real probe suites plus relevant journey checks |
| `experiment` | The goal is to learn from a realistic task, not to block ordinary development | Explicit experiment tests under `tests/experiments/` |

## Default-Fast Gate

For ordinary code work, run:

```bash
uv run ruff check .
uv run pytest -q tests/checks/contracts
```

Use narrower pytest paths when the touched behavior has a clear local boundary. Journey checks move out of the local default-fast gate: run them when the touched change affects rendered pages, browser state, navigation, forms, or the CI/release profile asks for them. Contract and journey checks should assert user-observable behavior, public return values, stable IDs, status semantics, structured errors, persisted artifacts, and accessible controls. They should not assert private variables, CSS classes, DOM nesting, transient implementation order, or exact copy unless the copy is itself the contract.

## Real Probes

Real probes are handbook-first. Before running or interpreting them, read:

```bash
python tests/probes/real_environment/run_real_probes.py --show-playbook
```

Common entries:

```bash
python tests/probes/real_environment/run_real_probes.py --suite real-agent --agent-targets codex,claude,opencode
python tests/probes/real_environment/run_real_probes.py --suite real-cli --cli-targets codex,claude,opencode
python tests/probes/real_environment/run_real_probes.py --suite release-web
```

The GitHub manual Real Probe workflow is only a wrapper around this runner. Its release profile selects `real-agent`, `real-cli`, and `release-web`; real workflow experiments remain opt-in through the experiment gate below and are not mixed into the release probe by default.

Real probes may skip on ordinary developer machines, but the skip reason must name the missing environment switch or command template. Phase reports are written under `.loopora/real-probes/` so a failing run exposes process, model, artifact, state, and command evidence without forcing the operator to infer progress from quiet stdout.

Claude Code and OpenCode model defaults are part of the ordinary release profile: Claude Code uses `Kimi-K2.6`, and OpenCode uses `minimax-token-plan/MiniMax-M2.7`. A real probe fails the default release profile if those models are not visible in the real Agent command template or real CLI command events. Set `LOOPORA_REAL_PROBE_ALLOW_MODEL_OVERRIDE=1` only when the release deliberately validates a different model.

## Review Cases

Review cases are separate from deterministic checks. They are case-first and intentionally allow fuzzy semantic checks such as text crowding, arrows crossing labels, clipped controls, expert-language leakage, misleading diagrams, or page chrome compressing content.

Run:

```bash
uv run python tests/reviews/run.py --case rendered-surfaces
uv run python tests/reviews/run.py --case rendered-surfaces --url home=http://127.0.0.1:8000/
```

SVG diagrams and Web pages share the same review runner and case format. Logo assets are not review-case targets; they keep ordinary structural checks for parseability, serving, and references.

## Experiments

Real workflow experiments are explicitly opt-in:

```bash
LOOPORA_ENABLE_REAL_WORKFLOW_EXPERIMENTS=1 uv run pytest -q tests/experiments/real_workflows
```

Experiments may preserve copied workspaces, run artifacts, proof output, and review notes. They should not become release blockers unless the shipped feature is specifically about that workflow.

## Guardrails

- Use deterministic code checks for stable contracts.
- Use review cases when code can collect pixels/text/hints but final judgment is semantic.
- Keep expression-flexibility examples in review cases instead of multiplying contract checks for every acceptable wording.
- Use scenarios when the useful artifact is an exploratory route rather than an automated assertion.
- Use experiments when the task is costly, provider-dependent, or intentionally research-like.
- Prefer one high-value journey over many branch-mirror tests.
- Keep language-specific checks narrow and focused on locale selection or resource presence, not exact phrasing.
- Keep legacy compatibility coverage separate from new-path quality assertions.
