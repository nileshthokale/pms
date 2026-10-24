"""Pre-build verification for the isolated test release.

Reads the staging snapshot strictly read-only and records:

* SHA-256 and size
* PRAGMA integrity_check / foreign_key_check
* headline table counts (must match the verified migration)
* active financial year
* the latest migration audit artefacts that are present

Writes ``migration_backups/test_release_source_verification.json``.

Usage:
    .venv\\Scripts\\python.exe tools\\verify_test_release_source.py
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STAGING = ROOT / "staging" / "pharmacy_staging.db"
OUTPUT = ROOT / "migration_backups" / "test_release_source_verification.json"

EXPECTED = {
    "sales_invoices": 72207,
    "items": 940,
    "purchase_invoices": 5727,
    "credit_notes": 1354,
    "patient_addresses": 25815,
}

AUDIT_FILES = [
    "full_application_data_integrity_audit.json",
    "full_application_data_integrity_test_results.json",
    "legacy_data_migration_summary.json",
    "legacy_data_final_reconciliation_review.json",
    "legacy_data_refresh_reconciliation.json",
    "legacy_data_idempotency_check.json",
]

TABLES = [
    "items",
    "suppliers",
    "customers",
    "doctors",
    "companies",
    "units",
    "categories",
    "purchase_invoices",
    "purchase_invoice_items",
    "sales_invoices",
    "sales_invoice_items",
    "credit_notes",
    "credit_note_items",
    "debit_notes",
    "supplier_payments",
    "customer_receipts",
    "stock_batches",
    "account_ledgers",
    "ledger_transactions",
    "journal_entries",
    "app_users",
    "patient_addresses",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    if not STAGING.is_file():
        raise SystemExit(f"Staging database missing: {STAGING}")

    result: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "staging_path": str(STAGING),
        "size_bytes": STAGING.stat().st_size,
        "sha256": sha256(STAGING),
        "ok": False,
    }

    conn = sqlite3.connect(f"file:{STAGING.as_posix()}?mode=ro", uri=True)
    try:
        result["integrity_check"] = [
            row[0] for row in conn.execute("PRAGMA integrity_check").fetchall()
        ]
        result["foreign_key_violations"] = len(
            conn.execute("PRAGMA foreign_key_check").fetchall()
        )
        counts = {}
        for table in TABLES:
            try:
                counts[table] = conn.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
            except sqlite3.Error as exc:
                counts[table] = f"ERROR: {exc}"
        result["counts"] = counts
        result["active_financial_years"] = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM financial_years WHERE is_active = 1 ORDER BY name"
            ).fetchall()
        ]
        result["sqlite_version"] = sqlite3.sqlite_version
    finally:
        conn.close()

    result["audit_artifacts"] = {}
    for name in AUDIT_FILES:
        path = ROOT / "migration_backups" / name
        if path.is_file():
            stat = path.stat()
            result["audit_artifacts"][name] = {
                "size_bytes": stat.st_size,
                "modified": datetime.fromtimestamp(
                    stat.st_mtime, tz=timezone.utc
                ).isoformat(),
                "sha256": sha256(path),
            }
        else:
            result["audit_artifacts"][name] = None

    problems = []
    if result["integrity_check"] != ["ok"]:
        problems.append(f"integrity_check={result['integrity_check']}")
    if result["foreign_key_violations"]:
        problems.append(f"foreign_key_violations={result['foreign_key_violations']}")
    for table, expected in EXPECTED.items():
        actual = result["counts"].get(table)
        if actual != expected:
            problems.append(f"{table}: expected {expected}, got {actual}")
    result["problems"] = problems
    result["ok"] = not problems

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2), encoding="utf-8")

    print(f"Staging database : {STAGING}")
    print(f"Size             : {result['size_bytes']:,} bytes")
    print(f"SHA-256          : {result['sha256']}")
    print(f"Integrity        : {result['integrity_check']}")
    print(f"FK violations    : {result['foreign_key_violations']}")
    for table, expected in EXPECTED.items():
        print(f"{table:20s}: {result['counts'].get(table):,} (expected {expected:,})")
    print(f"Active FY        : {result['active_financial_years']}")
    print(f"Report           : {OUTPUT}")
    if problems:
        print("\nFAILED:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("\n[PASS] Staging snapshot is ready to package.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
