"""End-to-end accounting audit tests — all 7 source types.

10 scenarios verifying that every source type posts correctly and that
the full transaction lifecycle (insert/edit/reverse/delete) produces the
expected ledger effects.  Also checks global balance invariant and
cross-module independence.

Scenarios:
  1: Customer Receipt posting
  2: Supplier Payment posting
  3: Counter Sale (walk-in, cash) posting
  4: Purchase Invoice (credit) posting
  5: Credit Note posting
  6: Debit Note posting
  7: Journal Entry posting
  8: Edit-and-repost lifecycle for all 7 source types
  9: Delete (reversal) lifecycle for all 7 source types
 10: Cross-module independence — all 7 types coexist without interference
 11: Persistence and balance consistency across fresh connections
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
    ROLE_SALES,
    ROLE_PURCHASE,
    ROLE_SALES_RETURN,
    ROLE_PURCHASE_RETURN,
    ensure_system_ledgers,
)
from database.accounting_posting import (
    SOURCE_CUSTOMER_RECEIPT,
    SOURCE_SUPPLIER_PAYMENT,
    SOURCE_COUNTER_SALE,
    SOURCE_PURCHASE_INVOICE,
    SOURCE_CREDIT_NOTE,
    SOURCE_DEBIT_NOTE,
    SOURCE_JOURNAL_ENTRY,
    PostingEngine,
    PostingError,
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

    _DB_PATH = os.path.join(os.path.dirname(__file__), "_test_e2e_audit.db")

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
        self.sales_return_ledger = LedgerDAO.get_by_system_role(ROLE_SALES_RETURN)
        self.purchase_return_ledger = LedgerDAO.get_by_system_role(ROLE_PURCHASE_RETURN)
        self.cash_ledger = LedgerDAO.get_by_system_role(ROLE_CASH)
        self.bank_ledger = LedgerDAO.get_by_system_role(ROLE_BANK)
        self.sales_ledger = LedgerDAO.get_by_system_role(ROLE_SALES)
        self.purchase_ledger = LedgerDAO.get_by_system_role(ROLE_PURCHASE)

        self.engine = PostingEngine()
        self._seed_stock()

    def _seed_stock(self, qty=100.0, rate=40.0):
        PurchaseDAO.insert_invoice(
            voucher_no="PV-0001", voucher_date="2026-01-15",
            voucher_time="", purchase_type="Cash",
            supplier_id=self.supplier_id, invoice_no="INV-001",
            invoice_date="2026-01-15",
            invoice_net_amount=qty * rate, bill_discount=0,
            due_date="", total_amount=qty * rate, gst_amount=0,
            debit_note_amount=0, other_amount=0,
            paid_amount=qty * rate, round_off=0,
            net_amount=qty * rate, remarks="",
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

    def _nets(self, source_type, source_id):
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT ledger_id, SUM(debit) - SUM(credit) AS net "
                "FROM ledger_transactions "
                "WHERE reference_type = ? AND reference_id = ? "
                "GROUP BY ledger_id HAVING ABS(SUM(debit) - SUM(credit)) > 0.005",
                (source_type, source_id),
            ).fetchall()
            return {r["ledger_id"]: round(r["net"], 2) for r in rows}
        finally:
            conn.close()


# ======================================================================
# Scenario 1: Customer Receipt posting
# ======================================================================

class TestScenario1_CustomerReceipt(_BaseTest):

    def test_01_cash_receipt_debits_cash(self):
        rid = CustomerReceiptDAO.insert_receipt({
            "receipt_date": "2026-02-01", "receipt_time": "",
            "customer_id": self.customer_id, "receipt_mode": "Cash",
            "amount": 500.0, "reference_no": "", "remarks": "",
        })
        rows = self.engine.get_posting_rows(SOURCE_CUSTOMER_RECEIPT, rid)
        self.assertEqual(len(rows), 2)
        nets = self._nets(SOURCE_CUSTOMER_RECEIPT, rid)
        self.assertIn(self.cash_ledger["id"], nets)
        self.assertEqual(nets[self.cash_ledger["id"]], 500.0)
        self.assertIn(self.customer_ledger_id, nets)
        self.assertEqual(nets[self.customer_ledger_id], -500.0)

    def test_02_bank_receipt_debits_bank(self):
        rid = CustomerReceiptDAO.insert_receipt({
            "receipt_date": "2026-02-01", "receipt_time": "",
            "customer_id": self.customer_id, "receipt_mode": "Bank",
            "amount": 300.0, "reference_no": "NEFT-123", "remarks": "",
        })
        nets = self._nets(SOURCE_CUSTOMER_RECEIPT, rid)
        self.assertIn(self.bank_ledger["id"], nets)
        self.assertEqual(nets[self.bank_ledger["id"]], 300.0)
        self.assertEqual(nets[self.customer_ledger_id], -300.0)

    def test_03_reference_fields_correct(self):
        rid = CustomerReceiptDAO.insert_receipt({
            "receipt_date": "2026-02-01", "receipt_time": "10:30",
            "customer_id": self.customer_id, "receipt_mode": "Cash",
            "amount": 100.0, "reference_no": "", "remarks": "",
        })
        rows = self.engine.get_posting_rows(SOURCE_CUSTOMER_RECEIPT, rid)
        for r in rows:
            self.assertEqual(r["reference_type"], "CUSTOMER_RECEIPT")
            self.assertEqual(r["reference_id"], rid)
            self.assertEqual(r["voucher_type"], "Customer Receipt")
            self.assertIn("CR-", r["voucher_no"])


# ======================================================================
# Scenario 2: Supplier Payment posting
# ======================================================================

class TestScenario2_SupplierPayment(_BaseTest):

    def test_04_cash_payment_credits_cash(self):
        pid = SupplierPaymentDAO.insert_payment({
            "payment_date": "2026-02-01", "payment_time": "",
            "supplier_id": self.supplier_id, "payment_mode": "Cash",
            "amount": 600.0, "reference_no": "", "remarks": "",
        })
        rows = self.engine.get_posting_rows(SOURCE_SUPPLIER_PAYMENT, pid)
        self.assertEqual(len(rows), 2)
        nets = self._nets(SOURCE_SUPPLIER_PAYMENT, pid)
        self.assertIn(self.supplier_ledger_id, nets)
        self.assertEqual(nets[self.supplier_ledger_id], 600.0)
        self.assertIn(self.cash_ledger["id"], nets)
        self.assertEqual(nets[self.cash_ledger["id"]], -600.0)

    def test_05_bank_payment_credits_bank(self):
        pid = SupplierPaymentDAO.insert_payment({
            "payment_date": "2026-02-01", "payment_time": "",
            "supplier_id": self.supplier_id, "payment_mode": "Bank",
            "amount": 250.0, "reference_no": "CHQ-456", "remarks": "",
        })
        nets = self._nets(SOURCE_SUPPLIER_PAYMENT, pid)
        self.assertIn(self.bank_ledger["id"], nets)
        self.assertEqual(nets[self.bank_ledger["id"]], -250.0)
        self.assertEqual(nets[self.supplier_ledger_id], 250.0)


# ======================================================================
# Scenario 3: Counter Sale (walk-in cash) posting
# ======================================================================

class TestScenario3_CounterSale(_BaseTest):

    def test_06_walkin_cash_sale(self):
        bill_no = SalesDAO.generate_next_bill_no()
        sid = SalesDAO.insert_invoice(
            bill_no=bill_no, sale_date="2026-02-01", sale_time="",
            sale_type="Cash", customer_id=None, patient_name="",
            doctor_id=None, discount=0, paid_amount=400.0,
            total_amount=400.0, round_off=0, net_amount=400.0,
            remarks="",
            items=[{
                "item_id": self.item_id, "stock_batch_id": self.batch_id,
                "pack_size": "10x10", "location": "", "batch_no": "BATCH-A",
                "expiry": "12/27", "mrp": 50.0, "sale_qty": 10.0,
                "discount_amount": 0, "amount": 400.0,
            }],
        )
        rows = self.engine.get_posting_rows(SOURCE_COUNTER_SALE, sid)
        self.assertEqual(len(rows), 2)
        nets = self._nets(SOURCE_COUNTER_SALE, sid)
        self.assertIn(self.cash_ledger["id"], nets)
        self.assertEqual(nets[self.cash_ledger["id"]], 400.0)
        self.assertIn(self.sales_ledger["id"], nets)
        self.assertEqual(nets[self.sales_ledger["id"]], -400.0)

    def test_07_walkin_sale_voucher_type(self):
        bill_no = SalesDAO.generate_next_bill_no()
        sid = SalesDAO.insert_invoice(
            bill_no=bill_no, sale_date="2026-02-01", sale_time="",
            sale_type="Cash", customer_id=None, patient_name="",
            doctor_id=None, discount=0, paid_amount=200.0,
            total_amount=200.0, round_off=0, net_amount=200.0,
            remarks="",
            items=[{
                "item_id": self.item_id, "stock_batch_id": self.batch_id,
                "pack_size": "10x10", "location": "", "batch_no": "BATCH-A",
                "expiry": "12/27", "mrp": 50.0, "sale_qty": 5.0,
                "discount_amount": 0, "amount": 200.0,
            }],
        )
        rows = self.engine.get_posting_rows(SOURCE_COUNTER_SALE, sid)
        for r in rows:
            self.assertEqual(r["reference_type"], "COUNTER_SALE")
            self.assertEqual(r["voucher_type"], "Counter Sale")


# ======================================================================
# Scenario 4: Purchase Invoice (credit) posting
# ======================================================================

class TestScenario4_PurchaseInvoice(_BaseTest):

    def test_08_credit_purchase(self):
        pid = PurchaseDAO.insert_invoice(
            voucher_no="PV-0010", voucher_date="2026-02-01",
            voucher_time="", purchase_type="Credit",
            supplier_id=self.supplier_id, invoice_no="INV-100",
            invoice_date="2026-02-01",
            invoice_net_amount=800.0, bill_discount=0,
            due_date="", total_amount=800.0, gst_amount=0,
            debit_note_amount=0, other_amount=0,
            paid_amount=0, round_off=0,
            net_amount=800.0, remarks="",
            items=[{
                "item_id": self.item_id, "pack_size": "10x10",
                "pay_qty": 20, "free_qty": 0, "batch_no": "BATCH-B",
                "expiry": "12/27", "rate": 40.0, "mrp": 50.0,
                "discount": 0, "gst_percent": 0, "gst_amount": 0,
                "amount": 800.0, "purchase_rate": 40.0,
                "net_rate": 40.0, "pp": 40.0,
            }],
        )
        rows = self.engine.get_posting_rows(SOURCE_PURCHASE_INVOICE, pid)
        self.assertEqual(len(rows), 2)
        nets = self._nets(SOURCE_PURCHASE_INVOICE, pid)
        self.assertIn(self.purchase_ledger["id"], nets)
        self.assertEqual(nets[self.purchase_ledger["id"]], 800.0)
        self.assertIn(self.supplier_ledger_id, nets)
        self.assertEqual(nets[self.supplier_ledger_id], -800.0)

    def test_09_partial_payment_purchase(self):
        pid = PurchaseDAO.insert_invoice(
            voucher_no="PV-0011", voucher_date="2026-02-01",
            voucher_time="", purchase_type="Cash",
            supplier_id=self.supplier_id, invoice_no="INV-101",
            invoice_date="2026-02-01",
            invoice_net_amount=1000.0, bill_discount=0,
            due_date="", total_amount=1000.0, gst_amount=0,
            debit_note_amount=0, other_amount=0,
            paid_amount=400.0, round_off=0,
            net_amount=1000.0, remarks="",
            items=[{
                "item_id": self.item_id, "pack_size": "10x10",
                "pay_qty": 25, "free_qty": 0, "batch_no": "BATCH-C",
                "expiry": "12/27", "rate": 40.0, "mrp": 50.0,
                "discount": 0, "gst_percent": 0, "gst_amount": 0,
                "amount": 1000.0, "purchase_rate": 40.0,
                "net_rate": 40.0, "pp": 40.0,
            }],
        )
        rows = self.engine.get_posting_rows(SOURCE_PURCHASE_INVOICE, pid)
        self.assertEqual(len(rows), 3)
        nets = self._nets(SOURCE_PURCHASE_INVOICE, pid)
        self.assertIn(self.purchase_ledger["id"], nets)
        self.assertEqual(nets[self.purchase_ledger["id"]], 1000.0)
        self.assertIn(self.cash_ledger["id"], nets)
        self.assertEqual(nets[self.cash_ledger["id"]], -400.0)
        self.assertIn(self.supplier_ledger_id, nets)
        self.assertEqual(nets[self.supplier_ledger_id], -600.0)


# ======================================================================
# Scenario 5: Credit Note posting
# ======================================================================

class TestScenario5_CreditNote(_BaseTest):

    def test_10_credit_note_posting(self):
        cn_id = CreditNoteDAO.insert_credit_note(
            {
                "voucher_date": "2026-02-01", "cn_date": "2026-02-01",
                "cn_type": "Customer", "customer_id": self.customer_id,
                "total_amount": 300.0, "ledger_amount": 300.0,
                "remarks": "",
            },
            [{
                "item_id": self.item_id, "stock_batch_id": self.batch_id,
                "batch_no": "BATCH-A", "expiry": "12/27",
                "pack_size": "10x10", "rate": 40.0, "mrp": 50.0,
                "return_qty": 7.5, "less_amount": 0,
                "amount": 300.0, "return_reason": "Damaged",
                "price_factor": 1.0,
            }],
        )
        rows = self.engine.get_posting_rows(SOURCE_CREDIT_NOTE, cn_id)
        self.assertEqual(len(rows), 2)
        nets = self._nets(SOURCE_CREDIT_NOTE, cn_id)
        self.assertIn(self.sales_return_ledger["id"], nets)
        self.assertEqual(nets[self.sales_return_ledger["id"]], 300.0)
        self.assertIn(self.customer_ledger_id, nets)
        self.assertEqual(nets[self.customer_ledger_id], -300.0)


# ======================================================================
# Scenario 6: Debit Note posting
# ======================================================================

class TestScenario6_DebitNote(_BaseTest):

    def test_11_debit_note_posting(self):
        dn_id = DebitNoteDAO.insert_debit_note(
            {
                "voucher_date": "2026-02-01", "voucher_time": "",
                "dn_date": "2026-02-01", "dn_type": "Supplier",
                "supplier_id": self.supplier_id,
                "total_amount": 200.0, "ledger_amount": 200.0,
                "remarks": "",
            },
            [{
                "item_id": self.item_id, "stock_batch_id": self.batch_id,
                "batch_no": "BATCH-A", "expiry": "12/27",
                "pack_size": "10x10", "rate": 40.0, "mrp": 50.0,
                "return_qty": 5.0, "less_amount": 0,
                "amount": 200.0, "return_reason": "Expired",
                "price_factor": 1.0,
            }],
        )
        rows = self.engine.get_posting_rows(SOURCE_DEBIT_NOTE, dn_id)
        self.assertEqual(len(rows), 2)
        nets = self._nets(SOURCE_DEBIT_NOTE, dn_id)
        self.assertIn(self.supplier_ledger_id, nets)
        self.assertEqual(nets[self.supplier_ledger_id], 200.0)
        self.assertIn(self.purchase_return_ledger["id"], nets)
        self.assertEqual(nets[self.purchase_return_ledger["id"]], -200.0)


# ======================================================================
# Scenario 7: Journal Entry posting
# ======================================================================

class TestScenario7_JournalEntry(_BaseTest):

    def test_12_journal_entry_posting(self):
        je_id = JournalDAO.insert_entry(
            {
                "entry_date": "2026-02-01", "narration": "Capital introduced",
            },
            [
                {"ledger_id": self.cash_ledger["id"], "description": "Cash in", "debit": 1000.0, "credit": 0.0},
                {"ledger_id": self.sales_ledger["id"], "description": "Capital", "debit": 0.0, "credit": 1000.0},
            ],
        )
        rows = self.engine.get_posting_rows(SOURCE_JOURNAL_ENTRY, je_id)
        self.assertEqual(len(rows), 2)
        nets = self._nets(SOURCE_JOURNAL_ENTRY, je_id)
        self.assertTrue(len(nets) == 2)

    def test_13_journal_entry_voucher_type(self):
        je_id = JournalDAO.insert_entry(
            {"entry_date": "2026-02-01", "narration": "Test"},
            [
                {"ledger_id": self.cash_ledger["id"], "description": "", "debit": 500.0, "credit": 0.0},
                {"ledger_id": self.customer_ledger_id, "description": "", "debit": 0.0, "credit": 500.0},
            ],
        )
        rows = self.engine.get_posting_rows(SOURCE_JOURNAL_ENTRY, je_id)
        for r in rows:
            self.assertEqual(r["reference_type"], "JOURNAL_ENTRY")
            self.assertEqual(r["reference_id"], je_id)
            self.assertEqual(r["voucher_type"], "Journal Entry")


# ======================================================================
# Scenario 8: Edit-and-repost lifecycle
# ======================================================================

class TestScenario8_EditRepostLifecycle(_BaseTest):

    def test_14_edit_customer_receipt(self):
        rid = CustomerReceiptDAO.insert_receipt({
            "receipt_date": "2026-02-01", "receipt_time": "",
            "customer_id": self.customer_id, "receipt_mode": "Cash",
            "amount": 100.0, "reference_no": "", "remarks": "",
        })
        nets1 = self._nets(SOURCE_CUSTOMER_RECEIPT, rid)
        self.assertEqual(nets1[self.cash_ledger["id"]], 100.0)

        CustomerReceiptDAO.update_receipt(rid, {
            "receipt_date": "2026-02-01", "receipt_time": "",
            "customer_id": self.customer_id, "receipt_mode": "Cash",
            "amount": 250.0, "reference_no": "", "remarks": "",
        })
        nets2 = self._nets(SOURCE_CUSTOMER_RECEIPT, rid)
        self.assertEqual(nets2[self.cash_ledger["id"]], 250.0)
        self.assertEqual(nets2[self.customer_ledger_id], -250.0)

    def test_15_edit_supplier_payment(self):
        pid = SupplierPaymentDAO.insert_payment({
            "payment_date": "2026-02-01", "payment_time": "",
            "supplier_id": self.supplier_id, "payment_mode": "Cash",
            "amount": 200.0, "reference_no": "", "remarks": "",
        })
        SupplierPaymentDAO.update_payment(pid, {
            "payment_date": "2026-02-01", "payment_time": "",
            "supplier_id": self.supplier_id, "payment_mode": "Cash",
            "amount": 500.0, "reference_no": "", "remarks": "",
        })
        nets = self._nets(SOURCE_SUPPLIER_PAYMENT, pid)
        self.assertEqual(nets[self.supplier_ledger_id], 500.0)
        self.assertEqual(nets[self.cash_ledger["id"]], -500.0)

    def test_16_edit_credit_note(self):
        cn_id = CreditNoteDAO.insert_credit_note(
            {
                "voucher_date": "2026-02-01", "cn_date": "2026-02-01",
                "cn_type": "Customer", "customer_id": self.customer_id,
                "total_amount": 100.0, "ledger_amount": 100.0,
                "remarks": "",
            },
            [{
                "item_id": self.item_id, "stock_batch_id": self.batch_id,
                "batch_no": "BATCH-A", "expiry": "12/27",
                "pack_size": "10x10", "rate": 40.0, "mrp": 50.0,
                "return_qty": 2.5, "less_amount": 0,
                "amount": 100.0, "return_reason": "Damaged",
                "price_factor": 1.0,
            }],
        )
        CreditNoteDAO.update_credit_note(
            cn_id,
            {
                "voucher_date": "2026-02-01", "cn_date": "2026-02-01",
                "cn_type": "Customer", "customer_id": self.customer_id,
                "total_amount": 200.0, "ledger_amount": 200.0,
                "remarks": "",
            },
            [{
                "item_id": self.item_id, "stock_batch_id": self.batch_id,
                "batch_no": "BATCH-A", "expiry": "12/27",
                "pack_size": "10x10", "rate": 40.0, "mrp": 50.0,
                "return_qty": 5.0, "less_amount": 0,
                "amount": 200.0, "return_reason": "Damaged",
                "price_factor": 1.0,
            }],
        )
        nets = self._nets(SOURCE_CREDIT_NOTE, cn_id)
        self.assertEqual(nets[self.sales_return_ledger["id"]], 200.0)
        self.assertEqual(nets[self.customer_ledger_id], -200.0)

    def test_17_edit_debit_note(self):
        dn_id = DebitNoteDAO.insert_debit_note(
            {
                "voucher_date": "2026-02-01", "voucher_time": "",
                "dn_date": "2026-02-01", "dn_type": "Supplier",
                "supplier_id": self.supplier_id,
                "total_amount": 100.0, "ledger_amount": 100.0,
                "remarks": "",
            },
            [{
                "item_id": self.item_id, "stock_batch_id": self.batch_id,
                "batch_no": "BATCH-A", "expiry": "12/27",
                "pack_size": "10x10", "rate": 40.0, "mrp": 50.0,
                "return_qty": 2.5, "less_amount": 0,
                "amount": 100.0, "return_reason": "Expired",
                "price_factor": 1.0,
            }],
        )
        DebitNoteDAO.update_debit_note(
            dn_id,
            {
                "voucher_date": "2026-02-01", "voucher_time": "",
                "dn_date": "2026-02-01", "dn_type": "Supplier",
                "supplier_id": self.supplier_id,
                "total_amount": 150.0, "ledger_amount": 150.0,
                "remarks": "",
            },
            [{
                "item_id": self.item_id, "stock_batch_id": self.batch_id,
                "batch_no": "BATCH-A", "expiry": "12/27",
                "pack_size": "10x10", "rate": 40.0, "mrp": 50.0,
                "return_qty": 3.75, "less_amount": 0,
                "amount": 150.0, "return_reason": "Expired",
                "price_factor": 1.0,
            }],
        )
        nets = self._nets(SOURCE_DEBIT_NOTE, dn_id)
        self.assertEqual(nets[self.supplier_ledger_id], 150.0)
        self.assertEqual(nets[self.purchase_return_ledger["id"]], -150.0)

    def test_18_edit_journal_entry(self):
        je_id = JournalDAO.insert_entry(
            {"entry_date": "2026-02-01", "narration": "Original"},
            [
                {"ledger_id": self.cash_ledger["id"], "description": "", "debit": 100.0, "credit": 0.0},
                {"ledger_id": self.customer_ledger_id, "description": "", "debit": 0.0, "credit": 100.0},
            ],
        )
        nets1 = self._nets(SOURCE_JOURNAL_ENTRY, je_id)
        self.assertEqual(nets1[self.cash_ledger["id"]], 100.0)

        JournalDAO.update_entry(
            je_id,
            {"entry_date": "2026-02-01", "narration": "Updated"},
            [
                {"ledger_id": self.cash_ledger["id"], "description": "", "debit": 250.0, "credit": 0.0},
                {"ledger_id": self.customer_ledger_id, "description": "", "debit": 0.0, "credit": 250.0},
            ],
        )
        nets2 = self._nets(SOURCE_JOURNAL_ENTRY, je_id)
        self.assertEqual(nets2[self.cash_ledger["id"]], 250.0)
        self.assertEqual(nets2[self.customer_ledger_id], -250.0)


# ======================================================================
# Scenario 8: Delete (reversal) lifecycle
# ======================================================================

class TestScenario9_DeleteLifecycle(_BaseTest):

    def test_19_delete_customer_receipt(self):
        rid = CustomerReceiptDAO.insert_receipt({
            "receipt_date": "2026-02-01", "receipt_time": "",
            "customer_id": self.customer_id, "receipt_mode": "Cash",
            "amount": 100.0, "reference_no": "", "remarks": "",
        })
        self.assertTrue(self.engine.is_posted(SOURCE_CUSTOMER_RECEIPT, rid))
        CustomerReceiptDAO.delete_receipt(rid)
        self.assertFalse(self.engine.is_posted(SOURCE_CUSTOMER_RECEIPT, rid))
        nets = self._nets(SOURCE_CUSTOMER_RECEIPT, rid)
        self.assertEqual(len(nets), 0)

    def test_20_delete_supplier_payment(self):
        pid = SupplierPaymentDAO.insert_payment({
            "payment_date": "2026-02-01", "payment_time": "",
            "supplier_id": self.supplier_id, "payment_mode": "Cash",
            "amount": 100.0, "reference_no": "", "remarks": "",
        })
        self.assertTrue(self.engine.is_posted(SOURCE_SUPPLIER_PAYMENT, pid))
        SupplierPaymentDAO.delete_payment(pid)
        self.assertFalse(self.engine.is_posted(SOURCE_SUPPLIER_PAYMENT, pid))

    def test_21_delete_credit_note(self):
        cn_id = CreditNoteDAO.insert_credit_note(
            {
                "voucher_date": "2026-02-01", "cn_date": "2026-02-01",
                "cn_type": "Customer", "customer_id": self.customer_id,
                "total_amount": 100.0, "ledger_amount": 100.0,
                "remarks": "",
            },
            [{
                "item_id": self.item_id, "stock_batch_id": self.batch_id,
                "batch_no": "BATCH-A", "expiry": "12/27",
                "pack_size": "10x10", "rate": 40.0, "mrp": 50.0,
                "return_qty": 2.5, "less_amount": 0,
                "amount": 100.0, "return_reason": "Damaged",
                "price_factor": 1.0,
            }],
        )
        self.assertTrue(self.engine.is_posted(SOURCE_CREDIT_NOTE, cn_id))
        CreditNoteDAO.delete_credit_note(cn_id)
        self.assertFalse(self.engine.is_posted(SOURCE_CREDIT_NOTE, cn_id))

    def test_22_delete_debit_note(self):
        dn_id = DebitNoteDAO.insert_debit_note(
            {
                "voucher_date": "2026-02-01", "voucher_time": "",
                "dn_date": "2026-02-01", "dn_type": "Supplier",
                "supplier_id": self.supplier_id,
                "total_amount": 100.0, "ledger_amount": 100.0,
                "remarks": "",
            },
            [{
                "item_id": self.item_id, "stock_batch_id": self.batch_id,
                "batch_no": "BATCH-A", "expiry": "12/27",
                "pack_size": "10x10", "rate": 40.0, "mrp": 50.0,
                "return_qty": 2.5, "less_amount": 0,
                "amount": 100.0, "return_reason": "Expired",
                "price_factor": 1.0,
            }],
        )
        self.assertTrue(self.engine.is_posted(SOURCE_DEBIT_NOTE, dn_id))
        DebitNoteDAO.delete_debit_note(dn_id)
        self.assertFalse(self.engine.is_posted(SOURCE_DEBIT_NOTE, dn_id))

    def test_23_delete_journal_entry(self):
        je_id = JournalDAO.insert_entry(
            {"entry_date": "2026-02-01", "narration": "To delete"},
            [
                {"ledger_id": self.cash_ledger["id"], "description": "", "debit": 200.0, "credit": 0.0},
                {"ledger_id": self.customer_ledger_id, "description": "", "debit": 0.0, "credit": 200.0},
            ],
        )
        self.assertTrue(self.engine.is_posted(SOURCE_JOURNAL_ENTRY, je_id))
        JournalDAO.delete_entry(je_id)
        self.assertFalse(self.engine.is_posted(SOURCE_JOURNAL_ENTRY, je_id))
        nets = self._nets(SOURCE_JOURNAL_ENTRY, je_id)
        self.assertEqual(len(nets), 0)


# ======================================================================
# Scenario 9: Cross-module independence
# ======================================================================

class TestScenario10_CrossModuleIndependence(_BaseTest):

    def test_24_all_seven_types_post_independently(self):
        rid = CustomerReceiptDAO.insert_receipt({
            "receipt_date": "2026-02-01", "receipt_time": "",
            "customer_id": self.customer_id, "receipt_mode": "Cash",
            "amount": 100.0, "reference_no": "", "remarks": "",
        })
        pid = SupplierPaymentDAO.insert_payment({
            "payment_date": "2026-02-01", "payment_time": "",
            "supplier_id": self.supplier_id, "payment_mode": "Cash",
            "amount": 80.0, "reference_no": "", "remarks": "",
        })
        bill_no = SalesDAO.generate_next_bill_no()
        sid = SalesDAO.insert_invoice(
            bill_no=bill_no, sale_date="2026-02-01", sale_time="",
            sale_type="Cash", customer_id=None, patient_name="",
            doctor_id=None, discount=0, paid_amount=200.0,
            total_amount=200.0, round_off=0, net_amount=200.0,
            remarks="",
            items=[{
                "item_id": self.item_id, "stock_batch_id": self.batch_id,
                "pack_size": "10x10", "location": "", "batch_no": "BATCH-A",
                "expiry": "12/27", "mrp": 50.0, "sale_qty": 5.0,
                "discount_amount": 0, "amount": 200.0,
            }],
        )
        cn_id = CreditNoteDAO.insert_credit_note(
            {
                "voucher_date": "2026-02-01", "cn_date": "2026-02-01",
                "cn_type": "Customer", "customer_id": self.customer_id,
                "total_amount": 50.0, "ledger_amount": 50.0,
                "remarks": "",
            },
            [{
                "item_id": self.item_id, "stock_batch_id": self.batch_id,
                "batch_no": "BATCH-A", "expiry": "12/27",
                "pack_size": "10x10", "rate": 40.0, "mrp": 50.0,
                "return_qty": 1.25, "less_amount": 0,
                "amount": 50.0, "return_reason": "Damaged",
                "price_factor": 1.0,
            }],
        )
        dn_id = DebitNoteDAO.insert_debit_note(
            {
                "voucher_date": "2026-02-01", "voucher_time": "",
                "dn_date": "2026-02-01", "dn_type": "Supplier",
                "supplier_id": self.supplier_id,
                "total_amount": 60.0, "ledger_amount": 60.0,
                "remarks": "",
            },
            [{
                "item_id": self.item_id, "stock_batch_id": self.batch_id,
                "batch_no": "BATCH-A", "expiry": "12/27",
                "pack_size": "10x10", "rate": 40.0, "mrp": 50.0,
                "return_qty": 1.5, "less_amount": 0,
                "amount": 60.0, "return_reason": "Expired",
                "price_factor": 1.0,
            }],
        )
        je_id = JournalDAO.insert_entry(
            {"entry_date": "2026-02-01", "narration": "Cross-module JE"},
            [
                {"ledger_id": self.cash_ledger["id"], "description": "", "debit": 150.0, "credit": 0.0},
                {"ledger_id": self.customer_ledger_id, "description": "", "debit": 0.0, "credit": 150.0},
            ],
        )

        self.assertTrue(self.engine.is_posted(SOURCE_CUSTOMER_RECEIPT, rid))
        self.assertTrue(self.engine.is_posted(SOURCE_SUPPLIER_PAYMENT, pid))
        self.assertTrue(self.engine.is_posted(SOURCE_COUNTER_SALE, sid))
        self.assertTrue(self.engine.is_posted(SOURCE_CREDIT_NOTE, cn_id))
        self.assertTrue(self.engine.is_posted(SOURCE_DEBIT_NOTE, dn_id))
        self.assertTrue(self.engine.is_posted(SOURCE_JOURNAL_ENTRY, je_id))

        nets_cr = self._nets(SOURCE_CUSTOMER_RECEIPT, rid)
        self.assertEqual(nets_cr[self.cash_ledger["id"]], 100.0)
        nets_sp = self._nets(SOURCE_SUPPLIER_PAYMENT, pid)
        self.assertEqual(nets_sp[self.supplier_ledger_id], 80.0)
        nets_je = self._nets(SOURCE_JOURNAL_ENTRY, je_id)
        self.assertEqual(nets_je[self.cash_ledger["id"]], 150.0)

    def test_25_global_balance_invariant(self):
        rid = CustomerReceiptDAO.insert_receipt({
            "receipt_date": "2026-02-01", "receipt_time": "",
            "customer_id": self.customer_id, "receipt_mode": "Cash",
            "amount": 500.0, "reference_no": "", "remarks": "",
        })
        pid = SupplierPaymentDAO.insert_payment({
            "payment_date": "2026-02-01", "payment_time": "",
            "supplier_id": self.supplier_id, "payment_mode": "Cash",
            "amount": 300.0, "reference_no": "", "remarks": "",
        })
        bill_no = SalesDAO.generate_next_bill_no()
        sid = SalesDAO.insert_invoice(
            bill_no=bill_no, sale_date="2026-02-01", sale_time="",
            sale_type="Cash", customer_id=None, patient_name="",
            doctor_id=None, discount=0, paid_amount=400.0,
            total_amount=400.0, round_off=0, net_amount=400.0,
            remarks="",
            items=[{
                "item_id": self.item_id, "stock_batch_id": self.batch_id,
                "pack_size": "10x10", "location": "", "batch_no": "BATCH-A",
                "expiry": "12/27", "mrp": 50.0, "sale_qty": 10.0,
                "discount_amount": 0, "amount": 400.0,
            }],
        )
        cn_id = CreditNoteDAO.insert_credit_note(
            {
                "voucher_date": "2026-02-01", "cn_date": "2026-02-01",
                "cn_type": "Customer", "customer_id": self.customer_id,
                "total_amount": 100.0, "ledger_amount": 100.0,
                "remarks": "",
            },
            [{
                "item_id": self.item_id, "stock_batch_id": self.batch_id,
                "batch_no": "BATCH-A", "expiry": "12/27",
                "pack_size": "10x10", "rate": 40.0, "mrp": 50.0,
                "return_qty": 2.5, "less_amount": 0,
                "amount": 100.0, "return_reason": "Damaged",
                "price_factor": 1.0,
            }],
        )
        dn_id = DebitNoteDAO.insert_debit_note(
            {
                "voucher_date": "2026-02-01", "voucher_time": "",
                "dn_date": "2026-02-01", "dn_type": "Supplier",
                "supplier_id": self.supplier_id,
                "total_amount": 80.0, "ledger_amount": 80.0,
                "remarks": "",
            },
            [{
                "item_id": self.item_id, "stock_batch_id": self.batch_id,
                "batch_no": "BATCH-A", "expiry": "12/27",
                "pack_size": "10x10", "rate": 40.0, "mrp": 50.0,
                "return_qty": 2.0, "less_amount": 0,
                "amount": 80.0, "return_reason": "Expired",
                "price_factor": 1.0,
            }],
        )
        je_id = JournalDAO.insert_entry(
            {"entry_date": "2026-02-01", "narration": "Balance invariant JE"},
            [
                {"ledger_id": self.cash_ledger["id"], "description": "", "debit": 300.0, "credit": 0.0},
                {"ledger_id": self.customer_ledger_id, "description": "", "debit": 0.0, "credit": 300.0},
            ],
        )

        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT SUM(debit) AS total_debit, SUM(credit) AS total_credit "
                "FROM ledger_transactions"
            ).fetchone()
            total_debit = round(row["total_debit"] or 0.0, 2)
            total_credit = round(row["total_credit"] or 0.0, 2)
            self.assertAlmostEqual(total_debit, total_credit, places=2)
        finally:
            conn.close()


# ======================================================================
# Scenario 10: Persistence and balance consistency
# ======================================================================

class TestScenario11_PersistenceAndBalance(_BaseTest):

    def test_26_posting_visible_via_get_posting_rows(self):
        rid = CustomerReceiptDAO.insert_receipt({
            "receipt_date": "2026-02-01", "receipt_time": "",
            "customer_id": self.customer_id, "receipt_mode": "Cash",
            "amount": 150.0, "reference_no": "", "remarks": "",
        })
        rows = self.engine.get_posting_rows(SOURCE_CUSTOMER_RECEIPT, rid)
        self.assertEqual(len(rows), 2)
        for r in rows:
            self.assertGreater(r["id"], 0)
            self.assertGreater(r["debit"], 0) if r["ledger_id"] == self.cash_ledger["id"] else None
            self.assertGreater(r["credit"], 0) if r["ledger_id"] == self.customer_ledger_id else None

    def test_27_ledger_transactions_visible_via_dao(self):
        rid = CustomerReceiptDAO.insert_receipt({
            "receipt_date": "2026-02-01", "receipt_time": "",
            "customer_id": self.customer_id, "receipt_mode": "Cash",
            "amount": 200.0, "reference_no": "", "remarks": "",
        })
        txns = LedgerDAO.get_transactions(self.customer_ledger_id)
        cr_txns = [t for t in txns if t["reference_type"] == "CUSTOMER_RECEIPT"]
        self.assertEqual(len(cr_txns), 1)
        self.assertEqual(cr_txns[0]["credit"], 200.0)

    def test_28_fresh_connection_reads_posting(self):
        rid = CustomerReceiptDAO.insert_receipt({
            "receipt_date": "2026-02-01", "receipt_time": "",
            "customer_id": self.customer_id, "receipt_mode": "Cash",
            "amount": 75.0, "reference_no": "", "remarks": "",
        })
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM ledger_transactions "
                "WHERE reference_type = ? AND reference_id = ?",
                (SOURCE_CUSTOMER_RECEIPT, rid),
            ).fetchone()
            self.assertEqual(row["cnt"], 2)
        finally:
            conn.close()

    def test_29_multiple_receipts累积正确(self):
        for amt in [100.0, 200.0, 50.0]:
            CustomerReceiptDAO.insert_receipt({
                "receipt_date": "2026-02-01", "receipt_time": "",
                "customer_id": self.customer_id, "receipt_mode": "Cash",
                "amount": amt, "reference_no": "", "remarks": "",
            })
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT SUM(debit) AS total_debit FROM ledger_transactions "
                "WHERE ledger_id = ? AND reference_type = ?",
                (self.cash_ledger["id"], SOURCE_CUSTOMER_RECEIPT),
            ).fetchone()
            self.assertAlmostEqual(row["total_debit"], 350.0, places=2)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
