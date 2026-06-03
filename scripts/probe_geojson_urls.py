"""Dev-only probe: HEAD/GET alternate GeoJSON hosts (not app production URLs)."""

from __future__ import annotations

import sys

import requests


def head(url: str) -> tuple[int | None, str]:
    try:
        r = requests.get(
            url,
            timeout=15,
            allow_redirects=True,
            headers={
                "Accept": "application/json,*/*",
                "Referer": "https://kartkatalog.geonorge.no/nedlasting",
            },
        )
        ctype = (r.headers.get("content-type") or "")[:40]
        if "json" in ctype or (r.content[:1] == b"{"):
            return r.status_code, ctype
        return r.status_code, ctype or "non-json"
    except Exception:
        return None, ""


def main() -> int:
    urls = sys.argv[1:]
    if not urls:
        urls = [
            "https://norgeskart.no/json/dekning/dtm/dtm-dekning-utm32.geojson",
            "https://norgeskart.no/json/dekning/dtm/dtm_dekning_utm32.geojson",
            "https://norgeskart.no/json/dekning/hoyde/dtm-dekning-utm32.geojson",
            "https://norgeskart.no/json/dekning/terrengmodell/dtm-dekning-utm32.geojson",
            "https://norgeskart.no/json/dekning/dtm/dtm_utm32.geojson",
            "https://norgeskart.no/json/dekning/dtm-dekning-utm32.geojson",
        ]
    for u in urls:
        code, ctype = head(u)
        print(f"{code} {ctype} {u}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

