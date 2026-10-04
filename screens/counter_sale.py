from __future__ import annotations

import math
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from PySide6.QtCore import (
    QEvent,
    QModelIndex,
    QPoint,
    QRect,
    QSize,
    QTimer,
    Qt,
    Signal,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QCompleter,
    QDateEdit,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtGui import QFont, QFontMetrics, QStandardItem, QStandardItemModel

from database.customer_dao import CustomerDAO
from database.connection import get_connection
from database.doctor_dao import DoctorDAO
from database.item_dao import ItemDAO
from database.sales_dao import SalesDAO
from database.draft_stock import available_quantity, reserved_quantity
from database import auth
from database import financial_year
from database.document_printing import (DocumentPrintError, a6_profile,
                                        generate_counter_sale_bill,
                                        print_pharmacy_a6_bill)
from database.hold_bill_dao import (
    create_hold,
    ensure_hold_tables,
    get_hold_items,
    update_status,
    STATUS_ACTIVE,
    STATUS_RESUMED,
)

from ui.theme import palette
from ui.components import FONT_FAMILY
_p = palette()
_DARK_BG = _p["bg"]
_SURFACE = _p["surface"]
_BORDER = _p["border"]
_ACCENT = _p["accent"]
_ACCENT_HOVER = _p["accent_hover"]
_TEXT = _p["text"]
_TEXT_DIM = _p["text_dim"]
_SELECTED = _p["selected"]
_SELECTED_TEXT = _p["selected_text"]
_ERROR = "#c0392b"
_WARNING = "#b26a00"
_POPUP_BG = "#ffffff"
_POPUP_TEXT = "#14212e"
_POPUP_BORDER = "#9db6cc"
_POPUP_SELECTED = "#cfe2f3"

_COMBO_STYLE = (
    f"QComboBox {{"
    f"  background-color: {_SURFACE}; color: {_TEXT};"
    f"  border: 1px solid {_BORDER}; border-radius: 2px;"
    f"  padding: 4px 6px; font-size: 11px; font-family: {FONT_FAMILY};"
    f"}}"
    f"QComboBox:hover {{ border: 1px solid {_ACCENT}; }}"
    f"QComboBox::drop-down {{ border: none; width: 22px; }}"
    f"QComboBox::down-arrow {{ image: none; border: none; }}"
    f"QComboBox QAbstractItemView {{"
    f"  background-color: {_POPUP_BG}; color: {_POPUP_TEXT};"
    f"  border: 1px solid {_POPUP_BORDER}; selection-background-color: {_POPUP_SELECTED};"
    f"  selection-color: {_POPUP_TEXT}; outline: 0;"
    f"  font-size: 11px; font-family: {FONT_FAMILY};"
    f"}}"
    f"QComboBox QAbstractItemView::item {{ min-height: 26px; padding: 2px 6px; }}"
    f"QComboBox QAbstractItemView::item:selected {{"
    f"  background-color: {_POPUP_SELECTED}; color: {_POPUP_TEXT};"
    f"}}"
)

_ENTRY_COMBO_STYLE = _COMBO_STYLE + (
    f"QComboBox QAbstractItemView {{"
    f"  background-color: {_POPUP_BG}; color: {_POPUP_TEXT};"
    f"  border: 1px solid {_POPUP_BORDER};"
    f"  selection-background-color: {_POPUP_SELECTED};"
    f"  selection-color: {_POPUP_TEXT}; outline: 0;"
    f"  font-size: 11px; font-family: {FONT_FAMILY};"
    f"}}"
)

_EDIT_STYLE = (
    f"QLineEdit {{"
    f"  background-color: {_SURFACE}; color: {_TEXT};"
    f"  border: 1px solid {_BORDER}; border-radius: 2px;"
    f"  padding: 4px 6px; font-size: 11px; font-family: {FONT_FAMILY};"
    f"}}"
    f"QLineEdit:focus {{ border: 1px solid {_ACCENT}; }}"
)

_DATE_STYLE = (
    f"QDateEdit {{"
    f"  background-color: {_SURFACE}; color: {_TEXT};"
    f"  border: 1px solid {_BORDER}; border-radius: 2px;"
    f"  padding: 4px 6px; font-size: 11px; font-family: {FONT_FAMILY};"
    f"}}"
    f"QDateEdit:focus {{ border: 1px solid {_ACCENT}; }}"
    f"QDateEdit::drop-down {{ border: none; width: 22px; }}"
    f"QDateEdit::down-arrow {{ image: none; border: none; }}"
)

# â”€â”€ Compact controls for the bottom billing block â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# The Sale Header strip and the totals/action footer live in a fixed
# ~100 px area, so their controls use 2 px vertical padding instead of the
# 4 px used by the entry bar.  Same fonts, same colours, same border: only
# the box is shorter so two metadata rows and a label/value stack both fit
# without clipping.
_COMPACT_PADDING = "2px 5px"

_COMPACT_EDIT_STYLE = (
    f"QLineEdit {{"
    f"  background-color: {_SURFACE}; color: {_TEXT};"
    f"  border: 1px solid {_BORDER}; border-radius: 2px;"
    f"  padding: {_COMPACT_PADDING}; font-size: 11px; font-family: {FONT_FAMILY};"
    f"}}"
    f"QLineEdit:focus {{ border: 1px solid {_ACCENT}; }}"
)

_COMPACT_COMBO_STYLE = (
    f"QComboBox {{"
    f"  background-color: {_SURFACE}; color: {_TEXT};"
    f"  border: 1px solid {_BORDER}; border-radius: 2px;"
    f"  padding: {_COMPACT_PADDING}; font-size: 11px; font-family: {FONT_FAMILY};"
    f"}}"
    f"QComboBox:hover {{ border: 1px solid {_ACCENT}; }}"
    f"QComboBox::drop-down {{ border: none; width: 18px; }}"
    f"QComboBox::down-arrow {{ image: none; border: none; }}"
    f"QComboBox QAbstractItemView {{"
    f"  background-color: {_POPUP_BG}; color: {_POPUP_TEXT};"
    f"  border: 1px solid {_POPUP_BORDER}; selection-background-color: {_POPUP_SELECTED};"
    f"  selection-color: {_POPUP_TEXT}; outline: 0;"
    f"  font-size: 11px; font-family: {FONT_FAMILY};"
    f"}}"
    f"QComboBox QAbstractItemView::item {{ min-height: 24px; padding: 2px 6px; }}"
    f"QComboBox QAbstractItemView::item:selected {{"
    f"  background-color: {_POPUP_SELECTED}; color: {_POPUP_TEXT};"
    f"}}"
)

_COMPACT_DATE_STYLE = (
    f"QDateEdit {{"
    f"  background-color: {_SURFACE}; color: {_TEXT};"
    f"  border: 1px solid {_BORDER}; border-radius: 2px;"
    f"  padding: {_COMPACT_PADDING}; font-size: 11px; font-family: {FONT_FAMILY};"
    f"}}"
    f"QDateEdit:focus {{ border: 1px solid {_ACCENT}; }}"
    f"QDateEdit::drop-down {{ border: none; width: 18px; }}"
    f"QDateEdit::down-arrow {{ image: none; border: none; }}"
)

# â”€â”€ Classic front-page buttons â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Reference look (legacy Pharma-WINNER front page): every button is a light,
# softly-rounded face with a thin coloured edge and dark bold text.  The
# button's *edge* carries its role instead of a flat coloured fill, so
# primary / hold / delete still read apart at a glance.
_BTN_FACE = _p["surface_alt"]
_BTN_FACE_HOVER = _p["selected"]
_BTN_FACE_PRESSED = _p["surface"]
_BTN_EDGE = _p["text_dim"]
_BTN_EDGE_HOVER = _p["accent"]
_BTN_FACE_DISABLED = _p["disabled_bg"]
_BTN_TEXT_DISABLED = _p["disabled_text"]
_BTN_DANGER_EDGE = _p.get("danger", _ERROR)
_BTN_WARNING_EDGE = _p.get("warning", _WARNING)


def _btn_style(
    edge: str,
    *,
    face: str | None = None,
    face_hover: str | None = None,
    face_pressed: str | None = None,
    fg: str | None = None,
    padding: str = "5px 14px",
    radius: str = "5px",
    font_size: str = "11px",
) -> str:
    """Build a classic (light face + thin edge) QPushButton stylesheet."""
    face = face or _BTN_FACE
    face_hover = face_hover or _BTN_FACE_HOVER
    face_pressed = face_pressed or _BTN_FACE_PRESSED
    return (
        "QPushButton {"
        f"  background-color: {face}; color: {fg or _TEXT};"
        f"  border: 1px solid {edge}; border-radius: {radius};"
        f"  padding: {padding}; font-weight: bold;"
        f"  font-size: {font_size}; font-family: {FONT_FAMILY};"
        "}"
        "QPushButton:hover {"
        f"  background-color: {face_hover}; border: 1px solid {edge};"
        "}"
        "QPushButton:pressed {"
        f"  background-color: {face_pressed}; border: 1px solid {edge};"
        "}"
        "QPushButton:disabled {"
        f"  background-color: {_BTN_FACE_DISABLED};"
        f"  color: {_BTN_TEXT_DISABLED}; border: 1px solid {_BTN_EDGE};"
        "}"
    )


# Primary action â€” blue edge (Save Sale, New Sale).
_BTN_SAVE = _btn_style(_p["accent"])
# Neutral action (Cancel, Edit, Print / PDF).
_BTN_SECONDARY = _btn_style(_BTN_EDGE)
# Destructive action â€” red edge (the right-panel Delete button).
_BTN_DANGER = _btn_style(_BTN_DANGER_EDGE, padding="3px 8px", radius="4px")
# Compact primary (the "+ Add" button in the entry row).
_BTN_GREEN_SM = _btn_style(_p["accent"], padding="4px 10px", radius="4px")
# Hold / pending action â€” amber edge (Hold Bill).
_BTN_ORANGE = _btn_style(_BTN_WARNING_EDGE)
# Table row action (per-row Delete inside the Bill Items "Del" column).
# A quiet red edge on the light surface: it reads as a control inside a
# table cell rather than as a standalone button competing with the row.
_BTN_ROW_ACTION = (
    "QPushButton {"
    f"  background-color: {_p['surface_alt']}; color: {_BTN_DANGER_EDGE};"
    f"  border: 1px solid {_BTN_DANGER_EDGE}; border-radius: 3px;"
    "  padding: 2px 6px; font-size: 10px; font-weight: bold;"
    f"  font-family: {FONT_FAMILY};"
    "}"
    "QPushButton:hover {"
    f"  background-color: {_p['selected']}; border: 1px solid {_BTN_DANGER_EDGE};"
    "}"
    "QPushButton:pressed {"
    f"  background-color: {_p['surface']}; border: 1px solid {_BTN_DANGER_EDGE};"
    "}"
    "QPushButton:disabled {"
    f"  background-color: {_p['disabled_bg']}; color: {_p['disabled_text']};"
    f"  border: 1px solid {_p['border']};"
    "}"
)

_LABEL_STYLE = f"color: {_TEXT}; font-size: 11px; font-family: {FONT_FAMILY}; background: transparent;"
_LABEL_DIM = f"color: {_TEXT_DIM}; font-size: 10px; font-family: {FONT_FAMILY}; background: transparent;"
_HEADER_LABEL = f"color: {_TEXT}; font-size: 11px; font-family: {FONT_FAMILY}; background: transparent; font-weight: bold;"

# â”€â”€ Item entry bar metrics â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# One compact row shared by all twelve controls.  Every control uses the
# same box height so the bar reads as a single instrument strip instead of
# a row of mismatched boxes, and the label width is measured from the real
# font (capped) so labels never reserve a wide, mostly empty box.
_ENTRY_BAR_HEIGHT = 34          # label + control box, one straight row
_ENTRY_ADD_WIDTH = 78           # compact "+ Add": inside the 70-90 px target
# Captions are sized from the real font but never reserve more than this, so
# the twelve-control row keeps its natural proportions on any platform font.
_ENTRY_LABEL_MAX_WIDTH = 26

# â”€â”€ Bottom billing block metrics â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# The Sale Header strip and the totals/action footer together form the
# fixed bottom billing section (~98 px), and both rows inside the strip use
# one shared box height so nothing is squeezed or clipped.
_METADATA_STRIP_HEIGHT = 54    # Bill No / Date / Time / Type + Customer row
_METADATA_CONTROL_HEIGHT = 22  # shared box height for every metadata control
_TOTALS_FOOTER_HEIGHT = 44     # totals + Hold / Save / Cancel
_TOTALS_CONTROL_HEIGHT = 22    # shared box height for footer totals
_ACTION_BUTTON_HEIGHT = 26     # Hold Bill / Save Sale / Cancel
_BILL_ROW_HEIGHT = 28          # Bill Items body row height
_BILL_HEADER_HEIGHT = 32       # header band is slightly taller than a row
_BILL_DELETE_WIDTH = 56        # compact Del action inside the table cell
_BILL_DELETE_HEIGHT = 22

# Bill Items columns.  Index 1 (Item Name) stretches; the rest are sized to
# their content so long item names and batch numbers cannot push the
# numeric columns off screen.
_BILL_COLUMN_WIDTHS = (34, 0, 82, 106, 150, 76, 76, 54, 84, 96, 72)
_BILL_CENTERED_COLUMNS = (0, 10)
_BILL_RIGHT_COLUMNS = (6, 7, 8, 9)

_GROUP_BOX = (
    f"QGroupBox {{"
    f"  color: {_TEXT}; font-weight: bold; font-size: 12px;"
    f"  font-family: {FONT_FAMILY};"
    f"  border: 1px solid {_BORDER}; border-radius: 2px;"
    f"  margin-top: 10px; padding-top: 14px;"
    f"}}"
    f"QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 6px; }}"
)

# Keep transient Qt widgets alive long enough for their Python wrappers to
# remain usable during tests and when a page is re-created without an explicit
# parent.  This prevents PySide from deleting the underlying C++ object while
# the Python code still holds a reference to the widget.
_LIVE_WIDGETS: list[object] = []


def _keep_alive(widget: object) -> None:
    _LIVE_WIDGETS.append(widget)


def _safe_float(text: str, default: float = 0.0) -> float:
    try:
        return float(text.strip()) if text.strip() else default
    except ValueError:
        return default


def _d(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _round2(value) -> float:
    return float(_d(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _make_edit(placeholder: str = "", width: int | None = None) -> QLineEdit:
    e = QLineEdit()
    e.setPlaceholderText(placeholder)
    e.setStyleSheet(_EDIT_STYLE)
    e.setFont(QFont("Segoe UI", 11))
    if width:
        e.setMaximumWidth(width)
    return e


def _make_compact_edit(placeholder: str = "", *,
                       height: int = _TOTALS_CONTROL_HEIGHT) -> QLineEdit:
    """Shorter-boxed line edit for the fixed bottom billing block."""
    e = QLineEdit()
    e.setPlaceholderText(placeholder)
    e.setStyleSheet(_COMPACT_EDIT_STYLE)
    e.setFont(QFont("Segoe UI", 11))
    e.setFixedHeight(height)
    return e


def _make_compact_combo() -> QComboBox:
    """Shorter-boxed combo for the fixed bottom billing block.

    Built on ``_KeyboardCombo`` so the popup styling and keyboard contract
    stay identical to the entry bar; only the box height differs.
    """
    c = _KeyboardCombo()
    c.setStyleSheet(_COMPACT_COMBO_STYLE)
    c.setFixedHeight(_METADATA_CONTROL_HEIGHT)
    c.lineEdit().setFixedHeight(_METADATA_CONTROL_HEIGHT - 2)
    _keep_alive(c)
    return c


def _make_compact_date() -> QDateEdit:
    d = QDateEdit()
    d.setCalendarPopup(True)
    d.setStyleSheet(_COMPACT_DATE_STYLE)
    d.setFixedHeight(_METADATA_CONTROL_HEIGHT)
    return d


class _KeyboardCombo(QComboBox):
    """Editable combo with a local, predictable completion keyboard contract."""

    completionAccepted = Signal()

    def __init__(self):
        super().__init__()
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCompleter(QCompleter(self.model(), self))
        completer = self.completer()
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        completer.setCompletionMode(QCompleter.PopupCompletion)
        completer.setMaxVisibleItems(10)
        completer.popup().setFocusPolicy(Qt.NoFocus)
        completer.popup().setSelectionMode(QAbstractItemView.SingleSelection)
        # QCompleter owns a separate popup; style it explicitly so it does
        # not fall back to the platform's dark palette on Windows.
        completer.popup().setStyleSheet(
            f"QAbstractItemView {{ background-color: {_POPUP_BG}; color: {_POPUP_TEXT}; "
            f"border: 1px solid {_POPUP_BORDER}; selection-background-color: {_POPUP_SELECTED}; "
            f"selection-color: {_POPUP_TEXT}; font: 11px 'Segoe UI'; outline: 0; }}"
            f"QAbstractItemView::item {{ min-height: 24px; padding: 2px 6px; }}"
            f"QAbstractItemView::item:selected {{ background-color: {_POPUP_SELECTED}; color: {_POPUP_TEXT}; }}"
        )
        self.setFocusPolicy(Qt.StrongFocus)
        self._show_all_on_click = False
        self.lineEdit().installEventFilter(self)
        # An editable QComboBox redirects keyboard focus to the combo itself
        # (the line edit's focus proxy), so a physical keyboard sends its key
        # events to *this* widget, not to the line edit.  Filtering both
        # targets keeps one predictable keyboard contract: completer keys are
        # handled by this class whether they arrive on the combo, on its line
        # edit, or on the completion popup.
        self.installEventFilter(self)
        completer.popup().installEventFilter(self)
        completer.activated[str].connect(self._on_activated)

    def set_completion_model(self, model, role=Qt.DisplayRole):
        self.completer().setModel(model)
        self.completer().setCompletionRole(role)

    def show_all_completions_on_click(self, enabled=True):
        self._show_all_on_click = enabled

    def isReadOnly(self) -> bool:
        """Read-only state of the editable text (the QLineEdit contract).

        Auto-filled entry fields are read-only line edits while the searchable
        ones are editable combos; reporting one uniform flag keeps every
        entry-bar field checkable the same way.
        """
        line_edit = self.lineEdit()
        return bool(line_edit is not None and line_edit.isReadOnly())

    def _restore_owner_activation(self) -> None:
        """Hand window activation back to the owner after the list closes.

        The completion list is its own top-level window. When it closes, some
        platforms (notably the offscreen test platform, but also a driver or a
        remote session) leave it as the active window, and focus then cannot
        move inside the page at all - so "Enter on a batch" would never reach
        Qty. Reactivating the owner restores the normal keyboard chain and is
        a no-op when the owner is already active.
        """
        owner = self.window()
        if owner is None:
            return
        active = QApplication.activeWindow()
        if active is not None and active is not owner:
            owner.activateWindow()

    def eventFilter(self, watched, event):
        popup = self.completer().popup()
        if watched is self.lineEdit() and event.type() == QEvent.MouseButtonPress:
            if self._show_all_on_click:
                QTimer.singleShot(0, self._show_completion_popup)
        elif watched is popup and event.type() == QEvent.Show:
            QTimer.singleShot(0, self._position_completion_popup)

        if event.type() != QEvent.KeyPress:
            return super().eventFilter(watched, event)

        key = event.key()
        if watched not in (self, self.lineEdit(), popup):
            return super().eventFilter(watched, event)

        if key in (Qt.Key_Down, Qt.Key_Up):
            if popup.isVisible():
                self._move_popup_selection(1 if key == Qt.Key_Down else -1)
                return True
            # Popup closed: open the list with a row already highlighted so
            # TYPE -> Down -> Enter always lands on a real entry instead of
            # being swallowed by QComboBox's own dropdown handling.
            self._open_popup_from_keyboard(key == Qt.Key_Down)
            return True

        if key in (Qt.Key_Return, Qt.Key_Enter):
            if popup.isVisible():
                self._accept_popup_selection()
                return True
            if self.currentData() is not None:
                self.completionAccepted.emit()
            # Always consumed: falling through would let QComboBox swallow
            # Enter instead of advancing the keyboard chain.
            return True

        if key == Qt.Key_Escape:
            popup.hide()
            self._restore_owner_activation()
            self.setFocus()
            return True

        if key == Qt.Key_Tab and popup.isVisible():
            if not self._accept_popup_selection():
                self.focusNextChild()
            return True

        return super().eventFilter(watched, event)

    def _completion_source_has_data(self) -> bool:
        """True when the completion source stores a role value per row.

        Placeholder rows (``-- Select --``, ``-- Select Batch --``,
        ``No products found``) store ``None`` in ``Qt.UserRole`` and are
        never selectable.  Plain choice lists (sale type) never store a role
        value, so every row of those counts as selectable.
        """
        model = self.completer().model()
        if model is None:
            return False
        for row in range(model.rowCount()):
            if model.index(row, 0).data(Qt.UserRole) is not None:
                return True
        return False

    def _selectable_index(self, start: int, step: int):
        """Walk the completion rows from ``start`` for a selectable one."""
        completer = self.completer()
        count = completer.completionCount()
        row = start
        while 0 <= row < count:
            index = completer.completionModel().index(row, 0)
            if index.data(Qt.UserRole) is not None:
                return index
            row += step
        if count and not self._completion_source_has_data():
            row = min(max(start, 0), count - 1)
            return completer.completionModel().index(row, 0)
        return QModelIndex()

    def _highlight_row(self, index) -> bool:
        if not index.isValid():
            return False
        popup = self.completer().popup()
        popup.setCurrentIndex(index)
        popup.scrollTo(index)
        return True

    def _move_popup_selection(self, step: int) -> bool:
        row = self.completer().popup().currentIndex().row()
        if row < 0:
            start = 0 if step > 0 else self.completer().completionCount() - 1
        else:
            start = row + step
        return self._highlight_row(self._selectable_index(start, step))

    def _open_popup_from_keyboard(self, from_top: bool) -> None:
        """Open the completion list from the keyboard with a row selected."""
        text = self.currentText()
        # An exact entry match would only filter the list down to itself;
        # listing every row keeps Down useful after a previous selection.
        if text and self.findText(text, Qt.MatchFixedString) >= 0:
            text = ""
        completer = self.completer()
        completer.setCompletionPrefix(text)
        if completer.completionCount() == 0:
            return
        completer.complete()
        self._position_completion_popup()
        if not completer.popup().isVisible():
            return
        start = 0 if from_top else completer.completionCount() - 1
        step = 1 if from_top else -1
        self._highlight_row(self._selectable_index(start, step))

    def _show_completion_popup(self):
        self.completer().setCompletionPrefix("")
        self.completer().complete()
        self._position_completion_popup()

    def _position_completion_popup(self):
        popup = self.completer().popup()
        if not popup.isVisible():
            return
        window = self.window()
        bounds = QRect(window.mapToGlobal(QPoint(0, 0)), window.size())
        count = max(1, self.completer().completionCount())
        row_height = max(24, popup.sizeHintForRow(0))
        height = min(row_height * min(count, 10) + 4, bounds.height())
        width = min(max(self.width(), popup.sizeHintForColumn(0) + 28), bounds.width())
        below = self.mapToGlobal(QPoint(0, self.height())).y()
        x = min(max(bounds.left(), self.mapToGlobal(QPoint(0, 0)).x()),
                bounds.right() - width + 1)
        y = min(below, bounds.bottom() - height + 1)
        y = max(bounds.top(), y)
        popup.setGeometry(x, y, width, height)

    def _accept_text(self, text: str):
        index = self.findText(text, Qt.MatchFixedString)
        if index >= 0:
            self.setCurrentIndex(index)
            return True
        return False

    def _on_activated(self, text: str):
        if self._accept_text(text):
            self.completionAccepted.emit()

    def _accept_popup_selection(self) -> bool:
        completer = self.completer()
        popup = completer.popup()
        index = popup.currentIndex()
        if index.isValid() and index.data(Qt.UserRole) is not None:
            accepted = True
        elif index.isValid() and not self._completion_source_has_data():
            # Plain choice list (sale type): rows carry no role value, so
            # the row the keyboard highlighted is the selection.
            accepted = True
        else:
            # Status rows ("-- Select --", "No products found") are shown in
            # the list but are never selectable; take the first real row.
            index = self._selectable_index(0, 1)
            accepted = index.isValid()
        if accepted:
            self._accept_text(index.data())
        popup.hide()
        self._restore_owner_activation()
        if accepted:
            self.completionAccepted.emit()
        return accepted


def _make_combo() -> QComboBox:
    c = _KeyboardCombo()
    c.setStyleSheet(_COMBO_STYLE)
    _keep_alive(c)
    return c


def _make_date() -> QDateEdit:
    d = QDateEdit()
    d.setCalendarPopup(True)
    d.setStyleSheet(_DATE_STYLE)
    return d


# ======================================================================
# Database-backed lookup fields (Sales Bill popup only)
# ======================================================================

# Cap on how many suggestions one lookup shows.  Patient names come from a
# large history table, so the list is a filtered window rather than the whole
# column â€” enough to browse, small enough to stay instant while typing.
_DB_LOOKUP_LIMIT = 60


def _patient_name_options(query: str) -> list[str]:
    """Distinct patient names already recorded in the database.

    Patient is free text on the sale, so the existing sale history is the
    real source of names.  Matching is case-insensitive and partial, so
    "ram" finds "BHRAMHAKUMARI NANDA".  Nothing is invented here.
    """
    text = (query or "").strip()
    pattern = f"%{text}%" if text else "%"
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT DISTINCT patient_name FROM sales_invoices "
            "WHERE patient_name IS NOT NULL AND TRIM(patient_name) <> '' "
            "AND patient_name COLLATE NOCASE LIKE ? "
            "ORDER BY patient_name LIMIT ?",
            (pattern, _DB_LOOKUP_LIMIT),
        ).fetchall()
    finally:
        conn.close()
    return [row[0] for row in rows]


def _address_options(query: str) -> list[str]:
    """Distinct addresses already stored against customers."""
    text = (query or "").strip()
    pattern = f"%{text}%" if text else "%"
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT DISTINCT address FROM customers "
            "WHERE address IS NOT NULL AND TRIM(address) <> '' "
            "AND address COLLATE NOCASE LIKE ? "
            "ORDER BY address LIMIT ?",
            (pattern, _DB_LOOKUP_LIMIT),
        ).fetchall()
    finally:
        conn.close()
    return [row[0] for row in rows]


class _DBLookupCombo(_KeyboardCombo):
    """Editable combo whose suggestions come from the live database.

    Behaves exactly like the existing item autocomplete: a click opens the
    list, typing filters it case-insensitively on a partial match, and
    Arrow Up / Arrow Down / Enter / Escape / Tab and mouse selection all
    work through the shared ``_KeyboardCombo`` contract.  Only the source of
    the rows differs â€” the values are queried on demand instead of held in
    memory, so a large patient history stays responsive.

    The ``text()`` / ``setText()`` / ``clear()`` trio mirrors the plain line
    edit it replaces, so the surrounding save logic is unchanged.
    """

    def __init__(self, option_provider, *, placeholder: str = "",
                 width: int | None = None):
        super().__init__()
        self._option_provider = option_provider
        self.setStyleSheet(_COMBO_STYLE)
        if placeholder:
            self.lineEdit().setPlaceholderText(placeholder)
        if width:
            # A floor, not a fixed size: the field may grow into whatever
            # space the strip has spare, so the row never shows a gap.
            self.setMinimumWidth(width)
        self.show_all_completions_on_click()
        self.lineEdit().textEdited.connect(self._on_text_edited)
        self._on_text_edited("")

    def _on_text_edited(self, text: str):
        """Re-query the database for what the user has typed so far."""
        self._reload(text)

    def _reload(self, query: str):
        """Replace the suggestion rows, keeping the typed text intact."""
        typed = self.lineEdit().text()
        try:
            options = self._option_provider(query)
        except Exception:
            # A lookup failure must never block typing in the bill.
            options = []
        self.blockSignals(True)
        try:
            QComboBox.clear(self)
            for option in options:
                self.addItem(option)
            # The completer reads the combo's own model, so a selected row
            # can always be matched back by text.
            self.set_completion_model(self.model())
            self.setEditText(typed)
        finally:
            self.blockSignals(False)

    def reload(self, query: str = ""):
        """Public refresh used when the popup opens."""
        self._reload(query)

    def text(self) -> str:
        return self.lineEdit().text()

    def setText(self, value: str):
        self.setEditText(value or "")

    def clear(self):
        """Clear the typed value only â€” the suggestion rows stay."""
        self.lineEdit().clear()


# ======================================================================
# Bill line item data class
# ======================================================================

class _BillItemRow:
    """One line item in the current bill."""

    def __init__(self, item_id: int, item_name: str, stock_batch_id: int,
                 pack_size: str, location: str, batch_no: str, expiry: str,
                 mrp: float, sale_qty: float, discount_amount: float,
                 amount: float):
        self.item_id = item_id
        self.item_name = item_name
        self.stock_batch_id = stock_batch_id
        self.pack_size = pack_size
        self.location = location
        self.batch_no = batch_no
        self.expiry = expiry
        self.mrp = mrp
        self.sale_qty = sale_qty
        self.discount_amount = discount_amount
        self.amount = amount

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "stock_batch_id": self.stock_batch_id,
            "pack_size": self.pack_size,
            "location": self.location,
            "batch_no": self.batch_no,
            "expiry": self.expiry,
            "mrp": self.mrp,
            "sale_qty": self.sale_qty,
            "discount_amount": self.discount_amount,
            "amount": self.amount,
        }


# ======================================================================
# Item Entry Bar (top of sale form)
# ======================================================================

class _ItemEntryBar(QWidget):
    """Single horizontal row for selecting item, batch and sale quantity.

    All twelve controls (CNo, Item, Batch, Pack, Loc, Exp, MRP, Avail, Qty,
    Disc, Amount, + Add) live on ONE row in that order â€” there is no second
    detail row, so the bar costs one line of vertical space instead of two.

    Kept at a fixed compact height so the active sale-entry region can never
    drift or grow when items/history rows are added.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        _keep_alive(self)
        self.setObjectName("ItemEntryBar")
        self._draft_reserved_qty = lambda _batch_id: 0.0
        # One single horizontal row â€” the target billing-bar order:
        #   CNo | Item | Batch | Pack | Loc | Exp | MRP | Avail | Qty |
        #   Disc | Amount | + Add
        #
        # There is deliberately NO second row: the auto-filled details used
        # to sit underneath and wasted a whole line of vertical space.
        self.setFixedHeight(_ENTRY_BAR_HEIGHT)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 6, 2)
        # 2 px between controls keeps the twelve boxes as one tight group;
        # each caption then carries its own 3 px right margin, which gives
        # the required 4-6 px label-to-field gap without spending layout
        # spacing on every pair.
        layout.setSpacing(2)

        # CNo (counter / current bill number â€” display only)
        layout.addWidget(self._lbl("CNo"))
        self.cno_label = QLabel("--")
        self.cno_label.setFixedWidth(34)
        self.cno_label.setAlignment(Qt.AlignCenter)
        self.cno_label.setStyleSheet(_LABEL_STYLE)
        self.cno_label.setFixedHeight(_ENTRY_BAR_HEIGHT - 8)
        layout.addWidget(self.cno_label)

        # Item â€” the widest field, capped at 300 px. The main search box, but not a
        # banner: on a 1920-wide monitor the width it does not take is shared
        # with the other fields so the bar fills evenly.
        layout.addWidget(self._lbl("Item"))
        self.item_combo = _make_combo()
        self.item_combo.setStyleSheet(_ENTRY_COMBO_STYLE)
        self._fit(self.item_combo, 150, 300)
        self.item_combo.setSizePolicy(QSizePolicy.Expanding,
                                      QSizePolicy.Fixed)
        self.item_combo.show_all_completions_on_click()
        self._item_completion_model = QStandardItemModel(self)
        self.item_combo.set_completion_model(
            self._item_completion_model, Qt.UserRole + 1
        )
        self._item_search_values: list[str] = []
        self._items_by_id: dict[int, dict] = {}
        self._has_no_match_row = False
        self.item_combo.lineEdit().textEdited.connect(
            self._on_item_search_text_changed
        )
        # Stretch weights: Item leads because it is the primary search field, but it
        # only takes a share of the spare width â€” Batch and the read-outs widen
        # too, so a wide monitor fills the bar evenly instead of turning Item
        # into a banner.  A trailing stretch keeps "+ Add" flush right once
        # every field has hit its maximum.
        layout.addWidget(self.item_combo, 3)

        # Batch â€” medium width: long batch numbers stay readable and the
        # light completion popup has room to show useful batch text.
        layout.addWidget(self._lbl("Batch"))
        self.batch_combo = _make_combo()
        self.batch_combo.setStyleSheet(_ENTRY_COMBO_STYLE)
        self._fit(self.batch_combo, 96, 200)
        self.batch_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.batch_combo.show_all_completions_on_click()
        layout.addWidget(self.batch_combo, 2)

        # Pack size (auto-filled)
        layout.addWidget(self._lbl("Pack"))
        self.pack_edit = _make_edit("")
        self.pack_edit.setFixedWidth(46)
        self.pack_edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.pack_edit.setReadOnly(True)
        layout.addWidget(self.pack_edit)

        # Location (from item master)
        layout.addWidget(self._lbl("Loc"))
        self.location_edit = _make_edit("")
        self._fit(self.location_edit, 52, 110)
        self.location_edit.setReadOnly(True)
        layout.addWidget(self.location_edit, 1)

        # Expiry (auto-filled)
        layout.addWidget(self._lbl("Exp"))
        self.expiry_edit = _make_edit("")
        self._fit(self.expiry_edit, 52, 110)
        self.expiry_edit.setAlignment(Qt.AlignCenter)
        self.expiry_edit.setReadOnly(True)
        layout.addWidget(self.expiry_edit, 1)

        # MRP (auto-filled)
        layout.addWidget(self._lbl("MRP"))
        self.mrp_edit = _make_edit("")
        self._fit(self.mrp_edit, 56, 110)
        self.mrp_edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.mrp_edit.setReadOnly(True)
        layout.addWidget(self.mrp_edit, 1)

        # Batch stock (auto-filled)
        layout.addWidget(self._lbl("Avail"))
        self.stock_edit = _make_edit("")
        self._fit(self.stock_edit, 52, 110)
        self.stock_edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.stock_edit.setReadOnly(True)
        layout.addWidget(self.stock_edit, 1)

        # Sale Qty
        layout.addWidget(self._lbl("Qty"))
        self.qty_edit = _make_edit("1")
        self.qty_edit.setFixedWidth(48)
        self.qty_edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(self.qty_edit)

        # Discount
        layout.addWidget(self._lbl("Disc"))
        self.discount_edit = _make_edit("0.00")
        self._fit(self.discount_edit, 52, 110)
        self.discount_edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(self.discount_edit, 1)

        # Calculated line amount (auto-filled)
        layout.addWidget(self._lbl("Amt"))
        self.amount_edit = _make_edit("")
        self._fit(self.amount_edit, 58, 120)
        self.amount_edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.amount_edit.setReadOnly(True)
        layout.addWidget(self.amount_edit, 1)

        # Absorb any width left over once every field hit its maximum, so
        # the Add button always stays flush against the right edge.
        layout.addStretch(1)

        # Add button â€” compact, same box height as the entry controls.
        self.add_btn = QPushButton("+ Add")
        self.add_btn.setStyleSheet(_BTN_GREEN_SM)
        self.add_btn.setFixedWidth(_ENTRY_ADD_WIDTH)
        self.add_btn.setMinimumHeight(_ENTRY_BAR_HEIGHT - 8)
        layout.addWidget(self.add_btn)

        # All entry controls share one box height, whatever the platform's
        # native control metrics turn out to be (a Windows combo renders
        # one pixel taller than a styled line edit).
        self._unify_control_heights()

        # Read-only fields must never steal the keyboard chain.
        for widget in (self.cno_label, self.pack_edit, self.location_edit,
                       self.expiry_edit, self.mrp_edit, self.stock_edit,
                       self.amount_edit):
            widget.setFocusPolicy(Qt.NoFocus)

        self.item_combo.completionAccepted.connect(self._focus_batch)
        self.batch_combo.completionAccepted.connect(self._focus_quantity)
        self.qty_edit.returnPressed.connect(self._activate_add)
        self.discount_edit.returnPressed.connect(self._activate_add)
        self._focus_order = (
            self.item_combo, self.batch_combo, self.qty_edit,
            self.discount_edit, self.add_btn,
        )
        # Tab order is declared on the combo widgets (the real focus
        # targets).  Their line edits are focus proxies and are skipped by
        # focus traversal, so naming them here would drop the batch combo
        # out of the chain entirely.
        self.setTabOrder(self.item_combo, self.batch_combo)
        self.setTabOrder(self.batch_combo, self.qty_edit)
        self.setTabOrder(self.qty_edit, self.discount_edit)
        self.setTabOrder(self.discount_edit, self.add_btn)

        # Wire signals
        self.item_combo.currentIndexChanged.connect(self._on_item_changed)
        self.batch_combo.currentIndexChanged.connect(self._on_batch_changed)
        self.qty_edit.textChanged.connect(self._refresh_amount_preview)
        self.discount_edit.textChanged.connect(self._refresh_amount_preview)
        self.pack_edit.textChanged.connect(self._refresh_amount_preview)
        self.mrp_edit.textChanged.connect(self._refresh_amount_preview)

    def _unify_control_heights(self) -> None:
        """Pin every entry-bar control to one shared box height.

        A styled ``QComboBox`` reports a different natural height from a
        styled ``QLineEdit`` on some platforms (Windows renders the combo
        one pixel taller).  Rather than hard-coding a number that would be
        wrong on another machine, take the tallest natural height the
        widgets ask for and pin them all to it, so the bar reads as a
        single straight row.
        """
        widgets = (
            self.cno_label, self.item_combo, self.batch_combo,
            self.pack_edit, self.location_edit, self.expiry_edit,
            self.mrp_edit, self.stock_edit, self.qty_edit,
            self.discount_edit, self.amount_edit, self.add_btn,
        )
        height = max(widget.sizeHint().height() for widget in widgets)
        for widget in widgets:
            widget.setFixedHeight(height)

    @staticmethod
    def _lbl(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(_LABEL_DIM)
        # A compact caption sized from the real font, so the label box hugs
        # its text (with a small pad) instead of reserving whatever the
        # default application font would demand.  Capped so a long caption
        # can never steal width from the fields it labels.
        font = QFont(FONT_FAMILY.split(",")[0].strip().strip("'"))
        font.setPixelSize(10)
        lbl.setFont(font)
        width = min(QFontMetrics(font).horizontalAdvance(text) + 3,
                    _ENTRY_LABEL_MAX_WIDTH)
        lbl.setFixedWidth(width)
        lbl.setContentsMargins(0, 0, 3, 0)
        lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        return lbl

    @staticmethod
    def _fit(widget, minimum: int, maximum: int) -> None:
        """Clamp a field into ``[minimum, maximum]``.

        Every field of the single entry row is clamped instead of left free:
        the compact read-outs can never be squeezed out of existence, nothing
        is allowed to grow past its preferred width, and only *Item* keeps an
        open maximum so it is always the widest control and the first one to
        give up space at narrow window sizes.
        """
        widget.setMinimumWidth(minimum)
        widget.setMaximumWidth(maximum)

    def load_items(self):
        self.item_combo.blockSignals(True)
        self.item_combo.clear()
        self._item_completion_model.clear()
        self._item_search_values.clear()
        self._items_by_id.clear()
        self._has_no_match_row = False
        self.item_combo.addItem("-- Select --", None)
        items = ItemDAO.get_all()
        for it in items:
            item_name = it["item_name"]
            generic_name = it.get("generic_name", "") or ""
            product_code = it.get("product_code", it.get("item_code", "")) or ""
            search_value = " ".join((item_name, generic_name, product_code)).strip()
            self.item_combo.addItem(item_name, it["id"])
            self._items_by_id[it["id"]] = it
            completion_item = QStandardItem(item_name)
            completion_item.setData(it["id"], Qt.UserRole)
            completion_item.setData(search_value, Qt.UserRole + 1)
            self._item_completion_model.appendRow(completion_item)
            self._item_search_values.append(search_value.casefold())
        self.item_combo.blockSignals(False)
        self.item_combo.setCurrentIndex(0)
        self.item_combo.lineEdit().setPlaceholderText("Search products")
        self.item_combo.lineEdit().clear()

    def _on_item_search_text_changed(self, text: str):
        query = text.strip()
        if self._has_no_match_row:
            self._item_completion_model.removeRow(
                self._item_completion_model.rowCount() - 1
            )
            self._has_no_match_row = False
        if query and not any(query.casefold() in value for value in self._item_search_values):
            status = QStandardItem("No products found")
            status.setData(None, Qt.UserRole)
            status.setData(query, Qt.UserRole + 1)
            self._item_completion_model.appendRow(status)
            self._has_no_match_row = True
        completer = self.item_combo.completer()
        completer.setCompletionPrefix(text)
        if text:
            completer.complete()

    def set_draft_reservation_provider(self, provider):
        """Set ``provider(batch_id) -> reserved quantity`` for this draft."""
        self._draft_reserved_qty = provider or (lambda _batch_id: 0.0)

    def _availability(self, batch: dict) -> tuple[float, float]:
        stock = float(batch.get("stock_qty", 0.0) or 0.0)
        reserved = max(0.0, float(self._draft_reserved_qty(batch["id"]) or 0.0))
        return reserved, max(0.0, stock - reserved)

    def _refresh_amount_preview(self):
        if self.batch_combo.currentData() is None:
            self.amount_edit.clear()
            return
        quantity = _safe_float(self.qty_edit.text())
        mrp = _safe_float(self.mrp_edit.text())
        pack_text = self.pack_edit.text().strip()
        pack_size = int(pack_text) if pack_text.isdigit() else 1
        if quantity <= 0 or pack_size <= 0 or not math.isfinite(quantity):
            self.amount_edit.clear()
            return
        discount = _safe_float(self.discount_edit.text())
        amount = _round2(quantity * mrp / pack_size - discount)
        self.amount_edit.setText(f"{amount:.2f}")

    def _on_item_changed(self, idx: int, focus_batch: bool = True):
        item_id = self.item_combo.currentData()
        self.batch_combo.blockSignals(True)
        self.batch_combo.clear()
        self.pack_edit.clear()
        self.location_edit.clear()
        self.expiry_edit.clear()
        self.mrp_edit.clear()
        self.stock_edit.clear()
        self.amount_edit.clear()
        if item_id is None:
            self.batch_combo.blockSignals(False)
            return
        item = self._items_by_id.get(item_id, {})
        self.location_edit.setText(item.get("location", "") or "")

        # Load available batches
        batches = SalesDAO.get_stock_batches_for_item(item_id)
        self.batch_combo.addItem("-- Select Batch --", None)
        for b in batches:
            exp = b.get("expiry", "")
            reserved, available = self._availability(b)
            suffix = f" | Bill: {reserved:.0f}" if reserved else ""
            label = (
                f"{b['batch_no']} | Exp: {exp} | MRP: {b.get('mrp', 0.0):.2f} "
                f"| Avail: {available:.0f}{suffix}"
            )
            self.batch_combo.addItem(label, b["id"])
        self.batch_combo.blockSignals(False)
        if item_id is not None and focus_batch:
            QTimer.singleShot(0, self._focus_batch)

    def _focus_batch(self):
        self.batch_combo.lineEdit().setFocus()
        if self.batch_combo.count() > 2:
            self.batch_combo._show_completion_popup()

    def _focus_quantity(self):
        self.qty_edit.selectAll()
        QTimer.singleShot(0, self.qty_edit.setFocus)

    def _activate_add(self):
        self.add_btn.click()

    def _on_batch_changed(self, idx: int):
        batch_id = self.batch_combo.currentData()
        if batch_id is None:
            self.pack_edit.clear()
            self.expiry_edit.clear()
            self.mrp_edit.clear()
            self.stock_edit.clear()
            return
        batch = SalesDAO.get_batch_by_id(batch_id)
        if batch:
            self.pack_edit.setText(batch.get("pack_size", ""))
            item = self._items_by_id.get(self.item_combo.currentData(), {})
            self.location_edit.setText(
                batch.get("location") or item.get("location", "") or ""
            )
            self.expiry_edit.setText(batch.get("expiry", ""))
            self.mrp_edit.setText(f"{batch.get('mrp', 0.0):.2f}")
            reserved, available = self._availability(batch)
            self.stock_edit.setText(f"{available:.0f}")
            self.stock_edit.setToolTip(
                f"Stored: {batch.get('stock_qty', 0.0):.0f} | "
                f"In bill: {reserved:.0f} | Available: {available:.0f}"
            )

    def refresh_draft_availability(self):
        """Refresh selected batch details and batch-popup labels after a draft change."""
        item_id = self.item_combo.currentData()
        batch_id = self.batch_combo.currentData()
        if item_id is None:
            return
        self._on_item_changed(self.item_combo.currentIndex(), focus_batch=False)
        idx = self.batch_combo.findData(batch_id)
        if idx >= 0:
            self.batch_combo.setCurrentIndex(idx)

    def clear(self):
        self.item_combo.setCurrentIndex(0)
        self.item_combo.lineEdit().clear()
        self.batch_combo.clear()
        self.pack_edit.clear()
        self.location_edit.clear()
        self.expiry_edit.clear()
        self.mrp_edit.clear()
        self.stock_edit.clear()
        self.amount_edit.clear()
        self.qty_edit.setText("1")
        self.discount_edit.setText("0.00")

    def set_cno(self, text: str):
        """Display the current counter/bill number (no logic attached).

        The compact CNo box is deliberately narrower than the bill number, so
        the full value is kept in a tooltip.
        """
        value = text or "--"
        self.cno_label.setText(value)
        self.cno_label.setToolTip(value)

    def get_current_data(self) -> dict | None:
        item_index = self.item_combo.currentIndex()
        item_id = self.item_combo.currentData()
        if (item_id is None or item_index < 0 or
                self.item_combo.currentText() != self.item_combo.itemText(item_index)):
            return None
        batch_index = self.batch_combo.currentIndex()
        batch_id = self.batch_combo.currentData()
        if (batch_id is None or batch_index < 0 or
                self.batch_combo.currentText() != self.batch_combo.itemText(batch_index)):
            return None
        batch = SalesDAO.get_batch_by_id(batch_id)
        if not batch:
            return None
        return {
            "item_id": item_id,
            "item_name": self.item_combo.currentText(),
            "stock_batch_id": batch_id,
            "pack_size": batch.get("pack_size", ""),
            "location": batch.get("location") or self.location_edit.text(),
            "batch_no": batch["batch_no"],
            "expiry": batch.get("expiry", ""),
            "mrp": batch.get("mrp", 0.0),
            "sale_qty": _safe_float(self.qty_edit.text(), 0.0),
            "discount_amount": _safe_float(self.discount_edit.text()),
            "batch_stock": batch.get("stock_qty", 0.0),
            "draft_qty": self._availability(batch)[0],
            "available_stock": self._availability(batch)[1],
        }


# ======================================================================
# Sale Dialog
# ======================================================================

class _SalePanel(QWidget):
    """Inline counter-sale entry panel (Regions B + C of the page layout).

    Owns the same widgets, validation and DAO calls that previously lived
    inside the modal ``_SaleDialog``.  The only change is *who hosts the
    widgets*: the Counter Sale page now embeds this panel directly under
    the history region so the active sale area is always in a fixed
    position.  No transaction logic was changed.

    Layout (top â†’ bottom):
        item entry bar  â†’  current bill table  â†’  bill/customer details
        â†’  totals + actions
    """

    saved = Signal()
    held = Signal()
    cancelled = Signal()
    totals_changed = Signal(str, str, str)  # bill_no, amount, bill_total

    def __init__(self, parent: QWidget | None = None, *,
                 invoice: dict | None = None,
                 hold_bill_data: dict | None = None,
                 popup_mode: bool = False):
        super().__init__(parent)
        _keep_alive(self)
        self._invoice = invoice
        self._hold_bill = hold_bill_data
        # Sales Bill popup layout only.  When true the sale header /
        # customer group are folded into one compact top strip so the popup
        # matches the reference arrangement; the inline Counter Sale panel
        # keeps its original footer layout untouched.
        self._popup_mode = popup_mode
        self._hold_bill_id: int | None = (
            hold_bill_data["hold"]["id"] if hold_bill_data else None
        )
        self._saved = False
        self._held = False
        # The Sales Bill review popup embeds its own panel; inside it
        # "Save Sale" is already the final step, so it commits instead of
        # opening another popup.
        self._in_review_popup = False
        # Re-entrancy / double-submit guard: a committed panel never commits
        # a second time, so a double-click cannot create two sales.
        self._commit_locked = False
        self._item_rows: list[_BillItemRow] = []
        # An edit has already deducted its original lines from stored stock.
        # Keep that quantity as an allowance while validating the draft; the
        # DAO's existing edit transaction restores old stock then applies the
        # replacement lines atomically on Save.
        self._original_batch_qty: dict[int, float] = {}
        # Contact number / address of each loaded customer, used by the
        # popup's read-only Cnt No and Address fields.
        self._customer_contacts: dict[int, str] = {}
        self._customer_addresses: dict[int, str] = {}

        self.setObjectName("SalePanel")
        self.setStyleSheet(
            f"#SalePanel {{ background-color: {_DARK_BG}; }}"
            f"#SalePanel QLabel {{ {_LABEL_STYLE} }}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        if self._popup_mode:
            # Reference arrangement for the Sales Bill popup: one compact
            # sale-header / customer strip at the top, then the existing
            # entry bar, bill table and totals below it.
            self._build_header(None)
            self._build_customer_bar(None)
            self._build_totals()
            top_strip = self._build_popup_top_strip()

        # -- Region B: active sale entry (directly below the history) --
        self._entry_bar = _ItemEntryBar()
        self._entry_bar.set_draft_reservation_provider(self._reserved_for_entry)
        self._entry_bar.load_items()
        root.addWidget(self._entry_bar)

        if self._popup_mode:
            self.apply_popup_entry_widths()

        # -- Region C: current bill table (gets the remaining space) --
        self._build_bill_table()
        root.addWidget(self._table_group, 1)

        if self._popup_mode:
            root.insertWidget(0, top_strip)
            root.addWidget(self._totals_widget)
        else:
            # Compact metadata replaces the former tall Sale Header /
            # Customer panels; the same field objects and data bindings
            # are retained.
            self._build_compact_sale_metadata()
            root.addWidget(self._metadata_strip)

            # -- Totals + actions --
            self._build_totals()
            root.addWidget(self._totals_widget)

        # Wire add button
        self._entry_bar.add_btn.clicked.connect(self._on_add_item)

        # CNo display mirrors the current bill number (display only).
        self.bill_no_edit.textChanged.connect(self._entry_bar.set_cno)
        self.bill_no_edit.textChanged.connect(self._emit_totals)

        self._set_bill_no()
        self._set_current_datetime()
        self._entry_bar.set_cno(self.bill_no_edit.text())

        if self._popup_mode:
            self._refresh_customer_info()

        if invoice:
            self._populate_invoice(invoice)
        elif hold_bill_data:
            self._populate_hold_bill(hold_bill_data)

    # ------------------------------------------------------------------
    # Inline lifecycle helpers (reset / load)
    # ------------------------------------------------------------------

    def reset_for_new(self):
        """Reset the form for a brand-new sale (New Sale / after a save)."""
        self._invoice = None
        self._hold_bill = None
        self._hold_bill_id = None
        self._saved = False
        self._held = False
        self._commit_locked = False
        self._item_rows.clear()
        self._original_batch_qty.clear()
        self._refresh_table()
        self._set_bill_no()
        self._set_current_datetime()
        if self.sale_type_combo.count():
            self.sale_type_combo.setCurrentIndex(0)
        for index in range(self.customer_combo.count()):
            if self.customer_combo.itemText(index).upper() == "WALKIN":
                self.customer_combo.setCurrentIndex(index)
                break
        self.patient_name_edit.clear()
        if self.doctor_combo.count():
            self.doctor_combo.setCurrentIndex(0)
        self.bill_disc_edit.setText("0.00")
        self.paid_edit.setText("0.00")
        self._entry_bar.load_items()
        self._entry_bar.clear()
        self._recalc_totals()
        self._entry_bar.set_cno(self.bill_no_edit.text())

    def load_invoice(self, invoice: dict):
        """Load an existing sale into the inline area for editing."""
        self.reset_for_new()
        self._invoice = invoice
        self._populate_invoice(invoice)

    def load_hold(self, hold_bill_data: dict):
        """Load a held bill into the inline area for resume."""
        self.reset_for_new()
        self._hold_bill = hold_bill_data
        self._hold_bill_id = (
            hold_bill_data["hold"]["id"] if hold_bill_data else None
        )
        self._populate_hold_bill(hold_bill_data)

    def focus_item_name(self):
        """Put the keyboard focus on the Item Name entry."""
        self._entry_bar.item_combo.lineEdit().setFocus()

    # ------------------------------------------------------------------
    # Live draft stock (display/validation only; never writes stock)
    # ------------------------------------------------------------------

    def _draft_qty_for_batch(self, batch_id: int) -> float:
        return sum(r.sale_qty for r in self._item_rows if r.stock_batch_id == batch_id)

    def _reserved_for_entry(self, batch_id: int) -> float:
        """Quantity reserved by this unsaved draft for a batch.

        Existing invoice lines are excluded up to their original quantity:
        their stock will be restored by the established edit workflow before
        the replacement rows are applied on Save.
        """
        return reserved_quantity(
            self._draft_qty_for_batch(batch_id),
            self._original_batch_qty.get(batch_id, 0.0),
        )

    def _available_for_batch(self, batch_id: int, stored_stock: float) -> float:
        return available_quantity(stored_stock, self._draft_qty_for_batch(batch_id),
                                  self._original_batch_qty.get(batch_id, 0.0))

    def _refresh_draft_availability(self):
        self._entry_bar.refresh_draft_availability()

    # ------------------------------------------------------------------
    # Header
    # ------------------------------------------------------------------

    def _build_header(self, parent_layout):
        grp = QGroupBox("Sale Header")
        grp.setStyleSheet(_GROUP_BOX)
        grp.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        grp.setFixedHeight(54)
        grid = QGridLayout(grp)
        grid.setSpacing(4)
        grid.setContentsMargins(8, 14, 8, 4)

        row = 0
        grid.addWidget(self._lbl("Bill No"), row, 0)
        self.bill_no_edit = _make_edit()
        self.bill_no_edit.setReadOnly(True)
        grid.addWidget(self.bill_no_edit, row, 1)

        grid.addWidget(self._lbl("Date"), row, 2)
        self.sale_date = _make_date()
        self.sale_date.setMaximumWidth(130)
        grid.addWidget(self.sale_date, row, 3)

        grid.addWidget(self._lbl("Time"), row, 4)
        self.sale_time_edit = _make_edit()
        self.sale_time_edit.setMaximumWidth(80)
        grid.addWidget(self.sale_time_edit, row, 5)

        grid.addWidget(self._lbl("Type"), row, 6)
        self.sale_type_combo = _make_combo()
        self.sale_type_combo.addItems(["Cash", "Credit", "Credit Card"])
        self.sale_type_combo.setMaximumWidth(110)
        grid.addWidget(self.sale_type_combo, row, 7)

        # A None parent layout builds the widgets without showing the group
        # box: the Sales Bill popup places these same widgets in its own top
        # strip instead of repeating the section at the bottom.
        if parent_layout is not None:
            parent_layout.addWidget(grp)
        else:
            # Popup mode: the group box is not shown, but it owns the Bill
            # No / Date / Time widgets, so it must stay referenced.
            self._sale_header_group = grp

    def _build_customer_bar(self, parent_layout):
        grp = QGroupBox("Customer / Doctor")
        grp.setStyleSheet(_GROUP_BOX)
        grp.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        grp.setFixedHeight(54)
        grid = QGridLayout(grp)
        grid.setSpacing(4)
        grid.setContentsMargins(8, 14, 8, 4)

        row = 0
        grid.addWidget(self._lbl("Customer *"), row, 0)
        self.customer_combo = _make_combo()
        self.customer_combo.setMinimumWidth(200)
        grid.addWidget(self.customer_combo, row, 1)

        grid.addWidget(self._lbl("Patient Name"), row, 2)
        self.patient_name_edit = _make_edit()
        grid.addWidget(self.patient_name_edit, row, 3)

        grid.addWidget(self._lbl("Doctor"), row, 4)
        self.doctor_combo = _make_combo()
        self.doctor_combo.setMinimumWidth(160)
        grid.addWidget(self.doctor_combo, row, 5)

        if parent_layout is not None:
            parent_layout.addWidget(grp)
        else:
            # Popup mode: Customer / Patient / Doctor are re-parented into
            # the top strip, so the hidden box only needs to stay alive.
            self._customer_group = grp
        self._load_customers()
        self._load_doctors()


    def _build_popup_top_strip(self) -> QWidget:
        """Top sale-header strip of the Sales Bill popup.

        Left column   Cnt No / Type
        Centre column Customer / Patient / Address
        Right column  Doctor / Discount / Paid Amount

        Every control here is the panel's own existing widget â€” the sale type,
        customer and doctor inputs plus the bill-discount and paid boxes
        created for the totals row.  Patient and Address are database-backed
        lookups here, and Cnt No is a read-only mirror of customer master
        data.

        Widths are set per the field minimums the popup needs: nothing is
        squeezed, so no label or value can overlap its neighbour.
        """
        strip = QWidget()
        strip.setObjectName("SalesBillTopStrip")
        strip.setStyleSheet(
            f"#SalesBillTopStrip {{ background-color: {_SURFACE};"
            f"  border-bottom: 1px solid {_BORDER}; }}"
        )
        strip.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        # Discount and Paid Amount are the panel's own bill-discount / paid
        # boxes.  In the popup they are built here instead of in the totals
        # row, so each widget exists exactly once.
        self.bill_disc_edit = _make_edit("0.00")
        self.paid_edit = _make_edit("0.00")

        outer = QHBoxLayout(strip)
        outer.setContentsMargins(8, 4, 8, 4)
        outer.setSpacing(10)

        # -- LEFT: Cnt No / Type --
        left = QGridLayout()
        left.setHorizontalSpacing(4)
        left.setVerticalSpacing(2)
        left.addWidget(self._lbl("Cnt No"), 0, 0)
        self.cnt_no_edit = _make_edit()
        self.cnt_no_edit.setReadOnly(True)
        _ItemEntryBar._fit(self.cnt_no_edit, 55, 90)
        left.addWidget(self.cnt_no_edit, 0, 1)
        left.addWidget(self._lbl("Type"), 1, 0)
        self.sale_type_combo.setMinimumWidth(110)
        left.addWidget(self.sale_type_combo, 1, 1)
        outer.addLayout(left)

        # -- CENTRE: Customer / Patient / Address --
        centre = QGridLayout()
        centre.setHorizontalSpacing(4)
        centre.setVerticalSpacing(2)
        centre.addWidget(self._lbl("Customer *"), 0, 0)
        self.customer_combo.setMinimumWidth(200)
        centre.addWidget(self.customer_combo, 0, 1)
        centre.addWidget(self._lbl("Patient Name"), 1, 0)

        # Patient becomes a searchable database field in the popup only.
        # The plain line edit it replaces stays alive but is unused; the
        # save logic keeps reading patient_name_edit either way.
        plain_patient = self.patient_name_edit
        patient = _DBLookupCombo(
            _patient_name_options, placeholder="Search patient name", width=260,
        )
        self.patient_name_edit = patient
        plain_patient.setParent(None)
        plain_patient.deleteLater()
        centre.addWidget(patient, 1, 1)

        centre.addWidget(self._lbl("Address"), 2, 0)
        # Address offers the addresses already on file, and still mirrors the
        # selected customer's own address.
        self.address_edit = _DBLookupCombo(
            _address_options, placeholder="Search saved address", width=300,
        )
        centre.addWidget(self.address_edit, 2, 1)
        centre.setColumnStretch(1, 1)
        # Centre and right share the strip's spare width between them, so the
        # Doctor column sits next to the address field instead of being pushed
        # across an empty gap.  Each field can grow into its share, which is
        # what keeps the spare space from appearing as a hole in the row.
        outer.addLayout(centre, 1)

        # -- RIGHT: Doctor / Discount / Paid Amount --
        right = QGridLayout()
        right.setHorizontalSpacing(4)
        right.setVerticalSpacing(2)
        right.addWidget(self._lbl("Doctor"), 0, 0)
        self._make_doctor_lookup()
        self.doctor_combo.setMinimumWidth(190)
        right.addWidget(self.doctor_combo, 0, 1)
        right.addWidget(self._lbl("Discount"), 1, 0)
        self.bill_disc_edit.setMinimumWidth(100)
        right.addWidget(self.bill_disc_edit, 1, 1)
        right.addWidget(self._lbl("Paid Amount"), 2, 0)
        self.paid_edit.setMinimumWidth(100)
        right.addWidget(self.paid_edit, 2, 1)
        right.setColumnStretch(1, 1)
        outer.addLayout(right, 1)

        # Discount / Paid recalculate through the same wiring as the panel.
        self.bill_disc_edit.textChanged.connect(self._recalc_totals)
        self.paid_edit.textChanged.connect(self._recalc_totals)

        # Cnt No / Address follow the selected customer.
        self.customer_combo.currentIndexChanged.connect(self._refresh_customer_info)

        return strip

    def apply_popup_entry_widths(self, available_width: int | None = None):
        """Size the popup's single Item Entry row so nothing overlaps.

        The row keeps its existing order, widgets, labels and behaviour â€”
        CNo, Item, Batch, Pack, Loc, Exp, MRP, Avail, Qty, Disc, Amt, + Add.
        Twelve fields plus their labels are simply wider than the popup, so
        instead of fixed guesses this measures what the row's labels, gaps
        and margins already consume and shares the rest across the fields in
        proportion to their comfortable sizes.  The sum is forced to the
        remaining space, so the row always lands on exactly one line with
        every field clear of its neighbour.

        Sizing stays inside Qt's layout system (minimum == maximum width on
        each field); no widget is positioned by coordinates.

        The Counter Sale screen is untouched: it keeps the entry bar's own
        widths because this runs only in popup mode.
        """
        bar = self._entry_bar
        layout = bar.layout()
        if available_width is None:
            available_width = bar.width()

        # What the row spends before any field: every label, every gap and
        # the bar's own margins.
        spent = (layout.spacing() * max(layout.count() - 1, 0)
                 + layout.contentsMargins().left()
                 + layout.contentsMargins().right())
        captions = 0
        for index in range(layout.count()):
            item = layout.itemAt(index)
            widget = item.widget()
            if widget is bar.cno_label:
                # This label mirrors the whole bill number, so its sizeHint is
                # far wider than the slot it is given below.  Charge the slot,
                # not the text.
                spent += _POPUP_CNO_WIDTH
            elif isinstance(widget, QLabel):
                spent += widget.sizeHint().width()
                captions += 1

        # Comfortable size per field: (attribute, preferred width).
        preferred = (
            # (attribute, comfortable width, smallest usable width)
            ("item_combo", 280, 120),
            ("batch_combo", 150, 80),
            ("pack_edit", 70, 34),
            ("location_edit", 90, 40),
            ("expiry_edit", 105, 48),
            ("mrp_edit", 95, 44),
            ("stock_edit", 90, 40),
            ("qty_edit", 75, 34),
            ("discount_edit", 90, 40),
            ("amount_edit", 110, 50),
            ("add_btn", 85, 60),
        )
        total_preferred = sum(width for _, width, _floor in preferred)
        # Captions are pinned to their own text width below, so everything the
        # row has not already spent on labels and gaps belongs to the fields.
        room = max(0, available_width - spent)

        # Search fields and the Add button are the ones a user actually types
        # into or reads at length, so they are guaranteed a comfortable width
        # first; the compact read-outs share what is left.
        floors = {"item_combo": 200, "batch_combo": 100, "add_btn": 64}
        if room >= sum(floors.values()):
            widths = dict(floors)
            shared = room - sum(floors.values())
            weights = [(a, w) for a, w, _f in preferred if a not in floors]
            weight_total = sum(w for _, w in weights)
            for attribute, weight in weights:
                widths[attribute] = shared * weight // weight_total
            widths["item_combo"] += shared - sum(
                v for a, v in widths.items() if a not in floors
            )
        else:
            # Not even the comfortable widths fit: share everything evenly.
            widths = {a: room * w // total_preferred for a, w, _f in preferred}
        # Give the rounding remainder to the Item field so the row consumes
        # exactly the space that was measured.
        widths["item_combo"] += room - sum(widths.values())

        for attribute, comfortable, floor in preferred:
            widget = getattr(bar, attribute)
            width = widths[attribute]
            _ItemEntryBar._fit(widget, width, width)

        # CNo mirrors the bill number in its own narrow label, kept wide
        # enough for the number and narrow enough to stay out of Item's way.
        bar.cno_label.setMinimumWidth(_POPUP_CNO_WIDTH)
        bar.cno_label.setMaximumWidth(_POPUP_CNO_WIDTH)
        self._pin_popup_entry_captions()
        self._fit_popup_entry_row_to_width(available_width, preferred)

    def _fit_popup_entry_row_to_width(self, available_width: int,
                                      preferred) -> None:
        """Trim the Item field if the row still does not fit the window.

        The widths above are computed from measured label and gap sizes, but
        Qt's own rounding can leave the row a pixel or two long.  Rather than
        let a caption or a field be squeezed, the Item field â€” which has the
        most room to give â€” absorbs the difference, never dropping below its
        usable minimum.
        """
        bar = self._entry_bar
        layout = bar.layout()

        def required_width() -> int:
            total = (layout.spacing() * max(layout.count() - 1, 0)
                     + layout.contentsMargins().left()
                     + layout.contentsMargins().right())
            for index in range(layout.count()):
                widget = layout.itemAt(index).widget()
                if widget is None:
                    continue
                if widget is bar.cno_label:
                    total += _POPUP_CNO_WIDTH
                elif isinstance(widget, QLabel):
                    total += widget.maximumWidth()
                else:
                    total += widget.maximumWidth()
            return total

        overflow = required_width() - available_width
        item = bar.item_combo
        floor = {attribute: smallest
                for attribute, _comfortable, smallest in preferred}["item_combo"]
        if overflow > 0:
            width = max(floor, item.maximumWidth() - overflow)
            _ItemEntryBar._fit(item, width, width)

    def _pin_popup_entry_captions(self):
        """Stop the row's captions being squeezed by the fields.

        Each caption is held at exactly the width its own text needs, which
        is what keeps a label from being clipped once the fields beside it
        have taken their share of the window.
        """
        bar = self._entry_bar
        for index in range(bar.layout().count()):
            widget = bar.layout().itemAt(index).widget()
            if isinstance(widget, QLabel) and widget is not bar.cno_label:
                width = widget.sizeHint().width()
                widget.setMinimumWidth(width)
                widget.setMaximumWidth(width)


    def _make_doctor_lookup(self):
        """Doctor becomes a click-to-open database dropdown in the popup.

        The rows stay exactly the doctors loaded from the ``doctors`` table
        (same ids, same order, ``-- None --`` placeholder first).  The popup
        only appends the specialty the table already stores, so the list is
        readable at a glance, and enables the same click-to-open list the
        item and batch fields use.  Selection keeps storing ``doctor_id``, so
        the saved bill is unchanged.
        """
        self.doctor_combo.show_all_completions_on_click(True)
        for row, doctor in enumerate(DoctorDAO.get_all()):
            specialty = (doctor.get("specialty") or "").strip()
            if not specialty:
                continue
            index = row + 1  # row 0 is the "-- None --" placeholder
            if index < self.doctor_combo.count():
                self.doctor_combo.setItemText(
                    index, f"{doctor['doctor_name']} - {specialty}"
                )

    def _refresh_customer_info(self, *_args):
        """Mirror the selected customer's contact number and address.

        Setting the address only replaces the text; the saved-address
        suggestions stay loaded, so the user can still pick another one.
        Patient and Doctor are never touched here.
        """
        if not hasattr(self, "cnt_no_edit"):
            return
        cid = self.customer_combo.currentData()
        self.cnt_no_edit.setText(self._customer_contacts.get(cid, ""))
        self.address_edit.setText(self._customer_addresses.get(cid, ""))

    def _remarks_text(self) -> str:
        """Bill remarks typed in the popup's Remarks box.

        Only the Sales Bill popup owns a Remarks box; everywhere else the
        stored remarks stay empty exactly as before.
        """
        box = getattr(self, "remarks_edit", None)
        return box.text().strip() if box is not None else ""


    def _build_compact_sale_metadata(self):
        """Small two-line metadata strip; no standalone Sale Header panel.

        Row 1 carries the bill identity (Bill No / Date / Time / Type) with
        balanced, content-sized widths and a trailing stretch.  Row 2 gives
        Customer / Patient / Doctor the full remaining width instead of
        forcing them through the same columns as row 1 â€” the two rows are
        independent, so neither row is squeezed by the other.
        """
        self._metadata_strip = QWidget()
        self._metadata_strip.setObjectName("CompactSaleMetadata")
        self._metadata_strip.setFixedHeight(_METADATA_STRIP_HEIGHT)
        self._metadata_strip.setStyleSheet(
            f"#CompactSaleMetadata {{ background-color: {_DARK_BG}; "
            f"border-top: 1px solid {_BORDER}; border-bottom: 1px solid {_BORDER}; }}"
        )
        outer = QVBoxLayout(self._metadata_strip)
        outer.setContentsMargins(8, 3, 8, 3)
        outer.setSpacing(2)

        # -- Row 1: bill identity ---------------------------------------
        row1 = QHBoxLayout()
        row1.setContentsMargins(0, 0, 0, 0)
        row1.setSpacing(5)

        row1.addWidget(self._compact_lbl("Bill No"))
        self.bill_no_edit = _make_compact_edit(height=_METADATA_CONTROL_HEIGHT)
        self.bill_no_edit.setReadOnly(True)
        self.bill_no_edit.setFixedWidth(112)
        self.bill_no_edit.setAlignment(Qt.AlignCenter)
        row1.addWidget(self.bill_no_edit)

        row1.addWidget(self._compact_lbl("Date"))
        self.sale_date = _make_compact_date()
        self.sale_date.setFixedWidth(112)
        row1.addWidget(self.sale_date)

        row1.addWidget(self._compact_lbl("Time"))
        self.sale_time_edit = _make_compact_edit(height=_METADATA_CONTROL_HEIGHT)
        self.sale_time_edit.setFixedWidth(70)
        self.sale_time_edit.setAlignment(Qt.AlignCenter)
        row1.addWidget(self.sale_time_edit)

        row1.addWidget(self._compact_lbl("Type"))
        self.sale_type_combo = _make_compact_combo()
        self.sale_type_combo.addItems(["Cash", "Credit", "Credit Card"])
        self.sale_type_combo.setFixedWidth(110)
        row1.addWidget(self.sale_type_combo)

        row1.addStretch(1)
        outer.addLayout(row1)

        # -- Row 2: customer / patient / doctor -------------------------
        row2 = QHBoxLayout()
        row2.setContentsMargins(0, 0, 0, 0)
        row2.setSpacing(5)

        row2.addWidget(self._compact_lbl("Customer *"))
        self.customer_combo = _make_compact_combo()
        self.customer_combo.setMinimumWidth(200)
        row2.addWidget(self.customer_combo, 3)

        row2.addWidget(self._compact_lbl("Patient"))
        self.patient_name_edit = _make_compact_edit(height=_METADATA_CONTROL_HEIGHT)
        self.patient_name_edit.setMinimumWidth(150)
        row2.addWidget(self.patient_name_edit, 3)

        row2.addWidget(self._compact_lbl("Doctor"))
        self.doctor_combo = _make_compact_combo()
        self.doctor_combo.setMinimumWidth(160)
        row2.addWidget(self.doctor_combo, 2)

        outer.addLayout(row2)

        self._load_customers()
        self._load_doctors()

    def _load_customers(self):
        customers = CustomerDAO.get_all()
        self.customer_combo.addItem("-- Select Customer --", None)
        for c in customers:
            self.customer_combo.addItem(c["customer_name"], c["id"])
            # Kept for the popup's read-only Cnt No / Address display.  The
            # customer rows are already loaded here, so no extra query runs.
            self._customer_contacts[c["id"]] = c.get("contact_no") or ""
            self._customer_addresses[c["id"]] = c.get("address") or ""
        # Try to default to WALKIN
        for i in range(self.customer_combo.count()):
            if self.customer_combo.itemText(i).upper() == "WALKIN":
                self.customer_combo.setCurrentIndex(i)
                break

    def _load_doctors(self):
        doctors = DoctorDAO.get_all()
        self.doctor_combo.addItem("-- None --", None)
        for d in doctors:
            self.doctor_combo.addItem(d["doctor_name"], d["id"])

    def _set_bill_no(self):
        if not self._invoice:
            self.bill_no_edit.setText(SalesDAO.generate_next_bill_no())

    def _set_current_datetime(self):
        now = datetime.now()
        from PySide6.QtCore import QDate
        self.sale_date.setDate(QDate(now.year, now.month, now.day))
        self.sale_time_edit.setText(now.strftime("%H:%M"))

    # ------------------------------------------------------------------
    # Bill table
    # ------------------------------------------------------------------

    def _build_bill_table(self):
        self._table_group = QGroupBox("Bill Items")
        self._table_group.setStyleSheet(_GROUP_BOX)
        layout = QVBoxLayout(self._table_group)
        layout.setContentsMargins(6, 18, 6, 6)

        self._table = QTableWidget()
        self._table.setColumnCount(11)
        self._table.setHorizontalHeaderLabels([
            "#", "Item Name", "Pack Size", "Location", "Batch No",
            "Expiry", "MRP", "Qty", "Disc Amt", "Amount", "Del"
        ])
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(True)
        self._table.setAlternatingRowColors(False)
        self._table.verticalHeader().setDefaultSectionSize(_BILL_ROW_HEIGHT)
        self._table.horizontalHeader().setStretchLastSection(False)
        self._table.horizontalHeader().setFixedHeight(_BILL_HEADER_HEIGHT)

        # Content-based fixed widths keep the grid readable and stop a long
        # batch number or location from inflating its column: only *Item
        # Name* stretches, so it absorbs the spare width at every desktop
        # size instead of pushing the numeric columns out of view.
        hv = self._table.horizontalHeader()
        for index, width in enumerate(_BILL_COLUMN_WIDTHS):
            hv.setSectionResizeMode(index, QHeaderView.Fixed)
            hv.resizeSection(index, width)
        hv.setSectionResizeMode(1, QHeaderView.Stretch)

        for index in _BILL_CENTERED_COLUMNS:
            item = self._table.horizontalHeaderItem(index)
            item.setTextAlignment(Qt.AlignCenter)
        for index in _BILL_RIGHT_COLUMNS:
            item = self._table.horizontalHeaderItem(index)
            item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

        hv.setStyleSheet(
            f"QHeaderView::section {{"
            f"  background-color: {_SURFACE}; color: {_TEXT};"
            f"  border: none; border-bottom: 2px solid {_ACCENT};"
            f"  padding: 4px 5px; font-weight: bold; font-size: 11px;"
            f"  font-family: {FONT_FAMILY};"
            f"}}"
        )
        self._table.setStyleSheet(
            f"QTableWidget {{"
            f"  background-color: {_DARK_BG}; color: {_TEXT};"
            f"  border: 1px solid {_BORDER}; gridline-color: {_BORDER};"
            f"  font-size: 11px; font-family: {FONT_FAMILY};"
            f"  selection-background-color: {_SELECTED};"
            f"  selection-color: {_TEXT};"
            f"}}"
            f"QTableWidget::item {{ padding: 3px 6px; }}"
        )
        layout.addWidget(self._table, 1)

    def _on_add_item(self):
        data = self._entry_bar.get_current_data()
        if data is None:
            QMessageBox.warning(self, "Validation", "Please select an item and batch.")
            return

        qty_text = self._entry_bar.qty_edit.text().strip()
        if not qty_text:
            self._entry_bar.qty_edit.setFocus()
            QMessageBox.warning(self, "Validation", "Sale Quantity is required.")
            return
        try:
            sale_qty = float(qty_text)
        except (TypeError, ValueError):
            sale_qty = 0.0
        if not math.isfinite(sale_qty) or sale_qty <= 0:
            self._entry_bar.qty_edit.setFocus()
            QMessageBox.warning(
                self, "Validation", "Sale Quantity must be a valid number greater than 0."
            )
            return
        data["sale_qty"] = sale_qty

        discount_text = self._entry_bar.discount_edit.text().strip()
        try:
            discount = float(discount_text) if discount_text else 0.0
        except (TypeError, ValueError):
            discount = float("nan")
        if not math.isfinite(discount) or discount < 0:
            self._entry_bar.discount_edit.setFocus()
            QMessageBox.warning(
                self, "Validation", "Discount must be a valid non-negative amount."
            )
            return
        data["discount_amount"] = discount

        available = self._available_for_batch(
            data["stock_batch_id"], data["batch_stock"]
        )
        if sale_qty > available:
            QMessageBox.warning(
                self, "Insufficient Stock",
                f"Only {available:.0f} units are available for this batch."
            )
            return

        if SalesDAO.is_expired(data["expiry"]):
            QMessageBox.warning(
                self, "Expired Batch",
                f"Batch {data['batch_no']} (Exp: {data['expiry']}) is expired. "
                f"Cannot sell expired stock."
            )
            return

        mrp = data["mrp"]
        discount = data["discount_amount"]
        ps_str = data["pack_size"]
        pack_size_int = 1
        if ps_str and str(ps_str).strip().isdigit():
            try:
                pack_size_int = int(str(ps_str).strip())
            except (ValueError, TypeError):
                pack_size_int = 1
        if pack_size_int < 1:
            pack_size_int = 1
        unit_price = mrp / pack_size_int
        gross = _round2(sale_qty * unit_price)
        if discount > gross:
            QMessageBox.warning(self, "Validation", "Discount cannot exceed gross amount.")
            return
        amount = _round2(gross - discount)

        existing = next(
            (r for r in self._item_rows
             if r.item_id == data["item_id"] and r.stock_batch_id == data["stock_batch_id"]),
            None,
        )
        if existing is not None:
            # Same item+batch is one bill line.  The per-add discount is
            # accumulated, matching the prior line-level discount semantics.
            existing.sale_qty += sale_qty
            existing.discount_amount = _round2(existing.discount_amount + discount)
            combined_gross = _round2(existing.sale_qty * unit_price)
            existing.amount = _round2(combined_gross - existing.discount_amount)
        else:
            row = _BillItemRow(
                item_id=data["item_id"], item_name=data["item_name"],
                stock_batch_id=data["stock_batch_id"], pack_size=data["pack_size"],
                location=data["location"], batch_no=data["batch_no"],
                expiry=data["expiry"], mrp=mrp, sale_qty=sale_qty,
                discount_amount=discount, amount=amount,
            )
            self._item_rows.append(row)
        self._refresh_table()
        self._recalc_totals()
        self._refresh_draft_availability()
        self._entry_bar.clear()
        self._entry_bar.item_combo.setFocus()

    def _refresh_table(self):
        self._table.setRowCount(len(self._item_rows))
        for i, r in enumerate(self._item_rows):
            self._table.setRowHeight(i, _BILL_ROW_HEIGHT)
            index_item = QTableWidgetItem(str(i + 1))
            index_item.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
            self._table.setItem(i, 0, index_item)
            self._table.setItem(i, 1, QTableWidgetItem(r.item_name))
            self._table.setItem(i, 2, QTableWidgetItem(r.pack_size))
            self._table.setItem(i, 3, QTableWidgetItem(r.location))
            self._table.setItem(i, 4, QTableWidgetItem(r.batch_no))
            expiry_item = QTableWidgetItem(r.expiry)
            expiry_item.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
            self._table.setItem(i, 5, expiry_item)

            mrp_item = QTableWidgetItem(f"{r.mrp:.2f}")
            mrp_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._table.setItem(i, 6, mrp_item)

            qty_item = QTableWidgetItem(f"{r.sale_qty:.0f}")
            qty_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._table.setItem(i, 7, qty_item)

            disc_item = QTableWidgetItem(f"{r.discount_amount:.2f}")
            disc_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._table.setItem(i, 8, disc_item)

            amt_item = QTableWidgetItem(f"{r.amount:.2f}")
            amt_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._table.setItem(i, 9, amt_item)

            self._make_row_delete_button(i)

    def _make_row_delete_button(self, index: int) -> QPushButton:
        """Compact Delete action, centred inside the fixed-width Del column.

        The button is wrapped in a filler cell so it is centred both ways and
        never stretches to the row height â€” a small table action instead of a
        standalone control dominating the row.  Delete behaviour is unchanged.
        """
        del_btn = QPushButton("Delete")
        del_btn.setStyleSheet(_BTN_ROW_ACTION)
        del_btn.setFixedSize(_BILL_DELETE_WIDTH, _BILL_DELETE_HEIGHT)
        del_btn.setToolTip(f"Remove line {index + 1} from this bill")
        del_btn.clicked.connect(lambda _, idx=index: self._delete_item(idx))

        cell = QWidget()
        cell.setStyleSheet("background: transparent;")
        cell_layout = QHBoxLayout(cell)
        cell_layout.setContentsMargins(0, 0, 0, 0)
        cell_layout.setSpacing(0)
        cell_layout.addStretch(1)
        cell_layout.addWidget(del_btn, 0, Qt.AlignVCenter)
        cell_layout.addStretch(1)
        _keep_alive(cell)
        self._table.setCellWidget(index, 10, cell)
        # QTableView sizes an index widget from its sizeHint, so pin the
        # filler to the full cell rect to guarantee the action is centred
        # both horizontally and vertically inside the Del column.
        column = self._table.columnWidth(10)
        cell.setFixedWidth(column)
        cell.setFixedHeight(_BILL_ROW_HEIGHT)
        return cell

    def _delete_item(self, idx: int):
        if 0 <= idx < len(self._item_rows):
            self._item_rows.pop(idx)
            self._refresh_table()
            self._recalc_totals()
            self._refresh_draft_availability()

    # ------------------------------------------------------------------
    # Totals
    # ------------------------------------------------------------------

    def _build_totals(self):
        """One clean totals + actions row across the bottom of the page.

        LEFT  : Total Items, Total Amt, Customer Saving, Round Off, NET AMT
                and Paid, each with a content-sized box (Net Amt emphasised).
        RIGHT : Hold Bill (secondary), Save Sale (primary), Cancel
                (secondary), all with the same box height as the entry bar.
        """
        self._totals_widget = QWidget()
        self._totals_widget.setFixedHeight(_TOTALS_FOOTER_HEIGHT)
        self._totals_widget.setStyleSheet(
            f"background-color: {_SURFACE}; border-top: 1px solid {_BORDER};"
        )
        layout = QHBoxLayout(self._totals_widget)
        layout.setContentsMargins(12, 3, 12, 3)
        layout.setSpacing(14)

        if self._popup_mode:
            # Discount / Paid Amount live in the popup's top strip, so the
            # summary row keeps only the calculated values.  The same
            # widgets are created there - nothing is duplicated.
            self._add_total_field(layout, "Total Amt", "total_amount_label",
                                  width=96)
            self._add_total_field(layout, "Round Off", "round_off_label",
                                  width=92)
            self._add_total_field(layout, "NET AMT", "net_amt_label",
                                  width=112, emphasised=True)
            layout.addStretch()
            return

        self._add_total_field(layout, "Total Items", "total_items_label",
                              width=64, emphasised=False)
        self._add_total_field(layout, "Total Amt", "total_amount_label",
                              width=96)
        self._add_total_field(layout, "Customer Saving", "bill_disc_edit",
                              width=100)
        self._add_total_field(layout, "Round Off", "round_off_label",
                              width=92)
        self._add_total_field(layout, "NET AMT", "net_amt_label",
                              width=112, emphasised=True)
        self._add_total_field(layout, "Paid", "paid_edit", width=96)

        # Wire recalc
        self.bill_disc_edit.textChanged.connect(self._recalc_totals)
        self.paid_edit.textChanged.connect(self._recalc_totals)

        # -- Actions (one set only: the sale area owns Save/Hold/Cancel) --
        layout.addStretch()

        hold_btn = QPushButton("Hold Bill")
        hold_btn.setStyleSheet(_BTN_ORANGE)
        hold_btn.setFixedSize(96, _ACTION_BUTTON_HEIGHT)
        hold_btn.clicked.connect(self._on_hold)
        layout.addWidget(hold_btn)

        save_btn = QPushButton("Save Sale")
        save_btn.setStyleSheet(_BTN_SAVE)
        save_btn.setFixedSize(104, _ACTION_BUTTON_HEIGHT)
        save_btn.clicked.connect(self._on_save)
        layout.addWidget(save_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(_BTN_SECONDARY)
        cancel_btn.setFixedSize(86, _ACTION_BUTTON_HEIGHT)
        cancel_btn.clicked.connect(self.cancelled.emit)
        layout.addWidget(cancel_btn)

    def _add_total_field(self, layout: QHBoxLayout, title: str, attr_name: str,
                         *, width: int, emphasised: bool = False):
        """One caption-over-value block of a fixed width in the footer."""
        container = QVBoxLayout()
        container.setSpacing(0)
        container.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel(title)
        lbl.setStyleSheet(_LABEL_DIM)
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setFixedWidth(width)
        lbl.setFixedHeight(14)
        container.addWidget(lbl)

        if attr_name.endswith("_label"):
            val_lbl = QLabel("0.00")
            val_lbl.setAlignment(Qt.AlignCenter)
            val_lbl.setFixedWidth(width)
            val_lbl.setFixedHeight(_TOTALS_CONTROL_HEIGHT)
            val_lbl.setStyleSheet(
                f"color: {_ACCENT if emphasised else _TEXT};"
                f"font-size: {13 if emphasised else 12}px; font-weight: bold;"
                f"background: transparent; font-family: {FONT_FAMILY};"
            )
            container.addWidget(val_lbl)
            setattr(self, attr_name, val_lbl)
        else:
            edit = _make_compact_edit("0.00", height=_TOTALS_CONTROL_HEIGHT)
            edit.setFixedWidth(width)
            edit.setAlignment(Qt.AlignRight)
            container.addWidget(edit)
            setattr(self, attr_name, edit)
            if attr_name not in ("bill_disc_edit", "paid_edit"):
                edit.setReadOnly(True)

        layout.addLayout(container)

    def _recalc_totals(self):
        total = sum(r.amount for r in self._item_rows)
        if getattr(self, "total_items_label", None) is not None:
            self.total_items_label.setText(str(len(self._item_rows)))
        self.total_amount_label.setText(f"{total:.2f}")

        bill_disc = _safe_float(self.bill_disc_edit.text())
        net = total - bill_disc
        round_off = _round2(net) - net
        net = _round2(net + round_off)

        self.round_off_label.setText(f"{round_off:.2f}")
        self.net_amt_label.setText(f"{net:.2f}")
        self._emit_totals()

    def _emit_totals(self):
        """Publish the live bill figures for the right-side bill panel."""
        self.totals_changed.emit(
            self.bill_no_edit.text(),
            self.total_amount_label.text(),
            self.net_amt_label.text(),
        )

    # ------------------------------------------------------------------
    # Populate for edit
    # ------------------------------------------------------------------

    def _populate_invoice(self, inv: dict):
        self.bill_no_edit.setText(inv.get("bill_no", ""))

        from PySide6.QtCore import QDate
        sd = inv.get("sale_date", "")
        if sd:
            try:
                parts = sd.split("-")
                self.sale_date.setDate(QDate(int(parts[0]), int(parts[1]), int(parts[2])))
            except Exception:
                pass

        self.sale_time_edit.setText(inv.get("sale_time", ""))
        idx = self.sale_type_combo.findText(inv.get("sale_type", "Cash"))
        if idx >= 0:
            self.sale_type_combo.setCurrentIndex(idx)

        cid = inv.get("customer_id")
        if cid:
            idx = self.customer_combo.findData(cid)
            if idx >= 0:
                self.customer_combo.setCurrentIndex(idx)

        self.patient_name_edit.setText(inv.get("patient_name", ""))

        did = inv.get("doctor_id")
        if did:
            idx = self.doctor_combo.findData(did)
            if idx >= 0:
                self.doctor_combo.setCurrentIndex(idx)

        items = SalesDAO.get_invoice_items(inv["id"])
        for it in items:
            row = _BillItemRow(
                item_id=it["item_id"],
                item_name=it.get("item_name", ""),
                stock_batch_id=it["stock_batch_id"],
                pack_size=it.get("pack_size", ""),
                location=it.get("location", ""),
                batch_no=it.get("batch_no", ""),
                expiry=it.get("expiry", ""),
                mrp=it.get("mrp", 0.0),
                sale_qty=it.get("sale_qty", 0.0),
                discount_amount=it.get("discount_amount", 0.0),
                amount=it.get("amount", 0.0),
            )
            self._item_rows.append(row)
            self._original_batch_qty[row.stock_batch_id] = (
                self._original_batch_qty.get(row.stock_batch_id, 0.0) + row.sale_qty
            )
        self._refresh_table()

        self.bill_disc_edit.setText(str(inv.get("discount", 0.0)))
        self.paid_edit.setText(str(inv.get("paid_amount", 0.0)))

        self._recalc_totals()
        self._refresh_draft_availability()

    @staticmethod
    def _lbl(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(_HEADER_LABEL)
        return lbl

    @staticmethod
    def _compact_lbl(text: str) -> QLabel:
        """Small bold caption for the metadata strip.

        Measured from the real font so the caption hugs its text instead of
        reserving a wide box, and vertically centred against its field.
        """
        lbl = QLabel(text)
        lbl.setStyleSheet(_LABEL_DIM)
        font = QFont(FONT_FAMILY.split(",")[0].strip().strip("'"))
        font.setPixelSize(10)
        font.setBold(True)
        lbl.setFont(font)
        lbl.setFixedWidth(QFontMetrics(font).horizontalAdvance(text) + 4)
        lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        return lbl

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def _focus_batch_for_row(self, row: _BillItemRow):
        item_index = self._entry_bar.item_combo.findData(row.item_id)
        if item_index >= 0:
            self._entry_bar.item_combo.setCurrentIndex(item_index)
        batch_index = self._entry_bar.batch_combo.findData(row.stock_batch_id)
        if batch_index >= 0:
            self._entry_bar.batch_combo.setCurrentIndex(batch_index)
        self._entry_bar.batch_combo.lineEdit().setFocus()

    def _validate_sale_items(self) -> bool:
        batches = {}
        for row in self._item_rows:
            if row.item_id is None:
                self._entry_bar.item_combo.lineEdit().setFocus()
                QMessageBox.warning(self, "Validation", "An item is required for every bill row.")
                return False
            if row.stock_batch_id is None:
                self._entry_bar.batch_combo.lineEdit().setFocus()
                QMessageBox.warning(self, "Validation", "A batch is required for every bill row.")
                return False
            try:
                quantity = float(row.sale_qty)
            except (TypeError, ValueError):
                quantity = 0.0
            if not math.isfinite(quantity) or quantity <= 0:
                self._focus_batch_for_row(row)
                self._entry_bar.qty_edit.setFocus()
                QMessageBox.warning(
                    self, "Validation", "Sale Quantity must be a valid number greater than 0."
                )
                return False
            try:
                discount = float(row.discount_amount)
            except (TypeError, ValueError):
                discount = float("nan")
            if not math.isfinite(discount) or discount < 0 or not math.isfinite(float(row.amount)):
                self._focus_batch_for_row(row)
                self._entry_bar.discount_edit.setFocus()
                QMessageBox.warning(self, "Validation", "Bill row amounts must be valid and non-negative.")
                return False

            batch = SalesDAO.get_batch_by_id(row.stock_batch_id)
            if not batch or batch.get("item_id") != row.item_id:
                self._focus_batch_for_row(row)
                QMessageBox.warning(
                    self, "Validation", f"Batch {row.batch_no} is no longer available for this item."
                )
                return False
            if SalesDAO.is_expired(batch.get("expiry", row.expiry)):
                self._focus_batch_for_row(row)
                QMessageBox.warning(
                    self, "Expired Batch",
                    f"Batch {batch.get('batch_no', row.batch_no)} is expired and cannot be sold."
                )
                return False
            batches[row.stock_batch_id] = batch

        for batch_id, batch in batches.items():
            draft_quantity = self._draft_qty_for_batch(batch_id)
            original_quantity = self._original_batch_qty.get(batch_id, 0.0)
            stored_quantity = float(batch.get("stock_qty", 0.0) or 0.0)
            if draft_quantity > stored_quantity + original_quantity:
                available = self._available_for_batch(batch_id, stored_quantity)
                row = next(r for r in self._item_rows if r.stock_batch_id == batch_id)
                self._focus_batch_for_row(row)
                QMessageBox.warning(
                    self, "Insufficient Stock",
                    f"Only {available:.0f} units are available for this batch."
                )
                return False
        return True

    def _on_save(self):
        """Entry point for the panel's Save Sale button.

        On the Counter Sale screen this only *validates* the draft and then
        opens the Sales Bill review popup.  Inside that popup the same button
        is the final step, so it validates and commits directly.  Either way
        validation runs first and nothing is committed until it passes.
        """
        if not self._validate_for_commit():
            return
        if self._in_review_popup:
            self._commit_sale()
            return
        self._open_review_dialog()

    def _open_review_dialog(self):
        """Show the compact, centred Sales Bill review/edit popup.

        ``show()`` (not ``exec()``) is used deliberately: the popup is modal
        and application-blocking for the user, but the call returns
        immediately so the save flow stays re-entrant and testable.
        """
        dialog = SalesBillReviewDialog(self, self)
        self._review_dialog = dialog
        dialog.finished.connect(self._release_review_dialog)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        return dialog

    def _release_review_dialog(self, *_args):
        """Drop the popup handle once it is gone (Close, Escape or Save)."""
        if getattr(self, "_review_dialog", None) is not None:
            del self._review_dialog

    def _validate_for_commit(self) -> bool:
        """Every business rule that must pass before a sale may be written.

        Used by both the Counter Sale Save Sale step and the popup's final
        Save, so the review popup can never be the step that skips a rule.
        """
        try:
            financial_year.validate_transaction_date(self.sale_date.date().toString("yyyy-MM-dd"))
        except financial_year.FinancialYearError as exc:
            self.sale_date.setFocus()
            QMessageBox.warning(self, "Financial Year", str(exc))
            return False

        if not self.customer_combo.currentData():
            self.customer_combo.setFocus()
            QMessageBox.warning(self, "Validation", "Customer is required.")
            return False

        if not self.bill_no_edit.text().strip():
            self.bill_no_edit.setFocus()
            QMessageBox.warning(self, "Validation", "Bill number is required.")
            return False

        if not self._item_rows:
            self._entry_bar.item_combo.lineEdit().setFocus()
            QMessageBox.warning(self, "Validation", "At least one item is required.")
            return False

        if not self._validate_sale_items():
            return False

        sale_time = self.sale_time_edit.text().strip()
        try:
            datetime.strptime(sale_time, "%H:%M")
        except ValueError:
            self.sale_time_edit.setFocus()
            QMessageBox.warning(self, "Validation", "Enter a valid sale time in HH:MM format.")
            return False

        self._recalc_totals()

        total_amount = _round2(float(_d(sum(r.amount for r in self._item_rows))))
        bill_discount_text = self.bill_disc_edit.text().strip()
        try:
            bill_discount = float(bill_discount_text) if bill_discount_text else 0.0
        except ValueError:
            bill_discount = float("nan")
        if (not math.isfinite(bill_discount) or bill_discount < 0 or
                bill_discount > total_amount):
            self.bill_disc_edit.setFocus()
            QMessageBox.warning(
                self, "Validation",
                "Bill discount must be a valid amount between 0 and the bill total."
            )
            return False

        paid_text = self.paid_edit.text().strip()
        try:
            paid = float(paid_text) if paid_text else 0.0
        except ValueError:
            paid = float("nan")
        if not math.isfinite(paid) or paid < 0:
            self.paid_edit.setFocus()
            QMessageBox.warning(
                self, "Validation", "Paid amount must be a valid non-negative amount."
            )
            return False

        return True

    def _commit_sale(self):
        """Write the sale: one invoice, one stock deduction, one posting.

        Only reachable through the popup's final Save (or directly from a
        panel already inside that popup).  Stock and accounting are handled
        by the established SalesDAO transaction, so the review popup adds no
        accounting behaviour of its own.
        """
        if self._commit_locked:
            # Double-submit guard: a second click on Save cannot produce a
            # second invoice, deduction or posting set.
            return
        self._commit_locked = True

        try:
            self._recalc_totals()
            total_amount = _round2(float(_d(sum(r.amount for r in self._item_rows))))
            bill_discount = _safe_float(self.bill_disc_edit.text())
            paid = _safe_float(self.paid_edit.text())
            round_off = _safe_float(self.round_off_label.text())
            net_amount = _round2(total_amount - bill_discount + round_off)
            sale_date = self.sale_date.date().toString("yyyy-MM-dd")
            sale_time = self.sale_time_edit.text().strip()
            sale_type = self.sale_type_combo.currentText()
            patient_name = self.patient_name_edit.text().strip()
            cid = self.customer_combo.currentData()
            did = self.doctor_combo.currentData()
            bill_no = self.bill_no_edit.text().strip()
            remarks = self._remarks_text()
            items_data = [r.to_dict() for r in self._item_rows]

            if self._invoice:
                # Edit: update in place â€” stock is adjusted and the
                # accounting posting is reversed + re-posted atomically.
                SalesDAO.update_invoice(
                    invoice_id=self._invoice["id"],
                    bill_no=bill_no, sale_date=sale_date,
                    sale_time=sale_time, sale_type=sale_type,
                    customer_id=cid, patient_name=patient_name,
                    doctor_id=did, discount=bill_discount,
                    paid_amount=paid, total_amount=total_amount,
                    round_off=round_off, net_amount=net_amount,
                    remarks=remarks, items=items_data,
                )
            else:
                SalesDAO.insert_invoice(
                    bill_no=bill_no, sale_date=sale_date, sale_time=sale_time,
                    sale_type=sale_type, customer_id=cid,
                    patient_name=patient_name, doctor_id=did,
                    discount=bill_discount, paid_amount=paid,
                    total_amount=total_amount, round_off=round_off,
                    net_amount=net_amount, remarks=remarks,
                    items=items_data,
                )
            self._saved = True
            self.saved.emit()
        except Exception as e:
            self._commit_locked = False
            QMessageBox.critical(self, "Error", f"Failed to save sale:\n{e}")

    # ------------------------------------------------------------------
    # Draft hand-off to / from the Sales Bill review popup
    # ------------------------------------------------------------------

    def draft_state(self) -> dict:
        """Snapshot of the unsaved draft, for the review popup to edit.

        Pure copy â€” nothing is written and no stock is reserved by taking
        this snapshot, which is what keeps the popup free of side effects.
        """
        return {
            "bill_no": self.bill_no_edit.text(),
            "sale_date": self.sale_date.date(),
            "sale_time": self.sale_time_edit.text(),
            "sale_type": self.sale_type_combo.currentText(),
            "customer_id": self.customer_combo.currentData(),
            "patient_name": self.patient_name_edit.text(),
            "doctor_id": self.doctor_combo.currentData(),
            "bill_discount": self.bill_disc_edit.text(),
            "paid_amount": self.paid_edit.text(),
            "invoice": self._invoice,
            "hold_bill_id": self._hold_bill_id,
            "original_batch_qty": dict(self._original_batch_qty),
            "rows": [
                {
                    "item_id": r.item_id,
                    "item_name": r.item_name,
                    "stock_batch_id": r.stock_batch_id,
                    "pack_size": r.pack_size,
                    "location": r.location,
                    "batch_no": r.batch_no,
                    "expiry": r.expiry,
                    "mrp": r.mrp,
                    "sale_qty": r.sale_qty,
                    "discount_amount": r.discount_amount,
                    "amount": r.amount,
                }
                for r in self._item_rows
            ],
        }

    def load_draft_state(self, state: dict):
        """Adopt a draft snapshot (used by the review popup to load the bill)."""
        self._invoice = state.get("invoice")
        self._hold_bill_id = state.get("hold_bill_id")
        self.bill_no_edit.setText(state.get("bill_no", ""))

        date_value = state.get("sale_date")
        if date_value is not None:
            self.sale_date.setDate(date_value)

        self.sale_time_edit.setText(state.get("sale_time", ""))

        type_index = self.sale_type_combo.findText(state.get("sale_type", "Cash"))
        if type_index >= 0:
            self.sale_type_combo.setCurrentIndex(type_index)

        customer_index = self.customer_combo.findData(state.get("customer_id"))
        if customer_index >= 0:
            self.customer_combo.setCurrentIndex(customer_index)

        self.patient_name_edit.setText(state.get("patient_name", ""))

        doctor_index = self.doctor_combo.findData(state.get("doctor_id"))
        if doctor_index >= 0:
            self.doctor_combo.setCurrentIndex(doctor_index)

        self.bill_disc_edit.setText(state.get("bill_discount", "0.00"))
        self.paid_edit.setText(state.get("paid_amount", "0.00"))

        self._original_batch_qty = dict(state.get("original_batch_qty") or {})
        self._item_rows = [
            _BillItemRow(
                item_id=row["item_id"],
                item_name=row["item_name"],
                stock_batch_id=row["stock_batch_id"],
                pack_size=row["pack_size"],
                location=row["location"],
                batch_no=row["batch_no"],
                expiry=row["expiry"],
                mrp=row["mrp"],
                sale_qty=row["sale_qty"],
                discount_amount=row["discount_amount"],
                amount=row["amount"],
            )
            for row in state.get("rows") or []
        ]
        self._refresh_table()
        self._recalc_totals()
        self._refresh_draft_availability()
        self._entry_bar.set_cno(self.bill_no_edit.text())
        self._focus_entry_on_first_row()

    def _focus_entry_on_first_row(self):
        """Show the first bill line's item/batch in the entry bar.

        Display only: selecting in the entry bar fills the read-only Pack /
        Location / Expiry / MRP / Batch-Stock boxes and loads the batch list,
        so the entry area of a review step always shows live item data
        instead of empty controls.  It reserves nothing and writes nothing.
        """
        if not self._item_rows:
            return
        first = self._item_rows[0]
        item_index = self._entry_bar.item_combo.findData(first.item_id)
        if item_index >= 0:
            self._entry_bar.item_combo.setCurrentIndex(item_index)
        batch_index = self._entry_bar.batch_combo.findData(first.stock_batch_id)
        if batch_index >= 0:
            self._entry_bar.batch_combo.setCurrentIndex(batch_index)

    @property
    def was_saved(self) -> bool:
        return self._saved

    # ------------------------------------------------------------------
    # Hold Bill
    # ------------------------------------------------------------------

    def _on_hold(self):
        if not self._item_rows:
            QMessageBox.warning(self, "Hold Bill", "No items to hold. Add items first.")
            return

        cid = self.customer_combo.currentData()
        patient_name = self.patient_name_edit.text().strip()
        did = self.doctor_combo.currentData()

        self._recalc_totals()
        total_amount = _round2(float(_d(sum(r.amount for r in self._item_rows))))

        items_data = []
        for r in self._item_rows:
            items_data.append({
                "item_id": r.item_id,
                "item_name_snapshot": r.item_name,
                "batch_no": r.batch_no,
                "pack_size": r.pack_size,
                "location": r.location,
                "expiry": r.expiry,
                "mrp": r.mrp,
                "sale_qty": r.sale_qty,
                "discount_amount": r.discount_amount,
                "amount": r.amount,
            })

        user = auth.session.user
        created_by = user["username"] if user else ""

        try:
            hold_id = create_hold(
                customer_id=cid,
                patient_name=patient_name,
                doctor_id=did,
                counter_no="",
                remarks="",
                total_amount_preview=total_amount,
                created_by=created_by,
                items=items_data,
            )
            hold = __import__(
                "database.hold_bill_dao", fromlist=["get_by_id"]
            ).get_by_id(hold_id)
            hold_num = hold["hold_number"] if hold else str(hold_id)
            QMessageBox.information(
                self, "Bill Held",
                f"Bill has been held as {hold_num}.\n"
                f"Items: {len(self._item_rows)}  |  Amount: {total_amount:.2f}"
            )
            self._held = True
            self.held.emit()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to hold bill:\n{e}")

    @property
    def was_held(self) -> bool:
        return getattr(self, "_held", False)

    def _populate_hold_bill(self, data: dict):
        """Load items from a held bill into the dialog for resume."""
        hold = data["hold"]
        items = data["items"]

        cid = hold.get("customer_id")
        if cid:
            idx = self.customer_combo.findData(cid)
            if idx >= 0:
                self.customer_combo.setCurrentIndex(idx)

        self.patient_name_edit.setText(hold.get("patient_name", ""))

        did = hold.get("doctor_id")
        if did:
            idx = self.doctor_combo.findData(did)
            if idx >= 0:
                self.doctor_combo.setCurrentIndex(idx)

        warnings = []
        for it in items:
            batch = SalesDAO.get_batch_by_item_and_batch_no(
                it["item_id"], it["batch_no"]
            )

            batch_stock = 0.0
            stock_batch_id = None
            if batch:
                stock_batch_id = batch["id"]
                batch_stock = batch.get("stock_qty", 0.0)

            if stock_batch_id is None:
                warnings.append(
                    f"Item '{it.get('item_name_snapshot', '')}' "
                    f"batch '{it['batch_no']}' â€” batch no longer available."
                )
                continue

            if SalesDAO.is_expired(it.get("expiry", "")):
                warnings.append(
                    f"Item '{it.get('item_name_snapshot', '')}' "
                    f"batch '{it['batch_no']}' â€” batch is expired."
                )
                continue

            if stock_batch_id and batch_stock < it.get("sale_qty", 0):
                warnings.append(
                    f"Item '{it.get('item_name_snapshot', '')}' "
                    f"batch '{it['batch_no']}' â€” insufficient stock "
                    f"({batch_stock:.0f} available, {it.get('sale_qty', 0):.0f} needed)."
                )

            row = _BillItemRow(
                item_id=it["item_id"],
                item_name=it.get("item_name_snapshot", ""),
                stock_batch_id=stock_batch_id,
                pack_size=it.get("pack_size", ""),
                location=it.get("location", ""),
                batch_no=it["batch_no"],
                expiry=it.get("expiry", ""),
                mrp=it.get("mrp", 0.0),
                sale_qty=it.get("sale_qty", 0.0),
                discount_amount=it.get("discount_amount", 0.0),
                amount=it.get("amount", 0.0),
            )
            self._item_rows.append(row)

        self._refresh_table()
        self._recalc_totals()
        self._refresh_draft_availability()

        if warnings:
            QMessageBox.warning(
                self, "Resume Warnings",
                "Some items from the held bill could not be loaded:\n\n"
                + "\n".join(warnings)
                + "\n\nPlease review before completing the sale."
            )


class _SaleDialog(QDialog):
    """Modal wrapper around :class:`_SalePanel` (compatibility only).

    The Counter Sale page uses the panel inline; this wrapper is kept so
    the modal entry point keeps working for any external caller.  It adds
    no transaction behaviour of its own.
    """

    def __init__(self, parent: QWidget | None = None, *,
                 invoice: dict | None = None,
                 hold_bill_data: dict | None = None):
        super().__init__(parent)
        _keep_alive(self)
        self.setWindowTitle("Counter Sale")
        self.setMinimumWidth(1200)
        self.setMinimumHeight(700)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._panel = _SalePanel(self, invoice=invoice,
                                 hold_bill_data=hold_bill_data)
        layout.addWidget(self._panel)

        self._panel.saved.connect(self.accept)
        self._panel.held.connect(self.accept)
        self._panel.cancelled.connect(self.reject)

    @property
    def was_saved(self) -> bool:
        return self._panel.was_saved

    @property
    def was_held(self) -> bool:
        return self._panel.was_held


# ======================================================================
# Sales Bill â€” review / edit popup (compact, modal, classic layout)
# ======================================================================

# Traditional pharmacy-software popup header: a solid blue title bar with
# white bold text, matching the reference bill window rather than a modern
# card.  Only this dialog uses the blue bar; the app palette is untouched.
_BILL_HEADER_BG = "#1f5c9e"
# Horizontal space the popup's own chrome takes from the item entry row:
# the body widget's margins and the vertical border either side.
_POPUP_BODY_CHROME = 16
# Slot reserved for the CNo mirror at the head of the popup's entry row.
_POPUP_CNO_WIDTH = 54
_BILL_DIALOG_STYLE = (
    f"QDialog#SalesBillDialog {{ background-color: {_SURFACE}; }}"
)


class SalesBillReviewDialog(QDialog):
    """Compact "Sales Bill" review/edit step for Counter Sale.

    Opened by the Counter Sale **Save Sale** button *after* the draft has
    been validated.  It shows the bill and lets the user correct the
    customer, patient, doctor, quantities, discounts and line items before
    committing.

    Transaction contract
    --------------------
    * Opening this popup writes nothing: no invoice, no stock deduction,
      no accounting entry.  It only takes a copy of the unsaved draft.
    * **Save** runs the full validation again and then performs the one and
      only commit (invoice + stock + posting) through the existing
      ``SalesDAO`` workflow.
    * **Close** / **Escape** discard the copy and return to Counter Sale
      with the draft untouched.

    The bill is edited through an embedded :class:`_SalePanel` set to
    review mode, so every existing control â€” item autocomplete, batch
    selection, draft stock reservation, add/delete line, keyboard
    navigation â€” is the same one the Counter Sale screen uses.
    """

    def __init__(self, panel: _SalePanel, parent: QWidget | None = None):
        super().__init__(parent)
        _keep_alive(self)
        self._source_panel = panel
        self.setObjectName("SalesBillDialog")
        self.setWindowTitle("Sales Bill")
        self.setModal(True)
        self.setStyleSheet(_BILL_DIALOG_STYLE)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_blue_header(panel))

        body = QWidget()
        body.setObjectName("SalesBillBody")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(6, 6, 6, 4)
        body_layout.setSpacing(0)

        # The editable copy of the draft.  Review mode makes its own
        # "Save Sale" behave as the final commit instead of opening a
        # second popup.
        self._panel = _SalePanel(body, popup_mode=True)
        self._panel._in_review_popup = True
        self._panel.load_draft_state(panel.draft_state())

        body_layout.addWidget(self._panel, 1)
        root.addWidget(body, 1)

        root.addWidget(self._build_actions())

        # The popup's Remarks box is the bill's remarks source when the sale
        # is committed from here; an edited bill shows its stored remarks.
        self._panel.remarks_edit = self.remarks_edit
        invoice = self._panel._invoice
        if invoice:
            self.remarks_edit.setText(invoice.get("remarks") or "")

        # A successful commit re-emits on the *source* panel so the Counter
        # Sale page performs its normal history refresh / form reset.
        self._panel.saved.connect(self._source_panel.saved.emit)
        # Hold stays a draft-only action: it is forwarded like Save so the
        # page resets, but no stock or accounting is touched either way.
        self._panel.held.connect(self._on_popup_held)
        # Cancel inside the popup means "discard", exactly like Close.
        self._panel.cancelled.connect(self.reject)

        self._resize_compact()
        # The popup's own width is only known now, so the Item Entry row is
        # measured and sized to fit exactly this window.
        self._panel.apply_popup_entry_widths(self.width() - _POPUP_BODY_CHROME)

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    def _build_blue_header(self, panel: _SalePanel) -> QWidget:
        """Blue title bar carrying Voucher No / Date / Time from the bill."""
        bar = QWidget()
        bar.setObjectName("SalesBillHeader")
        bar.setFixedHeight(52)
        bar.setStyleSheet(
            f"#SalesBillHeader {{ background-color: {_BILL_HEADER_BG};"
            f"  border-bottom: 1px solid {_BILL_HEADER_BG}; }}"
        )
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(12)

        title = QLabel("Sales Bill")
        title.setStyleSheet(
            "color: #ffffff; font-size: 14px; font-weight: bold;"
            f"background: transparent; font-family: {FONT_FAMILY};"
        )
        layout.addWidget(title)
        layout.addStretch()

        # Voucher No / Date / Time come from the live bill â€” the popup never
        # generates numbering of its own.
        for caption, value in (
            ("Voucher No", panel.bill_no_edit.text()),
            ("Date", panel.sale_date.date().toString("dd-MM-yyyy")),
            ("Time", panel.sale_time_edit.text()),
        ):
            caption_label = QLabel(caption)
            caption_label.setStyleSheet(
                "color: #d8e6f5; font-size: 10px; background: transparent;"
                f"font-family: {FONT_FAMILY};"
            )
            value_label = QLabel(value or "--")
            value_label.setStyleSheet(
                "color: #ffffff; font-size: 11px; font-weight: bold;"
                f"background: transparent; font-family: {FONT_FAMILY};"
            )
            layout.addWidget(caption_label)
            layout.addWidget(value_label)

        return bar

    def _build_actions(self) -> QWidget:
        """Bottom row: Total Items + Remarks on the left, Net Receivable and
        Save / Close on the right.
        """
        bar = QWidget()
        bar.setObjectName("SalesBillActions")
        bar.setStyleSheet(
            f"#SalesBillActions {{ background-color: {_SURFACE};"
            f"  border-top: 1px solid {_BORDER}; }}"
        )
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(10)

        # -- LEFT: Total Items / Remarks --
        items_caption = QLabel("Total Items")
        items_caption.setStyleSheet(
            f"color: {_TEXT}; font-size: 11px; background: transparent;"
            f"font-family: {FONT_FAMILY};"
        )
        layout.addWidget(items_caption)
        self._total_items_label = QLabel(str(len(self._panel._item_rows)))
        self._total_items_label.setStyleSheet(
            f"color: {_TEXT}; font-size: 11px; font-weight: bold;"
            f"background: transparent; font-family: {FONT_FAMILY};"
        )
        layout.addWidget(self._total_items_label)
        layout.addSpacing(6)

        remarks_caption = QLabel("Remarks")
        remarks_caption.setStyleSheet(
            f"color: {_TEXT}; font-size: 11px; background: transparent;"
            f"font-family: {FONT_FAMILY};"
        )
        layout.addWidget(remarks_caption)
        self.remarks_edit = _make_edit()
        self.remarks_edit.setMinimumWidth(140)
        layout.addWidget(self.remarks_edit)
        layout.addStretch()

        # -- RIGHT: Net Receivable --
        net_caption = QLabel("Net Receivable")
        net_caption.setStyleSheet(
            f"color: {_TEXT}; font-size: 12px; font-weight: bold;"
            f"background: transparent; font-family: {FONT_FAMILY};"
        )
        self._net_receivable_label = QLabel(self._panel.net_amt_label.text())
        self._net_receivable_label.setStyleSheet(
            f"color: {_ACCENT}; font-size: 14px; font-weight: bold;"
            f"background: transparent; font-family: {FONT_FAMILY};"
        )
        layout.addWidget(net_caption)
        layout.addWidget(self._net_receivable_label)
        layout.addSpacing(10)

        self._final_save_btn = QPushButton("Save")
        self._final_save_btn.setStyleSheet(_BTN_SAVE)
        self._final_save_btn.setFixedWidth(96)
        self._final_save_btn.setDefault(True)
        self._final_save_btn.setToolTip(
            "Commit this bill: save the sale, deduct stock and post accounting"
        )
        self._final_save_btn.clicked.connect(self._on_final_save)
        layout.addWidget(self._final_save_btn)

        close_btn = QPushButton("Close")
        close_btn.setStyleSheet(_BTN_SECONDARY)
        close_btn.setFixedWidth(96)
        close_btn.setAutoDefault(False)
        close_btn.clicked.connect(self.reject)
        layout.addWidget(close_btn)

        # Keep the Net Receivable summary live while the bill is edited.
        self._panel.totals_changed.connect(self._on_totals_changed)
        return bar

    def _on_totals_changed(self, bill_no: str, amount: str, bill_total: str):
        self._net_receivable_label.setText(amount)
        # Adding or deleting a line recalculates the totals, so the item
        # count is refreshed through that same existing signal.
        self._total_items_label.setText(str(len(self._panel._item_rows)))

    # Reference proportions for the Sales Bill window: a compact dialog that is
    # never full-screen at any of the supported desktop resolutions.  The
    # width is sized so the whole Item Entry row fits on ONE line with every
    # label and value clear of its neighbour â€” twelve labelled fields plus
    # their captions need roughly 1.2k px, so the window is wide and short
    # rather than square, and the height stays compact.
    MIN_WIDTH, MAX_WIDTH = 1180, 1300
    MIN_HEIGHT, MAX_HEIGHT = 520, 600

    @classmethod
    def target_size(cls, available_w: int, available_h: int) -> tuple[int, int]:
        """Popup size for a screen of ``available_w`` x ``available_h``."""
        width = min(cls.MAX_WIDTH,
                    max(cls.MIN_WIDTH, int(available_w * 0.96)))
        height = min(cls.MAX_HEIGHT,
                     max(cls.MIN_HEIGHT, int(available_h * 0.72)))
        return width, height

    def _resize_compact(self):
        """Keep the popup in the reference proportions, not full-screen."""
        screen = self.screen() if self.screen() else None
        available = (screen.availableSize() if screen else QSize(1366, 768))
        width, height = self.target_size(available.width(), available.height())
        self.setFixedSize(width, height)
        self.setMinimumSize(self.MIN_WIDTH, self.MIN_HEIGHT)
        self.setMaximumSize(self.MAX_WIDTH, self.MAX_HEIGHT)
        self._center_over_host()

    def _center_over_host(self):
        """Centre the popup on the Counter Sale screen behind it.

        Qt centres a dialog on its immediate parent, which here is the sale
        panel, so the position is set explicitly against the whole page to
        keep the window visually centred over Counter Sale.
        """
        host = self.parentWidget()
        anchor = host.window() if host is not None else None
        if anchor is None:
            return
        area = anchor.geometry()
        self.move(
            area.x() + max(0, (area.width() - self.width()) // 2),
            area.y() + max(0, (area.height() - self.height()) // 2),
        )

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _on_popup_held(self):
        """Forward a Hold made inside the popup and close it unchanged."""
        self._source_panel.held.emit()
        self.reject()

    def _on_final_save(self):
        """The only place the sale is actually written.

        ``was_saved`` is checked before and after so a second click (or a
        double-click) on Save can never produce a second invoice, stock
        deduction or posting set.
        """
        if self._panel.was_saved:
            return
        self._final_save_btn.setEnabled(False)
        # Runs the same full validation as the Counter Sale Save Sale step,
        # then commits.  Re-enables Save if validation or the write failed.
        self._panel._on_save()
        if not self._panel.was_saved:
            self._final_save_btn.setEnabled(True)
            return
        # Committed: the page has already refreshed history via the `saved`
        # signal, so close the popup.
        self.accept()


# ======================================================================
# Counter Sale PAGE (History | inline active sale area | bill panel)
# ======================================================================

class CounterSalePage(QWidget):
    """Counter Sale screen.

    Fixed three-region desktop layout (Phase 6E â€” Counter Sale Layout Fix):

        Region A  page header + controlled-height Bill History table
        Region B  active sale entry, directly below the history table
        Region C  current bill table (takes the remaining space)
        Right     fixed "Bill" panel with actions and live bill totals

    The sale area is embedded inline (via ``_SalePanel``), so adding items
    or history rows never moves or vertically centers the entry region.
    """

    HISTORY_PAGE_SIZE = 200

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        _keep_alive(self)
        self.setStyleSheet(f"background-color: {_DARK_BG};")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Region A (top): page header strip
        root.addWidget(self._build_header_strip())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(0)

        # Region A: controlled-height history table (directly below header)
        self._hist_table = self._build_history_table()
        self._history_offset = 0
        self._history_has_more = True
        self._history_loading = False
        self._hist_table.verticalScrollBar().valueChanged.connect(
            self._on_history_scroll
        )
        left.addWidget(self._hist_table)

        # Regions B + C: inline active sale area.  Only the bill table
        # inside the panel expands, so the entry region stays pinned.
        self._sale_panel = _SalePanel()
        self._sale_panel.saved.connect(self._on_sale_saved)
        self._sale_panel.held.connect(self._on_sale_held)
        self._sale_panel.cancelled.connect(self._on_sale_cancelled)
        left.addWidget(self._sale_panel, 1)

        body.addLayout(left, 1)
        body.addWidget(self._build_bill_panel())

        root.addLayout(body, 1)

        self._editing_invoice_id: int | None = None
        self._refresh_history()
        self._apply_history_height()

    # ------------------------------------------------------------------
    # Layout construction
    # ------------------------------------------------------------------

    def _build_header_strip(self) -> QWidget:
        """Region A header: page title + New Sale (history actions live in
        the right-side bill panel)."""
        header = QWidget()
        header.setFixedHeight(30)
        header.setStyleSheet(
            f"background-color: {_SURFACE}; border-bottom: 1px solid {_BORDER};"
        )
        hl = QHBoxLayout(header)
        hl.setContentsMargins(10, 0, 10, 0)
        hl.setSpacing(8)

        title = QLabel("Sales / Counter Sale")
        title.setStyleSheet(
            f"color: {_TEXT}; font-size: 18px; font-weight: bold;"
            f"background: transparent; font-family: {FONT_FAMILY};"
        )
        hl.addWidget(title)

        subtitle = QLabel("Bill History")
        subtitle.setStyleSheet(
            f"color: {_TEXT_DIM}; font-size: 11px;"
            f"background: transparent; font-family: {FONT_FAMILY};"
        )
        hl.addWidget(subtitle)
        hl.addStretch()

        self._new_btn = QPushButton("New Sale")
        self._new_btn.setFixedWidth(110)
        self._new_btn.setStyleSheet(_BTN_SAVE)
        self._new_btn.setToolTip(
            "Start a new sale in the active sale area below"
        )
        self._new_btn.clicked.connect(self._on_new)
        hl.addWidget(self._new_btn)

        return header

    def _build_history_table(self) -> QTableWidget:
        """Region A table â€” height is controlled by _apply_history_height()."""
        table = QTableWidget()
        table.setColumnCount(13)
        table.setHorizontalHeaderLabels([
            "Bill No", "Type", "Item Name", "MRP", "Qty", "Amount",
            "Patient", "Pack Size", "Batch No", "Expiry", "Time",
            "Disc Amt", "Bill Amount"
        ])
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.verticalHeader().setVisible(False)
        table.setShowGrid(True)
        table.setAlternatingRowColors(False)
        table.setSortingEnabled(True)
        table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        hv = table.horizontalHeader()
        hv.setStretchLastSection(True)
        for col in range(13):
            if col == 2:
                hv.setSectionResizeMode(col, QHeaderView.Stretch)
            else:
                hv.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        hv.setStyleSheet(
            f"QHeaderView::section {{"
            f"  background-color: {_SURFACE}; color: {_TEXT};"
            f"  border: none; border-bottom: 2px solid {_ACCENT};"
            f"  padding: 4px 6px; font-weight: bold; font-size: 11px;"
            f"  font-family: {FONT_FAMILY};"
            f"}}"
        )
        table.setStyleSheet(
            f"QTableWidget {{"
            f"  background-color: {_DARK_BG}; color: {_TEXT};"
            f"  border: 1px solid {_BORDER}; gridline-color: {_BORDER};"
            f"  font-size: 11px; font-family: {FONT_FAMILY};"
            f"  selection-background-color: {_ACCENT};"
            f"  selection-color: white;"
            f"}}"
            f"QTableWidget::item {{ padding: 3px 5px; }}"
        )
        return table

    def _build_bill_panel(self) -> QWidget:
        """Fixed right-side 'Bill' panel: actions + live bill totals."""
        panel = QWidget()
        panel.setObjectName("BillPanel")
        panel.setFixedWidth(236)
        panel.setStyleSheet(
            f"#BillPanel {{ background-color: {_SURFACE};"
            f"  border-left: 1px solid {_BORDER}; }}"
        )
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        actions = QGroupBox("Bill")
        actions.setStyleSheet(_GROUP_BOX)
        al = QVBoxLayout(actions)
        al.setContentsMargins(8, 16, 8, 8)
        al.setSpacing(4)
        for text, style, handler in (
            ("Edit", _BTN_SECONDARY, self._on_edit),
            ("Delete", _BTN_DANGER, self._on_delete),
            ("Print", _BTN_SECONDARY, self._on_direct_print),
            ("Print / PDF", _BTN_SECONDARY, self._on_print),
        ):
            btn = QPushButton(text)
            btn.setStyleSheet(style)
            btn.setFixedHeight(_ACTION_BUTTON_HEIGHT)
            btn.clicked.connect(handler)
            al.addWidget(btn)
        paper_label = QLabel(f"Paper: {a6_profile().size_label}")
        paper_label.setStyleSheet("color: #666; font-size: 8pt;")
        paper_label.setAlignment(Qt.AlignCenter)
        al.addWidget(paper_label)
        layout.addWidget(actions)

        info = QGroupBox("Current Bill")
        info.setStyleSheet(_GROUP_BOX)
        form = QFormLayout(info)
        form.setContentsMargins(8, 16, 8, 8)
        form.setSpacing(4)
        self._bill_total_value = QLabel("0.00")
        self._cno_value = QLabel(self._sale_panel.bill_no_edit.text() or "--")
        self._amount_value = QLabel("0.00")
        for value_label in (self._bill_total_value, self._cno_value,
                            self._amount_value):
            value_label.setStyleSheet(
                f"color: {_TEXT}; font-size: 11px; font-weight: bold;"
                f"font-family: {FONT_FAMILY}; background: transparent;"
            )
            value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.addRow(self._flbl("Bill Total"), self._bill_total_value)
        form.addRow(self._flbl("CNo"), self._cno_value)
        form.addRow(self._flbl("Amount"), self._amount_value)
        layout.addWidget(info)
        layout.addStretch()

        # Live display only â€” no logic attached.
        self._sale_panel.totals_changed.connect(self._on_bill_totals)
        self._on_bill_totals(
            self._sale_panel.bill_no_edit.text(),
            self._sale_panel.total_amount_label.text(),
            self._sale_panel.net_amt_label.text(),
        )
        return panel

    def _on_bill_totals(self, bill_no: str, amount: str, bill_total: str):
        """Mirror the active bill figures into the right-side panel."""
        self._cno_value.setText(bill_no or "--")
        self._amount_value.setText(amount)
        self._bill_total_value.setText(bill_total)

    def _apply_history_height(self):
        """Keep the history region at a controlled ~25-30% of page height.

        The table is given a fixed height, so an empty history table can
        never expand into a giant blank area and adding rows can never
        grow the region.  The filter bar was removed, so the history
        region now uses the freed vertical space.
        """
        page_height = self.height()
        if page_height < 200:          # before the first real resize
            page_height = 720
        target = int(page_height * 0.28)
        target = max(130, min(target, 280))
        self._hist_table.setFixedHeight(target)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_history_height()

    def showEvent(self, event):
        super().showEvent(event)
        self._apply_history_height()

    def _flbl(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(_LABEL_DIM)
        return lbl

    def _refresh_history(self):
        self._history_offset = 0
        self._history_has_more = True
        self._history_loading = False
        self._hist_table.setRowCount(0)
        self._load_more_history()

    def _on_history_scroll(self, value: int):
        scrollbar = self._hist_table.verticalScrollBar()
        if (self._hist_table.rowCount() and self._history_has_more and
                not self._history_loading and value >= scrollbar.maximum()):
            self._load_more_history()

    def _load_more_history(self):
        if self._history_loading or not self._history_has_more:
            return
        self._history_loading = True
        sorting_enabled = self._hist_table.isSortingEnabled()
        try:
            rows = SalesDAO.get_history_page(
                limit=self.HISTORY_PAGE_SIZE, offset=self._history_offset
            )
            if not rows:
                self._history_has_more = False
                return
            page_invoice_count = len({row["invoice_id"] for row in rows})
            self._history_has_more = page_invoice_count == self.HISTORY_PAGE_SIZE
            self._history_offset += self.HISTORY_PAGE_SIZE

            table = self._hist_table
            table.setSortingEnabled(False)
            first_row = table.rowCount()
            table.setRowCount(first_row + len(rows))
            for row_index, row in enumerate(rows, first_row):
                table.setItem(row_index, 0, QTableWidgetItem(row.get("bill_no") or ""))
                table.setItem(row_index, 1, QTableWidgetItem(row.get("sale_type") or ""))
                table.setItem(row_index, 2, QTableWidgetItem(row.get("item_name") or ""))

                mrp_item = QTableWidgetItem(f"{float(row.get('mrp') or 0):.2f}")
                mrp_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                table.setItem(row_index, 3, mrp_item)

                qty_item = QTableWidgetItem(f"{float(row.get('sale_qty') or 0):.0f}")
                qty_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                table.setItem(row_index, 4, qty_item)

                amount_item = QTableWidgetItem(f"{float(row.get('amount') or 0):.2f}")
                amount_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                table.setItem(row_index, 5, amount_item)

                table.setItem(row_index, 6, QTableWidgetItem(row.get("patient_name") or ""))
                table.setItem(row_index, 7, QTableWidgetItem(row.get("pack_size") or ""))
                table.setItem(row_index, 8, QTableWidgetItem(row.get("batch_no") or ""))
                table.setItem(row_index, 9, QTableWidgetItem(row.get("expiry") or ""))
                table.setItem(row_index, 10, QTableWidgetItem(row.get("sale_time") or ""))

                discount_item = QTableWidgetItem(
                    f"{float(row.get('discount_amount') or 0):.2f}"
                )
                discount_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                table.setItem(row_index, 11, discount_item)

                bill_item = QTableWidgetItem(f"{float(row.get('net_amount') or 0):.2f}")
                bill_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                table.setItem(row_index, 12, bill_item)
                table.item(row_index, 0).setData(Qt.UserRole, row["invoice_id"])
            table.setSortingEnabled(sorting_enabled)
        finally:
            self._history_loading = False

    def _selected_history_id(self) -> int | None:
        rows = self._hist_table.selectionModel().selectedRows()
        if not rows:
            return None
        row = rows[0].row()
        return self._hist_table.item(row, 0).data(Qt.UserRole)

    def _on_new(self):
        """Start a new sale inline: reset the form, focus Item Name."""
        self._editing_invoice_id = None
        self._sale_panel.reset_for_new()
        self._sale_panel.focus_item_name()

    def _on_edit(self):
        try:
            auth.session.require(auth.PERM_EDIT_TRANSACTIONS)
        except auth.PermissionDenied as exc:
            QMessageBox.warning(self, "Permission denied", str(exc)); return
        inv_id = self._selected_history_id()
        if not inv_id:
            QMessageBox.information(self, "Edit Sale", "Please select a bill to edit.")
            return
        inv = SalesDAO.get_by_id(inv_id)
        if not inv:
            QMessageBox.warning(self, "Edit Sale", "Could not load bill data.")
            return
        self._editing_invoice_id = inv_id
        self._sale_panel.load_invoice(inv)
        self._sale_panel.focus_item_name()

    def _on_delete(self):
        try:
            auth.session.require(auth.PERM_DELETE_TRANSACTIONS)
        except auth.PermissionDenied as exc:
            QMessageBox.warning(self, "Permission denied", str(exc)); return
        inv_id = self._selected_history_id()
        if not inv_id:
            QMessageBox.information(self, "Delete Sale", "Please select a bill to delete.")
            return
        reply = QMessageBox.question(
            self, "Confirm Delete",
            "Are you sure you want to delete this sale? Stock will be restored.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            try:
                SalesDAO.delete_invoice(inv_id)
                self._refresh_history()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to delete sale:\n{e}")

    def _on_print(self):
        inv_id = self._selected_history_id()
        if not inv_id:
            QMessageBox.information(self, "Print Sale", "Please select a bill to print.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save Sales Bill PDF", "sales_bill.pdf", "PDF (*.pdf)")
        if not path:
            return
        try:
            output = generate_counter_sale_bill(inv_id, path)
            QMessageBox.information(self, "PDF Saved", f"A6 receipt saved to:\n{output}")
        except DocumentPrintError as exc:
            QMessageBox.warning(self, "Print Sale", str(exc))

    def _on_direct_print(self):
        """Send the selected bill straight to the Windows print dialog on A6."""
        inv_id = self._selected_history_id()
        if not inv_id:
            QMessageBox.information(self, "Print Sale", "Please select a bill to print.")
            return
        try:
            print_pharmacy_a6_bill(inv_id, self, "Counter Sale Bill")
        except DocumentPrintError as exc:
            QMessageBox.warning(self, "Print Sale", str(exc))

    def _open_sale_dialog(self, invoice: dict | None = None,
                          hold_bill_data: dict | None = None):
        """Backwards-compatible entry point â€” the sale area is inline now.

        Kept so existing callers keep working; no dialog is opened and no
        transaction logic is duplicated.
        """
        if invoice is not None:
            self._sale_panel.load_invoice(invoice)
        elif hold_bill_data is not None:
            self._sale_panel.load_hold(hold_bill_data)
        else:
            self._sale_panel.reset_for_new()
        self._sale_panel.focus_item_name()

    def open_sale_dialog_with_hold(self, hold_bill_data: dict):
        """Load a held bill into the inline sale area (called from HoldBillPage).

        The resumed bill appears in the same Region B position as any new
        sale; Hold/Resume behaviour itself is unchanged.
        """
        self._open_sale_dialog(hold_bill_data=hold_bill_data)
        self.raise_()
        self.activateWindow()

    # ------------------------------------------------------------------
    # Inline sale-area lifecycle
    # ------------------------------------------------------------------

    def _on_sale_saved(self):
        # The save completed: refresh the history and reset the inline form
        # for the next sale (the modal dialog used to close here, which is
        # what prevented a second save of the same bill).
        self._editing_invoice_id = None
        self._refresh_history()
        self._sale_panel.reset_for_new()

    def _on_sale_held(self):
        # Hold completed: same lifecycle as before (dialog closed), now the
        # inline form is reset instead.
        self._editing_invoice_id = None
        self._refresh_history()
        self._sale_panel.reset_for_new()

    def _on_sale_cancelled(self):
        self._sale_panel.reset_for_new()
