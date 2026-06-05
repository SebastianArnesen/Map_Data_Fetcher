from __future__ import annotations

import os

# Kartverket cloud GeoJSON grids for map cell selection (Velg fra kartblad).
# Layer id → path mappings are taken from geonorge-nkg geoportal/nedlasting.html.
_GEONORGE_NKG_BASE = "https://geonorge-nkg.atkv3-prod.kartverket.cloud"
_GEONORGE_NKG_DEKNING_BASE = f"{_GEONORGE_NKG_BASE}/json/dekning"
_GEONORGE_NKG_DTM_GRID_BASE = f"{_GEONORGE_NKG_DEKNING_BASE}/dtm"
_GEONORGE_NKG_RASTER_GRID_BASE = f"{_GEONORGE_NKG_DEKNING_BASE}/raster"
_GEONORGE_NKG_SJO_CELLER_BASE = f"{_GEONORGE_NKG_DEKNING_BASE}/sjo/celler"

# Kartverket serves utm32/utm33/utm35.geojson (and raster/32|33|35.geojson) with
# coordinates in EUREF89 UTM zone 33 (EPSG:25833), regardless of filename.
# Using zone 32/35 EPSG codes misaligns the grid (too far left/right on the map).
_GRID_GEOJSON_EPSG = 25833

# Layers published in WGS84 geographic coordinates (per geoportal epsgCode).
_WGS84_LAYERS = frozenset(
    {
        "dtm-sjo-5",
        "dtm-sjo-25",
        "dybdedata_50m",
        "hovedserie_ny",
        "havnekart_ny",
        "kystkart_ny",
        "overseilingskart_ny",
        "svalbardkart_ny",
    }
)


def _kng_url(path: str) -> str:
    return f"{_GEONORGE_NKG_BASE}{path}"


def infer_source_epsg(*, layer_id: str | None = None, projection_code: str | None = None) -> int | None:
    """EPSG code for projected GeoJSON coordinates."""
    lid = (layer_id or "").strip().casefold()
    if lid == "dtm-svalbard":
        return None
    if lid in _WGS84_LAYERS:
        return 4326
    if lid in ("dtm-sjo", "dtm-sjo-50"):
        return 25833
    if lid.startswith("dtm-dekning-utm"):
        return _GRID_GEOJSON_EPSG
    if (
        lid in ("raster-32", "raster-33", "raster-35")
        or lid.startswith("raster-")
        or lid.startswith("n50_raster")
        or lid.startswith("n100_raster")
    ):
        return _GRID_GEOJSON_EPSG
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

    defaults: dict[str, str] = {
        # Land DTM grids
        "dtm-dekning-utm32": f"{_GEONORGE_NKG_DTM_GRID_BASE}/utm32.geojson",
        "dtm-dekning-utm33": f"{_GEONORGE_NKG_DTM_GRID_BASE}/utm33.geojson",
        "dtm-dekning-utm35": f"{_GEONORGE_NKG_DTM_GRID_BASE}/utm35.geojson",
        "dtm-dekning-utm33-100km": f"{_GEONORGE_NKG_DTM_GRID_BASE}/utm33-100km.geojson",
        "dtm-svalbard": f"{_GEONORGE_NKG_DEKNING_BASE}/svalbard/terrengmodellgr_Svalbard.json",
        # Sea/bathymetry DTM grids (Dybdedata)
        "dtm-sjo": f"{_GEONORGE_NKG_SJO_CELLER_BASE}/dtm50.geojson",
        "dtm-sjo-5": f"{_GEONORGE_NKG_SJO_CELLER_BASE}/dtm_05m.json",
        "dtm-sjo-25": f"{_GEONORGE_NKG_SJO_CELLER_BASE}/dtm_25m.json",
        "dtm-sjo-50": f"{_GEONORGE_NKG_SJO_CELLER_BASE}/dtm_50m.json",
        "dybdedata_50m": _kng_url("/json/norge/dybdedata_50m.geojson"),
        # Raster map sheets
        "raster-n50": f"{_GEONORGE_NKG_RASTER_GRID_BASE}/n50.geojson",
        "raster-n250": f"{_GEONORGE_NKG_RASTER_GRID_BASE}/n250_ny.geojson",
        "raster-n500": f"{_GEONORGE_NKG_RASTER_GRID_BASE}/n500_ny.geojson",
        "raster-n1000": f"{_GEONORGE_NKG_RASTER_GRID_BASE}/n1000_ny.geojson",
        "raster-32": f"{_GEONORGE_NKG_RASTER_GRID_BASE}/32.geojson",
        "raster-33": f"{_GEONORGE_NKG_RASTER_GRID_BASE}/33.geojson",
        "raster-35": f"{_GEONORGE_NKG_RASTER_GRID_BASE}/35.geojson",
        "rasterN50-2011": f"{_GEONORGE_NKG_RASTER_GRID_BASE}/rasterN50-2011.json",
        "rasterN50-2006": f"{_GEONORGE_NKG_RASTER_GRID_BASE}/rasterN50-2006.json",
        "n50_raster_regionsvis": f"{_GEONORGE_NKG_RASTER_GRID_BASE}/N50RasterRegionsvis_kartbladinndeling.json",
        "n50_raster_ruter": f"{_GEONORGE_NKG_RASTER_GRID_BASE}/n50.geojson",
        "n100_raster_ruter": f"{_GEONORGE_NKG_RASTER_GRID_BASE}/n100_raster_ruter.geojson",
        "n100_raster_regionsvis": f"{_GEONORGE_NKG_RASTER_GRID_BASE}/n100_raster_regionsvis.json",
        "n50_pod_inndeling2025": _kng_url("/json/dekning/land/n50/n50_pod_inndeling2025.json"),
        # Satellite / thematic grids
        "satellittbilder-100kmruter-utm33": (
            f"{_GEONORGE_NKG_DEKNING_BASE}/Satellittbilder_100kmruter_ETRS89utm33.json"
        ),
        # Download API typo layer id; same 100 km grid as other Sentinel skyfritt products.
        "ruter_entinelskyfritt2018uint16": (
            f"{_GEONORGE_NKG_DEKNING_BASE}/Satellittbilder_100kmruter_ETRS89utm33.json"
        ),
        # Sea chart map sheets
        "hovedserie_ny": f"{_GEONORGE_NKG_DEKNING_BASE}/sjo/hovedserie_ny.json",
        "havnekart_ny": f"{_GEONORGE_NKG_DEKNING_BASE}/sjo/havnekart_ny.json",
        "kystkart_ny": f"{_GEONORGE_NKG_DEKNING_BASE}/sjo/kystkart_ny.json",
        "overseilingskart_ny": f"{_GEONORGE_NKG_DEKNING_BASE}/sjo/overseilingskart_ny.json",
        "svalbardkart_ny": f"{_GEONORGE_NKG_DEKNING_BASE}/sjo/svalbardkart_ny.json",
    }
    return defaults.get(layer)
