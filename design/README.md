# Loopora Design

This directory is the current design boundary map. Product truth starts in `HUMAN-SHAPED-LOOP.zh-CN.md` and
`README.zh-CN.md`; design only records the contracts an implementation change must preserve.

Loopora's stable workflow is:

`compose Loop -> review Loop -> run Loop -> collect evidence -> report run status, Loop verdict, and result`

## Design Map

| Document | Stable boundary |
| --- | --- |
| `contracts.md` | Product, compiler, bundle, runtime, workflow, Web composer, and Agent Native contracts |
| `decisions/agent-native-execution-plane.md` | Accepted execution-plane split between Agent Native and headless worker paths |

## Maintenance Rules

- Do not add a new design file for implementation details, CSS, DOM shape, prompt wording, or one-off history.
- Keep stable claims in `contracts.md` as a compact table: boundary, claim, owning code, verification, and non-contracts.
- Tests should cite design only for stable product boundaries, not exact copy.
