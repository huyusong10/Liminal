---
summary: "Scenario: a new workspace import flow must land across UI, API, and storage, and Builder should push the first end-to-end slice before the rest of the loop judges it."
---

## Scenario

The platform team has already approved a new workspace import flow. Admins should be able to upload a project archive, let the system unpack it into managed storage, and then see the imported workspace in the existing project list.

## Request

Ship the new workspace import path end to end without redesigning the current project list or breaking the existing manual creation flow.

## Why this workflow fits

The target behavior is already clear, so Builder should land a real integration slice first. Inspector can then verify the import path with project evidence, GateKeeper can judge whether existing entry points survived, and Guide only needs to step in if the integration stalls.

## Why not the other workflows

This is not `Inspect First` because the team is not blocked on finding the problem. It is not `Triage First` because the task itself is already well defined. It is also not `Repair Loop`, because we are not entering with the expectation that one implementation pass will immediately need a second repair round.

## Example spec

# Task

Ship the new workspace import flow so admins can upload a project archive, complete the import, and see the imported workspace in the existing project list.

# Done When

- An admin can upload a supported project archive from the existing import entry point.
- The archive is unpacked into managed storage and a new workspace record is created successfully.
- The imported workspace appears in the existing project list with the expected metadata.
- A project-owned check or reproducible local verification proves the full import path works from the updated workspace.
- Existing manual workspace creation and project-list entry points continue to work.

# Guardrails

- Reuse the current project list and import surfaces instead of inventing a parallel flow.
- Preserve existing manual workspace creation and project-list routes.
- Keep the change scoped to the import path and imported workspace visibility.

# Role Notes

## Builder Notes

Move quickly toward a real end-to-end import slice instead of spending the whole round on diagnosis.

## Inspector Notes

Verify archive upload, unpacking, and imported-workspace visibility before looking for secondary polish.

## GateKeeper Notes

Pass only when the import works from the updated workspace and the existing project entry points still behave normally.

## Guide Notes

If progress stalls, narrow the next step to one missing outcome from `Done When`.
