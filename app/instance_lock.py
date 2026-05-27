"""Single-instance lock helpers shared by run.py and crash restart."""

from __future__ import annotations

from PySide6.QtCore import QLockFile, QTimer
from PySide6.QtWidgets import QApplication

from app.logging_config import log_dir


def acquire_single_instance_lock() -> QLockFile | None:
    lock = QLockFile(str(log_dir() / "app.lock"))
    lock.setStaleLockTime(0)
    if lock.tryLock(100):
        return lock
    lock.removeStaleLockFile()
    if lock.tryLock(100):
        return lock
    return None


def release_single_instance_lock() -> None:
    app = QApplication.instance()
    if app is None:
        return
    lock = getattr(app, "_single_instance_lock", None)
    if isinstance(lock, QLockFile) and lock.isLocked():
        lock.unlock()
    setattr(app, "_single_instance_lock", None)


def attach_single_instance_lock(app: QApplication, lock: QLockFile) -> None:
    app.aboutToQuit.connect(lock.unlock)
    app._single_instance_lock = lock  # type: ignore[attr-defined]


def schedule_restart(delay_ms: int = 400) -> None:
    """Quit and spawn a fresh process after releasing the instance lock."""

    def _restart() -> None:
        import os
        import subprocess
        import sys

        release_single_instance_lock()
        args = [sys.executable, *sys.argv[1:]]
        subprocess.Popen(args, close_fds=True)
        QApplication.quit()
        sys.exit(0)

    QTimer.singleShot(delay_ms, _restart)
