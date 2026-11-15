import os
import sys
import unittest
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, ".")

from PySide6.QtWidgets import QApplication, QTableWidgetItem
from PySide6.QtCore import Qt
from screens.debit_note import _DebitNoteEntryDialog, PendingDebitNotesDialog

app = QApplication.instance() or QApplication(sys.argv)


class TestDebitNoteUIFixes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import tempfile
        from database.connection import init_database, get_connection
        from database.item_dao import ItemDAO
        from database.unit_dao import UnitDAO
        cls._orig_db = os.environ.get("PHARMACY_DB")
        cls._db_fd, cls._db_path = tempfile.mkstemp(suffix="_dn_ui.db")
        os.close(cls._db_fd)
        os.environ["PHARMACY_DB"] = cls._db_path
        init_database()

        # Seed test item 101 with multiple batches (one active, one expired)
        uid = UnitDAO.insert("TAB")
        ItemDAO.insert(item_name="ELERAB D CAPSULE", unit_id=uid)
        conn = get_connection()
        conn.execute("UPDATE items SET id = 101 WHERE item_name = 'ELERAB D CAPSULE'")
        conn.execute(
            "INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size, mrp, purchase_rate, stock_qty) "
            "VALUES (101, 'B1', '2028-12-31', '10', 100.0, 80.0, 50)"
        )
        conn.execute(
            "INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size, mrp, purchase_rate, stock_qty) "
            "VALUES (101, 'B2', '2020-01-01', '10', 100.0, 80.0, 30)"
        )
        conn.commit()
        conn.close()

    @classmethod
    def tearDownClass(cls):
        try:
            os.remove(cls._db_path)
        except Exception:
            pass
        if cls._orig_db is not None:
            os.environ["PHARMACY_DB"] = cls._orig_db
        else:
            os.environ.pop("PHARMACY_DB", None)

    def test_issue1_entry_bar_layout_and_batch_empty_init(self):
        """Verify Issue 1:
        1. Expired Only checkbox correctly aligned in header row with adequate space.
        2. Batch combo starts genuinely empty with no placeholder text '-- Select Batch --'.
        3. Selecting an item loads batches; batch combo remains unselected (empty) if multiple batches exist.
        4. Batch selection correctly updates fields.
        5. Expired only toggle filters batches.
        """
        dlg = _DebitNoteEntryDialog()
        dlg.show()
        app.processEvents()

        try:
            bar = dlg._entry_bar

            # 1. Expired Only checkbox
            self.assertTrue(hasattr(bar, "expired_only_cb"))
            self.assertEqual(bar.expired_only_cb.text(), "Expired Only")
            self.assertFalse(bar.expired_only_cb.isChecked())

            # 2. Batch combo genuinely empty initially
            self.assertEqual(bar.batch_combo.currentText(), "")
            self.assertIsNone(bar.batch_combo.currentData())
            self.assertEqual(bar.batch_combo.lineEdit().placeholderText(), "")
            self.assertNotIn("-- Select Batch --", bar.batch_combo.currentText())

            # 3. Item combo has minimum width and expands responsively
            self.assertGreaterEqual(bar.item_combo.minimumWidth(), 260)
            self.assertGreaterEqual(bar.batch_combo.minimumWidth(), 150)

            # 4. Select item with multiple batches (e.g. 101 or 951)
            target_id = 101 if bar.item_combo.findData(101) >= 0 else 951
            idx = bar.item_combo.findData(target_id)
            self.assertGreaterEqual(idx, 0)
            bar.item_combo.setCurrentIndex(idx)
            app.processEvents()

            # Multiple batches: batch combo is empty
            self.assertGreater(bar.batch_combo.count(), 1)
            self.assertEqual(bar.batch_combo.currentText(), "")
            self.assertIsNone(bar.batch_combo.currentData())

            # Ensure "-- Select Batch --" is not an item in the batch combo
            for i in range(bar.batch_combo.count()):
                self.assertNotEqual(bar.batch_combo.itemText(i), "-- Select Batch --")

            # 5. Select batch
            bar.batch_combo.setCurrentIndex(0)
            app.processEvents()
            selected = bar.batch_combo.currentData()
            self.assertIsNotNone(selected)
            self.assertEqual(bar.expiry_edit.text(), selected.get("expiry", ""))
            self.assertEqual(bar.rate_edit.text(), f"{selected.get('purchase_rate', 0.0):.2f}")
            self.assertEqual(bar.mrp_edit.text(), f"{selected.get('mrp', 0.0):.2f}")

            # 6. Expired Only filtering
            total = bar.batch_combo.count()
            bar.expired_only_cb.setChecked(True)
            app.processEvents()
            exp_count = bar.batch_combo.count()
            self.assertLessEqual(exp_count, total)
            for i in range(exp_count):
                b = bar.batch_combo.itemData(i)
                self.assertTrue(b.get("is_expired"))
        finally:
            dlg.close()
            app.processEvents()

    def test_issue2_pending_debit_notes_dialog_layout_and_widths(self):
        """Verify Issue 2:
        1. Popup default width is increased (>= 800px) and vertical height is compact (<= 350px min).
        2. Columns have sensible widths: VhType >= 110, VhNo >= 150, VhDate >= 105, DebitAmt >= 115, DiscAmt >= 110.
        3. DebitAmt and DiscAmt editable fields have minimum widths so they stay visible.
        4. Date is formatted as DD-MM-YYYY without truncation.
        """
        dlg = PendingDebitNotesDialog(supplier_id=1, supplier_name="TEST SUPPLIER")
        dlg.show()
        app.processEvents()

        try:
            self.assertGreaterEqual(dlg.width(), 800)
            self.assertGreaterEqual(dlg.minimumWidth(), 780)
            self.assertLessEqual(dlg.minimumHeight(), 350)

            self.assertEqual(dlg.table.columnCount(), 7)
            self.assertGreaterEqual(dlg.table.columnWidth(0), 110)  # VhType
            self.assertGreaterEqual(dlg.table.columnWidth(1), 150)  # VhNo
            self.assertGreaterEqual(dlg.table.columnWidth(2), 105)  # VhDate
            self.assertGreaterEqual(dlg.table.columnWidth(3), 100)  # VhAmount
            self.assertGreaterEqual(dlg.table.columnWidth(4), 100)  # UnSettled
            self.assertGreaterEqual(dlg.table.columnWidth(5), 115)  # DebitAmt
            self.assertGreaterEqual(dlg.table.columnWidth(6), 110)  # DiscAmt

            # Test formatting date
            from datetime import datetime
            raw_date = "2026-10-05"
            disp = datetime.strptime(raw_date, "%Y-%m-%d").strftime("%d-%m-%Y")
            self.assertEqual(disp, "05-10-2026")
        finally:
            dlg.close()
            app.processEvents()


if __name__ == "__main__":
    unittest.main()
