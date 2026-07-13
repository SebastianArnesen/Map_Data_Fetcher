from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from PySide6.QtCore import QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QKeySequence,
    QPainter,
    QPen,
    QStandardItem,
    QStandardItemModel,
)
from PySide6.QtWidgets import (
    QApplication,
    QListView,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTreeView,
    QWidget,
)

from geonorge.models import DatasetAvailability
from app.filter_index import format_filter_key
from app.theme import (
    DARK,
    LIGHT,
    checkbox_auto_fill_border,
    checkbox_auto_tick_color,
    checkbox_disabled_fill_border,
    checkbox_fill_border,
    checkbox_tick_color,
    copy_hover_background,
    copy_icon_color,
    dataset_row_background,
    dataset_text_color,
    disabled_list_item_color,
    font_points,
    list_selection_border_color,
    qcolor,
    resolve_light_mode,
)

DATASET_COL_TITLE = 0
DATASET_COL_COPY = 1
DATASET_COL_TAGS = 2
DATASET_COL_LINK = 3


def dataset_shows_padlock(ds: DatasetAvailability) -> bool:
    return bool(ds.login_required or ds.access_is_restricted or ds.access_is_protected)


def dataset_padlock_tooltip(ds: DatasetAvailability) -> str | None:
    if not dataset_shows_padlock(ds):
        return None
    if ds.data_access:
        return ds.data_access
    if ds.login_required:
        return "Krever innlogging"
    return "Tilgangsbegrenset"


@dataclass(frozen=True)
class CheckListItem:
    key: str
    label: str
    payload: Any
    code: str = ""
    name: str = ""


def _check_state_value(state: object) -> int:
    if hasattr(state, "value"):
        return int(state.value)  # type: ignore[arg-type]
    if state is None:
        return int(Qt.Unchecked.value)
    return int(state)  # type: ignore[arg-type]


class TriStateAllModel(QStandardItemModel):
    """
    First row is the special 'All' item. Remaining rows are checkable items.

    Rules:
    - Checking All selects all.
    - When some but not all children are checked => All is PartiallyChecked.
    - Clicking All while PartiallyChecked clears All + clears children.
    """

    selection_changed = Signal()

    def __init__(self, all_label: str = "All"):
        super().__init__()
        self._all_label = all_label
        self._suppress = False
        self._has_all = True
        self._all_item: QStandardItem | None = None
        self._ensure_all_row()
        self.itemChanged.connect(self._on_item_changed)

    def _ensure_all_row(self) -> None:
        if not self._has_all:
            self._all_item = None
            return
        self._all_item = QStandardItem(self._all_label)
        self._all_item.setCheckable(True)
        self._all_item.setAutoTristate(True)
        self._all_item.setCheckState(Qt.Unchecked)
        self.appendRow(self._all_item)

    def set_items(self, items: Iterable[CheckListItem]) -> None:
        items = list(items)
        self._suppress = True
        try:
            self.clear()
            self._has_all = len(items) > 1
            self._ensure_all_row()

            for it in items:
                item = QStandardItem(it.label)
                item.setData(it.key, Qt.UserRole + 1)
                item.setData(it.payload, Qt.UserRole + 2)
                item.setCheckable(True)
                item.setCheckState(Qt.Unchecked)
                self.appendRow(item)
        finally:
            self._suppress = False
        self.selection_changed.emit()

    def checked_payloads(self) -> list[Any]:
        out: list[Any] = []
        start = 1 if self._has_all else 0
        for row in range(start, self.rowCount()):
            item = self.item(row)
            if item and item.checkState() == Qt.Checked:
                out.append(item.data(Qt.UserRole + 2))
        return out

    def checked_keys(self) -> set[str]:
        out: set[str] = set()
        start = 1 if self._has_all else 0
        for row in range(start, self.rowCount()):
            item = self.item(row)
            if item and item.checkState() == Qt.Checked:
                key = item.data(Qt.UserRole + 1)
                if isinstance(key, str):
                    out.add(key)
        return out

    def set_checked_keys(self, keys: set[str]) -> None:
        self._suppress = True
        try:
            start = 1 if self._has_all else 0
            for row in range(start, self.rowCount()):
                item = self.item(row)
                if not item:
                    continue
                key = item.data(Qt.UserRole + 1)
                item.setCheckState(Qt.Checked if key in keys else Qt.Unchecked)
            if self._has_all:
                self._update_all_from_children()
        finally:
            self._suppress = False
        self.selection_changed.emit()

    def auto_select_if_single_option(self) -> None:
        if self.rowCount() == 1:
            return
        if (self._has_all and self.rowCount() == 2) or (not self._has_all and self.rowCount() == 1):
            self._suppress = True
            try:
                idx = 1 if self._has_all else 0
                self.item(idx).setCheckState(Qt.Checked)  # type: ignore[union-attr]
                if self._has_all:
                    self._update_all_from_children()
            finally:
                self._suppress = False
            self.selection_changed.emit()

    def _on_item_changed(self, item: QStandardItem) -> None:
        if self._suppress:
            return

        if self._has_all and self._all_item is not None and item is self._all_item:
            if item.checkState() == Qt.PartiallyChecked:
                # User clicked it while partial: clear everything.
                self._set_all_children(Qt.Unchecked)
                self._all_item.setCheckState(Qt.Unchecked)
            elif item.checkState() == Qt.Checked:
                self._set_all_children(Qt.Checked)
                self._all_item.setCheckState(Qt.Checked)
            else:
                self._set_all_children(Qt.Unchecked)
                self._all_item.setCheckState(Qt.Unchecked)
            self.selection_changed.emit()
            return

        # Child changed; recompute All.
        if self._has_all:
            self._update_all_from_children()
        self.selection_changed.emit()

    def _set_all_children(self, state: Qt.CheckState) -> None:
        self._suppress = True
        try:
            for row in range(1, self.rowCount()):
                child = self.item(row)
                if child:
                    child.setCheckState(state)
        finally:
            self._suppress = False

    def _update_all_from_children(self) -> None:
        checked = 0
        total = max(0, self.rowCount() - 1)
        for row in range(1, self.rowCount()):
            child = self.item(row)
            if child and child.checkState() == Qt.Checked:
                checked += 1
        self._suppress = True
        try:
            if self._all_item is None:
                return
            if total == 0 or checked == 0:
                self._all_item.setCheckState(Qt.Unchecked)
            elif checked == total:
                self._all_item.setCheckState(Qt.Checked)
            else:
                self._all_item.setCheckState(Qt.PartiallyChecked)
        finally:
            self._suppress = False


class AreaSelectionModel(QStandardItemModel):
    selection_changed = Signal()

    def __init__(self, all_label: str = "All"):
        super().__init__()
        self._all_label = all_label
        self._suppress = False
        self._disabled_keys: set[str] = set()
        self.setHorizontalHeaderLabels(["", "Code", "Name"])
        self.itemChanged.connect(self._on_item_changed)

    def disabled_keys(self) -> set[str]:
        return set(self._disabled_keys)

    def is_row_disabled(self, row: int) -> bool:
        item = self.item(row, 0)
        if not item:
            return False
        key = item.data(Qt.UserRole + 1)
        return isinstance(key, str) and key in self._disabled_keys

    def set_items(
        self,
        items: Iterable[CheckListItem],
        *,
        name_only: bool = False,
        disabled_keys: set[str] | None = None,
        tooltips: dict[str, str] | None = None,
        notify: bool = True,
    ) -> None:
        items = list(items)
        self._name_only = bool(name_only)
        self._disabled_keys = set(disabled_keys or [])
        tooltips = tooltips or {}
        self._suppress = True
        try:
            self.clear()
            if name_only:
                self.setHorizontalHeaderLabels(["", "Name"])
            else:
                self.setHorizontalHeaderLabels(["", "Code", "Name"])
            disabled_brush = QBrush(disabled_list_item_color())
            for it in items:
                check_item = QStandardItem()
                check_item.setData(it.key, Qt.UserRole + 1)
                check_item.setData(it.payload, Qt.UserRole + 2)
                is_disabled = it.key in self._disabled_keys
                check_item.setCheckable(not is_disabled)
                check_item.setCheckState(Qt.Unchecked)
                area_tip = tooltips.get(it.key) or it.label or it.name
                check_item.setEditable(False)
                check_item.setToolTip(area_tip)
                if is_disabled:
                    check_item.setEnabled(False)
                    check_item.setForeground(disabled_brush)
                if name_only:
                    name_item = QStandardItem(it.name)
                    name_item.setEditable(False)
                    name_item.setToolTip(area_tip)
                    if is_disabled:
                        name_item.setEnabled(False)
                        name_item.setForeground(disabled_brush)
                    self.appendRow([check_item, name_item])
                else:
                    code_item = QStandardItem(it.code)
                    name_item = QStandardItem(it.name)
                    for item in (code_item, name_item):
                        item.setEditable(False)
                        item.setToolTip(area_tip)
                        if is_disabled:
                            item.setEnabled(False)
                            item.setForeground(disabled_brush)
                    self.appendRow([check_item, code_item, name_item])
        finally:
            self._suppress = False
        if notify:
            self.selection_changed.emit()

    def uses_name_only_column(self) -> bool:
        return getattr(self, "_name_only", False)

    def checked_payloads(self) -> list[Any]:
        out: list[Any] = []
        for row in range(self.rowCount()):
            item = self.item(row, 0)
            if item and _check_state_value(item.checkState()) == int(Qt.Checked.value):
                out.append(item.data(Qt.UserRole + 2))
        return out

    def checked_keys(self) -> set[str]:
        out: set[str] = set()
        for row in range(self.rowCount()):
            item = self.item(row, 0)
            if item and _check_state_value(item.checkState()) == int(Qt.Checked.value):
                key = item.data(Qt.UserRole + 1)
                if isinstance(key, str):
                    out.add(key)
        return out

    def set_checked_keys(self, keys: set[str]) -> None:
        self._suppress = True
        try:
            for row in range(self.rowCount()):
                item = self.item(row, 0)
                if not item:
                    continue
                key = item.data(Qt.UserRole + 1)
                if isinstance(key, str) and key in self._disabled_keys:
                    item.setCheckState(Qt.Unchecked)
                    continue
                item.setCheckState(Qt.Checked if key in keys else Qt.Unchecked)
        finally:
            self._suppress = False
        self.selection_changed.emit()

    def enabled_row_count(self) -> int:
        return sum(1 for row in range(self.rowCount()) if not self.is_row_disabled(row))

    def auto_select_if_single_option(self) -> None:
        enabled_rows = [row for row in range(self.rowCount()) if not self.is_row_disabled(row)]
        if len(enabled_rows) != 1:
            return
        self._suppress = True
        try:
            item = self.item(enabled_rows[0], 0)
            if item:
                item.setCheckState(Qt.Checked)
        finally:
            self._suppress = False
        self.selection_changed.emit()

    def _on_item_changed(self, item: QStandardItem) -> None:
        if self._suppress or item.column() != 0:
            return
        key = item.data(Qt.UserRole + 1)
        if isinstance(key, str) and key in self._disabled_keys:
            self._suppress = True
            try:
                item.setCheckState(Qt.Unchecked)
            finally:
                self._suppress = False
            return
        self.selection_changed.emit()

    def set_all_checked(self, checked: bool) -> None:
        self._suppress = True
        try:
            state = Qt.Checked if checked else Qt.Unchecked
            for row in range(self.rowCount()):
                if self.is_row_disabled(row):
                    continue
                child = self.item(row, 0)
                if child:
                    child.setCheckState(state)
        finally:
            self._suppress = False
        self.selection_changed.emit()

    def aggregate_check_state(self) -> Qt.CheckState:
        checked = 0
        total = 0
        for row in range(self.rowCount()):
            if self.is_row_disabled(row):
                continue
            total += 1
            child = self.item(row, 0)
            if child and _check_state_value(child.checkState()) == int(Qt.Checked.value):
                checked += 1
        if total == 0 or checked == 0:
            return Qt.Unchecked
        if checked == total:
            return Qt.Checked
        return Qt.PartiallyChecked


class CheckBoxDelegate(QStyledItemDelegate):
    def __init__(self, owner) -> None:
        view = getattr(owner, "area_view", owner)
        super().__init__(view)
        self._owner = owner

    def paint(self, painter: QPainter, option, index) -> None:
        if index.column() != 0:
            super().paint(painter, option, index)
            return

        state_value = _check_state_value(index.data(Qt.CheckStateRole))
        is_checked = state_value == int(Qt.Checked.value)
        is_partial = state_value == int(Qt.PartiallyChecked.value)
        model = index.model()
        is_disabled = hasattr(model, "is_row_disabled") and model.is_row_disabled(index.row())
        is_hover = not is_disabled and bool(option.state & QStyle.State_MouseOver)
        key = index.data(Qt.UserRole + 1)
        auto_codes = getattr(self._owner, "_auto_area_codes", set()) or set()
        is_auto = not is_disabled and isinstance(key, str) and key in auto_codes

        rect = QRectF(option.rect.x() + 5, option.rect.y() + (option.rect.height() - 13) / 2, 13, 13)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        light_mode = resolve_light_mode(self._owner)
        if is_disabled:
            fill, border = checkbox_disabled_fill_border(light_mode=light_mode)
            is_checked = False
            is_partial = False
        elif is_auto:
            fill, border = checkbox_auto_fill_border(light_mode=light_mode, hover=is_hover)
            is_checked = True
            is_partial = False
        else:
            fill, border = checkbox_fill_border(
                light_mode=light_mode,
                checked=is_checked,
                partial=is_partial,
                hover=is_hover,
            )
        painter.setBrush(QBrush(fill))
        painter.setPen(QPen(border, 1.3))
        painter.drawRoundedRect(rect, 3, 3)

        tick = checkbox_auto_tick_color() if is_auto else checkbox_tick_color()
        if is_checked and not is_auto and not is_disabled:
            painter.setPen(QPen(tick, 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.drawLine(rect.left() + 3.0, rect.center().y(), rect.left() + 5.5, rect.bottom() - 3.5)
            painter.drawLine(rect.left() + 5.5, rect.bottom() - 3.5, rect.right() - 2.5, rect.top() + 3.5)
        elif is_partial:
            painter.setPen(QPen(tick, 1.8, Qt.SolidLine, Qt.RoundCap))
            painter.drawLine(rect.left() + 3.0, rect.center().y(), rect.right() - 3.0, rect.center().y())
        painter.restore()


def paint_clipboard_icon(
    painter: QPainter,
    rect: QRect,
    *,
    bright: bool,
    light_mode: bool = False,
    cover_color: QColor | None = None,
) -> None:
    color = copy_icon_color(light_mode=light_mode, bright=bright)
    center = rect.center()
    cx, cy = float(center.x()), float(center.y())
    # Top-left sheet drawn first; bottom-right sheet is on top and masks part of it.
    back = QRectF(cx - 6.5, cy - 6.5, 9.5, 10.5)
    front = QRectF(cx - 1.0, cy - 2.0, 9.5, 10.5)
    pen = QPen(color, 1.35, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    painter.drawRoundedRect(back, 2.2, 2.2)
    if cover_color is not None:
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(cover_color))
        painter.drawRoundedRect(front.adjusted(-0.6, -0.6, 0.6, 0.6), 2.4, 2.4)
    painter.setBrush(Qt.NoBrush)
    painter.setPen(pen)
    painter.drawRoundedRect(front, 2.2, 2.2)


def paint_external_link_icon(
    painter: QPainter,
    rect: QRect,
    *,
    bright: bool,
    light_mode: bool = False,
    cover_color: QColor | None = None,
) -> None:
    """Rounded open-box icon with an arrow through the missing top-right corner."""
    color = copy_icon_color(light_mode=light_mode, bright=bright)
    cx = float(rect.center().x())
    cy = float(rect.center().y())
    pen = QPen(color, 1.35, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)

    size = 10.0
    half = size / 2.0
    box = QRectF(cx - half, cy - half, size, size)
    corner = 2.0
    gap = 2.6

    painter.drawRoundedRect(box, corner, corner)
    if cover_color is not None:
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(cover_color))
        painter.drawRect(QRectF(box.right() - gap, box.top() - 0.5, gap + 0.7, gap + 0.7))
        painter.setBrush(Qt.NoBrush)
        painter.setPen(pen)

    # Arrow exits through the open top-right corner; shifted 1px up vs the box.
    arrow_dy = -1.0
    ax1, ay1 = cx + half + 2.8, cy - half - 2.6 + arrow_dy
    ax0, ay0 = cx + 1.0, cy + 0.4 + arrow_dy
    arm = 4.6
    painter.drawLine(QPointF(ax0, ay0), QPointF(ax1, ay1))
    painter.drawLine(QPointF(ax1, ay1), QPointF(ax1 - arm, ay1))
    painter.drawLine(QPointF(ax1, ay1), QPointF(ax1, ay1 + arm))


def paint_padlock_icon(
    painter: QPainter,
    rect: QRect,
    *,
    bright: bool,
    light_mode: bool = False,
) -> None:
    color = copy_icon_color(light_mode=light_mode, bright=bright)
    center = rect.center()
    cx, cy = float(center.x()), float(center.y())
    pen = QPen(color, 1.35, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)

    body_w, body_h = 8.0, 6.5
    body = QRectF(cx - body_w / 2, cy - 0.5, body_w, body_h)
    painter.drawRoundedRect(body, 1.5, 1.5)

    shackle_w, shackle_h = 5.0, 4.5
    shackle = QRectF(cx - shackle_w / 2, cy - shackle_h - 1.5, shackle_w, shackle_h)
    painter.drawArc(shackle, 0 * 16, 180 * 16)


class ClipboardCopyWidget(QWidget):
    """Minimal clipboard affordance matching the dataset table copy column."""

    def __init__(self, parent: QWidget | None = None, *, owner=None) -> None:
        super().__init__(parent)
        self._owner = owner
        self.setFixedSize(34, 22)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._hover = False

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        light_mode = bool(getattr(self._owner, "_light_mode", False))
        cover = qcolor(LIGHT.card_bg if light_mode else DARK.card_bg)
        if self._hover:
            hover_bg = copy_hover_background(light_mode=light_mode)
            cover = hover_bg
            bg = QRectF(self.rect()).adjusted(2, 2, -2, -2)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(hover_bg))
            painter.drawRoundedRect(bg, 7, 7)
        paint_clipboard_icon(
            painter,
            self.rect(),
            bright=self._hover,
            light_mode=light_mode,
            cover_color=cover,
        )


class ExternalLinkWidget(QWidget):
    """External-link affordance matching the dataset table link column."""

    def __init__(self, parent: QWidget | None = None, *, owner=None) -> None:
        super().__init__(parent)
        self._owner = owner
        self.setFixedSize(34, 22)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._hover = False

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        light_mode = bool(getattr(self._owner, "_light_mode", False))
        cover = qcolor(LIGHT.card_bg if light_mode else DARK.card_bg)
        if self._hover:
            hover_bg = copy_hover_background(light_mode=light_mode)
            cover = hover_bg
            bg = QRectF(self.rect()).adjusted(2, 2, -2, -2)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(hover_bg))
            painter.drawRoundedRect(bg, 7, 7)
        paint_external_link_icon(
            painter,
            self.rect(),
            bright=self._hover,
            light_mode=light_mode,
            cover_color=cover,
        )


def clear_list_index_widgets(view: QListView) -> None:
    """Remove QLabel overlays; they double-draw on top of the default item paint."""
    model = view.model()
    if model is None:
        return
    for row in range(model.rowCount()):
        index = model.index(row, 0)
        if view.indexWidget(index) is not None:
            view.setIndexWidget(index, None)


def clear_tree_index_widgets(view: QTreeView, columns: Iterable[int]) -> None:
    model = view.model()
    if model is None:
        return
    for row in range(model.rowCount()):
        for col in columns:
            index = model.index(row, col)
            if view.indexWidget(index) is not None:
                view.setIndexWidget(index, None)


def clear_dataset_index_widgets(view: QTreeView) -> None:
    """Remove legacy per-row QLabel overlays from the dataset table."""
    model = view.model()
    row_cap = int(getattr(view, "_selectable_row_cap", 0) or 0)
    if model is not None:
        row_cap = max(row_cap, model.rowCount())
    for row in range(row_cap):
        for col in (DATASET_COL_TITLE, DATASET_COL_TAGS):
            if model is None:
                break
            index = model.index(row, col)
            if index.isValid() and view.indexWidget(index) is not None:
                view.setIndexWidget(index, None)
    view._selectable_row_cap = 0  # type: ignore[attr-defined]


class FilterListItemDelegate(QStyledItemDelegate):
    """List rows with full fill for user selection or outline-only for auto-selection."""

    def __init__(self, owner, *, kind: str) -> None:
        view = getattr(owner, f"{kind}_view", owner)
        super().__init__(view)
        self._owner = owner
        self._kind = kind

    def _is_auto_row(self, index) -> bool:
        model = index.model()
        if model is None or not hasattr(model, "selected_payload"):
            return False
        payload = model.selected_payload(index)
        if payload is None:
            return False
        if self._kind == "projection":
            auto = getattr(self._owner, "_auto_projection", None)
            return auto is not None and getattr(payload, "code", None) == auto.code
        auto = getattr(self._owner, "_auto_format", None)
        if auto is None:
            return False
        try:
            return format_filter_key(payload) == format_filter_key(auto)
        except (TypeError, AttributeError):
            return payload is auto

    def paint(self, painter: QPainter, option, index) -> None:
        is_auto = self._is_auto_row(index)
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        if is_auto:
            opt.state &= ~QStyle.State_Selected
        super().paint(painter, opt, index)
        if not is_auto:
            return
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        light_mode = resolve_light_mode(self._owner)
        border = list_selection_border_color(light_mode=light_mode)
        rect = QRectF(option.rect).adjusted(3, 3, -3, -3)
        pen = QPen(border, 2.0)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect, 8, 8)
        painter.restore()


class CopyableListView(QListView):
    """QListView with Ctrl+C support (no per-row index widgets)."""

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.matches(QKeySequence.StandardKey.Copy):
            self._copy_selection_to_clipboard()
            event.accept()
            return
        super().keyPressEvent(event)

    def _copy_selection_to_clipboard(self) -> None:
        model = self.model()
        if model is None:
            return
        indexes = self.selectedIndexes()
        if not indexes:
            current = self.currentIndex()
            if current.isValid():
                indexes = [current]
        lines: list[str] = []
        seen_rows: set[int] = set()
        for index in sorted(indexes, key=lambda idx: idx.row()):
            if index.row() in seen_rows:
                continue
            seen_rows.add(index.row())
            text = model.data(index, Qt.DisplayRole)
            if text:
                lines.append(str(text))
        if lines:
            QApplication.clipboard().setText("\n".join(lines))


class CopyableTreeView(QTreeView):
    """QTreeView with Ctrl+C for text cells (columns > 0)."""

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.matches(QKeySequence.StandardKey.Copy):
            index = self.currentIndex()
            if index.isValid() and index.column() > 0:
                text = self.model().data(index, Qt.DisplayRole) if self.model() else None
                if text:
                    QApplication.clipboard().setText(str(text))
                    event.accept()
                    return
        super().keyPressEvent(event)


class DatasetTreeView(CopyableTreeView):
    """Dataset table: Ctrl+C copies title or theme tags from the current cell."""

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.matches(QKeySequence.StandardKey.Copy):
            index = self.currentIndex()
            if index.isValid() and index.column() in (DATASET_COL_TITLE, DATASET_COL_TAGS):
                text = self.model().data(index, Qt.DisplayRole) if self.model() else None
                if text:
                    QApplication.clipboard().setText(str(text))
                    event.accept()
                    return
        super().keyPressEvent(event)


class DatasetItemDelegate(QStyledItemDelegate):
    def __init__(self, owner):
        super().__init__(owner.dataset_view)
        self._owner = owner

    def paint(self, painter: QPainter, option, index) -> None:
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.state &= ~QStyle.State_MouseOver
        opt.state &= ~QStyle.State_Selected

        row = index.row()
        col = index.column()
        hover = getattr(self._owner, "_dataset_hover", None)
        is_hover_title = hover == (row, DATASET_COL_TITLE) and col == DATASET_COL_TITLE
        is_hover_copy = hover == (row, DATASET_COL_COPY) and col in (DATASET_COL_TITLE, DATASET_COL_COPY)
        is_hover_link = hover == (row, DATASET_COL_LINK) and col in (DATASET_COL_TITLE, DATASET_COL_LINK)
        is_hover_tags = hover == (row, DATASET_COL_TAGS) and col == DATASET_COL_TAGS
        is_selected = bool(option.state & QStyle.State_Selected) and col == DATASET_COL_TITLE
        draw_bg = is_hover_title or is_hover_copy or is_hover_link or is_selected

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        light_mode = bool(getattr(self._owner, "_light_mode", False))
        if draw_bg:
            color = dataset_row_background(light_mode=light_mode, selected=is_selected)
            rect = QRectF(option.rect).adjusted(2, 2, -2, -2)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(color))
            painter.drawRoundedRect(rect, 7, 7)

        if col == DATASET_COL_COPY:
            cover = None
            if draw_bg:
                cover = dataset_row_background(light_mode=light_mode, selected=is_selected)
            else:
                cover = qcolor(LIGHT.card_bg if light_mode else DARK.card_bg)
            paint_clipboard_icon(
                painter,
                option.rect,
                bright=hover == (row, DATASET_COL_COPY),
                light_mode=light_mode,
                cover_color=cover,
            )
            painter.restore()
            return

        if col == DATASET_COL_LINK:
            cover = None
            if draw_bg:
                cover = dataset_row_background(light_mode=light_mode, selected=is_selected)
            else:
                cover = qcolor(LIGHT.card_bg if light_mode else DARK.card_bg)
            paint_external_link_icon(
                painter,
                option.rect,
                bright=hover == (row, DATASET_COL_LINK),
                light_mode=light_mode,
                cover_color=cover,
            )
            painter.restore()
            return

        text = str(index.data(Qt.DisplayRole) or "")
        color = dataset_text_color(
            light_mode=light_mode,
            column=col,
            tags_hover=is_hover_tags and bool(text.strip()),
        )
        font = QFont(option.font)
        if col == DATASET_COL_TAGS:
            font.setPointSize(font_points(10))
            font.setWeight(QFont.DemiBold)
        painter.setFont(font)
        painter.setPen(color)

        text_rect = option.rect.adjusted(8, 0, -6, 0)
        if col == DATASET_COL_TITLE:
            payload = index.data(Qt.UserRole + 1)
            if isinstance(payload, DatasetAvailability) and dataset_shows_padlock(payload):
                lock_rect = QRect(option.rect.left() + 6, option.rect.top(), 16, option.rect.height())
                paint_padlock_icon(
                    painter,
                    lock_rect,
                    bright=is_hover_title or is_selected,
                    light_mode=light_mode,
                )
                text_rect = option.rect.adjusted(22, 0, -6, 0)

        painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, text)
        painter.restore()


class SimpleListModel(QStandardItemModel):
    def set_items(
        self,
        labels_and_payloads: list[tuple[str, Any]],
        *,
        disabled_payloads: set[Any] | None = None,
        tooltips: dict[Any, str] | None = None,
        disabled_payload_ids: set[int] | None = None,
        tooltips_by_id: dict[int, str] | None = None,
    ) -> None:
        self.clear()
        disabled_payloads = disabled_payloads or set()
        tooltips = tooltips or {}
        disabled_payload_ids = disabled_payload_ids or set()
        tooltips_by_id = tooltips_by_id or {}
        for label, payload in labels_and_payloads:
            it = QStandardItem(label)
            it.setData(payload, Qt.UserRole + 1)
            tip = tooltips_by_id.get(id(payload))
            if not tip:
                try:
                    tip = tooltips.get(payload)
                except TypeError:
                    tip = None
            if tip:
                it.setToolTip(tip)
            elif label:
                it.setToolTip(label)
            is_disabled = False
            try:
                is_disabled = payload in disabled_payloads
            except TypeError:
                is_disabled = False
            if is_disabled or (id(payload) in disabled_payload_ids):
                it.setEnabled(False)
                it.setForeground(QBrush(disabled_list_item_color()))
            self.appendRow(it)

    def selected_payload(self, index) -> Any | None:
        if not index.isValid():
            return None
        item = self.itemFromIndex(index)
        if not item:
            return None
        return item.data(Qt.UserRole + 1)


class TwoColumnListModel(QStandardItemModel):
    def set_items(
        self,
        rows: list[tuple[str, str, Any]],
        *,
        disabled_payload_ids: set[int] | None = None,
        primary_tooltips_by_id: dict[int, str] | None = None,
        secondary_tooltips_by_id: dict[int, str] | None = None,
        link_tooltips_by_id: dict[int, str] | None = None,
    ) -> None:
        self.clear()
        disabled_payload_ids = disabled_payload_ids or set()
        primary_tooltips_by_id = primary_tooltips_by_id or {}
        secondary_tooltips_by_id = secondary_tooltips_by_id or {}
        link_tooltips_by_id = link_tooltips_by_id or {}
        for primary, secondary, payload in rows:
            primary_item = QStandardItem(primary)
            copy_item = QStandardItem("")
            link_item = QStandardItem("")
            secondary_item = QStandardItem(secondary)
            secondary_font = QFont()
            secondary_font.setPointSize(font_points(10))
            secondary_font.setWeight(QFont.DemiBold)
            secondary_item.setFont(secondary_font)
            copy_item.setTextAlignment(Qt.AlignCenter)
            link_item.setTextAlignment(Qt.AlignCenter)
            for item in (primary_item, copy_item, link_item, secondary_item):
                item.setData(payload, Qt.UserRole + 1)
                item.setEditable(False)
            if id(payload) in disabled_payload_ids:
                for item in (primary_item, secondary_item):
                    item.setEnabled(False)
                    item.setForeground(QBrush(disabled_list_item_color()))
            pid = id(payload)
            tip_p = primary_tooltips_by_id.get(pid)
            primary_item.setToolTip(tip_p if tip_p is not None else primary)
            copy_item.setToolTip("Copy...")
            tip_link = link_tooltips_by_id.get(pid)
            if tip_link:
                link_item.setToolTip(tip_link)
            tip_s = secondary_tooltips_by_id.get(pid)
            secondary_item.setToolTip(tip_s if tip_s is not None else secondary)
            secondary_item.setForeground(QBrush(QColor("#9ba3b4")))
            self.appendRow(
                [primary_item, copy_item, secondary_item, link_item],
            )

    def selected_payload(self, index) -> Any | None:
        if not index.isValid():
            return None
        item = self.itemFromIndex(index)
        if not item:
            return None
        return item.data(Qt.UserRole + 1)

