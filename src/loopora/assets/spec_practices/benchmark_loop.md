---
summary: "Scenario: the support-answer benchmark sits at 61% pass rate, and release requires at least 70% without hardcoded shortcuts."
---

## Scenario

The project already ships a support-answer evaluation harness. The current baseline is 61% pass rate, and the release target is 70% or better. The team explicitly does not want benchmark-only tricks that would make the real product worse.

## Request

Raise the evaluation result to the release target while keeping the live retrieval and ranking behavior honest.

## Why this workflow fits

Every iteration should stay anchored to benchmark evidence, not intuition. GateKeeper reads the benchmark first, Builder reacts to that verdict, and the next round only exists if the latest score changed the decision surface.

## Why not the other workflows

This is not `Build First` because implementation is not the primary loop driver here. It is not `Inspect First` because a failing path is not the main object of study. It is also not `Repair Loop`, because the key question each round is whether the measured score changed enough to justify the next move.

## Example spec

# Task

Raise the project-owned support-answer benchmark from the current 61% baseline to at least 70%, without introducing benchmark-only shortcuts.

# Done When

- The benchmark harness can be rerun end to end from the repository.
- The latest evaluation artifacts are fresh, inspectable, and tied to the current workspace.
- The latest benchmark result is at least 70%.
- Claimed gains can be traced to project changes that also improve the live system or the harness reliability.

# Guardrails

- Do not hardcode benchmark answers, label mappings, or one-off caches.
- Preserve the public product surface while optimizing.
- Keep benchmark inputs, reports, and score artifacts inspectable.

# Role Notes

## GateKeeper Notes

Start from benchmark evidence, not intuition, and fail closed when the harness itself is not trustworthy yet.

## Builder Notes

Prefer changes that improve the real system or harness reliability instead of chasing one-off score spikes.
