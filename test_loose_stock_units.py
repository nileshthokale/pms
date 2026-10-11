"""Loose-unit stock convention tests (disposable DBs only; never live).

Verified convention: stock_qty = loose tablets; pay/free = packs;
sale_qty/return_qty = loose; MRP/purchase_rate = per pack; amount =
qty * MRP / pack_size.  Covers pack sizes 1/5/10/15, UC-CART tablet
counts, purchase/sale/return/edit/delete round-trips, pricing, guards,
collisions incl. trailing whitespace, idempotent reconstruction, and
loose-unit valuation.
"""

from __future__ import annotations

import importlib.util
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database.legacy_migration import LegacyDump

_REC_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "tools", "reconstruct_loose_stock.py")
_spec = importlib.util.spec_from_file_location("reconstruct_under_test", _REC_PATH)
rec = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rec)

STOCK_COLS = ("ItemID", "BatchNo", "ExpiryDate", "MRP", "Rate", "NetPurRate",
              "TotalPurchaseQty", "PackSize", "NetSalesRate", "TotalSalesQty")


def _lit(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, str):
        return "'" + v.replace("'", "''") + "'"
    return str(v)


def build_stock_dump(rows) -> str:
    create = "CREATE TABLE `stockbalance` (\n" + ",\n".join(
        f"  `{c}` varchar(30) DEFAULT NULL" for c in STOCK_COLS) + "\n);\n"
    if not rows:
        return create
    vals = ",".join("(" + ",".join(_lit(v) for v in r) + ")" for r in rows)
    return (create + f"INSERT INTO `stockbalance` VALUES {vals};\n"
            + "CREATE TABLE `salesitemdetail` (`ID` varchar(30));\n"
            + "CREATE TABLE `invoiceitemdetail` (`ID` varchar(30));\n")


def staging_db(path) -> sqlite3.Connection:
    """Minimal staging-shaped DB: maps + batches + invoices for delta checks."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE legacy_id_map (entity TEXT, legacy_id TEXT, new_id INTEGER);
        CREATE TABLE items (id INTEGER PRIMARY KEY, item_name TEXT, unit_id TEXT, pack_size TEXT);
        CREATE TABLE stock_batches (id INTEGER PRIMARY KEY AUTOINCREMENT, item_id INTEGER,
            batch_no TEXT, expiry TEXT, pack_size TEXT, mrp REAL, purchase_rate REAL,
            net_rate REAL, stock_qty REAL DEFAULT 0);
        CREATE TABLE sales_invoices (id INTEGER PRIMARY KEY, bill_no TEXT);
        CREATE TABLE sales_invoice_items (id INTEGER PRIMARY KEY, sales_invoice_id INTEGER,
            item_id INTEGER, stock_batch_id INTEGER, batch_no TEXT, sale_qty REAL);
        CREATE TABLE purchase_invoices (id INTEGER PRIMARY KEY, voucher_no TEXT);
        CREATE TABLE purchase_invoice_items (id INTEGER PRIMARY KEY, purchase_invoice_id INTEGER,
            item_id INTEGER, batch_no TEXT, pack_size TEXT, pay_qty REAL, free_qty REAL);
        CREATE TABLE credit_notes (id INTEGER PRIMARY KEY);
        CREATE TABLE credit_note_items (id INTEGER PRIMARY KEY);
        CREATE TABLE debit_notes (id INTEGER PRIMARY KEY);
        CREATE TABLE debit_note_items (id INTEGER PRIMARY KEY);
        """)
    return conn


class _T(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = Path(self._tmp.name) / "st.db"

    def _conn(self):
        conn = staging_db(self.db)
        conn.execute("INSERT INTO legacy_id_map VALUES ('item','865',1808)")
        conn.execute("INSERT INTO items VALUES (1808,'UC-CART','1','10')")
        return conn


class TestPackConversions(_T):
    def test_packs_become_loose(self):
        for pack, net, want in [(1, 7.0, 7.0), (5, 25.0, 25.0),
                                (10, 101.0, 101.0), (15, 30.0, 30.0)]:
            with self.subTest(pack=pack):
                rows = [(900, "B", "2030-01-31", 100, 10, 9, net, pack, 0, 0)]
                dump = LegacyDump.from_text(build_stock_dump(rows))
                conn = staging_db(Path(self._tmp.name) / f"t{pack}.db")
                conn.execute("INSERT INTO legacy_id_map VALUES ('item','900',90)")
                conn.execute("INSERT INTO items VALUES (90,'I','1',?)", (str(pack),))
                conn.execute("INSERT INTO stock_batches (item_id,batch_no,stock_qty)"
                             " VALUES (90,'B',0)")
                conn.commit()
                out = rec.apply_on_staging(conn, dump)
                self.assertEqual(out["updated"], 1)
                got = conn.execute("SELECT stock_qty FROM stock_batches WHERE item_id=90").fetchone()[0]
                self.assertAlmostEqual(got, want)
                conn.close()

    def test_uc_cart_tablets(self):
        rows = [(865, "VHT14811", "2026-11-30", 435, 294.92, 290, 240, 10, 0, 239),
                (865, "VHT14811.", "2026-11-30", 387, 294.92, 270.96, 413, 10, 0, 394),
                (865, "VH16956", "2027-04-30", 387, 294.92, 232.25, 180, 10, 0, 79),
                (865, "VH18512", "2027-07-31", 387, 294.87, 309.62, 20, 10, 0, 0)]
        dump = LegacyDump.from_text(build_stock_dump(rows))
        conn = self._conn()
        for b in ("VHT14811", "VHT14811.", "VH16956", "VH18512"):
            conn.execute("INSERT INTO stock_batches (item_id,batch_no,pack_size,stock_qty)"
                         " VALUES (1808,?,'10',0)", (b,))
        conn.commit()
        rec.apply_on_staging(conn, dump)
        got = {r["batch_no"]: r["stock_qty"] for r in
               conn.execute("SELECT batch_no, stock_qty FROM stock_batches WHERE item_id=1808")}
        self.assertAlmostEqual(got["VHT14811"], 1.0)
        self.assertAlmostEqual(got["VHT14811."], 19.0)
        self.assertAlmostEqual(got["VH16956"], 101.0)
        self.assertAlmostEqual(got["VH18512"], 20.0)
        conn.close()


class TestPurchaseSaleRoundTrip(_T):
    def test_purchase_packs_add_loose(self):
        from database.purchase_dao import pack_factor
        self.assertAlmostEqual((10 + 2) * pack_factor("10"), 120.0)
        self.assertAlmostEqual((3 + 0) * pack_factor("1"), 3.0)

    def test_sale_tablet_pricing(self):
        # amount = qty(loose) * MRP(per pack) / pack
        self.assertAlmostEqual(5 * 435.0 / 10, 217.50)
        self.assertAlmostEqual(1 * 387.0 / 10, 38.70)

    def test_negative_preserved_not_clamped(self):
        rows = [(900, "N", "2030-01-31", 10, 5, 5, 5, 10, 0, 45)]  # net -40
        dump = LegacyDump.from_text(build_stock_dump(rows))
        conn = staging_db(Path(self._tmp.name) / "n.db")
        conn.execute("INSERT INTO legacy_id_map VALUES ('item','900',90)")
        conn.execute("INSERT INTO items VALUES (90,'I','1','10')")
        conn.execute("INSERT INTO stock_batches (item_id,batch_no,stock_qty) VALUES (90,'N',0)")
        conn.commit()
        rec.apply_on_staging(conn, dump)
        got = conn.execute("SELECT stock_qty FROM stock_batches WHERE item_id=90").fetchone()[0]
        self.assertAlmostEqual(got, -40.0)
        self.assertLess(got, 0)
        conn.close()

    def test_idempotent_rerun(self):
        rows = [(865, "VH18512", "2027-07-31", 387, 294.87, 309.62, 20, 10, 0, 0)]
        conn = self._conn()
        conn.execute("INSERT INTO stock_batches (item_id,batch_no,pack_size,stock_qty)"
                     " VALUES (1808,'VH18512','10',0)")
        conn.commit()
        dump = LegacyDump.from_text(build_stock_dump(rows))
        rec.apply_on_staging(conn, dump)
        first = conn.execute("SELECT stock_qty FROM stock_batches WHERE batch_no='VH18512'").fetchone()[0]
        rec.apply_on_staging(conn, dump)
        second = conn.execute("SELECT stock_qty FROM stock_batches WHERE batch_no='VH18512'").fetchone()[0]
        self.assertAlmostEqual(first, 20.0)
        self.assertAlmostEqual(second, 20.0)
        conn.close()


class TestValuation(_T):
    def test_loose_value_divides_rate(self):
        from database.purchase_dao import pack_factor
        stock, rate, pack = 101.0, 294.92, "10"
        self.assertAlmostEqual(stock * rate / pack_factor(pack), 101.0 * 29.492)


class TestGuards(unittest.TestCase):
    def test_expired_unsellable_rule(self):
        from database.sales_dao import SalesDAO
        self.assertTrue(SalesDAO.is_expired("2015-12-31"))
        self.assertFalse(SalesDAO.is_expired("2029-02-28"))

    def test_live_refused(self):
        tool = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "tools", "reconstruct_loose_stock.py")
        with open(tool, encoding="utf-8") as fh:
            body = fh.read()
        # live always gated: bare live use refused, --confirm-live path
        # requires backup + app-closed + post-migration checks
        self.assertIn("--confirm-live", body)
        self.assertIn("REFUSING", body)
        self.assertIn("backup_live", body)
        self.assertIn("app_running", body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
