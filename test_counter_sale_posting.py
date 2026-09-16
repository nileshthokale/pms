"""Phase 2E — Counter Sale posting integration tests.

42 tests covering:
  1-8:    Customer-linked credit sale posting (2 rows, debit/credit,
          net amount, reference identity, voucher number)
  9-10:   Fully-paid customer sale / partial-payment customer sale
  11-13:  WALKIN sale (fully paid, underpaid rejected, no fake ledger)
  14-15:  Failure safety (SALES role missing, customer ledger missing)
  16-17:  Duplicate posting prevention
  18-20:  Reversal (mirrored rows, net zero)
  21-27:  Edit / repost (amount, customer, customer→WALKIN, WALKIN
          transition rejected when underpaid)
  28-30:  Delete (accounting reversed, stock restored)
  31:     Transaction failure rolls back sale + stock + accounting
  32-34:  Persistence, ledger visibility, balance consistency
  35-42:  Regression — all existing modules still work
"""

import os
import sqlite3
import sys
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database.connection import get_connection, init_database, get_db_path
from database.account_roles import (
    ROLE_BANK,
    ROLE_CASH,
    ROLE_SALES,
    ensure_system_ledgers,
)
from database.accounting_posting import (
    SOURCE_COUNTER_SALE,
    SOURCE_CUSTOMER_RECEIPT,
    SOURCE_SUPPLIER_PAYMENT,
    PostingEngine,
    posting_engine,
    PostingError,
)
from database.ledger_dao import LedgerDAO
from database.customer_dao import CustomerDAO
from database.supplier_dao import SupplierDAO
from database.customer_receipt_dao import CustomerReceiptDAO
from database.supplier_payment_dao import SupplierPaymentDAO
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

    _DB_PATH = os.path.join(os.path.dirname(__file__), "_test_cs_posting.db")

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
        self.customer2_id = CustomerDAO.insert("SecondCustomer")
        self.doctor_id = DoctorDAO.insert("Dr. Smith")
        self.supplier_id = SupplierDAO.insert("TestSupplier")
        self.item_id = ItemDAO.insert(
            item_name="TestItem", unit_id=self.unit_id,
            company_id=self.company_id, pack_size="10x10",
        )
        ensure_system_ledgers()

        self.customer_ledger_id = CustomerDAO.get_ledger_id(self.customer_id)
        self.customer2_ledger_id = CustomerDAO.get_ledger_id(self.customer2_id)
        self.cash_ledger = LedgerDAO.get_by_system_role(ROLE_CASH)
        self.bank_ledger = LedgerDAO.get_by_system_role(ROLE_BANK)
        self.sales_ledger = LedgerDAO.get_by_system_role(ROLE_SALES)
        self.engine = posting_engine

        self._seed_stock()

    # ── helpers ──────────────────────────────────────────────────────
    def _seed_stock(self, qty=100.0, rate=40.0, mrp=50.0):
        PurchaseDAO.insert_invoice(
            voucher_no="PV-0001", voucher_date="2026-01-01", voucher_time="",
            purchase_type="Cash", supplier_id=self.supplier_id,
            invoice_no="INV-001", invoice_date="2026-01-01",
            invoice_net_amount=qty * rate, bill_discount=0, due_date="",
            total_amount=qty * rate, gst_amount=0, debit_note_amount=0,
            other_amount=0, paid_amount=qty * rate, round_off=0,
            net_amount=qty * rate, remarks="",
            items=[{
                "item_id": self.item_id, "pack_size": "10x10",
                "pay_qty": qty, "free_qty": 0, "batch_no": "BATCH-A",
                "expiry": "12/27", "rate": rate, "mrp": mrp, "discount": 0,
                "gst_percent": 0, "gst_amount": 0, "amount": qty * rate,
                "purchase_rate": rate, "net_rate": rate, "pp": rate,
            }],
        )
        batches = StockDAO.get_stock_batches_for_item(self.item_id)
        self.batch_id = batches[0]["id"]

    def _items(self, qty, mrp=50.0):
        amount = round(qty * mrp, 2)
        return [{
            "item_id": self.item_id, "stock_batch_id": self.batch_id,
            "pack_size": "10x10", "location": "", "batch_no": "BATCH-A",
            "expiry": "12/27", "mrp": mrp, "sale_qty": qty,
            "discount_amount": 0.0, "amount": amount,
        }]

    def _insert_sale(self, bill_no="CS-0001", customer_id=None, walkin=False,
                     sale_type="Credit", paid=0.0, qty=5.0, mrp=50.0,
                     date="2026-01-25"):
        amount = round(qty * mrp, 2)
        cid = None if walkin else (customer_id or self.customer_id)
        return SalesDAO.insert_invoice(
            bill_no=bill_no, sale_date=date, sale_time="10:00",
            sale_type=sale_type, customer_id=cid, patient_name="",
            doctor_id=None, discount=0.0, paid_amount=paid,
            total_amount=amount, round_off=0.0, net_amount=amount,
            remarks="", items=self._items(qty, mrp),
        )

    def _update_sale(self, sale_id, bill_no="CS-0001", customer_id=None,
                     walkin=False, sale_type="Credit", paid=0.0, qty=5.0,
                     mrp=50.0, date="2026-01-26"):
        amount = round(qty * mrp, 2)
        cid = None if walkin else (customer_id or self.customer_id)
        SalesDAO.update_invoice(
            invoice_id=sale_id, bill_no=bill_no, sale_date=date,
            sale_time="11:00", sale_type=sale_type, customer_id=cid,
            patient_name="", doctor_id=None, discount=0.0,
            paid_amount=paid, total_amount=amount, round_off=0.0,
            net_amount=amount, remarks="", items=self._items(qty, mrp),
        )

    def _nets(self, sale_id):
        """Per-ledger net (debit-credit) of all rows for a sale."""
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT ledger_id, SUM(debit) - SUM(credit) AS net "
                "FROM ledger_transactions "
                "WHERE reference_type = ? AND reference_id = ? "
                "GROUP BY ledger_id",
                (SOURCE_COUNTER_SALE, sale_id),
            ).fetchall()
            return {r["ledger_id"]: round(r["net"] or 0.0, 2) for r in rows}
        finally:
            conn.close()

    def _stock_qty(self):
        return StockDAO.get_stock_batches_for_item(self.item_id)[0]["stock_qty"]


# ======================================================================
# 1-10: Customer sale posting + payment treatment
# ======================================================================

class TestCustomerSalePosting(_BaseTest):

    def test_01_customer_linked_sale(self):
        sale_id = self._insert_sale()
        self.assertGreater(sale_id, 0)
        self.assertIsNotNone(SalesDAO.get_by_id(sale_id))

    def test_02_exactly_two_posting_rows(self):
        sale_id = self._insert_sale()  # credit sale, paid=0
        rows = self.engine.get_posting_rows(SOURCE_COUNTER_SALE, sale_id)
        self.assertEqual(len(rows), 2)

    def test_03_customer_ledger_debit(self):
        sale_id = self._insert_sale()
        rows = self.engine.get_posting_rows(SOURCE_COUNTER_SALE, sale_id)
        cust = [r for r in rows if r["ledger_id"] == self.customer_ledger_id]
        self.assertEqual(len(cust), 1)
        self.assertEqual(cust[0]["debit"], 250.0)
        self.assertEqual(cust[0]["credit"], 0.0)

    def test_04_sales_ledger_credit(self):
        sale_id = self._insert_sale()
        rows = self.engine.get_posting_rows(SOURCE_COUNTER_SALE, sale_id)
        sales = [r for r in rows if r["ledger_id"] == self.sales_ledger["id"]]
        self.assertEqual(len(sales), 1)
        self.assertEqual(sales[0]["debit"], 0.0)
        self.assertEqual(sales[0]["credit"], 250.0)

    def test_05_correct_net_amount(self):
        sale_id = self._insert_sale(qty=7, mrp=50.0)  # net 350
        rows = self.engine.get_posting_rows(SOURCE_COUNTER_SALE, sale_id)
        self.assertEqual(sum(r["debit"] for r in rows), 350.0)
        self.assertEqual(sum(r["credit"] for r in rows), 350.0)
        sale = SalesDAO.get_by_id(sale_id)
        self.assertEqual(sale["net_amount"], 350.0)

    def test_06_reference_type(self):
        sale_id = self._insert_sale()
        for r in self.engine.get_posting_rows(SOURCE_COUNTER_SALE, sale_id):
            self.assertEqual(r["reference_type"], "COUNTER_SALE")

    def test_07_reference_id(self):
        sale_id = self._insert_sale()
        for r in self.engine.get_posting_rows(SOURCE_COUNTER_SALE, sale_id):
            self.assertEqual(r["reference_id"], sale_id)

    def test_08_voucher_number(self):
        sale_id = self._insert_sale(bill_no="CS-0042")
        for r in self.engine.get_posting_rows(SOURCE_COUNTER_SALE, sale_id):
            self.assertEqual(r["voucher_no"], "CS-0042")
            self.assertEqual(r["voucher_type"], "Counter Sale")

    def test_09_fully_paid_customer_sale(self):
        # Approved policy (docs §10.B): fully paid with customer ->
        # Debit CASH (sale_type Cash) for paid / Credit SALES for net.
        sale_id = self._insert_sale(sale_type="Cash", paid=250.0)
        rows = self.engine.get_posting_rows(SOURCE_COUNTER_SALE, sale_id)
        self.assertEqual(len(rows), 2)  # no zero customer leg
        cash = [r for r in rows if r["ledger_id"] == self.cash_ledger["id"]]
        self.assertEqual(len(cash), 1)
        self.assertEqual(cash[0]["debit"], 250.0)
        self.assertIn("TestCustomer", cash[0]["description"])

    def test_10_partial_payment_customer_sale(self):
        # Approved policy: Debit tender paid / Debit Customer remainder /
        # Credit SALES net. "Credit"-type paid portion -> CASH.
        sale_id = self._insert_sale(sale_type="Credit", paid=100.0)
        rows = self.engine.get_posting_rows(SOURCE_COUNTER_SALE, sale_id)
        self.assertEqual(len(rows), 3)
        nets = self._nets(sale_id)
        self.assertEqual(nets[self.cash_ledger["id"]], 100.0)
        self.assertEqual(nets[self.customer_ledger_id], 150.0)
        self.assertEqual(nets[self.sales_ledger["id"]], -250.0)


# ======================================================================
# 11-13: WALKIN sales
# ======================================================================

class TestWalkinSales(_BaseTest):

    def test_11_walkin_fully_paid_sale(self):
        sale_id = self._insert_sale(
            walkin=True, sale_type="Cash", paid=250.0
        )
        self.assertGreater(sale_id, 0)
        rows = self.engine.get_posting_rows(SOURCE_COUNTER_SALE, sale_id)
        self.assertEqual(len(rows), 2)
        nets = self._nets(sale_id)
        self.assertEqual(nets[self.cash_ledger["id"]], 250.0)
        self.assertEqual(nets[self.sales_ledger["id"]], -250.0)
        self.assertIn("Walk-in", rows[0]["description"])

    def test_12_walkin_underpaid_rejected(self):
        with self.assertRaises(PostingError) as ctx:
            self._insert_sale(walkin=True, sale_type="Cash", paid=100.0)
        self.assertIn("fully paid", str(ctx.exception))

        # Nothing saved: no sale, no ledger rows, stock untouched
        conn = get_connection()
        try:
            sales = conn.execute(
                "SELECT COUNT(*) FROM sales_invoices"
            ).fetchone()[0]
            txns = conn.execute(
                "SELECT COUNT(*) FROM ledger_transactions "
                "WHERE reference_type = ?",
                (SOURCE_COUNTER_SALE,),
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(sales, 0)
        self.assertEqual(txns, 0)
        self.assertEqual(self._stock_qty(), 100.0)

    def test_13_walkin_touches_no_customer_ledger(self):
        # No fake WALKIN customer ledger is ever created, and the posting
        # never touches any customer's ledger.
        sale_id = self._insert_sale(
            walkin=True, sale_type="Cash", paid=250.0
        )
        rows = self.engine.get_posting_rows(SOURCE_COUNTER_SALE, sale_id)
        used = {r["ledger_id"] for r in rows}
        self.assertNotIn(self.customer_ledger_id, used)
        self.assertNotIn(self.customer2_ledger_id, used)
        self.assertEqual(
            len(LedgerDAO.get_transactions(self.customer_ledger_id)), 0
        )

        conn = get_connection()
        try:
            fake = conn.execute(
                "SELECT COUNT(*) FROM account_ledgers "
                "WHERE ledger_name LIKE '%alk%'"
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(fake, 0)


# ======================================================================
# 14-17: Failure safety and duplicate prevention
# ======================================================================

class TestFailureAndDuplicates(_BaseTest):

    def test_14_sales_ledger_missing_rollback(self):
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE account_ledgers SET system_role = NULL "
                "WHERE system_role = ?", (ROLE_SALES,)
            )
            conn.commit()
        finally:
            conn.close()

        with self.assertRaises(PostingError) as ctx:
            self._insert_sale()
        self.assertIn("'SALES' is not configured", str(ctx.exception))

        conn = get_connection()
        try:
            sales = conn.execute(
                "SELECT COUNT(*) FROM sales_invoices"
            ).fetchone()[0]
            txns = conn.execute(
                "SELECT COUNT(*) FROM ledger_transactions "
                "WHERE reference_type = ?",
                (SOURCE_COUNTER_SALE,),
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(sales, 0)
        self.assertEqual(txns, 0)
        self.assertEqual(self._stock_qty(), 100.0)

    def test_15_customer_ledger_missing_rollback(self):
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE customers SET ledger_id = NULL WHERE id = ?",
                (self.customer_id,),
            )
            conn.commit()
        finally:
            conn.close()

        with self.assertRaises(PostingError) as ctx:
            self._insert_sale()
        self.assertIn("no linked Account Ledger", str(ctx.exception))

        conn = get_connection()
        try:
            sales = conn.execute(
                "SELECT COUNT(*) FROM sales_invoices"
            ).fetchone()[0]
            txns = conn.execute(
                "SELECT COUNT(*) FROM ledger_transactions "
                "WHERE reference_type = ?",
                (SOURCE_COUNTER_SALE,),
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(sales, 0)
        self.assertEqual(txns, 0)
        self.assertEqual(self._stock_qty(), 100.0)

    def test_16_duplicate_posting_rejected(self):
        sale_id = self._insert_sale()
        with self.assertRaises(PostingError) as ctx:
            self.engine.post_counter_sale(sale_id)
        self.assertIn("already has an active", str(ctx.exception))

    def test_17_no_duplicate_active_effect(self):
        sale_id = self._insert_sale()
        try:
            self.engine.post_counter_sale(sale_id)
        except PostingError:
            pass  # expected refusal
        rows = self.engine.get_posting_rows(SOURCE_COUNTER_SALE, sale_id)
        self.assertEqual(len(rows), 2)
        self.assertTrue(self.engine.is_posted(SOURCE_COUNTER_SALE, sale_id))
        bal = LedgerDAO.get_balance(self.customer_ledger_id)
        self.assertEqual(bal["total_debit"], 250.0)


# ======================================================================
# 18-20: Reversal
# ======================================================================

class TestReversal(_BaseTest):

    def test_18_reverse_sale(self):
        sale_id = self._insert_sale()
        new_ids = self.engine.reverse(SOURCE_COUNTER_SALE, sale_id)
        self.assertEqual(len(new_ids), 2)
        rows = self.engine.get_posting_rows(SOURCE_COUNTER_SALE, sale_id)
        self.assertEqual(len(rows), 4)

    def test_19_mirrored_reversal_rows(self):
        sale_id = self._insert_sale()
        self.engine.reverse(SOURCE_COUNTER_SALE, sale_id)
        rows = self.engine.get_posting_rows(SOURCE_COUNTER_SALE, sale_id)

        rev_cust = [
            r for r in rows
            if r["ledger_id"] == self.customer_ledger_id
            and r["voucher_type"] == "Counter Sale Reversal"
        ]
        self.assertEqual(len(rev_cust), 1)
        self.assertEqual(rev_cust[0]["debit"], 0.0)
        self.assertEqual(rev_cust[0]["credit"], 250.0)
        self.assertIn("REVERSAL:", rev_cust[0]["description"])
        self.assertEqual(rev_cust[0]["reference_id"], sale_id)
        self.assertEqual(rev_cust[0]["voucher_no"], "CS-0001")

        rev_sales = [
            r for r in rows
            if r["ledger_id"] == self.sales_ledger["id"]
            and r["voucher_type"] == "Counter Sale Reversal"
        ]
        self.assertEqual(len(rev_sales), 1)
        self.assertEqual(rev_sales[0]["debit"], 250.0)

        # Reversing an already-reversed posting is a safe no-op
        self.assertEqual(
            self.engine.reverse(SOURCE_COUNTER_SALE, sale_id), []
        )

    def test_20_active_net_zero(self):
        sale_id = self._insert_sale()
        self.engine.reverse(SOURCE_COUNTER_SALE, sale_id)
        for net in self._nets(sale_id).values():
            self.assertEqual(net, 0.0)
        self.assertFalse(
            self.engine.is_posted(SOURCE_COUNTER_SALE, sale_id)
        )


# ======================================================================
# 21-27: Edit / repost
# ======================================================================

class TestEditRepost(_BaseTest):

    def test_21_edit_sale_amount(self):
        sale_id = self._insert_sale()          # net 250
        self._update_sale(sale_id, qty=6)      # net 300
        sale = SalesDAO.get_by_id(sale_id)
        self.assertEqual(sale["net_amount"], 300.0)
        nets = self._nets(sale_id)
        self.assertEqual(nets[self.customer_ledger_id], 300.0)
        self.assertEqual(nets[self.sales_ledger["id"]], -300.0)

    def test_22_old_posting_reversed_new_posted(self):
        sale_id = self._insert_sale()
        self._update_sale(sale_id, qty=6)
        rows = self.engine.get_posting_rows(SOURCE_COUNTER_SALE, sale_id)
        # 2 original + 2 reversal + 2 new posting
        self.assertEqual(len(rows), 6)
        reversals = [
            r for r in rows
            if r["voucher_type"] == "Counter Sale Reversal"
        ]
        self.assertEqual(len(reversals), 2)
        amounts = {r["debit"] or r["credit"] for r in reversals}
        self.assertEqual(amounts, {250.0})

    def test_23_edit_customer(self):
        sale_id = self._insert_sale()  # customer 1
        self._update_sale(sale_id, customer_id=self.customer2_id)
        sale = SalesDAO.get_by_id(sale_id)
        self.assertEqual(sale["customer_id"], self.customer2_id)

    def test_24_posting_moves_to_correct_customer_ledger(self):
        sale_id = self._insert_sale()
        self._update_sale(sale_id, customer_id=self.customer2_id)
        nets = self._nets(sale_id)
        self.assertEqual(nets.get(self.customer_ledger_id, 0.0), 0.0)
        self.assertEqual(nets[self.customer2_ledger_id], 250.0)
        self.assertEqual(nets[self.sales_ledger["id"]], -250.0)
        self.assertTrue(self.engine.is_posted(SOURCE_COUNTER_SALE, sale_id))
        # Old customer's ledger nets back to zero balance
        old_bal = LedgerDAO.get_balance(self.customer_ledger_id)
        self.assertEqual(old_bal["closing_balance"], 0.0)

    def test_25_customer_to_walkin_where_approved(self):
        sale_id = self._insert_sale()  # credit sale, customer 1
        self._update_sale(sale_id, walkin=True, sale_type="Cash",
                          paid=250.0)
        sale = SalesDAO.get_by_id(sale_id)
        self.assertIsNone(sale["customer_id"])
        nets = self._nets(sale_id)
        self.assertEqual(nets.get(self.customer_ledger_id, 0.0), 0.0)
        self.assertEqual(nets[self.cash_ledger["id"]], 250.0)
        self.assertEqual(nets[self.sales_ledger["id"]], -250.0)

    def test_26_cash_debit_for_valid_walkin(self):
        sale_id = self._insert_sale()
        self._update_sale(sale_id, walkin=True, sale_type="Cash",
                          paid=250.0)
        cash_txns = LedgerDAO.get_transactions(self.cash_ledger["id"])
        cash_txns = [t for t in cash_txns
                     if t["reference_type"] == SOURCE_COUNTER_SALE]
        self.assertEqual(len(cash_txns), 1)
        self.assertEqual(cash_txns[0]["voucher_type"], "Counter Sale")
        self.assertEqual(cash_txns[0]["debit"], 250.0)

    def test_27_invalid_walkin_transition_rejected(self):
        sale_id = self._insert_sale()
        with self.assertRaises(PostingError) as ctx:
            self._update_sale(sale_id, walkin=True, sale_type="Cash",
                              paid=100.0)
        self.assertIn("fully paid", str(ctx.exception))

        # Everything rolled back: sale still customer-linked and active
        sale = SalesDAO.get_by_id(sale_id)
        self.assertEqual(sale["customer_id"], self.customer_id)
        self.assertEqual(sale["paid_amount"], 0.0)
        rows = self.engine.get_posting_rows(SOURCE_COUNTER_SALE, sale_id)
        self.assertEqual(len(rows), 2)  # no reversal rows survived
        self.assertTrue(self.engine.is_posted(SOURCE_COUNTER_SALE, sale_id))
        self.assertEqual(self._stock_qty(), 95.0)


# ======================================================================
# 28-31: Delete and atomic rollback
# ======================================================================

class TestDeleteAndRollback(_BaseTest):

    def test_28_delete_sale(self):
        sale_id = self._insert_sale()
        SalesDAO.delete_invoice(sale_id)
        self.assertIsNone(SalesDAO.get_by_id(sale_id))

    def test_29_accounting_reversed_on_delete(self):
        sale_id = self._insert_sale()
        SalesDAO.delete_invoice(sale_id)
        for net in self._nets(sale_id).values():
            self.assertEqual(net, 0.0)
        rows = self.engine.get_posting_rows(SOURCE_COUNTER_SALE, sale_id)
        self.assertEqual(len(rows), 4)  # original + reversal, kept
        self.assertFalse(
            self.engine.is_posted(SOURCE_COUNTER_SALE, sale_id)
        )

    def test_30_stock_restored_on_delete(self):
        sale_id = self._insert_sale()
        self.assertEqual(self._stock_qty(), 95.0)
        SalesDAO.delete_invoice(sale_id)
        self.assertEqual(self._stock_qty(), 100.0)

    def test_31_failure_rolls_back_sale_stock_accounting(self):
        sale_id = self._insert_sale()
        self.assertEqual(self._stock_qty(), 95.0)

        conn = get_connection()
        try:
            conn.execute(
                "UPDATE account_ledgers SET system_role = NULL "
                "WHERE system_role = ?", (ROLE_SALES,)
            )
            conn.commit()
        finally:
            conn.close()

        with self.assertRaises(PostingError):
            self._update_sale(sale_id, qty=6)

        # Sale unchanged, old posting still active, stock unchanged
        sale = SalesDAO.get_by_id(sale_id)
        self.assertEqual(sale["net_amount"], 250.0)
        self.assertEqual(sale["customer_id"], self.customer_id)
        rows = self.engine.get_posting_rows(SOURCE_COUNTER_SALE, sale_id)
        self.assertEqual(len(rows), 2)
        self.assertTrue(self.engine.is_posted(SOURCE_COUNTER_SALE, sale_id))
        self.assertEqual(self._stock_qty(), 95.0)


# ======================================================================
# 32-34: Persistence, ledger visibility, balance consistency
# ======================================================================

class TestPersistenceAndLedger(_BaseTest):

    def test_32_persistence_after_restart(self):
        sale_id = self._insert_sale(qty=4)  # net 200

        # Simulate application restart: brand-new connection reading
        # committed state only.
        fresh = sqlite3.connect(get_db_path())
        fresh.row_factory = sqlite3.Row
        try:
            rows = fresh.execute(
                "SELECT * FROM ledger_transactions "
                "WHERE reference_type = ? AND reference_id = ?",
                (SOURCE_COUNTER_SALE, sale_id),
            ).fetchall()
        finally:
            fresh.close()

        self.assertEqual(len(rows), 2)
        debits = [r["debit"] for r in rows]
        credits = [r["credit"] for r in rows]
        self.assertIn(200.0, debits)
        self.assertIn(200.0, credits)

        self.assertTrue(
            PostingEngine().is_posted(SOURCE_COUNTER_SALE, sale_id)
        )

    def test_33_account_ledger_displays_entries(self):
        sale_id = self._insert_sale()

        # The Account Ledger screen reads LedgerDAO.get_transactions()
        cust_txns = LedgerDAO.get_transactions(self.customer_ledger_id)
        self.assertEqual(len(cust_txns), 1)
        self.assertEqual(cust_txns[0]["voucher_type"], "Counter Sale")
        self.assertEqual(cust_txns[0]["voucher_no"], "CS-0001")
        self.assertEqual(cust_txns[0]["debit"], 250.0)

        cust_bal = LedgerDAO.get_balance(self.customer_ledger_id)
        self.assertEqual(cust_bal["closing_balance"], 250.0)
        self.assertEqual(cust_bal["closing_balance_type"], "Debit")

        sales_txns = LedgerDAO.get_transactions(self.sales_ledger["id"])
        self.assertEqual(len(sales_txns), 1)
        self.assertEqual(sales_txns[0]["credit"], 250.0)
        sales_bal = LedgerDAO.get_balance(self.sales_ledger["id"])
        self.assertEqual(sales_bal["closing_balance"], 250.0)
        self.assertEqual(sales_bal["closing_balance_type"], "Credit")

    def test_34_customer_balance_consistency(self):
        # Credit sale 500 + receipt 200: the ledger balance (sales and
        # receipts both post) must equal the legacy balance method.
        # (Credit notes are not posted yet — the one remaining
        # divergence after this phase.)
        sale_id = self._insert_sale(qty=10)  # net 500, credit sale
        CustomerReceiptDAO.insert_receipt({
            "receipt_date": "2026-01-26", "receipt_time": "10:00",
            "customer_id": self.customer_id, "receipt_mode": "Cash",
            "amount": 200.0, "reference_no": "", "remarks": "",
        })

        legacy = CustomerReceiptDAO.get_customer_balance(self.customer_id)
        self.assertEqual(legacy, 300.0)

        ledger_bal = LedgerDAO.get_balance(self.customer_ledger_id)
        self.assertEqual(ledger_bal["closing_balance"], 300.0)
        self.assertEqual(ledger_bal["closing_balance_type"], "Debit")
        self.assertTrue(self.engine.is_posted(SOURCE_COUNTER_SALE, sale_id))


# ======================================================================
# 35-42: Regression — all existing modules still work
# ======================================================================

class TestRegression(_BaseTest):

    def test_35_customer_receipt_still_works(self):
        rid = CustomerReceiptDAO.insert_receipt({
            "receipt_date": "2026-01-26", "receipt_time": "10:00",
            "customer_id": self.customer_id, "receipt_mode": "Bank",
            "amount": 150.0, "reference_no": "NEFT-1", "remarks": "",
        })
        self.assertGreater(rid, 0)
        rows = self.engine.get_posting_rows(SOURCE_CUSTOMER_RECEIPT, rid)
        self.assertEqual(len(rows), 2)

    def test_36_supplier_payment_still_works(self):
        pid = SupplierPaymentDAO.insert_payment({
            "payment_date": "2026-01-26", "payment_time": "10:00",
            "supplier_id": self.supplier_id, "payment_mode": "Cash",
            "amount": 400.0, "reference_no": "", "remarks": "",
        })
        self.assertGreater(pid, 0)
        rows = self.engine.get_posting_rows(SOURCE_SUPPLIER_PAYMENT, pid)
        self.assertEqual(len(rows), 2)

    def test_37_purchase_still_works(self):
        inv_id = PurchaseDAO.insert_invoice(
            voucher_no="PV-0002", voucher_date="2026-02-01", voucher_time="",
            purchase_type="Credit", supplier_id=self.supplier_id,
            invoice_no="INV-002", invoice_date="2026-02-01",
            invoice_net_amount=1000.0, bill_discount=0, due_date="",
            total_amount=1000.0, gst_amount=0, debit_note_amount=0,
            other_amount=0, paid_amount=0, round_off=0,
            net_amount=1000.0, remarks="",
            items=[{
                "item_id": self.item_id, "pack_size": "10x10",
                "pay_qty": 20, "free_qty": 0, "batch_no": "BATCH-B",
                "expiry": "12/28", "rate": 50.0, "mrp": 60.0, "discount": 0,
                "gst_percent": 0, "gst_amount": 0, "amount": 1000.0,
                "purchase_rate": 50.0, "net_rate": 50.0, "pp": 50.0,
            }],
        )
        self.assertGreater(inv_id, 0)
        # Purchase invoice IS posted (Phase 2F)
        rows = self.engine.get_posting_rows("PURCHASE_INVOICE", inv_id)
        self.assertEqual(len(rows), 2)

    def test_38_credit_note_still_works(self):
        cn_id = CreditNoteDAO.insert_credit_note(
            {"voucher_date": "2026-01-26", "cn_date": "2026-01-26",
             "cn_type": "Customer", "customer_id": self.customer_id,
             "total_amount": 100, "ledger_amount": 100, "remarks": ""},
            [{
                "item_id": self.item_id, "stock_batch_id": self.batch_id,
                "batch_no": "BATCH-A", "expiry": "12/27",
                "pack_size": "10x10", "rate": 40, "mrp": 50,
                "return_qty": 2, "less_amount": 0, "amount": 100,
                "return_reason": "", "price_factor": 1.0,
            }],
        )
        self.assertGreater(cn_id, 0)
        # Credit notes ARE posted (Phase 2G)
        self.assertEqual(
            len(self.engine.get_posting_rows("CREDIT_NOTE", cn_id)), 2
        )

    def test_39_debit_note_still_works(self):
        dn_id = DebitNoteDAO.insert_debit_note(
            {"voucher_date": "2026-01-26", "voucher_time": "11:00",
             "dn_date": "2026-01-26", "dn_type": "Supplier",
             "supplier_id": self.supplier_id, "total_amount": 200,
             "ledger_amount": 200, "remarks": ""},
            [{
                "item_id": self.item_id, "stock_batch_id": self.batch_id,
                "batch_no": "BATCH-A", "expiry": "12/27",
                "pack_size": "10x10", "rate": 40, "mrp": 50,
                "return_qty": 5, "less_amount": 0, "amount": 200,
                "return_reason": "", "price_factor": 1.0,
            }],
        )
        self.assertGreater(dn_id, 0)
        self.assertEqual(
            len(self.engine.get_posting_rows("DEBIT_NOTE", dn_id)), 2
        )

    def test_40_journal_entry_still_works(self):
        eid = JournalDAO.insert_entry(
            {"entry_date": "2026-01-26", "entry_time": "", "narration": ""},
            [
                {"ledger_id": self.cash_ledger["id"], "description": "",
                 "debit": 100, "credit": 0},
                {"ledger_id": self.bank_ledger["id"], "description": "",
                 "debit": 0, "credit": 100},
            ],
        )
        self.assertGreater(eid, 0)
        self.assertEqual(len(JournalDAO.get_items(eid)), 2)

    def test_41_stock_master_still_works(self):
        self._insert_sale()
        all_stock = StockDAO.get_all()
        self.assertEqual(len(all_stock), 1)
        self.assertEqual(all_stock[0]["item_name"], "TestItem")
        self.assertEqual(all_stock[0]["stock_qty"], 95.0)
        found = StockDAO.search(item_name="TestItem")
        self.assertEqual(len(found), 1)

    def test_42_all_master_screens_still_work(self):
        self.assertGreater(len(CompanyDAO.get_all()), 0)
        self.assertGreater(len(UnitDAO.get_all()), 0)
        self.assertGreater(len(DrugDAO.get_all()), 0)
        self.assertGreater(len(SupplierDAO.get_all()), 0)
        self.assertGreater(len(CustomerDAO.get_all()), 0)
        self.assertGreater(len(DoctorDAO.get_all()), 0)
        self.assertGreater(len(ItemDAO.get_all()), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
