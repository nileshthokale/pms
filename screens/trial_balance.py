from __future__ import annotations

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDateEdit,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from database.trial_balance_dao import TrialBalanceDAO
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


def _fmt(value: float) -> str:
    """Readable currency formatting; zero renders as blank (accounting convention)."""
    if value == 0:
        return ""
    return f"{value:,.2f}"


class TrialBalancePage(QWidget):
    """Trial Balance report page (Account → Trial Balance).

    Reads the report from TrialBalanceDAO, which uses only
    account_ledgers + ledger_transactions (the posted accounting
    source). The table is read-only; export is a future task.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setStyleSheet(f"background-color: {_DARK_BG};")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header ───────────────────────────────────────────────
        header = QWidget()
        header.setFixedHeight(56)
        header.setStyleSheet(
            f"background-color: {_SURFACE}; border-bottom: 1px solid {_BORDER};"
        )
        hl = QHBoxLayout(header)
        hl.setContentsMargins(16, 0, 16, 0)

        title = QLabel("Trial Balance")
        title.setStyleSheet(
            f"color: {_TEXT}; font-size: 18px; font-weight: bold;"
            f"background: transparent; font-family: 'Segoe UI';"
        )
        hl.addWidget(title)
        hl.addStretch()
        root.addWidget(header)

        # ── Filter bar ───────────────────────────────────────────
        filter_bar = QWidget()
        fl = QHBoxLayout(filter_bar)
        fl.setContentsMargins(16, 8, 16, 8)
        fl.setSpacing(10)

        as_of_lbl = QLabel("As of Date")
        as_of_lbl.setStyleSheet(_FILTER_LABEL)
        fl.addWidget(as_of_lbl)

        self.as_of_edit = QDateEdit()
        self.as_of_edit.setCalendarPopup(True)
        self.as_of_edit.setDisplayFormat("yyyy-MM-dd")
        self.as_of_edit.setDate(QDate.fromString(active_date_range()[1], "yyyy-MM-dd"))
        self.as_of_edit.setFixedHeight(30)
        self.as_of_edit.setStyleSheet(
            f"QDateEdit {{ background-color: {_SURFACE}; color: {_TEXT};"
            f"  border: 1px solid {_BORDER}; border-radius: 2px;"
            f"  padding: 0 8px; font-size: 12px; font-family: 'Segoe UI'; }}"
            f"QDateEdit::drop-down {{ border: none; }}"
        )
        fl.addWidget(self.as_of_edit)

        self.zero_check = QCheckBox("Show Zero Balance")
        self.zero_check.setChecked(True)
        self.zero_check.setStyleSheet(
            f"QCheckBox {{ color: {_TEXT}; font-size: 12px;"
            f"  font-family: 'Segoe UI'; background: transparent; }}"
            f"QCheckBox::indicator {{ width: 16px; height: 16px;"
            f"  border: 1px solid {_BORDER}; border-radius: 3px;"
            f"  background-color: {_SURFACE}; }}"
        )
        fl.addWidget(self.zero_check)

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

        # ── Table ────────────────────────────────────────────────
        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels([
            "Ledger Name", "Account Group", "Debit", "Credit"
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
        hv.setSectionResizeMode(3, QHeaderView.ResizeToContents)
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

        # ── Summary bar ──────────────────────────────────────────
        summary = QWidget()
        summary.setFixedHeight(44)
        summary.setStyleSheet(
            f"background-color: {_SURFACE}; border-top: 1px solid {_BORDER};"
        )
        sl = QHBoxLayout(summary)
        sl.setContentsMargins(16, 0, 16, 0)
        sl.setSpacing(24)

        self._total_debit_lbl = QLabel("Total Debit: 0.00")
        self._total_credit_lbl = QLabel("Total Credit: 0.00")
        self._difference_lbl = QLabel("Difference: 0.00")
        self._status_lbl = QLabel("Status: BALANCED")

        summary_style = (
            f"color: {_TEXT}; font-size: 12px; font-weight: bold;"
            f"background: transparent; font-family: 'Segoe UI';"
        )
        dim_style = (
            f"color: {_TEXT_DIM}; font-size: 12px;"
            f"background: transparent; font-family: 'Segoe UI';"
        )
        for lbl, style in (
            (self._total_debit_lbl, summary_style),
            (self._total_credit_lbl, summary_style),
            (self._difference_lbl, dim_style),
        ):
            lbl.setStyleSheet(style)
            sl.addWidget(lbl)
        sl.addStretch()

        self._status_lbl.setStyleSheet(summary_style)
        sl.addWidget(self._status_lbl)
        root.addWidget(summary)

        # Initial generation with defaults (today, show zero balances)
        self._on_generate()

    # ------------------------------------------------------------------
    # Report generation
    # ------------------------------------------------------------------
    def _current_report(self) -> dict:
        as_of = self.as_of_edit.date().toString("yyyy-MM-dd")
        return TrialBalanceDAO.get_trial_balance_filtered(
            as_of_date=as_of, include_zero=self.zero_check.isChecked()
        )

    def _render(self, report: dict):
        rows = report["rows"]
        self._table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            name_item = QTableWidgetItem(r["ledger_name"])
            if r["system_role"]:
                name_item.setToolTip(
                    f"System account role: {r['system_role']}"
                )
            self._table.setItem(i, 0, name_item)
            self._table.setItem(i, 1, QTableWidgetItem(r["account_group"]))

            debit_item = QTableWidgetItem(_fmt(r["debit"]))
            debit_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._table.setItem(i, 2, debit_item)

            credit_item = QTableWidgetItem(_fmt(r["credit"]))
            credit_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._table.setItem(i, 3, credit_item)

        totals = report["totals"]
        self._total_debit_lbl.setText(
            f"Total Debit: {totals['total_debit']:,.2f}"
        )
        self._total_credit_lbl.setText(
            f"Total Credit: {totals['total_credit']:,.2f}"
        )
        self._difference_lbl.setText(
            f"Difference: {totals['difference']:,.2f}"
        )
        if totals["balanced"]:
            self._status_lbl.setText("Status: BALANCED")
            self._status_lbl.setStyleSheet(
                f"color: #2e7d32; font-size: 12px; font-weight: bold;"
                f"background: transparent; font-family: 'Segoe UI';"
            )
        else:
            self._status_lbl.setText(
                f"Status: UNBALANCED (by {totals['difference']:,.2f})"
            )
            self._status_lbl.setStyleSheet(
                f"color: #c0392b; font-size: 12px; font-weight: bold;"
                f"background: transparent; font-family: 'Segoe UI';"
            )

    def _on_generate(self):
        try:
            self._render(self._current_report())
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Error", f"Failed to generate Trial Balance:\n{e}")
