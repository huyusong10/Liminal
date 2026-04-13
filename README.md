[简体中文](./README.zh-CN.md) | **English**

<p align="center">
  <img src="./src/liminal/assets/logo/logo-with-text-horizontal.svg" alt="Liminal" width="560" />
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
  Liminal is a local-first orchestration tool for Codex-style build loops.
  You give it a Markdown spec and a workdir, and it runs a
  <strong>Generator → Tester → Verifier → Challenger</strong> cycle with a live web console.
</p>

![Liminal overview](./.github/assets/readme-overview.svg)

## Why Liminal

- Keep the goal stable while each run iterates against concrete checks.
- Support both explicit checks and exploratory runs with auto-generated frozen checks.
- Persist run artifacts under `.liminal/` so every iteration is inspectable and reproducible.
- Expose the same run state in a local web console with progress, console logs, timeline, and key artifacts.

## How It Works

![Liminal flow](./.github/assets/readme-flow.svg)

Each run compiles the Markdown spec into a frozen snapshot, updates the workspace, collects evidence, judges pass/fail, and only invokes the Challenger when the loop stalls or regresses.

## Features

- CLI commands for `run`, `serve`, `loops list`, `loops status`, `loops stop`, `loops rerun`, and `spec init`
- Local FastAPI console for loop creation, run monitoring, artifact inspection, and skill installation
- Structured run outputs such as `compiled_spec.json`, `tester_output.json`, `verifier_verdict.json`, `events.jsonl`, and `summary.md`
- Optional fake executor mode for smoke tests and demos
- Bundled `liminal-spec` skill that helps draft valid `spec.md` files

## Install

```bash
python3 -m pip install -e .
```

For real execution, make sure the `codex` CLI is available in your environment.

## Quick Start

1. Create a starter spec:

```bash
liminal spec init ./demo-spec.md
```

2. Edit it into something concrete:

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
```

3. Run a loop:

```bash
liminal run \
  --spec ./demo-spec.md \
  --workdir /absolute/path/to/project \
  --model gpt-5.4 \
  --max-iters 8
```

4. Start the local web console:

```bash
liminal serve --host 127.0.0.1 --port 8742
```

Then open [http://127.0.0.1:8742](http://127.0.0.1:8742).

## Spec Model

Liminal uses a Markdown spec with these top-level sections:

- `# Goal` required
- `# Checks` optional
- `# Constraints` optional

When `# Checks` is omitted, Liminal generates a frozen exploratory check set at run start. When checks are provided explicitly, each check should use a `###` heading and include `When`, `Expect`, and `Fail if`.

## Web Console

The local console includes:

- Saved loop list with status, model, latest run, and direct actions
- Loop creation page with spec validation and helper tooling
- Run detail page with live progress, stage explanations, console streaming, timeline, and fixed artifact tabs
- Tool page for installing the bundled `liminal-spec` skill

## Storage

Global state lives under `~/.liminal/`:

- `app.db`
- `settings.json`
- `logs/service.log`
- `recent_workdirs.json`

Per-project state lives under `<workdir>/.liminal/`:

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
LIMINAL_FAKE_EXECUTOR=success liminal run --spec ./demo-spec.md --workdir /tmp/project
```

Supported fake scenarios:

- `success`
- `plateau`
- `role_failure`

Optional delay per role:

```bash
LIMINAL_FAKE_EXECUTOR=success LIMINAL_FAKE_DELAY=0.5 liminal serve
```

## Project Layout

- `src/liminal/`: product package, templates, static files, bundled skills, and logo assets
- `tests/`: parser, runner, recovery, web, and browser coverage
- `pyproject.toml`: packaging, CLI entry point, and test configuration

## Development

Run the test suite:

```bash
python3 -m pytest -q
```
