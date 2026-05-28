from __future__ import annotations

import re
from dataclasses import dataclass

import requests


@dataclass(frozen=True)
class UpdateInfo:
    latest_version: str
    release_url: str
    is_prerelease: bool


_TAG_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$")


def _parse_semver(value: str) -> tuple[int, int, int] | None:
    m = _TAG_RE.match(value.strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def is_newer_version(current: str, latest: str) -> bool:
    a = _parse_semver(current)
    b = _parse_semver(latest)
    if a is None or b is None:
        # Fallback: unknown formats → don't auto-claim update.
        return False
    return b > a


def fetch_latest_release(*, owner: str, repo: str, timeout_s: float = 8.0) -> UpdateInfo:
    url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
    resp = requests.get(url, timeout=timeout_s, headers={"Accept": "application/vnd.github+json"})
    resp.raise_for_status()
    data = resp.json()
    tag = str(data.get("tag_name") or "").strip()
    html_url = str(data.get("html_url") or "").strip()
    prerelease = bool(data.get("prerelease"))
    return UpdateInfo(latest_version=tag.lstrip("v"), release_url=html_url, is_prerelease=prerelease)

