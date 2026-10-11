"""Read-only inventory of every candidate pharmacy database (Phase 1 audit).

Opens each database in immutable read-only mode (``file:...?mode=ro``) so no
journal, WAL, schema or data change is ever written to a database under
inspection.  Writes a JSON artefact and prints a compact human summary.

Usage:
    python tools/audit_db_inventory.py
    python tools/audit_db_inventory.py --json migration_backups/db_inventory.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = os.path.expanduser("~")
LOCALAPPDATA = os.environ.get("LOCALAPPDATA", os.path.join(HOME, "AppData", "Local"))

CANDIDATES = [
    ("runtime_exe_LOCALAPPDATA",
     os.path.join(LOCALAPPDATA, "PharmacyManagementSystem", "pharmacy.db")),
    ("dev_data_pharmacy", os.path.join(ROOT, "data", "pharmacy.db")),
    ("staging", os.path.join(ROOT, "staging", "pharmacy_staging.db")),
    ("staging_backup", os.path.join(ROOT, "staging", "backups",
                                    "pharmacy_backup_20261010_102540.db")),
    ("dl_backup_20261010_150357",
     os.path.join(HOME, "Downloads", "pharmacy_backup_20261010_150357.db")),
    ("dl_backup_20261009_131947",
     os.path.join(HOME, "Downloads", "pharmacy_backup_20261009_131947.db")),
    ("data_backup_20261005_183419",
     os.path.join(ROOT, "data", "pharmacy_backup_20261005_183419.db")),
    ("data_backup_20261005_183659",
     os.path.join(ROOT, "data", "pharmacy_backup_20261005_183659.db")),
    ("data_backup_20261005_184515",
     os.path.join(ROOT, "data", "pharmacy_backup_20261005_184515.db")),
    ("data_backup_temp", os.path.join(ROOT, "data", "pharmacy_temp.db")),
    ("regression_fixture",
     os.path.join(ROOT, "data",
                  "pharmacy.db_test_fixture_after_regression_20260918.db")),
]

COUNT_TABLES = [
    "items", "companies", "units", "drugs", "doctors", "customers", "suppliers",
    "account_groups", "account_ledgers", "financial_years",
    "sales_invoices", "sales_invoice_items",
    "purchase_invoices", "purchase_invoice_items",
    "credit_notes", "credit_note_items", "debit_notes", "debit_note_items",
    "customer_receipts", "supplier_payments",
    "stock_batches", "ledger_transactions", "journal_entries",
    "app_users", "legacy_id_map", "legacy_migration_meta",
    "import_history", "hold_bills",
]

ITEM_COLS = ("id", "item_name", "unit_id", "company_id", "pack_size", "mrp",
             "rate", "legacy_tax_id", "tax_structure")
BATCH_COLS = ("id", "item_id", "batch_no", "expiry", "pack_size", "mrp",
              "purchase_rate", "net_rate", "stock_qty")


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def connect_ro(path: str) -> sqlite3.Connection:
    uri = "file:" + path.replace("\\", "/").replace("?", "%3f").replace("#", "%23")
    conn = sqlite3.connect(uri + "?mode=ro", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def inspect(label: str, path: str) -> dict:
    out: dict = {"label": label, "path": path}
    if not os.path.isfile(path):
        out["status"] = "missing"
        return out
    out["status"] = "present"
    out["size_bytes"] = os.path.getsize(path)
    out["mtime"] = datetime.fromtimestamp(
        os.stat(path).st_mtime).isoformat(timespec="seconds")
    try:
        out["sha256"] = sha256_file(path)
    except OSError as exc:
        out["sha256"] = f"error: {exc}"
    try:
        conn = connect_ro(path)
    except sqlite3.Error as exc:
        out["open_error"] = str(exc)
        return out
    try:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        out["table_count"] = len(tables)
        out["tables"] = tables

        counts: dict = {}
        for t in COUNT_TABLES:
            if t in tables:
                try:
                    counts[t] = conn.execute(
                        f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                except sqlite3.Error as exc:
                    counts[t] = f"error: {exc}"
        out["row_counts"] = counts

        try:
            out["integrity_check"] = conn.execute(
                "PRAGMA integrity_check").fetchone()[0]
        except sqlite3.Error as exc:
            out["integrity_check"] = f"error: {exc}"
        try:
            out["foreign_key_violations"] = len(
                conn.execute("PRAGMA foreign_key_check").fetchall())
        except sqlite3.Error as exc:
            out["foreign_key_violations"] = f"error: {exc}"

        if "financial_years" in tables:
            out["financial_years"] = [dict(r) for r in conn.execute(
                "SELECT * FROM financial_years ORDER BY start_date")]

        if "items" in tables:
            out["items_columns"] = [r[1] for r in conn.execute(
                "PRAGMA table_info(items)")]
        if "stock_batches" in tables:
            out["stock_batches_columns"] = [r[1] for r in conn.execute(
                "PRAGMA table_info(stock_batches)")]

        # ── UC-ROSE trace ──────────────────────────────────────────────
        ucrose: dict = {}
        if "items" in tables:
            try:
                rows = conn.execute(
                    "SELECT id, item_name, unit_id, company_id, pack_size, mrp,"
                    " rate FROM items WHERE UPPER(item_name) LIKE '%ROSE%'"
                ).fetchall()
                ucrose["items_like_rose"] = [dict(r) for r in rows]
            except sqlite3.Error as exc:
                ucrose["items_like_rose"] = f"error: {exc}"
            if "stock_batches" in tables:
                batch_rows = []
                for r in ucrose.get("items_like_rose", []) or []:
                    if not isinstance(r, dict):
                        continue
                    for b in conn.execute(
                        "SELECT id, item_id, batch_no, expiry, pack_size, mrp,"
                        " purchase_rate, net_rate, stock_qty"
                        " FROM stock_batches WHERE item_id = ? ORDER BY batch_no",
                        (r["id"],),
                    ):
                        batch_rows.append(dict(b))
                ucrose["batches_for_rose_items"] = batch_rows
                ucrose["rose_positive_batches"] = [
                    b for b in batch_rows
                    if isinstance(b.get("stock_qty"), (int, float))
                    and b["stock_qty"] > 0]
        if "stock_batches" in tables:
            ucrose["stock_batches_total"] = conn.execute(
                "SELECT COUNT(*) FROM stock_batches").fetchone()[0]
            ucrose["stock_batches_positive"] = conn.execute(
                "SELECT COUNT(*) FROM stock_batches WHERE stock_qty > 0"
            ).fetchone()[0]
            ucrose["stock_batches_zero"] = conn.execute(
                "SELECT COUNT(*) FROM stock_batches WHERE stock_qty = 0"
            ).fetchone()[0]
            ucrose["stock_batches_negative"] = conn.execute(
                "SELECT COUNT(*) FROM stock_batches WHERE stock_qty < 0"
            ).fetchone()[0]
        out["ucrose"] = ucrose

        if "legacy_migration_meta" in tables:
            out["legacy_migration_meta"] = [dict(r) for r in conn.execute(
                "SELECT * FROM legacy_migration_meta LIMIT 50")]
    finally:
        conn.close()
    return out


def summary_line(d: dict) -> str:
    if d.get("status") != "present":
        return f"{d['label']:26s} MISSING"
    c = d.get("row_counts", {})
    return (
        f"{d['label']:26s} {d['size_bytes']:>12,}B  tables={d.get('table_count')}"
        f"  items={c.get('items')} batches={c.get('stock_batches')}"
        f" (+{d.get('ucrose', {}).get('stock_batches_positive')} >0)"
        f"  sales={c.get('sales_invoices')} purch={c.get('purchase_invoices')}"
        f"  ledgers={c.get('account_ledgers')} ltxn={c.get('ledger_transactions')}"
        f"  fy={c.get('financial_years')}  integrity={d.get('integrity_check')}"
        f"  fk={d.get('foreign_key_violations')}"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=os.path.join(
        ROOT, "migration_backups", "db_inventory.json"))
    args = ap.parse_args()

    results = [inspect(label, path) for label, path in CANDIDATES]
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "databases": results,
    }
    text = json.dumps(payload, indent=2, default=str)
    try:
        with open(args.json, "w", encoding="utf-8") as fh:
            fh.write(text)
        wrote = f"wrote {args.json}"
    except OSError as exc:
        wrote = f"could not write json: {exc}"

    print("=" * 100)
    for d in results:
        print(summary_line(d))
    print("=" * 100)
    for d in results:
        if d.get("status") != "present":
            continue
        print(f"\n--- {d['label']} :: {d['path']}")
        print(f"    sha256={d.get('sha256')}")
        print(f"    financial_years={json.dumps(d.get('financial_years'), default=str)}")
        uc = d.get("ucrose", {})
        print(f"    items LIKE '%ROSE%' = {json.dumps(uc.get('items_like_rose'), default=str)}")
        print(f"    rose batches = {json.dumps(uc.get('batches_for_rose_items'), default=str)}")
        print(f"    rose positive = {json.dumps(uc.get('rose_positive_batches'), default=str)}")
        print(f"    stock_batches total/pos/zero/neg = "
              f"{uc.get('stock_batches_total')}/{uc.get('stock_batches_positive')}/"
              f"{uc.get('stock_batches_zero')}/{uc.get('stock_batches_negative')}")
        print(f"    items_columns={d.get('items_columns')}")
        print(f"    stock_batches_columns={d.get('stock_batches_columns')}")
    print("\n" + wrote)
    return 0


if __name__ == "__main__":
    sys.exit(main())
