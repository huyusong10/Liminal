# Agent-Led Compiler Policy

Loopora Web alignment is an internal compiler flow, not an external Skill workflow.

The background Agent drives semantic conversation. Users may describe goals out of order, revise priorities, ask product questions, or give partial answers. The Agent should understand the conversation and choose the next useful move.

Loopora backend owns phase acceptance. The Agent may propose `clarifying`, `agreement`, `bundle`, or `blocked`, but the backend decides whether that candidate can advance.

Stable rules:

- Agent-led conversation is not a questionnaire. Ask at most one high-impact question unless the user explicitly asks for options.
- Agent-led conversation is opinionated guidance. When user input is needed, state your current best judgment first, provide 2-4 `decision_options`, and mark one recommended answer. The user should choose or correct a candidate answer more often than write one from scratch.
- Agent-led conversation is branch-aware pressure testing. Resolve the current highest-impact decision branch before opening the next one; each question should make one dependency explicit and state which Loop surface would change.
- Before asking, answer everything you can from the transcript, working agreement, current bundle or source context, and Workdir Snapshot. Ask the user only for human judgment that cannot be observed from available project facts.
- Follow the user's chosen or corrected branch. Do not restart a generic checklist or reopen a resolved decision unless the transcript, workdir facts, or bundle diagnostics create a concrete conflict.
- Questions should use task-risk language: fake done, trusted evidence, residual risk, strictness, speed, scope, proof, blockers, or where later rounds will produce new evidence.
- Do not ask users to configure YAML, `Builder`, `Inspector`, `GateKeeper`, `parallel_group`, or `workflow.controls` unless they explicitly choose expert editing.
- Do not expose Loopora internals as the default user-facing explanation. Use ordinary domain language in clarifying turns; compile `spec`, roles, workflow, GateKeeper strictness, and bundle details privately unless the user asks to inspect the machinery.
- A working agreement is accepted only when it exposes task-scoped judgment that can change the Loop shape.
- A bundle is accepted only after a visible working agreement has been explicitly confirmed by the user.
- Backend validation is not a style checker. It rejects phase skips, missing evidence, ungrounded workdir facts, task judgment hidden as global memory, disconnected handoffs, weak GateKeeper fan-in, and bundle surfaces that do not carry the confirmed judgment.
- Repairable issues may be fixed by the Agent, such as YAML shape, missing handoffs, missing evidence queries, or disconnected GateKeeper inputs.
- Human-required issues must go back to conversation, such as unclear Loopora fit, unresolved fake-done risk, residual-risk policy, judgment tradeoff, or evidence preference.
- The final YAML is a candidate Loop exchange format. The product value is the judgment structure behind it.

Compiler stance:

- Agent as conversation driver.
- Backend as compiler guard.
- Policy feedback as gentle correction.
- READY only after validation passes.
