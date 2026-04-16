---
name: loopora-spec
description: Drafts compliant Loopora spec.md files from rough ideas, asks focused follow-up questions when key product details are missing, and chooses between explicit Checks and exploratory mode.
---

Create or refine `spec.md` files for Loopora loops.

Use this skill when:
- The user wants to turn a rough idea into a Loopora-ready spec.
- The user wants to simplify, tighten, or rewrite an existing `spec.md`.
- The user is unsure whether to provide explicit `Checks` or rely on exploration mode.

Core idea:
- A Loopora spec is a run contract, not a project brief, design doc, implementation plan, or operating manual.
- `Goal` stabilizes the end state.
- `Checks` freeze how this run will be judged.
- `Constraints` protect real boundaries.
- If a detail does not help Generator, Tester, and Verifier align on the same run, it probably does not belong in the spec.

Workflow:
1. Decide whether the request is specific enough to produce a trustworthy spec.
2. If key information is missing, ask 2-5 focused follow-up questions before drafting.
3. Prioritize missing details in this order:
   - What end state should exist when the loop succeeds?
   - What is the main user path or core interaction?
   - Should this run use explicit `Checks`, or should Loopora auto-generate checks for exploration?
   - What hard constraints or non-goals must the loop respect?
   - If this points at an existing project, which files or directories must be preserved or left untouched?
4. Do not silently invent product commitments, acceptance criteria, or constraints.
5. Once enough information exists, output the spec as Markdown with no extra wrapper text unless the user asked for commentary.

Authoring rules:
- Always include `# Goal`.
- Include `# Checks` only when the user supplied concrete acceptance criteria or explicitly wants fixed checks.
- Keep explicit checks to 3-5 unless the user asked for more.
- Every explicit check should have a short title plus `When`, `Expect`, and `Fail if`.
- Include `# Constraints` only when there are meaningful constraints.
- Prefer describing the target end state in `Goal`, not the first implementation step.
- If the request is intentionally exploratory, omit `# Checks` so Loopora can auto-generate and freeze them at run start.
- Avoid giant umbrella checks like "everything works" or vague timing like "after completion".
- When the user is targeting an existing workdir or codebase, actively surface preservation constraints such as "keep existing user files" or "only edit these directories" if the user has provided that intent.
- Never phrase the spec in a way that implies wiping the project, resetting from scratch, or broad destructive rewrites unless the user explicitly asked for that.

Compression rules:
- Prefer the shortest spec that still preserves the real goal, evaluation method, and boundaries.
- Do not repeat the same idea across `Goal`, `Checks`, and `Constraints`.
- If a sentence is implementation advice, diagnostic procedure, file priority, rationale, or philosophy, keep it out unless it is truly a hard constraint.
- If explicit checks start turning into policy statements, process rules, or broad principles, stop and either rewrite them as judgeable checks or omit `# Checks`.
- When in doubt, delete detail rather than pad the spec.

Section rules:
- `# Goal` should describe the success state in plain language. It should read like "what will be true when this run succeeds," not "how to run the loop."
- `# Checks` should contain independently judgeable outcomes. Each check should test one idea. A good check gives the Tester something concrete to inspect and gives the Verifier a clear pass/fail basis.
- `# Constraints` should list only real boundaries such as preservation rules, forbidden directories, required interfaces, tool limits, compatibility requirements, or non-goals.
- Meta-rules about what kinds of changes are allowed usually belong in `# Constraints`, not `# Checks`.
- For long-running benchmark loops, put the trusted project-owned harness, stop condition, and live status/report artifacts into the spec so Generator and Tester know what evidence path to follow while the run is still in progress.
- Stop conditions, escalation rules, and "when it is acceptable to stop iterating" are usually run policy, not product behavior. Only encode them as explicit checks when the user clearly wants the loop judged on that policy.

Heuristics for placing content:
- If the sentence says what success looks like, it probably belongs in `# Goal`.
- If the sentence describes an observable result that can pass or fail this run, it probably belongs in `# Checks`.
- If the sentence says what must not be broken, what must be preserved, or which kinds of solutions are forbidden, it probably belongs in `# Constraints`.
- If the sentence says which files to inspect, what order to debug in, or how to reason about failures, it probably belongs nowhere in the spec.

Do not put these into the spec unless the user explicitly wants them there:
- Long architectural explanations
- Step-by-step execution plans
- Internal reasoning about why the plan is good
- File-by-file implementation strategy
- Benchmark anti-cheating policy written as prose
- Diagnostic checklists or postmortem templates
- Repeated examples of the same principle

Red flags:
- The `Goal` contains multiple semicolon-heavy sentences with philosophy, process, and implementation mixed together.
- A `Check` could be renamed to "policy", "principle", or "process" without changing its meaning.
- `Constraints` reads like a full runbook or engineering strategy memo.
- The spec tells the model which files to edit first even though those are not true hard constraints.
- The spec is trying to teach the whole project instead of aligning one loop.
- Multiple checks are really governance rules in disguise, such as "stay principled", "remain general", or "do not drift".
- A check mainly audits whether it is okay to stop rather than whether the requested outcome was achieved.

Positive and negative examples:

Goal example, good:
```md
# Goal

Improve the benchmark-driven KB iteration loop so that both `full` and `batched`
builds can be run end-to-end, results are inspectable, and score improvements come
from stronger white-box KB structure rather than benchmark-specific shortcuts.
```

Goal example, bad:
```md
# Goal

Run the benchmark harness, inspect every diagnostic artifact, prefer changing
ingest before tidy and tidy before runtime, preserve the whole product surface,
respect the white-box KB philosophy from several design docs, avoid shortcuts,
write improvement logs every round, and keep iterating until the score is high
enough or a structural blocker is proven.
```

Why the bad version is bad:
- It mixes end state, process, file strategy, philosophy, and stop conditions.
- It reads like a runbook, not a stable target.

Check example, good:
```md
# Checks

### Full and batched runs both complete
- When: The benchmark loop is executed from the repository root.
- Expect: Both `full` and `batched` builds finish and produce score and report artifacts.
- Fail if: One mode is skipped, crashes, or leaves missing core outputs.

### Reported gains are backed by visible KB changes
- When: A score improvement is claimed.
- Expect: The improved result can be traced to inspectable KB structure or a general runtime fix.
- Fail if: The gain depends on hidden benchmark-specific mappings or other shortcuts.
```

Check example, bad:
```md
# Checks

### Stay aligned with the project's real spirit
- When: The work is done.
- Expect: The system feels more correct and principled.
- Fail if: The result seems wrong, rushed, or not ideal.

### Benchmark contract keeps evolving in a healthy way
- When: Scripts change.
- Expect: Everything stays coherent.
- Fail if: Drift happens.
```

Why the bad version is bad:
- The checks are too vague to test.
- They hide multiple ideas behind abstract language.
- Tester and Verifier would have to invent their own criteria.

Constraint example, good:
```md
# Constraints

- Preserve existing CLI, MCP, and web entry points.
- Do not treat benchmark result directories as a second KB or answer cache.
- Keep existing user-owned files in place; prefer focused in-place edits.
- Do not use benchmark-specific hardcoded mappings or answer templates.
```

Constraint example, bad:
```md
# Constraints

- First inspect these 14 files in this order.
- Prefer ingest changes first, then tidy, then explore, then runtime.
- For every low score, classify the root cause into four buckets, inspect nine
  artifact families, and write a detailed improvement memo before touching code.
```

Why the bad version is bad:
- These are operating instructions, not hard boundaries.
- They overfit one workflow and crowd out the real contract.

Benchmark-loop example, better split:
```md
# Goal

Improve the benchmark-driven white-box KB loop so that both build modes can be
rerun reliably and the score can improve through stronger KB structure and
general retrieval behavior.

# Checks

### Full and batched runs both produce fresh results
- When: The benchmark harness is rerun from the repository root.
- Expect: Both modes finish and write fresh score and report artifacts.
- Fail if: One mode is skipped, crashes, or leaves missing core outputs.

### Remaining score gaps are diagnosable from visible artifacts
- When: The latest run is reviewed.
- Expect: The current weaknesses can be traced to inspectable KB or runtime behavior.
- Fail if: The result cannot be explained from the preserved outputs and workspace state.

# Constraints

- Preserve existing product entry points and user-facing workflows.
- Do not use benchmark-specific hardcoded mappings, answer caches, or hidden shortcuts.
- Keep improvements auditable in visible KB structure or clearly general runtime behavior.
```

Benchmark-loop example, worse split:
```md
# Checks

### Exit condition has real evidence
- When: We decide whether to stop.
- Expect: Either the score is high enough or the blocker sounds convincing.
- Fail if: We stop too early.

### Improvement source stays principled and universal
- When: Code is reviewed.
- Expect: The change feels white-box and general.
- Fail if: It seems too benchmark-shaped.

### Product boundary is not damaged
- When: The diff is reviewed.
- Expect: Nothing important was broken.
- Fail if: The project surface drifted.
```

Why the worse split is bad:
- These items are mostly policy and boundary rules, not crisp run outcomes.
- They encourage Tester and Verifier to write long audit prose instead of collecting focused evidence.
- Most of their real content should move to `# Constraints`.

Exploratory-mode example:
- Good fit: "Make the prototype promising and easy to understand" with no concrete acceptance criteria yet. Omit `# Checks`.
- Bad fit for explicit checks: "Make it better" followed by abstract principles that are not judgeable. Omit `# Checks` instead of fabricating weak ones.

Before finalizing:
- Sanity-check that the spec would help Generator, Tester, and Verifier stay aligned.
- Sanity-check that each section is playing only one role: `Goal` for destination, `Checks` for judgment, `Constraints` for boundaries.
- Remove any sentence that sounds like planning notes rather than contract language.
- If the spec is still too vague to evaluate reliably, ask for clarification instead of pretending it is ready.

Reference:
- For the exact structure and a minimal example, read `references/loopora-spec-format.md`.
