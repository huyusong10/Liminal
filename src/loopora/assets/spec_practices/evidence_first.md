---
summary: "Scenario: the task risk is still ambiguous, so the loop must ground evidence before Builder changes the system."
---

## Scenario

A long-running task already has visible symptoms or a broad goal, but the first safe implementation target is still unclear. Building immediately would likely amplify the wrong assumption.

## Request

Establish the first trustworthy evidence boundary, then make one focused change against that boundary and let GateKeeper judge the same evidence path.

## Why this workflow fits

Inspector goes first to separate facts, assumptions, and open questions. Builder then acts against the grounded slice rather than guessing across the whole system. GateKeeper decides whether the resulting state satisfies the same evidence boundary.

## Why not the other workflows

This is not `Build + Parallel Review` because there is not yet enough confidence to build first. It is not `Repair Loop` because the second pass is not known yet. It is not `Benchmark Gate` unless a stable benchmark is already the deciding signal.

## Why not just let an AI Agent do it

Without a grounded first inspection, an AI Agent can easily work hard on the wrong layer. Loopora reduces that drift by externalizing the evidence boundary before implementation begins.

## Example spec

# Task

Ground the first trustworthy evidence boundary for the current problem, then implement the smallest change that addresses that boundary.

# Done When

- The first failing or uncertain layer is identified through direct evidence.
- Builder makes one focused change against that evidence instead of broad speculative edits.
- The final validation uses the same evidence path that shaped the implementation.
- GateKeeper can explain which assumptions are now resolved and which risks remain.

# Guardrails

- Do not make broad implementation changes before the first evidence boundary is clear.
- Do not replace direct evidence with generic diagnosis prose.
- Preserve artifacts that explain why this slice was chosen.

# Success Surface

- The next implementation move is grounded rather than guessed.
- The final state can be evaluated against a stable evidence path.

# Fake Done

- The code changes but the original uncertainty remains.
- Inspector lists possibilities without identifying the strongest first evidence boundary.
- GateKeeper passes because something improved, not because the grounded slice is resolved.

# Evidence Preferences

- Prefer commands, logs, traces, tests, or artifact comparisons that identify where the issue first appears.
- Label assumptions explicitly when the workdir does not contain enough proof.

# Role Notes

## Inspector Notes

Pin down the first trustworthy evidence boundary before recommending implementation.

## Builder Notes

Repair only the grounded slice and keep the handoff tied to the Inspector evidence.

## GateKeeper Notes

Judge against the same evidence boundary; do not let a different success story replace the one that justified the change.
