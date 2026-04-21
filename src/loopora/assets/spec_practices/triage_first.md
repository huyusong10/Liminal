---
summary: "Scenario: as the hybrid-search rollout expands beyond the help center, operators now report stale results, ranking drift, broken filters, and occasional permission leakage, and this loop must reduce the noise to one actionable blocker."
---

## Scenario

The rollout is expanding from the help center into API docs and internal manuals. At the same time, several classes of issues start appearing together: stale results, ranking drift, broken filters, and occasional permission leakage. The team cannot fix every symptom in this round. The job here is to reduce the noise to one actionable blocker that should absorb the next meaningful implementation effort.

## Request

Turn the mixed rollout symptoms into one grounded blocker slice, then implement against that slice without pretending the entire search rollout stabilizes in this round.

## Why this workflow fits

The hardest problem is still deciding what this loop is actually about. Inspector must separate recurring signals from rollout noise, Guide must translate that diagnosis into one high-leverage next move, and only then should Builder commit code that GateKeeper can judge against a clarified target.

## Why not the other workflows

This is not `Inspect First` because the work has not yet been reduced to one stable defect with one evidence path. It is not `Build First` because asking Builder to move first would push implementation ahead of problem definition. It is also not `Repair Loop`, because this round is still about choosing the first repair slice, not planning a second pass.

## Why not just let a strong agent do it

Without Loopora, a strong agent could pick one symptom and start changing code, but humans would have to keep returning to ask whether that symptom was even the right blocker to chase. The bottleneck is not raw implementation; it is repeated human re-scoping. Loopora reduces that traffic by letting `Inspector` compress the evidence, `Guide` choose the slice, and only then letting `Builder` and `GateKeeper` spend effort on something the team actually wants judged this round.

## Example spec

# Task

Reduce the mixed hybrid-search rollout symptoms to one verified blocker slice, then implement that slice with evidence while preserving the wider rollout context.

# Done When

- The current symptom cloud is reduced to one diagnosed subsystem or decision point with direct evidence.
- One repair direction is selected and implemented against that diagnosed slice.
- The same clarified trigger path no longer exhibits the chosen blocker, or the remaining blocker is narrowed to one verified gap.
- The diagnosis trail remains inspectable through commands, traces, or rollout artifacts so later loops can build on it.

# Guardrails

- Do not widen this round into a full search-rollout stabilization rewrite.
- Preserve behaviors that have not been shown to belong to the chosen blocker slice.
- Keep the link between evidence, chosen repair direction, and final result traceable for the next loop.

# Role Notes

## Inspector Notes

Separate recurring rollout signals from noise and reduce the symptom cloud to the smallest defensible blocker statement.

## Guide Notes

Turn the diagnosis into one high-leverage next move, not a broad rollout roadmap.

## Builder Notes

Implement only after the chosen slice is narrow enough that GateKeeper can judge it against direct evidence.

## GateKeeper Notes

Judge this round against the clarified blocker slice, not against the entire rollout.
