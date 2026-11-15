"""Unit tests verifying the fix for the black input-field background issue in PendingCreditNotesDialog."""

import os
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QMessageBox, QLineEdit

from database.connection import get_connection, init_database
from database.customer_dao import CustomerDAO
from database.doctor_dao import DoctorDAO
from database.company_dao import CompanyDAO
from database.unit_dao import UnitDAO
from database.item_dao import ItemDAO
from database.credit_note_dao import CreditNoteDAO
from database.account_roles import ensure_system_ledgers
from database import auth, financial_year
from ui.theme import palette
from screens.credit_note import PendingCreditNotesDialog, _CreditNoteEntryDialog


class TestPendingCreditNotesDialogStyling(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls._orig_db = os.environ.get("PHARMACY_DB")
        cls._db_fd, cls._db_path = tempfile.mkstemp(suffix="_test_cn_style.db")
        os.close(cls._db_fd)
        os.environ["PHARMACY_DB"] = cls._db_path
        init_database()
        auth.ensure_auth_schema()
        financial_year.ensure_default_financial_year()
        if auth.user_count() == 0:
            auth.create_first_admin("admin", "admin123")
        auth.session.login("admin", "admin123")
        ensure_system_ledgers()

        # Seed data
        cls.comp_id = CompanyDAO.insert("Test Pharma", "TP")
        cls.unit_id = UnitDAO.insert("Tab")
        cls.cust_id = CustomerDAO.insert("John Doe", address="101 Main St", city="Pune")
        cls.doc_id = DoctorDAO.insert("Dr. Test")
        cls.item_id = ItemDAO.insert(
            item_name="PARACETAMOL 500",
            unit_id=cls.unit_id,
            company_id=cls.comp_id,
            pack_size="10",
            mrp=50.0,
            rate=35.0,
        )

        # Stock batch
        conn = get_connection()
        try:
            cur1 = conn.execute(
                """INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size, purchase_rate, net_rate, mrp, stock_qty)
                   VALUES (?, 'B1', '2028-12-31', '10', 35.0, 35.0, 50.0, 100.0)""",
                (cls.item_id,),
            )
            cls.batch1_id = cur1.lastrowid
            conn.commit()
        finally:
            conn.close()

        # Create two credit notes for John Doe:
        # CN 1: Amount = 100.0, Unsettled = 100.0
        cn1_hdr = {
            "voucher_no": "CN-TEST-001",
            "voucher_date": "2026-11-15",
            "voucher_time": "10:00 AM",
            "cn_date": "2026-11-15",
            "cn_type": "Customer",
            "customer_id": cls.cust_id,
            "total_amount": 100.0,
            "ledger_amount": 0.0,
            "add_to_ledger": False,
            "remarks": "Sample return 1",
        }
        cn1_items = [{
            "item_id": cls.item_id,
            "stock_batch_id": cls.batch1_id,
            "batch_no": "B1",
            "expiry": "2028-12-31",
            "pack_size": "10",
            "rate": 35.0,
            "mrp": 50.0,
            "return_qty": 2.0,
            "less_amount": 0.0,
            "amount": 100.0,
            "return_reason": "Sales Return",
            "price_factor": "MRP",
            "price_factor_num": 1.0,
        }]
        cls.cn1_id = CreditNoteDAO.insert_credit_note(cn1_hdr, cn1_items)

        # CN 2: Amount = 60.0, Unsettled = 60.0
        cn2_hdr = {
            "voucher_no": "CN-TEST-002",
            "voucher_date": "2026-11-15",
            "voucher_time": "11:00 AM",
            "cn_date": "2026-11-15",
            "cn_type": "Customer",
            "customer_id": cls.cust_id,
            "total_amount": 60.0,
            "ledger_amount": 0.0,
            "add_to_ledger": False,
            "remarks": "Sample return 2",
        }
        cn2_items = [{
            "item_id": cls.item_id,
            "stock_batch_id": cls.batch1_id,
            "batch_no": "B2",
            "expiry": "2028-12-31",
            "pack_size": "10",
            "rate": 30.0,
            "mrp": 50.0,
            "return_qty": 2.0,
            "less_amount": 0.0,
            "amount": 60.0,
            "return_reason": "Sales Return",
            "price_factor": "RATE",
            "price_factor_num": 1.0,
        }]
        cls.cn2_id = CreditNoteDAO.insert_credit_note(cn2_hdr, cn2_items)

    @classmethod
    def tearDownClass(cls):
        try:
            os.remove(cls._db_path)
        except Exception:
            pass
        if cls._orig_db is not None:
            os.environ["PHARMACY_DB"] = cls._orig_db
        else:
            os.environ.pop("PHARMACY_DB", None)

    def setUp(self):
        self._msg = mock.patch.multiple(
            QMessageBox, warning=mock.DEFAULT, information=mock.DEFAULT,
            critical=mock.DEFAULT, question=mock.DEFAULT,
        )
        self._msg.start()
        self.addCleanup(self._msg.stop)

    def test_01_dialog_stylesheet_does_not_contain_black_background(self):
        """Verify PendingCreditNotesDialog stylesheet has no hardcoded black QLineEdit background."""
        dlg = PendingCreditNotesDialog(
            None,
            customer_id=self.cust_id,
            customer_name="John Doe",
            max_adjustment_needed=100.0,
        )
        style = dlg.styleSheet().lower()
        # Ensure black input background is gone
        self.assertNotIn("qlineedit { background-color: #000", style)
        self.assertNotIn("background-color: #000000", style)
        # Ensure background is light / theme matching
        p = palette()
        expected_bg = p.get("bg", "#ffffff").lower()
        self.assertIn(f"background-color: {expected_bg}", style)
        expected_text = p.get("text", "#000000").lower()
        self.assertIn(f"color: {expected_text}", style)

    def test_02_credit_and_disc_edits_have_light_background_and_dark_text(self):
        """Verify CreditAmt and DiscAmt fields have light background and dark readable text."""
        dlg = PendingCreditNotesDialog(
            None,
            customer_id=self.cust_id,
            customer_name="John Doe",
            max_adjustment_needed=100.0,
        )
        self.assertEqual(len(dlg._row_edits), 2)

        p = palette()
        expected_bg = p.get("bg", "#ffffff").lower()
        expected_text = p.get("text", "#000000").lower()

        for idx, row in enumerate(dlg._row_edits):
            credit_edit: QLineEdit = row["credit_edit"]
            disc_edit: QLineEdit = row["disc_edit"]

            # 1. Stylesheet checks
            for ed, name in [(credit_edit, f"credit_edit_{idx}"), (disc_edit, f"disc_edit_{idx}")]:
                st = ed.styleSheet().lower()
                self.assertNotIn("background-color: #000", st)
                self.assertIn(f"background-color: {expected_bg}", st)
                self.assertIn(f"color: {expected_text}", st)

                # 2. QPalette Base and Text colors
                pal = ed.palette()
                base_col = pal.color(QPalette.Base).name().lower()
                text_col = pal.color(QPalette.Text).name().lower()
                self.assertEqual(base_col, expected_bg)
                self.assertEqual(text_col, expected_text)

                # 3. Alignment is right-aligned for financial amounts
                self.assertEqual(ed.alignment() & Qt.AlignRight, Qt.AlignRight)

    def test_03_editing_and_focus_switching(self):
        """Verify numeric editing, tabbing/focus changes between fields."""
        dlg = PendingCreditNotesDialog(
            None,
            customer_id=self.cust_id,
            customer_name="John Doe",
            max_adjustment_needed=100.0,
        )
        r0 = dlg._row_edits[0]
        credit_edit: QLineEdit = r0["credit_edit"]
        disc_edit: QLineEdit = r0["disc_edit"]

        dlg.show()
        QApplication.processEvents()
        # Set focus to credit_edit and edit value
        credit_edit.setFocus()
        credit_edit.setText("75.50")
        self.assertEqual(credit_edit.text(), "75.50")

        # Switch focus to disc_edit and edit value
        disc_edit.setFocus()
        disc_edit.setText("4.50")
        self.assertEqual(disc_edit.text(), "4.50")

        # Backgrounds remain intact after focus switches
        p = palette()
        expected_bg = p.get("bg", "#ffffff").lower()
        self.assertEqual(credit_edit.palette().color(QPalette.Base).name().lower(), expected_bg)
        self.assertEqual(disc_edit.palette().color(QPalette.Base).name().lower(), expected_bg)

    def test_04_calculations_and_saving_behavior_preserved(self):
        """Verify calculations, validation against over-credit, and settlements output."""
        dlg = PendingCreditNotesDialog(
            None,
            customer_id=self.cust_id,
            customer_name="John Doe",
            max_adjustment_needed=150.0,
        )
        r0 = dlg._row_edits[0]
        r1 = dlg._row_edits[1]

        # 1. Validation test: CreditAmt > Unsettled amount
        r0["credit_edit"].setText("150.00")  # unsettled is 100.0
        dlg._on_done()
        # Dialog should NOT have accepted settlements due to validation failure
        self.assertEqual(len(dlg.get_settlements()), 0)

        # 2. Validation test: Negative amount
        r0["credit_edit"].setText("-10.00")
        dlg._on_done()
        self.assertEqual(len(dlg.get_settlements()), 0)

        # 3. Valid settlement: Row 0 = 80.00, Row 1 = 30.00, Disc = 5.00
        r0["credit_edit"].setText("80.00")
        r0["disc_edit"].setText("0.00")
        r1["credit_edit"].setText("30.00")
        r1["disc_edit"].setText("5.00")

        dlg._on_done()
        self.assertEqual(dlg.result(), dlg.Accepted if hasattr(dlg, "Accepted") else 1)
        self.assertEqual(dlg.get_total_credit_applied(), 110.00)

        settlements = dlg.get_settlements()
        self.assertEqual(len(settlements), 2)
        self.assertEqual(settlements[0]["credit_note_id"], self.cn1_id)
        self.assertEqual(settlements[0]["credit_amount"], 80.00)
        self.assertEqual(settlements[0]["discount_amount"], 0.00)
        self.assertEqual(settlements[1]["credit_note_id"], self.cn2_id)
        self.assertEqual(settlements[1]["credit_amount"], 30.00)
        self.assertEqual(settlements[1]["discount_amount"], 5.00)

    def test_05_check_other_credit_note_dialog_inputs(self):
        """Verify _CreditNoteEntryDialog inputs do not have black background issue."""
        entry_dlg = _CreditNoteEntryDialog(None)
        st = entry_dlg.styleSheet().lower()
        self.assertNotIn("background-color: #000", st)
        self.assertNotIn("background-color: black", st)

        p = palette()
        expected_surface = p.get("surface", "#dce9f6").lower()
        self.assertIn(f"background-color: {expected_surface}", st)

        # Verify rate, mrp, qty, less edits exist and have readable fonts/styles
        bar = entry_dlg._entry_bar
        for ed in [bar.rate_edit, bar.mrp_edit, bar.qty_edit, bar.less_edit, entry_dlg.header_less_edit]:
            self.assertIsInstance(ed, QLineEdit)
            # Text is readable
            self.assertTrue(ed.isEnabled())


if __name__ == "__main__":
    unittest.main()
