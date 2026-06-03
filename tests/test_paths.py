from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app.paths import APP_DATA_DIR_NAME, app_data_dir, user_data_base_dir


def test_user_data_base_dir_windows(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    appdata = tmp_path / "AppData" / "Roaming"
    monkeypatch.setenv("APPDATA", str(appdata))
    assert user_data_base_dir() == appdata


def test_user_data_base_dir_darwin(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    assert user_data_base_dir() == tmp_path / "Library" / "Application Support"


def test_user_data_base_dir_linux_xdg(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    xdg = tmp_path / "xdg-data"
    monkeypatch.setenv("XDG_DATA_HOME", str(xdg))
    assert user_data_base_dir() == xdg


def test_user_data_base_dir_linux_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    assert user_data_base_dir() == tmp_path / ".local" / "share"


def test_app_data_dir_uses_named_subfolder(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    path = app_data_dir()
    assert path == tmp_path / "share" / APP_DATA_DIR_NAME
    assert path.is_dir()
