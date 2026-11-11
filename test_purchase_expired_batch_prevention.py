"""Comprehensive regression and unit tests for New Purchase Invoice:
Prevention of automatic selection of expired batches, invoice-date relative expiry validation,
batch dropdown behavior, and medicine-change field resetting.

Tests all 9 prompt requirements:
1. When a medicine is selected, do not automatically select any existing batch.
2. Keep the Batch field empty until the user explicitly selects a batch or enters a new batch number.
3. Never automatically select an expired batch for a new purchase when its expiry date is before the invoice date.
4. If the user opens the batch dropdown, show the batch numbers clearly. Display expiry dates as supporting information, but do not automatically select an item.
5. When the user manually selects a batch, update the expiry field according to that selection.
6. Allow the user to enter a new batch number and select its expiry date for newly purchased stock.
7. Compare expiry against the invoice date, not blindly against the computer date.
8. If the user manually selects or enters an expired batch (expiry date < invoice date), show a clear warning message and prevent saving/adding invalid new purchase stock.
9. When changing medicines, reset the previous medicine's batch and expiry values (plus rate, mrp, pay_qty, free_qty, discount) so stale data never carries over.
"""

import os
import sys
import unittest
from datetime import date
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QDate, QEvent, QModelIndex, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

app = QApplication.instance() or QApplication(sys.argv)

from screens.purchase_invoice import (
    BatchCompleter,
    BatchLineEdit,
    ExpiryDateEdit,
    _InvoiceDialog,
    _InvoiceItemRow,
    _ItemEntryBar,
    format_expiry_display,
    normalize_expiry_db,
    parse_expiry_to_date,
)


class TestPurchaseExpiredBatchPrevention(unittest.TestCase):

    def setUp(self):
        # Sample batches for testing:
        # One expired relative to invoice date 2026-10-23 (LN24019: 2026-04-30)
        # One valid unexpired (BAT2028: 2028-05-31)
        # One near future unexpired (LN2612: 2026-12-31)
        self.sample_batches = [
            {
                "id": 1001,
                "batch_no": "BAT2028",
                "expiry": "2028-05-31",
                "rate": 240.0,
                "mrp": 320.0,
                "pack_size": "15",
                "gst_percent": 12.0,
            },
            {
                "id": 1002,
                "batch_no": "LN2612",
                "expiry": "2026-12-31",
                "rate": 235.0,
                "mrp": 310.0,
                "pack_size": "15",
                "gst_percent": 12.0,
            },
            {
                "id": 1003,
                "batch_no": "LN24019",
                "expiry": "2026-04-30",
                "rate": 235.93,
                "mrp": 348.0,
                "pack_size": "15",
                "gst_percent": 18.0,
            },
        ]

    # ------------------------------------------------------------------
    # Req 1, 2, 3: Medicine selection leaves batch strictly empty
    # ------------------------------------------------------------------
    @patch("screens.purchase_invoice.ItemDAO")
    @patch("screens.purchase_invoice.PurchaseDAO")
    @patch("screens.purchase_invoice.SupplierDAO")
    @patch("screens.purchase_invoice.financial_year")
    def test_01_selecting_medicine_leaves_batch_empty_and_does_not_select_expired(
        self, mock_fy, mock_sup, mock_purch, mock_item
    ):
        mock_fy.get_active_financial_year.return_value = {
            "id": 1, "start_date": "2026-04-01", "end_date": "2027-03-31"
        }
        mock_sup.get_all.return_value = []
        mock_purch.generate_next_voucher_no.return_value = "PV-101"
        mock_purch.get_saved_batches_for_item.return_value = self.sample_batches
        item_data = {
            "id": 1843,
            "item_name": "CORCIUM FIT",
            "pack_size": "15",
            "rate": 247.24,
            "mrp": 324.50,
            "tax_structure": "GST 12%",
        }
        mock_item.get_all.return_value = [item_data]
        mock_item.get_by_id.return_value = item_data

        dlg = _InvoiceDialog()
        try:
            # Set invoice date to 2026-10-23
            dlg.invoice_date.setDate(QDate(2026, 10, 23))

            # Select CORCIUM FIT
            dlg._entry_bar.item_combo.blockSignals(True)
            dlg._entry_bar.item_combo.clear()
            dlg._entry_bar.item_combo.addItem("CORCIUM FIT", 1843)
            dlg._entry_bar.item_combo.setCurrentIndex(0)
            dlg._entry_bar.item_combo.blockSignals(False)
            dlg._on_item_changed(0)

            # 1 & 2: Batch field must remain strictly empty
            self.assertEqual(dlg._entry_bar.batch_edit.text(), "")
            # 3: Expired batch LN24019 is NOT selected
            self.assertNotEqual(dlg._entry_bar.batch_edit.text(), "LN24019")
            self.assertEqual(dlg._entry_bar.expiry_edit.text(), "")
            self.assertFalse(dlg._entry_bar.expiry_edit.isReadOnly())
            self.assertEqual(dlg._entry_bar._selected_batch_no, "")
            self.assertIsNone(dlg._entry_bar._selected_batch_id)
        finally:
            dlg.close()

    # ------------------------------------------------------------------
    # Req 4: Dropdown shows batch with supporting expiry, does not pre-select
    # ------------------------------------------------------------------
    def test_02_dropdown_displays_supporting_expiry_and_no_auto_selection(self):
        edit = BatchLineEdit("Batch", 130)
        inv_date = date(2026, 10, 23)
        edit.set_batches(self.sample_batches, invoice_date=inv_date)

        # 3 batches in model
        self.assertEqual(edit._model.rowCount(), 3)

        # Item 0 (BAT2028 - unexpired): shows batch with supporting expiry
        item0 = edit._model.item(0)
        self.assertTrue(item0.text().startswith("BAT2028"))
        self.assertIn("Exp: 31-05-2028", item0.text())
        self.assertNotIn("Expired", item0.text())

        # Item 2 (LN24019 - expired on 2026-10-23): shows batch with supporting expiry and Expired tag
        item2 = edit._model.item(2)
        self.assertTrue(item2.text().startswith("LN24019"))
        self.assertIn("Exp: 30-04-2026", item2.text())
        self.assertIn("Expired", item2.text())

        # Opening popup does not automatically pre-select any item
        edit.show()
        QTest.mouseClick(edit, Qt.LeftButton)
        popup = edit._completer.popup()
        self.assertEqual(popup.currentIndex().row(), -1)

    # ------------------------------------------------------------------
    # Req 5: Manually selecting a valid batch populates fields
    # ------------------------------------------------------------------
    def test_03_manually_selecting_valid_batch_populates_fields(self):
        bar = _ItemEntryBar()
        bar.get_invoice_date_fn = lambda: date(2026, 10, 23)
        bar.batch_edit.set_batches(self.sample_batches, invoice_date=date(2026, 10, 23))

        valid_batch = self.sample_batches[0]  # BAT2028, Exp 2028-05-31
        bar._on_saved_batch_selected(valid_batch)

        self.assertEqual(bar.batch_edit.text(), "BAT2028")
        self.assertEqual(bar.expiry_edit.text(), "31-05-2028")
        self.assertEqual(bar.rate_edit.text(), "240.00")
        self.assertEqual(bar.mrp_edit.text(), "320.00")
        self.assertEqual(bar._selected_batch_id, 1001)
        self.assertTrue(bar.expiry_edit.isReadOnly())

    # ------------------------------------------------------------------
    # Req 6: Entering a new batch number and selecting expiry works
    # ------------------------------------------------------------------
    @patch("screens.purchase_invoice.ItemDAO")
    @patch("screens.purchase_invoice.PurchaseDAO")
    @patch("screens.purchase_invoice.SupplierDAO")
    @patch("screens.purchase_invoice.financial_year")
    def test_04_entering_new_batch_number_and_expiry_allows_addition(
        self, mock_fy, mock_sup, mock_purch, mock_item
    ):
        mock_fy.get_active_financial_year.return_value = {
            "id": 1, "start_date": "2026-04-01", "end_date": "2027-03-31"
        }
        mock_sup.get_all.return_value = []
        mock_purch.generate_next_voucher_no.return_value = "PV-102"
        mock_purch.get_saved_batches_for_item.return_value = self.sample_batches
        item_data = {
            "id": 50,
            "item_name": "AMOXICILLIN 500",
            "pack_size": "10",
            "rate": 55.0,
            "mrp": 80.0,
            "tax_structure": "GST 12%",
        }
        mock_item.get_all.return_value = [item_data]
        mock_item.get_by_id.return_value = item_data

        dlg = _InvoiceDialog()
        try:
            dlg.invoice_date.setDate(QDate(2026, 10, 23))
            dlg._entry_bar.item_combo.clear()
            dlg._entry_bar.item_combo.addItem("AMOXICILLIN 500", 50)
            dlg._entry_bar.item_combo.setCurrentIndex(0)
            dlg._on_item_changed(0)

            # Type a brand new batch number
            dlg._entry_bar.batch_edit.setText("BRANDNEW99")
            dlg._entry_bar.expiry_edit.setText("31-12-2028")
            dlg._entry_bar.pay_qty_edit.setText("10")
            dlg._entry_bar.rate_edit.setText("55.00")
            dlg._entry_bar.mrp_edit.setText("80.00")

            initial_row_count = len(dlg._item_rows)
            dlg._on_add_item()

            self.assertEqual(len(dlg._item_rows), initial_row_count + 1)
            row = dlg._item_rows[-1]
            self.assertEqual(row.batch_no, "BRANDNEW99")
            self.assertEqual(row.expiry, "2028-12-31")
            self.assertEqual(row.pay_qty, 10.0)
        finally:
            dlg.close()

    # ------------------------------------------------------------------
    # Req 7 & 8: Expiry evaluated against invoice date (not system date)
    #            Expired batch triggers warning and prevents addition
    # ------------------------------------------------------------------
    @patch("screens.purchase_invoice.QMessageBox.warning")
    def test_05_selecting_expired_batch_relative_to_invoice_date_warns_and_rejects(
        self, mock_warn
    ):
        bar = _ItemEntryBar()
        # Invoice date is 2026-10-23
        bar.get_invoice_date_fn = lambda: date(2026, 10, 23)

        # Batch LN24019 expired on 2026-04-30
        expired_batch = self.sample_batches[2]
        bar._on_saved_batch_selected(expired_batch)

        # Warning was shown
        self.assertTrue(mock_warn.called)
        call_args = mock_warn.call_args[0]
        self.assertIn("Expired", call_args[1])
        self.assertIn("LN24019", call_args[2])
        self.assertIn("23-10-2026", call_args[2])

        # Batch and expiry remain cleared and unlocked
        self.assertEqual(bar.batch_edit.text(), "")
        self.assertEqual(bar.expiry_edit.text(), "")
        self.assertEqual(bar._selected_batch_no, "")
        self.assertIsNone(bar._selected_batch_id)
        self.assertFalse(bar.expiry_edit.isReadOnly())

    # ------------------------------------------------------------------
    # Req 7 & 8: Manually typed expired batch is blocked on Add Item
    # ------------------------------------------------------------------
    @patch("screens.purchase_invoice.QMessageBox.warning")
    @patch("screens.purchase_invoice.ItemDAO")
    @patch("screens.purchase_invoice.PurchaseDAO")
    @patch("screens.purchase_invoice.SupplierDAO")
    @patch("screens.purchase_invoice.financial_year")
    def test_06_manually_entered_expired_batch_blocked_on_add_item(
        self, mock_fy, mock_sup, mock_purch, mock_item, mock_warn
    ):
        mock_fy.get_active_financial_year.return_value = {
            "id": 1, "start_date": "2026-04-01", "end_date": "2027-03-31"
        }
        mock_sup.get_all.return_value = []
        mock_purch.generate_next_voucher_no.return_value = "PV-103"
        mock_purch.get_saved_batches_for_item.return_value = []
        item_data = {
            "id": 99,
            "item_name": "TEST MED",
            "pack_size": "10",
            "rate": 50.0,
            "mrp": 75.0,
            "tax_structure": "GST 12%",
        }
        mock_item.get_all.return_value = [item_data]
        mock_item.get_by_id.return_value = item_data

        dlg = _InvoiceDialog()
        try:
            # Invoice date: 23-10-2026
            dlg.invoice_date.setDate(QDate(2026, 10, 23))
            dlg._entry_bar.item_combo.clear()
            dlg._entry_bar.item_combo.addItem("TEST MED", 99)
            dlg._entry_bar.item_combo.setCurrentIndex(0)
            dlg._on_item_changed(0)

            # Enter expired batch: 30-04-2026 (prior to 23-10-2026)
            dlg._entry_bar.batch_edit.setText("LN24019")
            dlg._entry_bar.expiry_edit.setText("30-04-2026")
            dlg._entry_bar.pay_qty_edit.setText("5")

            dlg._on_add_item()

            # Must NOT be added to table
            self.assertEqual(len(dlg._item_rows), 0)
            # Warning must be shown
            self.assertTrue(mock_warn.called)
            call_text = str(mock_warn.call_args)
            self.assertIn("Expired", call_text)
            self.assertIn("23-10-2026", call_text)
        finally:
            dlg.close()

    # ------------------------------------------------------------------
    # Req 8: Saving invoice blocks expired batch rows
    # ------------------------------------------------------------------
    @patch("screens.purchase_invoice.QMessageBox.warning")
    @patch("screens.purchase_invoice.SupplierDAO")
    @patch("screens.purchase_invoice.PurchaseDAO")
    @patch("screens.purchase_invoice.financial_year")
    def test_07_saving_invoice_blocks_expired_batch(
        self, mock_fy, mock_purch, mock_sup, mock_warn
    ):
        mock_fy.get_active_financial_year.return_value = {
            "id": 1, "start_date": "2026-04-01", "end_date": "2027-03-31"
        }
        mock_sup.get_all.return_value = [{"id": 1, "supplier_name": "SUPPLIER A"}]
        mock_sup.get_by_id.return_value = {"id": 1, "supplier_name": "SUPPLIER A", "credit_period": 30}
        mock_purch.generate_next_voucher_no.return_value = "PV-104"

        dlg = _InvoiceDialog()
        try:
            dlg.invoice_date.setDate(QDate(2026, 10, 23))
            dlg.supplier_combo.clear()
            dlg.supplier_combo.addItem("SUPPLIER A", 1)
            dlg.supplier_combo.setCurrentIndex(0)
            dlg.voucher_no_edit.setText("PV-104")

            # Manually append a row that is expired on 2026-10-23
            row = _InvoiceItemRow(
                item_id=1,
                item_name="EXPIRED ITEM",
                pack_size="10",
                pay_qty=10,
                free_qty=0,
                batch_no="OLD_BATCH",
                expiry="2026-04-30",
                rate=50.0,
                mrp=75.0,
                discount=0.0,
                gst_percent=12.0,
                amount=500.0,
                gst_amount=60.0,
                purchase_rate=56.0,
                net_rate=56.0,
                pp=25.0,
            )
            dlg._item_rows.append(row)

            dlg._on_save()

            # Must NOT save and must warn
            self.assertFalse(dlg.was_saved)
            self.assertFalse(mock_purch.insert_invoice.called)
            self.assertTrue(mock_warn.called)
        finally:
            dlg.close()

    # ------------------------------------------------------------------
    # Req 9: Changing medicines clears batch, expiry, rate, mrp, qty, etc.
    # ------------------------------------------------------------------
    @patch("screens.purchase_invoice.ItemDAO")
    @patch("screens.purchase_invoice.PurchaseDAO")
    @patch("screens.purchase_invoice.SupplierDAO")
    @patch("screens.purchase_invoice.financial_year")
    def test_08_changing_medicines_resets_all_stale_data(
        self, mock_fy, mock_sup, mock_purch, mock_item
    ):
        mock_fy.get_active_financial_year.return_value = {
            "id": 1, "start_date": "2026-04-01", "end_date": "2027-03-31"
        }
        mock_sup.get_all.return_value = []
        mock_purch.generate_next_voucher_no.return_value = "PV-105"

        item1 = {
            "id": 1,
            "item_name": "MEDICINE A",
            "pack_size": "10",
            "rate": 45.0,
            "mrp": 65.0,
            "tax_structure": "GST 12%",
        }
        item2 = {
            "id": 2,
            "item_name": "MEDICINE B",
            "pack_size": "20",
            "rate": 90.0,
            "mrp": 140.0,
            "tax_structure": "GST 18%",
        }

        mock_item.get_all.return_value = [item1, item2]
        mock_item.get_by_id.side_effect = lambda i: item1 if i == 1 else item2
        mock_purch.get_saved_batches_for_item.return_value = []

        dlg = _InvoiceDialog()
        try:
            dlg.invoice_date.setDate(QDate(2026, 10, 23))

            # Select Item 1 and enter fields
            dlg._entry_bar.item_combo.clear()
            dlg._entry_bar.item_combo.addItem("MEDICINE A", 1)
            dlg._entry_bar.item_combo.addItem("MEDICINE B", 2)
            dlg._entry_bar.item_combo.setCurrentIndex(0)
            dlg._on_item_changed(0)

            dlg._entry_bar.batch_edit.setText("B_ITEM1")
            dlg._entry_bar.expiry_edit.setText("31-12-2028")
            dlg._entry_bar.pay_qty_edit.setText("15")
            dlg._entry_bar.free_qty_edit.setText("2")
            dlg._entry_bar.discount_edit.setText("5.0")

            # Now switch to Item 2
            dlg._entry_bar.item_combo.setCurrentIndex(1)
            dlg._on_item_changed(1)

            # All previous medicine fields must be reset:
            self.assertEqual(dlg._entry_bar.batch_edit.text(), "")
            self.assertEqual(dlg._entry_bar.expiry_edit.text(), "")
            self.assertEqual(dlg._entry_bar.pay_qty_edit.text(), "")
            self.assertEqual(dlg._entry_bar.free_qty_edit.text(), "")
            self.assertEqual(dlg._entry_bar.discount_edit.text(), "")
            self.assertEqual(dlg._entry_bar._selected_batch_no, "")
            self.assertIsNone(dlg._entry_bar._selected_batch_id)
            self.assertFalse(dlg._entry_bar.expiry_edit.isReadOnly())

            # Item 2 master details loaded
            self.assertEqual(dlg._entry_bar.pack_edit.text(), "20")
            self.assertEqual(dlg._entry_bar.gst_edit.text(), "18")
            self.assertEqual(dlg._entry_bar.rate_edit.text(), "90.00")
            self.assertEqual(dlg._entry_bar.mrp_edit.text(), "140.00")
        finally:
            dlg.close()


if __name__ == "__main__":
    unittest.main()
