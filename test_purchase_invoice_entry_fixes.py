"""Comprehensive verification test suite for Purchase -> New Purchase Invoice fixes:
1. Item-entry layout responsiveness & space redistribution (1200px, 1366px, 1600px, 1920px).
2. Medicine autocomplete search: case-insensitive, prefix-based matching from beginning only.
3. Existing batch selection: loads saved expiry date and details without overwriting.
4. New batch entry: leaves expiry empty, allows editing, validates before saving.
5. Purchase invoice save and stock update on an isolated database clone.
6. Non-prefix autocomplete on unrelated screens / default SearchableComboBox is preserved.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from datetime import date
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QDate, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget, QVBoxLayout

app = QApplication.instance() or QApplication(sys.argv)

import database.connection as db_conn
from database.stock_dao import StockDAO
from database.item_dao import ItemDAO
from database.purchase_dao import PurchaseDAO
from database.supplier_dao import SupplierDAO
from database.account_roles import ensure_system_ledgers
import database.financial_year as financial_year
from screens.purchase_invoice import (
    _InvoiceDialog,
    _InvoiceItemRow,
    _ItemEntryBar,
    BatchLineEdit,
    ExpiryDateEdit,
    parse_expiry_to_date,
    format_expiry_display,
)
from ui.components import SearchableComboBox


class TestPurchaseInvoiceEntryFixes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig_db = os.environ.get("PHARMACY_DB")
        cls._orig_conn_db_path = getattr(db_conn, "DB_PATH", None)
        cls.temp_dir = tempfile.mkdtemp(prefix="test_purch_fixes_")
        cls.test_db_path = os.path.join(cls.temp_dir, "isolated_test.db")
        os.environ["PHARMACY_DB"] = cls.test_db_path
        db_conn.DB_PATH = cls.test_db_path

        # Initialize fresh schema
        db_conn.init_database()
        ensure_system_ledgers()

        # Seed minimal financial year
        with db_conn.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO financial_years (id, name, start_date, end_date, is_active, created_at) "
                "VALUES (1, '2026-2027', '2026-04-01', '2027-03-31', 1, '2026-04-01 00:00:00')"
            )
            conn.commit()

        cls.supplier_id = SupplierDAO.insert("TEST PHARMA DISTRIBUTORS")

        # Insert items using ItemDAO
        ItemDAO.insert(item_name="TAB PARACETAMOL 500MG", pack_size="10", mrp=50.0, rate=35.0, tax_structure="GST 12%")
        ItemDAO.insert(item_name="TAB IBUPROFEN 400MG", pack_size="10", mrp=60.0, rate=42.0, tax_structure="GST 12%")
        ItemDAO.insert(item_name="CETAMOL TAB", pack_size="10", mrp=45.0, rate=30.0, tax_structure="GST 12%")
        ItemDAO.insert(item_name="ENDOFLAM SP", pack_size="10", mrp=120.0, rate=85.0, tax_structure="GST 18%")
        ItemDAO.insert(item_name="SCAREND GEL", pack_size="20G", mrp=150.0, rate=110.0, tax_structure="GST 18%")

        # Insert an existing batch for item 1
        with db_conn.get_connection() as conn:
            conn.execute(
                "INSERT INTO stock_batches (id, item_id, batch_no, expiry, mrp, purchase_rate, net_rate, stock_qty) "
                "VALUES (101, 1, 'PARA-EXISTING-01', '2028-10-31', 50.0, 35.0, 48.0, 100)"
            )
            conn.commit()

    @classmethod
    def tearDownClass(cls):
        if cls._orig_db is not None:
            os.environ["PHARMACY_DB"] = cls._orig_db
        else:
            os.environ.pop("PHARMACY_DB", None)
        if cls._orig_conn_db_path is not None:
            db_conn.DB_PATH = cls._orig_conn_db_path
        shutil.rmtree(cls.temp_dir, ignore_errors=True)

    def _pump(self):
        app.processEvents()

    # ==================================================================
    # 1. Purchase Item-Entry Layout & Responsiveness
    # ==================================================================
    def test_01_layout_redistribution_across_resolutions(self):
        """Verifies item entry layout bounds and space redistribution from 1200 to 1920px."""
        for total_w in [1200, 1366, 1600, 1920]:
            container = QWidget()
            container.resize(total_w, 60)
            layout = QVBoxLayout(container)
            layout.setContentsMargins(10, 5, 10, 5)
            bar = _ItemEntryBar(container)
            layout.addWidget(bar)
            container.show()
            self._pump()

            # 1. Bar remains single-row height
            self.assertLessEqual(bar.height(), 45)

            # 2. Item Name autocomplete width is bounded (not excessive at 1920px)
            # At 1920px, max_width=450 prevents it from eating 1050px
            self.assertLessEqual(bar.item_combo.width(), 450)
            self.assertGreaterEqual(bar.item_combo.width(), 180)

            # 3. All other fields have sufficient width to display their values without clipping
            self.assertGreaterEqual(bar.pack_edit.width(), 50)
            self.assertGreaterEqual(bar.pay_qty_edit.width(), 50)
            self.assertGreaterEqual(bar.free_qty_edit.width(), 44)
            self.assertGreaterEqual(bar.batch_edit.width(), 95)
            self.assertGreaterEqual(bar.expiry_edit.width(), 125)
            self.assertGreaterEqual(bar.rate_edit.width(), 62)
            self.assertGreaterEqual(bar.mrp_edit.width(), 62)
            self.assertGreaterEqual(bar.discount_edit.width(), 48)
            self.assertGreaterEqual(bar.gst_edit.width(), 42)

            # 4. + Add Item button stays within bar boundaries
            btn_right = bar.add_btn.geometry().right()
            self.assertLessEqual(btn_right, bar.width(), f"Button overflowed at width {total_w}")

            # 5. ExpiryDateEdit lineEdit fits 'DD-MM-YYYY' comfortably (95px+ vs 86px normal advance)
            self.assertGreaterEqual(bar.expiry_edit._line.width(), 95)
            if os.environ.get("QT_QPA_PLATFORM") != "offscreen":
                adv = bar.expiry_edit._line.fontMetrics().horizontalAdvance("DD-MM-YYYY")
                self.assertGreater(bar.expiry_edit._line.width(), adv)

            container.close()
            container.deleteLater()

    # ==================================================================
    # 2. Medicine Autocomplete Search (Prefix-Only)
    # ==================================================================
    def test_02_prefix_based_medicine_autocomplete(self):
        """Typing TAB returns items beginning with TAB, not substring matches."""
        bar = _ItemEntryBar()
        bar._load_items()
        self._pump()

        # Item combo has prefix_only=True
        self.assertTrue(getattr(bar.item_combo, "_prefix_only", False))

        # Test prefix matching: 'TAB'
        bar.item_combo._on_text_edited("TAB")
        self._pump()
        model = bar.item_combo._completer_model
        results = [model.index(i, 0).data(Qt.DisplayRole) for i in range(model.rowCount())]

        # Should match 'TAB PARACETAMOL 500MG' and 'TAB IBUPROFEN 400MG'
        self.assertIn("TAB PARACETAMOL 500MG", results)
        self.assertIn("TAB IBUPROFEN 400MG", results)
        # Should NOT match 'CETAMOL TAB'
        self.assertNotIn("CETAMOL TAB", results)

        # Test case-insensitivity: 'tab'
        bar.item_combo._on_text_edited("tab")
        self._pump()
        results_lower = [model.index(i, 0).data(Qt.DisplayRole) for i in range(model.rowCount())]
        self.assertIn("TAB PARACETAMOL 500MG", results_lower)
        self.assertNotIn("CETAMOL TAB", results_lower)

        # Test leading/trailing spaces ignored: '   tab   '
        bar.item_combo._on_text_edited("   tab   ")
        self._pump()
        results_spaced = [model.index(i, 0).data(Qt.DisplayRole) for i in range(model.rowCount())]
        self.assertIn("TAB PARACETAMOL 500MG", results_spaced)
        self.assertNotIn("CETAMOL TAB", results_spaced)

        # Test prefix matching: 'END'
        bar.item_combo._on_text_edited("END")
        self._pump()
        results_end = [model.index(i, 0).data(Qt.DisplayRole) for i in range(model.rowCount())]
        self.assertIn("ENDOFLAM SP", results_end)
        self.assertNotIn("SCAREND GEL", results_end)

        # Test non-prefix fails
        bar.item_combo._on_text_edited("PARACETAMOL")
        self._pump()
        results_para = [model.index(i, 0).data(Qt.DisplayRole) for i in range(model.rowCount())]
        # Since name starts with 'TAB PARACETAMOL', prefix 'PARACETAMOL' should NOT match
        self.assertNotIn("TAB PARACETAMOL 500MG", results_para)

        bar.deleteLater()

    def test_03_default_searchable_combobox_retains_contains_matching(self):
        """Unrelated screens without prefix_only=True keep normal contains-search."""
        combo = SearchableComboBox(placeholder="Search...")
        combo.populate([
            ("TAB PARACETAMOL 500MG", 1),
            ("CETAMOL TAB", 2),
        ])
        self.assertFalse(getattr(combo, "_prefix_only", False))

        combo._on_text_edited("TAB")
        self._pump()
        model = combo._completer_model
        results = [model.index(i, 0).data(Qt.DisplayRole) for i in range(model.rowCount())]
        # Both items contain 'TAB'
        self.assertIn("TAB PARACETAMOL 500MG", results)
        self.assertIn("CETAMOL TAB", results)

        combo.deleteLater()

    # ==================================================================
    # 3. Existing Batch Selection
    # ==================================================================
    def test_04_existing_batch_selection_loads_expiry_and_details(self):
        """Selecting an existing batch automatically loads its saved expiry date and details."""
        bar = _ItemEntryBar()
        bar.get_invoice_date_fn = lambda: date(2026, 11, 6)

        existing_batch = {
            "id": 101,
            "item_id": 1,
            "batch_no": "PARA-EXISTING-01",
            "expiry": "2028-10-31",
            "rate": 35.0,
            "mrp": 50.0,
            "pack_size": "10",
            "gst_percent": 12.0,
        }

        # Select saved batch
        bar._on_saved_batch_selected(existing_batch)
        self._pump()

        # Batch number set
        self.assertEqual(bar.batch_edit.text(), "PARA-EXISTING-01")
        # Expiry set to DD-MM-YYYY format
        self.assertEqual(bar.expiry_edit.text(), "31-10-2028")
        # Rate and MRP populated
        self.assertEqual(bar.rate_edit.text(), "35.00")
        self.assertEqual(bar.mrp_edit.text(), "50.00")
        self.assertEqual(bar.pack_edit.text(), "10")
        self.assertEqual(bar.gst_edit.text(), "12")
        # Batch fields are marked read-only to preserve saved batch integrity
        self.assertTrue(bar.expiry_edit.isReadOnly())
        self.assertTrue(bar.rate_edit.isReadOnly())
        self.assertTrue(bar.mrp_edit.isReadOnly())

        bar.deleteLater()

    # ==================================================================
    # 4. New Batch Entry and Editing
    # ==================================================================
    def test_05_new_batch_entry_leaves_expiry_empty_and_allows_editing(self):
        """Entering a new batch leaves expiry empty, unlocks fields, and allows editing."""
        bar = _ItemEntryBar()
        bar.get_invoice_date_fn = lambda: date(2026, 11, 6)

        # 1. First simulate existing batch was selected
        bar._on_saved_batch_selected({
            "id": 101,
            "batch_no": "PARA-EXISTING-01",
            "expiry": "2028-10-31",
            "rate": 35.0,
            "mrp": 50.0,
        })
        self.assertEqual(bar.expiry_edit.text(), "31-10-2028")
        self.assertTrue(bar.expiry_edit.isReadOnly())

        # 2. User edits batch text to a NEW batch number
        bar.batch_edit.setText("NEW-BATCH-999")
        self._pump()

        # Expiry is cleared immediately
        self.assertEqual(bar.expiry_edit.text(), "")
        # Selected batch id is cleared
        self.assertIsNone(bar._selected_batch_id)
        # Fields are unlocked for editing
        self.assertFalse(bar.expiry_edit.isReadOnly())
        self.assertFalse(bar.rate_edit.isReadOnly())
        self.assertFalse(bar.mrp_edit.isReadOnly())

        # 3. User manually enters expiry date
        bar.expiry_edit.setText("31-12-2029")
        self.assertEqual(bar.expiry_edit.text(), "31-12-2029")
        self.assertEqual(bar.expiry_edit.iso_date(), "2029-12-31")

        bar.deleteLater()

    # ==================================================================
    # 5. Expiry Validation and Invoice Save on Isolated Clone DB
    # ==================================================================
    def test_06_expiry_validation_on_save(self):
        """Validates that saving with empty or expired expiry shows a warning."""
        dlg = _InvoiceDialog()
        dlg.voucher_date.setDate(QDate(2026, 11, 6))

        # Select supplier
        dlg.supplier_combo.addItem("TEST PHARMA DISTRIBUTORS", self.supplier_id)
        dlg.supplier_combo.setCurrentIndex(0)

        # Add item row with empty expiry
        row_empty_exp = _InvoiceItemRow(
            item_id=1,
            item_name="TAB PARACETAMOL 500MG",
            pack_size="10",
            pay_qty=10,
            free_qty=0,
            batch_no="NEW-BAT-1",
            expiry="",
            rate=35.0,
            mrp=50.0,
            discount=0.0,
            gst_percent=12.0,
            amount=350.0,
            gst_amount=42.0,
            purchase_rate=39.2,
            net_rate=39.2,
            pp=25.0,
        )
        dlg._item_rows = [row_empty_exp]

        with patch.object(QMessageBox, "warning") as mock_warn:
            dlg._on_save()
            mock_warn.assert_called()
            args = mock_warn.call_args[0]
            self.assertEqual(args[1], "Validation")
            self.assertIn("requires a valid Expiry Date", args[2])

        # Change expiry to an EXPIRED date (e.g. 2026-05-31 when invoice is 2026-11-06)
        row_empty_exp.expiry = "31-05-2026"
        with patch.object(QMessageBox, "warning") as mock_warn:
            dlg._on_save()
            mock_warn.assert_called()
            args = mock_warn.call_args[0]
            self.assertEqual(args[1], "Expired Stock")
            self.assertIn("is expired", args[2])

        dlg.close()
        dlg.deleteLater()

    def test_07_save_invoice_updates_stock_without_overwriting_existing_batch_expiry(self):
        """Saving purchase invoice creates new batch / updates stock safely."""
        dlg = _InvoiceDialog()
        dlg.voucher_date.setDate(QDate(2026, 11, 6))

        dlg.supplier_combo.addItem("TEST PHARMA DISTRIBUTORS", self.supplier_id)
        dlg.supplier_combo.setCurrentIndex(0)

        # 1. Add item with existing batch (expiry 2028-10-31 in DB)
        # 2. Add item with brand new batch (expiry 2029-06-30)
        row1 = _InvoiceItemRow(
            item_id=1,
            item_name="TAB PARACETAMOL 500MG",
            pack_size="10",
            pay_qty=20,
            free_qty=2,
            batch_no="PARA-EXISTING-01",
            expiry="31-10-2028",
            rate=35.0,
            mrp=50.0,
            discount=0.0,
            gst_percent=12.0,
            amount=700.0,
            gst_amount=84.0,
            purchase_rate=39.2,
            net_rate=35.64,
            pp=25.0,
            batch_id=101,
        )
        row2 = _InvoiceItemRow(
            item_id=4,
            item_name="ENDOFLAM SP",
            pack_size="10",
            pay_qty=15,
            free_qty=1,
            batch_no="ENDO-NEW-888",
            expiry="30-06-2029",
            rate=85.0,
            mrp=120.0,
            discount=0.0,
            gst_percent=18.0,
            amount=1275.0,
            gst_amount=229.5,
            purchase_rate=100.3,
            net_rate=94.03,
            pp=25.0,
        )
        dlg._item_rows = [row1, row2]

        # Check stock before save:
        # Existing batch 101 had stock 100
        b101_before = StockDAO.get_stock_batch_by_id(101)
        self.assertEqual(b101_before["stock_qty"], 100)
        self.assertEqual(b101_before["expiry"], "2028-10-31")

        with patch.object(QMessageBox, "information") as mock_info, \
             patch.object(QMessageBox, "critical") as mock_crit, \
             patch.object(QMessageBox, "warning") as mock_warn:
            dlg._on_save()
            mock_crit.assert_not_called()
            mock_warn.assert_not_called()

        # Check stock after save:
        # Batch 101 stock should now be 100 + (20 + 2) * 10 = 320.0 (units)
        b101_after = StockDAO.get_stock_batch_by_id(101)
        self.assertEqual(b101_after["stock_qty"], 320.0)
        # DB expiry MUST NOT be overwritten or corrupted
        self.assertEqual(b101_after["expiry"], "2028-10-31")

        # New batch should be created with stock (15 + 1) * 10 = 160.0 and expiry 2029-06-30
        new_batches = StockDAO.get_stock_batches_for_item(4)
        new_batch = next((b for b in new_batches if b["batch_no"] == "ENDO-NEW-888"), None)
        self.assertIsNotNone(new_batch)
        self.assertEqual(new_batch["stock_qty"], 160.0)
        self.assertEqual(new_batch["expiry"], "2029-06-30")

        dlg.close()
        dlg.deleteLater()


if __name__ == "__main__":
    unittest.main()
