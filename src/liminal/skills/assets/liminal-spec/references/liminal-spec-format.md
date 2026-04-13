# Liminal Spec Format

Use this format:

```md
# Goal

Describe the end state the loop should reach.

# Checks

### Main flow works
- When: A user follows the main path.
- Expect: The main outcome succeeds.
- Fail if: The flow breaks, stalls, or stays ambiguous.

# Constraints

- List only real constraints.
```

Guidelines:
- `# Goal` is required.
- `# Checks` is optional. Omit it for exploratory runs when the user has not given concrete acceptance criteria.
- `# Constraints` is optional.
- Prefer 3-5 checks.
- Each check should be independently judgeable.
- Use `When`, `Expect`, and `Fail if` together.
