---
summary: "Scenario: a knowledge-base product is replacing keyword-only search with hybrid search, and this loop must get the first help-center slice ready for shadow traffic."
---

## Scenario

A knowledge-base product is replacing its old keyword-only search with a new hybrid search stack. The rollout starts with one concrete content domain: the public help center. This loop is not responsible for the whole search upgrade. It is responsible for getting the first help-center slice ready for shadow traffic, so the team can judge the new path on real content instead of on architecture diagrams.

## Request

Get the help-center domain through the first end-to-end hybrid-search path: ingestion, indexing, retrieval, permission filtering, and search-page serving. Keep the current search entry points intact and leave a clear go or no-go decision for shadow traffic.

## Why this workflow fits

The destination is already clear. What is missing first is a real working slice that Builder can land, so Inspector can validate it on real help-center content and GateKeeper can decide whether the new path is trustworthy enough to enter shadow traffic. Guide only matters if the first slice stalls and the next step must be narrowed.

## Why not the other workflows

This is not `Inspect First` because the team is not blocked on finding a mystery defect; it is blocked on establishing the first real path. It is not `Triage First` because the scope of this loop is already explicit. It is also not `Repair Loop`, because this round is about getting the baseline path to exist before any second-pass repair question appears.

## Why not just let an AI Agent do it

An AI Agent can absolutely write a first pass here. The reason to use Loopora is that, without a loop, humans would have to keep coming back after ingestion, after indexing, and after the first queries to ask the same questions again: is the path actually end to end now, is the result good enough for shadow traffic, and what is still the main blocker? Loopora folds those repeated check-ins into `Builder`, `Inspector`, `GateKeeper`, and `Guide`, so the human only needs to step in after the workflow has already collected the new evidence and verdicts.

## Example spec

# Task

Deliver the first help-center hybrid-search slice so the existing search entry points can serve real help-center content through the new stack and leave a trustworthy shadow-traffic decision.

# Done When

- Help-center content can move through the new ingestion and indexing path end to end.
- The existing search entry points can read results from the new help-center search path.
- At least one project-owned set of representative help-center queries returns usable results through the new stack.
- Permission filtering and basic result rendering still hold on the served path.
- The resulting evidence is strong enough for `GateKeeper` to decide whether the help-center slice can enter shadow traffic.

# Guardrails

- Keep this round scoped to the help-center slice instead of the full search migration.
- Reuse the current search entry points and public search page instead of creating a parallel search surface.
- Preserve the current outward search contract while the new slice is being introduced.

# Role Notes

## Builder Notes

Optimize for the first real shadow-ready path, not for speculative cleanup around the wider migration.

## Inspector Notes

Validate ingestion, indexing, retrieval, filtering, and search-page serving on real help-center content before chasing secondary polish.

## GateKeeper Notes

Pass only when the help-center slice is strong enough to justify shadow traffic on the existing search entry points.

## Guide Notes

If progress stalls, narrow the next move to the one missing outcome that prevents a clean shadow-traffic decision.
