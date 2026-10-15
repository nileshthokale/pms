from __future__ import annotations

import os
from PySide6.QtCore import QDate, Qt
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
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from database import document_printing, financial_year
from database.sales_dao import SalesDAO
from ui.components import FONT_FAMILY
from ui.searchable_filter import SearchableFilterEdit
from ui.theme import (
    TYPE_BUTTON,
    TYPE_FORM_LABEL,
    TYPE_HINT,
    TYPE_INPUT,
    TYPE_PAGE_TITLE,
    TYPE_SECTION_HEADER,
    TYPE_TABLE_DATA,
    TYPE_VALUE,
    TYPE_VALUE_EMPHASIS,
    date_subcontrols,
    palette,
)

_PAGE_SIZE_OPTIONS = [25, 50, 100]


def _fresh_edit_style(p: dict) -> str:
    return (
        f"QLineEdit {{"
        f"  background-color: {p['surface']}; color: {p['text']};"
        f"  border: 1px solid {p['border']}; border-radius: 2px;"
        f"  padding: 4px 6px; font-size: {TYPE_INPUT}px; font-family: {FONT_FAMILY};"
        f"}}"
        f"QLineEdit:focus {{ border: 1px solid {p['accent']}; }}"
    )


def _fresh_combo_style(p: dict) -> str:
    return (
        f"QComboBox {{"
        f"  background-color: {p['surface']}; color: {p['text']};"
        f"  border: 1px solid {p['border']}; border-radius: 2px;"
        f"  padding: 4px 6px; font-size: {TYPE_INPUT}px; font-family: {FONT_FAMILY};"
        f"}}"
        f"QComboBox:hover {{ border: 1px solid {p['accent']}; }}"
        f"QComboBox::drop-down {{ border: none; width: 20px; }}"
        f"QComboBox QAbstractItemView {{"
        f"  background-color: {p['bg']}; color: {p['text']};"
        f"  border: 1px solid {p['border']}; selection-background-color: {p['selected']};"
        f"  selection-color: {p['text']}; outline: 0;"
        f"  font-size: {TYPE_INPUT}px; font-family: {FONT_FAMILY};"
        f"}}"
    )


def _fresh_date_style(p: dict) -> str:
    return (
        f"QDateEdit {{"
        f"  background-color: {p['surface']}; color: {p['text']};"
        f"  border: 1px solid {p['border']}; border-radius: 2px;"
        f"  padding: 4px 6px; font-size: {TYPE_INPUT}px; font-family: {FONT_FAMILY};"
        f"}}"
        f"QDateEdit:focus {{ border: 1px solid {p['accent']}; }}"
        # Shared calendar chevron (ui.theme.date_subcontrols) — never
        # `image: none`, which hid the icon on every date field.
        + date_subcontrols(p, width=20)
    )


def _fresh_table_style(p: dict) -> str:
    return (
        f"QTableWidget {{"
        f"  background-color: {p['bg']}; color: {p['text']};"
        f"  border: 1px solid {p['border']}; gridline-color: {p['border']};"
        f"  font-size: {TYPE_TABLE_DATA}px; font-family: {FONT_FAMILY};"
        f"  selection-background-color: {p['accent']};"
        f"  selection-color: white;"
        f"}}"
        f"QTableWidget::item {{ padding: 3px 6px; }}"
    )


def _fresh_header_style(p: dict) -> str:
    return (
        f"QHeaderView::section {{"
        f"  background-color: {p['surface']}; color: {p['text']};"
        f"  border: none; border-bottom: 2px solid {p['accent']};"
        f"  padding: 4px 6px; font-weight: bold; font-size: 12px;"
        f"  font-family: {FONT_FAMILY};"
        f"}}"
    )


def _fresh_btn_style(p: dict, *, primary: bool = False, warning: bool = False) -> str:
    if primary:
        bg = p["accent"]
        hover = p["accent_hover"]
        fg = "white"
        edge = p["accent"]
    elif warning:
        bg = p["surface_alt"]
        hover = p["selected"]
        fg = p.get("warning", "#b26a00")
        edge = p.get("warning", "#b26a00")
    else:
        bg = p["surface_alt"]
        hover = p["selected"]
        fg = p["text"]
        edge = p["text_dim"]
    return (
        f"QPushButton {{"
        f"  background-color: {bg}; color: {fg};"
        f"  border: 1px solid {edge}; border-radius: 4px;"
        f"  padding: 5px 14px; font-weight: bold;"
        f"  font-size: {TYPE_BUTTON}px; font-family: {FONT_FAMILY};"
        f"}}"
        f"QPushButton:hover {{ background-color: {hover}; border: 1px solid {p['accent']}; }}"
        f"QPushButton:disabled {{"
        f"  background-color: {p['disabled_bg']}; color: {p['disabled_text']};"
        f"  border: 1px solid {p['border']};"
        f"}}"
    )


def _fmt_bill_no(bill_no: str | None) -> str:
    """Return the bill number with the financial-year prefix stripped for display.

    Bill numbers may carry a financial-year prefix like ``2025-2026-0123``.
    Only the exact pattern ``YYYY-YYYY-\d+`` is stripped; other formats
    (e.g. hand-written ``CS-0001``, bare ``1905``, or internally generated
    sequences) are left untouched so existing numbers are never corrupted.
    """
    if not bill_no or bill_no == "--":
        return bill_no
    import re
    m = re.match(r"\d{4}-\d{4}-(\d+)$", bill_no)
    if m:
        return m.group(1)
    return bill_no


class SalesBillDetailsDialog(QDialog):
    """Modal dialog displaying original bill details, line items, and reprint options."""

    def __init__(self, invoice_id: int, parent: QWidget | None = None):
        super().__init__(parent)
        self.invoice_id = invoice_id
        self.setWindowTitle("Sales Bill Details")
        self.resize(920, 640)
        self.setModal(True)

        self._invoice = SalesDAO.get_by_id(invoice_id)
        self._items = SalesDAO.get_invoice_items(invoice_id)

        self._build_ui()
        self.refresh_theme()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        # Title strip
        title_box = QHBoxLayout()
        self._title_lbl = QLabel("Sales Bill Details")
        self._title_lbl.setStyleSheet(f"font-size: {TYPE_PAGE_TITLE}px; font-weight: bold;")
        title_box.addWidget(self._title_lbl)
        title_box.addStretch()
        layout.addLayout(title_box)

        if not self._invoice:
            err_lbl = QLabel("Invoice details could not be loaded from database.")
            layout.addWidget(err_lbl)
            return

        # Header metadata frame
        self._meta_group = QGroupBox("Bill Information")
        grid = QGridLayout(self._meta_group)
        grid.setSpacing(8)
        grid.setContentsMargins(10, 14, 10, 10)

        bill_no = self._invoice.get("bill_no") or "--"
        sale_date = self._invoice.get("sale_date") or "--"
        sale_time = self._invoice.get("sale_time") or ""
        dt_str = f"{sale_date} {sale_time}".strip()
        sale_type = self._invoice.get("sale_type") or "Cash"
        cust_name = self._invoice.get("customer_name") or "--"
        pat_name = self._invoice.get("patient_name") or "--"
        doc_name = self._invoice.get("doctor_name") or "--"
        remarks = self._invoice.get("remarks") or ""

        def _meta_row(row_idx, label1, val1, label2, val2, label3=None, val3=None):
            l1 = QLabel(f"<b>{label1}:</b>")
            v1 = QLabel(str(val1))
            grid.addWidget(l1, row_idx, 0)
            grid.addWidget(v1, row_idx, 1)

            l2 = QLabel(f"<b>{label2}:</b>")
            v2 = QLabel(str(val2))
            grid.addWidget(l2, row_idx, 2)
            grid.addWidget(v2, row_idx, 3)

            if label3 is not None:
                l3 = QLabel(f"<b>{label3}:</b>")
                v3 = QLabel(str(val3))
                grid.addWidget(l3, row_idx, 4)
                grid.addWidget(v3, row_idx, 5)

        _meta_row(0, "Bill / CNo", bill_no, "Date & Time", dt_str, "Payment Type", sale_type)
        _meta_row(1, "Customer", cust_name, "Patient", pat_name, "Doctor", doc_name)
        if remarks:
            l_rem = QLabel("<b>Remarks:</b>")
            v_rem = QLabel(remarks)
            grid.addWidget(l_rem, 2, 0)
            grid.addWidget(v_rem, 2, 1, 1, 5)

        layout.addWidget(self._meta_group)

        # Line items table
        self._items_group = QGroupBox("Bill Items")
        items_layout = QVBoxLayout(self._items_group)
        items_layout.setContentsMargins(10, 14, 10, 10)

        self._table = QTableWidget()
        self._table.setColumnCount(10)
        self._table.setHorizontalHeaderLabels([
            "#", "Item Name", "Pack", "Location", "Batch No", "Expiry", "Qty", "MRP", "Disc Amt", "Amount"
        ])
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)

        self._table.setRowCount(len(self._items))
        for idx, item in enumerate(self._items):
            s_no = QTableWidgetItem(str(idx + 1))
            s_no.setTextAlignment(Qt.AlignCenter)
            self._table.setItem(idx, 0, s_no)

            name_item = QTableWidgetItem(str(item.get("item_name") or ""))
            self._table.setItem(idx, 1, name_item)

            pack_item = QTableWidgetItem(str(item.get("pack_size") or ""))
            pack_item.setTextAlignment(Qt.AlignCenter)
            self._table.setItem(idx, 2, pack_item)

            loc_item = QTableWidgetItem(str(item.get("location") or ""))
            loc_item.setTextAlignment(Qt.AlignCenter)
            self._table.setItem(idx, 3, loc_item)

            batch_item = QTableWidgetItem(str(item.get("batch_no") or ""))
            batch_item.setTextAlignment(Qt.AlignCenter)
            self._table.setItem(idx, 4, batch_item)

            exp_item = QTableWidgetItem(str(item.get("expiry") or ""))
            exp_item.setTextAlignment(Qt.AlignCenter)
            self._table.setItem(idx, 5, exp_item)

            qty_item = QTableWidgetItem(f"{float(item.get('sale_qty') or 0.0):g}")
            qty_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._table.setItem(idx, 6, qty_item)

            mrp_item = QTableWidgetItem(f"{float(item.get('mrp') or 0.0):.2f}")
            mrp_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._table.setItem(idx, 7, mrp_item)

            disc_item = QTableWidgetItem(f"{float(item.get('discount_amount') or 0.0):.2f}")
            disc_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._table.setItem(idx, 8, disc_item)

            amt_item = QTableWidgetItem(f"{float(item.get('amount') or 0.0):.2f}")
            amt_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._table.setItem(idx, 9, amt_item)

        items_layout.addWidget(self._table)
        layout.addWidget(self._items_group, 1)

        # Totals footer
        totals_box = QHBoxLayout()
        totals_box.setSpacing(16)

        tot_amt = float(self._invoice.get("total_amount") or 0.0)
        tot_disc = float(self._invoice.get("discount") or 0.0)
        round_off = float(self._invoice.get("round_off") or 0.0)
        net_amt = float(self._invoice.get("net_amount") or 0.0)
        paid_amt = float(self._invoice.get("paid_amount") or 0.0)

        def _tot_card(caption: str, val: float, emphasize: bool = False):
            vbox = QVBoxLayout()
            c_lbl = QLabel(caption)
            c_lbl.setStyleSheet(f"font-size: {TYPE_HINT}px; font-weight: bold;")
            c_lbl.setAlignment(Qt.AlignCenter)
            vbox.addWidget(c_lbl)

            sz = TYPE_VALUE_EMPHASIS if emphasize else TYPE_VALUE
            v_lbl = QLabel(f"{val:.2f}")
            v_lbl.setStyleSheet(f"font-size: {sz}px; font-weight: bold;")
            v_lbl.setAlignment(Qt.AlignCenter)
            vbox.addWidget(v_lbl)
            totals_box.addLayout(vbox)

        _tot_card("Total Amount", tot_amt)
        _tot_card("Discount", tot_disc)
        _tot_card("Round Off", round_off)
        _tot_card("Net Amount", net_amt, emphasize=True)
        _tot_card("Paid Amount", paid_amt)

        totals_box.addStretch(1)

        # Actions
        self._direct_print_btn = QPushButton("Print / Direct Print")
        self._direct_print_btn.clicked.connect(self._on_direct_print)
        totals_box.addWidget(self._direct_print_btn)

        self._save_pdf_btn = QPushButton("Save PDF")
        self._save_pdf_btn.clicked.connect(self._on_save_pdf)
        totals_box.addWidget(self._save_pdf_btn)

        self._close_btn = QPushButton("Close")
        self._close_btn.clicked.connect(self.accept)
        totals_box.addWidget(self._close_btn)

        layout.addLayout(totals_box)

    def _on_direct_print(self):
        try:
            document_printing.print_pharmacy_a6_bill(self.invoice_id, self, "Counter Sale Bill")
        except document_printing.DocumentPrintError as exc:
            QMessageBox.warning(self, "Print Bill", str(exc))

    def _on_save_pdf(self):
        bill_no = (self._invoice.get("bill_no") or f"bill_{self.invoice_id}").replace("/", "_")
        default_name = f"sale_bill_{bill_no}.pdf"
        path, _ = QFileDialog.getSaveFileName(self, "Save Bill PDF", default_name, "PDF (*.pdf)")
        if not path:
            return
        try:
            output = document_printing.generate_counter_sale_bill(self.invoice_id, path)
            QMessageBox.information(self, "PDF Saved", f"Bill saved to:\n{output}")
        except document_printing.DocumentPrintError as exc:
            QMessageBox.warning(self, "Save PDF", str(exc))

    def refresh_theme(self):
        p = palette()
        self.setStyleSheet(f"background-color: {p['bg']}; color: {p['text']}; font-family: {FONT_FAMILY};")
        self._table.setStyleSheet(_fresh_table_style(p))
        self._table.horizontalHeader().setStyleSheet(_fresh_header_style(p))
        self._direct_print_btn.setStyleSheet(_fresh_btn_style(p, primary=True))
        self._save_pdf_btn.setStyleSheet(_fresh_btn_style(p))
        self._close_btn.setStyleSheet(_fresh_btn_style(p))


class SalesHistoryPage(QWidget):
    """Dedicated Sales History screen (Sales → Sales History).

    Provides comprehensive searching, filtering across financial years,
    invoice details viewing, and safe reprinting without modifying any database
    or stock state.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("SalesHistoryPage")
        self._current_page = 1
        self._page_size = 50
        self._total_records = 0
        self._history_financial_year: dict | None = None

        self._build_ui()
        self._load_master_data()
        self.refresh_theme()
        self._perform_search()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        # ── 1. Page Title Header ─────────────────────────────────────
        title_box = QHBoxLayout()
        self._title_lbl = QLabel("Sales History")
        self._title_lbl.setStyleSheet(f"font-size: {TYPE_PAGE_TITLE}px; font-weight: bold;")
        title_box.addWidget(self._title_lbl)

        self._stats_lbl = QLabel("")
        self._stats_lbl.setStyleSheet(f"color: #7f8c8d; font-size: {TYPE_HINT}px;")
        title_box.addWidget(self._stats_lbl)
        title_box.addStretch()

        layout.addLayout(title_box)

        # ── 2. Search & Filter Bar ───────────────────────────────────
        self._filter_box = QGroupBox("Search Historical Sales")
        filter_layout = QVBoxLayout(self._filter_box)
        filter_layout.setContentsMargins(8, 12, 8, 8)
        filter_layout.setSpacing(6)

        # Single-row filter bar: Patient | Financial Year | Filter by Date |
        # From | To | Search | Reset.  All controls stay on ONE line at the
        # default window width; Patient and Financial Year absorb the spare
        # width so nothing is clipped at narrower sizes.
        row = QHBoxLayout()
        row.setSpacing(10)

        # Patient autocomplete edit (widest input — must stay readable)
        p_box = QHBoxLayout()
        p_box.setSpacing(6)
        p_lbl = QLabel("Patient:")
        p_lbl.setStyleSheet(f"font-size: {TYPE_FORM_LABEL}px; font-weight: bold;")
        p_box.addWidget(p_lbl)
        self._patient_edit = SearchableFilterEdit("Search patient name...")
        self._patient_edit.returnPressed.connect(self._on_search_clicked)
        p_box.addWidget(self._patient_edit)
        row.addLayout(p_box, 2)

        # FY Dropdown
        fy_box = QHBoxLayout()
        fy_box.setSpacing(6)
        fy_lbl = QLabel("Financial Year:")
        fy_lbl.setStyleSheet(f"font-size: {TYPE_FORM_LABEL}px; font-weight: bold;")
        fy_box.addWidget(fy_lbl)
        self._fy_combo = QComboBox()
        self._fy_combo.addItem("All Financial Years", userData=None)
        self._fy_combo.currentIndexChanged.connect(self._on_fy_changed)
        fy_box.addWidget(self._fy_combo)
        row.addLayout(fy_box, 2)

        # Date Range filter
        self._date_check = QCheckBox("Filter by Date:")
        self._date_check.setChecked(False)
        self._date_check.toggled.connect(self._on_date_check_toggled)
        row.addWidget(self._date_check)

        from_lbl = QLabel("From:")
        from_lbl.setStyleSheet(f"font-size: {TYPE_FORM_LABEL}px;")
        row.addWidget(from_lbl)
        self._from_date = QDateEdit()
        self._from_date.setCalendarPopup(True)
        self._from_date.setDate(QDate.currentDate())
        self._from_date.setEnabled(False)
        self._from_date.setFixedWidth(115)
        row.addWidget(self._from_date)

        to_lbl = QLabel("To:")
        to_lbl.setStyleSheet(f"font-size: {TYPE_FORM_LABEL}px;")
        row.addWidget(to_lbl)
        self._to_date = QDateEdit()
        self._to_date.setCalendarPopup(True)
        self._to_date.setDate(QDate.currentDate())
        self._to_date.setEnabled(False)
        self._to_date.setFixedWidth(115)
        row.addWidget(self._to_date)

        # Search & Reset buttons
        self._search_btn = QPushButton("Search")
        self._search_btn.clicked.connect(self._on_search_clicked)
        row.addWidget(self._search_btn)

        self._reset_btn = QPushButton("Reset")
        self._reset_btn.clicked.connect(self._on_reset_clicked)
        row.addWidget(self._reset_btn)

        filter_layout.addLayout(row)
        layout.addWidget(self._filter_box)

        # ── 3. Results Table ─────────────────────────────────────────
        self._table = QTableWidget()
        self._table.setColumnCount(10)
        self._table.setHorizontalHeaderLabels([
            "Bill No / CNo",
            "Sale Date & Time",
            "Customer",
            "Patient",
            "Doctor",
            "Bill Total",
            "Discount",
            "Paid Amount",
            "Net Amount",
            "Payment Type",
        ])
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(7, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(8, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(9, QHeaderView.ResizeToContents)

        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.doubleClicked.connect(self._on_view_details)
        self._table.itemSelectionChanged.connect(self._update_action_state)

        layout.addWidget(self._table, 1)

        # ── 4. Action Bar & Pagination Footer ────────────────────────
        footer_layout = QHBoxLayout()
        footer_layout.setSpacing(10)

        # Action buttons
        self._view_details_btn = QPushButton("View Details")
        self._view_details_btn.setEnabled(False)
        self._view_details_btn.clicked.connect(self._on_view_details)
        footer_layout.addWidget(self._view_details_btn)

        self._print_btn = QPushButton("Print / Direct Print")
        self._print_btn.setEnabled(False)
        self._print_btn.clicked.connect(self._on_direct_print)
        footer_layout.addWidget(self._print_btn)

        self._save_pdf_btn = QPushButton("Save PDF")
        self._save_pdf_btn.setEnabled(False)
        self._save_pdf_btn.clicked.connect(self._on_save_pdf)
        footer_layout.addWidget(self._save_pdf_btn)

        footer_layout.addStretch(1)

        # Pagination controls
        self._prev_btn = QPushButton("« Prev")
        self._prev_btn.setEnabled(False)
        self._prev_btn.clicked.connect(self._on_prev_page)
        footer_layout.addWidget(self._prev_btn)

        self._page_lbl = QLabel("Page 1 of 1")
        self._page_lbl.setStyleSheet(f"font-size: {TYPE_VALUE}px; font-weight: bold;")
        footer_layout.addWidget(self._page_lbl)

        self._next_btn = QPushButton("Next »")
        self._next_btn.setEnabled(False)
        self._next_btn.clicked.connect(self._on_next_page)
        footer_layout.addWidget(self._next_btn)

        page_sz_lbl = QLabel("Rows:")
        footer_layout.addWidget(page_sz_lbl)
        self._page_size_combo = QComboBox()
        for sz in _PAGE_SIZE_OPTIONS:
            self._page_size_combo.addItem(str(sz), userData=sz)
        self._page_size_combo.setCurrentText(str(self._page_size))
        self._page_size_combo.currentIndexChanged.connect(self._on_page_size_changed)
        footer_layout.addWidget(self._page_size_combo)

        layout.addLayout(footer_layout)

    def _load_master_data(self):
        """Populate patient and financial year candidates."""
        # Patients
        patients = SalesDAO.get_distinct_patient_names()
        pat_rows = [{"id": p, "name": p} for p in patients]
        self._patient_edit.set_options(pat_rows, id_key="id", text_key="name")

        # Financial Years
        self._fy_combo.blockSignals(True)
        try:
            self._fy_combo.clear()
            self._fy_combo.addItem("All Financial Years", userData=None)
            all_years = financial_year.get_financial_years()
            for y in all_years:
                self._fy_combo.addItem(f"FY {y['name']}", userData=y)
        finally:
            self._fy_combo.blockSignals(False)

    def set_history_financial_year(self, year: dict | None) -> None:
        """Called by the main-window navigation bar when viewing a different FY."""
        self._history_financial_year = dict(year) if year else None
        if not year:
            self._fy_combo.setCurrentIndex(0)
            return
        # Find index for year
        for idx in range(1, self._fy_combo.count()):
            y = self._fy_combo.itemData(idx)
            if y and y.get("name") == year.get("name"):
                self._fy_combo.setCurrentIndex(idx)
                break

    def _on_fy_changed(self, index: int):
        fy = self._fy_combo.itemData(index)
        if fy:
            # Set inclusive boundaries: 1 April - 31 March
            self._date_check.setChecked(True)
            self._from_date.setDate(QDate.fromString(fy["start_date"], "yyyy-MM-dd"))
            self._to_date.setDate(QDate.fromString(fy["end_date"], "yyyy-MM-dd"))
        else:
            self._date_check.setChecked(False)
        self._current_page = 1
        self._perform_search()

    def _on_date_check_toggled(self, checked: bool):
        self._from_date.setEnabled(checked)
        self._to_date.setEnabled(checked)

    def _on_search_clicked(self):
        self._current_page = 1
        self._perform_search()

    def _on_reset_clicked(self):
        self._patient_edit.clear_filter()
        self._fy_combo.setCurrentIndex(0)
        self._date_check.setChecked(False)
        self._from_date.setDate(QDate.currentDate())
        self._to_date.setDate(QDate.currentDate())
        self._current_page = 1
        self._perform_search()

    def _on_prev_page(self):
        if self._current_page > 1:
            self._current_page -= 1
            self._perform_search()

    def _on_next_page(self):
        max_page = max(1, (self._total_records + self._page_size - 1) // self._page_size)
        if self._current_page < max_page:
            self._current_page += 1
            self._perform_search()

    def _on_page_size_changed(self):
        sz = self._page_size_combo.currentData()
        if sz and sz != self._page_size:
            self._page_size = sz
            self._current_page = 1
            self._perform_search()

    def _selected_invoice_id(self) -> int | None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return None
        row = rows[0].row()
        item = self._table.item(row, 0)
        return item.data(Qt.UserRole) if item else None

    def _update_action_state(self):
        has_sel = self._selected_invoice_id() is not None
        self._view_details_btn.setEnabled(has_sel)
        self._print_btn.setEnabled(has_sel)
        self._save_pdf_btn.setEnabled(has_sel)

    def _on_view_details(self):
        inv_id = self._selected_invoice_id()
        if not inv_id:
            return
        dlg = SalesBillDetailsDialog(inv_id, self)
        dlg.exec()

    def _on_direct_print(self):
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
        inv = SalesDAO.get_by_id(inv_id) or {}
        bill_no = (inv.get("bill_no") or f"bill_{inv_id}").replace("/", "_")
        default_name = f"sale_bill_{bill_no}.pdf"
        path, _ = QFileDialog.getSaveFileName(self, "Save Bill PDF", default_name, "PDF (*.pdf)")
        if not path:
            return
        try:
            output = document_printing.generate_counter_sale_bill(inv_id, path)
            QMessageBox.information(self, "PDF Saved", f"Bill saved to:\n{output}")
        except document_printing.DocumentPrintError as exc:
            QMessageBox.warning(self, "Save PDF", str(exc))

    def _perform_search(self):
        """Execute database query with filters and populate the results table."""
        patient_name = self._patient_edit.text().strip()

        start_date = ""
        end_date = ""
        if self._date_check.isChecked():
            start_date = self._from_date.date().toString("yyyy-MM-dd")
            end_date = self._to_date.date().toString("yyyy-MM-dd")

        offset = (self._current_page - 1) * self._page_size

        try:
            rows, total = SalesDAO.search_sales_history(
                patient_name=patient_name,
                start_date=start_date,
                end_date=end_date,
                limit=self._page_size,
                offset=offset,
            )
        except Exception as exc:
            rows, total = [], 0
            QMessageBox.warning(self, "Search Error", f"Failed to search sales:\n{exc}")

        self._total_records = total
        self._populate_table(rows)

        # Update pagination info
        max_page = max(1, (self._total_records + self._page_size - 1) // self._page_size)
        self._page_lbl.setText(f"Page {self._current_page} of {max_page} ({self._total_records} bills)")
        self._prev_btn.setEnabled(self._current_page > 1)
        self._next_btn.setEnabled(self._current_page < max_page)
        self._stats_lbl.setText(f"Showing {len(rows)} of {self._total_records} records")
        self._update_action_state()

    def _populate_table(self, rows: list[dict]):
        self._table.setRowCount(len(rows))
        for r_idx, row in enumerate(rows):
            # 0: Bill No
            bno_item = QTableWidgetItem(str(row.get("bill_no") or "--"))
            bno_item.setData(Qt.UserRole, row.get("id"))
            bno_item.setTextAlignment(Qt.AlignCenter)
            self._table.setItem(r_idx, 0, bno_item)

            # 1: Date & Time
            s_date = row.get("sale_date") or ""
            s_time = row.get("sale_time") or ""
            dt_item = QTableWidgetItem(f"{s_date} {s_time}".strip())
            dt_item.setTextAlignment(Qt.AlignCenter)
            self._table.setItem(r_idx, 1, dt_item)

            # 2: Customer
            c_name = row.get("customer_name") or "--"
            self._table.setItem(r_idx, 2, QTableWidgetItem(c_name))

            # 3: Patient
            p_name = row.get("patient_name") or "--"
            self._table.setItem(r_idx, 3, QTableWidgetItem(p_name))

            # 4: Doctor
            d_name = row.get("doctor_name") or "--"
            self._table.setItem(r_idx, 4, QTableWidgetItem(d_name))

            # 5: Bill Total
            tot = float(row.get("total_amount") or 0.0)
            tot_item = QTableWidgetItem(f"{tot:.2f}")
            tot_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._table.setItem(r_idx, 5, tot_item)

            # 6: Discount
            disc = float(row.get("discount") or 0.0)
            disc_item = QTableWidgetItem(f"{disc:.2f}")
            disc_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._table.setItem(r_idx, 6, disc_item)

            # 7: Paid Amount
            paid = float(row.get("paid_amount") or 0.0)
            paid_item = QTableWidgetItem(f"{paid:.2f}")
            paid_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._table.setItem(r_idx, 7, paid_item)

            # 8: Net Amount
            net = float(row.get("net_amount") or 0.0)
            net_item = QTableWidgetItem(f"{net:.2f}")
            net_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._table.setItem(r_idx, 8, net_item)

            # 9: Payment Type
            stype = row.get("sale_type") or "Cash"
            st_item = QTableWidgetItem(stype)
            st_item.setTextAlignment(Qt.AlignCenter)
            self._table.setItem(r_idx, 9, st_item)

    def refresh_theme(self):
        p = palette()
        self.setStyleSheet(f"background-color: {p['bg']}; color: {p['text']}; font-family: {FONT_FAMILY};")

        # Tables and headers
        self._table.setStyleSheet(_fresh_table_style(p))
        self._table.horizontalHeader().setStyleSheet(_fresh_header_style(p))

        # Inputs
        self._patient_edit.setStyleSheet(_fresh_edit_style(p))
        self._fy_combo.setStyleSheet(_fresh_combo_style(p))
        self._page_size_combo.setStyleSheet(_fresh_combo_style(p))
        self._from_date.setStyleSheet(_fresh_date_style(p))
        self._to_date.setStyleSheet(_fresh_date_style(p))

        # Buttons
        self._search_btn.setStyleSheet(_fresh_btn_style(p, primary=True))
        self._reset_btn.setStyleSheet(_fresh_btn_style(p))
        self._view_details_btn.setStyleSheet(_fresh_btn_style(p, primary=True))
        self._print_btn.setStyleSheet(_fresh_btn_style(p))
        self._save_pdf_btn.setStyleSheet(_fresh_btn_style(p))
        self._prev_btn.setStyleSheet(_fresh_btn_style(p))
        self._next_btn.setStyleSheet(_fresh_btn_style(p))

        # Group box
        self._filter_box.setStyleSheet(
            f"QGroupBox {{"
            f"  background-color: {p['bg']}; color: {p['text']};"
            f"  font-weight: bold; font-size: {TYPE_SECTION_HEADER}px;"
            f"  border: 1px solid {p['border']}; border-radius: 2px;"
            f"  margin-top: 10px; padding-top: 14px;"
            f"}}"
            f"QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 6px;"
            f"  color: {p['text']}; background-color: {p['bg']}; }}"
        )

