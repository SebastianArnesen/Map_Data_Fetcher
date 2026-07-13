from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

import requests

from app.ssl_bundle import ca_bundle_path


class GeonorgeError(RuntimeError):
    pass


class NetworkError(GeonorgeError):
    """Connection or timeout failure talking to Geonorge."""


def is_network_error(exc: BaseException) -> bool:
    if isinstance(exc, NetworkError):
        return True
    if isinstance(exc, GeonorgeError):
        text = str(exc).casefold()
        markers = (
            "network error",
            "connection",
            "timed out",
            "timeout",
            "name resolution",
            "getaddrinfo",
            "download failed",
        )
        return any(marker in text for marker in markers)
    cause = getattr(exc, "__cause__", None)
    if cause is not None and cause is not exc:
        return is_network_error(cause)
    return isinstance(exc, (requests.Timeout, requests.ConnectionError))


@dataclass(frozen=True)
class HttpResult:
    status_code: int
    json: Any | None
    text: str


class HttpClient:
    def __init__(self, timeout_s: float = 30.0, user_agent: str = "Map Data Fetcher/1.0"):
        self._timeout = timeout_s
        self._user_agent = user_agent
        self._local = threading.local()

    def _session(self) -> requests.Session:
        session = getattr(self._local, "session", None)
        if session is None:
            session = requests.Session()
            session.headers.update({"User-Agent": self._user_agent})
            session.verify = ca_bundle_path()
            self._local.session = session
        return session

    def get_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        retries: int = 3,
        backoff_s: float = 1.0,
    ) -> HttpResult:
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            try:
                r = self._session().get(url, params=params, timeout=self._timeout)
                text = r.text or ""
                try:
                    data = r.json()
                except json.JSONDecodeError:
                    data = None
                return HttpResult(status_code=r.status_code, json=data, text=text)
            except (requests.Timeout, requests.ConnectionError) as e:
                last_exc = e
                if attempt >= retries:
                    break
                time.sleep(backoff_s * (2**attempt))
        raise NetworkError(f"Network error calling GET {url}: {last_exc}")

    def get_text(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        retries: int = 3,
        backoff_s: float = 1.0,
    ) -> HttpResult:
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            try:
                r = self._session().get(url, params=params, timeout=self._timeout)
                return HttpResult(status_code=r.status_code, json=None, text=r.text or "")
            except (requests.Timeout, requests.ConnectionError) as e:
                last_exc = e
                if attempt >= retries:
                    break
                time.sleep(backoff_s * (2**attempt))
        raise NetworkError(f"Network error calling GET {url}: {last_exc}")

    def post_json(
        self,
        url: str,
        payload: dict[str, Any],
        *,
        retries: int = 2,
        backoff_s: float = 1.0,
    ) -> HttpResult:
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            try:
                r = self._session().post(url, json=payload, timeout=self._timeout)
                text = r.text or ""
                try:
                    data = r.json()
                except json.JSONDecodeError:
                    data = None
                return HttpResult(status_code=r.status_code, json=data, text=text)
            except (requests.Timeout, requests.ConnectionError) as e:
                last_exc = e
                if attempt >= retries:
                    break
                time.sleep(backoff_s * (2**attempt))
        raise NetworkError(f"Network error calling POST {url}: {last_exc}")

    def content_length(self, url: str) -> int | None:
        try:
            r = self._session().head(url, allow_redirects=True, timeout=self._timeout)
            if r.status_code >= 400:
                return None
            raw = r.headers.get("Content-Length")
            return int(raw) if raw and raw.isdigit() else None
        except requests.RequestException:
            return None

    def download(
        self,
        url: str,
        target_path: str,
        *,
        chunk_size: int = 1024 * 256,
        retries: int = 3,
        backoff_s: float = 1.0,
        timeout_s: float = 120.0,
        progress: Callable[[int, int | None], None] | None = None,
        cancel: Callable[[], bool] | None = None,
    ) -> None:
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            try:
                with self._session().get(url, stream=True, timeout=timeout_s) as r:
                    r.raise_for_status()
                    raw_total = r.headers.get("Content-Length")
                    total = int(raw_total) if raw_total and raw_total.isdigit() else None
                    downloaded = 0
                    with open(target_path, "wb") as f:
                        for chunk in r.iter_content(chunk_size=chunk_size):
                            if cancel and cancel():
                                raise DownloadCancelledError("Download cancelled.")
                            if chunk:
                                f.write(chunk)
                                downloaded += len(chunk)
                                if progress:
                                    progress(downloaded, total)
                return
            except DownloadCancelledError:
                raise
            except (requests.Timeout, requests.ConnectionError) as e:
                last_exc = e
                if attempt >= retries:
                    break
                time.sleep(backoff_s * (2**attempt))
            except requests.HTTPError as e:
                last_exc = e
                if attempt >= retries:
                    break
                time.sleep(backoff_s * (2**attempt))
        if isinstance(last_exc, (requests.Timeout, requests.ConnectionError)):
            raise NetworkError(f"Download failed for {url}: {last_exc}")
        raise GeonorgeError(f"Download failed for {url}: {last_exc}")


class DownloadCancelledError(GeonorgeError):
    """Raised when a download is cancelled mid-transfer."""
