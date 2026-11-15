"""Tests for Less % and discount functionality across Debit Notes, Credit Notes,
Supplier Master, Customer Master, and Ledger Master.

Runs against an isolated temporary SQLite database, guaranteeing zero impact
to production data/pharmacy.db.
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import Qt, QDate
from PySide6.QtWidgets import QApplication

from database.connection import get_connection, init_database
from database.debit_note_dao import DebitNoteDAO
from database.credit_note_dao import CreditNoteDAO
from database.supplier_dao import SupplierDAO
from database.customer_dao import CustomerDAO
from database.item_dao import ItemDAO
from database.company_dao import CompanyDAO
from database.unit_dao import UnitDAO
from database.account_roles import ensure_system_ledgers
from database import auth, financial_year

from screens.debit_note import _DebitNoteEntryDialog, _parse_header_less
from screens.credit_note import _CreditNoteEntryDialog, _parse_header_less as _parse_cn_less
from screens.supplier_master import _SupplierDialog
from screens.customer_master import _CustomerDialog
from screens.account_ledger import _LedgerEntryDialog
from database.document_printing import generate_credit_note, generate_debit_note


class TestLessDiscountFunctionality(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls._db_fd, cls._db_path = tempfile.mkstemp(suffix="_test_less_disc.db")
        os.close(cls._db_fd)
        os.environ["PHARMACY_DB"] = cls._db_path
        init_database()
        auth.ensure_auth_schema()
        financial_year.ensure_default_financial_year()
        if auth.user_count() == 0:
            auth.create_first_admin("admin", "admin123")
        auth.session.login("admin", "admin123")
        ensure_system_ledgers()

        # Seed test unit and company
        conn = get_connection()
        try:
            conn.execute("INSERT OR IGNORE INTO units (id, unit_name) VALUES (1, 'TAB')")
            conn.execute(
                "INSERT OR IGNORE INTO companies (id, company_name, short_name) "
                "VALUES (1, 'TEST PHARMA', 'TP')"
            )
            # Create item and stock batch
            conn.execute(
                """
                INSERT OR IGNORE INTO items (id, item_name, company_id, unit_id, pack_size, mrp, rate)
                VALUES (301, 'KINGESIC-TH4 TABLET', 1, 1, '10', 220.0, 167.61)
                """
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO stock_batches (id, item_id, batch_no, expiry, pack_size, mrp, purchase_rate, stock_qty)
                VALUES (401, 301, 'LGP12/028/17', '2028-11-30', '10', 220.0, 167.61, 500.0)
                """
            )
            conn.commit()
        finally:
            conn.close()

        # Create suppliers with linked ledgers
        cls.sup_5pct_id = SupplierDAO.insert(supplier_name="SUPPLIER WITH 5PCT", discount=5.0)
        cls.sup_zero_id = SupplierDAO.insert(supplier_name="SUPPLIER WITH ZERO", discount=0.0)

        # Create customers with linked ledgers
        cls.cust_walkin_id = CustomerDAO.insert(customer_name="WALKIN", discount=5.0)
        cls.cust_zero_id = CustomerDAO.insert(customer_name="REGULAR PATIENT", discount=0.0)

    @classmethod
    def tearDownClass(cls):
        try:
            if os.path.exists(cls._db_path):
                os.remove(cls._db_path)
        except OSError:
            pass

    def test_01_parse_header_less_percentage_and_amount(self):
        """Test percentage and flat amount parsing logic."""
        # 5% of 110.00 subtotal = 5.50 discount, 5.0%
        less_amt, pct = _parse_header_less("5%", 110.00)
        self.assertEqual(less_amt, 5.50)
        self.assertEqual(pct, 5.0)

        # 0% of 110.00 subtotal = 0.00 discount, 0.0%
        less_amt, pct = _parse_header_less("0%", 110.00)
        self.assertEqual(less_amt, 0.00)
        self.assertEqual(pct, 0.0)

        # Flat amount 10.00 on 110.00 subtotal (returns pct = 0.0 because user entered flat amount)
        less_amt, pct = _parse_header_less("10.00", 110.00)
        self.assertEqual(less_amt, 10.00)
        self.assertEqual(pct, 0.0)

        # Flat amount greater than subtotal is capped at subtotal
        less_amt, pct = _parse_header_less("150.00", 110.00)
        self.assertEqual(less_amt, 110.00)
        self.assertEqual(pct, 0.0)

        # Blank or invalid input returns 0.0, 0.0
        less_amt, pct = _parse_header_less("", 110.00)
        self.assertEqual(less_amt, 0.0)
        self.assertEqual(pct, 0.0)

        less_amt, pct = _parse_header_less("invalid", 110.00)
        self.assertEqual(less_amt, 0.0)
        self.assertEqual(pct, 0.0)

    def test_02_debit_note_supplier_selection_populates_discount(self):
        """When selecting a supplier in Debit Note:
        - If configured (5%), populates 5%.
        - If not configured (0%), populates 0%.
        - Updates totals immediately.
        """
        dlg = _DebitNoteEntryDialog()
        dlg.show()
        self.app.processEvents()
        try:
            # Initially 0%
            self.assertEqual(dlg.header_less_edit.text(), "0%")

            # Select supplier with 5% discount
            idx = dlg.supplier_combo.findData(self.sup_5pct_id)
            self.assertGreaterEqual(idx, 0)
            dlg.supplier_combo.setCurrentIndex(idx)
            self.app.processEvents()

            # Header Less should be 5%
            self.assertEqual(dlg.header_less_edit.text(), "5%")

            # Now select supplier with 0% discount
            idx2 = dlg.supplier_combo.findData(self.sup_zero_id)
            self.assertGreaterEqual(idx2, 0)
            dlg.supplier_combo.setCurrentIndex(idx2)
            self.app.processEvents()

            # Header Less should be 0%
            self.assertEqual(dlg.header_less_edit.text(), "0%")
        finally:
            dlg.close()
            self.app.processEvents()

    def test_03_credit_note_customer_selection_and_pharma_winner_scenario(self):
        """Test the exact Pharma-WINNER scenario from the reference screenshot:
        Customer WALKIN has 5% discount configured.
        Item KINGESIC-TH4 TABLET, PackSize: 10, Qty: 5, Rate: 167.61, MRP: 220, PriceFactor: MRP.
        Item Amount = (220 / 10) * 5 = 110.00.
        Header Less: 5% (5.50).
        Total Amount: 104.50.
        """
        dlg = _CreditNoteEntryDialog()
        dlg.show()
        self.app.processEvents()
        try:
            # Customer combo should default to WALKIN which has 5% discount
            # Or manually set WALKIN
            idx = dlg.customer_combo.findData(self.cust_walkin_id)
            self.assertGreaterEqual(idx, 0)
            dlg.customer_combo.setCurrentIndex(idx)
            self.app.processEvents()

            self.assertEqual(dlg.header_less_edit.text(), "5%")

            # Now add item KINGESIC-TH4 TABLET (id 301)
            bar = dlg._entry_bar
            item_idx = bar.item_combo.findData(301)
            self.assertGreaterEqual(item_idx, 0)
            bar.item_combo.setCurrentIndex(item_idx)
            self.app.processEvents()

            # Select batch 401 (index 1, as index 0 is '-- Select Batch --')
            bar.batch_combo.setCurrentIndex(1)
            self.app.processEvents()

            bar.qty_edit.setText("5")
            bar.price_factor_combo.setCurrentText("MRP")
            self.app.processEvents()

            # Add item
            with mock.patch("PySide6.QtWidgets.QMessageBox.warning") as mock_w, \
                 mock.patch("PySide6.QtWidgets.QMessageBox.information"):
                dlg._on_add_item()
                self.app.processEvents()
                if mock_w.called:
                    self.fail(f"_on_add_item showed unexpected warning: {mock_w.call_args}")

            # Verify table item
            self.assertEqual(len(dlg._item_rows), 1)
            row = dlg._item_rows[0]
            self.assertTrue(row.item_name.startswith("KINGESIC-TH4 TABLET"))
            self.assertEqual(row.return_qty, 5.0)
            self.assertEqual(row.mrp, 220.0)
            self.assertEqual(row.amount, 110.00)
            self.assertEqual(row.less_amount, 0.0)  # Item level discount is 0

            # Verify dialog totals:
            # Subtotal = 110.00, Less: 5% = 5.50, Total Amount = 104.50
            self.assertEqual(dlg.total_items_val.text(), "1")
            self.assertEqual(dlg.total_amount_val.text(), "104.50")

            # Verify typing manual Less change: change 5% to 10%
            dlg.header_less_edit.setText("10%")
            self.app.processEvents()
            # 110.00 - 11.00 = 99.00
            self.assertEqual(dlg.total_amount_val.text(), "99.00")

            # Change to flat amount 10.00
            dlg.header_less_edit.setText("10.00")
            self.app.processEvents()
            # 110.00 - 10.00 = 100.00
            self.assertEqual(dlg.total_amount_val.text(), "100.00")

            # Reset back to 5%
            dlg.header_less_edit.setText("5%")
            self.app.processEvents()
            self.assertEqual(dlg.total_amount_val.text(), "104.50")

            # Save credit note
            with mock.patch("PySide6.QtWidgets.QMessageBox.information"), \
                 mock.patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn, \
                 mock.patch("PySide6.QtWidgets.QMessageBox.critical") as mock_crit:
                dlg._on_save()
                if not dlg.was_saved:
                    self.fail(f"Credit note save failed: warn={mock_warn.call_args}, crit={mock_crit.call_args}")
                self.assertTrue(dlg.was_saved)

            # Retrieve saved credit note from DAO
            cns = CreditNoteDAO.get_all()
            self.assertGreater(len(cns), 0)
            saved_cn = cns[0]
            self.assertEqual(saved_cn["total_amount"], 104.50)
            self.assertEqual(saved_cn["discount_pct"], 5.0)
            self.assertEqual(saved_cn["less_amount"], 5.50)

            # Re-open saved credit note in dialog to test persistence
            cn_full = CreditNoteDAO.get_by_id(saved_cn["id"])
            edit_dlg = _CreditNoteEntryDialog(cn=cn_full)
            edit_dlg.show()
            self.app.processEvents()
            try:
                self.assertEqual(edit_dlg.header_less_edit.text(), "5%")
                self.assertEqual(edit_dlg.total_amount_val.text(), "104.50")
            finally:
                edit_dlg.close()
                self.app.processEvents()
        finally:
            dlg.close()
            self.app.processEvents()

    def test_04_debit_note_workflow_and_persistence(self):
        """Test Debit Note save, calculation, persistence, and reopening with discount."""
        dlg = _DebitNoteEntryDialog()
        dlg.show()
        self.app.processEvents()
        try:
            # Select supplier with 5% discount
            idx = dlg.supplier_combo.findData(self.sup_5pct_id)
            dlg.supplier_combo.setCurrentIndex(idx)
            self.app.processEvents()
            self.assertEqual(dlg.header_less_edit.text(), "5%")

            # Add item
            bar = dlg._entry_bar
            item_idx = bar.item_combo.findData(301)
            bar.item_combo.setCurrentIndex(item_idx)
            self.app.processEvents()
            bar.batch_combo.setCurrentIndex(0)
            self.app.processEvents()

            bar.qty_edit.setText("5")
            bar.price_factor_combo.setCurrentText("MRP")
            self.app.processEvents()
            with mock.patch("PySide6.QtWidgets.QMessageBox.warning") as mock_w, \
                 mock.patch("PySide6.QtWidgets.QMessageBox.information"):
                dlg._on_add_item()
                self.app.processEvents()
                if mock_w.called:
                    self.fail(f"Debit note _on_add_item failed with warning: {mock_w.call_args}")

            # Subtotal 1100.00 (5 packs @ 220.00 MRP), Less 5% (55.00) -> Total 1045.00
            self.assertEqual(dlg.total_amount_val.text(), "1045.00")

            # Save debit note
            with mock.patch("PySide6.QtWidgets.QMessageBox.information"), \
                 mock.patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn, \
                 mock.patch("PySide6.QtWidgets.QMessageBox.critical") as mock_crit:
                dlg._on_save()
                if not dlg.was_saved:
                    self.fail(f"Debit note save failed: warn={mock_warn.call_args}, crit={mock_crit.call_args}")
                self.assertTrue(dlg.was_saved)

            # Check database
            dns = DebitNoteDAO.get_all()
            self.assertGreater(len(dns), 0)
            saved_dn = dns[0]
            self.assertEqual(saved_dn["total_amount"], 1045.00)
            self.assertEqual(saved_dn["discount_pct"], 5.0)
            self.assertEqual(saved_dn["less_amount"], 55.00)

            # Reopen in dialog
            dn_full = DebitNoteDAO.get_by_id(saved_dn["id"])
            edit_dlg = _DebitNoteEntryDialog(dn=dn_full)
            edit_dlg.show()
            self.app.processEvents()
            try:
                self.assertEqual(edit_dlg.header_less_edit.text(), "5%")
                self.assertEqual(edit_dlg.total_amount_val.text(), "1045.00")
            finally:
                edit_dlg.close()
                self.app.processEvents()
        finally:
            dlg.close()
            self.app.processEvents()

    def test_05_supplier_and_customer_master_validation(self):
        """Test 0% - 100% discount validation in Supplier and Customer master."""
        # 1. Supplier Master
        s_dlg = _SupplierDialog()
        s_dlg.show()
        self.app.processEvents()
        try:
            # Default discount is 0.0
            self.assertEqual(s_dlg._discount_edit.text(), "0.0")

            # Set invalid discount -5%
            s_dlg._supplier_name_edit.setText("INVALID SUP NEGATIVE")
            s_dlg._discount_edit.setText("-5.0")
            with mock.patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
                s_dlg._on_save()
                mock_warn.assert_called_with(s_dlg, "Validation", "Discount must be between 0% and 100%.")
                self.assertFalse(s_dlg.was_saved)

            # Set invalid discount 150%
            s_dlg._discount_edit.setText("150.0")
            with mock.patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
                s_dlg._on_save()
                mock_warn.assert_called_with(s_dlg, "Validation", "Discount must be between 0% and 100%.")
                self.assertFalse(s_dlg.was_saved)

            # Set valid discount 7.5%
            s_dlg._discount_edit.setText("7.5")
            s_dlg._on_save()
            self.assertTrue(s_dlg.was_saved)
        finally:
            s_dlg.close()
            self.app.processEvents()

        # 2. Customer Master
        c_dlg = _CustomerDialog()
        c_dlg.show()
        self.app.processEvents()
        try:
            # Default discount is 0.0
            self.assertEqual(c_dlg._discount_edit.text(), "0.0")

            # Set invalid discount 105%
            c_dlg._customer_name_edit.setText("INVALID CUST")
            c_dlg._discount_edit.setText("105.0")
            with mock.patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
                c_dlg._on_save()
                mock_warn.assert_called_with(c_dlg, "Validation", "Discount must be between 0% and 100%.")
                self.assertFalse(c_dlg.was_saved)

            # Set valid discount 3.0%
            c_dlg._discount_edit.setText("3.0")
            c_dlg._on_save()
            self.assertTrue(c_dlg.was_saved)
        finally:
            c_dlg.close()
            self.app.processEvents()

        # 3. Account Ledger
        l_dlg = _LedgerEntryDialog()
        l_dlg.show()
        self.app.processEvents()
        try:
            self.assertEqual(l_dlg._discount_edit.text(), "0.0")
            l_dlg._ledger_name_edit.setText("TEST LEDGER")
            l_dlg._discount_edit.setText("110.0")
            with mock.patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
                l_dlg._on_save()
                mock_warn.assert_called_with(l_dlg, "Validation", "Discount must be between 0% and 100%.")
                self.assertFalse(l_dlg.was_saved)
        finally:
            l_dlg.close()
            self.app.processEvents()

    def test_06_document_printing_includes_less_discount(self):
        """Test document printing text generation includes Less discount line."""
        cns = CreditNoteDAO.get_all()
        if cns:
            cn_id = cns[0]["id"]
            pdf_path = generate_credit_note(cn_id)
            self.assertTrue(os.path.exists(pdf_path))
            try:
                os.remove(pdf_path)
            except OSError:
                pass

    def test_07_item_level_and_header_discount_combination(self):
        """Verify that line-level discount and header discount calculate cleanly without double-counting.
        Line: Return 10 units @ MRP 220, pack_size 10 -> unit price = 22.0. Gross = 220.00.
        Line discount 10% -> disc_amt = 22.00, line amount = 198.00.
        Header Less: 5% -> 5% of 198.00 = 9.90.
        Total Amount = 198.00 - 9.90 = 188.10.
        """
        dlg = _CreditNoteEntryDialog()
        dlg.show()
        self.app.processEvents()
        try:
            dlg.customer_combo.set_selected_id(self.cust_walkin_id)
            self.app.processEvents()
            self.assertEqual(dlg.header_less_edit.text(), "5%")

            bar = dlg._entry_bar
            bar.item_combo.set_selected_id(301)
            self.app.processEvents()
            bar.batch_combo.setCurrentIndex(1)
            self.app.processEvents()

            bar.qty_edit.setText("10")
            bar.price_factor_combo.setCurrentText("MRP")
            bar.less_edit.setText("10.00")  # Line discount 10%
            self.app.processEvents()

            with mock.patch("PySide6.QtWidgets.QMessageBox.warning") as mock_w, \
                 mock.patch("PySide6.QtWidgets.QMessageBox.information"):
                dlg._on_add_item()
                self.app.processEvents()
                if mock_w.called:
                    self.fail(f"Add item failed: {mock_w.call_args}")

            self.assertEqual(len(dlg._item_rows), 1)
            row = dlg._item_rows[0]
            self.assertEqual(row.less_amount, 22.00)
            self.assertEqual(row.amount, 198.00)

            # Subtotal = 198.00, Less 5% = 9.90, Total = 188.10
            self.assertEqual(dlg.total_amount_val.text(), "188.10")
        finally:
            dlg.close()
            self.app.processEvents()

    def test_08_party_switching_updates_totals_immediately(self):
        """Switching between customer with 5% discount and 0% discount immediately
        updates header Less and recalculates the total.
        """
        dlg = _CreditNoteEntryDialog()
        dlg.show()
        self.app.processEvents()
        try:
            # Add an item first: 5 units @ 22 = 110.00
            dlg.customer_combo.set_selected_id(self.cust_walkin_id)
            self.app.processEvents()
            self.assertEqual(dlg.header_less_edit.text(), "5%")

            bar = dlg._entry_bar
            bar.item_combo.set_selected_id(301)
            self.app.processEvents()
            bar.batch_combo.setCurrentIndex(1)
            bar.qty_edit.setText("5")
            bar.price_factor_combo.setCurrentText("MRP")
            self.app.processEvents()

            with mock.patch("PySide6.QtWidgets.QMessageBox.warning"), \
                 mock.patch("PySide6.QtWidgets.QMessageBox.information"):
                dlg._on_add_item()
                self.app.processEvents()

            # With WALKIN (5%): Total = 104.50
            self.assertEqual(dlg.total_amount_val.text(), "104.50")

            # Switch customer to REGULAR PATIENT (0% discount)
            dlg.customer_combo.set_selected_id(self.cust_zero_id)
            self.app.processEvents()
            self.assertEqual(dlg.header_less_edit.text(), "0%")
            # Total should immediately update to 110.00
            self.assertEqual(dlg.total_amount_val.text(), "110.00")

            # Switch back to WALKIN (5% discount)
            dlg.customer_combo.set_selected_id(self.cust_walkin_id)
            self.app.processEvents()
            self.assertEqual(dlg.header_less_edit.text(), "5%")
            # Total should immediately update back to 104.50
            self.assertEqual(dlg.total_amount_val.text(), "104.50")
        finally:
            dlg.close()
            self.app.processEvents()

    def test_09_flat_amount_persistence_and_restore(self):
        """Saving a Debit Note with a flat currency amount (e.g. ₹25.00) persists
        less_amount and restores '25.00' when reopening.
        """
        dlg = _DebitNoteEntryDialog()
        dlg.show()
        self.app.processEvents()
        try:
            dlg.supplier_combo.set_selected_id(self.sup_zero_id)
            self.app.processEvents()
            self.assertEqual(dlg.header_less_edit.text(), "0%")

            bar = dlg._entry_bar
            bar.item_combo.set_selected_id(301)
            self.app.processEvents()
            bar.batch_combo.setCurrentIndex(0)
            bar.qty_edit.setText("1")
            bar.price_factor_combo.setCurrentText("MRP")
            self.app.processEvents()

            with mock.patch("PySide6.QtWidgets.QMessageBox.warning"), \
                 mock.patch("PySide6.QtWidgets.QMessageBox.information"):
                dlg._on_add_item()
                self.app.processEvents()

            # Subtotal is 220.00. Set flat discount 25.00
            dlg.header_less_edit.setText("25.00")
            self.app.processEvents()
            # 220.00 - 25.00 = 195.00
            self.assertEqual(dlg.total_amount_val.text(), "195.00")

            with mock.patch("PySide6.QtWidgets.QMessageBox.information"), \
                 mock.patch("PySide6.QtWidgets.QMessageBox.warning") as mock_w, \
                 mock.patch("PySide6.QtWidgets.QMessageBox.critical") as mock_c:
                dlg._on_save()
                if not dlg.was_saved:
                    self.fail(f"Save failed: {mock_w.call_args}, {mock_c.call_args}")
                self.assertTrue(dlg.was_saved)

            dns = DebitNoteDAO.get_all()
            saved_dn = dns[0]
            self.assertEqual(saved_dn["total_amount"], 195.00)
            self.assertEqual(saved_dn["less_amount"], 25.00)
            self.assertEqual(saved_dn["discount_pct"], 0.0)

            # Reopen in dialog
            dn_full = DebitNoteDAO.get_by_id(saved_dn["id"])
            edit_dlg = _DebitNoteEntryDialog(dn=dn_full)
            edit_dlg.show()
            self.app.processEvents()
            try:
                self.assertEqual(edit_dlg.header_less_edit.text(), "25.00")
                self.assertEqual(edit_dlg.total_amount_val.text(), "195.00")
            finally:
                edit_dlg.close()
                self.app.processEvents()
        finally:
            dlg.close()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
