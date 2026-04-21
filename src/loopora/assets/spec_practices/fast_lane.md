---
summary: "Scenario: a release-blocking invite-link redirect bug needs one Builder hotfix and one fast GateKeeper verdict, not a longer exploratory loop."
---

## Scenario

The release branch is blocked because invited users bounce between login and accept-invite instead of reaching the invitation page. The scope is narrow, the failing path is obvious, and the team only needs one focused Builder hotfix plus one fast GateKeeper verdict.

## Request

Fix the invite-link redirect path and verify the exact hotfix path with direct evidence.

## Why this workflow fits

The scope is narrow and the failure path is explicit. Builder can patch the redirect quickly, GateKeeper can judge the exact path immediately, and a short loop still preserves evidence for the hotfix.

## Example spec

# Task

Fix the invite-link redirect so invited users can sign in once and reach the accept-invite page instead of looping between routes.

# Done When

- Starting from a valid invite link, a signed-out user is sent to login once and then reaches the accept-invite page.
- Starting from the same invite link, a signed-in user reaches the accept-invite page directly.
- A direct reproducible verification confirms the redirect path no longer loops.
- Existing invite tokens, accept-invite behavior, and adjacent auth routes still work.

# Guardrails

- Keep the change scoped to the invite redirect and accept-invite path.
- Do not widen the task into a general auth refactor.
- Preserve existing invite token handling, route names, and adjacent auth behavior.

# Role Notes

## Builder Notes

Optimize for the shortest trustworthy path to a finished hotfix.

## GateKeeper Notes

Require direct evidence, but keep the verdict compact and proportional to the small scope.
