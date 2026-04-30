from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from loopora.utils import utc_now


class RepositoryLocalAssetRecordsMixin:
    def upsert_local_asset_root(
        self,
        *,
        resource_type: str,
        resource_id: str,
        path: str | Path,
        workdir: str = "",
        owner_id: str = "",
        state: str = "active",
    ) -> dict:
        normalized_state = self._normalize_local_asset_state(state)
        now = utc_now()
        normalized_path = str(Path(path).expanduser())
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO local_asset_roots
                    (resource_type, resource_id, path, workdir, owner_id, state, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(resource_type, resource_id, path) DO UPDATE SET
                    workdir = excluded.workdir,
                    owner_id = excluded.owner_id,
                    state = excluded.state,
                    updated_at = excluded.updated_at
                """,
                (
                    str(resource_type or "").strip(),
                    str(resource_id or "").strip(),
                    normalized_path,
                    str(workdir or "").strip(),
                    str(owner_id or "").strip(),
                    normalized_state,
                    now,
                ),
            )
            row = connection.execute(
                """
                SELECT * FROM local_asset_roots
                WHERE resource_type = ? AND resource_id = ? AND path = ?
                """,
                (str(resource_type or "").strip(), str(resource_id or "").strip(), normalized_path),
            ).fetchone()
        return self._decode_row(row)

    def mark_local_asset_root_state(
        self,
        *,
        resource_type: str,
        resource_id: str,
        state: str,
        path: str | Path | None = None,
    ) -> int:
        normalized_state = self._normalize_local_asset_state(state)
        now = utc_now()
        params: list[object] = [
            normalized_state,
            now,
            str(resource_type or "").strip(),
            str(resource_id or "").strip(),
        ]
        path_clause = ""
        if path is not None:
            path_clause = " AND path = ?"
            params.append(str(Path(path).expanduser()))
        with self.transaction() as connection:
            cursor = connection.execute(
                f"""
                UPDATE local_asset_roots
                SET state = ?, updated_at = ?
                WHERE resource_type = ? AND resource_id = ?{path_clause}
                """,
                params,
            )
        return int(cursor.rowcount or 0)

    def mark_local_asset_root_state_by_path(self, *, path: str | Path, state: str) -> int:
        normalized_state = self._normalize_local_asset_state(state)
        with self.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE local_asset_roots
                SET state = ?, updated_at = ?
                WHERE path = ?
                """,
                (normalized_state, utc_now(), str(Path(path).expanduser())),
            )
        return int(cursor.rowcount or 0)

    def list_local_asset_roots(
        self,
        *,
        resource_type: str | None = None,
        states: Iterable[str] | None = None,
    ) -> list[dict]:
        clauses: list[str] = []
        params: list[object] = []
        if resource_type:
            clauses.append("resource_type = ?")
            params.append(str(resource_type).strip())
        normalized_states = [
            self._normalize_local_asset_state(state)
            for state in (states or [])
            if str(state or "").strip()
        ]
        if normalized_states:
            placeholders = ", ".join("?" for _ in normalized_states)
            clauses.append(f"state IN ({placeholders})")
            params.extend(normalized_states)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM local_asset_roots
                {where}
                ORDER BY updated_at DESC, resource_type ASC, resource_id ASC
                """,
                params,
            ).fetchall()
        return [self._decode_row(row) for row in rows]

    @staticmethod
    def _normalize_local_asset_state(state: object) -> str:
        normalized = str(state or "active").strip().lower()
        if normalized not in {"active", "cleaned", "orphaned"}:
            return "active"
        return normalized
