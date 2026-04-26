---
summary: "Scenario: after the help-center slice enters shadow traffic, a small set of high-value queries regress, and the loop must pin down whether the first gap is ingestion, indexing, retrieval, reranking, or permission filtering."
---

## Scenario

The help-center slice is already in shadow traffic. Most queries look acceptable, but a small set of high-value queries now miss key results or return obviously stale answers compared with the old search. The team still does not know whether the first gap begins in ingestion freshness, index construction, retrieval, reranking, or permission filtering.

## Request

Ground the first failing layer for the regressed queries, then repair that layer without widening the work into a broad search rewrite.

## Why this workflow fits

The failure surface is already known: a stable set of high-value queries is regressing. What is missing now is trustworthy evidence about where the gap first appears. Inspector needs to pin down that first failing layer before Builder touches the system, and GateKeeper should later judge the repair against the same evidence path rather than against a different story.

## Why not the other workflows

This is not `Build First` because the help-center path already exists; the missing piece is evidence, not the first slice. It is not `Triage First` because the current issue has already been reduced to one query-regression problem, not a cloud of unrelated symptoms. It is also not `Repair Loop`, because we are still deciding the first repair target rather than planning the second repair pass.

## Why not just let an AI Agent do it

Without Loopora, an AI Agent could start changing retrieval, reranking, or freshness logic immediately, but humans would then have to keep returning to ask whether the agent is even working on the right layer. One review after the patch would not be enough, because the real question comes earlier: where does the first trustworthy gap appear? Loopora reduces those repeated human check-ins by letting `Inspector` pin the evidence, `Builder` repair against that evidence, and `GateKeeper` judge the same path afterward.

## Example spec

# Task

Identify the first failing layer behind the regressed high-value help-center queries in shadow traffic and repair it without changing the broader search contract.

# Done When

- A stable set of representative high-value queries reproduces the regression through project-owned evidence.
- The first layer where the regression appears is grounded in direct evidence.
- One repair is implemented against that grounded layer.
- The same representative queries now improve on the repaired path, or the remaining blocker is narrowed to one verified gap.
- Final validation follows the same evidence path that exposed the regression.

# Guardrails

- Do not widen this round into a broad search-stack rewrite before the first failing layer is grounded.
- Preserve the existing help-center search entry points and outward search contract.
- Keep the logs, traces, and artifacts that explain the regression so later loops do not restart blind.

# Role Notes

## Inspector Notes

First pin down where the regression appears between ingestion freshness, indexing, retrieval, reranking, and permission filtering.

## Builder Notes

Repair only the layer already supported by evidence instead of patching multiple guesses at once.

## GateKeeper Notes

Only pass if the same representative queries improve on the same evidence path that surfaced the regression.

## Guide Notes

If the evidence is still noisy, narrow the next move to a tighter diagnostic slice instead of broad search cleanup.
