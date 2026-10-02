from __future__ import annotations

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from database.gst_report_dao import GSTReportDAO
from database.financial_year import active_date_range
from ui.theme import palette

_p = palette()
_DARK_BG = _p["bg"]
_SURFACE = _p["surface"]
_BORDER = _p["border"]
_ACCENT = _p["accent"]
_ACCENT_HOVER = _p["accent_hover"]
_TEXT = _p["text"]
_TEXT_DIM = _p["text_dim"]

_COMBO_STYLE = (
    f"QComboBox {{"
    f"  background-color: {_SURFACE}; color: {_TEXT};"
    f"  border: 1px solid {_BORDER}; border-radius: 2px;"
    f"  padding: 5px 8px; font-size: 12px; font-family: 'Segoe UI';"
    f"}}"
    f"QComboBox:hover {{ border: 1px solid {_ACCENT}; }}"
    f"QComboBox::drop-down {{ border: none; width: 22px; }}"
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
    f"  padding: 5px 8px; font-size: 12px; font-family: 'Segoe UI';"
    f"}}"
    f"QLineEdit:focus {{ border: 1px solid {_ACCENT}; }}"
)

_DATE_STYLE = (
    f"QDateEdit {{"
    f"  background-color: {_SURFACE}; color: {_TEXT};"
    f"  border: 1px solid {_BORDER}; border-radius: 2px;"
    f"  padding: 4px 6px; font-size: 12px; font-family: 'Segoe UI';"
    f"}}"
    f"QDateEdit:disabled {{ color: {_TEXT_DIM}; }}"
    f"QDateEdit::drop-down {{ border: none; }}"
)

_BTN_PRIMARY = (
    f"QPushButton {{ background-color: {_ACCENT}; color: white;"
    f"  border: none; border-radius: 2px; padding: 7px 18px;"
    f"  font-weight: bold; font-size: 12px; font-family: 'Segoe UI'; }}"
    f"QPushButton:hover {{ background-color: {_ACCENT_HOVER}; }}"
)

_BTN_SECONDARY = (
    f"QPushButton {{ background-color: {_BORDER}; color: {_TEXT};"
    f"  border: none; border-radius: 2px; padding: 7px 18px;"
    f"  font-size: 12px; font-family: 'Segoe UI'; }}"
    f"QPushButton:hover {{ background-color: #7d93a8; }}"
)

_LABEL_STYLE = (
    f"color: {_TEXT}; font-size: 12px; background: transparent;"
    f"font-family: 'Segoe UI';"
)

_CHECK_STYLE = (
    f"QCheckBox {{ color: {_TEXT}; font-size: 12px;"
    f"  font-family: 'Segoe UI'; background: transparent; }}"
    f"QCheckBox::indicator {{ width: 14px; height: 14px;"
    f"  border: 1px solid {_BORDER}; border-radius: 3px;"
    f"  background-color: {_SURFACE}; }}"
)

_NOTICE_STYLE = (
    f"color: #CC8800; font-size: 11px; font-style: italic;"
    f"background: transparent; font-family: 'Segoe UI';"
)


class GSTReportPage(QWidget):
    """GST Report page (Reports → GST Report) — read-only.

    Displays Purchase GST data stored in purchase_invoices +
    purchase_invoice_items. Sales and Return GST data is not available
    (schema limitation) and is shown as a clear notice.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setStyleSheet(f"background-color: {_DARK_BG};")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header ───────────────────────────────────────────────
        header = QWidget()
        header.setFixedHeight(52)
        header.setStyleSheet(
            f"background-color: {_SURFACE}; border-bottom: 1px solid {_BORDER};"
        )
        hl = QHBoxLayout(header)
        hl.setContentsMargins(16, 0, 16, 0)

        title = QLabel("GST Report")
        title.setStyleSheet(
            f"color: {_TEXT}; font-size: 18px; font-weight: bold;"
            f"background: transparent; font-family: 'Segoe UI';"
        )
        hl.addWidget(title)
        hl.addStretch()

        hint = QLabel("Purchase GST only — Sales/Return GST not available")
        hint.setStyleSheet(
            f"color: {_TEXT_DIM}; font-size: 11px; background: transparent;"
            f"font-family: 'Segoe UI'; margin-right: 10px;"
        )
        hl.addWidget(hint)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.setStyleSheet(_BTN_SECONDARY)
        refresh_btn.clicked.connect(self._on_refresh)
        hl.addWidget(refresh_btn)
        root.addWidget(header)

        # ── Limitation notices ───────────────────────────────────
        notice_bar = QWidget()
        notice_bar.setStyleSheet(
            f"background-color: {_SURFACE}; border-bottom: 1px solid {_BORDER};"
        )
        nl = QHBoxLayout(notice_bar)
        nl.setContentsMargins(16, 4, 16, 4)

        notice1 = QLabel(
            "Sales GST not available — sales_invoices schema lacks GST fields"
        )
        notice1.setStyleSheet(_NOTICE_STYLE)
        nl.addWidget(notice1)

        notice2 = QLabel(
            "Credit/Debit Note GST not available — schema lacks GST fields"
        )
        notice2.setStyleSheet(_NOTICE_STYLE)
        nl.addWidget(notice2)

        nl.addStretch()
        root.addWidget(notice_bar)

        # ── Filter area ──────────────────────────────────────────
        filters = QWidget()
        filters.setStyleSheet(
            f"background-color: {_SURFACE}; border-bottom: 1px solid {_BORDER};"
        )
        fv = QVBoxLayout(filters)
        fv.setContentsMargins(16, 6, 16, 6)
        fv.setSpacing(6)

        # Row 1: dates + supplier + company
        row1 = QHBoxLayout()
        row1.setSpacing(8)

        self.from_check = QCheckBox("From")
        self.from_check.setStyleSheet(_CHECK_STYLE)
        self.from_check.toggled.connect(self._on_date_toggle)
        row1.addWidget(self.from_check)

        self.from_edit = QDateEdit()
        self.from_edit.setCalendarPopup(True)
        self.from_edit.setDisplayFormat("yyyy-MM-dd")
        fy_start, fy_end = active_date_range()
        self.from_edit.setDate(QDate.fromString(fy_start, "yyyy-MM-dd"))
        self.from_edit.setFixedWidth(120)
        self.from_edit.setStyleSheet(_DATE_STYLE)
        self.from_edit.setEnabled(False)
        row1.addWidget(self.from_edit)

        self.to_check = QCheckBox("To")
        self.to_check.setStyleSheet(_CHECK_STYLE)
        self.to_check.toggled.connect(self._on_date_toggle)
        row1.addWidget(self.to_check)

        self.to_edit = QDateEdit()
        self.to_edit.setCalendarPopup(True)
        self.to_edit.setDisplayFormat("yyyy-MM-dd")
        self.to_edit.setDate(QDate.fromString(fy_end, "yyyy-MM-dd"))
        self.to_edit.setFixedWidth(120)
        self.to_edit.setStyleSheet(_DATE_STYLE)
        self.to_edit.setEnabled(False)
        row1.addWidget(self.to_edit)

        row1.addSpacing(12)
        row1.addWidget(self._label("Supplier"))
        self.supplier_combo = QComboBox()
        self.supplier_combo.setStyleSheet(_COMBO_STYLE)
        self.supplier_combo.setMinimumWidth(150)
        row1.addWidget(self.supplier_combo)

        row1.addWidget(self._label("Company"))
        self.company_combo = QComboBox()
        self.company_combo.setStyleSheet(_COMBO_STYLE)
        self.company_combo.setMinimumWidth(140)
        row1.addWidget(self.company_combo)
        row1.addStretch()
        fv.addLayout(row1)

        # Row 2: item + GST % + invoice/voucher + actions
        row2 = QHBoxLayout()
        row2.setSpacing(8)

        row2.addWidget(self._label("Item"))
        self.item_combo = QComboBox()
        self.item_combo.setStyleSheet(_COMBO_STYLE)
        self.item_combo.setMinimumWidth(150)
        row2.addWidget(self.item_combo)

        row2.addWidget(self._label("GST %"))
        self.gst_combo = QComboBox()
        self.gst_combo.setStyleSheet(_COMBO_STYLE)
        self.gst_combo.setMinimumWidth(80)
        row2.addWidget(self.gst_combo)

        row2.addWidget(self._label("Invoice No"))
        self.invoice_edit = QLineEdit()
        self.invoice_edit.setStyleSheet(_EDIT_STYLE)
        self.invoice_edit.setPlaceholderText("e.g. INV-001")
        self.invoice_edit.setFixedWidth(110)
        self.invoice_edit.returnPressed.connect(self._on_generate)
        row2.addWidget(self.invoice_edit)

        row2.addWidget(self._label("Voucher No"))
        self.voucher_edit = QLineEdit()
        self.voucher_edit.setStyleSheet(_EDIT_STYLE)
        self.voucher_edit.setPlaceholderText("e.g. PV-0001")
        self.voucher_edit.setFixedWidth(110)
        self.voucher_edit.returnPressed.connect(self._on_generate)
        row2.addWidget(self.voucher_edit)

        row2.addStretch()

        search_btn = QPushButton("Search")
        search_btn.setStyleSheet(_BTN_PRIMARY)
        search_btn.clicked.connect(self._on_generate)
        row2.addWidget(search_btn)

        clear_btn = QPushButton("Clear")
        clear_btn.setStyleSheet(_BTN_SECONDARY)
        clear_btn.clicked.connect(self._on_clear)
        row2.addWidget(clear_btn)
        fv.addLayout(row2)

        root.addWidget(filters)

        # ── Purchase GST Table ───────────────────────────────────
        section_label = QLabel("  Purchase GST")
        section_label.setStyleSheet(
            f"color: {_TEXT}; font-size: 13px; font-weight: bold;"
            f"background: {_SURFACE}; padding: 4px 16px;"
            f"font-family: 'Segoe UI';"
        )
        root.addWidget(section_label)

        self._columns = [
            "Voucher No", "Voucher Date", "Invoice No", "Invoice Date",
            "Supplier", "Item Name", "Company", "Batch No",
            "Pay Qty", "Free Qty", "GST %", "Taxable Amt", "GST Amt",
            "Amount",
        ]
        self._table = QTableWidget()
        self._table.setColumnCount(len(self._columns))
        self._table.setHorizontalHeaderLabels(self._columns)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(True)

        hv = self._table.horizontalHeader()
        hv.setStretchLastSection(True)
        hv.setSectionResizeMode(5, QHeaderView.Stretch)
        hv.setStyleSheet(
            f"QHeaderView::section {{"
            f"  background-color: {_SURFACE}; color: {_TEXT};"
            f"  border: none; border-bottom: 2px solid {_ACCENT};"
            f"  padding: 3px 6px; font-weight: bold; font-size: 9pt;"
            f"  font-family: 'Segoe UI';"
            f"}}"
        )
        self._table.setStyleSheet(
            f"QTableWidget {{"
            f"  background-color: {_DARK_BG}; color: {_TEXT};"
            f"  border: 1px solid {_BORDER}; gridline-color: {_BORDER};"
            f"  font-size: 11px; font-family: 'Segoe UI';"
            f"  selection-background-color: {_ACCENT}; selection-color: white;"
            f"}}"
            f"QTableWidget::item {{ padding: 2px 5px; }}"
        )
        root.addWidget(self._table, 1)

        # ── GST Rate Summary Table ───────────────────────────────
        rate_label = QLabel("  GST Rate Summary")
        rate_label.setStyleSheet(
            f"color: {_TEXT}; font-size: 13px; font-weight: bold;"
            f"background: {_SURFACE}; padding: 4px 16px;"
            f"font-family: 'Segoe UI';"
        )
        root.addWidget(rate_label)

        self._rate_columns = ["GST %", "Taxable Amount", "GST Amount"]
        self._rate_table = QTableWidget()
        self._rate_table.setColumnCount(3)
        self._rate_table.setHorizontalHeaderLabels(self._rate_columns)
        self._rate_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._rate_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._rate_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._rate_table.verticalHeader().setVisible(False)
        self._rate_table.setShowGrid(True)
        self._rate_table.setMaximumHeight(160)

        rhv = self._rate_table.horizontalHeader()
        rhv.setStretchLastSection(True)
        rhv.setStyleSheet(
            f"QHeaderView::section {{"
            f"  background-color: {_SURFACE}; color: {_TEXT};"
            f"  border: none; border-bottom: 2px solid {_ACCENT};"
            f"  padding: 3px 6px; font-weight: bold; font-size: 9pt;"
            f"  font-family: 'Segoe UI';"
            f"}}"
        )
        self._rate_table.setStyleSheet(
            f"QTableWidget {{"
            f"  background-color: {_DARK_BG}; color: {_TEXT};"
            f"  border: 1px solid {_BORDER}; gridline-color: {_BORDER};"
            f"  font-size: 11px; font-family: 'Segoe UI';"
            f"  selection-background-color: {_ACCENT}; selection-color: white;"
            f"}}"
            f"QTableWidget::item {{ padding: 2px 5px; }}"
        )
        root.addWidget(self._rate_table, 0)

        # ── Summary bar ──────────────────────────────────────────
        summary = QWidget()
        summary.setFixedHeight(40)
        summary.setStyleSheet(
            f"background-color: {_SURFACE}; border-top: 1px solid {_BORDER};"
        )
        sl = QHBoxLayout(summary)
        sl.setContentsMargins(16, 0, 16, 0)
        sl.setSpacing(18)

        self._summary_labels: dict[str, QLabel] = {}
        for key, text in (
            ("bills", "Bills: 0"),
            ("lines", "Items: 0"),
            ("taxable", "Taxable: 0.00"),
            ("gst", "GST: 0.00"),
            ("discount", "Discount: 0.00"),
            ("net", "Net: 0.00"),
        ):
            lbl = QLabel(text)
            lbl.setStyleSheet(
                f"color: {_TEXT}; font-size: 12px; font-weight: bold;"
                f"background: transparent; font-family: 'Segoe UI';"
            )
            self._summary_labels[key] = lbl
            sl.addWidget(lbl)
        sl.addStretch()
        root.addWidget(summary)

        self._load_filter_options()
        self._on_generate()

    # ------------------------------------------------------------------
    def _label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(_LABEL_STYLE)
        return lbl

    def _load_filter_options(self):
        options = GSTReportDAO.get_filter_options()
        for combo, rows, id_key, name_key in (
            (self.supplier_combo, options["suppliers"], "id", "supplier_name"),
            (self.company_combo, options["companies"], "id", "company_name"),
            (self.item_combo, options["items"], "id", "item_name"),
        ):
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("All", None)
            for row in rows:
                combo.addItem(row[name_key], row[id_key])
            combo.setCurrentIndex(0)
            combo.blockSignals(False)

        # GST % combo — populated from actual data
        self.gst_combo.blockSignals(True)
        self.gst_combo.clear()
        self.gst_combo.addItem("All", None)
        for row in options["gst_percents"]:
            self.gst_combo.addItem(f"{row['gst_percent']:g}%", row["gst_percent"])
        self.gst_combo.setCurrentIndex(0)
        self.gst_combo.blockSignals(False)

    def _on_date_toggle(self):
        self.from_edit.setEnabled(self.from_check.isChecked())
        self.to_edit.setEnabled(self.to_check.isChecked())

    def _current_filters(self) -> dict:
        return {
            "from_date": (
                self.from_edit.date().toString("yyyy-MM-dd")
                if self.from_check.isChecked() else None
            ),
            "to_date": (
                self.to_edit.date().toString("yyyy-MM-dd")
                if self.to_check.isChecked() else None
            ),
            "supplier_id": self.supplier_combo.currentData(),
            "item_id": self.item_combo.currentData(),
            "company_id": self.company_combo.currentData(),
            "gst_percent": self.gst_combo.currentData(),
            "invoice_no": self.invoice_edit.text().strip() or None,
            "voucher_no": self.voucher_edit.text().strip() or None,
        }

    # ------------------------------------------------------------------
    def _render(self, report: dict):
        rows = report["rows"]
        self._table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            values = [
                r["voucher_no"],
                r["voucher_date"],
                r["invoice_no"] or "",
                r["invoice_date"] or "",
                r["supplier_name"] or "",
                r["item_name"] or "",
                r["company_name"] or "",
                r["batch_no"] or "",
                f"{r['pay_qty']:g}",
                f"{r['free_qty']:g}",
                f"{r['gst_percent']:g}",
                f"{r['taxable_amount']:,.2f}",
                f"{r['gst_amount']:,.2f}",
                f"{r['amount']:,.2f}",
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if col >= 8:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self._table.setItem(i, col, item)

        s = report["summary"]
        self._summary_labels["bills"].setText(f"Bills: {s['total_bills']}")
        self._summary_labels["lines"].setText(f"Items: {s['total_lines']}")
        self._summary_labels["taxable"].setText(
            f"Taxable: {s['total_taxable']:,.2f}"
        )
        self._summary_labels["gst"].setText(f"GST: {s['total_gst']:,.2f}")
        self._summary_labels["discount"].setText(
            f"Discount: {s['total_bill_discount']:,.2f}"
        )
        self._summary_labels["net"].setText(f"Net: {s['total_net']:,.2f}")

    def _render_rate_summary(self, rate_summary: list[dict]):
        self._rate_table.setRowCount(len(rate_summary))
        for i, r in enumerate(rate_summary):
            values = [
                f"{r['gst_percent']:g}%",
                f"{r['taxable_amount']:,.2f}",
                f"{r['gst_amount']:,.2f}",
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if col >= 1:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self._rate_table.setItem(i, col, item)

    def _on_generate(self):
        try:
            filters = self._current_filters()
            report = GSTReportDAO.get_purchase_gst_report(**filters)
            self._render(report)
            rate_summary = GSTReportDAO.get_gst_rate_summary(
                from_date=filters["from_date"],
                to_date=filters["to_date"],
                supplier_id=filters["supplier_id"],
                item_id=filters["item_id"],
                company_id=filters["company_id"],
                invoice_no=filters["invoice_no"],
                voucher_no=filters["voucher_no"],
            )
            self._render_rate_summary(rate_summary)
        except Exception as e:
            QMessageBox.critical(
                self, "Error", f"Failed to generate GST Report:\n{e}"
            )

    def _on_refresh(self):
        self._load_filter_options()
        self._on_generate()

    def _on_clear(self):
        self.from_check.setChecked(False)
        self.to_check.setChecked(False)
        self.supplier_combo.setCurrentIndex(0)
        self.company_combo.setCurrentIndex(0)
        self.item_combo.setCurrentIndex(0)
        self.gst_combo.setCurrentIndex(0)
        self.invoice_edit.clear()
        self.voucher_edit.clear()
        self._on_generate()
