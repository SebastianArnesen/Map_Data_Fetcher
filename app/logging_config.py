from __future__ import annotations

import logging
import os
from pathlib import Path

from app.paths import app_data_dir


def log_dir() -> Path:
    path = app_data_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_file() -> Path:
    return log_dir() / "app.log"


def _console_log_level() -> int:
    raw = (os.environ.get("GEONORGE_LOG_CONSOLE") or "warning").strip().upper()
    return getattr(logging, raw, logging.WARNING)


def configure_logging() -> None:
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.DEBUG)

    file_handler = logging.FileHandler(log_file(), encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(_console_log_level())
    console_handler.setFormatter(formatter)

    root.addHandler(file_handler)
    root.addHandler(console_handler)

