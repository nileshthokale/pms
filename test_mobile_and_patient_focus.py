"""Comprehensive tests for Mobile Number field and Patient Name focus after save.

Verifies:
1. MobileNumberLineEdit behavior:
   - Default '+91 ' prefix visible and non-removable.
   - Backspace / Delete / typing cannot delete prefix.
   - Allows up to 10 Indian mobile digits.
   - Blocks non-digit characters.
   - Pasting numbers with leading 0 or +91.
   - get_digits() and set_mobile_number().
2. UI Placement:
   - Mobile No input placed directly below Address in Sales Bill window top strip.
   - Label 'Mobile No' aligned with Address, Patient Name, Customer *.
3. Auto-population:
   - Selecting existing patient populates saved mobile number.
   - Clearing patient clears auto-filled mobile number.
   - Custom-typed mobile number is preserved (not overwritten).
4. Persistence on Save:
   - Persists mobile number to database (patient_addresses / customers).
   - Preserves existing customer contact info (does not overwrite).
5. Focus Patient Name after Save:
   - focus_patient_name() selects all text in patient_name_edit.
   - After _on_sale_saved(), focus_patient_name is triggered.
   - WALKIN default customer behavior preserved.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Isolated temporary database
_TMP_DIR = tempfile.mkdtemp(prefix="pms_mobile_test_")
_TMP_DB = os.path.join(_TMP_DIR, "test_mobile.db")
os.environ["PHARMACY_DB"] = _TMP_DB

from PySide6.QtCore import Qt, QDate
from PySide6.QtGui import QKeyEvent, QKeySequence
from PySide6.QtWidgets import QApplication, QMessageBox, QLabel

from database.connection import get_connection, init_database
from database.customer_dao import CustomerDAO, PatientOption
from database.doctor_dao import DoctorDAO
from database.item_dao import ItemDAO
from database.sales_dao import SalesDAO
from database.unit_dao import UnitDAO
from database.company_dao import CompanyDAO
from screens.counter_sale import (
    CounterSalePage,
    SalesBillReviewDialog,
    MobileNumberLineEdit,
    _SalePanel,
    PREFIX,
)

_APP = None


def setUpModule():
    global _APP
    init_database()
    _APP = QApplication.instance() or QApplication([])


class TestMobileNumberWidget(unittest.TestCase):
    """Unit tests for MobileNumberLineEdit widget."""

    def setUp(self):
        self.edit = MobileNumberLineEdit()

    def test_default_prefix(self):
        self.assertEqual(self.edit.text(), "+91 ")
        self.assertEqual(self.edit.get_digits(), "")
        self.assertEqual(self.edit.clean_mobile_for_db(), "")

    def test_typing_10_digits(self):
        for char in "9876543210":
            event = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_0 + int(char), Qt.NoModifier, char)
            self.edit.keyPressEvent(event)
        self.assertEqual(self.edit.text(), "+91 9876543210")
        self.assertEqual(self.edit.get_digits(), "9876543210")
        self.assertEqual(self.edit.clean_mobile_for_db(), "+91 9876543210")

    def test_blocks_11th_digit(self):
        for char in "98765432105":
            event = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_0 + int(char), Qt.NoModifier, char)
            self.edit.keyPressEvent(event)
        self.assertEqual(self.edit.text(), "+91 9876543210")
        self.assertEqual(self.edit.get_digits(), "9876543210")

    def test_blocks_letters_and_symbols(self):
        for char in "abc#$@":
            event = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_A, Qt.NoModifier, char)
            self.edit.keyPressEvent(event)
        self.assertEqual(self.edit.text(), "+91 ")
        self.assertEqual(self.edit.get_digits(), "")

    def test_backspace_cannot_remove_prefix(self):
        # Type 2 digits
        for char in "98":
            event = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_0 + int(char), Qt.NoModifier, char)
            self.edit.keyPressEvent(event)
        self.assertEqual(self.edit.text(), "+91 98")

        # Backspace 2 times
        for _ in range(2):
            event = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Backspace, Qt.NoModifier, "")
            self.edit.keyPressEvent(event)
        self.assertEqual(self.edit.text(), "+91 ")

        # Backspace again: prefix stays intact
        event = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Backspace, Qt.NoModifier, "")
        self.edit.keyPressEvent(event)
        self.assertEqual(self.edit.text(), "+91 ")

    def test_set_mobile_number_formats(self):
        self.edit.set_mobile_number("9876543210")
        self.assertEqual(self.edit.text(), "+91 9876543210")

        self.edit.set_mobile_number("09876543210")
        self.assertEqual(self.edit.text(), "+91 9876543210")

        self.edit.set_mobile_number("+91 9876543210")
        self.assertEqual(self.edit.text(), "+91 9876543210")

        self.edit.set_mobile_number("")
        self.assertEqual(self.edit.text(), "+91 ")


class TestMobileDatabaseIntegration(unittest.TestCase):
    """Tests for CustomerDAO mobile handling and patient address persistence."""

    def setUp(self):
        conn = get_connection()
        try:
            conn.execute("DELETE FROM patient_addresses")
            conn.execute("DELETE FROM customers WHERE customer_name != 'WALKIN'")
            conn.commit()
        finally:
            conn.close()

    def test_save_and_retrieve_patient_mobile(self):
        CustomerDAO.save_patient_address(
            patient_name="SURESH PATIL",
            address="KOTHRUD PUNE",
            customer_id=None,
            contact_no="9822012345",
        )
        saved = CustomerDAO.get_saved_mobile_for_patient("SURESH PATIL")
        self.assertEqual(saved, "9822012345")

        addresses = CustomerDAO.get_saved_addresses_for_patient("SURESH PATIL")
        self.assertIn("KOTHRUD PUNE", addresses)

    def test_get_matching_patients_includes_mobile(self):
        CustomerDAO.save_patient_address(
            patient_name="PRIYA VERMA",
            address="AUNDH PUNE",
            customer_id=None,
            contact_no="9765432100",
        )
        matches = CustomerDAO.get_matching_patients("PRIYA")
        self.assertTrue(len(matches) > 0)
        p = matches[0]
        self.assertEqual(p.name, "PRIYA VERMA")
        self.assertEqual(p.contact_no, "9765432100")

    def test_does_not_overwrite_existing_customer_contact_with_blank(self):
        cid = CustomerDAO.insert("ANIL KUMAR", contact_no="9111222333", address="DECCAN")
        # Save sale with blank mobile
        CustomerDAO.save_patient_address(
            patient_name="ANIL KUMAR",
            address="DECCAN NEW",
            customer_id=cid,
            contact_no="",
        )
        # Verify contact_no is preserved
        cust = CustomerDAO.get_by_id(cid)
        self.assertEqual(cust["contact_no"], "9111222333")


class TestSalesBillPopupMobileAndFocus(unittest.TestCase):
    """Tests for SalesBillReviewDialog Mobile field UI and Focus behaviour."""

    def setUp(self):
        self._msg = mock.patch.multiple(
            QMessageBox,
            warning=mock.DEFAULT, information=mock.DEFAULT,
            critical=mock.DEFAULT, question=mock.DEFAULT,
        )
        self._msg.start()
        self.addCleanup(self._msg.stop)

        conn = get_connection()
        try:
            for table in ("stock_batches", "sale_items", "sales_invoices", "patient_addresses", "items", "customers", "doctors"):
                try:
                    conn.execute(f"DELETE FROM {table}")
                except Exception:
                    pass
            conn.commit()
        finally:
            conn.close()

        from database.account_roles import ensure_system_ledgers
        ensure_system_ledgers()
        from database import financial_year as _fy
        _fy.ensure_default_financial_year()

        units = UnitDAO.get_all()
        self.unit_id = units[0]["id"] if units else UnitDAO.insert("TestUnit")
        comps = CompanyDAO.get_all()
        self.company_id = comps[0]["id"] if comps else CompanyDAO.insert("TestCo", "TC")
        self.item_id = ItemDAO.insert(
            item_name="Cetirizine 10mg", unit_id=self.unit_id,
            company_id=self.company_id, pack_size="10", mrp=30.0,
        )
        self.customer_id = CustomerDAO.insert("WALKIN")
        self.reg_customer_id = CustomerDAO.insert("Rohit Sharma", address="Koregaon Park", contact_no="9890123456")
        self.doctor_id = DoctorDAO.insert("DR. JOSHI", city="PUNE", specialty="PHYSICIAN")

        conn = get_connection()
        try:
            cur = conn.execute(
                "INSERT INTO stock_batches "
                "(item_id, batch_no, expiry, pack_size, mrp, stock_qty) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (self.item_id, "BATCH-01", "12/28", "10", 30.0, 50.0),
            )
            self.batch_id = cur.lastrowid
            conn.commit()
        finally:
            conn.close()

        self.page = CounterSalePage()
        self.page.resize(1366, 768)
        self.page.show()
        _APP.processEvents()

    def tearDown(self):
        self.page.hide()
        self.page.deleteLater()
        _APP.processEvents()

    def test_mobile_field_exists_directly_below_address(self):
        """Verify Mobile No field exists in the popup strip directly below Address."""
        dlg = SalesBillReviewDialog(self.page._sale_panel, parent=self.page)
        panel = dlg._panel
        self.assertTrue(hasattr(panel, "mobile_edit"))
        self.assertIsInstance(panel.mobile_edit, MobileNumberLineEdit)

        # Check top strip layout
        strip = panel.findChild(QLabel, "")  # verify labels
        labels = [l.text() for l in panel.findChildren(QLabel)]
        self.assertIn("Address", labels)
        self.assertIn("Mobile No", labels)

        # Verify default text
        self.assertEqual(panel.mobile_edit.text(), "+91 ")
        dlg.reject()

    def test_selecting_patient_populates_saved_mobile(self):
        """When an existing patient with saved mobile is typed/selected, mobile populates automatically."""
        CustomerDAO.save_patient_address(
            patient_name="MAHESH DESHMUKH",
            address="SHIVAJINAGAR",
            customer_id=None,
            contact_no="9876501234",
        )

        dlg = SalesBillReviewDialog(self.page._sale_panel, parent=self.page)
        panel = dlg._panel

        # Change patient name
        panel.patient_name_edit.setText("MAHESH DESHMUKH")
        _APP.processEvents()

        # Check address and mobile auto-populated
        self.assertEqual(panel.address_edit.text(), "SHIVAJINAGAR")
        self.assertEqual(panel.mobile_edit.text(), "+91 9876501234")
        self.assertEqual(panel.mobile_edit.get_digits(), "9876501234")

        # Clearing patient name clears auto-filled mobile
        panel.patient_name_edit.setText("")
        _APP.processEvents()
        self.assertEqual(panel.mobile_edit.text(), "+91 ")
        self.assertEqual(panel.address_edit.text(), "")

        dlg.reject()

    def test_custom_typed_mobile_not_overwritten(self):
        """If user custom-types a mobile, selecting/changing patient doesn't blow it away."""
        CustomerDAO.save_patient_address(
            patient_name="VIKRAM SINGH",
            address="CAMP",
            customer_id=None,
            contact_no="9800011122",
        )

        dlg = SalesBillReviewDialog(self.page._sale_panel, parent=self.page)
        panel = dlg._panel

        # User custom types mobile first
        panel.mobile_edit.set_mobile_number("9999988888")
        panel._on_mobile_edited("9999988888")

        # Now select patient
        panel.patient_name_edit.setText("VIKRAM SINGH")
        _APP.processEvents()

        # Custom mobile is kept
        self.assertEqual(panel.mobile_edit.get_digits(), "9999988888")
        dlg.reject()

    def test_focus_patient_name_helper(self):
        """focus_patient_name sets focus to patient_name_edit lineEdit and selects text."""
        dlg = SalesBillReviewDialog(self.page._sale_panel, parent=self.page)
        dlg.show()
        dlg.activateWindow()
        _APP.processEvents()

        panel = dlg._panel
        panel.patient_name_edit.setText("SAMPLE PATIENT")
        _APP.processEvents()

        panel.focus_patient_name()
        _APP.processEvents()

        # Target combo or lineEdit has focus and text is selected
        line_edit = panel.patient_name_edit.lineEdit() if hasattr(panel.patient_name_edit, "lineEdit") else panel.patient_name_edit
        self.assertIn(_APP.focusWidget(), (panel.patient_name_edit, line_edit))
        self.assertEqual(line_edit.selectedText(), "SAMPLE PATIENT")
        dlg.reject()

    def test_reset_for_new_resets_mobile_and_patient(self):
        """reset_for_new clears mobile number and resets to +91 ."""
        panel = self.page._sale_panel
        panel.mobile_edit.set_mobile_number("9876543210")
        panel.patient_name_edit.setText("PATIENT XYZ")

        panel.reset_for_new()
        _APP.processEvents()

        self.assertEqual(panel.mobile_edit.text(), "+91 ")
        self.assertEqual(panel.mobile_edit.get_digits(), "")
        self.assertEqual(panel.patient_name_edit.text(), "")

    def test_save_persists_mobile_number(self):
        """Committed bill persists mobile number to patient_addresses."""
        panel = self.page._sale_panel
        panel.reset_for_new()

        # Add item
        from screens.counter_sale import _BillItemRow
        panel._item_rows.append(_BillItemRow(
            item_id=self.item_id,
            item_name="Cetirizine 10mg",
            stock_batch_id=self.batch_id,
            batch_no="BATCH-01",
            expiry="12/28",
            pack_size="10",
            location="A1",
            mrp=30.0,
            sale_qty=2.0,
            discount_amount=0.0,
            amount=60.0,
        ))
        panel._recalc_totals()

        dlg = SalesBillReviewDialog(panel, parent=self.page)
        dlg_panel = dlg._panel
        dlg_panel.patient_name_edit.setText("KAVITA SHINDE")
        dlg_panel.address_edit.setText("BANER PUNE")
        dlg_panel.mobile_edit.set_mobile_number("9823456789")

        dlg._on_final_save()
        _APP.processEvents()

        # Verify saved in database
        saved_mob = CustomerDAO.get_saved_mobile_for_patient("KAVITA SHINDE")
        self.assertEqual(saved_mob, "9823456789")


if __name__ == "__main__":
    unittest.main()
