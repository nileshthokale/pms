from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from database.stock_dao import StockDAO
from database.company_dao import CompanyDAO

from ui.theme import palette
_p = palette()
_DARK_BG = _p["bg"]
_SURFACE = _p["surface"]
_BORDER = _p["border"]
_ACCENT = _p["accent"]
_ACCENT_HOVER = _p["accent_hover"]
_TEXT = _p["text"]
_TEXT_DIM = _p["text_dim"]

_COMBO_STYLE = (
    f"QComboBox {{"
    f"  background-color: {_SURFACE}; color: {_TEXT};"
    f"  border: 1px solid {_BORDER}; border-radius: 2px;"
    f"  padding: 6px; font-size: 13px; font-family: 'Segoe UI';"
    f"}}"
    f"QComboBox:hover {{ border: 1px solid {_ACCENT}; }}"
    f"QComboBox::drop-down {{ border: none; width: 24px; }}"
    f"QComboBox::down-arrow {{ image: none; border: none; }}"
    f"QComboBox QAbstractItemView {{"
    f"  background-color: {_SURFACE}; color: {_TEXT};"
    f"  border: 1px solid {_BORDER}; selection-background-color: {_ACCENT};"
    f"  font-size: 13px; font-family: 'Segoe UI';"
    f"}}"
)

_EDIT_STYLE = (
    f"QLineEdit {{"
    f"  background-color: {_SURFACE}; color: {_TEXT};"
    f"  border: 1px solid {_BORDER}; border-radius: 2px;"
    f"  padding: 6px 10px; font-size: 13px; font-family: 'Segoe UI';"
    f"}}"
    f"QLineEdit:focus {{ border: 1px solid {_ACCENT}; }}"
)

_BTN_GREEN = (
    f"QPushButton {{ background-color: {_ACCENT}; color: white;"
    f"  border: none; border-radius: 2px; padding: 6px 16px;"
    f"  font-weight: bold; font-size: 13px; font-family: 'Segoe UI'; }}"
    f"QPushButton:hover {{ background-color: {_ACCENT_HOVER}; }}"
)

_BTN_GRAY = (
    f"QPushButton {{ background-color: {_BORDER}; color: {_TEXT};"
    f"  border: none; border-radius: 2px; padding: 6px 16px;"
    f"  font-size: 13px; font-family: 'Segoe UI'; }}"
    f"QPushButton:hover {{ background-color: #7d93a8; }}"
)


class StockMasterPage(QWidget):
    """Stock / Inventory read-only table with search and filters."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setStyleSheet(f"background-color: {_DARK_BG};")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # -- Header bar --
        header = QWidget()
        header.setFixedHeight(56)
        header.setStyleSheet(
            f"background-color: {_SURFACE}; border-bottom: 1px solid {_BORDER};"
        )
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 0, 16, 0)

        title = QLabel("Stock Master")
        title.setStyleSheet(
            f"color: {_TEXT}; font-size: 18px; font-weight: bold;"
            f"background: transparent; font-family: 'Segoe UI';"
        )
        header_layout.addWidget(title)
        header_layout.addStretch()

        # Summary labels (right side of header)
        self._summary_label = QLabel("")
        self._summary_label.setStyleSheet(
            f"color: {_TEXT_DIM}; font-size: 13px; font-family: 'Segoe UI';"
            f"background: transparent; margin-right: 8px;"
        )
        header_layout.addWidget(self._summary_label)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.setFixedWidth(90)
        refresh_btn.setStyleSheet(_BTN_GREEN)
        refresh_btn.clicked.connect(self._on_search)
        header_layout.addWidget(refresh_btn)

        root.addWidget(header)

        # -- Filter bar --
        filter_bar = QWidget()
        filter_bar.setStyleSheet(
            f"background-color: {_SURFACE}; border-bottom: 1px solid {_BORDER};"
        )
        fl = QHBoxLayout(filter_bar)
        fl.setContentsMargins(16, 8, 16, 8)
        fl.setSpacing(8)

        # Item Name
        fl.addWidget(self._flbl("Item Name"))
        self._item_edit = QLineEdit()
        self._item_edit.setPlaceholderText("Search item name")
        self._item_edit.setFixedWidth(160)
        self._item_edit.setStyleSheet(_EDIT_STYLE)
        fl.addWidget(self._item_edit)

        # Batch No
        fl.addWidget(self._flbl("Batch No"))
        self._batch_edit = QLineEdit()
        self._batch_edit.setPlaceholderText("Search batch")
        self._batch_edit.setFixedWidth(120)
        self._batch_edit.setStyleSheet(_EDIT_STYLE)
        fl.addWidget(self._batch_edit)

        # Company
        fl.addWidget(self._flbl("Company"))
        self._company_combo = QComboBox()
        self._company_combo.setFixedWidth(160)
        self._company_combo.setStyleSheet(_COMBO_STYLE)
        self._company_combo.addItem("All Companies", None)
        for c in CompanyDAO.get_all():
            self._company_combo.addItem(c["company_name"], c["id"])
        fl.addWidget(self._company_combo)

        # Stock Status
        fl.addWidget(self._flbl("Status"))
        self._status_combo = QComboBox()
        self._status_combo.setFixedWidth(120)
        self._status_combo.setStyleSheet(_COMBO_STYLE)
        self._status_combo.addItems(["All", "In Stock", "Low Stock", "Out of Stock", "Expired"])
        fl.addWidget(self._status_combo)

        # Buttons
        search_btn = QPushButton("Search")
        search_btn.setFixedWidth(90)
        search_btn.setStyleSheet(_BTN_GREEN)
        search_btn.clicked.connect(self._on_search)
        fl.addWidget(search_btn)

        clear_btn = QPushButton("Clear")
        clear_btn.setFixedWidth(90)
        clear_btn.setStyleSheet(_BTN_GRAY)
        clear_btn.clicked.connect(self._on_clear)
        fl.addWidget(clear_btn)

        fl.addStretch()
        root.addWidget(filter_bar)

        # -- Table --
        self._table = QTableWidget()
        self._table.setColumnCount(11)
        self._table.setHorizontalHeaderLabels([
            "Item Name", "Company", "Unit", "Pack Size", "Batch No",
            "Expiry", "MRP", "Purchase Rate", "Net Rate", "Stock Qty", "Reorder Level"
        ])
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(True)
        self._table.setAlternatingRowColors(False)
        self._table.setSortingEnabled(True)

        header_view = self._table.horizontalHeader()
        header_view.setStretchLastSection(True)
        header_view.setSectionResizeMode(0, QHeaderView.Stretch)
        for col in range(1, 11):
            header_view.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        header_view.setStyleSheet(
            f"QHeaderView::section {{"
            f"  background-color: {_SURFACE}; color: {_TEXT};"
            f"  border: none; border-bottom: 2px solid {_ACCENT};"
            f"  padding: 4px 8px; font-weight: bold; font-size: 9pt;"
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
            f"QTableWidget::item {{ padding: 2px 6px; }}"
        )

        root.addWidget(self._table, 1)

        # Load initial data
        self._on_search()

    def _flbl(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color: {_TEXT_DIM}; font-size: 13px; font-family: 'Segoe UI';"
            f"background: transparent;"
        )
        return lbl

    def _on_search(self):
        item_name = self._item_edit.text().strip()
        batch_no = self._batch_edit.text().strip()
        company_id = self._company_combo.currentData()
        status = self._status_combo.currentText()

        rows = StockDAO.search(
            item_name=item_name,
            batch_no=batch_no,
            company_id=company_id,
            stock_status=status,
        )
        self._refresh_table(rows)

    def _on_clear(self):
        self._item_edit.clear()
        self._batch_edit.clear()
        self._company_combo.setCurrentIndex(0)
        self._status_combo.setCurrentIndex(0)
        self._on_search()

    def _refresh_table(self, rows: list[dict]):
        self._table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            self._table.setItem(i, 0, QTableWidgetItem(r.get("item_name", "") or ""))
            self._table.setItem(i, 1, QTableWidgetItem(r.get("company_name", "") or ""))
            self._table.setItem(i, 2, QTableWidgetItem(r.get("unit_name", "") or ""))
            self._table.setItem(i, 3, QTableWidgetItem(r.get("pack_size", "") or ""))
            self._table.setItem(i, 4, QTableWidgetItem(r.get("batch_no", "") or ""))
            self._table.setItem(i, 5, QTableWidgetItem(r.get("expiry", "") or ""))

            mrp_item = QTableWidgetItem()
            mrp_item.setData(Qt.DisplayRole, f"{r.get('mrp', 0.0):.2f}")
            mrp_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._table.setItem(i, 6, mrp_item)

            pr_item = QTableWidgetItem()
            pr_item.setData(Qt.DisplayRole, f"{r.get('purchase_rate', 0.0):.2f}")
            pr_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._table.setItem(i, 7, pr_item)

            nr_item = QTableWidgetItem()
            nr_item.setData(Qt.DisplayRole, f"{r.get('net_rate', 0.0):.2f}")
            nr_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._table.setItem(i, 8, nr_item)

            qty = r.get("stock_qty", 0.0)
            qty_item = QTableWidgetItem()
            qty_item.setData(Qt.DisplayRole, f"{qty:.2f}")
            qty_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            if qty <= 0:
                qty_item.setForeground(Qt.red)
            elif qty <= r.get("reorder_stock_level", 0):
                from PySide6.QtGui import QColor
                qty_item.setForeground(QColor("#b26a00"))
            self._table.setItem(i, 9, qty_item)

            reorder_item = QTableWidgetItem()
            reorder_item.setData(Qt.DisplayRole, str(r.get("reorder_stock_level", 0)))
            reorder_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._table.setItem(i, 10, reorder_item)

        # Update summary
        summary = StockDAO.get_summary(rows)
        self._summary_label.setText(
            f"Batches: {summary['total_batches']}  |  "
            f"Qty: {summary['total_qty']:.0f}  |  "
            f"Value: {summary['total_value']:.2f}"
        )
