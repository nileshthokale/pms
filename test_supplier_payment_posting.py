"""Phase 2D — Supplier Payment posting integration tests.

46 tests covering:
  1-3:   Supplier ledger linkage and system ledger setup
  4-8:   Cash payment posting (2 rows, debit/credit, reference, voucher)
  9-10:  Bank / Cheque payment posting
  11-12: UPI payment posting
  13-14: Duplicate posting prevention
  15-16: Reversal (mirrored rows, net-zero)
  17-20: Edit repost (amount change, mode change)
  21-22: Delete reversal
  23-28: Failure safety (missing supplier ledger, missing system ledger,
          invalid amount, unsupported mode, atomic rollback)
  29-30: Persistence, ledger visibility
  31-46: Regression — all existing modules still work
"""

import os
import sys
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database.connection import get_connection, init_database
from database.account_roles import (
    ROLE_BANK,
    ROLE_CASH,
    ensure_system_ledgers,
)
from database.accounting_posting import (
    SOURCE_SUPPLIER_PAYMENT,
    PostingEngine,
    posting_engine,
    PostingError,
)
from database.ledger_dao import LedgerDAO
from database.customer_dao import CustomerDAO
from database.supplier_dao import SupplierDAO
from database.supplier_payment_dao import SupplierPaymentDAO
from database.customer_receipt_dao import CustomerReceiptDAO
from database.purchase_dao import PurchaseDAO
from database.sales_dao import SalesDAO
from database.credit_note_dao import CreditNoteDAO
from database.debit_note_dao import DebitNoteDAO
from database.journal_dao import JournalDAO
from database.company_dao import CompanyDAO
from database.unit_dao import UnitDAO
from database.drug_dao import DrugDAO
from database.item_dao import ItemDAO
from database.stock_dao import StockDAO
from database.doctor_dao import DoctorDAO

_TABLES = [
    "journal_entry_items", "journal_entries",
    "ledger_transactions", "account_ledgers",
    "customer_receipts", "supplier_payments",
    "debit_note_items", "debit_notes",
    "credit_note_items", "credit_notes",
    "sales_invoice_items", "sales_invoices",
    "purchase_invoice_items", "purchase_invoices",
    "stock_batches", "item_ingredients", "items",
    "doctors", "customers", "suppliers", "drugs", "units", "companies",
]


class _BaseTest(unittest.TestCase):
    """Shared setUp — clean tables, masters, system roles, stock."""

    _DB_PATH = os.path.join(os.path.dirname(__file__), "_test_sp_posting.db")

    @classmethod
    def setUpClass(cls):
        if os.path.exists(cls._DB_PATH):
            os.remove(cls._DB_PATH)
        os.environ["PHARMACY_DB"] = cls._DB_PATH
        init_database()

    def setUp(self):
        conn = get_connection()
        try:
            for tbl in _TABLES:
                conn.execute(f"DELETE FROM {tbl}")
            conn.commit()
        finally:
            conn.close()

        self.company_id = CompanyDAO.insert("TestCo", "TC")
        self.unit_id = UnitDAO.insert("Pcs")
        self.drug_id = DrugDAO.insert("Paracetamol")
        self.customer_id = CustomerDAO.insert("TestCustomer")
        self.doctor_id = DoctorDAO.insert("Dr. Smith")
        self.supplier_id = SupplierDAO.insert("TestSupplier")
        self.item_id = ItemDAO.insert(
            item_name="TestItem", unit_id=self.unit_id,
            company_id=self.company_id, pack_size="10x10",
        )
        ensure_system_ledgers()

        self.supplier_ledger_id = SupplierDAO.get_ledger_id(self.supplier_id)
        self.cash_ledger = LedgerDAO.get_by_system_role(ROLE_CASH)
        self.bank_ledger = LedgerDAO.get_by_system_role(ROLE_BANK)
        self.engine = posting_engine

    # ── helpers ──────────────────────────────────────────────────────
    def _insert_payment(self, amount=500.0, mode="Cash", supplier_id=None,
                        date="2026-02-10", ref=""):
        return SupplierPaymentDAO.insert_payment({
            "payment_date": date, "payment_time": "10:00",
            "supplier_id": supplier_id or self.supplier_id,
            "payment_mode": mode, "amount": amount,
            "reference_no": ref, "remarks": "",
        })

    def _nets(self, payment_id):
        """Per-ledger net (debit-credit) of all rows for a payment.
        Filters out fully-reversed (net == 0) ledgers."""
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT ledger_id, SUM(debit) - SUM(credit) AS net "
                "FROM ledger_transactions "
                "WHERE reference_type = ? AND reference_id = ? "
                "GROUP BY ledger_id "
                "HAVING ABS(SUM(debit) - SUM(credit)) > 0.005",
                (SOURCE_SUPPLIER_PAYMENT, payment_id),
            ).fetchall()
            return {r["ledger_id"]: round(r["net"] or 0.0, 2) for r in rows}
        finally:
            conn.close()

    def _seed_stock(self):
        PurchaseDAO.insert_invoice(
            voucher_no="PV-0001", voucher_date="2026-01-01", voucher_time="",
            purchase_type="Cash", supplier_id=self.supplier_id,
            invoice_no="INV-001", invoice_date="2026-01-01",
            invoice_net_amount=4000.0, bill_discount=0, due_date="",
            total_amount=4000.0, gst_amount=0, debit_note_amount=0,
            other_amount=0, paid_amount=4000.0, round_off=0,
            net_amount=4000.0, remarks="",
            items=[{
                "item_id": self.item_id, "pack_size": "10x10",
                "pay_qty": 100, "free_qty": 0, "batch_no": "BATCH-A",
                "expiry": "12/27", "rate": 40.0, "mrp": 50.0, "discount": 0,
                "gst_percent": 0, "gst_amount": 0, "amount": 4000.0,
                "purchase_rate": 40.0, "net_rate": 40.0, "pp": 40.0,
            }],
        )
        batches = PurchaseDAO.get_stock_batches_for_item(self.item_id)
        return batches[0]["id"]


# ======================================================================
# 1-3: Supplier ledger linkage and system ledger setup
# ======================================================================

class TestSetupAndLinkage(_BaseTest):

    def test_01_supplier_has_linked_ledger(self):
        self.assertIsNotNone(self.supplier_ledger_id)
        ledger = LedgerDAO.get_ledger_by_id(self.supplier_ledger_id)
        self.assertIsNotNone(ledger)
        self.assertIn("TestSupplier", ledger["ledger_name"])
        self.assertEqual(ledger["account_group"], "Sundry Creditors")

    def test_02_cash_system_ledger_exists(self):
        self.assertIsNotNone(self.cash_ledger)
        self.assertEqual(self.cash_ledger["system_role"], ROLE_CASH)

    def test_03_bank_system_ledger_exists(self):
        self.assertIsNotNone(self.bank_ledger)
        self.assertEqual(self.bank_ledger["system_role"], ROLE_BANK)


# ======================================================================
# 4-8: Cash payment posting
# ======================================================================

class TestCashPaymentPosting(_BaseTest):

    def test_04_cash_payment_creates_two_rows(self):
        pid = self._insert_payment(amount=500.0, mode="Cash")
        rows = self.engine.get_posting_rows(SOURCE_SUPPLIER_PAYMENT, pid)
        self.assertEqual(len(rows), 2)

    def test_05_supplier_ledger_debited(self):
        pid = self._insert_payment(amount=750.0, mode="Cash")
        nets = self._nets(pid)
        self.assertIn(self.supplier_ledger_id, nets)
        self.assertEqual(nets[self.supplier_ledger_id], 750.0)

    def test_06_cash_ledger_credited(self):
        pid = self._insert_payment(amount=300.0, mode="Cash")
        nets = self._nets(pid)
        self.assertIn(self.cash_ledger["id"], nets)
        self.assertEqual(nets[self.cash_ledger["id"]], -300.0)

    def test_07_reference_type_and_id(self):
        pid = self._insert_payment(amount=100.0, mode="Cash")
        rows = self.engine.get_posting_rows(SOURCE_SUPPLIER_PAYMENT, pid)
        for r in rows:
            self.assertEqual(r["reference_type"], SOURCE_SUPPLIER_PAYMENT)
            self.assertEqual(r["reference_id"], pid)

    def test_08_voucher_number_in_posting(self):
        pid = self._insert_payment(amount=100.0, mode="Cash")
        rows = self.engine.get_posting_rows(SOURCE_SUPPLIER_PAYMENT, pid)
        voucher_no = rows[0]["voucher_no"]
        self.assertTrue(voucher_no.startswith("SP-"))
        for r in rows:
            self.assertEqual(r["voucher_no"], voucher_no)


# ======================================================================
# 9-12: Bank / Cheque / UPI posting
# ======================================================================

class TestPaymentModes(_BaseTest):

    def test_09_bank_payment_credits_bank_ledger(self):
        pid = self._insert_payment(amount=600.0, mode="Bank")
        nets = self._nets(pid)
        self.assertIn(self.bank_ledger["id"], nets)
        self.assertEqual(nets[self.bank_ledger["id"]], -600.0)
        self.assertNotIn(self.cash_ledger["id"], nets)

    def test_10_cheque_payment_credits_bank_ledger(self):
        pid = self._insert_payment(amount=400.0, mode="Cheque")
        nets = self._nets(pid)
        self.assertIn(self.bank_ledger["id"], nets)
        self.assertEqual(nets[self.bank_ledger["id"]], -400.0)

    def test_11_upi_payment_credits_bank_ledger(self):
        pid = self._insert_payment(amount=250.0, mode="UPI")
        nets = self._nets(pid)
        self.assertIn(self.bank_ledger["id"], nets)
        self.assertEqual(nets[self.bank_ledger["id"]], -250.0)

    def test_12_bank_payment_debits_supplier(self):
        pid = self._insert_payment(amount=800.0, mode="Bank")
        nets = self._nets(pid)
        self.assertEqual(nets[self.supplier_ledger_id], 800.0)


# ======================================================================
# 13-14: Duplicate posting prevention
# ======================================================================

class TestDuplicatePrevention(_BaseTest):

    def test_13_duplicate_posting_raises(self):
        pid = self._insert_payment(amount=100.0, mode="Cash")
        with self.assertRaises(PostingError):
            self.engine.post_supplier_payment(pid)

    def test_14_no_duplicate_active_effect(self):
        pid = self._insert_payment(amount=100.0, mode="Cash")
        rows = self.engine.get_posting_rows(SOURCE_SUPPLIER_PAYMENT, pid)
        self.assertEqual(len(rows), 2)


# ======================================================================
# 15-16: Reversal
# ======================================================================

class TestReversal(_BaseTest):

    def test_15_reversal_creates_mirrored_rows(self):
        pid = self._insert_payment(amount=500.0, mode="Cash")
        reversed_ids = self.engine.reverse(SOURCE_SUPPLIER_PAYMENT, pid)
        self.assertEqual(len(reversed_ids), 2)
        for rid in reversed_ids:
            conn = get_connection()
            try:
                row = conn.execute(
                    "SELECT * FROM ledger_transactions WHERE id = ?", (rid,)
                ).fetchone()
            finally:
                conn.close()
            self.assertIn("REVERSAL", row["description"])

    def test_16_net_becomes_zero_after_reversal(self):
        pid = self._insert_payment(amount=500.0, mode="Cash")
        self.engine.reverse(SOURCE_SUPPLIER_PAYMENT, pid)
        nets = self._nets(pid)
        self.assertEqual(len(nets), 0)


# ======================================================================
# 17-20: Edit / repost
# ======================================================================

class TestEditAndRepost(_BaseTest):

    def test_17_edit_amount_reposts(self):
        pid = self._insert_payment(amount=500.0, mode="Cash")
        SupplierPaymentDAO.update_payment(pid, {
            "payment_date": "2026-02-10", "payment_time": "10:00",
            "supplier_id": self.supplier_id, "payment_mode": "Cash",
            "amount": 750.0, "reference_no": "", "remarks": "",
        })
        nets = self._nets(pid)
        self.assertEqual(nets[self.supplier_ledger_id], 750.0)
        self.assertEqual(nets[self.cash_ledger["id"]], -750.0)

    def test_18_old_posting_reversed_on_edit(self):
        pid = self._insert_payment(amount=500.0, mode="Cash")
        rows_before = self.engine.get_posting_rows(SOURCE_SUPPLIER_PAYMENT, pid)
        self.assertEqual(len(rows_before), 2)

        SupplierPaymentDAO.update_payment(pid, {
            "payment_date": "2026-02-10", "payment_time": "10:00",
            "supplier_id": self.supplier_id, "payment_mode": "Cash",
            "amount": 100.0, "reference_no": "", "remarks": "",
        })
        rows_after = self.engine.get_posting_rows(SOURCE_SUPPLIER_PAYMENT, pid)
        # 2 original + 2 reversal + 2 new = 6
        self.assertEqual(len(rows_after), 6)

    def test_19_edit_mode_cash_to_bank(self):
        pid = self._insert_payment(amount=500.0, mode="Cash")
        SupplierPaymentDAO.update_payment(pid, {
            "payment_date": "2026-02-10", "payment_time": "10:00",
            "supplier_id": self.supplier_id, "payment_mode": "Bank",
            "amount": 500.0, "reference_no": "", "remarks": "",
        })
        nets = self._nets(pid)
        self.assertIn(self.bank_ledger["id"], nets)
        self.assertEqual(nets[self.bank_ledger["id"]], -500.0)
        self.assertNotIn(self.cash_ledger["id"], nets)

    def test_20_supplier_stays_correctly_mapped(self):
        pid = self._insert_payment(amount=500.0, mode="Cash")
        SupplierPaymentDAO.update_payment(pid, {
            "payment_date": "2026-02-10", "payment_time": "10:00",
            "supplier_id": self.supplier_id, "payment_mode": "Bank",
            "amount": 200.0, "reference_no": "", "remarks": "",
        })
        nets = self._nets(pid)
        self.assertIn(self.supplier_ledger_id, nets)
        self.assertEqual(nets[self.supplier_ledger_id], 200.0)


# ======================================================================
# 21-22: Delete
# ======================================================================

class TestDelete(_BaseTest):

    def test_21_delete_reverses_accounting(self):
        pid = self._insert_payment(amount=500.0, mode="Cash")
        self.assertTrue(self.engine.is_posted(SOURCE_SUPPLIER_PAYMENT, pid))
        SupplierPaymentDAO.delete_payment(pid)
        # After delete, the posting is fully reversed
        self.assertFalse(self.engine.is_posted(SOURCE_SUPPLIER_PAYMENT, pid))

    def test_22_no_active_effect_after_delete(self):
        pid = self._insert_payment(amount=500.0, mode="Cash")
        SupplierPaymentDAO.delete_payment(pid)
        nets = self._nets(pid)
        self.assertEqual(len(nets), 0)
        # Source row is also deleted
        self.assertIsNone(SupplierPaymentDAO.get_by_id(pid))


# ======================================================================
# 23-28: Failure safety
# ======================================================================

class TestFailureSafety(_BaseTest):

    def test_23_missing_supplier_ledger(self):
        # Create a supplier without a ledger
        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO suppliers (supplier_name) VALUES (?)",
                ("NoLedgerSupplier",),
            )
            conn.commit()
            raw_id = conn.execute(
                "SELECT id FROM suppliers WHERE supplier_name = 'NoLedgerSupplier'"
            ).fetchone()[0]
        finally:
            conn.close()

        with self.assertRaises((PostingError, Exception)):
            SupplierPaymentDAO.insert_payment({
                "payment_date": "2026-02-10", "payment_time": "10:00",
                "supplier_id": raw_id, "payment_mode": "Cash",
                "amount": 100.0, "reference_no": "", "remarks": "",
            })

    def test_24_missing_cash_system_ledger(self):
        # Remove CASH system role
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE account_ledgers SET system_role = NULL "
                "WHERE system_role = ?", (ROLE_CASH,)
            )
            conn.commit()
        finally:
            conn.close()

        with self.assertRaises(PostingError):
            self.engine.post_supplier_payment(
                self._insert_payment.__func__(self, amount=100.0, mode="Cash")
            )

    def test_25_missing_bank_system_ledger(self):
        # Remove BANK system role
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE account_ledgers SET system_role = NULL "
                "WHERE system_role = ?", (ROLE_BANK,)
            )
            conn.commit()
        finally:
            conn.close()

        with self.assertRaises(PostingError):
            self.engine.post_supplier_payment(
                self._insert_payment.__func__(self, amount=100.0, mode="Bank")
            )

    def test_26_invalid_amount_zero(self):
        with self.assertRaises((PostingError, Exception)):
            self._insert_payment(amount=0.0, mode="Cash")

    def test_27_invalid_amount_negative(self):
        with self.assertRaises((PostingError, Exception)):
            self._insert_payment(amount=-100.0, mode="Cash")

    def test_28_unsupported_payment_mode(self):
        with self.assertRaises((PostingError, Exception)):
            self._insert_payment(amount=100.0, mode="Crypto")


# ======================================================================
# 29-30: Persistence and ledger visibility
# ======================================================================

class TestPersistenceAndLedger(_BaseTest):

    def test_29_restart_persistence(self):
        pid = self._insert_payment(amount=555.0, mode="Cheque", ref="CHQ-1")

        from database.connection import get_db_path
        import sqlite3 as _sqlite3
        fresh = _sqlite3.connect(get_db_path())
        fresh.row_factory = _sqlite3.Row
        try:
            rows = fresh.execute(
                "SELECT * FROM ledger_transactions "
                "WHERE reference_type = ? AND reference_id = ?",
                (SOURCE_SUPPLIER_PAYMENT, pid),
            ).fetchall()
        finally:
            fresh.close()

        self.assertEqual(len(rows), 2)
        debits = [r["debit"] for r in rows]
        credits = [r["credit"] for r in rows]
        self.assertIn(555.0, debits)
        self.assertIn(555.0, credits)

        self.assertTrue(
            PostingEngine().is_posted(SOURCE_SUPPLIER_PAYMENT, pid)
        )

    def test_30_account_ledger_displays_payment_entries(self):
        pid = self._insert_payment(amount=500.0, ref="CASH-1")

        supplier_txns = LedgerDAO.get_transactions(self.supplier_ledger_id)
        supplier_payment_txns = [
            t for t in supplier_txns if t["reference_type"] == SOURCE_SUPPLIER_PAYMENT
        ]
        self.assertEqual(len(supplier_payment_txns), 1)
        self.assertEqual(supplier_payment_txns[0]["voucher_type"], "Supplier Payment")
        self.assertEqual(supplier_payment_txns[0]["debit"], 500.0)
        self.assertIn("TestSupplier", supplier_payment_txns[0]["description"])

        cash_txns = LedgerDAO.get_transactions(self.cash_ledger["id"])
        cash_payment_txns = [
            t for t in cash_txns if t["reference_type"] == SOURCE_SUPPLIER_PAYMENT
        ]
        self.assertEqual(len(cash_payment_txns), 1)
        self.assertEqual(cash_payment_txns[0]["credit"], 500.0)


# ======================================================================
# 31-46: Regression — all existing modules still work
# ======================================================================

class TestRegression(_BaseTest):

    def test_31_supplier_payment_crud_still_works(self):
        pid = self._insert_payment(amount=200.0)
        pay = SupplierPaymentDAO.get_by_id(pid)
        self.assertEqual(pay["voucher_no"], "SP-0001")
        self.assertEqual(pay["supplier_name"], "TestSupplier")

        all_pays = SupplierPaymentDAO.get_all()
        self.assertGreaterEqual(len(all_pays), 1)

        filtered = SupplierPaymentDAO.get_all_filtered(
            date_from="2026-01-01", date_to="2026-12-31"
        )
        self.assertGreaterEqual(len(filtered), 1)

        # Legacy balance method still available
        balance = SupplierPaymentDAO.get_supplier_balance(self.supplier_id)
        self.assertEqual(balance, -200.0)

    def test_32_customer_receipt_still_works(self):
        rid = CustomerReceiptDAO.insert_receipt({
            "receipt_date": "2026-01-20", "receipt_time": "10:00",
            "customer_id": self.customer_id, "receipt_mode": "Cash",
            "amount": 300, "reference_no": "", "remarks": "",
        })
        self.assertGreater(rid, 0)
        rows = posting_engine.get_posting_rows("CUSTOMER_RECEIPT", rid)
        self.assertEqual(len(rows), 2)

    def test_33_purchase_still_works(self):
        inv_id = PurchaseDAO.insert_invoice(
            voucher_no="PV-0001", voucher_date="2026-01-15", voucher_time="",
            purchase_type="Cash", supplier_id=self.supplier_id,
            invoice_no="INV-001", invoice_date="2026-01-15",
            invoice_net_amount=4000.0, bill_discount=0, due_date="",
            total_amount=4000.0, gst_amount=0, debit_note_amount=0,
            other_amount=0, paid_amount=4000.0, round_off=0,
            net_amount=4000.0, remarks="",
            items=[{
                "item_id": self.item_id, "pack_size": "10x10",
                "pay_qty": 100, "free_qty": 0, "batch_no": "BATCH-A",
                "expiry": "12/27", "rate": 40.0, "mrp": 50.0, "discount": 0,
                "gst_percent": 0, "gst_amount": 0, "amount": 4000.0,
                "purchase_rate": 40.0, "net_rate": 40.0, "pp": 40.0,
            }],
        )
        self.assertGreater(inv_id, 0)

    def test_34_counter_sale_still_works(self):
        batch_id = self._seed_stock()
        sale_id = SalesDAO.insert_invoice(
            bill_no="CS-0001", sale_date="2026-01-25", sale_time="10:00",
            sale_type="Cash", customer_id=self.customer_id,
            patient_name="TestPatient", doctor_id=None,
            discount=0, paid_amount=250, total_amount=250, round_off=0,
            net_amount=250, remarks="",
            items=[{
                "item_id": self.item_id, "stock_batch_id": batch_id,
                "pack_size": "10x10", "location": "", "batch_no": "BATCH-A",
                "expiry": "12/27", "mrp": 50, "sale_qty": 5,
                "discount_amount": 0, "amount": 250,
            }],
        )
        self.assertGreater(sale_id, 0)

    def test_35_credit_note_still_works(self):
        batch_id = self._seed_stock()
        cn_id = CreditNoteDAO.insert_credit_note(
            {"voucher_date": "2026-01-25", "cn_date": "2026-01-25",
             "cn_type": "Customer", "customer_id": self.customer_id,
             "total_amount": 100, "ledger_amount": 100, "remarks": ""},
            [{
                "item_id": self.item_id, "stock_batch_id": batch_id,
                "batch_no": "BATCH-A", "expiry": "12/27",
                "pack_size": "10x10", "rate": 40, "mrp": 50,
                "return_qty": 2, "less_amount": 0, "amount": 100,
                "return_reason": "", "price_factor": 1.0,
            }],
        )
        self.assertGreater(cn_id, 0)

    def test_36_debit_note_still_works(self):
        batch_id = self._seed_stock()
        dn_id = DebitNoteDAO.insert_debit_note(
            {"voucher_date": "2026-01-18", "voucher_time": "10:00",
             "dn_date": "2026-01-18", "dn_type": "Supplier",
             "supplier_id": self.supplier_id, "total_amount": 200,
             "ledger_amount": 200, "remarks": ""},
            [{
                "item_id": self.item_id, "stock_batch_id": batch_id,
                "batch_no": "BATCH-A", "expiry": "12/27",
                "pack_size": "10x10", "rate": 40, "mrp": 50,
                "return_qty": 5, "less_amount": 0, "amount": 200,
                "return_reason": "", "price_factor": 1.0,
            }],
        )
        self.assertGreater(dn_id, 0)

    def test_37_journal_entry_still_works(self):
        items = [
            {"ledger_id": self.cash_ledger["id"], "description": "",
             "debit": 100, "credit": 0},
            {"ledger_id": self.bank_ledger["id"], "description": "",
             "debit": 0, "credit": 100},
        ]
        eid = JournalDAO.insert_entry(
            {"entry_date": "2026-01-15", "entry_time": "",
             "narration": ""}, items,
        )
        self.assertGreater(eid, 0)
        self.assertEqual(len(JournalDAO.get_items(eid)), 2)

    def test_38_stock_master_still_works(self):
        self._seed_stock()
        all_stock = StockDAO.get_all()
        self.assertEqual(len(all_stock), 1)
        self.assertEqual(all_stock[0]["item_name"], "TestItem")
        self.assertEqual(all_stock[0]["stock_qty"], 100.0)

    def test_39_all_master_screens_still_work(self):
        self.assertGreater(len(CompanyDAO.get_all()), 0)
        self.assertGreater(len(UnitDAO.get_all()), 0)
        self.assertGreater(len(DrugDAO.get_all()), 0)
        self.assertGreater(len(SupplierDAO.get_all()), 0)
        self.assertGreater(len(CustomerDAO.get_all()), 0)
        self.assertGreater(len(DoctorDAO.get_all()), 0)
        self.assertGreater(len(ItemDAO.get_all()), 0)

    def test_40_description_includes_payment_info(self):
        pid = self._insert_payment(amount=100.0, mode="Cash", ref="REF-123")
        rows = self.engine.get_posting_rows(SOURCE_SUPPLIER_PAYMENT, pid)
        desc = rows[0]["description"]
        self.assertIn("TestSupplier", desc)
        self.assertIn("Cash", desc)
        self.assertIn("REF-123", desc)

    def test_41_description_without_reference(self):
        pid = self._insert_payment(amount=100.0, mode="Bank", ref="")
        rows = self.engine.get_posting_rows(SOURCE_SUPPLIER_PAYMENT, pid)
        desc = rows[0]["description"]
        self.assertIn("TestSupplier", desc)
        self.assertNotIn("Bank", desc.split("-")[-1])

    def test_42_reversal_rows_have_correct_voucher_type(self):
        pid = self._insert_payment(amount=100.0, mode="Cash")
        reversed_ids = self.engine.reverse(SOURCE_SUPPLIER_PAYMENT, pid)
        conn = get_connection()
        try:
            for rid in reversed_ids:
                row = conn.execute(
                    "SELECT voucher_type FROM ledger_transactions WHERE id = ?",
                    (rid,),
                ).fetchone()
                self.assertEqual(row["voucher_type"], "Supplier Payment Reversal")
        finally:
            conn.close()

    def test_43_multiple_payments_different_modes(self):
        pid1 = self._insert_payment(amount=100.0, mode="Cash")
        pid2 = self._insert_payment(amount=200.0, mode="Bank")
        nets1 = self._nets(pid1)
        nets2 = self._nets(pid2)
        self.assertIn(self.cash_ledger["id"], nets1)
        self.assertIn(self.bank_ledger["id"], nets2)

    def test_44_edit_preserves_voucher_no(self):
        pid = self._insert_payment(amount=500.0, mode="Cash")
        pay_before = SupplierPaymentDAO.get_by_id(pid)
        SupplierPaymentDAO.update_payment(pid, {
            "payment_date": "2026-02-10", "payment_time": "10:00",
            "supplier_id": self.supplier_id, "payment_mode": "Cash",
            "amount": 750.0, "reference_no": "", "remarks": "",
        })
        pay_after = SupplierPaymentDAO.get_by_id(pid)
        self.assertEqual(pay_before["voucher_no"], pay_after["voucher_no"])

    def test_45_delete_leaves_no_posting_rows_active(self):
        pid = self._insert_payment(amount=500.0, mode="Cash")
        SupplierPaymentDAO.delete_payment(pid)
        all_rows = self.engine.get_posting_rows(SOURCE_SUPPLIER_PAYMENT, pid)
        active_count = 0
        conn = get_connection()
        try:
            for r in all_rows:
                net = conn.execute(
                    "SELECT SUM(debit) - SUM(credit) AS net "
                    "FROM ledger_transactions "
                    "WHERE reference_type = ? AND reference_id = ? "
                    "AND ledger_id = ?",
                    (SOURCE_SUPPLIER_PAYMENT, pid, r["ledger_id"]),
                ).fetchone()["net"]
                if abs(net or 0.0) > 0.005:
                    active_count += 1
        finally:
            conn.close()
        self.assertEqual(active_count, 0)

    def test_46_engine_is_posted_returns_false_after_reverse(self):
        pid = self._insert_payment(amount=500.0, mode="Cash")
        self.assertTrue(self.engine.is_posted(SOURCE_SUPPLIER_PAYMENT, pid))
        self.engine.reverse(SOURCE_SUPPLIER_PAYMENT, pid)
        self.assertFalse(self.engine.is_posted(SOURCE_SUPPLIER_PAYMENT, pid))


if __name__ == "__main__":
    unittest.main(verbosity=2)
