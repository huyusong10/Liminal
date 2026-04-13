# Liminal

Liminal is a CLI-first local orchestration tool for Codex loops.

You give it:

1. A Markdown spec with natural-language cases and expected results
2. A workdir
3. Runtime parameters like model, retry policy, and max iterations

Liminal then runs a Generator -> Tester -> Verifier -> Challenger loop, stores the run under the project’s `.liminal/` folder, and exposes the same data through a local web console.

## What ships in this repo

- `liminal/`: the product code
- `tests/`: parser, runner, stop, web, and explorer coverage
- `desgin/`: earlier design notes kept as reference
- `orchestrator/`: legacy prototype modules kept for historical context

The new source of truth is the `liminal` package.

## Install

```bash
python3 -m pip install -e .
```

## Quick start

Create a spec:

```bash
liminal spec init ./demo-spec.md
```

Run a loop:

```bash
liminal run \
  --spec ./demo-spec.md \
  --workdir /absolute/path/to/project \
  --model gpt-5.4 \
  --max-iters 8
```

Start the local web console:

```bash
liminal serve --host 127.0.0.1 --port 8742
```

Then open [http://127.0.0.1:8742](http://127.0.0.1:8742).

## CLI

```bash
liminal run --spec <path> --workdir <path> --model <id> --max-iters <n>
liminal serve --host 127.0.0.1 --port 8742
liminal loops list
liminal loops status <loop-or-run-id>
liminal loops stop <run-id>
liminal loops rerun <loop-id>
liminal spec init <path>
```

## Spec format

The Markdown spec must include these top-level sections:

- `# Goal`
- `# Cases`
- `# Expected Results`
- `# Acceptance`
- `# Constraints`

Inside `# Cases` and `# Expected Results`, each case should use a `###` heading.

Liminal compiles that Markdown into an internal `compiled_spec.json` snapshot for each loop and run.

## Storage model

Global state lives under `~/.liminal/`:

- `app.db`: SQLite metadata
- `settings.json`: local settings
- `logs/service.log`: web service logs
- `recent_workdirs.json`: recent workdirs

Per-project state lives under `<workdir>/.liminal/`:

- `loops/<loop_id>/spec.md`
- `loops/<loop_id>/compiled_spec.json`
- `runs/<run_id>/events.jsonl`
- `runs/<run_id>/tester_output.json`
- `runs/<run_id>/verifier_verdict.json`
- `runs/<run_id>/iteration_log.jsonl`
- `runs/<run_id>/stagnation.json`
- `runs/<run_id>/summary.md`

## Web console

The local FastAPI console includes:

- Loop list with status, model, current iteration, and latest run
- Loop creation form
- Run detail page with overview, timeline, key outputs, and a read-only resource explorer
- SSE-backed live updates for active runs

## Real Codex vs fake executor

By default, Liminal uses the real `codex exec --json` CLI.

For local smoke tests or demos, you can switch to the fake executor:

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

## Tests

```bash
python3 -m pytest -q
```
