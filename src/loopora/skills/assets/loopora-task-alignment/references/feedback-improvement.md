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
- Prefer a complete coherent bundle over single-field edits.
- When evidence is present, translate evidence gaps into bundle changes.
- Ask a focused question only when the critique cannot determine the bundle shape.

## Output Discipline

The output is still one runnable Loopora bundle.

Do not output a standalone critique, plan, or progress note when Loopora Web is waiting for `bundle_yaml`.
