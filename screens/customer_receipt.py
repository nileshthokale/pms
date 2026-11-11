from __future__ import annotations

from datetime import datetime
from typing import Optional, List

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
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
)

from core.doc_formatter import format_document_number
from database import auth, financial_year
from database.connection import get_connection
from database.customer_dao import CustomerDAO
from database.customer_receipt_dao import CustomerReceiptDAO
from database.document_printing import DocumentPrintError, generate_customer_receipt
from database.ledger_dao import LedgerDAO
from screens.ledger_widgets import (
    SearchableSelector,
    btn_primary_style,
    btn_secondary_style,
    combo_style,
    date_edit_style,
    make_date_edit,
    table_header_style,
    table_style,
)
from ui.theme import date_subcontrols, palette, TYPE_FORM_LABEL, TYPE_INPUT, TYPE_PAGE_TITLE


def _safe_float(text: str, default: float = 0.0) -> float:
    try:
        clean = text.replace(",", "").strip()
        return float(clean) if clean else default
    except ValueError:
        return default


def _edit_style(p: dict) -> str:
    return (
        f"QLineEdit {{"
        f"  background-color: {p['surface']}; color: {p['text']};"
        f"  border: 1px solid {p['border']}; border-radius: 2px;"
        f"  padding: 5px; font-size: 15px; font-family: 'Segoe UI';"
        f"}}"
        f"QLineEdit:focus {{ border: 1px solid {p['accent']}; }}"
        f"QLineEdit:read-only {{ background-color: {p.get('bg_alt', p['bg'])}; color: {p['text_dim']}; }}"
    )


def _card_style(p: dict) -> str:
    return (
        f"QFrame, QWidget#totalsCard {{"
        f"  background-color: {p['surface']};"
        f"  border: 1px solid {p['border']}; border-radius: 4px;"
        f"  padding: 6px 12px;"
        f"}}"
    )


# ======================================================================
# Customer Receipt Entry Dialog
# ======================================================================

class _CustomerReceiptEntryDialog(QDialog):
    """Modal dialog for creating / editing a customer receipt voucher with FIFO bill allocations."""

    def __init__(self, parent: QWidget | None = None, *, receipt: dict | None = None):
        super().__init__(parent)
        self._receipt = receipt
        self._receipt_id = receipt["id"] if receipt else None
        self._saved = False
        self._bills_data: List[dict] = []
        self._updating_allocations = False

        self.setWindowTitle("Customer Receipt Voucher")
        self.setMinimumWidth(880)
        self.setMinimumHeight(540)
        self.setModal(True)

        self._build_ui()
        self._set_voucher_no()
        self._set_current_datetime()

        if receipt:
            self._populate_receipt(receipt)
        else:
            self._on_customer_changed(-1)

    def _build_ui(self):
        p = palette()
        self.setStyleSheet(f"QDialog {{ background-color: {p['bg']}; color: {p['text']}; }}")

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        # 1. Header Group
        grp = QGroupBox("Receipt Details")
        grp.setStyleSheet(
            f"QGroupBox {{"
            f"  background-color: {p['surface']}; color: {p['text']};"
            f"  font-weight: bold; font-size: 14px; border: 1px solid {p['border']};"
            f"  border-radius: 4px; margin-top: 10px; padding-top: 14px;"
            f"}}"
            f"QGroupBox::title {{"
            f"  subcontrol-origin: margin; left: 12px; padding: 0 6px;"
            f"  color: {p['accent']}; background-color: {p['surface']};"
            f"}}"
        )
        grid = QGridLayout(grp)
        grid.setSpacing(8)
        grid.setContentsMargins(12, 16, 12, 12)

        # Row 0: Voucher No & Date
        grid.addWidget(self._lbl("Voucher No:"), 0, 0)
        self.voucher_no_edit = QLineEdit()
        self.voucher_no_edit.setReadOnly(True)
        self.voucher_no_edit.setStyleSheet(_edit_style(p))
        grid.addWidget(self.voucher_no_edit, 0, 1)

        grid.addWidget(self._lbl("Receipt Date:"), 0, 2)
        self.receipt_date = make_date_edit(self, p)
        self.receipt_date.setMaximumWidth(150)
        grid.addWidget(self.receipt_date, 0, 3)

        # Row 1: Time & Receipt Into
        grid.addWidget(self._lbl("Receipt Time:"), 1, 0)
        self.receipt_time_edit = QLineEdit()
        self.receipt_time_edit.setStyleSheet(_edit_style(p))
        self.receipt_time_edit.setMaximumWidth(100)
        grid.addWidget(self.receipt_time_edit, 1, 1)

        grid.addWidget(self._lbl("Receipt Into:"), 1, 2)
        self.receipt_mode_combo = QComboBox()
        self.receipt_mode_combo.setStyleSheet(combo_style(p))
        self.receipt_mode_combo.addItems(["Cash", "Bank", "Cheque", "UPI"])
        self.receipt_mode_combo.setMaximumWidth(150)
        grid.addWidget(self.receipt_mode_combo, 1, 3)

        # Row 2: Searchable Customer & Ledger Balance
        grid.addWidget(self._lbl("Customer *:"), 2, 0)
        self.customer_selector = SearchableSelector(placeholder="-- Select Customer --", parent=self)
        self.customer_selector.setMinimumWidth(280)
        self.customer_selector.selection_changed.connect(self._on_customer_changed)
        grid.addWidget(self.customer_selector, 2, 1)

        grid.addWidget(self._lbl("Ledger Balance:"), 2, 2)
        self.balance_label = QLabel("0.00")
        self.balance_label.setStyleSheet(
            f"color: {p['accent']}; font-size: 15px; font-weight: bold;"
            f"background: transparent; font-family: 'Segoe UI';"
        )
        grid.addWidget(self.balance_label, 2, 3)

        # Row 3: Receipt Amount & Reference No
        grid.addWidget(self._lbl("Receipt Amount *:"), 3, 0)
        self.amount_edit = QLineEdit("0.00")
        self.amount_edit.setStyleSheet(_edit_style(p))
        self.amount_edit.setFont(QFont("Segoe UI", 12, QFont.Bold))
        self.amount_edit.textEdited.connect(self._on_amount_edited)
        grid.addWidget(self.amount_edit, 3, 1)

        grid.addWidget(self._lbl("Reference No:"), 3, 2)
        self.reference_no_edit = QLineEdit()
        self.reference_no_edit.setPlaceholderText("Cheque / UPI / Bank Ref")
        self.reference_no_edit.setStyleSheet(_edit_style(p))
        grid.addWidget(self.reference_no_edit, 3, 3)

        # Row 4: Remarks
        grid.addWidget(self._lbl("Remarks:"), 4, 0)
        self.remarks_edit = QLineEdit()
        self.remarks_edit.setStyleSheet(_edit_style(p))
        grid.addWidget(self.remarks_edit, 4, 1, 1, 3)

        root.addWidget(grp)

        # 2. Outstanding Sales Bills Table Group
        bill_grp = QGroupBox("Outstanding Sales Bills")
        bill_grp.setStyleSheet(
            f"QGroupBox {{"
            f"  background-color: {p['surface']}; color: {p['text']};"
            f"  font-weight: bold; font-size: 14px; border: 1px solid {p['border']};"
            f"  border-radius: 4px; margin-top: 10px; padding-top: 14px;"
            f"}}"
            f"QGroupBox::title {{"
            f"  subcontrol-origin: margin; left: 12px; padding: 0 6px;"
            f"  color: {p['accent']}; background-color: {p['surface']};"
            f"}}"
        )
        bill_layout = QVBoxLayout(bill_grp)
        bill_layout.setContentsMargins(10, 16, 10, 10)
        bill_layout.setSpacing(6)

        self._bill_table = QTableWidget()
        self._bill_table.setColumnCount(6)
        self._bill_table.setHorizontalHeaderLabels([
            "Bill No", "Bill Date", "Bill Amount (₹)",
            "Outstanding (₹)", "Received / Alloc (₹)", "Remaining (₹)",
        ])
        self._bill_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._bill_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._bill_table.verticalHeader().setVisible(False)
        self._bill_table.setShowGrid(True)
        self._bill_table.setStyleSheet(table_style(p))
        self._bill_table.horizontalHeader().setStyleSheet(table_header_style(p))
        self._bill_table.cellChanged.connect(self._on_table_cell_changed)

        hv = self._bill_table.horizontalHeader()
        hv.setStretchLastSection(False)
        hv.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hv.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hv.setSectionResizeMode(2, QHeaderView.Stretch)
        hv.setSectionResizeMode(3, QHeaderView.Stretch)
        hv.setSectionResizeMode(4, QHeaderView.Stretch)
        hv.setSectionResizeMode(5, QHeaderView.Stretch)

        bill_layout.addWidget(self._bill_table, 1)

        # 3. Bottom Totals Summary Card
        self._totals_card = QWidget()
        self._totals_card.setObjectName("totalsCard")
        self._totals_card.setStyleSheet(_card_style(p))
        tot_layout = QHBoxLayout(self._totals_card)
        tot_layout.setContentsMargins(10, 4, 10, 4)
        tot_layout.setSpacing(20)

        self._tot_bill_lbl = QLabel("Total Bills: ₹0.00")
        self._tot_bill_lbl.setStyleSheet(f"font-weight: bold; color: {p['text']}; font-size: 13px;")
        tot_layout.addWidget(self._tot_bill_lbl)

        self._tot_out_lbl = QLabel("Total Outstanding: ₹0.00")
        self._tot_out_lbl.setStyleSheet(f"font-weight: bold; color: {p.get('danger', '#c0392b')}; font-size: 13px;")
        tot_layout.addWidget(self._tot_out_lbl)

        self._tot_paid_lbl = QLabel("Total Received: ₹0.00")
        self._tot_paid_lbl.setStyleSheet(f"font-weight: bold; color: {p['accent']}; font-size: 13px;")
        tot_layout.addWidget(self._tot_paid_lbl)

        self._tot_rem_lbl = QLabel("Total Remaining: ₹0.00")
        self._tot_rem_lbl.setStyleSheet(f"font-weight: bold; color: {p['text']}; font-size: 13px;")
        tot_layout.addWidget(self._tot_rem_lbl)

        tot_layout.addStretch()
        bill_layout.addWidget(self._totals_card)

        root.addWidget(bill_grp, 1)

        # 4. Button Bar
        btn_bar = QHBoxLayout()
        btn_bar.setSpacing(10)
        btn_bar.addStretch()

        self._save_btn = QPushButton("Save Receipt")
        self._save_btn.setStyleSheet(btn_primary_style(p))
        self._save_btn.clicked.connect(self._on_save)
        btn_bar.addWidget(self._save_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(btn_secondary_style(p))
        cancel_btn.clicked.connect(self.reject)
        btn_bar.addWidget(cancel_btn)

        root.addLayout(btn_bar)

        self._load_customers()

    def _lbl(self, text: str) -> QLabel:
        p = palette()
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {p['text']}; font-size: 14px; font-weight: bold; background: transparent;")
        return lbl

    def _load_customers(self):
        customers = CustomerDAO.get_all()
        self.customer_selector.set_options(
            customers, id_key="id", name_key="customer_name", subtitle_key="city"
        )

    def _set_voucher_no(self):
        if not self._receipt:
            conn = None
            try:
                conn = get_connection()
                full = CustomerReceiptDAO.generate_next_voucher_no(conn)
                self._full_voucher_no = full
                self.voucher_no_edit.setText(format_document_number(full))
                self.voucher_no_edit.setToolTip(f"Full Voucher: {full}")
            finally:
                if conn:
                    conn.close()

    def _set_current_datetime(self):
        now = datetime.now()
        qdate = QDate(now.year, now.month, now.day)
        self.receipt_date.setDate(qdate)
        self.receipt_time_edit.setText(now.strftime("%H:%M"))

    def _on_customer_changed(self, idx: int):
        cid = self.customer_selector.selected_id
        p = palette()
        if not cid:
            self.balance_label.setText("0.00")
            self.balance_label.setStyleSheet(f"color: {p['text_dim']}; font-weight: bold;")
            self._load_bills([])
            return

        # 1. Fetch customer ledger balance
        try:
            cust = CustomerDAO.get_by_id(cid)
            ledger_id = cust.get("ledger_id") if cust else None
            if not ledger_id:
                ledger_id = CustomerDAO.get_ledger_id(cid)

            if not ledger_id:
                self.balance_label.setText("N/A (No ledger mapped)")
                self.balance_label.setToolTip("No linked account ledger found for this customer")
                self.balance_label.setStyleSheet(f"color: {p.get('danger', '#c0392b')}; font-weight: bold;")
            else:
                bal = LedgerDAO.get_balance(ledger_id)
                closing = float(bal.get("closing_balance", 0.0) or 0.0)
                closing_type = bal.get("closing_balance_type", "Debit")
                if abs(closing) < 1e-9:
                    self.balance_label.setText("₹0.00")
                    self.balance_label.setStyleSheet(f"color: {p['accent']}; font-weight: bold;")
                else:
                    color = p.get('danger', '#c0392b') if closing_type == "Debit" else p['accent']
                    self.balance_label.setText(f"₹{closing:,.2f} {closing_type}")
                    self.balance_label.setStyleSheet(f"color: {color}; font-weight: bold;")
                self.balance_label.setToolTip(f"Ledger ID: {ledger_id}")
        except Exception as exc:
            self.balance_label.setText("Error")
            self.balance_label.setToolTip(f"Failed to fetch ledger balance: {exc}")
            self.balance_label.setStyleSheet(f"color: {p.get('danger', '#c0392b')}; font-weight: bold;")

        # 2. Fetch outstanding sales bills
        bills = CustomerReceiptDAO.get_outstanding_bills(cid, exclude_receipt_id=self._receipt_id)
        self._load_bills(bills)

    def _load_bills(self, bills: List[dict]):
        self._bills_data = bills
        amount = _safe_float(self.amount_edit.text(), 0.0)

        # Allocate FIFO
        allocations = CustomerReceiptDAO.calculate_fifo_allocation(bills, amount)
        alloc_map = {a["sales_invoice_id"]: a["allocated_amount"] for a in allocations}

        # If editing and we have saved allocations, honor them if amount matches
        if self._receipt:
            for b in bills:
                if b.get("current_allocated", 0.0) > 0 and b["id"] not in alloc_map:
                    alloc_map[b["id"]] = b["current_allocated"]

        self._render_table(alloc_map)

    def _render_table(self, alloc_map: dict[int, float]):
        self._updating_allocations = True
        try:
            self._bill_table.setRowCount(len(self._bills_data))
            tot_bill = 0.0
            tot_out = 0.0
            tot_paid = 0.0
            tot_rem = 0.0

            for i, bill in enumerate(self._bills_data):
                bid = bill["id"]
                bill_amt = float(bill["bill_amount"])
                out_bal = float(bill["outstanding_balance"])
                alloc_amt = alloc_map.get(bid, 0.0)
                rem_bal = max(0.0, round(out_bal - alloc_amt, 2))

                tot_bill += bill_amt
                tot_out += out_bal
                tot_paid += alloc_amt
                tot_rem += rem_bal

                bno_item = QTableWidgetItem(format_document_number(bill.get("bill_no", "")))
                bno_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                self._bill_table.setItem(i, 0, bno_item)

                bdate_item = QTableWidgetItem(bill.get("sale_date", ""))
                bdate_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                self._bill_table.setItem(i, 1, bdate_item)

                amt_item = QTableWidgetItem(f"{bill_amt:,.2f}")
                amt_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                amt_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                self._bill_table.setItem(i, 2, amt_item)

                out_item = QTableWidgetItem(f"{out_bal:,.2f}")
                out_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                out_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                self._bill_table.setItem(i, 3, out_item)

                # Col 4: Received / Allocated amount (editable)
                paid_item = QTableWidgetItem(f"{alloc_amt:.2f}")
                paid_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                paid_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable)
                paid_item.setData(Qt.UserRole, bid)
                self._bill_table.setItem(i, 4, paid_item)

                rem_item = QTableWidgetItem(f"{rem_bal:,.2f}")
                rem_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                rem_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                self._bill_table.setItem(i, 5, rem_item)

            self._tot_bill_lbl.setText(f"Total Bills: ₹{tot_bill:,.2f}")
            self._tot_out_lbl.setText(f"Total Outstanding: ₹{tot_out:,.2f}")
            self._tot_paid_lbl.setText(f"Total Received: ₹{tot_paid:,.2f}")
            self._tot_rem_lbl.setText(f"Total Remaining: ₹{tot_rem:,.2f}")
        finally:
            self._updating_allocations = False

    def _on_amount_edited(self, text: str):
        if self._updating_allocations:
            return
        amount = _safe_float(text, 0.0)
        allocations = CustomerReceiptDAO.calculate_fifo_allocation(self._bills_data, amount)
        alloc_map = {a["sales_invoice_id"]: a["allocated_amount"] for a in allocations}
        self._render_table(alloc_map)

    def _on_table_cell_changed(self, row: int, col: int):
        if self._updating_allocations or col != 4:
            return
        item = self._bill_table.item(row, col)
        if not item or row >= len(self._bills_data):
            return

        val = _safe_float(item.text(), 0.0)
        out_bal = float(self._bills_data[row]["outstanding_balance"])

        if val < 0.0:
            val = 0.0
        elif val > out_bal:
            val = out_bal

        self._updating_allocations = True
        try:
            item.setText(f"{val:.2f}")
            rem = max(0.0, round(out_bal - val, 2))
            rem_item = self._bill_table.item(row, 5)
            if rem_item:
                rem_item.setText(f"{rem:,.2f}")

            # Recompute total amount
            total_allocated = 0.0
            for r in range(self._bill_table.rowCount()):
                p_item = self._bill_table.item(r, 4)
                if p_item:
                    total_allocated += _safe_float(p_item.text(), 0.0)
            self.amount_edit.setText(f"{total_allocated:.2f}")

            # Update summary
            tot_bill = sum(float(x["bill_amount"]) for x in self._bills_data)
            tot_out = sum(float(x["outstanding_balance"]) for x in self._bills_data)
            self._tot_bill_lbl.setText(f"Total Bills: ₹{tot_bill:,.2f}")
            self._tot_out_lbl.setText(f"Total Outstanding: ₹{tot_out:,.2f}")
            self._tot_paid_lbl.setText(f"Total Received: ₹{total_allocated:,.2f}")
            self._tot_rem_lbl.setText(f"Total Remaining: ₹{max(0.0, tot_out - total_allocated):,.2f}")
        finally:
            self._updating_allocations = False

    def _populate_receipt(self, rc: dict):
        full = rc.get("voucher_no", "")
        self._full_voucher_no = full
        self.voucher_no_edit.setText(format_document_number(full))
        self.voucher_no_edit.setToolTip(f"Full Voucher: {full}" if full else "")

        rd = rc.get("receipt_date", "")
        if rd:
            try:
                parts = rd.split("-")
                self.receipt_date.setDate(QDate(int(parts[0]), int(parts[1]), int(parts[2])))
            except Exception:
                pass

        self.receipt_time_edit.setText(rc.get("receipt_time", ""))

        idx = self.receipt_mode_combo.findText(rc.get("receipt_mode", "Cash"))
        if idx >= 0:
            self.receipt_mode_combo.setCurrentIndex(idx)

        cid = rc.get("customer_id")
        if cid:
            self.customer_selector.set_selected_id(cid)

        self.amount_edit.setText(f"{rc.get('amount', 0.0):.2f}")
        self.reference_no_edit.setText(rc.get("reference_no", ""))
        self.remarks_edit.setText(rc.get("remarks", ""))

        # Trigger load for this customer and apply saved allocations
        self._on_customer_changed(-1)

    def _on_save(self):
        # Prevent duplicate clicks
        self._save_btn.setEnabled(False)
        try:
            date_str = self.receipt_date.date().toString("yyyy-MM-dd")
            try:
                financial_year.validate_transaction_date(date_str)
            except financial_year.FinancialYearError as exc:
                QMessageBox.warning(self, "Financial Year", str(exc))
                return

            cid = self.customer_selector.selected_id
            if not cid:
                QMessageBox.warning(self, "Validation", "Customer is required.")
                return

            cust = CustomerDAO.get_by_id(cid)
            ledger_id = cust.get("ledger_id") if cust else None
            if not ledger_id:
                ledger_id = CustomerDAO.get_ledger_id(cid)
            if not ledger_id:
                QMessageBox.warning(
                    self,
                    "Account Mapping Missing",
                    f"Cannot post voucher: Customer '{cust.get('customer_name', '')}' has no linked Account Ledger.\n\n"
                    "Please configure the customer's ledger in Customer Master before posting receipts.",
                )
                return

            amount = _safe_float(self.amount_edit.text(), 0.0)
            if amount <= 0.0:
                QMessageBox.warning(self, "Validation", "Amount must be greater than 0.")
                return

            # Check if receipt amount exceeds total available outstanding balance
            total_available_outstanding = sum(float(x["outstanding_balance"]) for x in self._bills_data)
            if total_available_outstanding > 0 and amount > total_available_outstanding + 0.01:
                QMessageBox.warning(
                    self,
                    "Excess Receipt Rejected",
                    f"Receipt amount (₹{amount:,.2f}) exceeds total available outstanding balance "
                    f"(₹{total_available_outstanding:,.2f}).\n\nCustomer advances are not supported.",
                )
                return

            allocations: List[dict] = []
            for r in range(self._bill_table.rowCount()):
                p_item = self._bill_table.item(r, 4)
                if p_item:
                    alloc_amt = _safe_float(p_item.text(), 0.0)
                    if alloc_amt > 0.0:
                        allocations.append({
                            "sales_invoice_id": self._bills_data[r]["id"],
                            "allocated_amount": alloc_amt,
                            "discount_amount": 0.0,
                        })

            header = {
                "receipt_date": date_str,
                "receipt_time": self.receipt_time_edit.text().strip(),
                "customer_id": cid,
                "receipt_mode": self.receipt_mode_combo.currentText(),
                "amount": amount,
                "reference_no": self.reference_no_edit.text().strip(),
                "remarks": self.remarks_edit.text().strip(),
            }

            if self._receipt:
                CustomerReceiptDAO.update_receipt(self._receipt["id"], header, allocations=allocations)
            else:
                CustomerReceiptDAO.insert_receipt(header, allocations=allocations)

            self._saved = True
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save receipt voucher:\n{e}")
        finally:
            self._save_btn.setEnabled(True)

    @property
    def was_saved(self) -> bool:
        return self._saved


# ======================================================================
# Customer Receipt PAGE
# ======================================================================

class CustomerReceiptPage(QWidget):
    """Customer Receipt screen with history list and entry dialog."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("CustomerReceiptPage")
        self._history_financial_year: dict | None = None

        p = palette()
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
        p = palette()
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QWidget()
        header.setFixedHeight(56)
        header.setStyleSheet(
            f"background-color: {p['surface']}; border-bottom: 1px solid {p['border']};"
        )
        hl = QHBoxLayout(header)
        hl.setContentsMargins(16, 0, 16, 0)

        title = QLabel("Customer Receipt Voucher")
        title.setStyleSheet(
            f"color: {p['text']}; font-size: {TYPE_PAGE_TITLE}px; font-weight: bold;"
            f"background: transparent; font-family: 'Segoe UI';"
        )
        hl.addWidget(title)
        hl.addStretch()

        new_btn = QPushButton("+ New Voucher")
        new_btn.setFixedWidth(140)
        new_btn.setStyleSheet(btn_primary_style(p))
        new_btn.clicked.connect(self._on_new)
        hl.addWidget(new_btn)

        edit_btn = QPushButton("Edit")
        edit_btn.setFixedWidth(90)
        edit_btn.setStyleSheet(btn_secondary_style(p))
        edit_btn.clicked.connect(self._on_edit)
        hl.addWidget(edit_btn)

        print_btn = QPushButton("Print / PDF")
        print_btn.setFixedWidth(110)
        print_btn.setStyleSheet(btn_secondary_style(p))
        print_btn.clicked.connect(self._on_print)
        hl.addWidget(print_btn)

        del_btn = QPushButton("Delete")
        del_btn.setFixedWidth(90)
        del_btn.setStyleSheet(
            f"QPushButton {{ background-color: {p.get('danger', '#c0392b')}; color: white;"
            f"  border: none; border-radius: 2px; padding: 6px 14px;"
            f"  font-weight: bold; font-size: 14px; font-family: 'Segoe UI'; }}"
            f"QPushButton:hover {{ background-color: #d32f2f; }}"
        )
        del_btn.clicked.connect(self._on_delete)
        hl.addWidget(del_btn)

        layout.addWidget(header)

        # Filter bar
        filter_bar = QWidget()
        filter_bar.setFixedHeight(52)
        filter_bar.setStyleSheet(
            f"background-color: {p['surface']}; border-bottom: 1px solid {p['border']};"
        )
        fl = QHBoxLayout(filter_bar)
        fl.setContentsMargins(16, 0, 16, 0)
        fl.setSpacing(10)

        fl.addWidget(self._flbl("From:"))
        self._filter_from = make_date_edit(self, p)
        self._filter_from.setMaximumWidth(130)
        fl.addWidget(self._filter_from)

        fl.addWidget(self._flbl("To:"))
        self._filter_to = make_date_edit(self, p)
        self._filter_to.setMaximumWidth(130)
        fl.addWidget(self._filter_to)

        # Default dates to current financial year
        self._set_default_filter_dates()

        fl.addWidget(self._flbl("Customer:"))
        self._filter_customer = SearchableSelector(placeholder="-- All Customers --", parent=self)
        self._filter_customer.setMinimumWidth(220)
        self._load_filter_customers()
        fl.addWidget(self._filter_customer)

        filter_btn = QPushButton("Filter")
        filter_btn.setFixedWidth(80)
        filter_btn.setStyleSheet(btn_primary_style(p))
        filter_btn.clicked.connect(self._refresh_history)
        fl.addWidget(filter_btn)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.setFixedWidth(80)
        refresh_btn.setStyleSheet(btn_secondary_style(p))
        refresh_btn.clicked.connect(self._on_reset_and_refresh)
        fl.addWidget(refresh_btn)

        fl.addStretch()
        layout.addWidget(filter_bar)

        # History table
        self._hist_table = QTableWidget()
        self._hist_table.setColumnCount(8)
        self._hist_table.setHorizontalHeaderLabels([
            "Voucher Type", "Voucher No", "Date", "Time",
            "Customer", "Receipt Mode", "Reference No", "Amount (₹)"
        ])
        self._hist_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._hist_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._hist_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._hist_table.verticalHeader().setVisible(False)
        self._hist_table.setShowGrid(True)
        self._hist_table.setSortingEnabled(True)
        self._hist_table.setStyleSheet(table_style(p))
        self._hist_table.horizontalHeader().setStyleSheet(table_header_style(p))
        self._hist_table.itemDoubleClicked.connect(lambda item: self._on_edit())

        hv = self._hist_table.horizontalHeader()
        hv.setStretchLastSection(False)
        for col in range(8):
            if col == 4:
                hv.setSectionResizeMode(col, QHeaderView.Stretch)
            else:
                hv.setSectionResizeMode(col, QHeaderView.ResizeToContents)

        layout.addWidget(self._hist_table, 1)
        return page

    def _flbl(self, text: str) -> QLabel:
        p = palette()
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {p['text']}; font-weight: bold; font-size: 14px; background: transparent;")
        return lbl

    def _set_default_filter_dates(self):
        active_fy = financial_year.get_active_financial_year()
        if active_fy:
            try:
                s_parts = active_fy["start_date"].split("-")
                e_parts = active_fy["end_date"].split("-")
                self._filter_from.setDate(QDate(int(s_parts[0]), int(s_parts[1]), int(s_parts[2])))
                now = datetime.now()
                today = QDate(now.year, now.month, now.day)
                fy_end = QDate(int(e_parts[0]), int(e_parts[1]), int(e_parts[2]))
                self._filter_to.setDate(min(today, fy_end))
                return
            except Exception:
                pass
        now = datetime.now()
        self._filter_from.setDate(QDate(now.year, 4, 1) if now.month >= 4 else QDate(now.year - 1, 4, 1))
        self._filter_to.setDate(QDate(now.year, now.month, now.day))

    def _load_filter_customers(self):
        customers = CustomerDAO.get_all()
        self._filter_customer.set_options(
            customers, id_key="id", name_key="customer_name", subtitle_key="city"
        )

    def _on_reset_and_refresh(self):
        self._set_default_filter_dates()
        self._filter_customer.clear_selection()
        self._refresh_history()

    def _refresh_history(self):
        from_date = self._filter_from.date().toString("yyyy-MM-dd")
        to_date = self._filter_to.date().toString("yyyy-MM-dd")
        cust_id = self._filter_customer.selected_id

        receipts = CustomerReceiptDAO.get_all_filtered(
            date_from=from_date, date_to=to_date, customer_id=cust_id,
        )

        self._hist_table.setSortingEnabled(False)
        self._hist_table.setRowCount(len(receipts))
        for i, r in enumerate(receipts):
            raw_vno = r.get("voucher_no", "")
            formatted_vno = format_document_number(raw_vno)

            type_item = QTableWidgetItem("Customer Receipt")
            self._hist_table.setItem(i, 0, type_item)

            vno_item = QTableWidgetItem(formatted_vno)
            vno_item.setToolTip(f"Full Voucher: {raw_vno}")
            vno_item.setData(Qt.UserRole, r["id"])
            self._hist_table.setItem(i, 1, vno_item)

            self._hist_table.setItem(i, 2, QTableWidgetItem(r.get("receipt_date", "")))
            self._hist_table.setItem(i, 3, QTableWidgetItem(r.get("receipt_time", "")))
            self._hist_table.setItem(i, 4, QTableWidgetItem(r.get("customer_name", "") or "--"))
            self._hist_table.setItem(i, 5, QTableWidgetItem(r.get("receipt_mode", "")))
            self._hist_table.setItem(i, 6, QTableWidgetItem(r.get("reference_no", "") or "--"))

            amt_item = QTableWidgetItem(f"{float(r.get('amount', 0.0)):,.2f}")
            amt_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._hist_table.setItem(i, 7, amt_item)

        self._hist_table.setSortingEnabled(True)

    def _selected_id(self) -> int | None:
        rows = self._hist_table.selectionModel().selectedRows()
        if not rows:
            return None
        row = rows[0].row()
        item = self._hist_table.item(row, 1)
        return item.data(Qt.UserRole) if item else None

    def _on_new(self):
        self._open_dialog()

    def _on_edit(self):
        try:
            auth.session.require(auth.PERM_EDIT_TRANSACTIONS)
        except auth.PermissionDenied as exc:
            QMessageBox.warning(self, "Permission denied", str(exc))
            return
        rc_id = self._selected_id()
        if not rc_id:
            QMessageBox.information(self, "Edit Receipt", "Please select a receipt voucher to edit.")
            return
        rc = CustomerReceiptDAO.get_by_id(rc_id)
        if not rc:
            QMessageBox.warning(self, "Edit Receipt", "Could not load receipt data.")
            return
        self._open_dialog(receipt=rc)

    def _on_print(self):
        receipt_id = self._selected_id()
        if not receipt_id:
            QMessageBox.information(self, "Print Receipt", "Please select a receipt voucher to print.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save Customer Receipt PDF", "customer_receipt.pdf", "PDF (*.pdf)")
        if not path:
            return
        try:
            output = generate_customer_receipt(receipt_id, path)
            QMessageBox.information(self, "PDF Saved", f"Customer receipt saved to:\n{output}")
        except DocumentPrintError as exc:
            QMessageBox.warning(self, "Print Receipt", str(exc))

    def _on_delete(self):
        try:
            auth.session.require(auth.PERM_DELETE_TRANSACTIONS)
        except auth.PermissionDenied as exc:
            QMessageBox.warning(self, "Permission denied", str(exc))
            return
        rc_id = self._selected_id()
        if not rc_id:
            QMessageBox.information(self, "Delete Receipt", "Please select a receipt voucher to delete.")
            return

        rc = CustomerReceiptDAO.get_by_id(rc_id)
        vno = format_document_number(rc.get("voucher_no", "")) if rc else ""
        cust = rc.get("customer_name", "") if rc else ""
        amt = rc.get("amount", 0.0) if rc else 0.0

        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            f"Are you sure you want to delete Customer Receipt Voucher {vno} ({cust}, ₹{amt:,.2f})?\n\n"
            "This will reverse its accounting posting, restore outstanding sales bill balances, and remove the voucher.\n"
            "This action cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            try:
                CustomerReceiptDAO.delete_receipt(rc_id)
                self._refresh_history()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to delete receipt voucher:\n{e}")

    def _open_dialog(self, receipt: dict | None = None):
        dlg = _CustomerReceiptEntryDialog(self, receipt=receipt)
        dlg.exec()
        if dlg.was_saved:
            self._refresh_history()

    def refresh_theme(self):
        p = palette()
        self.setStyleSheet(f"background-color: {p['bg']};")
        self._hist_table.setStyleSheet(table_style(p))
        self._hist_table.horizontalHeader().setStyleSheet(table_header_style(p))
        self._filter_from.setStyleSheet(date_edit_style(p))
        self._filter_to.setStyleSheet(date_edit_style(p))
        self._filter_customer.refresh_theme(p)
