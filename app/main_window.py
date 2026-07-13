from __future__ import annotations

import logging
import math
import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from PySide6.QtCore import (
    QEvent,
    QItemSelectionModel,
    QModelIndex,
    QPoint,
    QPointF,
    QRectF,
    QSettings,
    QSize,
    QStandardPaths,
    Qt,
    QThreadPool,
    QTimer,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QCursor,
    QDesktopServices,
    QFont,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListView,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QStatusBar,
    QToolButton,
    QToolTip,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from app import APP_DISPLAY_NAME, __version__
from app.area_map_expand import (
    ExpandedAreaMapWindow,
    MapExpandButton,
    MapZoomInButton,
    MapZoomOutButton,
    expanded_map_window_geometry,
)
from app.compatibility_ui import (
    CompatibilityState,
    area_list_state,
    compute_compatibility,
    format_list_state,
    incompatible_selection_reasons,
    projection_list_state,
)
from app.dialogs import (
    show_connection_lost_dialog,
    themed_confirm_box,
    themed_message_box,
)
from app.download_progress import (
    DownloadOrderInfo,
    DownloadProgressDialog,
    DownloadProgressItem,
    area_progress_display,
    format_order_subheader,
)
from app.download_queue import PackagingSlotQueue, TransferSlotQueue
from app.filter_index import DatasetFilterIndex, format_filter_key
from app.map_picker import (
    ZOOM_STEP,
    MapPickerWidget,
    fetch_text,
    match_area_grid_codes,
    parse_geojson_grid_cells,
)
from app.models_qt import (
    DATASET_COL_COPY,
    DATASET_COL_LINK,
    DATASET_COL_TAGS,
    DATASET_COL_TITLE,
    AreaSelectionModel,
    CheckBoxDelegate,
    CheckListItem,
    ClipboardCopyWidget,
    CopyableListView,
    CopyableTreeView,
    DatasetItemDelegate,
    DatasetTreeView,
    ExternalLinkWidget,
    FilterListItemDelegate,
    SimpleListModel,
    TwoColumnListModel,
    clear_dataset_index_widgets,
    clear_list_index_widgets,
    clear_tree_index_widgets,
)
from app.theme import (
    SHARED,
    apply_base_style,
    build_stylesheet,
    busy_overlay_fill,
    checkbox_fill_border,
    checkbox_tick_color,
    default_text_scale_name,
    palette_for,
    qcolor,
    resolve_light_mode,
    scale_name_to_factor,
    scale_pixels,
    set_filter_busy_flag,
    set_text_scale_factor,
    theme_toggle_colors,
    theme_toggle_knob_border,
)
from app.tooltip_delay import cancel_pending_tooltips
from app.updates import (
    GITHUB_OWNER,
    GITHUB_REPO,
    build_latest_release_web_url,
    fetch_latest_release,
    is_newer_version,
)
from app.workers import FuncWorker, connect_worker_signals
from geonorge.batch_download import (
    BatchDownloadPartialFailure,
    DownloadCancelled,
    DownloadJobSpec,
    DownloadTask,
    build_target_path,
    run_batch_order_download,
)
from geonorge.client import HttpClient
from geonorge.compatibility import area_supports
from geonorge.discovery import DiscoveryService
from geonorge.map_selection import (
    geojson_url_for_map_selection_layer,
    infer_source_epsg,
    resolve_map_selection_layer,
)
from geonorge.models import (
    AreaOption,
    AreaType,
    DatasetAvailability,
    DatasetRef,
    FormatOption,
    ProjectionOption,
)
from geonorge.nedlasting import NedlastingClient

# Area table column layout (checkbox | code | name).
_AREA_CHECKBOX_COLUMN_W = 28
_AREA_CODE_COLUMN_W = 82  # 10px narrower than before so Name sits closer to Code

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _DownloadCancelledResult:
    pass


@dataclass
class _PartialDownloadResult:
    successes: list[tuple[str, str]]
    failures: list[tuple[str, str]]


@dataclass
class _DownloadJob:
    job_id: int
    cancel: threading.Event
    worker: FuncWorker | None
    dialog: DownloadProgressDialog


# Selected panel: collapse long category/area lists (>3 items → show 2 + toggle).
_SELECTED_GROUP_COLLAPSE_AFTER = 3
_SELECTED_GROUP_COLLAPSED_VISIBLE = 2

# Avoid building a multi-thousand-row area table when browsing filters without a dataset.
_AREA_TABLE_ROW_LIMIT = 600
# Area search is only offered when the current type has at least this many options.
_AREA_SEARCH_MIN_OPTIONS = 2

# Panels that may be refreshed after filter/list changes (merged across debounced timer ticks).
_REFRESH_ALL = frozenset(
    {
        "categories",
        "datasets",
        "area_types",
        "areas",
        "projections",
        "formats",
        "selected",
        "download",
    }
)
# Dataset / format / projection / area checkbox changes: skip category tag rebuild when unchanged.
_REFRESH_FILTER_IMPACT = _REFRESH_ALL
# Checking or unchecking areas does not change which rows appear in the area table.
_REFRESH_AREA_CHECK = frozenset(
    {"categories", "datasets", "area_types", "projections", "formats", "selected", "download"}
)
# Selecting a dataset narrows option lists but does not change category keys until enrichment.
_REFRESH_DATASET = frozenset(
    {"categories", "datasets", "areas", "area_types", "projections", "formats", "selected", "download"}
)
# During bulk enrichment without a selected dataset, refresh browse filter panels only.
_REFRESH_BROWSE_FILTERS = frozenset({"area_types", "areas", "projections", "formats"})

# Right-aligned action cluster in Selected rows (copy + link + row X).
_SELECTED_ROW_ACTIONS_WIDTH = 90
_SELECTED_ROW_ACTION_SPACING = 2
# Header clear-all is 24px wide; per-row clear is 18px — shift cluster left to align.
_SELECTED_ROW_ACTIONS_RIGHT_INSET = 6

AREA_TYPE_ORDER: tuple[AreaType, ...] = ("landsdekkende", "fylke", "kommune", "celle")

# Bottom panel width proportions (format ~25%; projection narrowed; selected + download wider).
_BOTTOM_PROJECTION_STRETCH = 4
_BOTTOM_FORMAT_STRETCH = 3
_BOTTOM_SELECTED_STRETCH = 5

_STATUS_SEPARATOR = "    |    "


def _norwegian_sort_key(value: str) -> str:
    return (
        value.casefold()
        .replace("æ", "{")
        .replace("ø", "|")
        .replace("å", "}")
    )


def _code_sort_key(code: str) -> tuple[int, str]:
    return (0, f"{int(code):08d}") if code.isdigit() else (1, code.casefold())


def _format_bytes(value: int | None) -> str:
    if value is None:
        return "unknown size"
    amount = float(value)
    for unit in ("B", "KB", "MB", "GB"):
        if amount < 1024 or unit == "GB":
            return f"{amount:.1f} {unit}" if unit != "B" else f"{int(amount)} B"
        amount /= 1024
    return f"{amount:.1f} GB"


def _format_filter_key(fmt: FormatOption) -> str:
    return format_filter_key(fmt)


def _status_message(*parts: str) -> str:
    return _STATUS_SEPARATOR.join(parts)


def _filter_panel_count_text(*, selectable: int, total: int) -> str:
    """Header counter: (total) or (selectable / total) when some rows are disabled."""
    if total <= 0:
        return ""
    if selectable < total:
        return f"({selectable:,} / {total:,})"
    return f"({total:,})"


def _check_state_value(state: object) -> int:
    if hasattr(state, "value"):
        return int(state.value)  # type: ignore[arg-type]
    if state is None:
        return int(Qt.Unchecked.value)
    return int(state)  # type: ignore[arg-type]


class HeaderCheckBox(QCheckBox):
    _INDICATOR_SIZE = 13
    _INDICATOR_LEFT = 5

    def _indicator_rect(self) -> QRectF:
        return QRectF(
            float(self._INDICATOR_LEFT),
            (self.height() - self._INDICATOR_SIZE) / 2.0,
            float(self._INDICATOR_SIZE),
            float(self._INDICATOR_SIZE),
        )

    def hitButton(self, pos: QPoint) -> bool:
        # Custom paint draws the box at a fixed offset; Qt's default hit test misses it.
        return self._indicator_rect().contains(QPointF(float(pos.x()), float(pos.y())))

    def paintEvent(self, event) -> None:
        rect = self._indicator_rect()
        state = _check_state_value(self.checkState())
        is_hover = self.underMouse()
        light_mode = resolve_light_mode(self)
        checked = state in (int(Qt.Checked.value), int(Qt.PartiallyChecked.value))
        partial = state == int(Qt.PartiallyChecked.value)
        fill, border = checkbox_fill_border(
            light_mode=light_mode,
            checked=checked,
            partial=partial,
            hover=is_hover,
        )
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QBrush(fill))
        painter.setPen(QPen(border, 1.3))
        painter.drawRoundedRect(rect, 3, 3)
        tick = checkbox_tick_color()
        if state == int(Qt.Checked.value):
            painter.setPen(QPen(tick, 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.drawLine(rect.left() + 3.0, rect.center().y(), rect.left() + 5.5, rect.bottom() - 3.5)
            painter.drawLine(rect.left() + 5.5, rect.bottom() - 3.5, rect.right() - 2.5, rect.top() + 3.5)
        elif partial:
            painter.setPen(QPen(tick, 1.8, Qt.SolidLine, Qt.RoundCap))
            painter.drawLine(rect.left() + 3.0, rect.center().y(), rect.right() - 3.0, rect.center().y())


class FilterCheckBox(QCheckBox):
    def paintEvent(self, event) -> None:
        state = _check_state_value(self.checkState())
        is_hover = self.underMouse()
        light_mode = resolve_light_mode(self)
        checked = state == int(Qt.Checked.value)
        fill, border = checkbox_fill_border(
            light_mode=light_mode,
            checked=checked,
            partial=False,
            hover=is_hover,
        )
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = QRectF(1, (self.height() - 13) / 2, 13, 13)
        painter.setBrush(QBrush(fill))
        painter.setPen(QPen(border, 1.3))
        painter.drawRoundedRect(rect, 3, 3)
        if checked:
            painter.setPen(QPen(checkbox_tick_color(), 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.drawLine(rect.left() + 3.0, rect.center().y(), rect.left() + 5.5, rect.bottom() - 3.5)
            painter.drawLine(rect.left() + 5.5, rect.bottom() - 3.5, rect.right() - 2.5, rect.top() + 3.5)

        painter.setPen(qcolor(palette_for(light_mode).filter_checkbox_fg))
        painter.drawText(self.rect().adjusted(20, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, self.text())


class _SelectableTextMixin:
    """
    Mouse-driven text selection without a visible text caret.

    Uses TextSelectableByMouse only (not TextSelectableByKeyboard) so Qt does not
    draw the blinking insertion cursor; Shift+arrow extends the highlight instead.
    """

    _selection_anchor: int

    def _init_selectable_text(self) -> None:
        self._selection_anchor = 0
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.setFocusPolicy(Qt.ClickFocus)
        self.setCursor(Qt.IBeamCursor)

    def _sync_selection_anchor_from_label(self) -> None:
        start = self.selectionStart()
        if start >= 0:
            self._selection_anchor = start

    @staticmethod
    def _selection_length(label: QLabel) -> int:
        if not label.hasSelectedText():
            return 0
        return len(label.selectedText())

    def mousePressEvent(self, event) -> None:  # noqa: N802
        super().mousePressEvent(event)
        self._sync_selection_anchor_from_label()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        super().mouseReleaseEvent(event)
        start = self.selectionStart()
        if start >= 0 and self._selection_length(self) > 0:
            self._selection_anchor = start

    def _extend_selection_with_shift(self, key: Qt.Key) -> None:
        text_len = len(self.text() or "")
        start = self.selectionStart()
        length = self._selection_length(self)
        if start < 0:
            start = 0
            length = 0
        anchor = self._selection_anchor
        focus = start + length
        if length > 0 and anchor == focus:
            anchor = start
        if key == Qt.Key.Key_Left:
            focus = max(0, focus - 1)
        elif key == Qt.Key.Key_Right:
            focus = min(text_len, focus + 1)
        elif key == Qt.Key.Key_Home:
            focus = 0
        elif key == Qt.Key.Key_End:
            focus = text_len
        else:
            return
        new_start = min(anchor, focus)
        new_length = abs(focus - anchor)
        self.setSelection(new_start, new_length)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.matches(QKeySequence.StandardKey.Copy):
            selected = self.selectedText()
            if selected:
                QApplication.clipboard().setText(selected)
                event.accept()
                return
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier and event.key() in (
            Qt.Key.Key_Left,
            Qt.Key.Key_Right,
            Qt.Key.Key_Home,
            Qt.Key.Key_End,
        ):
            self._extend_selection_with_shift(event.key())
            event.accept()
            return
        super().keyPressEvent(event)


class SelectableLabel(_SelectableTextMixin, QLabel):
    """Header/status text: selectable like a browser, no visible text caret."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._init_selectable_text()


class ElidedLabel(_SelectableTextMixin, QLabel):
    """Single-line label that ellipsizes; never expands layouts with the full text width."""

    def __init__(self, text: str = ""):
        super().__init__(text)
        self._full_text = text
        self.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.setWordWrap(False)
        self._init_selectable_text()

    def set_full_text(self, text: str) -> None:
        self._full_text = text
        self._refresh_elided_text()
        self.updateGeometry()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh_elided_text()

    def sizeHint(self) -> QSize:
        line_h = self.fontMetrics().height() + 4
        return QSize(0, line_h)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def _refresh_elided_text(self) -> None:
        width = self.contentsRect().width()
        if width <= 0 and self.parentWidget() is not None:
            width = self.parentWidget().contentsRect().width()
        elided = self.fontMetrics().elidedText(self._full_text, Qt.ElideRight, max(10, width))
        self.setText(elided)


class BusyOverlay(QWidget):
    """Rounded, semi-transparent overlay that blocks interaction."""

    def __init__(self, parent: QWidget, *, radius: int = 10) -> None:
        super().__init__(parent)
        self._radius = radius
        self._fill = busy_overlay_fill(light_mode=False)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setMouseTracking(True)
        self.setCursor(Qt.WaitCursor)
        self.hide()

    def set_fill(self, color: QColor) -> None:
        self._fill = color
        if self.isVisible():
            self.update()

    def event(self, event) -> bool:
        # Swallow input while visible.
        if self.isVisible() and event.type() in (
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonRelease,
            QEvent.Type.MouseButtonDblClick,
            QEvent.Type.Wheel,
            QEvent.Type.KeyPress,
            QEvent.Type.KeyRelease,
            QEvent.Type.ContextMenu,
        ):
            return True
        return super().event(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(self._fill))
        painter.drawRoundedRect(self.rect(), self._radius, self._radius)


class DatasetSearchLineEdit(QLineEdit):
    """Search field with a themed clear control and pointing-hand cursor on it."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        field_name: str = "datasetSearch",
        clear_name: str = "datasetSearchClear",
    ) -> None:
        super().__init__(parent)
        self.setObjectName(field_name)
        self._search_button: QPushButton | None = None
        self._clear_button = QToolButton(self)
        self._clear_button.setObjectName(clear_name)
        self._clear_button.setText("×")
        self._clear_button.setCursor(Qt.PointingHandCursor)
        self._clear_button.setToolTip("Clear search")
        self._clear_button.clicked.connect(self.clear)
        self._clear_button.hide()
        self.textChanged.connect(self._sync_clear_visibility)

    def set_search_button(self, button: QPushButton) -> None:
        self._search_button = button

    def _set_search_button_focused(self, focused: bool) -> None:
        button = self._search_button
        if button is None:
            return
        button.setProperty("searchFocused", focused)
        style = button.style()
        style.unpolish(button)
        style.polish(button)

    def focusInEvent(self, event) -> None:  # noqa: N802
        super().focusInEvent(event)
        self._set_search_button_focused(True)

    def focusOutEvent(self, event) -> None:  # noqa: N802
        super().focusOutEvent(event)
        self._set_search_button_focused(False)

    def _sync_clear_visibility(self, text: str) -> None:
        self._clear_button.setVisible(bool(text))
        self._position_clear_button()

    def clear(self) -> None:
        super().clear()
        self._sync_clear_visibility(self.text())

    def setText(self, text: str) -> None:  # noqa: N802 (Qt API)
        super().setText(text)
        self._sync_clear_visibility(text)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._position_clear_button()

    def _position_clear_button(self) -> None:
        size = 22
        x = max(4, self.width() - size - 6)
        y = max(0, (self.height() - size) // 2)
        self._clear_button.setGeometry(x, y, size, size)


class PagerButton(QPushButton):
    """Square pager control with a centered chevron drawn in the button."""

    def __init__(self, direction: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("pagerButton")
        self.setText("")
        self.setFixedSize(28, 28)
        self.setCursor(Qt.PointingHandCursor)
        self._direction = direction

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        light_mode = resolve_light_mode(self)
        color = qcolor(palette_for(light_mode).button_fg)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(color, 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        cx = self.width() / 2
        cy = self.height() / 2
        arm = 5
        inset = 3
        if self._direction == "prev":
            painter.drawLine(int(cx + inset), int(cy - arm), int(cx - inset), int(cy))
            painter.drawLine(int(cx - inset), int(cy), int(cx + inset), int(cy + arm))
        else:
            painter.drawLine(int(cx - inset), int(cy - arm), int(cx + inset), int(cy))
            painter.drawLine(int(cx + inset), int(cy), int(cx - inset), int(cy + arm))


class SearchMagnifyButton(QPushButton):
    """Compact search trigger with a simple magnifying-glass glyph."""

    def __init__(self, parent: QWidget | None = None, *, object_name: str = "datasetSearchButton") -> None:
        super().__init__(parent)
        self.setObjectName(object_name)
        self.setFixedSize(38, 34)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Search")
        self._light_mode = False

    def set_light_mode(self, value: bool) -> None:
        self._light_mode = bool(value)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        palette = palette_for(self._light_mode)
        if self._light_mode:
            icon_color = qcolor(palette.card_border)
        else:
            icon_color = qcolor(palette.input_border_focus)
        center = self.rect().center()
        cx, cy = float(center.x()), float(center.y())
        lens = QRectF(cx - 5.5, cy - 6.0, 9.0, 9.0)
        painter.setPen(QPen(icon_color, 1.35, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(lens)
        painter.drawLine(
            QPoint(int(lens.right() - 0.5), int(lens.bottom() - 0.5)),
            QPoint(int(cx + 6.0), int(cy + 6.0)),
        )


class ThemeToggleSwitch(QWidget):
    light_mode_changed = Signal(bool)

    @staticmethod
    def _paint_sun_icon(painter: QPainter, cx: float, cy: float, pen: QPen) -> None:
        """Circle with eight short rays (classic sun glyph)."""
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        core_r = 3.5
        painter.drawEllipse(QRectF(cx - core_r, cy - core_r, core_r * 2, core_r * 2))
        ray_start = core_r + 2.8
        ray_end = core_r + 5.0
        for i in range(8):
            angle = (math.pi / 4) * i - math.pi / 2
            x1 = cx + ray_start * math.cos(angle)
            y1 = cy + ray_start * math.sin(angle)
            x2 = cx + ray_end * math.cos(angle)
            y2 = cy + ray_end * math.sin(angle)
            painter.drawLine(QPoint(int(round(x1)), int(round(y1))), QPoint(int(round(x2)), int(round(y2))))

    @staticmethod
    def _paint_moon_icon(painter: QPainter, cx: float, cy: float) -> None:
        """Thin banana crescent (filled white)."""
        painter.setRenderHint(QPainter.Antialiasing)
        outer_r = 6.0
        body = QPainterPath()
        body.addEllipse(QRectF(cx - outer_r, cy - outer_r, outer_r * 2, outer_r * 2))
        cut = QPainterPath()
        inner_r = 5.6
        # Cut offset (~10° clockwise on screen; y-axis points down in Qt).
        cut_dx, cut_dy = -4.4, 1.0
        angle = math.radians(10)
        ox, oy = cut_dx, cut_dy
        cut_dx = ox * math.cos(angle) - oy * math.sin(angle)
        cut_dy = ox * math.sin(angle) + oy * math.cos(angle)
        cut.addEllipse(QRectF(cx - inner_r + cut_dx, cy - inner_r + cut_dy, inner_r * 2, inner_r * 2))
        crescent = body.subtracted(cut)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(qcolor(SHARED.white)))
        painter.drawPath(crescent)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(60, 30)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Light mode")
        self._light_mode = False
        border, track, icon = theme_toggle_colors(light_mode=False)
        self._border = border
        self._track_bg = track
        self._icon_color = icon

    def is_light_mode(self) -> bool:
        return self._light_mode

    def set_light_mode(self, value: bool) -> None:
        if self._light_mode == value:
            return
        self._light_mode = value
        self.setToolTip("Dark mode" if self._light_mode else "Light mode")
        self.update()

    def set_colors(self, *, border: QColor, track_bg: QColor, icon: QColor | None = None) -> None:
        self._border = border
        self._track_bg = track_bg
        if icon is not None:
            self._icon_color = icon
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.set_light_mode(not self._light_mode)
            self.light_mode_changed.emit(self._light_mode)
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        r = QRectF(self.rect()).adjusted(1.2, 1.2, -1.2, -1.2)
        radius = r.height() / 2
        painter.setPen(QPen(self._border, 1.35))
        painter.setBrush(QBrush(self._track_bg))
        painter.drawRoundedRect(r, radius, radius)

        # Knob
        knob_d = r.height() - 6
        knob_y = r.top() + (r.height() - knob_d) / 2
        if self._light_mode:
            knob_x = r.right() - knob_d - 3
        else:
            knob_x = r.left() + 3
        knob = QRectF(knob_x, knob_y, knob_d, knob_d)
        knob_fill, knob_border = theme_toggle_knob_border()
        painter.setBrush(QBrush(knob_fill))
        painter.setPen(QPen(knob_border, 1.25))
        painter.drawEllipse(knob)

        # Icons (same grey as panel borders)
        icon_pen = QPen(self._icon_color, 1.35, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        painter.setPen(icon_pen)
        painter.setBrush(Qt.NoBrush)
        center_y = r.center().y()
        if self._light_mode:
            self._paint_moon_icon(painter, r.left() + 15, center_y)
        else:
            self._paint_sun_icon(painter, r.right() - 15, r.center().y(), icon_pen)


def _merge_area_selection_with_visible_checks(
    selected: list[AreaOption],
    *,
    visible_codes: set[str],
    visible_checked: list[AreaOption],
) -> list[AreaOption]:
    """Keep selections not shown in the filtered list; sync only visible rows."""
    hidden = [a for a in selected if a.code not in visible_codes]
    return hidden + visible_checked


class MainWindow(QMainWindow):
    def __init__(self, *, profile_ui: bool = False):
        super().__init__()
        self.setWindowTitle(f"{APP_DISPLAY_NAME} (v{__version__})")
        self.resize(1200, 800)

        self._http = HttpClient()
        self._discovery = DiscoveryService(self._http)
        self._nedlasting = NedlastingClient(self._http)

        self._datasets: list[DatasetAvailability] = []
        self._dataset_index_by_uuid: dict[str, int] = {}
        self._dataset_refs: list[DatasetRef] = []
        self._displayed_dataset_uuids: list[str] = []
        self._enriching_uuids: set[str] = set()
        self._bulk_enrichment = False
        self._enrichment_cancel = threading.Event()

        self._selected_area_type: AreaType | None = None
        self._selected_areas: list[AreaOption] = []
        self._selected_dataset: DatasetAvailability | None = None
        self._selected_categories: set[str] = set()
        self._selected_categories_expanded = False
        self._selected_areas_expanded = False
        self._selected_projection: ProjectionOption | None = None
        self._selected_format: FormatOption | None = None
        self._auto_projection: ProjectionOption | None = None
        self._auto_format: FormatOption | None = None
        self._auto_area_type: AreaType | None = None
        self._auto_areas: list[AreaOption] = []
        self._auto_area_codes: set[str] = set()
        self._show_only_downloadable = False
        self._dataset_search_text = ""
        self._area_search_text = ""
        self._area_display_name_only = False
        self._active_workers: list[FuncWorker] = []
        self._area_sort_column = "name"
        self._area_sort_ascending = True
        self._suppress_area_change = False
        self._pending_area_change = False
        self._suppress_single_select_change = False
        self._hover_scroll_widgets: list[QWidget] = []
        self._area_signature: object = ()
        self._area_populate_context: tuple[str | None, AreaType | None] | None = None
        self._dataset_signature: tuple[tuple[str, str, str], ...] = ()
        self._projection_signature: tuple[str, ...] = ()
        self._format_signature: tuple[str, ...] = ()
        self._category_signature: tuple[str, ...] = ()
        self._area_types_signature: tuple[AreaType, ...] = ()
        self._compatibility_state = CompatibilityState()
        self._area_map_load_generation = 0
        self._map_grid_pool: QThreadPool | None = None
        self._area_map_reload_pending = False
        self._area_map_pending_apply: tuple[list, int, str] | None = None
        self._area_map_parsed: list = []
        self._area_map_expanded = False
        self._area_map_expanded_window: ExpandedAreaMapWindow | None = None
        self._area_map_closing = False
        self._recompute_running = False
        self._filter_index: DatasetFilterIndex | None = None
        self._login_required_datasets: list[DatasetAvailability] = []
        self._pending_refresh: frozenset[str] = frozenset()
        self._recompute_scope = "full"
        self._filter_busy_depth = 0
        self._filter_busy_widgets: list[QWidget] = []
        self._filter_busy_widget_set: set[QWidget] = set()
        self._busy_overlays: list[BusyOverlay] = []
        self._light_mode = False
        self._refresh_busy = False
        self._reset_busy = False
        self._recompute_timer = QTimer(self)
        self._recompute_timer.setSingleShot(True)
        self._recompute_timer.timeout.connect(self._recompute_lists)
        self._last_progress_message = ""
        self._profile_ui = bool(profile_ui)
        self._dataset_page = 0
        self._dataset_page_size = 500
        self._dataset_total_rows = 0
        self._dataset_hover: tuple[int, int] | None = None
        self._dataset_copy_menu: QMenu | None = None
        self._dataset_copy_menu_source: object | None = None
        self._mouse_selecting = False
        self._copy_menu_close_timer = QTimer(self)
        self._copy_menu_close_timer.setSingleShot(True)
        self._copy_menu_close_timer.timeout.connect(self._close_dataset_copy_menu)
        self._copy_status_timer = QTimer(self)
        self._copy_status_timer.setSingleShot(True)
        self._copy_status_timer.timeout.connect(lambda: self.copy_status_text.setText(""))
        self._packaging_queue = PackagingSlotQueue()
        self._transfer_queue = TransferSlotQueue()
        self._download_jobs: dict[int, _DownloadJob] = {}
        self._download_progress_dialog: DownloadProgressDialog | None = None
        self._download_job_seq = 0
        self._pending_update_url: str | None = None
        self._update_check_inflight = False
        self._build_ui()
        self._apply_style()
        self._wire_events()
        self._schedule_recompute_lists(0)

        self._update_check_timer = QTimer(self)
        self._update_check_timer.setInterval(30 * 60 * 1000)
        self._update_check_timer.timeout.connect(self._maybe_check_for_updates)
        self._update_check_timer.start()
        QTimer.singleShot(0, self._maybe_check_for_updates)

        self._load_initial_data()

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)

        outer = QGridLayout(root)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)

        # Top toolbar (Refresh, Clear filters), aligned with the left side.
        self.top_toolbar = QWidget()
        toolbar_layout = QHBoxLayout(self.top_toolbar)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        toolbar_layout.setSpacing(8)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setObjectName("toolbarButton")
        self.refresh_button.setCursor(Qt.PointingHandCursor)
        self.reset_cache_button = QPushButton("Reset cache")
        self.reset_cache_button.setObjectName("toolbarButton")
        self.reset_cache_button.setCursor(Qt.PointingHandCursor)
        self.reset_cache_button.setToolTip(
            "Delete the local dataset index and start over as if the app were never used."
        )
        self.check_updates_button = QPushButton("New version available")
        self.check_updates_button.setObjectName("toolbarButton")
        self.check_updates_button.setCursor(Qt.PointingHandCursor)
        self.check_updates_button.setToolTip("A newer release is on GitHub — open download page.")
        self.check_updates_button.setVisible(False)
        toolbar_layout.addWidget(self.refresh_button)
        toolbar_layout.addWidget(self.reset_cache_button)
        toolbar_layout.addWidget(self.check_updates_button)
        toolbar_layout.addStretch(1)
        self.text_scale_group = QButtonGroup(self)
        self.text_scale_normal_button = QPushButton("A")
        self.text_scale_normal_button.setObjectName("textScaleSmallButton")
        self.text_scale_normal_button.setCursor(Qt.PointingHandCursor)
        self.text_scale_normal_button.setToolTip("Standard text size")
        self.text_scale_large_button = QPushButton("A")
        self.text_scale_large_button.setObjectName("textScaleLargeButton")
        self.text_scale_large_button.setCursor(Qt.PointingHandCursor)
        self.text_scale_large_button.setToolTip("Larger text and controls (recommended on macOS/Linux)")
        self.text_scale_group.addButton(self.text_scale_normal_button, 0)
        self.text_scale_group.addButton(self.text_scale_large_button, 1)
        toolbar_layout.addWidget(self.text_scale_normal_button)
        toolbar_layout.addWidget(self.text_scale_large_button)
        self.theme_toggle = ThemeToggleSwitch(self.top_toolbar)
        toolbar_layout.addWidget(self.theme_toggle)

        # Main panel (contains all subpanels)
        self.main_frame = QFrame()
        self.main_frame.setObjectName("mainCard")
        self.main_frame.setFrameShape(QFrame.StyledPanel)
        main_layout = QHBoxLayout(self.main_frame)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(12)

        left_column = QWidget()
        left_layout = QVBoxLayout(left_column)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)

        self.downloadable_filter = FilterCheckBox("Only directly downloadable")
        self.downloadable_filter.setObjectName("filterCheckBox")
        self.downloadable_filter.setToolTip("Show only datasets directly downloadable via Geonorge's API.")
        self.downloadable_filter.setCursor(Qt.PointingHandCursor)

        self.categories_panel = QFrame()
        self.categories_panel.setObjectName("subCard")
        self.categories_panel.setFrameShape(QFrame.StyledPanel)
        categories_layout = QVBoxLayout(self.categories_panel)
        categories_layout.setContentsMargins(10, 10, 10, 10)
        categories_layout.setSpacing(8)
        self.category_header = QWidget()
        category_header_layout = QHBoxLayout(self.category_header)
        category_header_layout.setContentsMargins(0, 0, 0, 0)
        category_header_layout.setSpacing(6)
        self.category_label = SelectableLabel("Categories")
        self.category_count_label = SelectableLabel("(0)")
        self.category_count_label.setObjectName("secondaryHeaderLabel")
        category_header_layout.addWidget(self.category_label)
        category_header_layout.addWidget(self.category_count_label)
        category_header_layout.addStretch(1)
        self.category_view = CopyableListView()
        self.category_view.setObjectName("categoryView")
        self.category_view.setEditTriggers(QListView.NoEditTriggers)
        self.category_view.setSelectionMode(QListView.MultiSelection)
        categories_layout.addWidget(self.category_header)
        categories_layout.addWidget(self.category_view, 1)

        self.area_type_group = QButtonGroup(self)
        self.area_type_group.setExclusive(False)
        self.area_type_widget = QWidget()
        self.area_type_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        area_type_layout = QHBoxLayout(self.area_type_widget)
        area_type_layout.setContentsMargins(0, 0, 0, 0)
        area_type_layout.setSpacing(6)
        self.area_type_buttons: dict[AreaType, QRadioButton] = {
            "landsdekkende": QRadioButton("Entire country"),
            "fylke": QRadioButton("County"),
            "kommune": QRadioButton("Municipality"),
            "celle": QRadioButton("Cell"),
        }
        for i, (key, button) in enumerate(self.area_type_buttons.items()):
            button.setObjectName("areaTypeRadio")
            button.setAutoExclusive(False)
            button.setCursor(Qt.PointingHandCursor)
            button.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
            self.area_type_group.addButton(button, i)
            area_type_layout.addWidget(button)
        area_type_layout.addStretch(1)

        self.area_search_row = QWidget()
        area_search_layout = QHBoxLayout(self.area_search_row)
        area_search_layout.setContentsMargins(0, 0, 0, 0)
        area_search_layout.setSpacing(8)
        self.area_search_combo = QWidget()
        self.area_search_combo.setObjectName("areaSearchCombo")
        area_search_combo_layout = QHBoxLayout(self.area_search_combo)
        area_search_combo_layout.setContentsMargins(0, 0, 0, 0)
        area_search_combo_layout.setSpacing(0)
        self.area_search = DatasetSearchLineEdit(
            field_name="areaSearch",
            clear_name="areaSearchClear",
        )
        self.area_search.setPlaceholderText("Search name or code")
        self.area_search.setFixedHeight(34)
        self.area_search.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.area_search_button = SearchMagnifyButton(object_name="areaSearchButton")
        self.area_search.set_search_button(self.area_search_button)
        self.area_search_combo.setFixedHeight(34)
        self.area_search_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        area_search_combo_layout.addWidget(self.area_search, 1)
        area_search_combo_layout.addWidget(self.area_search_button, 0)
        area_search_layout.addWidget(self.area_search_combo, 1)
        self.area_map_zoom_out = MapZoomOutButton()
        self.area_map_zoom_out.setVisible(False)
        self.area_map_zoom_in = MapZoomInButton()
        self.area_map_zoom_in.setVisible(False)
        self.area_map_expand = MapExpandButton()
        self.area_map_expand.setVisible(False)
        self.area_search_toolbar_spacer = QWidget()
        self.area_search_toolbar_spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.area_search_toolbar_spacer.setVisible(False)
        area_search_layout.addWidget(self.area_map_zoom_out, 0)
        area_search_layout.addWidget(self.area_map_zoom_in, 0)
        area_search_layout.addWidget(self.area_map_expand, 0)
        area_search_layout.addWidget(self.area_search_toolbar_spacer, 1)
        self.open_map_button = QPushButton("Open map")
        self.open_map_button.setObjectName("toolbarButton")
        self.open_map_button.setCursor(Qt.PointingHandCursor)
        self.open_map_button.setFixedHeight(34)
        self.open_map_button.setToolTip("Open a map view for selecting cells.")
        self.open_map_button.setVisible(False)
        self.close_map_button = QPushButton("Close map")
        self.close_map_button.setObjectName("toolbarButton")
        self.close_map_button.setCursor(Qt.PointingHandCursor)
        self.close_map_button.setFixedHeight(34)
        self.close_map_button.setToolTip("Close the map and return to the area list.")
        self.close_map_button.setVisible(False)
        map_btn_w = max(self.open_map_button.sizeHint().width(), self.close_map_button.sizeHint().width()) + 20
        self.open_map_button.setFixedWidth(map_btn_w)
        self.close_map_button.setFixedWidth(map_btn_w)
        area_search_layout.addWidget(self.open_map_button, 0)
        area_search_layout.addWidget(self.close_map_button, 0)

        self.areas_panel = QFrame()
        self.areas_panel.setObjectName("subCard")
        self.areas_panel.setFrameShape(QFrame.StyledPanel)
        areas_layout = QVBoxLayout(self.areas_panel)
        areas_layout.setContentsMargins(10, 10, 10, 10)
        areas_layout.setSpacing(8)
        self.area_heading = QWidget()
        area_heading_layout = QHBoxLayout(self.area_heading)
        area_heading_layout.setContentsMargins(0, 0, 0, 0)
        area_heading_layout.setSpacing(6)
        self.area_label = SelectableLabel("Areas")
        self.area_count_label = SelectableLabel("")
        self.area_count_label.setObjectName("secondaryHeaderLabel")
        area_heading_layout.addWidget(self.area_label)
        area_heading_layout.addWidget(self.area_count_label)
        area_heading_layout.addStretch(1)
        self.area_header = QWidget()
        area_header_layout = QHBoxLayout(self.area_header)
        area_header_layout.setContentsMargins(0, 0, 9, 0)
        area_header_layout.setSpacing(0)
        self.area_all_checkbox = HeaderCheckBox()
        self.area_all_checkbox.setTristate(True)
        self.area_all_checkbox.setToolTip("Select all")
        self.area_all_checkbox.setCursor(Qt.PointingHandCursor)
        self.area_all_checkbox.setFixedWidth(28)
        self.area_code_header = QPushButton("Code")
        self.area_name_header = QPushButton("Name")
        self.area_code_header.setObjectName("areaHeaderButton")
        self.area_name_header.setObjectName("areaHeaderButton")
        self.area_code_header.setCursor(Qt.PointingHandCursor)
        self.area_name_header.setCursor(Qt.PointingHandCursor)
        self.area_code_header.setFixedWidth(_AREA_CODE_COLUMN_W)
        self.area_name_header.setMinimumWidth(80)
        area_header_layout.addWidget(self.area_all_checkbox)
        area_header_layout.addWidget(self.area_code_header)
        area_header_layout.addWidget(self.area_name_header, 1)

        self.area_view = CopyableTreeView()
        self.area_view.setEditTriggers(QListView.NoEditTriggers)
        self.area_view.setSelectionMode(QListView.NoSelection)
        self.area_view.setSelectionBehavior(QTreeView.SelectRows)
        self.area_view.setObjectName("areaView")
        self.area_view.setRootIsDecorated(False)
        self.area_view.setIndentation(0)
        self.area_view.setAlternatingRowColors(False)
        self.area_view.header().hide()
        self.area_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.area_view.setColumnWidth(0, _AREA_CHECKBOX_COLUMN_W)
        self.area_view.setColumnWidth(1, _AREA_CODE_COLUMN_W)
        self.area_view.setTextElideMode(Qt.ElideRight)
        self.area_view.installEventFilter(self)
        self.area_view.viewport().installEventFilter(self)

        self.area_list_section = QWidget()
        self.area_list_section.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        area_list_layout = QVBoxLayout(self.area_list_section)
        area_list_layout.setContentsMargins(0, 0, 0, 0)
        area_list_layout.setSpacing(8)
        area_list_layout.addWidget(self.area_header)
        area_list_layout.addWidget(self.area_view, 1)

        self.area_map_picker = MapPickerWidget()
        self.area_map_picker.setVisible(False)

        self.area_stack = QStackedWidget()
        self.area_stack.addWidget(self.area_list_section)
        self.area_stack.addWidget(self.area_map_picker)

        self.area_panel_fill = QWidget()
        self.area_panel_fill.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        areas_layout.addWidget(self.area_heading)
        areas_layout.addWidget(self.area_type_widget)
        areas_layout.addWidget(self.area_search_row)
        areas_layout.addWidget(self.area_stack, 1)
        areas_layout.addWidget(self.area_panel_fill, 1)

        left_layout.addWidget(self.areas_panel, 3)
        left_layout.addWidget(self.categories_panel, 2)

        right_column = QWidget()
        right_layout = QVBoxLayout(right_column)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(10)

        self.datasets_panel = QFrame()
        self.datasets_panel.setObjectName("subCard")
        self.datasets_panel.setFrameShape(QFrame.StyledPanel)
        datasets_layout = QVBoxLayout(self.datasets_panel)
        datasets_layout.setContentsMargins(10, 10, 10, 10)
        datasets_layout.setSpacing(8)

        self.dataset_header = QWidget()
        dataset_header_layout = QHBoxLayout(self.dataset_header)
        dataset_header_layout.setContentsMargins(0, 0, 0, 0)
        dataset_header_layout.setSpacing(6)
        self.dataset_label = SelectableLabel("Datasets")
        self.dataset_header_copy_widget = ClipboardCopyWidget(owner=self)
        self.dataset_header_copy_widget.setObjectName("datasetHeaderCopyCell")
        self.dataset_header_copy_widget.setToolTip("Copy...")
        self.dataset_header_copy_widget.setEnabled(False)
        self.dataset_header_copy_widget.installEventFilter(self)
        self.dataset_count_label = SelectableLabel("(0)")
        self.dataset_count_label.setObjectName("secondaryHeaderLabel")
        self.dataset_page_label = SelectableLabel("")
        self.dataset_page_label.setObjectName("secondaryHeaderLabel")
        self.dataset_prev_button = PagerButton("prev")
        self.dataset_next_button = PagerButton("next")
        dataset_header_layout.addWidget(self.dataset_label)
        dataset_header_layout.addWidget(self.dataset_count_label)
        dataset_header_layout.addWidget(self.dataset_header_copy_widget)
        dataset_header_layout.addSpacing(10)
        dataset_header_layout.addWidget(self.downloadable_filter, 0)
        dataset_header_layout.addStretch(1)
        dataset_header_layout.addWidget(self.dataset_page_label)
        dataset_header_layout.addWidget(self.dataset_prev_button)
        dataset_header_layout.addWidget(self.dataset_next_button)
        self.dataset_search_row = QWidget()
        dataset_search_layout = QHBoxLayout(self.dataset_search_row)
        dataset_search_layout.setContentsMargins(0, 0, 0, 0)
        dataset_search_layout.setSpacing(0)
        self.dataset_search_combo = QWidget()
        self.dataset_search_combo.setObjectName("datasetSearchCombo")
        dataset_search_combo_layout = QHBoxLayout(self.dataset_search_combo)
        dataset_search_combo_layout.setContentsMargins(0, 0, 0, 0)
        dataset_search_combo_layout.setSpacing(0)
        self.dataset_search = DatasetSearchLineEdit()
        self.dataset_search.setPlaceholderText("Search title or UUID")
        self.dataset_search.setFixedHeight(34)
        self.dataset_search.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.dataset_search_button = SearchMagnifyButton()
        self.dataset_search_combo.setFixedHeight(34)
        self.dataset_search.set_search_button(self.dataset_search_button)
        dataset_search_combo_layout.addWidget(self.dataset_search, 1)
        dataset_search_combo_layout.addWidget(self.dataset_search_button, 0)
        dataset_search_layout.addWidget(self.dataset_search_combo, 1)
        self.dataset_view = DatasetTreeView()
        self.dataset_view.setObjectName("datasetView")
        self.dataset_view.setEditTriggers(QListView.NoEditTriggers)
        self.dataset_view.setSelectionMode(QListView.SingleSelection)
        self.dataset_view.setSelectionBehavior(QTreeView.SelectItems)
        self.dataset_view.setFocusPolicy(Qt.StrongFocus)
        self.dataset_view.setRootIsDecorated(False)
        self.dataset_view.header().hide()
        header = self.dataset_view.header()
        header.setStretchLastSection(False)
        for col in (
            DATASET_COL_TITLE,
            DATASET_COL_COPY,
            DATASET_COL_TAGS,
            DATASET_COL_LINK,
        ):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
        self.dataset_view.setTextElideMode(Qt.ElideRight)
        self.dataset_view.setMouseTracking(True)
        self.dataset_view.viewport().setMouseTracking(True)
        datasets_layout.addWidget(self.dataset_header)
        datasets_layout.addWidget(self.dataset_search_row)
        datasets_layout.addWidget(self.dataset_view, 1)

        bottom_right = QWidget()
        br_layout = QHBoxLayout(bottom_right)
        br_layout.setContentsMargins(0, 0, 0, 0)
        br_layout.setSpacing(12)

        projection_column = QWidget()
        projection_column_layout = QVBoxLayout(projection_column)
        projection_column_layout.setContentsMargins(0, 0, 0, 0)
        projection_column_layout.setSpacing(0)

        self.projection_panel = QFrame()
        self.projection_panel.setObjectName("projectionCard")
        self.projection_panel.setFrameShape(QFrame.StyledPanel)
        proj_layout = QVBoxLayout(self.projection_panel)
        proj_layout.setContentsMargins(10, 10, 10, 10)
        proj_layout.setSpacing(8)
        self.projection_header = QWidget()
        projection_header_layout = QHBoxLayout(self.projection_header)
        projection_header_layout.setContentsMargins(0, 0, 0, 0)
        projection_header_layout.setSpacing(6)
        self.projection_label = SelectableLabel("Projection")
        self.projection_count_label = SelectableLabel("(0)")
        self.projection_count_label.setObjectName("secondaryHeaderLabel")
        projection_header_layout.addWidget(self.projection_label)
        projection_header_layout.addWidget(self.projection_count_label)
        projection_header_layout.addStretch(1)
        self.projection_view = CopyableListView()
        self.projection_view.setObjectName("projectionView")
        self.projection_view.setEditTriggers(QListView.NoEditTriggers)
        self.projection_view.setSelectionMode(QListView.SingleSelection)
        self.projection_view.setFocusPolicy(Qt.StrongFocus)
        proj_layout.addWidget(self.projection_header)
        proj_layout.addWidget(self.projection_view)
        projection_column_layout.addWidget(self.projection_panel, 1)

        format_column = QWidget()
        format_column_layout = QVBoxLayout(format_column)
        format_column_layout.setContentsMargins(0, 0, 0, 0)
        format_column_layout.setSpacing(0)
        self.format_panel = QFrame()
        self.format_panel.setObjectName("formatCard")
        self.format_panel.setFrameShape(QFrame.StyledPanel)
        fmt_layout = QVBoxLayout(self.format_panel)
        fmt_layout.setContentsMargins(10, 10, 10, 10)
        fmt_layout.setSpacing(8)
        self.format_header = QWidget()
        format_header_layout = QHBoxLayout(self.format_header)
        format_header_layout.setContentsMargins(0, 0, 0, 0)
        format_header_layout.setSpacing(6)
        self.format_label = SelectableLabel("Format")
        self.format_count_label = SelectableLabel("(0)")
        self.format_count_label.setObjectName("secondaryHeaderLabel")
        format_header_layout.addWidget(self.format_label)
        format_header_layout.addWidget(self.format_count_label)
        format_header_layout.addStretch(1)
        self.format_view = CopyableListView()
        self.format_view.setObjectName("formatView")
        self.format_view.setEditTriggers(QListView.NoEditTriggers)
        self.format_view.setSelectionMode(QListView.SingleSelection)
        self.format_view.setFocusPolicy(Qt.StrongFocus)
        fmt_layout.addWidget(self.format_header)
        fmt_layout.addWidget(self.format_view)
        format_column_layout.addWidget(self.format_panel, 1)

        selected_column = QWidget()
        selected_column_layout = QVBoxLayout(selected_column)
        selected_column_layout.setContentsMargins(0, 0, 0, 0)
        selected_column_layout.setSpacing(10)

        self.selected_panel = QFrame()
        self.selected_panel.setObjectName("selectedDatasetCard")
        self.selected_panel.setFrameShape(QFrame.StyledPanel)
        self.selected_panel.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        selected_layout = QVBoxLayout(self.selected_panel)
        selected_layout.setContentsMargins(10, 8, 10, 8)
        selected_layout.setSpacing(6)
        selected_header = QWidget()
        selected_header_layout = QHBoxLayout(selected_header)
        selected_header_layout.setContentsMargins(0, 0, 0, 0)
        selected_header_layout.setSpacing(6)
        self.selected_label = SelectableLabel("Selected")
        self.clear_all_selections_button = QPushButton("X")
        self.clear_all_selections_button.setObjectName("selectedPanelClearAllButton")
        self.clear_all_selections_button.setToolTip("Clear all selections")
        self.clear_all_selections_button.setCursor(Qt.PointingHandCursor)
        self.clear_all_selections_button.setFixedSize(24, 24)
        self.clear_all_selections_button.setVisible(False)
        self.clear_all_selections_button.clicked.connect(self._clear_all_selections)
        selected_header_layout.addWidget(self.selected_label)
        selected_header_layout.addStretch(1)
        selected_header_layout.addWidget(self.clear_all_selections_button)
        self.selected_rows_host = QWidget()
        self.selected_rows_host.setObjectName("selectedRowsHost")
        self.selected_rows_host.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.selected_rows_host.setMinimumWidth(0)
        self.selected_rows_host.setAttribute(Qt.WA_StyledBackground, True)
        self.selected_rows_layout = QVBoxLayout(self.selected_rows_host)
        self.selected_rows_layout.setContentsMargins(0, 0, 0, 0)
        self.selected_rows_layout.setSpacing(2)
        self.selected_rows_layout.setAlignment(Qt.AlignTop)
        self.selected_scroll = QScrollArea()
        self.selected_scroll.setObjectName("selectedScroll")
        self.selected_scroll.setWidgetResizable(True)
        self.selected_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.selected_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.selected_scroll.setFrameShape(QFrame.NoFrame)
        self.selected_scroll.setAttribute(Qt.WA_StyledBackground, True)
        self.selected_scroll.setMouseTracking(True)
        self.selected_scroll.viewport().setMouseTracking(True)
        self.selected_scroll.installEventFilter(self)
        self._hover_scroll_widgets.append(self.selected_scroll)
        self.selected_scroll.viewport().installEventFilter(self)
        self._hover_scroll_widgets.append(self.selected_scroll.viewport())
        self.selected_scroll.viewport().setObjectName("selectedScrollViewport")
        self.selected_scroll.viewport().setAttribute(Qt.WA_StyledBackground, True)
        self.selected_scroll.setWidget(self.selected_rows_host)
        self.selected_dataset_copy_widget = ClipboardCopyWidget(owner=self)
        self.selected_dataset_copy_widget.setObjectName("selectedDatasetCopyCell")
        self.selected_dataset_copy_widget.setToolTip("Copy...")
        self.selected_dataset_copy_widget.setVisible(False)
        self.selected_dataset_copy_widget.setEnabled(False)
        self.selected_dataset_copy_widget.installEventFilter(self)
        self.selected_dataset_link_widget = ExternalLinkWidget(owner=self)
        self.selected_dataset_link_widget.setObjectName("selectedDatasetLinkCell")
        self.selected_dataset_link_widget.setVisible(False)
        self.selected_dataset_link_widget.setEnabled(False)
        self.selected_dataset_link_widget.installEventFilter(self)
        selected_layout.addWidget(selected_header)
        selected_layout.addWidget(self.selected_scroll, 1)

        self.download_button = QPushButton("Download")
        self.download_button.setObjectName("downloadButton")
        self.download_button.setCursor(Qt.PointingHandCursor)
        self.download_button.setEnabled(False)
        self.download_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.selected_warning_label = QLabel()
        self.selected_warning_label.setObjectName("selectedWarningLabel")
        self.selected_warning_label.setWordWrap(True)
        self.selected_warning_label.hide()
        selected_column_layout.addWidget(self.selected_panel, 1)
        selected_column_layout.addWidget(self.selected_warning_label, 0)
        selected_column_layout.addWidget(self.download_button, 0)

        for column in (projection_column, format_column, selected_column):
            column.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            column.setMinimumWidth(0)
        for panel in (self.projection_panel, self.format_panel):
            panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            panel.setMinimumWidth(0)
        self.selected_panel.setMinimumWidth(0)

        br_layout.addWidget(projection_column, _BOTTOM_PROJECTION_STRETCH)
        br_layout.addWidget(format_column, _BOTTOM_FORMAT_STRETCH)
        br_layout.addWidget(selected_column, _BOTTOM_SELECTED_STRETCH)

        right_layout.addWidget(self.datasets_panel, 3)
        right_layout.addWidget(bottom_right, 2)

        main_layout.addWidget(left_column, 1)
        main_layout.addWidget(right_column, 2)

        outer.addWidget(self.top_toolbar, 0, 0, 1, 2)
        outer.addWidget(self.main_frame, 1, 0, 1, 2)
        outer.setRowStretch(1, 1)

        # Busy overlays (block clicks + match rounded panels)
        self._busy_overlays = [
            BusyOverlay(self.main_frame, radius=10),
        ]
        for overlay in self._busy_overlays:
            overlay.setGeometry(overlay.parentWidget().rect())
            overlay.raise_()
        self.main_frame.installEventFilter(self)

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status_text = SelectableLabel("Loading…")
        self.status_text.setObjectName("statusLabel")
        self.status.addWidget(self.status_text, 1)
        self.copy_status_text = SelectableLabel("")
        self.copy_status_text.setObjectName("copyStatusLabel")
        self.status.addPermanentWidget(self.copy_status_text)

        # Models
        self.area_model = AreaSelectionModel(all_label="All")
        self.area_view.setModel(self.area_model)
        self.area_view.setItemDelegateForColumn(0, CheckBoxDelegate(self))
        self._configure_area_columns()

        self.dataset_model = TwoColumnListModel()
        self.dataset_view.setModel(self.dataset_model)
        self.dataset_view.setItemDelegate(DatasetItemDelegate(self))
        self._configure_dataset_columns()

        self.category_model = SimpleListModel()
        self.category_view.setModel(self.category_model)

        self.projection_model = SimpleListModel()
        self.projection_view.setModel(self.projection_model)
        self.projection_view.setItemDelegate(FilterListItemDelegate(self, kind="projection"))

        self.format_model = SimpleListModel()
        self.format_view.setModel(self.format_model)
        self.format_view.setItemDelegate(FilterListItemDelegate(self, kind="format"))

        for view in (
            self.area_view,
            self.category_view,
            self.dataset_view,
            self.projection_view,
            self.format_view,
        ):
            view.setMouseTracking(True)
            view.viewport().setMouseTracking(True)
            view.viewport().setCursor(Qt.ArrowCursor)
            view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            if isinstance(view, QListView):
                view.setTextElideMode(Qt.ElideRight)
                view.setUniformItemSizes(True)
            view.installEventFilter(self)
            self._hover_scroll_widgets.append(view)
            view.viewport().installEventFilter(self)
            self._hover_scroll_widgets.append(view.viewport())

        clear_list_index_widgets(self.category_view)
        clear_list_index_widgets(self.projection_view)
        clear_list_index_widgets(self.format_view)
        clear_tree_index_widgets(self.area_view, [1, 2])
        clear_dataset_index_widgets(self.dataset_view)

        self._make_labels_selectable(self)
        self._apply_clickable_cursors(self)

        # No top menu bar; toolbar buttons cover refresh and clearing filters.
        self.menuBar().setVisible(False)

    def _apply_style(self) -> None:
        settings = QSettings("Geonorge", "Datasets")
        light = settings.value("ui/light_mode", False, type=bool)
        self._light_mode = bool(light)
        scale_name = str(settings.value("ui/text_scale", default_text_scale_name()) or default_text_scale_name())
        if scale_name not in ("normal", "large"):
            scale_name = default_text_scale_name()
        self._text_scale_name = "normal"
        self._apply_text_scale(scale_name, persist=False)
        self._on_theme_toggle(light, refresh_style=False)

    def _apply_text_scale(self, scale_name: str, *, persist: bool = True) -> None:
        self._text_scale_name = "large" if scale_name == "large" else "normal"
        factor = scale_name_to_factor(self._text_scale_name)
        set_text_scale_factor(factor)
        apply_base_style(ui_scale=factor)
        self.setStyleSheet(build_stylesheet(palette_for(self._light_mode), ui_scale=factor))
        self._apply_scaled_widget_metrics()
        if hasattr(self, "text_scale_normal_button"):
            self.text_scale_normal_button.setEnabled(self._text_scale_name != "normal")
            self.text_scale_large_button.setEnabled(self._text_scale_name != "large")
        if persist:
            QSettings("Geonorge", "Datasets").setValue("ui/text_scale", self._text_scale_name)
        if hasattr(self, "dataset_view"):
            self.dataset_view.viewport().update()
        self._apply_toolbar_fixed_fonts()
        self._apply_clickable_cursors(self)
        self._refresh_text_scale_button_cursors()

    def _refresh_text_scale_button_cursors(self) -> None:
        """Re-apply pointing-hand cursor after scale toggle (stylesheet + enable swap)."""
        for button in (
            getattr(self, "text_scale_normal_button", None),
            getattr(self, "text_scale_large_button", None),
        ):
            if button is None:
                continue
            cursor = Qt.PointingHandCursor if button.isEnabled() else Qt.ArrowCursor
            button.setCursor(cursor)
            if button.underMouse():
                # Qt may keep the old cursor until the pointer leaves and re-enters.
                button.unsetCursor()
                button.setCursor(cursor)

    def _apply_toolbar_fixed_fonts(self) -> None:
        """Top toolbar stays at a fixed size regardless of ui/text_scale."""
        app = QApplication.instance()
        base = QFont(app.font() if app is not None else QFont())
        body = QFont(base)
        body.setPointSize(10)
        for attr in ("refresh_button", "reset_cache_button", "check_updates_button"):
            button = getattr(self, attr, None)
            if button is not None:
                button.setFont(body)
        small = QFont(base)
        small.setPointSize(9)
        large = QFont(base)
        large.setPointSize(15)
        if hasattr(self, "text_scale_normal_button"):
            self.text_scale_normal_button.setText("A")
            self.text_scale_normal_button.setFont(small)
        if hasattr(self, "text_scale_large_button"):
            self.text_scale_large_button.setText("A")
            self.text_scale_large_button.setFont(large)
        if hasattr(self, "theme_toggle"):
            self.theme_toggle.setFont(body)

    def _apply_scaled_widget_metrics(self) -> None:
        search_h = scale_pixels(34, ui_scale=scale_name_to_factor(self._text_scale_name))
        search_btn_w = scale_pixels(38, ui_scale=scale_name_to_factor(self._text_scale_name))
        map_btn_pad = scale_pixels(20, ui_scale=scale_name_to_factor(self._text_scale_name))
        for widget in (
            getattr(self, "dataset_search", None),
            getattr(self, "area_search", None),
            getattr(self, "dataset_search_combo", None),
            getattr(self, "area_search_combo", None),
        ):
            if widget is not None:
                widget.setFixedHeight(search_h)
        for button in (
            getattr(self, "dataset_search_button", None),
            getattr(self, "area_search_button", None),
        ):
            if button is not None:
                button.setFixedSize(search_btn_w, search_h)
        for button in (
            getattr(self, "area_map_zoom_out", None),
            getattr(self, "area_map_zoom_in", None),
            getattr(self, "area_map_expand", None),
            getattr(self, "open_map_button", None),
            getattr(self, "close_map_button", None),
        ):
            if button is not None:
                button.setFixedHeight(search_h)
                if button in (self.open_map_button, self.close_map_button):
                    button.setFixedWidth(max(button.sizeHint().width(), search_h) + map_btn_pad)
                elif hasattr(button, "setFixedSize"):
                    button.setFixedSize(search_h, search_h)

    def _on_text_scale_clicked(self, button_id: int) -> None:
        scale_name = "large" if button_id == 1 else "normal"
        if scale_name == getattr(self, "_text_scale_name", "normal"):
            return
        self._apply_text_scale(scale_name)

    def _on_theme_toggle(self, light_mode: bool, *, refresh_style: bool = True) -> None:
        self._light_mode = bool(light_mode)
        if refresh_style:
            factor = scale_name_to_factor(getattr(self, "_text_scale_name", "normal"))
            self.setStyleSheet(build_stylesheet(palette_for(self._light_mode), ui_scale=factor))
        QSettings("Geonorge", "Datasets").setValue("ui/light_mode", self._light_mode)
        if hasattr(self, "theme_toggle"):
            self.theme_toggle.set_light_mode(self._light_mode)
            border, track, icon = theme_toggle_colors(light_mode=self._light_mode)
            self.theme_toggle.set_colors(border=border, track_bg=track, icon=icon)
        if hasattr(self, "dataset_search_button"):
            self.dataset_search_button.set_light_mode(self._light_mode)
        if hasattr(self, "area_search_button"):
            self.area_search_button.set_light_mode(self._light_mode)
        fill = busy_overlay_fill(light_mode=self._light_mode)
        for overlay in getattr(self, "_busy_overlays", []):
            overlay.set_fill(fill)
        if hasattr(self, "dataset_view"):
            clear_dataset_index_widgets(self.dataset_view)
            self.dataset_view.viewport().update()
        if hasattr(self, "category_view"):
            clear_list_index_widgets(self.category_view)
        if hasattr(self, "projection_view"):
            clear_list_index_widgets(self.projection_view)
        if hasattr(self, "format_view"):
            clear_list_index_widgets(self.format_view)
        if hasattr(self, "area_map_picker"):
            self.area_map_picker.canvas.set_dark_basemap(not self._light_mode)
        if self._area_map_expanded_window is not None:
            factor = scale_name_to_factor(getattr(self, "_text_scale_name", "normal"))
            self._area_map_expanded_window.setStyleSheet(
                build_stylesheet(palette_for(self._light_mode), ui_scale=factor)
            )
        if self._download_progress_dialog is not None:
            self._download_progress_dialog.apply_theme(light_mode=self._light_mode)
        if hasattr(self, "area_view"):
            clear_tree_index_widgets(
                self.area_view,
                [1] if self._area_display_name_only else [1, 2],
            )
        self._apply_clickable_cursors(self)

    def _wire_events(self) -> None:
        self.area_type_group.buttonClicked.connect(self._on_area_type_button_clicked)
        self.area_model.selection_changed.connect(self._on_areas_changed)
        self.area_all_checkbox.clicked.connect(self._on_area_all_clicked)
        self.area_code_header.clicked.connect(lambda: self._on_area_sort_requested("code"))
        self.area_name_header.clicked.connect(lambda: self._on_area_sort_requested("name"))
        self.area_view.clicked.connect(self._on_area_cell_clicked)
        self.downloadable_filter.stateChanged.connect(self._on_downloadable_filter_changed)
        self.category_view.selectionModel().selectionChanged.connect(self._on_category_selection_changed)
        self.dataset_search.returnPressed.connect(self._apply_dataset_search)
        self.dataset_search.textChanged.connect(self._on_dataset_search_text_changed)
        self.dataset_search_button.clicked.connect(self._apply_dataset_search)
        self.area_search.returnPressed.connect(self._apply_area_search)
        self.area_search.textChanged.connect(self._on_area_search_text_changed)
        self.area_search_button.clicked.connect(self._apply_area_search)
        self.open_map_button.clicked.connect(self._open_area_map)
        self.close_map_button.clicked.connect(self._close_area_map)
        self.area_map_zoom_in.clicked.connect(self._on_area_map_zoom_in)
        self.area_map_zoom_out.clicked.connect(self._on_area_map_zoom_out)
        self.area_map_expand.clicked.connect(self._expand_area_map)
        self.area_map_picker.toggled.connect(self._on_area_map_toggled)
        self.dataset_view.clicked.connect(self._on_dataset_clicked)
        self.dataset_view.selectionModel().currentChanged.connect(self._on_dataset_current_changed)
        self.dataset_prev_button.clicked.connect(self._on_dataset_prev_page)
        self.dataset_next_button.clicked.connect(self._on_dataset_next_page)
        self.projection_view.clicked.connect(self._on_projection_clicked)
        self.format_view.clicked.connect(self._on_format_clicked)
        self.refresh_button.clicked.connect(self._refresh_all)
        self.reset_cache_button.clicked.connect(self._reset_cache)
        self.check_updates_button.clicked.connect(self._open_pending_update)
        # Only leaf controls: clicking panel chrome must not trigger busy / disable the whole UI.
        self._filter_busy_widgets = [
            self.downloadable_filter,
            self.category_view,
            self.area_view,
            self.area_search,
            self.area_search_button,
            self.area_type_widget,
            self.area_all_checkbox,
            self.area_code_header,
            self.area_name_header,
            self.projection_view,
            self.format_view,
            self.dataset_view,
            self.dataset_search,
            self.dataset_search_button,
            self.dataset_prev_button,
            self.dataset_next_button,
        ]
        self._filter_busy_widget_set = set(self._filter_busy_widgets)
        for widget in self._filter_busy_widgets:
            widget.installEventFilter(self)
            viewport = getattr(widget, "viewport", None)
            if callable(viewport):
                widget.viewport().installEventFilter(self)
        self.theme_toggle.light_mode_changed.connect(lambda light: self._on_theme_toggle(light))
        self.text_scale_group.idClicked.connect(self._on_text_scale_clicked)
        self.download_button.clicked.connect(self._start_download_flow)
        self._update_area_details_visibility()

    def _set_toolbar_busy(self, *, refresh: bool | None = None, reset: bool | None = None) -> None:
        if refresh is not None:
            self._refresh_busy = refresh
        if reset is not None:
            self._reset_busy = reset
        busy = self._refresh_busy or self._reset_busy
        self.refresh_button.setEnabled(not busy)
        self.reset_cache_button.setEnabled(not busy)

    def _object_under_filter_busy(self, obj: object) -> bool:
        if self._filter_busy_depth <= 0:
            return False
        widget = obj if isinstance(obj, QWidget) else None
        if widget is None:
            return False
        current: QWidget | None = widget
        while current is not None:
            if current in self._filter_busy_widget_set:
                return True
            current = current.parentWidget()
        return False

    def _object_in_filter_widgets(self, obj: object) -> bool:
        widget = obj if isinstance(obj, QWidget) else None
        if widget is None:
            return False
        current: QWidget | None = widget
        while current is not None:
            if current in self._filter_busy_widget_set:
                return True
            current = current.parentWidget()
        return False

    def eventFilter(self, obj, event) -> bool:
        has_dataset_view = hasattr(self, "dataset_view")
        if event.type() == QEvent.Type.Resize:
            # Keep busy overlays covering their parent panels.
            for overlay in self._busy_overlays:
                if obj is overlay.parentWidget():
                    overlay.setGeometry(overlay.parentWidget().rect())
                    overlay.raise_()
                    break
            if has_dataset_view and obj is self.dataset_view.viewport():
                QTimer.singleShot(0, self._configure_dataset_columns)
            if hasattr(self, "area_view") and obj is self.area_view.viewport():
                QTimer.singleShot(0, self._configure_area_columns)

        if self._object_under_filter_busy(obj) and event.type() in (
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonRelease,
            QEvent.Type.MouseButtonDblClick,
            QEvent.Type.Wheel,
            QEvent.Type.KeyPress,
            QEvent.Type.KeyRelease,
        ):
            return True

        if isinstance(obj, QLabel) and event.type() == QEvent.Type.KeyPress:
            flags = obj.textInteractionFlags()
            if flags & Qt.TextInteractionFlag.TextSelectableByMouse:
                if event.matches(QKeySequence.StandardKey.Copy):
                    selected = obj.selectedText()
                    if selected:
                        QApplication.clipboard().setText(selected)
                        return True
                if event.modifiers() & Qt.KeyboardModifier.ShiftModifier and event.key() in (
                    Qt.Key.Key_Left,
                    Qt.Key.Key_Right,
                    Qt.Key.Key_Home,
                    Qt.Key.Key_End,
                ) and hasattr(obj, "_extend_selection_with_shift"):
                    obj._extend_selection_with_shift(event.key())  # type: ignore[attr-defined]
                    return True

        selected_copy = getattr(self, "selected_dataset_copy_widget", None)
        if event.type() == QEvent.MouseButtonPress:
            view = obj.parent() if hasattr(obj, "parent") and obj.parent() in self._hover_scroll_widgets else obj
            if view in (
                getattr(self, "dataset_view", None),
                getattr(self, "projection_view", None),
                getattr(self, "format_view", None),
            ):
                self._mouse_selecting = True
                QTimer.singleShot(250, lambda: setattr(self, "_mouse_selecting", False))

        if has_dataset_view and obj is self.dataset_view.viewport() and event.type() == QEvent.MouseButtonPress:
            index = self.dataset_view.indexAt(event.pos())
            if index.isValid() and index.column() == DATASET_COL_COPY:
                self._show_dataset_copy_menu(index)
                return True
            if index.isValid() and index.column() == DATASET_COL_LINK:
                ds = self.dataset_model.selected_payload(index)
                if isinstance(ds, DatasetAvailability):
                    self._open_dataset_in_browser(ds)
                return True
            if index.isValid() and index.column() != DATASET_COL_TITLE:
                return True

        selected_link = getattr(self, "selected_dataset_link_widget", None)
        if selected_link is not None and obj is selected_link and event.type() == QEvent.MouseButtonPress:
            if self._selected_dataset:
                self._open_dataset_in_browser(self._selected_dataset)
            return True

        if selected_copy is not None and obj is selected_copy and event.type() == QEvent.MouseButtonPress:
            if self._selected_dataset:
                self._show_selected_dataset_copy_menu()
            return True

        header_copy = getattr(self, "dataset_header_copy_widget", None)
        if header_copy is not None and obj is header_copy and event.type() == QEvent.MouseButtonPress:
            if header_copy.isEnabled():
                self._show_datasets_header_copy_menu()
            return True

        if selected_copy is not None and obj is selected_copy:
            if event.type() == QEvent.Enter:
                self._copy_menu_close_timer.stop()
            elif event.type() == QEvent.Leave:
                self._copy_menu_close_timer.start(2000)

        if header_copy is not None and obj is header_copy:
            if event.type() == QEvent.Enter:
                self._copy_menu_close_timer.stop()
            elif event.type() == QEvent.Leave:
                self._copy_menu_close_timer.start(2000)

        if event.type() == QEvent.MouseMove:
            if has_dataset_view and obj is self.dataset_view.viewport():
                self._handle_dataset_hover(event.pos())
            elif obj in self._hover_scroll_widgets:
                self._update_view_cursor(obj, event.pos())

        if obj is self._dataset_copy_menu:
            if event.type() == QEvent.Enter:
                self._copy_menu_close_timer.stop()
            elif event.type() == QEvent.Leave:
                self._copy_menu_close_timer.start(2000)
                QToolTip.hideText()
            elif event.type() == QEvent.MouseMove:
                menu = self._dataset_copy_menu
                if menu is not None:
                    action = menu.actionAt(event.pos())
                    tip = action.toolTip() if action is not None else ""
                    if tip:
                        QToolTip.showText(QCursor.pos(), tip, menu)
                    else:
                        QToolTip.hideText()
            elif event.type() == QEvent.Hide:
                QToolTip.hideText()

        if obj in self._hover_scroll_widgets:
            view = obj.parent() if hasattr(obj, "parent") and obj.parent() in self._hover_scroll_widgets else obj
            if event.type() == QEvent.Enter and hasattr(view, "setVerticalScrollBarPolicy"):
                view.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
                view.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            elif event.type() == QEvent.Leave and hasattr(view, "setVerticalScrollBarPolicy"):
                if not view.rect().contains(view.mapFromGlobal(QCursor.pos())):
                    view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                    view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                    view.viewport().setCursor(Qt.ArrowCursor)
                if has_dataset_view and view is self.dataset_view:
                    self._clear_dataset_hover()
        return super().eventFilter(obj, event)

    def _update_view_cursor(self, obj, pos) -> None:
        view = obj.parent() if hasattr(obj, "parent") and obj.parent() in self._hover_scroll_widgets else obj
        if not hasattr(view, "indexAt"):
            return
        index = view.indexAt(pos)
        clickable = index.isValid() and self._list_index_is_interactive(view, index)
        if view is self.dataset_view:
            clickable = index.isValid() and index.column() in (
                DATASET_COL_TITLE,
                DATASET_COL_COPY,
                DATASET_COL_LINK,
            )
        view.viewport().setCursor(Qt.PointingHandCursor if clickable else Qt.ArrowCursor)

    def _list_index_is_interactive(self, view, index) -> bool:
        if not index.isValid():
            return False
        model = view.model()
        if model is None:
            return False
        if hasattr(model, "is_row_disabled"):
            return not model.is_row_disabled(index.row())
        if hasattr(model, "item"):
            item = model.item(index.row())
            return item is not None and item.isEnabled()
        return True

    def _handle_dataset_hover(self, pos) -> None:
        index = self.dataset_view.indexAt(pos)
        hover = (index.row(), index.column()) if index.isValid() else None
        if hover != self._dataset_hover:
            self._clear_dataset_hover()
            self._dataset_hover = hover
            self._apply_dataset_hover()
        self._update_view_cursor(self.dataset_view.viewport(), pos)

    def _clear_dataset_hover(self) -> None:
        if self._dataset_hover is None:
            return
        self._dataset_hover = None
        self.dataset_view.viewport().update()

    def _apply_dataset_hover(self) -> None:
        self.dataset_view.viewport().update()

    def _dataset_tags_table_tooltip(self, ds: DatasetAvailability) -> str:
        tags = list(ds.original_categories or ds.categories)
        return "\n".join(tags) if tags else ""

    def _show_dataset_copy_menu(self, index) -> None:
        ds = self.dataset_model.selected_payload(index)
        if not isinstance(ds, DatasetAvailability):
            return
        source = ("cell", index.row(), index.column())
        rect = self.dataset_view.visualRect(index)
        anchor = self.dataset_view.viewport().mapToGlobal(rect.topRight())
        self._open_dataset_copy_menu(ds, source, anchor, to_left=False)

    def _show_selected_dataset_copy_menu(self) -> None:
        ds = self._selected_dataset
        if not isinstance(ds, DatasetAvailability):
            return
        source = "selected_copy"
        rect = self.selected_dataset_copy_widget.rect()
        anchor = self.selected_dataset_copy_widget.mapToGlobal(rect.topLeft())
        self._open_dataset_copy_menu(ds, source, anchor, to_left=True)

    def _show_datasets_header_copy_menu(self) -> None:
        rect = self.dataset_header_copy_widget.rect()
        anchor = self.dataset_header_copy_widget.mapToGlobal(rect.topLeft())
        self._open_datasets_list_copy_menu(anchor)

    def _open_datasets_list_copy_menu(self, anchor_global: QPoint) -> None:
        source_key = "datasets_header"
        if self._dataset_copy_menu is not None and self._dataset_copy_menu.isVisible():
            if self._dataset_copy_menu_source == source_key:
                self._dataset_copy_menu.close()
                return
            self._dataset_copy_menu.close()
        datasets = self._filtered_datasets()
        menu = QMenu(self)
        menu.installEventFilter(self)
        menu.setCursor(Qt.PointingHandCursor)
        menu.setToolTipsVisible(True)
        menu.setAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips, True)
        titles_action = menu.addAction("Titles")
        titles_action.setToolTip("Copy titles to clipboard")
        uuids_action = menu.addAction("UUIDs")
        uuids_action.setToolTip("Copy UUIDs to clipboard")
        combined_action = menu.addAction("Titles (UUIDs)")
        combined_action.setToolTip("Copy titles and UUIDs to clipboard")
        titles_action.triggered.connect(
            lambda _checked=False, items=datasets: self._copy_text_to_clipboard(
                "\n".join(ds.title for ds in items),
                "Copied titles.",
            )
        )
        uuids_action.triggered.connect(
            lambda _checked=False, items=datasets: self._copy_text_to_clipboard(
                "\n".join(ds.metadata_uuid for ds in items),
                "Copied UUIDs.",
            )
        )
        combined_action.triggered.connect(
            lambda _checked=False, items=datasets: self._copy_text_to_clipboard(
                "\n".join(f"{ds.title} ({ds.metadata_uuid})" for ds in items),
                "Copied titles and UUIDs.",
            )
        )
        menu.aboutToHide.connect(self._on_dataset_copy_menu_hidden)
        self._dataset_copy_menu = menu
        self._dataset_copy_menu_source = source_key
        menu.ensurePolished()
        menu.popup(anchor_global)
        self._copy_menu_close_timer.start(2000)

    def _open_dataset_copy_menu(
        self,
        ds: DatasetAvailability,
        source_key: object,
        anchor_global: QPoint,
        *,
        to_left: bool,
    ) -> None:
        if self._dataset_copy_menu is not None and self._dataset_copy_menu.isVisible():
            if self._dataset_copy_menu_source == source_key:
                self._dataset_copy_menu.close()
                return
            self._dataset_copy_menu.close()
        menu = QMenu(self)
        menu.installEventFilter(self)
        menu.setCursor(Qt.PointingHandCursor)
        menu.setToolTipsVisible(True)
        menu.setAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips, True)
        title_action = menu.addAction("Title")
        title_action.setToolTip("Copy title to clipboard")
        uuid_action = menu.addAction("UUID")
        uuid_action.setToolTip("Copy UUID to clipboard")
        title_action.triggered.connect(lambda _checked=False, item=ds: self._copy_text_to_clipboard(item.title, "Copied title."))
        uuid_action.triggered.connect(
            lambda _checked=False, item=ds: self._copy_text_to_clipboard(item.metadata_uuid, f"Copied UUID: {item.metadata_uuid}")
        )
        menu.aboutToHide.connect(self._on_dataset_copy_menu_hidden)
        self._dataset_copy_menu = menu
        self._dataset_copy_menu_source = source_key
        menu.ensurePolished()
        if to_left:
            pos = QPoint(anchor_global.x() - menu.sizeHint().width(), anchor_global.y())
            menu.popup(pos)
        else:
            menu.popup(anchor_global)
        self._copy_menu_close_timer.start(2000)

    def _close_dataset_copy_menu(self) -> None:
        if self._dataset_copy_menu is not None and self._dataset_copy_menu.isVisible():
            self._dataset_copy_menu.close()

    def _on_dataset_copy_menu_hidden(self) -> None:
        self._copy_menu_close_timer.stop()
        self._dataset_copy_menu = None
        self._dataset_copy_menu_source = None

    def _configure_area_columns(self) -> None:
        viewport_w = max(120, self.area_view.viewport().width())
        # Leave a few pixels so column widths never exceed the viewport (no h-scroll).
        slack = self.area_view.frameWidth() * 2 + 3
        usable = max(56, viewport_w - slack)
        checkbox_w = _AREA_CHECKBOX_COLUMN_W
        code_w = _AREA_CODE_COLUMN_W
        self.area_view.setColumnWidth(0, checkbox_w)
        if self.area_model.uses_name_only_column():
            if self.area_model.columnCount() > 1:
                self.area_view.setColumnWidth(1, max(56, usable - checkbox_w))
        else:
            self.area_view.setColumnWidth(1, code_w)
            if self.area_model.columnCount() > 2:
                self.area_view.setColumnWidth(2, max(56, usable - checkbox_w - code_w))

    def _configure_dataset_columns(self) -> None:
        """Size columns so the link column sits flush with the view's right edge."""
        viewport_w = max(200, self.dataset_view.viewport().width())
        copy_w = 34
        link_w = 34
        remaining = max(120, viewport_w - copy_w - link_w)
        title_w = max(160, int(remaining * 0.55))
        tags_w = max(80, remaining - title_w)
        self.dataset_view.setColumnWidth(DATASET_COL_COPY, copy_w)
        self.dataset_view.setColumnWidth(DATASET_COL_LINK, link_w)
        self.dataset_view.setColumnWidth(DATASET_COL_TITLE, title_w)
        self.dataset_view.setColumnWidth(DATASET_COL_TAGS, tags_w)

    def _make_labels_selectable(self, root: QWidget) -> None:
        for label in root.findChildren(QLabel):
            if isinstance(label, (ElidedLabel, SelectableLabel)):
                continue
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            label.setFocusPolicy(Qt.ClickFocus)
            label.setCursor(Qt.IBeamCursor)
            label.installEventFilter(self)

    def _apply_clickable_cursors(self, root: QWidget | None = None) -> None:
        root = root or self
        for widget in root.findChildren(QWidget):
            if isinstance(widget, (QPushButton, QToolButton, QRadioButton, QCheckBox)):
                widget.setCursor(Qt.PointingHandCursor if widget.isEnabled() else Qt.ArrowCursor)
        self.dataset_search.setCursor(Qt.IBeamCursor)
        self.area_search.setCursor(Qt.IBeamCursor)

    @staticmethod
    def _area_type_shows_area_list(area_type: AreaType | None) -> bool:
        return area_type is not None and area_type != "landsdekkende"

    def _area_populate_context_key(self, area_type: AreaType | None) -> tuple[str | None, AreaType | None]:
        ds_uuid = self._selected_dataset.metadata_uuid if self._selected_dataset else None
        return (ds_uuid, area_type)

    def _area_search_input_active(self) -> bool:
        area_type = self._active_area_type()
        if self._area_map_is_inline() or not self._area_type_shows_area_list(area_type):
            return False
        return len(self._candidate_areas(area_type)) >= _AREA_SEARCH_MIN_OPTIONS

    def _reconcile_area_search_with_candidates(self, all_areas: list[AreaOption]) -> None:
        if len(all_areas) < _AREA_SEARCH_MIN_OPTIONS:
            self._clear_area_search_filter()
            return
        committed = self._area_search_text
        if committed and self.area_search.text().strip() != committed:
            self.area_search.blockSignals(True)
            try:
                self.area_search.setText(committed)
            finally:
                self.area_search.blockSignals(False)

    def _area_list_content_signature(
        self,
        area_type: AreaType,
        display_areas: list[AreaOption],
        *,
        truncated: bool,
        filtered_total: int,
        disabled_keys: set[str] | None = None,
    ) -> tuple:
        ds_key = self._selected_dataset.metadata_uuid if self._selected_dataset else ""
        disabled_part = tuple(sorted(disabled_keys or []))
        if truncated:
            return ("truncated", ds_key, area_type, filtered_total, self._area_search_text, disabled_part)
        return ("full", ds_key, area_type, tuple((a.code, a.name) for a in display_areas), disabled_part)

    def _set_area_search_text(self, text: str) -> None:
        normalized = text.strip()
        if normalized == self._area_search_text:
            return
        self._area_search_text = normalized
        self._update_selected_panel()
        if not self._recompute_running and self._area_search_input_active():
            self._populate_areas_for_type(self._active_area_type(), preserve_selection=True)

    def _clear_area_search_filter(self, *, block_field_signals: bool = False) -> None:
        if not self._area_search_text and not self.area_search.text():
            return
        self._area_search_text = ""
        if block_field_signals:
            self.area_search.blockSignals(True)
        try:
            self.area_search.clear()
        finally:
            if block_field_signals:
                self.area_search.blockSignals(False)
        self._update_selected_panel()
        if not self._recompute_running and self._area_search_input_active():
            self._populate_areas_for_type(self._active_area_type(), preserve_selection=True)

    def _discard_area_search_if_hidden(self) -> None:
        if self._area_search_input_active():
            return
        self._clear_area_search_filter()

    def _entire_country_selection(
        self,
        areas: list[AreaOption],
        *,
        preserve_selection: bool,
    ) -> list[AreaOption]:
        if preserve_selection and self._selected_areas:
            valid_codes = {a.code for a in areas}
            kept = [a for a in self._selected_areas if a.code in valid_codes]
            if kept:
                return kept
        if not areas:
            return []
        if len(areas) == 1:
            return list(areas)
        preferred = next((a for a in areas if a.code == "0000"), None)
        return [preferred] if preferred else [areas[0]]

    def _visible_area_model_codes(self) -> set[str]:
        codes: set[str] = set()
        for row in range(self.area_model.rowCount()):
            item = self.area_model.item(row, 0)
            if not item:
                continue
            key = item.data(Qt.UserRole + 1)
            if isinstance(key, str):
                codes.add(key)
        return codes

    def _apply_model_checks_to_selected_areas(self) -> None:
        visible = self._visible_area_model_codes()
        visible_checked: list[AreaOption] = []
        for payload in self.area_model.checked_payloads():
            if isinstance(payload, AreaOption):
                visible_checked.append(payload)
        self._selected_areas = _merge_area_selection_with_visible_checks(
            self._selected_areas,
            visible_codes=visible,
            visible_checked=visible_checked,
        )

    def _update_area_search_row_visibility(self) -> None:
        map_inline = self._area_map_is_inline()
        show_list_types = self._area_type_shows_area_list(self._active_area_type())
        show_area_search = self._area_search_input_active()
        self.area_search_row.setVisible(map_inline or show_list_types)
        self.area_search_combo.setVisible(show_area_search)
        self.area_map_zoom_out.setVisible(map_inline)
        self.area_map_zoom_in.setVisible(map_inline)
        self.area_map_expand.setVisible(map_inline)
        self.area_search_toolbar_spacer.setVisible(map_inline)
        self._discard_area_search_if_hidden()

    def _update_area_details_visibility(self) -> None:
        shows_list_type = self._area_type_shows_area_list(self._active_area_type())
        map_inline = self._area_map_is_inline()
        show_list = shows_list_type and not map_inline
        self._update_area_search_row_visibility()
        self.area_list_section.setVisible(show_list)
        # Fill spacer is only for non-list area types (e.g. entire country), not inline map.
        self.area_panel_fill.setVisible(not shows_list_type)
        layout = self.areas_panel.layout()
        if layout is not None:
            stack_idx = layout.indexOf(self.area_stack)
            fill_idx = layout.indexOf(self.area_panel_fill)
            if stack_idx >= 0:
                layout.setStretch(stack_idx, 1)
            if fill_idx >= 0:
                layout.setStretch(fill_idx, 1 if not shows_list_type else 0)
        if show_list:
            self.area_code_header.setVisible(not self._area_display_name_only)
        else:
            self.area_code_header.setVisible(False)
        self._sync_area_master_checkbox_visibility()
        self._discard_area_search_if_hidden()

    def _update_area_header_visibility(self) -> None:
        self._update_area_details_visibility()

    @staticmethod
    def _area_table_name_only(area_type: AreaType | None, areas: list[AreaOption]) -> bool:
        if area_type != "celle" or not areas:
            return False
        return all(a.code.strip() == a.name.strip() for a in areas)

    def _filter_areas_by_search(self, areas: list[AreaOption]) -> list[AreaOption]:
        query = self._area_search_text.strip().casefold()
        if not query:
            return areas
        return [
            area
            for area in areas
            if query in area.code.casefold() or query in area.name.casefold()
        ]

    def _set_status(self, message: str) -> None:
        if message == self._last_progress_message:
            return
        self._last_progress_message = message
        logger.debug("UI status: %s", message)
        self.status_text.setText(message)

    def _invalidate_filter_index(self) -> None:
        self._filter_index = None

    def _ensure_filter_index(self) -> DatasetFilterIndex:
        if self._filter_index is None:
            self._filter_index = DatasetFilterIndex.build(self._datasets)
        return self._filter_index

    def _assign_datasets(self, datasets: list[DatasetAvailability]) -> None:
        self._datasets = datasets
        self._login_required_datasets = [d for d in datasets if d.login_required]
        self._invalidate_filter_index()
        self._category_signature = ()
        self._area_types_signature = ()
        self._rebuild_dataset_index()

    def _compose_filter_mask(self, *, ignore: set[str]) -> int:
        index = self._ensure_filter_index()
        return index.compose_mask(
            search_text=self._dataset_search_text,
            downloadable_only=self._show_only_downloadable,
            selected_uuid=self._selected_dataset.metadata_uuid if self._selected_dataset else None,
            categories=self._selected_categories,
            area_type=self._selected_area_type,
            area_codes={a.code for a in self._selected_areas},
            projection_code=self._selected_projection.code if self._selected_projection else None,
            format_key=_format_filter_key(self._selected_format) if self._selected_format else None,
            ignore=ignore,
        )

    def _active_area_type(self) -> AreaType | None:
        return self._selected_area_type or self._auto_area_type

    def _effective_projection(self) -> ProjectionOption | None:
        return self._selected_projection or self._auto_projection

    def _effective_format(self) -> FormatOption | None:
        return self._selected_format or self._auto_format

    def _effective_areas(self) -> list[AreaOption]:
        if self._selected_areas:
            return list(self._selected_areas)
        return list(self._auto_areas)

    def _dataset_compatibility_mode(self) -> bool:
        return self._selected_dataset is not None

    def _compute_compatibility(self, *, for_ui: bool = True) -> CompatibilityState:
        """Cross-filter lists using user selections only; download uses effective (incl. auto)."""
        if for_ui:
            selected_areas = list(self._selected_areas)
            projection = self._selected_projection
            fmt = self._selected_format
        else:
            selected_areas = self._effective_areas()
            projection = self._effective_projection()
            fmt = self._effective_format()
        return compute_compatibility(
            self._selected_dataset,
            area_type=self._active_area_type(),
            selected_areas=selected_areas,
            projection=projection,
            fmt=fmt,
        )

    def _incompatible_selection_reasons(self) -> list[str]:
        if not self._dataset_compatibility_mode() or not self._active_area_type():
            return []
        download_compat = self._compute_compatibility(for_ui=False)
        return incompatible_selection_reasons(
            download_compat,
            areas=self._effective_areas(),
            projection=self._effective_projection(),
            fmt=self._effective_format(),
        )

    def _clear_all_auto_selections(self) -> None:
        self._auto_projection = None
        self._auto_format = None
        self._auto_area_type = None
        self._auto_areas = []
        self._auto_area_codes = set()

    def _clear_user_area_selection(self) -> None:
        self._selected_area_type = None
        self._selected_areas = []

    def _clear_auto_area_selection(self) -> None:
        self._auto_area_type = None
        self._auto_areas = []
        self._auto_area_codes = set()

    def _promote_auto_area_type_if_user_selected_areas(self) -> bool:
        """When areas are chosen while the type was auto-only, show a normal radio check."""
        if not self._selected_areas or self._selected_area_type is not None or self._auto_area_type is None:
            return False
        self._selected_area_type = self._auto_area_type
        self._auto_area_type = None
        self._auto_areas = []
        self._auto_area_codes = set()
        self._apply_area_type_button_visuals()
        return True

    def _restore_auto_single_area(self) -> bool:
        area_type = self._active_area_type()
        if area_type is None or not self._area_type_shows_area_list(area_type):
            return False
        if self._selected_areas:
            return False
        all_areas = self._sort_areas(self._candidate_areas(area_type))
        areas = self._filter_areas_by_search(all_areas)
        if self._dataset_compatibility_mode():
            areas = [a for a in areas if self._compatibility_state.area_enabled(a)]
        if len(areas) != 1:
            self._auto_areas = []
            self._auto_area_codes = set()
            return False
        single = areas[0]
        self._auto_areas = [single]
        self._auto_area_codes = {single.code}
        self._suppress_area_change = True
        try:
            self.area_model.set_checked_keys(set())
        finally:
            self._suppress_area_change = False
        self.area_view.viewport().update()
        return True

    def _apply_area_type_button_visuals(self) -> None:
        for area_type, button in self.area_type_buttons.items():
            if not button.isVisible():
                button.setProperty("autoSelected", False)
                continue
            is_user = self._selected_area_type == area_type
            is_auto = (
                self._selected_area_type is None
                and self._auto_area_type == area_type
            )
            button.setProperty("autoSelected", is_auto)
            button.style().unpolish(button)
            button.style().polish(button)
            button.blockSignals(True)
            try:
                button.setChecked(is_user or is_auto)
            finally:
                button.blockSignals(False)
        self._sync_area_type_row_height()

    def _sync_area_type_row_height(self) -> None:
        visible = [button for button in self.area_type_buttons.values() if button.isVisible()]
        if not visible:
            self.area_type_widget.setFixedHeight(0)
            return
        self.area_type_widget.setMinimumHeight(0)
        self.area_type_widget.setMaximumHeight(16777215)
        self.area_type_widget.adjustSize()
        height = max(40, self.area_type_widget.sizeHint().height())
        self.area_type_widget.setFixedHeight(height)

    def _start_worker(self, worker: FuncWorker) -> None:
        self._active_workers.append(worker)

        def remove_worker() -> None:
            if worker in self._active_workers:
                self._active_workers.remove(worker)

        worker.signals.finished.connect(remove_worker, Qt.ConnectionType.QueuedConnection)
        QApplication.instance().threadPool().start(worker)  # type: ignore[union-attr]

    def _start_map_grid_worker(self, worker: FuncWorker) -> None:
        """Run map GeoJSON fetch/parse off the global pool so tile jobs cannot starve it."""
        if self._map_grid_pool is None:
            self._map_grid_pool = QThreadPool()
            self._map_grid_pool.setMaxThreadCount(1)
        self._active_workers.append(worker)

        def remove_worker() -> None:
            if worker in self._active_workers:
                self._active_workers.remove(worker)

        worker.signals.finished.connect(remove_worker, Qt.ConnectionType.QueuedConnection)
        self._map_grid_pool.start(worker)

    def _wait_map_grid_workers(self, timeout_ms: int = 10_000) -> None:
        pool = self._map_grid_pool
        if pool is not None:
            pool.waitForDone(timeout_ms)

    def _map_selection_layer(self, ds: DatasetAvailability | None) -> str | None:
        if not ds or not ds.capabilities:
            return None
        return resolve_map_selection_layer(
            map_selection_layer=ds.capabilities.map_selection_layer,
            title=ds.title,
            metadata_uuid=ds.metadata_uuid,
        )

    def _update_open_map_visibility(self) -> None:
        self._update_area_search_row_visibility()
        ds = self._selected_dataset
        layer_id = self._map_selection_layer(ds)
        show = bool(ds and self._active_area_type() == "celle" and layer_id)
        map_open = self._area_map_is_open()
        self.open_map_button.setVisible(show and not map_open)
        self.open_map_button.setEnabled(show and not map_open)
        self.close_map_button.setVisible(show and map_open)
        self.close_map_button.setEnabled(show and map_open)
        if show and layer_id:
            tip = f"Layer: {layer_id}"
            self.open_map_button.setToolTip(f"Open a map view for selecting cells.\n\n{tip}")
            self.close_map_button.setToolTip(f"Close the map and return to the area list.\n\n{tip}")

    def _area_map_supported(self) -> bool:
        ds = self._selected_dataset
        return bool(ds and self._active_area_type() == "celle" and self._map_selection_layer(ds))

    def _refresh_area_map_for_dataset_change(self) -> None:
        if not self._area_map_supported():
            self._close_area_map()
            return
        if self._area_map_is_expanded() and self._selected_dataset and self._area_map_expanded_window:
            self._area_map_expanded_window.setWindowTitle(self._selected_dataset.title)
        self._area_map_reload_pending = self._area_map_is_open()

    def _flush_pending_area_map_reload(self) -> None:
        if not self._area_map_reload_pending:
            return
        if self._recompute_running or self._recompute_timer.isActive():
            return
        if not self._area_map_supported():
            self._area_map_reload_pending = False
            return
        self._area_map_reload_pending = False
        self._open_area_map()

    def _apply_map_grid_result(
        self,
        parsed: object,
        *,
        load_generation: int,
        layer_id: str,
        source_epsg: int | None = None,
    ) -> None:
        if load_generation != self._area_map_load_generation:
            logger.debug("Ignoring stale map grid result for layer %s", layer_id)
            return
        if not self._area_map_is_open():
            return
        ds = self._selected_dataset
        active_layer = self._map_selection_layer(ds)
        if not ds or active_layer != layer_id:
            return
        if not isinstance(parsed, list):
            return
        try:
            self.area_map_picker.apply_parsed_grid(parsed, source_epsg=source_epsg)
        except Exception:
            logger.exception("Failed to apply map grid for layer %s", layer_id)
            return
        self._area_map_parsed = list(parsed) if isinstance(parsed, list) else []
        self._sync_area_map_selection()
        if not self.area_map_picker.canvas._grid_cells:
            logger.warning(
                "Map grid for layer %s is empty after apply (dataset %s)",
                layer_id,
                ds.metadata_uuid,
            )

    @Slot()
    def _flush_pending_area_map_apply(self) -> None:
        pending = self._area_map_pending_apply
        if pending is None:
            return
        if self._recompute_running or self._recompute_timer.isActive():
            QTimer.singleShot(0, self._flush_pending_area_map_apply)
            return
        parsed, load_generation, layer_id, source_epsg = pending
        self._area_map_pending_apply = None
        self._apply_map_grid_result(
            parsed,
            load_generation=load_generation,
            layer_id=layer_id,
            source_epsg=source_epsg,
        )

    def _open_area_map(self) -> None:
        if self._recompute_running or self._recompute_timer.isActive():
            self._area_map_reload_pending = True
            return
        self._wait_map_grid_workers()
        ds = self._selected_dataset
        layer_id = self._map_selection_layer(ds)
        if not ds or self._active_area_type() != "celle" or not layer_id:
            return
        # Invalidate in-flight loads before touching the canvas (prevents stale worker apply).
        self._area_map_load_generation += 1
        load_generation = self._area_map_load_generation
        self._area_map_pending_apply = None

        url = geojson_url_for_map_selection_layer(layer_id)
        if not url:
            box = themed_message_box(
                self,
                title="Map not found",
                text=(
                    f"Could not find map for {ds.title}.\n\n"
                    "Alternative:\n"
                    'Open dataset in browser, click "Last ned" (Download), go to '
                    "https://kartkatalog.geonorge.no/nedlasting, -> "
                    '"Geografisk område" -> "Velg fra kartblad".'
                ),
                icon="warning",
            )
            box.addButton("Close", QMessageBox.RejectRole)
            open_btn = box.addButton("Open in browser", QMessageBox.AcceptRole)
            box.setDefaultButton(open_btn)
            box.exec()
            if box.clickedButton() is open_btn:
                self._open_dataset_in_browser(ds)
            return

        self.area_map_picker.canvas.set_dark_basemap(not self._light_mode)
        self.area_map_picker.canvas.set_basemap_deferred(True)
        candidate_areas = self._candidate_areas("celle")
        allowed_codes = frozenset(a.code for a in candidate_areas) if candidate_areas else None
        selected_codes = frozenset(a.code for a in self._selected_areas)
        self.area_map_picker.canvas.set_selected_codes(set(selected_codes))
        self.area_map_picker.canvas.clear_basemap_tiles()
        self.area_map_picker.canvas.set_grid_cells([])
        if self._area_map_expanded:
            window = self._ensure_expanded_map_window()
            window.attach_map_picker(self.area_map_picker)
            self.area_stack.setCurrentWidget(self.area_list_section)
            window.show()
            window.setWindowTitle(ds.title)
        else:
            self._reparent_map_picker_to_stack()
            self.area_stack.setCurrentWidget(self.area_map_picker)
            self.area_map_picker.setVisible(True)
        self._update_open_map_visibility()
        self._update_area_details_visibility()

        proj_code = self._selected_projection.code if self._selected_projection else None
        source_epsg = infer_source_epsg(layer_id=layer_id, projection_code=proj_code)

        previous_status = self.status_text.text()
        self._set_status("Loading map grid…")

        def work() -> tuple[list, int, str, int | None]:
            text = fetch_text(url)
            parsed = parse_geojson_grid_cells(
                text,
                allowed_codes=allowed_codes,
            )
            if not parsed and allowed_codes:
                logger.info(
                    "Map grid: 0/%d area codes matched GeoJSON for %s; loading full layer",
                    len(allowed_codes),
                    layer_id,
                )
                parsed = parse_geojson_grid_cells(
                    text,
                    allowed_codes=None,
                )
            return parsed, load_generation, layer_id, source_epsg

        def on_result(payload: object) -> None:
            if not isinstance(payload, tuple) or len(payload) != 4:
                logger.warning("Unexpected map grid worker payload: %r", payload)
                return
            parsed, gen, lid, epsg = payload
            self._set_status(previous_status)
            if gen != self._area_map_load_generation:
                logger.debug("Ignoring stale map grid worker result (gen %s)", gen)
                return
            self._apply_map_grid_result(
                parsed,
                load_generation=gen,
                layer_id=lid,
                source_epsg=epsg,
            )

        def on_error(err: str) -> None:
            self._on_background_task_error(str(err))
            self._close_area_map()
            self._set_status(previous_status)

        worker = FuncWorker(work)
        connect_worker_signals(worker, result=on_result, error=on_error)
        self._start_map_grid_worker(worker)

    def _area_map_is_inline(self) -> bool:
        return self.area_stack.currentWidget() is self.area_map_picker

    def _area_map_is_expanded(self) -> bool:
        return self._area_map_expanded and self._area_map_expanded_window is not None

    def _area_map_is_open(self) -> bool:
        return self._area_map_is_inline() or self._area_map_is_expanded()

    def _reparent_map_picker_to_stack(self) -> None:
        picker = self.area_map_picker
        window = self._area_map_expanded_window
        if window is not None:
            window.detach_map_picker()
        if self.area_stack.indexOf(picker) < 0:
            self.area_stack.addWidget(picker)
        picker.setParent(self.area_stack)

    def _ensure_expanded_map_window(self) -> ExpandedAreaMapWindow:
        window = self._area_map_expanded_window
        if window is None:
            window = ExpandedAreaMapWindow(self)
            window.closed_by_user.connect(self._on_expanded_area_map_closed)
            window.zoom_in.connect(self._on_area_map_zoom_in)
            window.zoom_out.connect(self._on_area_map_zoom_out)
            screen = window.screen() or self.screen()
            if screen is not None:
                window.setGeometry(*expanded_map_window_geometry(screen))
            self._area_map_expanded_window = window
        ds = self._selected_dataset
        if ds:
            window.setWindowTitle(ds.title)
        return window

    def _expand_area_map(self) -> None:
        if not self._area_map_is_inline():
            return
        window = self._ensure_expanded_map_window()
        window.attach_map_picker(self.area_map_picker)
        self._area_map_expanded = True
        self.area_stack.setCurrentWidget(self.area_list_section)
        window.show()
        window.raise_()
        window.activateWindow()
        self._update_open_map_visibility()
        self._update_area_details_visibility()
        QTimer.singleShot(0, lambda: self._populate_areas_for_type(self._active_area_type()))

    def _collapse_expanded_map_to_inline(self, *, force: bool = False) -> None:
        if not force and not self._area_map_expanded:
            return
        self._area_map_expanded = False
        self._reparent_map_picker_to_stack()
        self.area_stack.setCurrentWidget(self.area_map_picker)
        self.area_map_picker.setVisible(True)
        self._update_open_map_visibility()
        self._update_area_details_visibility()

    def _on_expanded_area_map_closed(self) -> None:
        if self._area_map_closing:
            return
        if not self._area_map_expanded:
            return
        had_grid = bool(self.area_map_picker.canvas._grid_cells)
        self._area_map_expanded = False
        if had_grid:
            self._collapse_expanded_map_to_inline(force=True)
            QTimer.singleShot(0, lambda: self._populate_areas_for_type(self._active_area_type()))
        else:
            self._update_open_map_visibility()
            self._update_area_details_visibility()

    def _sync_area_map_selection(self) -> None:
        if not self._area_map_is_open():
            return
        candidate_areas = self._candidate_areas("celle")
        canvas = self.area_map_picker.canvas
        maps = match_area_grid_codes(canvas._grid_cells, self._area_map_parsed, candidate_areas)
        self.area_map_picker.set_area_grid_maps(maps)

        disabled_grid: set[str] = set()
        if self._dataset_compatibility_mode():
            compat = self._compatibility_state
            for area in candidate_areas:
                grid_code = maps.area_to_grid.get(area.code)
                if grid_code is None:
                    continue
                if area.code not in compat.enabled_area_codes:
                    disabled_grid.add(grid_code)
        disabled_grid |= set(canvas._grid_cells) - set(maps.grid_to_area)

        canvas.set_disabled_codes(disabled_grid)
        canvas.set_selected_codes(
            {
                maps.area_to_grid[area.code]
                for area in self._selected_areas
                if area.code in maps.area_to_grid
            }
            | {area.code for area in self._selected_areas if area.code in canvas._grid_cells}
        )

    def _close_area_map_if_inappropriate(self) -> None:
        if not self._area_map_is_open():
            return
        ds = self._selected_dataset
        show = ds is not None and self._active_area_type() == "celle" and bool(self._map_selection_layer(ds))
        if not show:
            self._close_area_map()

    def _close_area_map(self) -> None:
        cancel_pending_tooltips()
        was_open = self._area_map_is_open()
        self._area_map_closing = True
        try:
            self._area_map_expanded = False
            if self._area_map_expanded_window is not None:
                self._area_map_expanded_window.hide()
                self._area_map_expanded_window.detach_map_picker()
            self._area_map_load_generation += 1
            self._area_map_reload_pending = False
            self._area_map_pending_apply = None
            self._area_map_parsed = []
            self._wait_map_grid_workers()
            self.area_map_picker.canvas.clear_basemap_tiles()
            self.area_map_picker.canvas.set_grid_cells([])
            self._reparent_map_picker_to_stack()
            self.area_stack.setCurrentWidget(self.area_list_section)
            self.area_map_picker.setVisible(False)
            self._update_open_map_visibility()
            if was_open:
                QTimer.singleShot(0, lambda: self._populate_areas_for_type(self._active_area_type()))
        finally:
            self._area_map_closing = False

    def _on_area_map_zoom_in(self) -> None:
        canvas = self.area_map_picker.canvas
        canvas.set_center(lon=canvas._center_lon, lat=canvas._center_lat, zoom=canvas._zoom + ZOOM_STEP)  # type: ignore[attr-defined]

    def _on_area_map_zoom_out(self) -> None:
        canvas = self.area_map_picker.canvas
        canvas.set_center(lon=canvas._center_lon, lat=canvas._center_lat, zoom=canvas._zoom - ZOOM_STEP)  # type: ignore[attr-defined]

    def _on_area_map_toggled(self, code: str, selected: bool) -> None:
        if self._active_area_type() != "celle":
            return
        if self._dataset_compatibility_mode() and code not in self._compatibility_state.enabled_area_codes:
            return
        candidates = {a.code: a for a in self._candidate_areas("celle")}
        if selected:
            if code in candidates and all(a.code != code for a in self._selected_areas):
                self._selected_areas.append(candidates[code])
        else:
            self._selected_areas = [a for a in self._selected_areas if a.code != code]

        # Sync checkboxes in the list view (if present) and refresh dependent panels.
        self._suppress_area_change = True
        try:
            self.area_model.set_checked_keys({a.code for a in self._selected_areas})
        finally:
            self._suppress_area_change = False
        promoted = self._promote_auto_area_type_if_user_selected_areas()
        self._update_area_all_checkbox()
        self._update_selected_panel()
        self._reset_dataset_page()
        refresh = _REFRESH_AREA_CHECK
        if promoted:
            refresh = frozenset({"selected", "download"})
        self._schedule_recompute_lists(0, refresh=refresh, scope="area_check")

    def _maybe_check_for_updates(self) -> None:
        if self._pending_update_url is not None or self._update_check_inflight:
            return
        token = os.environ.get("GEONORGE_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN")
        self._update_check_inflight = True

        def work():
            return fetch_latest_release(owner=GITHUB_OWNER, repo=GITHUB_REPO, token=token)

        worker = FuncWorker(work)

        def on_result(info) -> None:
            self._update_check_inflight = False
            if is_newer_version(__version__, info.latest_version):
                self._pending_update_url = info.release_url or build_latest_release_web_url(
                    owner=GITHUB_OWNER, repo=GITHUB_REPO
                )
                self.check_updates_button.setVisible(True)
                self._update_check_timer.stop()

        def on_error(err) -> None:
            self._update_check_inflight = False
            logger.debug("Background update check failed: %s", err)

        connect_worker_signals(worker, result=on_result, error=on_error)
        self._start_worker(worker)

    def _open_pending_update(self) -> None:
        url = self._pending_update_url or build_latest_release_web_url(
            owner=GITHUB_OWNER, repo=GITHUB_REPO
        )
        if not url:
            box = themed_message_box(
                self,
                title="Couldn't open release page",
                text="No release URL is available.",
                icon="warning",
            )
            box.setStandardButtons(QMessageBox.Ok)
            box.exec()
            return
        if not QDesktopServices.openUrl(QUrl(url)):
            box = themed_message_box(
                self,
                title="Couldn't open release page",
                text=f"Your system could not open:\n{url}",
                icon="warning",
            )
            box.setStandardButtons(QMessageBox.Ok)
            box.exec()

    def _rebuild_dataset_index(self) -> None:
        self._dataset_index_by_uuid = {d.metadata_uuid: i for i, d in enumerate(self._datasets)}

    def _load_initial_data(self) -> None:
        logger.info("Starting initial data load")
        self.area_model.set_items([])
        self._set_status("Loading dataset list from Geonorge…")

        cached = self._discovery.load_cached()
        if cached:
            self._assign_datasets(cached)
            self._sync_dataset_refs_from_cache()
            self._set_status(
                _status_message(
                    f"Loaded {len(self._datasets)} datasets from cache",
                    "Refreshing in background",
                )
            )
        self._schedule_recompute_lists(0)

        worker = FuncWorker(lambda: self._discovery.fetch_dataset_refs(text="", max_results=10000))
        connect_worker_signals(
            worker,
            result=self._on_dataset_refs_loaded,
            error=self._on_background_task_error,
        )
        self._start_worker(worker)

    def _sync_dataset_refs_from_cache(self) -> None:
        self._dataset_refs = [DatasetRef(metadata_uuid=d.metadata_uuid, title=d.title) for d in self._datasets]

    def _populate_area_type_list(self) -> None:
        available = tuple(self._available_area_types_for_selected_dataset())
        repopulated = available != self._area_types_signature
        if repopulated:
            self._area_types_signature = available
            self._auto_area_type = None
            if self._selected_area_type and self._selected_area_type not in available:
                self._selected_area_type = None
                self._selected_areas = []
                self._auto_areas = []
                self._auto_area_codes = set()
            self._area_signature = ()
            self._area_populate_context = None
        for area_type, button in self.area_type_buttons.items():
            visible = area_type in available
            button.setVisible(visible)
            button.setEnabled(visible)
            button.setToolTip("" if visible else "This area type is not available for the selected dataset.")
        if repopulated and self._selected_area_type is None:
            if self._selected_dataset is not None and len(available) == 1:
                self._auto_area_type = available[0]
            else:
                self._auto_area_type = None
        self._apply_area_type_button_visuals()
        self._update_area_details_visibility()

    def _available_area_types_for_selected_dataset(self) -> list[AreaType]:
        if not self._selected_dataset:
            index = self._ensure_filter_index()
            mask = self._compose_filter_mask(ignore={"area_type", "areas"})
            available = index.area_types_for_mask(mask)
            if not available and self._datasets:
                return list(AREA_TYPE_ORDER)
            return available
        return [area_type for area_type in AREA_TYPE_ORDER if self._selected_dataset.areas_by_type.get(area_type)]

    def _dataset_is_downloadable(self, ds: DatasetAvailability) -> bool:
        return bool(ds.formats) and not ds.login_required

    def _dataset_can_open_in_browser(self, ds: DatasetAvailability) -> bool:
        return ds.enriched and not ds.login_required and not ds.formats

    def _dataset_metadata_url(self, ds: DatasetAvailability) -> str:
        slug = re.sub(r"[^0-9a-zA-ZæøåÆØÅ]+", "-", ds.title).strip("-").lower()
        return f"https://kartkatalog.geonorge.no/metadata/{quote(slug)}/{ds.metadata_uuid}"

    def _open_dataset_in_browser(self, ds: DatasetAvailability) -> None:
        QDesktopServices.openUrl(QUrl(self._dataset_metadata_url(ds)))

    def _candidate_categories(self) -> list[str]:
        index = self._ensure_filter_index()
        mask = self._compose_filter_mask(ignore={"category"})
        return sorted(index.categories_for_mask(mask), key=_norwegian_sort_key)

    def _category_original_tags(self, category: str) -> list[str]:
        index = self._ensure_filter_index()
        mask = self._compose_filter_mask(ignore={"category"})
        return sorted(index.category_tags_for_mask(category, mask), key=_norwegian_sort_key)

    def _dataset_original_category_label(self, ds: DatasetAvailability) -> str:
        return ", ".join(ds.original_categories or ds.categories)

    def _candidate_areas(self, area_type: AreaType) -> list[AreaOption]:
        if self._selected_dataset:
            return list(self._selected_dataset.areas_by_type.get(area_type, []))
        index = self._ensure_filter_index()
        mask = self._compose_filter_mask(ignore={"areas"})
        return index.areas_for_mask(area_type, mask)

    def _candidate_projections(self) -> list[ProjectionOption]:
        if self._selected_dataset and self._selected_dataset.projections:
            return sorted(self._selected_dataset.projections, key=lambda p: _code_sort_key(p.code))
        index = self._ensure_filter_index()
        mask = self._compose_filter_mask(ignore={"projection"})
        return sorted(index.projections_for_mask(mask), key=lambda p: _code_sort_key(p.code))

    def _candidate_formats(self) -> list[FormatOption]:
        if self._selected_dataset and self._selected_dataset.formats:
            seen: dict[str, FormatOption] = {}
            for f in self._selected_dataset.formats:
                seen.setdefault(_format_filter_key(f), f)
            return sorted(seen.values(), key=lambda f: _norwegian_sort_key(f.label))
        index = self._ensure_filter_index()
        mask = self._compose_filter_mask(ignore={"format"})
        return sorted(index.formats_for_mask(mask), key=lambda f: _norwegian_sort_key(f.label))

    def _validate_selections(self) -> None:
        if self._selected_dataset:
            uuid = self._selected_dataset.metadata_uuid
            still_present = next(
                (d for d in self._datasets if d.metadata_uuid == uuid),
                None,
            )
            if still_present is None or still_present.login_required:
                self._selected_dataset = None
            else:
                self._selected_dataset = still_present
        if self._selected_dataset:
            available_types = self._available_area_types_for_selected_dataset()
            if self._selected_area_type and self._selected_area_type not in available_types:
                self._selected_area_type = None
                self._selected_areas = []
                self._area_signature = ()
        if self._selected_categories:
            self._selected_categories &= set(self._candidate_categories())
        if self._selected_area_type:
            if self._selected_dataset:
                valid_codes = {a.code for a in self._selected_dataset.areas_by_type.get(self._selected_area_type, [])}
            else:
                index = self._ensure_filter_index()
                mask = self._compose_filter_mask(ignore={"areas"})
                valid_codes = index.area_codes_for_mask(self._selected_area_type, mask)
            self._selected_areas = [a for a in self._selected_areas if a.code in valid_codes]
        elif not self._auto_area_type:
            self._selected_areas = []
        if self._selected_projection:
            if not any(p.code == self._selected_projection.code for p in self._candidate_projections()):
                self._selected_projection = None
        if self._selected_format:
            target = _format_filter_key(self._selected_format)
            if not any(_format_filter_key(f) == target for f in self._candidate_formats()):
                self._selected_format = None
        if self._auto_projection:
            if not any(p.code == self._auto_projection.code for p in self._candidate_projections()):
                self._auto_projection = None
        if self._auto_format:
            target = _format_filter_key(self._auto_format)
            if not any(_format_filter_key(f) == target for f in self._candidate_formats()):
                self._auto_format = None
        if self._auto_area_type:
            available_types = self._available_area_types_for_selected_dataset()
            if self._auto_area_type not in available_types:
                self._auto_area_type = None
        if self._auto_areas and self._auto_area_type:
            if self._selected_dataset:
                valid_codes = {
                    a.code for a in self._selected_dataset.areas_by_type.get(self._auto_area_type, [])
                }
            else:
                index = self._ensure_filter_index()
                mask = self._compose_filter_mask(ignore={"areas"})
                valid_codes = index.area_codes_for_mask(self._auto_area_type, mask)
            self._auto_areas = [a for a in self._auto_areas if a.code in valid_codes]
            self._auto_area_codes = {a.code for a in self._auto_areas}

    def _sync_compatibility_state(self) -> None:
        """Recompute list cross-filters from explicit user selections (not auto-selections)."""
        self._compatibility_state = self._compute_compatibility(for_ui=True)
        if not self._dataset_compatibility_mode() or not self._active_area_type():
            return
        compat = self._compatibility_state
        if self._selected_projection and not compat.projection_enabled(self._selected_projection):
            self._selected_projection = None
        if self._selected_format and not compat.format_enabled(self._selected_format):
            self._selected_format = None
        enabled_area_codes = compat.enabled_area_codes
        self._selected_areas = [a for a in self._selected_areas if a.code in enabled_area_codes]

    def _begin_filter_panel_busy(self) -> None:
        cancel_pending_tooltips()
        self._filter_busy_depth += 1
        if self._filter_busy_depth != 1:
            return
        for widget in self._filter_busy_widgets:
            set_filter_busy_flag(widget, True)
        for overlay in self._busy_overlays:
            overlay.setGeometry(overlay.parentWidget().rect())
            overlay.show()
            overlay.raise_()
        for overlay in self._busy_overlays:
            overlay.repaint()
        QApplication.setOverrideCursor(Qt.WaitCursor)

    def _end_filter_panel_busy(self) -> None:
        if self._filter_busy_depth <= 0:
            return
        self._filter_busy_depth -= 1
        if self._filter_busy_depth != 0:
            return
        QApplication.restoreOverrideCursor()
        for widget in self._filter_busy_widgets:
            set_filter_busy_flag(widget, False)
        for overlay in self._busy_overlays:
            overlay.hide()

    def _recompute_lists(self) -> None:
        t0 = time.perf_counter()
        self._recompute_running = True
        refresh = self._pending_refresh or _REFRESH_ALL
        self._pending_refresh = frozenset()
        scope = self._recompute_scope
        self._recompute_scope = "full"
        try:
            if self._profile_ui:
                logger.info("UI recompute start scope=%s refresh=%s", scope, ",".join(sorted(refresh)))
            if self._selected_dataset:
                self._populate_area_type_list()
            self._validate_selections()
            if "categories" in refresh:
                self._populate_categories()
            if "datasets" in refresh:
                self._apply_dataset_filter()
            if "area_types" in refresh and not self._selected_dataset:
                self._populate_area_type_list()
            if refresh.intersection({"areas", "projections", "formats", "selected", "download"}):
                self._sync_compatibility_state()
            if "areas" in refresh and not self._area_map_is_inline():
                self._populate_areas_for_type(self._active_area_type(), preserve_selection=True)
            if refresh.intersection({"projections", "formats", "selected", "download"}):
                self._sync_compatibility_state()
            if "projections" in refresh:
                self._populate_projections()
            if "formats" in refresh:
                self._populate_formats()
            if "selected" in refresh:
                self._update_selected_panel()
            if "download" in refresh:
                self._update_download_button_state()
            if self._area_map_is_open():
                self._sync_area_map_selection()
        finally:
            self._recompute_running = False
            self._end_filter_panel_busy()
            if self._pending_area_change:
                self._pending_area_change = False
                self._on_areas_changed()
            if self._area_map_reload_pending:
                QTimer.singleShot(0, self._flush_pending_area_map_reload)
            if self._profile_ui:
                dt_ms = (time.perf_counter() - t0) * 1000.0
                logger.info("UI recompute end %.1fms scope=%s", dt_ms, scope)

    def _schedule_recompute_lists(
        self,
        delay_ms: int = 0,
        *,
        scope: str = "full",
        refresh: frozenset[str] | None = None,
    ) -> None:
        if refresh is not None:
            panels = refresh
        elif scope == "full":
            panels = _REFRESH_ALL
        else:
            panels = _REFRESH_FILTER_IMPACT
        self._pending_refresh |= panels
        if scope == "full":
            self._recompute_scope = "full"
        elif self._recompute_scope != "full":
            self._recompute_scope = scope
        if self._recompute_timer.isActive():
            delay_ms = max(delay_ms, 80 if scope == "full" else 120)
        # Keep filter panels interactive while background metadata enrichment runs.
        if self._filter_busy_depth == 0 and scope == "full" and not self._bulk_enrichment:
            self._begin_filter_panel_busy()
        self._recompute_timer.start(max(0, delay_ms))

    def _make_selected_clear_button(self, *, tooltip: str, on_click) -> QPushButton:
        button = QPushButton("X")
        button.setObjectName("selectedDatasetClearButton")
        button.setToolTip(tooltip)
        button.setCursor(Qt.PointingHandCursor)
        button.setFixedSize(18, 22)
        button.clicked.connect(on_click)
        return button

    def _add_selected_actions(
        self,
        row_layout: QHBoxLayout,
        *,
        show_copy: bool,
        show_open_link: bool,
        open_link_tooltip: str,
        on_clear: object,
    ) -> None:
        actions = QWidget()
        actions.setFixedWidth(_SELECTED_ROW_ACTIONS_WIDTH)
        actions_layout = QHBoxLayout(actions)
        actions_layout.setContentsMargins(0, 0, _SELECTED_ROW_ACTIONS_RIGHT_INSET, 0)
        actions_layout.setSpacing(
            _SELECTED_ROW_ACTION_SPACING if (show_copy or show_open_link) else 0,
        )
        if show_copy:
            actions_layout.addWidget(self.selected_dataset_copy_widget)
            self.selected_dataset_copy_widget.setVisible(True)
            self.selected_dataset_copy_widget.setEnabled(True)
        elif not show_open_link:
            actions_layout.addStretch(1)
        if show_open_link:
            if open_link_tooltip:
                self.selected_dataset_link_widget.setToolTip(open_link_tooltip)
            actions_layout.addWidget(self.selected_dataset_link_widget)
            self.selected_dataset_link_widget.setVisible(True)
            self.selected_dataset_link_widget.setEnabled(True)
        actions_layout.addWidget(self._make_selected_clear_button(tooltip="Unselect", on_click=on_clear))
        row_layout.addWidget(actions, 0)

    def _add_selected_group_header(
        self,
        title: str,
        *,
        count: int | None = None,
        on_clear_all: object | None = None,
        add_top_gap: bool = False,
    ) -> None:
        if add_top_gap:
            self.selected_rows_layout.addSpacing(14)
        row = QWidget()
        row.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        row.setMinimumWidth(0)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 4, 0, 2)
        row_layout.setSpacing(6)
        title_host = QWidget()
        title_layout = QHBoxLayout(title_host)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(6)
        label = SelectableLabel(title)
        label.setObjectName("selectedPanelGroupHeader")
        label.setToolTip(title)
        title_layout.addWidget(label, 0)
        if count is not None:
            count_label = SelectableLabel(f"({count:,})")
            count_label.setObjectName("secondaryHeaderLabel")
            title_layout.addWidget(count_label, 0)
        title_layout.addStretch(1)
        row_layout.addWidget(title_host, 1)
        if on_clear_all is not None:
            actions = QWidget()
            actions.setFixedWidth(_SELECTED_ROW_ACTIONS_WIDTH)
            actions_layout = QHBoxLayout(actions)
            actions_layout.setContentsMargins(0, 0, _SELECTED_ROW_ACTIONS_RIGHT_INSET, 0)
            actions_layout.setSpacing(0)
            actions_layout.addStretch(1)
            actions_layout.addWidget(
                self._make_selected_clear_button(
                    tooltip=f"Remove all {title.lower()}",
                    on_click=on_clear_all,
                )
            )
            row_layout.addWidget(actions, 0)
        self.selected_rows_layout.addWidget(row, 0, Qt.AlignTop)

    def _add_selected_row(
        self,
        *,
        text: str,
        tooltip: str = "",
        show_copy: bool = False,
        show_open_link: bool = False,
        open_link_tooltip: str = "",
        on_clear: object,
        auto_selected: bool = False,
    ) -> None:
        row = QWidget()
        row.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        row.setMinimumWidth(0)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 1, 0, 1)
        row_layout.setSpacing(6)
        label = ElidedLabel(text)
        label.setObjectName("selectedDatasetValueAuto" if auto_selected else "selectedDatasetValue")
        label.setToolTip(tooltip or text)
        row_layout.addWidget(label, 1)
        self._add_selected_actions(
            row_layout,
            show_copy=show_copy,
            show_open_link=show_open_link,
            open_link_tooltip=open_link_tooltip,
            on_clear=on_clear,
        )
        self.selected_rows_layout.addWidget(row, 0, Qt.AlignTop)

    def _add_selected_section_gap(self) -> None:
        self.selected_rows_layout.addSpacing(14)

    def _add_selected_toggle_link(self, label: str, on_click) -> None:
        button = QPushButton(label)
        button.setObjectName("selectedPanelToggle")
        button.setFlat(True)
        button.setCursor(Qt.PointingHandCursor)
        button.clicked.connect(on_click)
        row = QWidget()
        row.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 2, 0, 4)
        row_layout.setSpacing(0)
        row_layout.addWidget(button, 0, Qt.AlignLeft)
        row_layout.addStretch(1)
        self.selected_rows_layout.addWidget(row, 0, Qt.AlignTop)

    def _add_collapsible_selected_items(
        self,
        items: list,
        *,
        expanded: bool,
        on_show_more,
        on_show_less,
        add_item,
    ) -> None:
        if len(items) <= _SELECTED_GROUP_COLLAPSE_AFTER:
            for item in items:
                add_item(item)
            return
        visible = items if expanded else items[:_SELECTED_GROUP_COLLAPSED_VISIBLE]
        for item in visible:
            add_item(item)
        if expanded:
            self._add_selected_toggle_link("Show less", on_show_less)
        else:
            self._add_selected_toggle_link("Show more", on_show_more)

    def _set_selected_categories_expanded(self, expanded: bool) -> None:
        self._selected_categories_expanded = expanded
        self._update_selected_panel()

    def _set_selected_areas_expanded(self, expanded: bool) -> None:
        self._selected_areas_expanded = expanded
        self._update_selected_panel()

    def _clear_selected_rows(self) -> None:
        self.selected_dataset_copy_widget.setParent(None)
        self.selected_dataset_link_widget.setParent(None)
        while self.selected_rows_layout.count():
            item = self.selected_rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
            # Spacers from addStretch() are QSpacerItem without widgets.

    def _update_selected_panel(self) -> None:
        self._clear_selected_rows()
        self.selected_dataset_copy_widget.setVisible(False)
        self.selected_dataset_copy_widget.setEnabled(False)
        self.selected_dataset_link_widget.setVisible(False)
        self.selected_dataset_link_widget.setEnabled(False)

        has_items = False
        first_group = True

        if self._dataset_search_text or self._area_search_text:
            self._add_selected_group_header(
                "Search keys",
                add_top_gap=not first_group,
                on_clear_all=self._clear_all_search_keys,
            )
            first_group = False
            if self._dataset_search_text:
                ds_text = f'Dataset: "{self._dataset_search_text}"'
                self._add_selected_row(
                    text=ds_text,
                    tooltip=ds_text,
                    on_clear=self._clear_selected_search_key,
                )
            if self._area_search_text:
                area_text = f'Area: "{self._area_search_text}"'
                self._add_selected_row(
                    text=area_text,
                    tooltip=area_text,
                    on_clear=self._clear_selected_area_search_key,
                )
            has_items = True

        if self._selected_dataset:
            ds = self._selected_dataset
            tags = self._dataset_original_category_label(ds)
            uuid = ds.metadata_uuid
            tip = f"{ds.title}\n{uuid}\n{tags}" if tags else f"{ds.title}\n{uuid}"
            self._add_selected_group_header("Dataset", add_top_gap=not first_group)
            first_group = False
            self._add_selected_row(
                text=ds.title,
                tooltip=tip,
                show_copy=True,
                show_open_link=True,
                open_link_tooltip=self._dataset_metadata_url(ds),
                on_clear=self._clear_selected_dataset,
            )
            has_items = True

        if self._selected_categories:
            categories = sorted(self._selected_categories, key=_norwegian_sort_key)
            self._add_selected_group_header(
                "Categories",
                count=len(categories),
                add_top_gap=not first_group,
                on_clear_all=self._clear_all_selected_categories
                if len(categories) >= 2
                else None,
            )
            first_group = False
            if len(categories) <= _SELECTED_GROUP_COLLAPSE_AFTER:
                self._selected_categories_expanded = False

            def _add_category_row(category: str) -> None:
                self._add_selected_row(
                    text=category,
                    tooltip=category,
                    on_clear=lambda checked=False, c=category: self._clear_selected_category(c),
                )

            self._add_collapsible_selected_items(
                categories,
                expanded=self._selected_categories_expanded,
                on_show_more=lambda: self._set_selected_categories_expanded(True),
                on_show_less=lambda: self._set_selected_categories_expanded(False),
                add_item=_add_category_row,
            )
            has_items = True

        panel_areas: list[tuple[AreaOption, bool]] = []
        user_codes = {a.code for a in self._selected_areas}
        for area in sorted(self._selected_areas, key=lambda a: _norwegian_sort_key(a.label)):
            panel_areas.append((area, False))
        for area in sorted(self._auto_areas, key=lambda a: _norwegian_sort_key(a.label)):
            if area.code not in user_codes:
                panel_areas.append((area, True))
        if panel_areas:
            user_only_count = len(self._selected_areas)
            self._add_selected_group_header(
                "Areas",
                count=len(panel_areas),
                add_top_gap=not first_group,
                on_clear_all=self._clear_all_selected_areas if user_only_count >= 2 else None,
            )
            first_group = False
            if len(panel_areas) <= _SELECTED_GROUP_COLLAPSE_AFTER:
                self._selected_areas_expanded = False

            def _add_area_row(entry: tuple[AreaOption, bool]) -> None:
                area, is_auto = entry
                self._add_selected_row(
                    text=area.label,
                    tooltip=area.label,
                    auto_selected=is_auto,
                    on_clear=(
                        (lambda checked=False, a=area: self._clear_auto_area_one(a))
                        if is_auto
                        else (lambda checked=False, a=area: self._clear_selected_area_one(a))
                    ),
                )

            self._add_collapsible_selected_items(
                panel_areas,
                expanded=self._selected_areas_expanded,
                on_show_more=lambda: self._set_selected_areas_expanded(True),
                on_show_less=lambda: self._set_selected_areas_expanded(False),
                add_item=_add_area_row,
            )
            has_items = True

        if self._selected_projection:
            proj_text = self._selected_projection.label
            self._add_selected_group_header("Projection", add_top_gap=not first_group)
            first_group = False
            self._add_selected_row(
                text=proj_text,
                tooltip=proj_text,
                on_clear=self._clear_selected_projection,
            )
            has_items = True
        elif self._auto_projection:
            proj_text = self._auto_projection.label
            self._add_selected_group_header("Projection", add_top_gap=not first_group)
            first_group = False
            self._add_selected_row(
                text=proj_text,
                tooltip=proj_text,
                auto_selected=True,
                on_clear=self._clear_auto_projection,
            )
            has_items = True

        if self._selected_format:
            fmt_text = self._selected_format.label
            self._add_selected_group_header("Format", add_top_gap=not first_group)
            first_group = False
            self._add_selected_row(
                text=fmt_text,
                tooltip=fmt_text,
                on_clear=self._clear_selected_format,
            )
            has_items = True
        elif self._auto_format:
            fmt_text = self._auto_format.label
            self._add_selected_group_header("Format", add_top_gap=not first_group)
            first_group = False
            self._add_selected_row(
                text=fmt_text,
                tooltip=fmt_text,
                auto_selected=True,
                on_clear=self._clear_auto_format,
            )
            has_items = True

        self.clear_all_selections_button.setVisible(has_items)
        incompatible = self._incompatible_selection_reasons()
        if incompatible:
            self.selected_warning_label.setText(incompatible[0])
            self.selected_warning_label.show()
        else:
            self.selected_warning_label.clear()
            self.selected_warning_label.hide()
        if not has_items:
            none_label = ElidedLabel("None")
            none_label.setObjectName("selectedDatasetValue")
            none_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
            self.selected_rows_layout.addWidget(none_label, 0, Qt.AlignTop)
        self._make_labels_selectable(self.selected_rows_host)
        self.selected_scroll.verticalScrollBar().setValue(0)

    def _reset_dataset_page(self) -> None:
        if self._dataset_page == 0:
            return
        self._dataset_page = 0
        self._dataset_signature = ()

    def _clear_all_search_keys(self) -> None:
        if not (self._dataset_search_text or self._area_search_text):
            return
        self._dataset_search_text = ""
        self._area_search_text = ""
        self.dataset_search.clear()
        self.area_search.clear()
        self._update_selected_panel()
        self._area_signature = ()
        self._reset_dataset_page()
        self._schedule_recompute_lists(0)

    def _clear_selected_search_key(self) -> None:
        if not self._dataset_search_text:
            return
        self._dataset_search_text = ""
        self.dataset_search.clear()
        self._update_selected_panel()
        self._area_signature = ()
        self._reset_dataset_page()
        self._schedule_recompute_lists(0)

    def _clear_selected_area_search_key(self) -> None:
        if not self._area_search_text and not self.area_search.text().strip():
            return
        self._area_search_text = ""
        self.area_search.clear()
        self._update_selected_panel()
        if not self._recompute_running and self._area_search_input_active():
            self._populate_areas_for_type(self._active_area_type(), preserve_selection=True)
        else:
            self._area_signature = ()
            self._schedule_recompute_lists(0)

    def _dataset_page_count(self) -> int:
        if self._dataset_total_rows <= 0:
            return 1
        return max(1, (self._dataset_total_rows + self._dataset_page_size - 1) // self._dataset_page_size)

    def _on_dataset_prev_page(self) -> None:
        if self._dataset_page <= 0:
            return
        self._dataset_page -= 1
        self._dataset_signature = ()
        self._apply_dataset_filter()
        self.dataset_view.verticalScrollBar().setValue(0)

    def _on_dataset_next_page(self) -> None:
        if self._dataset_page >= self._dataset_page_count() - 1:
            return
        self._dataset_page += 1
        self._dataset_signature = ()
        self._apply_dataset_filter()
        self.dataset_view.verticalScrollBar().setValue(0)

    def _populate_categories(self) -> None:
        index = self._ensure_filter_index()
        mask = self._compose_filter_mask(ignore={"category"})
        categories = sorted(index.categories_for_mask(mask), key=_norwegian_sort_key)
        self.category_count_label.setText(f"({len(categories):,})")
        signature = tuple(categories)
        selection = self.category_view.selectionModel()
        was_blocked = selection.blockSignals(True)
        try:
            if signature != self._category_signature:
                self._category_signature = signature
                tooltips = {
                    category: ", ".join(
                        sorted(index.category_tags_for_mask(category, mask), key=_norwegian_sort_key)
                    )
                    for category in categories
                }
                self.category_model.set_items(
                    [(category, category) for category in categories],
                    tooltips=tooltips,
                )
            selection.clearSelection()
            for row, category in enumerate(categories):
                if category in self._selected_categories:
                    selection.select(self.category_model.index(row, 0), QItemSelectionModel.Select)
        finally:
            selection.blockSignals(was_blocked)
        clear_list_index_widgets(self.category_view)

    def _populate_areas_for_type(self, area_type: AreaType | None, *, preserve_selection: bool = True) -> None:
        # Areas list shows options compatible with all OTHER selected filters.
        if area_type is None:
            self.area_label.setText("Areas")
            self.area_count_label.setText("")
            self._area_signature = ()
            self._selected_areas = []
            self._auto_areas = []
            self._auto_area_codes = set()
            area_cols = [1] if self._area_display_name_only else [1, 2]
            clear_tree_index_widgets(self.area_view, area_cols)
            self._suppress_area_change = True
            try:
                self.area_model.set_items([], notify=False)
            finally:
                self._suppress_area_change = False
            self._update_area_all_checkbox()
            self.area_view.setCursor(Qt.ArrowCursor)
            self.area_view.viewport().setCursor(Qt.ArrowCursor)
            self._update_area_header_visibility()
            self._update_open_map_visibility()
            if self._auto_area_type is not None and self._selected_area_type is None:
                self._apply_area_type_button_visuals()
            return
        self.area_view.setCursor(Qt.ArrowCursor)
        self.area_view.viewport().setCursor(Qt.ArrowCursor)
        if preserve_selection:
            # Keep full selection; union model checks for in-flight clicks during recompute.
            checked_keys = {a.code for a in self._selected_areas}
            if self.area_model.rowCount():
                checked_keys |= self.area_model.checked_keys()
        else:
            checked_keys = set()
        scroll_value = self.area_view.verticalScrollBar().value()
        context = self._area_populate_context_key(area_type)
        if context != self._area_populate_context:
            self._area_signature = ()
            self._area_populate_context = context
        all_areas = self._sort_areas(self._candidate_areas(area_type))
        self._reconcile_area_search_with_candidates(all_areas)
        if area_type == "landsdekkende":
            total = len(all_areas)
            self.area_count_label.setText(_filter_panel_count_text(selectable=total, total=total) if total else "")
            self.area_label.setText("Areas")
            signature: object = ("landsdekkende", total)
            previous_signature = self._area_signature
            if preserve_selection and signature == previous_signature:
                self._update_area_details_visibility()
                return
            self._area_signature = signature
            clear_tree_index_widgets(self.area_view, [1, 2])
            self._suppress_area_change = True
            try:
                self.area_model.set_items([], notify=False)
            finally:
                self._suppress_area_change = False
            if self._selected_area_type == "landsdekkende":
                self._auto_areas = []
                self._selected_areas = self._entire_country_selection(
                    all_areas,
                    preserve_selection=preserve_selection,
                )
            elif self._auto_area_type == "landsdekkende" and len(all_areas) == 1:
                self._auto_areas = list(all_areas)
                self._selected_areas = []
            elif self._auto_area_type == "landsdekkende":
                self._auto_areas = self._entire_country_selection(all_areas, preserve_selection=False)
                self._selected_areas = []
            else:
                self._auto_areas = []
                self._selected_areas = []
            self._update_area_all_checkbox()
            self._update_area_details_visibility()
            self._update_open_map_visibility()
            return
        self._area_display_name_only = self._area_table_name_only(area_type, all_areas)
        areas = self._filter_areas_by_search(all_areas)
        total_areas = len(areas)
        if self._selected_dataset:
            truncated = False
            display_areas = areas
        else:
            truncated = total_areas > _AREA_TABLE_ROW_LIMIT
            display_areas = areas[:_AREA_TABLE_ROW_LIMIT] if truncated else areas
        compat = self._compatibility_state
        dataset_mode = self._dataset_compatibility_mode()
        area_state = area_list_state(compat, display_areas, dataset_mode=dataset_mode)
        disabled_keys = area_state.disabled_keys
        total_present = len(display_areas)
        selectable_present = total_present - len(disabled_keys)
        self.area_count_label.setText(
            _filter_panel_count_text(selectable=selectable_present, total=total_present)
        )
        area_tooltips = area_state.tooltips
        signature = self._area_list_content_signature(
            area_type,
            display_areas,
            truncated=truncated,
            filtered_total=total_areas,
            disabled_keys=disabled_keys if dataset_mode else None,
        )
        previous_signature = self._area_signature
        if preserve_selection and signature == previous_signature:
            self._update_area_all_checkbox()
            return
        self._area_signature = signature
        items = [
            CheckListItem(key=a.code, label=a.label, payload=a, code=a.code, name=a.name) for a in display_areas
        ]
        valid_keys = {a.code for a in areas}
        usable_keys = checked_keys & valid_keys
        area_cols = [1] if self._area_display_name_only else [1, 2]
        clear_tree_index_widgets(self.area_view, area_cols)
        self._suppress_area_change = True
        try:
            self.area_model.set_items(
                items,
                name_only=self._area_display_name_only,
                disabled_keys=disabled_keys,
                tooltips=area_tooltips,
                notify=False,
            )
            if usable_keys:
                self.area_model.set_checked_keys(usable_keys)
                self._auto_area_codes = set()
                self._auto_areas = []
            elif signature != previous_signature and len(items) == 1 and not self._selected_areas:
                single = display_areas[0]
                if not dataset_mode or compat.area_enabled(single):
                    self._auto_areas = [single]
                    self._auto_area_codes = {single.code}
                else:
                    self._auto_areas = []
                    self._auto_area_codes = set()
                self.area_model.set_checked_keys(set())
            elif signature != previous_signature and dataset_mode and not self._selected_areas:
                enabled_areas = [a for a in display_areas if compat.area_enabled(a)]
                if len(enabled_areas) == 1:
                    single = enabled_areas[0]
                    self._auto_areas = [single]
                    self._auto_area_codes = {single.code}
                    self.area_model.set_checked_keys(set())
                else:
                    self._auto_area_codes = set()
                    self._auto_areas = []
            elif signature != previous_signature:
                self._auto_area_codes = set()
                if not self._selected_areas:
                    self._auto_areas = []
            else:
                self._auto_area_codes = set()
                if not self._selected_areas:
                    self._auto_areas = []
        finally:
            self._suppress_area_change = False
        self._configure_area_columns()
        QTimer.singleShot(0, lambda value=scroll_value: self.area_view.verticalScrollBar().setValue(value))
        if self._selected_areas:
            self._auto_areas = []
            self._auto_area_codes = set()
        elif not self._auto_areas:
            self._selected_areas = self.area_model.checked_payloads()
        self.area_view.viewport().update()
        self._update_area_all_checkbox()
        self._update_area_header_visibility()
        self._update_open_map_visibility()
        if self._auto_area_type is not None and self._selected_area_type is None:
            self._apply_area_type_button_visuals()
        self._update_selected_panel()
        self._update_download_button_state()

    def _sort_areas(self, areas: list[AreaOption]) -> list[AreaOption]:
        reverse = not self._area_sort_ascending
        if self._area_sort_column == "code":
            return sorted(areas, key=lambda a: _code_sort_key(a.code), reverse=reverse)
        return sorted(areas, key=lambda a: (_norwegian_sort_key(a.name), _code_sort_key(a.code)), reverse=reverse)

    def _filtered_datasets(self) -> list[DatasetAvailability]:
        index = self._ensure_filter_index()
        mask = self._compose_filter_mask(ignore={"dataset"})
        filtered: list[DatasetAvailability] = list(self._login_required_datasets)
        filtered.extend(index.datasets_for_mask(mask))
        filtered.sort(key=lambda d: _norwegian_sort_key(d.title))
        return filtered

    def _apply_dataset_filter(self) -> None:
        clear_dataset_index_widgets(self.dataset_view)
        scroll_value = self.dataset_view.verticalScrollBar().value()

        filtered = self._filtered_datasets()
        disabled_ids = {id(ds) for ds in self._login_required_datasets}
        self._dataset_total_rows = len(filtered)
        page_count = self._dataset_page_count()
        if self._dataset_page >= page_count:
            self._dataset_page = page_count - 1
        if self._dataset_page < 0:
            self._dataset_page = 0

        start = self._dataset_page * self._dataset_page_size
        end = min(start + self._dataset_page_size, self._dataset_total_rows)
        visible = filtered[start:end]

        rows: list[tuple[str, str, object]] = []
        primary_tt: dict[int, str] = {}
        secondary_tt: dict[int, str] = {}
        link_tt: dict[int, str] = {}
        for ds in visible:
            rows.append((ds.title, self._dataset_original_category_label(ds), ds))
            pid = id(ds)
            primary_tt[pid] = f"{ds.title}\n{ds.metadata_uuid}"
            link_tt[pid] = self._dataset_metadata_url(ds)
            tip_tags = self._dataset_tags_table_tooltip(ds)
            if tip_tags:
                secondary_tt[pid] = tip_tags

        signature = tuple(
            (
                payload.metadata_uuid if isinstance(payload, DatasetAvailability) else str(id(payload)),
                title,
                tags,
            )
            for title, tags, payload in rows
        )
        page_label = f"{start + 1}-{end} of {self._dataset_total_rows}" if self._dataset_total_rows else "0 of 0"
        self.dataset_count_label.setText(f"({self._dataset_total_rows})")
        self.dataset_page_label.setText(page_label)
        self.dataset_prev_button.setEnabled(self._dataset_page > 0)
        self.dataset_next_button.setEnabled(self._dataset_page < page_count - 1)
        self.dataset_header_copy_widget.setEnabled(self._dataset_total_rows > 0)
        if signature == self._dataset_signature:
            self._displayed_dataset_uuids = [
                payload.metadata_uuid
                for _, _, payload in rows
                if isinstance(payload, DatasetAvailability)
            ]
            self._restore_dataset_selection()
            return
        self._dataset_signature = signature
        self.dataset_model.set_items(
            rows,
            disabled_payload_ids=disabled_ids,
            primary_tooltips_by_id=primary_tt,
            secondary_tooltips_by_id=secondary_tt,
            link_tooltips_by_id=link_tt,
        )
        self._displayed_dataset_uuids = [
            payload.metadata_uuid
            for _, _, payload in rows
            if isinstance(payload, DatasetAvailability)
        ]
        QTimer.singleShot(0, self._configure_dataset_columns)
        QTimer.singleShot(0, lambda value=scroll_value: self.dataset_view.verticalScrollBar().setValue(value))
        QTimer.singleShot(0, self.dataset_view.viewport().update)
        self._restore_dataset_selection()

    def _populate_projections(self) -> None:
        candidates = self._candidate_projections()
        compat = self._compatibility_state
        dataset_mode = self._dataset_compatibility_mode()
        state = projection_list_state(compat, candidates, dataset_mode=dataset_mode)
        total = len(candidates)
        selectable = total - len(state.disabled_payload_ids)
        self.projection_count_label.setText(
            _filter_panel_count_text(selectable=selectable, total=total)
        )
        previous_signature = self._projection_signature

        selection = self.projection_view.selectionModel()
        was_blocked = selection.blockSignals(True)
        self._suppress_single_select_change = True
        try:
            if state.content_signature != previous_signature:
                self._auto_projection = None
                self.projection_model.set_items(
                    [((p.name.strip() if p.name and p.name.strip() else p.code), p) for p in candidates],
                    disabled_payload_ids=state.disabled_payload_ids,
                    tooltips_by_id=state.tooltips_by_id,
                )
            self._projection_signature = state.content_signature
            self._reapply_projection_selection(candidates)
            if self._selected_projection:
                self._auto_projection = None
            elif state.auto_select is not None:
                self._auto_projection = state.auto_select
            else:
                self._auto_projection = None
        finally:
            self._suppress_single_select_change = False
            selection.blockSignals(was_blocked)
        clear_list_index_widgets(self.projection_view)
        self.projection_view.viewport().update()

    def _populate_formats(self) -> None:
        candidates = self._candidate_formats()
        compat = self._compatibility_state
        dataset_mode = self._dataset_compatibility_mode()
        state = format_list_state(
            compat,
            candidates,
            dataset_mode=dataset_mode,
            format_key_fn=_format_filter_key,
        )
        total = len(candidates)
        selectable = total - len(state.disabled_payload_ids)
        self.format_count_label.setText(
            _filter_panel_count_text(selectable=selectable, total=total)
        )
        previous_signature = self._format_signature

        selection = self.format_view.selectionModel()
        was_blocked = selection.blockSignals(True)
        self._suppress_single_select_change = True
        try:
            if state.content_signature != previous_signature:
                self._auto_format = None
                self.format_model.set_items(
                    [(f.label, f) for f in candidates],
                    disabled_payload_ids=state.disabled_payload_ids,
                    tooltips_by_id=state.tooltips_by_id,
                )
            self._format_signature = state.content_signature
            self._reapply_format_selection(candidates)
            if self._selected_format:
                self._auto_format = None
            elif state.auto_select is not None:
                self._auto_format = state.auto_select
            else:
                self._auto_format = None
        finally:
            self._suppress_single_select_change = False
            selection.blockSignals(was_blocked)
        clear_list_index_widgets(self.format_view)
        self.format_view.viewport().update()

    def _reapply_projection_selection(self, candidates: list[ProjectionOption]) -> None:
        selection = self.projection_view.selectionModel()
        selection.clearSelection()
        if not self._selected_projection:
            self.projection_view.setCurrentIndex(QModelIndex())
            return
        for row, p in enumerate(candidates):
            if p.code == self._selected_projection.code:
                idx = self.projection_model.index(row, 0)
                selection.select(idx, QItemSelectionModel.ClearAndSelect)
                self.projection_view.setCurrentIndex(idx)
                return
        self.projection_view.setCurrentIndex(QModelIndex())

    def _reapply_format_selection(self, candidates: list[FormatOption]) -> None:
        selection = self.format_view.selectionModel()
        selection.clearSelection()
        if not self._selected_format:
            self.format_view.setCurrentIndex(QModelIndex())
            return
        target = _format_filter_key(self._selected_format)
        for row, f in enumerate(candidates):
            if _format_filter_key(f) == target:
                idx = self.format_model.index(row, 0)
                selection.select(idx, QItemSelectionModel.ClearAndSelect)
                self.format_view.setCurrentIndex(idx)
                return
        self.format_view.setCurrentIndex(QModelIndex())

    @staticmethod
    def _download_button_text(count: int) -> str:
        if count == 1:
            return "Download 1 item"
        return f"Download {count} items"

    def _download_task_labels(self) -> list[str]:
        ds = self._selected_dataset
        if not ds:
            return []
        areas = self._effective_areas()
        if self._dataset_requires_area(ds) and areas:
            return [area.label for area in areas]
        return [ds.title]

    def _download_task_count(self) -> int:
        return len(self._download_task_labels())

    def _default_download_folder(self) -> Path:
        settings = QSettings("Geonorge", "Datasets")
        saved = settings.value("downloads/last_folder", "", type=str).strip()
        if saved:
            saved_path = Path(saved).expanduser()
            if saved_path.exists() and saved_path.is_dir():
                return saved_path

        qt_downloads = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
        if qt_downloads:
            qt_path = Path(qt_downloads)
            if qt_path.exists() and qt_path.is_dir():
                return qt_path

        home_downloads = Path.home() / "Downloads"
        if home_downloads.exists() and home_downloads.is_dir():
            return home_downloads

        return Path(__file__).resolve().parent.parent

    def _choose_download_folder(self) -> str:
        start_dir = str(self._default_download_folder())
        folder = QFileDialog.getExistingDirectory(self, "Choose download folder", start_dir)
        if folder:
            QSettings("Geonorge", "Datasets").setValue("downloads/last_folder", folder)
        return folder

    def _next_download_job_id(self) -> int:
        self._download_job_seq += 1
        return self._download_job_seq

    def _get_download_job(self, job_id: int) -> _DownloadJob | None:
        return self._download_jobs.get(job_id)

    def _get_or_create_download_progress_dialog(self) -> DownloadProgressDialog:
        if self._download_progress_dialog is None:
            dialog = DownloadProgressDialog(None, light_mode=self._light_mode)
            if self.windowIcon() and not self.windowIcon().isNull():
                dialog.setWindowIcon(self.windowIcon())
            dialog.cancel_requested.connect(self._request_cancel_download)
            dialog.close_all_requested.connect(self._request_cancel_all_downloads)
            dialog.finished.connect(self._on_download_progress_dialog_closed)
            self._download_progress_dialog = dialog
        return self._download_progress_dialog

    def _detach_download_job(self, job_id: int, *, remove_from_dialog: bool) -> None:
        self._download_jobs.pop(job_id, None)
        dialog = self._download_progress_dialog
        if dialog is None:
            return
        if remove_from_dialog:
            dialog.remove_order(job_id)
            if not dialog.has_orders():
                dialog.allow_close()
                dialog.close()
                dialog.deleteLater()
                self._download_progress_dialog = None
            return
        dialog.mark_order_finished(job_id)
        self._sync_download_dialog_complete_state()

    def _sync_download_dialog_complete_state(self) -> None:
        dialog = self._download_progress_dialog
        if dialog is None or self._download_jobs:
            return
        if dialog.all_orders_finished():
            dialog.enter_complete_mode()

    def _on_download_progress_dialog_closed(self) -> None:
        self._download_progress_dialog = None

    def _remove_download_job(self, job_id: int) -> None:
        self._detach_download_job(job_id, remove_from_dialog=True)

    def _request_cancel_all_downloads(self) -> None:
        if not self._download_jobs:
            return
        confirmed = themed_confirm_box(
            self,
            title="Cancel all downloads?",
            text="Stop all downloads in progress? Files already saved will be kept.",
            accept_label="Yes",
            reject_label="No",
        )
        if not confirmed:
            return
        for job_id in list(self._download_jobs):
            job = self._download_jobs.get(job_id)
            if job is None or job.cancel.is_set():
                continue
            job.cancel.set()
            job.dialog.set_order_cancelling(job_id, True)
        queue_suffix = self._download_queue_status()
        self._set_status(f"Cancelling downloads…{queue_suffix}")

    def _downloads_in_progress(self) -> bool:
        return any(job.worker is not None for job in self._download_jobs.values())

    def _request_cancel_download(self, job_id: int) -> None:
        job = self._get_download_job(job_id)
        if job is None or job.cancel.is_set():
            return
        confirmed = themed_confirm_box(
            self,
            title="Cancel download?",
            text="Stop this download? Files already saved will be kept.",
            accept_label="Yes",
            reject_label="No",
        )
        if not confirmed:
            return
        job.cancel.set()
        job.dialog.set_order_cancelling(job_id, True)
        queue_suffix = self._download_queue_status()
        self._set_status(f"Cancelling download…{queue_suffix}")

    def _confirm_quit_while_downloading(self) -> bool:
        return themed_confirm_box(
            self,
            title="Quit while downloading?",
            text="Downloads are still in progress. Quit anyway?",
            accept_label="Quit",
            reject_label="Cancel",
            destructive_accept=True,
        )

    def _cancel_all_downloads(self) -> None:
        for job in self._download_jobs.values():
            job.cancel.set()
            if self._download_progress_dialog is not None:
                self._download_progress_dialog.set_order_cancelling(job.job_id, True)

    def _download_queue_status(self) -> str:
        waiting = self._packaging_queue.waiting_count
        active = self._packaging_queue.active_count
        if waiting <= 0 and active <= 0:
            return ""
        parts: list[str] = []
        if active:
            parts.append(f"{active} packaging")
        if waiting:
            parts.append(f"{waiting} queued")
        return f" ({', '.join(parts)})"

    def _close_download_progress_dialog(self) -> None:
        for job_id in list(self._download_jobs):
            self._remove_download_job(job_id)
        if self._download_progress_dialog is not None:
            self._download_progress_dialog.allow_close()
            self._download_progress_dialog.close()
            self._download_progress_dialog.deleteLater()
            self._download_progress_dialog = None

    def _update_download_button_state(self) -> None:
        reasons: list[str] = []
        ds = self._selected_dataset
        if not ds:
            reasons.append("Select a dataset.")
            self.download_button.setText("Download")
        else:
            if self._dataset_can_open_in_browser(ds):
                self.download_button.setText("Open in browser")
                self.download_button.setEnabled(True)
                self.download_button.setToolTip("Open this dataset in the Geonorge catalog.")
                self.download_button.setCursor(Qt.PointingHandCursor)
                return
            if self._dataset_requires_area(ds):
                if not self._active_area_type() or not self._effective_areas():
                    reasons.append("Select an area.")
            if ds.projections and not self._effective_projection():
                reasons.append("Select a projection.")
        if not self._effective_format():
            reasons.append("Select a format.")
        reasons.extend(self._incompatible_selection_reasons())

        clickable = not reasons
        self.download_button.setEnabled(clickable)
        if clickable:
            count = self._download_task_count()
            self.download_button.setText(self._download_button_text(count))
            self.download_button.setToolTip("Download for the current selection.")
            self.download_button.setCursor(Qt.PointingHandCursor)
        else:
            self.download_button.setText("Download")
            self.download_button.setToolTip(" ".join(reasons))
            self.download_button.setCursor(Qt.ArrowCursor)

    def _dataset_requires_area(self, ds: DatasetAvailability) -> bool:
        return any(ds.areas_by_type.get(t) for t in AREA_TYPE_ORDER)

    def _restore_dataset_selection(self) -> None:
        if not self._selected_dataset:
            self.dataset_view.selectionModel().clearSelection()
            self.dataset_view.setCurrentIndex(QModelIndex())
            return
        for row in range(self.dataset_model.rowCount()):
            idx = self.dataset_model.index(row, 0)
            payload = self.dataset_model.selected_payload(idx)
            if (
                isinstance(payload, DatasetAvailability)
                and payload.metadata_uuid == self._selected_dataset.metadata_uuid
            ):
                self.dataset_view.selectionModel().select(idx, QItemSelectionModel.ClearAndSelect)
                self.dataset_view.setCurrentIndex(idx)
                return
        self.dataset_view.setCurrentIndex(QModelIndex())

    def _update_visible_dataset_row(self, ds: DatasetAvailability) -> None:
        for row in range(self.dataset_model.rowCount()):
            idx = self.dataset_model.index(row, 0)
            payload = self.dataset_model.selected_payload(idx)
            if not isinstance(payload, DatasetAvailability) or payload.metadata_uuid != ds.metadata_uuid:
                continue

            title_item = self.dataset_model.item(row, 0)
            copy_item = self.dataset_model.item(row, 1)
            tags_item = self.dataset_model.item(row, 2)
            title_tip = f"{ds.title}\n{ds.metadata_uuid}"
            tags_tip = self._dataset_tags_table_tooltip(ds)
            tags_display = self._dataset_original_category_label(ds)
            for item, text, tooltip in (
                (title_item, ds.title, title_tip),
                (tags_item, tags_display, tags_tip if tags_tip else tags_display),
            ):
                if item is None:
                    continue
                item.setText(text)
                item.setData(ds, Qt.UserRole + 1)
                item.setToolTip(tooltip)
                item.setEnabled(not ds.login_required)
                if ds.login_required:
                    item.setForeground(QBrush(QColor("#7d8597")))
            if copy_item is not None:
                copy_item.setData(ds, Qt.UserRole + 1)
                copy_item.setEnabled(True)
            self.dataset_view.viewport().update()
            return

    def _on_area_type_button_clicked(self, button) -> None:
        if self._recompute_running:
            return
        clicked_type: AreaType | None = None
        for area_type, candidate in self.area_type_buttons.items():
            if candidate is button:
                clicked_type = area_type
                break
        if clicked_type is None:
            return

        was_auto_only = self._selected_area_type is None and self._auto_area_type == clicked_type
        was_user = self._selected_area_type == clicked_type

        if was_auto_only:
            self._auto_area_type = None
            self._auto_areas = []
            self._auto_area_codes = set()
            self._selected_area_type = clicked_type
            self._close_area_map_if_inappropriate()
            for area_type, candidate in self.area_type_buttons.items():
                candidate.blockSignals(True)
                try:
                    candidate.setChecked(area_type == clicked_type)
                finally:
                    candidate.blockSignals(False)
            self._apply_area_type_button_visuals()
            self._selected_areas = []
            self._area_signature = ()
            self._clear_area_search_filter(block_field_signals=True)
            self._update_area_details_visibility()
            self._reset_dataset_page()
            self._schedule_recompute_lists(0, refresh=_REFRESH_FILTER_IMPACT)
            return

        if was_user and not button.isChecked():
            self._selected_area_type = None
            self._selected_areas = []
            available = tuple(self._available_area_types_for_selected_dataset())
            self._auto_area_type = clicked_type if len(available) == 1 else None
            self._auto_areas = []
            self._auto_area_codes = set()
            self._close_area_map_if_inappropriate()
            for area_type, candidate in self.area_type_buttons.items():
                candidate.blockSignals(True)
                try:
                    if area_type == clicked_type:
                        candidate.setChecked(self._auto_area_type == clicked_type)
                    else:
                        candidate.setChecked(False)
                finally:
                    candidate.blockSignals(False)
            self._apply_area_type_button_visuals()
            self._area_signature = ()
            self._clear_area_search_filter(block_field_signals=True)
            self._update_area_details_visibility()
            self._reset_dataset_page()
            self._schedule_recompute_lists(0, refresh=_REFRESH_FILTER_IMPACT)
            return

        self._auto_area_type = None
        self._auto_areas = []
        self._auto_area_codes = set()
        selected_area_type = clicked_type if button.isChecked() else None
        self._selected_area_type = selected_area_type
        self._close_area_map_if_inappropriate()
        for area_type, candidate in self.area_type_buttons.items():
            if candidate is not button:
                candidate.blockSignals(True)
                candidate.setChecked(False)
                candidate.blockSignals(False)
            elif selected_area_type is None:
                candidate.setChecked(False)
        self._selected_areas = []
        self._area_signature = ()
        self._clear_area_search_filter(block_field_signals=True)
        self._update_area_details_visibility()
        self._reset_dataset_page()
        self._schedule_recompute_lists(0, refresh=_REFRESH_FILTER_IMPACT)

    def _on_areas_changed(self) -> None:
        if self._suppress_area_change:
            return
        if self._recompute_running:
            self._pending_area_change = True
            return
        checked_keys = self.area_model.checked_keys()
        promoted_from_auto = bool(self._auto_area_codes & checked_keys)
        self._auto_areas = []
        self._auto_area_codes = set()
        self._apply_model_checks_to_selected_areas()
        if self._promote_auto_area_type_if_user_selected_areas():
            promoted_from_auto = True
        if not self._selected_areas:
            if self._restore_auto_single_area():
                self._update_area_all_checkbox()
                self._update_selected_panel()
                self._update_download_button_state()
                return
        self._update_area_all_checkbox()
        self._sync_area_map_selection()
        self._reset_dataset_page()
        refresh = _REFRESH_AREA_CHECK
        if promoted_from_auto:
            refresh = frozenset({"selected", "download"})
        self._schedule_recompute_lists(0, refresh=refresh, scope="area_check")

    def _on_area_all_clicked(self) -> None:
        # Drive from row model state, not Qt's tri-state toggle (which races with clicked).
        aggregate = self.area_model.aggregate_check_state()
        target_checked = aggregate != Qt.Checked
        self._auto_areas = []
        self._auto_area_codes = set()
        self._suppress_area_change = True
        try:
            self.area_model.set_all_checked(target_checked)
        finally:
            self._suppress_area_change = False
        self._on_areas_changed()

    def _sync_area_master_checkbox_visibility(self) -> None:
        show_list = self._area_type_shows_area_list(self._active_area_type())
        self.area_all_checkbox.setVisible(show_list and self.area_model.rowCount() > 1)

    def _update_area_all_checkbox(self) -> None:
        self.area_all_checkbox.blockSignals(True)
        try:
            state = self.area_model.aggregate_check_state()
            self.area_all_checkbox.setCheckState(state)
            enabled_count = self.area_model.enabled_row_count()
            self.area_all_checkbox.setEnabled(enabled_count > 0)
            self.area_all_checkbox.setCursor(
                Qt.PointingHandCursor if enabled_count > 0 else Qt.ArrowCursor
            )
            if enabled_count == 0:
                tip = "Select all"
            elif _check_state_value(state) == int(Qt.Checked.value):
                tip = "Unselect all enabled areas"
            else:
                tip = "Select all enabled areas"
            self.area_all_checkbox.setToolTip(tip)
            self.area_all_checkbox.update()
        finally:
            self.area_all_checkbox.blockSignals(False)
        self._sync_area_master_checkbox_visibility()

    def _on_area_sort_requested(self, column: str) -> None:
        if not self._area_type_shows_area_list(self._active_area_type()):
            return
        if self._area_sort_column == column:
            self._area_sort_ascending = not self._area_sort_ascending
        else:
            self._area_sort_column = column
            self._area_sort_ascending = True
        self._area_signature = ()
        self._populate_areas_for_type(self._active_area_type(), preserve_selection=True)

    def _on_area_cell_clicked(self, index) -> None:
        if not index.isValid():
            return
        if index.column() == 0:
            return
        if self.area_model.is_row_disabled(index.row()):
            return
        check_item = self.area_model.item(index.row(), 0)
        if not check_item or not check_item.isCheckable():
            return
        key = check_item.data(Qt.UserRole + 1)
        if isinstance(key, str) and key in self._auto_area_codes:
            self._auto_area_codes.discard(key)
            self._auto_areas = [a for a in self._auto_areas if a.code != key]
            check_item.setCheckState(Qt.Checked)
            return
        if _check_state_value(check_item.checkState()) == int(Qt.Checked.value):
            check_item.setCheckState(Qt.Unchecked)
        else:
            check_item.setCheckState(Qt.Checked)

    def _on_category_selection_changed(self) -> None:
        if self._recompute_running:
            return
        selected: set[str] = set()
        for index in self.category_view.selectionModel().selectedIndexes():
            category = self.category_model.selected_payload(index)
            if isinstance(category, str):
                selected.add(category)
        self._selected_categories = selected
        self._area_signature = ()
        self._reset_dataset_page()
        self._schedule_recompute_lists(0)

    def _on_downloadable_filter_changed(self) -> None:
        if self._recompute_running:
            return
        self._show_only_downloadable = self.downloadable_filter.isChecked()
        self._area_signature = ()
        self._reset_dataset_page()
        self._schedule_recompute_lists(0)

    def _on_dataset_search_text_changed(self, text: str) -> None:
        if text.strip():
            return
        self._apply_dataset_search()

    def _on_area_search_text_changed(self, text: str) -> None:
        if text.strip():
            return
        self._apply_area_search()

    def _apply_area_search(self) -> None:
        if self._recompute_running:
            return
        self._set_area_search_text(self.area_search.text())

    def _apply_dataset_search(self) -> None:
        if self._recompute_running:
            return
        text = self.dataset_search.text().strip()
        if text == self._dataset_search_text:
            return
        self._dataset_search_text = text
        self._update_selected_panel()
        self._area_signature = ()
        self._reset_dataset_page()
        self._schedule_recompute_lists(0)

    def _on_dataset_clicked(self, index) -> None:
        if not index.isValid():
            return
        if index.column() == DATASET_COL_COPY:
            self._show_dataset_copy_menu(index)
            return
        if index.column() == DATASET_COL_LINK:
            ds = self.dataset_model.selected_payload(index)
            if isinstance(ds, DatasetAvailability):
                self._open_dataset_in_browser(ds)
            return
        if index.column() != DATASET_COL_TITLE:
            return
        self._select_dataset_index(index, toggle=True)

    def _on_dataset_current_changed(self, current, previous) -> None:
        if self._mouse_selecting or self._suppress_single_select_change:
            return
        if not current.isValid() or current.column() != 0:
            return
        if not self.dataset_view.hasFocus():
            return
        self._select_dataset_index(current)

    def _copy_text_to_clipboard(self, text: str, message: str) -> None:
        QApplication.clipboard().setText(text)
        self.copy_status_text.setText(message)
        self._copy_status_timer.start(3500)

    def _clear_selected_dataset(self) -> None:
        if not self._selected_dataset:
            return
        self._close_dataset_copy_menu()
        self._selected_dataset = None
        self._clear_user_area_selection()
        self._clear_auto_area_selection()
        self._close_area_map_if_inappropriate()
        self._area_signature = ()
        self._update_selected_panel()
        self._schedule_recompute_lists(0, refresh=_REFRESH_DATASET)

    def _clear_all_selected_categories(self) -> None:
        if len(self._selected_categories) < 2:
            return
        self._selected_categories.clear()
        selection = self.category_view.selectionModel()
        was_blocked = selection.blockSignals(True)
        try:
            selection.clearSelection()
        finally:
            selection.blockSignals(was_blocked)
        self._reset_dataset_page()
        self._update_selected_panel()
        self._schedule_recompute_lists(0, refresh=_REFRESH_FILTER_IMPACT)

    def _clear_all_selected_areas(self) -> None:
        if len(self._selected_areas) < 2:
            return
        self._selected_areas = []
        self._area_signature = ()
        if self._selected_area_type is not None:
            self._selected_area_type = None
            for area_type, button in self.area_type_buttons.items():
                if button.isChecked() and area_type != self._auto_area_type:
                    button.blockSignals(True)
                    try:
                        button.setChecked(False)
                    finally:
                        button.blockSignals(False)
            self._apply_area_type_button_visuals()
            self._update_area_details_visibility()
        self._suppress_area_change = True
        try:
            self.area_model.set_checked_keys(set())
        finally:
            self._suppress_area_change = False
        self._update_area_all_checkbox()
        self._sync_area_map_selection()
        self._reset_dataset_page()
        self._update_selected_panel()
        self._schedule_recompute_lists(0, refresh=_REFRESH_FILTER_IMPACT)

    def _clear_selected_category(self, category: str) -> None:
        if category not in self._selected_categories:
            return
        self._selected_categories.discard(category)
        selection = self.category_view.selectionModel()
        was_blocked = selection.blockSignals(True)
        try:
            for row in range(self.category_model.rowCount()):
                idx = self.category_model.index(row, 0)
                if self.category_model.selected_payload(idx) == category:
                    selection.select(idx, QItemSelectionModel.Deselect)
        finally:
            selection.blockSignals(was_blocked)
        self._reset_dataset_page()
        self._update_selected_panel()
        self._schedule_recompute_lists(0, refresh=_REFRESH_FILTER_IMPACT)

    def _clear_selected_area_one(self, area: AreaOption) -> None:
        self._selected_areas = [a for a in self._selected_areas if a.code != area.code]
        self._area_signature = ()
        self._suppress_area_change = True
        try:
            self.area_model.set_checked_keys({a.code for a in self._selected_areas})
        finally:
            self._suppress_area_change = False
        self._update_area_all_checkbox()
        self._sync_area_map_selection()
        self._reset_dataset_page()
        self._update_selected_panel()
        self._schedule_recompute_lists(0, refresh=_REFRESH_AREA_CHECK)

    def _clear_auto_projection(self, checked: bool = False) -> None:
        del checked
        if not self._auto_projection:
            return
        self._auto_projection = None
        self.projection_view.viewport().update()
        self._update_selected_panel()
        self._schedule_recompute_lists(0, refresh=_REFRESH_FILTER_IMPACT)

    def _clear_auto_format(self, checked: bool = False) -> None:
        del checked
        if not self._auto_format:
            return
        self._auto_format = None
        self.format_view.viewport().update()
        self._update_selected_panel()
        self._schedule_recompute_lists(0, refresh=_REFRESH_FILTER_IMPACT)

    def _clear_auto_area_one(self, area: AreaOption) -> None:
        self._auto_areas = [a for a in self._auto_areas if a.code != area.code]
        self._auto_area_codes.discard(area.code)
        self.area_view.viewport().update()
        self._update_selected_panel()
        self._update_download_button_state()

    def _clear_selected_projection(self) -> None:
        if self._auto_projection:
            self._clear_auto_projection()
            return
        if not self._selected_projection:
            return
        self._selected_projection = None
        self._reset_dataset_page()
        self._update_selected_panel()
        self._schedule_recompute_lists(0, refresh=_REFRESH_FILTER_IMPACT)

    def _clear_selected_format(self) -> None:
        if self._auto_format:
            self._clear_auto_format()
            return
        if not self._selected_format:
            return
        self._selected_format = None
        self._reset_dataset_page()
        self._update_selected_panel()
        self._schedule_recompute_lists(0, refresh=_REFRESH_FILTER_IMPACT)

    def _clear_all_selections(self) -> None:
        cancel_pending_tooltips()
        self._close_dataset_copy_menu()
        self._selected_dataset = None
        self._close_area_map_if_inappropriate()
        self._selected_categories = set()
        self._selected_categories_expanded = False
        self._selected_areas_expanded = False
        self._selected_projection = None
        self._selected_format = None
        self._clear_all_auto_selections()
        self._selected_areas = []
        self._area_signature = ()
        self._dataset_search_text = ""
        self._area_search_text = ""
        self.dataset_search.blockSignals(True)
        self.dataset_search.clear()
        self.dataset_search.blockSignals(False)
        self.area_search.blockSignals(True)
        self.area_search.clear()
        self.area_search.blockSignals(False)
        self._reset_dataset_page()
        self.category_view.selectionModel().clearSelection()
        self.projection_view.selectionModel().clearSelection()
        self.format_view.selectionModel().clearSelection()
        self.dataset_view.selectionModel().clearSelection()
        self._suppress_area_change = True
        try:
            self.area_model.set_checked_keys(set())
        finally:
            self._suppress_area_change = False
        self._update_area_all_checkbox()
        self._sync_area_map_selection()
        self._update_selected_panel()
        self._schedule_recompute_lists(0, scope="full")

    def _select_dataset_index(self, index, *, toggle: bool = False) -> None:
        if self._recompute_running:
            return
        ds = self.dataset_model.selected_payload(index)
        if not isinstance(ds, DatasetAvailability):
            return
        if ds.login_required:
            return
        if not toggle and self._selected_dataset and self._selected_dataset.metadata_uuid == ds.metadata_uuid:
            return
        previous_uuid = self._selected_dataset.metadata_uuid if self._selected_dataset else None
        if toggle and self._selected_dataset and self._selected_dataset.metadata_uuid == ds.metadata_uuid:
            self._selected_dataset = None
            self._clear_user_area_selection()
            self._clear_auto_area_selection()
        else:
            self._selected_dataset = ds
            self._start_single_dataset_enrichment(ds)
        if self._area_map_is_open() and previous_uuid != (
            self._selected_dataset.metadata_uuid if self._selected_dataset else None
        ):
            self._refresh_area_map_for_dataset_change()
        else:
            self._close_area_map_if_inappropriate()
        self._area_signature = ()
        self._area_populate_context = None
        self._update_selected_panel()
        self._schedule_recompute_lists(0, refresh=_REFRESH_DATASET)

    def _on_projection_clicked(self, index) -> None:
        if not index.isValid():
            return
        self._select_projection_index(index, toggle=True)

    def _select_projection_index(self, index, *, toggle: bool = False) -> None:
        if self._recompute_running:
            return
        item = self.projection_model.item(index.row())
        if item is not None and not item.isEnabled():
            return
        p = self.projection_model.selected_payload(index)
        if not isinstance(p, ProjectionOption):
            return
        if not toggle and self._selected_projection and self._selected_projection.code == p.code:
            return
        if toggle and self._selected_projection and self._selected_projection.code == p.code:
            self._selected_projection = None
            candidates = self._candidate_projections()
            if len(candidates) == 1 and candidates[0].code == p.code:
                self._auto_projection = candidates[0]
            else:
                self._auto_projection = None
            self._reapply_projection_selection(candidates)
            self._reset_dataset_page()
            self._update_selected_panel()
            self._schedule_recompute_lists(0, refresh=_REFRESH_FILTER_IMPACT)
            self.projection_view.viewport().update()
            return
        if toggle and self._auto_projection and not self._selected_projection and self._auto_projection.code == p.code:
            self._auto_projection = None
            self._selected_projection = p
            self._reapply_projection_selection(self._candidate_projections())
            self._reset_dataset_page()
            self._update_selected_panel()
            self._schedule_recompute_lists(0, refresh=_REFRESH_FILTER_IMPACT)
            return
        self._auto_projection = None
        self._selected_projection = p
        self._reset_dataset_page()
        self._update_selected_panel()
        self._schedule_recompute_lists(0, refresh=_REFRESH_FILTER_IMPACT)

    def _on_format_clicked(self, index) -> None:
        if not index.isValid():
            return
        self._select_format_index(index, toggle=True)

    def _select_format_index(self, index, *, toggle: bool = False) -> None:
        if self._recompute_running:
            return
        item = self.format_model.item(index.row())
        if item is not None and not item.isEnabled():
            return
        fmt = self.format_model.selected_payload(index)
        if not isinstance(fmt, FormatOption):
            return
        target = _format_filter_key(fmt)
        if not toggle and self._selected_format and _format_filter_key(self._selected_format) == target:
            return
        if toggle and self._selected_format and _format_filter_key(self._selected_format) == target:
            self._selected_format = None
            candidates = self._candidate_formats()
            if len(candidates) == 1 and _format_filter_key(candidates[0]) == target:
                self._auto_format = candidates[0]
            else:
                self._auto_format = None
            self._reapply_format_selection(candidates)
            self._reset_dataset_page()
            self._update_selected_panel()
            self._schedule_recompute_lists(0, refresh=_REFRESH_FILTER_IMPACT)
            self.format_view.viewport().update()
            return
        if toggle and self._auto_format and not self._selected_format and _format_filter_key(self._auto_format) == target:
            self._auto_format = None
            self._selected_format = fmt
            self._reapply_format_selection(self._candidate_formats())
            self._reset_dataset_page()
            self._update_selected_panel()
            self._schedule_recompute_lists(0, refresh=_REFRESH_FILTER_IMPACT)
            return
        self._auto_format = None
        self._selected_format = fmt
        self._reset_dataset_page()
        self._update_selected_panel()
        self._schedule_recompute_lists(0, refresh=_REFRESH_FILTER_IMPACT)

    def _clear_filters(self) -> None:
        self._selected_categories = set()
        self._selected_area_type = None
        self._selected_areas = []
        self._selected_projection = None
        self._selected_format = None
        self._clear_all_auto_selections()
        self._show_only_downloadable = False
        self._dataset_search_text = ""
        self._area_signature = ()
        self._category_signature = ()
        self._area_types_signature = ()
        self._reset_dataset_page()
        self.downloadable_filter.blockSignals(True)
        self.downloadable_filter.setChecked(False)
        self.downloadable_filter.blockSignals(False)
        self.dataset_search.blockSignals(True)
        self.dataset_search.clear()
        self.dataset_search.blockSignals(False)
        self._clear_area_search_filter(block_field_signals=True)
        self._update_area_details_visibility()
        for button in self.area_type_buttons.values():
            button.blockSignals(True)
            button.setChecked(False)
            button.blockSignals(False)
        self._schedule_recompute_lists(0)

    def _start_download_flow(self) -> None:
        ds = self._selected_dataset
        if ds and self._dataset_can_open_in_browser(ds):
            self._open_dataset_in_browser(ds)
            return
        fmt = self._effective_format()
        proj = self._effective_projection()
        if not (ds and fmt):
            return
        if ds.projections and not proj:
            return
        requires_area = self._dataset_requires_area(ds)
        areas_eff = self._effective_areas()
        if requires_area and not areas_eff:
            return
        folder = self._choose_download_folder()
        if not folder:
            return

        job_id = self._next_download_job_id()
        cancel_event = threading.Event()
        progress_dialog = self._get_or_create_download_progress_dialog()

        areas: list[AreaOption | None] = list(areas_eff) if requires_area else [None]
        area_type = self._active_area_type() if requires_area else None

        projection_code = proj.code if proj else None
        projection_part = proj.code if proj else "any"
        holder: dict[str, FuncWorker] = {}

        safe_title = "".join(ch for ch in ds.title if ch.isalnum() or ch in (" ", "_", "-")).strip().replace(" ", "_")
        spec = DownloadJobSpec(
            metadata_uuid=ds.metadata_uuid,
            area_type=area_type,
            format_name=fmt.name,
            projection_code=projection_code,
            base_url=ds.download_api_base,
            output_dir=Path(folder),
            safe_title=safe_title,
            projection_part=projection_part,
        )

        progress_items = [
            DownloadProgressItem(
                display_text=area_progress_display(area) if area else ds.title,
                zip_filename=build_target_path(spec, area, area_type).name,
            )
            for area in areas
        ]
        display_names = [item.display_text for item in progress_items]
        projection_label = proj.label if proj else "Any projection"
        progress_dialog.add_order(
            DownloadOrderInfo(
                job_id=job_id,
                dataset_title=ds.title,
                subheader=format_order_subheader(
                    area_count=len(progress_items),
                    projection=projection_label,
                    format_name=fmt.name,
                ),
                items=progress_items,
            )
        )
        progress_dialog.show()

        job = _DownloadJob(
            job_id=job_id,
            cancel=cancel_event,
            worker=None,
            dialog=progress_dialog,
        )
        self._download_jobs[job_id] = job
        packaging_queue = self._packaging_queue
        transfer_queue = self._transfer_queue

        class _DownloadReporter:
            def __init__(self) -> None:
                self._packaging_done = False
                self._active_transfers: dict[int, tuple[str, int, int | None]] = {}

            def preparing(self, message: str) -> None:
                if "worker" not in holder:
                    return
                suffix = ""
                waiting = packaging_queue.waiting_count
                if waiting:
                    suffix = f" ({waiting} ahead in packaging queue)"
                holder["worker"].signals.emit_progress(0, 0, f"{message}{suffix}")

            def packaging(self, ready: int, total: int) -> None:
                if "worker" not in holder or self._packaging_done:
                    return
                if ready >= total:
                    self._packaging_done = True
                holder["worker"].signals.emit_progress(
                    ready, total, f"Preparing order: {ready}/{total} files ready…"
                )

            def downloading(self, index: int, label: str, size: int | None) -> None:
                if "worker" not in holder:
                    return
                display = display_names[index] if 0 <= index < len(display_names) else label
                holder["worker"].signals.item_active.emit(index)
                self._active_transfers[index] = (display, 0, size)
                self._emit_transfer_status()

            def transfer(
                self,
                index: int,
                label: str,
                downloaded: int,
                total: int | None,
                *,
                force: bool = False,
            ) -> None:
                if "worker" not in holder:
                    return
                display = display_names[index] if 0 <= index < len(display_names) else label
                self._active_transfers[index] = (display, downloaded, total)
                self._emit_transfer_status()

            def _emit_transfer_status(self) -> None:
                if "worker" not in holder or not self._active_transfers:
                    return
                active = len(self._active_transfers)
                _index, (label, downloaded, total) = max(
                    self._active_transfers.items(),
                    key=lambda item: item[1][1] / max(item[1][2] or 1, 1),
                )
                if total:
                    progress = f"{_format_bytes(downloaded)} / {_format_bytes(total)}"
                else:
                    progress = _format_bytes(downloaded)
                if active > 1:
                    message = f"Downloading {active} files in parallel — {label}: {progress}"
                else:
                    message = f"Downloading {label}: {progress}"
                holder["worker"].signals.emit_progress(downloaded, total or 0, message)

        download_reporter = _DownloadReporter()

        def do_download() -> list[tuple[str, str]] | _PartialDownloadResult | _DownloadCancelledResult:
            tasks = [DownloadTask(index=index, area=a) for index, a in enumerate(areas)]

            def on_item_completed(index: int) -> None:
                if "worker" in holder:
                    holder["worker"].signals.item_completed.emit(index)
                download_reporter._active_transfers.pop(index, None)

            def on_item_failed(index: int, _label: str, _reason: str) -> None:
                if "worker" in holder:
                    holder["worker"].signals.item_failed.emit(index)
                download_reporter._active_transfers.pop(index, None)

            try:
                return run_batch_order_download(
                    tasks,
                    spec,
                    ned=self._nedlasting,
                    http=self._http,
                    reporter=download_reporter,
                    on_item_completed=on_item_completed,
                    on_item_failed=on_item_failed,
                    acquire_packaging_slot=packaging_queue.acquire,
                    release_packaging_slot=packaging_queue.release,
                    acquire_transfer_slot=transfer_queue.acquire,
                    release_transfer_slot=transfer_queue.release,
                    cancel=cancel_event,
                )
            except BatchDownloadPartialFailure as exc:
                return _PartialDownloadResult(exc.successes, exc.failures)
            except DownloadCancelled:
                return _DownloadCancelledResult()
            except RuntimeError:
                raise
            except Exception as exc:
                raise RuntimeError(str(exc)) from exc

        def on_finished() -> None:
            job = self._get_download_job(job_id)
            if job is not None:
                job.worker = None

        def on_done(results: object) -> None:
            job = self._get_download_job(job_id)
            dialog = job.dialog if job is not None else None
            queue_suffix = self._download_queue_status()

            if isinstance(results, _PartialDownloadResult):
                succeeded = len(results.successes)
                failed = len(results.failures)
                total = succeeded + failed
                show_connection_lost_dialog(
                    self,
                    succeeded=succeeded,
                    failed=failed,
                    total=total,
                    failed_labels=[label for label, _reason in results.failures],
                )
                if dialog is not None:
                    dialog.mark_all_complete(job_id)
                self._detach_download_job(job_id, remove_from_dialog=False)
                self._set_status(f"Connection lost — download interrupted{queue_suffix}")
                return

            if isinstance(results, _DownloadCancelledResult):
                self._detach_download_job(job_id, remove_from_dialog=True)
                self._set_status(f"Download cancelled.{queue_suffix}")
                return

            if dialog is not None:
                dialog.mark_all_complete(job_id)
            self._detach_download_job(job_id, remove_from_dialog=False)
            self._set_status(f"Download complete.{queue_suffix}")

        def on_error(tb: str) -> None:
            job = self._get_download_job(job_id)
            dialog = job.dialog if job is not None else None
            queue_suffix = self._download_queue_status()

            if "DownloadCancelled" in tb:
                self._detach_download_job(job_id, remove_from_dialog=True)
                self._set_status(f"Download cancelled.{queue_suffix}")
                return

            logger.error("Download failed: %s", tb)

            if "NetworkError" in tb:
                if dialog is not None:
                    dialog.allow_close()
                show_connection_lost_dialog(
                    self,
                    succeeded=0,
                    failed=1,
                    total=1,
                )
                self._detach_download_job(job_id, remove_from_dialog=False)
                self._set_status(f"Connection lost — download interrupted{queue_suffix}")
                return

            self._detach_download_job(job_id, remove_from_dialog=True)
            self._set_status(f"Download failed.{queue_suffix}")
            self._download_with_per_area_prompts()

        self._set_status(f"Downloading…{self._download_queue_status()}")
        worker = FuncWorker(do_download)
        holder["worker"] = worker
        job.worker = worker
        connect_worker_signals(
            worker,
            result=on_done,
            error=on_error,
            finished=on_finished,
            progress=self._on_download_progress,
            item_completed=lambda idx: progress_dialog.mark_item_complete(job_id, idx),
            item_failed=lambda idx: progress_dialog.mark_item_failed(job_id, idx),
            item_active=lambda idx: progress_dialog.mark_item_active(job_id, idx),
        )
        self._start_worker(worker)

    def _on_download_done(self, results: object) -> None:
        # Per-job handlers are wired in _start_download_flow.
        if isinstance(results, list) and results:
            self._set_status("Download complete.")

    def _on_download_progress(self, done: int, total: int, message: str) -> None:
        logger.debug("Download progress %s/%s: %s", done, total, message)
        queue_suffix = self._download_queue_status()
        self._set_status(f"{message}{queue_suffix}")

    def _on_download_error(self, tb: str) -> None:
        logger.error("Download failed: %s", tb)

    def _download_with_per_area_prompts(self) -> None:
        ds = self._selected_dataset
        areas_eff = self._effective_areas()
        fmt_eff = self._effective_format()
        proj_eff = self._effective_projection()
        if not (ds and fmt_eff and areas_eff):
            return
        if ds.projections and not proj_eff:
            return
        folder = self._choose_download_folder()
        if not folder:
            return

        proj = proj_eff
        projection_code = proj.code if proj else None
        projection_part = proj.code if proj else "any"
        current_format = fmt_eff
        area_type = self._active_area_type()

        for a in list(areas_eff):
            if not area_supports(
                a,
                projection_code=projection_code,
                format_name=current_format.name,
            ):
                continue
            fmt = current_format
            while True:
                try:
                    ok, reason = self._nedlasting.validate_area_format_projection(
                        metadata_uuid=ds.metadata_uuid,
                        area_type=area_type,
                        area_code=a.code,
                        format_name=fmt.name,
                        projection_code=projection_code,
                        base_url=ds.download_api_base,
                        area_option=a,
                    )
                    if not ok:
                        raise RuntimeError(reason or "Not available.")
                    ref = self._nedlasting.place_order(
                        metadata_uuid=ds.metadata_uuid,
                        area_type=area_type,
                        area_code=a.code,
                        format_name=fmt.name,
                        projection_code=projection_code,
                        base_url=ds.download_api_base,
                        area_option=a,
                    )
                    url = self._nedlasting.poll_download_url(ref, base_url=ds.download_api_base)
                    size = self._http.content_length(url)
                    self._set_status(f"Downloading {a.label} ({_format_bytes(size)})…")
                    safe_title = "".join(ch for ch in ds.title if ch.isalnum() or ch in (" ", "_", "-")).strip().replace(" ", "_")
                    target = Path(folder) / f"{safe_title}_{area_type}_{a.code}_{fmt.name}_{projection_part}.zip"
                    self._http.download(url, str(target))
                    break
                except Exception as e:
                    # Prompt: skip or choose a different format for this area.
                    choices = [f.label for f in (ds.formats or [])]
                    msg = themed_message_box(
                        self,
                        title="Download not available",
                        text=f"Could not download for:\n\n{a.label}\n\nReason:\n{e}\n",
                        icon="warning",
                    )
                    skip_btn = msg.addButton("Skip this area", QMessageBox.RejectRole)
                    msg.addButton("Choose another format…", QMessageBox.AcceptRole)
                    msg.exec()
                    if msg.clickedButton() is skip_btn:
                        break
                    if not choices:
                        box = themed_message_box(
                            self,
                            title="No formats available",
                            text="No alternative formats are available for this dataset.",
                            icon="warning",
                        )
                        box.exec()
                        break
                    picked, ok = QInputDialog.getItem(
                        self,
                        "Choose format",
                        f"Select a different format for {a.label}:",
                        choices,
                        0,
                        False,
                    )
                    if not ok or not picked:
                        break
                    # Map label back to FormatOption
                    for f in ds.formats:
                        if f.label == picked:
                            fmt = f
                            break
                    continue

        self._set_status("Downloads finished (with possible skips).")

    def _on_dataset_refs_loaded(self, refs: object) -> None:
        if not isinstance(refs, list):
            return
        self._dataset_refs = [r for r in refs if isinstance(r, DatasetRef)]
        # Build initial availability list (no enrichment yet)
        indexed = self._discovery.load_indexed()
        existing = {d.metadata_uuid: d for d in indexed or self._datasets}
        merged: list[DatasetAvailability] = []
        for r in self._dataset_refs:
            cached = existing.get(r.metadata_uuid)
            if cached:
                if not cached.enriched and r.title:
                    cached.title = r.title
                elif not cached.title:
                    cached.title = r.title
                merged.append(cached)
            else:
                merged.append(DatasetAvailability(metadata_uuid=r.metadata_uuid, title=r.title))
        self._assign_datasets(sorted(merged, key=lambda d: _norwegian_sort_key(d.title)))
        self._schedule_recompute_lists(0)
        self._set_status(
            _status_message(
                f"Indexed {len(self._datasets)} datasets",
                "Checking Kartkatalog and download metadata",
            )
        )

        self._start_background_enrichment()

    def _start_background_enrichment(self) -> None:
        self._enrichment_cancel.clear()
        holder: dict[str, FuncWorker] = {}

        def enrich_all() -> tuple[list[DatasetAvailability], object]:
            ordered = self._enrichment_order()
            cached_by_uuid = {d.metadata_uuid: d for d in self._datasets}

            def on_progress(done: int, total: int, message: str) -> None:
                if "worker" in holder:
                    holder["worker"].signals.emit_progress(done, total, message)

            return self._discovery.enrich_parallel(
                ordered,
                cached_by_uuid=cached_by_uuid,
                on_progress=on_progress,
                cancel=self._enrichment_cancel,
            )

        worker = FuncWorker(enrich_all)
        holder["worker"] = worker
        self._bulk_enrichment = True
        connect_worker_signals(
            worker,
            result=self._on_enriched,
            error=self._on_enrichment_error,
            progress=self._on_enrichment_progress,
            finished=self._on_enrichment_finished,
        )
        self._start_worker(worker)

    def _enrichment_order(self) -> list[DatasetAvailability]:
        enriched = self._discovery.enriched_uuids()
        by_uuid = {d.metadata_uuid: d for d in self._datasets}
        ordered: list[DatasetAvailability] = []
        seen: set[str] = set()

        def add(uuid: str | None) -> None:
            if not uuid or uuid in seen or uuid in enriched:
                return
            ds = by_uuid.get(uuid)
            if ds is None:
                return
            seen.add(uuid)
            ordered.append(ds)

        if self._selected_dataset:
            add(self._selected_dataset.metadata_uuid)
        for uuid in self._displayed_dataset_uuids[:150]:
            add(uuid)
        for ds in self._datasets:
            add(ds.metadata_uuid)
        return ordered

    def _start_single_dataset_enrichment(self, ds: DatasetAvailability) -> None:
        if ds.metadata_uuid in self._discovery.enriched_uuids() or ds.metadata_uuid in self._enriching_uuids:
            return
        self._enriching_uuids.add(ds.metadata_uuid)

        cached = self._datasets[self._dataset_index_by_uuid[ds.metadata_uuid]] if ds.metadata_uuid in self._dataset_index_by_uuid else ds
        worker = FuncWorker(lambda item=ds, known=cached: self._discovery.enrich_one(item, cached=known).dataset)
        def clear_flag() -> None:
            self._enriching_uuids.discard(ds.metadata_uuid)

        connect_worker_signals(
            worker,
            result=self._on_dataset_enriched_partial,
            error=self._show_error,
            finished=clear_flag,
        )
        self._start_worker(worker)

    def _on_dataset_enriched_partial(self, item: object) -> None:
        if not isinstance(item, DatasetAvailability):
            return
        if self._bulk_enrichment:
            index = self._dataset_index_by_uuid.get(item.metadata_uuid)
            if index is None:
                self._dataset_index_by_uuid[item.metadata_uuid] = len(self._datasets)
                self._datasets.append(item)
            else:
                self._datasets[index] = item
            self._invalidate_filter_index()
            if not self._selected_dataset:
                self._schedule_recompute_lists(
                    800,
                    scope="browse",
                    refresh=_REFRESH_BROWSE_FILTERS,
                )
            return
        index = self._dataset_index_by_uuid.get(item.metadata_uuid)
        if index is None:
            self._dataset_index_by_uuid[item.metadata_uuid] = len(self._datasets)
            self._datasets.append(item)
        else:
            self._datasets[index] = item
        self._invalidate_filter_index()
        if self._selected_dataset and self._selected_dataset.metadata_uuid == item.metadata_uuid:
            self._selected_dataset = item
            self._schedule_recompute_lists(0)
            return
        if self._show_only_downloadable:
            self._schedule_recompute_lists(delay_ms=1000)
            return
        if item.metadata_uuid in self._displayed_dataset_uuids:
            self._update_visible_dataset_row(item)

    def _on_enrichment_progress(self, done: int, total: int, message: str) -> None:
        logger.debug("Enrichment progress %s/%s: %s", done, total, message)
        self._set_status(message)

    def _on_enriched(self, payload: object) -> None:
        if not isinstance(payload, tuple) or len(payload) != 2:
            return
        enriched, stats = payload
        if not isinstance(enriched, list):
            return
        by_uuid = {d.metadata_uuid: d for d in self._datasets}
        for item in enriched:
            if isinstance(item, DatasetAvailability):
                by_uuid[item.metadata_uuid] = item
        self._assign_datasets(sorted(by_uuid.values(), key=lambda d: _norwegian_sort_key(d.title)))
        if self._selected_dataset:
            selected_uuid = self._selected_dataset.metadata_uuid
            self._selected_dataset = next((d for d in self._datasets if d.metadata_uuid == selected_uuid), None)
        self._schedule_recompute_lists(0)
        if hasattr(stats, "skipped"):
            self._set_status(
                _status_message(
                    "Ready",
                    f"{len(self._datasets)} datasets indexed",
                    f"last metadata check: {stats.total} processed",
                    f"{stats.skipped} unchanged",
                    f"{stats.light_refresh} light refresh",
                    f"{stats.full_refresh} full refresh",
                )
            )
        else:
            self._set_status(_status_message("Ready", f"{len(self._datasets)} datasets indexed"))

    def _on_enrichment_error(self, tb: str) -> None:
        self._bulk_enrichment = False
        self._set_toolbar_busy(refresh=False, reset=False)
        self._show_error(tb)

    def _on_enrichment_finished(self) -> None:
        self._bulk_enrichment = False
        self._set_toolbar_busy(refresh=False, reset=False)

    def _on_background_task_error(self, tb: str) -> None:
        self._set_toolbar_busy(refresh=False, reset=False)
        self._show_error(tb)

    def _refresh_all(self) -> None:
        if self._refresh_busy or self._reset_busy:
            return
        self._set_toolbar_busy(refresh=True)
        self._set_status("Refreshing…")
        self._assign_datasets([])
        self._dataset_refs = []
        self._clear_filters()
        self._load_initial_data()

    def _stop_background_work(self, *, wait_ms: int = 8000) -> None:
        self._enrichment_cancel.set()
        self._bulk_enrichment = False
        app = QApplication.instance()
        if app is not None:
            pool = app.threadPool()
            pool.clear()
            pool.waitForDone(wait_ms)

    def _reset_cache(self) -> None:
        msg = themed_message_box(
            self,
            title="Reset cache",
            text="This deletes the local dataset index on disk and reloads everything from Geonorge.",
            informative_text=(
                "Use this for a clean slate. Reloading all metadata requires an internet connection "
                "and may take a while."
            ),
            icon="warning",
        )
        yes_btn = msg.addButton("Reset cache", QMessageBox.AcceptRole)
        msg.addButton("Cancel", QMessageBox.RejectRole)
        msg.setDefaultButton(yes_btn)
        msg.exec()
        if msg.clickedButton() is not yes_btn:
            return
        if self._refresh_busy or self._reset_busy:
            return
        self._set_toolbar_busy(refresh=True, reset=True)
        self._set_status("Resetting local cache…")
        self._stop_background_work()

        def run_reset() -> bool:
            self._discovery.clear_cache()
            return True

        worker = FuncWorker(run_reset)
        connect_worker_signals(
            worker,
            result=lambda _: self._on_cache_reset_done(),
            error=self._on_cache_reset_failed,
        )
        self._start_worker(worker)

    def _on_cache_reset_done(self) -> None:
        self._assign_datasets([])
        self._dataset_refs = []
        self._selected_dataset = None
        self._selected_areas = []
        self._selected_projection = None
        self._selected_format = None
        self._selected_categories = set()
        self._dataset_page = 0
        self._enrichment_cancel.clear()
        self._clear_filters()
        self._load_initial_data()

    def _on_cache_reset_failed(self, tb: str) -> None:
        self._set_toolbar_busy(refresh=False, reset=False)
        self._show_error(tb)
        self._set_status("Cache reset failed. See log file for details.")

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._configure_area_columns()
        self._configure_dataset_columns()

    def closeEvent(self, event) -> None:
        if self._downloads_in_progress():
            if not self._confirm_quit_while_downloading():
                event.ignore()
                return
            self._cancel_all_downloads()
        logger.info("Closing window; stopping background workers")
        self._stop_background_work()
        super().closeEvent(event)

    def _show_error(self, tb: str) -> None:
        logger.error("Unhandled background error: %s", tb)
        self._set_status("Error. See log file for details.")
        box = themed_message_box(self, title="Error", text=tb, icon="warning")
        box.exec()

