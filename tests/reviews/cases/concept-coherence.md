---
id: concept-coherence
title: Concept Coherence Review
targets:
  - id: top-level-anchor-text
    type: text_globs
    title: Top-level README and Human-Shaped Loop anchors
    globs:
      - README.md
      - README.zh-CN.md
      - HUMAN-SHAPED-LOOP.md
      - HUMAN-SHAPED-LOOP.zh-CN.md
    max_bytes_per_file: 30000
  - id: concept-source-text
    type: text_globs
    title: Product concept, diagram, tutorial, and prompt surfaces
    globs:
      - design/core-ideas/*.md
      - design/decisions/*.md
      - design/detailed-design/05-interfaces.md
      - design/detailed-design/06-workflow-and-prompts.md
      - design/detailed-design/09-web-bundle-alignment.md
      - src/loopora/assets/alignment/product-primer.md
      - src/loopora/assets/alignment/system-prompt.md
      - src/loopora/templates/tutorial.html
      - assets/diagrams/*.svg
    max_bytes_per_file: 8000
  - id: gen-loop-contract-text
    type: text_globs
    title: Bundle, gen, and loop execution design contracts
    globs:
      - design/detailed-design/08-bundles-and-alignment.md
      - design/detailed-design/10-agent-adapters.md
    max_bytes_per_file: 40000
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
      - term: 一点也
        label: inline Chinese review note
      - term: 这个图
        label: inline Chinese review note
      - term: 这里可能
        label: inline Chinese review note
      - term: 看看怎么
        label: inline Chinese review note
      - term: 有点突兀
        label: inline Chinese review note
      - term: 受到质疑
        label: inline Chinese review note
      - term: 吸引力
        label: inline Chinese review note
      - term: 拒绝和阻断
        label: inline Chinese review note
      - term: 不够好理解
        label: inline Chinese review note
      - term: 不要出现
        label: inline Chinese review note
      - term: 请巡检
        label: inline Chinese review note
      - term: 用户很容易看不懂
        label: inline Chinese review note
      - term: 太冗长
        label: inline Chinese review note
      - term: 不适合做最后总结
        label: inline Chinese review note
      - term: 简化
        label: inline Chinese review note
      - term: 去掉
        label: inline Chinese review note
---

Review docs, diagrams, Web surfaces, and prompts for whether they describe the same Loopora product shape.

Look for:

- Human-shaped Loop being replaced by a generic role list, prompt pack, loop script / script runner, or chat wrapper / chat assistant framing.
- Evidence, judgment, correction, and GateKeeper semantics being described inconsistently across docs, UI, and generated bundles.
- Diagrams or examples that imply humans only react after every round instead of shaping judgment before the loop runs.
- Import, manual composition, Web dialogue, and adapter flows being presented as the main product rather than routes for obtaining or improving a Loop.
- Tutorial orientation surfaces that teach the wrong start path, over-center expert assets, or drift away from the human-shaped Loop invariant.
- Concepts that are correct in one language but drift in another.
- Visible top-level docs shipping inline editorial review notes instead of reader-facing product explanation.
- Whether bundle design still externalizes task-scoped human judgment into runnable surfaces rather than becoming YAML configuration.
- Whether `/loopora-gen` still helps the human externalize judgment by checking fit and sufficiency, asking one focused question or returning Web review when needed, and refusing to invent missing judgment.
- Whether `/loopora-loop` still executes the reviewed Loop through run contracts, step capsules, host dispatch, required coverage, evidence gates, and task verdicts rather than relying on host memory or inline shortcuts.

Review findings should name the conflicting surfaces and the stable product invariant they violate. Prefer updating the relevant design or current docs over adding a brittle text assertion.
