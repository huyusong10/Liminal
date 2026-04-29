# Loopora Test Map

The test suite protects behavior contracts, not implementation shape.

## Layers

| Layer | Scope | Preferred anchors |
| --- | --- | --- |
| Contract | Spec compilation, bundle lifecycle, workflow normalization, run evidence, GateKeeper completion, revision lineage | Public return values, stable IDs, canonical artifacts, status semantics |
| API | HTTP request and response behavior for the same contracts | Status codes, structured response fields, stable error semantics |
| Page smoke | Server-rendered entry points and first-paint shell behavior | Routes, stable `data-testid` hooks, core links, locale initialization |
| Browser E2E | User journeys that require a real browser or client-side state | Accessible controls, visible outcomes, persisted state |
| Real CLI | Opt-in provider and fixture validation | Provider capability, degradation visibility, preserved artifacts |
| Scenarios | Manual exploratory journeys for a few core flows | Stable user goals, evidence boundaries, cross-entry consistency |

## Guardrails

- Do not assert static UI copy as the main contract.
- Do not assert CSS classes, DOM nesting, or script source internals unless the behavior has no better public anchor.
- Keep language-specific checks narrow and focused on locale selection or presence of translated resources, not exact phrasing.
- Default-path UI tests should assert the five user actions: describe task, confirm loop plan, run, inspect evidence, revise plan.
- Expert terms such as `bundle`, `YAML`, `orchestration`, and `workflow controls` should be asserted only on expert paths or debug/source panels, not as required default-path copy.
- Keep legacy compatibility coverage separate from new-path quality assertions.
- Prefer one high-value journey over many tests that mirror individual implementation branches.
- Keep `tests/scenarios/` small; merge adjacent UI flows into one journey instead of adding one file per page tweak.
