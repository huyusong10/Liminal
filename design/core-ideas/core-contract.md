# Core Contract

## 1. Purpose

This document is the compact contract map for Loopora's current product direction.
It does not replace the detailed designs. It exists to keep product language,
runtime behavior, Web surfaces, and tests aligned around the same governance loop.

Stable definition:

> Loopora is an external task-governance harness for long-running AI Agent work.

Every user-facing path and implementation boundary should serve this loop:

`task input -> aligned loop plan -> run with evidence -> revise the harness from evidence`

## 2. Stable Surfaces

Loopora's user-facing mental model is a loop plan. The file-backed exchange unit is
a bundle. A valid loop plan is not a role list or YAML blob; it is the combination
of these five surfaces.

| Surface | Stable responsibility | Canonical source |
| --- | --- | --- |
| `spec` | Freeze task scope, success surface, fake-done risks, guardrails, evidence preferences, and residual risk. | Markdown spec snapshot and compiled spec |
| `roles` | Define task-scoped posture for building, inspecting, judging, and guiding. | Role definitions in the bundle and imported assets |
| `workflow` | Define judgment order, bounded fan-out/fan-in, handoffs, information flow, controls, and stop semantics. | Workflow manifest |
| `evidence` | Record what each run proves, fails to prove, and cites as support. | `evidence/ledger.jsonl` plus linked artifacts |
| `revision` | Turn run evidence and user feedback into a newer harness, not just another prompt. | Alignment revision session and revised bundle |

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
| New task | Did the user only need to describe the task and choose a workdir? | Web alignment session transcript, workdir, readiness evidence |
| READY plan | Can the user inspect how the plan controls fake done and weak evidence? | Bundle validation, projection summary, `spec / roles / workflow` views |
| Run | Did execution freeze the contract and produce structured handoffs? | Run contract, step context packets, step handoffs |
| Evidence | Can the run answer what was proven and what remains unproven? | Evidence ledger, artifact refs, coverage projection |
| GateKeeper | Did finish require cited evidence rather than model self-report? | GateKeeper verdict envelope and runtime evidence gate |
| Revision | Does feedback revise the harness surface that caused the miss? | Revision source context, revised bundle, lineage metadata |

This flow is the default audit checklist for large refactors. A change that improves
one stage but disconnects it from the next stage is incomplete.

## 4. Test Alignment

Tests should primarily lock behavior at the governance boundary, not internal helper
shape. The highest-value regression path is:

`new task -> READY plan -> run -> evidence ledger -> GateKeeper verdict -> user feedback -> revision -> new run`

Stable test anchors:

- Use structure, roles, IDs, artifact presence, and status semantics over specific UI copy.
- Assert evidence and verdict references through canonical artifacts, not through raw logs.
- Keep provider-specific tests focused on capability and degradation visibility; provider
  differences must not change the loop plan's success contract.
- Keep legacy compatibility tests separate from new-path quality assertions.

## 5. Change Triggers

Update this document when a change alters:

- the five-surface contract,
- the default inspection flow,
- the canonical evidence source,
- GateKeeper finish semantics,
- revision lineage semantics,
- or the intended boundary between user-facing loop plans and internal bundles.

Do not update it for wording-only UI changes, small field additions, or provider option
defaults that do not alter the governance contract.
