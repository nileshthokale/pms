from __future__ import annotations

from datetime import datetime

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
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from database.credit_note_dao import CreditNoteDAO
from database import auth
from database import financial_year
from database.document_printing import DocumentPrintError, generate_credit_note
from database.customer_dao import CustomerDAO
from database.item_dao import ItemDAO
from database.stock_dao import StockDAO

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
    f"  font-weight: bold; font-size: 11px; font-family: 'Segoe UI'; }}"
    f"QPushButton:hover {{ background-color: #d32f2f; }}"
)

_BTN_GREEN_SM = (
    f"QPushButton {{ background-color: {_ACCENT}; color: white;"
    f"  border: none; border-radius: 2px; padding: 6px 14px;"
    f"  font-weight: bold; font-size: 12px; font-family: 'Segoe UI'; }}"
    f"QPushButton:hover {{ background-color: {_ACCENT_HOVER}; }}"
)

_LABEL_STYLE = f"color: {_TEXT}; font-size: 12px; font-family: 'Segoe UI'; background: transparent;"
_LABEL_DIM = f"color: {_TEXT_DIM}; font-size: 11px; font-family: 'Segoe UI'; background: transparent;"
_HEADER_LABEL = f"color: {_TEXT}; font-size: 11px; font-family: 'Segoe UI'; background: transparent; font-weight: bold;"

_GROUP_BOX = (
    f"QGroupBox {{"
    f"  color: {_TEXT}; font-weight: bold; font-size: 12px;"
    f"  border: 1px solid {_BORDER}; border-radius: 2px;"
    f"  margin-top: 10px; padding-top: 14px;"
    f"}}"
    f"QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 6px; }}"
)


def _safe_float(text: str, default: float = 0.0) -> float:
    try:
        return float(text.strip()) if text.strip() else default
    except ValueError:
        return default


def _make_edit(placeholder: str = "", width: int | None = None) -> QLineEdit:
    e = QLineEdit()
    e.setPlaceholderText(placeholder)
    e.setStyleSheet(_EDIT_STYLE)
    from PySide6.QtGui import QFont
    e.setFont(QFont("Segoe UI", 12))
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


# ======================================================================
# Return Item line data class
# ======================================================================

class _ReturnItemRow:
    """One line item being returned."""

    def __init__(self, item_id: int, item_name: str, stock_batch_id: int,
                 batch_no: str, expiry: str, pack_size: str,
                 mrp: float, purchase_rate: float,
                 return_qty: float, less_amount: float,
                 amount: float, return_reason: str, price_factor: float):
        self.item_id = item_id
        self.item_name = item_name
        self.stock_batch_id = stock_batch_id
        self.batch_no = batch_no
        self.expiry = expiry
        self.pack_size = pack_size
        self.mrp = mrp
        self.purchase_rate = purchase_rate
        self.return_qty = return_qty
        self.less_amount = less_amount
        self.amount = amount
        self.return_reason = return_reason
        self.price_factor = price_factor

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "stock_batch_id": self.stock_batch_id,
            "batch_no": self.batch_no,
            "expiry": self.expiry,
            "pack_size": self.pack_size,
            "rate": self.purchase_rate,
            "mrp": self.mrp,
            "return_qty": self.return_qty,
            "less_amount": self.less_amount,
            "amount": self.amount,
            "return_reason": self.return_reason,
            "price_factor": self.price_factor,
        }


# ======================================================================
# Item Entry Bar for Credit Note
# ======================================================================

class _ItemEntryBar(QWidget):
    """Horizontal bar for selecting item, batch, and entering return quantity."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)

        layout.addWidget(self._lbl("Item"))
        self.item_combo = _make_combo()
        self.item_combo.setMinimumWidth(200)
        layout.addWidget(self.item_combo)

        layout.addWidget(self._lbl("Batch"))
        self.batch_combo = _make_combo()
        self.batch_combo.setMinimumWidth(140)
        layout.addWidget(self.batch_combo)

        layout.addWidget(self._lbl("Pack"))
        self.pack_edit = _make_edit("", 70)
        self.pack_edit.setReadOnly(True)
        layout.addWidget(self.pack_edit)

        layout.addWidget(self._lbl("Exp"))
        self.expiry_edit = _make_edit("", 60)
        self.expiry_edit.setReadOnly(True)
        layout.addWidget(self.expiry_edit)

        layout.addWidget(self._lbl("MRP"))
        self.mrp_edit = _make_edit("", 65)
        self.mrp_edit.setReadOnly(True)
        layout.addWidget(self.mrp_edit)

        layout.addWidget(self._lbl("Stock"))
        self.stock_edit = _make_edit("", 55)
        self.stock_edit.setReadOnly(True)
        layout.addWidget(self.stock_edit)

        layout.addWidget(self._lbl("Ret Qty"))
        self.qty_edit = _make_edit("1", 55)
        layout.addWidget(self.qty_edit)

        layout.addWidget(self._lbl("Less Amt"))
        self.less_edit = _make_edit("0.00", 65)
        layout.addWidget(self.less_edit)

        layout.addWidget(self._lbl("Reason"))
        self.reason_edit = _make_edit("", 100)
        layout.addWidget(self.reason_edit)

        add_btn = QPushButton("+ Add")
        add_btn.setStyleSheet(_BTN_GREEN_SM)
        add_btn.setFixedWidth(60)
        layout.addWidget(add_btn)

        self.item_combo.currentIndexChanged.connect(self._on_item_changed)
        self.batch_combo.currentIndexChanged.connect(self._on_batch_changed)

    @staticmethod
    def _lbl(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(_LABEL_DIM)
        return lbl

    def load_items(self):
        self.item_combo.blockSignals(True)
        self.item_combo.clear()
        self.item_combo.addItem("-- Select --", None)
        items = ItemDAO.get_all()
        for it in items:
            self.item_combo.addItem(it["item_name"], it["id"])
        self.item_combo.blockSignals(False)

    def _on_item_changed(self, idx: int):
        item_id = self.item_combo.currentData()
        self.batch_combo.blockSignals(True)
        self.batch_combo.clear()
        self.pack_edit.clear()
        self.expiry_edit.clear()
        self.mrp_edit.clear()
        self.stock_edit.clear()
        if item_id is None:
            self.batch_combo.blockSignals(False)
            return
        batches = StockDAO.get_stock_batches_for_item(item_id)
        self.batch_combo.addItem("-- Select Batch --", None)
        for b in batches:
            exp = b.get("expiry", "")
            stock = b.get("stock_qty", 0.0)
            label = f"{b['batch_no']}  |  Exp: {exp}  |  Qty: {stock:.0f}"
            self.batch_combo.addItem(label, b["id"])
        self.batch_combo.blockSignals(False)

    def _on_batch_changed(self, idx: int):
        batch_id = self.batch_combo.currentData()
        if batch_id is None:
            self.pack_edit.clear()
            self.expiry_edit.clear()
            self.mrp_edit.clear()
            self.stock_edit.clear()
            return
        batch = StockDAO.get_stock_batch_by_id(batch_id)
        if batch:
            self.pack_edit.setText(batch.get("pack_size", ""))
            self.expiry_edit.setText(batch.get("expiry", ""))
            self.mrp_edit.setText(f"{batch.get('mrp', 0.0):.2f}")
            self.stock_edit.setText(f"{batch.get('stock_qty', 0.0):.0f}")

    def clear(self):
        self.item_combo.setCurrentIndex(0)
        self.batch_combo.clear()
        self.pack_edit.clear()
        self.expiry_edit.clear()
        self.mrp_edit.clear()
        self.stock_edit.clear()
        self.qty_edit.setText("1")
        self.less_edit.setText("0.00")
        self.reason_edit.clear()

    def get_current_data(self) -> dict | None:
        item_id = self.item_combo.currentData()
        batch_id = self.batch_combo.currentData()
        if item_id is None or batch_id is None:
            return None
        batch = StockDAO.get_stock_batch_by_id(batch_id)
        if not batch:
            return None
        return {
            "item_id": item_id,
            "item_name": self.item_combo.currentText(),
            "stock_batch_id": batch_id,
            "pack_size": batch.get("pack_size", ""),
            "batch_no": batch["batch_no"],
            "expiry": batch.get("expiry", ""),
            "mrp": batch.get("mrp", 0.0),
            "purchase_rate": batch.get("purchase_rate", 0.0),
            "stock_qty": batch.get("stock_qty", 0.0),
        }


# ======================================================================
# Credit Note Entry Dialog
# ======================================================================

class _CreditNoteEntryDialog(QDialog):
    """Modal dialog for creating / editing a credit note."""

    def __init__(self, parent: QWidget | None = None, *, cn: dict | None = None):
        super().__init__(parent)
        self._cn = cn
        self._saved = False
        self._item_rows: list[_ReturnItemRow] = []

        self.setWindowTitle("Credit Note")
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

        # -- Top: header + customer + item entry --
        top = QWidget()
        top_layout = QVBoxLayout(top)
        top_layout.setContentsMargins(8, 8, 8, 0)
        top_layout.setSpacing(4)

        self._build_header(top_layout)
        self._build_customer_bar(top_layout)

        self._entry_bar = _ItemEntryBar()
        top_layout.addWidget(self._entry_bar)

        root.addWidget(top)

        # -- Items table --
        self._build_items_table()
        root.addWidget(self._table_group, 1)

        # -- Totals row --
        self._build_totals()
        root.addWidget(self._totals_widget)

        # -- Button bar --
        btn_bar = QHBoxLayout()
        btn_bar.setContentsMargins(12, 6, 12, 8)
        btn_bar.addStretch()

        save_btn = QPushButton("Save Credit Note")
        save_btn.setStyleSheet(_BTN_SAVE)
        save_btn.clicked.connect(self._on_save)
        btn_bar.addWidget(save_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(_BTN_SECONDARY)
        cancel_btn.clicked.connect(self.reject)
        btn_bar.addWidget(cancel_btn)

        root.addLayout(btn_bar)

        # Wire add button
        for child in self._entry_bar.findChildren(QPushButton):
            if child.text() == "+ Add":
                child.clicked.connect(self._on_add_item)
                break

        self._set_voucher_no()
        self._set_current_date()

        if cn:
            self._populate_cn(cn)

    # ------------------------------------------------------------------
    # Header
    # ------------------------------------------------------------------

    def _build_header(self, parent_layout: QVBoxLayout):
        grp = QGroupBox("Credit Note Header")
        grp.setStyleSheet(_GROUP_BOX)
        grid = QGridLayout(grp)
        grid.setSpacing(6)
        grid.setContentsMargins(10, 18, 10, 8)

        row = 0
        grid.addWidget(self._lbl("Voucher No"), row, 0)
        self.voucher_no_edit = _make_edit()
        self.voucher_no_edit.setReadOnly(True)
        grid.addWidget(self.voucher_no_edit, row, 1)

        grid.addWidget(self._lbl("Date"), row, 2)
        self.voucher_date = _make_date()
        self.voucher_date.setMaximumWidth(130)
        grid.addWidget(self.voucher_date, row, 3)

        grid.addWidget(self._lbl("CN Date"), row, 4)
        self.cn_date = _make_date()
        self.cn_date.setMaximumWidth(130)
        grid.addWidget(self.cn_date, row, 5)

        grid.addWidget(self._lbl("CN Type"), row, 6)
        self.cn_type_combo = _make_combo()
        self.cn_type_combo.addItems(["Customer", "Supplier"])
        self.cn_type_combo.setMaximumWidth(110)
        grid.addWidget(self.cn_type_combo, row, 7)

        parent_layout.addWidget(grp)

    def _build_customer_bar(self, parent_layout: QVBoxLayout):
        grp = QGroupBox("Party Details")
        grp.setStyleSheet(_GROUP_BOX)
        grid = QGridLayout(grp)
        grid.setSpacing(6)
        grid.setContentsMargins(10, 18, 10, 8)

        row = 0
        grid.addWidget(self._lbl("Customer *"), row, 0)
        self.customer_combo = _make_combo()
        self.customer_combo.setMinimumWidth(200)
        grid.addWidget(self.customer_combo, row, 1)

        grid.addWidget(self._lbl("Remarks"), row, 2)
        self.remarks_edit = _make_edit()
        grid.addWidget(self.remarks_edit, row, 3)

        parent_layout.addWidget(grp)
        self._load_customers()

    def _load_customers(self):
        customers = CustomerDAO.get_all()
        self.customer_combo.addItem("-- Select Customer --", None)
        for c in customers:
            self.customer_combo.addItem(c["customer_name"], c["id"])

    def _set_voucher_no(self):
        if not self._cn:
            conn = None
            try:
                from database.connection import get_connection
                conn = get_connection()
                self.voucher_no_edit.setText(
                    CreditNoteDAO.generate_next_voucher_no(conn)
                )
            finally:
                if conn:
                    conn.close()

    def _set_current_date(self):
        from PySide6.QtCore import QDate
        now = datetime.now()
        qdate = QDate(now.year, now.month, now.day)
        self.voucher_date.setDate(qdate)
        self.cn_date.setDate(qdate)

    # ------------------------------------------------------------------
    # Items table
    # ------------------------------------------------------------------

    def _build_items_table(self):
        self._table_group = QGroupBox("Return Items")
        self._table_group.setStyleSheet(_GROUP_BOX)
        layout = QVBoxLayout(self._table_group)
        layout.setContentsMargins(6, 18, 6, 6)

        self._table = QTableWidget()
        self._table.setColumnCount(12)
        self._table.setHorizontalHeaderLabels([
            "#", "Item Name", "Pack Size", "Batch No", "Expiry",
            "MRP", "Rate", "Ret Qty", "Less Amt", "Amount", "Reason", "Del"
        ])
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(True)
        self._table.setAlternatingRowColors(False)
        self._table.horizontalHeader().setStretchLastSection(True)

        hv = self._table.horizontalHeader()
        for i in range(12):
            if i == 1:
                hv.setSectionResizeMode(i, QHeaderView.Stretch)
            else:
                hv.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        hv.setStyleSheet(
            f"QHeaderView::section {{"
            f"  background-color: {_SURFACE}; color: {_TEXT};"
            f"  border: none; border-bottom: 2px solid {_ACCENT};"
            f"  padding: 2px 5px; font-weight: bold; font-size: 9pt;"
            f"  font-family: 'Segoe UI';"
            f"}}"
        )
        self._table.setStyleSheet(
            f"QTableWidget {{"
            f"  background-color: {_DARK_BG}; color: {_TEXT};"
            f"  border: 1px solid {_BORDER}; gridline-color: {_BORDER};"
            f"  font-size: 11px; font-family: 'Segoe UI';"
            f"  selection-background-color: {_ACCENT};"
            f"  selection-color: white;"
            f"}}"
            f"QTableWidget::item {{ padding: 2px; }}"
        )
        layout.addWidget(self._table, 1)

    def _on_add_item(self):
        data = self._entry_bar.get_current_data()
        if data is None:
            QMessageBox.warning(self, "Validation", "Please select an item and batch.")
            return

        return_qty = _safe_float(self._entry_bar.qty_edit.text(), 0.0)
        if return_qty <= 0:
            QMessageBox.warning(self, "Validation", "Return Quantity must be greater than 0.")
            return

        mrp = data["mrp"]
        purchase_rate = data["purchase_rate"]
        less_amount = _safe_float(self._entry_bar.less_edit.text())
        amount = round(return_qty * purchase_rate - less_amount, 2)
        reason = self._entry_bar.reason_edit.text().strip()
        price_factor = 1.0

        row = _ReturnItemRow(
            item_id=data["item_id"],
            item_name=data["item_name"],
            stock_batch_id=data["stock_batch_id"],
            batch_no=data["batch_no"],
            expiry=data["expiry"],
            pack_size=data["pack_size"],
            mrp=mrp,
            purchase_rate=purchase_rate,
            return_qty=return_qty,
            less_amount=less_amount,
            amount=amount,
            return_reason=reason,
            price_factor=price_factor,
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
            self._table.setItem(i, 3, QTableWidgetItem(r.batch_no))
            self._table.setItem(i, 4, QTableWidgetItem(r.expiry))

            mrp_item = QTableWidgetItem(f"{r.mrp:.2f}")
            mrp_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._table.setItem(i, 5, mrp_item)

            rate_item = QTableWidgetItem(f"{r.purchase_rate:.2f}")
            rate_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._table.setItem(i, 6, rate_item)

            qty_item = QTableWidgetItem(f"{r.return_qty:.0f}")
            qty_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._table.setItem(i, 7, qty_item)

            less_item = QTableWidgetItem(f"{r.less_amount:.2f}")
            less_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._table.setItem(i, 8, less_item)

            amt_item = QTableWidgetItem(f"{r.amount:.2f}")
            amt_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._table.setItem(i, 9, amt_item)

            self._table.setItem(i, 10, QTableWidgetItem(r.return_reason))

            del_btn = QPushButton("Del")
            del_btn.setStyleSheet(_BTN_DANGER)
            del_btn.setFixedWidth(40)
            del_btn.clicked.connect(lambda _, idx=i: self._delete_item(idx))
            self._table.setCellWidget(i, 11, del_btn)

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

        self._add_total_field(layout, "Total Amount", "total_amount_label")
        self._add_total_field(layout, "Ledger Amount", "ledger_amount_label")

        self.total_amount_label = self._totals_widget.findChild(QLabel, "total_amount_label")
        self.ledger_amount_label = self._totals_widget.findChild(QLabel, "ledger_amount_label")

    def _add_total_field(self, layout: QHBoxLayout, title: str, attr_name: str):
        container = QVBoxLayout()
        container.setSpacing(1)
        lbl = QLabel(title)
        lbl.setStyleSheet(_HEADER_LABEL)
        lbl.setAlignment(Qt.AlignCenter)
        container.addWidget(lbl)

        val_lbl = QLabel("0.00")
        val_lbl.setObjectName(attr_name)
        val_lbl.setAlignment(Qt.AlignCenter)
        val_lbl.setStyleSheet(
            f"color: {_TEXT}; font-size: 13px; font-weight: bold;"
            f"background: transparent; font-family: 'Segoe UI'; padding: 2px;"
        )
        container.addWidget(val_lbl)
        setattr(self, attr_name, val_lbl)

        layout.addLayout(container)

    def _recalc_totals(self):
        total = round(sum(r.amount for r in self._item_rows), 2)
        self.total_amount_label.setText(f"{total:.2f}")
        self.ledger_amount_label.setText(f"{total:.2f}")

    # ------------------------------------------------------------------
    # Populate for edit
    # ------------------------------------------------------------------

    def _populate_cn(self, cn: dict):
        self.voucher_no_edit.setText(cn.get("voucher_no", ""))

        from PySide6.QtCore import QDate
        vd = cn.get("voucher_date", "")
        if vd:
            try:
                parts = vd.split("-")
                self.voucher_date.setDate(QDate(int(parts[0]), int(parts[1]), int(parts[2])))
            except Exception:
                pass

        cd = cn.get("cn_date", "")
        if cd:
            try:
                parts = cd.split("-")
                self.cn_date.setDate(QDate(int(parts[0]), int(parts[1]), int(parts[2])))
            except Exception:
                pass

        idx = self.cn_type_combo.findText(cn.get("cn_type", "Customer"))
        if idx >= 0:
            self.cn_type_combo.setCurrentIndex(idx)

        cid = cn.get("customer_id")
        if cid:
            idx = self.customer_combo.findData(cid)
            if idx >= 0:
                self.customer_combo.setCurrentIndex(idx)

        self.remarks_edit.setText(cn.get("remarks", ""))

        items = CreditNoteDAO.get_invoice_items(cn["id"])
        for it in items:
            row = _ReturnItemRow(
                item_id=it["item_id"],
                item_name=it.get("item_name", ""),
                stock_batch_id=it["stock_batch_id"],
                batch_no=it.get("batch_no", ""),
                expiry=it.get("expiry", ""),
                pack_size=it.get("pack_size", ""),
                mrp=it.get("mrp", 0.0),
                purchase_rate=it.get("rate", 0.0),
                return_qty=it.get("return_qty", 0.0),
                less_amount=it.get("less_amount", 0.0),
                amount=it.get("amount", 0.0),
                return_reason=it.get("return_reason", ""),
                price_factor=it.get("price_factor", 1.0),
            )
            self._item_rows.append(row)
        self._refresh_table()
        self._recalc_totals()

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
        cid = self.customer_combo.currentData()
        if not cid:
            QMessageBox.warning(self, "Validation", "Customer is required.")
            return

        if not self._item_rows:
            QMessageBox.warning(self, "Validation", "At least one item is required.")
            return

        self._recalc_totals()

        voucher_date = self.voucher_date.date().toString("yyyy-MM-dd")
        cn_date = self.cn_date.date().toString("yyyy-MM-dd")
        cn_type = self.cn_type_combo.currentText()
        remarks = self.remarks_edit.text().strip()
        total_amount = round(sum(r.amount for r in self._item_rows), 2)
        ledger_amount = total_amount

        header = {
            "voucher_date": voucher_date,
            "cn_date": cn_date,
            "cn_type": cn_type,
            "customer_id": cid,
            "total_amount": total_amount,
            "ledger_amount": ledger_amount,
            "remarks": remarks,
        }
        items_data = [r.to_dict() for r in self._item_rows]

        try:
            if self._cn:
                CreditNoteDAO.update_credit_note(self._cn["id"], header, items_data)
            else:
                CreditNoteDAO.insert_credit_note(header, items_data)
            self._saved = True
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save credit note:\n{e}")

    @property
    def was_saved(self) -> bool:
        return self._saved


# ======================================================================
# Credit Note PAGE
# ======================================================================

class CreditNotePage(QWidget):
    """Credit Note screen with history list and entry dialog."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setStyleSheet(f"background-color: {_DARK_BG};")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._stack = QStackedWidget()
        root.addWidget(self._stack)

        self._history_page = self._build_history_page()
        self._stack.addWidget(self._history_page)

        self._placeholder = QWidget()
        ph_layout = QVBoxLayout(self._placeholder)
        ph_layout.setAlignment(Qt.AlignCenter)
        lbl = QLabel("Credit note entry opens via dialog.")
        lbl.setStyleSheet(f"color: {_TEXT}; font-size: 16px; font-family: 'Segoe UI';")
        lbl.setAlignment(Qt.AlignCenter)
        ph_layout.addWidget(lbl)
        self._stack.addWidget(self._placeholder)

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

        title = QLabel("Credit Note - History")
        title.setStyleSheet(
            f"color: {_TEXT}; font-size: 18px; font-weight: bold;"
            f"background: transparent; font-family: 'Segoe UI';"
        )
        hl.addWidget(title)
        hl.addStretch()

        new_btn = QPushButton("New Credit Note")
        new_btn.setFixedWidth(140)
        new_btn.setStyleSheet(_BTN_SAVE)
        new_btn.clicked.connect(self._on_new)
        hl.addWidget(new_btn)

        edit_btn = QPushButton("Edit")
        edit_btn.setFixedWidth(90)
        edit_btn.setStyleSheet(_BTN_SECONDARY)
        edit_btn.clicked.connect(self._on_edit)
        hl.addWidget(edit_btn)

        print_btn = QPushButton("Print / PDF")
        print_btn.setFixedWidth(110)
        print_btn.setStyleSheet(_BTN_SECONDARY)
        print_btn.clicked.connect(self._on_print)
        hl.addWidget(print_btn)

        del_btn = QPushButton("Delete")
        del_btn.setFixedWidth(90)
        del_btn.setStyleSheet(_BTN_DANGER)
        del_btn.clicked.connect(self._on_delete)
        hl.addWidget(del_btn)

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

        fl.addWidget(self._flbl("Voucher No"))
        self._filter_voucher = _make_edit("CN-XXXX")
        self._filter_voucher.setMaximumWidth(120)
        fl.addWidget(self._filter_voucher)

        fl.addWidget(self._flbl("Customer"))
        self._filter_customer = _make_combo()
        self._filter_customer.setMinimumWidth(160)
        self._filter_customer.addItem("All Customers", None)
        for c in CustomerDAO.get_all():
            self._filter_customer.addItem(c["customer_name"], c["id"])
        fl.addWidget(self._filter_customer)

        filter_btn = QPushButton("Filter")
        filter_btn.setFixedWidth(70)
        filter_btn.setStyleSheet(_BTN_GREEN_SM)
        filter_btn.clicked.connect(self._refresh_history)
        fl.addWidget(filter_btn)

        fl.addStretch()
        layout.addWidget(filter_bar)

        # History table
        self._hist_table = QTableWidget()
        self._hist_table.setColumnCount(9)
        self._hist_table.setHorizontalHeaderLabels([
            "Voucher No", "Date", "CN Date", "CN Type", "Customer",
            "Total Amount", "Ledger Amount", "Remarks", "Items"
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
        for col in range(9):
            if col == 4:
                hv.setSectionResizeMode(col, QHeaderView.Stretch)
            else:
                hv.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        hv.setStyleSheet(
            f"QHeaderView::section {{"
            f"  background-color: {_SURFACE}; color: {_TEXT};"
            f"  border: none; border-bottom: 2px solid {_ACCENT};"
            f"  padding: 3px 6px; font-weight: bold; font-size: 9pt;"
            f"  font-family: 'Segoe UI';"
            f"}}"
        )
        self._hist_table.setStyleSheet(
            f"QTableWidget {{"
            f"  background-color: {_DARK_BG}; color: {_TEXT};"
            f"  border: 1px solid {_BORDER}; gridline-color: {_BORDER};"
            f"  font-size: 11px; font-family: 'Segoe UI';"
            f"  selection-background-color: {_ACCENT};"
            f"  selection-color: white;"
            f"}}"
            f"QTableWidget::item {{ padding: 2px 5px; }}"
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
        voucher_no = self._filter_voucher.text().strip()
        cust_id = self._filter_customer.currentData()

        cns = CreditNoteDAO.get_all_filtered(
            voucher_from=from_date, voucher_to=to_date,
            party="", voucher_no=voucher_no,
        )
        if cust_id:
            cns = [c for c in cns if c.get("customer_id") == cust_id]

        self._hist_table.setRowCount(len(cns))
        for i, cn in enumerate(cns):
            self._hist_table.setItem(i, 0, QTableWidgetItem(cn.get("voucher_no", "")))
            self._hist_table.setItem(i, 1, QTableWidgetItem(cn.get("voucher_date", "")))
            self._hist_table.setItem(i, 2, QTableWidgetItem(cn.get("cn_date", "")))
            self._hist_table.setItem(i, 3, QTableWidgetItem(cn.get("cn_type", "")))
            self._hist_table.setItem(i, 4, QTableWidgetItem(cn.get("customer_name", "")))

            amt_item = QTableWidgetItem(f"{cn.get('total_amount', 0.0):.2f}")
            amt_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._hist_table.setItem(i, 5, amt_item)

            led_item = QTableWidgetItem(f"{cn.get('ledger_amount', 0.0):.2f}")
            led_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._hist_table.setItem(i, 6, led_item)

            self._hist_table.setItem(i, 7, QTableWidgetItem(cn.get("remarks", "")))

            # Item count
            items = CreditNoteDAO.get_invoice_items(cn["id"])
            self._hist_table.setItem(i, 8, QTableWidgetItem(str(len(items))))

            self._hist_table.item(i, 0).setData(Qt.UserRole, cn["id"])

    def _selected_id(self) -> int | None:
        rows = self._hist_table.selectionModel().selectedRows()
        if not rows:
            return None
        row = rows[0].row()
        return self._hist_table.item(row, 0).data(Qt.UserRole)

    def _on_new(self):
        self._open_dialog()

    def _on_edit(self):
        try:
            auth.session.require(auth.PERM_EDIT_TRANSACTIONS)
        except auth.PermissionDenied as exc:
            QMessageBox.warning(self, "Permission denied", str(exc)); return
        cn_id = self._selected_id()
        if not cn_id:
            QMessageBox.information(self, "Edit Credit Note", "Please select a credit note to edit.")
            return
        cn = CreditNoteDAO.get_by_id(cn_id)
        if not cn:
            QMessageBox.warning(self, "Edit Credit Note", "Could not load credit note data.")
            return
        self._open_dialog(cn=cn)

    def _on_print(self):
        note_id = self._selected_id()
        if not note_id:
            QMessageBox.information(self, "Print Credit Note", "Please select a credit note to print.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save Credit Note PDF", "credit_note.pdf", "PDF (*.pdf)")
        if not path:
            return
        try:
            output = generate_credit_note(note_id, path)
            QMessageBox.information(self, "PDF Saved", f"Credit note saved to:\n{output}")
        except DocumentPrintError as exc:
            QMessageBox.warning(self, "Print Credit Note", str(exc))

    def _on_delete(self):
        try:
            auth.session.require(auth.PERM_DELETE_TRANSACTIONS)
        except auth.PermissionDenied as exc:
            QMessageBox.warning(self, "Permission denied", str(exc)); return
        cn_id = self._selected_id()
        if not cn_id:
            QMessageBox.information(self, "Delete Credit Note", "Please select a credit note to delete.")
            return
        reply = QMessageBox.question(
            self, "Confirm Delete",
            "Are you sure you want to delete this credit note? Stock will be restored.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            try:
                CreditNoteDAO.delete_credit_note(cn_id)
                self._refresh_history()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to delete credit note:\n{e}")

    def _open_dialog(self, cn: dict | None = None):
        dlg = _CreditNoteEntryDialog(self, cn=cn)
        dlg.exec()
        if dlg.was_saved:
            self._refresh_history()
