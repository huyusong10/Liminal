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
  <img alt="Agent first" src="https://img.shields.io/badge/agent--first-loop-2563EB">
  <img alt="Local first" src="https://img.shields.io/badge/local--first-evidence-0D7C66">
  <img alt="Status" src="https://img.shields.io/badge/status-experimental-D66A36">
</p>

# Loopora

**Turn `/goal`-style long tasks into Human-shaped Loops with evidence and verdicts.**

In a Coding Agent, a persistent goal such as `/goal` feels natural: give the Agent an objective, let it remember that objective, and let later turns keep pursuing it. That works well when the goal is clear, risk is low, and completion judgment is simple, such as "fix this error," "keep cleaning up this module," or "get this test set green."

The hard part of complex work is usually not only "keep going." It is judging after each round whether the Agent actually did the right thing: whether evidence is strong enough, whether risk is acceptable, whether the next round should turn, and whether the task can close. A bare persistent goal can keep the work moving, but it can also become a black box: the Agent keeps making the result more complete while early drift, weak evidence, and fake completion are inherited too.

Loopora handles that layer. When a task is too heavy to run as a bare `/goal`, use `/loopora-gen` to turn the objective, done criteria, fake-done patterns, evidence requirements, blocking risks, and next-round priorities into a reviewable Loop. Then use `/loopora-loop` to let the Agent keep executing inside that Loop.

The Agent still reads code, edits files, and runs tools. Loopora reduces error accumulation by making each round return to the same judgment, with evidence, gaps, blockers, and the final task verdict visible in Web.

For the deeper argument behind this layer, read [Human-Shaped Loop](./HUMAN-SHAPED-LOOP.md). This README explains how to use Loopora instead of running a long task as a bare persistent goal.

<p align="center">
  <img src="./assets/diagrams/loopora-overview.en.svg" alt="Loopora turns human task judgment into a plan file, runs the Agent loop, and shows evidence and verdicts in Web" width="1000" />
</p>

## From `/goal` To A Loop

If you would have written:

```text
/goal build the self-service refund flow until it is ready to ship
```

Loopora wants you to split that into two steps:

```text
/loopora-gen
/loopora-loop
```

The difference is not command length. It is the reviewable judgment structure created before the long run starts.

| With a bare `/goal` | With Loopora |
| --- | --- |
| The goal is usually one sentence | The goal becomes done criteria, fake-done patterns, evidence requirements, and blocking risks |
| The Agent mainly keeps pursuing the objective | Each round receives task judgment, action boundaries, evidence gaps, and output requirements |
| The work can look more complete over time | Each round must separate proven, weak, unproven, blocking, and residual risk |
| Closure can lean on the Agent saying it is done | The task verdict needs supporting evidence; missing required evidence prevents pass |
| The human keeps returning to correct drift | The human reviews the Loop before execution, inspects evidence during the run, and intervenes at key points |

Loopora does not reject `/goal`. It keeps the best intuition behind it: long work should be able to continue. For high-risk, multi-round, evidence-sensitive work, though, the run should first define how "actually done" will be judged.

## When Should Loopora Replace `/goal`?

Loopora is not for every task. It is for work where one Agent response can look plausible, but you worry about fake completion, weak evidence, or judgment drift across rounds.

| Situation | Recommendation |
| --- | --- |
| The goal is small and one Agent pass plus one human review is enough | Use the Agent or `/goal` directly. |
| A stable test, benchmark, or proof script can judge the task | Use that hard feedback first. |
| The task will take multiple rounds and each round creates new evidence | Loopora starts to help. |
| The result may look done while core risk remains unproven | Loopora is a strong fit. |
| The judgment should be retained, reviewed, reused, or managed in Web | Loopora is a strong fit. |

Typical examples: self-service refunds, billing permission refactors, cross-service payment callback issues, complex migrations, and product tasks that need exploration without losing judgment standards.

A simple test: if you expect to return in round two, three, or N to ask "is the evidence strong enough, is the risk acceptable, where should the next round go, and can this close?", do not run only a bare goal; compile that judgment into a Loop.

## Quick Start

For now, install from source. You need:

- Python 3.11+
- `uv`
- at least one Coding Agent: Codex, Claude Code, or OpenCode

From the Loopora repository root:

```bash
uv tool install --editable .
```

If uv says the tool directory is not on `PATH`, run:

```bash
uv tool update-shell
```

Then restart your shell.

Next, switch to the project where the Agent will work and install the Loopora entry:

```bash
cd /path/to/your/project
loopora init codex
```

Claude Code and OpenCode can be connected too:

```bash
loopora init claude
loopora init opencode
```

Then return to your Agent and use two entries for the current task:

```text
/loopora-gen
/loopora-loop
```

For a first run, invoke `/loopora-gen` inside your Agent and describe the task plus the judgment that matters:

```text
I need to build a refund request admin:
- a submitting page is not completion
- admin permission and refund eligibility must be proven
- payment failure must be traceable and handoff-ready
- the audit trail must reconstruct a refund
```

Loopora uses the judgment already visible in the current Agent context. If the important judgment is missing, `/loopora-gen` should ask one focused question or open Web review instead of guessing. After the preview looks right, run `/loopora-loop`; the current Agent enters the multi-round task under that Loop.

<p align="center">
  <img src="./assets/diagrams/first-run-path.en.svg" alt="Loopora recommends generating and running a Loop inside the Agent while the Web UI observes and manages the evidence" width="1000" />
</p>

## What Does `/loopora-gen` Produce?

`/loopora-gen` does not start execution immediately. Its job is to create a reviewable task plan. For first-use readers, think of that plan as the portable form of the Loop: it turns a long objective into judgment structure the later run cannot avoid.

In the path started from the Agent, the plan has to carry task-specific judgment, not just a task summary. Important task objects, risks, and evidence expectations should appear in the task contract, Agent responsibilities, and run flow.

The plan usually contains:

| Artifact | Purpose |
| --- | --- |
| Task contract | Captures goal, done criteria, fake-done patterns, tradeoffs, and blocking risks. |
| Agent responsibilities | States what each round should focus on, avoid, hand off, and verify. |
| Execution strategy | States what to build, prove, repair, narrow, expand, or defer. |
| Run flow | States role order, when to inspect, and where to return when evidence is weak. |
| Evidence rules | Separates strong proof from self-report or weak evidence. |
| Verdict rules | Decides when to pass, block, continue, or carry explicit residual risk. |
| Web preview | Lets you review fit, risks, evidence expectations, responsibilities, and closure conditions before running. |

<p align="center">
  <img src="./assets/diagrams/plan-judgment-structure.en.svg" alt="A Loopora plan file carries task-local judgment through task contract, Agent responsibilities, execution strategy, run flow, evidence rules, and verdict rules" width="1000" />
</p>

The plan is not trying to encode all human judgment. It encodes the part of judgment that repeatedly affects this long-running task: what counts as done, what must be rejected, what evidence is strong enough, which gap comes next, and when the task can close.

At runtime, Loopora turns those reader-facing pieces into a runnable plan: the task contract, Agent responsibilities, step order, handoffs, and evidence rules stay linked, so a Loop can be reviewed before execution and audited after execution.

## How Does `/loopora-loop` Run?

`/loopora-loop` starts or resumes a long-running task managed by Loopora. The Agent remains the main execution subject: it reads code, edits files, runs checks, and explains results. Loopora keeps each round tied back to the reviewed plan, required evidence, and verdict rules instead of letting the task continue from chat memory or a bare goal alone.

A run roughly progresses like this:

1. Loopora finds the reviewed candidate Loop.
2. The Agent works from the current round's goal and boundaries.
3. The Agent returns work output, checks, explanations, and evidence references.
4. Loopora reconciles what was proven, what is weak evidence, and what remains unproven.
5. Blocking risk cannot be packaged as completion.
6. Weak evidence pulls the next round back to a concrete gap.
7. When the task can close, Loopora produces a reviewable task verdict and residual-risk summary.

That is the difference between Loopora and an ordinary prompt or bare `/goal`: a prompt mainly shapes the next answer; a bare goal mainly keeps the Agent moving; Loopora keeps the same judgment active across multiple rounds.

## Evidence, Tests, And CI

Loopora does not replace tests, CI, or benchmark checks. The opposite: if a judgment can be expressed as a stable test, automated proof script, schema, lint, type check, or real external probe, it should usually become strong evidence first.

Loopora handles the layer around that evidence: when evidence is missing, failing, incomplete, or proving only part of the task, the Agent cannot package run completion as task completion.

| Evidence shape | What it means in Loopora |
| --- | --- |
| Tests, CI, benchmark checks, automated proof scripts | Strongest machine evidence for stable contracts. |
| Traceable artifacts, logs, screenshots, structured check results | Useful evidence, but it must say what it proves. |
| Independent checker / reviewer conclusions | Useful for surfacing risk, but not automatically hard proof. |
| The Agent's own summary | Readable explanation only; it cannot support pass by itself. |

If stable tests can fully judge the task, Loopora should not make the work heavier. Loopora is for long tasks that need tests and also need continuous judgment about evidence gaps, risk priority, and residual risk.

## Autonomy Boundary

Loopora aims to increase trusted autonomy, not grant unlimited autonomy.

- It does not give the Agent new system permissions; what the Agent can do still depends on the host tool, workdir, and local permissions.
- A Loop's action strategy expresses whether a step is read-only, can write, or can close the run.
- Worktree writes should have a clear boundary; parallel review should not become multiple actors editing the same workspace at once.
- A task verdict does not replace final human approval. It gives the human a reviewable evidence summary, blockers, and residual-risk explanation.
- Local runs create evidence and artifacts; if a task touches sensitive code, logs, or business data, handle them under the local project's security rules.

This boundary matters: Loopora is not trying to help the Agent claim completion more boldly. It is trying to make unsupported completion harder to claim.

## What Can Web Do?

The Web UI is the fuller observation and management surface. You can start a Loop from inside the Agent, then open Web whenever you want to inspect or manage it. When started from the Agent, `/loopora-gen` or `/loopora-loop` starts or reuses the local Web service when it returns a Web link, and the CLI output reports that status.

Start the local Web service manually:

```bash
loopora serve --host 127.0.0.1 --port 8742
```

Open [http://127.0.0.1:8742](http://127.0.0.1:8742).

Web is useful for:

| Scenario | What you can see or do |
| --- | --- |
| Review a candidate Loop | Inspect task contract, Agent responsibilities, execution strategy, run flow, evidence rules, and verdict rules. |
| Observe a run | See where the Loop is and what happened in the latest round. |
| Inspect evidence | Separate proven work, weak evidence, unproven gaps, blockers, and residual risk. |
| Manage entries | Install or update Codex, Claude Code, and OpenCode project entries. |
| Adjust plans | Edit a candidate plan when needed, or create a Loop directly from Web. |

The Agent entry and Web entry are not separate worlds. Even if a Loop starts inside your Agent, it is recorded in the same local system and can be viewed and managed in Web.
