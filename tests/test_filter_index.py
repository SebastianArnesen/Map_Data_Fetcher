from __future__ import annotations

from app.filter_index import DatasetFilterIndex
from geonorge.models import AreaOption, DatasetAvailability, FormatOption, ProjectionOption


def _ds(
    uuid: str,
    title: str,
    *,
    categories: list[str] | None = None,
    formats: list[FormatOption] | None = None,
    projections: list[ProjectionOption] | None = None,
    areas: dict[str, list[AreaOption]] | None = None,
) -> DatasetAvailability:
    return DatasetAvailability(
        metadata_uuid=uuid,
        title=title,
        categories=categories or [],
        original_categories=[],
        login_required=False,
        enriched=True,
        capabilities=None,
        area_types=set(areas.keys()) if areas else set(),
        areas_by_type=areas or {},
        formats=formats or [],
        projections=projections or [],
    )


def test_compose_mask_and_cache_search() -> None:
    tiff = FormatOption("TIFF")
    gdb = FormatOption("GDB")
    epsg = ProjectionOption(code="25833", name="ETRS89 / UTM 33N")
    a0 = AreaOption(type="celle", code="10", name="Cell 10")
    a1 = AreaOption(type="celle", code="20", name="Cell 20")

    datasets = [
        _ds(
            "a" * 8 + "-0000-0000-0000-" + "0" * 12,
            "Alpha dataset",
            categories=["Geologi"],
            formats=[tiff],
            projections=[epsg],
            areas={"celle": [a0]},
        ),
        _ds(
            "b" * 8 + "-0000-0000-0000-" + "0" * 12,
            "Bravo dataset",
            categories=["Transport"],
            formats=[gdb],
            projections=[],
            areas={"celle": [a1]},
        ),
    ]
    index = DatasetFilterIndex.build(datasets)

    # Search mask is cached by normalized query.
    m1 = index.search_mask("alpha")
    m2 = index.search_mask("  ALPHA  ")
    assert m1 == m2
    assert "alpha" in index.search_cache

    # Compose by category + format.
    mask = index.compose_mask(categories={"Geologi"}, format_key="tiff")
    assert index.mask_count(mask) == 1
    assert index.datasets_for_mask(mask)[0].title == "Alpha dataset"


def test_area_codes_for_mask() -> None:
    a0 = AreaOption(type="kommune", code="0301", name="Oslo")
    a1 = AreaOption(type="kommune", code="4601", name="Bergen")
    datasets = [
        _ds(
            "c" * 8 + "-0000-0000-0000-" + "0" * 12,
            "Cities",
            areas={"kommune": [a0, a1]},
        )
    ]
    index = DatasetFilterIndex.build(datasets)
    mask = index.compose_mask()
    assert index.area_codes_for_mask("kommune", mask) == {"0301", "4601"}

