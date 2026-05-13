# Public Diagram Assets

SVG diagrams in this directory are public documentation assets. They should explain stable Loopora principles and reader mental models, not private product mechanics.

Current canonical diagrams:

| File family | Purpose |
| --- | --- |
| `first-run-path.*.svg` | Shows the README-first path: start from the Coding Agent, preview in Web, then run with evidence flowing into one local record. |
| `bundle-judgment-structure.*.svg` | Shows the README technical overview: the Bundle surfaces that make task-local judgment runnable across rounds. |
| `loopora-position.*.svg` | Places Loopora outside the Agent as the running structure that keeps human judgment active across rounds. |
| `error-propagation.*.svg` | Shows how an unguided loop can turn an early proxy goal into a convincing but unsafe completion story. |
| `refund-evidence-loop.*.svg` | Uses the refund case to show the stable run pattern: output, evidence accounting, decision, and narrowed next action. |
| `judgment-surfaces.*.svg` | Shows how human wording becomes user-understandable running surfaces: task contract, execution posture, evidence path, and decision rule. |

Concrete examples are allowed only when they carry a durable idea for the public article. Do not use diagrams for volatile UI paths, onboarding steps, per-task role sequences, or implementation internals.

Style contract:

- Every diagram must remain a self-contained, parseable SVG with `role="img"`, `<title>`, and `<desc>`.
- Use a neutral, high-contrast palette that can sit inside README/docs pages without inheriting a particular app theme.
- Avoid fragile typography such as negative tracking or non-standard ad-hoc weight values; the exact copy may change, but the diagram should stay legible when scaled down in Markdown.
- Rendered layout quality is reviewed through the shared opt-in review suite in `tests/reviews/`, not through deterministic contract or journey checks.
