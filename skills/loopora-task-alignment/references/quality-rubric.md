# Alignment Quality Rubric

Use this rubric before presenting a working agreement or producing a bundle.

## Required readiness evidence

For each dimension, write concrete evidence. A bare `true` is not enough.

| Dimension | Good evidence | Weak evidence |
|-----------|---------------|---------------|
| `task_scope` | Names the deliverable, phase, and intentional non-goals | “Build the thing” |
| `success_surface` | States what the user can observe or run when it succeeds | “It works well” |
| `fake_done_risks` | Names unacceptable shallow outcomes | “Avoid bugs” |
| `evidence_preferences` | Names the proof type the user trusts most | “Need proof” |
| `role_posture` | Says how Builder, each Inspector responsibility, and GateKeeper should behave differently for this task | “Use three roles” |
| `workflow_shape` | Explains why the chosen order, any parallel inspection group, and information flow fit this task | “Builder then checker” |
| `workdir_facts` | Lists observed facts or clearly labels assumptions | Empty or invented facts |

## Working agreement quality bar

A working agreement is ready only when it includes:

- user intent in the user's language
- success criteria that would change implementation behavior
- fake-done states that would block GateKeeper
- evidence preferences that can be executed or inspected
- role posture tradeoffs, not just role names
- workflow rationale, not just workflow order
- an explicit reason when the workflow chooses parallel inspection or avoids it
- role-to-role and iteration-to-iteration information flow when the workflow has more than one reviewer or repair pass
- if `workflow.controls` exist, the specific error risk each control reduces
- workdir facts or explicit uncertainty

Use bounded parallel inspection when separate evidence responsibilities should inspect the same Builder output without turning the workflow into an arbitrary DAG.

## Bundle quality bar

A bundle is acceptable only when:

- `spec.markdown` carries the task contract, fake-done risks, evidence preferences, and residual risk.
- role prompts tell each role how to act, what to distrust, and what evidence or handoff to produce.
- `workflow.collaboration_intent` explains the task-specific judgment order.
- workflow steps use `parallel_group` only for bounded Inspector / Custom fan-out and use `inputs` when downstream roles should not receive indiscriminate context.
- `workflow.controls` are omitted unless the task has a concrete runtime error risk; when present they call only Inspector, Guide, or GateKeeper roles.
- GateKeeper can finish the run only after evidence satisfies the task contract.
- user-facing prose follows the user's language while Loopora domain terms stay stable.

## Common failure patterns

Reject these patterns:

- generic project-manager wording that could fit any task
- all posture placed in `spec` while role prompts stay generic
- workflow chosen only because it is the default
- parallel Inspectors named generically as “Inspector 1” and “Inspector 2”
- adding many roles without distinct evidence responsibilities
- GateKeeper relying on only the last Inspector when parallel inspection was used
- every step receiving all previous context when a focused input policy is needed
- controls used as generic timers, cron, webhook-like automation, or implicit Builder repair
- “confirm” treated as enough when the agreement is still vague
- evidence described as “tests or screenshots” without saying which one should persuade this task
- workdir assumptions stated as facts
