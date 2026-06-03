from __future__ import annotations

import traceback
import logging
from typing import Callable, Generic, TypeVar

from PySide6.QtCore import QObject, QRunnable, Qt, Signal, Slot

T = TypeVar("T")
logger = logging.getLogger(__name__)


class WorkerSignals(QObject, Generic[T]):
    result = Signal(object)
    item_completed = Signal(int)  # index of a finished step (e.g. per-area download)
    error = Signal(str)
    finished = Signal()
    progress = Signal(int, int, str)  # done, total, message


def connect_worker_signals(
    worker: "FuncWorker",
    *,
    result: Callable[[object], None] | None = None,
    error: Callable[[str], None] | None = None,
    finished: Callable[[], None] | None = None,
    progress: Callable[[int, int, str], None] | None = None,
    item_completed: Callable[[int], None] | None = None,
) -> None:
    """Connect worker signals with QueuedConnection (safe for GUI updates)."""
    queued = Qt.ConnectionType.QueuedConnection
    if result is not None:
        worker.signals.result.connect(result, queued)
    if error is not None:
        worker.signals.error.connect(error, queued)
    if finished is not None:
        worker.signals.finished.connect(finished, queued)
    if progress is not None:
        worker.signals.progress.connect(progress, queued)
    if item_completed is not None:
        worker.signals.item_completed.connect(item_completed, queued)


class FuncWorker(QRunnable):
    def __init__(self, fn: Callable[[], T]) -> None:
        super().__init__()
        self.fn = fn
        self.signals: WorkerSignals[T] = WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            res = self.fn()
            self.signals.result.emit(res)
        except Exception:
            tb = traceback.format_exc()
            logger.error("Background worker failed: %s", tb)
            self.signals.error.emit(tb)
        finally:
            self.signals.finished.emit()

