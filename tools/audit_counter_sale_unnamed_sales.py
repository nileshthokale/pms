"""Read-only audit of Counter Sale records created without a patient name.

This tool NEVER writes to the database.  It opens SQLite with ``mode=ro`` and
sets ``PRAGMA query_only=ON`` so an accidental write fails instead of altering
historical data.

Reliable identification rule
----------------------------
A historical sale is treated as "created without a patient name" only when
the stored ``sales_invoices.patient_name`` is NULL, empty, or whitespace-only:

    patient_name IS NULL OR TRIM(patient_name) = ''

Rows whose patient name is literally ``WALKIN`` are NOT classified as unnamed:
``WALKIN`` is also a legitimate stored patient name, and the application must
never assume every such row was auto-generated.

Usage
-----
    python tools/audit_counter_sale_unnamed_sales.py
    python tools/audit_counter_sale_unnamed_sales.py --db data/pharmacy.db
    python tools/audit_counter_sale_unnamed_sales.py --json audit.json

The database defaults to the application database (``PHARMACY_DB`` when set,
otherwise ``data/pharmacy.db``).  The report is informational only; no rows,
bill numbers, indexes, or sequences are changed.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent


def default_db_path() -> Path:
    configured = os.environ.get("PHARMACY_DB") or os.environ.get("PHARMACY_DB_PATH")
    if configured:
        return Path(configured)
    return ROOT / "data" / "pharmacy.db"


def open_read_only(path: Path) -> sqlite3.Connection:
    """Open *path* so that no statement can modify it."""
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    return conn


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _scalar(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> Any:
    row = conn.execute(sql, params).fetchone()
    return None if row is None else row[0]


def _bill_shape(bill_no: str) -> str:
    text = (bill_no or "").strip()
    if not text:
        return "blank"
    if text.upper().startswith("CS-"):
        return "legacy CS- prefix"
    if "-S" in text.upper():
        return "legacy ...-S<id> suffix"
    parts = text.split("-")
    if len(parts) >= 3 and parts[0].isdigit() and parts[1].isdigit():
        return "financial-year compound"
    if text.isdigit():
        return "plain numeric"
    return "other"


def build_audit(conn: sqlite3.Connection) -> dict[str, Any]:
    total = int(_scalar(conn, "SELECT COUNT(*) FROM sales_invoices") or 0)

    unnamed_predicate = "(patient_name IS NULL OR TRIM(patient_name) = '')"
    unnamed = int(
        _scalar(conn, f"SELECT COUNT(*) FROM sales_invoices WHERE {unnamed_predicate}")
        or 0
    )
    named = total - unnamed
    stored_walkin = int(
        _scalar(
            conn,
            "SELECT COUNT(*) FROM sales_invoices "
            "WHERE UPPER(TRIM(patient_name)) = 'WALKIN'",
        )
        or 0
    )
    blank_bill = int(
        _scalar(
            conn,
            "SELECT COUNT(*) FROM sales_invoices "
            "WHERE bill_no IS NULL OR TRIM(bill_no) = ''",
        )
        or 0
    )
    unnamed_blank_bill = int(
        _scalar(
            conn,
            f"SELECT COUNT(*) FROM sales_invoices WHERE {unnamed_predicate} "
            "AND (bill_no IS NULL OR TRIM(bill_no) = '')",
        )
        or 0
    )
    unnamed_with_number = unnamed - unnamed_blank_bill

    # Rows whose customer is the WALKIN customer, split by patient-name marker.
    # The second count must stay zero: WALKIN patient rows are not classified
    # as unnamed and are never bulk-edited by this feature.
    walkin_customer_unnamed = 0
    if _table_exists(conn, "customers"):
        walkin_customer_unnamed = int(
            _scalar(
                conn,
                f"""
                SELECT COUNT(*)
                FROM sales_invoices si
                LEFT JOIN customers c ON c.id = si.customer_id
                WHERE {unnamed_predicate.replace('patient_name', 'si.patient_name')}
                  AND UPPER(TRIM(COALESCE(c.customer_name, ''))) = 'WALKIN'
                """,
            )
            or 0
        )

    shapes: Counter[str] = Counter()
    for row in conn.execute(
        f"SELECT bill_no FROM sales_invoices WHERE {unnamed_predicate}"
    ):
        shapes[_bill_shape(row["bill_no"] or "")] += 1

    # Non-empty numbers must be unique.  Blank values are intentionally shared.
    duplicate_numbers = [
        dict(row)
        for row in conn.execute(
            """
            SELECT bill_no, COUNT(*) AS copies
            FROM sales_invoices
            WHERE bill_no IS NOT NULL AND TRIM(bill_no) <> ''
            GROUP BY bill_no
            HAVING COUNT(*) > 1
            ORDER BY copies DESC, bill_no
            LIMIT 50
            """
        )
    ]

    indexes = [
        dict(row)
        for row in conn.execute("PRAGMA index_list(sales_invoices)")
    ]
    partial_index = any(
        row.get("name") == "ux_sales_invoices_bill_no_nonblank"
        and int(row.get("unique") or 0) == 1
        for row in indexes
    )

    schema_sql = _scalar(
        conn,
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='sales_invoices'",
    )
    schema_inline_unique = bool(
        schema_sql and "bill_no" in schema_sql and "UNIQUE" in schema_sql.split("bill_no", 1)[1].split(",", 1)[0]
    )

    return {
        "database": str(conn.execute("PRAGMA database_list").fetchone()["file"]),
        "totals": {
            "sales_invoices": total,
            "unnamed_patient": unnamed,
            "named_patient": named,
            "stored_patient_walkin": stored_walkin,
            "blank_bill_no": blank_bill,
            "unnamed_with_blank_bill_no": unnamed_blank_bill,
            "unnamed_with_stored_bill_no": unnamed_with_number,
            "unnamed_with_walkin_customer": walkin_customer_unnamed,
        },
        "unnamed_bill_shapes": dict(sorted(shapes.items())),
        "duplicate_nonblank_bill_numbers": duplicate_numbers,
        "schema": {
            "partial_unique_nonblank_index": partial_index,
            "inline_bill_no_unique": schema_inline_unique,
        },
        "notes": [
            "Identification uses only patient_name IS NULL OR TRIM(patient_name) = ''.",
            "Rows with patient_name = 'WALKIN' are reported separately and are not treated as unnamed.",
            "No historical row, bill number, index, or sequence is changed by this audit.",
        ],
    }


def print_report(report: dict[str, Any]) -> None:
    totals = report["totals"]
    print("Counter Sale unnamed-sales audit (READ-ONLY)")
    print(f"Database: {report['database']}")
    print()
    print(f"  Total sales invoices          : {totals['sales_invoices']:,}")
    print(f"  Unnamed patient (reliable)    : {totals['unnamed_patient']:,}")
    print(f"  Named patient                 : {totals['named_patient']:,}")
    print(f"  Stored patient 'WALKIN'       : {totals['stored_patient_walkin']:,} (not assumed unnamed)")
    print(f"  Blank stored Bill No          : {totals['blank_bill_no']:,}")
    print(f"  Unnamed + blank Bill No       : {totals['unnamed_with_blank_bill_no']:,}")
    print(f"  Unnamed + stored Bill No      : {totals['unnamed_with_stored_bill_no']:,} "
          "(displayed blank, stored value preserved)")
    print(f"  Unnamed + WALKIN customer     : {totals['unnamed_with_walkin_customer']:,}")
    print()
    print("  Unnamed stored Bill No shapes:")
    for shape, count in report["unnamed_bill_shapes"].items():
        print(f"    {shape:<28}: {count:,}")
    print()
    schema = report["schema"]
    print(f"  Partial unique nonblank index : {schema['partial_unique_nonblank_index']}")
    print(f"  Inline bill_no UNIQUE remains : {schema['inline_bill_no_unique']}")
    duplicates = report["duplicate_nonblank_bill_numbers"]
    print(f"  Duplicate nonblank bill nos   : {len(duplicates):,}")
    if duplicates:
        for row in duplicates[:10]:
            print(f"    {row['bill_no']!r}: {row['copies']} copies")
    print()
    print("  No data was modified.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=None, help="SQLite database to audit (read-only)")
    parser.add_argument("--json", type=Path, default=None, help="Also write the full report as JSON")
    args = parser.parse_args(argv)

    path = args.db or default_db_path()
    if not path.exists():
        print(f"Database not found: {path}", file=sys.stderr)
        return 2
    try:
        conn = open_read_only(path)
    except sqlite3.Error as exc:
        print(f"Cannot open database read-only: {exc}", file=sys.stderr)
        return 2
    try:
        report = build_audit(conn)
    finally:
        conn.close()

    print_report(report)
    if args.json:
        args.json.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nJSON report written to {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
