---
summary: "Scenario: before wider rollout, the hybrid-search project needs one benchmark-driven round to decide whether the next human check-in should still focus on retrieval, reranking, or query rewrite."
---

## Scenario

The hybrid-search rollout is getting close to the point where the team must decide whether to expand beyond the first domain. Release is gated by a relevance benchmark and a locked score threshold. The work is no longer about one defect; it is about deciding, round by round, whether the next improvement should target retrieval, reranking, or query rewrite. This loop exists to turn the latest benchmark evidence into the next concrete move.

## Request

Run one benchmark-guided improvement round that leaves fresh evidence about whether the next effort should stay on the same subsystem or move elsewhere.

## Why this workflow fits

Every round should begin with measured evidence, not taste. GateKeeper reads the benchmark artifacts first, Builder reacts to that verdict, and the loop only continues when the latest score breakdown changes what should happen next.

## Why not the other workflows

This is not `Build First` because the system already exists and the deciding signal is no longer “can it run.” It is not `Inspect First` because the goal is not to pin down one failing path but to choose the next optimization target from benchmark evidence. It is also not `Repair Loop`, because the main driver is still the latest evaluation result rather than the residue of a specific repair pass.

## Why not just let a strong agent do it

Without Loopora, a strong agent could keep optimizing in one direction, but humans would need to return after every benchmark run to decide whether the score moved for the right reason, whether the remaining loss is still in the same subsystem, and whether the next round should change direction. Loopora reduces those repeated human check-ins by giving `GateKeeper` the benchmark first, letting `Builder` act on that verdict, and preserving the evidence needed for the next decision without making the human restate the whole context each time.

## Example spec

# Task

Use one benchmark-guided improvement round to advance hybrid-search quality and leave fresh score evidence that decides whether the next round should stay on the same subsystem or move elsewhere.

# Done When

- The relevance benchmark can be rerun end to end from the repository.
- Fresh evaluation artifacts are produced from the current workspace and remain inspectable.
- This round either improves the benchmark over the locked baseline or narrows the dominant remaining loss to one verified subsystem.
- The benchmark breakdown is specific enough to decide whether the next round should target retrieval, reranking, or query rewrite.
- Claimed gains can be traced to product improvements rather than benchmark-only shortcuts.

# Guardrails

- Do not hardcode benchmark answers, labels, or one-off caches.
- Preserve the live search contract while optimizing.
- Keep reports, score breakdowns, and benchmark inputs inspectable so the next round can build on them.

# Role Notes

## GateKeeper Notes

Start from the latest benchmark artifacts and fail closed if the harness itself is not trustworthy yet.

## Builder Notes

Make changes that improve a real subsystem, not one-off score spikes with no rollout value.
