"""Phase 2F — Purchase Invoice posting integration tests.

40 tests covering:
  1-3:   Supplier ledger linkage and system ledger setup
  4-8:   Credit purchase posting (2 rows, debit/credit, reference, voucher)
  9-11:  Cash purchase posting
  12-13: Credit Card purchase posting
  14-16: Partial payment posting (3 rows)
  17-18: Duplicate posting prevention
  19-20: Reversal (mirrored rows, net-zero)
  21-24: Edit repost (amount change, type change)
  25-26: Delete reversal
  27-34: Failure safety (missing ledgers, invalid amounts, unsupported
         purchase type, atomic rollback)
  35-36: Persistence, ledger visibility
  37-40: Regression — all existing modules still work
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
    ensure_system_ledgers,
)
from database.accounting_posting import (
    SOURCE_PURCHASE_INVOICE,
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
    """Shared setUp — clean tables, masters, system roles, item."""

    _DB_PATH = os.path.join(os.path.dirname(__file__), "_test_purchase_posting.db")

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
        self.purchase_ledger = LedgerDAO.get_by_system_role(ROLE_PURCHASE)
        self.cash_ledger = LedgerDAO.get_by_system_role(ROLE_CASH)
        self.bank_ledger = LedgerDAO.get_by_system_role(ROLE_BANK)
        self.engine = posting_engine

    # ── helpers ──────────────────────────────────────────────────────
    def _insert_purchase(self, *, net=1000.0, paid=0.0, purchase_type="Credit",
                         batch="BATCH-A", supplier_id=None, voucher_no="PV-0001"):
        return PurchaseDAO.insert_invoice(
            voucher_no=voucher_no, voucher_date="2026-02-01", voucher_time="",
            purchase_type=purchase_type,
            supplier_id=supplier_id or self.supplier_id,
            invoice_no="INV-001", invoice_date="2026-02-01",
            invoice_net_amount=net, bill_discount=0, due_date="",
            total_amount=net, gst_amount=0, debit_note_amount=0,
            other_amount=0, paid_amount=paid, round_off=0,
            net_amount=net, remarks="",
            items=[{
                "item_id": self.item_id, "pack_size": "10x10",
                "pay_qty": 20, "free_qty": 0, "batch_no": batch,
                "expiry": "12/28", "rate": net / 20.0, "mrp": 60.0,
                "discount": 0, "gst_percent": 0, "gst_amount": 0,
                "amount": net, "purchase_rate": net / 20.0,
                "net_rate": net / 20.0, "pp": net / 20.0,
            }],
        )

    def _nets(self, invoice_id):
        """Per-ledger net (debit-credit) of all rows for an invoice.
        Filters out fully-reversed (net == 0) ledgers."""
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT ledger_id, SUM(debit) - SUM(credit) AS net "
                "FROM ledger_transactions "
                "WHERE reference_type = ? AND reference_id = ? "
                "GROUP BY ledger_id "
                "HAVING ABS(SUM(debit) - SUM(credit)) > 0.005",
                (SOURCE_PURCHASE_INVOICE, invoice_id),
            ).fetchall()
            return {r["ledger_id"]: round(r["net"] or 0.0, 2) for r in rows}
        finally:
            conn.close()

    def _edit_purchase(self, invoice_id, *, net=1000.0, paid=0.0,
                       purchase_type="Credit"):
        PurchaseDAO.update_invoice(
            invoice_id=invoice_id, voucher_no="PV-0001",
            voucher_date="2026-02-01", voucher_time="",
            purchase_type=purchase_type, supplier_id=self.supplier_id,
            invoice_no="INV-001", invoice_date="2026-02-01",
            invoice_net_amount=net, bill_discount=0, due_date="",
            total_amount=net, gst_amount=0, debit_note_amount=0,
            other_amount=0, paid_amount=paid, round_off=0,
            net_amount=net, remarks="",
            items=[{
                "item_id": self.item_id, "pack_size": "10x10",
                "pay_qty": 20, "free_qty": 0, "batch_no": "BATCH-A",
                "expiry": "12/28", "rate": net / 20.0, "mrp": 60.0,
                "discount": 0, "gst_percent": 0, "gst_amount": 0,
                "amount": net, "purchase_rate": net / 20.0,
                "net_rate": net / 20.0, "pp": net / 20.0,
            }],
        )


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

    def test_02_purchase_system_ledger_exists(self):
        self.assertIsNotNone(self.purchase_ledger)
        self.assertEqual(self.purchase_ledger["system_role"], ROLE_PURCHASE)
        self.assertEqual(self.purchase_ledger["account_group"], "Purchase Accounts")

    def test_03_cash_system_ledger_exists(self):
        self.assertIsNotNone(self.cash_ledger)
        self.assertEqual(self.cash_ledger["system_role"], ROLE_CASH)


# ======================================================================
# 4-8: Credit purchase posting
# ======================================================================

class TestCreditPurchasePosting(_BaseTest):

    def test_04_credit_purchase_creates_two_rows(self):
        inv_id = self._insert_purchase(net=1000.0, paid=0.0,
                                       purchase_type="Credit")
        rows = self.engine.get_posting_rows(SOURCE_PURCHASE_INVOICE, inv_id)
        self.assertEqual(len(rows), 2)

    def test_05_purchase_ledger_debited(self):
        inv_id = self._insert_purchase(net=1000.0, paid=0.0,
                                       purchase_type="Credit")
        nets = self._nets(inv_id)
        self.assertIn(self.purchase_ledger["id"], nets)
        self.assertEqual(nets[self.purchase_ledger["id"]], 1000.0)

    def test_06_supplier_ledger_credited(self):
        inv_id = self._insert_purchase(net=750.0, paid=0.0,
                                       purchase_type="Credit")
        nets = self._nets(inv_id)
        self.assertIn(self.supplier_ledger_id, nets)
        self.assertEqual(nets[self.supplier_ledger_id], -750.0)

    def test_07_reference_type_and_id(self):
        inv_id = self._insert_purchase(net=100.0, paid=0.0,
                                       purchase_type="Credit")
        rows = self.engine.get_posting_rows(SOURCE_PURCHASE_INVOICE, inv_id)
        for r in rows:
            self.assertEqual(r["reference_type"], SOURCE_PURCHASE_INVOICE)
            self.assertEqual(r["reference_id"], inv_id)

    def test_08_voucher_number_in_posting(self):
        inv_id = self._insert_purchase(net=100.0, paid=0.0,
                                       purchase_type="Credit")
        rows = self.engine.get_posting_rows(SOURCE_PURCHASE_INVOICE, inv_id)
        voucher_no = rows[0]["voucher_no"]
        self.assertTrue(voucher_no.startswith("PV-"))
        for r in rows:
            self.assertEqual(r["voucher_no"], voucher_no)


# ======================================================================
# 9-11: Cash purchase posting
# ======================================================================

class TestCashPurchasePosting(_BaseTest):

    def test_09_cash_purchase_creates_two_rows(self):
        inv_id = self._insert_purchase(net=1000.0, paid=1000.0,
                                       purchase_type="Cash")
        rows = self.engine.get_posting_rows(SOURCE_PURCHASE_INVOICE, inv_id)
        self.assertEqual(len(rows), 2)

    def test_10_cash_ledger_credited(self):
        inv_id = self._insert_purchase(net=1000.0, paid=1000.0,
                                       purchase_type="Cash")
        nets = self._nets(inv_id)
        self.assertIn(self.cash_ledger["id"], nets)
        self.assertEqual(nets[self.cash_ledger["id"]], -1000.0)
        self.assertNotIn(self.supplier_ledger_id, nets)

    def test_11_cash_purchase_debits_purchase(self):
        inv_id = self._insert_purchase(net=500.0, paid=500.0,
                                       purchase_type="Cash")
        nets = self._nets(inv_id)
        self.assertIn(self.purchase_ledger["id"], nets)
        self.assertEqual(nets[self.purchase_ledger["id"]], 500.0)


# ======================================================================
# 12-13: Credit Card purchase posting
# ======================================================================

class TestCreditCardPurchasePosting(_BaseTest):

    def test_12_credit_card_purchase_credits_bank(self):
        inv_id = self._insert_purchase(net=600.0, paid=600.0,
                                       purchase_type="Credit Card")
        nets = self._nets(inv_id)
        self.assertIn(self.bank_ledger["id"], nets)
        self.assertEqual(nets[self.bank_ledger["id"]], -600.0)
        self.assertNotIn(self.cash_ledger["id"], nets)

    def test_13_credit_card_purchase_debits_purchase(self):
        inv_id = self._insert_purchase(net=800.0, paid=800.0,
                                       purchase_type="Credit Card")
        nets = self._nets(inv_id)
        self.assertEqual(nets[self.purchase_ledger["id"]], 800.0)


# ======================================================================
# 14-16: Partial payment posting
# ======================================================================

class TestPartialPaymentPosting(_BaseTest):

    def test_14_partial_payment_creates_three_rows(self):
        inv_id = self._insert_purchase(net=1000.0, paid=400.0,
                                       purchase_type="Cash")
        rows = self.engine.get_posting_rows(SOURCE_PURCHASE_INVOICE, inv_id)
        self.assertEqual(len(rows), 3)

    def test_15_partial_payment_credits_cash_and_supplier(self):
        inv_id = self._insert_purchase(net=1000.0, paid=400.0,
                                       purchase_type="Cash")
        nets = self._nets(inv_id)
        self.assertEqual(nets[self.purchase_ledger["id"]], 1000.0)
        self.assertEqual(nets[self.cash_ledger["id"]], -400.0)
        self.assertEqual(nets[self.supplier_ledger_id], -600.0)

    def test_16_partial_credit_type_uses_cash_default(self):
        inv_id = self._insert_purchase(net=1000.0, paid=300.0,
                                       purchase_type="Credit")
        nets = self._nets(inv_id)
        self.assertEqual(nets[self.cash_ledger["id"]], -300.0)
        self.assertEqual(nets[self.supplier_ledger_id], -700.0)


# ======================================================================
# 17-18: Duplicate posting prevention
# ======================================================================

class TestDuplicatePrevention(_BaseTest):

    def test_17_duplicate_posting_raises(self):
        inv_id = self._insert_purchase(net=100.0, paid=0.0,
                                       purchase_type="Credit")
        with self.assertRaises(PostingError):
            self.engine.post_purchase_invoice(inv_id)

    def test_18_no_duplicate_active_effect(self):
        inv_id = self._insert_purchase(net=100.0, paid=0.0,
                                       purchase_type="Credit")
        rows = self.engine.get_posting_rows(SOURCE_PURCHASE_INVOICE, inv_id)
        self.assertEqual(len(rows), 2)


# ======================================================================
# 19-20: Reversal
# ======================================================================

class TestReversal(_BaseTest):

    def test_19_reversal_creates_mirrored_rows(self):
        inv_id = self._insert_purchase(net=500.0, paid=0.0,
                                       purchase_type="Credit")
        reversed_ids = self.engine.reverse(SOURCE_PURCHASE_INVOICE, inv_id)
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

    def test_20_net_becomes_zero_after_reversal(self):
        inv_id = self._insert_purchase(net=500.0, paid=0.0,
                                       purchase_type="Credit")
        self.engine.reverse(SOURCE_PURCHASE_INVOICE, inv_id)
        nets = self._nets(inv_id)
        self.assertEqual(len(nets), 0)


# ======================================================================
# 21-24: Edit / repost
# ======================================================================

class TestEditAndRepost(_BaseTest):

    def test_21_edit_amount_reposts(self):
        inv_id = self._insert_purchase(net=500.0, paid=0.0,
                                       purchase_type="Credit")
        self._edit_purchase(inv_id, net=1500.0, paid=0.0,
                            purchase_type="Credit")
        nets = self._nets(inv_id)
        self.assertEqual(nets[self.purchase_ledger["id"]], 1500.0)
        self.assertEqual(nets[self.supplier_ledger_id], -1500.0)

    def test_22_old_posting_reversed_on_edit(self):
        inv_id = self._insert_purchase(net=500.0, paid=0.0,
                                       purchase_type="Credit")
        rows_before = self.engine.get_posting_rows(SOURCE_PURCHASE_INVOICE, inv_id)
        self.assertEqual(len(rows_before), 2)

        self._edit_purchase(inv_id, net=1000.0, paid=0.0,
                            purchase_type="Credit")
        rows_after = self.engine.get_posting_rows(SOURCE_PURCHASE_INVOICE, inv_id)
        # 2 original + 2 reversal + 2 new = 6
        self.assertEqual(len(rows_after), 6)

    def test_23_edit_type_cash_to_credit(self):
        inv_id = self._insert_purchase(net=1000.0, paid=1000.0,
                                       purchase_type="Cash")
        self._edit_purchase(inv_id, net=1000.0, paid=0.0,
                            purchase_type="Credit")
        nets = self._nets(inv_id)
        self.assertIn(self.supplier_ledger_id, nets)
        self.assertEqual(nets[self.supplier_ledger_id], -1000.0)
        self.assertNotIn(self.cash_ledger["id"], nets)

    def test_24_edit_partial_to_full(self):
        inv_id = self._insert_purchase(net=1000.0, paid=400.0,
                                       purchase_type="Cash")
        self._edit_purchase(inv_id, net=1000.0, paid=1000.0,
                            purchase_type="Cash")
        nets = self._nets(inv_id)
        self.assertEqual(nets[self.purchase_ledger["id"]], 1000.0)
        self.assertEqual(nets[self.cash_ledger["id"]], -1000.0)
        self.assertNotIn(self.supplier_ledger_id, nets)


# ======================================================================
# 25-26: Delete
# ======================================================================

class TestDelete(_BaseTest):

    def test_25_delete_reverses_accounting(self):
        inv_id = self._insert_purchase(net=500.0, paid=0.0,
                                       purchase_type="Credit")
        self.assertTrue(self.engine.is_posted(SOURCE_PURCHASE_INVOICE, inv_id))
        PurchaseDAO.delete_invoice(inv_id)
        self.assertFalse(self.engine.is_posted(SOURCE_PURCHASE_INVOICE, inv_id))

    def test_26_no_active_effect_after_delete(self):
        inv_id = self._insert_purchase(net=500.0, paid=0.0,
                                       purchase_type="Credit")
        PurchaseDAO.delete_invoice(inv_id)
        nets = self._nets(inv_id)
        self.assertEqual(len(nets), 0)
        self.assertIsNone(PurchaseDAO.get_by_id(inv_id))


# ======================================================================
# 27-34: Failure safety
# ======================================================================

class TestFailureSafety(_BaseTest):

    def test_27_missing_purchase_system_ledger(self):
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE account_ledgers SET system_role = NULL "
                "WHERE system_role = ?", (ROLE_PURCHASE,)
            )
            conn.commit()
        finally:
            conn.close()

        with self.assertRaises(PostingError):
            self._insert_purchase(net=1000.0, paid=0.0,
                                  purchase_type="Credit")
        # Whole save rolled back — nothing persisted
        self.assertEqual(len(PurchaseDAO.get_all()), 0)

    def test_28_missing_supplier_ledger(self):
        # Create a supplier without a linked ledger
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

        with self.assertRaises(PostingError):
            self._insert_purchase(net=1000.0, paid=0.0,
                                  purchase_type="Credit", supplier_id=raw_id)
        self.assertEqual(len(PurchaseDAO.get_all()), 0)

    def test_29_missing_cash_system_ledger(self):
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
            self._insert_purchase(net=1000.0, paid=1000.0,
                                  purchase_type="Cash")
        self.assertEqual(len(PurchaseDAO.get_all()), 0)

    def test_30_missing_bank_system_ledger(self):
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
            self._insert_purchase(net=1000.0, paid=1000.0,
                                  purchase_type="Credit Card")
        self.assertEqual(len(PurchaseDAO.get_all()), 0)

    def test_31_invalid_net_amount_zero(self):
        with self.assertRaises(PostingError):
            self._insert_purchase(net=0.0, paid=0.0,
                                  purchase_type="Credit")
        self.assertEqual(len(PurchaseDAO.get_all()), 0)

    def test_32_paid_amount_negative(self):
        with self.assertRaises(PostingError):
            self._insert_purchase(net=1000.0, paid=-100.0,
                                  purchase_type="Cash")
        self.assertEqual(len(PurchaseDAO.get_all()), 0)

    def test_33_paid_exceeds_net(self):
        with self.assertRaises(PostingError):
            self._insert_purchase(net=1000.0, paid=1200.0,
                                  purchase_type="Cash")
        self.assertEqual(len(PurchaseDAO.get_all()), 0)

    def test_34_unsupported_purchase_type(self):
        with self.assertRaises(PostingError):
            self._insert_purchase(net=1000.0, paid=500.0,
                                  purchase_type="Crypto")
        self.assertEqual(len(PurchaseDAO.get_all()), 0)


# ======================================================================
# 35-36: Persistence and ledger visibility
# ======================================================================

class TestPersistenceAndLedger(_BaseTest):

    def test_35_restart_persistence(self):
        inv_id = self._insert_purchase(net=555.0, paid=0.0,
                                       purchase_type="Credit")

        from database.connection import get_db_path
        import sqlite3 as _sqlite3
        fresh = _sqlite3.connect(get_db_path())
        fresh.row_factory = _sqlite3.Row
        try:
            rows = fresh.execute(
                "SELECT * FROM ledger_transactions "
                "WHERE reference_type = ? AND reference_id = ?",
                (SOURCE_PURCHASE_INVOICE, inv_id),
            ).fetchall()
        finally:
            fresh.close()

        self.assertEqual(len(rows), 2)
        debits = [r["debit"] for r in rows]
        credits = [r["credit"] for r in rows]
        self.assertIn(555.0, debits)
        self.assertIn(555.0, credits)

        self.assertTrue(
            PostingEngine().is_posted(SOURCE_PURCHASE_INVOICE, inv_id)
        )

    def test_36_account_ledger_displays_purchase_entries(self):
        inv_id = self._insert_purchase(net=500.0, paid=200.0,
                                       purchase_type="Cash")

        purchase_txns = LedgerDAO.get_transactions(self.purchase_ledger["id"])
        purchase_posting_txns = [
            t for t in purchase_txns
            if t["reference_type"] == SOURCE_PURCHASE_INVOICE
        ]
        self.assertEqual(len(purchase_posting_txns), 1)
        self.assertEqual(purchase_posting_txns[0]["voucher_type"], "Purchase Invoice")
        self.assertEqual(purchase_posting_txns[0]["debit"], 500.0)
        self.assertIn("TestSupplier", purchase_posting_txns[0]["description"])

        supplier_txns = LedgerDAO.get_transactions(self.supplier_ledger_id)
        supplier_posting_txns = [
            t for t in supplier_txns
            if t["reference_type"] == SOURCE_PURCHASE_INVOICE
        ]
        self.assertEqual(len(supplier_posting_txns), 1)
        self.assertEqual(supplier_posting_txns[0]["credit"], 300.0)


# ======================================================================
# 37-40: Regression — all existing modules still work
# ======================================================================

class TestRegression(_BaseTest):

    def test_37_purchase_crud_still_works(self):
        inv_id = self._insert_purchase(net=2000.0, paid=2000.0,
                                       purchase_type="Cash")
        inv = PurchaseDAO.get_by_id(inv_id)
        self.assertEqual(inv["voucher_no"], "PV-0001")
        self.assertEqual(inv["supplier_name"], "TestSupplier")

        all_invs = PurchaseDAO.get_all()
        self.assertGreaterEqual(len(all_invs), 1)

        filtered = PurchaseDAO.get_all_filtered(
            start_date="2026-01-01", end_date="2026-12-31"
        )
        self.assertGreaterEqual(len(filtered), 1)

        items = PurchaseDAO.get_invoice_items(inv_id)
        self.assertEqual(len(items), 1)

        stock = PurchaseDAO.get_stock_batches_for_item(self.item_id)
        self.assertEqual(len(stock), 1)
        self.assertEqual(stock[0]["stock_qty"], 20.0)

    def test_38_customer_receipt_still_works(self):
        rid = CustomerReceiptDAO.insert_receipt({
            "receipt_date": "2026-01-20", "receipt_time": "10:00",
            "customer_id": self.customer_id, "receipt_mode": "Cash",
            "amount": 300, "reference_no": "", "remarks": "",
        })
        self.assertGreater(rid, 0)
        rows = posting_engine.get_posting_rows("CUSTOMER_RECEIPT", rid)
        self.assertEqual(len(rows), 2)

    def test_39_supplier_payment_still_works(self):
        pid = SupplierPaymentDAO.insert_payment({
            "payment_date": "2026-01-22", "payment_time": "10:00",
            "supplier_id": self.supplier_id, "payment_mode": "Cash",
            "amount": 400, "reference_no": "", "remarks": "",
        })
        self.assertGreater(pid, 0)
        rows = posting_engine.get_posting_rows("SUPPLIER_PAYMENT", pid)
        self.assertEqual(len(rows), 2)

    def test_40_counter_sale_still_works(self):
        self._insert_purchase(net=1000.0, paid=1000.0, purchase_type="Cash")
        batch_id = StockDAO.get_stock_batches_for_item(self.item_id)[0]["id"]
        sale_id = SalesDAO.insert_invoice(
            bill_no="CS-0001", sale_date="2026-01-25", sale_time="10:00",
            sale_type="Cash", customer_id=self.customer_id,
            patient_name="TestPatient", doctor_id=None,
            discount=0, paid_amount=250, total_amount=250, round_off=0,
            net_amount=250, remarks="",
            items=[{
                "item_id": self.item_id, "stock_batch_id": batch_id,
                "pack_size": "10x10", "location": "", "batch_no": "BATCH-A",
                "expiry": "12/28", "mrp": 60, "sale_qty": 5,
                "discount_amount": 0, "amount": 250,
            }],
        )
        self.assertGreater(sale_id, 0)
        rows = posting_engine.get_posting_rows("COUNTER_SALE", sale_id)
        self.assertEqual(len(rows), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)