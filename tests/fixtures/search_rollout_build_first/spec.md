# Task

Deliver the first help-center hybrid-search slice so the existing search entry points can serve real help-center content through the new stack and leave a trustworthy shadow-traffic decision.

# Done When

- Help-center content can move through the new ingestion and indexing path end to end.
- The existing search entry points can read results from the new help-center search path.
- The representative queries `rotate personal token`, `saml sign-in domain`, and `billing export csv` return the correct help-center articles.
- Employee-only help-center content stays hidden from public viewers while remaining visible to employee viewers.
- `reports/help_center_shadow_decision.json` exists and clearly states whether the help-center slice is ready for shadow traffic.

# Guardrails

- Keep this round scoped to the help-center slice instead of the full search migration.
- Reuse the current search entry points instead of creating a parallel UI.
- Preserve the current outward search contract for public help-center traffic.

# Role Notes

## Builder Notes

Optimize for the first real help-center slice that can plausibly enter shadow traffic.

## Inspector Notes

Validate the representative queries and the public-versus-employee permission boundary on real records.

## GateKeeper Notes

Pass only when the help-center slice and the shadow-readiness report both make the rollout decision inspectable.

## Guide Notes

If the loop stalls, narrow the next move to the missing outcome that still blocks a trustworthy shadow decision.
