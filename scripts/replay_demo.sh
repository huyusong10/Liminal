#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "[replay] run orchestrator demo"
python3 orchestrator.py --max-iters 5 --base "$ROOT"

echo "[replay] last verifier verdict"
cat handoff/verifier_verdict.json

echo "[replay] generated website files"
ls -1 workspace/src
