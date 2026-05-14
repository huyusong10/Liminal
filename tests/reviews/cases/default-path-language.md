---
id: default-path-language
title: Default Path Language Quality
targets:
  - id: default-path-text
    type: text_globs
    title: Default path templates, static text, and conversation guidance
    globs:
      - src/loopora/templates/_display_preferences_bootstrap.html
      - src/loopora/templates/auth.html
      - src/loopora/templates/base.html
      - src/loopora/templates/index.html
      - src/loopora/templates/loop_detail.html
      - src/loopora/templates/new_loop.html
      - src/loopora/templates/run_console.html
      - src/loopora/templates/run_detail.html
      - src/loopora/templates/tools.html
      - src/loopora/templates/tutorial.html
      - src/loopora/static/app.js
      - src/loopora/static/pages/alignment.js
      - src/loopora/static/pages/bundle_import.js
      - src/loopora/static/pages/new_loop.js
      - src/loopora/static/pages/run_console.js
      - src/loopora/static/pages/run_detail*.js
      - src/loopora/static/pages/tools.js
      - src/loopora/static/pages/tutorial.js
      - src/loopora/assets/alignment/alignment-playbook.md
      - src/loopora/assets/alignment/compiler-policy.md
      - src/loopora/assets/alignment/product-primer.md
      - src/loopora/assets/alignment/system-prompt.md
    max_bytes_per_file: 6000
  - id: expert-language-hints
    type: term_hints
    title: Expert-language hints on default visible surfaces
    globs:
      - src/loopora/templates/_display_preferences_bootstrap.html
      - src/loopora/templates/auth.html
      - src/loopora/templates/base.html
      - src/loopora/templates/index.html
      - src/loopora/templates/loop_detail.html
      - src/loopora/templates/new_loop.html
      - src/loopora/templates/run_console.html
      - src/loopora/templates/run_detail.html
      - src/loopora/templates/tools.html
      - src/loopora/templates/tutorial.html
      - src/loopora/static/app.js
      - src/loopora/static/pages/alignment.js
      - src/loopora/static/pages/bundle_import.js
      - src/loopora/static/pages/new_loop.js
      - src/loopora/static/pages/run_console.js
      - src/loopora/static/pages/run_detail*.js
      - src/loopora/static/pages/tools.js
      - src/loopora/static/pages/tutorial.js
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

Review default user-facing paths as a non-expert user would encounter them. The text index may include conversation guidance that shapes the default Web compiler, but expert-term machine hints intentionally stay limited to visible Web surfaces and localized strings. Internal compiler references, resource-library detail pages, and expert editing screens belong in concept-coherence or scenario review, not this default-path hint stream.

Look for:

- Expert terms such as bundle, YAML, workflow controls, orchestration internals, adapter binding, or provider-specific jargon appearing before the user asks for expert mode.
- A page or prompt explaining implementation mechanics instead of the next user action.
- Copy that makes Loopora feel like a prompt pack, role zoo, or generic chat surface instead of a human-shaped Loop platform.
- Chinese and English variants that preserve the same user intent even when the exact words differ.
- Places where a test currently asserts exact copy even though the stable contract is semantic role, next action, or accessible control.
- Network/auth entry, locale choice, and accessibility affordances that technically work but explain the path in expert or implementation-first terms.

Review notes should cite the rendered page, prompt surface, or documentation section and describe the user confusion risk. Do not convert these findings into exact-copy assertions unless the copy itself is a public contract.
