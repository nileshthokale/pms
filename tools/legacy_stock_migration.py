"""Legacy stock-balance -> stock_batches migration (Phases 3, 4 and 5).

Why this exists
---------------
The application database (`data/pharmacy.db`) was produced by
``database/legacy_migration.py`` with stock deferred (``--skip-stock``).  It
therefore holds 7,616 ``stock_batches`` rows that exist only so historical
sales/purchase lines can link to a batch — **every one of them has
``stock_qty = 0``**.  Counter Sale offers only batches that hold stock
**and** have not expired (``database/sales_dao.py``
``get_stock_batches_for_item``), so the batch dropdown is empty for *every*
item, not just ``UC-ROSE``.

Blocking conditions
-------------------
This is an audit tool first: it refuses to guess.  ``--apply`` is
refused outright when any of these is unresolved, and the offending keys
are withheld from the plan rather than written with an invented value.

* **normalised batch-key collisions** — two source keys claiming one
  target batch once whitespace is normalised.  Item 238 has ``'CARE'``
  and ``' CARE'`` (stripping alone merges them); the legacy data also
  spreads single batches over internal whitespace runs, e.g. ``'CARE 1'``,
  ``'CARE  1'`` and ``'CARE   1'``.  The expiry, pack size, MRP, purchase
  rate and net rate of every variant are compared and reported; nothing
  is merged and no conflicting metadata is silently dropped.  The
  whitespace-collapsed key is for *detection only* — the batch number
  written to the target keeps the source's internal spacing.
* **unresolved pack size** — when neither the source row, the existing
  target row nor the item master supplies one.  A divisor of ``1`` is
  never substituted, because that reports loose units as packs.
* **merged-id collisions** — repeated source rows for one batch that
  disagree on pack size.

Metadata drift between repeated rows for the *same* batch is reported
but does not block: the legacy table has no unique key, so those rows
legitimately sum.

This tool imports the authoritative legacy stock from the
``stockbalance`` table with the unit conversion the rest of the application
already uses.

Unit semantics (verified against the dump and trigger bodies)
-------------------------------------------------------------
- ``stockbalance.TotalPurchaseQty`` / ``TotalSalesQty`` are in **loose
  individual units** — the source triggers maintain them that way
  (``+= TotalLooseQty``, ``+= AdjustedQty``, ``+= SalesQty``).
- The target ``stock_batches.stock_qty`` is in **packs** — the posting
  engine adds ``pay_qty + free_qty``, both packs.
- Therefore::

      net_loose_units = TotalPurchaseQty - TotalSalesQty
      target_stock_qty = net_loose_units / PackSize

- ``stockadjusted`` is **already** folded into ``stockbalance`` by the
  source triggers, so adjustments are never added again here.
- Positive, zero **and negative** nets are preserved exactly.  Nothing is
  clamped and no quantity is ever invented.

The migration is idempotent: every target row is *set* to the computed
value rather than incremented, so re-running produces the same result.

Usage
-----
    # 1. read-only plan + UC-ROSE trace (writes only report files)
    python tools/legacy_stock_migration.py --report

    # 2. clone the live DB and migrate the clone
    python tools/legacy_stock_migration.py --clone-to staging/stock_stage.db
    python tools/legacy_stock_migration.py --apply --db staging/stock_stage.db
    python tools/legacy_stock_migration.py --verify --db staging/stock_stage.db

    # 3. apply to the live database (needs --confirm-production)
    python tools/legacy_stock_migration.py --apply --confirm-production
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from database.legacy_migration import LegacyDump  # noqa: E402

DEFAULT_SOURCE = ROOT / "PharmaWinner202610051955.sql"
DEFAULT_DB = ROOT / "data" / "pharmacy.db"
REPORT_JSON = ROOT / "migration_backups" / "phase3_stock_migration.json"
REPORT_MD = ROOT / "migration_backups" / "phase3_stock_migration.md"

UC_ROSE_LEGACY_ID = 832


# ── helpers ──────────────────────────────────────────────────────────────

def num(value) -> float:
    """Source value -> float; None/blank/unparseable become 0.0."""
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def text(value) -> str:
    return "" if value is None else str(value).strip()


def loose_batch_no(value) -> str:
    """Whitespace-collapsed batch key, used **only** to detect collisions.

    The legacy data writes the same batch several ways — ``'CARE'`` and
    ``' CARE'``, or ``'CARE 1'``, ``'CARE  1'`` and ``'CARE   1'``.  Those
    are one batch spread over several rows, but they are *not* the key the
    migration writes: the target batch number keeps the source's internal
    spacing, so collapsing runs here can never silently rewrite a batch
    number.  This key exists purely to decide whether two source keys are
    claiming the same physical batch.
    """
    return " ".join(str(value).split())


def pack_text(value) -> str:
    """Render a legacy smallint pack size the way the app stores it."""
    if value is None:
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value).strip()
    return str(int(number)) if number.is_integer() else str(number)


def is_bad_date(value) -> bool:
    return not value or value in ("0000-00-00", "0001-01-01")


def clean_date(value) -> str:
    value = text(value)[:10]
    return "" if is_bad_date(value) else value


def is_expired(value) -> bool:
    """Mirror of ``SalesDAO.is_expired`` — migrated ``YYYY-MM-DD`` and
    legacy ``MM/YY`` expiry values.

    The migration report has to answer "what will Counter Sale offer
    after this runs?", and Counter Sale will not offer an expired batch,
    so the tool needs the same rule the app uses.
    ``test_legacy_stock_migration_audit`` asserts the two agree so this
    cannot drift.
    """
    value = text(value)
    if not value:
        return False
    try:
        expiry_date = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        try:
            month_text, year_text = value.split("/", 1)
            expiry_date = datetime(
                2000 + int(year_text), int(month_text), 1).date()
        except (ValueError, IndexError):
            return False
    return expiry_date < datetime.now().date()


def connect(path: Path, read_only: bool = False) -> sqlite3.Connection:
    if read_only:
        uri = "file:" + str(path).replace("\\", "/") + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=30)
    else:
        conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def sha256_file(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ── the plan ─────────────────────────────────────────────────────────────

class StockPlan:
    """Every ``stockbalance`` key resolved to a target batch and quantity.

    A plan is *blocked* when anything that would make the conversion wrong
    or ambiguous is unresolved.  A blocked plan can still be rendered as a
    report (so the problem can be reviewed) but is never applied.
    """

    def __init__(self) -> None:
        self.rows: list[dict] = []          # one per surviving target key
        self.conflicts: list[dict] = []     # merged-id collisions needing review
        self.unknown_legacy_items: list = []  # stockbalance item with no mapping
        self.missing_pack_size: list = []     # pack size could not be resolved
        self.merged_groups: list[dict] = []
        self.source_rows = 0
        self.source_keys = 0
        self.duplicate_source_rows = 0
        self.negatives: list[dict] = []
        self.positives = 0
        self.zeros = 0
        #: Keys that differ only by stray whitespace once normalised
        #: (``CARE`` vs ``' CARE'``).  Always blocking.
        self.normalized_collisions: list[dict] = []
        #: Same raw batch recorded more than once with disagreeing metadata.
        #: Reported, never silently dropped.
        self.metadata_drift: list[dict] = []
        #: Keys deliberately withheld from ``rows`` because they are
        #: unresolved (collision or missing pack size).
        self.withheld_keys: list[dict] = []

    # ── blocking ─────────────────────────────────────────────────────
    @property
    def blockers(self) -> list[dict]:
        """Everything that makes applying this plan unsafe."""
        out: list[dict] = []
        for c in self.conflicts:
            out.append({"kind": "merged_id_collision", **c})
        for c in self.normalized_collisions:
            out.append({"kind": "normalized_batch_collision", **c})
        for m in self.missing_pack_size:
            out.append({"kind": "unresolved_pack_size", **m})
        return out

    @property
    def blocked(self) -> bool:
        return bool(self.blockers)

    def as_dict(self) -> dict:
        return {
            "source_rows": self.source_rows,
            "source_keys": self.source_keys,
            "duplicate_source_rows": self.duplicate_source_rows,
            "target_keys": len(self.rows),
            "positive": self.positives,
            "zero": self.zeros,
            "negative": len(self.negatives),
            "negatives": self.negatives,
            "unknown_legacy_items": self.unknown_legacy_items,
            "missing_pack_size": self.missing_pack_size,
            "merged_groups": self.merged_groups,
            "conflicts": self.conflicts,
            "normalized_collisions": self.normalized_collisions,
            "metadata_drift": self.metadata_drift,
            "withheld_keys": self.withheld_keys,
            "blocked": self.blocked,
            "blocker_count": len(self.blockers),
        }


#: The batch metadata the audit compares when several source rows claim the
#: same target batch.  Order matters only for report readability.
COMPARED_FIELDS = ("expiry", "pack_size", "mrp", "purchase_rate", "net_rate")


def _member_fields(member: dict) -> dict:
    """The compared metadata of one source row, in report shape."""
    return {
        "expiry": member["expiry"],
        "pack_size": member["pack_size_src"],
        "mrp": member["mrp"],
        "purchase_rate": member["purchase_rate"],
        "net_rate": member["net_rate"],
    }


def _field_map(rows: list[dict]) -> dict:
    """First-seen value of every compared field, per raw batch variant."""
    out: dict[str, dict] = {}
    for member in rows:
        variant = member["raw_batch"]
        if variant in out:
            continue
        out[variant] = {
            **_member_fields(member),
            "net_loose": member["net_loose"],
            "legacy_items": sorted({member["legacy_item"]}),
        }
    return out


def _comparison(records: list[dict]) -> tuple[dict, list[str]]:
    """Per-field distinct values + the fields that disagree.

    Takes one dict per source row (or per raw batch variant); a field
    lands in ``disagreeing`` when those records hold more than one
    distinct value for it.
    """
    per_field: dict[str, list] = {}
    for field in COMPARED_FIELDS:
        values = []
        for record in records:
            value = record.get(field)
            if value not in values:
                values.append(value)
        per_field[field] = values
    disagreeing = [f for f, v in per_field.items() if len(v) > 1]
    return per_field, disagreeing


def build_plan(dump: LegacyDump, conn: sqlite3.Connection) -> StockPlan:
    """Resolve every legacy stockbalance key onto a target (item, batch).

    Nothing ambiguous is ever guessed:

    * two source batches that normalise to the same key (``CARE`` vs
      ``' CARE'``) are a **blocking** collision, and their expiry, pack
      size, MRP, purchase rate and net rate are compared so the
      disagreement is on the record rather than silently dropped;
    * a batch whose pack size cannot be resolved from the source, the
      existing target row or the item master is a **blocking** error —
      a divisor of 1 is never invented.

    Blocked keys are withheld from ``plan.rows`` entirely, so a blocked
    plan can be reported but can never write an ambiguous quantity.
    """
    plan = StockPlan()

    # legacy item id -> target item id (the migrator remapped ids)
    item_map = {
        text(r["legacy_id"]): int(r["new_id"])
        for r in conn.execute(
            "SELECT legacy_id, new_id FROM legacy_id_map WHERE entity = 'item'")
    }
    # target item pack size, the last-resort source for a pack size
    item_pack: dict[int, str] = {}
    for r in conn.execute("SELECT id, pack_size FROM items"):
        item_pack[int(r["id"])] = text(r["pack_size"])

    # existing target batches: (item_id, batch_no) -> row
    existing: dict[tuple[int, str], dict] = {}
    for r in conn.execute(
            "SELECT id, item_id, batch_no, expiry, pack_size, mrp,"
            " purchase_rate, net_rate, stock_qty FROM stock_batches"):
        existing[(int(r["item_id"]), text(r["batch_no"]))] = dict(r)

    # ── gather source rows into (target_item, batch) groups ─────────────
    groups: dict[tuple[int, str], list[dict]] = defaultdict(list)
    legacy_ids_by_group: dict[tuple[int, str], set[str]] = defaultdict(set)
    #: The *raw* batch strings that landed in each normalised group.  A
    #: group with more than one is a whitespace/case collision.
    raw_batches_by_group: dict[tuple[int, str], set[str]] = defaultdict(set)

    for row in dump.iter_rows("stockbalance"):
        plan.source_rows += 1
        legacy_item = text(row[0])
        raw_batch = "" if row[1] is None else str(row[1])
        batch_no = text(row[1])
        target_item = item_map.get(legacy_item)
        if target_item is None:
            plan.unknown_legacy_items.append(
                {"legacy_item": legacy_item, "batch_no": batch_no})
            continue
        if not batch_no:
            continue

        net_loose = num(row[6]) - num(row[9])          # purchase - sales
        raw_pack = num(row[7])
        pack_size = raw_pack if raw_pack > 0 else 0.0

        groups[(target_item, batch_no)].append({
            "legacy_item": legacy_item,
            "target_item": target_item,
            "batch_no": batch_no,
            "raw_batch": raw_batch,
            "expiry": clean_date(row[2]),
            "mrp": num(row[3]),
            "purchase_rate": num(row[4]),
            "net_rate": num(row[5]),
            "net_loose": net_loose,
            "pack_size_src": pack_size,
        })
        legacy_ids_by_group[(target_item, batch_no)].add(legacy_item)
        raw_batches_by_group[(target_item, batch_no)].add(raw_batch)

    plan.source_keys = len(groups)

    # ── normalised batch-key collisions ────────────────────────────────
    # Two source rows claiming one target batch once whitespace is
    # normalised.  Two forms:
    #   (a) one normalised key holding several *raw* strings — ``CARE``
    #       and ``' CARE'``, which stripping alone already merges;
    #   (b) several normalised keys sharing a *loose* key — ``CARE 1``,
    #       ``CARE  1`` and ``CARE   1``, which only collapsing internal
    #       whitespace runs brings together.
    # Neither is merged and neither is dropped: each is withheld and the
    # plan is blocked, with every compared field on the record.
    loose_index: dict[tuple[int, str], list[tuple[int, str]]] = defaultdict(list)
    for group_key in groups:
        loose_index[(group_key[0], loose_batch_no(group_key[1]))].append(
            group_key)

    collisions: dict[tuple[int, str], dict] = {}
    for group_key, raws in raw_batches_by_group.items():
        if len(raws) > 1:
            collisions[group_key] = {
                "members": list(groups[group_key]),
                "variant": "surrounding whitespace",
            }
    for member_keys in loose_index.values():
        if len(member_keys) > 1:
            members = [m for k in member_keys for m in groups[k]]
            for group_key in member_keys:
                collisions[group_key] = {
                    "members": members,
                    "variant": "internal whitespace",
                }

    reported: set[frozenset] = set()
    for group_key, info in sorted(collisions.items()):
        target_item, batch_no = group_key
        members = info["members"]
        field_map = _field_map(members)
        _per_field, disagreeing = _comparison(list(field_map.values()))
        signature = frozenset(m["raw_batch"] for m in members)
        if signature not in reported:
            reported.add(signature)
            plan.normalized_collisions.append({
                "target_item": target_item,
                "normalized_batch_no": loose_batch_no(batch_no),
                "collision_variant": info["variant"],
                "raw_variants": sorted(field_map),
                "legacy_items": sorted(
                    {m["legacy_item"] for m in members}),
                "source_rows": len(members),
                "net_loose_by_variant": {
                    v: field_map[v]["net_loose"] for v in sorted(field_map)},
                "metadata_by_variant": field_map,
                "compared_fields": list(COMPARED_FIELDS),
                "agreeing_fields": [f for f in COMPARED_FIELDS
                                    if f not in disagreeing],
                "conflicting_fields": disagreeing,
                "metadata_conflict": bool(disagreeing),
            })
        plan.withheld_keys.append({
            "target_item": target_item, "batch_no": batch_no,
            "reason": "normalized batch-key collision",
            "raw_variants": sorted(field_map)})

    # ── collapse each group into one target row ────────────────────────
    for key, members in groups.items():
        target_item, batch_no = key

        if key in collisions:
            continue

        # Several source rows for ONE raw batch (the legacy table has
        # no unique key).  Quantities legitimately sum, but disagreeing
        # metadata is reported rather than silently taken from the first
        # row seen.
        if len(members) > 1:
            pack_sizes = {m["pack_size_src"] for m in members}
            if len(pack_sizes) > 1:
                plan.conflicts.append({
                    "target_item": target_item, "batch_no": batch_no,
                    "reason": "merged rows disagree on pack size",
                    "pack_sizes": sorted(pack_sizes),
                    "legacy_items": sorted(legacy_ids_by_group[key]),
                })
                plan.withheld_keys.append({
                    "target_item": target_item, "batch_no": batch_no,
                    "reason": "merged rows disagree on pack size"})
                continue
            member_fields = [_member_fields(m) for m in members]
            _per_field, disagreeing = _comparison(member_fields)
            if disagreeing:
                plan.metadata_drift.append({
                    "target_item": target_item, "batch_no": batch_no,
                    "legacy_items": sorted(legacy_ids_by_group[key]),
                    "source_rows": len(members),
                    "conflicting_fields": disagreeing,
                    "rows": member_fields,
                })
            plan.merged_groups.append({
                "target_item": target_item, "batch_no": batch_no,
                "legacy_items": sorted(legacy_ids_by_group[key]),
                "net_loose": sum(m["net_loose"] for m in members),
            })
            plan.duplicate_source_rows += len(members) - 1

        head = members[0]
        net_loose = sum(m["net_loose"] for m in members)

        # Pack size — source value, then the existing target row, then
        # the item master.  If none resolves it the conversion is
        # undefined: block.  A divisor of 1 is never substituted, because
        # that would silently report loose units as packs.
        pack_size = head["pack_size_src"]
        if pack_size <= 0:
            prior = existing.get(key)
            if prior and text(prior.get("pack_size")):
                pack_size = num(prior["pack_size"])
            elif num(item_pack.get(target_item, "")):
                pack_size = num(item_pack[target_item])
        if pack_size <= 0:
            plan.missing_pack_size.append({
                "target_item": target_item,
                "batch_no": batch_no,
                "legacy_items": sorted(legacy_ids_by_group[key]),
                "net_loose": net_loose,
                "net_loose_is_zero": net_loose == 0,
                "existing_target_pack_size": (
                    text(existing[key].get("pack_size"))
                    if key in existing else ""),
                "item_master_pack_size": item_pack.get(target_item, ""),
            })
            plan.withheld_keys.append({
                "target_item": target_item, "batch_no": batch_no,
                "reason": "pack size could not be resolved"})
            continue

        stock_qty = net_loose / pack_size

        if stock_qty > 0:
            plan.positives += 1
        elif stock_qty == 0:
            plan.zeros += 1
        else:
            plan.negatives.append({
                "target_item": target_item, "batch_no": batch_no,
                "legacy_item": head["legacy_item"],
                "net_loose": net_loose, "pack_size": pack_size,
                "stock_qty": stock_qty})

        plan.rows.append({
            "target_item": target_item,
            "batch_no": batch_no,
            "expiry": head["expiry"],
            "mrp": head["mrp"],
            "purchase_rate": head["purchase_rate"],
            "net_rate": head["net_rate"],
            "pack_size": pack_text(pack_size),
            "pack_size_num": pack_size,
            "net_loose": net_loose,
            "stock_qty": stock_qty,
            "expired": is_expired(head["expiry"]),
            "legacy_items": sorted(legacy_ids_by_group[key]),
        })

    return plan


# ── applying ─────────────────────────────────────────────────────────────

def apply_plan(conn: sqlite3.Connection, plan: StockPlan, *,
               write_metadata: bool = True) -> dict:
    """Set every target batch to its computed pack quantity.

    Idempotent: quantities are *set*, never incremented.  Batch metadata
    (expiry/MRP/rates/pack size) is refreshed only from non-empty source
    values so richer existing data is not blanked out.
    """
    existing = {}
    for r in conn.execute(
            "SELECT id, item_id, batch_no, pack_size FROM stock_batches"):
        existing[(int(r["item_id"]), text(r["batch_no"]))] = int(r["id"])

    updated = inserted = 0
    for row in plan.rows:
        key = (row["target_item"], row["batch_no"])
        batch_id = existing.get(key)
        if batch_id is None:
            cur = conn.execute(
                """INSERT INTO stock_batches
                       (item_id, batch_no, expiry, pack_size, mrp,
                        purchase_rate, net_rate, stock_qty)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (row["target_item"], row["batch_no"], row["expiry"],
                 row["pack_size"], row["mrp"], row["purchase_rate"],
                 row["net_rate"], row["stock_qty"]),
            )
            existing[key] = cur.lastrowid
            inserted += 1
        else:
            conn.execute(
                """UPDATE stock_batches
                      SET stock_qty     = ?,
                          expiry        = CASE WHEN ? <> '' THEN ? ELSE expiry END,
                          pack_size     = CASE WHEN ? <> '' THEN ? ELSE pack_size END,
                          mrp           = CASE WHEN ? <> 0 THEN ? ELSE mrp END,
                          purchase_rate = CASE WHEN ? <> 0 THEN ? ELSE purchase_rate END,
                          net_rate      = CASE WHEN ? <> 0 THEN ? ELSE net_rate END
                    WHERE id = ?""",
                (row["stock_qty"],
                 row["expiry"], row["expiry"],
                 row["pack_size"], row["pack_size"],
                 row["mrp"], row["mrp"],
                 row["purchase_rate"], row["purchase_rate"],
                 row["net_rate"], row["net_rate"],
                 batch_id),
            )
            updated += 1

    if write_metadata:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS legacy_stock_migration (
                   id              INTEGER PRIMARY KEY AUTOINCREMENT,
                   applied_at      TEXT NOT NULL,
                   source_file     TEXT NOT NULL,
                   source_sha256   TEXT NOT NULL,
                   source_keys     INTEGER NOT NULL,
                   rows_updated    INTEGER NOT NULL,
                   rows_inserted   INTEGER NOT NULL,
                   positives       INTEGER NOT NULL,
                   zeros           INTEGER NOT NULL,
                   negatives       INTEGER NOT NULL,
                   conflicts       INTEGER NOT NULL
               )""")
        conn.execute(
            """INSERT INTO legacy_stock_migration
                   (applied_at, source_file, source_sha256, source_keys,
                    rows_updated, rows_inserted, positives, zeros, negatives,
                    conflicts)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (datetime.now().isoformat(timespec="seconds"),
             str(DEFAULT_SOURCE), sha256_file(DEFAULT_SOURCE),
             plan.source_keys, updated, inserted, plan.positives, plan.zeros,
             len(plan.negatives), len(plan.conflicts)),
        )

    conn.commit()
    return {"updated": updated, "inserted": inserted}


# ── verification ─────────────────────────────────────────────────────────

def verify(conn: sqlite3.Connection, plan: StockPlan) -> dict:
    """Re-read every migrated batch and compare against the plan."""
    mismatches: list[dict] = []
    missing: list[dict] = []
    for row in plan.rows:
        r = conn.execute(
            "SELECT stock_qty FROM stock_batches WHERE item_id = ? AND batch_no = ?",
            (row["target_item"], row["batch_no"]),
        ).fetchone()
        if r is None:
            missing.append({"item": row["target_item"],
                            "batch": row["batch_no"]})
            continue
        if abs(float(r["stock_qty"]) - row["stock_qty"]) > 1e-6:
            mismatches.append({
                "item": row["target_item"], "batch": row["batch_no"],
                "expected": row["stock_qty"], "actual": float(r["stock_qty"])})

    totals = conn.execute(
        """SELECT COUNT(*) AS n,
                  SUM(CASE WHEN stock_qty > 0 THEN 1 ELSE 0 END) AS pos,
                  SUM(CASE WHEN stock_qty = 0 THEN 1 ELSE 0 END) AS zer,
                  SUM(CASE WHEN stock_qty < 0 THEN 1 ELSE 0 END) AS neg
             FROM stock_batches""").fetchone()

    orphan_items = conn.execute(
        "SELECT COUNT(*) FROM stock_batches sb LEFT JOIN items i"
        " ON i.id = sb.item_id WHERE i.id IS NULL").fetchone()[0]

    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    fk = len(conn.execute("PRAGMA foreign_key_check").fetchall())
    dups = conn.execute(
        "SELECT COUNT(*) FROM (SELECT item_id, batch_no FROM stock_batches"
        " GROUP BY item_id, batch_no HAVING COUNT(*) > 1)").fetchone()[0]

    # Every source key must land in exactly one of: written to the plan, or
    # withheld with a reason.  Nothing may vanish between the dump and the
    # target — this is the source-to-target batch mapping check.
    mapped_keys = {(row["target_item"], row["batch_no"]) for row in plan.rows}
    withheld_keys = {(w["target_item"], w["batch_no"])
                     for w in plan.withheld_keys}
    duplicate_mapped = len(plan.rows) - len(mapped_keys)
    overlap = mapped_keys & withheld_keys
    mapping_partition_ok = (
        len(plan.rows) + len(plan.withheld_keys) == plan.source_keys
        and duplicate_mapped == 0 and not overlap)

    return {
        "plan_rows": len(plan.rows),
        "mismatches": len(mismatches),
        "mismatch_sample": mismatches[:20],
        "missing": len(missing),
        "missing_sample": missing[:20],
        "stock_batches_total": totals["n"],
        "stock_batches_positive": totals["pos"],
        "stock_batches_zero": totals["zer"],
        "stock_batches_negative": totals["neg"],
        "orphan_batches": orphan_items,
        "duplicate_keys": dups,
        "integrity_check": integrity,
        "foreign_key_violations": fk,
        "source_keys": plan.source_keys,
        "mapped_keys": len(plan.rows),
        "withheld_keys": len(plan.withheld_keys),
        "duplicate_mapped_keys": duplicate_mapped,
        "mapped_withheld_overlap": len(overlap),
        "mapping_partition_ok": mapping_partition_ok,
        "ok": (not mismatches and not missing and not orphan_items and not dups
               and integrity == "ok" and fk == 0 and mapping_partition_ok),
    }


# ── UC-ROSE trace ────────────────────────────────────────────────────────

def trace_uc_rose(dump: LegacyDump, conn: sqlite3.Connection,
                  plan: StockPlan) -> dict:
    """Full Phase-4 trace for the item the owner reported."""
    out: dict = {"legacy_item_id": UC_ROSE_LEGACY_ID}

    mapped = conn.execute(
        "SELECT new_id FROM legacy_id_map WHERE entity='item' AND legacy_id=?",
        (str(UC_ROSE_LEGACY_ID),)).fetchone()
    out["mapped_target_item_id"] = int(mapped["new_id"]) if mapped else None

    target = None
    if out["mapped_target_item_id"] is not None:
        r = conn.execute("SELECT * FROM items WHERE id = ?",
                         (out["mapped_target_item_id"],)).fetchone()
        target = dict(r) if r else None
    out["target_item_row"] = target

    # Source-side stockbalance rows for legacy item 832.
    src_rows = []
    for row in dump.iter_rows("stockbalance"):
        if text(row[0]) != str(UC_ROSE_LEGACY_ID):
            continue
        net_loose = num(row[6]) - num(row[9])
        ps = num(row[7])
        src_rows.append({
            "batch_no": text(row[1]),
            "expiry": clean_date(row[2]),
            "mrp": num(row[3]),
            "rate": num(row[4]),
            "net_pur_rate": num(row[5]),
            "total_purchase_qty_loose": num(row[6]),
            "pack_size": num(row[7]),
            "total_sales_qty_loose": num(row[9]),
            "net_loose_units": net_loose,
            "net_packs": (net_loose / ps) if ps else None,
        })
    out["source_stockbalance_rows"] = src_rows

    # Plan-side rows for the mapped target item — the *projected* state
    # after migration.  Everything below that answers "what will Counter
    # Sale offer?" is derived from these, never from the current target
    # rows (which are all stock_qty = 0 before the migration runs).
    out["plan_rows"] = [
        {k: v for k, v in r.items() if k != "pack_size_num"}
        for r in plan.rows if r["target_item"] == out["mapped_target_item_id"]]

    # Projected batches, in the shape the sales DAO returns.
    out["projected_batches"] = [
        {
            "item_id": r["target_item"],
            "batch_no": r["batch_no"],
            "expiry": r["expiry"],
            "pack_size": r["pack_size"],
            "mrp": r["mrp"],
            "purchase_rate": r["purchase_rate"],
            "net_rate": r["net_rate"],
            "stock_qty": r["stock_qty"],
        }
        for r in out["plan_rows"]
    ]
    out["projected_positive_batches"] = [
        b for b in out["projected_batches"] if b["stock_qty"] > 0]
    # Counter Sale offers a batch only when it has stock AND is unexpired.
    out["projected_sellable_batches"] = [
        b for b in out["projected_positive_batches"]
        if not is_expired(b["expiry"])]
    out["projected_expired_with_stock"] = [
        b for b in out["projected_positive_batches"]
        if is_expired(b["expiry"])]
    out["projected_counter_sale_rows"] = out["projected_sellable_batches"]

    # Keys for this item withheld as unresolved (collision / pack size).
    out["withheld_keys"] = [
        w for w in plan.withheld_keys
        if w["target_item"] == out["mapped_target_item_id"]]

    # Current target-side batches — the *pre-migration* truth.  These are
    # zero-quantity history-linkage rows, which is exactly why the
    # projection above cannot be read off them.
    if out["mapped_target_item_id"] is not None:
        out["current_target_batches"] = [dict(r) for r in conn.execute(
            "SELECT id, item_id, batch_no, expiry, pack_size, mrp,"
            " purchase_rate, net_rate, stock_qty FROM stock_batches"
            " WHERE item_id = ? ORDER BY batch_no",
            (out["mapped_target_item_id"],))]
    else:
        out["current_target_batches"] = []

    out["current_positive_batches"] = [
        b for b in out["current_target_batches"] if (b["stock_qty"] or 0) > 0]

    # What Counter Sale offers *right now*, before the migration.
    if out["mapped_target_item_id"] is not None:
        out["current_counter_sale_rows"] = [dict(r) for r in conn.execute(
            "SELECT sb.id, sb.batch_no, sb.expiry, sb.mrp, sb.stock_qty"
            " FROM stock_batches sb LEFT JOIN items i ON i.id = sb.item_id"
            " WHERE sb.item_id = ? AND sb.stock_qty > 0"
            " ORDER BY sb.expiry, sb.batch_no",
            (out["mapped_target_item_id"],))]
    else:
        out["current_counter_sale_rows"] = []
    return out


# ── reporting ────────────────────────────────────────────────────────────

def render_markdown(rep: dict) -> str:
    plan = rep["plan"]
    ver = rep.get("verification") or {}
    uc = rep["uc_rose"]
    L = [
        "# Phase 3 — Legacy Stock-Balance Migration",
        "",
        f"- Source: `{rep['source_file']}` ({rep['source_bytes']:,} bytes, READ-ONLY)",
        f"- Target: `{rep['db_path']}`",
        f"- Mode: `{rep['mode']}`",
        "",
        "## Unit conversion",
        "",
        "```",
        "net_loose_units  = stockbalance.TotalPurchaseQty - stockbalance.TotalSalesQty",
        "target_stock_qty = net_loose_units / stockbalance.PackSize",
        "```",
        "",
        "`stockadjusted` is already inside `TotalPurchaseQty` via the source",
        "triggers, so adjustments are never added a second time.  Positive,",
        "zero and negative nets are all preserved exactly.",
        "",
        "## Plan",
        "",
        f"- source rows: {plan['source_rows']}",
        f"- distinct target keys: {plan['source_keys']}",
        f"- keys written to the plan: {plan['target_keys']}",
        f"- keys WITHHELD as unresolved: {len(plan['withheld_keys'])}",
        f"- duplicate source rows collapsed: {plan['duplicate_source_rows']}",
        f"- positive: {plan['positive']}",
        f"- zero: {plan['zero']}",
        f"- negative (preserved as stored): {plan['negative']}",
        f"- legacy items with no mapping: {len(plan['unknown_legacy_items'])}",
        f"- **blocking normalised batch-key collisions: "
        f"{len(plan['normalized_collisions'])}**",
        f"- **blocking unresolved pack sizes: "
        f"{len(plan['missing_pack_size'])}**",
        f"- blocking merged-id collisions: {len(plan['conflicts'])}",
        f"- metadata drift reported (non-blocking): "
        f"{len(plan['metadata_drift'])}",
        "",
    ]
    if plan["blocked"]:
        L += [
            "> **PLAN BLOCKED — `--apply` will refuse.** "
            f"{plan['blocker_count']} unresolved key(s). Details below.",
            "",
        ]

    # ── blocking: normalised batch-key collisions ─────────────────────
    if plan["normalized_collisions"]:
        L += [
            "## BLOCKING — normalised batch-key collisions",
            "",
            "Source batches that are distinct strings but collapse to the",
            "same key once whitespace is stripped (for example `CARE` and",
            "`' CARE'`). They are **never merged and never silently",
            "dropped** — every compared field is listed so the difference",
            "is on the record.",
            "",
        ]
        for c in plan["normalized_collisions"]:
            verdict = ("metadata CONFLICTS" if c["metadata_conflict"]
                       else "metadata identical")
            L += [
                f"### target item {c['target_item']} · normalised key "
                f"`{c['normalized_batch_no']}` — "
                f"{len(c['raw_variants'])} raw variants "
                f"({c['collision_variant']}), {verdict}",
                "",
                "| raw batch | expiry | pack size | mrp | purchase rate | "
                "net rate | net loose |",
                "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
            ]
            for variant in c["raw_variants"]:
                values = c["metadata_by_variant"][variant]
                L.append(
                    f"| `{variant}` | {values['expiry']} | "
                    f"{values['pack_size']} | {values['mrp']} | "
                    f"{values['purchase_rate']} | {values['net_rate']} | "
                    f"{values['net_loose']} |")
            L += [
                "",
                f"- conflicting fields: "
                f"`{', '.join(c['conflicting_fields']) or '—'}`",
                f"- agreeing fields: "
                f"`{', '.join(c['agreeing_fields']) or '—'}`",
                f"- legacy items: {c['legacy_items']}",
                f"- source rows: {c['source_rows']}",
                "",
            ]

    # ── blocking: unresolved pack sizes ───────────────────────────────
    if plan["missing_pack_size"]:
        L += [
            "## BLOCKING — pack size could not be resolved",
            "",
            "The loose-unit to pack conversion needs a divisor. The source",
            "`PackSize`, the existing target row and the item master all",
            "failed to supply one, so these keys are withheld. **A divisor",
            "of 1 is never substituted** — that would report loose units",
            "as packs.",
            "",
            "| target item | batch | legacy items | net loose | source pack | "
            "target pack | item master pack |",
            "| ---: | --- | --- | ---: | ---: | --- | --- |",
        ]
        for m in plan["missing_pack_size"]:
            L.append(
                f"| {m['target_item']} | `{m['batch_no']}` | "
                f"{m['legacy_items']} | {m['net_loose']} | 0 | "
                f"`{m['existing_target_pack_size']}` | "
                f"`{m['item_master_pack_size']}` |")
        zero_net = [m for m in plan["missing_pack_size"]
                    if m["net_loose_is_zero"]]
        L += [
            "",
            f"- {len(zero_net)} of these have `net_loose == 0`, so the",
            "  divisor would not change the stored quantity — they are",
            "  still blocked, because the pack size is missing metadata.",
            "",
        ]

    # ── reported, non-blocking ────────────────────────────────────────
    if plan["metadata_drift"]:
        L += [
            "## Metadata drift on repeated rows (reported, not blocking)",
            "",
            "The legacy table has no unique key, so several rows can",
            "describe one real batch. Their quantities are summed, but",
            "these rows disagree on metadata; the first row seen is used",
            "and the disagreement is listed here rather than dropped.",
            "",
        ]
        for d in plan["metadata_drift"]:
            L.append(
                f"- item {d['target_item']} batch `{d['batch_no']}` "
                f"({d['source_rows']} rows) disagrees on "
                f"`{', '.join(d['conflicting_fields'])}`: "
                f"{json.dumps(d['rows'], default=str)}")
        L.append("")

    if plan["negatives"]:
        L += ["## Negative balances (preserved, never clamped)", ""]
        for n in plan["negatives"]:
            L.append(
                f"- item {n['target_item']} batch `{n['batch_no']}`: "
                f"{n['net_loose']} loose / pack {n['pack_size']} = "
                f"{n['stock_qty']:.4f} packs")
        L.append("")
    if plan["conflicts"]:
        L += ["## BLOCKING — merged-id collisions", ""]
        for c in plan["conflicts"]:
            L.append(f"- {json.dumps(c)}")
        L.append("")
    if plan["merged_groups"]:
        L += ["## Merged source rows combined (same target item + batch)", ""]
        for g in plan["merged_groups"]:
            L.append(f"- {json.dumps(g)}")
        L.append("")
    if ver:
        L += [
            "## Verification",
            "",
            f"- plan rows: {ver['plan_rows']}",
            f"- quantity mismatches: {ver['mismatches']}",
            f"- missing batches: {ver['missing']}",
            f"- duplicate (item, batch) keys: {ver['duplicate_keys']}",
            f"- orphan batches: {ver['orphan_batches']}",
            f"- `stock_batches` total: {ver['stock_batches_total']}",
            f"- positive: {ver['stock_batches_positive']}",
            f"- zero: {ver['stock_batches_zero']}",
            f"- negative: {ver['stock_batches_negative']}",
            f"- integrity_check: {ver['integrity_check']}",
            f"- foreign-key violations: {ver['foreign_key_violations']}",
            f"- **ok: {ver['ok']}**",
            "",
        ]
    L += [
        "## UC-ROSE trace",
        "",
        f"- legacy `itemmst.ID`: {uc['legacy_item_id']}",
        f"- mapped target `items.id`: {uc['mapped_target_item_id']}",
        f"- target item row: `{json.dumps(uc['target_item_row'], default=str)}`",
        f"- source `stockbalance` rows: {len(uc['source_stockbalance_rows'])}",
        f"- keys withheld for this item (unresolved): "
        f"{len(uc['withheld_keys'])}",
        "",
        "### Source stockbalance rows",
        "",
    ]
    for r in uc["source_stockbalance_rows"]:
        L.append(f"- `{json.dumps(r)}`")

    L += [
        "",
        "### Current state (before migration)",
        "",
        "- These target rows are the zero-quantity history-linkage rows.",
        "  They are shown for contrast only — **they are not the basis of",
        "  the projection below.**",
        "",
        f"- current `stock_batches` rows: "
        f"{len(uc['current_target_batches'])}",
        f"- of those, `stock_qty > 0`: {len(uc['current_positive_batches'])}",
        f"- offered by Counter Sale right now: "
        f"{len(uc['current_counter_sale_rows'])}",
        "",
        "### Projected state after migration (from `plan_rows`)",
        "",
        f"- projected batches: {len(uc['projected_batches'])}",
        f"- projected with `stock_qty > 0`: "
        f"{len(uc['projected_positive_batches'])}",
        f"- projected `stock_qty > 0` but expired (stocked, unsellable): "
        f"{len(uc['projected_expired_with_stock'])}",
        f"- **projected offered by Counter Sale (stock > 0 and unexpired): "
        f"{len(uc['projected_counter_sale_rows'])}**",
        "",
        "| batch | expiry | pack | mrp | net loose | projected stock | "
        "sellable |",
        "| --- | --- | ---: | ---: | ---: | ---: | :---: |",
    ]
    for r in uc["plan_rows"]:
        sellable = r["stock_qty"] > 0 and not r["expired"]
        L.append(
            f"| `{r['batch_no']}` | {r['expiry'] or '—'} | "
            f"{r['pack_size']} | {r['mrp']} | {r['net_loose']} | "
            f"{r['stock_qty']:.4f} | {'yes' if sellable else 'no'} |")
    L.append("")
    if not uc["plan_rows"]:
        L.append("- (no projected rows for this item — see the source rows "
                 "and withheld keys above)")
        L.append("")
    return "\n".join(L)


def write_reports(rep: dict) -> None:
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(
        json.dumps(rep, indent=2, default=str), encoding="utf-8")
    REPORT_MD.write_text(render_markdown(rep), encoding="utf-8")


# ── CLI ──────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=str(DEFAULT_DB),
                    help="target database (default: data/pharmacy.db)")
    ap.add_argument("--source", default=str(DEFAULT_SOURCE))
    ap.add_argument("--report", action="store_true",
                    help="read-only plan + UC-ROSE trace")
    ap.add_argument("--apply", action="store_true", help="apply the migration")
    ap.add_argument("--verify", action="store_true",
                    help="verify the target against a fresh plan")
    ap.add_argument("--clone-to", default=None,
                    help="copy --db to this path (staging clone) and stop")
    ap.add_argument("--confirm-production", action="store_true",
                    help="required when --db is the live data/pharmacy.db")
    ap.add_argument("--no-metadata", action="store_true",
                    help="skip writing the legacy_stock_migration audit row")
    args = ap.parse_args(argv)

    db_path = Path(args.db).resolve()
    src_path = Path(args.source).resolve()

    if args.clone_to:
        dest = Path(args.clone_to).resolve()
        dest.parent.mkdir(parents=True, exist_ok=True)
        src = connect(db_path, read_only=True)
        try:
            out = sqlite3.connect(str(dest))
            try:
                src.backup(out)
                out.commit()
            finally:
                out.close()
        finally:
            src.close()
        print(f"cloned {db_path} -> {dest} ({dest.stat().st_size:,} bytes)")
        return 0

    if not db_path.is_file():
        print(f"ERROR: database not found: {db_path}", file=sys.stderr)
        return 2

    is_live = os.path.normcase(str(db_path)) == os.path.normcase(str(DEFAULT_DB))
    if args.apply and is_live and not args.confirm_production:
        print("REFUSING: --apply on the live data/pharmacy.db needs "
              "--confirm-production (migrate a --clone-to copy first).",
              file=sys.stderr)
        return 3

    dump = LegacyDump(src_path)

    if args.apply:
        # verified backup first
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = Path(ROOT) / "migration_backups" / f"pre_stock_apply_{stamp}.db"
        backup.parent.mkdir(parents=True, exist_ok=True)
        src = connect(db_path, read_only=True)
        try:
            out = sqlite3.connect(str(backup))
            try:
                src.backup(out)
                out.commit()
            finally:
                out.close()
        finally:
            src.close()
        check = connect(backup, read_only=True)
        try:
            ok = check.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            check.close()
        if ok != "ok":
            print(f"REFUSING: backup failed integrity check ({ok})",
                  file=sys.stderr)
            return 4
        print(f"backup: {backup}")
        print(f"backup sha256: {sha256_file(backup)}")

    conn = connect(db_path, read_only=not args.apply)
    try:
        plan = build_plan(dump, conn)
        rep = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "source_file": str(src_path),
            "source_bytes": src_path.stat().st_size,
            "db_path": str(db_path),
            "db_sha256_before": sha256_file(db_path),
            "mode": ("apply" if args.apply else
                     "verify" if args.verify else "report"),
            "plan": plan.as_dict(),
        }

        if args.apply and plan.blocked:
            rep["verification"] = None
            rep["uc_rose"] = trace_uc_rose(dump, conn, plan)
            write_reports(rep)
            counts: dict[str, int] = {}
            for blocker in plan.blockers:
                counts[blocker["kind"]] = counts.get(blocker["kind"], 0) + 1
            detail = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
            print("REFUSING: the plan is blocked — nothing was written "
                  f"({detail}).", file=sys.stderr)
            print(f"See {REPORT_MD} for the blocker detail.", file=sys.stderr)
            return 5

        if args.apply:
            result = apply_plan(conn, plan,
                                write_metadata=not args.no_metadata)
            rep["applied"] = result
            rep["verification"] = verify(conn, plan)
            rep["uc_rose"] = trace_uc_rose(dump, conn, plan)
            rep["db_sha256_after"] = sha256_file(db_path)
        else:
            rep["verification"] = verify(conn, plan) if args.verify else None
            rep["uc_rose"] = trace_uc_rose(dump, conn, plan)

        write_reports(rep)
    finally:
        conn.close()

    if not args.apply and plan.blocked:
        print(f"BLOCKED: {len(plan.blockers)} unresolved key(s); this plan "
              f"may not be applied. See {REPORT_MD}", file=sys.stderr)
        blocked_report_rc = 6
    else:
        blocked_report_rc = 0

    # ── console summary ────────────────────────────────────────────────
    p = rep["plan"]
    print("=" * 78)
    print(f"target      : {rep['db_path']}")
    print(f"mode        : {rep['mode']}"
          + ("   [BLOCKED — will not apply]" if p["blocked"] else ""))
    print(f"source rows : {p['source_rows']}   distinct keys: {p['source_keys']}"
          f"   written: {p['target_keys']}   withheld: "
          f"{len(p['withheld_keys'])}")
    print(f"positive    : {p['positive']}   zero: {p['zero']}   "
          f"negative: {p['negative']}")
    print(f"unmapped legacy items : {len(p['unknown_legacy_items'])}")
    print(f"BLOCKERS              : normalized batch collisions="
          f"{len(p['normalized_collisions'])}  unresolved pack sizes="
          f"{len(p['missing_pack_size'])}  merged-id collisions="
          f"{len(p['conflicts'])}")
    print(f"reported (non-blocking): metadata drift="
          f"{len(p['metadata_drift'])}")
    if p["blocked"]:
        for b in plan.blockers[:20]:
            print(f"  ! {b['kind']}: item {b.get('target_item')} "
                  f"batch `{b.get('batch_no') or b.get('normalized_batch_no')}`")
        if len(plan.blockers) > 20:
            print(f"  ! ... and {len(plan.blockers) - 20} more (see report)")
    if "applied" in rep:
        print(f"applied     : {rep['applied']}")
    if rep.get("verification"):
        v = rep["verification"]
        print(f"verify      : ok={v['ok']} mismatches={v['mismatches']} "
              f"missing={v['missing']} dup_keys={v['duplicate_keys']} "
              f"orphans={v['orphan_batches']} integrity={v['integrity_check']}")
        print(f"stock_rows  : total={v['stock_batches_total']} "
              f"positive={v['stock_batches_positive']} zero={v['stock_batches_zero']} "
              f"negative={v['stock_batches_negative']}")
        print(f"mapping     : source keys={v['source_keys']} "
              f"mapped={v['mapped_keys']} withheld={v['withheld_keys']} "
              f"partition_ok={v['mapping_partition_ok']}")
    uc = rep["uc_rose"]
    print("-" * 78)
    print(f"UC-ROSE     : legacy item {uc['legacy_item_id']} -> target item "
          f"{uc['mapped_target_item_id']}")
    print(f"              source stockbalance rows : "
          f"{len(uc['source_stockbalance_rows'])}")
    for r in uc["source_stockbalance_rows"]:
        print(f"                {r['batch_no']:<12} exp {r['expiry']:<12} "
              f"pack {r['pack_size']:>5} net_loose {r['net_loose_units']:>10} "
              f"-> {r['net_packs']} packs")
    print(f"              withheld for this item   : "
          f"{len(uc['withheld_keys'])}")
    for w in uc["withheld_keys"][:10]:
        print(f"                ! {w['reason']}: `{w['batch_no']}` "
              f"{w.get('raw_variants', '')}")
    print(f"              Counter Sale offers now   : "
          f"{len(uc['current_counter_sale_rows'])} batch(es)")
    print(f"              PROJECTED after migration : "
          f"{len(uc['projected_batches'])} batch(es), "
          f"{len(uc['projected_positive_batches'])} with stock, "
          f"{len(uc['projected_expired_with_stock'])} expired-with-stock, "
          f"{len(uc['projected_counter_sale_rows'])} offered for sale")
    for r in uc["plan_rows"]:
        sellable = "SELLABLE" if (r["stock_qty"] > 0 and not r["expired"]) \
            else "not offered"
        print(f"                {r['batch_no']:<12} exp {r['expiry'] or '-':<12} "
              f"pack {r['pack_size']:>5} mrp {r['mrp']:<8} "
              f"stock {r['stock_qty']:>10.4f}  {sellable}")
    print("=" * 78)
    print(f"reports: {REPORT_MD}\n         {REPORT_JSON}")
    return blocked_report_rc


if __name__ == "__main__":
    raise SystemExit(main())
