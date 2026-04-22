# Task

Collapse the mixed rollout symptoms into one blocker slice, repair that slice, and leave a triage decision that explains why this round owns it.

# Done When

- The current rollout symptoms are reduced to one blocker slice instead of a grab bag of unrelated fixes.
- Public search traffic no longer surfaces employee-only rollout manuals.
- Employee viewers can still retrieve the internal rollout manuals they need.
- `reports/triage_decision.json` exists and identifies the blocker this round owns.

# Guardrails

- Do not try to solve every rollout symptom in one round.
- Keep the decision anchored to the most severe blocker in `RELEASE_BLOCKER_ORDER`.
- Preserve public help-center and API-doc search behavior while narrowing the blocker.

# Role Notes

## Inspector Notes

Gather evidence across the competing symptoms first, then anchor on the blocker that most threatens a wider rollout.

## Guide Notes

Translate the symptom pile into one blocker slice that this round can own end to end.

## Builder Notes

Repair the chosen blocker cleanly and leave the other symptoms explicitly deferred.

## GateKeeper Notes

Pass only when the blocker is repaired and the triage decision clearly explains why this round chose it.
