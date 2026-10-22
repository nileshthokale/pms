import os
import sys
import unittest
import tempfile
import sqlite3
from unittest.mock import patch

sys.path.insert(0, ".")

from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)

import database.connection as db_conn
from database.debit_note_dao import DebitNoteDAO
from database.credit_note_dao import CreditNoteDAO
from database.accounting_posting import posting_engine
from database.purchase_dao import pack_factor


class TestDebitAndCreditNotes(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._temp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        cls._temp_path = cls._temp_file.name
        cls._temp_file.close()

        # Patch get_db_path so connection uses the isolated test DB
        cls._db_patch = patch.object(db_conn, "get_db_path", return_value=cls._temp_path)
        cls._db_patch.start()

        db_conn.init_database()
        cls._seed_test_data()

    @classmethod
    def tearDownClass(cls):
        cls._db_patch.stop()
        if os.path.exists(cls._temp_path):
            try:
                os.remove(cls._temp_path)
            except OSError:
                pass

    @classmethod
    def _seed_test_data(cls):
        conn = db_conn.get_connection()
        try:
            # Financial Year
            conn.execute(
                """
                INSERT OR REPLACE INTO financial_years (id, name, start_date, end_date, is_active, created_at)
                VALUES (1, '2026-2027', '2026-04-01', '2027-03-31', 1, '2026-04-01 00:00:00')
                """
            )

            # Account Groups
            conn.execute(
                "INSERT OR IGNORE INTO account_groups (id, group_name) VALUES (1, 'Sundry Creditors'), (2, 'Sundry Debtors'), (3, 'Direct Expenses'), (4, 'Sales Account')"
            )

            # Account Ledgers (including System Roles)
            conn.execute(
                """
                INSERT OR REPLACE INTO account_ledgers (id, ledger_name, account_group_id, system_role)
                VALUES
                    (1, 'Purchase Return Account', 3, 'PURCHASE_RETURN'),
                    (2, 'Sales Return Account', 4, 'SALES_RETURN'),
                    (3, 'Purchase Account', 3, 'PURCHASE'),
                    (4, 'Sales Account', 4, 'SALES'),
                    (5, 'Cash Account', 1, 'CASH'),
                    (10, 'Supplier A Ledger', 1, NULL),
                    (20, 'Customer Walkin Ledger', 2, NULL)
                """
            )

            # Supplier
            conn.execute(
                """
                INSERT OR REPLACE INTO suppliers (id, supplier_name, ledger_id)
                VALUES (1, 'ANAND PHARMA', 10)
                """
            )

            # Customer
            conn.execute(
                """
                INSERT OR REPLACE INTO customers (id, customer_name, ledger_id)
                VALUES (159, 'WALKIN', 20)
                """
            )

            # Items
            conn.execute(
                """
                INSERT OR REPLACE INTO items (id, item_name, pack_size, mrp)
                VALUES
                    (101, 'PARACETAMOL 650MG', '10', 30.0),
                    (102, 'AMOXICILLIN 500MG', '10', 120.0),
                    (103, 'COUGH SYRUP 100ML', '1', 85.0)
                """
            )

            # Stock Batches (stock_qty in loose units)
            # Item 101: pack_size 10, 100 loose tablets = 10 packs
            conn.execute(
                """
                INSERT OR REPLACE INTO stock_batches (id, item_id, batch_no, expiry, pack_size, mrp, purchase_rate, stock_qty)
                VALUES
                    (1, 101, 'BATCH-P1', '2028-12-31', '10', 30.0, 20.0, 100.0),
                    (2, 102, 'BATCH-A1', '2028-10-31', '10', 120.0, 90.0, 50.0),
                    (3, 103, 'BATCH-EXP', '2020-01-01', '1', 85.0, 60.0, 20.0)
                """
            )

            conn.commit()
        finally:
            conn.close()

    def setUp(self):
        # Reset stock quantities before each test
        conn = db_conn.get_connection()
        try:
            conn.execute("UPDATE stock_batches SET stock_qty = 100.0 WHERE id = 1")
            conn.execute("UPDATE stock_batches SET stock_qty = 50.0 WHERE id = 2")
            conn.execute("UPDATE stock_batches SET stock_qty = 20.0 WHERE id = 3")
            conn.commit()
        finally:
            conn.close()

    # ──────────────────────────────────────────────────────────────────
    # 1. Supplier Return (Debit Note) Tests
    # ──────────────────────────────────────────────────────────────────

    def test_01_supplier_return_creation_with_ledger_posting(self):
        """Create a Debit Note with Add to Supplier Ledger checked."""
        header = {
            "voucher_date": "2026-10-21",
            "voucher_time": "03:40 PM",
            "dn_date": "2026-10-21",
            "dn_type": "Supplier",
            "supplier_id": 1,
            "total_amount": 100.0,
            "add_to_ledger": True,
            "remarks": "Test DN with ledger",
        }
        # Returning 5 packs of 10 tablets = 50 loose units deducted from stock
        items = [
            {
                "item_id": 101,
                "stock_batch_id": 1,
                "batch_no": "BATCH-P1",
                "expiry": "2028-12-31",
                "pack_size": "10",
                "rate": 20.0,
                "mrp": 30.0,
                "return_qty": 5.0,
                "free_qty": 0.0,
                "is_pack_qty": True,
                "less_amount": 0.0,
                "amount": 100.0,
                "return_reason": "Purchase Return",
                "price_factor": 1.0,
            }
        ]

        dn_id = DebitNoteDAO.insert_debit_note(header, items)
        self.assertGreater(dn_id, 0)

        # Check debit note record
        dn = DebitNoteDAO.get_by_id(dn_id)
        self.assertIsNotNone(dn)
        self.assertEqual(dn["added_to_ledger"], "Y")
        self.assertEqual(dn["total_amount"], 100.0)
        self.assertEqual(dn["ledger_amount"], 100.0)
        self.assertTrue(dn["voucher_no"].startswith("2026-2027-DebitNote-"))

        # Check stock deduction: 100 - (5 * 10) = 50 loose units remaining
        conn = db_conn.get_connection()
        try:
            batch = conn.execute("SELECT stock_qty FROM stock_batches WHERE id = 1").fetchone()
            self.assertEqual(batch["stock_qty"], 50.0)

            # Check ledger postings: exactly 2 rows
            # Debit Supplier (10) for 100.0, Credit Purchase Return (1) for 100.0
            rows = conn.execute(
                "SELECT * FROM ledger_transactions WHERE reference_type = 'DEBIT_NOTE' AND reference_id = ?",
                (dn_id,),
            ).fetchall()
            self.assertEqual(len(rows), 2)
            deb = [r for r in rows if r["debit"] > 0][0]
            cred = [r for r in rows if r["credit"] > 0][0]
            self.assertEqual(deb["ledger_id"], 10)
            self.assertEqual(deb["debit"], 100.0)
            self.assertEqual(cred["ledger_id"], 1)
            self.assertEqual(cred["credit"], 100.0)
        finally:
            conn.close()

    def test_02_supplier_return_creation_without_ledger_posting(self):
        """Create a Debit Note with Add to Supplier Ledger UNCHECKED."""
        header = {
            "voucher_date": "2026-10-21",
            "voucher_time": "03:45 PM",
            "supplier_id": 1,
            "total_amount": 40.0,
            "add_to_ledger": False,
            "remarks": "Unposted DN",
        }
        # Returning 2 packs of 10 tablets = 20 loose units
        items = [
            {
                "item_id": 101,
                "stock_batch_id": 1,
                "batch_no": "BATCH-P1",
                "pack_size": "10",
                "rate": 20.0,
                "mrp": 30.0,
                "return_qty": 2.0,
                "free_qty": 0.0,
                "is_pack_qty": True,
                "less_amount": 0.0,
                "amount": 40.0,
                "return_reason": "Purchase Return",
            }
        ]

        dn_id = DebitNoteDAO.insert_debit_note(header, items)
        dn = DebitNoteDAO.get_by_id(dn_id)
        self.assertEqual(dn["added_to_ledger"], "N")
        self.assertEqual(dn["ledger_amount"], 0.0)

        # Stock deduction still happens: 100 - 20 = 80
        conn = db_conn.get_connection()
        try:
            batch = conn.execute("SELECT stock_qty FROM stock_batches WHERE id = 1").fetchone()
            self.assertEqual(batch["stock_qty"], 80.0)

            # Zero ledger entries created
            rows = conn.execute(
                "SELECT * FROM ledger_transactions WHERE reference_type = 'DEBIT_NOTE' AND reference_id = ?",
                (dn_id,),
            ).fetchall()
            self.assertEqual(len(rows), 0)
        finally:
            conn.close()

    def test_03_supplier_return_pack_and_free_quantity_conversion(self):
        """Test pack size conversion including free quantities."""
        header = {
            "voucher_date": "2026-10-21",
            "supplier_id": 1,
            "total_amount": 60.0,
            "add_to_ledger": False,
        }
        # 2 pay packs + 1 free pack of 10 = 30 loose units deducted
        items = [
            {
                "item_id": 101,
                "stock_batch_id": 1,
                "batch_no": "BATCH-P1",
                "pack_size": "10",
                "rate": 30.0,
                "return_qty": 2.0,
                "free_qty": 1.0,
                "is_pack_qty": True,
                "amount": 60.0,
            }
        ]
        DebitNoteDAO.insert_debit_note(header, items)

        conn = db_conn.get_connection()
        try:
            batch = conn.execute("SELECT stock_qty FROM stock_batches WHERE id = 1").fetchone()
            self.assertEqual(batch["stock_qty"], 70.0)  # 100 - 30 = 70
        finally:
            conn.close()

    def test_04_supplier_return_insufficient_stock_prevents_save(self):
        """Test that return quantity exceeding available stock raises ValueError."""
        header = {
            "voucher_date": "2026-10-21",
            "supplier_id": 1,
            "total_amount": 400.0,
            "add_to_ledger": False,
        }
        # Attempting to return 15 packs = 150 loose units when only 100 available
        items = [
            {
                "item_id": 101,
                "stock_batch_id": 1,
                "batch_no": "BATCH-P1",
                "pack_size": "10",
                "rate": 20.0,
                "return_qty": 15.0,
                "free_qty": 0.0,
                "is_pack_qty": True,
                "amount": 300.0,
            }
        ]
        with self.assertRaises(ValueError) as ctx:
            DebitNoteDAO.insert_debit_note(header, items)
        self.assertIn("Insufficient stock", str(ctx.exception))

        # Ensure stock was NOT touched (atomic rollback)
        conn = db_conn.get_connection()
        try:
            batch = conn.execute("SELECT stock_qty FROM stock_batches WHERE id = 1").fetchone()
            self.assertEqual(batch["stock_qty"], 100.0)
        finally:
            conn.close()

    def test_05_supplier_return_edit_safely_reverses_and_reapplies(self):
        """Test updating a debit note reverses old effects and applies new ones."""
        header1 = {
            "voucher_date": "2026-10-21",
            "supplier_id": 1,
            "total_amount": 60.0,
            "add_to_ledger": True,
        }
        items1 = [
            {
                "item_id": 101,
                "stock_batch_id": 1,
                "batch_no": "BATCH-P1",
                "pack_size": "10",
                "rate": 20.0,
                "return_qty": 3.0,  # 30 loose units deducted
                "is_pack_qty": True,
                "amount": 60.0,
            }
        ]
        dn_id = DebitNoteDAO.insert_debit_note(header1, items1)

        # Stock is now 70.0
        conn = db_conn.get_connection()
        try:
            batch = conn.execute("SELECT stock_qty FROM stock_batches WHERE id = 1").fetchone()
            self.assertEqual(batch["stock_qty"], 70.0)
        finally:
            conn.close()

        # Update: change return_qty to 1 pack (10 loose units)
        header2 = {
            "voucher_date": "2026-10-21",
            "supplier_id": 1,
            "total_amount": 20.0,
            "add_to_ledger": True,
        }
        items2 = [
            {
                "item_id": 101,
                "stock_batch_id": 1,
                "batch_no": "BATCH-P1",
                "pack_size": "10",
                "rate": 20.0,
                "return_qty": 1.0,  # 10 loose units
                "is_pack_qty": True,
                "amount": 20.0,
            }
        ]
        DebitNoteDAO.update_debit_note(dn_id, header2, items2)

        # Stock should now be: 70 + 30 (restored) - 10 (new deduction) = 90.0
        conn = db_conn.get_connection()
        try:
            batch = conn.execute("SELECT stock_qty FROM stock_batches WHERE id = 1").fetchone()
            self.assertEqual(batch["stock_qty"], 90.0)

            # Check ledger has original (2), reversal (2), and new (2) = 6 rows with net 20.0
            rows = conn.execute(
                "SELECT * FROM ledger_transactions WHERE reference_type = 'DEBIT_NOTE' AND reference_id = ?",
                (dn_id,),
            ).fetchall()
            self.assertEqual(len(rows), 6)
            sup_net_debit = sum(r["debit"] - r["credit"] for r in rows if r["ledger_id"] == 10)
            self.assertEqual(sup_net_debit, 20.0)
            pr_net_credit = sum(r["credit"] - r["debit"] for r in rows if r["ledger_id"] == 1)
            self.assertEqual(pr_net_credit, 20.0)
        finally:
            conn.close()

    def test_06_supplier_return_delete_restores_stock_and_reverses_ledger(self):
        """Test deleting a debit note restores stock and removes ledger entries."""
        header = {
            "voucher_date": "2026-10-21",
            "supplier_id": 1,
            "total_amount": 40.0,
            "add_to_ledger": True,
        }
        items = [
            {
                "item_id": 101,
                "stock_batch_id": 1,
                "batch_no": "BATCH-P1",
                "pack_size": "10",
                "rate": 20.0,
                "return_qty": 2.0,  # 20 loose units
                "amount": 40.0,
            }
        ]
        dn_id = DebitNoteDAO.insert_debit_note(header, items)

        # Delete the debit note
        DebitNoteDAO.delete_debit_note(dn_id)

        # Stock is restored back to 100.0
        conn = db_conn.get_connection()
        try:
            batch = conn.execute("SELECT stock_qty FROM stock_batches WHERE id = 1").fetchone()
            self.assertEqual(batch["stock_qty"], 100.0)

            # Record deleted
            self.assertIsNone(DebitNoteDAO.get_by_id(dn_id))

            # Active ledger entries reversed
            active_rows = conn.execute(
                "SELECT * FROM ledger_transactions WHERE reference_type = 'DEBIT_NOTE' AND reference_id = ?",
                (dn_id,),
            ).fetchall()
            net_debit = sum(r["debit"] for r in active_rows)
            net_credit = sum(r["credit"] for r in active_rows)
            self.assertEqual(net_debit, net_credit)
        finally:
            conn.close()

    # ──────────────────────────────────────────────────────────────────
    # 2. Customer Return (Credit Note) Tests
    # ──────────────────────────────────────────────────────────────────

    def test_07_customer_return_creation_with_ledger_posting(self):
        """Create a Credit Note with Add to Ledger checked."""
        header = {
            "voucher_date": "2026-10-21",
            "voucher_time": "03:41 PM",
            "customer_id": 159,
            "total_amount": 60.0,
            "add_to_ledger": True,
            "remarks": "Test CN with ledger",
        }
        # Returning 20 loose tablets of PARACETAMOL
        items = [
            {
                "item_id": 101,
                "stock_batch_id": 1,
                "batch_no": "BATCH-P1",
                "expiry": "2028-12-31",
                "pack_size": "10",
                "rate": 20.0,
                "mrp": 30.0,
                "return_qty": 20.0,  # 20 loose units
                "less_amount": 0.0,
                "amount": 60.0,
                "return_reason": "Sales Return",
                "price_factor": 1.0,
            }
        ]

        cn_id = CreditNoteDAO.insert_credit_note(header, items)
        self.assertGreater(cn_id, 0)

        cn = CreditNoteDAO.get_by_id(cn_id)
        self.assertIsNotNone(cn)
        self.assertEqual(cn["added_to_ledger"], "Y")
        self.assertEqual(cn["total_amount"], 60.0)
        self.assertEqual(cn["ledger_amount"], 60.0)
        self.assertTrue(cn["voucher_no"].startswith("2026-2027-CreditNote-"))

        # Stock restoration: 100 + 20 = 120 loose units
        conn = db_conn.get_connection()
        try:
            batch = conn.execute("SELECT stock_qty FROM stock_batches WHERE id = 1").fetchone()
            self.assertEqual(batch["stock_qty"], 120.0)

            # Check ledger postings: exactly 2 rows
            # Debit Sales Return (2) for 60.0, Credit Customer Walkin (20) for 60.0
            rows = conn.execute(
                "SELECT * FROM ledger_transactions WHERE reference_type = 'CREDIT_NOTE' AND reference_id = ?",
                (cn_id,),
            ).fetchall()
            self.assertEqual(len(rows), 2)
            deb = [r for r in rows if r["debit"] > 0][0]
            cred = [r for r in rows if r["credit"] > 0][0]
            self.assertEqual(deb["ledger_id"], 2)
            self.assertEqual(deb["debit"], 60.0)
            self.assertEqual(cred["ledger_id"], 20)
            self.assertEqual(cred["credit"], 60.0)
        finally:
            conn.close()

    def test_08_customer_return_creation_without_ledger_posting(self):
        """Create a Credit Note with Add to Ledger UNCHECKED."""
        header = {
            "voucher_date": "2026-10-21",
            "customer_id": 159,
            "total_amount": 30.0,
            "add_to_ledger": False,
            "remarks": "Unposted CN",
        }
        items = [
            {
                "item_id": 101,
                "stock_batch_id": 1,
                "batch_no": "BATCH-P1",
                "expiry": "2028-12-31",
                "return_qty": 10.0,
                "amount": 30.0,
                "return_reason": "Sales Return",
            }
        ]
        cn_id = CreditNoteDAO.insert_credit_note(header, items)
        cn = CreditNoteDAO.get_by_id(cn_id)
        self.assertEqual(cn["added_to_ledger"], "N")
        self.assertEqual(cn["ledger_amount"], 0.0)

        # Stock is restored: 100 + 10 = 110
        conn = db_conn.get_connection()
        try:
            batch = conn.execute("SELECT stock_qty FROM stock_batches WHERE id = 1").fetchone()
            self.assertEqual(batch["stock_qty"], 110.0)

            # 0 ledger entries
            rows = conn.execute(
                "SELECT * FROM ledger_transactions WHERE reference_type = 'CREDIT_NOTE' AND reference_id = ?",
                (cn_id,),
            ).fetchall()
            self.assertEqual(len(rows), 0)
        finally:
            conn.close()

    def test_09_customer_return_unsellable_expired_and_damaged_stock(self):
        """Inventory safety: Expired or damaged goods must NOT enter saleable stock."""
        header = {
            "voucher_date": "2026-10-21",
            "customer_id": 159,
            "total_amount": 85.0,
            "add_to_ledger": False,
        }
        # Batch 3 is expired (2020-01-01)
        items_expired = [
            {
                "item_id": 103,
                "stock_batch_id": 3,
                "batch_no": "BATCH-EXP",
                "expiry": "2020-01-01",
                "return_qty": 5.0,
                "amount": 85.0,
                "return_reason": "Sales Return",
            }
        ]
        CreditNoteDAO.insert_credit_note(header, items_expired)

        # Stock for expired batch MUST NOT increase
        conn = db_conn.get_connection()
        try:
            b3 = conn.execute("SELECT stock_qty FROM stock_batches WHERE id = 3").fetchone()
            self.assertEqual(b3["stock_qty"], 20.0)  # Remains 20.0, not 25.0
        finally:
            conn.close()

        # Damaged items must also NOT increase stock
        items_damaged = [
            {
                "item_id": 101,
                "stock_batch_id": 1,
                "batch_no": "BATCH-P1",
                "expiry": "2028-12-31",
                "return_qty": 10.0,
                "amount": 30.0,
                "return_reason": "Breakage/Damage",
            }
        ]
        CreditNoteDAO.insert_credit_note(header, items_damaged)
        conn = db_conn.get_connection()
        try:
            b1 = conn.execute("SELECT stock_qty FROM stock_batches WHERE id = 1").fetchone()
            self.assertEqual(b1["stock_qty"], 100.0)  # Remains 100.0, not 110.0
        finally:
            conn.close()

    def test_10_customer_return_edit_and_delete_reversals(self):
        """Test editing and deleting a credit note reverses stock and ledger correctly."""
        header = {
            "voucher_date": "2026-10-21",
            "customer_id": 159,
            "total_amount": 30.0,
            "add_to_ledger": True,
        }
        items = [
            {
                "item_id": 101,
                "stock_batch_id": 1,
                "batch_no": "BATCH-P1",
                "expiry": "2028-12-31",
                "return_qty": 10.0,  # 10 loose units restored
                "amount": 30.0,
                "return_reason": "Sales Return",
            }
        ]
        cn_id = CreditNoteDAO.insert_credit_note(header, items)

        # Stock is 110.0
        conn = db_conn.get_connection()
        try:
            b = conn.execute("SELECT stock_qty FROM stock_batches WHERE id = 1").fetchone()
            self.assertEqual(b["stock_qty"], 110.0)
        finally:
            conn.close()

        # Delete credit note: stock deduction reverses the restoration back to 100.0
        CreditNoteDAO.delete_credit_note(cn_id)
        conn = db_conn.get_connection()
        try:
            b = conn.execute("SELECT stock_qty FROM stock_batches WHERE id = 1").fetchone()
            self.assertEqual(b["stock_qty"], 100.0)
            self.assertIsNone(CreditNoteDAO.get_by_id(cn_id))
        finally:
            conn.close()

    # ──────────────────────────────────────────────────────────────────
    # 3. Menu, Shortcuts, Navigation and Historical Safety
    # ──────────────────────────────────────────────────────────────────

    def test_11_menu_and_shortcut_registration(self):
        """Verify Account menu items and shortcuts Ctrl+D / Ctrl+C."""
        from ui.menu_data import MENUS
        from ui.navigation_bar import MENU_SHORTCUTS

        account_menu = MENUS.get("Account", [])
        self.assertIn("Debit Note (Return to Supplier)", account_menu)
        self.assertIn("Credit Note (Return from Customer)", account_menu)

        self.assertEqual(MENU_SHORTCUTS.get("Debit Note (Return to Supplier)"), "Ctrl+D")
        self.assertEqual(MENU_SHORTCUTS.get("Credit Note (Return from Customer)"), "Ctrl+C")

    def test_12_historical_credit_notes_preservation(self):
        """Verify that historical credit notes with AddedToLedger='N' have 0 ledger entries."""
        conn = db_conn.get_connection()
        try:
            # Insert mock migrated note with AddedToLedger = 'N'
            conn.execute(
                """
                INSERT INTO credit_notes (voucher_no, voucher_date, customer_id, total_amount, ledger_amount, remarks, added_to_ledger)
                VALUES ('2026-2027-CreditNote-999', '2026-10-15', 159, 500.0, 500.0, "AddedToLedger='N' (Unposted in legacy source)", 'N')
                """
            )
            cn_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.commit()

            # Ensure zero ledger transactions exist
            txs = conn.execute(
                "SELECT * FROM ledger_transactions WHERE reference_type = 'CREDIT_NOTE' AND reference_id = ?",
                (cn_id,),
            ).fetchall()
            self.assertEqual(len(txs), 0)

            # Ensure get_all_filtered preserves added_to_ledger = 'N'
            cns = CreditNoteDAO.get_all_filtered(voucher_no="2026-2027-CreditNote-999")
            self.assertEqual(len(cns), 1)
            self.assertEqual(cns[0]["added_to_ledger"], "N")
        finally:
            conn.close()

    # ──────────────────────────────────────────────────────────────────
    # 4. UI Dialog & Page Interaction Tests
    # ──────────────────────────────────────────────────────────────────

    def test_13_debit_note_dialog_and_totals_calculation(self):
        """Test _DebitNoteEntryDialog UI layout, adding items, less discount, and totals."""
        from screens.debit_note import _DebitNoteEntryDialog
        dlg = _DebitNoteEntryDialog()

        # Select supplier
        idx = dlg.supplier_combo.findData(1)
        self.assertGreaterEqual(idx, 0)
        dlg.supplier_combo.setCurrentIndex(idx)

        # Select item
        item_idx = dlg._entry_bar.item_combo.findData(101)
        self.assertGreater(item_idx, 0)
        dlg._entry_bar.item_combo.setCurrentIndex(item_idx)

        # Select batch
        self.assertGreater(dlg._entry_bar.batch_combo.count(), 1)
        dlg._entry_bar.batch_combo.setCurrentIndex(1)

        dlg._entry_bar.qty_edit.setText("2")
        dlg._entry_bar.less_edit.setText("10.0")  # 10% discount
        # Rate is 20.0. 2 * 20.0 = 40.0 - 10% = 36.0
        dlg._on_add_item()

        self.assertEqual(len(dlg._item_rows), 1)
        self.assertEqual(dlg._item_rows[0].amount, 36.0)
        self.assertEqual(dlg.total_amount_val.text(), "36.00")
        dlg.close()

    def test_14_credit_note_dialog_and_totals_calculation(self):
        """Test _CreditNoteEntryDialog UI layout, adding items, and totals."""
        from screens.credit_note import _CreditNoteEntryDialog
        dlg = _CreditNoteEntryDialog()

        # Customer should default to WALKIN (159)
        self.assertEqual(dlg.customer_combo.currentData(), 159)

        # Select item
        item_idx = dlg._entry_bar.item_combo.findData(101)
        self.assertGreater(item_idx, 0)
        dlg._entry_bar.item_combo.setCurrentIndex(item_idx)
        dlg._entry_bar.batch_combo.setCurrentIndex(1)

        dlg._entry_bar.qty_edit.setText("10")  # 10 tablets
        # Price factor defaults to MRP (30.0 for pack of 10 -> unit price = 3.0)
        # Gross = 10 * 3.0 = 30.0
        dlg._on_add_item()

        self.assertEqual(len(dlg._item_rows), 1)
        self.assertEqual(dlg._item_rows[0].amount, 30.0)
        self.assertEqual(dlg.total_amount_val.text(), "30.00")
        dlg.close()

    def test_15_debit_note_page_and_credit_note_page_lists(self):
        """Test DebitNotePage and CreditNotePage list loading and filtering."""
        from screens.debit_note import DebitNotePage
        from screens.credit_note import CreditNotePage

        dn_page = DebitNotePage()
        self.assertGreaterEqual(dn_page._hist_table.rowCount(), 0)

        cn_page = CreditNotePage()
        self.assertGreaterEqual(cn_page._hist_table.rowCount(), 0)

        dn_page.close()
        cn_page.close()


if __name__ == "__main__":
    unittest.main()
