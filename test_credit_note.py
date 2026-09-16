import os
import sys
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database.connection import get_connection, init_database
from database.account_roles import ensure_system_ledgers
from database.credit_note_dao import CreditNoteDAO
from database.customer_dao import CustomerDAO
from database.doctor_dao import DoctorDAO
from database.item_dao import ItemDAO
from database.stock_dao import StockDAO
from database.unit_dao import UnitDAO
from database.company_dao import CompanyDAO
from database.drug_dao import DrugDAO
from database.purchase_dao import PurchaseDAO
from database.supplier_dao import SupplierDAO


class _BaseTest(unittest.TestCase):
    """Shared setUp for every test class — fresh DB, seed master data, and a stock batch."""

    _DB_PATH = os.path.join(os.path.dirname(__file__), "_test_cn.db")

    @classmethod
    def setUpClass(cls):
        if os.path.exists(cls._DB_PATH):
            os.remove(cls._DB_PATH)
        os.environ["PHARMACY_DB"] = cls._DB_PATH
        init_database()

        conn = get_connection()
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("DELETE FROM credit_note_items")
            conn.execute("DELETE FROM credit_notes")
            conn.execute("DELETE FROM sales_invoice_items")
            conn.execute("DELETE FROM sales_invoices")
            conn.execute("DELETE FROM purchase_invoice_items")
            conn.execute("DELETE FROM purchase_invoices")
            conn.execute("DELETE FROM ledger_transactions")
            conn.execute("DELETE FROM account_ledgers")
            conn.execute("DELETE FROM stock_batches")
            conn.execute("DELETE FROM item_ingredients")
            conn.execute("DELETE FROM items")
            conn.execute("DELETE FROM doctors")
            conn.execute("DELETE FROM customers")
            conn.execute("DELETE FROM suppliers")
            conn.execute("DELETE FROM drugs")
            conn.execute("DELETE FROM units")
            conn.execute("DELETE FROM companies")
            conn.commit()
        finally:
            conn.close()

    def setUp(self):
        self.conn = get_connection()
        try:
            self.conn.execute("DELETE FROM credit_note_items")
            self.conn.execute("DELETE FROM credit_notes")
            self.conn.execute("DELETE FROM sales_invoice_items")
            self.conn.execute("DELETE FROM sales_invoices")
            self.conn.execute("DELETE FROM purchase_invoice_items")
            self.conn.execute("DELETE FROM purchase_invoices")
            self.conn.execute("DELETE FROM ledger_transactions")
            self.conn.execute("DELETE FROM account_ledgers")
            self.conn.execute("DELETE FROM stock_batches")
            self.conn.execute("DELETE FROM item_ingredients")
            self.conn.execute("DELETE FROM items")
            self.conn.execute("DELETE FROM doctors")
            self.conn.execute("DELETE FROM customers")
            self.conn.execute("DELETE FROM suppliers")
            self.conn.execute("DELETE FROM drugs")
            self.conn.execute("DELETE FROM units")
            self.conn.execute("DELETE FROM companies")
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
            voucher_no="PV-0001",
            voucher_date="2026-01-15",
            voucher_time="",
            purchase_type="Cash",
            supplier_id=self.supplier_id,
            invoice_no="INV-001",
            invoice_date="2026-01-15",
            invoice_net_amount=4000.0,
            bill_discount=0,
            due_date="",
            total_amount=4000.0,
            gst_amount=0,
            debit_note_amount=0,
            other_amount=0,
            paid_amount=4000.0,
            round_off=0,
            net_amount=4000.0,
            remarks="Initial purchase",
            items=[{
                "item_id": self.item_id,
                "pack_size": "10x10",
                "pay_qty": 100,
                "free_qty": 0,
                "batch_no": "BATCH-A",
                "expiry": "12/27",
                "rate": 40.0,
                "mrp": 50.0,
                "discount": 0,
                "gst_percent": 0,
                "gst_amount": 0,
                "amount": 4000.0,
                "purchase_rate": 40.0,
                "net_rate": 40.0,
                "pp": 40.0,
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
class TestCNBasicCRUD(_BaseTest):
    def test_01_create_credit_note(self):
        header = {
            "voucher_date": "2026-01-20",
            "cn_date": "2026-01-20",
            "cn_type": "Customer",
            "customer_id": self.customer_id,
            "total_amount": 400.0,
            "ledger_amount": 400.0,
            "remarks": "Customer returned damaged goods",
        }
        items = [{
            "item_id": self.item_id,
            "stock_batch_id": self.batch_id,
            "batch_no": "BATCH-A",
            "expiry": "12/27",
            "pack_size": "10x10",
            "rate": 40.0,
            "mrp": 50.0,
            "return_qty": 10,
            "less_amount": 0,
            "amount": 400.0,
            "return_reason": "Damaged",
            "price_factor": 1.0,
        }]
        cn_id = CreditNoteDAO.insert_credit_note(header, items)
        self.assertGreater(cn_id, 0)

        cn = CreditNoteDAO.get_by_id(cn_id)
        self.assertIsNotNone(cn)
        self.assertEqual(cn["voucher_no"], "CN-0001")
        self.assertEqual(cn["total_amount"], 400.0)

    def test_02_voucher_number_auto_increment(self):
        h1 = {"voucher_date": "2026-01-20", "cn_date": "2026-01-20", "cn_type": "Customer", "customer_id": self.customer_id, "total_amount": 100, "ledger_amount": 100, "remarks": ""}
        i1 = [{"item_id": self.item_id, "stock_batch_id": self.batch_id, "batch_no": "BATCH-A", "expiry": "12/27", "pack_size": "10x10", "rate": 40, "mrp": 50, "return_qty": 2, "less_amount": 0, "amount": 80, "return_reason": "", "price_factor": 1.0}]
        cn1_id = CreditNoteDAO.insert_credit_note(h1, i1)

        h2 = {"voucher_date": "2026-01-21", "cn_date": "2026-01-21", "cn_type": "Customer", "customer_id": self.customer_id, "total_amount": 160, "ledger_amount": 160, "remarks": ""}
        i2 = [{"item_id": self.item_id, "stock_batch_id": self.batch_id, "batch_no": "BATCH-A", "expiry": "12/27", "pack_size": "10x10", "rate": 40, "mrp": 50, "return_qty": 4, "less_amount": 0, "amount": 160, "return_reason": "", "price_factor": 1.0}]
        cn2_id = CreditNoteDAO.insert_credit_note(h2, i2)

        cn1 = CreditNoteDAO.get_by_id(cn1_id)
        cn2 = CreditNoteDAO.get_by_id(cn2_id)
        self.assertEqual(cn1["voucher_no"], "CN-0001")
        self.assertEqual(cn2["voucher_no"], "CN-0002")

    def test_03_stock_restoration_on_insert(self):
        before = StockDAO.get_stock_batch_by_id(self.batch_id)["stock_qty"]

        header = {"voucher_date": "2026-01-20", "cn_date": "2026-01-20", "cn_type": "Customer", "customer_id": self.customer_id, "total_amount": 400, "ledger_amount": 400, "remarks": ""}
        items = [{"item_id": self.item_id, "stock_batch_id": self.batch_id, "batch_no": "BATCH-A", "expiry": "12/27", "pack_size": "10x10", "rate": 40, "mrp": 50, "return_qty": 10, "less_amount": 0, "amount": 400, "return_reason": "", "price_factor": 1.0}]
        CreditNoteDAO.insert_credit_note(header, items)

        after = StockDAO.get_stock_batch_by_id(self.batch_id)["stock_qty"]
        self.assertAlmostEqual(after, before + 10, places=2)

    def test_04_multiple_items(self):
        item2_id = ItemDAO.insert(
            item_name="Item2",
            unit_id=self.unit_id,
            company_id=self.company_id,
            pack_size="5x5",
            reorder_stock_level=5,
        )
        PurchaseDAO.insert_invoice(
            voucher_no="PV-0002", voucher_date="2026-01-15", voucher_time="",
            purchase_type="Cash", supplier_id=self.supplier_id,
            invoice_no="INV-002", invoice_date="2026-01-15",
            invoice_net_amount=1000.0, bill_discount=0, due_date="",
            total_amount=1000.0, gst_amount=0, debit_note_amount=0,
            other_amount=0, paid_amount=1000.0, round_off=0, net_amount=1000.0,
            remarks="",
            items=[{
                "item_id": item2_id, "pack_size": "5x5", "pay_qty": 50,
                "free_qty": 0, "batch_no": "BATCH-B", "expiry": "06/27",
                "rate": 20, "mrp": 30, "discount": 0, "gst_percent": 0,
                "gst_amount": 0, "amount": 1000, "purchase_rate": 20,
                "net_rate": 20, "pp": 20,
            }],
        )
        batches2 = StockDAO.get_stock_batches_for_item(item2_id)
        batch2_id = batches2[0]["id"]

        header = {"voucher_date": "2026-01-20", "cn_date": "2026-01-20", "cn_type": "Customer", "customer_id": self.customer_id, "total_amount": 600, "ledger_amount": 600, "remarks": ""}
        items = [
            {"item_id": self.item_id, "stock_batch_id": self.batch_id, "batch_no": "BATCH-A", "expiry": "12/27", "pack_size": "10x10", "rate": 40, "mrp": 50, "return_qty": 5, "less_amount": 0, "amount": 200, "return_reason": "Damaged", "price_factor": 1.0},
            {"item_id": item2_id, "stock_batch_id": batch2_id, "batch_no": "BATCH-B", "expiry": "06/27", "pack_size": "5x5", "rate": 20, "mrp": 30, "return_qty": 20, "less_amount": 0, "amount": 400, "return_reason": "Wrong item", "price_factor": 1.0},
        ]
        cn_id = CreditNoteDAO.insert_credit_note(header, items)
        cn_items = CreditNoteDAO.get_invoice_items(cn_id)
        self.assertEqual(len(cn_items), 2)

    def test_05_edit_credit_note(self):
        header = {"voucher_date": "2026-01-20", "cn_date": "2026-01-20", "cn_type": "Customer", "customer_id": self.customer_id, "total_amount": 200, "ledger_amount": 200, "remarks": "old"}
        items = [{"item_id": self.item_id, "stock_batch_id": self.batch_id, "batch_no": "BATCH-A", "expiry": "12/27", "pack_size": "10x10", "rate": 40, "mrp": 50, "return_qty": 5, "less_amount": 0, "amount": 200, "return_reason": "", "price_factor": 1.0}]
        cn_id = CreditNoteDAO.insert_credit_note(header, items)

        before = StockDAO.get_stock_batch_by_id(self.batch_id)["stock_qty"]

        new_header = {"voucher_date": "2026-01-21", "cn_date": "2026-01-21", "cn_type": "Customer", "customer_id": self.customer_id, "total_amount": 400, "ledger_amount": 400, "remarks": "updated"}
        new_items = [{"item_id": self.item_id, "stock_batch_id": self.batch_id, "batch_no": "BATCH-A", "expiry": "12/27", "pack_size": "10x10", "rate": 40, "mrp": 50, "return_qty": 10, "less_amount": 0, "amount": 400, "return_reason": "Changed mind", "price_factor": 1.0}]
        CreditNoteDAO.update_credit_note(cn_id, new_header, new_items)

        after = StockDAO.get_stock_batch_by_id(self.batch_id)["stock_qty"]
        self.assertAlmostEqual(after, before - 5 + 10, places=2)

        cn = CreditNoteDAO.get_by_id(cn_id)
        self.assertEqual(cn["remarks"], "updated")
        self.assertEqual(cn["total_amount"], 400)

    def test_06_delete_credit_note(self):
        header = {"voucher_date": "2026-01-20", "cn_date": "2026-01-20", "cn_type": "Customer", "customer_id": self.customer_id, "total_amount": 400, "ledger_amount": 400, "remarks": ""}
        items = [{"item_id": self.item_id, "stock_batch_id": self.batch_id, "batch_no": "BATCH-A", "expiry": "12/27", "pack_size": "10x10", "rate": 40, "mrp": 50, "return_qty": 10, "less_amount": 0, "amount": 400, "return_reason": "", "price_factor": 1.0}]
        cn_id = CreditNoteDAO.insert_credit_note(header, items)

        before = StockDAO.get_stock_batch_by_id(self.batch_id)["stock_qty"]
        CreditNoteDAO.delete_credit_note(cn_id)
        after = StockDAO.get_stock_batch_by_id(self.batch_id)["stock_qty"]

        self.assertEqual(before - after, 10)
        self.assertIsNone(CreditNoteDAO.get_by_id(cn_id))


# ======================================================================
# 7-9: Filtering
# ======================================================================
class TestCNFiltering(_BaseTest):
    def _create_cn(self, date="2026-01-20", cust_id=None, remarks=""):
        header = {"voucher_date": date, "cn_date": date, "cn_type": "Customer", "customer_id": cust_id or self.customer_id, "total_amount": 200, "ledger_amount": 200, "remarks": remarks}
        items = [{"item_id": self.item_id, "stock_batch_id": self.batch_id, "batch_no": "BATCH-A", "expiry": "12/27", "pack_size": "10x10", "rate": 40, "mrp": 50, "return_qty": 5, "less_amount": 0, "amount": 200, "return_reason": "", "price_factor": 1.0}]
        return CreditNoteDAO.insert_credit_note(header, items)

    def test_07_filter_by_voucher_date(self):
        self._create_cn(date="2026-01-15")
        self._create_cn(date="2026-02-10")
        results = CreditNoteDAO.get_all_filtered(voucher_from="2026-02-01", voucher_to="2026-02-28")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["voucher_date"], "2026-02-10")

    def test_08_filter_by_customer(self):
        cust2_id = CustomerDAO.insert("CustTwo")
        self._create_cn(cust_id=self.customer_id)
        self._create_cn(cust_id=cust2_id)
        results = CreditNoteDAO.get_all_filtered(party="CustTwo")
        self.assertEqual(len(results), 1)

    def test_09_filter_by_voucher_no(self):
        self._create_cn()
        self._create_cn()
        results = CreditNoteDAO.get_all_filtered(voucher_no="CN-0001")
        self.assertEqual(len(results), 1)


# ======================================================================
# 10-12: Validation
# ======================================================================
class TestCNValidation(_BaseTest):
    def test_10_no_customer_raises(self):
        header = {"voucher_date": "2026-01-20", "cn_date": "2026-01-20", "cn_type": "Customer", "customer_id": None, "total_amount": 0, "ledger_amount": 0, "remarks": ""}
        items = [{"item_id": self.item_id, "stock_batch_id": self.batch_id, "batch_no": "BATCH-A", "expiry": "12/27", "pack_size": "10x10", "rate": 40, "mrp": 50, "return_qty": 5, "less_amount": 0, "amount": 200, "return_reason": "", "price_factor": 1.0}]
        with self.assertRaises(Exception):
            CreditNoteDAO.insert_credit_note(header, items)

    def test_11_no_items_still_creates_header(self):
        header = {"voucher_date": "2026-01-20", "cn_date": "2026-01-20", "cn_type": "Customer", "customer_id": self.customer_id, "total_amount": 0, "ledger_amount": 0, "remarks": "empty"}
        cn_id = CreditNoteDAO.insert_credit_note(header, [])
        cn = CreditNoteDAO.get_by_id(cn_id)
        self.assertIsNotNone(cn)
        self.assertEqual(cn["remarks"], "empty")

    def test_12_return_qty_zero(self):
        header = {"voucher_date": "2026-01-20", "cn_date": "2026-01-20", "cn_type": "Customer", "customer_id": self.customer_id, "total_amount": 0, "ledger_amount": 0, "remarks": ""}
        items = [{"item_id": self.item_id, "stock_batch_id": self.batch_id, "batch_no": "BATCH-A", "expiry": "12/27", "pack_size": "10x10", "rate": 40, "mrp": 50, "return_qty": 0, "less_amount": 0, "amount": 0, "return_reason": "", "price_factor": 1.0}]
        cn_id = CreditNoteDAO.insert_credit_note(header, items)
        batch_after = StockDAO.get_stock_batch_by_id(self.batch_id)["stock_qty"]
        self.assertAlmostEqual(batch_after, 100.0, places=2)


# ======================================================================
# 13-16: Features
# ======================================================================
class TestCNFeatures(_BaseTest):
    def test_13_less_amount(self):
        header = {"voucher_date": "2026-01-20", "cn_date": "2026-01-20", "cn_type": "Customer", "customer_id": self.customer_id, "total_amount": 380, "ledger_amount": 380, "remarks": ""}
        items = [{"item_id": self.item_id, "stock_batch_id": self.batch_id, "batch_no": "BATCH-A", "expiry": "12/27", "pack_size": "10x10", "rate": 40, "mrp": 50, "return_qty": 10, "less_amount": 20, "amount": 380, "return_reason": "partial", "price_factor": 1.0}]
        cn_id = CreditNoteDAO.insert_credit_note(header, items)
        cn_items = CreditNoteDAO.get_invoice_items(cn_id)
        self.assertEqual(cn_items[0]["less_amount"], 20)
        self.assertEqual(cn_items[0]["amount"], 380)

    def test_14_cn_type_supplier(self):
        header = {"voucher_date": "2026-01-20", "cn_date": "2026-01-20", "cn_type": "Supplier", "customer_id": self.customer_id, "total_amount": 200, "ledger_amount": 200, "remarks": ""}
        items = [{"item_id": self.item_id, "stock_batch_id": self.batch_id, "batch_no": "BATCH-A", "expiry": "12/27", "pack_size": "10x10", "rate": 40, "mrp": 50, "return_qty": 5, "less_amount": 0, "amount": 200, "return_reason": "", "price_factor": 1.0}]
        cn_id = CreditNoteDAO.insert_credit_note(header, items)
        cn = CreditNoteDAO.get_by_id(cn_id)
        self.assertEqual(cn["cn_type"], "Supplier")

    def test_15_cn_date_separate(self):
        header = {"voucher_date": "2026-01-20", "cn_date": "2026-01-25", "cn_type": "Customer", "customer_id": self.customer_id, "total_amount": 200, "ledger_amount": 200, "remarks": ""}
        items = [{"item_id": self.item_id, "stock_batch_id": self.batch_id, "batch_no": "BATCH-A", "expiry": "12/27", "pack_size": "10x10", "rate": 40, "mrp": 50, "return_qty": 5, "less_amount": 0, "amount": 200, "return_reason": "", "price_factor": 1.0}]
        cn_id = CreditNoteDAO.insert_credit_note(header, items)
        cn = CreditNoteDAO.get_by_id(cn_id)
        self.assertEqual(cn["voucher_date"], "2026-01-20")
        self.assertEqual(cn["cn_date"], "2026-01-25")

    def test_16_remarks_persisted(self):
        header = {"voucher_date": "2026-01-20", "cn_date": "2026-01-20", "cn_type": "Customer", "customer_id": self.customer_id, "total_amount": 200, "ledger_amount": 200, "remarks": "Customer returned expired tablets"}
        items = [{"item_id": self.item_id, "stock_batch_id": self.batch_id, "batch_no": "BATCH-A", "expiry": "12/27", "pack_size": "10x10", "rate": 40, "mrp": 50, "return_qty": 5, "less_amount": 0, "amount": 200, "return_reason": "", "price_factor": 1.0}]
        cn_id = CreditNoteDAO.insert_credit_note(header, items)
        cn = CreditNoteDAO.get_by_id(cn_id)
        self.assertEqual(cn["remarks"], "Customer returned expired tablets")


# ======================================================================
# 17-19: Persistence / item-level
# ======================================================================
class TestCNPersistence(_BaseTest):
    def test_17_items_persisted(self):
        header = {"voucher_date": "2026-01-20", "cn_date": "2026-01-20", "cn_type": "Customer", "customer_id": self.customer_id, "total_amount": 200, "ledger_amount": 200, "remarks": ""}
        items = [{"item_id": self.item_id, "stock_batch_id": self.batch_id, "batch_no": "BATCH-A", "expiry": "12/27", "pack_size": "10x10", "rate": 40, "mrp": 50, "return_qty": 5, "less_amount": 0, "amount": 200, "return_reason": "Damaged", "price_factor": 1.0}]
        cn_id = CreditNoteDAO.insert_credit_note(header, items)
        cn_items = CreditNoteDAO.get_invoice_items(cn_id)
        self.assertEqual(len(cn_items), 1)
        self.assertEqual(cn_items[0]["item_name"], "TestItem")
        self.assertEqual(cn_items[0]["return_reason"], "Damaged")

    def test_18_multiple_cns(self):
        for i in range(5):
            header = {"voucher_date": f"2026-01-{10+i}", "cn_date": f"2026-01-{10+i}", "cn_type": "Customer", "customer_id": self.customer_id, "total_amount": 100, "ledger_amount": 100, "remarks": f"CN {i+1}"}
            items = [{"item_id": self.item_id, "stock_batch_id": self.batch_id, "batch_no": "BATCH-A", "expiry": "12/27", "pack_size": "10x10", "rate": 40, "mrp": 50, "return_qty": 1, "less_amount": 0, "amount": 40, "return_reason": "", "price_factor": 1.0}]
            CreditNoteDAO.insert_credit_note(header, items)
        all_cns = CreditNoteDAO.get_all()
        self.assertEqual(len(all_cns), 5)
        self.assertEqual(all_cns[0]["voucher_no"], "CN-0005")

    def test_19_delete_reverses_stock(self):
        header = {"voucher_date": "2026-01-20", "cn_date": "2026-01-20", "cn_type": "Customer", "customer_id": self.customer_id, "total_amount": 200, "ledger_amount": 200, "remarks": ""}
        items = [{"item_id": self.item_id, "stock_batch_id": self.batch_id, "batch_no": "BATCH-A", "expiry": "12/27", "pack_size": "10x10", "rate": 40, "mrp": 50, "return_qty": 25, "less_amount": 0, "amount": 1000, "return_reason": "", "price_factor": 1.0}]
        cn_id = CreditNoteDAO.insert_credit_note(header, items)
        before = StockDAO.get_stock_batch_by_id(self.batch_id)["stock_qty"]
        CreditNoteDAO.delete_credit_note(cn_id)
        after = StockDAO.get_stock_batch_by_id(self.batch_id)["stock_qty"]
        self.assertAlmostEqual(before - after, 25, places=2)


# ======================================================================
# 20-22: Edit stock reversal
# ======================================================================
class TestCNEditStock(_BaseTest):
    def test_20_edit_reverses_old_stock(self):
        header = {"voucher_date": "2026-01-20", "cn_date": "2026-01-20", "cn_type": "Customer", "customer_id": self.customer_id, "total_amount": 400, "ledger_amount": 400, "remarks": ""}
        items = [{"item_id": self.item_id, "stock_batch_id": self.batch_id, "batch_no": "BATCH-A", "expiry": "12/27", "pack_size": "10x10", "rate": 40, "mrp": 50, "return_qty": 10, "less_amount": 0, "amount": 400, "return_reason": "", "price_factor": 1.0}]
        cn_id = CreditNoteDAO.insert_credit_note(header, items)
        before = StockDAO.get_stock_batch_by_id(self.batch_id)["stock_qty"]

        new_header = {"voucher_date": "2026-01-21", "cn_date": "2026-01-21", "cn_type": "Customer", "customer_id": self.customer_id, "total_amount": 200, "ledger_amount": 200, "remarks": ""}
        new_items = [{"item_id": self.item_id, "stock_batch_id": self.batch_id, "batch_no": "BATCH-A", "expiry": "12/27", "pack_size": "10x10", "rate": 40, "mrp": 50, "return_qty": 5, "less_amount": 0, "amount": 200, "return_reason": "", "price_factor": 1.0}]
        CreditNoteDAO.update_credit_note(cn_id, new_header, new_items)
        after = StockDAO.get_stock_batch_by_id(self.batch_id)["stock_qty"]
        self.assertAlmostEqual(after, before - 10 + 5, places=2)

    def test_21_rate_from_purchase_rate(self):
        header = {"voucher_date": "2026-01-20", "cn_date": "2026-01-20", "cn_type": "Customer", "customer_id": self.customer_id, "total_amount": 400, "ledger_amount": 400, "remarks": ""}
        items = [{"item_id": self.item_id, "stock_batch_id": self.batch_id, "batch_no": "BATCH-A", "expiry": "12/27", "pack_size": "10x10", "rate": 40, "mrp": 50, "return_qty": 10, "less_amount": 0, "amount": 400, "return_reason": "", "price_factor": 1.0}]
        cn_id = CreditNoteDAO.insert_credit_note(header, items)
        cn_items = CreditNoteDAO.get_invoice_items(cn_id)
        self.assertEqual(cn_items[0]["rate"], 40.0)

    def test_22_amount_calculation(self):
        header = {"voucher_date": "2026-01-20", "cn_date": "2026-01-20", "cn_type": "Customer", "customer_id": self.customer_id, "total_amount": 380, "ledger_amount": 380, "remarks": ""}
        items = [{"item_id": self.item_id, "stock_batch_id": self.batch_id, "batch_no": "BATCH-A", "expiry": "12/27", "pack_size": "10x10", "rate": 40, "mrp": 50, "return_qty": 10, "less_amount": 20, "amount": 380, "return_reason": "", "price_factor": 1.0}]
        cn_id = CreditNoteDAO.insert_credit_note(header, items)
        cn_items = CreditNoteDAO.get_invoice_items(cn_id)
        self.assertEqual(cn_items[0]["amount"], 380)


# ======================================================================
# 23-26: Edge cases
# ======================================================================
class TestCNEdgeCases(_BaseTest):
    def test_23_ledger_matches_total(self):
        header = {"voucher_date": "2026-01-20", "cn_date": "2026-01-20", "cn_type": "Customer", "customer_id": self.customer_id, "total_amount": 500, "ledger_amount": 500, "remarks": ""}
        items = [{"item_id": self.item_id, "stock_batch_id": self.batch_id, "batch_no": "BATCH-A", "expiry": "12/27", "pack_size": "10x10", "rate": 40, "mrp": 50, "return_qty": 10, "less_amount": 0, "amount": 400, "return_reason": "", "price_factor": 1.0}]
        cn_id = CreditNoteDAO.insert_credit_note(header, items)
        cn = CreditNoteDAO.get_by_id(cn_id)
        self.assertEqual(cn["total_amount"], cn["ledger_amount"])

    def test_24_all_customer_types(self):
        for ctype in ["Customer", "Supplier"]:
            header = {"voucher_date": "2026-01-20", "cn_date": "2026-01-20", "cn_type": ctype, "customer_id": self.customer_id, "total_amount": 200, "ledger_amount": 200, "remarks": ctype}
            items = [{"item_id": self.item_id, "stock_batch_id": self.batch_id, "batch_no": "BATCH-A", "expiry": "12/27", "pack_size": "10x10", "rate": 40, "mrp": 50, "return_qty": 5, "less_amount": 0, "amount": 200, "return_reason": "", "price_factor": 1.0}]
            cn_id = CreditNoteDAO.insert_credit_note(header, items)
            cn = CreditNoteDAO.get_by_id(cn_id)
            self.assertEqual(cn["cn_type"], ctype)

    def test_25_empty_filter_returns_all(self):
        for i in range(3):
            header = {"voucher_date": f"2026-01-{10+i}", "cn_date": f"2026-01-{10+i}", "cn_type": "Customer", "customer_id": self.customer_id, "total_amount": 100, "ledger_amount": 100, "remarks": ""}
            items = [{"item_id": self.item_id, "stock_batch_id": self.batch_id, "batch_no": "BATCH-A", "expiry": "12/27", "pack_size": "10x10", "rate": 40, "mrp": 50, "return_qty": 1, "less_amount": 0, "amount": 40, "return_reason": "", "price_factor": 1.0}]
            CreditNoteDAO.insert_credit_note(header, items)
        results = CreditNoteDAO.get_all_filtered()
        self.assertEqual(len(results), 3)

    def test_26_voucher_no_auto_increment_edge(self):
        all_cn = CreditNoteDAO.get_all()
        self.assertEqual(len(all_cn), 0)
        header = {"voucher_date": "2026-01-20", "cn_date": "2026-01-20", "cn_type": "Customer", "customer_id": self.customer_id, "total_amount": 200, "ledger_amount": 200, "remarks": ""}
        items = [{"item_id": self.item_id, "stock_batch_id": self.batch_id, "batch_no": "BATCH-A", "expiry": "12/27", "pack_size": "10x10", "rate": 40, "mrp": 50, "return_qty": 5, "less_amount": 0, "amount": 200, "return_reason": "", "price_factor": 1.0}]
        cn_id = CreditNoteDAO.insert_credit_note(header, items)
        cn = CreditNoteDAO.get_by_id(cn_id)
        self.assertEqual(cn["voucher_no"], "CN-0001")


if __name__ == "__main__":
    unittest.main()
