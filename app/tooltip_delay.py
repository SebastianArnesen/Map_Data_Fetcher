"""Application-wide tooltip delay using native QToolTip."""

from __future__ import annotations

import logging

from PySide6.QtCore import QEvent, QModelIndex, QObject, QPoint, Qt, QTimer
from PySide6.QtGui import QCursor, QHelpEvent
from PySide6.QtWidgets import QAbstractItemView, QApplication, QMenu, QToolTip, QWidget
from shiboken6 import isValid

logger = logging.getLogger(__name__)

DEFAULT_TOOLTIP_DELAY_MS = 1000
_installed_filter: DelayedToolTipFilter | None = None


def _item_view_for(widget: QWidget) -> QAbstractItemView | None:
    if isinstance(widget, QAbstractItemView):
        return widget
    parent = widget.parentWidget()
    if isinstance(parent, QAbstractItemView):
        return parent
    return None


def _widget_alive(widget: QWidget | None) -> bool:
    return widget is not None and isValid(widget)


def _inside_menu(widget: QWidget) -> bool:
    current: QWidget | None = widget
    while current is not None:
        if isinstance(current, QMenu):
            return True
        current = current.parentWidget()
    return False


def _viewport_local_point(widget: QWidget, *, help_event: QHelpEvent | None = None) -> QPoint | None:
    """Map a position to viewport coordinates for indexAt()."""
    view = _item_view_for(widget)
    if view is None or not _widget_alive(view):
        return None
    viewport = view.viewport()
    if help_event is not None:
        if viewport is not None and widget is viewport:
            return help_event.pos()
        return viewport.mapFromGlobal(help_event.globalPos()) if viewport is not None else help_event.pos()
    if viewport is not None:
        return viewport.mapFromGlobal(QCursor.pos())
    return widget.mapFromGlobal(QCursor.pos())


def cancel_pending_tooltips() -> None:
    """Hide any in-flight tooltip (e.g. before list rebuilds)."""
    if _installed_filter is not None:
        _installed_filter.cancel()


class DelayedToolTipFilter(QObject):
    """Delay native tooltips; block Qt's immediate show on QEvent.ToolTip."""

    def __init__(self, delay_ms: int = DEFAULT_TOOLTIP_DELAY_MS, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._delay_ms = max(0, int(delay_ms))
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._show_pending)
        self._text = ""
        self._anchor: QWidget | None = None
        self._global_pos = QPoint()
        self._model_index = QModelIndex()
        self._anchor_destroyed = False
        self._destroy_signal_connected = False

    def cancel(self) -> None:
        self._cancel()

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if not isinstance(obj, QWidget):
            return False

        # Native map canvas: hover repaints frequently; skip delayed tooltips here.
        if type(obj).__name__ in ("MapCanvas", "MapPickerWidget"):
            return False

        # QMenu + QAction tooltips and hover are handled by Qt when tooltips are visible.
        if isinstance(obj, QMenu) or _inside_menu(obj):
            return False

        et = event.type()
        if et == QEvent.Type.MouseButtonPress:
            self._cancel()

        if et in (QEvent.Type.HoverEnter, QEvent.Type.Enter, QEvent.Type.MouseMove, QEvent.Type.HoverMove):
            tip, anchor, index = self._tip_for_widget(obj)
            if tip and anchor is not None:
                if tip != self._text or anchor is not self._anchor or index != self._model_index:
                    self._schedule(anchor, tip, QCursor.pos(), index)
            elif self._anchor is not None and self._widgets_related(obj, self._anchor):
                QTimer.singleShot(0, self._check_cancelled)
            return False

        if et in (QEvent.Type.HoverLeave, QEvent.Type.Leave):
            if self._anchor is not None and self._widgets_related(obj, self._anchor):
                QTimer.singleShot(0, self._check_cancelled)
            return False

        if et != QEvent.Type.ToolTip:
            return False
        if not isinstance(event, QHelpEvent):
            return False
        tip, anchor, index = self._tip_for_widget(obj, help_event=event)
        if tip and anchor is not None:
            self._schedule(anchor, tip, event.globalPos(), index)
        else:
            self._cancel()
        return True

    @staticmethod
    def _widgets_related(a: QWidget, b: QWidget) -> bool:
        return a is b or b.isAncestorOf(a) or a.isAncestorOf(b)

    def _tip_for_widget(
        self,
        widget: QWidget,
        *,
        help_event: QHelpEvent | None = None,
    ) -> tuple[str, QWidget | None, QModelIndex]:
        view = _item_view_for(widget)
        if view is not None and _widget_alive(view):
            local = _viewport_local_point(widget, help_event=help_event)
            viewport = view.viewport() or view
            if local is not None and viewport.rect().contains(local):
                index = view.indexAt(local)
                if index.isValid():
                    tip = index.data(Qt.ItemDataRole.ToolTipRole) or ""
                    if tip:
                        anchor = view.viewport() or view
                        return str(tip), anchor, index

        current: QWidget | None = widget
        while current is not None and _widget_alive(current):
            tip = current.toolTip()
            if tip:
                return tip, current, QModelIndex()
            current = current.parentWidget()
        return "", None, QModelIndex()

    def _unlink_anchor_destroyed(self) -> None:
        if not self._destroy_signal_connected:
            return
        anchor = self._anchor
        self._destroy_signal_connected = False
        if anchor is not None and _widget_alive(anchor):
            try:
                anchor.destroyed.disconnect(self._on_anchor_destroyed)
            except (RuntimeError, TypeError):
                pass

    def _schedule(
        self,
        anchor: QWidget,
        text: str,
        global_pos: QPoint,
        index: QModelIndex,
    ) -> None:
        if not _widget_alive(anchor):
            self._cancel()
            return
        self._timer.stop()
        QToolTip.hideText()
        if self._anchor is not anchor:
            self._unlink_anchor_destroyed()
            self._anchor = anchor
            if _widget_alive(anchor):
                anchor.destroyed.connect(self._on_anchor_destroyed)
                self._destroy_signal_connected = True
        self._text = text
        self._global_pos = global_pos
        self._model_index = QModelIndex(index)
        self._anchor_destroyed = False
        self._timer.start(self._delay_ms)

    def _on_anchor_destroyed(self, *_args: object) -> None:
        self._destroy_signal_connected = False
        self._anchor_destroyed = True
        self._cancel()

    def _cancel(self) -> None:
        self._timer.stop()
        self._unlink_anchor_destroyed()
        self._anchor = None
        self._text = ""
        self._model_index = QModelIndex()
        self._anchor_destroyed = False
        QToolTip.hideText()

    def _resolve_model_index(self, view: QAbstractItemView) -> QModelIndex:
        if not self._model_index.isValid():
            return QModelIndex()
        model = view.model()
        if model is None:
            return QModelIndex()
        row = self._model_index.row()
        column = self._model_index.column()
        parent = self._model_index.parent()
        current = model.index(row, column, parent)
        return current if current.isValid() else QModelIndex()

    def _cursor_over_anchor(self) -> bool:
        anchor = self._anchor
        text = self._text
        if anchor is None or not text or self._anchor_destroyed or not _widget_alive(anchor):
            return False
        if not anchor.isVisible():
            return False

        view = _item_view_for(anchor)
        if view is not None and _widget_alive(view):
            local = _viewport_local_point(anchor)
            viewport = view.viewport() or view
            if local is None or not viewport.rect().contains(local):
                return False
            index = view.indexAt(local)
            if not index.isValid():
                return False
            current = index.data(Qt.ItemDataRole.ToolTipRole) or ""
            return str(current) == text

        local = anchor.mapFromGlobal(QCursor.pos())
        return anchor.rect().contains(local)

    def _check_cancelled(self) -> None:
        if not self._cursor_over_anchor():
            self._cancel()

    def _show_pending(self) -> None:
        if not self._text or self._anchor is None or self._anchor_destroyed:
            self._cancel()
            return
        if not _widget_alive(self._anchor):
            self._cancel()
            return
        if not self._cursor_over_anchor():
            self._cancel()
            return

        anchor = self._anchor
        pos = self._global_pos
        rect = None
        view = _item_view_for(anchor)
        if view is not None and _widget_alive(view):
            index = self._resolve_model_index(view)
            if index.isValid():
                try:
                    rect = view.visualRect(index)
                    pos = view.mapToGlobal(rect.center())
                except Exception:
                    logger.debug("visualRect failed for tooltip index", exc_info=True)
                    self._cancel()
                    return

        try:
            if rect is not None:
                QToolTip.showText(pos, self._text, anchor, rect)
            else:
                QToolTip.showText(pos, self._text, anchor)
        except (TypeError, RuntimeError):
            try:
                QToolTip.showText(pos, self._text)
            except Exception:
                logger.debug("QToolTip.showText failed", exc_info=True)
                self._cancel()


def enable_widget_tooltips(root: QWidget) -> None:
    """Help Qt emit tooltip events for all descendants."""
    root.setAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips, True)
    for widget in root.findChildren(QWidget):
        widget.setAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips, True)
        if hasattr(widget, "viewport"):
            viewport = widget.viewport()
            if viewport is not None:
                viewport.setAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips, True)
                viewport.setMouseTracking(True)
        if isinstance(widget, QAbstractItemView):
            widget.setMouseTracking(True)


def install_delayed_tooltips(app: QApplication, delay_ms: int = DEFAULT_TOOLTIP_DELAY_MS) -> DelayedToolTipFilter:
    global _installed_filter
    filt = DelayedToolTipFilter(delay_ms=delay_ms, parent=app)
    app.installEventFilter(filt)
    _installed_filter = filt
    return filt
