"""Progress dialog listing download tasks and marking each as it completes."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.theme import SHARED, palette_for


def build_download_progress_stylesheet(*, light_mode: bool) -> str:
    c = palette_for(light_mode)
    return f"""
        QDialog#downloadProgressDialog {{
            background-color: {c.card_bg};
        }}
        QLabel#downloadProgressHeading {{
            color: {c.window_fg};
            font-size: 11pt;
            font-weight: 700;
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
        QScrollArea#downloadProgressScroll {{
            background: transparent;
            border: none;
        }}
        QWidget#downloadProgressList {{
            background: transparent;
        }}
    """


class DownloadProgressDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None,
        items: list[str],
        *,
        light_mode: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("downloadProgressDialog")
        self.setWindowTitle("Downloading")
        self.setModal(False)
        self.setMinimumWidth(440)
        self.setStyleSheet(build_download_progress_stylesheet(light_mode=light_mode))

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        heading = QLabel(f"Downloading {len(items)} item{'s' if len(items) != 1 else ''}…")
        heading.setObjectName("downloadProgressHeading")
        root.addWidget(heading)

        scroll = QScrollArea()
        scroll.setObjectName("downloadProgressScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.NoFrame)

        list_host = QWidget()
        list_host.setObjectName("downloadProgressList")
        list_layout = QVBoxLayout(list_host)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(6)

        self._marks: list[QLabel] = []
        for text in items:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)
            mark = QLabel("·")
            mark.setObjectName("downloadProgressPending")
            mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label = QLabel(text)
            label.setObjectName("downloadProgressItem")
            label.setWordWrap(True)
            label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            row_layout.addWidget(mark)
            row_layout.addWidget(label, 1)
            list_layout.addWidget(row)
            self._marks.append(mark)

        list_layout.addStretch(1)
        scroll.setWidget(list_host)
        scroll.setMinimumHeight(min(280, max(120, len(items) * 28)))
        root.addWidget(scroll, 1)

    def mark_item_complete(self, index: int) -> None:
        if index < 0 or index >= len(self._marks):
            return
        mark = self._marks[index]
        mark.setText("✓")
        mark.setObjectName("downloadProgressCheck")
        mark.style().unpolish(mark)
        mark.style().polish(mark)

    def mark_all_complete(self) -> None:
        for index in range(len(self._marks)):
            self.mark_item_complete(index)
