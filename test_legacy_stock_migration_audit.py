"""Audit tests for the legacy stock-balance migration tool.

Covers the pre-apply safety checks the migration audit must enforce:

* normalised batch-key collisions (item 238 ``CARE`` vs ``' CARE'``) are
  detected, the five compared metadata fields are reported, and nothing
  is merged or silently discarded;
* an unresolvable batch pack size is a hard blocking error — a divisor
  of 1 is never substituted;
* negative balances survive exactly;
* expired positive-stock batches are never offered for a new sale;
* the UC-ROSE projection is computed from ``plan_rows``, not from the
  current zero-quantity target rows.

Everything runs against throwaway SQLite databases via ``PHARMACY_DB``;
``data/pharmacy.db`` is never opened.
"""

from __future__ import annotations

import importlib.util
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database.legacy_migration import LegacyDump  # noqa: E402

# The migration tool is a script, not a package module — load it by path.
_TOOL_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "tools",
    "legacy_stock_migration.py")
_spec = importlib.util.spec_from_file_location(
    "legacy_stock_migration_under_test", _TOOL_PATH)
tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tool)

STOCKBALANCE_COLUMNS = (
    "ItemID", "BatchNo", "ExpiryDate", "MRP", "Rate", "NetPurRate",
    "TotalPurchaseQty", "PackSize", "NetSalesRate", "TotalSalesQty",
)

#: Relative dates keep the expiry assertions true whenever the suite runs.
FUTURE_EXPIRY = (datetime.now() + timedelta(days=3650)).strftime("%Y-%m-%d")
PAST_EXPIRY = "2015-12-31"


def _literal(value) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    return str(value)


def build_dump(rows) -> str:
    """A minimal mysqldump-shaped stockbalance table."""
    create = "CREATE TABLE `stockbalance` (\n" + ",\n".join(
        f"  `{name}` varchar(30) DEFAULT NULL"
        for name in STOCKBALANCE_COLUMNS) + "\n);\n"
    values = ",".join(
        "(" + ",".join(_literal(v) for v in row) + ")" for row in rows)
    return create + f"INSERT INTO `stockbalance` VALUES {values};\n"


def target_db(path) -> sqlite3.Connection:
    """A stub of the target schema: only what ``build_plan`` reads."""
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
        """)
    return conn


def map_items(conn, mapping) -> None:
    """``mapping``: {legacy item id: (target item id, item master pack size)}"""
    for legacy_id, (target_id, pack) in mapping.items():
        conn.execute(
            "INSERT INTO legacy_id_map (entity, legacy_id, new_id)"
            " VALUES ('item', ?, ?)", (str(legacy_id), target_id))
        conn.execute(
            "INSERT INTO items (id, item_name, unit_id, pack_size)"
            " VALUES (?, ?, '1', ?)", (target_id, f"ITEM-{target_id}", pack))
    conn.commit()


class _PlanTest(unittest.TestCase):
    """Shared plumbing: synthetic dump + stub target database."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = Path(self._tmp.name) / "target.db"

    def plan(self, source_rows, mapping):
        """Build a plan over a synthetic source and a stub target.

        Returns ``(plan, conn)``; the caller closes ``conn``.
        """
        dump = LegacyDump.from_text(build_dump(source_rows))
        conn = target_db(self.db_path)
        map_items(conn, mapping)
        return tool.build_plan(dump, conn), conn

    def plan_with_conn(self, source_rows, mapping):
        conn = target_db(self.db_path)
        map_items(conn, mapping)
        dump = LegacyDump.from_text(build_dump(source_rows))
        return tool.build_plan(dump, conn), conn, dump


# ══════════════════════════════════════════════════════════════════════
# 1. Normalised batch-key collisions
# ══════════════════════════════════════════════════════════════════════

class TestNormalizedBatchCollisions(_PlanTest):
    """``CARE`` and ``' CARE'`` are different strings, one key."""

    #: legacy item 238 exactly as the real dump holds it: the two rows
    #: disagree on expiry and on net rate.
    CARE_ROWS = [
        (238, "CARE", "2017-05-31", 125, 52, 52, 112, 1, 125, 112),
        (238, " CARE", "2018-05-31", 125, 52, 50, 21, 1, 124.99, 21),
        (238, "OTHER", "2030-05-31", 10, 5, 5, 60, 6, 10, 0),
    ]
    MAPPING = {238: (1, "")}

    def test_collision_is_detected_and_blocks_the_plan(self):
        plan, conn = self.plan(self.CARE_ROWS, self.MAPPING)
        try:
            self.assertTrue(plan.blocked)
            self.assertEqual(len(plan.normalized_collisions), 1)
            kinds = {b["kind"] for b in plan.blockers}
            self.assertIn("normalized_batch_collision", kinds)
        finally:
            conn.close()

    def test_both_raw_variants_are_recorded(self):
        plan, conn = self.plan(self.CARE_ROWS, self.MAPPING)
        try:
            collision = plan.normalized_collisions[0]
            self.assertEqual(collision["raw_variants"], [" CARE", "CARE"])
            self.assertEqual(collision["normalized_batch_no"], "CARE")
            self.assertEqual(collision["legacy_items"], ["238"])
        finally:
            conn.close()

    def test_conflicting_and_agreeing_fields_are_both_reported(self):
        plan, conn = self.plan(self.CARE_ROWS, self.MAPPING)
        try:
            collision = plan.normalized_collisions[0]
            # expiry 2017 vs 2018 and net rate 52 vs 50 disagree.
            self.assertEqual(
                sorted(collision["conflicting_fields"]),
                ["expiry", "net_rate"])
            self.assertEqual(
                sorted(collision["agreeing_fields"]),
                ["mrp", "pack_size", "purchase_rate"])
            self.assertTrue(collision["metadata_conflict"])
            # The metadata itself is carried, not summarised away.
            self.assertEqual(
                collision["metadata_by_variant"][" CARE"]["expiry"],
                "2018-05-31")
            self.assertEqual(
                collision["metadata_by_variant"]["CARE"]["net_rate"], 52.0)
        finally:
            conn.close()

    def test_colliding_key_is_withheld_not_merged(self):
        plan, conn = self.plan(self.CARE_ROWS, self.MAPPING)
        try:
            keys = {(r["target_item"], r["batch_no"]) for r in plan.rows}
            self.assertNotIn((1, "CARE"), keys)
            withheld = {(w["target_item"], w["batch_no"])
                        for w in plan.withheld_keys}
            self.assertIn((1, "CARE"), withheld)
        finally:
            conn.close()

    def test_unrelated_keys_still_plan_normally(self):
        plan, conn = self.plan(self.CARE_ROWS, self.MAPPING)
        try:
            rows = {r["batch_no"]: r for r in plan.rows}
            self.assertIn("OTHER", rows)
            self.assertAlmostEqual(rows["OTHER"]["stock_qty"], 10.0)
        finally:
            conn.close()

    def test_identical_metadata_still_blocks_but_is_labelled(self):
        """Same metadata is still withheld — just reported as identical."""
        rows = [
            (238, "CARE", "2017-05-31", 125, 52, 52, 100, 1, 125, 0),
            (238, " CARE", "2017-05-31", 125, 52, 52, 40, 1, 125, 0),
        ]
        plan, conn = self.plan(rows, self.MAPPING)
        try:
            collision = plan.normalized_collisions[0]
            self.assertFalse(collision["metadata_conflict"])
            self.assertEqual(collision["conflicting_fields"], [])
            self.assertTrue(plan.blocked)
        finally:
            conn.close()


# ══════════════════════════════════════════════════════════════════════
# 2. Internal-whitespace collisions
# ══════════════════════════════════════════════════════════════════════

class TestInternalWhitespaceCollisions(_PlanTest):
    """The dump spreads one batch over spacing runs: 'CARE 1' / 'CARE  1'."""

    ROWS = [
        (351, "CARE 1", "2027-05-31", 125, 52, 52, 30, 1, 125, 0),
        (351, "CARE  1", "2028-05-31", 125, 52, 51, 20, 1, 125, 0),
        (351, "CARE   1", "2029-05-31", 125, 52, 50, 10, 1, 125, 0),
        (351, "OTHER", "2030-05-31", 10, 5, 5, 60, 6, 10, 0),
    ]
    MAPPING = {351: (9, "")}

    def test_internal_spacing_variants_collide_and_block(self):
        plan, conn = self.plan(self.ROWS, self.MAPPING)
        try:
            self.assertTrue(plan.blocked)
            self.assertEqual(len(plan.normalized_collisions), 1)
            collision = plan.normalized_collisions[0]
            self.assertEqual(
                sorted(collision["raw_variants"]),
                sorted(["CARE 1", "CARE  1", "CARE   1"]))
            self.assertEqual(collision["normalized_batch_no"], "CARE 1")
            self.assertEqual(collision["collision_variant"],
                             "internal whitespace")
            self.assertEqual(sorted(collision["conflicting_fields"]),
                             ["expiry", "net_rate"])
        finally:
            conn.close()

    def test_every_spacing_variant_is_withheld(self):
        plan, conn = self.plan(self.ROWS, self.MAPPING)
        try:
            withheld = {w["batch_no"] for w in plan.withheld_keys}
            self.assertEqual(withheld, {"CARE 1", "CARE  1", "CARE   1"})
            self.assertNotIn("OTHER", withheld)
        finally:
            conn.close()

    def test_a_lone_spaced_batch_keeps_its_spacing(self):
        """Detection must not rewrite a batch number that is not colliding."""
        rows = [(600, "ST16  2195", "2030-01-31", 10, 5, 5, 60, 6, 10, 0)]
        plan, conn = self.plan(rows, {600: (7, "")})
        try:
            self.assertFalse(plan.blocked)
            self.assertEqual([r["batch_no"] for r in plan.rows],
                             ["ST16  2195"])
            self.assertAlmostEqual(plan.rows[0]["stock_qty"], 10.0)
        finally:
            conn.close()

    def test_loose_key_collapses_and_strips(self):
        self.assertEqual(tool.loose_batch_no("  CARE   1 "), "CARE 1")
        self.assertEqual(tool.loose_batch_no("CARE 1"), "CARE 1")
        self.assertEqual(tool.loose_batch_no("\tCARE\n1"), "CARE 1")


# ══════════════════════════════════════════════════════════════════════
# 3. Unresolved pack size is a hard blocking error
# ══════════════════════════════════════════════════════════════════════

class TestMissingPackSize(_PlanTest):

    #: PackSize 0, item master has no pack size, no existing target row.
    ROWS = [
        (10, "NP-1", "2030-01-31", 10, 5, 5, 100, 0, 10, 0),
        (10, "OK-1", "2030-01-31", 10, 5, 5, 60, 6, 10, 0),
    ]
    MAPPING = {10: (2, "")}

    def test_unresolved_pack_size_blocks(self):
        plan, conn = self.plan(self.ROWS, self.MAPPING)
        try:
            self.assertTrue(plan.blocked)
            self.assertEqual(len(plan.missing_pack_size), 1)
            self.assertIn("unresolved_pack_size",
                          {b["kind"] for b in plan.blockers})
        finally:
            conn.close()

    def test_divisor_of_one_is_never_substituted(self):
        plan, conn = self.plan(self.ROWS, self.MAPPING)
        try:
            # 100 loose units must NOT appear as 100 packs.
            self.assertNotIn((2, "NP-1"),
                             {(r["target_item"], r["batch_no"])
                              for r in plan.rows})
            self.assertFalse(
                [r for r in plan.rows if r["stock_qty"] == 100.0],
                "a missing pack size must not be divided by 1")
        finally:
            conn.close()

    def test_missing_entry_records_where_it_looked(self):
        plan, conn = self.plan(self.ROWS, self.MAPPING)
        try:
            missing = plan.missing_pack_size[0]
            self.assertEqual(missing["batch_no"], "NP-1")
            self.assertEqual(missing["net_loose"], 100.0)
            self.assertEqual(missing["item_master_pack_size"], "")
            self.assertEqual(missing["existing_target_pack_size"], "")
            self.assertFalse(missing["net_loose_is_zero"])
        finally:
            conn.close()

    def test_pack_size_falls_back_to_the_item_master(self):
        """A real item master pack size resolves it — no block."""
        plan, conn = self.plan(self.ROWS, {10: (2, "10")})
        try:
            self.assertFalse(plan.blocked)
            rows = {r["batch_no"]: r for r in plan.rows}
            self.assertAlmostEqual(rows["NP-1"]["stock_qty"], 10.0)
            self.assertEqual(rows["NP-1"]["pack_size"], "10")
        finally:
            conn.close()

    def test_pack_size_falls_back_to_the_existing_target_row(self):
        conn = target_db(self.db_path)
        map_items(conn, {10: (2, "")})
        conn.execute(
            "INSERT INTO stock_batches (item_id, batch_no, expiry,"
            " pack_size, mrp, purchase_rate, net_rate, stock_qty)"
            " VALUES (2, 'NP-1', '2030-01-31', '5', 10, 5, 5, 0)")
        conn.commit()
        dump = LegacyDump.from_text(build_dump(self.ROWS))
        try:
            plan = tool.build_plan(dump, conn)
            self.assertFalse(plan.blocked)
            rows = {r["batch_no"]: r for r in plan.rows}
            self.assertAlmostEqual(rows["NP-1"]["stock_qty"], 20.0)
        finally:
            conn.close()


# ══════════════════════════════════════════════════════════════════════
# 4. Negative balances
# ══════════════════════════════════════════════════════════════════════

class TestNegativeBalances(_PlanTest):

    ROWS = [
        # purchase 5, sales 45 -> net -40 loose -> -4 packs at pack 10
        (11, "NEG-1", "2030-01-31", 10, 5, 5, 5, 10, 10, 45),
        (11, "POS-1", "2030-01-31", 10, 5, 5, 70, 10, 10, 10),
    ]
    MAPPING = {11: (3, "")}

    def test_negative_net_is_preserved_exactly(self):
        plan, conn = self.plan(self.ROWS, self.MAPPING)
        try:
            rows = {r["batch_no"]: r for r in plan.rows}
            self.assertAlmostEqual(rows["NEG-1"]["stock_qty"], -4.0)
            self.assertEqual(rows["NEG-1"]["net_loose"], -40.0)
        finally:
            conn.close()

    def test_negative_is_recorded_and_not_clamped_to_zero(self):
        plan, conn = self.plan(self.ROWS, self.MAPPING)
        try:
            self.assertEqual(len(plan.negatives), 1)
            self.assertEqual(plan.negatives[0]["batch_no"], "NEG-1")
            self.assertEqual(plan.negatives[0]["stock_qty"], -4.0)
        finally:
            conn.close()

    def test_negative_does_not_block(self):
        plan, conn = self.plan(self.ROWS, self.MAPPING)
        try:
            self.assertFalse(plan.blocked)
        finally:
            conn.close()

    def test_negatives_are_counted_separately_from_zero_and_positive(self):
        plan, conn = self.plan(self.ROWS, self.MAPPING)
        try:
            self.assertEqual(plan.positives, 1)
            self.assertEqual(plan.zeros, 0)
            self.assertEqual(len(plan.negatives), 1)
        finally:
            conn.close()


# ══════════════════════════════════════════════════════════════════════
# 5. Expired positive-stock batches
# ══════════════════════════════════════════════════════════════════════

class TestExpiredBatches(_PlanTest):

    ROWS = [
        # item 832 is the UC-ROSE legacy id the trace reports on.
        (832, "FUTURE", FUTURE_EXPIRY, 100, 10, 9, 100, 10, 10, 0),
        (832, "PAST", PAST_EXPIRY, 100, 10, 9, 50, 10, 10, 0),
        (832, "SOLD-OUT", FUTURE_EXPIRY, 100, 10, 9, 30, 10, 10, 30),
    ]
    MAPPING = {832: (5, "")}

    def test_expired_batch_with_stock_is_planned_but_not_sellable(self):
        plan, conn = self.plan(self.ROWS, self.MAPPING)
        try:
            rows = {r["batch_no"]: r for r in plan.rows}
            self.assertAlmostEqual(rows["PAST"]["stock_qty"], 5.0)
            self.assertTrue(rows["PAST"]["expired"])
            self.assertFalse(rows["FUTURE"]["expired"])
        finally:
            conn.close()

    def test_uc_rose_projection_excludes_expired_stock(self):
        plan, conn, dump = self.plan_with_conn(self.ROWS, self.MAPPING)
        try:
            trace = tool.trace_uc_rose(dump, conn, plan)
            offered = {b["batch_no"]
                       for b in trace["projected_counter_sale_rows"]}
            self.assertEqual(offered, {"FUTURE"})
            expired = {b["batch_no"]
                       for b in trace["projected_expired_with_stock"]}
            self.assertEqual(expired, {"PAST"})
        finally:
            conn.close()

    def test_empty_expiry_is_not_treated_as_expired(self):
        self.assertFalse(tool.is_expired(""))
        self.assertFalse(tool.is_expired(None))

    def test_tool_expiry_rule_matches_the_sales_dao(self):
        """The report's 'what Counter Sale offers' must use the app's rule."""
        from database.sales_dao import SalesDAO
        for value in ("2015-12-31", FUTURE_EXPIRY, "01/20", "12/99", "",
                      None, "0000-00-00", "not-a-date"):
            self.assertEqual(
                tool.is_expired(value), SalesDAO.is_expired(value or ""),
                f"expiry rule differs for {value!r}")


# ══════════════════════════════════════════════════════════════════════
# 6. Projected batch counts come from plan_rows
# ══════════════════════════════════════════════════════════════════════

class TestProjectedBatchCounts(_PlanTest):

    ROWS = [
        (832, "FUTURE", FUTURE_EXPIRY, 100, 10, 9, 100, 10, 10, 0),
        (832, "PAST", PAST_EXPIRY, 100, 10, 9, 50, 10, 10, 0),
        (832, "EMPTY", FUTURE_EXPIRY, 100, 10, 9, 40, 10, 10, 40),
    ]
    MAPPING = {832: (5, "")}

    def test_projection_is_read_off_plan_rows(self):
        plan, conn, dump = self.plan_with_conn(self.ROWS, self.MAPPING)
        try:
            trace = tool.trace_uc_rose(dump, conn, plan)
            self.assertEqual(len(trace["plan_rows"]), 3)
            self.assertEqual(len(trace["projected_batches"]), 3)
            self.assertEqual(len(trace["projected_positive_batches"]), 2)
            self.assertEqual(len(trace["projected_counter_sale_rows"]), 1)
        finally:
            conn.close()

    def test_target_rows_are_zero_so_the_projection_cannot_use_them(self):
        """The regression this fixes: target rows are all zero before apply."""
        plan, conn, dump = self.plan_with_conn(self.ROWS, self.MAPPING)
        try:
            trace = tool.trace_uc_rose(dump, conn, plan)
            self.assertEqual(trace["current_counter_sale_rows"], [])
            self.assertEqual(trace["current_positive_batches"], [])
            self.assertNotEqual(
                len(trace["projected_counter_sale_rows"]),
                len(trace["current_counter_sale_rows"]))
        finally:
            conn.close()

    def test_projection_tracks_stock_quantities(self):
        plan, conn, dump = self.plan_with_conn(self.ROWS, self.MAPPING)
        try:
            trace = tool.trace_uc_rose(dump, conn, plan)
            by_batch = {b["batch_no"]: b for b in trace["projected_batches"]}
            self.assertAlmostEqual(by_batch["FUTURE"]["stock_qty"], 10.0)
            self.assertAlmostEqual(by_batch["PAST"]["stock_qty"], 5.0)
            self.assertAlmostEqual(by_batch["EMPTY"]["stock_qty"], 0.0)
        finally:
            conn.close()


# ══════════════════════════════════════════════════════════════════════
# 7. Source-to-target mapping partition
# ══════════════════════════════════════════════════════════════════════

class TestMappingPartition(_PlanTest):

    ROWS = [
        (238, "CARE", "2017-05-31", 125, 52, 52, 112, 1, 125, 112),
        (238, " CARE", "2018-05-31", 125, 52, 50, 21, 1, 124.99, 21),
        (238, "GOOD", "2030-05-31", 10, 5, 5, 60, 6, 10, 0),
    ]
    MAPPING = {238: (1, "")}

    def test_every_source_key_is_either_mapped_or_withheld(self):
        plan, conn = self.plan(self.ROWS, self.MAPPING)
        try:
            result = tool.verify(conn, plan)
            self.assertTrue(result["mapping_partition_ok"])
            self.assertEqual(result["source_keys"], plan.source_keys)
            self.assertEqual(
                result["mapped_keys"] + result["withheld_keys"],
                result["source_keys"])
            self.assertEqual(result["duplicate_mapped_keys"], 0)
            self.assertEqual(result["mapped_withheld_overlap"], 0)
        finally:
            conn.close()

    def test_withheld_keys_are_never_counted_as_verified(self):
        plan, conn = self.plan(self.ROWS, self.MAPPING)
        try:
            result = tool.verify(conn, plan)
            # The withheld CARE key was never claimed as mapped, so it can
            # never appear as a missing batch. The mapped GOOD row is the
            # only one the target is checked for, and this stub target has
            # no batches at all.
            missing_batches = {m["batch"] for m in result["missing_sample"]}
            self.assertNotIn("CARE", missing_batches)
            self.assertEqual(missing_batches, {"GOOD"})
            self.assertEqual(result["mismatches"], 0)
        finally:
            conn.close()


# ══════════════════════════════════════════════════════════════════════
# 8. --apply refuses a blocked plan
# ══════════════════════════════════════════════════════════════════════

class TestApplyRefusesBlockedPlan(_PlanTest):

    ROWS = [
        (238, "CARE", "2017-05-31", 125, 52, 52, 112, 1, 125, 112),
        (238, " CARE", "2018-05-31", 125, 52, 50, 21, 1, 124.99, 21),
    ]

    def test_apply_returns_refusal_and_writes_nothing(self):
        conn = target_db(self.db_path)
        map_items(conn, {238: (1, "")})
        conn.close()

        dump_path = Path(self._tmp.name) / "source.sql"
        dump_path.write_text(build_dump(self.ROWS), encoding="utf-8")

        reports = Path(self._tmp.name) / "reports"
        reports.mkdir()

        before = sqlite3.connect(self.db_path)
        try:
            batches_before = before.execute(
                "SELECT COUNT(*) FROM stock_batches").fetchone()[0]
        finally:
            before.close()

        rc = None
        with mock.patch.object(tool, "ROOT", Path(self._tmp.name)), \
                mock.patch.object(tool, "REPORT_JSON",
                                  reports / "plan.json"), \
                mock.patch.object(tool, "REPORT_MD", reports / "plan.md"):
            rc = tool.main(["--apply", "--db", str(self.db_path),
                            "--source", str(dump_path)])

        self.assertEqual(rc, 5, "a blocked plan must refuse --apply")

        after = sqlite3.connect(self.db_path)
        try:
            batches_after = after.execute(
                "SELECT COUNT(*) FROM stock_batches").fetchone()[0]
        finally:
            after.close()
        self.assertEqual(batches_before, batches_after,
                         "nothing may be written when the plan is blocked")

    def test_report_mode_exits_non_zero_when_blocked(self):
        conn = target_db(self.db_path)
        map_items(conn, {238: (1, "")})
        conn.close()

        dump_path = Path(self._tmp.name) / "source.sql"
        dump_path.write_text(build_dump(self.ROWS), encoding="utf-8")

        reports = Path(self._tmp.name) / "reports"
        reports.mkdir()

        with mock.patch.object(tool, "ROOT", Path(self._tmp.name)), \
                mock.patch.object(tool, "REPORT_JSON",
                                  reports / "plan.json"), \
                mock.patch.object(tool, "REPORT_MD", reports / "plan.md"):
            rc = tool.main(["--report", "--db", str(self.db_path),
                            "--source", str(dump_path)])

        self.assertEqual(rc, 6)
        self.assertTrue((reports / "plan.md").exists())
        body = (reports / "plan.md").read_text(encoding="utf-8")
        self.assertIn("BLOCKING", body)
        self.assertIn("CARE", body)


# ══════════════════════════════════════════════════════════════════════
# 9. Counter Sale must not offer expired batches
# ══════════════════════════════════════════════════════════════════════

class TestCounterSaleExpiry(_PlanTest):
    """End-to-end against the real schema via ``init_database``."""

    def setUp(self):
        super().setUp()
        self._db = Path(self._tmp.name) / "app.db"
        self._env = mock.patch.dict(
            os.environ, {"PHARMACY_DB": str(self._db)})
        self._env.start()
        self.addCleanup(self._env.stop)

        from database.connection import get_connection, init_database
        init_database()
        self.get_connection = get_connection

        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO items (id, item_name, unit_id, pack_size)"
                " VALUES (1, 'BANDAGE', NULL, '10')")
            conn.execute(
                "INSERT INTO stock_batches (id, item_id, batch_no, expiry,"
                " pack_size, mrp, purchase_rate, net_rate, stock_qty)"
                " VALUES (1, 1, 'EXPIRED', ?, '10', 100, 50, 50, 10)",
                (PAST_EXPIRY,))
            conn.execute(
                "INSERT INTO stock_batches (id, item_id, batch_no, expiry,"
                " pack_size, mrp, purchase_rate, net_rate, stock_qty)"
                " VALUES (2, 1, 'GOOD', ?, '10', 100, 50, 50, 5)",
                (FUTURE_EXPIRY,))
            conn.execute(
                "INSERT INTO stock_batches (id, item_id, batch_no, expiry,"
                " pack_size, mrp, purchase_rate, net_rate, stock_qty)"
                " VALUES (3, 1, 'ZERO', ?, '10', 100, 50, 50, 0)",
                (FUTURE_EXPIRY,))
            conn.commit()
        finally:
            conn.close()

    def test_expired_batches_are_not_offered(self):
        from database.sales_dao import SalesDAO
        offered = SalesDAO.get_stock_batches_for_item(1)
        self.assertEqual([b["batch_no"] for b in offered], ["GOOD"])

    def test_positive_stock_alone_is_not_enough(self):
        from database.sales_dao import SalesDAO
        offered = SalesDAO.get_stock_batches_for_item(1)
        self.assertNotIn("EXPIRED", [b["batch_no"] for b in offered])
        self.assertNotIn("ZERO", [b["batch_no"] for b in offered])

    def test_expired_batch_is_still_visible_to_stock_reporting(self):
        """Excluding it from sales must not hide it from write-off."""
        from database.sales_dao import SalesDAO
        conn = self.get_connection()
        try:
            row = conn.execute(
                "SELECT stock_qty FROM stock_batches WHERE id = 1"
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(row["stock_qty"], 10)
        self.assertTrue(SalesDAO.is_expired(PAST_EXPIRY))

    def test_posting_an_expired_batch_is_rejected(self):
        from database.sales_dao import SalesDAO
        with self.assertRaises(ValueError) as ctx:
            SalesDAO.insert_invoice(
                bill_no="CS-TEST", sale_date="2026-01-01", sale_time="",
                sale_type="Cash", customer_id=None, patient_name="",
                doctor_id=None, discount=0, paid_amount=100,
                total_amount=100, round_off=0, net_amount=100, remarks="",
                items=[{
                    "item_id": 1, "stock_batch_id": 1, "pack_size": "10",
                    "location": "", "batch_no": "EXPIRED",
                    "expiry": PAST_EXPIRY, "mrp": 100, "sale_qty": 1,
                    "discount_amount": 0, "amount": 100,
                }],
            )
        self.assertIn("expired", str(ctx.exception).lower())

    def test_posting_an_unexpired_batch_is_not_blocked_by_the_guard(self):
        """The guard must reject expiry, not everything."""
        from database.sales_dao import SalesDAO
        conn = self.get_connection()
        try:
            row = conn.execute(
                "SELECT stock_qty FROM stock_batches WHERE id = 2"
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(row["stock_qty"], 5)
        self.assertFalse(SalesDAO.is_expired(FUTURE_EXPIRY))


if __name__ == "__main__":
    unittest.main(verbosity=2)
