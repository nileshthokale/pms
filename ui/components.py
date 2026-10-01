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

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from ui.theme import palette

# Single desktop-friendly font family for the whole application.
FONT_FAMILY = "'Segoe UI', 'Tahoma', sans-serif"

# Compact control metrics (px) shared across screens.
CONTROL_HEIGHT = 24
ROW_HEIGHT = 22
HEADER_HEIGHT = 24


# ── Label styles ──────────────────────────────────────────────────────

def label_style(*, dim: bool = False, bold: bool = False, size: int = 9,
                danger: bool = False, success: bool = False) -> str:
    p = palette()
    if danger:
        color = p["danger"]
    elif success:
        color = p["success"]
    elif dim:
        color = p["text_dim"]
    else:
        color = p["text"]
    weight = "font-weight: bold;" if bold else ""
    return (
        f"color: {color}; font-size: {size}pt; {weight}"
        f"font-family: {FONT_FAMILY}; background: transparent;"
    )


def title_style(size: int = 14) -> str:
    """Page-title style (large, dark, compact)."""
    p = palette()
    return (
        f"color: {p['text']}; font-size: {size}pt; font-weight: bold;"
        f"font-family: {FONT_FAMILY}; background: transparent;"
    )


def section_title_style() -> str:
    return label_style(bold=True, size=10)


# ── Input styles ──────────────────────────────────────────────────────

def edit_style() -> str:
    p = palette()
    return (
        "QLineEdit {"
        f"  background-color: {p['bg']}; color: {p['text']};"
        f"  border: 1px solid {p['border']}; border-radius: 2px;"
        f"  padding: 2px 5px; font-size: 9pt; font-family: {FONT_FAMILY};"
        "}"
        f"QLineEdit:focus {{ border: 1px solid {p['focus']}; }}"
        f"QLineEdit:disabled {{ background-color: {p['disabled_bg']};"
        f"  color: {p['disabled_text']}; }}"
    )


def combo_style() -> str:
    p = palette()
    return (
        "QComboBox {"
        f"  background-color: {p['bg']}; color: {p['text']};"
        f"  border: 1px solid {p['border']}; border-radius: 2px;"
        f"  padding: 2px 5px; font-size: 9pt; font-family: {FONT_FAMILY};"
        "}"
        f"QComboBox:hover {{ border: 1px solid {p['focus']}; }}"
        "QComboBox::drop-down { border: none; width: 18px; }"
        "QComboBox::down-arrow { image: none; border: none; }"
        "QComboBox QAbstractItemView {"
        f"  background-color: {p['bg']}; color: {p['text']};"
        f"  border: 1px solid {p['border']};"
        f"  selection-background-color: {p['selected']};"
        f"  selection-color: {p['selected_text']};"
        f"  font-size: 9pt; font-family: {FONT_FAMILY};"
        "}"
    )


def date_style() -> str:
    p = palette()
    return (
        "QDateEdit, QTimeEdit, QDateTimeEdit {"
        f"  background-color: {p['bg']}; color: {p['text']};"
        f"  border: 1px solid {p['border']}; border-radius: 2px;"
        f"  padding: 2px 5px; font-size: 9pt; font-family: {FONT_FAMILY};"
        "}"
        f"QDateEdit:focus, QTimeEdit:focus, QDateTimeEdit:focus"
        f" {{ border: 1px solid {p['focus']}; }}"
        "QDateEdit::drop-down, QTimeEdit::drop-down,"
        "QDateTimeEdit::drop-down { border: none; width: 18px; }"
        "QDateEdit::down-arrow, QTimeEdit::down-arrow,"
        "QDateTimeEdit::down-arrow { image: none; border: none; }"
    )


def spin_style() -> str:
    p = palette()
    return (
        "QSpinBox, QDoubleSpinBox {"
        f"  background-color: {p['bg']}; color: {p['text']};"
        f"  border: 1px solid {p['border']}; border-radius: 2px;"
        f"  padding: 2px 5px; font-size: 9pt; font-family: {FONT_FAMILY};"
        "}"
        f"QSpinBox:focus, QDoubleSpinBox:focus"
        f" {{ border: 1px solid {p['focus']}; }}"
    )


def checkbox_style() -> str:
    p = palette()
    return (
        "QCheckBox, QRadioButton {"
        f"  color: {p['text']}; font-size: 9pt;"
        f"  font-family: {FONT_FAMILY}; background: transparent;"
        "}"
        "QCheckBox::indicator, QRadioButton::indicator {"
        f"  width: 13px; height: 13px; border: 1px solid {p['border']};"
        f"  background-color: {p['bg']};"
        "}"
        "QCheckBox::indicator:checked {"
        f"  background-color: {p['accent']};"
        "}"
    )


def group_box_style() -> str:
    p = palette()
    return (
        "QGroupBox {"
        f"  color: {p['text']}; font-weight: bold; font-size: 9pt;"
        f"  border: 1px solid {p['border']}; border-radius: 2px;"
        "  margin-top: 10px; padding-top: 12px;"
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
        f"  padding: 3px 12px; font-size: 9pt;"
        f"  font-family: {FONT_FAMILY}; min-height: 18px;"
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
        f"  font-size: 9pt; font-family: {FONT_FAMILY};"
        f"  selection-background-color: {p['selected']};"
        f"  selection-color: {p['selected_text']};"
        "}"
        "QTableWidget::item, QTableView::item { padding: 1px 4px; }"
        "QTableWidget::item:selected, QTableView::item:selected {"
        f"  background-color: {p['selected']};"
        f"  color: {p['selected_text']};"
        "}"
    )


def table_header_style(*, size: int = 9) -> str:
    p = palette()
    return (
        "QHeaderView::section {"
        f"  background-color: {p['table_header']}; color: {p['header_text']};"
        f"  border: none;"
        f"  border-right: 1px solid {p['border']};"
        f"  border-bottom: 1px solid {p['border']};"
        f"  padding: 3px 6px; font-weight: bold; font-size: {size}pt;"
        f"  font-family: {FONT_FAMILY};"
        "}"
        "QHeaderView::section:vertical {"
        f"  background-color: {p['surface']};"
        "}"
    )


def style_data_table(table: QTableWidget, *, stretch_columns=(),
                     resize_to_contents=(), grid: bool = True,
                     alternating: bool = False,
                     row_height: int = ROW_HEIGHT) -> QTableWidget:
    """Apply the shared grid/selection/header look to a data table."""
    table.setStyleSheet(table_style())
    table.setShowGrid(grid)
    table.setAlternatingRowColors(alternating)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSelectionMode(QAbstractItemView.SingleSelection)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(row_height)
    header = table.horizontalHeader()
    header.setStyleSheet(table_header_style())
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
        self.setFixedHeight(30)
        self.setStyleSheet(
            f"#PageHeader {{ {strip_style()} }}"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(8)

        self._title = QLabel(title)
        self._title.setStyleSheet(title_style(12))
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
        p = palette()
        self.setStyleSheet(
            f"#SummaryPanel {{ background-color: {p['surface_alt']};"
            f"  border: 1px solid {p['border']}; border-radius: 2px; }}"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(12)
        self._label = QLabel("")
        self._label.setStyleSheet(label_style(size=9))
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
        self.setStyleSheet(label_style(size=9))
        self.setWordWrap(True)

    def set_status(self, text: str, level: str = "info") -> None:
        self.setText(text)
        if level == "error":
            self.setStyleSheet(label_style(size=9, danger=True, bold=True))
        elif level == "success":
            self.setStyleSheet(label_style(size=9, success=True, bold=True))
        elif level == "warning":
            p = palette()
            self.setStyleSheet(
                f"color: {p['warning']}; font-size: 9pt; font-weight: bold;"
                f"font-family: {FONT_FAMILY}; background: transparent;"
            )
        else:
            self.setStyleSheet(label_style(size=9))


class FormSection(QFrame):
    """A titled, bordered section grouping compact form fields."""

    def __init__(self, title: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("FormSection")
        p = palette()
        self.setStyleSheet(
            f"#FormSection {{ background-color: {p['surface']};"
            f"  border: 1px solid {p['border']}; border-radius: 2px; }}"
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 5, 8, 5)
        outer.setSpacing(4)
        self._title = None
        if title:
            self._title = QLabel(title)
            self._title.setStyleSheet(label_style(bold=True, size=9))
            outer.addWidget(self._title)
        self.body = QVBoxLayout()
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(4)
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
        self.setStyleSheet(f"#FilterBar {{ {strip_style()} }}")
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(10, 5, 10, 5)
        self._layout.setSpacing(6)

    def add_field(self, label: str, widget: QWidget) -> None:
        lbl = QLabel(label)
        lbl.setStyleSheet(label_style(size=9))
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
        self.search_edit.setStyleSheet(edit_style())
        self.search_edit.setMinimumWidth(220)
        self.search_edit.setClearButtonEnabled(True)
        super().add_field("Search", self.search_edit)


# ── Small helpers used by screens ─────────────────────────────────────

def subtitle(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(label_style(dim=True))
    return label


def style_edit(widget):
    widget.setStyleSheet(edit_style())
    return widget


def style_combo(widget):
    widget.setStyleSheet(combo_style())
    return widget


def style_date(widget):
    widget.setStyleSheet(date_style())
    return widget


def style_label(widget, *, dim: bool = False, bold: bool = False, size: int = 9):
    widget.setStyleSheet(label_style(dim=dim, bold=bold, size=size))
    return widget


def polish_page(root: QWidget) -> QWidget:
    """Apply the shared compact data-table treatment to a whole page.

    Called centrally by the main window for every page so tables look
    identical everywhere (visible grid, compact rows, row selection)
    without each screen duplicating the setup.
    """
    for table in root.findChildren(QTableWidget):
        table.setShowGrid(True)
        table.setWordWrap(False)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
        header = table.horizontalHeader()
        if header.height() <= 0:
            header.setFixedHeight(HEADER_HEIGHT)
        header.setHighlightSections(False)
    for header_view in root.findChildren(QHeaderView):
        if not header_view.styleSheet():
            header_view.setStyleSheet(table_header_style())
    return root


__all__ = [
    "FONT_FAMILY", "CONTROL_HEIGHT", "ROW_HEIGHT", "HEADER_HEIGHT",
    "ActionButton", "PageHeader", "SummaryPanel", "StatusLabel",
    "FormSection", "FilterBar", "SearchBar",
    "label_style", "title_style", "section_title_style", "edit_style",
    "combo_style", "date_style", "spin_style", "checkbox_style",
    "group_box_style", "btn_primary_style", "btn_secondary_style",
    "btn_success_style", "btn_danger_style", "btn_warning_style",
    "style_button", "table_style", "table_header_style",
    "style_data_table", "panel_style", "strip_style", "subtitle",
    "style_edit", "style_combo", "style_date", "style_label",
    "polish_page",
]
