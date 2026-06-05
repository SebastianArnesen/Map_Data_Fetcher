from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from typing import Callable

from .catalog import KartkatalogCatalog
from .client import HttpClient
from .constants import ENRICH_BATCH_SIZE, ENRICH_MAX_WORKERS, ENRICH_PROGRESS_INTERVAL, ENRICHMENT_VERSION
from .index_cache import DatasetIndex, _needs_capabilities_reenrich
from .models import DatasetAvailability, DatasetRef
from .nedlasting import NedlastingClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EnrichStats:
    total: int
    skipped: int
    light_refresh: int
    full_refresh: int


@dataclass(frozen=True)
class EnrichOutcome:
    dataset: DatasetAvailability
    kind: str  # skip | light | full


class DiscoveryService:
    """
    High-level orchestrator.

    We keep startup fast by:
    - loading cached dataset availability if present
    - fetching dataset refs from the Kartkatalog sitemap (optional text search when provided)
    - progressively enriching datasets (capabilities -> areas -> projections/formats)
    """

    def __init__(self, http: HttpClient | None = None):
        self.http = http or HttpClient()
        self.nedlasting = NedlastingClient(self.http)
        self.catalog = KartkatalogCatalog(self.http)
        self.index = DatasetIndex()
        self.index.migrate_json_cache_if_empty()

    def load_cached(self) -> list[DatasetAvailability] | None:
        indexed = self.index.load_all()
        return indexed if indexed else None

    def fetch_dataset_refs(self, *, text: str = "", max_results: int = 10000) -> list[DatasetRef]:
        logger.info("Fetching dataset refs (max_results=%s)", max_results)
        if text.strip():
            refs, num_found = self.catalog.search(text=text, limit=max_results, offset=0)
            if refs:
                logger.info("Using Kartkatalog search (%s/%s refs)", len(refs), num_found)
                self.index.upsert_refs(refs)
                return refs

        refs = self.catalog.sitemap_refs(limit=max_results)
        logger.info("Using Kartkatalog sitemap (%s refs)", len(refs))
        self.index.upsert_refs(refs)
        return refs

    def load_indexed(self) -> list[DatasetAvailability]:
        return self.index.load_all()

    def enriched_uuids(self) -> set[str]:
        return self.index.enriched_uuids()

    def clear_cache(self) -> None:
        self.index.clear_all()

    def enrich_one(
        self,
        base: DatasetAvailability,
        cached: DatasetAvailability | None = None,
        *,
        write: bool = True,
    ) -> EnrichOutcome:
        """
        Fill capabilities + codelists. Marks login_required if we see 401/403.

        Uses Kartkatalog DateMetadataUpdated: if unchanged since last enrichment, skip Nedlasting calls.
        """
        d = base
        if cached is None or cached.metadata_uuid != d.metadata_uuid:
            cached = self.index.load_one(d.metadata_uuid)

        meta = None
        download_api_base = self.nedlasting.BASE
        try:
            meta = self.catalog.get_metadata(d.metadata_uuid)
            if meta is None:
                logger.warning("No Kartkatalog metadata for %s", d.metadata_uuid)
                return EnrichOutcome(d, "full")

            if title := meta.title:
                d.title = title
            d.categories = meta.categories
            d.original_categories = meta.original_categories
            d.catalog_metadata_updated = meta.metadata_updated
            download_api_base = meta.download_api_base or self.nedlasting.BASE

            if cached and _can_skip_nedlasting(cached, meta.metadata_updated):
                logger.debug("Skipping unchanged metadata for %s", d.metadata_uuid)
                return EnrichOutcome(cached, "skip")

            if cached and _can_light_refresh(cached, meta.metadata_updated):
                logger.debug("Light refresh (no download service) for %s", d.metadata_uuid)
                updated = _apply_catalog_fields(cached, meta, download_api_base)
                updated = self._light_nedlasting_refresh(updated, download_api_base)
                updated.enrichment_version = ENRICHMENT_VERSION
                if write:
                    self.index.upsert_one(updated, enriched=True)
                return EnrichOutcome(updated, "light")

            logger.debug("Enriching %s (%s)", d.title, d.metadata_uuid)
            d.download_api_base = download_api_base
            caps = self.nedlasting.capabilities(d.metadata_uuid, base_url=d.download_api_base)
            d.capabilities = caps
            if caps and caps.supports_area_selection:
                areas_by_type = self.nedlasting.areas(d.metadata_uuid, base_url=d.download_api_base)
                d.areas_by_type = areas_by_type
                d.area_types = set(areas_by_type.keys())
                embedded_formats = _formats_from_areas(areas_by_type)
                embedded_projections = _projections_from_areas(areas_by_type)
            else:
                d.areas_by_type = {}
                d.area_types = set()
                embedded_formats = []
                embedded_projections = []
            if caps and caps.supports_projection_selection:
                d.projections = embedded_projections or self.nedlasting.projections(
                    d.metadata_uuid, base_url=d.download_api_base
                )
            else:
                d.projections = []
            if caps and caps.supports_format_selection:
                d.formats = embedded_formats or self.nedlasting.formats(d.metadata_uuid, base_url=d.download_api_base)
            else:
                d.formats = []
            d.login_required = False
            d.enriched = True
            d.enrichment_version = ENRICHMENT_VERSION
            if write:
                self.index.upsert_one(d, enriched=True)
            return EnrichOutcome(d, "full")
        except PermissionError:
            updated = replace(
                d,
                login_required=True,
                enriched=True,
                enrichment_version=ENRICHMENT_VERSION,
                catalog_metadata_updated=meta.metadata_updated if meta else d.catalog_metadata_updated,
                download_api_base=download_api_base if meta else d.download_api_base,
            )
            if write:
                self.index.upsert_one(updated, enriched=True, last_error="Login required")
            return EnrichOutcome(updated, "full")

    def _light_nedlasting_refresh(
        self, ds: DatasetAvailability, download_api_base: str
    ) -> DatasetAvailability:
        caps = self.nedlasting.capabilities(ds.metadata_uuid, base_url=download_api_base)
        ds.capabilities = caps
        ds.download_api_base = download_api_base
        if not caps:
            ds.areas_by_type = {}
            ds.area_types = set()
            ds.formats = []
            ds.projections = []
            return ds
        return self._full_nedlasting_fill(ds, download_api_base)

    def _full_nedlasting_fill(self, ds: DatasetAvailability, download_api_base: str) -> DatasetAvailability:
        caps = ds.capabilities or self.nedlasting.capabilities(ds.metadata_uuid, base_url=download_api_base)
        ds.capabilities = caps
        ds.download_api_base = download_api_base
        if caps and caps.supports_area_selection:
            areas_by_type = self.nedlasting.areas(ds.metadata_uuid, base_url=download_api_base)
            ds.areas_by_type = areas_by_type
            ds.area_types = set(areas_by_type.keys())
            embedded_formats = _formats_from_areas(areas_by_type)
            embedded_projections = _projections_from_areas(areas_by_type)
        else:
            ds.areas_by_type = {}
            ds.area_types = set()
            embedded_formats = []
            embedded_projections = []
        if caps and caps.supports_projection_selection:
            ds.projections = embedded_projections or self.nedlasting.projections(
                ds.metadata_uuid, base_url=download_api_base
            )
        else:
            ds.projections = []
        if caps and caps.supports_format_selection:
            ds.formats = embedded_formats or self.nedlasting.formats(ds.metadata_uuid, base_url=download_api_base)
        else:
            ds.formats = []
        ds.login_required = False
        ds.enriched = True
        return ds

    def enrich_parallel(
        self,
        items: list[DatasetAvailability],
        *,
        cached_by_uuid: dict[str, DatasetAvailability],
        on_progress: Callable[[int, int, str], None] | None = None,
        cancel: threading.Event | None = None,
    ) -> tuple[list[DatasetAvailability], EnrichStats]:
        if not items:
            return [], EnrichStats(total=0, skipped=0, light_refresh=0, full_refresh=0)

        total = len(items)
        results_by_uuid: dict[str, DatasetAvailability] = {}
        pending: list[DatasetAvailability] = []
        pending_lock = threading.Lock()
        stats_lock = threading.Lock()

        def flush_pending() -> None:
            nonlocal pending
            with pending_lock:
                if not pending:
                    return
                batch = pending
                pending = []
            if batch:
                self.index.upsert_batch(batch, enriched=True)

        counters = {"skip": 0, "light": 0, "full": 0}
        last_title = {"value": ""}

        def work_item(item: DatasetAvailability) -> DatasetAvailability:
            if cancel and cancel.is_set():
                return cached_by_uuid.get(item.metadata_uuid, item)
            cached = cached_by_uuid.get(item.metadata_uuid)
            outcome = self.enrich_one(item, cached=cached, write=False)
            with stats_lock:
                counters[outcome.kind] = counters.get(outcome.kind, 0) + 1
                last_title["value"] = outcome.dataset.title
            if outcome.kind != "skip":
                should_flush = False
                with pending_lock:
                    pending.append(outcome.dataset)
                    if len(pending) >= ENRICH_BATCH_SIZE:
                        should_flush = True
                if should_flush:
                    flush_pending()
            return outcome.dataset

        completed = 0
        with ThreadPoolExecutor(max_workers=ENRICH_MAX_WORKERS) as pool:
            futures = [pool.submit(work_item, item) for item in items]
            try:
                for future in as_completed(futures):
                    if cancel and cancel.is_set():
                        break
                    completed += 1
                    try:
                        ds = future.result()
                        results_by_uuid[ds.metadata_uuid] = ds
                    except Exception:
                        logger.exception("Enrichment task failed")
                    if on_progress and (
                        completed == 1
                        or completed % ENRICH_PROGRESS_INTERVAL == 0
                        or completed == total
                    ):
                        title = last_title["value"]
                        suffix = f" — {title}" if title else ""
                        on_progress(completed, total, f"Checking metadata: {completed}/{total}{suffix}")
            finally:
                if cancel and cancel.is_set():
                    pool.shutdown(wait=False, cancel_futures=True)

        flush_pending()

        ordered = [results_by_uuid.get(item.metadata_uuid, item) for item in items]
        final_stats = EnrichStats(
            total=total,
            skipped=counters.get("skip", 0),
            light_refresh=counters.get("light", 0),
            full_refresh=counters.get("full", 0),
        )
        return ordered, final_stats


def _apply_catalog_fields(
    cached: DatasetAvailability, meta, download_api_base: str
) -> DatasetAvailability:
    cached.title = meta.title or cached.title
    cached.categories = meta.categories
    cached.original_categories = meta.original_categories
    cached.catalog_metadata_updated = meta.metadata_updated
    cached.download_api_base = download_api_base
    return cached


def _can_skip_nedlasting(cached: DatasetAvailability, metadata_updated: str | None) -> bool:
    if not cached.enriched or cached.enrichment_version < ENRICHMENT_VERSION:
        return False
    if not metadata_updated or not cached.catalog_metadata_updated:
        return False
    if metadata_updated != cached.catalog_metadata_updated:
        return False
    if _needs_area_reenrich(cached):
        return False
    if _needs_capabilities_reenrich(cached):
        return False
    return True


def _can_light_refresh(cached: DatasetAvailability, metadata_updated: str | None) -> bool:
    if not cached.enriched or cached.enrichment_version < ENRICHMENT_VERSION:
        return False
    if not metadata_updated or not cached.catalog_metadata_updated:
        return False
    if metadata_updated == cached.catalog_metadata_updated:
        return False
    if cached.capabilities is not None:
        return False
    return True


def _needs_area_reenrich(cached: DatasetAvailability) -> bool:
    caps = cached.capabilities
    return bool(caps and caps.supports_area_selection and not cached.areas_by_type)


def _formats_from_areas(areas_by_type) -> list:
    seen: set[str] = set()
    out = []
    for areas in areas_by_type.values():
        for area in areas:
            for fmt in area.formats:
                key = fmt.label.casefold()
                if key in seen:
                    continue
                seen.add(key)
                out.append(fmt)
    return out


def _projections_from_areas(areas_by_type) -> list:
    seen: set[str] = set()
    out = []
    for areas in areas_by_type.values():
        for area in areas:
            for projection in area.projections:
                if projection.code in seen:
                    continue
                seen.add(projection.code)
                out.append(projection)
    return out
