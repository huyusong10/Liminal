# Diagram Assets

SVG diagrams in this directory should describe stable Loopora principles, not product-specific flows.

Use SVG for durable ideas such as human-shaped Loop, judgment compilation, error deceleration, autonomy factors, and alignment revealing tacit judgment.

Keep concrete workflows, examples, onboarding steps, UI paths, and task-specific role sequences in text. Those details are expected to evolve, and text is easier to maintain than diagram assets.

Style contract:

- Every diagram must remain a self-contained, parseable SVG with `role="img"`, `<title>`, and `<desc>`.
- Use a neutral, high-contrast palette that can sit inside README/docs pages without inheriting a specific app theme.
- Avoid fragile typography such as negative tracking or non-standard ad-hoc weight values; the exact copy may change, but the diagram should stay legible when scaled down in Markdown.
- Rendered layout quality is reviewed through the shared opt-in review suite in `tests/reviews/`, not through deterministic contract or journey checks.
