"""Phase 3 — Trial Balance tests.

50 tests covering:
   1-5:    Empty DB, opening balances, balanced journal entries
   6-12:   Each of the 7 posted source types reflects correctly
  13-15:   System / customer / supplier ledgers included
  16-19:   Zero-balance behavior, as-of date filtering
  20-22:   Balance invariant, difference, unbalanced detection
  23-27:   Account Ledger agreement, reversals, edit, delete, coexistence
  28-36:   Multi-line journals, multi-transaction ledgers, each system role
  37:      Persistence after restart
  38-41:   UI (skip without PySide6; run in the development environment)
  42-50:   Regression — existing modules still work
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
    ROLE_PURCHASE,
    ROLE_PURCHASE_RETURN,
    ROLE_SALES,
    ROLE_SALES_RETURN,
    ensure_system_ledgers,
)
from database.accounting_posting import (
    SOURCE_CUSTOMER_RECEIPT,
    SOURCE_COUNTER_SALE,
    SOURCE_CREDIT_NOTE,
    SOURCE_DEBIT_NOTE,
    SOURCE_JOURNAL_ENTRY,
    SOURCE_PURCHASE_INVOICE,
    SOURCE_SUPPLIER_PAYMENT,
    PostingEngine,
)
from database.trial_balance_dao import TrialBalanceDAO
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

try:
    from PySide6.QtWidgets import QApplication
    from screens.trial_balance import TrialBalancePage

    HAS_PYSIDE6 = True
    _PYSIDE_SKIP_REASON = ""
except ImportError as _exc:  # pragma: no cover - test environment without GUI
    HAS_PYSIDE6 = False
    _PYSIDE_SKIP_REASON = f"PySide6 not available ({_exc})"

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
    """Fresh DB per module; clean tables + masters + system ledgers per case.

    No stock is seeded by default — seeding posts a purchase which would
    pollute Trial Balance figures. Tests needing stock call _seed_stock.
    """

    _DB_PATH = os.path.join(os.path.dirname(__file__), "_test_trial_balance.db")

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

        self.customer_ledger_id = CustomerDAO.get_ledger_id(self.customer_id)
        self.supplier_ledger_id = SupplierDAO.get_ledger_id(self.supplier_id)
        self.cash_ledger = LedgerDAO.get_by_system_role(ROLE_CASH)
        self.bank_ledger = LedgerDAO.get_by_system_role(ROLE_BANK)
        self.sales_ledger = LedgerDAO.get_by_system_role(ROLE_SALES)
        self.purchase_ledger = LedgerDAO.get_by_system_role(ROLE_PURCHASE)
        self.sales_return_ledger = LedgerDAO.get_by_system_role(ROLE_SALES_RETURN)
        self.purchase_return_ledger = LedgerDAO.get_by_system_role(ROLE_PURCHASE_RETURN)

        self.engine = PostingEngine()

    # ── helpers ──────────────────────────────────────────────────────
    def _seed_stock(self, qty=100.0, rate=40.0, date="2026-01-05"):
        """Fully-paid cash purchase — posts PURCHASE debit / CASH credit."""
        PurchaseDAO.insert_invoice(
            voucher_no="PV-SEED", voucher_date=date, voucher_time="",
            purchase_type="Cash", supplier_id=self.supplier_id,
            invoice_no="INV-SEED", invoice_date=date,
            invoice_net_amount=qty * rate, bill_discount=0, due_date="",
            total_amount=qty * rate, gst_amount=0, debit_note_amount=0,
            other_amount=0, paid_amount=qty * rate, round_off=0,
            net_amount=qty * rate, remarks="",
            items=[{
                "item_id": self.item_id, "pack_size": "10x10",
                "pay_qty": qty, "free_qty": 0, "batch_no": "BATCH-A",
                "expiry": "12/27", "rate": rate, "mrp": 50.0, "discount": 0,
                "gst_percent": 0, "gst_amount": 0, "amount": qty * rate,
                "purchase_rate": rate, "net_rate": rate, "pp": rate,
            }],
        )
        batches = StockDAO.get_stock_batches_for_item(self.item_id)
        return batches[0]["id"]

    def _walkin_sale(self, amount=400.0, date="2026-03-10"):
        bill_no = SalesDAO.generate_next_bill_no()
        return SalesDAO.insert_invoice(
            bill_no=bill_no, sale_date=date, sale_time="",
            sale_type="Cash", customer_id=None, patient_name="",
            doctor_id=None, discount=0, paid_amount=amount,
            total_amount=amount, round_off=0, net_amount=amount,
            remarks="",
            items=[{
                "item_id": self.item_id, "stock_batch_id": self._seed_stock(),
                "pack_size": "10x10", "location": "", "batch_no": "BATCH-A",
                "expiry": "12/27", "mrp": 50.0, "sale_qty": amount / 50.0,
                "discount_amount": 0, "amount": amount,
            }],
        )

    def _tb_row(self, report, ledger_id):
        for r in report["rows"]:
            if r["ledger_id"] == ledger_id:
                return r
        self.fail(f"Ledger {ledger_id} missing from Trial Balance")


# ======================================================================
# 1-5: Empty database, opening balances, journal entries
# ======================================================================

class TestBasics(_BaseTest):

    def test_01_empty_database(self):
        report = TrialBalanceDAO.get_trial_balance()
        # Ledgers exist (masters + system roles) but carry no balances
        self.assertGreaterEqual(report["totals"]["ledger_count"], 8)
        for r in report["rows"]:
            self.assertTrue(r["is_zero"])
            self.assertEqual(r["debit"], 0.0)
            self.assertEqual(r["credit"], 0.0)
        self.assertEqual(report["totals"]["total_debit"], 0.0)
        self.assertEqual(report["totals"]["total_credit"], 0.0)
        self.assertTrue(report["totals"]["balanced"])
        self.assertTrue(TrialBalanceDAO.verify_balanced())

    def test_02_opening_debit_balance(self):
        lid = LedgerDAO.insert_ledger(
            "OB Debit Test", account_group="Sundry Debtors",
            opening_balance=500.0, opening_balance_type="Debit",
        )
        report = TrialBalanceDAO.get_trial_balance()
        row = self._tb_row(report, lid)
        self.assertEqual(row["debit"], 500.0)
        self.assertEqual(row["credit"], 0.0)
        self.assertFalse(row["is_zero"])

    def test_03_opening_credit_balance(self):
        lid = LedgerDAO.insert_ledger(
            "OB Credit Test", account_group="Sundry Creditors",
            opening_balance=750.25, opening_balance_type="Credit",
        )
        report = TrialBalanceDAO.get_trial_balance()
        row = self._tb_row(report, lid)
        self.assertEqual(row["debit"], 0.0)
        self.assertEqual(row["credit"], 750.25)
        self.assertFalse(row["is_zero"])

    def test_04_one_balanced_journal_entry(self):
        JournalDAO.insert_entry(
            {"entry_date": "2026-02-01", "narration": "Capital"},
            [
                {"ledger_id": self.cash_ledger["id"], "description": "",
                 "debit": 1000.0, "credit": 0.0},
                {"ledger_id": self.sales_ledger["id"], "description": "",
                 "debit": 0.0, "credit": 1000.0},
            ],
        )
        report = TrialBalanceDAO.get_trial_balance()
        self.assertEqual(self._tb_row(report, self.cash_ledger["id"])["debit"], 1000.0)
        self.assertEqual(self._tb_row(report, self.sales_ledger["id"])["credit"], 1000.0)
        self.assertTrue(report["totals"]["balanced"])
        self.assertEqual(report["totals"]["difference"], 0.0)

    def test_05_multiple_journal_entries(self):
        JournalDAO.insert_entry(
            {"entry_date": "2026-02-01", "narration": "JE 1"},
            [
                {"ledger_id": self.cash_ledger["id"], "description": "",
                 "debit": 100.0, "credit": 0.0},
                {"ledger_id": self.bank_ledger["id"], "description": "",
                 "debit": 0.0, "credit": 100.0},
            ],
        )
        JournalDAO.insert_entry(
            {"entry_date": "2026-02-02", "narration": "JE 2"},
            [
                {"ledger_id": self.customer_ledger_id, "description": "",
                 "debit": 250.0, "credit": 0.0},
                {"ledger_id": self.cash_ledger["id"], "description": "",
                 "debit": 0.0, "credit": 250.0},
            ],
        )
        report = TrialBalanceDAO.get_trial_balance()
        row = self._tb_row(report, self.cash_ledger["id"])
        self.assertEqual(row["debit"], 0.0)   # 100 debit - 250 credit
        self.assertEqual(row["credit"], 150.0)
        self.assertEqual(self._tb_row(report, self.bank_ledger["id"])["credit"], 100.0)
        self.assertEqual(self._tb_row(report, self.customer_ledger_id)["debit"], 250.0)
        self.assertTrue(report["totals"]["balanced"])


# ======================================================================
# 6-12: Every posted source type reflects in the Trial Balance
# ======================================================================

class TestSourceTypes(_BaseTest):

    def test_06_customer_receipt(self):
        CustomerReceiptDAO.insert_receipt({
            "receipt_date": "2026-02-01", "receipt_time": "",
            "customer_id": self.customer_id, "receipt_mode": "Cash",
            "amount": 500.0, "reference_no": "", "remarks": "",
        })
        report = TrialBalanceDAO.get_trial_balance()
        self.assertEqual(self._tb_row(report, self.cash_ledger["id"])["debit"], 500.0)
        self.assertEqual(self._tb_row(report, self.customer_ledger_id)["credit"], 500.0)
        self.assertTrue(report["totals"]["balanced"])

    def test_07_supplier_payment(self):
        SupplierPaymentDAO.insert_payment({
            "payment_date": "2026-02-01", "payment_time": "",
            "supplier_id": self.supplier_id, "payment_mode": "Bank",
            "amount": 300.0, "reference_no": "NEFT-1", "remarks": "",
        })
        report = TrialBalanceDAO.get_trial_balance()
        self.assertEqual(self._tb_row(report, self.supplier_ledger_id)["debit"], 300.0)
        self.assertEqual(self._tb_row(report, self.bank_ledger["id"])["credit"], 300.0)
        self.assertTrue(report["totals"]["balanced"])

    def test_08_counter_sale(self):
        self._walkin_sale(amount=400.0)
        report = TrialBalanceDAO.get_trial_balance()
        # seed purchase: CASH -4000 credit; sale: CASH +400 debit -> net 3600 credit
        self.assertEqual(self._tb_row(report, self.cash_ledger["id"])["credit"], 3600.0)
        self.assertEqual(self._tb_row(report, self.purchase_ledger["id"])["debit"], 4000.0)
        self.assertEqual(self._tb_row(report, self.sales_ledger["id"])["credit"], 400.0)
        self.assertTrue(report["totals"]["balanced"])

    def test_09_purchase_invoice(self):
        PurchaseDAO.insert_invoice(
            voucher_no="PV-0001", voucher_date="2026-02-01", voucher_time="",
            purchase_type="Credit", supplier_id=self.supplier_id,
            invoice_no="INV-001", invoice_date="2026-02-01",
            invoice_net_amount=1000.0, bill_discount=0, due_date="",
            total_amount=1000.0, gst_amount=0, debit_note_amount=0,
            other_amount=0, paid_amount=0, round_off=0,
            net_amount=1000.0, remarks="",
            items=[{
                "item_id": self.item_id, "pack_size": "10x10",
                "pay_qty": 20, "free_qty": 0, "batch_no": "BATCH-P",
                "expiry": "12/27", "rate": 50.0, "mrp": 60.0, "discount": 0,
                "gst_percent": 0, "gst_amount": 0, "amount": 1000.0,
                "purchase_rate": 50.0, "net_rate": 50.0, "pp": 50.0,
            }],
        )
        report = TrialBalanceDAO.get_trial_balance()
        self.assertEqual(self._tb_row(report, self.purchase_ledger["id"])["debit"], 1000.0)
        self.assertEqual(self._tb_row(report, self.supplier_ledger_id)["credit"], 1000.0)
        self.assertTrue(report["totals"]["balanced"])

    def test_10_credit_note(self):
        batch_id = self._seed_stock()
        CreditNoteDAO.insert_credit_note(
            {"voucher_date": "2026-02-01", "cn_date": "2026-02-01",
             "cn_type": "Customer", "customer_id": self.customer_id,
             "total_amount": 100.0, "ledger_amount": 100.0, "remarks": ""},
            [{
                "item_id": self.item_id, "stock_batch_id": batch_id,
                "batch_no": "BATCH-A", "expiry": "12/27",
                "pack_size": "10x10", "rate": 40, "mrp": 50,
                "return_qty": 2, "less_amount": 0, "amount": 100,
                "return_reason": "Damaged", "price_factor": 1.0,
            }],
        )
        report = TrialBalanceDAO.get_trial_balance()
        self.assertEqual(self._tb_row(report, self.sales_return_ledger["id"])["debit"], 100.0)
        self.assertEqual(self._tb_row(report, self.customer_ledger_id)["credit"], 100.0)
        self.assertTrue(report["totals"]["balanced"])

    def test_11_debit_note(self):
        batch_id = self._seed_stock()
        DebitNoteDAO.insert_debit_note(
            {"voucher_date": "2026-02-01", "voucher_time": "",
             "dn_date": "2026-02-01", "dn_type": "Supplier",
             "supplier_id": self.supplier_id, "total_amount": 200.0,
             "ledger_amount": 200.0, "remarks": ""},
            [{
                "item_id": self.item_id, "stock_batch_id": batch_id,
                "batch_no": "BATCH-A", "expiry": "12/27",
                "pack_size": "10x10", "rate": 40, "mrp": 50,
                "return_qty": 5, "less_amount": 0, "amount": 200,
                "return_reason": "Expired", "price_factor": 1.0,
            }],
        )
        report = TrialBalanceDAO.get_trial_balance()
        self.assertEqual(self._tb_row(report, self.supplier_ledger_id)["debit"], 200.0)
        self.assertEqual(self._tb_row(report, self.purchase_return_ledger["id"])["credit"], 200.0)
        self.assertTrue(report["totals"]["balanced"])

    def test_12_mixed_transactions(self):
        # One of every source type in the same database
        self._walkin_sale(amount=400.0)  # seeds a purchase too
        PurchaseDAO.insert_invoice(
            voucher_no="PV-0002", voucher_date="2026-02-02", voucher_time="",
            purchase_type="Credit", supplier_id=self.supplier_id,
            invoice_no="INV-002", invoice_date="2026-02-02",
            invoice_net_amount=600.0, bill_discount=0, due_date="",
            total_amount=600.0, gst_amount=0, debit_note_amount=0,
            other_amount=0, paid_amount=0, round_off=0,
            net_amount=600.0, remarks="",
            items=[{
                "item_id": self.item_id, "pack_size": "10x10",
                "pay_qty": 12, "free_qty": 0, "batch_no": "BATCH-M",
                "expiry": "12/28", "rate": 50.0, "mrp": 60.0, "discount": 0,
                "gst_percent": 0, "gst_amount": 0, "amount": 600.0,
                "purchase_rate": 50.0, "net_rate": 50.0, "pp": 50.0,
            }],
        )
        CustomerReceiptDAO.insert_receipt({
            "receipt_date": "2026-02-03", "receipt_time": "",
            "customer_id": self.customer_id, "receipt_mode": "UPI",
            "amount": 150.0, "reference_no": "UPI-1", "remarks": "",
        })
        SupplierPaymentDAO.insert_payment({
            "payment_date": "2026-02-04", "payment_time": "",
            "supplier_id": self.supplier_id, "payment_mode": "Cheque",
            "amount": 220.0, "reference_no": "CHQ-1", "remarks": "",
        })
        JournalDAO.insert_entry(
            {"entry_date": "2026-02-05", "narration": "Mixed"},
            [
                {"ledger_id": self.cash_ledger["id"], "description": "",
                 "debit": 75.0, "credit": 0.0},
                {"ledger_id": self.bank_ledger["id"], "description": "",
                 "debit": 0.0, "credit": 75.0},
            ],
        )
        report = TrialBalanceDAO.get_trial_balance()
        self.assertTrue(report["totals"]["balanced"])
        self.assertEqual(report["totals"]["difference"], 0.0)
        self.assertGreater(report["totals"]["total_debit"], 0.0)


# ======================================================================
# 13-19: Ledger inclusion, zero balances, as-of dates
# ======================================================================

class TestInclusionAndFilters(_BaseTest):

    def test_13_system_ledgers_included(self):
        self._walkin_sale(amount=400.0)
        report = TrialBalanceDAO.get_trial_balance()
        ids = {r["ledger_id"] for r in report["rows"]}
        for led in (self.cash_ledger, self.bank_ledger, self.sales_ledger,
                    self.purchase_ledger, self.sales_return_ledger,
                    self.purchase_return_ledger):
            self.assertIn(led["id"], ids)
        # System ledgers are not excluded merely for having a system_role
        self.assertNotEqual(self._tb_row(report, self.cash_ledger["id"])["credit"], 0.0)
        self.assertNotEqual(self._tb_row(report, self.sales_ledger["id"])["credit"], 0.0)

    def test_14_customer_ledgers_included(self):
        report = TrialBalanceDAO.get_trial_balance()
        ids = {r["ledger_id"] for r in report["rows"]}
        self.assertIn(self.customer_ledger_id, ids)
        names = {r["ledger_name"] for r in report["rows"]}
        self.assertIn("Customer - TestCustomer", names)

    def test_15_supplier_ledgers_included(self):
        report = TrialBalanceDAO.get_trial_balance()
        ids = {r["ledger_id"] for r in report["rows"]}
        self.assertIn(self.supplier_ledger_id, ids)
        names = {r["ledger_name"] for r in report["rows"]}
        self.assertIn("Supplier - TestSupplier", names)

    def test_16_zero_balance_behavior(self):
        # Default: show all (Account Ledger convention)
        full = TrialBalanceDAO.get_trial_balance_filtered(include_zero=True)
        self.assertGreaterEqual(len(full["rows"]), 8)

        # Option: hide zero balances
        hidden = TrialBalanceDAO.get_trial_balance_filtered(include_zero=False)
        for r in hidden["rows"]:
            self.assertFalse(r["is_zero"])
        self.assertLess(len(hidden["rows"]), len(full["rows"]))

        # Totals unaffected by the filter
        self.assertEqual(hidden["totals"], full["totals"])

    def test_17_as_of_includes_earlier_transactions(self):
        JournalDAO.insert_entry(
            {"entry_date": "2026-01-10", "narration": "Early"},
            [
                {"ledger_id": self.cash_ledger["id"], "description": "",
                 "debit": 100.0, "credit": 0.0},
                {"ledger_id": self.sales_ledger["id"], "description": "",
                 "debit": 0.0, "credit": 100.0},
            ],
        )
        report = TrialBalanceDAO.get_trial_balance(as_of_date="2026-02-15")
        self.assertEqual(self._tb_row(report, self.cash_ledger["id"])["debit"], 100.0)

    def test_18_as_of_excludes_future_transactions(self):
        JournalDAO.insert_entry(
            {"entry_date": "2026-03-10", "narration": "Future"},
            [
                {"ledger_id": self.cash_ledger["id"], "description": "",
                 "debit": 900.0, "credit": 0.0},
                {"ledger_id": self.sales_ledger["id"], "description": "",
                 "debit": 0.0, "credit": 900.0},
            ],
        )
        report = TrialBalanceDAO.get_trial_balance(as_of_date="2026-02-15")
        self.assertTrue(self._tb_row(report, self.cash_ledger["id"])["is_zero"])
        self.assertTrue(self._tb_row(report, self.sales_ledger["id"])["is_zero"])
        # Without a filter everything is included
        full = TrialBalanceDAO.get_trial_balance()
        self.assertEqual(self._tb_row(full, self.cash_ledger["id"])["debit"], 900.0)

    def test_19_opening_balance_in_historical_as_of(self):
        lid = LedgerDAO.insert_ledger(
            "OB History", account_group="Sundry Debtors",
            opening_balance=500.0, opening_balance_type="Debit",
        )
        JournalDAO.insert_entry(
            {"entry_date": "2026-03-10", "narration": "Future txn"},
            [
                {"ledger_id": lid, "description": "",
                 "debit": 300.0, "credit": 0.0},
                {"ledger_id": self.cash_ledger["id"], "description": "",
                 "debit": 0.0, "credit": 300.0},
            ],
        )
        report = TrialBalanceDAO.get_trial_balance(as_of_date="2026-01-01")
        row = self._tb_row(report, lid)
        self.assertEqual(row["debit"], 500.0)  # opening only, future txn excluded
        self.assertFalse(row["is_zero"])


# ======================================================================
# 20-27: Invariant, agreement, reversals, edit, delete, coexistence
# ======================================================================

class TestInvariantAndLifecycle(_BaseTest):

    def test_20_total_debit_equals_total_credit(self):
        self._walkin_sale(amount=400.0)
        CustomerReceiptDAO.insert_receipt({
            "receipt_date": "2026-02-03", "receipt_time": "",
            "customer_id": self.customer_id, "receipt_mode": "Bank",
            "amount": 150.0, "reference_no": "", "remarks": "",
        })
        SupplierPaymentDAO.insert_payment({
            "payment_date": "2026-02-04", "payment_time": "",
            "supplier_id": self.supplier_id, "payment_mode": "Cash",
            "amount": 220.0, "reference_no": "", "remarks": "",
        })
        totals = TrialBalanceDAO.get_totals()
        self.assertEqual(totals["total_debit"], totals["total_credit"])
        self.assertEqual(totals["difference"], 0.0)
        self.assertTrue(totals["balanced"])

    def test_21_difference_calculated_correctly(self):
        # Opening debit 500 + opening credit 300 -> difference 200 unbalanced
        LedgerDAO.insert_ledger("DiffA", opening_balance=500.0,
                                opening_balance_type="Debit")
        LedgerDAO.insert_ledger("DiffB", opening_balance=300.0,
                                opening_balance_type="Credit")
        totals = TrialBalanceDAO.get_totals()
        self.assertEqual(totals["difference"], 200.0)
        self.assertFalse(totals["balanced"])

    def test_22_unbalanced_data_reported_not_fixed(self):
        # A raw unbalanced manual row (debit without credit)
        LedgerDAO.add_transaction({
            "ledger_id": self.cash_ledger["id"],
            "transaction_date": "2026-02-01", "transaction_time": "",
            "voucher_type": "MANUAL", "voucher_no": "M-0001",
            "description": "unbalanced", "debit": 137.25, "credit": 0.0,
        })
        conn = get_connection()
        try:
            before_count = conn.execute(
                "SELECT COUNT(*) FROM ledger_transactions"
            ).fetchone()[0]
        finally:
            conn.close()

        report = TrialBalanceDAO.get_trial_balance()
        self.assertFalse(report["totals"]["balanced"])
        self.assertEqual(report["totals"]["difference"], 137.25)
        self.assertFalse(TrialBalanceDAO.verify_balanced())

        # No artificial balancing entry was inserted
        conn = get_connection()
        try:
            after_count = conn.execute(
                "SELECT COUNT(*) FROM ledger_transactions"
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(after_count, before_count)

    def test_23_account_ledger_agrees_with_trial_balance(self):
        self._walkin_sale(amount=400.0)
        CustomerReceiptDAO.insert_receipt({
            "receipt_date": "2026-02-03", "receipt_time": "",
            "customer_id": self.customer_id, "receipt_mode": "Cash",
            "amount": 150.0, "reference_no": "", "remarks": "",
        })
        as_of = "2026-12-31"
        report = TrialBalanceDAO.get_trial_balance(as_of_date=as_of)
        for r in report["rows"]:
            bal = LedgerDAO.get_balance_as_of(r["ledger_id"], as_of)
            if r["debit"] > 0:
                self.assertEqual(bal["closing_balance"], r["debit"])
                self.assertEqual(bal["closing_balance_type"], "Debit")
            elif r["credit"] > 0:
                self.assertEqual(bal["closing_balance"], r["credit"])
                self.assertEqual(bal["closing_balance_type"], "Credit")
            else:
                self.assertEqual(bal["closing_balance"], 0.0)

    def test_24_reversal_rows_not_double_counted(self):
        rid = CustomerReceiptDAO.insert_receipt({
            "receipt_date": "2026-02-01", "receipt_time": "",
            "customer_id": self.customer_id, "receipt_mode": "Cash",
            "amount": 500.0, "reference_no": "", "remarks": "",
        })
        self.engine.reverse(SOURCE_CUSTOMER_RECEIPT, rid)
        report = TrialBalanceDAO.get_trial_balance()
        # 500 debit + 500 reversal credit on Cash -> net zero
        self.assertTrue(self._tb_row(report, self.cash_ledger["id"])["is_zero"])
        self.assertTrue(self._tb_row(report, self.customer_ledger_id)["is_zero"])
        self.assertEqual(report["totals"]["total_debit"], 0.0)
        self.assertEqual(report["totals"]["total_credit"], 0.0)

    def test_25_edited_transaction_current_net(self):
        rid = CustomerReceiptDAO.insert_receipt({
            "receipt_date": "2026-02-01", "receipt_time": "",
            "customer_id": self.customer_id, "receipt_mode": "Cash",
            "amount": 100.0, "reference_no": "", "remarks": "",
        })
        CustomerReceiptDAO.update_receipt(rid, {
            "receipt_date": "2026-02-02", "receipt_time": "",
            "customer_id": self.customer_id, "receipt_mode": "Cash",
            "amount": 250.0, "reference_no": "", "remarks": "edited",
        })
        report = TrialBalanceDAO.get_trial_balance()
        self.assertEqual(self._tb_row(report, self.cash_ledger["id"])["debit"], 250.0)
        self.assertEqual(self._tb_row(report, self.customer_ledger_id)["credit"], 250.0)
        self.assertTrue(report["totals"]["balanced"])

    def test_26_deleted_transaction_no_active_effect(self):
        rid = CustomerReceiptDAO.insert_receipt({
            "receipt_date": "2026-02-01", "receipt_time": "",
            "customer_id": self.customer_id, "receipt_mode": "Bank",
            "amount": 400.0, "reference_no": "", "remarks": "",
        })
        CustomerReceiptDAO.delete_receipt(rid)
        report = TrialBalanceDAO.get_trial_balance()
        self.assertTrue(self._tb_row(report, self.bank_ledger["id"])["is_zero"])
        self.assertTrue(self._tb_row(report, self.customer_ledger_id)["is_zero"])
        self.assertEqual(report["totals"]["difference"], 0.0)

    def test_27_multiple_source_types_coexist(self):
        self._walkin_sale(amount=400.0)
        CustomerReceiptDAO.insert_receipt({
            "receipt_date": "2026-02-03", "receipt_time": "",
            "customer_id": self.customer_id, "receipt_mode": "Cash",
            "amount": 150.0, "reference_no": "", "remarks": "",
        })
        SupplierPaymentDAO.insert_payment({
            "payment_date": "2026-02-04", "payment_time": "",
            "supplier_id": self.supplier_id, "payment_mode": "Bank",
            "amount": 220.0, "reference_no": "", "remarks": "",
        })
        PurchaseDAO.insert_invoice(
            voucher_no="PV-0009", voucher_date="2026-02-05", voucher_time="",
            purchase_type="Credit", supplier_id=self.supplier_id,
            invoice_no="INV-009", invoice_date="2026-02-05",
            invoice_net_amount=700.0, bill_discount=0, due_date="",
            total_amount=700.0, gst_amount=0, debit_note_amount=0,
            other_amount=0, paid_amount=0, round_off=0,
            net_amount=700.0, remarks="",
            items=[{
                "item_id": self.item_id, "pack_size": "10x10",
                "pay_qty": 14, "free_qty": 0, "batch_no": "BATCH-X",
                "expiry": "12/28", "rate": 50.0, "mrp": 60.0, "discount": 0,
                "gst_percent": 0, "gst_amount": 0, "amount": 700.0,
                "purchase_rate": 50.0, "net_rate": 50.0, "pp": 50.0,
            }],
        )
        report = TrialBalanceDAO.get_trial_balance()
        # Each type's posting is visible and the whole is still balanced
        self.assertEqual(self._tb_row(report, self.sales_ledger["id"])["credit"], 400.0)
        self.assertEqual(self._tb_row(report, self.purchase_ledger["id"])["debit"], 4700.0)
        self.assertTrue(report["totals"]["balanced"])


# ======================================================================
# 28-37: Multi-line, multi-transaction, system roles, persistence
# ======================================================================

class TestDetailChecks(_BaseTest):

    def test_28_multi_line_journal(self):
        je_id = JournalDAO.insert_entry(
            {"entry_date": "2026-02-01", "narration": "3-line JE"},
            [
                {"ledger_id": self.cash_ledger["id"], "description": "",
                 "debit": 100.0, "credit": 0.0},
                {"ledger_id": self.bank_ledger["id"], "description": "",
                 "debit": 200.0, "credit": 0.0},
                {"ledger_id": self.customer_ledger_id, "description": "",
                 "debit": 0.0, "credit": 300.0},
            ],
        )
        self.assertEqual(
            len(self.engine.get_posting_rows(SOURCE_JOURNAL_ENTRY, je_id)), 3
        )
        report = TrialBalanceDAO.get_trial_balance()
        self.assertEqual(self._tb_row(report, self.cash_ledger["id"])["debit"], 100.0)
        self.assertEqual(self._tb_row(report, self.bank_ledger["id"])["debit"], 200.0)
        self.assertEqual(self._tb_row(report, self.customer_ledger_id)["credit"], 300.0)
        self.assertTrue(report["totals"]["balanced"])

    def test_29_customer_ledger_multiple_transactions(self):
        # Sale (customer debit) + receipt (customer credit) + CN (credit)
        batch_id = self._seed_stock()
        bill_no = SalesDAO.generate_next_bill_no()
        SalesDAO.insert_invoice(
            bill_no=bill_no, sale_date="2026-02-01", sale_time="",
            sale_type="Credit", customer_id=self.customer_id,
            patient_name="", doctor_id=None, discount=0, paid_amount=0,
            total_amount=500.0, round_off=0, net_amount=500.0, remarks="",
            items=[{
                "item_id": self.item_id, "stock_batch_id": batch_id,
                "pack_size": "10x10", "location": "", "batch_no": "BATCH-A",
                "expiry": "12/27", "mrp": 50.0, "sale_qty": 10,
                "discount_amount": 0, "amount": 500.0,
            }],
        )
        CustomerReceiptDAO.insert_receipt({
            "receipt_date": "2026-02-02", "receipt_time": "",
            "customer_id": self.customer_id, "receipt_mode": "Cash",
            "amount": 200.0, "reference_no": "", "remarks": "",
        })
        CreditNoteDAO.insert_credit_note(
            {"voucher_date": "2026-02-03", "cn_date": "2026-02-03",
             "cn_type": "Customer", "customer_id": self.customer_id,
             "total_amount": 50.0, "ledger_amount": 50.0, "remarks": ""},
            [{
                "item_id": self.item_id, "stock_batch_id": batch_id,
                "batch_no": "BATCH-A", "expiry": "12/27",
                "pack_size": "10x10", "rate": 50, "mrp": 50,
                "return_qty": 1, "less_amount": 0, "amount": 50,
                "return_reason": "Damaged", "price_factor": 1.0,
            }],
        )
        report = TrialBalanceDAO.get_trial_balance()
        # 500 debit - 200 receipt - 50 CN = 250 debit
        self.assertEqual(self._tb_row(report, self.customer_ledger_id)["debit"], 250.0)
        self.assertTrue(report["totals"]["balanced"])

    def test_30_supplier_ledger_multiple_transactions(self):
        # Purchase (credit) + payment (debit) + DN (debit)
        PurchaseDAO.insert_invoice(
            voucher_no="PV-0001", voucher_date="2026-02-01", voucher_time="",
            purchase_type="Credit", supplier_id=self.supplier_id,
            invoice_no="INV-001", invoice_date="2026-02-01",
            invoice_net_amount=800.0, bill_discount=0, due_date="",
            total_amount=800.0, gst_amount=0, debit_note_amount=0,
            other_amount=0, paid_amount=0, round_off=0,
            net_amount=800.0, remarks="",
            items=[{
                "item_id": self.item_id, "pack_size": "10x10",
                "pay_qty": 16, "free_qty": 0, "batch_no": "BATCH-S",
                "expiry": "12/28", "rate": 50.0, "mrp": 60.0, "discount": 0,
                "gst_percent": 0, "gst_amount": 0, "amount": 800.0,
                "purchase_rate": 50.0, "net_rate": 50.0, "pp": 50.0,
            }],
        )
        SupplierPaymentDAO.insert_payment({
            "payment_date": "2026-02-02", "payment_time": "",
            "supplier_id": self.supplier_id, "payment_mode": "Cash",
            "amount": 300.0, "reference_no": "", "remarks": "",
        })
        DebitNoteDAO.insert_debit_note(
            {"voucher_date": "2026-02-03", "voucher_time": "",
             "dn_date": "2026-02-03", "dn_type": "Supplier",
             "supplier_id": self.supplier_id, "total_amount": 100.0,
             "ledger_amount": 100.0, "remarks": ""},
            [{
                "item_id": self.item_id,
                "stock_batch_id": StockDAO.get_stock_batches_for_item(self.item_id)[0]["id"],
                "batch_no": "BATCH-S", "expiry": "12/28",
                "pack_size": "10x10", "rate": 50, "mrp": 60,
                "return_qty": 2, "less_amount": 0, "amount": 100,
                "return_reason": "Expired", "price_factor": 1.0,
            }],
        )
        report = TrialBalanceDAO.get_trial_balance()
        # 800 credit - 300 payment - 100 DN = 400 credit
        self.assertEqual(self._tb_row(report, self.supplier_ledger_id)["credit"], 400.0)
        self.assertTrue(report["totals"]["balanced"])

    def test_31_cash_ledger(self):
        CustomerReceiptDAO.insert_receipt({
            "receipt_date": "2026-02-01", "receipt_time": "",
            "customer_id": self.customer_id, "receipt_mode": "Cash",
            "amount": 75.0, "reference_no": "", "remarks": "",
        })
        report = TrialBalanceDAO.get_trial_balance()
        self.assertEqual(self._tb_row(report, self.cash_ledger["id"])["debit"], 75.0)
        self.assertEqual(
            self._tb_row(report, self.cash_ledger["id"])["account_group"],
            self.cash_ledger["account_group"],
        )

    def test_32_bank_ledger(self):
        CustomerReceiptDAO.insert_receipt({
            "receipt_date": "2026-02-01", "receipt_time": "",
            "customer_id": self.customer_id, "receipt_mode": "UPI",
            "amount": 75.0, "reference_no": "", "remarks": "",
        })
        report = TrialBalanceDAO.get_trial_balance()
        self.assertEqual(self._tb_row(report, self.bank_ledger["id"])["debit"], 75.0)

    def test_33_sales_ledger(self):
        self._walkin_sale(amount=250.0)
        report = TrialBalanceDAO.get_trial_balance()
        self.assertEqual(self._tb_row(report, self.sales_ledger["id"])["credit"], 250.0)

    def test_34_purchase_ledger(self):
        self._seed_stock()
        report = TrialBalanceDAO.get_trial_balance()
        self.assertEqual(self._tb_row(report, self.purchase_ledger["id"])["debit"], 4000.0)

    def test_35_sales_return_ledger(self):
        batch_id = self._seed_stock()
        CreditNoteDAO.insert_credit_note(
            {"voucher_date": "2026-02-01", "cn_date": "2026-02-01",
             "cn_type": "Customer", "customer_id": self.customer_id,
             "total_amount": 80.0, "ledger_amount": 80.0, "remarks": ""},
            [{
                "item_id": self.item_id, "stock_batch_id": batch_id,
                "batch_no": "BATCH-A", "expiry": "12/27",
                "pack_size": "10x10", "rate": 40, "mrp": 50,
                "return_qty": 2, "less_amount": 0, "amount": 80,
                "return_reason": "Damaged", "price_factor": 1.0,
            }],
        )
        report = TrialBalanceDAO.get_trial_balance()
        self.assertEqual(self._tb_row(report, self.sales_return_ledger["id"])["debit"], 80.0)

    def test_36_purchase_return_ledger(self):
        batch_id = self._seed_stock()
        DebitNoteDAO.insert_debit_note(
            {"voucher_date": "2026-02-01", "voucher_time": "",
             "dn_date": "2026-02-01", "dn_type": "Supplier",
             "supplier_id": self.supplier_id, "total_amount": 120.0,
             "ledger_amount": 120.0, "remarks": ""},
            [{
                "item_id": self.item_id, "stock_batch_id": batch_id,
                "batch_no": "BATCH-A", "expiry": "12/27",
                "pack_size": "10x10", "rate": 40, "mrp": 50,
                "return_qty": 3, "less_amount": 0, "amount": 120,
                "return_reason": "Expired", "price_factor": 1.0,
            }],
        )
        report = TrialBalanceDAO.get_trial_balance()
        self.assertEqual(self._tb_row(report, self.purchase_return_ledger["id"])["credit"], 120.0)

    def test_37_restart_persistence(self):
        self._walkin_sale(amount=400.0)
        totals = TrialBalanceDAO.get_totals()

        # Simulate restart: brand-new connection reading committed state.
        # Raw transaction sums must balance (4400/4400: seed purchase
        # 4000 + sale 400 on each side)...
        fresh = sqlite3.connect(get_db_path())
        fresh.row_factory = sqlite3.Row
        try:
            row = fresh.execute(
                "SELECT COALESCE(SUM(debit), 0) AS d, COALESCE(SUM(credit), 0) AS c "
                "FROM ledger_transactions"
            ).fetchone()
        finally:
            fresh.close()

        self.assertEqual(round(row["d"], 2), round(row["c"], 2))
        # ...while closing totals net each ledger (CASH nets to 3600
        # credit, so totals are 4000/4000) and still balance.
        self.assertEqual(totals["total_debit"], totals["total_credit"])
        self.assertEqual(totals["total_debit"], 4000.0)
        # A fresh DAO call reads the same committed report
        again = TrialBalanceDAO.get_trial_balance()
        self.assertEqual(again["totals"], totals)


# ======================================================================
# 38-41: UI (dependency-skipped without PySide6; run in dev environment)
# ======================================================================

@unittest.skipUnless(HAS_PYSIDE6, _PYSIDE_SKIP_REASON)
class TestTrialBalanceUI(_BaseTest):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.app = QApplication.instance() or QApplication([])

    def test_38_page_opens(self):
        page = TrialBalancePage()
        self.assertIsNotNone(page)
        self.assertEqual(page._table.columnCount(), 4)
        self.assertEqual(page._table.horizontalHeaderItem(0).text(), "Ledger Name")
        self.assertEqual(page._table.horizontalHeaderItem(3).text(), "Credit")

    def test_39_generate_button_works(self):
        CustomerReceiptDAO.insert_receipt({
            "receipt_date": "2026-02-01", "receipt_time": "",
            "customer_id": self.customer_id, "receipt_mode": "Cash",
            "amount": 500.0, "reference_no": "", "remarks": "",
        })
        page = TrialBalancePage()
        page._on_generate()
        self.assertGreater(page._table.rowCount(), 0)
        self.assertIn("500.00", page._total_debit_lbl.text())
        self.assertIn("BALANCED", page._status_lbl.text())

    def test_40_as_of_date_filter_works(self):
        JournalDAO.insert_entry(
            {"entry_date": "2026-01-10", "narration": "Early"},
            [
                {"ledger_id": self.cash_ledger["id"], "description": "",
                 "debit": 100.0, "credit": 0.0},
                {"ledger_id": self.sales_ledger["id"], "description": "",
                 "debit": 0.0, "credit": 100.0},
            ],
        )
        JournalDAO.insert_entry(
            {"entry_date": "2026-03-10", "narration": "Future"},
            [
                {"ledger_id": self.cash_ledger["id"], "description": "",
                 "debit": 900.0, "credit": 0.0},
                {"ledger_id": self.sales_ledger["id"], "description": "",
                 "debit": 0.0, "credit": 900.0},
            ],
        )
        from PySide6.QtCore import QDate
        page = TrialBalancePage()
        page.as_of_edit.setDate(QDate(2026, 2, 15))
        page._on_generate()
        self.assertIn("100.00", page._total_debit_lbl.text())
        # Include the future entry by widening the date
        page.as_of_edit.setDate(QDate(2026, 12, 31))
        page._on_generate()
        self.assertIn("1,000.00", page._total_debit_lbl.text())

    def test_41_zero_balance_toggle_works(self):
        page = TrialBalancePage()
        page.zero_check.setChecked(True)
        page._on_generate()
        with_all = page._table.rowCount()

        page.zero_check.setChecked(False)
        page._on_generate()
        without_zero = page._table.rowCount()

        # Fresh DB: every ledger is zero -> all rows hidden when unchecked
        self.assertGreater(with_all, 0)
        self.assertEqual(without_zero, 0)


# ======================================================================
# 42-50: Regression — existing modules still work
# ======================================================================

class TestRegression(_BaseTest):

    def test_42_account_ledger_works(self):
        led = LedgerDAO.insert_ledger("TB Reg Ledger", account_group="Reg")
        got = LedgerDAO.get_ledger_by_id(led)
        self.assertEqual(got["ledger_name"], "TB Reg Ledger")
        bal = LedgerDAO.get_balance(led)
        self.assertEqual(bal["closing_balance"], 0.0)

    def test_43_journal_entry_works(self):
        je_id = JournalDAO.insert_entry(
            {"entry_date": "2026-02-01", "narration": "Reg"},
            [
                {"ledger_id": self.cash_ledger["id"], "description": "",
                 "debit": 10.0, "credit": 0.0},
                {"ledger_id": self.bank_ledger["id"], "description": "",
                 "debit": 0.0, "credit": 10.0},
            ],
        )
        self.assertGreater(je_id, 0)
        self.assertEqual(len(JournalDAO.get_items(je_id)), 2)

    def test_44_customer_receipt_works(self):
        rid = CustomerReceiptDAO.insert_receipt({
            "receipt_date": "2026-02-01", "receipt_time": "",
            "customer_id": self.customer_id, "receipt_mode": "Cash",
            "amount": 20.0, "reference_no": "", "remarks": "",
        })
        self.assertGreater(rid, 0)
        self.assertEqual(CustomerReceiptDAO.get_by_id(rid)["amount"], 20.0)

    def test_45_supplier_payment_works(self):
        pid = SupplierPaymentDAO.insert_payment({
            "payment_date": "2026-02-01", "payment_time": "",
            "supplier_id": self.supplier_id, "payment_mode": "Cash",
            "amount": 30.0, "reference_no": "", "remarks": "",
        })
        self.assertGreater(pid, 0)
        self.assertEqual(SupplierPaymentDAO.get_by_id(pid)["amount"], 30.0)

    def test_46_counter_sale_works(self):
        sid = self._walkin_sale(amount=250.0)
        self.assertGreater(sid, 0)
        self.assertEqual(SalesDAO.get_by_id(sid)["net_amount"], 250.0)

    def test_47_purchase_works(self):
        inv_id = self._seed_stock()
        self.assertGreater(inv_id, 0)
        self.assertEqual(PurchaseDAO.get_by_id(inv_id)["net_amount"], 4000.0)

    def test_48_credit_note_works(self):
        batch_id = self._seed_stock()
        cn_id = CreditNoteDAO.insert_credit_note(
            {"voucher_date": "2026-02-01", "cn_date": "2026-02-01",
             "cn_type": "Customer", "customer_id": self.customer_id,
             "total_amount": 40.0, "ledger_amount": 40.0, "remarks": ""},
            [{
                "item_id": self.item_id, "stock_batch_id": batch_id,
                "batch_no": "BATCH-A", "expiry": "12/27",
                "pack_size": "10x10", "rate": 40, "mrp": 50,
                "return_qty": 1, "less_amount": 0, "amount": 40,
                "return_reason": "", "price_factor": 1.0,
            }],
        )
        self.assertGreater(cn_id, 0)
        self.assertEqual(CreditNoteDAO.get_by_id(cn_id)["total_amount"], 40.0)

    def test_49_debit_note_works(self):
        batch_id = self._seed_stock()
        dn_id = DebitNoteDAO.insert_debit_note(
            {"voucher_date": "2026-02-01", "voucher_time": "",
             "dn_date": "2026-02-01", "dn_type": "Supplier",
             "supplier_id": self.supplier_id, "total_amount": 60.0,
             "ledger_amount": 60.0, "remarks": ""},
            [{
                "item_id": self.item_id, "stock_batch_id": batch_id,
                "batch_no": "BATCH-A", "expiry": "12/27",
                "pack_size": "10x10", "rate": 40, "mrp": 50,
                "return_qty": 1.5, "less_amount": 0, "amount": 60,
                "return_reason": "", "price_factor": 1.0,
            }],
        )
        self.assertGreater(dn_id, 0)
        self.assertEqual(DebitNoteDAO.get_by_id(dn_id)["total_amount"], 60.0)

    def test_50_all_master_pages_data_work(self):
        self.assertGreater(len(CompanyDAO.get_all()), 0)
        self.assertGreater(len(UnitDAO.get_all()), 0)
        self.assertGreater(len(DrugDAO.get_all()), 0)
        self.assertGreater(len(SupplierDAO.get_all()), 0)
        self.assertGreater(len(CustomerDAO.get_all()), 0)
        self.assertGreater(len(DoctorDAO.get_all()), 0)
        self.assertGreater(len(ItemDAO.get_all()), 0)
        self.assertGreater(len(LedgerDAO.get_all_ledgers()), 0)
        self.assertIsNotNone(LedgerDAO.get_by_system_role(ROLE_CASH))
        # The full report still balances after all the regression activity
        self.assertTrue(TrialBalanceDAO.verify_balanced())


if __name__ == "__main__":
    unittest.main(verbosity=2)
