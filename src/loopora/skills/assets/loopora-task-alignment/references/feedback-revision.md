# Feedback Revision Guide

Use this reference when revising an existing bundle from user critique or vague feedback.

## Core rule

Treat critique as a bundle-level revision signal, not as a direct workflow patch.

Revise the whole bundle where needed:
- `spec`
- `role_definitions`
- `workflow`

Do not assume every complaint maps to only one field.

## Revision process

1. Read the prior bundle.
2. Read the user’s critique.
3. Identify which collaboration judgment changed.
4. Update all affected surfaces.
5. Present the revised working agreement if the change is material.
6. Output the revised YAML bundle only after confirmation.

## Common vague critiques

### “不够重视重构”

Possible meaning:
- success criteria underweight maintainability
- fake-done states do not call out surface-only fixes
- Builder posture is too delivery-first
- GateKeeper posture is too tolerant of structural debt
- workflow reaches GateKeeper too quickly

Typical revision directions:
- strengthen `# Success Surface`
- add stronger `# Fake Done` bullets
- increase Builder or GateKeeper posture strictness
- make the workflow collect more evidence before sign-off

### “太偷懒了”

Possible meaning:
- verification depth was too shallow
- the bundle accepted surface fixes
- role posture prioritized speed too strongly
- workflow ended before enough evidence was gathered

Typical revision directions:
- raise evidence expectations
- clarify fake-done states
- tighten Inspector or GateKeeper posture
- add or reposition an inspection step

### “太保守了”

Possible meaning:
- residual-risk tolerance is lower than the user wants
- GateKeeper posture is too strict
- workflow inserts too many validation checkpoints

Typical revision directions:
- soften `# Residual Risk`
- relax GateKeeper posture
- simplify the workflow where appropriate

## When to ask a clarifying question

Ask a follow-up only when the critique stays ambiguous after reading the prior bundle.

Good follow-up shape:
- offer 2 to 3 concrete interpretations
- ask which one matches
- avoid reopening the whole interview

Example:

“当你说这次太偷懒了，你更在意的是没补结构、没补验证，还是只是把表面症状糊过去了？”

## Preservation rule

When revising:
- preserve stable bundle sections unless the new critique conflicts with them
- keep the user’s original task framing when still valid
- change only what the critique actually reorients
