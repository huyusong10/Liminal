from __future__ import annotations

import json
import logging

from loopora.db_shared import logger
from loopora.diagnostics import log_event
from loopora.settings import app_home
from loopora.utils import utc_now


class RepositoryBundleRecordsMixin:
    def create_bundle(self, payload: dict) -> dict:
        now = utc_now()
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO bundle_definitions (
                    id, name, description, collaboration_summary, workdir, loop_id, orchestration_id,
                    role_definition_ids_json, source_bundle_id, revision, imported_from_path,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["id"],
                    payload["name"],
                    payload.get("description", ""),
                    payload.get("collaboration_summary", ""),
                    payload.get("workdir", ""),
                    payload.get("loop_id", ""),
                    payload.get("orchestration_id", ""),
                    json.dumps(payload.get("role_definition_ids", []), ensure_ascii=False),
                    payload.get("source_bundle_id", ""),
                    int(payload.get("revision", 1) or 1),
                    payload.get("imported_from_path", ""),
                    now,
                    now,
                ),
            )
            self._replace_bundle_asset_ownership_for_connection(connection, payload, now=now)
            self._upsert_bundle_local_asset_root_for_connection(connection, payload, now=now)
        bundle = self.get_bundle(payload["id"])
        log_event(
            logger,
            logging.INFO,
            "db.bundle.created",
            "Persisted bundle definition",
            bundle_id=payload["id"],
            bundle_name=payload["name"],
            loop_id=payload.get("loop_id", ""),
            orchestration_id=payload.get("orchestration_id", ""),
        )
        return bundle

    def update_bundle(self, bundle_id: str, payload: dict) -> dict | None:
        now = utc_now()
        with self.transaction() as connection:
            row = connection.execute("SELECT 1 FROM bundle_definitions WHERE id = ?", (bundle_id,)).fetchone()
            if row is None:
                return None
            connection.execute(
                """
                UPDATE bundle_definitions
                SET name = ?, description = ?, collaboration_summary = ?, workdir = ?, loop_id = ?, orchestration_id = ?,
                    role_definition_ids_json = ?, source_bundle_id = ?, revision = ?, imported_from_path = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    payload["name"],
                    payload.get("description", ""),
                    payload.get("collaboration_summary", ""),
                    payload.get("workdir", ""),
                    payload.get("loop_id", ""),
                    payload.get("orchestration_id", ""),
                    json.dumps(payload.get("role_definition_ids", []), ensure_ascii=False),
                    payload.get("source_bundle_id", ""),
                    int(payload.get("revision", 1) or 1),
                    payload.get("imported_from_path", ""),
                    now,
                    bundle_id,
                ),
            )
            ownership_payload = {**payload, "id": bundle_id}
            self._replace_bundle_asset_ownership_for_connection(connection, ownership_payload, now=now)
            self._upsert_bundle_local_asset_root_for_connection(connection, ownership_payload, now=now)
        bundle = self.get_bundle(bundle_id)
        log_event(
            logger,
            logging.INFO,
            "db.bundle.updated",
            "Updated bundle definition",
            bundle_id=bundle_id,
            bundle_name=payload["name"],
            loop_id=payload.get("loop_id", ""),
            orchestration_id=payload.get("orchestration_id", ""),
        )
        return bundle

    def get_bundle(self, bundle_id: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM bundle_definitions WHERE id = ?", (bundle_id,)).fetchone()
        return self._decode_row(row) if row else None

    def list_bundles(self) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM bundle_definitions ORDER BY updated_at DESC, created_at DESC").fetchall()
        return [self._decode_row(row) for row in rows]

    def delete_bundle(self, bundle_id: str) -> bool:
        with self.transaction() as connection:
            row = connection.execute("SELECT 1 FROM bundle_definitions WHERE id = ?", (bundle_id,)).fetchone()
            if row is None:
                return False
            connection.execute("DELETE FROM bundle_definitions WHERE id = ?", (bundle_id,))
        log_event(
            logger,
            logging.INFO,
            "db.bundle.deleted",
            "Deleted bundle definition",
            bundle_id=bundle_id,
        )
        return True

    def list_bundle_asset_ownership(self, bundle_id: str) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM bundle_asset_ownership
                WHERE bundle_id = ?
                ORDER BY asset_type ASC, asset_id ASC
                """,
                (bundle_id,),
            ).fetchall()
        return [self._decode_row(row) for row in rows]

    def get_bundle_asset_owner(self, asset_type: str, asset_id: str) -> str:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT bundle_id FROM bundle_asset_ownership
                WHERE asset_type = ? AND asset_id = ?
                """,
                (asset_type, asset_id),
            ).fetchone()
        return str(row["bundle_id"]) if row else ""

    def delete_bundle_graph(self, bundle_id: str) -> bool:
        with self.transaction() as connection:
            bundle = connection.execute(
                "SELECT * FROM bundle_definitions WHERE id = ?",
                (bundle_id,),
            ).fetchone()
            if bundle is None:
                return False
            ownership_rows = connection.execute(
                """
                SELECT asset_type, asset_id FROM bundle_asset_ownership
                WHERE bundle_id = ?
                """,
                (bundle_id,),
            ).fetchall()
            assets = {
                (str(row["asset_type"] or "").strip(), str(row["asset_id"] or "").strip())
                for row in ownership_rows
                if str(row["asset_type"] or "").strip() and str(row["asset_id"] or "").strip()
            }
            loop_id = next((asset_id for asset_type, asset_id in assets if asset_type == "loop"), "")
            orchestration_id = next((asset_id for asset_type, asset_id in assets if asset_type == "orchestration"), "")
            role_definition_ids = sorted(asset_id for asset_type, asset_id in assets if asset_type == "role_definition")
            if loop_id:
                connection.execute(
                    "DELETE FROM run_events WHERE run_id IN (SELECT id FROM loop_runs WHERE loop_id = ?)",
                    (loop_id,),
                )
                connection.execute(
                    "DELETE FROM workdir_locks WHERE run_id IN (SELECT id FROM loop_runs WHERE loop_id = ?)",
                    (loop_id,),
                )
                connection.execute("DELETE FROM loop_runs WHERE loop_id = ?", (loop_id,))
                connection.execute("DELETE FROM loop_definitions WHERE id = ?", (loop_id,))
            if orchestration_id:
                connection.execute("DELETE FROM orchestration_definitions WHERE id = ?", (orchestration_id,))
            for role_definition_id in role_definition_ids:
                connection.execute("DELETE FROM role_definitions WHERE id = ?", (role_definition_id,))
            connection.execute("DELETE FROM bundle_asset_ownership WHERE bundle_id = ?", (bundle_id,))
            connection.execute("DELETE FROM bundle_definitions WHERE id = ?", (bundle_id,))
        log_event(
            logger,
            logging.INFO,
            "db.bundle_graph.deleted",
            "Deleted bundle-owned record graph",
            bundle_id=bundle_id,
            loop_id=loop_id,
            orchestration_id=orchestration_id,
            role_definition_count=len(role_definition_ids),
        )
        return True

    def replace_bundle_graph(self, bundle_id: str, payload: dict) -> bool:
        now = utc_now()
        with self.transaction() as connection:
            bundle = connection.execute(
                "SELECT * FROM bundle_definitions WHERE id = ?",
                (bundle_id,),
            ).fetchone()
            if bundle is None:
                return False
            old_assets = {
                (str(row["asset_type"] or "").strip(), str(row["asset_id"] or "").strip())
                for row in connection.execute(
                    """
                    SELECT asset_type, asset_id FROM bundle_asset_ownership
                    WHERE bundle_id = ?
                    """,
                    (bundle_id,),
                ).fetchall()
                if str(row["asset_type"] or "").strip() and str(row["asset_id"] or "").strip()
            }
            linked_old_assets = set(self._bundle_asset_rows_from_bundle_row(bundle))
            missing_ownership = sorted(linked_old_assets - old_assets)
            if missing_ownership:
                formatted = ", ".join(f"{asset_type}:{asset_id}" for asset_type, asset_id in missing_ownership)
                raise ValueError(f"bundle graph is missing ownership for linked assets: {formatted}")

            new_payload = {**payload, "id": bundle_id}
            new_assets = set(self._bundle_asset_rows_from_payload(new_payload))
            assets_to_delete = old_assets - new_assets

            connection.execute(
                """
                UPDATE bundle_definitions
                SET name = ?, description = ?, collaboration_summary = ?, workdir = ?, loop_id = ?, orchestration_id = ?,
                    role_definition_ids_json = ?, source_bundle_id = ?, revision = ?, imported_from_path = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    payload["name"],
                    payload.get("description", ""),
                    payload.get("collaboration_summary", ""),
                    payload.get("workdir", ""),
                    payload.get("loop_id", ""),
                    payload.get("orchestration_id", ""),
                    json.dumps(payload.get("role_definition_ids", []), ensure_ascii=False),
                    payload.get("source_bundle_id", ""),
                    int(payload.get("revision", 1) or 1),
                    payload.get("imported_from_path", ""),
                    now,
                    bundle_id,
                ),
            )
            self._delete_owned_asset_rows_for_connection(connection, assets_to_delete)
            self._replace_bundle_asset_ownership_for_connection(connection, new_payload, now=now)
            self._upsert_bundle_local_asset_root_for_connection(connection, new_payload, now=now)
        log_event(
            logger,
            logging.INFO,
            "db.bundle_graph.replaced",
            "Replaced bundle-owned record graph",
            bundle_id=bundle_id,
            old_asset_count=len(old_assets),
            new_asset_count=len(new_assets),
        )
        return True

    @staticmethod
    def _bundle_asset_rows_from_payload(payload: dict) -> list[tuple[str, str]]:
        rows: list[tuple[str, str]] = []
        loop_id = str(payload.get("loop_id") or "").strip()
        if loop_id:
            rows.append(("loop", loop_id))
        orchestration_id = str(payload.get("orchestration_id") or "").strip()
        if orchestration_id:
            rows.append(("orchestration", orchestration_id))
        for role_definition_id in payload.get("role_definition_ids") or []:
            normalized = str(role_definition_id or "").strip()
            if normalized:
                rows.append(("role_definition", normalized))
        return rows

    @staticmethod
    def _bundle_asset_rows_from_bundle_row(bundle) -> list[tuple[str, str]]:
        rows: list[tuple[str, str]] = []
        loop_id = str(bundle["loop_id"] or "").strip()
        if loop_id:
            rows.append(("loop", loop_id))
        orchestration_id = str(bundle["orchestration_id"] or "").strip()
        if orchestration_id:
            rows.append(("orchestration", orchestration_id))
        try:
            role_definition_ids = json.loads(str(bundle["role_definition_ids_json"] or "[]"))
        except json.JSONDecodeError:
            role_definition_ids = []
        for role_definition_id in role_definition_ids if isinstance(role_definition_ids, list) else []:
            normalized = str(role_definition_id or "").strip()
            if normalized:
                rows.append(("role_definition", normalized))
        return rows

    @staticmethod
    def _delete_owned_asset_rows_for_connection(connection, assets: set[tuple[str, str]]) -> None:
        loop_ids = sorted(asset_id for asset_type, asset_id in assets if asset_type == "loop")
        orchestration_ids = sorted(asset_id for asset_type, asset_id in assets if asset_type == "orchestration")
        role_definition_ids = sorted(asset_id for asset_type, asset_id in assets if asset_type == "role_definition")
        for loop_id in loop_ids:
            connection.execute(
                "DELETE FROM run_events WHERE run_id IN (SELECT id FROM loop_runs WHERE loop_id = ?)",
                (loop_id,),
            )
            connection.execute(
                "DELETE FROM workdir_locks WHERE run_id IN (SELECT id FROM loop_runs WHERE loop_id = ?)",
                (loop_id,),
            )
            connection.execute("DELETE FROM loop_runs WHERE loop_id = ?", (loop_id,))
            connection.execute("DELETE FROM loop_definitions WHERE id = ?", (loop_id,))
        for orchestration_id in orchestration_ids:
            connection.execute("DELETE FROM orchestration_definitions WHERE id = ?", (orchestration_id,))
        for role_definition_id in role_definition_ids:
            connection.execute("DELETE FROM role_definitions WHERE id = ?", (role_definition_id,))

    def _replace_bundle_asset_ownership_for_connection(
        self,
        connection,
        payload: dict,
        *,
        now: str,
    ) -> None:
        bundle_id = str(payload.get("id") or "").strip()
        if not bundle_id:
            return
        connection.execute("DELETE FROM bundle_asset_ownership WHERE bundle_id = ?", (bundle_id,))
        for asset_type, asset_id in self._bundle_asset_rows_from_payload(payload):
            connection.execute(
                """
                INSERT INTO bundle_asset_ownership (bundle_id, asset_type, asset_id, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (bundle_id, asset_type, asset_id, now),
            )

    @staticmethod
    def _upsert_bundle_local_asset_root_for_connection(connection, payload: dict, *, now: str) -> None:
        bundle_id = str(payload.get("id") or "").strip()
        if not bundle_id:
            return
        connection.execute(
            """
            INSERT INTO local_asset_roots
                (resource_type, resource_id, path, workdir, owner_id, state, updated_at)
            VALUES ('bundle', ?, ?, ?, ?, 'active', ?)
            ON CONFLICT(resource_type, resource_id, path) DO UPDATE SET
                workdir = excluded.workdir,
                owner_id = excluded.owner_id,
                state = 'active',
                updated_at = excluded.updated_at
            """,
            (
                bundle_id,
                str(app_home() / "bundles" / bundle_id),
                str(payload.get("workdir") or ""),
                bundle_id,
                now,
            ),
        )
