from __future__ import annotations

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QDateEdit,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from database import document_printing
from database.sales_report_dao import SalesReportDAO
from ui.fy_view import view_year_bounds
from ui.searchable_filter import SearchableFilterEdit
from ui.theme import indicator_style, palette

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


def _date_style(p: dict) -> str:
    return (
        "QDateEdit {"
        f" background-color: {p['surface']}; color: {p['text']};"
        f" border: 1px solid {p['border']}; border-radius: 2px;"
        " padding: 5px 8px; font-size: 12px; font-family: 'Segoe UI';"
        "} QDateEdit:focus {"
        f" border: 1px solid {p['accent']}; }}"
        "QDateEdit::drop-down { border: none; width: 20px; }"
    )


_DATE_STYLE = _date_style(_p)


def _radio_style(p: dict) -> str:
    """Item Wise / Bill Wise radios: text plus a theme-aware indicator dot."""
    return (
        f"QRadioButton {{ color: {p['text']}; font-size: 12px;"
        f"  background: transparent; border: none; outline: none;"
        f"  spacing: 5px; font-family: 'Segoe UI'; }}"
        "QRadioButton:focus { background: transparent;"
        "  border: none; outline: none; }"
        "QRadioButton:hover { background: transparent; border: none; }"
        + indicator_style(checkbox=False)
    )


_RADIO_STYLE = _radio_style(_p)


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

class SalesReportPage(QWidget):
    """Sales Report page (Reports → Sales Report) — read-only.

    Reports the application's sales source documents
    (sales_invoices + sales_invoice_items). Financial reports (Trial
    Balance, P&L, Balance Sheet) are based on ledger postings instead.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        # The navbar changes this display-only value through
        # ``set_history_financial_year``.  It deliberately never changes the
        # active FY in the database.
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

        # One compact row.  The navbar FY is the only period control; report
        # filters below can never disable or override that date constraint.
        row1 = QHBoxLayout()
        row1.setSpacing(8)

        row1.addWidget(self._label("Customer"))
        self.customer_edit = SearchableFilterEdit("All customers")
        self.customer_edit.setMinimumWidth(150)
        row1.addWidget(self.customer_edit)

        row1.addWidget(self._label("Company"))
        self.company_edit = SearchableFilterEdit("All companies")
        self.company_edit.setMinimumWidth(135)
        row1.addWidget(self.company_edit)

        row1.addWidget(self._label("Item"))
        self.item_edit = SearchableFilterEdit("All items")
        self.item_edit.setMinimumWidth(155)
        self.item_edit.returnPressed.connect(self._on_generate)
        row1.addWidget(self.item_edit)

        # Single-day selector.  Off by default so the page keeps its
        # financial-year view; when on, the picked day is intersected with
        # the FY bounds below and both the table and the print follow it.
        self._date_check = QCheckBox("Date:")
        self._date_check.setChecked(False)
        self._date_check.setStyleSheet(_LABEL_STYLE)
        self._date_check.toggled.connect(self._on_date_toggled)
        row1.addWidget(self._date_check)

        self._date_edit = QDateEdit()
        self._date_edit.setCalendarPopup(True)
        self._date_edit.setDate(QDate.currentDate())
        self._date_edit.setEnabled(False)
        self._date_edit.setFixedWidth(110)
        self._date_edit.setStyleSheet(_DATE_STYLE)
        self._date_edit.dateChanged.connect(self._on_generate)
        row1.addWidget(self._date_edit)

        self.mode_group = QButtonGroup(self)
        self.item_wise_radio = QRadioButton("Item Wise")
        self.bill_wise_radio = QRadioButton("Bill Wise")
        self.item_wise_radio.setStyleSheet(_RADIO_STYLE)
        self.bill_wise_radio.setStyleSheet(_RADIO_STYLE)
        self.item_wise_radio.setChecked(True)
        self.mode_group.addButton(self.item_wise_radio)
        self.mode_group.addButton(self.bill_wise_radio)
        row1.addWidget(self.item_wise_radio)
        row1.addWidget(self.bill_wise_radio)

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
        self._summary = summary
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
        for edit, rows, id_key, name_key in (
            (self.customer_edit, options["customers"], "id", "customer_name"),
            (self.company_edit, options["companies"], "id", "company_name"),
            (self.item_edit, options["items"], "id", "item_name"),
        ):
            edit.set_options(rows, id_key, name_key)

    def _current_filters(self) -> dict:
        # `view_year_bounds` falls back to the active FY, so this call can
        # never form an unbounded query even before a navbar selection.
        from_date, to_date = view_year_bounds(self._history_financial_year)
        if self._date_check.isChecked():
            # Narrow to the picked day without ever widening past the FY
            # bounds; a day outside the FY yields an (honest) empty report.
            picked = self._date_edit.date().toString("yyyy-MM-dd")
            from_date = max(from_date, picked)
            to_date = min(to_date, picked)
        return {
            "from_date": from_date,
            "to_date": to_date,
            "customer_id": self.customer_edit.selected_id,
            "item_id": self.item_edit.selected_id,
            "company_id": self.company_edit.selected_id,
        }

    def _selected_day(self) -> str | None:
        """Picked calendar day (ISO) when the Date box is checked."""
        if self._date_check.isChecked():
            picked = self._date_edit.date()
            if picked.isValid():
                return picked.toString("yyyy-MM-dd")
        return None

    def _on_date_toggled(self, checked: bool):
        self._date_edit.setEnabled(checked)
        self._on_generate()

    def set_history_financial_year(self, year: dict | None):
        """Refresh for the navbar's view-only selected financial year."""
        self._history_financial_year = dict(year) if year else None
        self._on_generate()

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
            self._last_report = SalesReportDAO.get_sales_report(**self._current_filters())
            self._render(self._last_report)
        except Exception as e:
            QMessageBox.critical(
                self, "Error", f"Failed to generate Sales Report:\n{e}"
            )

    def _on_refresh(self):
        self._load_filter_options()
        self._on_generate()

    def _on_clear(self):
        self.customer_edit.clear_filter()
        self.company_edit.clear_filter()
        self.item_edit.clear_filter()
        self._date_check.blockSignals(True)
        self._date_edit.blockSignals(True)
        self._date_check.setChecked(False)
        self._date_edit.setDate(QDate.currentDate())
        self._date_check.blockSignals(False)
        self._date_edit.blockSignals(False)
        self._date_edit.setEnabled(False)
        self._on_generate()

    def _filter_summary(self) -> str:
        parts = [f"Financial year: {self._financial_year_name()}"]
        for label, edit in (("Customer", self.customer_edit),
                            ("Company", self.company_edit), ("Item", self.item_edit)):
            if edit.selected_id is not None:
                parts.append(f"{label}: {edit.text()}")
        picked = self._selected_day()
        if picked is not None:
            day = picked.split("-")
            parts.append(f"Date: {day[2]}-{day[1]}-{day[0]}")
        parts.append(f"Mode: {'Bill Wise' if self.bill_wise_radio.isChecked() else 'Item Wise'}")
        return " | ".join(parts)

    def _financial_year_name(self) -> str:
        year = self._history_financial_year or {}
        return str(year.get("name") or "FY " + "–".join(
            (self._current_filters()["from_date"][:4], self._current_filters()["to_date"][:4])
        ))

    def _on_print(self):
        # Re-query so printed output exactly matches the current controls.
        # The selected mode changes only the print rendering, never the data.
        try:
            filters = self._current_filters()
            report = SalesReportDAO.get_sales_report(**filters)
        except Exception as exc:
            QMessageBox.warning(self, "Sales Report", f"Could not prepare report: {exc}")
            return
        billwise = self.bill_wise_radio.isChecked()
        if billwise:
            dialog_title, default_name = "Save Bill Wise Sales Report PDF", "sales_report_billwise.pdf"
        else:
            dialog_title, default_name = "Save Item Wise Sales Report PDF", "sales_report_itemwise.pdf"
        path, _ = QFileDialog.getSaveFileName(
            self, dialog_title, default_name, "PDF (*.pdf)"
        )
        if not path:
            return
        try:
            if billwise:
                output = document_printing.generate_billwise_sales_report_pdf(
                    report["rows"], report["summary"], self._financial_year_name(),
                    self._filter_summary(), path,
                )
            else:
                output = document_printing.generate_sales_report_pdf(
                    report["rows"], report["summary"], self._financial_year_name(),
                    self._filter_summary(), path,
                    report_from=self._selected_day() or filters["from_date"],
                    report_to=self._selected_day() or filters["to_date"],
                )
        except document_printing.DocumentPrintError as exc:
            QMessageBox.warning(self, "Sales Report", str(exc))
            return
        QMessageBox.information(self, "Sales Report PDF", f"Saved to:\n{output}\n\nUse your PDF viewer's Print command to choose a printer.")

    def refresh_theme(self):
        """Refresh screen and completion popup colours without losing state."""
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
        for edit in (self.customer_edit, self.company_edit, self.item_edit):
            edit.refresh_theme()
        for radio in (self.item_wise_radio, self.bill_wise_radio):
            radio.setStyleSheet(_radio_style(p))
        self._date_edit.setStyleSheet(_date_style(p))
        self._date_check.setStyleSheet(
            f"color: {p['text']}; font-size: 12px; background: transparent;"
            f"font-family: 'Segoe UI';"
        )
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
            if text == "Sales Report":
                label.setStyleSheet(
                    f"color: {p['text']}; font-size: 18px; font-weight: bold;"
                    "background: transparent; font-family: 'Segoe UI';"
                )
            elif "Based on sales bills" in text:
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
