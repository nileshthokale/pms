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
    SOURCE_CUSTOMER_RECEIPT,
    PostingEngine,
    posting_engine,
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

    _DB_PATH = os.path.join(os.path.dirname(__file__), "_test_posting.db")

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

        self.customer_ledger_id = CustomerDAO.get_ledger_id(self.customer_id)
        self.cash_ledger = LedgerDAO.get_by_system_role(ROLE_CASH)
        self.bank_ledger = LedgerDAO.get_by_system_role(ROLE_BANK)
        self.engine = posting_engine

    # ── helpers ──────────────────────────────────────────────────────
    def _insert_receipt(self, amount=500.0, mode="Cash", customer_id=None,
                        date="2026-01-20", ref=""):
        return CustomerReceiptDAO.insert_receipt({
            "receipt_date": date, "receipt_time": "10:00",
            "customer_id": customer_id or self.customer_id,
            "receipt_mode": mode, "amount": amount,
            "reference_no": ref, "remarks": "",
        })

    def _nets(self, receipt_id):
        """Per-ledger net (debit-credit) of all rows for a receipt."""
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT ledger_id, SUM(debit) - SUM(credit) AS net "
                "FROM ledger_transactions "
                "WHERE reference_type = ? AND reference_id = ? "
                "GROUP BY ledger_id",
                (SOURCE_CUSTOMER_RECEIPT, receipt_id),
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
        batches = StockDAO.get_stock_batches_for_item(self.item_id)
        return batches[0]["id"]


# ======================================================================
# 1-11: Cash receipt posting
# ======================================================================

class TestCashReceiptPosting(_BaseTest):

    def test_01_customer_has_linked_ledger(self):
        self.assertIsNotNone(self.customer_ledger_id)
        ledger = LedgerDAO.get_ledger_by_id(self.customer_ledger_id)
        self.assertEqual(ledger["ledger_name"], "Customer - TestCustomer")
        self.assertEqual(
            CustomerDAO.get_customer_by_ledger(self.customer_ledger_id)["id"],
            self.customer_id,
        )

    def test_02_cash_system_ledger_exists(self):
        self.assertIsNotNone(self.cash_ledger)
        self.assertEqual(self.cash_ledger["system_role"], "CASH")
        self.assertEqual(self.cash_ledger["ledger_name"], "Cash")

    def test_03_bank_system_ledger_exists(self):
        self.assertIsNotNone(self.bank_ledger)
        self.assertEqual(self.bank_ledger["system_role"], "BANK")
        self.assertEqual(self.bank_ledger["ledger_name"], "Bank")

    def test_04_create_valid_cash_receipt(self):
        rid = self._insert_receipt(amount=500.0, mode="Cash")
        self.assertGreater(rid, 0)
        self.assertIsNotNone(CustomerReceiptDAO.get_by_id(rid))

    def test_05_exactly_two_posting_rows(self):
        rid = self._insert_receipt()
        rows = self.engine.get_posting_rows(SOURCE_CUSTOMER_RECEIPT, rid)
        self.assertEqual(len(rows), 2)

    def test_06_cash_ledger_debited(self):
        rid = self._insert_receipt(amount=500.0)
        rows = self.engine.get_posting_rows(SOURCE_CUSTOMER_RECEIPT, rid)
        cash_rows = [r for r in rows if r["ledger_id"] == self.cash_ledger["id"]]
        self.assertEqual(len(cash_rows), 1)
        self.assertEqual(cash_rows[0]["debit"], 500.0)
        self.assertEqual(cash_rows[0]["credit"], 0.0)

    def test_07_customer_ledger_credited(self):
        rid = self._insert_receipt(amount=500.0)
        rows = self.engine.get_posting_rows(SOURCE_CUSTOMER_RECEIPT, rid)
        cust_rows = [
            r for r in rows if r["ledger_id"] == self.customer_ledger_id
        ]
        self.assertEqual(len(cust_rows), 1)
        self.assertEqual(cust_rows[0]["debit"], 0.0)
        self.assertEqual(cust_rows[0]["credit"], 500.0)

    def test_08_amount_equality_debit_equals_credit(self):
        rid = self._insert_receipt(amount=321.45)
        rows = self.engine.get_posting_rows(SOURCE_CUSTOMER_RECEIPT, rid)
        total_debit = sum(r["debit"] for r in rows)
        total_credit = sum(r["credit"] for r in rows)
        self.assertEqual(total_debit, 321.45)
        self.assertEqual(total_credit, 321.45)

    def test_09_reference_type_set(self):
        rid = self._insert_receipt()
        rows = self.engine.get_posting_rows(SOURCE_CUSTOMER_RECEIPT, rid)
        for r in rows:
            self.assertEqual(r["reference_type"], "CUSTOMER_RECEIPT")

    def test_10_reference_id_set(self):
        rid = self._insert_receipt()
        rows = self.engine.get_posting_rows(SOURCE_CUSTOMER_RECEIPT, rid)
        for r in rows:
            self.assertEqual(r["reference_id"], rid)

    def test_11_voucher_number_set(self):
        rid = self._insert_receipt()
        voucher_no = CustomerReceiptDAO.get_by_id(rid)["voucher_no"]
        rows = self.engine.get_posting_rows(SOURCE_CUSTOMER_RECEIPT, rid)
        for r in rows:
            self.assertEqual(r["voucher_no"], voucher_no)
            self.assertEqual(r["voucher_type"], "Customer Receipt")


# ======================================================================
# 12-17: Payment mode mapping
# ======================================================================

class TestPaymentModes(_BaseTest):

    def _assert_single_debit(self, rid, ledger_id, amount):
        rows = self.engine.get_posting_rows(SOURCE_CUSTOMER_RECEIPT, rid)
        self.assertEqual(len(rows), 2)
        target = [r for r in rows if r["ledger_id"] == ledger_id]
        self.assertEqual(len(target), 1)
        self.assertEqual(target[0]["debit"], amount)
        self.assertEqual(target[0]["credit"], 0.0)

    def test_12_create_bank_receipt(self):
        rid = self._insert_receipt(amount=800.0, mode="Bank", ref="NEFT-1")
        self.assertGreater(rid, 0)

    def test_13_bank_receipt_debits_bank(self):
        rid = self._insert_receipt(amount=800.0, mode="Bank")
        self._assert_single_debit(rid, self.bank_ledger["id"], 800.0)

    def test_14_create_cheque_receipt(self):
        rid = self._insert_receipt(amount=250.0, mode="Cheque", ref="CHQ-9")
        self.assertGreater(rid, 0)

    def test_15_cheque_receipt_debits_bank(self):
        rid = self._insert_receipt(amount=250.0, mode="Cheque")
        self._assert_single_debit(rid, self.bank_ledger["id"], 250.0)

    def test_16_create_upi_receipt(self):
        rid = self._insert_receipt(amount=90.0, mode="UPI", ref="UPI-77")
        self.assertGreater(rid, 0)

    def test_17_upi_receipt_debits_bank(self):
        rid = self._insert_receipt(amount=90.0, mode="UPI")
        self._assert_single_debit(rid, self.bank_ledger["id"], 90.0)


# ======================================================================
# 18-22: Idempotency and reversal
# ======================================================================

class TestDuplicateAndReverse(_BaseTest):

    def test_18_duplicate_posting_refused(self):
        rid = self._insert_receipt(amount=500.0)
        with self.assertRaises(Exception) as ctx:
            self.engine.post_customer_receipt(rid)
        self.assertIn("already has an active", str(ctx.exception))

    def test_19_no_duplicate_ledger_effect(self):
        rid = self._insert_receipt(amount=500.0)
        before = LedgerDAO.get_balance(self.cash_ledger["id"])
        try:
            self.engine.post_customer_receipt(rid)
        except Exception:
            pass  # expected refusal
        rows = self.engine.get_posting_rows(SOURCE_CUSTOMER_RECEIPT, rid)
        self.assertEqual(len(rows), 2)
        after = LedgerDAO.get_balance(self.cash_ledger["id"])
        self.assertEqual(before["total_debit"], after["total_debit"])
        self.assertTrue(self.engine.is_posted(
            SOURCE_CUSTOMER_RECEIPT, rid
        ))

    def test_20_reverse_receipt(self):
        rid = self._insert_receipt(amount=500.0)
        new_ids = self.engine.reverse(SOURCE_CUSTOMER_RECEIPT, rid)
        self.assertEqual(len(new_ids), 2)
        self.assertTrue(all(i > 0 for i in new_ids))

    def test_21_mirrored_reversal_rows(self):
        rid = self._insert_receipt(amount=500.0)
        self.engine.reverse(SOURCE_CUSTOMER_RECEIPT, rid)
        rows = self.engine.get_posting_rows(SOURCE_CUSTOMER_RECEIPT, rid)
        self.assertEqual(len(rows), 4)

        rev_cash = [
            r for r in rows
            if r["ledger_id"] == self.cash_ledger["id"]
            and r["voucher_type"] == "Customer Receipt Reversal"
        ]
        self.assertEqual(len(rev_cash), 1)
        self.assertEqual(rev_cash[0]["credit"], 500.0)
        self.assertEqual(rev_cash[0]["debit"], 0.0)
        self.assertIn("REVERSAL:", rev_cash[0]["description"])
        # identity preserved on reversal rows
        self.assertEqual(rev_cash[0]["reference_id"], rid)
        self.assertEqual(rev_cash[0]["reference_type"],
                         SOURCE_CUSTOMER_RECEIPT)

        rev_cust = [
            r for r in rows
            if r["ledger_id"] == self.customer_ledger_id
            and r["voucher_type"] == "Customer Receipt Reversal"
        ]
        self.assertEqual(len(rev_cust), 1)
        self.assertEqual(rev_cust[0]["debit"], 500.0)
        self.assertEqual(rev_cust[0]["credit"], 0.0)

        # reversing an already-reversed posting is a safe no-op
        self.assertEqual(
            self.engine.reverse(SOURCE_CUSTOMER_RECEIPT, rid), []
        )

    def test_22_net_effect_zero_after_reversal(self):
        rid = self._insert_receipt(amount=500.0)
        self.engine.reverse(SOURCE_CUSTOMER_RECEIPT, rid)
        nets = self._nets(rid)
        for ledger_id, net in nets.items():
            self.assertEqual(net, 0.0, f"ledger {ledger_id} not zero")
        self.assertFalse(self.engine.is_posted(
            SOURCE_CUSTOMER_RECEIPT, rid
        ))
        # reversing an unknown source type is refused
        with self.assertRaises(Exception):
            self.engine.reverse("UNKNOWN_SOURCE", rid)


# ======================================================================
# 23-27: Edit / repost and delete
# ======================================================================

class TestEditAndDelete(_BaseTest):

    def test_23_edit_receipt(self):
        rid = self._insert_receipt(amount=100.0)
        CustomerReceiptDAO.update_receipt(rid, {
            "receipt_date": "2026-01-21", "receipt_time": "11:00",
            "customer_id": self.customer_id, "receipt_mode": "Bank",
            "amount": 250.0, "reference_no": "NEW", "remarks": "edited",
        })
        rec = CustomerReceiptDAO.get_by_id(rid)
        self.assertEqual(rec["amount"], 250.0)
        self.assertEqual(rec["receipt_mode"], "Bank")

    def test_24_old_posting_reversed_on_edit(self):
        rid = self._insert_receipt(amount=100.0)
        CustomerReceiptDAO.update_receipt(rid, {
            "receipt_date": "2026-01-21", "receipt_time": "11:00",
            "customer_id": self.customer_id, "receipt_mode": "Cash",
            "amount": 250.0, "reference_no": "", "remarks": "",
        })
        rows = self.engine.get_posting_rows(SOURCE_CUSTOMER_RECEIPT, rid)
        reversals = [
            r for r in rows
            if r["voucher_type"] == "Customer Receipt Reversal"
        ]
        self.assertEqual(len(reversals), 2)
        reversal_amounts = {r["debit"] or r["credit"] for r in reversals}
        self.assertEqual(reversal_amounts, {100.0})

    def test_25_new_amount_posted_on_edit(self):
        rid = self._insert_receipt(amount=100.0)
        CustomerReceiptDAO.update_receipt(rid, {
            "receipt_date": "2026-01-21", "receipt_time": "11:00",
            "customer_id": self.customer_id, "receipt_mode": "Bank",
            "amount": 250.0, "reference_no": "", "remarks": "",
        })
        # Net effect must equal the NEW amount on the correct ledgers
        nets = self._nets(rid)
        self.assertEqual(nets[self.bank_ledger["id"]], 250.0)
        self.assertEqual(nets[self.customer_ledger_id], -250.0)
        # Old Cash leg fully reversed (original debit + reversal = 0)
        self.assertEqual(nets.get(self.cash_ledger["id"], 0.0), 0.0)
        self.assertTrue(self.engine.is_posted(SOURCE_CUSTOMER_RECEIPT, rid))

    def test_26_delete_receipt(self):
        rid = self._insert_receipt(amount=400.0)
        CustomerReceiptDAO.delete_receipt(rid)
        self.assertIsNone(CustomerReceiptDAO.get_by_id(rid))

    def test_27_delete_reverses_accounting_effect(self):
        rid = self._insert_receipt(amount=400.0)
        CustomerReceiptDAO.delete_receipt(rid)
        nets = self._nets(rid)
        for ledger_id, net in nets.items():
            self.assertEqual(net, 0.0, f"ledger {ledger_id} not zero")
        self.assertFalse(self.engine.is_posted(SOURCE_CUSTOMER_RECEIPT, rid))
        rows = self.engine.get_posting_rows(SOURCE_CUSTOMER_RECEIPT, rid)
        self.assertEqual(len(rows), 4)  # 2 original + 2 reversal, kept


# ======================================================================
# 28-33: Failure safety
# ======================================================================

class TestFailureSafety(_BaseTest):

    def test_28_missing_customer_ledger_fails_safely(self):
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE customers SET ledger_id = NULL WHERE id = ?",
                (self.customer_id,),
            )
            conn.commit()
        finally:
            conn.close()

        with self.assertRaises(Exception) as ctx:
            self._insert_receipt(amount=100.0)
        self.assertIn("no linked Account Ledger", str(ctx.exception))

        # Source receipt was rolled back — nothing saved, nothing posted
        conn = get_connection()
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM customer_receipts"
            ).fetchone()[0]
            txn_count = conn.execute(
                "SELECT COUNT(*) FROM ledger_transactions"
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(count, 0)
        self.assertEqual(txn_count, 0)

    def test_29_missing_system_ledger_fails_safely(self):
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE account_ledgers SET system_role = NULL "
                "WHERE system_role = ?",
                (ROLE_CASH,),
            )
            conn.commit()
        finally:
            conn.close()

        with self.assertRaises(Exception) as ctx:
            self._insert_receipt(amount=100.0, mode="Cash")
        self.assertIn("not configured", str(ctx.exception))

        conn = get_connection()
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM customer_receipts"
            ).fetchone()[0]
            txn_count = conn.execute(
                "SELECT COUNT(*) FROM ledger_transactions"
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(count, 0)
        self.assertEqual(txn_count, 0)

        # Bank mode still works with CASH unconfigured
        rid = self._insert_receipt(amount=100.0, mode="Bank")
        self.assertGreater(rid, 0)

    def test_30_invalid_receipt_amount_fails_safely(self):
        # DAO-level validation (pre-existing)
        with self.assertRaises(ValueError):
            self._insert_receipt(amount=0.0)
        with self.assertRaises(ValueError):
            self._insert_receipt(amount=-50.0)

        # Engine-level: a raw zero-amount receipt row cannot be posted
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("BEGIN")
            cur.execute(
                "INSERT INTO customer_receipts "
                "(voucher_no, receipt_date, receipt_time, customer_id, "
                "receipt_mode, amount, reference_no, remarks) "
                "VALUES ('CR-0099', '2026-01-20', '10:00', ?, 'Cash', "
                "0, '', '')",
                (self.customer_id,),
            )
            rid = cur.lastrowid
            conn.commit()
        finally:
            conn.close()

        with self.assertRaises(Exception) as ctx:
            self.engine.post_customer_receipt(rid)
        self.assertIn("greater than 0", str(ctx.exception))
        self.assertEqual(
            len(self.engine.get_posting_rows(SOURCE_CUSTOMER_RECEIPT, rid)),
            0,
        )

    def test_31_unsupported_payment_mode_fails_safely(self):
        # DAO path: receipt saved attempt rolls back completely
        with self.assertRaises(Exception) as ctx:
            self._insert_receipt(amount=100.0, mode="Bitcoin")
        self.assertIn("unsupported payment mode", str(ctx.exception))

        conn = get_connection()
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM customer_receipts"
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(count, 0)

        # Engine path: raw receipt row with bad mode refuses to post
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("BEGIN")
            cur.execute(
                "INSERT INTO customer_receipts "
                "(voucher_no, receipt_date, receipt_time, customer_id, "
                "receipt_mode, amount, reference_no, remarks) "
                "VALUES ('CR-0098', '2026-01-20', '10:00', ?, 'Barter', "
                "100, '', '')",
                (self.customer_id,),
            )
            rid = cur.lastrowid
            conn.commit()
        finally:
            conn.close()

        with self.assertRaises(Exception):
            self.engine.post_customer_receipt(rid)
        self.assertEqual(
            len(self.engine.get_posting_rows(SOURCE_CUSTOMER_RECEIPT, rid)),
            0,
        )

    def test_32_failure_during_posting_rolls_back_everything(self):
        # Post succeeds once, then break the customer link and edit:
        # the UPDATE must roll back together with the failed re-post.
        rid = self._insert_receipt(amount=100.0)

        conn = get_connection()
        try:
            conn.execute(
                "UPDATE customers SET ledger_id = NULL WHERE id = ?",
                (self.customer_id,),
            )
            conn.commit()
        finally:
            conn.close()

        with self.assertRaises(Exception):
            CustomerReceiptDAO.update_receipt(rid, {
                "receipt_date": "2026-01-21", "receipt_time": "11:00",
                "customer_id": self.customer_id, "receipt_mode": "Cash",
                "amount": 250.0, "reference_no": "", "remarks": "",
            })

        # Source edit rolled back: old values intact
        rec = CustomerReceiptDAO.get_by_id(rid)
        self.assertEqual(rec["amount"], 100.0)
        self.assertEqual(rec["receipt_date"], "2026-01-20")

    def test_33_failure_after_source_update_rolls_back_everything(self):
        rid = self._insert_receipt(amount=100.0)

        conn = get_connection()
        try:
            conn.execute(
                "UPDATE customers SET ledger_id = NULL WHERE id = ?",
                (self.customer_id,),
            )
            conn.commit()
        finally:
            conn.close()

        with self.assertRaises(Exception):
            CustomerReceiptDAO.update_receipt(rid, {
                "receipt_date": "2026-01-21", "receipt_time": "11:00",
                "customer_id": self.customer_id, "receipt_mode": "Cash",
                "amount": 250.0, "reference_no": "", "remarks": "",
            })

        # Old posting untouched: still exactly the 2 original rows,
        # no reversal rows, still active.
        rows = self.engine.get_posting_rows(SOURCE_CUSTOMER_RECEIPT, rid)
        self.assertEqual(len(rows), 2)
        reversals = [
            r for r in rows
            if r["voucher_type"] == "Customer Receipt Reversal"
        ]
        self.assertEqual(len(reversals), 0)
        self.assertTrue(self.engine.is_posted(SOURCE_CUSTOMER_RECEIPT, rid))


# ======================================================================
# 34-35: Persistence and ledger visibility
# ======================================================================

class TestPersistenceAndLedger(_BaseTest):

    def test_34_restart_and_verify_persistence(self):
        rid = self._insert_receipt(amount=555.0, mode="Cheque", ref="CHQ-1")

        # Simulate application restart: brand-new connection object
        # reading committed state only.
        from database.connection import get_db_path
        import sqlite3 as _sqlite3
        fresh = _sqlite3.connect(get_db_path())
        fresh.row_factory = _sqlite3.Row
        try:
            rows = fresh.execute(
                "SELECT * FROM ledger_transactions "
                "WHERE reference_type = ? AND reference_id = ?",
                (SOURCE_CUSTOMER_RECEIPT, rid),
            ).fetchall()
        finally:
            fresh.close()

        self.assertEqual(len(rows), 2)
        debits = [r["debit"] for r in rows]
        credits = [r["credit"] for r in rows]
        self.assertIn(555.0, debits)
        self.assertIn(555.0, credits)

        # Engine state also survives (fresh DAO/engine reads)
        self.assertTrue(
            PostingEngine().is_posted(SOURCE_CUSTOMER_RECEIPT, rid)
        )

    def test_35_account_ledger_displays_receipt_entries(self):
        rid = self._insert_receipt(amount=500.0, ref="CASH-1")

        # The Account Ledger screen reads LedgerDAO.get_transactions()
        cash_txns = LedgerDAO.get_transactions(self.cash_ledger["id"])
        self.assertEqual(len(cash_txns), 1)
        self.assertEqual(cash_txns[0]["voucher_type"], "Customer Receipt")
        self.assertEqual(cash_txns[0]["debit"], 500.0)
        self.assertIn("TestCustomer", cash_txns[0]["description"])

        cust_txns = LedgerDAO.get_transactions(self.customer_ledger_id)
        self.assertEqual(len(cust_txns), 1)
        self.assertEqual(cust_txns[0]["credit"], 500.0)

        # Ledger balance reflects the receipt: customer owes 500 less
        bal = LedgerDAO.get_balance(self.customer_ledger_id)
        self.assertEqual(bal["total_credit"], 500.0)
        self.assertEqual(bal["closing_balance"], 500.0)
        self.assertEqual(bal["closing_balance_type"], "Credit")

        cash_bal = LedgerDAO.get_balance(self.cash_ledger["id"])
        self.assertEqual(cash_bal["total_debit"], 500.0)
        self.assertEqual(cash_bal["closing_balance_type"], "Debit")


# ======================================================================
# 36-44: Regression — all existing modules still work
# ======================================================================

class TestRegression(_BaseTest):

    def test_36_customer_receipt_functionality_still_works(self):
        rid = self._insert_receipt(amount=200.0)
        rec = CustomerReceiptDAO.get_by_id(rid)
        self.assertEqual(rec["voucher_no"], "CR-0001")
        self.assertEqual(rec["customer_name"], "TestCustomer")

        all_recs = CustomerReceiptDAO.get_all()
        self.assertEqual(len(all_recs), 1)

        filtered = CustomerReceiptDAO.get_all_filtered(
            date_from="2026-01-01", date_to="2026-01-31"
        )
        self.assertEqual(len(filtered), 1)

        # Legacy balance method still available and consistent
        balance = CustomerReceiptDAO.get_customer_balance(self.customer_id)
        self.assertEqual(balance, -200.0)

    def test_37_supplier_payment_still_works(self):
        pay_id = SupplierPaymentDAO.insert_payment({
            "payment_date": "2026-01-20", "payment_time": "10:00",
            "supplier_id": self.supplier_id, "payment_mode": "Cash",
            "amount": 500, "reference_no": "", "remarks": "",
        })
        self.assertGreater(pay_id, 0)
        # Supplier payments are now posted (Phase 2D)
        rows = self.engine.get_posting_rows("SUPPLIER_PAYMENT", pay_id)
        self.assertEqual(len(rows), 2)

    def test_38_purchase_still_works(self):
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
        batches = PurchaseDAO.get_stock_batches_for_item(self.item_id)
        self.assertEqual(len(batches), 1)
        self.assertEqual(batches[0]["stock_qty"], 100.0)
        # Purchase invoice IS posted (Phase 2F)
        rows = self.engine.get_posting_rows("PURCHASE_INVOICE", inv_id)
        self.assertEqual(len(rows), 2)

    def test_39_counter_sale_still_works(self):
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
        batches = StockDAO.get_stock_batches_for_item(self.item_id)
        self.assertEqual(batches[0]["stock_qty"], 95.0)
        # Sales ARE posted since Phase 2E (COUNTER_SALE identity);
        # fully-paid Cash sale with customer -> Debit CASH / Credit SALES
        from database.accounting_posting import SOURCE_COUNTER_SALE
        rows = self.engine.get_posting_rows(SOURCE_COUNTER_SALE, sale_id)
        self.assertEqual(len(rows), 2)
        self.assertTrue(
            self.engine.is_posted(SOURCE_COUNTER_SALE, sale_id)
        )

    def test_40_credit_note_still_works(self):
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

    def test_41_debit_note_still_works(self):
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

    def test_42_journal_entry_still_works(self):
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

    def test_43_stock_master_still_works(self):
        self._seed_stock()
        all_stock = StockDAO.get_all()
        self.assertEqual(len(all_stock), 1)
        self.assertEqual(all_stock[0]["item_name"], "TestItem")
        self.assertEqual(all_stock[0]["stock_qty"], 100.0)

    def test_44_all_master_screens_still_work(self):
        self.assertGreater(len(CompanyDAO.get_all()), 0)
        self.assertGreater(len(UnitDAO.get_all()), 0)
        self.assertGreater(len(DrugDAO.get_all()), 0)
        self.assertGreater(len(SupplierDAO.get_all()), 0)
        self.assertGreater(len(CustomerDAO.get_all()), 0)
        self.assertGreater(len(DoctorDAO.get_all()), 0)
        self.assertGreater(len(ItemDAO.get_all()), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
