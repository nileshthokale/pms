"""Migration script: Reassign Sales Bill Numbers to fill 2017 and 2018.

Problem:
Bill numbers 2017 and 2018 were consumed by unnamed sales (IDs 72186, 72187)
which display as blank in the UI. Consequently, newer named bills began at
2019, 2020, 2021... creating a perceived 2-number gap.

Solution:
1. Take a safety snapshot backup of the database before making any changes.
2. In an atomic transaction (BEGIN IMMEDIATE):
   - Set bill_no = '' on unnamed invoices 72186 and 72187 (matching system standard).
   - In ledger_transactions, set voucher_no = '' and description = 'Sale to WALKIN' for 72186 and 72187.
   - For invoices 72188 to 72202 (15 bills):
     Shift bill_no down by 2 (e.g. 2019 -> 2017, 2020 -> 2018, ..., 2033 -> 2031).
     Update ledger_transactions voucher_no and description accordingly.
   - Verify zero duplicate bill numbers and verify integrity_check.
   - Verify SalesDAO.generate_next_bill_no() yields 2032 as the next bill number.
3. Commit transaction.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import os
import sqlite3
import sys

# Ensure repository root is on sys.path
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def create_safety_backup(db_path: str, backup_dir: str | None = None) -> str:
    """Create a consistent snapshot backup using SQLite's online backup API."""
    if backup_dir is None:
        backup_dir = os.path.join(os.path.dirname(os.path.abspath(db_path)), "backups")
    os.makedirs(backup_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(backup_dir, f"pharmacy_backup_pre_bill_renumber_{stamp}.db")

    src = sqlite3.connect(db_path)
    dest = sqlite3.connect(backup_path)
    try:
        src.backup(dest)
    finally:
        dest.close()
        src.close()
    return backup_path


def check_already_applied(cur: sqlite3.Cursor) -> bool:
    """Check if the renumbering has already been applied."""
    cur.execute("SELECT id, bill_no FROM sales_invoices WHERE id IN (72186, 72187, 72188, 72189)")
    rows = dict(cur.fetchall())
    if (
        rows.get(72186) == ""
        and rows.get(72187) == ""
        and rows.get(72188) == "2017"
        and rows.get(72189) == "2018"
    ):
        return True
    return False


def reassign_bill_numbers(
    db_path: str,
    make_backup: bool = True,
    backup_dir: str | None = None,
    dry_run: bool = False,
) -> dict:
    """Apply the renumbering migration atomically.

    Returns a report dictionary detailing the operations and changes.
    """
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Database file not found: {db_path}")

    backup_path = None
    if make_backup and not dry_run:
        backup_path = create_safety_backup(db_path, backup_dir=backup_dir)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    try:
        if check_already_applied(cur):
            return {
                "status": "already_applied",
                "message": "Migration already applied. Bills 2017 and 2018 are already mapped to invoices 72188 and 72189.",
                "backup_path": backup_path,
                "changes": [],
            }

        # Validate prerequisite state
        cur.execute("""
            SELECT id, bill_no, patient_name, total_amount, net_amount
            FROM sales_invoices
            WHERE id >= 72184
            ORDER BY id ASC
        """)
        invoices = {r["id"]: dict(r) for r in cur.fetchall()}

        expected_initial = {
            72186: "2017",
            72187: "2018",
            72188: "2019",
            72189: "2020",
        }
        for inv_id, exp_bno in expected_initial.items():
            actual_bno = invoices.get(inv_id, {}).get("bill_no")
            if actual_bno != exp_bno:
                raise ValueError(
                    f"Unexpected initial state for invoice {inv_id}: expected bill_no={exp_bno!r}, found={actual_bno!r}"
                )

        cur.execute("BEGIN IMMEDIATE")

        changes_log = []

        # Step 1: Blank bill_no on unnamed invoices 72186 and 72187
        for unnamed_id in (72186, 72187):
            old_bno = invoices[unnamed_id]["bill_no"]
            cur.execute("UPDATE sales_invoices SET bill_no = '' WHERE id = ?", (unnamed_id,))
            cur.execute(
                """
                UPDATE ledger_transactions
                SET voucher_no = '',
                    description = 'Sale to WALKIN'
                WHERE reference_type = 'COUNTER_SALE' AND reference_id = ?
                """,
                (unnamed_id,),
            )
            lt_updated = cur.rowcount
            changes_log.append({
                "invoice_id": unnamed_id,
                "patient_name": invoices[unnamed_id]["patient_name"],
                "old_bill_no": old_bno,
                "new_bill_no": "",
                "ledger_rows_updated": lt_updated,
            })

        # Step 2: Renumber 72188 through 72202 in ascending order
        for shift_id in range(72188, 72203):
            if shift_id not in invoices:
                continue
            old_bno = invoices[shift_id]["bill_no"]
            if not old_bno.isdigit():
                raise ValueError(f"Invoice {shift_id} bill_no {old_bno!r} is not numeric")
            new_bno = str(int(old_bno) - 2)

            cur.execute("UPDATE sales_invoices SET bill_no = ? WHERE id = ?", (new_bno, shift_id))
            cur.execute(
                """
                UPDATE ledger_transactions
                SET voucher_no = ?,
                    description = REPLACE(
                        REPLACE(description, 'Sale ' || ? || ' ', 'Sale ' || ? || ' '),
                        'REVERSAL: Counter Sale ' || ?,
                        'REVERSAL: Counter Sale ' || ?
                    )
                WHERE reference_type = 'COUNTER_SALE' AND reference_id = ?
                """,
                (new_bno, old_bno, new_bno, old_bno, new_bno, shift_id),
            )
            lt_updated = cur.rowcount
            changes_log.append({
                "invoice_id": shift_id,
                "patient_name": invoices[shift_id]["patient_name"],
                "old_bill_no": old_bno,
                "new_bill_no": new_bno,
                "ledger_rows_updated": lt_updated,
            })

        # Verification A: No duplicate non-blank bill numbers
        cur.execute("""
            SELECT bill_no, COUNT(*) as cnt
            FROM sales_invoices
            WHERE bill_no IS NOT NULL AND TRIM(bill_no) <> ''
            GROUP BY bill_no
            HAVING cnt > 1
        """)
        dups = cur.fetchall()
        if dups:
            dup_list = [f"{r['bill_no']} (x{r['cnt']})" for r in dups]
            raise RuntimeError(f"Duplicate non-blank bill numbers detected after migration: {', '.join(dup_list)}")

        # Verification B: Bills 2017 and 2018 assigned to 72188 and 72189
        cur.execute("SELECT id, bill_no FROM sales_invoices WHERE id IN (72188, 72189)")
        assigned = dict(cur.fetchall())
        if assigned.get(72188) != "2017" or assigned.get(72189) != "2018":
            raise RuntimeError(f"Invoices 72188/72189 not mapped correctly: {assigned}")

        # Verification C: Next bill number generation
        from database.sales_dao import SalesDAO
        next_candidate = SalesDAO.generate_next_bill_no(cur=cur)
        from core.doc_formatter import format_sales_bill_number
        disp_next = format_sales_bill_number(next_candidate)
        if disp_next != "2032":
            raise RuntimeError(
                f"Next bill number mismatch: expected '2032', got candidate={next_candidate!r} disp={disp_next!r}"
            )

        # Verification D: Database integrity check
        cur.execute("PRAGMA integrity_check")
        integrity_row = cur.fetchone()
        integrity_status = integrity_row[0] if integrity_row else "unknown"
        if integrity_status != "ok":
            raise RuntimeError(f"PRAGMA integrity_check failed: {integrity_status}")

        if dry_run:
            conn.rollback()
            return {
                "status": "dry_run_success",
                "message": "Dry-run succeeded without errors; all changes rolled back.",
                "backup_path": backup_path,
                "changes": changes_log,
                "next_bill_no": next_candidate,
                "displayed_next_bill_no": disp_next,
            }

        conn.commit()
        return {
            "status": "success",
            "message": "Successfully renumbered bills 2019..2033 to 2017..2031, freed 72186/72187.",
            "backup_path": backup_path,
            "changes": changes_log,
            "next_bill_no": next_candidate,
            "displayed_next_bill_no": disp_next,
            "integrity": integrity_status,
        }

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Reassign Sales Bill Numbers to fill 2017 and 2018.")
    parser.add_argument("--db-path", default="data/pharmacy.db", help="Path to pharmacy.db")
    parser.add_argument("--dry-run", action="store_true", help="Simulate migration without committing")
    parser.add_argument("--no-backup", action="store_true", help="Skip creating safety backup")
    parser.add_argument("--backup-dir", default=None, help="Directory to save safety backup")
    args = parser.parse_args()

    print(f"Target DB: {args.db_path}")
    print(f"Dry-run: {args.dry_run}")
    print(f"Make backup: {not args.no_backup}")

    result = reassign_bill_numbers(
        db_path=args.db_path,
        make_backup=not args.no_backup,
        backup_dir=args.backup_dir,
        dry_run=args.dry_run,
    )

    print("\nResult:")
    print(f"Status: {result['status']}")
    print(f"Message: {result['message']}")
    if result.get("backup_path"):
        print(f"Backup created at: {result['backup_path']}")
    if result.get("displayed_next_bill_no"):
        print(f"Next bill number: {result['displayed_next_bill_no']} (raw: {result.get('next_bill_no')})")

    print(f"\nChanged {len(result['changes'])} records:")
    print(f"{'Inv ID':<8} {'Patient':<25} {'Old Bill':<10} {'New Bill':<10} {'LT Rows'}")
    print("-" * 65)
    for ch in result["changes"]:
        print(f"{ch['invoice_id']:<8} {ch['patient_name'][:24]:<25} {ch['old_bill_no']:<10} {ch['new_bill_no']:<10} {ch['ledger_rows_updated']}")


if __name__ == "__main__":
    main()
