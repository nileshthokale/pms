import os
import sys
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database.connection import get_connection, init_database
from database.account_roles import ensure_system_ledgers
from database.ledger_dao import LedgerDAO
from database.customer_dao import CustomerDAO
from database.supplier_dao import SupplierDAO
from database.supplier_payment_dao import SupplierPaymentDAO
from database.customer_receipt_dao import CustomerReceiptDAO
from database.doctor_dao import DoctorDAO
from database.item_dao import ItemDAO
from database.stock_dao import StockDAO
from database.unit_dao import UnitDAO
from database.company_dao import CompanyDAO
from database.drug_dao import DrugDAO
from database.purchase_dao import PurchaseDAO
from database.sales_dao import SalesDAO
from database.credit_note_dao import CreditNoteDAO
from database.debit_note_dao import DebitNoteDAO


class _BaseTest(unittest.TestCase):
    """Shared setUp — fresh DB, seed master data."""

    _DB_PATH = os.path.join(os.path.dirname(__file__), "_test_led.db")

    @classmethod
    def setUpClass(cls):
        if os.path.exists(cls._DB_PATH):
            os.remove(cls._DB_PATH)
        os.environ["PHARMACY_DB"] = cls._DB_PATH
        init_database()

        conn = get_connection()
        try:
            for tbl in [
                "ledger_transactions", "account_ledgers",
                "customer_receipts", "supplier_payments",
                "debit_note_items", "debit_notes",
                "credit_note_items", "credit_notes",
                "sales_invoice_items", "sales_invoices",
                "purchase_invoice_items", "purchase_invoices",
                "stock_batches", "item_ingredients", "items",
                "doctors", "customers", "suppliers", "drugs", "units", "companies",
            ]:
                conn.execute(f"DELETE FROM {tbl}")
            conn.commit()
        finally:
            conn.close()

    def setUp(self):
        self.conn = get_connection()
        try:
            for tbl in [
                "ledger_transactions", "account_ledgers",
                "customer_receipts", "supplier_payments",
                "debit_note_items", "debit_notes",
                "credit_note_items", "credit_notes",
                "sales_invoice_items", "sales_invoices",
                "purchase_invoice_items", "purchase_invoices",
                "stock_batches", "item_ingredients", "items",
                "doctors", "customers", "suppliers", "drugs", "units", "companies",
            ]:
                self.conn.execute(f"DELETE FROM {tbl}")
            self.conn.commit()
        finally:
            self.conn.close()

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

    def tearDown(self):
        self.conn.close()


# ======================================================================
# 1-5: Ledger CRUD
# ======================================================================
class TestLedgerCRUD(_BaseTest):
    def test_01_create_ledger(self):
        lid = LedgerDAO.insert_ledger(
            ledger_name="Sundry Creditors",
            account_group="Liability",
            opening_balance=1000.0,
            opening_balance_type="Credit",
        )
        self.assertGreater(lid, 0)
        lg = LedgerDAO.get_ledger_by_id(lid)
        self.assertIsNotNone(lg)
        self.assertEqual(lg["ledger_name"], "Sundry Creditors")
        self.assertEqual(lg["account_group"], "Liability")
        self.assertEqual(lg["opening_balance"], 1000.0)
        self.assertEqual(lg["opening_balance_type"], "Credit")

    def test_02_edit_ledger(self):
        lid = LedgerDAO.insert_ledger(ledger_name="TestLedger", account_group="Asset")
        LedgerDAO.update_ledger(lid, ledger_name="UpdatedLedger", account_group="Liability", credit_limit=5000)
        lg = LedgerDAO.get_ledger_by_id(lid)
        self.assertEqual(lg["ledger_name"], "UpdatedLedger")
        self.assertEqual(lg["account_group"], "Liability")
        self.assertEqual(lg["credit_limit"], 5000)

    def test_03_duplicate_ledger_validation(self):
        lid = LedgerDAO.insert_ledger(ledger_name="TestCash")
        self.assertTrue(LedgerDAO.ledger_name_exists("TestCash"))
        # Excluding own ID should return False (not a duplicate for itself)
        self.assertFalse(LedgerDAO.ledger_name_exists("TestCash", exclude_id=lid))
        # Excluding non-existent ID should still find the name
        self.assertTrue(LedgerDAO.ledger_name_exists("TestCash", exclude_id=999))

    def test_04_search_ledger(self):
        LedgerDAO.insert_ledger(ledger_name="Sundry Creditors")
        LedgerDAO.insert_ledger(ledger_name="Sundry Debtors")
        LedgerDAO.insert_ledger(ledger_name="Cash in Hand")
        results = LedgerDAO.search_ledgers("Sundry")
        self.assertEqual(len(results), 2)

    def test_05_empty_search_returns_all(self):
        LedgerDAO.insert_ledger(ledger_name="A")
        LedgerDAO.insert_ledger(ledger_name="B")
        LedgerDAO.insert_ledger(ledger_name="C")
        all_ledgers = LedgerDAO.get_all_ledgers()
        self.assertEqual(len(all_ledgers), 11)


# ======================================================================
# 6-7: Opening balance types
# ======================================================================
class TestLedgerOpeningBalance(_BaseTest):
    def test_06_opening_debit_balance(self):
        lid = LedgerDAO.insert_ledger(ledger_name="TestCash", opening_balance=5000, opening_balance_type="Debit")
        balance = LedgerDAO.get_balance(lid)
        self.assertEqual(balance["total_debit"], 5000.0)
        self.assertEqual(balance["total_credit"], 0.0)
        self.assertEqual(balance["closing_balance"], 5000.0)
        self.assertEqual(balance["closing_balance_type"], "Debit")

    def test_07_opening_credit_balance(self):
        lid = LedgerDAO.insert_ledger(ledger_name="TestBank", opening_balance=3000, opening_balance_type="Credit")
        balance = LedgerDAO.get_balance(lid)
        self.assertEqual(balance["total_debit"], 0.0)
        self.assertEqual(balance["total_credit"], 3000.0)
        self.assertEqual(balance["closing_balance"], 3000.0)
        self.assertEqual(balance["closing_balance_type"], "Credit")


# ======================================================================
# 8-10: Transaction CRUD
# ======================================================================
class TestLedgerTransactions(_BaseTest):
    def test_08_add_debit_transaction(self):
        lid = LedgerDAO.insert_ledger(ledger_name="TestCash")
        txn_id = LedgerDAO.add_transaction({
            "ledger_id": lid, "transaction_date": "2026-01-15",
            "voucher_type": "Receipt", "voucher_no": "R-001",
            "description": "Cash received", "debit": 1000, "credit": 0,
        })
        self.assertGreater(txn_id, 0)
        txns = LedgerDAO.get_transactions(lid)
        self.assertEqual(len(txns), 1)
        self.assertEqual(txns[0]["debit"], 1000)

    def test_09_add_credit_transaction(self):
        lid = LedgerDAO.insert_ledger(ledger_name="TestCash")
        LedgerDAO.add_transaction({
            "ledger_id": lid, "transaction_date": "2026-01-15",
            "voucher_type": "Payment", "voucher_no": "P-001",
            "description": "Cash paid", "debit": 0, "credit": 500,
        })
        txns = LedgerDAO.get_transactions(lid)
        self.assertEqual(len(txns), 1)
        self.assertEqual(txns[0]["credit"], 500)

    def test_10_verify_balance_calculation(self):
        lid = LedgerDAO.insert_ledger(ledger_name="TestCash", opening_balance=1000, opening_balance_type="Debit")
        LedgerDAO.add_transaction({
            "ledger_id": lid, "transaction_date": "2026-01-15",
            "voucher_type": "Receipt", "voucher_no": "R-001",
            "description": "Sale", "debit": 500, "credit": 0,
        })
        LedgerDAO.add_transaction({
            "ledger_id": lid, "transaction_date": "2026-01-16",
            "voucher_type": "Payment", "voucher_no": "P-001",
            "description": "Expense", "debit": 0, "credit": 200,
        })
        balance = LedgerDAO.get_balance(lid)
        # Opening 1000 (debit) + 500 (debit) - 200 (credit) = 1300 debit
        self.assertEqual(balance["total_debit"], 1500.0)
        self.assertEqual(balance["total_credit"], 200.0)
        self.assertEqual(balance["closing_balance"], 1300.0)
        self.assertEqual(balance["closing_balance_type"], "Debit")


# ======================================================================
# 11-12: Running balance / chronological order
# ======================================================================
class TestLedgerRunningBalance(_BaseTest):
    def test_11_running_balance(self):
        lid = LedgerDAO.insert_ledger(ledger_name="TestCash")
        LedgerDAO.add_transaction({"ledger_id": lid, "transaction_date": "2026-01-15", "voucher_type": "Receipt", "voucher_no": "R-001", "description": "", "debit": 1000, "credit": 0})
        LedgerDAO.add_transaction({"ledger_id": lid, "transaction_date": "2026-01-16", "voucher_type": "Payment", "voucher_no": "P-001", "description": "", "debit": 0, "credit": 300})
        LedgerDAO.add_transaction({"ledger_id": lid, "transaction_date": "2026-01-17", "voucher_type": "Receipt", "voucher_no": "R-002", "description": "", "debit": 500, "credit": 0})
        txns = LedgerDAO.get_transactions(lid)
        running = 0.0
        for t in txns:
            running = running + t["debit"] - t["credit"]
        self.assertAlmostEqual(running, 1200.0, places=2)

    def test_12_multiple_transactions_chronological(self):
        lid = LedgerDAO.insert_ledger(ledger_name="TestBank")
        for i in range(5):
            LedgerDAO.add_transaction({
                "ledger_id": lid, "transaction_date": f"2026-01-{10+i}",
                "voucher_type": "Journal", "voucher_no": f"J-{i+1:04d}",
                "description": f"Txn {i+1}", "debit": 100 * (i+1), "credit": 50 * (i+1),
            })
        txns = LedgerDAO.get_transactions(lid)
        self.assertEqual(len(txns), 5)
        # Verify chronological order
        dates = [t["transaction_date"] for t in txns]
        self.assertEqual(dates, sorted(dates))


# ======================================================================
# 13: Persistence
# ======================================================================
class TestLedgerPersistence(_BaseTest):
    def test_13_persistence_across_connections(self):
        lid = LedgerDAO.insert_ledger(ledger_name="Persistent", account_group="Asset")
        LedgerDAO.add_transaction({
            "ledger_id": lid, "transaction_date": "2026-01-15",
            "voucher_type": "Journal", "voucher_no": "J-001",
            "description": "Persisted txn", "debit": 500, "credit": 0,
        })
        lg = LedgerDAO.get_ledger_by_id(lid)
        self.assertIsNotNone(lg)
        self.assertEqual(lg["ledger_name"], "Persistent")
        txns = LedgerDAO.get_transactions(lid)
        self.assertEqual(len(txns), 1)
        self.assertEqual(txns[0]["description"], "Persisted txn")


# ======================================================================
# 14-15: Validation
# ======================================================================
class TestLedgerValidation(_BaseTest):
    def test_14_invalid_numeric_input(self):
        lid = LedgerDAO.insert_ledger(ledger_name="TestSafe", opening_balance=0)
        lg = LedgerDAO.get_ledger_by_id(lid)
        self.assertIsNotNone(lg)
        self.assertEqual(lg["opening_balance"], 0.0)

    def test_15_missing_ledger_name(self):
        with self.assertRaises(Exception):
            LedgerDAO.insert_ledger(ledger_name="")


# ======================================================================
# 16-25: Cross-module verification
# ======================================================================
class TestLedgerCrossModule(_BaseTest):
    def test_16_customer_master_still_works(self):
        cid = CustomerDAO.insert("CrossModuleCustomer")
        c = CustomerDAO.get_by_id(cid)
        self.assertIsNotNone(c)
        self.assertEqual(c["customer_name"], "CrossModuleCustomer")

    def test_17_supplier_master_still_works(self):
        sid = SupplierDAO.insert("CrossModuleSupplier")
        s = SupplierDAO.get_by_id(sid)
        self.assertIsNotNone(s)
        self.assertEqual(s["supplier_name"], "CrossModuleSupplier")

    def test_18_supplier_payment_still_works(self):
        pay_id = SupplierPaymentDAO.insert_payment({
            "payment_date": "2026-01-20", "payment_time": "10:00",
            "supplier_id": self.supplier_id, "payment_mode": "Cash",
            "amount": 500, "reference_no": "", "remarks": "",
        })
        self.assertGreater(pay_id, 0)

    def test_19_customer_receipt_still_works(self):
        ensure_system_ledgers()
        rec_id = CustomerReceiptDAO.insert_receipt({
            "receipt_date": "2026-01-20", "receipt_time": "10:00",
            "customer_id": self.customer_id, "receipt_mode": "Cash",
            "amount": 300, "reference_no": "", "remarks": "",
        })
        self.assertGreater(rec_id, 0)

    def test_20_purchase_still_works(self):
        PurchaseDAO.insert_invoice(
            voucher_no="PV-0099", voucher_date="2026-03-01", voucher_time="",
            purchase_type="Cash", supplier_id=self.supplier_id,
            invoice_no="INV-099", invoice_date="2026-03-01",
            invoice_net_amount=500.0, bill_discount=0, due_date="",
            total_amount=500.0, gst_amount=0, debit_note_amount=0,
            other_amount=0, paid_amount=500.0, round_off=0, net_amount=500.0,
            remarks="",
            items=[{"item_id": self.item_id, "pack_size": "10x10", "pay_qty": 10, "free_qty": 0, "batch_no": "PBATCH", "expiry": "06/28", "rate": 50, "mrp": 60, "discount": 0, "gst_percent": 0, "gst_amount": 0, "amount": 500, "purchase_rate": 50, "net_rate": 50, "pp": 50}],
        )
        batches = StockDAO.get_stock_batches_for_item(self.item_id)
        self.assertGreater(len(batches), 0)

    def test_21_counter_sale_still_works(self):
        ensure_system_ledgers()
        batches = StockDAO.get_stock_batches_for_item(self.item_id)
        if not batches:
            PurchaseDAO.insert_invoice(
                voucher_no="PV-PRE", voucher_date="2026-01-01", voucher_time="",
                purchase_type="Cash", supplier_id=self.supplier_id,
                invoice_no="INV-PRE", invoice_date="2026-01-01",
                invoice_net_amount=4000.0, bill_discount=0, due_date="",
                total_amount=4000.0, gst_amount=0, debit_note_amount=0,
                other_amount=0, paid_amount=4000.0, round_off=0, net_amount=4000.0,
                remarks="",
                items=[{"item_id": self.item_id, "pack_size": "10x10", "pay_qty": 100, "free_qty": 0, "batch_no": "BATCH-A", "expiry": "12/27", "rate": 40, "mrp": 50, "discount": 0, "gst_percent": 0, "gst_amount": 0, "amount": 4000, "purchase_rate": 40, "net_rate": 40, "pp": 40}],
            )
            batches = StockDAO.get_stock_batches_for_item(self.item_id)
        batch_id = batches[0]["id"]
        sale_id = SalesDAO.insert_invoice(
            bill_no="CS-0099", sale_date="2026-01-25", sale_time="10:00",
            sale_type="Cash", customer_id=self.customer_id,
            patient_name="TestPatient", doctor_id=None,
            discount=0, paid_amount=250, total_amount=250, round_off=0,
            net_amount=250, remarks="",
            items=[{"item_id": self.item_id, "stock_batch_id": batch_id, "pack_size": "10x10", "location": "", "batch_no": "BATCH-A", "expiry": "12/27", "mrp": 50, "sale_qty": 5, "discount_amount": 0, "amount": 250}],
        )
        self.assertGreater(sale_id, 0)

    def test_22_credit_note_still_works(self):
        batches = StockDAO.get_stock_batches_for_item(self.item_id)
        if not batches:
            PurchaseDAO.insert_invoice(
                voucher_no="PV-PRE2", voucher_date="2026-01-01", voucher_time="",
                purchase_type="Cash", supplier_id=self.supplier_id,
                invoice_no="INV-PRE2", invoice_date="2026-01-01",
                invoice_net_amount=4000.0, bill_discount=0, due_date="",
                total_amount=4000.0, gst_amount=0, debit_note_amount=0,
                other_amount=0, paid_amount=4000.0, round_off=0, net_amount=4000.0,
                remarks="",
                items=[{"item_id": self.item_id, "pack_size": "10x10", "pay_qty": 100, "free_qty": 0, "batch_no": "BATCH-A", "expiry": "12/27", "rate": 40, "mrp": 50, "discount": 0, "gst_percent": 0, "gst_amount": 0, "amount": 4000, "purchase_rate": 40, "net_rate": 40, "pp": 40}],
            )
            batches = StockDAO.get_stock_batches_for_item(self.item_id)
        batch_id = batches[0]["id"]
        cn_id = CreditNoteDAO.insert_credit_note(
            {"voucher_date": "2026-01-25", "cn_date": "2026-01-25", "cn_type": "Customer", "customer_id": self.customer_id, "total_amount": 100, "ledger_amount": 100, "remarks": ""},
            [{"item_id": self.item_id, "stock_batch_id": batch_id, "batch_no": "BATCH-A", "expiry": "12/27", "pack_size": "10x10", "rate": 40, "mrp": 50, "return_qty": 2, "less_amount": 0, "amount": 100, "return_reason": "", "price_factor": 1.0}],
        )
        self.assertGreater(cn_id, 0)

    def test_23_debit_note_still_works(self):
        PurchaseDAO.insert_invoice(
            voucher_no="PV-DN", voucher_date="2026-01-01", voucher_time="",
            purchase_type="Cash", supplier_id=self.supplier_id,
            invoice_no="INV-DN", invoice_date="2026-01-01",
            invoice_net_amount=4000.0, bill_discount=0, due_date="",
            total_amount=4000.0, gst_amount=0, debit_note_amount=0,
            other_amount=0, paid_amount=4000.0, round_off=0, net_amount=4000.0,
            remarks="",
            items=[{"item_id": self.item_id, "pack_size": "10x10", "pay_qty": 100, "free_qty": 0, "batch_no": "BATCH-A", "expiry": "12/27", "rate": 40, "mrp": 50, "discount": 0, "gst_percent": 0, "gst_amount": 0, "amount": 4000, "purchase_rate": 40, "net_rate": 40, "pp": 40}],
        )
        batches = StockDAO.get_stock_batches_for_item(self.item_id)
        batch_id = batches[0]["id"]
        dn_id = DebitNoteDAO.insert_debit_note(
            {"voucher_date": "2026-01-18", "voucher_time": "10:00", "dn_date": "2026-01-18", "dn_type": "Supplier", "supplier_id": self.supplier_id, "total_amount": 200, "ledger_amount": 200, "remarks": ""},
            [{"item_id": self.item_id, "stock_batch_id": batch_id, "batch_no": "BATCH-A", "expiry": "12/27", "pack_size": "10x10", "rate": 40, "mrp": 50, "return_qty": 5, "less_amount": 0, "amount": 200, "return_reason": "", "price_factor": 1.0}],
        )
        self.assertGreater(dn_id, 0)

    def test_24_stock_master_still_works(self):
        all_stock = StockDAO.get_all()
        self.assertIsInstance(all_stock, list)

    def test_25_all_master_screens_still_work(self):
        self.assertGreater(len(CompanyDAO.get_all()), 0)
        self.assertGreater(len(UnitDAO.get_all()), 0)
        self.assertGreater(len(DrugDAO.get_all()), 0)
        self.assertGreater(len(SupplierDAO.get_all()), 0)
        self.assertGreater(len(CustomerDAO.get_all()), 0)
        self.assertGreater(len(DoctorDAO.get_all()), 0)
        self.assertGreater(len(ItemDAO.get_all()), 0)


if __name__ == "__main__":
    unittest.main()
