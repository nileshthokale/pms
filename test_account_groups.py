"""Phase 4A/4B — Account Group Classification tests.

58 tests covering:

  1-9:    AccountGroupDAO CRUD
  10-16:  Migration and data preservation
  17-22:  System-role classification
  23:     Unmapped legacy group (custom text, not Sundry Debtors/Creditors)
  24-25:  Migration idempotency and transactionality
  26-27:  Account Ledger create/edit with structured group
  28-37:  Regression — all modules
  38-41:  Party classification — Sundry Debtors/Creditors mapping
  42-45:  Party ledger validation — customer/supplier group and normal balance
  46-49:  Party ledger identity preservation
  50-51:  Party migration idempotency and custom classification preservation
  52-58:  Regression — Trial Balance, Account Ledger, all source types
"""

import os
import sys
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database.connection import get_connection, init_database
from database.account_group_dao import AccountGroupDAO
from database.account_roles import (
    ROLE_CASH,
    ROLE_BANK,
    ROLE_SALES,
    ROLE_PURCHASE,
    ROLE_SALES_RETURN,
    ROLE_PURCHASE_RETURN,
    STMT_ASSET,
    STMT_LIABILITY,
    STMT_EQUITY,
    STMT_INCOME,
    STMT_EXPENSE,
    NORMAL_DEBIT,
    NORMAL_CREDIT,
    ensure_system_ledgers,
    ensure_account_groups,
    migrate_legacy_ledger_groups,
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
    "ledger_transactions", "account_ledgers", "account_groups",
    "customer_receipts", "supplier_payments",
    "debit_note_items", "debit_notes",
    "credit_note_items", "credit_notes",
    "sales_invoice_items", "sales_invoices",
    "purchase_invoice_items", "purchase_invoices",
    "stock_batches", "item_ingredients", "items",
    "doctors", "customers", "suppliers", "drugs", "units", "companies",
]


class _BaseTest(unittest.TestCase):
    """Fresh DB per module; clean tables per case."""

    _DB_PATH = os.path.join(os.path.dirname(__file__), "_test_account_groups.db")

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


# ======================================================================
# Tests 1-9: AccountGroupDAO CRUD
# ======================================================================

class TestGroupCRUD(_BaseTest):

    def test_01_create_root_group(self):
        gid = AccountGroupDAO.insert(
            "Current Assets", statement_type=STMT_ASSET,
            normal_balance=NORMAL_DEBIT,
        )
        g = AccountGroupDAO.get_by_id(gid)
        self.assertIsNotNone(g)
        self.assertEqual(g["group_name"], "Current Assets")
        self.assertIsNone(g["parent_group_id"])
        self.assertEqual(g["statement_type"], STMT_ASSET)
        self.assertEqual(g["normal_balance"], NORMAL_DEBIT)
        self.assertEqual(g["is_system"], 0)

    def test_02_create_child_group(self):
        parent_id = AccountGroupDAO.insert(
            "Assets", statement_type=STMT_ASSET,
            normal_balance=NORMAL_DEBIT, is_system=True,
        )
        child_id = AccountGroupDAO.insert(
            "Current Assets", parent_group_id=parent_id,
            statement_type=STMT_ASSET, normal_balance=NORMAL_DEBIT,
        )
        child = AccountGroupDAO.get_by_id(child_id)
        self.assertEqual(child["parent_group_id"], parent_id)

        children = AccountGroupDAO.get_children(parent_id)
        self.assertEqual(len(children), 1)
        self.assertEqual(children[0]["id"], child_id)

    def test_03_parent_relationship_works(self):
        root = AccountGroupDAO.insert(
            "Assets", statement_type=STMT_ASSET, normal_balance=NORMAL_DEBIT,
        )
        c1 = AccountGroupDAO.insert(
            "Current Assets", parent_group_id=root,
            statement_type=STMT_ASSET, normal_balance=NORMAL_DEBIT,
        )
        c2 = AccountGroupDAO.insert(
            "Fixed Assets", parent_group_id=root,
            statement_type=STMT_ASSET, normal_balance=NORMAL_DEBIT,
        )
        children = AccountGroupDAO.get_children(root)
        self.assertEqual(len(children), 2)
        child_ids = {c["id"] for c in children}
        self.assertIn(c1, child_ids)
        self.assertIn(c2, child_ids)

    def test_04_duplicate_name_rejected(self):
        AccountGroupDAO.insert("Assets", statement_type=STMT_ASSET)
        with self.assertRaises(ValueError) as ctx:
            AccountGroupDAO.insert("Assets", statement_type=STMT_ASSET)
        self.assertIn("already exists", str(ctx.exception))

    def test_05_circular_parent_rejected(self):
        root = AccountGroupDAO.insert(
            "Assets", statement_type=STMT_ASSET, normal_balance=NORMAL_DEBIT,
        )
        child = AccountGroupDAO.insert(
            "Current Assets", parent_group_id=root,
            statement_type=STMT_ASSET, normal_balance=NORMAL_DEBIT,
        )
        with self.assertRaises(ValueError) as ctx:
            AccountGroupDAO.update(
                root, "Assets", parent_group_id=child,
                statement_type=STMT_ASSET, normal_balance=NORMAL_DEBIT,
            )
        self.assertIn("circular", str(ctx.exception).lower())

    def test_06_edit_group(self):
        gid = AccountGroupDAO.insert(
            "Old Name", statement_type=STMT_ASSET, normal_balance=NORMAL_DEBIT,
        )
        AccountGroupDAO.update(
            gid, "New Name", statement_type=STMT_LIABILITY,
            normal_balance=NORMAL_CREDIT,
        )
        g = AccountGroupDAO.get_by_id(gid)
        self.assertEqual(g["group_name"], "New Name")
        self.assertEqual(g["statement_type"], STMT_LIABILITY)
        self.assertEqual(g["normal_balance"], NORMAL_CREDIT)

    def test_07_search(self):
        AccountGroupDAO.insert(
            "Cash and Bank", statement_type=STMT_ASSET,
        )
        AccountGroupDAO.insert(
            "Sales Income", statement_type=STMT_INCOME,
        )
        all_groups = AccountGroupDAO.get_all()
        results = [g for g in all_groups if "cash" in g["group_name"].lower()]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["group_name"], "Cash and Bank")

    def test_08_delete_unused_group(self):
        gid = AccountGroupDAO.insert(
            "Temp Group", statement_type=STMT_EXPENSE,
        )
        ok, _ = AccountGroupDAO.can_delete(gid)
        self.assertTrue(ok)
        AccountGroupDAO.delete(gid)
        self.assertIsNone(AccountGroupDAO.get_by_id(gid))

    def test_09_prevent_deletion_used_by_ledger(self):
        gid = AccountGroupDAO.insert(
            "Protected Group", statement_type=STMT_ASSET,
        )
        LedgerDAO.insert_ledger(
            ledger_name="Test Ledger For Group",
            account_group_id=gid,
        )
        ok, reason = AccountGroupDAO.can_delete(gid)
        self.assertFalse(ok)
        self.assertIn("used by", reason.lower())

        with self.assertRaises(ValueError):
            AccountGroupDAO.delete(gid)


# ======================================================================
# Tests 10-16: Migration and data preservation
# ======================================================================

class TestMigration(_BaseTest):

    def test_10_structured_ledger_mapping_works(self):
        result = ensure_account_groups()
        self.assertEqual(result["status"], "success")
        self.assertGreater(len(result["created"]), 0)

        cash_group = AccountGroupDAO.get_by_name("Current Assets")
        self.assertIsNotNone(cash_group)

    def test_11_existing_account_group_text_preserved(self):
        lid = LedgerDAO.insert_ledger(
            ledger_name="My Custom Ledger",
            account_group="Custom Group XYZ",
        )
        ledger = LedgerDAO.get_ledger_by_id(lid)
        self.assertEqual(ledger["account_group"], "Custom Group XYZ")
        self.assertIsNone(ledger.get("account_group_id"))

    def test_12_existing_ledgers_survive_migration(self):
        lid = LedgerDAO.insert_ledger(
            ledger_name="Pre-Migration Ledger",
            account_group="Cash-in-Hand",
            opening_balance=1000.0,
        )
        ensure_account_groups()
        migrate_legacy_ledger_groups()

        ledger = LedgerDAO.get_ledger_by_id(lid)
        self.assertIsNotNone(ledger)
        self.assertEqual(ledger["account_group"], "Cash-in-Hand")
        self.assertIsNotNone(ledger["account_group_id"])

    def test_13_existing_customer_mappings_survive(self):
        cust_id = CustomerDAO.insert("TestCust_Mig")
        ledger_id = CustomerDAO.get_ledger_id(cust_id)
        self.assertIsNotNone(ledger_id)

        ensure_account_groups()
        migrate_legacy_ledger_groups()

        ledger = LedgerDAO.get_ledger_by_id(ledger_id)
        self.assertIsNotNone(ledger)

    def test_14_existing_supplier_mappings_survive(self):
        sup_id = SupplierDAO.insert("TestSup_Mig")
        ledger_id = SupplierDAO.get_ledger_id(sup_id)
        self.assertIsNotNone(ledger_id)

        ensure_account_groups()
        migrate_legacy_ledger_groups()

        ledger = LedgerDAO.get_ledger_by_id(ledger_id)
        self.assertIsNotNone(ledger)

    def test_15_existing_transactions_survive(self):
        ensure_system_ledgers()
        cash = LedgerDAO.get_by_system_role(ROLE_CASH)
        self.assertIsNotNone(cash)

        LedgerDAO.add_transaction({
            "ledger_id": cash["id"],
            "transaction_date": "2026-01-01",
            "voucher_type": "Test",
            "voucher_no": "T-001",
            "debit": 500.0,
            "credit": 0.0,
        })

        ensure_account_groups()
        migrate_legacy_ledger_groups()

        txns = LedgerDAO.get_transactions(cash["id"])
        self.assertEqual(len(txns), 1)
        self.assertEqual(txns[0]["debit"], 500.0)

    def test_16_existing_system_roles_survive(self):
        ensure_system_ledgers()
        cash_before = LedgerDAO.get_by_system_role(ROLE_CASH)
        self.assertIsNotNone(cash_before)

        ensure_account_groups()
        migrate_legacy_ledger_groups()

        cash_after = LedgerDAO.get_by_system_role(ROLE_CASH)
        self.assertIsNotNone(cash_after)
        self.assertEqual(cash_before["id"], cash_after["id"])


# ======================================================================
# Tests 17-22: System-role classification
# ======================================================================

class TestSystemRoleClassification(_BaseTest):

    def setUp(self):
        super().setUp()
        ensure_system_ledgers()
        ensure_account_groups()
        migrate_legacy_ledger_groups()

    def _get_group_name(self, role):
        ledger = LedgerDAO.get_by_system_role(role)
        if not ledger:
            return None
        gid = ledger.get("account_group_id")
        if gid:
            g = AccountGroupDAO.get_by_id(gid)
            return g["group_name"] if g else None
        return ledger.get("account_group")

    def test_17_cash_classification(self):
        self.assertEqual(self._get_group_name(ROLE_CASH), "Current Assets")

    def test_18_bank_classification(self):
        self.assertEqual(self._get_group_name(ROLE_BANK), "Current Assets")

    def test_19_sales_classification(self):
        self.assertEqual(self._get_group_name(ROLE_SALES), "Sales")

    def test_20_purchase_classification(self):
        self.assertEqual(self._get_group_name(ROLE_PURCHASE), "Purchase-related")

    def test_21_sales_return_classification(self):
        self.assertEqual(self._get_group_name(ROLE_SALES_RETURN), "Sales")

    def test_22_purchase_return_classification(self):
        self.assertEqual(self._get_group_name(ROLE_PURCHASE_RETURN), "Purchase-related")


# ======================================================================
# Test 23: Unmapped legacy group (custom text, not Sundry Debtors/Creditors)
# ======================================================================

class TestUnmappedLegacy(_BaseTest):

    def test_23_unmapped_legacy_group_remains_unresolved(self):
        lid = LedgerDAO.insert_ledger(
            ledger_name="Custom Group Ledger",
            account_group="Loans & Advances",
        )
        ensure_account_groups()
        migrate_legacy_ledger_groups()

        ledger = LedgerDAO.get_ledger_by_id(lid)
        self.assertEqual(ledger["account_group"], "Loans & Advances")
        self.assertIsNone(ledger["account_group_id"])


# ======================================================================
# Tests 24-25: Migration idempotency and transactionality
# ======================================================================

class TestMigrationProperties(_BaseTest):

    def test_24_migration_idempotent(self):
        ensure_account_groups()
        r1 = migrate_legacy_ledger_groups()

        # Run again — should be no-op
        r2 = migrate_legacy_ledger_groups()
        self.assertEqual(r2["migrated"], 0)
        self.assertEqual(r2["already_migrated"], r1["migrated"])

    def test_25_migration_preserves_data(self):
        ensure_system_ledgers()
        lid = LedgerDAO.insert_ledger(
            ledger_name="Pre-Migration Ledger 2",
            account_group="Cash-in-Hand",
            opening_balance=2500.0,
        )
        ensure_account_groups()
        migrate_legacy_ledger_groups()

        ledger = LedgerDAO.get_ledger_by_id(lid)
        self.assertEqual(ledger["account_group"], "Cash-in-Hand")
        self.assertIsNotNone(ledger["account_group_id"])
        self.assertEqual(ledger["opening_balance"], 2500.0)


# ======================================================================
# Tests 26-27: Account Ledger create/edit with structured group
# ======================================================================

class TestLedgerWithStructuredGroup(_BaseTest):

    def setUp(self):
        super().setUp()
        ensure_account_groups()

    def test_26_create_ledger_with_structured_group(self):
        asset_group = AccountGroupDAO.get_by_name("Current Assets")
        self.assertIsNotNone(asset_group)

        lid = LedgerDAO.insert_ledger(
            ledger_name="New Cash Ledger",
            account_group="Cash-in-Hand",
            account_group_id=asset_group["id"],
        )
        ledger = LedgerDAO.get_ledger_by_id(lid)
        self.assertEqual(ledger["account_group_id"], asset_group["id"])
        self.assertEqual(ledger["account_group"], "Cash-in-Hand")

    def test_27_edit_ledger_structured_group(self):
        asset_group = AccountGroupDAO.get_by_name("Current Assets")
        exp_group = AccountGroupDAO.get_by_name("Operating Expenses")
        self.assertIsNotNone(asset_group)
        self.assertIsNotNone(exp_group)

        lid = LedgerDAO.insert_ledger(
            ledger_name="Movable Ledger",
            account_group_id=asset_group["id"],
        )
        LedgerDAO.update_ledger(
            lid, "Movable Ledger", account_group_id=exp_group["id"],
        )
        ledger = LedgerDAO.get_ledger_by_id(lid)
        self.assertEqual(ledger["account_group_id"], exp_group["id"])


# ======================================================================
# Tests 28-37: Regression — all existing functionality still works
# ======================================================================

class TestRegression(_BaseTest):

    def setUp(self):
        super().setUp()
        ensure_system_ledgers()
        ensure_account_groups()
        migrate_legacy_ledger_groups()

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

        self.customer_ledger_id = CustomerDAO.get_ledger_id(self.customer_id)
        self.supplier_ledger_id = SupplierDAO.get_ledger_id(self.supplier_id)

        # Seed stock
        PurchaseDAO.insert_invoice(
            voucher_no="PV-REG", voucher_date="2026-03-01", voucher_time="",
            purchase_type="Cash", supplier_id=self.supplier_id,
            invoice_no="INV-REG", invoice_date="2026-03-01",
            invoice_net_amount=4000.0, bill_discount=0,
            due_date="", total_amount=4000.0, gst_amount=0,
            debit_note_amount=0, other_amount=0,
            paid_amount=4000.0, round_off=0,
            net_amount=4000.0, remarks="",
            items=[{
                "item_id": self.item_id, "pack_size": "10x10",
                "pay_qty": 100.0, "free_qty": 0, "batch_no": "BATCH-REG",
                "expiry": "12/28", "rate": 40.0, "mrp": 50.0,
                "discount": 0, "gst_percent": 0, "gst_amount": 0,
                "amount": 4000.0, "purchase_rate": 40.0,
                "net_rate": 40.0, "pp": 40.0,
            }],
        )
        batches = StockDAO.get_stock_batches_for_item(self.item_id)
        self.batch_id = batches[0]["id"]

    def test_28_trial_balance_still_works(self):
        from database.trial_balance_dao import TrialBalanceDAO
        data = TrialBalanceDAO.get_trial_balance()
        self.assertIsInstance(data, dict)
        self.assertIn("rows", data)
        self.assertIn("totals", data)

    def test_29_customer_receipt_still_works(self):
        rid = CustomerReceiptDAO.insert_receipt({
            "receipt_date": "2026-03-01", "receipt_time": "",
            "customer_id": self.customer_id, "receipt_mode": "Cash",
            "amount": 100.0, "reference_no": "", "remarks": "",
        })
        self.assertGreater(rid, 0)

    def test_30_supplier_payment_still_works(self):
        pid = SupplierPaymentDAO.insert_payment({
            "payment_date": "2026-03-01", "payment_time": "",
            "supplier_id": self.supplier_id, "payment_mode": "Cash",
            "amount": 100.0, "reference_no": "", "remarks": "",
        })
        self.assertGreater(pid, 0)

    def test_31_counter_sale_still_works(self):
        bill_no = SalesDAO.generate_next_bill_no()
        sid = SalesDAO.insert_invoice(
            bill_no=bill_no, sale_date="2026-03-01", sale_time="",
            sale_type="Cash", customer_id=None, patient_name="",
            doctor_id=None, discount=0, paid_amount=100.0,
            total_amount=100.0, round_off=0, net_amount=100.0,
            remarks="",
            items=[{
                "item_id": self.item_id, "stock_batch_id": self.batch_id,
                "pack_size": "10x10", "location": "", "batch_no": "BATCH-REG",
                "expiry": "12/28", "mrp": 50.0, "sale_qty": 2.0,
                "discount_amount": 0, "amount": 100.0,
            }],
        )
        self.assertGreater(sid, 0)

    def test_32_purchase_still_works(self):
        pid = PurchaseDAO.insert_invoice(
            voucher_no="PV-NEW", voucher_date="2026-03-01", voucher_time="",
            purchase_type="Credit", supplier_id=self.supplier_id,
            invoice_no="INV-NEW", invoice_date="2026-03-01",
            invoice_net_amount=200.0, bill_discount=0,
            due_date="", total_amount=200.0, gst_amount=0,
            debit_note_amount=0, other_amount=0,
            paid_amount=0, round_off=0,
            net_amount=200.0, remarks="",
            items=[{
                "item_id": self.item_id, "pack_size": "10x10",
                "pay_qty": 5, "free_qty": 0, "batch_no": "BATCH-REG",
                "expiry": "12/28", "rate": 40.0, "mrp": 50.0,
                "discount": 0, "gst_percent": 0, "gst_amount": 0,
                "amount": 200.0, "purchase_rate": 40.0,
                "net_rate": 40.0, "pp": 40.0,
            }],
        )
        self.assertGreater(pid, 0)

    def test_33_credit_note_still_works(self):
        cn_id = CreditNoteDAO.insert_credit_note(
            {
                "voucher_date": "2026-03-01", "cn_date": "2026-03-01",
                "cn_type": "Customer", "customer_id": self.customer_id,
                "total_amount": 100.0, "ledger_amount": 100.0,
                "remarks": "",
            },
            [{
                "item_id": self.item_id, "stock_batch_id": self.batch_id,
                "batch_no": "BATCH-REG", "expiry": "12/28",
                "pack_size": "10x10", "rate": 40.0, "mrp": 50.0,
                "return_qty": 2.5, "less_amount": 0,
                "amount": 100.0, "return_reason": "Damaged",
                "price_factor": 1.0,
            }],
        )
        self.assertGreater(cn_id, 0)

    def test_34_debit_note_still_works(self):
        dn_id = DebitNoteDAO.insert_debit_note(
            {
                "voucher_date": "2026-03-01", "voucher_time": "",
                "dn_date": "2026-03-01", "dn_type": "Supplier",
                "supplier_id": self.supplier_id,
                "total_amount": 80.0, "ledger_amount": 80.0,
                "remarks": "",
            },
            [{
                "item_id": self.item_id, "stock_batch_id": self.batch_id,
                "batch_no": "BATCH-REG", "expiry": "12/28",
                "pack_size": "10x10", "rate": 40.0, "mrp": 50.0,
                "return_qty": 2.0, "less_amount": 0,
                "amount": 80.0, "return_reason": "Expired",
                "price_factor": 1.0,
            }],
        )
        self.assertGreater(dn_id, 0)

    def test_35_journal_entry_still_works(self):
        je_id = JournalDAO.insert_entry(
            {"entry_date": "2026-03-01", "narration": "Regression test"},
            [
                {"ledger_id": self.customer_ledger_id, "description": "", "debit": 100.0, "credit": 0.0},
                {"ledger_id": self.supplier_ledger_id, "description": "", "debit": 0.0, "credit": 100.0},
            ],
        )
        self.assertGreater(je_id, 0)

    def test_36_stock_master_still_works(self):
        batches = StockDAO.get_stock_batches_for_item(self.item_id)
        self.assertGreater(len(batches), 0)
        self.assertEqual(batches[0]["stock_qty"], 100.0)

    def test_37_account_groups_get_tree(self):
        tree = AccountGroupDAO.get_tree()
        self.assertGreater(len(tree), 0)

        # Verify root groups have children
        root_names = {g["group_name"] for g in tree}
        self.assertIn("Assets", root_names)
        self.assertIn("Liabilities", root_names)

        # Find Assets root
        assets = next(g for g in tree if g["group_name"] == "Assets")
        self.assertGreater(len(assets["children"]), 0)


# ======================================================================
# Tests 38-41: Party classification — Sundry Debtors/Creditors mapping
# ======================================================================

class TestPartyClassification(_BaseTest):

    def setUp(self):
        super().setUp()
        ensure_system_ledgers()
        ensure_account_groups()

    def test_38_sundry_debtors_maps_to_current_assets(self):
        lid = LedgerDAO.insert_ledger(
            ledger_name="SD Ledger",
            account_group="Sundry Debtors",
        )
        migrate_legacy_ledger_groups()
        ledger = LedgerDAO.get_ledger_by_id(lid)
        self.assertIsNotNone(ledger["account_group_id"])
        g = AccountGroupDAO.get_by_id(ledger["account_group_id"])
        self.assertEqual(g["group_name"], "Current Assets")
        self.assertEqual(g["statement_type"], STMT_ASSET)

    def test_39_sundry_creditors_maps_to_current_liabilities(self):
        lid = LedgerDAO.insert_ledger(
            ledger_name="SC Ledger",
            account_group="Sundry Creditors",
        )
        migrate_legacy_ledger_groups()
        ledger = LedgerDAO.get_ledger_by_id(lid)
        self.assertIsNotNone(ledger["account_group_id"])
        g = AccountGroupDAO.get_by_id(ledger["account_group_id"])
        self.assertEqual(g["group_name"], "Current Liabilities")
        self.assertEqual(g["statement_type"], STMT_LIABILITY)

    def test_40_customer_ledger_gets_sundry_debtors_group(self):
        cust_id = CustomerDAO.insert("PartyCust")
        ledger_id = CustomerDAO.get_ledger_id(cust_id)
        ledger = LedgerDAO.get_ledger_by_id(ledger_id)
        self.assertEqual(ledger["account_group"], "Sundry Debtors")

        migrate_legacy_ledger_groups()
        ledger = LedgerDAO.get_ledger_by_id(ledger_id)
        self.assertIsNotNone(ledger["account_group_id"])
        g = AccountGroupDAO.get_by_id(ledger["account_group_id"])
        self.assertEqual(g["group_name"], "Current Assets")

    def test_41_supplier_ledger_gets_sundry_creditors_group(self):
        sup_id = SupplierDAO.insert("PartySup")
        ledger_id = SupplierDAO.get_ledger_id(sup_id)
        ledger = LedgerDAO.get_ledger_by_id(ledger_id)
        self.assertEqual(ledger["account_group"], "Sundry Creditors")

        migrate_legacy_ledger_groups()
        ledger = LedgerDAO.get_ledger_by_id(ledger_id)
        self.assertIsNotNone(ledger["account_group_id"])
        g = AccountGroupDAO.get_by_id(ledger["account_group_id"])
        self.assertEqual(g["group_name"], "Current Liabilities")


# ======================================================================
# Tests 42-45: Party ledger validation — normal balance
# ======================================================================

class TestPartyNormalBalance(_BaseTest):

    def setUp(self):
        super().setUp()
        ensure_system_ledgers()
        ensure_account_groups()

    def _get_group_info(self, ledger_id):
        ledger = LedgerDAO.get_ledger_by_id(ledger_id)
        gid = ledger.get("account_group_id")
        if gid:
            g = AccountGroupDAO.get_by_id(gid)
            return g
        return None

    def test_42_customer_normal_balance_is_debit(self):
        cust_id = CustomerDAO.insert("NormCust")
        ledger_id = CustomerDAO.get_ledger_id(cust_id)
        migrate_legacy_ledger_groups()
        g = self._get_group_info(ledger_id)
        self.assertIsNotNone(g)
        self.assertEqual(g["normal_balance"], NORMAL_DEBIT)

    def test_43_supplier_normal_balance_is_credit(self):
        sup_id = SupplierDAO.insert("NormSup")
        ledger_id = SupplierDAO.get_ledger_id(sup_id)
        migrate_legacy_ledger_groups()
        g = self._get_group_info(ledger_id)
        self.assertIsNotNone(g)
        self.assertEqual(g["normal_balance"], NORMAL_CREDIT)

    def test_44_customer_statement_type_is_asset(self):
        cust_id = CustomerDAO.insert("StmtCust")
        ledger_id = CustomerDAO.get_ledger_id(cust_id)
        migrate_legacy_ledger_groups()
        g = self._get_group_info(ledger_id)
        self.assertIsNotNone(g)
        self.assertEqual(g["statement_type"], STMT_ASSET)

    def test_45_supplier_statement_type_is_liability(self):
        sup_id = SupplierDAO.insert("StmtSup")
        ledger_id = SupplierDAO.get_ledger_id(sup_id)
        migrate_legacy_ledger_groups()
        g = self._get_group_info(ledger_id)
        self.assertIsNotNone(g)
        self.assertEqual(g["statement_type"], STMT_LIABILITY)


# ======================================================================
# Tests 46-49: Party ledger identity preservation
# ======================================================================

class TestPartyIdentityPreservation(_BaseTest):

    def setUp(self):
        super().setUp()
        ensure_system_ledgers()
        ensure_account_groups()

    def test_46_customer_ledger_id_unchanged_after_migration(self):
        cust_id = CustomerDAO.insert("IDCust")
        ledger_before = CustomerDAO.get_ledger_id(cust_id)
        migrate_legacy_ledger_groups()
        ledger_after = CustomerDAO.get_ledger_id(cust_id)
        self.assertEqual(ledger_before, ledger_after)

    def test_47_supplier_ledger_id_unchanged_after_migration(self):
        sup_id = SupplierDAO.insert("IDSup")
        ledger_before = SupplierDAO.get_ledger_id(sup_id)
        migrate_legacy_ledger_groups()
        ledger_after = SupplierDAO.get_ledger_id(sup_id)
        self.assertEqual(ledger_before, ledger_after)

    def test_48_customer_transactions_unchanged(self):
        cust_id = CustomerDAO.insert("TxnCust")
        ledger_id = CustomerDAO.get_ledger_id(cust_id)
        LedgerDAO.add_transaction({
            "ledger_id": ledger_id,
            "transaction_date": "2026-04-01",
            "voucher_type": "Test",
            "voucher_no": "T-PT-01",
            "debit": 250.0,
            "credit": 0.0,
        })
        migrate_legacy_ledger_groups()
        txns = LedgerDAO.get_transactions(ledger_id)
        self.assertEqual(len(txns), 1)
        self.assertEqual(txns[0]["debit"], 250.0)

    def test_49_supplier_transactions_unchanged(self):
        sup_id = SupplierDAO.insert("TxnSup")
        ledger_id = SupplierDAO.get_ledger_id(sup_id)
        LedgerDAO.add_transaction({
            "ledger_id": ledger_id,
            "transaction_date": "2026-04-01",
            "voucher_type": "Test",
            "voucher_no": "T-PT-02",
            "debit": 0.0,
            "credit": 350.0,
        })
        migrate_legacy_ledger_groups()
        txns = LedgerDAO.get_transactions(ledger_id)
        self.assertEqual(len(txns), 1)
        self.assertEqual(txns[0]["credit"], 350.0)


# ======================================================================
# Tests 50-51: Party migration idempotency and custom preservation
# ======================================================================

class TestPartyMigrationProperties(_BaseTest):

    def setUp(self):
        super().setUp()
        ensure_system_ledgers()
        ensure_account_groups()

    def test_50_party_migration_idempotent(self):
        cust_id = CustomerDAO.insert("IdemCust")
        ledger_id = CustomerDAO.get_ledger_id(cust_id)
        migrate_legacy_ledger_groups()
        g1 = LedgerDAO.get_ledger_by_id(ledger_id)["account_group_id"]

        migrate_legacy_ledger_groups()
        g2 = LedgerDAO.get_ledger_by_id(ledger_id)["account_group_id"]
        self.assertEqual(g1, g2)

    def test_51_custom_classifications_not_overwritten(self):
        custom_gid = AccountGroupDAO.insert(
            "My Custom Group", statement_type=STMT_EXPENSE,
            normal_balance=NORMAL_DEBIT,
        )
        lid = LedgerDAO.insert_ledger(
            ledger_name="Already Classified",
            account_group="Sundry Debtors",
            account_group_id=custom_gid,
        )
        migrate_legacy_ledger_groups()
        ledger = LedgerDAO.get_ledger_by_id(lid)
        # Should keep custom classification, not overwrite
        self.assertEqual(ledger["account_group_id"], custom_gid)


# ======================================================================
# Tests 52-58: Regression — full module regression after Phase 4B
# ======================================================================

class TestPartyRegression(_BaseTest):

    def setUp(self):
        super().setUp()
        ensure_system_ledgers()
        ensure_account_groups()

        self.company_id = CompanyDAO.insert("TestCo4B", "TC4B")
        self.unit_id = UnitDAO.insert("Pcs")
        self.drug_id = DrugDAO.insert("Paracetamol")
        self.customer_id = CustomerDAO.insert("Cust4B")
        self.doctor_id = DoctorDAO.insert("Dr. 4B")
        self.supplier_id = SupplierDAO.insert("Sup4B")
        self.item_id = ItemDAO.insert(
            item_name="Item4B", unit_id=self.unit_id,
            company_id=self.company_id, pack_size="10x10",
        )

        self.customer_ledger_id = CustomerDAO.get_ledger_id(self.customer_id)
        self.supplier_ledger_id = SupplierDAO.get_ledger_id(self.supplier_id)

        PurchaseDAO.insert_invoice(
            voucher_no="PV-4B", voucher_date="2026-04-01", voucher_time="",
            purchase_type="Cash", supplier_id=self.supplier_id,
            invoice_no="INV-4B", invoice_date="2026-04-01",
            invoice_net_amount=4000.0, bill_discount=0,
            due_date="", total_amount=4000.0, gst_amount=0,
            debit_note_amount=0, other_amount=0,
            paid_amount=4000.0, round_off=0,
            net_amount=4000.0, remarks="",
            items=[{
                "item_id": self.item_id, "pack_size": "10x10",
                "pay_qty": 100.0, "free_qty": 0, "batch_no": "B4B",
                "expiry": "12/28", "rate": 40.0, "mrp": 50.0,
                "discount": 0, "gst_percent": 0, "gst_amount": 0,
                "amount": 4000.0, "purchase_rate": 40.0,
                "net_rate": 40.0, "pp": 40.0,
            }],
        )
        batches = StockDAO.get_stock_batches_for_item(self.item_id)
        self.batch_id = batches[0]["id"]

        migrate_legacy_ledger_groups()

    def test_52_trial_balance_still_works(self):
        from database.trial_balance_dao import TrialBalanceDAO
        data = TrialBalanceDAO.get_trial_balance()
        self.assertIsInstance(data, dict)
        self.assertIn("rows", data)
        self.assertIn("totals", data)

    def test_53_account_ledger_classified(self):
        cust_ledger = LedgerDAO.get_ledger_by_id(self.customer_ledger_id)
        self.assertIsNotNone(cust_ledger["account_group_id"])
        sup_ledger = LedgerDAO.get_ledger_by_id(self.supplier_ledger_id)
        self.assertIsNotNone(sup_ledger["account_group_id"])

    def test_54_customer_receipt_still_works(self):
        rid = CustomerReceiptDAO.insert_receipt({
            "receipt_date": "2026-04-01", "receipt_time": "",
            "customer_id": self.customer_id, "receipt_mode": "Cash",
            "amount": 100.0, "reference_no": "", "remarks": "",
        })
        self.assertGreater(rid, 0)

    def test_55_supplier_payment_still_works(self):
        pid = SupplierPaymentDAO.insert_payment({
            "payment_date": "2026-04-01", "payment_time": "",
            "supplier_id": self.supplier_id, "payment_mode": "Cash",
            "amount": 100.0, "reference_no": "", "remarks": "",
        })
        self.assertGreater(pid, 0)

    def test_56_counter_sale_still_works(self):
        bill_no = SalesDAO.generate_next_bill_no()
        sid = SalesDAO.insert_invoice(
            bill_no=bill_no, sale_date="2026-04-01", sale_time="",
            sale_type="Cash", customer_id=None, patient_name="",
            doctor_id=None, discount=0, paid_amount=100.0,
            total_amount=100.0, round_off=0, net_amount=100.0,
            remarks="",
            items=[{
                "item_id": self.item_id, "stock_batch_id": self.batch_id,
                "pack_size": "10x10", "location": "", "batch_no": "B4B",
                "expiry": "12/28", "mrp": 50.0, "sale_qty": 2.0,
                "discount_amount": 0, "amount": 100.0,
            }],
        )
        self.assertGreater(sid, 0)

    def test_57_purchase_still_works(self):
        pid = PurchaseDAO.insert_invoice(
            voucher_no="PV-4B2", voucher_date="2026-04-01", voucher_time="",
            purchase_type="Credit", supplier_id=self.supplier_id,
            invoice_no="INV-4B2", invoice_date="2026-04-01",
            invoice_net_amount=200.0, bill_discount=0,
            due_date="", total_amount=200.0, gst_amount=0,
            debit_note_amount=0, other_amount=0,
            paid_amount=0, round_off=0,
            net_amount=200.0, remarks="",
            items=[{
                "item_id": self.item_id, "pack_size": "10x10",
                "pay_qty": 5, "free_qty": 0, "batch_no": "B4B",
                "expiry": "12/28", "rate": 40.0, "mrp": 50.0,
                "discount": 0, "gst_percent": 0, "gst_amount": 0,
                "amount": 200.0, "purchase_rate": 40.0,
                "net_rate": 40.0, "pp": 40.0,
            }],
        )
        self.assertGreater(pid, 0)

    def test_58_all_master_screens_data(self):
        self.assertIsNotNone(CompanyDAO.get_all())
        self.assertIsNotNone(LedgerDAO.get_all_ledgers())
        tree = AccountGroupDAO.get_tree()
        self.assertGreater(len(tree), 0)


if __name__ == "__main__":
    unittest.main()
