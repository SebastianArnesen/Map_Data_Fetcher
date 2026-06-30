"""Limits concurrent Geonorge server-side packaging orders and file transfers."""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator

from geonorge.constants import MAX_PARALLEL_DOWNLOADS, MAX_SERVER_ORDERS


class PackagingSlotQueue:
    """Thread-safe queue: at most ``max_slots`` Geonorge orders packaging at once."""

    def __init__(self, max_slots: int = MAX_SERVER_ORDERS) -> None:
        self._max_slots = max(1, max_slots)
        self._semaphore = threading.Semaphore(self._max_slots)
        self._lock = threading.Lock()
        self._waiting = 0
        self._active = 0

    @property
    def waiting_count(self) -> int:
        with self._lock:
            return self._waiting

    @property
    def active_count(self) -> int:
        with self._lock:
            return self._active

    def acquire(self) -> None:
        with self._lock:
            self._waiting += 1
        self._semaphore.acquire()
        with self._lock:
            self._waiting -= 1
            self._active += 1

    def release(self) -> None:
        with self._lock:
            if self._active > 0:
                self._active -= 1
        self._semaphore.release()

    @contextmanager
    def slot(self) -> Iterator[None]:
        self.acquire()
        try:
            yield
        finally:
            self.release()


class TransferSlotQueue(PackagingSlotQueue):
    """Thread-safe queue: at most ``max_slots`` file transfers across all jobs."""

    def __init__(self, max_slots: int = MAX_PARALLEL_DOWNLOADS) -> None:
        super().__init__(max_slots=max_slots)
