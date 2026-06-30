from __future__ import annotations

import pytest
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication, QPushButton

from app.download_progress import (
    DownloadOrderInfo,
    DownloadProgressDialog,
    DownloadProgressItem,
    _QuarterSpinner,
    area_progress_display,
    build_download_progress_stylesheet,
    format_order_subheader,
)
from app.theme import SHARED
from geonorge.models import AreaOption


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _sample_order(job_id: int = 1) -> DownloadOrderInfo:
    return DownloadOrderInfo(
        job_id=job_id,
        dataset_title="Sentinel-2 Skyfritt Norge 2025",
        subheader=format_order_subheader(area_count=2, projection="25832", format_name="TIFF"),
        items=[
            DownloadProgressItem("T32VKK", "Sentinel2_celle_T32VKK_TIFF_25832.zip"),
            DownloadProgressItem("T32VKL", "Sentinel2_celle_T32VKL_TIFF_25832.zip"),
        ],
    )


def test_mark_order_finished_hides_section_cancel(qapp) -> None:
    dialog = DownloadProgressDialog(None, light_mode=True)
    dialog.add_order(_sample_order(job_id=3))
    section = dialog._sections[3]
    assert not section.is_finished()
    dialog.mark_order_finished(3)
    assert section.is_finished()
    dialog.show()
    qapp.processEvents()
    assert not section._section_cancel.isVisible()


def test_enter_complete_mode_shows_ok(qapp) -> None:
    dialog = DownloadProgressDialog(None, light_mode=True)
    dialog.add_order(_sample_order(job_id=4))
    dialog.mark_order_finished(4)
    dialog.enter_complete_mode()
    assert "Download complete" in dialog._heading.text()
    assert "✓" in dialog._heading.text()
    assert SHARED.download in dialog._heading.text()
    assert dialog.findChild(QPushButton, "downloadProgressCancelButton").text() == "OK"


def test_download_progress_has_cancel_button(qapp) -> None:
    dialog = DownloadProgressDialog(None, light_mode=True)
    dialog.add_order(_sample_order())
    cancel = dialog.findChild(QPushButton, "downloadProgressCancelButton")
    assert cancel is not None


def test_area_progress_display_avoids_duplicate_code_and_name() -> None:
    area = AreaOption(type="celle", code="T32VKK", name="T32VKK")
    assert area_progress_display(area) == "T32VKK"
    named = AreaOption(type="celle", code="0301", name="Oslo")
    assert area_progress_display(named) == "Oslo"


def test_mark_item_active_uses_spinner(qapp) -> None:
    dialog = DownloadProgressDialog(None, light_mode=True)
    dialog.add_order(_sample_order())
    dialog.mark_item_active(1, 0)
    section = dialog._sections[1]
    assert isinstance(section._rows[0].mark, _QuarterSpinner)


def test_mark_item_failed_uses_warning_style(qapp) -> None:
    dialog = DownloadProgressDialog(None, light_mode=True)
    dialog.add_order(_sample_order())
    dialog.mark_item_failed(1, 0)
    section = dialog._sections[1]
    assert section._rows[0].mark.text() == "⚠"
    assert section._rows[0].mark.objectName() == "downloadProgressFailed"


def test_item_label_tooltip_is_zip_filename(qapp) -> None:
    dialog = DownloadProgressDialog(None, light_mode=True)
    dialog.add_order(_sample_order())
    section = dialog._sections[1]
    assert section._rows[0].label.toolTip() == "Sentinel2_celle_T32VKK_TIFF_25832.zip"


def test_close_event_emits_cancel_requested_for_single_order(qapp) -> None:
    dialog = DownloadProgressDialog(None, light_mode=True)
    dialog.add_order(_sample_order(job_id=7))
    received: list[int] = []
    dialog.cancel_requested.connect(received.append)

    event = QCloseEvent()
    dialog.closeEvent(event)
    assert received == [7]
    assert not event.isAccepted()


def test_stylesheet_includes_failed_and_cancel_rules() -> None:
    stylesheet = build_download_progress_stylesheet(light_mode=True)
    assert "downloadProgressFailed" in stylesheet
    assert "downloadProgressCancelButton" in stylesheet
    assert "downloadProgressSectionCancel" in stylesheet
    assert "#f0c040" in stylesheet


def test_apply_theme_updates_light_mode(qapp) -> None:
    dialog = DownloadProgressDialog(None, light_mode=False)
    dialog.add_order(_sample_order())
    dialog.mark_item_active(1, 0)
    dialog.apply_theme(light_mode=True)
    assert dialog._light_mode is True
    spinner = dialog._sections[1]._rows[0].mark
    assert isinstance(spinner, _QuarterSpinner)
    assert spinner._light_mode is True
