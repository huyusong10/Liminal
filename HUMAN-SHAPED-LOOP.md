# Human-Shaped Loop: Why Long Agent Tasks Need the Shape of Human Judgment

[简体中文](./HUMAN-SHAPED-LOOP.zh-CN.md) | **English**

This article explains the engineering thinking and collaboration philosophy behind Loopora. For installation and usage, start with the [README](./README.md).

Loopora begins from a plain desire: laziness.

More accurately, it begins from not wanting to sit at a desk, wait for an Agent to finish a round, point out what is wrong, and nudge it to fix the same kind of thing again.

The laziness here is not about avoiding judgment. It is about repeatedly applying the same kinds of judgment: whether this is done, whether evidence is strong enough, whether risk is acceptable, where the next round should return, and whether the task can close.

The concrete answers differ by task, but the question types keep recurring. Loopora tries to turn those recurring judgments into a running structure before later rounds need them again.

<p align="center">
  <img src="./assets/diagrams/loopora-position.en.svg" alt="Loopora turns human judgment into a running structure outside the Agent" width="1000" />
</p>

## 1. A Task That Looks Perfect For An Agent

Imagine a B2B SaaS company whose support team handles a large number of refund tickets every day.

The team decides to build a self-service refund flow: a customer admin opens the billing page, sees whether an order is eligible, submits a refund request, and gets a clear result. If an order looks risky, the flow hands it off to support.

This looks like a good task for a Coding Agent:

- there is a product surface to build.
- there are business rules to encode.
- there are tests to add.
- there are edge cases to discover.
- there is enough work that one pass may not be enough.

So the user says:

> Build a self-service refund flow: a customer admin can request refunds for eligible orders from the billing page; risky orders go to support. Make it safe, add tests, iterate until it is ready to ship.

Round one looks promising: a page, a form, a status message, a few mocked eligibility rules, and passing main-path tests.

The Agent says:

> Done! I achieved the goal!

If this were just a demo, the story might end here. But if this is meant to ship as a real product, the real problems are only beginning:

- It does not prove that only authorized customer admins can request refunds.
- The eligibility check is mocked, not a reliable business path.
- Main-path tests pass, but partial refunds, disputed orders, chargebacks, refunds past the window, and closed accounting periods are not covered.
- It does not explain what happens when the payment provider fails: how the system records it, what the ledger state is, and how support takes over.
- It does not prove that the audit log is enough for support, finance, or compliance to reconstruct what happened.

Now the human reviewer is not facing an abstract concern. They face a concrete shipping decision: can this go live?

The answer is no.

So the reviewer says:

> Not ready. Prove authorization, eligibility, payment failure, and the audit trail first. Only then polish the UI.

Round two may also look more product-like. It adds more page states, more confirmation copy, more mock data, and it mentions "authorization," "eligibility," and "audit" in the summary.

The trouble is exactly there: the human correction was right, and the Agent did not completely ignore it. The problem is that, in an ordinary chat, the judgment still exists only as static text. It has not become evidence that later rounds must cite, blocking conditions that cannot be waived, next-round priorities, or stop conditions that prevent closure.

So the Agent may locally respond to the correction while still returning to easier work: put authorization into copy, leave eligibility in mocked rules, add more main-path tests, then say with more confidence that safety has been improved. It did a lot, but the main risk barely moved. The danger did not disappear. It hid behind a more product-like interface and a more coherent completion story.

If the task keeps running in that direction, the drift may not look like obvious derailment. Round two puts authorization hints into the page, but the real authorization path is still unproven; round three adds main-path tests around mocked eligibility rules without touching the real business boundary; round four writes a final explanation and acceptance summary while still failing to explain provider failure, ledger state, and support handoff. Every round looks like progress, but progress is happening on the visible surface, not on the refund safety gate that would decide whether this can ship.

The Agent is not lazy, and there were not too few rounds. The human also said the right thing. What is missing is a shape that lets the right judgment keep acting in later rounds.

## 2. Human Intervention Shapes The Loop

A long Agent task is already a loop: execute, report, judge, redirect, execute again.

In an ordinary chat, the shape of that loop mainly comes from the Agent's current understanding, the chat memory, and the work it just performed. Each time the human returns, they temporarily reshape the loop: what to reject, what to trust, what must block, what to change next, and when to close.

In engineering teams, these interventions rarely remain only as reminders. When a reviewer says, "Do not just build the page; prove authorization and auditability first," that sentence turns into design constraints, test plans, release gates, audit checks, rollback conditions, and support handoff instructions. Judgment is not merely remembered. It is placed where later work cannot avoid it.

The recurring control signals are small enough to name:

| What the human keeps doing | Stable meaning | Where engineering usually puts it |
| --- | --- | --- |
| Say "not done" | This looks complete, but does not meet the shipping standard. | Done criteria, counterexamples, acceptance notes |
| Judge evidence strength | This material is trustworthy; that is only self-report. | Test results, logs, audit records, traceable artifacts |
| Say "go here next" | Do not keep expanding; repair this gap first. | Priorities, next-step plans, handoff notes |
| Set "cannot pass" | This risk cannot be packaged as completion. | Release gates, rollback conditions, blocking findings |
| Decide closure | These parts are proven; those parts are explicit residual risk. | Acceptance records, residual-risk notes, follow-up owners |

That is what Human-shaped Loop is trying to name.

It does not put the human back into every execution step, and it does not ask the human to write more at the beginning. It turns human judgment into the shape of the later loop. That shape decides what results can be accepted, what evidence is strong enough, which risks must block, why the next round should turn, and how the task can close honestly.

So a Human-shaped Loop is not a longer prompt, and it is not "make the model reflect for more rounds." It asks whether human judgment can be previewed, executed, evidenced, traced, and judged.

## 3. Why PRDs, Tests, And Plain Loops Are Not Enough

Better questions at the start, a stronger PRD, and a plan-execute-self-check routine usually improve the result.

Those methods are useful. Up-front clarity reduces the chance of a bad first pass. A PRD can state goals, constraints, and boundaries. Checklists can remind the Agent not to miss common risks. Tests, type checks, static checks, proof scripts, and benchmarks can turn part of the judgment into hard feedback. Multi-Agent review can add a skeptical angle.

But they mainly improve the opening, or a class of boundaries already expressible through tools. They do not replace judgment returning during execution.

Real engineering teams do not cancel code review, tests, release gates, monitoring, and retrospectives because the design document is detailed. Documents state intent; execution creates new facts. Once the refund task enters a multi-round run, every round creates questions:

- What code and flow did it actually change?
- Which hard parts did it route around?
- Are the new tests proving core risk, or only proving easier paths?
- Did the summary turn "not proven" into "done"?

Those facts only exist after execution, so every round has to answer what it proved, which gaps block closure, which risks can remain explicitly, and whether the next round should expand, gather evidence, narrow scope, fix root cause, or stop.

**This is the difference between PRD / prompt and Human-shaped Loop:**

| PRD / prompt | Human-shaped Loop |
| --- | --- |
| Describes goals and constraints known before the task starts | Turns judgment into control structure that keeps acting during execution |
| Reminds the Agent what to care about | Requires each round to answer with evidence |
| Improves first-round quality | Controls multi-round error propagation |
| Can be selectively quoted or locally satisfied | Records gaps, blockers, and residual risk |
| Mainly answers "what should be done" | Keeps asking "was it proven, should we turn, can we close" |

Fixed cases and automated checks are also essential. In the refund task, only authorized admins can request refunds, past-window refunds are rejected, duplicate refunds are rejected, and provider failure creates a record plus a handoff path. Those should become stable checks whenever possible.

The principle is simple: if a judgment can be expressed as a stable test, schema, lint rule, type check, benchmark, or proof script, it should usually become hard evidence.

But evidence also has strength. The Agent's natural-language summary can help a reader, but it cannot sit at the top of the evidence chain.

| Evidence source | How to treat it |
| --- | --- |
| Tests, CI, benchmarks, proof scripts, real external probes | Strongest; good for stable contracts and machine-adjudicable boundaries. |
| Traceable artifacts, logs, screenshots, structured check results | Useful, but they must state what they prove. |
| Independent checks or human review | Useful for surfacing risk and gaps, but usually needs to land in more concrete evidence. |
| The Agent's natural-language summary | Useful for reading, but not enough to support pass by itself. |

Tests can say whether a set of checks passed. The higher-level judgment still asks whether those checks cover this task's done criteria, whether missing evidence blocks closure, and whether the next round should return to a specific evidence gap.

Without that kind of gate, more rounds can amplify early error. The Agent keeps acting, keeps summarizing, and keeps making the result look more complete, while the underlying definition of completion has drifted.

<p align="center">
  <img src="./assets/diagrams/error-propagation.en.svg" alt="How a plain automated loop packages early error into a more convincing completion story" width="1000" />
</p>

This does not mean refund safety cannot be tested. Quite the opposite: the more important the area, the more it should become tests, audit records, simulated failures, support handoff drills, or other evidence.

The point is that some judgment does not fit into one score, but it can become structure:

- **Priority order**: the real refund path matters more than a polished page.
- **Blocking conditions**: unauthorized refunds, double refunds, and missing audit trails cannot pass.
- **Evidence demands**: authorization, eligibility, provider failure, and support handoff must leave traceable material.
- **Residual risk**: a rare provider edge can remain only if it is visible, named, and owned.

This is not abandoning proof. It is recognizing that some proof is not a single number. It is a set of judgments that constrains later action and final evaluation.

## 4. Why Not A Fixed Team Template?

Another common approach is to freeze a human team shape into an Agent workflow: a product manager analyzes requirements, an architect designs, an engineer implements, a tester or QA agent reviews, and a final reviewer signs off.

That approach has value. Real teams use roles, stage handoffs, and standard operating procedures to reduce confusion. When the task type is stable, the failure modes are stable, and the artifacts are stable, a fixed process can reduce idle chatter and make Agents more disciplined.

But it solves a different layer of the problem. A fixed team template mostly answers:

> Who acts first, who acts next, and who reviews whom?

Human-shaped Loop asks:

> In this task, what is not done? What evidence should be trusted? Which risks must block? Which gap should pull the next round back? When can the task close honestly?

Those questions are not interchangeable. In the refund task, a generic "QA" role may check that the page works, tests pass, and copy is complete while still failing to prove authorization, eligibility, provider failure, and auditability. In a data migration task, QA may need to focus on idempotence, rollback, reconciliation, and rollout boundaries. In a refactor, the reviewer may need to judge behavior compatibility, whether complexity actually decreased, and whether existing tests still protect the public contract.

The role name can stay the same while the useful judgment changes with the task. A fixed template can provide generic division of labor, but it does not automatically know which fake completion this task is most likely to produce.

That is why Loopora needs to generate the Loop structure dynamically. "Dynamic" here does not mean changing the rules arbitrarily during the run. It means compiling a reviewable Loop before execution from the current task's goal, fake-done patterns, evidence preferences, blocking risks, execution priorities, and residual-risk policy. Once the human accepts it, that Loop should stay stable during execution: later rounds cannot quietly lower the done criteria, and required evidence cannot be waived just because a generic reviewer says the result looks good.

This is also why Loopora should not devolve into role proliferation. More roles are not automatically safer. A new role is useful only when it carries a new evidence responsibility, handoff boundary, or verdict input. Otherwise, "product manager + architect + engineer + QA" is only a more team-shaped story, not a more trustworthy task judgment.

The difference can be compressed into one sentence:

> Fixed team templates imitate division of labor; Loopora generates task judgment. The former answers "who does the work," while the latter answers "what proves this round was right."

So a good Loop is not necessarily more complex. It should be the smallest structure that covers the critical judgment of this task: when automated tests can prove something, use tests; when independent evidence is needed, assign evidence responsibility; when a risk must block, put it into verdict rules; when judgment is missing, ask, review, or refuse to run instead of applying a universal workflow.

## 5. What Changes Inside Loopora?

When Human-shaped Loop lands in Loopora, it first appears through three reader-visible surfaces:

- **Reviewable before the run**: the user can see what this Loop will reject, trust, prioritize, block, and accept at closure.
- **Inherited during execution**: later rounds receive the same judgment, action boundaries, evidence gaps, and output requirements instead of continuing from chat memory alone.
- **Auditable at closure**: the result can say what was proven, what is weak evidence, what remains unproven, what blocks closure, and what residual risk is explicit.

Readers do not need to understand Loopora's internal terms first. The important point is that judgment cannot remain only in a prompt or summary. It has to become material the later work repeatedly encounters.

<p align="center">
  <img src="./assets/diagrams/judgment-surfaces.en.svg" alt="Human judgment becomes a task contract, execution strategy, evidence path, and decision rule" width="1000" />
</p>

Return to the refund task. Before the loop starts, the user should not need to hand-write a large configuration. Loopora should turn the judgment into runnable structure:

- A submitting page is not completion.
- Authorization, eligibility, provider failure, audit, and support handoff require evidence.
- Unauthorized refunds, double refunds, and missing audit trails must block.
- Rare provider edges may remain as residual risk, but only if visible, named, and owned.

After the Agent completes the first round, it cannot only report "done." If this round still returns a page, a form, mocked eligibility rules, and main-path tests, it has to return to the visible judgment standard:

- What did this round actually prove?
- Is there evidence for the authorized-admin path?
- Is refund eligibility a real business path, or still mocked rules?
- After provider failure, is there a record, ledger state, and support handoff?
- Can support, finance, or compliance reconstruct what happened from the audit material?

This round might then be organized like this:

| Evaluation surface | This round's reality |
| --- | --- |
| Proven | The page can submit, and main-path tests pass |
| Weak evidence | Refund eligibility still mainly comes from mocked rules |
| Unproven | Authorized-admin path, provider failure handling, audit trail |
| Blocking risk | If unauthorized refund safety is unproven, the run cannot close |

<p align="center">
  <img src="./assets/diagrams/refund-evidence-loop.en.svg" alt="The refund task in Loopora is pulled into the next round by evidence gaps" width="1000" />
</p>

When evidence is weak, the next round is not free to continue in any direction, and it should not keep polishing UI or adding more confirmation copy. It gets pulled back to the harder questions: prove authorization first, cover refund eligibility boundaries first, add the provider failure path first, and add audit records plus human handoff first.

Closure also does not promise zero risk. A good conclusion should clearly separate what is proven, which cases remain uncovered, which findings block closure, and which risks can move forward only if visible, owned, and connected to follow-up.

## 6. What Does This Require From The System?

Human-shaped Loop is not just the name of an essay. It is a minimum bar the system has to meet.

- A candidate Loop cannot be only a task summary; it must carry this task's judgment boundary.
- The Loop structure cannot be only a fixed team template; roles and flow must carry this task's evidence responsibilities, handoff boundaries, and verdict inputs.
- When judgment is insufficient, the system should ask, review, or refuse to become runnable instead of inventing missing judgment.
- Once a run starts, each step should inherit these judgments, action boundaries, and evidence gaps.
- Each round must return to evidence, coverage, handoff material, and gaps instead of retaining only a polished summary.
- Final pass must depend on supporting evidence; missing required evidence must prevent the task from being packaged as passed.
- Runtime lifecycle and task meaning must stay separate: the system can finish running while the task remains unproven.

If these conditions are invisible in the product experience, Human-shaped Loop remains a nice phrase instead of a trustworthy runtime boundary.

That is the line between Loopora and an ordinary prompt: a prompt can remind the model; Loopora has to turn the reminder into something the run can ask about, record, and decide from.

## 7. When Does Loopora Fit?

Loopora is not for every complex task. Complexity is not the deciding factor. Repeated judgment is.

Engineering process has a cost, so it is not spread evenly across every task. Changing button copy does not need design review, release gates, and a retrospective. Fixing a small bug with a clear stack trace usually does not need them either. Heavy process on light work only slows the work down.

Refunds, billing permissions, payment callbacks, and data migration are different. Design has to name the risks, tests have to prove key boundaries, someone has to decide before release, and failure paths have to be traceable. Risk accumulates across rounds, evidence has to be retained, and completion cannot rest only on the implementer's summary.

Ask in this order:

| Gate | If the answer leans yes | If the answer leans no |
| --- | --- | --- |
| Is one Agent pass plus one human review enough? | Skip Loopora; direct work is cheaper | Continue |
| Will later rounds create new evidence? | Continue | Do not open a Loop; it will only create longer narrative |
| Can the judgment become a stable automated check? | Prefer tests, benchmarks, or proof scripts | Continue |
| Is fake completion likely? | Loopora is more valuable | Direct Agent work or a simple loop may be enough |
| Should this judgment survive one chat? | It may deserve a Loop | Direct chat is enough |

More concrete examples:

- **Usually skip**: generate 30 campaign ideas, fix a button crash with a clear stack trace, split a small helper with clear boundaries.
- **Better fit**: self-service refunds, billing permission refactors, intermittent cross-service payment callback loss, brand exploration that must avoid stale patterns across rounds.
- **Key difference**: not whether the task sounds complex, but whether humans would repeatedly return after key rounds to judge evidence, risk, direction, and closure.

## 8. Stronger Models And Trusted Autonomy

The model should learn general capability: language, coding, planning, tool use, reasoning patterns, and broad taste. Those abilities should transfer across users and tasks.

Stronger models will make many tasks easier. They are like more senior engineers: they can notice more risks up front, write a better first plan, and avoid many basic mistakes.

But nobody cancels code review, tests, release gates, audit trails, and incident retrospectives just because the engineer is senior. That is not distrust of individual ability. Delivery judgment does not live only inside individual ability. Which risks are acceptable, what evidence is sufficient, and when residual risk can ship depend on the specific task, team commitment, and business environment. They have to be explicit enough to be debated and changed.

This means judgment is not something that can be written once into a model or global memory. It is bound to this task, this set of risks, this team commitment, and this evidence.

Judgment inside one task should often be local, temporary, and debatable:

- this refund flow should be conservative; not every product task should be.
- this prototype can accept rough visuals; not every prototype can.
- this benchmark is trusted here; another benchmark may mislead.
- this residual risk is acceptable now; the same risk may block elsewhere.

These judgments should be explicit, previewable, editable, exportable, and disposable. They belong in the Loop layer outside the Agent, not silently in model weights or long-term memory.

> The model learns general capability. The Loop learns how this task should be judged.

Loopora is not trying to increase the Agent's freedom. It is trying to increase trusted autonomy. Autonomy does not mean running without constraint. It means continuing inside the shape of human judgment.

That also means autonomy needs boundaries. Loopora should not give the Agent new permissions, bypass the host tool's safety model, or turn a passed task result into final human approval. It can externalize action permissions, evidence gaps, blockers, and residual risk, so the human intervenes less often in routine cycles but more clearly at key decisions.

When judgment, evidence, redirection, and closure have been externalized, humans can truly come back less often. That is Loopora's version of laziness: not sacrificing quality to save effort, but raising trusted autonomy so the same judgment does not have to be repeated by hand.

Human-in-the-loop puts humans inside execution.

Human-shaped Loop turns human judgment into prior execution structure.

That is Human-shaped Loop.

To install and run Loopora, return to the [README](./README.md). The README explains how to use it; this article explains why this layer exists.
