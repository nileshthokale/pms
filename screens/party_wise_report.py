from __future__ import annotations

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
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

from database.party_wise_report_dao import PartyWiseReportDAO
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


class PartyWiseReportPage(QWidget):
    """Party Wise Report page (Reports → Party Wise Report) — read-only.

    Shows transaction summaries for Customers and Suppliers with
    outstanding balances sourced from the mapped Account Ledger.
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

        title = QLabel("Party Wise Report")
        title.setStyleSheet(
            f"color: {_TEXT}; font-size: 18px; font-weight: bold;"
            f"background: transparent; font-family: 'Segoe UI';"
        )
        hl.addWidget(title)
        hl.addStretch()

        hint = QLabel(
            "Balances from Account Ledger — operational totals from source tables"
        )
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

        # Row 1: party type + dates + party name
        row1 = QHBoxLayout()
        row1.setSpacing(8)

        row1.addWidget(self._label("Party Type"))
        self.party_type_combo = QComboBox()
        self.party_type_combo.addItems(["All", "Customer", "Supplier"])
        self.party_type_combo.setStyleSheet(_COMBO_STYLE)
        self.party_type_combo.setMinimumWidth(110)
        self.party_type_combo.currentIndexChanged.connect(
            self._on_party_type_changed
        )
        row1.addWidget(self.party_type_combo)

        row1.addWidget(self._label("From Date"))
        self.from_edit = QDateEdit()
        self.from_edit.setCalendarPopup(True)
        self.from_edit.setDisplayFormat("yyyy-MM-dd")
        fy_start, fy_end = active_date_range()
        self.from_edit.setDate(QDate.fromString(fy_start, "yyyy-MM-dd"))
        self.from_edit.setFixedWidth(120)
        self.from_edit.setStyleSheet(_DATE_STYLE)
        row1.addWidget(self.from_edit)

        row1.addWidget(self._label("To Date"))
        self.to_edit = QDateEdit()
        self.to_edit.setCalendarPopup(True)
        self.to_edit.setDisplayFormat("yyyy-MM-dd")
        self.to_edit.setDate(QDate.fromString(fy_end, "yyyy-MM-dd"))
        self.to_edit.setFixedWidth(120)
        self.to_edit.setStyleSheet(_DATE_STYLE)
        row1.addWidget(self.to_edit)

        row1.addWidget(self._label("Party Name"))
        self.party_name_edit = QLineEdit()
        self.party_name_edit.setStyleSheet(_EDIT_STYLE)
        self.party_name_edit.setPlaceholderText("partial search...")
        self.party_name_edit.setFixedWidth(160)
        self.party_name_edit.returnPressed.connect(self._on_generate)
        row1.addWidget(self.party_name_edit)

        row1.addStretch()

        search_btn = QPushButton("Search")
        search_btn.setStyleSheet(_BTN_PRIMARY)
        search_btn.clicked.connect(self._on_generate)
        row1.addWidget(search_btn)

        clear_btn = QPushButton("Clear")
        clear_btn.setStyleSheet(_BTN_SECONDARY)
        clear_btn.clicked.connect(self._on_clear)
        row1.addWidget(clear_btn)

        fv.addLayout(row1)
        root.addWidget(filters)

        # ── Table ────────────────────────────────────────────────
        self._table = QTableWidget()
        self._table.setColumnCount(7)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(True)

        hv = self._table.horizontalHeader()
        hv.setStretchLastSection(True)
        hv.setSectionResizeMode(0, QHeaderView.Stretch)
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
            ("parties", "Parties: 0"),
            ("operational", "Total: 0.00"),
            ("returns", "Returns: 0.00"),
            ("payments", "Payments: 0.00"),
            ("outstanding", "Outstanding: 0.00"),
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

        self._on_generate()

    # ------------------------------------------------------------------
    def _label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(_LABEL_STYLE)
        return lbl

    def _on_party_type_changed(self):
        self._on_generate()

    def _current_filters(self) -> dict:
        return {
            "from_date": self.from_edit.date().toString("yyyy-MM-dd"),
            "to_date": self.to_edit.date().toString("yyyy-MM-dd"),
            "party_name": self.party_name_edit.text().strip() or None,
        }

    def _render_customer(self, rows: list[dict]):
        headers = [
            "Customer Name", "City", "Contact No",
            "Total Sales", "Credit Notes", "Receipts",
            "Outstanding",
        ]
        self._table.setColumnCount(len(headers))
        self._table.setHorizontalHeaderLabels(headers)

        hv = self._table.horizontalHeader()
        hv.setSectionResizeMode(0, QHeaderView.Stretch)
        for c in range(1, len(headers)):
            hv.setSectionResizeMode(c, QHeaderView.ResizeToContents)

        self._table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            bal_sign = 1.0 if r["ledger_balance_type"] == "Debit" else -1.0
            outstanding = r["ledger_balance"] * bal_sign

            values = [
                r["customer_name"] or "",
                r["city"] or "",
                r["contact_no"] or "",
                f"{r['total_sales']:,.2f}",
                f"{r['total_credit_notes']:,.2f}",
                f"{r['total_receipts']:,.2f}",
                f"{outstanding:,.2f}",
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if col >= 3:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self._table.setItem(i, col, item)

        total_sales = sum(r["total_sales"] for r in rows)
        total_returns = sum(r["total_credit_notes"] for r in rows)
        total_receipts = sum(r["total_receipts"] for r in rows)
        total_outstanding = sum(
            r["ledger_balance"]
            * (1.0 if r["ledger_balance_type"] == "Debit" else -1.0)
            for r in rows
        )

        self._summary_labels["parties"].setText(f"Customers: {len(rows)}")
        self._summary_labels["operational"].setText(
            f"Sales: {total_sales:,.2f}"
        )
        self._summary_labels["returns"].setText(
            f"Returns: {total_returns:,.2f}"
        )
        self._summary_labels["payments"].setText(
            f"Receipts: {total_receipts:,.2f}"
        )
        self._summary_labels["outstanding"].setText(
            f"Outstanding: {total_outstanding:,.2f}"
        )

    def _render_supplier(self, rows: list[dict]):
        headers = [
            "Supplier Name", "City", "Contact No",
            "Total Purchases", "Debit Notes", "Payments",
            "Outstanding",
        ]
        self._table.setColumnCount(len(headers))
        self._table.setHorizontalHeaderLabels(headers)

        hv = self._table.horizontalHeader()
        hv.setSectionResizeMode(0, QHeaderView.Stretch)
        for c in range(1, len(headers)):
            hv.setSectionResizeMode(c, QHeaderView.ResizeToContents)

        self._table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            bal_sign = 1.0 if r["ledger_balance_type"] == "Credit" else -1.0
            outstanding = r["ledger_balance"] * bal_sign

            values = [
                r["supplier_name"] or "",
                r["city"] or "",
                r["contact_no"] or "",
                f"{r['total_purchases']:,.2f}",
                f"{r['total_debit_notes']:,.2f}",
                f"{r['total_payments']:,.2f}",
                f"{outstanding:,.2f}",
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if col >= 3:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self._table.setItem(i, col, item)

        total_purchases = sum(r["total_purchases"] for r in rows)
        total_returns = sum(r["total_debit_notes"] for r in rows)
        total_payments = sum(r["total_payments"] for r in rows)
        total_outstanding = sum(
            r["ledger_balance"]
            * (1.0 if r["ledger_balance_type"] == "Credit" else -1.0)
            for r in rows
        )

        self._summary_labels["parties"].setText(f"Suppliers: {len(rows)}")
        self._summary_labels["operational"].setText(
            f"Purchases: {total_purchases:,.2f}"
        )
        self._summary_labels["returns"].setText(
            f"Returns: {total_returns:,.2f}"
        )
        self._summary_labels["payments"].setText(
            f"Payments: {total_payments:,.2f}"
        )
        self._summary_labels["outstanding"].setText(
            f"Outstanding: {total_outstanding:,.2f}"
        )

    def _on_generate(self):
        try:
            filters = self._current_filters()
            party_type = self.party_type_combo.currentText()

            if party_type == "Customer":
                rows = PartyWiseReportDAO.get_customer_report(**filters)
                self._render_customer(rows)
            elif party_type == "Supplier":
                rows = PartyWiseReportDAO.get_supplier_report(**filters)
                self._render_supplier(rows)
            else:
                # All — show customers then suppliers with separator
                cust_rows = PartyWiseReportDAO.get_customer_report(
                    **filters
                )
                supp_rows = PartyWiseReportDAO.get_supplier_report(
                    **filters
                )

                if cust_rows:
                    self._render_customer(cust_rows)
                elif supp_rows:
                    self._render_supplier(supp_rows)
                else:
                    self._table.setColumnCount(7)
                    self._table.setHorizontalHeaderLabels([
                        "Party Name", "City", "Contact No",
                        "Total Sales/Purchases", "Returns",
                        "Receipts/Payments", "Outstanding",
                    ])
                    self._table.setRowCount(0)
                    self._summary_labels["parties"].setText("Parties: 0")
                    self._summary_labels["operational"].setText("Total: 0.00")
                    self._summary_labels["returns"].setText("Returns: 0.00")
                    self._summary_labels["payments"].setText(
                        "Payments: 0.00"
                    )
                    self._summary_labels["outstanding"].setText(
                        "Outstanding: 0.00"
                    )

        except Exception as e:
            QMessageBox.critical(
                self, "Error",
                f"Failed to generate Party Wise Report:\n{e}",
            )

    def _on_refresh(self):
        self._on_generate()

    def _on_clear(self):
        self.party_type_combo.setCurrentIndex(0)
        fy_start, fy_end = active_date_range()
        self.from_edit.setDate(QDate.fromString(fy_start, "yyyy-MM-dd"))
        self.to_edit.setDate(QDate.fromString(fy_end, "yyyy-MM-dd"))
        self.party_name_edit.clear()
        self._on_generate()
