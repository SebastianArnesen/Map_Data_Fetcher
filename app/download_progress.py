"""Progress dialog listing download tasks grouped by order."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, ClassVar

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.theme import SHARED, palette_for, qcolor

WARNING_AMBER = "#f0c040"
# Mouse-only selection avoids the blinking text caret on read-only labels.
_SELECTABLE = Qt.TextInteractionFlag.TextSelectableByMouse


def area_progress_display(area) -> str:
    """Short label for a download row (avoid ``code — name`` when they match)."""
    if area is None:
        return "Dataset"
    if area.name and area.name != area.code:
        return area.name
    return area.code or area.name or "?"


def format_order_subheader(*, area_count: int, projection: str, format_name: str) -> str:
    areas = f"{area_count} area" if area_count == 1 else f"{area_count} areas"
    return f"{areas}, {projection}, {format_name}"


@dataclass(frozen=True)
class DownloadProgressItem:
    display_text: str
    zip_filename: str


@dataclass(frozen=True)
class DownloadOrderInfo:
    job_id: int
    dataset_title: str
    subheader: str
    items: list[DownloadProgressItem]


def build_download_progress_stylesheet(*, light_mode: bool) -> str:
    c = palette_for(light_mode)
    return f"""
        QDialog#downloadProgressDialog {{
            background-color: {c.card_bg};
        }}
        QLabel#downloadProgressWindowHeading {{
            color: {c.window_fg};
            font-size: 11pt;
            font-weight: 700;
        }}
        QLabel#downloadProgressOrderTitle {{
            color: {c.window_fg};
            font-size: 10pt;
            font-weight: 700;
        }}
        QLabel#downloadProgressOrderSubheader {{
            color: {c.secondary_label_fg};
            font-size: 9pt;
        }}
        QLabel#downloadProgressItem {{
            color: {c.window_fg};
            font-size: 10pt;
        }}
        QLabel#downloadProgressPending {{
            color: {c.secondary_label_fg};
            font-size: 11pt;
            min-width: 22px;
            max-width: 22px;
        }}
        QLabel#downloadProgressCheck {{
            color: {SHARED.download};
            font-size: 11pt;
            font-weight: 700;
            min-width: 22px;
            max-width: 22px;
        }}
        QLabel#downloadProgressFailed {{
            color: {WARNING_AMBER};
            font-size: 11pt;
            font-weight: 700;
            min-width: 22px;
            max-width: 22px;
        }}
        QPushButton#downloadProgressCancelButton {{
            background: {c.button_bg};
            color: {c.button_fg};
            border: 1px solid {c.button_border};
            border-radius: 8px;
            padding: 6px 16px;
            min-width: 88px;
            font-weight: 600;
        }}
        QPushButton#downloadProgressCancelButton:hover {{
            background: {c.button_hover_bg};
            color: {c.button_hover_fg};
            border-color: {c.button_hover_border};
        }}
        QPushButton#downloadProgressCancelButton:pressed {{
            background: {c.button_pressed_bg};
            border-color: {c.button_pressed_border};
        }}
        QPushButton#downloadProgressCancelButton:disabled {{
            color: {c.secondary_label_fg};
            background: {c.button_bg};
        }}
        QPushButton#downloadProgressSectionCancel {{
            background: {c.button_bg};
            color: {c.button_fg};
            border: 1px solid {c.button_border};
            border-radius: 8px;
            padding: 4px 12px;
            min-width: 64px;
            font-size: 9pt;
            font-weight: 600;
        }}
        QPushButton#downloadProgressSectionCancel:hover {{
            background: {c.button_hover_bg};
            color: {c.button_hover_fg};
            border-color: {c.button_hover_border};
        }}
        QPushButton#downloadProgressSectionCancel:pressed {{
            background: {c.button_pressed_bg};
            border-color: {c.button_pressed_border};
        }}
        QPushButton#downloadProgressSectionCancel:disabled {{
            color: {c.secondary_label_fg};
            background: {c.button_bg};
        }}
        QScrollArea#downloadProgressScroll {{
            background: transparent;
            border: none;
        }}
        QScrollArea#downloadProgressScroll > QWidget > QWidget {{
            background: transparent;
        }}
        QScrollBar:vertical {{
            background: transparent;
            width: 8px;
            margin: 0px;
            border: none;
        }}
        QScrollBar::handle:vertical {{
            background: {c.scrollbar_handle};
            border-radius: 4px;
            min-height: 24px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: {c.scrollbar_handle_hover};
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0px;
            border: none;
            background: none;
        }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
            background: transparent;
        }}
        QWidget#downloadProgressList {{
            background: transparent;
        }}
        QFrame#downloadProgressOrderSeparator {{
            color: {c.button_border};
        }}
    """


class _QuarterSpinner(QWidget):
    """A small rotating quarter-ring arc with no track."""

    _FRAME_MS = 120
    _SEGMENT_SPAN = 84 * 16  # leave small gaps between quarter arcs
    _SEGMENT_GAP = 6 * 16
    _instances: ClassVar[set[_QuarterSpinner]] = set()
    _timer: ClassVar[QTimer | None] = None

    def __init__(self, parent: QWidget | None = None, *, light_mode: bool = False) -> None:
        super().__init__(parent)
        self.setObjectName("downloadProgressSpinner")
        self.setFixedSize(14, 14)
        self.setAutoFillBackground(False)
        self._light_mode = light_mode

    @classmethod
    def _segment(cls) -> int:
        tick = int(time.monotonic() * 1000 // cls._FRAME_MS)
        return (-tick) % 4

    @classmethod
    def _on_tick(cls) -> None:
        for spinner in list(cls._instances):
            spinner.update()

    @classmethod
    def _ensure_timer(cls) -> None:
        if cls._timer is None:
            cls._timer = QTimer()
            cls._timer.setInterval(cls._FRAME_MS)
            cls._timer.timeout.connect(cls._on_tick)
        if not cls._timer.isActive():
            cls._timer.start()

    def set_light_mode(self, light_mode: bool) -> None:
        self._light_mode = light_mode
        self.update()

    def start(self) -> None:
        type(self)._instances.add(self)
        type(self)._ensure_timer()
        self.update()

    def stop(self) -> None:
        type(self)._instances.discard(self)
        if not type(self)._instances and type(self)._timer is not None:
            type(self)._timer.stop()

    def is_spinning(self) -> bool:
        return self in type(self)._instances

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        del event
        base = qcolor(palette_for(self._light_mode).secondary_label_fg)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        pen_width = 2
        rect = self.rect().adjusted(pen_width, pen_width, -pen_width, -pen_width)
        color = QColor(base)
        pen = QPen(color, pen_width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        start = self._segment() * 90 * 16 + self._SEGMENT_GAP // 2
        painter.drawArc(rect, start, self._SEGMENT_SPAN)


class _ItemRow:
    __slots__ = ("mark_host", "mark", "label")

    def __init__(self, mark_host: QWidget, mark: QWidget, label: QLabel) -> None:
        self.mark_host = mark_host
        self.mark = mark
        self.label = label


class _OrderSection:
    def __init__(
        self,
        parent_layout: QVBoxLayout,
        info: DownloadOrderInfo,
        *,
        on_cancel: Callable[[int], None],
        light_mode: bool,
    ) -> None:
        self.job_id = info.job_id
        self._full_title = info.dataset_title
        self._rows: list[_ItemRow] = []
        self._cancelling = False
        self._finished = False
        self._light_mode = light_mode
        self.widgets: list[QWidget] = []

        def _track(widget: QWidget) -> QWidget:
            parent_layout.addWidget(widget)
            self.widgets.append(widget)
            return widget

        header_row = QWidget()
        header_layout = QHBoxLayout(header_row)
        header_layout.setContentsMargins(0, 8, 0, 0)
        header_layout.setSpacing(8)

        self._title = QLabel(info.dataset_title)
        self._title.setObjectName("downloadProgressOrderTitle")
        self._title.setToolTip(info.dataset_title)
        self._title.setTextInteractionFlags(_SELECTABLE)
        self._title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        header_layout.addWidget(self._title, 1)

        self._section_cancel = QPushButton("Cancel")
        self._section_cancel.setObjectName("downloadProgressSectionCancel")
        self._section_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self._section_cancel.clicked.connect(lambda: on_cancel(info.job_id))
        header_layout.addWidget(self._section_cancel)
        _track(header_row)

        self._subheader = QLabel(info.subheader)
        self._subheader.setObjectName("downloadProgressOrderSubheader")
        self._subheader.setTextInteractionFlags(_SELECTABLE)
        _track(self._subheader)

        for item in info.items:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)

            mark_host = QWidget()
            mark_host.setFixedWidth(22)
            mark_layout = QHBoxLayout(mark_host)
            mark_layout.setContentsMargins(0, 0, 0, 0)
            mark = QLabel("·")
            mark.setObjectName("downloadProgressPending")
            mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
            mark.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
            mark_layout.addWidget(mark)

            label = QLabel(item.display_text)
            label.setObjectName("downloadProgressItem")
            label.setToolTip(item.zip_filename)
            label.setWordWrap(True)
            label.setTextInteractionFlags(_SELECTABLE)
            label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

            row_layout.addWidget(mark_host)
            row_layout.addWidget(label, 1)
            _track(row)
            self._rows.append(_ItemRow(mark_host, mark, label))

    def set_cancelling(self, cancelling: bool) -> None:
        self._cancelling = cancelling
        if not self._finished:
            self._section_cancel.setEnabled(not cancelling)

    def mark_order_finished(self) -> None:
        self._finished = True
        self._section_cancel.hide()

    def is_finished(self) -> bool:
        return self._finished

    def update_title_elide(self, width: int) -> None:
        if width <= 0:
            return
        metrics = QFontMetrics(self._title.font())
        self._title.setText(metrics.elidedText(self._full_title, Qt.TextElideMode.ElideRight, width))

    def _replace_mark(self, row: _ItemRow, widget: QWidget) -> None:
        if isinstance(row.mark, _QuarterSpinner):
            row.mark.stop()
        layout = row.mark_host.layout()
        if layout is not None:
            layout.removeWidget(row.mark)
        row.mark.deleteLater()
        row.mark = widget
        if layout is not None:
            layout.addWidget(widget, 0, Qt.AlignmentFlag.AlignCenter)

    def mark_item_active(self, index: int) -> None:
        if index < 0 or index >= len(self._rows):
            return
        row = self._rows[index]
        if isinstance(row.mark, _QuarterSpinner) and row.mark.is_spinning():
            return
        spinner = _QuarterSpinner(row.mark_host, light_mode=self._light_mode)
        self._replace_mark(row, spinner)
        spinner.start()

    def apply_theme(self, *, light_mode: bool) -> None:
        self._light_mode = light_mode
        for row in self._rows:
            if isinstance(row.mark, _QuarterSpinner):
                row.mark.set_light_mode(light_mode)

    def mark_item_complete(self, index: int) -> None:
        if index < 0 or index >= len(self._rows):
            return
        row = self._rows[index]
        mark = QLabel("✓", row.mark_host)
        mark.setObjectName("downloadProgressCheck")
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self._replace_mark(row, mark)

    def mark_item_failed(self, index: int) -> None:
        if index < 0 or index >= len(self._rows):
            return
        row = self._rows[index]
        mark = QLabel("⚠", row.mark_host)
        mark.setObjectName("downloadProgressFailed")
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self._replace_mark(row, mark)

    def mark_all_complete(self) -> None:
        for index in range(len(self._rows)):
            self.mark_item_complete(index)


class DownloadProgressDialog(QDialog):
    cancel_requested = Signal(int)
    close_all_requested = Signal()

    def __init__(self, parent: QWidget | None, *, light_mode: bool = False) -> None:
        super().__init__(parent)
        self.setObjectName("downloadProgressDialog")
        self.setWindowTitle("Downloading")
        self.setModal(False)
        self.setMinimumWidth(480)
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowSystemMenuHint
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowMinimizeButtonHint
        )
        self._light_mode = light_mode
        self._allow_close = False
        self._complete_mode = False
        self._sections: dict[int, _OrderSection] = {}
        self.setStyleSheet(build_download_progress_stylesheet(light_mode=light_mode))

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 6, 14)
        root.setSpacing(10)

        self._heading = QLabel("Downloading…")
        self._heading.setObjectName("downloadProgressWindowHeading")
        self._heading.setTextInteractionFlags(_SELECTABLE)
        root.addWidget(self._heading)

        self._scroll = QScrollArea()
        self._scroll.setObjectName("downloadProgressScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setViewportMargins(0, 0, 0, 0)

        self._list_host = QWidget()
        self._list_host.setObjectName("downloadProgressList")
        self._list_layout = QVBoxLayout(self._list_host)
        self._list_layout.setContentsMargins(0, 0, 2, 0)
        self._list_layout.setSpacing(4)
        self._list_layout.addStretch(1)

        self._scroll.setWidget(self._list_host)
        self._scroll.setMinimumHeight(280)
        root.addWidget(self._scroll, 1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self._cancel_button = QPushButton("Cancel all")
        self._cancel_button.setObjectName("downloadProgressCancelButton")
        self._cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._cancel_button.clicked.connect(self._on_footer_button_clicked)
        button_row.addWidget(self._cancel_button)
        root.addLayout(button_row)

    def _pop_trailing_stretch(self) -> None:
        count = self._list_layout.count()
        if count <= 0:
            return
        item = self._list_layout.itemAt(count - 1)
        if item is not None and item.spacerItem() is not None:
            self._list_layout.takeAt(count - 1)

    def add_order(self, info: DownloadOrderInfo) -> None:
        self._complete_mode = False
        self._allow_close = False
        self._pop_trailing_stretch()
        section = _OrderSection(
            self._list_layout,
            info,
            on_cancel=self._on_section_cancel,
            light_mode=self._light_mode,
        )
        self._sections[info.job_id] = section
        self._list_layout.addStretch(1)
        self._refresh_heading()
        self._update_title_elides()

    def remove_order(self, job_id: int) -> None:
        section = self._sections.pop(job_id, None)
        if section is None:
            return
        for row in section._rows:
            if isinstance(row.mark, _QuarterSpinner):
                row.mark.stop()
        for widget in section.widgets:
            self._list_layout.removeWidget(widget)
            widget.deleteLater()
        self._refresh_heading()
        self._update_title_elides()

    def has_orders(self) -> bool:
        return bool(self._sections)

    def job_ids(self) -> list[int]:
        return list(self._sections.keys())

    def all_orders_finished(self) -> bool:
        return bool(self._sections) and all(section.is_finished() for section in self._sections.values())

    def mark_order_finished(self, job_id: int) -> None:
        section = self._sections.get(job_id)
        if section is not None:
            section.mark_order_finished()
        self._refresh_heading()

    def enter_complete_mode(self) -> None:
        if self._complete_mode:
            return
        self._complete_mode = True
        self.allow_close()
        self._refresh_heading()

    def _refresh_heading(self) -> None:
        if self._complete_mode:
            self._heading.setTextFormat(Qt.TextFormat.RichText)
            self._heading.setText(
                f'Download complete <span style="color:{SHARED.download};">✓</span>'
            )
            self._cancel_button.setVisible(True)
            self._cancel_button.setText("OK")
            return

        self._heading.setTextFormat(Qt.TextFormat.PlainText)
        active_sections = [section for section in self._sections.values() if not section.is_finished()]
        if not active_sections:
            return
        count = sum(len(section._rows) for section in active_sections)
        orders = len(active_sections)
        if orders <= 1:
            self._heading.setText(f"Downloading {count} item{'s' if count != 1 else ''}…")
        else:
            self._heading.setText(
                f"Downloading {count} item{'s' if count != 1 else ''} "
                f"in {orders} order{'s' if orders != 1 else ''}…"
            )
        self._cancel_button.setVisible(True)
        self._cancel_button.setText("Cancel all" if orders > 1 else "Cancel")

    def _on_footer_button_clicked(self) -> None:
        if self._complete_mode:
            self.close()
            return
        self._on_cancel_all_clicked()

    def _on_section_cancel(self, job_id: int) -> None:
        self.cancel_requested.emit(job_id)

    def _on_cancel_all_clicked(self) -> None:
        if len(self._sections) == 1:
            self.cancel_requested.emit(next(iter(self._sections)))
            return
        self.close_all_requested.emit()

    def set_order_cancelling(self, job_id: int, cancelling: bool) -> None:
        section = self._sections.get(job_id)
        if section is not None:
            section.set_cancelling(cancelling)

    def allow_close(self) -> None:
        self._allow_close = True

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._allow_close or self._complete_mode:
            super().closeEvent(event)
            return
        event.ignore()
        if self._sections:
            if len(self._sections) == 1:
                self.cancel_requested.emit(next(iter(self._sections)))
            else:
                self.close_all_requested.emit()

    def reject(self) -> None:  # noqa: N802
        if self._allow_close or self._complete_mode:
            super().reject()
            return
        if self._sections:
            if len(self._sections) == 1:
                self.cancel_requested.emit(next(iter(self._sections)))
            else:
                self.close_all_requested.emit()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._update_title_elides()

    def _update_title_elides(self) -> None:
        for section in self._sections.values():
            width = section._title.width()
            if width <= 0:
                width = self.width() - 120
            section.update_title_elide(width)

    def mark_item_active(self, job_id: int, index: int) -> None:
        section = self._sections.get(job_id)
        if section is not None:
            section.mark_item_active(index)

    def mark_item_complete(self, job_id: int, index: int) -> None:
        section = self._sections.get(job_id)
        if section is not None:
            section.mark_item_complete(index)

    def mark_item_failed(self, job_id: int, index: int) -> None:
        section = self._sections.get(job_id)
        if section is not None:
            section.mark_item_failed(index)

    def mark_all_complete(self, job_id: int) -> None:
        section = self._sections.get(job_id)
        if section is not None:
            section.mark_all_complete()

    def apply_theme(self, *, light_mode: bool) -> None:
        if self._light_mode == light_mode:
            return
        self._light_mode = light_mode
        self.setStyleSheet(build_download_progress_stylesheet(light_mode=light_mode))
        for section in self._sections.values():
            section.apply_theme(light_mode=light_mode)
