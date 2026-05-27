"""Per-user data directory (AppData) for logs, cache, locks, and crash reports."""

from __future__ import annotations

import logging
import os
from pathlib import Path

APP_DATA_DIR_NAME = "GeonorgeDatasets"
LEGACY_APP_DATA_DIR_NAME = "GeonorgeDesktopDownloader"

logger = logging.getLogger(__name__)


def app_data_dir() -> Path:
    """
    Return the folder for logs, SQLite index, locks, and crash reports.

    Migrates the old ``GeonorgeDesktopDownloader`` folder on first run when the
    new name does not exist yet.
    """
    base = Path(os.environ.get("APPDATA") or Path.home())
    new_path = base / APP_DATA_DIR_NAME
    legacy_path = base / LEGACY_APP_DATA_DIR_NAME

    if new_path.exists():
        return new_path

    if legacy_path.exists():
        try:
            legacy_path.rename(new_path)
            logger.info("Migrated app data folder to %s", new_path)
            return new_path
        except OSError as exc:
            logger.warning(
                "Could not rename %s to %s (%s); using legacy folder",
                legacy_path,
                new_path,
                exc,
            )
            return legacy_path

    new_path.mkdir(parents=True, exist_ok=True)
    return new_path
