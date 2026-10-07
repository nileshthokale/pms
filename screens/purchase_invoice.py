from __future__ import annotations

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
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

from ui.theme import palette
_p = palette()
_DARK_BG = _p["bg"]
_SURFACE = _p["surface"]
_BORDER = _p["border"]
_ACCENT = _p["accent"]
_ACCENT_HOVER = _p["accent_hover"]
_TEXT = _p["text"]
_TEXT_DIM = _p["text_dim"]
_ERROR = "#c0392b"

_COMBO_STYLE = (
    f"QComboBox {{"
    f"  background-color: {_SURFACE}; color: {_TEXT};"
    f"  border: 1px solid {_BORDER}; border-radius: 2px;"
    f"  padding: 6px; font-size: 12px; font-family: 'Segoe UI';"
    f"}}"
    f"QComboBox:hover {{ border: 1px solid {_ACCENT}; }}"
    f"QComboBox::drop-down {{ border: none; width: 24px; }}"
    f"QComboBox::down-arrow {{ image: none; border: none; }}"
    f"QComboBox QAbstractItemView {{"
    f"  background-color: {_SURFACE}; color: {_TEXT};"
    f"  border: 1px solid {_BORDER}; selection-background-color: {_ACCENT};"
    f"  font-size: 12px; font-family: 'Segoe UI';"
    f"}}"
)

_EDIT_STYLE = (
    f"QLineEdit {{"
    f"  background-color: {_SURFACE}; color: {_TEXT};"
    f"  border: 1px solid {_BORDER}; border-radius: 2px;"
    f"  padding: 5px; font-size: 12px; font-family: 'Segoe UI';"
    f"}}"
    f"QLineEdit:focus {{ border: 1px solid {_ACCENT}; }}"
)

_DATE_STYLE = (
    f"QDateEdit {{"
    f"  background-color: {_SURFACE}; color: {_TEXT};"
    f"  border: 1px solid {_BORDER}; border-radius: 2px;"
    f"  padding: 5px; font-size: 12px; font-family: 'Segoe UI';"
    f"}}"
    f"QDateEdit:focus {{ border: 1px solid {_ACCENT}; }}"
    f"QDateEdit::drop-down {{ border: none; width: 24px; }}"
    f"QDateEdit::down-arrow {{ image: none; border: none; }}"
)

_BTN_SAVE = (
    f"QPushButton {{ background-color: {_ACCENT}; color: white;"
    f"  border: none; border-radius: 2px; padding: 8px 20px;"
    f"  font-weight: bold; font-size: 13px; font-family: 'Segoe UI'; }}"
    f"QPushButton:hover {{ background-color: {_ACCENT_HOVER}; }}"
)

_BTN_SECONDARY = (
    f"QPushButton {{ background-color: {_BORDER}; color: {_TEXT};"
    f"  border: none; border-radius: 2px; padding: 8px 20px;"
    f"  font-size: 13px; font-family: 'Segoe UI'; }}"
    f"QPushButton:hover {{ background-color: #7d93a8; }}"
)

_BTN_DANGER = (
    f"QPushButton {{ background-color: {_ERROR}; color: white;"
    f"  border: none; border-radius: 3px; padding: 4px 8px;"
    f"  font-weight: bold; font-size: 12px; font-family: 'Segoe UI'; }}"
    f"QPushButton:hover {{ background-color: #d32f2f; }}"
)

_BTN_GREEN_SM = (
    f"QPushButton {{ background-color: {_ACCENT}; color: white;"
    f"  border: none; border-radius: 2px; padding: 6px 14px;"
    f"  font-weight: bold; font-size: 12px; font-family: 'Segoe UI'; }}"
    f"QPushButton:hover {{ background-color: {_ACCENT_HOVER}; }}"
)

_LABEL_STYLE = f"color: {_TEXT}; font-size: 12px; font-family: 'Segoe UI'; background: transparent;"
_LABEL_DIM = f"color: {_TEXT}; font-size: 12px; font-weight: bold; font-family: 'Segoe UI'; background: transparent;"
_HEADER_LABEL = f"color: {_TEXT}; font-size: 12px; font-family: 'Segoe UI'; background: transparent; font-weight: bold;"

_GROUP_BOX = (
    f"QGroupBox {{"
    f"  color: {_TEXT}; font-weight: bold; font-size: 12px;"
    f"  border: 1px solid {_BORDER}; border-radius: 2px;"
    f"  margin-top: 10px; padding-top: 14px;"
    f"}}"
    f"QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 6px; }}"
)


def _make_edit(placeholder: str = "", width: int | None = None) -> QLineEdit:
    e = QLineEdit()
    e.setPlaceholderText(placeholder)
    e.setStyleSheet(_EDIT_STYLE)
    e.setFont(__import__("PySide6.QtGui", fromlist=["QFont"]).QFont("Segoe UI", 12))
    if width:
        e.setMaximumWidth(width)
    return e


def _make_combo() -> QComboBox:
    c = QComboBox()
    c.setStyleSheet(_COMBO_STYLE)
    return c


def _make_date() -> QDateEdit:
    d = QDateEdit()
    d.setCalendarPopup(True)
    d.setStyleSheet(_DATE_STYLE)
    return d


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
    """Horizontal bar for adding a single item to the invoice."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)

        # Item selector
        layout.addWidget(self._label("Item"))
        self.item_combo = _make_combo()
        self.item_combo.setMinimumWidth(180)
        self.item_combo.setSizePolicy(__import__("PySide6.QtWidgets", fromlist=["QSizePolicy"]).QSizePolicy.Expanding, __import__("PySide6.QtWidgets", fromlist=["QSizePolicy"]).QSizePolicy.Fixed)
        layout.addWidget(self.item_combo)

        # Pack size
        layout.addWidget(self._label("Pack"))
        self.pack_edit = _make_edit("Pack", 60)
        layout.addWidget(self.pack_edit)

        # Pay Qty
        layout.addWidget(self._label("Pay Qty"))
        self.pay_qty_edit = _make_edit("0", 55)
        layout.addWidget(self.pay_qty_edit)

        # Free Qty
        layout.addWidget(self._label("Free"))
        self.free_qty_edit = _make_edit("0", 50)
        layout.addWidget(self.free_qty_edit)

        # Batch
        layout.addWidget(self._label("Batch"))
        self.batch_edit = _make_edit("Batch", 70)
        layout.addWidget(self.batch_edit)

        # Expiry
        layout.addWidget(self._label("Exp"))
        self.expiry_edit = _make_edit("MM/YY", 55)
        layout.addWidget(self.expiry_edit)

        # Rate
        layout.addWidget(self._label("Rate"))
        self.rate_edit = _make_edit("0.00", 65)
        layout.addWidget(self.rate_edit)

        # MRP
        layout.addWidget(self._label("MRP"))
        self.mrp_edit = _make_edit("0.00", 65)
        layout.addWidget(self.mrp_edit)

        # Discount
        layout.addWidget(self._label("Disc"))
        self.discount_edit = _make_edit("0.00", 55)
        layout.addWidget(self.discount_edit)

        # GST %
        layout.addWidget(self._label("GST%"))
        self.gst_edit = _make_edit("0.00", 50)
        layout.addWidget(self.gst_edit)

        # Add button
        add_btn = QPushButton("+ Add")
        add_btn.setStyleSheet(_BTN_GREEN_SM)
        add_btn.setFixedWidth(60)
        layout.addWidget(add_btn)

        self._load_items()

    def _load_items(self):
        items = ItemDAO.get_all()
        self.item_combo.addItem("-- Select --", None)
        for it in items:
            self.item_combo.addItem(it["item_name"], it["id"])

    @staticmethod
    def _label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(_LABEL_DIM)
        return lbl

    def clear(self):
        self.item_combo.setCurrentIndex(0)
        self.pack_edit.clear()
        self.pay_qty_edit.clear()
        self.free_qty_edit.clear()
        self.batch_edit.clear()
        self.expiry_edit.clear()
        self.rate_edit.clear()
        self.mrp_edit.clear()
        self.discount_edit.clear()
        self.gst_edit.clear()

    def get_current_item_data(self) -> dict | None:
        item_id = self.item_combo.currentData()
        if item_id is None:
            return None
        item_name = self.item_combo.currentText()
        item_full = ItemDAO.get_by_id(item_id)
        return {
            "item_id": item_id,
            "item_name": item_name,
            "pack_size": self.pack_edit.text().strip() or (item_full.get("pack_size", "") if item_full else ""),
            "pay_qty": _safe_float(self.pay_qty_edit.text()),
            "free_qty": _safe_float(self.free_qty_edit.text()),
            "batch_no": self.batch_edit.text().strip(),
            "expiry": self.expiry_edit.text().strip(),
            "rate": _safe_float(self.rate_edit.text()),
            "mrp": _safe_float(self.mrp_edit.text()),
            "discount": _safe_float(self.discount_edit.text()),
            "gst_percent": _safe_float(self.gst_edit.text()),
            "item_name": item_name,
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

        # -- Totals row --
        self._build_totals()
        root.addWidget(self._totals_widget)

        # -- Button bar --
        btn_bar = QHBoxLayout()
        btn_bar.setContentsMargins(12, 6, 12, 8)
        btn_bar.addStretch()
        save_btn = QPushButton("Save Invoice")
        save_btn.setStyleSheet(_BTN_SAVE)
        save_btn.clicked.connect(self._on_save)
        btn_bar.addWidget(save_btn)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(_BTN_SECONDARY)
        cancel_btn.clicked.connect(self.reject)
        btn_bar.addWidget(cancel_btn)
        root.addLayout(btn_bar)

        # Wire entry bar add button
        self._entry_bar.item_combo.currentIndexChanged.connect(self._on_item_changed)
        self._entry_bar.rate_edit.textChanged.connect(self._recalc_current_line)
        self._entry_bar.mrp_edit.textChanged.connect(self._recalc_current_line)
        self._entry_bar.discount_edit.textChanged.connect(self._recalc_current_line)
        self._entry_bar.gst_edit.textChanged.connect(self._recalc_current_line)
        self._entry_bar.pay_qty_edit.textChanged.connect(self._recalc_current_line)

        # Find the add button inside entry bar
        for child in self._entry_bar.findChildren(QPushButton):
            if child.text() == "+ Add":
                child.clicked.connect(self._on_add_item)
                break

        self._set_voucher_no()
        self._set_current_datetime()

        if invoice:
            self._populate_invoice(invoice)

    # ------------------------------------------------------------------
    # Header
    # ------------------------------------------------------------------

    def _build_header(self, parent_layout: QVBoxLayout):
        grp = QGroupBox("Invoice Header")
        grp.setStyleSheet(_GROUP_BOX)
        grid = QGridLayout(grp)
        grid.setSpacing(6)
        grid.setContentsMargins(10, 18, 10, 8)

        row = 0

        # Voucher No
        grid.addWidget(self._lbl("Voucher No"), row, 0)
        self.voucher_no_edit = _make_edit()
        self.voucher_no_edit.setReadOnly(True)
        grid.addWidget(self.voucher_no_edit, row, 1)

        # Date
        grid.addWidget(self._lbl("Date"), row, 2)
        self.voucher_date = _make_date()
        self.voucher_date.setMaximumWidth(130)
        grid.addWidget(self.voucher_date, row, 3)

        # Time
        grid.addWidget(self._lbl("Time"), row, 4)
        self.voucher_time_edit = _make_edit()
        self.voucher_time_edit.setMaximumWidth(80)
        grid.addWidget(self.voucher_time_edit, row, 5)

        # Type
        grid.addWidget(self._lbl("Type"), row, 6)
        self.purchase_type_combo = _make_combo()
        self.purchase_type_combo.addItems(["Credit", "Cash", "Credit Card"])
        self.purchase_type_combo.setMaximumWidth(110)
        grid.addWidget(self.purchase_type_combo, row, 7)

        row += 1

        # Supplier
        grid.addWidget(self._lbl("Supplier *"), row, 0)
        self.supplier_combo = _make_combo()
        self.supplier_combo.setMinimumWidth(200)
        grid.addWidget(self.supplier_combo, row, 1)

        # Supplier Balance
        grid.addWidget(self._lbl("Bal."), row, 2)
        self.supplier_bal_label = QLabel("0.00")
        self.supplier_bal_label.setStyleSheet(
            f"color: {_TEXT_DIM}; font-size: 12px; background: transparent;"
            f"font-family: 'Segoe UI'; padding: 4px;"
        )
        grid.addWidget(self.supplier_bal_label, row, 3)

        row += 1

        # Invoice No
        grid.addWidget(self._lbl("Inv. No"), row, 0)
        self.invoice_no_edit = _make_edit()
        grid.addWidget(self.invoice_no_edit, row, 1)

        # Invoice Date
        grid.addWidget(self._lbl("Inv. Date"), row, 2)
        self.invoice_date = _make_date()
        self.invoice_date.setMaximumWidth(130)
        grid.addWidget(self.invoice_date, row, 3)

        # Invoice Net Amount
        grid.addWidget(self._lbl("Inv. Amt"), row, 4)
        self.inv_net_amt_edit = _make_edit("0.00")
        self.inv_net_amt_edit.setMaximumWidth(100)
        grid.addWidget(self.inv_net_amt_edit, row, 5)

        # Bill Discount
        grid.addWidget(self._lbl("Bill Disc."), row, 6)
        self.bill_discount_edit = _make_edit("0.00")
        self.bill_discount_edit.setMaximumWidth(100)
        grid.addWidget(self.bill_discount_edit, row, 7)

        row += 1

        # Due Date
        grid.addWidget(self._lbl("Due Date"), row, 0)
        self.due_date = _make_date()
        self.due_date.setMaximumWidth(130)
        grid.addWidget(self.due_date, row, 1)

        parent_layout.addWidget(grp)

        # Load suppliers
        self._load_suppliers()

    def _load_suppliers(self):
        suppliers = SupplierDAO.get_all()
        self.supplier_combo.addItem("-- Select Supplier --", None)
        for s in suppliers:
            self.supplier_combo.addItem(s["supplier_name"], s["id"])
        self.supplier_combo.currentIndexChanged.connect(self._on_supplier_changed)

    def _on_supplier_changed(self, idx: int):
        sid = self.supplier_combo.currentData()
        if sid:
            sup = SupplierDAO.get_by_id(sid)
            if sup:
                bal = sup.get("opening_balance", 0.0)
                self.supplier_bal_label.setText(f"{bal:.2f}")
                return
        self.supplier_bal_label.setText("0.00")

    def _set_voucher_no(self):
        if not self._invoice:
            self.voucher_no_edit.setText(PurchaseDAO.generate_next_voucher_no())

    def _set_current_datetime(self):
        now = datetime.now()
        from PySide6.QtCore import QDate, QTime
        self.voucher_date.setDate(QDate(now.year, now.month, now.day))
        self.voucher_time_edit.setText(now.strftime("%H:%M"))

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
        self._table.horizontalHeader().setStretchLastSection(True)

        hv = self._table.horizontalHeader()
        for i in range(17):
            if i == 1:
                hv.setSectionResizeMode(i, QHeaderView.Stretch)
            else:
                hv.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        hv.setStyleSheet(
            f"QHeaderView::section {{"
            f"  background-color: {_SURFACE}; color: {_TEXT};"
            f"  border: none; border-bottom: 2px solid {_ACCENT};"
            f"  padding: 2px 5px; font-weight: bold; font-size: 12px;"
            f"  font-family: 'Segoe UI';"
            f"}}"
        )
        self._table.setStyleSheet(
            f"QTableWidget {{"
            f"  background-color: {_DARK_BG}; color: {_TEXT};"
            f"  border: 1px solid {_BORDER}; gridline-color: {_BORDER};"
            f"  font-size: 13px; font-family: 'Segoe UI';"
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
            QMessageBox.warning(self, "Validation", "Please select an item.")
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
        qty_total = pay_qty + free_qty
        amount = _round2(qty_total * rate)
        gst_amount = _round2(amount * gst_pct / 100.0)
        total_for_line = amount + gst_amount

        # Purchase rate, net rate, PP
        purchase_rate = _round2(total_for_line / qty_total) if qty_total else 0.0
        net_rate = _round2(rate)  # net rate = rate per unit after disc
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
            self._table.setItem(i, 0, QTableWidgetItem(str(i + 1)))
            self._table.setItem(i, 1, QTableWidgetItem(r.item_name))
            self._table.setItem(i, 2, QTableWidgetItem(r.pack_size))
            self._table.setItem(i, 3, QTableWidgetItem(f"{r.pay_qty:.2f}"))
            self._table.setItem(i, 4, QTableWidgetItem(f"{r.free_qty:.2f}"))
            self._table.setItem(i, 5, QTableWidgetItem(r.batch_no))
            self._table.setItem(i, 6, QTableWidgetItem(r.expiry))
            self._table.setItem(i, 7, QTableWidgetItem(f"{r.rate:.2f}"))
            self._table.setItem(i, 8, QTableWidgetItem(f"{r.mrp:.2f}"))
            self._table.setItem(i, 9, QTableWidgetItem(f"{r.discount:.2f}"))
            self._table.setItem(i, 10, QTableWidgetItem(f"{r.amount:.2f}"))
            self._table.setItem(i, 11, QTableWidgetItem(f"{r.gst_percent:.2f}"))
            self._table.setItem(i, 12, QTableWidgetItem(f"{r.gst_amount:.2f}"))
            self._table.setItem(i, 13, QTableWidgetItem(f"{r.purchase_rate:.2f}"))
            self._table.setItem(i, 14, QTableWidgetItem(f"{r.net_rate:.2f}"))
            self._table.setItem(i, 15, QTableWidgetItem(f"{r.pp:.2f}"))

            del_btn = QPushButton("Del")
            del_btn.setStyleSheet(_BTN_DANGER)
            del_btn.setFixedWidth(40)
            del_btn.clicked.connect(lambda _, idx=i: self._delete_item(idx))
            self._table.setCellWidget(i, 16, del_btn)

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
        self._totals_widget.setFixedHeight(44)
        self._totals_widget.setStyleSheet(
            f"background-color: {_SURFACE}; border-top: 1px solid {_BORDER};"
        )
        layout = QHBoxLayout(self._totals_widget)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(16)

        self._add_total_field(layout, "Total Amt", "total_amount_label")
        self._add_total_field(layout, "+ GST", "gst_label")
        self._add_total_field(layout, "- Bill Disc", "bill_disc_edit")
        self._add_total_field(layout, "- DN Amt", "dn_edit")
        self._add_total_field(layout, "+ Other", "other_edit")
        self._add_total_field(layout, "Paid", "paid_edit")
        self._add_total_field(layout, "Round Off", "round_off_edit")
        self._add_total_field(layout, "NET AMT", "net_amt_label")

    def _add_total_field(self, layout: QHBoxLayout, title: str, attr_name: str):
        container = QVBoxLayout()
        container.setSpacing(1)
        lbl = QLabel(title)
        lbl.setStyleSheet(_HEADER_LABEL)
        lbl.setAlignment(Qt.AlignCenter)
        container.addWidget(lbl)

        if attr_name.endswith("_label"):
            val_lbl = QLabel("0.00")
            val_lbl.setAlignment(Qt.AlignCenter)
            val_lbl.setStyleSheet(
                f"color: {_TEXT}; font-size: 13px; font-weight: bold;"
                f"background: transparent; font-family: 'Segoe UI'; padding: 2px;"
            )
            container.addWidget(val_lbl)
            setattr(self, attr_name, val_lbl)
        else:
            edit = _make_edit("0.00")
            edit.setMaximumWidth(90)
            edit.setAlignment(Qt.AlignCenter)
            container.addWidget(edit)
            setattr(self, attr_name, edit)
            if attr_name not in ("bill_disc_edit", "dn_edit", "other_edit", "paid_edit", "round_off_edit"):
                edit.setReadOnly(True)

        layout.addLayout(container)

    def _recalc_totals(self):
        total_amount = sum(r.amount for r in self._item_rows)
        total_gst = sum(r.gst_amount for r in self._item_rows)

        self.total_amount_label.setText(f"{total_amount:.2f}")
        self.gst_label.setText(f"{total_gst:.2f}")

        bill_disc = _safe_float(self.bill_disc_edit.text())
        dn = _safe_float(self.dn_edit.text())
        other = _safe_float(self.other_edit.text())
        paid = _safe_float(self.paid_edit.text())

        net = total_amount + total_gst - bill_disc - dn + other
        round_off = _round2(net) - net
        net = _round2(net + round_off)

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
        self.voucher_no_edit.setText(inv.get("voucher_no", ""))

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
        self.bill_discount_edit.setText(str(inv.get("bill_discount", 0.0)))

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

        self._wire_totals_recalc()
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
            QMessageBox.warning(self, "Validation", "Supplier is required.")
            return

        if not self._item_rows:
            QMessageBox.warning(self, "Validation", "At least one item is required.")
            return

        voucher_no = self.voucher_no_edit.text().strip()
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

        # Page 0: History list
        self._history_page = self._build_history_page()
        self._stack.addWidget(self._history_page)

        # Page 1: Invoice form (embedded widget wrapping the dialog content)
        self._invoice_page = self._build_invoice_page()
        self._stack.addWidget(self._invoice_page)

        self._editing_invoice_id: int | None = None
        self._refresh_history()

    # ------------------------------------------------------------------
    # History page
    # ------------------------------------------------------------------

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
        title = QLabel("Purchase History")
        title.setStyleSheet(
            f"color: {_TEXT}; font-size: 18px; font-weight: bold;"
            f"background: transparent; font-family: 'Segoe UI';"
        )
        hl.addWidget(title)
        hl.addStretch()

        new_btn = QPushButton("New Purchase")
        new_btn.setFixedWidth(120)
        new_btn.setStyleSheet(_BTN_SAVE)
        new_btn.clicked.connect(self._on_new)
        hl.addWidget(new_btn)

        edit_btn = QPushButton("Edit")
        edit_btn.setFixedWidth(90)
        edit_btn.setStyleSheet(_BTN_SECONDARY)
        edit_btn.clicked.connect(self._on_edit)
        hl.addWidget(edit_btn)

        delete_btn = QPushButton("Delete")
        delete_btn.setFixedWidth(90)
        delete_btn.setStyleSheet(_BTN_DANGER)
        delete_btn.clicked.connect(self._on_delete)
        hl.addWidget(delete_btn)

        print_btn = QPushButton("Print / PDF")
        print_btn.setFixedWidth(110)
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
        self._filter_from.setMaximumWidth(120)
        fl.addWidget(self._filter_from)

        fl.addWidget(self._flbl("To"))
        self._filter_to = _make_date()
        self._filter_to.setMaximumWidth(120)
        fl.addWidget(self._filter_to)

        fl.addWidget(self._flbl("Supplier"))
        self._filter_supplier = _make_combo()
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
            f"  padding: 4px 8px; font-weight: bold; font-size: 12px;"
            f"  font-family: 'Segoe UI';"
            f"}}"
        )
        self._hist_table.setStyleSheet(
            f"QTableWidget {{"
            f"  background-color: {_DARK_BG}; color: {_TEXT};"
            f"  border: 1px solid {_BORDER}; gridline-color: {_BORDER};"
            f"  font-size: 13px; font-family: 'Segoe UI';"
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
            self._hist_table.setItem(i, 1, QTableWidgetItem(inv.get("voucher_no", "")))
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
        lbl.setStyleSheet(f"color: {_TEXT}; font-size: 16px; font-family: 'Segoe UI';")
        lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(lbl)
        return page
