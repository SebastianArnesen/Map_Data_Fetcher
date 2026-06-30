from __future__ import annotations

import requests

from geonorge.client import GeonorgeError, NetworkError, is_network_error


def test_is_network_error_recognizes_network_error_subclass() -> None:
    assert is_network_error(NetworkError("connection reset"))


def test_is_network_error_recognizes_requests_timeout() -> None:
    assert is_network_error(requests.Timeout("timed out"))


def test_is_network_error_recognizes_requests_connection_error() -> None:
    assert is_network_error(requests.ConnectionError("refused"))


def test_is_network_error_recognizes_geonorge_download_message() -> None:
    assert is_network_error(GeonorgeError("Download failed for https://example/a.zip"))


def test_is_network_error_rejects_unrelated_runtime_error() -> None:
    assert not is_network_error(RuntimeError("order rejected"))
