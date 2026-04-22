# Task

Locate the first layer where the help-center shadow slice regresses on high-value queries, then repair that layer without rewriting the whole search stack.

# Done When

- The representative shadow queries `rotate personal token` and `saml sign-in domain` are reproducible from the current workspace.
- The first failing layer is pinned down with direct evidence instead of guesswork.
- The repaired help-center shadow results now serve the latest document revision for both representative queries.
- `reports/high_value_query_root_cause.md` exists and explains the failing layer that was fixed.

# Guardrails

- Do not expand this round into a full hybrid-search rewrite.
- Keep the repair anchored to the first failing layer that actually explains the regression.
- Preserve the public help-center contract while repairing the shadow slice.

# Role Notes

## Inspector Notes

Start by proving whether the regression begins in ingestion freshness, revision selection, indexing, retrieval, or serving.

## Builder Notes

Only repair the layer that has direct evidence behind it.

## GateKeeper Notes

Pass only when the representative queries and the root-cause report agree on the same repaired layer.

## Guide Notes

If the diagnosis is still noisy, narrow the next move to the smallest slice that can disprove the leading root-cause hypothesis.
