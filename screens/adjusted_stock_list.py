"""Adjusted Stock List page for Pharmacy Management System.

Matches the Pharma-WINNER Adjusted Stock List workflow:
- Action toolbar: New and Edit buttons
- Banner header: 'Adjusted Stock List'
- Filters:
  * Item dropdown with 'ALL' option
  * Date range filter: From Date, Filter type (AdjustedDate), To Date, Filter, Refresh
- 11-column history table matching reference screenshots:
  ItemName | PackSize | Date | BatchNo | Expiry | Qty | MRP | Rate | TxPer | TaxAmt | NetRate
- Double-clicking or clicking Edit opens the Stock Adjustment dialog in edit mode
- Atomic delta reconciliation on edit; no double-counting; preserves historical records
"""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from PySide6.QtCore import Qt, QDate
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateEdit,
    QFrame,
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

from database.stock_adjustment_dao import StockAdjustmentDAO
from screens.stock_adjustment_dialog import StockAdjustmentDialog, _format_expiry_display
from ui.theme import (
    FONT_FAMILY,
    TYPE_BUTTON,
    TYPE_FORM_LABEL,
    TYPE_HINT,
    TYPE_INPUT,
    TYPE_PAGE_TITLE,
    palette,
)


def _fmt_date_dmy(iso_date: str) -> str:
    """Format YYYY-MM-DD to DD/MM/YYYY for UI display matching Pharma-WINNER."""
    if not iso_date:
        return ""
    parts = str(iso_date).strip().split("-")
    if len(parts) == 3:
        return f"{parts[2]}/{parts[1]}/{parts[0]}"
    return iso_date


class AdjustedStockListPage(QWidget):
    """Adjusted Stock List page matching Pharma-WINNER reference."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._records: list[dict[str, Any]] = []
        self._init_ui()
        self._load_item_filter()
        self._refresh_history()

    def _init_ui(self):
        p = palette()
        self.setStyleSheet(
            f"QWidget {{ background-color: {p['surface']}; color: {p['text']}; font-family: {FONT_FAMILY}; }}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(6)

        # ── Top Cyan Header / Banner Bar ──────────────────────────────
        banner_bar = QFrame()
        banner_bar.setFixedHeight(54)
        banner_bar.setStyleSheet(
            "QFrame { background-color: #00a2e8; border: 1px solid #0088cc; border-radius: 3px; }"
        )
        banner_layout = QHBoxLayout(banner_bar)
        banner_layout.setContentsMargins(8, 4, 8, 4)
        banner_layout.setSpacing(8)

        # Action Buttons (Left)
        self.btn_new = QPushButton("New")
        self.btn_new.setToolTip("Record new stock adjustment (Ctrl+A)")
        self.btn_new.setFixedSize(70, 36)
        self.btn_new.setStyleSheet(
            "QPushButton { background-color: #f0f0f0; color: #000000; border: 1px solid #aaaaaa; "
            "border-radius: 3px; font-weight: bold; font-size: 13px; }"
            "QPushButton:hover { background-color: #ffffff; border-color: #004488; }"
        )
        self.btn_new.clicked.connect(self._on_new)
        banner_layout.addWidget(self.btn_new)

        self.btn_edit = QPushButton("Edit")
        self.btn_edit.setToolTip("Edit selected stock adjustment")
        self.btn_edit.setFixedSize(70, 36)
        self.btn_edit.setStyleSheet(
            "QPushButton { background-color: #f0f0f0; color: #000000; border: 1px solid #aaaaaa; "
            "border-radius: 3px; font-weight: bold; font-size: 13px; }"
            "QPushButton:hover { background-color: #ffffff; border-color: #004488; }"
        )
        self.btn_edit.clicked.connect(self._on_edit)
        banner_layout.addWidget(self.btn_edit)

        banner_layout.addStretch()

        # Title: Adjusted Stock List (Centered bold maroon)
        title_lbl = QLabel("Adjusted Stock List")
        title_lbl.setStyleSheet(
            "color: #800000; font-size: 20px; font-weight: bold; background: transparent;"
        )
        banner_layout.addWidget(title_lbl)
        banner_layout.addStretch()

        root.addWidget(banner_bar)

        # ── Filter Bar ────────────────────────────────────────────────
        filter_bar = QFrame()
        filter_bar.setFixedHeight(42)
        filter_bar.setStyleSheet(
            f"QFrame {{ background-color: {p['surface_alt']}; border: 1px solid {p['border']}; border-radius: 2px; }}"
        )
        fl = QHBoxLayout(filter_bar)
        fl.setContentsMargins(10, 2, 10, 2)
        fl.setSpacing(8)

        lbl_item = QLabel("Item:")
        lbl_item.setStyleSheet(f"font-weight: bold; font-size: {TYPE_FORM_LABEL}px; color: {p['text']};")
        fl.addWidget(lbl_item)

        self.item_filter_combo = QComboBox()
        self.item_filter_combo.setMinimumWidth(260)
        self.item_filter_combo.setFixedHeight(28)
        self.item_filter_combo.setStyleSheet(
            f"QComboBox {{ background-color: {p['surface']}; color: {p['text']}; border: 1px solid {p['border']}; "
            f"padding: 2px 6px; font-size: {TYPE_INPUT}px; }}"
        )
        self.item_filter_combo.currentIndexChanged.connect(self._refresh_history)
        fl.addWidget(self.item_filter_combo)

        fl.addStretch()

        # Date range filters matching reference: FromDate | AdjustedDate | ToDate | Filter
        self.from_date_edit = QDateEdit()
        self.from_date_edit.setCalendarPopup(True)
        self.from_date_edit.setDisplayFormat("dd/MM/yyyy")
        self.from_date_edit.setDate(QDate.currentDate())
        self.from_date_edit.setFixedWidth(110)
        self.from_date_edit.setFixedHeight(28)
        fl.addWidget(self.from_date_edit)

        self.date_type_combo = QComboBox()
        self.date_type_combo.addItem("AdjustedDate")
        self.date_type_combo.setFixedWidth(120)
        self.date_type_combo.setFixedHeight(28)
        fl.addWidget(self.date_type_combo)

        self.to_date_edit = QDateEdit()
        self.to_date_edit.setCalendarPopup(True)
        self.to_date_edit.setDisplayFormat("dd/MM/yyyy")
        self.to_date_edit.setDate(QDate.currentDate())
        self.to_date_edit.setFixedWidth(110)
        self.to_date_edit.setFixedHeight(28)
        fl.addWidget(self.to_date_edit)

        self.btn_filter = QPushButton("Filter")
        self.btn_filter.setFixedWidth(70)
        self.btn_filter.setFixedHeight(28)
        self.btn_filter.setStyleSheet(
            f"QPushButton {{ background-color: {p['accent']}; color: #ffffff; border: 1px solid {p['accent']}; "
            f"border-radius: 2px; font-weight: bold; font-size: {TYPE_BUTTON}px; }}"
            f"QPushButton:hover {{ background-color: {p['selected']}; }}"
        )
        self.btn_filter.clicked.connect(self._refresh_history)
        fl.addWidget(self.btn_filter)

        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.setFixedWidth(75)
        self.btn_refresh.setFixedHeight(28)
        self.btn_refresh.setStyleSheet(
            f"QPushButton {{ background-color: {p['surface']}; color: {p['text']}; border: 1px solid {p['border']}; "
            f"border-radius: 2px; font-size: {TYPE_BUTTON}px; }}"
            f"QPushButton:hover {{ background-color: {p['selected']}; color: {p['selected_text']}; }}"
        )
        self.btn_refresh.clicked.connect(self._on_reset_filters)
        fl.addWidget(self.btn_refresh)

        root.addWidget(filter_bar)

        # ── History Table (11 Columns) ─────────────────────────────────
        # ItemName | PackSize | Date | BatchNo | Expiry | Qty | MRP | Rate | TxPer | TaxAmt | NetRate
        self.table = QTableWidget()
        self.table.setColumnCount(11)
        self.table.setHorizontalHeaderLabels([
            "ItemName", "PackSize", "Date", "BatchNo", "Expiry",
            "Qty", "MRP", "Rate", "TxPer", "TaxAmt", "NetRate"
        ])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(True)
        self.table.setAlternatingRowColors(False)
        self.table.setSortingEnabled(True)

        hv = self.table.horizontalHeader()
        hv.setStretchLastSection(False)
        hv.setSectionResizeMode(0, QHeaderView.Stretch)            # ItemName stretches
        hv.setSectionResizeMode(1, QHeaderView.ResizeToContents)   # PackSize
        hv.setSectionResizeMode(2, QHeaderView.ResizeToContents)   # Date
        hv.setSectionResizeMode(3, QHeaderView.ResizeToContents)   # BatchNo
        hv.setSectionResizeMode(4, QHeaderView.ResizeToContents)   # Expiry
        hv.setSectionResizeMode(5, QHeaderView.ResizeToContents)   # Qty
        hv.setSectionResizeMode(6, QHeaderView.ResizeToContents)   # MRP
        hv.setSectionResizeMode(7, QHeaderView.ResizeToContents)   # Rate
        hv.setSectionResizeMode(8, QHeaderView.ResizeToContents)   # TxPer
        hv.setSectionResizeMode(9, QHeaderView.ResizeToContents)   # TaxAmt
        hv.setSectionResizeMode(10, QHeaderView.ResizeToContents)  # NetRate

        self.table.itemDoubleClicked.connect(self._on_table_double_clicked)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)

        root.addWidget(self.table, 1)

        # ── Status Bar Strip ──────────────────────────────────────────
        status_bar = QHBoxLayout()
        self.lbl_record_count = QLabel("0 record(s)")
        self.lbl_record_count.setStyleSheet(f"font-size: {TYPE_HINT}px; color: {p['text_dim']}; font-weight: bold;")
        status_bar.addWidget(self.lbl_record_count)
        status_bar.addStretch()
        root.addLayout(status_bar)

    def _load_item_filter(self):
        """Populate the Item filter combo with 'ALL' and all distinct items."""
        self.item_filter_combo.blockSignals(True)
        self.item_filter_combo.clear()
        self.item_filter_combo.addItem("ALL", None)

        items = StockAdjustmentDAO.get_distinct_adjusted_items()
        for it in items:
            self.item_filter_combo.addItem(it["item_name"], int(it["id"]))
        self.item_filter_combo.blockSignals(False)

    def _on_reset_filters(self):
        """Reset date range and item filter, then reload records."""
        self.from_date_edit.setDate(QDate.currentDate())
        self.to_date_edit.setDate(QDate.currentDate())
        self.item_filter_combo.setCurrentIndex(0)
        self._load_item_filter()
        self._refresh_history()

    def _refresh_history(self):
        """Load and display records matching current filter criteria."""
        item_id = self.item_filter_combo.currentData()

        # Convert QDate to ISO format YYYY-MM-DD
        from_iso = self.from_date_edit.date().toString("yyyy-MM-dd")
        to_iso = self.to_date_edit.date().toString("yyyy-MM-dd")

        self._records = StockAdjustmentDAO.get_all_filtered(
            from_date=from_iso,
            to_date=to_iso,
            item_id=item_id,
        )

        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self._records))

        for r_idx, r in enumerate(self._records):
            def _it(val: Any, align=Qt.AlignLeft | Qt.AlignVCenter) -> QTableWidgetItem:
                item = QTableWidgetItem(str(val))
                item.setTextAlignment(align)
                return item

            # 0. ItemName
            it_name = _it(r.get("item_name") or "", Qt.AlignLeft | Qt.AlignVCenter)
            it_name.setData(Qt.UserRole, int(r["id"]))  # Store adjustment ID in column 0
            self.table.setItem(r_idx, 0, it_name)

            # 1. PackSize
            self.table.setItem(r_idx, 1, _it(r.get("pack_size") or "1", Qt.AlignCenter))

            # 2. Date (DD/MM/YYYY)
            date_disp = _fmt_date_dmy(r.get("adjustment_date") or "")
            self.table.setItem(r_idx, 2, _it(date_disp, Qt.AlignCenter))

            # 3. BatchNo
            self.table.setItem(r_idx, 3, _it(r.get("batch_no") or "", Qt.AlignCenter))

            # 4. Expiry
            exp_disp = _format_expiry_display(r.get("expiry") or "")
            self.table.setItem(r_idx, 4, _it(exp_disp, Qt.AlignCenter))

            # 5. Qty (+/- with sign)
            qty_val = float(r.get("adjusted_qty") or 0.0)
            qty_str = f"{qty_val:+g}"
            it_qty = _it(qty_str, Qt.AlignRight | Qt.AlignVCenter)
            it_qty.setForeground(QColor("#16A34A" if qty_val > 0 else "#DC2626"))
            self.table.setItem(r_idx, 5, it_qty)

            # 6. MRP
            self.table.setItem(r_idx, 6, _it(f"{float(r.get('mrp') or 0.0):.2f}", Qt.AlignRight | Qt.AlignVCenter))

            # 7. Rate
            self.table.setItem(r_idx, 7, _it(f"{float(r.get('rate') or 0.0):.2f}", Qt.AlignRight | Qt.AlignVCenter))

            # 8. TxPer
            tx_per = float(r.get("tax_percent") or 0.0)
            self.table.setItem(r_idx, 8, _it(f"{int(tx_per) if tx_per.is_integer() else tx_per:g}", Qt.AlignRight | Qt.AlignVCenter))

            # 9. TaxAmt
            tax_amt = float(r.get("tax_amount") or 0.0)
            self.table.setItem(r_idx, 9, _it(f"{tax_amt:.2f}", Qt.AlignRight | Qt.AlignVCenter))

            # 10. NetRate
            self.table.setItem(r_idx, 10, _it(f"{float(r.get('net_rate') or 0.0):.2f}", Qt.AlignRight | Qt.AlignVCenter))

        self.table.setSortingEnabled(True)
        self.lbl_record_count.setText(f"{len(self._records)} record(s)")

    def _get_selected_adjustment_id(self) -> int | None:
        """Return the adjustment ID of the selected row, if any."""
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 0)
        if item is not None:
            val = item.data(Qt.UserRole)
            if val is not None:
                return int(val)
        return None

    def _on_selection_changed(self):
        """Enable or disable Edit button based on selection."""
        has_sel = bool(self.table.selectionModel().selectedRows())
        self.btn_edit.setEnabled(has_sel)

    def _on_table_double_clicked(self, item: QTableWidgetItem):
        """Open edit dialog when a table row is double-clicked."""
        self._on_edit()

    def _on_new(self):
        """Open the Stock Adjustment dialog to record a new adjustment."""
        dlg = StockAdjustmentDialog(self)
        if dlg.exec():
            self._load_item_filter()
            self._refresh_history()

    def _on_edit(self):
        """Open the Stock Adjustment dialog in edit mode for the selected record."""
        adj_id = self._get_selected_adjustment_id()
        if adj_id is None:
            QMessageBox.information(self, "Edit Stock Adjustment", "Please select an adjustment row to edit.")
            return

        dlg = StockAdjustmentDialog(self, edit_adjustment_id=adj_id)
        if dlg.exec():
            self._refresh_history()
