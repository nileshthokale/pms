"""Tests for Counter Sale:
1. Mandatory medicine name validation (empty / unselected / typed invalid blocked at item entry and final save).
2. Schedule H1 and NRX medicines display in red.
3. Ordinary medicines display in black.
4. Billing calculations, stock validation, and normal saving continue to work.
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
from PySide6.QtGui import QColor, QPalette
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
    _SalePanel,
    _BillItemRow,
    is_schedule_h1,
    is_schedule_nrx,
    is_schedule_h1_or_nrx,
)


class TestCounterSaleMedicineValidationAndClassification(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fd, cls._db_path = tempfile.mkstemp(prefix="pharmacy_cs_med_", suffix=".db")
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

        self.company_id = CompanyDAO.insert("Test Pharma", "TP")
        self.unit_id = UnitDAO.insert("Strip")
        self.supplier_id = SupplierDAO.insert("Test Supplier")
        self.customer_id = CustomerDAO.get_or_create_walkin()

        # 1. Ordinary medicine (not H1, not NRX)
        self.ord_item_id = ItemDAO.insert(
            item_name="PARACETAMOL 500MG",
            unit_id=self.unit_id,
            company_id=self.company_id,
            pack_size="10",
            mrp=50.0,
            scheduled="",
        )

        # 2. Schedule H1 medicine
        self.h1_item_id = ItemDAO.insert(
            item_name="ALPRAZOLAM 0.5MG",
            unit_id=self.unit_id,
            company_id=self.company_id,
            pack_size="10",
            mrp=120.0,
            scheduled="H1",
        )

        # 3. Schedule H1 medicine with legacy code '2'
        self.h1_legacy_id = ItemDAO.insert(
            item_name="CEFIXIME 200MG",
            unit_id=self.unit_id,
            company_id=self.company_id,
            pack_size="10",
            mrp=180.0,
            scheduled="2",
        )

        # 4. NRX medicine
        self.nrx_item_id = ItemDAO.insert(
            item_name="CODEINE PHOSPHATE",
            unit_id=self.unit_id,
            company_id=self.company_id,
            pack_size="1",
            mrp=250.0,
            scheduled="NRX",
        )

        # 5. NRX medicine with legacy code '4'
        self.nrx_legacy_id = ItemDAO.insert(
            item_name="METHADONE TAB",
            unit_id=self.unit_id,
            company_id=self.company_id,
            pack_size="1",
            mrp=300.0,
            scheduled="4",
        )

        # Create stock for each medicine via purchase invoice
        PurchaseDAO.insert_invoice(
            voucher_no="PV-MED-1",
            voucher_date="2026-10-01",
            voucher_time="09:00",
            purchase_type="Cash",
            supplier_id=self.supplier_id,
            invoice_no="PINV-MED-1",
            invoice_date="2026-10-01",
            invoice_net_amount=10000.0,
            bill_discount=0.0,
            due_date="",
            total_amount=10000.0,
            gst_amount=0.0,
            debit_note_amount=0.0,
            other_amount=0.0,
            paid_amount=10000.0,
            round_off=0.0,
            net_amount=10000.0,
            remarks="",
            items=[
                {
                    "item_id": self.ord_item_id,
                    "pack_size": "10",
                    "pay_qty": 50.0,
                    "free_qty": 0.0,
                    "batch_no": "ORD-B1",
                    "expiry": "12/30",
                    "rate": 30.0,
                    "mrp": 50.0,
                    "discount": 0.0,
                    "gst_percent": 0.0,
                    "gst_amount": 0.0,
                    "amount": 1500.0,
                    "purchase_rate": 30.0,
                    "net_rate": 30.0,
                    "pp": 30.0,
                },
                {
                    "item_id": self.h1_item_id,
                    "pack_size": "10",
                    "pay_qty": 50.0,
                    "free_qty": 0.0,
                    "batch_no": "H1-B1",
                    "expiry": "12/30",
                    "rate": 70.0,
                    "mrp": 120.0,
                    "discount": 0.0,
                    "gst_percent": 0.0,
                    "gst_amount": 0.0,
                    "amount": 3500.0,
                    "purchase_rate": 70.0,
                    "net_rate": 70.0,
                    "pp": 70.0,
                },
                {
                    "item_id": self.nrx_item_id,
                    "pack_size": "1",
                    "pay_qty": 50.0,
                    "free_qty": 0.0,
                    "batch_no": "NRX-B1",
                    "expiry": "12/30",
                    "rate": 150.0,
                    "mrp": 250.0,
                    "discount": 0.0,
                    "gst_percent": 0.0,
                    "gst_amount": 0.0,
                    "amount": 7500.0,
                    "purchase_rate": 150.0,
                    "net_rate": 150.0,
                    "pp": 150.0,
                },
            ],
        )

        self.warning_calls = []

        def mock_warning(parent, title, message):
            self.warning_calls.append((title, message))
            return QMessageBox.Ok

        self._warning_patcher = mock.patch.object(QMessageBox, "warning", side_effect=mock_warning)
        self._warning_patcher.start()
        self.addCleanup(self._warning_patcher.stop)

    # ------------------------------------------------------------------
    # 1. Classification logic tests
    # ------------------------------------------------------------------

    def test_01_classification_helpers(self):
        """Verify H1 and NRX classification helpers against database values."""
        self.assertTrue(is_schedule_h1("H1"))
        self.assertTrue(is_schedule_h1("2"))
        self.assertTrue(is_schedule_h1("Schedule H1"))
        self.assertFalse(is_schedule_h1(""))
        self.assertFalse(is_schedule_h1("1"))
        self.assertFalse(is_schedule_h1("4"))

        self.assertTrue(is_schedule_nrx("NRX"))
        self.assertTrue(is_schedule_nrx("4"))
        self.assertTrue(is_schedule_nrx("Schedule NRX"))
        self.assertFalse(is_schedule_nrx(""))
        self.assertFalse(is_schedule_nrx("1"))
        self.assertFalse(is_schedule_nrx("2"))

        self.assertTrue(is_schedule_h1_or_nrx("H1"))
        self.assertTrue(is_schedule_h1_or_nrx("2"))
        self.assertTrue(is_schedule_h1_or_nrx("NRX"))
        self.assertTrue(is_schedule_h1_or_nrx("4"))
        self.assertFalse(is_schedule_h1_or_nrx(""))
        self.assertFalse(is_schedule_h1_or_nrx("1"))
        self.assertFalse(is_schedule_h1_or_nrx("3"))

    # ------------------------------------------------------------------
    # 2. Block adding empty/unselected medicine at Item Entry
    # ------------------------------------------------------------------

    def test_02_item_entry_blocks_blank_medicine(self):
        """Clicking + Add with no medicine selected blocks item entry and warns user."""
        panel = _SalePanel()
        _app.processEvents()

        # Item combo is at index 0 (-- Select --)
        panel._entry_bar.add_btn.click()
        _app.processEvents()

        self.assertEqual(len(panel._item_rows), 0)
        self.assertEqual(panel._table.rowCount(), 0)
        self.assertTrue(any("Please select a medicine name" in msg for _, msg in self.warning_calls))

        panel.deleteLater()
        _app.processEvents()

    def test_03_item_entry_blocks_typed_unregistered_medicine(self):
        """Typing an unknown/unregistered medicine without selecting blocks entry and warns user."""
        panel = _SalePanel()
        _app.processEvents()

        panel._entry_bar.item_combo.lineEdit().setText("UNKNOWN MEDICINE XYZ")
        panel._entry_bar.add_btn.click()
        _app.processEvents()

        self.assertEqual(len(panel._item_rows), 0)
        self.assertEqual(panel._table.rowCount(), 0)
        self.assertTrue(any("Please select a medicine name before saving." in msg for _, msg in self.warning_calls))

        panel.deleteLater()
        _app.processEvents()

    # ------------------------------------------------------------------
    # 3. Block final save without valid medicine
    # ------------------------------------------------------------------

    def test_04_save_action_blocks_when_no_medicine_added(self):
        """Clicking Save Sale with zero items blocks save and warns user."""
        panel = _SalePanel()
        _app.processEvents()

        panel._on_save()
        _app.processEvents()

        self.assertFalse(getattr(panel, "was_saved", False))
        self.assertTrue(any("Please select a medicine name before saving." in msg for _, msg in self.warning_calls))

        # Ensure no records in database
        conn = get_connection()
        try:
            count = conn.execute("SELECT COUNT(*) FROM sales_invoices").fetchone()[0]
            self.assertEqual(count, 0)
        finally:
            conn.close()

        panel.deleteLater()
        _app.processEvents()

    def test_05_save_action_blocks_when_typed_text_unselected(self):
        """Clicking Save Sale when an unregistered medicine was typed blocks save."""
        panel = _SalePanel()
        _app.processEvents()

        panel._entry_bar.item_combo.lineEdit().setText("SOME TYPED TEXT")
        panel._on_save()
        _app.processEvents()

        self.assertFalse(getattr(panel, "was_saved", False))
        self.assertTrue(any("Please select a medicine name before saving." in msg for _, msg in self.warning_calls))

        panel.deleteLater()
        _app.processEvents()

    def test_06_database_blocks_saving_empty_or_invalid_items(self):
        """SalesDAO.create_sale raises ValueError if items list is empty or invalid."""
        with self.assertRaises(ValueError) as ctx:
            SalesDAO.insert_invoice(
                bill_no="B-TEST-0",
                sale_date="2026-10-25",
                sale_time="10:00",
                sale_type="Cash",
                customer_id=self.customer_id,
                patient_name="Patient",
                doctor_id=None,
                discount=0.0,
                paid_amount=0.0,
                total_amount=0.0,
                round_off=0.0,
                net_amount=0.0,
                remarks="",
                items=[],  # Empty
            )
        self.assertIn("Please select a medicine name before saving.", str(ctx.exception))

        with self.assertRaises(ValueError) as ctx2:
            SalesDAO.insert_invoice(
                bill_no="B-TEST-1",
                sale_date="2026-10-25",
                sale_time="10:00",
                sale_type="Cash",
                customer_id=self.customer_id,
                patient_name="Patient",
                doctor_id=None,
                discount=0.0,
                paid_amount=0.0,
                total_amount=0.0,
                round_off=0.0,
                net_amount=0.0,
                remarks="",
                items=[{"item_id": 999999, "stock_batch_id": 1, "mrp": 10.0, "sale_qty": 1.0, "amount": 10.0}],
            )
        self.assertIn("Please select a medicine name before saving.", str(ctx2.exception))

    # ------------------------------------------------------------------
    # 4. Color presentation: Ordinary medicine is Black, H1/NRX are Red
    # ------------------------------------------------------------------

    def test_07_ordinary_medicine_is_black(self):
        """Ordinary medicine has black text in item-entry and in table rows."""
        panel = _SalePanel()
        _app.processEvents()

        # Select Paracetamol (ordinary)
        idx = panel._entry_bar.item_combo.findData(self.ord_item_id)
        self.assertGreaterEqual(idx, 0)
        panel._entry_bar.item_combo.setCurrentIndex(idx)
        _app.processEvents()

        # Check entry bar text color
        color = panel._entry_bar.item_name_color()
        self.assertEqual(color, QColor(Qt.black))
        line_edit_pal_color = panel._entry_bar.item_combo.lineEdit().palette().color(QPalette.Text)
        self.assertEqual(line_edit_pal_color, QColor(Qt.black))

        # Select batch and add to table
        b_idx = panel._entry_bar.batch_combo.count() - 1
        panel._entry_bar.batch_combo.setCurrentIndex(b_idx)
        panel._entry_bar.qty_edit.setText("2")
        panel._entry_bar.add_btn.click()
        _app.processEvents()

        self.assertEqual(panel._table.rowCount(), 1)
        name_cell = panel._table.item(0, 1)
        self.assertIsNotNone(name_cell)
        self.assertEqual(name_cell.text(), "PARACETAMOL 500MG")
        self.assertEqual(name_cell.foreground().color(), QColor(Qt.black))

        panel.deleteLater()
        _app.processEvents()

    def test_08_schedule_h1_medicine_is_red(self):
        """Schedule H1 medicine has red text in item-entry and in table rows."""
        panel = _SalePanel()
        _app.processEvents()

        # Select Alprazolam (H1)
        idx = panel._entry_bar.item_combo.findData(self.h1_item_id)
        self.assertGreaterEqual(idx, 0)
        panel._entry_bar.item_combo.setCurrentIndex(idx)
        _app.processEvents()

        # Check entry bar text color is red
        color = panel._entry_bar.item_name_color()
        self.assertEqual(color, QColor(Qt.red))
        line_edit_pal_color = panel._entry_bar.item_combo.lineEdit().palette().color(QPalette.Text)
        self.assertEqual(line_edit_pal_color, QColor(Qt.red))
        self.assertIn("red", panel._entry_bar.item_combo.lineEdit().styleSheet().lower())

        # Select batch and add to table
        b_idx = panel._entry_bar.batch_combo.count() - 1
        panel._entry_bar.batch_combo.setCurrentIndex(b_idx)
        panel._entry_bar.qty_edit.setText("1")
        panel._entry_bar.add_btn.click()
        _app.processEvents()

        self.assertEqual(panel._table.rowCount(), 1)
        name_cell = panel._table.item(0, 1)
        self.assertIsNotNone(name_cell)
        self.assertEqual(name_cell.text(), "ALPRAZOLAM 0.5MG")
        self.assertEqual(name_cell.foreground().color(), QColor(Qt.red))

        panel.deleteLater()
        _app.processEvents()

    def test_09_schedule_nrx_medicine_is_red(self):
        """NRX medicine has red text in item-entry and in table rows."""
        panel = _SalePanel()
        _app.processEvents()

        # Select Codeine (NRX)
        idx = panel._entry_bar.item_combo.findData(self.nrx_item_id)
        self.assertGreaterEqual(idx, 0)
        panel._entry_bar.item_combo.setCurrentIndex(idx)
        _app.processEvents()

        # Check entry bar text color is red
        color = panel._entry_bar.item_name_color()
        self.assertEqual(color, QColor(Qt.red))
        line_edit_pal_color = panel._entry_bar.item_combo.lineEdit().palette().color(QPalette.Text)
        self.assertEqual(line_edit_pal_color, QColor(Qt.red))

        # Select batch and add to table
        b_idx = panel._entry_bar.batch_combo.count() - 1
        panel._entry_bar.batch_combo.setCurrentIndex(b_idx)
        panel._entry_bar.qty_edit.setText("1")
        panel._entry_bar.add_btn.click()
        _app.processEvents()

        self.assertEqual(panel._table.rowCount(), 1)
        name_cell = panel._table.item(0, 1)
        self.assertIsNotNone(name_cell)
        self.assertEqual(name_cell.text(), "CODEINE PHOSPHATE")
        self.assertEqual(name_cell.foreground().color(), QColor(Qt.red))

        panel.deleteLater()
        _app.processEvents()

    # ------------------------------------------------------------------
    # 5. Full valid sale workflow & calculation preservation
    # ------------------------------------------------------------------

    def test_10_valid_sale_workflow_and_calculations(self):
        """Valid sale with selected medicine calculates totals, passes validation and saves."""
        panel = _SalePanel()
        _app.processEvents()

        # Select Paracetamol
        idx = panel._entry_bar.item_combo.findData(self.ord_item_id)
        panel._entry_bar.item_combo.setCurrentIndex(idx)
        b_idx = panel._entry_bar.batch_combo.count() - 1
        panel._entry_bar.batch_combo.setCurrentIndex(b_idx)
        panel._entry_bar.qty_edit.setText("2")  # 2 units @ MRP 50 (pack 10) = 10.00
        panel._entry_bar.discount_edit.setText("1.00")
        panel._entry_bar.add_btn.click()
        _app.processEvents()

        self.assertEqual(len(panel._item_rows), 1)
        row = panel._item_rows[0]
        # 2 units * (50 MRP / 10 pack) - 1.00 disc = 9.00
        self.assertAlmostEqual(row.amount, 9.00)

        # Set customer, valid patient name and paid amount
        c_idx = panel.customer_combo.findData(self.customer_id)
        panel.customer_combo.setCurrentIndex(c_idx)
        panel.patient_name_edit.setText("John Doe")
        panel.paid_edit.setText("9.00")
        panel._recalc_totals()

        # Save directly through _commit_sale (bypassing review dialog for headless test)
        valid = panel._validate_for_commit()
        self.assertTrue(valid)
        panel._commit_sale()
        _app.processEvents()

        self.assertTrue(panel.was_saved)

        # Verify stock was deducted: originally 50, sold 2 -> 498 remaining
        batch_after = StockDAO.get_stock_batch_by_id(row.stock_batch_id)
        self.assertEqual(batch_after["stock_qty"], 498.0)

        # Verify database invoice
        conn = get_connection()
        try:
            inv = conn.execute("SELECT id, total_amount, net_amount, patient_name, bill_no FROM sales_invoices").fetchone()
            self.assertIsNotNone(inv)
            self.assertEqual(inv["patient_name"], "John Doe")
            self.assertTrue(bool(inv["bill_no"]))
            self.assertAlmostEqual(inv["net_amount"], 9.00)

            item_saved = conn.execute("SELECT item_id, batch_no, sale_qty, amount FROM sales_invoice_items").fetchone()
            self.assertEqual(item_saved["item_id"], self.ord_item_id)
            self.assertEqual(item_saved["sale_qty"], 2.0)
        finally:
            conn.close()

        panel.deleteLater()
        _app.processEvents()

    # ------------------------------------------------------------------
    # 6. Patient Name Validation & WALKIN blocking tests
    # ------------------------------------------------------------------

    def _setup_panel_with_item(self, item_id: int | None = None, in_popup: bool = True) -> _SalePanel:
        if item_id is None:
            item_id = self.h1_item_id
        panel = _SalePanel(popup_mode=in_popup)
        if in_popup:
            panel._in_review_popup = True
        _app.processEvents()
        idx = panel._entry_bar.item_combo.findData(item_id)
        panel._entry_bar.item_combo.setCurrentIndex(idx)
        b_idx = panel._entry_bar.batch_combo.count() - 1
        panel._entry_bar.batch_combo.setCurrentIndex(b_idx)
        panel._entry_bar.qty_edit.setText("1")
        panel._entry_bar.add_btn.click()
        _app.processEvents()
        c_idx = panel.customer_combo.findData(self.customer_id)
        panel.customer_combo.setCurrentIndex(c_idx)
        panel.paid_edit.setText("5.00")
        panel._recalc_totals()
        self.warning_calls.clear()
        return panel

    def test_11_save_blocked_when_patient_name_is_empty(self):
        """Saving is blocked when patient name is empty; warning is shown."""
        panel = self._setup_panel_with_item()

        # Empty patient name
        panel.patient_name_edit.setText("")
        valid = panel._validate_for_commit()
        self.assertFalse(valid)
        self.assertTrue(any("Patient name is required before saving." in msg for _, msg in self.warning_calls))

        # Attempt commit directly
        panel._commit_sale()
        self.assertFalse(getattr(panel, "was_saved", False))

        # DB has 0 invoices
        conn = get_connection()
        try:
            count = conn.execute("SELECT COUNT(*) FROM sales_invoices").fetchone()[0]
            self.assertEqual(count, 0)
        finally:
            conn.close()

        panel.deleteLater()
        _app.processEvents()

    def test_12_save_blocked_when_patient_name_is_whitespace(self):
        """Saving is blocked when patient name is whitespace; warning is shown."""
        panel = self._setup_panel_with_item()

        panel.patient_name_edit.setText("    \t   ")
        valid = panel._validate_for_commit()
        self.assertFalse(valid)
        self.assertTrue(any("Patient name is required before saving." in msg for _, msg in self.warning_calls))

        panel._commit_sale()
        self.assertFalse(getattr(panel, "was_saved", False))

        panel.deleteLater()
        _app.processEvents()

    def test_13_save_blocked_when_patient_name_is_walkin(self):
        """Saving is blocked when patient name is 'WALKIN'; warning is shown."""
        panel = self._setup_panel_with_item()

        panel.patient_name_edit.setText("WALKIN")
        valid = panel._validate_for_commit()
        self.assertFalse(valid)
        self.assertTrue(any("Patient name cannot be WALKIN. Name is required." in msg for _, msg in self.warning_calls))

        panel._commit_sale()
        self.assertFalse(getattr(panel, "was_saved", False))

        conn = get_connection()
        try:
            count = conn.execute("SELECT COUNT(*) FROM sales_invoices").fetchone()[0]
            self.assertEqual(count, 0)
        finally:
            conn.close()

        panel.deleteLater()
        _app.processEvents()

    def test_14_save_blocked_for_all_walkin_variations(self):
        """Saving is blocked for variations: walkin, WALK-IN, WALK IN, WALKIN CUSTOMER."""
        variations = ["walkin", "WALK-IN", "walk-in", "WALK IN", "walk in", "WALKIN CUSTOMER", "walk-in customer"]
        for v in variations:
            panel = self._setup_panel_with_item()
            panel.patient_name_edit.setText(v)
            valid = panel._validate_for_commit()
            self.assertFalse(valid, f"Expected validation failure for '{v}'")
            self.assertTrue(
                any("Patient name cannot be WALKIN. Name is required." in msg for _, msg in self.warning_calls),
                f"Expected WALKIN warning for '{v}'"
            )

            panel.deleteLater()
            _app.processEvents()

    def test_15_nrx_medicine_blocks_empty_or_walkin_and_saves_with_name(self):
        """NRX medicine blocks save when patient name is empty or WALKIN, and saves with name."""
        panel = self._setup_panel_with_item(item_id=self.nrx_item_id, in_popup=True)

        # 1. Empty name blocked
        panel.patient_name_edit.setText("")
        valid = panel._validate_for_commit()
        self.assertFalse(valid)
        self.assertTrue(any("Patient name is required before saving." in msg for _, msg in self.warning_calls))

        # 2. WALKIN blocked
        self.warning_calls.clear()
        panel.patient_name_edit.setText("WALKIN")
        valid = panel._validate_for_commit()
        self.assertFalse(valid)
        self.assertTrue(any("Patient name cannot be WALKIN. Name is required." in msg for _, msg in self.warning_calls))

        # 3. Valid name succeeds
        self.warning_calls.clear()
        panel.patient_name_edit.setText("Patient NRX")
        valid = panel._validate_for_commit()
        self.assertTrue(valid)
        panel._commit_sale()
        self.assertTrue(getattr(panel, "was_saved", False))

        panel.deleteLater()
        _app.processEvents()

    def test_16_main_screen_save_opens_review_dialog_to_write_name(self):
        """On main screen, Save Sale opens review dialog so user can write patient name."""
        panel = self._setup_panel_with_item(in_popup=False)
        self.assertFalse(panel._in_review_popup)

        # On main screen with empty patient name, clicking Save Sale must open review dialog
        panel._on_save()
        _app.processEvents()

        self.assertTrue(hasattr(panel, "_review_dialog") and panel._review_dialog is not None)
        dlg = panel._review_dialog
        self.assertFalse(dlg._panel.was_saved)

        # In review dialog, clicking Save without name is blocked
        dlg._panel.patient_name_edit.setText("")
        dlg._on_final_save()
        _app.processEvents()
        self.assertFalse(dlg._panel.was_saved)
        self.assertTrue(any("Patient name is required before saving." in msg for _, msg in self.warning_calls))

        # In review dialog, enter name and save succeeds
        self.warning_calls.clear()
        dlg._panel.patient_name_edit.setText("Valid Patient")
        dlg._on_final_save()
        _app.processEvents()
        self.assertTrue(dlg._panel.was_saved)

        dlg.close()
        panel.deleteLater()
        _app.processEvents()

    def test_17_ordinary_medicine_saves_without_patient_name(self):
        """When the bill only contains ordinary non-H1/non-NRX medicines, saving without name succeeds."""
        panel = self._setup_panel_with_item(item_id=self.ord_item_id, in_popup=True)
        panel.patient_name_edit.setText("")
        valid = panel._validate_for_commit()
        self.assertTrue(valid)
        panel._commit_sale()
        self.assertTrue(getattr(panel, "was_saved", False))

        conn = get_connection()
        try:
            inv = conn.execute("SELECT id, patient_name, bill_no FROM sales_invoices ORDER BY id DESC LIMIT 1").fetchone()
            self.assertIsNotNone(inv)
            self.assertEqual(inv["patient_name"], "WALKIN")
            self.assertEqual(inv["bill_no"], "")
        finally:
            conn.close()

        panel.deleteLater()
        _app.processEvents()


if __name__ == "__main__":
    unittest.main()
