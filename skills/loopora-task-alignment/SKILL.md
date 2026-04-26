---
name: loopora-task-alignment
description: Turn a user’s concrete task into a Loopora YAML bundle through dialogue. Use when an external agent needs to interview the user, clarify tradeoffs, build a transient working agreement, and output a single runnable bundle that encodes collaboration posture across spec, role definitions, and workflow. Also use when revising an existing bundle from vague feedback such as “不够重视重构” or “太保守了”.
---

# Loopora Task Alignment

Interview the user about the current task, not about their permanent persona.

Treat the job as task-scoped alignment:
- understand the work the user wants done
- surface the key collaboration tradeoffs for this task
- form a transient working agreement
- confirm that agreement explicitly
- output one YAML bundle only

Read [references/bundle-contract.md](references/bundle-contract.md) before producing or revising a bundle.
Read [references/feedback-revision.md](references/feedback-revision.md) when the user is revising an existing bundle from critique or vague feedback.

## Workflow

### 1. Frame the task

Start from the task the user wants to run in Loopora.

Clarify only what changes the bundle shape:
- what work is actually being attempted
- what “done” should feel like here
- what kind of fake progress the user is trying to avoid
- where the user expects caution versus speed

Do not ask the user to describe their global personality.

### 2. Drive alignment through dialogue

Use short dialogue rounds, not questionnaires.

Prefer a mix of:
- principle questions: “这次你更怕做慢，还是更怕做糙？”
- case questions: “功能到了但结构很脆，你要先补重构还是先交证据？”
- contrast questions: “这次你希望 GateKeeper 更像严格签字人，还是务实推进者？”

Ask only a few questions at a time.
Stop asking only when the task shape, success surface, fake-done risks, evidence preference, role posture, and workflow shape are all clear enough to affect a runnable bundle.

### 3. Build a transient working agreement

Before writing YAML, summarize your current understanding in plain language and ask the user to confirm it.

The working agreement must capture:
- what this task is trying to accomplish
- what counts as success
- what kinds of fake done are unacceptable
- what evidence the user trusts most
- how the main roles should behave on this task
- what workflow shape follows from those preferences

Explicit confirmation is necessary but not sufficient. If the confirmation still leaves a major bundle-shaping choice ambiguous, ask the next focused question instead of producing YAML.

Do not turn the working agreement into a standalone runtime artifact.
It is only a transient alignment checkpoint before bundle generation.
When running inside Loopora Web, the service tracks whether this agreement was confirmed. Do not output YAML until that backend-confirmed stage is active.

### 4. Compile the bundle holistically

After explicit confirmation, compile one YAML bundle that jointly carries collaboration posture through:
- `spec`
- `role_definitions`
- `workflow`

Do not treat posture as spec-only.
Do not revise only one surface when the change clearly affects the others.
For implementation tasks, default to a Builder -> Inspector -> GateKeeper flow unless the user’s task clearly needs a different shape. GateKeeper-mode bundles must include a GateKeeper step that can finish the run.

### 5. Output discipline

Once the user confirms and you are ready to deliver:
- output YAML only
- do not add prose before or after the YAML
- do not mutate Loopora directly
- do not output a separate working agreement file

If the user has not confirmed the agreement yet, keep the conversation in alignment mode instead of emitting premature YAML.

## Creation Mode

Use this mode when the user starts from a task or idea.

Aim to discover:
- task shape
- success surface
- evidence preference
- fake-done risks
- role posture
- workflow bias

Then compile a fresh bundle.

## Revision Mode

Use this mode when the user provides:
- an existing bundle
- run feedback
- vague critique
- a statement that “this still doesn’t feel right”

Interpret critique against the whole prior bundle.
Default to revising the bundle holistically instead of editing one field in isolation.

Ask a follow-up question only when the critique is genuinely ambiguous after reading the existing bundle and the feedback.

## Guardrails

- Keep the dialogue task-scoped.
- Match the user's natural language for user-facing dialogue, working agreement prose, `collaboration_summary`, `spec.markdown` prose, role descriptions, `posture_notes`, and `workflow.collaboration_intent`.
- Preserve Loopora domain terms exactly: `spec`, `roles`, `workflow`, `bundle`, `Builder`, `Inspector`, `GateKeeper`, `Guide`, `workdir`, and `READY`.
- Do not translate YAML keys, role archetypes, or required spec headings such as `# Task`, `# Done When`, `# Success Surface`, `# Fake Done`, `# Evidence Preferences`, and `# Role Notes`.
- Preserve concrete user phrases when they help the bundle feel like the user’s own intent.
- Prefer the smallest number of questions that still changes the bundle meaningfully; do not compress away questions that determine success criteria or fake-done risks.
- When revising, preserve stable parts of the prior bundle unless the new feedback conflicts with them.
- Never output JSON, markdown wrappers, or explanatory prose when the requested final artifact is the bundle.
