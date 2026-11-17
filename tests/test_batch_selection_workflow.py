"""Test batch selection workflow, 5-row popup sizing, status column removal,
and keyboard navigation (Type Item -> Tab -> Up/Down -> Tab -> Qty).
"""
import os
import shutil
import sys
import tempfile
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, ".")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QKeyEvent

from ui.components import TableComboBox, DEFAULT_BATCH_COLUMNS
from screens.counter_sale import CounterSalePage, _ItemEntryBar
import database.connection as db_conn
from database.connection import init_database, get_connection
from database.account_roles import ensure_system_ledgers
from database.financial_year import ensure_default_financial_year

app = QApplication.instance() or QApplication([])


class TestBatchSelectionWorkflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp_dir = tempfile.mkdtemp(prefix="pms_test_batch_wf_")
        cls.db_path = os.path.join(cls.tmp_dir, "test_batch_wf.db")
        cls._orig_env = os.environ.get("PHARMACY_DB")
        os.environ["PHARMACY_DB"] = cls.db_path

        init_database()
        ensure_system_ledgers()
        ensure_default_financial_year()

        conn = get_connection()
        try:
            conn.execute("INSERT OR IGNORE INTO units (id, unit_name) VALUES (1, 'TAB')")
            conn.execute("INSERT OR IGNORE INTO companies (id, company_name, short_name) VALUES (1, 'SUN PHARMA', 'SUN')")
            conn.execute(
                "INSERT OR REPLACE INTO items (id, item_name, company_id, unit_id, pack_size, location, mrp) "
                "VALUES (101, 'BIO D3 PLUS (TABLET)', 1, 1, '10', 'RACK-1', 301.0)"
            )
            conn.execute(
                "INSERT OR REPLACE INTO items (id, item_name, company_id, unit_id, pack_size, location, mrp) "
                "VALUES (102, 'PARACETAMOL 500', 1, 1, '10', 'RACK-2', 50.0)"
            )
            batches = [
                (1, 101, "KBC2402A", "2026-12-31", "10", 301.0, 215.0, 215.0, 10.0),
                (2, 101, "14253406A", "2028-07-31", "10", 341.34, 260.07, 260.07, 5.0),
                (3, 101, "14261266A", "2029-02-28", "10", 341.34, 260.07, 260.07, 40.0),
            ]
            for bid, iid, bno, exp, pack, mrp, prate, nrate, stock in batches:
                conn.execute(
                    "INSERT OR REPLACE INTO stock_batches (id, item_id, batch_no, expiry, pack_size, mrp, purchase_rate, net_rate, stock_qty) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (bid, iid, bno, exp, pack, mrp, prate, nrate, stock),
                )
            conn.commit()
        finally:
            conn.close()

    @classmethod
    def tearDownClass(cls):
        if cls._orig_env is not None:
            os.environ["PHARMACY_DB"] = cls._orig_env
        else:
            os.environ.pop("PHARMACY_DB", None)
        try:
            shutil.rmtree(cls.tmp_dir, ignore_errors=True)
        except Exception:
            pass
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

        # Focus should advance to pack_edit
        self.assertEqual(app.focusWidget(), bar.pack_edit)
        bar.close()


if __name__ == "__main__":
    unittest.main()
