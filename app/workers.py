from __future__ import annotations

import traceback
import logging
from typing import Callable, Generic, TypeVar

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

T = TypeVar("T")
logger = logging.getLogger(__name__)


class WorkerSignals(QObject, Generic[T]):
    result = Signal(object)
    item_completed = Signal(int)  # index of a finished step (e.g. per-area download)
    error = Signal(str)
    finished = Signal()
    progress = Signal(int, int, str)  # done, total, message


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

