---
summary: "Scenario: full-text reindexing for very large tenants blows past the release window, and the team already expects the first repair to expose a second bottleneck."
---

## Scenario

A self-hosted knowledge product regularly blows past its release window when it runs a full-text reindex for very large tenants. The team already knows the first repair will likely remove the obvious queue backlog only to reveal a second bottleneck in replay, compaction, or index writes.

## Request

Leave explicit room for a fix, re-check, and second repair cycle so large-tenant reindexing returns to an acceptable window instead of merely moving the pressure from one stage to another.

## Why this workflow fits

This task starts with the expectation that one repair pass will not be enough. Builder needs an initial pass to remove the first bottleneck, Inspector needs to study the new runtime evidence, Guide needs to help pick the second pass, and only then should Builder and GateKeeper close it out.

## Why not the other workflows

This is not `Build First` because the first implementation pass is not the end state. It is not `Inspect First` because the first repair is itself required to surface the next signal. It is also not `Benchmark Loop`, because the deciding signal is not one score but the real system bottleneck that remains after the first repair.

## Example spec

# Task

Bring full-text reindexing for very large tenants back inside an acceptable window and remove the most important bottleneck that remains after the first repair.

# Done When

- The first repair pass produces new reindex evidence that shows whether the original dominant bottleneck is gone.
- A follow-up inspection confirms whether the remaining bottleneck lives in replay, compaction, or index writes.
- The final state no longer blows the release window for large-tenant reindexing and does not merely move the blockage from one stage to another.
- The latest validation uses the same large-tenant reindex path instead of switching to a lighter substitute case.

# Guardrails

- Keep each repair pass focused and preserve enough evidence to justify the next one.
- Preserve behavior for normal tenants and routine incremental indexing.
- Do not trade away index completeness or recoverability just to reduce the window.

# Role Notes

## Builder Notes

Use the first pass to remove the dominant known bottleneck, then use the second pass only for the largest verified gap that remains.

## Inspector Notes

Compare the new reindex trace directly against the pre-repair baseline instead of inventing a lighter measurement path.

## Guide Notes

If the first repair exposes a different class of bottleneck, point the second pass at that new gap instead of forcing the old theory.

## GateKeeper Notes

Only pass if the original release-window pressure is genuinely reduced and the index remains complete and usable.
