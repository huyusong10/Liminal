# Bundle Improvement Guide

Use this guide only when the user explicitly asks to improve an existing Loopora bundle, or when Loopora Web starts an alignment session from an imported bundle or run evidence.

This is an optional user-directed capability. Do not present it as a required Loopora lifecycle stage.

## Inputs

An improvement session may include:

- the current bundle YAML
- a source bundle id
- run evidence summaries
- evidence coverage gaps
- a GateKeeper verdict
- the user's critique or desired change

Treat those inputs as context for producing a better complete bundle, not as a separate task result.

## Improvement Discipline

- Read the current bundle before changing it.
- Preserve stable task intent, workdir, executor defaults, and useful role posture unless the feedback conflicts with them.
- Identify the governance surface that should change: `spec`, `roles`, `workflow`, evidence expectations, or GateKeeper strictness.
- Before producing YAML, form a working agreement that names both the preservation policy and the feedback-driven delta.
- If the source Loop used a non-GateKeeper completion mode, treat conversion to evidence-backed GateKeeper task verdicts as an explicit governance delta; do not silently describe that as preserving the source completion behavior.
- Prefer a complete coherent bundle over single-field edits.
- When evidence is present, translate evidence gaps into bundle changes.
- Translate evidence buckets into governance changes: Weak evidence should tighten evidence expectations, Unproven surfaces should update `spec` or Inspector duties, Blocking findings should become guardrails or GateKeeper blockers, and accepted Residual risk should stay visible rather than disappearing into prose.
- Before producing the improved YAML, privately pressure-test the revised candidate against a plausible repeat of the source failure or critique. If the new `spec`, role posture, workflow, handoffs, evidence queries, and GateKeeper rules would not expose, repair, or block that failure, revise the bundle delta or ask one focused question.
- Ask a focused question only when the critique cannot determine the bundle shape.

## Output Discipline

The output is still one runnable Loopora bundle.

The improved bundle must be standalone. Do not write `metadata.source_bundle_id` or `metadata.revision`, and do not reuse the source bundle id as `metadata.bundle_id`; the source bundle, run id, evidence summaries, and critique are temporary inputs for shaping a new candidate, not lineage fields in the candidate.

Do not output a standalone critique, plan, or progress note when Loopora Web is waiting for `bundle_yaml`.
