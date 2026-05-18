from __future__ import annotations

import json
import shutil
from pathlib import Path

from loopora.diagnostics import get_logger
from loopora.service_cleanup_diagnostics import cleanup_diagnostic_payload, log_cleanup_diagnostic
from loopora.structured_numbers import structured_non_negative_int

logger = get_logger("loopora.service_alignment")


class ServiceAlignmentLegacyMixin:
    @staticmethod
    def _copy_alignment_legacy_file(source: Path, target: Path) -> None:
        if source.exists() and not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    def _copy_alignment_legacy_file_aliases(self, root: Path, paths: dict[str, Path]) -> None:
        moves: list[tuple[Path, Path]] = [
            (root / "bundle.yml", paths["bundle"]),
            (root / "transcript.jsonl", paths["transcript"]),
            (root / "working_agreement.json", paths["agreement"]),
            (root / "validation.json", paths["validation"]),
        ]
        for source, target in moves:
            self._copy_alignment_legacy_file(source, target)

    def _copy_alignment_legacy_prompts(self, root: Path) -> None:
        for prompt_path in sorted(root.glob("alignment_prompt_*.md")):
            attempt = self._alignment_attempt_from_legacy_path(prompt_path)
            invocation_dir = self._alignment_invocation_dir(root, attempt, repair=False)
            invocation_dir.mkdir(parents=True, exist_ok=True)
            self._copy_alignment_legacy_file(prompt_path, invocation_dir / "prompt.md")

    def _copy_alignment_legacy_outputs(self, root: Path, bundle_path: Path) -> None:
        for output_path in sorted(root.glob("alignment_output_*.json")):
            attempt = self._alignment_attempt_from_legacy_path(output_path)
            invocation_dir = self._alignment_invocation_dir(root, attempt, repair=False)
            invocation_dir.mkdir(parents=True, exist_ok=True)
            target = invocation_dir / "output.json"
            self._copy_alignment_legacy_output(output_path, target, bundle_path)

    def _copy_alignment_legacy_output(self, output_path: Path, target: Path, bundle_path: Path) -> None:
        if target.exists():
            return
        try:
            payload = json.loads(output_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            shutil.copy2(output_path, target)
            return
        target.write_text(
            json.dumps(self._alignment_output_debug_payload(payload, bundle_path), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _copy_alignment_legacy_schema(self, root: Path) -> None:
        legacy_schema = root / "alignment_schema.json"
        if legacy_schema.exists():
            invocation_dir = self._alignment_invocation_dir(root, 0, repair=False)
            invocation_dir.mkdir(parents=True, exist_ok=True)
            self._copy_alignment_legacy_file(legacy_schema, invocation_dir / "schema.json")

    def _copy_alignment_legacy_validations(self, root: Path) -> None:
        for validation_path in sorted(root.glob("validation_*.json")):
            attempt = self._alignment_attempt_from_legacy_path(validation_path)
            invocation_dir = self._alignment_invocation_dir(root, attempt, repair=False)
            invocation_dir.mkdir(parents=True, exist_ok=True)
            self._copy_alignment_legacy_file(validation_path, invocation_dir / "validation.json")

    def _move_alignment_legacy_remainders(self, session: dict, root: Path, legacy_dir: Path) -> None:
        for source in root.iterdir():
            if source.name in {"conversation", "agreement", "artifacts", "events", "invocations", "legacy"}:
                continue
            if source.name == ".DS_Store":
                continue
            target = legacy_dir / source.name
            if target.exists():
                continue
            try:
                shutil.move(str(source), str(target))
            except OSError as exc:
                diagnostic = cleanup_diagnostic_payload(
                    operation="alignment_legacy_artifact_migration",
                    resource_type="path",
                    resource_id=source,
                    owner_id=session["id"],
                    error=exc,
                    target_path=target,
                )
                log_cleanup_diagnostic(logger, **diagnostic)
                self._append_alignment_diagnostic_event(
                    session["id"],
                    "alignment_legacy_artifact_migration_failed",
                    diagnostic,
                )

    @staticmethod
    def _alignment_attempt_from_legacy_path(path: Path) -> int:
        stem = path.stem
        try:
            return max(0, int(stem.rsplit("_", 1)[-1]))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _alignment_invocation_dir(root: Path, attempt: int, *, repair: bool) -> Path:
        suffix = "-repair" if repair else ""
        attempt_index = structured_non_negative_int(attempt)
        return root / "invocations" / f"{attempt_index + 1:04d}{suffix}"

    @staticmethod
    def _alignment_next_invocation_dir(root: Path, attempt: int, *, repair: bool) -> Path:
        suffix = "-repair" if repair else ""
        invocations_dir = root / "invocations"
        index = structured_non_negative_int(attempt) + 1
        while True:
            candidate = invocations_dir / f"{index:04d}{suffix}"
            if not candidate.exists():
                return candidate
            index += 1

    @staticmethod
    def _alignment_latest_invocation_dir(root: Path) -> Path | None:
        invocations_dir = root / "invocations"
        if not invocations_dir.is_dir():
            return None
        candidates = [path for path in invocations_dir.iterdir() if path.is_dir()]
        if not candidates:
            return None
        return max(candidates, key=lambda path: path.stat().st_mtime_ns)
