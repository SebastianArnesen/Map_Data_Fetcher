"""Map reload lifecycle (dataset switch while map was open)."""

from __future__ import annotations

import pytest

from app.map_picker import fetch_text, parse_geojson_grid_cells
from geonorge.map_selection import geojson_url_for_map_selection_layer, infer_source_epsg


@pytest.mark.network
def test_utm33_geojson_parses_with_dataset_style_filter() -> None:
    """UTM33 grid should yield cells when allowed_codes is empty (no filter)."""
    layer = "dtm-dekning-utm33"
    url = geojson_url_for_map_selection_layer(layer)
    assert url is not None
    text = fetch_text(url)
    parsed = parse_geojson_grid_cells(
        text,
        allowed_codes=set(),
        source_epsg=infer_source_epsg(layer_id=layer),
    )
    assert len(parsed) > 100


def test_utm35_and_utm33_layers_use_distinct_urls() -> None:
    u35 = geojson_url_for_map_selection_layer("dtm-dekning-utm35")
    u33 = geojson_url_for_map_selection_layer("dtm-dekning-utm33")
    assert u35 is not None and u33 is not None
    assert u35 != u33
