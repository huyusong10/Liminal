---
summary: "Scenario: full search reindexing for the new hybrid stack still blows the maintenance window, and the team already expects the first repair to expose the second bottleneck."
---

## Scenario

The new hybrid stack is functionally close, but one major blocker remains before a wider cutover: a full search reindex still blows past the maintenance window. The team already knows the first repair will likely remove the most obvious bottleneck only to expose a second one deeper in chunking, permission bitmaps, shard merge, or index writes.

## Request

Leave explicit room for a fix, re-check, and second repair cycle so a full hybrid-search reindex returns to an acceptable maintenance window instead of merely moving pressure from one stage to another.

## Why this workflow fits

This task begins with the expectation that one repair pass will not be enough. Builder needs an initial pass to remove the first bottleneck, Inspector needs to study the new runtime evidence, Guide needs to choose the second pass, and only then should Builder and GateKeeper close the loop.

## Why not the other workflows

This is not `Build First` because the baseline path already exists. It is not `Inspect First` because the first repair is itself required to surface the next meaningful evidence. It is also not `Benchmark Loop`, because the deciding signal is not one score but the actual system bottleneck that remains after the first repair.

## Why not just let a strong agent do it

A strong agent can certainly attempt the first repair. The problem is that humans would still need to come back after that repair to read the new traces, decide what the real second bottleneck is, and redirect the next pass. That repeated re-entry is exactly the bottleneck Loopora is meant to reduce. `Builder` creates the new runtime state, `Inspector` reads it, `Guide` narrows the second move, and `GateKeeper` decides whether the window is actually back under control.

## Example spec

# Task

Bring full hybrid-search reindexing back inside an acceptable maintenance window and remove the most important bottleneck that remains after the first repair.

# Done When

- The first repair pass produces new reindex evidence that shows whether the original dominant bottleneck is gone.
- A follow-up inspection confirms whether the remaining bottleneck lives in chunking, permission bitmap generation, shard merge, or index writes.
- The final state no longer blows the maintenance window and does not merely move the blockage from one stage to another.
- The latest validation uses the same full reindex path instead of switching to a lighter substitute case.

# Guardrails

- Keep each repair pass focused and preserve enough evidence to justify the next one.
- Preserve behavior for routine incremental indexing and live query serving.
- Do not trade away index completeness or recoverability just to reduce the window.

# Role Notes

## Builder Notes

Use the first pass to remove the dominant known bottleneck, then use the second pass only for the largest verified gap that remains.

## Inspector Notes

Compare the new reindex trace directly against the pre-repair baseline instead of inventing a lighter measurement path.

## Guide Notes

If the first repair exposes a different class of bottleneck, point the second pass at that new gap instead of forcing the old theory.

## GateKeeper Notes

Only pass if the original maintenance-window pressure is genuinely reduced and the index remains complete and usable.
