# Bundle Contract

Use this reference before producing a new bundle or revising an existing one.

## Required output shape

Emit one YAML object with these top-level keys:

```yaml
version: 1
metadata:
  name: "..."
  description: "..."
collaboration_summary: "..."
loop:
  name: "..."
  workdir: "/absolute/path"
  completion_mode: "gatekeeper"
  executor_kind: "codex"
  executor_mode: "preset"
  command_cli: ""
  command_args_text: ""
  model: ""
  reasoning_effort: ""
  iteration_interval_seconds: 0
  max_iters: 8
  max_role_retries: 2
  delta_threshold: 0.005
  trigger_window: 4
  regression_window: 2
spec:
  markdown: |
    # Task
    ...
role_definitions:
  - key: "builder"
    name: "Focused Builder"
    description: "..."
    archetype: "builder"
    prompt_ref: "builder.md"
    prompt_markdown: |
      ---
      version: 1
      archetype: builder
      ---
      ...
    posture_notes: "..."
    executor_kind: "codex"
    executor_mode: "preset"
    command_cli: ""
    command_args_text: ""
    model: ""
    reasoning_effort: ""
  - key: "contract-inspector"
    name: "Contract Inspector"
    description: "..."
    archetype: "inspector"
    prompt_ref: "inspector.md"
    prompt_markdown: |
      ---
      version: 1
      archetype: inspector
      ---
      ...
    posture_notes: "..."
    executor_kind: "codex"
    executor_mode: "preset"
    command_cli: ""
    command_args_text: ""
    model: ""
    reasoning_effort: ""
  - key: "evidence-inspector"
    name: "Evidence Inspector"
    description: "..."
    archetype: "inspector"
    prompt_ref: "inspector.md"
    prompt_markdown: |
      ---
      version: 1
      archetype: inspector
      ---
      ...
    posture_notes: "..."
    executor_kind: "codex"
    executor_mode: "preset"
    command_cli: ""
    command_args_text: ""
    model: ""
    reasoning_effort: ""
  - key: "gatekeeper"
    name: "Conservative GateKeeper"
    description: "..."
    archetype: "gatekeeper"
    prompt_ref: "gatekeeper.md"
    prompt_markdown: |
      ---
      version: 1
      archetype: gatekeeper
      ---
      ...
    posture_notes: "..."
    executor_kind: "codex"
    executor_mode: "preset"
    command_cli: ""
    command_args_text: ""
    model: ""
    reasoning_effort: ""
workflow:
  version: 1
  preset: ""
  collaboration_intent: "..."
  roles:
    - id: "builder"
      role_definition_key: "builder"
    - id: "contract_inspector"
      role_definition_key: "contract-inspector"
    - id: "evidence_inspector"
      role_definition_key: "evidence-inspector"
    - id: "gatekeeper"
      role_definition_key: "gatekeeper"
  steps:
    - id: "builder_step"
      role_id: "builder"
      on_pass: "continue"
    - id: "contract_inspection_step"
      role_id: "contract_inspector"
      parallel_group: "inspection_pack"
      inputs:
        handoffs_from: ["builder_step"]
        evidence_query:
          archetypes: ["builder"]
          limit: 12
        iteration_memory: "summary_only"
      on_pass: "continue"
    - id: "evidence_inspection_step"
      role_id: "evidence_inspector"
      parallel_group: "inspection_pack"
      inputs:
        handoffs_from: ["builder_step"]
        evidence_query:
          archetypes: ["builder"]
          limit: 12
        iteration_memory: "summary_only"
      on_pass: "continue"
    - id: "gatekeeper_step"
      role_id: "gatekeeper"
      inputs:
        handoffs_from: ["contract_inspection_step", "evidence_inspection_step"]
        evidence_query:
          archetypes: ["builder", "inspector"]
          limit: 24
      on_pass: "finish_run"
```

The final artifact must be a raw YAML document. Do not put it in a markdown code fence, do not prefix it with an explanation or comment, and do not append a summary or import instructions after it. The first non-empty line should be `version: 1`.

Generated bundle metadata must describe one standalone candidate. Do not set `metadata.source_bundle_id` or `metadata.revision`; source bundle / run context is temporary dialogue input, not system-level lineage.

When Loopora Web or the user provides target executor settings, copy the same executor fields into `loop` and every `role_definitions[]` entry unless the user explicitly asks for expert per-role overrides. A bundle that silently switches from command/custom executor settings back to a preset executor will not run under the selected runtime.

## Posture mapping

`collaboration posture` must be carried jointly across three surfaces.

### 1. Spec

Use `spec.markdown` to encode the task contract.

Prefer including these sections when they matter:
- `# Task`
- `# Done When`
- `# Guardrails`
- `# Success Surface`
- `# Fake Done`
- `# Evidence Preferences`
- `# Residual Risk`
- `# Role Notes`

Loopora compiles `spec.markdown` before a bundle can be imported. Obey these
format rules exactly:
- `# Task` is required and must contain concrete task prose, not generic placeholders such as "requested behavior", "do the task", or "the alignment agreement".
- `# Done When` may be omitted for exploratory runs, but when present it must contain at least one top-level `-` bullet.
- `# Success Surface`, `# Fake Done`, and `# Evidence Preferences` are optional for manually imported bundles, but when present each must contain at least one top-level `-` bullet.
- `# Residual Risk` is optional prose for manually imported bundles. When a generated or reviewed bundle accepts any residual risk, name what may remain plus the owner, follow-up, or acceptance path; otherwise say the task fails closed.
- `# Role Notes` is optional, but when present it must use `## <Role Name> Notes` subheadings. Put each role's note under its own second-level heading.
- Do not use legacy headings such as `# Goal`, `# Checks`, or `# Constraints`.

Web alignment bundles must name the concrete user-facing task in `# Task` and include non-empty `# Done When`, `# Success Surface`, `# Fake Done`, `# Evidence Preferences`, and `# Residual Risk` sections. These sections remain strongly recommended for external bundles too because they make the collaboration posture visible to the user and GateKeeper.

Use the spec for:
- task framing
- success criteria
- explicit fake-done states
- evidence preferences
- execution priorities or deliberate deferrals
- residual-risk stance
- task-level judgment tradeoffs
- project-local governance obligations when they affect the task contract
- role-specific notes that belong in the task contract

Do not use the bundle as personality memory. If the user names a preference, compile only the preference that changes this task's success surface, evidence expectations, role posture, or workflow. Do not turn it into a global persona, permanent preference, or cross-task user profile.

Write evidence expectations so the run result can separate lifecycle status from task verdict. The final evidence projection should be able to classify important claims as Proven, Weak, Unproven, Blocking, or Residual risk instead of collapsing them into one narrative summary. Web alignment bundles must make that bucket projection visible somewhere in the governance prose.

If the Workdir Snapshot shows project-local governance markers such as `AGENTS.md`, applicable parent `AGENTS.md`, `design/README.md`, `design/`, or `tests/`, do not claim their contents unless observed. Mention their existence only as an obligation or evidence path: Builder should read applicable project-local rules and design, Inspector / Custom review should verify relevant design or test contracts, and GateKeeper should treat skipped project rules or missing expected validation as Weak, Unproven, or Blocking according to the task.

### 2. Role definitions

Use role definitions for task-scoped role posture:
- what this role should emphasize
- how strict or exploratory it should be
- what it should distrust
- what evidence should persuade it
- which evidence bucket it should produce or protect: Proven, Weak, Unproven, Blocking, or Residual risk

Use `posture_notes` for the task-specific stance.
Keep `archetype` stable and use `prompt_markdown` to express the role’s operating behavior.
The role prompt / posture must match the archetype responsibility. Builder must describe construction or implementation responsibility, Inspector must describe inspection / review / verification responsibility, Guide must describe narrowing, redirection, or repair-guidance responsibility, and GateKeeper must describe final judgment, blocking, or closure responsibility. Evidence language alone is not enough if the same sentence could be pasted into every role.

### 3. Workflow

Use workflow for execution shape:
- role ordering
- who goes first
- whether evidence comes before implementation
- where Guide intervenes
- whether the loop is tightly gated or more exploratory
- whether bounded parallel inspection is needed
- what upstream handoffs, evidence, and iteration memory each step should see

Use `workflow.collaboration_intent` to capture the high-level execution bias.

Runtime invariant:
- Default Web compiler bundles should set `loop.completion_mode` to `gatekeeper` so task verdicts come from evidence and GateKeeper judgment rather than run lifecycle completion.
- `loop.completion_mode` only supports `gatekeeper` and `rounds`; do not emit unknown, boolean, or numeric modes.
- `loop.executor_kind` / `loop.executor_mode` must use the same supported executor contract as normal Loop creation; custom executors require command mode and valid command arguments.
- If a role omits executor fields, Loopora Core treats it as inheriting the normalized loop executor defaults; prefer emitting the fields explicitly for generated bundles so the selected runtime is visible before import.
- In `gatekeeper` mode, the workflow must include a role whose role definition has `archetype: "gatekeeper"` and at least one step for that role with `on_pass: "finish_run"`.
- For fresh implementation bundles where the target is clear enough to build, prefer Builder -> [Contract Inspector + Evidence Inspector] -> GateKeeper.
- Use Inspector -> Builder -> GateKeeper when the first safe change is unclear.
- Use Builder -> [parallel Inspectors / Custom reviewers] -> Guide -> Builder -> GateKeeper when the task expects a second repair pass.
- Use Benchmark Inspector -> Builder -> Regression Inspector -> GateKeeper when an existing benchmark or contract proof should control the decision.
- Use a long-chain phase workflow when the task has multiple evidence-bearing stages that would otherwise be hidden inside one oversized Builder prompt. A 5+ role or step chain is acceptable when every added role produces a distinct artifact, proof target, handoff, review responsibility, repair direction, or GateKeeper input.
- Long-chain workflows are still one linear `workflow.steps` sequence in version 1. Do not emit nested Loops, arbitrary branch syntax, dynamic DAGs, or sub-workflow entities.
- Multiple Builder roles or Builder steps must be task-specific, such as API Builder, UI Builder, Migration Builder, Repair Builder, or Evidence Hardening Builder. Do not use `Builder 1` / `Builder 2`, and do not split a single continuous implementation into multiple Builders unless the split creates a clearer evidence boundary.
- `parallel_group` is only for contiguous Inspector / Custom steps. Do not put Builder, Guide, or GateKeeper inside a parallel group.
- If the workflow uses `parallel_group`, `workflow.collaboration_intent` must explain why bounded parallel or independent inspection fits this task.
- `workflow.collaboration_intent` must also explain where weak evidence, drift, or fake done is exposed early. A role order that only says Builder then Inspector then GateKeeper is not yet human-shaped.
- Use `inputs.handoffs_from`, `inputs.evidence_query`, and `inputs.iteration_memory` to express information flow when the workflow has multiple review views or repair passes.
- Parallel Inspector / Custom review steps must name the same upstream Builder handoff through `inputs.handoffs_from` so independent reviewers inspect the same artifact from different evidence responsibilities.
- Parallel Inspector / Custom review steps must query Builder evidence through `inputs.evidence_query` so each review can inspect durable proof, not only a prose handoff.
- Parallel Inspector / Custom review steps must declare `inputs.iteration_memory`, usually `summary_only`, so the next run iteration has an explicit memory policy instead of relying on ambient context.
- Custom review role prompts and posture must state their low-permission or read-only specialized review / advisory responsibility. A Custom reviewer must not imply it can write the workdir or make the final pass/fail decision.
- A non-parallel Inspector / Custom review step that runs after a Builder must still name a Builder handoff and query Builder evidence; otherwise the review is relying on ambient context.
- A Builder step that runs after Inspector / Custom / benchmark review and before any Guide must name the review handoff, otherwise the evidence-first or benchmark-first workflow is only a visual order.
- A Builder step that runs after Inspector / Custom / benchmark review and before any Guide must declare `inputs.iteration_memory` so the evidence-first repair pass does not rely on ambient context.
- A Builder step that runs after another Builder step should either name the prior phase handoff or be separated by Inspector / Custom / Guide evidence that it explicitly reads. If it does neither, the long-chain split probably belongs in one Builder step.
- Parallel specialized Inspectors must use distinct task-scoped `role_definition_key` values so each evidence responsibility has its own prompt and posture; copying the same Inspector prompt under two keys is not enough.
- A Guide step that runs after Inspector / Custom review must name those review handoffs and query review evidence before producing repair guidance.
- A Guide step that runs after Inspector / Custom review must declare `inputs.iteration_memory`, usually `summary_only`, so repair guidance can cite prior iteration evidence explicitly.
- A Builder step that runs after Guide must name the Guide handoff so the next implementation pass follows the narrowed repair direction instead of ambient context.
- A Builder step that runs after Guide must declare `inputs.iteration_memory`, often `same_step` or `summary_only`, so the repair pass does not depend on implicit chat memory.
- Any finishing GateKeeper step must name upstream handoffs through `inputs.handoffs_from` and query relevant evidence through `inputs.evidence_query`; final judgment cannot rely only on the GateKeeper prompt.
- If Inspector, Custom, or Guide review / correction steps run before a finishing GateKeeper, that GateKeeper must read those review handoffs and query their evidence. Do not let the final verdict look only at Builder evidence after review has happened.
- In a long-chain workflow, the finishing GateKeeper must read the critical phase handoffs, not only the final Builder handoff. It should query Builder, Inspector, Custom, and Guide evidence as applicable so the final verdict can explain which phase claims are Proven, Weak, Unproven, Blocking, or Residual risk.
- When a GateKeeper finishes after a parallel inspection group, its `inputs.handoffs_from` must name every parallel Inspector / Custom review step id, not only the last review or a generic Inspector label.
- A finishing GateKeeper after parallel inspection must query Builder, Inspector, and Custom evidence as applicable through `inputs.evidence_query`.
- Every workflow role must have task-scoped `name` and `posture_notes`; Web alignment treats bare names like `Builder`, `Inspector`, `GateKeeper`, or numbered names like `Inspector 1` as semantic lint failures.

Optional runtime controls:
- `workflow.controls[]` is an advanced error-control mechanism, not a general timer or event automation system.
- Use controls only when the task has a concrete long-run risk: no evidence progress, role timeout/failure, or repeated GateKeeper rejection.
- `when.signal` may only be `no_evidence_progress`, `role_timeout`, `step_failed`, or `gatekeeper_rejected`.
- `call.role_id` must point to an existing Inspector, Guide, or GateKeeper role. Never use controls to call Builder or write directly to the workdir.
- `mode` may only be `advisory`, `blocking`, or `repair_guidance`; `max_fires_per_run` should normally be `1`.
- If you add a control, the surrounding `collaboration_intent`, spec evidence preferences, or role posture must make clear what error risk it controls. Do not add generic “periodic check” controls.

## Output rules

- Make the bundle readable first, then runnable.
- Produce a bundle only after Loopora fit is established; do not use YAML to force direct Agent work, one-review tasks, direct-answer / one-off tasks, or benchmark/test-harness-only work into a governed Loop.
- Before emitting YAML, privately rehearse one complete intended run path: Builder output and handoff, Inspector / Custom review evidence, optional Guide repair direction, any second Builder pass, GateKeeper evidence-backed verdict, and the user's evidence audit. If any step depends on ambient chat context instead of explicit `inputs.handoffs_from`, `inputs.evidence_query`, role posture, or evidence buckets, revise the bundle or ask one focused question before producing YAML.
- Before emitting YAML, privately pressure-test the candidate Loop with one plausible future failure: a shallow completion, weak proof, drift, missing coverage, or unacceptable residual risk. If the `spec`, role posture, workflow, handoffs, evidence queries, and GateKeeper rules would not expose, repair, or block it, revise those surfaces or ask another focused question before producing the bundle.
- Project the working agreement into all governance surfaces: `collaboration_summary` tells why this task needs multi-round Loopora governance and how future human proof demands, user-facing rejection criteria, correction roles, execution priorities, local-governance responsibilities, timing / stop decisions, strict-vs-pragmatic closure choices, and durable proof expectations become `spec`, `roles`, and `workflow`; it must describe that mapping, not merely list the surface names. `spec.markdown` carries concrete task scope / success / fake-done / evidence / residual-risk policy / execution priorities / judgment tradeoffs; `spec.markdown` `# Role Notes` or `role_definitions` carry Builder / Inspector / Guide / GateKeeper / Custom posture, role-level tradeoffs, and project-local governance responsibilities when those archetypes or markers are used; and `workflow.collaboration_intent` plus step `inputs` and workflow controls carry judgment order, build/prove/repair/narrow/expand/defer priorities, local-governance checkpoints, closure choices, error exposure, and evidence flow.
- Run an agreement-to-bundle traceability checklist before final YAML: every confirmed judgment item must land in `collaboration_summary`, `spec.markdown` / `# Role Notes`, `role_definitions[].prompt_markdown` / `posture_notes`, `workflow.collaboration_intent`, step `inputs`, workflow controls, or GateKeeper evidence rules. Metadata and loop names are not enough. If the only copy of a judgment is in `agreement_summary`, readiness evidence, transcript memory, metadata / loop names, or private reasoning, the bundle is not complete.
- Make it clear how GateKeeper should distinguish Proven, Weak, Unproven, Blocking, and Residual risk evidence. A bundle that lets a normal run status masquerade as task proof is not aligned with Loopora's verdict contract.
- Preserve one coherent story across summary, spec, roles, and workflow.
- Keep workdir grounding consistent across readiness evidence and final YAML. Bundle prose may use the user's requested stack, but it must not say the Workdir Snapshot observed a framework, test suite, or build capability unless snapshot markers support that claim.
- Match the user's natural language in user-facing names and prose fields while preserving Loopora terms such as `spec`, `roles`, `workflow`, `bundle`, `Builder`, `Inspector`, `GateKeeper`, `Guide`, `Custom`, `workdir`, and `READY`. For Chinese tasks, `metadata.name`, `metadata.description`, `loop.name`, and `role_definitions[].name` should contain Chinese semantics instead of generic English labels.
- Do not translate YAML keys, role archetypes, or required spec headings.
- Do not emit a separate working agreement file.
- Do not emit prose outside the YAML when the user is asking for the final bundle.
