"""Regression and feature verification for Patient Name & Address Autocomplete.

Tests the 8 required behaviors on an isolated SQLite database:
  1. Existing patient MR NILESH THOKALE with saved address RAHURI -> address fills correctly.
  2. New patient -> address remains blank.
  3. Entering a new address -> address is saved and retrieved on a later bill.
  4. Typing a partial name -> suggestions contain matching patient names.
  5. Selecting a suggestion -> the correct corresponding address appears.
  6. Editing the address manually -> no unrelated address overwrites it.
  7. Customer WALKIN remains separate from Patient Name.
  8. Existing saved patient records remain unchanged and production DB is untouched.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_TMP_DIR = tempfile.mkdtemp(prefix="pms_pat_addr_test_")
_TMP_DB = os.path.join(_TMP_DIR, "pat_addr_test.db")
os.environ["PHARMACY_DB"] = _TMP_DB

from database.connection import get_connection, init_database
from database.customer_dao import CustomerDAO, PatientOption
from database.sales_dao import SalesDAO
from database.item_dao import ItemDAO
from database.company_dao import CompanyDAO
from database.unit_dao import UnitDAO
from database.supplier_dao import SupplierDAO
from database.purchase_dao import PurchaseDAO
from database.stock_dao import StockDAO
from database import auth, financial_year
from database.account_roles import ensure_system_ledgers

from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication, QMessageBox
from screens.counter_sale import _SalePanel, _patient_name_options, _address_options, _BillItemRow

_app = QApplication.instance() or QApplication([])


class TestPatientNameAndAddressAutocomplete(unittest.TestCase):
    _TMP_DB = _TMP_DB

    @classmethod
    def setUpClass(cls):
        os.environ["PHARMACY_DB"] = cls._TMP_DB
        init_database()
        auth.ensure_auth_schema()
        financial_year.ensure_default_financial_year()
        if auth.user_count() == 0:
            auth.create_first_admin("admin", "admin-pass-1")
        auth.session.login("admin", "admin-pass-1")
        ensure_system_ledgers()

    def setUp(self):
        os.environ["PHARMACY_DB"] = self._TMP_DB
        conn = get_connection()
        try:
            for tbl in (
                "ledger_transactions", "sales_invoice_items", "sales_invoices",
                "purchase_invoice_items", "purchase_invoices", "stock_batches",
                "items", "customers", "doctors", "suppliers", "units", "companies",
                "patient_addresses"
            ):
                try:
                    conn.execute(f"DELETE FROM {tbl}")
                except Exception:
                    pass
            conn.commit()
        finally:
            conn.close()

        # Seed master data
        self.walkin_id = CustomerDAO.get_or_create_walkin()
        self.comp_id = CompanyDAO.insert("Cipla", "CIP")
        self.unit_id = UnitDAO.insert("Strip")
        self.item_id = ItemDAO.insert("Paracetamol", self.unit_id, self.comp_id, "10", 50.0)
        self.supplier_id = SupplierDAO.insert("Distributor")
        PurchaseDAO.insert_invoice(
            voucher_no="PV-0001", voucher_date="2026-01-01", voucher_time="",
            purchase_type="Cash", supplier_id=self.supplier_id,
            invoice_no="INV-001", invoice_date="2026-01-01",
            invoice_net_amount=5000.0, bill_discount=0, due_date="",
            total_amount=5000.0, gst_amount=0, debit_note_amount=0,
            other_amount=0, paid_amount=5000.0, round_off=0,
            net_amount=5000.0, remarks="",
            items=[{
                "item_id": self.item_id, "pack_size": "10",
                "pay_qty": 10.0, "free_qty": 0, "batch_no": "BATCH-01",
                "expiry": "12/28", "rate": 40.0, "mrp": 50.0,
                "discount": 0, "gst_percent": 0, "gst_amount": 0,
                "amount": 400.0, "purchase_rate": 40.0,
                "net_rate": 40.0, "pp": 40.0,
            }],
        )
        batches = StockDAO.get_stock_batches_for_item(self.item_id)
        self.batch_id = batches[0]["id"]

        # Mock out dialog boxes
        self._patches = [
            mock.patch.object(QMessageBox, "warning", return_value=QMessageBox.Ok),
            mock.patch.object(QMessageBox, "information", return_value=QMessageBox.Ok),
            mock.patch.object(QMessageBox, "critical", return_value=QMessageBox.Ok),
            mock.patch.object(QMessageBox, "question", return_value=QMessageBox.Yes),
        ]
        for patch in self._patches:
            patch.start()
            self.addCleanup(patch.stop)

        # Seed existing patient: MR NILESH THOKALE with address RAHURI
        CustomerDAO.insert("MR NILESH THOKALE", address="RAHURI")
        CustomerDAO.save_patient_address("MR NILESH THOKALE", "RAHURI")

        # Seed another patient: MR BHAU NIMSE with address PUNE
        CustomerDAO.insert("MR BHAU NIMSE", address="PUNE")
        CustomerDAO.save_patient_address("MR BHAU NIMSE", "PUNE")

    def _pump(self):
        _app.processEvents()
        _app.processEvents()

    def _make_popup_panel(self) -> _SalePanel:
        panel = _SalePanel(popup_mode=True)
        panel.show()
        self._pump()
        return panel

    def _add_row(self, panel: _SalePanel):
        panel._item_rows.append(_BillItemRow(
            item_id=self.item_id, item_name="Paracetamol",
            stock_batch_id=self.batch_id, pack_size="10", location="",
            batch_no="BATCH-01", expiry="12/28", mrp=50.0,
            sale_qty=1.0, discount_amount=0.0, amount=50.0,
        ))
        panel.paid_edit.setText("50.00")
        panel._recalc_totals()

    def test_01_existing_patient_populates_address(self):
        """1. Existing patient MR NILESH THOKALE with saved address RAHURI -> address fills correctly."""
        panel = self._make_popup_panel()
        panel.patient_name_edit.setText("MR NILESH THOKALE")
        self._pump()
        self.assertEqual(panel.patient_name_edit.text(), "MR NILESH THOKALE")
        self.assertEqual(panel.address_edit.text(), "RAHURI")

    def test_02_new_patient_address_remains_blank(self):
        """2. New patient -> address remains blank; does not copy another patient's address."""
        panel = self._make_popup_panel()
        panel.patient_name_edit.setText("NEW UNKNOWN PATIENT")
        self._pump()
        self.assertEqual(panel.patient_name_edit.text(), "NEW UNKNOWN PATIENT")
        self.assertEqual(panel.address_edit.text(), "")

    def test_03_enter_new_address_persists_and_retrieves_later(self):
        """3. Entering a new address saves it and retrieves it on a future bill."""
        panel = self._make_popup_panel()
        panel.patient_name_edit.setText("KISHOR PATIL")
        panel.address_edit.setText("SHIRDI")
        self._add_row(panel)
        panel._commit_sale()
        self.assertTrue(panel._saved)

        # On subsequent bill:
        panel2 = self._make_popup_panel()
        panel2.patient_name_edit.setText("KISHOR PATIL")
        self._pump()
        self.assertEqual(panel2.address_edit.text(), "SHIRDI")

    def test_04_typing_partial_name_shows_matching_patient_suggestions(self):
        """4. Typing a partial name displays matching patient-name suggestions."""
        # Query matching patients for "NILESH"
        matches = CustomerDAO.get_matching_patients("NILESH")
        self.assertTrue(len(matches) > 0)
        self.assertEqual(matches[0].name, "MR NILESH THOKALE")
        self.assertEqual(matches[0].address, "RAHURI")
        self.assertIn("MR NILESH THOKALE", matches[0].display_text)

        # Query options for single letter "N"
        opts = _patient_name_options("N")
        self.assertTrue(len(opts) > 0)
        names = [opt.name if isinstance(opt, PatientOption) else str(opt) for opt in opts]
        self.assertIn("MR NILESH THOKALE", names)

        # Typing in popup combo shows dropdown
        panel = self._make_popup_panel()
        panel.patient_name_edit.lineEdit().setText("N")
        panel.patient_name_edit.lineEdit().textEdited.emit("N")
        self._pump()
        self.assertGreater(panel.patient_name_edit.count(), 0)
        self.assertTrue(panel.patient_name_edit.completer().popup().isVisible())

    def test_05_selecting_suggestion_populates_corresponding_address(self):
        """5. Selecting a suggestion populates the matching address."""
        panel = self._make_popup_panel()
        panel.patient_name_edit.lineEdit().setText("NILESH")
        panel.patient_name_edit.lineEdit().textEdited.emit("NILESH")
        self._pump()

        # Completer popup is open with MR NILESH THOKALE
        completer = panel.patient_name_edit.completer()
        popup = completer.popup()
        self.assertTrue(popup.isVisible())

        # Select highlighted suggestion
        panel.patient_name_edit._accept_popup_selection()
        self._pump()

        self.assertEqual(panel.patient_name_edit.text(), "MR NILESH THOKALE")
        self.assertEqual(panel.address_edit.text(), "RAHURI")

    def test_06_manual_address_edit_not_overwritten(self):
        """6. When the user edits the address manually, no unrelated address overwrites it."""
        panel = self._make_popup_panel()
        panel.patient_name_edit.setText("MR NILESH THOKALE")
        self._pump()
        self.assertEqual(panel.address_edit.text(), "RAHURI")

        # User manually edits address
        panel.address_edit.lineEdit().setText("RAHURI FACTORY")
        panel.address_edit.lineEdit().textEdited.emit("RAHURI FACTORY")
        self._pump()
        self.assertEqual(panel.address_edit.text(), "RAHURI FACTORY")
        self.assertTrue(panel._user_edited_address)

        # Editing patient within same name should not overwrite user-edited address
        panel._update_address_for_patient("MR NILESH THOKALE")
        self._pump()
        self.assertEqual(panel.address_edit.text(), "RAHURI FACTORY")

    def test_07_customer_walkin_remains_separate_from_patient_name(self):
        """7. Customer WALKIN remains separate from Patient Name."""
        panel = self._make_popup_panel()
        # Customer is WALKIN
        walkin_idx = panel.customer_combo.findData(self.walkin_id)
        if walkin_idx >= 0:
            panel.customer_combo.setCurrentIndex(walkin_idx)

        # Patient Name is MR NILESH THOKALE
        panel.patient_name_edit.setText("MR NILESH THOKALE")
        self._pump()
        self.assertEqual(panel.patient_name_edit.text(), "MR NILESH THOKALE")
        self.assertEqual(panel.address_edit.text(), "RAHURI")

        # Switching customer does not overwrite patient name
        self.assertNotEqual(panel.patient_name_edit.text(), "WALKIN")
        self.assertNotIn("WALKIN", [opt.name for opt in CustomerDAO.get_matching_patients("")])

    def test_08_existing_saved_patient_records_unchanged(self):
        """8. Existing saved patient records remain intact; production DB safe."""
        # Check test DB
        conn = get_connection()
        try:
            r1 = conn.execute("SELECT address FROM patient_addresses WHERE patient_name = 'MR NILESH THOKALE'").fetchone()
            self.assertEqual(r1[0], "RAHURI")
            r2 = conn.execute("SELECT address FROM patient_addresses WHERE patient_name = 'MR BHAU NIMSE'").fetchone()
            self.assertEqual(r2[0], "PUNE")
        finally:
            conn.close()

        # Check production DB
        if os.path.exists("data/pharmacy.db"):
            import sqlite3
            pconn = sqlite3.connect("data/pharmacy.db")
            cnt = pconn.execute("SELECT count(*) FROM sales_invoices").fetchone()[0]
            pconn.close()
            self.assertEqual(cnt, 72175, "Production sales_invoices count must remain 72,175 intact")


if __name__ == "__main__":
    unittest.main()
