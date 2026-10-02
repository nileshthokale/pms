from __future__ import annotations

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QDateEdit, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from database.cash_book_dao import CashBookDAO, CashBookError
from database import document_printing
from ui import components as ui


class CashBookPage(QWidget):
    """Read-only Cash Book sourced from the CASH system ledger."""

    def __init__(self, parent=None):
        super().__init__(parent)
        colors = ui.palette()
        self.setStyleSheet(f"background-color: {colors['bg']};")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(ui.PageHeader("Account / Cash Book"))

        filters = ui.FilterBar()
        self._from = ui.style_date(QDateEdit())
        self._from.setCalendarPopup(True)
        filters.add_field("From Date", self._from)
        self._to = ui.style_date(QDateEdit())
        self._to.setCalendarPopup(True)
        filters.add_field("To Date", self._to)
        refresh = ui.ActionButton("Refresh", "primary", height=24)
        refresh.clicked.connect(self._refresh)
        filters.add_widget(refresh)
        print_button = ui.ActionButton("Print / PDF", "secondary", height=24)
        print_button.clicked.connect(self._print)
        filters.add_widget(print_button)
        filters.add_stretch()
        root.addWidget(filters)

        self._summary = QLabel()
        self._summary.setWordWrap(True)
        self._summary.setStyleSheet(ui.label_style(size=9))
        summary_bar = QWidget()
        summary_bar.setStyleSheet(
            f"background-color: {colors['surface_alt']};"
            f"border-bottom: 1px solid {colors['border']};"
        )
        sl = QVBoxLayout(summary_bar)
        sl.setContentsMargins(10, 4, 10, 4)
        sl.addWidget(self._summary)
        root.addWidget(summary_bar)

        self._table = ui.style_data_table(
            QTableWidget(0, 7), stretch_columns=(3,)
        )
        self._table.setHorizontalHeaderLabels([
            "Date", "Reference", "Reference Type", "Particulars",
            "Debit", "Credit", "Running Balance",
        ])
        root.addWidget(self._table, 1)

        self._set_default_dates()
        self._refresh()

    def _set_default_dates(self):
        options = CashBookDAO.get_filter_options()
        self._from.setDate(QDate.fromString(options["from_date"], "yyyy-MM-dd")); self._to.setDate(QDate.fromString(options["to_date"], "yyyy-MM-dd"))

    def _dates(self):
        return self._from.date().toString("yyyy-MM-dd"), self._to.date().toString("yyyy-MM-dd")

    def _refresh(self):
        try:
            report = CashBookDAO.get_cash_book(*self._dates())
        except CashBookError as exc:
            QMessageBox.warning(self, "Cash Book", str(exc)); return
        summary = report["summary"]
        self._summary.setText(f"Opening Balance: {report['opening_balance']:.2f} | Debit: {summary['total_debit']:.2f} | Credit: {summary['total_credit']:.2f} | Net Movement: {summary['net_movement']:.2f} | Closing Balance: {summary['closing_balance']:.2f}")
        self._table.setRowCount(len(report["rows"]))
        for index, row in enumerate(report["rows"]):
            values = (row["transaction_date"], row["voucher_no"], row["reference_type"], row["description"], f"{row['debit'] or 0:.2f}", f"{row['credit'] or 0:.2f}", f"{row['balance']:.2f}")
            for column, value in enumerate(values): self._table.setItem(index, column, QTableWidgetItem(str(value)))
        if not report["rows"] and report["ledger"]:
            self._summary.setText(self._summary.text() + " | No cash transactions found for the selected period.")
        elif not report["ledger"]:
            self._summary.setText("No CASH system ledger configured. No cash transactions found for the selected period.")

    def _print(self):
        try: report = CashBookDAO.get_cash_book(*self._dates())
        except CashBookError as exc: QMessageBox.warning(self, "Cash Book", str(exc)); return
        lines = ["Cash Book", f"From: {self._dates()[0]}  To: {self._dates()[1]}", f"Opening Balance: {report['opening_balance']:.2f}", "Date | Reference | Particulars | Debit | Credit | Balance"]
        for row in report["rows"]: lines.append(" | ".join((row["transaction_date"], row["voucher_no"], row["description"], f"{row['debit'] or 0:.2f}", f"{row['credit'] or 0:.2f}", f"{row['balance']:.2f}")))
        summary = report["summary"]; lines.append(f"Closing Balance: {summary['closing_balance']:.2f}")
        path, _ = QFileDialog.getSaveFileName(self, "Save Cash Book PDF", "cash_book.pdf", "PDF (*.pdf)")
        if not path: return
        try:
            output = document_printing.generate_document("Cash Book", {"voucher_no": f"{self._dates()[0]} to {self._dates()[1]}"}, [{"item_name": line} for line in lines], path)
            QMessageBox.information(self, "PDF Saved", f"Cash Book saved to:\n{output}")
        except document_printing.DocumentPrintError as exc: QMessageBox.warning(self, "Cash Book", str(exc))
