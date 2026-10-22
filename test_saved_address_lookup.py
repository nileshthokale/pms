"""Regression tests for automatic saved-address lookup in Counter Sale / Sales Bill dialog.

Tests cover:
  1. Patient with one previously saved address (auto-fill).
  2. Patient with multiple saved addresses (dropdown shown directly below Address).
  3. Patient with no saved address (blank, allow entry).
  4. WALKIN customer with a named patient (segregated by patient name, not shared).
  5. Different patients with similar names (no false-positive address selection).
  6. Changing the patient after an address was auto-filled (clears old, loads new).
  7. Manual address entry and address persistence after saving and reopening a bill.
  8. Case-insensitive matching and whitespace tolerance.
  9. Database safety: isolated temporary database, production data untouched.
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
_TMP_DIR = tempfile.mkdtemp(prefix="pms_addr_test_")
_TMP_DB = os.path.join(_TMP_DIR, "addr_test.db")
os.environ["PHARMACY_DB"] = _TMP_DB

from database.connection import get_connection, init_database
from database.customer_dao import CustomerDAO
from database.doctor_dao import DoctorDAO
from database.item_dao import ItemDAO
from database.unit_dao import UnitDAO
from database.company_dao import CompanyDAO
from database.supplier_dao import SupplierDAO
from database.purchase_dao import PurchaseDAO
from database.sales_dao import SalesDAO
from database import auth, financial_year
from database.account_roles import ensure_system_ledgers

try:
    from PySide6.QtWidgets import QApplication, QMessageBox
    from screens.counter_sale import _SalePanel, SalesBillReviewDialog
    HAS_PYSIDE6 = True
except ImportError:
    HAS_PYSIDE6 = False


@unittest.skipUnless(HAS_PYSIDE6, "PySide6 not available")
class TestSavedAddressLookup(unittest.TestCase):
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
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        os.environ["PHARMACY_DB"] = self._TMP_DB
        conn = get_connection()
        try:
            for tbl in (
                "ledger_transactions", "sales_invoice_items", "sales_invoices",
                "purchase_invoice_items", "purchase_invoices", "stock_batches",
                "items", "customers", "doctors", "suppliers", "units", "companies", "patient_addresses"
            ):
                try:
                    conn.execute(f"DELETE FROM {tbl}")
                except Exception:
                    pass
            conn.commit()
        finally:
            conn.close()

        ensure_system_ledgers()
        financial_year.ensure_default_financial_year()

        self.unit_id = UnitDAO.insert("Pcs")
        self.company_id = CompanyDAO.insert("TestCo", "TC")
        self.supplier_id = SupplierDAO.insert("TestSupplier")
        self.doctor_id = DoctorDAO.insert("Dr. Test")
        self.item_id = ItemDAO.insert(
            item_name="Paracetamol",
            unit_id=self.unit_id,
            company_id=self.company_id,
            pack_size="10x10",
            mrp=50.0,
        )

        # Seed stock
        PurchaseDAO.insert_invoice(
            voucher_no="PV-0001", voucher_date="2026-01-01", voucher_time="",
            purchase_type="Cash", supplier_id=self.supplier_id,
            invoice_no="INV-001", invoice_date="2026-01-01",
            invoice_net_amount=5000.0, bill_discount=0, due_date="",
            total_amount=5000.0, gst_amount=0, debit_note_amount=0,
            other_amount=0, paid_amount=5000.0, round_off=0,
            net_amount=5000.0, remarks="",
            items=[{
                "item_id": self.item_id, "pack_size": "10x10",
                "pay_qty": 1.0, "free_qty": 0, "batch_no": "BATCH-01",
                "expiry": "12/28", "rate": 40.0, "mrp": 50.0,
                "discount": 0, "gst_percent": 0, "gst_amount": 0,
                "amount": 4000.0, "purchase_rate": 40.0,
                "net_rate": 40.0, "pp": 40.0,
            }],
        )
        from database.stock_dao import StockDAO
        batches = StockDAO.get_stock_batches_for_item(self.item_id)
        self.batch_id = batches[0]["id"]

        # Ensure WALKIN customer exists
        self.walkin_id = CustomerDAO.get_or_create_walkin()

        # Mock out dialog boxes
        self._patches = [
            mock.patch.object(QMessageBox, "warning", return_value=QMessageBox.Ok),
            mock.patch.object(QMessageBox, "information", return_value=QMessageBox.Ok),
            mock.patch.object(QMessageBox, "critical", return_value=QMessageBox.Ok),
            mock.patch.object(QMessageBox, "question", return_value=QMessageBox.Yes),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)

    def _pump(self, n=5):
        for _ in range(n):
            self._app.processEvents()

    def _make_popup_panel(self) -> tuple[SalesBillReviewDialog, _SalePanel]:
        source = _SalePanel(popup_mode=False)
        self._pump()
        dlg = SalesBillReviewDialog(source)
        self._pump()
        return dlg, dlg._panel

    def test_01_single_saved_address_autopopulates(self):
        """1. When exactly one saved address exists, auto-populate the Address field."""
        # Seed customer with an address
        CustomerDAO.insert("MR NILESH THOKALE", address="123 MARKET ROAD, PUNE")

        dlg, panel = self._make_popup_panel()
        self.assertEqual(panel.address_edit.text(), "")

        # Enter patient name
        panel.patient_name_edit.setText("MR NILESH THOKALE")
        self._pump()

        # Address must be automatically populated
        self.assertEqual(panel.address_edit.text(), "123 MARKET ROAD, PUNE")

    def test_02_multiple_saved_addresses_displays_dropdown(self):
        """2. When multiple saved addresses exist, display dropdown below Address field."""
        # Patient has address from customer record and another from historical sale
        c1 = CustomerDAO.insert("PATIENT MULTI (HOME)", address="HOME ADDRESS, NAGAR")
        c2 = CustomerDAO.insert("PATIENT MULTI (WORK)", address="WORK ADDRESS, PUNE")

        # Record historical sales under both
        SalesDAO.insert_invoice(
            bill_no="CS-101", sale_date="2026-01-01", sale_time="",
            sale_type="Cash", customer_id=c1, patient_name="PATIENT MULTI",
            doctor_id=self.doctor_id, discount=0, paid_amount=50,
            total_amount=50, round_off=0, net_amount=50, remarks="",
            items=[],
        )
        SalesDAO.insert_invoice(
            bill_no="CS-102", sale_date="2026-01-02", sale_time="",
            sale_type="Cash", customer_id=c2, patient_name="PATIENT MULTI",
            doctor_id=self.doctor_id, discount=0, paid_amount=50,
            total_amount=50, round_off=0, net_amount=50, remarks="",
            items=[],
        )

        dlg, panel = self._make_popup_panel()
        panel.patient_name_edit.setText("PATIENT MULTI")
        self._pump()

        # Multiple addresses exist: field is left blank for user choice
        self.assertEqual(panel.address_edit.text(), "")
        # Suggestions must contain both addresses
        options = [panel.address_edit.itemText(i) for i in range(panel.address_edit.count())]
        self.assertIn("WORK ADDRESS, PUNE", options)
        self.assertIn("HOME ADDRESS, NAGAR", options)

    def test_03_no_saved_address_leaves_blank_allows_entry(self):
        """3. When no saved address exists, leave field blank and allow typing."""
        dlg, panel = self._make_popup_panel()
        panel.patient_name_edit.setText("NEW UNKNOWN PATIENT")
        self._pump()

        self.assertEqual(panel.address_edit.text(), "")

        # Allow user to type new address
        panel.address_edit.setText("789 BRAND NEW ROAD")
        self.assertEqual(panel.address_edit.text(), "789 BRAND NEW ROAD")

    def test_04_walkin_customer_with_named_patient(self):
        """4. WALKIN customers: uses patient name rather than treating every WALKIN sale as one."""
        # Patient A and Patient B both bought under WALKIN
        CustomerDAO.save_patient_address("PATIENT A", "ADDRESS A", customer_id=self.walkin_id)
        CustomerDAO.save_patient_address("PATIENT B", "ADDRESS B", customer_id=self.walkin_id)

        dlg, panel = self._make_popup_panel()
        # Customer is WALKIN
        panel.customer_combo.setCurrentIndex(panel.customer_combo.findData(self.walkin_id))
        self._pump()

        # Typing Patient A retrieves Address A
        panel.patient_name_edit.setText("PATIENT A")
        self._pump()
        self.assertEqual(panel.address_edit.text(), "ADDRESS A")

        # Typing Patient B retrieves Address B
        panel.patient_name_edit.setText("PATIENT B")
        self._pump()
        self.assertEqual(panel.address_edit.text(), "ADDRESS B")

    def test_05_different_patients_similar_names_no_false_matches(self):
        """5. Do not select address belonging to a different patient merely because names are similar."""
        CustomerDAO.insert("NILESH THOKALE", address="PUNE CITY")

        dlg, panel = self._make_popup_panel()
        # Typing a prefix or similar name like "NILESH" must NOT auto-fill Nilesh Thokale's address
        panel.patient_name_edit.setText("NILESH")
        self._pump()
        self.assertEqual(panel.address_edit.text(), "")

        panel.patient_name_edit.setText("NILESH PATIL")
        self._pump()
        self.assertEqual(panel.address_edit.text(), "")

        # Exact match does auto-fill
        panel.patient_name_edit.setText("NILESH THOKALE")
        self._pump()
        self.assertEqual(panel.address_edit.text(), "PUNE CITY")

    def test_06_changing_patient_clears_previous_autofill(self):
        """6. When patient name changes, clear previously auto-filled address."""
        CustomerDAO.insert("PATIENT ONE", address="ONE STREET")

        dlg, panel = self._make_popup_panel()
        panel.patient_name_edit.setText("PATIENT ONE")
        self._pump()
        self.assertEqual(panel.address_edit.text(), "ONE STREET")

        # Switch to patient with no saved address
        panel.patient_name_edit.setText("PATIENT TWO")
        self._pump()
        self.assertEqual(panel.address_edit.text(), "")

    def test_07_case_insensitive_and_whitespace_tolerance(self):
        """7. Case-insensitive and whitespace tolerant matching."""
        CustomerDAO.insert("DR. RAJESH KUMAR", address="HOSPITAL ROAD, MUMBAI")

        dlg, panel = self._make_popup_panel()
        # Messy whitespace and lower case
        panel.patient_name_edit.setText("   dr.   rajesh   kumar   ")
        self._pump()
        self.assertEqual(panel.address_edit.text(), "HOSPITAL ROAD, MUMBAI")

    def test_08_manual_entry_and_persistence_on_save_and_reopen(self):
        """8. Manually entered address is persisted and retrieved on future sales / bill reload."""
        dlg, panel = self._make_popup_panel()
        # Select WALKIN
        panel.customer_combo.setCurrentIndex(panel.customer_combo.findData(self.walkin_id))
        panel.patient_name_edit.setText("SAVAN DHANWADE")
        panel.address_edit.setText("RAHURI FACTORY, AHMEDNAGAR")

        # Add line item so commit succeeds
        from screens.counter_sale import _BillItemRow
        panel._item_rows.append(_BillItemRow(
            item_id=self.item_id, item_name="Paracetamol",
            stock_batch_id=self.batch_id, pack_size="10x10", location="",
            batch_no="BATCH-01", expiry="12/28", mrp=50.0,
            sale_qty=1.0, discount_amount=0.0, amount=50.0,
        ))
        panel._recalc_totals()

        # Commit sale
        panel._commit_sale()
        self.assertTrue(panel._saved)

        # 1) Future sale for the same patient retrieves the address
        dlg2, panel2 = self._make_popup_panel()
        panel2.patient_name_edit.setText("SAVAN DHANWADE")
        self._pump()
        self.assertEqual(panel2.address_edit.text(), "RAHURI FACTORY, AHMEDNAGAR")

        # 2) Reopening/loading the saved invoice displays the address
        all_inv = SalesDAO.get_all()
        self.assertTrue(len(all_inv) > 0)
        saved_inv = SalesDAO.get_by_id(all_inv[0]["id"])
        panel3 = _SalePanel(popup_mode=True)
        panel3.load_invoice(saved_inv)
        self._pump()
        self.assertEqual(panel3.address_edit.text(), "RAHURI FACTORY, AHMEDNAGAR")

    def test_09_production_database_safety(self):
        """9. Verify test ran strictly against isolated DB; production DB is untouched."""
        self.assertNotEqual(os.path.abspath(_TMP_DB), os.path.abspath("data/pharmacy.db"))
        self.assertTrue(os.path.exists(_TMP_DB))
        import sqlite3
        if os.path.exists("data/pharmacy.db"):
            pconn = sqlite3.connect("data/pharmacy.db")
            cnt = pconn.execute("SELECT count(*) FROM sales_invoices").fetchone()[0]
            pconn.close()
            self.assertEqual(cnt, 72175, "Production invoices count must remain 72,175 intact")

    def test_10_address_autocomplete_on_first_character_typing(self):
        """10. Feature B: Typing 1st character in Address triggers dropdown with suggestions."""
        # Seed saved addresses in customers and patient_addresses
        CustomerDAO.insert("MR BHAU NIMSE", address="RAHURI")
        CustomerDAO.insert("MR GORAKSHANTH NIMSE", address="RAHU")
        CustomerDAO.insert("MR DATTA BELHEKAR", address="PUNE")

        dlg, panel = self._make_popup_panel()
        # Set patient name that has no previous address (WALKIN customer)
        panel.patient_name_edit.setText("MR ABAJI JADHAV")
        self._pump()

        # Address is blank
        self.assertEqual(panel.address_edit.text(), "")

        # Type 'R' into Address field
        from PySide6.QtGui import QKeyEvent
        from PySide6.QtCore import QEvent, Qt
        event = QKeyEvent(QEvent.KeyPress, Qt.Key_R, Qt.NoModifier, "R")
        self._app.sendEvent(panel.address_edit.lineEdit(), event)
        self._pump()

        # Autocomplete dropdown must appear directly beneath the field
        self.assertTrue(panel.address_edit.completer().popup().isVisible())
        self.assertGreater(panel.address_edit.count(), 0)

        # Dropdown items must include matching addresses and associated patient names
        items = [panel.address_edit.itemText(i) for i in range(panel.address_edit.count())]
        self.assertTrue(any("RAHURI" in item for item in items))
        self.assertTrue(any("RAHU" in item for item in items))

    def test_11_address_keyboard_selection_and_clean_address_fill(self):
        """11. Feature B: Down arrow + Enter selects address and fills clean address into field."""
        CustomerDAO.insert("MR BHAU NIMSE", address="RAHURI")
        CustomerDAO.insert("MR DATTA BELHEKAR", address="PUNE")

        dlg, panel = self._make_popup_panel()
        panel.patient_name_edit.setText("MR ABAJI JADHAV")
        self._pump()

        from PySide6.QtGui import QKeyEvent
        from PySide6.QtCore import QEvent, Qt
        # Type 'R'
        event = QKeyEvent(QEvent.KeyPress, Qt.Key_R, Qt.NoModifier, "R")
        self._app.sendEvent(panel.address_edit.lineEdit(), event)
        self._pump()
        self.assertTrue(panel.address_edit.completer().popup().isVisible())

        # Press Down arrow to navigate popup
        event_down = QKeyEvent(QEvent.KeyPress, Qt.Key_Down, Qt.NoModifier)
        self._app.sendEvent(panel.address_edit.lineEdit(), event_down)
        self._pump()

        # Press Enter to confirm selection
        event_enter = QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier)
        self._app.sendEvent(panel.address_edit.lineEdit(), event_enter)
        self._pump()

        # Field must be filled with clean address (e.g. 'RAHURI'), not the combined display text
        self.assertEqual(panel.address_edit.text(), "RAHURI")
        # Popup must be closed cleanly
        self.assertFalse(panel.address_edit.completer().popup().isVisible())

    def test_12_address_mouse_selection_and_no_stray_popups(self):
        """12. Feature B: Mouse selection fills clean address and closes popup cleanly."""
        CustomerDAO.insert("MR BHAU NIMSE", address="RAHURI")
        CustomerDAO.insert("MR GORAKSHANTH NIMSE", address="RAHU")

        dlg, panel = self._make_popup_panel()
        panel.address_edit.setText("R")
        panel.address_edit.lineEdit().textEdited.emit("R")
        self._pump()

        self.assertTrue(panel.address_edit.completer().popup().isVisible())

        # Simulate clicking the second item
        popup = panel.address_edit.completer().popup()
        comp_model = panel.address_edit.completer().completionModel()
        if comp_model.rowCount() > 0:
            idx = comp_model.index(0, 0)
            panel.address_edit.completer().activated[str].emit(idx.data())
            self._pump()

        self.assertIn(panel.address_edit.text(), ("RAHURI", "RAHU"))
        self.assertFalse(popup.isVisible())

    def test_13_abaji_jadhav_scenario_end_to_end(self):
        """13. End-to-end user scenario:
        - Customer: WALKIN
        - Patient Name: MR ABAJI JADHAV
        - Address: User types 'R', selects RAHURI
        - Sale committed
        - Next sale for MR ABAJI JADHAV automatically retrieves RAHURI (Feature A)
        """
        CustomerDAO.insert("MR BHAU NIMSE", address="RAHURI")

        # 1. First sale
        dlg, panel = self._make_popup_panel()
        panel.customer_combo.setCurrentIndex(panel.customer_combo.findData(self.walkin_id))
        panel.patient_name_edit.setText("MR ABAJI JADHAV")
        self._pump()

        # User types 'R' into Address
        from PySide6.QtGui import QKeyEvent
        from PySide6.QtCore import QEvent, Qt
        event = QKeyEvent(QEvent.KeyPress, Qt.Key_R, Qt.NoModifier, "R")
        self._app.sendEvent(panel.address_edit.lineEdit(), event)
        self._pump()
        self.assertTrue(panel.address_edit.completer().popup().isVisible())

        # User confirms 'RAHURI'
        panel.address_edit.setText("RAHURI")
        panel.address_edit.completer().popup().hide()
        self._pump()

        # Add line item and commit
        from screens.counter_sale import _BillItemRow
        panel._item_rows.append(_BillItemRow(
            item_id=self.item_id, item_name="Paracetamol",
            stock_batch_id=self.batch_id, pack_size="10x10", location="",
            batch_no="BATCH-01", expiry="12/28", mrp=50.0,
            sale_qty=1.0, discount_amount=0.0, amount=50.0,
        ))
        panel._recalc_totals()
        panel._commit_sale()
        self.assertTrue(panel._saved)

        # 2. Subsequent sale: User enters 'MR ABAJI JADHAV', address 'RAHURI' is auto-filled!
        dlg2, panel2 = self._make_popup_panel()
        panel2.patient_name_edit.setText("MR ABAJI JADHAV")
        self._pump()

        self.assertEqual(panel2.address_edit.text(), "RAHURI")


if __name__ == "__main__":
    unittest.main(verbosity=2)
