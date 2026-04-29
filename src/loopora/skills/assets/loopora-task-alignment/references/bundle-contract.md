# Bundle Contract

Use this reference before producing a new bundle or revising an existing one.

## Required output shape

Emit one YAML object with these top-level keys:

```yaml
version: 1
metadata:
  name: "..."
  description: "..."
  revision: 1
collaboration_summary: "..."
loop:
  name: "..."
  workdir: "/absolute/path"
  completion_mode: "gatekeeper"
  executor_kind: "codex"
  executor_mode: "preset"
  command_cli: "codex"
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
    name: "Builder"
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
    command_cli: "codex"
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
    command_cli: "codex"
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
    command_cli: "codex"
    command_args_text: ""
    model: ""
    reasoning_effort: ""
  - key: "gatekeeper"
    name: "GateKeeper"
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
    command_cli: "codex"
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
- `# Task` is required and must contain prose.
- `# Done When` may be omitted for exploratory runs, but when present it must contain at least one top-level `-` bullet.
- `# Success Surface`, `# Fake Done`, and `# Evidence Preferences` are optional, but when present each must contain at least one top-level `-` bullet.
- `# Residual Risk` is optional prose.
- `# Role Notes` is optional, but when present it must use `## <Role Name> Notes` subheadings. Put each role's note under its own second-level heading.
- Do not use legacy headings such as `# Goal`, `# Checks`, or `# Constraints`.

Web alignment bundles must include non-empty `# Success Surface`, `# Fake Done`, and `# Evidence Preferences` sections. These sections remain strongly recommended for external bundles too because they make the collaboration posture visible to the user and GateKeeper.

Use the spec for:
- task framing
- success criteria
- explicit fake-done states
- evidence preferences
- residual-risk stance
- role-specific notes that belong in the task contract

### 2. Role definitions

Use role definitions for task-scoped role posture:
- what this role should emphasize
- how strict or exploratory it should be
- what it should distrust
- what evidence should persuade it

Use `posture_notes` for the task-specific stance.
Keep `archetype` stable and use `prompt_markdown` to express the role’s operating behavior.

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
- If `loop.completion_mode` is `gatekeeper`, the workflow must include a role whose role definition has `archetype: "gatekeeper"` and at least one step for that role with `on_pass: "finish_run"`.
- For fresh implementation bundles where the target is clear enough to build, prefer Builder -> [Contract Inspector + Evidence Inspector] -> GateKeeper.
- Use Inspector -> Builder -> GateKeeper when the first safe change is unclear.
- Use Builder -> [parallel Inspectors] -> Guide -> Builder -> GateKeeper when the task expects a second repair pass.
- Use Benchmark Inspector -> Builder -> Regression Inspector -> GateKeeper when an existing benchmark or contract proof should control the decision.
- `parallel_group` is only for contiguous Inspector / Custom steps. Do not put Builder, Guide, or GateKeeper inside a parallel group.
- Use `inputs.handoffs_from`, `inputs.evidence_query`, and `inputs.iteration_memory` to express information flow when the workflow has multiple review views or repair passes.
- Every workflow role should have task-scoped `posture_notes`; Web alignment treats missing posture notes as a semantic lint failure.

Optional runtime controls:
- `workflow.controls[]` is an advanced error-control mechanism, not a general timer or event automation system.
- Use controls only when the task has a concrete long-run risk: no evidence progress, role timeout/failure, or repeated GateKeeper rejection.
- `when.signal` may only be `no_evidence_progress`, `role_timeout`, `step_failed`, or `gatekeeper_rejected`.
- `call.role_id` must point to an existing Inspector, Guide, or GateKeeper role. Never use controls to call Builder or write directly to the workdir.
- `mode` may only be `advisory`, `blocking`, or `repair_guidance`; `max_fires_per_run` should normally be `1`.
- If you add a control, the surrounding `collaboration_intent`, spec evidence preferences, or role posture must make clear what error risk it controls. Do not add generic “periodic check” controls.

## Output rules

- Make the bundle readable first, then runnable.
- Preserve one coherent story across summary, spec, roles, and workflow.
- Match the user's natural language in prose fields while preserving Loopora terms such as `spec`, `roles`, `workflow`, `bundle`, `Builder`, `Inspector`, `GateKeeper`, `Guide`, `workdir`, and `READY`.
- Do not translate YAML keys, role archetypes, or required spec headings.
- Do not emit a separate working agreement file.
- Do not emit prose outside the YAML when the user is asking for the final bundle.
