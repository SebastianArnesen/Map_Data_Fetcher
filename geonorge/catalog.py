from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote, urlparse

from .client import HttpClient
from .models import DatasetRef


@dataclass(frozen=True)
class KartkatalogMetadata:
    title: str | None
    categories: list[str]
    original_categories: list[str]
    download_api_base: str | None
    metadata_updated: str | None


class KartkatalogCatalog:
    BASE = "https://kartkatalog.geonorge.no/api"

    def __init__(self, http: HttpClient):
        self._http = http

    def sitemap_uuids(self, *, limit: int = 5000) -> list[str]:
        """
        Kartkatalog's search endpoint currently returns 0 results. The sitemap endpoint provides
        a large list of metadata URLs; we extract UUIDs from it.
        """
        url = f"{self.BASE}/sitemap"
        res = self._http.get_text(url)
        if res.status_code != 200 or not res.text:
            return []
        uuids = _extract_uuids(res.text)
        # de-dupe, preserve order
        seen: set[str] = set()
        out: list[str] = []
        for u in uuids:
            if u in seen:
                continue
            seen.add(u)
            out.append(u)
            if len(out) >= limit:
                break
        return out

    def sitemap_refs(self, *, limit: int = 5000) -> list[DatasetRef]:
        """
        Fast startup list: sitemap URLs include both a slug and UUID, so we can show
        readable dataset titles immediately without making hundreds of getdata calls.
        """
        url = f"{self.BASE}/sitemap"
        res = self._http.get_text(url)
        if res.status_code != 200 or not res.text:
            return []
        refs = _extract_refs(res.text)
        seen: set[str] = set()
        out: list[DatasetRef] = []
        for ref in refs:
            if ref.metadata_uuid in seen:
                continue
            seen.add(ref.metadata_uuid)
            out.append(ref)
            if len(out) >= limit:
                break
        return out

    def get_title(self, metadata_uuid: str) -> str | None:
        url = f"{self.BASE}/getdata/{metadata_uuid}"
        res = self._http.get_json(url)
        if res.status_code != 200 or not isinstance(res.json, dict):
            return None
        title = res.json.get("Title") or res.json.get("NorwegianTitle") or res.json.get("EnglishTitle")
        if isinstance(title, str) and title.strip():
            return title.strip()
        return None

    def get_metadata(self, metadata_uuid: str) -> KartkatalogMetadata | None:
        url = f"{self.BASE}/getdata/{metadata_uuid}"
        res = self._http.get_json(url)
        if res.status_code != 200 or not isinstance(res.json, dict):
            return None
        payload = res.json
        title = payload.get("Title") or payload.get("NorwegianTitle") or payload.get("EnglishTitle")
        clean_title = title.strip() if isinstance(title, str) and title.strip() else None
        original_categories = _extract_category_tags(payload)
        return KartkatalogMetadata(
            title=clean_title,
            categories=normalize_categories(original_categories),
            original_categories=original_categories,
            download_api_base=_extract_download_api_base(payload),
            metadata_updated=_extract_metadata_updated(payload),
        )

    def get_title_and_categories(self, metadata_uuid: str) -> tuple[str | None, list[str], list[str], str | None]:
        meta = self.get_metadata(metadata_uuid)
        if meta is None:
            return (None, [], [], None)
        return (meta.title, meta.categories, meta.original_categories, meta.download_api_base)

    def search(self, *, text: str = "", limit: int = 200, offset: int = 0) -> tuple[list[DatasetRef], int]:
        """
        Returns (results, num_found).

        Kartkatalog's schema varies a bit; we robustly extract uuid + title.
        """
        url = f"{self.BASE}/search"
        res = self._http.get_json(url, params={"text": text, "limit": limit, "offset": offset})
        if res.status_code != 200 or not isinstance(res.json, dict):
            return ([], 0)

        num_found = int(res.json.get("NumFound") or 0)
        results = res.json.get("Results") or []
        out: list[DatasetRef] = []
        if isinstance(results, list):
            for item in results:
                if not isinstance(item, dict):
                    continue
                uuid = item.get("Uuid") or item.get("uuid") or item.get("MetadataUuid") or item.get("metadataUuid")
                if not uuid:
                    continue
                title = _extract_title(item) or str(uuid)
                out.append(DatasetRef(metadata_uuid=str(uuid), title=title))
        return out, num_found


def _extract_title(item: dict[str, Any]) -> str | None:
    for k in ("Title", "title", "Name", "name"):
        v = item.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    # Sometimes nested.
    md = item.get("Metadata") or item.get("metadata")
    if isinstance(md, dict):
        for k in ("Title", "title"):
            v = md.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return None


def _extract_metadata_updated(item: dict[str, Any]) -> str | None:
    for key in ("DateMetadataUpdated", "dateMetadataUpdated", "MetadataUpdated", "metadataUpdated"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _extract_download_api_base(item: dict[str, Any]) -> str | None:
    candidates: list[str] = []
    details = item.get("DistributionDetails")
    if isinstance(details, dict):
        url = details.get("URL") or details.get("Url") or details.get("url")
        protocol = str(details.get("Protocol") or details.get("protocol") or "")
        if isinstance(url, str) and "DOWNLOAD" in protocol.upper():
            candidates.append(url)
    for key in ("DownloadUrl", "DistributionUrl", "MapLink"):
        value = item.get(key)
        if isinstance(value, str):
            candidates.append(value)
    for candidate in candidates:
        base = _normalize_download_api_base(candidate)
        if base:
            return base
    return None


def _normalize_download_api_base(value: str) -> str | None:
    parsed = urlparse(value.strip())
    if not parsed.scheme or not parsed.netloc:
        return None
    path = parsed.path
    marker = "/api/"
    if marker in path:
        prefix = path.split(marker, 1)[0]
        return f"{parsed.scheme}://{parsed.netloc}{prefix}/api".rstrip("/")
    if path.rstrip("/").endswith("/api"):
        return f"{parsed.scheme}://{parsed.netloc}{path.rstrip('/')}"
    return None


def _extract_category_tags(item: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("TopicCategories", "TopicCategory", "KeywordsTheme", "KeywordsNationalTheme"):
        raw = item.get(key)
        if isinstance(raw, str):
            values.append(raw)
        elif isinstance(raw, list):
            for value in raw:
                if isinstance(value, str):
                    values.append(value)
                elif isinstance(value, dict) and value.get("EnglishKeyword"):
                    keyword = value.get("KeywordValue")
                    if isinstance(keyword, str):
                        values.append(keyword)
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        cleaned = value.strip()
        normalized = cleaned.casefold()
        if not cleaned or cleaned.startswith(("{", "[")) or normalized in seen:
            continue
        seen.add(normalized)
        out.append(cleaned)
    return out


_CATEGORY_ALIASES: dict[str, str] = {
    "1:50 000": "1:50 000",
    "1:50000": "1:50 000",
    "norge 1:50 000": "1:50 000",
    "administrativ inndeling": "Administrativ inndeling",
    "administrative grenser": "Administrativ inndeling",
    "aktsomhet": "Aktsomhet",
    "aktsomhetsgrad": "Aktsomhet",
    "basis geodata": "Basisdata",
    "basisdata": "Basisdata",
    "batymetri": "Batymetri og Dybde",
    "dybde": "Batymetri og Dybde",
    "dybdeareal": "Batymetri og Dybde",
    "dybdedata": "Batymetri og Dybde",
    "dybdekontur": "Batymetri og Dybde",
    "dybdekurver": "Batymetri og Dybde",
    "dybdelag": "Batymetri og Dybde",
    "dybdepunkt": "Batymetri og Dybde",
    "havbunn": "Batymetri og Dybde",
    "havdyp": "Batymetri og Dybde",
    "sjøbunn": "Batymetri og Dybde",
    "sjødyp": "Batymetri og Dybde",
    "bygningar": "Bygninger",
    "bygninger": "Bygninger",
    "kirker": "Bygninger",
    "kyrkjer": "Bygninger",
    "digital terrengmodell": "Terrengmodeller",
    "dtm": "Terrengmodeller",
    "terrengmodell": "Terrengmodeller",
    "farekart": "Farekart",
    "farekartlegging": "Farekart",
    "farled": "Farled",
    "farledsforskriften": "Farled",
    "flom": "Flom",
    "flomutsatt areal": "Flom",
    "gass felt": "Gass",
    "gass funn": "Gass",
    "geologi": "Geologi",
    "geoligiske-grenser": "Geologi",
    "geologiske-grenser": "Geologi",
    "geovitenskapelig informasjon": "Geologi",
    "grunne": "Grunne",
    "grunnvann": "Grunne",
    "hav": "Hav",
    "norskehavet": "Hav",
    "høyde": "Høyde",
    "høydedata": "Høyde",
    "høydemodell": "Høyde",
    "kart over norge": "Kart",
    "kartdata": "Kart",
    "m711": "Kart",
    "kulturminne": "Kulturminner",
    "kulturminner": "Kulturminner",
    "sefrak": "Kulturminner",
    "kyst": "Kyst",
    "kyst og fiskeri": "Kyst",
    "kyst og sjø": "Kyst",
    "kystverket": "Kyst",
    "listeført": "Listeført",
    "los": "Los",
    "losbording": "Los",
    "losbordingsplass": "Los",
    "løsmasse": "Løsmasse",
    "løsmasser": "Løsmasse",
    "magnetiske-grenser": "Magnetisme",
    "mbe": "MBE (Multibeam Echosounder)",
    "multistråle": "MBE (Multibeam Echosounder)",
    "n 50": "N50",
    "n50": "N50",
    "n50 raster": "N50",
    "natur": "Natur",
    "naturforvaltning": "Natur",
    "olje felt": "Petroleum",
    "olje funn": "Petroleum",
    "olje rig": "Petroleum",
    "petroleums funn": "Petroleum",
    "overflate installasjoner": "Overflateinstallasjoner",
    "overflateinstallasjon": "Overflateinstallasjoner",
    "produksjons skip": "Produksjonsskip",
    "pukk": "Steinindustri",
    "steinindustri": "Steinindustri",
    "rein": "Reinsdyr",
    "reindrift": "Reinsdyr",
    "s57": "S-57",
    "samferdsel": "Samfunn & Kultur",
    "samfunn og kultur": "Samfunn & Kultur",
    "samfunnssikkerhet": "Samfunn & Kultur",
    "sjø": "Sjø",
    "sjødata": "Sjø",
    "sjødivisjonen": "Sjø",
    "sjøkart": "Sjø",
    "sjøsikkerhet": "Sjø",
    "sjøtrafikk": "Sjø",
    "strukturelementer": "Strukturelementer",
    "trafikkdata": "Trafikk & Veier",
    "trafikkmengde": "Trafikk & Veier",
    "veginformasjon": "Trafikk & Veier",
    "ådt": "Trafikk & Veier",
    "tørrfall": "Tørrfall",
    "tørrfallsgrense": "Tørrfall",
}


def normalize_categories(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        normalized = _normalize_category(value)
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(normalized)
    return out


def _normalize_category(value: str) -> str:
    compact = " ".join(value.replace("_", " ").strip().split())
    key = compact.casefold()
    if key in _CATEGORY_ALIASES:
        return _CATEGORY_ALIASES[key]
    if compact.isupper() and len(compact) <= 5:
        return compact
    if compact.islower() or compact[:1].islower():
        return compact[:1].upper() + compact[1:]
    return compact


_UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_SITEMAP_REF_RE = re.compile(
    r"https://kartkatalog\.geonorge\.no/metadata/(?P<slug>[^/<]+)/(?P<uuid>[0-9a-fA-F-]{36})"
)


def _extract_uuids(text: str) -> list[str]:
    return _UUID_RE.findall(text)


def _slug_to_title(slug: str) -> str:
    """Turn a Kartkatalog URL slug into a display title (UTF-8, Norwegian letters preserved)."""
    text = unquote(slug, encoding="utf-8").replace("-", " ")
    text = " ".join(text.split())
    if not text:
        return ""
    return " ".join(part[:1].upper() + part[1:] if part else "" for part in text.split())


def _extract_refs(text: str) -> list[DatasetRef]:
    out: list[DatasetRef] = []
    for match in _SITEMAP_REF_RE.finditer(text):
        slug = match.group("slug")
        title = _slug_to_title(slug)
        out.append(DatasetRef(metadata_uuid=match.group("uuid"), title=title or match.group("uuid")))
    return out

