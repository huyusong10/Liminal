---
summary: "Scenario: users report password-reset emails sometimes send twice, but nobody knows whether the duplicate comes from the UI, API, or queue."
---

## Scenario

Support keeps getting reports that password-reset emails sometimes arrive twice. The reports are inconsistent, and the team has not confirmed whether the duplicate is triggered by the web UI, the backend API, or the async email queue.

## Request

Turn the fuzzy complaint into one verified repair direction, then land that repair with evidence.

## Why this workflow fits

The problem statement is still ambiguous, so Inspector should shrink the ambiguity first, Guide should turn that diagnosis into one concrete move, and only then should Builder commit to a repair that GateKeeper can judge.

## Why not the other workflows

This is not `Inspect First` because even the failing path is still fuzzy. It is not `Build First` because asking Builder to move first would force implementation before the task is even shaped. It is also not `Repair Loop`, because we are still trying to define the first repair direction, not plan the second one.

## Example spec

# Task

Turn the duplicate password-reset email complaint into one verified repair direction, then implement that repair with evidence.

# Done When

- The current issue is reduced to one diagnosed layer or decision point with direct evidence.
- One repair direction is implemented against that diagnosed issue.
- The same clarified trigger no longer sends duplicate emails, or the remaining blocker is narrowed to one verified gap.
- The diagnosis trace remains inspectable through files, commands, or artifacts.

# Guardrails

- Do not let the scope sprawl into unrelated cleanup while the issue is still being clarified.
- Preserve email flows that have not been shown to be part of the problem.
- Keep the diagnosis traceable from evidence to final repair.

# Role Notes

## Inspector Notes

Frame the ambiguity into the smallest concrete problem statement possible.

## Guide Notes

Translate the diagnosis into one high-leverage next move, not a long strategy memo.

## Builder Notes

Implement the chosen direction only after the problem statement is narrow enough to verify.

## GateKeeper Notes

Judge against the clarified problem definition, not the original vague wording.
