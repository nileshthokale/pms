"""Regression test suite for Counter Sale Walk-in Patient and Bill Number fixes.

Covers:
1. Default patient name is WALKIN when patient name is empty.
2. Default patient name is WALKIN when patient name contains only whitespace.
3. Real patient name is preserved when provided.
4. Customer selection is preserved when a customer is chosen.
5. No duplicate WALKIN customer records are created when one already exists.
6. An unnamed sale stores a genuinely blank Bill No.
7. Historical sales with empty patient names display a blank Bill No and WALKIN.
8. Bill number remains stable when a named saved bill is reopened and edited.
9. Blank Bill No has a blank tooltip (no placeholder or internal id).
10. Centralized formatters hide the number only when the patient is empty.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import datetime

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from core.doc_formatter import format_document_number, format_sales_bill_number
from database.connection import get_connection, init_database
from database import auth, financial_year
from database.account_roles import ensure_system_ledgers
from database.company_dao import CompanyDAO
from database.customer_dao import CustomerDAO
from database.doctor_dao import DoctorDAO
from database.item_dao import ItemDAO
from database.purchase_dao import PurchaseDAO
from database.sales_dao import SalesDAO
from database.stock_dao import StockDAO
from database.supplier_dao import SupplierDAO
from database.unit_dao import UnitDAO
from screens.counter_sale import CounterSalePage, _BillItemRow, _display_bill_no
from screens.sales_history import SalesHistoryPage, SalesBillDetailsDialog, _fmt_bill_no


class TestCounterSaleWalkinAndBillNoFix(unittest.TestCase):
    _DB_PATH = os.path.join(tempfile.gettempdir(), "_test_cs_walkin_billno.db")

    @classmethod
    def setUpClass(cls):
        if os.path.exists(cls._DB_PATH):
            try:
                os.remove(cls._DB_PATH)
            except Exception:
                pass
        os.environ["PHARMACY_DB"] = cls._DB_PATH
        init_database()
        auth.ensure_auth_schema()
        financial_year.ensure_financial_year_schema()
        financial_year.ensure_default_financial_year()
        if auth.user_count() == 0:
            auth.create_first_admin("admin", "admin-pass-1")
        auth.session.login("admin", "admin-pass-1")
        ensure_system_ledgers()

    def setUp(self):
        os.environ["PHARMACY_DB"] = self._DB_PATH
        conn = get_connection()
        try:
            for tbl in (
                "ledger_transactions", "sales_invoice_items", "sales_invoices",
                "purchase_invoice_items", "purchase_invoices", "stock_batches",
                "items", "customers", "doctors", "suppliers", "drugs", "units", "companies"
            ):
                try:
                    conn.execute(f"DELETE FROM {tbl}")
                except Exception:
                    pass
            conn.commit()
        finally:
            conn.close()

        # Seed master data
        self.comp_id = CompanyDAO.insert("TestPharma", "TP")
        self.unit_id = UnitDAO.insert("Strip")
        self.supplier_id = SupplierDAO.insert("MainSupplier")
        self.named_customer_id = CustomerDAO.insert("Alice Health")
        self.item_id = ItemDAO.insert(
            item_name="BIO D3 PLUS",
            unit_id=self.unit_id,
            company_id=self.comp_id,
            pack_size="15",
            mrp=341.34,
        )

        # Seed stock
        PurchaseDAO.insert_invoice(
            voucher_no="PV-0001",
            voucher_date="2026-10-01",
            voucher_time="10:00",
            purchase_type="Cash",
            supplier_id=self.supplier_id,
            invoice_no="PINV-001",
            invoice_date="2026-10-01",
            invoice_net_amount=5000.0,
            bill_discount=0,
            due_date="",
            total_amount=5000.0,
            gst_amount=0,
            debit_note_amount=0,
            other_amount=0,
            paid_amount=5000.0,
            round_off=0,
            net_amount=5000.0,
            remarks="",
            items=[{
                "item_id": self.item_id,
                "pack_size": "15",
                "pay_qty": 500.0,
                "free_qty": 0,
                "batch_no": "14261266A",
                "expiry": "2029-02-28",
                "rate": 20.0,
                "mrp": 341.34,
                "discount": 0,
                "gst_percent": 0,
                "gst_amount": 0,
                "amount": 5000.0,
                "purchase_rate": 20.0,
                "net_rate": 20.0,
                "pp": 20.0,
            }],
        )
        batches = StockDAO.get_stock_batches_for_item(self.item_id)
        self.assertTrue(batches)
        self.batch_id = batches[0]["id"]

    def _make_row(self, qty=1.0, amt=22.76):
        return _BillItemRow(
            item_id=self.item_id,
            item_name="BIO D3 PLUS",
            stock_batch_id=self.batch_id,
            pack_size="15",
            location="",
            batch_no="14261266A",
            expiry="2029-02-28",
            mrp=341.34,
            sale_qty=qty,
            discount_amount=0.0,
            amount=amt,
        )

    def test_01_formatter_rules_blank_for_empty_patient(self):
        """Empty/whitespace patient hides the number; named/omitted keeps it."""
        self.assertEqual(format_sales_bill_number("2026-2027-1905", patient_name=""), "")
        self.assertEqual(format_sales_bill_number("2026-2027-1905", patient_name="   "), "")
        self.assertEqual(format_sales_bill_number("2026-2027-1905", patient_name=None), "1905")
        self.assertEqual(format_sales_bill_number("2026-2027-1905", patient_name="John Doe"), "1905")
        self.assertEqual(format_sales_bill_number("2026-2027-Cash-201-S72334"), "201")
        self.assertEqual(format_sales_bill_number("2015"), "2015")

        self.assertEqual(SalesDAO.display_bill_no("2026-2027-1905", patient_name=""), "")
        self.assertEqual(SalesDAO.display_bill_no("2026-2027-1905", patient_name="  "), "")
        self.assertEqual(_display_bill_no("2026-2027-1905", patient_name=""), "")
        self.assertEqual(_display_bill_no("2026-2027-1905", patient_name="   "), "")
        self.assertEqual(_fmt_bill_no("2026-2027-1905", patient_name=""), "")
        self.assertEqual(_fmt_bill_no("2026-2027-1905", patient_name="   "), "")

    def test_02_empty_patient_saved_as_walkin(self):
        """When saved with empty patient name, patient_name in DB must be 'WALKIN'."""
        page = CounterSalePage()
        page.show()
        _app.processEvents()

        # Add item to active sale
        page._sale_panel.patient_name_edit.setText("")
        page._sale_panel._item_rows.append(self._make_row())
        page._sale_panel.paid_edit.setText("22.76")
        page._sale_panel._commit_sale()
        _app.processEvents()

        # Check DB
        conn = get_connection()
        try:
            inv = conn.execute("SELECT bill_no, patient_name, customer_id FROM sales_invoices ORDER BY id DESC LIMIT 1").fetchone()
            self.assertIsNotNone(inv)
            self.assertEqual(inv["patient_name"], "WALKIN")
            self.assertIsNotNone(inv["customer_id"])
            self.assertEqual(inv["bill_no"], "", "unnamed sale must keep a blank Bill No")
            # Verify customer name is WALKIN
            cust = conn.execute("SELECT customer_name FROM customers WHERE id = ?", (inv["customer_id"],)).fetchone()
            self.assertEqual(cust["customer_name"].upper(), "WALKIN")
        finally:
            conn.close()

        # Check Bill History display
        page._refresh_history()
        _app.processEvents()
        table = page._hist_table
        self.assertGreater(table.rowCount(), 0)
        # Bill No column must be genuinely blank, with no placeholder.
        bno_cell = table.item(0, 0)
        self.assertEqual(bno_cell.text(), "")
        self.assertEqual(bno_cell.toolTip(), "")
        # Patient column
        pat_cell = table.item(0, 6)
        self.assertEqual(pat_cell.text(), "WALKIN")

        page.close()

    def test_03_whitespace_patient_saved_as_walkin(self):
        """When saved with whitespace-only patient name, patient_name in DB must be 'WALKIN'."""
        page = CounterSalePage()
        page.show()
        _app.processEvents()

        page._sale_panel.patient_name_edit.setText("   \t  ")
        page._sale_panel._item_rows.append(self._make_row())
        page._sale_panel.paid_edit.setText("22.76")
        page._sale_panel._commit_sale()
        _app.processEvents()

        conn = get_connection()
        try:
            inv = conn.execute("SELECT bill_no, patient_name FROM sales_invoices ORDER BY id DESC LIMIT 1").fetchone()
            self.assertEqual(inv["patient_name"], "WALKIN")
            self.assertEqual(inv["bill_no"], "")
        finally:
            conn.close()

        page.close()

    def test_04_named_patient_preserved(self):
        """When a real patient name is entered, it must be preserved."""
        page = CounterSalePage()
        page.show()
        _app.processEvents()

        page._sale_panel.patient_name_edit.setText("MR MAHESH DHOKANE")
        page._sale_panel._item_rows.append(self._make_row())
        page._sale_panel.paid_edit.setText("22.76")
        page._sale_panel._commit_sale()
        _app.processEvents()

        conn = get_connection()
        try:
            inv = conn.execute("SELECT bill_no, patient_name FROM sales_invoices ORDER BY id DESC LIMIT 1").fetchone()
            self.assertEqual(inv["patient_name"], "MR MAHESH DHOKANE")
        finally:
            conn.close()

        # Check Bill History display
        page._refresh_history()
        _app.processEvents()
        table = page._hist_table
        pat_cell = table.item(0, 6)
        self.assertEqual(pat_cell.text(), "MR MAHESH DHOKANE")

        page.close()

    def test_05_no_duplicate_walkin_customer(self):
        """WALKIN customer creation must be idempotent: no duplicates."""
        w_id1 = CustomerDAO.get_or_create_walkin()
        w_id2 = CustomerDAO.get_or_create_walkin()
        self.assertEqual(w_id1, w_id2)

        conn = get_connection()
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM customers WHERE UPPER(TRIM(customer_name)) = 'WALKIN'"
            ).fetchone()[0]
            self.assertEqual(count, 1)
        finally:
            conn.close()

    def test_06_customer_selection_preserved(self):
        """When a customer is explicitly selected, that customer must be preserved."""
        page = CounterSalePage()
        page.show()
        _app.processEvents()

        # Select Alice Health
        idx = page._sale_panel.customer_combo.findText("Alice Health")
        self.assertGreater(idx, 0)
        page._sale_panel.customer_combo.setCurrentIndex(idx)
        # Empty patient name
        page._sale_panel.patient_name_edit.setText("")
        page._sale_panel._item_rows.append(self._make_row())
        page._sale_panel.paid_edit.setText("22.76")
        page._sale_panel._commit_sale()
        _app.processEvents()

        conn = get_connection()
        try:
            inv = conn.execute("SELECT customer_id, patient_name FROM sales_invoices ORDER BY id DESC LIMIT 1").fetchone()
            self.assertEqual(inv["customer_id"], self.named_customer_id)
            self.assertEqual(inv["patient_name"], "WALKIN")
        finally:
            conn.close()

        page.close()

    def test_07_bill_number_stability_on_reopen_and_edit(self):
        """Reopening and editing an existing bill preserves its Bill No stably."""
        # Insert a bill directly
        today = datetime.now().strftime("%Y-%m-%d")
        bno = SalesDAO.generate_next_bill_no()
        inv_id = SalesDAO.insert_invoice(
            bill_no=bno,
            sale_date=today,
            sale_time="14:00",
            sale_type="Cash",
            customer_id=self.named_customer_id,
            patient_name="Original Patient",
            doctor_id=None,
            discount=0.0,
            paid_amount=22.76,
            total_amount=22.76,
            round_off=0.0,
            net_amount=22.76,
            remarks="",
            items=[{
                "item_id": self.item_id,
                "stock_batch_id": self.batch_id,
                "pack_size": "15",
                "location": "",
                "batch_no": "14261266A",
                "expiry": "2029-02-28",
                "mrp": 341.34,
                "sale_qty": 1.0,
                "discount_amount": 0.0,
                "amount": 22.76,
            }],
        )

        page = CounterSalePage()
        page.show()
        _app.processEvents()

        inv = SalesDAO.get_by_id(inv_id)
        page._sale_panel.load_invoice(inv)
        _app.processEvents()

        expected_disp = format_document_number(bno)
        self.assertEqual(page._sale_panel.bill_no_edit.text(), expected_disp)

        # Clearing the name hides the legacy number while editing; the stored
        # number itself is never rewritten.
        page._sale_panel.patient_name_edit.setText("")
        _app.processEvents()
        self.assertEqual(page._sale_panel.bill_no_edit.text(), "")

        page._sale_panel.patient_name_edit.setText("   ")
        _app.processEvents()
        self.assertEqual(page._sale_panel.bill_no_edit.text(), "")

        # Save the edited bill: the stored number is preserved unchanged and
        # the cleared patient is stored as WALKIN.
        page._sale_panel._commit_sale()
        _app.processEvents()

        conn = get_connection()
        try:
            updated = conn.execute("SELECT bill_no, patient_name FROM sales_invoices WHERE id = ?", (inv_id,)).fetchone()
            self.assertEqual(updated["bill_no"], bno, "Stored Bill No must remain unchanged after edit")
            self.assertEqual(updated["patient_name"], "WALKIN", "Cleared patient must become WALKIN")
        finally:
            conn.close()

        page.close()

    def test_08_bill_wise_history_displays_blank_and_walkin(self):
        """In Bill Wise mode an unnamed sale shows blank Bill No and WALKIN."""
        today = datetime.now().strftime("%Y-%m-%d")
        inv_id = SalesDAO.insert_invoice(
            bill_no="",
            sale_date=today,
            sale_time="15:00",
            sale_type="Cash",
            customer_id=None,
            patient_name="",
            doctor_id=None,
            discount=0.0,
            paid_amount=22.76,
            total_amount=22.76,
            round_off=0.0,
            net_amount=22.76,
            remarks="",
            items=[{
                "item_id": self.item_id,
                "stock_batch_id": self.batch_id,
                "pack_size": "15",
                "location": "",
                "batch_no": "14261266A",
                "expiry": "2029-02-28",
                "mrp": 341.34,
                "sale_qty": 1.0,
                "discount_amount": 0.0,
                "amount": 22.76,
            }],
        )

        page = CounterSalePage()
        page.show()
        page._hist_bill_mode.setChecked(True)
        _app.processEvents()

        table = page._hist_table
        self.assertGreater(table.rowCount(), 0)
        cell_bno = table.item(0, 0)
        cell_pat = table.item(0, 2)
        self.assertEqual(cell_bno.text(), "")
        self.assertEqual(cell_bno.toolTip(), "")
        self.assertEqual(cell_pat.text(), "WALKIN")

        conn = get_connection()
        try:
            stored = conn.execute(
                "SELECT bill_no FROM sales_invoices WHERE id = ?", (inv_id,)
            ).fetchone()
            self.assertEqual(stored["bill_no"], "")
        finally:
            conn.close()

        page.close()

    def test_09_historical_sales_display_blank_bill_no_and_walkin(self):
        """A legacy empty-patient row displays blank while storage is intact."""
        fb_bno = "2026-2027-Cash-201-S72334"
        conn = get_connection()
        try:
            cur = conn.execute(
                "INSERT INTO sales_invoices ("
                "bill_no, sale_date, sale_time, sale_type, customer_id, "
                "patient_name, doctor_id, discount, paid_amount, total_amount, "
                "round_off, net_amount, remarks"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (fb_bno, "2026-10-19", "11:09", "Cash", None, "", None,
                 0.0, 22.76, 22.76, 0.0, 22.76, "legacy unmatched patient"),
            )
            conn.commit()
            fb_id = cur.lastrowid
        finally:
            conn.close()

        page = CounterSalePage()
        page.show()
        page._hist_date.setDate(QDate.fromString("2026-10-19", "yyyy-MM-dd"))
        page._refresh_history()
        _app.processEvents()

        table = page._hist_table
        self.assertGreater(table.rowCount(), 0)
        bno_cell = table.item(0, 0)
        pat_cell = table.item(0, 6)
        self.assertEqual(bno_cell.text(), "")
        self.assertEqual(bno_cell.toolTip(), "")
        self.assertEqual(pat_cell.text(), "WALKIN")

        conn = get_connection()
        try:
            stored = conn.execute(
                "SELECT bill_no, patient_name FROM sales_invoices WHERE id = ?",
                (fb_id,),
            ).fetchone()
            self.assertEqual(stored["bill_no"], fb_bno)
            self.assertEqual(stored["patient_name"], "")
        finally:
            conn.close()

        page.close()


if __name__ == "__main__":
    unittest.main()
