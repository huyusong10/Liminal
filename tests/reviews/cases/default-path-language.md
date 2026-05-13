---
id: default-path-language
title: Default Path Language Quality
targets:
  - id: default-path-text
    type: text_globs
    title: Default path templates, static text, and alignment prompt assets
    globs:
      - src/loopora/templates/*.html
      - src/loopora/static/app.js
      - src/loopora/static/pages/*.js
      - src/loopora/assets/alignment/*.md
    max_bytes_per_file: 6000
  - id: expert-language-hints
    type: term_hints
    title: Expert-language and drift hints
    globs:
      - src/loopora/templates/*.html
      - src/loopora/static/app.js
      - src/loopora/static/pages/*.js
      - src/loopora/assets/alignment/*.md
    terms:
      - bundle
      - YAML
      - workflow controls
      - orchestration
      - adapter binding
      - provider
      - prompt pack
      - role zoo
---

Review default user-facing paths as a non-expert user would encounter them.

Look for:

- Expert terms such as bundle, YAML, workflow controls, orchestration internals, adapter binding, or provider-specific jargon appearing before the user asks for expert mode.
- A page or prompt explaining implementation mechanics instead of the next user action.
- Copy that makes Loopora feel like a prompt pack, role zoo, or generic chat surface instead of a human-shaped Loop platform.
- Chinese and English variants that preserve the same user intent even when the exact words differ.
- Places where a test currently asserts exact copy even though the stable contract is semantic role, next action, or accessible control.
- Network/auth entry, locale choice, and accessibility affordances that technically work but explain the path in expert or implementation-first terms.

Review notes should cite the rendered page, prompt surface, or documentation section and describe the user confusion risk. Do not convert these findings into exact-copy assertions unless the copy itself is a public contract.
