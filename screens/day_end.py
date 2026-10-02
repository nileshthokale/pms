from __future__ import annotations

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDateEdit,
    QFileDialog,
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

from database import document_printing
from database.day_end_dao import DayEndDAO, DayEndError
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

_DATE_STYLE = (
    f"QDateEdit {{"
    f"  background-color: {_SURFACE}; color: {_TEXT};"
    f"  border: 1px solid {_BORDER}; border-radius: 2px;"
    f"  padding: 4px 6px; font-size: 12px; font-family: 'Segoe UI';"
    f"}}"
    f"QDateEdit::drop-down {{ border: none; }}"
)

_LABEL_STYLE = (
    f"color: {_TEXT}; font-size: 12px; background: transparent;"
    f"font-family: 'Segoe UI';"
)

_SECTION_ORDER = [
    ("Sales", "sales"),
    ("Purchases", "purchases"),
    ("Returns", "returns"),
    ("Receipts", "receipts"),
    ("Payments", "payments"),
    ("Cash", "cash"),
    ("Bank", "bank"),
    ("Stock Impact", "stock"),
    ("Overall Summary", "overall"),
    ("Reconciliation", "reconciliation"),
]


def _format_value(value) -> str:
    if isinstance(value, float):
        return f"{value:,.2f}"
    return str(value)


class DayEndPage(QWidget):
    """Day End report page (Sales → Day End) — read-only.

    Daily operational summary of the selected business date. This
    implementation performs NO end-of-day closing: it does not post
    accounting entries, lock the date, change stock, or alter ledger
    balances. Printing produces a "Day End" PDF and is also read-only.
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

        title = QLabel("Day End")
        title.setStyleSheet(
            f"color: {_TEXT}; font-size: 18px; font-weight: bold;"
            f"background: transparent; font-family: 'Segoe UI';"
        )
        hl.addWidget(title)
        hl.addStretch()

        hint = QLabel(
            "Read-only daily summary — no closing entries, no date locking"
        )
        hint.setStyleSheet(
            f"color: {_TEXT_DIM}; font-size: 11px; background: transparent;"
            f"font-family: 'Segoe UI'; margin-right: 10px;"
        )
        hl.addWidget(hint)

        print_btn = QPushButton("Print / PDF")
        print_btn.setStyleSheet(_BTN_SECONDARY)
        print_btn.clicked.connect(self._print)
        hl.addWidget(print_btn)

        refresh_btn = QPushButton("Generate / Refresh")
        refresh_btn.setStyleSheet(_BTN_PRIMARY)
        refresh_btn.clicked.connect(self._refresh)
        hl.addWidget(refresh_btn)
        root.addWidget(header)

        # ── Controls ─────────────────────────────────────────────
        controls = QWidget()
        controls.setStyleSheet(
            f"background-color: {_SURFACE}; border-bottom: 1px solid {_BORDER};"
        )
        cl = QHBoxLayout(controls)
        cl.setContentsMargins(16, 8, 16, 8)
        cl.setSpacing(8)

        date_lbl = QLabel("Business Date")
        date_lbl.setStyleSheet(_LABEL_STYLE)
        cl.addWidget(date_lbl)

        self._date = QDateEdit()
        self._date.setCalendarPopup(True)
        self._date.setDisplayFormat("yyyy-MM-dd")
        self._date.setFixedWidth(120)
        self._date.setStyleSheet(_DATE_STYLE)
        self._date.setDate(QDate.fromString(DayEndDAO.default_date(), "yyyy-MM-dd"))
        self._date.dateChanged.connect(self._refresh)
        cl.addWidget(self._date)

        generate_btn = QPushButton("Generate")
        generate_btn.setStyleSheet(_BTN_PRIMARY)
        generate_btn.clicked.connect(self._refresh)
        cl.addWidget(generate_btn)
        cl.addStretch()
        root.addWidget(controls)

        # ── Table ────────────────────────────────────────────────
        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["Section", "Metric", "Value"])
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(True)

        hv = self._table.horizontalHeader()
        hv.setStretchLastSection(True)
        hv.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hv.setSectionResizeMode(1, QHeaderView.Stretch)
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
        sl.setSpacing(20)

        self._summary = QLabel("")
        self._summary.setStyleSheet(
            f"color: {_TEXT}; font-size: 12px; font-weight: bold;"
            f"background: transparent; font-family: 'Segoe UI';"
        )
        sl.addWidget(self._summary)
        sl.addStretch()
        root.addWidget(summary)

        self._refresh()

    # ------------------------------------------------------------------
    def _day(self) -> str:
        return self._date.date().toString("yyyy-MM-dd")

    def _report(self) -> dict:
        return DayEndDAO.get_day_end_report(self._day())

    def _refresh(self):
        try:
            report = self._report()
        except DayEndError as exc:
            QMessageBox.warning(self, "Day End", str(exc))
            return

        rows: list[tuple[str, str, str]] = []
        for section_label, key in _SECTION_ORDER:
            data = report[key]
            for metric, value in data.items():
                rows.append(
                    (
                        section_label,
                        metric.replace("_", " ").title(),
                        _format_value(value),
                    )
                )

        self._table.setRowCount(len(rows))
        for index, (section, metric, value) in enumerate(rows):
            self._table.setItem(index, 0, QTableWidgetItem(section))
            self._table.setItem(index, 1, QTableWidgetItem(metric))
            value_item = QTableWidgetItem(value)
            value_item.setTextAlignment(
                Qt.AlignRight | Qt.AlignVCenter
            )
            self._table.setItem(index, 2, value_item)

        overall = report["overall"]
        empty = all(
            value == 0
            for key in ("sales", "purchases", "returns", "receipts", "payments")
            for value in report[key].values()
        )
        text = (
            "Read-only summary.  ·  "
            f"Business Date: {report['date']}  ·  "
            f"Sales: {overall['sales']:,.2f}  ·  "
            f"Purchases: {overall['purchases']:,.2f}  ·  "
            f"Receipts: {overall['customer_receipts']:,.2f}  ·  "
            f"Payments: {overall['supplier_payments']:,.2f}  ·  "
            f"Cash Movement: {overall['cash_movement']:,.2f}  ·  "
            f"Bank Movement: {overall['bank_movement']:,.2f}"
        )
        if empty:
            text += "  ·  No transactions found for the selected date."
        self._summary.setText(text)

    def _print(self):
        try:
            report = self._report()
        except DayEndError as exc:
            QMessageBox.warning(self, "Day End", str(exc))
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Save Day End PDF",
            f"day_end_{report['date']}.pdf", "PDF (*.pdf)",
        )
        if not path:
            return

        items: list[dict] = []
        for section_label, key in _SECTION_ORDER:
            for metric, value in report[key].items():
                items.append({
                    "item_name": (
                        f"{section_label} | "
                        f"{metric.replace('_', ' ').title()} | "
                        f"{_format_value(value)}"
                    )
                })

        record = {
            "voucher_no": report["date"],
            "voucher_date": report["date"],
        }
        try:
            output = document_printing.generate_document(
                "Day End", record, items, path
            )
        except document_printing.DocumentPrintError as exc:
            QMessageBox.warning(self, "Day End", str(exc))
            return
        QMessageBox.information(
            self, "PDF Saved", f"Day End saved to:\n{output}"
        )
