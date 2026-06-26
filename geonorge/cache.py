from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .catalog import normalize_categories
from .models import (
    AreaOption,
    DatasetAvailability,
    DatasetCapabilities,
    FormatOption,
    ProjectionOption,
)


def default_cache_dir() -> Path:
    from app.paths import app_data_dir

    return app_data_dir()


def _caps_to_dict(caps: DatasetCapabilities | None) -> dict[str, Any] | None:
    return None if caps is None else asdict(caps)


def _caps_from_dict(d: dict[str, Any] | None) -> DatasetCapabilities | None:
    if not d:
        return None
    return DatasetCapabilities(
        supports_area_selection=bool(d.get("supports_area_selection")),
        supports_format_selection=bool(d.get("supports_format_selection")),
        supports_projection_selection=bool(d.get("supports_projection_selection")),
        supports_polygon_selection=bool(d.get("supports_polygon_selection")),
        map_selection_layer=(
            str(d.get("map_selection_layer")).strip()
            if isinstance(d.get("map_selection_layer"), str) and str(d.get("map_selection_layer")).strip()
            else None
        ),
    )


def _clean_cached_categories(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if not isinstance(value, str):
            continue
        cleaned = value.strip()
        if cleaned.startswith("{") and "EnglishKeyword" in cleaned and "KeywordValue" in cleaned:
            match = re.search(r"['\"]KeywordValue['\"]\s*:\s*['\"]([^'\"]+)['\"]", cleaned)
            cleaned = match.group(1).strip() if match else ""
        normalized = cleaned.casefold()
        if not cleaned or cleaned.startswith(("{", "[")) or normalized in seen:
            continue
        seen.add(normalized)
        out.append(cleaned)
    return out


def dataset_to_dict(it: DatasetAvailability) -> dict[str, Any]:
    return {
        "metadata_uuid": it.metadata_uuid,
        "title": it.title,
        "categories": it.categories,
        "original_categories": it.original_categories,
        "login_required": it.login_required,
        "enriched": it.enriched,
        "catalog_metadata_updated": it.catalog_metadata_updated,
        "enrichment_version": it.enrichment_version,
        "download_api_base": it.download_api_base,
        "capabilities": _caps_to_dict(it.capabilities),
        "area_types": sorted(list(it.area_types)),
        "areas_by_type": {
            k: [
                {
                    "type": a.type,
                    "code": a.code,
                    "name": a.name,
                    "formats": [{"name": f.name, "version": f.version} for f in a.formats],
                    "projections": [
                        {"code": p.code, "name": p.name, "codespace": p.codespace} for p in a.projections
                    ],
                    "formats_by_projection": {
                        code: sorted(list(fmts)) for code, fmts in a.formats_by_projection.items()
                    },
                }
                for a in v
            ]
            for k, v in it.areas_by_type.items()
        },
        "formats": [{"name": f.name, "version": f.version} for f in it.formats],
        "projections": [
            {"code": p.code, "name": p.name, "codespace": p.codespace} for p in it.projections
        ],
    }


def dataset_from_dict(d: dict[str, Any]) -> DatasetAvailability:
    original_categories = _clean_cached_categories(d.get("original_categories"))
    if not original_categories:
        original_categories = _clean_cached_categories(d.get("categories"))
    it = DatasetAvailability(
        metadata_uuid=str(d["metadata_uuid"]),
        title=str(d.get("title", "")),
        categories=normalize_categories(original_categories),
        original_categories=original_categories,
        login_required=bool(d.get("login_required", False)),
        enriched=bool(d.get("enriched", False)),
        catalog_metadata_updated=(
            d.get("catalog_metadata_updated") if isinstance(d.get("catalog_metadata_updated"), str) else None
        ),
        enrichment_version=int(d.get("enrichment_version") or 0),
        download_api_base=d.get("download_api_base") if isinstance(d.get("download_api_base"), str) else None,
        capabilities=_caps_from_dict(d.get("capabilities")),
    )
    it.area_types = set(d.get("area_types") or [])
    areas_by_type: dict[str, list[AreaOption]] = {}
    for k, v in (d.get("areas_by_type") or {}).items():
        areas_by_type[k] = [
            AreaOption(
                type=a["type"],
                code=a["code"],
                name=a["name"],
                formats=[FormatOption(name=f["name"], version=f.get("version")) for f in (a.get("formats") or [])],
                projections=[
                    ProjectionOption(code=p["code"], name=p.get("name"), codespace=p.get("codespace"))
                    for p in (a.get("projections") or [])
                ],
                formats_by_projection={
                    str(code): frozenset(str(f) for f in fmts)
                    for code, fmts in (a.get("formats_by_projection") or {}).items()
                },
            )
            for a in v
        ]
    it.areas_by_type = areas_by_type  # type: ignore[assignment]
    it.formats = [FormatOption(name=f["name"], version=f.get("version")) for f in (d.get("formats") or [])]
    it.projections = [
        ProjectionOption(code=p["code"], name=p.get("name"), codespace=p.get("codespace"))
        for p in (d.get("projections") or [])
    ]
    return it


def load_legacy_json_cache() -> list[DatasetAvailability] | None:
    """One-time migration source for empty SQLite indexes (legacy cache.json)."""
    path = default_cache_dir() / "cache.json"
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    datasets = raw.get("datasets")
    if not isinstance(datasets, list):
        return None
    out: list[DatasetAvailability] = []
    for d in datasets:
        try:
            out.append(dataset_from_dict(d))
        except Exception:
            continue
    return out or None

