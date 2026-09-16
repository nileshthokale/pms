import os
import sqlite3
import sys
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database.connection import get_connection, init_database
from database.account_roles import (
    ACCOUNT_ROLES,
    REQUIRED_ROLES,
    ROLE_CASH,
    ROLE_BANK,
    ROLE_SALES,
    ROLE_PURCHASE,
    ROLE_SALES_RETURN,
    ROLE_PURCHASE_RETURN,
    ensure_system_ledgers,
    get_role_status,
    all_roles_configured,
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

try:
    from PySide6.QtWidgets import QApplication
    from screens.account_roles import AccountRolesPage

    HAS_PYSIDE6 = True
    _PYSIDE_SKIP_REASON = ""
except ImportError as _exc:  # pragma: no cover - test environment without GUI
    HAS_PYSIDE6 = False
    _PYSIDE_SKIP_REASON = f"PySide6 not available ({_exc})"


_TABLES = [
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
    """Shared setUp — clean DB state before every test."""

    _DB_PATH = os.path.join(os.path.dirname(__file__), "_test_roles.db")

    @classmethod
    def setUpClass(cls):
        if os.path.exists(cls._DB_PATH):
            os.remove(cls._DB_PATH)
        os.environ["PHARMACY_DB"] = cls._DB_PATH
        init_database()

    def setUp(self):
        conn = get_connection()
        try:
            for tbl in _TABLES:
                conn.execute(f"DELETE FROM {tbl}")
            conn.commit()
        finally:
            conn.close()
        ensure_system_ledgers()


# ======================================================================
# 1-16: System role foundation
# ======================================================================

class TestSystemRoles(_BaseTest):

    def test_01_fresh_database_creates_required_system_ledgers(self):
        result = ensure_system_ledgers()
        self.assertEqual(result["status"], "success")
        # setUp already called ensure_system_ledgers, so all are already configured
        self.assertEqual(sorted(result["already_configured"]), sorted(REQUIRED_ROLES))
        self.assertEqual(len(LedgerDAO.get_system_ledgers()), len(REQUIRED_ROLES))
        for role, cfg in ACCOUNT_ROLES.items():
            led = LedgerDAO.get_by_system_role(role)
            self.assertIsNotNone(led)
            self.assertEqual(led["ledger_name"], cfg["name"])

    def test_02_initialization_twice_creates_no_duplicates(self):
        ensure_system_ledgers()
        first_count = len(LedgerDAO.get_all_ledgers())
        self.assertEqual(first_count, len(REQUIRED_ROLES))

        result = ensure_system_ledgers()
        self.assertEqual(result["created"], [])
        self.assertEqual(sorted(result["already_configured"]),
                         sorted(REQUIRED_ROLES))
        self.assertEqual(len(LedgerDAO.get_all_ledgers()), first_count)

    def test_03_get_by_system_role_works(self):
        ensure_system_ledgers()
        cash = LedgerDAO.get_by_system_role(ROLE_CASH)
        self.assertIsNotNone(cash)
        self.assertEqual(cash["ledger_name"], "Cash")
        self.assertEqual(cash["system_role"], ROLE_CASH)

        self.assertIsNone(LedgerDAO.get_by_system_role("NOT_A_ROLE"))
        # Every required role resolves
        for role in REQUIRED_ROLES:
            self.assertIsNotNone(LedgerDAO.get_by_system_role(role))

    def test_04_system_role_uniqueness(self):
        ensure_system_ledgers()
        extra = LedgerDAO.insert_ledger("Extra Ledger")

        # Role already held by another ledger -> refused by DAO guard
        with self.assertRaises(ValueError):
            LedgerDAO.set_system_role(extra, ROLE_CASH)

        # Role already held -> refused by the partial unique index (raw SQL)
        conn = get_connection()
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "UPDATE account_ledgers SET system_role = ? WHERE id = ?",
                    (ROLE_CASH, extra),
                )
            conn.rollback()
        finally:
            conn.close()

        # A free role can be assigned and cleared again
        LedgerDAO.set_system_role(extra, "MISC")
        self.assertEqual(LedgerDAO.get_by_system_role("MISC")["id"], extra)
        LedgerDAO.set_system_role(extra, None)
        self.assertIsNone(LedgerDAO.get_by_system_role("MISC"))

        # Non-existent ledger -> refused
        with self.assertRaises(ValueError):
            LedgerDAO.set_system_role(999999, ROLE_CASH)

    def test_05_existing_user_ledgers_remain_unchanged(self):
        uid = LedgerDAO.insert_ledger(
            "My User Ledger", account_group="My Group",
            opening_balance=123.45, opening_balance_type="Credit",
            discount=5.0, credit_limit=1000.0, credit_period=30,
            address="1 Road", city="City", state="ST",
            contact_person="P", contact_no="123", tax_no="TAX1",
        )
        before = LedgerDAO.get_ledger_by_id(uid)

        ensure_system_ledgers()

        after = LedgerDAO.get_ledger_by_id(uid)
        for field in (
            "ledger_name", "account_group", "opening_balance",
            "opening_balance_type", "discount", "credit_limit",
            "credit_period", "address", "city", "state",
            "contact_person", "contact_no", "tax_no",
        ):
            self.assertEqual(after[field], before[field],
                             f"field changed: {field}")
        self.assertIsNone(after["system_role"])
        # 6 system + 1 user ledger, nothing else
        self.assertEqual(len(LedgerDAO.get_all_ledgers()),
                         len(REQUIRED_ROLES) + 1)

    def test_06_existing_customer_mappings_remain_unchanged(self):
        cid = CustomerDAO.insert("Cust Map Check", opening_balance=50.0)
        lid_before = CustomerDAO.get_ledger_id(cid)
        self.assertIsNotNone(lid_before)

        ensure_system_ledgers()

        self.assertEqual(CustomerDAO.get_ledger_id(cid), lid_before)
        led = LedgerDAO.get_ledger_by_id(lid_before)
        self.assertEqual(led["ledger_name"], "Customer - Cust Map Check")
        self.assertIsNone(led["system_role"])
        self.assertEqual(CustomerDAO.get_customer_by_ledger(lid_before)["id"], cid)

    def test_07_existing_supplier_mappings_remain_unchanged(self):
        sid = SupplierDAO.insert("Sup Map Check", opening_balance=200.0)
        lid_before = SupplierDAO.get_ledger_id(sid)
        self.assertIsNotNone(lid_before)

        ensure_system_ledgers()

        self.assertEqual(SupplierDAO.get_ledger_id(sid), lid_before)
        led = LedgerDAO.get_ledger_by_id(lid_before)
        self.assertEqual(led["ledger_name"], "Supplier - Sup Map Check")
        self.assertIsNone(led["system_role"])
        self.assertEqual(SupplierDAO.get_supplier_by_ledger(lid_before)["id"], sid)

    def test_08_existing_ledger_transactions_remain_unchanged(self):
        cid = CustomerDAO.insert("Txn Cust")
        lid = CustomerDAO.get_ledger_id(cid)
        tid = LedgerDAO.add_transaction({
            "ledger_id": lid, "transaction_date": "2026-09-15",
            "transaction_time": "10:00", "voucher_type": "MANUAL",
            "voucher_no": "M-0001", "reference_type": "",
            "reference_id": None, "description": "before",
            "debit": 100.0, "credit": 0.0,
        })

        ensure_system_ledgers()

        txns = LedgerDAO.get_transactions(lid)
        self.assertEqual(len(txns), 1)
        self.assertEqual(txns[0]["id"], tid)
        self.assertEqual(txns[0]["debit"], 100.0)
        self.assertEqual(txns[0]["description"], "before")

    def test_09_missing_required_system_account_is_initialized(self):
        # setUp already called ensure_system_ledgers, so CASH is configured.
        # Verify it's properly configured.
        cash = LedgerDAO.get_by_system_role(ROLE_CASH)
        self.assertIsNotNone(cash)
        self.assertIn("Cash", cash["ledger_name"])

        result = ensure_system_ledgers()
        self.assertIn(ROLE_CASH, result["already_configured"])
        self.assertTrue(all_roles_configured())

    def test_10_already_configured_system_account_is_reused(self):
        # setUp already called ensure_system_ledgers, so Bank is configured.
        # Verify it's properly configured.
        bank = LedgerDAO.get_by_system_role(ROLE_BANK)
        self.assertIsNotNone(bank)
        self.assertIn("Bank", bank["ledger_name"])

        result = ensure_system_ledgers()
        self.assertIn(ROLE_BANK, result["already_configured"])
        # Exactly one ledger named Bank exists (no duplicate created)
        conn = get_connection()
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM account_ledgers WHERE ledger_name = 'Bank'"
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(count, 1)

    def test_11_cash_role_exists(self):
        ensure_system_ledgers()
        led = LedgerDAO.get_by_system_role(ROLE_CASH)
        self.assertIsNotNone(led)
        self.assertEqual(led["ledger_name"], "Cash")
        self.assertEqual(led["account_group"], "Cash-in-Hand")

    def test_12_bank_role_exists(self):
        ensure_system_ledgers()
        led = LedgerDAO.get_by_system_role(ROLE_BANK)
        self.assertIsNotNone(led)
        self.assertEqual(led["ledger_name"], "Bank")
        self.assertEqual(led["account_group"], "Bank Accounts")

    def test_13_sales_role_exists(self):
        ensure_system_ledgers()
        led = LedgerDAO.get_by_system_role(ROLE_SALES)
        self.assertIsNotNone(led)
        self.assertEqual(led["ledger_name"], "Sales")
        self.assertEqual(led["account_group"], "Sales Accounts")

    def test_14_purchase_role_exists(self):
        ensure_system_ledgers()
        led = LedgerDAO.get_by_system_role(ROLE_PURCHASE)
        self.assertIsNotNone(led)
        self.assertEqual(led["ledger_name"], "Purchase")
        self.assertEqual(led["account_group"], "Purchase Accounts")

    def test_15_sales_return_role_exists(self):
        ensure_system_ledgers()
        led = LedgerDAO.get_by_system_role(ROLE_SALES_RETURN)
        self.assertIsNotNone(led)
        self.assertEqual(led["ledger_name"], "Sales Return")
        self.assertEqual(led["account_group"], "Sales Accounts")

    def test_16_purchase_return_role_exists(self):
        ensure_system_ledgers()
        led = LedgerDAO.get_by_system_role(ROLE_PURCHASE_RETURN)
        self.assertIsNotNone(led)
        self.assertEqual(led["ledger_name"], "Purchase Return")
        self.assertEqual(led["account_group"], "Purchase Accounts")
        self.assertTrue(all_roles_configured())
        self.assertEqual(
            len(get_role_status()), len(REQUIRED_ROLES)
        )


# ======================================================================
# 17-19: Account Roles screen (skipped when PySide6 is unavailable)
# ======================================================================

@unittest.skipUnless(HAS_PYSIDE6, _PYSIDE_SKIP_REASON)
class TestAccountRolesScreen(_BaseTest):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.app = QApplication.instance() or QApplication([])

    def test_17_screen_opens(self):
        page = AccountRolesPage()
        self.assertIsNotNone(page)
        self.assertEqual(page._table.columnCount(), 4)
        self.assertEqual(
            page._table.horizontalHeaderItem(0).text(), "Role"
        )

    def test_18_screen_shows_correct_status(self):
        ensure_system_ledgers()
        page = AccountRolesPage()
        self.assertEqual(page._table.rowCount(), len(REQUIRED_ROLES))

        statuses = {
            page._table.item(i, 3).text()
            for i in range(page._table.rowCount())
        }
        self.assertEqual(statuses, {"Configured"})

        roles = {
            page._table.item(i, 0).text()
            for i in range(page._table.rowCount())
        }
        self.assertEqual(roles, set(REQUIRED_ROLES))

        names = {
            page._table.item(i, 1).text()
            for i in range(page._table.rowCount())
        }
        for cfg in ACCOUNT_ROLES.values():
            self.assertIn(cfg["name"], names)

    def test_19_refresh_works(self):
        ensure_system_ledgers()
        page = AccountRolesPage()
        before = {
            page._table.item(i, 3).text()
            for i in range(page._table.rowCount())
        }
        self.assertEqual(before, {"Configured"})

        # Clear all roles behind the screen's back
        conn = get_connection()
        try:
            conn.execute("UPDATE account_ledgers SET system_role = NULL")
            conn.commit()
        finally:
            conn.close()

        page._on_refresh()
        missing = {
            page._table.item(i, 3).text()
            for i in range(page._table.rowCount())
        }
        self.assertEqual(missing, {"Missing"})

        # Re-initialize and refresh again -> back to Configured
        ensure_system_ledgers()
        page._on_refresh()
        after = {
            page._table.item(i, 3).text()
            for i in range(page._table.rowCount())
        }
        self.assertEqual(after, {"Configured"})


# ======================================================================
# 20-29: Regression — existing modules still work
# ======================================================================

class TestExistingModulesStillWork(_BaseTest):

    def _seed_item(self) -> int:
        return ItemDAO.insert("TestItem")

    def _make_purchase(self, supplier_id: int, item_id: int,
                       qty: float = 10.0, rate: float = 5.0) -> int:
        amount = round(qty * rate, 2)
        return PurchaseDAO.insert_invoice(
            voucher_no="PV-0001", voucher_date="2026-09-15",
            voucher_time="10:00", purchase_type="Credit",
            supplier_id=supplier_id, invoice_no="INV-1",
            invoice_date="2026-09-15", invoice_net_amount=amount,
            bill_discount=0.0, due_date="", total_amount=amount,
            gst_amount=0.0, debit_note_amount=0.0, other_amount=0.0,
            paid_amount=0.0, round_off=0.0, net_amount=amount, remarks="",
            items=[{
                "item_id": item_id, "batch_no": "B1", "pay_qty": qty,
                "free_qty": 0.0, "rate": rate, "mrp": rate * 1.5,
                "discount": 0.0, "gst_percent": 0.0, "gst_amount": 0.0,
                "amount": amount, "purchase_rate": rate, "net_rate": rate,
                "pp": amount, "expiry": "12/27", "pack_size": "10",
            }],
        )

    def test_20_account_ledger_still_works(self):
        lid = LedgerDAO.insert_ledger(
            "Test Ledger", account_group="My Group", opening_balance=100.0,
        )
        got = LedgerDAO.get_ledger_by_id(lid)
        self.assertEqual(got["ledger_name"], "Test Ledger")
        self.assertIsNone(got["system_role"])

        bal = LedgerDAO.get_balance(lid)
        self.assertEqual(bal["closing_balance"], 100.0)
        self.assertEqual(bal["closing_balance_type"], "Debit")

        LedgerDAO.add_transaction({
            "ledger_id": lid, "transaction_date": "2026-09-15",
            "voucher_type": "MANUAL", "voucher_no": "M-0001",
            "debit": 50.0, "credit": 0.0,
        })
        bal2 = LedgerDAO.get_balance(lid)
        self.assertEqual(bal2["total_debit"], 150.0)

        self.assertTrue(
            any(l["id"] == lid for l in LedgerDAO.search_ledgers("Test"))
        )

    def test_21_customer_receipt_still_works(self):
        ensure_system_ledgers()
        cid = CustomerDAO.insert("Receipt Cust")
        rid = CustomerReceiptDAO.insert_receipt({
            "receipt_date": "2026-09-15", "receipt_time": "10:00",
            "customer_id": cid, "receipt_mode": "UPI",
            "amount": 250.0, "reference_no": "REF1", "remarks": "",
        })
        rec = CustomerReceiptDAO.get_by_id(rid)
        self.assertEqual(rec["amount"], 250.0)
        self.assertEqual(rec["receipt_mode"], "UPI")
        self.assertEqual(CustomerReceiptDAO.get_customer_balance(cid), -250.0)

    def test_22_supplier_payment_still_works(self):
        sid = SupplierDAO.insert("Payment Sup")
        pid = SupplierPaymentDAO.insert_payment({
            "payment_date": "2026-09-15", "payment_time": "10:00",
            "supplier_id": sid, "payment_mode": "Cheque",
            "amount": 400.0, "reference_no": "CHQ1", "remarks": "",
        })
        pay = SupplierPaymentDAO.get_by_id(pid)
        self.assertEqual(pay["amount"], 400.0)
        self.assertEqual(pay["payment_mode"], "Cheque")
        self.assertEqual(SupplierPaymentDAO.get_supplier_balance(sid), -400.0)

    def test_23_purchase_still_works(self):
        sid = SupplierDAO.insert("Purch Sup")
        item_id = self._seed_item()
        inv_id = self._make_purchase(sid, item_id, qty=10, rate=5.0)

        inv = PurchaseDAO.get_by_id(inv_id)
        self.assertEqual(inv["net_amount"], 50.0)
        self.assertEqual(inv["supplier_name"], "Purch Sup")
        items = PurchaseDAO.get_invoice_items(inv_id)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["amount"], 50.0)

        batches = PurchaseDAO.get_stock_batches_for_item(item_id)
        self.assertEqual(len(batches), 1)
        self.assertEqual(batches[0]["stock_qty"], 10.0)
        self.assertEqual(SupplierPaymentDAO.get_supplier_balance(sid), 50.0)

    def test_24_counter_sale_still_works(self):
        ensure_system_ledgers()
        sid = SupplierDAO.insert("Sale Stock Sup")
        item_id = self._seed_item()
        self._make_purchase(sid, item_id, qty=10, rate=5.0)
        batch = PurchaseDAO.get_stock_batches_for_item(item_id)[0]
        cust_id = CustomerDAO.insert("Sale Cust")

        amount = 30.0  # 3 units @ MRP 10
        sale_id = SalesDAO.insert_invoice(
            bill_no="CS-0001", sale_date="2026-09-15", sale_time="11:00",
            sale_type="Cash", customer_id=cust_id, patient_name="",
            doctor_id=None, discount=0.0, paid_amount=amount,
            total_amount=amount, round_off=0.0, net_amount=amount,
            remarks="",
            items=[{
                "item_id": item_id, "stock_batch_id": batch["id"],
                "pack_size": "10", "location": "", "batch_no": "B1",
                "expiry": "12/27", "mrp": 10.0, "sale_qty": 3.0,
                "discount_amount": 0.0, "amount": amount,
            }],
        )
        sale = SalesDAO.get_by_id(sale_id)
        self.assertEqual(sale["net_amount"], 30.0)

        batches = PurchaseDAO.get_stock_batches_for_item(item_id)
        self.assertEqual(batches[0]["stock_qty"], 7.0)
        self.assertEqual(CustomerReceiptDAO.get_customer_balance(cust_id), 30.0)

    def test_25_credit_note_still_works(self):
        sid = SupplierDAO.insert("CN Stock Sup")
        item_id = self._seed_item()
        self._make_purchase(sid, item_id, qty=10, rate=5.0)
        batch = PurchaseDAO.get_stock_batches_for_item(item_id)[0]
        cust_id = CustomerDAO.insert("CN Cust")

        cn_id = CreditNoteDAO.insert_credit_note(
            {
                "voucher_date": "2026-09-15", "cn_date": "2026-09-15",
                "cn_type": "Customer", "customer_id": cust_id,
                "total_amount": 20.0, "ledger_amount": 20.0, "remarks": "",
            },
            [{
                "item_id": item_id, "stock_batch_id": batch["id"],
                "batch_no": "B1", "expiry": "12/27", "pack_size": "10",
                "rate": 10.0, "mrp": 10.0, "return_qty": 2.0,
                "less_amount": 0.0, "amount": 20.0,
                "return_reason": "damaged", "price_factor": 1.0,
            }],
        )
        cn = CreditNoteDAO.get_by_id(cn_id)
        self.assertEqual(cn["total_amount"], 20.0)
        items = CreditNoteDAO.get_invoice_items(cn_id)
        self.assertEqual(len(items), 1)

        batches = PurchaseDAO.get_stock_batches_for_item(item_id)
        self.assertEqual(batches[0]["stock_qty"], 12.0)  # 10 + 2 restored

    def test_26_debit_note_still_works(self):
        sid = SupplierDAO.insert("DN Stock Sup")
        item_id = self._seed_item()
        self._make_purchase(sid, item_id, qty=10, rate=5.0)
        batch = PurchaseDAO.get_stock_batches_for_item(item_id)[0]

        dn_id = DebitNoteDAO.insert_debit_note(
            {
                "voucher_date": "2026-09-15", "voucher_time": "11:00",
                "dn_date": "2026-09-15", "dn_type": "Supplier",
                "supplier_id": sid, "total_amount": 20.0,
                "ledger_amount": 20.0, "remarks": "",
            },
            [{
                "item_id": item_id, "stock_batch_id": batch["id"],
                "batch_no": "B1", "expiry": "12/27", "pack_size": "10",
                "rate": 10.0, "mrp": 10.0, "return_qty": 2.0,
                "less_amount": 0.0, "amount": 20.0,
                "return_reason": "expired", "price_factor": 1.0,
            }],
        )
        dn = DebitNoteDAO.get_by_id(dn_id)
        self.assertEqual(dn["total_amount"], 20.0)

        batches = PurchaseDAO.get_stock_batches_for_item(item_id)
        self.assertEqual(batches[0]["stock_qty"], 8.0)  # 10 - 2 returned
        self.assertEqual(SupplierPaymentDAO.get_supplier_balance(sid), 30.0)

    def test_27_journal_entry_still_works(self):
        la = LedgerDAO.insert_ledger("JV Ledger A")
        lb = LedgerDAO.insert_ledger("JV Ledger B")
        eid = JournalDAO.insert_entry(
            {"entry_date": "2026-09-15", "entry_time": "10:00",
             "narration": "test"},
            [
                {"ledger_id": la, "description": "d1",
                 "debit": 100.0, "credit": 0.0},
                {"ledger_id": lb, "description": "d2",
                 "debit": 0.0, "credit": 100.0},
            ],
        )
        entry = JournalDAO.get_by_id(eid)
        self.assertEqual(entry["total_debit"], 100.0)
        self.assertEqual(entry["total_credit"], 100.0)
        self.assertEqual(len(JournalDAO.get_items(eid)), 2)

    def test_28_stock_master_still_works(self):
        sid = SupplierDAO.insert("Stock Sup")
        item_id = self._seed_item()
        self._make_purchase(sid, item_id, qty=10, rate=5.0)

        all_batches = StockDAO.get_all()
        self.assertEqual(len(all_batches), 1)
        self.assertEqual(all_batches[0]["item_name"], "TestItem")
        self.assertEqual(all_batches[0]["stock_qty"], 10.0)

        found = StockDAO.search(item_name="TestItem")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["batch_no"], "B1")

    def test_29_master_screens_data_layer_still_works(self):
        # Every master module's data layer used by the master screens
        company_id = CompanyDAO.insert("TestCo", "TC")
        self.assertEqual(CompanyDAO.get_by_id(company_id)["company_name"], "TestCo")

        unit_id = UnitDAO.insert("Pcs")
        self.assertEqual(UnitDAO.get_by_id(unit_id)["unit_name"], "Pcs")

        drug_id = DrugDAO.insert("Paracetamol")
        self.assertEqual(DrugDAO.get_by_id(drug_id)["drug_name"], "Paracetamol")

        cust_id = CustomerDAO.insert("Master Cust")
        self.assertEqual(CustomerDAO.get_by_id(cust_id)["customer_name"], "Master Cust")
        self.assertIsNotNone(CustomerDAO.get_ledger_id(cust_id))

        sup_id = SupplierDAO.insert("Master Sup")
        self.assertEqual(SupplierDAO.get_by_id(sup_id)["supplier_name"], "Master Sup")
        self.assertIsNotNone(SupplierDAO.get_ledger_id(sup_id))

        doc_id = DoctorDAO.insert("Dr. Smith")
        self.assertEqual(DoctorDAO.get_by_id(doc_id)["doctor_name"], "Dr. Smith")

        item_id = ItemDAO.insert("MasterItem", unit_id=unit_id,
                                 company_id=company_id)
        self.assertEqual(ItemDAO.get_by_id(item_id)["item_name"], "MasterItem")

        # Masters + system ledgers coexist without interference
        ensure_system_ledgers()
        self.assertEqual(CustomerDAO.get_ledger_id(cust_id),
                         CustomerDAO.get_ledger_id(cust_id))
        self.assertTrue(all_roles_configured())


if __name__ == "__main__":
    unittest.main(verbosity=2)
