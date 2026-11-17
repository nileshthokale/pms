from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, QDate, QEvent, QEvent, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from database.debit_note_dao import DebitNoteDAO
from database import financial_year
from database.document_printing import DocumentPrintError, generate_debit_note
from database.item_dao import ItemDAO
from database.purchase_dao import pack_factor
from database.supplier_dao import SupplierDAO
from core.doc_formatter import format_document_number

from ui.components import ConstrainedComboBox, SearchableComboBox, TableComboBox
from ui.theme import combo_subcontrols, date_subcontrols, palette


def _get_palette():
    return palette()


def _safe_float(text: str, default: float = 0.0) -> float:
    try:
        t = str(text).strip()
        return float(t) if t else default
    except (ValueError, TypeError):
        return default


def _parse_header_less(text: str, subtotal: float) -> tuple[float, float]:
    """Parse header Less text into (less_amount, discount_pct).

    Supports percentage format (e.g. '5%', '5.0%') or flat amount (e.g. '10.00', '15').
    Returns (less_amount, discount_pct) rounded to 2 decimal places.
    """
    raw = (text or "").strip()
    if not raw:
        return 0.0, 0.0
    if "%" in raw:
        try:
            pct = float(raw.replace("%", "").strip())
        except ValueError:
            pct = 0.0
        pct = max(0.0, min(100.0, pct))
        less_amt = round(subtotal * (pct / 100.0), 2)
        return less_amt, pct
    else:
        try:
            amt = float(raw)
        except ValueError:
            amt = 0.0
        amt = max(0.0, amt)
        less_amt = min(amt, subtotal) if subtotal > 0 else amt
        return less_amt, 0.0


# ======================================================================
# Return Item line data class
# ======================================================================

class _ReturnItemRow:
    """One line item being returned to supplier."""

    def __init__(
        self,
        item_id: int,
        item_name: str,
        stock_batch_id: int,
        batch_no: str,
        expiry: str,
        pack_size: str,
        rate: float,
        mrp: float,
        return_qty: float,
        free_qty: float,
        less_amount: float,
        amount: float,
        return_reason: str,
        price_factor: str = "RATE",
        price_factor_num: float = 1.0,
    ):
        self.item_id = item_id
        self.item_name = item_name
        self.stock_batch_id = stock_batch_id
        self.batch_no = batch_no
        self.expiry = expiry
        self.pack_size = pack_size
        self.rate = rate
        self.mrp = mrp
        self.return_qty = return_qty
        self.free_qty = free_qty
        self.less_amount = less_amount
        self.amount = amount
        self.return_reason = return_reason
        self.price_factor = price_factor
        self.price_factor_num = price_factor_num

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "stock_batch_id": self.stock_batch_id,
            "batch_no": self.batch_no,
            "expiry": self.expiry,
            "pack_size": self.pack_size,
            "rate": self.rate,
            "mrp": self.mrp,
            "return_qty": self.return_qty,
            "free_qty": self.free_qty,
            "less_amount": self.less_amount,
            "amount": self.amount,
            "return_reason": self.return_reason,
            "price_factor": self.price_factor_num,
            "is_pack_qty": True,
        }


# ======================================================================
# Item Entry Bar for Debit Note
# ======================================================================

class _ItemEntryBar(QWidget):
    """Horizontal bar matching Pharma-WINNER item entry row."""

    @staticmethod
    def _detect_unit_name(item_name: str, unit_name: str = "") -> str:
        combined = f"{item_name} {unit_name}".upper()
        if any(w in combined for w in ["CAP", "CAPSULE", "CAPS"]):
            return "Capsules"
        if any(w in combined for w in ["TAB", "TABLET", "TABS"]):
            return "Tablets"
        if any(w in combined for w in ["INJ", "INJECTION"]):
            return "Vials"
        if any(w in combined for w in ["SYR", "SYRUP", "SUSP", "SUSPENSION", "BOT", "BOTTLE"]):
            return "Bottles"
        if item_name and "(" in item_name and item_name.endswith(")"):
            extracted = item_name.rsplit("(", 1)[1].rstrip(")").strip()
            if extracted:
                return extracted
        return "Units"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._supplier_id: int | None = None
        self._build_ui()

    def _build_ui(self):
        p = _get_palette()
        grid = QGridLayout(self)
        grid.setContentsMargins(6, 4, 6, 4)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)

        def _make_lbl(text: str, bold: bool = False):
            l = QLabel(text)
            f = "bold" if bold else "normal"
            l.setStyleSheet(f"color: {p['text']}; font-size: 13px; font-weight: {f}; font-family: 'Segoe UI';")
            return l

        # Col 0: Item Name label + Expired Only checkbox in header row
        item_hdr = QHBoxLayout()
        item_hdr.setContentsMargins(0, 0, 0, 0)
        item_hdr.setSpacing(8)
        item_hdr.addWidget(_make_lbl("* Item Name", bold=True))
        item_hdr.addStretch()

        self.expired_only_cb = QCheckBox("Expired Only")
        self.expired_only_cb.setStyleSheet(f"color: {p['text']}; font-size: 12px; font-weight: normal; font-family: 'Segoe UI';")
        self.expired_only_cb.toggled.connect(self._on_expired_toggled)
        item_hdr.addWidget(self.expired_only_cb)
        grid.addLayout(item_hdr, 0, 0)

        self.item_combo = SearchableComboBox(placeholder="Type medicine name to search...")
        self.item_combo.setMinimumWidth(260)
        self.item_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        grid.addWidget(self.item_combo, 1, 0)

        # Col 1: Batch #
        grid.addWidget(_make_lbl("Batch #"), 0, 1)
        self.batch_combo = TableComboBox(placeholder="", min_width=320)
        self.batch_combo.setMinimumWidth(160)
        self.batch_combo.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.batch_combo.selection_changed.connect(self._on_batch_selected)
        grid.addWidget(self.batch_combo, 1, 1)

        # Col 2: Expiry
        grid.addWidget(_make_lbl("Expiry"), 0, 2)
        self.expiry_edit = QLineEdit()
        self.expiry_edit.setFixedWidth(80)
        self.expiry_edit.setReadOnly(True)
        self.expiry_edit.setFocusPolicy(Qt.NoFocus)
        self.expiry_edit.setAlignment(Qt.AlignCenter)
        grid.addWidget(self.expiry_edit, 1, 2)

        # Col 3: Pack Size
        grid.addWidget(_make_lbl("Pack Size"), 0, 3)
        self.pack_edit = QLineEdit()
        self.pack_edit.setFixedWidth(70)
        self.pack_edit.setReadOnly(True)
        self.pack_edit.setFocusPolicy(Qt.NoFocus)
        self.pack_edit.setAlignment(Qt.AlignCenter)
        grid.addWidget(self.pack_edit, 1, 3)

        # Col 4: Rate
        grid.addWidget(_make_lbl("Rate"), 0, 4)
        self.rate_edit = QLineEdit("0.00")
        self.rate_edit.setFixedWidth(70)
        self.rate_edit.setAlignment(Qt.AlignRight)
        grid.addWidget(self.rate_edit, 1, 4)

        # Col 5: MRP
        grid.addWidget(_make_lbl("MRP"), 0, 5)
        self.mrp_edit = QLineEdit("0.00")
        self.mrp_edit.setFixedWidth(70)
        self.mrp_edit.setReadOnly(True)
        self.mrp_edit.setFocusPolicy(Qt.NoFocus)
        self.mrp_edit.setAlignment(Qt.AlignRight)
        grid.addWidget(self.mrp_edit, 1, 5)

        # Col 6: Return Qty
        self.return_qty_lbl = _make_lbl("Return Qty (Units)")
        grid.addWidget(self.return_qty_lbl, 0, 6)
        self.qty_edit = QLineEdit("1")
        self.qty_edit.setFixedWidth(75)
        self.qty_edit.setAlignment(Qt.AlignCenter)
        self.qty_edit.setToolTip("Return quantity in individual units (tablets/capsules)")
        grid.addWidget(self.qty_edit, 1, 6)

        # Col 7: Free Qty
        self.free_qty_lbl = _make_lbl("Free Qty (Units)")
        grid.addWidget(self.free_qty_lbl, 0, 7)
        self.free_qty_edit = QLineEdit("0")
        self.free_qty_edit.setFixedWidth(65)
        self.free_qty_edit.setAlignment(Qt.AlignCenter)
        self.free_qty_edit.setToolTip("Free quantity in individual units (tablets/capsules)")
        grid.addWidget(self.free_qty_edit, 1, 7)

        # Col 8: Less %
        grid.addWidget(_make_lbl("Less %"), 0, 8)
        self.less_edit = QLineEdit("0.00")
        self.less_edit.setFixedWidth(65)
        self.less_edit.setAlignment(Qt.AlignRight)
        grid.addWidget(self.less_edit, 1, 8)

        # Col 9: Return Reason
        grid.addWidget(_make_lbl("Return Reason"), 0, 9)
        self.reason_combo = ConstrainedComboBox()
        self.reason_combo.setMinimumWidth(130)
        self.reason_combo.addItems([
            "Purchase Return",
            "Expiry Return",
            "Breakage/Damage",
            "Slow Moving",
            "Rate Difference",
            "Other",
        ])
        grid.addWidget(self.reason_combo, 1, 9)

        # Col 10: Price Factor
        grid.addWidget(_make_lbl("Price Factor"), 0, 10)
        self.price_factor_combo = ConstrainedComboBox()
        self.price_factor_combo.setFixedWidth(90)
        self.price_factor_combo.addItems(["RATE", "MRP"])
        grid.addWidget(self.price_factor_combo, 1, 10)

        # Col 11: Add Button
        grid.addWidget(QLabel(""), 0, 11)
        self.add_btn = QPushButton("▼")
        self.add_btn.setToolTip("Add item to return list")
        self.add_btn.setFixedWidth(40)
        self.add_btn.setFixedHeight(30)
        self.add_btn.setAutoDefault(False)
        self.add_btn.setDefault(False)
        self.add_btn.setStyleSheet(
            f"QPushButton {{ background-color: {p['accent']}; color: white; "
            f"font-weight: bold; font-size: 14px; border: none; border-radius: 3px; }}"
            f"QPushButton:hover {{ background-color: {p['accent_hover']}; }}"
        )
        grid.addWidget(self.add_btn, 1, 11)

        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 1)
        for c in range(2, 12):
            grid.setColumnStretch(c, 0)

        self.item_combo.selection_changed.connect(self._on_item_selected)
        if self.item_combo.lineEdit():
            self.item_combo.lineEdit().installEventFilter(self)
        self.item_combo.installEventFilter(self)

        if self.batch_combo.lineEdit():
            self.batch_combo.lineEdit().installEventFilter(self)
        self.batch_combo.installEventFilter(self)

        # Wire keyboard flow across entry bar:
        # Item -> Batch -> Qty -> Rate -> Add -> next item
        self.item_combo.completionAccepted.connect(self._focus_batch)
        self.item_combo.returnPressed.connect(self._focus_batch)
        self.batch_combo.completionAccepted.connect(self._focus_qty)
        self.batch_combo.returnPressed.connect(self._focus_qty)
        self.qty_edit.returnPressed.connect(self._focus_rate)
        self.free_qty_edit.returnPressed.connect(self._focus_rate)
        self.rate_edit.returnPressed.connect(self.add_btn.click)
        self.less_edit.returnPressed.connect(self.add_btn.click)

        self.qty_edit.installEventFilter(self)
        self.rate_edit.installEventFilter(self)

    def _focus_batch(self):
        line = self.batch_combo.lineEdit()
        if line is not None:
            line.setFocus()
            line.selectAll()
        else:
            self.batch_combo.setFocus()

    def _focus_qty(self):
        self.qty_edit.setFocus()
        self.qty_edit.selectAll()

    def _focus_rate(self):
        self.rate_edit.setFocus()
        self.rate_edit.selectAll()

    def _commit_item_and_focus_batch(self):
        completer = self.item_combo.completer()
        popup = completer.popup() if completer else None
        committed = False
        if popup and popup.isVisible():
            cur_idx = popup.currentIndex()
            if cur_idx.isValid() and cur_idx.data(Qt.UserRole) is not None:
                self.item_combo._on_completer_index_activated(cur_idx)
                committed = True
            elif self.item_combo._completer_model.rowCount() > 0:
                first_idx = self.item_combo._completer_model.index(0, 0)
                if first_idx.isValid() and first_idx.data(Qt.UserRole) is not None:
                    self.item_combo._on_completer_index_activated(first_idx)
                    committed = True
            popup.hide()

        if not committed:
            self.item_combo.resolve_text()

        item_id = self.item_combo.currentData()
        if item_id:
            self._reload_batches(int(item_id))
            if hasattr(self.batch_combo, "lineEdit") and self.batch_combo.lineEdit():
                self.batch_combo.lineEdit().setFocus()
            else:
                self.batch_combo.setFocus()
            if self.batch_combo.count() > 1:
                QTimer.singleShot(50, self.batch_combo.showPopup)

    def _commit_batch_and_focus_qty(self):
        if hasattr(self.batch_combo, "_popup_frame") and self.batch_combo._popup_frame.isVisible():
            idx = self.batch_combo.table_view.currentIndex()
            if not idx.isValid():
                start = 1 if (self.batch_combo._table_model.rowCount() > 1 and self.batch_combo.itemData(0) is None and self.batch_combo.itemText(0).startswith("--")) else 0
                for r in range(start, self.batch_combo._table_model.rowCount()):
                    if not self.batch_combo.table_view.isRowHidden(r):
                        idx = self.batch_combo._table_model.index(r, 0)
                        break
            if idx.isValid():
                self.batch_combo._commit_row(idx.row(), emit_completion=True)
            self.batch_combo.hidePopup()
        self._focus_qty()

    def eventFilter(self, watched, event):
        if hasattr(self, "item_combo") and (watched is self.item_combo or (self.item_combo.lineEdit() and watched is self.item_combo.lineEdit())):
            if event.type() == QEvent.MouseButtonPress:
                line = self.item_combo.lineEdit()
                if line:
                    QTimer.singleShot(0, line.selectAll)
                if not self.item_combo.completer().popup().isVisible():
                    QTimer.singleShot(50, self.item_combo.show_all_suggestions)
            elif event.type() == QEvent.KeyPress:
                key = event.key()
                if key in (Qt.Key_Return, Qt.Key_Enter):
                    self._commit_item_and_focus_batch()
                    return True
                elif key == Qt.Key_Tab and not (event.modifiers() & Qt.ShiftModifier):
                    self._commit_item_and_focus_batch()
                    return True
        elif hasattr(self, "batch_combo") and (watched is self.batch_combo or (self.batch_combo.lineEdit() and watched is self.batch_combo.lineEdit())):
            if event.type() == QEvent.MouseButtonPress:
                line = self.batch_combo.lineEdit()
                if line:
                    QTimer.singleShot(0, line.selectAll)
                if self.batch_combo.count() > 1 and not getattr(self.batch_combo, "_popup_frame", None):
                    QTimer.singleShot(50, self.batch_combo.showPopup)
            elif event.type() == QEvent.KeyPress:
                key = event.key()
                if key in (Qt.Key_Return, Qt.Key_Enter):
                    self._commit_batch_and_focus_qty()
                    return True
                elif key == Qt.Key_Tab and not (event.modifiers() & Qt.ShiftModifier):
                    self._commit_batch_and_focus_qty()
                    return True
                elif key == Qt.Key_Backtab or (key == Qt.Key_Tab and (event.modifiers() & Qt.ShiftModifier)):
                    if hasattr(self.batch_combo, "_popup_frame") and self.batch_combo._popup_frame.isVisible():
                        self.batch_combo.hidePopup()
                    if self.item_combo.lineEdit():
                        self.item_combo.lineEdit().setFocus()
                        self.item_combo.lineEdit().selectAll()
                    else:
                        self.item_combo.setFocus()
                    return True
        elif hasattr(self, "qty_edit") and watched is self.qty_edit:
            if event.type() == QEvent.KeyPress:
                key = event.key()
                if key == Qt.Key_Backtab or (key == Qt.Key_Tab and (event.modifiers() & Qt.ShiftModifier)):
                    if self.batch_combo.lineEdit():
                        self.batch_combo.lineEdit().setFocus()
                        self.batch_combo.lineEdit().selectAll()
                    else:
                        self.batch_combo.setFocus()
                    return True
        elif hasattr(self, "rate_edit") and watched is self.rate_edit:
            if event.type() == QEvent.KeyPress:
                key = event.key()
                if key == Qt.Key_Backtab or (key == Qt.Key_Tab and (event.modifiers() & Qt.ShiftModifier)):
                    self.qty_edit.setFocus()
                    self.qty_edit.selectAll()
                    return True
        return super().eventFilter(watched, event)

    def set_supplier_id(self, supplier_id: int | None):
        self._supplier_id = supplier_id
        # Reload batches if item is currently selected
        item_id = self.item_combo.currentData()
        if item_id:
            self._reload_batches(item_id)

    def load_items(self):
        items = ItemDAO.get_items_for_selector()
        list_items = []
        seen_ids = set()
        for it in items:
            item_id = it.get("id")
            if item_id is None or item_id in seen_ids:
                continue
            seen_ids.add(item_id)
            uname = (it.get("unit_name") or "").strip()
            name_display = f"{it['item_name']} ({uname})" if uname else it["item_name"]
            list_items.append((name_display, item_id))
        self.item_combo.populate(list_items)

    def _on_item_selected(self, item_id: object):
        if not item_id:
            self.batch_combo.clear()
            self.batch_combo.clear_selection()
            self._clear_batch_fields()
            return
        self._reload_batches(int(item_id))

    def _on_expired_toggled(self, checked: bool):
        item_id = self.item_combo.currentData()
        if item_id:
            self._reload_batches(int(item_id))

    def _reload_batches(self, item_id: int):
        self.batch_combo.blockSignals(True)
        self.batch_combo.clear()
        self._clear_batch_fields()

        batches = DebitNoteDAO.get_batches_for_supplier_item(
            self._supplier_id, item_id, expired_only=self.expired_only_cb.isChecked()
        )
        for b in batches:
            b_no = b.get("batch_no", "")
            self.batch_combo.addItem(b_no, b, raw_name=b_no, row_data=b)

        if len(batches) == 1:
            self.batch_combo.setCurrentIndex(0)
            self._on_batch_selected(batches[0])
        else:
            self.batch_combo.clear_selection()
            self._clear_batch_fields()

        self.batch_combo.blockSignals(False)

    def _on_batch_selected(self, batch_data: object):
        if not batch_data or not isinstance(batch_data, dict):
            self._clear_batch_fields()
            return
        b = batch_data
        self.expiry_edit.setText(b.get("expiry", ""))
        self.pack_edit.setText(str(b.get("pack_size") or "1"))
        self.rate_edit.setText(f"{b.get('purchase_rate', 0.0):.2f}")
        self.mrp_edit.setText(f"{b.get('mrp', 0.0):.2f}")
        unit = self._detect_unit_name(self.item_combo.currentText())
        if hasattr(self, "return_qty_lbl"):
            self.return_qty_lbl.setText(f"Return Qty ({unit})")
        if hasattr(self, "free_qty_lbl"):
            self.free_qty_lbl.setText(f"Free Qty ({unit})")

    def _on_batch_changed(self, idx: int):
        b = self.batch_combo.currentData()
        self._on_batch_selected(b)

    def _clear_batch_fields(self):
        self.expiry_edit.clear()
        self.pack_edit.clear()
        self.rate_edit.setText("0.00")
        self.mrp_edit.setText("0.00")
        self.qty_edit.setText("1")
        self.free_qty_edit.setText("0")
        self.less_edit.setText("0.00")
        if hasattr(self, "return_qty_lbl"):
            self.return_qty_lbl.setText("Return Qty (Units)")
        if hasattr(self, "free_qty_lbl"):
            self.free_qty_lbl.setText("Free Qty (Units)")

    def clear(self):
        self.item_combo.clear_selection()
        self.batch_combo.clear()
        self.batch_combo.clear_selection()
        self._clear_batch_fields()
        self.qty_edit.setText("1")
        self.free_qty_edit.setText("0")
        self.rate_edit.setText("0.00")
        self.less_edit.setText("0.00")
        line = self.batch_combo.lineEdit()
        if line:
            line.setPlaceholderText("Select item first")

    def get_current_data(self) -> dict | None:
        item_id = self.item_combo.currentData()
        batch_data = self.batch_combo.currentData()
        if not item_id or not batch_data:
            return None

        return {
            "item_id": int(item_id),
            "item_name": self.item_combo.currentText(),
            "stock_batch_id": batch_data["id"],
            "batch_no": batch_data["batch_no"],
            "expiry": self.expiry_edit.text().strip(),
            "pack_size": self.pack_edit.text().strip() or "1",
            "rate": _safe_float(self.rate_edit.text(), 0.0),
            "mrp": _safe_float(self.mrp_edit.text(), 0.0),
            "return_qty": _safe_float(self.qty_edit.text(), 0.0),
            "free_qty": _safe_float(self.free_qty_edit.text(), 0.0),
            "less_pct": _safe_float(self.less_edit.text(), 0.0),
            "return_reason": self.reason_combo.currentText(),
            "price_factor": self.price_factor_combo.currentText(),
            "available_stock": float(batch_data.get("stock_qty", 0.0)),
        }


# ======================================================================
# Debit Note Entry Dialog (Modal Form)
# ======================================================================

class _DebitNoteEntryDialog(QDialog):
    """Modal dialog for creating / editing a debit note."""

    def __init__(self, parent: QWidget | None = None, *, dn: dict | None = None, supplier_id: int | None = None):
        super().__init__(parent)
        self._dn = dn
        self._saved = False
        self._item_rows: list[_ReturnItemRow] = []

        title_text = "Edit Debit Note" if dn else "New Debit Note"
        self.setWindowTitle(f"Debit Note - {title_text}")
        self.resize(1260, 680)
        self.setMinimumWidth(1160)
        self.setMinimumHeight(600)
        self.setModal(True)

        p = _get_palette()
        self.setStyleSheet(
            f"QDialog {{ background-color: {p['surface']}; color: {p['text']}; }}"
            f"QLineEdit, QDateEdit, QComboBox {{ background-color: {p['surface']}; color: {p['text']}; "
            f"border: 1px solid {p['border']}; border-radius: 2px; padding: 4px; font-size: 13px; font-family: 'Segoe UI'; }}"
            f"QLineEdit:focus, QDateEdit:focus, QComboBox:focus {{ border: 1px solid {p['accent']}; }}"
            + date_subcontrols(p, width=22)
            + combo_subcontrols(p, width=22)
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        # 1. Top banner strip (Pharma-WINNER style)
        self._build_top_banner(root, title_text)

        # 2. Header row (Type, Date, Supplier, Less)
        self._build_header_row(root)

        # 3. Item Entry Bar
        self._entry_bar = _ItemEntryBar(self)
        self._entry_bar.add_btn.clicked.connect(self._on_add_item)
        root.addWidget(self._entry_bar)

        # 4. Items table
        self._build_items_table(root)

        # 5. Bottom summary bar
        self._build_bottom_bar(root)

        # Load initial data with cascade suppression
        self._populating = True
        try:
            self._load_suppliers()
            self._entry_bar.load_items()

            if dn:
                self._populate_dn(dn)
            else:
                self._init_new_dn()
                if supplier_id:
                    self.supplier_combo.set_selected_id(supplier_id)
        finally:
            self._populating = False
        self._recalc_totals()

    def _build_top_banner(self, parent_layout: QVBoxLayout, title_text: str):
        p = _get_palette()
        banner = QFrame()
        banner.setFixedHeight(42)
        banner.setStyleSheet(
            f"background-color: {p['accent']}; border-radius: 3px; color: white;"
        )
        bl = QHBoxLayout(banner)
        bl.setContentsMargins(12, 0, 12, 0)
        bl.setSpacing(16)

        self.title_lbl = QLabel(title_text)
        self.title_lbl.setStyleSheet("font-size: 16px; font-weight: bold; color: white; background: transparent;")
        bl.addWidget(self.title_lbl)

        bl.addStretch()

        bl.addWidget(self._banner_lbl("Voucher No"))
        self.voucher_no_lbl = QLabel("")
        self.voucher_no_lbl.setStyleSheet("font-size: 15px; font-weight: bold; color: white; background: transparent;")
        bl.addWidget(self.voucher_no_lbl)

        bl.addWidget(self._banner_lbl("Date"))
        self.banner_date_lbl = QLabel("")
        self.banner_date_lbl.setStyleSheet("font-size: 14px; font-weight: bold; color: white; background: transparent;")
        bl.addWidget(self.banner_date_lbl)

        bl.addWidget(self._banner_lbl("Time"))
        self.banner_time_lbl = QLabel("")
        self.banner_time_lbl.setStyleSheet("font-size: 14px; font-weight: bold; color: white; background: transparent;")
        bl.addWidget(self.banner_time_lbl)

        parent_layout.addWidget(banner)

    def _banner_lbl(self, text: str) -> QLabel:
        lbl = QLabel(text + ":")
        lbl.setStyleSheet("color: #e0f2fe; font-size: 13px; font-weight: bold; background: transparent;")
        return lbl

    def _build_header_row(self, parent_layout: QVBoxLayout):
        p = _get_palette()
        frame = QFrame()
        frame.setStyleSheet(f"background-color: {p['surface']}; border: 1px solid {p['border']}; border-radius: 3px;")
        hl = QHBoxLayout(frame)
        hl.setContentsMargins(10, 8, 10, 8)
        hl.setSpacing(12)

        def _hdr_lbl(text: str):
            l = QLabel(text)
            l.setStyleSheet(f"color: {p['text']}; font-size: 13px; font-weight: bold; background: transparent;")
            return l

        hl.addWidget(_hdr_lbl("Type :"))
        self.type_combo = ConstrainedComboBox()
        self.type_combo.addItems(["Supplier"])
        self.type_combo.setFixedWidth(110)
        hl.addWidget(self.type_combo)

        hl.addWidget(_hdr_lbl("Date :"))
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("dd/MM/yyyy")
        self.date_edit.setFixedWidth(120)
        self.date_edit.dateChanged.connect(self._on_date_changed)
        hl.addWidget(self.date_edit)

        hl.addWidget(_hdr_lbl("Supplier :"))
        self.supplier_combo = SearchableComboBox(placeholder="-- Select Supplier --")
        self.supplier_combo.setMinimumWidth(320)
        self.supplier_combo.selection_changed.connect(self._on_supplier_changed)
        self.supplier_combo.returnPressed.connect(self._focus_entry_item)
        hl.addWidget(self.supplier_combo, 1)

        hl.addWidget(_hdr_lbl("Less :"))
        self.header_less_edit = QLineEdit("0%")
        self.header_less_edit.setFixedWidth(80)
        self.header_less_edit.setAlignment(Qt.AlignRight)
        self.header_less_edit.setToolTip("Discount percentage (e.g. 5%) or flat amount (e.g. 10.00)")
        self.header_less_edit.textChanged.connect(self._recalc_totals)
        self.header_less_edit.returnPressed.connect(self._focus_entry_item)
        hl.addWidget(self.header_less_edit)

        parent_layout.addWidget(frame)

    def _focus_entry_item(self):
        if hasattr(self, "_entry_bar"):
            if hasattr(self._entry_bar.item_combo, "lineEdit") and self._entry_bar.item_combo.lineEdit():
                self._entry_bar.item_combo.lineEdit().setFocus()
                self._entry_bar.item_combo.lineEdit().selectAll()
            else:
                self._entry_bar.item_combo.setFocus()

    def _build_items_table(self, parent_layout: QVBoxLayout):
        p = _get_palette()
        self._table = QTableWidget()
        self._table.setColumnCount(13)
        self._table.setHorizontalHeaderLabels([
            "ItemName", "PackSize", "BatchNo", "Expiry", "Rate", "MRP",
            "Qty", "FreeQty", "DiscAmt", "Amount", "Reason", "PriceFactor", "Del"
        ])
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(True)
        self._table.setAlternatingRowColors(False)

        hv = self._table.horizontalHeader()
        hv.setSectionResizeMode(0, QHeaderView.Stretch)
        for i in range(1, 13):
            hv.setSectionResizeMode(i, QHeaderView.ResizeToContents)

        hv.setStyleSheet(
            f"QHeaderView::section {{ background-color: {p['surface']}; color: {p['text']}; "
            f"border: 1px solid {p['border']}; border-bottom: 2px solid {p['accent']}; "
            f"padding: 4px; font-weight: bold; font-size: 13px; font-family: 'Segoe UI'; }}"
        )
        self._table.setStyleSheet(
            f"QTableWidget {{ background-color: {p['surface']}; color: {p['text']}; "
            f"border: 1px solid {p['border']}; gridline-color: {p['border']}; "
            f"selection-background-color: {p['accent']}; selection-color: white; font-size: 13px; }}"
            f"QTableWidget::item {{ padding: 3px 6px; }}"
        )
        parent_layout.addWidget(self._table, 1)

    def _build_bottom_bar(self, parent_layout: QVBoxLayout):
        p = _get_palette()
        bar = QFrame()
        bar.setStyleSheet(f"background-color: {p['surface']}; border-top: 1px solid {p['border']};")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(10, 8, 10, 4)
        bl.setSpacing(16)

        def _bot_lbl(text: str):
            l = QLabel(text)
            l.setStyleSheet(f"color: {p['text']}; font-size: 13px; font-weight: bold; background: transparent;")
            return l

        bl.addWidget(_bot_lbl("Total Items :"))
        self.total_items_val = QLineEdit("0")
        self.total_items_val.setReadOnly(True)
        self.total_items_val.setFixedWidth(70)
        self.total_items_val.setAlignment(Qt.AlignCenter)
        bl.addWidget(self.total_items_val)

        bl.addWidget(_bot_lbl("Total Amount :"))
        self.total_amount_val = QLineEdit("0.00")
        self.total_amount_val.setReadOnly(True)
        self.total_amount_val.setFixedWidth(110)
        self.total_amount_val.setAlignment(Qt.AlignRight)
        self.total_amount_val.setStyleSheet(f"font-weight: bold; color: {p['accent']}; font-size: 14px;")
        bl.addWidget(self.total_amount_val)

        self.add_to_ledger_cb = QCheckBox("Amount Add to Supplier Ledger")
        self.add_to_ledger_cb.setStyleSheet(f"color: {p['text']}; font-size: 13px; font-weight: bold;")
        bl.addWidget(self.add_to_ledger_cb)

        bl.addStretch()

        self.save_btn = QPushButton("Save")
        self.save_btn.setFixedWidth(100)
        self.save_btn.setFixedHeight(32)
        self.save_btn.setAutoDefault(False)
        self.save_btn.setDefault(False)
        self.save_btn.setStyleSheet(
            f"QPushButton {{ background-color: {p['accent']}; color: white; "
            f"font-weight: bold; font-size: 14px; border: none; border-radius: 3px; }}"
            f"QPushButton:hover {{ background-color: {p['accent_hover']}; }}"
        )
        self.save_btn.clicked.connect(self._on_save)
        bl.addWidget(self.save_btn)

        self.close_btn = QPushButton("Close")
        self.close_btn.setFixedWidth(100)
        self.close_btn.setFixedHeight(32)
        self.close_btn.setAutoDefault(False)
        self.close_btn.setDefault(False)
        self.close_btn.setStyleSheet(
            f"QPushButton {{ background-color: {p['border']}; color: {p['text']}; "
            f"font-size: 14px; border: none; border-radius: 3px; }}"
            f"QPushButton:hover {{ background-color: #94a3b8; }}"
        )
        self.close_btn.clicked.connect(self.reject)
        bl.addWidget(self.close_btn)

        parent_layout.addWidget(bar)

    def _load_suppliers(self):
        suppliers = SupplierDAO.get_all()
        self._supplier_cache = {s["id"]: s for s in suppliers}
        items = [(s["supplier_name"], s["id"]) for s in suppliers]
        self.supplier_combo.populate(items)

    def _on_supplier_changed(self, supplier_id: object):
        sid = int(supplier_id) if supplier_id else None
        self._entry_bar.set_supplier_id(sid)
        if getattr(self, "_populating", False):
            return
        if sid:
            sup = getattr(self, "_supplier_cache", {}).get(sid) or SupplierDAO.get_by_id(sid)
            disc = float(sup.get("discount") or 0.0) if sup else 0.0
            if disc > 0:
                self.header_less_edit.setText(f"{disc:g}%")
            else:
                self.header_less_edit.setText("0%")
        else:
            self.header_less_edit.setText("0%")

    def _on_date_changed(self, qdate: QDate):
        self.banner_date_lbl.setText(qdate.toString("dd-MM-yyyy"))

    def _init_new_dn(self):
        from core.doc_formatter import format_document_number
        now = datetime.now()
        qdate = QDate(now.year, now.month, now.day)
        self.date_edit.setDate(qdate)
        self.banner_date_lbl.setText(now.strftime("%d-%m-%Y"))
        self.banner_time_lbl.setText(now.strftime("%I:%M %p"))

        full_vno = DebitNoteDAO.generate_next_voucher_no()
        self._full_voucher_no = full_vno
        self.voucher_no_lbl.setText(format_document_number(full_vno))
        self.voucher_no_lbl.setToolTip(f"Full Voucher: {full_vno}")

        # Ledger posting unchecked by default matching Screenshot 1
        self.add_to_ledger_cb.setChecked(False)

        sid = self.supplier_combo.currentData()
        if sid:
            sup = getattr(self, "_supplier_cache", {}).get(int(sid)) or SupplierDAO.get_by_id(int(sid))
            disc = float(sup.get("discount") or 0.0) if sup else 0.0
            if disc > 0:
                self.header_less_edit.setText(f"{disc:g}%")
            else:
                self.header_less_edit.setText("0%")
        else:
            self.header_less_edit.setText("0%")

    def _populate_dn(self, dn: dict):
        self._populating = True
        try:
            from core.doc_formatter import format_document_number
            full_vno = dn.get("voucher_no", "")
            self._full_voucher_no = full_vno
            self.voucher_no_lbl.setText(format_document_number(full_vno))
            self.voucher_no_lbl.setToolTip(f"Full Voucher: {full_vno}")

            vd = dn.get("voucher_date", "")
            if vd:
                parts = vd.split("-")
                self.date_edit.setDate(QDate(int(parts[0]), int(parts[1]), int(parts[2])))
            self.banner_time_lbl.setText(dn.get("voucher_time", ""))

            sid = dn.get("supplier_id")
            if sid:
                idx = self.supplier_combo.findData(sid)
                if idx >= 0:
                    self.supplier_combo.setCurrentIndex(idx)

            # Checkbox state
            is_posted = dn.get("added_to_ledger") == "Y"
            self.add_to_ledger_cb.setChecked(is_posted)

            # Header Less / Discount restoration
            disc_pct = float(dn.get("discount_pct") or 0.0)
            less_amt = float(dn.get("less_amount") or 0.0)
            if disc_pct > 0:
                self.header_less_edit.setText(f"{disc_pct:g}%")
            elif less_amt > 0:
                self.header_less_edit.setText(f"{less_amt:.2f}")
            else:
                self.header_less_edit.setText("0%")

            # Load items
            items = DebitNoteDAO.get_items(dn["id"])
            self._item_rows.clear()
            for it in items:
                self._item_rows.append(
                    _ReturnItemRow(
                        item_id=it["item_id"],
                        item_name=it.get("item_name", ""),
                        stock_batch_id=it["stock_batch_id"],
                        batch_no=it.get("batch_no", ""),
                        expiry=it.get("expiry", ""),
                        pack_size=str(it.get("pack_size") or "1"),
                        rate=float(it.get("rate", 0.0)),
                        mrp=float(it.get("mrp", 0.0)),
                        return_qty=float(it.get("return_qty", 0.0)),
                        free_qty=float(it.get("free_qty", 0.0)),
                        less_amount=float(it.get("less_amount", 0.0)),
                        amount=float(it.get("amount", 0.0)),
                        return_reason=it.get("return_reason", "Purchase Return"),
                        price_factor="RATE" if it.get("price_factor", 1.0) == 1.0 else "MRP",
                        price_factor_num=float(it.get("price_factor", 1.0)),
                    )
                )
            self._refresh_table()
            self._recalc_totals()
        finally:
            self._populating = False

    def _on_add_item(self):
        data = self._entry_bar.get_current_data()
        if not data:
            QMessageBox.warning(self, "Validation", "Please select an item and batch.")
            return

        sid = self.supplier_combo.currentData()
        if not sid:
            QMessageBox.warning(self, "Validation", "Please select a supplier first.")
            return

        ret_qty = data["return_qty"]
        free_qty = data["free_qty"]
        if ret_qty <= 0:
            QMessageBox.warning(self, "Validation", "Return quantity must be greater than 0.")
            return

        p_factor = pack_factor(data["pack_size"])
        loose_deduction = (ret_qty + free_qty) * p_factor
        available_stock = data["available_stock"]

        # Also account for any same-batch items already added to the table
        already_added_loose = sum(
            (r.return_qty + r.free_qty) * pack_factor(r.pack_size)
            for r in self._item_rows
            if r.stock_batch_id == data["stock_batch_id"]
        )

        unit = self._entry_bar._detect_unit_name(data["item_name"])

        if (loose_deduction + already_added_loose) > available_stock:
            max_packs = max(0.0, (available_stock - already_added_loose) / p_factor)
            QMessageBox.warning(
                self,
                "Insufficient Stock",
                f"Batch {data['batch_no']} has {available_stock:g} loose {unit.lower()} in stock.\n"
                f"Cannot return {loose_deduction + already_added_loose:g} loose {unit.lower()} "
                f"(max available: {max_packs:g} packs).",
            )
            return

        base_price = data["rate"] if data["price_factor"] == "RATE" else data["mrp"]
        gross = ret_qty * base_price
        less_pct = data["less_pct"]
        disc_amt = round(gross * (less_pct / 100.0), 2)
        amount = round(gross - disc_amt, 2)

        row = _ReturnItemRow(
            item_id=data["item_id"],
            item_name=data["item_name"],
            stock_batch_id=data["stock_batch_id"],
            batch_no=data["batch_no"],
            expiry=data["expiry"],
            pack_size=data["pack_size"],
            rate=data["rate"],
            mrp=data["mrp"],
            return_qty=ret_qty,
            free_qty=free_qty,
            less_amount=disc_amt,
            amount=amount,
            return_reason=data["return_reason"],
            price_factor=data["price_factor"],
            price_factor_num=1.0,
        )
        self._item_rows.append(row)
        self._refresh_table()
        self._recalc_totals()
        self._entry_bar.clear()
        if self._entry_bar.item_combo.lineEdit():
            self._entry_bar.item_combo.lineEdit().setFocus()
        else:
            self._entry_bar.item_combo.setFocus()

    def _refresh_table(self):
        p = _get_palette()
        self._table.setUpdatesEnabled(False)
        self._table.blockSignals(True)
        try:
            self._table.setRowCount(len(self._item_rows))
            btn_style = (
                "QPushButton { background-color: #ef4444; color: white; border: none; "
                "border-radius: 2px; font-weight: bold; font-size: 11px; padding: 2px; }"
                "QPushButton:hover { background-color: #dc2626; }"
            )
            for i, r in enumerate(self._item_rows):
                self._table.setItem(i, 0, QTableWidgetItem(r.item_name))
                self._table.setItem(i, 1, QTableWidgetItem(r.pack_size))
                self._table.setItem(i, 2, QTableWidgetItem(r.batch_no))
                self._table.setItem(i, 3, QTableWidgetItem(r.expiry))

                rate_item = QTableWidgetItem(f"{r.rate:.2f}")
                rate_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self._table.setItem(i, 4, rate_item)

                mrp_item = QTableWidgetItem(f"{r.mrp:.2f}")
                mrp_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self._table.setItem(i, 5, mrp_item)

                qty_item = QTableWidgetItem(f"{r.return_qty:g}")
                qty_item.setTextAlignment(Qt.AlignCenter)
                self._table.setItem(i, 6, qty_item)

                free_item = QTableWidgetItem(f"{r.free_qty:g}")
                free_item.setTextAlignment(Qt.AlignCenter)
                self._table.setItem(i, 7, free_item)

                disc_item = QTableWidgetItem(f"{r.less_amount:.2f}")
                disc_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self._table.setItem(i, 8, disc_item)

                amt_item = QTableWidgetItem(f"{r.amount:.2f}")
                amt_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self._table.setItem(i, 9, amt_item)

                self._table.setItem(i, 10, QTableWidgetItem(r.return_reason))
                self._table.setItem(i, 11, QTableWidgetItem(r.price_factor))

                del_btn = QPushButton("Del")
                del_btn.setStyleSheet(btn_style)
                del_btn.setFixedWidth(36)
                del_btn.clicked.connect(lambda _, idx=i: self._delete_row(idx))
                self._table.setCellWidget(i, 12, del_btn)
        finally:
            self._table.blockSignals(False)
            self._table.setUpdatesEnabled(True)

    def _delete_row(self, idx: int):
        if 0 <= idx < len(self._item_rows):
            self._item_rows.pop(idx)
            self._refresh_table()
            self._recalc_totals()

    def _recalc_totals(self):
        total_items = len(self._item_rows)
        subtotal = sum(r.amount for r in self._item_rows)
        less_amt, _ = _parse_header_less(self.header_less_edit.text(), subtotal)
        total_amount = max(0.0, round(subtotal - less_amt, 2))

        self.total_items_val.setText(str(total_items))
        self.total_amount_val.setText(f"{total_amount:.2f}")

    def _on_save(self):
        try:
            financial_year.validate_transaction_date(self.date_edit.date().toString("yyyy-MM-dd"))
        except financial_year.FinancialYearError as exc:
            QMessageBox.warning(self, "Financial Year", str(exc))
            return

        sid = self.supplier_combo.currentData()
        if not sid:
            QMessageBox.warning(self, "Validation", "Supplier is required.")
            return

        if not self._item_rows:
            QMessageBox.warning(self, "Validation", "At least one item is required.")
            return

        self._recalc_totals()
        subtotal = sum(r.amount for r in self._item_rows)
        less_amt, disc_pct = _parse_header_less(self.header_less_edit.text(), subtotal)
        total_amount = max(0.0, round(subtotal - less_amt, 2))
        add_to_ledger = self.add_to_ledger_cb.isChecked()

        voucher_date = self.date_edit.date().toString("yyyy-MM-dd")
        voucher_time = self.banner_time_lbl.text() or datetime.now().strftime("%I:%M %p")
        dn_date = voucher_date

        header = {
            "voucher_no": getattr(self, "_full_voucher_no", ""),
            "voucher_date": voucher_date,
            "voucher_time": voucher_time,
            "dn_date": dn_date,
            "dn_type": self.type_combo.currentText() or "Supplier",
            "supplier_id": int(sid),
            "total_amount": total_amount,
            "ledger_amount": total_amount if add_to_ledger else 0.0,
            "add_to_ledger": add_to_ledger,
            "discount_pct": disc_pct,
            "less_amount": less_amt,
            "remarks": "",
        }
        items_data = [r.to_dict() for r in self._item_rows]

        try:
            if self._dn:
                DebitNoteDAO.update_debit_note(self._dn["id"], header, items_data)
            else:
                DebitNoteDAO.insert_debit_note(header, items_data)
            self._saved = True
            QMessageBox.information(self, "Success", "Debit Note saved successfully.")
            self.accept()
        except ValueError as e:
            QMessageBox.warning(self, "Validation", str(e))
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save debit note:\n{e}")

    @property
    def was_saved(self) -> bool:
        return self._saved


# ======================================================================
# Debit Note PAGE (List Screen)
# ======================================================================

class DebitNotePage(QWidget):
    """Debit Note screen with history list matching Pharma-WINNER reference."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        p = _get_palette()
        self.setStyleSheet(f"background-color: {p['bg']};")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._stack = QStackedWidget()
        root.addWidget(self._stack)

        self._history_page = self._build_history_page()
        self._stack.addWidget(self._history_page)

        self._refresh_history()

    def _build_history_page(self) -> QWidget:
        p = _get_palette()
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 1. Top cyan banner: Debit Note List
        banner = QFrame()
        banner.setFixedHeight(46)
        banner.setStyleSheet(
            f"background-color: {p['accent']}; color: white; border-bottom: 2px solid {p['accent_hover']};"
        )
        bl = QHBoxLayout(banner)
        bl.setContentsMargins(16, 0, 16, 0)

        # Actions at top left: New, Edit, Print, Delete
        new_btn = QPushButton("New")
        new_btn.setToolTip("Create New Debit Note (Return to Supplier)")
        new_btn.setFixedWidth(75)
        new_btn.setFixedHeight(30)
        new_btn.setStyleSheet(
            "QPushButton { background-color: #0284c7; color: white; font-weight: bold; "
            "border: none; border-radius: 3px; font-size: 13px; }"
            "QPushButton:hover { background-color: #0369a1; }"
        )
        new_btn.clicked.connect(self._on_new)
        bl.addWidget(new_btn)

        edit_btn = QPushButton("Edit")
        edit_btn.setToolTip("Edit Selected Debit Note")
        edit_btn.setFixedWidth(75)
        edit_btn.setFixedHeight(30)
        edit_btn.setStyleSheet(
            "QPushButton { background-color: #0284c7; color: white; font-weight: bold; "
            "border: none; border-radius: 3px; font-size: 13px; }"
            "QPushButton:hover { background-color: #0369a1; }"
        )
        edit_btn.clicked.connect(self._on_edit)
        bl.addWidget(edit_btn)

        print_btn = QPushButton("Print")
        print_btn.setToolTip("Print / Export Debit Note PDF")
        print_btn.setFixedWidth(75)
        print_btn.setFixedHeight(30)
        print_btn.setStyleSheet(
            "QPushButton { background-color: #0284c7; color: white; font-weight: bold; "
            "border: none; border-radius: 3px; font-size: 13px; }"
            "QPushButton:hover { background-color: #0369a1; }"
        )
        print_btn.clicked.connect(self._on_print)
        bl.addWidget(print_btn)

        del_btn = QPushButton("Delete")
        del_btn.setToolTip("Delete Selected Debit Note and Reverse Stock/Ledger")
        del_btn.setFixedWidth(75)
        del_btn.setFixedHeight(30)
        del_btn.setStyleSheet(
            "QPushButton { background-color: #dc2626; color: white; font-weight: bold; "
            "border: none; border-radius: 3px; font-size: 13px; }"
            "QPushButton:hover { background-color: #b91c1c; }"
        )
        del_btn.clicked.connect(self._on_delete)
        bl.addWidget(del_btn)

        bl.addStretch()

        title_lbl = QLabel("Debit Note List")
        title_lbl.setStyleSheet("font-size: 18px; font-weight: bold; color: white; background: transparent;")
        bl.addWidget(title_lbl)

        bl.addStretch()
        layout.addWidget(banner)

        # 2. Filter row: Date range + Supplier search
        filter_bar = QFrame()
        filter_bar.setFixedHeight(46)
        filter_bar.setStyleSheet(f"background-color: {p['surface']}; border-bottom: 1px solid {p['border']};")
        fl = QHBoxLayout(filter_bar)
        fl.setContentsMargins(12, 0, 12, 0)
        fl.setSpacing(10)

        def _flbl(text: str):
            l = QLabel(text)
            l.setStyleSheet(f"color: {p['text']}; font-size: 13px; font-weight: bold; background: transparent;")
            return l

        self._filter_from = QDateEdit()
        self._filter_from.setCalendarPopup(True)
        self._filter_from.setDisplayFormat("dd/MM/yyyy")
        self._filter_from.setFixedWidth(115)

        self._filter_to = QDateEdit()
        self._filter_to.setCalendarPopup(True)
        self._filter_to.setDisplayFormat("dd/MM/yyyy")
        self._filter_to.setFixedWidth(115)

        # Initialize filter dates from active financial year or current date
        fy = financial_year.get_active_financial_year()
        if fy:
            s_parts = fy["start_date"].split("-")
            e_parts = fy["end_date"].split("-")
            self._filter_from.setDate(QDate(int(s_parts[0]), int(s_parts[1]), int(s_parts[2])))
            self._filter_to.setDate(QDate(int(e_parts[0]), int(e_parts[1]), int(e_parts[2])))
        else:
            now = datetime.now()
            self._filter_from.setDate(QDate(now.year, 1, 1))
            self._filter_to.setDate(QDate(now.year, 12, 31))

        fl.addWidget(self._filter_from)
        fl.addWidget(_flbl("VhDate"))
        fl.addWidget(self._filter_to)

        go_btn = QPushButton("Go")
        go_btn.setFixedWidth(50)
        go_btn.setFixedHeight(28)
        go_btn.setStyleSheet(
            f"QPushButton {{ background-color: {p['accent']}; color: white; "
            f"font-weight: bold; font-size: 13px; border: none; border-radius: 2px; }}"
            f"QPushButton:hover {{ background-color: {p['accent_hover']}; }}"
        )
        go_btn.clicked.connect(self._refresh_history)
        fl.addWidget(go_btn)

        fl.addStretch()

        fl.addWidget(_flbl("Supplier"))
        self._filter_supplier = SearchableComboBox(placeholder="[Search Supplier]")
        self._filter_supplier.setFixedWidth(240)
        sup_items = [("All Suppliers", None)] + [(s["supplier_name"], s["id"]) for s in SupplierDAO.get_all()]
        self._filter_supplier.populate(sup_items)
        self._filter_supplier.setCurrentIndex(0)
        fl.addWidget(self._filter_supplier)

        filter_btn = QPushButton("Filter")
        filter_btn.setFixedWidth(65)
        filter_btn.setFixedHeight(28)
        filter_btn.setStyleSheet(
            f"QPushButton {{ background-color: {p['accent']}; color: white; "
            f"font-weight: bold; font-size: 13px; border: none; border-radius: 2px; }}"
            f"QPushButton:hover {{ background-color: {p['accent_hover']}; }}"
        )
        filter_btn.clicked.connect(self._refresh_history)
        fl.addWidget(filter_btn)

        layout.addWidget(filter_bar)

        # 3. History table: VhType | VhNo | VhDate | VhTime | DNDate | DNType | Name | Amount
        self._hist_table = QTableWidget()
        self._hist_table.setColumnCount(8)
        self._hist_table.setHorizontalHeaderLabels([
            "VhType", "VhNo", "VhDate", "VhTime", "DNDate", "DNType", "Name", "Amount"
        ])
        self._hist_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._hist_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._hist_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._hist_table.verticalHeader().setVisible(False)
        self._hist_table.setShowGrid(True)
        self._hist_table.setAlternatingRowColors(False)
        self._hist_table.setSortingEnabled(True)
        self._hist_table.cellDoubleClicked.connect(lambda row, col: self._on_edit())

        hv = self._hist_table.horizontalHeader()
        hv.setSectionResizeMode(6, QHeaderView.Stretch)  # Name column stretches
        for c in [0, 1, 2, 3, 4, 5, 7]:
            hv.setSectionResizeMode(c, QHeaderView.ResizeToContents)

        hv.setStyleSheet(
            f"QHeaderView::section {{ background-color: {p['surface']}; color: {p['text']}; "
            f"border: 1px solid {p['border']}; border-bottom: 2px solid {p['accent']}; "
            f"padding: 5px; font-weight: bold; font-size: 13px; font-family: 'Segoe UI'; }}"
        )
        self._hist_table.setStyleSheet(
            f"QTableWidget {{ background-color: {p['surface']}; color: {p['text']}; "
            f"border: 1px solid {p['border']}; gridline-color: {p['border']}; "
            f"selection-background-color: {p['accent']}; selection-color: white; font-size: 13px; }}"
            f"QTableWidget::item {{ padding: 3px 6px; }}"
        )
        layout.addWidget(self._hist_table, 1)

        return page

    def _refresh_history(self):
        from_date = self._filter_from.date().toString("yyyy-MM-dd")
        to_date = self._filter_to.date().toString("yyyy-MM-dd")
        sup_id = self._filter_supplier.currentData()
        sid = int(sup_id) if sup_id else None

        dns = DebitNoteDAO.get_all_filtered(
            voucher_from=from_date,
            voucher_to=to_date,
            supplier_id=sid,
        )

        self._hist_table.setUpdatesEnabled(False)
        self._hist_table.setSortingEnabled(False)
        try:
            self._hist_table.setRowCount(len(dns))

            for i, dn in enumerate(dns):
                raw_vno = dn.get("voucher_no", "")
                disp_no = format_document_number(raw_vno)

                item_type = QTableWidgetItem("Debit Note")
                item_type.setData(Qt.UserRole, dn["id"])
                self._hist_table.setItem(i, 0, item_type)

                no_item = QTableWidgetItem(disp_no)
                no_item.setToolTip(f"Full Voucher: {raw_vno}")
                self._hist_table.setItem(i, 1, no_item)

                # Dates in dd/MM/yyyy
                vd = dn.get("voucher_date", "")
                if vd and "-" in vd:
                    p_date = vd.split("-")
                    vd_disp = f"{p_date[2]}/{p_date[1]}/{p_date[0]}"
                else:
                    vd_disp = vd
                self._hist_table.setItem(i, 2, QTableWidgetItem(vd_disp))

                self._hist_table.setItem(i, 3, QTableWidgetItem(dn.get("voucher_time", "")))

                dd = dn.get("dn_date", "")
                if dd and "-" in dd:
                    p_date = dd.split("-")
                    dd_disp = f"{p_date[2]}/{p_date[1]}/{p_date[0]}"
                else:
                    dd_disp = dd
                self._hist_table.setItem(i, 4, QTableWidgetItem(dd_disp))

                self._hist_table.setItem(i, 5, QTableWidgetItem(dn.get("dn_type", "Supplier")))
                self._hist_table.setItem(i, 6, QTableWidgetItem(dn.get("supplier_name", "")))

                tot_val = float(dn.get('total_amount', 0.0) or 0.0)
                amt_item = QTableWidgetItem(f"{tot_val:.2f}")
                amt_item.setData(Qt.EditRole, tot_val)
                amt_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self._hist_table.setItem(i, 7, amt_item)
        finally:
            self._hist_table.setSortingEnabled(True)
            self._hist_table.setUpdatesEnabled(True)

    def _selected_id(self) -> int | None:
        rows = self._hist_table.selectionModel().selectedRows()
        if not rows:
            return None
        row = rows[0].row()
        item = self._hist_table.item(row, 0)
        return item.data(Qt.UserRole) if item else None

    def _on_new(self):
        dlg = _DebitNoteEntryDialog(self)
        if dlg.exec() == QDialog.Accepted and dlg.was_saved:
            self._refresh_history()

    def _on_edit(self):
        dn_id = self._selected_id()
        if not dn_id:
            QMessageBox.information(self, "Edit Debit Note", "Please select a debit note from the list.")
            return

        dn = DebitNoteDAO.get_by_id(dn_id)
        if not dn:
            QMessageBox.warning(self, "Error", f"Debit note #{dn_id} not found.")
            return

        dlg = _DebitNoteEntryDialog(self, dn=dn)
        if dlg.exec() == QDialog.Accepted and dlg.was_saved:
            self._refresh_history()

    def _on_delete(self):
        dn_id = self._selected_id()
        if not dn_id:
            QMessageBox.information(self, "Delete Debit Note", "Please select a debit note to delete.")
            return

        dn = DebitNoteDAO.get_by_id(dn_id)
        if not dn:
            return

        msg = (
            f"Are you sure you want to delete Debit Note {dn['voucher_no']}?\n\n"
            f"Supplier: {dn.get('supplier_name', '')}\n"
            f"Amount: {dn.get('total_amount', 0.0):.2f}\n\n"
            "This will reverse stock deductions and any ledger accounting entries."
        )
        res = QMessageBox.question(
            self,
            "Confirm Delete",
            msg,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if res == QMessageBox.Yes:
            try:
                DebitNoteDAO.delete_debit_note(dn_id)
                QMessageBox.information(self, "Deleted", f"Debit Note {dn['voucher_no']} deleted successfully.")
                self._refresh_history()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to delete debit note:\n{e}")

    def _on_print(self):
        dn_id = self._selected_id()
        if not dn_id:
            QMessageBox.information(self, "Print Debit Note", "Please select a debit note from the list.")
            return

        dn = DebitNoteDAO.get_by_id(dn_id)
        if not dn:
            return

        default_name = f"{dn['voucher_no']}.pdf".replace("/", "-")
        pdf_path, _ = QFileDialog.getSaveFileName(
            self, "Save Debit Note PDF", default_name, "PDF Files (*.pdf)"
        )
        if not pdf_path:
            return

        try:
            generate_debit_note(dn_id, pdf_path)
            QMessageBox.information(self, "Success", f"Debit Note PDF generated at:\n{pdf_path}")
        except DocumentPrintError as e:
            QMessageBox.warning(self, "Print Error", str(e))
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to generate PDF:\n{e}")


# ======================================================================
# Pending Debit Notes Selection Dialog (Pharma-WINNER Screenshot 3)
# ======================================================================

class PendingDebitNotesDialog(QDialog):
    """Dialog allowing selection and partial/full adjustment of pending debit notes."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        supplier_id: int | None = None,
        supplier_name: str | None = None,
        max_adjustment_needed: float = 0.0,
        already_applied_settlements: list[dict] | None = None,
    ):
        super().__init__(parent)
        self._supplier_id = supplier_id
        self._supplier_name = (supplier_name or "").strip()
        self._max_needed = max_adjustment_needed
        self._already_applied = {s.get("debit_note_id", s.get("id")): s for s in (already_applied_settlements or [])}
        self._settlements_result: list[dict] = []
        self._row_edits: list[dict] = []

        self.setWindowTitle(f"Pending Debit Note(s) For {self._supplier_name}")
        self.resize(880, 400)
        self.setMinimumWidth(800)
        self.setMinimumHeight(300)
        self.setModal(True)

        p = _get_palette()
        # Light yellow table background matching Pharma-WINNER Screenshot 3
        table_bg = "#ffffea" if not p.get("is_dark", False) else p["surface"]
        self.setStyleSheet(
            f"QDialog {{ background-color: {p['surface']}; color: {p['text']}; }}"
            f"QTableWidget {{ background-color: {table_bg}; color: {p['text']}; "
            f"gridline-color: {p['border']}; border: 1px solid {p['border']}; }}"
            f"QHeaderView::section {{ background-color: {p['accent']}; color: white; font-weight: bold; padding: 4px; border: none; }}"
            f"QLineEdit {{ background-color: {p['surface']}; color: {p['text']}; border: 1px solid {p['border']}; padding: 3px; font-weight: bold; }}"
            f"QLineEdit:focus {{ border: 1px solid {p['accent']}; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "VhType", "VhNo", "VhDate", "VhAmount", "UnSettled", "DebitAmt", "DiscAmt"
        ])
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setMinimumSectionSize(80)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table, 1)

        # Bottom buttons row
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(10)

        self.new_dn_btn = QPushButton("New Debit Note")
        self.new_dn_btn.setStyleSheet(
            f"QPushButton {{ background-color: {p['accent']}; color: white; font-weight: bold; padding: 6px 14px; border-radius: 3px; }}"
            f"QPushButton:hover {{ background-color: {p['accent_hover']}; }}"
        )
        self.new_dn_btn.clicked.connect(self._on_new_debit_note)
        btn_row.addWidget(self.new_dn_btn)

        btn_row.addStretch()

        self.done_btn = QPushButton("Done")
        self.done_btn.setStyleSheet(
            f"QPushButton {{ background-color: {p['accent']}; color: white; font-weight: bold; padding: 6px 20px; border-radius: 3px; }}"
            f"QPushButton:hover {{ background-color: {p['accent_hover']}; }}"
        )
        self.done_btn.clicked.connect(self._on_done)
        btn_row.addWidget(self.done_btn)

        self.close_btn = QPushButton("Close")
        self.close_btn.setStyleSheet(
            f"QPushButton {{ background-color: transparent; color: {p['text']}; border: 1px solid {p['border']}; padding: 6px 20px; border-radius: 3px; }}"
            f"QPushButton:hover {{ background-color: {p['border']}; }}"
        )
        self.close_btn.clicked.connect(self.reject)
        btn_row.addWidget(self.close_btn)

        layout.addLayout(btn_row)

        self._load_pending_notes()

    def _load_pending_notes(self):
        notes = DebitNoteDAO.get_unsettled_by_supplier(
            self._supplier_id, self._supplier_name
        )
        self.table.setUpdatesEnabled(False)
        self.table.setSortingEnabled(False)
        try:
            self.table.setRowCount(len(notes))
            self._row_edits = []

            remaining_needed = self._max_needed

            for row, n in enumerate(notes):
                dn_id = n["id"]
                vh_no = str(n.get("voucher_no", ""))
                vh_date = str(n.get("voucher_date", ""))
                vh_amt = float(n.get("total_amount", 0.0))
                unsettled = float(n.get("unsettled_amount", 0.0))

                # Prior adjustment if already opened
                prior_debit = 0.0
                prior_disc = 0.0
                if dn_id in self._already_applied:
                    prior_debit = float(self._already_applied[dn_id].get("debit_amount", self._already_applied[dn_id].get("settled_amount", 0.0)))
                    prior_disc = float(self._already_applied[dn_id].get("discount_amount", 0.0))

                # If opening fresh and needed > 0, auto-fill up to remaining needed
                if prior_debit <= 0 and remaining_needed > 0 and unsettled > 0:
                    suggested = min(unsettled, remaining_needed)
                    prior_debit = suggested
                    remaining_needed -= suggested

                raw_date = str(n.get("voucher_date", "")).strip()
                if raw_date and len(raw_date) >= 10 and raw_date[4] == "-" and raw_date[7] == "-":
                    disp_date = f"{raw_date[8:10]}-{raw_date[5:7]}-{raw_date[:4]}"
                else:
                    disp_date = raw_date

                item_type = QTableWidgetItem("Debit Note")
                item_type.setFlags(item_type.flags() & ~Qt.ItemIsEditable)

                item_no = QTableWidgetItem(vh_no)
                item_no.setFlags(item_no.flags() & ~Qt.ItemIsEditable)

                item_date = QTableWidgetItem(disp_date)
                item_date.setTextAlignment(Qt.AlignCenter)
                item_date.setFlags(item_date.flags() & ~Qt.ItemIsEditable)

                item_amt = QTableWidgetItem(f"{vh_amt:.2f}")
                item_amt.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                item_amt.setFlags(item_amt.flags() & ~Qt.ItemIsEditable)

                item_unsettled = QTableWidgetItem(f"{unsettled:.2f}")
                item_unsettled.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                item_unsettled.setFlags(item_unsettled.flags() & ~Qt.ItemIsEditable)

                debit_edit = QLineEdit(f"{prior_debit:.2f}" if prior_debit > 0 else "0.0")
                debit_edit.setAlignment(Qt.AlignRight)
                debit_edit.setMinimumWidth(85)

                disc_edit = QLineEdit(f"{prior_disc:.2f}" if prior_disc > 0 else "0.0")
                disc_edit.setAlignment(Qt.AlignRight)
                disc_edit.setMinimumWidth(85)

                self.table.setItem(row, 0, item_type)
                self.table.setItem(row, 1, item_no)
                self.table.setItem(row, 2, item_date)
                self.table.setItem(row, 3, item_amt)
                self.table.setItem(row, 4, item_unsettled)
                self.table.setCellWidget(row, 5, debit_edit)
                self.table.setCellWidget(row, 6, disc_edit)

                self._row_edits.append({
                    "debit_note_id": dn_id,
                    "voucher_no": vh_no,
                    "voucher_date": vh_date,
                    "total_amount": vh_amt,
                    "unsettled": unsettled,
                    "debit_edit": debit_edit,
                    "disc_edit": disc_edit,
                })

            self.table.setColumnWidth(0, 115)
            self.table.setColumnWidth(1, 165)
            self.table.setColumnWidth(2, 110)
            self.table.setColumnWidth(3, 110)
            self.table.setColumnWidth(4, 110)
        finally:
            self.table.setUpdatesEnabled(True)
        self.table.setColumnWidth(5, 120)
        self.table.setColumnWidth(6, 115)

    def _on_new_debit_note(self):
        dlg = _DebitNoteEntryDialog(self, supplier_id=self._supplier_id)
        if (dlg.exec() if hasattr(dlg, "exec") else dlg.exec_()) == QDialog.Accepted or dlg._saved:
            self._load_pending_notes()

    def _on_done(self):
        settlements = []
        for r in self._row_edits:
            try:
                debit_amt = round(float(r["debit_edit"].text() or 0.0), 2)
            except ValueError:
                debit_amt = 0.0
            try:
                disc_amt = round(float(r["disc_edit"].text() or 0.0), 2)
            except ValueError:
                disc_amt = 0.0

            if debit_amt > r["unsettled"] + 0.001:
                QMessageBox.warning(
                    self,
                    "Invalid Amount",
                    f"Debit amount ({debit_amt:.2f}) for Voucher #{r['voucher_no']} "
                    f"cannot exceed unsettled amount ({r['unsettled']:.2f})."
                )
                return

            if debit_amt < 0 or disc_amt < 0:
                QMessageBox.warning(self, "Invalid Amount", "Debit and Discount amounts cannot be negative.")
                return

            if debit_amt > 0:
                settlements.append({
                    "debit_note_id": r["debit_note_id"],
                    "voucher_no": r["voucher_no"],
                    "debit_amount": debit_amt,
                    "discount_amount": disc_amt,
                })

        self._settlements_result = settlements
        self.accept()

    def get_settlements(self) -> list[dict]:
        return list(self._settlements_result)

    def get_total_debit_applied(self) -> float:
        return round(sum(float(s["debit_amount"]) for s in self._settlements_result), 2)
