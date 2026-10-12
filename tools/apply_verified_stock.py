"""Apply the verified historical stock migration (staging-first, one transaction).

Combines the latest ``legacy_stock_migration.build_plan`` (7776
non-colliding keys) with ``legacy_stock_resolution.resolve_plan`` (8
collision groups, 17 exact variants, 1 synthetic alias, 21 CARE remaps,
durable ``legacy_batch_resolution`` provenance).

Safety
------
* Staging-first: test on a fresh backup-API clone; live needs
  ``--confirm-live`` AND the app (main.py) must not be running.
* One transaction (BEGIN IMMEDIATE … COMMIT); any failed check rolls back
  with no partial writes.
* Idempotent: quantities are SET (never incremented); aliases addressed by
  (item, batch_no) unique key; remaps target exact line IDs; provenance
  table rewritten deterministically.
* Never ``/1`` for missing pack; never double-adds adjustments (uses
  stockbalance net only); never merges conflicting metadata.
* Never touches LOCALAPPDATA/EXE/dist; never replaces live with staging.

Usage
-----
    python tools/apply_verified_stock.py --db staging/stock_apply_stage.db [--source ...]
    python tools/apply_verified_stock.py --db data/pharmacy.db --confirm-live
"""

from __future__ import annotations

import argparse
import hashlib
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from database.legacy_migration import LegacyDump
from tools import legacy_stock_migration as mig
from tools import legacy_stock_resolution as reso

DEFAULT_SOURCE = mig.DEFAULT_SOURCE
DEFAULT_DB = mig.DEFAULT_DB
LIVE_RESOLVED = Path(DEFAULT_DB).resolve()


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for ch in iter(lambda: fh.read(1 << 20), b""):
            h.update(ch)
    return h.hexdigest()


def app_running() -> list[str]:
    """PIDs/command lines suggesting the app is open (best effort)."""
    hits = []
    try:
        import subprocess
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name LIKE '%python%'\" | Select-Object -ExpandProperty CommandLine"],
            capture_output=True, text=True, timeout=30)
        for line in (out.stdout or "").splitlines():
            if "main.py" in line:
                hits.append(line.strip())
    except Exception:
        pass
    return hits


def build_verified(dump: LegacyDump, conn: sqlite3.Connection):
    plan = mig.build_plan(dump, conn)
    resolution = reso.resolve_plan(dump, conn)
    return plan, resolution


def check_ready(plan, resolution) -> list[str]:
    errs = []
    if len(resolution["groups"]) != 8:
        errs.append(f"expected 8 collision groups, got {len(resolution['groups'])}")
    if resolution["blocked_groups"] != 0:
        errs.append(f"{resolution['blocked_groups']} collision groups still blocked")
    rec = resolution["reconciliation"]
    if rec["withheld_stripped_keys_covered"] != 16 or rec["withheld_stripped_keys_omitted"] != 0:
        errs.append(f"withheld coverage wrong: {rec}")
    if rec["collision_variants_mapped"] != 17:
        errs.append(f"expected 17 variants mapped, got {rec['collision_variants_mapped']}")
    # 1199 18-pack present in correct target
    found18 = any(r["target_item"] == 1199 and abs(r["stock_qty"] - 18.0) < 1e-9
                  for r in resolution["resolved_rows"])
    if not found18:
        errs.append("1199 CARE UNI 18.0-pack row missing")
    # 21 remaps planned for 1182
    g1182 = next((g for g in resolution["groups"] if g["target_item"] == 1182), None)
    if not g1182 or g1182["remap"]["sales_moves_planned"] != 21:
        errs.append(f"1182 remap != 21: {g1182['remap'] if g1182 else None}")
    if plan.missing_pack_size:
        errs.append(f"missing pack sizes: {len(plan.missing_pack_size)} (never /1)")
    return errs


def apply_one_transaction(conn: sqlite3.Connection, dump: LegacyDump,
                          plan, resolution) -> dict:
    """Everything in ONE transaction. Raises on any failure (rolls back)."""
    cur = conn.cursor()
    cur.execute("BEGIN IMMEDIATE")
    try:
        # 1. base non-colliding rows (SET quantities + metadata)
        existing = {}
        for r in conn.execute("SELECT id, item_id, batch_no FROM stock_batches"):
            existing[(int(r["item_id"]), mig.text(r["batch_no"]))] = int(r["id"])
        updated = inserted = 0
        for row in plan.rows:
            key = (row["target_item"], row["batch_no"])
            bid = existing.get(key)
            if bid is None:
                c = conn.execute(
                    """INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size,
                       mrp, purchase_rate, net_rate, stock_qty)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (row["target_item"], row["batch_no"], row["expiry"], row["pack_size"],
                     row["mrp"], row["purchase_rate"], row["net_rate"], row["stock_qty"]))
                existing[key] = c.lastrowid
                inserted += 1
            else:
                conn.execute(
                    """UPDATE stock_batches SET stock_qty=?,
                       expiry=CASE WHEN ?<>'' THEN ? ELSE expiry END,
                       pack_size=CASE WHEN ?<>'' THEN ? ELSE pack_size END,
                       mrp=CASE WHEN ?<>0 THEN ? ELSE mrp END,
                       purchase_rate=CASE WHEN ?<>0 THEN ? ELSE purchase_rate END,
                       net_rate=CASE WHEN ?<>0 THEN ? ELSE net_rate END
                       WHERE id=?""",
                    (row["stock_qty"], row["expiry"], row["expiry"], row["pack_size"],
                     row["pack_size"], row["mrp"], row["mrp"], row["purchase_rate"],
                     row["purchase_rate"], row["net_rate"], row["net_rate"], bid))
                updated += 1
        # 2. collision variants: variant-specific metadata + quantities
        alias_ids = {}
        for g in resolution["groups"]:
            for v in g["variants"]:
                tgt, alias = g["target_item"], v["alias_batch_no"]
                if v["existing_batch_id"] is not None:
                    conn.execute(
                        """UPDATE stock_batches SET stock_qty=?,
                           expiry=CASE WHEN ?<>'' THEN ? ELSE expiry END,
                           pack_size=CASE WHEN ?<>'' THEN ? ELSE pack_size END,
                           mrp=CASE WHEN ?<>0 THEN ? ELSE mrp END,
                           purchase_rate=CASE WHEN ?<>0 THEN ? ELSE purchase_rate END,
                           net_rate=CASE WHEN ?<>0 THEN ? ELSE net_rate END
                           WHERE id=?""",
                        (v["stock_qty"], v["expiry"], v["expiry"],
                         v["pack_size_text"], v["pack_size_text"],
                         v["mrp"], v["mrp"], v["purchase_rate"], v["purchase_rate"],
                         v["net_rate"], v["net_rate"], v["existing_batch_id"]))
                    alias_ids[(tgt, alias)] = v["existing_batch_id"]
                    updated += 1
                else:
                    c = conn.execute(
                        """INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size,
                           mrp, purchase_rate, net_rate, stock_qty)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (tgt, alias, v["expiry"], v["pack_size_text"], v["mrp"],
                         v["purchase_rate"], v["net_rate"], v["stock_qty"]))
                    alias_ids[(tgt, alias)] = c.lastrowid
                    inserted += 1
        # 3. 21 CARE remaps: recompute exact line IDs now (never from old report)
        sale_map = {mig.text(r["legacy_id"]): int(r["new_id"]) for r in
                    conn.execute("SELECT legacy_id, new_id FROM legacy_id_map WHERE entity='sale'")}
        item1182 = next(g["target_item"] for g in resolution["groups"] if g["target_item"] == 1182)
        canon_id = conn.execute("SELECT id FROM stock_batches WHERE item_id=? AND batch_no='CARE'",
                                (item1182,)).fetchone()
        canon_id = int(canon_id[0])
        new_alias_id = alias_ids.get((item1182, "CARE[exact=' CARE']"))
        if not new_alias_id:
            raise RuntimeError("CARE alias id missing")
        move_inv = set()
        for row in dump.iter_rows("salesitemdetail"):
            if mig.text(row[2]) != "238" or str(row[4]) != " CARE":
                continue
            nid = sale_map.get(mig.text(row[1]))
            if nid is not None:
                move_inv.add(nid)
        if len(move_inv) != 21:
            raise RuntimeError(f"expected 21 CARE move invoices, found {len(move_inv)}")
        ph = ",".join("?" * len(move_inv))
        lines = conn.execute(
            f"SELECT id FROM sales_invoice_items WHERE item_id=? AND stock_batch_id=? "
            f"AND sales_invoice_id IN ({ph}) ORDER BY id",
            (item1182, canon_id, *sorted(move_inv))).fetchall()
        if len(lines) != 21:
            raise RuntimeError(
                f"expected 21 CARE lines to remap, found {len(lines)}")
        for (lid,) in lines:
            conn.execute("UPDATE sales_invoice_items SET stock_batch_id=? WHERE id=?",
                         (new_alias_id, int(lid)))
        # canonical 112 must remain
        remain = conn.execute("SELECT COUNT(*) FROM sales_invoice_items WHERE item_id=? AND stock_batch_id=?",
                              (item1182, canon_id)).fetchone()[0]
        # 4. durable provenance (deterministic rewrite)
        reso.write_provenance(conn, resolution)
        # 5. audit row
        conn.execute(
            """CREATE TABLE IF NOT EXISTS legacy_stock_migration (
               id INTEGER PRIMARY KEY AUTOINCREMENT, applied_at TEXT NOT NULL,
               source_file TEXT NOT NULL, source_sha256 TEXT NOT NULL,
               source_keys INTEGER NOT NULL, rows_updated INTEGER NOT NULL,
               rows_inserted INTEGER NOT NULL, positives INTEGER NOT NULL,
               zeros INTEGER NOT NULL, negatives INTEGER NOT NULL, conflicts INTEGER NOT NULL)""")
        conn.execute(
            """INSERT INTO legacy_stock_migration (applied_at, source_file, source_sha256,
               source_keys, rows_updated, rows_inserted, positives, zeros, negatives, conflicts)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (datetime.now().isoformat(timespec="seconds"), str(DEFAULT_SOURCE),
             sha256_file(DEFAULT_SOURCE), plan.source_keys, updated, inserted,
             plan.positives, plan.zeros, len(plan.negatives), len(plan.conflicts)))
        conn.commit()
        return {"updated": updated, "inserted": inserted, "remapped": len(lines),
                "alias_ids": {f"{k}": v for k, v in alias_ids.items()}}
    except Exception:
        conn.rollback()
        raise


def verify_after(conn: sqlite3.Connection, dump: LegacyDump, plan, resolution) -> dict:
    out = {}
    out["integrity"] = conn.execute("PRAGMA integrity_check").fetchone()[0]
    out["fk"] = len(conn.execute("PRAGMA foreign_key_check").fetchall())
    out["dups"] = conn.execute(
        "SELECT COUNT(*) FROM (SELECT item_id, batch_no FROM stock_batches "
        "GROUP BY item_id, batch_no HAVING COUNT(*)>1)").fetchone()[0]
    out["orphans"] = conn.execute(
        "SELECT COUNT(*) FROM stock_batches sb LEFT JOIN items i ON i.id=sb.item_id "
        "WHERE i.id IS NULL").fetchone()[0]
    t = conn.execute("SELECT COUNT(*) n, SUM(CASE WHEN stock_qty>0 THEN 1 ELSE 0 END) pos,"
                     " SUM(CASE WHEN stock_qty=0 THEN 1 ELSE 0 END) zer,"
                     " SUM(CASE WHEN stock_qty<0 THEN 1 ELSE 0 END) neg FROM stock_batches").fetchone()
    out.update(total=t["n"], positive=t["pos"], zero=t["zer"], negative=t["neg"])
    # source-to-target quantities: base rows + resolved variants
    mm = miss = 0
    for row in plan.rows:
        r = conn.execute("SELECT stock_qty FROM stock_batches WHERE item_id=? AND batch_no=?",
                         (row["target_item"], row["batch_no"])).fetchone()
        if r is None:
            miss += 1
        elif abs(float(r["stock_qty"]) - row["stock_qty"]) > 1e-6:
            mm += 1
    for r in resolution["resolved_rows"]:
        q = conn.execute("SELECT stock_qty FROM stock_batches WHERE item_id=? AND batch_no=?",
                         (r["target_item"], r["alias_batch_no"])).fetchone()
        if q is None:
            miss += 1
        elif abs(float(q["stock_qty"]) - r["stock_qty"]) > 1e-6:
            mm += 1
    out["mismatches"] = mm
    out["missing"] = miss
    # provenance recoverability from table alone
    expected = {(g["target_item"], v["alias_batch_no"]): v["raw_batch_exact"]
                for g in resolution["groups"] for v in g["variants"]}
    out["provenance"] = reso.verify_provenance_reconstruction(conn, expected)
    # CARE remap check
    out["care_new_count"] = conn.execute(
        "SELECT COUNT(*) FROM sales_invoice_items WHERE item_id=1182 AND stock_batch_id="
        "(SELECT id FROM stock_batches WHERE item_id=1182 AND batch_no='CARE[exact='' CARE'']')").fetchone()[0]
    out["care_canon_count"] = conn.execute(
        "SELECT COUNT(*) FROM sales_invoice_items WHERE item_id=1182 AND stock_batch_id="
        "(SELECT id FROM stock_batches WHERE item_id=1182 AND batch_no='CARE')").fetchone()[0]
    # Counter Sale availability (same rule as app, no UI import)
    def expired(v):
        from datetime import datetime as dt
        v = (v or "").strip()
        if not v:
            return False
        try:
            d = dt.strptime(v, "%Y-%m-%d").date()
        except ValueError:
            try:
                m, y = v.split("/", 1)
                d = dt(2000 + int(y), int(m), 1).date()
            except (ValueError, IndexError):
                return False
        return d < dt.now().date()
    def avail(item_id):
        rows = conn.execute("SELECT batch_no, expiry, stock_qty FROM stock_batches "
                            "WHERE item_id=? AND stock_qty>0", (item_id,)).fetchall()
        return sorted([dict(r) for r in rows if not expired(r["expiry"])],
                      key=lambda b: (b["expiry"] or "", b["batch_no"] or ""))
    for label, iid in (("BIO D3 PLUS", 951), ("UC-ROSE", 1775)):
        a = avail(iid)
        out[f"avail_{iid}"] = [(b["batch_no"], b["expiry"], b["stock_qty"]) for b in a]
    out["ok"] = (out["integrity"] == "ok" and out["fk"] == 0 and out["dups"] == 0
                 and out["orphans"] == 0 and out["mismatches"] == 0 and out["missing"] == 0
                 and out["provenance"]["ok"] and out["care_new_count"] == 21
                 and out["care_canon_count"] == 112)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--source", default=str(DEFAULT_SOURCE))
    ap.add_argument("--confirm-live", action="store_true")
    ap.add_argument("--clone-to", default=None)
    args = ap.parse_args(argv)
    db_path = Path(args.db).resolve()
    src_path = Path(args.source).resolve()
    if args.clone_to:
        dest = Path(args.clone_to).resolve()
        dest.parent.mkdir(parents=True, exist_ok=True)
        s = sqlite3.connect(f"file:{str(db_path).replace(chr(92), '/')}?mode=ro", uri=True, timeout=30)
        try:
            o = sqlite3.connect(str(dest))
            try:
                s.backup(o)
                o.commit()
            finally:
                o.close()
        finally:
            s.close()
        print(f"cloned {db_path} -> {dest} ({dest.stat().st_size:,} bytes)")
        return 0
    is_live = str(db_path) == str(LIVE_RESOLVED)
    if is_live and not args.confirm_live:
        print("REFUSING: live target needs --confirm-live", file=sys.stderr)
        return 3
    if is_live and app_running():
        print("REFUSING: application (main.py) appears running; close it first", file=sys.stderr)
        return 4
    dump = LegacyDump(src_path)
    conn = sqlite3.connect(str(db_path), timeout=60)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        plan, resolution = build_verified(dump, conn)
        errs = check_ready(plan, resolution)
        if errs:
            print("NOT READY:", file=sys.stderr)
            for e in errs:
                print(f"  - {e}", file=sys.stderr)
            return 5
        applied = apply_one_transaction(conn, dump, plan, resolution)
        # fresh read for verification
        v = verify_after(conn, dump, plan, resolution)
        print(f"applied: {applied}")
        print(f"verify: ok={v['ok']} integrity={v['integrity']} fk={v['fk']} dups={v['dups']} "
              f"mism={v['mismatches']} miss={v['missing']} total={v['total']} "
              f"pos={v['positive']} zero={v['zero']} neg={v['negative']}")
        print(f"CARE remapped={v['care_new_count']} canonical={v['care_canon_count']}")
        print(f"BIO avail: {v.get('avail_951')}")
        print(f"UC-ROSE avail: {v.get('avail_1775')}")
        return 0 if v["ok"] else 6
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
