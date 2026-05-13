---
id: default-path-language
title: Default Path Language Quality
targets: []
---

Review default user-facing paths as a non-expert user would encounter them.

Look for:

- Expert terms such as bundle, YAML, workflow controls, orchestration internals, adapter binding, or provider-specific jargon appearing before the user asks for expert mode.
- A page or prompt explaining implementation mechanics instead of the next user action.
- Copy that makes Loopora feel like a prompt pack, role zoo, or generic chat surface instead of a human-shaped Loop platform.
- Chinese and English variants that preserve the same user intent even when the exact words differ.
- Places where a test currently asserts exact copy even though the stable contract is semantic role, next action, or accessible control.

Review notes should cite the rendered page, prompt surface, or documentation section and describe the user confusion risk. Do not convert these findings into exact-copy assertions unless the copy itself is a public contract.
