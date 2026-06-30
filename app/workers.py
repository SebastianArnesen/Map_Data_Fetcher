from __future__ import annotations

import logging
import traceback
from typing import Callable, Generic, TypeVar

from PySide6.QtCore import QObject, QRunnable, Qt, Signal, Slot

T = TypeVar("T")
logger = logging.getLogger(__name__)


class WorkerSignals(QObject, Generic[T]):
    result = Signal(object)
    item_completed = Signal(int)  # index of a finished step (e.g. per-area download)
    item_failed = Signal(int)  # index of a failed step (e.g. connection loss)
    item_active = Signal(int)  # index of a file currently transferring
    error = Signal(str)
    finished = Signal()
    # qint64: byte counts for downloads can exceed 32-bit signed int (~2 GiB).
    progress = Signal("qint64", "qint64", str)  # done, total, message

    def emit_progress(self, done: int, total: int, message: str) -> None:
        """Emit progress; safe for multi-gigabyte byte counts."""
        try:
            self.progress.emit(done, total, message)
        except OverflowError:
            # Belt-and-suspenders if an old 32-bit Signal is still loaded in memory.
            logger.warning("Progress byte count overflow; sending message-only update")
            self.progress.emit(0, 0, message)


def connect_worker_signals(
    worker: "FuncWorker",
    *,
    result: Callable[[object], None] | None = None,
    error: Callable[[str], None] | None = None,
    finished: Callable[[], None] | None = None,
    progress: Callable[[int, int, str], None] | None = None,
    item_completed: Callable[[int], None] | None = None,
    item_failed: Callable[[int], None] | None = None,
    item_active: Callable[[int], None] | None = None,
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
    if item_failed is not None:
        worker.signals.item_failed.connect(item_failed, queued)
    if item_active is not None:
        worker.signals.item_active.connect(item_active, queued)


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

