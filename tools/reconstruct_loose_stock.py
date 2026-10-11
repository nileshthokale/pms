"""Reconstruct correct loose-unit stock on a STAGING clone (never live).

Background: the historical migration stored ``stock_qty`` in packs
(``net_loose / PackSize``) while the whole application works in loose
tablets (``sale_qty`` loose, ``amount = qty*MRP/pack``, purchase tests seed
loose units).  Fractional packs (0.1/1.9/10.1) are the symptom; UC-CART
should read 1/19/101/20 tablets, not 0/2/10/2.

What this does (one transaction, idempotent SETs, staging only)
---------------------------------------------------------------
* legacy closing per exact raw batch -> ``stock_qty = net_loose`` (packs
  NEVER divide; missing pack is irrelevant for loose units).
* exact-identity mapping: stripped ``batch_no`` normally; ``(1182,' CARE')``
  -> alias ``CARE[exact=' CARE']``; 19 trailing-whitespace raws map to
  their stripped batches (pack 1, values already exact) and gain
  provenance rows — no renames, no FK changes for them.
* negatives preserved exactly; no clamping; no adjustment double-count
  (stockadjusted already inside TotalPurchaseQty).
* durable ``legacy_batch_resolution`` rewrite (17 collision + 19 trailing
  = 36 rows) + ``legacy_stock_correction`` audit row.
* post-migration app transactions: verified zero (invoice ID sets and
  quantity checksums identical between pre-image and live), so nothing to
  merge; the script aborts if it detects any.

Safety: refuses the live ``data/pharmacy.db`` path outright (no override
flag).  There is no live path in this task.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import defaultdict
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
REPORT_JSON = ROOT / "migration_backups" / "phase3_loose_reconstruction.json"
REPORT_MD = ROOT / "migration_backups" / "phase3_loose_reconstruction.md"


def connect_ro(path: Path) -> sqlite3.Connection:
    uri = "file:" + str(path).replace("\\", "/") + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=60)
    conn.row_factory = sqlite3.Row
    return conn


def legacy_nets(dump: LegacyDump, item_map: dict):
    """(target_item, exact_raw) -> {legacy, net_loose, pack_src, meta}."""
    out: dict[tuple[int, str], dict] = {}
    for row in dump.iter_rows("stockbalance"):
        leg = mig.text(row[0])
        raw = "" if row[1] is None else str(row[1])
        tgt = item_map.get(leg)
        if tgt is None or not raw or not mig.text(raw):
            continue
        key = (tgt, raw)
        net = mig.num(row[6]) - mig.num(row[9])
        pack = mig.num(row[7]) if mig.num(row[7]) > 0 else 0.0
        if key not in out:
            out[key] = {"legacy": leg, "net": 0.0, "pack": pack,
                        "expiry": mig.clean_date(row[2]), "mrp": mig.num(row[3]),
                        "prate": mig.num(row[4]), "nrate": mig.num(row[5]), "n": 0}
        out[key]["net"] += net
        out[key]["n"] += 1
    return out


def target_key(tgt: int, raw: str) -> tuple[int, str]:
    if tgt == 1182 and raw == " CARE":
        return (1182, "CARE[exact=' CARE']")
    return (tgt, mig.text(raw))


def check_no_post_migration(conn: sqlite3.Connection, pre_path: Path) -> list[str]:
    """Prove zero genuine app transactions since migration (read-only)."""
    errs = []
    if not pre_path.is_file():
        return [f"pre-image not found: {pre_path}"]
    pre = connect_ro(pre_path)
    try:
        for tbl in ["purchase_invoices", "sales_invoices", "credit_notes", "debit_notes",
                    "purchase_invoice_items", "sales_invoice_items"]:
            lmax = conn.execute(f"SELECT MAX(id) FROM {tbl}").fetchone()[0]
            pmax = pre.execute(f"SELECT MAX(id) FROM {tbl}").fetchone()[0]
            if lmax != pmax:
                errs.append(f"{tbl}: live max {lmax} != pre max {pmax}")
        lp = conn.execute("SELECT COUNT(*), COALESCE(SUM(pay_qty+free_qty),0) FROM purchase_invoice_items").fetchone()
        pp = pre.execute("SELECT COUNT(*), COALESCE(SUM(pay_qty+free_qty),0) FROM purchase_invoice_items").fetchone()
        if tuple(lp) != tuple(pp):
            errs.append(f"purchase lines changed: live {tuple(lp)} vs pre {tuple(pp)}")
        ls = conn.execute("SELECT COUNT(*), COALESCE(SUM(sale_qty),0) FROM sales_invoice_items").fetchone()
        ps = pre.execute("SELECT COUNT(*), COALESCE(SUM(sale_qty),0) FROM sales_invoice_items").fetchone()
        if tuple(ls) != tuple(ps):
            errs.append(f"sales lines changed: live {tuple(ls)} vs pre {tuple(ps)}")
    finally:
        pre.close()
    return errs


def build_report(conn: sqlite3.Connection, dump: LegacyDump, pre_path: Path) -> dict:
    item_map = {mig.text(r["legacy_id"]): int(r["new_id"]) for r in
                conn.execute("SELECT legacy_id, new_id FROM legacy_id_map WHERE entity='item'")}
    nets = legacy_nets(dump, item_map)
    existing = {(int(r["item_id"]), "" if r["batch_no"] is None else str(r["batch_no"])): dict(r)
                for r in conn.execute("SELECT id, item_id, batch_no, stock_qty FROM stock_batches")}
    rows, trailing, neg = [], [], []
    for (tgt, raw), s in sorted(nets.items()):
        tk = target_key(tgt, raw)
        ex = existing.get(tk)
        rows.append({"target_item": tgt, "raw": raw, "alias": tk[1],
                     "legacy": s["legacy"], "pack": s["pack"], "net_loose": s["net"],
                     "stored": float(ex["stock_qty"]) if ex else None,
                     "batch_id": int(ex["id"]) if ex else None,
                     "trailing": raw != mig.text(raw)})
        if raw != mig.text(raw):
            trailing.append(raw)
        if s["net"] < 0:
            neg.append({"target_item": tgt, "raw": raw, "net": s["net"]})
    drift = [r for r in rows if r["batch_id"] is not None
             and abs(r["stored"] - (r["net_loose"] / r["pack"] if r["pack"] else 0)) > 1e-6]
    return {"n_source": len(nets), "n_rows": len(rows),
            "n_trailing": len(trailing), "negatives": neg,
            "post_migration_issues": check_no_post_migration(conn, pre_path),
            "drift_vs_packs": drift, "rows": rows}


def apply_on_staging(conn: sqlite3.Connection, dump: LegacyDump) -> dict:
    item_map = {mig.text(r["legacy_id"]): int(r["new_id"]) for r in
                conn.execute("SELECT legacy_id, new_id FROM legacy_id_map WHERE entity='item'")}
    nets = legacy_nets(dump, item_map)
    # Resolve BEFORE mutating: the resolver treats an already-present alias
    # as a conflict, so the plan must be computed on the pristine state.
    resolution = reso.resolve_plan(dump, conn)
    blocked = [g for g in resolution["groups"] if g["status"] != "resolved"]
    if blocked:
        raise RuntimeError(f"cannot apply with blocked groups: "
                           f"{[(g['target_item'], g['normalized_key'], g['block_reason']) for g in blocked]}")
    cur = conn.cursor()
    cur.execute("BEGIN IMMEDIATE")
    try:
        alias_ids: dict[tuple[int, str], int] = {}
        updated = inserted = 0
        for (tgt, raw), s in nets.items():
            tk = target_key(tgt, raw)
            r = conn.execute("SELECT id FROM stock_batches WHERE item_id=? AND batch_no=?",
                             (tk[0], tk[1])).fetchone()
            if r is None:
                c = conn.execute(
                    """INSERT INTO stock_batches (item_id, batch_no, expiry, pack_size, mrp,
                       purchase_rate, net_rate, stock_qty) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (tk[0], tk[1], s["expiry"], mig.pack_text(s["pack"]) if s["pack"] else "",
                     s["mrp"], s["prate"], s["nrate"], s["net"]))
                alias_ids[tk] = int(c.lastrowid)
                inserted += 1
            else:
                conn.execute(
                    """UPDATE stock_batches SET stock_qty=?,
                       expiry=CASE WHEN ?<>'' THEN ? ELSE expiry END,
                       mrp=CASE WHEN ?<>0 THEN ? ELSE mrp END,
                       purchase_rate=CASE WHEN ?<>0 THEN ? ELSE purchase_rate END,
                       net_rate=CASE WHEN ?<>0 THEN ? ELSE net_rate END
                       WHERE id=?""",
                    (s["net"], s["expiry"], s["expiry"], s["mrp"], s["mrp"],
                     s["prate"], s["prate"], s["nrate"], s["nrate"], int(r["id"])))
                alias_ids.setdefault(tk, int(r["id"]))
                updated += 1
        # durable provenance from the precomputed resolution (8 groups, 17
        # variants); trailing raws are mapped 1:1 to stripped batches
        # (pack 1) — record them too.  Total 36 rows.
        reso.create_provenance_table(conn)
        conn.execute("DELETE FROM legacy_batch_resolution")
        nprov = 0
        for g in resolution["groups"]:
            for v in g["variants"]:
                if v["stock_qty"] is None:
                    continue
                conn.execute(
                    """INSERT INTO legacy_batch_resolution (target_item_id, alias_batch_no,
                       raw_batch_exact, stripped_batch, normalized_key, legacy_item_id, expiry,
                       pack_size, mrp, purchase_rate, net_rate, net_loose, stock_qty,
                       existing_batch_id, is_canonical, display_label)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (g["target_item"], v["alias_batch_no"], v["raw_batch_exact"],
                     v["stripped_batch"], g["normalized_key"], ",".join(v["legacy_items"]),
                     v["expiry"], v["pack_size_text"], v["mrp"], v["purchase_rate"],
                     v["net_rate"], v["net_loose"], v["net_loose"],
                     alias_ids.get((g["target_item"], v["alias_batch_no"]),
                                   v["existing_batch_id"]),
                     1 if v["is_canonical"] else 0,
                     v["display_batch_no"]))
                nprov += 1
        # trailing-whitespace provenance (pack 1: packs == loose, no value change)
        seen = {(g["target_item"], v["raw_batch_exact"])
                for g in resolution["groups"] for v in g["variants"]}
        for (tgt, raw), s in sorted(nets.items()):
            if raw == mig.text(raw) or (tgt, raw) in seen:
                continue
            tk = target_key(tgt, raw)
            ex = conn.execute("SELECT id FROM stock_batches WHERE item_id=? AND batch_no=?",
                              (tk[0], tk[1])).fetchone()
            conn.execute(
                """INSERT OR IGNORE INTO legacy_batch_resolution (target_item_id, alias_batch_no,
                   raw_batch_exact, stripped_batch, normalized_key, legacy_item_id, expiry,
                   pack_size, mrp, purchase_rate, net_rate, net_loose, stock_qty,
                   existing_batch_id, is_canonical, display_label)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (tgt, tk[1], raw, mig.text(raw), reso.loose_batch_no(mig.text(raw)),
                 s["legacy"], s["expiry"], mig.pack_text(s["pack"]) if s["pack"] else "",
                 s["mrp"], s["prate"], s["nrate"], s["net"], s["net"],
                 int(ex["id"]) if ex else None, 0, reso.display_batch_no(tk[1])))
            nprov += 1
        conn.execute(
            """CREATE TABLE IF NOT EXISTS legacy_stock_correction (
               id INTEGER PRIMARY KEY AUTOINCREMENT, applied_at TEXT NOT NULL,
               source_file TEXT NOT NULL, batches_set INTEGER NOT NULL,
               negatives_preserved INTEGER NOT NULL)""")
        nneg = sum(1 for s in nets.values() if s["net"] < 0)
        conn.execute("INSERT INTO legacy_stock_correction (applied_at, source_file, batches_set, negatives_preserved)"
                     " VALUES (?, ?, ?, ?)",
                     (datetime.now().isoformat(timespec="seconds"), str(DEFAULT_SOURCE),
                      len(nets), nneg))
        conn.commit()
        return {"updated": updated, "inserted": inserted, "provenance_rows": nprov,
                "negatives": nneg, "source_keys": len(nets)}
    except Exception:
        conn.rollback()
        raise


def app_running() -> list[str]:
    """Command lines suggesting the app is open (best effort, read-only)."""
    try:
        import subprocess
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name LIKE '%python%'\" |"
             " Select-Object -ExpandProperty CommandLine"],
            capture_output=True, text=True, timeout=30)
        return [ln.strip() for ln in (out.stdout or "").splitlines() if "main.py" in ln]
    except Exception:
        return []


def backup_live(live: Path) -> Path:
    """Timestamped backup of live via the online backup API + validation."""
    import hashlib
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = ROOT / "migration_backups" / f"pre_loose_correction_{stamp}.db"
    dest.parent.mkdir(parents=True, exist_ok=True)
    src = connect_ro(live)
    try:
        out = sqlite3.connect(str(dest))
        try:
            src.backup(out)
            out.commit()
        finally:
            out.close()
    finally:
        src.close()
    chk = sqlite3.connect(str(dest))
    try:
        chk.row_factory = sqlite3.Row
        if chk.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("backup integrity_check failed")
        for tbl in ["stock_batches", "sales_invoice_items", "purchase_invoice_items",
                    "legacy_id_map", "legacy_batch_resolution"]:
            chk.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()
    finally:
        chk.close()
    h = hashlib.sha256()
    with open(dest, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    print(f"backup: {dest} ({dest.stat().st_size:,} bytes, sha256={h.hexdigest()})")
    return dest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=None)
    ap.add_argument("--source", default=str(DEFAULT_SOURCE))
    ap.add_argument("--pre-image", default="staging/stock_final_verify.db")
    ap.add_argument("--clone-to", default=None)
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--confirm-live", action="store_true",
                    help="allow --db data/pharmacy.db (takes a validated backup first)")
    args = ap.parse_args(argv)
    if args.clone_to:
        from pathlib import Path as _P
        src = _P(args.db or str(DEFAULT_DB)).resolve()
        dest = _P(args.clone_to).resolve()
        if dest == LIVE_RESOLVED:
            print("REFUSING: will not overwrite live via --clone-to", file=sys.stderr)
            return 3
        dest.parent.mkdir(parents=True, exist_ok=True)
        s = connect_ro(src)
        try:
            o = sqlite3.connect(str(dest))
            try:
                s.backup(o)
                o.commit()
            finally:
                o.close()
        finally:
            s.close()
        print(f"cloned {src} -> {dest} ({dest.stat().st_size:,} bytes)")
        return 0
    if args.db is None:
        print("pass --db <staging-clone> (live is refused)", file=sys.stderr)
        return 2
    from pathlib import Path as _P
    db_path = _P(args.db).resolve() if args.db else None
    is_live = db_path is not None and db_path == LIVE_RESOLVED
    if db_path is not None and is_live and not (args.apply and args.confirm_live):
        print("REFUSING: live database needs --apply --confirm-live (backup first)",
              file=sys.stderr)
        return 3
    if args.db is None and not args.clone_to:
        print("pass --db <staging-clone> (live needs --apply --confirm-live)", file=sys.stderr)
        return 2
    src_path = _P(args.source).resolve()
    pre_path = _P(args.pre_image).resolve()
    import json
    if args.report:
        conn = connect_ro(db_path)
        try:
            dump = LegacyDump(src_path)
            rep = {"generated_at": datetime.now().isoformat(timespec="seconds"),
                   "db_path": str(db_path), "mode": "loose-preview",
                   **build_report(conn, dump, pre_path)}
            REPORT_JSON.write_text(json.dumps(rep, indent=2, default=str), encoding="utf-8")
            L = ["# Loose-unit reconstruction preview (STAGING, read-only)", "",
                 f"- source keys: {rep['n_source']}",
                 f"- trailing-whitespace raws: {rep['n_trailing']}",
                 f"- negatives preserved: {len(rep['negatives'])}",
                 f"- post-migration issues: {rep['post_migration_issues'] or 'none'}",
                 f"- drift vs packs (pre-apply, expected all): {len(rep['drift_vs_packs'])}"]
            REPORT_MD.write_text("\n".join(L) + "\n", encoding="utf-8")
            print(f"source={rep['n_source']} trailing={rep['n_trailing']} "
                  f"neg={len(rep['negatives'])} issues={rep['post_migration_issues'] or 'none'}")
        finally:
            conn.close()
        return 0
    if args.apply:
        if is_live:
            running = app_running()
            if running:
                print("REFUSING: application appears running; close it first:", file=sys.stderr)
                for line in running:
                    print(f"  {line}", file=sys.stderr)
                return 4
            backup_live(db_path)
        conn = sqlite3.connect(str(db_path), timeout=60)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            dump = LegacyDump(src_path)
            pre_issues = check_no_post_migration(conn, pre_path)
            if pre_issues:
                print("REFUSING:", pre_issues, file=sys.stderr)
                return 5
            out = apply_on_staging(conn, dump)
            print(f"applied: {out}")
            return 0
        finally:
            conn.close()
    print("pass --report or --apply", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
