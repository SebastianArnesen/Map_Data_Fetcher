from __future__ import annotations

import time
from typing import Any

from .client import GeonorgeError, HttpClient
from .compatibility import area_supports, format_key
from .constants import ORDER_CHUNK_SIZE, ORDER_POLL_INTERVAL_S
from .models import (
    AreaOption,
    AreaType,
    DatasetAvailability,
    DatasetCapabilities,
    FormatOption,
    OrderFile,
    ProjectionOption,
)


class NedlastingClient:
    BASE = "https://nedlasting.geonorge.no/api"

    def __init__(self, http: HttpClient):
        self._http = http
        self._order_area_type_cache: dict[tuple[str, str], list[Any]] = {}

    def _base(self, base_url: str | None = None) -> str:
        return (base_url or self.BASE).rstrip("/")

    def try_list_internal_datasets(self) -> list[DatasetAvailability] | None:
        """
        Best-effort: if the internal dataset listing is publicly accessible, it gives us
        the cleanest (title, metadataUuid) list. Otherwise returns None.
        """
        url = f"{self.BASE}/internal/dataset"
        res = self._http.get_json(url)
        if res.status_code in (401, 403, 404):
            return None
        if res.status_code != 200 or not isinstance(res.json, list):
            return None

        out: list[DatasetAvailability] = []
        for item in res.json:
            if not isinstance(item, dict):
                continue
            title = item.get("Title") or item.get("title") or item.get("Name") or item.get("name")
            uuid = item.get("MetadataUuid") or item.get("metadataUuid") or item.get("metadata_uuid")
            if not uuid:
                continue
            out.append(DatasetAvailability(metadata_uuid=str(uuid), title=str(title or uuid)))
        return out

    def capabilities(self, metadata_uuid: str, *, base_url: str | None = None) -> DatasetCapabilities | None:
        # Prefer v2 if available, fall back to v1.
        base = self._base(base_url)
        for url in (f"{base}/v2/capabilities/{metadata_uuid}", f"{base}/capabilities/{metadata_uuid}"):
            res = self._http.get_json(url)
            if res.status_code in (401, 403):
                raise PermissionError("Login required")
            if res.status_code == 404:
                continue
            if res.status_code != 200 or not isinstance(res.json, dict):
                continue
            return DatasetCapabilities(
                supports_projection_selection=bool(res.json.get("supportsProjectionSelection")),
                supports_format_selection=bool(res.json.get("supportsFormatSelection")),
                supports_polygon_selection=bool(res.json.get("supportsPolygonSelection")),
                supports_area_selection=bool(res.json.get("supportsAreaSelection")),
                map_selection_layer=(
                    str(res.json.get("mapSelectionLayer")).strip()
                    if isinstance(res.json.get("mapSelectionLayer"), str) and str(res.json.get("mapSelectionLayer")).strip()
                    else None
                ),
            )
        return None

    def formats(self, metadata_uuid: str, *, base_url: str | None = None) -> list[FormatOption]:
        base = self._base(base_url)
        res = None
        for url in (f"{base}/v2/codelists/format/{metadata_uuid}", f"{base}/codelists/format/{metadata_uuid}"):
            res = self._http.get_json(url)
            if res.status_code in (401, 403):
                raise PermissionError("Login required")
            if res.status_code == 200:
                break
        if res is None or res.status_code != 200:
            return []
        if isinstance(res.json, list):
            items = res.json
        elif isinstance(res.json, dict):
            items = res.json.get("formats") or res.json.get("Formats") or res.json.get("items") or res.json.get("Items")
            if not isinstance(items, list):
                items = res.json.get("content") if isinstance(res.json.get("content"), list) else []
        else:
            items = []
        out: list[FormatOption] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            name = it.get("name") or it.get("Name")
            if not name:
                continue
            out.append(FormatOption(name=str(name), version=(it.get("version") or it.get("Version"))))
        # De-dupe on name+version
        seen: set[tuple[str, str | None]] = set()
        uniq: list[FormatOption] = []
        for f in out:
            key = (f.name, f.version)
            if key in seen:
                continue
            seen.add(key)
            uniq.append(f)
        return uniq

    def projections(self, metadata_uuid: str, *, base_url: str | None = None) -> list[ProjectionOption]:
        base = self._base(base_url)
        res = None
        for url in (f"{base}/v2/codelists/projection/{metadata_uuid}", f"{base}/codelists/projection/{metadata_uuid}"):
            res = self._http.get_json(url)
            if res.status_code in (401, 403):
                raise PermissionError("Login required")
            if res.status_code == 200:
                break
        if res is None or res.status_code != 200:
            return []
        if isinstance(res.json, list):
            items = res.json
        elif isinstance(res.json, dict):
            items = (
                res.json.get("projections")
                or res.json.get("Projections")
                or res.json.get("items")
                or res.json.get("Items")
            )
            if not isinstance(items, list):
                items = res.json.get("content") if isinstance(res.json.get("content"), list) else []
        else:
            items = []
        out: list[ProjectionOption] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            code = it.get("code") or it.get("Code")
            if not code:
                continue
            out.append(
                ProjectionOption(
                    code=str(code),
                    name=(it.get("name") or it.get("Name")),
                    codespace=(it.get("codespace") or it.get("Codespace")),
                )
            )
        # De-dupe on code
        seen: set[str] = set()
        uniq: list[ProjectionOption] = []
        for p in out:
            if p.code in seen:
                continue
            seen.add(p.code)
            uniq.append(p)
        return uniq

    def areas(self, metadata_uuid: str, *, base_url: str | None = None) -> dict[AreaType, list[AreaOption]]:
        """
        Returns areas grouped by type (landsdekkende/fylke/kommune when present).
        """
        base = self._base(base_url)
        urls = (f"{base}/v2/codelists/area/{metadata_uuid}", f"{base}/codelists/area/{metadata_uuid}")
        last: Any | None = None
        for url in urls:
            res = self._http.get_json(url)
            if res.status_code in (401, 403):
                raise PermissionError("Login required")
            if res.status_code == 404:
                continue
            last = res.json
            if res.status_code != 200 or res.json is None:
                continue
            parsed = _parse_areas_payload(res.json)
            if parsed:
                return parsed
        if last is not None:
            return _parse_areas_payload(last)
        return {}

    def place_order(
        self,
        *,
        metadata_uuid: str,
        area_type: AreaType | None,
        area_code: str | None,
        format_name: str,
        projection_code: str | None,
        base_url: str | None = None,
        usage: str = "Geonorge Datasets",
        area_option: AreaOption | None = None,
    ) -> str:
        areas: list[tuple[AreaType | None, str | None, AreaOption | None]] = []
        if area_type and area_code:
            areas = [(area_type, area_code, area_option)]
        refs = self.place_batch_order(
            metadata_uuid=metadata_uuid,
            areas=areas,
            format_name=format_name,
            projection_code=projection_code,
            base_url=base_url,
            usage=usage,
        )
        return refs[0]

    def place_batch_order(
        self,
        *,
        metadata_uuid: str,
        areas: list[tuple[AreaType | None, str | None, AreaOption | None]],
        format_name: str,
        projection_code: str | None,
        base_url: str | None = None,
        usage: str = "Geonorge Datasets",
    ) -> list[str]:
        """
        Place one or more Geonorge orders with multiple orderLines per POST.

        Returns one reference number per successful POST (multiple if chunking fallback splits the request).
        """
        if not areas:
            payload = self._build_order_payload(
                metadata_uuid, [], format_name, projection_code, base_url, usage
            )
            return [self._post_order_payload(payload, base_url)]

        selections = list(areas)
        refs: list[str] = []
        chunk_size = max(1, ORDER_CHUNK_SIZE)
        offset = 0
        while offset < len(selections):
            chunk = selections[offset : offset + chunk_size]
            try:
                payload = self._build_order_payload(
                    metadata_uuid, chunk, format_name, projection_code, base_url, usage
                )
                refs.append(self._post_order_payload(payload, base_url))
                offset += len(chunk)
            except GeonorgeError:
                if len(chunk) <= 1:
                    raise
                chunk_size = max(1, len(chunk) // 2)
        return refs

    def _build_order_payload(
        self,
        metadata_uuid: str,
        areas: list[tuple[AreaType | None, str | None, AreaOption | None]],
        format_name: str,
        projection_code: str | None,
        base_url: str | None,
        usage: str,
    ) -> dict[str, Any]:
        order_lines: list[dict[str, Any]] = []
        if not areas:
            line: dict[str, Any] = {
                "metadataUuid": metadata_uuid,
                "formats": [{"name": format_name}],
            }
            if projection_code:
                line["projections"] = [{"code": str(projection_code)}]
            order_lines.append(line)
        else:
            for area_type, area_code, area_option in areas:
                if not area_type or not area_code:
                    continue
                line = {
                    "metadataUuid": metadata_uuid,
                    "formats": [{"name": format_name}],
                    "areas": [
                        {
                            "code": area_code,
                            "type": self._resolve_order_area_type(
                                metadata_uuid=metadata_uuid,
                                area_type=area_type,
                                area_code=area_code,
                                format_name=format_name,
                                projection_code=projection_code,
                                base_url=base_url,
                            ),
                        }
                    ],
                }
                if projection_code:
                    line["projections"] = [{"code": str(projection_code)}]
                order_lines.append(line)
        return {"usage": usage, "orderLines": order_lines}

    def _post_order_payload(self, payload: dict[str, Any], base_url: str | None) -> str:
        base = self._base(base_url)
        urls = (f"{base}/order", f"{base}/v2/order")
        res = None
        for url in urls:
            res = self._http.post_json(url, payload)
            if res.status_code != 404:
                break
        if res is None:
            raise GeonorgeError("Failed to place order: no order endpoint attempted.")
        if res.status_code in (401, 403):
            raise PermissionError("Login required")
        if res.status_code not in (200, 201, 211):
            raise GeonorgeError(f"Failed to place order ({res.status_code}): {res.text[:500]}")
        if not isinstance(res.json, dict) or not res.json.get("referenceNumber"):
            raise GeonorgeError("Order response missing referenceNumber.")
        return str(res.json["referenceNumber"])

    def _resolve_order_area_type(
        self,
        *,
        metadata_uuid: str,
        area_type: AreaType,
        area_code: str,
        format_name: str,
        projection_code: str | None,
        base_url: str | None = None,
    ) -> str:
        # The UI normalizes both "celle" and "ikke spesifisert" to Cell, but
        # Geonorge may require the raw type that carries the chosen delivery option.
        if area_type != "celle":
            return area_type
        items = self._area_codelist_items(metadata_uuid=metadata_uuid, base_url=base_url)
        if not items:
            return area_type
        first_matching_type: str | None = None
        for item in items:
            if not isinstance(item, dict):
                continue
            raw_type = str(item.get("type") or item.get("Type") or "")
            normalized = _normalize_area_type(raw_type)
            code = item.get("code") or item.get("Code")
            if normalized != area_type or str(code) != str(area_code):
                continue
            first_matching_type = first_matching_type or raw_type
            if _area_item_supports_selection(item, format_name=format_name, projection_code=projection_code):
                return raw_type
        return first_matching_type or area_type

    def _area_codelist_items(self, *, metadata_uuid: str, base_url: str | None) -> list[Any]:
        base = self._base(base_url)
        cache_key = (metadata_uuid, base)
        cached = self._order_area_type_cache.get(cache_key)
        if cached is not None:
            return cached
        res = None
        for url in (f"{base}/v2/codelists/area/{metadata_uuid}", f"{base}/codelists/area/{metadata_uuid}"):
            res = self._http.get_json(url)
            if res.status_code == 200:
                break
        items: list[Any] = res.json if res is not None and res.status_code == 200 and isinstance(res.json, list) else []
        self._order_area_type_cache[cache_key] = items
        return items

    def validate_area_format_projection(
        self,
        *,
        metadata_uuid: str,
        area_type: AreaType | None,
        area_code: str | None,
        format_name: str,
        projection_code: str | None,
        base_url: str | None = None,
        area_option: AreaOption | None = None,
    ) -> tuple[bool, str | None]:
        """
        Preflight using cached per-area compatibility when available.
        Falls back to dataset-wide codelists only when area_option is not provided.
        """
        if not area_type or not area_code:
            return (True, None)

        area = area_option
        if area is None:
            try:
                areas_by_type = self.areas(metadata_uuid, base_url=base_url)
            except PermissionError:
                return (False, "Requires login/authorization.")
            for candidate in areas_by_type.get(area_type) or []:
                if candidate.code == area_code:
                    area = candidate
                    break
            if area is None:
                return (False, "Selected area is not available for this dataset.")

        if not area_supports(area, projection_code=projection_code, format_name=format_name):
            if projection_code and not area_supports(area, projection_code=projection_code):
                return (False, "Selected projection is not available for this area.")
            return (False, "Selected format is not available for this area and projection.")

        if area.formats or area.projections or area.formats_by_projection:
            return (True, None)

        try:
            formats = self.formats(metadata_uuid, base_url=base_url)
            if formats and not any(f.name == format_name for f in formats):
                return (False, "Selected format is not available for this dataset.")
            projections = self.projections(metadata_uuid, base_url=base_url)
            if projections and projection_code and not any(p.code == projection_code for p in projections):
                return (False, "Selected projection is not available for this dataset.")
        except PermissionError:
            return (False, "Requires login/authorization.")
        return (True, None)

    def poll_download_url(
        self,
        reference_number: str,
        *,
        base_url: str | None = None,
        timeout_s: float = 60 * 30,
        poll_s: float = ORDER_POLL_INTERVAL_S,
    ) -> str:
        start = time.time()
        while True:
            files = self.poll_order_files(reference_number, base_url=base_url)
            for order_file in files:
                if order_file.is_downloadable and order_file.download_url:
                    return order_file.download_url
            if time.time() - start > timeout_s:
                raise GeonorgeError("Timed out waiting for files.")
            time.sleep(poll_s)

    def poll_order_files(
        self,
        reference_number: str,
        *,
        base_url: str | None = None,
    ) -> list[OrderFile]:
        base = self._base(base_url)
        urls = (f"{base}/order/{reference_number}", f"{base}/v2/order/{reference_number}")
        res = None
        for url in urls:
            res = self._http.get_json(url)
            if res.status_code != 404:
                break
        if res is None:
            raise GeonorgeError("No order status endpoint attempted.")
        if res.status_code in (401, 403):
            raise PermissionError("Login required")
        if res.status_code != 200:
            raise GeonorgeError(f"Order status failed ({res.status_code}).")
        data = res.json
        if isinstance(data, list) and data:
            data = data[0]
        if not isinstance(data, dict):
            raise GeonorgeError("Unexpected order status response.")
        return parse_order_files(data.get("files") or [])


def parse_order_files(raw_files: Any) -> list[OrderFile]:
    if not isinstance(raw_files, list):
        return []
    out: list[OrderFile] = []
    for item in raw_files:
        if not isinstance(item, dict):
            continue
        out.append(
            OrderFile(
                file_id=_str_or_none(item.get("fileId") or item.get("FileId")),
                area_code=_str_or_none(item.get("area") or item.get("Area")),
                download_url=_str_or_none(item.get("downloadUrl") or item.get("DownloadUrl")),
                status=_str_or_none(item.get("status") or item.get("Status")),
                name=_str_or_none(item.get("name") or item.get("Name")),
                format_name=_str_or_none(item.get("format") or item.get("Format")),
                projection_code=_str_or_none(item.get("projection") or item.get("Projection")),
            )
        )
    return out


def all_packaging_complete(files: list[OrderFile], *, expected_area_codes: set[str]) -> bool:
    """True when every expected area has a downloadable file."""
    if not expected_area_codes:
        return any(f.is_downloadable for f in files)
    ready = {f.area_code for f in files if f.is_downloadable and f.area_code}
    return expected_area_codes <= ready


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_areas_payload(payload: Any) -> dict[AreaType, list[AreaOption]]:
    collected: dict[AreaType, dict[str, AreaOption]] = {}

    # Common shapes:
    # - {"areas":[{type,code,name},...]}  (flat)
    # - {"codelists":[{"type":"fylke","values":[...]}, ...]}  (grouped)
    # - {"areasByType": {"fylke":[...], ...}}
    # - [{type,code,name},...]  (flat list)
    if isinstance(payload, list):
        for it in payload:
            if not isinstance(it, dict):
                continue
            t = it.get("type") or it.get("Type")
            code = it.get("code") or it.get("Code")
            name = it.get("name") or it.get("Name")
            if t and code and name:
                at = _normalize_area_type(str(t))
                if at:
                    _merge_area_option(collected, _area_option_from_dict(at, it, code, name))
        return _finalize_area_options(collected)

    if isinstance(payload, dict):
        if isinstance(payload.get("areasByType"), dict):
            for t, values in payload["areasByType"].items():
                _add_area_values(collected, str(t), values)
            return _finalize_area_options(collected)

        areas = payload.get("areas") or payload.get("Areas")
        if isinstance(areas, list):
            for it in areas:
                if not isinstance(it, dict):
                    continue
                t = it.get("type") or it.get("Type")
                code = it.get("code") or it.get("Code")
                name = it.get("name") or it.get("Name")
                if t and code and name:
                    at = _normalize_area_type(str(t))
                    if at:
                        _merge_area_option(collected, _area_option_from_dict(at, it, code, name))
            if collected:
                return _finalize_area_options(collected)

        codelists = payload.get("codelists") or payload.get("Codelists")
        if isinstance(codelists, list):
            for cl in codelists:
                if not isinstance(cl, dict):
                    continue
                t = cl.get("type") or cl.get("Type")
                values = cl.get("values") or cl.get("Values") or cl.get("areas") or cl.get("Areas")
                if t:
                    _add_area_values(collected, str(t), values)
            if collected:
                return _finalize_area_options(collected)

    return {}


def _normalize_area_type(value: str) -> AreaType | None:
    key = " ".join(value.strip().casefold().split())
    if key in ("landsdekkende", "fylke", "kommune", "celle"):
        return key  # type: ignore[return-value]
    if key == "ikke spesifisert":
        return "celle"
    return None


def _add_area_values(out: dict[AreaType, dict[str, AreaOption]], t: str, values: Any) -> None:
    normalized_type = _normalize_area_type(t)
    if normalized_type is None:
        return
    if not isinstance(values, list):
        return
    for it in values:
        if not isinstance(it, dict):
            continue
        code = it.get("code") or it.get("Code")
        name = it.get("name") or it.get("Name")
        if code and name:
            _merge_area_option(out, _area_option_from_dict(normalized_type, it, code, name))


def _merge_area_option(out: dict[AreaType, dict[str, AreaOption]], option: AreaOption) -> None:
    by_code = out.setdefault(option.type, {})
    existing = by_code.get(option.code)
    if existing is None:
        by_code[option.code] = option
        return
    by_code[option.code] = AreaOption(
        type=existing.type,
        code=existing.code,
        name=existing.name or option.name,
        formats=_merge_formats(existing.formats, option.formats),
        projections=_merge_projections(existing.projections, option.projections),
        formats_by_projection=_merge_formats_by_projection(
            existing.formats_by_projection, option.formats_by_projection
        ),
    )


def _finalize_area_options(collected: dict[AreaType, dict[str, AreaOption]]) -> dict[AreaType, list[AreaOption]]:
    return {area_type: list(by_code.values()) for area_type, by_code in collected.items()}


def _merge_formats(left: list[FormatOption], right: list[FormatOption]) -> list[FormatOption]:
    seen: set[str] = set()
    out: list[FormatOption] = []
    for fmt in [*left, *right]:
        key = fmt.label.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(fmt)
    return out


def _merge_projections(left: list[ProjectionOption], right: list[ProjectionOption]) -> list[ProjectionOption]:
    seen: set[str] = set()
    out: list[ProjectionOption] = []
    for projection in [*left, *right]:
        if projection.code in seen:
            continue
        seen.add(projection.code)
        out.append(projection)
    return out


def _merge_formats_by_projection(
    left: dict[str, frozenset[str]],
    right: dict[str, frozenset[str]],
) -> dict[str, frozenset[str]]:
    """Intersect per-projection format sets when duplicate area rows are merged."""
    merged: dict[str, set[str]] = {}
    for code in set(left) | set(right):
        left_fmts = left.get(code) or frozenset()
        right_fmts = right.get(code) or frozenset()
        if left_fmts and right_fmts:
            merged[code] = set(left_fmts) & set(right_fmts)
        elif left_fmts:
            merged[code] = set(left_fmts)
        elif right_fmts:
            merged[code] = set(right_fmts)
    return {code: frozenset(fmts) for code, fmts in merged.items()}


def _area_option_from_dict(area_type: str, item: dict[str, Any], code: Any, name: Any) -> AreaOption:
    formats = _parse_embedded_formats(item.get("formats") or item.get("Formats"))
    projections = _parse_embedded_projections(item.get("projections") or item.get("Projections"))
    formats_by_projection = _parse_formats_by_projection(item, formats=formats, projections=projections)
    return AreaOption(
        type=area_type,  # type: ignore[arg-type]
        code=str(code),
        name=str(name),
        formats=formats,
        projections=projections,
        formats_by_projection=formats_by_projection,
    )


def _format_name_key(value: Any) -> str:
    return " ".join(str(value or "").split()).casefold()


def _area_item_supports_selection(item: dict[str, Any], *, format_name: str, projection_code: str | None) -> bool:
    target_format = _format_name_key(format_name)
    formats = item.get("formats") or item.get("Formats") or []
    projections = item.get("projections") or item.get("Projections") or []

    format_ok = True
    if isinstance(formats, list) and formats:
        format_ok = any(
            isinstance(fmt, dict) and _format_name_key(fmt.get("name") or fmt.get("Name")) == target_format
            for fmt in formats
        )

    projection_ok = True
    if projection_code and isinstance(projections, list) and projections:
        projection_ok = False
        for projection in projections:
            if not isinstance(projection, dict) or str(projection.get("code") or projection.get("Code")) != str(projection_code):
                continue
            projection_formats = projection.get("formats") or projection.get("Formats") or []
            if isinstance(projection_formats, list) and projection_formats:
                if not any(
                    isinstance(fmt, dict) and _format_name_key(fmt.get("name") or fmt.get("Name")) == target_format
                    for fmt in projection_formats
                ):
                    continue
            projection_ok = True
            break

    return format_ok and projection_ok


def _parse_embedded_formats(items: Any) -> list[FormatOption]:
    if not isinstance(items, list):
        return []
    seen: set[str] = set()
    out: list[FormatOption] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        name = it.get("name") or it.get("Name")
        if not name:
            continue
        fmt = FormatOption(name=str(name), version=(it.get("version") or it.get("Version")))
        key = fmt.label.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(fmt)
    return out


def _parse_embedded_projections(items: Any) -> list[ProjectionOption]:
    if not isinstance(items, list):
        return []
    seen: set[str] = set()
    out: list[ProjectionOption] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        code = it.get("code") or it.get("Code")
        if not code:
            continue
        code = str(code)
        if code in seen:
            continue
        seen.add(code)
        out.append(
            ProjectionOption(
                code=code,
                name=(it.get("name") or it.get("Name")),
                codespace=(it.get("codespace") or it.get("Codespace")),
            )
        )
    return out


def _parse_formats_by_projection(
    item: dict[str, Any],
    *,
    formats: list[FormatOption],
    projections: list[ProjectionOption],
) -> dict[str, frozenset[str]]:
    raw_projections = item.get("projections") or item.get("Projections") or []
    if not isinstance(raw_projections, list):
        raw_projections = []

    flat_keys = {format_key(f) for f in formats}
    result: dict[str, set[str]] = {}
    has_nested_formats = False

    for projection in raw_projections:
        if not isinstance(projection, dict):
            continue
        code = projection.get("code") or projection.get("Code")
        if not code:
            continue
        code = str(code)
        nested = projection.get("formats") or projection.get("Formats") or []
        if isinstance(nested, list) and nested:
            has_nested_formats = True
            keys = {
                _format_name_key(fmt.get("name") or fmt.get("Name"))
                for fmt in nested
                if isinstance(fmt, dict) and (fmt.get("name") or fmt.get("Name"))
            }
            result.setdefault(code, set()).update(keys)
        else:
            result.setdefault(code, set())

    if has_nested_formats:
        for code, keys in list(result.items()):
            if not keys and flat_keys:
                result[code] = set(flat_keys)
        return {code: frozenset(keys) for code, keys in result.items() if keys}

    if projections and flat_keys:
        return {p.code: frozenset(flat_keys) for p in projections}

    return {}

