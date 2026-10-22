"""Isolated regression tests for unnamed Counter Sales and blank Bill Nos.

Every test runs against a fresh temporary SQLite database.  ``data/pharmacy.db``
is never opened or modified.

Required behaviour:
1. empty Patient Name  -> store WALKIN, keep a genuinely blank Bill No;
2. whitespace Patient  -> store WALKIN, keep a genuinely blank Bill No;
3. real Patient Name    -> preserve it and generate a non-empty Bill No;
4. multiple unnamed sales can all share the blank Bill No (no UNIQUE clash);
5. the blank Bill No survives save, refresh, reopen, edit, and a restart;
6. historical unnamed rows display blank while their stored number, ids and
   stock stay untouched; named rows keep their number;
7. stock, accounting and printing still work for the unnamed sale.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import date
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QApplication, QMessageBox

_app = QApplication.instance() or QApplication([])

from core.doc_formatter import format_sales_bill_number
from database import auth, document_printing, financial_year
from database.account_roles import ensure_system_ledgers
from database.company_dao import CompanyDAO
from database.connection import get_connection, init_database
from database.customer_dao import CustomerDAO
from database.item_dao import ItemDAO
from database.purchase_dao import PurchaseDAO
from database.sales_dao import SalesDAO
from database.stock_dao import StockDAO
from database.supplier_dao import SupplierDAO
from database.unit_dao import UnitDAO
from screens.counter_sale import CounterSalePage, _BillItemRow, _display_bill_no
from screens.sales_history import SalesHistoryPage, _fmt_bill_no


TODAY = date.today().isoformat()


class TestUnnamedSalesBlankBillNo(unittest.TestCase):
    _DB_PATH: str = ""

    @classmethod
    def setUpClass(cls):
        fd, cls._DB_PATH = tempfile.mkstemp(prefix="pharmacy_unnamed_sales_", suffix=".db")
        os.close(fd)
        cls._previous_db = os.environ.get("PHARMACY_DB")
        os.environ["PHARMACY_DB"] = cls._DB_PATH
        init_database()
        auth.ensure_auth_schema()
        financial_year.ensure_financial_year_schema()
        financial_year.ensure_default_financial_year()
        if auth.user_count() == 0:
            auth.create_first_admin("admin", "admin-pass-1")
        auth.session.login("admin", "admin-pass-1")
        ensure_system_ledgers()

    @classmethod
    def tearDownClass(cls):
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(cls._DB_PATH + suffix)
            except FileNotFoundError:
                pass
        if cls._previous_db is None:
            os.environ.pop("PHARMACY_DB", None)
        else:
            os.environ["PHARMACY_DB"] = cls._previous_db

    def setUp(self):
        conn = get_connection()
        try:
            for table in (
                "ledger_transactions", "sales_invoice_items", "sales_invoices",
                "purchase_invoice_items", "purchase_invoices", "stock_batches",
                "hold_bill_items", "hold_bills", "items", "customers",
                "doctors", "suppliers", "drugs", "units", "companies",
            ):
                try:
                    conn.execute(f"DELETE FROM {table}")
                except Exception:
                    pass
            conn.commit()
        finally:
            conn.close()

        self.company_id = CompanyDAO.insert("Unnamed Test Pharma", "UTP")
        self.unit_id = UnitDAO.insert("Strip")
        self.supplier_id = SupplierDAO.insert("Unnamed Test Supplier")
        self.item_id = ItemDAO.insert(
            item_name="UNNAMED TEST ITEM",
            unit_id=self.unit_id,
            company_id=self.company_id,
            pack_size="10",
            mrp=100.0,
        )
        PurchaseDAO.insert_invoice(
            voucher_no="PV-UNNAMED-1",
            voucher_date=TODAY,
            voucher_time="09:00",
            purchase_type="Cash",
            supplier_id=self.supplier_id,
            invoice_no="PINV-UNNAMED-1",
            invoice_date=TODAY,
            invoice_net_amount=5000.0,
            bill_discount=0.0,
            due_date="",
            total_amount=5000.0,
            gst_amount=0.0,
            debit_note_amount=0.0,
            other_amount=0.0,
            paid_amount=5000.0,
            round_off=0.0,
            net_amount=5000.0,
            remarks="",
            items=[{
                "item_id": self.item_id,
                "pack_size": "10",
                "pay_qty": 100.0,
                "free_qty": 0.0,
                "batch_no": "UNNAMED-BATCH-1",
                "expiry": "12/30",
                "rate": 50.0,
                "mrp": 100.0,
                "discount": 0.0,
                "gst_percent": 0.0,
                "gst_amount": 0.0,
                "amount": 5000.0,
                "purchase_rate": 50.0,
                "net_rate": 50.0,
                "pp": 50.0,
            }],
        )
        self.batch = StockDAO.get_stock_batches_for_item(self.item_id)[0]
        self._patches = [
            mock.patch.object(QMessageBox, "warning", return_value=QMessageBox.Ok),
            mock.patch.object(QMessageBox, "information", return_value=QMessageBox.Ok),
            mock.patch.object(QMessageBox, "critical", return_value=QMessageBox.Ok),
            mock.patch.object(QMessageBox, "question", return_value=QMessageBox.Yes),
        ]
        for patch in self._patches:
            patch.start()
            self.addCleanup(patch.stop)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _sale_kwargs(self, *, bill_no, patient_name, amount=100.0,
                     sale_date=TODAY):
        return dict(
            bill_no=bill_no,
            sale_date=sale_date,
            sale_time="10:30",
            sale_type="Cash",
            customer_id=None,
            patient_name=patient_name,
            doctor_id=None,
            discount=0.0,
            paid_amount=amount,
            total_amount=amount,
            round_off=0.0,
            net_amount=amount,
            remarks="",
            items=[{
                "item_id": self.item_id,
                "stock_batch_id": self.batch["id"],
                "pack_size": "10",
                "location": "",
                "batch_no": self.batch["batch_no"],
                "expiry": self.batch["expiry"],
                "mrp": 100.0,
                "sale_qty": 1.0,
                "discount_amount": 0.0,
                "amount": amount,
            }],
        )

    def _insert(self, **overrides):
        kwargs = self._sale_kwargs(**overrides)
        return SalesDAO.insert_invoice(**kwargs)

    def _fetch(self, invoice_id):
        conn = get_connection()
        try:
            return conn.execute(
                "SELECT id, bill_no, patient_name, customer_id, net_amount "
                "FROM sales_invoices WHERE id = ?",
                (invoice_id,),
            ).fetchone()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # 1-4: Save behaviour
    # ------------------------------------------------------------------

    def test_01_empty_patient_saves_walkin_with_blank_bill_no(self):
        invoice_id = self._insert(bill_no="", patient_name="")
        row = self._fetch(invoice_id)
        self.assertEqual(row["patient_name"], "WALKIN")
        self.assertEqual(row["bill_no"], "")
        self.assertIsNotNone(row["customer_id"])
        self.assertEqual(_display_bill_no(row["bill_no"], patient_name=""), "")
        self.assertEqual(
            format_sales_bill_number(row["bill_no"], patient_name=row["patient_name"]),
            "",
        )

    def test_02_whitespace_patient_saves_walkin_with_blank_bill_no(self):
        invoice_id = self._insert(bill_no="", patient_name="   \t  ")
        row = self._fetch(invoice_id)
        self.assertEqual(row["patient_name"], "WALKIN")
        self.assertEqual(row["bill_no"], "")

    def test_03_real_patient_is_preserved_and_gets_a_bill_number(self):
        invoice_id = self._insert(bill_no=None, patient_name="MR REAL PATIENT")
        row = self._fetch(invoice_id)
        self.assertEqual(row["patient_name"], "MR REAL PATIENT")
        self.assertTrue(row["bill_no"].strip(), "named sale must get a bill number")
        self.assertNotEqual(
            format_sales_bill_number(row["bill_no"], patient_name=row["patient_name"]),
            "",
        )

    def test_04_multiple_unnamed_sales_share_blank_bill_no(self):
        ids = [
            self._insert(bill_no="", patient_name=""),
            self._insert(bill_no="", patient_name="   "),
            self._insert(bill_no="", patient_name=""),
        ]
        for invoice_id in ids:
            row = self._fetch(invoice_id)
            self.assertEqual(row["bill_no"], "")
            self.assertEqual(row["patient_name"], "WALKIN")

        conn = get_connection()
        try:
            blanks = conn.execute(
                "SELECT COUNT(*) FROM sales_invoices WHERE bill_no = ''"
            ).fetchone()[0]
            index_rows = {
                row["name"]: row
                for row in conn.execute("PRAGMA index_list(sales_invoices)")
            }
            self.assertEqual(blanks, 3)
            self.assertIn("ux_sales_invoices_bill_no_nonblank", index_rows)
            self.assertEqual(
                int(index_rows["ux_sales_invoices_bill_no_nonblank"]["unique"]), 1
            )
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # 5: Save / refresh / reopen / edit / restart
    # ------------------------------------------------------------------

    def test_05_blank_bill_no_survives_counter_sale_edit_and_restart(self):
        page = CounterSalePage()
        page.show()
        _app.processEvents()
        panel = page._sale_panel
        panel.patient_name_edit.setText("")
        panel._item_rows.append(_BillItemRow(
            item_id=self.item_id,
            item_name="UNNAMED TEST ITEM",
            stock_batch_id=self.batch["id"],
            pack_size="10",
            location="",
            batch_no=self.batch["batch_no"],
            expiry=self.batch["expiry"],
            mrp=100.0,
            sale_qty=1.0,
            discount_amount=0.0,
            amount=100.0,
        ))
        panel.paid_edit.setText("100.00")
        panel._commit_sale()
        _app.processEvents()

        conn = get_connection()
        try:
            saved = conn.execute(
                "SELECT id, bill_no, patient_name FROM sales_invoices "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(saved["bill_no"], "")
        self.assertEqual(saved["patient_name"], "WALKIN")
        invoice_id = saved["id"]

        # History refresh: blank cell and blank tooltip, patient shown as WALKIN.
        page._refresh_history()
        _app.processEvents()
        table = page._hist_table
        found = -1
        for r in range(table.rowCount()):
            cell = table.item(r, 0)
            if cell and cell.data(0x0100) == invoice_id:
                found = r
                break
        self.assertGreaterEqual(found, 0)
        self.assertEqual(table.item(found, 0).text(), "")
        self.assertEqual(table.item(found, 0).toolTip(), "")
        self.assertEqual(table.item(found, 6).text(), "WALKIN")
        page.close()

        # Reopen and edit the saved unnamed sale.  The edit must keep both the
        # WALKIN marker and the genuinely blank Bill No.
        invoice = SalesDAO.get_by_id(invoice_id)
        edit_page = CounterSalePage()
        edit_page.show()
        _app.processEvents()
        edit_panel = edit_page._sale_panel
        edit_panel.load_invoice(invoice)
        _app.processEvents()
        self.assertEqual(edit_panel.patient_name_edit.text(), "WALKIN")
        self.assertEqual(edit_panel.bill_no_edit.text(), "")

        edit_panel.paid_edit.setText("100.00")
        edit_panel._commit_sale()
        _app.processEvents()
        edit_page.close()

        # Restart simulation: initialize the schema again and reread.
        init_database()
        row = self._fetch(invoice_id)
        self.assertEqual(row["bill_no"], "")
        self.assertEqual(row["patient_name"], "WALKIN")

    # ------------------------------------------------------------------
    # 6: Historical display is blank, storage is untouched
    # ------------------------------------------------------------------

    def test_06_historical_unnamed_row_displays_blank_but_keeps_storage(self):
        historical_no = "2026-2027-Cash-201-S72334"
        # Historical rows are seeded directly: the current DAO deliberately
        # stores WALKIN for every new unnamed sale, so a raw row is the only
        # faithful way to represent a legacy record whose stored patient name
        # is genuinely empty.
        conn = get_connection()
        try:
            cur = conn.execute(
                "INSERT INTO sales_invoices ("
                "bill_no, sale_date, sale_time, sale_type, customer_id, "
                "patient_name, doctor_id, discount, paid_amount, total_amount, "
                "round_off, net_amount, remarks"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (historical_no, "2020-01-15", "10:00", "Cash", None,
                 "", None, 0.0, 100.0, 100.0, 0.0, 100.0, "legacy unnamed row"),
            )
            unnamed_id = cur.lastrowid
            cur = conn.execute(
                "INSERT INTO sales_invoices ("
                "bill_no, sale_date, sale_time, sale_type, customer_id, "
                "patient_name, doctor_id, discount, paid_amount, total_amount, "
                "round_off, net_amount, remarks"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("2020-2021-1905", "2020-01-15", "10:00", "Cash", None,
                 "HISTORICAL PATIENT", None, 0.0, 100.0, 100.0, 0.0, 100.0,
                 "legacy named row"),
            )
            named_id = cur.lastrowid
            conn.commit()
        finally:
            conn.close()

        conn = get_connection()
        try:
            before_unnamed = dict(conn.execute(
                "SELECT * FROM sales_invoices WHERE id = ?", (unnamed_id,)
            ).fetchone())
            before_named = dict(conn.execute(
                "SELECT * FROM sales_invoices WHERE id = ?", (named_id,)
            ).fetchone())
            stock_before = conn.execute(
                "SELECT stock_qty FROM stock_batches WHERE id = ?", (self.batch["id"],)
            ).fetchone()[0]
        finally:
            conn.close()

        self.assertEqual(
            SalesDAO.display_bill_no(historical_no, patient_name=""), ""
        )
        self.assertEqual(_fmt_bill_no(historical_no, patient_name=""), "")
        self.assertEqual(
            format_sales_bill_number(historical_no, patient_name=""), ""
        )
        self.assertNotEqual(
            SalesDAO.display_bill_no(historical_no, patient_name="HISTORICAL PATIENT"),
            "",
        )

        page = SalesHistoryPage()
        page.show()
        page._date_check.setChecked(True)
        page._from_date.setDate(QDate.fromString("2020-01-15", "yyyy-MM-dd"))
        page._to_date.setDate(QDate.fromString("2020-01-15", "yyyy-MM-dd"))
        page._perform_search()
        _app.processEvents()

        unnamed_row = named_row = -1
        for r in range(page._table.rowCount()):
            cell = page._table.item(r, 0)
            if not cell:
                continue
            if cell.data(0x0100) == unnamed_id:
                unnamed_row = r
            elif cell.data(0x0100) == named_id:
                named_row = r
        self.assertGreaterEqual(unnamed_row, 0)
        self.assertGreaterEqual(named_row, 0)

        self.assertEqual(page._table.item(unnamed_row, 0).text(), "")
        self.assertEqual(page._table.item(unnamed_row, 0).toolTip(), "")
        self.assertEqual(page._table.item(unnamed_row, 2).text(), "WALKIN")
        self.assertNotEqual(page._table.item(named_row, 0).text(), "")
        self.assertEqual(
            page._table.item(named_row, 2).text(), "HISTORICAL PATIENT"
        )
        page.close()

        # Stored values, ids and stock must be byte-for-byte untouched.
        conn = get_connection()
        try:
            after_unnamed = dict(conn.execute(
                "SELECT * FROM sales_invoices WHERE id = ?", (unnamed_id,)
            ).fetchone())
            after_named = dict(conn.execute(
                "SELECT * FROM sales_invoices WHERE id = ?", (named_id,)
            ).fetchone())
            stock_after = conn.execute(
                "SELECT stock_qty FROM stock_batches WHERE id = ?", (self.batch["id"],)
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(before_unnamed, after_unnamed)
        self.assertEqual(before_named, after_named)
        self.assertEqual(stock_before, stock_after)

    # ------------------------------------------------------------------
    # 7: Stock, accounting and printing remain healthy
    # ------------------------------------------------------------------

    def test_07_unnamed_sale_stock_accounting_and_printing(self):
        conn = get_connection()
        try:
            stock_before = conn.execute(
                "SELECT stock_qty FROM stock_batches WHERE id = ?", (self.batch["id"],)
            ).fetchone()[0]
        finally:
            conn.close()

        invoice_id = self._insert(bill_no="", patient_name="")
        row = self._fetch(invoice_id)
        self.assertEqual(row["bill_no"], "")

        conn = get_connection()
        try:
            stock_after = conn.execute(
                "SELECT stock_qty FROM stock_batches WHERE id = ?", (self.batch["id"],)
            ).fetchone()[0]
            postings = conn.execute(
                "SELECT voucher_no, debit, credit FROM ledger_transactions "
                "WHERE reference_type = 'COUNTER_SALE' AND reference_id = ?",
                (invoice_id,),
            ).fetchall()
        finally:
            conn.close()

        self.assertEqual(stock_after, stock_before - 1.0)
        self.assertGreaterEqual(len(postings), 2)
        self.assertTrue(all(p["voucher_no"] == "" for p in postings))

        output = os.path.join(
            tempfile.gettempdir(), f"_unnamed_sale_{invoice_id}.pdf"
        )
        self.addCleanup(lambda: os.path.exists(output) and os.remove(output))
        printed = document_printing.generate_counter_sale_bill(invoice_id, output)
        self.assertTrue(os.path.exists(printed))
        self.assertGreater(os.path.getsize(printed), 0)


if __name__ == "__main__":
    unittest.main()
