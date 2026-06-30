from __future__ import annotations

import sys

import pytest
from PySide6.QtCore import QCoreApplication

from app.workers import WorkerSignals

# > 32-bit signed int max (~2 GiB)
THREE_GIB = 3 * 1024**3


@pytest.fixture(scope="module")
def qt_app() -> QCoreApplication:
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication(sys.argv)
    return app


def test_progress_signal_accepts_multi_gigabyte_counts(qt_app: QCoreApplication) -> None:
    signals = WorkerSignals()
    received: list[tuple[int, int, str]] = []

    signals.progress.connect(lambda done, total, msg: received.append((done, total, msg)))
    signals.emit_progress(THREE_GIB, THREE_GIB, "3 GiB")

    assert received == [(THREE_GIB, THREE_GIB, "3 GiB")]
