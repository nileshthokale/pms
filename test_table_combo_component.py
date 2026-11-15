import unittest
import os
import sys
import tempfile
from unittest.mock import patch
from datetime import datetime, date
from typing import Any

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QKeyEvent
from PySide6.QtCore import Qt, QEvent

app = QApplication.instance() or QApplication([])

import database.connection as db_conn
from ui.components import TableComboBox, DEFAULT_BATCH_COLUMNS


class TestTableComboBox(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._temp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        cls._temp_path = cls._temp_file.name
        cls._temp_file.close()

        cls._db_patch = patch.object(db_conn, "get_db_path", return_value=cls._temp_path)
        cls._db_patch.start()
        db_conn.init_database()

        conn = db_conn.get_connection()
        try:
            conn.execute("INSERT OR IGNORE INTO account_groups (id, group_name) VALUES (1, 'Sundry Creditors'), (2, 'Sundry Debtors')")
            conn.execute("INSERT OR IGNORE INTO account_ledgers (id, ledger_name, account_group_id) VALUES (10, 'Supplier A', 1), (20, 'Walkin', 2)")
            conn.execute("INSERT OR IGNORE INTO suppliers (id, supplier_name, ledger_id) VALUES (1, 'ANAND PHARMA', 10)")
            conn.execute("INSERT OR IGNORE INTO customers (id, customer_name, ledger_id) VALUES (159, 'WALKIN', 20)")
            conn.execute("INSERT OR IGNORE INTO items (id, item_name, pack_size, mrp) VALUES (101, 'PARACETAMOL 650MG', '10', 30.0)")
            conn.execute("INSERT OR IGNORE INTO stock_batches (id, item_id, batch_no, expiry, pack_size, mrp, purchase_rate, stock_qty) VALUES (1, 101, 'BATCH-P1', '2028-12-31', '10', 30.0, 20.0, 100.0)")
            conn.commit()
        finally:
            conn.close()

    @classmethod
    def tearDownClass(cls):
        cls._db_patch.stop()
        if os.path.exists(cls._temp_path):
            try:
                os.remove(cls._temp_path)
            except OSError:
                pass
    def setUp(self):
        self.combo = TableComboBox(placeholder="Select Batch...")
        self.sample_batches = [
            {
                "id": 101,
                "batch_no": "ACR26040",
                "expiry": "2028-03-31",
                "pack_size": 10,
                "purchase_rate": 92.20,
                "mrp": 121.00,
                "stock_qty": 335.0,
                "is_expired": 0,
            },
            {
                "id": 102,
                "batch_no": "BBC-105",
                "expiry": "2020-09-30",
                "pack_size": 1,
                "purchase_rate": 64.29,
                "mrp": 90.00,
                "stock_qty": 0.0,
                "is_expired": 1,
            },
            {
                "id": 103,
                "batch_no": "BBC-141",
                "expiry": "2027-11-30",
                "pack_size": 1,
                "purchase_rate": 64.29,
                "mrp": 90.00,
                "stock_qty": 1.0,
                "is_expired": 0,
            },
        ]

    def test_01_set_batches_and_columns(self):
        self.combo.set_batches(self.sample_batches)
        # Row 0 is "-- Select Batch --", followed by 3 batches
        self.assertEqual(self.combo.count(), 4)
        self.assertEqual(self.combo._table_model.rowCount(), 4)
        self.assertEqual(self.combo._table_model.columnCount(), 6)

        # Header titles
        headers = [self.combo._table_model.headerData(c, Qt.Horizontal) for c in range(6)]
        self.assertEqual(headers, ["Batch No", "Expiry Date", "MRP", "Rate", "Balance", "Status"])

    def test_02_data_and_display_formatting(self):
        self.combo.set_batches(self.sample_batches)
        # Index 1 is ACR26040
        self.combo.setCurrentIndex(1)
        self.assertEqual(self.combo.currentText(), "ACR26040")
        self.assertEqual(self.combo.currentData(), self.sample_batches[0])

        # Table items formatting
        bno_item = self.combo._table_model.item(1, 0)
        exp_item = self.combo._table_model.item(1, 1)
        mrp_item = self.combo._table_model.item(1, 2)
        rate_item = self.combo._table_model.item(1, 3)
        bal_item = self.combo._table_model.item(1, 4)
        status_item = self.combo._table_model.item(1, 5)

        self.assertEqual(bno_item.text(), "ACR26040")
        self.assertEqual(exp_item.text(), "31-03-2028")
        self.assertEqual(mrp_item.text(), "121.00")
        self.assertEqual(rate_item.text(), "92.20")
        self.assertEqual(bal_item.text(), "335")
        self.assertEqual(status_item.text(), "Valid")

    def test_03_expired_and_zero_stock_visual_cues(self):
        self.combo.set_batches(self.sample_batches)
        # Index 2 is BBC-105 (Expired, stock 0)
        status_item = self.combo._table_model.item(2, 5)
        self.assertEqual(status_item.text(), "Expired")
        self.assertTrue(status_item.font().bold())

        # Balance item should be "0"
        bal_item = self.combo._table_model.item(2, 4)
        self.assertEqual(bal_item.text(), "0")

    def test_04_find_data_and_set_selected_id(self):
        self.combo.set_batches(self.sample_batches)
        idx = self.combo.findData(103)
        self.assertEqual(idx, 3)
        self.combo.setCurrentIndex(idx)
        self.assertEqual(self.combo.currentText(), "BBC-141")

    def test_05_legacy_add_item_compatibility(self):
        combo = TableComboBox()
        # Debit Note style: addItem(label, dict, raw_name=b_no)
        b = self.sample_batches[0]
        label = "ACR26040 (Exp: 2028-03-31, Stk: 335)"
        combo.addItem(label, b, raw_name="ACR26040")

        self.assertEqual(combo.count(), 1)
        combo.setCurrentIndex(0)
        self.assertEqual(combo.currentText(), "ACR26040")
        self.assertEqual(combo.currentData(), b)
        self.assertEqual(combo._table_model.item(0, 1).text(), "31-03-2028")
        self.assertEqual(combo._table_model.item(0, 2).text(), "121.00")

    def test_06_text_filter_search(self):
        self.combo.set_batches(self.sample_batches)
        # Type "BBC"
        self.combo._on_text_edited("BBC")
        # Row 1 (ACR26040) should be hidden, Row 2 and 3 should be visible
        self.assertTrue(self.combo.table_view.isRowHidden(1))
        self.assertFalse(self.combo.table_view.isRowHidden(2))
        self.assertFalse(self.combo.table_view.isRowHidden(3))

        # Clear filter
        self.combo._on_text_edited("")
        self.assertFalse(self.combo.table_view.isRowHidden(1))
        self.assertFalse(self.combo.table_view.isRowHidden(2))

    def test_07_keyboard_navigation(self):
        self.combo.set_batches(self.sample_batches)
        line = self.combo.lineEdit()

        # Press Down arrow to open popup
        down_event = QKeyEvent(QEvent.KeyPress, Qt.Key_Down, Qt.NoModifier)
        self.combo.eventFilter(line, down_event)
        self.assertTrue(self.combo._popup_frame.isVisible())
        self.assertEqual(self.combo.table_view.currentIndex().row(), 1)

        # Press Down arrow again to move selection to index 2
        self.combo.eventFilter(line, down_event)
        cur = self.combo.table_view.currentIndex()
        self.assertEqual(cur.row(), 2)

        # Press Up arrow to move back to index 1
        up_event = QKeyEvent(QEvent.KeyPress, Qt.Key_Up, Qt.NoModifier)
        self.combo.eventFilter(line, up_event)
        self.assertEqual(self.combo.table_view.currentIndex().row(), 1)

        # Press Enter to commit selection
        enter_event = QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier)
        self.combo.eventFilter(line, enter_event)
        self.assertFalse(self.combo._popup_frame.isVisible())
        self.assertEqual(self.combo.currentText(), "ACR26040")

    def test_08_set_table_data_generic(self):
        combo = TableComboBox()
        custom_cols = [
            {"key": "code", "header": "Item Code", "width": 80, "align": Qt.AlignLeft},
            {"key": "name", "header": "Description", "width": 200, "align": Qt.AlignLeft},
            {"key": "price", "header": "Price", "width": 80, "align": Qt.AlignRight},
        ]
        rows = [
            {"id": 1, "code": "IT001", "name": "Aspirin 100mg", "price": 45.0},
            {"id": 2, "code": "IT002", "name": "Vitamin C 500mg", "price": 85.0},
        ]
        combo.set_table_data(rows, columns=custom_cols, display_key="code", id_key="id", placeholder="-- Select Item --")
        self.assertEqual(combo.count(), 3)
        self.assertEqual(combo._table_model.columnCount(), 3)
        self.assertEqual(combo._table_model.headerData(1, Qt.Horizontal), "Description")

        combo.setCurrentIndex(1)
        self.assertEqual(combo.currentText(), "IT001")
        self.assertEqual(combo.currentData(), 1)

    def test_09_mouse_click_and_double_click_selection(self):
        self.combo.set_batches(self.sample_batches)
        self.combo.showPopup()
        self.assertTrue(self.combo._popup_frame.isVisible())

        # Click on row 3 (BBC-141)
        model_idx = self.combo._table_model.index(3, 0)
        self.combo._on_table_row_clicked(model_idx)

        self.assertFalse(self.combo._popup_frame.isVisible())
        self.assertEqual(self.combo.currentText(), "BBC-141")
        self.assertEqual(self.combo.currentData()["id"], 103)

    def test_10_escape_key_dismissal(self):
        self.combo.set_batches(self.sample_batches)
        self.combo.showPopup()
        self.assertTrue(self.combo._popup_frame.isVisible())

        # Press Escape
        esc_event = QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier)
        self.combo.eventFilter(self.combo.lineEdit(), esc_event)
        self.assertFalse(self.combo._popup_frame.isVisible())

    def test_11_tab_key_commits_and_dismisses(self):
        self.combo.set_batches(self.sample_batches)
        self.combo.showPopup()
        self.assertTrue(self.combo._popup_frame.isVisible())

        # Select row 2
        idx2 = self.combo._table_model.index(2, 0)
        self.combo.table_view.setCurrentIndex(idx2)

        # Press Tab
        tab_event = QKeyEvent(QEvent.KeyPress, Qt.Key_Tab, Qt.NoModifier)
        handled = self.combo.eventFilter(self.combo.lineEdit(), tab_event)
        # Should return False to let Tab advance focus
        self.assertFalse(handled)
        self.assertFalse(self.combo._popup_frame.isVisible())
        self.assertEqual(self.combo.currentText(), "BBC-105")

    def test_12_clean_closed_display_without_concatenated_strings(self):
        self.combo.set_batches(self.sample_batches)
        self.combo.setCurrentIndex(1)
        # Display in line edit must be purely the batch number
        self.assertEqual(self.combo.lineEdit().text(), "ACR26040")
        self.assertNotIn("Exp:", self.combo.lineEdit().text())
        self.assertNotIn("MRP:", self.combo.lineEdit().text())
        self.assertNotIn("Stk:", self.combo.lineEdit().text())
        self.assertNotIn("[EXP]", self.combo.lineEdit().text())

        # Tooltip should contain the full informative summary
        tooltip = self.combo.lineEdit().toolTip()
        self.assertIn("ACR26040", tooltip)
        self.assertIn("Exp: 31-03-2028", tooltip)
        self.assertIn("MRP: 121.00", tooltip)
        self.assertIn("Rate: 92.20", tooltip)
        self.assertIn("Balance: 335", tooltip)

    def test_13_debit_note_dialog_batch_auto_population(self):
        from screens.debit_note import _DebitNoteEntryDialog
        dlg = _DebitNoteEntryDialog()
        try:
            # TableComboBox is used for batch_combo
            self.assertIsInstance(dlg._entry_bar.batch_combo, TableComboBox)
            # Select supplier
            idx = dlg.supplier_combo.findData(1)
            if idx >= 0:
                dlg.supplier_combo.setCurrentIndex(idx)
            # Select item
            item_idx = dlg._entry_bar.item_combo.findData(101)
            if item_idx >= 0:
                dlg._entry_bar.item_combo.setCurrentIndex(item_idx)
                # Verify batch table has batch columns
                self.assertGreaterEqual(dlg._entry_bar.batch_combo.count(), 1)
                dlg._entry_bar.batch_combo.setCurrentIndex(0)
                # Fields auto-populated
                self.assertEqual(dlg._entry_bar.batch_combo.currentText(), "BATCH-P1")
                self.assertEqual(dlg._entry_bar.expiry_edit.text(), "2028-12-31")
                self.assertEqual(dlg._entry_bar.pack_edit.text(), "10")
                self.assertEqual(dlg._entry_bar.rate_edit.text(), "20.00")
                self.assertEqual(dlg._entry_bar.mrp_edit.text(), "30.00")
        finally:
            dlg.close()

    def test_14_credit_note_dialog_batch_auto_population(self):
        from screens.credit_note import _CreditNoteEntryDialog
        dlg = _CreditNoteEntryDialog()
        try:
            self.assertIsInstance(dlg._entry_bar.batch_combo, TableComboBox)
            # Select item
            item_idx = dlg._entry_bar.item_combo.findData(101)
            if item_idx >= 0:
                dlg._entry_bar.item_combo.setCurrentIndex(item_idx)
                self.assertGreaterEqual(dlg._entry_bar.batch_combo.count(), 2)
                dlg._entry_bar.batch_combo.setCurrentIndex(1)
                self.assertEqual(dlg._entry_bar.batch_combo.currentText(), "BATCH-P1")
                self.assertEqual(dlg._entry_bar.expiry_edit.text(), "2028-12-31")
                self.assertEqual(dlg._entry_bar.pack_edit.text(), "10")
                self.assertEqual(dlg._entry_bar.rate_edit.text(), "20.00")
                self.assertEqual(dlg._entry_bar.mrp_edit.text(), "30.00")
        finally:
            dlg.close()


if __name__ == "__main__":
    unittest.main()
