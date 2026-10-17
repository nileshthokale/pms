from __future__ import annotations

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from PySide6.QtCore import Qt, QDate, QEvent, QStringListModel
from PySide6.QtWidgets import (
    QAbstractItemView,
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
    QVBoxLayout,
    QWidget,
)

from database.supplier_dao import SupplierDAO
from database.item_dao import ItemDAO
from database.tax_structures import rate_percent
from database.purchase_dao import PurchaseDAO
from database import auth
from database import financial_year
from database.document_printing import DocumentPrintError, generate_purchase_invoice

from ui.components import ConstrainedComboBox
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
        f"  border: 1px solid {border}; selection-background-color: {accent};"
        f"  selection-color: {selected_text};"
        f"  font-size: 15px; font-family: 'Segoe UI';"
        f"  outline: none;"
        f"}}"
        f"QComboBox QAbstractItemView::item {{"
        f"  min-height: 26px; padding: 2px 8px;"
        f"}}"
        f"QComboBox QAbstractItemView::item:selected {{"
        f"  background-color: {accent}; color: {selected_text};"
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
        f"  font-size: 15px; font-weight: bold; font-family: 'Segoe UI';"
        f"}}"
    )


def _display_voucher_no(voucher_no: str) -> str:
    """Return only the numeric / sequence part of a voucher number for display.
    e.g. '2026-2027-Credit-0251' -> '0251', preserving the full compound key in the database.
    """
    from core.doc_formatter import format_document_number
    return format_document_number(voucher_no)


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


def _make_date(p: dict | None = None) -> QDateEdit:
    d = QDateEdit()
    d.setCalendarPopup(True)
    d.setDisplayFormat("dd-MM-yyyy")
    d.setStyleSheet(_date_style(p))
    d.setFixedHeight(32)
    return d


class SearchableComboBox(ConstrainedComboBox):
    """Editable, searchable combo box with case-insensitive partial matching.

    - Compact dropdown (~8-10 visible entries) with vertical scrollbar.
    - Uses case-insensitive contains matching for suggestions as user types.
    - Keyboard navigation: Down/Up to highlight, Enter to select, Escape to dismiss.
    - Prevents arbitrary text from being accepted (currentData returns None if text doesn't match).
    - Preserves selection and updates associated fields.
    """

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
        line = self.lineEdit()
        if line is not None:
            line.setPlaceholderText(placeholder)
            line.setStyleSheet(_searchable_lineedit_style())
            line.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            line.installEventFilter(self)
            line.editingFinished.connect(self._resolve_current_text)

        self._completer = QCompleter(self)
        self._completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._completer.setFilterMode(Qt.MatchContains)
        self._completer.setCompletionMode(QCompleter.PopupCompletion)
        self._completer.setMaxVisibleItems(max_visible)
        popup = self._completer.popup()
        if popup is not None:
            popup.setMaximumHeight(max_height)
            popup.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            popup.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setCompleter(self._completer)
        self._completer.activated[str].connect(self._on_completion_str)
        self.refresh_theme()

    def refresh_theme(self, p: dict | None = None):
        p = p or palette()
        self.setStyleSheet(_combo_style(p))
        line = self.lineEdit()
        if line is not None:
            line.setStyleSheet(_searchable_lineedit_style(p))
        popup = self._completer.popup()
        if popup is not None:
            surface = p["surface"]
            text = p["text"]
            border = p["border"]
            accent = p["accent"]
            selected_text = p.get("selected_text", "#ffffff")
            popup.setStyleSheet(
                f"QAbstractItemView {{"
                f"  background-color: {surface}; color: {text};"
                f"  border: 1px solid {border};"
                f"  selection-background-color: {accent}; selection-color: {selected_text};"
                f"  font-size: 15px; font-family: 'Segoe UI'; outline: 0;"
                f"}}"
                f"QAbstractItemView::item {{ min-height: 26px; padding: 2px 8px; }}"
            )

    def populate(self, items: list[tuple[str, Any]]):
        """Populate items and update the completer model in a single fast batch.
        Initializes the combo in an empty, unselected state.
        """
        self.blockSignals(True)
        super().clear()
        names = []
        for text, data in items:
            super().addItem(text, data)
            names.append(text)
        super().setCurrentIndex(-1)
        line = self.lineEdit()
        if line is not None:
            line.clear()
            line.setToolTip("")
        self.blockSignals(False)
        self._completer.setModel(QStringListModel(names, self._completer))

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

    def clear_selection(self):
        """Reset combo to empty/unselected state and clear lineEdit text."""
        self.setCurrentIndex(-1)
        line = self.lineEdit()
        if line is not None:
            line.clear()
            line.setToolTip("")

    def currentText(self) -> str:
        idx = self.currentIndex()
        if idx >= 0:
            return self.itemText(idx)
        line = self.lineEdit()
        return line.text().strip() if line is not None else ""

    def showPopup(self):
        prefix = self.lineEdit().text().strip() if self.lineEdit() is not None else ""
        self._completer.setCompletionPrefix(prefix)
        self._completer.complete()

    def _on_completion_str(self, text: str):
        idx = self.findText(text, Qt.MatchFixedString)
        if idx >= 0:
            self.setCurrentIndex(idx)

    def _resolve_current_text(self):
        line = self.lineEdit()
        if not line:
            return
        text = line.text().strip()
        if not text:
            self.setCurrentIndex(-1)
            return
        # Only resolve if it's an exact case-insensitive match for an existing item
        idx = self.findText(text, Qt.MatchFixedString)
        if idx >= 0 and self.itemData(idx) is not None:
            self.setCurrentIndex(idx)
            line.setText(self.itemText(idx))
        else:
            self.setCurrentIndex(-1)

    def currentData(self, role: int = Qt.UserRole) -> Any:
        line = self.lineEdit()
        typed = line.text().strip() if line is not None else ""
        if not typed:
            return None
        idx = self.currentIndex()
        if idx >= 0:
            item_txt = self.itemText(idx).strip()
            if typed.casefold() == item_txt.casefold():
                return super().currentData(role)
        # Attempt exact match with master record names
        match_idx = self.findText(typed, Qt.MatchFixedString)
        if match_idx >= 0 and super().itemData(match_idx, role) is not None:
            return super().itemData(match_idx, role)
        return None

    def eventFilter(self, obj, event):
        if obj == self.lineEdit() and event.type() == QEvent.KeyPress:
            key = event.key()
            popup = self._completer.popup()
            if key == Qt.Key_Escape and popup is not None and popup.isVisible():
                popup.hide()
                return True
            if key in (Qt.Key_Down, Qt.Key_Up):
                if popup is not None and not popup.isVisible():
                    self._completer.setCompletionPrefix(self.lineEdit().text().strip())
                    self._completer.complete()
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
                    current = popup.currentIndex()
                    if not current.isValid() and self._completer.completionCount():
                        current = self._completer.completionModel().index(0, 0)
                    if current.isValid():
                        text = current.data(Qt.DisplayRole)
                        self._on_completion_str(str(text))
                        popup.hide()
                    return True
                else:
                    self._resolve_current_text()
                    return False
        return super().eventFilter(obj, event)


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


class _InvoiceItemRow:
    """Represents one item row in the invoice item table (used for data storage)."""

    def __init__(self, item_id: int, item_name: str, pack_size: str,
                 pay_qty: float, free_qty: float, batch_no: str,
                 expiry: str, rate: float, mrp: float, discount: float,
                 gst_percent: float, amount: float, gst_amount: float,
                 purchase_rate: float, net_rate: float, pp: float):
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

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "pack_size": self.pack_size,
            "pay_qty": self.pay_qty,
            "free_qty": self.free_qty,
            "batch_no": self.batch_no,
            "expiry": self.expiry,
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


class _ItemEntryBar(QWidget):
    """Entry bar for adding a single item to the invoice."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entry_labels: list[QLabel] = []
        root_v = QVBoxLayout(self)
        root_v.setContentsMargins(8, 4, 8, 4)
        root_v.setSpacing(8)

        # Controls creation
        self.item_combo = SearchableComboBox(
            placeholder="Type item name...",
            max_visible=9,
            max_height=270,
            max_width=450,
            min_width=280,
            allow_width_expansion=True,
        )
        self.item_combo.setFixedWidth(330)
        self.pack_edit = _make_edit("Pack", 70)
        self.batch_edit = _make_edit("Batch No", 130)
        self.expiry_edit = _make_edit("MM/YY", 95)

        self.pay_qty_edit = _make_edit("0", 75)
        self.free_qty_edit = _make_edit("0", 65)
        self.rate_edit = _make_edit("0.00", 85)
        self.mrp_edit = _make_edit("0.00", 85)
        self.discount_edit = _make_edit("0.00", 75)
        self.gst_edit = _make_edit("0.00", 75)

        self.add_btn = QPushButton("+ Add Item")
        self.add_btn.setStyleSheet(_BTN_GREEN_SM)
        self.add_btn.setFixedSize(110, 32)

        # Row 0: Item | Pack | Batch | Expiry
        row0 = QHBoxLayout()
        row0.setContentsMargins(0, 0, 0, 0)
        row0.setSpacing(12)
        row0.addWidget(self._field("Item *", self.item_combo, label_width=60))
        row0.addWidget(self._field("Pack", self.pack_edit, label_width=45))
        row0.addWidget(self._field("Batch *", self.batch_edit, label_width=60))
        row0.addWidget(self._field("Expiry *", self.expiry_edit, label_width=65))
        row0.addStretch(1)
        root_v.addLayout(row0)

        # Row 1: Pay Qty | Free | Rate | MRP | Discount % | GST % | Add Button
        row1 = QHBoxLayout()
        row1.setContentsMargins(0, 0, 0, 0)
        row1.setSpacing(10)
        row1.addWidget(self._field("Pay Qty *", self.pay_qty_edit, label_width=68))
        row1.addWidget(self._field("Free", self.free_qty_edit, label_width=40))
        row1.addWidget(self._field("Rate *", self.rate_edit, label_width=50))
        row1.addWidget(self._field("MRP *", self.mrp_edit, label_width=50))
        row1.addWidget(self._field("Discount %", self.discount_edit, label_width=78))
        row1.addWidget(self._field("GST %", self.gst_edit, label_width=50))
        row1.addWidget(self.add_btn)
        row1.addStretch(1)
        root_v.addLayout(row1)

        self._load_items()

    def _field(self, label_text: str, widget: QWidget, label_width: int | None = None) -> QWidget:
        container = QWidget()
        h = QHBoxLayout(container)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        lbl = QLabel(label_text)
        lbl.setStyleSheet(_LABEL_DIM)
        if label_width:
            lbl.setFixedWidth(label_width)
        self._entry_labels.append(lbl)
        h.addWidget(lbl)
        h.addWidget(widget)
        return container

    def _load_items(self):
        items = ItemDAO.get_all()
        list_items = []
        for it in items:
            list_items.append((it["item_name"], it["id"]))
        self.item_combo.populate(list_items)

    def clear(self):
        self.item_combo.clear_selection()
        self.pack_edit.clear()
        self.pay_qty_edit.clear()
        self.free_qty_edit.clear()
        self.batch_edit.clear()
        self.expiry_edit.clear()
        self.rate_edit.clear()
        self.mrp_edit.clear()
        self.discount_edit.clear()
        self.gst_edit.clear()

    def refresh_theme(self, p: dict | None = None):
        p = p or palette()
        self.item_combo.refresh_theme(p)
        edit_st = _edit_style(p)
        for w in (self.pack_edit, self.batch_edit, self.expiry_edit,
                  self.pay_qty_edit, self.free_qty_edit, self.rate_edit,
                  self.mrp_edit, self.discount_edit, self.gst_edit):
            w.setStyleSheet(edit_st)
        lbl_st = f"color: {p['text']}; font-size: 15px; font-weight: bold; font-family: 'Segoe UI'; background: transparent;"
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
        return {
            "item_id": item_id,
            "item_name": item_name,
            "pack_size": self.pack_edit.text().strip() or item_full.get("pack_size", ""),
            "pay_qty": _safe_float(self.pay_qty_edit.text()),
            "free_qty": _safe_float(self.free_qty_edit.text()),
            "batch_no": self.batch_edit.text().strip(),
            "expiry": self.expiry_edit.text().strip(),
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

        # Screen-aware sizing: 90% width, 85% height, centered
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

        # -- Top area: header + item entry --
        top = QWidget()
        top_layout = QVBoxLayout(top)
        top_layout.setContentsMargins(8, 8, 8, 0)
        top_layout.setSpacing(6)

        # Header fields
        self._build_header(top_layout)

        # Item entry bar
        self._entry_bar = _ItemEntryBar()
        top_layout.addWidget(self._entry_bar)

        root.addWidget(top)

        # -- Item table --
        self._build_item_table()
        root.addWidget(self._table_group, 1)

        # -- Totals + action buttons (combined footer) --
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
        self._entry_bar.gst_edit.returnPressed.connect(self._on_add_item)

        self._set_voucher_no()
        self._set_current_datetime()

        # Wire totals auto-recalc for all modes (new + edit)
        self._wire_totals_recalc()

        if invoice:
            self._populate_invoice(invoice)

    # ------------------------------------------------------------------
    # Header
    # ------------------------------------------------------------------

    def _build_header(self, parent_layout: QVBoxLayout):
        grp = QGroupBox("Invoice Header")
        grp.setStyleSheet(_GROUP_BOX)
        grid = QGridLayout(grp)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        grid.setContentsMargins(12, 18, 12, 10)

        # Standard label widths across columns
        LBL_COL0_W = 85
        LBL_COL2_W = 68
        LBL_COL4_W = 65
        LBL_COL6_W = 70

        # Row 0: Voucher No | Date | Time | Type
        lbl_v = self._lbl("Voucher No")
        lbl_v.setFixedWidth(LBL_COL0_W)
        grid.addWidget(lbl_v, 0, 0, Qt.AlignLeft | Qt.AlignVCenter)
        self.voucher_no_edit = _make_edit(width=135)
        self.voucher_no_edit.setReadOnly(True)
        self.voucher_no_edit.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        grid.addWidget(self.voucher_no_edit, 0, 1)

        lbl_date = self._lbl("Date")
        lbl_date.setFixedWidth(LBL_COL2_W)
        grid.addWidget(lbl_date, 0, 2, Qt.AlignLeft | Qt.AlignVCenter)
        self.voucher_date = _make_date()
        self.voucher_date.setFixedWidth(145)
        grid.addWidget(self.voucher_date, 0, 3)

        lbl_time = self._lbl("Time")
        lbl_time.setFixedWidth(LBL_COL4_W)
        grid.addWidget(lbl_time, 0, 4, Qt.AlignLeft | Qt.AlignVCenter)
        self.voucher_time_edit = _make_edit(width=90)
        self.voucher_time_edit.setAlignment(Qt.AlignCenter)
        grid.addWidget(self.voucher_time_edit, 0, 5)

        lbl_type = self._lbl("Type")
        lbl_type.setFixedWidth(LBL_COL6_W)
        grid.addWidget(lbl_type, 0, 6, Qt.AlignLeft | Qt.AlignVCenter)
        self.purchase_type_combo = _make_combo(max_visible=5, max_height=160)
        self.purchase_type_combo.addItems(["Credit", "Cash", "Credit Card"])
        self.purchase_type_combo.setFixedWidth(120)
        grid.addWidget(self.purchase_type_combo, 0, 7)

        # Row 1: Supplier * (spans cols 1-3) | Bal. | Due Date
        lbl_sup = self._lbl("Supplier *")
        lbl_sup.setFixedWidth(LBL_COL0_W)
        grid.addWidget(lbl_sup, 1, 0, Qt.AlignLeft | Qt.AlignVCenter)
        self.supplier_combo = SearchableComboBox(
            placeholder="Type supplier name...",
            max_visible=9,
            max_height=270,
            max_width=450,
            min_width=280,
            allow_width_expansion=True,
        )
        grid.addWidget(self.supplier_combo, 1, 1, 1, 3)

        lbl_bal = self._lbl("Bal.")
        lbl_bal.setFixedWidth(LBL_COL4_W)
        grid.addWidget(lbl_bal, 1, 4, Qt.AlignLeft | Qt.AlignVCenter)
        self.supplier_bal_label = QLabel("0.00")
        self.supplier_bal_label.setFixedWidth(90)
        self.supplier_bal_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.supplier_bal_label.setStyleSheet(
            f"color: {_TEXT_DIM}; font-size: 15px; font-weight: bold; background: transparent;"
            f"font-family: 'Segoe UI'; padding: 4px;"
        )
        grid.addWidget(self.supplier_bal_label, 1, 5)

        lbl_due = self._lbl("Due Date")
        lbl_due.setFixedWidth(LBL_COL6_W)
        grid.addWidget(lbl_due, 1, 6, Qt.AlignLeft | Qt.AlignVCenter)
        self.due_date = _make_date()
        self.due_date.setFixedWidth(145)
        grid.addWidget(self.due_date, 1, 7)

        # Row 2: Inv. No | Inv. Date | Inv. Amt | Bill Disc.
        lbl_inv = self._lbl("Inv. No")
        lbl_inv.setFixedWidth(LBL_COL0_W)
        grid.addWidget(lbl_inv, 2, 0, Qt.AlignLeft | Qt.AlignVCenter)
        self.invoice_no_edit = _make_edit(width=190)
        grid.addWidget(self.invoice_no_edit, 2, 1)

        lbl_inv_date = self._lbl("Inv. Date")
        lbl_inv_date.setFixedWidth(LBL_COL2_W)
        grid.addWidget(lbl_inv_date, 2, 2, Qt.AlignLeft | Qt.AlignVCenter)
        self.invoice_date = _make_date()
        self.invoice_date.setFixedWidth(145)
        grid.addWidget(self.invoice_date, 2, 3)

        lbl_inv_amt = self._lbl("Inv. Amt")
        lbl_inv_amt.setFixedWidth(LBL_COL4_W)
        grid.addWidget(lbl_inv_amt, 2, 4, Qt.AlignLeft | Qt.AlignVCenter)
        self.inv_net_amt_edit = _make_edit("0.00", width=100)
        self.inv_net_amt_edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        grid.addWidget(self.inv_net_amt_edit, 2, 5)

        lbl_bill_disc = self._lbl("Bill Disc.")
        lbl_bill_disc.setFixedWidth(LBL_COL6_W)
        grid.addWidget(lbl_bill_disc, 2, 6, Qt.AlignLeft | Qt.AlignVCenter)
        self.bill_discount_edit = _make_edit("0.00", width=120)
        self.bill_discount_edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        grid.addWidget(self.bill_discount_edit, 2, 7)

        grid.setColumnStretch(8, 1)

        parent_layout.addWidget(grp)

        # Load suppliers and wire date/discount connections
        self._load_suppliers()
        self.invoice_date.dateChanged.connect(self._on_invoice_date_changed)
        self.bill_discount_edit.textChanged.connect(self._sync_header_to_footer_disc)

    def _load_suppliers(self):
        suppliers = SupplierDAO.get_all()
        list_suppliers = []
        for s in suppliers:
            list_suppliers.append((s["supplier_name"], s["id"]))
        self.supplier_combo.populate(list_suppliers)
        self.supplier_combo.currentIndexChanged.connect(self._on_supplier_changed)

    def _on_supplier_changed(self, idx: int):
        sid = self.supplier_combo.currentData()
        if sid:
            sup = SupplierDAO.get_by_id(sid)
            if sup:
                bal = sup.get("opening_balance", 0.0)
                self.supplier_bal_label.setText(f"{bal:.2f}")
                # For new purchases, apply supplier payment term (credit_period)
                if not self._invoice:
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
                return
        self.supplier_bal_label.setText("0.00")

    def _on_invoice_date_changed(self, new_date: QDate):
        """When invoice date changes on a new invoice, update due date accordingly."""
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

    def _set_voucher_no(self):
        if not self._invoice:
            full = PurchaseDAO.generate_next_voucher_no()
            self._full_voucher_no = full
            self.voucher_no_edit.setText(_display_voucher_no(full))
            self.voucher_no_edit.setToolTip(f"Full Voucher: {full}")

    def _set_current_datetime(self):
        now = datetime.now()
        today = QDate(now.year, now.month, now.day)
        self.voucher_date.setDate(today)
        self.voucher_time_edit.setText(now.strftime("%H:%M"))
        # Default invoice date to today for a new invoice.
        # Due date defaults to today + 30 days (or supplier term if selected).
        self.invoice_date.setDate(today)
        self.due_date.setDate(today.addDays(30))

    # ------------------------------------------------------------------
    # Item entry + table
    # ------------------------------------------------------------------

    def _build_item_table(self):
        self._table_group = QGroupBox("Items")
        self._table_group.setStyleSheet(_GROUP_BOX)
        layout = QVBoxLayout(self._table_group)
        layout.setContentsMargins(6, 18, 6, 6)

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
            3: 75,   # Pay Qty
            4: 65,   # Free
            5: 110,  # Batch
            6: 75,   # Exp
            7: 80,   # Rate
            8: 80,   # MRP
            9: 65,   # Disc
            10: 95,  # Amount
            11: 65,  # GST%
            12: 85,  # GST Amt
            13: 85,  # Pur Rate
            14: 85,  # Net Rate
            15: 95,  # PP
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
            return
        item = ItemDAO.get_by_id(item_id)
        if item:
            if not self._entry_bar.pack_edit.text():
                self._entry_bar.pack_edit.setText(item.get("pack_size", ""))
            if not self._entry_bar.mrp_edit.text():
                self._entry_bar.mrp_edit.setText(str(item.get("mrp", 0.0)))
            if not self._entry_bar.rate_edit.text():
                self._entry_bar.rate_edit.setText(str(item.get("rate", 0.0)))
            tax = item.get("tax_structure", "")
            # Read the stored GST rate through the shared tax module instead
            # of parsing display text.  rate_percent returns None for a
            # legacy tax code, so an imported item still gets no invented
            # GST; a new GST item pre-fills the correct rate.  The box is
            # still per-line and fully user-overridable.
            percent = rate_percent(tax)
            if percent is not None and not self._entry_bar.gst_edit.text():
                self._entry_bar.gst_edit.setText(
                    f"{percent:g}" if percent else "0")

    def _recalc_current_line(self):
        """Live recalculation placeholder (does not affect table)."""
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

        if rate < 0:
            QMessageBox.warning(self, "Validation", "Rate cannot be negative.")
            return

        if data["mrp"] < 0:
            QMessageBox.warning(self, "Validation", "MRP cannot be negative.")
            return

        if gst_pct < 0:
            QMessageBox.warning(self, "Validation", "GST percentage cannot be negative.")
            return

        # Calculate amount and GST
        # Amount is based on PAY QTY only — free goods are not charged.
        disc_pct = _d(discount)
        gross = _d(pay_qty) * _d(rate)
        disc_amt = gross * disc_pct / _d(100) if disc_pct else _d(0)
        amount = _round2(gross - disc_amt)
        gst_amount = _round2(amount * gst_pct / 100.0)
        total_for_line = _round2(_d(amount) + _d(gst_amount))

        # Purchase rate = cost-per-paid-pack (incl GST), net rate = cost-per-received-pack (incl GST)
        qty_total = pay_qty + free_qty
        purchase_rate = _round2(total_for_line / pay_qty) if pay_qty else 0.0
        net_rate = _round2(total_for_line / qty_total) if qty_total else 0.0
        pp = _round2(total_for_line)  # PP = total price for this line

        row = _InvoiceItemRow(
            item_id=data["item_id"],
            item_name=data["item_name"],
            pack_size=data["pack_size"],
            pay_qty=pay_qty,
            free_qty=free_qty,
            batch_no=batch_no,
            expiry=data["expiry"],
            rate=rate,
            mrp=data["mrp"],
            discount=discount,
            gst_percent=gst_pct,
            amount=amount,
            gst_amount=gst_amount,
            purchase_rate=purchase_rate,
            net_rate=net_rate,
            pp=pp,
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
            self._table.setItem(i, 3, _item(f"{r.pay_qty:.2f}", Qt.AlignRight | Qt.AlignVCenter))
            self._table.setItem(i, 4, _item(f"{r.free_qty:.2f}", Qt.AlignRight | Qt.AlignVCenter))
            batch_w = _item(r.batch_no, Qt.AlignCenter)
            batch_w.setToolTip(r.batch_no)
            self._table.setItem(i, 5, batch_w)
            self._table.setItem(i, 6, _item(r.expiry, Qt.AlignCenter))
            self._table.setItem(i, 7, _item(f"{r.rate:.2f}", Qt.AlignRight | Qt.AlignVCenter))
            self._table.setItem(i, 8, _item(f"{r.mrp:.2f}", Qt.AlignRight | Qt.AlignVCenter))
            self._table.setItem(i, 9, _item(f"{r.discount:.2f}", Qt.AlignRight | Qt.AlignVCenter))
            self._table.setItem(i, 10, _item(f"{r.amount:.2f}", Qt.AlignRight | Qt.AlignVCenter))
            self._table.setItem(i, 11, _item(f"{r.gst_percent:.2f}", Qt.AlignRight | Qt.AlignVCenter))
            self._table.setItem(i, 12, _item(f"{r.gst_amount:.2f}", Qt.AlignRight | Qt.AlignVCenter))
            self._table.setItem(i, 13, _item(f"{r.purchase_rate:.2f}", Qt.AlignRight | Qt.AlignVCenter))
            self._table.setItem(i, 14, _item(f"{r.net_rate:.2f}", Qt.AlignRight | Qt.AlignVCenter))
            self._table.setItem(i, 15, _item(f"{r.pp:.2f}", Qt.AlignRight | Qt.AlignVCenter))

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

    # ------------------------------------------------------------------
    # Totals
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

        # Stretch separates totals from action buttons without cramping
        layout.addStretch(1)

        # Action buttons integrated into footer
        save_btn = QPushButton("Save Invoice")
        save_btn.setStyleSheet(_BTN_SAVE)
        save_btn.setFixedSize(125, 36)
        save_btn.clicked.connect(self._on_save)
        layout.addWidget(save_btn, 0, Qt.AlignVCenter)

        layout.addSpacing(10)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(_BTN_SECONDARY)
        cancel_btn.setFixedSize(95, 36)
        cancel_btn.clicked.connect(self.reject)
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
        """Wire up auto-recalc for totals fields."""
        for attr in ("bill_disc_edit", "dn_edit", "other_edit", "paid_edit", "round_off_edit"):
            w = getattr(self, attr)
            w.textChanged.connect(self._recalc_totals)

    # ------------------------------------------------------------------
    # Populate for edit
    # ------------------------------------------------------------------

    def _populate_invoice(self, inv: dict):
        full = inv.get("voucher_no", "")
        self._full_voucher_no = full
        self.voucher_no_edit.setText(_display_voucher_no(full))
        self.voucher_no_edit.setToolTip(f"Full Voucher: {full}")

        from PySide6.QtCore import QDate
        vd = inv.get("voucher_date", "")
        if vd:
            try:
                parts = vd.split("-")
                self.voucher_date.setDate(QDate(int(parts[0]), int(parts[1]), int(parts[2])))
            except Exception:
                pass

        self.voucher_time_edit.setText(inv.get("voucher_time", ""))
        idx = self.purchase_type_combo.findText(inv.get("purchase_type", "Credit"))
        if idx >= 0:
            self.purchase_type_combo.setCurrentIndex(idx)

        sid = inv.get("supplier_id")
        if sid:
            idx = self.supplier_combo.findData(sid)
            if idx >= 0:
                self.supplier_combo.setCurrentIndex(idx)

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
                pp=it.get("pp", 0.0),
            )
            self._item_rows.append(row)
        self._refresh_table()

        # Populate totals
        self.dn_edit.setText(str(inv.get("debit_note_amount", 0.0)))
        self.other_edit.setText(str(inv.get("other_amount", 0.0)))
        self.paid_edit.setText(str(inv.get("paid_amount", 0.0)))
        self.round_off_edit.setText(str(inv.get("round_off", 0.0)))

        self._recalc_totals()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _lbl(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(_HEADER_LABEL)
        return lbl

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

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

        voucher_no = getattr(self, "_full_voucher_no", None) or self.voucher_no_edit.text().strip()
        if not voucher_no:
            QMessageBox.warning(self, "Validation", "Voucher number is required.")
            return

        # Recalc totals for safety
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
            f"color: {p.get('text_dim', _TEXT_DIM)}; font-size: 15px; font-weight: bold; background: transparent;"
            f"font-family: 'Segoe UI'; padding: 4px;"
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

    def showEvent(self, event):
        super().showEvent(event)
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
        parts_s = fy_start.split("-")
        self._filter_from.setDate(QDate(int(parts_s[0]), int(parts_s[1]), int(parts_s[2])))
        now = datetime.now()
        today = QDate(now.year, now.month, now.day)
        parts_e = fy_end.split("-")
        fy_end_qdate = QDate(int(parts_e[0]), int(parts_e[1]), int(parts_e[2]))
        # To = min(today, FY end) so if today is within FY, show up to today;
        # otherwise show the entire FY range.
        self._filter_to.setDate(min(today, fy_end_qdate) if today <= fy_end_qdate else fy_end_qdate)

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
            self._hist_table.setItem(i, 3, QTableWidgetItem(inv.get("voucher_time", "")))
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

