"""Phase 2 party-master migration tests (temp DBs only, never data/pharmacy.db).

Covers: tool dry-run consistency, apply counts/IDs, SELF pair, WALKIN
defaults, ledger_id NULL + no auto-ledgers, opening balances excluded,
Phase-1 freeze, transaction tables empty, integrity/FK clean.
"""

import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "PharmaWinner202610051955.sql"


def _fresh_db(tag: str) -> str:
    import sys

    sys.path.insert(0, str(ROOT))
    db_path = os.path.join(tempfile.gettempdir(), f"pharmacy_phase2_{tag}.db")
    for suffix in ("", "-wal", "-shm"):
        stale = db_path + suffix
        if os.path.exists(stale):
            os.remove(stale)
    os.environ["PHARMACY_DB"] = db_path
    from database.connection import init_database

    init_database()
    return db_path


class Phase2DryRunTests(unittest.TestCase):
    def test_dry_run_consistent_with_expected_counts(self):
        import sys

        sys.path.insert(0, str(ROOT))
        from database.legacy_migration import LegacyDump
        from tools.migrate_party_masters_from_pharma_winner import build_dry_run

        rep = build_dry_run(LegacyDump(SOURCE))
        self.assertTrue(rep["internally_consistent"], rep["blockers"])
        self.assertEqual(rep["target_expected"],
                         {"customers": 29, "suppliers": 85, "doctors": 8})
        self.assertIn(3, rep["duplicate_doctor_names"].get("SELF", []))
        self.assertIn(6, rep["duplicate_doctor_names"].get("SELF", []))
        self.assertEqual(rep["missing_info_ledgers"], [7])  # WALKIN defaults
        self.assertEqual(rep["orphan_info_rows"], [])


class Phase2ApplyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_path = _fresh_db("apply")
        import sys

        sys.path.insert(0, str(ROOT))
        from tools.migrate_party_masters_from_pharma_winner import do_apply

        cls.result = do_apply(SOURCE, cls.db_path, backup_dir=tempfile.gettempdir(),
                              no_backup=True)

    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        self.addCleanup(conn.close)
        return conn

    def test_counts(self):
        conn = self._conn()
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0], 29)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM suppliers").fetchone()[0], 85)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM doctors").fetchone()[0], 8)

    def test_ids_preserved_and_self_pair(self):
        conn = self._conn()
        d3 = dict(conn.execute("SELECT * FROM doctors WHERE id=3").fetchone())
        d6 = dict(conn.execute("SELECT * FROM doctors WHERE id=6").fetchone())
        self.assertEqual((d3["doctor_name"], d3["city"]), ("SELF", "RAHURI"))
        self.assertEqual((d6["doctor_name"], d6["specialty"]), ("SELF", "SELF"))
        self.assertEqual(conn.execute("SELECT * FROM customers WHERE id=7").fetchone()["customer_name"], "WALKIN")
        self.assertEqual(conn.execute("SELECT * FROM suppliers WHERE id=8").fetchone()["supplier_name"], "KARWA AGENCIES")

    def test_no_ledgers_or_balances(self):
        conn = self._conn()
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM account_ledgers").fetchone()[0], 0)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM suppliers WHERE ledger_id IS NOT NULL").fetchone()[0], 0)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM customers WHERE ledger_id IS NOT NULL").fetchone()[0], 0)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM suppliers WHERE opening_balance!=0").fetchone()[0], 0)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM customers WHERE opening_balance!=0").fetchone()[0], 0)

    def test_transactions_empty_and_integrity(self):
        conn = self._conn()
        for t in ("purchase_invoices", "purchase_invoice_items", "stock_batches",
                  "sales_invoices", "sales_invoice_items", "customer_receipts",
                  "supplier_payments", "credit_notes", "credit_note_items",
                  "debit_notes", "debit_note_items", "journal_entries",
                  "journal_entry_items", "ledger_transactions"):
            self.assertEqual(conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0], 0, t)
        self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
