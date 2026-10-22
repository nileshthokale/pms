"""Automated tests for Stock Adjustment feature.

Matches Pharma-WINNER Stock Adjustment workflow:
1. A medicine with multiple batches
2. Selecting each batch loads that batch's own values
3. Positive adjustment (+2 adds loose units)
4. Negative adjustment (-1 removes loose units)
5. Rejection of invalid and zero quantities
6. Rejection of an adjustment that would create negative stock
7. Correct loose-unit and pack-size handling (no double multiplying)
8. Transaction rollback when saving fails
9. Correct stock refresh in Counter Sale
10. Preservation of purchase and sales history
11. Correct behavior for zero-stock and expired batches
12. Duplicate-click protection
13. Itemwise ledger movement integration
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication(sys.argv)

# Create isolated temporary database for test suite
_TMP_DIR = tempfile.mkdtemp(prefix="pms_stock_adj_test_")
_TMP_DB = os.path.join(_TMP_DIR, "stock_adj_test.db")
os.environ["PHARMACY_DB"] = _TMP_DB

from database.connection import get_connection, init_database
from database.stock_dao import StockDAO
from database.stock_adjustment_dao import StockAdjustmentDAO, StockAdjustmentError
from database.ledger_report_dao import LedgerReportDAO
from screens.stock_adjustment_dialog import StockAdjustmentDialog, _format_expiry_display
from screens.counter_sale import CounterSalePage, _SalePanel


class TestStockAdjustment(unittest.TestCase):
    """Test suite for Stock Adjustment feature and Pharma-WINNER workflow."""

    @classmethod
    def setUpClass(cls):
        init_database()

    @classmethod
    def tearDownClass(cls):
        try:
            if os.path.exists(_TMP_DB):
                os.remove(_TMP_DB)
            if os.path.exists(_TMP_DIR):
                shutil.rmtree(_TMP_DIR, ignore_errors=True)
        except Exception:
            pass

    def setUp(self):
        # Seed test data in the isolated test database
        conn = get_connection()
        try:
            conn.execute("DELETE FROM stock_adjustments")
            conn.execute("DELETE FROM sales_invoice_items")
            conn.execute("DELETE FROM sales_invoices")
            conn.execute("DELETE FROM purchase_invoice_items")
            conn.execute("DELETE FROM purchase_invoices")
            conn.execute("DELETE FROM stock_batches")
            conn.execute("DELETE FROM items")
            conn.execute("DELETE FROM suppliers")
            conn.execute("DELETE FROM customers")

            # 1. Supplier
            conn.execute("INSERT INTO suppliers (id, supplier_name) VALUES (1, 'ELEMENT PHARMA')")

            # 2. Customer
            conn.execute("INSERT INTO customers (id, customer_name) VALUES (1, 'WALKIN')")

            # 3. Item: ELERAB D CAPSULE (Pack 10)
            conn.execute(
                """
                INSERT INTO items (id, item_name, pack_size, mrp, rate)
                VALUES (101, 'ELERAB D CAPSULE', '10', 112.49, 85.72)
                """
            )
            # Item 102: PARACETAMOL 500MG TABLET (Pack 10) with 1 batch
            conn.execute(
                """
                INSERT INTO items (id, item_name, pack_size, mrp, rate)
                VALUES (102, 'PARACETAMOL 500MG TABLET', '10', 20.00, 15.00)
                """
            )
            # Item 103: NEW MEDICINE NO BATCHES with 0 batches
            conn.execute(
                """
                INSERT INTO items (id, item_name, pack_size, mrp, rate)
                VALUES (103, 'NEW MEDICINE NO BATCHES', '1', 50.00, 40.00)
                """
            )

            # 4. Batches for ELERAB D CAPSULE:
            # Batch 1: Available stock 627, Exp 2027-11-30
            conn.execute(
                """
                INSERT INTO stock_batches (id, item_id, batch_no, expiry, pack_size, mrp, purchase_rate, net_rate, stock_qty)
                VALUES (1001, 101, 'WEA8325001', '2027-11-30', '10', 112.49, 85.72, 90.01, 627.0)
                """
            )
            # Batch 2: Zero stock 0, Exp 2026-12-31
            conn.execute(
                """
                INSERT INTO stock_batches (id, item_id, batch_no, expiry, pack_size, mrp, purchase_rate, net_rate, stock_qty)
                VALUES (1002, 101, 'ACRD500GF.', '2026-12-31', '10', 112.50, 85.72, 90.01, 0.0)
                """
            )
            # Batch 3: Expired batch stock 15, Exp 2022-01-01
            conn.execute(
                """
                INSERT INTO stock_batches (id, item_id, batch_no, expiry, pack_size, mrp, purchase_rate, net_rate, stock_qty)
                VALUES (1003, 101, 'EXP888', '2022-01-01', '10', 99.00, 75.00, 78.75, 15.0)
                """
            )
            # Batch for Item 102: PARA-B1, stock 100, Exp 2028-05-31
            conn.execute(
                """
                INSERT INTO stock_batches (id, item_id, batch_no, expiry, pack_size, mrp, purchase_rate, net_rate, stock_qty)
                VALUES (2001, 102, 'PARA-B1', '2028-05-31', '10', 20.00, 15.00, 15.75, 100.0)
                """
            )

            # 5. Purchase history record for Batch 1 (tax 5%)
            conn.execute(
                """
                INSERT INTO purchase_invoices (id, voucher_no, voucher_date, supplier_id)
                VALUES (501, 'PINV-001', '2026-01-15', 1)
                """
            )
            conn.execute(
                """
                INSERT INTO purchase_invoice_items (purchase_invoice_id, item_id, batch_no, expiry, pack_size, pay_qty, free_qty, rate, mrp, gst_percent)
                VALUES (501, 101, 'WEA8325001', '2027-11-30', '10', 65, 0, 85.72, 112.49, 5.0)
                """
            )

            conn.commit()
        finally:
            conn.close()

    def test_01_multiple_batches_for_medicine(self):
        """1. A medicine with multiple batches loads all batches with IDs and flags."""
        batches = StockDAO.get_batches_for_adjustment(101)
        self.assertEqual(len(batches), 3)

        b_ids = [b["id"] for b in batches]
        self.assertIn(1001, b_ids)
        self.assertIn(1002, b_ids)
        self.assertIn(1003, b_ids)

        # Check Zero-stock flag on Batch 2
        b2 = next(b for b in batches if b["id"] == 1002)
        self.assertEqual(b2["stock_qty"], 0.0)
        self.assertTrue(b2["is_zero_stock"])
        self.assertFalse(b2["is_expired"])

        # Check Expired flag on Batch 3
        b3 = next(b for b in batches if b["id"] == 1003)
        self.assertEqual(b3["stock_qty"], 15.0)
        self.assertFalse(b3["is_zero_stock"])
        self.assertTrue(b3["is_expired"])

    def test_02_dialog_batch_selection_loads_exact_values(self):
        """2. Selecting each batch loads that batch's own values in the dialog."""
        dlg = StockAdjustmentDialog(item_id=101, stock_batch_id=1002)

        # Medicine name and PackSize
        self.assertIn("ELERAB D CAPSULE", dlg.item_combo.currentText())
        self.assertEqual(dlg.pack_edit.text(), "10")

        # Total item stock: active eligible stock = 627 (expired batch 1003 has 15, total book = 642)
        self.assertEqual(dlg.item_stock_edit.text(), "627")
        self.assertEqual(dlg._stock_summary["eligible_stock"], 627.0)
        self.assertEqual(dlg._stock_summary["expired_stock"], 15.0)
        self.assertEqual(dlg._stock_summary["total_book_stock"], 642.0)

        # Batch 2 is selected
        self.assertEqual(dlg.batch_combo.currentData(), 1002)
        self.assertEqual(dlg.batch_stock_edit.text(), "0")
        self.assertEqual(dlg.expiry_edit.text(), "12-2026")
        self.assertEqual(dlg.mrp_edit.text(), "112.50")
        self.assertEqual(dlg.rate_edit.text(), "85.72")
        self.assertEqual(dlg.net_rate_edit.text(), "90.01")

        # Switch to Batch 1
        dlg._select_batch_by_id(1001)
        self.assertEqual(dlg.batch_combo.currentData(), 1001)
        self.assertEqual(dlg.batch_stock_edit.text(), "627")
        self.assertEqual(dlg.expiry_edit.text(), "11-2027")
        self.assertEqual(dlg.mrp_edit.text(), "112.49")
        self.assertEqual(dlg.tax_edit.text(), "5.00%")
        self.assertEqual(dlg.net_rate_edit.text(), "90.01")

        dlg.close()

    def test_03_positive_adjustment_loose_units(self):
        """3. Positive adjustment adds loose units atomically with audit trail."""
        # Batch 1002 starts at 0 stock. Add +2 loose units
        record = StockAdjustmentDAO.record_adjustment(
            item_id=101,
            stock_batch_id=1002,
            adjusted_qty=2.0,
            reason="Found 2 physical capsules during inventory audit",
            user_name="admin",
        )

        self.assertIsNotNone(record["id"])
        self.assertEqual(record["previous_qty"], 0.0)
        self.assertEqual(record["adjusted_qty"], 2.0)
        self.assertEqual(record["resulting_qty"], 2.0)
        self.assertEqual(record["batch_no"], "ACRD500GF.")

        # Verify stock_batches table has updated stock_qty = 2
        batch = StockDAO.get_stock_batch_by_id(1002)
        self.assertIsNotNone(batch)
        self.assertEqual(batch["stock_qty"], 2.0)

        # Verify audit record in stock_adjustments table
        audit_records = StockAdjustmentDAO.get_adjustments_for_batch(1002)
        self.assertEqual(len(audit_records), 1)
        self.assertEqual(audit_records[0]["adjusted_qty"], 2.0)
        self.assertEqual(audit_records[0]["resulting_qty"], 2.0)
        self.assertEqual(audit_records[0]["reason"], "Found 2 physical capsules during inventory audit")

    def test_04_negative_adjustment_loose_units(self):
        """4. Negative adjustment removes loose units atomically."""
        # Batch 1001 starts at 627. Adjust by -27
        record = StockAdjustmentDAO.record_adjustment(
            item_id=101,
            stock_batch_id=1001,
            adjusted_qty=-27.0,
            reason="Damaged strip write-off",
            user_name="admin",
        )

        self.assertEqual(record["previous_qty"], 627.0)
        self.assertEqual(record["adjusted_qty"], -27.0)
        self.assertEqual(record["resulting_qty"], 600.0)

        # Verify database
        batch = StockDAO.get_stock_batch_by_id(1001)
        self.assertEqual(batch["stock_qty"], 600.0)

    def test_05_rejection_of_invalid_and_zero_quantities(self):
        """5. Rejection of invalid and zero quantities."""
        # Zero quantity
        with self.assertRaises(StockAdjustmentError) as ctx_zero:
            StockAdjustmentDAO.record_adjustment(
                item_id=101,
                stock_batch_id=1001,
                adjusted_qty=0.0,
            )
        self.assertIn("cannot be zero", str(ctx_zero.exception))

        # Invalid string non-numeric
        with self.assertRaises(StockAdjustmentError) as ctx_invalid:
            StockAdjustmentDAO.record_adjustment(
                item_id=101,
                stock_batch_id=1001,
                adjusted_qty="invalid_qty",  # type: ignore
            )
        self.assertIn("not a valid number", str(ctx_invalid.exception))

        # Stock remains untouched
        batch = StockDAO.get_stock_batch_by_id(1001)
        self.assertEqual(batch["stock_qty"], 627.0)

    def test_06_rejection_of_negative_resulting_stock(self):
        """6. Rejection of an adjustment that would create negative stock."""
        # Batch 1002 has 0 stock. Attempt -1
        with self.assertRaises(StockAdjustmentError) as ctx_neg:
            StockAdjustmentDAO.record_adjustment(
                item_id=101,
                stock_batch_id=1002,
                adjusted_qty=-1.0,
            )
        self.assertIn("negative stock", str(ctx_neg.exception))

        # Stock remains untouched at 0.0
        batch = StockDAO.get_stock_batch_by_id(1002)
        self.assertEqual(batch["stock_qty"], 0.0)

        # Batch 1003 has 15 stock. Attempt -16
        with self.assertRaises(StockAdjustmentError) as ctx_neg2:
            StockAdjustmentDAO.record_adjustment(
                item_id=101,
                stock_batch_id=1003,
                adjusted_qty=-16.0,
            )
        self.assertIn("negative stock", str(ctx_neg2.exception))
        batch3 = StockDAO.get_stock_batch_by_id(1003)
        self.assertEqual(batch3["stock_qty"], 15.0)

    def test_07_loose_unit_and_pack_size_convention(self):
        """7. Correct loose-unit and pack-size handling (no double multiplying)."""
        # Batch 1001 pack size is 10. Adjusting +5 adds exactly 5 loose units
        record = StockAdjustmentDAO.record_adjustment(
            item_id=101,
            stock_batch_id=1001,
            adjusted_qty=5.0,
        )
        self.assertEqual(record["resulting_qty"], 632.0)  # 627 + 5, NOT 627 + 50

        batch = StockDAO.get_stock_batch_by_id(1001)
        self.assertEqual(batch["stock_qty"], 632.0)

    def test_08_transaction_rollback_when_saving_fails(self):
        """8. Transaction rollback when saving fails."""
        conn = get_connection()
        try:
            # Batch 1002 has 0 stock. If we attempt -5 inside a transaction:
            with self.assertRaises(StockAdjustmentError):
                StockAdjustmentDAO.record_adjustment(
                    item_id=101,
                    stock_batch_id=1002,
                    adjusted_qty=-5.0,
                    conn=conn,
                )
            conn.rollback()

            # Ensure stock was not updated
            cur = conn.execute("SELECT stock_qty FROM stock_batches WHERE id = 1002")
            self.assertEqual(cur.fetchone()[0], 0.0)

            # Ensure no audit record created
            cur = conn.execute("SELECT COUNT(*) FROM stock_adjustments WHERE stock_batch_id = 1002")
            self.assertEqual(cur.fetchone()[0], 0)
        finally:
            conn.close()

    def test_09_correct_stock_refresh_in_counter_sale(self):
        """9. Correct stock refresh in Counter Sale entry bar."""
        panel = _SalePanel()
        entry_bar = panel._entry_bar

        # Select ELERAB D CAPSULE
        idx = entry_bar.item_combo.findData(101)
        self.assertGreaterEqual(idx, 0)
        entry_bar.item_combo.setCurrentIndex(idx)
        entry_bar._on_item_changed(idx)

        # Select Batch 1001 (initial stock 627)
        b_idx = entry_bar.batch_combo.findData(1001)
        self.assertGreaterEqual(b_idx, 0)
        entry_bar.batch_combo.setCurrentIndex(b_idx)
        self.assertEqual(entry_bar.stock_edit.text(), "627")

        # Perform an adjustment +33 on Batch 1001
        StockAdjustmentDAO.record_adjustment(
            item_id=101,
            stock_batch_id=1001,
            adjusted_qty=33.0,
        )

        # Trigger panel notification
        panel._on_stock_adjustment_applied(item_id=101, batch_id=1001, adj_qty=33.0, res_qty=660.0)

        # Counter Sale entry bar stock_edit immediately reflects 660!
        self.assertEqual(entry_bar.stock_edit.text(), "660")

    def test_10_preservation_of_purchase_and_sales_history(self):
        """10. Preservation of purchase and sales history."""
        # Check purchase history before adjustment
        conn = get_connection()
        try:
            p_items_before = conn.execute("SELECT * FROM purchase_invoice_items WHERE item_id = 101").fetchall()
            self.assertEqual(len(p_items_before), 1)
            orig_pay_qty = p_items_before[0]["pay_qty"]
            orig_rate = p_items_before[0]["rate"]
            orig_mrp = p_items_before[0]["mrp"]

            # Perform adjustment
            StockAdjustmentDAO.record_adjustment(
                item_id=101,
                stock_batch_id=1001,
                adjusted_qty=10.0,
            )

            # Check purchase history after adjustment
            p_items_after = conn.execute("SELECT * FROM purchase_invoice_items WHERE item_id = 101").fetchall()
            self.assertEqual(len(p_items_after), 1)
            self.assertEqual(p_items_after[0]["pay_qty"], orig_pay_qty)
            self.assertEqual(p_items_after[0]["rate"], orig_rate)
            self.assertEqual(p_items_after[0]["mrp"], orig_mrp)
        finally:
            conn.close()

    def test_11_zero_stock_and_expired_batches_workflow(self):
        """11. Correct behavior for zero-stock and expired batches."""
        # 1. Zero-stock batch 1002 can receive stock
        rec_zero = StockAdjustmentDAO.record_adjustment(
            item_id=101,
            stock_batch_id=1002,
            adjusted_qty=50.0,
            reason="Replenishment from extra stock",
        )
        self.assertEqual(rec_zero["previous_qty"], 0.0)
        self.assertEqual(rec_zero["resulting_qty"], 50.0)

        # 2. Expired batch 1003 can be written down to 0
        rec_exp = StockAdjustmentDAO.record_adjustment(
            item_id=101,
            stock_batch_id=1003,
            adjusted_qty=-15.0,
            reason="Disposed expired stock",
        )
        self.assertEqual(rec_exp["previous_qty"], 15.0)
        self.assertEqual(rec_exp["resulting_qty"], 0.0)

        batch_exp = StockDAO.get_stock_batch_by_id(1003)
        self.assertEqual(batch_exp["stock_qty"], 0.0)

    def test_12_duplicate_click_protection(self):
        """12. Duplicate-click protection on Stock Adjustment dialog."""
        dlg = StockAdjustmentDialog(item_id=101, stock_batch_id=1001)
        dlg.qty_edit.setText("+5")

        self.assertFalse(dlg._is_saving)
        self.assertTrue(dlg.save_btn.isEnabled())

        # Simulate clicking Save: flag set and button disabled
        dlg._is_saving = True
        dlg.save_btn.setEnabled(False)

        # Second click while saving is in progress does nothing
        dlg._on_save()
        self.assertTrue(dlg._is_saving)
        self.assertFalse(dlg.save_btn.isEnabled())

        dlg.close()

    def test_13_itemwise_ledger_movement_integration(self):
        """13. Stock adjustments appear in Itemwise Ledger and maintain mathematical consistency."""
        # Apply positive adjustment +20 to Batch 1001
        StockAdjustmentDAO.record_adjustment(
            item_id=101,
            stock_batch_id=1001,
            adjusted_qty=20.0,
            reason="Audit adjustment",
        )

        # Apply negative adjustment -5 to Batch 1001
        StockAdjustmentDAO.record_adjustment(
            item_id=101,
            stock_batch_id=1001,
            adjusted_qty=-5.0,
            reason="Sample distribution",
        )

        # Query itemwise ledger for 2026-01-01 to 2026-12-31
        ledger = LedgerReportDAO.get_item_ledger(
            item_id=101,
            from_date="2026-01-01",
            to_date="2026-12-31",
        )

        adj_rows = [r for r in ledger["rows"] if r["voucher_type"] == "Stock Adjustment"]
        self.assertEqual(len(adj_rows), 2)

        # Positive adjustment appears as inward
        inward_adj = next(r for r in adj_rows if r["inward_qty"] > 0)
        self.assertEqual(inward_adj["inward_qty"], 20.0)
        self.assertEqual(inward_adj["outward_qty"], 0.0)
        self.assertIn("Audit adjustment", inward_adj["particulars"])

        # Negative adjustment appears as outward
        outward_adj = next(r for r in adj_rows if r["outward_qty"] > 0)
        self.assertEqual(outward_adj["inward_qty"], 0.0)
        self.assertEqual(outward_adj["outward_qty"], 5.0)
        self.assertIn("Sample distribution", outward_adj["particulars"])

    def test_14_expiry_formatting_helper(self):
        """14. Expiry formatting helper formats MM-YYYY correctly."""
        self.assertEqual(_format_expiry_display("2026-12-31"), "12-2026")
        self.assertEqual(_format_expiry_display("2027-11"), "11-2027")
        self.assertEqual(_format_expiry_display("05/2028"), "05-2028")
        self.assertEqual(_format_expiry_display("12/26"), "12-2026")

    def test_15_changing_medicine_clears_stale_batch_fields(self):
        """15. Changing medicine refreshes batch list and clears stale batch fields."""
        dlg = StockAdjustmentDialog(item_id=101, stock_batch_id=1001)
        self.assertEqual(dlg.batch_combo.currentData(), 1001)
        self.assertEqual(dlg.batch_stock_edit.text(), "627")
        self.assertEqual(dlg.expiry_edit.text(), "11-2027")

        # Now change medicine to Item 102 (PARACETAMOL, has single batch 2001)
        dlg.item_combo.set_selected_id(102)

        # Batch 2001 should be auto-selected (single batch) and fields reflect Item 102
        self.assertEqual(dlg.batch_combo.currentData(), 2001)
        self.assertEqual(dlg.batch_stock_edit.text(), "100")
        self.assertEqual(dlg.expiry_edit.text(), "05-2028")
        self.assertEqual(dlg.mrp_edit.text(), "20.00")
        self.assertEqual(dlg.rate_edit.text(), "15.00")

        dlg.close()

    def test_16_medicine_with_no_batches_graceful_message(self):
        """16. Medicine with no batches displays graceful helpful message."""
        dlg = StockAdjustmentDialog(item_id=103)
        self.assertIn("No batches found for this medicine", dlg.batch_combo.currentText())
        self.assertIsNone(dlg.batch_combo.currentData())
        self.assertEqual(dlg.batch_stock_edit.text(), "")
        self.assertEqual(dlg.expiry_edit.text(), "")
        self.assertEqual(dlg.mrp_edit.text(), "")
        self.assertIn("no existing stock batches", dlg.projected_label.text())

        dlg.close()


if __name__ == "__main__":
    unittest.main()
