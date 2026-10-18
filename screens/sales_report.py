from __future__ import annotations

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDateEdit,
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
from database.sales_report_dao import SalesReportDAO
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
    f"  padding: 5px 8px; font-size: 15px; font-family: 'Segoe UI';"
    f"}}"
    f"QLineEdit:focus {{ border: 1px solid {_ACCENT}; }}"
)

_BTN_PRIMARY = (
    f"QPushButton {{ background-color: {_ACCENT}; color: white;"
    f"  border: none; border-radius: 2px; padding: 7px 18px;"
    f"  font-weight: bold; font-size: 15px; font-family: 'Segoe UI'; }}"
    f"QPushButton:hover {{ background-color: {_ACCENT_HOVER}; }}"
)

_BTN_SECONDARY = (
    f"QPushButton {{ background-color: {_BORDER}; color: {_TEXT};"
    f"  border: none; border-radius: 2px; padding: 7px 18px;"
    f"  font-size: 15px; font-family: 'Segoe UI'; }}"
    f"QPushButton:hover {{ background-color: #7d93a8; }}"
)

_LABEL_STYLE = (
    f"color: {_TEXT}; font-size: 15px; background: transparent;"
    f"font-family: 'Segoe UI';"
)


def _date_style(p: dict) -> str:
    return (
        "QDateEdit {"
        f" background-color: {p['surface']}; color: {p['text']};"
        f" border: 1px solid {p['border']}; border-radius: 2px;"
        " padding: 5px 8px; font-size: 15px; font-family: 'Segoe UI';"
        "} QDateEdit:focus {"
        f" border: 1px solid {p['accent']}; }}"
        "QDateEdit::drop-down { border: none; width: 20px; }"
    )


_DATE_STYLE = _date_style(_p)


def _edit_style(p: dict) -> str:
    return (
        "QLineEdit {"
        f" background-color: {p['surface']}; color: {p['text']};"
        f" border: 1px solid {p['border']}; border-radius: 2px;"
        " padding: 5px 8px; font-size: 15px; font-family: 'Segoe UI';"
        "} QLineEdit:focus {"
        f" border: 1px solid {p['accent']}; }}"
    )


def _button_style(p: dict, primary: bool = False) -> str:
    if primary:
        return (
            f"QPushButton {{ background-color: {p['accent']}; color: white;"
            " border: none; border-radius: 2px; padding: 7px 18px;"
            " font-weight: bold; font-size: 15px; font-family: 'Segoe UI'; }"
            f"QPushButton:hover {{ background-color: {p['accent_hover']}; }}"
        )
    return (
        f"QPushButton {{ background-color: {p['border']}; color: {p['text']};"
        " border: none; border-radius: 2px; padding: 7px 18px;"
        " font-size: 15px; font-family: 'Segoe UI'; }"
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
            f"color: {_TEXT}; font-size: 22px; font-weight: bold;"
            f"background: transparent; font-family: 'Segoe UI';"
        )
        hl.addWidget(title)
        hl.addStretch()

        hint = QLabel("Based on sales bills — financial reports use ledger postings")
        hint.setStyleSheet(
            f"color: {_TEXT_DIM}; font-size: 13px; background: transparent;"
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
        fv.setSpacing(8)

        # Two clean rows: filters first, then the actions.  The window may
        # be as narrow as 1024px, while a single row of six filters plus
        # four buttons demanded far more than that — squeezing everything
        # into it pushed the labels into their neighbours.  Each caption
        # now travels inside a small unit with its control, so a label can
        # never drift away from its field, and the action buttons get a
        # row of their own when they cannot fit beside the filters.
        #
        # The navbar FY is the only period control; report filters below
        # can never disable or override that date constraint.
        row1 = QHBoxLayout()
        row1.setSpacing(14)

        self.customer_edit = SearchableFilterEdit("All customers")
        self.customer_edit.setMinimumWidth(130)
        self.customer_edit.returnPressed.connect(self._on_generate)
        row1.addWidget(self._filter_unit("Customer", self.customer_edit))

        self.company_edit = SearchableFilterEdit("All companies")
        self.company_edit.setMinimumWidth(120)
        self.company_edit.returnPressed.connect(self._on_generate)
        row1.addWidget(self._filter_unit("Company", self.company_edit))

        self.item_edit = SearchableFilterEdit("All items")
        self.item_edit.setMinimumWidth(140)
        self.item_edit.returnPressed.connect(self._on_generate)
        row1.addWidget(self._filter_unit("Item", self.item_edit))

        # Picking a suggestion (Enter key or mouse click) searches at once:
        # the widget records the selected ID first, then this refresh runs
        # with the fresh selection.
        for edit in (self.customer_edit, self.company_edit, self.item_edit):
            edit.picked.connect(self._on_generate)

        self.patient_edit = QLineEdit()
        self.patient_edit.setStyleSheet(_EDIT_STYLE)
        self.patient_edit.setPlaceholderText("patient name")
        self.patient_edit.setMinimumWidth(110)
        self.patient_edit.returnPressed.connect(self._on_generate)
        row1.addWidget(self._filter_unit("Patient", self.patient_edit))
        row1.addStretch()
        fv.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(10)

        self._from_date = QDateEdit()
        self._from_date.setCalendarPopup(True)
        self._from_date.setFixedWidth(120)
        self._from_date.setStyleSheet(_DATE_STYLE)
        self._from_date.dateChanged.connect(self._on_generate)
        row2.addWidget(self._filter_unit("From Date", self._from_date))

        self._to_date = QDateEdit()
        self._to_date.setCalendarPopup(True)
        self._to_date.setFixedWidth(120)
        self._to_date.setStyleSheet(_DATE_STYLE)
        self._to_date.dateChanged.connect(self._on_generate)
        row2.addWidget(self._filter_unit("To Date", self._to_date))

        row2.addStretch()

        search_btn = QPushButton("Search")
        search_btn.setStyleSheet(_BTN_PRIMARY)
        search_btn.clicked.connect(self._on_generate)
        row2.addWidget(search_btn)

        clear_btn = QPushButton("Clear")
        clear_btn.setStyleSheet(_BTN_SECONDARY)
        clear_btn.clicked.connect(self._on_clear)
        row2.addWidget(clear_btn)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.setStyleSheet(_BTN_SECONDARY)
        refresh_btn.clicked.connect(self._on_refresh)
        row2.addWidget(refresh_btn)

        print_btn = QPushButton("Print")
        print_btn.setStyleSheet(_BTN_SECONDARY)
        print_btn.clicked.connect(self._on_print)
        row2.addWidget(print_btn)
        fv.addLayout(row2)

        root.addWidget(filters)

        # ── Table ────────────────────────────────────────────────
        self._table = QTableWidget()
        self._table.setColumnCount(11)
        self._table.setHorizontalHeaderLabels([
            "Bill No", "Sale Date", "Patient Name", "Doctor",
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
        hv.setSectionResizeMode(4, QHeaderView.Stretch)
        hv.setStyleSheet(
            f"QHeaderView::section {{"
            f"  background-color: {_SURFACE}; color: {_TEXT};"
            f"  border: none; border-bottom: 2px solid {_ACCENT};"
            f"  padding: 3px 6px; font-weight: bold; font-size: 15px;"
            f"  font-family: 'Segoe UI';"
            f"}}"
        )
        self._table.setStyleSheet(
            f"QTableWidget {{"
            f"  background-color: {_DARK_BG}; color: {_TEXT};"
            f"  border: 1px solid {_BORDER}; gridline-color: {_BORDER};"
            f"  font-size: 15px; font-family: 'Segoe UI';"
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
            if key == "net":
                sl.addStretch()
            lbl = QLabel(text)
            lbl.setStyleSheet(
                f"color: {_TEXT}; font-size: 15px; font-weight: bold;"
                f"background: transparent; font-family: 'Segoe UI';"
            )
            self._summary_labels[key] = lbl
            sl.addWidget(lbl)
        root.addWidget(summary)

        # Default to today's live date so opening the page shows the daily
        # report straight away; Clear restores the same default.
        today = QDate.currentDate()
        for edit in (self._from_date, self._to_date):
            edit.blockSignals(True)
            edit.setDate(today)
            edit.blockSignals(False)
        self._load_filter_options()
        self._on_generate()

    # ------------------------------------------------------------------
    def _label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(_LABEL_STYLE)
        return lbl

    def _filter_unit(self, text: str, control: QWidget) -> QWidget:
        """A caption glued to its control at a fixed small gap.

        Wrapping the pair in a tiny container is what keeps the label next
        to the field it names at every window width; the toolbar rows then
        space these units apart from each other.
        """
        unit = QWidget()
        box = QHBoxLayout(unit)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(8)
        box.addWidget(self._label(text))
        box.addWidget(control)
        return unit

    def _load_filter_options(self):
        options = SalesReportDAO.get_filter_options()
        for edit, rows, id_key, name_key in (
            (self.customer_edit, options["customers"], "id", "customer_name"),
            (self.company_edit, options["companies"], "id", "company_name"),
            (self.item_edit, options["items"], "id", "item_name"),
        ):
            edit.set_options(rows, id_key, name_key)

    def _filter_id(self, edit: SearchableFilterEdit):
        """Selected ID, falling back to fully-typed filter text.

        Covers typing an exact name and pressing Search without ever picking
        the completion popup; partial or unknown text still means no filter.
        """
        if edit.selected_id is not None:
            return edit.selected_id
        return edit.exact_id_for_text(edit.text())

    def _current_filters(self) -> dict:
        # The FY range always caps the report; the From/To editors narrow
        # inside it but can never widen past it.
        fy_from, fy_to = view_year_bounds(self._history_financial_year)
        picked_from, picked_to = self._picked_dates()
        return {
            "from_date": max(fy_from, picked_from),
            "to_date": min(fy_to, picked_to),
            "customer_id": self._filter_id(self.customer_edit),
            "item_id": self._filter_id(self.item_edit),
            "company_id": self._filter_id(self.company_edit),
            "patient": self.patient_edit.text().strip() or None,
        }

    def _picked_dates(self) -> tuple[str, str]:
        """From/To editor values as ISO dates, falling back to the FY bounds."""
        fy_from, fy_to = view_year_bounds(self._history_financial_year)
        from_q, to_q = self._from_date.date(), self._to_date.date()
        picked_from = from_q.toString("yyyy-MM-dd") if from_q.isValid() else fy_from
        picked_to = to_q.toString("yyyy-MM-dd") if to_q.isValid() else fy_to
        return picked_from, picked_to

    def _range_valid(self) -> bool:
        picked_from, picked_to = self._picked_dates()
        return picked_from <= picked_to

    def _reset_date_edits(self):
        from_date, to_date = view_year_bounds(self._history_financial_year)
        for edit, iso in ((self._from_date, from_date), (self._to_date, to_date)):
            edit.blockSignals(True)
            edit.setDate(QDate.fromString(iso, "yyyy-MM-dd"))
            edit.blockSignals(False)

    def set_history_financial_year(self, year: dict | None):
        """Refresh for the navbar's view-only selected financial year."""
        self._history_financial_year = dict(year) if year else None
        self._reset_date_edits()
        self._on_generate()

    # ------------------------------------------------------------------
    def _render(self, report: dict):
        rows = report["rows"]
        self._table.setRowCount(len(rows))
        from core.doc_formatter import format_sales_bill_number
        for i, r in enumerate(rows):
            values = [
                format_sales_bill_number(r["bill_no"], patient_name=r.get("patient_name")),
                r["sale_date"],
                str(r["patient_name"] or "").strip() or "WALKIN",
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
                if col >= 7:
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
        if not self._range_valid():
            QMessageBox.warning(self, "Sales Report", "From Date cannot be later than To Date.")
            return
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
        self.patient_edit.clear()
        today = QDate.currentDate()
        for edit in (self._from_date, self._to_date):
            edit.blockSignals(True)
            edit.setDate(today)
            edit.blockSignals(False)
        self._on_generate()

    def _filter_summary(self) -> str:
        parts = [f"Financial year: {self._financial_year_name()}"]
        for label, edit in (("Customer", self.customer_edit),
                            ("Company", self.company_edit), ("Item", self.item_edit)):
            if edit.selected_id is not None:
                parts.append(f"{label}: {edit.text()}")
        if self.patient_edit.text().strip():
            parts.append(f"Patient: {self.patient_edit.text().strip()}")
        picked_from, picked_to = self._picked_dates()

        def _dmy(iso: str) -> str:
            day = iso.split("-")
            return f"{day[2]}-{day[1]}-{day[0]}" if len(day) == 3 else iso

        parts.append(f"From: {_dmy(picked_from)} To: {_dmy(picked_to)}")
        return " | ".join(parts)

    def _report_title(self, filters: dict | None = None) -> str:
        """Print title matching the filters that are actually applied.

        Company only → COMPANYWISE SALES REPORT; Customer/Patient only →
        PATIENTWISE; Item only → ITEMWISE; no filter kind → DAILY.  When
        several kinds are entered the title combines them, so no filter
        is silently dropped and the title cannot mislead.
        """
        f = self._current_filters() if filters is None else filters
        kinds: list[str] = []
        if f.get("company_id") is not None:
            kinds.append("COMPANYWISE")
        if f.get("customer_id") is not None or f.get("patient"):
            kinds.append("PATIENTWISE")
        if f.get("item_id") is not None:
            kinds.append("ITEMWISE")
        if not kinds:
            return "DAILY SALES REPORT"
        return " & ".join(kinds) + " SALES REPORT"

    def _financial_year_name(self) -> str:
        year = self._history_financial_year or {}
        return str(year.get("name") or "FY " + "–".join(
            (self._current_filters()["from_date"][:4], self._current_filters()["to_date"][:4])
        ))

    def _on_print(self):
        # Re-query so printed output exactly matches the current controls.
        if not self._range_valid():
            QMessageBox.warning(self, "Sales Report", "From Date cannot be later than To Date.")
            return
        filters = self._current_filters()
        try:
            report = SalesReportDAO.get_sales_report(**filters)
        except Exception as exc:
            QMessageBox.warning(self, "Sales Report", f"Could not prepare report: {exc}")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Daily Sales Report PDF", "daily_sales_report.pdf", "PDF (*.pdf)"
        )
        if not path:
            return
        try:
            output = document_printing.generate_daily_sales_report_pdf(
                report["rows"], report["summary"], self._financial_year_name(),
                self._filter_summary(), path,
                from_date=filters.get("from_date") or "",
                to_date=filters.get("to_date") or "",
                report_title=self._report_title(filters),
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
        self.patient_edit.setStyleSheet(_edit_style(p))
        self._from_date.setStyleSheet(_date_style(p))
        self._to_date.setStyleSheet(_date_style(p))
        for button in self.findChildren(QPushButton):
            button.setStyleSheet(_button_style(p, button.text() == "Search"))
        self._table.setStyleSheet(
            "QTableWidget {"
            f" background-color: {p['bg']}; color: {p['text']};"
            f" border: 1px solid {p['border']}; gridline-color: {p['border']};"
            " font-size: 15px; font-family: 'Segoe UI';"
            f" selection-background-color: {p['accent']}; selection-color: white;"
            "} QTableWidget::item { padding: 2px 5px; }"
        )
        self._table.horizontalHeader().setStyleSheet(
            "QHeaderView::section {"
            f" background-color: {p['surface']}; color: {p['text']};"
            f" border: none; border-bottom: 2px solid {p['accent']};"
            " padding: 3px 6px; font-weight: bold; font-size: 15px;"
            " font-family: 'Segoe UI'; }"
        )
        for label in self.findChildren(QLabel):
            text = label.text()
            if text == "Sales Report":
                label.setStyleSheet(
                    f"color: {p['text']}; font-size: 22px; font-weight: bold;"
                    "background: transparent; font-family: 'Segoe UI';"
                )
            elif "Based on sales bills" in text:
                label.setStyleSheet(
                    f"color: {p['text_dim']}; font-size: 13px; background: transparent;"
                    "font-family: 'Segoe UI'; margin-right: 10px;"
                )
            elif label in self._summary_labels.values():
                label.setStyleSheet(
                    f"color: {p['text']}; font-size: 15px; font-weight: bold;"
                    "background: transparent; font-family: 'Segoe UI';"
                )
            else:
                label.setStyleSheet(
                    f"color: {p['text']}; font-size: 15px; background: transparent;"
                    "font-family: 'Segoe UI';"
                )
