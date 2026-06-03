from __future__ import annotations

import os

# Kartverket cloud GeoJSON grids for map cell selection (Velg fra kartblad).
_GEONORGE_NKG_DEKNING_BASE = "https://geonorge-nkg.atkv3-prod.kartverket.cloud/json/dekning"
_GEONORGE_NKG_DTM_GRID_BASE = f"{_GEONORGE_NKG_DEKNING_BASE}/dtm"
_GEONORGE_NKG_RASTER_GRID_BASE = f"{_GEONORGE_NKG_DEKNING_BASE}/raster"

# Kartverket serves utm32/utm33/utm35.geojson with coordinates in EUREF89 UTM zone 33
# (EPSG:25833), regardless of filename. Using zone 32/35 EPSG codes misaligns the grid.
_DTM_GRID_GEOJSON_EPSG = 25833


def infer_source_epsg(*, layer_id: str | None = None, projection_code: str | None = None) -> int | None:
    """EPSG code for projected GeoJSON coordinates."""
    lid = (layer_id or "").strip().casefold()
    if lid == "dtm-svalbard":
        return None
    if lid.startswith("dtm-dekning-utm"):
        return _DTM_GRID_GEOJSON_EPSG
    if lid == "raster-32":
        return 25832
    if lid == "raster-35":
        return 25835
    if lid.startswith("raster-") or lid.startswith("n50_raster") or lid.startswith("n100_raster"):
        return 25833
    if lid.startswith("satellittbilder-") or lid.startswith("ruter_"):
        return 25833
    if projection_code and str(projection_code).isdigit():
        return int(projection_code)
    return None


def normalize_grid_coordinates(x: float, y: float, *, source_epsg: int) -> tuple[float, float]:
    """
    Placeholder hook for any future normalization of grid coordinates.
    For now, we trust the published GeoJSON coordinates as-is.
    """
    return x, y


def geojson_url_for_map_selection_layer(layer_id: str) -> str | None:
    """
    Resolve a Download API `mapSelectionLayer` id (e.g. "raster-n250") into a
    GeoJSON URL containing the selectable grid polygons.
    """
    raw = (layer_id or "").strip()
    if not raw:
        return None
    layer = raw.casefold()

    # Global override (useful if the published URLs change).
    if url := (os.environ.get("GEONORGE_MAPSELECTION_GEOJSON_URL") or "").strip():
        return url

    # Per-layer override. Example:
    #   set GEONORGE_MAPSELECTION_LAYER_URL_RASTER_N250=https://.../n250.geojson
    env_key = "GEONORGE_MAPSELECTION_LAYER_URL_" + layer.upper().replace("-", "_")
    if url := (os.environ.get(env_key) or "").strip():
        return url

    # Best-effort defaults. These are intentionally conservative; if a layer is
    # unknown, return None and let the UI fall back to list-only selection.
    defaults: dict[str, str] = {
        "dtm-dekning-utm32": f"{_GEONORGE_NKG_DTM_GRID_BASE}/utm32.geojson",
        "dtm-dekning-utm33": f"{_GEONORGE_NKG_DTM_GRID_BASE}/utm33.geojson",
        "dtm-dekning-utm35": f"{_GEONORGE_NKG_DTM_GRID_BASE}/utm35.geojson",
        "dtm-dekning-utm33-100km": f"{_GEONORGE_NKG_DTM_GRID_BASE}/utm33-100km.geojson",
        "dtm-svalbard": f"{_GEONORGE_NKG_DEKNING_BASE}/svalbard/terrengmodellgr_Svalbard.json",
        "raster-n250": f"{_GEONORGE_NKG_RASTER_GRID_BASE}/n250.geojson",
        "raster-n500": f"{_GEONORGE_NKG_RASTER_GRID_BASE}/n500.geojson",
        "raster-n1000": f"{_GEONORGE_NKG_RASTER_GRID_BASE}/n1000.geojson",
        "raster-32": f"{_GEONORGE_NKG_RASTER_GRID_BASE}/32.geojson",
        "raster-33": f"{_GEONORGE_NKG_RASTER_GRID_BASE}/33.geojson",
        "raster-35": f"{_GEONORGE_NKG_RASTER_GRID_BASE}/35.geojson",
        "n50_raster_regionsvis": f"{_GEONORGE_NKG_RASTER_GRID_BASE}/n50.geojson",
        "n50_raster_ruter": f"{_GEONORGE_NKG_RASTER_GRID_BASE}/n50.geojson",
        "satellittbilder-100kmruter-utm33": (
            f"{_GEONORGE_NKG_DEKNING_BASE}/Satellittbilder_100kmruter_ETRS89utm33.json"
        ),
        # Download API typo layer id; same 100 km grid as other Sentinel skyfritt products.
        "ruter_entinelskyfritt2018uint16": (
            f"{_GEONORGE_NKG_DEKNING_BASE}/Satellittbilder_100kmruter_ETRS89utm33.json"
        ),
    }
    return defaults.get(layer)

