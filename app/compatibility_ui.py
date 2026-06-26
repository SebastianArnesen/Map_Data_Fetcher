from __future__ import annotations

from dataclasses import dataclass, field

from geonorge.compatibility import (
    area_disabled_reason,
    enabled_area_codes,
    enabled_format_keys,
    enabled_projection_codes,
    format_disabled_reason,
    format_key,
    projection_disabled_reason,
)
from geonorge.models import AreaOption, AreaType, DatasetAvailability, FormatOption, ProjectionOption


@dataclass
class CompatibilityState:
    all_areas: list[AreaOption] = field(default_factory=list)
    all_projections: list[ProjectionOption] = field(default_factory=list)
    all_formats: list[FormatOption] = field(default_factory=list)
    enabled_projection_codes: set[str] = field(default_factory=set)
    enabled_format_keys: set[str] = field(default_factory=set)
    enabled_area_codes: set[str] = field(default_factory=set)
    projection_tooltips: dict[str, str] = field(default_factory=dict)
    format_tooltips: dict[str, str] = field(default_factory=dict)
    area_tooltips: dict[str, str] = field(default_factory=dict)

    def projection_enabled(self, projection: ProjectionOption) -> bool:
        return projection.code in self.enabled_projection_codes

    def format_enabled(self, fmt: FormatOption) -> bool:
        return format_key(fmt) in self.enabled_format_keys

    def area_enabled(self, area: AreaOption) -> bool:
        return area.code in self.enabled_area_codes


@dataclass(frozen=True)
class ProjectionPopulateState:
    disabled_payload_ids: set[int]
    tooltips_by_id: dict[int, str]
    content_signature: tuple
    auto_select: ProjectionOption | None


@dataclass(frozen=True)
class FormatPopulateState:
    disabled_payload_ids: set[int]
    tooltips_by_id: dict[int, str]
    content_signature: tuple
    auto_select: FormatOption | None


@dataclass(frozen=True)
class AreaPopulateState:
    disabled_keys: set[str]
    tooltips: dict[str, str]
    disabled_signature_part: tuple[str, ...]


def projection_list_state(
    compat: CompatibilityState,
    candidates: list[ProjectionOption],
    *,
    dataset_mode: bool,
) -> ProjectionPopulateState:
    if not dataset_mode:
        return ProjectionPopulateState(
            disabled_payload_ids=set(),
            tooltips_by_id={id(p): p.label for p in candidates},
            content_signature=(tuple(p.code for p in candidates),),
            auto_select=candidates[0] if len(candidates) == 1 else None,
        )
    enabled = [p for p in candidates if compat.projection_enabled(p)]
    return ProjectionPopulateState(
        disabled_payload_ids={id(p) for p in candidates if not compat.projection_enabled(p)},
        tooltips_by_id={id(p): compat.projection_tooltips.get(p.code, p.label) for p in candidates},
        content_signature=(
            tuple(p.code for p in candidates),
            tuple(sorted(compat.enabled_projection_codes)),
        ),
        auto_select=enabled[0] if len(enabled) == 1 else None,
    )


def format_list_state(
    compat: CompatibilityState,
    candidates: list[FormatOption],
    *,
    dataset_mode: bool,
    format_key_fn,
) -> FormatPopulateState:
    if not dataset_mode:
        return FormatPopulateState(
            disabled_payload_ids=set(),
            tooltips_by_id={id(f): f.label for f in candidates},
            content_signature=(tuple(format_key_fn(f) for f in candidates),),
            auto_select=candidates[0] if len(candidates) == 1 else None,
        )
    enabled = [f for f in candidates if compat.format_enabled(f)]
    return FormatPopulateState(
        disabled_payload_ids={id(f) for f in candidates if not compat.format_enabled(f)},
        tooltips_by_id={id(f): compat.format_tooltips.get(format_key_fn(f), f.label) for f in candidates},
        content_signature=(
            tuple(format_key_fn(f) for f in candidates),
            tuple(sorted(compat.enabled_format_keys)),
        ),
        auto_select=enabled[0] if len(enabled) == 1 else None,
    )


def area_list_state(
    compat: CompatibilityState,
    display_areas: list[AreaOption],
    *,
    dataset_mode: bool,
) -> AreaPopulateState:
    if not dataset_mode:
        return AreaPopulateState(
            disabled_keys=set(),
            tooltips={a.code: a.label for a in display_areas},
            disabled_signature_part=(),
        )
    disabled_keys = {a.code for a in display_areas if not compat.area_enabled(a)}
    return AreaPopulateState(
        disabled_keys=disabled_keys,
        tooltips={a.code: compat.area_tooltips.get(a.code, a.label) for a in display_areas},
        disabled_signature_part=tuple(sorted(disabled_keys)),
    )


def incompatible_selection_reasons(
    compat: CompatibilityState,
    *,
    areas: list[AreaOption],
    projection: ProjectionOption | None,
    fmt: FormatOption | None,
) -> list[str]:
    reasons: list[str] = []
    if projection and not compat.projection_enabled(projection):
        reasons.append("Selected projection is not compatible with the current areas.")
    if fmt and not compat.format_enabled(fmt):
        reasons.append("Selected format is not compatible with the current areas and projection.")
    elif areas:
        for area in areas:
            if not compat.area_enabled(area):
                reasons.append(
                    "One or more selected areas are not compatible with the current projection and format."
                )
                break
    return reasons

def compute_compatibility(
    dataset: DatasetAvailability | None,
    *,
    area_type: AreaType | None,
    selected_areas: list[AreaOption],
    projection: ProjectionOption | None,
    fmt: FormatOption | None,
) -> CompatibilityState:
    state = CompatibilityState()
    if not dataset or not area_type:
        return state

    state.all_areas = list(dataset.areas_by_type.get(area_type, []))
    state.all_projections = list(dataset.projections)
    state.all_formats = list(dataset.formats)

    # With no explicit area picks, cross-filter projections/formats against every
    # area in the dataset (union). With picks, require compatibility with all of them.
    reference_areas = selected_areas if selected_areas else state.all_areas
    use_union = not selected_areas
    total_selected = len(selected_areas)

    state.enabled_projection_codes = enabled_projection_codes(
        reference_areas,
        state.all_projections,
        format_name=fmt.name if fmt else None,
        union=use_union,
    )
    state.enabled_format_keys = enabled_format_keys(
        reference_areas,
        state.all_formats,
        projection_code=projection.code if projection else None,
        union=use_union,
    )
    state.enabled_area_codes = enabled_area_codes(
        state.all_areas,
        projection_code=projection.code if projection else None,
        format_name=fmt.name if fmt else None,
    )

    for p in state.all_projections:
        state.projection_tooltips[p.code] = projection_disabled_reason(
            p,
            selected_areas=reference_areas,
            total_selected=len(reference_areas),
            format_name=fmt.name if fmt else None,
            union=use_union,
        )

    for f in state.all_formats:
        state.format_tooltips[format_key(f)] = format_disabled_reason(
            f,
            selected_areas=reference_areas,
            projection=projection,
            total_selected=len(reference_areas),
            union=use_union,
        )

    for area in state.all_areas:
        state.area_tooltips[area.code] = area_disabled_reason(
            area, projection=projection, fmt=fmt
        )

    return state
