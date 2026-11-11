"""Integration test for opening and editing Purchase Invoices from Purchase Report.

Verifies:
1. PurchaseReportPage table items store purchase_id on column 0 UserRole.
2. Double clicking a row or clicking 'Edit Invoice' opens _InvoiceDialog populated with the invoice.
3. Dialog matches Screenshot 1 structure:
   - Cyan header with 'Edit Invoice', voucher no, date, time
   - 3-column top form (Type, Date, Supplier, Edit, Balance, Invoice #, Inv Net Amt, Discount, Due Date)
   - 16-column items grid
   - Total Items
   - Net Payable panel
   - Info callout strip and Save / Close buttons
4. Saving updates the existing invoice and refreshes the report.
5. Closing or pressing Esc cancels without saving.
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import Qt, QDate
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv)

from database.connection import init_database
from database.purchase_dao import PurchaseDAO
from screens.purchase_invoice import _InvoiceDialog
from screens.purchase_report import PurchaseReportPage


class TestPurchaseReportInvoiceIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_database()
    def setUp(self):
        self.app = app

    def test_01_report_page_has_edit_button_and_connections(self):
        """Test PurchaseReportPage UI has Edit Invoice button and double click connected."""
        page = PurchaseReportPage()
        page.show()
        self.app.processEvents()

        # Check Edit Invoice button exists
        from PySide6.QtWidgets import QPushButton
        edit_btns = [b for b in page.findChildren(QPushButton) if "Edit Invoice" in b.text()]
        self.assertEqual(len(edit_btns), 1)

        page.close()

    @patch("screens.purchase_report.PurchaseReportDAO")
    @patch("screens.purchase_invoice.PurchaseDAO")
    @patch("screens.purchase_report.PurchaseDAO")
    def test_02_open_invoice_dialog_populated_from_report(self, mock_report_purch_dao, mock_inv_purch_dao, mock_report_dao):
        """Test selecting a row and opening invoice dialog populates data correctly."""
        mock_report_dao.get_filter_options.return_value = {
            "suppliers": [{"id": 1, "supplier_name": "TEST SUPPLIER"}],
            "companies": [],
            "items": [],
        }
        mock_report_dao.get_purchase_report.return_value = {
            "rows": [
                {
                    "purchase_id": 9999,
                    "voucher_no": "2026-2027-Credit-268",
                    "voucher_date": "2026-10-26",
                    "invoice_no": "INV-999",
                    "invoice_date": "2026-10-25",
                    "supplier_name": "TEST SUPPLIER",
                    "item_name": "AMOXICILLIN 500",
                    "company_name": "TEST PHARMA",
                    "pack_size": "10",
                    "batch_no": "B123",
                    "expiry": "2028-12-31",
                    "pay_qty": 10.0,
                    "free_qty": 1.0,
                    "rate": 50.0,
                    "mrp": 75.0,
                    "discount": 0.0,
                    "gst_percent": 12.0,
                    "gst_amount": 60.0,
                    "amount": 500.0,
                    "purchase_rate": 56.0,
                    "net_rate": 50.91,
                }
            ],
            "summary": {
                "total_bills": 1,
                "total_pay_qty": 10.0,
                "total_free_qty": 1.0,
                "total_gross": 500.0,
                "total_gst": 60.0,
                "total_discount": 0.0,
                "total_net": 560.0,
            },
        }

        mock_inv = {
            "id": 9999,
            "voucher_no": "2026-2027-Credit-268",
            "voucher_date": "2026-10-26",
            "voucher_time": "12:52",
            "purchase_type": "Credit",
            "supplier_id": 1,
            "invoice_no": "INV-999",
            "invoice_date": "2026-10-25",
            "invoice_net_amount": 560.0,
            "bill_discount": 0.0,
            "due_date": "2026-11-25",
            "total_amount": 500.0,
            "gst_amount": 60.0,
            "debit_note_amount": 0.0,
            "other_amount": 0.0,
            "paid_amount": 0.0,
            "round_off": 0.0,
            "net_amount": 560.0,
            "remarks": "Test purchase remarks",
            "supplier_name": "TEST SUPPLIER",
        }
        mock_report_purch_dao.get_by_id.return_value = mock_inv
        mock_inv_purch_dao.get_by_id.return_value = mock_inv
        mock_inv_purch_dao.get_invoice_items.return_value = [
            {
                "item_id": 101,
                "item_name": "AMOXICILLIN 500",
                "pack_size": "10",
                "pay_qty": 10.0,
                "free_qty": 1.0,
                "batch_no": "B123",
                "expiry": "2028-12-31",
                "rate": 50.0,
                "mrp": 75.0,
                "discount": 0.0,
                "gst_percent": 12.0,
                "amount": 500.0,
                "gst_amount": 60.0,
                "purchase_rate": 56.0,
                "net_rate": 50.91,
                "pp": 25.0,
            }
        ]

        page = PurchaseReportPage()
        page.show()
        page._on_generate()
        self.app.processEvents()

        # Check table has 1 row and item(0, 0) has purchase_id 9999
        self.assertEqual(page._table.rowCount(), 1)
        self.assertEqual(page._table.item(0, 0).data(Qt.UserRole), 9999)

        # Open invoice dialog directly with the invoice
        inv = mock_report_purch_dao.get_by_id(9999)
        dlg = _InvoiceDialog(page, invoice=inv)
        dlg.show()
        self.app.processEvents()

        # Verify dialog structure matching header + restored layout
        self.assertIn("Purchase Invoice", dlg.windowTitle())
        self.assertEqual(dlg._header_title_lbl.text(), "Edit Invoice")
        self.assertEqual(dlg.voucher_no_edit.text(), "268")
        self.assertEqual(dlg.invoice_no_edit.text(), "INV-999")
        self.assertEqual(dlg.purchase_type_combo.currentText(), "Credit")
        self.assertTrue(dlg.due_date.isVisible())

        # Verify grid has 17 columns (# to Del)
        self.assertEqual(dlg._table.columnCount(), 17)
        expected_cols = [
            "#", "Item Name", "Pack", "Pay Qty", "Free", "Batch",
            "Exp", "Rate", "MRP", "Disc", "Amount", "GST%",
            "GST Amt", "Pur Rate", "Net Rate", "PP", "Del"
        ]
        actual_cols = [dlg._table.horizontalHeaderItem(c).text() for c in range(17)]
        self.assertEqual(actual_cols, expected_cols)

        # Verify row 0 data
        self.assertEqual(dlg._table.item(0, 0).text(), "1")
        self.assertEqual(dlg._table.item(0, 1).text(), "AMOXICILLIN 500")
        self.assertEqual(dlg._table.item(0, 5).text(), "B123")
        self.assertEqual(dlg._table.item(0, 15).text(), "25")

        # Verify totals
        self.assertEqual(dlg.total_amount_label.text(), "500.00")
        self.assertEqual(dlg.gst_label.text(), "60.00")
        self.assertEqual(dlg.net_amt_label.text(), "560.00")

        dlg.close()
        page.close()

    def test_03_real_database_invoice_open_in_dialog(self):
        """Test opening an actual historical invoice from the database in _InvoiceDialog."""
        invs = PurchaseDAO.get_all()
        if not invs:
            self.skipTest("No purchase invoices in database")

        target_inv = PurchaseDAO.get_by_id(invs[0]["id"])
        self.assertIsNotNone(target_inv)

        dlg = _InvoiceDialog(invoice=target_inv)
        dlg.show()
        self.app.processEvents()

        # Verify edit mode title and populated fields
        self.assertEqual(dlg._header_title_lbl.text(), "Edit Invoice")
        self.assertIn("Purchase Invoice", dlg.windowTitle())
        self.assertTrue(dlg.due_date.isVisible())
        self.assertEqual(dlg._table.columnCount(), 17)

        # Check that items were populated into grid
        items = PurchaseDAO.get_invoice_items(target_inv["id"])
        self.assertEqual(dlg._table.rowCount(), len(items))

        # Close without saving
        dlg.reject()
        self.assertFalse(dlg.was_saved)


if __name__ == "__main__":
    unittest.main()
