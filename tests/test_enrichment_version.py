from __future__ import annotations

from geonorge.index_cache import _needs_capabilities_reenrich
from geonorge.models import DatasetAvailability, DatasetCapabilities


def test_legacy_v3_cell_cache_needs_capabilities_reenrich() -> None:
    ds = DatasetAvailability(
        metadata_uuid="uuid-1",
        title="Raster",
        enriched=True,
        enrichment_version=3,
        capabilities=DatasetCapabilities(
            supports_area_selection=True,
            supports_format_selection=True,
            supports_projection_selection=True,
            supports_polygon_selection=False,
            map_selection_layer=None,
        ),
    )
    ds.area_types = {"celle"}
    assert _needs_capabilities_reenrich(ds) is True


def test_v4_cell_cache_does_not_need_capabilities_reenrich() -> None:
    ds = DatasetAvailability(
        metadata_uuid="uuid-2",
        title="Raster",
        enriched=True,
        enrichment_version=4,
        capabilities=DatasetCapabilities(
            supports_area_selection=True,
            supports_format_selection=True,
            supports_projection_selection=True,
            supports_polygon_selection=False,
            map_selection_layer=None,
        ),
    )
    ds.area_types = {"celle"}
    assert _needs_capabilities_reenrich(ds) is False
