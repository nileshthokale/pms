from __future__ import annotations

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDateEdit,
    QHBoxLayout,
    QHeaderView,
    QLabel,
        QPushButton,
        QScrollArea,
        QTableWidget,
        QTableWidgetItem,
        QVBoxLayout,
        QWidget,
)

from ui.theme import palette
from database.financial_year import active_date_range

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

_SECTION_HEADER = (
    f"color: {_ACCENT}; font-size: 14px; font-weight: bold;"
    f"background: transparent; font-family: 'Segoe UI';"
    f"padding: 8px 0 4px 0;"
)

_TOTAL_STYLE = (
    f"color: {_TEXT}; font-size: 12px; font-weight: bold;"
    f"background: transparent; font-family: 'Segoe UI';"
    f"padding: 4px 0;"
)


def _fmt(value: float) -> str:
    """Readable currency formatting."""
    if value == 0:
        return ""
    return f"{value:,.2f}"


class BalanceSheetPage(QWidget):
    """Balance Sheet report page (Account → Balance Sheet).

    Reads from BalanceSheetDAO, which uses only
    account_ledgers + ledger_transactions + account_groups.
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

        title = QLabel("Balance Sheet")
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

        # ── Scrollable content area ──────────────────────────────
        from PySide6.QtWidgets import QScrollArea
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            f"QScrollArea {{ border: none; background: transparent; }}"
        )
        content = QWidget()
        content.setStyleSheet("background: transparent;")
        self._content_layout = QVBoxLayout(content)
        self._content_layout.setContentsMargins(16, 0, 16, 0)
        self._content_layout.setSpacing(0)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        # ── Summary bar ──────────────────────────────────────────
        summary = QWidget()
        summary.setFixedHeight(44)
        summary.setStyleSheet(
            f"background-color: {_SURFACE}; border-top: 1px solid {_BORDER};"
        )
        sl = QHBoxLayout(summary)
        sl.setContentsMargins(16, 0, 16, 0)
        sl.setSpacing(24)

        self._total_assets_lbl = QLabel("Total Assets: 0.00")
        self._total_liabilities_lbl = QLabel("Total Liabilities: 0.00")
        self._total_equity_lbl = QLabel("Total Equity: 0.00")
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
            (self._total_assets_lbl, summary_style),
            (self._total_liabilities_lbl, summary_style),
            (self._total_equity_lbl, summary_style),
            (self._difference_lbl, dim_style),
        ):
            lbl.setStyleSheet(style)
            sl.addWidget(lbl)
        sl.addStretch()

        self._status_lbl.setStyleSheet(summary_style)
        sl.addWidget(self._status_lbl)
        root.addWidget(summary)

        # Initial generation with defaults
        self._on_generate()

    # ------------------------------------------------------------------
    # Report generation
    # ------------------------------------------------------------------
    def _current_report(self) -> dict:
        from database.balance_sheet_dao import BalanceSheetDAO

        as_of = self.as_of_edit.date().toString("yyyy-MM-dd")
        return BalanceSheetDAO.get_balance_sheet(as_of_date=as_of)

    def _clear_content(self):
        while self._content_layout.count():
            child = self._content_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

    def _add_section(
        self, title: str, rows: list[dict], total: float, color: str = _TEXT
    ):
        """Add a section (header, table, total) to the content area."""
        # Section header
        lbl = QLabel(title)
        lbl.setStyleSheet(
            f"color: {color}; font-size: 14px; font-weight: bold;"
            f"background: transparent; font-family: 'Segoe UI';"
            f"padding: 10px 0 4px 0;"
        )
        self._content_layout.addWidget(lbl)

        if not rows:
            empty = QLabel("  No ledgers")
            empty.setStyleSheet(
                f"color: {_TEXT_DIM}; font-size: 11px;"
                f"background: transparent; font-family: 'Segoe UI';"
                f"padding: 2px 0 2px 12px;"
            )
            self._content_layout.addWidget(empty)
        else:
            # Table for the section
            table = QTableWidget()
            table.setColumnCount(3)
            table.setHorizontalHeaderLabels([
                "Ledger", "Account Group", "Amount"
            ])
            table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            table.setSelectionBehavior(QAbstractItemView.SelectRows)
            table.setSelectionMode(QAbstractItemView.SingleSelection)
            table.verticalHeader().setVisible(False)
            table.setShowGrid(True)
            table.setAlternatingRowColors(True)
            table.setFixedHeight(
                30 + len(rows) * 28 + 4
            )

            hv = table.horizontalHeader()
            hv.setStretchLastSection(True)
            hv.setSectionResizeMode(0, QHeaderView.Stretch)
            hv.setSectionResizeMode(1, QHeaderView.ResizeToContents)
            hv.setSectionResizeMode(2, QHeaderView.ResizeToContents)
            hv.setStyleSheet(
                f"QHeaderView::section {{"
                f"  background-color: {_SURFACE}; color: {_TEXT};"
                f"  border: none; border-bottom: 1px solid {_BORDER};"
                f"  padding: 2px 5px; font-weight: bold; font-size: 12px;"
                f"  font-family: 'Segoe UI';"
                f"}}"
            )
            table.setStyleSheet(
                f"QTableWidget {{"
                f"  background-color: {_DARK_BG}; color: {_TEXT};"
                f"  border: 1px solid {_BORDER}; gridline-color: {_BORDER};"
                f"  font-size: 13px; font-family: 'Segoe UI';"
                f"  selection-background-color: {_ACCENT};"
                f"  selection-color: white;"
                f"}}"
                f"QTableWidget::item {{ padding: 2px; }}"
                f"QTableWidget::item:alternate {{ background-color: {_SURFACE}; }}"
            )

            table.setRowCount(len(rows))
            for i, r in enumerate(rows):
                table.setItem(i, 0, QTableWidgetItem(r["ledger_name"]))
                table.setItem(i, 1, QTableWidgetItem(r["account_group"]))
                amt_item = QTableWidgetItem(_fmt(r["amount"]))
                amt_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                table.setItem(i, 2, amt_item)

            self._content_layout.addWidget(table)

        # Total row
        total_lbl = QLabel(f"  Total {title}: {_fmt(total)}")
        total_lbl.setStyleSheet(
            f"color: {_TEXT}; font-size: 12px; font-weight: bold;"
            f"background: transparent; font-family: 'Segoe UI';"
            f"padding: 4px 0 6px 0;"
        )
        self._content_layout.addWidget(total_lbl)

    def _render(self, report: dict):
        self._clear_content()

        # Assets section
        self._add_section(
            "ASSETS",
            report["assets"],
            report["totals"]["total_assets"],
            color="#2e7d32",
        )

        # Liabilities section
        self._add_section(
            "LIABILITIES",
            report["liabilities"],
            report["totals"]["total_liabilities"],
            color="#c0392b",
        )

        # Equity section
        self._add_section(
            "EQUITY / CAPITAL",
            report["equity"],
            report["totals"]["total_equity"],
            color="#2196f3",
        )

        # Unclassified section
        if report["unclassified"]:
            self._add_section(
                "UNCLASSIFIED ACCOUNTS",
                report["unclassified"],
                0.0,
                color="#b26a00",
            )

        # Summary totals
        totals = report["totals"]
        self._total_assets_lbl.setText(
            f"Total Assets: {_fmt(totals['total_assets'])}"
        )
        self._total_liabilities_lbl.setText(
            f"Total Liabilities: {_fmt(totals['total_liabilities'])}"
        )
        self._total_equity_lbl.setText(
            f"Total Equity: {_fmt(totals['total_equity'])}"
        )
        self._difference_lbl.setText(
            f"Difference: {_fmt(totals['difference'])}"
        )
        status = totals["status"]
        if status == "BALANCED":
            self._status_lbl.setText("Status: BALANCED")
            self._status_lbl.setStyleSheet(
                f"color: #2e7d32; font-size: 12px; font-weight: bold;"
                f"background: transparent; font-family: 'Segoe UI';"
            )
        elif status == "EQUITY TREATMENT REQUIRED":
            self._status_lbl.setText("Status: EQUITY TREATMENT REQUIRED")
            self._status_lbl.setStyleSheet(
                f"color: #b26a00; font-size: 12px; font-weight: bold;"
                f"background: transparent; font-family: 'Segoe UI';"
            )
        else:
            self._status_lbl.setText(
                f"Status: UNBALANCED (by {_fmt(totals['difference'])})"
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
            QMessageBox.critical(
                self, "Error",
                f"Failed to generate Balance Sheet:\n{e}",
            )
