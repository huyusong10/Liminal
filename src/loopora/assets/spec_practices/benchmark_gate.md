---
summary: "Scenario: a benchmark or contract proof already exists, and the loop should use the same measurement before and after the change."
---

## Scenario

The task has a repeatable benchmark, contract test, or measurement artifact. The main risk is not lacking effort; it is claiming progress with a different evidence standard after implementation.

## Request

Read the benchmark evidence first, make one focused change, re-check the same evidence path, and let GateKeeper decide from the updated proof.

## Why this workflow fits

Benchmark Inspector establishes the baseline. Builder targets the highest-leverage failing signal. Regression Inspector reruns or inspects the same path after the change. GateKeeper closes only if the repeated evidence is strong enough and residual risk is acceptable.

## Why not the other workflows

This is not `Build + Parallel Review` because the primary decision source is already a benchmark. It is not `Evidence First` because the evidence mechanism exists and should be reused. It is not `Repair Loop` unless the first repair is expected to expose a second blocker that needs another Builder pass.

## Why not just let an AI Agent do it

An AI Agent can optimize toward a number, but without an external loop it may switch evidence standards, overfit one spot check, or summarize improvement without a repeatable proof. Loopora pins the evidence path before and after the change.

## Example spec

# Task

Use the existing benchmark or contract proof to improve the most important failing signal without changing the evidence standard.

# Done When

- The pre-change benchmark or contract evidence is recorded.
- Builder targets the highest-leverage measured blocker.
- The post-change evidence uses the same benchmark, contract proof, or measurement path.
- GateKeeper can cite the repeated evidence and name any remaining residual risk.

# Guardrails

- Do not switch to easier evidence after implementation.
- Do not optimize a narrow metric in a way that violates the user-facing contract.
- Preserve the benchmark output or artifact that explains the verdict.

# Success Surface

- The measured blocker improves or is clearly narrowed.
- The evidence path remains comparable before and after the change.

# Fake Done

- A different command passes while the original benchmark still fails.
- The result improves one number but breaks the task contract.
- The final verdict lacks benchmark or contract evidence refs.

# Evidence Preferences

- Prefer project-owned benchmark output, contract proof, regression reports, or saved metric artifacts.
- Treat anecdotal inspection as supporting context, not the primary proof.

# Role Notes

## Benchmark Inspector Notes

Capture the baseline evidence and name the highest-leverage failing signal.

## Builder Notes

Make the smallest change that targets the measured blocker without changing the evidence standard.

## Regression Inspector Notes

Re-check the same evidence path and call out regressions, overfitting, or missing measurement.

## GateKeeper Notes

Pass only when repeated evidence justifies the verdict and residual risk is explicit.
