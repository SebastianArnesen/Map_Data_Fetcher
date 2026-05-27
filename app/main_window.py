from __future__ import annotations

import logging
import math
import re
import threading
from pathlib import Path
from urllib.parse import quote

from PySide6.QtCore import QEvent, QModelIndex, QPoint, QRectF, Signal, QSize, Qt, QItemSelectionModel, QTimer, QUrl
from PySide6.QtGui import (
    QBrush,
    QColor,
    QCursor,
    QDesktopServices,
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
    QStatusBar,
    QToolButton,
    QToolTip,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from geonorge.client import HttpClient

# Area table column layout (checkbox | code | name).
_AREA_CHECKBOX_COLUMN_W = 28
_AREA_CODE_COLUMN_W = 82  # 10px narrower than before so Name sits closer to Code
from geonorge.catalog import normalize_categories
from geonorge.discovery import DiscoveryService
from geonorge.models import AreaOption, AreaType, DatasetAvailability, DatasetRef, FormatOption, ProjectionOption
from geonorge.nedlasting import NedlastingClient

from app.dialogs import themed_message_box
from app.download_progress import DownloadProgressDialog
from app.filter_index import DatasetFilterIndex, format_filter_key
from app.theme import (
    SHARED,
    apply_base_style,
    build_stylesheet,
    busy_overlay_fill,
    checkbox_fill_border,
    checkbox_tick_color,
    palette_for,
    qcolor,
    resolve_light_mode,
    set_filter_busy_flag,
    theme_toggle_colors,
    theme_toggle_knob_border,
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
    DatasetItemDelegate,
    ExternalLinkWidget,
    SimpleListModel,
    CopyableListView,
    CopyableTreeView,
    DatasetTreeView,
    clear_dataset_index_widgets,
    clear_list_index_widgets,
    clear_tree_index_widgets,
    TwoColumnListModel,
)
from app.tooltip_delay import cancel_pending_tooltips
from app.workers import FuncWorker

logger = logging.getLogger(__name__)

# Selected panel: collapse long category/area lists (>3 items → show 2 + toggle).
_SELECTED_GROUP_COLLAPSE_AFTER = 3
_SELECTED_GROUP_COLLAPSED_VISIBLE = 2

# Avoid building a multi-thousand-row area table when browsing filters without a dataset.
_AREA_TABLE_ROW_LIMIT = 600

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


def _check_state_value(state: object) -> int:
    if hasattr(state, "value"):
        return int(state.value)  # type: ignore[arg-type]
    if state is None:
        return int(Qt.Unchecked.value)
    return int(state)  # type: ignore[arg-type]


class HeaderCheckBox(QCheckBox):
    def paintEvent(self, event) -> None:
        rect = QRectF(5, (self.height() - 13) / 2, 13, 13)
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


class ElidedLabel(QLabel):
    """Single-line label that ellipsizes; never expands layouts with the full text width."""

    def __init__(self, text: str = ""):
        super().__init__(text)
        self._full_text = text
        self.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.setWordWrap(False)

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


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Geonorge Datasets")
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
        self._show_only_downloadable = False
        self._dataset_search_text = ""
        self._area_search_text = ""
        self._area_display_name_only = False
        self._active_workers: list[FuncWorker] = []
        self._area_sort_column = "name"
        self._area_sort_ascending = True
        self._suppress_area_change = False
        self._suppress_single_select_change = False
        self._hover_scroll_widgets: list[QWidget] = []
        self._area_signature: tuple[tuple[str, str], ...] = ()
        self._dataset_signature: tuple[tuple[str, str, str], ...] = ()
        self._projection_signature: tuple[str, ...] = ()
        self._format_signature: tuple[str, ...] = ()
        self._category_signature: tuple[str, ...] = ()
        self._area_types_signature: tuple[AreaType, ...] = ()
        self._area_all_previous_state = Qt.Unchecked
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
        self._download_progress_dialog: DownloadProgressDialog | None = None
        self._build_ui()
        self._apply_style()
        self._wire_events()
        self._schedule_recompute_lists(0)

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
        toolbar_layout.addWidget(self.refresh_button)
        toolbar_layout.addWidget(self.reset_cache_button)
        toolbar_layout.addStretch(1)
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
        self.category_label = QLabel("Categories")
        self.category_count_label = QLabel("(0)")
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
        self.area_type_widget.setFixedHeight(38)
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
            button.setAutoExclusive(False)
            button.setCursor(Qt.PointingHandCursor)
            self.area_type_group.addButton(button, i)
            area_type_layout.addWidget(button)
        area_type_layout.addStretch(1)

        self.area_search_row = QWidget()
        area_search_layout = QHBoxLayout(self.area_search_row)
        area_search_layout.setContentsMargins(0, 0, 0, 0)
        area_search_layout.setSpacing(0)
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
        area_search_combo_layout.addWidget(self.area_search, 1)
        area_search_combo_layout.addWidget(self.area_search_button, 0)
        area_search_layout.addWidget(self.area_search_combo, 1)

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
        self.area_label = QLabel("Areas")
        self.area_count_label = QLabel("")
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
        area_list_layout.addWidget(self.area_search_row)
        area_list_layout.addWidget(self.area_header)
        area_list_layout.addWidget(self.area_view, 1)

        self.area_panel_fill = QWidget()
        self.area_panel_fill.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        areas_layout.addWidget(self.area_heading)
        areas_layout.addWidget(self.area_type_widget)
        areas_layout.addWidget(self.area_list_section, 1)
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
        self.dataset_label = QLabel("Datasets")
        self.dataset_count_label = QLabel("(0)")
        self.dataset_count_label.setObjectName("secondaryHeaderLabel")
        self.dataset_page_label = QLabel("")
        self.dataset_page_label.setObjectName("secondaryHeaderLabel")
        self.dataset_prev_button = PagerButton("prev")
        self.dataset_next_button = PagerButton("next")
        dataset_header_layout.addWidget(self.dataset_label)
        dataset_header_layout.addWidget(self.dataset_count_label)
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
        self.projection_label = QLabel("Projection")
        self.projection_count_label = QLabel("(0)")
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
        self.format_label = QLabel("Format")
        self.format_count_label = QLabel("(0)")
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
        self.selected_label = QLabel("Selected")
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
        self.selected_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.selected_scroll.setFrameShape(QFrame.NoFrame)
        self.selected_scroll.setAttribute(Qt.WA_StyledBackground, True)
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
        selected_column_layout.addWidget(self.selected_panel, 1)
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
        self.status_text = QLabel("Loading…")
        self.status_text.setObjectName("statusLabel")
        self.status.addWidget(self.status_text, 1)
        self.copy_status_text = QLabel("")
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

        self.format_model = SimpleListModel()
        self.format_view.setModel(self.format_model)

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
        apply_base_style()
        self._on_theme_toggle(False)

    def _on_theme_toggle(self, light_mode: bool) -> None:
        self._light_mode = bool(light_mode)
        self.setStyleSheet(build_stylesheet(palette_for(self._light_mode)))
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
        if hasattr(self, "area_view"):
            clear_tree_index_widgets(
                self.area_view,
                [1] if self._area_display_name_only else [1, 2],
            )
        self._apply_clickable_cursors(self)

    def _wire_events(self) -> None:
        self.area_type_group.buttonClicked.connect(self._on_area_type_button_clicked)
        self.area_model.selection_changed.connect(self._on_areas_changed)
        self.area_all_checkbox.pressed.connect(self._remember_area_all_state)
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
        self.dataset_view.clicked.connect(self._on_dataset_clicked)
        self.dataset_view.selectionModel().currentChanged.connect(self._on_dataset_current_changed)
        self.dataset_prev_button.clicked.connect(self._on_dataset_prev_page)
        self.dataset_next_button.clicked.connect(self._on_dataset_next_page)
        self.projection_view.clicked.connect(self._on_projection_clicked)
        self.format_view.clicked.connect(self._on_format_clicked)
        self.refresh_button.clicked.connect(self._refresh_all)
        self.reset_cache_button.clicked.connect(self._reset_cache)
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
        self.theme_toggle.light_mode_changed.connect(self._on_theme_toggle)
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

        if selected_copy is not None and obj is selected_copy:
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
        clickable = index.isValid()
        if view is self.dataset_view:
            clickable = index.isValid() and index.column() in (
                DATASET_COL_TITLE,
                DATASET_COL_COPY,
                DATASET_COL_LINK,
            )
        view.viewport().setCursor(Qt.PointingHandCursor if clickable else Qt.ArrowCursor)

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
        flags = Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard
        for label in root.findChildren(QLabel):
            label.setTextInteractionFlags(flags)
            # Needed for Ctrl+C on selected QLabel text.
            label.setFocusPolicy(Qt.ClickFocus)
            label.setCursor(Qt.ArrowCursor)

    def _apply_clickable_cursors(self, root: QWidget | None = None) -> None:
        root = root or self
        for widget in root.findChildren(QWidget):
            if isinstance(widget, (QPushButton, QToolButton, QRadioButton, QCheckBox)):
                widget.setCursor(Qt.PointingHandCursor)
        self.dataset_search.setCursor(Qt.IBeamCursor)
        self.area_search.setCursor(Qt.IBeamCursor)

    @staticmethod
    def _area_type_shows_area_list(area_type: AreaType | None) -> bool:
        return area_type is not None and area_type != "landsdekkende"

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

    def _update_area_details_visibility(self) -> None:
        show_list = self._area_type_shows_area_list(self._selected_area_type)
        self.area_list_section.setVisible(show_list)
        self.area_panel_fill.setVisible(not show_list)
        layout = self.areas_panel.layout()
        if layout is not None:
            list_idx = layout.indexOf(self.area_list_section)
            fill_idx = layout.indexOf(self.area_panel_fill)
            if list_idx >= 0:
                layout.setStretch(list_idx, 1 if show_list else 0)
            if fill_idx >= 0:
                layout.setStretch(fill_idx, 0 if show_list else 1)
        if show_list:
            self.area_all_checkbox.setVisible(True)
            self.area_code_header.setVisible(not self._area_display_name_only)
        else:
            self.area_all_checkbox.setVisible(False)
            self.area_code_header.setVisible(False)
            if self._selected_area_type is None:
                self._area_search_text = ""
                self.area_search.blockSignals(True)
                self.area_search.clear()
                self.area_search.blockSignals(False)

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

    def _start_worker(self, worker: FuncWorker) -> None:
        self._active_workers.append(worker)

        def remove_worker() -> None:
            if worker in self._active_workers:
                self._active_workers.remove(worker)

        worker.signals.finished.connect(remove_worker)
        QApplication.instance().threadPool().start(worker)  # type: ignore[union-attr]

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
        worker.signals.result.connect(self._on_dataset_refs_loaded)
        worker.signals.error.connect(self._on_background_task_error)
        self._start_worker(worker)

    def _sync_dataset_refs_from_cache(self) -> None:
        self._dataset_refs = [DatasetRef(metadata_uuid=d.metadata_uuid, title=d.title) for d in self._datasets]

    def _populate_area_type_list(self) -> None:
        available = tuple(self._available_area_types_for_selected_dataset())
        if available == self._area_types_signature:
            for area_type, button in self.area_type_buttons.items():
                button.blockSignals(True)
                button.setChecked(area_type == self._selected_area_type)
                button.blockSignals(False)
            return
        self._area_types_signature = available
        if self._selected_area_type and self._selected_area_type not in available:
            self._selected_area_type = None
            self._selected_areas = []
            self._area_signature = ()
        for area_type, button in self.area_type_buttons.items():
            visible = area_type in available
            button.setVisible(visible)
            button.setEnabled(visible)
            button.setToolTip("" if visible else "This area type is not available for the selected dataset.")
            button.blockSignals(True)
            button.setChecked(area_type == self._selected_area_type)
            button.blockSignals(False)

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
        else:
            self._selected_areas = []
        if self._selected_projection:
            if not any(p.code == self._selected_projection.code for p in self._candidate_projections()):
                self._selected_projection = None
        if self._selected_format:
            target = _format_filter_key(self._selected_format)
            if not any(_format_filter_key(f) == target for f in self._candidate_formats()):
                self._selected_format = None

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
        QApplication.processEvents()
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
        self._recompute_running = True
        refresh = self._pending_refresh or _REFRESH_ALL
        self._pending_refresh = frozenset()
        scope = self._recompute_scope
        self._recompute_scope = "full"
        try:
            self._validate_selections()
            if "categories" in refresh:
                self._populate_categories()
            if "datasets" in refresh:
                self._apply_dataset_filter()
            if "area_types" in refresh:
                self._populate_area_type_list()
            if "areas" in refresh:
                self._populate_areas_for_type(self._selected_area_type, preserve_selection=True)
            if "projections" in refresh:
                self._populate_projections()
            if "formats" in refresh:
                self._populate_formats()
            if "selected" in refresh:
                self._update_selected_panel()
            if "download" in refresh:
                self._update_download_button_state()
        finally:
            self._recompute_running = False
            self._end_filter_panel_busy()

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
        if self._filter_busy_depth == 0 and scope == "full":
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

    def _add_selected_row(
        self,
        *,
        text: str,
        tooltip: str = "",
        is_dataset_title: bool = False,
        show_copy: bool = False,
        show_open_link: bool = False,
        open_link_tooltip: str = "",
        on_clear: object,
    ) -> None:
        row = QWidget()
        row.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        row.setMinimumWidth(0)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 1, 0, 1)
        row_layout.setSpacing(6)
        label = ElidedLabel(text)
        label.setObjectName("selectedDatasetTitle" if is_dataset_title else "selectedDatasetValue")
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
        section_started = False

        if self._selected_dataset:
            ds = self._selected_dataset
            tags = self._dataset_original_category_label(ds)
            uuid = ds.metadata_uuid
            tip = f"{ds.title}\n{uuid}\n{tags}" if tags else f"{ds.title}\n{uuid}"
            self._add_selected_row(
                text=ds.title,
                tooltip=tip,
                is_dataset_title=True,
                show_copy=True,
                show_open_link=True,
                open_link_tooltip=self._dataset_metadata_url(ds),
                on_clear=self._clear_selected_dataset,
            )
            has_items = True
            section_started = True

        if self._selected_categories:
            if section_started:
                self._add_selected_section_gap()
            categories = sorted(self._selected_categories, key=_norwegian_sort_key)
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
            section_started = True

        if self._selected_areas:
            if section_started:
                self._add_selected_section_gap()
            areas = sorted(self._selected_areas, key=lambda a: _norwegian_sort_key(a.label))
            if len(areas) <= _SELECTED_GROUP_COLLAPSE_AFTER:
                self._selected_areas_expanded = False

            def _add_area_row(area: AreaOption) -> None:
                self._add_selected_row(
                    text=area.label,
                    tooltip=area.label,
                    on_clear=lambda checked=False, a=area: self._clear_selected_area_one(a),
                )

            self._add_collapsible_selected_items(
                areas,
                expanded=self._selected_areas_expanded,
                on_show_more=lambda: self._set_selected_areas_expanded(True),
                on_show_less=lambda: self._set_selected_areas_expanded(False),
                add_item=_add_area_row,
            )
            has_items = True
            section_started = True

        if self._selected_projection:
            if section_started:
                self._add_selected_section_gap()
            proj_text = self._selected_projection.label
            self._add_selected_row(
                text=proj_text,
                tooltip=proj_text,
                on_clear=self._clear_selected_projection,
            )
            has_items = True
            section_started = True

        if self._selected_format:
            if section_started:
                self._add_selected_section_gap()
            fmt_text = self._selected_format.label
            self._add_selected_row(
                text=fmt_text,
                tooltip=fmt_text,
                on_clear=self._clear_selected_format,
            )
            has_items = True

        self.clear_all_selections_button.setVisible(has_items)
        if not has_items:
            none_label = ElidedLabel("None")
            none_label.setObjectName("selectedDatasetValue")
            none_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
            self.selected_rows_layout.addWidget(none_label, 0, Qt.AlignTop)
        self.selected_scroll.verticalScrollBar().setValue(0)

    def _reset_dataset_page(self) -> None:
        if self._dataset_page == 0:
            return
        self._dataset_page = 0
        self._dataset_signature = ()

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
            area_cols = [1] if self._area_display_name_only else [1, 2]
            clear_tree_index_widgets(self.area_view, area_cols)
            self._suppress_area_change = True
            try:
                self.area_model.set_items([])
            finally:
                self._suppress_area_change = False
            self._update_area_all_checkbox()
            self.area_view.setCursor(Qt.ArrowCursor)
            self.area_view.viewport().setCursor(Qt.ArrowCursor)
            self._update_area_header_visibility()
            return
        self.area_view.setCursor(Qt.ArrowCursor)
        self.area_view.viewport().setCursor(Qt.ArrowCursor)
        if preserve_selection:
            checked_keys = {a.code for a in self._selected_areas}
        else:
            checked_keys = set()
        scroll_value = self.area_view.verticalScrollBar().value()
        all_areas = self._sort_areas(self._candidate_areas(area_type))
        if area_type == "landsdekkende":
            total = len(all_areas)
            self.area_count_label.setText(f"({total:,})" if total else "")
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
                self.area_model.set_items([])
            finally:
                self._suppress_area_change = False
            self._selected_areas = self._entire_country_selection(
                all_areas,
                preserve_selection=preserve_selection,
            )
            self._update_area_all_checkbox()
            self._update_area_details_visibility()
            return
        self._area_display_name_only = self._area_table_name_only(area_type, all_areas)
        areas = self._filter_areas_by_search(all_areas)
        total_areas = len(areas)
        self.area_count_label.setText(f"({total_areas:,})")
        if total_areas > _AREA_TABLE_ROW_LIMIT:
            self.area_label.setText("Areas")
            display_areas = areas[:_AREA_TABLE_ROW_LIMIT]
            signature = ("truncated", area_type, total_areas, self._area_search_text)
        else:
            self.area_label.setText("Areas")
            display_areas = areas
            signature = tuple((a.code, a.name) for a in areas)
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
            self.area_model.set_items(items, name_only=self._area_display_name_only)
            if usable_keys:
                self.area_model.set_checked_keys(usable_keys)
            elif signature != previous_signature and len(items) == 1:
                self.area_model.auto_select_if_single_option()
        finally:
            self._suppress_area_change = False
        self._configure_area_columns()
        QTimer.singleShot(0, lambda value=scroll_value: self.area_view.verticalScrollBar().setValue(value))
        self._selected_areas = self.area_model.checked_payloads()
        self._update_area_all_checkbox()
        self._update_area_header_visibility()

    def _sort_areas(self, areas: list[AreaOption]) -> list[AreaOption]:
        reverse = not self._area_sort_ascending
        if self._area_sort_column == "code":
            return sorted(areas, key=lambda a: _code_sort_key(a.code), reverse=reverse)
        return sorted(areas, key=lambda a: (_norwegian_sort_key(a.name), _code_sort_key(a.code)), reverse=reverse)

    def _apply_dataset_filter(self) -> None:
        clear_dataset_index_widgets(self.dataset_view)
        index = self._ensure_filter_index()
        mask = self._compose_filter_mask(ignore={"dataset"})
        scroll_value = self.dataset_view.verticalScrollBar().value()

        filtered: list[DatasetAvailability] = list(self._login_required_datasets)
        disabled_ids = {id(ds) for ds in self._login_required_datasets}
        filtered.extend(index.datasets_for_mask(mask))

        filtered.sort(key=lambda d: _norwegian_sort_key(d.title))
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
        self.projection_count_label.setText(f"({len(candidates):,})")
        signature = tuple(p.code for p in candidates)
        previous_signature = self._projection_signature
        self._projection_signature = signature

        selection = self.projection_view.selectionModel()
        was_blocked = selection.blockSignals(True)
        self._suppress_single_select_change = True
        try:
            if signature != previous_signature:
                self.projection_model.set_items(
                    [((p.name.strip() if p.name and p.name.strip() else p.code), p) for p in candidates],
                    tooltips_by_id={id(p): p.label for p in candidates},
                )
            self._reapply_projection_selection(candidates)
        finally:
            self._suppress_single_select_change = False
            selection.blockSignals(was_blocked)
        clear_list_index_widgets(self.projection_view)

    def _populate_formats(self) -> None:
        candidates = self._candidate_formats()
        self.format_count_label.setText(f"({len(candidates):,})")
        signature = tuple(_format_filter_key(f) for f in candidates)
        previous_signature = self._format_signature
        self._format_signature = signature

        selection = self.format_view.selectionModel()
        was_blocked = selection.blockSignals(True)
        self._suppress_single_select_change = True
        try:
            if signature != previous_signature:
                self.format_model.set_items([(f.label, f) for f in candidates])
            self._reapply_format_selection(candidates)
        finally:
            self._suppress_single_select_change = False
            selection.blockSignals(was_blocked)
        clear_list_index_widgets(self.format_view)

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
        if self._dataset_requires_area(ds) and self._selected_areas:
            return [area.label for area in self._selected_areas]
        return [ds.title]

    def _download_task_count(self) -> int:
        return len(self._download_task_labels())

    def _close_download_progress_dialog(self) -> None:
        if self._download_progress_dialog is not None:
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
            if self._dataset_requires_area(ds) and (not self._selected_area_type or not self._selected_areas):
                reasons.append("Select an area.")
            if ds.projections and not self._selected_projection:
                reasons.append("Select a projection.")
        if not self._selected_format:
            reasons.append("Select a format.")

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
        selected_area_type: AreaType | None = None
        for area_type, candidate in self.area_type_buttons.items():
            if candidate is button:
                selected_area_type = area_type if button.isChecked() else None
                break
        self._selected_area_type = selected_area_type
        for area_type, candidate in self.area_type_buttons.items():
            if candidate is not button:
                candidate.blockSignals(True)
                candidate.setChecked(False)
                candidate.blockSignals(False)
            elif selected_area_type is None:
                candidate.setChecked(False)
        self._selected_areas = []
        self._area_signature = ()
        self._area_types_signature = ()
        self._area_search_text = ""
        self.area_search.blockSignals(True)
        self.area_search.clear()
        self.area_search.blockSignals(False)
        self._update_area_details_visibility()
        self._reset_dataset_page()
        self._schedule_recompute_lists(0, refresh=_REFRESH_FILTER_IMPACT)

    def _on_areas_changed(self) -> None:
        if self._recompute_running or self._suppress_area_change:
            return
        self._selected_areas = self.area_model.checked_payloads()
        self._update_area_all_checkbox()
        self._reset_dataset_page()
        self._schedule_recompute_lists(0, refresh=_REFRESH_AREA_CHECK)

    def _remember_area_all_state(self) -> None:
        self._area_all_previous_state = self.area_all_checkbox.checkState()

    def _on_area_all_clicked(self) -> None:
        # Standard tri-state master behavior:
        # unchecked -> checked, checked -> unchecked, partial -> checked.
        target_checked = _check_state_value(self._area_all_previous_state) != int(Qt.Checked.value)
        self.area_model.set_all_checked(target_checked)
        self._selected_areas = self.area_model.checked_payloads()
        self._update_area_all_checkbox()
        self._reset_dataset_page()
        self._schedule_recompute_lists(0, refresh=_REFRESH_AREA_CHECK)

    def _update_area_all_checkbox(self) -> None:
        self.area_all_checkbox.blockSignals(True)
        try:
            state = self.area_model.aggregate_check_state()
            self.area_all_checkbox.setCheckState(state)
            self.area_all_checkbox.setEnabled(self.area_model.rowCount() > 0)
            self.area_all_checkbox.setToolTip(
                "Unselect all" if _check_state_value(state) == int(Qt.Checked.value) else "Select all"
            )
            self.area_all_checkbox.update()
        finally:
            self.area_all_checkbox.blockSignals(False)

    def _on_area_sort_requested(self, column: str) -> None:
        if not self._area_type_shows_area_list(self._selected_area_type):
            return
        if self._area_sort_column == column:
            self._area_sort_ascending = not self._area_sort_ascending
        else:
            self._area_sort_column = column
            self._area_sort_ascending = True
        self._area_signature = ()
        self._populate_areas_for_type(self._selected_area_type, preserve_selection=True)

    def _on_area_cell_clicked(self, index) -> None:
        if not index.isValid() or index.column() == 0:
            return
        check_item = self.area_model.item(index.row(), 0)
        if not check_item or not check_item.isCheckable():
            return
        check_item.setCheckState(
            Qt.Unchecked if _check_state_value(check_item.checkState()) == int(Qt.Checked.value) else Qt.Checked
        )

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
        if self._recompute_running or not self._area_type_shows_area_list(self._selected_area_type):
            return
        text = self.area_search.text().strip()
        if text == self._area_search_text:
            return
        self._area_search_text = text
        self._populate_areas_for_type(self._selected_area_type, preserve_selection=True)

    def _apply_dataset_search(self) -> None:
        if self._recompute_running:
            return
        text = self.dataset_search.text().strip()
        if text == self._dataset_search_text:
            return
        self._dataset_search_text = text
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
        self._area_signature = ()
        self._update_selected_panel()
        self._schedule_recompute_lists(0, refresh=_REFRESH_DATASET)

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
        self._reset_dataset_page()
        self._update_selected_panel()
        self._schedule_recompute_lists(0, refresh=_REFRESH_AREA_CHECK)

    def _clear_selected_projection(self) -> None:
        if not self._selected_projection:
            return
        self._selected_projection = None
        self._reset_dataset_page()
        self._update_selected_panel()
        self._schedule_recompute_lists(0, refresh=_REFRESH_FILTER_IMPACT)

    def _clear_selected_format(self) -> None:
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
        self._selected_categories = set()
        self._selected_categories_expanded = False
        self._selected_areas_expanded = False
        self._selected_projection = None
        self._selected_format = None
        self._selected_areas = []
        self._area_signature = ()
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
        if toggle and self._selected_dataset and self._selected_dataset.metadata_uuid == ds.metadata_uuid:
            self._selected_dataset = None
        else:
            self._selected_dataset = ds
            self._start_single_dataset_enrichment(ds)
        self._area_signature = ()
        self._update_selected_panel()
        self._schedule_recompute_lists(0, refresh=_REFRESH_DATASET)

    def _on_projection_clicked(self, index) -> None:
        if not index.isValid():
            return
        self._select_projection_index(index, toggle=True)

    def _select_projection_index(self, index, *, toggle: bool = False) -> None:
        if self._recompute_running:
            return
        p = self.projection_model.selected_payload(index)
        if not isinstance(p, ProjectionOption):
            return
        if not toggle and self._selected_projection and self._selected_projection.code == p.code:
            return
        if toggle and self._selected_projection and self._selected_projection.code == p.code:
            self._selected_projection = None
        else:
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
        fmt = self.format_model.selected_payload(index)
        if not isinstance(fmt, FormatOption):
            return
        target = _format_filter_key(fmt)
        if not toggle and self._selected_format and _format_filter_key(self._selected_format) == target:
            return
        if toggle and self._selected_format and _format_filter_key(self._selected_format) == target:
            self._selected_format = None
        else:
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
        self._show_only_downloadable = False
        self._dataset_search_text = ""
        self._area_search_text = ""
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
        self.area_search.blockSignals(True)
        self.area_search.clear()
        self.area_search.blockSignals(False)
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
        if not (ds and self._selected_format):
            return
        if ds.projections and not self._selected_projection:
            return
        requires_area = self._dataset_requires_area(ds)
        if requires_area and not self._selected_areas:
            return
        folder = QFileDialog.getExistingDirectory(self, "Choose download folder")
        if not folder:
            return

        task_labels = self._download_task_labels()
        self._close_download_progress_dialog()
        progress_dialog = DownloadProgressDialog(
            self,
            task_labels,
            light_mode=self._light_mode,
        )
        self._download_progress_dialog = progress_dialog
        progress_dialog.show()

        proj = self._selected_projection
        fmt = self._selected_format
        areas: list[AreaOption | None] = list(self._selected_areas) if requires_area else [None]
        area_type = self._selected_area_type if requires_area else None

        projection_code = proj.code if proj else None
        projection_part = proj.code if proj else "any"
        holder: dict[str, FuncWorker] = {}

        def do_download() -> list[tuple[str, str]]:
            results: list[tuple[str, str]] = []
            for index, a in enumerate(areas):
                area_label = a.label if a else "Dataset"
                area_code = a.code if a else None
                if "worker" in holder:
                    holder["worker"].signals.progress.emit(0, 0, f"Preparing {area_label}…")
                # Preflight + interactive fallback for "this area can't be produced with this format".
                while True:
                    ok, reason = self._nedlasting.validate_area_format_projection(
                        metadata_uuid=ds.metadata_uuid,
                        area_type=area_type,
                        area_code=area_code,
                        format_name=fmt.name,
                        projection_code=projection_code,
                        base_url=ds.download_api_base,
                    )
                    if not ok:
                        raise RuntimeError(f"{area_label}: {reason or 'Not available.'}")
                    try:
                        ref = self._nedlasting.place_order(
                            metadata_uuid=ds.metadata_uuid,
                            area_type=area_type,
                            area_code=area_code,
                            format_name=fmt.name,
                            projection_code=projection_code,
                            base_url=ds.download_api_base,
                        )
                        url = self._nedlasting.poll_download_url(ref, base_url=ds.download_api_base)
                        size = self._http.content_length(url)
                        if "worker" in holder:
                            holder["worker"].signals.progress.emit(0, size or 0, f"Downloading {area_label} ({_format_bytes(size)})…")
                        safe_title = "".join(ch for ch in ds.title if ch.isalnum() or ch in (" ", "_", "-")).strip().replace(" ", "_")
                        area_part = f"{area_type}_{area_code}" if area_type and area_code else "full"
                        target = Path(folder) / f"{safe_title}_{area_part}_{fmt.name}_{projection_part}.zip"

                        def on_progress(downloaded: int, total: int | None, label: str = area_label) -> None:
                            if "worker" not in holder:
                                return
                            if total:
                                message = f"Downloading {label}: {_format_bytes(downloaded)} / {_format_bytes(total)}"
                            else:
                                message = f"Downloading {label}: {_format_bytes(downloaded)}"
                            holder["worker"].signals.progress.emit(downloaded, total or 0, message)

                        self._http.download(url, str(target), progress=on_progress)
                        results.append((area_label, str(target)))
                        if "worker" in holder:
                            holder["worker"].signals.item_completed.emit(index)
                        break
                    except Exception as e:
                        # Re-raise so UI thread can decide skip/change-format.
                        raise RuntimeError(f"{area_label}: {e}") from e
            return results

        self._set_status("Downloading…")
        worker = FuncWorker(do_download)
        holder["worker"] = worker
        worker.signals.result.connect(self._on_download_done)
        worker.signals.error.connect(self._on_download_error)
        worker.signals.progress.connect(self._on_download_progress)
        worker.signals.item_completed.connect(progress_dialog.mark_item_complete)
        self._start_worker(worker)

    def _on_download_done(self, results: object) -> None:
        if self._download_progress_dialog is not None:
            self._download_progress_dialog.mark_all_complete()
        self._close_download_progress_dialog()
        self._set_status("Download complete.")
        if isinstance(results, list):
            msg = "\n".join([f"{area_label}: {path}" for area_label, path in results])
        else:
            msg = "Done."
        box = themed_message_box(
            self,
            title="Download complete",
            text=msg,
            icon="success",
        )
        box.exec()

    def _on_download_progress(self, done: int, total: int, message: str) -> None:
        logger.debug("Download progress %s/%s: %s", done, total, message)
        self._set_status(message)

    def _on_download_error(self, tb: str) -> None:
        logger.error("Download failed: %s", tb)
        self._close_download_progress_dialog()
        self._set_status("Download failed.")
        # If multiple areas are selected, we want per-area warnings with skip/change-format.
        # Since the worker stops on first failure, we re-run sequentially on the UI thread with prompts.
        self._download_with_per_area_prompts()

    def _download_with_per_area_prompts(self) -> None:
        ds = self._selected_dataset
        if not (ds and self._selected_format and self._selected_areas):
            return
        if ds.projections and not self._selected_projection:
            return
        folder = QFileDialog.getExistingDirectory(self, "Choose download folder")
        if not folder:
            return

        proj = self._selected_projection
        projection_code = proj.code if proj else None
        projection_part = proj.code if proj else "any"
        current_format = self._selected_format
        area_type = self._selected_area_type

        for a in list(self._selected_areas):
            fmt = current_format
            while True:
                try:
                    ref = self._nedlasting.place_order(
                        metadata_uuid=ds.metadata_uuid,
                        area_type=area_type,
                        area_code=a.code,
                        format_name=fmt.name,
                        projection_code=projection_code,
                        base_url=ds.download_api_base,
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
                    change_btn = msg.addButton("Choose another format…", QMessageBox.AcceptRole)
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
                    holder["worker"].signals.progress.emit(done, total, message)

            return self._discovery.enrich_parallel(
                ordered,
                cached_by_uuid=cached_by_uuid,
                on_progress=on_progress,
                cancel=self._enrichment_cancel,
            )

        worker = FuncWorker(enrich_all)
        holder["worker"] = worker
        self._bulk_enrichment = True
        worker.signals.result.connect(self._on_enriched)
        worker.signals.error.connect(self._on_enrichment_error)
        worker.signals.progress.connect(self._on_enrichment_progress)
        worker.signals.finished.connect(self._on_enrichment_finished)
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
        worker.signals.result.connect(self._on_dataset_enriched_partial)
        worker.signals.error.connect(self._show_error)

        def clear_flag() -> None:
            self._enriching_uuids.discard(ds.metadata_uuid)

        worker.signals.finished.connect(clear_flag)
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
        worker.signals.result.connect(lambda _: self._on_cache_reset_done())
        worker.signals.error.connect(self._on_cache_reset_failed)
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
        logger.info("Closing window; stopping background workers")
        self._stop_background_work()
        super().closeEvent(event)

    def _show_error(self, tb: str) -> None:
        logger.error("Unhandled background error: %s", tb)
        self._set_status("Error. See log file for details.")
        box = themed_message_box(self, title="Error", text=tb, icon="warning")
        box.exec()

