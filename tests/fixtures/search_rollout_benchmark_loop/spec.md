# Task

Use one benchmark-driven optimization pass to bring hybrid-search relevance to the release line and leave enough evidence to decide the next subsystem focus.

# Done When

- The visible relevance benchmark reaches at least `0.95`.
- The holdout benchmark reaches at least `0.95`.
- `reports/benchmark_direction.json` exists and records the benchmark score, holdout score, and the most likely next focus.
- The changes stay anchored to real retrieval, reranking, or query-rewrite improvements instead of a one-off benchmark hack.

# Guardrails

- Do not hardcode exact benchmark answers into the search path.
- Preserve the public-versus-employee visibility contract.
- Keep the benchmark and holdout results inspectable from the current workspace.

# Role Notes

## GateKeeper Notes

Read the benchmark results first and only pass when both benchmark and holdout evidence support the current direction.

## Builder Notes

Prefer changes that improve the actual search stack rather than one-off score spikes.
