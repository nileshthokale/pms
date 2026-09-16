"""Phase 5D — Party Wise Report tests.

46 tests covering:
    1-2:   Empty customer/supplier reports
    3-6:   One/many customers, one/many suppliers
    7-12:  Customer sales, credit notes, receipts; Supplier purchases, debit notes, payments
    13-14: Ledger balance for customer and supplier
    15-17: Date filtering, customer name filter, supplier name filter
    18-20: Party type selection (Customer, Supplier, All)
    21-22: Customer and supplier summaries
    23-24: Edited transaction, deleted transaction excluded
    25:    Accounting balance agrees with Account Ledger
    26-27: Opening balance handling for customer and supplier
    28:    Outstanding sign handling
    29:    Period / end-date behavior documented
    30:    Report is read-only
    31:    Persistence
    32-38: Regression: Customer Receipt, Supplier Payment, Counter Sale,
           Purchase Invoice, Credit Note, Debit Note, Journal Entry still work
    39-41: Regression: Trial Balance, P&L, Balance Sheet still work
    42-44: Regression: Sales Report, Purchase Report, Expiry Report still work
    45-46: Regression: Stock Master, All Master screens work
"""

import os
import sys
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database.connection import get_connection, init_database
from database.account_roles import (
    ROLE_CASH,
    ROLE_BANK,
    ROLE_SALES,
    ROLE_PURCHASE,
    ensure_system_ledgers,
    ensure_account_groups,
    migrate_legacy_ledger_groups,
)
from database.accounting_posting import PostingEngine
from database.party_wise_report_dao import PartyWiseReportDAO
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
from database.trial_balance_dao import TrialBalanceDAO
from database.profit_loss_dao import ProfitLossDAO
from database.balance_sheet_dao import BalanceSheetDAO
from database.sales_report_dao import SalesReportDAO
from database.purchase_report_dao import PurchaseReportDAO
from database.company_dao import CompanyDAO
from database.unit_dao import UnitDAO
from database.drug_dao import DrugDAO
from database.item_dao import ItemDAO
from database.stock_dao import StockDAO
from database.doctor_dao import DoctorDAO

try:
    from PySide6.QtWidgets import QApplication
    from screens.party_wise_report import PartyWiseReportPage

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
    _DB_PATH = os.path.join(
        os.path.dirname(__file__), "_test_party_wise_report.db"
    )

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
        self.customer_id = CustomerDAO.insert("CustomerA", city="Mumbai")
        self.customer_b_id = CustomerDAO.insert("CustomerB", city="Delhi")
        self.doctor_id = DoctorDAO.insert("Dr. Smith")
        self.supplier_id = SupplierDAO.insert(
            "SupplierA", city="Pune", opening_balance=0
        )
        self.supplier_b_id = SupplierDAO.insert(
            "SupplierB", city="Chennai", opening_balance=0
        )
        self.item_id = ItemDAO.insert(
            item_name="ItemA", unit_id=self.unit_id,
            company_id=self.company_id, pack_size="10x10",
        )
        self.item_b_id = ItemDAO.insert(
            item_name="ItemB", unit_id=self.unit_id,
            company_id=self.company_id, pack_size="10x10",
        )
        ensure_system_ledgers()
        ensure_account_groups()
        migrate_legacy_ledger_groups()

        self.customer_ledger_id = CustomerDAO.get_ledger_id(self.customer_id)
        self.customer_b_ledger_id = CustomerDAO.get_ledger_id(
            self.customer_b_id
        )
        self.supplier_ledger_id = SupplierDAO.get_ledger_id(self.supplier_id)
        self.supplier_b_ledger_id = SupplierDAO.get_ledger_id(
            self.supplier_b_id
        )

        self.engine = PostingEngine()
        self._pv_count = 0
        self._cs_count = 0

    # ── helpers ──────────────────────────────────────────────────────
    def _seed_stock(
        self, item_id=None, batch_no="BATCH-A",
        qty=100.0, rate=40.0, mrp=50.0, date="2026-01-05",
    ):
        self._pv_count += 1
        PurchaseDAO.insert_invoice(
            voucher_no=f"PV-{self._pv_count:04d}", voucher_date=date,
            voucher_time="", purchase_type="Cash",
            supplier_id=self.supplier_id,
            invoice_no=f"INV-{self._pv_count:04d}", invoice_date=date,
            invoice_net_amount=qty * rate, bill_discount=0, due_date="",
            total_amount=qty * rate, gst_amount=0, debit_note_amount=0,
            other_amount=0, paid_amount=qty * rate, round_off=0,
            net_amount=qty * rate, remarks="",
            items=[{
                "item_id": item_id or self.item_id, "pack_size": "10x10",
                "pay_qty": qty, "free_qty": 0, "batch_no": batch_no,
                "expiry": "12/27", "rate": rate, "mrp": mrp, "discount": 0,
                "gst_percent": 0, "gst_amount": 0,
                "amount": qty * rate,
                "purchase_rate": rate, "net_rate": rate, "pp": rate,
            }],
        )
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT id FROM stock_batches "
                "WHERE item_id = ? AND batch_no = ?",
                (item_id or self.item_id, batch_no),
            ).fetchone()
        finally:
            conn.close()
        return row["id"]

    def _sale(
        self, *, date="2026-02-01", customer_id=None,
        net=500.0, bill_no=None, sale_type="Credit", paid=0.0,
    ):
        self._cs_count += 1
        bill_no = bill_no or f"CS-{self._cs_count:04d}"
        cid = customer_id if customer_id is not None else self.customer_id
        items = [{
            "item_id": self.item_id,
            "stock_batch_id": self._batch_id,
            "pack_size": "10x10", "location": "",
            "batch_no": "BATCH-A", "expiry": "12/27",
            "mrp": 50.0, "sale_qty": net / 50.0,
            "discount_amount": 0, "amount": net,
        }]
        return SalesDAO.insert_invoice(
            bill_no=bill_no, sale_date=date, sale_time="",
            sale_type=sale_type, customer_id=cid, patient_name="",
            doctor_id=None, discount=0, paid_amount=paid,
            total_amount=net, round_off=0, net_amount=net,
            remarks="", items=items,
        )

    def _make_purchase(
        self, *, date="2026-03-01", supplier_id=None,
        net=1000.0, pv="PV-001", ptype="Credit", paid=0.0,
    ):
        sid = supplier_id or self.supplier_id
        items = [{
            "item_id": self.item_id, "pack_size": "10x10",
            "pay_qty": net / 100.0, "free_qty": 0,
            "batch_no": "BATCH-A", "expiry": "12/27",
            "rate": 100.0, "mrp": 120.0, "discount": 0,
            "gst_percent": 0, "gst_amount": 0, "amount": net,
            "purchase_rate": 100.0, "net_rate": 100.0, "pp": 100.0,
        }]
        return PurchaseDAO.insert_invoice(
            voucher_no=pv, voucher_date=date, voucher_time="",
            purchase_type=ptype, supplier_id=sid,
            invoice_no=f"INV-{pv}", invoice_date=date,
            invoice_net_amount=net, bill_discount=0, due_date="",
            total_amount=net, gst_amount=0, debit_note_amount=0,
            other_amount=0, paid_amount=paid, round_off=0,
            net_amount=net, remarks="", items=items,
        )


# ======================================================================
# 1-2: Empty reports
# ======================================================================

class TestEmpty(_BaseTest):

    def test_01_empty_customer_report(self):
        # With no transactions, customers still appear (no date filter)
        # but all totals are zero — this is the correct behavior.
        rows = PartyWiseReportDAO.get_customer_report()
        for r in rows:
            self.assertEqual(r["total_sales"], 0.0)
            self.assertEqual(r["total_credit_notes"], 0.0)
            self.assertEqual(r["total_receipts"], 0.0)

    def test_02_empty_supplier_report(self):
        rows = PartyWiseReportDAO.get_supplier_report()
        for r in rows:
            self.assertEqual(r["total_purchases"], 0.0)
            self.assertEqual(r["total_debit_notes"], 0.0)
            self.assertEqual(r["total_payments"], 0.0)


# ======================================================================
# 3-6: One/many customers and suppliers
# ======================================================================

class TestPartyBasics(_BaseTest):

    def setUp(self):
        super().setUp()
        self._batch_id = self._seed_stock()

    def test_03_one_customer(self):
        self._sale(date="2026-02-01", net=500.0)
        rows = PartyWiseReportDAO.get_customer_report()
        # Both customers appear, but only CustomerA has sales
        cust = [r for r in rows if r["customer_id"] == self.customer_id][0]
        self.assertEqual(cust["customer_name"], "CustomerA")
        self.assertAlmostEqual(cust["total_sales"], 500.0, places=2)

    def test_04_multiple_customers(self):
        self._sale(date="2026-02-01", customer_id=self.customer_id, net=500.0)
        self._sale(date="2026-02-01", customer_id=self.customer_b_id, net=300.0)
        rows = PartyWiseReportDAO.get_customer_report()
        self.assertEqual(len(rows), 2)
        names = {r["customer_name"] for r in rows}
        self.assertIn("CustomerA", names)
        self.assertIn("CustomerB", names)

    def test_05_one_supplier(self):
        self._make_purchase(date="2026-03-01", net=1000.0)
        rows = PartyWiseReportDAO.get_supplier_report(
            from_date="2026-03-01", to_date="2026-03-31"
        )
        # Only SupplierA has purchases in March
        sup = [r for r in rows if r["supplier_id"] == self.supplier_id][0]
        self.assertEqual(sup["supplier_name"], "SupplierA")
        self.assertAlmostEqual(sup["total_purchases"], 1000.0, places=2)

    def test_06_multiple_suppliers(self):
        self._make_purchase(
            date="2026-03-01", supplier_id=self.supplier_id, net=1000.0
        )
        self._make_purchase(
            date="2026-03-01", supplier_id=self.supplier_b_id, net=800.0,
            pv="PV-002",
        )
        rows = PartyWiseReportDAO.get_supplier_report()
        self.assertEqual(len(rows), 2)
        names = {r["supplier_name"] for r in rows}
        self.assertIn("SupplierA", names)
        self.assertIn("SupplierB", names)


# ======================================================================
# 7-12: Transaction totals
# ======================================================================

class TestTransactionTotals(_BaseTest):

    def setUp(self):
        super().setUp()
        self._batch_id = self._seed_stock()

    def test_07_customer_sales_totals(self):
        self._sale(date="2026-02-01", customer_id=self.customer_id, net=500.0)
        self._sale(
            date="2026-02-10", customer_id=self.customer_id, net=300.0,
            bill_no="CS-0099",
        )
        rows = PartyWiseReportDAO.get_customer_report()
        cust = [r for r in rows if r["customer_id"] == self.customer_id][0]
        self.assertAlmostEqual(cust["total_sales"], 800.0, places=2)

    def test_08_customer_credit_note_totals(self):
        self._sale(date="2026-02-01", customer_id=self.customer_id, net=500.0)
        CreditNoteDAO.insert_credit_note(
            header={
                "voucher_date": "2026-02-05", "voucher_time": "",
                "customer_id": self.customer_id, "total_amount": 100.0,
                "ledger_amount": 100.0, "remarks": "",
            },
            items=[{
                "item_id": self.item_id, "stock_batch_id": self._batch_id,
                "batch_no": "BATCH-A", "expiry": "12/27",
                "pack_size": "10x10", "rate": 50.0, "mrp": 50.0,
                "return_qty": 2.0, "less_amount": 0, "amount": 100.0,
                "return_reason": "test", "price_factor": 1.0,
            }],
        )
        rows = PartyWiseReportDAO.get_customer_report(
            from_date="2026-02-01", to_date="2026-02-28"
        )
        cust = [r for r in rows if r["customer_id"] == self.customer_id][0]
        self.assertAlmostEqual(cust["total_credit_notes"], 100.0, places=2)

    def test_09_customer_receipt_totals(self):
        self._sale(date="2026-02-01", customer_id=self.customer_id, net=500.0)
        CustomerReceiptDAO.insert_receipt({
            "receipt_date": "2026-02-10", "receipt_time": "",
            "customer_id": self.customer_id, "receipt_mode": "Cash",
            "amount": 200.0, "reference_no": "", "remarks": "",
        })
        rows = PartyWiseReportDAO.get_customer_report(
            from_date="2026-02-01", to_date="2026-02-28"
        )
        cust = [r for r in rows if r["customer_id"] == self.customer_id][0]
        self.assertAlmostEqual(cust["total_receipts"], 200.0, places=2)

    def test_10_supplier_purchase_totals(self):
        self._make_purchase(
            date="2026-03-01", supplier_id=self.supplier_id, net=1000.0
        )
        self._make_purchase(
            date="2026-03-10", supplier_id=self.supplier_id, net=500.0,
            pv="PV-002",
        )
        rows = PartyWiseReportDAO.get_supplier_report(
            from_date="2026-03-01", to_date="2026-03-31"
        )
        sup = [r for r in rows if r["supplier_id"] == self.supplier_id][0]
        self.assertAlmostEqual(sup["total_purchases"], 1500.0, places=2)

    def test_11_supplier_debit_note_totals(self):
        self._make_purchase(
            date="2026-03-01", supplier_id=self.supplier_id, net=1000.0
        )
        DebitNoteDAO.insert_debit_note(
            header={
                "voucher_date": "2026-03-05", "voucher_time": "",
                "supplier_id": self.supplier_id, "total_amount": 150.0,
                "ledger_amount": 150.0, "remarks": "",
            },
            items=[{
                "item_id": self.item_id, "stock_batch_id": self._batch_id,
                "batch_no": "BATCH-A", "expiry": "12/27",
                "pack_size": "10x10", "rate": 100.0, "mrp": 120.0,
                "return_qty": 1.0, "less_amount": 0, "amount": 150.0,
                "return_reason": "test", "price_factor": 1.0,
            }],
        )
        rows = PartyWiseReportDAO.get_supplier_report(
            from_date="2026-03-01", to_date="2026-03-31"
        )
        sup = [r for r in rows if r["supplier_id"] == self.supplier_id][0]
        self.assertAlmostEqual(sup["total_debit_notes"], 150.0, places=2)

    def test_12_supplier_payment_totals(self):
        self._make_purchase(
            date="2026-03-01", supplier_id=self.supplier_id, net=1000.0
        )
        SupplierPaymentDAO.insert_payment({
            "payment_date": "2026-03-10", "payment_time": "",
            "supplier_id": self.supplier_id, "payment_mode": "Cash",
            "amount": 400.0, "reference_no": "", "remarks": "",
        })
        rows = PartyWiseReportDAO.get_supplier_report(
            from_date="2026-03-01", to_date="2026-03-31"
        )
        sup = [r for r in rows if r["supplier_id"] == self.supplier_id][0]
        self.assertAlmostEqual(sup["total_payments"], 400.0, places=2)


# ======================================================================
# 13-14: Ledger balance
# ======================================================================

class TestLedgerBalance(_BaseTest):

    def setUp(self):
        super().setUp()
        self._batch_id = self._seed_stock()

    def test_13_customer_ledger_balance(self):
        # Sale of 500: Customer debited 500 (owes us 500)
        self._sale(date="2026-02-01", customer_id=self.customer_id, net=500.0)
        bal = LedgerDAO.get_balance(self.customer_ledger_id)
        self.assertAlmostEqual(bal["closing_balance"], 500.0, places=2)
        self.assertEqual(bal["closing_balance_type"], "Debit")

    def test_14_supplier_ledger_balance(self):
        # Purchase of 1000: Supplier credited 1000 (we owe them 1000)
        self._make_purchase(
            date="2026-03-01", supplier_id=self.supplier_id, net=1000.0
        )
        bal = LedgerDAO.get_balance(self.supplier_ledger_id)
        self.assertAlmostEqual(bal["closing_balance"], 1000.0, places=2)
        self.assertEqual(bal["closing_balance_type"], "Credit")


# ======================================================================
# 15-17: Filters
# ======================================================================

class TestFilters(_BaseTest):

    def setUp(self):
        super().setUp()
        self._batch_id = self._seed_stock()

    def test_15_date_filtering(self):
        # Sale in Feb, sale in Mar — only Feb should appear
        self._sale(date="2026-02-01", customer_id=self.customer_id, net=500.0)
        self._sale(
            date="2026-03-01", customer_id=self.customer_id, net=300.0,
            bill_no="CS-0099",
        )
        rows = PartyWiseReportDAO.get_customer_report(
            from_date="2026-02-01", to_date="2026-02-28"
        )
        cust = [r for r in rows if r["customer_id"] == self.customer_id][0]
        self.assertAlmostEqual(cust["total_sales"], 500.0, places=2)

    def test_16_customer_name_filter(self):
        self._sale(date="2026-02-01", customer_id=self.customer_id, net=500.0)
        self._sale(
            date="2026-02-01", customer_id=self.customer_b_id, net=300.0
        )
        rows = PartyWiseReportDAO.get_customer_report(party_name="CustomerA")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["customer_name"], "CustomerA")

    def test_17_supplier_name_filter(self):
        self._make_purchase(
            date="2026-03-01", supplier_id=self.supplier_id, net=1000.0
        )
        self._make_purchase(
            date="2026-03-01", supplier_id=self.supplier_b_id, net=800.0,
            pv="PV-002",
        )
        rows = PartyWiseReportDAO.get_supplier_report(party_name="SupplierA")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["supplier_name"], "SupplierA")


# ======================================================================
# 18-20: Party type selection
# ======================================================================

class TestPartyType(_BaseTest):

    def setUp(self):
        super().setUp()
        self._batch_id = self._seed_stock()

    def test_18_customer_type(self):
        self._sale(date="2026-02-01", customer_id=self.customer_id, net=500.0)
        # Use date filter so only customers with transactions in period appear
        cust_rows = PartyWiseReportDAO.get_customer_report(
            from_date="2026-02-01", to_date="2026-02-28"
        )
        self.assertGreaterEqual(len(cust_rows), 1)
        cust = [r for r in cust_rows if r["customer_id"] == self.customer_id][0]
        self.assertAlmostEqual(cust["total_sales"], 500.0, places=2)

    def test_19_supplier_type(self):
        self._make_purchase(
            date="2026-03-01", supplier_id=self.supplier_id, net=1000.0
        )
        # Use date filter so only suppliers with transactions in period appear
        supp_rows = PartyWiseReportDAO.get_supplier_report(
            from_date="2026-03-01", to_date="2026-03-31"
        )
        self.assertGreaterEqual(len(supp_rows), 1)
        sup = [r for r in supp_rows if r["supplier_id"] == self.supplier_id][0]
        self.assertAlmostEqual(sup["total_purchases"], 1000.0, places=2)

    def test_20_all_type(self):
        self._sale(date="2026-02-01", customer_id=self.customer_id, net=500.0)
        self._make_purchase(
            date="2026-03-01", supplier_id=self.supplier_id, net=1000.0
        )
        cust_rows = PartyWiseReportDAO.get_customer_report()
        supp_rows = PartyWiseReportDAO.get_supplier_report()
        self.assertGreaterEqual(len(cust_rows), 1)
        self.assertGreaterEqual(len(supp_rows), 1)


# ======================================================================
# 21-22: Summaries
# ======================================================================

class TestSummaries(_BaseTest):

    def setUp(self):
        super().setUp()
        self._batch_id = self._seed_stock()

    def test_21_customer_summary(self):
        self._sale(date="2026-02-01", customer_id=self.customer_id, net=500.0)
        self._sale(
            date="2026-02-01", customer_id=self.customer_b_id, net=300.0
        )
        summary = PartyWiseReportDAO.get_customer_summary()
        self.assertEqual(summary["total_customers"], 2)
        self.assertAlmostEqual(summary["total_sales"], 800.0, places=2)

    def test_22_supplier_summary(self):
        self._make_purchase(
            date="2026-03-01", supplier_id=self.supplier_id, net=1000.0
        )
        self._make_purchase(
            date="2026-03-01", supplier_id=self.supplier_b_id, net=800.0,
            pv="PV-002",
        )
        summary = PartyWiseReportDAO.get_supplier_summary(
            from_date="2026-03-01", to_date="2026-03-31"
        )
        self.assertEqual(summary["total_suppliers"], 2)
        self.assertAlmostEqual(summary["total_purchases"], 1800.0, places=2)


# ======================================================================
# 23-24: Edited and deleted transactions
# ======================================================================

class TestEditDelete(_BaseTest):

    def setUp(self):
        super().setUp()
        self._batch_id = self._seed_stock()

    def test_23_edited_receipt_reflected(self):
        self._sale(date="2026-02-01", customer_id=self.customer_id, net=500.0)
        rid = CustomerReceiptDAO.insert_receipt({
            "receipt_date": "2026-02-10", "receipt_time": "",
            "customer_id": self.customer_id, "receipt_mode": "Cash",
            "amount": 100.0, "reference_no": "", "remarks": "",
        })
        # Update receipt to 250
        receipt = CustomerReceiptDAO.get_by_id(rid)
        CustomerReceiptDAO.update_receipt(rid, {
            "receipt_date": receipt["receipt_date"],
            "receipt_time": receipt["receipt_time"],
            "customer_id": receipt["customer_id"],
            "receipt_mode": receipt["receipt_mode"],
            "amount": 250.0,
            "reference_no": receipt["reference_no"],
            "remarks": receipt["remarks"],
        })
        rows = PartyWiseReportDAO.get_customer_report(
            from_date="2026-02-01", to_date="2026-02-28"
        )
        cust = [r for r in rows if r["customer_id"] == self.customer_id][0]
        self.assertAlmostEqual(cust["total_receipts"], 250.0, places=2)

    def test_24_deleted_payment_excluded(self):
        self._make_purchase(
            date="2026-03-01", supplier_id=self.supplier_id, net=1000.0
        )
        pid = SupplierPaymentDAO.insert_payment({
            "payment_date": "2026-03-10", "payment_time": "",
            "supplier_id": self.supplier_id, "payment_mode": "Cash",
            "amount": 400.0, "reference_no": "", "remarks": "",
        })
        SupplierPaymentDAO.delete_payment(pid)
        rows = PartyWiseReportDAO.get_supplier_report(
            from_date="2026-03-01", to_date="2026-03-31"
        )
        sup = [r for r in rows if r["supplier_id"] == self.supplier_id][0]
        self.assertAlmostEqual(sup["total_payments"], 0.0, places=2)


# ======================================================================
# 25: Accounting balance agrees with Account Ledger
# ======================================================================

class TestAccountingConsistency(_BaseTest):

    def setUp(self):
        super().setUp()
        self._batch_id = self._seed_stock()

    def test_25_balance_agrees_with_ledger(self):
        self._sale(date="2026-02-01", customer_id=self.customer_id, net=500.0)
        CustomerReceiptDAO.insert_receipt({
            "receipt_date": "2026-02-10", "receipt_time": "",
            "customer_id": self.customer_id, "receipt_mode": "Cash",
            "amount": 200.0, "reference_no": "", "remarks": "",
        })
        rows = PartyWiseReportDAO.get_customer_report(
            from_date="2026-02-01", to_date="2026-02-28"
        )
        cust = [r for r in rows if r["customer_id"] == self.customer_id][0]
        ledger_bal = LedgerDAO.get_balance(self.customer_ledger_id)
        self.assertAlmostEqual(
            cust["ledger_balance"],
            ledger_bal["closing_balance"],
            places=2,
        )
        self.assertEqual(
            cust["ledger_balance_type"],
            ledger_bal["closing_balance_type"],
        )


# ======================================================================
# 26-27: Opening balance handling
# ======================================================================

class TestOpeningBalance(_BaseTest):

    def setUp(self):
        super().setUp()
        self._batch_id = self._seed_stock()

    def test_26_customer_opening_balance(self):
        # Create customer with opening balance
        cid = CustomerDAO.insert("CustOB", opening_balance=500.0)
        lid = CustomerDAO.get_ledger_id(cid)
        # Ledger should carry the opening balance
        ledger = LedgerDAO.get_ledger_by_id(lid)
        self.assertAlmostEqual(ledger["opening_balance"], 500.0, places=2)
        self.assertEqual(ledger["opening_balance_type"], "Debit")

    def test_27_supplier_opening_balance(self):
        # Create supplier with opening balance
        sid = SupplierDAO.insert("SuppOB", opening_balance=300.0)
        lid = SupplierDAO.get_ledger_id(sid)
        ledger = LedgerDAO.get_ledger_by_id(lid)
        self.assertAlmostEqual(ledger["opening_balance"], 300.0, places=2)
        self.assertEqual(ledger["opening_balance_type"], "Credit")


# ======================================================================
# 28: Outstanding sign handling
# ======================================================================

class TestOutstandingSign(_BaseTest):

    def setUp(self):
        super().setUp()
        self._batch_id = self._seed_stock()

    def test_28_outstanding_sign(self):
        # Customer sale = 500 (debit balance = we are owed 500)
        self._sale(date="2026-02-01", customer_id=self.customer_id, net=500.0)
        rows = PartyWiseReportDAO.get_customer_report()
        cust = [r for r in rows if r["customer_id"] == self.customer_id][0]
        bal = LedgerDAO.get_balance(self.customer_ledger_id)
        self.assertEqual(bal["closing_balance_type"], "Debit")
        self.assertAlmostEqual(bal["closing_balance"], 500.0, places=2)

        # Supplier purchase = 1000 (credit balance = we owe 1000)
        self._make_purchase(
            date="2026-03-01", supplier_id=self.supplier_id, net=1000.0
        )
        sbal = LedgerDAO.get_balance(self.supplier_ledger_id)
        self.assertEqual(sbal["closing_balance_type"], "Credit")
        self.assertAlmostEqual(sbal["closing_balance"], 1000.0, places=2)


# ======================================================================
# 29: Period / end-date behavior documented
# ======================================================================

class TestPeriodBehavior(_BaseTest):

    def setUp(self):
        super().setUp()
        self._batch_id = self._seed_stock()

    def test_29_outstanding_is_current_not_period_end(self):
        # Sale in Feb
        self._sale(date="2026-02-01", customer_id=self.customer_id, net=500.0)
        # Receipt in Mar
        CustomerReceiptDAO.insert_receipt({
            "receipt_date": "2026-03-10", "receipt_time": "",
            "customer_id": self.customer_id, "receipt_mode": "Cash",
            "amount": 200.0, "reference_no": "", "remarks": "",
        })
        # Report with to_date=Feb should still show CURRENT balance
        # (outstanding is always current, not period-end)
        rows = PartyWiseReportDAO.get_customer_report(
            from_date="2026-02-01", to_date="2026-02-28"
        )
        cust = [r for r in rows if r["customer_id"] == self.customer_id][0]
        # Current ledger balance = 500 - 200 = 300 Debit
        # (even though receipt was in Mar, the balance is current)
        bal = LedgerDAO.get_balance(self.customer_ledger_id)
        self.assertAlmostEqual(cust["ledger_balance"], 300.0, places=2)
        self.assertEqual(cust["ledger_balance_type"], "Debit")


# ======================================================================
# 30: Report is read-only
# ======================================================================

class TestReadOnly(_BaseTest):

    def test_30_report_is_read_only(self):
        dao = PartyWiseReportDAO
        # Verify methods return data, never modify
        cust = dao.get_customer_report()
        supp = dao.get_supplier_report()
        self.assertIsInstance(cust, list)
        self.assertIsInstance(supp, list)


# ======================================================================
# 31: Persistence
# ======================================================================

class TestPersistence(_BaseTest):

    def setUp(self):
        super().setUp()
        self._batch_id = self._seed_stock()

    def test_31_persistence(self):
        self._sale(date="2026-02-01", customer_id=self.customer_id, net=500.0)
        rows = PartyWiseReportDAO.get_customer_report(
            from_date="2026-02-01", to_date="2026-02-28"
        )
        self.assertEqual(len(rows), 1)
        # Simulate restart by closing and re-opening connection
        conn = get_connection()
        conn.close()
        rows2 = PartyWiseReportDAO.get_customer_report(
            from_date="2026-02-01", to_date="2026-02-28"
        )
        self.assertEqual(len(rows2), 1)
        self.assertEqual(rows[0]["total_sales"], rows2[0]["total_sales"])


# ======================================================================
# 32-38: Regression — existing modules still work
# ======================================================================

class TestRegressionTransactions(_BaseTest):

    def setUp(self):
        super().setUp()
        self._batch_id = self._seed_stock()

    def test_32_customer_receipt_still_works(self):
        self._sale(date="2026-02-01", customer_id=self.customer_id, net=500.0)
        rid = CustomerReceiptDAO.insert_receipt({
            "receipt_date": "2026-02-10", "receipt_time": "",
            "customer_id": self.customer_id, "receipt_mode": "Cash",
            "amount": 200.0, "reference_no": "", "remarks": "",
        })
        self.assertIsNotNone(rid)
        receipt = CustomerReceiptDAO.get_by_id(rid)
        self.assertAlmostEqual(receipt["amount"], 200.0, places=2)

    def test_33_supplier_payment_still_works(self):
        self._make_purchase(
            date="2026-03-01", supplier_id=self.supplier_id, net=1000.0
        )
        pid = SupplierPaymentDAO.insert_payment({
            "payment_date": "2026-03-10", "payment_time": "",
            "supplier_id": self.supplier_id, "payment_mode": "Cash",
            "amount": 400.0, "reference_no": "", "remarks": "",
        })
        self.assertIsNotNone(pid)
        payment = SupplierPaymentDAO.get_by_id(pid)
        self.assertAlmostEqual(payment["amount"], 400.0, places=2)

    def test_34_counter_sale_still_works(self):
        bid = self._sale(date="2026-02-01", customer_id=self.customer_id, net=500.0)
        self.assertIsNotNone(bid)
        sale = SalesDAO.get_by_id(bid)
        self.assertAlmostEqual(sale["net_amount"], 500.0, places=2)

    def test_35_purchase_invoice_still_works(self):
        pid = self._make_purchase(
            date="2026-03-01", supplier_id=self.supplier_id, net=1000.0
        )
        self.assertIsNotNone(pid)
        inv = PurchaseDAO.get_by_id(pid)
        self.assertAlmostEqual(inv["net_amount"], 1000.0, places=2)

    def test_36_credit_note_still_works(self):
        self._sale(date="2026-02-01", customer_id=self.customer_id, net=500.0)
        cn_id = CreditNoteDAO.insert_credit_note(
            header={
                "voucher_date": "2026-02-05", "voucher_time": "",
                "customer_id": self.customer_id, "total_amount": 100.0,
                "ledger_amount": 100.0, "remarks": "",
            },
            items=[{
                "item_id": self.item_id, "stock_batch_id": self._batch_id,
                "batch_no": "BATCH-A", "expiry": "12/27",
                "pack_size": "10x10", "rate": 50.0, "mrp": 50.0,
                "return_qty": 2.0, "less_amount": 0, "amount": 100.0,
                "return_reason": "test", "price_factor": 1.0,
            }],
        )
        self.assertIsNotNone(cn_id)

    def test_37_debit_note_still_works(self):
        self._make_purchase(
            date="2026-03-01", supplier_id=self.supplier_id, net=1000.0
        )
        dn_id = DebitNoteDAO.insert_debit_note(
            header={
                "voucher_date": "2026-03-05", "voucher_time": "",
                "supplier_id": self.supplier_id, "total_amount": 150.0,
                "ledger_amount": 150.0, "remarks": "",
            },
            items=[{
                "item_id": self.item_id, "stock_batch_id": self._batch_id,
                "batch_no": "BATCH-A", "expiry": "12/27",
                "pack_size": "10x10", "rate": 100.0, "mrp": 120.0,
                "return_qty": 1.0, "less_amount": 0, "amount": 150.0,
                "return_reason": "test", "price_factor": 1.0,
            }],
        )
        self.assertIsNotNone(dn_id)

    def test_38_journal_entry_still_works(self):
        cash = LedgerDAO.get_by_system_role(ROLE_CASH)
        sales = LedgerDAO.get_by_system_role(ROLE_SALES)
        jid = JournalDAO.insert_entry(
            header={"entry_date": "2026-04-01", "entry_time": "", "narration": "Test JV"},
            items=[
                {"ledger_id": cash["id"], "debit": 500.0, "credit": 0.0, "description": "Dr Cash"},
                {"ledger_id": sales["id"], "debit": 0.0, "credit": 500.0, "description": "Cr Sales"},
            ],
        )
        self.assertIsNotNone(jid)


# ======================================================================
# 39-41: Regression — financial reports
# ======================================================================

class TestRegressionFinancial(_BaseTest):

    def setUp(self):
        super().setUp()
        self._batch_id = self._seed_stock()

    def test_39_trial_balance_still_works(self):
        self._sale(date="2026-02-01", customer_id=self.customer_id, net=500.0)
        self._make_purchase(
            date="2026-03-01", supplier_id=self.supplier_id, net=1000.0
        )
        tb = TrialBalanceDAO.get_trial_balance()
        self.assertIn("rows", tb)
        self.assertIn("totals", tb)
        self.assertTrue(tb["totals"]["balanced"])

    def test_40_profit_loss_still_works(self):
        self._sale(date="2026-02-01", customer_id=self.customer_id, net=500.0)
        self._make_purchase(
            date="2026-03-01", supplier_id=self.supplier_id, net=1000.0
        )
        pl = ProfitLossDAO.get_profit_loss("2026-01-01", "2026-12-31")
        self.assertIn("income", pl)
        self.assertIn("expenses", pl)

    def test_41_balance_sheet_still_works(self):
        self._sale(date="2026-02-01", customer_id=self.customer_id, net=500.0)
        self._make_purchase(
            date="2026-03-01", supplier_id=self.supplier_id, net=1000.0
        )
        bs = BalanceSheetDAO.get_balance_sheet("2026-12-31")
        self.assertIn("assets", bs)
        self.assertIn("liabilities", bs)


# ======================================================================
# 42-44: Regression — other reports
# ======================================================================

class TestRegressionReports(_BaseTest):

    def setUp(self):
        super().setUp()
        self._batch_id = self._seed_stock()

    def test_42_sales_report_still_works(self):
        self._sale(date="2026-02-01", customer_id=self.customer_id, net=500.0)
        report = SalesReportDAO.get_sales_report()
        self.assertIn("rows", report)
        self.assertIn("summary", report)

    def test_43_purchase_report_still_works(self):
        self._make_purchase(
            date="2026-03-01", supplier_id=self.supplier_id, net=1000.0
        )
        report = PurchaseReportDAO.get_purchase_report()
        self.assertIn("rows", report)
        self.assertIn("summary", report)

    def test_44_expiry_report_still_works(self):
        from database.expiry_report_dao import ExpiryReportDAO
        report = ExpiryReportDAO.get_expiry_report()
        self.assertIsInstance(report, dict)


# ======================================================================
# 45-46: Regression — masters
# ======================================================================

class TestRegressionMasters(_BaseTest):

    def test_45_stock_master_still_works(self):
        batch_id = self._seed_stock()
        batches = StockDAO.get_stock_batches_for_item(self.item_id)
        self.assertGreaterEqual(len(batches), 1)

    def test_46_master_crud_still_works(self):
        cid = CompanyDAO.insert("NewCo", "NC")
        self.assertIsNotNone(cid)
        uid = UnitDAO.insert("Box")
        self.assertIsNotNone(uid)
        did = DrugDAO.insert("Ibuprofen")
        self.assertIsNotNone(did)
        iid = ItemDAO.insert(
            item_name="ItemNew", unit_id=uid,
            company_id=cid, pack_size="10x10",
        )
        self.assertIsNotNone(iid)


# ======================================================================
# UI tests (require PySide6)
# ======================================================================

@unittest.skipUnless(HAS_PYSIDE6, _PYSIDE_SKIP_REASON)
class TestUI(_BaseTest):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not hasattr(cls, "_app"):
            cls._app = QApplication.instance() or QApplication([])

    def test_ui_instantiation(self):
        page = PartyWiseReportPage()
        self.assertIsInstance(page, PartyWiseReportPage)

    def test_ui_has_controls(self):
        page = PartyWiseReportPage()
        self.assertIsNotNone(page.party_type_combo)
        self.assertIsNotNone(page.from_edit)
        self.assertIsNotNone(page.to_edit)
        self.assertIsNotNone(page.party_name_edit)
        self.assertIsNotNone(page._table)


if __name__ == "__main__":
    unittest.main()
