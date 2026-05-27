"""Stable TLS CA bundle paths for dev runs and PyInstaller one-file builds."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_ENV_KEYS = ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE")


def _path_from_frozen_bundle() -> Path | None:
    meipass = getattr(sys, "_MEIPASS", None)
    if not meipass:
        return None
    candidate = Path(meipass) / "certifi" / "cacert.pem"
    return candidate if candidate.is_file() else None


def _path_from_certifi() -> Path | None:
    try:
        import certifi
    except ImportError:
        return None
    candidate = Path(certifi.where())
    return candidate if candidate.is_file() else None


def _clear_stale_meipass_env() -> None:
    """Drop CA env vars that still point at a removed one-file extract directory."""
    for key in _ENV_KEYS:
        raw = os.environ.get(key)
        if not raw:
            continue
        path = Path(raw)
        if "_MEI" in raw and not path.is_file():
            logger.debug("Removing stale %s=%s", key, raw)
            os.environ.pop(key, None)


def configure_ssl_bundle() -> Path | None:
    """
    Ensure HTTPS clients can verify certificates.

    PyInstaller one-file restarts often inherit SSL_CERT_FILE from the parent
    process while the old _MEI* folder is already gone; clear those first, then
    point at the current bundle.
    """
    _clear_stale_meipass_env()
    bundle = _path_from_frozen_bundle() or _path_from_certifi()
    if bundle is None:
        logger.warning("No CA certificate bundle found; HTTPS may fail")
        return None
    bundle_str = str(bundle)
    os.environ["SSL_CERT_FILE"] = bundle_str
    os.environ["REQUESTS_CA_BUNDLE"] = bundle_str
    logger.debug("Using CA bundle: %s", bundle_str)
    return bundle


def ca_bundle_path() -> str | bool:
    """Path for requests ``verify=``; True lets requests pick its own default."""
    bundle = configure_ssl_bundle()
    return str(bundle) if bundle is not None else True
