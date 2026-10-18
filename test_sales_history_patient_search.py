"""Regression tests for the Sales History patient-name search.

The patient search must match the WHOLE name the operator types:

1. Every typed word must be found in the stored patient name, in any
   order — "THORVE PRATAP" finds "PRATAP THORVE", "GHADGE MIRA" finds
   "MRS MIRA GHADGE".
2. Single-word (partial) search keeps working, case-insensitively.
3. Pressing Enter while the suggestion list is open searches exactly what
   was typed; the text is never silently replaced by the first suggestion.
4. Explicitly picking a suggestion (mouse click or Down + Enter) searches
   that suggestion immediately.

Runs offscreen: QT_QPA_PLATFORM=offscreen.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from database.connection import get_connection, init_database
from database import auth, financial_year
from database.company_dao import CompanyDAO
from database.customer_dao import CustomerDAO
from database.doctor_dao import DoctorDAO
from database.item_dao import ItemDAO
from database.purchase_dao import PurchaseDAO
from database.sales_dao import SalesDAO
from database.stock_dao import StockDAO
from database.supplier_dao import SupplierDAO
from database.unit_dao import UnitDAO
from database.account_roles import ensure_system_ledgers

from screens.sales_history import SalesHistoryPage


class SalesHistoryPatientSearchTests(unittest.TestCase):
    _DB_PATH = os.path.join(
        tempfile.gettempdir(), "_test_sales_history_patient_search.db"
    )

    _PATIENTS = [
        ("CS-0001", "PRATAP THORVE"),
        ("CS-0002", "PRATAP SINGH KADAM"),
        ("CS-0003", "MRS MIRA GHADGE"),
        ("CS-0004", "MR SANJAY BANSODE"),
    ]

    @classmethod
    def setUpClass(cls):
        if os.path.exists(cls._DB_PATH):
            os.remove(cls._DB_PATH)
        os.environ["PHARMACY_DB"] = cls._DB_PATH
        init_database()
        auth.ensure_auth_schema()
        financial_year.ensure_financial_year_schema()
        financial_year.ensure_default_financial_year()
        if auth.user_count() == 0:
            auth.create_first_admin("admin", "admin-pass-1")
        auth.session.login("admin", "admin-pass-1")
        ensure_system_ledgers()
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        conn = get_connection()
        try:
            for tbl in (
                "ledger_transactions", "sales_invoice_items", "sales_invoices",
                "purchase_invoice_items", "purchase_invoices", "stock_batches",
                "hold_bill_items", "hold_bills", "items", "customers",
                "doctors", "suppliers", "drugs", "units", "companies",
            ):
                try:
                    conn.execute(f"DELETE FROM {tbl}")
                except Exception:
                    pass
            conn.commit()
        finally:
            conn.close()

        financial_year.ensure_default_financial_year()

        company_id = CompanyDAO.insert("TestPharma", "TP")
        unit_id = UnitDAO.insert("Strip")
        supplier_id = SupplierDAO.insert("MainSupplier")
        customer_id = CustomerDAO.insert("Customer Alpha")
        doctor_id = DoctorDAO.insert("Dr. Smith", specialty="General")
        item_id = ItemDAO.insert(
            item_name="Amoxicillin 500mg", unit_id=unit_id,
            company_id=company_id, pack_size="10x10",
        )
        ensure_system_ledgers()

        PurchaseDAO.insert_invoice(
            voucher_no="PV-0001", voucher_date="2025-05-01", voucher_time="10:00",
            purchase_type="Cash", supplier_id=supplier_id,
            invoice_no="PINV-001", invoice_date="2025-05-01",
            invoice_net_amount=5000.0, bill_discount=0, due_date="",
            total_amount=5000.0, gst_amount=0, debit_note_amount=0,
            other_amount=0, paid_amount=5000.0, round_off=0,
            net_amount=5000.0, remarks="",
            items=[{
                "item_id": item_id, "pack_size": "10x10",
                "pay_qty": 200.0, "free_qty": 0, "batch_no": "BATCH-AMOX-01",
                "expiry": "12/28", "rate": 50.0, "mrp": 70.0,
                "discount": 0, "gst_percent": 0, "gst_amount": 0,
                "amount": 5000.0, "purchase_rate": 50.0,
                "net_rate": 50.0, "pp": 50.0,
            }],
        )
        batch_id = StockDAO.get_stock_batches_for_item(item_id)[0]["id"]

        for idx, (bill_no, patient) in enumerate(self._PATIENTS, start=1):
            SalesDAO.insert_invoice(
                bill_no=bill_no, sale_date="2026-10-10",
                sale_time=f"10:0{idx}", sale_type="Cash",
                customer_id=customer_id, patient_name=patient,
                doctor_id=doctor_id, discount=0.0, paid_amount=70.0,
                total_amount=70.0, round_off=0.0, net_amount=70.0, remarks="",
                items=[{
                    "item_id": item_id, "stock_batch_id": batch_id,
                    "pack_size": "10x10", "location": "", "batch_no": "BATCH-AMOX-01",
                    "expiry": "12/28", "mrp": 70.0, "sale_qty": 1.0,
                    "discount_amount": 0.0, "amount": 70.0,
                }],
            )

        for target in (QMessageBox, ):
            for name in ("warning", "information"):
                patcher = mock.patch.object(target, name, return_value=QMessageBox.Ok)
                patcher.start()
                self.addCleanup(patcher.stop)

    def _pump(self, n=3):
        for _ in range(n):
            self._app.processEvents()

    def _make_page(self) -> SalesHistoryPage:
        page = SalesHistoryPage()
        page.show()
        self._pump()
        self.addCleanup(lambda: (page.hide(), page.deleteLater()))
        return page

    def _table_names(self, page: SalesHistoryPage) -> list[str]:
        return [
            page._table.item(r, 2).text() for r in range(page._table.rowCount())
        ]

    def _search(self, page: SalesHistoryPage, text: str) -> list[str]:
        page._patient_edit.setText(text)
        page._on_search_clicked()
        self._pump()
        return self._table_names(page)

    # ------------------------------------------------------------------
    # 1. DAO: every typed word must appear (any order); single word is
    #    the old partial match.
    # ------------------------------------------------------------------
    def test_01_word_order_independent_matching(self):
        rows, total = SalesDAO.search_sales_history(patient_name="THORVE", limit=10)
        self.assertEqual([r["patient_name"] for r in rows], ["PRATAP THORVE"])
        self.assertEqual(total, 1)

        rows, total = SalesDAO.search_sales_history(
            patient_name="THORVE PRATAP", limit=10
        )
        self.assertEqual([r["patient_name"] for r in rows], ["PRATAP THORVE"])

        rows, total = SalesDAO.search_sales_history(
            patient_name="GHADGE MIRA", limit=10
        )
        self.assertEqual([r["patient_name"] for r in rows], ["MRS MIRA GHADGE"])

        # Case-insensitive and word-order independent.
        rows, total = SalesDAO.search_sales_history(
            patient_name="mira ghadge", limit=10
        )
        self.assertEqual([r["patient_name"] for r in rows], ["MRS MIRA GHADGE"])

        # Every word must match — an unmatched word returns nothing.
        rows, total = SalesDAO.search_sales_history(
            patient_name="MIRA NOBODY", limit=10
        )
        self.assertEqual(rows, [])
        self.assertEqual(total, 0)

        # A single first name still matches every patient with that name.
        rows, total = SalesDAO.search_sales_history(patient_name="pratap", limit=10)
        self.assertEqual(
            sorted(r["patient_name"] for r in rows),
            ["PRATAP SINGH KADAM", "PRATAP THORVE"],
        )

    # ------------------------------------------------------------------
    # 2. Page-level search uses the whole typed name in any order.
    # ------------------------------------------------------------------
    def test_02_page_search_whole_name_any_order(self):
        page = self._make_page()

        self.assertEqual(self._search(page, "THORVE PRATAP"), ["PRATAP THORVE"])
        self.assertEqual(self._search(page, "GHADGE MIRA"), ["MRS MIRA GHADGE"])
        self.assertEqual(self._search(page, "SANJAY"), ["MR SANJAY BANSODE"])
        self.assertEqual(self._search(page, "MIRA NOBODY"), [])

        # Reset restores every saved bill.
        page._on_reset_clicked()
        self._pump()
        self.assertEqual(page._table.rowCount(), len(self._PATIENTS))

    # ------------------------------------------------------------------
    # 3. Enter searches the typed text immediately without popup interference.
    # ------------------------------------------------------------------
    def test_03_enter_searches_typed_text_not_first_suggestion(self):
        page = self._make_page()
        field = page._patient_edit
        field.setFocus()
        QTest.keyClicks(field, "pratap")
        self._pump()

        # No disruptive completer popup blocks the screen
        self.assertFalse(hasattr(field, "_completer"))

        QTest.keyClick(field, Qt.Key_Return)
        self._pump()

        # The typed text survives; both matching patients are searched.
        self.assertEqual(field.text(), "PRATAP")
        self.assertEqual(
            sorted(self._table_names(page)),
            ["PRATAP SINGH KADAM", "PRATAP THORVE"],
        )

    # ------------------------------------------------------------------
    # 4. Typing shows available patient names in a dropdown popup;
    #    bottom table does NOT filter while typing ("not direct on bottom");
    #    selecting a suggestion immediately filters the table.
    # ------------------------------------------------------------------
    def test_04_dropdown_shows_available_names_and_filters_on_select(self):
        page = self._make_page()
        field = page._patient_edit

        # All 4 patients initially displayed
        self.assertEqual(len(self._table_names(page)), len(self._PATIENTS))

        # Operator types "thorve"
        field.setFocus()
        QTest.keyClicks(field, "thorve")
        self._pump()
        # Debounce timer fetches suggestions
        field._debounce_timer.timeout.emit()
        self._pump()

        # Input text is uppercase
        self.assertEqual(field.text(), "THORVE")
        # Popup contains matching suggestion(s)
        self.assertTrue(field._popup.isVisible())
        items = [field._popup.item(i).text() for i in range(field._popup.count())]
        self.assertIn("PRATAP THORVE", items)

        # Bottom table is NOT filtered directly on keystroke ("not direct on bottom")
        self.assertEqual(len(self._table_names(page)), len(self._PATIENTS))

        # Picking the item from dropdown
        item = field._popup.item(0)
        field._popup.itemClicked.emit(item)
        self._pump()

        # Input is updated to the picked patient name and table is filtered
        self.assertEqual(field.text(), "PRATAP THORVE")
        self.assertEqual(self._table_names(page), ["PRATAP THORVE"])

    # ------------------------------------------------------------------
    # 5. Paging and the other filters still work with a word search.
    # ------------------------------------------------------------------
    def test_05_search_combines_with_other_filters(self):
        page = self._make_page()

        # A search that matches nothing must show an empty table, not an
        # error, and keep pagination sane.
        self.assertEqual(self._search(page, "NOBODY MATCHES"), [])
        self.assertIn("0 bills", page._page_lbl.text())

        # Date limit far in the future hides everything even though the
        # patient matches.
        page._patient_edit.setText("THORVE")
        page._date_check.setChecked(True)
        page._from_date.setDate(page._from_date.date().addDays(1))
        page._to_date.setDate(page._to_date.date().addDays(2))
        page._on_search_clicked()
        self._pump()
        self.assertEqual(self._table_names(page), [])


if __name__ == "__main__":
    unittest.main()
