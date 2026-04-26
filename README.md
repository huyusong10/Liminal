[简体中文](./README.zh-CN.md) | **English**

<p align="center">
  <img src="./src/loopora/assets/logo/logo-with-text-horizontal.svg" alt="Loopora" width="720" />
</p>

<p align="center">
  <a href="https://www.python.org/">
    <img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white">
  </a>
  <a href="https://fastapi.tiangolo.com/">
    <img alt="FastAPI" src="https://img.shields.io/badge/web-FastAPI-009688?logo=fastapi&logoColor=white">
  </a>
  <img alt="Local first" src="https://img.shields.io/badge/local--first-AI%20Agent%20evidence%20loops-0D7C66">
  <img alt="Status" src="https://img.shields.io/badge/status-experimental-D66A36">
</p>

Loopora is a local-first workbench for long-running AI Agent tasks.

It turns task-specific judgment into a runnable evidence loop: align the task, generate a loop plan, run local AI Agent CLIs, collect evidence, and revise the plan from what actually happened.

## If an AI Agent can already do the work, why use Loopora?

That is the first question Loopora should survive.

If the task is small, obvious, and reviewable in one pass, do not use Loopora. Ask an AI Agent to do it, review once, and move on.

But what if the hard part is not producing the first answer?

What if the hard part is that humans keep returning to ask:

- did this round prove the right thing?
- is this truly done, or just locally plausible?
- should the next round build, inspect, repair, narrow the slice, or stop?
- is this residual risk acceptable for this task?
- what should change in the next attempt because of the evidence we just saw?

When those questions repeat, the bottleneck is not generation. The bottleneck is judgment.

**Loopora exists for that moment: it compiles task-specific judgment into a loop that can act, inspect, gate, and improve from evidence.**

## What Makes Loopora Different?

Loopora is not a role zoo. More roles do not automatically create better long-running work.

Loopora is not a prompt pack. A longer prompt does not make completion criteria, role posture, and workflow timing inspectable.

Loopora is not just a loop script. Repeating an AI Agent call only helps when each round produces new evidence and a clearer next move.

Loopora combines the three missing pieces into one local system:

| Piece | What Loopora makes explicit |
|-------|-----------------------------|
| Task contract | What counts as progress, fake done, trusted evidence, guardrails, and residual risk |
| Agent posture | How each AI Agent role should build, inspect, gate, or redirect for this task |
| Workflow timing | When judgment happens, how the run loops, and when it can stop |

Those pieces are stored together as a loop plan, run together, and revised together.

## Quick Start

Install from the repository root:

```bash
uv sync
```

Start the local Web console:

```bash
uv run loopora serve --host 127.0.0.1 --port 8742
```

Open [http://127.0.0.1:8742](http://127.0.0.1:8742), click **New Task**, choose a workdir, and describe what you want Loopora to do.

The recommended Web path is:

```text
describe task -> align loop plan -> preview -> create and run -> inspect evidence -> revise plan
```

## A Concrete Example

Imagine you type:

> Build an English learning website.

A normal AI Agent path may jump straight into screens: a landing page, vocabulary cards, a few buttons, maybe a polished UI. It can look finished before it proves that a learner can complete one real learning cycle.

Loopora slows down at the point that matters. It asks:

- Is the first version a runnable learning path, or just a product sketch?
- What is fake done? A pretty page with no real study loop?
- What evidence proves that a user can choose a goal, study, practice, and see progress?
- Should the final gate reject shallow polish even if the page looks good?

After alignment, Loopora shows a **loop plan**. The plan explains:

- `spec`: the task contract, success surface, fake-done states, evidence preferences, and guardrails.
- `roles`: task-shaped AI Agent roles such as `Builder`, `Inspector`, and `GateKeeper`.
- `workflow`: the order of judgment, for example `Builder -> Inspector -> GateKeeper`.

Then Loopora creates and runs the loop. `Builder` changes the workdir, `Inspector` checks whether the learning path is real, and `GateKeeper` decides whether the evidence is strong enough to finish.

If the result still feels wrong, the next step should not be random prompt editing. The next step is a plan revision based on run evidence.

## What Does Loopora Generate?

Loopora first generates a human-readable **loop plan**.

Internally, that plan is stored as a YAML **bundle**: a single importable file that contains the task contract, AI Agent role posture, workflow, and loop settings.

You do not need to hand-write bundles to start. The Web UI generates the plan through conversation, validates the bundle, and shows READY only after the file passes Loopora's contract.

The bundle matters because it is:

- readable: you can inspect why this collaboration shape exists
- runnable: Loopora can materialize it into local assets and start a run
- evidence-oriented: the run can show what happened and why it passed or failed
- revisable: later feedback can produce the next plan instead of scattered field edits

## How the Web Flow Works

```mermaid
flowchart LR
    A["Describe the task"] --> B["Align loop plan"]
    B --> C["READY plan"]
    C --> D["Preview spec / roles / workflow"]
    D --> E["Create and run"]
    E --> F["Run evidence"]
    F --> G["Revise the plan"]
```

In the Web UI:

1. **Workbench** shows current tasks and run state.
2. **New Task** opens the chat-first alignment page.
3. Loopora calls your local AI Agent CLI, asks clarifying questions, and keeps session context across turns.
4. When the plan is READY, the page shows the task contract, role cards, workflow diagram, and source file actions.
5. **Create and run** imports the bundle through the normal lifecycle and starts the loop.
6. **Plans** stores reusable loop plans and bundle revisions.

Manual creation still exists, but it is the expert path for users who already know which `spec`, `roles`, or `workflow` surface they want to edit.

## Why Not Just Write a Better Prompt?

Because the judgment is not one prompt.

If you put it only in the `spec`, the roles stay generic.  
If you put it only in role prompts, the pass/fail contract drifts.  
If you put it only in a workflow, the system knows the order but not the judgment.

Loopora spreads task posture across three runtime surfaces:

| Surface | What it carries |
|---------|-----------------|
| `spec` | Success criteria, evidence, fake-done states, guardrails, residual risk |
| `roles` | How each AI Agent role should build, inspect, gate, or redirect for this task |
| `workflow` | When each kind of judgment happens and how the run finishes |

The loop then tests those surfaces against fresh evidence instead of self-report.

## When Should You Use Loopora?

Ask the negative question first:

> Would one AI Agent pass plus one human review be enough?

If yes, skip Loopora.

Now ask the positive question:

> Would a human otherwise return after each meaningful round to judge what the result means?

If yes, Loopora may fit.

Use it when the task is:

- long enough that one pass will not settle it
- stateful enough that every round changes the evidence
- uncertain enough that build, inspect, gate, and redirect should be separated
- important enough that "looks done" is not the same as "done"

Do not use it when another round will not create new evidence. A loop without new evidence is drift.

<p align="center">
  <img src="./.github/assets/readme-decision-tree.en.png" alt="Loopora decision board" width="1120" />
</p>

## Workflow Shapes

Do not start by memorizing presets. Ask what humans would otherwise need to decide first.

| Shape | Use when... |
|-------|-------------|
| `Build First` | you need the first end-to-end path before anyone can judge |
| `Inspect First` | you need proof of the failing layer before more code |
| `Triage First` | multiple symptoms must be narrowed into one repair slice |
| `Repair Loop` | one repair pass will not be enough |
| `Benchmark Loop` | the next move should depend on the latest measurement |

These shapes answer the same question:

> What judgment should the loop surface before humans have to come back?

## External AI Agent Path

The Web UI is the default path because it keeps alignment, bundle validation, preview, creation, and run evidence in one guided flow. Plan revision should use that evidence as its source of truth instead of drifting into hidden prompt edits.

If you prefer to align outside the Web UI, open **Resources -> Tools & Skill** and install the repo-local `loopora-task-alignment` Skill into Codex, Claude Code, or OpenCode.

That path still produces the same YAML bundle. Import it from **Resources -> Manual creation** when you want to run it in Loopora.

## CLI

The CLI remains available for automation and expert usage:

```bash
uv run loopora run \
  --spec ./demo-spec.md \
  --workdir /absolute/path/to/project \
  --executor codex \
  --model gpt-5.4 \
  --max-iters 8
```

## Project Status

Loopora is experimental and local-first. Expect active iteration around the Web flow, bundle alignment quality, evidence review, and long-running scenario coverage.

Core guarantees:

- bundle import/export stays file-based and inspectable
- Web alignment does not bypass the bundle lifecycle
- run evidence is stored locally under Loopora-managed artifacts
- expert routes for `spec / roles / workflow` remain available
- future revisions should flow from evidence and feedback, not hidden prompt drift

## Development

Run the tests:

```bash
uv run pytest -q
```
