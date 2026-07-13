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


def test_ruter_entinelskyfritt_default_url() -> None:
    url = geojson_url_for_map_selection_layer("Ruter_entinelSkyfritt2018Uint16")
    assert url is not None
    assert url.endswith("/tema/Ruter_entinelSkyfritt2018Uint16.geojson")
    assert "Satellittbilder_100kmruter" not in url


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
    assert infer_source_epsg(layer_id="Ruter_entinelSkyfritt2018Uint16", projection_code=None) is None
    assert infer_source_epsg(layer_id="ruter_entinelskyfritt2018uint16", projection_code="25833") is None
    assert infer_source_epsg(layer_id="dtm-sjo-25", projection_code=None) == 4326
    assert infer_source_epsg(layer_id="dtm-sjo-50", projection_code=None) == 25833
    assert infer_source_epsg(layer_id="dybdedata_50m", projection_code=None) == 25833
    assert infer_source_epsg(layer_id="dybdedata_50m", projection_code="4326") == 25833


def test_normalize_grid_coordinates_passthrough() -> None:
    assert normalize_grid_coordinates(-10_000.0, 6_600_000.0, source_epsg=25832) == (-10_000.0, 6_600_000.0)
    assert normalize_grid_coordinates(1_100_000.0, 7_700_000.0, source_epsg=25835) == (1_100_000.0, 7_700_000.0)


def test_geojson_url_resolution_env_override() -> None:
    os.environ["GEONORGE_MAPSELECTION_GEOJSON_URL"] = "https://example.com/grid.geojson"
    try:
        assert geojson_url_for_map_selection_layer("raster-n250") == "https://example.com/grid.geojson"
    finally:
        os.environ.pop("GEONORGE_MAPSELECTION_GEOJSON_URL", None)


def test_normalize_area_code_for_mgrs_strips_t_prefix() -> None:
    pytest.importorskip("mgrs")
    from app.map_picker import _normalize_area_code_for_mgrs

    assert _normalize_area_code_for_mgrs("T33WXS") == "33WXS"


def test_match_area_grid_codes_uses_area_name_for_label() -> None:
    from PySide6.QtGui import QPainterPath

    from app.map_picker import GridCellShape, ParsedGridCell, match_area_grid_codes
    from geonorge.models import AreaOption

    path = QPainterPath()
    path.addRect(0, 0, 1, 1)
    shapes = {
        "7507-4": GridCellShape(
            code="7507-4",
            path_lonlat=path,
            bbox_lonlat=(0.0, 0.0, 1.0, 1.0),
        )
    }
    parsed = [
        ParsedGridCell(
            code="7507-4",
            rings=(((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 0.0)),),
            properties=(("n", "7507-4"),),
        )
    ]
    areas = [AreaOption(type="celle", code="7507-4", name="Cell A")]
    maps = match_area_grid_codes(shapes, parsed, areas)
    assert maps.area_to_grid["7507-4"] == "7507-4"
    assert maps.cell_labels["7507-4"] == "Cell A"


@pytest.mark.network
def test_dybdedata_50m_grid_matches_all_areas() -> None:
    from app.map_picker import build_grid_cell_shapes, match_area_grid_codes, parse_geojson_grid_cells
    from geonorge.models import AreaOption

    layer_id = "dybdedata_50m"
    metadata_uuid = "bbd687d0-d34f-4d95-9e60-27e330e0f76e"
    url = geojson_url_for_map_selection_layer(layer_id)
    assert url is not None
    assert url.endswith("/json/norge/dybdedata_50m.geojson")

    text = requests.get(url, timeout=60).text
    parsed = parse_geojson_grid_cells(text)
    assert len(parsed) == 49
    assert any(cell.code == "B0216" for cell in parsed)

    source_epsg = infer_source_epsg(layer_id=layer_id, projection_code=None)
    assert source_epsg == 25833
    shapes_list = build_grid_cell_shapes(parsed, source_epsg=source_epsg)
    shapes = {shape.code: shape for shape in shapes_list}
    assert len(shapes) == 49

    min_lon = min(s.bbox_lonlat[0] for s in shapes_list)
    min_lat = min(s.bbox_lonlat[1] for s in shapes_list)
    max_lon = max(s.bbox_lonlat[2] for s in shapes_list)
    max_lat = max(s.bbox_lonlat[3] for s in shapes_list)
    assert 0.0 <= min_lon <= max_lon <= 35.0
    assert 55.0 <= min_lat <= max_lat <= 73.0

    areas_raw = requests.get(
        f"https://nedlasting.geonorge.no/api/codelists/area/{metadata_uuid}",
        timeout=60,
    ).json()
    area_codes = [
        str(a.get("code") or a.get("Code"))
        for a in areas_raw
        if str(a.get("type") or a.get("Type") or "").lower() == "celle"
    ]
    assert len(area_codes) == 49

    areas = [AreaOption(type="celle", code=code, name=code) for code in area_codes]
    maps = match_area_grid_codes(shapes, parsed, areas)
    assert len(maps.area_to_grid) == 49
    assert len(shapes) - len(maps.grid_to_area) == 0
    assert maps.area_to_grid["B0216"] == "B0216"


@pytest.mark.network
def test_sentinel_skyfritt_grid_matches_all_areas() -> None:
    from app.map_picker import build_grid_cell_shapes, match_area_grid_codes, parse_geojson_grid_cells
    from geonorge.models import AreaOption

    layer_id = "Ruter_entinelSkyfritt2018Uint16"
    metadata_uuid = "60ecee84-bd74-430c-92dc-a1a01a05df9e"
    url = geojson_url_for_map_selection_layer(layer_id)
    assert url is not None
    assert url.endswith("/tema/Ruter_entinelSkyfritt2018Uint16.geojson")

    text = requests.get(url, timeout=60).text
    parsed = parse_geojson_grid_cells(text)
    assert len(parsed) == 88
    assert any(cell.code == "T32VKK" for cell in parsed)

    source_epsg = infer_source_epsg(layer_id=layer_id, projection_code=None)
    assert source_epsg is None
    shapes = {shape.code: shape for shape in build_grid_cell_shapes(parsed, source_epsg=source_epsg)}

    areas_raw = requests.get(
        f"https://nedlasting.geonorge.no/api/codelists/area/{metadata_uuid}",
        timeout=60,
    ).json()
    area_codes = [
        str(a.get("code") or a.get("Code"))
        for a in areas_raw
        if str(a.get("type") or a.get("Type") or "").lower() == "celle"
    ]
    assert len(area_codes) == 88

    areas = [AreaOption(type="celle", code=code, name=code) for code in area_codes]
    maps = match_area_grid_codes(shapes, parsed, areas)
    assert len(maps.area_to_grid) == 88
    assert len(shapes) - len(maps.grid_to_area) == 0
    assert maps.area_to_grid["T32VKK"] == "T32VKK"


@pytest.mark.network
def test_satellite_grid_maps_mgrs_area_codes() -> None:
    pytest.importorskip("mgrs")
    from app.map_picker import build_grid_cell_shapes, match_area_grid_codes, parse_geojson_grid_cells
    from geonorge.models import AreaOption

    url = geojson_url_for_map_selection_layer("satellittbilder-100kmruter-utm33")
    assert url is not None
    text = requests.get(url, timeout=60).text
    parsed = parse_geojson_grid_cells(text)
    shapes = {shape.code: shape for shape in build_grid_cell_shapes(parsed, source_epsg=25833)}
    areas = [AreaOption(type="celle", code="T33WXS", name="T33WXS")]
    maps = match_area_grid_codes(shapes, parsed, areas)
    assert maps.area_to_grid.get("T33WXS") is not None
    assert maps.cell_labels[maps.area_to_grid["T33WXS"]] == "T33WXS"


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


def test_fractional_zoom_sits_between_integer_levels() -> None:
    lon, lat = 10.75, 59.91
    x5, y5 = lonlat_to_global_px(lon, lat, 5.0)
    x55, y55 = lonlat_to_global_px(lon, lat, 5.5)
    x6, y6 = lonlat_to_global_px(lon, lat, 6.0)
    assert x5 < x55 < x6
    assert y5 < y55 < y6
    lon55, lat55 = global_px_to_lonlat(x55, y55, 5.5)
    assert abs(lon55 - lon) < 1e-6
    assert abs(lat55 - lat) < 1e-6

