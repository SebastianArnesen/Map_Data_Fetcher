from __future__ import annotations

import app.crash_handler as crash_handler


def test_report_uncaught_exception_deduplicates_repeated_errors(
    monkeypatch,
) -> None:
    writes: list[str] = []

    monkeypatch.setattr(crash_handler, "_write_crash_report", lambda text: writes.append(text) or crash_handler.crash_reports_dir() / "x.txt")
    monkeypatch.setattr(crash_handler, "_schedule_crash_ui", lambda *args, **kwargs: None)
    monkeypatch.setattr(crash_handler, "_resolve_light_mode", lambda: False)

    crash_handler._last_crash_fingerprint = None
    crash_handler._last_crash_report_time = 0.0
    crash_handler._suppressed_duplicate_count = 0
    crash_handler._handling_crash = False

    exc = OverflowError()

    assert crash_handler.report_uncaught_exception(OverflowError, exc, None, origin="sys.excepthook") is True
    assert crash_handler.report_uncaught_exception(OverflowError, exc, None, origin="sys.excepthook") is True
    assert crash_handler.report_uncaught_exception(OverflowError, exc, None, origin="sys.excepthook") is True

    assert len(writes) == 1
    assert crash_handler._suppressed_duplicate_count == 2


def test_report_uncaught_exception_reentrant_call_is_swallowed() -> None:
    crash_handler._handling_crash = True
    try:
        assert crash_handler.report_uncaught_exception(RuntimeError, RuntimeError("x"), None) is True
    finally:
        crash_handler._handling_crash = False
