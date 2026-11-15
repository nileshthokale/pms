"""Test batch selection workflow, 5-row popup sizing, status column removal,
and keyboard navigation (Type Item -> Tab -> Up/Down -> Tab -> Qty).
"""
import os
import sys
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, ".")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QKeyEvent

from ui.components import TableComboBox, DEFAULT_BATCH_COLUMNS
from screens.counter_sale import CounterSalePage, _ItemEntryBar

app = QApplication.instance() or QApplication([])


class TestBatchSelectionWorkflow(unittest.TestCase):
    def test_01_status_column_removed(self):
        """Verify 'Status' column is removed from default batch columns."""
        keys = [c["key"] for c in DEFAULT_BATCH_COLUMNS]
        headers = [c["header"] for c in DEFAULT_BATCH_COLUMNS]
        self.assertNotIn("status", keys)
        self.assertNotIn("Status", headers)
        self.assertEqual(headers, ["Batch No", "Expiry Date", "MRP", "Rate", "Balance"])

    def test_02_five_batches_show_without_scrollbar_six_plus_scrolls(self):
        """Verify popup displays 5 batches without scrollbar, and scrolls for 6+ batches."""
        combo = TableComboBox()
        batches_5 = [
            {"batch_no": f"BATCH_{i}", "expiry": "2028-12-31", "mrp": 100.0 + i, "rate": 80.0, "stock_qty": 10 + i}
            for i in range(5)
        ]
        for b in batches_5:
            combo.addItem(b["batch_no"], b["batch_no"], row_data=b)

        combo.showPopup()
        app.processEvents()

        table = combo.table_view
        v_bar = table.verticalScrollBar()
        # For 5 batches, vertical scrollbar should not need to scroll
        self.assertEqual(v_bar.maximum(), 0, "5 batches should show completely without scrollbar")

        # Now add 3 more batches (total 8 batches)
        combo.hidePopup()
        for i in range(5, 8):
            b = {"batch_no": f"BATCH_{i}", "expiry": "2028-12-31", "mrp": 100.0 + i, "rate": 80.0, "stock_qty": 10 + i}
            combo.addItem(b["batch_no"], b["batch_no"], row_data=b)

        combo.showPopup()
        app.processEvents()

        # For 8 batches, vertical scrollbar must be active
        self.assertGreater(v_bar.maximum(), 0, "8 batches should have scrollbar active to scroll beyond 5")
        combo.hidePopup()

    def test_03_item_tab_opens_batch_and_arrow_keys_navigate(self):
        """Verify typing item + Tab opens batch popup, arrow keys select batch, Tab commits."""
        bar = _ItemEntryBar()
        bar.show()
        bar.activateWindow()
        app.processEvents()

        items = [("BIO D3 PLUS (TABLET)", 101), ("PARACETAMOL 500", 102)]
        bar.item_combo.clear()
        for name, iid in items:
            bar.item_combo.addItem(name, iid)

        batches = [
            {"id": 1, "batch_no": "KBC2402A", "expiry": "2026-12-31", "mrp": 301.0, "purchase_rate": 215.0, "stock_qty": 10, "is_expired": False},
            {"id": 2, "batch_no": "14253406A", "expiry": "2028-07-31", "mrp": 341.34, "purchase_rate": 260.07, "stock_qty": 5, "is_expired": False},
            {"id": 3, "batch_no": "14261266A", "expiry": "2029-02-28", "mrp": 341.34, "purchase_rate": 260.07, "stock_qty": 40, "is_expired": False},
        ]
        bar.batch_combo.clear()
        for b in batches:
            bar.batch_combo.addItem(b["batch_no"], b["id"], raw_name=b["batch_no"], row_data=b)

        # 1. Type item name
        bar.item_combo.lineEdit().setFocus()
        bar.item_combo.setEditText("BIO D3 PLUS")
        app.processEvents()

        # 2. Press Tab on item_combo
        tab_ev = QKeyEvent(QEvent.KeyPress, Qt.Key_Tab, Qt.NoModifier)
        bar.item_combo.eventFilter(bar.item_combo.lineEdit(), tab_ev)
        app.processEvents()

        # Batch combo popup should now be open
        self.assertTrue(bar.batch_combo._popup_frame.isVisible(), "Batch popup must open automatically on Tab from Item")

        # 3. Press Down Arrow to navigate to 2nd batch (14253406A)
        down_ev = QKeyEvent(QEvent.KeyPress, Qt.Key_Down, Qt.NoModifier)
        bar.batch_combo.eventFilter(bar.batch_combo.lineEdit(), down_ev)
        app.processEvents()

        cur_row = bar.batch_combo.table_view.currentIndex().row()
        self.assertEqual(cur_row, 1, "Down arrow should move highlight to row 1")

        # 4. Press Tab to commit selected batch
        bar.batch_combo.eventFilter(bar.batch_combo.lineEdit(), tab_ev)
        app.processEvents()

        # Batch popup should close, batch 14253406A should be selected
        self.assertFalse(bar.batch_combo._popup_frame.isVisible(), "Batch popup must close after Tab commit")
        self.assertEqual(bar.batch_combo.currentText(), "14253406A")
        self.assertEqual(bar.batch_combo.currentData(), 2)
        self.assertEqual(bar.mrp_edit.text(), "341.34")
        self.assertEqual(bar.expiry_edit.text(), "2028-07-31")

        # Focus should advance to qty_edit
        self.assertEqual(app.focusWidget(), bar.qty_edit)
        bar.close()


if __name__ == "__main__":
    unittest.main()
