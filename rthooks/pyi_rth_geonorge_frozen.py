"""Runtime paths for PyInstaller bundles (Qt plugins, PROJ data, SSL certs)."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _bundle_root() -> Path | None:
    if not getattr(sys, "frozen", False):
        return None
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(sys.executable).resolve().parent


def _set_proj_data(root: Path) -> None:
    candidates = (
        root / "pyproj" / "proj_dir" / "share" / "proj",
        root / "share" / "proj",
        root / "proj",
    )
    for path in candidates:
        if (path / "proj.db").is_file():
            os.environ.setdefault("PROJ_DATA", str(path))
            os.environ.setdefault("PROJ_LIB", str(path))
            return


def _set_qt_plugins(root: Path) -> None:
    if sys.platform != "darwin":
        return
    for rel in (
        Path("PySide6") / "Qt" / "plugins",
        Path("PySide6") / "plugins",
        Path("Qt") / "plugins",
    ):
        plugins = root / rel
        if plugins.is_dir():
            os.environ.setdefault("QT_PLUGIN_PATH", str(plugins))
            platforms = plugins / "platforms"
            if platforms.is_dir():
                os.environ.setdefault("QT_QPA_PLATFORM_PLUGIN_PATH", str(platforms))
            return


def _apply() -> None:
    root = _bundle_root()
    if root is None:
        return
    _set_proj_data(root)
    _set_qt_plugins(root)


_apply()
