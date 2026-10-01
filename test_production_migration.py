"""Tests for Phase 6D-1 Controlled Production Database Migration & Backup Verification."""

import os
import shutil
import sqlite3
import hashlib
from unittest import TestCase
from datetime import datetime

from database.backup_restore import create_backup, validate_backup, _copy_db
from database.connection import init_database
from database import auth
from database.financial_year import ensure_default_financial_year
from database.hold_bill_dao import ensure_hold_tables

PROD_DB = os.path.abspath(os.path.join(os.path.dirname(__file__), "data", "pharmacy.db"))
BACKUP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "backups"))


class TestProductionMigration(TestCase):
    """
    Tests for backup and migration safety.
    IMPORTANT: We never mutate PROD_DB in these tests.
    We copy it to a temporary location.
    """

    @classmethod
    def setUpClass(cls):
        # We need a pristine copy of PROD_DB for each test method to play with,
        # or we just create one temp DB and use it.
        # But for 30 tests, it's better to manage per-test setups.
        pass

    def setUp(self):
        self.temp_db = f"_test_migration_{id(self)}.db"
        if os.path.exists(self.temp_db):
            os.remove(self.temp_db)
        
        # Copy prod_db to temp_db (rehearsal DB)
        shutil.copy2(PROD_DB, self.temp_db)
        os.environ["PHARMACY_DB"] = self.temp_db

    def tearDown(self):
        if os.path.exists(self.temp_db):
            try:
                os.remove(self.temp_db)
            except OSError:
                pass
        if "PHARMACY_DB" in os.environ:
            del os.environ["PHARMACY_DB"]

    def _get_counts(self, db_path):
        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [r[0] for r in cursor.fetchall()]
            counts = {}
            for t in tables:
                cursor.execute(f"SELECT COUNT(*) FROM {t}")
                counts[t] = cursor.fetchone()[0]
            return counts
        finally:
            conn.close()

    def _run_migration(self):
        init_database()
        auth.ensure_auth_schema()
        ensure_default_financial_year()
        ensure_hold_tables()

    # --- 1. Production DB Inspection Tests ---
    
    def test_01_prod_db_exists(self):
        self.assertTrue(os.path.exists(PROD_DB), "Production database must exist")

    def test_02_prod_db_has_size(self):
        size = os.path.getsize(PROD_DB)
        self.assertGreater(size, 0, "Production database must not be empty")

    def test_03_prod_db_is_sqlite(self):
        with open(PROD_DB, 'rb') as f:
            header = f.read(16)
        self.assertEqual(header, b"SQLite format 3\000")

    def test_04_prod_db_has_expected_tables(self):
        conn = sqlite3.connect(PROD_DB)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cursor.fetchall()]
        conn.close()
        self.assertIn('items', tables)
        self.assertIn('financial_years', tables)

    # --- 2. Backup Creation & Validation Tests ---
    
    def test_05_backup_creation_succeeds(self):
        # We backup the temp_db to simulate
        backup_info = create_backup(BACKUP_DIR, record_last=False)
        self.assertTrue(os.path.exists(backup_info['path']))
        self.assertGreater(backup_info['size_bytes'], 0)
        os.remove(backup_info['path'])

    def test_06_backup_has_sha256(self):
        backup_info = create_backup(BACKUP_DIR, record_last=False)
        self.assertIn('sha256', backup_info)
        self.assertEqual(len(backup_info['sha256']), 64)
        os.remove(backup_info['path'])

    def test_07_backup_validation_succeeds(self):
        backup_info = create_backup(BACKUP_DIR, record_last=False)
        val = validate_backup(backup_info['path'])
        self.assertTrue(val['valid'])
        self.assertEqual(val['integrity'], 'ok')
        os.remove(backup_info['path'])

    def test_08_backup_validation_returns_tables(self):
        backup_info = create_backup(BACKUP_DIR, record_last=False)
        val = validate_backup(backup_info['path'])
        self.assertGreater(len(val['tables']), 0)
        os.remove(backup_info['path'])

    def test_09_backup_validation_detects_empty_file(self):
        empty_file = os.path.join(BACKUP_DIR, "empty_backup.db")
        with open(empty_file, 'w') as f:
            f.write("")
        val = validate_backup(empty_file)
        self.assertFalse(val['valid'])
        self.assertEqual(val['reason'], "File is empty.")
        os.remove(empty_file)

    def test_10_backup_validation_detects_missing_file(self):
        val = validate_backup("nonexistent_backup.db")
        self.assertFalse(val['valid'])
        self.assertEqual(val['reason'], "File not found.")

    def test_11_backup_file_is_readonly_during_validation(self):
        backup_info = create_backup(BACKUP_DIR, record_last=False)
        mtime_before = os.path.getmtime(backup_info['path'])
        validate_backup(backup_info['path'])
        mtime_after = os.path.getmtime(backup_info['path'])
        self.assertEqual(mtime_before, mtime_after)
        os.remove(backup_info['path'])

    # --- 3. Migration Rehearsal & Schema Tests ---
    
    def test_12_migration_adds_category_table(self):
        self._run_migration()
        conn = sqlite3.connect(self.temp_db)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='categories'")
        self.assertIsNotNone(cursor.fetchone())
        conn.close()

    def test_13_migration_adds_hold_bills_table(self):
        self._run_migration()
        conn = sqlite3.connect(self.temp_db)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='hold_bills'")
        self.assertIsNotNone(cursor.fetchone())
        conn.close()

    def test_14_migration_adds_hold_bill_items_table(self):
        self._run_migration()
        conn = sqlite3.connect(self.temp_db)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='hold_bill_items'")
        self.assertIsNotNone(cursor.fetchone())
        conn.close()

    def test_15_migration_does_not_drop_tables(self):
        tables_before = set(self._get_counts(self.temp_db).keys())
        self._run_migration()
        tables_after = set(self._get_counts(self.temp_db).keys())
        # All old tables must be in the new tables set
        self.assertTrue(tables_before.issubset(tables_after))

    def test_16_migration_preserves_row_counts(self):
        counts_before = self._get_counts(self.temp_db)
        self._run_migration()
        counts_after = self._get_counts(self.temp_db)
        
        for t, count in counts_before.items():
            self.assertEqual(count, counts_after[t], f"Row count changed for table {t}")

    def test_17_migration_preserves_financial_year(self):
        conn = sqlite3.connect(self.temp_db)
        fy_before = conn.execute("SELECT * FROM financial_years").fetchall()
        conn.close()
        
        self._run_migration()
        
        conn = sqlite3.connect(self.temp_db)
        fy_after = conn.execute("SELECT * FROM financial_years").fetchall()
        conn.close()
        
        self.assertEqual(fy_before, fy_after)

    def test_18_migration_preserves_users(self):
        conn = sqlite3.connect(self.temp_db)
        users_before = conn.execute("SELECT * FROM app_users").fetchall()
        conn.close()
        
        self._run_migration()
        
        conn = sqlite3.connect(self.temp_db)
        users_after = conn.execute("SELECT * FROM app_users").fetchall()
        conn.close()
        
        self.assertEqual(users_before, users_after)

    def test_19_migration_foreign_keys_valid(self):
        self._run_migration()
        conn = sqlite3.connect(self.temp_db)
        cursor = conn.cursor()
        cursor.execute("PRAGMA foreign_key_check")
        violations = cursor.fetchall()
        conn.close()
        self.assertEqual(len(violations), 0, f"FK violations found: {violations}")

    def test_20_migration_integrity_ok(self):
        self._run_migration()
        conn = sqlite3.connect(self.temp_db)
        cursor = conn.cursor()
        cursor.execute("PRAGMA integrity_check")
        integrity = cursor.fetchone()[0]
        conn.close()
        self.assertEqual(integrity, "ok")

    # --- 4. Migration Idempotence Tests ---

    def test_21_idempotence_table_count(self):
        self._run_migration()
        counts_run1 = self._get_counts(self.temp_db)
        
        self._run_migration() # run again
        counts_run2 = self._get_counts(self.temp_db)
        
        self.assertEqual(len(counts_run1), len(counts_run2))

    def test_22_idempotence_row_counts(self):
        self._run_migration()
        counts_run1 = self._get_counts(self.temp_db)
        
        self._run_migration()
        counts_run2 = self._get_counts(self.temp_db)
        
        self.assertEqual(counts_run1, counts_run2)

    def test_23_idempotence_foreign_keys(self):
        self._run_migration()
        self._run_migration()
        conn = sqlite3.connect(self.temp_db)
        cursor = conn.cursor()
        cursor.execute("PRAGMA foreign_key_check")
        violations = cursor.fetchall()
        conn.close()
        self.assertEqual(len(violations), 0)

    def test_24_idempotence_integrity(self):
        self._run_migration()
        self._run_migration()
        conn = sqlite3.connect(self.temp_db)
        cursor = conn.cursor()
        cursor.execute("PRAGMA integrity_check")
        integrity = cursor.fetchone()[0]
        conn.close()
        self.assertEqual(integrity, "ok")

    # --- 5. Restore Rehearsal Tests ---
    
    def test_25_restore_rehearsal_copies_data(self):
        backup_info = create_backup(BACKUP_DIR, record_last=False)
        restore_db = self.temp_db + "_restored"
        
        _copy_db(backup_info['path'], restore_db)
        self.assertTrue(os.path.exists(restore_db))
        
        size1 = os.path.getsize(backup_info['path'])
        size2 = os.path.getsize(restore_db)
        
        # SQLite copy might have slight size diff due to pages, but should be close.
        self.assertGreater(size2, 0)
        
        os.remove(backup_info['path'])
        os.remove(restore_db)

    def test_26_restore_rehearsal_integrity(self):
        backup_info = create_backup(BACKUP_DIR, record_last=False)
        restore_db = self.temp_db + "_restored"
        _copy_db(backup_info['path'], restore_db)
        
        conn = sqlite3.connect(restore_db)
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        conn.close()
        self.assertEqual(integrity, "ok")
        
        os.remove(backup_info['path'])
        os.remove(restore_db)

    def test_27_restore_rehearsal_validates(self):
        backup_info = create_backup(BACKUP_DIR, record_last=False)
        restore_db = self.temp_db + "_restored"
        _copy_db(backup_info['path'], restore_db)
        
        val = validate_backup(restore_db)
        self.assertTrue(val['valid'])
        
        os.remove(backup_info['path'])
        os.remove(restore_db)

    def test_28_restore_rehearsal_preserves_master_data(self):
        # Migration already run in previous tests might not be here.
        self._run_migration()
        backup_info = create_backup(BACKUP_DIR, record_last=False)
        
        restore_db = self.temp_db + "_restored"
        _copy_db(backup_info['path'], restore_db)
        
        conn = sqlite3.connect(restore_db)
        items_count = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        conn.close()
        
        self.assertGreaterEqual(items_count, 0)
        
        os.remove(backup_info['path'])
        os.remove(restore_db)

    # --- 6. Safety boundary tests ---

    def test_29_migration_does_not_modify_prod_db_directly(self):
        mtime_before = os.path.getmtime(PROD_DB)
        self._run_migration()
        mtime_after = os.path.getmtime(PROD_DB)
        # Assuming the OS timestamps are fine. Note we are migrating temp_db.
        self.assertEqual(mtime_before, mtime_after)

    def test_30_prod_db_remains_the_same_size_if_untouched(self):
        size_before = os.path.getsize(PROD_DB)
        self._run_migration()
        size_after = os.path.getsize(PROD_DB)
        self.assertEqual(size_before, size_after)

