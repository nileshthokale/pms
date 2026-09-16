import os
import sys
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database.connection import get_connection, init_database
from database.account_roles import ensure_system_ledgers
from database.supplier_payment_dao import SupplierPaymentDAO
from database.supplier_dao import SupplierDAO
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
from database.debit_note_dao import DebitNoteDAO


class _BaseTest(unittest.TestCase):
    """Shared setUp — fresh DB, seed master data, purchase, and a stock batch."""

    _DB_PATH = os.path.join(os.path.dirname(__file__), "_test_sp.db")

    @classmethod
    def setUpClass(cls):
        if os.path.exists(cls._DB_PATH):
            os.remove(cls._DB_PATH)
        os.environ["PHARMACY_DB"] = cls._DB_PATH
        init_database()

        conn = get_connection()
        try:
            for tbl in [
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

        ensure_system_ledgers()

        self.item_id = ItemDAO.insert(
            item_name="TestItem",
            unit_id=self.unit_id,
            company_id=self.company_id,
            pack_size="10x10",
            reorder_stock_level=10,
        )

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
class TestSPBasicCRUD(_BaseTest):
    def test_01_create_payment(self):
        header = {
            "payment_date": "2026-01-20", "payment_time": "10:00",
            "supplier_id": self.supplier_id, "payment_mode": "Cash",
            "amount": 500.0, "reference_no": "CASH-001",
            "remarks": "Paid against PV-0001",
        }
        pay_id = SupplierPaymentDAO.insert_payment(header)
        self.assertGreater(pay_id, 0)

        pay = SupplierPaymentDAO.get_by_id(pay_id)
        self.assertIsNotNone(pay)
        self.assertEqual(pay["voucher_no"], "SP-0001")
        self.assertEqual(pay["amount"], 500.0)
        self.assertEqual(pay["payment_mode"], "Cash")
        self.assertEqual(pay["supplier_name"], "TestSupplier")

    def test_02_voucher_number_auto_increment(self):
        h1 = {"payment_date": "2026-01-20", "payment_time": "10:00", "supplier_id": self.supplier_id, "payment_mode": "Cash", "amount": 500, "reference_no": "", "remarks": ""}
        h2 = {"payment_date": "2026-01-21", "payment_time": "11:00", "supplier_id": self.supplier_id, "payment_mode": "Bank", "amount": 1000, "reference_no": "", "remarks": ""}

        id1 = SupplierPaymentDAO.insert_payment(h1)
        id2 = SupplierPaymentDAO.insert_payment(h2)

        p1 = SupplierPaymentDAO.get_by_id(id1)
        p2 = SupplierPaymentDAO.get_by_id(id2)
        self.assertEqual(p1["voucher_no"], "SP-0001")
        self.assertEqual(p2["voucher_no"], "SP-0002")

    def test_03_multiple_payments(self):
        for i in range(5):
            header = {"payment_date": f"2026-01-{10+i}", "payment_time": "10:00", "supplier_id": self.supplier_id, "payment_mode": "Cash", "amount": 100, "reference_no": "", "remarks": f"Payment {i+1}"}
            SupplierPaymentDAO.insert_payment(header)
        all_pays = SupplierPaymentDAO.get_all()
        self.assertEqual(len(all_pays), 5)

    def test_04_edit_payment(self):
        header = {"payment_date": "2026-01-20", "payment_time": "10:00", "supplier_id": self.supplier_id, "payment_mode": "Cash", "amount": 500, "reference_no": "OLD-REF", "remarks": "old"}
        pay_id = SupplierPaymentDAO.insert_payment(header)

        new_header = {"payment_date": "2026-01-21", "payment_time": "11:00", "supplier_id": self.supplier_id, "payment_mode": "Bank", "amount": 800, "reference_no": "NEW-REF", "remarks": "updated"}
        SupplierPaymentDAO.update_payment(pay_id, new_header)

        pay = SupplierPaymentDAO.get_by_id(pay_id)
        self.assertEqual(pay["amount"], 800)
        self.assertEqual(pay["payment_mode"], "Bank")
        self.assertEqual(pay["reference_no"], "NEW-REF")
        self.assertEqual(pay["remarks"], "updated")

    def test_05_delete_payment(self):
        header = {"payment_date": "2026-01-20", "payment_time": "10:00", "supplier_id": self.supplier_id, "payment_mode": "Cash", "amount": 500, "reference_no": "", "remarks": ""}
        pay_id = SupplierPaymentDAO.insert_payment(header)
        self.assertIsNotNone(SupplierPaymentDAO.get_by_id(pay_id))

        SupplierPaymentDAO.delete_payment(pay_id)
        self.assertIsNone(SupplierPaymentDAO.get_by_id(pay_id))

    def test_06_get_by_id_returns_none(self):
        self.assertIsNone(SupplierPaymentDAO.get_by_id(9999))


# ======================================================================
# 7-9: Filtering
# ======================================================================
class TestSPFiltering(_BaseTest):
    def _create_pay(self, date="2026-01-20", sup_id=None, amount=200):
        header = {"payment_date": date, "payment_time": "10:00", "supplier_id": sup_id or self.supplier_id, "payment_mode": "Cash", "amount": amount, "reference_no": "", "remarks": ""}
        return SupplierPaymentDAO.insert_payment(header)

    def test_07_filter_by_date(self):
        self._create_pay(date="2026-01-15")
        self._create_pay(date="2026-02-10")
        results = SupplierPaymentDAO.get_all_filtered(date_from="2026-02-01", date_to="2026-02-28")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["payment_date"], "2026-02-10")

    def test_08_filter_by_supplier(self):
        sup2_id = SupplierDAO.insert("SupTwo")
        self._create_pay(sup_id=self.supplier_id)
        self._create_pay(sup_id=sup2_id)
        results = SupplierPaymentDAO.get_all_filtered(supplier_id=sup2_id)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["supplier_name"], "SupTwo")

    def test_09_filter_all_returns_all(self):
        self._create_pay()
        self._create_pay()
        self._create_pay()
        results = SupplierPaymentDAO.get_all_filtered()
        self.assertEqual(len(results), 3)


# ======================================================================
# 10-12: Validation
# ======================================================================
class TestSPValidation(_BaseTest):
    def test_10_missing_supplier_raises(self):
        header = {"payment_date": "2026-01-20", "payment_time": "", "supplier_id": None, "payment_mode": "Cash", "amount": 500, "reference_no": "", "remarks": ""}
        with self.assertRaises(Exception):
            SupplierPaymentDAO.insert_payment(header)

    def test_11_zero_amount_rejected(self):
        header = {"payment_date": "2026-01-20", "payment_time": "", "supplier_id": self.supplier_id, "payment_mode": "Cash", "amount": 0, "reference_no": "", "remarks": ""}
        with self.assertRaises(Exception):
            SupplierPaymentDAO.insert_payment(header)

    def test_12_negative_amount_rejected(self):
        header = {"payment_date": "2026-01-20", "payment_time": "", "supplier_id": self.supplier_id, "payment_mode": "Cash", "amount": -100, "reference_no": "", "remarks": "Adjustment"}
        with self.assertRaises(Exception):
            SupplierPaymentDAO.insert_payment(header)


# ======================================================================
# 13-16: Features
# ======================================================================
class TestSPFeatures(_BaseTest):
    def test_13_payment_modes(self):
        for mode in ["Cash", "Bank", "Cheque", "UPI"]:
            header = {"payment_date": "2026-01-20", "payment_time": "10:00", "supplier_id": self.supplier_id, "payment_mode": mode, "amount": 100, "reference_no": f"REF-{mode}", "remarks": ""}
            SupplierPaymentDAO.insert_payment(header)
        all_pays = SupplierPaymentDAO.get_all()
        self.assertEqual(len(all_pays), 4)
        modes = {p["payment_mode"] for p in all_pays}
        self.assertEqual(modes, {"Cash", "Bank", "Cheque", "UPI"})

    def test_14_reference_no_persisted(self):
        header = {"payment_date": "2026-01-20", "payment_time": "10:00", "supplier_id": self.supplier_id, "payment_mode": "Bank", "amount": 500, "reference_no": "NEFT-12345", "remarks": ""}
        pay_id = SupplierPaymentDAO.insert_payment(header)
        pay = SupplierPaymentDAO.get_by_id(pay_id)
        self.assertEqual(pay["reference_no"], "NEFT-12345")

    def test_15_remarks_persisted(self):
        header = {"payment_date": "2026-01-20", "payment_time": "10:00", "supplier_id": self.supplier_id, "payment_mode": "Cash", "amount": 500, "reference_no": "", "remarks": "Payment for January purchase"}
        pay_id = SupplierPaymentDAO.insert_payment(header)
        pay = SupplierPaymentDAO.get_by_id(pay_id)
        self.assertEqual(pay["remarks"], "Payment for January purchase")

    def test_16_multiple_suppliers(self):
        sup2_id = SupplierDAO.insert("SupTwo")
        SupplierPaymentDAO.insert_payment({"payment_date": "2026-01-20", "payment_time": "10:00", "supplier_id": self.supplier_id, "payment_mode": "Cash", "amount": 500, "reference_no": "", "remarks": ""})
        SupplierPaymentDAO.insert_payment({"payment_date": "2026-01-20", "payment_time": "10:00", "supplier_id": sup2_id, "payment_mode": "Bank", "amount": 700, "reference_no": "", "remarks": ""})
        all_pays = SupplierPaymentDAO.get_all()
        self.assertEqual(len(all_pays), 2)
        names = {p["supplier_name"] for p in all_pays}
        self.assertEqual(names, {"TestSupplier", "SupTwo"})


# ======================================================================
# 17-19: Persistence
# ======================================================================
class TestSPPersistence(_BaseTest):
    def test_17_get_all_returns_descending(self):
        for i in range(3):
            SupplierPaymentDAO.insert_payment({"payment_date": f"2026-01-{10+i}", "payment_time": "10:00", "supplier_id": self.supplier_id, "payment_mode": "Cash", "amount": 100, "reference_no": "", "remarks": ""})
        all_pays = SupplierPaymentDAO.get_all()
        self.assertEqual(len(all_pays), 3)
        # Latest inserted should be first (descending by id)
        self.assertEqual(all_pays[0]["voucher_no"], "SP-0003")

    def test_18_edit_preserves_voucher_no(self):
        header = {"payment_date": "2026-01-20", "payment_time": "10:00", "supplier_id": self.supplier_id, "payment_mode": "Cash", "amount": 500, "reference_no": "", "remarks": ""}
        pay_id = SupplierPaymentDAO.insert_payment(header)
        original_voucher = SupplierPaymentDAO.get_by_id(pay_id)["voucher_no"]
        SupplierPaymentDAO.update_payment(pay_id, {"payment_date": "2026-01-21", "payment_time": "11:00", "supplier_id": self.supplier_id, "payment_mode": "Bank", "amount": 800, "reference_no": "", "remarks": ""})
        pay = SupplierPaymentDAO.get_by_id(pay_id)
        self.assertEqual(pay["voucher_no"], original_voucher)

    def test_19_delete_all_leaves_empty(self):
        for i in range(3):
            pay_id = SupplierPaymentDAO.insert_payment({"payment_date": f"2026-01-{10+i}", "payment_time": "10:00", "supplier_id": self.supplier_id, "payment_mode": "Cash", "amount": 100, "reference_no": "", "remarks": ""})
            SupplierPaymentDAO.delete_payment(pay_id)
        all_pays = SupplierPaymentDAO.get_all()
        self.assertEqual(len(all_pays), 0)


# ======================================================================
# 20-22: Balance calculation
# ======================================================================
class TestSPBalance(_BaseTest):
    def test_20_balance_initial(self):
        balance = SupplierPaymentDAO.get_supplier_balance(self.supplier_id)
        # Purchases = 4000, no debit notes, no payments
        self.assertAlmostEqual(balance, 4000.0, places=2)

    def test_21_balance_after_payment(self):
        SupplierPaymentDAO.insert_payment({"payment_date": "2026-01-20", "payment_time": "10:00", "supplier_id": self.supplier_id, "payment_mode": "Cash", "amount": 500, "reference_no": "", "remarks": ""})
        balance = SupplierPaymentDAO.get_supplier_balance(self.supplier_id)
        self.assertAlmostEqual(balance, 3500.0, places=2)

    def test_22_balance_after_debit_note_and_payment(self):
        # Create debit note returning goods worth 400
        dn_header = {"voucher_date": "2026-01-18", "voucher_time": "10:00", "dn_date": "2026-01-18", "dn_type": "Supplier", "supplier_id": self.supplier_id, "total_amount": 400, "ledger_amount": 400, "remarks": ""}
        dn_items = [{"item_id": self.item_id, "stock_batch_id": self.batch_id, "batch_no": "BATCH-A", "expiry": "12/27", "pack_size": "10x10", "rate": 40, "mrp": 50, "return_qty": 10, "less_amount": 0, "amount": 400, "return_reason": "", "price_factor": 1.0}]
        DebitNoteDAO.insert_debit_note(dn_header, dn_items)

        # Payment of 1500
        SupplierPaymentDAO.insert_payment({"payment_date": "2026-01-20", "payment_time": "10:00", "supplier_id": self.supplier_id, "payment_mode": "Bank", "amount": 1500, "reference_no": "NEFT-001", "remarks": ""})

        balance = SupplierPaymentDAO.get_supplier_balance(self.supplier_id)
        # 4000 (purchases) - 400 (debit note) - 1500 (payment) = 2100
        self.assertAlmostEqual(balance, 2100.0, places=2)

    def test_23_balance_after_full_payment(self):
        SupplierPaymentDAO.insert_payment({"payment_date": "2026-01-20", "payment_time": "10:00", "supplier_id": self.supplier_id, "payment_mode": "Cash", "amount": 4000, "reference_no": "", "remarks": ""})
        balance = SupplierPaymentDAO.get_supplier_balance(self.supplier_id)
        self.assertAlmostEqual(balance, 0.0, places=2)

    def test_24_balance_overpayment(self):
        SupplierPaymentDAO.insert_payment({"payment_date": "2026-01-20", "payment_time": "10:00", "supplier_id": self.supplier_id, "payment_mode": "Cash", "amount": 5000, "reference_no": "", "remarks": ""})
        balance = SupplierPaymentDAO.get_supplier_balance(self.supplier_id)
        self.assertAlmostEqual(balance, -1000.0, places=2)


# ======================================================================
# 25-28: Edge cases and cross-module verification
# ======================================================================
class TestSPEdgeCases(_BaseTest):
    def test_25_persistence_across_connections(self):
        header = {"payment_date": "2026-01-20", "payment_time": "10:00", "supplier_id": self.supplier_id, "payment_mode": "Cash", "amount": 500, "reference_no": "PERSIST-001", "remarks": "persisted"}
        pay_id = SupplierPaymentDAO.insert_payment(header)

        pay = SupplierPaymentDAO.get_by_id(pay_id)
        self.assertIsNotNone(pay)
        self.assertEqual(pay["reference_no"], "PERSIST-001")

    def test_26_purchase_still_works(self):
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

    def test_27_debit_note_still_works(self):
        dn_header = {"voucher_date": "2026-01-18", "voucher_time": "10:00", "dn_date": "2026-01-18", "dn_type": "Supplier", "supplier_id": self.supplier_id, "total_amount": 200, "ledger_amount": 200, "remarks": ""}
        dn_items = [{"item_id": self.item_id, "stock_batch_id": self.batch_id, "batch_no": "BATCH-A", "expiry": "12/27", "pack_size": "10x10", "rate": 40, "mrp": 50, "return_qty": 5, "less_amount": 0, "amount": 200, "return_reason": "", "price_factor": 1.0}]
        dn_id = DebitNoteDAO.insert_debit_note(dn_header, dn_items)
        self.assertGreater(dn_id, 0)

    def test_28_all_master_screens_still_work(self):
        self.assertGreater(len(CompanyDAO.get_all()), 0)
        self.assertGreater(len(UnitDAO.get_all()), 0)
        self.assertGreater(len(DrugDAO.get_all()), 0)
        self.assertGreater(len(SupplierDAO.get_all()), 0)
        self.assertGreater(len(CustomerDAO.get_all()), 0)
        self.assertGreater(len(DoctorDAO.get_all()), 0)
        self.assertGreater(len(ItemDAO.get_all()), 0)


if __name__ == "__main__":
    unittest.main()
