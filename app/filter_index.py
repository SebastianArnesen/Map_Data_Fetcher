from __future__ import annotations

import re
from dataclasses import dataclass
from dataclasses import field
from typing import Iterable

from geonorge.catalog import normalize_categories
from geonorge.models import AreaOption, AreaType, DatasetAvailability, FormatOption, ProjectionOption

AREA_TYPE_ORDER: tuple[AreaType, ...] = ("landsdekkende", "fylke", "kommune", "celle")


def format_filter_key(fmt: FormatOption) -> str:
    cleaned = fmt.label.replace("\u200b", "").replace("\ufeff", "")
    return " ".join(cleaned.split()).casefold()


def dataset_matches_search(ds: DatasetAvailability, query: str) -> bool:
    text = query.strip().casefold()
    if not text:
        return True
    title = ds.title.casefold()
    uuid = ds.metadata_uuid.casefold()
    words = re.findall(r"[\wæøåÆØÅ]+", ds.title.casefold())

    def _uuid_prefix_matches(token: str) -> bool:
        compact_uuid = uuid.replace("-", "")
        compact_token = token.casefold().replace("-", "")
        return bool(compact_token) and compact_uuid.startswith(compact_token)

    for token in text.split():
        if _uuid_prefix_matches(token):
            continue
        if token in title:
            continue
        if any(word.startswith(token) for word in words):
            continue
        return False
    return True


def _mask_from_indices(indices: Iterable[int]) -> int:
    mask = 0
    for index in indices:
        mask |= 1 << index
    return mask


def iter_mask_indices(mask: int) -> Iterable[int]:
    while mask:
        lsb = mask & -mask
        yield lsb.bit_length() - 1
        mask ^= lsb


def original_tags_for_category(ds: DatasetAvailability, category: str) -> list[str]:
    originals = ds.original_categories or []
    if not originals:
        return [category] if category in ds.categories else []
    return [tag for tag in originals if category in normalize_categories([tag])]


@dataclass(frozen=True)
class DatasetFilterIndex:
    """
    Bitmask index over eligible (non-login) datasets.

    Each filter dimension is a map from key -> int bitmask where bit i means datasets[i] matches.
    Active filters combine with bitwise AND for fast intersection.
    """

    datasets: tuple[DatasetAvailability, ...]
    all_mask: int
    downloadable_mask: int
    category_masks: dict[str, int]
    projection_masks: dict[str, int]
    format_masks: dict[str, int]
    area_masks: dict[AreaType, dict[str, int]]
    uuid_masks: dict[str, int]
    area_catalog: dict[AreaType, dict[str, AreaOption]]
    format_catalog: dict[str, FormatOption]
    projection_catalog: dict[str, ProjectionOption]
    area_type_masks: dict[AreaType, int]
    category_tag_masks: dict[str, dict[str, tuple[str, int]]]
    search_cache: dict[str, int] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def build(cls, datasets: list[DatasetAvailability]) -> DatasetFilterIndex:
        eligible = tuple(d for d in datasets if not d.login_required)
        count = len(eligible)
        all_mask = (1 << count) - 1 if count else 0

        downloadable_mask = _mask_from_indices(i for i, d in enumerate(eligible) if d.formats)

        category_masks: dict[str, int] = {}
        projection_masks: dict[str, int] = {}
        format_masks: dict[str, int] = {}
        area_masks: dict[AreaType, dict[str, int]] = {}
        uuid_masks: dict[str, int] = {}
        area_catalog: dict[AreaType, dict[str, AreaOption]] = {}
        format_catalog: dict[str, FormatOption] = {}
        projection_catalog: dict[str, ProjectionOption] = {}
        area_type_masks: dict[AreaType, int] = {}
        category_tag_masks: dict[str, dict[str, tuple[str, int]]] = {}

        for i, ds in enumerate(eligible):
            bit = 1 << i
            uuid_masks[ds.metadata_uuid] = bit
            for category in ds.categories:
                if not category.strip():
                    continue
                category_masks[category] = category_masks.get(category, 0) | bit
                tag_bits = category_tag_masks.setdefault(category, {})
                for original in original_tags_for_category(ds, category):
                    norm = original.casefold()
                    display, prev = tag_bits.get(norm, (original, 0))
                    tag_bits[norm] = (display, prev | bit)
            for projection in ds.projections:
                projection_masks[projection.code] = projection_masks.get(projection.code, 0) | bit
                projection_catalog.setdefault(projection.code, projection)
            for fmt in ds.formats:
                key = format_filter_key(fmt)
                format_masks[key] = format_masks.get(key, 0) | bit
                format_catalog.setdefault(key, fmt)
            for area_type, areas in ds.areas_by_type.items():
                by_code = area_masks.setdefault(area_type, {})
                catalog = area_catalog.setdefault(area_type, {})
                type_mask = area_type_masks.setdefault(area_type, 0)
                for area in areas:
                    by_code[area.code] = by_code.get(area.code, 0) | bit
                    type_mask |= bit
                    catalog.setdefault(area.code, area)

        return cls(
            datasets=eligible,
            all_mask=all_mask,
            downloadable_mask=downloadable_mask,
            category_masks=category_masks,
            projection_masks=projection_masks,
            format_masks=format_masks,
            area_masks=area_masks,
            uuid_masks=uuid_masks,
            area_catalog=area_catalog,
            format_catalog=format_catalog,
            projection_catalog=projection_catalog,
            area_type_masks=area_type_masks,
            category_tag_masks=category_tag_masks,
        )

    def search_mask(self, query: str) -> int:
        text = query.strip()
        if not text:
            return self.all_mask
        key = " ".join(text.split()).casefold()
        cached = self.search_cache.get(key)
        if cached is not None:
            return cached
        mask = _mask_from_indices(
            i for i, ds in enumerate(self.datasets) if dataset_matches_search(ds, key)
        )
        self.search_cache[key] = mask
        return mask

    def compose_mask(
        self,
        *,
        search_text: str = "",
        downloadable_only: bool = False,
        selected_uuid: str | None = None,
        categories: set[str] | None = None,
        area_type: AreaType | None = None,
        area_codes: set[str] | None = None,
        projection_code: str | None = None,
        format_key: str | None = None,
        ignore: set[str] | None = None,
    ) -> int:
        ignore = ignore or set()
        mask = self.all_mask

        if "downloadable" not in ignore and downloadable_only:
            mask &= self.downloadable_mask
        if "dataset" not in ignore and selected_uuid:
            mask &= self.uuid_masks.get(selected_uuid, 0)
        if "category" not in ignore and categories:
            category_mask = 0
            for category in categories:
                category_mask |= self.category_masks.get(category, 0)
            mask &= category_mask
        if "areas" not in ignore and area_type and area_codes:
            by_code = self.area_masks.get(area_type, {})
            area_mask = self.all_mask
            for code in area_codes:
                area_mask &= by_code.get(code, 0)
            mask &= area_mask
        if "projection" not in ignore and projection_code:
            mask &= self.projection_masks.get(projection_code, 0)
        if "format" not in ignore and format_key:
            mask &= self.format_masks.get(format_key, 0)
        if "search" not in ignore and search_text.strip():
            mask &= self.search_mask(search_text)
        return mask

    def datasets_for_mask(self, mask: int) -> list[DatasetAvailability]:
        return [self.datasets[i] for i in iter_mask_indices(mask)]

    def mask_count(self, mask: int) -> int:
        return mask.bit_count()

    def categories_for_mask(self, mask: int) -> list[str]:
        if not mask:
            return []
        return [category for category, bits in self.category_masks.items() if bits & mask]

    def formats_for_mask(self, mask: int) -> list[FormatOption]:
        if not mask:
            return []
        return [
            self.format_catalog[key]
            for key, bits in self.format_masks.items()
            if bits & mask and key in self.format_catalog
        ]

    def projections_for_mask(self, mask: int) -> list[ProjectionOption]:
        if not mask:
            return []
        return [
            self.projection_catalog[code]
            for code, bits in self.projection_masks.items()
            if bits & mask and code in self.projection_catalog
        ]

    def area_codes_for_mask(self, area_type: AreaType, mask: int) -> set[str]:
        if not mask:
            return set()
        bits_by_code = self.area_masks.get(area_type, {})
        return {code for code, bits in bits_by_code.items() if bits & mask}

    def areas_for_mask(self, area_type: AreaType, mask: int) -> list[AreaOption]:
        if not mask:
            return []
        catalog = self.area_catalog.get(area_type, {})
        bits_by_code = self.area_masks.get(area_type, {})
        return [catalog[code] for code in catalog if bits_by_code.get(code, 0) & mask]

    def area_types_for_mask(self, mask: int) -> list[AreaType]:
        if not mask:
            return []
        return [
            area_type
            for area_type in AREA_TYPE_ORDER
            if self.area_type_masks.get(area_type, 0) & mask
        ]

    def category_tags_for_mask(self, category: str, mask: int) -> list[str]:
        if not mask:
            return []
        tag_bits = self.category_tag_masks.get(category, {})
        seen: set[str] = set()
        out: list[str] = []
        for norm, (display, bits) in tag_bits.items():
            if not (bits & mask) or norm in seen:
                continue
            seen.add(norm)
            out.append(display)
        return out
