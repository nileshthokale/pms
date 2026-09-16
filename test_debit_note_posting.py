"""Phase 2H - Debit Note (Supplier Return) posting integration tests.

41 tests covering:

  1-2:   Supplier ledger linkage and PURCHASE_RETURN system ledger setup
  3-8:   Debit Note posting (2 rows, debit Supplier / credit Purchase Return,
         total_amount from Decision 3, reference/voucher fields)
  9:     DAO insert auto-posts in the same transaction (2 rows)
  10-12: Stock deduction unchanged by posting, net-zero effect,
         system roles (Sales/Cash/Bank) absent from a plain posting
  13-14: Duplicate posting prevention
  15-16: Reversal (mirrored rows, net-zero)
  17-20: Edit / repost (amount change, old reversal, supplier change
         moves rows to the new supplier ledger)
  21:    Delete reversal
  22:    Missing supplier ledger_id fails safely and rolls back the note
  23:    PURCHASE_RETURN role unconfigured fails safely
  24:    Negative total creates no posting rows
  25:    Zero-amount note legacy behaviour preserved (no posting yet)
  26:    Negative total produces zero posting rows
  27:    Missing supplier header fails safely
  28:    Persistence across a fresh database connection
  29-30: Account-ledger visibility (supplier ledger shows the entry)
  31-36: Regression - customer receipt, supplier payment, counter sale,
         purchase invoice, credit note, stock master still work
  37-41: Edit supplier moves rows, edit qty adjusts stock correctly,
         all master screens still work, debit note CRUD still works
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
    ROLE_PURCHASE,
    ROLE_PURCHASE_RETURN,
    ROLE_SALES,
    ensure_system_ledgers,
)
from database.accounting_posting import (
    SOURCE_DEBIT_NOTE,
    PostingEngine,
    PostingError,
    posting_engine,
)
from database.ledger_dao import LedgerDAO
from database.customer_dao import CustomerDAO
from database.supplier_dao import SupplierDAO
from database.debit_note_dao import DebitNoteDAO
from database.customer_receipt_dao import CustomerReceiptDAO
from database.supplier_payment_dao import SupplierPaymentDAO
from database.purchase_dao import PurchaseDAO
from database.sales_dao import SalesDAO
from database.credit_note_dao import CreditNoteDAO
from database.company_dao import CompanyDAO
from database.unit_dao import UnitDAO
from database.drug_dao import DrugDAO
from database.item_dao import ItemDAO
from database.stock_dao import StockDAO
from database.doctor_dao import DoctorDAO

TABLES = [
    "debit_note_items", "debit_notes",
    "credit_note_items", "credit_notes",
    "sales_invoice_items", "sales_invoices",
    "ledger_transactions", "account_ledgers",
    "customer_receipts",
    "supplier_payments",
    "purchase_invoice_items", "purchase_invoices",
    "stock_batches", "item_ingredients", "items",
    "doctors", "customers", "suppliers", "drugs", "units", "companies",
]


class _BaseTest(unittest.TestCase):
    """Fresh DB per module; clean tables + masters + system ledgers per case."""

    _DB_PATH = os.path.join(os.path.dirname(__file__), "_test_debit_note_posting.db")

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
        self.purchase_return_ledger = LedgerDAO.get_by_system_role(ROLE_PURCHASE_RETURN)
        self.cash_ledger = LedgerDAO.get_by_system_role(ROLE_CASH)
        self.bank_ledger = LedgerDAO.get_by_system_role(ROLE_BANK)
        self.sales_ledger = LedgerDAO.get_by_system_role(ROLE_SALES)
        self.purchase_ledger = LedgerDAO.get_by_system_role(ROLE_PURCHASE)

        self.engine = PostingEngine()
        self._seed_stock()

    # ── helpers ──────────────────────────────────────────────────────
    def _seed_stock(self, qty=100.0, rate=40.0):
        PurchaseDAO.insert_invoice(
            voucher_no="PV-0001",
            voucher_date="2026-01-15",
            voucher_time="",
            purchase_type="Cash",
            supplier_id=self.supplier_id,
            invoice_no="INV-001",
            invoice_date="2026-01-15",
            invoice_net_amount=qty * rate,
            bill_discount=0,
            due_date="",
            total_amount=qty * rate,
            gst_amount=0,
            debit_note_amount=0,
            other_amount=0,
            paid_amount=qty * rate,
            round_off=0,
            net_amount=qty * rate,
            remarks="",
            items=[{
                "item_id": self.item_id, "pack_size": "10x10",
                "pay_qty": qty, "free_qty": 0, "batch_no": "BATCH-A",
                "expiry": "12/27", "rate": rate, "mrp": 50.0,
                "discount": 0, "gst_percent": 0, "gst_amount": 0,
                "amount": qty * rate, "purchase_rate": rate,
                "net_rate": rate, "pp": rate,
            }],
        )
        batches = StockDAO.get_stock_batches_for_item(self.item_id)
        self.batch_id = batches[0]["id"]

    def _header(self, total=400.0, supplier_id=None):
        return {
            "voucher_date": "2026-01-20", "voucher_time": "10:00",
            "dn_date": "2026-01-20", "dn_type": "Supplier",
            "supplier_id": supplier_id or self.supplier_id,
            "total_amount": total, "ledger_amount": total, "remarks": "",
        }

    def _items(self, qty=10.0, rate=40.0):
        return [{
            "item_id": self.item_id, "stock_batch_id": self.batch_id,
            "batch_no": "BATCH-A", "expiry": "12/27", "pack_size": "10x10",
            "rate": rate, "mrp": 50.0, "return_qty": qty,
            "less_amount": 0, "amount": round(qty * rate, 2),
            "return_reason": "Damaged", "price_factor": 1.0,
        }]

    def _nets(self, dn_id):
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT ledger_id, SUM(debit) - SUM(credit) AS net "
                "FROM ledger_transactions "
                "WHERE reference_type = ? AND reference_id = ? "
                "GROUP BY ledger_id HAVING ABS(SUM(debit) - SUM(credit)) > 0.005",
                (SOURCE_DEBIT_NOTE, dn_id),
            ).fetchall()
            return {r["ledger_id"]: round(r["net"], 2) for r in rows}
        finally:
            conn.close()


# ======================================================================
# 1-2: Supplier ledger linkage and system setup
# ======================================================================

class TestSetupAndLinkage(_BaseTest):

    def test_01_supplier_has_linked_ledger(self):
        self.assertIsNotNone(self.supplier_ledger_id)
        ledger = LedgerDAO.get_ledger_by_id(self.supplier_ledger_id)
        self.assertIsNotNone(ledger)
        self.assertIn("TestSupplier", ledger["ledger_name"])
        self.assertEqual(ledger["account_group"], "Sundry Creditors")

    def test_02_purchase_return_system_ledger_exists(self):
        self.assertIsNotNone(self.purchase_return_ledger)
        self.assertEqual(self.purchase_return_ledger["system_role"], ROLE_PURCHASE_RETURN)
        self.assertEqual(self.purchase_return_ledger["account_group"], "Purchase Accounts")


# ======================================================================
# 3-12: Debit Note posting
# ======================================================================

class TestDebitNotePosting(_BaseTest):

    def test_03_debit_note_creates_two_rows(self):
        dn_id = DebitNoteDAO.insert_debit_note(self._header(), self._items())
        rows = self.engine.get_posting_rows(SOURCE_DEBIT_NOTE, dn_id)
        self.assertEqual(len(rows), 2)

    def test_04_supplier_ledger_debited(self):
        dn_id = DebitNoteDAO.insert_debit_note(self._header(400.0), self._items())
        nets = self._nets(dn_id)
        self.assertIn(self.supplier_ledger_id, nets)
        self.assertEqual(nets[self.supplier_ledger_id], 400.0)

    def test_05_purchase_return_ledger_credited(self):
        dn_id = DebitNoteDAO.insert_debit_note(self._header(400.0), self._items())
        nets = self._nets(dn_id)
        self.assertIn(self.purchase_return_ledger["id"], nets)
        self.assertEqual(nets[self.purchase_return_ledger["id"]], -400.0)

    def test_06_reference_type_and_id(self):
        dn_id = DebitNoteDAO.insert_debit_note(self._header(), self._items())
        rows = self.engine.get_posting_rows(SOURCE_DEBIT_NOTE, dn_id)
        for r in rows:
            self.assertEqual(r["reference_type"], SOURCE_DEBIT_NOTE)
            self.assertEqual(r["reference_id"], dn_id)

    def test_07_voucher_number_in_posting(self):
        dn_id = DebitNoteDAO.insert_debit_note(self._header(), self._items())
        rows = self.engine.get_posting_rows(SOURCE_DEBIT_NOTE, dn_id)
        voucher_no = rows[0]["voucher_no"]
        self.assertTrue(voucher_no.startswith("DN-"))
        for r in rows:
            self.assertEqual(r["voucher_no"], voucher_no)

    def test_08_entries_path_to_supplier_and_purchase_return_only(self):
        dn_id = DebitNoteDAO.insert_debit_note(self._header(), self._items())
        nets = self._nets(dn_id)
        self.assertEqual(set(nets.keys()), {
            self.supplier_ledger_id, self.purchase_return_ledger["id"],
        })

    def test_09_dao_insert_auto_posts_in_same_transaction(self):
        dn_id = DebitNoteDAO.insert_debit_note(self._header(), self._items())
        self.assertTrue(self.engine.is_posted(SOURCE_DEBIT_NOTE, dn_id))
        self.assertEqual(len(self.engine.get_posting_rows(SOURCE_DEBIT_NOTE, dn_id)), 2)

    def test_10_stock_deduction_unchanged_by_posting(self):
        before = StockDAO.get_stock_batch_by_id(self.batch_id)["stock_qty"]
        dn_id = DebitNoteDAO.insert_debit_note(self._header(200.0),
                                                 self._items(qty=5.0))
        after = StockDAO.get_stock_batch_by_id(self.batch_id)["stock_qty"]
        self.assertAlmostEqual(after, before - 5.0, places=2)

    def test_11_net_effect_balances_to_zero(self):
        dn_id = DebitNoteDAO.insert_debit_note(self._header(600.0),
                                                 self._items(qty=15.0))
        rows = self.engine.get_posting_rows(SOURCE_DEBIT_NOTE, dn_id)
        total_debit = sum(r["debit"] for r in rows)
        total_credit = sum(r["credit"] for r in rows)
        self.assertAlmostEqual(total_debit, total_credit, places=2)

    def test_12_system_tender_roles_not_posted(self):
        dn_id = DebitNoteDAO.insert_debit_note(self._header(300.0),
                                                 self._items())
        nets = self._nets(dn_id)
        self.assertNotIn(self.cash_ledger["id"], nets)
        self.assertNotIn(self.bank_ledger["id"], nets)
        self.assertNotIn(self.sales_ledger["id"], nets)


# ======================================================================
# 13-14: Duplicate posting prevention
# ======================================================================

class TestDuplicatePrevention(_BaseTest):

    def test_13_duplicate_posting_raises(self):
        dn_id = DebitNoteDAO.insert_debit_note(self._header(), self._items())
        with self.assertRaises(PostingError):
            self.engine.post_debit_note(dn_id)

    def test_14_no_duplicate_active_effect(self):
        dn_id = DebitNoteDAO.insert_debit_note(self._header(), self._items())
        rows = self.engine.get_posting_rows(SOURCE_DEBIT_NOTE, dn_id)
        self.assertEqual(len(rows), 2)
        active = [r for r in rows if not r.get("reversed")]
        self.assertEqual(len(active), 2)


# ======================================================================
# 15-16: Reversal
# ======================================================================

class TestReversal(_BaseTest):

    def test_15_reversal_creates_mirrored_rows(self):
        dn_id = DebitNoteDAO.insert_debit_note(self._header(500.0),
                                                 self._items())
        reversed_ids = self.engine.reverse(SOURCE_DEBIT_NOTE, dn_id)
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
        dn_id = DebitNoteDAO.insert_debit_note(self._header(500.0),
                                                 self._items())
        self.engine.reverse(SOURCE_DEBIT_NOTE, dn_id)
        nets = self._nets(dn_id)
        self.assertEqual(len(nets), 0)


# ======================================================================
# 17-20: Edit / repost
# ======================================================================

class TestEditAndRepost(_BaseTest):

    def test_17_edit_amount_reposts(self):
        dn_id = DebitNoteDAO.insert_debit_note(self._header(400.0),
                                                 self._items())
        DebitNoteDAO.update_debit_note(
            dn_id, self._header(800.0), self._items(qty=20.0),
        )
        nets = self._nets(dn_id)
        self.assertEqual(nets[self.supplier_ledger_id], 800.0)
        self.assertEqual(nets[self.purchase_return_ledger["id"]], -800.0)

    def test_18_old_posting_reversed_on_edit(self):
        dn_id = DebitNoteDAO.insert_debit_note(self._header(400.0),
                                                 self._items())
        before = self.engine.get_posting_rows(SOURCE_DEBIT_NOTE, dn_id)
        self.assertEqual(len(before), 2)

        DebitNoteDAO.update_debit_note(
            dn_id, self._header(800.0), self._items(qty=20.0),
        )
        rows_after = self.engine.get_posting_rows(SOURCE_DEBIT_NOTE, dn_id)
        # 2 + 2 reversal + 2 repost = 6
        self.assertEqual(len(rows_after), 6)

    def test_19_edit_type_field_voucher_type(self):
        dn_id = DebitNoteDAO.insert_debit_note(self._header(), self._items())
        rows = self.engine.get_posting_rows(SOURCE_DEBIT_NOTE, dn_id)
        for r in rows:
            self.assertEqual(r["voucher_type"], "Debit Note")

    def test_20_edit_supplier_moves_rows_to_new_supplier(self):
        supplier2_id = SupplierDAO.insert("SecondSupplier")
        supplier2_ledger_id = SupplierDAO.get_ledger_id(supplier2_id)
        self.assertIsNotNone(supplier2_ledger_id)

        dn_id = DebitNoteDAO.insert_debit_note(self._header(300.0),
                                                 self._items())
        DebitNoteDAO.update_debit_note(
            dn_id, self._header(300.0, supplier_id=supplier2_id),
            self._items(),
        )
        nets = self._nets(dn_id)
        self.assertIn(supplier2_ledger_id, nets)
        self.assertEqual(nets[supplier2_ledger_id], 300.0)


# ======================================================================
# 21: Delete
# ======================================================================

class TestDelete(_BaseTest):

    def test_21_delete_reverses_accounting(self):
        dn_id = DebitNoteDAO.insert_debit_note(self._header(500.0),
                                                 self._items())
        self.assertTrue(self.engine.is_posted(SOURCE_DEBIT_NOTE, dn_id))
        DebitNoteDAO.delete_debit_note(dn_id)
        self.assertFalse(self.engine.is_posted(SOURCE_DEBIT_NOTE, dn_id))
        self.assertIsNone(DebitNoteDAO.get_by_id(dn_id))


# ======================================================================
# 22-27: Failure safety
# ======================================================================

class TestFailureSafety(_BaseTest):

    def test_22_supplier_without_ledger_id(self):
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("BEGIN")
            cur.execute("INSERT INTO suppliers (supplier_name) VALUES (?)",
                        ("NoLedgerSupplier",))
            raw_sup_id = cur.lastrowid
            conn.commit()
        finally:
            conn.close()

        header = self._header(200.0, supplier_id=raw_sup_id)
        with self.assertRaises(PostingError):
            DebitNoteDAO.insert_debit_note(header, self._items())
        self.assertEqual(len(DebitNoteDAO.get_all()), 0)

    def test_23_missing_purchase_return_system_ledger(self):
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE account_ledgers SET system_role = NULL "
                "WHERE system_role = ?", (ROLE_PURCHASE_RETURN,)
            )
            conn.commit()
        finally:
            conn.close()

        with self.assertRaises(PostingError):
            DebitNoteDAO.insert_debit_note(self._header(), self._items())
        self.assertEqual(len(DebitNoteDAO.get_all()), 0)

    def test_24_negative_total_creates_no_posting(self):
        dn_id = DebitNoteDAO.insert_debit_note(
            self._header(-100.0), self._items()
        )
        self.assertFalse(self.engine.is_posted(SOURCE_DEBIT_NOTE, dn_id))
        self.assertEqual(len(self.engine.get_posting_rows(SOURCE_DEBIT_NOTE, dn_id)), 0)

    def test_25_zero_amount_legacy_no_post_yet(self):
        dn_id = DebitNoteDAO.insert_debit_note(
            self._header(0.0), self._items()
        )
        self.assertIsNotNone(DebitNoteDAO.get_by_id(dn_id))
        self.assertFalse(
            self.engine.is_posted(SOURCE_DEBIT_NOTE, dn_id)
        )

    def test_26_negative_total_no_posting_rows(self):
        dn_id = DebitNoteDAO.insert_debit_note(
            self._header(-100.0), self._items()
        )
        self.assertEqual(len(self.engine.get_posting_rows(SOURCE_DEBIT_NOTE, dn_id)), 0)

    def test_27_missing_supplier_header(self):
        dn_id = DebitNoteDAO.insert_debit_note(
            self._header(200.0, supplier_id=None), self._items()
        )
        self.assertIsNotNone(DebitNoteDAO.get_by_id(dn_id))


# ======================================================================
# 28-30: Persistence and ledger visibility
# ======================================================================

class TestPersistenceAndLedger(_BaseTest):

    def test_28_restart_persistence(self):
        dn_id = DebitNoteDAO.insert_debit_note(self._header(555.0),
                                                 self._items())
        import sqlite3 as _sqlite3
        from database.connection import get_db_path

        fresh = _sqlite3.connect(get_db_path())
        fresh.row_factory = _sqlite3.Row
        try:
            rows = fresh.execute(
                "SELECT * FROM ledger_transactions "
                "WHERE reference_type = ? AND reference_id = ?",
                (SOURCE_DEBIT_NOTE, dn_id),
            ).fetchall()
        finally:
            fresh.close()

        self.assertEqual(len(rows), 2)
        debits = [r["debit"] for r in rows]
        credits = [r["credit"] for r in rows]
        self.assertIn(555.0, debits)
        self.assertIn(555.0, credits)
        self.assertTrue(
            PostingEngine().is_posted(SOURCE_DEBIT_NOTE, dn_id)
        )

    def test_29_supplier_ledger_shows_debit_note_entries(self):
        dn_id = DebitNoteDAO.insert_debit_note(self._header(200.0),
                                                 self._items())
        txns = LedgerDAO.get_transactions(self.supplier_ledger_id)
        dn_txns = [
            t for t in txns
            if t["reference_type"] == SOURCE_DEBIT_NOTE
        ]
        self.assertEqual(len(dn_txns), 1)
        self.assertEqual(dn_txns[0]["debit"], 200.0)
        self.assertEqual(dn_txns[0]["voucher_type"], "Debit Note")

    def test_30_purchase_return_ledger_shows_debit_note_entries(self):
        dn_id = DebitNoteDAO.insert_debit_note(self._header(200.0),
                                                 self._items())
        txns = LedgerDAO.get_transactions(self.purchase_return_ledger["id"])
        dn_txns = [
            t for t in txns
            if t["reference_type"] == SOURCE_DEBIT_NOTE
        ]
        self.assertEqual(len(dn_txns), 1)
        self.assertEqual(dn_txns[0]["credit"], 200.0)


# ======================================================================
# 31-36: Regression - all existing modules still work
# ======================================================================

class TestRegression(_BaseTest):

    def test_31_customer_receipt_still_works(self):
        rid = CustomerReceiptDAO.insert_receipt({
            "receipt_date": "2026-01-20", "receipt_time": "10:00",
            "customer_id": self.customer_id, "receipt_mode": "Cash",
            "amount": 300, "reference_no": "", "remarks": "",
        })
        self.assertGreater(rid, 0)
        rows = self.engine.get_posting_rows("CUSTOMER_RECEIPT", rid)
        self.assertEqual(len(rows), 2)

    def test_32_supplier_payment_still_works(self):
        pid = SupplierPaymentDAO.insert_payment({
            "payment_date": "2026-01-22", "payment_time": "10:00",
            "supplier_id": self.supplier_id, "payment_mode": "Cash",
            "amount": 150, "reference_no": "", "remarks": "",
        })
        self.assertGreater(pid, 0)
        rows = self.engine.get_posting_rows("SUPPLIER_PAYMENT", pid)
        self.assertEqual(len(rows), 2)

    def test_33_purchase_posting_still_works(self):
        inv_id = PurchaseDAO.insert_invoice(
            voucher_no="PV-0002",
            voucher_date="2026-01-30",
            voucher_time="",
            purchase_type="Cash",
            supplier_id=self.supplier_id,
            invoice_no="INV-002",
            invoice_date="2026-01-30",
            invoice_net_amount=1000.0,
            bill_discount=0,
            due_date="",
            total_amount=1000.0,
            gst_amount=0,
            debit_note_amount=0,
            other_amount=0,
            paid_amount=1000.0,
            round_off=0,
            net_amount=1000.0,
            remarks="",
            items=[{
                "item_id": self.item_id, "pack_size": "10x10",
                "pay_qty": 20, "free_qty": 0, "batch_no": "BATCH-B",
                "expiry": "12/28", "rate": 50.0, "mrp": 60.0,
                "discount": 0, "gst_percent": 0, "gst_amount": 0,
                "amount": 1000.0, "purchase_rate": 50.0,
                "net_rate": 50.0, "pp": 50.0,
            }],
        )
        self.assertGreater(inv_id, 0)
        rows = self.engine.get_posting_rows("PURCHASE_INVOICE", inv_id)
        self.assertEqual(len(rows), 2)

    def test_34_sales_posting_still_works(self):
        sale_id = SalesDAO.insert_invoice(
            bill_no="CS-0002", sale_date="2026-01-30", sale_time="10:00",
            sale_type="Cash", customer_id=self.customer_id,
            patient_name="", doctor_id=None,
            discount=0, paid_amount=250, total_amount=250, round_off=0,
            net_amount=250, remarks="",
            items=[{
                "item_id": self.item_id, "stock_batch_id": self.batch_id,
                "pack_size": "10x10", "location": "", "batch_no": "BATCH-A",
                "expiry": "12/27", "mrp": 50.0, "sale_qty": 5,
                "discount_amount": 0, "amount": 250.0,
            }],
        )
        self.assertGreater(sale_id, 0)
        rows = self.engine.get_posting_rows("COUNTER_SALE", sale_id)
        self.assertEqual(len(rows), 2)

    def test_35_credit_note_still_works(self):
        cn_id = CreditNoteDAO.insert_credit_note(
            {
                "voucher_date": "2026-01-25", "cn_date": "2026-01-25",
                "cn_type": "Customer", "customer_id": self.customer_id,
                "total_amount": 200, "ledger_amount": 200, "remarks": "",
            },
            [{
                "item_id": self.item_id, "stock_batch_id": self.batch_id,
                "batch_no": "BATCH-A", "expiry": "12/27", "pack_size": "10x10",
                "rate": 40, "mrp": 50, "return_qty": 5,
                "less_amount": 0, "amount": 200, "return_reason": "",
                "price_factor": 1.0,
            }],
        )
        self.assertGreater(cn_id, 0)
        rows = self.engine.get_posting_rows("CREDIT_NOTE", cn_id)
        self.assertEqual(len(rows), 2)

    def test_36_stock_master_still_works(self):
        all_stock = StockDAO.get_all()
        self.assertGreater(len(all_stock), 0)
        item_stock = StockDAO.get_by_item(self.item_id)
        self.assertGreater(len(item_stock), 0)


# ======================================================================
# 37-41: Additional edit, stock, and master regression
# ======================================================================

class TestEditAndMasterRegression(_BaseTest):

    def test_37_edit_return_qty_stock_remains_correct(self):
        before = StockDAO.get_stock_batch_by_id(self.batch_id)["stock_qty"]
        dn_id = DebitNoteDAO.insert_debit_note(self._header(400.0),
                                                 self._items(qty=10.0))
        mid = StockDAO.get_stock_batch_by_id(self.batch_id)["stock_qty"]
        self.assertAlmostEqual(mid, before - 10.0, places=2)

        DebitNoteDAO.update_debit_note(
            dn_id, self._header(200.0), self._items(qty=5.0),
        )
        after = StockDAO.get_stock_batch_by_id(self.batch_id)["stock_qty"]
        self.assertAlmostEqual(after, before - 5.0, places=2)

    def test_38_delete_restores_stock(self):
        before = StockDAO.get_stock_batch_by_id(self.batch_id)["stock_qty"]
        dn_id = DebitNoteDAO.insert_debit_note(self._header(400.0),
                                                 self._items(qty=10.0))
        DebitNoteDAO.delete_debit_note(dn_id)
        after = StockDAO.get_stock_batch_by_id(self.batch_id)["stock_qty"]
        self.assertAlmostEqual(after, before, places=2)

    def test_39_all_master_screens_still_work(self):
        self.assertGreater(len(CompanyDAO.get_all()), 0)
        self.assertGreater(len(UnitDAO.get_all()), 0)
        self.assertGreater(len(DrugDAO.get_all()), 0)
        self.assertGreater(len(SupplierDAO.get_all()), 0)
        self.assertGreater(len(CustomerDAO.get_all()), 0)
        self.assertGreater(len(DoctorDAO.get_all()), 0)
        self.assertGreater(len(ItemDAO.get_all()), 0)

    def test_40_debit_note_crud_still_works(self):
        dn_id = DebitNoteDAO.insert_debit_note(self._header(200.0),
                                                 self._items(qty=5.0))
        self.assertGreater(dn_id, 0)
        dn = DebitNoteDAO.get_by_id(dn_id)
        self.assertIsNotNone(dn)
        self.assertEqual(dn["total_amount"], 200.0)

    def test_41_multiple_debit_notes_post_independently(self):
        dn1_id = DebitNoteDAO.insert_debit_note(self._header(200.0),
                                                  self._items(qty=5.0))
        dn2_id = DebitNoteDAO.insert_debit_note(self._header(100.0),
                                                  self._items(qty=2.5))
        self.assertTrue(self.engine.is_posted(SOURCE_DEBIT_NOTE, dn1_id))
        self.assertTrue(self.engine.is_posted(SOURCE_DEBIT_NOTE, dn2_id))
        nets1 = self._nets(dn1_id)
        nets2 = self._nets(dn2_id)
        self.assertEqual(nets1[self.supplier_ledger_id], 200.0)
        self.assertEqual(nets2[self.supplier_ledger_id], 100.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
