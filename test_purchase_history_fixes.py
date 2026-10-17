"""Focused regression tests for Purchase History fixes:
1. Voucher Number without leading zeros (e.g. 252, not 0252; Cash 1, Credit Card 1).
2. Time formatting in 12-hour AM/PM without leading zero on hours (e.g. 7:56 PM, 10:18 AM, 12:44 PM).
3. Financial-Year date filtering and set_history_financial_year on PurchaseInvoicePage.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime

from PySide6.QtCore import Qt, QDate
from PySide6.QtWidgets import QApplication

_app = QApplication.instance()
if _app is None:
    _app = QApplication(sys.argv)

from core.doc_formatter import (
    format_document_number,
    format_purchase_voucher_number,
    format_time_12hr,
)
from database import financial_year
from database.connection import get_connection
from database.purchase_dao import PurchaseDAO
from screens.purchase_invoice import (
    PurchaseInvoicePage,
    _InvoiceDialog,
    _display_voucher_no,
)


class TestPurchaseHistoryFixes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        financial_year.ensure_default_financial_year()

    def test_01_format_time_12hr(self):
        """Test conversion of all time formats to 12-hour AM/PM."""
        cases = [
            ("19:56", "7:56 PM"),
            ("19:56:00", "7:56 PM"),
            ("10:18 AM", "10:18 AM"),
            ("12:44 PM", "12:44 PM"),
            ("12:00 PM", "12:00 PM"),
            ("12:00", "12:00 PM"),
            ("00:00", "12:00 AM"),
            ("00:30", "12:30 AM"),
            ("12:00 AM", "12:00 AM"),
            ("09:05", "9:05 AM"),
            ("09:05 AM", "9:05 AM"),
            ("9:05 AM", "9:05 AM"),
            ("23:59", "11:59 PM"),
            ("01:15", "1:15 AM"),
            ("1:15 AM", "1:15 AM"),
            ("", ""),
            (None, ""),
            ("--", "--"),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(format_time_12hr(raw), expected)

    def test_02_format_purchase_voucher_number(self):
        """Test that purchase voucher numbers have no leading zeros."""
        cases = [
            ("2026-2027-Credit-0251", "251"),
            ("2026-2027-Credit-250", "250"),
            ("2026-2027-Credit-252", "252"),
            ("2026-2027-Cash-0001", "1"),
            ("2026-2027-Cash-1", "1"),
            ("2026-2027-Cash-42", "42"),
            ("2026-2027-Credit Card-1", "1"),
            ("0252", "252"),
            ("252", "252"),
            ("PV-0001", "1"),
            ("", ""),
            (None, ""),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(format_purchase_voucher_number(raw), expected)

    def test_03_generate_next_voucher_no_types(self):
        """Test next voucher number generation for Credit, Cash, and Credit Card."""
        # For Credit in 2026-2027: DB currently has up to 251 (2026-2027-Credit-0251)
        next_credit = PurchaseDAO.generate_next_voucher_no("Credit")
        self.assertEqual(next_credit, "2026-2027-Credit-252")
        self.assertEqual(_display_voucher_no(next_credit), "252")

        # For Cash in 2026-2027: none exists yet, so start at 1
        next_cash = PurchaseDAO.generate_next_voucher_no("Cash")
        self.assertEqual(next_cash, "2026-2027-Cash-1")
        self.assertEqual(_display_voucher_no(next_cash), "1")

        # For Credit Card in 2026-2027: none exists yet, so start at 1
        next_cc = PurchaseDAO.generate_next_voucher_no("Credit Card")
        self.assertEqual(next_cc, "2026-2027-Credit Card-1")
        self.assertEqual(_display_voucher_no(next_cc), "1")

    def test_04_new_dialog_voucher_display_and_type_change(self):
        """Test that New Purchase dialog displays 252 (not 0252) and updates on type change."""
        dlg = _InvoiceDialog()
        try:
            # Default is Credit -> 252
            self.assertEqual(dlg.voucher_no_edit.text(), "252")
            self.assertFalse(dlg.voucher_no_edit.text().startswith("0"))
            self.assertEqual(dlg._full_voucher_no, "2026-2027-Credit-252")

            # Change to Cash -> 1
            dlg.purchase_type_combo.setCurrentText("Cash")
            self.assertEqual(dlg.voucher_no_edit.text(), "1")
            self.assertEqual(dlg._full_voucher_no, "2026-2027-Cash-1")

            # Change back to Credit -> 252
            dlg.purchase_type_combo.setCurrentText("Credit")
            self.assertEqual(dlg.voucher_no_edit.text(), "252")
            self.assertEqual(dlg._full_voucher_no, "2026-2027-Credit-252")

            # Check time formatting in dialog
            time_text = dlg.voucher_time_edit.text()
            self.assertTrue("AM" in time_text or "PM" in time_text)
            self.assertFalse(time_text.startswith("0"))
        finally:
            dlg.close()

    def test_05_purchase_history_table_formatting(self):
        """Test that Purchase History table renders voucher numbers and 12-hr AM/PM times."""
        page = PurchaseInvoicePage()
        try:
            page._refresh_history()
            table = page._hist_table
            self.assertGreater(table.rowCount(), 0)

            # Check top row (newest row, id 5714 which had '19:56' and '0251')
            row0_vno = table.item(0, 1).text()
            row0_time = table.item(0, 3).text()

            # Voucher should be numeric without leading zeros ('251')
            self.assertEqual(row0_vno, "251")
            # Time should be 12-hour AM/PM ('7:56 PM')
            self.assertEqual(row0_time, "7:56 PM")

            # Check that all rows in table have AM/PM times if time is present
            for r in range(min(table.rowCount(), 20)):
                t_item = table.item(r, 3)
                if t_item and t_item.text():
                    t = t_item.text()
                    self.assertTrue(
                        "AM" in t or "PM" in t,
                        f"Row {r} time '{t}' is not in AM/PM format"
                    )
                    # Verify no leading zero on hour
                    self.assertFalse(
                        t.startswith("0"),
                        f"Row {r} time '{t}' should not start with leading zero"
                    )
        finally:
            page.close()

    def test_06_purchase_history_financial_year_switching(self):
        """Test that navbar FY switching updates Purchase History date filters."""
        page = PurchaseInvoicePage()
        try:
            # Active FY
            active_fy = financial_year.get_active_financial_year()
            self.assertTrue(hasattr(page, "set_history_financial_year"))

            # Switch to FY 2024-2025
            old_fy = {
                "id": 11,
                "name": "2024-2025",
                "start_date": "2024-04-01",
                "end_date": "2025-03-31",
            }
            page.set_history_financial_year(old_fy)
            self.assertEqual(page._filter_from.date().toString("yyyy-MM-dd"), "2024-04-01")
            self.assertEqual(page._filter_to.date().toString("yyyy-MM-dd"), "2025-03-31")

            # Reset back to active FY (None)
            page.set_history_financial_year(None)
            self.assertEqual(
                page._filter_from.date().toString("yyyy-MM-dd"),
                active_fy["start_date"]
            )
        finally:
            page.close()


if __name__ == "__main__":
    unittest.main()
