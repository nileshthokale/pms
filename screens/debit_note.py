from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, QDate
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QFrame,
)

from database.debit_note_dao import DebitNoteDAO
from database import auth
from database import financial_year
from database.document_printing import DocumentPrintError, generate_debit_note
from database.item_dao import ItemDAO
from database.purchase_dao import pack_factor
from database.stock_dao import StockDAO
from database.supplier_dao import SupplierDAO

from ui.components import SearchableComboBox
from ui.theme import date_subcontrols, palette


def _get_palette():
    return palette()


def _safe_float(text: str, default: float = 0.0) -> float:
    try:
        t = str(text).strip()
        return float(t) if t else default
    except (ValueError, TypeError):
        return default


# ======================================================================
# Return Item line data class
# ======================================================================

class _ReturnItemRow:
    """One line item being returned to supplier."""

    def __init__(
        self,
        item_id: int,
        item_name: str,
        stock_batch_id: int,
        batch_no: str,
        expiry: str,
        pack_size: str,
        rate: float,
        mrp: float,
        return_qty: float,
        free_qty: float,
        less_amount: float,
        amount: float,
        return_reason: str,
        price_factor: str = "RATE",
        price_factor_num: float = 1.0,
    ):
        self.item_id = item_id
        self.item_name = item_name
        self.stock_batch_id = stock_batch_id
        self.batch_no = batch_no
        self.expiry = expiry
        self.pack_size = pack_size
        self.rate = rate
        self.mrp = mrp
        self.return_qty = return_qty
        self.free_qty = free_qty
        self.less_amount = less_amount
        self.amount = amount
        self.return_reason = return_reason
        self.price_factor = price_factor
        self.price_factor_num = price_factor_num

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "stock_batch_id": self.stock_batch_id,
            "batch_no": self.batch_no,
            "expiry": self.expiry,
            "pack_size": self.pack_size,
            "rate": self.rate,
            "mrp": self.mrp,
            "return_qty": self.return_qty,
            "free_qty": self.free_qty,
            "less_amount": self.less_amount,
            "amount": self.amount,
            "return_reason": self.return_reason,
            "price_factor": self.price_factor_num,
            "is_pack_qty": True,
        }


# ======================================================================
# Item Entry Bar for Debit Note
# ======================================================================

class _ItemEntryBar(QWidget):
    """Horizontal bar matching Pharma-WINNER item entry row."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._supplier_id: int | None = None
        self._build_ui()

    def _build_ui(self):
        p = _get_palette()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(4)

        # Labels row
        lbl_row = QHBoxLayout()
        lbl_row.setContentsMargins(0, 0, 0, 0)
        lbl_row.setSpacing(4)

        def _make_lbl(text: str, width: int | None = None, bold: bool = False):
            l = QLabel(text)
            f = "bold" if bold else "normal"
            l.setStyleSheet(f"color: {p['text']}; font-size: 13px; font-weight: {f}; font-family: 'Segoe UI';")
            if width:
                l.setFixedWidth(width)
            return l

        lbl_row.addWidget(_make_lbl("* Item Name", 240, bold=True))
        lbl_row.addWidget(_make_lbl("", 90))  # space for expired only checkbox
        lbl_row.addWidget(_make_lbl("Batch #", 150))
        lbl_row.addWidget(_make_lbl("Expiry", 80))
        lbl_row.addWidget(_make_lbl("Pack Size", 70))
        lbl_row.addWidget(_make_lbl("Rate", 70))
        lbl_row.addWidget(_make_lbl("MRP", 70))
        lbl_row.addWidget(_make_lbl("Return Qty", 70))
        lbl_row.addWidget(_make_lbl("Free Qty", 65))
        lbl_row.addWidget(_make_lbl("Less %", 65))
        lbl_row.addWidget(_make_lbl("Return Reason", 130))
        lbl_row.addWidget(_make_lbl("Price Factor", 90))
        lbl_row.addWidget(_make_lbl("", 40))  # add button space
        layout.addLayout(lbl_row)

        # Controls row
        ctrl_row = QHBoxLayout()
        ctrl_row.setContentsMargins(0, 0, 0, 0)
        ctrl_row.setSpacing(4)

        self.item_combo = SearchableComboBox(placeholder="Type medicine name to search...")
        self.item_combo.setFixedWidth(240)
        ctrl_row.addWidget(self.item_combo)

        self.expired_only_cb = QCheckBox("Expired Only")
        self.expired_only_cb.setFixedWidth(90)
        self.expired_only_cb.setStyleSheet(f"color: {p['text']}; font-size: 12px;")
        self.expired_only_cb.toggled.connect(self._on_expired_toggled)
        ctrl_row.addWidget(self.expired_only_cb)

        self.batch_combo = SearchableComboBox(placeholder="-- Select Batch --", min_width=320)
        self.batch_combo.setFixedWidth(170)
        self.batch_combo.selection_changed.connect(self._on_batch_selected)
        self.batch_combo.currentIndexChanged.connect(self._on_batch_changed)
        ctrl_row.addWidget(self.batch_combo)

        self.expiry_edit = QLineEdit()
        self.expiry_edit.setFixedWidth(80)
        self.expiry_edit.setReadOnly(True)
        self.expiry_edit.setAlignment(Qt.AlignCenter)
        ctrl_row.addWidget(self.expiry_edit)

        self.pack_edit = QLineEdit()
        self.pack_edit.setFixedWidth(70)
        self.pack_edit.setReadOnly(True)
        self.pack_edit.setAlignment(Qt.AlignCenter)
        ctrl_row.addWidget(self.pack_edit)

        self.rate_edit = QLineEdit("0.00")
        self.rate_edit.setFixedWidth(70)
        self.rate_edit.setAlignment(Qt.AlignRight)
        ctrl_row.addWidget(self.rate_edit)

        self.mrp_edit = QLineEdit("0.00")
        self.mrp_edit.setFixedWidth(70)
        self.mrp_edit.setAlignment(Qt.AlignRight)
        ctrl_row.addWidget(self.mrp_edit)

        self.qty_edit = QLineEdit("1")
        self.qty_edit.setFixedWidth(70)
        self.qty_edit.setAlignment(Qt.AlignCenter)
        ctrl_row.addWidget(self.qty_edit)

        self.free_qty_edit = QLineEdit("0")
        self.free_qty_edit.setFixedWidth(65)
        self.free_qty_edit.setAlignment(Qt.AlignCenter)
        ctrl_row.addWidget(self.free_qty_edit)

        self.less_edit = QLineEdit("0.00")
        self.less_edit.setFixedWidth(65)
        self.less_edit.setAlignment(Qt.AlignRight)
        ctrl_row.addWidget(self.less_edit)

        self.reason_combo = QComboBox()
        self.reason_combo.setFixedWidth(130)
        self.reason_combo.addItems([
            "Purchase Return",
            "Expiry Return",
            "Breakage/Damage",
            "Slow Moving",
            "Rate Difference",
            "Other",
        ])
        ctrl_row.addWidget(self.reason_combo)

        self.price_factor_combo = QComboBox()
        self.price_factor_combo.setFixedWidth(90)
        self.price_factor_combo.addItems(["RATE", "MRP"])
        ctrl_row.addWidget(self.price_factor_combo)

        self.add_btn = QPushButton("▼")
        self.add_btn.setToolTip("Add item to return list")
        self.add_btn.setFixedWidth(40)
        self.add_btn.setFixedHeight(30)
        self.add_btn.setStyleSheet(
            f"QPushButton {{ background-color: {p['accent']}; color: white; "
            f"font-weight: bold; font-size: 14px; border: none; border-radius: 3px; }}"
            f"QPushButton:hover {{ background-color: {p['accent_hover']}; }}"
        )
        ctrl_row.addWidget(self.add_btn)

        layout.addLayout(ctrl_row)

        self.item_combo.selection_changed.connect(self._on_item_selected)

    def set_supplier_id(self, supplier_id: int | None):
        self._supplier_id = supplier_id
        # Reload batches if item is currently selected
        item_id = self.item_combo.currentData()
        if item_id:
            self._reload_batches(item_id)

    def load_items(self):
        items = ItemDAO.get_all()
        list_items = [(it["item_name"], it["id"]) for it in items]
        self.item_combo.populate(list_items)

    def _on_item_selected(self, item_id: object):
        if not item_id:
            self.batch_combo.clear()
            self._clear_batch_fields()
            return
        self._reload_batches(int(item_id))

    def _on_expired_toggled(self, checked: bool):
        item_id = self.item_combo.currentData()
        if item_id:
            self._reload_batches(int(item_id))

    def _reload_batches(self, item_id: int):
        self.batch_combo.blockSignals(True)
        self.batch_combo.clear()
        self._clear_batch_fields()

        batches = DebitNoteDAO.get_batches_for_supplier_item(
            self._supplier_id, item_id, expired_only=self.expired_only_cb.isChecked()
        )
        self.batch_combo.addItem("-- Select Batch --", None)
        for b in batches:
            b_no = b.get("batch_no", "")
            exp = b.get("expiry", "")
            stock = b.get("stock_qty", 0.0)
            tag = " [EXP]" if b.get("is_expired") else ""
            label = f"{b_no} (Exp: {exp}, Stk: {stock:g}){tag}"
            self.batch_combo.addItem(label, b, raw_name=b_no)
        self.batch_combo.blockSignals(False)

        if len(batches) == 1:
            self.batch_combo.setCurrentIndex(1)
            self._on_batch_selected(batches[0])
        else:
            self.batch_combo.setCurrentIndex(0)

    def _on_batch_selected(self, batch_data: object):
        if not batch_data or not isinstance(batch_data, dict):
            self._clear_batch_fields()
            return
        b = batch_data
        self.expiry_edit.setText(b.get("expiry", ""))
        self.pack_edit.setText(str(b.get("pack_size") or "1"))
        self.rate_edit.setText(f"{b.get('purchase_rate', 0.0):.2f}")
        self.mrp_edit.setText(f"{b.get('mrp', 0.0):.2f}")

    def _on_batch_changed(self, idx: int):
        b = self.batch_combo.currentData()
        self._on_batch_selected(b)

    def _clear_batch_fields(self):
        self.expiry_edit.clear()
        self.pack_edit.clear()
        self.rate_edit.setText("0.00")
        self.mrp_edit.setText("0.00")
        self.qty_edit.setText("1")
        self.free_qty_edit.setText("0")
        self.less_edit.setText("0.00")

    def clear(self):
        self.item_combo.clear_selection()
        self.batch_combo.clear_selection()
        self._clear_batch_fields()

    def get_current_data(self) -> dict | None:
        item_id = self.item_combo.currentData()
        batch_data = self.batch_combo.currentData()
        if not item_id or not batch_data:
            return None

        return {
            "item_id": int(item_id),
            "item_name": self.item_combo.currentText(),
            "stock_batch_id": batch_data["id"],
            "batch_no": batch_data["batch_no"],
            "expiry": self.expiry_edit.text().strip(),
            "pack_size": self.pack_edit.text().strip() or "1",
            "rate": _safe_float(self.rate_edit.text(), 0.0),
            "mrp": _safe_float(self.mrp_edit.text(), 0.0),
            "return_qty": _safe_float(self.qty_edit.text(), 0.0),
            "free_qty": _safe_float(self.free_qty_edit.text(), 0.0),
            "less_pct": _safe_float(self.less_edit.text(), 0.0),
            "return_reason": self.reason_combo.currentText(),
            "price_factor": self.price_factor_combo.currentText(),
            "available_stock": float(batch_data.get("stock_qty", 0.0)),
        }


# ======================================================================
# Debit Note Entry Dialog (Modal Form)
# ======================================================================

class _DebitNoteEntryDialog(QDialog):
    """Modal dialog for creating / editing a debit note."""

    def __init__(self, parent: QWidget | None = None, *, dn: dict | None = None):
        super().__init__(parent)
        self._dn = dn
        self._saved = False
        self._item_rows: list[_ReturnItemRow] = []

        title_text = "Edit Debit Note" if dn else "New Debit Note"
        self.setWindowTitle(f"Debit Note - {title_text}")
        self.setMinimumWidth(1260)
        self.setMinimumHeight(680)
        self.setModal(True)

        p = _get_palette()
        self.setStyleSheet(
            f"QDialog {{ background-color: {p['surface']}; color: {p['text']}; }}"
            f"QLineEdit, QDateEdit, QComboBox {{ background-color: {p['surface']}; color: {p['text']}; "
            f"border: 1px solid {p['border']}; border-radius: 2px; padding: 4px; font-size: 13px; font-family: 'Segoe UI'; }}"
            f"QLineEdit:focus, QDateEdit:focus, QComboBox:focus {{ border: 1px solid {p['accent']}; }}"
            + date_subcontrols(p, width=22)
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        # 1. Top banner strip (Pharma-WINNER style)
        self._build_top_banner(root, title_text)

        # 2. Header row (Type, Date, Supplier, Less)
        self._build_header_row(root)

        # 3. Item Entry Bar
        self._entry_bar = _ItemEntryBar(self)
        self._entry_bar.add_btn.clicked.connect(self._on_add_item)
        root.addWidget(self._entry_bar)

        # 4. Items table
        self._build_items_table(root)

        # 5. Bottom summary bar
        self._build_bottom_bar(root)

        # Load initial data
        self._load_suppliers()
        self._entry_bar.load_items()

        if dn:
            self._populate_dn(dn)
        else:
            self._init_new_dn()

    def _build_top_banner(self, parent_layout: QVBoxLayout, title_text: str):
        p = _get_palette()
        banner = QFrame()
        banner.setFixedHeight(42)
        banner.setStyleSheet(
            f"background-color: {p['accent']}; border-radius: 3px; color: white;"
        )
        bl = QHBoxLayout(banner)
        bl.setContentsMargins(12, 0, 12, 0)
        bl.setSpacing(16)

        self.title_lbl = QLabel(title_text)
        self.title_lbl.setStyleSheet("font-size: 16px; font-weight: bold; color: white; background: transparent;")
        bl.addWidget(self.title_lbl)

        bl.addStretch()

        bl.addWidget(self._banner_lbl("Voucher No"))
        self.voucher_no_lbl = QLabel("")
        self.voucher_no_lbl.setStyleSheet("font-size: 15px; font-weight: bold; color: white; background: transparent;")
        bl.addWidget(self.voucher_no_lbl)

        bl.addWidget(self._banner_lbl("Date"))
        self.banner_date_lbl = QLabel("")
        self.banner_date_lbl.setStyleSheet("font-size: 14px; font-weight: bold; color: white; background: transparent;")
        bl.addWidget(self.banner_date_lbl)

        bl.addWidget(self._banner_lbl("Time"))
        self.banner_time_lbl = QLabel("")
        self.banner_time_lbl.setStyleSheet("font-size: 14px; font-weight: bold; color: white; background: transparent;")
        bl.addWidget(self.banner_time_lbl)

        parent_layout.addWidget(banner)

    def _banner_lbl(self, text: str) -> QLabel:
        lbl = QLabel(text + ":")
        lbl.setStyleSheet("color: #e0f2fe; font-size: 13px; font-weight: bold; background: transparent;")
        return lbl

    def _build_header_row(self, parent_layout: QVBoxLayout):
        p = _get_palette()
        frame = QFrame()
        frame.setStyleSheet(f"background-color: {p['surface']}; border: 1px solid {p['border']}; border-radius: 3px;")
        hl = QHBoxLayout(frame)
        hl.setContentsMargins(10, 8, 10, 8)
        hl.setSpacing(12)

        def _hdr_lbl(text: str):
            l = QLabel(text)
            l.setStyleSheet(f"color: {p['text']}; font-size: 13px; font-weight: bold; background: transparent;")
            return l

        hl.addWidget(_hdr_lbl("Type :"))
        self.type_combo = QComboBox()
        self.type_combo.addItems(["Supplier"])
        self.type_combo.setFixedWidth(110)
        hl.addWidget(self.type_combo)

        hl.addWidget(_hdr_lbl("Date :"))
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("dd/MM/yyyy")
        self.date_edit.setFixedWidth(120)
        self.date_edit.dateChanged.connect(self._on_date_changed)
        hl.addWidget(self.date_edit)

        hl.addWidget(_hdr_lbl("Supplier :"))
        self.supplier_combo = SearchableComboBox(placeholder="-- Select Supplier --")
        self.supplier_combo.setMinimumWidth(320)
        self.supplier_combo.selection_changed.connect(self._on_supplier_changed)
        hl.addWidget(self.supplier_combo, 1)

        hl.addWidget(_hdr_lbl("Less :"))
        self.header_less_edit = QLineEdit("0.00")
        self.header_less_edit.setFixedWidth(80)
        self.header_less_edit.setAlignment(Qt.AlignRight)
        self.header_less_edit.textChanged.connect(self._recalc_totals)
        hl.addWidget(self.header_less_edit)

        parent_layout.addWidget(frame)

    def _build_items_table(self, parent_layout: QVBoxLayout):
        p = _get_palette()
        self._table = QTableWidget()
        self._table.setColumnCount(13)
        self._table.setHorizontalHeaderLabels([
            "ItemName", "PackSize", "BatchNo", "Expiry", "Rate", "MRP",
            "Qty", "FreeQty", "DiscAmt", "Amount", "Reason", "PriceFactor", "Del"
        ])
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(True)
        self._table.setAlternatingRowColors(False)

        hv = self._table.horizontalHeader()
        hv.setSectionResizeMode(0, QHeaderView.Stretch)
        for i in range(1, 13):
            hv.setSectionResizeMode(i, QHeaderView.ResizeToContents)

        hv.setStyleSheet(
            f"QHeaderView::section {{ background-color: {p['surface']}; color: {p['text']}; "
            f"border: 1px solid {p['border']}; border-bottom: 2px solid {p['accent']}; "
            f"padding: 4px; font-weight: bold; font-size: 13px; font-family: 'Segoe UI'; }}"
        )
        self._table.setStyleSheet(
            f"QTableWidget {{ background-color: {p['surface']}; color: {p['text']}; "
            f"border: 1px solid {p['border']}; gridline-color: {p['border']}; "
            f"selection-background-color: {p['accent']}; selection-color: white; font-size: 13px; }}"
            f"QTableWidget::item {{ padding: 3px 6px; }}"
        )
        parent_layout.addWidget(self._table, 1)

    def _build_bottom_bar(self, parent_layout: QVBoxLayout):
        p = _get_palette()
        bar = QFrame()
        bar.setStyleSheet(f"background-color: {p['surface']}; border-top: 1px solid {p['border']};")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(10, 8, 10, 4)
        bl.setSpacing(16)

        def _bot_lbl(text: str):
            l = QLabel(text)
            l.setStyleSheet(f"color: {p['text']}; font-size: 13px; font-weight: bold; background: transparent;")
            return l

        bl.addWidget(_bot_lbl("Total Items :"))
        self.total_items_val = QLineEdit("0")
        self.total_items_val.setReadOnly(True)
        self.total_items_val.setFixedWidth(70)
        self.total_items_val.setAlignment(Qt.AlignCenter)
        bl.addWidget(self.total_items_val)

        bl.addWidget(_bot_lbl("Total Amount :"))
        self.total_amount_val = QLineEdit("0.00")
        self.total_amount_val.setReadOnly(True)
        self.total_amount_val.setFixedWidth(110)
        self.total_amount_val.setAlignment(Qt.AlignRight)
        self.total_amount_val.setStyleSheet(f"font-weight: bold; color: {p['accent']}; font-size: 14px;")
        bl.addWidget(self.total_amount_val)

        self.add_to_ledger_cb = QCheckBox("Amount Add to Supplier Ledger")
        self.add_to_ledger_cb.setStyleSheet(f"color: {p['text']}; font-size: 13px; font-weight: bold;")
        bl.addWidget(self.add_to_ledger_cb)

        bl.addStretch()

        self.save_btn = QPushButton("Save")
        self.save_btn.setFixedWidth(100)
        self.save_btn.setFixedHeight(32)
        self.save_btn.setStyleSheet(
            f"QPushButton {{ background-color: {p['accent']}; color: white; "
            f"font-weight: bold; font-size: 14px; border: none; border-radius: 3px; }}"
            f"QPushButton:hover {{ background-color: {p['accent_hover']}; }}"
        )
        self.save_btn.clicked.connect(self._on_save)
        bl.addWidget(self.save_btn)

        self.close_btn = QPushButton("Close")
        self.close_btn.setFixedWidth(100)
        self.close_btn.setFixedHeight(32)
        self.close_btn.setStyleSheet(
            f"QPushButton {{ background-color: {p['border']}; color: {p['text']}; "
            f"font-size: 14px; border: none; border-radius: 3px; }}"
            f"QPushButton:hover {{ background-color: #94a3b8; }}"
        )
        self.close_btn.clicked.connect(self.reject)
        bl.addWidget(self.close_btn)

        parent_layout.addWidget(bar)

    def _load_suppliers(self):
        suppliers = SupplierDAO.get_all()
        items = [(s["supplier_name"], s["id"]) for s in suppliers]
        self.supplier_combo.populate(items)

    def _on_supplier_changed(self, supplier_id: object):
        sid = int(supplier_id) if supplier_id else None
        self._entry_bar.set_supplier_id(sid)

    def _on_date_changed(self, qdate: QDate):
        self.banner_date_lbl.setText(qdate.toString("dd-MM-yyyy"))

    def _init_new_dn(self):
        from core.doc_formatter import format_document_number
        now = datetime.now()
        qdate = QDate(now.year, now.month, now.day)
        self.date_edit.setDate(qdate)
        self.banner_date_lbl.setText(now.strftime("%d-%m-%Y"))
        self.banner_time_lbl.setText(now.strftime("%I:%M %p"))

        full_vno = DebitNoteDAO.generate_next_voucher_no()
        self._full_voucher_no = full_vno
        self.voucher_no_lbl.setText(format_document_number(full_vno))
        self.voucher_no_lbl.setToolTip(f"Full Voucher: {full_vno}")

        # Ledger posting is checked by default for active accounting flow
        self.add_to_ledger_cb.setChecked(True)

    def _populate_dn(self, dn: dict):
        from core.doc_formatter import format_document_number
        full_vno = dn.get("voucher_no", "")
        self._full_voucher_no = full_vno
        self.voucher_no_lbl.setText(format_document_number(full_vno))
        self.voucher_no_lbl.setToolTip(f"Full Voucher: {full_vno}")

        vd = dn.get("voucher_date", "")
        if vd:
            parts = vd.split("-")
            self.date_edit.setDate(QDate(int(parts[0]), int(parts[1]), int(parts[2])))
        self.banner_time_lbl.setText(dn.get("voucher_time", ""))

        sid = dn.get("supplier_id")
        if sid:
            idx = self.supplier_combo.findData(sid)
            if idx >= 0:
                self.supplier_combo.setCurrentIndex(idx)

        # Checkbox state
        is_posted = dn.get("added_to_ledger") == "Y"
        self.add_to_ledger_cb.setChecked(is_posted)

        # Load items
        items = DebitNoteDAO.get_items(dn["id"])
        self._item_rows.clear()
        for it in items:
            self._item_rows.append(
                _ReturnItemRow(
                    item_id=it["item_id"],
                    item_name=it.get("item_name", ""),
                    stock_batch_id=it["stock_batch_id"],
                    batch_no=it.get("batch_no", ""),
                    expiry=it.get("expiry", ""),
                    pack_size=str(it.get("pack_size") or "1"),
                    rate=float(it.get("rate", 0.0)),
                    mrp=float(it.get("mrp", 0.0)),
                    return_qty=float(it.get("return_qty", 0.0)),
                    free_qty=float(it.get("free_qty", 0.0)),
                    less_amount=float(it.get("less_amount", 0.0)),
                    amount=float(it.get("amount", 0.0)),
                    return_reason=it.get("return_reason", "Purchase Return"),
                    price_factor="RATE" if it.get("price_factor", 1.0) == 1.0 else "MRP",
                    price_factor_num=float(it.get("price_factor", 1.0)),
                )
            )
        self._refresh_table()
        self._recalc_totals()

    def _on_add_item(self):
        data = self._entry_bar.get_current_data()
        if not data:
            QMessageBox.warning(self, "Validation", "Please select an item and batch.")
            return

        sid = self.supplier_combo.currentData()
        if not sid:
            QMessageBox.warning(self, "Validation", "Please select a supplier first.")
            return

        ret_qty = data["return_qty"]
        free_qty = data["free_qty"]
        if ret_qty <= 0:
            QMessageBox.warning(self, "Validation", "Return quantity must be greater than 0.")
            return

        p_factor = pack_factor(data["pack_size"])
        loose_deduction = (ret_qty + free_qty) * p_factor
        available_stock = data["available_stock"]

        # Also account for any same-batch items already added to the table
        already_added_loose = sum(
            (r.return_qty + r.free_qty) * pack_factor(r.pack_size)
            for r in self._item_rows
            if r.stock_batch_id == data["stock_batch_id"]
        )

        if (loose_deduction + already_added_loose) > available_stock:
            max_packs = max(0.0, (available_stock - already_added_loose) / p_factor)
            QMessageBox.warning(
                self,
                "Insufficient Stock",
                f"Batch {data['batch_no']} has {available_stock:g} loose units in stock.\n"
                f"Cannot return {loose_deduction + already_added_loose:g} loose units "
                f"(max available: {max_packs:g} packs).",
            )
            return

        base_price = data["rate"] if data["price_factor"] == "RATE" else data["mrp"]
        gross = ret_qty * base_price
        less_pct = data["less_pct"]
        disc_amt = round(gross * (less_pct / 100.0), 2)
        amount = round(gross - disc_amt, 2)

        row = _ReturnItemRow(
            item_id=data["item_id"],
            item_name=data["item_name"],
            stock_batch_id=data["stock_batch_id"],
            batch_no=data["batch_no"],
            expiry=data["expiry"],
            pack_size=data["pack_size"],
            rate=data["rate"],
            mrp=data["mrp"],
            return_qty=ret_qty,
            free_qty=free_qty,
            less_amount=disc_amt,
            amount=amount,
            return_reason=data["return_reason"],
            price_factor=data["price_factor"],
            price_factor_num=1.0,
        )
        self._item_rows.append(row)
        self._refresh_table()
        self._recalc_totals()
        self._entry_bar.clear()

    def _refresh_table(self):
        p = _get_palette()
        self._table.setRowCount(len(self._item_rows))
        for i, r in enumerate(self._item_rows):
            self._table.setItem(i, 0, QTableWidgetItem(r.item_name))
            self._table.setItem(i, 1, QTableWidgetItem(r.pack_size))
            self._table.setItem(i, 2, QTableWidgetItem(r.batch_no))
            self._table.setItem(i, 3, QTableWidgetItem(r.expiry))

            rate_item = QTableWidgetItem(f"{r.rate:.2f}")
            rate_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._table.setItem(i, 4, rate_item)

            mrp_item = QTableWidgetItem(f"{r.mrp:.2f}")
            mrp_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._table.setItem(i, 5, mrp_item)

            qty_item = QTableWidgetItem(f"{r.return_qty:g}")
            qty_item.setTextAlignment(Qt.AlignCenter)
            self._table.setItem(i, 6, qty_item)

            free_item = QTableWidgetItem(f"{r.free_qty:g}")
            free_item.setTextAlignment(Qt.AlignCenter)
            self._table.setItem(i, 7, free_item)

            disc_item = QTableWidgetItem(f"{r.less_amount:.2f}")
            disc_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._table.setItem(i, 8, disc_item)

            amt_item = QTableWidgetItem(f"{r.amount:.2f}")
            amt_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._table.setItem(i, 9, amt_item)

            self._table.setItem(i, 10, QTableWidgetItem(r.return_reason))
            self._table.setItem(i, 11, QTableWidgetItem(r.price_factor))

            del_btn = QPushButton("Del")
            del_btn.setStyleSheet(
                "QPushButton { background-color: #ef4444; color: white; border: none; "
                "border-radius: 2px; font-weight: bold; font-size: 11px; padding: 2px; }"
                "QPushButton:hover { background-color: #dc2626; }"
            )
            del_btn.setFixedWidth(36)
            del_btn.clicked.connect(lambda _, idx=i: self._delete_row(idx))
            self._table.setCellWidget(i, 12, del_btn)

    def _delete_row(self, idx: int):
        if 0 <= idx < len(self._item_rows):
            self._item_rows.pop(idx)
            self._refresh_table()
            self._recalc_totals()

    def _recalc_totals(self):
        total_items = len(self._item_rows)
        subtotal = sum(r.amount for r in self._item_rows)
        header_less = _safe_float(self.header_less_edit.text(), 0.0)
        total_amount = max(0.0, round(subtotal - header_less, 2))

        self.total_items_val.setText(str(total_items))
        self.total_amount_val.setText(f"{total_amount:.2f}")

    def _on_save(self):
        try:
            financial_year.validate_transaction_date(self.date_edit.date().toString("yyyy-MM-dd"))
        except financial_year.FinancialYearError as exc:
            QMessageBox.warning(self, "Financial Year", str(exc))
            return

        sid = self.supplier_combo.currentData()
        if not sid:
            QMessageBox.warning(self, "Validation", "Supplier is required.")
            return

        if not self._item_rows:
            QMessageBox.warning(self, "Validation", "At least one item is required.")
            return

        self._recalc_totals()
        total_amount = float(self.total_amount_val.text())
        add_to_ledger = self.add_to_ledger_cb.isChecked()

        voucher_date = self.date_edit.date().toString("yyyy-MM-dd")
        voucher_time = self.banner_time_lbl.text() or datetime.now().strftime("%I:%M %p")
        dn_date = voucher_date

        header = {
            "voucher_no": getattr(self, "_full_voucher_no", ""),
            "voucher_date": voucher_date,
            "voucher_time": voucher_time,
            "dn_date": dn_date,
            "dn_type": self.type_combo.currentText() or "Supplier",
            "supplier_id": int(sid),
            "total_amount": total_amount,
            "ledger_amount": total_amount if add_to_ledger else 0.0,
            "add_to_ledger": add_to_ledger,
            "remarks": "",
        }
        items_data = [r.to_dict() for r in self._item_rows]

        try:
            if self._dn:
                DebitNoteDAO.update_debit_note(self._dn["id"], header, items_data)
            else:
                DebitNoteDAO.insert_debit_note(header, items_data)
            self._saved = True
            QMessageBox.information(self, "Success", "Debit Note saved successfully.")
            self.accept()
        except ValueError as e:
            QMessageBox.warning(self, "Validation", str(e))
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save debit note:\n{e}")

    @property
    def was_saved(self) -> bool:
        return self._saved


# ======================================================================
# Debit Note PAGE (List Screen)
# ======================================================================

class DebitNotePage(QWidget):
    """Debit Note screen with history list matching Pharma-WINNER reference."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        p = _get_palette()
        self.setStyleSheet(f"background-color: {p['bg']};")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._stack = QStackedWidget()
        root.addWidget(self._stack)

        self._history_page = self._build_history_page()
        self._stack.addWidget(self._history_page)

        self._refresh_history()

    def _build_history_page(self) -> QWidget:
        p = _get_palette()
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 1. Top cyan banner: Debit Note List
        banner = QFrame()
        banner.setFixedHeight(46)
        banner.setStyleSheet(
            f"background-color: {p['accent']}; color: white; border-bottom: 2px solid {p['accent_hover']};"
        )
        bl = QHBoxLayout(banner)
        bl.setContentsMargins(16, 0, 16, 0)

        # Actions at top left: New, Edit, Print, Delete
        new_btn = QPushButton("New")
        new_btn.setToolTip("Create New Debit Note (Return to Supplier)")
        new_btn.setFixedWidth(75)
        new_btn.setFixedHeight(30)
        new_btn.setStyleSheet(
            "QPushButton { background-color: #0284c7; color: white; font-weight: bold; "
            "border: none; border-radius: 3px; font-size: 13px; }"
            "QPushButton:hover { background-color: #0369a1; }"
        )
        new_btn.clicked.connect(self._on_new)
        bl.addWidget(new_btn)

        edit_btn = QPushButton("Edit")
        edit_btn.setToolTip("Edit Selected Debit Note")
        edit_btn.setFixedWidth(75)
        edit_btn.setFixedHeight(30)
        edit_btn.setStyleSheet(
            "QPushButton { background-color: #0284c7; color: white; font-weight: bold; "
            "border: none; border-radius: 3px; font-size: 13px; }"
            "QPushButton:hover { background-color: #0369a1; }"
        )
        edit_btn.clicked.connect(self._on_edit)
        bl.addWidget(edit_btn)

        print_btn = QPushButton("Print")
        print_btn.setToolTip("Print / Export Debit Note PDF")
        print_btn.setFixedWidth(75)
        print_btn.setFixedHeight(30)
        print_btn.setStyleSheet(
            "QPushButton { background-color: #0284c7; color: white; font-weight: bold; "
            "border: none; border-radius: 3px; font-size: 13px; }"
            "QPushButton:hover { background-color: #0369a1; }"
        )
        print_btn.clicked.connect(self._on_print)
        bl.addWidget(print_btn)

        del_btn = QPushButton("Delete")
        del_btn.setToolTip("Delete Selected Debit Note and Reverse Stock/Ledger")
        del_btn.setFixedWidth(75)
        del_btn.setFixedHeight(30)
        del_btn.setStyleSheet(
            "QPushButton { background-color: #dc2626; color: white; font-weight: bold; "
            "border: none; border-radius: 3px; font-size: 13px; }"
            "QPushButton:hover { background-color: #b91c1c; }"
        )
        del_btn.clicked.connect(self._on_delete)
        bl.addWidget(del_btn)

        bl.addStretch()

        title_lbl = QLabel("Debit Note List")
        title_lbl.setStyleSheet("font-size: 18px; font-weight: bold; color: white; background: transparent;")
        bl.addWidget(title_lbl)

        bl.addStretch()
        layout.addWidget(banner)

        # 2. Filter row: Date range + Supplier search
        filter_bar = QFrame()
        filter_bar.setFixedHeight(46)
        filter_bar.setStyleSheet(f"background-color: {p['surface']}; border-bottom: 1px solid {p['border']};")
        fl = QHBoxLayout(filter_bar)
        fl.setContentsMargins(12, 0, 12, 0)
        fl.setSpacing(10)

        def _flbl(text: str):
            l = QLabel(text)
            l.setStyleSheet(f"color: {p['text']}; font-size: 13px; font-weight: bold; background: transparent;")
            return l

        self._filter_from = QDateEdit()
        self._filter_from.setCalendarPopup(True)
        self._filter_from.setDisplayFormat("dd/MM/yyyy")
        self._filter_from.setFixedWidth(115)

        self._filter_to = QDateEdit()
        self._filter_to.setCalendarPopup(True)
        self._filter_to.setDisplayFormat("dd/MM/yyyy")
        self._filter_to.setFixedWidth(115)

        # Initialize filter dates from active financial year or current date
        fy = financial_year.get_active_financial_year()
        if fy:
            s_parts = fy["start_date"].split("-")
            e_parts = fy["end_date"].split("-")
            self._filter_from.setDate(QDate(int(s_parts[0]), int(s_parts[1]), int(s_parts[2])))
            self._filter_to.setDate(QDate(int(e_parts[0]), int(e_parts[1]), int(e_parts[2])))
        else:
            now = datetime.now()
            self._filter_from.setDate(QDate(now.year, 1, 1))
            self._filter_to.setDate(QDate(now.year, 12, 31))

        fl.addWidget(self._filter_from)
        fl.addWidget(_flbl("VhDate"))
        fl.addWidget(self._filter_to)

        go_btn = QPushButton("Go")
        go_btn.setFixedWidth(50)
        go_btn.setFixedHeight(28)
        go_btn.setStyleSheet(
            f"QPushButton {{ background-color: {p['accent']}; color: white; "
            f"font-weight: bold; font-size: 13px; border: none; border-radius: 2px; }}"
            f"QPushButton:hover {{ background-color: {p['accent_hover']}; }}"
        )
        go_btn.clicked.connect(self._refresh_history)
        fl.addWidget(go_btn)

        fl.addStretch()

        fl.addWidget(_flbl("Supplier"))
        self._filter_supplier = SearchableComboBox(placeholder="[Search Supplier]")
        self._filter_supplier.setFixedWidth(240)
        sup_items = [("All Suppliers", None)] + [(s["supplier_name"], s["id"]) for s in SupplierDAO.get_all()]
        self._filter_supplier.populate(sup_items)
        self._filter_supplier.setCurrentIndex(0)
        fl.addWidget(self._filter_supplier)

        filter_btn = QPushButton("Filter")
        filter_btn.setFixedWidth(65)
        filter_btn.setFixedHeight(28)
        filter_btn.setStyleSheet(
            f"QPushButton {{ background-color: {p['accent']}; color: white; "
            f"font-weight: bold; font-size: 13px; border: none; border-radius: 2px; }}"
            f"QPushButton:hover {{ background-color: {p['accent_hover']}; }}"
        )
        filter_btn.clicked.connect(self._refresh_history)
        fl.addWidget(filter_btn)

        layout.addWidget(filter_bar)

        # 3. History table: VhType | VhNo | VhDate | VhTime | DNDate | DNType | Name | Amount
        self._hist_table = QTableWidget()
        self._hist_table.setColumnCount(8)
        self._hist_table.setHorizontalHeaderLabels([
            "VhType", "VhNo", "VhDate", "VhTime", "DNDate", "DNType", "Name", "Amount"
        ])
        self._hist_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._hist_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._hist_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._hist_table.verticalHeader().setVisible(False)
        self._hist_table.setShowGrid(True)
        self._hist_table.setAlternatingRowColors(False)
        self._hist_table.setSortingEnabled(True)
        self._hist_table.cellDoubleClicked.connect(lambda row, col: self._on_edit())

        hv = self._hist_table.horizontalHeader()
        hv.setSectionResizeMode(6, QHeaderView.Stretch)  # Name column stretches
        for c in [0, 1, 2, 3, 4, 5, 7]:
            hv.setSectionResizeMode(c, QHeaderView.ResizeToContents)

        hv.setStyleSheet(
            f"QHeaderView::section {{ background-color: {p['surface']}; color: {p['text']}; "
            f"border: 1px solid {p['border']}; border-bottom: 2px solid {p['accent']}; "
            f"padding: 5px; font-weight: bold; font-size: 13px; font-family: 'Segoe UI'; }}"
        )
        self._hist_table.setStyleSheet(
            f"QTableWidget {{ background-color: {p['surface']}; color: {p['text']}; "
            f"border: 1px solid {p['border']}; gridline-color: {p['border']}; "
            f"selection-background-color: {p['accent']}; selection-color: white; font-size: 13px; }}"
            f"QTableWidget::item {{ padding: 3px 6px; }}"
        )
        layout.addWidget(self._hist_table, 1)

        return page

    def _refresh_history(self):
        from_date = self._filter_from.date().toString("yyyy-MM-dd")
        to_date = self._filter_to.date().toString("yyyy-MM-dd")
        sup_id = self._filter_supplier.currentData()
        sid = int(sup_id) if sup_id else None

        dns = DebitNoteDAO.get_all_filtered(
            voucher_from=from_date,
            voucher_to=to_date,
            supplier_id=sid,
        )

        self._hist_table.setSortingEnabled(False)
        self._hist_table.setRowCount(len(dns))

        for i, dn in enumerate(dns):
            from core.doc_formatter import format_document_number
            raw_vno = dn.get("voucher_no", "")
            disp_no = format_document_number(raw_vno)

            item_type = QTableWidgetItem("Debit Note")
            item_type.setData(Qt.UserRole, dn["id"])
            self._hist_table.setItem(i, 0, item_type)

            no_item = QTableWidgetItem(disp_no)
            no_item.setToolTip(f"Full Voucher: {raw_vno}")
            self._hist_table.setItem(i, 1, no_item)

            # Dates in dd/MM/yyyy
            vd = dn.get("voucher_date", "")
            if vd and "-" in vd:
                p_date = vd.split("-")
                vd_disp = f"{p_date[2]}/{p_date[1]}/{p_date[0]}"
            else:
                vd_disp = vd
            self._hist_table.setItem(i, 2, QTableWidgetItem(vd_disp))

            self._hist_table.setItem(i, 3, QTableWidgetItem(dn.get("voucher_time", "")))

            dd = dn.get("dn_date", "")
            if dd and "-" in dd:
                p_date = dd.split("-")
                dd_disp = f"{p_date[2]}/{p_date[1]}/{p_date[0]}"
            else:
                dd_disp = dd
            self._hist_table.setItem(i, 4, QTableWidgetItem(dd_disp))

            self._hist_table.setItem(i, 5, QTableWidgetItem(dn.get("dn_type", "Supplier")))
            self._hist_table.setItem(i, 6, QTableWidgetItem(dn.get("supplier_name", "")))

            amt_item = QTableWidgetItem(f"{dn.get('total_amount', 0.0):.2f}")
            amt_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._hist_table.setItem(i, 7, amt_item)

        self._hist_table.setSortingEnabled(True)

    def _selected_id(self) -> int | None:
        rows = self._hist_table.selectionModel().selectedRows()
        if not rows:
            return None
        row = rows[0].row()
        item = self._hist_table.item(row, 0)
        return item.data(Qt.UserRole) if item else None

    def _on_new(self):
        dlg = _DebitNoteEntryDialog(self)
        if dlg.exec() == QDialog.Accepted and dlg.was_saved:
            self._refresh_history()

    def _on_edit(self):
        dn_id = self._selected_id()
        if not dn_id:
            QMessageBox.information(self, "Edit Debit Note", "Please select a debit note from the list.")
            return

        dn = DebitNoteDAO.get_by_id(dn_id)
        if not dn:
            QMessageBox.warning(self, "Error", f"Debit note #{dn_id} not found.")
            return

        dlg = _DebitNoteEntryDialog(self, dn=dn)
        if dlg.exec() == QDialog.Accepted and dlg.was_saved:
            self._refresh_history()

    def _on_delete(self):
        dn_id = self._selected_id()
        if not dn_id:
            QMessageBox.information(self, "Delete Debit Note", "Please select a debit note to delete.")
            return

        dn = DebitNoteDAO.get_by_id(dn_id)
        if not dn:
            return

        msg = (
            f"Are you sure you want to delete Debit Note {dn['voucher_no']}?\n\n"
            f"Supplier: {dn.get('supplier_name', '')}\n"
            f"Amount: {dn.get('total_amount', 0.0):.2f}\n\n"
            "This will reverse stock deductions and any ledger accounting entries."
        )
        res = QMessageBox.question(
            self,
            "Confirm Delete",
            msg,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if res == QMessageBox.Yes:
            try:
                DebitNoteDAO.delete_debit_note(dn_id)
                QMessageBox.information(self, "Deleted", f"Debit Note {dn['voucher_no']} deleted successfully.")
                self._refresh_history()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to delete debit note:\n{e}")

    def _on_print(self):
        dn_id = self._selected_id()
        if not dn_id:
            QMessageBox.information(self, "Print Debit Note", "Please select a debit note from the list.")
            return

        dn = DebitNoteDAO.get_by_id(dn_id)
        if not dn:
            return

        default_name = f"{dn['voucher_no']}.pdf".replace("/", "-")
        pdf_path, _ = QFileDialog.getSaveFileName(
            self, "Save Debit Note PDF", default_name, "PDF Files (*.pdf)"
        )
        if not pdf_path:
            return

        try:
            generate_debit_note(dn_id, pdf_path)
            QMessageBox.information(self, "Success", f"Debit Note PDF generated at:\n{pdf_path}")
        except DocumentPrintError as e:
            QMessageBox.warning(self, "Print Error", str(e))
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to generate PDF:\n{e}")
