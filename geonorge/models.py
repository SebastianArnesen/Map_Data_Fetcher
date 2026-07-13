from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

AreaType = Literal["landsdekkende", "fylke", "kommune", "celle"]


@dataclass(frozen=True)
class DatasetRef:
    metadata_uuid: str
    title: str


@dataclass(frozen=True)
class FormatOption:
    name: str
    version: str | None = None

    @property
    def label(self) -> str:
        name = " ".join(self.name.split())
        version = " ".join(self.version.split()) if self.version else None
        if version:
            return f"{name} ({version})"
        return name


@dataclass(frozen=True)
class ProjectionOption:
    code: str
    name: str | None = None
    codespace: str | None = None

    @property
    def label(self) -> str:
        if self.name:
            return f"{self.code} — {self.name}"
        return self.code


@dataclass(frozen=True)
class AreaOption:
    type: AreaType
    code: str
    name: str
    formats: list[FormatOption] = field(default_factory=list)
    projections: list[ProjectionOption] = field(default_factory=list)
    # projection code -> normalized format keys valid under that projection
    formats_by_projection: dict[str, frozenset[str]] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return f"{self.code} — {self.name}"


@dataclass(frozen=True)
class OrderFile:
    """One file entry from a Geonorge order status response."""

    file_id: str | None
    area_code: str | None
    download_url: str | None
    status: str | None
    name: str | None
    format_name: str | None = None
    projection_code: str | None = None

    @property
    def is_downloadable(self) -> bool:
        return bool(self.download_url)


@dataclass(frozen=True)
class DatasetCapabilities:
    supports_area_selection: bool
    supports_format_selection: bool
    supports_projection_selection: bool
    supports_polygon_selection: bool
    # Optional: enables "Velg fra kartblad" (cell selection via a coverage layer in Norgeskart).
    map_selection_layer: str | None = None


@dataclass
class DatasetAvailability:
    metadata_uuid: str
    title: str
    categories: list[str] = field(default_factory=list)
    original_categories: list[str] = field(default_factory=list)
    login_required: bool = False
    access_is_restricted: bool = False
    access_is_protected: bool = False
    access_is_opendata: bool = False
    data_access: str | None = None
    enriched: bool = False
    # ISO timestamp from Kartkatalog DateMetadataUpdated (used to skip unchanged records).
    catalog_metadata_updated: str | None = None
    enrichment_version: int = 0
    download_api_base: str | None = None
    capabilities: DatasetCapabilities | None = None
    area_types: set[AreaType] = field(default_factory=set)
    areas_by_type: dict[AreaType, list[AreaOption]] = field(default_factory=dict)
    formats: list[FormatOption] = field(default_factory=list)
    projections: list[ProjectionOption] = field(default_factory=list)

