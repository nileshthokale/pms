from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
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

from database.expiry_report_dao import ExpiryReportDAO
from ui.theme import palette

_p = palette()
_DARK_BG = _p["bg"]
_SURFACE = _p["surface"]
_BORDER = _p["border"]
_ACCENT = _p["accent"]
_ACCENT_HOVER = _p["accent_hover"]
_TEXT = _p["text"]
_TEXT_DIM = _p["text_dim"]

_EXPIRED_COLOR = QColor("#c0392b")
_SOON_COLOR = QColor("#b26a00")
_OK_COLOR = QColor("#2e7d32")
_INVALID_COLOR = QColor("#9e9e9e")

# (label, days, is_default)
_WITHIN_OPTIONS = [
    ("30 Days", 30),
    ("60 Days", 60),
    ("90 Days", 90),
    ("6 Months", 180),
    ("12 Months", 365),
]

_STATUS_OPTIONS = [
    ("Expiring Soon", "expiring_soon"),
    ("Expired", "expired"),
    ("All", "all"),
]

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


class ExpiryReportPage(QWidget):
    """Expiry Report page (Reports → Expiry Report) — read-only.

    Shows batches that are expired or approaching expiry from the
    current stock_batches data. Never modifies stock, batches, expiry
    values or purchase records.
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

        title = QLabel("Expiry Report")
        title.setStyleSheet(
            f"color: {_TEXT}; font-size: 18px; font-weight: bold;"
            f"background: transparent; font-family: 'Segoe UI';"
        )
        hl.addWidget(title)
        hl.addStretch()

        hint = QLabel(
            "Defaults: Expiring Soon · Within 90 Days · Zero-stock batches excluded"
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

        # Row 1: status + within + zero stock
        row1 = QHBoxLayout()
        row1.setSpacing(8)

        row1.addWidget(self._label("Status"))
        self.status_combo = QComboBox()
        self.status_combo.setStyleSheet(_COMBO_STYLE)
        self.status_combo.setMinimumWidth(130)
        for label, value in _STATUS_OPTIONS:
            self.status_combo.addItem(label, value)
        row1.addWidget(self.status_combo)

        row1.addWidget(self._label("Within"))
        self.within_combo = QComboBox()
        self.within_combo.setStyleSheet(_COMBO_STYLE)
        self.within_combo.setMinimumWidth(110)
        for label, days in _WITHIN_OPTIONS:
            self.within_combo.addItem(label, days)
        self.within_combo.setCurrentIndex(2)  # 90 Days (default)
        row1.addWidget(self.within_combo)

        row1.addSpacing(12)
        self.zero_check = QCheckBox("Include Zero Stock")
        self.zero_check.setStyleSheet(_CHECK_STYLE)
        self.zero_check.setChecked(False)
        row1.addWidget(self.zero_check)
        row1.addStretch()
        fv.addLayout(row1)

        # Row 2: item + company + batch + actions
        row2 = QHBoxLayout()
        row2.setSpacing(8)

        row2.addWidget(self._label("Item"))
        self.item_edit = QLineEdit()
        self.item_edit.setStyleSheet(_EDIT_STYLE)
        self.item_edit.setPlaceholderText("item name")
        self.item_edit.setFixedWidth(150)
        self.item_edit.returnPressed.connect(self._on_generate)
        row2.addWidget(self.item_edit)

        row2.addWidget(self._label("Company"))
        self.company_combo = QComboBox()
        self.company_combo.setStyleSheet(_COMBO_STYLE)
        self.company_combo.setMinimumWidth(140)
        row2.addWidget(self.company_combo)

        row2.addWidget(self._label("Batch No"))
        self.batch_edit = QLineEdit()
        self.batch_edit.setStyleSheet(_EDIT_STYLE)
        self.batch_edit.setPlaceholderText("batch")
        self.batch_edit.setFixedWidth(110)
        self.batch_edit.returnPressed.connect(self._on_generate)
        row2.addWidget(self.batch_edit)

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
        self._columns = [
            "Item Name", "Company", "Unit", "Pack", "Batch No",
            "Expiry", "MRP", "Purchase Rate", "Net Rate",
            "Current Stock", "Reorder Level", "Status",
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
        hv.setSectionResizeMode(0, QHeaderView.Stretch)
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
        sl.setSpacing(20)

        self._summary_labels: dict[str, QLabel] = {}
        for key, text in (
            ("expired", "Expired: 0"),
            ("soon", "Expiring Soon: 0"),
            ("invalid", "Invalid: 0"),
            ("batches", "Batches: 0"),
            ("qty", "Total Qty: 0"),
            ("value", "Est. Stock Value: 0.00 (informational)"),
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
        options = ExpiryReportDAO.get_filter_options()
        self.company_combo.blockSignals(True)
        self.company_combo.clear()
        self.company_combo.addItem("All", None)
        for row in options["companies"]:
            self.company_combo.addItem(row["company_name"], row["id"])
        self.company_combo.setCurrentIndex(0)
        self.company_combo.blockSignals(False)

    def _current_filters(self) -> dict:
        return {
            "status": self.status_combo.currentData(),
            "within_days": self.within_combo.currentData(),
            "item_name": self.item_edit.text().strip() or None,
            "company_id": self.company_combo.currentData(),
            "batch_no": self.batch_edit.text().strip() or None,
            "include_zero": self.zero_check.isChecked(),
        }

    # ------------------------------------------------------------------
    def _render(self, report: dict):
        rows = report["rows"]
        self._table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            expiry_display = r["expiry"] if r["expiry"] else "Unknown"
            if r["status"] == "invalid":
                expiry_display = r["expiry"] or "Unknown"

            values = [
                r["item_name"] or "",
                r["company_name"] or "",
                r["unit_name"] or "",
                r["pack_size"] or "",
                r["batch_no"] or "",
                expiry_display,
                f"{r['mrp']:,.2f}",
                f"{r['purchase_rate']:,.2f}",
                f"{r['net_rate']:,.2f}",
                f"{r['stock_qty']:g}",
                f"{r['reorder_stock_level']:g}" if r["reorder_stock_level"] is not None else "",
                r["status_label"],
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if 6 <= col <= 10:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if col == 11:
                    # Status text always present; color is a secondary cue
                    if r["status"] == "expired":
                        item.setForeground(_EXPIRED_COLOR)
                    elif r["status"] == "expiring_soon":
                        item.setForeground(_SOON_COLOR)
                    elif r["status"] == "ok":
                        item.setForeground(_OK_COLOR)
                    else:
                        item.setForeground(_INVALID_COLOR)
                self._table.setItem(i, col, item)

        s = report["summary"]
        self._summary_labels["expired"].setText(f"Expired: {s['expired_count']}")
        self._summary_labels["soon"].setText(
            f"Expiring Soon: {s['expiring_soon_count']}"
        )
        self._summary_labels["invalid"].setText(
            f"Invalid: {s['invalid_count']}"
        )
        self._summary_labels["batches"].setText(
            f"Batches: {s['total_batches']}"
        )
        self._summary_labels["qty"].setText(f"Total Qty: {s['total_qty']:g}")
        self._summary_labels["value"].setText(
            f"Est. Stock Value: {s['estimated_value']:,.2f} (informational)"
        )

    def _on_generate(self):
        try:
            self._render(ExpiryReportDAO.get_expiry_report(**self._current_filters()))
        except Exception as e:
            QMessageBox.critical(
                self, "Error", f"Failed to generate Expiry Report:\n{e}"
            )

    def _on_refresh(self):
        self._load_filter_options()
        self._on_generate()

    def _on_clear(self):
        self.status_combo.setCurrentIndex(0)   # Expiring Soon (default)
        self.within_combo.setCurrentIndex(2)   # 90 Days (default)
        self.zero_check.setChecked(False)
        self.item_edit.clear()
        self.company_combo.setCurrentIndex(0)
        self.batch_edit.clear()
        self._on_generate()
