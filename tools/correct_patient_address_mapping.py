"""Safe, Transactional Patient Name & Address Mapping Correction.

Corrects patient name-to-address mapping using PharmaWinner SQL export as reference.
Operates STRICTLY within patient identity/address mapping scope:
- Only touches `patient_addresses` table.
- Does NOT modify sales_invoices, sales_invoice_items, stock, ledger, or prices.
- Supports --dry-run (default) and --apply.
- In --apply mode, creates an immutable pre-correction backup in migration_backups/.
- Rolls back on any invariant or validation check failure.
"""

from __future__ import annotations

import argparse
import csv
import datetime
import hashlib
import os
import sqlite3
import sys
from pathlib import Path
from collections import defaultdict, Counter

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from database.legacy_migration import LegacyDump

DEFAULT_DUMP = ROOT / "PharmaWinner202610231351.sql"
DEFAULT_DB = ROOT / "data" / "pharmacy.db"
BACKUP_DIR = ROOT / "migration_backups"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def extract_patient_mappings(dump_path: Path) -> dict:
    print(f"Reading patient records from {dump_path.name}...")
    dump = LegacyDump(dump_path)
    
    pat_addrs = defaultdict(Counter)
    pat_dates = defaultdict(dict)
    total_sales = 0

    for r in dump.iter_rows("salesvhheader"):
        total_sales += 1
        date_val = str(r[4]) if len(r) > 4 and r[4] else ""
        p_name = " ".join(str(r[10]).split()).strip() if len(r) > 10 and r[10] else ""
        p_addr = " ".join(str(r[11]).split()).strip() if len(r) > 11 and r[11] else ""
        
        if not p_name:
            continue
        norm = p_name.upper()
        if norm in ("WALKIN", "WALKIN CUSTOMER") or not p_addr:
            continue
            
        pat_addrs[p_name][p_addr] += 1
        pat_dates[p_name][p_addr] = max(pat_dates[p_name].get(p_addr, ""), date_val)

    print(f"Extracted address records for {len(pat_addrs)} unique patient names across {total_sales} sales.")
    return {
        "addresses": pat_addrs,
        "dates": pat_dates,
    }


def run_correction(db_path: Path, dump_path: Path, apply: bool = False):
    print("=" * 70)
    print("PATIENT NAME & ADDRESS MAPPING CORRECTION SCRIPT")
    print(f"Mode: {'APPLY (Live Transactional Write)' if apply else 'DRY RUN (Read Only)'}")
    print(f"Database: {db_path.resolve()}")
    print(f"Source Dump: {dump_path.resolve()}")
    print("=" * 70)

    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")
    if not dump_path.exists():
        raise FileNotFoundError(f"Source dump not found: {dump_path}")

    # Extract mappings
    extracted = extract_patient_mappings(dump_path)
    pat_addrs = extracted["addresses"]
    pat_dates = extracted["dates"]

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # Baseline inspection of protected tables
    PROTECTED_TABLES = [
        "sales_invoices",
        "sales_invoice_items",
        "stock_batches",
        "purchase_invoices",
        "purchase_invoice_items",
        "credit_notes",
        "credit_note_items",
        "ledger_transactions",
        "customers",
        "items",
    ]
    cur = conn.cursor()
    protected_baselines = {}
    for t in PROTECTED_TABLES:
        cnt = cur.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        id_sum = cur.execute(f"SELECT COALESCE(SUM(id), 0) FROM {t}").fetchone()[0]
        protected_baselines[t] = (cnt, id_sum)

    cur.execute("SELECT count(*) FROM patient_addresses")
    pa_before_count = cur.fetchone()[0]

    cur.execute("SELECT patient_name, address FROM patient_addresses")
    existing_pairs = {(r[0].strip().upper(), r[1].strip().upper()) for r in cur.fetchall()}

    # Customer lookup map
    cur.execute("SELECT id, UPPER(TRIM(customer_name)) as name FROM customers WHERE UPPER(customer_name) NOT IN ('WALKIN', 'WALKIN CUSTOMER')")
    cust_map = {r["name"]: r["id"] for r in cur.fetchall()}

    # Prepare insertions
    to_insert = []
    
    for p_name, addr_counter in pat_addrs.items():
        norm_name = p_name.upper()
        cust_id = cust_map.get(norm_name)
        
        # Sort addresses by visit date descending, then visit count descending
        sorted_addrs = sorted(
            addr_counter.keys(),
            key=lambda a: (pat_dates[p_name].get(a, ""), addr_counter[a]),
            reverse=True
        )
        
        for addr in sorted_addrs:
            pair = (norm_name, addr.upper())
            if pair not in existing_pairs:
                latest_date = pat_dates[p_name].get(addr, "2026-01-01")
                # Format as ISO timestamp for updated_at
                timestamp = f"{latest_date} 12:00:00" if latest_date else datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                to_insert.append((p_name, addr, cust_id, timestamp))
                existing_pairs.add(pair)

    print(f"\n[Analysis]")
    print(f"  Existing patient_addresses rows: {pa_before_count}")
    print(f"  New verified patient address rows to insert: {len(to_insert)}")
    print(f"  Total patient_addresses after insertion: {pa_before_count + len(to_insert)}")

    if not apply:
        print("\n[DRY RUN COMPLETE] No changes were written to the database.")
        print("To execute with pre-backup and atomic commit, run with --apply.")
        conn.close()
        return

    # APPLY MODE
    print("\n[Step 1/4] Creating Pre-Correction Immutable Backup...")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = BACKUP_DIR / f"pre_patient_address_correction_{timestamp_str}.db"

    # WAL Checkpoint before backup
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    b_conn = sqlite3.connect(str(backup_file))
    conn.backup(b_conn)
    b_conn.close()

    pre_hash = sha256_file(db_path)
    bak_hash = sha256_file(backup_file)
    print(f"  Backup created: {backup_file.name}")
    print(f"  Original DB SHA-256: {pre_hash}")
    print(f"  Backup file SHA-256: {bak_hash}")

    # Verify backup
    chk_conn = sqlite3.connect(str(backup_file))
    chk = chk_conn.execute("PRAGMA integrity_check").fetchone()[0]
    chk_conn.close()
    if chk != "ok":
        raise RuntimeError(f"Backup integrity check failed: {chk}")
    print("  Backup verified successfully (PRAGMA integrity_check = ok).")

    print("\n[Step 2/4] Executing Transactional Insertions into patient_addresses...")
    try:
        conn.execute("BEGIN IMMEDIATE")
        
        insert_sql = """
            INSERT OR IGNORE INTO patient_addresses (patient_name, address, customer_id, updated_at)
            VALUES (?, ?, ?, ?)
        """
        conn.executemany(insert_sql, to_insert)
        
        # Invariant validations
        cur = conn.cursor()
        
        # 1. Check patient_addresses count
        cur.execute("SELECT count(*) FROM patient_addresses")
        pa_after_count = cur.fetchone()[0]
        print(f"  patient_addresses count: {pa_before_count} -> {pa_after_count}")
        
        # 2. Check ALL protected tables are completely UNTOUCHED (count and id sum)
        for t, (exp_cnt, exp_id_sum) in protected_baselines.items():
            act_cnt = cur.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
            act_id_sum = cur.execute(f"SELECT COALESCE(SUM(id), 0) FROM {t}").fetchone()[0]
            if act_cnt != exp_cnt or act_id_sum != exp_id_sum:
                raise RuntimeError(
                    f"INVARIANT VIOLATION: Protected table '{t}' modified! "
                    f"Expected count={exp_cnt}, got={act_cnt}; Expected id_sum={exp_id_sum}, got={act_id_sum}"
                )
        print(f"  Verified all {len(protected_baselines)} protected tables are completely unchanged.")
            
        # 3. Check integrity
        cur.execute("PRAGMA integrity_check")
        integ = cur.fetchone()[0]
        if integ != "ok":
            raise RuntimeError(f"INVARIANT VIOLATION: PRAGMA integrity_check = {integ}!")
            
        cur.execute("PRAGMA foreign_key_check")
        fks = cur.fetchall()
        if fks:
            raise RuntimeError(f"INVARIANT VIOLATION: {len(fks)} foreign key violations found!")

        conn.commit()
        print("  Transaction committed successfully.")
    except Exception as e:
        conn.rollback()
        conn.close()
        print(f"\n[ROLLBACK] Transaction rolled back due to error: {e}")
        raise

    print("\n[Step 3/4] Checkpoint and clean journal files...")
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()

    print("\n[Step 4/4] Post-Correction Verification...")
    post_conn = sqlite3.connect(str(db_path))
    post_cur = post_conn.cursor()

    integ = post_cur.execute("PRAGMA integrity_check").fetchone()[0]
    if integ != "ok":
        raise RuntimeError(f"Post-apply integrity check failed: {integ}")
    print("  Post-apply PRAGMA integrity_check = ok")

    fks = post_cur.execute("PRAGMA foreign_key_check").fetchall()
    if fks:
        raise RuntimeError(f"Post-apply foreign key check failed with {len(fks)} violations!")
    print("  Post-apply PRAGMA foreign_key_check = 0 violations")

    for t, (exp_cnt, exp_id_sum) in protected_baselines.items():
        act_cnt = post_cur.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        act_id_sum = post_cur.execute(f"SELECT COALESCE(SUM(id), 0) FROM {t}").fetchone()[0]
        if act_cnt != exp_cnt or act_id_sum != exp_id_sum:
            raise RuntimeError(f"Post-apply check failed: Protected table '{t}' modified!")
    print(f"  Post-apply verified all {len(protected_baselines)} protected tables remain identical.")
    
    # Verify Schedule H1 address resolution
    post_cur.execute("""
        SELECT count(*)
        FROM sales_invoices si
        JOIN sales_invoice_items sii ON sii.sales_invoice_id = si.id
        JOIN items i ON i.id = sii.item_id
        LEFT JOIN (
            SELECT patient_name, address
            FROM (
                SELECT patient_name, address,
                       ROW_NUMBER() OVER (
                           PARTITION BY UPPER(TRIM(patient_name))
                           ORDER BY updated_at DESC, id DESC
                       ) as rn
                FROM patient_addresses
            ) WHERE rn = 1
        ) pa ON UPPER(TRIM(pa.patient_name)) = UPPER(TRIM(si.patient_name))
        LEFT JOIN customers c ON c.id = si.customer_id
        WHERE i.scheduled IN ('2', 'H1')
          AND COALESCE(NULLIF(TRIM(pa.address), ''), NULLIF(TRIM(c.address), ''), '') <> ''
    """)
    h1_resolved_rows = post_cur.fetchone()[0]
    
    post_cur.execute("""
        SELECT count(*)
        FROM sales_invoices si
        JOIN sales_invoice_items sii ON sii.sales_invoice_id = si.id
        JOIN items i ON i.id = sii.item_id
        WHERE i.scheduled IN ('2', 'H1')
    """)
    h1_total_rows = post_cur.fetchone()[0]
    
    print(f"  Schedule H1 Sales Rows with Address: {h1_resolved_rows} / {h1_total_rows} ({h1_resolved_rows/h1_total_rows*100:.2f}%)")
    post_conn.close()

    post_hash = sha256_file(db_path)
    print(f"  Final DB SHA-256: {post_hash}")
    print("\n" + "=" * 70)
    print("PATIENT NAME & ADDRESS CORRECTION COMPLETED SUCCESSFULLY!")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="Correct patient name and address mappings.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="Path to SQLite database")
    parser.add_argument("--dump", type=Path, default=DEFAULT_DUMP, help="Path to PharmaWinner SQL export")
    parser.add_argument("--apply", action="store_true", help="Apply changes with transactional safety and pre-backup")
    args = parser.parse_args()

    run_correction(args.db, args.dump, apply=args.apply)


if __name__ == "__main__":
    main()
