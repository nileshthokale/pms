"""End-to-end Counter Sale save workflow on an isolated temporary database.

Covers the review popup's final Save path:
1. empty patient -> WALKIN + genuinely blank Bill No;
2. whitespace-only patient -> WALKIN + blank Bill No;
3. real patient -> preserved name + non-empty Bill No;
4. editing a saved named bill preserves its number;
5. editing a saved unnamed bill keeps the blank Bill No;
6. history (item-wise and bill-wise) shows blank cells and blank tooltips for
   unnamed sales, and numeric numbers for named sales.

The test never opens data/pharmacy.db; PHARMACY_DB points at a fresh temp file.
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
from PySide6.QtWidgets import QApplication, QMessageBox

_app = QApplication.instance() or QApplication([])

from database import auth, financial_year
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
from screens.counter_sale import (
    CounterSalePage,
    SalesBillReviewDialog,
    _BillItemRow,
    _display_bill_no,
    HISTORY_MODE_BILL,
    HISTORY_MODE_ITEM,
)


class TestCounterSaleSaveWorkflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fd, cls._db_path = tempfile.mkstemp(prefix="pharmacy_cs_save_", suffix=".db")
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

        self.company_id = CompanyDAO.insert("Workflow Pharma", "WFP")
        self.unit_id = UnitDAO.insert("Strip")
        self.supplier_id = SupplierDAO.insert("Workflow Supplier")
        self.item_id = ItemDAO.insert(
            item_name="WORKFLOW TEST ITEM",
            unit_id=self.unit_id,
            company_id=self.company_id,
            pack_size="10",
            mrp=100.0,
        )
        PurchaseDAO.insert_invoice(
            voucher_no="PV-WF-1",
            voucher_date="2026-10-01",
            voucher_time="09:00",
            purchase_type="Cash",
            supplier_id=self.supplier_id,
            invoice_no="PINV-WF-1",
            invoice_date="2026-10-01",
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
                "batch_no": "WF-BATCH-1",
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

    def _row(self):
        return _BillItemRow(
            item_id=self.item_id,
            item_name="WORKFLOW TEST ITEM",
            stock_batch_id=self.batch["id"],
            pack_size="10",
            location="",
            batch_no=self.batch["batch_no"],
            expiry=self.batch["expiry"],
            mrp=100.0,
            sale_qty=1.0,
            discount_amount=0.0,
            amount=100.0,
        )

    def _save_through_review(self, patient_name: str):
        # Create WALKIN before the page loads its customer combo.
        walkin_id = CustomerDAO.get_or_create_walkin()
        page = CounterSalePage()
        page.show()
        _app.processEvents()
        panel = page._sale_panel
        walkin_idx = panel.customer_combo.findData(walkin_id)
        if walkin_idx >= 0:
            panel.customer_combo.setCurrentIndex(walkin_idx)
        panel.patient_name_edit.setText(patient_name)
        panel._item_rows.append(self._row())
        panel.paid_edit.setText("100.00")
        panel._recalc_totals()

        dialog = panel._open_review_dialog()
        _app.processEvents()
        dialog._on_final_save()
        _app.processEvents()

        conn = get_connection()
        try:
            saved = conn.execute(
                "SELECT id, bill_no, patient_name FROM sales_invoices "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
        page.close()
        return saved

    def test_01_empty_patient_saves_walkin_with_blank_bill_no(self):
        saved = self._save_through_review("")
        self.assertIsNotNone(saved)
        self.assertEqual(saved["patient_name"], "WALKIN")
        self.assertEqual(saved["bill_no"], "")

    def test_02_whitespace_patient_saves_walkin_with_blank_bill_no(self):
        saved = self._save_through_review("   \t  ")
        self.assertIsNotNone(saved)
        self.assertEqual(saved["patient_name"], "WALKIN")
        self.assertEqual(saved["bill_no"], "")

    def test_03_named_patient_preserved_with_number(self):
        saved = self._save_through_review("MR NILESH THOKALE")
        self.assertIsNotNone(saved)
        self.assertEqual(saved["patient_name"], "MR NILESH THOKALE")
        self.assertTrue(saved["bill_no"].strip())

    def test_04_editing_saved_named_bill_preserves_number(self):
        saved = self._save_through_review("ORIGINAL PATIENT")
        self.assertIsNotNone(saved)
        original_bill_no = saved["bill_no"]
        self.assertTrue(original_bill_no.strip())

        invoice = SalesDAO.get_by_id(saved["id"])
        page = CounterSalePage()
        page.show()
        _app.processEvents()
        dialog = SalesBillReviewDialog(
            page._sale_panel, parent=page, invoice=invoice
        )
        _app.processEvents()
        self.assertNotEqual(dialog._panel.bill_no_edit.text(), "")
        dialog._panel.patient_name_edit.setText("EDITED PATIENT")
        dialog._on_final_save()
        _app.processEvents()

        updated = SalesDAO.get_by_id(saved["id"])
        self.assertEqual(updated["bill_no"], original_bill_no)
        self.assertEqual(updated["patient_name"], "EDITED PATIENT")
        page.close()

    def test_05_editing_saved_unnamed_bill_preserves_blank_bill_no(self):
        saved = self._save_through_review("")
        self.assertIsNotNone(saved)
        self.assertEqual(saved["bill_no"], "")

        invoice = SalesDAO.get_by_id(saved["id"])
        page = CounterSalePage()
        page.show()
        _app.processEvents()
        dialog = SalesBillReviewDialog(
            page._sale_panel, parent=page, invoice=invoice
        )
        _app.processEvents()
        self.assertEqual(
            dialog._panel.bill_no_edit.text(), _display_bill_no(saved["bill_no"])
        )
        dialog._panel.paid_edit.setText("100.00")
        dialog._on_final_save()
        _app.processEvents()

        updated = SalesDAO.get_by_id(saved["id"])
        self.assertEqual(updated["bill_no"], "")
        self.assertEqual(updated["patient_name"], "WALKIN")
        page.close()

    def test_06_history_item_and_bill_wise_display_bill_no_for_all(self):
        unnamed = self._save_through_review("")
        named = self._save_through_review("NAMED HISTORY PATIENT")
        self.assertIsNotNone(unnamed)
        self.assertIsNotNone(named)

        page = CounterSalePage()
        page.show()
        _app.processEvents()
        page._refresh_history()
        _app.processEvents()
        table = page._hist_table

        def row_for(invoice_id):
            for r in range(table.rowCount()):
                cell = table.item(r, 0)
                if cell and cell.data(Qt.UserRole) == invoice_id:
                    return r
            return -1

        unnamed_row = row_for(unnamed["id"])
        named_row = row_for(named["id"])
        self.assertGreaterEqual(unnamed_row, 0)
        self.assertGreaterEqual(named_row, 0)
        self.assertEqual(table.item(unnamed_row, 0).text(), "")
        self.assertEqual(table.item(unnamed_row, 0).toolTip(), "")
        self.assertEqual(table.item(unnamed_row, 6).text(), "WALKIN")
        self.assertTrue(table.item(named_row, 0).text().strip())

        page._set_history_mode(HISTORY_MODE_BILL)
        _app.processEvents()
        unnamed_row = named_row = -1
        for r in range(table.rowCount()):
            cell = table.item(r, 0)
            if not cell:
                continue
            if cell.data(Qt.UserRole) == unnamed["id"]:
                unnamed_row = r
            elif cell.data(Qt.UserRole) == named["id"]:
                named_row = r
        self.assertGreaterEqual(unnamed_row, 0)
        self.assertGreaterEqual(named_row, 0)
        self.assertEqual(table.item(unnamed_row, 0).text(), "")
        self.assertEqual(table.item(unnamed_row, 0).toolTip(), "")
        self.assertEqual(table.item(unnamed_row, 2).text(), "WALKIN")
        self.assertTrue(table.item(named_row, 0).text().strip())
        page.close()


if __name__ == '__main__':
    unittest.main()
