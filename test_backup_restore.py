"""Phase 5F — Backup & Restore tests.

45 tests (42 service-level + 3 PySide6-dependent UI tests that skip in
headless environments and run in the development environment).

Isolation guarantees:
  - every test runs against a throwaway database via PHARMACY_DB
    (_test_backup_restore.db) — data/pharmacy.db is never touched
  - backups are written to per-test temporary directories
  - the old Pharma-WINNER/MySQL database is never referenced anywhere
"""

import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database.connection import get_connection, init_database, get_db_path
from database.account_roles import ensure_system_ledgers
from database import backup_restore
from database.backup_restore import (
    EXPECTED_TABLES,
    BackupError,
    compute_sha256,
    create_backup,
    get_database_info,
    get_last_backup_info,
    restore_backup,
    validate_backup,
    verify_checksum,
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
    from screens.backup_restore import BackupRestorePage

    HAS_PYSIDE6 = True
    _PYSIDE_SKIP_REASON = ""
except ImportError as _exc:  # pragma: no cover
    HAS_PYSIDE6 = False
    _PYSIDE_SKIP_REASON = f"PySide6 not available ({_exc})"

TABLES = [
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

REAL_DB = os.path.join(os.path.dirname(__file__), "data", "pharmacy.db")


class _BaseTest(unittest.TestCase):
    _DB_PATH = os.path.join(os.path.dirname(__file__), "_test_backup_restore.db")

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

        self._tmp = tempfile.mkdtemp(prefix="pharmacy_backup_test_")
        self.addCleanup(shutil.rmtree, self._tmp, True)

        self.company_id = CompanyDAO.insert("BkpCompany", "BC")
        self.unit_id = UnitDAO.insert("Pcs")
        self.drug_id = DrugDAO.insert("Paracetamol")
        self.customer_id = CustomerDAO.insert("BkpCustomer")
        self.doctor_id = DoctorDAO.insert("Dr. Backup")
        self.supplier_id = SupplierDAO.insert("BkpSupplier")
        self.item_id = ItemDAO.insert(
            item_name="BkpItem", unit_id=self.unit_id,
            company_id=self.company_id, pack_size="10x10",
        )
        ensure_system_ledgers()

    # ── helpers ──────────────────────────────────────────────────────
    def _backup(self, name="test_backup.db"):
        return create_backup(os.path.join(self._tmp, name))

    def _read_from(self, db_path, sql, params=()):
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]
        finally:
            conn.close()

    def _db_hash(self):
        return compute_sha256(get_db_path())

    def _seed_purchase(self, voucher_no="PV-0001", qty=10.0, rate=40.0,
                       gst_percent=5.0, batch_no="BATCH-A",
                       invoice_no="INV-0001"):
        amount = round(qty * rate, 2)
        gst_amount = round(amount * gst_percent / 100.0, 2)
        total = amount
        net = round(total + gst_amount, 2)
        return PurchaseDAO.insert_invoice(
            voucher_no=voucher_no, voucher_date="2026-02-01",
            voucher_time="", purchase_type="Credit",
            supplier_id=self.supplier_id, invoice_no=invoice_no,
            invoice_date="2026-02-01", invoice_net_amount=net,
            bill_discount=0, due_date="", total_amount=total,
            gst_amount=gst_amount, debit_note_amount=0, other_amount=0,
            paid_amount=0, round_off=0, net_amount=net, remarks="",
            items=[{
                "item_id": self.item_id, "pack_size": "10x10",
                "pay_qty": qty, "free_qty": 0, "batch_no": batch_no,
                "expiry": "12/27", "rate": rate, "mrp": 50.0, "discount": 0,
                "gst_percent": gst_percent, "gst_amount": gst_amount,
                "amount": amount, "purchase_rate": rate, "net_rate": rate,
                "pp": rate,
            }],
        )

    def _seed_sale(self):
        batch = StockDAO.get_stock_batches_for_item(self.item_id)[0]
        return SalesDAO.insert_invoice(
            bill_no="CS-0001", sale_date="2026-02-02", sale_time="",
            sale_type="Cash", customer_id=self.customer_id,
            patient_name="Pat", doctor_id=self.doctor_id, discount=0,
            paid_amount=50, total_amount=50, round_off=0, net_amount=50,
            remarks="",
            items=[{
                "item_id": self.item_id, "stock_batch_id": batch["id"],
                "pack_size": "10x10", "location": "", "batch_no": "BATCH-A",
                "expiry": "12/27", "mrp": 50, "sale_qty": 1,
                "discount_amount": 0, "amount": 50,
            }],
        )

    def _seed_everything(self):
        """One record of all 7 posted source types + masters."""
        self._seed_purchase()
        self._seed_sale()
        batch = StockDAO.get_stock_batches_for_item(self.item_id)[0]
        CreditNoteDAO.insert_credit_note(
            {"voucher_date": "2026-02-03", "cn_date": "2026-02-03",
             "cn_type": "Customer", "customer_id": self.customer_id,
             "total_amount": 40.0, "ledger_amount": 40.0, "remarks": ""},
            [{
                "item_id": self.item_id, "stock_batch_id": batch["id"],
                "batch_no": "BATCH-A", "expiry": "12/27",
                "pack_size": "10x10", "rate": 40, "mrp": 50,
                "return_qty": 1, "less_amount": 0, "amount": 40,
                "return_reason": "", "price_factor": 1.0,
            }],
        )
        DebitNoteDAO.insert_debit_note(
            {"voucher_date": "2026-02-04", "voucher_time": "",
             "dn_date": "2026-02-04", "dn_type": "Supplier",
             "supplier_id": self.supplier_id, "total_amount": 20.0,
             "ledger_amount": 20.0, "remarks": ""},
            [{
                "item_id": self.item_id, "stock_batch_id": batch["id"],
                "batch_no": "BATCH-A", "expiry": "12/27",
                "pack_size": "10x10", "rate": 40, "mrp": 50,
                "return_qty": 0.5, "less_amount": 0, "amount": 20,
                "return_reason": "", "price_factor": 1.0,
            }],
        )
        CustomerReceiptDAO.insert_receipt({
            "receipt_date": "2026-02-05", "receipt_time": "",
            "customer_id": self.customer_id, "receipt_mode": "Cash",
            "amount": 10.0, "reference_no": "", "remarks": "",
        })
        SupplierPaymentDAO.insert_payment({
            "payment_date": "2026-02-05", "payment_time": "",
            "supplier_id": self.supplier_id, "payment_mode": "Cash",
            "amount": 5.0, "reference_no": "", "remarks": "",
        })
        cash = LedgerDAO.get_by_system_role("CASH")
        bank = LedgerDAO.get_by_system_role("BANK")
        JournalDAO.insert_entry(
            {"entry_date": "2026-02-05", "narration": "Backup test"},
            [
                {"ledger_id": cash["id"], "description": "",
                 "debit": 15.0, "credit": 0.0},
                {"ledger_id": bank["id"], "description": "",
                 "debit": 0.0, "credit": 15.0},
            ],
        )


# ======================================================================
# 1-14: Backup creation and preservation
# ======================================================================

class TestBackupCreation(_BaseTest):

    def test_01_backup_empty_database(self):
        info = self._backup("empty.db")
        self.assertTrue(os.path.isfile(info["path"]))
        self.assertGreater(info["size_bytes"], 0)
        self.assertEqual(info["table_count"], len(EXPECTED_TABLES))

    def test_02_backup_populated_database(self):
        CompanyDAO.insert("SecondCo", "SC")
        info = self._backup("populated.db")
        self.assertEqual(len(info["sha256"]), 64)
        rows = self._read_from(
            info["path"], "SELECT company_name FROM companies ORDER BY id"
        )
        self.assertEqual(
            [r["company_name"] for r in rows], ["BkpCompany", "SecondCo"]
        )

    def test_03_backup_includes_all_tables(self):
        info = self._backup()
        validation = validate_backup(info["path"])
        self.assertTrue(validation["valid"])
        for table in EXPECTED_TABLES:
            self.assertIn(table, validation["tables"])

    def test_04_schema_preserved(self):
        info = self._backup()
        source_cols = [
            r["name"] for r in self._read_from(
                get_db_path(), "PRAGMA table_info(purchase_invoices)"
            )
        ]
        backup_cols = [
            r["name"] for r in self._read_from(
                info["path"], "PRAGMA table_info(purchase_invoices)"
            )
        ]
        self.assertEqual(source_cols, backup_cols)
        self.assertIn("net_amount", backup_cols)

    def test_05_indexes_preserved(self):
        info = self._backup()
        source_idx = sorted(
            r["name"] for r in self._read_from(
                get_db_path(),
                "SELECT name FROM sqlite_master WHERE type='index' "
                "AND name NOT LIKE 'sqlite_%'",
            )
        )
        backup_idx = sorted(
            r["name"] for r in self._read_from(
                info["path"],
                "SELECT name FROM sqlite_master WHERE type='index' "
                "AND name NOT LIKE 'sqlite_%'",
            )
        )
        self.assertEqual(source_idx, backup_idx)
        self.assertIn("idx_account_ledgers_system_role", backup_idx)

    def test_06_constraints_preserved(self):
        info = self._backup()
        # UNIQUE(company_name) is still enforced inside the backup
        conn = sqlite3.connect(info["path"])
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO companies (company_name, short_name) "
                    "VALUES (?, ?)", ("BkpCompany", "DUP")
                )
                conn.commit()
        finally:
            conn.close()

    def test_07_foreign_keys_preserved(self):
        info = self._backup()
        source_fk = self._read_from(
            get_db_path(), "PRAGMA foreign_key_list(sales_invoices)"
        )
        backup_fk = self._read_from(
            info["path"], "PRAGMA foreign_key_list(sales_invoices)"
        )
        self.assertEqual(len(source_fk), len(backup_fk))
        self.assertGreater(len(backup_fk), 0)

    def test_08_purchase_data_preserved(self):
        self._seed_purchase(qty=12, rate=40, gst_percent=5)
        info = self._backup()
        invoices = self._read_from(
            info["path"], "SELECT * FROM purchase_invoices"
        )
        self.assertEqual(len(invoices), 1)
        self.assertEqual(invoices[0]["voucher_no"], "PV-0001")
        self.assertEqual(invoices[0]["gst_amount"], 24.0)
        self.assertEqual(invoices[0]["net_amount"], 504.0)
        items = self._read_from(
            info["path"], "SELECT * FROM purchase_invoice_items"
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["pay_qty"], 12)

    def test_09_sales_data_preserved(self):
        self._seed_purchase()
        self._seed_sale()
        info = self._backup()
        sales = self._read_from(info["path"], "SELECT * FROM sales_invoices")
        self.assertEqual(len(sales), 1)
        self.assertEqual(sales[0]["bill_no"], "CS-0001")
        self.assertEqual(sales[0]["net_amount"], 50.0)
        items = self._read_from(
            info["path"], "SELECT * FROM sales_invoice_items"
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["amount"], 50.0)

    def test_10_stock_batches_preserved(self):
        self._seed_purchase(qty=10)
        info = self._backup()
        batches = self._read_from(
            info["path"], "SELECT * FROM stock_batches"
        )
        self.assertEqual(len(batches), 1)
        self.assertEqual(batches[0]["batch_no"], "BATCH-A")
        self.assertEqual(batches[0]["stock_qty"], 10.0)

    def test_11_customer_supplier_preserved(self):
        info = self._backup()
        customers = self._read_from(
            info["path"], "SELECT customer_name, ledger_id FROM customers"
        )
        suppliers = self._read_from(
            info["path"], "SELECT supplier_name, ledger_id FROM suppliers"
        )
        self.assertEqual(customers[0]["customer_name"], "BkpCustomer")
        self.assertIsNotNone(customers[0]["ledger_id"])
        self.assertEqual(suppliers[0]["supplier_name"], "BkpSupplier")
        self.assertIsNotNone(suppliers[0]["ledger_id"])

    def test_12_ledger_accounting_preserved(self):
        self._seed_purchase()
        info = self._backup()
        ledgers = self._read_from(
            info["path"],
            "SELECT ledger_name, system_role FROM account_ledgers "
            "WHERE system_role IS NOT NULL ORDER BY system_role",
        )
        roles = [r["system_role"] for r in ledgers]
        self.assertIn("CASH", roles)
        self.assertIn("SALES", roles)
        txns = self._read_from(
            info["path"],
            "SELECT reference_type, debit, credit FROM ledger_transactions "
            "WHERE reference_type = 'PURCHASE_INVOICE'",
        )
        self.assertEqual(len(txns), 2)

    def test_13_journal_preserved(self):
        cash = LedgerDAO.get_by_system_role("CASH")
        bank = LedgerDAO.get_by_system_role("BANK")
        JournalDAO.insert_entry(
            {"entry_date": "2026-02-06", "narration": "Preserved JE"},
            [
                {"ledger_id": cash["id"], "description": "",
                 "debit": 33.0, "credit": 0.0},
                {"ledger_id": bank["id"], "description": "",
                 "debit": 0.0, "credit": 33.0},
            ],
        )
        info = self._backup()
        entries = self._read_from(
            info["path"], "SELECT * FROM journal_entries"
        )
        items = self._read_from(
            info["path"], "SELECT * FROM journal_entry_items"
        )
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["narration"], "Preserved JE")
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["debit"], 33.0)

    def test_14_gst_purchase_fields_preserved(self):
        self._seed_purchase(qty=10, rate=40, gst_percent=5)
        info = self._backup()
        items = self._read_from(
            info["path"],
            "SELECT gst_percent, gst_amount FROM purchase_invoice_items",
        )
        self.assertEqual(items[0]["gst_percent"], 5.0)
        self.assertEqual(items[0]["gst_amount"], 20.0)  # 400 × 5%

    def test_14b_gst_varied_rates_preserved(self):
        self._seed_purchase(voucher_no="PV-A", gst_percent=5, invoice_no="I1")
        self._seed_purchase(voucher_no="PV-B", gst_percent=12, invoice_no="I2")
        info = self._backup()
        rates = sorted(
            r["gst_percent"] for r in self._read_from(
                info["path"],
                "SELECT gst_percent FROM purchase_invoice_items",
            )
        )
        self.assertEqual(rates, [5.0, 12.0])


# ======================================================================
# 15-24: Validation and checksum
# ======================================================================

class TestValidation(_BaseTest):

    def test_15_validate_valid_backup(self):
        info = self._backup()
        result = validate_backup(info["path"])
        self.assertTrue(result["valid"])
        self.assertEqual(result["reason"], "")
        self.assertEqual(result["integrity"], "ok")
        self.assertEqual(len(result["sha256"]), 64)
        self.assertEqual(len(result["tables"]), len(EXPECTED_TABLES))
        self.assertEqual(result["missing_tables"], [])

    def test_16_validate_invalid_sqlite_file(self):
        path = os.path.join(self._tmp, "not_a_db.db")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("this is definitely not a sqlite database")
        result = validate_backup(path)
        self.assertFalse(result["valid"])
        self.assertNotEqual(result["reason"], "")

    def test_17_validate_nonexistent_backup(self):
        result = validate_backup(os.path.join(self._tmp, "missing.db"))
        self.assertFalse(result["valid"])
        self.assertIn("not found", result["reason"].lower())

    def test_18_validate_empty_file(self):
        path = os.path.join(self._tmp, "empty.db")
        open(path, "wb").close()
        result = validate_backup(path)
        self.assertFalse(result["valid"])
        self.assertIn("empty", result["reason"].lower())

    def test_19_validate_corrupted_backup(self):
        info = self._backup("corrupt_me.db")
        size = os.path.getsize(info["path"])
        with open(info["path"], "r+b") as fh:
            # Destroy a full page region in the middle of the file —
            # deterministic corruption of used B-tree pages
            fh.seek(size // 2)
            fh.write(b"\xff" * min(4096, size // 4))
        result = validate_backup(info["path"])
        self.assertFalse(result["valid"])
        self.assertNotEqual(result["reason"], "")

    def test_20_validate_missing_tables(self):
        path = os.path.join(self._tmp, "wrong_schema.db")
        conn = sqlite3.connect(path)
        try:
            conn.execute("CREATE TABLE dummy (id INTEGER)")
            conn.commit()
        finally:
            conn.close()
        result = validate_backup(path)
        self.assertFalse(result["valid"])
        self.assertIn("missing tables", result["reason"].lower())
        self.assertIn("companies", result["missing_tables"])

    def test_21_validation_does_not_modify_backup(self):
        info = self._backup()
        before_sha = compute_sha256(info["path"])
        before_mtime = os.path.getmtime(info["path"])
        validate_backup(info["path"])
        validate_backup(info["path"])  # idempotent, read-only
        self.assertEqual(compute_sha256(info["path"]), before_sha)
        self.assertEqual(os.path.getmtime(info["path"]), before_mtime)

    def test_22_checksum_consistent(self):
        info = self._backup()
        self.assertEqual(
            compute_sha256(info["path"]), compute_sha256(info["path"])
        )
        self.assertEqual(info["sha256"], compute_sha256(info["path"]))

    def test_23_checksum_changes_for_changed_file(self):
        info = self._backup("change_me.db")
        before = compute_sha256(info["path"])
        with open(info["path"], "ab") as fh:
            fh.write(b"extra-bytes")
        self.assertNotEqual(compute_sha256(info["path"]), before)

    def test_24_verify_checksum_helper(self):
        info = self._backup()
        self.assertTrue(verify_checksum(info["path"], info["sha256"]))
        self.assertFalse(verify_checksum(info["path"], "0" * 64))
        self.assertFalse(
            verify_checksum(os.path.join(self._tmp, "nope.db"), info["sha256"])
        )


# ======================================================================
# 25-37: Restore
# ======================================================================

class TestRestore(_BaseTest):

    def test_25_restore_success(self):
        info = self._backup("snapshot.db")
        # Change live data after the backup
        CompanyDAO.insert("AddedAfterBackup", "AAB")
        outcome = restore_backup(info["path"])
        self.assertTrue(outcome["restored"])
        names = [
            r["company_name"] for r in self._read_from(
                get_db_path(), "SELECT company_name FROM companies ORDER BY id"
            )
        ]
        self.assertEqual(names, ["BkpCompany"])

    def test_26_restore_replaces_changed_data(self):
        info = self._backup("state_a.db")
        # Rename company (state B) then restore state A
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE companies SET company_name = 'RenamedCo' WHERE id = ?",
                (self.company_id,),
            )
            conn.commit()
        finally:
            conn.close()
        restore_backup(info["path"])
        rows = self._read_from(
            get_db_path(), "SELECT company_name FROM companies"
        )
        self.assertEqual(rows[0]["company_name"], "BkpCompany")

    def test_27_restore_preserves_all_modules(self):
        self._seed_everything()
        info = self._backup("full.db")

        snapshot_tables = [
            "companies", "customers", "suppliers", "items",
            "stock_batches", "purchase_invoices", "purchase_invoice_items",
            "sales_invoices", "sales_invoice_items",
            "credit_notes", "credit_note_items",
            "debit_notes", "debit_note_items",
            "customer_receipts", "supplier_payments",
            "journal_entries", "journal_entry_items",
            "account_ledgers", "ledger_transactions",
        ]
        expected = {
            t: self._read_from(get_db_path(), f"SELECT * FROM {t} ORDER BY id")
            for t in snapshot_tables
        }

        # Wreck the live data
        for tbl in TABLES:
            conn = get_connection()
            try:
                conn.execute(f"DELETE FROM {tbl}")
                conn.commit()
            finally:
                conn.close()
        CompanyDAO.insert("Junk", "J")

        restore_backup(info["path"])

        for t in snapshot_tables:
            actual = self._read_from(
                get_db_path(), f"SELECT * FROM {t} ORDER BY id"
            )
            self.assertEqual(actual, expected[t], f"table mismatch: {t}")

    def test_28_pre_restore_safety_backup_created(self):
        # Marker in current data before restoring an older backup
        CompanyDAO.insert("OnlyInCurrent", "OIC")
        info = self._backup("older.db")

        conn = get_connection()
        try:
            conn.execute("DELETE FROM companies WHERE company_name = 'OnlyInCurrent'")
            conn.commit()
        finally:
            conn.close()

        outcome = restore_backup(info["path"])
        safety = outcome["safety_backup"]
        self.assertTrue(os.path.isfile(safety))
        safety_validation = validate_backup(safety)
        self.assertTrue(safety_validation["valid"])
        # Safety backup contains the pre-restore state (no marker because
        # it was deleted just before, but it must contain BkpCompany)
        names = [
            r["company_name"] for r in self._read_from(
                safety, "SELECT company_name FROM companies"
            )
        ]
        self.assertIn("BkpCompany", names)

    def test_29_restore_refuses_invalid_backup(self):
        bad = os.path.join(self._tmp, "bad.db")
        with open(bad, "w", encoding="utf-8") as fh:
            fh.write("not sqlite")
        before = self._db_hash()
        with self.assertRaises(BackupError):
            restore_backup(bad)
        self.assertEqual(self._db_hash(), before)

    def test_30_restore_refuses_missing_backup(self):
        before = self._db_hash()
        with self.assertRaises(BackupError):
            restore_backup(os.path.join(self._tmp, "missing.db"))
        self.assertEqual(self._db_hash(), before)

    def test_31_failed_restore_recovers_original(self):
        info = self._backup("good.db")
        CompanyDAO.insert("MarkerCompany", "MC")

        # First _copy_db call (the restore) fails; the recovery call runs
        with mock.patch.object(
            backup_restore, "_copy_db",
            side_effect=[RuntimeError("simulated restore failure"),
                         mock.DEFAULT],
        ):
            with self.assertRaises(BackupError) as ctx:
                restore_backup(info["path"])
        self.assertIn("recovered", str(ctx.exception).lower())

    def test_32_failed_restore_no_data_loss(self):
        info = self._backup("good2.db")
        CompanyDAO.insert("MarkerCompany", "MC")

        with mock.patch.object(
            backup_restore, "_copy_db",
            side_effect=[RuntimeError("simulated restore failure"),
                         mock.DEFAULT],
        ):
            with self.assertRaises(BackupError):
                restore_backup(info["path"])

        names = [
            r["company_name"] for r in self._read_from(
                get_db_path(), "SELECT company_name FROM companies"
            )
        ]
        self.assertIn("MarkerCompany", names)  # original fully recovered

    def test_33_source_backup_unchanged_after_restore(self):
        info = self._backup("source.db")
        sha_before = compute_sha256(info["path"])
        restore_backup(info["path"])
        self.assertEqual(compute_sha256(info["path"]), sha_before)
        self.assertTrue(os.path.isfile(info["path"]))

    def test_34_repeated_backups(self):
        first = self._backup("first.db")
        CompanyDAO.insert("BetweenBackups", "BB")
        second = self._backup("second.db")
        self.assertTrue(validate_backup(first["path"])["valid"])
        self.assertTrue(validate_backup(second["path"])["valid"])
        self.assertNotEqual(first["sha256"], second["sha256"])

    def test_35_repeated_restore(self):
        info = self._backup("repeat.db")
        restore_backup(info["path"])
        outcome = restore_backup(info["path"])  # restore the same file again
        self.assertTrue(outcome["restored"])
        names = [
            r["company_name"] for r in self._read_from(
                get_db_path(), "SELECT company_name FROM companies"
            )
        ]
        self.assertEqual(names, ["BkpCompany"])

    def test_36_read_write_isolation(self):
        info = self._backup("isolate.db")
        backup_sha = compute_sha256(info["path"])
        # Mutating the live database must not touch the backup file
        CompanyDAO.insert("AfterBackup", "AB")
        self.assertEqual(compute_sha256(info["path"]), backup_sha)
        backup_names = [
            r["company_name"] for r in self._read_from(
                info["path"], "SELECT company_name FROM companies"
            )
        ]
        self.assertEqual(backup_names, ["BkpCompany"])

    def test_37_persistence_after_reopen(self):
        info = self._backup("persist.db")
        CompanyDAO.insert("AfterBackup", "AB")
        restore_backup(info["path"])

        # Fresh connection sees the restored state
        fresh = sqlite3.connect(get_db_path())
        fresh.row_factory = sqlite3.Row
        try:
            rows = [
                r["company_name"] for r in fresh.execute(
                    "SELECT company_name FROM companies"
                ).fetchall()
            ]
        finally:
            fresh.close()
        self.assertEqual(rows, ["BkpCompany"])


# ======================================================================
# 38-45: Info, naming, last-backup, safety, regression, UI
# ======================================================================

class TestInfoAndSafety(_BaseTest):

    def test_38_get_database_info(self):
        info = get_database_info()
        self.assertEqual(info["path"], get_db_path())
        self.assertTrue(info["exists"])
        self.assertGreater(info["size_bytes"], 0)
        self.assertEqual(info["table_count"], len(EXPECTED_TABLES))

    def test_39_folder_destination_timestamped_name(self):
        info = create_backup(self._tmp)  # folder, not a file path
        name = os.path.basename(info["path"])
        self.assertTrue(name.startswith("pharmacy_backup_"))
        self.assertTrue(name.endswith(".db"))
        self.assertIn(self._tmp, info["path"])

    def test_40_last_backup_info_recorded(self):
        info = self._backup("recorded.db")
        last = get_last_backup_info()
        self.assertIsNotNone(last)
        self.assertEqual(last["path"], info["path"])
        self.assertEqual(last["sha256"], info["sha256"])

        # Safety backups (record_last=False) must not overwrite the record
        safety = create_backup(self._tmp, record_last=False)
        self.assertNotEqual(safety["path"], info["path"])
        self.assertEqual(get_last_backup_info()["path"], info["path"])

    def test_41_real_database_not_touched(self):
        real_hash = None
        if os.path.isfile(REAL_DB):
            real_hash = compute_sha256(REAL_DB)

        # Full cycle against the isolated test database
        info = self._backup()
        CompanyDAO.insert("Cycle", "C")
        restore_backup(info["path"])

        if real_hash is not None:
            self.assertEqual(compute_sha256(REAL_DB), real_hash)
        # The test database (via PHARMACY_DB) is not data/pharmacy.db
        self.assertNotEqual(
            os.path.abspath(get_db_path()), os.path.abspath(REAL_DB)
        )

    def test_42_regression_crud_after_backup_ops(self):
        info = self._backup()
        restore_backup(info["path"])
        # Normal DAO operations still work after backup/restore
        cid = CompanyDAO.insert("PostRestoreCo", "PRC")
        self.assertIsNotNone(CompanyDAO.get_by_id(cid))
        self._seed_purchase(voucher_no="PV-AFTER")
        self.assertEqual(
            len(PurchaseDAO.get_all()), 1
        )


@unittest.skipUnless(HAS_PYSIDE6, _PYSIDE_SKIP_REASON)
class TestBackupRestoreUI(_BaseTest):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.app = QApplication.instance() or QApplication([])

    def test_43_page_opens(self):
        page = BackupRestorePage()
        self.assertIsNotNone(page)

    def test_44_page_shows_database_info(self):
        page = BackupRestorePage()
        self.assertIn(get_db_path(), page._db_path_lbl.text())
        self.assertIn("Tables:", page._db_size_lbl.text())

    def test_45_page_has_action_buttons(self):
        from PySide6.QtWidgets import QPushButton
        page = BackupRestorePage()
        texts = {
            b.text() for b in page.findChildren(QPushButton)
        }
        self.assertIn("Create Backup", texts)
        self.assertIn("Restore Backup", texts)
        self.assertIn("Validate Backup", texts)
        self.assertIn("Refresh", texts)


if __name__ == "__main__":
    unittest.main(verbosity=2)
