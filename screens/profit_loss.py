from __future__ import annotations

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDateEdit,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QMessageBox,
)

from database.profit_loss_dao import ProfitLossDAO
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

_BTN_PRIMARY = (
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

_FILTER_LABEL = (
    f"color: {_TEXT}; font-size: 12px; font-weight: bold;"
    f"background: transparent; font-family: 'Segoe UI';"
)

_SECTION_STYLE = (
    f"color: {_ACCENT}; font-size: 13px; font-weight: bold;"
    f"background: transparent; font-family: 'Segoe UI'; padding: 4px 0;"
)

_WARNING_STYLE = (
    f"color: #b26a00; font-size: 11px; font-style: italic;"
    f"background: transparent; font-family: 'Segoe UI'; padding: 2px 0;"
)

_SUMMARY_STYLE = (
    f"color: {_TEXT}; font-size: 12px; font-weight: bold;"
    f"background: transparent; font-family: 'Segoe UI';"
)

_PROFIT_STYLE = (
    f"color: #2e7d32; font-size: 13px; font-weight: bold;"
    f"background: transparent; font-family: 'Segoe UI';"
)

_LOSS_STYLE = (
    f"color: #c0392b; font-size: 13px; font-weight: bold;"
    f"background: transparent; font-family: 'Segoe UI';"
)

_ZERO_STYLE = (
    f"color: {_TEXT_DIM}; font-size: 13px; font-weight: bold;"
    f"background: transparent; font-family: 'Segoe UI';"
)


def _fmt(value: float) -> str:
    if value == 0:
        return ""
    return f"{value:,.2f}"


class ProfitLossPage(QWidget):
    """Profit & Loss report page (Account -> Profit & Loss).

    Reads the report from ProfitLossDAO, which uses only
    account_ledgers + ledger_transactions + account_groups.
    The table is read-only.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setStyleSheet(f"background-color: {_DARK_BG};")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        header = QWidget()
        header.setFixedHeight(56)
        header.setStyleSheet(
            f"background-color: {_SURFACE}; border-bottom: 1px solid {_BORDER};"
        )
        hl = QHBoxLayout(header)
        hl.setContentsMargins(16, 0, 16, 0)

        title = QLabel("Profit & Loss")
        title.setStyleSheet(
            f"color: {_TEXT}; font-size: 18px; font-weight: bold;"
            f"background: transparent; font-family: 'Segoe UI';"
        )
        hl.addWidget(title)
        hl.addStretch()
        root.addWidget(header)

        # Filter bar
        filter_bar = QWidget()
        fl = QHBoxLayout(filter_bar)
        fl.setContentsMargins(16, 8, 16, 8)
        fl.setSpacing(10)

        from_lbl = QLabel("From Date")
        from_lbl.setStyleSheet(_FILTER_LABEL)
        fl.addWidget(from_lbl)

        self.from_edit = QDateEdit()
        self.from_edit.setCalendarPopup(True)
        self.from_edit.setDisplayFormat("yyyy-MM-dd")
        fy_start, fy_end = active_date_range()
        self.from_edit.setDate(QDate.fromString(fy_start, "yyyy-MM-dd"))
        self.from_edit.setFixedHeight(30)
        self.from_edit.setStyleSheet(
            f"QDateEdit {{ background-color: {_SURFACE}; color: {_TEXT};"
            f"  border: 1px solid {_BORDER}; border-radius: 2px;"
            f"  padding: 0 8px; font-size: 12px; font-family: 'Segoe UI'; }}"
            f"QDateEdit::drop-down {{ border: none; }}"
        )
        fl.addWidget(self.from_edit)

        to_lbl = QLabel("To Date")
        to_lbl.setStyleSheet(_FILTER_LABEL)
        fl.addWidget(to_lbl)

        self.to_edit = QDateEdit()
        self.to_edit.setCalendarPopup(True)
        self.to_edit.setDisplayFormat("yyyy-MM-dd")
        self.to_edit.setDate(QDate.fromString(fy_end, "yyyy-MM-dd"))
        self.to_edit.setFixedHeight(30)
        self.to_edit.setStyleSheet(
            f"QDateEdit {{ background-color: {_SURFACE}; color: {_TEXT};"
            f"  border: 1px solid {_BORDER}; border-radius: 2px;"
            f"  padding: 0 8px; font-size: 12px; font-family: 'Segoe UI'; }}"
            f"QDateEdit::drop-down {{ border: none; }}"
        )
        fl.addWidget(self.to_edit)

        generate_btn = QPushButton("Generate")
        generate_btn.setStyleSheet(_BTN_PRIMARY)
        generate_btn.clicked.connect(self._on_generate)
        fl.addWidget(generate_btn)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.setStyleSheet(_BTN_SECONDARY)
        refresh_btn.clicked.connect(self._on_generate)
        fl.addWidget(refresh_btn)

        fl.addStretch()
        root.addWidget(filter_bar)

        # Table
        self._table = QTableWidget()
        self._table.setColumnCount(3)
        self._table.setHorizontalHeaderLabels([
            "Ledger", "Account Group", "Amount"
        ])
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(True)

        hv = self._table.horizontalHeader()
        hv.setStretchLastSection(True)
        hv.setSectionResizeMode(0, QHeaderView.Stretch)
        hv.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hv.setSectionResizeMode(2, QHeaderView.ResizeToContents)
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
            f"  selection-background-color: {_ACCENT};"
            f"  selection-color: white;"
            f"}}"
            f"QTableWidget::item {{ padding: 2px 5px; }}"
        )
        root.addWidget(self._table, 1)

        # Summary bar
        summary = QWidget()
        summary.setFixedHeight(44)
        summary.setStyleSheet(
            f"background-color: {_SURFACE}; border-top: 1px solid {_BORDER};"
        )
        sl = QHBoxLayout(summary)
        sl.setContentsMargins(16, 0, 16, 0)
        sl.setSpacing(24)

        self._total_income_lbl = QLabel("Total Income: 0.00")
        self._total_expense_lbl = QLabel("Total Expenses: 0.00")
        self._net_lbl = QLabel("Net: 0.00")

        for lbl in (self._total_income_lbl, self._total_expense_lbl):
            lbl.setStyleSheet(_SUMMARY_STYLE)
            sl.addWidget(lbl)
        sl.addStretch()

        self._net_lbl.setStyleSheet(_PROFIT_STYLE)
        sl.addWidget(self._net_lbl)
        root.addWidget(summary)

        # Warnings area
        self._warnings = QLabel("")
        self._warnings.setStyleSheet(_WARNING_STYLE)
        self._warnings.setWordWrap(True)
        self._warnings.setVisible(False)
        root.addWidget(self._warnings)

        # Initial generation
        self._on_generate()

    def _current_report(self) -> dict:
        from_date = self.from_edit.date().toString("yyyy-MM-dd")
        to_date = self.to_edit.date().toString("yyyy-MM-dd")
        return ProfitLossDAO.get_profit_loss(from_date, to_date)

    def _render(self, report: dict):
        income = report["income"]
        expenses = report["expenses"]
        unclassified = report["unclassified"]
        totals = report["totals"]

        # Build table: Income section header + rows, Expense section + rows
        all_rows = []

        # Income section
        if income:
            all_rows.append(("__SECTION__", "INCOME", "", ""))
            for r in income:
                all_rows.append((
                    r["ledger_name"],
                    r["account_group"],
                    _fmt(r["amount"]),
                ))
            all_rows.append(("__TOTAL__", "Total Income", _fmt(totals["total_income"])))
            all_rows.append(("__BLANK__", "", ""))

        # Expense section
        if expenses:
            all_rows.append(("__SECTION__", "EXPENSES", "", ""))
            for r in expenses:
                all_rows.append((
                    r["ledger_name"],
                    r["account_group"],
                    _fmt(r["amount"]),
                ))
            all_rows.append(("__TOTAL__", "Total Expenses", _fmt(totals["total_expenses"])))
            all_rows.append(("__BLANK__", "", ""))

        # Net result
        if income or expenses:
            all_rows.append(("__NET__", totals["net_label"], _fmt(totals["net_result"])))

        self._table.setRowCount(len(all_rows))
        for i, row_data in enumerate(all_rows):
            if row_data[0] == "__SECTION__":
                item = QTableWidgetItem(row_data[1])
                item.setFlags(Qt.ItemIsEnabled)
                font = item.font()
                font.setBold(True)
                item.setFont(font)
                item.setForeground(QBrush(QColor(_TEXT)))
                self._table.setItem(i, 0, item)
                self._table.setItem(i, 1, QTableWidgetItem(""))
                self._table.setItem(i, 2, QTableWidgetItem(""))
            elif row_data[0] == "__TOTAL__":
                item = QTableWidgetItem(row_data[1])
                item.setFlags(Qt.ItemIsEnabled)
                font = item.font()
                font.setBold(True)
                item.setFont(font)
                self._table.setItem(i, 0, item)
                self._table.setItem(i, 1, QTableWidgetItem(""))
                amt_item = QTableWidgetItem(row_data[2])
                amt_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                font2 = amt_item.font()
                font2.setBold(True)
                amt_item.setFont(font2)
                self._table.setItem(i, 2, amt_item)
            elif row_data[0] == "__NET__":
                item = QTableWidgetItem(row_data[1])
                item.setFlags(Qt.ItemIsEnabled)
                font = item.font()
                font.setBold(True)
                font.setPointSize(font.pointSize() + 1)
                item.setFont(font)
                self._table.setItem(i, 0, item)
                self._table.setItem(i, 1, QTableWidgetItem(""))
                amt_item = QTableWidgetItem(row_data[2])
                amt_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                font2 = amt_item.font()
                font2.setBold(True)
                font2.setPointSize(font2.pointSize() + 1)
                amt_item.setFont(font2)
                self._table.setItem(i, 2, amt_item)
            elif row_data[0] == "__BLANK__":
                self._table.setItem(i, 0, QTableWidgetItem(""))
                self._table.setItem(i, 1, QTableWidgetItem(""))
                self._table.setItem(i, 2, QTableWidgetItem(""))
            else:
                self._table.setItem(i, 0, QTableWidgetItem(row_data[0]))
                self._table.setItem(i, 1, QTableWidgetItem(row_data[1]))
                amt_item = QTableWidgetItem(row_data[2])
                amt_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self._table.setItem(i, 2, amt_item)

        # Summary
        self._total_income_lbl.setText(
            f"Total Income: {totals['total_income']:,.2f}"
        )
        self._total_expense_lbl.setText(
            f"Total Expenses: {totals['total_expenses']:,.2f}"
        )
        net = totals["net_result"]
        self._net_lbl.setText(
            f"{totals['net_label']}: {net:,.2f}"
        )
        if net > 0.005:
            self._net_lbl.setStyleSheet(_PROFIT_STYLE)
        elif net < -0.005:
            self._net_lbl.setStyleSheet(_LOSS_STYLE)
        else:
            self._net_lbl.setStyleSheet(_ZERO_STYLE)

        # Warnings
        warnings = []
        if totals["has_unclassified"]:
            warnings.append(
                "Unclassified accounts detected - not included in totals."
            )
        if totals["has_cogs_limitation"]:
            warnings.append(
                "Inventory/COGS not calculated (periodic inventory). "
                "Gross profit = Income - Expenses (not Sales - COGS)."
            )
        if totals["has_gst_limitation"]:
            warnings.append(
                "GST not separately accounted (gross posting)."
            )
        if warnings:
            self._warnings.setText("  |  ".join(warnings))
            self._warnings.setVisible(True)
        else:
            self._warnings.setVisible(False)

    def _on_generate(self):
        try:
            self._render(self._current_report())
        except Exception as e:
            QMessageBox.critical(
                self, "Error",
                f"Failed to generate Profit & Loss:\n{e}"
            )
