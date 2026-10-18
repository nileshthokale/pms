"""Customer Ledger report screen.

Displays detailed accounting transactions for a chosen customer, including:
- Date range filtering respecting the active / selected financial year
- Searchable customer selection
- Opening balance before the first transaction (with DR/CR)
- Transaction-wise debit, credit, voucher details, and running balance (with DR/CR)
- Closing balance after the last transaction (with DR/CR)
- Total debits and credits
- Full day/night theme support
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
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

from core.doc_formatter import format_document_number
from database import financial_year
from database.ledger_report_dao import LedgerReportDAO
from screens.ledger_widgets import (
    SearchableSelector,
    btn_primary_style,
    btn_secondary_style,
    make_date_edit,
    table_header_style,
    table_style,
)
from ui.fy_view import view_year_bounds
from ui.theme import palette, TYPE_PAGE_TITLE


class CustomerLedgerPage(QWidget):
    """Customer Ledger page (Reports -> Customer Ledger)."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._history_financial_year: dict | None = None
        self._last_report: dict | None = None

        p = palette()
        self.setStyleSheet(f"background-color: {p['bg']};")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── 1. Header ───────────────────────────────────────────────
        self._header = QWidget()
        self._header.setFixedHeight(54)
        hl = QHBoxLayout(self._header)
        hl.setContentsMargins(16, 0, 16, 0)

        self._title_label = QLabel("Customer Ledger")
        self._title_label.setStyleSheet(
            f"color: {p['text']}; font-size: {TYPE_PAGE_TITLE}px; font-weight: bold;"
            f"background: transparent; font-family: 'Segoe UI';"
        )
        hl.addWidget(self._title_label)

        self._header_hint = QLabel(
            "Detailed customer accounting transactions · Running balance · DR / CR"
        )
        self._header_hint.setStyleSheet(
            f"color: {p['text_dim']}; font-size: 13px; background: transparent;"
            f"font-family: 'Segoe UI'; margin-left: 14px;"
        )
        hl.addWidget(self._header_hint)
        hl.addStretch()

        root.addWidget(self._header)

        # ── 2. Filter Bar ───────────────────────────────────────────
        self._filter_bar = QWidget()
        fl = QHBoxLayout(self._filter_bar)
        fl.setContentsMargins(16, 8, 16, 8)
        fl.setSpacing(10)

        self._lbl_customer = QLabel("Customer:")
        self._lbl_customer.setStyleSheet(f"color: {p['text']}; font-weight: bold; font-size: 14px;")
        fl.addWidget(self._lbl_customer)

        self._customer_selector = SearchableSelector(placeholder="-- Select Customer --")
        self._customer_selector.setMinimumWidth(260)
        self._customer_selector.selection_changed.connect(self._on_customer_changed)
        fl.addWidget(self._customer_selector)

        self._lbl_from = QLabel("From Date:")
        self._lbl_from.setStyleSheet(f"color: {p['text']}; font-weight: bold; font-size: 14px;")
        fl.addWidget(self._lbl_from)

        self._from_date = make_date_edit(self)
        self._from_date.setFixedWidth(125)
        fl.addWidget(self._from_date)

        self._lbl_to = QLabel("To Date:")
        self._lbl_to.setStyleSheet(f"color: {p['text']}; font-weight: bold; font-size: 14px;")
        fl.addWidget(self._lbl_to)

        self._to_date = make_date_edit(self)
        self._to_date.setFixedWidth(125)
        fl.addWidget(self._to_date)

        self._btn_show = QPushButton("Show Report")
        self._btn_show.setStyleSheet(btn_primary_style(p))
        self._btn_show.clicked.connect(self._on_generate)
        fl.addWidget(self._btn_show)

        self._btn_refresh = QPushButton("Refresh")
        self._btn_refresh.setStyleSheet(btn_secondary_style(p))
        self._btn_refresh.clicked.connect(self._on_refresh)
        fl.addWidget(self._btn_refresh)

        self._btn_clear = QPushButton("Clear")
        self._btn_clear.setStyleSheet(btn_secondary_style(p))
        self._btn_clear.clicked.connect(self._on_clear)
        fl.addWidget(self._btn_clear)

        fl.addStretch()
        root.addWidget(self._filter_bar)

        # ── 3. Summary Panel ────────────────────────────────────────
        self._summary_panel = QWidget()
        self._summary_panel.setFixedHeight(68)
        sl = QHBoxLayout(self._summary_panel)
        sl.setContentsMargins(16, 6, 16, 6)
        sl.setSpacing(20)

        # Details box
        self._info_party = QLabel("Party: -")
        self._info_party.setStyleSheet(f"color: {p['text']}; font-size: 14px; font-weight: bold;")
        sl.addWidget(self._info_party)

        # Opening balance
        self._lbl_card_ob = QLabel("Opening Balance:")
        self._lbl_card_ob.setStyleSheet(f"color: {p['text_dim']}; font-size: 13px; font-weight: bold;")
        self._val_card_ob = QLabel("0.00 DR")
        self._val_card_ob.setStyleSheet(f"color: {p['text']}; font-size: 15px; font-weight: bold;")
        ob_box = QVBoxLayout()
        ob_box.setSpacing(2)
        ob_box.addWidget(self._lbl_card_ob)
        ob_box.addWidget(self._val_card_ob)
        sl.addLayout(ob_box)

        # Total debit
        self._lbl_card_dr = QLabel("Total Debit (Dr):")
        self._lbl_card_dr.setStyleSheet(f"color: {p['text_dim']}; font-size: 13px; font-weight: bold;")
        self._val_card_dr = QLabel("0.00")
        self._val_card_dr.setStyleSheet(f"color: {p['text']}; font-size: 15px; font-weight: bold;")
        dr_box = QVBoxLayout()
        dr_box.setSpacing(2)
        dr_box.addWidget(self._lbl_card_dr)
        dr_box.addWidget(self._val_card_dr)
        sl.addLayout(dr_box)

        # Total credit
        self._lbl_card_cr = QLabel("Total Credit (Cr):")
        self._lbl_card_cr.setStyleSheet(f"color: {p['text_dim']}; font-size: 13px; font-weight: bold;")
        self._val_card_cr = QLabel("0.00")
        self._val_card_cr.setStyleSheet(f"color: {p['text']}; font-size: 15px; font-weight: bold;")
        cr_box = QVBoxLayout()
        cr_box.setSpacing(2)
        cr_box.addWidget(self._lbl_card_cr)
        cr_box.addWidget(self._val_card_cr)
        sl.addLayout(cr_box)

        # Closing balance
        self._lbl_card_cb = QLabel("Closing Balance:")
        self._lbl_card_cb.setStyleSheet(f"color: {p['text_dim']}; font-size: 13px; font-weight: bold;")
        self._val_card_cb = QLabel("0.00 DR")
        self._val_card_cb.setStyleSheet(f"color: {p['accent']}; font-size: 16px; font-weight: bold;")
        cb_box = QVBoxLayout()
        cb_box.setSpacing(2)
        cb_box.addWidget(self._lbl_card_cb)
        cb_box.addWidget(self._val_card_cb)
        sl.addLayout(cb_box)

        sl.addStretch()

        # Warning / status indicator
        self._status_badge = QLabel("")
        self._status_badge.setStyleSheet(f"color: {p.get('danger', '#c0392b')}; font-size: 13px; font-weight: bold;")
        sl.addWidget(self._status_badge)

        root.addWidget(self._summary_panel)

        # ── 4. Transaction Table ────────────────────────────────────
        self._columns = [
            "Date", "Particulars", "Voucher Type", "Voucher No",
            "Debit (Dr)", "Credit (Cr)", "Balance"
        ]
        self._table = QTableWidget()
        self._table.setColumnCount(len(self._columns))
        self._table.setHorizontalHeaderLabels(self._columns)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(True)
        self._table.setAlternatingRowColors(False)

        hv = self._table.horizontalHeader()
        hv.setStretchLastSection(False)
        hv.setSectionResizeMode(0, QHeaderView.ResizeToContents)  # Date
        hv.setSectionResizeMode(1, QHeaderView.Stretch)           # Particulars
        hv.setSectionResizeMode(2, QHeaderView.ResizeToContents)  # Voucher Type
        hv.setSectionResizeMode(3, QHeaderView.ResizeToContents)  # Voucher No
        hv.setSectionResizeMode(4, QHeaderView.ResizeToContents)  # Debit
        hv.setSectionResizeMode(5, QHeaderView.ResizeToContents)  # Credit
        hv.setSectionResizeMode(6, QHeaderView.ResizeToContents)  # Balance

        root.addWidget(self._table, 1)

        self._apply_theme_styles(p)
        self._load_options()
        self._set_default_dates()

    # ── Option loading & Date initialization ─────────────────────────

    def _load_options(self):
        customers = LedgerReportDAO.get_customer_options()
        self._customer_selector.set_options(
            customers, id_key="id", name_key="customer_name", subtitle_key="city"
        )

    def _set_default_dates(self):
        """Default range: FY start date to today's date, respecting viewing FY."""
        fy_from, fy_to = view_year_bounds(self._history_financial_year)
        today_iso = date.today().isoformat()
        if fy_from <= today_iso <= fy_to:
            default_to = today_iso
        elif today_iso > fy_to:
            default_to = fy_to
        else:
            default_to = fy_to

        self._from_date.blockSignals(True)
        self._to_date.blockSignals(True)
        self._from_date.setDate(QDate.fromString(fy_from, "yyyy-MM-dd"))
        self._to_date.setDate(QDate.fromString(default_to, "yyyy-MM-dd"))
        self._from_date.blockSignals(False)
        self._to_date.blockSignals(False)

    def set_history_financial_year(self, year: dict | None) -> None:
        """Called when user changes financial year view from the navigation bar."""
        self._history_financial_year = dict(year) if year else None
        self._set_default_dates()
        if self._customer_selector.selected_id:
            self._on_generate()

    # ── Report Generation ────────────────────────────────────────────

    def _on_customer_changed(self, customer_id):
        if customer_id:
            self._on_generate()

    def _on_refresh(self):
        self._load_options()
        if self._customer_selector.selected_id:
            self._on_generate()

    def _on_clear(self):
        self._customer_selector.clear_selection()
        self._set_default_dates()
        self._table.setRowCount(0)
        self._info_party.setText("Party: -")
        self._val_card_ob.setText("0.00 DR")
        self._val_card_dr.setText("0.00")
        self._val_card_cr.setText("0.00")
        self._val_card_cb.setText("0.00 DR")
        self._status_badge.setText("")

    def _on_generate(self):
        customer_id = self._customer_selector.selected_id
        if not customer_id:
            QMessageBox.information(
                self, "Customer Ledger", "Please select a customer from the list."
            )
            return

        from_iso = self._from_date.date().toString("yyyy-MM-dd")
        to_iso = self._to_date.date().toString("yyyy-MM-dd")

        if from_iso > to_iso:
            QMessageBox.warning(
                self, "Date Error", "From Date cannot be later than To Date."
            )
            return

        try:
            report = LedgerReportDAO.get_customer_ledger(
                customer_id=customer_id,
                from_date=from_iso,
                to_date=to_iso,
            )
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to generate report:\n{exc}")
            return

        self._last_report = report
        self._render(report)

    # ── Rendering ────────────────────────────────────────────────────

    def _render(self, report: dict):
        p = palette()
        cust = report.get("customer") or {}
        pname = cust.get("customer_name", "")
        city = cust.get("city", "")
        contact = cust.get("contact_no", "")

        info_parts = [f"Party: {pname}"]
        if city:
            info_parts.append(f"({city})")
        if contact:
            info_parts.append(f"Ph: {contact}")
        self._info_party.setText("  ".join(info_parts))

        ob = report["opening_balance"]
        ob_type = report["opening_balance_type"]
        self._val_card_ob.setText(f"{ob:,.2f} {ob_type}")

        td = report["total_debit"]
        tc = report["total_credit"]
        self._val_card_dr.setText(f"{td:,.2f}")
        self._val_card_cr.setText(f"{tc:,.2f}")

        cb = report["closing_balance"]
        cb_type = report["closing_balance_type"]
        self._val_card_cb.setText(f"{cb:,.2f} {cb_type}")

        warning = report.get("warning")
        if warning:
            self._status_badge.setText(warning)
            self._status_badge.setStyleSheet(f"color: {p.get('danger', '#c0392b')}; font-weight: bold;")
        elif not report["rows"]:
            self._status_badge.setText("No transactions found for selected period.")
            self._status_badge.setStyleSheet(f"color: {p['text_dim']}; font-weight: normal;")
        else:
            self._status_badge.setText(f"{len(report['rows'])} transaction(s)")
            self._status_badge.setStyleSheet(f"color: {p['text_dim']}; font-weight: normal;")

        txns = report["rows"]
        total_rows = len(txns) + 2
        self._table.setRowCount(total_rows)

        # ── Row 0: Opening Balance ──
        self._set_cell(0, 0, report["from_date"], bold=True)
        self._set_cell(0, 1, "*** OPENING BALANCE ***", bold=True)
        self._set_cell(0, 2, "-", align=Qt.AlignCenter)
        self._set_cell(0, 3, "-", align=Qt.AlignCenter)
        self._set_cell(0, 4, "-", align=Qt.AlignRight)
        self._set_cell(0, 5, "-", align=Qt.AlignRight)
        self._set_cell(0, 6, f"{ob:,.2f} {ob_type}", bold=True, align=Qt.AlignRight,
                       color=p.get("danger", "#c0392b") if ob_type == "DR" else p.get("success", "#2e7d32"))

        # ── Rows 1..N: Transactions ──
        for idx, t in enumerate(txns, start=1):
            self._set_cell(idx, 0, t["transaction_date"])
            self._set_cell(idx, 1, t["particulars"])
            self._set_cell(idx, 2, t["voucher_type"])

            vno = t["voucher_no"]
            disp_vno = format_document_number(vno)
            self._set_cell(idx, 3, disp_vno, tooltip=f"Voucher: {vno}")

            d_val = t["debit"]
            d_text = f"{d_val:,.2f}" if d_val else ""
            self._set_cell(idx, 4, d_text, align=Qt.AlignRight)

            c_val = t["credit"]
            c_text = f"{c_val:,.2f}" if c_val else ""
            self._set_cell(idx, 5, c_text, align=Qt.AlignRight)

            bal = t["running_balance"]
            b_type = t["running_balance_type"]
            bal_text = f"{bal:,.2f} {b_type}"
            color = p.get("danger", "#c0392b") if b_type == "DR" else p.get("success", "#2e7d32")
            self._set_cell(idx, 6, bal_text, align=Qt.AlignRight, color=color)

        # ── Last Row: Totals & Closing Balance ──
        last_row = total_rows - 1
        self._set_cell(last_row, 0, report["to_date"], bold=True)
        self._set_cell(last_row, 1, "*** TOTALS & CLOSING BALANCE ***", bold=True)
        self._set_cell(last_row, 2, "-", align=Qt.AlignCenter)
        self._set_cell(last_row, 3, "-", align=Qt.AlignCenter)
        self._set_cell(last_row, 4, f"{td:,.2f}", bold=True, align=Qt.AlignRight)
        self._set_cell(last_row, 5, f"{tc:,.2f}", bold=True, align=Qt.AlignRight)
        self._set_cell(last_row, 6, f"{cb:,.2f} {cb_type}", bold=True, align=Qt.AlignRight,
                       color=p.get("danger", "#c0392b") if cb_type == "DR" else p.get("success", "#2e7d32"))

    def _set_cell(
        self,
        row: int,
        col: int,
        text: str,
        bold: bool = False,
        align: int = Qt.AlignLeft | Qt.AlignVCenter,
        color: str | None = None,
        tooltip: str | None = None,
    ):
        item = QTableWidgetItem(str(text))
        item.setTextAlignment(align)
        if bold:
            f = item.font()
            f.setBold(True)
            item.setFont(f)
        if color:
            from PySide6.QtGui import QColor
            item.setForeground(QColor(color))
        if tooltip:
            item.setToolTip(tooltip)
        self._table.setItem(row, col, item)

    # ── Theme Refresh ────────────────────────────────────────────────

    def _apply_theme_styles(self, p: dict):
        self.setStyleSheet(f"background-color: {p['bg']};")
        self._header.setStyleSheet(
            f"background-color: {p['surface']}; border-bottom: 1px solid {p['border']};"
        )
        self._filter_bar.setStyleSheet(
            f"background-color: {p['surface']}; border-bottom: 1px solid {p['border']};"
        )
        self._summary_panel.setStyleSheet(
            f"background-color: {p.get('surface_alt', p['surface'])}; border-bottom: 1px solid {p['border']};"
        )
        self._table.setStyleSheet(table_style(p))
        self._table.horizontalHeader().setStyleSheet(table_header_style(p))

        self._btn_show.setStyleSheet(btn_primary_style(p))
        self._btn_refresh.setStyleSheet(btn_secondary_style(p))
        self._btn_clear.setStyleSheet(btn_secondary_style(p))

        self._customer_selector.refresh_theme(p)

    def refresh_theme(self, p: dict | None = None) -> None:
        p = p or palette()
        self._apply_theme_styles(p)
        if self._last_report:
            self._render(self._last_report)
