from __future__ import annotations

import sys

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QMessageBox

from app.crash_handler import GeonorgeApplication, install_crash_handler
from app.instance_lock import acquire_single_instance_lock, attach_single_instance_lock
from app.logging_config import configure_logging
from app.main_window import MainWindow
from app.resources import apply_app_icon
from app.ssl_bundle import configure_ssl_bundle
from app.tooltip_delay import enable_widget_tooltips, install_delayed_tooltips


def main() -> int:
    configure_logging()
    configure_ssl_bundle()
    install_crash_handler()
    app = GeonorgeApplication(sys.argv)
    install_delayed_tooltips(app)
    lock = acquire_single_instance_lock()
    if lock is None:
        QMessageBox.information(
            None,
            "Geonorge Datasets is already running",
            "The app is already open. Please use the existing window.",
        )
        return 0
    attach_single_instance_lock(app, lock)

    # Small convenience: put a thread pool on the app instance.
    app.threadPool = lambda: QThreadPool.globalInstance()  # type: ignore[attr-defined]
    w = MainWindow()
    apply_app_icon(app, w)
    enable_widget_tooltips(w)
    w.showMaximized()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
