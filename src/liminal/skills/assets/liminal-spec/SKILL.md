---
name: liminal-spec
description: Drafts compliant Liminal spec.md files from rough ideas, asks focused follow-up questions when key product details are missing, and chooses between explicit Checks and exploratory mode.
---

Create or refine `spec.md` files for Liminal loops.

Use this skill when:
- The user wants to turn a rough idea into a Liminal-ready spec.
- The user wants to simplify, tighten, or rewrite an existing `spec.md`.
- The user is unsure whether to provide explicit `Checks` or rely on exploration mode.

Workflow:
1. Decide whether the request is specific enough to produce a trustworthy spec.
2. If key information is missing, ask 2-5 focused follow-up questions before drafting.
3. Prioritize missing details in this order:
   - What end state should exist when the loop succeeds?
   - What is the main user path or core interaction?
   - Should this run use explicit `Checks`, or should Liminal auto-generate checks for exploration?
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
- If the request is intentionally exploratory, omit `# Checks` so Liminal can auto-generate and freeze them at run start.
- Avoid giant umbrella checks like "everything works" or vague timing like "after completion".
- When the user is targeting an existing workdir or codebase, actively surface preservation constraints such as "keep existing user files" or "only edit these directories" if the user has provided that intent.
- Never phrase the spec in a way that implies wiping the project, resetting from scratch, or broad destructive rewrites unless the user explicitly asked for that.

Before finalizing:
- Sanity-check that the spec would help Generator, Tester, and Verifier stay aligned.
- If the spec is still too vague to evaluate reliably, ask for clarification instead of pretending it is ready.

Reference:
- For the exact structure and a minimal example, read `references/liminal-spec-format.md`.
