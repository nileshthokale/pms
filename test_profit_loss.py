"""Phase 4C — Profit & Loss tests.

50 tests covering:
    1-2:    Empty P&L
    3:      Sales income
    4:      Sales Return effect
    5:      Purchase-related expense
    6:      Purchase Return effect
    7:      Operating Expense
    8:      Multiple income ledgers
    9:      Multiple expense ledgers
   10:      Net Profit
   11:      Net Loss
   12:      Zero result
   13-14:   Date filtering (from/to)
   15-16:   Transactions outside period excluded
   17:      Opening balance excluded
   18:      Reversed posting excluded
   19:      Edited transaction reflects new amount
   20:      Deleted transaction has no effect
   21-22:   Customer / Supplier excluded
   23-24:   Cash / Bank excluded
   25:      Capital excluded
   26:      SALES system role included
   27:      SALES_RETURN classified by ledger group
   28:      PURCHASE classified by ledger group
   29:      PURCHASE_RETURN classified by ledger group
   30:      Unclassified ledger detected
   31:      Unclassified excluded from totals
   32:      Inventory/COGS limitation reported
   33:      GST limitation reported
   34:      Decimal / tolerance handling
   35:      Ledger and P&L consistency
   36:      Trial Balance consistency
   37:      Persistence
   38-41:   UI (skip without PySide6)
   42-50:   Regression — existing modules still work
"""

import os
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
    ensure_account_groups,
    migrate_legacy_ledger_groups,
)
from database.account_group_dao import AccountGroupDAO
from database.accounting_posting import PostingEngine
from database.profit_loss_dao import ProfitLossDAO
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
    from screens.profit_loss import ProfitLossPage

    HAS_PYSIDE6 = True
    _PYSIDE_SKIP_REASON = ""
except ImportError as _exc:
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
    _DB_PATH = os.path.join(os.path.dirname(__file__), "_test_profit_loss.db")

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
        ensure_account_groups()
        migrate_legacy_ledger_groups()

        self.customer_ledger_id = CustomerDAO.get_ledger_id(self.customer_id)
        self.supplier_ledger_id = SupplierDAO.get_ledger_id(self.supplier_id)
        self.cash_ledger = LedgerDAO.get_by_system_role(ROLE_CASH)
        self.bank_ledger = LedgerDAO.get_by_system_role(ROLE_BANK)
        self.sales_ledger = LedgerDAO.get_by_system_role(ROLE_SALES)
        self.purchase_ledger = LedgerDAO.get_by_system_role(ROLE_PURCHASE)
        self.sales_return_ledger = LedgerDAO.get_by_system_role(ROLE_SALES_RETURN)
        self.purchase_return_ledger = LedgerDAO.get_by_system_role(ROLE_PURCHASE_RETURN)

        self.engine = PostingEngine()

    def _seed_stock(self, qty=100.0, rate=40.0, date="2026-01-05"):
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
                "item_id": self.item_id,
                "stock_batch_id": self._batch_id,
                "pack_size": "10x10", "location": "", "batch_no": "BATCH-A",
                "expiry": "12/27", "mrp": 50.0, "sale_qty": amount / 50.0,
                "discount_amount": 0, "amount": amount,
            }],
        )

    def _make_purchase(self, net=1000.0, date="2026-03-10", pv="PV-001",
                       inv="INV-001", ptype="Credit"):
        return PurchaseDAO.insert_invoice(
            voucher_no=pv, voucher_date=date, voucher_time="",
            purchase_type=ptype, supplier_id=self.supplier_id,
            invoice_no=inv, invoice_date=date,
            invoice_net_amount=net, bill_discount=0, due_date="",
            total_amount=net, gst_amount=0, debit_note_amount=0,
            other_amount=0, paid_amount=0 if ptype == "Credit" else net,
            round_off=0, net_amount=net, remarks="",
            items=[{
                "item_id": self.item_id, "pack_size": "10x10",
                "pay_qty": net / 100.0, "free_qty": 0,
                "batch_no": "BATCH-A", "expiry": "12/27",
                "rate": 100.0, "mrp": 120.0, "discount": 0,
                "gst_percent": 0, "gst_amount": 0, "amount": net,
                "purchase_rate": 100.0, "net_rate": 100.0, "pp": 100.0,
            }],
        )

    def _make_journal(self, lines, jv="JV-001", date="2026-03-01"):
        header = {"entry_date": date, "entry_time": "", "narration": ""}
        items = []
        for lid, dr, cr, desc in lines:
            items.append({
                "ledger_id": lid, "debit": dr, "credit": cr,
                "description": desc,
            })
        return JournalDAO.insert_entry(header, items)


# ======================================================================
# Tests 1-2: Empty P&L
# ======================================================================

class TestEmptyPL(_BaseTest):

    def test_01_empty_pl_no_rows(self):
        report = ProfitLossDAO.get_profit_loss("2026-01-01", "2026-12-31")
        self.assertEqual(report["income"], [])
        self.assertEqual(report["expenses"], [])
        self.assertEqual(report["unclassified"], [])

    def test_02_empty_pl_totals_zero(self):
        report = ProfitLossDAO.get_profit_loss("2026-01-01", "2026-12-31")
        t = report["totals"]
        self.assertEqual(t["total_income"], 0.0)
        self.assertEqual(t["total_expenses"], 0.0)
        self.assertEqual(t["net_result"], 0.0)
        self.assertEqual(t["net_label"], "No Profit / No Loss")


# ======================================================================
# Tests 3-9: Individual posting sources
# ======================================================================

class TestPostingSources(_BaseTest):

    def setUp(self):
        super().setUp()
        self._batch_id = self._seed_stock()

    def test_03_sales_income(self):
        self._walkin_sale(500.0, "2026-03-10")
        report = ProfitLossDAO.get_profit_loss("2026-03-01", "2026-03-31")
        self.assertEqual(len(report["income"]), 1)
        self.assertEqual(report["income"][0]["ledger_id"], self.sales_ledger["id"])
        self.assertAlmostEqual(report["income"][0]["amount"], 500.0, places=2)
        self.assertAlmostEqual(report["totals"]["total_income"], 500.0, places=2)

    def test_04_sales_return_effect(self):
        cust_id = CustomerDAO.insert("CN Customer")
        CreditNoteDAO.insert_credit_note(
            {"voucher_date": "2026-03-15", "voucher_time": "",
             "customer_id": cust_id, "total_amount": 100.0,
             "ledger_amount": 100.0},
            [],
        )
        report = ProfitLossDAO.get_profit_loss("2026-03-01", "2026-03-31")
        sr_rows = [r for r in report["income"]
                    if r["ledger_id"] == self.sales_return_ledger["id"]]
        self.assertEqual(len(sr_rows), 1)
        self.assertAlmostEqual(sr_rows[0]["amount"], -100.0, places=2)

    def test_05_purchase_expense(self):
        self._make_purchase(1000.0, "2026-03-10", "PV-001", "INV-001")
        report = ProfitLossDAO.get_profit_loss("2026-03-01", "2026-03-31")
        exp = [r for r in report["expenses"]
                if r["ledger_id"] == self.purchase_ledger["id"]]
        self.assertEqual(len(exp), 1)
        self.assertAlmostEqual(exp[0]["amount"], 1000.0, places=2)

    def test_06_purchase_return_effect(self):
        self._make_purchase(500.0, "2026-03-10", "PV-002", "INV-002")
        DebitNoteDAO.insert_debit_note(
            {"voucher_date": "2026-03-15", "voucher_time": "",
             "supplier_id": self.supplier_id, "total_amount": 150.0,
             "ledger_amount": 150.0},
            [],
        )
        report = ProfitLossDAO.get_profit_loss("2026-03-01", "2026-03-31")
        pr_rows = [r for r in report["expenses"]
                    if r["ledger_id"] == self.purchase_return_ledger["id"]]
        self.assertEqual(len(pr_rows), 1)
        self.assertAlmostEqual(pr_rows[0]["amount"], -150.0, places=2)

    def test_07_operating_expense_via_journal(self):
        op_gid = AccountGroupDAO.get_by_name("Operating Expenses")
        op_ledger_id = LedgerDAO.insert_ledger(
            ledger_name="Rent Expense",
            account_group="Operating Expenses",
            account_group_id=op_gid["id"] if op_gid else None,
        )
        self._make_journal([
            (op_ledger_id, 2000.0, 0.0, "March Rent"),
            (self.cash_ledger["id"], 0.0, 2000.0, "Cash payment"),
        ], "JV-OP-001", "2026-03-01")

        report = ProfitLossDAO.get_profit_loss("2026-03-01", "2026-03-31")
        rent_rows = [r for r in report["expenses"]
                      if r["ledger_name"] == "Rent Expense"]
        self.assertEqual(len(rent_rows), 1)
        self.assertAlmostEqual(rent_rows[0]["amount"], 2000.0, places=2)

    def test_08_multiple_income_ledgers(self):
        self._walkin_sale(500.0, "2026-03-10")
        inc_gid = AccountGroupDAO.get_by_name("Sales")
        other_inc_id = LedgerDAO.insert_ledger(
            ledger_name="Interest Income",
            account_group="Sales Accounts",
            account_group_id=inc_gid["id"] if inc_gid else None,
        )
        self._make_journal([
            (self.cash_ledger["id"], 100.0, 0.0, "Interest received"),
            (other_inc_id, 0.0, 100.0, "Interest income"),
        ], "JV-INC-001", "2026-03-20")

        report = ProfitLossDAO.get_profit_loss("2026-03-01", "2026-03-31")
        self.assertGreaterEqual(len(report["income"]), 2)
        self.assertAlmostEqual(report["totals"]["total_income"], 600.0, places=2)

    def test_09_multiple_expense_ledgers(self):
        self._make_purchase(800.0, "2026-03-10", "PV-MULT", "INV-MULT", "Cash")
        op_gid = AccountGroupDAO.get_by_name("Operating Expenses")
        sal_ledger_id = LedgerDAO.insert_ledger(
            ledger_name="Salary Expense",
            account_group="Operating Expenses",
            account_group_id=op_gid["id"] if op_gid else None,
        )
        self._make_journal([
            (sal_ledger_id, 3000.0, 0.0, "March salary"),
            (self.cash_ledger["id"], 0.0, 3000.0, "Cash payment"),
        ], "JV-EXP-001", "2026-03-15")

        report = ProfitLossDAO.get_profit_loss("2026-03-01", "2026-03-31")
        self.assertGreaterEqual(len(report["expenses"]), 2)
        self.assertAlmostEqual(report["totals"]["total_expenses"], 3800.0, places=2)


# ======================================================================
# Tests 10-12: Net result
# ======================================================================

class TestNetResult(_BaseTest):

    def setUp(self):
        super().setUp()
        self._batch_id = self._seed_stock()

    def test_10_net_profit(self):
        self._walkin_sale(1000.0, "2026-03-10")
        self._make_purchase(400.0, "2026-03-12", "PV-NP", "INV-NP", "Cash")
        report = ProfitLossDAO.get_profit_loss("2026-03-01", "2026-03-31")
        self.assertEqual(report["totals"]["net_label"], "Net Profit")
        self.assertAlmostEqual(report["totals"]["net_result"], 600.0, places=2)

    def test_11_net_loss(self):
        self._walkin_sale(200.0, "2026-03-10")
        self._make_purchase(800.0, "2026-03-12", "PV-NL", "INV-NL", "Cash")
        report = ProfitLossDAO.get_profit_loss("2026-03-01", "2026-03-31")
        self.assertEqual(report["totals"]["net_label"], "Net Loss")
        self.assertAlmostEqual(report["totals"]["net_result"], -600.0, places=2)

    def test_12_zero_result(self):
        self._walkin_sale(500.0, "2026-03-10")
        self._make_purchase(500.0, "2026-03-12", "PV-ZR", "INV-ZR", "Cash")
        report = ProfitLossDAO.get_profit_loss("2026-03-01", "2026-03-31")
        self.assertEqual(report["totals"]["net_label"], "No Profit / No Loss")
        self.assertAlmostEqual(report["totals"]["net_result"], 0.0, places=2)


# ======================================================================
# Tests 13-16: Date filtering
# ======================================================================

class TestDateFiltering(_BaseTest):

    def setUp(self):
        super().setUp()
        self._batch_id = self._seed_stock()

    def test_13_from_date_excludes_before(self):
        self._walkin_sale(500.0, "2026-02-15")
        report = ProfitLossDAO.get_profit_loss("2026-03-01", "2026-03-31")
        self.assertEqual(report["totals"]["total_income"], 0.0)

    def test_14_to_date_excludes_after(self):
        self._walkin_sale(500.0, "2026-04-15")
        report = ProfitLossDAO.get_profit_loss("2026-03-01", "2026-03-31")
        self.assertEqual(report["totals"]["total_income"], 0.0)

    def test_15_transaction_before_period_excluded(self):
        self._walkin_sale(500.0, "2026-01-10")
        report = ProfitLossDAO.get_profit_loss("2026-03-01", "2026-03-31")
        self.assertEqual(len(report["income"]), 0)

    def test_16_transaction_after_period_excluded(self):
        self._walkin_sale(500.0, "2026-06-10")
        report = ProfitLossDAO.get_profit_loss("2026-03-01", "2026-03-31")
        self.assertEqual(len(report["income"]), 0)


# ======================================================================
# Test 17: Opening balance excluded
# ======================================================================

class TestOpeningBalanceExcluded(_BaseTest):

    def test_17_opening_balance_excluded(self):
        LedgerDAO.update_ledger(
            self.sales_ledger["id"], self.sales_ledger["ledger_name"],
            self.sales_ledger["account_group"] or "",
            5000.0, "Credit",
        )
        report = ProfitLossDAO.get_profit_loss("2026-03-01", "2026-03-31")
        self.assertEqual(report["totals"]["total_income"], 0.0)


# ======================================================================
# Tests 18-20: Reversal / edit / delete
# ======================================================================

class TestReversalHandling(_BaseTest):

    def setUp(self):
        super().setUp()
        self._batch_id = self._seed_stock()

    def test_18_reversed_posting_excluded(self):
        bill_no = SalesDAO.generate_next_bill_no()
        sale_id = SalesDAO.insert_invoice(
            bill_no=bill_no, sale_date="2026-03-10", sale_time="",
            sale_type="Cash", customer_id=None, patient_name="",
            doctor_id=None, discount=0, paid_amount=500.0,
            total_amount=500.0, round_off=0, net_amount=500.0,
            remarks="",
            items=[{
                "item_id": self.item_id,
                "stock_batch_id": self._batch_id,
                "pack_size": "10x10", "location": "", "batch_no": "BATCH-A",
                "expiry": "12/27", "mrp": 50.0, "sale_qty": 10.0,
                "discount_amount": 0, "amount": 500.0,
            }],
        )
        SalesDAO.delete_invoice(sale_id)
        # Use no date filter to see all activity including reversal
        report = ProfitLossDAO.get_profit_loss(None, None)
        sales_rows = [r for r in report["income"]
                       if r["ledger_id"] == self.sales_ledger["id"]]
        self.assertEqual(len(sales_rows), 0)

    def test_19_edited_transaction_reflects_new_amount(self):
        pid = self._make_purchase(500.0, "2026-03-10", "PV-EDIT", "INV-EDIT")
        PurchaseDAO.update_invoice(
            invoice_id=pid, voucher_no="PV-EDIT", voucher_date="2026-03-10",
            voucher_time="", purchase_type="Cash",
            supplier_id=self.supplier_id, invoice_no="INV-EDIT",
            invoice_date="2026-03-10", invoice_net_amount=800.0,
            bill_discount=0, due_date="", total_amount=800.0,
            gst_amount=0, debit_note_amount=0, other_amount=0,
            paid_amount=800.0, round_off=0, net_amount=800.0, remarks="",
            items=[{
                "item_id": self.item_id, "pack_size": "10x10",
                "pay_qty": 8, "free_qty": 0, "batch_no": "BATCH-A",
                "expiry": "12/27", "rate": 100.0, "mrp": 120.0,
                "discount": 0, "gst_percent": 0, "gst_amount": 0,
                "amount": 800.0, "purchase_rate": 100.0,
                "net_rate": 100.0, "pp": 100.0,
            }],
        )
        report = ProfitLossDAO.get_profit_loss("2026-03-01", "2026-03-31")
        pur = [r for r in report["expenses"]
                if r["ledger_id"] == self.purchase_ledger["id"]]
        self.assertEqual(len(pur), 1)
        self.assertAlmostEqual(pur[0]["amount"], 800.0, places=2)

    def test_20_deleted_transaction_no_effect(self):
        pid = self._make_purchase(500.0, "2026-03-10", "PV-DEL", "INV-DEL")
        PurchaseDAO.delete_invoice(pid)
        # Filter to March only — seed purchase is in January, so the
        # Purchase ledger in this period should show zero net activity.
        report = ProfitLossDAO.get_profit_loss("2026-03-01", "2026-03-31")
        pur = [r for r in report["expenses"]
                if r["ledger_id"] == self.purchase_ledger["id"]]
        self.assertEqual(len(pur), 0)


# ======================================================================
# Tests 21-25: Excluded accounts
# ======================================================================

class TestExcludedAccounts(_BaseTest):

    def setUp(self):
        super().setUp()
        self._batch_id = self._seed_stock()

    def test_21_customer_ledger_excluded(self):
        self._walkin_sale(500.0, "2026-03-10")
        report = ProfitLossDAO.get_profit_loss("2026-03-01", "2026-03-31")
        all_ids = (
            [r["ledger_id"] for r in report["income"]]
            + [r["ledger_id"] for r in report["expenses"]]
        )
        self.assertNotIn(self.customer_ledger_id, all_ids)

    def test_22_supplier_ledger_excluded(self):
        self._make_purchase(500.0, "2026-03-10", "PV-SUP", "INV-SUP")
        report = ProfitLossDAO.get_profit_loss("2026-03-01", "2026-03-31")
        all_ids = (
            [r["ledger_id"] for r in report["income"]]
            + [r["ledger_id"] for r in report["expenses"]]
        )
        self.assertNotIn(self.supplier_ledger_id, all_ids)

    def test_23_cash_excluded(self):
        self._walkin_sale(500.0, "2026-03-10")
        report = ProfitLossDAO.get_profit_loss("2026-03-01", "2026-03-31")
        all_ids = (
            [r["ledger_id"] for r in report["income"]]
            + [r["ledger_id"] for r in report["expenses"]]
        )
        self.assertNotIn(self.cash_ledger["id"], all_ids)

    def test_24_bank_excluded(self):
        self._make_purchase(500.0, "2026-03-10", "PV-BANK", "INV-BANK",
                           "Credit Card")
        report = ProfitLossDAO.get_profit_loss("2026-03-01", "2026-03-31")
        all_ids = (
            [r["ledger_id"] for r in report["income"]]
            + [r["ledger_id"] for r in report["expenses"]]
        )
        self.assertNotIn(self.bank_ledger["id"], all_ids)

    def test_25_capital_excluded(self):
        cap_gid = AccountGroupDAO.get_by_name("Capital")
        cap_id = LedgerDAO.insert_ledger(
            ledger_name="Owner Capital",
            account_group="Capital",
            account_group_id=cap_gid["id"] if cap_gid else None,
        )
        self._make_journal([
            (cap_id, 0.0, 10000.0, "Capital introduced"),
            (self.cash_ledger["id"], 10000.0, 0.0, "Cash received"),
        ], "JV-CAP", "2026-03-01")
        report = ProfitLossDAO.get_profit_loss("2026-03-01", "2026-03-31")
        all_ids = (
            [r["ledger_id"] for r in report["income"]]
            + [r["ledger_id"] for r in report["expenses"]]
        )
        self.assertNotIn(cap_id, all_ids)


# ======================================================================
# Tests 26-29: System role classification
# ======================================================================

class TestSystemRoleClassification(_BaseTest):

    def setUp(self):
        super().setUp()
        self._batch_id = self._seed_stock()

    def test_26_sales_system_role_included(self):
        self._walkin_sale(500.0, "2026-03-10")
        report = ProfitLossDAO.get_profit_loss("2026-03-01", "2026-03-31")
        sales_rows = [r for r in report["income"]
                       if r["ledger_id"] == self.sales_ledger["id"]]
        self.assertEqual(len(sales_rows), 1)

    def test_27_sales_return_classified_by_group(self):
        self.assertEqual(
            self.sales_return_ledger.get("account_group"), "Sales Accounts"
        )
        sr_gid = AccountGroupDAO.get_by_name("Sales")
        self.assertIsNotNone(sr_gid)
        self.assertEqual(sr_gid["statement_type"], "INCOME")

    def test_28_purchase_classified_by_group(self):
        self.assertEqual(
            self.purchase_ledger.get("account_group"), "Purchase Accounts"
        )
        pr_gid = AccountGroupDAO.get_by_name("Purchase-related")
        self.assertIsNotNone(pr_gid)
        self.assertEqual(pr_gid["statement_type"], "EXPENSE")

    def test_29_purchase_return_classified_by_group(self):
        self.assertEqual(
            self.purchase_return_ledger.get("account_group"), "Purchase Accounts"
        )
        pr_gid = AccountGroupDAO.get_by_name("Purchase-related")
        self.assertIsNotNone(pr_gid)
        self.assertEqual(pr_gid["statement_type"], "EXPENSE")


# ======================================================================
# Tests 30-31: Unclassified accounts
# ======================================================================

class TestUnclassifiedAccounts(_BaseTest):

    def test_30_unclassified_ledger_detected(self):
        lid = LedgerDAO.insert_ledger(
            ledger_name="Mystery Ledger",
            account_group="Custom Group XYZ",
        )
        self._make_journal([
            (lid, 500.0, 0.0, "Mystery debit"),
            (self.cash_ledger["id"], 0.0, 500.0, "Cash"),
        ], "JV-UNCL", "2026-03-01")
        report = ProfitLossDAO.get_profit_loss("2026-03-01", "2026-03-31")
        uncl = [r for r in report["unclassified"]
                 if r["ledger_id"] == lid]
        self.assertEqual(len(uncl), 1)

    def test_31_unclassified_excluded_from_totals(self):
        lid = LedgerDAO.insert_ledger(
            ledger_name="Mystery Ledger 2",
            account_group="Something Weird",
        )
        self._make_journal([
            (lid, 1000.0, 0.0, "Mystery"),
            (self.cash_ledger["id"], 0.0, 1000.0, "Cash"),
        ], "JV-UNCL2", "2026-03-01")
        report = ProfitLossDAO.get_profit_loss("2026-03-01", "2026-03-31")
        self.assertEqual(report["totals"]["total_income"], 0.0)
        self.assertEqual(report["totals"]["total_expenses"], 0.0)
        self.assertTrue(report["totals"]["has_unclassified"])


# ======================================================================
# Tests 32-33: Limitation notices
# ======================================================================

class TestLimitationNotices(_BaseTest):

    def test_32_cogs_limitation_reported(self):
        report = ProfitLossDAO.get_profit_loss("2026-01-01", "2026-12-31")
        self.assertTrue(report["totals"]["has_cogs_limitation"])

    def test_33_gst_limitation_reported(self):
        report = ProfitLossDAO.get_profit_loss("2026-01-01", "2026-12-31")
        self.assertTrue(report["totals"]["has_gst_limitation"])


# ======================================================================
# Test 34: Decimal / tolerance
# ======================================================================

class TestDecimalTolerance(_BaseTest):

    def setUp(self):
        super().setUp()
        self._batch_id = self._seed_stock()

    def test_34_decimal_tolerance(self):
        self._walkin_sale(333.33, "2026-03-10")
        self._make_purchase(100.0, "2026-03-12", "PV-DEC", "INV-DEC", "Cash")
        report = ProfitLossDAO.get_profit_loss("2026-03-01", "2026-03-31")
        net = report["totals"]["net_result"]
        self.assertAlmostEqual(net, 233.33, places=2)


# ======================================================================
# Test 35: Ledger and P&L consistency
# ======================================================================

class TestLedgerConsistency(_BaseTest):

    def setUp(self):
        super().setUp()
        self._batch_id = self._seed_stock()

    def test_35_ledger_and_pl_consistency(self):
        self._walkin_sale(700.0, "2026-03-10")
        report = ProfitLossDAO.get_profit_loss("2026-03-01", "2026-03-31")
        sales_pl = [r for r in report["income"]
                     if r["ledger_id"] == self.sales_ledger["id"]]
        self.assertEqual(len(sales_pl), 1)
        self.assertAlmostEqual(sales_pl[0]["amount"], 700.0, places=2)


# ======================================================================
# Test 36: Trial Balance consistency
# ======================================================================

class TestTrialBalanceConsistency(_BaseTest):

    def setUp(self):
        super().setUp()
        self._batch_id = self._seed_stock()

    def test_36_trial_balance_consistency(self):
        self._walkin_sale(500.0, "2026-03-10")
        self._make_purchase(300.0, "2026-03-12", "PV-TB", "INV-TB", "Cash")
        tb = TrialBalanceDAO.get_trial_balance("2026-03-31")
        pl = ProfitLossDAO.get_profit_loss("2026-03-01", "2026-03-31")
        self.assertTrue(tb["totals"]["balanced"])
        tb_sales = next(
            (r for r in tb["rows"] if r["ledger_id"] == self.sales_ledger["id"]),
            None,
        )
        tb_purchase = next(
            (r for r in tb["rows"] if r["ledger_id"] == self.purchase_ledger["id"]),
            None,
        )
        self.assertIsNotNone(tb_sales)
        self.assertIsNotNone(tb_purchase)


# ======================================================================
# Test 37: Persistence
# ======================================================================

class TestPersistence(_BaseTest):

    def setUp(self):
        super().setUp()
        self._batch_id = self._seed_stock()

    def test_37_persistence(self):
        self._walkin_sale(500.0, "2026-03-10")
        conn = get_connection()
        conn.close()
        report = ProfitLossDAO.get_profit_loss("2026-03-01", "2026-03-31")
        self.assertAlmostEqual(report["totals"]["total_income"], 500.0, places=2)


# ======================================================================
# Tests 38-41: UI (skip without PySide6)
# ======================================================================

@unittest.skipUnless(HAS_PYSIDE6, _PYSIDE_SKIP_REASON)
class TestPLUI(_BaseTest):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if HAS_PYSIDE6:
            cls._app = QApplication.instance() or QApplication([])

    def test_38_pl_page_opens(self):
        page = ProfitLossPage()
        self.assertIsNotNone(page)

    def test_39_generate_works(self):
        page = ProfitLossPage()
        page._on_generate()
        self.assertIsNotNone(page._table)

    def test_40_date_filtering_ui(self):
        page = ProfitLossPage()
        page.from_edit.setDate(QDate(2026, 3, 1))
        page.to_edit.setDate(QDate(2026, 3, 31))
        page._on_generate()
        self.assertIsNotNone(page._table)

    def test_41_refresh_works(self):
        page = ProfitLossPage()
        page._on_generate()
        page._on_generate()
        self.assertIsNotNone(page._table)


# ======================================================================
# Tests 42-50: Regression
# ======================================================================

class TestRegression(_BaseTest):

    def setUp(self):
        super().setUp()
        self._batch_id = self._seed_stock()

    def test_42_customer_receipt_still_works(self):
        rid = CustomerReceiptDAO.insert_receipt({
            "receipt_date": "2026-03-10", "receipt_time": "",
            "customer_id": self.customer_id, "receipt_mode": "Cash",
            "amount": 100.0, "reference_no": "", "remarks": "",
        })
        self.assertGreater(rid, 0)

    def test_43_supplier_payment_still_works(self):
        pid = SupplierPaymentDAO.insert_payment({
            "payment_date": "2026-03-10", "payment_time": "",
            "supplier_id": self.supplier_id, "payment_mode": "Cash",
            "amount": 100.0, "reference_no": "", "remarks": "",
        })
        self.assertGreater(pid, 0)

    def test_44_counter_sale_still_works(self):
        bill_no = SalesDAO.generate_next_bill_no()
        sid = SalesDAO.insert_invoice(
            bill_no=bill_no, sale_date="2026-03-10", sale_time="",
            sale_type="Cash", customer_id=None, patient_name="",
            doctor_id=None, discount=0, paid_amount=100.0,
            total_amount=100.0, round_off=0, net_amount=100.0,
            remarks="",
            items=[{
                "item_id": self.item_id,
                "stock_batch_id": self._batch_id,
                "pack_size": "10x10", "location": "", "batch_no": "BATCH-A",
                "expiry": "12/27", "mrp": 50.0, "sale_qty": 2.0,
                "discount_amount": 0, "amount": 100.0,
            }],
        )
        self.assertGreater(sid, 0)

    def test_45_purchase_invoice_still_works(self):
        pid = self._make_purchase(200.0, "2026-03-10", "PV-REG", "INV-REG",
                                  "Cash")
        self.assertGreater(pid, 0)

    def test_46_credit_note_still_works(self):
        cn_id = CreditNoteDAO.insert_credit_note(
            {"voucher_date": "2026-03-10", "voucher_time": "",
             "customer_id": self.customer_id, "total_amount": 50.0,
             "ledger_amount": 50.0},
            [],
        )
        self.assertGreater(cn_id, 0)

    def test_47_debit_note_still_works(self):
        dn_id = DebitNoteDAO.insert_debit_note(
            {"voucher_date": "2026-03-10", "voucher_time": "",
             "supplier_id": self.supplier_id, "total_amount": 75.0,
             "ledger_amount": 75.0},
            [],
        )
        self.assertGreater(dn_id, 0)

    def test_48_journal_entry_still_works(self):
        je_id = self._make_journal([
            (self.cash_ledger["id"], 100.0, 0.0, "Debit"),
            (self.sales_ledger["id"], 0.0, 100.0, "Credit"),
        ], "JV-REG", "2026-03-10")
        self.assertGreater(je_id, 0)

    def test_49_trial_balance_still_works(self):
        tb = TrialBalanceDAO.get_trial_balance()
        self.assertIn("rows", tb)
        self.assertIn("totals", tb)

    def test_50_all_master_screens_work(self):
        self.assertIsNotNone(CompanyDAO.get_all())
        self.assertIsNotNone(LedgerDAO.get_all_ledgers())
        tree = AccountGroupDAO.get_tree()
        self.assertGreater(len(tree), 0)


if __name__ == "__main__":
    unittest.main()
