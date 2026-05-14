---
id: concept-coherence
title: Concept Coherence Review
targets:
  - id: concept-source-text
    type: text_globs
    title: Product concept, diagram, tutorial, and prompt surfaces
    globs:
      - README.md
      - README.zh-CN.md
      - HUMAN-SHAPED-LOOP.md
      - HUMAN-SHAPED-LOOP.zh-CN.md
      - design/core-ideas/*.md
      - design/decisions/*.md
      - design/detailed-design/05-interfaces.md
      - design/detailed-design/06-workflow-and-prompts.md
      - design/detailed-design/08-bundles-and-alignment.md
      - design/detailed-design/09-web-bundle-alignment.md
      - design/detailed-design/10-agent-adapters.md
      - src/loopora/assets/alignment/product-primer.md
      - src/loopora/assets/alignment/system-prompt.md
      - src/loopora/templates/tutorial.html
      - assets/diagrams/*.svg
    max_bytes_per_file: 8000
  - id: concept-drift-hints
    type: term_hints
    title: Public-reader concept drift and framing hints
    globs:
      - README.md
      - README.zh-CN.md
      - HUMAN-SHAPED-LOOP.md
      - HUMAN-SHAPED-LOOP.zh-CN.md
      - src/loopora/templates/tutorial.html
      - assets/diagrams/*.svg
    terms:
      - prompt pack
      - role zoo
      - generic chat
      - script runner
      - loop script
      - chat wrapper
---

Review docs, diagrams, Web surfaces, and prompts for whether they describe the same Loopora product shape.

Look for:

- Human-shaped Loop being replaced by a generic role list, prompt pack, loop script / script runner, or chat wrapper / chat assistant framing.
- Evidence, judgment, correction, and GateKeeper semantics being described inconsistently across docs, UI, and generated bundles.
- Diagrams or examples that imply humans only react after every round instead of shaping judgment before the loop runs.
- Import, manual composition, Web dialogue, and adapter flows being presented as the main product rather than routes for obtaining or improving a Loop.
- Tutorial orientation surfaces that teach the wrong start path, over-center expert assets, or drift away from the human-shaped Loop invariant.
- Concepts that are correct in one language but drift in another.

Review findings should name the conflicting surfaces and the stable product invariant they violate. Prefer updating the relevant design or current docs over adding a brittle text assertion.
