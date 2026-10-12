"""Collision-safe resolution for the 8 normalized batch-key groups (staging only).

Owner-approved preparation — NOT an apply step.

Why this exists
--------------
``tools/legacy_stock_migration.py`` blocks on 16 withheld batch keys across
8 ``(target_item, normalized_batch)`` collision groups (whitespace variants
claiming one target batch).  Blocking is
correct — merging would silently discard conflicting expiry / MRP / rate
metadata — but it leaves stock at zero.  This module prepares a
collision-safe mapping that:

* never merges distinct source batches because their normalized keys match;
* preserves every variant's exact original batch string, legacy item id,
  expiry, pack size, MRP, purchase rate and net rate;
* gives colliding variants stable, distinct target identities.  Only where
  stripping alone collides (``CARE`` vs ``' CARE'``) is a deterministic
  synthetic alias required; internal-whitespace variants (``CARE 1`` vs
  ``'CARE  1'``) already have distinct ``(item_id, batch_no)`` identities
  and keep them — visible distinction is provided by
  :func:`display_batch_no` for Counter Sale rather than by renaming stored
  batches and breaking historical text linkage;
* preserves each variant's independent quantity
  ``(TotalPurchaseQty - TotalSalesQty) / PackSize`` — adjustments are never
  added again (already inside ``TotalPurchaseQty``) and no quantity is
  invented (a missing pack size stays blocking, never ``/1``);
* plans historical ``sales_invoice_items.stock_batch_id`` remaps only where
  the target merged them (legacy 238 ``CARE``); already-distinct groups
  need zero remaps.  Historical row details (amounts, quantities, stored
  ``batch_no`` text) are never rewritten by this report.

Safety
------
* Read-only.  Opens the database with SQLite ``mode=ro`` and issues only
  ``SELECT`` statements.  There is deliberately NO ``--apply`` path here —
  applying (creating the one new alias batch + setting quantities +
  remapping 21 sales FKs) is a separate owner-reviewed step.
* Never touches live ``data/pharmacy.db`` for writing; the intended use is
  ``--clone-to`` a fresh staging file (read-only source) then ``--report
  --db <staging>``.
* If a correct mapping cannot be established for a group (unresolvable
  pack size, alias collides with an unrelated existing batch, or mixed
  vouchers make the variant unassignable), the group stays blocked with an
  explicit reason.

Usage
-----
    # fresh staging clone (reads live read-only, writes only the clone file)
    python tools/legacy_stock_resolution.py --clone-to staging/stock_resolution_stage.db

    # read-only resolution report against the clone
    python tools/legacy_stock_resolution.py --report --db staging/stock_resolution_stage.db
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from database.legacy_migration import LegacyDump  # noqa: E402

from tools.legacy_stock_migration import (  # noqa: E402
    COMPARED_FIELDS,
    DEFAULT_DB,
    DEFAULT_SOURCE,
    build_plan,
    clean_date,
    is_expired,
    loose_batch_no,
    num,
    pack_text,
    text,
    trace_uc_rose,
)

REPORT_JSON = ROOT / "migration_backups" / "phase3_stock_resolution.json"
REPORT_MD = ROOT / "migration_backups" / "phase3_stock_resolution.md"


# ── display ──────────────────────────────────────────────────────────

def display_batch_no(batch_no: str) -> str:
    """Human-visible form of a batch number for Counter Sale.

    Internal runs of 2+ spaces and surrounding whitespace are invisible in
    most UI fonts (``'CARE  1'`` vs ``'CARE 1'``).  This renders them
    explicitly so colliding variants are visibly distinct without renaming
    stored batches:

    * ``'CARE'`` -> ``'CARE'``
    * ``' CARE'`` -> ``'[lead-1]CARE'``
    * ``'BHU '`` -> ``'BHU[trail-1]'``
    * ``'CARE  1'`` (2 spaces) -> ``'CARE[2sp]1'``
    * ``'N  142033'`` -> ``'N[2sp]142033'``

    Single internal spaces are preserved as-is.  The mapping is
    deterministic and reversible for audit (``[Nsp]`` -> N spaces).
    """
    s = "" if batch_no is None else str(batch_no)
    # leading / trailing runs first so interior logic sees the core
    lead = len(s) - len(s.lstrip(" "))
    trail = len(s) - len(s.rstrip(" "))
    core = s.strip(" ")
    # collapse interior runs of 2+ spaces to [Nsp]
    core = re.sub(r" {2,}", lambda m: f"[{len(m.group(0))}sp]", core)
    out = core
    if lead:
        out = f"[lead-{lead}]" + out
    if trail:
        out = out + f"[trail-{trail}]"
    return out


def _visible_spacing(stripped: str) -> str:
    """Display form used in tests: same rule as :func:`display_batch_no`."""
    return display_batch_no(stripped)


# ── aliases ──────────────────────────────────────────────────────────

def alias_for_surrounding_collision(stripped_base: str, raw: str) -> str:
    """Deterministic synthetic alias for a stripped-collision variant.

    ``stripped_base`` is ``text(raw)`` shared by several raws (e.g.
    ``'CARE'`` for both ``'CARE'`` and ``' CARE'``).  The alias embeds the
    exact original (``repr``) so provenance is visible in the identity
    itself, e.g. ``CARE[exact=' CARE']``.  Deterministic: same inputs always
    yield the same alias; distinct raws always yield distinct aliases.
    """
    return f"{stripped_base}[exact={raw!r}]"


def _resolve_pack_size(pack_src: float, target_item: int, alias_key,
                       existing: dict, item_pack: dict,
                       allow_existing_fallback: bool) -> float:
    """Same fallback order as the base plan, per variant.

    Source value, then the existing target row for that alias key, then the
    item master.  ``allow_existing_fallback=False`` for non-canonical
    stripped-collision variants so a canonical row's metadata can never leak
    into another variant.  Never returns 1 as a substitute — 0 means
    unresolvable (blocking).
    """
    if pack_src and pack_src > 0:
        return pack_src
    if allow_existing_fallback:
        prior = existing.get(alias_key)
        if prior and text(prior.get("pack_size")):
            v = num(prior["pack_size"])
            if v > 0:
                return v
    v = num(item_pack.get(target_item, ""))
    if v > 0:
        return v
    return 0.0


# ── durable provenance ─────────────────────────────────────────────
# JSON reports are audit copies only.  The recoverable record is the
# ``legacy_batch_resolution`` table described below.  Nothing in this module
# creates it in a real database — the helpers operate on whatever connection
# the caller passes, so tests use disposable SQLite files while live/staging
# stay untouched.

PROVENANCE_DDL = """
CREATE TABLE IF NOT EXISTS legacy_batch_resolution (
    target_item_id      INTEGER NOT NULL,
    alias_batch_no      TEXT    NOT NULL,
    raw_batch_exact     TEXT    NOT NULL,
    stripped_batch      TEXT    NOT NULL,
    normalized_key      TEXT    NOT NULL,
    legacy_item_id      TEXT    NOT NULL,
    expiry              TEXT    NOT NULL DEFAULT '',
    pack_size           TEXT    NOT NULL DEFAULT '',
    mrp                 REAL    NOT NULL DEFAULT 0,
    purchase_rate       REAL    NOT NULL DEFAULT 0,
    net_rate            REAL    NOT NULL DEFAULT 0,
    net_loose           REAL    NOT NULL DEFAULT 0,
    stock_qty           REAL    NOT NULL DEFAULT 0,
    existing_batch_id   INTEGER,
    is_canonical        INTEGER NOT NULL DEFAULT 0,
    display_label       TEXT    NOT NULL DEFAULT '',
    PRIMARY KEY (target_item_id, alias_batch_no)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_batch_res_exact
    ON legacy_batch_resolution(target_item_id, raw_batch_exact);
"""


def create_provenance_table(conn: sqlite3.Connection) -> None:
    """Create the durable provenance table (caller chooses the database)."""
    conn.executescript(PROVENANCE_DDL)
    conn.commit()


def write_provenance(conn: sqlite3.Connection, resolution: dict) -> int:
    """Persist every resolved variant; idempotent via DELETE+INSERT.

    Returns the number of rows written.  Only groups with
    ``status == 'resolved'`` are stored; blocked variants stay out so a
    future apply can never pick them up by accident.
    """
    create_provenance_table(conn)
    conn.execute("DELETE FROM legacy_batch_resolution")
    n = 0
    for g in resolution.get("groups", []):
        if g.get("status") != "resolved":
            continue
        for v in g.get("variants", []):
            if v.get("stock_qty") is None:
                continue
            conn.execute(
                """INSERT INTO legacy_batch_resolution
                       (target_item_id, alias_batch_no, raw_batch_exact,
                        stripped_batch, normalized_key, legacy_item_id,
                        expiry, pack_size, mrp, purchase_rate, net_rate,
                        net_loose, stock_qty, existing_batch_id,
                        is_canonical, display_label)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (g["target_item"], v["alias_batch_no"], v["raw_batch_exact"],
                 v["stripped_batch"], g["normalized_key"],
                 ",".join(v.get("legacy_items", [])),
                 v.get("expiry", ""), v.get("pack_size_text", ""),
                 v.get("mrp", 0.0), v.get("purchase_rate", 0.0),
                 v.get("net_rate", 0.0), v.get("net_loose", 0.0),
                 v.get("stock_qty", 0.0), v.get("existing_batch_id"),
                 1 if v.get("is_canonical") else 0,
                 v.get("display_batch_no", "")))
            n += 1
    conn.commit()
    return n


def read_provenance(conn: sqlite3.Connection) -> list[dict]:
    """Read the durable mapping back (no JSON involved)."""
    conn.row_factory = sqlite3.Row
    return [dict(r) for r in conn.execute(
        "SELECT * FROM legacy_batch_resolution"
        " ORDER BY target_item_id, alias_batch_no")]


def verify_provenance_reconstruction(conn: sqlite3.Connection,
                                    expected_aliases: dict) -> dict:
    """Prove exact identities recover from the table alone.

    ``expected_aliases`` maps ``(target_item, alias) -> raw_exact``.
    Returns ``{'ok': bool, 'missing': [...], 'mismatched': [...]}``.
    """
    rows = read_provenance(conn)
    got = {(r["target_item_id"], r["alias_batch_no"]): r["raw_batch_exact"]
           for r in rows}
    missing = [k for k in expected_aliases if k not in got]
    mismatched = [k for k in expected_aliases
                  if k in got and got[k] != expected_aliases[k]]
    return {"ok": not missing and not mismatched and len(got) == len(expected_aliases),
            "rows": len(got), "missing": missing, "mismatched": mismatched}


# ── resolution ───────────────────────────────────────────────────────

def _read_maps(conn: sqlite3.Connection):
    item_map = {
        text(r["legacy_id"]): int(r["new_id"])
        for r in conn.execute(
            "SELECT legacy_id, new_id FROM legacy_id_map WHERE entity='item'")}
    item_pack: dict[int, str] = {}
    for r in conn.execute("SELECT id, pack_size FROM items"):
        item_pack[int(r["id"])] = text(r["pack_size"])
    existing: dict[tuple[int, str], dict] = {}
    for r in conn.execute(
            "SELECT id, item_id, batch_no, expiry, pack_size, mrp,"
            " purchase_rate, net_rate, stock_qty FROM stock_batches"):
        existing[(int(r["item_id"]), text(r["batch_no"]))] = dict(r)
    existing_exact: dict[tuple[int, str], dict] = {}
    for r in conn.execute(
            "SELECT id, item_id, batch_no FROM stock_batches"):
        existing_exact[(int(r["item_id"]), "" if r["batch_no"] is None else str(r["batch_no"]))] = dict(r)
    sale_vh_to_new = {
        text(r["legacy_id"]): int(r["new_id"])
        for r in conn.execute(
            "SELECT legacy_id, new_id FROM legacy_id_map WHERE entity='sale'")}
    purchase_vh_to_new = {
        text(r["legacy_id"]): int(r["new_id"])
        for r in conn.execute(
            "SELECT legacy_id, new_id FROM legacy_id_map WHERE entity='purchase'")}
    return item_map, item_pack, existing, existing_exact, sale_vh_to_new, purchase_vh_to_new


def _collision_groups_from_withheld(base, dump: LegacyDump,
                                      item_map: dict) -> list[dict]:
    """Rebuild collision groups keyed by ``(target_item, normalized_key)``.

    The base plan's ``normalized_collisions`` list deduplicates by raw
    signature globally, which drops groups when two target items share the
    same raw variants (1134 vs 1199 ``CARE UNI``).  ``withheld_keys`` is
    authoritative (16 entries), so groups are rebuilt from it: withheld
    entries are bucketed by ``(target_item, loose(stripped))``; each bucket
    with >1 stripped key, or a single stripped key holding >1 raw, is one
    group.  Per-variant metadata is recomputed from the dump (never merged
    across target items or across raws).
    """
    # (target, stripped) -> raw set (authoritative, from withheld entries)
    stripped_raws: dict[tuple[int, str], set[str]] = defaultdict(set)
    for w in base.withheld_keys:
        tgt, stripped = w["target_item"], w["batch_no"]
        for raw in w.get("raw_variants", [stripped]):
            stripped_raws[(tgt, stripped)].add(raw)
    # bucket by (target, loose)
    buckets: dict[tuple[int, str], dict] = defaultdict(
        lambda: {"stripped": set(), "raws": set()})
    for (tgt, stripped), raws in stripped_raws.items():
        loose = loose_batch_no(stripped)
        buckets[(tgt, loose)]["stripped"].add(stripped)
        buckets[(tgt, loose)]["raws"].update(raws)
    # source rows by exact (target, raw) for metadata (never cross-item)
    src_by_target_raw: dict[tuple[int, str], list[dict]] = defaultdict(list)
    for row in dump.iter_rows("stockbalance"):
        leg = text(row[0])
        raw = "" if row[1] is None else str(row[1])
        tgt = item_map.get(leg)
        if tgt is None or not raw or not text(raw):
            continue
        src_by_target_raw[(tgt, raw)].append(row)
    groups = []
    for (tgt, loose) in sorted(buckets):
        stripped_set = buckets[(tgt, loose)]["stripped"]
        raw_set = sorted(buckets[(tgt, loose)]["raws"])
        # surrounding (one stripped, many raws) vs internal (many stripped)
        variant = ("surrounding whitespace"
                   if len(stripped_set) == 1 and len(raw_set) > 1
                   else "internal whitespace")
        # per-raw first-seen metadata for comparison
        field_by_raw: dict[str, dict] = {}
        legacy_items: set[str] = set()
        for raw in raw_set:
            src_rows = [r for (t, rw), lst in src_by_target_raw.items()
                        if t == tgt and rw == raw for r in lst]
            if src_rows:
                r0 = src_rows[0]
                field_by_raw[raw] = {
                    "expiry": clean_date(r0[2]),
                    "pack_size": num(r0[7]) if num(r0[7]) > 0 else 0.0,
                    "mrp": num(r0[3]),
                    "purchase_rate": num(r0[4]),
                    "net_rate": num(r0[5]),
                    "net_loose": sum(num(r[6]) - num(r[9]) for r in src_rows),
                    "legacy_items": sorted({text(r[0]) for r in src_rows}),
                }
                legacy_items.update(text(r[0]) for r in src_rows)
            else:
                field_by_raw[raw] = {
                    "expiry": "", "pack_size": 0.0, "mrp": 0.0,
                    "purchase_rate": 0.0, "net_rate": 0.0, "net_loose": 0.0,
                    "legacy_items": [],
                }
        from tools.legacy_stock_migration import _comparison  # local import
        records = [{k: v[k] for k in COMPARED_FIELDS} for v in field_by_raw.values()]
        _per, disagreeing = _comparison(records)
        groups.append({
            "target_item": tgt,
            "normalized_batch_no": loose,
            "collision_variant": variant,
            "raw_variants": raw_set,
            "legacy_items": sorted(legacy_items),
            "source_rows": sum(len([r for (t, rw), lst in src_by_target_raw.items()
                                    if t == tgt and rw == raw for r in lst])
                               for raw in raw_set),
            "net_loose_by_variant": {r: field_by_raw[r]["net_loose"] for r in raw_set},
            "metadata_by_variant": field_by_raw,
            "compared_fields": list(COMPARED_FIELDS),
            "agreeing_fields": [f for f in COMPARED_FIELDS if f not in disagreeing],
            "conflicting_fields": disagreeing,
            "metadata_conflict": bool(disagreeing),
        })
    return groups


def _source_variants_by_collision(dump: LegacyDump, item_map: dict,
                                  groups) -> dict:
    """Exact-raw rows per ``(target, loose)`` group: {(target, loose): {raw: [rows]}}.

    ``groups`` are the per-target collision records from
    :func:`_collision_groups_from_withheld` (8 groups).  Each stockbalance
    row is placed under its own ``(target, loose)`` key by exact raw string
    — never merged across raws or across target items.  Quantities sum only
    within the same exact ``(target, raw)``.
    """
    loose_to_raws: dict[tuple[int, str], set[str]] = {}
    for c in groups:
        loose_to_raws[(c["target_item"], c["normalized_batch_no"])] = set(c["raw_variants"])
    out: dict[tuple[int, str], dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for row in dump.iter_rows("stockbalance"):
        legacy_item = text(row[0])
        raw_batch = "" if row[1] is None else str(row[1])
        tgt = item_map.get(legacy_item)
        if tgt is None or not raw_batch or not text(raw_batch):
            continue
        loose = loose_batch_no(text(raw_batch))
        key = (tgt, loose)
        if key not in loose_to_raws or raw_batch not in loose_to_raws[key]:
            continue
        out[key][raw_batch].append({
            "legacy_item": legacy_item,
            "raw_batch": raw_batch,
            "stripped": text(raw_batch),
            "expiry": clean_date(row[2]),
            "mrp": num(row[3]),
            "purchase_rate": num(row[4]),
            "net_rate": num(row[5]),
            "net_loose": num(row[6]) - num(row[9]),
            "pack_src": num(row[7]) if num(row[7]) > 0 else 0.0,
        })
    return out


def _historical_variant_counts(dump: LegacyDump, legacy_items: list[str]):
    """Source sales/purchase line counts per exact raw batch (read-only).

    Returns dicts plus voucher-mixing analysis: whether any legacy voucher
    contains two variants of the same group (which would make VhID-based
    remapping ambiguous).
    """
    legset = {text(x) for x in legacy_items}
    sales_by_raw: dict[str, int] = defaultdict(int)
    sales_vh: dict[str, set] = defaultdict(set)
    for row in dump.iter_rows("salesitemdetail"):
        if text(row[2]) not in legset:
            continue
        raw = "" if row[4] is None else str(row[4])
        sales_by_raw[raw] += 1
        sales_vh[text(row[1])].add(raw)
    purch_by_raw: dict[str, int] = defaultdict(int)
    purch_vh: dict[str, set] = defaultdict(set)
    for row in dump.iter_rows("invoiceitemdetail"):
        if text(row[2]) not in legset:
            continue
        raw = "" if row[3] is None else str(row[3])
        purch_by_raw[raw] += 1
        purch_vh[text(row[1])].add(raw)
    return sales_by_raw, sales_vh, purch_by_raw, purch_vh


def resolve_plan(dump: LegacyDump, conn: sqlite3.Connection) -> dict:
    """Build the collision-safe resolution (read-only, no writes).

    Returns a JSON-serialisable dict with ``groups`` (one per blocked
    collision), each holding per-variant ``provenance`` rows with distinct
    ``alias_batch_no`` identities, independent quantities, remap counts and
    a ``status`` of ``resolved`` or ``blocked`` with ``block_reason``.
    """
    base = build_plan(dump, conn)
    item_map, item_pack, existing, existing_exact, sale_map, purch_map = _read_maps(conn)
    collision_groups = _collision_groups_from_withheld(base, dump, item_map)
    variants = _source_variants_by_collision(dump, item_map, collision_groups)

    # current sales FK distribution for the 7 items (read-only verification)
    sales_fk: dict[tuple[int, str], int] = defaultdict(int)
    for r in conn.execute(
            "SELECT item_id, stock_batch_id, batch_no FROM sales_invoice_items"):
        sales_fk[(int(r["item_id"]), int(r["stock_batch_id"]))] += 1
    batch_id_by_key: dict[tuple[int, str], int] = {}
    batch_no_by_id: dict[int, str] = {}
    for r in conn.execute("SELECT id, item_id, batch_no FROM stock_batches"):
        batch_id_by_key[(int(r["item_id"]), text(r["batch_no"]))] = int(r["id"])
        batch_no_by_id[int(r["id"])] = "" if r["batch_no"] is None else str(r["batch_no"])

    groups_out = []
    resolved_rows = []
    for coll in sorted(collision_groups,
                       key=lambda c: (c["target_item"], c["normalized_batch_no"])):
        tgt = coll["target_item"]
        loose = coll["normalized_batch_no"]
        raws_sorted = sorted(coll["raw_variants"])
        per_raw = variants.get((tgt, loose), {})
        sales_by_raw, sales_vh, purch_by_raw, purch_vh = _historical_variant_counts(
            dump, coll["legacy_items"])

        # stripped analysis: surrounding collision iff stripped values collide
        stripped_of = {raw: text(raw) for raw in raws_sorted}
        stripped_vals = sorted(set(stripped_of.values()))
        has_stripped_collision = len(stripped_vals) < len(raws_sorted)
        # canonical: raw already in collapsed, stripped form
        canonical = next((raw for raw in raws_sorted
                          if raw == loose_batch_no(raw) == stripped_of[raw]), None)
        if canonical is None:
            # deterministic fallback: raw equal to its stripped form, else first
            canonical = next((raw for raw in raws_sorted if raw == stripped_of[raw]),
                             raws_sorted[0])

        variants_out = []
        group_block_reason = None
        # alias uniqueness scope: existing batches for this item + aliases in group
        taken_aliases = {b for (i, b) in existing_exact if i == tgt}
        # canonical keeps its stripped name (existing id reused); remove from taken
        # so reusing it is not treated as a collision
        group_aliases: dict[str, str] = {}
        for raw in raws_sorted:
            stripped = stripped_of[raw]
            if has_stripped_collision:
                if raw == canonical:
                    alias = stripped
                else:
                    alias = alias_for_surrounding_collision(stripped, raw)
            else:
                alias = stripped
            group_aliases[raw] = alias

        # Alias collision with a genuinely unrelated existing batch?
        # A present alias row whose metadata matches this variant's source
        # metadata is our own deterministic alias from a prior run (or the
        # pre-existing merged row) — safe to reuse, which also makes reruns
        # idempotent.  A metadata mismatch still blocks.
        for raw in raws_sorted:
            alias = group_aliases[raw]
            if raw == canonical and has_stripped_collision:
                continue  # reuses the merged row itself
            # internal groups reuse their own stripped rows — also reuses
            if not has_stripped_collision:
                continue  # alias == stripped == own existing row
            hit = existing_exact.get((tgt, alias))
            if hit is None:
                continue
            detail = existing.get((tgt, text(alias)), {}) or {}
            want_rows = per_raw.get(raw) or []
            want = want_rows[0] if want_rows else {}
            mism = []
            if text(detail.get("expiry")) != text(want.get("expiry") or ""):
                mism.append("expiry")
            for fld, key in (("mrp", "mrp"), ("purchase_rate", "purchase_rate"),
                             ("net_rate", "net_rate")):
                try:
                    if abs(float(detail.get(fld) or 0) - float(want.get(key) or 0)) > 1e-9:
                        mism.append(fld)
                except (TypeError, ValueError):
                    mism.append(fld)
            if mism:
                group_block_reason = (
                    f"alias {alias!r} already exists as an unrelated batch for"
                    f" item {tgt} (differs on {', '.join(mism)}); refusing to overwrite")
                break
            # else: own prior alias — reuse below via existing_batch_id lookup
        # duplicate aliases within group?
        if group_block_reason is None and len(set(group_aliases.values())) != len(raws_sorted):
            group_block_reason = "deterministic aliases collided within the group"

        for raw in raws_sorted:
            rows = per_raw.get(raw, [])
            net_loose = sum(r["net_loose"] for r in rows) if rows else coll["metadata_by_variant"][raw]["net_loose"]
            # metadata: prefer stockbalance exact-raw rows; fall back to plan's field map
            if rows:
                # sum keeps quantity exact; metadata from first row of that raw
                head = rows[0]
                # pack disagreement within same exact raw stays blocking (as base plan)
                packs = {r["pack_src"] for r in rows}
                pack_disagree = len(packs) > 1
                meta = {"expiry": head["expiry"], "pack_src": head["pack_src"],
                        "mrp": head["mrp"], "purchase_rate": head["purchase_rate"],
                        "net_rate": head["net_rate"]}
            else:
                fm = coll["metadata_by_variant"][raw]
                head = None
                packs = {fm["pack_size"]}
                pack_disagree = False
                meta = {"expiry": fm["expiry"], "pack_src": fm["pack_size"],
                        "mrp": fm["mrp"], "purchase_rate": fm["purchase_rate"],
                        "net_rate": fm["net_rate"]}
            alias = group_aliases[raw]
            allow_existing = not (has_stripped_collision and raw != canonical)
            pack = 0.0 if pack_disagree else _resolve_pack_size(
                meta["pack_src"], tgt, (tgt, text(alias)),
                existing, item_pack, allow_existing)
            if pack_disagree:
                group_block_reason = (
                    f"repeated rows for exact batch {raw!r} disagree on pack size"
                    f" {sorted(packs)}")
            if pack <= 0 and group_block_reason is None:
                group_block_reason = (
                    f"pack size unresolvable for variant {raw!r} (source 0,"
                    " no usable target/master fallback); divisor 1 never used")
            stock_qty = (net_loose / pack) if pack > 0 else None
            # existing batch id reuse?
            if has_stripped_collision and raw == canonical:
                existing_id = batch_id_by_key.get((tgt, text(alias)))
            elif not has_stripped_collision:
                existing_id = batch_id_by_key.get((tgt, text(alias)))
            else:
                # non-canonical stripped collision: None means a new alias
                # row is created on apply; a present id is our own prior
                # alias (metadata already verified above) and is reused.
                existing_id = batch_id_by_key.get((tgt, text(alias)))
            # Variant-specific metadata update plan: never silently reuse an
            # incompatible existing row.  Compare the stored batch (if any)
            # against this variant's source metadata field by field.
            existing_row = existing.get((tgt, text(alias))) if existing_id is not None else None
            _diffs = []
            if existing_row is None and existing_id is None:
                metadata_update_plan = (
                    f"INSERT new batch {alias!r} with source metadata"
                    f" (expiry {meta['expiry']}, pack {pack_text(pack) if pack > 0 else '?'},"
                    f" mrp {meta['mrp']}, purchase {meta['purchase_rate']},"
                    f" net {meta['net_rate']}); history rows untouched")
            elif existing_row is not None:
                if text(existing_row.get("expiry")) != text(meta["expiry"]):
                    _diffs.append(f"expiry {existing_row.get('expiry')!r}->{meta['expiry']!r}")
                if text(existing_row.get("pack_size")) != (pack_text(pack) if pack > 0 else ""):
                    _diffs.append(f"pack {existing_row.get('pack_size')!r}->{pack_text(pack) if pack > 0 else ''!r}")
                if float(existing_row.get("mrp") or 0) != float(meta["mrp"] or 0):
                    _diffs.append(f"mrp {existing_row.get('mrp')!r}->{meta['mrp']!r}")
                if float(existing_row.get("purchase_rate") or 0) != float(meta["purchase_rate"] or 0):
                    _diffs.append(f"purchase {existing_row.get('purchase_rate')!r}->{meta['purchase_rate']!r}")
                if float(existing_row.get("net_rate") or 0) != float(meta["net_rate"] or 0):
                    _diffs.append(f"net {existing_row.get('net_rate')!r}->{meta['net_rate']!r}")
                metadata_update_plan = (
                    "none — existing batch metadata already matches this variant"
                    if not _diffs else
                    f"UPDATE batch id {existing_id} fields on apply: " + "; ".join(_diffs)
                    + "; historical invoice-line copies untouched")
            else:
                metadata_update_plan = "none"
            variants_out.append({
                "raw_batch_exact": raw,
                "stripped_batch": stripped_of[raw],
                "alias_batch_no": alias,
                "display_batch_no": display_batch_no(alias),
                "is_canonical": raw == canonical,
                "legacy_items": sorted({r["legacy_item"] for r in rows}) if rows else coll["legacy_items"],
                "expiry": meta["expiry"],
                "pack_size_src": meta["pack_src"],
                "pack_size_resolved": pack if pack > 0 else 0.0,
                "pack_size_text": pack_text(pack) if pack > 0 else "",
                "mrp": meta["mrp"],
                "purchase_rate": meta["purchase_rate"],
                "net_rate": meta["net_rate"],
                "net_loose": net_loose,
                "stock_qty": stock_qty,
                "expired": is_expired(meta["expiry"]),
                "existing_batch_id": existing_id,
                "reuses_existing": existing_id is not None,
                "metadata_update_needed": bool(_diffs) if existing_id is not None else True,
                "metadata_update_plan": metadata_update_plan,
                "source_stockbalance_rows": len(rows) or 1,
                "source_sales_lines": sales_by_raw.get(raw, 0),
                "source_purchase_lines": purch_by_raw.get(raw, 0),
            })
            if pack > 0 and group_block_reason is None:
                resolved_rows.append({
                    "target_item": tgt,
                    "alias_batch_no": alias,
                    "raw_batch_exact": raw,
                    "expiry": meta["expiry"],
                    "pack_size": pack_text(pack),
                    "pack_size_num": pack,
                    "mrp": meta["mrp"],
                    "purchase_rate": meta["purchase_rate"],
                    "net_rate": meta["net_rate"],
                    "net_loose": net_loose,
                    "stock_qty": stock_qty,
                    "expired": is_expired(meta["expiry"]),
                })

        # historical remap analysis (read-only)
        # For merged (stripped-collision) groups: sales FKs currently all on
        # canonical id; lines whose legacy VhID maps to a non-canonical raw
        # would move.  For distinct groups: expect zero moves; verify.
        remap = {"sales_moves_planned": 0, "sales_already_correct": 0,
                 "purchase_lines_documented": 0, "mixed_vouchers": []}
        if group_block_reason is None:
            if has_stripped_collision:
                canon_id = batch_id_by_key.get((tgt, text(canonical)))
                # legacy VhIDs whose sales lines are non-canonical raws
                move_vhs = set()
                for row in dump.iter_rows("salesitemdetail"):
                    if text(row[2]) not in {text(x) for x in coll["legacy_items"]}:
                        continue
                    if str(row[4]) in [r for r in raws_sorted if r != canonical]:
                        new_inv = sale_map.get(text(row[1]))
                        if new_inv is not None:
                            move_vhs.add(new_inv)
                # count target sales lines on canonical id that belong to move set
                if canon_id is not None and move_vhs:
                    placeholders = ",".join("?" * len(move_vhs))
                    q = ("SELECT COUNT(*) FROM sales_invoice_items"
                         " WHERE item_id=? AND stock_batch_id=? AND sales_invoice_id IN"
                         f" ({placeholders})")
                    try:
                        remap["sales_moves_planned"] = conn.execute(
                            q, (tgt, canon_id, *sorted(move_vhs))).fetchone()[0]
                    except sqlite3.Error:
                        remap["sales_moves_planned"] = 0
                remap["purchase_lines_documented"] = sum(
                    purch_by_raw.get(r, 0) for r in raws_sorted)
                # mixed vouchers (same Vh with 2 variants) — informational;
                # 238 has none, so remap is deterministic
                for vh, raws in sales_vh.items():
                    if len([r for r in raws if r in set(raws_sorted)]) > 1:
                        remap["mixed_vouchers"].append(vh)
            else:
                remap["sales_already_correct"] = sum(
                    sales_by_raw.get(r, 0) for r in raws_sorted)
                remap["purchase_lines_documented"] = sum(
                    purch_by_raw.get(r, 0) for r in raws_sorted)
                for vh, raws in sales_vh.items():
                    if len([r for r in raws if r in set(raws_sorted)]) > 1:
                        remap["mixed_vouchers"].append(vh)

        status = "blocked" if group_block_reason else "resolved"
        groups_out.append({
            "target_item": tgt,
            "normalized_key": loose,
            "collision_variant": coll["collision_variant"],
            "raw_variants": raws_sorted,
            "legacy_items": coll["legacy_items"],
            "has_stripped_collision": has_stripped_collision,
            "canonical_raw": canonical,
            "conflicting_fields": coll["conflicting_fields"],
            "agreeing_fields": coll["agreeing_fields"],
            "metadata_conflict": coll["metadata_conflict"],
            "status": status,
            "block_reason": group_block_reason,
            "variants": variants_out,
            "remap": remap,
        })
        if group_block_reason:
            # drop this group's rows from the resolved set
            resolved_rows = [r for r in resolved_rows
                             if not (r["target_item"] == tgt and r["raw_batch_exact"] in set(raws_sorted))]

    # reconciliation: source keys vs mapped/withheld, incl. pos/zero/neg.
    # Mathematical invariant: every base source key is classified exactly
    # once.  Base: source_keys == len(rows) + len(withheld_keys) with zero
    # overlap (verified by the audit tool's mapping_partition_ok).  Here the
    # 16 withheld stripped keys expand to 17 raw variants (1182's single
    # stripped key holds 2 raws); resolution maps variants, so both counts
    # are reported with no omissions.
    pos = sum(1 for r in resolved_rows if r["stock_qty"] > 0)
    zer = sum(1 for r in resolved_rows if r["stock_qty"] == 0)
    neg_rows = [r for r in resolved_rows if r["stock_qty"] < 0]
    total_variants = sum(len(g["raw_variants"]) for g in groups_out)
    mapped_variants = sum(len(g["raw_variants"]) for g in groups_out if g["status"] == "resolved")
    withheld_stripped_covered = sum(
        len([w for w in base.withheld_keys
             if w["target_item"] == g["target_item"]
             and loose_batch_no(w["batch_no"]) == g["normalized_key"]])
        for g in groups_out)
    mapped_keys = {(r["target_item"], r["alias_batch_no"]) for r in resolved_rows}
    uc = trace_uc_rose(dump, conn, base)
    return {
        "base_plan": base.as_dict(),
        "groups": groups_out,
        "resolved_rows": resolved_rows,
        "resolved_groups": sum(1 for g in groups_out if g["status"] == "resolved"),
        "blocked_groups": sum(1 for g in groups_out if g["status"] == "blocked"),
        "reconciliation": {
            "collision_variants_total": total_variants,
            "collision_variants_mapped": mapped_variants,
            "collision_variants_withheld": total_variants - mapped_variants,
            "withheld_stripped_keys_total": len(base.withheld_keys),
            "withheld_stripped_keys_covered": withheld_stripped_covered,
            "withheld_stripped_keys_omitted": len(base.withheld_keys) - withheld_stripped_covered,
            "resolved_positive": pos,
            "resolved_zero": zer,
            "resolved_negative": len(neg_rows),
            "resolved_negatives": neg_rows,
            "base_target_keys": len(base.rows),
            "base_withheld": len(base.withheld_keys),
            "base_source_keys": base.source_keys,
            "mapping_partition_math": (
                f"{base.source_keys} source keys = {len(base.rows)} base rows +"
                f" {len(base.withheld_keys)} withheld; resolution covers"
                f" {withheld_stripped_covered}/{len(base.withheld_keys)} withheld"
                f" stripped keys as {mapped_variants}/{total_variants} variants"),
        },
        "uc_rose": uc,
    }


# ── reporting ────────────────────────────────────────────────────────

def render_markdown(rep: dict) -> str:
    res = rep["resolution"]
    base = res["base_plan"]
    L = [
        "# Phase 3 — Collision-Safe Resolution (STAGING ONLY, NO APPLY)",
        "",
        f"- Source: `{rep['source_file']}` ({rep['source_bytes']:,} bytes, READ-ONLY)",
        f"- Target (read-only): `{rep['db_path']}`",
        f"- Mode: `{rep['mode']}` — this report plans distinct identities only.",
        "  No stock quantity was written and no historical FK was changed.",
        "",
        "## Safety",
        "",
        "- Never merges distinct source batches by normalized key.",
        "- Exact originals retained per variant below + in JSON provenance.",
        "- Synthetic aliases only where stripping collides; otherwise existing",
        "  distinct identities are reused (no renames, no text-linkage breaks).",
        "- Quantities are per-variant `(purchase-sales)/pack`; no double-counted",
        "  adjustments; missing pack stays blocking (never `/1`).",
        "",
        "## Base plan (blocking, for reference)",
        "",
        f"- source rows: {base['source_rows']}",
        f"- distinct target keys: {base['source_keys']}",
        f"- keys in base plan: {base['target_keys']}",
        f"- withheld: {len(base['withheld_keys'])}",
        f"- normalized collisions: {len(base['normalized_collisions'])}",
        f"- missing pack: {len(base['missing_pack_size'])}",
        "",
        "## Resolution summary",
        "",
        f"- collision groups: {len(res['groups'])} (grouped by target_item + normalized key)",
        f"- resolved: {res['resolved_groups']}",
        f"- still blocked: {res['blocked_groups']}",
        f"- variants mapped: {res['reconciliation']['collision_variants_mapped']}/"
        f"{res['reconciliation']['collision_variants_total']}",
        f"- withheld stripped keys covered: "
        f"{res['reconciliation']['withheld_stripped_keys_covered']}/"
        f"{res['reconciliation']['withheld_stripped_keys_total']}",
        f"- partition math: {res['reconciliation']['mapping_partition_math']}",
        f"- resolved quantities: positive "
        f"{res['reconciliation']['resolved_positive']}, zero "
        f"{res['reconciliation']['resolved_zero']}, negative "
        f"{res['reconciliation']['resolved_negative']}",
        "",
    ]
    for g in res["groups"]:
        L += [
            f"### item {g['target_item']} · `{g['normalized_key']}` — {g['status'].upper()}",
            "",
            f"- variant: {g['collision_variant']}; stripped collision: "
            f"{g['has_stripped_collision']}; canonical: `{g['canonical_raw']}`",
            f"- conflicting: `{', '.join(g['conflicting_fields']) or '—'}`; "
            f"agreeing: `{', '.join(g['agreeing_fields']) or '—'}`",
        ]
        if g["status"] == "blocked":
            L += [f"- BLOCK REASON: {g['block_reason']}", ""]
        else:
            L += [f"- sales moves planned: {g['remap']['sales_moves_planned']}; "
                  f"sales already correct: {g['remap']['sales_already_correct']}; "
                  f"purchase lines documented: {g['remap']['purchase_lines_documented']}; "
                  f"mixed vouchers: {len(g['remap']['mixed_vouchers'])}", ""]
        L += ["| exact raw | alias (target identity) | display | expiry | pack | mrp |"
              " purch.rate | net rate | net loose | stock | existing id | sales | purch |",
              "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"
              " ---: | ---: |"]
        for v in g["variants"]:
            L.append(
                f"| `{v['raw_batch_exact']}` | `{v['alias_batch_no']}` | "
                f"`{v['display_batch_no']}` | {v['expiry']} | {v['pack_size_text']} | "
                f"{v['mrp']} | {v['purchase_rate']} | {v['net_rate']} | "
                f"{v['net_loose']} | "
                f"{v['stock_qty'] if v['stock_qty'] is not None else 'BLOCKED'} | "
                f"{v['existing_batch_id'] or 'NEW'} | {v['source_sales_lines']} | "
                f"{v['source_purchase_lines']} |")
        L += ["- variant-specific metadata plans (existing rows never reused blindly):", ""]
        for v in g["variants"]:
            L.append(f"  - `{v['raw_batch_exact']}` → `{v['alias_batch_no']}`: "
                     f"{v.get('metadata_update_plan', 'none')}")
        L += [""]
    uc = res["uc_rose"]
    L += [
        "## UC-ROSE (unchanged, from base `plan_rows`)",
        "",
        f"- legacy 832 → target {uc['mapped_target_item_id']}: "
        f"{len(uc['plan_rows'])} projected batches, "
        f"{len(uc['projected_positive_batches'])} with stock, "
        f"{len(uc['projected_counter_sale_rows'])} sellable, "
        f"{len(uc['current_counter_sale_rows'])} offered now.",
        "",
        "_End of resolution report — no quantities applied, no FKs changed._",
        "",
    ]
    return "\n".join(L)


def write_reports(rep: dict) -> None:
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(rep, indent=2, default=str), encoding="utf-8")
    REPORT_MD.write_text(render_markdown(rep), encoding="utf-8")


def connect_ro(path: Path) -> sqlite3.Connection:
    uri = "file:" + str(path).replace("\\", "/") + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def sha256_file(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--source", default=str(DEFAULT_SOURCE))
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--clone-to", default=None)
    args = ap.parse_args(argv)

    db_path = Path(args.db).resolve()
    src_path = Path(args.source).resolve()

    if args.clone_to:
        dest = Path(args.clone_to).resolve()
        dest.parent.mkdir(parents=True, exist_ok=True)
        src = connect_ro(db_path)
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

    if not args.report:
        print("nothing to do: pass --report (read-only) or --clone-to PATH",
              file=sys.stderr)
        return 2
    if not db_path.is_file():
        print(f"ERROR: database not found: {db_path}", file=sys.stderr)
        return 2

    dump = LegacyDump(src_path)
    conn = connect_ro(db_path)
    try:
        resolution = resolve_plan(dump, conn)
        rep = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "source_file": str(src_path),
            "source_bytes": src_path.stat().st_size,
            "db_path": str(db_path),
            "db_sha256": sha256_file(db_path),
            "mode": "resolution-report",
            "resolution": resolution,
        }
        write_reports(rep)
    finally:
        conn.close()

    print("=" * 78)
    print(f"target (read-only): {rep['db_path']}")
    print(f"groups: {len(resolution['groups'])}  resolved: "
          f"{resolution['resolved_groups']}  blocked: {resolution['blocked_groups']}")
    for g in resolution["groups"]:
        print(f"  {g['status'][:4].upper()}: item {g['target_item']} "
              f"`{g['normalized_key']}` -> "
              f"{', '.join(v['alias_batch_no'] for v in g['variants'])}")
    print(f"reports: {REPORT_MD}\n         {REPORT_JSON}")
    if resolution["blocked_groups"]:
        print(f"NOTE: {resolution['blocked_groups']} group(s) remain blocked — "
              "see report; nothing was applied.", file=sys.stderr)
        return 6
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
