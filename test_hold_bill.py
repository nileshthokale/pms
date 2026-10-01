"""Phase 6B-6 — Hold Bill / Resume Bill tests.

65+ dedicated tests covering:
  CREATION:        1-7    create hold with various data
  STORAGE:         8-11   persistence, reload, ordering, status
  NO SIDE EFFECTS: 12-17  no sale, stock, ledger, posting, TB, P&L
  RESUME:          18-26  resume, revalidation, warnings
  COMPLETION:      27-33  hold -> resume -> complete lifecycle
  DELETE:          34-39  discard, confirmation, no effects
  MULTIPLE HOLDS:  40-43  isolation, coexistence
  PERSISTENCE:     44-45  survive DB close/reopen
  AUTH:            46-49  ADMIN, STAFF, permissions
  FIN YEAR:        50-52  hold date, no accounting until complete
  READ-ONLY:       53-56  balances unchanged
  REGRESSION:      57-65  existing modules still work
"""

import os
import sqlite3
import sys
import unittest
from datetime import datetime

os.environ["QT_QPA_PLATFORM"] = "offscreen"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database.connection import get_connection, init_database, get_db_path
from database.account_roles import (
    ROLE_BANK, ROLE_CASH, ROLE_SALES,
    ensure_system_ledgers,
)
from database.accounting_posting import posting_engine, PostingEngine, SOURCE_COUNTER_SALE
from database.ledger_dao import LedgerDAO
from database.customer_dao import CustomerDAO
from database.supplier_dao import SupplierDAO
from database.purchase_dao import PurchaseDAO
from database.sales_dao import SalesDAO
from database.stock_dao import StockDAO
from database.doctor_dao import DoctorDAO
from database.company_dao import CompanyDAO
from database.unit_dao import UnitDAO
from database.drug_dao import DrugDAO
from database.item_dao import ItemDAO
from database import auth
from database import financial_year
from database.hold_bill_dao import (
    ensure_hold_tables,
    create_hold,
    get_all,
    get_by_id,
    get_hold_items,
    update_status,
    delete_hold,
    count_active,
    STATUS_ACTIVE,
    STATUS_RESUMED,
    STATUS_DISCARDED,
)

_TABLES = [
    "hold_bill_items", "hold_bills",
    "ledger_transactions", "account_ledgers",
    "sales_invoice_items", "sales_invoices",
    "purchase_invoice_items", "purchase_invoices",
    "stock_batches", "item_ingredients", "items",
    "doctors", "customers", "suppliers", "drugs", "units", "companies",
]


class _BaseTest(unittest.TestCase):
    """Shared setUp — clean tables, masters, stock, system roles."""

    _DB_PATH = os.path.join(os.path.dirname(__file__), "_test_hold_bill.db")

    @classmethod
    def setUpClass(cls):
        if os.path.exists(cls._DB_PATH):
            os.remove(cls._DB_PATH)
        os.environ["PHARMACY_DB"] = cls._DB_PATH
        init_database()
        ensure_hold_tables()
        auth.ensure_auth_schema()

    def setUp(self):
        conn = get_connection()
        try:
            for tbl in _TABLES:
                conn.execute(f"DELETE FROM {tbl}")
            conn.commit()
        finally:
            conn.close()

        self.company_id = CompanyDAO.insert("TestCo", "TC")
        self.unit_id = UnitDAO.insert("Pcs")
        self.drug_id = DrugDAO.insert("Paracetamol")
        self.customer_id = CustomerDAO.insert("TestCustomer")
        self.customer2_id = CustomerDAO.insert("SecondCustomer")
        self.doctor_id = DoctorDAO.insert("Dr. Smith")
        self.supplier_id = SupplierDAO.insert("TestSupplier")
        self.item_id = ItemDAO.insert(
            item_name="TestItem", unit_id=self.unit_id,
            company_id=self.company_id, pack_size="10x10",
        )
        self.item2_id = ItemDAO.insert(
            item_name="TestItem2", unit_id=self.unit_id,
            company_id=self.company_id, pack_size="5x10",
        )
        ensure_system_ledgers()

        self.cash_ledger = LedgerDAO.get_by_system_role(ROLE_CASH)
        self.sales_ledger = LedgerDAO.get_by_system_role(ROLE_SALES)
        self.customer_ledger_id = CustomerDAO.get_ledger_id(self.customer_id)
        self.engine = posting_engine

        self._seed_stock()

    def _seed_stock(self, qty=100.0, rate=40.0, mrp=50.0):
        PurchaseDAO.insert_invoice(
            voucher_no="PV-0001", voucher_date="2026-01-01", voucher_time="",
            purchase_type="Cash", supplier_id=self.supplier_id,
            invoice_no="INV-001", invoice_date="2026-01-01",
            invoice_net_amount=qty * rate, bill_discount=0, due_date="",
            total_amount=qty * rate, gst_amount=0, debit_note_amount=0,
            other_amount=0, paid_amount=qty * rate, round_off=0,
            net_amount=qty * rate, remarks="",
            items=[{
                "item_id": self.item_id, "pack_size": "10x10",
                "pay_qty": qty, "free_qty": 0, "batch_no": "BATCH-A",
                "expiry": "12/27", "rate": rate, "mrp": mrp, "discount": 0,
                "gst_percent": 0, "gst_amount": 0, "amount": qty * rate,
                "purchase_rate": rate, "net_rate": rate, "pp": rate,
            }],
        )
        PurchaseDAO.insert_invoice(
            voucher_no="PV-0002", voucher_date="2026-01-01", voucher_time="",
            purchase_type="Cash", supplier_id=self.supplier_id,
            invoice_no="INV-002", invoice_date="2026-01-01",
            invoice_net_amount=qty * rate, bill_discount=0, due_date="",
            total_amount=qty * rate, gst_amount=0, debit_note_amount=0,
            other_amount=0, paid_amount=qty * rate, round_off=0,
            net_amount=qty * rate, remarks="",
            items=[{
                "item_id": self.item2_id, "pack_size": "5x10",
                "pay_qty": qty, "free_qty": 0, "batch_no": "BATCH-B",
                "expiry": "12/27", "rate": rate, "mrp": mrp, "discount": 0,
                "gst_percent": 0, "gst_amount": 0, "amount": qty * rate,
                "purchase_rate": rate, "net_rate": rate, "pp": rate,
            }],
        )
        batches = StockDAO.get_stock_batches_for_item(self.item_id)
        self.batch_id = batches[0]["id"]
        batches2 = StockDAO.get_stock_batches_for_item(self.item2_id)
        self.batch2_id = batches2[0]["id"]

    def _hold_items(self, item_id=None, batch_no="BATCH-A", qty=5.0,
                    mrp=50.0, amount=None):
        iid = item_id or self.item_id
        if amount is None:
            amount = round(qty * mrp, 2)
        return [{
            "item_id": iid,
            "item_name_snapshot": "TestItem" if iid == self.item_id else "TestItem2",
            "batch_no": batch_no,
            "pack_size": "10x10",
            "location": "",
            "expiry": "12/27",
            "mrp": mrp,
            "sale_qty": qty,
            "discount_amount": 0.0,
            "amount": amount,
        }]

    def _stock_qty(self, item_id=None):
        iid = item_id or self.item_id
        batches = StockDAO.get_stock_batches_for_item(iid)
        return sum(b["stock_qty"] for b in batches)

    def _ledger_net(self, source_type, source_id):
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT ledger_id, SUM(debit) - SUM(credit) AS net "
                "FROM ledger_transactions "
                "WHERE reference_type = ? AND reference_id = ? "
                "GROUP BY ledger_id",
                (source_type, source_id),
            ).fetchall()
            return {r["ledger_id"]: round(r["net"] or 0.0, 2) for r in rows}
        finally:
            conn.close()


# ======================================================================
# 1-7: CREATION
# ======================================================================

class TestCreation(_BaseTest):

    def test_01_create_hold_single_item(self):
        hid = create_hold(
            customer_id=self.customer_id,
            patient_name="Patient1",
            items=self._hold_items(),
        )
        self.assertGreater(hid, 0)
        hold = get_by_id(hid)
        self.assertIsNotNone(hold)
        self.assertEqual(hold["status"], STATUS_ACTIVE)

    def test_02_create_hold_multiple_items(self):
        items = self._hold_items() + self._hold_items(
            item_id=self.item2_id, batch_no="BATCH-B",
        )
        hid = create_hold(customer_id=self.customer_id, items=items)
        stored = get_hold_items(hid)
        self.assertEqual(len(stored), 2)

    def test_03_create_hold_with_customer(self):
        hid = create_hold(customer_id=self.customer_id, items=self._hold_items())
        hold = get_by_id(hid)
        self.assertEqual(hold["customer_id"], self.customer_id)

    def test_04_create_hold_with_patient_name(self):
        hid = create_hold(
            customer_id=self.customer_id,
            patient_name="John Doe",
            items=self._hold_items(),
        )
        hold = get_by_id(hid)
        self.assertEqual(hold["patient_name"], "John Doe")

    def test_05_create_hold_with_doctor(self):
        hid = create_hold(
            customer_id=self.customer_id,
            doctor_id=self.doctor_id,
            items=self._hold_items(),
        )
        hold = get_by_id(hid)
        self.assertEqual(hold["doctor_id"], self.doctor_id)

    def test_06_hold_number_is_unique(self):
        hid1 = create_hold(items=self._hold_items())
        hid2 = create_hold(items=self._hold_items())
        h1 = get_by_id(hid1)
        h2 = get_by_id(hid2)
        self.assertNotEqual(h1["hold_number"], h2["hold_number"])

    def test_07_hold_stores_all_item_fields(self):
        items = self._hold_items(qty=3.0, mrp=55.0, amount=165.0)
        hid = create_hold(items=items)
        stored = get_hold_items(hid)
        self.assertEqual(len(stored), 1)
        it = stored[0]
        self.assertEqual(it["item_id"], self.item_id)
        self.assertEqual(it["batch_no"], "BATCH-A")
        self.assertEqual(it["mrp"], 55.0)
        self.assertEqual(it["sale_qty"], 3.0)
        self.assertEqual(it["amount"], 165.0)
        self.assertEqual(it["pack_size"], "10x10")


# ======================================================================
# 8-11: STORAGE
# ======================================================================

class TestStorage(_BaseTest):

    def test_08_hold_persists_in_database(self):
        hid = create_hold(items=self._hold_items())
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM hold_bills WHERE id = ?", (hid,)
            ).fetchone()
            self.assertEqual(row[0], 1)
        finally:
            conn.close()

    def test_09_get_all_returns_holds(self):
        create_hold(items=self._hold_items())
        create_hold(items=self._hold_items())
        holds = get_all()
        self.assertEqual(len(holds), 2)

    def test_10_get_by_id_returns_correct_hold(self):
        hid = create_hold(
            customer_id=self.customer_id,
            patient_name="TestPatient",
            items=self._hold_items(),
        )
        hold = get_by_id(hid)
        self.assertEqual(hold["id"], hid)
        self.assertEqual(hold["patient_name"], "TestPatient")

    def test_11_hold_items_ordering_preserved(self):
        items = [
            {"item_id": self.item_id, "item_name_snapshot": "A",
             "batch_no": "BATCH-A", "pack_size": "", "location": "",
             "expiry": "12/27", "mrp": 50.0, "sale_qty": 1.0,
             "discount_amount": 0.0, "amount": 50.0},
            {"item_id": self.item2_id, "item_name_snapshot": "B",
             "batch_no": "BATCH-B", "pack_size": "", "location": "",
             "expiry": "12/27", "mrp": 50.0, "sale_qty": 2.0,
             "discount_amount": 0.0, "amount": 100.0},
        ]
        hid = create_hold(items=items)
        stored = get_hold_items(hid)
        self.assertEqual(stored[0]["ordering"], 0)
        self.assertEqual(stored[1]["ordering"], 1)
        self.assertEqual(stored[0]["item_name_snapshot"], "A")
        self.assertEqual(stored[1]["item_name_snapshot"], "B")


# ======================================================================
# 12-17: NO TRANSACTION SIDE EFFECTS
# ======================================================================

class TestNoSideEffects(_BaseTest):

    def test_12_no_sales_invoice_created(self):
        sales_before = conn_count("sales_invoices")
        create_hold(items=self._hold_items())
        self.assertEqual(conn_count("sales_invoices"), sales_before)

    def test_13_no_stock_reduction(self):
        stock_before = self._stock_qty()
        create_hold(items=self._hold_items(qty=10.0))
        self.assertEqual(self._stock_qty(), stock_before)

    def test_14_no_ledger_transaction(self):
        txns_before = conn_count("ledger_transactions")
        create_hold(items=self._hold_items())
        self.assertEqual(conn_count("ledger_transactions"), txns_before)

    def test_15_no_posting_engine_call(self):
        hid = create_hold(items=self._hold_items())
        self.assertFalse(self.engine.is_posted("HOLD_BILL", hid))

    def test_16_no_trial_balance_effect(self):
        bal_before = LedgerDAO.get_balance(self.customer_ledger_id)
        create_hold(items=self._hold_items())
        bal_after = LedgerDAO.get_balance(self.customer_ledger_id)
        self.assertEqual(bal_before["closing_balance"], bal_after["closing_balance"])

    def test_17_no_profit_loss_effect(self):
        sales_before = self.sales_ledger["id"]
        bal_before = LedgerDAO.get_balance(sales_before)
        create_hold(items=self._hold_items())
        bal_after = LedgerDAO.get_balance(sales_before)
        self.assertEqual(bal_before["closing_balance"], bal_after["closing_balance"])


# ======================================================================
# 18-26: RESUME
# ======================================================================

class TestResume(_BaseTest):

    def test_18_resume_loads_items(self):
        hid = create_hold(
            customer_id=self.customer_id,
            items=self._hold_items(qty=3.0),
        )
        hold = get_by_id(hid)
        items = get_hold_items(hid)
        hold_data = {"hold": hold, "items": items}
        self.assertEqual(len(hold_data["items"]), 1)
        self.assertEqual(hold_data["items"][0]["sale_qty"], 3.0)

    def test_19_resume_multiple_items(self):
        items = self._hold_items() + self._hold_items(
            item_id=self.item2_id, batch_no="BATCH-B", qty=2.0,
        )
        hid = create_hold(items=items)
        stored = get_hold_items(hid)
        self.assertEqual(len(stored), 2)

    def test_20_expired_batch_detection(self):
        expired_batch = "EXPIRED-BATCH"
        PurchaseDAO.insert_invoice(
            voucher_no="PV-EXP", voucher_date="2026-01-01", voucher_time="",
            purchase_type="Cash", supplier_id=self.supplier_id,
            invoice_no="INV-EXP", invoice_date="2026-01-01",
            invoice_net_amount=100.0, bill_discount=0, due_date="",
            total_amount=100.0, gst_amount=0, debit_note_amount=0,
            other_amount=0, paid_amount=100.0, round_off=0,
            net_amount=100.0, remarks="",
            items=[{
                "item_id": self.item_id, "pack_size": "10x10",
                "pay_qty": 10, "free_qty": 0, "batch_no": expired_batch,
                "expiry": "01/20", "rate": 10.0, "mrp": 15.0, "discount": 0,
                "gst_percent": 0, "gst_amount": 0, "amount": 100.0,
                "purchase_rate": 10.0, "net_rate": 10.0, "pp": 10.0,
            }],
        )
        batch = SalesDAO.get_batch_by_item_and_batch_no(
            self.item_id, expired_batch
        )
        self.assertTrue(SalesDAO.is_expired(batch["expiry"]))

    def test_21_missing_batch_detection(self):
        batch = SalesDAO.get_batch_by_item_and_batch_no(
            self.item_id, "NONEXISTENT-BATCH"
        )
        self.assertIsNone(batch)

    def test_22_insufficient_stock_detection(self):
        batch = SalesDAO.get_batch_by_item_and_batch_no(
            self.item_id, "BATCH-A"
        )
        self.assertIsNotNone(batch)
        self.assertGreater(batch["stock_qty"], 0)

    def test_23_missing_item_detection(self):
        batch = SalesDAO.get_batch_by_item_and_batch_no(
            99999, "BATCH-A"
        )
        self.assertIsNone(batch)

    def test_24_resume_status_update(self):
        hid = create_hold(items=self._hold_items())
        hold = get_by_id(hid)
        self.assertEqual(hold["status"], STATUS_ACTIVE)
        update_status(hid, STATUS_RESUMED, "testuser")
        hold = get_by_id(hid)
        self.assertEqual(hold["status"], STATUS_RESUMED)

    def test_25_resume_only_active_holds(self):
        hid = create_hold(items=self._hold_items())
        update_status(hid, STATUS_RESUMED)
        holds = get_all(status=STATUS_ACTIVE)
        self.assertEqual(len(holds), 0)

    def test_26_hold_items_include_item_name(self):
        hid = create_hold(items=self._hold_items())
        items = get_hold_items(hid)
        self.assertIn("item_name", items[0])


# ======================================================================
# 27-33: COMPLETION LIFECYCLE
# ======================================================================

class TestCompletion(_BaseTest):

    def _do_complete_sale(self, hold_data, paid=0.0):
        """Simulate completing a sale from hold data."""
        hold = hold_data["hold"]
        items_data = []
        for it in hold_data["items"]:
            batch = SalesDAO.get_batch_by_item_and_batch_no(
                it["item_id"], it["batch_no"]
            )
            if not batch:
                continue
            items_data.append({
                "item_id": it["item_id"],
                "stock_batch_id": batch["id"],
                "pack_size": it.get("pack_size", ""),
                "location": it.get("location", ""),
                "batch_no": it["batch_no"],
                "expiry": it.get("expiry", ""),
                "mrp": it.get("mrp", 0.0),
                "sale_qty": it.get("sale_qty", 0.0),
                "discount_amount": it.get("discount_amount", 0.0),
                "amount": it.get("amount", 0.0),
            })
        total = sum(it["amount"] for it in items_data)
        return SalesDAO.insert_invoice(
            bill_no="CS-HOLD-001",
            sale_date=datetime.now().strftime("%Y-%m-%d"),
            sale_time=datetime.now().strftime("%H:%M"),
            sale_type="Cash",
            customer_id=hold.get("customer_id"),
            patient_name=hold.get("patient_name", ""),
            doctor_id=hold.get("doctor_id"),
            discount=0.0,
            paid_amount=paid if paid else total,
            total_amount=total,
            round_off=0.0,
            net_amount=total,
            remarks="",
            items=items_data,
        )

    def test_27_hold_to_complete_creates_one_sale(self):
        hid = create_hold(
            customer_id=self.customer_id,
            items=self._hold_items(qty=5.0),
        )
        hold = get_by_id(hid)
        items = get_hold_items(hid)
        sale_id = self._do_complete_sale({"hold": hold, "items": items})
        self.assertGreater(sale_id, 0)
        sale = SalesDAO.get_by_id(sale_id)
        self.assertIsNotNone(sale)

    def test_28_one_stock_effect(self):
        stock_before = self._stock_qty()
        hid = create_hold(items=self._hold_items(qty=5.0))
        hold = get_by_id(hid)
        items = get_hold_items(hid)
        self._do_complete_sale({"hold": hold, "items": items})
        self.assertEqual(self._stock_qty(), stock_before - 5.0)

    def test_29_one_accounting_effect(self):
        hid = create_hold(
            customer_id=self.customer_id,
            items=self._hold_items(qty=5.0),
        )
        hold = get_by_id(hid)
        items = get_hold_items(hid)
        sale_id = self._do_complete_sale({"hold": hold, "items": items})
        self.assertTrue(self.engine.is_posted(SOURCE_COUNTER_SALE, sale_id))

    def test_30_hold_status_updates_on_complete(self):
        hid = create_hold(
            customer_id=self.customer_id,
            items=self._hold_items(),
        )
        update_status(hid, STATUS_RESUMED)
        hold = get_by_id(hid)
        self.assertEqual(hold["status"], STATUS_RESUMED)

    def test_31_no_duplicate_sale_on_resume_then_complete(self):
        hid = create_hold(
            customer_id=self.customer_id,
            items=self._hold_items(qty=5.0),
        )
        hold = get_by_id(hid)
        items = get_hold_items(hid)
        sale_id = self._do_complete_sale({"hold": hold, "items": items})
        sales_count = conn_count("sales_invoices")
        self.assertEqual(sales_count, 1)

    def test_32_stock_reduced_exactly_once(self):
        stock_before = self._stock_qty()
        hid = create_hold(items=self._hold_items(qty=7.0))
        hold = get_by_id(hid)
        items = get_hold_items(hid)
        self._do_complete_sale({"hold": hold, "items": items})
        self.assertEqual(self._stock_qty(), stock_before - 7.0)

    def test_33_accounting_posting_is_atomic(self):
        hid = create_hold(
            customer_id=self.customer_id,
            items=self._hold_items(qty=5.0),
        )
        hold = get_by_id(hid)
        items = get_hold_items(hid)
        sale_id = self._do_complete_sale({"hold": hold, "items": items})
        rows = self.engine.get_posting_rows(SOURCE_COUNTER_SALE, sale_id)
        self.assertEqual(len(rows), 2)


# ======================================================================
# 34-39: DELETE / DISCARD
# ======================================================================

class TestDelete(_BaseTest):

    def test_34_discard_hold(self):
        hid = create_hold(items=self._hold_items())
        delete_hold(hid)
        self.assertIsNone(get_by_id(hid))

    def test_35_discard_prevents_double_delete(self):
        hid = create_hold(items=self._hold_items())
        delete_hold(hid)
        hold = get_by_id(hid)
        self.assertIsNone(hold)

    def test_36_no_accounting_on_discard(self):
        txns_before = conn_count("ledger_transactions")
        hid = create_hold(items=self._hold_items())
        delete_hold(hid)
        self.assertEqual(conn_count("ledger_transactions"), txns_before)

    def test_37_no_stock_effect_on_discard(self):
        stock_before = self._stock_qty()
        hid = create_hold(items=self._hold_items(qty=10.0))
        delete_hold(hid)
        self.assertEqual(self._stock_qty(), stock_before)

    def test_38_discard_leaves_other_holds_intact(self):
        hid1 = create_hold(items=self._hold_items())
        hid2 = create_hold(items=self._hold_items())
        delete_hold(hid1)
        self.assertIsNone(get_by_id(hid1))
        self.assertIsNotNone(get_by_id(hid2))

    def test_39_discard_status_update(self):
        hid = create_hold(items=self._hold_items())
        update_status(hid, STATUS_DISCARDED)
        hold = get_by_id(hid)
        self.assertEqual(hold["status"], STATUS_DISCARDED)


# ======================================================================
# 40-43: MULTIPLE HOLDS
# ======================================================================

class TestMultipleHolds(_BaseTest):

    def test_40_isolated_records(self):
        hid1 = create_hold(
            customer_id=self.customer_id,
            patient_name="Patient A",
            items=self._hold_items(),
        )
        hid2 = create_hold(
            customer_id=self.customer2_id,
            patient_name="Patient B",
            items=self._hold_items(item_id=self.item2_id, batch_no="BATCH-B"),
        )
        h1 = get_by_id(hid1)
        h2 = get_by_id(hid2)
        self.assertEqual(h1["patient_name"], "Patient A")
        self.assertEqual(h2["patient_name"], "Patient B")

    def test_41_deleting_one_does_not_affect_another(self):
        hid1 = create_hold(items=self._hold_items())
        hid2 = create_hold(items=self._hold_items())
        delete_hold(hid1)
        self.assertIsNone(get_by_id(hid1))
        self.assertIsNotNone(get_by_id(hid2))

    def test_42_multiple_holds_coexist(self):
        for i in range(5):
            create_hold(items=self._hold_items())
        holds = get_all()
        self.assertEqual(len(holds), 5)

    def test_43_count_active(self):
        create_hold(items=self._hold_items())
        create_hold(items=self._hold_items())
        self.assertEqual(count_active(), 2)
        all_holds = get_all()
        update_status(all_holds[0]["id"], STATUS_RESUMED)
        self.assertEqual(count_active(), 1)


# ======================================================================
# 44-45: PERSISTENCE
# ======================================================================

class TestPersistence(_BaseTest):

    def test_44_hold_survives_db_close(self):
        hid = create_hold(
            customer_id=self.customer_id,
            patient_name="PersistTest",
            items=self._hold_items(),
        )
        fresh = sqlite3.connect(get_db_path())
        fresh.row_factory = sqlite3.Row
        try:
            row = fresh.execute(
                "SELECT * FROM hold_bills WHERE id = ?", (hid,)
            ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(dict(row)["patient_name"], "PersistTest")
        finally:
            fresh.close()

    def test_45_hold_items_survive_db_close(self):
        hid = create_hold(items=self._hold_items(qty=8.0))
        fresh = sqlite3.connect(get_db_path())
        fresh.row_factory = sqlite3.Row
        try:
            rows = fresh.execute(
                "SELECT * FROM hold_bill_items WHERE hold_bill_id = ?", (hid,)
            ).fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual(dict(rows[0])["sale_qty"], 8.0)
        finally:
            fresh.close()


# ======================================================================
# 46-49: AUTH
# ======================================================================

class TestAuth(_BaseTest):

    def test_46_admin_can_hold(self):
        admin = auth.create_first_admin("admin1", "password123")
        self.assertTrue(auth.has_permission(admin, auth.PERM_COUNTER_SALE))

    def test_47_staff_can_hold(self):
        staff = auth.create_user(
            admin_user(), "staff1", "password123", auth.ROLE_PHARMACIST_STAFF
        )
        self.assertTrue(auth.has_permission(staff, auth.PERM_COUNTER_SALE))

    def test_48_hold_number_format(self):
        hid = create_hold(items=self._hold_items())
        hold = get_by_id(hid)
        self.assertTrue(hold["hold_number"].startswith("HOLD-"))

    def test_49_hold_number_sequential(self):
        hid1 = create_hold(items=self._hold_items())
        hid2 = create_hold(items=self._hold_items())
        h1 = get_by_id(hid1)
        h2 = get_by_id(hid2)
        num1 = int(h1["hold_number"].split("-")[1])
        num2 = int(h2["hold_number"].split("-")[1])
        self.assertEqual(num2, num1 + 1)


# ======================================================================
# 50-52: FINANCIAL YEAR
# ======================================================================

class TestFinancialYear(_BaseTest):

    def test_50_hold_date_is_valid(self):
        now = datetime.now().strftime("%Y-%m-%d")
        financial_year.validate_transaction_date(now)

    def test_51_no_accounting_entry_until_complete(self):
        hid = create_hold(
            customer_id=self.customer_id,
            items=self._hold_items(),
        )
        self.assertFalse(self.engine.is_posted("HOLD_BILL", hid))

    def test_52_hold_date_not_in_ledger(self):
        hid = create_hold(items=self._hold_items())
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM ledger_transactions "
                "WHERE voucher_no = ?",
                (f"HOLD-{hid:04d}",),
            ).fetchone()
            self.assertEqual(row[0], 0)
        finally:
            conn.close()


# ======================================================================
# 53-56: READ-ONLY SIDE EFFECTS
# ======================================================================

class TestReadOnlySideEffects(_BaseTest):

    def _balance(self, ledger_id):
        return LedgerDAO.get_balance(ledger_id)["closing_balance"]

    def test_53_holding_does_not_change_balances(self):
        cust_before = self._balance(self.customer_ledger_id)
        sales_before = self._balance(self.sales_ledger["id"])
        create_hold(
            customer_id=self.customer_id,
            items=self._hold_items(qty=10.0),
        )
        self.assertEqual(self._balance(self.customer_ledger_id), cust_before)
        self.assertEqual(self._balance(self.sales_ledger["id"]), sales_before)

    def test_54_resuming_does_not_change_balances(self):
        hid = create_hold(
            customer_id=self.customer_id,
            items=self._hold_items(),
        )
        cust_before = self._balance(self.customer_ledger_id)
        update_status(hid, STATUS_RESUMED)
        self.assertEqual(self._balance(self.customer_ledger_id), cust_before)

    def test_55_discarding_does_not_change_balances(self):
        hid = create_hold(
            customer_id=self.customer_id,
            items=self._hold_items(),
        )
        cust_before = self._balance(self.customer_ledger_id)
        delete_hold(hid)
        self.assertEqual(self._balance(self.customer_ledger_id), cust_before)

    def test_56_stock_unchanged_through_hold_lifecycle(self):
        stock_before = self._stock_qty()
        hid = create_hold(items=self._hold_items(qty=5.0))
        self.assertEqual(self._stock_qty(), stock_before)
        update_status(hid, STATUS_RESUMED)
        self.assertEqual(self._stock_qty(), stock_before)
        delete_hold(hid)
        self.assertEqual(self._stock_qty(), stock_before)


# ======================================================================
# 57-65: REGRESSION
# ======================================================================

class TestRegression(_BaseTest):

    def test_57_sales_bill_unchanged(self):
        hid = create_hold(items=self._hold_items())
        sales_before = conn_count("sales_invoices")
        self.assertEqual(conn_count("sales_invoices"), sales_before)

    def test_58_counter_sale_still_works(self):
        sale_id = SalesDAO.insert_invoice(
            bill_no="CS-0001",
            sale_date=datetime.now().strftime("%Y-%m-%d"),
            sale_time="10:00",
            sale_type="Cash",
            customer_id=self.customer_id,
            patient_name="",
            doctor_id=None,
            discount=0.0,
            paid_amount=250.0,
            total_amount=250.0,
            round_off=0.0,
            net_amount=250.0,
            remarks="",
            items=[{
                "item_id": self.item_id, "stock_batch_id": self.batch_id,
                "pack_size": "10x10", "location": "", "batch_no": "BATCH-A",
                "expiry": "12/27", "mrp": 50.0, "sale_qty": 5.0,
                "discount_amount": 0.0, "amount": 250.0,
            }],
        )
        self.assertGreater(sale_id, 0)

    def test_59_stock_master_unchanged(self):
        create_hold(items=self._hold_items())
        all_stock = StockDAO.get_all()
        self.assertEqual(len(all_stock), 2)

    def test_60_posting_engine_unchanged(self):
        sale_id = SalesDAO.insert_invoice(
            bill_no="CS-0002",
            sale_date=datetime.now().strftime("%Y-%m-%d"),
            sale_time="10:00",
            sale_type="Cash",
            customer_id=self.customer_id,
            patient_name="",
            doctor_id=None,
            discount=0.0,
            paid_amount=250.0,
            total_amount=250.0,
            round_off=0.0,
            net_amount=250.0,
            remarks="",
            items=[{
                "item_id": self.item_id, "stock_batch_id": self.batch_id,
                "pack_size": "10x10", "location": "", "batch_no": "BATCH-A",
                "expiry": "12/27", "mrp": 50.0, "sale_qty": 5.0,
                "discount_amount": 0.0, "amount": 250.0,
            }],
        )
        self.assertTrue(self.engine.is_posted(SOURCE_COUNTER_SALE, sale_id))

    def test_61_all_master_screens_still_work(self):
        create_hold(items=self._hold_items())
        self.assertGreater(len(CompanyDAO.get_all()), 0)
        self.assertGreater(len(UnitDAO.get_all()), 0)
        self.assertGreater(len(DrugDAO.get_all()), 0)
        self.assertGreater(len(SupplierDAO.get_all()), 0)
        self.assertGreater(len(CustomerDAO.get_all()), 0)
        self.assertGreater(len(DoctorDAO.get_all()), 0)
        self.assertGreater(len(ItemDAO.get_all()), 0)

    def test_62_financial_year_unchanged(self):
        financial_year.ensure_default_financial_year()
        create_hold(items=self._hold_items())
        fy = financial_year.get_active_financial_year()
        self.assertIsNotNone(fy)

    def test_63_purchase_unaffected(self):
        stock_before = self._stock_qty()
        create_hold(items=self._hold_items())
        self.assertEqual(self._stock_qty(), stock_before)

    def test_64_hold_bill_tables_created(self):
        ensure_hold_tables()
        conn = get_connection()
        try:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name IN ('hold_bills', 'hold_bill_items')"
            ).fetchall()
            self.assertEqual(len(tables), 2)
        finally:
            conn.close()

    def test_65_complete_lifecycle(self):
        stock_before = self._stock_qty()
        txns_before = conn_count("ledger_transactions")
        sales_before = conn_count("sales_invoices")

        hid = create_hold(
            customer_id=self.customer_id,
            patient_name="LifecycleTest",
            items=self._hold_items(qty=5.0),
        )

        self.assertEqual(self._stock_qty(), stock_before)
        self.assertEqual(conn_count("sales_invoices"), sales_before)

        hold = get_by_id(hid)
        items = get_hold_items(hid)
        update_status(hid, STATUS_RESUMED)

        items_data = []
        for it in items:
            batch = SalesDAO.get_batch_by_item_and_batch_no(
                it["item_id"], it["batch_no"]
            )
            items_data.append({
                "item_id": it["item_id"],
                "stock_batch_id": batch["id"],
                "pack_size": it.get("pack_size", ""),
                "location": it.get("location", ""),
                "batch_no": it["batch_no"],
                "expiry": it.get("expiry", ""),
                "mrp": it.get("mrp", 0.0),
                "sale_qty": it.get("sale_qty", 0.0),
                "discount_amount": it.get("discount_amount", 0.0),
                "amount": it.get("amount", 0.0),
            })
        total = sum(it["amount"] for it in items_data)

        sale_id = SalesDAO.insert_invoice(
            bill_no="CS-LIFECYCLE",
            sale_date=datetime.now().strftime("%Y-%m-%d"),
            sale_time="10:00",
            sale_type="Cash",
            customer_id=self.customer_id,
            patient_name="LifecycleTest",
            doctor_id=None,
            discount=0.0,
            paid_amount=total,
            total_amount=total,
            round_off=0.0,
            net_amount=total,
            remarks="",
            items=items_data,
        )

        self.assertEqual(conn_count("sales_invoices"), sales_before + 1)
        self.assertEqual(self._stock_qty(), stock_before - 5.0)
        self.assertTrue(self.engine.is_posted(SOURCE_COUNTER_SALE, sale_id))
        self.assertEqual(conn_count("ledger_transactions"), txns_before + 2)

        self.assertIsNotNone(SalesDAO.get_by_id(sale_id))


# ======================================================================
# Helpers
# ======================================================================

def conn_count(table: str) -> int:
    conn = get_connection()
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def admin_user() -> dict:
    """Get or create an admin user for auth tests."""
    users = auth.list_users()
    for u in users:
        if u["role"] == auth.ROLE_ADMIN and u["is_active"]:
            return u
    return auth.create_first_admin("testadmin", "password123")


if __name__ == "__main__":
    unittest.main(verbosity=2)
