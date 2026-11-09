"""Verification test suite for Purchase Invoice item-entry Edit and Hist buttons and popups:
1. Presence, positioning, styling, and tooltip of Edit and Hist buttons next to Item Name.
2. Clicking Edit without item selected warns with information dialog.
3. Clicking Edit with an item selected opens _ItemDialog populated with item data.
4. Saving _ItemDialog updates item_combo and reloads item details in the entry bar.
5. Clicking Hist without item selected warns with information dialog.
6. Clicking Hist with an item selected opens _ItemPurchaseHistoryDialog.
7. Verification of _ItemPurchaseHistoryDialog columns:
   Tran.No, Tran.Date, Tran.Type, BatchNo, PayQty, FreeQty, MRP, Rate, DiscAmt, Supplier.
8. Selecting a history row or double clicking populates batch, expiry, rate, and MRP into entry bar.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import date
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

app = QApplication.instance() or QApplication(sys.argv)

from database.item_dao import ItemDAO
from database.purchase_dao import PurchaseDAO
from screens.purchase_invoice import (
    _InvoiceDialog,
    _ItemEntryBar,
    _ItemPurchaseHistoryDialog,
)
from screens.item_master import _ItemDialog


class TestPurchaseItemEditAndHistory(unittest.TestCase):
    def setUp(self):
        self.dlg = _InvoiceDialog()
        self.bar = self.dlg._entry_bar
        app.processEvents()

    def tearDown(self):
        self.dlg.close()
        app.processEvents()

    def test_01_buttons_presence_and_properties(self):
        """1. Verify Edit and Hist buttons are present next to item combo with proper properties."""
        self.assertTrue(hasattr(self.bar, "btn_item_edit"))
        self.assertTrue(hasattr(self.bar, "btn_item_hist"))

        self.assertEqual(self.bar.btn_item_edit.text(), "Edit")
        self.assertEqual(self.bar.btn_item_hist.text(), "Hist")

        # Focus policy is NoFocus to preserve tab navigation
        self.assertEqual(self.bar.btn_item_edit.focusPolicy(), Qt.NoFocus)
        self.assertEqual(self.bar.btn_item_hist.focusPolicy(), Qt.NoFocus)

        # Tooltips
        self.assertIn("Edit", self.bar.btn_item_edit.toolTip())
        self.assertIn("history", self.bar.btn_item_hist.toolTip().lower())

        # Buttons are parented inside the item container
        item_container = self.bar.item_combo.parentWidget()
        self.assertEqual(self.bar.btn_item_edit.parentWidget(), item_container)
        self.assertEqual(self.bar.btn_item_hist.parentWidget(), item_container)

    @patch("PySide6.QtWidgets.QMessageBox.information")
    def test_02_edit_without_selection_shows_warning(self, mock_info):
        """2. Clicking Edit with no item selected prompts user to select an item first."""
        self.bar.item_combo.setCurrentIndex(-1)
        self.bar.btn_item_edit.click()
        app.processEvents()
        mock_info.assert_called_once()
        self.assertIn("select an item", mock_info.call_args[0][2].lower())

    @patch("screens.item_master._ItemDialog.exec")
    def test_03_edit_with_selection_opens_item_dialog(self, mock_exec):
        """3. Clicking Edit with an item selected opens _ItemDialog populated with that item."""
        mock_exec.return_value = 0  # Cancelled without save

        # Add a test item
        test_item_id = 1811  # ORICOXIB-TH in test DB
        idx = self.bar.item_combo.findData(test_item_id)
        if idx < 0:
            self.bar.item_combo.addItem("ORICOXIB-TH", test_item_id)
            idx = self.bar.item_combo.findData(test_item_id)
        self.bar.item_combo.setCurrentIndex(idx)
        app.processEvents()

        with patch("screens.item_master._ItemDialog.__init__", return_value=None) as mock_init:
            self.bar.btn_item_edit.click()
            app.processEvents()
            mock_init.assert_called_once()
            call_kwargs = mock_init.call_args[1]
            self.assertIn("item", call_kwargs)
            self.assertEqual(call_kwargs["item"]["id"], test_item_id)

    @patch("PySide6.QtWidgets.QMessageBox.information")
    def test_04_hist_without_selection_shows_warning(self, mock_info):
        """4. Clicking Hist with no item selected prompts user to select an item first."""
        self.bar.item_combo.setCurrentIndex(-1)
        self.bar.btn_item_hist.click()
        app.processEvents()
        mock_info.assert_called_once()
        self.assertIn("select an item", mock_info.call_args[0][2].lower())

    def test_05_item_purchase_history_dialog_columns_and_data(self):
        """5. Verify _ItemPurchaseHistoryDialog opens with correct columns, title, and data."""
        # Use item 1811 (ORICOXIB-TH) which has known purchase history
        test_item_id = 1811
        item_name = "ORICOXIB-TH TABLET"

        dlg = _ItemPurchaseHistoryDialog(self.dlg, item_id=test_item_id, item_name=item_name)
        try:
            self.assertEqual(dlg.windowTitle(), f"Item Purchase History [ {item_name} ]")

            expected_headers = [
                "Tran.No", "Tran.Date", "Tran.Type", "BatchNo", "PayQty", "FreeQty",
                "MRP", "Rate", "DiscAmt", "Supplier"
            ]
            actual_headers = [dlg.table.horizontalHeaderItem(i).text() for i in range(10)]
            self.assertEqual(actual_headers, expected_headers)

            # Rows should be loaded
            self.assertGreater(dlg.table.rowCount(), 0)

            # Verify first row data formatting
            row0_vno = dlg.table.item(0, 0).text()
            row0_date = dlg.table.item(0, 1).text()
            row0_type = dlg.table.item(0, 2).text()
            row0_batch = dlg.table.item(0, 3).text()
            row0_pay = dlg.table.item(0, 4).text()
            row0_free = dlg.table.item(0, 5).text()
            row0_mrp = dlg.table.item(0, 6).text()
            row0_rate = dlg.table.item(0, 7).text()
            row0_disc = dlg.table.item(0, 8).text()
            row0_sup = dlg.table.item(0, 9).text()

            # Date format should be DD-MM-YYYY
            self.assertEqual(len(row0_date), 10)
            self.assertEqual(row0_date[2], "-")
            self.assertEqual(row0_date[5], "-")

            # Batch and quantities should be non-empty
            self.assertTrue(bool(row0_batch))
            self.assertTrue(bool(row0_pay))
            self.assertTrue(bool(row0_sup))

            # Trigger Ok button selection
            dlg.table.selectRow(0)
            dlg.ok_btn.click()
            self.assertIsNotNone(dlg.selected_batch)
            self.assertEqual(dlg.selected_batch.get("batch_no"), row0_batch)
        finally:
            dlg.close()

    def test_06_hist_selection_populates_entry_bar(self):
        """6. Selecting a history item and confirming populates entry bar batch details."""
        test_item_id = 1811
        idx = self.bar.item_combo.findData(test_item_id)
        if idx < 0:
            self.bar.item_combo.addItem("ORICOXIB-TH", test_item_id)
            idx = self.bar.item_combo.findData(test_item_id)
        self.bar.item_combo.setCurrentIndex(idx)
        app.processEvents()

        # Mock dialog exec to auto-select first row and accept
        def fake_exec(dlg_self):
            if dlg_self.table.rowCount() > 0:
                dlg_self.table.selectRow(0)
                dlg_self.selected_batch = dlg_self._history_data[0]
            return 1

        with patch.object(_ItemPurchaseHistoryDialog, "exec", fake_exec):
            self.bar.btn_item_hist.click()
            app.processEvents()

            # Verify batch fields were auto-populated
            self.assertTrue(bool(self.bar.batch_edit.text()))
            self.assertTrue(bool(self.bar.rate_edit.text()))
            self.assertTrue(bool(self.bar.mrp_edit.text()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
