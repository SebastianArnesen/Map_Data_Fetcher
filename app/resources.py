"""Resolve bundled asset paths in development and PyInstaller one-file builds."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QWidget


def project_root() -> Path:
    """Repository root when running from source; extract dir when frozen."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parent.parent


def asset_path(filename: str) -> Path:
    return project_root() / "assets" / filename


def load_app_icon() -> QIcon:
    path = asset_path("appIcon.ico")
    if path.is_file():
        return QIcon(str(path))
    return QIcon()


def apply_app_icon(app: QApplication, window: QWidget | None = None) -> None:
    icon = load_app_icon()
    if icon.isNull():
        return
    app.setWindowIcon(icon)
    if window is not None:
        window.setWindowIcon(icon)
