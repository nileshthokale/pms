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

from database.sales_report_dao import SalesReportDAO
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


class SalesReportPage(QWidget):
    """Sales Report page (Reports → Sales Report) — read-only.

    Reports the application's sales source documents
    (sales_invoices + sales_invoice_items). Financial reports (Trial
    Balance, P&L, Balance Sheet) are based on ledger postings instead.
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

        title = QLabel("Sales Report")
        title.setStyleSheet(
            f"color: {_TEXT}; font-size: 18px; font-weight: bold;"
            f"background: transparent; font-family: 'Segoe UI';"
        )
        hl.addWidget(title)
        hl.addStretch()

        hint = QLabel("Based on sales bills — financial reports use ledger postings")
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

        # ── Filter area ──────────────────────────────────────────
        filters = QWidget()
        filters.setStyleSheet(
            f"background-color: {_SURFACE}; border-bottom: 1px solid {_BORDER};"
        )
        fv = QVBoxLayout(filters)
        fv.setContentsMargins(16, 6, 16, 6)
        fv.setSpacing(6)

        # Row 1: dates + customer + doctor
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
        row1.addWidget(self._label("Customer"))
        self.customer_combo = QComboBox()
        self.customer_combo.setStyleSheet(_COMBO_STYLE)
        self.customer_combo.setMinimumWidth(150)
        row1.addWidget(self.customer_combo)

        row1.addWidget(self._label("Doctor"))
        self.doctor_combo = QComboBox()
        self.doctor_combo.setStyleSheet(_COMBO_STYLE)
        self.doctor_combo.setMinimumWidth(140)
        row1.addWidget(self.doctor_combo)
        row1.addStretch()
        fv.addLayout(row1)

        # Row 2: company + item + bill no + patient + actions
        row2 = QHBoxLayout()
        row2.setSpacing(8)

        row2.addWidget(self._label("Company"))
        self.company_combo = QComboBox()
        self.company_combo.setStyleSheet(_COMBO_STYLE)
        self.company_combo.setMinimumWidth(130)
        row2.addWidget(self.company_combo)

        row2.addWidget(self._label("Item"))
        self.item_combo = QComboBox()
        self.item_combo.setStyleSheet(_COMBO_STYLE)
        self.item_combo.setMinimumWidth(150)
        row2.addWidget(self.item_combo)

        row2.addWidget(self._label("Bill No"))
        self.bill_edit = QLineEdit()
        self.bill_edit.setStyleSheet(_EDIT_STYLE)
        self.bill_edit.setPlaceholderText("e.g. CS-0001")
        self.bill_edit.setFixedWidth(110)
        self.bill_edit.returnPressed.connect(self._on_generate)
        row2.addWidget(self.bill_edit)

        row2.addWidget(self._label("Patient"))
        self.patient_edit = QLineEdit()
        self.patient_edit.setStyleSheet(_EDIT_STYLE)
        self.patient_edit.setPlaceholderText("patient name")
        self.patient_edit.setFixedWidth(120)
        self.patient_edit.returnPressed.connect(self._on_generate)
        row2.addWidget(self.patient_edit)

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

        # ── Table ────────────────────────────────────────────────
        self._table = QTableWidget()
        self._table.setColumnCount(12)
        self._table.setHorizontalHeaderLabels([
            "Bill No", "Sale Date", "Customer", "Patient", "Doctor",
            "Item Name", "Batch No", "Expiry", "MRP", "Qty",
            "Discount", "Amount",
        ])
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(True)

        hv = self._table.horizontalHeader()
        hv.setStretchLastSection(True)
        hv.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hv.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hv.setSectionResizeMode(5, QHeaderView.Stretch)
        hv.setStyleSheet(
            f"QHeaderView::section {{"
            f"  background-color: {_SURFACE}; color: {_TEXT};"
            f"  border: none; border-bottom: 2px solid {_ACCENT};"
            f"  padding: 3px 6px; font-weight: bold; font-size: 12px;"
            f"  font-family: 'Segoe UI';"
            f"}}"
        )
        self._table.setStyleSheet(
            f"QTableWidget {{"
            f"  background-color: {_DARK_BG}; color: {_TEXT};"
            f"  border: 1px solid {_BORDER}; gridline-color: {_BORDER};"
            f"  font-size: 13px; font-family: 'Segoe UI';"
            f"  selection-background-color: {_ACCENT}; selection-color: white;"
            f"}}"
            f"QTableWidget::item {{ padding: 2px 5px; }}"
        )
        root.addWidget(self._table, 1)

        # ── Summary bar ──────────────────────────────────────────
        summary = QWidget()
        summary.setFixedHeight(40)
        summary.setStyleSheet(
            f"background-color: {_SURFACE}; border-top: 1px solid {_BORDER};"
        )
        sl = QHBoxLayout(summary)
        sl.setContentsMargins(16, 0, 16, 0)
        sl.setSpacing(22)

        self._summary_labels: dict[str, QLabel] = {}
        for key, text in (
            ("bills", "Bills: 0"),
            ("lines", "Items: 0"),
            ("qty", "Qty: 0"),
            ("gross", "Gross: 0.00"),
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
        options = SalesReportDAO.get_filter_options()
        for combo, rows, id_key, name_key in (
            (self.customer_combo, options["customers"], "id", "customer_name"),
            (self.doctor_combo, options["doctors"], "id", "doctor_name"),
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
            "customer_id": self.customer_combo.currentData(),
            "item_id": self.item_combo.currentData(),
            "company_id": self.company_combo.currentData(),
            "bill_no": self.bill_edit.text().strip() or None,
            "patient": self.patient_edit.text().strip() or None,
            "doctor_id": self.doctor_combo.currentData(),
        }

    # ------------------------------------------------------------------
    def _render(self, report: dict):
        rows = report["rows"]
        self._table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            values = [
                r["bill_no"],
                r["sale_date"],
                r["customer_name"] or "",
                r["patient_name"] or "",
                r["doctor_name"] or "",
                r["item_name"] or "",
                r["batch_no"] or "",
                r["expiry"] or "",
                f"{r['mrp']:,.2f}",
                f"{r['sale_qty']:g}",
                f"{r['discount_amount']:,.2f}",
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
        self._summary_labels["qty"].setText(f"Qty: {s['total_qty']:g}")
        self._summary_labels["gross"].setText(f"Gross: {s['total_gross']:,.2f}")
        self._summary_labels["discount"].setText(
            f"Discount: {s['total_discount']:,.2f}"
        )
        self._summary_labels["net"].setText(f"Net: {s['total_net']:,.2f}")

    def _on_generate(self):
        try:
            self._render(SalesReportDAO.get_sales_report(**self._current_filters()))
        except Exception as e:
            QMessageBox.critical(
                self, "Error", f"Failed to generate Sales Report:\n{e}"
            )

    def _on_refresh(self):
        self._load_filter_options()
        self._on_generate()

    def _on_clear(self):
        self.from_check.setChecked(False)
        self.to_check.setChecked(False)
        self.customer_combo.setCurrentIndex(0)
        self.doctor_combo.setCurrentIndex(0)
        self.company_combo.setCurrentIndex(0)
        self.item_combo.setCurrentIndex(0)
        self.bill_edit.clear()
        self.patient_edit.clear()
        self._on_generate()
