"""Themed QMessageBox helpers matching the application palette."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.theme import SHARED, palette_for


def build_message_box_stylesheet(*, light_mode: bool) -> str:
    c = palette_for(light_mode)
    s = SHARED
    return f"""
        QMessageBox {{
            background-color: {c.card_bg};
        }}
        QMessageBox QLabel {{
            color: {c.window_fg};
            background: transparent;
            font-size: 10pt;
        }}
        QMessageBox QPushButton {{
            background: {c.button_bg};
            color: {c.button_fg};
            border: 1px solid {c.button_border};
            border-radius: 8px;
            padding: 6px 16px;
            min-width: 88px;
            font-weight: 600;
        }}
        QMessageBox QPushButton:hover {{
            background: {c.button_hover_bg};
            color: {c.button_hover_fg};
            border-color: {c.button_hover_border};
        }}
        QMessageBox QPushButton:pressed {{
            background: {c.button_pressed_bg};
            border-color: {c.button_pressed_border};
        }}
        QMessageBox QPushButton:default {{
            border-color: {s.accent};
        }}
    """


def apply_message_box_theme(box: QMessageBox, *, light_mode: bool) -> None:
    box.setStyleSheet(build_message_box_stylesheet(light_mode=light_mode))


def _warning_icon_pixmap(size: int = 48) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    cx, cy = size / 2, size / 2
    triangle = [
        (cx, cy - 16),
        (cx + 15, cy + 12),
        (cx - 15, cy + 12),
    ]
    poly = QPolygonF([QPointF(x, y) for x, y in triangle])
    painter.setPen(QPen(QColor("#f0c040"), 1.4))
    painter.setBrush(QColor("#f0c040"))
    painter.drawPolygon(poly)
    painter.setPen(QPen(QColor("#1a1408"), 1.8))
    painter.drawLine(int(cx), int(cy - 4), int(cx), int(cy + 4))
    painter.drawPoint(int(cx), int(cy + 8))
    painter.end()
    return pixmap


def _success_icon_pixmap(size: int = 48) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    cx, cy = size / 2, size / 2
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(SHARED.download))
    painter.drawEllipse(QRectF(cx - 16, cy - 16, 32, 32))
    painter.setPen(QPen(QColor(SHARED.white), 2.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.drawLine(int(cx - 7), int(cy), int(cx - 1), int(cy + 7))
    painter.drawLine(int(cx - 1), int(cy + 7), int(cx + 9), int(cy - 6))
    painter.end()
    return pixmap


def _resolve_light_mode(parent: QWidget | None) -> bool:
    current = parent
    while current is not None:
        if hasattr(current, "_light_mode"):
            return bool(current._light_mode)
        current = current.parentWidget()
    return False


def themed_message_box(
    parent: QWidget | None,
    *,
    title: str,
    text: str,
    informative_text: str = "",
    icon: str = "none",
) -> QMessageBox:
    """icon: 'none' | 'warning' | 'success'"""
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    if informative_text:
        box.setInformativeText(informative_text)
    box.setIcon(QMessageBox.Icon.NoIcon)
    if icon == "warning":
        box.setIconPixmap(_warning_icon_pixmap())
    elif icon == "success":
        box.setIconPixmap(_success_icon_pixmap())
    apply_message_box_theme(box, light_mode=_resolve_light_mode(parent))
    return box


def build_scrollable_dialog_stylesheet(*, light_mode: bool) -> str:
    c = palette_for(light_mode)
    return f"""
        QDialog#scrollableMessageDialog {{
            background-color: {c.card_bg};
        }}
        QLabel#scrollableMessageHeading {{
            color: {c.window_fg};
            background: transparent;
            font-size: 11pt;
            font-weight: 700;
        }}
        QLabel#scrollableMessageSubtitle {{
            color: {c.secondary_label_fg};
            background: transparent;
            font-size: 9pt;
        }}
        QTextEdit#scrollableMessageBody {{
            background: {c.input_bg};
            color: {c.window_fg};
            border: 1px solid {c.input_border};
            border-radius: 8px;
            font-family: Consolas, monospace;
            font-size: 9pt;
            padding: 6px;
        }}
        QPushButton#scrollableMessageOk {{
            background: {c.button_bg};
            color: {c.button_fg};
            border: 1px solid {c.button_border};
            border-radius: 8px;
            padding: 6px 16px;
            min-width: 88px;
            font-weight: 600;
        }}
        QPushButton#scrollableMessageOk:hover {{
            background: {c.button_hover_bg};
            color: {c.button_hover_fg};
            border-color: {c.button_hover_border};
        }}
        QPushButton#scrollableMessageOk:pressed {{
            background: {c.button_pressed_bg};
            border-color: {c.button_pressed_border};
        }}
        QScrollArea#scrollableMessageScroll {{
            background: transparent;
            border: none;
        }}
    """


def themed_scrollable_message_dialog(
    parent: QWidget | None,
    *,
    title: str,
    heading: str,
    body: str,
    subtitle: str = "",
    icon: str = "none",
    max_body_height: int = 320,
) -> QDialog:
    """Dialog with a capped, scrollable body for long text (e.g. many download paths)."""
    light_mode = _resolve_light_mode(parent)
    dialog = QDialog(parent)
    dialog.setObjectName("scrollableMessageDialog")
    dialog.setWindowTitle(title)
    dialog.setModal(True)
    dialog.setMinimumWidth(520)
    dialog.setMaximumHeight(max_body_height + 180)
    dialog.setStyleSheet(build_scrollable_dialog_stylesheet(light_mode=light_mode))

    root = QVBoxLayout(dialog)
    root.setContentsMargins(16, 14, 16, 14)
    root.setSpacing(10)

    header = QHBoxLayout()
    header.setSpacing(12)
    if icon == "warning":
        icon_label = QLabel()
        icon_label.setPixmap(_warning_icon_pixmap(40))
        header.addWidget(icon_label)
    elif icon == "success":
        icon_label = QLabel()
        icon_label.setPixmap(_success_icon_pixmap(40))
        header.addWidget(icon_label)

    header_text = QVBoxLayout()
    header_text.setSpacing(4)
    heading_label = QLabel(heading)
    heading_label.setObjectName("scrollableMessageHeading")
    heading_label.setWordWrap(True)
    header_text.addWidget(heading_label)
    if subtitle:
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("scrollableMessageSubtitle")
        subtitle_label.setWordWrap(True)
        header_text.addWidget(subtitle_label)
    header.addLayout(header_text, 1)
    root.addLayout(header)

    scroll = QScrollArea()
    scroll.setObjectName("scrollableMessageScroll")
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setMaximumHeight(max_body_height)

    body_edit = QTextEdit()
    body_edit.setObjectName("scrollableMessageBody")
    body_edit.setReadOnly(True)
    body_edit.setPlainText(body)
    body_edit.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
    scroll.setWidget(body_edit)
    root.addWidget(scroll, 1)

    buttons = QHBoxLayout()
    buttons.addStretch(1)
    ok = QPushButton("OK")
    ok.setObjectName("scrollableMessageOk")
    ok.setDefault(True)
    ok.clicked.connect(dialog.accept)
    buttons.addWidget(ok)
    root.addLayout(buttons)

    return dialog
