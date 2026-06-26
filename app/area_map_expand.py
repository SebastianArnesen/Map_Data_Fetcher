"""Expanded cell-map window and toolbar icon buttons."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QMainWindow, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from app.theme import palette_for, qcolor, resolve_light_mode


def _toolbar_icon_color(*, light_mode: bool, hover: bool, pressed: bool) -> QColor:
    palette = palette_for(light_mode)
    if pressed:
        return qcolor(palette.list_selected_fg)
    if hover:
        return qcolor(palette.header_button_hover_fg)
    return qcolor(palette.button_fg)


def _paint_zoom_minus(painter: QPainter, rect: QRectF, *, light_mode: bool, hover: bool, pressed: bool) -> None:
    color = _toolbar_icon_color(light_mode=light_mode, hover=hover, pressed=pressed)
    painter.setPen(QPen(color, 2.2, Qt.SolidLine, Qt.RoundCap))
    cx = rect.center().x()
    cy = rect.center().y()
    arm = 6.5
    painter.drawLine(QPointF(cx - arm, cy), QPointF(cx + arm, cy))


def _paint_zoom_plus(painter: QPainter, rect: QRectF, *, light_mode: bool, hover: bool, pressed: bool) -> None:
    color = _toolbar_icon_color(light_mode=light_mode, hover=hover, pressed=pressed)
    painter.setPen(QPen(color, 2.2, Qt.SolidLine, Qt.RoundCap))
    cx = rect.center().x()
    cy = rect.center().y()
    arm = 6.5
    painter.drawLine(QPointF(cx - arm, cy), QPointF(cx + arm, cy))
    painter.drawLine(QPointF(cx, cy - arm), QPointF(cx, cy + arm))


def _paint_expand_arrows(painter: QPainter, rect: QRectF, *, light_mode: bool, hover: bool, pressed: bool) -> None:
    color = _toolbar_icon_color(light_mode=light_mode, hover=hover, pressed=pressed)
    pen = QPen(color, 2.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    painter.setPen(pen)
    inset = 4.0
    x0 = rect.left() + inset
    y0 = rect.bottom() - inset
    x1 = rect.right() - inset
    y1 = rect.top() + inset
    painter.drawLine(QPointF(x0, y0), QPointF(x1, y1))
    head = 4.2
    painter.drawLine(QPointF(x1, y1), QPointF(x1 - head, y1))
    painter.drawLine(QPointF(x1, y1), QPointF(x1, y1 + head))
    painter.drawLine(QPointF(x0, y0), QPointF(x0 + head, y0))
    painter.drawLine(QPointF(x0, y0), QPointF(x0, y0 - head))


class MapToolbarIconButton(QPushButton):
    """Square map toolbar control with a custom-painted glyph."""

    def __init__(self, *, kind: str, tooltip: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("toolbarButton")
        self.setText("")
        self.setToolTip(tooltip)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(34, 34)
        self._kind = kind

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        light_mode = resolve_light_mode(self)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(4, 4, -4, -4)
        hover = self.underMouse()
        pressed = self.isDown()
        if self._kind == "zoom_out":
            _paint_zoom_minus(painter, rect, light_mode=light_mode, hover=hover, pressed=pressed)
        elif self._kind == "zoom_in":
            _paint_zoom_plus(painter, rect, light_mode=light_mode, hover=hover, pressed=pressed)
        else:
            _paint_expand_arrows(painter, rect, light_mode=light_mode, hover=hover, pressed=pressed)


class MapZoomOutButton(MapToolbarIconButton):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(kind="zoom_out", tooltip="Zoom out", parent=parent)


class MapZoomInButton(MapToolbarIconButton):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(kind="zoom_in", tooltip="Zoom in", parent=parent)


class MapExpandButton(MapToolbarIconButton):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(kind="expand", tooltip="Open map in a separate window", parent=parent)


class _MapZoomOverlay(QWidget):
    """Floating zoom controls over the expanded map."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("mapZoomOverlay")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        self.zoom_out = MapZoomOutButton(self)
        self.zoom_in = MapZoomInButton(self)
        layout.addWidget(self.zoom_out)
        layout.addWidget(self.zoom_in)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def reposition(self) -> None:
        self.adjustSize()
        self.move(0, 0)
        self.raise_()


class ExpandedAreaMapWindow(QMainWindow):
    """Separate window for the cell map picker."""

    closed_by_user = Signal()
    zoom_in = Signal()
    zoom_out = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("expandedAreaMapWindow")
        self._map_container = QWidget()
        self._map_container.setObjectName("expandedMapContainer")
        self.setCentralWidget(self._map_container)
        self._map_layout = QVBoxLayout(self._map_container)
        self._map_layout.setContentsMargins(0, 0, 0, 0)
        self._map_layout.setSpacing(0)
        self._overlay = _MapZoomOverlay(self._map_container)
        self._overlay.zoom_in.clicked.connect(self.zoom_in.emit)
        self._overlay.zoom_out.clicked.connect(self.zoom_out.emit)
        self._picker: QWidget | None = None

    def attach_map_picker(self, picker: QWidget) -> None:
        if self._picker is picker and picker.parent() is self._map_container:
            picker.show()
            self._overlay.reposition()
            return
        if self._picker is not None and self._picker is not picker:
            self._map_layout.removeWidget(self._picker)
        self._picker = picker
        picker.setParent(self._map_container)
        if self._map_layout.indexOf(picker) < 0:
            self._map_layout.addWidget(picker, 1)
        picker.show()
        self._overlay.reposition()

    def detach_map_picker(self) -> QWidget | None:
        picker = self._picker
        if picker is None:
            return None
        self._map_layout.removeWidget(picker)
        picker.setParent(None)
        picker.hide()
        self._picker = None
        return picker

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._overlay.reposition()

    def closeEvent(self, event) -> None:  # noqa: N802
        self.closed_by_user.emit()
        event.ignore()
        self.hide()


def expanded_map_window_geometry(screen) -> tuple[int, int, int, int]:
    """Return x, y, width, height slightly inset from the available screen area."""
    available = screen.availableGeometry()
    margin_w = max(48, int(available.width() * 0.06))
    margin_h = max(48, int(available.height() * 0.06))
    return (
        available.x() + margin_w // 2,
        available.y() + margin_h // 2,
        available.width() - margin_w,
        available.height() - margin_h,
    )
