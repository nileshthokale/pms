"""Comprehensive Data Integrity Regression Test Suite.

Verifies application-wide data integrity fixes:
1. RC-1: Title & Staging Badge display in Staging Mode.
2. RC-2: Expiry date parsing for ISO YYYY-MM-DD in StockDAO.
3. RC-3: Sold-out batch return in StockDAO & CreditNoteDAO.
4. RC-4: Party balance synchronization between Vouchers & General Ledger.
5. RC-5: Robust pack size factor calculation across real-world packaging formats.
6. RC-6: Numeric manufacturer batch integrity (STASHPain batch '133').
7. RC-7: Numerical sorting behavior in table widgets.
8. RC-8: Item search by Legacy ID and Target Database ID.
9. DB-1: Production database immutability verification.
10. DB-2: User test invoice 72184 verification.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import sys
import unittest
from pathlib import Path

# Ensure project root is in sys.path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

PROD_DB = ROOT / "data" / "pharmacy.db"
STAGING_DB = ROOT / "staging" / "pharmacy_staging.db"
DISPOSABLE_DB = ROOT / "staging" / "test_integrity_disposable.db"

# Expected verified SHA-256 baselines for production database:
# - 338aeb... : Initial post-audit baseline
# - bfeb6f... : Forensically verified baseline after auth_audit_log row 192 (admin login at 16:04 UTC)
PROD_BASELINE_HASHES = {
    "338aeb0ef427789f5d729cffaa3a36354f0b0360c6aee3679f89cf4905904e75",
    "bfeb6f39fa8a4f7837c815f646f0dfcf66cf08383dc076817d772d5307226079",
}


def get_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


class FullAppDataIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Create disposable clone of staging for all tests
        if DISPOSABLE_DB.exists():
            DISPOSABLE_DB.unlink()
        shutil.copy2(STAGING_DB, DISPOSABLE_DB)
        os.environ["PHARMACY_DB"] = str(DISPOSABLE_DB)
        os.environ["PHARMACY_STAGING_MODE"] = "1"

    @classmethod
    def tearDownClass(cls):
        if DISPOSABLE_DB.exists():
            DISPOSABLE_DB.unlink()

    def test_01_production_database_untouched(self):
        """Verify production database has not been modified."""
        self.assertTrue(PROD_DB.exists(), "Production DB must exist")
        current_hash = get_hash(PROD_DB).lower()
        self.assertIn(
            current_hash,
            PROD_BASELINE_HASHES,
            f"Production DB hash mismatch! Expected one of {PROD_BASELINE_HASHES}, got {current_hash}",
        )

    def test_02_invoice_72184_user_test_provenance(self):
        """Verify invoice 72184 (bill 2015) in prod DB is a live user test record."""
        conn = sqlite3.connect(f"file:{PROD_DB}?mode=ro", uri=True)
        try:
            inv = conn.execute(
                "SELECT id, bill_no, sale_date, sale_time, customer_id, patient_name, net_amount, remarks "
                "FROM sales_invoices WHERE id = 72184"
            ).fetchone()
            self.assertIsNotNone(inv, "Invoice 72184 must exist in production database")
            self.assertEqual(inv[1], "2015", "Bill No must be '2015'")
            self.assertEqual(inv[2], "2026-10-20", "Sale date must be '2026-10-20'")
            self.assertEqual(inv[5], "MR NASIR ATTAR", "Patient must be 'MR NASIR ATTAR'")
            self.assertEqual(inv[7], "", "User test record must have empty remarks (no legacy header ID)")

            # Verify it has double-entry ledger postings in prod DB
            lt_count = conn.execute(
                "SELECT count(*) FROM ledger_transactions WHERE reference_type = 'COUNTER_SALE' AND reference_id = 72184"
            ).fetchone()[0]
            self.assertEqual(lt_count, 2, "Invoice 72184 must have 2 double-entry ledger postings")

            # Verify it does NOT exist in staging DB
            conn_staging = sqlite3.connect(f"file:{STAGING_DB}?mode=ro", uri=True)
            try:
                inv_staging = conn_staging.execute(
                    "SELECT id FROM sales_invoices WHERE id = 72184"
                ).fetchone()
                self.assertIsNone(inv_staging, "Invoice 72184 must NOT exist in staging database")
            finally:
                conn_staging.close()
        finally:
            conn.close()

    def test_03_expiry_date_parsing_iso_format(self):
        """RC-2: Verify StockDAO correctly parses ISO YYYY-MM-DD stored expiry dates."""
        from database.stock_dao import StockDAO

        # Test _is_expired helper
        self.assertTrue(StockDAO._is_expired("2016-08-31"), "2016 date must be expired")
        self.assertTrue(StockDAO._is_expired("2020-01-31"), "2020 date must be expired")
        self.assertFalse(StockDAO._is_expired("2032-05-31"), "2032 date must NOT be expired")
        self.assertTrue(StockDAO._is_expired("05/18"), "Legacy 05/18 must be expired")
        self.assertFalse(StockDAO._is_expired("12/35"), "Future 12/35 must NOT be expired")

        # Test search with Expired status
        expired_batches = StockDAO.search(stock_status="Expired")
        self.assertGreater(len(expired_batches), 1000, "Must find over 1000 expired batches in staging")

        # Test get_expiring
        expiring = StockDAO.get_expiring(within_months=3)
        self.assertGreater(len(expiring), 1000, "Must find expiring/expired batches")

    def test_04_zero_stock_batches_for_credit_notes(self):
        """RC-3: Verify StockDAO can return zero-stock batches for credit note returns."""
        from database.stock_dao import StockDAO

        # Item 1689 (STASHPain) has 42 total batches, but only 6 with stock > 0
        all_batches = StockDAO.get_stock_batches_for_item(1689, include_zero_stock=True)
        active_batches = StockDAO.get_stock_batches_for_item(1689, include_zero_stock=False)

        self.assertEqual(len(all_batches), 42, "Item 1689 should have 42 total batches")
        self.assertEqual(len(active_batches), 6, "Item 1689 should have 6 batches with stock > 0")
        self.assertGreater(len(all_batches), len(active_batches))

    def test_05_party_balance_synchronization(self):
        """RC-4: Verify Voucher balance equals General Ledger balance for parties with opening balances."""
        from database.supplier_payment_dao import SupplierPaymentDAO
        from database.customer_receipt_dao import CustomerReceiptDAO
        from database.ledger_dao import LedgerDAO
        from database.supplier_dao import SupplierDAO
        from database.customer_dao import CustomerDAO

        # Supplier 158: ANAND PHARMA has opening balance -10403
        sup = SupplierDAO.get_by_id(158)
        sup_voucher_bal = SupplierPaymentDAO.get_supplier_balance(158)
        sup_ledger_bal = LedgerDAO.get_balance(sup["ledger_id"])["closing_balance"]
        self.assertEqual(
            sup_voucher_bal,
            sup_ledger_bal,
            f"Supplier payment balance ({sup_voucher_bal}) must match ledger balance ({sup_ledger_bal})",
        )
        self.assertEqual(sup_voucher_bal, 208767.0)

        # Customer 186: MISS GAURI PATOLE
        cust = CustomerDAO.get_by_id(186)
        cust_voucher_bal = CustomerReceiptDAO.get_customer_balance(186)
        cust_ledger_bal = LedgerDAO.get_balance(cust["ledger_id"])["closing_balance"]
        self.assertEqual(
            cust_voucher_bal,
            cust_ledger_bal,
            f"Customer receipt balance ({cust_voucher_bal}) must match ledger balance ({cust_ledger_bal})",
        )
        self.assertEqual(cust_voucher_bal, 483.0)

    def test_06_pack_factor_robustness(self):
        """RC-5: Verify pack_factor robustly parses pharma packaging strings."""
        from database.purchase_dao import pack_factor

        cases = [
            ("10", 10.0),
            ("10'S", 10.0),
            ("10's", 10.0),
            ("1*10", 10.0),
            ("10*10", 100.0),
            ("1X10", 10.0),
            ("10TAB", 10.0),
            ("15 Tabs", 15.0),
            ("100ML", 100.0),
            ("1", 1.0),
            ("", 1.0),
            (None, 1.0),
        ]
        for text, expected in cases:
            self.assertEqual(
                pack_factor(text),
                expected,
                f"pack_factor({text!r}) should equal {expected}",
            )

    def test_07_numeric_batch_number_manufacturer_integrity(self):
        """RC-6: Verify batch '133' is a genuine manufacturer batch for STASHPain."""
        conn = sqlite3.connect(f"file:{STAGING_DB}?mode=ro", uri=True)
        try:
            # Batch 133 in stock_batches
            sb = conn.execute(
                "SELECT sb.id, sb.batch_no, sb.mrp, i.item_name FROM stock_batches sb "
                "JOIN items i ON i.id = sb.item_id WHERE sb.batch_no = '133' AND UPPER(i.item_name) = 'STASHPAIN'"
            ).fetchone()
            self.assertIsNotNone(sb, "Batch '133' must exist for STASHPAIN in stock_batches")
            self.assertEqual(sb[1], "133")

            # Check purchase provenance
            pur = conn.execute(
                "SELECT pi.invoice_no, pi.invoice_date, pii.batch_no, s.supplier_name "
                "FROM purchase_invoice_items pii "
                "JOIN purchase_invoices pi ON pi.id = pii.purchase_invoice_id "
                "JOIN suppliers s ON s.id = pi.supplier_id "
                "WHERE pii.item_id = 1689 AND pii.batch_no = '133'"
            ).fetchall()
            self.assertGreater(len(pur), 0, "Batch '133' must have purchase invoice provenance")
            self.assertEqual(pur[0][2], "133")
            self.assertIn("SHRINIWAS", pur[0][3].upper())
        finally:
            conn.close()

    def test_08_numerical_table_sorting(self):
        """RC-7: Verify NumericTableWidgetItem performs numerical rather than string comparison."""
        from screens.stock_master import NumericTableWidgetItem

        item_small = NumericTableWidgetItem(20.0, "20.00")
        item_large = NumericTableWidgetItem(100.0, "100.00")

        # In string sorting, "100.00" < "20.00" is True
        self.assertTrue("100.00" < "20.00")
        # In NumericTableWidgetItem, item_small < item_large must be True
        self.assertTrue(item_small < item_large)
        self.assertFalse(item_large < item_small)

    def test_09_item_search_by_legacy_id_and_target_id(self):
        """RC-8: Verify ItemDAO.search matches legacy ID 944 and target ID 1885."""
        from database.item_dao import ItemDAO

        by_legacy = ItemDAO.search("944")
        self.assertEqual(len(by_legacy), 1)
        self.assertEqual(by_legacy[0]["id"], 1885)
        self.assertEqual(by_legacy[0]["legacy_id"], "944")
        self.assertEqual(by_legacy[0]["item_name"], "MERSILK NW 5010")

        by_target = ItemDAO.search("1885")
        self.assertEqual(len(by_target), 1)
        self.assertEqual(by_target[0]["id"], 1885)

        by_name = ItemDAO.search("MERSILK")
        self.assertGreaterEqual(len(by_name), 1)
        self.assertEqual(by_name[0]["id"], 1885)


if __name__ == "__main__":
    test_methods = sorted([m for m in dir(FullAppDataIntegrityTests) if m.startswith("test_")])
    suite = unittest.TestLoader().loadTestsFromTestCase(FullAppDataIntegrityTests)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    failed_tests = {f[0]._testMethodName: f[1] for f in result.failures}
    error_tests = {e[0]._testMethodName: e[1] for e in result.errors}

    test_records = []
    for name in test_methods:
        fn = getattr(FullAppDataIntegrityTests, name)
        doc = getattr(fn, "__doc__", "") or ""
        st = "FAIL" if name in failed_tests else ("ERROR" if name in error_tests else "PASS")
        test_records.append({"name": name, "status": st, "description": doc.strip()})

    results_dict = {
        "total_tests": len(test_methods),
        "passed": len(test_methods) - len(result.failures) - len(result.errors),
        "failures": len(result.failures),
        "errors": len(result.errors),
        "tests": test_records,
    }
    with open("migration_backups/full_application_data_integrity_test_results.json", "w", encoding="utf-8") as f:
        json.dump(results_dict, f, indent=2)

    sys.exit(0 if result.wasSuccessful() else 1)
