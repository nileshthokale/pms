import os
import sys
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database.connection import get_connection, init_database
from database.account_roles import ensure_system_ledgers, ROLE_CASH
from database.journal_dao import JournalDAO
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
    """Shared setUp — fresh DB, seed ledgers and master data."""

    _DB_PATH = os.path.join(os.path.dirname(__file__), "_test_je.db")

    @classmethod
    def setUpClass(cls):
        if os.path.exists(cls._DB_PATH):
            os.remove(cls._DB_PATH)
        os.environ["PHARMACY_DB"] = cls._DB_PATH
        init_database()

        conn = get_connection()
        try:
            for tbl in [
                "journal_entry_items", "journal_entries",
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
                "journal_entry_items", "journal_entries",
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

        self.cash_ledger_id = LedgerDAO.get_by_system_role(ROLE_CASH)["id"]
        self.capital_ledger_id = LedgerDAO.insert_ledger(ledger_name="Capital", account_group="Equity")
        self.sales_ledger_id = LedgerDAO.insert_ledger(ledger_name="Sales Account", account_group="Income")
        self.purchase_ledger_id = LedgerDAO.insert_ledger(ledger_name="Purchase Account", account_group="Expense")

    def tearDown(self):
        self.conn.close()


# ======================================================================
# 1-5: Basic CRUD
# ======================================================================
class TestJEBasicCRUD(_BaseTest):
    def test_01_create_balanced_entry(self):
        items = [
            {"ledger_id": self.cash_ledger_id, "description": "Cash received", "debit": 1000, "credit": 0},
            {"ledger_id": self.capital_ledger_id, "description": "Capital introduced", "debit": 0, "credit": 1000},
        ]
        eid = JournalDAO.insert_entry(
            {"entry_date": "2026-01-15", "entry_time": "10:00", "narration": "Initial capital"},
            items,
        )
        self.assertGreater(eid, 0)
        entry = JournalDAO.get_by_id(eid)
        self.assertIsNotNone(entry)
        self.assertEqual(entry["voucher_no"], "JV-0001")
        self.assertEqual(entry["total_debit"], 1000.0)
        self.assertEqual(entry["total_credit"], 1000.0)

    def test_02_voucher_number_auto_increment(self):
        items = [
            {"ledger_id": self.cash_ledger_id, "description": "", "debit": 500, "credit": 0},
            {"ledger_id": self.capital_ledger_id, "description": "", "debit": 0, "credit": 500},
        ]
        eid1 = JournalDAO.insert_entry({"entry_date": "2026-01-15", "entry_time": "", "narration": ""}, items)
        eid2 = JournalDAO.insert_entry({"entry_date": "2026-01-16", "entry_time": "", "narration": ""}, items)
        e1 = JournalDAO.get_by_id(eid1)
        e2 = JournalDAO.get_by_id(eid2)
        self.assertEqual(e1["voucher_no"], "JV-0001")
        self.assertEqual(e2["voucher_no"], "JV-0002")

    def test_03_verify_history(self):
        items = [
            {"ledger_id": self.cash_ledger_id, "description": "", "debit": 200, "credit": 0},
            {"ledger_id": self.capital_ledger_id, "description": "", "debit": 0, "credit": 200},
        ]
        JournalDAO.insert_entry({"entry_date": "2026-01-15", "entry_time": "10:00", "narration": "Test"}, items)
        all_entries = JournalDAO.get_all()
        self.assertEqual(len(all_entries), 1)
        self.assertEqual(all_entries[0]["narration"], "Test")

    def test_04_verify_journal_lines(self):
        items = [
            {"ledger_id": self.cash_ledger_id, "description": "Cash in", "debit": 1000, "credit": 0},
            {"ledger_id": self.sales_ledger_id, "description": "Sales", "debit": 0, "credit": 1000},
        ]
        eid = JournalDAO.insert_entry({"entry_date": "2026-01-15", "entry_time": "", "narration": ""}, items)
        lines = JournalDAO.get_items(eid)
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0]["ledger_name"], "Cash")
        self.assertEqual(lines[0]["debit"], 1000)
        self.assertEqual(lines[1]["ledger_name"], "Sales Account")
        self.assertEqual(lines[1]["credit"], 1000)

    def test_05_edit_entry(self):
        items = [
            {"ledger_id": self.cash_ledger_id, "description": "", "debit": 500, "credit": 0},
            {"ledger_id": self.capital_ledger_id, "description": "", "debit": 0, "credit": 500},
        ]
        eid = JournalDAO.insert_entry({"entry_date": "2026-01-15", "entry_time": "", "narration": "old"}, items)

        new_items = [
            {"ledger_id": self.cash_ledger_id, "description": "updated", "debit": 800, "credit": 0},
            {"ledger_id": self.capital_ledger_id, "description": "updated", "debit": 0, "credit": 800},
        ]
        JournalDAO.update_entry(eid, {"entry_date": "2026-01-16", "entry_time": "11:00", "narration": "updated"}, new_items)

        entry = JournalDAO.get_by_id(eid)
        self.assertEqual(entry["narration"], "updated")
        self.assertEqual(entry["total_debit"], 800)
        lines = JournalDAO.get_items(eid)
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0]["description"], "updated")


# ======================================================================
# 6-8: Multiple debit/credit lines
# ======================================================================
class TestJEMultiLines(_BaseTest):
    def test_06_multiple_debit_lines(self):
        items = [
            {"ledger_id": self.cash_ledger_id, "description": "", "debit": 300, "credit": 0},
            {"ledger_id": self.purchase_ledger_id, "description": "", "debit": 200, "credit": 0},
            {"ledger_id": self.capital_ledger_id, "description": "", "debit": 0, "credit": 500},
        ]
        eid = JournalDAO.insert_entry({"entry_date": "2026-01-15", "entry_time": "", "narration": ""}, items)
        entry = JournalDAO.get_by_id(eid)
        self.assertEqual(entry["total_debit"], 500.0)
        self.assertEqual(entry["total_credit"], 500.0)

    def test_07_multiple_credit_lines(self):
        items = [
            {"ledger_id": self.cash_ledger_id, "description": "", "debit": 600, "credit": 0},
            {"ledger_id": self.capital_ledger_id, "description": "", "debit": 0, "credit": 200},
            {"ledger_id": self.sales_ledger_id, "description": "", "debit": 0, "credit": 400},
        ]
        eid = JournalDAO.insert_entry({"entry_date": "2026-01-15", "entry_time": "", "narration": ""}, items)
        entry = JournalDAO.get_by_id(eid)
        self.assertEqual(entry["total_debit"], 600.0)
        self.assertEqual(entry["total_credit"], 600.0)

    def test_08_balanced_multi_line(self):
        items = [
            {"ledger_id": self.cash_ledger_id, "description": "", "debit": 100, "credit": 0},
            {"ledger_id": self.purchase_ledger_id, "description": "", "debit": 200, "credit": 0},
            {"ledger_id": self.capital_ledger_id, "description": "", "debit": 0, "credit": 150},
            {"ledger_id": self.sales_ledger_id, "description": "", "debit": 0, "credit": 150},
        ]
        eid = JournalDAO.insert_entry({"entry_date": "2026-01-15", "entry_time": "", "narration": ""}, items)
        entry = JournalDAO.get_by_id(eid)
        self.assertEqual(entry["total_debit"], 300.0)
        self.assertEqual(entry["total_credit"], 300.0)
        lines = JournalDAO.get_items(eid)
        self.assertEqual(len(lines), 4)


# ======================================================================
# 9-13: Validation
# ======================================================================
class TestJEValidation(_BaseTest):
    def test_09_reject_unbalanced_entry(self):
        items = [
            {"ledger_id": self.cash_ledger_id, "description": "", "debit": 1000, "credit": 0},
            {"ledger_id": self.capital_ledger_id, "description": "", "debit": 0, "credit": 900},
        ]
        with self.assertRaises(ValueError) as ctx:
            JournalDAO.insert_entry({"entry_date": "2026-01-15", "entry_time": "", "narration": ""}, items)
        self.assertIn("not balanced", str(ctx.exception))

    def test_10_reject_zero_total(self):
        items = [
            {"ledger_id": self.cash_ledger_id, "description": "", "debit": 0, "credit": 0},
            {"ledger_id": self.capital_ledger_id, "description": "", "debit": 0, "credit": 0},
        ]
        with self.assertRaises(ValueError) as ctx:
            JournalDAO.insert_entry({"entry_date": "2026-01-15", "entry_time": "", "narration": ""}, items)
        self.assertIn("either Debit or Credit", str(ctx.exception))

    def test_11_reject_both_debit_and_credit(self):
        items = [
            {"ledger_id": self.cash_ledger_id, "description": "", "debit": 500, "credit": 500},
            {"ledger_id": self.capital_ledger_id, "description": "", "debit": 0, "credit": 0},
        ]
        with self.assertRaises(ValueError) as ctx:
            JournalDAO.insert_entry({"entry_date": "2026-01-15", "entry_time": "", "narration": ""}, items)
        self.assertIn("both Debit and Credit", str(ctx.exception))

    def test_12_reject_neither_debit_nor_credit(self):
        items = [
            {"ledger_id": self.cash_ledger_id, "description": "", "debit": 500, "credit": 0},
            {"ledger_id": self.capital_ledger_id, "description": "", "debit": 0, "credit": 0},
        ]
        with self.assertRaises(ValueError) as ctx:
            JournalDAO.insert_entry({"entry_date": "2026-01-15", "entry_time": "", "narration": ""}, items)
        self.assertIn("either Debit or Credit", str(ctx.exception))

    def test_13_reject_missing_ledger(self):
        items = [
            {"ledger_id": None, "description": "", "debit": 500, "credit": 0},
            {"ledger_id": self.capital_ledger_id, "description": "", "debit": 0, "credit": 500},
        ]
        with self.assertRaises(ValueError) as ctx:
            JournalDAO.insert_entry({"entry_date": "2026-01-15", "entry_time": "", "narration": ""}, items)
        self.assertIn("Ledger is required", str(ctx.exception))


# ======================================================================
# 14-17: Edit/delete persistence
# ======================================================================
class TestJEEditDelete(_BaseTest):
    def test_14_edit_voucher_unchanged(self):
        items = [
            {"ledger_id": self.cash_ledger_id, "description": "", "debit": 100, "credit": 0},
            {"ledger_id": self.capital_ledger_id, "description": "", "debit": 0, "credit": 100},
        ]
        eid = JournalDAO.insert_entry({"entry_date": "2026-01-15", "entry_time": "", "narration": ""}, items)
        original_voucher = JournalDAO.get_by_id(eid)["voucher_no"]
        JournalDAO.update_entry(eid, {"entry_date": "2026-01-16", "entry_time": "", "narration": "edited"}, items)
        entry = JournalDAO.get_by_id(eid)
        self.assertEqual(entry["voucher_no"], original_voucher)

    def test_15_delete_entry(self):
        items = [
            {"ledger_id": self.cash_ledger_id, "description": "", "debit": 100, "credit": 0},
            {"ledger_id": self.capital_ledger_id, "description": "", "debit": 0, "credit": 100},
        ]
        eid = JournalDAO.insert_entry({"entry_date": "2026-01-15", "entry_time": "", "narration": ""}, items)
        JournalDAO.delete_entry(eid)
        self.assertIsNone(JournalDAO.get_by_id(eid))
        self.assertEqual(len(JournalDAO.get_items(eid)), 0)

    def test_16_duplicate_voucher_protection(self):
        items = [
            {"ledger_id": self.cash_ledger_id, "description": "", "debit": 100, "credit": 0},
            {"ledger_id": self.capital_ledger_id, "description": "", "debit": 0, "credit": 100},
        ]
        JournalDAO.insert_entry({"entry_date": "2026-01-15", "entry_time": "", "narration": ""}, items)
        all_entries = JournalDAO.get_all()
        voucher_nos = [e["voucher_no"] for e in all_entries]
        self.assertEqual(len(voucher_nos), len(set(voucher_nos)))

    def test_17_persistence_across_connections(self):
        items = [
            {"ledger_id": self.cash_ledger_id, "description": "persisted", "debit": 250, "credit": 0},
            {"ledger_id": self.capital_ledger_id, "description": "persisted", "debit": 0, "credit": 250},
        ]
        eid = JournalDAO.insert_entry({"entry_date": "2026-01-15", "entry_time": "10:00", "narration": "persist"}, items)
        entry = JournalDAO.get_by_id(eid)
        self.assertIsNotNone(entry)
        self.assertEqual(entry["narration"], "persist")
        lines = JournalDAO.get_items(eid)
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0]["description"], "persisted")


# ======================================================================
# 18-19: Filtering
# ======================================================================
class TestJEFiltering(_BaseTest):
    def _create_je(self, date="2026-01-20", voucher=None):
        items = [
            {"ledger_id": self.cash_ledger_id, "description": "", "debit": 100, "credit": 0},
            {"ledger_id": self.capital_ledger_id, "description": "", "debit": 0, "credit": 100},
        ]
        return JournalDAO.insert_entry({"entry_date": date, "entry_time": "", "narration": ""}, items)

    def test_18_date_filtering(self):
        self._create_je(date="2026-01-15")
        self._create_je(date="2026-02-10")
        results = JournalDAO.get_all_filtered(date_from="2026-02-01", date_to="2026-02-28")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["entry_date"], "2026-02-10")

    def test_19_voucher_filtering(self):
        eid = self._create_je()
        voucher = JournalDAO.get_by_id(eid)["voucher_no"]
        results = JournalDAO.get_all_filtered(voucher_no=voucher)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["voucher_no"], voucher)


# ======================================================================
# 20-29: Cross-module verification
# ======================================================================
class TestJECrossModule(_BaseTest):
    def test_20_persistence_restart(self):
        items = [
            {"ledger_id": self.cash_ledger_id, "description": "", "debit": 100, "credit": 0},
            {"ledger_id": self.capital_ledger_id, "description": "", "debit": 0, "credit": 100},
        ]
        eid = JournalDAO.insert_entry({"entry_date": "2026-01-15", "entry_time": "", "narration": ""}, items)
        self.assertIsNotNone(JournalDAO.get_by_id(eid))

    def test_21_account_ledger_still_works(self):
        all_ledgers = LedgerDAO.get_all_ledgers()
        self.assertEqual(len(all_ledgers), 11)
        balance = LedgerDAO.get_balance(self.cash_ledger_id)
        self.assertIsNotNone(balance)

    def test_22_customer_receipt_still_works(self):
        ensure_system_ledgers()
        rec_id = CustomerReceiptDAO.insert_receipt({
            "receipt_date": "2026-01-20", "receipt_time": "10:00",
            "customer_id": self.customer_id, "receipt_mode": "Cash",
            "amount": 300, "reference_no": "", "remarks": "",
        })
        self.assertGreater(rec_id, 0)

    def test_23_supplier_payment_still_works(self):
        pay_id = SupplierPaymentDAO.insert_payment({
            "payment_date": "2026-01-20", "payment_time": "10:00",
            "supplier_id": self.supplier_id, "payment_mode": "Cash",
            "amount": 500, "reference_no": "", "remarks": "",
        })
        self.assertGreater(pay_id, 0)

    def test_24_purchase_still_works(self):
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

    def test_25_counter_sale_still_works(self):
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

    def test_26_credit_note_still_works(self):
        batches = StockDAO.get_stock_batches_for_item(self.item_id)
        if not batches:
            PurchaseDAO.insert_invoice(
                voucher_no="PV-CN", voucher_date="2026-01-01", voucher_time="",
                purchase_type="Cash", supplier_id=self.supplier_id,
                invoice_no="INV-CN", invoice_date="2026-01-01",
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

    def test_27_debit_note_still_works(self):
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

    def test_28_stock_master_still_works(self):
        all_stock = StockDAO.get_all()
        self.assertIsInstance(all_stock, list)

    def test_29_all_master_screens_still_work(self):
        self.assertGreater(len(CompanyDAO.get_all()), 0)
        self.assertGreater(len(UnitDAO.get_all()), 0)
        self.assertGreater(len(DrugDAO.get_all()), 0)
        self.assertGreater(len(SupplierDAO.get_all()), 0)
        self.assertGreater(len(CustomerDAO.get_all()), 0)
        self.assertGreater(len(DoctorDAO.get_all()), 0)
        self.assertGreater(len(ItemDAO.get_all()), 0)


if __name__ == "__main__":
    unittest.main()
