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
from typing import Any, Optional

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
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
            min_width=270,
            allow_width_expansion=True,
        )
        self.batch_combo.setFixedHeight(30)
        self.batch_combo.setMinimumWidth(260)
        self.batch_combo.selection_changed.connect(self._on_batch_selected)
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
        self.batch_combo.set_selected_id(batch_id)

    def _on_item_selected(self, item_id: Any):
        """Called when a medicine is chosen from the SearchableComboBox."""
        if item_id is None:
            self._clear_all_fields()
            return
        self._load_batches_for_item(int(item_id))

    def _load_batches_for_item(self, item_id: int):
        """Load all batches for the selected medicine into batch_combo."""
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
                f"Expired Stock in DB: {expired_stock:g} tablets ({summary['expired_batch_count']} batches)\n"
                f"Total Book Stock: {total_book:g} tablets"
            )
            self.stock_breakdown_lbl.setText(
                f"[!] Active Eligible: {eligible_stock:g} | Expired in DB: {expired_stock:g} ({summary['expired_batch_count']} historical batches) | Total Book: {total_book:g}"
            )
            self.stock_breakdown_lbl.setStyleSheet("font-size: 12px; color: #D97706; font-weight: bold;")
            self.stock_breakdown_lbl.setVisible(True)
        else:
            self.item_stock_edit.setToolTip(f"Total Eligible Stock: {eligible_stock:g} tablets")
            self.stock_breakdown_lbl.setVisible(False)

        if not self._batches:
            self.batch_combo.populate([("No batches found for this medicine", None, "")])
            self.batch_combo.setCurrentIndex(0)
            self._clear_batch_fields()
            self.projected_label.setText("This medicine has no existing stock batches.")
            self.projected_label.setStyleSheet("color: #D97706; font-weight: bold;")
            return

        batch_items = []
        for b in self._batches:
            b_no = str(b.get("batch_no") or "").strip() or "-"
            exp = _format_expiry_display(b.get("expiry") or "")
            qty = float(b.get("stock_qty") or 0.0)
            mrp = float(b.get("mrp") or 0.0)

            status_tag = ""
            if b.get("is_zero_stock"):
                status_tag = " [0 Stock]"
            elif b.get("is_expired"):
                status_tag = " [EXPIRED]"

            label = f"{b_no} | Exp: {exp or '-'} | Stk: {qty:g}{status_tag} | MRP: {mrp:.2f}"
            batch_items.append((label, int(b["id"]), b_no))

        self.batch_combo.populate(batch_items)

        # Select appropriate default batch:
        # 1. If explicit batch requested (edit mode / initial), pick it
        # 2. Else pick primary active batch (largest stock or first unexpired)
        # 3. Else if only expired batches have stock, pick first
        # 4. Else if only zero stock batches, pick first
        chosen_batch_id = None
        if self._initial_batch_id is not None and self._initial_batch_id in self._batches_by_id:
            chosen_batch_id = self._initial_batch_id
            self._initial_batch_id = None
        elif summary["active_batches"]:
            # Pick active batch with largest stock
            chosen_batch_id = max(summary["active_batches"], key=lambda b: float(b.get("stock_qty") or 0.0))["id"]
        elif summary["expired_batches"]:
            chosen_batch_id = summary["expired_batches"][0]["id"]
        elif self._batches:
            chosen_batch_id = self._batches[0]["id"]

        if chosen_batch_id is not None:
            self.batch_combo.set_selected_id(chosen_batch_id)
        else:
            self.batch_combo.clear_selection()
            self._clear_batch_fields()

    def _on_batch_selected(self, batch_id: Any):
        """Called when a batch is chosen from the SearchableComboBox."""
        if batch_id is None or int(batch_id) not in self._batches_by_id:
            self._clear_batch_fields()
            return

        b = self._batches_by_id[int(batch_id)]
        self.pack_edit.setText(str(b.get("pack_size") or "1"))
        qty = float(b.get("stock_qty") or 0.0)
        self.batch_stock_edit.setText(f"{int(qty) if qty.is_integer() else qty:g}")
        self.expiry_edit.setText(_format_expiry_display(b.get("expiry") or ""))
        self.mrp_edit.setText(f"{float(b.get('mrp') or 0.0):.2f}")
        self.rate_edit.setText(f"{float(b.get('purchase_rate') or 0.0):.2f}")
        self.tax_edit.setText(f"{float(b.get('tax_percent') or 0.0):.2f}%")
        self.net_rate_edit.setText(f"{float(b.get('net_rate') or 0.0):.2f}")

        # Update styling based on expiry
        p = palette()
        if b.get("is_expired"):
            self.batch_stock_edit.setToolTip("[!] This batch is EXPIRED. Use adjustment to write off.")
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
        if b.get("is_expired"):
            self.reason_edit.setText(f"Expired stock write-off: batch {b_no} (expired {exp})")
        else:
            self.reason_edit.setText(f"Batch zero-out / disposal: batch {b_no}")
        self._update_projected_stock()

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
