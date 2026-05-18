# Alignment Quality Rubric

Use this rubric before presenting a working agreement or producing a bundle.

## Required readiness evidence

For each dimension, write concrete evidence. A bare `true` is not enough.

| Dimension | Good evidence | Weak evidence |
|-----------|---------------|---------------|
| `loop_fit` | Explains why direct Agent work, one review, direct chat / direct answer, one-off task handling, or benchmark/test-harness-only validation is not enough; names the new proof / artifact / handoff / observation / verdict context later rounds will create; and states the repeated judgment, fake-done risk, GateKeeper decision, or run-owned/exportable/auditable contract that makes that evidence worth governing | “It is complex” |
| `task_scope` | Names the deliverable, phase, and intentional non-goals | “Build the thing” |
| `success_surface` | States what the user can observe or run when it succeeds | “It works well” |
| `fake_done_risks` | Names unacceptable shallow outcomes | “Avoid bugs” |
| `evidence_preferences` | Names the proof type the user trusts most | “Need proof” |
| `execution_strategy` | States what later rounds should build, prove, narrow, repair, expand, or deliberately defer first | “Work iteratively” |
| `residual_risk_policy` | States what can remain visible, who or what follow-up / acceptance path owns it, what must fail closed, or why no residual risk is acceptable | “Some risk is fine” |
| `judgment_tradeoffs` | Captures a concrete preference order or contrast: which imperfect result to reject, when speed loses to proof, or when strict blocking beats pragmatic progress | “Balance quality and progress” |
| `local_governance` | States whether project-local governance markers affect this Loop; if `AGENTS.md`, applicable parent `AGENTS.md`, `design/README.md`, `design/`, or `tests/` are relevant, maps them to Builder reading, Inspector / Custom verification, and GateKeeper Weak / Unproven / Blocking treatment without inventing contents | Marker lists with no runtime responsibility |
| `role_posture` | Says how Builder, each Inspector responsibility, Guide, GateKeeper, and Custom reviewers should behave differently for this task when present | “Use three roles” |
| `workflow_shape` | Explains why the chosen order, information flow, final GateKeeper judgment / closure, and early error-exposure path fit this task | “Builder then checker” |
| `workdir_facts` | Lists observed facts supported by the Workdir Snapshot or clearly labels assumptions; when governance markers such as `AGENTS.md`, applicable parent `AGENTS.md`, `design/README.md`, `design/`, or `tests/` exist, explains how roles will read, verify, or gate against them without inventing their contents | Empty, invented facts, or marker lists with no role responsibility |

## Working agreement quality bar

A working agreement is ready only when it includes:

- Loopora fit: why direct Agent work, one review, direct answer / one-off handling, or benchmark/test-harness-only validation is not enough
- why the judgment should be inherited by a run, exported, reused, or audited rather than staying as chat-only advice
- user intent in the user's language
- success criteria that would change implementation behavior
- fake-done states that would block GateKeeper
- evidence preferences that can be executed or inspected
- execution strategy that says which proof, repair, narrowing, expansion, or deferral should guide later rounds before polishing or closure
- residual-risk policy that tells GateKeeper what can remain visible, who or what follow-up / acceptance path owns it, and what must block
- evidence bucket expectations: what should count as Proven, Weak, Unproven, Blocking, or Residual risk for this task
- role posture tradeoffs, not just role names
- workflow rationale, not just workflow order
- where weak evidence, drift, or fake done will be exposed early
- if the workflow is a 5+ role or multi-Builder long chain, why each phase creates a new artifact, proof target, handoff, or review boundary instead of role-zoo complexity
- role-to-role and iteration-to-iteration information flow when the workflow has more than one reviewer or repair pass
- an agreement-to-bundle traceability check: every confirmed judgment item can be mapped to `collaboration_summary`, `spec.markdown` / `# Role Notes`, `role_definitions`, `workflow.collaboration_intent`, step `inputs`, or GateKeeper evidence rules; metadata and loop names do not count
- a private complete-run rehearsal: Builder, Inspector / Custom review, optional Guide repair direction, any second Builder pass, GateKeeper verdict, and user evidence audit can all be followed through explicit handoffs, evidence queries, and evidence buckets
- a private failed-round pressure test: at least one plausible fake-done, weak-proof, drift, or residual-risk failure would be exposed, repaired, or blocked by the proposed `spec`, roles, workflow, handoffs, evidence queries, and GateKeeper rules
- advanced workflow fields, if present, are justified by explicit expert/source compatibility and a concrete risk boundary
- workdir facts or explicit uncertainty
- if project-local governance markers exist, role responsibilities or validation expectations that make Builder / Inspector / Custom / GateKeeper respect those markers
- `open_questions` empty, no-open-questions, or explicit-confirmation-only; unresolved bundle-shaping choices must be asked next

Clarifying turns before the agreement should also pass a user-guidance bar:

- the assistant states a concrete recommended judgment before asking the user to choose
- `decision_options` gives 2-4 concise choices, with one recommended option when a default is appropriate
- the choices use the user's task language rather than exposing YAML, role, or workflow mechanics
- clicking the recommended option would produce a complete enough user reply for the next compiler step
- the question follows the current decision branch instead of restarting a generic checklist
- observable facts from transcript, source context, current bundle, or Workdir Snapshot have been used instead of being asked back to the user
- the question identifies the bundle-shaping consequence: Loopora fit, `spec`, role posture, workflow information flow, advanced workflow fields, or GateKeeper strictness

Use advanced workflow fields only when expert/source compatibility requires them; default bundles should stay linear and express most complexity through role posture, `inputs`, evidence queries, and GateKeeper strictness.

## Bundle quality bar

A bundle is acceptable only when:

Treat this section as quality guidance, not a fixed regex vocabulary. Loopora's hard linter should block missing sections, broken handoffs, missing evidence queries, raw-YAML / metadata violations, unsupported workdir claims, and explicit anti-patterns. It should not reject a strong model's valid bundle only because the prose uses different words for tradeoffs, role posture, evidence preferences, or residual risk.

- `collaboration_summary` tells the readable governance story, including evidence and GateKeeper posture.
- `collaboration_summary` explains how the working agreement projects across `spec`, `roles`, and `workflow`; it must not merely list those surface names.
- every confirmed judgment item has a concrete bundle destination; nothing important exists only in `agreement_summary`, readiness evidence, transcript memory, or private reasoning.
- The bundle projects judgment tradeoffs into final running surfaces: the `spec`, role posture, workflow, or GateKeeper strictness must preserve which imperfect result should be rejected, when proof beats speed, or when blocking beats pragmatic progress.
- `spec.markdown` carries concrete, judgeable Done When checks, observable success surfaces, task contract, fake-done risks, evidence preferences, execution priorities, judgment tradeoffs, and residual-risk policy; Fake Done must name shallow completion shapes, evidence preferences must name proof types rather than only saying “need evidence,” execution priorities must say what to build / prove / repair / narrow / expand / defer first, judgment tradeoffs must preserve concrete preference order, and residual risk must say what can remain visible, who or what follow-up / acceptance path owns it, and what must block or fail closed.
- role definition names are task-specific enough to shape behavior, not bare archetypes or numbered placeholders.
- role prompts tell each role how to act, what to distrust, and what evidence or handoff to produce.
- role prompts match archetype responsibility: Builder builds or modifies, Inspector inspects / reviews / verifies, Guide narrows / redirects / guides repair, GateKeeper judges / blocks / closes, and Custom stays low-permission and specialized. Generic evidence language alone is not enough.
- role prompts use evidence buckets when useful: Builder describes proof it is trying to make Proven, Inspector distinguishes Weak / Unproven / Blocking findings, Guide turns Unproven or Blocking gaps into a repair direction, GateKeeper keeps Residual risk visible, and Custom marks specialized observations without claiming write or finish authority.
- the bundle visibly projects task verdict evidence into all five stable buckets: Proven, Weak, Unproven, Blocking, and Residual risk.
- default alignment bundles use `completion_mode: "gatekeeper"` so task verdicts are evidence-based rather than only lifecycle-based.
- `workflow.collaboration_intent` explains the task-specific judgment order, evidence flow, and final GateKeeper judgment / closure.
- default workflow output is linear; advanced workflow fields are absent unless expert/source compatibility requires them and validation proves why they exist.
- long-chain workflows use linear `workflow.steps`, not nested Loops, dynamic branches, or sub-workflow entities.
- 5+ role or multi-Builder workflows justify every added role through a distinct artifact, proof target, handoff, review responsibility, repair direction, or GateKeeper input.
- multiple Builder roles or Builder steps have task-specific names and phase responsibilities, not `Builder 1` / `Builder 2`; later Builders read prior phase, review, or Guide handoffs when those handoffs shape the next phase.
- complex review or repair steps declare `inputs.iteration_memory` so cross-iteration evidence flow is explicit instead of relying on ambient context.
- Inspector / Custom review steps after Builder name a Builder handoff and query Builder evidence instead of relying on ambient context.
- Builder after Inspector / Custom / benchmark review reads the review handoff when no Guide has narrowed the direction.
- multiple Inspector / Custom review steps name the relevant upstream Builder handoff in `inputs.handoffs_from` and query Builder evidence in `inputs.evidence_query`.
- specialized Inspector / Custom review roles use distinct `role_definition_key` values with responsibility-specific prompt and posture.
- Custom review roles state low-permission or read-only specialized review / advisory responsibility and do not claim workdir writes or final pass/fail authority.
- Guide after review reads review handoffs and queries review evidence before giving repair guidance.
- Builder after Guide reads the Guide handoff before making the next implementation pass.
- any finishing GateKeeper names upstream handoffs and queries relevant evidence from Builder, Inspector, Custom, or Guide steps as applicable.
- finishing GateKeeper reads Inspector / Custom / Guide review handoffs and queries review evidence whenever review happened before final judgment; a final verdict based only on Builder evidence is not enough after review.
- default bundles keep advanced workflow fields out of the main path; complexity should usually live in role posture, `inputs`, evidence queries, and GateKeeper strictness.
- GateKeeper can finish the run only after evidence satisfies the task contract.
- the candidate Loop has survived a private complete-run rehearsal: Builder, Inspector / Custom review, optional Guide repair direction, any second Builder pass, GateKeeper verdict, and user evidence audit are connected by explicit handoffs, evidence queries, and evidence buckets rather than ambient chat memory.
- the candidate Loop has survived a private failed-round pressure test: a plausible shallow completion, weak proof, drift, or unacceptable residual risk would not slip through as a pass.
- user-facing names and prose follow the user's language while Loopora domain terms stay stable.
- a Chinese user's working agreement and readiness evidence are written in Chinese prose, not English prose under Chinese labels.

## Common failure patterns

Reject these patterns:

- generic project-manager wording that could fit any task
- long questionnaire turns that ask for many missing dimensions instead of the next Loop-shaping answer
- naked clarifying questions that ask the user to invent a judgment without a recommended answer or structured choices
- questions that ask the user for project facts already visible in transcript, source context, current bundle, or Workdir Snapshot
- interview loops that reopen resolved branches without a new conflict, diagnostic, or changed user answer
- user-facing choices that expose Loopora internals instead of task-domain tradeoffs
- prompt-pack bundles with long role prose but no evidence path, handoff discipline, or GateKeeper closure
- role-zoo bundles that add reviewers without distinct evidence responsibilities
- loop-script bundles that repeat steps without explaining new evidence or stop conditions
- personality-memory bundles that turn task-scoped judgment into global persona, permanent preferences, or a cross-task user profile
- all posture placed in `spec` while role prompts stay generic
- role prompts that mention evidence but never state the Builder / Inspector / Guide / GateKeeper / Custom responsibility they are supposed to carry
- workflow chosen only because it is the default
- advanced workflow fields present in YAML without explicit expert/source compatibility or a concrete risk boundary
- evidence-first or benchmark-first workflows where Builder does not read the review handoff that was supposed to shape the implementation
- specialized Inspectors named generically as “Inspector 1” and “Inspector 2”
- Custom review steps that bypass the handoff / evidence rules required of Inspector reviewers
- Custom review roles that sound like generic advisers, workdir writers, or final decision makers instead of low-permission specialized reviewers
- adding many roles without distinct evidence responsibilities
- long-chain workflows where extra Builders do not create distinct phase evidence or handoff boundaries
- nested Loop, arbitrary branch, or dynamic DAG language disguised as workflow v1
- GateKeeper relying only on the final Builder in a long chain while skipping earlier phase handoffs or evidence
- finishing GateKeeper steps with no upstream handoff or no evidence query
- finishing GateKeeper steps that skip Inspector / Custom / Guide review handoffs or review evidence
- Inspector or GateKeeper steps reading only handoff prose when durable evidence queries are required
- Guide repair steps that do not query review evidence, or second Builder steps that ignore Guide handoff
- every step receiving all previous context when a focused input policy is needed
- expert controls used as generic timers, cron, webhook-like automation, or implicit Builder repair
- “confirm” treated as enough when the agreement is still vague
- Chinese labels wrapped around English working-agreement evidence
- evidence described as “tests or screenshots” without saying which one should persuade this task
- evidence that is flattened into a generic summary instead of distinguishing Proven, Weak, Unproven, Blocking, and Residual risk
- bundles that mention proof types but never expose the five stable evidence buckets used for the final task verdict
- working-agreement judgments that never leave `agreement_summary`, readiness evidence, transcript memory, or private reasoning
- candidate Loops that were never privately rehearsed end to end, so a later Builder, Guide, GateKeeper, or user audit step depends on ambient chat context instead of handoffs and evidence queries
- candidate Loops that were never pressure-tested against a plausible fake-done or weak-proof future round before confirmation or YAML output
- workdir assumptions stated as facts
- observed stack, framework, test-suite, or build-script claims not supported by the Workdir Snapshot
- bundle prose that repeats unsupported observed workdir claims even when readiness evidence labels the stack unknown
- `AGENTS.md`, applicable parent `AGENTS.md`, `design/`, or `tests/` markers listed as facts but never connected to Builder reading, Inspector / Custom verification, or GateKeeper gating
- unresolved success, evidence, role, residual-risk, or workflow choices hidden inside `open_questions`
