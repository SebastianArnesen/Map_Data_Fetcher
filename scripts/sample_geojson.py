"""Dev-only: fetch and summarize a GeoJSON URL (default kartkatalog host)."""

import json
import sys

import requests

url = sys.argv[1] if len(sys.argv) > 1 else "https://kartkatalog.geonorge.no/json/dekning/dtm10.geojson"
r = requests.get(url, timeout=60, headers={"Accept": "application/json"})
print("status", r.status_code, "ctype", r.headers.get("content-type"), "len", len(r.content))
r.raise_for_status()
d = r.json()
print("type", d.get("type"), "features", len(d.get("features") or []))
if d.get("features"):
    props = d["features"][0].get("properties") or {}
    print("props keys", list(props.keys())[:15])
    print("sample props", props)
