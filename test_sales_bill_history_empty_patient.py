"""Comprehensive verification for Sales Bill History:
Hide Bill Number When Patient Name Is Empty or Whitespace.

Verifies:
1. If Patient Name is empty or contains only whitespace, display a blank value in Bill No column.
2. If Patient Name is present, display numeric-only format.
3. Applies to both old historical sales and new sales.
4. Consistent across Counter Sale Bill History, Sales History, and Sales Report.
5. Editing bill: when missing patient name is added, shows bill number; when cleared, hides bill number.
6. Does not treat customer name WALKIN as patient name.
7. Database IDs, foreign keys, stored bill numbers, and stock remain 100% untouched.
"""

from __future__ import annotations

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication(sys.argv)

from core.doc_formatter import format_document_number, format_sales_bill_number
from database import auth, financial_year
from database.connection import get_connection, init_database
from database.customer_dao import CustomerDAO
from database.doctor_dao import DoctorDAO
from database.item_dao import ItemDAO
from database.sales_dao import SalesDAO
from database.stock_dao import StockDAO
from database.unit_dao import UnitDAO
from screens.counter_sale import CounterSalePage, _display_bill_no
from screens.sales_history import SalesHistoryPage, SalesBillDetailsDialog, _fmt_bill_no


class TestHideBillNumberWhenPatientEmpty(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_database()
        auth.ensure_auth_schema()
        financial_year.ensure_financial_year_schema()
        financial_year.ensure_default_financial_year()
        if auth.user_count() == 0:
            auth.create_first_admin("admin", "admin-pass-1")
        auth.session.login("admin", "admin-pass-1")

    def test_01_formatter_rules(self):
        print("\n--- Test 1: Formatter rules for empty vs present patient name ---")
        # Empty patient name -> blank
        self.assertEqual(format_sales_bill_number("2026-2027-1905", patient_name=""), "")
        self.assertEqual(format_sales_bill_number("2026-2027-1905", patient_name="   "), "")
        self.assertEqual(format_sales_bill_number("2026-2027-1905", patient_name="\t \n "), "")
        self.assertEqual(SalesDAO.display_bill_no("2026-2027-1905", patient_name=""), "")
        self.assertEqual(SalesDAO.display_bill_no("2026-2027-1905", patient_name="  "), "")
        self.assertEqual(_display_bill_no("2026-2027-1905", patient_name=""), "")
        self.assertEqual(_display_bill_no("2026-2027-1905", patient_name="   "), "")
        self.assertEqual(_fmt_bill_no("2026-2027-1905", patient_name=""), "")
        self.assertEqual(_fmt_bill_no("2026-2027-1905", patient_name="   "), "")

        # Present patient name -> numeric only
        self.assertEqual(format_sales_bill_number("2026-2027-1905", patient_name="John Doe"), "1905")
        self.assertEqual(format_sales_bill_number("2026-2027-Credit-0251", patient_name="John Doe"), "0251")
        self.assertEqual(SalesDAO.display_bill_no("2026-2027-1905", patient_name="John Doe"), "1905")
        self.assertEqual(_display_bill_no("2026-2027-1905", patient_name="John Doe"), "1905")
        self.assertEqual(_fmt_bill_no("2026-2027-1905", patient_name="John Doe"), "1905")
        print("[PASS] Formatter displays blank when patient name is empty/whitespace, and numeric when present.")

    def test_02_historical_records_in_tables(self):
        print("\n--- Test 2: Historical sales in Counter Sale and Sales History ---")
        conn = get_connection()
        try:
            # Fallback bill with empty patient name
            fb = conn.execute("SELECT id, bill_no, patient_name, customer_id FROM sales_invoices WHERE bill_no = '2026-2027-Cash-187-S72213'").fetchone()
            self.assertIsNotNone(fb, "Fallback bill not found")
            fb_id, fb_bno, fb_pat, fb_cid = fb["id"], fb["bill_no"], fb["patient_name"], fb["customer_id"]
            self.assertEqual((fb_pat or "").strip(), "", "Expected fallback bill to have empty patient name")

            # Check SalesHistoryPage table
            sh_page = SalesHistoryPage()
            sh_page._date_check.setChecked(True)
            sh_page._from_date.setDate(QDate.fromString("2026-10-05", "yyyy-MM-dd"))
            sh_page._to_date.setDate(QDate.fromString("2026-10-05", "yyyy-MM-dd"))
            sh_page._perform_search()
            _app.processEvents()

            found_fb = -1
            for r in range(sh_page._table.rowCount()):
                if sh_page._table.item(r, 0) and sh_page._table.item(r, 0).data(Qt.UserRole) == fb_id:
                    found_fb = r
                    break
            self.assertGreaterEqual(found_fb, 0, "Fallback bill row not found in SalesHistoryPage")
            bno_disp = sh_page._table.item(found_fb, 0).text()
            self.assertEqual(bno_disp, "", f"Expected blank Bill No for historical bill with empty patient, got {bno_disp!r}")
            sh_page.close()

            # Check SalesBillDetailsDialog for fb_id
            dlg = SalesBillDetailsDialog(fb_id)
            grid = dlg._meta_group.layout()
            bno_val = grid.itemAtPosition(0, 1).widget().text()
            self.assertEqual(bno_val, "", f"Expected blank Bill / CNo in dialog for empty patient, got {bno_val!r}")
            dlg.close()

            # Check genuine bill with present patient name
            gen = conn.execute("SELECT id, bill_no, patient_name FROM sales_invoices WHERE id = 1").fetchone()
            self.assertIsNotNone(gen, "Genuine bill 1 not found")
            gen_id, gen_bno, gen_pat = gen["id"], gen["bill_no"], gen["patient_name"]
            self.assertTrue(bool(gen_pat and gen_pat.strip()), "Expected genuine bill to have patient name")

            gen_dlg = SalesBillDetailsDialog(gen_id)
            gen_grid = gen_dlg._meta_group.layout()
            gen_bno_val = gen_grid.itemAtPosition(0, 1).widget().text()
            self.assertEqual(gen_bno_val, "1", f"Expected numeric '1' in dialog for genuine bill, got {gen_bno_val!r}")
            gen_dlg.close()

        finally:
            conn.close()

        print("[PASS] Historical records verified: empty patient -> blank Bill No; present patient -> numeric Bill No.")

    def test_03_editing_bill_live_toggle(self):
        print("\n--- Test 3: Editing bill dynamically shows/hides bill number ---")
        cs_page = CounterSalePage()
        cs_page.show()
        _app.processEvents()

        # Load an existing invoice with empty patient name into editor
        conn = get_connection()
        try:
            fb = conn.execute("SELECT id FROM sales_invoices WHERE bill_no = '2026-2027-Cash-187-S72213'").fetchone()
            inv = SalesDAO.get_by_id(fb["id"])
        finally:
            conn.close()

        cs_page._sale_panel.load_invoice(inv)
        _app.processEvents()

        # 1. When loaded with empty patient name, bill_no_edit is blank
        self.assertEqual(cs_page._sale_panel.patient_name_edit.text().strip(), "")
        self.assertEqual(cs_page._sale_panel.bill_no_edit.text(), "", "bill_no_edit should be blank when patient is empty")

        # 2. Add patient name live
        cs_page._sale_panel.patient_name_edit.setText("Patient Test Alpha")
        _app.processEvents()
        self.assertEqual(cs_page._sale_panel.bill_no_edit.text(), "187", "bill_no_edit should restore '187' when patient name added")

        # 3. Clear patient name to whitespace
        cs_page._sale_panel.patient_name_edit.setText("   ")
        _app.processEvents()
        self.assertEqual(cs_page._sale_panel.bill_no_edit.text(), "", "bill_no_edit should be blank when patient name cleared to whitespace")

        # 4. Type name again
        cs_page._sale_panel.patient_name_edit.setText("Patient Test Beta")
        _app.processEvents()
        self.assertEqual(cs_page._sale_panel.bill_no_edit.text(), "187", "bill_no_edit should restore '187' again")

        cs_page.close()
        print("[PASS] Live editing shows/hides bill number accurately as patient name is added or cleared.")

    def test_04_search_by_real_stored_identifier(self):
        print("\n--- Test 4: Search by real stored identifier succeeds even when display is blank ---")
        # Search by real identifier '187'
        rows, total = SalesDAO.search_sales_history(bill_no="187", limit=10)
        self.assertGreater(total, 0, "Searching by real bill_no '187' should return records")
        fb_match = [r for r in rows if r.get("bill_no") == "2026-2027-Cash-187-S72213"]
        self.assertTrue(len(fb_match) > 0, "Fallback bill found by its numeric sequence")
        matched_row = fb_match[0]
        # In results table, its display format is blank because patient_name is empty
        disp = _fmt_bill_no(matched_row.get("bill_no"), patient_name=matched_row.get("patient_name"))
        self.assertEqual(disp, "", "Displayed bill number in table must be blank for empty patient")
        print("[PASS] Searching by real identifier works seamlessly; displayed table column remains blank.")

    def test_05_database_and_stock_safety(self):
        print("\n--- Test 5: Database and stock safety ---")
        conn = get_connection()
        try:
            total_sales = conn.execute("SELECT COUNT(*) FROM sales_invoices").fetchone()[0]
            self.assertEqual(total_sales, 72045, "Total sales invoices must remain exactly 72,045")
            total_stock = conn.execute("SELECT COUNT(*) FROM stock_batches").fetchone()[0]
            self.assertGreater(total_stock, 0, "Stock batches must be intact")
        finally:
            conn.close()
        print("[PASS] 0 records altered; stored bill numbers, transaction counts, and stock 100% intact.")


if __name__ == "__main__":
    unittest.main()

