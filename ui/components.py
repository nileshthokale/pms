"""Reusable UI components and style helpers for the Phase 6E light theme.

Every colour comes from the single centralized palette in ``ui.theme`` —
screens must not hard-code colours.  The helpers are intentionally thin:
they return stylesheet strings / configure widgets so screens can adopt
one consistent, traditional Windows desktop appearance without
duplicating style code.

Nothing in this module touches business logic, DAOs, signals, or data.

Usage in a screen::

    from ui import components as ui

    title = ui.PageHeader("Sales / Counter Sale")
    entry = ui.style_edit(QLineEdit())
    ui.style_data_table(self._table, stretch_columns=(1,))
"""

from __future__ import annotations

import re

from PySide6.QtCore import (
    QEvent,
    QModelIndex,
    QPoint,
    QRect,
    QStringListModel,
    QTimer,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QFont,
    QStandardItem,
    QStandardItemModel,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QCompleter,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from ui.theme import (
    FONT_FAMILY,
    FONT_NAME,
    TYPE_BUTTON,
    TYPE_FORM_LABEL,
    TYPE_HINT,
    TYPE_INPUT,
    TYPE_PAGE_TITLE,
    TYPE_SECTION_HEADER,
    TYPE_TABLE_DATA,
    TYPE_TABLE_HEADER,
    palette,
    indicator_style,
    remap_baked_colors,
    tooltip_rule,
)

# Readable desktop control metrics (px) shared across screens.
# Rows are sized so the shared TYPE_TABLE_DATA text (15 px ≈ 11 pt) plus the
# ``QTableWidget::item`` padding of 3 px never clips, while staying compact
# enough for 1366x768 pharmacy desktops.  Heights grew with the 11-12 pt
# baseline so larger fonts never clip or overlap.
CONTROL_HEIGHT = 34
ROW_HEIGHT = 32
HEADER_HEIGHT = 34

# The hint size screens declared before the shared type scale existed.  The
# theme-refresh inference still recognises it, so a screen that has not been
# moved onto the scale keeps its dim captions dim instead of silently
# becoming full-strength text.
_LEGACY_HINT_PX = 11


def readable_font(size: int, *, bold: bool = False) -> QFont:
    """Build the shared QFont for a given pixel size.

    Qt honours a stylesheet ``font-size`` over ``setFont()``, so widget and
    stylesheet must agree.  Screens that need the *actual* rendered font
    (font metrics, column sizing, ``QFontMetrics``) build it from here so it
    can never drift from the stylesheet declaration.
    """
    font = QFont(FONT_NAME)
    font.setPixelSize(size)
    font.setBold(bold)
    return font


# ── Label styles ──────────────────────────────────────────────────────

def label_style(*, dim: bool = False, bold: bool = True,
                size: int = TYPE_FORM_LABEL,
                danger: bool = False, success: bool = False) -> str:
    """Stylesheet for a caption / label at the shared readable size."""
    p = palette()
    if danger:
        color = p["danger"]
    elif success:
        color = p["success"]
    elif dim:
        color = p["text_dim"]
    else:
        color = p["text"]
    # The application stylesheet makes every ``QLabel`` bold, so a caption
    # that is deliberately *not* bold (a dim hint) has to say so explicitly —
    # otherwise "unset" would silently inherit the bold weight.
    weight = "font-weight: bold;" if bold else "font-weight: normal;"
    return (
        f"color: {color}; font-size: {size}px; {weight}"
        f"font-family: {FONT_FAMILY}; background: transparent;"
    )


def title_style(size: int = TYPE_PAGE_TITLE) -> str:
    """Page-title style (large, bold, black)."""
    p = palette()
    return (
        f"color: {p['text']}; font-size: {size}px; font-weight: bold;"
        f"font-family: {FONT_FAMILY}; background: transparent;"
    )


def section_title_style() -> str:
    """Section heading ("Bill Items", report sections): bold, black, 13 px."""
    return label_style(bold=True, size=TYPE_SECTION_HEADER)


# ── Input styles ──────────────────────────────────────────────────────

def _input_rules(selector: str, *, size: int = TYPE_INPUT) -> str:
    p = palette()
    return (
        f"{selector} {{"
        f"  background-color: {p['bg']}; color: {p['text']};"
        f"  border: 1px solid {p['border']}; border-radius: 2px;"
        f"  padding: 4px 7px; font-size: {size}px;"
        f"  font-weight: bold; font-family: {FONT_FAMILY};"
        "}"
    )


def edit_style() -> str:
    p = palette()
    return (
        _input_rules("QLineEdit")
        + f"QLineEdit:focus {{ border: 1px solid {p['focus']}; }}"
        + f"QLineEdit:disabled {{ background-color: {p['disabled_bg']};"
        + f"  color: {p['disabled_text']}; }}"
    )


def combo_style() -> str:
    p = palette()
    return (
        _input_rules("QComboBox")
        + f"QComboBox:hover {{ border: 1px solid {p['focus']}; }}"
        + "QComboBox::drop-down { border: none; width: 18px; }"
        + "QComboBox::down-arrow { image: none; border: none; }"
        + "QComboBox QAbstractItemView {"
        + f"  background-color: {p['bg']}; color: {p['text']};"
        + f"  border: 1px solid {p['border']};"
        + f"  selection-background-color: {p['selected']};"
        + f"  selection-color: {p['selected_text']};"
        + f"  font-size: {TYPE_INPUT}px; font-family: {FONT_FAMILY};"
        + "}"
    )


def date_style() -> str:
    # Shared date-field look: base input rules plus the centralized
    # drop-down button + calendar chevron from ui.theme.  The chevron is a
    # generated PNG tinted with the live palette (never `image: none`, which
    # is what hid the icon on every screen).
    from ui.theme import date_subcontrols
    p = palette()
    return (
        _input_rules("QDateEdit, QTimeEdit, QDateTimeEdit")
        + "QDateEdit:focus, QTimeEdit:focus, QDateTimeEdit:focus"
        + f" {{ border: 1px solid {p['focus']}; }}"
        + f"QDateEdit:disabled, QTimeEdit:disabled, QDateTimeEdit:disabled"
        + f" {{ background-color: {p['disabled_bg']};"
        + f"  color: {p['disabled_text']}; }}"
        + date_subcontrols(p, width=22)
    )


def spin_style() -> str:
    p = palette()
    return (
        _input_rules("QSpinBox, QDoubleSpinBox")
        + "QSpinBox:focus, QDoubleSpinBox:focus"
        + f" {{ border: 1px solid {p['focus']}; }}"
    )


def checkbox_style() -> str:
    p = palette()
    return (
        "QCheckBox, QRadioButton {"
        f"  color: {p['text']}; font-size: {TYPE_FORM_LABEL}px;"
        f"  font-family: {FONT_FAMILY}; background: transparent;"
        "  border: none; outline: none;"
        "  spacing: 5px;"
        "}"
        "QCheckBox:focus, QRadioButton:focus {"
        "  background: transparent; border: none; outline: none;"
        "}"
        "QCheckBox:hover, QRadioButton:hover {"
        "  background: transparent; border: none;"
        "}"
        # Shared with the application stylesheet: the check mark / radio dot
        # follows the mode, so a checked control never renders as a plain
        # square that is indistinguishable from an unchecked one.
        + indicator_style()
    )


def group_box_style() -> str:
    p = palette()
    return (
        "QGroupBox {"
        f"  color: {p['text']}; font-weight: bold;"
        f"  font-size: {TYPE_SECTION_HEADER}px;"
        f"  border: 1px solid {p['border']}; border-radius: 2px;"
        "  margin-top: 12px; padding-top: 14px;"
        f"  background-color: {p['bg']};"
        "}"
        "QGroupBox::title {"
        "  subcontrol-origin: margin; left: 8px; padding: 0 4px;"
        f"  background-color: {p['surface']};"
        "}"
    )


# ── Button styles ─────────────────────────────────────────────────────

def _button_style(bg: str, fg: str, hover: str, pressed: str) -> str:
    p = palette()
    return (
        "QPushButton {"
        f"  background-color: {bg}; color: {fg};"
        f"  border: 1px solid {p['border']}; border-radius: 2px;"
        f"  padding: 5px 14px; font-size: {TYPE_BUTTON}px;"
        f"  font-weight: bold; font-family: {FONT_FAMILY}; min-height: 22px;"
        "}"
        f"QPushButton:hover {{ background-color: {hover}; }}"
        f"QPushButton:pressed {{ background-color: {pressed}; }}"
        "QPushButton:disabled {"
        f"  background-color: {p['disabled_bg']};"
        f"  color: {p['disabled_text']};"
        "}"
    )


def btn_primary_style() -> str:
    p = palette()
    return _button_style(p["accent"], "#ffffff", p["accent_hover"],
                         p["accent_pressed"])


def btn_secondary_style() -> str:
    p = palette()
    return _button_style(p["surface"], p["text"], p["selected"],
                         p["accent_pressed"])


def btn_success_style() -> str:
    p = palette()
    return _button_style(p["success"], "#ffffff", p["success_hover"],
                         p["success_hover"])


def btn_danger_style() -> str:
    p = palette()
    return _button_style(p["danger"], "#ffffff", p["danger_hover"],
                         p["danger_hover"])


def btn_warning_style() -> str:
    p = palette()
    return _button_style(p["warning"], "#ffffff", p["warning_hover"],
                         p["warning_hover"])


# Common aliases so existing screen constant names can be routed here.
BTN_GREEN = btn_primary_style
BTN_PRIMARY = btn_primary_style
BTN_SAVE = btn_primary_style
BTN_SECONDARY = btn_secondary_style
BTN_GRAY = btn_secondary_style
BTN_DANGER = btn_danger_style
BTN_RED = btn_danger_style
BTN_ORANGE = btn_warning_style
BTN_WARNING = btn_warning_style


def style_button(button: QPushButton, variant: str = "secondary",
                 *, height: int | None = CONTROL_HEIGHT) -> QPushButton:
    styles = {
        "primary": btn_primary_style,
        "secondary": btn_secondary_style,
        "success": btn_success_style,
        "danger": btn_danger_style,
        "warning": btn_warning_style,
    }
    button.setStyleSheet(styles.get(variant, btn_secondary_style)())
    button.setCursor(Qt.PointingHandCursor)
    # Remember the variant + height so refresh_tree() can re-apply the same
    # centralized style after a Day/Night switch without losing the variant
    # (primary white-on-accent must stay white; secondary text must flip).
    try:
        button.setProperty("theme_source", "components")
        button.setProperty("theme_kind", f"button:{variant}")
        if height is not None:
            button.setProperty("theme_height", int(height))
    except Exception:
        pass
    if height:
        button.setMinimumHeight(height)
    return button


class ActionButton(QPushButton):
    """Traditional rectangular desktop action button."""

    def __init__(self, text: str, variant: str = "secondary",
                 parent: QWidget | None = None, *, height: int | None = CONTROL_HEIGHT):
        super().__init__(text, parent)
        style_button(self, variant, height=height)


# ── Table styles ──────────────────────────────────────────────────────

def table_style() -> str:
    p = palette()
    return (
        "QTableWidget, QTableView {"
        f"  background-color: {p['bg']}; color: {p['text']};"
        f"  alternate-background-color: {p['surface_alt']};"
        f"  border: 1px solid {p['border']};"
        f"  gridline-color: {p['grid']};"
        f"  font-size: {TYPE_TABLE_DATA}px; font-weight: bold; font-family: {FONT_FAMILY};"
        f"  selection-background-color: {p['selected']};"
        f"  selection-color: {p['selected_text']};"
        "}"
        "QTableWidget::item, QTableView::item { padding: 3px 6px; }"
        "QTableWidget::item:selected, QTableView::item:selected {"
        f"  background-color: {p['selected']};"
        f"  color: {p['selected_text']};"
        "}"
    )


def table_header_style(*, size: int = TYPE_TABLE_HEADER) -> str:
    p = palette()
    return (
        "QHeaderView::section {"
        f"  background-color: {p['table_header']}; color: {p['header_text']};"
        f"  border: none;"
        f"  border-right: 1px solid {p['border']};"
        f"  border-bottom: 1px solid {p['border']};"
        f"  padding: 3px 6px; font-weight: bold; font-size: {size}px;"
        f"  font-family: {FONT_FAMILY};"
        "}"
        "QHeaderView::section:vertical {"
        f"  background-color: {p['surface']};"
        "}"
    )


def _mark(widget, kind: str) -> None:
    """Tag a components-styled widget so refresh_tree() can update it."""
    try:
        widget.setProperty("theme_source", "components")
        widget.setProperty("theme_kind", kind)
    except Exception:
        pass


def style_data_table(table: QTableWidget, *, stretch_columns=(),
                     resize_to_contents=(), grid: bool = True,
                     alternating: bool = False,
                     row_height: int = ROW_HEIGHT) -> QTableWidget:
    """Apply the shared grid/selection/header look to a data table.

    Both the stylesheet *and* the widget/header QFont are set.  A Qt
    stylesheet ``font-size`` wins over ``setFont()``, so setting them from
    the same scale keeps the declared size, the rendered cell text and any
    ``QFontMetrics`` measurement in agreement.
    """
    table.setStyleSheet(table_style())
    _mark(table, "table")
    table.setFont(readable_font(TYPE_TABLE_DATA))
    table.setShowGrid(grid)
    table.setAlternatingRowColors(alternating)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSelectionMode(QAbstractItemView.SingleSelection)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(row_height)
    header = table.horizontalHeader()
    header.setStyleSheet(table_header_style())
    _mark(header, "table_header")
    header.setFont(readable_font(TYPE_TABLE_HEADER, bold=True))
    header.setFixedHeight(HEADER_HEIGHT)
    header.setStretchLastSection(True)
    for column in stretch_columns:
        header.setSectionResizeMode(column, QHeaderView.Stretch)
    for column in resize_to_contents:
        header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
    return table


# ── Containers / composite widgets ────────────────────────────────────

def panel_style() -> str:
    p = palette()
    return (
        "background-color: {bg}; border: 1px solid {border}; border-radius: 2px;"
    ).format(bg=p["bg"], border=p["border"])


def strip_style() -> str:
    """Light blue strip used for page headers and filter bars."""
    p = palette()
    return (
        "background-color: {surface};"
        "border-bottom: 1px solid {border};"
    ).format(surface=p["surface"], border=p["border"])


class PageHeader(QFrame):
    """Consistent page header strip: light blue background, dark title.

    Screens use this as the top strip so every page looks the same:
        "Sales / Counter Sale"
    """

    def __init__(self, title: str, subtitle: str = "",
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("PageHeader")
        _mark(self, "page_header")
        self.setFixedHeight(36)
        self.setStyleSheet(
            f"#PageHeader {{ {strip_style()} }}"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(8)

        self._title = QLabel(title)
        self._title.setStyleSheet(title_style())
        layout.addWidget(self._title)

        if subtitle:
            self._subtitle = QLabel(subtitle)
            self._subtitle.setStyleSheet(label_style(dim=True))
            layout.addWidget(self._subtitle)
        else:
            self._subtitle = None

        layout.addStretch()

    def add_action(self, widget: QWidget) -> None:
        """Add a right-aligned action widget (usually a button)."""
        self.layout().addWidget(widget)

    def add_actions(self, widgets) -> None:
        for widget in widgets:
            self.add_action(widget)

    def set_title(self, text: str) -> None:
        self._title.setText(text)


class SummaryPanel(QFrame):
    """Compact summary strip (opening balance / totals / status)."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("SummaryPanel")
        _mark(self, "summary_panel")
        p = palette()
        self.setStyleSheet(
            f"#SummaryPanel {{ background-color: {p['surface_alt']};"
            f"  border: 1px solid {p['border']}; border-radius: 2px; }}"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(12)
        self._label = QLabel("")
        self._label.setStyleSheet(label_style())
        self._label.setWordWrap(True)
        layout.addWidget(self._label, 1)

    def set_text(self, text: str) -> None:
        self._label.setText(text)

    def text(self) -> str:
        return self._label.text()


class StatusLabel(QLabel):
    """Small status/validation label colour-coded from the theme."""

    def __init__(self, text: str = "", parent: QWidget | None = None):
        super().__init__(text, parent)
        self.setStyleSheet(label_style())
        _mark(self, "status_label")
        try:
            self.setProperty("theme_level", "info")
        except Exception:
            pass
        self.setWordWrap(True)

    def set_status(self, text: str, level: str = "info") -> None:
        self.setText(text)
        try:
            self.setProperty("theme_level", level)
        except Exception:
            pass
        if level == "error":
            self.setStyleSheet(label_style(danger=True, bold=True))
        elif level == "success":
            self.setStyleSheet(label_style(success=True, bold=True))
        elif level == "warning":
            p = palette()
            self.setStyleSheet(
                f"color: {p['warning']}; font-size: {TYPE_FORM_LABEL}px;"
                f"font-weight: bold;"
                f"font-family: {FONT_FAMILY}; background: transparent;"
            )
        else:
            self.setStyleSheet(label_style())


class FormSection(QFrame):
    """A titled, bordered section grouping compact form fields."""

    def __init__(self, title: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("FormSection")
        _mark(self, "form_section")
        p = palette()
        self.setStyleSheet(
            f"#FormSection {{ background-color: {p['surface']};"
            f"  border: 1px solid {p['border']}; border-radius: 2px; }}"
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 7, 10, 7)
        outer.setSpacing(6)
        self._title = None
        if title:
            self._title = QLabel(title)
            self._title.setStyleSheet(section_title_style())
            outer.addWidget(self._title)
        self.body = QVBoxLayout()
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(6)
        outer.addLayout(self.body)

    def add_row(self, layout) -> None:
        self.body.addLayout(layout)

    def add_widget(self, widget: QWidget) -> None:
        self.body.addWidget(widget)


class FilterBar(QFrame):
    """Light blue filter strip; rows of label+control plus actions."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("FilterBar")
        _mark(self, "filter_bar")
        self.setStyleSheet(f"#FilterBar {{ {strip_style()} }}")
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(12, 7, 12, 7)
        self._layout.setSpacing(8)

    def add_field(self, label: str, widget: QWidget) -> None:
        lbl = QLabel(label)
        lbl.setStyleSheet(label_style())
        self._layout.addWidget(lbl)
        self._layout.addWidget(widget)

    def add_widget(self, widget: QWidget) -> None:
        self._layout.addWidget(widget)

    def add_stretch(self) -> None:
        self._layout.addStretch()

    def add_spacing(self, px: int) -> None:
        self._layout.addSpacing(px)


class SearchBar(FilterBar):
    """Filter bar specialised for a single search box with actions."""

    def __init__(self, placeholder: str = "Search...",
                 parent: QWidget | None = None):
        super().__init__(parent)
        from PySide6.QtWidgets import QLineEdit

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(placeholder)
        style_edit(self.search_edit)
        self.search_edit.setMinimumWidth(220)
        self.search_edit.setClearButtonEnabled(True)
        super().add_field("Search", self.search_edit)


class ConstrainedComboBox(QComboBox):
    """QComboBox with screen-aware popup sizing, alignment and item limits.

    - Limits visible items to approximately 8-10 entries (~250-280px max height).
    - Ensures a working vertical scrollbar is present when entries exceed the limit.
    - Keeps the popup aligned with its input field.
    - Matches field width by default while allowing moderate expansion up to
      a configurable maximum width for long names without covering adjacent controls.
    - Adapts to available screen space (opens upward if screen bottom is near).
    - Preserves keyboard navigation (type-to-search, Up/Down, Enter, Escape).
    - Also configures any attached QCompleter popup with the same height and item limits.
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        max_visible_items: int = 9,
        max_popup_height: int = 270,
        min_popup_height: int = 100,
        max_popup_width: int | None = None,
        min_popup_width: int | None = None,
        allow_width_expansion: bool = True,
    ):
        super().__init__(parent)
        self._max_visible = max_visible_items
        self._max_popup_height = max_popup_height
        self._min_popup_height = min_popup_height
        self._max_popup_width = max_popup_width
        self._min_popup_width = min_popup_width
        self._allow_width_expansion = allow_width_expansion

        self.setMaxVisibleItems(max_visible_items)
        view = self.view()
        if view is not None:
            view.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            popup = view.window()
            if popup is not None:
                popup.setMaximumHeight(max_popup_height)
                if max_popup_width is not None:
                    popup.setMaximumWidth(max_popup_width)

    def setCompleter(self, completer):
        super().setCompleter(completer)
        if completer is not None:
            completer.setMaxVisibleItems(self._max_visible)
            popup = completer.popup()
            if popup is not None:
                popup.setMaximumHeight(self._max_popup_height)
                popup.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
                popup.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    def showPopup(self):
        super().showPopup()
        view = self.view()
        if view is None:
            return
        popup = view.window()
        if popup is None:
            return

        from PySide6.QtCore import QPoint, QRect
        from PySide6.QtGui import QGuiApplication

        screen = self.screen() or QGuiApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)

        g_pos = self.mapToGlobal(QPoint(0, 0))
        combo_w = self.width()
        combo_h = self.height()

        target_w = combo_w
        if self._allow_width_expansion:
            model = view.model()
            needed_w = view.sizeHintForColumn(0) + 26 if (model and model.rowCount() > 0) else combo_w
            max_w = self._max_popup_width if self._max_popup_width is not None else (combo_w + 100)
            target_w = max(combo_w, min(needed_w, max_w))
        if self._max_popup_width is not None:
            target_w = min(target_w, self._max_popup_width)
        if self._min_popup_width is not None:
            target_w = max(target_w, self._min_popup_width)

        target_h = self._max_popup_height
        space_below = avail.bottom() - (g_pos.y() + combo_h)
        space_above = g_pos.y() - avail.top()

        if space_below >= target_h or space_below >= space_above:
            h = min(target_h, max(self._min_popup_height, space_below - 8))
            y = g_pos.y() + combo_h
        else:
            h = min(target_h, max(self._min_popup_height, space_above - 8))
            y = g_pos.y() - h

        x = g_pos.x()
        if x + target_w > avail.right() - 5:
            x = max(avail.left() + 5, avail.right() - target_w - 5)
        if x < avail.left() + 5:
            x = avail.left() + 5

        popup.setGeometry(QRect(x, y, target_w, h))
        if popup.layout():
            popup.layout().activate()


class SearchableComboBox(ConstrainedComboBox):
    """Editable, searchable combo box with case-insensitive partial matching.

    - Dynamic suggestions dropdown appears immediately on typing first character.
    - Displays suggestions directly BELOW the corresponding input field.
    - Filters results dynamically as each character is typed using case-insensitive substring matching.
    - Helpful 'No matching records found' message when query matches nothing.
    - Keyboard navigation: Down/Up to highlight, Enter to select, Escape to dismiss.
    - Mouse selection commits chosen item.
    - Prevents arbitrary text from being accepted (currentData returns None if text doesn't match).
    - Preserves selected supplier/item ID and updates associated fields.
    - Supports populate(), set_options(), addItem(), addItems(), and clear().
    """

    selection_changed = Signal(object)  # emits selected ID or None

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        placeholder: str = "",
        max_visible: int = 9,
        max_height: int = 270,
        max_width: int | None = None,
        min_width: int | None = None,
        allow_width_expansion: bool = True,
    ):
        super().__init__(
            parent,
            max_visible_items=max_visible,
            max_popup_height=max_height,
            max_popup_width=max_width,
            min_popup_width=min_width,
            allow_width_expansion=allow_width_expansion,
        )
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        self.setFixedHeight(32)

        self._placeholder = placeholder
        self._min_popup_width: int = min_width if min_width is not None else 320
        self._items_data: list[tuple[str, Any, str, int]] = []
        self._item_map: dict[str, int] = {}
        self._id_to_index: dict[Any, int] = {}
        self._block_filter: bool = False

        line = self.lineEdit()
        if line is not None:
            line.setPlaceholderText(placeholder)
            line.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            line.installEventFilter(self)
            line.textEdited.connect(self._on_text_edited)
            line.editingFinished.connect(self._resolve_current_text)

        self._completer_model = QStandardItemModel(self)
        self._completer = QCompleter(self._completer_model, self)
        self._completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._completer.setFilterMode(Qt.MatchContains)
        self._completer.setCompletionMode(QCompleter.PopupCompletion)
        self._completer.setMaxVisibleItems(max_visible)

        popup = self._completer.popup()
        if popup is not None:
            popup.setFocusPolicy(Qt.NoFocus)
            popup.setSelectionMode(QAbstractItemView.SingleSelection)
            popup.installEventFilter(self)
            popup.setMaximumHeight(max_height)
            popup.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            popup.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            popup.clicked.connect(self._on_completer_index_activated)

        self.setCompleter(self._completer)
        self._completer.activated[QModelIndex].connect(self._on_completer_index_activated)

        self.currentIndexChanged.connect(self._on_index_changed)
        self.refresh_theme()

    def _on_index_changed(self, index: int) -> None:
        self.selection_changed.emit(self.currentData())

    def refresh_theme(self, p: dict | None = None):
        p = p or palette()
        surface = p["surface"]
        text = p["text"]
        border = p["border"]
        accent = p["accent"]
        selected_bg = p.get("selected", accent)
        selected_text = p.get("selected_text", "#ffffff")
        text_dim = p.get("text_dim", "#888888")

        self.setStyleSheet(
            f"QComboBox {{"
            f"  background-color: {surface}; color: {text};"
            f"  border: 1px solid {border}; border-radius: 2px;"
            f"  padding: 2px 6px; font-size: 15px; font-weight: bold; font-family: 'Segoe UI';"
            f"  min-height: 24px;"
            f"}}"
            f"QComboBox:hover {{ border: 1px solid {accent}; }}"
            f"QComboBox:focus {{ border: 1px solid {accent}; }}"
            f"QComboBox::drop-down {{"
            f"  subcontrol-origin: padding; subcontrol-position: top right;"
            f"  width: 22px; border-left: 1px solid {border};"
            f"}}"
            f"QComboBox QAbstractItemView {{"
            f"  background-color: {surface}; color: {text};"
            f"  border: 1px solid {border}; selection-background-color: {accent};"
            f"  selection-color: white; font-size: 15px; font-family: 'Segoe UI';"
            f"}}"
        )
        line = self.lineEdit()
        if line is not None:
            line.setStyleSheet(
                f"QLineEdit {{"
                f"  background: transparent; color: {text};"
                f"  border: none; padding: 1px 4px;"
                f"  font-size: 14px; font-weight: bold; font-family: 'Segoe UI';"
                f"}}"
            )
        popup = self._completer.popup()
        if popup is not None:
            popup.setStyleSheet(
                f"QAbstractItemView {{"
                f"  background-color: {surface}; color: {text};"
                f"  border: 1px solid {border};"
                f"  selection-background-color: {selected_bg}; selection-color: {selected_text};"
                f"  font-size: 15px; font-family: 'Segoe UI'; outline: 0;"
                f"}}"
                f"QAbstractItemView::item {{ min-height: 26px; padding: 2px 8px; }}"
                f"QAbstractItemView::item:disabled {{ color: {text_dim}; font-style: italic; background-color: transparent; }}"
                f"QAbstractItemView::item:selected {{ background-color: {selected_bg}; color: {selected_text}; }}"
            )

    def clear(self):
        """Clear all combo items, completer model, and mappings."""
        self._block_filter = True
        try:
            super().clear()
            self._items_data.clear()
            self._item_map.clear()
            self._id_to_index.clear()
            self._completer_model.clear()
            line = self.lineEdit()
            if line is not None:
                line.clear()
                line.setToolTip("")
        finally:
            self._block_filter = False

    def addItem(self, text: str, data: Any = None, raw_name: str | None = None):
        """Add a single item and update completer mapping."""
        raw = raw_name if raw_name is not None else text
        idx = len(self._items_data)
        text_str = str(text or "")
        raw_str = str(raw or "")
        self._items_data.append((text_str, data, raw_str, idx))
        super().addItem(text_str, data)
        self.setItemData(idx, raw_str, Qt.UserRole + 1)

        t_key = text_str.strip().casefold()
        if t_key:
            self._item_map[t_key] = idx
        r_key = raw_str.strip().casefold()
        if r_key:
            self._item_map[r_key] = idx
        if data is not None:
            try:
                self._id_to_index[data] = idx
            except TypeError:
                pass
            if isinstance(data, dict) and "id" in data:
                self._id_to_index[data["id"]] = idx

        # When first item is added to QComboBox, Qt auto-selects it. Keep unselected:
        if super().count() == 1 and self.currentIndex() == 0 and data is None:
            super().setCurrentIndex(-1)
            line = self.lineEdit()
            if line is not None:
                line.clear()

    def addItems(self, texts: list[str]):
        """Add multiple text items."""
        for t in texts:
            self.addItem(t)

    def populate(self, items: list[tuple[Any, ...]]):
        """Populate items and update the completer model in a single fast batch.
        Initializes the combo in an empty, unselected state.
        Each item is either (text, data) or (display_text, data, raw_name).
        """
        self.blockSignals(True)
        self._block_filter = True
        try:
            self.clear()
            for entry in items:
                if len(entry) >= 3:
                    text, data, raw_name = entry[0], entry[1], entry[2]
                elif len(entry) == 2:
                    if isinstance(entry[0], (int, type(None))) and isinstance(entry[1], str):
                        data, text = entry[0], entry[1]
                    else:
                        text, data = entry[0], entry[1]
                    raw_name = text
                else:
                    text = entry[0]
                    data = None
                    raw_name = text
                self.addItem(text, data, raw_name)

            super().setCurrentIndex(-1)
            line = self.lineEdit()
            if line is not None:
                line.clear()
                line.setToolTip("")
        finally:
            self._block_filter = False
            self.blockSignals(False)

    def set_options(
        self,
        rows: list[dict],
        id_key: str = "id",
        name_key: str = "name",
        subtitle_key: str | None = None,
    ) -> None:
        """Populate options from a list of master records."""
        self._options = list(rows)
        items = []
        for row in rows:
            name = str(row.get(name_key) or "").strip()
            item_id = row.get(id_key)
            if subtitle_key and row.get(subtitle_key):
                sub = str(row[subtitle_key]).strip()
                if sub and sub.casefold() not in name.casefold():
                    display = f"{name}  [{sub}]"
                else:
                    display = name
            else:
                display = name
            items.append((display, item_id, name))
        self.populate(items)

    @property
    def options(self) -> list[dict]:
        return getattr(self, "_options", [])

    @property
    def selected_id(self) -> Any:
        return self.currentData()

    @property
    def selected_name(self) -> str:
        if self.currentData() is None:
            return ""
        idx = self.currentIndex()
        return self.itemText(idx) if idx >= 0 else ""

    def set_selected_id(self, item_id: Any) -> None:
        if item_id is None:
            self.clear_selection()
            return
        if hasattr(self, "_id_to_index") and item_id in self._id_to_index:
            self.setCurrentIndex(self._id_to_index[item_id])
            return
        for idx in range(self.count()):
            if self.itemData(idx) == item_id:
                self.setCurrentIndex(idx)
                return
        self.clear_selection()

    def clear_selection(self):
        """Reset combo to empty/unselected state and clear lineEdit text."""
        self.setCurrentIndex(-1)
        line = self.lineEdit()
        if line is not None:
            line.clear()
            line.setToolTip("")

    def setCurrentIndex(self, index: int):
        super().setCurrentIndex(index)
        line = self.lineEdit()
        if line is not None:
            if index >= 0:
                txt = self.itemText(index)
                line.setText(txt)
                line.setCursorPosition(0)
                line.setToolTip(txt)
            else:
                line.clear()
                line.setToolTip("")

    def currentText(self) -> str:
        line = self.lineEdit()
        if line is not None:
            return line.text().strip()
        idx = self.currentIndex()
        if idx >= 0:
            return self.itemText(idx)
        return ""

    def _on_text_edited(self, text: str):
        """Dynamically filter suggestions on typing each character and display dropdown below."""
        if getattr(self, "_block_filter", False):
            return
        query = text.strip()
        popup = self._completer.popup()
        if not query:
            if popup and popup.isVisible():
                popup.hide()
            self.setCurrentIndex(-1)
            self.selection_changed.emit(None)
            return

        q_fold = query.casefold()
        matches = [
            it for it in self._items_data
            if (it[1] is not None or not it[0].startswith("--"))
            and (q_fold in it[0].casefold() or q_fold in it[2].casefold())
        ]

        self._completer_model.clear()
        if matches:
            for m in matches:
                item = QStandardItem(m[0])
                item.setData(m[1], Qt.UserRole)
                item.setData(m[0], Qt.DisplayRole)
                if len(m) >= 4:
                    item.setData(m[3], Qt.UserRole + 2)
                self._completer_model.appendRow(item)
        else:
            short_q = (query[:35] + '...') if len(query) > 35 else query
            no_match_text = f"No matching records found for '{short_q}'"
            item = QStandardItem(no_match_text)
            item.setEnabled(False)
            item.setData(None, Qt.UserRole)
            self._completer_model.appendRow(item)

        self._completer.setCompletionPrefix("")
        self._completer.complete()
        self._position_completion_popup()

    def _position_completion_popup(self):
        """Position the completer dropdown directly BELOW the input field."""
        popup = self._completer.popup()
        if not popup or not popup.isVisible():
            return
        bottom_left = self.mapToGlobal(QPoint(0, self.height()))
        x = bottom_left.x()
        y = bottom_left.y() + 2
        min_w = getattr(self, "_min_popup_width", 320) or 320
        width = max(self.width(), min_w)

        count = self._completer_model.rowCount()
        row_height = max(26, popup.sizeHintForRow(0) if count > 0 else 26)
        visible_rows = min(max(count, 1), 8)
        height = row_height * visible_rows + 6

        screen = QApplication.primaryScreen()
        if screen:
            screen_geo = screen.availableGeometry()
            if y + height > screen_geo.bottom() and bottom_left.y() - self.height() - height >= screen_geo.top():
                y = self.mapToGlobal(QPoint(0, 0)).y() - height - 2

        popup.setGeometry(QRect(x, y, width, height))

    def show_all_suggestions(self):
        """Show full suggestion dropdown without text filter."""
        popup = self._completer.popup()
        if not self._items_data:
            return
        self._completer_model.clear()
        for m in self._items_data:
            if m[1] is None and m[0].startswith("--"):
                continue
            item = QStandardItem(m[0])
            item.setData(m[1], Qt.UserRole)
            item.setData(m[0], Qt.DisplayRole)
            if len(m) >= 4:
                item.setData(m[3], Qt.UserRole + 2)
            self._completer_model.appendRow(item)
        self._completer.setCompletionPrefix("")
        self._completer.complete()
        self._position_completion_popup()

    def showPopup(self):
        line = self.lineEdit()
        text = line.text().strip() if line is not None else ""
        if text and text != getattr(self, "_placeholder", ""):
            self._on_text_edited(text)
        else:
            self.show_all_suggestions()

    def findData(self, data: Any, role: int = Qt.UserRole) -> int:
        idx = super().findData(data, role)
        if idx >= 0:
            return idx
        if isinstance(data, (int, str)) and hasattr(self, "_id_to_index") and data in self._id_to_index:
            return self._id_to_index[data]
        if isinstance(data, int):
            for i in range(self.count()):
                d = self.itemData(i, role)
                if isinstance(d, dict) and d.get("id") == data:
                    return i
        return -1

    def _find_matching_index(self, text: str) -> int:
        folded = text.strip().casefold()
        if not folded:
            return -1
        if hasattr(self, "_item_map") and folded in self._item_map:
            return self._item_map[folded]
        idx = self.findText(text.strip(), Qt.MatchFixedString)
        if idx >= 0:
            return idx
        for i in range(self.count()):
            if self.itemText(i).strip().casefold() == folded:
                return i
            raw = self.itemData(i, Qt.UserRole + 1)
            if raw and str(raw).strip().casefold() == folded:
                return i
        return -1

    def _on_completer_index_activated(self, index: QModelIndex):
        """Handle selection of an item from the completer popup."""
        if not index.isValid():
            return
        data = index.data(Qt.UserRole)
        if data is None:
            # Disabled item (e.g. 'No matching records found')
            return
        text = index.data(Qt.DisplayRole)
        combo_idx = index.data(Qt.UserRole + 2)
        self._block_filter = True
        try:
            if combo_idx is not None and isinstance(combo_idx, int) and 0 <= combo_idx < self.count():
                idx = combo_idx
            else:
                idx = self._find_matching_index(str(text))
            if idx >= 0:
                self.setCurrentIndex(idx)
                line = self.lineEdit()
                if line is not None:
                    line.setText(self.itemText(idx))
                    line.setCursorPosition(0)
            else:
                line = self.lineEdit()
                if line is not None:
                    line.setText(str(text))
        finally:
            self._block_filter = False

        popup = self._completer.popup()
        if popup and popup.isVisible():
            popup.hide()

        self.selection_changed.emit(self.currentData())

    def _resolve_current_text(self):
        if getattr(self, "_block_filter", False):
            return
        line = self.lineEdit()
        if not line:
            return
        text = line.text().strip()
        if not text or text == getattr(self, "_placeholder", ""):
            self.setCurrentIndex(-1)
            return

        # 1. Exact match with display or raw name
        match_idx = self._find_matching_index(text)
        if match_idx >= 0 and self.itemData(match_idx) is not None:
            if self.currentIndex() != match_idx:
                self.setCurrentIndex(match_idx)
            line.setText(self.itemText(match_idx))
            return

        # 2. If text unambiguously matches exactly one item in _items_data, resolve it
        matches = [
            it for it in self._items_data
            if (it[1] is not None or not it[0].startswith("--"))
            and (text.casefold() in it[0].casefold() or text.casefold() in it[2].casefold())
        ]
        if len(matches) == 1:
            cand_idx = matches[0][3] if len(matches[0]) >= 4 else self._find_matching_index(matches[0][0])
            if cand_idx >= 0 and self.itemData(cand_idx) is not None:
                if self.currentIndex() != cand_idx:
                    self.setCurrentIndex(cand_idx)
                line.setText(self.itemText(cand_idx))
                return

        # 3. No match or ambiguous match: clear selection
        self.setCurrentIndex(-1)

    def resolve_text(self) -> bool:
        """Resolve current lineEdit text against available items.
        Returns True if a valid item is selected/resolved, False otherwise.
        """
        if self.currentData() is not None:
            return True
        self.blockSignals(True)
        try:
            self._resolve_current_text()
        finally:
            self.blockSignals(False)
        return self.currentData() is not None

    def currentData(self, role: int = Qt.UserRole) -> Any:
        line = self.lineEdit()
        typed = line.text().strip() if line is not None else ""
        if not typed or typed == getattr(self, "_placeholder", ""):
            return None
        idx = self.currentIndex()
        if idx >= 0:
            item_txt = self.itemText(idx).strip()
            if typed.casefold() == item_txt.casefold():
                return super().currentData(role)
            raw_name = self.itemData(idx, Qt.UserRole + 1)
            if raw_name and typed.casefold() == str(raw_name).strip().casefold():
                return super().currentData(role)
        # Attempt exact match with master record names or display names
        match_idx = self._find_matching_index(typed)
        if match_idx >= 0 and super().itemData(match_idx, role) is not None:
            return super().itemData(match_idx, role)
        return None

    def eventFilter(self, obj, event):
        line = self.lineEdit()
        if obj == line:
            if event.type() in (QEvent.MouseButtonPress, QEvent.FocusIn):
                QTimer.singleShot(0, line.selectAll)
            elif event.type() == QEvent.KeyPress:
                key = event.key()
                popup = self._completer.popup()
                if key == Qt.Key_Escape:
                    if popup and popup.isVisible():
                        popup.hide()
                        return True
                elif key in (Qt.Key_Down, Qt.Key_Up):
                    if not popup or not popup.isVisible():
                        text = line.text().strip()
                        if text and text != getattr(self, "_placeholder", ""):
                            self._on_text_edited(text)
                        else:
                            self.show_all_suggestions()
                        return True
                    count = self._completer_model.rowCount()
                    if count:
                        cur_row = popup.currentIndex().row()
                        step = 1 if key == Qt.Key_Down else -1
                        next_row = 0 if cur_row < 0 and key == Qt.Key_Down else (count - 1 if cur_row < 0 else cur_row + step)
                        while 0 <= next_row < count:
                            idx = self._completer_model.index(next_row, 0)
                            if idx.data(Qt.UserRole) is not None:
                                popup.setCurrentIndex(idx)
                                popup.scrollTo(idx)
                                return True
                            next_row += step
                        return True
                elif key in (Qt.Key_Return, Qt.Key_Enter):
                    if popup and popup.isVisible():
                        idx = popup.currentIndex()
                        if not idx.isValid() or idx.data(Qt.UserRole) is None:
                            for r in range(self._completer_model.rowCount()):
                                cand = self._completer_model.index(r, 0)
                                if cand.data(Qt.UserRole) is not None:
                                    idx = cand
                                    break
                        if idx.isValid() and idx.data(Qt.UserRole) is not None:
                            self._on_completer_index_activated(idx)
                            return True
                    else:
                        self._resolve_current_text()
                        return False
                elif key in (Qt.Key_Tab, Qt.Key_Backtab):
                    if popup and popup.isVisible():
                        idx = popup.currentIndex()
                        if idx.isValid() and idx.data(Qt.UserRole) is not None:
                            self._on_completer_index_activated(idx)
                        popup.hide()
        return super().eventFilter(obj, event)


# ── Small helpers used by screens ─────────────────────────────────────

def subtitle(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(label_style(dim=True))
    return label


def style_edit(widget, *, upper: bool | None = None):
    """Apply the shared input style and, by default, upper-case entry.

    ``upper`` is the explicit switch for the automatic UPPERCASE rule in
    ``ui.input_rules``: ``True`` forces it, ``False`` opts the field out, and
    the default ``None`` leaves the application-wide policy in charge (which
    converts business data and already excludes passwords, read-only fields,
    file dialogs and numeric spin boxes).  Screens only need to pass it for
    the rare field that disagrees with the default.
    """
    widget.setStyleSheet(edit_style())
    _mark(widget, "edit")
    if upper is not None:
        from ui.input_rules import set_uppercase
        set_uppercase(widget, upper)
    return widget


def style_combo(widget, *, upper: bool | None = None):
    widget.setStyleSheet(combo_style())
    _mark(widget, "combo")
    # Editable combo text fields + dropdown views follow the app theme, but
    # an explicit mark lets refresh_tree() re-apply without guessing.
    try:
        from PySide6.QtWidgets import QComboBox
        if isinstance(widget, QComboBox) and widget.isEditable():
            line = widget.lineEdit()
            if line is not None:
                _mark(line, "combo_line")
    except Exception:
        pass
    if upper is not None:
        from ui.input_rules import set_uppercase
        set_uppercase(widget, upper)
    return widget


def style_date(widget):
    """Apply the shared date style and enable its calendar popup.

    Every editable date-selection control in the application must open a
    calendar when its button is clicked; the popup flag is set here so no
    screen can end up with a styled but popup-less field.  Read-only date
    *displays* (QLabels) never pass through this helper, so they are
    unaffected.
    """
    widget.setStyleSheet(date_style())
    _mark(widget, "date")
    try:
        widget.setCalendarPopup(True)
    except Exception:
        pass
    return widget


def style_label(widget, *, dim: bool = False, bold: bool = False,
                size: int = TYPE_FORM_LABEL):
    widget.setStyleSheet(label_style(dim=dim, bold=bold, size=size))
    try:
        widget.setProperty("theme_source", "components")
        widget.setProperty("theme_kind", "label")
        widget.setProperty("theme_dim", bool(dim))
        widget.setProperty("theme_bold", bool(bold))
        widget.setProperty("theme_size", int(size))
    except Exception:
        pass
    return widget


_FONT_SIZE_RE = re.compile(r"font-size:\s*\d+(?:px|pt)")


def _declares_own_font(stylesheet: str) -> bool:
    """True when a widget's own stylesheet already pins a font size."""
    return bool(stylesheet) and bool(_FONT_SIZE_RE.search(stylesheet))


def polish_page(root: QWidget) -> QWidget:
    """Apply the shared compact data-table treatment to a whole page.

    Called centrally by the main window for every page so tables look
    identical everywhere (visible grid, compact rows, row selection)
    without each screen duplicating the setup.

    It also enforces the readable typography floor on any table or header
    that does **not** declare its own font size: a Qt stylesheet
    ``font-size`` outranks ``setFont()``, so the QFont is only a reliable
    floor when the stylesheet is silent about size.  Screens that declare
    their own (larger or equal) size keep full control.
    """
    # Include the root itself when it IS a table/header (unit tests pass a
    # bare QTableWidget as root; findChildren() only returns descendants).
    try:
        tables = list(root.findChildren(QTableWidget))
        if isinstance(root, QTableWidget) and root not in tables:
            tables.insert(0, root)
    except Exception:
        tables = []
    for table in tables:
        table.setShowGrid(True)
        table.setWordWrap(False)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
        if not _declares_own_font(table.styleSheet()):
            table.setFont(readable_font(TYPE_TABLE_DATA))
            if not table.styleSheet():
                table.setStyleSheet(table_style())
                _mark(table, "table")
        else:
            # Screen pins its own size: mirror it into the QFont so metrics
            # (column sizing, row-height checks) agree with the stylesheet.
            # Stylesheet wins rendering; the font is only the measurement.
            try:
                m = _FONT_SIZE_RE.search(table.styleSheet())
                if m:
                    size = int(re.search(r"\d+", m.group(0)).group(0))
                    table.setFont(readable_font(size))
            except Exception:
                pass
        header = table.horizontalHeader()
        if header.height() <= 0:
            header.setFixedHeight(HEADER_HEIGHT)
        header.setHighlightSections(False)
    try:
        headers = list(root.findChildren(QHeaderView))
        if isinstance(root, QHeaderView) and root not in headers:
            headers.insert(0, root)
        # A bare table root owns a header that findChildren missed.
        if isinstance(root, QTableWidget):
            hv = root.horizontalHeader()
            if hv is not None and hv not in headers:
                headers.insert(0, hv)
    except Exception:
        headers = []
    for header_view in headers:
        if not header_view.styleSheet():
            header_view.setStyleSheet(table_header_style())
            _mark(header_view, "table_header")
        if not _declares_own_font(header_view.styleSheet()):
            header_view.setFont(readable_font(TYPE_TABLE_HEADER, bold=True))
        else:
            try:
                m = _FONT_SIZE_RE.search(header_view.styleSheet())
                if m:
                    size = int(re.search(r"\d+", m.group(0)).group(0))
                    header_view.setFont(readable_font(size, bold=True))
            except Exception:
                pass
    # Controls that carry their own ``::indicator`` rule need the check-mark
    # glyph before the first paint, not only after the first Day/Night switch.
    try:
        refresh_indicators(root)
    except Exception:
        pass
    return root


def refresh_tree(root: QWidget) -> int:
    """Re-apply centralized components styles to a widget tree in place.

    Only widgets created through ``ui.components`` helpers (tagged with the
    ``theme_source=components`` property) are touched, so screen-specific
    custom styles (entry bars, bill tables, variant buttons) are never
    overwritten here — their owning screen's ``refresh_theme()`` handles
    those with full role knowledge.  Returns the number of widgets updated.

    This preserves layout, focus, selection and all business state: only
    stylesheet strings (and matching QFonts) are recomputed from the live
    centralized palette.
    """
    try:
        widgets = [root] + list(root.findChildren(QWidget))
    except Exception:
        return 0
    updated = 0
    for widget in widgets:
        try:
            source = widget.property("theme_source")
        except Exception:
            continue
        if source != "components":
            continue
        try:
            kind = widget.property("theme_kind")
        except Exception:
            continue
        if not kind:
            continue
        try:
            if kind == "table":
                from PySide6.QtWidgets import QTableWidget
                if isinstance(widget, QTableWidget):
                    widget.setStyleSheet(table_style())
                    widget.setFont(readable_font(TYPE_TABLE_DATA))
                    updated += 1
            elif kind == "table_header":
                from PySide6.QtWidgets import QHeaderView
                if isinstance(widget, QHeaderView):
                    widget.setStyleSheet(table_header_style())
                    widget.setFont(readable_font(TYPE_TABLE_HEADER, bold=True))
                    updated += 1
            elif kind == "edit":
                widget.setStyleSheet(edit_style())
                updated += 1
            elif kind == "combo":
                widget.setStyleSheet(combo_style())
                updated += 1
            elif kind == "date":
                widget.setStyleSheet(date_style())
                updated += 1
            elif kind == "label":
                try:
                    dim = bool(widget.property("theme_dim"))
                    bold = bool(widget.property("theme_bold"))
                    size = int(widget.property("theme_size") or TYPE_FORM_LABEL)
                except Exception:
                    dim, bold, size = False, False, TYPE_FORM_LABEL
                widget.setStyleSheet(
                    label_style(dim=dim, bold=bold, size=size)
                )
                updated += 1
            elif kind == "status_label":
                try:
                    level = str(widget.property("theme_level") or "info")
                except Exception:
                    level = "info"
                if hasattr(widget, "set_status"):
                    # Recompute without changing text.
                    text = widget.text()
                    widget.set_status(text, level)
                    updated += 1
                else:
                    widget.setStyleSheet(label_style())
                    updated += 1
            elif isinstance(kind, str) and kind.startswith("button:"):
                variant = kind.split(":", 1)[1] or "secondary"
                try:
                    height = widget.property("theme_height")
                    height = int(height) if height else None
                except Exception:
                    height = None
                style_button(widget, variant, height=height)
                updated += 1
            elif kind in ("page_header", "filter_bar"):
                widget.setStyleSheet(
                    f"#{widget.objectName()} {{ {strip_style()} }}"
                )
                updated += 1
            elif kind == "summary_panel":
                p = palette()
                widget.setStyleSheet(
                    f"#SummaryPanel {{ background-color: {p['surface_alt']};"
                    f"  border: 1px solid {p['border']}; border-radius: 2px; }}"
                )
                updated += 1
            elif kind == "form_section":
                p = palette()
                widget.setStyleSheet(
                    f"#FormSection {{ background-color: {p['surface']};"
                    f"  border: 1px solid {p['border']}; border-radius: 2px; }}"
                )
                updated += 1
        except Exception:
            continue
    # Title / subtitle labels inside PageHeader follow the title style.
    for widget in widgets:
        try:
            parent = widget.parent()
            if (parent is not None
                    and parent.objectName() == "PageHeader"
                    and source != "components"):
                pass
        except Exception:
            pass
    return updated


def refresh_popups(root: QWidget) -> int:
    """Refresh combo-dropdown and completer-popup views under a widget.

    QCompleter popups and QComboBox dropdown views are top-level windows
    owned by their combo but styled explicitly at construction with baked
    hex values.  The application stylesheet already covers the generic
    ``QComboBox QAbstractItemView`` / ``QAbstractItemView`` selectors, so
    explicitly-styled popups only need a repolish here; screens with custom
    popup colours refresh them in their own ``refresh_theme()``.
    """
    updated = 0
    try:
        from PySide6.QtWidgets import QComboBox
        combos = root.findChildren(QComboBox)
    except Exception:
        return 0
    for combo in combos:
        try:
            view = combo.view()
            if view is not None:
                style = view.style()
                if style is not None:
                    style.unpolish(view)
                    style.polish(view)
                view.update()
                updated += 1
        except Exception:
            continue
        try:
            completer = combo.completer()
            popup = completer.popup() if completer is not None else None
            if popup is not None:
                style = popup.style()
                if style is not None:
                    style.unpolish(popup)
                    style.polish(popup)
                popup.update()
                updated += 1
        except Exception:
            continue
    return updated


def refresh_generic_screen(root: QWidget) -> int:
    """In-place Day/Night refresh for screens with baked module styles.

    Most screens (Purchase, Account, Reports, Masters) build their
    stylesheets once at import from ``palette()`` (``_DARK_BG``,
    ``_SURFACE``, ``_GROUP_BOX``, ``_COMBO_STYLE`` …).  After a theme switch
    those baked hex values are stale (dark ``#000000`` persisting in Day
    Mode is the black-rectangle bug).  This refreshes the common patterns
    in place — preserving layout, inputs, selection and drafts — using only
    the live centralized palette:

    * page / panel backgrounds (``background-color`` bg role — safe),
    * QGroupBox (adds the missing opaque ``bg`` + title ``bg``),
    * tables + headers (bg / text / border / grid; selection maps to the
      screen's own accent convention — white on accent stays readable),
    * combos / edits / dates (surface bg, text, border, accent focus;
      dropdown + completer popups follow the item-view colours),
    * buttons (variant inferred from fixed structure; primary white-on-
      accent text is preserved, never flipped to black),
    * transparent labels (text vs dim roles inferred from both palettes).

    Screens with their own ``refresh_theme()`` (Counter Sale) are handled
    there with full role knowledge; this is the safe fallback for every
    other screen.  Returns widgets updated.
    """
    try:
        from PySide6.QtWidgets import (
            QCheckBox, QComboBox, QDateEdit, QGroupBox, QLabel, QLineEdit,
            QPushButton, QRadioButton, QTableWidget, QWidget, QHeaderView,
        )
    except Exception:
        return 0
    try:
        p = palette()
    except Exception:
        return 0
    try:
        widgets = [root] + list(root.findChildren(QWidget))
    except Exception:
        return 0
    try:
        from ui.theme import _PALETTES as _PALS
        all_bg = {str(_PALS[m].get("bg", "")).lower() for m in _PALS}
        all_surface = {str(_PALS[m].get("surface", "")).lower() for m in _PALS}
        all_text = {str(_PALS[m].get("text", "")).lower() for m in _PALS}
        all_dim = {str(_PALS[m].get("text_dim", "")).lower() for m in _PALS}
        all_border = {str(_PALS[m].get("border", "")).lower() for m in _PALS}
        all_accent = {str(_PALS[m].get("accent", "")).lower() for m in _PALS}
    except Exception:
        all_bg = all_surface = all_text = all_dim = set()
        all_border = all_accent = set()
    updated = 0
    import re as _re
    for w in widgets:
        try:
            # Skip components-tagged widgets (handled by refresh_tree) and
            # Counter Sale widgets (handled by refresh_cs_tree).
            try:
                if w.property("theme_source") == "components":
                    continue
                if w.property("cs_style") is not None:
                    continue
            except Exception:
                pass
            if isinstance(w, QGroupBox):
                ss = w.styleSheet() if hasattr(w, "styleSheet") else ""
                if "QGroupBox" not in ss:
                    continue
                # Preserve the screen's own font-size/weight; only colours.
                size_m = _re.search(r"font-size:\s*(\d+)px", ss)
                size = size_m.group(1) if size_m else "12"
                weight = "font-weight: bold;" if "font-weight: bold" in ss else ""
                w.setStyleSheet(
                    f"QGroupBox {{"
                    f"  background-color: {p['bg']};"
                    f"  color: {p['text']}; {weight} font-size: {size}px;"
                    f"  font-family: {FONT_FAMILY};"
                    f"  border: 1px solid {p['border']}; border-radius: 2px;"
                    f"  margin-top: 10px; padding-top: 14px;"
                    f"}}"
                    f"QGroupBox::title {{ subcontrol-origin: margin; left: 10px;"
                    f" padding: 0 6px; color: {p['text']};"
                    f" background-color: {p['bg']}; }}"
                )
                updated += 1
                continue
            if isinstance(w, (QCheckBox, QRadioButton)):
                if _apply_indicator(w):
                    updated += 1
                continue
            if isinstance(w, QTableWidget):
                ss = w.styleSheet() if hasattr(w, "styleSheet") else ""
                if "QTableWidget" not in ss and not ss.strip() == "":
                    # Unstyled tables follow the app stylesheet + palette.
                    continue
                if "QTableWidget" not in ss:
                    continue
                pad_m = _re.search(r"QTableWidget::item\s*\{\{\s*padding:\s*([^;]+);", ss)
                pad = pad_m.group(1).strip() if pad_m else "3px 6px"
                # Screens use accent selection + white text (readable both).
                w.setStyleSheet(
                    f"QTableWidget {{"
                    f"  background-color: {p['bg']}; color: {p['text']};"
                    f"  border: 1px solid {p['border']}; gridline-color: {p['grid']};"
                    f"  font-size: {TYPE_TABLE_DATA}px; font-family: {FONT_FAMILY};"
                    f"  selection-background-color: {p['accent']};"
                    f"  selection-color: white;"
                    f"}}"
                    f"QTableWidget::item {{ padding: {pad}; }}"
                )
                try:
                    hv = w.horizontalHeader()
                    hss = hv.styleSheet() if hasattr(hv, "styleSheet") else ""
                    if "QHeaderView::section" in hss or True:
                        hv.setStyleSheet(table_header_style())
                except Exception:
                    pass
                updated += 1
                continue
            if isinstance(w, QHeaderView):
                # Standalone header views (covered with their table above).
                continue
            if isinstance(w, QComboBox):
                ss = w.styleSheet() if hasattr(w, "styleSheet") else ""
                if "QComboBox" not in ss:
                    continue
                # In-place colour refresh: preserve the screen's own metrics
                # (padding, fonts, drop-down width) and surface-vs-bg roles;
                # only centralized hex values are swapped.  Screens use
                # surface fills with palette text; dropdown selection stays
                # accent (white on accent is readable both modes).
                try:
                    new_ss = ss
                    for old, new in (
                        (_PALS["dark"]["surface"], p["surface"]),
                        (_PALS["light"]["surface"], p["surface"]),
                        (_PALS["dark"]["bg"], p["bg"]),
                        (_PALS["light"]["bg"], p["bg"]),
                        (_PALS["dark"]["text"], p["text"]),
                        (_PALS["light"]["text"], p["text"]),
                        (_PALS["dark"]["border"], p["border"]),
                        (_PALS["light"]["border"], p["border"]),
                        (_PALS["dark"]["accent"], p["accent"]),
                        (_PALS["light"]["accent"], p["accent"]),
                    ):
                        if old and new and old.lower() != new.lower():
                            new_ss = _re.sub(_re.escape(old), new, new_ss,
                                             flags=_re.IGNORECASE)
                    # Focus ring follows the focus token (== accent).
                    if new_ss != ss:
                        w.setStyleSheet(new_ss)
                        updated += 1
                except Exception:
                    pass
                try:
                    view = w.view()
                    if view is not None:
                        view.update()
                except Exception:
                    pass
                try:
                    comp = w.completer()
                    pop = comp.popup() if comp is not None else None
                    if pop is not None:
                        try:
                            pss = pop.styleSheet() if hasattr(pop, "styleSheet") else ""
                            if pss and "QAbstractItemView" in pss:
                                new_pss = pss
                                for old, new in (
                                    (_PALS["dark"]["surface"], p["surface"]),
                                    (_PALS["light"]["surface"], p["surface"]),
                                    (_PALS["dark"]["bg"], p["bg"]),
                                    (_PALS["light"]["bg"], p["bg"]),
                                    (_PALS["dark"]["text"], p["text"]),
                                    (_PALS["light"]["text"], p["text"]),
                                    (_PALS["dark"]["border"], p["border"]),
                                    (_PALS["light"]["border"], p["border"]),
                                    (_PALS["dark"]["accent"], p["accent"]),
                                    (_PALS["light"]["accent"], p["accent"]),
                                ):
                                    if old and new and old.lower() != new.lower():
                                        new_pss = _re.sub(_re.escape(old), new, new_pss,
                                                          flags=_re.IGNORECASE)
                                if new_pss != pss:
                                    pop.setStyleSheet(new_pss)
                            pop.update()
                        except Exception:
                            try:
                                pop.update()
                            except Exception:
                                pass
                except Exception:
                    pass
                continue
            if isinstance(w, QLineEdit):
                try:
                    parent = w.parent()
                    from PySide6.QtWidgets import QComboBox as _CB
                    if parent is not None and isinstance(parent, _CB):
                        continue
                except Exception:
                    pass
                ss = w.styleSheet() if hasattr(w, "styleSheet") else ""
                if "QLineEdit" not in ss:
                    continue
                try:
                    new_ss = ss
                    for old, new in (
                        (_PALS["dark"]["surface"], p["surface"]),
                        (_PALS["light"]["surface"], p["surface"]),
                        (_PALS["dark"]["bg"], p["bg"]),
                        (_PALS["light"]["bg"], p["bg"]),
                        (_PALS["dark"]["text"], p["text"]),
                        (_PALS["light"]["text"], p["text"]),
                        (_PALS["dark"]["border"], p["border"]),
                        (_PALS["light"]["border"], p["border"]),
                        (_PALS["dark"]["accent"], p["accent"]),
                        (_PALS["light"]["accent"], p["accent"]),
                    ):
                        if old and new and old.lower() != new.lower():
                            new_ss = _re.sub(_re.escape(old), new, new_ss,
                                             flags=_re.IGNORECASE)
                    if new_ss != ss:
                        w.setStyleSheet(new_ss)
                        updated += 1
                except Exception:
                    pass
                continue
            if isinstance(w, QDateEdit):
                ss = w.styleSheet() if hasattr(w, "styleSheet") else ""
                if "QDateEdit" not in ss:
                    continue
                try:
                    # First remap the baked base colours (bg/text/border/
                    # accent), preserving the screen's own metrics, then
                    # replace the icon-hiding drop-down/arrow rules with the
                    # shared visible chevron.  A plain hex remap alone would
                    # preserve `image: none` and keep the icon invisible.
                    new_ss = ss
                    for old, new in (
                        (_PALS["dark"]["surface"], p["surface"]),
                        (_PALS["light"]["surface"], p["surface"]),
                        (_PALS["dark"]["bg"], p["bg"]),
                        (_PALS["light"]["bg"], p["bg"]),
                        (_PALS["dark"]["text"], p["text"]),
                        (_PALS["light"]["text"], p["text"]),
                        (_PALS["dark"]["border"], p["border"]),
                        (_PALS["light"]["border"], p["border"]),
                        (_PALS["dark"]["accent"], p["accent"]),
                        (_PALS["light"]["accent"], p["accent"]),
                    ):
                        if old and new and old.lower() != new.lower():
                            new_ss = _re.sub(_re.escape(old), new, new_ss,
                                             flags=_re.IGNORECASE)
                    try:
                        from ui.theme import fix_date_stylesheet as _fix_dates
                        new_ss = _fix_dates(new_ss, p)
                    except Exception:
                        pass
                    try:
                        if not w.calendarPopup():
                            w.setCalendarPopup(True)
                    except Exception:
                        pass
                    if new_ss != ss:
                        w.setStyleSheet(new_ss)
                        updated += 1
                    elif "down-arrow" not in ss and "drop-down" not in ss:
                        # Unstyled date field follows the app stylesheet;
                        # repolish so the global chevron applies.
                        try:
                            style = w.style()
                            if style is not None:
                                style.unpolish(w)
                                style.polish(w)
                            w.update()
                        except Exception:
                            pass
                except Exception:
                    pass
                continue
            if isinstance(w, QPushButton):
                ss = w.styleSheet() if hasattr(w, "styleSheet") else ""
                if "QPushButton" not in ss:
                    continue
                # In-place variant-aware refresh: saturated fills (accent /
                # error red) keep white text in both modes; muted fills
                # follow the palette text.  Padding, radius and fonts are
                # preserved so layout never shifts.
                try:
                    lower = ss.lower()
                    saturated = (
                        "#c0392b" in lower or "#c62828" in lower
                        or "#2e7d32" in lower or "#2f6fb0" in lower
                        or any(a and a.lower() in lower for a in all_accent)
                    )
                    new_ss = ss
                    # Background fills follow their roles.
                    for old, new in (
                        (_PALS["dark"]["accent"], p["accent"]),
                        (_PALS["light"]["accent"], p["accent"]),
                        (_PALS["dark"]["border"], p["border"]),
                        (_PALS["light"]["border"], p["border"]),
                        (_PALS["dark"]["surface"], p["surface"]),
                        (_PALS["light"]["surface"], p["surface"]),
                        (_PALS["dark"]["bg"], p["bg"]),
                        (_PALS["light"]["bg"], p["bg"]),
                    ):
                        if old and new and old.lower() != new.lower():
                            # Only swap background-color occurrences to avoid
                            # touching border/text hexes that share values.
                            new_ss = _re.sub(
                                r"(background-color:\s*)" + _re.escape(old),
                                r"\1" + new, new_ss, flags=_re.IGNORECASE)
                    if not saturated:
                        # Muted button: text follows the palette.
                        for old, new in (
                            (_PALS["dark"]["text"], p["text"]),
                            (_PALS["light"]["text"], p["text"]),
                        ):
                            if old and new and old.lower() != new.lower():
                                new_ss = _re.sub(
                                    r"(^|[;{}]\s*color:\s*)" + _re.escape(old),
                                    r"\1" + new, new_ss, flags=_re.IGNORECASE)
                    if new_ss != ss:
                        w.setStyleSheet(new_ss)
                        updated += 1
                except Exception:
                    pass
                continue
            if isinstance(w, QLabel):
                ss = w.styleSheet() if hasattr(w, "styleSheet") else ""
                if not ss or "background: transparent" not in ss:
                    continue
                m = _re.search(r"color:\s*(#[0-9a-fA-F]{6}|white|black)", ss)
                if not m:
                    continue
                col = m.group(1).lower()
                try:
                    if col in all_dim:
                        new_col = p["text_dim"]
                    elif col in all_text or col in ("#000000", "#ffffff", "black", "white"):
                        # White/black alone is ambiguous; a screen's dim
                        # hints declare the shared hint size without a bold
                        # weight, while a caption of the same nominal colour
                        # is bold.  The pre-scale hint size is still accepted
                        # so the inference keeps working for any screen that
                        # has not been moved onto the scale yet.
                        hint_markers = (f"font-size: {TYPE_HINT}px",
                                        f"font-size: {_LEGACY_HINT_PX}px")
                        if ("font-weight: bold" not in ss
                                and any(marker in ss
                                        for marker in hint_markers)):
                            new_col = p["text_dim"]
                        else:
                            new_col = p["text"]
                    else:
                        continue
                    w.setStyleSheet(ss[:m.start()] + f"color: {new_col}" + ss[m.end():])
                    updated += 1
                except Exception:
                    pass
                continue
        except Exception:
            continue
    # Page-level background (simple `background-color: <bg>` on the root).
    try:
        ss = root.styleSheet() if hasattr(root, "styleSheet") else ""
        if ss and "background-color:" in ss and "Q" not in ss.split("background-color:")[0][-20:]:
            import re as _re2
            root.setStyleSheet(f"background-color: {p['bg']};")
            updated += 1
        elif root.objectName() in ("", None) and ss.strip().startswith("background-color"):
            root.setStyleSheet(f"background-color: {p['bg']};")
            updated += 1
    except Exception:
        pass
    # Plain containers (page title strips, filter/tool bars, side panels).
    try:
        updated += refresh_containers(root)
    except Exception:
        pass
    return updated


# Property prefixes a container may legitimately carry a theme role under.
# ``color`` is deliberately absent: a container's foreground is either
# inherited from the shared stylesheet or is a deliberate constant (the
# white caption on the blue sales-bill header), and rewriting it would
# break the constant cases.
_CONTAINER_PROPS = ("background", "border", "gridline", "selection-background")

# A tooltip rule this module appended on an earlier switch.
_TOOLTIP_RULE_RE = re.compile(r"QToolTip\s*\{[^}]*\}")

# Any rule whose selector names the ``::indicator`` sub-control.
_INDICATOR_RULE_RE = re.compile(r"[^{}]*::indicator[^{}]*\{[^}]*\}")


def _with_tooltip_rule(sheet: str) -> str:
    """Append the mode's tooltip rule to a sheet that styles bare labels.

    Qt's tooltip widget is a ``QLabel``, so a widget-level rule like
    ``QLabel { color: …; background: transparent; }`` — used by most
    dialogs in this codebase — also matches the tooltip, and a widget-level
    rule outranks the application stylesheet.  The result was a transparent
    black tooltip in both modes.  Emitting the tooltip rule *after* it, at
    the same specificity, restores the readable note.

    Any tooltip rule appended by an earlier switch is removed first, so the
    sheet always ends up carrying the *current* mode's colours.  A sheet
    that cannot capture a tooltip is returned untouched.
    """
    stripped = _TOOLTIP_RULE_RE.sub("", sheet)
    if "QLabel" not in stripped:
        return sheet
    return stripped + tooltip_rule()


def _apply_indicator(widget) -> bool:
    """Rewrite one control's local ``::indicator`` rule; True if it changed.

    Screens that style the indicator themselves (Reports, Trial Balance)
    bake a size and colours into a module-level rule at import time.  Naming
    the ``::indicator`` sub-control is enough to stop Qt drawing the native
    check mark, so the rule has to carry the glyph explicitly — and it has
    to follow the mode.  The local size and the widget's own text rule are
    preserved.  Controls that do not style the indicator are left alone:
    they follow the application stylesheet.
    """
    from PySide6.QtWidgets import QRadioButton

    sheet = widget.styleSheet() if hasattr(widget, "styleSheet") else ""
    if "::indicator" not in sheet:
        return False
    size_m = re.search(r"width:\s*(\d+)px", sheet)
    size = int(size_m.group(1)) if size_m else 13
    base = _INDICATOR_RULE_RE.sub("", sheet).strip()
    if "#" in base:
        base = remap_baked_colors(base)
    is_radio = isinstance(widget, QRadioButton)
    fresh = base + indicator_style(
        checkbox=not is_radio, radio=is_radio, size=size
    )
    if fresh == sheet:
        return False
    widget.setStyleSheet(fresh)
    return True


def refresh_indicators(root: QWidget) -> int:
    """Refresh every checkbox / radio in a tree that styles its indicator.

    Called at page build time (so the check mark is right from the first
    paint) and on every Day/Night switch.  Returns widgets updated.
    """
    try:
        from PySide6.QtWidgets import QCheckBox, QRadioButton
    except Exception:  # pragma: no cover - headless
        return 0
    try:
        widgets = list(root.findChildren(QCheckBox)) + list(
            root.findChildren(QRadioButton)
        )
    except Exception:
        return 0
    updated = 0
    for widget in widgets:
        try:
            if _apply_indicator(widget):
                updated += 1
        except Exception:
            continue
    return updated


def refresh_containers(root: QWidget) -> int:
    """Re-apply live background/border roles to baked container stylesheets.

    Every screen styles its chrome — the page title strip, the search /
    filter toolbar and, on Counter Sale, the right-side ``BillPanel`` — with
    module-level constants captured at import time (``_SURFACE``,
    ``_BORDER``).  Those widgets are plain ``QWidget``/``QFrame`` containers,
    so none of the class-specific passes in this module or in
    ``screens.counter_sale.refresh_cs_tree`` reached them: after switching
    to Night Mode the strips and panels kept the Day Mode light-blue
    ``#dce9f6`` surface, and after switching back a stale dark surface could
    survive.  That is the mixed-theme defect.

    This pass rewrites only *background* and *border* declarations, and only
    when the baked value is the same role in one of the centralized
    palettes, so screen-specific constants (the Counter Sale error red, the
    sales-bill header blue) are never touched.  Layout, fonts and metrics
    are untouched.  Returns the number of widgets updated.
    """
    try:
        from PySide6.QtWidgets import QWidget as _QW
    except Exception:  # pragma: no cover - headless
        return 0
    try:
        widgets = [root] + list(root.findChildren(_QW))
    except Exception:
        return 0
    updated = 0
    for widget in widgets:
        try:
            if widget.property("theme_source") == "components":
                continue        # handled by refresh_tree
            if widget.property("cs_style") is not None:
                continue        # handled by refresh_cs_tree
            sheet = widget.styleSheet() if hasattr(widget, "styleSheet") else ""
            if not sheet:
                continue
            fresh = sheet
            if "#" in sheet:
                fresh = remap_baked_colors(sheet, only=_CONTAINER_PROPS)
            fresh = _with_tooltip_rule(fresh)
            if fresh != sheet:
                widget.setStyleSheet(fresh)
                updated += 1
        except Exception:
            continue
    return updated


__all__ = [
    "FONT_FAMILY", "FONT_NAME", "CONTROL_HEIGHT", "ROW_HEIGHT", "HEADER_HEIGHT",
    "ActionButton", "PageHeader", "SummaryPanel", "StatusLabel",
    "FormSection", "FilterBar", "SearchBar", "ConstrainedComboBox",
    "label_style", "title_style", "section_title_style", "edit_style",
    "combo_style", "date_style", "spin_style", "checkbox_style",
    "group_box_style", "btn_primary_style", "btn_secondary_style",
    "btn_success_style", "btn_danger_style", "btn_warning_style",
    "style_button", "table_style", "table_header_style",
    "style_data_table", "panel_style", "strip_style", "subtitle",
    "style_edit", "style_combo", "style_date", "style_label",
    "polish_page", "readable_font", "refresh_tree", "refresh_popups",
    "refresh_generic_screen", "refresh_containers", "refresh_indicators",
]
