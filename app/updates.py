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


def build_latest_release_api_url(*, owner: str, repo: str) -> str:
    return f"https://api.github.com/repos/{owner}/{repo}/releases/latest"


def build_latest_release_web_url(*, owner: str, repo: str) -> str:
    return f"https://github.com/{owner}/{repo}/releases/latest"


def fetch_latest_release(
    *,
    owner: str,
    repo: str,
    token: str | None = None,
    timeout_s: float = 8.0,
) -> UpdateInfo:
    url = build_latest_release_api_url(owner=owner, repo=repo)
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    resp = requests.get(url, timeout=timeout_s, headers=headers)
    resp.raise_for_status()
    data = resp.json()
    tag = str(data.get("tag_name") or "").strip()
    html_url = str(data.get("html_url") or "").strip()
    prerelease = bool(data.get("prerelease"))
    return UpdateInfo(latest_version=tag.lstrip("v"), release_url=html_url, is_prerelease=prerelease)

