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
  <img alt="Local first" src="https://img.shields.io/badge/local--first-loop%20orchestration%20platform-0D7C66">
  <img alt="Status" src="https://img.shields.io/badge/status-experimental-D66A36">
</p>

## What if the hard part is not writing the patch?

What if the real difficulty is not “run the agent one more time,” but learning what the world says after that round lands?

What if one `Builder` pass is not enough, and what you really need is:

- `Inspector` to reopen the evidence
- `GateKeeper` to decide whether this round truly crossed the line
- `Guide` to step in only when the loop starts to stall or drift

Then the problem is no longer “agent automation.” It is orchestration.

**Loopora is a local-first loop orchestration platform for evidence-driven agent work.**

It exists for tasks that cannot be settled in one pass, where the next move should change after new evidence arrives, and where `Builder`, `Inspector`, `GateKeeper`, and `Guide` should each play a distinct role in convergence.

<p align="center">
  <img src="./.github/assets/readme-decision-tree.en.png" alt="Loopora decision board" width="1120" />
</p>

## What Loopora is for

Many loop systems are controversial for a fair reason: if an agent keeps running on the same stale assumption, the loop becomes drift, not progress.

Loopora is built for the opposite shape:

- `Builder` pushes the workspace forward
- `Inspector` gathers new evidence from the updated state
- `GateKeeper` decides pass or fail from that evidence
- `Guide` only redirects when the loop is stuck or leaning the wrong way

That is the point of the loop: not “let the agent think longer,” but **let the next step depend on what really changed.**

## When it is worth using

Use Loopora when:

- the root cause is still ungrounded and `Inspector` should go first
- one repair pass is expected to expose the second bottleneck
- progress must be judged by a benchmark or evaluation harness, not by intuition
- the work will span multiple rounds and you want every handoff, verdict, and artifact to stay inspectable

Do not use Loopora for:

- tiny copy edits
- small buttons
- obvious feature slices a single agent can land safely in one pass

## Start with these 5 core workflows

Loopora deliberately defaults to 5 core workflows, because most real loop-worthy tasks fall into 5 kinds of uncertainty.

- `Build First`
  Use it when the missing piece is the first real working slice. Think of a multi-surface import flow that touches UI, API, and storage, where the target is clear but nothing end to end is running yet.

- `Inspect First`
  Use it when the missing piece is evidence. Think of a billing-close pipeline where some enterprise tenants now get incomplete invoice archives and nobody knows whether the gap begins in aggregation, rendering, bundling, or upload.

- `Triage First`
  Use it when even the problem statement is still fuzzy. Think of a handoff ticket that only says “the system sometimes sends duplicate emails,” and the job is first to collapse that into one actionable defect.

- `Repair Loop`
  Use it when you already expect one repair pass not to be enough. Think of large-tenant full-text reindexing that blows the release window, where the first repair will likely expose a second system bottleneck.

- `Benchmark Loop`
  Use it when the next move should come from the latest benchmark, not from taste. Think of pulling an evaluation score from 61% to 70% without overfitting the prompt to the benchmark itself.

The tutorial starts with the decision board, and each workflow card can open its example in place. You do not need to memorize rules first; start from the nearest real task.

## Quick start

1. Install

```bash
python3 -m pip install -e .
```

2. Start the local web console

```bash
loopora serve --host 127.0.0.1 --port 8742
```

Then open [http://127.0.0.1:8742](http://127.0.0.1:8742).

3. Open the tutorial and orchestration pages first

Use the decision board to answer two questions: should this task enter Loopora at all, and if it should, which workflow should get the first crucial signal. Then open the closest built-in example. The example itself explains why `Builder`, `Inspector`, `GateKeeper`, and `Guide` are arranged that way.

4. Adapt the spec, then create a loop

Loopora specs stay short. They only need:

- `# Task`
- `# Done When`
- `# Guardrails`
- `# Role Notes`

The easiest path is to start from the closest built-in example instead of writing one from scratch.

## Web UI first, CLI still available

The Web UI is the recommended entry point because it keeps the full loop in one place:

- choose a workflow
- open a real scenario example
- adapt the spec
- create the loop
- watch the round-by-round artifacts, evidence, and GateKeeper verdicts

If you already know the loop you want, the CLI is still there:

```bash
loopora run \
  --spec ./demo-spec.md \
  --workdir /absolute/path/to/project \
  --executor codex \
  --model gpt-5.4 \
  --max-iters 8
```

## Development

Run the tests:

```bash
python3 -m pytest -q
```
