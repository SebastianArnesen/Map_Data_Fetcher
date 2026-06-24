from __future__ import annotations

import os

import pytest
import requests
from PySide6.QtGui import QPainterPath

from app.map_picker import (
    build_grid_cell_shapes,
    global_px_to_lonlat,
    lonlat_to_global_px,
    parse_geojson_grid_cells,
)
from geonorge.map_selection import (
    geojson_url_for_map_selection_layer,
    infer_source_epsg,
    normalize_grid_coordinates,
)
from geonorge.models import DatasetCapabilities


def test_capabilities_holds_map_selection_layer() -> None:
    caps = DatasetCapabilities(
        supports_area_selection=True,
        supports_format_selection=True,
        supports_projection_selection=True,
        supports_polygon_selection=False,
        map_selection_layer="raster-n250",
    )
    assert caps.map_selection_layer == "raster-n250"


def test_dtm_dekning_utm32_default_url() -> None:
    url = geojson_url_for_map_selection_layer("dtm-dekning-utm32")
    assert url is not None
    assert url.endswith("/utm32.geojson")
    assert "geonorge-nkg.atkv3-prod.kartverket.cloud" in url


def test_dtm_svalbard_default_url() -> None:
    url = geojson_url_for_map_selection_layer("dtm-svalbard")
    assert url is not None
    assert url.endswith("/svalbard/terrengmodellgr_Svalbard.json")


def test_satellittbilder_100kmruter_default_url() -> None:
    url = geojson_url_for_map_selection_layer("Satellittbilder-100kmruter-utm33")
    assert url is not None
    assert url.endswith("/Satellittbilder_100kmruter_ETRS89utm33.json")


def test_raster_n250_default_url() -> None:
    url = geojson_url_for_map_selection_layer("raster-n250")
    assert url is not None
    assert url.endswith("/raster/n250_ny.geojson")


def test_n100_raster_ruter_default_url() -> None:
    url = geojson_url_for_map_selection_layer("n100_raster_ruter")
    assert url is not None
    assert url.endswith("/raster/n100_raster_ruter.geojson")


def test_dtm_sjo_25_default_url() -> None:
    url = geojson_url_for_map_selection_layer("dtm-sjo-25")
    assert url is not None
    assert url.endswith("/sjo/celler/dtm_25m.json")


def test_dtm_sjo_5_and_50_default_urls() -> None:
    u5 = geojson_url_for_map_selection_layer("dtm-sjo-5")
    u50 = geojson_url_for_map_selection_layer("dtm-sjo-50")
    assert u5 is not None and u5.endswith("/sjo/celler/dtm_05m.json")
    assert u50 is not None and u50.endswith("/sjo/celler/dtm_50m.json")


def test_dybdedata_50m_default_url() -> None:
    url = geojson_url_for_map_selection_layer("dybdedata_50m")
    assert url is not None
    assert url.endswith("/json/norge/dybdedata_50m.geojson")


def test_infer_source_epsg_from_layer_and_projection() -> None:
    assert infer_source_epsg(layer_id="dtm-dekning-utm32", projection_code=None) == 25833
    assert infer_source_epsg(layer_id="dtm-dekning-utm35", projection_code="25835") == 25833
    assert infer_source_epsg(layer_id="dtm-svalbard", projection_code="25833") is None
    assert infer_source_epsg(layer_id=None, projection_code="25833") == 25833
    assert infer_source_epsg(layer_id="raster-n250", projection_code=None) == 25833
    assert infer_source_epsg(layer_id="raster-32", projection_code=None) == 25833
    assert infer_source_epsg(layer_id="raster-35", projection_code="25835") == 25833
    assert infer_source_epsg(layer_id="Satellittbilder-100kmruter-utm33", projection_code=None) == 25833
    assert infer_source_epsg(layer_id="dtm-sjo-25", projection_code=None) == 4326
    assert infer_source_epsg(layer_id="dtm-sjo-50", projection_code=None) == 25833


def test_normalize_grid_coordinates_passthrough() -> None:
    assert normalize_grid_coordinates(-10_000.0, 6_600_000.0, source_epsg=25832) == (-10_000.0, 6_600_000.0)
    assert normalize_grid_coordinates(1_100_000.0, 7_700_000.0, source_epsg=25835) == (1_100_000.0, 7_700_000.0)


def test_geojson_url_resolution_env_override() -> None:
    os.environ["GEONORGE_MAPSELECTION_GEOJSON_URL"] = "https://example.com/grid.geojson"
    try:
        assert geojson_url_for_map_selection_layer("raster-n250") == "https://example.com/grid.geojson"
    finally:
        os.environ.pop("GEONORGE_MAPSELECTION_GEOJSON_URL", None)


@pytest.mark.network
def test_svalbard_multipolygon_uses_separate_subpaths() -> None:
    url = geojson_url_for_map_selection_layer("dtm-svalbard")
    assert url is not None
    text = requests.get(url, timeout=60).text
    parsed = parse_geojson_grid_cells(text, allowed_codes=None, source_epsg=None)
    shapes = build_grid_cell_shapes(parsed, source_epsg=None)
    cell = next(s for s in shapes if s.code == "25161")
    move_tos = sum(
        1
        for i in range(cell.path_lonlat.elementCount())
        if cell.path_lonlat.elementAt(i).type == QPainterPath.ElementType.MoveToElement
    )
    assert move_tos >= 2


def test_webmercator_roundtrip_is_reasonable() -> None:
    lon, lat, zoom = 10.75, 59.91, 10
    x, y = lonlat_to_global_px(lon, lat, zoom)
    lon2, lat2 = global_px_to_lonlat(x, y, zoom)
    assert abs(lon2 - lon) < 1e-6
    assert abs(lat2 - lat) < 1e-6

