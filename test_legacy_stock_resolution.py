"""Staging-only tests for the 8 collision-group resolution.

Covers owner requirements without touching any real database:

* all eight real collision groups (incl. target 1199) resolve to distinct
  identities with exact provenance and independent quantities;
* repeatability (same inputs -> same aliases);
* metadata preservation (expiry / pack / MRP / purchase / net);
* historical reference integrity (238 merged sales split via VhID;
  already-distinct groups need zero moves);
* Counter Sale visible distinction (display strings visibly distinct);
* blocked fallback when pack size cannot be resolved.

Everything runs against throwaway SQLite files; ``data/pharmacy.db`` and
the source dump are never opened.
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

from database.legacy_migration import LegacyDump  # noqa: E402

_TOOL_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "tools",
    "legacy_stock_resolution.py")
_spec = importlib.util.spec_from_file_location(
    "legacy_stock_resolution_under_test", _TOOL_PATH)
res = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(res)

STOCK_COLS = (
    "ItemID", "BatchNo", "ExpiryDate", "MRP", "Rate", "NetPurRate",
    "TotalPurchaseQty", "PackSize", "NetSalesRate", "TotalSalesQty",
)
SALES_COLS = ("ID", "VhID", "ItemID", "PackSize", "BatchNo", "ExpiryDate",
              "MRP", "SalesQty", "SalesRate", "NetSalesRate", "DiscEntered",
              "DiscPer", "DiscAmt", "Amount")
PURCH_COLS = ("ID", "VhID", "ItemID", "BatchNo", "PackSize", "ExpiryDate",
              "PayPackQty", "FreePackQty", "RcvdPackQty", "TotalLooseQty",
              "Rate", "MRP", "DiscEntered", "DiscPer", "DiscAmt", "Amount",
              "TaxPer", "TaxAmt", "PurRate", "NetRate", "SaleRate", "ChallanID")


def _literal(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, str):
        return "'" + v.replace("'", "''") + "'"
    return str(v)


def _table_sql(name, cols, rows) -> str:
    create = "CREATE TABLE `" + name + "` (\n" + ",\n".join(
        f"  `{c}` varchar(30) DEFAULT NULL" for c in cols) + "\n);\n"
    if not rows:
        return create
    values = ",".join(
        "(" + ",".join(_literal(v) for v in r) + ")" for r in rows)
    return create + f"INSERT INTO `{name}` VALUES {values};\n"


def build_dump(stock_rows, sales_rows=(), purch_rows=()) -> str:
    return (_table_sql("stockbalance", STOCK_COLS, stock_rows)
            + _table_sql("salesitemdetail", SALES_COLS, sales_rows)
            + _table_sql("invoiceitemdetail", PURCH_COLS, purch_rows))


def target_db(path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE legacy_id_map (
            entity TEXT, legacy_id TEXT, new_id INTEGER);
        CREATE TABLE items (
            id INTEGER PRIMARY KEY, item_name TEXT, unit_id TEXT,
            pack_size TEXT);
        CREATE TABLE stock_batches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER, batch_no TEXT, expiry TEXT, pack_size TEXT,
            mrp REAL, purchase_rate REAL, net_rate REAL,
            stock_qty REAL DEFAULT 0);
        CREATE TABLE sales_invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT, bill_no TEXT);
        CREATE TABLE sales_invoice_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sales_invoice_id INTEGER, item_id INTEGER,
            stock_batch_id INTEGER, batch_no TEXT);
        CREATE TABLE purchase_invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT, voucher_no TEXT);
        CREATE TABLE purchase_invoice_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            purchase_invoice_id INTEGER, item_id INTEGER, batch_no TEXT);
        """)
    return conn


def map_item(conn, legacy_id, target_id, pack="") -> None:
    conn.execute(
        "INSERT INTO legacy_id_map (entity, legacy_id, new_id)"
        " VALUES ('item', ?, ?)", (str(legacy_id), target_id))
    conn.execute(
        "INSERT INTO items (id, item_name, unit_id, pack_size)"
        " VALUES (?, ?, '1', ?)", (target_id, f"ITEM-{target_id}", pack))
    conn.commit()


def add_batch(conn, item_id, batch_no, expiry="", pack="", mrp=0.0,
              prate=0.0, net=0.0) -> int:
    cur = conn.execute(
        "INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size,"
        " mrp, purchase_rate, net_rate, stock_qty)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
        (item_id, batch_no, expiry, pack, mrp, prate, net))
    conn.commit()
    return cur.lastrowid


# Real stockbalance rows for the 7 groups (exact raws + metadata).
# (ItemID, BatchNo, Expiry, MRP, Rate, NetPurRate, Purch, Pack, NetSalesRate, Sales)
GROUP_16 = [
    (16, "N 142033", "2017-05-31", 210, 72, 72, 21, 1, 0, 21),
    (16, "N  142033", "2017-05-31", 270, 72, 72, 21, 1, 0, 21),
]
GROUP_149 = [
    (149, "KR  2923", "2016-11-30", 46.5, 35.8, 37.59, 20, 10, 0, 20),
    (149, "KR 2923", "2016-11-30", 46.5, 36.49, 38.31, 125, 10, 0, 125),
]
GROUP_189 = [
    (189, "CARE UNI", "2017-05-31", 260, 95, 107.44, 7, 1, 0, 7),
    (189, "CARE  UNI", "2017-05-31", 230, 110, 110, 12, 1, 0, 3),
]
GROUP_238 = [
    (238, "CARE", "2017-05-31", 125, 52, 52, 112, 1, 125, 112),
    (238, " CARE", "2018-05-31", 125, 52, 50, 21, 1, 124.99, 21),
]
GROUP_351 = [
    (351, "CARE 1", "2017-05-31", 65, 15, 15, 2, 1, 0, 2),
    (351, "CARE  1", "2017-05-31", 55, 15, 15, 2, 1, 0, 2),
    (351, "CARE   1", "2017-05-31", 75, 15, 15, 4, 1, 0, 4),
]
GROUP_581 = [
    (581, "LA 60709", "2019-06-30", 23, 17.36, 10.95, 286, 5, 0, 286),
    (581, "LA  60709", "2019-06-30", 23, 17.36, 19.09, 105, 5, 0, 105),
]
GROUP_600 = [
    (600, "ST16 2195", "2018-09-30", 71, 50.71, 52.07, 850, 10, 0, 850),
    (600, "ST16  2195", "2018-09-30", 71, 50.71, 53.25, 616, 10, 0, 616),
]
# Target 1199 (legacy 255) shares raw signatures with 1134 but is a separate
# target item and must never merge with it.
GROUP_255 = [
    (255, "CARE  UNI", "2017-05-31", 360, 175, 175, 5, 1, 0, 5),
    (255, "CARE UNI", "2017-05-31", 415, 160, 163.25, 26, 1, 0, 8),
]

ALL_GROUPS = {
    16: (1, GROUP_16), 149: (2, GROUP_149), 189: (3, GROUP_189),
    238: (4, GROUP_238), 351: (5, GROUP_351), 581: (6, GROUP_581),
    600: (7, GROUP_600), 255: (8, GROUP_255),
}


class _ResTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = Path(self._tmp.name) / "target.db"

    def resolve(self, stock_rows, mapping, sales_rows=(), purch_rows=(),
                pre_batches=()):
        """Build stub target, pre-create batches, resolve. Returns (out, conn)."""
        dump = LegacyDump.from_text(build_dump(stock_rows, sales_rows, purch_rows))
        conn = target_db(self.db_path)
        for leg, (tgt, _pack) in mapping.items():
            map_item(conn, leg, tgt, _pack)
        for (tgt, batch, exp, pack, mrp, pr, net) in pre_batches:
            add_batch(conn, tgt, batch, exp, pack, mrp, pr, net)
        out = res.resolve_plan(dump, conn)
        return out, conn, dump


# ── 1. all eight groups resolve with distinct identities ─────────────

class TestAllSevenGroups(_ResTest):
    def _full(self):
        stock = (GROUP_16 + GROUP_149 + GROUP_189 + GROUP_238 + GROUP_351
                 + GROUP_581 + GROUP_600 + GROUP_255)
        mapping = {leg: (tgt, "") for leg, (tgt, _rows) in ALL_GROUPS.items()}
        pre = [
            (1, "N 142033", "2017-05-31", "1", 210, 72, 72),
            (1, "N  142033", "2017-05-31", "1", 270, 72, 72),
            (2, "KR  2923", "2016-11-30", "10", 46.5, 35.8, 37.59),
            (2, "KR 2923", "2016-11-30", "10", 46.5, 36.49, 38.31),
            (3, "CARE UNI", "2017-05-31", "1", 220, 110, 110),
            (3, "CARE  UNI", "2017-05-31", "1", 230, 110, 110),
            (4, "CARE", "2017-05-31", "1", 125, 52, 52),
            (5, "CARE 1", "2017-05-31", "1", 65, 15, 15),
            (5, "CARE  1", "2017-05-31", "1", 55, 15, 15),
            (5, "CARE   1", "2017-05-31", "1", 75, 15, 15),
            (6, "LA 60709", "2019-06-30", "5", 23, 17.36, 17.76),
            (6, "LA  60709", "2019-06-30", "5", 23, 17.36, 17.48),
            (7, "ST16 2195", "2018-09-30", "10", 71, 50.71, 56.8),
            (7, "ST16  2195", "2018-09-30", "10", 71, 50.71, 56.8),
            (8, "CARE  UNI", "2017-05-31", "1", 360, 175, 175),
            (8, "CARE UNI", "2020-02-29", "1", 390, 175, 175),
        ]
        return self.resolve(stock, mapping, pre_batches=pre)

    def test_all_seven_resolve(self):
        out, conn, _dump = self._full()
        try:
            self.assertEqual(len(out["groups"]), 8)
            self.assertEqual(out["resolved_groups"], 8)
            self.assertEqual(out["blocked_groups"], 0)
        finally:
            conn.close()

    def test_aliases_distinct_per_group(self):
        out, conn, _dump = self._full()
        try:
            for g in out["groups"]:
                aliases = [v["alias_batch_no"] for v in g["variants"]]
                self.assertEqual(len(aliases), len(set(aliases)),
                                 f"item {g['target_item']} aliases merged!")
                # never merges: one resolved row per raw variant
                self.assertEqual(len(aliases), len(g["raw_variants"]))
        finally:
            conn.close()

    def test_exact_originals_preserved(self):
        out, conn, _dump = self._full()
        try:
            by_item = {g["target_item"]: g for g in out["groups"]}
            # 238 keeps both exact raws
            raws_238 = {v["raw_batch_exact"] for v in by_item[4]["variants"]}
            self.assertEqual(raws_238, {"CARE", " CARE"})
            raws_351 = {v["raw_batch_exact"] for v in by_item[5]["variants"]}
            self.assertEqual(raws_351, {"CARE 1", "CARE  1", "CARE   1"})
        finally:
            conn.close()

    def test_quantities_independent(self):
        out, conn, _dump = self._full()
        try:
            by_item = {g["target_item"]: g for g in out["groups"]}
            # 189: 0 vs 9 loose -> 0 vs 9 packs
            q189 = {v["raw_batch_exact"]: v["stock_qty"]
                    for v in by_item[3]["variants"]}
            self.assertAlmostEqual(q189["CARE UNI"], 0.0)
            self.assertAlmostEqual(q189["CARE  UNI"], 9.0)
            # 238: both zero, preserved exactly
            q238 = {v["raw_batch_exact"]: v["stock_qty"]
                    for v in by_item[4]["variants"]}
            self.assertAlmostEqual(q238["CARE"], 0.0)
            self.assertAlmostEqual(q238[" CARE"], 0.0)
        finally:
            conn.close()

    def test_metadata_preserved_per_variant(self):
        out, conn, _dump = self._full()
        try:
            by_item = {g["target_item"]: g for g in out["groups"]}
            m238 = {v["raw_batch_exact"]: v for v in by_item[4]["variants"]}
            self.assertEqual(m238["CARE"]["expiry"], "2017-05-31")
            self.assertEqual(m238[" CARE"]["expiry"], "2018-05-31")
            self.assertAlmostEqual(m238["CARE"]["net_rate"], 52.0)
            self.assertAlmostEqual(m238[" CARE"]["net_rate"], 50.0)
        finally:
            conn.close()

    def test_reconciliation_counts(self):
        out, conn, _dump = self._full()
        try:
            rec = out["reconciliation"]
            self.assertEqual(rec["collision_variants_total"], 17)
            self.assertEqual(rec["collision_variants_mapped"], 17)
            self.assertEqual(rec["collision_variants_withheld"], 0)
        finally:
            conn.close()

    def test_1199_variants_and_18_pack(self):
        out, conn, _dump = self._full()
        try:
            by_item = {g["target_item"]: g for g in out["groups"]}
            self.assertIn(8, by_item)
            g = by_item[8]
            self.assertEqual(g["status"], "resolved")
            self.assertEqual(g["legacy_items"], ["255"])
            q = {v["raw_batch_exact"]: v["stock_qty"] for v in g["variants"]}
            self.assertAlmostEqual(q["CARE  UNI"], 0.0)
            self.assertAlmostEqual(q["CARE UNI"], 18.0)
            m = {v["raw_batch_exact"]: v for v in g["variants"]}
            self.assertEqual(m["CARE  UNI"]["expiry"], "2017-05-31")
            self.assertAlmostEqual(m["CARE  UNI"]["mrp"], 360.0)
            self.assertEqual(m["CARE UNI"]["expiry"], "2017-05-31")
            self.assertAlmostEqual(m["CARE UNI"]["mrp"], 415.0)
            self.assertAlmostEqual(m["CARE UNI"]["purchase_rate"], 160.0)
            self.assertAlmostEqual(m["CARE UNI"]["net_rate"], 163.25)
            # incompatible existing metadata must be flagged, not reused blindly
            self.assertTrue(m["CARE UNI"]["metadata_update_needed"])
            self.assertIn("UPDATE", m["CARE UNI"]["metadata_update_plan"])
        finally:
            conn.close()

    def test_cross_item_batches_never_merge(self):
        out, conn, _dump = self._full()
        try:
            by_item = {g["target_item"]: g for g in out["groups"]}
            g1134 = by_item[3]
            g1199 = by_item[8]
            self.assertEqual(g1134["legacy_items"], ["189"])
            self.assertEqual(g1199["legacy_items"], ["255"])
            ids1134 = {v["alias_batch_no"] for v in g1134["variants"]}
            ids1199 = {v["alias_batch_no"] for v in g1199["variants"]}
            # same alias strings may recur across items, but identities are
            # (target_item, alias) pairs — prove the pairs are disjoint
            pairs1134 = {(3, a) for a in ids1134}
            pairs1199 = {(8, a) for a in ids1199}
            self.assertTrue(pairs1134.isdisjoint(pairs1199))
        finally:
            conn.close()


# ── 2. repeatability ─────────────────────────────────────────────────

class TestRepeatability(_ResTest):
    def test_same_inputs_same_aliases(self):
        stock = GROUP_238 + GROUP_351
        mapping = {238: (4, ""), 351: (5, "")}
        pre = [(4, "CARE", "2017-05-31", "1", 125, 52, 52)]
        out1, c1, _ = self.resolve(stock, mapping, pre_batches=pre)
        # fresh stub for second run (same logical content)
        db2 = Path(self._tmp.name) / "target2.db"
        dump2 = LegacyDump.from_text(build_dump(stock))
        c2 = target_db(db2)
        for leg, (tgt, pk) in mapping.items():
            map_item(c2, leg, tgt, pk)
        for (t, b, e, p, m, pr, n) in pre:
            add_batch(c2, t, b, e, p, m, pr, n)
        out2 = res.resolve_plan(dump2, c2)
        try:
            a1 = [(g["target_item"], v["raw_batch_exact"], v["alias_batch_no"])
                  for g in out1["groups"] for v in g["variants"]]
            a2 = [(g["target_item"], v["raw_batch_exact"], v["alias_batch_no"])
                  for g in out2["groups"] for v in g["variants"]]
            self.assertEqual(a1, a2)
        finally:
            c1.close()
            c2.close()


# ── 3. historical integrity (238 merged split via VhID) ──────────────

class TestHistoricalIntegrity(_ResTest):
    def test_238_sales_split_is_deterministic(self):
        # 2 CARE + 1 ' CARE', each on its own voucher — mirrors the real
        # property (no voucher mixes variants).
        sales = [
            (101, 5001, 238, 1, "CARE", "2017-05-31", 125, 1, 125, 125, 0, 0, 0, 125),
            (102, 5002, 238, 1, "CARE", "2017-05-31", 125, 1, 125, 125, 0, 0, 0, 125),
            (103, 5003, 238, 1, " CARE", "2018-05-31", 95, 1, 95, 95, 0, 0, 0, 95),
        ]
        purch = [
            (201, 6001, 238, "CARE", 1, "2017-05-31", 0, 0, 0, 0, 52, 125, 0, 0, 0, 0, 0, 0, 52, 52, 0, None),
            (202, 6002, 238, " CARE", 1, "2018-05-31", 0, 0, 0, 0, 52, 125, 0, 0, 0, 0, 0, 0, 52, 50, 0, None),
        ]
        dump = LegacyDump.from_text(build_dump(GROUP_238, sales, purch))
        conn = target_db(self.db_path)
        map_item(conn, 238, 4, "")
        canon = add_batch(conn, 4, "CARE", "2017-05-31", "1", 125, 52, 52)
        # header mappings: legacy Vh -> new invoice
        conn.execute("INSERT INTO legacy_id_map (entity, legacy_id, new_id)"
                     " VALUES ('sale', '5001', 7001)")
        conn.execute("INSERT INTO legacy_id_map (entity, legacy_id, new_id)"
                     " VALUES ('sale', '5002', 7002)")
        conn.execute("INSERT INTO legacy_id_map (entity, legacy_id, new_id)"
                     " VALUES ('sale', '5003', 7003)")
        # target sales lines: all currently on canonical (merged state)
        for inv in (7001, 7002, 7003):
            conn.execute("INSERT INTO sales_invoices (id, bill_no) VALUES (?, ?)",
                         (inv, f"B-{inv}"))
            conn.execute("INSERT INTO sales_invoice_items"
                         " (sales_invoice_id, item_id, stock_batch_id, batch_no)"
                         " VALUES (?, 4, ?, 'CARE')", (inv, canon))
        conn.commit()
        try:
            out = res.resolve_plan(dump, conn)
            g238 = next(g for g in out["groups"] if g["target_item"] == 4)
            self.assertEqual(g238["status"], "resolved")
            self.assertEqual(g238["remap"]["sales_moves_planned"], 1)
            # already-distinct control: 351 needs no moves
        finally:
            conn.close()

    def test_distinct_groups_need_zero_moves(self):
        dump = LegacyDump.from_text(build_dump(GROUP_351))
        conn = target_db(self.db_path)
        map_item(conn, 351, 5, "")
        add_batch(conn, 5, "CARE 1", "2017-05-31", "1", 65, 15, 15)
        add_batch(conn, 5, "CARE  1", "2017-05-31", "1", 55, 15, 15)
        add_batch(conn, 5, "CARE   1", "2017-05-31", "1", 75, 15, 15)
        try:
            out = res.resolve_plan(dump, conn)
            g = next(g for g in out["groups"] if g["target_item"] == 5)
            self.assertEqual(g["remap"]["sales_moves_planned"], 0)
        finally:
            conn.close()


# ── 4. Counter Sale visible distinction ──────────────────────────────

class TestVisibleDistinction(unittest.TestCase):
    def test_all_variant_displays_distinct(self):
        all_raws = ["N 142033", "N  142033", "KR  2923", "KR  2923",
                    "CARE UNI", "CARE  UNI", "CARE", " CARE",
                    "CARE 1", "CARE  1", "CARE   1",
                    "LA 60709", "LA  60709", "ST16 2195", "ST16  2195"]
        displays = [res.display_batch_no(r) for r in all_raws]
        # within each collision group displays must differ
        for group in (["N 142033", "N  142033"], ["KR 2923", "KR  2923"],
                      ["CARE UNI", "CARE  UNI"], ["CARE", " CARE"],
                      ["CARE 1", "CARE  1", "CARE   1"],
                      ["LA 60709", "LA  60709"], ["ST16 2195", "ST16  2195"]):
            ds = [res.display_batch_no(r) for r in group]
            self.assertEqual(len(ds), len(set(ds)), f"invisible: {group}")

    def test_display_does_not_rely_on_counting_spaces(self):
        # 'CARE  1' vs 'CARE 1' must differ by more than whitespace width
        d1 = res.display_batch_no("CARE 1")
        d2 = res.display_batch_no("CARE  1")
        self.assertNotEqual(d1, d2)
        self.assertIn("[2sp]", d2)
        self.assertNotIn("[", d1.replace("[lead", "").replace("[trail", ""))

    def test_synthetic_alias_is_visible(self):
        alias = res.alias_for_surrounding_collision("CARE", " CARE")
        self.assertNotEqual(alias, "CARE")
        self.assertIn("CARE", alias)
        # Counter Sale list of aliases for 238 must be visibly two items
        self.assertNotEqual("CARE", alias)
        self.assertNotEqual(res.display_batch_no("CARE"),
                            res.display_batch_no(" CARE"))


# ── 5. durable provenance recoverability (disposable DB only) ────────

class TestProvenanceRecoverability(_ResTest):
    def test_table_reconstructs_identities_without_json(self):
        stock = GROUP_238 + GROUP_255
        mapping = {238: (4, ""), 255: (8, "")}
        pre = [(4, "CARE", "2017-05-31", "1", 125, 52, 52),
               (8, "CARE  UNI", "2017-05-31", "1", 360, 175, 175),
               (8, "CARE UNI", "2020-02-29", "1", 390, 175, 175)]
        out, conn, _dump = self.resolve(stock, mapping, pre_batches=pre)
        try:
            # persist to a separate disposable DB (simulates the future
            # migration database, not the test stub itself)
            prov_path = Path(self._tmp.name) / "prov.db"
            prov = sqlite3.connect(str(prov_path))
            try:
                n = res.write_provenance(prov, out)
                self.assertEqual(n, 4)  # 2 (238) + 2 (1199)
                expected = {(g["target_item"], v["alias_batch_no"]): v["raw_batch_exact"]
                            for g in out["groups"] for v in g["variants"]}
                # simulate JSON loss: drop all in-memory resolution data and
                # reconstruct purely from the table
                check = res.verify_provenance_reconstruction(prov, expected)
                self.assertTrue(check["ok"], f"reconstruction failed: {check}")
                rows = res.read_provenance(prov)
                self.assertEqual(len(rows), 4)
                cols = {c[1] for c in prov.execute("PRAGMA table_info(legacy_batch_resolution)")}
                for required in ("target_item_id", "alias_batch_no", "raw_batch_exact",
                                 "normalized_key", "legacy_item_id", "expiry",
                                 "pack_size", "mrp", "purchase_rate", "net_rate",
                                 "net_loose", "stock_qty", "existing_batch_id",
                                 "is_canonical", "display_label"):
                    self.assertIn(required, cols)
                # uniqueness enforced: duplicate alias rejected
                with self.assertRaises(sqlite3.IntegrityError):
                    prov.execute("INSERT INTO legacy_batch_resolution"
                                 " (target_item_id, alias_batch_no, raw_batch_exact,"
                                 " stripped_batch, normalized_key, legacy_item_id)"
                                 " VALUES (4, 'CARE', 'CARE-dup', 'CARE', 'CARE', '238')")
                # 18-pack row recoverable with exact identity
                r18 = [r for r in rows if r["target_item_id"] == 8
                       and r["raw_batch_exact"] == "CARE UNI"][0]
                self.assertAlmostEqual(r18["stock_qty"], 18.0)
                self.assertEqual(r18["expiry"], "2017-05-31")
            finally:
                prov.close()
        finally:
            conn.close()


class TestAliasRerun(_ResTest):
    def test_matching_alias_is_reused_not_blocked(self):
        # Prior run created the synthetic alias with this variant's metadata.
        out, conn, _dump = self.resolve(
            GROUP_238, {238: (4, "")},
            pre_batches=[
                (4, "CARE", "2017-05-31", "1", 125, 52, 52),
                (4, "CARE[exact=' CARE']", "2018-05-31", "1", 125, 52, 50),
            ])
        try:
            g = next(g for g in out["groups"] if g["target_item"] == 4)
            self.assertEqual(g["status"], "resolved")
            m = {v["raw_batch_exact"]: v for v in g["variants"]}
            self.assertTrue(m[" CARE"]["reuses_existing"])
        finally:
            conn.close()

    def test_conflicting_alias_stays_blocked(self):
        # An unrelated batch squatting on the alias name with different
        # metadata must still block.
        out, conn, _dump = self.resolve(
            GROUP_238, {238: (4, "")},
            pre_batches=[
                (4, "CARE", "2017-05-31", "1", 125, 52, 52),
                (4, "CARE[exact=' CARE']", "1999-01-01", "1", 999, 1, 1),
            ])
        try:
            g = next(g for g in out["groups"] if g["target_item"] == 4)
            self.assertEqual(g["status"], "blocked")
            self.assertIn("unrelated", g["block_reason"])
        finally:
            conn.close()


# ── 6. blocked fallback ──────────────────────────────────────────────

class TestBlockedFallback(_ResTest):
    def test_unresolvable_pack_stays_blocked(self):
        stock = [(900, "NP 1", "2030-01-31", 10, 5, 5, 100, 0, 10, 0),
                 (900, "NP  1", "2030-01-31", 10, 5, 5, 50, 0, 10, 0)]
        out, conn, _dump = self.resolve(stock, {900: (8, "")})
        try:
            self.assertEqual(len(out["groups"]), 1)
            g = out["groups"][0]
            self.assertEqual(g["status"], "blocked")
            self.assertIn("pack size", g["block_reason"].lower())
            self.assertEqual(out["blocked_groups"], 1)
            # nothing mapped for the blocked group
            self.assertFalse([r for r in out["resolved_rows"]
                              if r["target_item"] == 8])
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
