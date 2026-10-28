from __future__ import annotations

import calendar
import re
from datetime import datetime, date
from decimal import Decimal, ROUND_HALF_UP

from PySide6.QtCore import Qt, QDate, QEvent, QStringListModel, Signal, QModelIndex, QPoint
from PySide6.QtGui import QFont, QStandardItemModel, QStandardItem
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCalendarWidget,
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
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from database.supplier_dao import SupplierDAO
from database.ledger_dao import LedgerDAO
from database.item_dao import ItemDAO
from database.tax_structures import rate_percent
from database.purchase_dao import PurchaseDAO
from database import auth
from database import financial_year
from database.document_printing import DocumentPrintError, generate_purchase_invoice

from ui.components import ConstrainedComboBox, SearchableComboBox
from ui.theme import date_subcontrols, palette
_p = palette()
_DARK_BG = _p["bg"]
_SURFACE = _p["surface"]
_BORDER = _p["border"]
_ACCENT = _p["accent"]
_ACCENT_HOVER = _p["accent_hover"]
_TEXT = _p["text"]
_TEXT_DIM = _p["text_dim"]
_ERROR = "#c0392b"


def _combo_style(p: dict | None = None) -> str:
    p = p or palette()
    surface = p["surface"]
    text = p["text"]
    border = p["border"]
    accent = p["accent"]
    selected_bg = p.get("selected", accent)
    selected_text = p.get("selected_text", "#ffffff")
    return (
        f"QComboBox {{"
        f"  background-color: {surface}; color: {text};"
        f"  border: 1px solid {border}; border-radius: 2px;"
        f"  padding: 2px 6px; font-size: 15px; font-weight: bold; font-family: 'Segoe UI';"
        f"  min-height: 24px;"
        f"}}"
        f"QComboBox:hover {{ border: 1px solid {accent}; }}"
        f"QComboBox::drop-down {{ border: none; width: 24px; }}"
        f"QComboBox::down-arrow {{ image: none; border: none; }}"
        f"QComboBox QAbstractItemView {{"
        f"  background-color: {surface}; color: {text};"
        f"  border: 1px solid {border}; selection-background-color: {selected_bg};"
        f"  selection-color: {selected_text};"
        f"  font-size: 15px; font-family: 'Segoe UI';"
        f"  outline: none;"
        f"}}"
        f"QComboBox QAbstractItemView::item {{"
        f"  min-height: 26px; padding: 2px 8px;"
        f"}}"
        f"QComboBox QAbstractItemView::item:selected {{"
        f"  background-color: {selected_bg}; color: {selected_text};"
        f"}}"
    )


_COMBO_STYLE = _combo_style()


def _edit_style(p: dict | None = None) -> str:
    p = p or palette()
    surface = p["surface"]
    text = p["text"]
    border = p["border"]
    accent = p["accent"]
    return (
        f"QLineEdit {{"
        f"  background-color: {surface}; color: {text};"
        f"  border: 1px solid {border}; border-radius: 2px;"
        f"  padding: 2px 6px; font-size: 15px; font-weight: bold; font-family: 'Segoe UI';"
        f"  min-height: 24px;"
        f"}}"
        f"QLineEdit:focus {{ border: 1px solid {accent}; }}"
    )


_EDIT_STYLE = _edit_style()


def _searchable_lineedit_style(p: dict | None = None) -> str:
    p = p or palette()
    text = p["text"]
    return (
        f"QLineEdit {{"
        f"  background: transparent; color: {text};"
        f"  border: none; padding: 1px 4px;"
        f"  font-size: 14px; font-weight: bold; font-family: 'Segoe UI';"
        f"}}"
    )


def _display_voucher_no(voucher_no: str) -> str:
    """Return only the numeric / sequence part of a voucher number for display.
    e.g. '2026-2027-Credit-0251' -> '251', preserving the full compound key in the database.
    """
    from core.doc_formatter import format_purchase_voucher_number
    return format_purchase_voucher_number(voucher_no)


def _date_style(p: dict | None = None) -> str:
    p = p or palette()
    surface = p["surface"]
    text = p["text"]
    border = p["border"]
    accent = p["accent"]
    return (
        f"QDateEdit {{"
        f"  background-color: {surface}; color: {text};"
        f"  border: 1px solid {border}; border-radius: 2px;"
        f"  padding: 2px 6px; font-size: 15px; font-weight: bold; font-family: 'Segoe UI';"
        f"  min-height: 24px;"
        f"}}"
        f"QDateEdit:focus {{ border: 1px solid {accent}; }}"
        + date_subcontrols(p, width=24)
    )


_DATE_STYLE = _date_style()

_BTN_SAVE = (
    f"QPushButton {{ background-color: {_ACCENT}; color: white;"
    f"  border: none; border-radius: 2px; padding: 8px 20px;"
    f"  font-weight: bold; font-size: 15px; font-family: 'Segoe UI'; }}"
    f"QPushButton:hover {{ background-color: {_ACCENT_HOVER}; }}"
)

_BTN_SECONDARY = (
    f"QPushButton {{ background-color: {_BORDER}; color: {_TEXT};"
    f"  border: none; border-radius: 2px; padding: 8px 20px;"
    f"  font-size: 15px; font-family: 'Segoe UI'; }}"
    f"QPushButton:hover {{ background-color: #7d93a8; }}"
)

_BTN_DANGER = (
    f"QPushButton {{ background-color: {_ERROR}; color: white;"
    f"  border: none; border-radius: 3px; padding: 4px 8px;"
    f"  font-weight: bold; font-size: 15px; font-family: 'Segoe UI'; }}"
    f"QPushButton:hover {{ background-color: #d32f2f; }}"
)

_BTN_GREEN_SM = (
    f"QPushButton {{ background-color: {_ACCENT}; color: white;"
    f"  border: none; border-radius: 2px; padding: 6px 14px;"
    f"  font-weight: bold; font-size: 15px; font-family: 'Segoe UI'; }}"
    f"QPushButton:hover {{ background-color: {_ACCENT_HOVER}; }}"
)

_LABEL_STYLE = f"color: {_TEXT}; font-size: 15px; font-family: 'Segoe UI'; background: transparent;"
_LABEL_DIM = f"color: {_TEXT}; font-size: 15px; font-weight: bold; font-family: 'Segoe UI'; background: transparent;"
_HEADER_LABEL = f"color: {_TEXT}; font-size: 15px; font-family: 'Segoe UI'; background: transparent; font-weight: bold;"

_GROUP_BOX = (
    f"QGroupBox {{"
    f"  background-color: {_DARK_BG};"
    f"  color: {_TEXT}; font-weight: bold; font-size: 15px;"
    f"  border: 1px solid {_BORDER}; border-radius: 2px;"
    f"  margin-top: 10px; padding-top: 14px;"
    f"}}"
    f"QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 6px;"
    f"  color: {_TEXT}; background-color: {_DARK_BG}; }}"
)


def _make_edit(placeholder: str = "", width: int | None = None) -> QLineEdit:
    e = QLineEdit()
    e.setPlaceholderText(placeholder)
    e.setStyleSheet(_EDIT_STYLE)
    e.setFont(__import__("PySide6.QtGui", fromlist=["QFont"]).QFont("Segoe UI", 11))
    e.setFixedHeight(32)
    if width:
        e.setFixedWidth(width)
    return e


def _entry_edit_style(p: dict | None = None) -> str:
    p = p or palette()
    surface = p["surface"]
    text = p["text"]
    border = p["border"]
    accent = p["accent"]
    disabled_bg = p.get("disabled_bg", surface)
    return (
        f"QLineEdit {{"
        f"  background-color: {surface}; color: {text};"
        f"  border: 1px solid {border}; border-radius: 2px;"
        f"  padding: 2px 3px; font-size: 13px; font-weight: bold; font-family: 'Segoe UI';"
        f"  min-height: 22px;"
        f"}}"
        f"QLineEdit:focus {{ border: 1px solid {accent}; }}"
        f"QLineEdit:read-only {{"
        f"  background-color: {disabled_bg}; color: {text};"
        f"  border: 1px solid {border};"
        f"}}"
    )


def _make_entry_edit(placeholder: str = "", width: int | None = None, p: dict | None = None) -> QLineEdit:
    e = QLineEdit()
    e.setPlaceholderText(placeholder)
    e.setStyleSheet(_entry_edit_style(p))
    e.setFont(__import__("PySide6.QtGui", fromlist=["QFont"]).QFont("Segoe UI", 9))
    e.setFixedHeight(30)
    if width:
        e.setFixedWidth(width)
    return e


def _btn_add_item_style(p: dict | None = None) -> str:
    p = p or palette()
    accent = p.get("accent", _ACCENT)
    accent_hover = p.get("accent_hover", _ACCENT_HOVER)
    return (
        f"QPushButton {{ background-color: {accent}; color: white;"
        f"  border: none; border-radius: 2px; padding: 2px 6px;"
        f"  font-weight: bold; font-size: 13px; font-family: 'Segoe UI'; }}"
        f"QPushButton:hover {{ background-color: {accent_hover}; }}"
    )


def _make_combo(
    *,
    max_visible: int = 9,
    max_height: int = 270,
    max_width: int | None = None,
    min_width: int | None = None,
    allow_width_expansion: bool = True,
) -> ConstrainedComboBox:
    c = ConstrainedComboBox(
        max_visible_items=max_visible,
        max_popup_height=max_height,
        max_popup_width=max_width,
        min_popup_width=min_width,
        allow_width_expansion=allow_width_expansion,
    )
    c.setStyleSheet(_combo_style())
    c.setFixedHeight(32)
    return c


def _make_date(p: dict | None = None, parent: QWidget | None = None) -> QDateEdit:
    d = QDateEdit(parent)
    d.setCalendarPopup(True)
    d.setDisplayFormat("dd-MM-yyyy")
    d.setStyleSheet(_date_style(p))
    d.setFixedHeight(32)
    return d


# SearchableComboBox is defined in ui.components and imported above for use across all screens.


def _safe_float(text: str, default: float = 0.0) -> float:
    try:
        return float(text.strip()) if text.strip() else default
    except ValueError:
        return default


def _d(value) -> Decimal:
    """Convert to Decimal for currency-safe arithmetic."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _round2(value) -> float:
    """Round to 2 decimal places using ROUND_HALF_UP."""
    return float(_d(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def parse_expiry_to_date(val: str | date | None) -> date | None:
    """Parse any stored or entered expiry string into a datetime.date."""
    if not val:
        return None
    if isinstance(val, date):
        return val
    s = str(val).strip()
    if not s or s.upper() in ("DD-MM-YYYY", "MM/YY"):
        return None
    for fmt in (
        "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d",
        "%d.%m.%Y", "%d-%m-%y", "%d/%m/%y", "%d.%m.%y",
    ):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    parts = [p.strip() for p in re.split(r"[-/.]", s) if p.strip()]
    if len(parts) == 2:
        try:
            if len(parts[0]) == 4:
                y = int(parts[0])
                m = int(parts[1])
            else:
                m = int(parts[0])
                y = int(parts[1])
                if y < 100:
                    y += 2000
            if 1 <= m <= 12:
                last_day = calendar.monthrange(y, m)[1]
                return date(y, m, last_day)
        except Exception:
            pass
    if s.isdigit():
        try:
            if len(s) == 8:
                d, m, y = int(s[:2]), int(s[2:4]), int(s[4:])
                if 1 <= m <= 12 and 1 <= d <= 31 and 1900 <= y <= 2100:
                    return date(y, m, d)
                y, m, d = int(s[:4]), int(s[4:6]), int(s[6:])
                if 1 <= m <= 12 and 1 <= d <= 31 and 1900 <= y <= 2100:
                    return date(y, m, d)
            elif len(s) == 6:
                d, m, y = int(s[:2]), int(s[2:4]), int(s[4:]) + 2000
                if 1 <= m <= 12 and 1 <= d <= 31:
                    return date(y, m, d)
            elif len(s) == 4:
                m, y = int(s[:2]), int(s[2:]) + 2000
                if 1 <= m <= 12:
                    last_day = calendar.monthrange(y, m)[1]
                    return date(y, m, last_day)
        except Exception:
            pass
    return None


def format_expiry_display(val: str | date | None) -> str:
    """Format any expiry value to DD-MM-YYYY for UI display."""
    d = parse_expiry_to_date(val)
    return d.strftime("%d-%m-%Y") if d else (str(val).strip() if val else "")


def normalize_expiry_db(val: str | date | None) -> str:
    """Normalize any expiry value to YYYY-MM-DD for database storage."""
    d = parse_expiry_to_date(val)
    return d.strftime("%Y-%m-%d") if d else (str(val).strip() if val else "")


class BatchCompleter(QCompleter):
    """QCompleter that returns the batch number from UserRole data upon selection."""

    def pathFromIndex(self, index: QModelIndex) -> str:
        data = index.data(Qt.UserRole)
        if isinstance(data, dict):
            return data.get("batch_no", "")
        return super().pathFromIndex(index)


class BatchLineEdit(QLineEdit):
    """Line edit for batch number with dynamic autocomplete for existing saved batches."""

    batch_selected = Signal(dict)

    def __init__(self, placeholder: str = "Batch", width: int = 82, p: dict | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self.setFixedHeight(30)
        if width:
            self.setFixedWidth(width)
        self.setFont(QFont("Segoe UI", 9))
        self.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.textChanged.connect(
            lambda t: self.setToolTip(f"Batch: {t}" if t else "Enter batch number")
        )

        self._model = QStandardItemModel(self)
        self._completer = BatchCompleter(self._model, self)
        self._completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._completer.setFilterMode(Qt.MatchContains)
        self._completer.setCompletionRole(Qt.UserRole + 1)
        self._completer.setCompletionMode(QCompleter.PopupCompletion)
        self._completer.setMaxVisibleItems(8)

        popup = self._completer.popup()
        if popup is not None:
            popup.setMinimumWidth(220)
            popup.setMaximumHeight(240)
            popup.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            popup.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.setCompleter(self._completer)
        self._completer.activated[QModelIndex].connect(self._on_completer_activated)
        self.textEdited.connect(self._on_text_edited)
        self.installEventFilter(self)
        self.refresh_theme(p)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        if not self.isReadOnly() and self._model.rowCount() > 0:
            popup = self._completer.popup()
            if popup is not None and not popup.isVisible():
                self._completer.setCompletionPrefix(self.text().strip())
                self._completer.complete()
                popup.setCurrentIndex(QModelIndex())

    def refresh_theme(self, p: dict | None = None):
        p = p or palette()
        surface = p["surface"]
        text = p["text"]
        border = p["border"]
        accent = p["accent"]
        selected_bg = p.get("selected", accent)
        selected_fg = p.get("selected_text", "#ffffff")
        self.setStyleSheet(_entry_edit_style(p))
        popup = self._completer.popup()
        if popup is not None:
            popup.setStyleSheet(
                f"QAbstractItemView {{"
                f"  background-color: {surface}; color: {text};"
                f"  border: 1px solid {border};"
                f"  selection-background-color: {selected_bg}; selection-color: {selected_fg};"
                f"  font-size: 14px; font-family: 'Segoe UI'; outline: 0;"
                f"}}"
                f"QAbstractItemView::item {{ min-height: 26px; padding: 2px 8px; }}"
            )

    def set_batches(self, batches: list[dict], invoice_date: date | None = None):
        """Populate the completer model with saved batches for the current item displaying Batch No and supporting Expiry info."""
        self._model.clear()
        for b in batches:
            bno = (b.get("batch_no") or "").strip()
            if not bno:
                continue
            exp = (b.get("expiry") or "").strip()
            exp_disp = format_expiry_display(exp)
            if exp_disp:
                exp_d = parse_expiry_to_date(exp)
                if invoice_date and exp_d and exp_d < invoice_date:
                    label = f"{bno}  (Exp: {exp_disp} - Expired)"
                else:
                    label = f"{bno}  (Exp: {exp_disp})"
            else:
                label = bno

            item = QStandardItem(label)
            item.setData(bno, Qt.UserRole + 1)
            item.setData(b, Qt.UserRole)
            self._model.appendRow(item)

    def _on_text_edited(self, text: str):
        if not self._model.rowCount():
            return
        prefix = text.strip()
        if prefix:
            self._completer.setCompletionPrefix(prefix)
            if self._completer.completionCount() > 0:
                self._completer.complete()
            else:
                popup = self._completer.popup()
                if popup is not None and popup.isVisible():
                    popup.hide()
        else:
            popup = self._completer.popup()
            if popup is not None and popup.isVisible():
                popup.hide()

    def _on_completer_activated(self, index: QModelIndex):
        if not index.isValid():
            return
        data = index.data(Qt.UserRole)
        if isinstance(data, dict):
            self.setText(data.get("batch_no", ""))
            self.batch_selected.emit(data)


    def _resolve_typed_batch(self):
        """If current text matches a saved batch exactly, emit batch_selected."""
        typed = self.text().strip()
        if not typed:
            return
        for r in range(self._model.rowCount()):
            item = self._model.item(r)
            bno = item.data(Qt.UserRole + 1)
            if bno and str(bno).casefold() == typed.casefold():
                data = item.data(Qt.UserRole)
                if isinstance(data, dict):
                    self.setText(data.get("batch_no", ""))
                    self.batch_selected.emit(data)
                break

    def focusOutEvent(self, event):
        popup = self._completer.popup()
        if popup is not None and popup.isVisible():
            popup.hide()
        self._resolve_typed_batch()
        super().focusOutEvent(event)

    def eventFilter(self, obj, event):
        if obj == self and event.type() == QEvent.KeyPress:
            key = event.key()
            popup = self._completer.popup()
            if key == Qt.Key_Escape and popup is not None and popup.isVisible():
                popup.hide()
                return True
            if key in (Qt.Key_Down, Qt.Key_Up):
                if popup is not None and not popup.isVisible():
                    self._completer.setCompletionPrefix(self.text().strip())
                    self._completer.complete()
                    popup.setCurrentIndex(QModelIndex())
                count = self._completer.completionCount()
                if count and popup is not None:
                    current = popup.currentIndex().row()
                    if current < 0:
                        current = 0 if key == Qt.Key_Down else count - 1
                    elif key == Qt.Key_Down:
                        current = min(current + 1, count - 1)
                    else:
                        current = max(current - 1, 0)
                    self._completer.setCurrentRow(current)
                    popup.setCurrentIndex(self._completer.completionModel().index(current, 0))
                return True
            if key in (Qt.Key_Return, Qt.Key_Enter):
                if popup is not None and popup.isVisible():
                    cur = popup.currentIndex()
                    if cur.isValid() and cur.row() >= 0:
                        data = cur.data(Qt.UserRole)
                        if isinstance(data, dict):
                            self.setText(data.get("batch_no", ""))
                            self.batch_selected.emit(data)
                        popup.hide()
                        return True
                    else:
                        popup.hide()
                        self._resolve_typed_batch()
                        return False
                else:
                    self._resolve_typed_batch()
            if key == Qt.Key_Tab:
                if popup is not None and popup.isVisible():
                    cur = popup.currentIndex()
                    if cur.isValid() and cur.row() >= 0:
                        data = cur.data(Qt.UserRole)
                        if isinstance(data, dict):
                            self.setText(data.get("batch_no", ""))
                            self.batch_selected.emit(data)
                        popup.hide()
                        return True
                    popup.hide()
                self._resolve_typed_batch()
        return super().eventFilter(obj, event)


class ExpiryDateEdit(QWidget):
    """Date-picker / calendar control for Expiry Date with DD-MM-YYYY display,
    clear text entry, and calendar popup.
    """

    dateChanged = Signal(QDate)

    def __init__(self, parent: QWidget | None = None, width: int = 108, p: dict | None = None):
        super().__init__(parent)
        self.setObjectName("ExpiryDateEdit")
        self._current_date: QDate | None = None
        self._popup: QDialog | None = None
        self._cal: QCalendarWidget | None = None
        self._read_only: bool = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._line = QLineEdit(self)
        self._line.setPlaceholderText("DD-MM-YYYY")
        self._line.setAlignment(Qt.AlignCenter)
        self._line.setFont(QFont("Segoe UI", 9))
        self._line.editingFinished.connect(self._on_editing_finished)
        layout.addWidget(self._line, 1)

        self._btn = QToolButton(self)
        self._btn.setFocusPolicy(Qt.NoFocus)
        self._btn.setCursor(Qt.PointingHandCursor)
        self._btn.clicked.connect(self.show_popup)
        layout.addWidget(self._btn)

        self.setFixedHeight(30)
        if width:
            self.setFixedWidth(width)

        self._init_calendar()
        self.refresh_theme(p)

    def isReadOnly(self) -> bool:
        return self._read_only

    def setReadOnly(self, ro: bool):
        self._read_only = bool(ro)
        self._line.setReadOnly(self._read_only)
        self._btn.setEnabled(not self._read_only)
        self.refresh_theme()

    def _init_calendar(self):
        self._popup = QDialog(self, Qt.Popup | Qt.FramelessWindowHint)
        self._popup.setAttribute(Qt.WA_DeleteOnClose, False)
        pop_layout = QHBoxLayout(self._popup)
        pop_layout.setContentsMargins(2, 2, 2, 2)
        pop_layout.setSpacing(0)

        self._cal = QCalendarWidget(self._popup)
        self._cal.setGridVisible(True)
        self._cal.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)
        self._cal.clicked.connect(self._on_date_picked)
        pop_layout.addWidget(self._cal)

        today = QDate.currentDate()
        self._cal.setCurrentPage(today.year() + 2, today.month())

    def show_popup(self):
        if self._read_only or not self._popup:
            return
        if self._current_date and self._current_date.isValid():
            self._cal.setSelectedDate(self._current_date)
            self._cal.setCurrentPage(self._current_date.year(), self._current_date.month())
        else:
            today = QDate.currentDate()
            self._cal.setCurrentPage(today.year() + 2, today.month())

        from PySide6.QtWidgets import QApplication
        p = self.mapToGlobal(QPoint(0, self.height()))
        pop_w = 260
        pop_h = 220
        if self._popup.sizeHint().isValid():
            pop_w = max(pop_w, self._popup.sizeHint().width())
            pop_h = max(pop_h, self._popup.sizeHint().height())

        screen = QApplication.screenAt(p) or QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            # If popup would extend below screen bottom, position above widget
            if p.y() + pop_h > geo.bottom():
                p_above = self.mapToGlobal(QPoint(0, -pop_h))
                if p_above.y() >= geo.top():
                    p = p_above
                else:
                    p.setY(max(geo.top(), geo.bottom() - pop_h))
            # If popup would extend past right edge, position within right edge
            if p.x() + pop_w > geo.right():
                p.setX(max(geo.left(), geo.right() - pop_w))

        self._popup.move(p)
        self._popup.show()

    def _on_date_picked(self, qdate: QDate):
        if self._read_only:
            return
        self.setDate(qdate)
        if self._popup:
            self._popup.hide()
        self._line.setFocus()

    def _on_editing_finished(self):
        if self._read_only:
            return
        raw = self._line.text().strip()
        if not raw or raw.upper() == "DD-MM-YYYY":
            self.clear()
            return
        d = parse_expiry_to_date(raw)
        if d:
            self.setDate(QDate(d.year, d.month, d.day))
        else:
            self._current_date = None

    def text(self) -> str:
        return self._line.text().strip()

    def iso_date(self) -> str:
        raw = self._line.text().strip()
        d = parse_expiry_to_date(raw)
        return d.strftime("%Y-%m-%d") if d else ""

    def date(self) -> QDate:
        return self._current_date if self._current_date else QDate(1900, 1, 1)

    def setDate(self, qdate: QDate):
        if qdate and qdate.isValid() and qdate > QDate(1900, 1, 1):
            self._current_date = qdate
            self._line.setText(qdate.toString("dd-MM-yyyy"))
            self.dateChanged.emit(qdate)
        else:
            self.clear()

    def setText(self, text: str):
        if not text:
            self.clear()
            return
        d = parse_expiry_to_date(text)
        if d:
            self.setDate(QDate(d.year, d.month, d.day))
        else:
            self._current_date = None
            self._line.setText(str(text).strip())

    def clear(self):
        self._current_date = None
        self._line.clear()
        if self._cal:
            today = QDate.currentDate()
            self._cal.setCurrentPage(today.year() + 2, today.month())

    def calendarPopup(self) -> bool:
        return True

    def setCalendarPopup(self, enable: bool):
        pass

    def displayFormat(self) -> str:
        return "dd-MM-yyyy"

    def setDisplayFormat(self, fmt: str):
        pass

    def setMinimumDate(self, min_date: QDate):
        pass

    def minimumDate(self) -> QDate:
        return QDate(1900, 1, 1)

    def setSpecialValueText(self, txt: str):
        pass

    def specialValueText(self) -> str:
        return "DD-MM-YYYY"

    def calendarWidget(self) -> QCalendarWidget | None:
        return self._cal

    def lineEdit(self) -> QLineEdit:
        return self._line

    def refresh_theme(self, p: dict | None = None):
        p = p or palette()
        surface = p["surface"]
        text = p["text"]
        border = p["border"]
        accent = p["accent"]
        disabled_bg = p.get("disabled_bg", surface)
        disabled_text = p.get("disabled_text", "#9aa7b4")
        header_bg = p.get("table_header", surface)
        cal_bg = p.get("bg", "#ffffff")
        self._line.setStyleSheet(
            f"QLineEdit {{"
            f"  background-color: {surface}; color: {text};"
            f"  border: 1px solid {border}; border-right: none;"
            f"  border-top-left-radius: 2px; border-bottom-left-radius: 2px;"
            f"  padding: 2px 2px; font-size: 14px; font-weight: bold; font-family: 'Segoe UI';"
            f"}}"
            f"QLineEdit:focus {{ border: 1px solid {accent}; border-right: none; }}"
            f"QLineEdit:read-only {{"
            f"  background-color: {disabled_bg}; color: {text};"
            f"  border: 1px solid {border}; border-right: none;"
            f"}}"
        )
        btn_bg = disabled_bg if self._read_only else header_bg
        self._btn.setStyleSheet(
            f"QToolButton {{"
            f"  background-color: {btn_bg}; color: {text};"
            f"  border: 1px solid {border};"
            f"  border-top-right-radius: 2px; border-bottom-right-radius: 2px;"
            f"  width: 20px; font-size: 10px; font-weight: bold;"
            f"}}"
            f"QToolButton:hover {{ background-color: {accent}; color: white; }}"
            f"QToolButton:disabled {{ background-color: {disabled_bg}; color: {disabled_text}; }}"
        )
        self._btn.setText("▼")
        if self._cal:
            self._cal.setStyleSheet(
                f"QCalendarWidget QWidget {{ background-color: {cal_bg}; color: {text}; font-size: 13px; font-family: 'Segoe UI'; }}"
                f"QCalendarWidget QTableView {{ alternate-background-color: {surface}; background-color: {cal_bg}; color: {text}; selection-background-color: {accent}; selection-color: white; }}"
                f"QCalendarWidget QToolButton {{ background-color: {header_bg}; color: {text}; font-weight: bold; border: 1px solid {border}; border-radius: 2px; }}"
                f"QCalendarWidget QSpinBox {{ background-color: {surface}; color: {text}; border: 1px solid {border}; }}"
            )


class _InvoiceItemRow:
    """Represents one item row in the invoice item table (used for data storage)."""

    def __init__(self, item_id: int, item_name: str, pack_size: str,
                 pay_qty: float, free_qty: float, batch_no: str,
                 expiry: str, rate: float, mrp: float, discount: float,
                 gst_percent: float, amount: float, gst_amount: float,
                 purchase_rate: float, net_rate: float, pp: float,
                 batch_id: int | None = None):
        self.item_id = item_id
        self.item_name = item_name
        self.pack_size = pack_size
        self.pay_qty = pay_qty
        self.free_qty = free_qty
        self.batch_no = batch_no
        self.expiry = expiry
        self.rate = rate
        self.mrp = mrp
        self.discount = discount
        self.gst_percent = gst_percent
        self.amount = amount
        self.gst_amount = gst_amount
        self.purchase_rate = purchase_rate
        self.net_rate = net_rate
        self.pp = pp
        self.batch_id = batch_id

    def to_dict(self) -> dict:
        d = {
            "item_id": self.item_id,
            "pack_size": self.pack_size,
            "pay_qty": self.pay_qty,
            "free_qty": self.free_qty,
            "batch_no": self.batch_no,
            "expiry": normalize_expiry_db(self.expiry) if self.expiry else "",
            "rate": self.rate,
            "mrp": self.mrp,
            "discount": self.discount,
            "gst_percent": self.gst_percent,
            "amount": self.amount,
            "gst_amount": self.gst_amount,
            "purchase_rate": self.purchase_rate,
            "net_rate": self.net_rate,
            "pp": self.pp,
        }
        if self.batch_id is not None:
            d["batch_id"] = self.batch_id
        return d


class _ItemEntryBar(QWidget):
    """Entry bar for adding a single item to the invoice on a single horizontal row."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entry_labels: list[QLabel] = []
        self._selected_batch_no: str = ""
        self._selected_batch_id: int | None = None
        self._selected_batch_data: dict | None = None
        self.get_invoice_date_fn = None

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(2, 2, 2, 2)
        main_layout.setSpacing(3)
        self.setFixedHeight(34)

        # Controls creation
        self.item_combo = SearchableComboBox(
            placeholder="Type item name...",
            max_visible=9,
            max_height=270,
            max_width=650,
            min_width=160,
            allow_width_expansion=True,
        )
        self.item_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.item_combo.setMinimumWidth(160)
        self.item_combo.setFixedHeight(30)
        self.item_combo.setToolTip("Search and select medicine / item")

        self.pack_edit = _make_entry_edit("Pack", 42)
        self.pack_edit.setReadOnly(True)
        self.pack_edit.setFocusPolicy(Qt.NoFocus)
        self.pack_edit.setAlignment(Qt.AlignCenter)
        self.pack_edit.setFixedHeight(30)
        self.pack_edit.setToolTip("Pack size (auto-filled)")

        self.batch_edit = BatchLineEdit("Batch", 82)
        self.batch_edit.setFixedHeight(30)
        self.batch_edit.batch_selected.connect(self._on_saved_batch_selected)
        self.batch_edit.textChanged.connect(self._on_batch_text_changed)

        self.expiry_edit = ExpiryDateEdit(width=100)
        self.expiry_edit.setFixedHeight(30)

        self.pay_qty_edit = _make_entry_edit("0", 44)
        self.pay_qty_edit.setFixedHeight(30)
        self.pay_qty_edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.pay_qty_edit.setToolTip("Payable Quantity")

        self.free_qty_edit = _make_entry_edit("0", 38)
        self.free_qty_edit.setFixedHeight(30)
        self.free_qty_edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.free_qty_edit.setToolTip("Free Quantity")

        self.rate_edit = _make_entry_edit("0.00", 52)
        self.rate_edit.setFixedHeight(30)
        self.rate_edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.rate_edit.setToolTip("Purchase Rate")

        self.mrp_edit = _make_entry_edit("0.00", 52)
        self.mrp_edit.setFixedHeight(30)
        self.mrp_edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.mrp_edit.setToolTip("MRP")

        self.discount_edit = _make_entry_edit("0.00", 42)
        self.discount_edit.setFixedHeight(30)
        self.discount_edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.discount_edit.setToolTip("Discount (%)")

        self.gst_edit = _make_entry_edit("0", 38)
        self.gst_edit.setReadOnly(True)
        self.gst_edit.setFocusPolicy(Qt.NoFocus)
        self.gst_edit.setAlignment(Qt.AlignCenter)
        self.gst_edit.setFixedHeight(30)
        self.gst_edit.setToolTip("GST (%)")

        self.add_btn = QPushButton("+ Add Item")
        self.add_btn.setStyleSheet(_btn_add_item_style())
        self.add_btn.setFixedSize(84, 30)
        self.add_btn.setToolTip("Add item to invoice (Enter)")

        # Single horizontal row layout:
        # Item | Pack | Qty | Free | Batch | Exp | Rate | MRP | Disc | GST | + Add Item
        self.row_layout = main_layout
        self.row1_layout = main_layout  # alias for backward compatibility

        item_field = self._field("Item", self.item_combo, stretch=1)
        main_layout.addWidget(item_field, 1)
        main_layout.addWidget(self._field("Pack", self.pack_edit))
        main_layout.addWidget(self._field("Qty", self.pay_qty_edit))
        main_layout.addWidget(self._field("Free", self.free_qty_edit))
        main_layout.addWidget(self._field("Batch", self.batch_edit))
        main_layout.addWidget(self._field("Exp", self.expiry_edit))
        main_layout.addWidget(self._field("Rate", self.rate_edit))
        main_layout.addWidget(self._field("MRP", self.mrp_edit))
        main_layout.addWidget(self._field("Disc", self.discount_edit))
        main_layout.addWidget(self._field("GST", self.gst_edit))
        main_layout.addWidget(self.add_btn)

        # Set logical tab traversal
        QWidget.setTabOrder(self.item_combo, self.pay_qty_edit)
        QWidget.setTabOrder(self.pay_qty_edit, self.free_qty_edit)
        QWidget.setTabOrder(self.free_qty_edit, self.batch_edit)
        QWidget.setTabOrder(self.batch_edit, self.expiry_edit)
        QWidget.setTabOrder(self.expiry_edit, self.rate_edit)
        QWidget.setTabOrder(self.rate_edit, self.mrp_edit)
        QWidget.setTabOrder(self.mrp_edit, self.discount_edit)
        QWidget.setTabOrder(self.discount_edit, self.add_btn)

        self._load_items()

    def set_batch_fields_readonly(self, ro: bool):
        self.expiry_edit.setReadOnly(ro)
        self.rate_edit.setReadOnly(ro)
        self.mrp_edit.setReadOnly(ro)

    def _on_batch_text_changed(self, text: str):
        curr_saved = getattr(self, "_selected_batch_no", "")
        clean = text.strip()
        if curr_saved and clean.casefold() != curr_saved.casefold():
            self._selected_batch_no = ""
            self._selected_batch_id = None
            self._selected_batch_data = None
            self.set_batch_fields_readonly(False)

    def _field(self, label_text: str, widget: QWidget, label_width: int | None = None, stretch: int = 0) -> QWidget:
        container = QWidget()
        h = QHBoxLayout(container)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(2)
        lbl = QLabel(label_text)
        lbl.setFont(QFont("Segoe UI", 9, QFont.Bold))
        lbl.setStyleSheet(f"color: {_TEXT}; font-size: 11px; font-weight: bold; font-family: 'Segoe UI'; margin: 0; padding: 0; background: transparent;")
        if label_width:
            lbl.setFixedWidth(label_width)
        self._entry_labels.append(lbl)
        h.addWidget(lbl)
        h.addWidget(widget, stretch)
        return container

    def get_invoice_date(self) -> date:
        if callable(getattr(self, "get_invoice_date_fn", None)):
            try:
                return self.get_invoice_date_fn()
            except Exception:
                pass
        return date.today()

    def _on_saved_batch_selected(self, data: dict):
        if not data:
            return
        bno = (data.get("batch_no") or "").strip()
        raw_exp = data.get("expiry")
        exp_d = parse_expiry_to_date(raw_exp)
        inv_d = self.get_invoice_date()

        if exp_d and inv_d and exp_d < inv_d:
            exp_disp = format_expiry_display(exp_d)
            inv_disp = inv_d.strftime("%d-%m-%Y")
            QMessageBox.warning(
                self,
                "Expired Batch",
                f"Batch '{bno}' is expired ({exp_disp}) on invoice date ({inv_disp}).\n\n"
                f"Expired batches cannot be entered in a new purchase invoice.\n"
                f"Please enter a new batch number and valid expiry date.",
            )
            self.batch_edit.clear()
            self.expiry_edit.clear()
            self._selected_batch_no = ""
            self._selected_batch_id = None
            self._selected_batch_data = None
            self.set_batch_fields_readonly(False)
            return

        self._selected_batch_no = bno
        self._selected_batch_id = data.get("id") or data.get("batch_id")
        self._selected_batch_data = data
        if bno:
            self.batch_edit.setText(bno)
        if raw_exp:
            self.expiry_edit.setText(format_expiry_display(raw_exp))
        else:
            self.expiry_edit.clear()
        if data.get("rate") is not None and float(data.get("rate") or 0.0) > 0:
            self.rate_edit.setText(f"{float(data['rate']):.2f}")
        if data.get("mrp") is not None and float(data.get("mrp") or 0.0) > 0:
            self.mrp_edit.setText(f"{float(data['mrp']):.2f}")
        if data.get("pack_size"):
            self.pack_edit.setText(str(data["pack_size"]).strip())
        if data.get("gst_percent") is not None and float(data.get("gst_percent") or 0.0) >= 0:
            self.gst_edit.setText(f"{float(data['gst_percent']):g}")
        self.set_batch_fields_readonly(True)

    def _load_items(self):
        try:
            items = ItemDAO.get_all()
        except Exception:
            items = []
        list_items = []
        for it in items:
            list_items.append((it["item_name"], it["id"]))
        self.item_combo.populate(list_items)

    def clear(self):
        self._selected_batch_no = ""
        self._selected_batch_id = None
        self._selected_batch_data = None
        self.item_combo.clear_selection()
        self.pack_edit.clear()
        self.pay_qty_edit.clear()
        self.free_qty_edit.clear()
        self.batch_edit.clear()
        self.batch_edit.set_batches([])
        self.expiry_edit.clear()
        self.rate_edit.clear()
        self.mrp_edit.clear()
        self.discount_edit.clear()
        self.gst_edit.clear()
        self.set_batch_fields_readonly(False)

    def refresh_theme(self, p: dict | None = None):
        p = p or palette()
        self.item_combo.refresh_theme(p)
        self.batch_edit.refresh_theme(p)
        self.expiry_edit.refresh_theme(p)
        edit_st = _entry_edit_style(p)
        for w in (self.pack_edit,
                  self.pay_qty_edit, self.free_qty_edit, self.rate_edit,
                  self.mrp_edit, self.discount_edit, self.gst_edit):
            w.setStyleSheet(edit_st)
        self.add_btn.setStyleSheet(_btn_add_item_style(p))
        lbl_st = f"color: {p['text']}; font-size: 12px; font-weight: bold; font-family: 'Segoe UI'; background: transparent;"
        for lbl in self._entry_labels:
            lbl.setStyleSheet(lbl_st)

    def get_current_item_data(self) -> dict | None:
        item_id = self.item_combo.currentData()
        if item_id is None:
            return None
        item_full = ItemDAO.get_by_id(item_id)
        if not item_full:
            return None
        item_name = item_full.get("item_name") or self.item_combo.currentText()
        expiry_val = self.expiry_edit.iso_date() or self.expiry_edit.text().strip()
        return {
            "item_id": item_id,
            "item_name": item_name,
            "pack_size": self.pack_edit.text().strip() or item_full.get("pack_size", ""),
            "pay_qty": _safe_float(self.pay_qty_edit.text()),
            "free_qty": _safe_float(self.free_qty_edit.text()),
            "batch_no": self.batch_edit.text().strip(),
            "batch_id": getattr(self, "_selected_batch_id", None),
            "expiry": expiry_val,
            "rate": _safe_float(self.rate_edit.text()),
            "mrp": _safe_float(self.mrp_edit.text()),
            "discount": _safe_float(self.discount_edit.text()),
            "gst_percent": _safe_float(self.gst_edit.text()),
            "item_full": item_full,
        }


class _InvoiceDialog(QDialog):
    """Modal dialog for entering / editing a purchase invoice."""

    def __init__(self, parent: QWidget | None = None, *, invoice: dict | None = None):
        super().__init__(parent)
        self._invoice = invoice
        self._saved = False
        self._item_rows: list[_InvoiceItemRow] = []

        self.setWindowTitle("Edit Purchase Invoice" if invoice else "New Purchase Invoice")
        self.setMinimumWidth(1200)
        self.setMinimumHeight(700)
        self.setModal(True)

        from PySide6.QtWidgets import QApplication
        screen = QApplication.primaryScreen()
        if screen:
            sg = screen.availableGeometry()
            w = int(sg.width() * 0.90)
            h = int(sg.height() * 0.85)
            self.resize(max(w, 1200), max(h, 700))
            self.move(
                sg.x() + (sg.width() - self.width()) // 2,
                sg.y() + (sg.height() - self.height()) // 2,
            )

        self.setStyleSheet(
            f"QDialog {{ background-color: {_DARK_BG}; }}"
            f"QLabel {{ {_LABEL_STYLE} }}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 1. Cyan Blue Header Strip (#00c0fe)
        self._build_header_strip(root)

        # 2. Top area: Header form + item entry
        top = QWidget()
        top_layout = QVBoxLayout(top)
        top_layout.setContentsMargins(8, 6, 8, 2)
        top_layout.setSpacing(4)

        # Header fields
        self._build_header(top_layout)

        # Item entry bar
        self._entry_bar = _ItemEntryBar(self)
        self._entry_bar.get_invoice_date_fn = self.get_invoice_date
        top_layout.addWidget(self._entry_bar)

        root.addWidget(top)

        # 3. Item table (17 columns with #)
        self._build_item_table()
        root.addWidget(self._table_group, 1)

        # 4. Totals + action buttons (combined footer)
        self._build_totals()
        root.addWidget(self._totals_widget)

        # Wire entry bar add button
        self._entry_bar.item_combo.currentIndexChanged.connect(self._on_item_changed)
        self._entry_bar.rate_edit.textChanged.connect(self._recalc_current_line)
        self._entry_bar.mrp_edit.textChanged.connect(self._recalc_current_line)
        self._entry_bar.discount_edit.textChanged.connect(self._recalc_current_line)
        self._entry_bar.gst_edit.textChanged.connect(self._recalc_current_line)
        self._entry_bar.pay_qty_edit.textChanged.connect(self._recalc_current_line)
        self._entry_bar.free_qty_edit.textChanged.connect(self._recalc_current_line)

        # Wire add button inside entry bar
        if hasattr(self._entry_bar, "add_btn"):
            self._entry_bar.add_btn.clicked.connect(self._on_add_item)
        else:
            for child in self._entry_bar.findChildren(QPushButton):
                if "+ Add" in child.text():
                    child.clicked.connect(self._on_add_item)
                    break
        self._entry_bar.discount_edit.returnPressed.connect(self._on_add_item)
        self._entry_bar.gst_edit.returnPressed.connect(self._on_add_item)

        self._set_voucher_no()
        self._set_current_datetime()

        # Wire totals auto-recalc for all modes (new + edit)
        self._wire_totals_recalc()

        if invoice:
            self._populate_invoice(invoice)

    # ------------------------------------------------------------------
    # Header Strip (Cyan #00c0fe)
    # ------------------------------------------------------------------

    def _build_header_strip(self, parent_layout: QVBoxLayout):
        strip = QWidget()
        strip.setFixedHeight(34)
        strip.setStyleSheet("background-color: #00c0fe; border-top-left-radius: 4px; border-top-right-radius: 4px;")
        layout = QHBoxLayout(strip)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(10)

        self._header_title_lbl = QLabel("Edit Invoice" if self._invoice else "New Invoice")
        self._header_title_lbl.setStyleSheet("color: #000000; font-size: 15px; font-weight: bold; font-family: 'Segoe UI'; background: transparent;")
        layout.addWidget(self._header_title_lbl)

        layout.addStretch(1)

        # Voucher No
        lbl_v = QLabel("Voucher No")
        lbl_v.setStyleSheet("color: #000000; font-size: 13px; font-weight: bold; font-family: 'Segoe UI'; background: transparent;")
        layout.addWidget(lbl_v)
        self.voucher_no_edit = QLineEdit()
        self.voucher_no_edit.setReadOnly(True)
        self.voucher_no_edit.setFixedSize(65, 24)
        self.voucher_no_edit.setAlignment(Qt.AlignCenter)
        self.voucher_no_edit.setStyleSheet("background: #ffffff; color: #000000; border: 1px solid #7eaadb; font-size: 13px; font-weight: bold;")
        layout.addWidget(self.voucher_no_edit)

        # Date
        lbl_d = QLabel("Date")
        lbl_d.setStyleSheet("color: #000000; font-size: 13px; font-weight: bold; font-family: 'Segoe UI'; background: transparent;")
        layout.addWidget(lbl_d)
        self.voucher_date = _make_date()
        self.voucher_date.setFixedSize(110, 24)
        layout.addWidget(self.voucher_date)

        # Time
        lbl_t = QLabel("Time")
        lbl_t.setStyleSheet("color: #000000; font-size: 13px; font-weight: bold; font-family: 'Segoe UI'; background: transparent;")
        layout.addWidget(lbl_t)
        self.voucher_time_edit = QLineEdit()
        self.voucher_time_edit.setFixedSize(80, 24)
        self.voucher_time_edit.setAlignment(Qt.AlignCenter)
        self.voucher_time_edit.setStyleSheet("background: #ffffff; color: #000000; border: 1px solid #7eaadb; font-size: 13px;")
        layout.addWidget(self.voucher_time_edit)

        parent_layout.addWidget(strip)

    # ------------------------------------------------------------------
    # Header Form
    # ------------------------------------------------------------------

    def _build_header(self, parent_layout: QVBoxLayout):
        grp = QGroupBox("Invoice Header")
        grp.setStyleSheet(_GROUP_BOX)
        form_layout = QHBoxLayout(grp)
        form_layout.setContentsMargins(10, 10, 10, 8)
        form_layout.setSpacing(16)

        # Left Column: Type, Date
        left_col = QWidget()
        left_grid = QGridLayout(left_col)
        left_grid.setContentsMargins(0, 0, 0, 0)
        left_grid.setSpacing(6)

        lbl_type = self._lbl("Type :")
        self.purchase_type_combo = _make_combo(max_visible=5, max_height=160)
        self.purchase_type_combo.addItems(["Credit", "Cash", "Credit Card"])
        self.purchase_type_combo.setFixedWidth(112)
        self.purchase_type_combo.currentTextChanged.connect(self._on_purchase_type_changed)
        left_grid.addWidget(lbl_type, 0, 0, Qt.AlignRight | Qt.AlignVCenter)
        left_grid.addWidget(self.purchase_type_combo, 0, 1)

        lbl_date = self._lbl("Date :")
        self.invoice_date = _make_date()
        self.invoice_date.setFixedWidth(118)
        self.invoice_date.dateChanged.connect(self._on_invoice_date_changed)
        left_grid.addWidget(lbl_date, 1, 0, Qt.AlignRight | Qt.AlignVCenter)
        left_grid.addWidget(self.invoice_date, 1, 1)
        form_layout.addWidget(left_col)

        # Middle Column: Supplier, Edit, Balance, Invoice #, Inv Net Amt
        mid_col = QWidget()
        mid_grid = QGridLayout(mid_col)
        mid_grid.setContentsMargins(0, 0, 0, 0)
        mid_grid.setSpacing(6)

        lbl_sup = self._lbl("Supplier :")
        mid_grid.addWidget(lbl_sup, 0, 0, Qt.AlignRight | Qt.AlignVCenter)

        sup_row = QHBoxLayout()
        sup_row.setContentsMargins(0, 0, 0, 0)
        sup_row.setSpacing(4)
        self.supplier_combo = SearchableComboBox(
            placeholder="Type supplier name...",
            max_visible=9,
            max_height=270,
            max_width=450,
            min_width=240,
            allow_width_expansion=True,
        )
        sup_row.addWidget(self.supplier_combo, 1)

        self.btn_supplier_edit = QPushButton("Edit")
        self.btn_supplier_edit.setFixedSize(36, 26)
        self.btn_supplier_edit.setStyleSheet(
            "QPushButton { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #ffffff, stop:1 #dbe7f5); border: 1px solid #7eaadb; border-radius: 2px; color: #0a3663; font-size: 11px; font-weight: bold; } QPushButton:hover { background: #cde2f8; }"
        )
        self.btn_supplier_edit.setToolTip("Edit selected supplier master")
        self.btn_supplier_edit.setFocusPolicy(Qt.NoFocus)
        self.btn_supplier_edit.clicked.connect(self._on_edit_supplier)
        sup_row.addWidget(self.btn_supplier_edit)

        self.sup_bal_prefix = QLabel("(Balance=")
        self.sup_bal_prefix.setStyleSheet(f"color: {_TEXT}; font-size: 13px; font-weight: bold; background: transparent;")
        sup_row.addWidget(self.sup_bal_prefix)

        self.supplier_bal_label = QLabel("0.00")
        self.supplier_bal_label.setStyleSheet(f"color: {_TEXT}; font-size: 13px; font-weight: bold; background: transparent;")
        sup_row.addWidget(self.supplier_bal_label)

        self.sup_bal_suffix = QLabel(")")
        self.sup_bal_suffix.setStyleSheet(f"color: {_TEXT}; font-size: 13px; font-weight: bold; background: transparent;")
        sup_row.addWidget(self.sup_bal_suffix)

        mid_grid.addLayout(sup_row, 0, 1)

        # Row 1 of Middle: Invoice # and Inv Net Amt
        inv_row = QHBoxLayout()
        inv_row.setContentsMargins(0, 0, 0, 0)
        inv_row.setSpacing(6)

        lbl_inv_no = self._lbl("Invoice # :")
        inv_row.addWidget(lbl_inv_no)
        self.invoice_no_edit = _make_edit(width=110)
        inv_row.addWidget(self.invoice_no_edit)

        lbl_inv_amt = self._lbl("Inv Net Amt :")
        inv_row.addWidget(lbl_inv_amt)
        self.inv_net_amt_edit = _make_edit("0.00", width=105)
        self.inv_net_amt_edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        inv_row.addWidget(self.inv_net_amt_edit)
        inv_row.addStretch(1)

        mid_grid.addLayout(inv_row, 1, 1)
        form_layout.addWidget(mid_col, 1)

        # Right Column: Discount, Due Date
        right_col = QWidget()
        right_grid = QGridLayout(right_col)
        right_grid.setContentsMargins(0, 0, 0, 0)
        right_grid.setSpacing(6)

        lbl_disc = self._lbl("Discount :")
        right_grid.addWidget(lbl_disc, 0, 0, Qt.AlignRight | Qt.AlignVCenter)

        disc_row = QHBoxLayout()
        disc_row.setContentsMargins(0, 0, 0, 0)
        disc_row.setSpacing(2)
        self.bill_disc_type_combo = _make_combo()
        self.bill_disc_type_combo.addItems(["Rs", "%"])
        self.bill_disc_type_combo.setFixedSize(50, 26)
        disc_row.addWidget(self.bill_disc_type_combo)
        self.bill_discount_edit = _make_edit("0.00", width=85)
        self.bill_discount_edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.bill_discount_edit.textChanged.connect(self._sync_header_to_footer_disc)
        disc_row.addWidget(self.bill_discount_edit)
        right_grid.addLayout(disc_row, 0, 1)

        lbl_due = self._lbl("Due Date :")
        right_grid.addWidget(lbl_due, 1, 0, Qt.AlignRight | Qt.AlignVCenter)
        self.due_date = _make_date(parent=self)
        self.due_date.setFixedWidth(118)
        right_grid.addWidget(self.due_date, 1, 1)
        form_layout.addWidget(right_col)

        parent_layout.addWidget(grp)
        self._load_suppliers()

    def _on_edit_supplier(self):
        sid = self.supplier_combo.currentData()
        if not sid:
            QMessageBox.information(self, "Edit Supplier", "Please select a supplier first.")
            return
        try:
            from screens.supplier_master import _SupplierDialog
            dlg = _SupplierDialog(self, supplier_id=sid)
            if dlg.exec():
                self._load_suppliers()
                idx = self.supplier_combo.findData(sid)
                if idx >= 0:
                    self.supplier_combo.setCurrentIndex(idx)
                self._update_supplier_balance(sid)
        except Exception as exc:
            QMessageBox.warning(self, "Edit Supplier", f"Could not edit supplier: {exc}")

    def _load_suppliers(self):
        try:
            suppliers = SupplierDAO.get_all()
        except Exception:
            suppliers = []
        list_suppliers = []
        for s in suppliers:
            list_suppliers.append((s["supplier_name"], s["id"]))
        self.supplier_combo.populate(list_suppliers)
        self.supplier_combo.currentIndexChanged.connect(self._on_supplier_changed)
        line = self.supplier_combo.lineEdit()
        if line is not None:
            line.textChanged.connect(self._on_supplier_text_changed)

    def _on_supplier_text_changed(self, text: str):
        self._on_supplier_changed()

    def _on_supplier_changed(self, idx: int = -1):
        sid = self.supplier_combo.currentData()
        self._update_supplier_balance(sid)
        if sid:
            sup = SupplierDAO.get_by_id(sid)
            if sup and not self._invoice:
                credit_days = sup.get("credit_period")
                try:
                    days = int(credit_days) if credit_days is not None else 0
                except (ValueError, TypeError):
                    days = 0
                inv_date = self.invoice_date.date()
                if days > 0:
                    self.due_date.setDate(inv_date.addDays(days))
                else:
                    self.due_date.setDate(inv_date.addDays(30))

    def _update_supplier_balance(self, sid: int | None):
        if not sid:
            self.supplier_bal_label.setText("0.00")
            self.supplier_bal_label.setToolTip("")
            p = palette()
            self.supplier_bal_label.setStyleSheet(
                f"color: {p.get('text_dim', _TEXT_DIM)}; font-size: 13px; font-weight: bold; background: transparent;"
                f"font-family: 'Segoe UI'; padding: 2px;"
            )
            return

        try:
            sup = SupplierDAO.get_by_id(sid)
            if not sup:
                self.supplier_bal_label.setText("Error")
                self.supplier_bal_label.setToolTip("Supplier record not found in database")
                p = palette()
                self.supplier_bal_label.setStyleSheet(
                    f"color: {p.get('danger', '#c62828')}; font-size: 13px; font-weight: bold; background: transparent;"
                    f"font-family: 'Segoe UI'; padding: 2px;"
                )
                return

            ledger_id = sup.get("ledger_id")
            if not ledger_id:
                ledger_id = SupplierDAO.get_ledger_id(sid)

            if not ledger_id:
                self.supplier_bal_label.setText("N/A")
                self.supplier_bal_label.setToolTip("No linked account ledger found for this supplier")
                p = palette()
                self.supplier_bal_label.setStyleSheet(
                    f"color: {p.get('danger', '#c62828')}; font-size: 13px; font-weight: bold; background: transparent;"
                    f"font-family: 'Segoe UI'; padding: 2px;"
                )
                return

            bal = LedgerDAO.get_balance(ledger_id)
            closing = float(bal.get("closing_balance", 0.0) or 0.0)
            closing_type = bal.get("closing_balance_type", "Credit")

            if abs(closing) < 1e-9:
                self.supplier_bal_label.setText("0.00")
            else:
                sign = 1.0 if closing_type == "Credit" else -1.0
                outstanding = closing * sign
                self.supplier_bal_label.setText(f"{outstanding:,.2f}")

            self.supplier_bal_label.setToolTip(f"Closing Balance: {closing:,.2f} ({closing_type})")
            p = palette()
            self.supplier_bal_label.setStyleSheet(
                f"color: {p.get('text_dim', _TEXT_DIM)}; font-size: 13px; font-weight: bold; background: transparent;"
                f"font-family: 'Segoe UI'; padding: 2px;"
            )
        except Exception as exc:
            self.supplier_bal_label.setText("Error")
            self.supplier_bal_label.setToolTip(f"Failed to retrieve ledger balance: {exc}")
            p = palette()
            self.supplier_bal_label.setStyleSheet(
                f"color: {p.get('danger', '#c62828')}; font-size: 13px; font-weight: bold; background: transparent;"
                f"font-family: 'Segoe UI'; padding: 2px;"
            )

    def get_invoice_date(self) -> date:
        try:
            qd = self.invoice_date.date()
            return date(qd.year(), qd.month(), qd.day())
        except Exception:
            return date.today()

    def _on_invoice_date_changed(self, new_date: QDate):
        if not self._invoice:
            sid = self.supplier_combo.currentData()
            days = 0
            if sid:
                sup = SupplierDAO.get_by_id(sid)
                if sup:
                    try:
                        days = int(sup.get("credit_period") or 0)
                    except (ValueError, TypeError):
                        days = 0
            if days > 0:
                self.due_date.setDate(new_date.addDays(days))
            else:
                self.due_date.setDate(new_date.addDays(30))

        item_id = self._entry_bar.item_combo.currentData()
        if item_id:
            try:
                batches = PurchaseDAO.get_saved_batches_for_item(item_id)
                if not isinstance(batches, list):
                    batches = []
            except Exception:
                batches = []
            self._entry_bar.batch_edit.set_batches(batches, invoice_date=self.get_invoice_date())

    def _sync_header_to_footer_disc(self, text: str):
        if hasattr(self, "bill_disc_edit") and self.bill_disc_edit.text() != text:
            self.bill_disc_edit.blockSignals(True)
            self.bill_disc_edit.setText(text)
            self.bill_disc_edit.blockSignals(False)
            self._recalc_totals()

    def _sync_footer_to_header_disc(self, text: str):
        if hasattr(self, "bill_discount_edit") and self.bill_discount_edit.text() != text:
            self.bill_discount_edit.blockSignals(True)
            self.bill_discount_edit.setText(text)
            self.bill_discount_edit.blockSignals(False)
            self._recalc_totals()

    def _on_purchase_type_changed(self, new_type: str):
        if not self._invoice:
            self._set_voucher_no()

    def _set_voucher_no(self):
        if not self._invoice:
            ptype = self.purchase_type_combo.currentText() if hasattr(self, "purchase_type_combo") else "Credit"
            full = PurchaseDAO.generate_next_voucher_no(purchase_type=ptype)
            self._full_voucher_no = full
            self.voucher_no_edit.setText(_display_voucher_no(full))
            self.voucher_no_edit.setToolTip(f"Full Voucher: {full}")

    def _set_current_datetime(self):
        now = datetime.now()
        today = QDate(now.year, now.month, now.day)
        self.voucher_date.setDate(today)
        from core.doc_formatter import format_time_12hr
        self.voucher_time_edit.setText(format_time_12hr(now.strftime("%H:%M")))
        self.invoice_date.setDate(today)
        self.due_date.setDate(today.addDays(30))

    # ------------------------------------------------------------------
    # Item Table (17 columns with #)
    # ------------------------------------------------------------------

    def _build_item_table(self):
        self._table_group = QGroupBox("Items")
        self._table_group.setStyleSheet(_GROUP_BOX)
        layout = QVBoxLayout(self._table_group)
        layout.setContentsMargins(6, 12, 6, 6)

        self._table = QTableWidget()
        self._table.setColumnCount(17)
        self._table.setHorizontalHeaderLabels([
            "#", "Item Name", "Pack", "Pay Qty", "Free", "Batch",
            "Exp", "Rate", "MRP", "Disc", "Amount", "GST%",
            "GST Amt", "Pur Rate", "Net Rate", "PP", "Del"
        ])
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(True)
        self._table.setAlternatingRowColors(False)

        hv = self._table.horizontalHeader()
        hv.setStretchLastSection(False)
        hv.setSectionResizeMode(1, QHeaderView.Stretch)

        col_widths = {
            0: 42,   # #
            2: 60,   # Pack
            3: 85,   # Pay Qty
            4: 65,   # Free
            5: 135,  # Batch
            6: 95,   # Exp
            7: 95,   # Rate
            8: 95,   # MRP
            9: 65,   # Disc
            10: 120, # Amount
            11: 65,  # GST%
            12: 100, # GST Amt
            13: 100, # Pur Rate
            14: 100, # Net Rate
            15: 115, # PP
            16: 55,  # Del
        }
        for col, width in col_widths.items():
            hv.setSectionResizeMode(col, QHeaderView.Interactive)
            self._table.setColumnWidth(col, width)

        hv.setStyleSheet(
            f"QHeaderView::section {{"
            f"  background-color: {_SURFACE}; color: {_TEXT};"
            f"  border: none; border-bottom: 2px solid {_ACCENT};"
            f"  padding: 2px 5px; font-weight: bold; font-size: 15px;"
            f"  font-family: 'Segoe UI';"
            f"}}"
        )
        self._table.setStyleSheet(
            f"QTableWidget {{"
            f"  background-color: {_DARK_BG}; color: {_TEXT};"
            f"  border: 1px solid {_BORDER}; gridline-color: {_BORDER};"
            f"  font-size: 15px; font-family: 'Segoe UI';"
            f"  selection-background-color: {_ACCENT};"
            f"  selection-color: white;"
            f"}}"
            f"QTableWidget::item {{ padding: 2px; }}"
        )
        layout.addWidget(self._table, 1)

    def _on_item_changed(self, idx: int):
        item_id = self._entry_bar.item_combo.currentData()
        if item_id is None:
            self._entry_bar._selected_batch_no = ""
            self._entry_bar._selected_batch_id = None
            self._entry_bar._selected_batch_data = None
            self._entry_bar.batch_edit.clear()
            self._entry_bar.batch_edit.set_batches([])
            self._entry_bar.expiry_edit.clear()
            self._entry_bar.pack_edit.clear()
            self._entry_bar.gst_edit.clear()
            self._entry_bar.pay_qty_edit.clear()
            self._entry_bar.free_qty_edit.clear()
            self._entry_bar.rate_edit.clear()
            self._entry_bar.mrp_edit.clear()
            self._entry_bar.discount_edit.clear()
            self._entry_bar.set_batch_fields_readonly(False)
            return
        item = ItemDAO.get_by_id(item_id)
        if item:
            self._entry_bar.pack_edit.setText(str(item.get("pack_size", "") or ""))
            tax = item.get("tax_structure", "")
            percent = rate_percent(tax, item.get("legacy_tax_id"))
            if percent is None and isinstance(tax, str):
                m = re.search(r"GST\s*@?\s*(\d+(?:\.\d+)?)", tax, re.I) or re.search(r"(\d+(?:\.\d+)?)\s*%", tax)
                if m:
                    candidate = m.group(1)
                    p = rate_percent(candidate)
                    if p is not None:
                        percent = p
                    else:
                        try:
                            val = float(candidate)
                            if str(int(val)) in ("0", "5", "12", "18", "28"):
                                percent = val
                        except ValueError:
                            pass
            self._entry_bar.gst_edit.setText(f"{percent:g}" if percent is not None else "0")

            self._entry_bar._selected_batch_no = ""
            self._entry_bar._selected_batch_id = None
            self._entry_bar._selected_batch_data = None
            self._entry_bar.mrp_edit.setText(f"{float(item.get('mrp', 0.0) or 0.0):.2f}")
            self._entry_bar.rate_edit.setText(f"{float(item.get('rate', 0.0) or 0.0):.2f}")
            self._entry_bar.batch_edit.clear()
            self._entry_bar.expiry_edit.clear()
            self._entry_bar.pay_qty_edit.clear()
            self._entry_bar.free_qty_edit.clear()
            self._entry_bar.discount_edit.clear()
            self._entry_bar.set_batch_fields_readonly(False)

            try:
                batches = PurchaseDAO.get_saved_batches_for_item(item_id)
                if not isinstance(batches, list):
                    batches = []
            except Exception:
                batches = []
            self._entry_bar.batch_edit.set_batches(batches, invoice_date=self.get_invoice_date())

    def _recalc_current_line(self):
        pass

    def _on_add_item(self):
        data = self._entry_bar.get_current_item_data()
        if data is None:
            QMessageBox.warning(self, "Validation", "Please select a valid item from the list.")
            return

        pay_qty = data["pay_qty"]
        free_qty = data["free_qty"]
        rate = data["rate"]
        discount = data["discount"]
        gst_pct = data["gst_percent"]

        if pay_qty <= 0:
            QMessageBox.warning(self, "Validation", "Pay Quantity must be greater than 0.")
            return

        batch_no = data["batch_no"]
        if not batch_no:
            QMessageBox.warning(self, "Validation", "Batch Number is required.")
            return

        inv_d = self.get_invoice_date()
        raw_expiry = self._entry_bar.expiry_edit.text().strip()
        if raw_expiry and raw_expiry.upper() != "DD-MM-YYYY":
            parsed_d = parse_expiry_to_date(raw_expiry)
            if not parsed_d:
                QMessageBox.warning(
                    self,
                    "Validation",
                    f"Invalid Expiry Date '{raw_expiry}'.\nPlease enter a valid date in DD-MM-YYYY or MM/YY format.",
                )
                return
            if parsed_d < inv_d:
                exp_disp = parsed_d.strftime("%d-%m-%Y")
                inv_disp = inv_d.strftime("%d-%m-%Y")
                QMessageBox.warning(
                    self,
                    "Expired Stock",
                    f"Batch '{batch_no}' is expired ({exp_disp}) on invoice date ({inv_disp}).\n\n"
                    f"Expired stock cannot be added to a new purchase invoice.",
                )
                return

        eff_expiry = data.get("expiry") or raw_expiry
        if eff_expiry and eff_expiry.upper() != "DD-MM-YYYY":
            parsed_d = parse_expiry_to_date(eff_expiry)
            if parsed_d and parsed_d < inv_d:
                exp_disp = parsed_d.strftime("%d-%m-%Y")
                inv_disp = inv_d.strftime("%d-%m-%Y")
                QMessageBox.warning(
                    self,
                    "Expired Stock",
                    f"Batch '{batch_no}' is expired ({exp_disp}) on invoice date ({inv_disp}).\n\n"
                    f"Expired stock cannot be added to a new purchase invoice.",
                )
                return

        if rate < 0:
            QMessageBox.warning(self, "Validation", "Rate cannot be negative.")
            return

        if data["mrp"] < 0:
            QMessageBox.warning(self, "Validation", "MRP cannot be negative.")
            return

        if gst_pct < 0:
            QMessageBox.warning(self, "Validation", "GST percentage cannot be negative.")
            return

        disc_pct = _d(discount)
        gross = _d(pay_qty) * _d(rate)
        disc_amt = gross * disc_pct / _d(100) if disc_pct else _d(0)
        amount = _round2(gross - disc_amt)
        gst_amount = _round2(amount * gst_pct / 100.0)
        total_for_line = _round2(_d(amount) + _d(gst_amount))

        qty_total = pay_qty + free_qty
        purchase_rate = _round2(total_for_line / pay_qty) if pay_qty else 0.0
        net_rate = _round2(total_for_line / qty_total) if qty_total else 0.0

        mrp_val = float(data.get("mrp") or 0.0)
        if purchase_rate > 0 and mrp_val > purchase_rate:
            calc_pp = round(((mrp_val - purchase_rate) / purchase_rate) * 100.0, 2)
            if abs(calc_pp - 25.0) < 0.1 or abs(calc_pp - round(calc_pp)) < 0.05:
                pp = float(round(calc_pp))
            else:
                pp = calc_pp
        else:
            pp = 25.0

        row = _InvoiceItemRow(
            item_id=data["item_id"],
            item_name=data["item_name"],
            pack_size=data["pack_size"],
            pay_qty=pay_qty,
            free_qty=free_qty,
            batch_no=batch_no,
            expiry=normalize_expiry_db(data["expiry"]) if data["expiry"] else "",
            rate=rate,
            mrp=data["mrp"],
            discount=discount,
            gst_percent=gst_pct,
            amount=amount,
            gst_amount=gst_amount,
            purchase_rate=purchase_rate,
            net_rate=net_rate,
            pp=pp,
            batch_id=data.get("batch_id"),
        )
        self._item_rows.append(row)
        self._refresh_table()
        self._recalc_totals()
        self._entry_bar.clear()

    def _refresh_table(self):
        self._table.setRowCount(len(self._item_rows))
        for i, r in enumerate(self._item_rows):
            def _item(text: str, align: Qt.AlignmentFlag = Qt.AlignLeft | Qt.AlignVCenter) -> QTableWidgetItem:
                it = QTableWidgetItem(text)
                it.setTextAlignment(align)
                return it

            self._table.setItem(i, 0, _item(str(i + 1), Qt.AlignCenter))
            item_w = _item(r.item_name, Qt.AlignLeft | Qt.AlignVCenter)
            item_w.setToolTip(r.item_name)
            self._table.setItem(i, 1, item_w)
            self._table.setItem(i, 2, _item(r.pack_size, Qt.AlignCenter))
            self._table.setItem(i, 3, _item(f"{r.pay_qty:g}", Qt.AlignRight | Qt.AlignVCenter))
            self._table.setItem(i, 4, _item(f"{r.free_qty:g}", Qt.AlignRight | Qt.AlignVCenter))
            batch_w = _item(r.batch_no, Qt.AlignCenter)
            batch_w.setToolTip(r.batch_no)
            self._table.setItem(i, 5, batch_w)
            self._table.setItem(i, 6, _item(format_expiry_display(r.expiry), Qt.AlignCenter))
            self._table.setItem(i, 7, _item(f"{r.rate:.2f}", Qt.AlignRight | Qt.AlignVCenter))
            self._table.setItem(i, 8, _item(f"{r.mrp:.2f}", Qt.AlignRight | Qt.AlignVCenter))
            self._table.setItem(i, 9, _item(f"{r.discount:.2f}", Qt.AlignRight | Qt.AlignVCenter))
            self._table.setItem(i, 10, _item(f"{r.amount:.2f}", Qt.AlignRight | Qt.AlignVCenter))
            self._table.setItem(i, 11, _item(f"{r.gst_percent:g}", Qt.AlignRight | Qt.AlignVCenter))
            self._table.setItem(i, 12, _item(f"{r.gst_amount:.2f}", Qt.AlignRight | Qt.AlignVCenter))
            self._table.setItem(i, 13, _item(f"{r.purchase_rate:.2f}", Qt.AlignRight | Qt.AlignVCenter))
            self._table.setItem(i, 14, _item(f"{r.net_rate:.2f}", Qt.AlignRight | Qt.AlignVCenter))
            pp_disp = f"{int(r.pp)}" if (isinstance(r.pp, (int, float)) and r.pp == int(r.pp)) else f"{r.pp:.2f}"
            self._table.setItem(i, 15, _item(pp_disp, Qt.AlignRight | Qt.AlignVCenter))

            del_btn = QPushButton("×")
            del_btn.setStyleSheet(_BTN_DANGER)
            del_btn.setFixedSize(28, 24)
            del_btn.setToolTip("Remove item")
            del_btn.clicked.connect(lambda _, idx=i: self._delete_item(idx))

            cell = QWidget()
            cell_layout = QHBoxLayout(cell)
            cell_layout.setContentsMargins(0, 0, 0, 0)
            cell_layout.setAlignment(Qt.AlignCenter)
            cell_layout.addWidget(del_btn)
            self._table.setCellWidget(i, 16, cell)

    def _delete_item(self, idx: int):
        if 0 <= idx < len(self._item_rows):
            self._item_rows.pop(idx)
            self._refresh_table()
            self._recalc_totals()
            self._entry_bar.clear()

    # ------------------------------------------------------------------
    # Totals (Combined Footer Bar)
    # ------------------------------------------------------------------

    def _build_totals(self):
        self._totals_widget = QWidget()
        self._totals_widget.setFixedHeight(70)
        self._totals_widget.setStyleSheet(
            f"background-color: {_SURFACE}; border-top: 1px solid {_BORDER};"
        )
        layout = QHBoxLayout(self._totals_widget)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(10)

        self._add_total_field(layout, "Total Amt", "total_amount_label")
        self._add_total_field(layout, "+ GST", "gst_label")
        self._add_total_field(layout, "- Bill Disc", "bill_disc_edit")
        self._add_total_field(layout, "- DN Amt", "dn_edit")
        self._add_total_field(layout, "+ Other", "other_edit")
        self._add_total_field(layout, "Paid", "paid_edit")
        self._add_total_field(layout, "Round Off", "round_off_edit")
        self._add_total_field(layout, "NET AMT", "net_amt_label")

        layout.addStretch(1)

        save_btn = QPushButton("Save Invoice")
        save_btn.setStyleSheet(_BTN_SAVE)
        save_btn.setFixedSize(125, 36)
        save_btn.clicked.connect(self._on_save)
        self.save_btn = save_btn
        layout.addWidget(save_btn, 0, Qt.AlignVCenter)

        layout.addSpacing(10)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(_BTN_SECONDARY)
        cancel_btn.setFixedSize(95, 36)
        cancel_btn.clicked.connect(self.reject)
        self.cancel_btn = cancel_btn
        layout.addWidget(cancel_btn, 0, Qt.AlignVCenter)

        self.bill_disc_edit.textChanged.connect(self._sync_footer_to_header_disc)

    def _add_total_field(self, layout: QHBoxLayout, title: str, attr_name: str):
        container = QVBoxLayout()
        container.setSpacing(2)
        lbl = QLabel(title)
        lbl.setStyleSheet(_HEADER_LABEL)
        lbl.setAlignment(Qt.AlignCenter)
        container.addWidget(lbl)

        if attr_name.endswith("_label"):
            val_lbl = QLabel("0.00")
            val_lbl.setAlignment(Qt.AlignCenter)
            val_lbl.setMinimumWidth(80)
            if attr_name == "net_amt_label":
                val_lbl.setStyleSheet(
                    f"color: {_ACCENT}; font-size: 16px; font-weight: bold;"
                    f"background: transparent; font-family: 'Segoe UI'; padding: 2px;"
                )
            else:
                val_lbl.setStyleSheet(
                    f"color: {_TEXT}; font-size: 15px; font-weight: bold;"
                    f"background: transparent; font-family: 'Segoe UI'; padding: 2px;"
                )
            container.addWidget(val_lbl)
            setattr(self, attr_name, val_lbl)
        else:
            edit = _make_edit("0.00")
            edit.setMinimumWidth(75)
            edit.setMaximumWidth(95)
            edit.setAlignment(Qt.AlignCenter)
            container.addWidget(edit)
            setattr(self, attr_name, edit)
            if attr_name not in ("bill_disc_edit", "dn_edit", "other_edit", "paid_edit", "round_off_edit"):
                edit.setReadOnly(True)

        layout.addLayout(container)

    def _recalc_totals(self):
        total_amount = _round2(sum(r.amount for r in self._item_rows))
        total_gst = _round2(sum(r.gst_amount for r in self._item_rows))

        self.total_amount_label.setText(f"{total_amount:.2f}")
        self.gst_label.setText(f"{total_gst:.2f}")

        bill_disc = _safe_float(self.bill_disc_edit.text())
        dn = _safe_float(self.dn_edit.text())
        other = _safe_float(self.other_edit.text())

        raw_net = _d(total_amount) + _d(total_gst) - _d(bill_disc) - _d(dn) + _d(other)
        rounded_net = int(raw_net.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        round_off = _round2(float(_d(rounded_net) - raw_net))
        net = float(rounded_net)

        self.round_off_edit.setText(f"{round_off:.2f}")
        self.net_amt_label.setText(f"{net:.2f}")

    def _wire_totals_recalc(self):
        for attr in ("bill_disc_edit", "dn_edit", "other_edit", "paid_edit", "round_off_edit"):
            w = getattr(self, attr, None)
            if w is not None:
                w.textChanged.connect(self._recalc_totals)

    def _populate_invoice(self, inv: dict):
        full = inv.get("voucher_no", "")
        self._full_voucher_no = full
        self.voucher_no_edit.setText(_display_voucher_no(full))
        self.voucher_no_edit.setToolTip(f"Full Voucher: {full}")

        vd = inv.get("voucher_date", "")
        if vd:
            try:
                parts = vd.split("-")
                self.voucher_date.setDate(QDate(int(parts[0]), int(parts[1]), int(parts[2])))
            except Exception:
                pass

        from core.doc_formatter import format_time_12hr
        self.voucher_time_edit.setText(format_time_12hr(inv.get("voucher_time", "")))
        idx = self.purchase_type_combo.findText(inv.get("purchase_type", "Credit"))
        if idx >= 0:
            self.purchase_type_combo.setCurrentIndex(idx)

        sid = inv.get("supplier_id")
        if sid:
            idx = self.supplier_combo.findData(sid)
            if idx >= 0:
                self.supplier_combo.setCurrentIndex(idx)
            self._update_supplier_balance(sid)

        self.invoice_no_edit.setText(inv.get("invoice_no", ""))

        id_str = inv.get("invoice_date", "")
        if id_str:
            try:
                parts = id_str.split("-")
                self.invoice_date.setDate(QDate(int(parts[0]), int(parts[1]), int(parts[2])))
            except Exception:
                pass

        self.inv_net_amt_edit.setText(str(inv.get("invoice_net_amount", 0.0)))
        bd = str(inv.get("bill_discount", 0.0))
        self.bill_discount_edit.setText(bd)
        self.bill_disc_edit.setText(bd)

        dd = inv.get("due_date", "")
        if dd:
            try:
                parts = dd.split("-")
                self.due_date.setDate(QDate(int(parts[0]), int(parts[1]), int(parts[2])))
            except Exception:
                pass

        # Load items
        items = PurchaseDAO.get_invoice_items(inv["id"])
        for it in items:
            row = _InvoiceItemRow(
                item_id=it["item_id"],
                item_name=it.get("item_name", ""),
                pack_size=it.get("pack_size", ""),
                pay_qty=it.get("pay_qty", 0.0),
                free_qty=it.get("free_qty", 0.0),
                batch_no=it.get("batch_no", ""),
                expiry=it.get("expiry", ""),
                rate=it.get("rate", 0.0),
                mrp=it.get("mrp", 0.0),
                discount=it.get("discount", 0.0),
                gst_percent=it.get("gst_percent", 0.0),
                amount=it.get("amount", 0.0),
                gst_amount=it.get("gst_amount", 0.0),
                purchase_rate=it.get("purchase_rate", 0.0),
                net_rate=it.get("net_rate", 0.0),
                pp=(
                    float(it["pp"]) if (0 < float(it.get("pp") or 0.0) <= 100)
                    else (
                        float(round(((float(it.get("mrp") or 0.0) - float(it.get("purchase_rate") or 0.0)) / float(it["purchase_rate"])) * 100.0))
                        if (float(it.get("purchase_rate") or 0.0) > 0 and float(it.get("mrp") or 0.0) > float(it.get("purchase_rate") or 0.0)
                            and abs(((float(it.get("mrp") or 0.0) - float(it.get("purchase_rate") or 0.0)) / float(it["purchase_rate"])) * 100.0 - 25.0) < 0.1)
                        else (
                            round(((float(it.get("mrp") or 0.0) - float(it.get("purchase_rate") or 0.0)) / float(it["purchase_rate"])) * 100.0, 2)
                            if (float(it.get("purchase_rate") or 0.0) > 0 and float(it.get("mrp") or 0.0) > float(it.get("purchase_rate") or 0.0))
                            else 25.0
                        )
                    )
                ),
            )
            self._item_rows.append(row)
        self._refresh_table()

        # Populate totals
        self.dn_edit.setText(str(inv.get("debit_note_amount", 0.0)))
        self.other_edit.setText(str(inv.get("other_amount", 0.0)))
        self.paid_edit.setText(str(inv.get("paid_amount", 0.0)))
        self.round_off_edit.setText(str(inv.get("round_off", 0.0)))

        self._recalc_totals()

    @staticmethod
    def _lbl(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(_HEADER_LABEL)
        return lbl

    def _on_save(self):
        try:
            financial_year.validate_transaction_date(self.voucher_date.date().toString("yyyy-MM-dd"))
        except financial_year.FinancialYearError as exc:
            QMessageBox.warning(self, "Financial Year", str(exc)); return
        sid = self.supplier_combo.currentData()
        if not sid:
            QMessageBox.warning(self, "Validation", "Please select a valid supplier from the list.")
            return

        if not self._item_rows:
            QMessageBox.warning(self, "Validation", "At least one item is required.")
            return

        inv_d = self.get_invoice_date()
        for r in self._item_rows:
            if r.expiry:
                parsed_exp = parse_expiry_to_date(r.expiry)
                if parsed_exp and parsed_exp < inv_d:
                    exp_disp = parsed_exp.strftime("%d-%m-%Y")
                    inv_disp = inv_d.strftime("%d-%m-%Y")
                    QMessageBox.warning(
                        self,
                        "Expired Stock",
                        f"Cannot save invoice: Item '{r.item_name}' (Batch '{r.batch_no}') "
                        f"is expired ({exp_disp}) on invoice date ({inv_disp}).\n\n"
                        f"Expired stock cannot be entered in a new purchase invoice.",
                    )
                    return

        voucher_no = getattr(self, "_full_voucher_no", None) or self.voucher_no_edit.text().strip()
        if not voucher_no:
            QMessageBox.warning(self, "Validation", "Voucher number is required.")
            return

        self._recalc_totals()

        total_amount = _round2(float(_d(sum(r.amount for r in self._item_rows))))
        gst_amount = _round2(float(_d(sum(r.gst_amount for r in self._item_rows))))
        bill_discount = _safe_float(self.bill_discount_edit.text())
        dn = _safe_float(self.dn_edit.text())
        other = _safe_float(self.other_edit.text())
        paid = _safe_float(self.paid_edit.text())
        round_off = _safe_float(self.round_off_edit.text())
        net_amount = _round2(total_amount + gst_amount - bill_discount - dn + other + round_off)

        inv_net_amount = _safe_float(self.inv_net_amt_edit.text())
        voucher_date = self.voucher_date.date().toString("yyyy-MM-dd")
        voucher_time = self.voucher_time_edit.text().strip()
        purchase_type = self.purchase_type_combo.currentText()
        invoice_no = self.invoice_no_edit.text().strip()
        invoice_date = self.invoice_date.date().toString("yyyy-MM-dd")
        due_date = self.due_date.date().toString("yyyy-MM-dd")
        remarks = ""

        items_data = [r.to_dict() for r in self._item_rows]

        try:
            if self._invoice:
                PurchaseDAO.update_invoice(
                    invoice_id=self._invoice["id"],
                    voucher_no=voucher_no, voucher_date=voucher_date,
                    voucher_time=voucher_time, purchase_type=purchase_type,
                    supplier_id=sid, invoice_no=invoice_no,
                    invoice_date=invoice_date, invoice_net_amount=inv_net_amount,
                    bill_discount=bill_discount, due_date=due_date,
                    total_amount=total_amount, gst_amount=gst_amount,
                    debit_note_amount=dn, other_amount=other,
                    paid_amount=paid, round_off=round_off,
                    net_amount=net_amount, remarks=remarks,
                    items=items_data,
                )
            else:
                PurchaseDAO.insert_invoice(
                    voucher_no=voucher_no, voucher_date=voucher_date,
                    voucher_time=voucher_time, purchase_type=purchase_type,
                    supplier_id=sid, invoice_no=invoice_no,
                    invoice_date=invoice_date, invoice_net_amount=inv_net_amount,
                    bill_discount=bill_discount, due_date=due_date,
                    total_amount=total_amount, gst_amount=gst_amount,
                    debit_note_amount=dn, other_amount=other,
                    paid_amount=paid, round_off=round_off,
                    net_amount=net_amount, remarks=remarks,
                    items=items_data,
                )
            self._saved = True
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save invoice:\n{e}")

    @property
    def was_saved(self) -> bool:
        return self._saved

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.reject()
            return
        if event.modifiers() & Qt.ControlModifier and event.key() == Qt.Key_S:
            self._on_save()
            return
        super().keyPressEvent(event)

    def refresh_theme(self):
        p = palette()
        self.supplier_combo.refresh_theme(p)
        self.purchase_type_combo.setStyleSheet(_combo_style(p))
        self._entry_bar.refresh_theme(p)
        date_st = _date_style(p)
        self.voucher_date.setStyleSheet(date_st)
        self.invoice_date.setStyleSheet(date_st)
        self.due_date.setStyleSheet(date_st)
        edit_st = _edit_style(p)
        self.voucher_no_edit.setStyleSheet(edit_st)
        self.voucher_time_edit.setStyleSheet(edit_st)
        self.invoice_no_edit.setStyleSheet(edit_st)
        self.inv_net_amt_edit.setStyleSheet(edit_st)
        self.bill_discount_edit.setStyleSheet(edit_st)
        self.supplier_bal_label.setStyleSheet(
            f"color: {p.get('text_dim', _TEXT_DIM)}; font-size: 13px; font-weight: bold; background: transparent;"
            f"font-family: 'Segoe UI'; padding: 2px;"
        )
        self.setStyleSheet(
            f"QDialog {{ background-color: {p['bg']}; }}"
            f"QLabel {{ color: {p['text']}; font-size: 15px; font-family: 'Segoe UI'; background: transparent; }}"
        )


# ======================================================================
# Purchase Invoice PAGE  (stacked: History view | New/Edit view)
# ======================================================================

class PurchaseInvoicePage(QWidget):
    """Purchase Invoice screen with history list and invoice entry."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setStyleSheet(f"background-color: {_DARK_BG};")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._stack = QStackedWidget()
        root.addWidget(self._stack)

        self._current_fy_id: int | None = None

        # Page 0: History list
        self._history_page = self._build_history_page()
        self._stack.addWidget(self._history_page)

        # Page 1: Invoice form (embedded widget wrapping the dialog content)
        self._invoice_page = self._build_invoice_page()
        self._stack.addWidget(self._invoice_page)

        self._editing_invoice_id: int | None = None
        self._init_filter_dates()
        self._refresh_history()

    # ------------------------------------------------------------------
    # History page
    # ------------------------------------------------------------------

    def set_history_financial_year(self, year: dict | None) -> None:
        """Apply the navbar's view-only financial-year selection to Purchase History."""
        self._history_financial_year = dict(year) if year else None
        if year and year.get("start_date") and year.get("end_date"):
            start = str(year["start_date"])
            end = str(year["end_date"])
            self._current_fy_id = year.get("id")
            from PySide6.QtCore import QDate
            q_start = QDate.fromString(start, "yyyy-MM-dd")
            q_end = QDate.fromString(end, "yyyy-MM-dd")
            if q_start.isValid() and q_end.isValid():
                self._filter_from.setDate(q_start)
                self._filter_to.setDate(q_end)
        else:
            self._history_financial_year = None
            self._init_filter_dates()
        self._refresh_history()

    def showEvent(self, event):
        super().showEvent(event)
        if getattr(self, "_history_financial_year", None):
            return
        fy = financial_year.get_active_financial_year()
        fy_id = fy["id"] if fy else None
        if getattr(self, "_current_fy_id", None) != fy_id:
            self._init_filter_dates()
            self._refresh_history()

    def _init_filter_dates(self):
        """Set From/To date filter defaults from the active financial year."""
        from PySide6.QtCore import QDate
        fy = financial_year.get_active_financial_year()
        if fy:
            fy_start = fy["start_date"]  # "YYYY-MM-DD"
            fy_end = fy["end_date"]
            self._current_fy_id = fy["id"]
        else:
            fy_start = financial_year.DEFAULT_START
            fy_end = financial_year.DEFAULT_END
            self._current_fy_id = None
        q_start = QDate.fromString(fy_start, "yyyy-MM-dd")
        if q_start.isValid():
            self._filter_from.setDate(q_start)
        now = datetime.now()
        today = QDate(now.year, now.month, now.day)
        q_end = QDate.fromString(fy_end, "yyyy-MM-dd")
        if q_end.isValid():
            self._filter_to.setDate(min(today, q_end) if today <= q_end else q_end)

    def _build_history_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QWidget()
        header.setFixedHeight(56)
        header.setStyleSheet(
            f"background-color: {_SURFACE}; border-bottom: 1px solid {_BORDER};"
        )
        hl = QHBoxLayout(header)
        hl.setContentsMargins(16, 0, 16, 0)
        hl.setSpacing(8)
        title = QLabel("Purchase History")
        title.setStyleSheet(
            f"color: {_TEXT}; font-size: 22px; font-weight: bold;"
            f"background: transparent; font-family: 'Segoe UI';"
        )
        hl.addWidget(title)
        hl.addStretch()

        # Consistent button height for the toolbar row
        _TOOLBAR_BTN_H = 36

        new_btn = QPushButton("New Purchase")
        new_btn.setFixedSize(140, _TOOLBAR_BTN_H)
        new_btn.setStyleSheet(_BTN_SAVE)
        new_btn.clicked.connect(self._on_new)
        hl.addWidget(new_btn)

        edit_btn = QPushButton("Edit")
        edit_btn.setFixedSize(85, _TOOLBAR_BTN_H)
        edit_btn.setStyleSheet(_BTN_SECONDARY)
        edit_btn.clicked.connect(self._on_edit)
        hl.addWidget(edit_btn)

        delete_btn = QPushButton("Delete")
        delete_btn.setFixedSize(85, _TOOLBAR_BTN_H)
        delete_btn.setStyleSheet(_BTN_DANGER)
        delete_btn.clicked.connect(self._on_delete)
        hl.addWidget(delete_btn)

        print_btn = QPushButton("Print / PDF")
        print_btn.setFixedSize(115, _TOOLBAR_BTN_H)
        print_btn.setStyleSheet(_BTN_SECONDARY)
        print_btn.clicked.connect(self._on_print)
        hl.addWidget(print_btn)

        layout.addWidget(header)

        # Filter bar
        filter_bar = QWidget()
        filter_bar.setFixedHeight(48)
        filter_bar.setStyleSheet(
            f"background-color: {_SURFACE}; border-bottom: 1px solid {_BORDER};"
        )
        fl = QHBoxLayout(filter_bar)
        fl.setContentsMargins(16, 0, 16, 0)
        fl.setSpacing(8)

        fl.addWidget(self._flbl("From"))
        self._filter_from = _make_date()
        self._filter_from.setFixedWidth(145)
        fl.addWidget(self._filter_from)

        fl.addWidget(self._flbl("To"))
        self._filter_to = _make_date()
        self._filter_to.setFixedWidth(145)
        fl.addWidget(self._filter_to)

        fl.addWidget(self._flbl("Supplier"))
        self._filter_supplier = _make_combo(max_visible=9, max_height=270, max_width=380)
        self._filter_supplier.setMinimumWidth(160)
        self._filter_supplier.addItem("All Suppliers", None)
        for s in SupplierDAO.get_all():
            self._filter_supplier.addItem(s["supplier_name"], s["id"])
        fl.addWidget(self._filter_supplier)

        filter_btn = QPushButton("Filter")
        filter_btn.setFixedWidth(70)
        filter_btn.setStyleSheet(_BTN_GREEN_SM)
        filter_btn.clicked.connect(self._refresh_history)
        fl.addWidget(filter_btn)

        fl.addStretch()
        layout.addWidget(filter_bar)

        # Table
        self._hist_table = QTableWidget()
        self._hist_table.setColumnCount(8)
        self._hist_table.setHorizontalHeaderLabels([
            "Voucher Type", "Voucher No", "Voucher Date", "Time",
            "Invoice No", "Invoice Date", "Supplier", "Amount"
        ])
        self._hist_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._hist_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._hist_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._hist_table.verticalHeader().setVisible(False)
        self._hist_table.setShowGrid(True)
        self._hist_table.setAlternatingRowColors(False)
        self._hist_table.setSortingEnabled(True)

        hv = self._hist_table.horizontalHeader()
        hv.setStretchLastSection(True)
        hv.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hv.setSectionResizeMode(1, QHeaderView.Stretch)
        hv.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hv.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        hv.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        hv.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        hv.setSectionResizeMode(6, QHeaderView.Stretch)
        hv.setSectionResizeMode(7, QHeaderView.ResizeToContents)
        hv.setStyleSheet(
            f"QHeaderView::section {{"
            f"  background-color: {_SURFACE}; color: {_TEXT};"
            f"  border: none; border-bottom: 2px solid {_ACCENT};"
            f"  padding: 4px 8px; font-weight: bold; font-size: 15px;"
            f"  font-family: 'Segoe UI';"
            f"}}"
        )
        self._hist_table.setStyleSheet(
            f"QTableWidget {{"
            f"  background-color: {_DARK_BG}; color: {_TEXT};"
            f"  border: 1px solid {_BORDER}; gridline-color: {_BORDER};"
            f"  font-size: 15px; font-family: 'Segoe UI';"
            f"  selection-background-color: {_ACCENT};"
            f"  selection-color: white;"
            f"}}"
            f"QTableWidget::item {{ padding: 2px 6px; }}"
        )
        layout.addWidget(self._hist_table, 1)

        return page

    def _flbl(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(_LABEL_DIM)
        return lbl

    def _refresh_history(self):
        from_date = self._filter_from.date().toString("yyyy-MM-dd")
        to_date = self._filter_to.date().toString("yyyy-MM-dd")
        sup_id = self._filter_supplier.currentData()

        invs = PurchaseDAO.get_all_filtered(
            start_date=from_date, end_date=to_date, supplier_id=sup_id
        )
        self._hist_table.setRowCount(len(invs))
        for i, inv in enumerate(invs):
            self._hist_table.setItem(i, 0, QTableWidgetItem(inv.get("purchase_type", "")))
            raw_vno = inv.get("voucher_no", "")
            vno_item = QTableWidgetItem(_display_voucher_no(raw_vno))
            vno_item.setToolTip(f"Full Voucher: {raw_vno}")
            self._hist_table.setItem(i, 1, vno_item)
            self._hist_table.setItem(i, 2, QTableWidgetItem(inv.get("voucher_date", "")))
            from core.doc_formatter import format_time_12hr
            raw_time = inv.get("voucher_time", "")
            self._hist_table.setItem(i, 3, QTableWidgetItem(format_time_12hr(raw_time)))
            self._hist_table.setItem(i, 4, QTableWidgetItem(inv.get("invoice_no", "")))
            self._hist_table.setItem(i, 5, QTableWidgetItem(inv.get("invoice_date", "")))
            self._hist_table.setItem(i, 6, QTableWidgetItem(inv.get("supplier_name", "") or ""))
            self._hist_table.setItem(i, 7, QTableWidgetItem(f"{inv.get('net_amount', 0.0):.2f}"))
            # Store id as data in first column
            self._hist_table.item(i, 0).setData(Qt.UserRole, inv["id"])

    def _selected_history_id(self) -> int | None:
        rows = self._hist_table.selectionModel().selectedRows()
        if not rows:
            return None
        row = rows[0].row()
        return self._hist_table.item(row, 0).data(Qt.UserRole)

    def _on_new(self):
        self._editing_invoice_id = None
        self._open_invoice_dialog()

    def _on_edit(self):
        try:
            auth.session.require(auth.PERM_EDIT_TRANSACTIONS)
        except auth.PermissionDenied as exc:
            QMessageBox.warning(self, "Permission denied", str(exc)); return
        inv_id = self._selected_history_id()
        if not inv_id:
            QMessageBox.information(self, "Edit Purchase", "Please select an invoice to edit.")
            return
        inv = PurchaseDAO.get_by_id(inv_id)
        if not inv:
            QMessageBox.warning(self, "Edit Purchase", "Could not load invoice data.")
            return
        self._open_invoice_dialog(invoice=inv)

    def _on_print(self):
        invoice_id = self._selected_history_id()
        if not invoice_id:
            QMessageBox.information(self, "Print Purchase", "Please select an invoice to print.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save Purchase Invoice PDF", "purchase_invoice.pdf", "PDF (*.pdf)")
        if not path:
            return
        try:
            output = generate_purchase_invoice(invoice_id, path)
            QMessageBox.information(self, "PDF Saved", f"Purchase invoice saved to:\n{output}")
        except DocumentPrintError as exc:
            QMessageBox.warning(self, "Print Purchase", str(exc))

    def _on_delete(self):
        try:
            auth.session.require(auth.PERM_DELETE_TRANSACTIONS)
        except auth.PermissionDenied as exc:
            QMessageBox.warning(self, "Permission denied", str(exc)); return
        invoice_id = self._selected_history_id()
        if not invoice_id:
            QMessageBox.information(self, "Delete Purchase", "Please select a purchase invoice to delete.")
            return
        invoice = PurchaseDAO.get_by_id(invoice_id)
        if not invoice:
            QMessageBox.warning(self, "Delete Purchase", "This purchase no longer exists.")
            self._refresh_history(); return
        summary = (
            f"Voucher: {invoice.get('voucher_no', '')}\n"
            f"Supplier: {invoice.get('supplier_name', '')}\n"
            f"Net Amount: {invoice.get('net_amount', 0.0):.2f}\n\n"
            "Deleting this purchase will reverse its stock effect, reverse its "
            "accounting/ledger effect, and remove the source transaction.\n\n"
            "This action cannot be undone. Continue?"
        )
        if QMessageBox.warning(self, "Confirm Purchase Delete", summary, QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            PurchaseDAO.delete_invoice(invoice_id, actor=auth.session.user)
        except (auth.PermissionDenied, Exception) as exc:
            QMessageBox.critical(self, "Delete Purchase Failed", str(exc)); return
        self._hist_table.clearSelection()
        self._refresh_history()
        QMessageBox.information(self, "Purchase Deleted", "Purchase invoice deleted and its effects reversed.")

    def _open_invoice_dialog(self, invoice: dict | None = None):
        dlg = _InvoiceDialog(self, invoice=invoice)
        dlg.exec()
        if dlg.was_saved:
            self._refresh_history()

    # ------------------------------------------------------------------
    # Invoice page (not used directly; dialog-based approach)
    # ------------------------------------------------------------------

    def _build_invoice_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel("Invoice entry opens via dialog.")
        lbl.setStyleSheet(f"color: {_TEXT}; font-size: 17px; font-family: 'Segoe UI';")
        lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(lbl)
        return page

    def refresh_theme(self):
        p = palette()
        self.setStyleSheet(f"background-color: {p['bg']};")
        if hasattr(self, "_filter_supplier"):
            self._filter_supplier.setStyleSheet(_combo_style(p))
        if hasattr(self, "_filter_from"):
            self._filter_from.setStyleSheet(_date_style(p))
        if hasattr(self, "_filter_to"):
            self._filter_to.setStyleSheet(_date_style(p))

