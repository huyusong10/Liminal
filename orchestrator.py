from __future__ import annotations

import argparse
from pathlib import Path

from orchestrator.engine import Orchestrator


def main() -> None:
    parser = argparse.ArgumentParser(description="Liminal external orchestrator")
    parser.add_argument("--max-iters", type=int, default=3)
    parser.add_argument("--base", type=Path, default=Path("."))
    args = parser.parse_args()

    Orchestrator(args.base.resolve()).run_loop(max_iters=args.max_iters)


if __name__ == "__main__":
    main()
