from __future__ import annotations

import threading
import time

from app.download_queue import PackagingSlotQueue, TransferSlotQueue


def test_waiting_count_increments_while_blocked() -> None:
    queue = PackagingSlotQueue(max_slots=1)
    queue.acquire()
    started = threading.Event()
    done = threading.Event()

    def waiter() -> None:
        started.set()
        queue.acquire()
        done.set()
        queue.release()

    threading.Thread(target=waiter, daemon=True).start()
    assert started.wait(timeout=2.0)
    time.sleep(0.05)
    assert queue.waiting_count >= 1
    queue.release()
    assert done.wait(timeout=2.0)

def test_third_acquire_blocks_until_release() -> None:
    queue = PackagingSlotQueue(max_slots=2)
    queue.acquire()
    queue.acquire()

    acquired_third = threading.Event()

    def try_third() -> None:
        queue.acquire()
        acquired_third.set()
        queue.release()

    threading.Thread(target=try_third, daemon=True).start()
    time.sleep(0.1)
    assert not acquired_third.is_set()

    queue.release()
    assert acquired_third.wait(timeout=2.0)
    queue.release()


def test_transfer_slot_queue_limits_parallel_downloads() -> None:
    queue = TransferSlotQueue(max_slots=3)
    for _ in range(3):
        queue.acquire()

    acquired_fourth = threading.Event()

    def try_fourth() -> None:
        queue.acquire()
        acquired_fourth.set()
        queue.release()

    threading.Thread(target=try_fourth, daemon=True).start()
    time.sleep(0.1)
    assert not acquired_fourth.is_set()

    queue.release()
    assert acquired_fourth.wait(timeout=2.0)
    for _ in range(3):
        queue.release()
