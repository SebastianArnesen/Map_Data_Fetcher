"""Themed QMessageBox helpers matching the application palette."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPolygonF
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QMessageBox, QWidget

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
