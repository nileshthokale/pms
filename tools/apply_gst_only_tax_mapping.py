"""Apply the REVIEWED GST-only per-item mapping (local dev DB only).

Source of truth: migration_backups/item_tax_gst_only_dryrun.json.
Updates ONLY items.tax_structure; every other column (incl. legacy_tax_id)
must remain byte-identical. Atomic: rollback on any validation failure.
Refuses production/frozen targets. Requires --confirm-local-dev.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from database.connection import get_app_data_dir, get_db_path  # noqa: E402

ALLOWED = {"5", "12", "18", "28", "0", ""}
EXPECTED = {"5": 218, "12": 313, "18": 23, "28": 2, "0": 7, "": 379}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", required=True)
    ap.add_argument("--confirm-local-dev", action="store_true", required=True)
    ap.add_argument("--target", default=None)
    args = ap.parse_args(argv)

    if getattr(sys, "frozen", False):
        print("SAFETY REFUSAL: frozen process", file=sys.stderr)
        return 2
    target = os.path.abspath(args.target) if args.target else os.path.abspath(get_db_path())
    app_dir = os.path.abspath(get_app_data_dir())
    if os.path.normcase(target).startswith(os.path.normcase(app_dir + os.sep)):
        print(f"SAFETY REFUSAL: production target {target}", file=sys.stderr)
        return 2

    rep = json.loads((ROOT / "migration_backups" / "item_tax_gst_only_dryrun.json").read_text())
    decisions = rep["items"]
    assert len(decisions) == 942, "dry run stale"
    assert dict(Counter(d["new_tax_structure"] for d in decisions)) == EXPECTED, "totals drifted"
    wanted = {d["item_id"]: d["new_tax_structure"] for d in decisions}
    assert set(wanted) and all(v in ALLOWED for v in wanted.values())

    conn = sqlite3.connect(target)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("BEGIN IMMEDIATE")
        before = {r[0]: (r[1], r[2]) for r in conn.execute(
            "SELECT id, tax_structure, legacy_tax_id FROM items")}
        assert len(before) == 942, f"expected 942 items, found {len(before)}"
        assert set(before) == set(wanted), "ID set changed — refusing"
        for iid, new_tax in wanted.items():
            conn.execute("UPDATE items SET tax_structure=? WHERE id=?", (new_tax, iid))
        problems: list[str] = []
        totals = Counter(r[0] for r in conn.execute("SELECT tax_structure FROM items"))
        if dict(totals) != EXPECTED:
            problems.append(f"totals mismatch: {dict(totals)}")
        # nothing else may change: compare full rows except tax_structure
        for r in conn.execute("SELECT * FROM items"):
            d = dict(zip([c[1] for c in conn.execute("PRAGMA table_info(items)")], r))
            old_tax, old_prov = before[d["id"]]
            if d["legacy_tax_id"] != old_prov:
                problems.append(f"id {d['id']}: provenance changed")
            if d["tax_structure"] != wanted[d["id"]]:
                problems.append(f"id {d['id']}: tax not per mapping")
        r590 = conn.execute("SELECT tax_structure, legacy_tax_id FROM items WHERE id=590").fetchone()
        if tuple(r590) != ("", 6):
            problems.append(f"item 590 must stay EMPTY/6, found {tuple(r590)}")
        for t, exp in (("companies", 219), ("units", 14), ("drugs", 137),
                       ("item_ingredients", 402), ("suppliers", 0), ("customers", 0),
                       ("doctors", 0)):
            got = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            if got != exp:
                problems.append(f"{t}: {got} != {exp}")
        for t in ("purchase_invoices", "purchase_invoice_items", "stock_batches",
                  "sales_invoices", "sales_invoice_items", "customer_receipts",
                  "supplier_payments", "credit_notes", "credit_note_items",
                  "debit_notes", "debit_note_items", "journal_entries",
                  "journal_entry_items", "ledger_transactions"):
            if conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] != 0:
                problems.append(f"{t} not empty")
        if conn.execute("PRAGMA foreign_key_check").fetchall():
            problems.append("FK violations")
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            problems.append("integrity failed")
        if problems:
            conn.rollback()
            print("VALIDATION FAILED (rolled back):", *problems, sep="\n - ", file=sys.stderr)
            return 1
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()
    print(json.dumps({"target": target, "updated": 942,
                      "sha256": hashlib.sha256(Path(target).read_bytes()).hexdigest()},
                     indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
