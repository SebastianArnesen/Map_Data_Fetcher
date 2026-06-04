"""
Central UI theme definitions for Geonorge Datasets.

Edit colors here; `build_stylesheet()` turns them into Qt Style Sheets (QSS).
Custom-painted widgets (checkboxes, dataset rows, icons) use the same palettes
via helper functions at the bottom of this file.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication, QWidget

UI_SCALE_LARGE = 1.2
_TEXT_SCALE_FACTOR = 1.0


def default_text_scale_name() -> str:
    """First-run default: larger UI on macOS and Linux."""
    if sys.platform in ("darwin", "linux"):
        return "large"
    return "normal"


def scale_name_to_factor(name: str | None) -> float:
    return UI_SCALE_LARGE if name == "large" else 1.0


def set_text_scale_factor(scale: float) -> None:
    global _TEXT_SCALE_FACTOR
    _TEXT_SCALE_FACTOR = max(1.0, min(1.5, float(scale)))


def text_scale_factor() -> float:
    return _TEXT_SCALE_FACTOR


def font_points(base: int, *, ui_scale: float | None = None) -> int:
    scale = text_scale_factor() if ui_scale is None else ui_scale
    return max(8, round(base * scale))


def scale_pixels(value: int, *, ui_scale: float | None = None) -> int:
    scale = text_scale_factor() if ui_scale is None else ui_scale
    return max(value, round(value * scale))


# ---------------------------------------------------------------------------
# Colors shared by both themes (semantic / brand)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SharedColors:
    border: str = "#242a38"
    accent: str = "#6f96ff"
    accent_hover_border: str = "#6f96ff"
    white: str = "#ffffff"
    checkbox_checked: str = "#6f96ff"
    checkbox_tick: str = "#ffffff"
    download: str = "#2ea043"
    download_hover: str = "#34b94e"
    download_pressed: str = "#258d39"
    download_disabled_bg: str = "#1d3a26"
    download_disabled_text: str = "#7a9486"
    clear: str = "#9b2d35"
    clear_hover: str = "#ff4d5e"
    clear_pressed: str = "#ff6b78"
    clear_disabled: str = "#684149"
    knob: str = "#ffffff"


SHARED = SharedColors()


# ---------------------------------------------------------------------------
# Per-theme palette (surfaces, text, list states, chrome)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ThemeColors:
    """All hex colors for one visual theme."""

    # Window & panels
    window_bg: str
    window_fg: str
    card_bg: str
    card_border: str
    input_bg: str
    input_bg_focus: str
    input_border: str
    input_border_focus: str
    input_placeholder: str
    busy_overlay: str  # "#RRGGBB" or "#AARRGGBB"
    busy_widget_bg: str
    busy_widget_fg: str

    # Lists (QListView categories / projection / format)
    list_fg: str
    list_selected_bg: str
    list_selected_fg: str
    list_hover_bg: str

    # Dataset tree (delegate paints rows; QSS keeps selection transparent)
    dataset_row_fg: str
    dataset_row_selected_bg: str
    dataset_row_hover_bg: str
    dataset_tag_fg: str
    dataset_tag_hover_fg: str
    copy_icon: str
    copy_icon_bright: str
    copy_hover_bg: str

    # Area tree
    area_hover_bg: str

    # Menus & radios
    menu_bg: str
    menu_fg: str
    menu_selected_bg: str
    menu_selected_fg: str
    radio_fg: str
    radio_hover_bg: str
    radio_indicator_bg: str
    radio_indicator_border: str

    # Buttons (toolbar, pager, headers, search)
    button_bg: str
    button_fg: str
    button_border: str
    button_hover_bg: str
    button_hover_fg: str
    button_hover_border: str
    button_pressed_bg: str
    button_pressed_border: str
    button_disabled_fg: str
    button_disabled_border: str
    button_disabled_bg: str
    header_button_fg: str
    header_button_hover_fg: str

    # Scrollbars (CSS rgba string for handle)
    scrollbar_handle: str
    scrollbar_handle_hover: str

    # Status bar & labels
    statusbar_bg: str
    statusbar_fg: str
    statusbar_border: str
    status_label_fg: str
    copy_status_fg: str
    secondary_label_fg: str
    selected_value_fg: str
    selected_value_auto_fg: str
    filter_checkbox_fg: str
    search_clear_fg: str

    # Checkbox / indicator (QSS + optional custom paint)
    checkbox_unchecked_bg: str
    checkbox_unchecked_border: str

    # Theme toggle track (icons always use SHARED.border)
    toggle_track_bg: str

    # Misc
    selection_bg: str
    selection_fg: str
    disabled_list_item: str


DARK = ThemeColors(
    window_bg="#0f1115",
    window_fg="#e6e6e6",
    card_bg="#151821",
    card_border=SHARED.border,
    input_bg="#10131b",
    input_bg_focus="#121724",
    input_border=SHARED.border,
    input_border_focus="#38415a",
    input_placeholder="#6f7689",
    busy_overlay="#48ffffff",
    busy_widget_bg="#10131b",
    busy_widget_fg="#6f7689",
    list_fg="#e6e6e6",
    list_selected_bg="#2a3561",
    list_selected_fg="#ffffff",
    list_hover_bg="#20263a",
    dataset_row_fg="#ffffff",
    dataset_row_selected_bg="#2a3561",
    dataset_row_hover_bg="#20263a",
    dataset_tag_fg="#9ba3b4",
    dataset_tag_hover_fg="#ffffff",
    copy_icon="#6f7689",
    copy_icon_bright="#ffffff",
    copy_hover_bg="#20263a",
    area_hover_bg="#20263a",
    menu_bg="#151821",
    menu_fg="#e6e6e6",
    menu_selected_bg="#20263a",
    menu_selected_fg="#ffffff",
    radio_fg="#e6e6e6",
    radio_hover_bg="#20263a",
    radio_indicator_bg="#e7ebf4",
    radio_indicator_border="transparent",
    button_bg="#151821",
    button_fg="#cfd3dc",
    button_border="#2c3346",
    button_hover_bg="#20263a",
    button_hover_fg="#ffffff",
    button_hover_border="#38415a",
    button_pressed_bg="#2a3561",
    button_pressed_border="#3b4a78",
    button_disabled_fg="#6f7689",
    button_disabled_border="#232838",
    button_disabled_bg="#131620",
    header_button_fg="#9ba3b4",
    header_button_hover_fg="#d7dbe5",
    scrollbar_handle="rgba(125, 133, 151, 80)",
    scrollbar_handle_hover="rgba(155, 163, 180, 150)",
    statusbar_bg="#0f1115",
    statusbar_fg="#cfd3dc",
    statusbar_border=SHARED.border,
    status_label_fg="#cfd3dc",
    copy_status_fg="#9fb8ff",
    secondary_label_fg="#9ba3b4",
    selected_value_fg="#cfd3dc",
    selected_value_auto_fg="#8b93a8",
    filter_checkbox_fg="#e6e6e6",
    search_clear_fg="#ffffff",
    checkbox_unchecked_bg="#e7ebf4",
    checkbox_unchecked_border="transparent",
    toggle_track_bg="#ffffff",
    selection_bg="#2a3561",
    selection_fg="#ffffff",
    disabled_list_item="#7d8597",
)

LIGHT = ThemeColors(
    window_bg="#ffffff",
    window_fg="#0f1115",
    card_bg="#f7f9ff",
    card_border=SHARED.border,
    input_bg="#ffffff",
    input_bg_focus="#ffffff",
    input_border=SHARED.border,
    input_border_focus=SHARED.border,
    input_placeholder=SHARED.border,
    busy_overlay="#52000000",
    busy_widget_bg="#f1f3f9",
    busy_widget_fg=SHARED.border,
    list_fg="#0f1115",
    list_selected_bg="#c7d8ff",
    list_selected_fg="#0f1115",
    list_hover_bg="#dbe6ff",
    dataset_row_fg="#0f1115",
    dataset_row_selected_bg="#c7d8ff",
    dataset_row_hover_bg="#dbe6ff",
    dataset_tag_fg=SHARED.border,
    dataset_tag_hover_fg=SHARED.border,
    copy_icon=SHARED.border,
    copy_icon_bright=SHARED.border,
    copy_hover_bg="#dbe6ff",
    area_hover_bg="#dbe6ff",
    menu_bg="#ffffff",
    menu_fg="#0f1115",
    menu_selected_bg="#dbe6ff",
    menu_selected_fg="#0f1115",
    radio_fg="#0f1115",
    radio_hover_bg="#dbe6ff",
    radio_indicator_bg="#ffffff",
    radio_indicator_border=SHARED.border,
    button_bg="#f7f9ff",
    button_fg=SHARED.border,
    button_border=SHARED.border,
    button_hover_bg="#dbe6ff",
    button_hover_fg="#0f1115",
    button_hover_border=SHARED.border,
    button_pressed_bg="#c7d8ff",
    button_pressed_border=SHARED.border,
    button_disabled_fg=SHARED.border,
    button_disabled_border=SHARED.border,
    button_disabled_bg="#fbfcff",
    header_button_fg=SHARED.border,
    header_button_hover_fg="#0f1115",
    scrollbar_handle="rgba(36, 42, 56, 80)",
    scrollbar_handle_hover="rgba(36, 42, 56, 150)",
    statusbar_bg="#ffffff",
    statusbar_fg=SHARED.border,
    statusbar_border=SHARED.border,
    status_label_fg=SHARED.border,
    copy_status_fg=SHARED.border,
    secondary_label_fg=SHARED.border,
    selected_value_fg="#0f1115",
    selected_value_auto_fg="#7d8597",
    filter_checkbox_fg="#0f1115",
    search_clear_fg=SHARED.border,
    checkbox_unchecked_bg="#ffffff",
    checkbox_unchecked_border=SHARED.border,
    toggle_track_bg=DARK.card_bg,
    # Stronger contrast for text selection in light mode.
    selection_bg=SHARED.accent,
    selection_fg=SHARED.white,
    disabled_list_item="#7d8597",
)


def palette_for(light_mode: bool) -> ThemeColors:
    return LIGHT if light_mode else DARK


def resolve_light_mode(widget=None) -> bool:
    """Prefer MainWindow._light_mode; fall back to palette brightness."""
    current = widget
    while current is not None:
        if hasattr(current, "_light_mode"):
            return bool(current._light_mode)
        current = current.parentWidget()
    if widget is not None:
        return widget.palette().color(QPalette.ColorRole.Window).lightness() > 200
    return False


def qcolor(hex_value: str) -> QColor:
    return QColor(hex_value)


def set_filter_busy_flag(widget: QWidget, busy: bool) -> None:
    widget.setProperty("filterBusy", busy)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    viewport = getattr(widget, "viewport", None)
    if callable(viewport):
        set_filter_busy_flag(widget.viewport(), busy)


# ---------------------------------------------------------------------------
# Qt Style Sheet builder
# ---------------------------------------------------------------------------


def _button_block(
    selector: str,
    c: ThemeColors,
    *,
    radius: str = "8px",
    padding: str = "6px 14px",
    font_weight: str = "600",
) -> str:
    return f"""
        {selector} {{
            background: {c.button_bg};
            color: {c.button_fg};
            border: 1px solid {c.button_border};
            border-radius: {radius};
            padding: {padding};
            font-weight: {font_weight};
        }}
        {selector}:hover {{
            background: {c.button_hover_bg};
            color: {c.button_hover_fg};
            border-color: {c.button_hover_border};
        }}
        {selector}:pressed {{
            background: {c.button_pressed_bg};
            border-color: {c.button_pressed_border};
        }}
        {selector}:disabled {{
            color: {c.button_disabled_fg};
            border-color: {c.button_disabled_border};
            background: {c.button_disabled_bg};
        }}
    """


def _clear_button_block(selector: str) -> str:
    s = SHARED
    return f"""
        {selector} {{
            background: transparent;
            color: {s.clear};
            border: none;
            border-radius: 0px;
            padding: 0px;
            font-weight: 700;
        }}
        {selector}:hover {{ background: transparent; color: {s.clear_hover}; border: none; }}
        {selector}:pressed {{ background: transparent; color: {s.clear_pressed}; border: none; }}
        {selector}:disabled {{ background: transparent; color: {s.clear_disabled}; border: none; }}
    """


def build_stylesheet(c: ThemeColors, *, ui_scale: float | None = None) -> str:
    """Build the full application QSS for one theme."""
    scale = text_scale_factor() if ui_scale is None else ui_scale

    def fs(pt: float) -> str:
        return f"{max(8, round(pt * scale))}pt"

    def sp(px: int) -> int:
        return max(px, round(px * scale))

    s = SHARED
    filter_checkbox_rule = ""
    if c is LIGHT:
        filter_checkbox_rule = f"QCheckBox#filterCheckBox {{ color: {c.filter_checkbox_fg}; background: transparent; }}\n"

    checkbox_border = (
        f"border: 1px solid {c.checkbox_unchecked_border};"
        if c.checkbox_unchecked_border != "transparent"
        else "border: none;"
    )
    radio_border = (
        f"border: 1px solid {c.radio_indicator_border};"
        if c.radio_indicator_border != "transparent"
        else "border: 1px solid transparent;"
    )

    # Light mode: dark-panel blue (#2a3561), readable on white; dark mode: accent link blue.
    selected_toggle = DARK.list_selected_bg if c is LIGHT else s.accent
    return f"""
        QMainWindow {{ background: {c.window_bg}; color: {c.window_fg}; }}
        QFrame#mainCard {{
            background: {c.card_bg};
            border: 1px solid {c.card_border};
            border-radius: 10px;
        }}
        QFrame#subCard, QFrame#projectionCard, QFrame#formatCard, QFrame#selectedDatasetCard {{
            background: {c.card_bg};
            border: 1px solid {c.card_border};
            border-radius: 10px;
        }}
        QLabel {{
            color: {c.window_fg};
            font-size: {fs(12)};
            font-weight: 700;
            border: none;
            background: transparent;
            selection-background-color: {c.selection_bg};
            selection-color: {c.selection_fg};
        }}
        {filter_checkbox_rule}
        QCheckBox {{ color: {c.window_fg}; background: transparent; }}
        QListView, QTreeView {{
            background: transparent;
            border: none;
            color: {c.list_fg};
            outline: none;
        }}
        QListView::item {{ padding: 8px 10px; border-radius: 8px; }}
        QTreeView#areaView::item {{ padding: 7px 2px 7px 4px; border-radius: 0px; }}
        QTreeView::item {{ padding: 7px 4px; border-radius: 0px; }}
        QListView::item:selected {{ background: {c.list_selected_bg}; color: {c.list_selected_fg}; }}
        QListView::item:selected:!active {{ background: {c.list_selected_bg}; color: {c.list_selected_fg}; }}
        QTreeView#areaView::item:selected {{ background: transparent; }}
        QTreeView#datasetView::item:selected {{
            background: transparent;
            color: {c.dataset_row_fg};
        }}
        QTreeView#datasetView::item:selected:!active {{
            background: transparent;
            color: {c.dataset_row_fg};
        }}
        QListView::item:hover, QTreeView#areaView::item:hover {{ background: {c.area_hover_bg}; }}
        QTreeView#datasetView::item:hover {{ background: transparent; }}
        QMenu {{
            background: {c.menu_bg};
            color: {c.menu_fg};
            border: 1px solid {c.card_border};
            border-radius: 0px;
            padding: 0px;
        }}
        QMenu::item {{ padding: 5px 10px; border-radius: 0px; }}
        QMenu::item:selected {{ background: {c.menu_selected_bg}; color: {c.menu_selected_fg}; }}
        QMenu::item:hover {{ background: {c.menu_selected_bg}; color: {c.menu_selected_fg}; }}
        QRadioButton {{
            color: {c.radio_fg};
            background: transparent;
            padding: 6px 8px;
            border-radius: 8px;
        }}
        QRadioButton:hover {{ background: {c.radio_hover_bg}; }}
        QRadioButton::indicator {{
            width: 10px;
            height: 10px;
            min-width: 10px;
            max-width: 10px;
            min-height: 10px;
            max-height: 10px;
            {radio_border}
            border-radius: 5px;
            background: {c.radio_indicator_bg};
        }}
        QRadioButton::indicator:hover {{
            background: {s.white};
            border: 1px solid {s.accent};
            border-radius: 5px;
        }}
        QRadioButton::indicator:checked {{
            background: qradialgradient(
                cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
                stop:0 {s.white}, stop:0.36 {s.white}, stop:0.37 {s.accent}, stop:1 {s.accent}
            );
            border: 1px solid {s.accent};
            border-radius: 5px;
        }}
        QRadioButton::indicator:checked:hover {{
            background: qradialgradient(
                cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
                stop:0 {s.white}, stop:0.36 {s.white}, stop:0.37 {s.accent}, stop:1 {s.accent}
            );
            border: 1px solid {s.accent};
            border-radius: 5px;
        }}
        QPushButton#areaHeaderButton {{
            background: transparent;
            color: {c.header_button_fg};
            border: none;
            border-radius: 7px;
            padding: 5px 8px;
            font-weight: 600;
            text-align: left;
        }}
        QPushButton#areaHeaderButton:hover {{
            background: {c.list_hover_bg};
            color: {c.header_button_hover_fg};
        }}
        QPushButton#areaHeaderButton:pressed {{ background: {c.list_selected_bg}; }}
        {_button_block("QPushButton#toolbarButton", c)}
        QLineEdit#datasetSearch, QLineEdit#areaSearch {{
            background: {c.input_bg};
            color: {c.window_fg};
            border: 1px solid {c.input_border};
            border-radius: 8px;
            padding: 0px 30px 0px 10px;
            height: {sp(32)}px;
            min-height: {sp(32)}px;
            max-height: {sp(32)}px;
            selection-background-color: {c.selection_bg};
            selection-color: {c.selection_fg};
        }}
        QWidget#datasetSearchCombo QLineEdit#datasetSearch,
        QWidget#areaSearchCombo QLineEdit#areaSearch {{
            border-top-right-radius: 0px;
            border-bottom-right-radius: 0px;
            border-right: 0px;
        }}
        QToolButton#datasetSearchClear, QToolButton#areaSearchClear {{
            color: {c.search_clear_fg};
            background: transparent;
            border: none;
            border-radius: 6px;
            font-size: {fs(14)};
            font-weight: 700;
            padding: 0px 4px;
        }}
        QToolButton#datasetSearchClear:hover, QToolButton#areaSearchClear:hover {{
            background: {c.button_hover_bg};
        }}
        QLineEdit#datasetSearch:focus, QLineEdit#areaSearch:focus {{
            border-color: {c.input_border_focus};
            background: {c.input_bg_focus};
        }}
        QLineEdit#datasetSearch::placeholder, QLineEdit#areaSearch::placeholder {{ color: {c.input_placeholder}; }}
        QWidget#datasetSearchCombo QPushButton#datasetSearchButton,
        QWidget#areaSearchCombo QPushButton#areaSearchButton {{
            background: {c.input_bg};
            color: {c.button_fg};
            border: 1px solid {c.input_border};
            border-left: none;
            border-top-right-radius: 8px;
            border-bottom-right-radius: 8px;
            border-top-left-radius: 0px;
            border-bottom-left-radius: 0px;
            padding: 0px;
            min-width: {sp(38)}px;
            max-width: {sp(38)}px;
            height: {sp(32)}px;
            min-height: {sp(32)}px;
            max-height: {sp(32)}px;
        }}
        QWidget#datasetSearchCombo QPushButton#datasetSearchButton:hover,
        QWidget#areaSearchCombo QPushButton#areaSearchButton:hover {{
            background: {c.button_hover_bg};
            color: {c.button_hover_fg};
            border-color: {c.button_hover_border};
        }}
        QWidget#datasetSearchCombo QPushButton#datasetSearchButton:pressed,
        QWidget#areaSearchCombo QPushButton#areaSearchButton:pressed {{
            background: {c.button_pressed_bg};
            border-color: {c.button_pressed_border};
        }}
        QWidget#datasetSearchCombo QLineEdit#datasetSearch:focus,
        QWidget#areaSearchCombo QLineEdit#areaSearch:focus {{
            border-color: {c.input_border_focus};
            background: {c.input_bg_focus};
        }}
        QWidget#datasetSearchCombo QPushButton#datasetSearchButton[searchFocused="true"],
        QWidget#areaSearchCombo QPushButton#areaSearchButton[searchFocused="true"] {{
            border-color: {c.input_border_focus};
            background: {c.input_bg_focus};
        }}
        QPushButton#pagerButton {{
            background: {c.button_bg};
            color: {c.button_fg};
            border: 1px solid {c.button_border};
            border-radius: 8px;
            padding: 0px;
            min-width: {sp(32)}px;
            max-width: {sp(32)}px;
            min-height: {sp(32)}px;
            max-height: {sp(32)}px;
        }}
        QPushButton#pagerButton:hover {{
            background: {c.button_hover_bg};
            color: {c.button_hover_fg};
            border-color: {c.button_hover_border};
        }}
        QPushButton#pagerButton:pressed {{
            background: {c.button_pressed_bg};
            border-color: {c.button_pressed_border};
        }}
        QPushButton#pagerButton:disabled {{
            color: {c.button_disabled_fg};
            border-color: {c.button_disabled_border};
            background: {c.button_disabled_bg};
        }}
        {_clear_button_block("QPushButton#selectedDatasetClearButton")}
        QPushButton#selectedPanelClearAllButton {{
            background: transparent;
            color: {s.clear};
            border: none;
            border-radius: 0px;
            padding: 0px;
            font-size: {fs(12)};
            font-weight: 700;
        }}
        QPushButton#selectedPanelClearAllButton:hover {{ color: {s.clear_hover}; }}
        QPushButton#selectedPanelClearAllButton:pressed {{ color: {s.clear_pressed}; }}
        QPushButton#selectedPanelClearAllButton:disabled {{ color: {s.clear_disabled}; }}
        QScrollArea#selectedScroll {{ background: {c.card_bg}; border: none; }}
        QWidget#selectedScrollViewport, QWidget#selectedRowsHost {{ background: {c.card_bg}; }}
        QWidget#selectedDatasetCopyCell {{ background: transparent; }}
        QListView[filterBusy="true"], QTreeView[filterBusy="true"], QLineEdit[filterBusy="true"],
        QFrame[filterBusy="true"], QWidget[filterBusy="true"] {{
            background-color: {c.busy_widget_bg};
            color: {c.busy_widget_fg};
        }}
        QListView[filterBusy="true"]::item, QTreeView[filterBusy="true"]::item {{
            color: {c.busy_widget_fg};
        }}
        QPushButton#downloadButton {{
            background: {s.download};
            color: {s.white};
            border: 1px solid {s.download};
            border-radius: 8px;
            padding: 10px 18px;
            font-size: {fs(11)};
            font-weight: 700;
        }}
        QPushButton#downloadButton:hover {{ background: {s.download_hover}; border-color: {s.download_hover}; }}
        QPushButton#downloadButton:pressed {{ background: {s.download_pressed}; border-color: {s.download_pressed}; }}
        QPushButton#downloadButton:disabled {{
            background: {s.download_disabled_bg};
            color: {s.download_disabled_text};
            border-color: {s.download_disabled_bg};
        }}
        QCheckBox::indicator {{
            width: 13px;
            height: 13px;
            {checkbox_border}
            border-radius: 3px;
            background: {c.checkbox_unchecked_bg};
        }}
        QCheckBox#filterCheckBox::indicator {{
            width: 13px;
            height: 13px;
            {checkbox_border}
            border-radius: 3px;
            background: {c.checkbox_unchecked_bg};
        }}
        QCheckBox::indicator:hover {{
            background: {s.white};
            border: 1px solid {s.accent};
        }}
        QCheckBox#filterCheckBox::indicator:hover {{
            background: {s.white};
            border: 1px solid {s.accent};
        }}
        QCheckBox::indicator:checked, QCheckBox::indicator:indeterminate {{
            background: {s.accent};
            border: 1px solid {s.accent};
        }}
        QTreeView::indicator {{
            width: 13px;
            height: 13px;
            {checkbox_border}
            border-radius: 3px;
            background: {c.checkbox_unchecked_bg};
        }}
        QTreeView::indicator:hover {{
            background: {s.white};
            border: 1px solid {s.accent};
        }}
        QTreeView::indicator:checked {{
            background: {s.accent};
            border: 1px solid {s.accent};
        }}
        QTreeView::indicator:indeterminate {{
            background: {s.accent};
            border: 1px solid {s.accent};
        }}
        QScrollBar:vertical, QScrollBar:horizontal {{ background: transparent; border: none; margin: 0px; }}
        QScrollBar:vertical {{ width: 9px; }}
        QScrollBar:horizontal {{ height: 9px; }}
        QScrollBar::handle {{
            background: {c.scrollbar_handle};
            border-radius: 4px;
            min-height: 28px;
            min-width: 28px;
        }}
        QScrollBar::handle:hover {{ background: {c.scrollbar_handle_hover}; }}
        QScrollBar::add-line, QScrollBar::sub-line {{
            width: 0px;
            height: 0px;
            border: none;
            background: transparent;
        }}
        QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
        QStatusBar {{
            background: {c.statusbar_bg};
            color: {c.statusbar_fg};
            border-top: 1px solid {c.statusbar_border};
        }}
        QLabel#statusLabel {{ font-size: {fs(9)}; font-weight: 500; color: {c.status_label_fg}; }}
        QLabel#copyStatusLabel {{ font-size: {fs(9)}; font-weight: 600; color: {c.copy_status_fg}; }}
        QLabel#secondaryHeaderLabel {{ color: {c.secondary_label_fg}; font-size: {fs(10)}; font-weight: 600; }}
        QLabel#selectedDatasetValue {{
            color: {c.selected_value_fg};
            font-size: {fs(10)};
            font-weight: 600;
            padding: 0px;
            margin: 0px;
        }}
        QLabel#selectedDatasetTitle {{
            color: {c.selected_value_fg};
            font-size: {fs(10)};
            font-weight: 600;
            padding: 0px;
            margin: 0px;
        }}
        QLabel#selectedPanelGroupHeader {{
            color: {c.selected_value_fg};
            font-size: {fs(10)};
            font-weight: 700;
            padding: 0px;
            margin: 0px;
        }}
        QLabel#selectedDatasetValueAuto {{
            color: {c.selected_value_auto_fg};
            font-size: {fs(10)};
            font-weight: 600;
            padding: 0px;
            margin: 0px;
        }}
        QRadioButton#areaTypeRadio {{
            padding: 4px 10px 4px 8px;
        }}
        QRadioButton#areaTypeRadio[autoSelected="true"]::indicator {{
            width: 12px;
            height: 12px;
            min-width: 12px;
            max-width: 12px;
            min-height: 12px;
            max-height: 12px;
            border: 1px solid {s.accent};
            border-radius: 6px;
            background: {s.white};
        }}
        QRadioButton#areaTypeRadio[autoSelected="true"]::indicator:hover {{
            background: {s.white};
            border: 1px solid {s.accent};
            border-radius: 6px;
        }}
        QRadioButton#areaTypeRadio[autoSelected="true"]::indicator:checked {{
            background: {s.accent};
            border: 1px solid {s.accent};
            border-radius: 6px;
        }}
        QRadioButton#areaTypeRadio[autoSelected="true"]::indicator:checked:hover {{
            background: {s.accent};
            border: 1px solid {s.accent};
            border-radius: 6px;
        }}
        QPushButton#selectedPanelToggle {{
            background: transparent;
            border: none;
            color: {selected_toggle};
            text-align: left;
            padding: 0px 0px 2px 0px;
            font-size: {fs(10)};
            font-weight: 600;
        }}
        QPushButton#selectedPanelToggle:hover {{
            color: {selected_toggle};
            text-decoration: underline;
        }}
        QPushButton#selectedPanelToggle:pressed {{
            color: {selected_toggle};
        }}
    """


def apply_base_style(app: QApplication | None = None, *, ui_scale: float | None = None) -> None:
    """Fusion style + default app font (call once at startup)."""
    target = app or QApplication.instance()
    if target is None:
        return
    target.setStyle("Fusion")
    font = QFont()
    font.setPointSize(font_points(10, ui_scale=ui_scale))
    target.setFont(font)


# ---------------------------------------------------------------------------
# Helpers for custom-painted widgets (import QColor via qcolor())
# ---------------------------------------------------------------------------


def checkbox_fill_border(
    *,
    light_mode: bool,
    checked: bool,
    partial: bool,
    hover: bool,
) -> tuple[QColor, QColor]:
    """Fill and border colors for custom-painted checkboxes."""
    c = palette_for(light_mode)
    s = SHARED
    if checked or partial:
        fill = qcolor(s.accent)
    elif hover:
        fill = qcolor(s.white)
    else:
        fill = qcolor(c.checkbox_unchecked_bg)
    if hover:
        border = qcolor(s.accent)
    elif light_mode:
        border = qcolor(c.checkbox_unchecked_border)
    else:
        border = fill
    return fill, border


def checkbox_tick_color() -> QColor:
    return qcolor(SHARED.checkbox_tick)


def list_selection_border_color(*, light_mode: bool) -> QColor:
    return qcolor(palette_for(light_mode).list_selected_bg)


def checkbox_auto_fill_border(*, light_mode: bool, hover: bool) -> tuple[QColor, QColor]:
    """Solid blue box (no tick), for auto-selected area checkboxes."""
    del light_mode
    del hover
    accent = qcolor(SHARED.accent)
    return accent, accent


def checkbox_auto_tick_color() -> QColor:
    return qcolor(SHARED.accent)


def copy_icon_color(*, light_mode: bool, bright: bool) -> QColor:
    c = palette_for(light_mode)
    if light_mode:
        return qcolor(c.copy_icon)
    return qcolor(c.copy_icon_bright if bright else c.copy_icon)


def copy_hover_background(*, light_mode: bool) -> QColor:
    return qcolor(palette_for(light_mode).copy_hover_bg)


def dataset_row_background(*, light_mode: bool, selected: bool) -> QColor:
    c = palette_for(light_mode)
    hex_value = c.dataset_row_selected_bg if selected else c.dataset_row_hover_bg
    return qcolor(hex_value)


def dataset_text_color(*, light_mode: bool, column: int, tags_hover: bool) -> QColor:
    c = palette_for(light_mode)
    if column == 2:
        return qcolor(c.dataset_tag_hover_fg if tags_hover else c.dataset_tag_fg)
    return qcolor(c.dataset_row_fg)


def busy_overlay_fill(*, light_mode: bool) -> QColor:
    return qcolor(palette_for(light_mode).busy_overlay)


def theme_toggle_colors(*, light_mode: bool) -> tuple[QColor, QColor, QColor]:
    """Border, track background, icon (all use shared border grey for icons)."""
    c = palette_for(light_mode)
    return qcolor(SHARED.border), qcolor(c.toggle_track_bg), qcolor(SHARED.border)


def theme_toggle_knob_border() -> tuple[QColor, QColor]:
    return qcolor(SHARED.knob), qcolor(SHARED.border)


def disabled_list_item_color() -> QColor:
    return qcolor(DARK.disabled_list_item)
