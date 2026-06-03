"""Per-user data directory for logs, cache, locks, and crash reports."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

APP_DATA_DIR_NAME = "GeonorgeDatasets"
LEGACY_APP_DATA_DIR_NAME = "GeonorgeDesktopDownloader"

logger = logging.getLogger(__name__)


def user_data_base_dir() -> Path:
    """
    Parent directory for app-specific data (OS convention).

    - Windows: ``%APPDATA%``
    - macOS: ``~/Library/Application Support``
    - Linux: ``$XDG_DATA_HOME`` or ``~/.local/share``
    """
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA") or Path.home())
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support"
    xdg = os.environ.get("XDG_DATA_HOME", "").strip()
    if xdg:
        return Path(xdg)
    return Path.home() / ".local" / "share"


def _migrate_folder(source: Path, target: Path) -> Path | None:
    if not source.exists() or source == target:
        return None
    if target.exists():
        return target
    try:
        source.rename(target)
        logger.info("Migrated app data folder from %s to %s", source, target)
        return target
    except OSError as exc:
        logger.warning(
            "Could not rename %s to %s (%s); using source folder",
            source,
            target,
            exc,
        )
        return source


def app_data_dir() -> Path:
    """
    Return the folder for logs, SQLite index, locks, and crash reports.

    Migrates legacy ``GeonorgeDesktopDownloader`` (and on macOS/Linux, old
    flat ``~/GeonorgeDatasets`` installs) on first run when the new path does
    not exist yet.
    """
    base = user_data_base_dir()
    new_path = base / APP_DATA_DIR_NAME
    legacy_path = base / LEGACY_APP_DATA_DIR_NAME

    if new_path.exists():
        return new_path

    migrated = _migrate_folder(legacy_path, new_path)
    if migrated is not None:
        return migrated

    if sys.platform != "win32":
        for flat in (Path.home() / APP_DATA_DIR_NAME, Path.home() / LEGACY_APP_DATA_DIR_NAME):
            migrated = _migrate_folder(flat, new_path)
            if migrated is not None:
                return migrated

    new_path.mkdir(parents=True, exist_ok=True)
    return new_path
