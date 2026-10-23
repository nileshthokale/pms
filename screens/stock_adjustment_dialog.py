"""Stock Adjustment dialog for Pharmacy Management System.

Matches the Pharma-WINNER Stock Adjustment workflow:
- Medicine search with SearchableComboBox (autocomplete, no unwanted placeholder entries)
- Batch selection retaining actual database batch ID and item ID
- Auto-populates PackSize, Item Stock, Batch Stock, Expiry, MRP, Rate, Tax, Net Rate
- Supports positive and negative quantity adjustments in loose units (+2, -1)
- Supports New Adjustment and Edit Adjustment modes
- Real-time projected stock display and strict negative-stock rejection
- Atomic SQLite transaction and audit record creation / reconciliation
- Immediate stock refresh in Counter Sale and duplicate-click protection
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Optional

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
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

from database.connection import get_connection
from database.stock_dao import StockDAO
from database.stock_adjustment_dao import StockAdjustmentDAO, StockAdjustmentError
from ui.components import FONT_FAMILY, SearchableComboBox
from ui.theme import (
    TYPE_BUTTON,
    TYPE_FORM_LABEL,
    TYPE_HINT,
    TYPE_INPUT,
    TYPE_PAGE_TITLE,
    palette,
)


def _format_expiry_display(expiry: str) -> str:
    """Format expiry as MM-YYYY matching Pharma-WINNER reference."""
    if not expiry:
        return ""
    exp = str(expiry).strip()
    m_iso = re.match(r"^(\d{4})-(\d{1,2})(?:-\d{1,2})?$", exp)
    if m_iso:
        return f"{int(m_iso.group(2)):02d}-{m_iso.group(1)}"
    m_slash = re.match(r"^(\d{1,2})/(\d{2,4})$", exp)
    if m_slash:
        year = m_slash.group(2)
        if len(year) == 2:
            year = f"20{year}"
        return f"{int(m_slash.group(1)):02d}-{year}"
    return exp


_BUTTON_SECONDARY_STYLE = (
    "QPushButton { background-color: #374151; color: #ffffff; border: 1px solid #4B5563; "
    "border-radius: 3px; font-size: 13px; font-weight: bold; padding: 4px 10px; }"
    "QPushButton:hover { background-color: #4B5563; }"
)


class StockAdjustmentDialog(QDialog):
    """Stock Adjustment dialog matching Pharma-WINNER reference."""

    adjustment_saved = Signal(int, int, float, float)  # item_id, batch_id, adjusted_qty, resulting_qty

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        item_id: Optional[int] = None,
        stock_batch_id: Optional[int] = None,
        edit_adjustment_id: Optional[int] = None,
    ):
        super().__init__(parent)
        self._edit_adjustment_id = edit_adjustment_id
        self._edit_adj_data: dict[str, Any] | None = None
        self.setWindowTitle("Edit Stock Adjustment" if edit_adjustment_id else "Stock Adjustment")
        self.setMinimumWidth(1020)
        self.resize(1080, 310)
        self.setModal(True)

        self._initial_item_id = item_id
        self._initial_batch_id = stock_batch_id
        self._items_list: list[dict[str, Any]] = []
        self._batches: list[dict[str, Any]] = []
        self._batches_by_id: dict[int, dict[str, Any]] = {}
        self._stock_summary: dict[str, Any] | None = None
        self._is_saving = False

        self._init_ui()
        self._load_items()

        # If editing an existing adjustment, load it and lock selectors
        if self._edit_adjustment_id is not None:
            self._load_edit_adjustment(self._edit_adjustment_id)
        elif self._initial_item_id is not None:
            self.item_combo.set_selected_id(self._initial_item_id)
            if self._initial_batch_id is not None:
                self.batch_combo.set_selected_id(self._initial_batch_id)

    def _init_ui(self):
        p = palette()
        self.setStyleSheet(
            f"QDialog {{ background-color: {p['surface']}; color: {p['text']}; font-family: {FONT_FAMILY}; }}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(8)

        # Title / Banner
        title_bar = QHBoxLayout()
        title_text = "Edit Stock Adjustment" if self._edit_adjustment_id else "Stock Adjustment"
        self._title_lbl = QLabel(title_text)
        self._title_lbl.setStyleSheet(
            f"font-size: {TYPE_PAGE_TITLE}px; font-weight: bold; color: {p['accent']};"
        )
        title_bar.addWidget(self._title_lbl)
        title_bar.addStretch()
        root.addLayout(title_bar)

        # Main Fields Card
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background-color: {p['surface_alt']}; border: 1px solid {p['border']}; border-radius: 4px; padding: 4px; }}"
        )
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(10, 8, 10, 8)
        card_layout.setSpacing(8)

        # Row 1: Item Name with wide SearchableComboBox and Hist button
        row1 = QHBoxLayout()
        row1.setSpacing(8)

        lbl_item = QLabel("* Item Name:")
        lbl_item.setStyleSheet(f"font-weight: bold; font-size: {TYPE_FORM_LABEL}px; color: {p['text']};")
        row1.addWidget(lbl_item)

        self.item_combo = SearchableComboBox(
            placeholder="Type medicine name to search...",
            min_width=450,
            allow_width_expansion=True,
        )
        self.item_combo.setFixedHeight(30)
        self.item_combo.selection_changed.connect(self._on_item_selected)
        row1.addWidget(self.item_combo, 1)

        self.btn_hist = QPushButton("Hist")
        self.btn_hist.setToolTip("View recent adjustment history for this medicine")
        self.btn_hist.setFixedWidth(55)
        self.btn_hist.setFixedHeight(30)
        self.btn_hist.setStyleSheet(
            f"QPushButton {{ background-color: {p['surface']}; color: {p['text']}; border: 1px solid {p['border']}; "
            f"border-radius: 2px; padding: 3px 6px; font-size: {TYPE_BUTTON}px; font-weight: bold; }}"
            f"QPushButton:hover {{ background-color: {p['selected']}; color: {p['selected_text']}; }}"
        )
        self.btn_hist.clicked.connect(self._show_history_popup)
        row1.addWidget(self.btn_hist)

        row1.addSpacing(10)
        lbl_mode = QLabel("Mode:")
        lbl_mode.setStyleSheet(f"font-weight: bold; font-size: {TYPE_FORM_LABEL}px; color: {p['text']};")
        row1.addWidget(lbl_mode)

        self.op_filter = QComboBox()
        self.op_filter.addItems([
            "All Active Batches",
            "Stock Removal (-)",
            "Stock Addition (+)",
            "Write-Off Expired Stock",
        ])
        self.op_filter.setFixedHeight(30)
        self.op_filter.setMinimumWidth(160)
        self.op_filter.setStyleSheet(
            f"QComboBox {{ background-color: {p['surface']}; color: {p['text']}; border: 1px solid {p['border']}; "
            f"padding: 2px 8px; font-size: {TYPE_INPUT}px; border-radius: 2px; }}"
        )
        self.op_filter.currentIndexChanged.connect(self._on_filter_changed)
        row1.addWidget(self.op_filter)

        self.show_expired_cb = QCheckBox("Show Expired (Write-Off)")
        self.show_expired_cb.setStyleSheet(f"font-size: {TYPE_FORM_LABEL}px; color: {p['text']};")
        self.show_expired_cb.stateChanged.connect(self._on_show_expired_toggled)
        row1.addWidget(self.show_expired_cb)

        card_layout.addLayout(row1)

        # Row 2: Grid of all batch and stock details
        # Matching Pharma-WINNER horizontal arrangement:
        # PackSize | Item Stock | Batch # | Batch Stock | Qty (+/-) | Expiry | MRP | Rate | Tax | Net Rate
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(3)

        col = 0
        # 1. PackSize
        grid.addWidget(self._create_header_label("PackSize"), 0, col)
        self.pack_edit = self._create_readonly_edit()
        self.pack_edit.setFixedWidth(70)
        self.pack_edit.setAlignment(Qt.AlignCenter)
        grid.addWidget(self.pack_edit, 1, col)
        col += 1

        # 2. Item Stock
        grid.addWidget(self._create_header_label("Item Stock"), 0, col)
        self.item_stock_edit = self._create_readonly_edit()
        self.item_stock_edit.setFixedWidth(80)
        self.item_stock_edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        grid.addWidget(self.item_stock_edit, 1, col)
        col += 1

        # 3. Batch # (Searchable Dropdown)
        grid.addWidget(self._create_header_label("Batch #"), 0, col)
        self.batch_combo = SearchableComboBox(
            placeholder="Select Batch...",
            min_width=350,
            allow_width_expansion=True,
        )
        self.batch_combo.setFixedHeight(30)
        self.batch_combo.setMinimumWidth(260)
        self.batch_combo.selection_changed.connect(self._on_batch_selected)

        # Wrap set_selected_id so that if an expired batch ID is targeted, write-off mode is automatically enabled
        _orig_batch_set_id = self.batch_combo.set_selected_id
        def _wrapped_batch_set_id(bid: Any):
            if bid is not None and isinstance(bid, int) and bid in self._batches_by_id:
                b_info = self._batches_by_id[bid]
                if (b_info.get("is_expired") or not b_info.get("is_valid_expiry")) and hasattr(self, "show_expired_cb") and not self.show_expired_cb.isChecked():
                    self.show_expired_cb.blockSignals(True)
                    self.show_expired_cb.setChecked(True)
                    self.show_expired_cb.blockSignals(False)
                    self._populate_batch_dropdown(select_batch_id=bid)
                    return
            _orig_batch_set_id(bid)
        self.batch_combo.set_selected_id = _wrapped_batch_set_id

        grid.addWidget(self.batch_combo, 1, col)
        col += 1

        # 4. Batch Stock
        grid.addWidget(self._create_header_label("Batch Stock"), 0, col)
        self.batch_stock_edit = self._create_readonly_edit()
        self.batch_stock_edit.setFixedWidth(80)
        self.batch_stock_edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        grid.addWidget(self.batch_stock_edit, 1, col)
        col += 1

        # 5. Qty (+/-) (Yellow Highlighted Editable Box)
        lbl_qty = self._create_header_label("Qty (+/-)")
        lbl_qty.setStyleSheet(f"font-weight: bold; font-size: {TYPE_FORM_LABEL}px; color: {p['accent']};")
        grid.addWidget(lbl_qty, 0, col)
        self.qty_edit = QLineEdit()
        self.qty_edit.setPlaceholderText("+2 / -1")
        self.qty_edit.setFixedWidth(85)
        self.qty_edit.setFixedHeight(30)
        self.qty_edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        is_dark = p.get("is_dark", False)
        qty_bg = "#453805" if is_dark else "#FFFFCC"
        qty_fg = "#FFFFFF" if is_dark else "#000000"
        self.qty_edit.setStyleSheet(
            f"QLineEdit {{ background-color: {qty_bg}; color: {qty_fg}; border: 2px solid {p['accent']}; "
            f"font-size: {TYPE_INPUT + 1}px; font-weight: bold; padding: 2px 6px; border-radius: 2px; }}"
        )
        self.qty_edit.textChanged.connect(self._update_projected_stock)
        self.qty_edit.returnPressed.connect(self._on_save)
        grid.addWidget(self.qty_edit, 1, col)
        col += 1

        # 6. Expiry
        grid.addWidget(self._create_header_label("Expiry"), 0, col)
        self.expiry_edit = self._create_readonly_edit()
        self.expiry_edit.setFixedWidth(80)
        self.expiry_edit.setAlignment(Qt.AlignCenter)
        grid.addWidget(self.expiry_edit, 1, col)
        col += 1

        # 7. MRP
        grid.addWidget(self._create_header_label("MRP"), 0, col)
        self.mrp_edit = self._create_readonly_edit()
        self.mrp_edit.setFixedWidth(80)
        self.mrp_edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        grid.addWidget(self.mrp_edit, 1, col)
        col += 1

        # 8. Rate (Purchase Rate)
        grid.addWidget(self._create_header_label("Rate"), 0, col)
        self.rate_edit = self._create_readonly_edit()
        self.rate_edit.setFixedWidth(80)
        self.rate_edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        grid.addWidget(self.rate_edit, 1, col)
        col += 1

        # 9. Tax
        grid.addWidget(self._create_header_label("Tax"), 0, col)
        self.tax_edit = self._create_readonly_edit()
        self.tax_edit.setFixedWidth(65)
        self.tax_edit.setAlignment(Qt.AlignCenter)
        grid.addWidget(self.tax_edit, 1, col)
        col += 1

        # 10. Net Rate
        grid.addWidget(self._create_header_label("Net Rate"), 0, col)
        self.net_rate_edit = self._create_readonly_edit()
        self.net_rate_edit.setFixedWidth(80)
        self.net_rate_edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        grid.addWidget(self.net_rate_edit, 1, col)

        card_layout.addLayout(grid)

        # Row 3: Live Projected Stock strip & Reason field
        row3 = QHBoxLayout()
        row3.setSpacing(12)

        self.projected_label = QLabel("Select a medicine and batch to adjust stock.")
        self.projected_label.setStyleSheet(
            f"font-size: {TYPE_FORM_LABEL}px; font-weight: bold; color: {p['text_dim']};"
        )
        row3.addWidget(self.projected_label)
        row3.addStretch()

        lbl_reason = QLabel("Reason:")
        lbl_reason.setStyleSheet(f"font-size: {TYPE_FORM_LABEL}px; color: {p['text']};")
        row3.addWidget(lbl_reason)

        self.reason_edit = QLineEdit()
        self.reason_edit.setPlaceholderText("Optional (e.g. Physical count, Damage)")
        self.reason_edit.setFixedWidth(280)
        self.reason_edit.setFixedHeight(28)
        self.reason_edit.setStyleSheet(
            f"QLineEdit {{ background-color: {p['surface']}; color: {p['text']}; border: 1px solid {p['border']}; padding: 3px 6px; font-size: {TYPE_INPUT}px; }}"
        )
        self.reason_edit.returnPressed.connect(self._on_save)
        row3.addWidget(self.reason_edit)

        card_layout.addLayout(row3)

        # Stock Breakdown info label (visible when active vs expired inventory differs)
        self.stock_breakdown_lbl = QLabel("")
        self.stock_breakdown_lbl.setStyleSheet(f"font-size: 12px; color: {p['text_dim']}; font-style: italic;")
        self.stock_breakdown_lbl.setVisible(False)
        card_layout.addWidget(self.stock_breakdown_lbl)

        # Row 4: Safe Physical Stock Reconciliation & Movement Audit
        row4 = QHBoxLayout()
        row4.setSpacing(10)

        lbl_phys = QLabel("Physical Count:")
        lbl_phys.setStyleSheet(f"font-size: {TYPE_FORM_LABEL}px; font-weight: bold; color: {p['accent']};")
        row4.addWidget(lbl_phys)

        self.phys_count_edit = QLineEdit()
        self.phys_count_edit.setPlaceholderText("e.g. 230")
        self.phys_count_edit.setFixedWidth(110)
        self.phys_count_edit.setFixedHeight(28)
        self.phys_count_edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.phys_count_edit.setStyleSheet(
            f"QLineEdit {{ background-color: {p['surface']}; color: {p['text']}; border: 1px solid {p['accent']}; padding: 2px 6px; font-size: {TYPE_INPUT}px; font-weight: bold; }}"
        )
        self.phys_count_edit.textChanged.connect(self._on_physical_count_changed)
        row4.addWidget(self.phys_count_edit)

        self.btn_reconcile = QPushButton("Reconcile Difference")
        self.btn_reconcile.setToolTip("Calculate variance between physical count and book stock, and apply to Qty (+/-)")
        self.btn_reconcile.setFixedHeight(28)
        self.btn_reconcile.setStyleSheet(
            f"QPushButton {{ background-color: {p['surface']}; color: {p['text']}; border: 1px solid {p['border']}; border-radius: 2px; padding: 2px 10px; font-size: {TYPE_BUTTON}px; font-weight: bold; }}"
            f"QPushButton:hover {{ background-color: {p['selected']}; color: {p['selected_text']}; }}"
        )
        self.btn_reconcile.clicked.connect(self._on_apply_physical_reconciliation)
        row4.addWidget(self.btn_reconcile)

        self.btn_write_off = QPushButton("Zero-Out / Write-Off")
        self.btn_write_off.setToolTip("Write off the selected batch to 0 (for expired or disposed stock)")
        self.btn_write_off.setFixedHeight(28)
        self.btn_write_off.setStyleSheet(
            f"QPushButton {{ background-color: {p['surface']}; color: #DC2626; border: 1px solid #DC2626; border-radius: 2px; padding: 2px 10px; font-size: {TYPE_BUTTON}px; font-weight: bold; }}"
            f"QPushButton:hover {{ background-color: #DC2626; color: #ffffff; }}"
        )
        self.btn_write_off.clicked.connect(self._on_write_off_batch)
        row4.addWidget(self.btn_write_off)

        self.btn_new_batch = QPushButton("+ New Batch")
        self.btn_new_batch.setToolTip("Create a new stock batch for this medicine to add stock")
        self.btn_new_batch.setFixedHeight(28)
        self.btn_new_batch.setStyleSheet(
            f"QPushButton {{ background-color: {p['surface']}; color: {p['accent']}; border: 1px solid {p['accent']}; border-radius: 2px; padding: 2px 10px; font-size: {TYPE_BUTTON}px; font-weight: bold; }}"
            f"QPushButton:hover {{ background-color: {p['accent']}; color: #ffffff; }}"
        )
        self.btn_new_batch.clicked.connect(self._on_create_new_batch)
        row4.addWidget(self.btn_new_batch)

        self.btn_movement = QPushButton("Movement Ledger")
        self.btn_movement.setToolTip("View authoritative transaction ledger (purchases, sales, returns, adjustments) for this batch")
        self.btn_movement.setFixedHeight(28)
        self.btn_movement.setStyleSheet(
            f"QPushButton {{ background-color: {p['surface']}; color: {p['text']}; border: 1px solid {p['border']}; border-radius: 2px; padding: 2px 10px; font-size: {TYPE_BUTTON}px; }}"
            f"QPushButton:hover {{ background-color: {p['selected']}; color: {p['selected_text']}; }}"
        )
        self.btn_movement.clicked.connect(self._show_movement_dialog)
        row4.addWidget(self.btn_movement)

        row4.addStretch()
        self.reconcile_status_lbl = QLabel("")
        self.reconcile_status_lbl.setStyleSheet("font-size: 12px; font-weight: bold;")
        row4.addWidget(self.reconcile_status_lbl)

        card_layout.addLayout(row4)
        root.addWidget(card)

        # Action Buttons (Bottom Right)
        btn_bar = QHBoxLayout()
        btn_bar.addStretch()

        self.save_btn = QPushButton("Save")
        self.save_btn.setFixedWidth(100)
        self.save_btn.setFixedHeight(32)
        self.save_btn.setStyleSheet(
            f"QPushButton {{ background-color: {p['accent']}; color: #ffffff; border: 1px solid {p['accent']}; "
            f"border-radius: 3px; font-weight: bold; font-size: {TYPE_BUTTON}px; }}"
            f"QPushButton:hover {{ background-color: {p['selected']}; }}"
            f"QPushButton:disabled {{ background-color: {p['disabled_bg']}; color: {p['disabled_text']}; border: 1px solid {p['border']}; }}"
        )
        self.save_btn.clicked.connect(self._on_save)
        btn_bar.addWidget(self.save_btn)

        self.close_btn = QPushButton("Close")
        self.close_btn.setFixedWidth(90)
        self.close_btn.setFixedHeight(32)
        self.close_btn.setStyleSheet(
            f"QPushButton {{ background-color: {p['surface_alt']}; color: {p['text']}; border: 1px solid {p['border']}; "
            f"border-radius: 3px; font-size: {TYPE_BUTTON}px; }}"
            f"QPushButton:hover {{ background-color: {p['selected']}; color: {p['selected_text']}; }}"
        )
        self.close_btn.clicked.connect(self.reject)
        btn_bar.addWidget(self.close_btn)

        root.addLayout(btn_bar)

    def _create_header_label(self, text: str) -> QLabel:
        p = palette()
        lbl = QLabel(text)
        lbl.setStyleSheet(f"font-size: {TYPE_HINT}px; font-weight: bold; color: {p['text_dim']};")
        lbl.setAlignment(Qt.AlignCenter)
        return lbl

    def _create_readonly_edit(self) -> QLineEdit:
        p = palette()
        edit = QLineEdit()
        edit.setReadOnly(True)
        edit.setFixedHeight(30)
        edit.setFocusPolicy(Qt.NoFocus)
        edit.setStyleSheet(
            f"QLineEdit {{ background-color: {p['disabled_bg']}; color: {p['text']}; "
            f"border: 1px solid {p['border']}; padding: 3px 6px; font-size: {TYPE_INPUT}px; }}"
        )
        return edit

    def _load_items(self):
        """Load all medicines from items table into the search combo."""
        conn = get_connection()
        try:
            cur = conn.execute(
                """
                SELECT id, item_name, COALESCE(pack_size, '1') AS pack_size
                FROM items
                ORDER BY item_name COLLATE NOCASE ASC
                """
            )
            self._items_list = [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

        items = []
        for it in self._items_list:
            display = f"{it['item_name']} [Pack: {it['pack_size']}]"
            items.append((display, int(it["id"]), str(it["item_name"])))

        self.item_combo.populate(items)

    def _load_edit_adjustment(self, adjustment_id: int):
        """Load an existing adjustment into the form for editing."""
        adj = StockAdjustmentDAO.get_by_id(adjustment_id)
        if not adj:
            QMessageBox.warning(self, "Error", f"Stock adjustment record {adjustment_id} not found.")
            QTimer.singleShot(0, self.reject)
            return

        self._edit_adj_data = adj
        item_id = int(adj["item_id"])
        batch_id = int(adj["stock_batch_id"])

        self.item_combo.set_selected_id(item_id)
        self.item_combo.setEnabled(False)  # Lock item in edit mode

        self.batch_combo.set_selected_id(batch_id)
        self.batch_combo.setEnabled(False)  # Lock batch in edit mode

        self.qty_edit.setText(f"{float(adj['adjusted_qty']):g}")
        self.reason_edit.setText(str(adj.get("reason", "") or ""))

        self._update_projected_stock()

    def _select_item_by_id(self, item_id: int):
        self.item_combo.set_selected_id(item_id)

    def _select_batch_by_id(self, batch_id: int):
        if batch_id in self._batches_by_id:
            b_info = self._batches_by_id[batch_id]
            if (b_info.get("is_expired") or not b_info.get("is_valid_expiry")) and hasattr(self, "show_expired_cb") and not self.show_expired_cb.isChecked():
                self.show_expired_cb.blockSignals(True)
                self.show_expired_cb.setChecked(True)
                self.show_expired_cb.blockSignals(False)
                self._populate_batch_dropdown(select_batch_id=batch_id)
                return
        self.batch_combo.set_selected_id(batch_id)

    def _on_item_selected(self, item_id: Any):
        """Called when a medicine is chosen from the SearchableComboBox."""
        if item_id is None:
            self._clear_all_fields()
            return
        self._load_batches_for_item(int(item_id))

    def _load_batches_for_item(self, item_id: int):
        """Load batches for the selected medicine into batch_combo based on active mode."""
        summary = StockDAO.get_item_stock_summary(item_id)
        self._stock_summary = summary
        self._batches = summary["batches"]
        self._batches_by_id = {int(b["id"]): b for b in self._batches}

        # Item Stock: Display verified eligible (active saleable) stock under verified unit conventions
        eligible_stock = summary["eligible_stock"]
        expired_stock = summary["expired_stock"]
        total_book = summary["total_book_stock"]

        self.item_stock_edit.setText(f"{int(eligible_stock) if eligible_stock.is_integer() else eligible_stock:g}")
        if expired_stock > 0:
            self.item_stock_edit.setToolTip(
                f"Eligible (Active) Stock: {eligible_stock:g} tablets\n"
                f"Expired/Write-Off in DB: {expired_stock:g} tablets ({summary['expired_batch_count']} batches)\n"
                f"Total Book Stock: {total_book:g} tablets"
            )
            self.stock_breakdown_lbl.setText(
                f"[!] Active Eligible: {eligible_stock:g} | Expired/Write-Off in DB: {expired_stock:g} ({summary['expired_batch_count']} batches) | Total Book: {total_book:g}"
            )
            self.stock_breakdown_lbl.setStyleSheet("font-size: 12px; color: #D97706; font-weight: bold;")
            self.stock_breakdown_lbl.setVisible(True)
        else:
            self.item_stock_edit.setToolTip(f"Total Eligible Stock: {eligible_stock:g} tablets")
            self.stock_breakdown_lbl.setVisible(False)

        self._populate_batch_dropdown()

    def _on_filter_changed(self):
        if not hasattr(self, "op_filter"):
            return
        mode = self.op_filter.currentText()
        if mode == "Write-Off Expired Stock":
            if hasattr(self, "show_expired_cb") and not self.show_expired_cb.isChecked():
                self.show_expired_cb.blockSignals(True)
                self.show_expired_cb.setChecked(True)
                self.show_expired_cb.blockSignals(False)
        else:
            if hasattr(self, "show_expired_cb") and self.show_expired_cb.isChecked():
                self.show_expired_cb.blockSignals(True)
                self.show_expired_cb.setChecked(False)
                self.show_expired_cb.blockSignals(False)
        self._populate_batch_dropdown()

    def _on_show_expired_toggled(self, state: int):
        if not hasattr(self, "op_filter") or not hasattr(self, "show_expired_cb"):
            return
        if self.show_expired_cb.isChecked():
            idx = self.op_filter.findText("Write-Off Expired Stock")
            if idx >= 0:
                self.op_filter.blockSignals(True)
                self.op_filter.setCurrentIndex(idx)
                self.op_filter.blockSignals(False)
        else:
            idx = self.op_filter.findText("All Active Batches")
            if idx >= 0:
                self.op_filter.blockSignals(True)
                self.op_filter.setCurrentIndex(idx)
                self.op_filter.blockSignals(False)
        self._populate_batch_dropdown()

    def _populate_batch_dropdown(self, select_batch_id: Optional[int] = None):
        """Populate batch_combo with filtered batches according to active mode."""
        if not self._batches:
            self.batch_combo.populate([("No batches found for this medicine", None, "")])
            self.batch_combo.setCurrentIndex(0)
            self._clear_batch_fields()
            self.projected_label.setText("This medicine has no existing stock batches.")
            self.projected_label.setStyleSheet("color: #D97706; font-weight: bold;")
            return

        mode = self.op_filter.currentText() if hasattr(self, "op_filter") else "All Active Batches"
        include_expired = (
            (hasattr(self, "show_expired_cb") and self.show_expired_cb.isChecked())
            or (mode == "Write-Off Expired Stock")
        )

        if include_expired:
            # Expired or invalid expiry batches for disposal / write-off
            filtered = [
                b for b in self._batches
                if b.get("is_expired") or not b.get("is_valid_expiry")
            ]
            empty_msg = "No expired batches found for write-off"
        elif mode == "Stock Removal (-)":
            # Active unexpired batches with stock available to remove
            filtered = [
                b for b in self._batches
                if b.get("is_unexpired") and float(b.get("stock_qty") or 0.0) > 0.0
            ]
            empty_msg = "No active batches with available stock"
        elif mode == "Stock Addition (+)":
            # Active unexpired batches (both positive stock and zero stock can receive stock)
            filtered = [
                b for b in self._batches
                if b.get("is_unexpired")
            ]
            empty_msg = "No eligible unexpired batches found"
        else:
            # "All Active Batches" (Default): Active valid unexpired batches only
            filtered = [
                b for b in self._batches
                if b.get("is_unexpired")
            ]
            empty_msg = "No active unexpired batches found"

        if not filtered:
            self.batch_combo.populate([(empty_msg, None, "")])
            self.batch_combo.setCurrentIndex(0)
            self._clear_batch_fields()
            p = palette()
            self.projected_label.setText(empty_msg)
            self.projected_label.setStyleSheet(f"color: {p['text_dim']}; font-weight: bold;")
            return

        batch_items = []
        for b in filtered:
            b_no = str(b.get("batch_no") or "").strip() or "-"
            # User requirement: Batch box shows ONLY the batch number (no expiry, no MRP)
            batch_items.append((b_no, int(b["id"]), b_no))

        self.batch_combo.populate(batch_items)

        # Handle initial or explicit selection
        target_id = select_batch_id
        if target_id is None and self._initial_batch_id is not None:
            target_id = self._initial_batch_id
            self._initial_batch_id = None
            if target_id in self._batches_by_id:
                b_info = self._batches_by_id[target_id]
                if (b_info.get("is_expired") or not b_info.get("is_valid_expiry")) and not include_expired:
                    if hasattr(self, "show_expired_cb"):
                        self.show_expired_cb.blockSignals(True)
                        self.show_expired_cb.setChecked(True)
                        self.show_expired_cb.blockSignals(False)
                    self._populate_batch_dropdown(select_batch_id=target_id)
                    return

        if target_id is not None and target_id in self._batches_by_id:
            self.batch_combo.set_selected_id(target_id)
        else:
            # Do NOT auto-select batch when selecting a medicine.
            # Batch field remains empty until the user explicitly chooses a batch.
            self.batch_combo.clear_selection()
            self._clear_batch_fields()
            p = palette()
            self.projected_label.setText("Select a batch to adjust stock.")
            self.projected_label.setStyleSheet(f"color: {p['text_dim']}; font-weight: bold;")

    def _on_batch_selected(self, batch_id: Any):
        """Called when a batch is chosen from the SearchableComboBox."""
        if batch_id is None or int(batch_id) not in self._batches_by_id:
            self._clear_batch_fields()
            return

        b = self._batches_by_id[int(batch_id)]
        b_no = str(b.get("batch_no") or "").strip() or "-"
        exp = _format_expiry_display(b.get("expiry") or "")
        mrp = float(b.get("mrp") or 0.0)

        # Batch box displays ONLY the batch number
        line = self.batch_combo.lineEdit()
        if line is not None and line.text() != b_no:
            line.setText(b_no)
            line.setCursorPosition(0)

        self.batch_combo.setToolTip(f"Batch: {b_no} | Exp: {exp} | MRP: {mrp:.2f}")

        self.pack_edit.setText(str(b.get("pack_size") or "1"))
        qty = float(b.get("stock_qty") or 0.0)
        self.batch_stock_edit.setText(f"{int(qty) if qty.is_integer() else qty:g}")
        self.expiry_edit.setText(exp)
        self.mrp_edit.setText(f"{mrp:.2f}")
        self.rate_edit.setText(f"{float(b.get('purchase_rate') or 0.0):.2f}")
        self.tax_edit.setText(f"{float(b.get('tax_percent') or 0.0):.2f}%")
        self.net_rate_edit.setText(f"{float(b.get('net_rate') or 0.0):.2f}")

        # Update styling based on expiry
        p = palette()
        if b.get("is_expired") or not b.get("is_valid_expiry"):
            exp_text = "EXPIRED" if b.get("is_expired") else "INVALID EXPIRY"
            self.batch_stock_edit.setToolTip(f"[!] This batch is {exp_text}. Use adjustment to write off.")
            self.batch_stock_edit.setStyleSheet(
                f"QLineEdit {{ background-color: #7F1D1D; color: #FECACA; border: 1px solid #DC2626; padding: 3px 6px; font-weight: bold; font-size: {TYPE_INPUT}px; }}"
            )
        else:
            self.batch_stock_edit.setToolTip(f"Current stored stock: {qty:g} loose units")
            self.batch_stock_edit.setStyleSheet(
                f"QLineEdit {{ background-color: {p['disabled_bg']}; color: {p['text']}; border: 1px solid {p['border']}; padding: 3px 6px; font-size: {TYPE_INPUT}px; }}"
            )

        self._update_projected_stock()
        self._on_physical_count_changed()
        QTimer.singleShot(50, self.qty_edit.setFocus)

    def _clear_batch_fields(self):
        self.pack_edit.clear()
        self.batch_stock_edit.clear()
        self.expiry_edit.clear()
        self.mrp_edit.clear()
        self.rate_edit.clear()
        self.tax_edit.clear()
        self.net_rate_edit.clear()
        if hasattr(self, "phys_count_edit"):
            self.phys_count_edit.clear()
        if hasattr(self, "reconcile_status_lbl"):
            self.reconcile_status_lbl.clear()
        self._update_projected_stock()

    def _clear_all_fields(self):
        self.item_stock_edit.clear()
        self.batch_combo.clear()
        self._batches.clear()
        self._batches_by_id.clear()
        self._stock_summary = None
        if hasattr(self, "stock_breakdown_lbl"):
            self.stock_breakdown_lbl.setVisible(False)
        self._clear_batch_fields()

    def _on_physical_count_changed(self):
        """Update variance calculation in real time as physical count is entered."""
        if not hasattr(self, "phys_count_edit") or not hasattr(self, "reconcile_status_lbl"):
            return
        text = self.phys_count_edit.text().strip()
        if not text:
            self.reconcile_status_lbl.clear()
            return

        try:
            phys_val = float(text)
        except ValueError:
            self.reconcile_status_lbl.setText("Enter valid number")
            self.reconcile_status_lbl.setStyleSheet("color: #DC2626; font-weight: bold;")
            return

        batch_id = self.batch_combo.currentData()
        b = self._batches_by_id.get(int(batch_id)) if batch_id is not None else None
        cur_batch_stock = float(b.get("stock_qty") or 0.0) if b else 0.0

        item_active = float(self._stock_summary["eligible_stock"]) if getattr(self, "_stock_summary", None) else cur_batch_stock
        expired = float(self._stock_summary["expired_stock"]) if getattr(self, "_stock_summary", None) else 0.0

        item_diff = round(phys_val - item_active, 4)

        color = "#16A34A" if item_diff == 0.0 else "#D97706"
        exp_note = f" ([!] {expired:g} expired in DB)" if expired > 0 else ""
        self.reconcile_status_lbl.setText(
            f"Physical: {phys_val:g} | Active Book: {item_active:g} (Var: {item_diff:+g}){exp_note} | Batch Stock: {cur_batch_stock:g}"
        )
        self.reconcile_status_lbl.setStyleSheet(f"color: {color}; font-weight: bold;")

    def _on_apply_physical_reconciliation(self):
        """Apply variance between physical count and book stock to the adjustment quantity."""
        text = self.phys_count_edit.text().strip()
        if not text:
            QMessageBox.information(self, "Reconcile", "Please enter physical stock count first.")
            return
        try:
            phys_val = float(text)
        except ValueError:
            QMessageBox.warning(self, "Invalid Input", "Physical count must be a valid number.")
            return

        batch_id = self.batch_combo.currentData()
        if batch_id is None or int(batch_id) not in self._batches_by_id:
            QMessageBox.warning(self, "Select Batch", "Please select a batch to reconcile.")
            return

        b = self._batches_by_id[int(batch_id)]
        cur_batch_stock = float(b.get("stock_qty") or 0.0)
        item_active = float(self._stock_summary["eligible_stock"]) if getattr(self, "_stock_summary", None) else cur_batch_stock

        if getattr(self, "_stock_summary", None) and b.get("is_eligible"):
            var = round(phys_val - item_active, 4)
            reason = f"Physical count reconciliation (physical={phys_val:g}, active book={item_active:g})"
        else:
            var = round(phys_val - cur_batch_stock, 4)
            reason = f"Physical count reconciliation for batch {b.get('batch_no', '')} (physical={phys_val:g}, book={cur_batch_stock:g})"

        if var == 0.0:
            QMessageBox.information(self, "No Variance", "Physical count exactly matches book stock. No adjustment needed.")
            return

        if cur_batch_stock + var < 0.0:
            QMessageBox.warning(
                self,
                "Negative Stock Error",
                f"Applying variance ({var:+g}) to batch {b.get('batch_no', '')} (stock: {cur_batch_stock:g}) would result in negative stock.\n"
                f"Please verify batch selection or enter batch-specific count.",
            )
            return

        self.qty_edit.setText(f"{var:+g}")
        self.reason_edit.setText(reason)
        self._update_projected_stock()

    def _on_write_off_batch(self):
        """Quick action to write off the entire stock of the selected batch to 0."""
        batch_id = self.batch_combo.currentData()
        if batch_id is None or int(batch_id) not in self._batches_by_id:
            # If expired batches exist, switch to write-off mode automatically
            if self._stock_summary and self._stock_summary.get("expired_batches"):
                if hasattr(self, "show_expired_cb"):
                    self.show_expired_cb.setChecked(True)
                QMessageBox.information(
                    self,
                    "Write-Off Mode",
                    "Expired batches loaded into Batch dropdown. Please select an expired batch to write off.",
                )
            else:
                QMessageBox.warning(self, "Select Batch", "Please select a batch to write off.")
            return

        b = self._batches_by_id[int(batch_id)]
        cur_stock = float(b.get("stock_qty") or 0.0)
        if cur_stock <= 0:
            QMessageBox.information(self, "Zero Stock", "This batch already has 0 stock.")
            return

        self.qty_edit.setText(f"-{int(cur_stock) if cur_stock.is_integer() else cur_stock:g}")
        b_no = b.get("batch_no") or ""
        exp = _format_expiry_display(b.get("expiry") or "")
        if b.get("is_expired") or not b.get("is_valid_expiry"):
            self.reason_edit.setText(f"Expired stock write-off: batch {b_no} (expired {exp})")
        else:
            self.reason_edit.setText(f"Batch zero-out / disposal: batch {b_no}")
        self._update_projected_stock()

    def _on_create_new_batch(self):
        """Allow creating a new batch for the selected medicine during stock adjustment."""
        item_id = self.item_combo.currentData()
        if item_id is None:
            QMessageBox.warning(self, "Select Medicine", "Please select a medicine before creating a new batch.")
            return

        item_info = next((it for it in self._items_list if it["id"] == int(item_id)), None)
        item_name = item_info["item_name"] if item_info else "Medicine"
        default_pack = item_info.get("pack_size", "1") if item_info else "1"

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Create New Batch - {item_name}")
        dlg.setFixedWidth(420)
        p = palette()
        dlg.setStyleSheet(f"QDialog {{ background-color: {p['surface']}; color: {p['text']}; font-family: {FONT_FAMILY}; }}")

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        grid = QGridLayout()
        grid.setSpacing(8)

        grid.addWidget(QLabel("Batch No *:"), 0, 0)
        batch_no_edit = QLineEdit()
        batch_no_edit.setPlaceholderText("e.g. BATCH2026")
        grid.addWidget(batch_no_edit, 0, 1)

        grid.addWidget(QLabel("Expiry (MM/YY or YYYY-MM-DD) *:"), 1, 0)
        expiry_edit = QLineEdit()
        expiry_edit.setPlaceholderText("e.g. 12/28 or 2028-12-31")
        grid.addWidget(expiry_edit, 1, 1)

        grid.addWidget(QLabel("Pack Size:"), 2, 0)
        pack_size_edit = QLineEdit(str(default_pack))
        grid.addWidget(pack_size_edit, 2, 1)

        grid.addWidget(QLabel("MRP:"), 3, 0)
        mrp_edit = QLineEdit("0.00")
        grid.addWidget(mrp_edit, 3, 1)

        grid.addWidget(QLabel("Purchase Rate:"), 4, 0)
        rate_edit = QLineEdit("0.00")
        grid.addWidget(rate_edit, 4, 1)

        layout.addLayout(grid)

        btn_box = QHBoxLayout()
        btn_box.addStretch()
        btn_save = QPushButton("Create Batch")
        btn_save.setStyleSheet(f"background-color: {p['accent']}; color: #ffffff; font-weight: bold; padding: 6px 14px;")
        btn_cancel = QPushButton("Cancel")
        btn_cancel.setStyleSheet(_BUTTON_SECONDARY_STYLE)
        btn_cancel.clicked.connect(dlg.reject)
        btn_box.addWidget(btn_save)
        btn_box.addWidget(btn_cancel)
        layout.addLayout(btn_box)

        def do_save():
            b_no = batch_no_edit.text().strip().upper()
            if not b_no:
                QMessageBox.warning(dlg, "Validation Error", "Batch No is required.")
                batch_no_edit.setFocus()
                return

            exp_raw = expiry_edit.text().strip()
            parsed_exp = StockDAO.parse_expiry_date(exp_raw)
            if parsed_exp is None:
                QMessageBox.warning(dlg, "Validation Error", "Please enter a valid expiry date (e.g. MM/YY or YYYY-MM-DD).")
                expiry_edit.setFocus()
                return

            if parsed_exp < date.today():
                QMessageBox.warning(dlg, "Validation Error", "Cannot create a new batch with an already expired date.")
                expiry_edit.setFocus()
                return

            try:
                mrp_val = float(mrp_edit.text().strip() or "0")
                rate_val = float(rate_edit.text().strip() or "0")
            except ValueError:
                QMessageBox.warning(dlg, "Validation Error", "MRP and Purchase Rate must be valid numbers.")
                return

            p_size = pack_size_edit.text().strip() or "1"
            iso_exp = parsed_exp.isoformat()

            conn = get_connection()
            try:
                existing = conn.execute(
                    "SELECT id FROM stock_batches WHERE item_id = ? AND UPPER(batch_no) = ?",
                    (int(item_id), b_no)
                ).fetchone()
                if existing:
                    new_batch_id = existing[0]
                else:
                    cur = conn.execute(
                        """
                        INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size, mrp, purchase_rate, net_rate, stock_qty)
                        VALUES (?, ?, ?, ?, ?, ?, ?, 0.0)
                        """,
                        (int(item_id), b_no, iso_exp, p_size, mrp_val, rate_val, rate_val)
                    )
                    conn.commit()
                    new_batch_id = cur.lastrowid
            finally:
                conn.close()

            dlg.accept()
            self._load_batches_for_item(int(item_id))
            self.batch_combo.set_selected_id(new_batch_id)
            self.qty_edit.setFocus()

        btn_save.clicked.connect(do_save)
        dlg.exec()

    def _show_movement_dialog(self):
        """Display authoritative movement ledger audit for the selected batch."""
        item_id = self.item_combo.currentData()
        batch_id = self.batch_combo.currentData()
        if item_id is None or batch_id is None or int(batch_id) not in self._batches_by_id:
            QMessageBox.information(self, "Select Batch", "Please select a medicine and batch first.")
            return

        b = self._batches_by_id[int(batch_id)]
        m = StockDAO.get_batch_ledger_movement(int(item_id), int(batch_id), b.get("batch_no"))

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Movement Ledger - Batch {b.get('batch_no', '')}")
        dlg.resize(540, 360)
        p = palette()
        dlg.setStyleSheet(f"QDialog {{ background-color: {p['surface']}; color: {p['text']}; font-family: {FONT_FAMILY}; }}")

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        header_lbl = QLabel(f"Authoritative Movement Ledger: {b.get('item_name', '')} (Batch: {b.get('batch_no', '')})")
        header_lbl.setStyleSheet(f"font-size: 15px; font-weight: bold; color: {p['accent']};")
        layout.addWidget(header_lbl)

        grid = QGridLayout()
        grid.setSpacing(8)

        status_text = "100% In Agreement" if m["variance"] == 0 else f"Discrepancy: {m['variance']:+g}"
        rows = [
            ("Pack Size Factor:", f"{m['pack_factor']} (Purchases converted to loose units)"),
            ("Total Purchased (Loose Units):", f"{m['purchased_loose']:g}"),
            ("Total Sold (Loose Units):", f"{m['sold_loose']:g}"),
            ("Sales Returns / Credit Notes (+):", f"{m['sales_returns_loose']:g}"),
            ("Purchase Returns / Debit Notes (-):", f"{m['purchase_returns_loose']:g}"),
            ("Previous Stock Adjustments (+/-):", f"{m['adjustments_loose']:g}"),
            ("Calculated Movement Balance:", f"{m['calculated_book_stock']:g}"),
            ("Current Stored Stock:", f"{m['stored_stock']:g}"),
            ("Reconciliation Status:", status_text),
        ]

        for idx, (label, val) in enumerate(rows):
            lbl_w = QLabel(label)
            lbl_w.setStyleSheet(f"font-size: 13px; font-weight: bold; color: {p['text']};")
            val_w = QLabel(val)
            val_style = "font-size: 13px; color: #16A34A; font-weight: bold;" if "Agreement" in val else f"font-size: 13px; color: {p['text']}; font-weight: bold;"
            val_w.setStyleSheet(val_style)
            grid.addWidget(lbl_w, idx, 0)
            grid.addWidget(val_w, idx, 1)

        layout.addLayout(grid)
        layout.addStretch()

        close_btn = QPushButton("Close")
        close_btn.setFixedWidth(90)
        close_btn.setStyleSheet(_BUTTON_SECONDARY_STYLE)
        close_btn.clicked.connect(dlg.accept)
        btn_box = QHBoxLayout()
        btn_box.addStretch()
        btn_box.addWidget(close_btn)
        layout.addLayout(btn_box)

        dlg.exec()

    def _update_projected_stock(self):
        """Compute and display projected stock dynamically as user types."""
        p = palette()
        batch_id = self.batch_combo.currentData()
        if batch_id is None or int(batch_id) not in self._batches_by_id:
            self.projected_label.setText("Select a medicine and batch to adjust stock.")
            self.projected_label.setStyleSheet(f"color: {p['text_dim']}; font-weight: bold;")
            return

        b = self._batches_by_id[int(batch_id)]
        cur_stock = float(b.get("stock_qty") or 0.0)
        text = self.qty_edit.text().strip()

        if not text:
            self.projected_label.setText(
                f"Current Stock: {cur_stock:g}  |  Adjustment: --  |  Projected Stock: {cur_stock:g}"
            )
            self.projected_label.setStyleSheet(f"color: {p['text_dim']}; font-weight: bold;")
            return

        try:
            adj_val = float(text)
        except ValueError:
            self.projected_label.setText("Invalid adjustment quantity (enter +N or -N)")
            self.projected_label.setStyleSheet("color: #DC2626; font-weight: bold;")
            return

        if adj_val == 0.0:
            self.projected_label.setText("Adjustment quantity cannot be zero.")
            self.projected_label.setStyleSheet("color: #D97706; font-weight: bold;")
            return

        if adj_val < 0.0 and cur_stock <= 0.0:
            self.projected_label.setText(
                f"Current: 0  |  Adjustment: {adj_val:+g}  |  [ERROR: Cannot remove stock from zero-stock batch]"
            )
            self.projected_label.setStyleSheet("color: #DC2626; font-weight: bold;")
            return

        if adj_val > 0.0 and (b.get("is_expired") or not b.get("is_valid_expiry")):
            self.projected_label.setText(
                f"Current: {cur_stock:g}  |  Adjustment: {adj_val:+g}  |  [ERROR: Cannot add stock to expired batch]"
            )
            self.projected_label.setStyleSheet("color: #DC2626; font-weight: bold;")
            return

        if self._edit_adjustment_id is not None and self._edit_adj_data:
            old_qty = float(self._edit_adj_data.get("adjusted_qty") or 0.0)
            delta = round(adj_val - old_qty, 4)
            projected = round(cur_stock + delta, 4)
            if projected < 0.0:
                self.projected_label.setText(
                    f"Current: {cur_stock:g}  |  Original Adj: {old_qty:+g}  |  Delta: {delta:+g}  |  Projected: {projected:g} [ERROR: Negative stock]"
                )
                self.projected_label.setStyleSheet("color: #DC2626; font-weight: bold;")
            else:
                color_code = "#16A34A" if delta >= 0 else "#2563EB"
                self.projected_label.setText(
                    f"Current: {cur_stock:g}  |  Original: {old_qty:+g}  |  New Adj: {adj_val:+g} (Delta: {delta:+g})  |  Projected: {projected:g}"
                )
                self.projected_label.setStyleSheet(f"color: {color_code}; font-weight: bold;")
        else:
            projected = round(cur_stock + adj_val, 4)
            if projected < 0.0:
                self.projected_label.setText(
                    f"Current: {cur_stock:g}  |  Adjustment: {adj_val:+g}  |  Projected: {projected:g} [ERROR: Negative stock not allowed]"
                )
                self.projected_label.setStyleSheet("color: #DC2626; font-weight: bold;")
            else:
                action_tag = "[INCREASE]" if adj_val > 0 else "[DECREASE]"
                color_code = "#16A34A" if adj_val > 0 else "#2563EB"
                self.projected_label.setText(
                    f"Current: {cur_stock:g}  |  Adjustment: {adj_val:+g}  |  Projected: {projected:g} {action_tag}"
                )
                self.projected_label.setStyleSheet(f"color: {color_code}; font-weight: bold;")

    def _show_history_popup(self):
        """Show recent adjustments for the selected item."""
        item_id = self.item_combo.currentData()
        if item_id is None:
            QMessageBox.information(self, "Item History", "Please select a medicine first.")
            return

        records = StockAdjustmentDAO.get_adjustments_for_item(int(item_id))
        if not records:
            QMessageBox.information(
                self,
                "Adjustment History",
                "No previous stock adjustments recorded for this medicine.",
            )
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Stock Adjustment History")
        dlg.resize(680, 320)
        dlg_layout = QVBoxLayout(dlg)

        table = QTableWidget(len(records), 6)
        table.setHorizontalHeaderLabels([
            "Date", "Batch #", "Prev Stock", "Adj Qty", "Result Stock", "Reason"
        ])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        for r_idx, r in enumerate(records):
            table.setItem(r_idx, 0, QTableWidgetItem(f"{r['adjustment_date']} {r.get('adjustment_time', '')}"))
            table.setItem(r_idx, 1, QTableWidgetItem(str(r.get("batch_no", ""))))
            table.setItem(r_idx, 2, QTableWidgetItem(f"{float(r.get('previous_qty', 0)):g}"))
            adj = float(r.get("adjusted_qty", 0))
            it_adj = QTableWidgetItem(f"{adj:+g}")
            it_adj.setForeground(QColor("#16A34A" if adj > 0 else "#DC2626"))
            table.setItem(r_idx, 3, it_adj)
            table.setItem(r_idx, 4, QTableWidgetItem(f"{float(r.get('resulting_qty', 0)):g}"))
            table.setItem(r_idx, 5, QTableWidgetItem(str(r.get("reason", ""))))

        dlg_layout.addWidget(table)
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(dlg.accept)
        dlg_layout.addWidget(btn_close, alignment=Qt.AlignRight)
        dlg.exec()

    def _on_save(self):
        """Validate and atomically execute or update the stock adjustment."""
        if self._is_saving:
            return

        item_id = self.item_combo.currentData()
        if item_id is None:
            QMessageBox.warning(self, "Validation Error", "Please select a medicine.")
            self.item_combo.setFocus()
            return

        batch_id = self.batch_combo.currentData()
        if batch_id is None or int(batch_id) not in self._batches_by_id:
            QMessageBox.warning(self, "Validation Error", "Please select a valid stock batch.")
            self.batch_combo.setFocus()
            return

        text = self.qty_edit.text().strip()
        if not text:
            QMessageBox.warning(self, "Validation Error", "Please enter an adjustment quantity (e.g. +2 or -1).")
            self.qty_edit.setFocus()
            return

        try:
            adj_val = float(text)
        except ValueError:
            QMessageBox.warning(self, "Validation Error", f"'{text}' is not a valid number.")
            self.qty_edit.setFocus()
            return

        if adj_val == 0.0:
            QMessageBox.warning(self, "Validation Error", "Adjustment quantity cannot be zero.")
            self.qty_edit.setFocus()
            return

        b = self._batches_by_id[int(batch_id)]
        cur_stock = float(b.get("stock_qty") or 0.0)

        # Stock removal validation: batch must have available stock
        if adj_val < 0.0 and cur_stock <= 0.0:
            QMessageBox.warning(
                self,
                "Zero Stock Error",
                f"Batch '{b.get('batch_no')}' has 0 available stock.\n"
                f"Stock removal is not permitted on a zero-stock batch.",
            )
            self.qty_edit.setFocus()
            return

        # Stock addition validation: expired or invalid expiry batches cannot receive stock
        if adj_val > 0.0 and (b.get("is_expired") or not b.get("is_valid_expiry")):
            QMessageBox.warning(
                self,
                "Expired Batch Error",
                f"Batch '{b.get('batch_no')}' is expired or has an invalid expiry date.\n"
                f"Stock addition to expired batches is strictly prohibited.\n"
                f"Expired stock can only be written off / disposed.",
            )
            self.qty_edit.setFocus()
            return

        if self._edit_adjustment_id is not None and self._edit_adj_data:
            old_qty = float(self._edit_adj_data.get("adjusted_qty") or 0.0)
            delta = round(adj_val - old_qty, 4)
            projected = round(cur_stock + delta, 4)
        else:
            projected = round(cur_stock + adj_val, 4)

        if projected < 0.0:
            QMessageBox.warning(
                self,
                "Negative Stock Error",
                f"Adjustment of {adj_val:+g} would result in negative stock ({projected:g}).\n"
                f"Current batch stock is {cur_stock:g}.\n"
                f"Negative stock is not permitted.",
            )
            self.qty_edit.setFocus()
            return

        reason = self.reason_edit.text().strip()

        # Duplicate-click protection
        self._is_saving = True
        self.save_btn.setEnabled(False)

        try:
            if self._edit_adjustment_id is not None:
                result = StockAdjustmentDAO.update_adjustment(
                    adjustment_id=int(self._edit_adjustment_id),
                    new_adjusted_qty=adj_val,
                    reason=reason,
                    user_name="",
                )
            else:
                result = StockAdjustmentDAO.record_adjustment(
                    item_id=int(item_id),
                    stock_batch_id=int(batch_id),
                    adjusted_qty=adj_val,
                    reason=reason,
                    user_name="",
                )

            # Signal listeners (Counter Sale, Adjusted Stock List, etc.)
            self.adjustment_saved.emit(
                int(item_id),
                int(batch_id),
                float(adj_val),
                float(result["resulting_qty"]),
            )

            item_name = result.get("item_name") or b.get("item_name") or "Medicine"
            batch_no = result.get("batch_no") or b.get("batch_no") or ""

            msg_title = "Stock Adjustment Updated" if self._edit_adjustment_id else "Stock Adjustment Successful"
            QMessageBox.information(
                self,
                msg_title,
                f"{msg_title}!\n\n"
                f"Medicine: {item_name}\n"
                f"Batch: {batch_no}\n"
                f"Adjustment: {result['adjusted_qty']:+g}\n"
                f"Resulting Stock: {result['resulting_qty']:g}\n",
            )

            self.accept()
        except StockAdjustmentError as err:
            QMessageBox.warning(self, "Adjustment Failed", str(err))
            self.save_btn.setEnabled(True)
            self._is_saving = False
            self.qty_edit.setFocus()
        except Exception as err:
            QMessageBox.critical(self, "System Error", f"Failed to record adjustment:\n{err}")
            self.save_btn.setEnabled(True)
            self._is_saving = False
            self.qty_edit.setFocus()
