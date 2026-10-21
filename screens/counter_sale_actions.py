"""Quick-action dialogs for Counter Sale:
1. Drug Substitute
2. Items Demand Order
3. Customer Balance List
4. Supplier Balance List

Implements actual SQLite database queries and authoritative ledger logic,
supporting Day Mode, Night Mode, searching, sorting, and reporting.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, List, Optional

from PySide6.QtCore import QEvent, QModelIndex, QPoint, QRect, QSize, Qt, Signal, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QCompleter,
    QDialog,
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
from database.drug_dao import DrugDAO
from database.ledger_dao import LedgerDAO
from database.party_wise_report_dao import PartyWiseReportDAO
from database.stock_dao import StockDAO

from ui.theme import (
    TYPE_BUTTON,
    TYPE_FORM_LABEL,
    TYPE_HINT,
    TYPE_INPUT,
    TYPE_PAGE_TITLE,
    TYPE_SECTION_HEADER,
    TYPE_TABLE_DATA,
    TYPE_TABLE_HEADER,
    palette,
)
from ui.components import FONT_FAMILY
from ui.crystal_report_viewer import (
    BlockKind,
    MARGIN_LEFT,
    MARGIN_RIGHT,
    PAGE_WIDTH,
    ReportBlock,
    ReportHeaderData,
    ReportPage,
    get_default_store_identity,
    print_or_export_report_pages,
)


# ---------------------------------------------------------------------------
# Styling Helpers
# ---------------------------------------------------------------------------

def _fresh_btn_style(edge: str, p: dict | None = None, padding: str = "5px 14px") -> str:
    p = p or palette()
    face = p["surface_alt"]
    face_hover = p["selected"]
    face_pressed = p["surface"]
    return (
        f"QPushButton {{"
        f"  background-color: {face}; color: {p['text']};"
        f"  border: 1px solid {edge}; border-radius: 2px;"
        f"  padding: {padding}; font-size: {TYPE_BUTTON}px;"
        f"  font-family: {FONT_FAMILY}; font-weight: 500;"
        f"}}"
        f"QPushButton:hover {{"
        f"  background-color: {face_hover}; color: {p['selected_text']};"
        f"  border: 1px solid {p['accent']};"
        f"}}"
        f"QPushButton:pressed {{"
        f"  background-color: {face_pressed};"
        f"}}"
        f"QPushButton:disabled {{"
        f"  background-color: {p['disabled_bg']}; color: {p['disabled_text']};"
        f"  border: 1px solid {p['border']};"
        f"}}"
    )


def _fresh_table_style(p: dict | None = None) -> str:
    p = p or palette()
    return (
        f"QTableWidget {{"
        f"  background-color: {p['bg']}; color: {p['text']};"
        f"  border: 1px solid {p['border']}; gridline-color: {p['border']};"
        f"  font-size: {TYPE_TABLE_DATA}px; font-family: {FONT_FAMILY};"
        f"  selection-background-color: {p['selected']};"
        f"  selection-color: {p['selected_text']};"
        f"}}"
        f"QTableWidget::item {{ padding: 3px 6px; }}"
    )


def _fresh_header_style(p: dict | None = None) -> str:
    p = p or palette()
    return (
        f"QHeaderView::section {{"
        f"  background-color: {p['surface']}; color: {p['text']};"
        f"  border: none; border-bottom: 2px solid {p['accent']};"
        f"  padding: 5px 6px; font-weight: bold;"
        f"  font-size: {TYPE_TABLE_HEADER}px;"
        f"  font-family: {FONT_FAMILY};"
        f"}}"
    )


def _fresh_input_style(p: dict | None = None) -> str:
    p = p or palette()
    return (
        f"QLineEdit {{"
        f"  background-color: {p['surface']}; color: {p['text']};"
        f"  border: 1px solid {p['border']}; border-radius: 2px;"
        f"  padding: 4px 8px; font-size: {TYPE_INPUT}px;"
        f"  font-family: {FONT_FAMILY};"
        f"}}"
        f"QLineEdit:focus {{ border: 1px solid {p['accent']}; }}"
    )


def _fresh_combo_style(p: dict | None = None) -> str:
    p = p or palette()
    return (
        f"QComboBox {{"
        f"  background-color: {p['surface']}; color: {p['text']};"
        f"  border: 1px solid {p['border']}; border-radius: 2px;"
        f"  padding: 4px 8px; font-size: {TYPE_INPUT}px;"
        f"  font-family: {FONT_FAMILY};"
        f"}}"
        f"QComboBox:focus {{ border: 1px solid {p['accent']}; }}"
        f"QComboBox QAbstractItemView {{"
        f"  background-color: {p['bg']}; color: {p['text']};"
        f"  border: 1px solid {p['border']}; selection-background-color: {p['selected']};"
        f"  selection-color: {p['selected_text']}; font-size: {TYPE_INPUT}px;"
        f"}}"
    )


def _fresh_completer_popup_style(p: dict | None = None) -> str:
    p = p or palette()
    surface = p["surface"]
    text = p["text"]
    border = p["border"]
    accent = p["accent"]
    selected_bg = p.get("selected", accent)
    selected_text = p.get("selected_text", "#FFFFFF")
    text_dim = p.get("text_dim", "#888888")
    return (
        f"QAbstractItemView {{"
        f"  background-color: {surface}; color: {text};"
        f"  border: 1px solid {border}; border-radius: 4px;"
        f"  selection-background-color: {selected_bg}; selection-color: {selected_text};"
        f"  font-size: {TYPE_INPUT}px; font-family: {FONT_FAMILY}; outline: 0;"
        f"}}"
        f"QAbstractItemView::item {{ min-height: 26px; padding: 4px 8px; }}"
        f"QAbstractItemView::item:disabled {{ color: {text_dim}; font-style: italic; background-color: transparent; }}"
        f"QAbstractItemView::item:selected {{ background-color: {selected_bg}; color: {selected_text}; }}"
    )


# ---------------------------------------------------------------------------
# Numeric Table Widget Item for Accurate Sorting
# ---------------------------------------------------------------------------

class NumericTableWidgetItem(QTableWidgetItem):
    """QTableWidgetItem comparing numerically via sort_value."""

    def __init__(self, text: str, sort_value: float | int):
        super().__init__(text)
        self.sort_value = sort_value

    def __lt__(self, other: Any) -> bool:
        if isinstance(other, NumericTableWidgetItem):
            return self.sort_value < other.sort_value
        if hasattr(other, "sort_value"):
            return self.sort_value < other.sort_value
        try:
            return self.sort_value < float(other.text())
        except (ValueError, TypeError):
            return self.text() < other.text()


# ---------------------------------------------------------------------------
# Report Pagination Helper
# ---------------------------------------------------------------------------

def paginate_report_blocks(
    header: ReportHeaderData,
    blocks: List[ReportBlock],
    table_header_block: Optional[ReportBlock] = None,
    max_body_height: float = 980.0,
) -> List[ReportPage]:
    if not blocks:
        return [ReportPage(page_num=1, total_pages=1, header=header, blocks=[])]

    pages: List[ReportPage] = []
    current_blocks: List[ReportBlock] = []
    current_h = 0.0

    for block in blocks:
        needed_h = 60.0 if block.kind in (BlockKind.GROUP_HEADER, BlockKind.ITEM_SUBTOTAL) else block.height
        if current_blocks and (current_h + needed_h > max_body_height):
            pages.append(
                ReportPage(
                    page_num=len(pages) + 1,
                    total_pages=0,
                    header=header,
                    blocks=current_blocks,
                )
            )
            current_blocks = []
            current_h = 0.0
            if table_header_block and block.kind != BlockKind.TABLE_HEADER:
                current_blocks.append(table_header_block)
                current_h += table_header_block.height

        current_blocks.append(block)
        current_h += block.height

    if current_blocks:
        pages.append(
            ReportPage(
                page_num=len(pages) + 1,
                total_pages=0,
                header=header,
                blocks=current_blocks,
            )
        )

    total = len(pages)
    for p in pages:
        p.total_pages = total

    return pages


# ---------------------------------------------------------------------------
# 1. Drug Substitute Dialog
# ---------------------------------------------------------------------------

class DrugSubstituteDialog(QDialog):
    """Dialog to search and view database substitute items by active drug/ingredient."""

    item_selected = Signal(int)

    def __init__(self, parent: QWidget | None = None, initial_item_id: int | None = None):
        super().__init__(parent)
        self.setWindowTitle("Drug Substitute")
        self.setModal(True)
        self.resize(720, 480)

        self.selected_item_id: int | None = None
        self._initial_item_id = initial_item_id
        self._drugs: list[dict] = []
        self._items: list[dict] = []
        self._block_search: bool = False

        self._build_ui()
        self._load_drugs()
        self.refresh_theme()

        # If an initial item is provided, pre-select its drug
        if self._initial_item_id:
            drugs_for_item = DrugDAO.get_drugs_for_item(self._initial_item_id)
            if drugs_for_item:
                target_drug_id = drugs_for_item[0]["id"]
                idx = self.drug_combo.findData(target_drug_id)
                if idx >= 0:
                    self.drug_combo.setCurrentIndex(idx)
                    self._on_show_clicked()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        # Top Bar: Drug label + Searchable Combo + Show Button
        top_bar = QHBoxLayout()
        top_bar.setSpacing(8)

        self.drug_lbl = QLabel("Drug :")
        self.drug_lbl.setStyleSheet(f"font-size: {TYPE_FORM_LABEL}px; font-weight: bold;")
        top_bar.addWidget(self.drug_lbl)

        self.drug_combo = QComboBox()
        self.drug_combo.setEditable(True)
        self.drug_combo.setInsertPolicy(QComboBox.NoInsert)

        # Setup dynamic suggestions completer
        self._completer_model = QStandardItemModel(self)
        self._completer = QCompleter(self._completer_model, self.drug_combo)
        self._completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._completer.setCompletionMode(QCompleter.PopupCompletion)
        self._completer.setMaxVisibleItems(8)
        self._completer.activated[QModelIndex].connect(self._on_completer_activated)

        popup = self._completer.popup()
        if popup is not None:
            popup.setFocusPolicy(Qt.NoFocus)
            popup.setSelectionMode(QAbstractItemView.SingleSelection)
            popup.installEventFilter(self)

        self.drug_combo.setCompleter(self._completer)
        top_bar.addWidget(self.drug_combo, 1)

        line_edit = self.drug_combo.lineEdit()
        line_edit.setPlaceholderText("Type drug or medicine name to search...")
        line_edit.setClearButtonEnabled(True)
        line_edit.installEventFilter(self)
        line_edit.textEdited.connect(self._on_text_edited)
        line_edit.textChanged.connect(self._on_text_changed)

        self.drug_combo.installEventFilter(self)
        self.drug_combo.activated.connect(self._on_combo_activated)

        self.show_btn = QPushButton("Show")
        self.show_btn.setFixedHeight(30)
        self.show_btn.clicked.connect(self._on_show_clicked)
        top_bar.addWidget(self.show_btn)

        root.addLayout(top_bar)

        # Table
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Item Name", "Unit", "MRP"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setSortingEnabled(True)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        self.table.setColumnWidth(1, 110)
        self.table.setColumnWidth(2, 110)

        self.table.doubleClicked.connect(self._on_row_double_clicked)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)

        root.addWidget(self.table, 1)

        # Empty State Message Label
        self.empty_label = QLabel("Select a drug/ingredient and click Show to view matching products.")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setStyleSheet(f"font-size: {TYPE_HINT}px; font-style: italic; padding: 20px;")
        root.addWidget(self.empty_label)
        self.empty_label.setVisible(False)

        # Bottom Bar: Summary + Select & Close Buttons
        bottom_bar = QHBoxLayout()
        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet(f"font-size: {TYPE_HINT}px;")
        bottom_bar.addWidget(self.status_lbl)

        bottom_bar.addStretch()

        self.select_btn = QPushButton("Select Item")
        self.select_btn.setEnabled(False)
        self.select_btn.setFixedHeight(30)
        self.select_btn.clicked.connect(self._on_select_item)
        bottom_bar.addWidget(self.select_btn)

        self.close_btn = QPushButton("Close")
        self.close_btn.setFixedHeight(30)
        self.close_btn.clicked.connect(self.reject)
        bottom_bar.addWidget(self.close_btn)

        root.addLayout(bottom_bar)

    def _position_completion_popup(self):
        if not hasattr(self, "_completer"):
            return
        popup = self._completer.popup()
        if not popup or not popup.isVisible():
            return

        bottom_left = self.drug_combo.mapToGlobal(QPoint(0, self.drug_combo.height()))
        x = bottom_left.x()
        y = bottom_left.y() + 2
        width = max(self.drug_combo.width(), 350)

        count = self._completer_model.rowCount()
        row_height = max(26, popup.sizeHintForRow(0) if count > 0 else 26)
        visible_rows = min(max(count, 1), 8)
        height = row_height * visible_rows + 6

        window = self.window()
        window_rect = window.rect()
        global_bottom = window.mapToGlobal(QPoint(0, window_rect.bottom())).y()

        if y + height <= global_bottom + 60:
            popup.setGeometry(x, y, width, height)
        else:
            avail_h = max(100, global_bottom - y)
            popup.setGeometry(x, y, width, min(height, avail_h))

    def eventFilter(self, obj, event):
        line_edit = self.drug_combo.lineEdit()
        popup = self._completer.popup() if hasattr(self, "_completer") else None

        if obj is line_edit and event.type() == QEvent.MouseButtonPress:
            self.clear_all_fields(clear_text=True)

        if popup and obj is popup and event.type() == QEvent.Show:
            QTimer.singleShot(0, self._position_completion_popup)

        if event.type() == QEvent.KeyPress:
            key = event.key()

            # When popup is open
            if popup and popup.isVisible():
                if key == Qt.Key_Down:
                    self._move_popup_selection(1)
                    return True
                elif key == Qt.Key_Up:
                    self._move_popup_selection(-1)
                    return True
                elif key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Tab):
                    if self._accept_popup_selection():
                        return True
                    popup.hide()
                    self._on_show_clicked()
                    return True
                elif key == Qt.Key_Escape:
                    popup.hide()
                    return True
            else:
                # When popup is closed
                if key == Qt.Key_Down:
                    if self.table.rowCount() > 0:
                        self.table.setFocus()
                        if self.table.currentRow() < 0:
                            self.table.selectRow(0)
                        return True
                elif key in (Qt.Key_Return, Qt.Key_Enter):
                    self._on_show_clicked()
                    return True

        return super().eventFilter(obj, event)

    def _move_popup_selection(self, step: int):
        popup = self._completer.popup()
        count = self._completer_model.rowCount()
        if count == 0:
            return

        current = popup.currentIndex().row()
        if current < 0:
            next_row = 0 if step > 0 else count - 1
        else:
            next_row = current + step

        while 0 <= next_row < count:
            idx = self._completer_model.index(next_row, 0)
            if idx.data(Qt.UserRole) is not None:
                popup.setCurrentIndex(idx)
                popup.scrollTo(idx)
                return
            next_row += step

    def _accept_popup_selection(self) -> bool:
        popup = self._completer.popup()
        idx = popup.currentIndex()
        if not idx.isValid() or idx.data(Qt.UserRole) is None:
            for r in range(self._completer_model.rowCount()):
                cand = self._completer_model.index(r, 0)
                if cand.data(Qt.UserRole) is not None:
                    idx = cand
                    break

        if idx.isValid() and idx.data(Qt.UserRole) is not None:
            popup.hide()
            entry = idx.data(Qt.UserRole)
            self._on_suggestion_selected(entry)
            return True
        return False

    def clear_all_fields(self, clear_text: bool = True):
        self._block_search = True
        if clear_text:
            self.drug_combo.lineEdit().clear()
            self.drug_combo.setCurrentIndex(-1)
        self._block_search = False

        if hasattr(self, "_completer") and self._completer.popup():
            self._completer.popup().hide()

        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        self.table.setSortingEnabled(True)
        self.status_lbl.setText("")
        self._items = []
        self.selected_item_id = None
        self.select_btn.setEnabled(False)
        self.empty_label.setText("Select a drug/ingredient and click Show to view matching products.")
        self.empty_label.setVisible(False)

    def _on_text_changed(self, text: str):
        if self._block_search:
            return
        query = text.strip()
        if not query or query == "-- Select Drug / Ingredient --":
            self.clear_all_fields(clear_text=False)
            if hasattr(self, "_completer") and self._completer.popup():
                self._completer.popup().hide()

    def _on_text_edited(self, text: str):
        if self._block_search:
            return
        query = text.strip()
        if not query or query == "-- Select Drug / Ingredient --":
            self.clear_all_fields(clear_text=False)
            if hasattr(self, "_completer") and self._completer.popup():
                self._completer.popup().hide()
            return

        # Dynamically query suggestions from database
        suggestions = DrugDAO.search_suggestions(query)
        self._completer_model.clear()

        if suggestions:
            for s in suggestions:
                item = QStandardItem(s["name"])
                item.setData(s, Qt.UserRole)
                self._completer_model.appendRow(item)
            self.empty_label.setVisible(False)
        else:
            item = QStandardItem("No matching medicines found")
            item.setEnabled(False)
            item.setData(None, Qt.UserRole)
            self._completer_model.appendRow(item)
            self.empty_label.setText("No matching medicines found.")
            self.empty_label.setVisible(True)
            self.table.setRowCount(0)
            self.status_lbl.setText("Found 0 matching items")
            self.select_btn.setEnabled(False)

        self._completer.setCompletionPrefix("")
        self._completer.complete()
        self._position_completion_popup()

    def _on_completer_activated(self, index: QModelIndex):
        if not index.isValid():
            return
        entry = index.data(Qt.UserRole)
        if entry is None:
            return
        self._on_suggestion_selected(entry)

    def _on_suggestion_selected(self, entry: dict):
        if not entry:
            return
        kind = entry.get("kind")
        name = entry.get("name", "")
        item_or_drug_id = entry.get("id")

        self._block_search = True
        self.drug_combo.lineEdit().setText(name)
        self._block_search = False

        if hasattr(self, "_completer") and self._completer.popup():
            self._completer.popup().hide()

        if kind == "drug":
            idx = self.drug_combo.findData(item_or_drug_id)
            if idx >= 0:
                self.drug_combo.blockSignals(True)
                self.drug_combo.setCurrentIndex(idx)
                self.drug_combo.blockSignals(False)
            self._items = DrugDAO.get_substitutes(item_or_drug_id)
        else:  # kind == "item"
            drugs = DrugDAO.get_drugs_for_item(item_or_drug_id)
            if drugs:
                target_drug_id = drugs[0]["id"]
                idx = self.drug_combo.findData(target_drug_id)
                if idx >= 0:
                    self.drug_combo.blockSignals(True)
                    self.drug_combo.setCurrentIndex(idx)
                    self.drug_combo.blockSignals(False)
                self._items = DrugDAO.get_substitutes(target_drug_id)
            else:
                self._items = DrugDAO.search_substitutes(name)

        self._populate_table(self._items, query=name)

    def _on_combo_activated(self, index: int):
        drug_id = self.drug_combo.itemData(index)
        if drug_id is not None:
            self._items = DrugDAO.get_substitutes(drug_id)
            self._populate_table(self._items)
        else:
            self.clear_all_fields(clear_text=True)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if self.table.hasFocus() and self.table.currentRow() >= 0:
                self._on_select_item()
                return
        super().keyPressEvent(event)

    def _load_drugs(self):
        self._block_search = True
        self.drug_combo.blockSignals(True)
        self.drug_combo.clear()
        self.drug_combo.addItem("-- Select Drug / Ingredient --", None)
        self._drugs = DrugDAO.get_all()
        for d in self._drugs:
            self.drug_combo.addItem(d["drug_name"], d["id"])
        if not self._initial_item_id:
            self.drug_combo.setCurrentIndex(-1)
            self.drug_combo.lineEdit().clear()
        self.drug_combo.blockSignals(False)
        self._block_search = False

    def _on_show_clicked(self):
        if hasattr(self, "_completer") and self._completer.popup():
            self._completer.popup().hide()

        drug_id = self.drug_combo.currentData()
        if drug_id is None:
            # Try to match by current text
            text = self.drug_combo.currentText().strip()
            for d in self._drugs:
                if d["drug_name"].strip().upper() == text.upper():
                    drug_id = d["id"]
                    break

        if drug_id is not None:
            self._items = DrugDAO.get_substitutes(drug_id)
            self._populate_table(self._items)
            return

        text = self.drug_combo.currentText().strip()
        if text and text != "-- Select Drug / Ingredient --":
            # Search substitutes by text
            items = DrugDAO.search_substitutes(text)
            if items:
                self._items = items
                self._populate_table(self._items, query=text)
                return
            else:
                self.table.setRowCount(0)
                self.empty_label.setText("No matching medicines found.")
                self.empty_label.setVisible(True)
                self.status_lbl.setText("Found 0 matching items")
                self.select_btn.setEnabled(False)
                return

        self.table.setRowCount(0)
        self.empty_label.setText("Please select a valid drug from the list.")
        self.empty_label.setVisible(True)
        self.status_lbl.setText("")
        self.select_btn.setEnabled(False)

    def _populate_table(self, items: list[dict], query: str = ""):
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(items))

        for row, it in enumerate(items):
            # Item Name
            name_item = QTableWidgetItem(it.get("item_name") or "")
            name_item.setData(Qt.UserRole, it.get("item_id"))
            self.table.setItem(row, 0, name_item)

            # Unit
            unit_item = QTableWidgetItem(it.get("unit_name") or "")
            unit_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 1, unit_item)

            # MRP (shows batch-specific MRP or variation across available batches)
            min_val = float(it.get("min_mrp", it.get("mrp", 0.0)))
            max_val = float(it.get("max_mrp", it.get("mrp", 0.0)))
            has_variation = it.get("has_variation", False)

            if has_variation and min_val != max_val:
                min_s = str(int(min_val)) if min_val.is_integer() else f"{min_val:.2f}"
                max_s = str(int(max_val)) if max_val.is_integer() else f"{max_val:.2f}"
                mrp_str = f"{min_s} - {max_s} (Varies)"
            else:
                mrp_str = str(int(min_val)) if min_val.is_integer() else f"{min_val:.2f}"

            mrp_item = NumericTableWidgetItem(mrp_str, min_val)
            mrp_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

            batches = it.get("saleable_batches", [])
            if batches:
                lines = [
                    f"Batch {b['batch_no']}: MRP ₹{float(b.get('mrp', 0)):.2f} "
                    f"(Exp: {b.get('expiry', '-')}, Avail: {b.get('stock_qty', 0):.0f})"
                    for b in batches
                ]
                mrp_item.setToolTip("\n".join(lines))
            else:
                mrp_item.setToolTip("No stock currently available in saleable batches.")

            self.table.setItem(row, 2, mrp_item)

        self.table.setSortingEnabled(True)

        if not items:
            if query:
                self.empty_label.setText(f"No matching products exist for '{query}'.")
            else:
                self.empty_label.setText("No matching products exist in Item Master for this drug.")
            self.empty_label.setVisible(True)
            self.status_lbl.setText("Found 0 matching items")
            self.selected_item_id = None
            self.select_btn.setEnabled(False)
        else:
            self.empty_label.setVisible(False)
            self.status_lbl.setText(f"Found {len(items)} matching items")
            self.table.selectRow(0)
            self._on_selection_changed()

    def _on_selection_changed(self):
        selected_rows = self.table.selectionModel().selectedRows()
        if selected_rows:
            row = selected_rows[0].row()
            item = self.table.item(row, 0)
            if item is not None:
                self.selected_item_id = item.data(Qt.UserRole)
                self.select_btn.setEnabled(True)
                return
        self.selected_item_id = None
        self.select_btn.setEnabled(False)

    def _on_row_double_clicked(self, index):
        self._on_select_item()

    def _on_select_item(self):
        row = self.table.currentRow()
        if row < 0:
            return
        item = self.table.item(row, 0)
        if item is not None:
            self.selected_item_id = item.data(Qt.UserRole)
            if self.selected_item_id:
                self.item_selected.emit(self.selected_item_id)
                self.accept()

    def refresh_theme(self):
        p = palette()
        self.setStyleSheet(f"QDialog {{ background-color: {p['surface']}; color: {p['text']}; }}")
        self.drug_lbl.setStyleSheet(f"color: {p['text']}; font-size: {TYPE_FORM_LABEL}px; font-weight: bold;")
        self.drug_combo.setStyleSheet(_fresh_combo_style(p))
        if hasattr(self, "_completer") and self._completer.popup():
            self._completer.popup().setStyleSheet(_fresh_completer_popup_style(p))
        self.show_btn.setStyleSheet(_fresh_btn_style(p["accent"], p))
        self.table.setStyleSheet(_fresh_table_style(p))
        self.table.horizontalHeader().setStyleSheet(_fresh_header_style(p))
        self.empty_label.setStyleSheet(f"color: {p['text_dim']}; font-size: {TYPE_HINT}px; font-style: italic;")
        self.status_lbl.setStyleSheet(f"color: {p['text_dim']}; font-size: {TYPE_HINT}px;")
        self.select_btn.setStyleSheet(_fresh_btn_style(p["accent"], p))
        self.close_btn.setStyleSheet(_fresh_btn_style(p["text_dim"], p))


# ---------------------------------------------------------------------------
# 2. Demand Order Dialog
# ---------------------------------------------------------------------------

class DemandOrderDialog(QDialog):
    """Searchable report table of items requiring reorder (current stock <= reorder level)."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Items Demand Order")
        self.setModal(True)
        self.resize(960, 560)

        self._all_records: list[dict] = []
        self._displayed_records: list[dict] = []

        self._build_ui()
        self.refresh_data()
        self.refresh_theme()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        # Top Bar: Search + Refresh
        top_bar = QHBoxLayout()
        top_bar.setSpacing(8)

        self.search_lbl = QLabel("Search:")
        self.search_lbl.setStyleSheet(f"font-size: {TYPE_FORM_LABEL}px; font-weight: bold;")
        top_bar.addWidget(self.search_lbl)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search item name or supplier...")
        self.search_edit.textChanged.connect(self._filter_records)
        top_bar.addWidget(self.search_edit, 1)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setFixedHeight(30)
        self.refresh_btn.clicked.connect(self.refresh_data)
        top_bar.addWidget(self.refresh_btn)

        root.addLayout(top_bar)

        # Table
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([
            "Item Name", "Unit", "Current Stock", "Reorder Level", "Supplier", "Contact Number"
        ])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setSortingEnabled(True)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        header.setSectionResizeMode(3, QHeaderView.Fixed)
        header.setSectionResizeMode(4, QHeaderView.Interactive)
        header.setSectionResizeMode(5, QHeaderView.Interactive)

        self.table.setColumnWidth(1, 90)
        self.table.setColumnWidth(2, 110)
        self.table.setColumnWidth(3, 110)
        self.table.setColumnWidth(4, 200)
        self.table.setColumnWidth(5, 150)

        root.addWidget(self.table, 1)

        # Empty State Message Label
        self.empty_label = QLabel("No items currently require reordering.")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setStyleSheet(f"font-size: {TYPE_HINT}px; font-style: italic; padding: 20px;")
        root.addWidget(self.empty_label)
        self.empty_label.setVisible(False)

        # Bottom Bar: Summary + Close
        bottom_bar = QHBoxLayout()
        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet(f"font-size: {TYPE_HINT}px;")
        bottom_bar.addWidget(self.status_lbl)

        bottom_bar.addStretch()

        self.close_btn = QPushButton("Close")
        self.close_btn.setFixedHeight(30)
        self.close_btn.clicked.connect(self.reject)
        bottom_bar.addWidget(self.close_btn)

        root.addLayout(bottom_bar)

    def refresh_data(self):
        self._all_records = StockDAO.get_demand_order_items()
        self._filter_records()

    def _filter_records(self):
        query = self.search_edit.text().strip().upper()
        if not query:
            self._displayed_records = list(self._all_records)
        else:
            self._displayed_records = [
                r for r in self._all_records
                if query in str(r.get("item_name") or "").upper()
                or query in str(r.get("supplier_name") or "").upper()
                or query in str(r.get("contact_no") or "").upper()
            ]

        self._populate_table()

    def _populate_table(self):
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self._displayed_records))

        for row, r in enumerate(self._displayed_records):
            # Item Name
            name_item = QTableWidgetItem(r.get("item_name") or "")
            name_item.setData(Qt.UserRole, r.get("item_id"))
            self.table.setItem(row, 0, name_item)

            # Unit
            unit_item = QTableWidgetItem(r.get("unit_name") or "")
            unit_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 1, unit_item)

            # Current Stock
            stock_val = float(r.get("current_stock") or 0.0)
            stock_str = str(int(stock_val)) if stock_val.is_integer() else f"{stock_val:.2f}"
            stock_item = NumericTableWidgetItem(stock_str, stock_val)
            stock_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(row, 2, stock_item)

            # Reorder Level
            reorder_val = int(r.get("reorder_stock_level") or 0)
            reorder_item = NumericTableWidgetItem(str(reorder_val), reorder_val)
            reorder_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(row, 3, reorder_item)

            # Supplier
            sup_name = r.get("supplier_name") or "-"
            sup_item = QTableWidgetItem(sup_name)
            self.table.setItem(row, 4, sup_item)

            # Contact Number
            contact_str = r.get("contact_no") or "-"
            contact_item = QTableWidgetItem(contact_str)
            self.table.setItem(row, 5, contact_item)

        self.table.setSortingEnabled(True)

        count = len(self._displayed_records)
        if count == 0:
            if not self._all_records:
                self.empty_label.setText("No items currently require reordering.")
            else:
                self.empty_label.setText("No items match your search filter.")
            self.empty_label.setVisible(True)
            self.status_lbl.setText("Showing 0 items")
        else:
            self.empty_label.setVisible(False)
            self.status_lbl.setText(f"Showing {count} item records requiring reorder")

    def refresh_theme(self):
        p = palette()
        self.setStyleSheet(f"QDialog {{ background-color: {p['surface']}; color: {p['text']}; }}")
        self.search_lbl.setStyleSheet(f"color: {p['text']}; font-size: {TYPE_FORM_LABEL}px; font-weight: bold;")
        self.search_edit.setStyleSheet(_fresh_input_style(p))
        self.refresh_btn.setStyleSheet(_fresh_btn_style(p["accent"], p))
        self.table.setStyleSheet(_fresh_table_style(p))
        self.table.horizontalHeader().setStyleSheet(_fresh_header_style(p))
        self.empty_label.setStyleSheet(f"color: {p['text_dim']}; font-size: {TYPE_HINT}px; font-style: italic;")
        self.status_lbl.setStyleSheet(f"color: {p['text_dim']}; font-size: {TYPE_HINT}px;")
        self.close_btn.setStyleSheet(_fresh_btn_style(p["text_dim"], p))


# ---------------------------------------------------------------------------
# 3. Customer Balance Dialog
# ---------------------------------------------------------------------------

class CustomerBalanceDialog(QDialog):
    """Customer Balance report dialog with search, sorting, totals, and report printing."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("CUSTOMER BALANCE LIST")
        self.setModal(True)
        self.resize(960, 600)

        self._all_records: list[dict] = []
        self._displayed_records: list[dict] = []

        self._build_ui()
        self.refresh_data()
        self.refresh_theme()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        # Top Bar: Search + Refresh + Print
        top_bar = QHBoxLayout()
        top_bar.setSpacing(8)

        self.search_lbl = QLabel("Search:")
        self.search_lbl.setStyleSheet(f"font-size: {TYPE_FORM_LABEL}px; font-weight: bold;")
        top_bar.addWidget(self.search_lbl)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search customer name, address, contact...")
        self.search_edit.textChanged.connect(self._filter_records)
        top_bar.addWidget(self.search_edit, 1)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setFixedHeight(30)
        self.refresh_btn.clicked.connect(self.refresh_data)
        top_bar.addWidget(self.refresh_btn)

        self.print_btn = QPushButton("Print / PDF")
        self.print_btn.setFixedHeight(30)
        self.print_btn.clicked.connect(self._on_print_report)
        top_bar.addWidget(self.print_btn)

        root.addLayout(top_bar)

        # Table
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels([
            "Sr. No.", "Customer Name", "Address", "Contact Number", "Outstanding Balance"
        ])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setSortingEnabled(True)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Interactive)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.Interactive)
        header.setSectionResizeMode(4, QHeaderView.Fixed)

        self.table.setColumnWidth(0, 65)
        self.table.setColumnWidth(1, 230)
        self.table.setColumnWidth(3, 140)
        self.table.setColumnWidth(4, 150)

        root.addWidget(self.table, 1)

        # Empty State Message Label
        self.empty_label = QLabel("No customers found.")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setStyleSheet(f"font-size: {TYPE_HINT}px; font-style: italic; padding: 20px;")
        root.addWidget(self.empty_label)
        self.empty_label.setVisible(False)

        # Footer Bar: Records Count + Total Balance + Close
        footer_bar = QHBoxLayout()
        self.records_lbl = QLabel("")
        self.records_lbl.setStyleSheet(f"font-size: {TYPE_HINT}px;")
        footer_bar.addWidget(self.records_lbl)

        footer_bar.addStretch()

        self.total_lbl = QLabel("")
        self.total_lbl.setStyleSheet(
            f"font-size: {TYPE_FORM_LABEL}px; font-weight: bold;"
        )
        footer_bar.addWidget(self.total_lbl)

        footer_bar.addSpacing(16)

        self.close_btn = QPushButton("Close")
        self.close_btn.setFixedHeight(30)
        self.close_btn.clicked.connect(self.reject)
        footer_bar.addWidget(self.close_btn)

        root.addLayout(footer_bar)

    def refresh_data(self):
        raw = PartyWiseReportDAO.get_customer_balances()
        self._all_records = []
        for idx, r in enumerate(raw, 1):
            closing = float(r.get("ledger_balance") or 0.0)
            bal_type = r.get("ledger_balance_type") or "Debit"
            # For Sundry Debtors: Debit is positive (customer owes us), Credit is negative
            signed_bal = closing if bal_type == "Debit" else -closing
            self._all_records.append({
                "sr_no": idx,
                "id": r.get("customer_id"),
                "name": r.get("customer_name") or "",
                "address": r.get("address") or "",
                "contact_no": r.get("contact_no") or "",
                "balance": signed_bal,
                "balance_type": bal_type,
                "has_transactions": r.get("has_transactions", True),
            })
        self._filter_records()

    def _filter_records(self):
        query = self.search_edit.text().strip().upper()
        if not query:
            self._displayed_records = list(self._all_records)
        else:
            self._displayed_records = [
                r for r in self._all_records
                if query in r["name"].upper()
                or query in r["address"].upper()
                or query in r["contact_no"].upper()
            ]

        self._populate_table()

    def _populate_table(self):
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self._displayed_records))

        total_balance = 0.0

        for row, r in enumerate(self._displayed_records):
            # Sr. No.
            sr_val = r["sr_no"]
            sr_item = NumericTableWidgetItem(str(sr_val), sr_val)
            sr_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 0, sr_item)

            # Customer Name
            name_item = QTableWidgetItem(r["name"])
            name_item.setData(Qt.UserRole, r["id"])
            self.table.setItem(row, 1, name_item)

            # Address
            addr_item = QTableWidgetItem(r["address"])
            self.table.setItem(row, 2, addr_item)

            # Contact Number
            contact_item = QTableWidgetItem(r["contact_no"])
            self.table.setItem(row, 3, contact_item)

            # Outstanding Balance
            bal = r["balance"]
            total_balance += bal
            bal_str = str(int(bal)) if bal == int(bal) else f"{bal:.2f}"
            bal_item = NumericTableWidgetItem(bal_str, bal)
            bal_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            dir_text = "Debit (Dr)" if bal >= 0 else "Credit (Cr)"
            bal_item.setToolTip(f"Outstanding: {bal:.2f} [{dir_text}]")
            self.table.setItem(row, 4, bal_item)

        self.table.setSortingEnabled(True)

        count = len(self._displayed_records)
        if count == 0:
            self.empty_label.setVisible(True)
            self.records_lbl.setText("Showing 0 customers")
            self.total_lbl.setText("Total Outstanding: 0.00")
        else:
            self.empty_label.setVisible(False)
            self.records_lbl.setText(f"Showing {count} customers")
            tot_str = f"{int(total_balance):,}" if total_balance == int(total_balance) else f"{total_balance:,.2f}"
            dir_text = "Dr" if total_balance >= 0 else "Cr"
            self.total_lbl.setText(f"Total Outstanding: {tot_str} {dir_text}")

    def _on_print_report(self):
        if not self._displayed_records:
            QMessageBox.information(self, "Print Report", "No records to print.")
            return
        pages = generate_customer_balance_report_pages(self._displayed_records)
        print_or_export_report_pages(pages, parent=self)

    def refresh_theme(self):
        p = palette()
        self.setStyleSheet(f"QDialog {{ background-color: {p['surface']}; color: {p['text']}; }}")
        self.search_lbl.setStyleSheet(f"color: {p['text']}; font-size: {TYPE_FORM_LABEL}px; font-weight: bold;")
        self.search_edit.setStyleSheet(_fresh_input_style(p))
        self.refresh_btn.setStyleSheet(_fresh_btn_style(p["accent"], p))
        self.print_btn.setStyleSheet(_fresh_btn_style(p["accent"], p))
        self.table.setStyleSheet(_fresh_table_style(p))
        self.table.horizontalHeader().setStyleSheet(_fresh_header_style(p))
        self.empty_label.setStyleSheet(f"color: {p['text_dim']}; font-size: {TYPE_HINT}px; font-style: italic;")
        self.records_lbl.setStyleSheet(f"color: {p['text_dim']}; font-size: {TYPE_HINT}px;")
        self.total_lbl.setStyleSheet(f"color: {p['text']}; font-size: {TYPE_FORM_LABEL}px; font-weight: bold;")
        self.close_btn.setStyleSheet(_fresh_btn_style(p["text_dim"], p))


# ---------------------------------------------------------------------------
# 4. Supplier Balance Dialog
# ---------------------------------------------------------------------------

class SupplierBalanceDialog(QDialog):
    """Supplier Balance report dialog with search, sorting, totals, and report printing."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("SUPPLIER BALANCE LIST")
        self.setModal(True)
        self.resize(960, 600)

        self._all_records: list[dict] = []
        self._displayed_records: list[dict] = []

        self._build_ui()
        self.refresh_data()
        self.refresh_theme()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        # Top Bar: Search + Refresh + Print
        top_bar = QHBoxLayout()
        top_bar.setSpacing(8)

        self.search_lbl = QLabel("Search:")
        self.search_lbl.setStyleSheet(f"font-size: {TYPE_FORM_LABEL}px; font-weight: bold;")
        top_bar.addWidget(self.search_lbl)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search supplier name, address, contact...")
        self.search_edit.textChanged.connect(self._filter_records)
        top_bar.addWidget(self.search_edit, 1)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setFixedHeight(30)
        self.refresh_btn.clicked.connect(self.refresh_data)
        top_bar.addWidget(self.refresh_btn)

        self.print_btn = QPushButton("Print / PDF")
        self.print_btn.setFixedHeight(30)
        self.print_btn.clicked.connect(self._on_print_report)
        top_bar.addWidget(self.print_btn)

        root.addLayout(top_bar)

        # Table
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels([
            "Sr. No.", "Supplier Name", "Address", "Contact Number", "Outstanding Balance"
        ])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setSortingEnabled(True)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Interactive)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.Interactive)
        header.setSectionResizeMode(4, QHeaderView.Fixed)

        self.table.setColumnWidth(0, 65)
        self.table.setColumnWidth(1, 240)
        self.table.setColumnWidth(3, 150)
        self.table.setColumnWidth(4, 150)

        root.addWidget(self.table, 1)

        # Empty State Message Label
        self.empty_label = QLabel("No suppliers found.")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setStyleSheet(f"font-size: {TYPE_HINT}px; font-style: italic; padding: 20px;")
        root.addWidget(self.empty_label)
        self.empty_label.setVisible(False)

        # Footer Bar: Records Count + Total Balance + Close
        footer_bar = QHBoxLayout()
        self.records_lbl = QLabel("")
        self.records_lbl.setStyleSheet(f"font-size: {TYPE_HINT}px;")
        footer_bar.addWidget(self.records_lbl)

        footer_bar.addStretch()

        self.total_lbl = QLabel("")
        self.total_lbl.setStyleSheet(
            f"font-size: {TYPE_FORM_LABEL}px; font-weight: bold;"
        )
        footer_bar.addWidget(self.total_lbl)

        footer_bar.addSpacing(16)

        self.close_btn = QPushButton("Close")
        self.close_btn.setFixedHeight(30)
        self.close_btn.clicked.connect(self.reject)
        footer_bar.addWidget(self.close_btn)

        root.addLayout(footer_bar)

    def refresh_data(self):
        raw = PartyWiseReportDAO.get_supplier_balances()
        self._all_records = []
        for idx, r in enumerate(raw, 1):
            closing = float(r.get("ledger_balance") or 0.0)
            bal_type = r.get("ledger_balance_type") or "Credit"
            # For Sundry Creditors: Credit is positive (we owe supplier), Debit is negative
            signed_bal = closing if bal_type == "Credit" else -closing
            self._all_records.append({
                "sr_no": idx,
                "id": r.get("supplier_id"),
                "name": r.get("supplier_name") or "",
                "address": r.get("address") or "",
                "contact_no": r.get("contact_no") or "",
                "balance": signed_bal,
                "balance_type": bal_type,
                "has_transactions": r.get("has_transactions", True),
            })
        self._filter_records()

    def _filter_records(self):
        query = self.search_edit.text().strip().upper()
        if not query:
            self._displayed_records = list(self._all_records)
        else:
            self._displayed_records = [
                r for r in self._all_records
                if query in r["name"].upper()
                or query in r["address"].upper()
                or query in r["contact_no"].upper()
            ]

        self._populate_table()

    def _populate_table(self):
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self._displayed_records))

        total_balance = 0.0

        for row, r in enumerate(self._displayed_records):
            # Sr. No.
            sr_val = r["sr_no"]
            sr_item = NumericTableWidgetItem(str(sr_val), sr_val)
            sr_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 0, sr_item)

            # Supplier Name
            name_item = QTableWidgetItem(r["name"])
            name_item.setData(Qt.UserRole, r["id"])
            self.table.setItem(row, 1, name_item)

            # Address
            addr_item = QTableWidgetItem(r["address"])
            self.table.setItem(row, 2, addr_item)

            # Contact Number
            contact_item = QTableWidgetItem(r["contact_no"])
            self.table.setItem(row, 3, contact_item)

            # Outstanding Balance
            bal = r["balance"]
            total_balance += bal
            bal_str = str(int(bal)) if bal == int(bal) else f"{bal:.2f}"
            bal_item = NumericTableWidgetItem(bal_str, bal)
            bal_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            dir_text = "Credit (Cr)" if bal >= 0 else "Debit (Dr)"
            tip = f"Outstanding: {bal:.2f} [{dir_text}]"
            if not r["has_transactions"]:
                tip += " (No ledger transactions or opening balance recorded)"
            bal_item.setToolTip(tip)
            self.table.setItem(row, 4, bal_item)

        self.table.setSortingEnabled(True)

        count = len(self._displayed_records)
        if count == 0:
            self.empty_label.setVisible(True)
            self.records_lbl.setText("Showing 0 suppliers")
            self.total_lbl.setText("Total Outstanding: 0.00")
        else:
            self.empty_label.setVisible(False)
            self.records_lbl.setText(f"Showing {count} suppliers")
            tot_str = f"{int(total_balance):,}" if total_balance == int(total_balance) else f"{total_balance:,.2f}"
            dir_text = "Cr" if total_balance >= 0 else "Dr"
            self.total_lbl.setText(f"Total Outstanding: {tot_str} {dir_text}")

    def _on_print_report(self):
        if not self._displayed_records:
            QMessageBox.information(self, "Print Report", "No records to print.")
            return
        pages = generate_supplier_balance_report_pages(self._displayed_records)
        print_or_export_report_pages(pages, parent=self)

    def refresh_theme(self):
        p = palette()
        self.setStyleSheet(f"QDialog {{ background-color: {p['surface']}; color: {p['text']}; }}")
        self.search_lbl.setStyleSheet(f"color: {p['text']}; font-size: {TYPE_FORM_LABEL}px; font-weight: bold;")
        self.search_edit.setStyleSheet(_fresh_input_style(p))
        self.refresh_btn.setStyleSheet(_fresh_btn_style(p["accent"], p))
        self.print_btn.setStyleSheet(_fresh_btn_style(p["accent"], p))
        self.table.setStyleSheet(_fresh_table_style(p))
        self.table.horizontalHeader().setStyleSheet(_fresh_header_style(p))
        self.empty_label.setStyleSheet(f"color: {p['text_dim']}; font-size: {TYPE_HINT}px; font-style: italic;")
        self.records_lbl.setStyleSheet(f"color: {p['text_dim']}; font-size: {TYPE_HINT}px;")
        self.total_lbl.setStyleSheet(f"color: {p['text']}; font-size: {TYPE_FORM_LABEL}px; font-weight: bold;")
        self.close_btn.setStyleSheet(_fresh_btn_style(p["text_dim"], p))


# ---------------------------------------------------------------------------
# Crystal Report Page Builders for Printing / PDF
# ---------------------------------------------------------------------------

def generate_customer_balance_report_pages(records: list[dict]) -> list[ReportPage]:
    store_name, store_address = get_default_store_identity()
    header = ReportHeaderData(
        store_name=store_name,
        store_address=store_address,
        header_line_1="",
        header_line_2="SUNDRY DEBTORS",
    )

    widths = [45.0, 185.0, 224.0, 150.0, 120.0]  # sum == 724.0 px (A4 portrait content width)
    aligns = ["center", "left", "left", "left", "right"]

    table_header_block = ReportBlock(
        kind=BlockKind.TABLE_HEADER,
        height=22.0,
        data={
            "columns": ["SrNo", "Name", "Address", "Contact No", "Balance"],
            "widths": widths,
            "aligns": aligns,
        },
    )

    blocks: list[ReportBlock] = [table_header_block]
    total_balance = 0.0

    for r in records:
        bal = float(r.get("balance") or 0.0)
        total_balance += bal
        bal_str = str(int(bal)) if bal == int(bal) else f"{bal:.2f}"
        blocks.append(
            ReportBlock(
                kind=BlockKind.DATA_ROW,
                height=18.0,
                data={
                    "cells": [
                        str(r.get("sr_no", "")),
                        str(r.get("name", "")),
                        str(r.get("address", "")),
                        str(r.get("contact_no", "")),
                        bal_str,
                    ],
                    "widths": widths,
                    "aligns": aligns,
                },
            )
        )

    # Grand total block
    tot_str = str(int(total_balance)) if total_balance == int(total_balance) else f"{total_balance:.2f}"
    custom_cells = [
        {"width": sum(widths[:-1]), "text": "Total :", "align": "right"},
        {"width": widths[-1], "text": tot_str, "align": "right"},
    ]
    blocks.append(
        ReportBlock(
            kind=BlockKind.GRAND_TOTAL,
            height=22.0,
            data={"custom_cells": custom_cells, "widths": widths},
        )
    )

    return paginate_report_blocks(header, blocks, table_header_block)


def generate_supplier_balance_report_pages(records: list[dict]) -> list[ReportPage]:
    store_name, store_address = get_default_store_identity()
    header = ReportHeaderData(
        store_name=store_name,
        store_address=store_address,
        header_line_1="",
        header_line_2="SUNDRY CREDITORS",
    )

    widths = [45.0, 185.0, 224.0, 150.0, 120.0]
    aligns = ["center", "left", "left", "left", "right"]

    table_header_block = ReportBlock(
        kind=BlockKind.TABLE_HEADER,
        height=22.0,
        data={
            "columns": ["SrNo", "Name", "Address", "Contact No", "Balance"],
            "widths": widths,
            "aligns": aligns,
        },
    )

    blocks: list[ReportBlock] = [table_header_block]
    total_balance = 0.0

    for r in records:
        bal = float(r.get("balance") or 0.0)
        total_balance += bal
        bal_str = str(int(bal)) if bal == int(bal) else f"{bal:.2f}"
        blocks.append(
            ReportBlock(
                kind=BlockKind.DATA_ROW,
                height=18.0,
                data={
                    "cells": [
                        str(r.get("sr_no", "")),
                        str(r.get("name", "")),
                        str(r.get("address", "")),
                        str(r.get("contact_no", "")),
                        bal_str,
                    ],
                    "widths": widths,
                    "aligns": aligns,
                },
            )
        )

    tot_str = str(int(total_balance)) if total_balance == int(total_balance) else f"{total_balance:.2f}"
    custom_cells = [
        {"width": sum(widths[:-1]), "text": "Total :", "align": "right"},
        {"width": widths[-1], "text": tot_str, "align": "right"},
    ]
    blocks.append(
        ReportBlock(
            kind=BlockKind.GRAND_TOTAL,
            height=22.0,
            data={"custom_cells": custom_cells, "widths": widths},
        )
    )

    return paginate_report_blocks(header, blocks, table_header_block)
