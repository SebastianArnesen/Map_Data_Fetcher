from __future__ import annotations

from geonorge.models import AreaOption, FormatOption, ProjectionOption


def format_key(fmt: FormatOption | str) -> str:
    if isinstance(fmt, FormatOption):
        cleaned = fmt.label.replace("\u200b", "").replace("\ufeff", "")
        return " ".join(cleaned.split()).casefold()
    return " ".join(str(fmt).split()).casefold()


def area_supports(
    area: AreaOption,
    *,
    projection_code: str | None = None,
    format_name: str | None = None,
) -> bool:
    """Return True when area supports the given projection/format combination."""
    target_format = format_key(format_name) if format_name else None

    if area.formats_by_projection:
        if projection_code is None:
            if target_format is None:
                return True
            if any(target_format in fmts for fmts in area.formats_by_projection.values()):
                return True
            return not area.formats and not any(area.formats_by_projection.values())

        if projection_code not in area.formats_by_projection:
            if area.projections:
                if not any(p.code == projection_code for p in area.projections):
                    return False
                if target_format is None:
                    return True
                if area.formats:
                    return any(format_key(f) == target_format for f in area.formats)
                return True
            return False

        allowed = area.formats_by_projection[projection_code]
        if target_format is None:
            return bool(allowed)
        return target_format in allowed

    if projection_code and area.projections:
        if not any(p.code == projection_code for p in area.projections):
            return False

    if target_format and area.formats:
        return any(format_key(f) == target_format for f in area.formats)

    return True


def enabled_projection_codes(
    areas: list[AreaOption],
    all_projections: list[ProjectionOption],
) -> set[str]:
    if not areas:
        return {p.code for p in all_projections}
    enabled: set[str] | None = None
    for area in areas:
        supported = {p.code for p in all_projections if area_supports(area, projection_code=p.code)}
        enabled = supported if enabled is None else enabled & supported
    return enabled or set()


def enabled_format_keys(
    areas: list[AreaOption],
    all_formats: list[FormatOption],
    *,
    projection_code: str | None,
) -> set[str]:
    if not areas:
        return {format_key(f) for f in all_formats}
    enabled: set[str] | None = None
    for area in areas:
        supported = {
            format_key(f)
            for f in all_formats
            if area_supports(area, projection_code=projection_code, format_name=f.name)
        }
        enabled = supported if enabled is None else enabled & supported
    return enabled or set()


def enabled_area_codes(
    areas: list[AreaOption],
    *,
    projection_code: str | None,
    format_name: str | None,
) -> set[str]:
    return {
        area.code
        for area in areas
        if area_supports(area, projection_code=projection_code, format_name=format_name)
    }


def projection_disabled_reason(
    projection: ProjectionOption,
    *,
    selected_areas: list[AreaOption],
    total_selected: int,
) -> str:
    if not selected_areas:
        return projection.label
    missing = sum(
        1 for area in selected_areas if not area_supports(area, projection_code=projection.code)
    )
    if missing == 0:
        return projection.label
    if missing == 1:
        return f"Not available for 1 of {total_selected} selected areas"
    return f"Not available for {missing} of {total_selected} selected areas"


def format_disabled_reason(
    fmt: FormatOption,
    *,
    selected_areas: list[AreaOption],
    projection: ProjectionOption | None,
    total_selected: int,
) -> str:
    projection_code = projection.code if projection else None
    if not selected_areas:
        return fmt.label
    missing = sum(
        1
        for area in selected_areas
        if not area_supports(area, projection_code=projection_code, format_name=fmt.name)
    )
    if missing == 0:
        return fmt.label
    if projection:
        prefix = f"Not available with {projection.label}"
    else:
        prefix = "Not available"
    if missing == 1:
        return f"{prefix} for 1 of {total_selected} selected areas"
    return f"{prefix} for {missing} of {total_selected} selected areas"


def area_disabled_reason(
    area: AreaOption,
    *,
    projection: ProjectionOption | None,
    fmt: FormatOption | None,
) -> str:
    projection_code = projection.code if projection else None
    format_name = fmt.name if fmt else None
    if area_supports(area, projection_code=projection_code, format_name=format_name):
        return area.label
    parts: list[str] = []
    if projection and not area_supports(area, projection_code=projection.code):
        parts.append(f"projection {projection.label}")
    if fmt and not area_supports(
        area, projection_code=projection_code, format_name=format_name
    ):
        parts.append(f"format {fmt.label}")
    if parts:
        return f"Not available with {' and '.join(parts)}"
    return area.label
