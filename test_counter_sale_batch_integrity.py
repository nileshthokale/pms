"""Regression test suite for Counter Sale batch integrity and selection.

Covers:
1. Items with alphabetic, numeric-only, and mixed-format batch numbers.
2. Items with one batch and multiple batches.
3. Item selection without a batch selection (Batch field remains empty).
4. Switching items after choosing a batch (invalidates previous batch and clears stale values).
5. Adding several items with different batch numbers.
6. Editing and restoring a line's batch details (via double-click or edit_row).
7. Preventing internal batch IDs from being shown as batch numbers.
8. Ensuring batch expiry, MRP, and available stock belong to the selected batch.
9. Preventing batch-to-item mismatches.
10. Ensuring no existing historical transaction is modified.
11. Ensuring title bar preserves [STAGING / AUDIT MODE] across screen actions.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QTableWidgetItem

from database.connection import get_connection, init_database
from database.sales_dao import SalesDAO
from database.item_dao import ItemDAO
from database.customer_dao import CustomerDAO
from database.doctor_dao import DoctorDAO
from database.company_dao import CompanyDAO
from database.unit_dao import UnitDAO
from database.drug_dao import DrugDAO
from database.supplier_dao import SupplierDAO
from database.purchase_dao import PurchaseDAO
from database.stock_dao import StockDAO
from database.hold_bill_dao import ensure_hold_tables
from database.account_roles import ensure_system_ledgers
from database import auth, financial_year
from screens.counter_sale import CounterSalePage, _ItemEntryBar, _BillItemRow
from ui.main_window import _get_window_title

_TEST_DB = os.path.join(tempfile.gettempdir(), "test_counter_sale_batch_integrity.db")
_TABLES = [
    "ledger_transactions", "account_ledgers",
    "customer_receipts", "supplier_payments",
    "debit_note_items", "debit_notes",
    "credit_note_items", "credit_notes",
    "sales_invoice_items", "sales_invoices",
    "purchase_invoice_items", "purchase_invoices",
    "hold_bill_items", "hold_bills",
    "stock_batches", "item_ingredients", "items",
    "doctors", "customers", "suppliers", "drugs", "units", "companies",
]


class TestCounterSaleBatchIntegrity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.path.exists(_TEST_DB):
            try:
                os.remove(_TEST_DB)
            except Exception:
                pass
        os.environ["PHARMACY_DB"] = _TEST_DB
        init_database()
        ensure_hold_tables()
        auth.ensure_auth_schema()
        financial_year.ensure_default_financial_year()
        if auth.user_count() == 0:
            auth.create_first_admin("admin", "admin-pass-1")
        auth.session.login("admin", "admin-pass-1")
        cls.app = QApplication.instance() or QApplication([])

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("PHARMACY_DB", None)
        if os.path.exists(_TEST_DB):
            try:
                os.remove(_TEST_DB)
            except Exception:
                pass

    def setUp(self):
        self._msg = mock.patch.multiple(
            QMessageBox,
            warning=mock.DEFAULT,
            information=mock.DEFAULT,
            critical=mock.DEFAULT,
            question=mock.MagicMock(return_value=QMessageBox.Yes),
        )
        self._msg.start()
        self.addCleanup(self._msg.stop)

        conn = get_connection()
        try:
            for tbl in _TABLES:
                try:
                    conn.execute(f"DELETE FROM {tbl}")
                except Exception:
                    pass
            conn.commit()
        finally:
            conn.close()

        ensure_system_ledgers()
        self.unit_id = UnitDAO.insert("Tab")
        self.company_id = CompanyDAO.insert("TestPharma", "TP")
        self.supplier_id = SupplierDAO.insert("Supplier1")
        self.customer_id = CustomerDAO.insert("Customer1")
        self.customer_walkin_id = CustomerDAO.insert("Walkin Customer")
        self.doctor_id = DoctorDAO.insert("Dr. Patel")

        # Create Items
        # 1. Numeric batch item (e.g. STASHPAIN with batch "133")
        self.item_stashpain = ItemDAO.insert(
            item_name="STASHPain", unit_id=self.unit_id,
            company_id=self.company_id, pack_size="1", mrp=126.0
        )
        # 2. Single batch item (e.g. TENDOMAC with batch "MML/26/006")
        self.item_tendomac = ItemDAO.insert(
            item_name="TENDOMAC", unit_id=self.unit_id,
            company_id=self.company_id, pack_size="15", mrp=462.0
        )
        # 3. Multi-batch item (e.g. LUMIA 2K with batches "GKG2007A" and "GKH0615A")
        self.item_lumia = ItemDAO.insert(
            item_name="LUMIA 2K", unit_id=self.unit_id,
            company_id=self.company_id, pack_size="10", mrp=115.31
        )
        # 4. Item with purely alphabetic batch
        self.item_alpha = ItemDAO.insert(
            item_name="ALPHA MED", unit_id=self.unit_id,
            company_id=self.company_id, pack_size="10", mrp=80.0
        )
        # 5. Item with zero stock / expired batch
        self.item_nostock = ItemDAO.insert(
            item_name="NO STOCK MED", unit_id=self.unit_id,
            company_id=self.company_id, pack_size="10", mrp=50.0
        )

        self._seed_stock_data()

    def _seed_stock_data(self):
        conn = get_connection()
        try:
            # Batch 1 for STASHPain: numeric batch "133", stored stock 13
            conn.execute(
                """
                INSERT INTO stock_batches (id, item_id, batch_no, expiry, pack_size, mrp, purchase_rate, net_rate, stock_qty)
                VALUES (7059, ?, '133', '2027-09-30', '1', 126.0, 96.0, 84.0, 13.0)
                """,
                (self.item_stashpain,)
            )
            # Batch 2 for STASHPain: numeric batch "110", stored stock 8
            conn.execute(
                """
                INSERT INTO stock_batches (id, item_id, batch_no, expiry, pack_size, mrp, purchase_rate, net_rate, stock_qty)
                VALUES (6988, ?, '110', '2027-09-30', '1', 126.0, 96.0, 84.0, 8.0)
                """,
                (self.item_stashpain,)
            )

            # Exactly ONE batch for TENDOMAC: "MML/26/006", stored stock 18
            conn.execute(
                """
                INSERT INTO stock_batches (id, item_id, batch_no, expiry, pack_size, mrp, purchase_rate, net_rate, stock_qty)
                VALUES (7094, ?, 'MML/26/006', '2028-04-30', '15', 462.0, 352.0, 369.6, 18.0)
                """,
                (self.item_tendomac,)
            )

            # Two batches for LUMIA 2K: differing MRPs and expiries
            conn.execute(
                """
                INSERT INTO stock_batches (id, item_id, batch_no, expiry, pack_size, mrp, purchase_rate, net_rate, stock_qty)
                VALUES (6932, ?, 'GKG2007A', '2027-02-28', '10', 123.0, 85.0, 90.0, 13.0)
                """,
                (self.item_lumia,)
            )
            conn.execute(
                """
                INSERT INTO stock_batches (id, item_id, batch_no, expiry, pack_size, mrp, purchase_rate, net_rate, stock_qty)
                VALUES (7023, ?, 'GKH0615A', '2027-05-31', '10', 115.31, 87.86, 92.25, 28.0)
                """,
                (self.item_lumia,)
            )

            # Purely alphabetic batch for ALPHA MED
            conn.execute(
                """
                INSERT INTO stock_batches (id, item_id, batch_no, expiry, pack_size, mrp, purchase_rate, net_rate, stock_qty)
                VALUES (8001, ?, 'ALPHABATCH', '2027-12-31', '10', 80.0, 50.0, 55.0, 20.0)
                """,
                (self.item_alpha,)
            )

            # Expired batch and zero-stock batch for NO STOCK MED
            conn.execute(
                """
                INSERT INTO stock_batches (id, item_id, batch_no, expiry, pack_size, mrp, purchase_rate, net_rate, stock_qty)
                VALUES (9001, ?, 'EXPIRED', '2020-01-01', '10', 50.0, 30.0, 35.0, 50.0)
                """,
                (self.item_nostock,)
            )
            conn.execute(
                """
                INSERT INTO stock_batches (id, item_id, batch_no, expiry, pack_size, mrp, purchase_rate, net_rate, stock_qty)
                VALUES (9002, ?, 'ZEROSTOCK', '2028-01-01', '10', 50.0, 30.0, 35.0, 0.0)
                """,
                (self.item_nostock,)
            )
            conn.commit()
        finally:
            conn.close()

    def test_01_numeric_alphabetic_mixed_batches_and_no_internal_id_leak(self):
        """Verifies that numeric batch '133' is displayed as '133', not its internal ID 7059."""
        page = CounterSalePage()
        page.show()
        self.app.processEvents()
        self.addCleanup(lambda: (page.hide(), page.deleteLater()))

        bar = page._sale_panel._entry_bar

        # Select STASHPain
        bar.item_combo.setCurrentIndex(bar.item_combo.findData(self.item_stashpain))
        self.app.processEvents()

        # Check batch combo contents
        texts = [bar.batch_combo.itemText(i) for i in range(bar.batch_combo.count())]
        self.assertEqual(len(texts), 2)
        # Ensure '133' is in the text, and internal ID 7059 is NOT shown as batch number
        batch_133_text = next(t for t in texts if t.startswith("133 |"))
        self.assertIn("Exp: 2027-09-30", batch_133_text)
        self.assertIn("MRP: 126.00", batch_133_text)
        self.assertIn("Avail: 13", batch_133_text)
        self.assertNotIn("7059 |", batch_133_text)

        # Select batch 133 explicitly
        bar.batch_combo.setCurrentIndex(bar.batch_combo.findData(7059))
        self.app.processEvents()

        self.assertEqual(bar.mrp_edit.text(), "126.00")
        self.assertEqual(bar.expiry_edit.text(), "2027-09-30")
        self.assertEqual(bar.stock_edit.text(), "13")

        # Add to bill
        bar.qty_edit.setText("2")
        bar.add_btn.click()
        self.app.processEvents()

        # Check table row
        self.assertEqual(page._sale_panel._table.rowCount(), 1)
        row = page._sale_panel._item_rows[0]
        self.assertEqual(row.batch_no, "133")
        self.assertEqual(row.stock_batch_id, 7059)
        self.assertEqual(page._sale_panel._table.item(0, 4).text(), "133")

    def test_02_single_batch_item_opens_popup_and_allows_explicit_selection(self):
        """Item with exactly 1 batch (TENDOMAC) must show popup on focus, keep batch empty initially, and allow explicit selection."""
        page = CounterSalePage()
        page.show()
        self.app.processEvents()
        self.addCleanup(lambda: (page.hide(), page.deleteLater()))

        bar = page._sale_panel._entry_bar

        # Select TENDOMAC (has exactly 1 batch: MML/26/006)
        bar.item_combo.setCurrentIndex(bar.item_combo.findData(self.item_tendomac))
        self.app.processEvents()

        # Exactly 1 batch loaded
        self.assertEqual(bar.batch_combo.count(), 1)
        # Batch field must remain empty until user explicitly selects
        self.assertEqual(bar.batch_combo.currentIndex(), -1)
        self.assertEqual(bar.batch_combo.lineEdit().text(), "")
        self.assertEqual(bar.batch_combo.lineEdit().placeholderText(), "Select batch")
        self.assertIsNone(bar.get_current_data())

        # Calling _focus_batch MUST show completion popup even when count == 1
        bar._focus_batch()
        self.app.processEvents()
        self.assertTrue(bar.batch_combo.completer().popup().isVisible())

        # Select the batch explicitly
        idx = bar.batch_combo.findData(7094)
        bar.batch_combo.setCurrentIndex(idx)
        self.app.processEvents()

        self.assertEqual(bar.mrp_edit.text(), "462.00")
        self.assertEqual(bar.expiry_edit.text(), "2028-04-30")
        self.assertEqual(bar.stock_edit.text(), "18")
        self.assertEqual(bar.pack_edit.text(), "15")

        # Add to bill
        bar.qty_edit.setText("1")
        bar.add_btn.click()
        self.app.processEvents()

        self.assertEqual(page._sale_panel._table.rowCount(), 1)
        row = page._sale_panel._item_rows[0]
        self.assertEqual(row.batch_no, "MML/26/006")
        self.assertEqual(row.mrp, 462.0)

    def test_03_multi_batch_item_selection_and_differing_mrps(self):
        """Item with multiple batches allows selecting between batches with differing MRPs."""
        page = CounterSalePage()
        page.show()
        self.app.processEvents()
        self.addCleanup(lambda: (page.hide(), page.deleteLater()))

        bar = page._sale_panel._entry_bar

        # Select LUMIA 2K
        bar.item_combo.setCurrentIndex(bar.item_combo.findData(self.item_lumia))
        self.app.processEvents()
        self.assertEqual(bar.batch_combo.count(), 2)

        # Select first batch: GKG2007A (MRP 123.0)
        idx1 = bar.batch_combo.findData(6932)
        bar.batch_combo.setCurrentIndex(idx1)
        self.app.processEvents()
        self.assertEqual(bar.mrp_edit.text(), "123.00")
        self.assertEqual(bar.expiry_edit.text(), "2027-02-28")
        self.assertEqual(bar.stock_edit.text(), "13")

        # Switch to second batch: GKH0615A (MRP 115.31)
        idx2 = bar.batch_combo.findData(7023)
        bar.batch_combo.setCurrentIndex(idx2)
        self.app.processEvents()
        self.assertEqual(bar.mrp_edit.text(), "115.31")
        self.assertEqual(bar.expiry_edit.text(), "2027-05-31")
        self.assertEqual(bar.stock_edit.text(), "28")

    def test_04_item_selection_without_batch_cannot_be_added(self):
        """Attempting to add an item without choosing a batch must warn and refuse addition."""
        page = CounterSalePage()
        page.show()
        self.app.processEvents()
        self.addCleanup(lambda: (page.hide(), page.deleteLater()))

        bar = page._sale_panel._entry_bar

        # Select LUMIA 2K but do not touch batch
        bar.item_combo.setCurrentIndex(bar.item_combo.findData(self.item_lumia))
        self.app.processEvents()

        self.assertEqual(bar.batch_combo.currentIndex(), -1)
        self.assertEqual(bar.batch_combo.lineEdit().text(), "")

        bar.add_btn.click()
        self.app.processEvents()

        # Table remains completely empty
        self.assertEqual(page._sale_panel._table.rowCount(), 0)

    def test_05_switching_items_invalidates_previous_batch_and_clears_stale_data(self):
        """Switching the selected item resets batch and clears all dependent controls."""
        page = CounterSalePage()
        page.show()
        self.app.processEvents()
        self.addCleanup(lambda: (page.hide(), page.deleteLater()))

        bar = page._sale_panel._entry_bar

        # Select STASHPain and choose batch
        bar.item_combo.setCurrentIndex(bar.item_combo.findData(self.item_stashpain))
        self.app.processEvents()
        bar.batch_combo.setCurrentIndex(bar.batch_combo.findData(7059))
        self.app.processEvents()

        self.assertEqual(bar.mrp_edit.text(), "126.00")
        self.assertEqual(bar.expiry_edit.text(), "2027-09-30")

        # Now switch item to ALPHA MED
        bar.item_combo.setCurrentIndex(bar.item_combo.findData(self.item_alpha))
        self.app.processEvents()

        # Batch must be reset to -1, text cleared, dependent fields cleared
        self.assertEqual(bar.batch_combo.currentIndex(), -1)
        self.assertEqual(bar.batch_combo.lineEdit().text(), "")
        self.assertEqual(bar.mrp_edit.text(), "")
        self.assertEqual(bar.expiry_edit.text(), "")
        self.assertEqual(bar.stock_edit.text(), "")
        self.assertEqual(bar.pack_edit.text(), "")
        self.assertEqual(bar.amount_edit.text(), "")

    def test_06_add_several_items_with_different_batch_formats(self):
        """Adding several items with numeric, alphabetic, and mixed batch numbers preserves each batch identity."""
        page = CounterSalePage()
        page.show()
        self.app.processEvents()
        self.addCleanup(lambda: (page.hide(), page.deleteLater()))

        bar = page._sale_panel._entry_bar

        items_to_add = [
            (self.item_stashpain, 7059, "133", "2"),
            (self.item_tendomac, 7094, "MML/26/006", "1"),
            (self.item_lumia, 7023, "GKH0615A", "3"),
            (self.item_alpha, 8001, "ALPHABATCH", "1"),
        ]

        for item_id, batch_id, expected_bno, qty in items_to_add:
            bar.item_combo.setCurrentIndex(bar.item_combo.findData(item_id))
            self.app.processEvents()
            bar.batch_combo.setCurrentIndex(bar.batch_combo.findData(batch_id))
            self.app.processEvents()
            bar.qty_edit.setText(qty)
            bar.add_btn.click()
            self.app.processEvents()

        self.assertEqual(page._sale_panel._table.rowCount(), 4)
        for i, (item_id, batch_id, expected_bno, qty) in enumerate(items_to_add):
            row = page._sale_panel._item_rows[i]
            self.assertEqual(row.item_id, item_id)
            self.assertEqual(row.stock_batch_id, batch_id)
            self.assertEqual(row.batch_no, expected_bno)
            self.assertEqual(page._sale_panel._table.item(i, 4).text(), expected_bno)

    def test_07_edit_and_restore_line_details(self):
        """Double-clicking a bill table row restores its exact item, batch, expiry, and MRP without choosing a different batch."""
        page = CounterSalePage()
        page.show()
        self.app.processEvents()
        self.addCleanup(lambda: (page.hide(), page.deleteLater()))

        bar = page._sale_panel._entry_bar

        # Add STASHPain batch 133
        bar.item_combo.setCurrentIndex(bar.item_combo.findData(self.item_stashpain))
        self.app.processEvents()
        bar.batch_combo.setCurrentIndex(bar.batch_combo.findData(7059))
        self.app.processEvents()
        bar.qty_edit.setText("2")
        bar.add_btn.click()
        self.app.processEvents()

        self.assertEqual(page._sale_panel._table.rowCount(), 1)
        self.assertEqual(page._sale_panel._item_rows[0].sale_qty, 2.0)

        # Double click the row to edit
        page._sale_panel.edit_row(0)
        self.app.processEvents()

        # Row is removed from table and restored into entry bar
        self.assertEqual(page._sale_panel._table.rowCount(), 0)
        self.assertEqual(bar.item_combo.currentData(), self.item_stashpain)
        self.assertEqual(bar.batch_combo.currentData(), 7059)
        self.assertEqual(bar.mrp_edit.text(), "126.00")
        self.assertEqual(bar.expiry_edit.text(), "2027-09-30")
        self.assertEqual(bar.qty_edit.text(), "2")

        # Update quantity to 4 and add back
        bar.qty_edit.setText("4")
        bar.add_btn.click()
        self.app.processEvents()

        self.assertEqual(page._sale_panel._table.rowCount(), 1)
        updated_row = page._sale_panel._item_rows[0]
        self.assertEqual(updated_row.batch_no, "133")
        self.assertEqual(updated_row.sale_qty, 4.0)
        # 4 * 126.00 = 504.00
        self.assertEqual(updated_row.amount, 504.0)

    def test_08_empty_stock_item_displays_no_stock_placeholder(self):
        """Item with no saleable stock displays 'No stock available' placeholder and has 0 batches."""
        page = CounterSalePage()
        page.show()
        self.app.processEvents()
        self.addCleanup(lambda: (page.hide(), page.deleteLater()))

        bar = page._sale_panel._entry_bar

        bar.item_combo.setCurrentIndex(bar.item_combo.findData(self.item_nostock))
        self.app.processEvents()

        self.assertEqual(bar.batch_combo.count(), 0)
        self.assertEqual(bar.batch_combo.lineEdit().text(), "")
        self.assertEqual(bar.batch_combo.lineEdit().placeholderText(), "No stock available")
        self.assertIsNone(bar.get_current_data())

    def test_09_prevent_item_batch_mismatch(self):
        """Directly verifies that get_current_data rejects a batch belonging to another item."""
        page = CounterSalePage()
        page.show()
        self.app.processEvents()
        self.addCleanup(lambda: (page.hide(), page.deleteLater()))

        bar = page._sale_panel._entry_bar

        # Force a mismatch: item is TENDOMAC, but batch_combo contains STASHPain batch
        bar.item_combo.setCurrentIndex(bar.item_combo.findData(self.item_tendomac))
        bar.batch_combo.clear()
        bar.batch_combo.addItem("Fake Batch", 7059)  # 7059 belongs to STASHPain
        bar.batch_combo.setCurrentIndex(0)
        self.app.processEvents()

        self.assertIsNone(bar.get_current_data())

    def test_10_staging_branding_title_preservation(self):
        """Title bar preserves [STAGING / AUDIT MODE] when switching screens."""
        os.environ["PHARMACY_STAGING_MODE"] = "1"
        try:
            title = _get_window_title("New Bill")
            self.assertIn("[STAGING / AUDIT MODE]", title)
            self.assertIn("New Bill", title)
        finally:
            os.environ.pop("PHARMACY_STAGING_MODE", None)


if __name__ == "__main__":
    unittest.main()
