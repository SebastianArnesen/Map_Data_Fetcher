"""Uncaught exception handling, crash reports, and restart support."""

from __future__ import annotations

import datetime as dt
import faulthandler
import logging
import sys
import threading
import traceback
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QTimer, QtMsgType, qInstallMessageHandler
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from app.logging_config import log_dir
from app.theme import palette_for

logger = logging.getLogger(__name__)

_handling_crash = False
_crash_ui_scheduled = False
_installed = False
_faulthandler_file = None

PROJECT_CRASH_DIR = Path(__file__).resolve().parent.parent / "crash_reports"

# Set by queue_crash_report; consumed on the next event-loop tick.
_pending_crash_ui: dict[str, Any] | None = None


def crash_reports_dir() -> Path:
    path = log_dir() / "crash_reports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_crash_report(text: str) -> Path:
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"crash_{stamp}.txt"
    user_path = crash_reports_dir() / filename
    user_path.write_text(text, encoding="utf-8")
    latest_user = crash_reports_dir() / "latest.txt"
    latest_user.write_text(text, encoding="utf-8")

    try:
        PROJECT_CRASH_DIR.mkdir(parents=True, exist_ok=True)
        (PROJECT_CRASH_DIR / filename).write_text(text, encoding="utf-8")
        (PROJECT_CRASH_DIR / "latest.txt").write_text(text, encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not mirror crash report into project folder: %s", exc)
    return user_path


def _format_crash_report(exc_type, exc_value, exc_tb, *, origin: str = "uncaught") -> str:
    lines = [
        f"timestamp: {dt.datetime.now().isoformat(timespec='seconds')}",
        f"origin: {origin}",
        f"python: {sys.version}",
        f"executable: {sys.executable}",
        f"argv: {sys.argv!r}",
        "",
        "traceback:",
        "".join(traceback.format_exception(exc_type, exc_value, exc_tb)).rstrip(),
        "",
    ]
    return "\n".join(lines)


def _resolve_light_mode() -> bool:
    app = QApplication.instance()
    if app is None:
        return False
    win = app.activeWindow()
    if win is not None and hasattr(win, "_light_mode"):
        return bool(win._light_mode)
    return False


def _native_fatal_message(title: str, text: str) -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, text[:3000], title[:128], 0x10)
    except Exception:
        logger.exception("Native fatal message box failed")


class _CrashDialog(QDialog):
    def __init__(self, report_path: Path, summary: str, *, light_mode: bool = False) -> None:
        super().__init__(None)
        self.setWindowTitle("Application error")
        self.setModal(True)
        self.setMinimumSize(560, 420)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        c = palette_for(light_mode)
        self.setStyleSheet(
            f"""
            QDialog {{
                background: {c.card_bg};
            }}
            QLabel {{
                color: {c.window_fg};
                background: transparent;
            }}
            QTextEdit {{
                background: {c.input_bg};
                color: {c.window_fg};
                border: 1px solid {c.input_border};
                border-radius: 8px;
                font-family: Consolas, monospace;
                font-size: 9pt;
            }}
            QPushButton {{
                background: {c.button_bg};
                color: {c.button_fg};
                border: 1px solid {c.button_border};
                border-radius: 8px;
                padding: 6px 14px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background: {c.button_hover_bg};
            }}
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        intro = QLabel(
            "The application hit an unexpected error and needs to close.\n"
            "You can quit or try restarting.\n\n"
            f"A detailed report was saved to:\n{report_path}"
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        details = QTextEdit()
        details.setReadOnly(True)
        details.setPlainText(summary)
        layout.addWidget(details, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        quit_btn = QPushButton("Quit")
        restart_btn = QPushButton("Restart")
        quit_btn.clicked.connect(self.reject)
        restart_btn.clicked.connect(self.accept)
        buttons.addWidget(quit_btn)
        buttons.addWidget(restart_btn)
        layout.addLayout(buttons)

        self._restart = False

    def restart_requested(self) -> bool:
        return self._restart

    def accept(self) -> None:
        self._restart = True
        super().accept()


def _present_crash_dialog(report_path: Path, summary: str, *, light_mode: bool) -> bool:
    """Show crash UI; return True if the user chose restart."""
    summary = summary if len(summary) <= 12000 else summary[:12000] + "\n\n… (truncated)"
    try:
        dialog = _CrashDialog(report_path, summary, light_mode=light_mode)
        dialog.exec()
        return dialog.restart_requested()
    except Exception:
        logger.exception("Themed crash dialog failed; using fallback message box")
        try:
            box = QMessageBox(None)
            box.setIcon(QMessageBox.Icon.Critical)
            box.setWindowTitle("Application error")
            box.setText("The application hit an unexpected error and needs to close.")
            box.setInformativeText(f"Details were saved to:\n{report_path}")
            box.setDetailedText(summary)
            box.setStandardButtons(QMessageBox.StandardButton.Ok)
            box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
            box.exec()
        except Exception:
            logger.exception("Qt fallback message box failed")
            _native_fatal_message(
                "Geonorge Datasets — Error",
                f"The application crashed.\n\nDetails saved to:\n{report_path}\n\n{summary[:1500]}",
            )
    return False


def _flush_pending_crash_ui() -> None:
    global _crash_ui_scheduled, _pending_crash_ui
    _crash_ui_scheduled = False
    pending = _pending_crash_ui
    _pending_crash_ui = None
    if pending is None:
        return

    restart = _present_crash_dialog(
        pending["report_path"],
        pending["summary"],
        light_mode=pending["light_mode"],
    )
    if restart:
        restart_application()
    elif QApplication.instance() is not None:
        QApplication.quit()


def _schedule_crash_ui(report_path: Path, summary: str, *, light_mode: bool) -> None:
    global _crash_ui_scheduled, _pending_crash_ui
    _pending_crash_ui = {
        "report_path": report_path,
        "summary": summary,
        "light_mode": light_mode,
    }
    app = QApplication.instance()
    if app is None:
        _flush_pending_crash_ui()
        return
    if not _crash_ui_scheduled:
        _crash_ui_scheduled = True
        QTimer.singleShot(0, _flush_pending_crash_ui)


def report_uncaught_exception(
    exc_type,
    exc_value,
    exc_tb,
    *,
    origin: str = "uncaught",
) -> bool:
    """Log, persist, and show crash UI. Returns True if handled."""
    global _handling_crash
    if _handling_crash:
        return False
    if exc_type is KeyboardInterrupt:
        return False
    _handling_crash = True
    try:
        report = _format_crash_report(exc_type, exc_value, exc_tb, origin=origin)
        report_path = _write_crash_report(report)
        logger.critical("Unhandled exception (%s) saved to %s", origin, report_path)
        _schedule_crash_ui(report_path, report, light_mode=_resolve_light_mode())
        return True
    except Exception:
        logger.exception("Crash reporting failed")
        _native_fatal_message(
            "Geonorge Datasets — Error",
            "".join(traceback.format_exception(exc_type, exc_value, exc_tb))[:3000],
        )
        return False
    finally:
        _handling_crash = False


def restart_application() -> None:
    from app.instance_lock import schedule_restart

    logger.info("Restarting application")
    schedule_restart()


def _sys_excepthook(exc_type, exc_value, exc_tb) -> None:
    if report_uncaught_exception(exc_type, exc_value, exc_tb, origin="sys.excepthook"):
        return
    sys.__excepthook__(exc_type, exc_value, exc_tb)


def _threading_excepthook(args: threading.ExceptHookArgs) -> None:
    if args.exc_type is KeyboardInterrupt:
        return
    report_uncaught_exception(
        args.exc_type,
        args.exc_value,
        args.exc_traceback,
        origin="threading",
    )


def _unraisablehook(unraisable: sys.UnraisableHookArgs) -> None:
    exc_type = unraisable.exc_type
    exc_value = unraisable.exc_value
    exc_tb = unraisable.exc_traceback
    if exc_type is None:
        return
    report_uncaught_exception(exc_type, exc_value, exc_tb, origin="unraisable")


def _qt_message_handler(mode, context, message) -> None:  # noqa: ANN001
    if mode != QtMsgType.QtFatalMsg:
        return
    text = f"Qt fatal: {message}"
    logger.critical(text)
    try:
        path = crash_reports_dir() / "latest.txt"
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        path.write_text(f"{existing}\n\n{text}".strip(), encoding="utf-8")
    except OSError:
        pass
    _native_fatal_message("Geonorge Datasets — Fatal error", text)


class GeonorgeApplication(QApplication):
    """QApplication that catches exceptions raised while delivering events."""

    def notify(self, receiver, event) -> bool:  # noqa: N802
        try:
            return super().notify(receiver, event)
        except Exception:
            exc_info = sys.exc_info()
            if report_uncaught_exception(*exc_info, origin="qt.event"):
                return False
            raise


def install_crash_handler() -> None:
    global _installed, _faulthandler_file
    if _installed:
        return
    _installed = True
    sys.excepthook = _sys_excepthook
    threading.excepthook = _threading_excepthook
    sys.unraisablehook = _unraisablehook
    qInstallMessageHandler(_qt_message_handler)

    fatal_log = crash_reports_dir() / "fatal.log"
    try:
        _faulthandler_file = open(fatal_log, "a", encoding="utf-8")  # noqa: SIM115
        _faulthandler_file.write(f"\n--- session {dt.datetime.now().isoformat(timespec='seconds')} ---\n")
        _faulthandler_file.flush()
        faulthandler.enable(file=_faulthandler_file, all_threads=True)
    except OSError:
        faulthandler.enable(all_threads=True)

    def _fatal_hook(signum, frame) -> None:  # noqa: ANN001
        try:
            report = ["fatal signal crash", f"timestamp: {dt.datetime.now().isoformat(timespec='seconds')}"]
            report.append("".join(traceback.format_stack(frame)))
            text = "\n".join(report)
            _write_crash_report(text)
            _native_fatal_message(
                "Geonorge Datasets — Fatal error",
                "The application crashed unexpectedly.\n\n"
                f"Details were saved under:\n{crash_reports_dir()}",
            )
        finally:
            if _faulthandler_file is not None:
                try:
                    faulthandler.dump_traceback(file=_faulthandler_file, all_threads=True)
                except Exception:
                    pass

    try:
        faulthandler.register(_fatal_hook)
    except Exception:
        logger.debug("Could not register faulthandler hook", exc_info=True)

    logger.info("Crash handler installed (reports in %s)", crash_reports_dir())
