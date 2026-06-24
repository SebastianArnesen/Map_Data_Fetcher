from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

from .cache import dataset_from_dict, dataset_to_dict, default_cache_dir, load_legacy_json_cache
from .constants import ENRICHMENT_VERSION
from .map_selection import resolve_map_selection_layer
from .models import DatasetAvailability, DatasetRef


def index_file_path() -> Path:
    d = default_cache_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d / "dataset_index.sqlite3"


def _download_service_flag(ds: DatasetAvailability) -> int | None:
    if not ds.enriched:
        return None
    if ds.capabilities is None:
        return 0
    return 1


def _needs_area_reenrich(ds: DatasetAvailability) -> bool:
    caps = ds.capabilities
    return bool(caps and caps.supports_area_selection and not ds.areas_by_type)


def _needs_capabilities_reenrich(ds: DatasetAvailability) -> bool:
    """Re-fetch Nedlasting capabilities when map_selection_layer is missing for cell datasets."""
    caps = ds.capabilities
    if not ds.enriched or not caps or not caps.supports_area_selection:
        return False
    if "celle" not in ds.area_types:
        return False
    if resolve_map_selection_layer(
        map_selection_layer=caps.map_selection_layer,
        title=ds.title,
        metadata_uuid=ds.metadata_uuid,
    ):
        return False
    return True


class DatasetIndex:
    def __init__(self, path: Path | None = None):
        self.path = path or index_file_path()
        self._write_lock = threading.Lock()
        self._ensure_schema()

    @staticmethod
    def cache_directory() -> Path:
        return default_cache_dir()

    def clear_all(self) -> None:
        """
        Reset local index database and legacy cache files (out-of-box state).

        On Windows, deleting an open SQLite file often fails with WinError 32.
        Prefer clearing the database contents in-place (DROP/CREATE) rather than
        unlinking the file.
        """
        with self._write_lock:
            # Clear the database in-place (robust vs file locking).
            try:
                with self._connect() as conn:
                    conn.execute("PRAGMA wal_checkpoint(FULL)")
                    conn.execute("DROP TABLE IF EXISTS datasets")
                    conn.execute("DROP TABLE IF EXISTS refs")
                    conn.execute("DROP TABLE IF EXISTS tags")
                    conn.execute("DROP TABLE IF EXISTS cache")
            except sqlite3.Error:
                # Best-effort fallback: if schema clearing fails, try removing files.
                for path in (self.path, Path(f"{self.path}-wal"), Path(f"{self.path}-shm")):
                    try:
                        if path.exists():
                            path.unlink()
                    except OSError:
                        pass

            # Remove legacy JSON cache if present.
            try:
                legacy = self.cache_directory() / "cache.json"
                if legacy.exists():
                    legacy.unlink()
            except OSError:
                pass

        # Recreate schema for fresh use.
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS datasets (
                    metadata_uuid TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    indexed_at REAL NOT NULL,
                    enriched_at REAL,
                    last_error TEXT,
                    catalog_metadata_updated TEXT,
                    enrichment_version INTEGER NOT NULL DEFAULT 0,
                    download_api_base TEXT,
                    has_download_service INTEGER
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_datasets_title ON datasets(title)")
            self._migrate_columns(conn)
            # Older runs stored enriched_at without Kartkatalog timestamps; force those back into the check queue.
            conn.execute(
                """
                UPDATE datasets
                SET enrichment_version = 0
                WHERE enriched_at IS NOT NULL
                  AND (catalog_metadata_updated IS NULL OR catalog_metadata_updated = '')
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_datasets_enriched ON datasets(enriched_at, enrichment_version)"
            )
            self._backfill_index_columns(conn)

    def _migrate_columns(self, conn: sqlite3.Connection) -> None:
        existing = {row[1] for row in conn.execute("PRAGMA table_info(datasets)")}
        additions = {
            "catalog_metadata_updated": "TEXT",
            "enrichment_version": "INTEGER DEFAULT 0",
            "download_api_base": "TEXT",
            "has_download_service": "INTEGER",
        }
        for name, ddl in additions.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE datasets ADD COLUMN {name} {ddl}")
        conn.execute(
            "UPDATE datasets SET enrichment_version = 0 WHERE enrichment_version IS NULL"
        )

    def _backfill_index_columns(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute(
            """
            SELECT metadata_uuid, data_json, enriched_at
            FROM datasets
            WHERE enriched_at IS NOT NULL
              AND (enrichment_version IS NULL OR enrichment_version < ? OR catalog_metadata_updated IS NULL)
            """,
            (ENRICHMENT_VERSION,),
        ).fetchall()
        for uuid, raw, enriched_at in rows:
            try:
                ds = dataset_from_dict(json.loads(raw))
            except Exception:
                continue
            ds.enriched = enriched_at is not None
            conn.execute(
                """
                UPDATE datasets SET
                    catalog_metadata_updated = ?,
                    enrichment_version = ?,
                    download_api_base = ?,
                    has_download_service = ?
                WHERE metadata_uuid = ?
                """,
                (
                    ds.catalog_metadata_updated,
                    int(ds.enrichment_version or 0),
                    ds.download_api_base,
                    _download_service_flag(ds),
                    uuid,
                ),
            )

    def migrate_json_cache_if_empty(self) -> None:
        with self._connect() as conn:
            existing = conn.execute("SELECT COUNT(*) FROM datasets").fetchone()[0]
        if existing:
            return
        cached = load_legacy_json_cache()
        if cached:
            self.upsert_batch(cached, enriched=True)

    def _hydrate(
        self,
        row_title: str,
        raw: str,
        enriched_at: float | None,
        catalog_metadata_updated: str | None,
        enrichment_version: int | None,
        download_api_base: str | None,
        has_download_service: int | None,
    ) -> DatasetAvailability | None:
        try:
            ds = dataset_from_dict(json.loads(raw))
        except Exception:
            return None
        json_title = (ds.title or "").strip()
        stored_title = (row_title or "").strip()
        if enriched_at is not None and json_title:
            ds.title = json_title
        elif stored_title:
            ds.title = stored_title
        elif json_title:
            ds.title = json_title
        ds.enriched = enriched_at is not None
        if catalog_metadata_updated:
            ds.catalog_metadata_updated = catalog_metadata_updated
        if enrichment_version is not None:
            ds.enrichment_version = int(enrichment_version)
        if download_api_base:
            ds.download_api_base = download_api_base
        return ds

    def load_all(self) -> list[DatasetAvailability]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT title, data_json, enriched_at, catalog_metadata_updated, enrichment_version,
                       download_api_base, has_download_service
                FROM datasets
                ORDER BY title COLLATE NOCASE
                """
            ).fetchall()
        out: list[DatasetAvailability] = []
        for row in rows:
            ds = self._hydrate(*row)
            if ds is not None:
                out.append(ds)
        return out

    def load_one(self, metadata_uuid: str) -> DatasetAvailability | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT title, data_json, enriched_at, catalog_metadata_updated, enrichment_version,
                       download_api_base, has_download_service
                FROM datasets WHERE metadata_uuid = ?
                """,
                (metadata_uuid,),
            ).fetchone()
        if not row:
            return None
        return self._hydrate(*row)

    def enriched_uuids(self) -> set[str]:
        """Datasets that do not need any Kartkatalog or Nedlasting refresh."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT metadata_uuid, data_json
                FROM datasets
                WHERE enriched_at IS NOT NULL
                  AND enrichment_version >= ?
                  AND catalog_metadata_updated IS NOT NULL
                  AND catalog_metadata_updated != ''
                """,
                (ENRICHMENT_VERSION,),
            ).fetchall()
        out: set[str] = set()
        for uuid, raw in rows:
            try:
                ds = dataset_from_dict(json.loads(raw))
            except Exception:
                continue
            if _needs_area_reenrich(ds):
                continue
            if _needs_capabilities_reenrich(ds):
                continue
            out.add(str(uuid))
        return out

    def upsert_refs(self, refs: list[DatasetRef]) -> None:
        if not refs:
            return
        now = time.time()
        with self._write_lock, self._connect() as conn:
            existing_rows = {
                row[0]: (row[1], row[2])
                for row in conn.execute(
                    "SELECT metadata_uuid, title, enriched_at FROM datasets"
                ).fetchall()
            }
            conn.execute("BEGIN")
            try:
                for ref in refs:
                    row = existing_rows.get(ref.metadata_uuid)
                    if row is None:
                        ds = DatasetAvailability(metadata_uuid=ref.metadata_uuid, title=ref.title)
                        conn.execute(
                            """
                            INSERT INTO datasets(
                                metadata_uuid, title, data_json, indexed_at, enriched_at, last_error,
                                catalog_metadata_updated, enrichment_version, download_api_base, has_download_service
                            ) VALUES (?, ?, ?, ?, NULL, NULL, NULL, 0, NULL, NULL)
                            """,
                            (
                                ds.metadata_uuid,
                                ds.title,
                                json.dumps(dataset_to_dict(ds), ensure_ascii=False),
                                now,
                            ),
                        )
                        continue
                    old_title, enriched_at = row
                    if enriched_at is not None:
                        # Keep Kartkatalog titles from enrichment; sitemap slugs are often wrong.
                        continue
                    new_title = ref.title or old_title
                    ds = DatasetAvailability(metadata_uuid=ref.metadata_uuid, title=new_title)
                    conn.execute(
                        """
                        INSERT INTO datasets(
                            metadata_uuid, title, data_json, indexed_at, enriched_at, last_error,
                            catalog_metadata_updated, enrichment_version, download_api_base, has_download_service
                        ) VALUES (?, ?, ?, ?, NULL, NULL, NULL, 0, NULL, NULL)
                        ON CONFLICT(metadata_uuid) DO UPDATE SET
                            title = excluded.title,
                            data_json = excluded.data_json,
                            indexed_at = excluded.indexed_at
                        """,
                        (
                            ds.metadata_uuid,
                            ds.title,
                            json.dumps(dataset_to_dict(ds), ensure_ascii=False),
                            now,
                        ),
                    )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

    def _upsert_params(self, ds: DatasetAvailability, *, enriched: bool, last_error: str | None) -> tuple:
        now = time.time()
        ds.enriched = enriched or ds.enriched
        return (
            ds.metadata_uuid,
            ds.title,
            json.dumps(dataset_to_dict(ds), ensure_ascii=False),
            now,
            now if enriched else None,
            last_error,
            ds.catalog_metadata_updated,
            ds.enrichment_version,
            ds.download_api_base,
            _download_service_flag(ds),
        )

    def upsert_one(self, ds: DatasetAvailability, *, enriched: bool, last_error: str | None = None) -> None:
        with self._write_lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO datasets(
                    metadata_uuid, title, data_json, indexed_at, enriched_at, last_error,
                    catalog_metadata_updated, enrichment_version, download_api_base, has_download_service
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(metadata_uuid) DO UPDATE SET
                    title = excluded.title,
                    data_json = excluded.data_json,
                    indexed_at = excluded.indexed_at,
                    enriched_at = CASE WHEN excluded.enriched_at IS NULL THEN datasets.enriched_at ELSE excluded.enriched_at END,
                    last_error = excluded.last_error,
                    catalog_metadata_updated = excluded.catalog_metadata_updated,
                    enrichment_version = excluded.enrichment_version,
                    download_api_base = excluded.download_api_base,
                    has_download_service = excluded.has_download_service
                """,
                self._upsert_params(ds, enriched=enriched, last_error=last_error),
            )

    def upsert_batch(self, items: list[DatasetAvailability], *, enriched: bool) -> None:
        if not items:
            return
        rows = [self._upsert_params(ds, enriched=enriched, last_error=None) for ds in items]
        with self._write_lock, self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO datasets(
                    metadata_uuid, title, data_json, indexed_at, enriched_at, last_error,
                    catalog_metadata_updated, enrichment_version, download_api_base, has_download_service
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(metadata_uuid) DO UPDATE SET
                    title = excluded.title,
                    data_json = excluded.data_json,
                    indexed_at = excluded.indexed_at,
                    enriched_at = CASE WHEN excluded.enriched_at IS NULL THEN datasets.enriched_at ELSE excluded.enriched_at END,
                    last_error = excluded.last_error,
                    catalog_metadata_updated = excluded.catalog_metadata_updated,
                    enrichment_version = excluded.enrichment_version,
                    download_api_base = excluded.download_api_base,
                    has_download_service = excluded.has_download_service
                """,
                rows,
            )

    def upsert_many(self, items: list[DatasetAvailability], *, enriched: bool) -> None:
        for offset in range(0, len(items), 200):
            self.upsert_batch(items[offset : offset + 200], enriched=enriched)
