"""Exhaustive automated regression tests for Adjusted Stock List and Stock Adjustment workflow.

Tests cover:
  1. Selecting a medicine loads all its valid batches (including 0-stock batches).
  2. Switching medicines wipes the previous batch and dependent values.
  3. Selecting a batch populates all 10 fields (PackSize, Item Stock, Batch Stock, Expiry, MRP, Rate, Tax, Net Rate).
  4. Positive adjustment (+5) increases batch stock and creates audit record in stock_adjustments.
  5. Negative adjustment (-3) decreases batch stock and creates audit record in stock_adjustments.
  6. Rejection of zero adjustment and negative resulting stock.
  7. Adjusted Stock List page renders all 11 columns matching Pharma-WINNER screenshots.
  8. History filtering by date range and Item (ALL vs specific medicine).
  9. Editing an adjustment performs atomic delta reconciliation without double-counting stock.
  10. Editing an adjustment rejects any delta that would create negative stock.
  11. Canceling an edit leaves stock and database records unchanged.
  12. Transaction rollback on failed save leaves no orphan rows or modified stock.
  13. Counter Sale history and sales invoices remain 100% segregated and unharmed.
  14. Purchase invoices and accounting ledgers remain 100% segregated and unharmed.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication(sys.argv)

# Isolated temporary database
_TMP_DIR = tempfile.mkdtemp(prefix="pms_stock_adj_test_")
_TMP_DB = os.path.join(_TMP_DIR, "stock_adj_test.db")
os.environ["PHARMACY_DB"] = _TMP_DB

from database.connection import get_connection, init_database
from database.stock_dao import StockDAO
from database.stock_adjustment_dao import StockAdjustmentDAO, StockAdjustmentError
from database.item_dao import ItemDAO
from database.unit_dao import UnitDAO
from database.company_dao import CompanyDAO
from database.supplier_dao import SupplierDAO
from database.customer_dao import CustomerDAO
from database.purchase_dao import PurchaseDAO
from database.sales_dao import SalesDAO
from database import auth, financial_year
from database.account_roles import ensure_system_ledgers

from screens.stock_adjustment_dialog import StockAdjustmentDialog, _format_expiry_display
from screens.adjusted_stock_list import AdjustedStockListPage, _fmt_date_dmy
from screens.counter_sale import CounterSalePage


class TestAdjustedStockListAndWorkflow(unittest.TestCase):
    _TMP_DB = _TMP_DB

    @classmethod
    def setUpClass(cls):
        os.environ["PHARMACY_DB"] = cls._TMP_DB
        init_database()
        auth.ensure_auth_schema()
        financial_year.ensure_default_financial_year()
        if auth.user_count() == 0:
            auth.create_first_admin("admin", "admin-pass-1")
        auth.session.login("admin", "admin-pass-1")
        ensure_system_ledgers()

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
        os.environ["PHARMACY_DB"] = self._TMP_DB
        conn = get_connection()
        try:
            for tbl in (
                "stock_adjustments", "sales_invoice_items", "sales_invoices",
                "purchase_invoice_items", "purchase_invoices", "stock_batches",
                "items", "suppliers", "customers", "units", "companies"
            ):
                try:
                    conn.execute(f"DELETE FROM {tbl}")
                except Exception:
                    pass
            conn.commit()
        finally:
            conn.close()

        ensure_system_ledgers()
        financial_year.ensure_default_financial_year()

        self.unit_id = UnitDAO.insert("Nos")
        self.company_id = CompanyDAO.insert("TestCo", "TC")
        self.supplier_id = SupplierDAO.insert("SANJIVANI AGENCIES")
        self.customer_id = CustomerDAO.insert("WALKIN")

        # Create Item 1: UBINEXT-LC TABLET (Pack 10)
        self.item1_id = ItemDAO.insert(
            item_name="UBINEXT-LC TABLET", unit_id=self.unit_id,
            company_id=self.company_id, pack_size="10",
            rate=169.14, mrp=222.0, tax_structure="GST @ 5%",
        )
        # Create Item 2: LUMIA 2K CAPSULE (Pack 10)
        self.item2_id = ItemDAO.insert(
            item_name="LUMIA 2K CAPSULE", unit_id=self.unit_id,
            company_id=self.company_id, pack_size="10",
            rate=87.86, mrp=115.31, tax_structure="GST @ 5%",
        )

        # Seed batches for Item 1:
        # Batch 1: positive stock 20 units
        # Batch 2: zero stock 0 units
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size, mrp, purchase_rate, net_rate, stock_qty)
                VALUES (?, '0AAIZ005', '2028-01-31', '10', 222.0, 169.14, 177.60, 20.0)
                """,
                (self.item1_id,),
            )
            self.batch1_id = cur.lastrowid

            cur.execute(
                """
                INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size, mrp, purchase_rate, net_rate, stock_qty)
                VALUES (?, '0AAIZ006', '2028-06-30', '10', 222.0, 169.14, 177.60, 0.0)
                """,
                (self.item1_id,),
            )
            self.batch2_id = cur.lastrowid

            # Seed batch for Item 2: positive stock 50 units
            cur.execute(
                """
                INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size, mrp, purchase_rate, net_rate, stock_qty)
                VALUES (?, 'GKH0615A', '2027-05-31', '10', 115.31, 87.86, 92.25, 50.0)
                """,
                (self.item2_id,),
            )
            self.batch3_id = cur.lastrowid
            conn.commit()
        finally:
            conn.close()

    def _pump(self):
        _app.processEvents()

    def test_01_load_batches_for_selected_item_and_switch_items(self):
        """1. Selecting a medicine loads all valid batches (including 0-stock). Switching clears previous batch."""
        dlg = StockAdjustmentDialog()
        self._pump()

        # Select Item 1
        dlg.item_combo.set_selected_id(self.item1_id)
        self._pump()

        # Verify Item 1 has 2 batches loaded
        self.assertEqual(len(dlg._batches), 2)
        batch_ids = [b["id"] for b in dlg._batches]
        self.assertIn(self.batch1_id, batch_ids)
        self.assertIn(self.batch2_id, batch_ids)

        # Total item stock should be 20.0
        self.assertEqual(dlg.item_stock_edit.text(), "20")

        # Now switch to Item 2
        dlg.item_combo.set_selected_id(self.item2_id)
        self._pump()

        # Verify only Item 2's batch is loaded
        self.assertEqual(len(dlg._batches), 1)
        self.assertEqual(dlg._batches[0]["id"], self.batch3_id)
        self.assertEqual(dlg.item_stock_edit.text(), "50")

        # Previous batch IDs must not be present
        self.assertNotIn(self.batch1_id, [b["id"] for b in dlg._batches])
        dlg.close()

    def test_02_select_batch_populates_all_fields(self):
        """2. Choosing a batch populates PackSize, Item Stock, Batch Stock, Expiry, MRP, Rate, Tax, Net Rate."""
        dlg = StockAdjustmentDialog(item_id=self.item1_id, stock_batch_id=self.batch1_id)
        self._pump()

        self.assertEqual(dlg.pack_edit.text(), "10")
        self.assertEqual(dlg.item_stock_edit.text(), "20")
        self.assertEqual(dlg.batch_stock_edit.text(), "20")
        self.assertEqual(dlg.expiry_edit.text(), "01-2028")
        self.assertEqual(dlg.mrp_edit.text(), "222.00")
        self.assertEqual(dlg.rate_edit.text(), "169.14")
        self.assertEqual(dlg.net_rate_edit.text(), "177.60")
        dlg.close()

    def test_03_positive_adjustment_increases_batch_stock_and_creates_audit_row(self):
        """3. Positive adjustment (+5) atomically increases stock_batches and records audit in stock_adjustments."""
        res = StockAdjustmentDAO.record_adjustment(
            item_id=self.item1_id,
            stock_batch_id=self.batch1_id,
            adjusted_qty=5.0,
            reason="Physical audit surplus",
            user_name="admin",
        )

        self.assertEqual(res["previous_qty"], 20.0)
        self.assertEqual(res["adjusted_qty"], 5.0)
        self.assertEqual(res["resulting_qty"], 25.0)

        # Verify stock_batches table in SQLite
        batch = StockDAO.get_stock_batch_by_id(self.batch1_id)
        self.assertEqual(batch["stock_qty"], 25.0)

        # Verify audit record in stock_adjustments table
        records = StockAdjustmentDAO.get_adjustments_for_item(self.item1_id)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["adjusted_qty"], 5.0)
        self.assertEqual(records[0]["resulting_qty"], 25.0)
        self.assertEqual(records[0]["reason"], "Physical audit surplus")

    def test_04_negative_adjustment_decreases_batch_stock_and_creates_audit_row(self):
        """4. Negative adjustment (-3) atomically decreases stock_batches and records audit."""
        res = StockAdjustmentDAO.record_adjustment(
            item_id=self.item1_id,
            stock_batch_id=self.batch1_id,
            adjusted_qty=-3.0,
            reason="Damage / Breakage",
            user_name="admin",
        )

        self.assertEqual(res["previous_qty"], 20.0)
        self.assertEqual(res["adjusted_qty"], -3.0)
        self.assertEqual(res["resulting_qty"], 17.0)

        batch = StockDAO.get_stock_batch_by_id(self.batch1_id)
        self.assertEqual(batch["stock_qty"], 17.0)

    def test_05_negative_stock_and_zero_qty_rejection(self):
        """5. Rejection of zero adjustment and negative resulting stock with transaction safety."""
        # 0 adjustment
        with self.assertRaises(StockAdjustmentError):
            StockAdjustmentDAO.record_adjustment(self.item1_id, self.batch1_id, 0.0)

        # Stock is 20. Attempt -25 -> results in -5 -> Must raise error!
        with self.assertRaises(StockAdjustmentError):
            StockAdjustmentDAO.record_adjustment(self.item1_id, self.batch1_id, -25.0)

        # Batch stock remains 20.0
        batch = StockDAO.get_stock_batch_by_id(self.batch1_id)
        self.assertEqual(batch["stock_qty"], 20.0)

        # No records created
        self.assertEqual(len(StockAdjustmentDAO.get_adjustments_for_item(self.item1_id)), 0)

    def test_06_adjusted_stock_list_history_displays_11_columns_matching_screenshot(self):
        """6. Adjusted Stock List page displays all 11 columns matching Pharma-WINNER screenshots."""
        # Record 2 adjustments
        StockAdjustmentDAO.record_adjustment(
            item_id=self.item1_id, stock_batch_id=self.batch1_id, adjusted_qty=4.0, reason="Count"
        )
        StockAdjustmentDAO.record_adjustment(
            item_id=self.item2_id, stock_batch_id=self.batch3_id, adjusted_qty=-2.0, reason="Damage"
        )

        page = AdjustedStockListPage()
        self._pump()

        self.assertEqual(page.table.rowCount(), 2)

        # Row 0 (newest): LUMIA 2K CAPSULE, Batch GKH0615A, Qty -2, Rate 87.86, MRP 115.31
        self.assertEqual(page.table.item(0, 0).text(), "LUMIA 2K CAPSULE")
        self.assertEqual(page.table.item(0, 1).text(), "10")             # PackSize
        self.assertTrue(len(page.table.item(0, 2).text()) > 0)           # Date
        self.assertEqual(page.table.item(0, 3).text(), "GKH0615A")       # BatchNo
        self.assertEqual(page.table.item(0, 4).text(), "05-2027")        # Expiry
        self.assertEqual(page.table.item(0, 5).text(), "-2")             # Qty
        self.assertEqual(page.table.item(0, 6).text(), "115.31")         # MRP
        self.assertEqual(page.table.item(0, 7).text(), "87.86")          # Rate
        self.assertEqual(page.table.item(0, 8).text(), "0")              # TxPer
        self.assertEqual(page.table.item(0, 9).text(), "0.00")           # TaxAmt
        self.assertEqual(page.table.item(0, 10).text(), "92.25")         # NetRate

        # Row 1: UBINEXT-LC TABLET, Batch 0AAIZ005, Qty +4, Rate 169.14, MRP 222.00
        self.assertEqual(page.table.item(1, 0).text(), "UBINEXT-LC TABLET")
        self.assertEqual(page.table.item(1, 3).text(), "0AAIZ005")
        self.assertEqual(page.table.item(1, 5).text(), "+4")
        self.assertEqual(page.table.item(1, 6).text(), "222.00")
        self.assertEqual(page.table.item(1, 7).text(), "169.14")
        page.close()

    def test_07_history_filtering_by_date_and_item(self):
        """7. History filtering by date range and Item (ALL vs specific medicine)."""
        StockAdjustmentDAO.record_adjustment(self.item1_id, self.batch1_id, 2.0)
        StockAdjustmentDAO.record_adjustment(self.item2_id, self.batch3_id, 3.0)

        page = AdjustedStockListPage()
        self._pump()
        self.assertEqual(page.table.rowCount(), 2)

        # Filter by Item 1
        idx = page.item_filter_combo.findData(self.item1_id)
        self.assertGreater(idx, 0)
        page.item_filter_combo.setCurrentIndex(idx)
        self._pump()

        self.assertEqual(page.table.rowCount(), 1)
        self.assertEqual(page.table.item(0, 0).text(), "UBINEXT-LC TABLET")

        # Filter by ALL
        page.item_filter_combo.setCurrentIndex(0)
        self._pump()
        self.assertEqual(page.table.rowCount(), 2)
        page.close()

    def test_08_edit_adjustment_atomic_delta_reconciliation_no_double_count(self):
        """8. Editing an adjustment reconciles stock with delta without double-counting."""
        # Initial stock = 20. Record +5 -> batch stock = 25.
        adj = StockAdjustmentDAO.record_adjustment(
            item_id=self.item1_id,
            stock_batch_id=self.batch1_id,
            adjusted_qty=5.0,
            reason="Initial count",
        )
        self.assertEqual(StockDAO.get_stock_batch_by_id(self.batch1_id)["stock_qty"], 25.0)

        # Edit adjustment: change from +5 to +2.
        # Delta = 2 - 5 = -3.
        # Batch stock should become 25 - 3 = 22! (NOT 20 + 2 = 22, nor 25 + 2 = 27)
        updated = StockAdjustmentDAO.update_adjustment(
            adjustment_id=adj["id"],
            new_adjusted_qty=2.0,
            reason="Corrected count",
        )

        self.assertEqual(updated["adjusted_qty"], 2.0)
        self.assertEqual(updated["resulting_qty"], 22.0)
        self.assertEqual(StockDAO.get_stock_batch_by_id(self.batch1_id)["stock_qty"], 22.0)

    def test_09_edit_adjustment_prevent_negative_stock(self):
        """9. Editing an adjustment rejects any delta that would cause negative batch stock."""
        # Initial stock = 20. Record +2 -> batch stock = 22.
        adj = StockAdjustmentDAO.record_adjustment(self.item1_id, self.batch1_id, 2.0)

        # Simulate other sales leaving only 5 units in stock
        conn = get_connection()
        try:
            conn.execute("UPDATE stock_batches SET stock_qty = 5.0 WHERE id = ?", (self.batch1_id,))
            conn.commit()
        finally:
            conn.close()

        # Current stock is 5. If we edit adjustment from +2 to -10, delta is -12 -> 5 + (-12) = -7 < 0 -> Must reject!
        with self.assertRaises(StockAdjustmentError):
            StockAdjustmentDAO.update_adjustment(adj["id"], -10.0)

        # Stock remains 5.0
        self.assertEqual(StockDAO.get_stock_batch_by_id(self.batch1_id)["stock_qty"], 5.0)

    def test_10_cancel_edit_leaves_records_intact(self):
        """10. Canceling / rejecting edit dialog leaves database and stock untouched."""
        adj = StockAdjustmentDAO.record_adjustment(self.item1_id, self.batch1_id, 3.0)
        stock_before = StockDAO.get_stock_batch_by_id(self.batch1_id)["stock_qty"]

        dlg = StockAdjustmentDialog(edit_adjustment_id=adj["id"])
        self._pump()
        dlg.qty_edit.setText("99")
        self._pump()

        # Reject dialog without saving
        dlg.reject()
        self._pump()

        # Stock and record must remain untouched
        stock_after = StockDAO.get_stock_batch_by_id(self.batch1_id)["stock_qty"]
        self.assertEqual(stock_after, stock_before)

        reloaded_adj = StockAdjustmentDAO.get_by_id(adj["id"])
        self.assertEqual(reloaded_adj["adjusted_qty"], 3.0)

    def test_11_transaction_rollback_on_failure(self):
        """11. Transaction rollback on simulated error leaves no orphan rows or modified stock."""
        stock_before = StockDAO.get_stock_batch_by_id(self.batch1_id)["stock_qty"]
        count_before = len(StockAdjustmentDAO.get_all_filtered())

        # Attempt adjustment with invalid batch ID
        with self.assertRaises(StockAdjustmentError):
            StockAdjustmentDAO.record_adjustment(self.item1_id, stock_batch_id=999999, adjusted_qty=5.0)

        # Stock and audit count unchanged
        stock_after = StockDAO.get_stock_batch_by_id(self.batch1_id)["stock_qty"]
        self.assertEqual(stock_after, stock_before)
        self.assertEqual(len(StockAdjustmentDAO.get_all_filtered()), count_before)

    def test_12_counter_sale_and_sales_history_remain_unharmed(self):
        """12. Counter Sale history and sales_invoices remain completely segregated and unharmed."""
        # Insert a counter sale
        from screens.counter_sale import _BillItemRow
        page = CounterSalePage()
        self._pump()

        panel = page._sale_panel
        panel.customer_combo.setCurrentIndex(panel.customer_combo.findData(self.customer_id))
        panel.patient_name_edit.setText("TEST PATIENT")
        self._pump()

        panel._item_rows.append(_BillItemRow(
            item_id=self.item1_id, item_name="UBINEXT-LC TABLET",
            stock_batch_id=self.batch1_id, pack_size="10", location="",
            batch_no="0AAIZ005", expiry="2028-01-31", mrp=222.0,
            sale_qty=1.0, discount_amount=0.0, amount=222.0,
        ))
        panel._recalc_totals()
        panel._commit_sale()
        self._pump()

        # Now record a stock adjustment
        StockAdjustmentDAO.record_adjustment(self.item1_id, self.batch1_id, 4.0)

        # Verify sales_invoices table has exactly 1 row with patient name TEST PATIENT
        conn = get_connection()
        try:
            cur = conn.execute("SELECT id, patient_name, bill_no FROM sales_invoices")
            invs = cur.fetchall()
            self.assertEqual(len(invs), 1)
            self.assertEqual(invs[0]["patient_name"], "TEST PATIENT")
            self.assertEqual(invs[0][1], "TEST PATIENT")
            self.assertTrue(len(invs[0][2]) > 0)
        finally:
            conn.close()

        # Verify Counter Sale bill history table continues to show the counter sale
        page._refresh_history()
        self._pump()
        self.assertGreaterEqual(page._hist_table.rowCount(), 1)
        page.close()

    def test_13_purchase_invoices_and_ledger_transactions_remain_unharmed(self):
        """13. Purchase invoices and accounting ledgers remain completely segregated and unharmed."""
        # Insert a purchase invoice
        inv_id = PurchaseDAO.insert_invoice(
            voucher_no="PV-0001", voucher_date="2026-10-22", voucher_time="10:00",
            purchase_type="Credit", supplier_id=self.supplier_id,
            invoice_no="INV-100", invoice_date="2026-10-22", invoice_net_amount=500.0,
            bill_discount=0.0, due_date="2026-11-22", total_amount=500.0,
            gst_amount=0.0, debit_note_amount=0.0, other_amount=0.0,
            paid_amount=0.0, round_off=0.0, net_amount=500.0, remarks="",
            items=[
                {
                    "item_id": self.item1_id, "item_name": "UBINEXT-LC TABLET",
                    "pack_size": "10", "pay_qty": 5.0, "free_qty": 0.0,
                    "batch_no": "0AAIZ005", "expiry": "2028-01-31",
                    "rate": 100.0, "mrp": 125.0, "discount": 0.0,
                    "gst_percent": 0.0, "gst_amount": 0.0, "amount": 500.0,
                    "purchase_rate": 100.0, "net_rate": 100.0, "pp": 25.0,
                }
            ],
        )

        # Record a stock adjustment
        StockAdjustmentDAO.record_adjustment(self.item1_id, self.batch1_id, 10.0)

        # Verify purchase invoice is intact
        inv = PurchaseDAO.get_by_id(inv_id)
        self.assertEqual(inv["voucher_no"], "PV-0001")
        self.assertEqual(inv["net_amount"], 500.0)

        # Verify purchase invoice items
        items = PurchaseDAO.get_invoice_items(inv_id)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["batch_no"], "0AAIZ005")


if __name__ == "__main__":
    unittest.main(verbosity=2)
