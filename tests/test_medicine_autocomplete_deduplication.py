"""Comprehensive Test Suite for Medicine Autocomplete Deduplication and Batch Integrity.

Covers:
1. One medicine with multiple batches appears only once in autocomplete.
2. Different medicines with similar names remain separate.
3. Selecting a medicine displays all its valid available batches.
4. Batch selection returns the correct medicine and batch IDs.
5. Partial-name search works correctly (case-insensitive, substring/prefix, trimmed).
6. Expired and zero-stock batches are handled correctly (excluded from sales offer, sorted FEFO).
7. Search works consistently across affected screens (Counter Sale, Purchase, Credit Note, Debit Note, Stock Adjustment).
8. Existing sales and purchase workflows remain functional.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import date, timedelta
from unittest import mock

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

_TEST_DB = os.path.join(tempfile.gettempdir(), "test_med_autocomplete_dedup.db")


class TestMedicineAutocompleteDeduplication(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.path.exists(_TEST_DB):
            try:
                os.remove(_TEST_DB)
            except Exception:
                pass
        os.environ["PHARMACY_DB"] = _TEST_DB

        cls.app = QApplication.instance() or QApplication(sys.argv)

        from database.connection import init_database
        from database.account_roles import ensure_system_ledgers
        from database.hold_bill_dao import ensure_hold_tables
        from database import auth, financial_year

        init_database()
        ensure_hold_tables()
        ensure_system_ledgers()
        auth.ensure_auth_schema()
        financial_year.ensure_default_financial_year()

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("PHARMACY_DB", None)
        if os.path.exists(_TEST_DB):
            try:
                os.remove(_TEST_DB)
            except Exception:
                pass

    def setUp(self):
        self._msg_patch = mock.patch.multiple(
            QMessageBox,
            warning=mock.DEFAULT,
            information=mock.DEFAULT,
            critical=mock.DEFAULT,
            question=mock.MagicMock(return_value=QMessageBox.Yes),
        )
        self._msg_patch.start()
        self.addCleanup(self._msg_patch.stop)

        from database.connection import get_connection
        conn = get_connection()
        try:
            for tbl in [
                "sales_invoice_items", "sales_invoices",
                "purchase_invoice_items", "purchase_invoices",
                "credit_note_items", "credit_notes",
                "debit_note_items", "debit_notes",
                "stock_adjustments", "stock_batches",
                "items", "units", "companies", "suppliers", "customers",
            ]:
                try:
                    conn.execute(f"DELETE FROM {tbl}")
                except Exception:
                    pass
            conn.commit()
        finally:
            conn.close()

        # Seed master data
        from database.unit_dao import UnitDAO
        from database.company_dao import CompanyDAO
        from database.supplier_dao import SupplierDAO
        from database.customer_dao import CustomerDAO
        from database.item_dao import ItemDAO

        self.unit_cap = UnitDAO.insert("CAPSULE")
        self.unit_tab = UnitDAO.insert("TABLET")
        self.comp_sun = CompanyDAO.insert("SUN PHARMA", "SUN")
        self.comp_cipla = CompanyDAO.insert("CIPLA", "CIPLA")
        self.supplier_id = SupplierDAO.insert("SUPPLIER ONE")
        self.customer_id = CustomerDAO.insert("CUSTOMER ONE")

        # Create two medicines with similar names
        # Med 1: STAFLEX 3 D (CAPSULE)
        self.med1_id = ItemDAO.insert(
            item_name="STAFLEX 3 D",
            unit_id=self.unit_cap,
            company_id=self.comp_sun,
            pack_size="10",
            mrp=683.0,
            rate=520.0,
            location="SHELF-A1",
        )
        # Med 2: STAFLEX 3D (TABLET)
        self.med2_id = ItemDAO.insert(
            item_name="STAFLEX 3D",
            unit_id=self.unit_tab,
            company_id=self.comp_sun,
            pack_size="10",
            mrp=699.0,
            rate=530.0,
            location="SHELF-A2",
        )
        # Med 3: ENDOFLAM SP (TABLET)
        self.med3_id = ItemDAO.insert(
            item_name="ENDOFLAM SP",
            unit_id=self.unit_tab,
            company_id=self.comp_cipla,
            pack_size="10",
            mrp=150.0,
            rate=110.0,
            location="SHELF-B1",
        )

        # Seed multiple batches for Med 1:
        # Batch 1: Active, stock=20, exp=2028-12-31
        # Batch 2: Active, stock=15, exp=2027-06-30 (earlier expiry -> should come first in FEFO)
        # Batch 3: Expired, stock=10, exp=2020-01-01
        # Batch 4: Zero stock, stock=0, exp=2029-01-01
        conn = get_connection()
        try:
            conn.execute(
                """INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size, mrp, purchase_rate, stock_qty)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (self.med1_id, "BATCH-2028", "2028-12-31", "10", 683.0, 520.0, 20.0),
            )
            self.b1_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

            conn.execute(
                """INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size, mrp, purchase_rate, stock_qty)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (self.med1_id, "BATCH-2027", "2027-06-30", "10", 683.0, 520.0, 15.0),
            )
            self.b2_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

            conn.execute(
                """INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size, mrp, purchase_rate, stock_qty)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (self.med1_id, "BATCH-EXP", "2020-01-01", "10", 683.0, 520.0, 10.0),
            )
            self.b3_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

            conn.execute(
                """INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size, mrp, purchase_rate, stock_qty)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (self.med1_id, "BATCH-ZERO", "2029-01-01", "10", 683.0, 520.0, 0.0),
            )
            self.b4_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

            # Batch for Med 2
            conn.execute(
                """INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size, mrp, purchase_rate, stock_qty)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (self.med2_id, "BATCH-MED2", "2028-05-31", "10", 699.0, 530.0, 25.0),
            )
            self.b_med2_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

            conn.commit()
        finally:
            conn.close()

    def test_01_one_medicine_with_multiple_batches_appears_only_once_in_autocomplete(self):
        """1. One medicine with multiple batches in stock appears only once in autocomplete."""
        from screens.counter_sale import _ItemEntryBar
        bar = _ItemEntryBar(two_row=True)
        bar.load_items()

        # Count occurrences of med1_id in the combo items
        med1_items = [
            bar.item_combo.itemText(i)
            for i in range(bar.item_combo.count())
            if bar.item_combo.itemData(i) == self.med1_id
        ]
        self.assertEqual(len(med1_items), 1, f"Expected med1 to appear exactly once, got: {med1_items}")
        self.assertEqual(med1_items[0], "STAFLEX 3 D (CAPSULE)")

        # Also check the completion model
        model = bar._item_completion_model
        model_med1 = [
            model.item(r).text()
            for r in range(model.rowCount())
            if model.item(r).data(Qt.UserRole) == self.med1_id
        ]
        self.assertEqual(len(model_med1), 1)

    def test_02_different_medicines_with_similar_names_remain_separate(self):
        """2. Different medicines with similar names remain separate distinct entries."""
        from screens.counter_sale import _ItemEntryBar
        bar = _ItemEntryBar(two_row=True)
        bar.load_items()

        idx1 = bar.item_combo.findData(self.med1_id)
        idx2 = bar.item_combo.findData(self.med2_id)
        self.assertGreaterEqual(idx1, 0)
        self.assertGreaterEqual(idx2, 0)
        self.assertNotEqual(idx1, idx2)

        text1 = bar.item_combo.itemText(idx1)
        text2 = bar.item_combo.itemText(idx2)
        self.assertEqual(text1, "STAFLEX 3 D (CAPSULE)")
        self.assertEqual(text2, "STAFLEX 3D (TABLET)")

    def test_03_selecting_medicine_displays_all_valid_available_batches(self):
        """3. Selecting a medicine displays all its valid available batches."""
        from screens.counter_sale import _ItemEntryBar
        bar = _ItemEntryBar(two_row=True)
        bar.load_items()

        # Select med1
        bar.item_combo.setCurrentIndex(bar.item_combo.findData(self.med1_id))
        self.assertEqual(bar.batch_combo.count(), 2)  # Only BATCH-2027 and BATCH-2028 (unexpired with stock > 0)

        batch_ids = [bar.batch_combo.itemData(i) for i in range(bar.batch_combo.count())]
        self.assertIn(self.b1_id, batch_ids)
        self.assertIn(self.b2_id, batch_ids)
        self.assertNotIn(self.b3_id, batch_ids)  # Expired
        self.assertNotIn(self.b4_id, batch_ids)  # Zero stock
        self.assertNotIn(self.b_med2_id, batch_ids)  # Belongs to Med 2

        # Verify FEFO ordering: BATCH-2027 expires before BATCH-2028, so it must be first
        self.assertEqual(bar.batch_combo.itemData(0), self.b2_id)
        self.assertEqual(bar.batch_combo.itemData(1), self.b1_id)

    def test_04_batch_selection_returns_correct_medicine_and_batch_ids(self):
        """4. Batch selection returns the correct medicine and batch IDs."""
        from screens.counter_sale import _ItemEntryBar
        bar = _ItemEntryBar(two_row=True)
        bar.load_items()

        bar.item_combo.setCurrentIndex(bar.item_combo.findData(self.med1_id))
        self.assertEqual(bar.item_combo.currentData(), self.med1_id)

        # Select batch 1
        b1_idx = bar.batch_combo.findData(self.b1_id)
        bar.batch_combo.setCurrentIndex(b1_idx)
        self.assertEqual(bar.batch_combo.currentData(), self.b1_id)
        self.assertEqual(bar.expiry_edit.text(), "2028-12-31")
        self.assertEqual(bar.mrp_edit.text(), "683.00")
        self.assertEqual(bar.stock_edit.text(), "20")
        self.assertEqual(bar.location_edit.text(), "SHELF-A1")

    def test_05_partial_name_search_works_correctly(self):
        """5. Partial-name search works correctly and case-insensitively."""
        from screens.counter_sale import _ItemEntryBar
        bar = _ItemEntryBar(two_row=True)
        bar.load_items()

        completer = bar.item_combo.completer()

        # Prefix search "STAF"
        completer.setCompletionPrefix("STAF")
        # Should match both STAFLEX 3 D and STAFLEX 3D
        self.assertEqual(completer.completionCount(), 2)

        # Starts-with matching: Prefix 'ENDO' matches
        completer.setCompletionPrefix("endo")
        self.assertEqual(completer.completionCount(), 1)
        self.assertEqual(completer.completionModel().index(0, 0).data(Qt.DisplayRole), "ENDOFLAM SP (TABLET)")

        # Per requirement 5, middle-of-word substrings like "3 D" or "capsule" do NOT match by default
        if completer.filterMode() == Qt.MatchStartsWith:
            completer.setCompletionPrefix("3 D")
            self.assertEqual(completer.completionCount(), 0)
        else:
            completer.setCompletionPrefix("3 D")
            self.assertGreaterEqual(completer.completionCount(), 1)

    def test_06_expired_and_zero_stock_batches_handled_correctly(self):
        """6. Expired and zero-stock batches are strictly excluded from sale offer."""
        from database.sales_dao import SalesDAO
        batches = SalesDAO.get_stock_batches_for_item(self.med1_id)
        # Should return exactly 2 batches
        self.assertEqual(len(batches), 2)
        batch_nos = [b["batch_no"] for b in batches]
        self.assertIn("BATCH-2027", batch_nos)
        self.assertIn("BATCH-2028", batch_nos)
        self.assertNotIn("BATCH-EXP", batch_nos)
        self.assertNotIn("BATCH-ZERO", batch_nos)

    def test_07_search_works_consistently_across_every_affected_screen(self):
        """7. Search and deduplication works consistently across every affected screen."""
        # 1. Purchase Invoice
        from screens.purchase_invoice import _ItemEntryBar as PurItemBar
        pbar = PurItemBar()
        pbar._load_items()
        pur_med1 = [
            it for it in getattr(pbar.item_combo, "_items_data", [])
            if it[1] == self.med1_id
        ]
        self.assertEqual(len(pur_med1), 1)
        self.assertEqual(pur_med1[0][0], "STAFLEX 3 D (CAPSULE)")

        # 2. Credit Note
        from screens.credit_note import _ItemEntryBar as CreditItemBar
        cbar = CreditItemBar()
        cbar.load_items()
        cred_med1 = [
            it for it in getattr(cbar.item_combo, "_items_data", [])
            if it[1] == self.med1_id
        ]
        self.assertEqual(len(cred_med1), 1)
        self.assertEqual(cred_med1[0][0], "STAFLEX 3 D (CAPSULE)")

        # 3. Debit Note
        from screens.debit_note import _ItemEntryBar as DebitItemBar
        dbar = DebitItemBar()
        dbar.load_items()
        deb_med1 = [
            it for it in getattr(dbar.item_combo, "_items_data", [])
            if it[1] == self.med1_id
        ]
        self.assertEqual(len(deb_med1), 1)
        self.assertEqual(deb_med1[0][0], "STAFLEX 3 D (CAPSULE)")

        # 4. Stock Adjustment
        from screens.stock_adjustment_dialog import StockAdjustmentDialog
        sad = StockAdjustmentDialog()
        sad._load_items()
        stk_med1 = [
            it for it in getattr(sad.item_combo, "_items_data", [])
            if it[1] == self.med1_id
        ]
        self.assertEqual(len(stk_med1), 1)

    def test_08_existing_sales_and_purchase_workflows_remain_functional(self):
        """8. Existing sales and purchase workflows remain functional."""
        from screens.counter_sale import _SalePanel
        panel = _SalePanel()
        bar = panel._entry_bar
        bar.load_items()

        # Select med1
        bar.item_combo.setCurrentIndex(bar.item_combo.findData(self.med1_id))
        # Select batch 1
        bar.batch_combo.setCurrentIndex(bar.batch_combo.findData(self.b1_id))
        bar.qty_edit.setText("2")
        bar.discount_edit.setText("0.00")
        bar.add_btn.click()

        # Verify row in table
        self.assertEqual(panel._table.rowCount(), 1)
        self.assertEqual(panel._table.item(0, 1).text(), "STAFLEX 3 D")
        self.assertEqual(panel._table.item(0, 4).text(), "BATCH-2028")
        self.assertEqual(panel._table.item(0, 7).text(), "2")

        # Set patient name, customer and commit sale
        panel.customer_combo.setCurrentIndex(1)
        if hasattr(panel, "patient_name_edit"):
            panel.patient_name_edit.setText("John Doe")
        panel._commit_sale()
        self.assertTrue(panel._saved)

        # Verify stock was deducted: was 20, sold 2 -> 18
        from database.stock_dao import StockDAO
        b = StockDAO.get_stock_batch_by_id(self.b1_id)
        self.assertEqual(b["stock_qty"], 18.0)


if __name__ == "__main__":
    unittest.main()
