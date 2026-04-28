---
summary: "Scenario: a product task needs a real implementation plus two independent evidence views before it is safe to close."
---

## Scenario

A team wants an AI Agent to carry a substantial product change past the first implementation pass. The target is clear enough to build, but the risk is not one-dimensional: the result may violate the user contract, and it may also lack reproducible proof. A single reviewer can miss one of those surfaces.

## Request

Build the first inspectable result, then review it from both contract and evidence perspectives before deciding whether the loop can finish.

## Why this workflow fits

Builder creates a concrete state first. Contract Inspector checks whether that state matches the task contract, guardrails, and fake-done risks. Evidence Inspector independently checks whether the main path is backed by repeatable proof. GateKeeper then closes only when both inspection surfaces support the verdict.

## Why not the other workflows

This is not `Evidence First` because the target is already clear enough to attempt. It is not `Repair Loop` because the task does not yet assume a second repair pass. It is not `Benchmark Gate` unless a stable benchmark or contract proof is already the main decision source.

## Why not just let an AI Agent do it

An AI Agent can build the first pass, but humans often come back afterward to ask two different questions: did it actually satisfy the task, and is there trustworthy evidence? Loopora externalizes both checks, runs them as a bounded parallel inspection group, and lets GateKeeper make the final call from the gathered evidence.

## Example spec

# Task

Ship the first working version of the requested feature while keeping the result inspectable from both user-contract and evidence perspectives.

# Done When

- A user-visible main path exists and can be exercised.
- The implementation respects the stated task contract and guardrails.
- At least one repeatable proof demonstrates the main path or the primary behavior.
- GateKeeper can cite evidence from both contract and evidence inspection before finishing.

# Guardrails

- Do not claim completion from screenshots, static pages, or optimistic summaries alone.
- Keep the first pass scoped to a coherent slice instead of scattering disconnected changes.
- Preserve enough handoff detail for both inspectors to review the same Builder output.

# Success Surface

- The result feels like a real first usable slice, not a demo facade.
- The main behavior can be explained through concrete files, commands, artifacts, or browser-visible behavior.

# Fake Done

- UI polish exists but the main path does not work.
- Tests or artifacts exist but do not cover the user-facing promise.
- The implementation works once but leaves no repeatable evidence for GateKeeper.

# Evidence Preferences

- Prefer project-owned commands, browser paths, contract tests, or generated artifacts that can be rerun.
- Treat static appearance as secondary evidence unless the task is explicitly visual.

# Role Notes

## Builder Notes

Create one coherent inspectable result and leave a concise handoff that two inspectors can review independently.

## Contract Inspector Notes

Check the result against the task contract, guardrails, and fake-done risks before discussing secondary polish.

## Evidence Inspector Notes

Collect repeatable proof for the main path and clearly mark any evidence that is weak, indirect, or missing.

## GateKeeper Notes

Finish only when both inspection surfaces support the verdict and the evidence ledger can justify closing the loop.
