import os
import sys
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database.connection import get_connection, init_database
from database.account_roles import ensure_system_ledgers, ROLE_CASH
from database.migrate_ledger_mapping import run_migration
from database.customer_dao import CustomerDAO
from database.supplier_dao import SupplierDAO
from database.ledger_dao import LedgerDAO
from database.customer_receipt_dao import CustomerReceiptDAO
from database.supplier_payment_dao import SupplierPaymentDAO
from database.credit_note_dao import CreditNoteDAO
from database.debit_note_dao import DebitNoteDAO
from database.purchase_dao import PurchaseDAO
from database.sales_dao import SalesDAO
from database.journal_dao import JournalDAO
from database.company_dao import CompanyDAO
from database.unit_dao import UnitDAO
from database.drug_dao import DrugDAO
from database.item_dao import ItemDAO
from database.stock_dao import StockDAO
from database.doctor_dao import DoctorDAO


class _BaseTest(unittest.TestCase):
    """Shared setUp — fresh DB, clean state."""

    _DB_PATH = os.path.join(os.path.dirname(__file__), "_test_mapping.db")

    @classmethod
    def setUpClass(cls):
        if os.path.exists(cls._DB_PATH):
            os.remove(cls._DB_PATH)
        os.environ["PHARMACY_DB"] = cls._DB_PATH
        init_database()

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

    def tearDown(self):
        self.conn.close()


# ======================================================================
# 1-14: Migration & Mapping Tests
# ======================================================================
class TestMigration(_BaseTest):
    def test_01_existing_customer_receives_one_ledger(self):
        cid = CustomerDAO.insert.__wrapped__(
            customer_name="TestCust", opening_balance=500.0,
        ) if hasattr(CustomerDAO.insert, '__wrapped__') else None
        # Use raw insert to simulate pre-migration state
        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO customers (customer_name, opening_balance) VALUES (?, ?)",
                ("OldCustomer", 100.0),
            )
            conn.commit()
            row = conn.execute("SELECT id FROM customers WHERE customer_name = 'OldCustomer'").fetchone()
            cust_id = row["id"]
        finally:
            conn.close()

        result = run_migration()
        self.assertEqual(result["status"], "success")
        self.assertGreaterEqual(result["customers_migrated"], 1)

        cust = CustomerDAO.get_by_id(cust_id)
        self.assertIsNotNone(cust["ledger_id"])
        ledger = LedgerDAO.get_ledger_by_id(cust["ledger_id"])
        self.assertIsNotNone(ledger)
        self.assertEqual(ledger["ledger_name"], "Customer - OldCustomer")

    def test_02_existing_supplier_receives_one_ledger(self):
        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO suppliers (supplier_name, opening_balance) VALUES (?, ?)",
                ("OldSupplier", 200.0),
            )
            conn.commit()
            row = conn.execute("SELECT id FROM suppliers WHERE supplier_name = 'OldSupplier'").fetchone()
            sup_id = row["id"]
        finally:
            conn.close()

        result = run_migration()
        self.assertEqual(result["status"], "success")
        self.assertGreaterEqual(result["suppliers_migrated"], 1)

        sup = SupplierDAO.get_by_id(sup_id)
        self.assertIsNotNone(sup["ledger_id"])
        ledger = LedgerDAO.get_ledger_by_id(sup["ledger_id"])
        self.assertIsNotNone(ledger)
        self.assertEqual(ledger["ledger_name"], "Supplier - OldSupplier")

    def test_03_existing_linked_records_not_duplicated(self):
        # Insert customer + ledger manually, link them
        conn = get_connection()
        try:
            ledger_id = conn.execute(
                "INSERT INTO account_ledgers (ledger_name, account_group) VALUES (?, ?)",
                ("Customer - PreExisting", "Sundry Debtors"),
            ).lastrowid
            conn.execute(
                "INSERT INTO customers (customer_name, opening_balance, ledger_id) VALUES (?, ?, ?)",
                ("PreExisting", 0.0, ledger_id),
            )
            conn.commit()
            row = conn.execute("SELECT id FROM customers WHERE customer_name = 'PreExisting'").fetchone()
            cust_id = row["id"]
        finally:
            conn.close()

        result = run_migration()

        cust = CustomerDAO.get_by_id(cust_id)
        self.assertEqual(cust["ledger_id"], ledger_id)

        # No duplicate ledger created
        ledgers = LedgerDAO.search_ledgers("Customer - PreExisting")
        self.assertEqual(len(ledgers), 1)

    def test_04_new_customer_auto_creates_ledger(self):
        cid = CustomerDAO.insert(customer_name="BrandNew", opening_balance=0.0)
        cust = CustomerDAO.get_by_id(cid)
        self.assertIsNotNone(cust["ledger_id"])
        ledger = LedgerDAO.get_ledger_by_id(cust["ledger_id"])
        self.assertEqual(ledger["ledger_name"], "Customer - BrandNew")

    def test_05_new_supplier_auto_creates_ledger(self):
        sid = SupplierDAO.insert(supplier_name="BrandNewSup", opening_balance=0.0)
        sup = SupplierDAO.get_by_id(sid)
        self.assertIsNotNone(sup["ledger_id"])
        ledger = LedgerDAO.get_ledger_by_id(sup["ledger_id"])
        self.assertEqual(ledger["ledger_name"], "Supplier - BrandNewSup")

    def test_06_edit_customer_no_second_ledger(self):
        cid = CustomerDAO.insert(customer_name="EditCust")
        cust = CustomerDAO.get_by_id(cid)
        original_ledger_id = cust["ledger_id"]

        CustomerDAO.update(
            cid, customer_name="EditCust Updated",
            city="Mumbai", credit_limit=500.0,
        )

        cust = CustomerDAO.get_by_id(cid)
        self.assertEqual(cust["ledger_id"], original_ledger_id)
        ledger = LedgerDAO.get_ledger_by_id(original_ledger_id)
        self.assertEqual(ledger["ledger_name"], "Customer - EditCust Updated")
        self.assertEqual(ledger["city"], "Mumbai")

    def test_07_edit_supplier_no_second_ledger(self):
        sid = SupplierDAO.insert(supplier_name="EditSup")
        sup = SupplierDAO.get_by_id(sid)
        original_ledger_id = sup["ledger_id"]

        SupplierDAO.update(
            sid, supplier_name="EditSup Updated",
            city="Delhi", credit_limit=1000.0,
        )

        sup = SupplierDAO.get_by_id(sid)
        self.assertEqual(sup["ledger_id"], original_ledger_id)
        ledger = LedgerDAO.get_ledger_by_id(original_ledger_id)
        self.assertEqual(ledger["ledger_name"], "Supplier - EditSup Updated")
        self.assertEqual(ledger["city"], "Delhi")

    def test_08_customer_ledger_id_persists(self):
        cid = CustomerDAO.insert(customer_name="PersistCust")
        cust = CustomerDAO.get_by_id(cid)
        ledger_id = cust["ledger_id"]

        # Read again
        cust2 = CustomerDAO.get_by_id(cid)
        self.assertEqual(cust2["ledger_id"], ledger_id)

    def test_09_supplier_ledger_id_persists(self):
        sid = SupplierDAO.insert(supplier_name="PersistSup")
        sup = SupplierDAO.get_by_id(sid)
        ledger_id = sup["ledger_id"]

        sup2 = SupplierDAO.get_by_id(sid)
        self.assertEqual(sup2["ledger_id"], ledger_id)

    def test_10_customer_opening_balance_migrates(self):
        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO customers (customer_name, opening_balance) VALUES (?, ?)",
                ("OBCust", 750.0),
            )
            conn.commit()
            row = conn.execute("SELECT id FROM customers WHERE customer_name = 'OBCust'").fetchone()
            cust_id = row["id"]
        finally:
            conn.close()

        run_migration()

        cust = CustomerDAO.get_by_id(cust_id)
        ledger = LedgerDAO.get_ledger_by_id(cust["ledger_id"])
        self.assertEqual(ledger["opening_balance"], 750.0)
        self.assertEqual(ledger["opening_balance_type"], "Debit")

    def test_11_supplier_opening_balance_migrates(self):
        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO suppliers (supplier_name, opening_balance) VALUES (?, ?)",
                ("OBSup", 1200.0),
            )
            conn.commit()
            row = conn.execute("SELECT id FROM suppliers WHERE supplier_name = 'OBSup'").fetchone()
            sup_id = row["id"]
        finally:
            conn.close()

        run_migration()

        sup = SupplierDAO.get_by_id(sup_id)
        ledger = LedgerDAO.get_ledger_by_id(sup["ledger_id"])
        self.assertEqual(ledger["opening_balance"], 1200.0)
        self.assertEqual(ledger["opening_balance_type"], "Credit")

    def test_12_ledger_opening_balance_correct(self):
        cid = CustomerDAO.insert(customer_name="OBCheck", opening_balance=300.0)
        cust = CustomerDAO.get_by_id(cid)
        ledger = LedgerDAO.get_ledger_by_id(cust["ledger_id"])
        self.assertEqual(ledger["opening_balance"], 300.0)
        self.assertEqual(ledger["opening_balance_type"], "Debit")

    def test_13_migration_safe_when_run_twice(self):
        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO customers (customer_name, opening_balance) VALUES (?, ?)",
                ("TwiceCust", 100.0),
            )
            conn.execute(
                "INSERT INTO suppliers (supplier_name, opening_balance) VALUES (?, ?)",
                ("TwiceSup", 200.0),
            )
            conn.commit()
        finally:
            conn.close()

        r1 = run_migration()
        r2 = run_migration()

        # Second run should not create duplicates
        ledgers = LedgerDAO.search_ledgers("Customer - TwiceCust")
        self.assertEqual(len(ledgers), 1)
        ledgers = LedgerDAO.search_ledgers("Supplier - TwiceSup")
        self.assertEqual(len(ledgers), 1)

    def test_14_migration_no_duplicate_ledgers(self):
        conn = get_connection()
        try:
            for name in ["DupCust1", "DupCust2", "DupCust3"]:
                conn.execute(
                    "INSERT INTO customers (customer_name, opening_balance) VALUES (?, ?)",
                    (name, 0.0),
                )
            conn.commit()
        finally:
            conn.close()

        run_migration()

        all_ledgers = LedgerDAO.get_all_ledgers()
        cust_ledgers = [l for l in all_ledgers if l["ledger_name"].startswith("Customer -")]
        self.assertEqual(len(cust_ledgers), 3)


# ======================================================================
# 15-16: Deletion Safety Tests
# ======================================================================
class TestDeletionSafety(_BaseTest):
    def test_15_customer_delete_no_ledger_with_transactions(self):
        cid = CustomerDAO.insert(customer_name="DelCust")
        cust = CustomerDAO.get_by_id(cid)
        ledger_id = cust["ledger_id"]

        # Add a transaction to the ledger
        LedgerDAO.add_transaction({
            "ledger_id": ledger_id,
            "transaction_date": "2026-01-15",
            "voucher_type": "Manual",
            "voucher_no": "M-001",
            "debit": 100.0,
            "credit": 0.0,
        })

        # Delete should fail (returns False)
        result = CustomerDAO.delete(cid)
        self.assertFalse(result)

        # Customer still exists
        cust = CustomerDAO.get_by_id(cid)
        self.assertIsNotNone(cust)

    def test_16_supplier_delete_no_ledger_with_transactions(self):
        sid = SupplierDAO.insert(supplier_name="DelSup")
        sup = SupplierDAO.get_by_id(sid)
        ledger_id = sup["ledger_id"]

        LedgerDAO.add_transaction({
            "ledger_id": ledger_id,
            "transaction_date": "2026-01-15",
            "voucher_type": "Manual",
            "voucher_no": "M-002",
            "debit": 0.0,
            "credit": 200.0,
        })

        result = SupplierDAO.delete(sid)
        self.assertFalse(result)

        sup = SupplierDAO.get_by_id(sid)
        self.assertIsNotNone(sup)


# ======================================================================
# 17-29: Cross-Module Tests
# ======================================================================
class TestCrossModule(_BaseTest):
    def setUp(self):
        super().setUp()
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

    def test_17_company_master_works(self):
        all_companies = CompanyDAO.get_all()
        self.assertGreater(len(all_companies), 0)

    def test_18_unit_master_works(self):
        all_units = UnitDAO.get_all()
        self.assertGreater(len(all_units), 0)

    def test_19_drug_master_works(self):
        all_drugs = DrugDAO.get_all()
        self.assertGreater(len(all_drugs), 0)

    def test_20_item_master_works(self):
        all_items = ItemDAO.get_all()
        self.assertGreater(len(all_items), 0)

    def test_21_purchase_works(self):
        PurchaseDAO.insert_invoice(
            voucher_no="PV-0001", voucher_date="2026-03-01", voucher_time="",
            purchase_type="Cash", supplier_id=self.supplier_id,
            invoice_no="INV-001", invoice_date="2026-03-01",
            invoice_net_amount=500.0, bill_discount=0, due_date="",
            total_amount=500.0, gst_amount=0, debit_note_amount=0,
            other_amount=0, paid_amount=500.0, round_off=0, net_amount=500.0,
            remarks="",
            items=[{"item_id": self.item_id, "pack_size": "10x10", "pay_qty": 10, "free_qty": 0, "batch_no": "PBATCH", "expiry": "06/28", "rate": 50, "mrp": 60, "discount": 0, "gst_percent": 0, "gst_amount": 0, "amount": 500, "purchase_rate": 50, "net_rate": 50, "pp": 50}],
        )
        batches = StockDAO.get_stock_batches_for_item(self.item_id)
        self.assertGreater(len(batches), 0)

    def test_22_counter_sale_works(self):
        ensure_system_ledgers()
        PurchaseDAO.insert_invoice(
            voucher_no="PV-CS", voucher_date="2026-01-01", voucher_time="",
            purchase_type="Cash", supplier_id=self.supplier_id,
            invoice_no="INV-CS", invoice_date="2026-01-01",
            invoice_net_amount=4000.0, bill_discount=0, due_date="",
            total_amount=4000.0, gst_amount=0, debit_note_amount=0,
            other_amount=0, paid_amount=4000.0, round_off=0, net_amount=4000.0,
            remarks="",
            items=[{"item_id": self.item_id, "pack_size": "10x10", "pay_qty": 100, "free_qty": 0, "batch_no": "BATCH-A", "expiry": "12/27", "rate": 40, "mrp": 50, "discount": 0, "gst_percent": 0, "gst_amount": 0, "amount": 4000, "purchase_rate": 40, "net_rate": 40, "pp": 40}],
        )
        batches = StockDAO.get_stock_batches_for_item(self.item_id)
        batch_id = batches[0]["id"]
        sale_id = SalesDAO.insert_invoice(
            bill_no="CS-0001", sale_date="2026-01-25", sale_time="10:00",
            sale_type="Cash", customer_id=self.customer_id,
            patient_name="TestPatient", doctor_id=None,
            discount=0, paid_amount=250, total_amount=250, round_off=0,
            net_amount=250, remarks="",
            items=[{"item_id": self.item_id, "stock_batch_id": batch_id, "pack_size": "10x10", "location": "", "batch_no": "BATCH-A", "expiry": "12/27", "mrp": 50, "sale_qty": 5, "discount_amount": 0, "amount": 250}],
        )
        self.assertGreater(sale_id, 0)

    def test_23_credit_note_works(self):
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

    def test_24_debit_note_works(self):
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

    def test_25_supplier_payment_works(self):
        pay_id = SupplierPaymentDAO.insert_payment({
            "payment_date": "2026-01-20", "payment_time": "10:00",
            "supplier_id": self.supplier_id, "payment_mode": "Cash",
            "amount": 500, "reference_no": "", "remarks": "",
        })
        self.assertGreater(pay_id, 0)

    def test_26_customer_receipt_works(self):
        ensure_system_ledgers()
        rec_id = CustomerReceiptDAO.insert_receipt({
            "receipt_date": "2026-01-20", "receipt_time": "10:00",
            "customer_id": self.customer_id, "receipt_mode": "Cash",
            "amount": 300, "reference_no": "", "remarks": "",
        })
        self.assertGreater(rec_id, 0)

    def test_27_journal_entry_works(self):
        items = [
            {"ledger_id": self.cash_ledger_id, "description": "", "debit": 100, "credit": 0},
            {"ledger_id": self.capital_ledger_id, "description": "", "debit": 0, "credit": 100},
        ]
        eid = JournalDAO.insert_entry({"entry_date": "2026-01-15", "entry_time": "", "narration": ""}, items)
        self.assertGreater(eid, 0)

    def test_28_account_ledger_works(self):
        all_ledgers = LedgerDAO.get_all_ledgers()
        self.assertGreater(len(all_ledgers), 0)
        balance = LedgerDAO.get_balance(self.cash_ledger_id)
        self.assertIsNotNone(balance)

    def test_29_stock_master_works(self):
        all_stock = StockDAO.get_all()
        self.assertIsInstance(all_stock, list)


# ======================================================================
# 30-35: Customer/Supplier Ledger Mapping DAO Tests
# ======================================================================
class TestCustomerLedgerMapping(_BaseTest):
    def test_30_get_ledger_id(self):
        cid = CustomerDAO.insert(customer_name="LedgerIdCust")
        ledger_id = CustomerDAO.get_ledger_id(cid)
        self.assertIsNotNone(ledger_id)
        self.assertGreater(ledger_id, 0)

    def test_31_get_customer_by_ledger(self):
        cid = CustomerDAO.insert(customer_name="ByLedgerCust")
        ledger_id = CustomerDAO.get_ledger_id(cid)
        cust = CustomerDAO.get_customer_by_ledger(ledger_id)
        self.assertIsNotNone(cust)
        self.assertEqual(cust["id"], cid)

    def test_32_get_ledger_id_returns_none_for_missing(self):
        self.assertIsNone(CustomerDAO.get_ledger_id(99999))

    def test_33_get_customer_by_ledger_returns_none(self):
        self.assertIsNone(CustomerDAO.get_customer_by_ledger(99999))


class TestSupplierLedgerMapping(_BaseTest):
    def test_34_get_ledger_id(self):
        sid = SupplierDAO.insert(supplier_name="LedgerIdSup")
        ledger_id = SupplierDAO.get_ledger_id(sid)
        self.assertIsNotNone(ledger_id)
        self.assertGreater(ledger_id, 0)

    def test_35_get_supplier_by_ledger(self):
        sid = SupplierDAO.insert(supplier_name="ByLedgerSup")
        ledger_id = SupplierDAO.get_ledger_id(sid)
        sup = SupplierDAO.get_supplier_by_ledger(ledger_id)
        self.assertIsNotNone(sup)
        self.assertEqual(sup["id"], sid)

    def test_36_get_ledger_id_returns_none_for_missing(self):
        self.assertIsNone(SupplierDAO.get_ledger_id(99999))

    def test_37_get_supplier_by_ledger_returns_none(self):
        self.assertIsNone(SupplierDAO.get_supplier_by_ledger(99999))


# ======================================================================
# 38-42: Legacy Balance Methods Still Work
# ======================================================================
class TestLegacyBalanceMethods(_BaseTest):
    def setUp(self):
        super().setUp()
        self.company_id = CompanyDAO.insert("TestCo", "TC")
        self.unit_id = UnitDAO.insert("Pcs")
        self.drug_id = DrugDAO.insert("Paracetamol")
        self.customer_id = CustomerDAO.insert("LegacyCust")
        self.supplier_id = SupplierDAO.insert("LegacySup")
        self.doctor_id = DoctorDAO.insert("Dr. Legacy")
        self.item_id = ItemDAO.insert(
            item_name="LegacyItem", unit_id=self.unit_id,
            company_id=self.company_id, pack_size="10x10",
            reorder_stock_level=10,
        )

    def test_38_customer_balance_still_works(self):
        balance = CustomerReceiptDAO.get_customer_balance(self.customer_id)
        self.assertEqual(balance, 0.0)

    def test_39_supplier_balance_still_works(self):
        balance = SupplierPaymentDAO.get_supplier_balance(self.supplier_id)
        self.assertEqual(balance, 0.0)

    def test_40_customer_balance_after_sale(self):
        ensure_system_ledgers()
        PurchaseDAO.insert_invoice(
            voucher_no="PV-LB", voucher_date="2026-01-01", voucher_time="",
            purchase_type="Cash", supplier_id=self.supplier_id,
            invoice_no="INV-LB", invoice_date="2026-01-01",
            invoice_net_amount=4000.0, bill_discount=0, due_date="",
            total_amount=4000.0, gst_amount=0, debit_note_amount=0,
            other_amount=0, paid_amount=4000.0, round_off=0, net_amount=4000.0,
            remarks="",
            items=[{"item_id": self.item_id, "pack_size": "10x10", "pay_qty": 100, "free_qty": 0, "batch_no": "BATCH-A", "expiry": "12/27", "rate": 40, "mrp": 50, "discount": 0, "gst_percent": 0, "gst_amount": 0, "amount": 4000, "purchase_rate": 40, "net_rate": 40, "pp": 40}],
        )
        batches = StockDAO.get_stock_batches_for_item(self.item_id)
        batch_id = batches[0]["id"]
        SalesDAO.insert_invoice(
            bill_no="CS-LB", sale_date="2026-01-25", sale_time="10:00",
            sale_type="Credit", customer_id=self.customer_id,
            patient_name="", doctor_id=None,
            discount=0, paid_amount=0, total_amount=250, round_off=0,
            net_amount=250, remarks="",
            items=[{"item_id": self.item_id, "stock_batch_id": batch_id, "pack_size": "10x10", "location": "", "batch_no": "BATCH-A", "expiry": "12/27", "mrp": 50, "sale_qty": 5, "discount_amount": 0, "amount": 250}],
        )
        balance = CustomerReceiptDAO.get_customer_balance(self.customer_id)
        self.assertEqual(balance, 250.0)

    def test_41_supplier_balance_after_purchase(self):
        PurchaseDAO.insert_invoice(
            voucher_no="PV-SB", voucher_date="2026-01-01", voucher_time="",
            purchase_type="Credit", supplier_id=self.supplier_id,
            invoice_no="INV-SB", invoice_date="2026-01-01",
            invoice_net_amount=1000.0, bill_discount=0, due_date="",
            total_amount=1000.0, gst_amount=0, debit_note_amount=0,
            other_amount=0, paid_amount=0, round_off=0, net_amount=1000.0,
            remarks="",
            items=[{"item_id": self.item_id, "pack_size": "10x10", "pay_qty": 20, "free_qty": 0, "batch_no": "BATCH-B", "expiry": "12/27", "rate": 50, "mrp": 60, "discount": 0, "gst_percent": 0, "gst_amount": 0, "amount": 1000, "purchase_rate": 50, "net_rate": 50, "pp": 50}],
        )
        balance = SupplierPaymentDAO.get_supplier_balance(self.supplier_id)
        self.assertEqual(balance, 1000.0)

    def test_42_all_master_screens_still_work(self):
        self.assertGreater(len(CompanyDAO.get_all()), 0)
        self.assertGreater(len(UnitDAO.get_all()), 0)
        self.assertGreater(len(DrugDAO.get_all()), 0)
        self.assertGreater(len(SupplierDAO.get_all()), 0)
        self.assertGreater(len(CustomerDAO.get_all()), 0)
        self.assertGreater(len(DoctorDAO.get_all()), 0)
        self.assertGreater(len(ItemDAO.get_all()), 0)


if __name__ == "__main__":
    unittest.main()
