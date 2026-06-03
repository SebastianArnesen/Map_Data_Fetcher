"""Single-instance lock helpers shared by run.py and crash restart."""

from __future__ import annotations

import os

from PySide6.QtCore import QLockFile, QTimer
from PySide6.QtWidgets import QApplication

from app.logging_config import log_dir
from app.windows_subprocess import gui_executable, hidden_popen_kwargs


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
        import subprocess
        import sys
        from pathlib import Path

        release_single_instance_lock()

        project_root = Path(__file__).resolve().parent.parent

        # When running from source, sys.executable is python and sys.argv[0] is the entry script.
        # When running as a frozen exe, sys.executable == sys.argv[0] (exe path).
        exe = Path(sys.executable)
        argv0 = Path(sys.argv[0]) if sys.argv else Path()
        if getattr(sys, "frozen", False) or (
            exe.suffix.casefold() == ".exe" and argv0.suffix.casefold() == ".exe"
        ):
            args = [sys.executable, *sys.argv[1:]]
        else:
            # Run as a module from the project root so `import app` resolves after restart.
            extra = sys.argv[1:]
            if extra and Path(extra[0]).name.casefold() == "run.py":
                extra = extra[1:]
            args = [gui_executable(), "-m", "app.run", *extra]

        subprocess.Popen(
            args,
            cwd=project_root,
            close_fds=os.name != "nt",
            **hidden_popen_kwargs(),
        )
        QApplication.quit()
        sys.exit(0)

    QTimer.singleShot(delay_ms, _restart)
