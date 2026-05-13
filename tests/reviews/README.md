# Review Cases

Review cases are opt-in evidence workflows for rendered surfaces and other fuzzy semantic judgments. They are not deterministic contract or journey checks and are not release gates by default.

Use it when a user or reviewer asks for visual quality, semantic language, concept coherence, or Agent-behavior review work. SVG diagrams and Web pages use the same runner and the same case format; they differ only by target type.

## How To Run

List available cases:

```bash
uv run python tests/reviews/run.py --list
```

Run the default rendered-surface review:

```bash
uv run python tests/reviews/run.py --case rendered-surfaces
```

Include Web pages by passing URLs directly:

```bash
uv run python tests/reviews/run.py --case rendered-surfaces --url home=http://127.0.0.1:8000/ --url compose=http://127.0.0.1:8000/loops/new/bundle
```

Or by environment variable:

```bash
LOOPORA_REVIEW_URLS="home=http://127.0.0.1:8000/,compose=http://127.0.0.1:8000/loops/new/bundle" \
  uv run python tests/reviews/run.py --case rendered-surfaces
```

Artifacts are written under `.loopora/reviews/<timestamp>/` and include screenshots, rendered contact sheets, machine hints, and a Markdown report.

## What Counts As Evidence

The runner captures concrete pixels and lightweight machine hints. The final judgment is still human/agent review against the case brief.

Good findings describe rendered user-facing problems:

- text clipped by or touching a containing shape
- arrows, badges, pills, or captions crossing readable content
- controls or labels that collide after scaling
- web panels, nav, cards, or dynamic content that compress into incoherent layouts
- mobile/desktop variants that lose the same semantic hierarchy

Do not put logo assets in this suite. Logo assets can keep ordinary structural tests for parseability, serving, and references, but they do not participate in text/layout visual semantics.
