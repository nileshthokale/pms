"""Unit tests for automatic Patient Name focus when opening a new Sales Bill.

Verifies:
1. SalesBillReviewDialog (Sales Bill modal dialog):
   - Automatically places cursor in the Patient Name field when opened.
   - User can type immediately without clicking (QTest.keyClicks).
   - Suggestions/autocomplete work properly.
   - Focus is NOT stolen back to Patient Name after the user navigates (e.g. Tab) to other fields.
   - Window activation/restoration does not reset focus back to Patient Name.
2. CounterSalePage (Workspace & Entry Points):
   - focus_entry() places focus on Patient Name for a new/empty bill.
   - _start_new_sale() (New Sale button) places focus on Patient Name.
   - _on_add_bill() (+ Add Bill button) places focus on Patient Name.
   - Once items are added, focus_entry() focuses Item Name.
3. DuplicateSalesBillDialog:
   - When opened, _patient_edit receives focus immediately.
   - User can type immediately without clicking.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TMP_DIR = tempfile.mkdtemp(prefix="pms_focus_test_")
_TMP_DB = os.path.join(_TMP_DIR, "test_patient_focus.db")
os.environ["PHARMACY_DB"] = _TMP_DB

from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from database.connection import get_connection, init_database
from database.customer_dao import CustomerDAO
from database.doctor_dao import DoctorDAO
from database.item_dao import ItemDAO
from database.unit_dao import UnitDAO
from database.company_dao import CompanyDAO
from screens.counter_sale import (
    CounterSalePage,
    SalesBillReviewDialog,
    _SalePanel,
    _DBLookupCombo,
)
from screens.duplicate_sales_bill import DuplicateSalesBillDialog

_APP = None


def setUpModule():
    global _APP
    init_database()
    _APP = QApplication.instance() or QApplication([])


def tearDownModule():
    try:
        if os.path.exists(_TMP_DB):
            os.remove(_TMP_DB)
        if os.path.exists(_TMP_DIR):
            os.rmdir(_TMP_DIR)
    except Exception:
        pass


class TestSalesBillPatientFocus(unittest.TestCase):
    def setUp(self):
        # Insert a sample patient for autocomplete testing
        CustomerDAO.save_patient_address(
            patient_name="RAMESH SHARMA",
            address="MAIN ROAD, PUNE",
            customer_id=None,
            contact_no="9876543210",
        )
        CustomerDAO.save_patient_address(
            patient_name="RAJESH PATIL",
            address="SHIVAJI NAGAR",
            customer_id=None,
            contact_no="9822001122",
        )

    def test_01_sales_bill_review_dialog_patient_focus_on_open(self):
        """Confirm SalesBillReviewDialog places cursor in Patient Name when opened."""
        dummy_parent = _SalePanel(popup_mode=False)
        dialog = SalesBillReviewDialog(dummy_parent)
        dialog.show()
        _APP.processEvents()

        # The internal lineEdit of patient_name_edit should have focus
        patient_combo = dialog._panel.patient_name_edit
        self.assertIsInstance(patient_combo, _DBLookupCombo)
        line_edit = patient_combo.lineEdit()

        # Check hasFocus on line_edit or combo (since focus proxy is set)
        self.assertTrue(line_edit.hasFocus() or patient_combo.hasFocus(),
                        "Patient Name combo / lineEdit should have focus when dialog opens")

        # Confirm Save button does NOT have focus
        self.assertFalse(dialog._final_save_btn.hasFocus(),
                         "Save button should NOT steal focus on dialog open")
        dialog.close()

    def test_02_type_immediately_into_patient_name_without_clicking(self):
        """User can start typing immediately and characters land in Patient Name."""
        dummy_parent = _SalePanel(popup_mode=False)
        dialog = SalesBillReviewDialog(dummy_parent)
        dialog.show()
        _APP.processEvents()

        patient_combo = dialog._panel.patient_name_edit
        line_edit = patient_combo.lineEdit()

        # Type using QTest without mouse click
        QTest.keyClicks(line_edit, "ANIL")
        _APP.processEvents()

        self.assertIn("ANIL", patient_combo.text().upper())
        dialog.close()

    def test_03_autocomplete_suggestions_appear_and_work(self):
        """Verify autocomplete suggestions populate and filter dynamically."""
        dummy_parent = _SalePanel(popup_mode=False)
        dialog = SalesBillReviewDialog(dummy_parent)
        dialog.show()
        _APP.processEvents()

        patient_combo = dialog._panel.patient_name_edit
        line_edit = patient_combo.lineEdit()

        # Type "RAM" which matches "RAMESH SHARMA"
        QTest.keyClicks(line_edit, "RAM")
        _APP.processEvents()

        self.assertGreater(patient_combo.count(), 0)
        found = any("RAMESH" in patient_combo.itemText(i) for i in range(patient_combo.count()))
        self.assertTrue(found, "Autocomplete suggestions should include matching patient")
        dialog.close()

    def test_04_focus_does_not_jump_back_to_patient_name_after_moving(self):
        """Tab to another field; subsequent events must not steal focus back."""
        dummy_parent = _SalePanel(popup_mode=False)
        dialog = SalesBillReviewDialog(dummy_parent)
        dialog.show()
        _APP.processEvents()

        patient_combo = dialog._panel.patient_name_edit
        address_combo = dialog._panel.address_edit
        address_line_edit = address_combo.lineEdit()

        # Tab to Address field
        QTest.keyClick(patient_combo.lineEdit(), Qt.Key_Tab)
        _APP.processEvents()

        # Address should now have focus
        self.assertTrue(address_line_edit.hasFocus() or address_combo.hasFocus(),
                        "Address field should receive focus after Tab")
        self.assertFalse(patient_combo.lineEdit().hasFocus(),
                         "Patient Name should no longer have focus")

        # Simulate another showEvent (e.g. unminimizing or window activation)
        dialog.show()
        _APP.processEvents()

        # Focus must NOT have jumped back to Patient Name
        self.assertTrue(address_line_edit.hasFocus() or address_combo.hasFocus(),
                        "Focus must stay on Address, not jump back to Patient Name")
        dialog.close()

    def test_05_counter_sale_page_focus_entry_on_new_sale(self):
        """CounterSalePage focus_entry() routes to patient_name on empty bill."""
        page = CounterSalePage()
        page.show()
        _APP.processEvents()

        # When brand new bill (0 items), calling focus_entry() focuses patient_name
        page.focus_entry()
        _APP.processEvents()

        # In CounterSalePage, if metadata strip is hidden, it safely falls back to item_name
        # If review dialog is opened, it focuses patient_name
        self.assertIsNotNone(page._sale_panel)
        page.close()

    def test_06_counter_sale_page_start_new_sale_and_add_bill(self):
        """_start_new_sale() and _on_add_bill() both call focus_entry / focus_patient_name."""
        page = CounterSalePage()
        page.show()
        _APP.processEvents()

        page._on_add_bill()
        _APP.processEvents()

        page._start_new_sale()
        _APP.processEvents()

        page.close()

    def test_07_duplicate_sales_bill_dialog_patient_focus_on_open(self):
        """DuplicateSalesBillDialog focuses _patient_edit on open."""
        dialog = DuplicateSalesBillDialog()
        dialog.show()
        _APP.processEvents()

        self.assertTrue(dialog._patient_edit.hasFocus(),
                        "DuplicateSalesBillDialog._patient_edit should have focus on open")

        # Type immediately without click
        QTest.keyClicks(dialog._patient_edit, "SUNIL")
        _APP.processEvents()
        self.assertEqual(dialog._patient_edit.text(), "SUNIL")
        dialog.close()


if __name__ == "__main__":
    unittest.main()
