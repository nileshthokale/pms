from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
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

from database import document_printing
from database.purchase_report_dao import PurchaseReportDAO
from ui.fy_view import view_year_bounds
from ui.searchable_filter import SearchableFilterEdit
from ui.theme import palette

_p = palette()
_DARK_BG = _p["bg"]
_SURFACE = _p["surface"]
_BORDER = _p["border"]
_ACCENT = _p["accent"]
_ACCENT_HOVER = _p["accent_hover"]
_TEXT = _p["text"]
_TEXT_DIM = _p["text_dim"]

_EDIT_STYLE = (
    f"QLineEdit {{"
    f"  background-color: {_SURFACE}; color: {_TEXT};"
    f"  border: 1px solid {_BORDER}; border-radius: 2px;"
    f"  padding: 5px 8px; font-size: 12px; font-family: 'Segoe UI';"
    f"}}"
    f"QLineEdit:focus {{ border: 1px solid {_ACCENT}; }}"
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


def _edit_style(p: dict) -> str:
    return (
        "QLineEdit {"
        f" background-color: {p['surface']}; color: {p['text']};"
        f" border: 1px solid {p['border']}; border-radius: 2px;"
        " padding: 5px 8px; font-size: 12px; font-family: 'Segoe UI';"
        "} QLineEdit:focus {"
        f" border: 1px solid {p['accent']}; }}"
    )


def _button_style(p: dict, primary: bool = False) -> str:
    if primary:
        return (
            f"QPushButton {{ background-color: {p['accent']}; color: white;"
            " border: none; border-radius: 2px; padding: 7px 18px;"
            " font-weight: bold; font-size: 12px; font-family: 'Segoe UI'; }"
            f"QPushButton:hover {{ background-color: {p['accent_hover']}; }}"
        )
    return (
        f"QPushButton {{ background-color: {p['border']}; color: {p['text']};"
        " border: none; border-radius: 2px; padding: 7px 18px;"
        " font-size: 12px; font-family: 'Segoe UI'; }"
        f"QPushButton:hover {{ background-color: {p['text_dim']}; }}"
    )

class PurchaseReportPage(QWidget):
    """Purchase Report page (Reports → Purchase Report) — read-only.

    Reports the application's purchase source documents
    (purchase_invoices + purchase_invoice_items). Financial reports
    (Trial Balance, P&L, Balance Sheet) are based on ledger postings
    instead.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._history_financial_year: dict | None = None
        self._last_report: dict | None = None
        self.setStyleSheet(f"background-color: {_DARK_BG};")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header ───────────────────────────────────────────────
        header = QWidget()
        self._header = header
        header.setFixedHeight(52)
        header.setStyleSheet(
            f"background-color: {_SURFACE}; border-bottom: 1px solid {_BORDER};"
        )
        hl = QHBoxLayout(header)
        hl.setContentsMargins(16, 0, 16, 0)

        title = QLabel("Purchase Report")
        title.setStyleSheet(
            f"color: {_TEXT}; font-size: 18px; font-weight: bold;"
            f"background: transparent; font-family: 'Segoe UI';"
        )
        hl.addWidget(title)
        hl.addStretch()

        hint = QLabel("Based on purchase vouchers — financial reports use ledger postings")
        hint.setStyleSheet(
            f"color: {_TEXT_DIM}; font-size: 11px; background: transparent;"
            f"font-family: 'Segoe UI'; margin-right: 10px;"
        )
        hl.addWidget(hint)

        root.addWidget(header)

        # ── Filter area ──────────────────────────────────────────
        filters = QWidget()
        self._filters = filters
        filters.setStyleSheet(
            f"background-color: {_SURFACE}; border-bottom: 1px solid {_BORDER};"
        )
        fv = QVBoxLayout(filters)
        fv.setContentsMargins(16, 6, 16, 6)
        fv.setSpacing(6)

        # The navbar's view-only financial year is the sole period selector.
        # Nothing in this toolbar can remove its inclusive voucher-date range.
        row1 = QHBoxLayout()
        row1.setSpacing(5)
        row1.addWidget(self._label("Supplier"))
        self.supplier_edit = SearchableFilterEdit("All suppliers")
        self.supplier_edit.setFixedWidth(125)
        row1.addWidget(self.supplier_edit)

        row1.addWidget(self._label("Company"))
        self.company_edit = SearchableFilterEdit("All companies")
        self.company_edit.setFixedWidth(115)
        row1.addWidget(self.company_edit)

        row1.addWidget(self._label("Item"))
        self.item_edit = SearchableFilterEdit("All items")
        self.item_edit.setFixedWidth(130)
        row1.addWidget(self.item_edit)

        row1.addWidget(self._label("Invoice"))
        self.invoice_edit = QLineEdit()
        self.invoice_edit.setStyleSheet(_EDIT_STYLE)
        self.invoice_edit.setPlaceholderText("e.g. INV-001")
        self.invoice_edit.setFixedWidth(88)
        self.invoice_edit.returnPressed.connect(self._on_generate)
        row1.addWidget(self.invoice_edit)

        row1.addWidget(self._label("Voucher"))
        self.voucher_edit = QLineEdit()
        self.voucher_edit.setStyleSheet(_EDIT_STYLE)
        self.voucher_edit.setPlaceholderText("e.g. PV-0001")
        self.voucher_edit.setFixedWidth(88)
        self.voucher_edit.returnPressed.connect(self._on_generate)
        row1.addWidget(self.voucher_edit)

        row1.addWidget(self._label("Batch"))
        self.batch_edit = QLineEdit()
        self.batch_edit.setStyleSheet(_EDIT_STYLE)
        self.batch_edit.setPlaceholderText("batch")
        self.batch_edit.setFixedWidth(75)
        self.batch_edit.returnPressed.connect(self._on_generate)
        row1.addWidget(self.batch_edit)

        row1.addStretch()

        search_btn = QPushButton("Search")
        search_btn.setStyleSheet(_BTN_PRIMARY)
        search_btn.clicked.connect(self._on_generate)
        row1.addWidget(search_btn)

        clear_btn = QPushButton("Clear")
        clear_btn.setStyleSheet(_BTN_SECONDARY)
        clear_btn.clicked.connect(self._on_clear)
        row1.addWidget(clear_btn)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.setStyleSheet(_BTN_SECONDARY)
        refresh_btn.clicked.connect(self._on_refresh)
        row1.addWidget(refresh_btn)

        print_btn = QPushButton("Print")
        print_btn.setStyleSheet(_BTN_SECONDARY)
        print_btn.clicked.connect(self._on_print)
        row1.addWidget(print_btn)
        fv.addLayout(row1)

        root.addWidget(filters)

        # ── Table ────────────────────────────────────────────────
        self._columns = [
            "Voucher No", "Voucher Date", "Invoice No", "Invoice Date",
            "Supplier", "Item Name", "Company", "Pack", "Batch No",
            "Expiry", "Pay Qty", "Free Qty", "Rate", "MRP", "Disc",
            "GST %", "GST Amt", "Amount", "Purc Rate", "Net Rate",
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
        hv.setSectionResizeMode(5, QHeaderView.Stretch)  # item name
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
        self._summary = summary
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
            ("pay_qty", "Pay Qty: 0"),
            ("free_qty", "Free: 0"),
            ("gross", "Gross: 0.00"),
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
        options = PurchaseReportDAO.get_filter_options()
        for edit, rows, id_key, name_key in (
            (self.supplier_edit, options["suppliers"], "id", "supplier_name"),
            (self.company_edit, options["companies"], "id", "company_name"),
            (self.item_edit, options["items"], "id", "item_name"),
        ):
            edit.set_options(rows, id_key, name_key)

    def _current_filters(self) -> dict:
        from_date, to_date = view_year_bounds(self._history_financial_year)
        return {
            "from_date": from_date,
            "to_date": to_date,
            "supplier_id": self.supplier_edit.selected_id,
            "item_id": self.item_edit.selected_id,
            "company_id": self.company_edit.selected_id,
            "invoice_no": self.invoice_edit.text().strip() or None,
            "voucher_no": self.voucher_edit.text().strip() or None,
            "batch_no": self.batch_edit.text().strip() or None,
        }

    def set_history_financial_year(self, year: dict | None):
        """Apply the navbar's view-only financial-year selection."""
        self._history_financial_year = dict(year) if year else None
        self._on_generate()

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
                r["pack_size"] or "",
                r["batch_no"] or "",
                r["expiry"] or "",
                f"{r['pay_qty']:g}",
                f"{r['free_qty']:g}",
                f"{r['rate']:,.2f}",
                f"{r['mrp']:,.2f}",
                f"{r['discount']:,.2f}",
                f"{r['gst_percent']:g}",
                f"{r['gst_amount']:,.2f}",
                f"{r['amount']:,.2f}",
                f"{r['purchase_rate']:,.2f}",
                f"{r['net_rate']:,.2f}",
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if col >= 10:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self._table.setItem(i, col, item)

        s = report["summary"]
        self._summary_labels["bills"].setText(f"Bills: {s['total_bills']}")
        self._summary_labels["pay_qty"].setText(
            f"Pay Qty: {s['total_pay_qty']:g}"
        )
        self._summary_labels["free_qty"].setText(
            f"Free: {s['total_free_qty']:g}"
        )
        self._summary_labels["gross"].setText(f"Gross: {s['total_gross']:,.2f}")
        self._summary_labels["gst"].setText(f"GST: {s['total_gst']:,.2f}")
        self._summary_labels["discount"].setText(
            f"Discount: {s['total_discount']:,.2f}"
        )
        self._summary_labels["net"].setText(f"Net: {s['total_net']:,.2f}")

    def _on_generate(self):
        try:
            self._last_report = PurchaseReportDAO.get_purchase_report(**self._current_filters())
            self._render(self._last_report)
        except Exception as e:
            QMessageBox.critical(
                self, "Error", f"Failed to generate Purchase Report:\n{e}"
            )

    def _on_refresh(self):
        self._load_filter_options()
        self._on_generate()

    def _on_clear(self):
        self.supplier_edit.clear_filter()
        self.company_edit.clear_filter()
        self.item_edit.clear_filter()
        self.invoice_edit.clear()
        self.voucher_edit.clear()
        self.batch_edit.clear()
        self._on_generate()

    def _financial_year_name(self) -> str:
        year = self._history_financial_year or {}
        filters = self._current_filters()
        return str(year.get("name") or "FY " + "–".join(
            (filters["from_date"][:4], filters["to_date"][:4])
        ))

    def _filter_summary(self) -> str:
        parts = [f"Financial year: {self._financial_year_name()}"]
        for label, edit in (("Supplier", self.supplier_edit),
                            ("Company", self.company_edit), ("Item", self.item_edit)):
            if edit.selected_id is not None:
                parts.append(f"{label}: {edit.text()}")
        for label, edit in (("Invoice", self.invoice_edit), ("Voucher", self.voucher_edit),
                            ("Batch", self.batch_edit)):
            if edit.text().strip():
                parts.append(f"{label}: {edit.text().strip()}")
        return " | ".join(parts)

    def _on_print(self):
        try:
            report = PurchaseReportDAO.get_purchase_report(**self._current_filters())
        except Exception as exc:
            QMessageBox.warning(self, "Purchase Report", f"Could not prepare report: {exc}")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Purchase Report PDF", "purchase_report.pdf", "PDF (*.pdf)"
        )
        if not path:
            return
        try:
            output = document_printing.generate_purchase_report_pdf(
                report["rows"], report["summary"], self._financial_year_name(),
                self._filter_summary(), path,
            )
        except document_printing.DocumentPrintError as exc:
            QMessageBox.warning(self, "Purchase Report", str(exc))
            return
        QMessageBox.information(
            self, "Purchase Report PDF",
            f"Saved to:\n{output}\n\nUse your PDF viewer's Print command to choose a printer.",
        )

    def refresh_theme(self):
        """Refresh report chrome and autocomplete popups in Day/Night mode."""
        p = palette()
        self.setStyleSheet(f"background-color: {p['bg']};")
        self._header.setStyleSheet(
            f"background-color: {p['surface']}; border-bottom: 1px solid {p['border']};"
        )
        self._filters.setStyleSheet(
            f"background-color: {p['surface']}; border-bottom: 1px solid {p['border']};"
        )
        self._summary.setStyleSheet(
            f"background-color: {p['surface']}; border-top: 1px solid {p['border']};"
        )
        for edit in (self.supplier_edit, self.company_edit, self.item_edit):
            edit.refresh_theme()
        for edit in (self.invoice_edit, self.voucher_edit, self.batch_edit):
            edit.setStyleSheet(_edit_style(p))
        for button in self.findChildren(QPushButton):
            button.setStyleSheet(_button_style(p, button.text() == "Search"))
        self._table.setStyleSheet(
            "QTableWidget {"
            f" background-color: {p['bg']}; color: {p['text']};"
            f" border: 1px solid {p['border']}; gridline-color: {p['border']};"
            " font-size: 13px; font-family: 'Segoe UI';"
            f" selection-background-color: {p['accent']}; selection-color: white;"
            "} QTableWidget::item { padding: 2px 5px; }"
        )
        self._table.horizontalHeader().setStyleSheet(
            "QHeaderView::section {"
            f" background-color: {p['surface']}; color: {p['text']};"
            f" border: none; border-bottom: 2px solid {p['accent']};"
            " padding: 3px 6px; font-weight: bold; font-size: 12px;"
            " font-family: 'Segoe UI'; }"
        )
        for label in self.findChildren(QLabel):
            text = label.text()
            if text == "Purchase Report":
                label.setStyleSheet(
                    f"color: {p['text']}; font-size: 18px; font-weight: bold;"
                    "background: transparent; font-family: 'Segoe UI';"
                )
            elif "Based on purchase vouchers" in text:
                label.setStyleSheet(
                    f"color: {p['text_dim']}; font-size: 11px; background: transparent;"
                    "font-family: 'Segoe UI'; margin-right: 10px;"
                )
            elif label in self._summary_labels.values():
                label.setStyleSheet(
                    f"color: {p['text']}; font-size: 12px; font-weight: bold;"
                    "background: transparent; font-family: 'Segoe UI';"
                )
            else:
                label.setStyleSheet(
                    f"color: {p['text']}; font-size: 12px; background: transparent;"
                    "font-family: 'Segoe UI';"
                )
