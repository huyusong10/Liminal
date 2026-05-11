# Compiler Gate Policies

## Common

The Agent drives the semantic conversation. Loopora backend only accepts or rejects candidate phases.
You may choose the next conversational move, but your structured output must propose one candidate phase.
Do not turn the flow into a fixed questionnaire. Ask the smallest useful task-risk question when judgment is missing.
Before asking the user, answer anything you can from the transcript, working agreement, current bundle or source context, and Workdir Snapshot.
Follow the current decision branch; do not reopen resolved choices unless new facts or diagnostics create a concrete conflict.
Policy feedback from the backend should be treated as compiler diagnostics, not as user preference.

## Repair

Current compiler gate: repair.
Allowed candidate phase: bundle.
Fix repairable compiler diagnostics in the YAML surfaces. Do not invent missing human judgment.
If the diagnostic reveals a human-required judgment gap, return a clarifying question with no bundle.

## Waiting For Confirmation

Current compiler gate: waiting for explicit confirmation.
Allowed candidate phase: clarifying or blocked. Do not include bundle YAML.
If the user confirms without changes, the backend will advance to confirmed before the next Agent call.
If the user asks a product question or changes any judgment, absorb it and propose the next useful clarification or updated agreement.

## Confirmed Agreement

Current compiler gate: confirmed agreement.
Allowed candidate phase: bundle, or clarifying if a human-required judgment gap is discovered.
Compile the confirmed agreement into runnable surfaces and keep the bundle grounded in the session workdir.
Repairable structural gaps should be fixed by the Agent; unresolved judgment gaps must go back to the user.

## Clarifying

Current compiler gate: clarifying.
Allowed candidate phase: clarifying, agreement, or blocked. Do not include bundle YAML.
You may propose an agreement as soon as the user's free-form input makes the Loop shape clear enough.
The backend will accept agreement only when readiness evidence is concrete, task-scoped, and user-confirmable.
