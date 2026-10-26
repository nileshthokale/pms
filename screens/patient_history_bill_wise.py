"""Patient History – Bill Number Wise Screen.

Allows searching previous sales bills by Bill Number and/or Patient Name,
with optional date range filtering, immediate itemized bill inspection,
and direct A6 bill reprint / PDF export.
"""

from __future__ import annotations

import os
from datetime import datetime
from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDateEdit,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from database import document_printing, financial_year
from database.sales_dao import SalesDAO
from screens.sales_history import (
    PatientSearchEdit,
    SalesBillDetailsDialog,
    _fresh_btn_style,
    _fresh_date_style,
    _fresh_edit_style,
    _fresh_header_style,
    _fresh_table_style,
)
from ui.components import FONT_FAMILY
from ui.fy_view import view_year_bounds
from ui.input_rules import attach_uppercase
from ui.theme import (
    TYPE_BUTTON,
    TYPE_FORM_LABEL,
    TYPE_HINT,
    TYPE_INPUT,
    TYPE_PAGE_TITLE,
    TYPE_SECTION_HEADER,
    TYPE_TABLE_DATA,
    TYPE_TABLE_HEADER,
    TYPE_VALUE,
    TYPE_VALUE_EMPHASIS,
    palette,
)


def _format_dmy(date_val: str) -> str:
    """Format ISO date YYYY-MM-DD to DD/MM/YYYY."""
    if not date_val:
        return ""
    clean = str(date_val).strip()
    try:
        parts = clean.split(" ")[0].split("-")
        if len(parts) == 3 and len(parts[0]) == 4:
            return f"{parts[2].zfill(2)}/{parts[1].zfill(2)}/{parts[0]}"
    except Exception:
        pass
    return clean


def _format_expiry(exp_val: str) -> str:
    """Format expiry date to DD/MM/YYYY or MM/YY."""
    if not exp_val:
        return ""
    clean = str(exp_val).strip()
    try:
        parts = clean.split("-")
        if len(parts) == 3 and len(parts[0]) == 4:
            return f"{parts[2].zfill(2)}/{parts[1].zfill(2)}/{parts[0]}"
        if len(parts) == 2:
            return f"{parts[1].zfill(2)}/{parts[0]}"
    except Exception:
        pass
    return clean


class PatientHistoryBillWisePage(QWidget):
    """Patient History – Bill Number Wise page."""

    close_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("PatientHistoryBillWisePage")
        self.window_title_text = "Patient History – Bill Number Wise"
        self._history_financial_year: dict | None = None
        self._bills: list[dict] = []
        self._selected_invoice: dict | None = None

        self._build_ui()
        self._set_default_dates()
        self.refresh_theme()
        self._perform_search()

    def _build_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(12, 10, 12, 10)
        root_layout.setSpacing(8)

        # ── 1. Page Header ───────────────────────────────────────────
        title_box = QHBoxLayout()
        self._title_lbl = QLabel("Patient History – Bill Number Wise")
        self._title_lbl.setStyleSheet(f"font-size: {TYPE_PAGE_TITLE}px; font-weight: bold;")
        title_box.addWidget(self._title_lbl)

        self._stats_lbl = QLabel("")
        self._stats_lbl.setStyleSheet(f"color: {palette()['text_dim']}; font-size: {TYPE_HINT}px;")
        title_box.addWidget(self._stats_lbl)
        title_box.addStretch()
        root_layout.addLayout(title_box)

        # ── 2. Search & Filters Bar ──────────────────────────────────
        self._filter_box = QGroupBox("Search & Filters")
        filter_layout = QVBoxLayout(self._filter_box)
        filter_layout.setContentsMargins(8, 10, 8, 8)
        filter_layout.setSpacing(6)

        row = QHBoxLayout()
        row.setSpacing(10)

        # Bill Number input
        b_box = QHBoxLayout()
        b_box.setSpacing(6)
        b_lbl = QLabel("Bill No:")
        b_lbl.setStyleSheet(f"font-size: {TYPE_FORM_LABEL}px; font-weight: bold;")
        b_box.addWidget(b_lbl)
        self._bill_no_edit = QLineEdit()
        self._bill_no_edit.setPlaceholderText("Enter bill number...")
        self._bill_no_edit.setClearButtonEnabled(True)
        self._bill_no_edit.setFixedWidth(140)
        attach_uppercase(self._bill_no_edit)
        self._bill_no_edit.returnPressed.connect(self._on_search_clicked)
        b_box.addWidget(self._bill_no_edit)
        row.addLayout(b_box)

        # Patient Name search with live autocomplete
        p_box = QHBoxLayout()
        p_box.setSpacing(6)
        p_lbl = QLabel("Patient:")
        p_lbl.setStyleSheet(f"font-size: {TYPE_FORM_LABEL}px; font-weight: bold;")
        p_box.addWidget(p_lbl)
        self._patient_edit = PatientSearchEdit("Search patient name...")
        self._patient_edit.returnPressed.connect(self._on_search_clicked)
        self._patient_edit.picked.connect(self._on_search_clicked)
        p_box.addWidget(self._patient_edit)
        row.addLayout(p_box, 1)

        # Optional Date Filter Checkbox
        self._date_check = QCheckBox("Filter by Date:")
        self._date_check.setChecked(False)
        self._date_check.toggled.connect(self._on_date_check_toggled)
        row.addWidget(self._date_check)

        # From Date
        from_box = QHBoxLayout()
        from_box.setSpacing(4)
        self._from_lbl = QLabel("From:")
        self._from_lbl.setStyleSheet(f"font-size: {TYPE_FORM_LABEL}px;")
        from_box.addWidget(self._from_lbl)
        self._from_date = QDateEdit()
        self._from_date.setCalendarPopup(True)
        self._from_date.setDisplayFormat("dd/MM/yyyy")
        self._from_date.setDate(QDate.currentDate())
        self._from_date.setFixedWidth(110)
        self._from_date.setEnabled(False)
        from_box.addWidget(self._from_date)
        row.addLayout(from_box)

        # To Date
        to_box = QHBoxLayout()
        to_box.setSpacing(4)
        self._to_lbl = QLabel("To:")
        self._to_lbl.setStyleSheet(f"font-size: {TYPE_FORM_LABEL}px;")
        to_box.addWidget(self._to_lbl)
        self._to_date = QDateEdit()
        self._to_date.setCalendarPopup(True)
        self._to_date.setDisplayFormat("dd/MM/yyyy")
        self._to_date.setDate(QDate.currentDate())
        self._to_date.setFixedWidth(110)
        self._to_date.setEnabled(False)
        to_box.addWidget(self._to_date)
        row.addLayout(to_box)

        # Search, Reset & Refresh Buttons
        self._search_btn = QPushButton("Search")
        self._search_btn.clicked.connect(self._on_search_clicked)
        row.addWidget(self._search_btn)

        self._reset_btn = QPushButton("Reset")
        self._reset_btn.clicked.connect(self._on_reset_clicked)
        row.addWidget(self._reset_btn)

        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.clicked.connect(self._on_refresh_clicked)
        row.addWidget(self._refresh_btn)

        filter_layout.addLayout(row)
        root_layout.addWidget(self._filter_box)

        # ── 3. Splitter: Bills Master Table (Top) + Items Detail Pane (Bottom)
        self._splitter = QSplitter(Qt.Vertical)
        self._splitter.setHandleWidth(4)

        # ── 3A. Bills Master Table Container ─────────────────────────
        bills_container = QWidget()
        bills_layout = QVBoxLayout(bills_container)
        bills_layout.setContentsMargins(0, 0, 0, 0)
        bills_layout.setSpacing(4)

        bills_hdr_lbl = QLabel("Sales Bills History")
        bills_hdr_lbl.setStyleSheet(f"font-size: {TYPE_SECTION_HEADER}px; font-weight: bold;")
        bills_layout.addWidget(bills_hdr_lbl)

        self._bills_table = QTableWidget()
        self._bills_table.setColumnCount(8)
        self._bills_table.setHorizontalHeaderLabels([
            "Bill Number",
            "Bill Date",
            "Patient Name",
            "Doctor Name",
            "Total Items",
            "Bill Amount",
            "Discount",
            "Net Amount",
        ])
        b_hdr = self._bills_table.horizontalHeader()
        b_hdr.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        b_hdr.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        b_hdr.setSectionResizeMode(2, QHeaderView.Stretch)
        b_hdr.setSectionResizeMode(3, QHeaderView.Stretch)
        b_hdr.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        b_hdr.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        b_hdr.setSectionResizeMode(6, QHeaderView.ResizeToContents)
        b_hdr.setSectionResizeMode(7, QHeaderView.ResizeToContents)

        self._bills_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._bills_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._bills_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._bills_table.itemSelectionChanged.connect(self._on_bill_selection_changed)
        self._bills_table.cellClicked.connect(lambda r, c: self._on_bill_selection_changed())
        self._bills_table.doubleClicked.connect(self._on_view_details)
        bills_layout.addWidget(self._bills_table, 1)

        self._splitter.addWidget(bills_container)

        # ── 3B. Bill Details Pane (Bottom) ───────────────────────────
        details_container = QWidget()
        details_layout = QVBoxLayout(details_container)
        details_layout.setContentsMargins(0, 4, 0, 0)
        details_layout.setSpacing(4)

        self._details_hdr_lbl = QLabel("Bill Details — Select a bill above to view medicines")
        self._details_hdr_lbl.setStyleSheet(f"font-size: {TYPE_SECTION_HEADER}px; font-weight: bold;")
        details_layout.addWidget(self._details_hdr_lbl)

        self._items_table = QTableWidget()
        self._items_table.setColumnCount(8)
        self._items_table.setHorizontalHeaderLabels([
            "Medicine Name",
            "Batch Number",
            "Expiry Date",
            "Pack Size",
            "Quantity",
            "MRP",
            "Discount",
            "Amount",
        ])
        i_hdr = self._items_table.horizontalHeader()
        i_hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        i_hdr.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        i_hdr.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        i_hdr.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        i_hdr.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        i_hdr.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        i_hdr.setSectionResizeMode(6, QHeaderView.ResizeToContents)
        i_hdr.setSectionResizeMode(7, QHeaderView.ResizeToContents)

        self._items_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._items_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._items_table.setSelectionMode(QAbstractItemView.SingleSelection)
        details_layout.addWidget(self._items_table, 1)

        # Selected Bill Summary Strip
        self._summary_frame = QFrame()
        self._summary_frame.setStyleSheet("QFrame { border: 1px solid #C0C0C0; border-radius: 4px; padding: 4px; }")
        summary_layout = QHBoxLayout(self._summary_frame)
        summary_layout.setContentsMargins(8, 4, 8, 4)
        summary_layout.setSpacing(20)

        self._sum_items_lbl = QLabel("Total Items: 0")
        self._sum_items_lbl.setStyleSheet(f"font-size: {TYPE_VALUE}px; font-weight: bold;")
        summary_layout.addWidget(self._sum_items_lbl)

        self._sum_total_lbl = QLabel("Bill Amount: ₹0.00")
        self._sum_total_lbl.setStyleSheet(f"font-size: {TYPE_VALUE}px; font-weight: bold;")
        summary_layout.addWidget(self._sum_total_lbl)

        self._sum_disc_lbl = QLabel("Discount: ₹0.00")
        self._sum_disc_lbl.setStyleSheet(f"font-size: {TYPE_VALUE}px; font-weight: bold;")
        summary_layout.addWidget(self._sum_disc_lbl)

        self._sum_net_lbl = QLabel("Net Amount: ₹0.00")
        self._sum_net_lbl.setStyleSheet(
            f"font-size: {TYPE_VALUE_EMPHASIS}px; font-weight: bold; color: #1B5299;"
        )
        summary_layout.addWidget(self._sum_net_lbl)
        summary_layout.addStretch()

        details_layout.addWidget(self._summary_frame)

        self._splitter.addWidget(details_container)
        self._splitter.setStretchFactor(0, 3)
        self._splitter.setStretchFactor(1, 2)
        root_layout.addWidget(self._splitter, 1)

        # ── 4. Action Footer ─────────────────────────────────────────
        footer_layout = QHBoxLayout()
        footer_layout.setSpacing(10)

        self._view_details_btn = QPushButton("View Bill Details")
        self._view_details_btn.setEnabled(False)
        self._view_details_btn.clicked.connect(self._on_view_details)
        footer_layout.addWidget(self._view_details_btn)

        self._print_btn = QPushButton("Print Bill")
        self._print_btn.setEnabled(False)
        self._print_btn.clicked.connect(self._on_print_bill)
        footer_layout.addWidget(self._print_btn)

        self._pdf_btn = QPushButton("Print / PDF")
        self._pdf_btn.setEnabled(False)
        self._pdf_btn.clicked.connect(self._on_save_pdf)
        footer_layout.addWidget(self._pdf_btn)

        footer_layout.addStretch()

        self._close_btn = QPushButton("Close")
        self._close_btn.clicked.connect(self._on_close)
        footer_layout.addWidget(self._close_btn)

        root_layout.addLayout(footer_layout)

    def _set_default_dates(self):
        """Set default dates from active financial year or current year."""
        today = QDate.currentDate()
        active = financial_year.get_active_financial_year()
        if active and active.get("start_date"):
            sd = QDate.fromString(active["start_date"], "yyyy-MM-dd")
            if sd.isValid():
                self._from_date.setDate(sd)
            else:
                self._from_date.setDate(QDate(today.year() if today.month() >= 4 else today.year() - 1, 4, 1))
        else:
            self._from_date.setDate(QDate(today.year() if today.month() >= 4 else today.year() - 1, 4, 1))
        self._to_date.setDate(today)

    def set_history_financial_year(self, year: dict | None) -> None:
        """Scope search to chosen viewing financial year."""
        self._history_financial_year = dict(year) if year else None
        if self._history_financial_year and self._history_financial_year.get("start_date"):
            sd = QDate.fromString(self._history_financial_year["start_date"], "yyyy-MM-dd")
            if sd.isValid():
                self._from_date.setDate(sd)
            ed_str = self._history_financial_year.get("end_date") or ""
            ed = QDate.fromString(ed_str, "yyyy-MM-dd") if ed_str else QDate()
            if ed.isValid():
                self._to_date.setDate(ed)
            self._date_check.setChecked(True)
            self._perform_search()

    def _on_date_check_toggled(self, checked: bool):
        self._from_date.setEnabled(checked)
        self._to_date.setEnabled(checked)

    def _on_search_clicked(self):
        self._perform_search()

    def _on_refresh_clicked(self):
        self._perform_search()

    def _on_reset_clicked(self):
        self._bill_no_edit.clear()
        self._patient_edit.clear_filter()
        self._date_check.setChecked(False)
        self._set_default_dates()
        self._perform_search()

    def _on_close(self):
        self.close_requested.emit()

    def _selected_invoice_id(self) -> int | None:
        if not self._bills_table.selectionModel():
            return None
        selected_rows = self._bills_table.selectionModel().selectedRows()
        if selected_rows:
            row = selected_rows[0].row()
        else:
            row = self._bills_table.currentRow()
        if row < 0 or row >= self._bills_table.rowCount():
            return None
        item = self._bills_table.item(row, 0)
        return item.data(Qt.UserRole) if item else None

    def _on_bill_selection_changed(self):
        inv_id = self._selected_invoice_id()
        has_sel = inv_id is not None
        self._view_details_btn.setEnabled(has_sel)
        self._print_btn.setEnabled(has_sel)
        self._pdf_btn.setEnabled(has_sel)

        if not has_sel:
            self._clear_items_pane()
            return

        # Find selected invoice dict
        inv = next((b for b in self._bills if b.get("id") == inv_id), None)
        self._selected_invoice = inv
        if not inv:
            inv = SalesDAO.get_by_id(inv_id)
            self._selected_invoice = inv

        if inv:
            disp_bno = inv.get("display_bill_no") or SalesDAO.display_bill_no(
                inv.get("bill_no", ""), patient_name=inv.get("patient_name", "")
            )
            p_name = inv.get("patient_name") or "WALKIN"
            s_date = _format_dmy(inv.get("sale_date", ""))
            self._details_hdr_lbl.setText(
                f"Bill Details — Bill No: {disp_bno}  |  Patient: {p_name}  |  Date: {s_date}"
            )
            tot_amt = float(inv.get("total_amount") or 0.0)
            disc_amt = float(inv.get("discount") or 0.0)
            net_amt = float(inv.get("net_amount") or 0.0)
            self._sum_total_lbl.setText(f"Bill Amount: ₹{tot_amt:.2f}")
            self._sum_disc_lbl.setText(f"Discount: ₹{disc_amt:.2f}")
            self._sum_net_lbl.setText(f"Net Amount: ₹{net_amt:.2f}")
        else:
            self._details_hdr_lbl.setText("Bill Details")

        # Load invoice items
        items = SalesDAO.get_invoice_items(inv_id)
        self._populate_items_table(items)

    def _clear_items_pane(self):
        self._selected_invoice = None
        self._view_details_btn.setEnabled(False)
        self._print_btn.setEnabled(False)
        self._pdf_btn.setEnabled(False)
        self._details_hdr_lbl.setText("Bill Details — Select a bill above to view medicines")
        self._items_table.setRowCount(0)
        self._sum_items_lbl.setText("Total Items: 0")
        self._sum_total_lbl.setText("Bill Amount: ₹0.00")
        self._sum_disc_lbl.setText("Discount: ₹0.00")
        self._sum_net_lbl.setText("Net Amount: ₹0.00")

    def _perform_search(self):
        bno = self._bill_no_edit.text().strip()
        pname = self._patient_edit.text().strip()

        start_date = ""
        end_date = ""
        if self._date_check.isChecked():
            start_date = self._from_date.date().toString("yyyy-MM-dd")
            end_date = self._to_date.date().toString("yyyy-MM-dd")

        rows, total = SalesDAO.search_patient_bill_history(
            bill_no=bno,
            patient_name=pname,
            start_date=start_date,
            end_date=end_date,
            limit=100,
            offset=0,
        )
        self._bills = rows
        self._populate_bills_table(rows)

        # Update stats
        if total == 0:
            self._stats_lbl.setText("No matching bills found.")
        elif total == 1:
            self._stats_lbl.setText("1 bill found")
        else:
            self._stats_lbl.setText(f"{total} bills found (showing {len(rows)})")

    def _populate_bills_table(self, rows: list[dict]):
        self._bills_table.clearSelection()
        self._bills_table.setRowCount(len(rows))
        for r_idx, r in enumerate(rows):
            inv_id = r.get("id")
            disp_bno = r.get("display_bill_no") or SalesDAO.display_bill_no(
                r.get("bill_no", ""), patient_name=r.get("patient_name", "")
            )
            sale_date = _format_dmy(r.get("sale_date", ""))
            pat_name = str(r.get("patient_name") or "WALKIN").strip()
            doc_name = str(r.get("doctor_name") or "").strip()
            tot_items = str(r.get("total_items") or 0)
            tot_amt = f"{float(r.get('total_amount') or 0.0):.2f}"
            disc_amt = f"{float(r.get('discount') or 0.0):.2f}"
            net_amt = f"{float(r.get('net_amount') or 0.0):.2f}"

            # 0: Bill Number
            item_bno = QTableWidgetItem(disp_bno)
            item_bno.setTextAlignment(Qt.AlignCenter)
            item_bno.setData(Qt.UserRole, inv_id)
            self._bills_table.setItem(r_idx, 0, item_bno)

            # 1: Bill Date
            item_date = QTableWidgetItem(sale_date)
            item_date.setTextAlignment(Qt.AlignCenter)
            self._bills_table.setItem(r_idx, 1, item_date)

            # 2: Patient Name
            item_pat = QTableWidgetItem(pat_name)
            self._bills_table.setItem(r_idx, 2, item_pat)

            # 3: Doctor Name
            item_doc = QTableWidgetItem(doc_name)
            self._bills_table.setItem(r_idx, 3, item_doc)

            # 4: Total Items
            item_ti = QTableWidgetItem(tot_items)
            item_ti.setTextAlignment(Qt.AlignCenter)
            self._bills_table.setItem(r_idx, 4, item_ti)

            # 5: Bill Amount
            item_amt = QTableWidgetItem(tot_amt)
            item_amt.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._bills_table.setItem(r_idx, 5, item_amt)

            # 6: Discount
            item_disc = QTableWidgetItem(disc_amt)
            item_disc.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._bills_table.setItem(r_idx, 6, item_disc)

            # 7: Net Amount
            item_net = QTableWidgetItem(net_amt)
            item_net.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._bills_table.setItem(r_idx, 7, item_net)

        if rows:
            self._bills_table.selectRow(0)
            self._on_bill_selection_changed()
        else:
            self._clear_items_pane()

    def _populate_items_table(self, items: list[dict]):
        self._items_table.setRowCount(len(items))
        self._sum_items_lbl.setText(f"Total Items: {len(items)}")

        for r_idx, itm in enumerate(items):
            med_name = str(itm.get("item_name") or "").strip()
            batch_no = str(itm.get("batch_no") or "").strip()
            expiry = _format_expiry(itm.get("expiry") or "")
            pack_size = str(itm.get("pack_size") or "").strip()
            qty = str(int(itm.get("sale_qty", 0))) if float(itm.get("sale_qty", 0)).is_integer() else f"{float(itm.get('sale_qty', 0)):.2f}"
            mrp = f"{float(itm.get('mrp') or 0.0):.2f}"
            disc = f"{float(itm.get('discount_amount') or 0.0):.2f}"
            amt = f"{float(itm.get('amount') or 0.0):.2f}"

            # 0: Medicine Name
            self._items_table.setItem(r_idx, 0, QTableWidgetItem(med_name))

            # 1: Batch Number
            item_batch = QTableWidgetItem(batch_no)
            item_batch.setTextAlignment(Qt.AlignCenter)
            self._items_table.setItem(r_idx, 1, item_batch)

            # 2: Expiry Date
            item_exp = QTableWidgetItem(expiry)
            item_exp.setTextAlignment(Qt.AlignCenter)
            self._items_table.setItem(r_idx, 2, item_exp)

            # 3: Pack Size
            item_pack = QTableWidgetItem(pack_size)
            item_pack.setTextAlignment(Qt.AlignCenter)
            self._items_table.setItem(r_idx, 3, item_pack)

            # 4: Quantity
            item_qty = QTableWidgetItem(qty)
            item_qty.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._items_table.setItem(r_idx, 4, item_qty)

            # 5: MRP
            item_mrp = QTableWidgetItem(mrp)
            item_mrp.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._items_table.setItem(r_idx, 5, item_mrp)

            # 6: Discount
            item_disc = QTableWidgetItem(disc)
            item_disc.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._items_table.setItem(r_idx, 6, item_disc)

            # 7: Amount
            item_amt = QTableWidgetItem(amt)
            item_amt.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._items_table.setItem(r_idx, 7, item_amt)

    def _on_view_details(self):
        inv_id = self._selected_invoice_id()
        if not inv_id:
            return
        dlg = SalesBillDetailsDialog(inv_id, self)
        dlg.exec()

    def _on_print_bill(self):
        inv_id = self._selected_invoice_id()
        if not inv_id:
            return
        try:
            document_printing.print_pharmacy_a6_bill(inv_id, self, "Counter Sale Bill")
        except document_printing.DocumentPrintError as exc:
            QMessageBox.warning(self, "Print Bill", str(exc))

    def _on_save_pdf(self):
        inv_id = self._selected_invoice_id()
        if not inv_id:
            return
        inv = self._selected_invoice or SalesDAO.get_by_id(inv_id) or {}
        disp_bno = inv.get("display_bill_no") or SalesDAO.display_bill_no(
            inv.get("bill_no", ""), patient_name=inv.get("patient_name", "")
        )
        safe_bno = (disp_bno or f"bill_{inv_id}").replace("/", "_")
        default_name = f"sale_bill_{safe_bno}.pdf"
        path, _ = QFileDialog.getSaveFileName(self, "Save Bill PDF", default_name, "PDF (*.pdf)")
        if not path:
            return
        try:
            output = document_printing.generate_counter_sale_bill(inv_id, path)
            QMessageBox.information(self, "PDF Saved", f"Bill saved to:\n{output}")
        except document_printing.DocumentPrintError as exc:
            QMessageBox.warning(self, "Save PDF", str(exc))

    def refresh_theme(self):
        p = palette()
        self.setStyleSheet(f"background-color: {p['bg']}; color: {p['text']}; font-family: {FONT_FAMILY};")
        self._bill_no_edit.setStyleSheet(_fresh_edit_style(p))
        self._patient_edit.refresh_theme()
        self._from_date.setStyleSheet(_fresh_date_style(p))
        self._to_date.setStyleSheet(_fresh_date_style(p))

        self._search_btn.setStyleSheet(_fresh_btn_style(p, primary=True))
        self._reset_btn.setStyleSheet(_fresh_btn_style(p))
        self._refresh_btn.setStyleSheet(_fresh_btn_style(p))

        self._bills_table.setStyleSheet(_fresh_table_style(p))
        self._bills_table.horizontalHeader().setStyleSheet(_fresh_header_style(p))
        self._items_table.setStyleSheet(_fresh_table_style(p))
        self._items_table.horizontalHeader().setStyleSheet(_fresh_header_style(p))

        self._view_details_btn.setStyleSheet(_fresh_btn_style(p))
        self._print_btn.setStyleSheet(_fresh_btn_style(p, primary=True))
        self._pdf_btn.setStyleSheet(_fresh_btn_style(p))
        self._close_btn.setStyleSheet(_fresh_btn_style(p))
