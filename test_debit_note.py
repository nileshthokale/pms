import os
import sys
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database.connection import get_connection, init_database
from database.account_roles import ensure_system_ledgers
from database.debit_note_dao import DebitNoteDAO
from database.customer_dao import CustomerDAO
from database.doctor_dao import DoctorDAO
from database.item_dao import ItemDAO
from database.stock_dao import StockDAO
from database.unit_dao import UnitDAO
from database.company_dao import CompanyDAO
from database.drug_dao import DrugDAO
from database.purchase_dao import PurchaseDAO
from database.sales_dao import SalesDAO
from database.credit_note_dao import CreditNoteDAO
from database.supplier_dao import SupplierDAO


class _BaseTest(unittest.TestCase):
    """Shared setUp — fresh DB, seed master data, and a stock batch."""

    _DB_PATH = os.path.join(os.path.dirname(__file__), "_test_dn.db")

    @classmethod
    def setUpClass(cls):
        if os.path.exists(cls._DB_PATH):
            os.remove(cls._DB_PATH)
        os.environ["PHARMACY_DB"] = cls._DB_PATH
        init_database()

        conn = get_connection()
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            for tbl in [
                "debit_note_items", "debit_notes",
                "credit_note_items", "credit_notes",
                "sales_invoice_items", "sales_invoices",
                "purchase_invoice_items", "purchase_invoices",
                "ledger_transactions", "account_ledgers",
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
                "debit_note_items", "debit_notes",
                "credit_note_items", "credit_notes",
                "sales_invoice_items", "sales_invoices",
                "purchase_invoice_items", "purchase_invoices",
                "ledger_transactions", "account_ledgers",
                "stock_batches", "item_ingredients", "items",
                "doctors", "customers", "suppliers", "drugs", "units", "companies",
            ]:
                self.conn.execute(f"DELETE FROM {tbl}")
            self.conn.commit()
        finally:
            self.conn.close()

        self.company_id = CompanyDAO.insert("TestCo", "TC")
        self.unit_id = UnitDAO.insert("Pcs")
        self.drug_id = DrugDAO.insert("Paracetamol")
        self.customer_id = CustomerDAO.insert("TestCustomer")
        self.doctor_id = DoctorDAO.insert("Dr. Smith")
        self.supplier_id = SupplierDAO.insert("TestSupplier")

        self.item_id = ItemDAO.insert(
            item_name="TestItem",
            unit_id=self.unit_id,
            company_id=self.company_id,
            pack_size="10x10",
            reorder_stock_level=10,
        )

        ensure_system_ledgers()

        PurchaseDAO.insert_invoice(
            voucher_no="PV-0001", voucher_date="2026-01-15", voucher_time="",
            purchase_type="Cash", supplier_id=self.supplier_id,
            invoice_no="INV-001", invoice_date="2026-01-15",
            invoice_net_amount=4000.0, bill_discount=0, due_date="",
            total_amount=4000.0, gst_amount=0, debit_note_amount=0,
            other_amount=0, paid_amount=4000.0, round_off=0, net_amount=4000.0,
            remarks="Initial purchase",
            items=[{
                "item_id": self.item_id, "pack_size": "10x10",
                "pay_qty": 100, "free_qty": 0,
                "batch_no": "BATCH-A", "expiry": "12/27",
                "rate": 40.0, "mrp": 50.0, "discount": 0,
                "gst_percent": 0, "gst_amount": 0, "amount": 4000.0,
                "purchase_rate": 40.0, "net_rate": 40.0, "pp": 40.0,
            }],
        )

        batches = StockDAO.get_stock_batches_for_item(self.item_id)
        self.batch_id = batches[0]["id"] if batches else None
        self.assertIsNotNone(self.batch_id, "Stock batch must exist after purchase")

    def tearDown(self):
        self.conn.close()


# ======================================================================
# 1-6: Basic CRUD
# ======================================================================
class TestDNBasicCRUD(_BaseTest):
    def test_01_create_debit_note(self):
        header = {
            "voucher_date": "2026-01-20", "voucher_time": "10:00",
            "dn_date": "2026-01-20", "dn_type": "Supplier",
            "supplier_id": self.supplier_id,
            "total_amount": 400.0, "ledger_amount": 400.0,
            "remarks": "Returned damaged goods to supplier",
        }
        items = [{
            "item_id": self.item_id, "stock_batch_id": self.batch_id,
            "batch_no": "BATCH-A", "expiry": "12/27", "pack_size": "10x10",
            "rate": 40.0, "mrp": 50.0, "return_qty": 10,
            "less_amount": 0, "amount": 400.0,
            "return_reason": "Damaged", "price_factor": 1.0,
        }]
        dn_id = DebitNoteDAO.insert_debit_note(header, items)
        self.assertGreater(dn_id, 0)

        dn = DebitNoteDAO.get_by_id(dn_id)
        self.assertIsNotNone(dn)
        self.assertEqual(dn["voucher_no"], "DN-0001")
        self.assertEqual(dn["total_amount"], 400.0)

    def test_02_voucher_number_auto_increment(self):
        h1 = {"voucher_date": "2026-01-20", "voucher_time": "10:00", "dn_date": "2026-01-20", "dn_type": "Supplier", "supplier_id": self.supplier_id, "total_amount": 80, "ledger_amount": 80, "remarks": ""}
        i1 = [{"item_id": self.item_id, "stock_batch_id": self.batch_id, "batch_no": "BATCH-A", "expiry": "12/27", "pack_size": "10x10", "rate": 40, "mrp": 50, "return_qty": 2, "less_amount": 0, "amount": 80, "return_reason": "", "price_factor": 1.0}]
        dn1_id = DebitNoteDAO.insert_debit_note(h1, i1)

        h2 = {"voucher_date": "2026-01-21", "voucher_time": "11:00", "dn_date": "2026-01-21", "dn_type": "Supplier", "supplier_id": self.supplier_id, "total_amount": 160, "ledger_amount": 160, "remarks": ""}
        i2 = [{"item_id": self.item_id, "stock_batch_id": self.batch_id, "batch_no": "BATCH-A", "expiry": "12/27", "pack_size": "10x10", "rate": 40, "mrp": 50, "return_qty": 4, "less_amount": 0, "amount": 160, "return_reason": "", "price_factor": 1.0}]
        dn2_id = DebitNoteDAO.insert_debit_note(h2, i2)

        dn1 = DebitNoteDAO.get_by_id(dn1_id)
        dn2 = DebitNoteDAO.get_by_id(dn2_id)
        self.assertEqual(dn1["voucher_no"], "DN-0001")
        self.assertEqual(dn2["voucher_no"], "DN-0002")

    def test_03_stock_decreases_on_insert(self):
        before = StockDAO.get_stock_batch_by_id(self.batch_id)["stock_qty"]
        header = {"voucher_date": "2026-01-20", "voucher_time": "10:00", "dn_date": "2026-01-20", "dn_type": "Supplier", "supplier_id": self.supplier_id, "total_amount": 400, "ledger_amount": 400, "remarks": ""}
        items = [{"item_id": self.item_id, "stock_batch_id": self.batch_id, "batch_no": "BATCH-A", "expiry": "12/27", "pack_size": "10x10", "rate": 40, "mrp": 50, "return_qty": 10, "less_amount": 0, "amount": 400, "return_reason": "", "price_factor": 1.0}]
        DebitNoteDAO.insert_debit_note(header, items)
        after = StockDAO.get_stock_batch_by_id(self.batch_id)["stock_qty"]
        self.assertAlmostEqual(after, before - 10, places=2)

    def test_04_multiple_items(self):
        item2_id = ItemDAO.insert(item_name="Item2", unit_id=self.unit_id, company_id=self.company_id, pack_size="5x5", reorder_stock_level=5)
        PurchaseDAO.insert_invoice(
            voucher_no="PV-0002", voucher_date="2026-01-15", voucher_time="",
            purchase_type="Cash", supplier_id=self.supplier_id,
            invoice_no="INV-002", invoice_date="2026-01-15",
            invoice_net_amount=1000.0, bill_discount=0, due_date="",
            total_amount=1000.0, gst_amount=0, debit_note_amount=0,
            other_amount=0, paid_amount=1000.0, round_off=0, net_amount=1000.0,
            remarks="",
            items=[{"item_id": item2_id, "pack_size": "5x5", "pay_qty": 50, "free_qty": 0, "batch_no": "BATCH-B", "expiry": "06/27", "rate": 20, "mrp": 30, "discount": 0, "gst_percent": 0, "gst_amount": 0, "amount": 1000, "purchase_rate": 20, "net_rate": 20, "pp": 20}],
        )
        batches2 = StockDAO.get_stock_batches_for_item(item2_id)
        batch2_id = batches2[0]["id"]

        header = {"voucher_date": "2026-01-20", "voucher_time": "10:00", "dn_date": "2026-01-20", "dn_type": "Supplier", "supplier_id": self.supplier_id, "total_amount": 600, "ledger_amount": 600, "remarks": ""}
        items = [
            {"item_id": self.item_id, "stock_batch_id": self.batch_id, "batch_no": "BATCH-A", "expiry": "12/27", "pack_size": "10x10", "rate": 40, "mrp": 50, "return_qty": 5, "less_amount": 0, "amount": 200, "return_reason": "Damaged", "price_factor": 1.0},
            {"item_id": item2_id, "stock_batch_id": batch2_id, "batch_no": "BATCH-B", "expiry": "06/27", "pack_size": "5x5", "rate": 20, "mrp": 30, "return_qty": 20, "less_amount": 0, "amount": 400, "return_reason": "Wrong item", "price_factor": 1.0},
        ]
        dn_id = DebitNoteDAO.insert_debit_note(header, items)
        dn_items = DebitNoteDAO.get_items(dn_id)
        self.assertEqual(len(dn_items), 2)

    def test_05_edit_debit_note(self):
        header = {"voucher_date": "2026-01-20", "voucher_time": "10:00", "dn_date": "2026-01-20", "dn_type": "Supplier", "supplier_id": self.supplier_id, "total_amount": 200, "ledger_amount": 200, "remarks": "old"}
        items = [{"item_id": self.item_id, "stock_batch_id": self.batch_id, "batch_no": "BATCH-A", "expiry": "12/27", "pack_size": "10x10", "rate": 40, "mrp": 50, "return_qty": 5, "less_amount": 0, "amount": 200, "return_reason": "", "price_factor": 1.0}]
        dn_id = DebitNoteDAO.insert_debit_note(header, items)
        before = StockDAO.get_stock_batch_by_id(self.batch_id)["stock_qty"]

        new_header = {"voucher_date": "2026-01-21", "voucher_time": "11:00", "dn_date": "2026-01-21", "dn_type": "Supplier", "supplier_id": self.supplier_id, "total_amount": 400, "ledger_amount": 400, "remarks": "updated"}
        new_items = [{"item_id": self.item_id, "stock_batch_id": self.batch_id, "batch_no": "BATCH-A", "expiry": "12/27", "pack_size": "10x10", "rate": 40, "mrp": 50, "return_qty": 10, "less_amount": 0, "amount": 400, "return_reason": "Changed mind", "price_factor": 1.0}]
        DebitNoteDAO.update_debit_note(dn_id, new_header, new_items)

        after = StockDAO.get_stock_batch_by_id(self.batch_id)["stock_qty"]
        self.assertAlmostEqual(after, before + 5 - 10, places=2)

        dn = DebitNoteDAO.get_by_id(dn_id)
        self.assertEqual(dn["remarks"], "updated")
        self.assertEqual(dn["total_amount"], 400)

    def test_06_delete_debit_note(self):
        header = {"voucher_date": "2026-01-20", "voucher_time": "10:00", "dn_date": "2026-01-20", "dn_type": "Supplier", "supplier_id": self.supplier_id, "total_amount": 400, "ledger_amount": 400, "remarks": ""}
        items = [{"item_id": self.item_id, "stock_batch_id": self.batch_id, "batch_no": "BATCH-A", "expiry": "12/27", "pack_size": "10x10", "rate": 40, "mrp": 50, "return_qty": 10, "less_amount": 0, "amount": 400, "return_reason": "", "price_factor": 1.0}]
        dn_id = DebitNoteDAO.insert_debit_note(header, items)

        before = StockDAO.get_stock_batch_by_id(self.batch_id)["stock_qty"]
        DebitNoteDAO.delete_debit_note(dn_id)
        after = StockDAO.get_stock_batch_by_id(self.batch_id)["stock_qty"]

        self.assertEqual(after - before, 10)
        self.assertIsNone(DebitNoteDAO.get_by_id(dn_id))


# ======================================================================
# 7-9: Filtering
# ======================================================================
class TestDNFiltering(_BaseTest):
    def _create_dn(self, date="2026-01-20", sup_id=None, remarks=""):
        header = {"voucher_date": date, "voucher_time": "10:00", "dn_date": date, "dn_type": "Supplier", "supplier_id": sup_id or self.supplier_id, "total_amount": 200, "ledger_amount": 200, "remarks": remarks}
        items = [{"item_id": self.item_id, "stock_batch_id": self.batch_id, "batch_no": "BATCH-A", "expiry": "12/27", "pack_size": "10x10", "rate": 40, "mrp": 50, "return_qty": 5, "less_amount": 0, "amount": 200, "return_reason": "", "price_factor": 1.0}]
        return DebitNoteDAO.insert_debit_note(header, items)

    def test_07_filter_by_voucher_date(self):
        self._create_dn(date="2026-01-15")
        self._create_dn(date="2026-02-10")
        results = DebitNoteDAO.get_all_filtered(voucher_from="2026-02-01", voucher_to="2026-02-28")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["voucher_date"], "2026-02-10")

    def test_08_filter_by_supplier(self):
        sup2_id = SupplierDAO.insert("SupTwo")
        self._create_dn(sup_id=self.supplier_id)
        self._create_dn(sup_id=sup2_id)
        results = DebitNoteDAO.get_all_filtered(party="SupTwo")
        self.assertEqual(len(results), 1)

    def test_09_filter_by_voucher_no(self):
        self._create_dn()
        self._create_dn()
        results = DebitNoteDAO.get_all_filtered(voucher_no="DN-0001")
        self.assertEqual(len(results), 1)


# ======================================================================
# 10-12: Validation
# ======================================================================
class TestDNValidation(_BaseTest):
    def test_10_missing_supplier_raises(self):
        header = {"voucher_date": "2026-01-20", "voucher_time": "10:00", "dn_date": "2026-01-20", "dn_type": "Supplier", "supplier_id": None, "total_amount": 0, "ledger_amount": 0, "remarks": ""}
        items = [{"item_id": self.item_id, "stock_batch_id": self.batch_id, "batch_no": "BATCH-A", "expiry": "12/27", "pack_size": "10x10", "rate": 40, "mrp": 50, "return_qty": 5, "less_amount": 0, "amount": 200, "return_reason": "", "price_factor": 1.0}]
        with self.assertRaises(Exception):
            DebitNoteDAO.insert_debit_note(header, items)

    def test_11_insufficient_stock_raises(self):
        header = {"voucher_date": "2026-01-20", "voucher_time": "10:00", "dn_date": "2026-01-20", "dn_type": "Supplier", "supplier_id": self.supplier_id, "total_amount": 8000, "ledger_amount": 8000, "remarks": ""}
        items = [{"item_id": self.item_id, "stock_batch_id": self.batch_id, "batch_no": "BATCH-A", "expiry": "12/27", "pack_size": "10x10", "rate": 40, "mrp": 50, "return_qty": 200, "less_amount": 0, "amount": 8000, "return_reason": "", "price_factor": 1.0}]
        with self.assertRaises(ValueError) as ctx:
            DebitNoteDAO.insert_debit_note(header, items)
        self.assertIn("Insufficient stock", str(ctx.exception))

    def test_12_return_qty_zero_raises(self):
        header = {"voucher_date": "2026-01-20", "voucher_time": "10:00", "dn_date": "2026-01-20", "dn_type": "Supplier", "supplier_id": self.supplier_id, "total_amount": 0, "ledger_amount": 0, "remarks": ""}
        items = [{"item_id": self.item_id, "stock_batch_id": self.batch_id, "batch_no": "BATCH-A", "expiry": "12/27", "pack_size": "10x10", "rate": 40, "mrp": 50, "return_qty": 0, "less_amount": 0, "amount": 0, "return_reason": "", "price_factor": 1.0}]
        with self.assertRaises(ValueError) as ctx:
            DebitNoteDAO.insert_debit_note(header, items)
        self.assertIn("greater than 0", str(ctx.exception))


# ======================================================================
# 13-16: Features
# ======================================================================
class TestDNFeatures(_BaseTest):
    def test_13_less_amount(self):
        header = {"voucher_date": "2026-01-20", "voucher_time": "10:00", "dn_date": "2026-01-20", "dn_type": "Supplier", "supplier_id": self.supplier_id, "total_amount": 380, "ledger_amount": 380, "remarks": ""}
        items = [{"item_id": self.item_id, "stock_batch_id": self.batch_id, "batch_no": "BATCH-A", "expiry": "12/27", "pack_size": "10x10", "rate": 40, "mrp": 50, "return_qty": 10, "less_amount": 20, "amount": 380, "return_reason": "partial", "price_factor": 1.0}]
        dn_id = DebitNoteDAO.insert_debit_note(header, items)
        dn_items = DebitNoteDAO.get_items(dn_id)
        self.assertEqual(dn_items[0]["less_amount"], 20)
        self.assertEqual(dn_items[0]["amount"], 380)

    def test_14_dn_type_supplier(self):
        header = {"voucher_date": "2026-01-20", "voucher_time": "10:00", "dn_date": "2026-01-20", "dn_type": "Supplier", "supplier_id": self.supplier_id, "total_amount": 200, "ledger_amount": 200, "remarks": ""}
        items = [{"item_id": self.item_id, "stock_batch_id": self.batch_id, "batch_no": "BATCH-A", "expiry": "12/27", "pack_size": "10x10", "rate": 40, "mrp": 50, "return_qty": 5, "less_amount": 0, "amount": 200, "return_reason": "", "price_factor": 1.0}]
        dn_id = DebitNoteDAO.insert_debit_note(header, items)
        dn = DebitNoteDAO.get_by_id(dn_id)
        self.assertEqual(dn["dn_type"], "Supplier")

    def test_15_dn_date_separate(self):
        header = {"voucher_date": "2026-01-20", "voucher_time": "10:00", "dn_date": "2026-01-25", "dn_type": "Supplier", "supplier_id": self.supplier_id, "total_amount": 200, "ledger_amount": 200, "remarks": ""}
        items = [{"item_id": self.item_id, "stock_batch_id": self.batch_id, "batch_no": "BATCH-A", "expiry": "12/27", "pack_size": "10x10", "rate": 40, "mrp": 50, "return_qty": 5, "less_amount": 0, "amount": 200, "return_reason": "", "price_factor": 1.0}]
        dn_id = DebitNoteDAO.insert_debit_note(header, items)
        dn = DebitNoteDAO.get_by_id(dn_id)
        self.assertEqual(dn["voucher_date"], "2026-01-20")
        self.assertEqual(dn["dn_date"], "2026-01-25")

    def test_16_remarks_persisted(self):
        header = {"voucher_date": "2026-01-20", "voucher_time": "10:00", "dn_date": "2026-01-20", "dn_type": "Supplier", "supplier_id": self.supplier_id, "total_amount": 200, "ledger_amount": 200, "remarks": "Returned expired tablets to supplier"}
        items = [{"item_id": self.item_id, "stock_batch_id": self.batch_id, "batch_no": "BATCH-A", "expiry": "12/27", "pack_size": "10x10", "rate": 40, "mrp": 50, "return_qty": 5, "less_amount": 0, "amount": 200, "return_reason": "", "price_factor": 1.0}]
        dn_id = DebitNoteDAO.insert_debit_note(header, items)
        dn = DebitNoteDAO.get_by_id(dn_id)
        self.assertEqual(dn["remarks"], "Returned expired tablets to supplier")


# ======================================================================
# 17-19: Persistence / item-level
# ======================================================================
class TestDNPersistence(_BaseTest):
    def test_17_items_persisted(self):
        header = {"voucher_date": "2026-01-20", "voucher_time": "10:00", "dn_date": "2026-01-20", "dn_type": "Supplier", "supplier_id": self.supplier_id, "total_amount": 200, "ledger_amount": 200, "remarks": ""}
        items = [{"item_id": self.item_id, "stock_batch_id": self.batch_id, "batch_no": "BATCH-A", "expiry": "12/27", "pack_size": "10x10", "rate": 40, "mrp": 50, "return_qty": 5, "less_amount": 0, "amount": 200, "return_reason": "Damaged", "price_factor": 1.0}]
        dn_id = DebitNoteDAO.insert_debit_note(header, items)
        dn_items = DebitNoteDAO.get_items(dn_id)
        self.assertEqual(len(dn_items), 1)
        self.assertEqual(dn_items[0]["item_name"], "TestItem")
        self.assertEqual(dn_items[0]["return_reason"], "Damaged")

    def test_18_multiple_dns(self):
        for i in range(5):
            header = {"voucher_date": f"2026-01-{10+i}", "voucher_time": "10:00", "dn_date": f"2026-01-{10+i}", "dn_type": "Supplier", "supplier_id": self.supplier_id, "total_amount": 40, "ledger_amount": 40, "remarks": f"DN {i+1}"}
            items = [{"item_id": self.item_id, "stock_batch_id": self.batch_id, "batch_no": "BATCH-A", "expiry": "12/27", "pack_size": "10x10", "rate": 40, "mrp": 50, "return_qty": 1, "less_amount": 0, "amount": 40, "return_reason": "", "price_factor": 1.0}]
            DebitNoteDAO.insert_debit_note(header, items)
        all_dns = DebitNoteDAO.get_all()
        self.assertEqual(len(all_dns), 5)
        self.assertEqual(all_dns[0]["voucher_no"], "DN-0005")

    def test_19_delete_restores_stock(self):
        header = {"voucher_date": "2026-01-20", "voucher_time": "10:00", "dn_date": "2026-01-20", "dn_type": "Supplier", "supplier_id": self.supplier_id, "total_amount": 1000, "ledger_amount": 1000, "remarks": ""}
        items = [{"item_id": self.item_id, "stock_batch_id": self.batch_id, "batch_no": "BATCH-A", "expiry": "12/27", "pack_size": "10x10", "rate": 40, "mrp": 50, "return_qty": 25, "less_amount": 0, "amount": 1000, "return_reason": "", "price_factor": 1.0}]
        dn_id = DebitNoteDAO.insert_debit_note(header, items)
        before = StockDAO.get_stock_batch_by_id(self.batch_id)["stock_qty"]
        DebitNoteDAO.delete_debit_note(dn_id)
        after = StockDAO.get_stock_batch_by_id(self.batch_id)["stock_qty"]
        self.assertAlmostEqual(after - before, 25, places=2)


# ======================================================================
# 20-22: Edit stock reversal
# ======================================================================
class TestDNEditStock(_BaseTest):
    def test_20_edit_reverses_old_deduction(self):
        header = {"voucher_date": "2026-01-20", "voucher_time": "10:00", "dn_date": "2026-01-20", "dn_type": "Supplier", "supplier_id": self.supplier_id, "total_amount": 400, "ledger_amount": 400, "remarks": ""}
        items = [{"item_id": self.item_id, "stock_batch_id": self.batch_id, "batch_no": "BATCH-A", "expiry": "12/27", "pack_size": "10x10", "rate": 40, "mrp": 50, "return_qty": 10, "less_amount": 0, "amount": 400, "return_reason": "", "price_factor": 1.0}]
        dn_id = DebitNoteDAO.insert_debit_note(header, items)
        before = StockDAO.get_stock_batch_by_id(self.batch_id)["stock_qty"]

        new_header = {"voucher_date": "2026-01-21", "voucher_time": "11:00", "dn_date": "2026-01-21", "dn_type": "Supplier", "supplier_id": self.supplier_id, "total_amount": 200, "ledger_amount": 200, "remarks": ""}
        new_items = [{"item_id": self.item_id, "stock_batch_id": self.batch_id, "batch_no": "BATCH-A", "expiry": "12/27", "pack_size": "10x10", "rate": 40, "mrp": 50, "return_qty": 5, "less_amount": 0, "amount": 200, "return_reason": "", "price_factor": 1.0}]
        DebitNoteDAO.update_debit_note(dn_id, new_header, new_items)
        after = StockDAO.get_stock_batch_by_id(self.batch_id)["stock_qty"]
        self.assertAlmostEqual(after, before + 10 - 5, places=2)

    def test_21_rate_from_purchase_rate(self):
        header = {"voucher_date": "2026-01-20", "voucher_time": "10:00", "dn_date": "2026-01-20", "dn_type": "Supplier", "supplier_id": self.supplier_id, "total_amount": 400, "ledger_amount": 400, "remarks": ""}
        items = [{"item_id": self.item_id, "stock_batch_id": self.batch_id, "batch_no": "BATCH-A", "expiry": "12/27", "pack_size": "10x10", "rate": 40, "mrp": 50, "return_qty": 10, "less_amount": 0, "amount": 400, "return_reason": "", "price_factor": 1.0}]
        dn_id = DebitNoteDAO.insert_debit_note(header, items)
        dn_items = DebitNoteDAO.get_items(dn_id)
        self.assertEqual(dn_items[0]["rate"], 40.0)

    def test_22_amount_calculation(self):
        header = {"voucher_date": "2026-01-20", "voucher_time": "10:00", "dn_date": "2026-01-20", "dn_type": "Supplier", "supplier_id": self.supplier_id, "total_amount": 380, "ledger_amount": 380, "remarks": ""}
        items = [{"item_id": self.item_id, "stock_batch_id": self.batch_id, "batch_no": "BATCH-A", "expiry": "12/27", "pack_size": "10x10", "rate": 40, "mrp": 50, "return_qty": 10, "less_amount": 20, "amount": 380, "return_reason": "", "price_factor": 1.0}]
        dn_id = DebitNoteDAO.insert_debit_note(header, items)
        dn_items = DebitNoteDAO.get_items(dn_id)
        self.assertEqual(dn_items[0]["amount"], 380)


# ======================================================================
# 23-28: Edge cases and cross-module verification
# ======================================================================
class TestDNEdgeCases(_BaseTest):
    def test_23_persistence_across_connections(self):
        header = {"voucher_date": "2026-01-20", "voucher_time": "10:00", "dn_date": "2026-01-20", "dn_type": "Supplier", "supplier_id": self.supplier_id, "total_amount": 200, "ledger_amount": 200, "remarks": "persisted"}
        items = [{"item_id": self.item_id, "stock_batch_id": self.batch_id, "batch_no": "BATCH-A", "expiry": "12/27", "pack_size": "10x10", "rate": 40, "mrp": 50, "return_qty": 5, "less_amount": 0, "amount": 200, "return_reason": "", "price_factor": 1.0}]
        dn_id = DebitNoteDAO.insert_debit_note(header, items)

        dn = DebitNoteDAO.get_by_id(dn_id)
        self.assertIsNotNone(dn)
        self.assertEqual(dn["remarks"], "persisted")
        dn_items = DebitNoteDAO.get_items(dn_id)
        self.assertEqual(len(dn_items), 1)

    def test_24_purchase_still_works(self):
        item2_id = ItemDAO.insert(item_name="ItemPurchase", unit_id=self.unit_id, company_id=self.company_id, pack_size="1x1", reorder_stock_level=0)
        inv_id = PurchaseDAO.insert_invoice(
            voucher_no="PV-0099", voucher_date="2026-03-01", voucher_time="",
            purchase_type="Cash", supplier_id=self.supplier_id,
            invoice_no="INV-099", invoice_date="2026-03-01",
            invoice_net_amount=500.0, bill_discount=0, due_date="",
            total_amount=500.0, gst_amount=0, debit_note_amount=0,
            other_amount=0, paid_amount=500.0, round_off=0, net_amount=500.0,
            remarks="",
            items=[{"item_id": item2_id, "pack_size": "1x1", "pay_qty": 25, "free_qty": 0, "batch_no": "PBATCH", "expiry": "06/28", "rate": 20, "mrp": 25, "discount": 0, "gst_percent": 0, "gst_amount": 0, "amount": 500, "purchase_rate": 20, "net_rate": 20, "pp": 20}],
        )
        self.assertGreater(inv_id, 0)
        batches = StockDAO.get_stock_batches_for_item(item2_id)
        self.assertEqual(len(batches), 1)
        self.assertAlmostEqual(batches[0]["stock_qty"], 25, places=2)

    def test_25_counter_sale_still_works(self):
        ensure_system_ledgers()
        sale_batches = StockDAO.get_stock_batches_for_item(self.item_id)
        self.assertGreater(len(sale_batches), 0)
        sale_id = SalesDAO.insert_invoice(
            bill_no="CS-0099", sale_date="2026-01-25", sale_time="10:00",
            sale_type="Cash", customer_id=self.customer_id,
            patient_name="TestPatient", doctor_id=None,
            discount=0, paid_amount=250, total_amount=250, round_off=0,
            net_amount=250, remarks="",
            items=[{"item_id": self.item_id, "stock_batch_id": self.batch_id, "pack_size": "10x10", "location": "", "batch_no": "BATCH-A", "expiry": "12/27", "mrp": 50, "sale_qty": 5, "discount_amount": 0, "amount": 250}],
        )
        self.assertGreater(sale_id, 0)

    def test_26_credit_note_still_works(self):
        cn_header = {"voucher_date": "2026-01-25", "cn_date": "2026-01-25", "cn_type": "Customer", "customer_id": self.customer_id, "total_amount": 200, "ledger_amount": 200, "remarks": ""}
        cn_items = [{"item_id": self.item_id, "stock_batch_id": self.batch_id, "batch_no": "BATCH-A", "expiry": "12/27", "pack_size": "10x10", "rate": 40, "mrp": 50, "return_qty": 5, "less_amount": 0, "amount": 200, "return_reason": "", "price_factor": 1.0}]
        before = StockDAO.get_stock_batch_by_id(self.batch_id)["stock_qty"]
        cn_id = CreditNoteDAO.insert_credit_note(cn_header, cn_items)
        after = StockDAO.get_stock_batch_by_id(self.batch_id)["stock_qty"]
        self.assertGreater(after, before)

    def test_27_stock_master_still_works(self):
        all_stock = StockDAO.get_all()
        self.assertGreater(len(all_stock), 0)
        item_stock = StockDAO.get_by_item(self.item_id)
        self.assertGreater(len(item_stock), 0)

    def test_28_all_master_screens_still_work(self):
        from database.company_dao import CompanyDAO
        from database.unit_dao import UnitDAO
        from database.drug_dao import DrugDAO
        from database.supplier_dao import SupplierDAO
        from database.customer_dao import CustomerDAO
        from database.doctor_dao import DoctorDAO
        from database.item_dao import ItemDAO

        self.assertGreater(len(CompanyDAO.get_all()), 0)
        self.assertGreater(len(UnitDAO.get_all()), 0)
        self.assertGreater(len(DrugDAO.get_all()), 0)
        self.assertGreater(len(SupplierDAO.get_all()), 0)
        self.assertGreater(len(CustomerDAO.get_all()), 0)
        self.assertGreater(len(DoctorDAO.get_all()), 0)
        self.assertGreater(len(ItemDAO.get_all()), 0)


if __name__ == "__main__":
    unittest.main()
