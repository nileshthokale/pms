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
from database.document_printing import DocumentPrintError, generate_supplier_payment
from database.ledger_dao import LedgerDAO
from database.supplier_dao import SupplierDAO
from database.supplier_payment_dao import SupplierPaymentDAO
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
# Supplier Payment Entry Dialog
# ======================================================================

class _SupplierPaymentEntryDialog(QDialog):
    """Modal dialog for creating / editing a supplier payment voucher with FIFO invoice allocations."""

    def __init__(self, parent: QWidget | None = None, *, payment: dict | None = None):
        super().__init__(parent)
        self._payment = payment
        self._payment_id = payment["id"] if payment else None
        self._saved = False
        self._invoices_data: List[dict] = []
        self._updating_allocations = False

        self.setWindowTitle("Supplier Payment Voucher")
        self.setMinimumWidth(920)
        self.setMinimumHeight(560)
        self.setModal(True)

        self._build_ui()
        self._set_voucher_no()
        self._set_current_datetime()

        if payment:
            self._populate_payment(payment)
        else:
            self._on_supplier_changed(-1)

    def _build_ui(self):
        p = palette()
        self.setStyleSheet(f"QDialog {{ background-color: {p['bg']}; color: {p['text']}; }}")

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        # 1. Header Group
        grp = QGroupBox("Voucher Details")
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

        grid.addWidget(self._lbl("Voucher Date:"), 0, 2)
        self.payment_date = make_date_edit(self, p)
        self.payment_date.setMaximumWidth(150)
        grid.addWidget(self.payment_date, 0, 3)

        # Row 1: Time & Payment From
        grid.addWidget(self._lbl("Voucher Time:"), 1, 0)
        self.payment_time_edit = QLineEdit()
        self.payment_time_edit.setStyleSheet(_edit_style(p))
        self.payment_time_edit.setMaximumWidth(100)
        grid.addWidget(self.payment_time_edit, 1, 1)

        grid.addWidget(self._lbl("Payment From:"), 1, 2)
        self.payment_mode_combo = QComboBox()
        self.payment_mode_combo.setStyleSheet(combo_style(p))
        self.payment_mode_combo.addItems(["Cash", "Bank", "Cheque", "UPI"])
        self.payment_mode_combo.setMaximumWidth(150)
        grid.addWidget(self.payment_mode_combo, 1, 3)

        # Row 2: Searchable Supplier & Ledger Balance
        grid.addWidget(self._lbl("Supplier *:"), 2, 0)
        self.supplier_selector = SearchableSelector(placeholder="-- Select Supplier --", parent=self)
        self.supplier_selector.setMinimumWidth(280)
        self.supplier_selector.selection_changed.connect(self._on_supplier_changed)
        grid.addWidget(self.supplier_selector, 2, 1)

        grid.addWidget(self._lbl("Ledger Balance:"), 2, 2)
        self.balance_label = QLabel("0.00")
        self.balance_label.setStyleSheet(
            f"color: {p['accent']}; font-size: 15px; font-weight: bold;"
            f"background: transparent; font-family: 'Segoe UI';"
        )
        grid.addWidget(self.balance_label, 2, 3)

        # Row 3: Payment Amount & Reference No
        grid.addWidget(self._lbl("Payment Amount *:"), 3, 0)
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

        # 2. Outstanding Invoices Table Group
        inv_grp = QGroupBox("Outstanding Purchase Invoices")
        inv_grp.setStyleSheet(
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
        inv_layout = QVBoxLayout(inv_grp)
        inv_layout.setContentsMargins(10, 16, 10, 10)
        inv_layout.setSpacing(6)

        self._inv_table = QTableWidget()
        self._inv_table.setColumnCount(9)
        self._inv_table.setHorizontalHeaderLabels([
            "Voucher Type", "Bill/Inv No", "Bill Date", "Voucher No",
            "Voucher Date", "Invoice Amt (₹)", "Outstanding (₹)",
            "Paid / Alloc (₹)", "Remaining (₹)",
        ])
        self._inv_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._inv_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._inv_table.verticalHeader().setVisible(False)
        self._inv_table.setShowGrid(True)
        self._inv_table.setStyleSheet(table_style(p))
        self._inv_table.horizontalHeader().setStyleSheet(table_header_style(p))
        self._inv_table.cellChanged.connect(self._on_table_cell_changed)

        hv = self._inv_table.horizontalHeader()
        hv.setStretchLastSection(False)
        hv.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hv.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hv.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hv.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        hv.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        hv.setSectionResizeMode(5, QHeaderView.Stretch)
        hv.setSectionResizeMode(6, QHeaderView.Stretch)
        hv.setSectionResizeMode(7, QHeaderView.Stretch)
        hv.setSectionResizeMode(8, QHeaderView.Stretch)

        inv_layout.addWidget(self._inv_table, 1)

        # 3. Bottom Totals Summary Card
        self._totals_card = QWidget()
        self._totals_card.setObjectName("totalsCard")
        self._totals_card.setStyleSheet(_card_style(p))
        tot_layout = QHBoxLayout(self._totals_card)
        tot_layout.setContentsMargins(10, 4, 10, 4)
        tot_layout.setSpacing(20)

        self._tot_inv_lbl = QLabel("Total Invoices: ₹0.00")
        self._tot_inv_lbl.setStyleSheet(f"font-weight: bold; color: {p['text']}; font-size: 13px;")
        tot_layout.addWidget(self._tot_inv_lbl)

        self._tot_out_lbl = QLabel("Total Outstanding: ₹0.00")
        self._tot_out_lbl.setStyleSheet(f"font-weight: bold; color: {p.get('danger', '#c0392b')}; font-size: 13px;")
        tot_layout.addWidget(self._tot_out_lbl)

        self._tot_paid_lbl = QLabel("Total Allocated: ₹0.00")
        self._tot_paid_lbl.setStyleSheet(f"font-weight: bold; color: {p['accent']}; font-size: 13px;")
        tot_layout.addWidget(self._tot_paid_lbl)

        self._tot_rem_lbl = QLabel("Total Remaining: ₹0.00")
        self._tot_rem_lbl.setStyleSheet(f"font-weight: bold; color: {p['text']}; font-size: 13px;")
        tot_layout.addWidget(self._tot_rem_lbl)

        tot_layout.addStretch()
        inv_layout.addWidget(self._totals_card)

        root.addWidget(inv_grp, 1)

        # 4. Button Bar
        btn_bar = QHBoxLayout()
        btn_bar.setSpacing(10)
        btn_bar.addStretch()

        self._save_btn = QPushButton("Save Payment")
        self._save_btn.setStyleSheet(btn_primary_style(p))
        self._save_btn.clicked.connect(self._on_save)
        btn_bar.addWidget(self._save_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(btn_secondary_style(p))
        cancel_btn.clicked.connect(self.reject)
        btn_bar.addWidget(cancel_btn)

        root.addLayout(btn_bar)

        self._load_suppliers()

    def _lbl(self, text: str) -> QLabel:
        p = palette()
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {p['text']}; font-size: 14px; font-weight: bold; background: transparent;")
        return lbl

    def _load_suppliers(self):
        suppliers = SupplierDAO.get_all()
        self.supplier_selector.set_options(
            suppliers, id_key="id", name_key="supplier_name", subtitle_key="city"
        )

    def _set_voucher_no(self):
        if not self._payment:
            conn = None
            try:
                conn = get_connection()
                full = SupplierPaymentDAO.generate_next_voucher_no(conn)
                self._full_voucher_no = full
                self.voucher_no_edit.setText(format_document_number(full))
                self.voucher_no_edit.setToolTip(f"Full Voucher: {full}")
            finally:
                if conn:
                    conn.close()

    def _set_current_datetime(self):
        now = datetime.now()
        qdate = QDate(now.year, now.month, now.day)
        self.payment_date.setDate(qdate)
        self.payment_time_edit.setText(now.strftime("%H:%M"))

    def _on_supplier_changed(self, idx: int):
        sid = self.supplier_selector.selected_id
        p = palette()
        if not sid:
            self.balance_label.setText("0.00")
            self.balance_label.setStyleSheet(f"color: {p['text_dim']}; font-weight: bold;")
            self._load_invoices([])
            return

        # 1. Fetch supplier ledger balance
        try:
            sup = SupplierDAO.get_by_id(sid)
            ledger_id = sup.get("ledger_id") if sup else None
            if not ledger_id:
                ledger_id = SupplierDAO.get_ledger_id(sid)

            if not ledger_id:
                self.balance_label.setText("N/A (No ledger mapped)")
                self.balance_label.setToolTip("No linked account ledger found for this supplier")
                self.balance_label.setStyleSheet(f"color: {p.get('danger', '#c0392b')}; font-weight: bold;")
            else:
                bal = LedgerDAO.get_balance(ledger_id)
                closing = float(bal.get("closing_balance", 0.0) or 0.0)
                closing_type = bal.get("closing_balance_type", "Credit")
                if abs(closing) < 1e-9:
                    self.balance_label.setText("₹0.00")
                    self.balance_label.setStyleSheet(f"color: {p['accent']}; font-weight: bold;")
                else:
                    color = p['accent'] if closing_type == "Debit" else p.get('danger', '#c0392b')
                    self.balance_label.setText(f"₹{closing:,.2f} {closing_type}")
                    self.balance_label.setStyleSheet(f"color: {color}; font-weight: bold;")
                self.balance_label.setToolTip(f"Ledger ID: {ledger_id}")
        except Exception as exc:
            self.balance_label.setText("Error")
            self.balance_label.setToolTip(f"Failed to fetch ledger balance: {exc}")
            self.balance_label.setStyleSheet(f"color: {p.get('danger', '#c0392b')}; font-weight: bold;")

        # 2. Fetch outstanding purchase invoices
        invoices = SupplierPaymentDAO.get_outstanding_invoices(sid, exclude_payment_id=self._payment_id)
        self._load_invoices(invoices)

    def _load_invoices(self, invoices: List[dict]):
        self._invoices_data = invoices
        amount = _safe_float(self.amount_edit.text(), 0.0)

        # Allocate FIFO
        allocations = SupplierPaymentDAO.calculate_fifo_allocation(invoices, amount)
        alloc_map = {a["purchase_invoice_id"]: a["allocated_amount"] for a in allocations}

        # If editing and we have saved allocations, honor them if amount matches
        if self._payment:
            for inv in invoices:
                if inv.get("current_allocated", 0.0) > 0 and inv["id"] not in alloc_map:
                    alloc_map[inv["id"]] = inv["current_allocated"]

        self._render_table(alloc_map)

    def _render_table(self, alloc_map: dict[int, float]):
        self._updating_allocations = True
        try:
            self._inv_table.setRowCount(len(self._invoices_data))
            tot_inv = 0.0
            tot_out = 0.0
            tot_paid = 0.0
            tot_rem = 0.0

            for i, inv in enumerate(self._invoices_data):
                iid = inv["id"]
                inv_amt = float(inv["invoice_amount"])
                out_bal = float(inv["outstanding_balance"])
                alloc_amt = alloc_map.get(iid, 0.0)
                rem_bal = max(0.0, round(out_bal - alloc_amt, 2))

                tot_inv += inv_amt
                tot_out += out_bal
                tot_paid += alloc_amt
                tot_rem += rem_bal

                vtype_item = QTableWidgetItem(inv.get("purchase_type", "Credit"))
                vtype_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                self._inv_table.setItem(i, 0, vtype_item)

                ino_item = QTableWidgetItem(inv.get("invoice_no", "") or "--")
                ino_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                self._inv_table.setItem(i, 1, ino_item)

                idate_item = QTableWidgetItem(inv.get("invoice_date", "") or "--")
                idate_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                self._inv_table.setItem(i, 2, idate_item)

                vno_item = QTableWidgetItem(format_document_number(inv.get("voucher_no", "")))
                vno_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                self._inv_table.setItem(i, 3, vno_item)

                vdate_item = QTableWidgetItem(inv.get("voucher_date", ""))
                vdate_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                self._inv_table.setItem(i, 4, vdate_item)

                amt_item = QTableWidgetItem(f"{inv_amt:,.2f}")
                amt_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                amt_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                self._inv_table.setItem(i, 5, amt_item)

                out_item = QTableWidgetItem(f"{out_bal:,.2f}")
                out_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                out_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                self._inv_table.setItem(i, 6, out_item)

                # Col 7: Paid / Allocated amount (editable)
                paid_item = QTableWidgetItem(f"{alloc_amt:.2f}")
                paid_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                paid_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable)
                paid_item.setData(Qt.UserRole, iid)
                self._inv_table.setItem(i, 7, paid_item)

                rem_item = QTableWidgetItem(f"{rem_bal:,.2f}")
                rem_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                rem_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                self._inv_table.setItem(i, 8, rem_item)

            self._tot_inv_lbl.setText(f"Total Invoices: ₹{tot_inv:,.2f}")
            self._tot_out_lbl.setText(f"Total Outstanding: ₹{tot_out:,.2f}")
            self._tot_paid_lbl.setText(f"Total Allocated: ₹{tot_paid:,.2f}")
            self._tot_rem_lbl.setText(f"Total Remaining: ₹{tot_rem:,.2f}")
        finally:
            self._updating_allocations = False

    def _on_amount_edited(self, text: str):
        if self._updating_allocations:
            return
        amount = _safe_float(text, 0.0)
        allocations = SupplierPaymentDAO.calculate_fifo_allocation(self._invoices_data, amount)
        alloc_map = {a["purchase_invoice_id"]: a["allocated_amount"] for a in allocations}
        self._render_table(alloc_map)

    def _on_table_cell_changed(self, row: int, col: int):
        if self._updating_allocations or col != 7:
            return
        item = self._inv_table.item(row, col)
        if not item or row >= len(self._invoices_data):
            return

        val = _safe_float(item.text(), 0.0)
        out_bal = float(self._invoices_data[row]["outstanding_balance"])

        if val < 0.0:
            val = 0.0
        elif val > out_bal:
            val = out_bal

        self._updating_allocations = True
        try:
            item.setText(f"{val:.2f}")
            rem = max(0.0, round(out_bal - val, 2))
            rem_item = self._inv_table.item(row, 8)
            if rem_item:
                rem_item.setText(f"{rem:,.2f}")

            # Recompute total amount
            total_allocated = 0.0
            for r in range(self._inv_table.rowCount()):
                p_item = self._inv_table.item(r, 7)
                if p_item:
                    total_allocated += _safe_float(p_item.text(), 0.0)
            self.amount_edit.setText(f"{total_allocated:.2f}")

            # Update summary
            tot_inv = sum(float(x["invoice_amount"]) for x in self._invoices_data)
            tot_out = sum(float(x["outstanding_balance"]) for x in self._invoices_data)
            self._tot_inv_lbl.setText(f"Total Invoices: ₹{tot_inv:,.2f}")
            self._tot_out_lbl.setText(f"Total Outstanding: ₹{tot_out:,.2f}")
            self._tot_paid_lbl.setText(f"Total Allocated: ₹{total_allocated:,.2f}")
            self._tot_rem_lbl.setText(f"Total Remaining: ₹{max(0.0, tot_out - total_allocated):,.2f}")
        finally:
            self._updating_allocations = False

    def _populate_payment(self, pay: dict):
        full = pay.get("voucher_no", "")
        self._full_voucher_no = full
        self.voucher_no_edit.setText(format_document_number(full))
        self.voucher_no_edit.setToolTip(f"Full Voucher: {full}" if full else "")

        pd = pay.get("payment_date", "")
        if pd:
            try:
                parts = pd.split("-")
                self.payment_date.setDate(QDate(int(parts[0]), int(parts[1]), int(parts[2])))
            except Exception:
                pass

        self.payment_time_edit.setText(pay.get("payment_time", ""))

        idx = self.payment_mode_combo.findText(pay.get("payment_mode", "Cash"))
        if idx >= 0:
            self.payment_mode_combo.setCurrentIndex(idx)

        sid = pay.get("supplier_id")
        if sid:
            self.supplier_selector.set_selected_id(sid)

        self.amount_edit.setText(f"{pay.get('amount', 0.0):.2f}")
        self.reference_no_edit.setText(pay.get("reference_no", ""))
        self.remarks_edit.setText(pay.get("remarks", ""))

        # Trigger load for this supplier and apply saved allocations
        self._on_supplier_changed(-1)

    def _on_save(self):
        # Prevent duplicate clicks
        self._save_btn.setEnabled(False)
        try:
            date_str = self.payment_date.date().toString("yyyy-MM-dd")
            try:
                financial_year.validate_transaction_date(date_str)
            except financial_year.FinancialYearError as exc:
                QMessageBox.warning(self, "Financial Year", str(exc))
                return

            sid = self.supplier_selector.selected_id
            if not sid:
                QMessageBox.warning(self, "Validation", "Supplier is required.")
                return

            sup = SupplierDAO.get_by_id(sid)
            ledger_id = sup.get("ledger_id") if sup else None
            if not ledger_id:
                ledger_id = SupplierDAO.get_ledger_id(sid)
            if not ledger_id:
                QMessageBox.warning(
                    self,
                    "Account Mapping Missing",
                    f"Cannot post voucher: Supplier '{sup.get('supplier_name', '')}' has no linked Account Ledger.\n\n"
                    "Please configure the supplier's ledger in Supplier Master before posting payments.",
                )
                return

            amount = _safe_float(self.amount_edit.text(), 0.0)
            if amount <= 0.0:
                QMessageBox.warning(self, "Validation", "Amount must be greater than 0.")
                return

            # Check if payment amount exceeds total available outstanding balance
            total_available_outstanding = sum(float(x["outstanding_balance"]) for x in self._invoices_data)
            if total_available_outstanding > 0 and amount > total_available_outstanding + 0.01:
                QMessageBox.warning(
                    self,
                    "Excess Payment Rejected",
                    f"Payment amount (₹{amount:,.2f}) exceeds total available outstanding balance "
                    f"(₹{total_available_outstanding:,.2f}).\n\nSupplier advances are not supported.",
                )
                return

            allocations: List[dict] = []
            for r in range(self._inv_table.rowCount()):
                p_item = self._inv_table.item(r, 7)
                if p_item:
                    alloc_amt = _safe_float(p_item.text(), 0.0)
                    if alloc_amt > 0.0:
                        allocations.append({
                            "purchase_invoice_id": self._invoices_data[r]["id"],
                            "allocated_amount": alloc_amt,
                            "discount_amount": 0.0,
                        })

            header = {
                "payment_date": date_str,
                "payment_time": self.payment_time_edit.text().strip(),
                "supplier_id": sid,
                "payment_mode": self.payment_mode_combo.currentText(),
                "amount": amount,
                "reference_no": self.reference_no_edit.text().strip(),
                "remarks": self.remarks_edit.text().strip(),
            }

            if self._payment:
                SupplierPaymentDAO.update_payment(self._payment["id"], header, allocations=allocations)
            else:
                SupplierPaymentDAO.insert_payment(header, allocations=allocations)

            self._saved = True
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save payment voucher:\n{e}")
        finally:
            self._save_btn.setEnabled(True)

    @property
    def was_saved(self) -> bool:
        return self._saved


# ======================================================================
# Supplier Payment PAGE
# ======================================================================

class SupplierPaymentPage(QWidget):
    """Supplier Payment screen with history list and entry dialog."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("SupplierPaymentPage")
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

        title = QLabel("Supplier Payment Voucher")
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

        fl.addWidget(self._flbl("Supplier:"))
        self._filter_supplier = SearchableSelector(placeholder="-- All Suppliers --", parent=self)
        self._filter_supplier.setMinimumWidth(220)
        self._load_filter_suppliers()
        fl.addWidget(self._filter_supplier)

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
            "Supplier", "Payment Mode", "Reference No", "Amount (₹)"
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
                # default to end of FY or today if within FY
                today = QDate(now.year, now.month, now.day)
                fy_end = QDate(int(e_parts[0]), int(e_parts[1]), int(e_parts[2]))
                self._filter_to.setDate(min(today, fy_end))
                return
            except Exception:
                pass
        now = datetime.now()
        self._filter_from.setDate(QDate(now.year, 4, 1) if now.month >= 4 else QDate(now.year - 1, 4, 1))
        self._filter_to.setDate(QDate(now.year, now.month, now.day))

    def _load_filter_suppliers(self):
        suppliers = SupplierDAO.get_all()
        self._filter_supplier.set_options(
            suppliers, id_key="id", name_key="supplier_name", subtitle_key="city"
        )

    def _on_reset_and_refresh(self):
        self._set_default_filter_dates()
        self._filter_supplier.clear_selection()
        self._refresh_history()

    def _refresh_history(self):
        from_date = self._filter_from.date().toString("yyyy-MM-dd")
        to_date = self._filter_to.date().toString("yyyy-MM-dd")
        sup_id = self._filter_supplier.selected_id

        payments = SupplierPaymentDAO.get_all_filtered(
            date_from=from_date, date_to=to_date, supplier_id=sup_id,
        )

        self._hist_table.setSortingEnabled(False)
        self._hist_table.setRowCount(len(payments))
        for i, p in enumerate(payments):
            raw_vno = p.get("voucher_no", "")
            formatted_vno = format_document_number(raw_vno)

            type_item = QTableWidgetItem("Supplier Payment")
            self._hist_table.setItem(i, 0, type_item)

            vno_item = QTableWidgetItem(formatted_vno)
            vno_item.setToolTip(f"Full Voucher: {raw_vno}")
            vno_item.setData(Qt.UserRole, p["id"])
            self._hist_table.setItem(i, 1, vno_item)

            self._hist_table.setItem(i, 2, QTableWidgetItem(p.get("payment_date", "")))
            self._hist_table.setItem(i, 3, QTableWidgetItem(p.get("payment_time", "")))
            self._hist_table.setItem(i, 4, QTableWidgetItem(p.get("supplier_name", "") or "--"))
            self._hist_table.setItem(i, 5, QTableWidgetItem(p.get("payment_mode", "")))
            self._hist_table.setItem(i, 6, QTableWidgetItem(p.get("reference_no", "") or "--"))

            amt_item = QTableWidgetItem(f"{float(p.get('amount', 0.0)):,.2f}")
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
        pay_id = self._selected_id()
        if not pay_id:
            QMessageBox.information(self, "Edit Payment", "Please select a payment voucher to edit.")
            return
        pay = SupplierPaymentDAO.get_by_id(pay_id)
        if not pay:
            QMessageBox.warning(self, "Edit Payment", "Could not load payment data.")
            return
        self._open_dialog(payment=pay)

    def _on_print(self):
        payment_id = self._selected_id()
        if not payment_id:
            QMessageBox.information(self, "Print Payment", "Please select a payment voucher to print.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save Supplier Payment PDF", "supplier_payment.pdf", "PDF (*.pdf)")
        if not path:
            return
        try:
            output = generate_supplier_payment(payment_id, path)
            QMessageBox.information(self, "PDF Saved", f"Supplier payment saved to:\n{output}")
        except DocumentPrintError as exc:
            QMessageBox.warning(self, "Print Payment", str(exc))

    def _on_delete(self):
        try:
            auth.session.require(auth.PERM_DELETE_TRANSACTIONS)
        except auth.PermissionDenied as exc:
            QMessageBox.warning(self, "Permission denied", str(exc))
            return
        pay_id = self._selected_id()
        if not pay_id:
            QMessageBox.information(self, "Delete Payment", "Please select a payment voucher to delete.")
            return

        pay = SupplierPaymentDAO.get_by_id(pay_id)
        vno = format_document_number(pay.get("voucher_no", "")) if pay else ""
        sup = pay.get("supplier_name", "") if pay else ""
        amt = pay.get("amount", 0.0) if pay else 0.0

        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            f"Are you sure you want to delete Supplier Payment Voucher {vno} ({sup}, ₹{amt:,.2f})?\n\n"
            "This will reverse its accounting posting, restore outstanding invoice balances, and remove the voucher.\n"
            "This action cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            try:
                SupplierPaymentDAO.delete_payment(pay_id)
                self._refresh_history()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to delete payment voucher:\n{e}")

    def _open_dialog(self, payment: dict | None = None):
        dlg = _SupplierPaymentEntryDialog(self, payment=payment)
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
        self._filter_supplier.refresh_theme(p)
