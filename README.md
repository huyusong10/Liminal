[简体中文](./README.zh-CN.md) | **English**

<p align="center">
  <img src="./src/loopora/assets/logo/logo-with-text-horizontal.svg" alt="Loopora" width="560" />
</p>

<p align="center">
  <a href="https://www.python.org/">
    <img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white">
  </a>
  <a href="https://fastapi.tiangolo.com/">
    <img alt="FastAPI" src="https://img.shields.io/badge/web-FastAPI-009688?logo=fastapi&logoColor=white">
  </a>
  <img alt="Local first" src="https://img.shields.io/badge/local--first-loop%20orchestration-0D7C66">
  <img alt="Status" src="https://img.shields.io/badge/status-experimental-D66A36">
</p>

<p align="center">
  Loopora is a local-first orchestration tool for agentic build loops.
  You give it a Markdown spec and a workdir, and it runs a
  <strong>Generator → Tester → Verifier → Challenger</strong> cycle with a live web console.
</p>

![Loopora overview](./.github/assets/readme-overview.svg)

## Why Loopora

- Keep the goal stable while each run iterates against concrete checks.
- Support both explicit checks and exploratory runs with auto-generated frozen checks.
- Persist run artifacts under `.loopora/` so every iteration is inspectable and reproducible.
- Expose the same run state in a local web console with progress, console logs, timeline, and key artifacts.
- Run the same loop definition with Codex, Claude Code, or OpenCode, with provider-aware model and effort settings.

## How It Works

![Loopora flow](./.github/assets/readme-flow.svg)

Each run compiles the Markdown spec into a frozen snapshot, updates the workspace, collects evidence, judges pass/fail, and only invokes the Challenger when the loop stalls or regresses.

## Features

- Local FastAPI console for loop creation, run monitoring, artifact inspection, and skill installation
- The loop creation page remembers unfinished browser drafts and surfaces recent workdirs without changing the underlying loop model
- Structured run outputs such as `compiled_spec.json`, `tester_output.json`, `verifier_verdict.json`, `events.jsonl`, and `summary.md`
- CLI commands for `run`, `serve`, `loops create`, `loops list`, `loops status`, `loops stop`, `loops rerun`, `loops delete`, `spec init`, and `spec validate`
- Optional fake executor mode for smoke tests and demos
- Bundled `loopora-spec` skill that helps draft valid `spec.md` files

## Install

```bash
python3 -m pip install -e .
```

For real execution, make sure the CLI you want to use is available in your environment:

- `codex`
- `claude`
- `opencode`

## Recommended Start: Web UI

1. If you have not installed it yet:

```bash
python3 -m pip install -e .
```

2. Start the local web console:

```bash
loopora serve --host 127.0.0.1 --port 8742
```

Then open [http://127.0.0.1:8742](http://127.0.0.1:8742).

If you want to expose the Web UI on your LAN, bind a public host and protect it with a token:

```bash
loopora serve --host 0.0.0.0 --port 8742 --auth-token your-secret
```

Then open `http://<server-ip>:8742/?token=your-secret` once in the browser. After that, the browser keeps a session cookie. In network mode, paste absolute paths from the server machine directly into the form because native file dialogs are intentionally disabled.

3. Create a starter spec:

```bash
loopora spec init ./demo-spec.md
```

4. Edit it into something concrete:

```md
# Goal

Build a useful landing page for an English learning site.

# Checks

### Main path is clear
- When: A new user opens the page and tries to start learning
- Expect: The main action is obvious and the first step is easy to begin
- Fail if: The page feels ambiguous or the user cannot tell what to do next

# Constraints

- Start with a front-end prototype
- Preserve the existing project files and prefer focused in-place edits
```

5. In the Web UI, create a loop, point it at your `workdir` and `spec.md`, choose an execution tool, and start the run.

The Web UI is the recommended workflow because it gives you live progress, console streaming, timeline milestones, and fixed artifact tabs in one place.

## CLI Supplement

If you want to start a run directly from the terminal, you can still do that:

```bash
loopora run \
  --spec ./demo-spec.md \
  --workdir /absolute/path/to/project \
  --executor codex \
  --model gpt-5.4 \
  --max-iters 8
```

You can switch tools with `--executor claude` or `--executor opencode`. Claude Code uses `low/medium/high/max`. For more tool-specific or fast-moving CLI flags, the Web UI now also supports direct command parameters.
The CLI now exposes the same core loop creation surface as the Web UI: `--executor-mode command`, repeated `--command-arg` entries for direct argv templates, `loops create` when you want to save without starting, and `spec validate` for a quick structural check.

## Spec Model

Loopora uses a Markdown spec with these top-level sections:

- `# Goal` required
- `# Checks` optional
- `# Constraints` optional

When `# Checks` is omitted, Loopora generates a frozen exploratory check set at run start. When checks are provided explicitly, each check should use a `###` heading and include `When`, `Expect`, and `Fail if`.
For existing projects, it is a good idea to use `# Constraints` to say what must stay untouched and to make it explicit that existing user files should be preserved.

For long-running benchmark or evaluation loops, specs work better when they make the owned workflow explicit:

- Put the real success condition in `# Goal`, not just "run the benchmark". Name the project-owned harness and the stop condition if you already know them.
- Use `# Checks` for judgeable outcomes such as fresh score/report artifacts, thresholded scores, or a clearly evidenced architecture-blocked stop condition.
- Use `# Constraints` for forbidden shortcuts, preserved directories, and the only acceptable sources of improvement.
- If the run will take a while, name the project-owned status or report artifacts that should be observed while waiting so silence is not the only progress signal.

## Web Console

The local console includes:

- Saved loop list with status, model, latest run, and direct actions
- Loop creation page with spec validation, recent workdir suggestions, helper tooling, and browser-local draft recovery
- Run detail page with live progress, stage explanations, console streaming, timeline, and fixed artifact tabs
- Tool page for installing the bundled `loopora-spec` skill

## Storage

Global state lives under `~/.loopora/` by default. Set `LOOPORA_HOME=/custom/path` to relocate it when you need an isolated or sandbox-friendly home. For upgrade safety, Loopora still honors `LIMINAL_HOME` and will keep using an existing `~/.liminal/` home until you migrate it:

`settings.json` is treated as self-healing state: if it is missing, corrupted, or contains unknown or out-of-range values, Loopora falls back to safe defaults and rewrites the file into a normalized shape on the next load.

`recent_workdirs.json` is best-effort UI state: Loopora only projects non-empty path strings back into suggestions and ignores corrupted or non-string entries.

- `app.db`
- `settings.json`
- `logs/service.log`
- `recent_workdirs.json`

Per-project state lives under `<workdir>/.loopora/`. Existing workdirs that already use `.liminal/` remain readable and writable:

- `loops/<loop_id>/spec.md`
- `loops/<loop_id>/compiled_spec.json`
- `runs/<run_id>/events.jsonl`
- `runs/<run_id>/tester_output.json`
- `runs/<run_id>/verifier_verdict.json`
- `runs/<run_id>/iteration_log.jsonl`
- `runs/<run_id>/stagnation.json`
- `runs/<run_id>/summary.md`

## Fake Executor

For smoke tests or demos, you can switch to the fake executor:

```bash
LOOPORA_FAKE_EXECUTOR=success loopora run --spec ./demo-spec.md --workdir /tmp/project
```

Supported fake scenarios:

- `success`
- `plateau`
- `role_failure`

Optional delay per role:

```bash
LOOPORA_FAKE_EXECUTOR=success LOOPORA_FAKE_DELAY=0.5 loopora serve
```

## Project Layout

- `src/loopora/`: product package, templates, static files, bundled skills, and logo assets
- `tests/`: parser, runner, recovery, web, and browser coverage
- `pyproject.toml`: packaging, CLI entry point, and test configuration

## Development

Run the test suite:

```bash
python3 -m pytest -q
```
