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
workflow:
  version: 1
  preset: ""
  collaboration_intent: "..."
  roles:
    - id: "builder"
      role_definition_key: "builder"
  steps:
    - id: "builder_step"
      role_id: "builder"
      on_pass: "continue"
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

Use `workflow.collaboration_intent` to capture the high-level execution bias.

## Output rules

- Make the bundle readable first, then runnable.
- Preserve one coherent story across summary, spec, roles, and workflow.
- Do not emit a separate working agreement file.
- Do not emit prose outside the YAML when the user is asking for the final bundle.
