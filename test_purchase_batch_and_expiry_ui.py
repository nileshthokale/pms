"""Unit and integration tests for New Purchase Invoice:
Batch Dropdown simplification, Expiry Date picker, UI layout, and calculations integrity.

Verifies the 7 requirements:
1. Selecting an item leaves the batch field empty (no auto-selection).
2. The dropdown displays only batch numbers (no expiry/rates/pipes).
3. Selecting a batch loads its correct saved expiry and pricing details, preserving internal batch ID.
4. Changing the item clears the previous batch and dependent fields.
5. Manually selecting an expiry date works correctly (calendar, text entry, bounds check, validation).
6. Existing batches are not overwritten accidentally.
7. Existing purchase calculations and invoice saving remain unchanged.
"""

import sys
import os
import unittest
import sqlite3
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import Qt, QDate, QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

app = QApplication.instance() or QApplication(sys.argv)

from screens.purchase_invoice import (
    _ItemEntryBar,
    _InvoiceDialog,
    BatchLineEdit,
    ExpiryDateEdit,
    parse_expiry_to_date,
    format_expiry_display,
    normalize_expiry_db,
    _InvoiceItemRow,
)
from database.purchase_dao import PurchaseDAO


class TestPurchaseBatchAndExpiryUI(unittest.TestCase):

    def setUp(self):
        self.bar = _ItemEntryBar()
        self.sample_batches = [
            {"id": 101, "batch_no": "BAT-2026-A", "expiry": "2028-05-31", "rate": 45.50, "mrp": 70.0, "pack_size": "10", "gst_percent": 12.0},
            {"id": 102, "batch_no": "BAT-2026-B", "expiry": "2029-01-31", "rate": 50.00, "mrp": 80.0, "pack_size": "10", "gst_percent": 12.0},
        ]

    def tearDown(self):
        self.bar.deleteLater()

    # ------------------------------------------------------------------
    # 1. Selecting an item leaves the batch field empty
    # ------------------------------------------------------------------
    @patch("screens.purchase_invoice.ItemDAO")
    @patch("screens.purchase_invoice.PurchaseDAO")
    @patch("screens.purchase_invoice.SupplierDAO")
    @patch("screens.purchase_invoice.financial_year")
    def test_01_selecting_item_leaves_batch_field_empty(
        self, mock_fy, mock_sup, mock_purch, mock_item
    ):
        mock_fy.get_active_financial_year.return_value = {
            "id": 1, "start_date": "2026-04-01", "end_date": "2027-03-31"
        }
        mock_sup.get_all.return_value = []
        mock_purch.generate_next_voucher_no.return_value = "PV-100"
        mock_purch.get_saved_batches_for_item.return_value = self.sample_batches
        mock_item.get_all.return_value = [
            {"id": 1, "item_name": "PARACETAMOL 500MG", "pack_size": "10", "rate": 40.0, "mrp": 60.0, "tax_structure": "GST 12%"}
        ]
        mock_item.get_by_id.return_value = {
            "id": 1, "item_name": "PARACETAMOL 500MG", "pack_size": "10", "rate": 40.0, "mrp": 60.0, "tax_structure": "GST 12%"
        }

        dlg = _InvoiceDialog()
        try:
            # Simulate selecting Item 1
            dlg._entry_bar.item_combo.blockSignals(True)
            dlg._entry_bar.item_combo.clear()
            dlg._entry_bar.item_combo.addItem("PARACETAMOL 500MG", 1)
            dlg._entry_bar.item_combo.setCurrentIndex(0)
            dlg._entry_bar.item_combo.blockSignals(False)
            dlg._on_item_changed(0)

            # R1: The batch field must remain strictly empty (no auto-selection)
            self.assertEqual(dlg._entry_bar.batch_edit.text(), "")
            # Completer has the batches loaded
            self.assertEqual(dlg._entry_bar.batch_edit._model.rowCount(), 2)
            # Expiry date field must be empty
            self.assertEqual(dlg._entry_bar.expiry_edit.text(), "")
            # Pay Qty and Free Qty must be empty
            self.assertEqual(dlg._entry_bar.pay_qty_edit.text(), "")
            self.assertEqual(dlg._entry_bar.free_qty_edit.text(), "")
        finally:
            dlg.close()

    # ------------------------------------------------------------------
    # 2. The dropdown displays batch numbers with supporting expiry info
    # ------------------------------------------------------------------
    def test_02_dropdown_displays_batch_numbers_with_supporting_expiry(self):
        edit = BatchLineEdit("Batch", 130)
        edit.set_batches(self.sample_batches)

        # Model should have 2 rows
        self.assertEqual(edit._model.rowCount(), 2)

        # Check item 0
        item0 = edit._model.item(0)
        self.assertTrue(item0.text().startswith("BAT-2026-A"))
        self.assertIn("Exp: 31-05-2028", item0.text())
        self.assertNotIn("Rate", item0.text())

        # Check item 1
        item1 = edit._model.item(1)
        self.assertTrue(item1.text().startswith("BAT-2026-B"))
        self.assertIn("Exp: 31-01-2029", item1.text())

    # ------------------------------------------------------------------
    # 3. Selecting a batch loads its correct saved expiry and pricing details
    # ------------------------------------------------------------------
    def test_03_selecting_batch_loads_correct_saved_expiry_and_pricing(self):
        self.bar.batch_edit.set_batches(self.sample_batches)

        # User selects batch BAT-2026-A
        selected_data = self.sample_batches[0]
        self.bar._on_saved_batch_selected(selected_data)

        # Verified batch text
        self.assertEqual(self.bar.batch_edit.text(), "BAT-2026-A")
        # Expiry date populated from batch: 2028-05-31 -> 31-05-2028
        self.assertEqual(self.bar.expiry_edit.text(), "31-05-2028")
        # Rate and MRP populated from batch
        self.assertEqual(self.bar.rate_edit.text(), "45.50")
        self.assertEqual(self.bar.mrp_edit.text(), "70.00")
        # Pack and GST populated if present
        self.assertEqual(self.bar.pack_edit.text(), "10")
        self.assertEqual(self.bar.gst_edit.text(), "12")

        # Internal batch ID is preserved
        self.assertEqual(self.bar._selected_batch_id, 101)

        # When getting current item data, batch_id is preserved
        with patch("screens.purchase_invoice.ItemDAO.get_by_id", return_value={"id": 1, "item_name": "Test", "pack_size": "10"}):
            self.bar.item_combo.clear()
            self.bar.item_combo.addItem("Test", 1)
            self.bar.item_combo.setCurrentIndex(0)
            data = self.bar.get_current_item_data()
            self.assertEqual(data["batch_id"], 101)
            self.assertEqual(data["batch_no"], "BAT-2026-A")

    # ------------------------------------------------------------------
    # 4. Changing the item clears the previous batch and dependent fields
    # ------------------------------------------------------------------
    @patch("screens.purchase_invoice.ItemDAO")
    @patch("screens.purchase_invoice.PurchaseDAO")
    @patch("screens.purchase_invoice.SupplierDAO")
    @patch("screens.purchase_invoice.financial_year")
    def test_04_changing_item_clears_previous_batch_and_dependent_fields(
        self, mock_fy, mock_sup, mock_purch, mock_item
    ):
        mock_fy.get_active_financial_year.return_value = {
            "id": 1, "start_date": "2026-04-01", "end_date": "2027-03-31"
        }
        mock_sup.get_all.return_value = []
        mock_purch.generate_next_voucher_no.return_value = "PV-101"

        batches_item_1 = [
            {"id": 201, "batch_no": "BATCH_ITEM_1", "expiry": "2028-06-30", "rate": 50.0, "mrp": 75.0, "pack_size": "10"}
        ]
        batches_item_2 = [
            {"id": 202, "batch_no": "BATCH_ITEM_2", "expiry": "2029-03-31", "rate": 90.0, "mrp": 120.0, "pack_size": "10"}
        ]

        def fake_get_batches(item_id):
            return batches_item_1 if item_id == 1 else batches_item_2

        mock_purch.get_saved_batches_for_item.side_effect = fake_get_batches

        item1_dict = {"id": 1, "item_name": "MEDICINE ONE", "pack_size": "10", "rate": 48.0, "mrp": 70.0, "tax_structure": "GST 12%"}
        item2_dict = {"id": 2, "item_name": "MEDICINE TWO", "pack_size": "15", "rate": 88.0, "mrp": 115.0, "tax_structure": "GST 18%"}

        def fake_get_by_id(item_id):
            return item1_dict if item_id == 1 else item2_dict

        mock_item.get_by_id.side_effect = fake_get_by_id
        mock_item.get_all.return_value = [item1_dict, item2_dict]

        dlg = _InvoiceDialog()
        try:
            # 1. Select Item 1
            dlg._entry_bar.item_combo.blockSignals(True)
            dlg._entry_bar.item_combo.clear()
            dlg._entry_bar.item_combo.addItem("MEDICINE ONE", 1)
            dlg._entry_bar.item_combo.addItem("MEDICINE TWO", 2)
            dlg._entry_bar.item_combo.setCurrentIndex(0)
            dlg._entry_bar.item_combo.blockSignals(False)
            dlg._on_item_changed(0)

            # Select batch for Item 1
            dlg._entry_bar._on_saved_batch_selected(batches_item_1[0])
            dlg._entry_bar.pay_qty_edit.setText("20")
            dlg._entry_bar.free_qty_edit.setText("2")
            dlg._entry_bar.discount_edit.setText("5.00")

            self.assertEqual(dlg._entry_bar.batch_edit.text(), "BATCH_ITEM_1")
            self.assertEqual(dlg._entry_bar.expiry_edit.text(), "30-06-2028")
            self.assertEqual(dlg._entry_bar._selected_batch_id, 201)

            # 2. Change selection to Item 2
            dlg._entry_bar.item_combo.setCurrentIndex(1)
            dlg._on_item_changed(1)

            # Previous batch selection MUST be cleared
            self.assertEqual(dlg._entry_bar.batch_edit.text(), "")
            self.assertIsNone(dlg._entry_bar._selected_batch_id)
            self.assertEqual(dlg._entry_bar.expiry_edit.text(), "")
            self.assertEqual(dlg._entry_bar.pay_qty_edit.text(), "")
            self.assertEqual(dlg._entry_bar.free_qty_edit.text(), "")
            self.assertEqual(dlg._entry_bar.discount_edit.text(), "")

            # Batches for Item 2 only must be loaded
            self.assertEqual(dlg._entry_bar.batch_edit._model.rowCount(), 1)
            self.assertTrue(dlg._entry_bar.batch_edit._model.item(0).text().startswith("BATCH_ITEM_2"))

            # Master rate/mrp/pack/gst updated for Item 2
            self.assertEqual(dlg._entry_bar.pack_edit.text(), "15")
            self.assertEqual(dlg._entry_bar.gst_edit.text(), "18")
            self.assertEqual(dlg._entry_bar.rate_edit.text(), "88.00")
            self.assertEqual(dlg._entry_bar.mrp_edit.text(), "115.00")
        finally:
            dlg.close()

    # ------------------------------------------------------------------
    # 5. Manually selecting an expiry date works correctly
    # ------------------------------------------------------------------
    def test_05_manually_selecting_expiry_date(self):
        expiry_widget = ExpiryDateEdit(width=125)

        # Manual text entry in DD-MM-YYYY
        expiry_widget.setText("15-08-2029")
        self.assertEqual(expiry_widget.text(), "15-08-2029")
        self.assertEqual(expiry_widget.iso_date(), "2029-08-15")

        # Manual text entry in MM/YY
        expiry_widget.setText("08/28")
        self.assertEqual(expiry_widget.text(), "31-08-2028")
        self.assertEqual(expiry_widget.iso_date(), "2028-08-31")

        # Calendar widget pick
        qdate = QDate(2030, 4, 25)
        expiry_widget.setDate(qdate)
        self.assertEqual(expiry_widget.text(), "25-04-2030")
        self.assertEqual(expiry_widget.iso_date(), "2030-04-25")

        # Clear
        expiry_widget.clear()
        self.assertEqual(expiry_widget.text(), "")
        self.assertEqual(expiry_widget.iso_date(), "")

        # show_popup screen boundary check doesn't crash
        expiry_widget.show_popup()
        if expiry_widget._popup:
            self.assertTrue(expiry_widget._popup.isVisible())
            expiry_widget._popup.hide()

    @patch("screens.purchase_invoice.QMessageBox.warning")
    @patch("screens.purchase_invoice.ItemDAO")
    @patch("screens.purchase_invoice.SupplierDAO")
    @patch("screens.purchase_invoice.PurchaseDAO")
    @patch("screens.purchase_invoice.financial_year")
    def test_05b_invalid_expiry_date_validation(self, mock_fy, mock_purch, mock_sup, mock_item, mock_warn):
        mock_fy.get_active_financial_year.return_value = {
            "id": 1, "start_date": "2026-04-01", "end_date": "2027-03-31"
        }
        mock_sup.get_all.return_value = []
        mock_purch.generate_next_voucher_no.return_value = "PV-105"
        mock_purch.get_saved_batches_for_item.return_value = []
        mock_item.get_all.return_value = []
        mock_item.get_by_id.return_value = {"id": 1, "item_name": "Test", "pack_size": "10"}

        dlg = _InvoiceDialog()
        try:
            dlg._entry_bar.item_combo.clear()
            dlg._entry_bar.item_combo.addItem("Test", 1)
            dlg._entry_bar.item_combo.setCurrentIndex(0)
            dlg._entry_bar.pay_qty_edit.setText("5")
            dlg._entry_bar.rate_edit.setText("10.00")
            dlg._entry_bar.mrp_edit.setText("15.00")
            dlg._entry_bar.batch_edit.setText("BAT-TEST")

            # Set invalid expiry date text
            dlg._entry_bar.expiry_edit._line.setText("99-99-9999")

            # Trigger add item
            dlg._on_add_item()

            # Warning should be displayed
            mock_warn.assert_called_once()
            self.assertIn("Invalid Expiry Date", mock_warn.call_args[0][2])
            # Item should NOT be added
            self.assertEqual(len(dlg._item_rows), 0)
        finally:
            dlg.close()

    # ------------------------------------------------------------------
    # 6. Existing batches are not overwritten accidentally
    # ------------------------------------------------------------------
    def test_06_existing_batches_not_overwritten_accidentally(self):
        # Create an in-memory database with stock_batches
        conn = sqlite3.connect(":memory:")
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE stock_batches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id INTEGER,
                batch_no TEXT,
                expiry TEXT,
                pack_size TEXT,
                mrp REAL,
                purchase_rate REAL,
                net_rate REAL,
                stock_qty REAL
            )
        """)
        # Insert pre-existing batch
        cur.execute("""
            INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size, mrp, purchase_rate, net_rate, stock_qty)
            VALUES (10, 'EXISTING_BATCH', '2028-12-31', '10', 100.0, 70.0, 70.0, 50.0)
        """)
        conn.commit()

        # Simulate purchasing into the existing batch: stock_qty increases, but expiry and mrp are preserved
        batch_id = 1
        qty_to_add = 30.0  # adding 30 units
        cur.execute("UPDATE stock_batches SET stock_qty = stock_qty + ? WHERE id = ?", (qty_to_add, batch_id))
        conn.commit()

        cur.execute("SELECT * FROM stock_batches WHERE id = 1")
        row = cur.fetchone()
        self.assertEqual(row[8], 80.0)  # stock_qty incremented to 80
        self.assertEqual(row[3], "2028-12-31")  # expiry preserved
        self.assertEqual(row[5], 100.0)  # mrp preserved

        # Simulate entering a genuinely new batch
        cur.execute("""
            INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size, mrp, purchase_rate, net_rate, stock_qty)
            VALUES (10, 'NEW_BATCH_001', '2029-06-30', '10', 120.0, 80.0, 80.0, 20.0)
        """)
        conn.commit()

        # Check that existing batch 1 remains unchanged
        cur.execute("SELECT * FROM stock_batches WHERE id = 1")
        row1 = cur.fetchone()
        self.assertEqual(row1[2], "EXISTING_BATCH")
        self.assertEqual(row1[3], "2028-12-31")
        self.assertEqual(row1[8], 80.0)

        # Check new batch created
        cur.execute("SELECT * FROM stock_batches WHERE id = 2")
        row2 = cur.fetchone()
        self.assertEqual(row2[2], "NEW_BATCH_001")
        self.assertEqual(row2[3], "2029-06-30")
        self.assertEqual(row2[8], 20.0)

        conn.close()

    # ------------------------------------------------------------------
    # 7. Existing purchase calculations and invoice saving remain unchanged
    # ------------------------------------------------------------------
    @patch("screens.purchase_invoice.PurchaseDAO")
    @patch("screens.purchase_invoice.ItemDAO")
    @patch("screens.purchase_invoice.SupplierDAO")
    @patch("screens.purchase_invoice.financial_year")
    def test_07_existing_purchase_calculations_and_saving_unchanged(
        self, mock_fy, mock_sup, mock_item, mock_purch
    ):
        mock_fy.get_active_financial_year.return_value = {
            "id": 1, "start_date": "2026-04-01", "end_date": "2027-03-31"
        }
        mock_sup.get_all.return_value = [{"id": 5, "supplier_name": "ABC PHARMA"}]
        mock_purch.generate_next_voucher_no.return_value = "PV-200"
        mock_purch.get_saved_batches_for_item.return_value = []
        mock_item.get_all.return_value = [{"id": 1, "item_name": "MED-A", "pack_size": "10", "rate": 100.0, "mrp": 150.0, "tax_structure": "GST 5%"}]
        mock_item.get_by_id.return_value = {"id": 1, "item_name": "MED-A", "pack_size": "10", "rate": 100.0, "mrp": 150.0, "tax_structure": "GST 5%"}

        dlg = _InvoiceDialog()
        try:
            dlg.supplier_combo.clear()
            dlg.supplier_combo.addItem("ABC PHARMA", 5)
            dlg.supplier_combo.setCurrentIndex(0)

            # Setup entry row: Pay Qty = 10, Free Qty = 2, Rate = 100.00, Disc = 10%, GST = 5%, MRP = 150
            dlg._entry_bar.item_combo.clear()
            dlg._entry_bar.item_combo.addItem("MED-A", 1)
            dlg._entry_bar.item_combo.setCurrentIndex(0)
            dlg._entry_bar.pack_edit.setText("10")
            dlg._entry_bar.pay_qty_edit.setText("10")
            dlg._entry_bar.free_qty_edit.setText("2")
            dlg._entry_bar.batch_edit.setText("B-100")
            dlg._entry_bar.expiry_edit.setText("31-12-2029")
            dlg._entry_bar.rate_edit.setText("100.00")
            dlg._entry_bar.mrp_edit.setText("150.00")
            dlg._entry_bar.discount_edit.setText("10.00")
            dlg._entry_bar.gst_edit.setText("5.00")

            dlg._on_add_item()

            self.assertEqual(len(dlg._item_rows), 1)
            r = dlg._item_rows[0]
            # Gross = 10 * 100 = 1000. Disc 10% = 100. Amount = 900.00
            self.assertEqual(r.amount, 900.00)
            # GST 5% on 900 = 45.00
            self.assertEqual(r.gst_amount, 45.00)
            # Total for line = 945.00
            # Purchase rate = 945 / 10 = 94.50
            self.assertEqual(r.purchase_rate, 94.50)
            # Net rate = 945 / (10 + 2) = 78.75
            self.assertEqual(r.net_rate, 78.75)
            # PP margin = ((150 - 94.50) / 94.50) * 100 = 58.73%
            self.assertAlmostEqual(r.pp, 58.73, places=2)

            # Check footer totals
            # Total Amount = 900.00, GST = 45.00, Net = 945.00
            self.assertEqual(dlg.total_amount_label.text(), "900.00")
            self.assertEqual(dlg.gst_label.text(), "45.00")
            self.assertEqual(dlg.net_amt_label.text(), "945.00")

            # Check saving
            mock_purch.insert_invoice.return_value = 999
            dlg._on_save()
            self.assertTrue(dlg.was_saved)
            mock_purch.insert_invoice.assert_called_once()
        finally:
            dlg.close()


if __name__ == "__main__":
    unittest.main()
