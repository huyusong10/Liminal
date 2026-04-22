# Task

Bring full hybrid-search reindexing back inside the maintenance window and leave a repair review that explains the final bottleneck state.

# Done When

- Full reindexing finishes inside `MAINTENANCE_WINDOW_SECONDS`.
- Duplicate ACL work is collapsed so permission digest calls stay close to the number of unique ACL groups.
- Duplicate chunk work is collapsed so embedding calls stay close to the number of unique chunks.
- `reports/reindex_repair_review.json` exists and records the final metrics plus whether the maintenance window is now met.

# Guardrails

- Do not fake the metrics or hardcode a passing review file.
- Keep the reindex output structurally equivalent; this round is about performance and maintenance-window safety.
- Avoid moving the bottleneck from one stage to another without showing the new metrics.

# Role Notes

## Builder Notes

Assume one repair pass is not enough; optimize for a clean first improvement that still leaves inspectable metrics.

## Inspector Notes

Compare the post-repair metrics with the maintenance window and the call-count structure, not just with a subjective feeling of speed.

## Guide Notes

Use the first repaired metrics to decide whether the second pass should focus on ACL work, chunk work, or another exposed bottleneck.

## GateKeeper Notes

Pass only when the final metrics and the repair review agree that the maintenance window is now met.
