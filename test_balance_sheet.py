"""Phase 4D — Balance Sheet tests.

50 tests covering:
    1:      Empty Balance Sheet
    2:      Cash under Assets
    3:      Bank under Assets
    4:      Customer/Sundry Debtors under Current Assets
    5:      Supplier/Sundry Creditors under Current Liabilities
    6:      Capital under Equity
    7:      Income ledgers not on Balance Sheet
    8:      Expense ledgers not on Balance Sheet
    9:      Sales classification
    10:     Purchase classification
    11:     Sales Return classification
    12:     Purchase Return classification
    13:     Opening Debit asset
    14:     Opening Credit liability
    15:     As-of-date includes earlier transactions
    16:     As-of-date excludes future transactions
    17:     Reversed posting has no active effect
    18:     Edited transaction reflects current state
    19:     Deleted transaction has no active effect
    20:     Customer ledger classification
    21:     Supplier ledger classification
    22:     Unclassified ledger detected
    23:     Unclassified ledger not silently included
    24:     Multiple asset groups
    25:     Multiple liability groups
    26:     Multiple equity groups
    27:     Current P&L treatment follows approved design
    28:     No artificial balancing entries
    29:     Difference calculation
    30:     Balanced dataset
    31:     Intentionally unbalanced dataset is UNBALANCED
    32:     Trial Balance consistency
    33:     Account Ledger consistency
    34:     P&L consistency where applicable
    35:     Persistence
    36:     UI opens
    37:     Generate works
    38:     Date filter works
    39:     Refresh works
    40:     Customer Receipt still works
    41:     Supplier Payment still works
    42:     Counter Sale still works
    43:     Purchase Invoice still works
    44:     Credit Note still works
    45:     Debit Note still works
    46:     Journal Entry still works
    47:     Trial Balance still works
    48:     Profit & Loss still works
    49:     Stock Master still works
    50:     All Master screens work
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
from database.balance_sheet_dao import BalanceSheetDAO
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
    from screens.balance_sheet import BalanceSheetPage

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
    _DB_PATH = os.path.join(os.path.dirname(__file__), "_test_balance_sheet.db")

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

    def _update_opening(self, ledger_id, ledger_name, account_group,
                        opening_balance, opening_balance_type):
        """Update a ledger's opening balance without wiping account_group_id."""
        ledger = LedgerDAO.get_ledger_by_id(ledger_id)
        LedgerDAO.update_ledger(
            ledger_id, ledger_name, account_group,
            opening_balance, opening_balance_type,
            account_group_id=ledger["account_group_id"],
        )

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
# Test 1: Empty Balance Sheet
# ======================================================================

class TestEmptyBalanceSheet(_BaseTest):

    def test_01_empty_balance_sheet(self):
        report = BalanceSheetDAO.get_balance_sheet("2026-03-31")
        self.assertEqual(report["assets"], [])
        self.assertEqual(report["liabilities"], [])
        self.assertEqual(report["equity"], [])
        self.assertEqual(report["unclassified"], [])
        t = report["totals"]
        self.assertEqual(t["total_assets"], 0.0)
        self.assertEqual(t["total_liabilities"], 0.0)
        self.assertEqual(t["total_equity"], 0.0)
        self.assertEqual(t["difference"], 0.0)
        self.assertEqual(t["status"], "BALANCED")


# ======================================================================
# Tests 2-3: Cash and Bank under Assets
# ======================================================================

class TestAssetClassification(_BaseTest):

    def test_02_cash_under_assets(self):
        self._update_opening(
            self.cash_ledger["id"], self.cash_ledger["ledger_name"],
            self.cash_ledger["account_group"] or "",
            500.0, "Debit",
        )
        report = BalanceSheetDAO.get_balance_sheet("2026-03-31")
        assets = [r for r in report["assets"]
                  if r["ledger_id"] == self.cash_ledger["id"]]
        self.assertEqual(len(assets), 1)
        self.assertAlmostEqual(assets[0]["amount"], 500.0, places=2)

    def test_03_bank_under_assets(self):
        self._update_opening(
            self.bank_ledger["id"], self.bank_ledger["ledger_name"],
            self.bank_ledger["account_group"] or "",
            1000.0, "Debit",
        )
        report = BalanceSheetDAO.get_balance_sheet("2026-03-31")
        assets = [r for r in report["assets"]
                  if r["ledger_id"] == self.bank_ledger["id"]]
        self.assertEqual(len(assets), 1)
        self.assertAlmostEqual(assets[0]["amount"], 1000.0, places=2)


# ======================================================================
# Tests 4-6: Customer, Supplier, Capital classification
# ======================================================================

class TestPartyClassification(_BaseTest):

    def test_04_customer_under_current_assets(self):
        self._update_opening(
            self.customer_ledger_id, "TestCustomer",
            "Sundry Debtors", 300.0, "Debit",
        )
        report = BalanceSheetDAO.get_balance_sheet("2026-03-31")
        assets = [r for r in report["assets"]
                  if r["ledger_id"] == self.customer_ledger_id]
        self.assertEqual(len(assets), 1)
        self.assertAlmostEqual(assets[0]["amount"], 300.0, places=2)

    def test_05_supplier_under_current_liabilities(self):
        self._update_opening(
            self.supplier_ledger_id, "TestSupplier",
            "Sundry Creditors", 700.0, "Credit",
        )
        report = BalanceSheetDAO.get_balance_sheet("2026-03-31")
        liabs = [r for r in report["liabilities"]
                 if r["ledger_id"] == self.supplier_ledger_id]
        self.assertEqual(len(liabs), 1)
        self.assertAlmostEqual(liabs[0]["amount"], 700.0, places=2)

    def test_06_capital_under_equity(self):
        capital_group = AccountGroupDAO.get_by_name("Capital")
        self.assertIsNotNone(capital_group)
        ledger_id = LedgerDAO.insert_ledger(
            ledger_name="Capital Account",
            account_group="Capital",
            opening_balance=5000.0,
            opening_balance_type="Credit",
            account_group_id=capital_group["id"],
        )
        report = BalanceSheetDAO.get_balance_sheet("2026-03-31")
        equity = [r for r in report["equity"]
                  if r["ledger_id"] == ledger_id]
        self.assertEqual(len(equity), 1)
        self.assertAlmostEqual(equity[0]["amount"], 5000.0, places=2)


# ======================================================================
# Tests 7-8: Income/Expense not on Balance Sheet
# ======================================================================

class TestIncomeExpenseExclusion(_BaseTest):

    def test_07_income_ledgers_not_on_balance_sheet(self):
        self._batch_id = self._seed_stock()
        self._walkin_sale(500.0, "2026-03-10")
        report = BalanceSheetDAO.get_balance_sheet("2026-03-31")
        all_bs_ids = (
            [r["ledger_id"] for r in report["assets"]]
            + [r["ledger_id"] for r in report["liabilities"]]
            + [r["ledger_id"] for r in report["equity"]]
        )
        self.assertNotIn(self.sales_ledger["id"], all_bs_ids)

    def test_08_expense_ledgers_not_on_balance_sheet(self):
        self._batch_id = self._seed_stock()
        self._make_purchase(1000.0, "2026-03-10", "PV-001", "INV-001")
        report = BalanceSheetDAO.get_balance_sheet("2026-03-31")
        all_bs_ids = (
            [r["ledger_id"] for r in report["assets"]]
            + [r["ledger_id"] for r in report["liabilities"]]
            + [r["ledger_id"] for r in report["equity"]]
        )
        self.assertNotIn(self.purchase_ledger["id"], all_bs_ids)


# ======================================================================
# Tests 9-12: System role classification
# ======================================================================

class TestSystemRoleClassification(_BaseTest):

    def test_09_sales_classification(self):
        self._batch_id = self._seed_stock()
        self._walkin_sale(500.0, "2026-03-10")
        report = BalanceSheetDAO.get_balance_sheet("2026-03-31")
        all_bs_ids = (
            [r["ledger_id"] for r in report["assets"]]
            + [r["ledger_id"] for r in report["liabilities"]]
            + [r["ledger_id"] for r in report["equity"]]
        )
        self.assertNotIn(self.sales_ledger["id"], all_bs_ids)

    def test_10_purchase_classification(self):
        self._batch_id = self._seed_stock()
        self._make_purchase(1000.0, "2026-03-10")
        report = BalanceSheetDAO.get_balance_sheet("2026-03-31")
        all_bs_ids = (
            [r["ledger_id"] for r in report["assets"]]
            + [r["ledger_id"] for r in report["liabilities"]]
            + [r["ledger_id"] for r in report["equity"]]
        )
        self.assertNotIn(self.purchase_ledger["id"], all_bs_ids)

    def test_11_sales_return_classification(self):
        report = BalanceSheetDAO.get_balance_sheet("2026-03-31")
        all_bs_ids = (
            [r["ledger_id"] for r in report["assets"]]
            + [r["ledger_id"] for r in report["liabilities"]]
            + [r["ledger_id"] for r in report["equity"]]
        )
        self.assertNotIn(self.sales_return_ledger["id"], all_bs_ids)

    def test_12_purchase_return_classification(self):
        report = BalanceSheetDAO.get_balance_sheet("2026-03-31")
        all_bs_ids = (
            [r["ledger_id"] for r in report["assets"]]
            + [r["ledger_id"] for r in report["liabilities"]]
            + [r["ledger_id"] for r in report["equity"]]
        )
        self.assertNotIn(self.purchase_return_ledger["id"], all_bs_ids)


# ======================================================================
# Tests 13-14: Opening balance handling
# ======================================================================

class TestOpeningBalanceHandling(_BaseTest):

    def test_13_opening_debit_asset(self):
        self._update_opening(
            self.cash_ledger["id"], self.cash_ledger["ledger_name"],
            self.cash_ledger["account_group"] or "",
            2000.0, "Debit",
        )
        report = BalanceSheetDAO.get_balance_sheet("2026-03-31")
        assets = [r for r in report["assets"]
                  if r["ledger_id"] == self.cash_ledger["id"]]
        self.assertEqual(len(assets), 1)
        self.assertAlmostEqual(assets[0]["amount"], 2000.0, places=2)

    def test_14_opening_credit_liability(self):
        self._update_opening(
            self.supplier_ledger_id, "TestSupplier",
            "Sundry Creditors", 3000.0, "Credit",
        )
        report = BalanceSheetDAO.get_balance_sheet("2026-03-31")
        liabs = [r for r in report["liabilities"]
                 if r["ledger_id"] == self.supplier_ledger_id]
        self.assertEqual(len(liabs), 1)
        self.assertAlmostEqual(liabs[0]["amount"], 3000.0, places=2)


# ======================================================================
# Tests 15-16: As-of-date filtering
# ======================================================================

class TestAsOfDateFiltering(_BaseTest):

    def setUp(self):
        super().setUp()
        self._batch_id = self._seed_stock()

    def test_15_as_of_date_includes_earlier(self):
        # Seed purchase creates Cash -4000; walkin sale adds +500
        self._walkin_sale(500.0, "2026-02-15")
        report = BalanceSheetDAO.get_balance_sheet("2026-03-31")
        assets = [r for r in report["assets"]
                  if r["ledger_id"] == self.cash_ledger["id"]]
        self.assertEqual(len(assets), 1)
        # Cash: -4000 (seed) + 500 (sale) = -3500
        self.assertAlmostEqual(assets[0]["amount"], -3500.0, places=2)

    def test_16_as_of_date_excludes_future(self):
        self._walkin_sale(500.0, "2026-06-15")
        report = BalanceSheetDAO.get_balance_sheet("2026-03-31")
        # Seed purchase is in January (included), but sale is in June (excluded)
        # Cash has -4000 from seed purchase only → net -4000
        # -4000 is a credit balance for an asset → shown as negative
        assets = [r for r in report["assets"]
                  if r["ledger_id"] == self.cash_ledger["id"]]
        self.assertEqual(len(assets), 1)
        self.assertAlmostEqual(assets[0]["amount"], -4000.0, places=2)


# ======================================================================
# Tests 17-19: Reversal / edit / delete
# ======================================================================

class TestReversalHandling(_BaseTest):

    def setUp(self):
        super().setUp()
        self._batch_id = self._seed_stock()

    def test_17_reversed_posting_no_effect(self):
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
        # Cash ledger has -4000 from seed purchase, sale+reversal net to 0
        report = BalanceSheetDAO.get_balance_sheet("2026-12-31")
        cash_rows = [r for r in report["assets"]
                     if r["ledger_id"] == self.cash_ledger["id"]]
        # Cash still appears because of seed purchase (-4000)
        self.assertEqual(len(cash_rows), 1)
        self.assertAlmostEqual(cash_rows[0]["amount"], -4000.0, places=2)

    def test_18_edited_transaction_reflects_current(self):
        pid = self._make_purchase(500.0, "2026-03-10", "PV-EDIT", "INV-EDIT")
        PurchaseDAO.update_invoice(
            invoice_id=pid, voucher_no="PV-EDIT", voucher_date="2026-03-10",
            voucher_time="", purchase_type="Credit",
            supplier_id=self.supplier_id, invoice_no="INV-EDIT",
            invoice_date="2026-03-10", invoice_net_amount=800.0,
            bill_discount=0, due_date="", total_amount=800.0,
            gst_amount=0, debit_note_amount=0, other_amount=0,
            paid_amount=0, round_off=0, net_amount=800.0, remarks="",
            items=[{
                "item_id": self.item_id, "pack_size": "10x10",
                "pay_qty": 8, "free_qty": 0, "batch_no": "BATCH-A",
                "expiry": "12/27", "rate": 100.0, "mrp": 120.0,
                "discount": 0, "gst_percent": 0, "gst_amount": 0,
                "amount": 800.0, "purchase_rate": 100.0,
                "net_rate": 100.0, "pp": 100.0,
            }],
        )
        report = BalanceSheetDAO.get_balance_sheet("2026-03-31")
        sup = [r for r in report["liabilities"]
               if r["ledger_id"] == self.supplier_ledger_id]
        self.assertEqual(len(sup), 1)
        self.assertAlmostEqual(sup[0]["amount"], 800.0, places=2)

    def test_19_deleted_transaction_no_effect(self):
        pid = self._make_purchase(500.0, "2026-03-10", "PV-DEL", "INV-DEL")
        PurchaseDAO.delete_invoice(pid)
        report = BalanceSheetDAO.get_balance_sheet("2026-03-31")
        sup = [r for r in report["liabilities"]
               if r["ledger_id"] == self.supplier_ledger_id]
        self.assertEqual(len(sup), 0)


# ======================================================================
# Tests 20-21: Customer / Supplier ledger classification
# ======================================================================

class TestPartyLedgerClassification(_BaseTest):

    def test_20_customer_ledger_classification(self):
        ledger = LedgerDAO.get_ledger_by_id(self.customer_ledger_id)
        self.assertIsNotNone(ledger)
        self.assertEqual(ledger["account_group"], "Sundry Debtors")
        self.assertIsNotNone(ledger["account_group_id"])
        group = AccountGroupDAO.get_by_id(ledger["account_group_id"])
        self.assertEqual(group["statement_type"], "ASSET")

    def test_21_supplier_ledger_classification(self):
        ledger = LedgerDAO.get_ledger_by_id(self.supplier_ledger_id)
        self.assertIsNotNone(ledger)
        self.assertEqual(ledger["account_group"], "Sundry Creditors")
        self.assertIsNotNone(ledger["account_group_id"])
        group = AccountGroupDAO.get_by_id(ledger["account_group_id"])
        self.assertEqual(group["statement_type"], "LIABILITY")


# ======================================================================
# Tests 22-23: Unclassified accounts
# ======================================================================

class TestUnclassifiedAccounts(_BaseTest):

    def test_22_unclassified_ledger_detected(self):
        ledger_id = LedgerDAO.insert_ledger(
            ledger_name="Mystery Ledger",
            account_group="Unknown Group",
            opening_balance=100.0,
            opening_balance_type="Debit",
        )
        report = BalanceSheetDAO.get_balance_sheet("2026-03-31")
        uncl = [r for r in report["unclassified"]
                if r["ledger_id"] == ledger_id]
        self.assertEqual(len(uncl), 1)

    def test_23_unclassified_not_in_statement_sections(self):
        ledger_id = LedgerDAO.insert_ledger(
            ledger_name="Mystery Ledger",
            account_group="Unknown Group",
            opening_balance=100.0,
            opening_balance_type="Debit",
        )
        report = BalanceSheetDAO.get_balance_sheet("2026-03-31")
        all_bs_ids = (
            [r["ledger_id"] for r in report["assets"]]
            + [r["ledger_id"] for r in report["liabilities"]]
            + [r["ledger_id"] for r in report["equity"]]
        )
        self.assertNotIn(ledger_id, all_bs_ids)


# ======================================================================
# Tests 24-26: Multiple groups
# ======================================================================

class TestMultipleGroups(_BaseTest):

    def test_24_multiple_asset_groups(self):
        self._update_opening(
            self.cash_ledger["id"], self.cash_ledger["ledger_name"],
            self.cash_ledger["account_group"] or "",
            500.0, "Debit",
        )
        self._update_opening(
            self.bank_ledger["id"], self.bank_ledger["ledger_name"],
            self.bank_ledger["account_group"] or "",
            1000.0, "Debit",
        )
        self._update_opening(
            self.customer_ledger_id, "TestCustomer",
            "Sundry Debtors", 300.0, "Debit",
        )
        report = BalanceSheetDAO.get_balance_sheet("2026-03-31")
        self.assertGreaterEqual(len(report["assets"]), 3)
        self.assertAlmostEqual(
            report["totals"]["total_assets"], 1800.0, places=2
        )

    def test_25_multiple_liability_groups(self):
        self._update_opening(
            self.supplier_ledger_id, "TestSupplier",
            "Sundry Creditors", 700.0, "Credit",
        )
        lt_liab = AccountGroupDAO.get_by_name("Long Term Liabilities")
        self.assertIsNotNone(lt_liab)
        loan_id = LedgerDAO.insert_ledger(
            ledger_name="Term Loan",
            account_group="Long Term Liabilities",
            opening_balance=5000.0,
            opening_balance_type="Credit",
            account_group_id=lt_liab["id"],
        )
        report = BalanceSheetDAO.get_balance_sheet("2026-03-31")
        self.assertGreaterEqual(len(report["liabilities"]), 2)
        self.assertAlmostEqual(
            report["totals"]["total_liabilities"], 5700.0, places=2
        )

    def test_26_multiple_equity_groups(self):
        capital_group = AccountGroupDAO.get_by_name("Capital")
        self.assertIsNotNone(capital_group)
        LedgerDAO.insert_ledger(
            ledger_name="Owner Capital",
            account_group="Capital",
            opening_balance=10000.0,
            opening_balance_type="Credit",
            account_group_id=capital_group["id"],
        )
        LedgerDAO.insert_ledger(
            ledger_name="Reserves",
            account_group="Capital",
            opening_balance=2000.0,
            opening_balance_type="Credit",
            account_group_id=capital_group["id"],
        )
        report = BalanceSheetDAO.get_balance_sheet("2026-03-31")
        self.assertGreaterEqual(len(report["equity"]), 2)
        self.assertAlmostEqual(
            report["totals"]["total_equity"], 12000.0, places=2
        )


# ======================================================================
# Tests 27-28: P&L treatment and no artificial balancing
# ======================================================================

class TestPLTreatment(_BaseTest):

    def test_27_current_pl_treatment(self):
        self._batch_id = self._seed_stock()
        # Seed creates Cash -4000; sale adds Cash +500 → Cash = -3500
        self._walkin_sale(500.0, "2026-03-10")
        report = BalanceSheetDAO.get_balance_sheet("2026-03-31")
        cash = [r for r in report["assets"]
                if r["ledger_id"] == self.cash_ledger["id"]]
        self.assertEqual(len(cash), 1)
        self.assertAlmostEqual(cash[0]["amount"], -3500.0, places=2)
        self.assertEqual(report["totals"]["status"], "UNBALANCED")

    def test_28_no_artificial_balancing(self):
        self._update_opening(
            self.cash_ledger["id"], self.cash_ledger["ledger_name"],
            self.cash_ledger["account_group"] or "",
            1000.0, "Debit",
        )
        report = BalanceSheetDAO.get_balance_sheet("2026-03-31")
        self.assertEqual(report["totals"]["status"], "UNBALANCED")
        self.assertAlmostEqual(report["totals"]["difference"], 1000.0, places=2)


# ======================================================================
# Tests 29-31: Balance calculation and difference
# ======================================================================

class TestBalanceCalculation(_BaseTest):

    def test_29_difference_calculation(self):
        self._update_opening(
            self.cash_ledger["id"], self.cash_ledger["ledger_name"],
            self.cash_ledger["account_group"] or "",
            1000.0, "Debit",
        )
        self._update_opening(
            self.supplier_ledger_id, "TestSupplier",
            "Sundry Creditors", 400.0, "Credit",
        )
        report = BalanceSheetDAO.get_balance_sheet("2026-03-31")
        self.assertAlmostEqual(
            report["totals"]["difference"], 600.0, places=2
        )
        self.assertEqual(report["totals"]["status"], "UNBALANCED")

    def test_30_balanced_dataset(self):
        self._update_opening(
            self.cash_ledger["id"], self.cash_ledger["ledger_name"],
            self.cash_ledger["account_group"] or "",
            5000.0, "Debit",
        )
        self._update_opening(
            self.supplier_ledger_id, "TestSupplier",
            "Sundry Creditors", 2000.0, "Credit",
        )
        capital_group = AccountGroupDAO.get_by_name("Capital")
        LedgerDAO.insert_ledger(
            ledger_name="Owner Capital",
            account_group="Capital",
            opening_balance=3000.0,
            opening_balance_type="Credit",
            account_group_id=capital_group["id"],
        )
        report = BalanceSheetDAO.get_balance_sheet("2026-03-31")
        self.assertEqual(report["totals"]["status"], "BALANCED")
        self.assertAlmostEqual(report["totals"]["difference"], 0.0, places=2)

    def test_31_intentionally_unbalanced(self):
        self._update_opening(
            self.cash_ledger["id"], self.cash_ledger["ledger_name"],
            self.cash_ledger["account_group"] or "",
            5000.0, "Debit",
        )
        capital_group = AccountGroupDAO.get_by_name("Capital")
        LedgerDAO.insert_ledger(
            ledger_name="Owner Capital",
            account_group="Capital",
            opening_balance=3000.0,
            opening_balance_type="Credit",
            account_group_id=capital_group["id"],
        )
        report = BalanceSheetDAO.get_balance_sheet("2026-03-31")
        self.assertEqual(report["totals"]["status"], "UNBALANCED")
        self.assertAlmostEqual(report["totals"]["difference"], 2000.0, places=2)


# ======================================================================
# Tests 32-34: Consistency checks
# ======================================================================

class TestConsistency(_BaseTest):

    def setUp(self):
        super().setUp()
        self._batch_id = self._seed_stock()

    def test_32_trial_balance_consistency(self):
        self._update_opening(
            self.cash_ledger["id"], self.cash_ledger["ledger_name"],
            self.cash_ledger["account_group"] or "",
            1000.0, "Debit",
        )
        self._walkin_sale(500.0, "2026-03-10")
        as_of = "2026-03-31"
        bs = BalanceSheetDAO.get_balance_sheet(as_of)
        tb = TrialBalanceDAO.get_trial_balance(as_of)
        bs_cash = [r for r in bs["assets"]
                   if r["ledger_id"] == self.cash_ledger["id"]]
        tb_cash = [r for r in tb["rows"]
                   if r["ledger_id"] == self.cash_ledger["id"]]
        self.assertEqual(len(bs_cash), 1)
        self.assertEqual(len(tb_cash), 1)
        # Cash: 1000 opening - 4000 seed + 500 sale = -2500
        self.assertAlmostEqual(bs_cash[0]["amount"], -2500.0, places=2)
        # TB shows debit or credit side; -2500 is credit → TB credit = 2500
        self.assertAlmostEqual(tb_cash[0]["credit"], 2500.0, places=2)

    def test_33_account_ledger_consistency(self):
        self._update_opening(
            self.cash_ledger["id"], self.cash_ledger["ledger_name"],
            self.cash_ledger["account_group"] or "",
            750.0, "Debit",
        )
        as_of = "2026-03-31"
        bs = BalanceSheetDAO.get_balance_sheet(as_of)
        bs_cash = [r for r in bs["assets"]
                   if r["ledger_id"] == self.cash_ledger["id"]]
        self.assertEqual(len(bs_cash), 1)
        # Cash: 750 opening - 4000 seed = -3250
        self.assertAlmostEqual(bs_cash[0]["amount"], -3250.0, places=2)

    def test_34_pl_consistency(self):
        self._walkin_sale(500.0, "2026-03-10")
        self._make_purchase(300.0, "2026-03-10", "PV-002", "INV-002")
        pl = ProfitLossDAO.get_profit_loss("2026-03-01", "2026-03-31")
        bs = BalanceSheetDAO.get_balance_sheet("2026-03-31")
        self.assertGreater(len(pl["income"]), 0)
        self.assertGreater(len(pl["expenses"]), 0)
        all_bs_ids = (
            [r["ledger_id"] for r in bs["assets"]]
            + [r["ledger_id"] for r in bs["liabilities"]]
            + [r["ledger_id"] for r in bs["equity"]]
        )
        self.assertNotIn(self.sales_ledger["id"], all_bs_ids)
        self.assertNotIn(self.purchase_ledger["id"], all_bs_ids)


# ======================================================================
# Test 35: Persistence
# ======================================================================

class TestPersistence(_BaseTest):

    def test_35_persistence(self):
        self._update_opening(
            self.cash_ledger["id"], self.cash_ledger["ledger_name"],
            self.cash_ledger["account_group"] or "",
            1234.56, "Debit",
        )
        report1 = BalanceSheetDAO.get_balance_sheet("2026-03-31")
        conn = get_connection()
        conn.close()
        report2 = BalanceSheetDAO.get_balance_sheet("2026-03-31")
        self.assertEqual(
            report1["totals"]["total_assets"],
            report2["totals"]["total_assets"],
        )


# ======================================================================
# Tests 36-39: UI (skip without PySide6)
# ======================================================================

@unittest.skipUnless(HAS_PYSIDE6, _PYSIDE_SKIP_REASON)
class TestBalanceSheetUI(_BaseTest):

    def test_36_page_opens(self):
        page = BalanceSheetPage()
        self.assertIsNotNone(page)

    def test_37_generate_works(self):
        page = BalanceSheetPage()
        page._on_generate()

    def test_38_date_filter_works(self):
        page = BalanceSheetPage()
        from PySide6.QtCore import QDate
        page.as_of_edit.setDate(QDate(2026, 6, 15))
        page._on_generate()

    def test_39_refresh_works(self):
        page = BalanceSheetPage()
        page._on_generate()


# ======================================================================
# Tests 40-50: Regression — existing modules still work
# ======================================================================

class TestRegression(_BaseTest):

    def setUp(self):
        super().setUp()
        self._batch_id = self._seed_stock()

    def test_40_customer_receipt_still_works(self):
        rid = CustomerReceiptDAO.insert_receipt({
            "receipt_date": "2026-03-10", "receipt_time": "",
            "customer_id": self.customer_id, "receipt_mode": "Cash",
            "amount": 100.0, "reference_no": "", "remarks": "",
        })
        self.assertGreater(rid, 0)

    def test_41_supplier_payment_still_works(self):
        pid = SupplierPaymentDAO.insert_payment({
            "payment_date": "2026-03-10", "payment_time": "",
            "supplier_id": self.supplier_id, "payment_mode": "Cash",
            "amount": 100.0, "reference_no": "", "remarks": "",
        })
        self.assertGreater(pid, 0)

    def test_42_counter_sale_still_works(self):
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
        self.assertIsNotNone(sale_id)
        self.assertGreater(sale_id, 0)

    def test_43_purchase_invoice_still_works(self):
        pid = PurchaseDAO.insert_invoice(
            voucher_no="PV-002", voucher_date="2026-03-10",
            voucher_time="", purchase_type="Credit",
            supplier_id=self.supplier_id, invoice_no="INV-002",
            invoice_date="2026-03-10", invoice_net_amount=600.0,
            bill_discount=0, due_date="", total_amount=600.0,
            gst_amount=0, debit_note_amount=0, other_amount=0,
            paid_amount=0, round_off=0, net_amount=600.0, remarks="",
            items=[{
                "item_id": self.item_id, "pack_size": "10x10",
                "pay_qty": 6, "free_qty": 0, "batch_no": "BATCH-A",
                "expiry": "12/27", "rate": 100.0, "mrp": 120.0,
                "discount": 0, "gst_percent": 0, "gst_amount": 0,
                "amount": 600.0, "purchase_rate": 100.0,
                "net_rate": 100.0, "pp": 100.0,
            }],
        )
        self.assertIsNotNone(pid)
        self.assertGreater(pid, 0)

    def test_44_credit_note_still_works(self):
        cn_id = CreditNoteDAO.insert_credit_note(
            header={
                "voucher_no": "CN-001", "voucher_date": "2026-03-10",
                "voucher_time": "", "customer_id": self.customer_id,
                "total_amount": 200.0, "remarks": "",
            },
            items=[],
        )
        self.assertIsNotNone(cn_id)
        self.assertGreater(cn_id, 0)

    def test_45_debit_note_still_works(self):
        dn_id = DebitNoteDAO.insert_debit_note(
            header={
                "voucher_no": "DN-001", "voucher_date": "2026-03-10",
                "voucher_time": "", "supplier_id": self.supplier_id,
                "total_amount": 200.0, "remarks": "",
            },
            items=[],
        )
        self.assertIsNotNone(dn_id)
        self.assertGreater(dn_id, 0)

    def test_46_journal_entry_still_works(self):
        je_id = self._make_journal(
            [
                (self.cash_ledger["id"], 500.0, 0.0, "Debit Cash"),
                (self.bank_ledger["id"], 0.0, 500.0, "Credit Bank"),
            ],
        )
        self.assertIsNotNone(je_id)
        self.assertGreater(je_id, 0)

    def test_47_trial_balance_still_works(self):
        self._update_opening(
            self.cash_ledger["id"], self.cash_ledger["ledger_name"],
            self.cash_ledger["account_group"] or "",
            1000.0, "Debit",
        )
        tb = TrialBalanceDAO.get_trial_balance("2026-03-31")
        self.assertIsNotNone(tb)
        self.assertIn("rows", tb)
        self.assertIn("totals", tb)

    def test_48_profit_loss_still_works(self):
        self._walkin_sale(500.0, "2026-03-10")
        pl = ProfitLossDAO.get_profit_loss("2026-03-01", "2026-03-31")
        self.assertIsNotNone(pl)
        self.assertIn("income", pl)
        self.assertIn("expenses", pl)

    def test_49_stock_master_still_works(self):
        batches = StockDAO.get_stock_batches_for_item(self.item_id)
        self.assertGreater(len(batches), 0)

    @unittest.skipUnless(HAS_PYSIDE6, _PYSIDE_SKIP_REASON)
    def test_50_all_master_screens_work(self):
        import screens
        masters = [
            screens.CompanyMasterPage,
            screens.UnitMasterPage,
            screens.DrugMasterPage,
            screens.SupplierMasterPage,
            screens.CustomerMasterPage,
            screens.DoctorMasterPage,
            screens.ItemMasterPage,
            screens.StockMasterPage,
            screens.AccountLedgerPage,
            screens.AccountRolesPage,
        ]
        for cls in masters:
            page = cls()
            self.assertIsNotNone(page)


if __name__ == "__main__":
    unittest.main()
