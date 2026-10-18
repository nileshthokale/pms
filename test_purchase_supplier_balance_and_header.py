"""Comprehensive test suite for Purchase Invoice: Supplier Ledger Balance & Due Date UI Removal.

Verifies:
1. Removal of Due Date label and date-picker from dialog header UI (invisible in UI).
2. Header reorganization: Supplier combo spans cols 1-5, Bal label in col 6, supplier_bal_label in col 7 (112 px).
3. Retrieval and immediate display of supplier's real ledger balance via LedgerDAO.
4. Correct sign and formatting conventions (Credit=positive, Debit=negative, zero=0.00, comma thousands separator).
5. Accurate handling of suppliers with opening balance, transaction history, advance debit balances, and zero balances.
6. Error / warning display when balance cannot be retrieved (no silent 0.00).
7. Pure read-only behavior of supplier selection (no ledger transactions created on selection).
8. Full invoice creation, item addition, saving with internal due_date preservation, and ledger posting.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import date
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import Qt, QDate, QEvent
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QLabel

app = QApplication.instance() or QApplication(sys.argv)

from screens.purchase_invoice import (
    _InvoiceDialog,
    SearchableComboBox,
)
from database.connection import init_database, get_connection
from database.account_roles import ensure_system_ledgers
from database import auth, financial_year
from database.company_dao import CompanyDAO
from database.unit_dao import UnitDAO
from database.drug_dao import DrugDAO
from database.item_dao import ItemDAO
from database.supplier_dao import SupplierDAO
from database.supplier_payment_dao import SupplierPaymentDAO
from database.ledger_dao import LedgerDAO
from database.purchase_dao import PurchaseDAO


class TestPurchaseSupplierBalanceAndHeader(unittest.TestCase):

    def setUp(self):
        self._orig_db = os.environ.get("PHARMACY_DB")
        self.db_path = os.path.join(tempfile.gettempdir(), f"test_purchase_header_{os.getpid()}_{id(self)}.db")
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except OSError:
                pass
        os.environ["PHARMACY_DB"] = self.db_path

        init_database()
        ensure_system_ledgers()
        auth.ensure_auth_schema()
        financial_year.ensure_default_financial_year()

        self.company_id = CompanyDAO.insert("Test Pharma Ltd", "TP")
        self.unit_id = UnitDAO.insert("Strips")
        self.drug_id = DrugDAO.insert("Paracetamol")

        # 1. Supplier Zero: 0 opening balance, no transactions
        self.sup_zero_id = SupplierDAO.insert("ALPHA DRUGS", opening_balance=0.0)

        # 2. Supplier With Opening: 1500.00 Credit opening balance, no transactions
        self.sup_ob_id = SupplierDAO.insert("BETA HEALTHCARE", opening_balance=1500.0)

        # 3. Supplier Active: 0 opening balance, will have purchase + payment
        self.sup_active_id = SupplierDAO.insert("GAMMA PHARMA", opening_balance=0.0)

        # 4. Supplier Advance: 0 opening balance, will have payment only (Debit balance)
        self.sup_advance_id = SupplierDAO.insert("DELTA MEDICINES", opening_balance=0.0)

        # Item for purchase testing
        self.item_id = ItemDAO.insert(
            item_name="PARACET 500",
            unit_id=self.unit_id,
            company_id=self.company_id,
            pack_size="10",
            tax_structure="GST5",
            rate=50.0,
            mrp=80.0,
        )

    def tearDown(self):
        if getattr(self, "_orig_db", None) is not None:
            os.environ["PHARMACY_DB"] = self._orig_db
        else:
            os.environ.pop("PHARMACY_DB", None)
        if hasattr(self, "db_path") and os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except OSError:
                pass

    def test_01_due_date_control_removed_from_ui(self):
        """Due Date label and date-picker are completely removed from header UI."""
        dlg = _InvoiceDialog()
        dlg.resize(1200, 720)
        dlg.show()
        app.processEvents()

        # 1. Internal due_date widget exists for persistence, but is hidden / not visible in UI
        self.assertFalse(dlg.due_date.isVisible())
        self.assertEqual(dlg.due_date.parent(), dlg)

        # 2. Confirm no QLabel in the header group has text "Due Date"
        header_labels = [c.text() for c in dlg.findChildren(QLabel)]
        self.assertNotIn("Due Date", header_labels)

        # 3. Confirm all required fields remain present and visible
        self.assertTrue(dlg.voucher_no_edit.isVisible())
        self.assertTrue(dlg.voucher_date.isVisible())
        self.assertTrue(dlg.voucher_time_edit.isVisible())
        self.assertTrue(dlg.purchase_type_combo.isVisible())
        self.assertTrue(dlg.invoice_no_edit.isVisible())
        self.assertTrue(dlg.invoice_date.isVisible())
        self.assertTrue(dlg.supplier_combo.isVisible())
        self.assertTrue(dlg.supplier_bal_label.isVisible())
        self.assertTrue(dlg.inv_net_amt_edit.isVisible())
        self.assertTrue(dlg.bill_discount_edit.isVisible())

        dlg.close()

    def test_02_header_grid_alignment_and_space_distribution(self):
        """Header grid stays aligned, compact, and uses space from Due Date for wider fields."""
        dlg = _InvoiceDialog()
        dlg.resize(1200, 720)
        dlg.show()
        app.processEvents()

        # Supplier combo spans cols 1-5 (~415 px space)
        self.assertGreaterEqual(dlg.supplier_combo.width(), 270)
        self.assertLessEqual(dlg.supplier_combo.width(), 500)

        # Bal label width is 112 px (aligned with purchase_type_combo in col 7)
        self.assertEqual(dlg.supplier_bal_label.width(), 112)
        self.assertEqual(dlg.purchase_type_combo.width(), 112)

        # Check alignment of Voucher No and Supplier *
        lbls = [w for w in dlg.findChildren(QLabel) if w.text() in ("Voucher No", "Supplier *", "Bal.", "Type")]
        sup_lbl = [w for w in lbls if w.text() == "Supplier *"][0]
        v_lbl = [w for w in lbls if w.text() == "Voucher No"][0]
        self.assertEqual(sup_lbl.width(), v_lbl.width())

        dlg.close()

    def test_03_supplier_with_zero_opening_and_zero_transactions(self):
        """Supplier with 0.00 opening balance and no transactions shows 0.00."""
        dlg = _InvoiceDialog()
        idx = dlg.supplier_combo.findData(self.sup_zero_id)
        self.assertGreaterEqual(idx, 0)

        dlg.supplier_combo.setCurrentIndex(idx)
        app.processEvents()

        self.assertEqual(dlg.supplier_bal_label.text(), "0.00")
        dlg.close()

    def test_04_supplier_with_opening_balance_and_no_transactions(self):
        """Supplier with opening balance shows the actual ledger opening balance, not 0.00."""
        dlg = _InvoiceDialog()
        idx = dlg.supplier_combo.findData(self.sup_ob_id)
        self.assertGreaterEqual(idx, 0)

        dlg.supplier_combo.setCurrentIndex(idx)
        app.processEvents()

        # 1500 Credit opening balance -> formatted as 1,500.00
        self.assertEqual(dlg.supplier_bal_label.text(), "1,500.00")
        self.assertIn("1,500.00", dlg.supplier_bal_label.toolTip())
        self.assertIn("Credit", dlg.supplier_bal_label.toolTip())
        dlg.close()

    def test_05_supplier_balance_updates_with_purchases_and_payments(self):
        """Supplier balance reflects purchases and payments from ledger postings."""
        # 1. Purchase of 5000.00 on credit from GAMMA PHARMA
        inv_id = PurchaseDAO.insert_invoice(
            voucher_no="2026-2027-Credit-0001",
            voucher_date="2026-10-15",
            voucher_time="10:00",
            purchase_type="Credit",
            supplier_id=self.sup_active_id,
            invoice_no="INV-101",
            invoice_date="2026-10-15",
            invoice_net_amount=5000.0,
            bill_discount=0.0,
            due_date="2026-11-15",
            total_amount=5000.0,
            gst_amount=0.0,
            debit_note_amount=0.0,
            other_amount=0.0,
            paid_amount=0.0,
            round_off=0.0,
            net_amount=5000.0,
            remarks="",
            items=[{
                "item_id": self.item_id,
                "pack_size": "10",
                "pay_qty": 100.0,
                "free_qty": 0.0,
                "batch_no": "B100",
                "expiry": "2028-10-31",
                "rate": 50.0,
                "mrp": 80.0,
                "discount": 0.0,
                "amount": 5000.0,
                "gst_percent": 0.0,
                "gst_amount": 0.0,
                "purchase_rate": 50.0,
                "net_rate": 50.0,
                "pp": 5000.0,
            }],
        )

        # 2. Payment of 1200.00 to GAMMA PHARMA
        SupplierPaymentDAO.insert_payment({
            "payment_date": "2026-10-16",
            "payment_time": "11:00",
            "supplier_id": self.sup_active_id,
            "payment_mode": "Cash",
            "amount": 1200.0,
            "reference_no": "PAY-01",
            "remarks": "Partial payment",
        })

        # Net outstanding: 5000 - 1200 = 3800.00 Credit
        dlg = _InvoiceDialog()
        idx = dlg.supplier_combo.findData(self.sup_active_id)
        dlg.supplier_combo.setCurrentIndex(idx)
        app.processEvents()

        self.assertEqual(dlg.supplier_bal_label.text(), "3,800.00")
        self.assertIn("3,800.00", dlg.supplier_bal_label.toolTip())
        self.assertIn("Credit", dlg.supplier_bal_label.toolTip())
        dlg.close()

    def test_06_supplier_with_debit_balance_shows_negative(self):
        """Supplier with Debit balance (advance payment) shows negative sign."""
        SupplierPaymentDAO.insert_payment({
            "payment_date": "2026-10-16",
            "payment_time": "12:00",
            "supplier_id": self.sup_advance_id,
            "payment_mode": "Cash",
            "amount": 750.0,
            "reference_no": "ADV-01",
            "remarks": "Advance deposit",
        })

        dlg = _InvoiceDialog()
        idx = dlg.supplier_combo.findData(self.sup_advance_id)
        dlg.supplier_combo.setCurrentIndex(idx)
        app.processEvents()

        self.assertEqual(dlg.supplier_bal_label.text(), "-750.00")
        self.assertIn("750.00", dlg.supplier_bal_label.toolTip())
        self.assertIn("Debit", dlg.supplier_bal_label.toolTip())
        dlg.close()

    def test_07_switching_suppliers_updates_balance_immediately(self):
        """Changing supplier selection updates the balance every time."""
        dlg = _InvoiceDialog()

        # 1. Select BETA (1500.00)
        idx_ob = dlg.supplier_combo.findData(self.sup_ob_id)
        dlg.supplier_combo.setCurrentIndex(idx_ob)
        app.processEvents()
        self.assertEqual(dlg.supplier_bal_label.text(), "1,500.00")

        # 2. Switch to ALPHA (0.00)
        idx_zero = dlg.supplier_combo.findData(self.sup_zero_id)
        dlg.supplier_combo.setCurrentIndex(idx_zero)
        app.processEvents()
        self.assertEqual(dlg.supplier_bal_label.text(), "0.00")

        # 3. Switch back to BETA (1500.00)
        dlg.supplier_combo.setCurrentIndex(idx_ob)
        app.processEvents()
        self.assertEqual(dlg.supplier_bal_label.text(), "1,500.00")

        dlg.close()

    def test_08_typing_autocomplete_and_clearing(self):
        """Searchable combo autocomplete resolves supplier by text and updates balance."""
        dlg = _InvoiceDialog()
        line = dlg.supplier_combo.lineEdit()
        self.assertIsNotNone(line)

        # 1. Type exact supplier name "BETA HEALTHCARE"
        line.setText("BETA HEALTHCARE")
        dlg.supplier_combo._resolve_current_text()
        app.processEvents()
        self.assertEqual(dlg.supplier_bal_label.text(), "1,500.00")

        # 2. Clear text -> balance resets to 0.00
        line.clear()
        app.processEvents()
        self.assertEqual(dlg.supplier_bal_label.text(), "0.00")

        dlg.close()

    def test_09_unlinked_supplier_shows_warning_state(self):
        """If a supplier lacks a linked ledger, displays error/warning, never silent 0.00."""
        # Insert supplier directly into DB without linked ledger
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("INSERT INTO suppliers (supplier_name) VALUES ('ORPHAN SUPPLIER')")
            orphan_id = cur.lastrowid
            conn.commit()
        finally:
            conn.close()

        dlg = _InvoiceDialog()
        # Reload suppliers in dialog
        dlg._load_suppliers()
        idx = dlg.supplier_combo.findData(orphan_id)
        self.assertGreaterEqual(idx, 0)

        dlg.supplier_combo.setCurrentIndex(idx)
        app.processEvents()

        # Must NOT silently show 0.00
        self.assertIn(dlg.supplier_bal_label.text(), ("N/A", "Error"))
        self.assertIn("ledger", dlg.supplier_bal_label.toolTip().lower())
        dlg.close()

    def test_10_supplier_selection_is_pure_read_only(self):
        """Selecting suppliers does not insert or alter any ledger transactions."""
        conn = get_connection()
        try:
            initial_count = conn.execute("SELECT COUNT(*) FROM ledger_transactions").fetchone()[0]
        finally:
            conn.close()

        dlg = _InvoiceDialog()
        for sid in (self.sup_zero_id, self.sup_ob_id, self.sup_active_id):
            idx = dlg.supplier_combo.findData(sid)
            dlg.supplier_combo.setCurrentIndex(idx)
            app.processEvents()

        dlg.close()

        conn = get_connection()
        try:
            final_count = conn.execute("SELECT COUNT(*) FROM ledger_transactions").fetchone()[0]
        finally:
            conn.close()

        self.assertEqual(initial_count, final_count)

    def test_11_save_invoice_preserves_internal_due_date_and_posts_ledger(self):
        """Saving an invoice preserves internal due date and posts correctly to ledger."""
        dlg = _InvoiceDialog()
        idx = dlg.supplier_combo.findData(self.sup_zero_id)
        dlg.supplier_combo.setCurrentIndex(idx)

        # Set invoice number
        dlg.invoice_no_edit.setText("INV-NEW-99")

        # Fill entry bar
        item_idx = dlg._entry_bar.item_combo.findData(self.item_id)
        dlg._entry_bar.item_combo.setCurrentIndex(item_idx)
        dlg._entry_bar.pay_qty_edit.setText("10")
        dlg._entry_bar.free_qty_edit.setText("0")
        dlg._entry_bar.rate_edit.setText("50.00")
        dlg._entry_bar.mrp_edit.setText("80.00")
        dlg._entry_bar.batch_edit.setText("BAT-99")
        dlg._entry_bar.expiry_edit.setText("10/29")
        dlg._entry_bar.gst_edit.setText("5.00")

        dlg._on_add_item()
        self.assertEqual(len(dlg._item_rows), 1)

        # Save invoice
        dlg._on_save()
        self.assertTrue(dlg.was_saved)

        # Verify database record has due_date preserved
        invs = PurchaseDAO.get_all_filtered(supplier_id=self.sup_zero_id)
        self.assertEqual(len(invs), 1)
        inv = invs[0]
        self.assertTrue(inv["due_date"])  # due_date is saved!

        # Verify supplier's ledger was credited
        lid = SupplierDAO.get_ledger_id(self.sup_zero_id)
        bal = LedgerDAO.get_balance(lid)
        self.assertAlmostEqual(bal["closing_balance"], inv["net_amount"], places=2)
        self.assertEqual(bal["closing_balance_type"], "Credit")

        # Opening a new dialog and selecting that supplier now shows the updated balance
        dlg2 = _InvoiceDialog()
        idx2 = dlg2.supplier_combo.findData(self.sup_zero_id)
        dlg2.supplier_combo.setCurrentIndex(idx2)
        app.processEvents()

        self.assertEqual(dlg2.supplier_bal_label.text(), f"{inv['net_amount']:,.2f}")
        dlg2.close()

    def test_12_existing_invoice_edit_dialog_populates_balance(self):
        """Editing an existing invoice shows supplier's current ledger balance and hides due date."""
        invs = PurchaseDAO.get_all_filtered(supplier_id=self.sup_zero_id)
        if not invs:
            # Create a quick invoice
            PurchaseDAO.insert_invoice(
                voucher_no="2026-2027-Credit-0002",
                voucher_date="2026-10-15",
                voucher_time="10:00",
                purchase_type="Credit",
                supplier_id=self.sup_ob_id,
                invoice_no="INV-202",
                invoice_date="2026-10-15",
                invoice_net_amount=100.0,
                bill_discount=0.0,
                due_date="2026-11-15",
                total_amount=100.0,
                gst_amount=0.0,
                debit_note_amount=0.0,
                other_amount=0.0,
                paid_amount=0.0,
                round_off=0.0,
                net_amount=100.0,
                remarks="",
                items=[],
            )
            invs = PurchaseDAO.get_all_filtered(supplier_id=self.sup_ob_id)

        inv = invs[0]
        dlg = _InvoiceDialog(invoice=inv)
        dlg.resize(1200, 720)
        dlg.show()
        app.processEvents()

        self.assertFalse(dlg.due_date.isVisible())
        self.assertNotEqual(dlg.supplier_bal_label.text(), "")
        self.assertNotEqual(dlg.supplier_bal_label.text(), "Error")

        dlg.close()

    def test_13_tab_key_accepts_autocomplete_and_updates_balance(self):
        """Pressing Tab on active/highlighted suggestion accepts supplier and updates Bal."""
        dlg = _InvoiceDialog()
        line = dlg.supplier_combo.lineEdit()
        self.assertIsNotNone(line)

        # Type prefix 'BET' and show popup
        line.setFocus()
        line.setText("BET")
        dlg.supplier_combo.showPopup()
        self.assertTrue(dlg.supplier_combo._completer.popup().isVisible())

        # Down arrow to highlight suggestion
        event_down = QKeyEvent(QEvent.KeyPress, Qt.Key_Down, Qt.NoModifier)
        dlg.supplier_combo.eventFilter(line, event_down)

        # Press Tab
        event_tab = QKeyEvent(QEvent.KeyPress, Qt.Key_Tab, Qt.NoModifier)
        dlg.supplier_combo.eventFilter(line, event_tab)
        app.processEvents()

        # Supplier is accepted, currentData resolved to sup_ob_id, and Bal updated
        self.assertEqual(dlg.supplier_combo.currentText(), "BETA HEALTHCARE")
        self.assertEqual(dlg.supplier_combo.currentData(), self.sup_ob_id)
        self.assertEqual(dlg.supplier_bal_label.text(), "1,500.00")
        dlg.close()

    def test_14_unique_prefix_typing_resolves_and_updates_due_date(self):
        """Typing an unambiguous prefix and unfocusing resolves supplier, balance, and credit period."""
        # Update BETA supplier with credit period 45 days
        conn = get_connection()
        try:
            conn.execute("UPDATE suppliers SET credit_period = 45 WHERE id = ?", (self.sup_ob_id,))
            conn.commit()
        finally:
            conn.close()

        dlg = _InvoiceDialog()
        line = dlg.supplier_combo.lineEdit()
        self.assertIsNotNone(line)

        line.setText("BETA")
        dlg.supplier_combo._resolve_current_text()
        app.processEvents()

        self.assertEqual(dlg.supplier_combo.currentText(), "BETA HEALTHCARE")
        self.assertEqual(dlg.supplier_combo.currentData(), self.sup_ob_id)
        self.assertEqual(dlg.supplier_bal_label.text(), "1,500.00")

        # Due date updated to invoice_date + 45 days
        expected_due = dlg.invoice_date.date().addDays(45)
        self.assertEqual(dlg.due_date.date(), expected_due)
        dlg.close()


if __name__ == "__main__":
    unittest.main()

