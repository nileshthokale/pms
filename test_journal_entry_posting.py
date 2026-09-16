"""Phase 2J - Journal Entry posting integration tests.

43 tests covering:

  1-5:   Basic posting — row count, debit/credit mapping, reference identity,
         voucher number, descriptions
  6-9:   Balanced posting — debit total, credit total, multi-line correctness
  10-12: Ledger verification — correct ledger per line, transaction visibility,
         balance effect
  13-14: Reference identity — reference_type, reference_id
  15:    Duplicate posting prevention
  16-18: Reversal — mirrored rows, net becomes zero
  19-24: Edit and repost — amount change, ledger change, add line, remove line,
         narration change, voucher unchanged
  25:    Idempotency — posting identity preserved
  26-28: Delete lifecycle — accounting reversed, no active effect
  29-31: Failure safety — missing ledger, invalid journal, unbalanced
  32-33: Failure rollback — failure during posting, failure after update
  34-36: Persistence — fresh connection reads, LedgerDAO visibility, balance
  37-43: Regression — customer receipt, supplier payment, counter sale,
         purchase invoice, credit note, debit note, stock master, all masters
"""

import os
import sqlite3
import sys
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database.connection import get_connection, init_database
from database.account_roles import (
    ROLE_CASH,
    ensure_system_ledgers,
)
from database.accounting_posting import (
    SOURCE_JOURNAL_ENTRY,
    PostingEngine,
    PostingError,
    posting_engine,
)
from database.ledger_dao import LedgerDAO
from database.journal_dao import JournalDAO
from database.customer_dao import CustomerDAO
from database.supplier_dao import SupplierDAO
from database.customer_receipt_dao import CustomerReceiptDAO
from database.supplier_payment_dao import SupplierPaymentDAO
from database.purchase_dao import PurchaseDAO
from database.sales_dao import SalesDAO
from database.credit_note_dao import CreditNoteDAO
from database.debit_note_dao import DebitNoteDAO
from database.company_dao import CompanyDAO
from database.unit_dao import UnitDAO
from database.drug_dao import DrugDAO
from database.item_dao import ItemDAO
from database.stock_dao import StockDAO
from database.doctor_dao import DoctorDAO

TABLES = [
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
    """Fresh DB per module; clean tables + masters + system ledgers per case."""

    _DB_PATH = os.path.join(os.path.dirname(__file__), "_test_je_posting.db")

    @classmethod
    def setUpClass(cls):
        if os.path.exists(cls._DB_PATH):
            os.remove(cls._DB_PATH)
        os.environ["PHARMACY_DB"] = cls._DB_PATH
        init_database()

    def setUp(self):
        conn = get_connection()
        try:
            for tbl in TABLES:
                conn.execute(f"DELETE FROM {tbl}")
            conn.commit()
        finally:
            conn.close()

        ensure_system_ledgers()

        self.company_id = CompanyDAO.insert("TestCo", "TC")
        self.unit_id = UnitDAO.insert("Pcs")
        self.drug_id = DrugDAO.insert("Paracetamol")
        self.customer_id = CustomerDAO.insert("TestCustomer")
        self.doctor_id = DoctorDAO.insert("Dr. Smith")
        self.supplier_id = SupplierDAO.insert("TestSupplier")
        self.item_id = ItemDAO.insert(
            item_name="TestItem", unit_id=self.unit_id,
            company_id=self.company_id, pack_size="10x10",
            reorder_stock_level=10,
        )

        self.cash_ledger_id = LedgerDAO.get_by_system_role(ROLE_CASH)["id"]
        self.capital_ledger_id = LedgerDAO.insert_ledger(
            ledger_name="Capital", account_group="Equity"
        )
        self.sales_ledger_id = LedgerDAO.insert_ledger(
            ledger_name="Sales Account", account_group="Income"
        )
        self.purchase_ledger_id = LedgerDAO.insert_ledger(
            ledger_name="Purchase Account", account_group="Expense"
        )
        self.rent_ledger_id = LedgerDAO.insert_ledger(
            ledger_name="Rent Expense", account_group="Expense"
        )

        self.engine = PostingEngine()

    def _nets(self, entry_id):
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT ledger_id, SUM(debit) - SUM(credit) AS net "
                "FROM ledger_transactions "
                "WHERE reference_type = ? AND reference_id = ? "
                "GROUP BY ledger_id HAVING ABS(SUM(debit) - SUM(credit)) > 0.005",
                (SOURCE_JOURNAL_ENTRY, entry_id),
            ).fetchall()
            return {r["ledger_id"]: round(r["net"], 2) for r in rows}
        finally:
            conn.close()

    def _items(self, d1=1000, c1=0, d2=0, c2=1000, ledger1=None, ledger2=None):
        return [
            {
                "ledger_id": ledger1 or self.cash_ledger_id,
                "description": "Cash received",
                "debit": d1, "credit": c1,
            },
            {
                "ledger_id": ledger2 or self.capital_ledger_id,
                "description": "Capital introduced",
                "debit": d2, "credit": c2,
            },
        ]

    def _header(self, date="2026-03-01", narration="Test JE"):
        return {
            "entry_date": date, "entry_time": "10:00",
            "narration": narration,
        }


# ======================================================================
# 1-5: Basic posting
# ======================================================================

class TestSetupAndPosting(_BaseTest):

    def test_01_creates_posting_rows(self):
        eid = JournalDAO.insert_entry(self._header(), self._items())
        rows = self.engine.get_posting_rows(SOURCE_JOURNAL_ENTRY, eid)
        self.assertEqual(len(rows), 2)

    def test_02_debit_line_maps_correctly(self):
        items = [
            {"ledger_id": self.cash_ledger_id, "description": "Cash in", "debit": 500, "credit": 0},
            {"ledger_id": self.capital_ledger_id, "description": "Capital", "debit": 0, "credit": 500},
        ]
        eid = JournalDAO.insert_entry(self._header(), items)
        rows = self.engine.get_posting_rows(SOURCE_JOURNAL_ENTRY, eid)
        debit_rows = [r for r in rows if r["debit"] > 0]
        self.assertEqual(len(debit_rows), 1)
        self.assertEqual(debit_rows[0]["ledger_id"], self.cash_ledger_id)
        self.assertEqual(debit_rows[0]["debit"], 500.0)

    def test_03_credit_line_maps_correctly(self):
        items = [
            {"ledger_id": self.cash_ledger_id, "description": "Cash in", "debit": 500, "credit": 0},
            {"ledger_id": self.capital_ledger_id, "description": "Capital", "debit": 0, "credit": 500},
        ]
        eid = JournalDAO.insert_entry(self._header(), items)
        rows = self.engine.get_posting_rows(SOURCE_JOURNAL_ENTRY, eid)
        credit_rows = [r for r in rows if r["credit"] > 0]
        self.assertEqual(len(credit_rows), 1)
        self.assertEqual(credit_rows[0]["ledger_id"], self.capital_ledger_id)
        self.assertEqual(credit_rows[0]["credit"], 500.0)

    def test_04_voucher_number_correct(self):
        eid = JournalDAO.insert_entry(self._header(), self._items())
        rows = self.engine.get_posting_rows(SOURCE_JOURNAL_ENTRY, eid)
        for r in rows:
            self.assertEqual(r["voucher_type"], "Journal Entry")
            self.assertIn("JV-", r["voucher_no"])

    def test_05_descriptions_from_journal_lines(self):
        items = [
            {"ledger_id": self.cash_ledger_id, "description": "Cash in", "debit": 100, "credit": 0},
            {"ledger_id": self.capital_ledger_id, "description": "Capital", "debit": 0, "credit": 100},
        ]
        eid = JournalDAO.insert_entry(self._header(), items)
        rows = self.engine.get_posting_rows(SOURCE_JOURNAL_ENTRY, eid)
        descs = {r["ledger_id"]: r["description"] for r in rows}
        self.assertEqual(descs[self.cash_ledger_id], "Cash in")
        self.assertEqual(descs[self.capital_ledger_id], "Capital")


# ======================================================================
# 6-9: Balanced posting
# ======================================================================

class TestBalancedPosting(_BaseTest):

    def test_06_debit_total_correct(self):
        eid = JournalDAO.insert_entry(self._header(), self._items(d1=750, c2=750))
        nets = self._nets(eid)
        self.assertIn(self.cash_ledger_id, nets)
        self.assertEqual(nets[self.cash_ledger_id], 750.0)

    def test_07_credit_total_correct(self):
        eid = JournalDAO.insert_entry(self._header(), self._items(d1=750, c2=750))
        nets = self._nets(eid)
        self.assertIn(self.capital_ledger_id, nets)
        self.assertEqual(nets[self.capital_ledger_id], -750.0)

    def test_08_multi_line_balanced(self):
        items = [
            {"ledger_id": self.cash_ledger_id, "description": "", "debit": 100, "credit": 0},
            {"ledger_id": self.rent_ledger_id, "description": "", "debit": 200, "credit": 0},
            {"ledger_id": self.capital_ledger_id, "description": "", "debit": 0, "credit": 150},
            {"ledger_id": self.sales_ledger_id, "description": "", "debit": 0, "credit": 150},
        ]
        eid = JournalDAO.insert_entry(self._header(), items)
        rows = self.engine.get_posting_rows(SOURCE_JOURNAL_ENTRY, eid)
        self.assertEqual(len(rows), 4)
        nets = self._nets(eid)
        self.assertEqual(len(nets), 4)

    def test_09_only_two_ledgers_in_simple_entry(self):
        eid = JournalDAO.insert_entry(self._header(), self._items())
        nets = self._nets(eid)
        self.assertEqual(len(nets), 2)


# ======================================================================
# 10-12: Ledger verification
# ======================================================================

class TestLedgerVerification(_BaseTest):

    def test_10_correct_ledger_per_line(self):
        items = [
            {"ledger_id": self.cash_ledger_id, "description": "", "debit": 300, "credit": 0},
            {"ledger_id": self.rent_ledger_id, "description": "", "debit": 0, "credit": 300},
        ]
        eid = JournalDAO.insert_entry(self._header(), items)
        nets = self._nets(eid)
        self.assertIn(self.cash_ledger_id, nets)
        self.assertEqual(nets[self.cash_ledger_id], 300.0)
        self.assertIn(self.rent_ledger_id, nets)
        self.assertEqual(nets[self.rent_ledger_id], -300.0)

    def test_11_transaction_visible_via_ledger_dao(self):
        eid = JournalDAO.insert_entry(self._header(), self._items(d1=200, c2=200))
        txns = LedgerDAO.get_transactions(self.cash_ledger_id)
        je_txns = [t for t in txns if t["reference_type"] == "JOURNAL_ENTRY"]
        self.assertEqual(len(je_txns), 1)
        self.assertEqual(je_txns[0]["debit"], 200.0)

    def test_12_balance_reflects_posting(self):
        JournalDAO.insert_entry(self._header(), self._items(d1=500, c2=500))
        bal = LedgerDAO.get_balance(self.cash_ledger_id)
        self.assertGreater(bal["total_debit"], 0)


# ======================================================================
# 13-14: Reference identity
# ======================================================================

class TestReferenceIdentity(_BaseTest):

    def test_13_reference_type_and_id(self):
        eid = JournalDAO.insert_entry(self._header(), self._items())
        rows = self.engine.get_posting_rows(SOURCE_JOURNAL_ENTRY, eid)
        for r in rows:
            self.assertEqual(r["reference_type"], "JOURNAL_ENTRY")
            self.assertEqual(r["reference_id"], eid)

    def test_14_voucher_type_label(self):
        eid = JournalDAO.insert_entry(self._header(), self._items())
        rows = self.engine.get_posting_rows(SOURCE_JOURNAL_ENTRY, eid)
        for r in rows:
            self.assertEqual(r["voucher_type"], "Journal Entry")


# ======================================================================
# 15: Duplicate posting prevention
# ======================================================================

class TestDuplicatePrevention(_BaseTest):

    def test_15_duplicate_posting_refused(self):
        eid = JournalDAO.insert_entry(self._header(), self._items())
        with self.assertRaises(PostingError) as ctx:
            self.engine.post_journal_entry(eid)
        self.assertIn("already has an active", str(ctx.exception))
        rows = self.engine.get_posting_rows(SOURCE_JOURNAL_ENTRY, eid)
        self.assertEqual(len(rows), 2)


# ======================================================================
# 16-18: Reversal
# ======================================================================

class TestReversal(_BaseTest):

    def test_16_reversal_creates_mirrored_rows(self):
        eid = JournalDAO.insert_entry(self._header(), self._items(d1=1000, c2=1000))
        self.engine.reverse(SOURCE_JOURNAL_ENTRY, eid)
        rows = self.engine.get_posting_rows(SOURCE_JOURNAL_ENTRY, eid)
        self.assertEqual(len(rows), 4)

    def test_17_reversal_voucher_type(self):
        eid = JournalDAO.insert_entry(self._header(), self._items(d1=1000, c2=1000))
        self.engine.reverse(SOURCE_JOURNAL_ENTRY, eid)
        rows = self.engine.get_posting_rows(SOURCE_JOURNAL_ENTRY, eid)
        rev_rows = [r for r in rows if "Reversal" in (r["voucher_type"] or "")]
        self.assertEqual(len(rev_rows), 2)
        for r in rev_rows:
            self.assertEqual(r["voucher_type"], "Journal Entry Reversal")

    def test_18_net_becomes_zero_after_reversal(self):
        eid = JournalDAO.insert_entry(self._header(), self._items(d1=500, c2=500))
        self.engine.reverse(SOURCE_JOURNAL_ENTRY, eid)
        nets = self._nets(eid)
        self.assertEqual(len(nets), 0)


# ======================================================================
# 19-24: Edit and repost
# ======================================================================

class TestEditAndRepost(_BaseTest):

    def test_19_edit_amount(self):
        eid = JournalDAO.insert_entry(self._header(), self._items(d1=100, c2=100))
        JournalDAO.update_entry(
            eid,
            self._header(narration="updated"),
            self._items(d1=500, c2=500),
        )
        nets = self._nets(eid)
        self.assertEqual(nets[self.cash_ledger_id], 500.0)
        self.assertEqual(nets[self.capital_ledger_id], -500.0)

    def test_20_old_posting_reversed(self):
        eid = JournalDAO.insert_entry(self._header(), self._items(d1=100, c2=100))
        rows_before = self.engine.get_posting_rows(SOURCE_JOURNAL_ENTRY, eid)
        self.assertEqual(len(rows_before), 2)
        JournalDAO.update_entry(
            eid,
            self._header(),
            self._items(d1=200, c2=200),
        )
        rows_after = self.engine.get_posting_rows(SOURCE_JOURNAL_ENTRY, eid)
        self.assertEqual(len(rows_after), 6)

    def test_21_edit_ledger(self):
        eid = JournalDAO.insert_entry(self._header(), self._items(d1=100, c2=100))
        JournalDAO.update_entry(
            eid,
            self._header(),
            self._items(d1=100, c2=100, ledger1=self.rent_ledger_id),
        )
        nets = self._nets(eid)
        self.assertIn(self.rent_ledger_id, nets)
        self.assertEqual(nets[self.rent_ledger_id], 100.0)
        self.assertNotIn(self.cash_ledger_id, nets)

    def test_22_add_line(self):
        eid = JournalDAO.insert_entry(self._header(), self._items(d1=100, c2=100))
        new_items = [
            {"ledger_id": self.cash_ledger_id, "description": "", "debit": 100, "credit": 0},
            {"ledger_id": self.rent_ledger_id, "description": "", "debit": 200, "credit": 0},
            {"ledger_id": self.capital_ledger_id, "description": "", "debit": 0, "credit": 300},
        ]
        JournalDAO.update_entry(eid, self._header(), new_items)
        rows = self.engine.get_posting_rows(SOURCE_JOURNAL_ENTRY, eid)
        self.assertEqual(len(rows), 7)

    def test_23_remove_line(self):
        items = [
            {"ledger_id": self.cash_ledger_id, "description": "", "debit": 100, "credit": 0},
            {"ledger_id": self.rent_ledger_id, "description": "", "debit": 200, "credit": 0},
            {"ledger_id": self.capital_ledger_id, "description": "", "debit": 0, "credit": 300},
        ]
        eid = JournalDAO.insert_entry(self._header(), items)
        JournalDAO.update_entry(
            eid,
            self._header(),
            self._items(d1=100, c2=100),
        )
        rows = self.engine.get_posting_rows(SOURCE_JOURNAL_ENTRY, eid)
        self.assertEqual(len(rows), 8)

    def test_24_voucher_number_unchanged(self):
        eid = JournalDAO.insert_entry(self._header(), self._items())
        original_voucher = JournalDAO.get_by_id(eid)["voucher_no"]
        JournalDAO.update_entry(eid, self._header(), self._items(d1=200, c2=200))
        entry = JournalDAO.get_by_id(eid)
        self.assertEqual(entry["voucher_no"], original_voucher)


# ======================================================================
# 25: Idempotency
# ======================================================================

class TestIdempotency(_BaseTest):

    def test_25_posting_identity_preserved(self):
        eid = JournalDAO.insert_entry(self._header(), self._items(d1=300, c2=300))
        rows = self.engine.get_posting_rows(SOURCE_JOURNAL_ENTRY, eid)
        for r in rows:
            self.assertEqual(r["reference_type"], "JOURNAL_ENTRY")
            self.assertEqual(r["reference_id"], eid)


# ======================================================================
# 26-28: Delete lifecycle
# ======================================================================

class TestDelete(_BaseTest):

    def test_26_delete_reverses_accounting(self):
        eid = JournalDAO.insert_entry(self._header(), self._items(d1=100, c2=100))
        self.assertTrue(self.engine.is_posted(SOURCE_JOURNAL_ENTRY, eid))
        JournalDAO.delete_entry(eid)
        self.assertFalse(self.engine.is_posted(SOURCE_JOURNAL_ENTRY, eid))

    def test_27_no_active_effect_after_delete(self):
        eid = JournalDAO.insert_entry(self._header(), self._items(d1=200, c2=200))
        JournalDAO.delete_entry(eid)
        nets = self._nets(eid)
        self.assertEqual(len(nets), 0)

    def test_28_reversal_rows_remain(self):
        eid = JournalDAO.insert_entry(self._header(), self._items(d1=100, c2=100))
        JournalDAO.delete_entry(eid)
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM ledger_transactions "
                "WHERE reference_type = ? AND reference_id = ?",
                (SOURCE_JOURNAL_ENTRY, eid),
            ).fetchone()
            self.assertEqual(row["cnt"], 4)
        finally:
            conn.close()


# ======================================================================
# 29-31: Failure safety
# ======================================================================

class TestFailureSafety(_BaseTest):

    def test_29_missing_ledger_fails_safely(self):
        items = [
            {"ledger_id": 99999, "description": "", "debit": 100, "credit": 0},
            {"ledger_id": self.capital_ledger_id, "description": "", "debit": 0, "credit": 100},
        ]
        with self.assertRaises((PostingError, ValueError, sqlite3.IntegrityError)) as ctx:
            JournalDAO.insert_entry(self._header(), items)
        self.assertTrue(len(str(ctx.exception)) > 0)
        conn = get_connection()
        try:
            row = conn.execute("SELECT COUNT(*) AS cnt FROM journal_entries").fetchone()
            self.assertEqual(row["cnt"], 0)
        finally:
            conn.close()

    def test_30_invalid_journal_rejected(self):
        items = [
            {"ledger_id": self.cash_ledger_id, "description": "", "debit": 0, "credit": 0},
            {"ledger_id": self.capital_ledger_id, "description": "", "debit": 0, "credit": 0},
        ]
        with self.assertRaises(ValueError):
            JournalDAO.insert_entry(self._header(), items)

    def test_31_unbalanced_journal_rejected(self):
        items = [
            {"ledger_id": self.cash_ledger_id, "description": "", "debit": 100, "credit": 0},
            {"ledger_id": self.capital_ledger_id, "description": "", "debit": 0, "credit": 50},
        ]
        with self.assertRaises(ValueError):
            JournalDAO.insert_entry(self._header(), items)


# ======================================================================
# 32-33: Failure rollback
# ======================================================================

class TestFailureRollback(_BaseTest):

    def test_32_failure_during_posting_rolls_back(self):
        bad_items = [
            {"ledger_id": 99999, "description": "", "debit": 100, "credit": 0},
            {"ledger_id": self.capital_ledger_id, "description": "", "debit": 0, "credit": 100},
        ]
        with self.assertRaises(Exception):
            JournalDAO.insert_entry(self._header(), bad_items)
        conn = get_connection()
        try:
            row = conn.execute("SELECT COUNT(*) AS cnt FROM journal_entries").fetchone()
            self.assertEqual(row["cnt"], 0)
        finally:
            conn.close()

    def test_33_failure_after_update_rolls_back(self):
        eid = JournalDAO.insert_entry(self._header(), self._items(d1=100, c2=100))
        bad_items = [
            {"ledger_id": 99999, "description": "", "debit": 200, "credit": 0},
            {"ledger_id": self.capital_ledger_id, "description": "", "debit": 0, "credit": 200},
        ]
        with self.assertRaises(Exception):
            JournalDAO.update_entry(eid, self._header(), bad_items)
        entry = JournalDAO.get_by_id(eid)
        self.assertIsNotNone(entry)
        nets = self._nets(eid)
        self.assertEqual(len(nets), 2)


# ======================================================================
# 34-36: Persistence
# ======================================================================

class TestPersistence(_BaseTest):

    def test_34_fresh_connection_reads_posting(self):
        eid = JournalDAO.insert_entry(self._header(), self._items(d1=150, c2=150))
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM ledger_transactions "
                "WHERE reference_type = ? AND reference_id = ?",
                (SOURCE_JOURNAL_ENTRY, eid),
            ).fetchone()
            self.assertEqual(row["cnt"], 2)
        finally:
            conn.close()

    def test_35_ledger_dao_shows_transactions(self):
        eid = JournalDAO.insert_entry(self._header(), self._items(d1=250, c2=250))
        txns = LedgerDAO.get_transactions(self.cash_ledger_id)
        je_txns = [t for t in txns if t["reference_type"] == "JOURNAL_ENTRY"]
        self.assertEqual(len(je_txns), 1)
        self.assertEqual(je_txns[0]["debit"], 250.0)

    def test_36_multiple_entries_cumulate(self):
        for amt in [100, 200, 50]:
            JournalDAO.insert_entry(
                self._header(),
                self._items(d1=amt, c2=amt),
            )
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT SUM(debit) AS total FROM ledger_transactions "
                "WHERE ledger_id = ? AND reference_type = ?",
                (self.cash_ledger_id, SOURCE_JOURNAL_ENTRY),
            ).fetchone()
            self.assertAlmostEqual(row["total"], 350.0, places=2)
        finally:
            conn.close()


# ======================================================================
# 37-43: Regression
# ======================================================================

class TestRegression(_BaseTest):

    def test_37_customer_receipt_still_works(self):
        rec_id = CustomerReceiptDAO.insert_receipt({
            "receipt_date": "2026-03-01", "receipt_time": "10:00",
            "customer_id": self.customer_id, "receipt_mode": "Cash",
            "amount": 300, "reference_no": "", "remarks": "",
        })
        self.assertGreater(rec_id, 0)

    def test_38_supplier_payment_still_works(self):
        pay_id = SupplierPaymentDAO.insert_payment({
            "payment_date": "2026-03-01", "payment_time": "10:00",
            "supplier_id": self.supplier_id, "payment_mode": "Cash",
            "amount": 500, "reference_no": "", "remarks": "",
        })
        self.assertGreater(pay_id, 0)

    def test_39_counter_sale_still_works(self):
        PurchaseDAO.insert_invoice(
            voucher_no="PV-REG", voucher_date="2026-03-01", voucher_time="",
            purchase_type="Cash", supplier_id=self.supplier_id,
            invoice_no="INV-REG", invoice_date="2026-03-01",
            invoice_net_amount=4000.0, bill_discount=0, due_date="",
            total_amount=4000.0, gst_amount=0, debit_note_amount=0,
            other_amount=0, paid_amount=4000.0, round_off=0, net_amount=4000.0,
            remarks="",
            items=[{
                "item_id": self.item_id, "pack_size": "10x10",
                "pay_qty": 100, "free_qty": 0, "batch_no": "BATCH-REG",
                "expiry": "12/27", "rate": 40, "mrp": 50,
                "discount": 0, "gst_percent": 0, "gst_amount": 0,
                "amount": 4000, "purchase_rate": 40, "net_rate": 40, "pp": 40,
            }],
        )
        batches = StockDAO.get_stock_batches_for_item(self.item_id)
        batch_id = batches[0]["id"]
        sale_id = SalesDAO.insert_invoice(
            bill_no="CS-REG", sale_date="2026-03-01", sale_time="10:00",
            sale_type="Cash", customer_id=self.customer_id,
            patient_name="TestPatient", doctor_id=None,
            discount=0, paid_amount=250, total_amount=250,
            round_off=0, net_amount=250, remarks="",
            items=[{
                "item_id": self.item_id, "stock_batch_id": batch_id,
                "pack_size": "10x10", "location": "", "batch_no": "BATCH-REG",
                "expiry": "12/27", "mrp": 50, "sale_qty": 5,
                "discount_amount": 0, "amount": 250,
            }],
        )
        self.assertGreater(sale_id, 0)

    def test_40_purchase_still_works(self):
        PurchaseDAO.insert_invoice(
            voucher_no="PV-40", voucher_date="2026-03-01", voucher_time="",
            purchase_type="Cash", supplier_id=self.supplier_id,
            invoice_no="INV-40", invoice_date="2026-03-01",
            invoice_net_amount=500.0, bill_discount=0, due_date="",
            total_amount=500.0, gst_amount=0, debit_note_amount=0,
            other_amount=0, paid_amount=500.0, round_off=0, net_amount=500.0,
            remarks="",
            items=[{
                "item_id": self.item_id, "pack_size": "10x10",
                "pay_qty": 10, "free_qty": 0, "batch_no": "BATCH-40",
                "expiry": "12/27", "rate": 50, "mrp": 60,
                "discount": 0, "gst_percent": 0, "gst_amount": 0,
                "amount": 500, "purchase_rate": 50, "net_rate": 50, "pp": 50,
            }],
        )
        batches = StockDAO.get_stock_batches_for_item(self.item_id)
        self.assertGreater(len(batches), 0)

    def test_41_credit_note_still_works(self):
        PurchaseDAO.insert_invoice(
            voucher_no="PV-CN", voucher_date="2026-03-01", voucher_time="",
            purchase_type="Cash", supplier_id=self.supplier_id,
            invoice_no="INV-CN", invoice_date="2026-03-01",
            invoice_net_amount=4000.0, bill_discount=0, due_date="",
            total_amount=4000.0, gst_amount=0, debit_note_amount=0,
            other_amount=0, paid_amount=4000.0, round_off=0, net_amount=4000.0,
            remarks="",
            items=[{
                "item_id": self.item_id, "pack_size": "10x10",
                "pay_qty": 100, "free_qty": 0, "batch_no": "BATCH-CN",
                "expiry": "12/27", "rate": 40, "mrp": 50,
                "discount": 0, "gst_percent": 0, "gst_amount": 0,
                "amount": 4000, "purchase_rate": 40, "net_rate": 40, "pp": 40,
            }],
        )
        batches = StockDAO.get_stock_batches_for_item(self.item_id)
        batch_id = batches[0]["id"]
        cn_id = CreditNoteDAO.insert_credit_note(
            {
                "voucher_date": "2026-03-01", "cn_date": "2026-03-01",
                "cn_type": "Customer", "customer_id": self.customer_id,
                "total_amount": 100, "ledger_amount": 100, "remarks": "",
            },
            [{
                "item_id": self.item_id, "stock_batch_id": batch_id,
                "batch_no": "BATCH-CN", "expiry": "12/27",
                "pack_size": "10x10", "rate": 40, "mrp": 50,
                "return_qty": 2, "less_amount": 0,
                "amount": 100, "return_reason": "", "price_factor": 1.0,
            }],
        )
        self.assertGreater(cn_id, 0)

    def test_42_debit_note_still_works(self):
        PurchaseDAO.insert_invoice(
            voucher_no="PV-DN", voucher_date="2026-03-01", voucher_time="",
            purchase_type="Cash", supplier_id=self.supplier_id,
            invoice_no="INV-DN", invoice_date="2026-03-01",
            invoice_net_amount=4000.0, bill_discount=0, due_date="",
            total_amount=4000.0, gst_amount=0, debit_note_amount=0,
            other_amount=0, paid_amount=4000.0, round_off=0, net_amount=4000.0,
            remarks="",
            items=[{
                "item_id": self.item_id, "pack_size": "10x10",
                "pay_qty": 100, "free_qty": 0, "batch_no": "BATCH-DN",
                "expiry": "12/27", "rate": 40, "mrp": 50,
                "discount": 0, "gst_percent": 0, "gst_amount": 0,
                "amount": 4000, "purchase_rate": 40, "net_rate": 40, "pp": 40,
            }],
        )
        batches = StockDAO.get_stock_batches_for_item(self.item_id)
        batch_id = batches[0]["id"]
        dn_id = DebitNoteDAO.insert_debit_note(
            {
                "voucher_date": "2026-03-01", "voucher_time": "10:00",
                "dn_date": "2026-03-01", "dn_type": "Supplier",
                "supplier_id": self.supplier_id,
                "total_amount": 200, "ledger_amount": 200, "remarks": "",
            },
            [{
                "item_id": self.item_id, "stock_batch_id": batch_id,
                "batch_no": "BATCH-DN", "expiry": "12/27",
                "pack_size": "10x10", "rate": 40, "mrp": 50,
                "return_qty": 5, "less_amount": 0,
                "amount": 200, "return_reason": "", "price_factor": 1.0,
            }],
        )
        self.assertGreater(dn_id, 0)

    def test_43_all_master_screens_still_work(self):
        self.assertGreater(len(CompanyDAO.get_all()), 0)
        self.assertGreater(len(UnitDAO.get_all()), 0)
        self.assertGreater(len(DrugDAO.get_all()), 0)
        self.assertGreater(len(SupplierDAO.get_all()), 0)
        self.assertGreater(len(CustomerDAO.get_all()), 0)
        self.assertGreater(len(DoctorDAO.get_all()), 0)
        self.assertGreater(len(ItemDAO.get_all()), 0)


if __name__ == "__main__":
    unittest.main()
