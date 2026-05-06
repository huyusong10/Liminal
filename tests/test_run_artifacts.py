from __future__ import annotations

import json
from pathlib import Path

from loopora.run_artifacts import (
    append_jsonl_with_mirrors,
    read_jsonl,
    read_stagnation_state,
    write_json_with_mirrors,
    write_text_with_mirrors,
)


def test_jsonl_legacy_mirror_failure_does_not_block_canonical_write(tmp_path: Path) -> None:
    canonical_path = tmp_path / "timeline" / "events.jsonl"
    mirror_path = tmp_path / "events.jsonl"
    mirror_path.mkdir(parents=True)

    append_jsonl_with_mirrors(canonical_path, {"ok": True}, mirror_paths=[mirror_path])

    assert [json.loads(line) for line in canonical_path.read_text(encoding="utf-8").splitlines()] == [{"ok": True}]


def test_json_legacy_mirror_failure_does_not_block_canonical_write(tmp_path: Path) -> None:
    canonical_path = tmp_path / "timeline" / "stagnation.json"
    mirror_path = tmp_path / "stagnation.json"
    mirror_path.mkdir(parents=True)

    write_json_with_mirrors(canonical_path, {"mode": "none"}, mirror_paths=[mirror_path])

    assert json.loads(canonical_path.read_text(encoding="utf-8")) == {"mode": "none"}


def test_text_legacy_mirror_failure_does_not_block_canonical_write(tmp_path: Path) -> None:
    canonical_path = tmp_path / "summary" / "summary.md"
    mirror_path = tmp_path / "summary.md"
    mirror_path.mkdir(parents=True)

    write_text_with_mirrors(canonical_path, "Summary\n", mirror_paths=[mirror_path])

    assert canonical_path.read_text(encoding="utf-8") == "Summary\n"


def test_read_jsonl_tolerates_invalid_utf8_artifacts(tmp_path: Path) -> None:
    artifact_path = tmp_path / "timeline" / "events.jsonl"
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_bytes(b'{"ok": true}\n\xff\n')

    assert read_jsonl(artifact_path) == []


def test_read_stagnation_state_recovers_corrupt_json(tmp_path: Path) -> None:
    artifact_path = tmp_path / "timeline" / "stagnation.json"
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_text("{", encoding="utf-8")

    assert read_stagnation_state(artifact_path) == {
        "stagnation_mode": "none",
        "recent_composites": [],
        "recent_deltas": [],
        "consecutive_low_delta": 0,
    }
