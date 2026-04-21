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

## What if the scarce resource is not model capability, but human attention?

A strong agent can often write the patch.

The bottleneck appears one step later.

Someone has to come back and ask:

- is this first path real enough to trust?
- did we actually fix the right layer?
- should we keep pushing, stop here, or redirect the next round?

Do that once and it is fine.
Do it after every meaningful step and human attention becomes the traffic bottleneck.

**Loopora is a local-first loop orchestration platform for long, evidence-driven agent work.**

It does not exist because the agent is helpless. It exists because some end-to-end tasks keep pulling humans back in to confirm, judge, and steer the work. Loopora turns those repeated checkpoints into a `Builder → Inspector → GateKeeper → Guide` workflow so humans can step in less often, but step in with better evidence when they do.

<p align="center">
  <img src="./.github/assets/readme-decision-tree.en.png" alt="Loopora decision board" width="1120" />
</p>

## Why Loopora exists

Many loop systems deserve the skepticism they get. If an agent keeps running on the same stale assumption, the loop becomes drift, not progress.

Loopora is built for a narrower and more useful shape:

- `Builder` moves the workspace forward
- `Inspector` reopens the evidence from the updated state
- `GateKeeper` decides whether this round actually crossed the line
- `Guide` only redirects when the work stalls or starts leaning the wrong way

The point is not infinite autonomy. The point is to remove the human attention bottleneck by encoding the check-ins humans would otherwise perform over and over.

## A concrete project, five different loops

Imagine one knowledge-base product replacing its old keyword-only search with a new hybrid search stack. Same product, same rollout, five different long tasks:

- `Build First`
  Get the first help-center slice fully wired end to end so `GateKeeper` can decide whether it is finally ready for shadow traffic.

- `Inspect First`
  After shadow begins, a small set of high-value queries regress. `Inspector` must prove whether the first real gap is ingestion freshness, indexing, retrieval, reranking, or permissions before `Builder` repairs it.

- `Triage First`
  The rollout expands and multiple symptoms appear at once: stale results, ranking drift, broken filters, permission leaks. This round is not about fixing everything; it is about narrowing the one blocker slice that should own the next round.

- `Repair Loop`
  Full reindexing blows the maintenance window. Everyone already knows one repair pass will not be enough, so the first fix must be followed by a fresh inspection before the second fix is chosen.

- `Benchmark Loop`
  The system is close, but the release line is still gated by relevance benchmark results. Each round starts with `GateKeeper` reading the latest evaluation before `Builder` decides whether the next push belongs in retrieval, reranking, or query rewrite.

These are not five tiny tickets. They are five long, end-to-end tasks where a strong agent could help a lot, but humans would otherwise need to keep stepping back in to confirm and redirect the work.

The tutorial starts with the decision board, and each workflow card can open its example in place. Start from the nearest real task, not from an abstract rulebook.

## When to skip Loopora

Do not open a loop if one strong agent pass plus one human review is enough.

Skip Loopora for:

- tiny copy edits
- small UI affordances
- obvious feature slices a single agent can land safely in one pass

Use Loopora when the work is long enough, stateful enough, and uncertain enough that humans would otherwise keep coming back after every meaningful round.

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

Use the decision board to answer two questions: should this task enter Loopora at all, and if it should, which workflow should surface the first crucial signal so humans do not need to step back in immediately. Then open the closest built-in example. The example itself explains why `Builder`, `Inspector`, `GateKeeper`, and `Guide` are arranged that way.

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
