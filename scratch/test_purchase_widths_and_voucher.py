"""Targeted regression test for Purchase Invoice widths, text visibility, and Voucher No display."""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import unittest
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from screens.purchase_invoice import (
    _display_voucher_no,
    _InvoiceDialog,
    SearchableComboBox,
    _ItemEntryBar,
)
from database import financial_year

app = QApplication.instance() or QApplication(sys.argv)


class TestPurchaseWidthsAndVoucher(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Ensure active FY
        financial_year.ensure_default_financial_year()

    def test_01_display_voucher_no(self):
        self.assertEqual(_display_voucher_no("2026-2027-Credit-0251"), "251")
        self.assertEqual(_display_voucher_no("2026-2027-Credit-250"), "250")
        self.assertEqual(_display_voucher_no("2026-2027-Credit-252"), "252")
        self.assertEqual(_display_voucher_no("2026-2027-Cash-1"), "1")
        self.assertEqual(_display_voucher_no("PUR-0042"), "42")
        self.assertEqual(_display_voucher_no("999"), "999")
        self.assertEqual(_display_voucher_no(""), "")
        self.assertEqual(_display_voucher_no(None), "")

    def test_02_new_dialog_voucher_no_display(self):
        dlg = _InvoiceDialog()
        full = getattr(dlg, "_full_voucher_no", None)
        self.assertIsNotNone(full)
        self.assertIn("Credit-", full)
        displayed = dlg.voucher_no_edit.text()
        self.assertEqual(displayed, _display_voucher_no(full))
        self.assertTrue(displayed.isdigit())
        self.assertFalse(displayed.startswith("0"))
        self.assertEqual(dlg.voucher_no_edit.toolTip(), f"Full Voucher: {full}")
        dlg.close()

    def test_03_edit_dialog_voucher_no_display(self):
        dummy_invoice = {
            "id": 99999,
            "voucher_no": "2026-2027-Credit-0345",
            "voucher_date": "2026-05-10",
            "voucher_time": "11:20",
            "purchase_type": "Credit",
            "supplier_id": 1,
            "invoice_no": "INV-XYZ-88",
            "invoice_date": "2026-05-10",
            "invoice_net_amount": 500.0,
            "bill_discount": 0.0,
            "due_date": "2026-06-09",
            "debit_note_amount": 0.0,
            "other_amount": 0.0,
            "paid_amount": 0.0,
            "round_off": 0.0,
            "net_amount": 500.0,
            "remarks": "",
            "items": [],
        }
        dlg = _InvoiceDialog(invoice=dummy_invoice)
        self.assertEqual(getattr(dlg, "_full_voucher_no"), "2026-2027-Credit-0345")
        self.assertEqual(dlg.voucher_no_edit.text(), "345")
        self.assertEqual(dlg.voucher_no_edit.toolTip(), "Full Voucher: 2026-2027-Credit-0345")
        dlg.close()

    def test_04_control_widths(self):
        dlg = _InvoiceDialog()
        dlg.resize(1200, 720)
        dlg.show()
        app.processEvents()

        # Voucher No: 105 px
        self.assertEqual(dlg.voucher_no_edit.width(), 105)
        # Supplier combo: wide searchable input spanning cols 1-5 (~270-500 px)
        self.assertGreaterEqual(dlg.supplier_combo.width(), 270)
        self.assertLessEqual(dlg.supplier_combo.width(), 500)
        # Invoice No edit: 115 px
        self.assertEqual(dlg.invoice_no_edit.width(), 115)
        # Date fields: 128 px
        self.assertEqual(dlg.voucher_date.width(), 128)
        self.assertEqual(dlg.invoice_date.width(), 128)
        self.assertEqual(dlg.due_date.width(), 128)
        self.assertFalse(dlg.due_date.isVisible())
        # Time edit: 80 px
        self.assertEqual(dlg.voucher_time_edit.width(), 80)
        # Type combo: 112 px
        self.assertEqual(dlg.purchase_type_combo.width(), 112)
        # Bal label: 112 px (expanded from 80 px using space from removed Due Date)
        self.assertEqual(dlg.supplier_bal_label.width(), 112)
        # Inv amt edit: 115 px
        self.assertEqual(dlg.inv_net_amt_edit.width(), 115)
        # Bill discount edit: 125 px
        self.assertEqual(dlg.bill_discount_edit.width(), 125)

        # Item combo in entry bar: min_width=160 px
        self.assertGreaterEqual(dlg._entry_bar.item_combo.width(), 160)
        dlg.close()

    def test_05_searchable_combo_styling_and_selection(self):
        combo = SearchableComboBox(placeholder="Search medicine...")
        combo.populate([("Paracetamol 500mg Strip of 10 Tablets", 101), ("Amoxicillin 250mg", 102)])
        self.assertEqual(combo.currentIndex(), -1)
        self.assertEqual(combo.currentText(), "")

        # Select first item
        combo.setCurrentIndex(0)
        self.assertEqual(combo.currentText(), "Paracetamol 500mg Strip of 10 Tablets")
        line = combo.lineEdit()
        self.assertIsNotNone(line)
        # Cursor should be at 0 so long names show from the start
        self.assertEqual(line.cursorPosition(), 0)
        # Tooltip should contain full name
        self.assertEqual(line.toolTip(), "Paracetamol 500mg Strip of 10 Tablets")
        # Inner lineEdit stylesheet must NOT contain solid border or crushing padding
        self.assertIn("border: none", line.styleSheet())
        self.assertIn("background: transparent", line.styleSheet())
        combo.close()


if __name__ == "__main__":
    unittest.main()
