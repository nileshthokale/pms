"""Isolated verification for Sales Bill History and empty Patient Names.

Rules verified:
1. Empty/whitespace stored patient -> blank Bill No display; named -> numeric.
2. Counter Sale history, Sales History table and details dialog agree.
3. Editing a historical unnamed bill keeps its stored number unchanged and
   keeps the blank display while the patient name is empty.
4. Searching by the stored identifier still finds the record.
5. Historical rows, ids, and stock are not modified by display/search.

The test uses a disposable SQLite database and never touches data/pharmacy.db.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QApplication, QMessageBox

_app = QApplication.instance() or QApplication(sys.argv)

from core.doc_formatter import format_sales_bill_number
from database import auth, financial_year
from database.account_roles import ensure_system_ledgers
from database.connection import get_connection, init_database
from database.sales_dao import SalesDAO
from screens.counter_sale import CounterSalePage, _display_bill_no
from screens.sales_history import SalesBillDetailsDialog, SalesHistoryPage, _fmt_bill_no


HISTORICAL_BILL = "2026-2027-Cash-187-S72213"
GENUINE_BILL = "2026-2027-1905"


class TestBlankBillNoForEmptyPatient(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fd, cls._db_path = tempfile.mkstemp(prefix="pharmacy_history_blank_", suffix=".db")
        os.close(fd)
        cls._previous_db = os.environ.get("PHARMACY_DB")
        os.environ["PHARMACY_DB"] = cls._db_path
        init_database()
        auth.ensure_auth_schema()
        financial_year.ensure_financial_year_schema()
        financial_year.ensure_default_financial_year()
        if auth.user_count() == 0:
            auth.create_first_admin("admin", "admin-pass-1")
        auth.session.login("admin", "admin-pass-1")
        ensure_system_ledgers()

        conn = get_connection()
        try:
            cur = conn.execute(
                "INSERT INTO sales_invoices ("
                "bill_no, sale_date, sale_time, sale_type, customer_id, "
                "patient_name, doctor_id, discount, paid_amount, total_amount, "
                "round_off, net_amount, remarks"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (HISTORICAL_BILL, "2020-01-15", "11:09", "Cash", None,
                 "", None, 0.0, 51.0, 51.0, 0.0, 51.0,
                 "Legacy salesvhheader ID 72213; BillNo 0"),
            )
            cls.historical_id = cur.lastrowid
            cur = conn.execute(
                "INSERT INTO sales_invoices ("
                "bill_no, sale_date, sale_time, sale_type, customer_id, "
                "patient_name, doctor_id, discount, paid_amount, total_amount, "
                "round_off, net_amount, remarks"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (GENUINE_BILL, "2020-01-15", "12:00", "Cash", None,
                 "HISTORICAL PATIENT", None, 0.0, 51.0, 51.0, 0.0, 51.0,
                 "Legacy salesvhheader ID 10; BillNo 1905"),
            )
            cls.genuine_id = cur.lastrowid
            conn.commit()
        finally:
            conn.close()

    @classmethod
    def tearDownClass(cls):
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(cls._db_path + suffix)
            except FileNotFoundError:
                pass
        if cls._previous_db is None:
            os.environ.pop("PHARMACY_DB", None)
        else:
            os.environ["PHARMACY_DB"] = cls._previous_db

    def test_01_formatter_rules(self):
        self.assertEqual(format_sales_bill_number(HISTORICAL_BILL, patient_name=""), "")
        self.assertEqual(format_sales_bill_number(HISTORICAL_BILL, patient_name="   "), "")
        self.assertEqual(format_sales_bill_number(HISTORICAL_BILL, patient_name=None), "187")
        self.assertEqual(format_sales_bill_number(HISTORICAL_BILL, patient_name="John"), "187")
        self.assertEqual(SalesDAO.display_bill_no(HISTORICAL_BILL, patient_name=""), "")
        self.assertEqual(_display_bill_no(HISTORICAL_BILL, patient_name=""), "")
        self.assertEqual(_fmt_bill_no(HISTORICAL_BILL, patient_name=""), "")
        self.assertEqual(_fmt_bill_no(None, patient_name="John"), "")

    def test_02_history_table_and_details_dialog(self):
        page = SalesHistoryPage()
        page.show()
        page._date_check.setChecked(True)
        page._from_date.setDate(QDate.fromString("2020-01-15", "yyyy-MM-dd"))
        page._to_date.setDate(QDate.fromString("2020-01-15", "yyyy-MM-dd"))
        page._perform_search()
        _app.processEvents()

        rows = {}
        for r in range(page._table.rowCount()):
            cell = page._table.item(r, 0)
            if cell:
                rows[cell.data(0x0100)] = r
        self.assertIn(self.historical_id, rows)
        self.assertIn(self.genuine_id, rows)

        hist_row = rows[self.historical_id]
        self.assertEqual(page._table.item(hist_row, 0).text(), "")
        self.assertEqual(page._table.item(hist_row, 0).toolTip(), "")
        self.assertEqual(page._table.item(hist_row, 2).text(), "WALKIN")

        gen_row = rows[self.genuine_id]
        self.assertEqual(page._table.item(gen_row, 0).text(), "1905")
        self.assertEqual(page._table.item(gen_row, 2).text(), "HISTORICAL PATIENT")
        page.close()

        dialog = SalesBillDetailsDialog(self.historical_id)
        grid = dialog._meta_group.layout()
        self.assertEqual(grid.itemAtPosition(0, 1).widget().text(), "")
        self.assertEqual(grid.itemAtPosition(1, 1).widget().text(), "WALKIN")
        dialog.close()

        dialog = SalesBillDetailsDialog(self.genuine_id)
        grid = dialog._meta_group.layout()
        self.assertEqual(grid.itemAtPosition(0, 1).widget().text(), "1905")
        self.assertEqual(grid.itemAtPosition(1, 1).widget().text(), "HISTORICAL PATIENT")
        dialog.close()

    def test_03_editing_historical_unnamed_bill(self):
        invoice = SalesDAO.get_by_id(self.historical_id)
        self.assertEqual((invoice["patient_name"] or "").strip(), "")

        page = CounterSalePage()
        page.show()
        _app.processEvents()
        panel = page._sale_panel
        panel.load_invoice(invoice)
        _app.processEvents()

        self.assertEqual(panel.bill_no_edit.text(), "")
        panel.patient_name_edit.setText("REAL PATIENT")
        _app.processEvents()
        self.assertEqual(panel.bill_no_edit.text(), "187")
        panel.patient_name_edit.setText("   ")
        _app.processEvents()
        self.assertEqual(panel.bill_no_edit.text(), "")

        panel.paid_edit.setText("51.00")
        with mock.patch.object(QMessageBox, "critical", return_value=QMessageBox.Ok):
            panel._commit_sale()
        _app.processEvents()
        page.close()

        stored = SalesDAO.get_by_id(self.historical_id)
        self.assertEqual(stored["bill_no"], HISTORICAL_BILL)
        self.assertEqual((stored["patient_name"] or "").strip(), "")

    def test_04_search_by_stored_identifier(self):
        rows, total = SalesDAO.search_sales_history(bill_no="187", limit=50)
        self.assertGreater(total, 0)
        matched = [r for r in rows if r["id"] == self.historical_id]
        self.assertEqual(len(matched), 1)
        self.assertEqual(
            _fmt_bill_no(
                matched[0]["bill_no"],
                patient_name=matched[0]["patient_name"],
            ),
            "",
        )

    def test_05_history_display_does_not_change_storage(self):
        conn = get_connection()
        try:
            before = [
                dict(conn.execute(
                    "SELECT * FROM sales_invoices WHERE id = ?", (invoice_id,)
                ).fetchone())
                for invoice_id in (self.historical_id, self.genuine_id)
            ]
        finally:
            conn.close()

        self.test_02_history_table_and_details_dialog()

        conn = get_connection()
        try:
            after = [
                dict(conn.execute(
                    "SELECT * FROM sales_invoices WHERE id = ?", (invoice_id,)
                ).fetchone())
                for invoice_id in (self.historical_id, self.genuine_id)
            ]
        finally:
            conn.close()
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
