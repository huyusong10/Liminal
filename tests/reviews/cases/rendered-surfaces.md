---
id: rendered-surfaces
title: Rendered Surface Reading Quality
targets:
  - id: docs-diagrams
    type: svg_directory
    title: Documentation diagrams
    path: docs/assets/diagrams
  - id: operator-web-pages
    type: web_urls
    title: Web pages supplied by the operator
    optional: true
    urls_env: LOOPORA_REVIEW_URLS
    viewports:
      - name: desktop
        width: 1440
        height: 1000
      - name: narrow
        width: 390
        height: 844
---

Review rendered Loopora surfaces as a reader would see them. This case intentionally covers both static SVG diagrams and live Web pages with one shared visual semantics workflow.

Look for:

- Text that is clipped, too close to a card boundary, or visibly forced into a box that was designed for shorter copy.
- Arrows, connector lines, pills, captions, badges, or status chips crossing labels or occupying the same visual lane as surrounding content.
- Bottom captions or summary statements colliding with nearby panels, chips, or legends.
- Dense cards, controls, or page chrome that lose readable hierarchy after viewport scaling.
- Bilingual variants where one language fits but the other no longer has enough layout budget.

Logo assets are explicitly out of scope for this case.
