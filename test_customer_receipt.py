import os
import sys
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database.connection import get_connection, init_database
from database.account_roles import ensure_system_ledgers
from database.customer_receipt_dao import CustomerReceiptDAO
from database.customer_dao import CustomerDAO
from database.supplier_dao import SupplierDAO
from database.supplier_payment_dao import SupplierPaymentDAO
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
    """Shared setUp — fresh DB, seed master data, sale, and a stock batch."""

    _DB_PATH = os.path.join(os.path.dirname(__file__), "_test_cr.db")

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
                "customer_receipts",
                "supplier_payments",
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
                "customer_receipts",
                "supplier_payments",
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

        self.company_id = CompanyDAO.insert("TestCo", "TC")
        self.unit_id = UnitDAO.insert("Pcs")
        self.drug_id = DrugDAO.insert("Paracetamol")
        self.customer_id = CustomerDAO.insert("TestCustomer")
        self.doctor_id = DoctorDAO.insert("Dr. Smith")
        self.supplier_id = SupplierDAO.insert("TestSupplier")

        # System account roles (CASH/BANK) required by receipt posting
        ensure_system_ledgers()

        self.item_id = ItemDAO.insert(
            item_name="TestItem",
            unit_id=self.unit_id,
            company_id=self.company_id,
            pack_size="10x10",
            reorder_stock_level=10,
        )

        # Create a purchase so stock exists
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

        # Create a sale so customer owes money
        self.sale_id = SalesDAO.insert_invoice(
            bill_no="CS-0001", sale_date="2026-01-18", sale_time="10:00",
            sale_type="Credit", customer_id=self.customer_id,
            patient_name="TestPatient", doctor_id=None,
            discount=0, paid_amount=0, total_amount=500, round_off=0,
            net_amount=500, remarks="Credit sale",
            items=[{
                "item_id": self.item_id, "stock_batch_id": self.batch_id,
                "pack_size": "10x10", "location": "", "batch_no": "BATCH-A",
                "expiry": "12/27", "mrp": 50, "sale_qty": 10,
                "discount_amount": 0, "amount": 500,
            }],
        )

    def tearDown(self):
        self.conn.close()


# ======================================================================
# 1-5: Basic CRUD
# ======================================================================
class TestCRBasicCRUD(_BaseTest):
    def test_01_create_receipt(self):
        header = {
            "receipt_date": "2026-01-20", "receipt_time": "10:00",
            "customer_id": self.customer_id, "receipt_mode": "Cash",
            "amount": 200.0, "reference_no": "CASH-001",
            "remarks": "Received against CS-0001",
        }
        rec_id = CustomerReceiptDAO.insert_receipt(header)
        self.assertGreater(rec_id, 0)

        rec = CustomerReceiptDAO.get_by_id(rec_id)
        self.assertIsNotNone(rec)
        self.assertEqual(rec["voucher_no"], "CR-0001")
        self.assertEqual(rec["amount"], 200.0)
        self.assertEqual(rec["receipt_mode"], "Cash")
        self.assertEqual(rec["customer_name"], "TestCustomer")

    def test_02_voucher_number_auto_increment(self):
        h1 = {"receipt_date": "2026-01-20", "receipt_time": "10:00", "customer_id": self.customer_id, "receipt_mode": "Cash", "amount": 100, "reference_no": "", "remarks": ""}
        h2 = {"receipt_date": "2026-01-21", "receipt_time": "11:00", "customer_id": self.customer_id, "receipt_mode": "Bank", "amount": 200, "reference_no": "", "remarks": ""}

        id1 = CustomerReceiptDAO.insert_receipt(h1)
        id2 = CustomerReceiptDAO.insert_receipt(h2)

        r1 = CustomerReceiptDAO.get_by_id(id1)
        r2 = CustomerReceiptDAO.get_by_id(id2)
        self.assertEqual(r1["voucher_no"], "CR-0001")
        self.assertEqual(r2["voucher_no"], "CR-0002")

    def test_03_receipt_appears_in_history(self):
        header = {"receipt_date": "2026-01-20", "receipt_time": "10:00", "customer_id": self.customer_id, "receipt_mode": "Cash", "amount": 150, "reference_no": "", "remarks": ""}
        CustomerReceiptDAO.insert_receipt(header)
        all_recs = CustomerReceiptDAO.get_all()
        self.assertEqual(len(all_recs), 1)
        self.assertEqual(all_recs[0]["customer_name"], "TestCustomer")

    def test_04_amount_stored_correctly(self):
        header = {"receipt_date": "2026-01-20", "receipt_time": "10:00", "customer_id": self.customer_id, "receipt_mode": "Cash", "amount": 123.45, "reference_no": "", "remarks": ""}
        rec_id = CustomerReceiptDAO.insert_receipt(header)
        rec = CustomerReceiptDAO.get_by_id(rec_id)
        self.assertAlmostEqual(rec["amount"], 123.45, places=2)

    def test_05_edit_receipt(self):
        header = {"receipt_date": "2026-01-20", "receipt_time": "10:00", "customer_id": self.customer_id, "receipt_mode": "Cash", "amount": 100, "reference_no": "OLD-REF", "remarks": "old"}
        rec_id = CustomerReceiptDAO.insert_receipt(header)

        new_header = {"receipt_date": "2026-01-21", "receipt_time": "11:00", "customer_id": self.customer_id, "receipt_mode": "Bank", "amount": 250, "reference_no": "NEW-REF", "remarks": "updated"}
        CustomerReceiptDAO.update_receipt(rec_id, new_header)

        rec = CustomerReceiptDAO.get_by_id(rec_id)
        self.assertEqual(rec["amount"], 250)
        self.assertEqual(rec["receipt_mode"], "Bank")
        self.assertEqual(rec["reference_no"], "NEW-REF")
        self.assertEqual(rec["remarks"], "updated")


# ======================================================================
# 6: All receipt modes
# ======================================================================
class TestCRReceiptModes(_BaseTest):
    def test_06_all_receipt_modes(self):
        for mode in ["Cash", "Bank", "Cheque", "UPI"]:
            header = {"receipt_date": "2026-01-20", "receipt_time": "10:00", "customer_id": self.customer_id, "receipt_mode": mode, "amount": 50, "reference_no": f"REF-{mode}", "remarks": ""}
            CustomerReceiptDAO.insert_receipt(header)
        all_recs = CustomerReceiptDAO.get_all()
        self.assertEqual(len(all_recs), 4)
        modes = {r["receipt_mode"] for r in all_recs}
        self.assertEqual(modes, {"Cash", "Bank", "Cheque", "UPI"})


# ======================================================================
# 7-8: Edit verification
# ======================================================================
class TestCREditVerification(_BaseTest):
    def test_07_edit_preserves_voucher_no(self):
        header = {"receipt_date": "2026-01-20", "receipt_time": "10:00", "customer_id": self.customer_id, "receipt_mode": "Cash", "amount": 100, "reference_no": "", "remarks": ""}
        rec_id = CustomerReceiptDAO.insert_receipt(header)
        original_voucher = CustomerReceiptDAO.get_by_id(rec_id)["voucher_no"]
        CustomerReceiptDAO.update_receipt(rec_id, {"receipt_date": "2026-01-21", "receipt_time": "11:00", "customer_id": self.customer_id, "receipt_mode": "Bank", "amount": 200, "reference_no": "", "remarks": ""})
        rec = CustomerReceiptDAO.get_by_id(rec_id)
        self.assertEqual(rec["voucher_no"], original_voucher)

    def test_08_multiple_receipts(self):
        for i in range(5):
            CustomerReceiptDAO.insert_receipt({"receipt_date": f"2026-01-{10+i}", "receipt_time": "10:00", "customer_id": self.customer_id, "receipt_mode": "Cash", "amount": 50, "reference_no": "", "remarks": f"Receipt {i+1}"})
        all_recs = CustomerReceiptDAO.get_all()
        self.assertEqual(len(all_recs), 5)


# ======================================================================
# 9-12: Validation
# ======================================================================
class TestCRValidation(_BaseTest):
    def test_09_voucher_always_unique(self):
        for _ in range(3):
            CustomerReceiptDAO.insert_receipt({"receipt_date": "2026-01-20", "receipt_time": "10:00", "customer_id": self.customer_id, "receipt_mode": "Cash", "amount": 50, "reference_no": "", "remarks": ""})
        all_recs = CustomerReceiptDAO.get_all()
        voucher_nos = [r["voucher_no"] for r in all_recs]
        self.assertEqual(len(voucher_nos), len(set(voucher_nos)))

    def test_10_amount_zero_rejected(self):
        header = {"receipt_date": "2026-01-20", "receipt_time": "", "customer_id": self.customer_id, "receipt_mode": "Cash", "amount": 0, "reference_no": "", "remarks": ""}
        with self.assertRaises(ValueError) as ctx:
            CustomerReceiptDAO.insert_receipt(header)
        self.assertIn("greater than 0", str(ctx.exception))

    def test_11_negative_amount_rejected(self):
        header = {"receipt_date": "2026-01-20", "receipt_time": "", "customer_id": self.customer_id, "receipt_mode": "Cash", "amount": -50, "reference_no": "", "remarks": "Adjustment"}
        with self.assertRaises(ValueError) as ctx:
            CustomerReceiptDAO.insert_receipt(header)
        self.assertIn("greater than 0", str(ctx.exception))

    def test_12_missing_customer_raises(self):
        header = {"receipt_date": "2026-01-20", "receipt_time": "", "customer_id": None, "receipt_mode": "Cash", "amount": 100, "reference_no": "", "remarks": ""}
        with self.assertRaises(Exception):
            CustomerReceiptDAO.insert_receipt(header)


# ======================================================================
# 13-14: Filtering
# ======================================================================
class TestCRFiltering(_BaseTest):
    def _create_rec(self, date="2026-01-20", cust_id=None, amount=100):
        header = {"receipt_date": date, "receipt_time": "10:00", "customer_id": cust_id or self.customer_id, "receipt_mode": "Cash", "amount": amount, "reference_no": "", "remarks": ""}
        return CustomerReceiptDAO.insert_receipt(header)

    def test_13_date_filtering(self):
        self._create_rec(date="2026-01-15")
        self._create_rec(date="2026-02-10")
        results = CustomerReceiptDAO.get_all_filtered(date_from="2026-02-01", date_to="2026-02-28")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["receipt_date"], "2026-02-10")

    def test_14_customer_filtering(self):
        cust2_id = CustomerDAO.insert("CustTwo")
        self._create_rec(cust_id=self.customer_id)
        self._create_rec(cust_id=cust2_id)
        results = CustomerReceiptDAO.get_all_filtered(customer_id=cust2_id)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["customer_name"], "CustTwo")


# ======================================================================
# 15-16: Delete
# ======================================================================
class TestCRDelete(_BaseTest):
    def test_15_delete_receipt(self):
        header = {"receipt_date": "2026-01-20", "receipt_time": "10:00", "customer_id": self.customer_id, "receipt_mode": "Cash", "amount": 100, "reference_no": "", "remarks": ""}
        rec_id = CustomerReceiptDAO.insert_receipt(header)
        self.assertIsNotNone(CustomerReceiptDAO.get_by_id(rec_id))

        CustomerReceiptDAO.delete_receipt(rec_id)
        self.assertIsNone(CustomerReceiptDAO.get_by_id(rec_id))

    def test_16_delete_only_receipt(self):
        header = {"receipt_date": "2026-01-20", "receipt_time": "10:00", "customer_id": self.customer_id, "receipt_mode": "Cash", "amount": 100, "reference_no": "", "remarks": ""}
        rec_id = CustomerReceiptDAO.insert_receipt(header)
        CustomerReceiptDAO.delete_receipt(rec_id)
        all_recs = CustomerReceiptDAO.get_all()
        self.assertEqual(len(all_recs), 0)


# ======================================================================
# 17: Persistence across connections
# ======================================================================
class TestCRPersistence(_BaseTest):
    def test_17_persistence_across_connections(self):
        header = {"receipt_date": "2026-01-20", "receipt_time": "10:00", "customer_id": self.customer_id, "receipt_mode": "Cash", "amount": 300, "reference_no": "PERSIST-001", "remarks": "persisted"}
        rec_id = CustomerReceiptDAO.insert_receipt(header)

        rec = CustomerReceiptDAO.get_by_id(rec_id)
        self.assertIsNotNone(rec)
        self.assertEqual(rec["reference_no"], "PERSIST-001")
        self.assertEqual(rec["amount"], 300.0)


# ======================================================================
# 18: Customer balance behavior
# ======================================================================
class TestCRBalance(_BaseTest):
    def test_18_balance_after_sale(self):
        balance = CustomerReceiptDAO.get_customer_balance(self.customer_id)
        # Sale = 500, no credit notes, no receipts
        self.assertAlmostEqual(balance, 500.0, places=2)

    def test_18b_balance_after_receipt(self):
        CustomerReceiptDAO.insert_receipt({"receipt_date": "2026-01-20", "receipt_time": "10:00", "customer_id": self.customer_id, "receipt_mode": "Cash", "amount": 200, "reference_no": "", "remarks": ""})
        balance = CustomerReceiptDAO.get_customer_balance(self.customer_id)
        # 500 (sale) - 0 (credit notes) - 200 (receipts) = 300
        self.assertAlmostEqual(balance, 300.0, places=2)

    def test_18c_balance_full_payment(self):
        CustomerReceiptDAO.insert_receipt({"receipt_date": "2026-01-20", "receipt_time": "10:00", "customer_id": self.customer_id, "receipt_mode": "Cash", "amount": 500, "reference_no": "", "remarks": ""})
        balance = CustomerReceiptDAO.get_customer_balance(self.customer_id)
        self.assertAlmostEqual(balance, 0.0, places=2)

    def test_18d_balance_overpayment(self):
        CustomerReceiptDAO.insert_receipt({"receipt_date": "2026-01-20", "receipt_time": "10:00", "customer_id": self.customer_id, "receipt_mode": "Cash", "amount": 700, "reference_no": "", "remarks": ""})
        balance = CustomerReceiptDAO.get_customer_balance(self.customer_id)
        self.assertAlmostEqual(balance, -200.0, places=2)


# ======================================================================
# 19-25: Cross-module verification
# ======================================================================
class TestCRCrossModule(_BaseTest):
    def test_19_counter_sale_still_works(self):
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

    def test_20_credit_note_still_works(self):
        cn_header = {"voucher_date": "2026-01-25", "cn_date": "2026-01-25", "cn_type": "Customer", "customer_id": self.customer_id, "total_amount": 100, "ledger_amount": 100, "remarks": ""}
        cn_items = [{"item_id": self.item_id, "stock_batch_id": self.batch_id, "batch_no": "BATCH-A", "expiry": "12/27", "pack_size": "10x10", "rate": 40, "mrp": 50, "return_qty": 2, "less_amount": 0, "amount": 100, "return_reason": "", "price_factor": 1.0}]
        before = StockDAO.get_stock_batch_by_id(self.batch_id)["stock_qty"]
        cn_id = CreditNoteDAO.insert_credit_note(cn_header, cn_items)
        after = StockDAO.get_stock_batch_by_id(self.batch_id)["stock_qty"]
        self.assertGreater(after, before)

    def test_21_purchase_still_works(self):
        inv_id = PurchaseDAO.insert_invoice(
            voucher_no="PV-0099", voucher_date="2026-03-01", voucher_time="",
            purchase_type="Cash", supplier_id=self.supplier_id,
            invoice_no="INV-099", invoice_date="2026-03-01",
            invoice_net_amount=500.0, bill_discount=0, due_date="",
            total_amount=500.0, gst_amount=0, debit_note_amount=0,
            other_amount=0, paid_amount=500.0, round_off=0, net_amount=500.0,
            remarks="",
            items=[{"item_id": self.item_id, "pack_size": "10x10", "pay_qty": 10, "free_qty": 0, "batch_no": "PBATCH", "expiry": "06/28", "rate": 50, "mrp": 60, "discount": 0, "gst_percent": 0, "gst_amount": 0, "amount": 500, "purchase_rate": 50, "net_rate": 50, "pp": 50}],
        )
        self.assertGreater(inv_id, 0)

    def test_22_debit_note_still_works(self):
        dn_header = {"voucher_date": "2026-01-18", "voucher_time": "10:00", "dn_date": "2026-01-18", "dn_type": "Supplier", "supplier_id": self.supplier_id, "total_amount": 200, "ledger_amount": 200, "remarks": ""}
        dn_items = [{"item_id": self.item_id, "stock_batch_id": self.batch_id, "batch_no": "BATCH-A", "expiry": "12/27", "pack_size": "10x10", "rate": 40, "mrp": 50, "return_qty": 5, "less_amount": 0, "amount": 200, "return_reason": "", "price_factor": 1.0}]
        dn_id = DebitNoteDAO.insert_debit_note(dn_header, dn_items)
        self.assertGreater(dn_id, 0)

    def test_23_supplier_payment_still_works(self):
        header = {"payment_date": "2026-01-20", "payment_time": "10:00", "supplier_id": self.supplier_id, "payment_mode": "Cash", "amount": 500, "reference_no": "", "remarks": ""}
        pay_id = SupplierPaymentDAO.insert_payment(header)
        self.assertGreater(pay_id, 0)

    def test_24_stock_master_still_works(self):
        all_stock = StockDAO.get_all()
        self.assertGreater(len(all_stock), 0)

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
