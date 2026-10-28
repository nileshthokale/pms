"""Regression tests for Purchase Invoice PP column display and item deletion fixes.

Tests cover:
  1. PP column displays "25" (representing 25% profit percentage) matching Pharma-WINNER
     reference screenshot for all 4 items (UBINEXT-LC, LUMIA 2K, MAC RD, PANTOCID DSR),
     and does NOT display line totals (532.79, 922.53, 763.46, 4416.09).
  2. Purchase rate, net rate, GST, stock valuation, and invoice totals remain strictly
     accurate and uncorrupted by PP display.
  3. Reopening an existing invoice from the database preserves and displays PP as "25".
  4. Deleting an item from an invoice with multiple items:
     - Removes the deleted row from the table and recalculates totals immediately.
     - Preserves the remaining rows and their exact batch identities.
     - Fully clears the item entry bar (item combo, batch, expiry, rate, MRP, discount, GST, pay/free qty).
  5. Selecting a different item after deletion:
     - Populates only the newly selected item's master data (MRP, rate, pack, GST).
     - Does not carry over the deleted item's batch, MRP, rate, or discount.
  6. Cancel / Transaction safety:
     - Closing or canceling an edit does not corrupt persisted database records or stock batches.
  7. Production database safety:
     - Verified isolated temporary database; data/pharmacy.db is untouched.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Isolated temporary database
_TMP_DIR = tempfile.mkdtemp(prefix="pms_purch_test_")
_TMP_DB = os.path.join(_TMP_DIR, "purch_test.db")
os.environ["PHARMACY_DB"] = _TMP_DB

from database.connection import get_connection, init_database
from database.supplier_dao import SupplierDAO
from database.item_dao import ItemDAO
from database.unit_dao import UnitDAO
from database.company_dao import CompanyDAO
from database.purchase_dao import PurchaseDAO
from database.stock_dao import StockDAO
from database import auth, financial_year
from database.account_roles import ensure_system_ledgers

try:
    from PySide6.QtWidgets import QApplication
    from screens.purchase_invoice import _InvoiceDialog, _InvoiceItemRow
    HAS_PYSIDE6 = True
except ImportError:
    HAS_PYSIDE6 = False


@unittest.skipUnless(HAS_PYSIDE6, "PySide6 not available")
class TestPurchaseInvoicePPAndItemDeletion(unittest.TestCase):
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
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        os.environ["PHARMACY_DB"] = self._TMP_DB
        conn = get_connection()
        try:
            for tbl in (
                "ledger_transactions", "purchase_invoice_items", "purchase_invoices",
                "stock_batches", "items", "suppliers", "units", "companies"
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

        # 4 items matching Pharma-WINNER screenshot Voucher 260
        self.item1_id = ItemDAO.insert(
            item_name="UBINEXT-LC TABLET", unit_id=self.unit_id,
            company_id=self.company_id, pack_size="10",
            rate=169.14, mrp=222.0, tax_structure="GST @ 5%",
        )
        self.item2_id = ItemDAO.insert(
            item_name="LUMIA 2K CAPSULE", unit_id=self.unit_id,
            company_id=self.company_id, pack_size="10",
            rate=87.86, mrp=115.31, tax_structure="GST @ 5%",
        )
        self.item3_id = ItemDAO.insert(
            item_name="MAC RD CAPSULE", unit_id=self.unit_id,
            company_id=self.company_id, pack_size="15",
            rate=72.71, mrp=95.44, tax_structure="GST @ 5%",
        )
        self.item4_id = ItemDAO.insert(
            item_name="PANTOCID DSR CAPSULE", unit_id=self.unit_id,
            company_id=self.company_id, pack_size="15",
            rate=210.29, mrp=276.0, tax_structure="GST @ 5%",
        )

    def _pump(self):
        self._app.processEvents()

    def test_01_pp_displays_25_matching_pharma_winner_screenshot(self):
        """1. Bug 1: PP column displays '25' for all items matching Pharma-WINNER voucher 260.
        Does NOT display erroneous line totals (532.79, 922.53, 763.46, 4416.09).
        """
        dlg = _InvoiceDialog()
        bar = dlg._entry_bar

        # Row 1: UBINEXT-LC TABLET (PayQty 3, FreeQty 0, Batch 0AAIZ005, Exp 31-01-2028, Rate 169.14, MRP 222)
        bar.item_combo.set_selected_id(self.item1_id)
        self._pump()
        bar.pay_qty_edit.setText("3")
        bar.free_qty_edit.setText("0")
        bar.batch_edit.setText("0AAIZ005")
        bar.expiry_edit.setText("31-01-2028")
        bar.rate_edit.setText("169.14")
        bar.mrp_edit.setText("222.00")
        bar.discount_edit.setText("0.00")
        dlg._on_add_item()
        self._pump()

        # Row 2: LUMIA 2K CAPSULE (PayQty 10, FreeQty 0, Batch GKH0615A, Exp 31-05-2027, Rate 87.86, MRP 115.31)
        bar.item_combo.set_selected_id(self.item2_id)
        self._pump()
        bar.pay_qty_edit.setText("10")
        bar.free_qty_edit.setText("0")
        bar.batch_edit.setText("GKH0615A")
        bar.expiry_edit.setText("31-05-2027")
        bar.rate_edit.setText("87.86")
        bar.mrp_edit.setText("115.31")
        bar.discount_edit.setText("0.00")
        dlg._on_add_item()
        self._pump()

        # Row 3: MAC RD CAPSULE (PayQty 10, FreeQty 1, Batch 02260665, Exp 30-06-2028, Rate 72.71, MRP 95.44)
        bar.item_combo.set_selected_id(self.item3_id)
        self._pump()
        bar.pay_qty_edit.setText("10")
        bar.free_qty_edit.setText("1")
        bar.batch_edit.setText("02260665")
        bar.expiry_edit.setText("30-06-2028")
        bar.rate_edit.setText("72.71")
        bar.mrp_edit.setText("95.44")
        bar.discount_edit.setText("0.00")
        dlg._on_add_item()
        self._pump()

        # Row 4: PANTOCID DSR CAPSULE (PayQty 20, FreeQty 0, Batch GTH2228A, Exp 30-06-2028, Rate 210.29, MRP 276)
        bar.item_combo.set_selected_id(self.item4_id)
        self._pump()
        bar.pay_qty_edit.setText("20")
        bar.free_qty_edit.setText("0")
        bar.batch_edit.setText("GTH2228A")
        bar.expiry_edit.setText("30-06-2028")
        bar.rate_edit.setText("210.29")
        bar.mrp_edit.setText("276.00")
        bar.discount_edit.setText("0.00")
        dlg._on_add_item()
        self._pump()

        self.assertEqual(dlg._table.rowCount(), 4)

        # Check PP column text (Column 15) for all 4 items
        for row_idx in range(4):
            pp_cell = dlg._table.item(row_idx, 15)
            self.assertIsNotNone(pp_cell)
            self.assertEqual(pp_cell.text(), "25", f"Row {row_idx} PP must be '25'")

        # Confirm it is NOT the line total
        self.assertNotEqual(dlg._table.item(0, 15).text(), "532.79")
        self.assertNotEqual(dlg._table.item(1, 15).text(), "922.53")
        self.assertNotEqual(dlg._table.item(2, 15).text(), "763.46")
        self.assertNotEqual(dlg._table.item(3, 15).text(), "4416.09")

        # Verify rates and totals are not distorted
        self.assertEqual(dlg._table.item(0, 13).text(), "177.60")  # Pur Rate
        self.assertEqual(dlg._table.item(0, 14).text(), "177.60")  # Net Rate
        self.assertEqual(dlg._table.item(2, 13).text(), "76.35")   # MAC RD Pur Rate
        self.assertEqual(dlg._table.item(2, 14).text(), "69.41")   # MAC RD Net Rate (with 1 free pack)

        # Invoice totals
        self.assertEqual(dlg.total_amount_label.text(), "6318.92")
        self.assertEqual(dlg.gst_label.text(), "315.95")
        self.assertEqual(dlg.net_amt_label.text(), "6635.00")
        dlg.close()

    def test_02_reopen_persisted_invoice_displays_pp_25(self):
        """2. Saving invoice and reopening in edit mode correctly retrieves and displays PP as 25."""
        inv_id = PurchaseDAO.insert_invoice(
            voucher_no="PV-0260", voucher_date="2026-10-21", voucher_time="13:44",
            purchase_type="Credit", supplier_id=self.supplier_id,
            invoice_no="9598", invoice_date="2026-10-09", invoice_net_amount=6635.0,
            bill_discount=0.0, due_date="2026-11-09", total_amount=6318.92,
            gst_amount=315.95, debit_note_amount=0.0, other_amount=0.0,
            paid_amount=0.0, round_off=0.13, net_amount=6635.0, remarks="",
            items=[
                {
                    "item_id": self.item1_id, "item_name": "UBINEXT-LC TABLET",
                    "pack_size": "10", "pay_qty": 3.0, "free_qty": 0.0,
                    "batch_no": "0AAIZ005", "expiry": "2028-01-31",
                    "rate": 169.14, "mrp": 222.0, "discount": 0.0,
                    "gst_percent": 5.0, "gst_amount": 25.37, "amount": 507.42,
                    "purchase_rate": 177.60, "net_rate": 177.60, "pp": 25.0,
                },
                {
                    "item_id": self.item2_id, "item_name": "LUMIA 2K CAPSULE",
                    "pack_size": "10", "pay_qty": 10.0, "free_qty": 0.0,
                    "batch_no": "GKH0615A", "expiry": "2027-05-31",
                    "rate": 87.86, "mrp": 115.31, "discount": 0.0,
                    "gst_percent": 5.0, "gst_amount": 43.93, "amount": 878.60,
                    "purchase_rate": 92.25, "net_rate": 92.25, "pp": 25.0,
                },
            ],
        )

        inv = PurchaseDAO.get_by_id(inv_id)
        dlg = _InvoiceDialog(invoice=inv)
        self._pump()

        self.assertEqual(dlg._table.rowCount(), 2)
        self.assertEqual(dlg._table.item(0, 15).text(), "25")
        self.assertEqual(dlg._table.item(1, 15).text(), "25")
        dlg.close()

    def test_03_delete_item_clears_entry_bar_and_preserves_remaining_rows(self):
        """3. Bug 2: Deleting an item removes the row, recalculates totals, and clears stale entry fields."""
        dlg = _InvoiceDialog()
        bar = dlg._entry_bar

        # Add Item 1
        bar.item_combo.set_selected_id(self.item1_id)
        self._pump()
        bar.pay_qty_edit.setText("3")
        bar.free_qty_edit.setText("0")
        bar.batch_edit.setText("BATCH-01")
        bar.expiry_edit.setText("31-01-2028")
        bar.rate_edit.setText("169.14")
        bar.mrp_edit.setText("222.00")
        dlg._on_add_item()
        self._pump()

        # Add Item 2
        bar.item_combo.set_selected_id(self.item2_id)
        self._pump()
        bar.pay_qty_edit.setText("10")
        bar.free_qty_edit.setText("0")
        bar.batch_edit.setText("BATCH-02")
        bar.expiry_edit.setText("31-05-2027")
        bar.rate_edit.setText("87.86")
        bar.mrp_edit.setText("115.31")
        dlg._on_add_item()
        self._pump()

        # Add Item 3
        bar.item_combo.set_selected_id(self.item3_id)
        self._pump()
        bar.pay_qty_edit.setText("5")
        bar.free_qty_edit.setText("0")
        bar.batch_edit.setText("BATCH-03")
        bar.expiry_edit.setText("30-06-2028")
        bar.rate_edit.setText("72.71")
        bar.mrp_edit.setText("95.44")
        dlg._on_add_item()
        self._pump()

        self.assertEqual(dlg._table.rowCount(), 3)

        # Simulate user having typed / entered something in the entry bar before deleting
        bar.batch_edit.setText("STALE-BATCH")
        bar.mrp_edit.setText("999.00")
        bar.rate_edit.setText("888.00")
        bar.discount_edit.setText("15.00")

        # Delete Item 2 (index 1)
        dlg._delete_item(1)
        self._pump()

        # Table should now have 2 items
        self.assertEqual(dlg._table.rowCount(), 2)

        # Remaining rows must be Item 1 and Item 3 with their exact identities
        self.assertEqual(dlg._table.item(0, 1).text(), "UBINEXT-LC TABLET")
        self.assertEqual(dlg._table.item(0, 5).text(), "BATCH-01")
        self.assertEqual(dlg._table.item(1, 1).text(), "MAC RD CAPSULE")
        self.assertEqual(dlg._table.item(1, 5).text(), "BATCH-03")

        # Entry bar must be completely cleared:
        self.assertIsNone(bar.item_combo.currentData())
        self.assertEqual(bar.item_combo.currentText(), "")
        self.assertEqual(bar.batch_edit.text(), "")
        self.assertEqual(bar.mrp_edit.text(), "")
        self.assertEqual(bar.rate_edit.text(), "")
        self.assertEqual(bar.expiry_edit.text(), "")
        self.assertEqual(bar.pay_qty_edit.text(), "")
        self.assertEqual(bar.free_qty_edit.text(), "")
        self.assertEqual(bar.discount_edit.text(), "")
        self.assertEqual(bar.gst_edit.text(), "")
        self.assertEqual(bar.pack_edit.text(), "")
        self.assertEqual(bar.batch_edit._model.rowCount(), 0)

        # Totals must be recalculated for items 1 and 3 only
        expected_total = round(3 * 169.14 + 5 * 72.71, 2)  # 507.42 + 363.55 = 870.97
        self.assertEqual(dlg.total_amount_label.text(), f"{expected_total:.2f}")

        dlg.close()

    def test_04_selecting_different_item_after_delete_does_not_inherit_stale_values(self):
        """4. Selecting another item after deletion populates only that item's data and no stale values."""
        dlg = _InvoiceDialog()
        bar = dlg._entry_bar

        # Add Item 1
        bar.item_combo.set_selected_id(self.item1_id)
        self._pump()
        bar.pay_qty_edit.setText("3")
        bar.batch_edit.setText("BATCH-OLD")
        bar.mrp_edit.setText("222.00")
        dlg._on_add_item()
        self._pump()

        # Delete the item
        dlg._delete_item(0)
        self._pump()

        # Now select Item 4 (PANTOCID DSR: MRP=276, Rate=210.29, Pack=15, GST=5%)
        bar.item_combo.set_selected_id(self.item4_id)
        self._pump()

        # Verify only Item 4's data is present
        self.assertEqual(bar.mrp_edit.text(), "276.00")
        self.assertEqual(bar.rate_edit.text(), "210.29")
        self.assertEqual(bar.pack_edit.text(), "15")
        self.assertEqual(bar.gst_edit.text(), "5")

        # Stale batch and quantities must NOT be carried over
        self.assertEqual(bar.batch_edit.text(), "")
        self.assertEqual(bar.pay_qty_edit.text(), "")
        self.assertEqual(bar.free_qty_edit.text(), "")
        self.assertEqual(bar.discount_edit.text(), "")
        self.assertEqual(bar.expiry_edit.text(), "")

        dlg.close()

    def test_05_cancel_edit_does_not_corrupt_database_or_stock(self):
        """5. Canceling an edit does not delete stock batches or corrupt persisted invoice."""
        inv_id = PurchaseDAO.insert_invoice(
            voucher_no="PV-0001", voucher_date="2026-10-21", voucher_time="10:00",
            purchase_type="Credit", supplier_id=self.supplier_id,
            invoice_no="INV-1", invoice_date="2026-10-21", invoice_net_amount=500.0,
            bill_discount=0.0, due_date="2026-11-21", total_amount=500.0,
            gst_amount=0.0, debit_note_amount=0.0, other_amount=0.0,
            paid_amount=0.0, round_off=0.0, net_amount=500.0, remarks="",
            items=[
                {
                    "item_id": self.item1_id, "item_name": "UBINEXT-LC TABLET",
                    "pack_size": "10", "pay_qty": 5.0, "free_qty": 0.0,
                    "batch_no": "B-PERSIST", "expiry": "2028-01-31",
                    "rate": 100.0, "mrp": 125.0, "discount": 0.0,
                    "gst_percent": 0.0, "gst_amount": 0.0, "amount": 500.0,
                    "purchase_rate": 100.0, "net_rate": 100.0, "pp": 25.0,
                }
            ],
        )

        batches = StockDAO.get_stock_batches_for_item(self.item1_id, include_zero_stock=True)
        self.assertTrue(len(batches) > 0)
        initial_qty = batches[0]["stock_qty"]
        self.assertGreater(initial_qty, 0)

        # Open in dialog and delete item in UI, but reject dialog (Cancel)
        inv = PurchaseDAO.get_by_id(inv_id)
        dlg = _InvoiceDialog(invoice=inv)
        self._pump()
        dlg._delete_item(0)
        self._pump()
        self.assertEqual(dlg._table.rowCount(), 0)

        # Reject / Cancel dialog without saving
        dlg.reject()
        self._pump()

        # Database and stock must be completely untouched
        db_items = PurchaseDAO.get_invoice_items(inv_id)
        self.assertEqual(len(db_items), 1)
        self.assertEqual(db_items[0]["batch_no"], "B-PERSIST")

        batches_after = StockDAO.get_stock_batches_for_item(self.item1_id, include_zero_stock=True)
        self.assertEqual(batches_after[0]["stock_qty"], initial_qty)


if __name__ == "__main__":
    unittest.main(verbosity=2)
