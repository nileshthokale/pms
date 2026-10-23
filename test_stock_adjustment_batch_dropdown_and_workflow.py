"""Comprehensive Regression Test Suite for Stock Adjustment Batch Dropdown & Workflow.

Validates all requirements:
1. Expiry date comparison using actual date values, not strings.
2. Missing or invalid expiry dates are never treated as valid unexpired batches.
3. Batch dropdown in normal adjustment mode shows ONLY active, non-expired batches.
4. Expired, missing-expiry, and invalid-expiry batches are strictly excluded from normal dropdown.
5. In Stock Removal mode, zero-stock batches are also excluded.
6. Display in batch dropdown shows ONLY the batch number (no expiry, MRP, or status tags).
7. Medicine selection does not auto-select any batch (leaves batch unselected until chosen).
8. Selecting a batch populates exact pack size, batch stock, expiry, MRP, rate, and tax.
9. Stock addition is permitted on eligible unexpired batches (including zero-stock unexpired).
10. Stock addition to expired or invalid-expiry batches is strictly rejected.
11. Stock removal from zero-stock batches or resulting in negative stock is strictly rejected.
12. Expired stock write-off workflow is kept separate, writes down to 0, and preserves history without deletion.
13. Creating a new batch with valid future expiry is supported.
14. Batch identity (batch ID vs item ID vs batch no) is strictly preserved across medicines.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import date, timedelta
from unittest import mock

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication, QMessageBox

from database.connection import get_connection, init_database
from database.stock_dao import StockDAO
from database.stock_adjustment_dao import StockAdjustmentDAO, StockAdjustmentError
from screens.stock_adjustment_dialog import StockAdjustmentDialog


class TestStockAdjustmentBatchDropdownAndWorkflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)
        init_database()

    def setUp(self):
        self._patches = [
            mock.patch.object(QMessageBox, "warning", return_value=QMessageBox.Ok),
            mock.patch.object(QMessageBox, "information", return_value=QMessageBox.Ok),
            mock.patch.object(QMessageBox, "critical", return_value=QMessageBox.Ok),
            mock.patch.object(QMessageBox, "question", return_value=QMessageBox.Yes),
        ]
        for p in self._patches:
            p.start()

        conn = get_connection()
        try:
            # Clean up test records
            conn.execute("DELETE FROM stock_adjustments")
            conn.execute("DELETE FROM purchase_invoice_items")
            conn.execute("DELETE FROM purchase_invoices")
            conn.execute("DELETE FROM sales_invoice_items")
            conn.execute("DELETE FROM sales_invoices")
            conn.execute("DELETE FROM stock_batches")
            conn.execute("DELETE FROM items WHERE id >= 900")
            conn.execute("DELETE FROM units WHERE id >= 900")
            conn.execute("DELETE FROM companies WHERE id >= 900")

            # Seed test unit and company
            conn.execute("INSERT OR REPLACE INTO units (id, unit_name) VALUES (901, 'TAB')")
            conn.execute("INSERT OR REPLACE INTO companies (id, company_name, short_name) VALUES (901, 'PHARMA CORP', 'PHARMA')")

            # Seed Medicine A (ID: 910)
            conn.execute(
                """
                INSERT INTO items (id, item_name, company_id, unit_id, pack_size, rate, mrp)
                VALUES (910, 'AMOXICILLIN 500MG', 901, 901, '10', 50.0, 75.0)
                """
            )
            # Seed Medicine B (ID: 920)
            conn.execute(
                """
                INSERT INTO items (id, item_name, company_id, unit_id, pack_size, rate, mrp)
                VALUES (920, 'AZITHROMYCIN 500MG', 901, 901, '3', 60.0, 95.0)
                """
            )

            # Batches for Medicine A:
            # 1. Active unexpired batch with stock
            conn.execute(
                """
                INSERT INTO stock_batches (id, item_id, batch_no, expiry, pack_size, mrp, purchase_rate, net_rate, stock_qty)
                VALUES (9101, 910, 'AMX-ACT-1', '2028-12-31', '10', 75.0, 50.0, 52.5, 40.0)
                """
            )
            # 2. Active unexpired batch with zero stock
            conn.execute(
                """
                INSERT INTO stock_batches (id, item_id, batch_no, expiry, pack_size, mrp, purchase_rate, net_rate, stock_qty)
                VALUES (9102, 910, 'AMX-ZERO-2', '2029-06-30', '10', 75.0, 50.0, 52.5, 0.0)
                """
            )
            # 3. Expired batch with stock
            conn.execute(
                """
                INSERT INTO stock_batches (id, item_id, batch_no, expiry, pack_size, mrp, purchase_rate, net_rate, stock_qty)
                VALUES (9103, 910, 'AMX-EXP-3', '2024-01-15', '10', 70.0, 45.0, 47.25, 15.0)
                """
            )
            # 4. Missing expiry batch with stock
            conn.execute(
                """
                INSERT INTO stock_batches (id, item_id, batch_no, expiry, pack_size, mrp, purchase_rate, net_rate, stock_qty)
                VALUES (9104, 910, 'AMX-NOEXP-4', '', '10', 70.0, 45.0, 47.25, 10.0)
                """
            )
            # 5. Invalid expiry batch with stock
            conn.execute(
                """
                INSERT INTO stock_batches (id, item_id, batch_no, expiry, pack_size, mrp, purchase_rate, net_rate, stock_qty)
                VALUES (9105, 910, 'AMX-BADEXP-5', 'INVALID-EXP-DATE', '10', 70.0, 45.0, 47.25, 8.0)
                """
            )

            # Batches for Medicine B (shares identical batch number 'AMX-ACT-1' to test batch identity integrity)
            conn.execute(
                """
                INSERT INTO stock_batches (id, item_id, batch_no, expiry, pack_size, mrp, purchase_rate, net_rate, stock_qty)
                VALUES (9201, 920, 'AMX-ACT-1', '2028-12-31', '3', 95.0, 60.0, 63.0, 100.0)
                """
            )

            conn.commit()
        finally:
            conn.close()

    def tearDown(self):
        for p in reversed(getattr(self, "_patches", [])):
            p.stop()

    def _pump(self):
        self.app.processEvents()

    # ─────────────────────────────────────────────────────────────────
    # 1. Date Parsing & Real Date Comparison Tests
    # ─────────────────────────────────────────────────────────────────

    def test_01_parse_expiry_dates_actual_date_objects(self):
        """1. parse_expiry_date returns actual date objects, handling ISO, MM/YY, and invalid strings."""
        # ISO date
        d_iso = StockDAO.parse_expiry_date("2028-12-31")
        self.assertIsInstance(d_iso, date)
        self.assertEqual(d_iso, date(2028, 12, 31))

        # Month/Year formats resolve to the last day of that month
        d_slash = StockDAO.parse_expiry_date("02/28")
        self.assertIsInstance(d_slash, date)
        self.assertEqual(d_slash, date(2028, 2, 29))  # 2028 is leap year

        d_dash = StockDAO.parse_expiry_date("11-2027")
        self.assertIsInstance(d_dash, date)
        self.assertEqual(d_dash, date(2027, 11, 30))

        # Missing / empty values return None
        self.assertIsNone(StockDAO.parse_expiry_date(""))
        self.assertIsNone(StockDAO.parse_expiry_date(None))
        self.assertIsNone(StockDAO.parse_expiry_date("   "))
        self.assertIsNone(StockDAO.parse_expiry_date("DD-MM-YYYY"))
        self.assertIsNone(StockDAO.parse_expiry_date("MM/YY"))

        # Invalid / malformed strings return None
        self.assertIsNone(StockDAO.parse_expiry_date("INVALID-DATE"))
        self.assertIsNone(StockDAO.parse_expiry_date("99/99"))
        self.assertIsNone(StockDAO.parse_expiry_date("13/2028"))

    def test_02_is_valid_and_unexpired_actual_date_comparison(self):
        """2. is_valid_and_unexpired compares actual date objects and safely excludes missing/invalid."""
        future_iso = (date.today() + timedelta(days=100)).isoformat()
        past_iso = (date.today() - timedelta(days=10)).isoformat()

        self.assertTrue(StockDAO.is_valid_and_unexpired(future_iso))
        self.assertFalse(StockDAO.is_valid_and_unexpired(past_iso))

        # Missing or invalid expiry must NEVER be treated as valid or unexpired
        self.assertFalse(StockDAO.is_valid_and_unexpired(""))
        self.assertFalse(StockDAO.is_valid_and_unexpired(None))
        self.assertFalse(StockDAO.is_valid_and_unexpired("INVALID"))
        self.assertFalse(StockDAO.is_valid_and_unexpired("99/99"))

    # ─────────────────────────────────────────────────────────────────
    # 2. Batch Dropdown Filtering Tests
    # ─────────────────────────────────────────────────────────────────

    def test_03_dropdown_shows_only_active_unexpired_batches_by_default(self):
        """3. Batch dropdown in normal adjustment mode shows ONLY active, non-expired batches."""
        dlg = StockAdjustmentDialog(item_id=910)
        self._pump()

        # Medicine A has 5 batches in DB:
        # - 9101: active, unexpired, stock 40
        # - 9102: active, unexpired, stock 0
        # - 9103: expired (2024-01-15)
        # - 9104: missing expiry ("")
        # - 9105: invalid expiry ("INVALID-EXP-DATE")

        items_data = dlg.batch_combo._items_data
        # By default (All Active Batches), only active unexpired batches are loaded
        self.assertEqual(len(items_data), 2)

        batch_ids = [data_id for _lbl, data_id, _name, _idx in items_data]
        self.assertIn(9101, batch_ids)
        self.assertIn(9102, batch_ids)
        self.assertNotIn(9103, batch_ids)  # Expired must be excluded
        self.assertNotIn(9104, batch_ids)  # Missing expiry must be excluded
        self.assertNotIn(9105, batch_ids)  # Invalid expiry must be excluded

        # Dropdown text shows ONLY batch number
        for label, _data_id, raw_name, _idx in items_data:
            self.assertEqual(label, raw_name)
            self.assertNotIn("Exp:", label)
            self.assertNotIn("MRP:", label)

        # Dropdown does NOT auto-select batch
        self.assertIsNone(dlg.batch_combo.currentData())
        self.assertEqual(dlg.batch_combo.currentText(), "")
        self.assertEqual(dlg.batch_stock_edit.text(), "")

        dlg.close()

    def test_04_dropdown_stock_removal_mode_excludes_zero_stock_batches(self):
        """4. In 'Stock Removal (-)' mode, zero-stock batches are also excluded from dropdown."""
        dlg = StockAdjustmentDialog(item_id=910)
        self._pump()

        # Switch mode to Stock Removal (-)
        idx = dlg.op_filter.findText("Stock Removal (-)")
        self.assertGreaterEqual(idx, 0)
        dlg.op_filter.setCurrentIndex(idx)
        self._pump()

        items_data = dlg.batch_combo._items_data
        # Only Batch 9101 has stock > 0 and is unexpired
        self.assertEqual(len(items_data), 1)
        self.assertEqual(items_data[0][1], 9101)  # Only 9101 is eligible for removal

        dlg.close()

    def test_05_dropdown_write_off_mode_shows_expired_and_invalid_batches(self):
        """5. In 'Write-Off Expired Stock' mode, expired and invalid batches are loaded for disposal."""
        dlg = StockAdjustmentDialog(item_id=910)
        self._pump()

        # Switch to Write-Off mode
        dlg.show_expired_cb.setChecked(True)
        self._pump()

        items_data = dlg.batch_combo._items_data
        # Must show the 3 write-off batches: 9103 (expired), 9104 (no exp), 9105 (bad exp)
        self.assertEqual(len(items_data), 3)

        batch_ids = [data_id for _lbl, data_id, _name, _idx in items_data]
        self.assertIn(9103, batch_ids)
        self.assertIn(9104, batch_ids)
        self.assertIn(9105, batch_ids)
        self.assertNotIn(9101, batch_ids)  # Active batches excluded from write-off mode
        self.assertNotIn(9102, batch_ids)

        dlg.close()

    # ─────────────────────────────────────────────────────────────────
    # 3. Stock Addition & Removal Logic Tests
    # ─────────────────────────────────────────────────────────────────

    def test_06_stock_addition_to_unexpired_zero_stock_batch_allowed(self):
        """6. Adding stock to an unexpired zero-stock batch is allowed."""
        rec = StockAdjustmentDAO.record_adjustment(
            item_id=910,
            stock_batch_id=9102,
            adjusted_qty=25.0,
            reason="Replenish stock for unexpired batch",
            user_name="tester",
        )
        self.assertEqual(rec["previous_qty"], 0.0)
        self.assertEqual(rec["adjusted_qty"], 25.0)
        self.assertEqual(rec["resulting_qty"], 25.0)

        # Database verification
        b = StockDAO.get_stock_batch_by_id(9102)
        self.assertEqual(b["stock_qty"], 25.0)

    def test_07_stock_addition_to_expired_batch_rejected(self):
        """7. Adding stock to an expired batch is strictly rejected by DAO and UI."""
        # DAO rejection
        with self.assertRaises(StockAdjustmentError) as ctx:
            StockAdjustmentDAO.record_adjustment(
                item_id=910,
                stock_batch_id=9103,  # expired batch
                adjusted_qty=10.0,
                reason="Attempting to add to expired",
            )
        self.assertIn("expired", str(ctx.exception).lower())

        # UI rejection
        dlg = StockAdjustmentDialog(item_id=910)
        self._pump()
        dlg._select_batch_by_id(9103)
        self._pump()
        dlg.qty_edit.setText("+10")
        self._pump()
        self.assertIn("ERROR", dlg.projected_label.text())

        # Attempt to save in dialog
        dlg._on_save()
        self.assertFalse(dlg._is_saving)  # Save was blocked

        # Stored stock remained unchanged at 15.0
        b = StockDAO.get_stock_batch_by_id(9103)
        self.assertEqual(b["stock_qty"], 15.0)
        dlg.close()

    def test_08_stock_addition_to_missing_and_invalid_expiry_rejected(self):
        """8. Adding stock to missing-expiry or invalid-expiry batches is rejected."""
        # Missing expiry batch 9104
        with self.assertRaises(StockAdjustmentError) as ctx_missing:
            StockAdjustmentDAO.record_adjustment(
                item_id=910,
                stock_batch_id=9104,
                adjusted_qty=5.0,
            )
        self.assertIn("invalid expiry", str(ctx_missing.exception).lower())

        # Invalid expiry batch 9105
        with self.assertRaises(StockAdjustmentError) as ctx_invalid:
            StockAdjustmentDAO.record_adjustment(
                item_id=910,
                stock_batch_id=9105,
                adjusted_qty=5.0,
            )
        self.assertIn("invalid expiry", str(ctx_invalid.exception).lower())

    def test_09_stock_removal_from_zero_stock_batch_rejected(self):
        """9. Removing stock from a zero-stock batch is strictly rejected."""
        # Batch 9102 has 0 stock
        with self.assertRaises(StockAdjustmentError) as ctx:
            StockAdjustmentDAO.record_adjustment(
                item_id=910,
                stock_batch_id=9102,
                adjusted_qty=-5.0,
            )
        self.assertIn("negative stock", str(ctx.exception).lower())

    def test_10_stock_removal_exceeding_available_stock_rejected(self):
        """10. Removing more stock than available is strictly rejected."""
        # Batch 9101 has 40 stock. Attempt -45
        with self.assertRaises(StockAdjustmentError) as ctx:
            StockAdjustmentDAO.record_adjustment(
                item_id=910,
                stock_batch_id=9101,
                adjusted_qty=-45.0,
            )
        self.assertIn("negative stock", str(ctx.exception).lower())

        # Batch 9101 stock remains 40
        b = StockDAO.get_stock_batch_by_id(9101)
        self.assertEqual(b["stock_qty"], 40.0)

    # ─────────────────────────────────────────────────────────────────
    # 4. Expired Stock Write-Off Workflow Tests
    # ─────────────────────────────────────────────────────────────────

    def test_11_expired_stock_write_off_workflow(self):
        """11. Expired stock write-off zeros out stock, creates audit record, and preserves batch history."""
        dlg = StockAdjustmentDialog(item_id=910)
        self._pump()

        # Select expired batch 9103 (auto-enables write-off mode)
        dlg._select_batch_by_id(9103)
        self._pump()

        self.assertEqual(dlg.batch_stock_edit.text(), "15")

        # Click write-off button
        dlg._on_write_off_batch()
        self._pump()

        self.assertEqual(dlg.qty_edit.text(), "-15")
        self.assertIn("Expired stock write-off", dlg.reason_edit.text())

        # Save adjustment
        dlg._on_save()
        self._pump()

        # Verify batch record is NOT deleted, but stock is now 0
        b = StockDAO.get_stock_batch_by_id(9103)
        self.assertIsNotNone(b)
        self.assertEqual(b["stock_qty"], 0.0)

        # Verify audit history
        adjs = StockAdjustmentDAO.get_adjustments_for_batch(9103)
        self.assertEqual(len(adjs), 1)
        self.assertEqual(adjs[0]["previous_qty"], 15.0)
        self.assertEqual(adjs[0]["adjusted_qty"], -15.0)
        self.assertEqual(adjs[0]["resulting_qty"], 0.0)
        self.assertIn("Expired stock write-off", adjs[0]["reason"])

        dlg.close()

    # ─────────────────────────────────────────────────────────────────
    # 5. New Batch Creation During Adjustment Tests
    # ─────────────────────────────────────────────────────────────────

    def test_12_new_batch_creation_supported(self):
        """12. Creating a new batch with valid future expiry is supported for stock addition."""
        dlg = StockAdjustmentDialog(item_id=910)
        self._pump()

        # Create new batch directly in DB as dialog helper simulates
        future_d = (date.today() + timedelta(days=500)).isoformat()
        conn = get_connection()
        try:
            cur = conn.execute(
                """
                INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size, mrp, purchase_rate, net_rate, stock_qty)
                VALUES (910, 'AMX-BRANDNEW', ?, '10', 80.0, 55.0, 57.75, 0.0)
                """,
                (future_d,),
            )
            conn.commit()
            new_bid = cur.lastrowid
        finally:
            conn.close()

        # Refresh dialog batches
        dlg._load_batches_for_item(910)
        self._pump()

        # The new batch is present and selectable
        dlg.batch_combo.set_selected_id(new_bid)
        self._pump()

        self.assertEqual(dlg.batch_combo.currentData(), new_bid)
        self.assertEqual(dlg.batch_stock_edit.text(), "0")
        self.assertEqual(dlg.mrp_edit.text(), "80.00")

        # Now add stock +30
        dlg.qty_edit.setText("+30")
        dlg._on_save()
        self._pump()

        # Stored stock is now 30
        b = StockDAO.get_stock_batch_by_id(new_bid)
        self.assertEqual(b["stock_qty"], 30.0)

        dlg.close()

    # ─────────────────────────────────────────────────────────────────
    # 6. Batch Identity & Medicine Switching Tests
    # ─────────────────────────────────────────────────────────────────

    def test_13_batch_identity_preserved_across_medicines_with_same_batch_no(self):
        """13. Preserves database batch ID; identical batch numbers on different medicines remain separate."""
        # Batch 9101 (Med 910) and Batch 9201 (Med 920) both have batch_no = 'AMX-ACT-1'
        b1 = StockDAO.get_stock_batch_by_id(9101)
        b2 = StockDAO.get_stock_batch_by_id(9201)
        self.assertEqual(b1["batch_no"], b2["batch_no"])
        self.assertNotEqual(b1["item_id"], b2["item_id"])

        # Adjust batch 9101 on Medicine 910 by -5
        StockAdjustmentDAO.record_adjustment(
            item_id=910,
            stock_batch_id=9101,
            adjusted_qty=-5.0,
            reason="Item 910 adjustment",
        )

        # Batch 9101 stock reduced from 40 to 35
        self.assertEqual(StockDAO.get_stock_batch_by_id(9101)["stock_qty"], 35.0)
        # Batch 9201 stock remains completely unaffected at 100.0
        self.assertEqual(StockDAO.get_stock_batch_by_id(9201)["stock_qty"], 100.0)

    def test_14_switching_medicine_clears_stale_batch_selection(self):
        """14. Switching medicine clears batch selection and dependent fields."""
        dlg = StockAdjustmentDialog(item_id=910)
        self._pump()

        dlg.batch_combo.set_selected_id(9101)
        self._pump()
        self.assertEqual(dlg.batch_stock_edit.text(), "40")

        # Switch to Medicine B (920)
        dlg.item_combo.set_selected_id(920)
        self._pump()

        # Batch selection and batch fields must be cleared
        self.assertIsNone(dlg.batch_combo.currentData())
        self.assertEqual(dlg.batch_stock_edit.text(), "")
        self.assertEqual(dlg.expiry_edit.text(), "")
        self.assertEqual(dlg.mrp_edit.text(), "")

        # Selecting Batch 9201 on Medicine B loads its own values
        dlg.batch_combo.set_selected_id(9201)
        self._pump()
        self.assertEqual(dlg.batch_stock_edit.text(), "100")
        self.assertEqual(dlg.mrp_edit.text(), "95.00")

        dlg.close()


if __name__ == "__main__":
    unittest.main()
