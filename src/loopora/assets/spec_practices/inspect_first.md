---
summary: "Scenario: after a billing-pipeline handoff, some enterprise tenants now get incomplete invoice archives, but the fault could still live in aggregation, rendering, bundling, or upload."
---

## Scenario

You just inherited a month-end billing pipeline. Finance reports that a small set of large tenants sometimes receive incomplete invoice archives even though the totals still look correct. No one has pinned down whether the gap starts in usage aggregation, invoice rendering, archive bundling, or object-storage upload retries.

## Request

Ground why the invoice archive becomes incomplete, then repair the real cause without turning the work into a broad billing-close rewrite.

## Why this workflow fits

The first missing piece is not another code pass. Inspector needs to pin down the failure shape and evidence chain before Builder touches the pipeline, and GateKeeper should later judge the repair against that same evidence path instead of against a new story.

## Why not the other workflows

This is not `Build First` because the missing piece is trustworthy evidence, not a first working slice. It is not `Triage First` because the problem boundary is already fairly concrete; what is missing is the grounded root cause. It is also not `Repair Loop`, because talking about a second repair pass is premature before the first verified repair target exists.

## Example spec

# Task

Identify the real cause of incomplete invoice archives in the month-end billing pipeline and repair it without changing the existing billing-close contract.

# Done When

- Direct project evidence reproduces or clearly explains why invoice archives are missing files.
- At least one real root cause is verified and repaired, or the remaining blocker is narrowed to one verified gap.
- The same month-end pipeline now produces a complete invoice archive, or leaves only one smaller confirmed residual issue.
- Final validation follows the same evidence path that exposed the problem instead of switching to a different explanation.

# Guardrails

- Do not start a broad billing-close refactor before the evidence chain is grounded.
- Preserve the existing billing-close behavior, archive naming, and outward delivery contract.
- Keep the logs, reports, and intermediate artifacts that explain the issue so later analysis does not restart blind.

# Role Notes

## Inspector Notes

First pin down which tenant class, which close run, and which pipeline artifact first becomes incomplete.

## Builder Notes

Repair only the cause already supported by evidence instead of rewriting aggregation, bundling, and upload handling all at once.

## GateKeeper Notes

Only pass if the same month-end pipeline path is revalidated with a complete invoice archive.

## Guide Notes

If the evidence is still diffuse, narrow the next move to a tighter diagnostic slice instead of recommending a broad cleanup.
