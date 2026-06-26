from __future__ import annotations

from geonorge.compatibility import (
    area_disabled_reason,
    area_supports,
    enabled_area_codes,
    enabled_format_keys,
    enabled_projection_codes,
    format_disabled_reason,
    format_key,
    projection_disabled_reason,
)
from geonorge.models import AreaOption, FormatOption, ProjectionOption
from geonorge.nedlasting import _area_option_from_dict, _merge_formats_by_projection, _parse_areas_payload, _parse_formats_by_projection


def _area(
    *,
    code: str,
    projections: list[str] | None = None,
    formats: list[str] | None = None,
    formats_by_projection: dict[str, frozenset[str]] | None = None,
) -> AreaOption:
    return AreaOption(
        type="celle",
        code=code,
        name=code,
        formats=[FormatOption(name=n) for n in (formats or [])],
        projections=[ProjectionOption(code=c, name=c) for c in (projections or [])],
        formats_by_projection=formats_by_projection or {},
    )


def test_parse_nested_projection_formats() -> None:
    item = {
        "projections": [
            {
                "code": "25832",
                "formats": [{"name": "TIFF"}],
            },
            {
                "code": "25833",
                "formats": [{"name": "XYZ"}],
            },
        ]
    }
    formats = [FormatOption(name="TIFF"), FormatOption(name="XYZ")]
    projections = [ProjectionOption(code="25832"), ProjectionOption(code="25833")]
    parsed = _parse_formats_by_projection(item, formats=formats, projections=projections)
    assert parsed["25832"] == frozenset({format_key("TIFF")})
    assert parsed["25833"] == frozenset({format_key("XYZ")})


def test_area_option_from_dict_preserves_formats_by_projection() -> None:
    item = {
        "formats": [{"name": "TIFF"}],
        "projections": [
            {"code": "25832", "formats": [{"name": "TIFF"}]},
            {"code": "25833", "formats": [{"name": "TIFF"}]},
        ],
    }
    area = _area_option_from_dict("celle", item, "NHS-D0308", "NHS-D0308")
    assert "25832" in area.formats_by_projection
    assert format_key("TIFF") in area.formats_by_projection["25832"]


def test_strict_intersection_for_projections() -> None:
    areas = [
        _area(code="a", projections=["25832", "25833"]),
        _area(code="b", projections=["25833"]),
    ]
    all_projections = [
        ProjectionOption(code="25832"),
        ProjectionOption(code="25833"),
    ]
    enabled = enabled_projection_codes(areas, all_projections)
    assert enabled == {"25833"}


def test_format_gated_by_projection() -> None:
    area = _area(
        code="a",
        formats_by_projection={
            "25832": frozenset({format_key("TIFF")}),
            "25833": frozenset({format_key("XYZ")}),
        },
        projections=["25832", "25833"],
        formats=["TIFF", "XYZ"],
    )
    assert area_supports(area, projection_code="25832", format_name="TIFF")
    assert not area_supports(area, projection_code="25832", format_name="XYZ")
    assert area_supports(area, projection_code="25833", format_name="XYZ")


def test_enabled_areas_respect_projection_and_format() -> None:
    areas = [
        _area(
            code="a",
            formats_by_projection={"25832": frozenset({format_key("TIFF")})},
            projections=["25832"],
            formats=["TIFF"],
        ),
        _area(
            code="b",
            formats_by_projection={"25833": frozenset({format_key("TIFF")})},
            projections=["25833"],
            formats=["TIFF"],
        ),
    ]
    enabled = enabled_area_codes(areas, projection_code="25832", format_name="TIFF")
    assert enabled == {"a"}


def test_enabled_formats_strict_intersection() -> None:
    areas = [
        _area(
            code="a",
            formats_by_projection={"25832": frozenset({format_key("TIFF"), format_key("XYZ")})},
            projections=["25832"],
            formats=["TIFF", "XYZ"],
        ),
        _area(
            code="b",
            formats_by_projection={"25832": frozenset({format_key("TIFF")})},
            projections=["25832"],
            formats=["TIFF"],
        ),
    ]
    all_formats = [FormatOption(name="TIFF"), FormatOption(name="XYZ")]
    enabled = enabled_format_keys(areas, all_formats, projection_code="25832")
    assert enabled == {format_key("TIFF")}


def test_disabled_reason_messages() -> None:
    areas = [_area(code="a", projections=["25833"]), _area(code="b", projections=["25832"])]
    projection = ProjectionOption(code="25832", name="UTM 32")
    reason = projection_disabled_reason(projection, selected_areas=areas, total_selected=2)
    assert "1 of 2" in reason

    fmt = FormatOption(name="TIFF")
    fmt_reason = format_disabled_reason(
        fmt,
        selected_areas=areas,
        projection=projection,
        total_selected=2,
    )
    assert "UTM 32" in fmt_reason

    area = areas[0]
    area_reason = area_disabled_reason(area, projection=projection, fmt=fmt)
    assert "Not available" in area_reason


def test_browse_mode_projection_list_state_enables_all() -> None:
    from app.compatibility_ui import CompatibilityState, projection_list_state

    compat = CompatibilityState()
    candidates = [
        ProjectionOption(code="25832", name="UTM 32"),
        ProjectionOption(code="25833", name="UTM 33"),
    ]
    state = projection_list_state(compat, candidates, dataset_mode=False)
    assert state.disabled_payload_ids == set()
    assert len(state.tooltips_by_id) == 2
    assert state.content_signature == (("25832", "25833"),)


def test_dataset_mode_projection_list_state_disables_incompatible() -> None:
    from app.compatibility_ui import CompatibilityState, projection_list_state

    compat = CompatibilityState(enabled_projection_codes={"25833"})
    candidates = [
        ProjectionOption(code="25832", name="UTM 32"),
        ProjectionOption(code="25833", name="UTM 33"),
    ]
    state = projection_list_state(compat, candidates, dataset_mode=True)
    assert len(state.disabled_payload_ids) == 1
    assert state.auto_select is not None
    assert state.auto_select.code == "25833"


def test_browse_mode_format_list_state_enables_all() -> None:
    from app.compatibility_ui import CompatibilityState, format_list_state

    compat = CompatibilityState()
    candidates = [FormatOption(name="TIFF"), FormatOption(name="XYZ")]
    state = format_list_state(
        compat,
        candidates,
        dataset_mode=False,
        format_key_fn=format_key,
    )
    assert state.disabled_payload_ids == set()


def test_merge_formats_by_projection_intersects_duplicate_rows() -> None:
    left = {"25833": frozenset({format_key("TIFF")})}
    right = {"25833": frozenset({format_key("XYZ")})}
    merged = _merge_formats_by_projection(left, right)
    assert merged == {"25833": frozenset()}


def test_duplicate_area_rows_intersect_projection_formats() -> None:
    payload = [
        {
            "type": "celle",
            "code": "NHS-D0308",
            "name": "NHS-D0308",
            "projections": [{"code": "25833", "formats": [{"name": "TIFF"}]}],
        },
        {
            "type": "celle",
            "code": "NHS-D0308",
            "name": "NHS-D0308",
            "projections": [{"code": "25833", "formats": [{"name": "XYZ"}]}],
        },
    ]
    parsed = _parse_areas_payload(payload)
    area = parsed["celle"][0]
    assert not area_supports(area, projection_code="25833", format_name="TIFF")
    assert not area_supports(area, projection_code="25833", format_name="XYZ")


def test_browse_mode_area_list_state_enables_all() -> None:
    from app.compatibility_ui import CompatibilityState, area_list_state

    compat = CompatibilityState()
    areas = [_area(code="a"), _area(code="b")]
    state = area_list_state(compat, areas, dataset_mode=False)
    assert state.disabled_keys == set()
    assert state.disabled_signature_part == ()


def test_no_selected_areas_cross_filters_projection_and_format() -> None:
    from app.compatibility_ui import compute_compatibility
    from geonorge.models import DatasetAvailability

    all_areas = [
        _area(
            code="a",
            formats_by_projection={"25833": frozenset({format_key("TIFF")})},
            projections=["25833"],
            formats=["TIFF"],
        ),
        _area(
            code="b",
            formats_by_projection={"4326": frozenset({format_key("NED")})},
            projections=["4326"],
            formats=["NED"],
        ),
    ]
    dataset = DatasetAvailability(metadata_uuid="uuid", title="Test")
    dataset.areas_by_type = {"celle": all_areas}
    dataset.projections = [
        ProjectionOption(code="25833", name="UTM 33"),
        ProjectionOption(code="4326", name="WGS84"),
    ]
    dataset.formats = [FormatOption(name="TIFF"), FormatOption(name="NED")]

    compat = compute_compatibility(
        dataset,
        area_type="celle",
        selected_areas=[],
        projection=ProjectionOption(code="4326", name="WGS84"),
        fmt=FormatOption(name="TIFF"),
    )
    assert compat.enabled_area_codes == set()
    assert "4326" not in compat.enabled_projection_codes
    assert format_key("TIFF") not in compat.enabled_format_keys

    with_utm = compute_compatibility(
        dataset,
        area_type="celle",
        selected_areas=[],
        projection=ProjectionOption(code="25833", name="UTM 33"),
        fmt=FormatOption(name="TIFF"),
    )
    assert with_utm.enabled_area_codes == {"a"}
    assert "25833" in with_utm.enabled_projection_codes
    assert format_key("TIFF") in with_utm.enabled_format_keys


def test_union_projection_enablement_without_selected_areas() -> None:
    areas = [
        _area(code="a", projections=["25832"]),
        _area(code="b", projections=["25833"]),
    ]
    all_projections = [
        ProjectionOption(code="25832"),
        ProjectionOption(code="25833"),
    ]
    enabled = enabled_projection_codes(areas, all_projections, union=True)
    assert enabled == {"25832", "25833"}


def test_union_projection_respects_selected_format() -> None:
    areas = [
        _area(
            code="a",
            formats_by_projection={"4326": frozenset({format_key("NED")})},
            projections=["4326"],
            formats=["NED"],
        ),
        _area(
            code="b",
            formats_by_projection={"25833": frozenset({format_key("TIFF")})},
            projections=["25833"],
            formats=["TIFF"],
        ),
    ]
    all_projections = [
        ProjectionOption(code="4326"),
        ProjectionOption(code="25833"),
    ]
    enabled = enabled_projection_codes(
        areas,
        all_projections,
        format_name="TIFF",
        union=True,
    )
    assert enabled == {"25833"}


def test_area_gating_only_when_projection_and_format_explicit() -> None:
    from app.compatibility_ui import compute_compatibility
    from geonorge.models import DatasetAvailability, FormatOption, ProjectionOption

    all_areas = [
        _area(
            code="a",
            formats_by_projection={"25833": frozenset({format_key("TIFF")})},
            projections=["25833"],
            formats=["TIFF"],
        ),
        _area(
            code="b",
            formats_by_projection={"25832": frozenset({format_key("TIFF")})},
            projections=["25832"],
            formats=["TIFF"],
        ),
    ]
    dataset = DatasetAvailability(metadata_uuid="uuid", title="Test")
    dataset.areas_by_type = {"celle": all_areas}
    dataset.projections = [
        ProjectionOption(code="25833", name="UTM 33"),
        ProjectionOption(code="25832", name="UTM 32"),
    ]
    dataset.formats = [FormatOption(name="TIFF")]
    projection = ProjectionOption(code="25833", name="UTM 33")
    fmt = FormatOption(name="TIFF")

    without_explicit = compute_compatibility(
        dataset,
        area_type="celle",
        selected_areas=[all_areas[0]],
        projection=None,
        fmt=None,
    )
    with_explicit = compute_compatibility(
        dataset,
        area_type="celle",
        selected_areas=[all_areas[0]],
        projection=projection,
        fmt=fmt,
    )
    assert without_explicit.enabled_area_codes == {"a", "b"}
    assert with_explicit.enabled_area_codes == {"a"}
