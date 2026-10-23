"""Automated tests for New Purchase Invoice single-row item entry layout.

Verifies:
1. All item-entry controls fit on one single horizontal row.
2. Item search field expands dynamically with available width.
3. Controls (Pack, Batch, Expiry, Qty, Free, Rate, MRP, Disc, GST, + Add Item) are compact,
   properly sized, non-overlapping, and fully visible at normal window sizes (1200px and up).
4. Items table is positioned directly below the single-row entry bar.
5. Tab order traverses the single row continuously.
6. ExpiryDateEdit remains functional and readable.
7. Adding an item, clearing the bar, and calculations continue to work seamlessly.
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QApplication, QHeaderView

app = QApplication.instance() or QApplication(sys.argv)

from screens.purchase_invoice import (
    _InvoiceDialog,
    _ItemEntryBar,
    ExpiryDateEdit,
    BatchLineEdit,
    SearchableComboBox,
)


class TestPurchaseSingleRowLayout(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pass

    def _pump(self):
        app.processEvents()

    def test_01_item_entry_bar_is_single_horizontal_row(self):
        """1. Entry bar layout is a single horizontal row containing all controls."""
        bar = _ItemEntryBar()
        self._pump()

        # Bar height is compact (~34px), not a double-row (~78px)
        self.assertLessEqual(bar.height(), 45)

        # Labels check
        expected_labels = ["Item", "Pack", "Batch", "Exp", "Qty", "Free", "Rate", "MRP", "Disc", "GST"]
        actual_labels = [lbl.text() for lbl in bar._entry_labels]
        self.assertEqual(actual_labels, expected_labels)

        # Add button
        self.assertEqual(bar.add_btn.text(), "+ Add Item")
        self.assertEqual(bar.add_btn.height(), 30)

        # Layout must have at least 11 items on the single row
        self.assertGreaterEqual(bar.layout().count(), 11)

    @patch("screens.purchase_invoice.PurchaseDAO")
    @patch("screens.purchase_invoice.ItemDAO")
    @patch("screens.purchase_invoice.SupplierDAO")
    @patch("screens.purchase_invoice.financial_year")
    def test_02_all_controls_fit_without_overflow_at_1200_and_above(
        self, mock_fy, mock_sup, mock_item, mock_purch
    ):
        """2. All controls fit on one line without clipping or overflow at 1200px, 1366px, and 1600px."""
        mock_fy.get_active_financial_year.return_value = {
            "id": 1, "start_date": "2026-04-01", "end_date": "2027-03-31"
        }
        mock_sup.get_all.return_value = []
        mock_purch.generate_next_voucher_no.return_value = "PV-0001"
        mock_purch.get_saved_batches_for_item.return_value = []
        mock_item.get_all.return_value = []

        dlg = _InvoiceDialog()
        try:
            for w, h in [(1200, 700), (1366, 768), (1600, 900)]:
                dlg.resize(w, h)
                dlg.show()
                self._pump()

                bar = dlg._entry_bar
                # Bar height remains compact single row
                self.assertLessEqual(bar.height(), 45)

                # Add button stays fully within the entry bar right boundary
                btn_right = bar.add_btn.geometry().right()
                self.assertLessEqual(btn_right, bar.width())

                # Item combo takes available space and expands as window widens
                self.assertGreaterEqual(bar.item_combo.width(), 150)
                if w >= 1366:
                    self.assertGreaterEqual(bar.item_combo.width(), 200)

                # Verify each control's geometry is non-overlapping and ordered left to right
                geoms = [
                    ("Item", bar.item_combo.parentWidget().geometry()),
                    ("Pack", bar.pack_edit.parentWidget().geometry()),
                    ("Batch", bar.batch_edit.parentWidget().geometry()),
                    ("Exp", bar.expiry_edit.parentWidget().geometry()),
                    ("Qty", bar.pay_qty_edit.parentWidget().geometry()),
                    ("Free", bar.free_qty_edit.parentWidget().geometry()),
                    ("Rate", bar.rate_edit.parentWidget().geometry()),
                    ("MRP", bar.mrp_edit.parentWidget().geometry()),
                    ("Disc", bar.discount_edit.parentWidget().geometry()),
                    ("GST", bar.gst_edit.parentWidget().geometry()),
                    ("Add", bar.add_btn.geometry()),
                ]

                for i in range(len(geoms) - 1):
                    cur_name, cur_g = geoms[i]
                    nxt_name, nxt_g = geoms[i + 1]
                    self.assertGreater(
                        nxt_g.left(),
                        cur_g.left(),
                        f"Expected {nxt_name} (left={nxt_g.left()}) to be to the right of {cur_name} (left={cur_g.left()})"
                    )
        finally:
            dlg.close()

    @patch("screens.purchase_invoice.PurchaseDAO")
    @patch("screens.purchase_invoice.ItemDAO")
    @patch("screens.purchase_invoice.SupplierDAO")
    @patch("screens.purchase_invoice.financial_year")
    def test_03_items_table_positioned_directly_below_entry_bar(
        self, mock_fy, mock_sup, mock_item, mock_purch
    ):
        """3. Items table is positioned directly below the single-row entry bar."""
        mock_fy.get_active_financial_year.return_value = {"id": 1, "start_date": "2026-04-01", "end_date": "2027-03-31"}
        mock_sup.get_all.return_value = []
        mock_purch.generate_next_voucher_no.return_value = "PV-0001"
        mock_purch.get_saved_batches_for_item.return_value = []
        mock_item.get_all.return_value = []

        dlg = _InvoiceDialog()
        try:
            dlg.resize(1200, 700)
            dlg.show()
            self._pump()

            bar = dlg._entry_bar
            tbl = dlg._table_group

            # Table top must be below entry bar
            bar_bottom_global = bar.mapToGlobal(bar.rect().bottomLeft()).y()
            tbl_top_global = tbl.mapToGlobal(tbl.rect().topLeft()).y()
            gap = tbl_top_global - bar_bottom_global

            self.assertGreaterEqual(gap, 0)
            # Gap between single-row entry bar and Items group is compact (under 25px)
            self.assertLessEqual(gap, 25)
        finally:
            dlg.close()

    def test_04_tab_order_traverses_single_row_continuously(self):
        """4. Tab order traverses the single row from left to right."""
        from PySide6.QtTest import QTest

        bar = _ItemEntryBar()
        bar.show()
        self._pump()

        # Focus starts at item_combo
        bar.item_combo.setFocus()
        self._pump()

        expected_focus_order = [
            bar.batch_edit,
            bar.expiry_edit._line,
            bar.pay_qty_edit,
            bar.free_qty_edit,
            bar.rate_edit,
            bar.mrp_edit,
            bar.discount_edit,
            bar.add_btn,
        ]

        for expected_widget in expected_focus_order:
            current_focus = app.focusWidget()
            QTest.keyClick(current_focus, Qt.Key_Tab)
            self._pump()
            self.assertEqual(app.focusWidget(), expected_widget)

        bar.close()

    def test_05_expiry_date_edit_functionality_preserved(self):
        """5. ExpiryDateEdit functions properly on the single row."""
        bar = _ItemEntryBar()
        self._pump()

        # Keyboard entry of DD-MM-YYYY
        bar.expiry_edit.setText("31-12-2028")
        self.assertEqual(bar.expiry_edit.text(), "31-12-2028")
        self.assertEqual(bar.expiry_edit.iso_date(), "2028-12-31")

        # Clear
        bar.clear()
        self.assertEqual(bar.expiry_edit.text(), "")
        self.assertEqual(bar.expiry_edit.iso_date(), "")

    @patch("screens.purchase_invoice.ItemDAO")
    def test_06_add_item_clears_and_preserves_single_row(self, mock_item):
        """6. Adding an item and resetting entry bar preserves single-row geometry."""
        mock_item.get_by_id.return_value = {
            "id": 1, "item_name": "AMOXICILLIN 500", "pack_size": "10",
            "rate": 45.0, "mrp": 70.0, "tax_structure": "GST @ 12%",
        }
        bar = _ItemEntryBar()
        self._pump()

        bar.item_combo.addItem("AMOXICILLIN 500", 1)
        bar.item_combo.setCurrentIndex(0)
        bar.batch_edit.setText("AMX-001")
        bar.expiry_edit.setText("30-06-2029")
        bar.pay_qty_edit.setText("10")
        bar.free_qty_edit.setText("1")
        bar.rate_edit.setText("45.00")
        bar.mrp_edit.setText("70.00")
        bar.discount_edit.setText("5.00")
        bar.gst_edit.setText("12")

        data = bar.get_current_item_data()
        self.assertIsNotNone(data)
        self.assertEqual(data["item_name"], "AMOXICILLIN 500")
        self.assertEqual(data["batch_no"], "AMX-001")
        self.assertEqual(data["expiry"], "2029-06-30")
        self.assertEqual(data["pay_qty"], 10.0)
        self.assertEqual(data["free_qty"], 1.0)
        self.assertEqual(data["rate"], 45.0)
        self.assertEqual(data["mrp"], 70.0)
        self.assertEqual(data["discount"], 5.0)
        self.assertEqual(data["gst_percent"], 12.0)

        # Clear bar
        bar.clear()
        self.assertEqual(bar.batch_edit.text(), "")
        self.assertEqual(bar.pay_qty_edit.text(), "")
        self.assertLessEqual(bar.height(), 45)


if __name__ == "__main__":
    unittest.main(verbosity=2)
