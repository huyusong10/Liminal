# Loopora Evolution

This note tracks product direction. It is not a module contract; stable
contracts live in `../design/`.

## Product North Star

Loopora is an external task-governance harness for long-running AI Agent work.

The durable loop is:

`task input -> aligned loop plan -> run with evidence -> revise the harness from evidence`

Future work should improve error control, evidence quality, and revision quality
without turning the product into a YAML generator, role library, generic chat
wrapper, or workflow automation platform.

## Current Direction

| Theme | Direction | Stable contract source |
| --- | --- | --- |
| Loop plans | Bundle remains the file-backed exchange unit, while users think in task plans. | `../design/core-ideas/product-principle.md`, `../design/detailed-design/08-bundles-and-alignment.md` |
| Evidence | Runs must produce evidence that can be cited, inspected, and used for revision. | `../design/core-ideas/core-contract.md`, `../design/detailed-design/04-persistence-and-reliability.md` |
| GateKeeper | Finish semantics must depend on cited evidence, not model self-report. | `../design/detailed-design/02-orchestration-service.md`, `../design/detailed-design/06-workflow-and-prompts.md` |
| Revision | Feedback should revise the harness surface that caused the miss. | `../design/detailed-design/08-bundles-and-alignment.md`, `../design/detailed-design/09-web-bundle-alignment.md` |
| Interfaces | Web, CLI, and API should expose the same loop and bundle semantics. | `../design/detailed-design/05-interfaces.md` |
| Providers | Provider differences should appear as capability or degradation evidence, not changed success criteria. | `../design/detailed-design/03-executor-subsystem.md` |

## Near-Term Priorities

1. **Keep tests contract-shaped.**
   Favor fewer high-value checks around the governance boundary. Avoid tests that
   lock static copy, CSS classes, DOM structure, script implementation details, or
   one-off page tweaks.

2. **Keep planning separate from contracts.**
   Planning notes can guide direction, but routine code changes should only need
   the relevant `design/` contract.

3. **Keep user paths simple.**
   The default Web path should remain task description, workdir selection, READY
   preview, run, evidence, and revision. Expert controls should not become the
   first-use experience.

4. **Preserve bundle lifecycle consistency.**
   READY preview, import, export, derive, delete, edit, and revision should keep
   flowing through one bundle lifecycle instead of branching into page-local data
   models.

5. **Make legacy quality visible.**
   Old runs and bundles may remain readable, but missing evidence or lineage
   should be visible as a quality gap rather than inferred as full compliance.

## Migration Notes

| Old shape | Acceptable compatibility | New quality bar |
| --- | --- | --- |
| Legacy bundle without governance projection | Import and run, with missing surfaces marked as legacy or undeclared. | Projection can explain risk, evidence, workflow shape, GateKeeper, and revision lineage. |
| Legacy run without evidence ledger | Keep logs and artifacts accessible. | New runs write canonical evidence and coverage artifacts. |
| GateKeeper verdict without refs | Show as historical text, not a strong evidence gate. | Passing verdicts cite evidence or provide measurable direct claims. |
| Manual loop | Keep runnable and exportable. | Derived bundle re-expresses the governance surfaces coherently. |

## Non-Goals

- Do not make Loopora a generic project management system.
- Do not make evidence a full-text log index.
- Do not make GateKeeper a narrative reviewer.
- Do not require every AI Agent task to use Loopora.
- Do not turn workflow into a general DAG or automation engine.
- Do not hide provider capability gaps by weakening the loop plan's success
  criteria.
