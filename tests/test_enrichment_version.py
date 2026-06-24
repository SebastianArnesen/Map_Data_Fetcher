from __future__ import annotations

from geonorge.index_cache import _needs_capabilities_reenrich
from geonorge.map_selection import (
    geojson_url_for_map_selection_layer,
    infer_map_selection_layer,
    resolve_map_selection_layer,
)
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


def test_v4_cell_cache_with_inferred_title_does_not_need_capabilities_reenrich() -> None:
    ds = DatasetAvailability(
        metadata_uuid="d87fde8d-f151-4560-8aa1-7ecb6a5d90f4",
        title="N100 Raster (UTM33) - Rutevis",
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


def test_v4_unknown_cell_cache_still_needs_capabilities_reenrich() -> None:
    ds = DatasetAvailability(
        metadata_uuid="uuid-2",
        title="Some other raster",
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
    assert _needs_capabilities_reenrich(ds) is True


def test_infer_n100_raster_rutevis_layer() -> None:
    layer = infer_map_selection_layer(
        title="N100 Raster (UTM33) - Rutevis",
        metadata_uuid="d87fde8d-f151-4560-8aa1-7ecb6a5d90f4",
    )
    assert layer == "n100_raster_ruter"


def test_resolve_n100_raster_rutevis_layer_without_cached_capabilities_field() -> None:
    layer = resolve_map_selection_layer(
        map_selection_layer=None,
        title="N100 Raster (UTM33) - Rutevis",
        metadata_uuid="d87fde8d-f151-4560-8aa1-7ecb6a5d90f4",
    )
    assert layer == "n100_raster_ruter"
    url = geojson_url_for_map_selection_layer(layer)
    assert url is not None
    assert url.endswith("/n100_raster_ruter.geojson")
