# Core Contract

## 1. Purpose

This document is the compact contract map for Loopora's current product direction.
It does not replace the detailed designs. It exists to keep product language,
runtime behavior, Web surfaces, and tests aligned around the same long-task workflow.

Stable definition:

> Loopora is a local-first platform for composing, running, and observing long-running AI Agent tasks.

Every user-facing path and implementation boundary should serve this workflow:

`compose Loop -> run Loop -> automatic iteration with evidence -> evidence verdict and result`

## 2. Stable Surfaces

Loopora's primary object is a Loop. The file-backed exchange unit is a bundle.
A valid Loop is not a role list or YAML blob; it is the combination of these
runtime input surfaces plus observable evidence output.

| Surface | Stable responsibility | Canonical source |
| --- | --- | --- |
| `spec` | Freeze task scope, success surface, fake-done risks, guardrails, evidence preferences, and residual risk. | Markdown spec snapshot and compiled spec |
| `roles` | Define task-scoped posture for building, inspecting, judging, and guiding. | Role definitions in the bundle and imported assets |
| `workflow` | Define judgment order, bounded fan-out/fan-in, handoffs, information flow, controls, and stop semantics. | Workflow manifest |
| `evidence` | Record what each run proves, fails to prove, and cites as support. | `evidence/ledger.jsonl` plus linked artifacts |
Rules:

- No surface is allowed to become a parallel fact source for another surface.
- Web may hide internal terms on the default path, but every visible conclusion must
  trace back to one of these surfaces.
- Legacy data may remain readable, but it must not be presented as having the same
  evidence quality as new runs.

## 3. Inspection Flow

Core flow inspection should follow this path, in order:

| Stage | Question it must answer | Stable evidence of correctness |
| --- | --- | --- |
| Loop composition | Can the user compose or obtain a Loop through the selected scenario: Web conversation, manual expert composition, or direct bundle import? | Alignment session transcript, bundle preview/import validation, or manually selected `spec / roles / workflow / loop` assets |
| Loop confirmation | Can the user inspect how the Loop controls fake done and weak evidence before running it? | READY projection for bundle paths, or expert views for manual assets |
| Run | Did execution freeze the Loop contract and produce structured handoffs? | Run contract, step context packets, step handoffs |
| Automatic iteration | Did the system advance through roles and workflow because each round produced new evidence, handoff, or verdict context? | Iteration summaries, workflow events, step handoffs |
| Evidence | Can the run answer what was proven and what remains unproven? | Evidence ledger, artifact refs, coverage projection |
| GateKeeper | Did finish require cited evidence rather than model self-report? | GateKeeper verdict envelope and runtime evidence gate |
| Result | Can the user inspect what the run proved, failed to prove, and why it passed or failed? | Evidence summary, verdict context, ledger and artifact links |

This flow is the default audit checklist for large refactors. A change that improves
one stage but disconnects it from the next stage is incomplete.

## 4. Test Alignment

Tests should primarily lock behavior at the governance boundary, not internal helper
shape. The highest-value regression path is:

`Loop composition -> Loop confirmation -> run -> automatic iteration -> evidence ledger -> GateKeeper verdict -> result`

Stable test anchors:

- Use structure, roles, IDs, artifact presence, and status semantics over specific UI copy.
- Assert evidence and verdict references through canonical artifacts, not through raw logs.
- Keep provider-specific tests focused on capability and degradation visibility; provider
  differences must not change the Loop's success contract.
- Keep legacy compatibility tests separate from new-path quality assertions.

## 5. Change Triggers

Update this document when a change alters:

- the four-surface contract,
- the default inspection flow,
- the canonical evidence source,
- GateKeeper finish semantics,
- bundle version metadata,
- or the intended boundary between the user-facing Loop and internal bundles.

Do not update it for wording-only UI changes, small field additions, or provider option
defaults that do not alter the governance contract.
