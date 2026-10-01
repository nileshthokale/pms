"""Hold Bill DAO — temporary draft-sale storage.

A held bill is a DRAFT only.  It does NOT:
  - reduce stock
  - create sales invoice accounting postings
  - change customer balance
  - affect Trial Balance / P&L / Balance Sheet
  - appear in completed sales history

The sale is finalized ONLY when the user completes it through the
normal SalesDAO.insert_invoice flow after resuming the draft.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from database.connection import get_connection

# Hold statuses
STATUS_ACTIVE = "ACTIVE"
STATUS_RESUMED = "RESUMED"
STATUS_DISCARDED = "DISCARDED"


def ensure_hold_tables() -> None:
    """Create hold_bill / hold_bill_items tables if missing."""
    conn = get_connection()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS hold_bills (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                hold_number         TEXT    NOT NULL UNIQUE,
                created_at          TEXT    NOT NULL,
                updated_at          TEXT    NOT NULL,
                customer_id         INTEGER REFERENCES customers(id) ON DELETE SET NULL,
                patient_name        TEXT    DEFAULT '',
                doctor_id           INTEGER REFERENCES doctors(id) ON DELETE SET NULL,
                counter_no          TEXT    DEFAULT '',
                remarks             TEXT    DEFAULT '',
                status              TEXT    NOT NULL DEFAULT 'ACTIVE',
                total_amount_preview REAL   DEFAULT 0.0,
                created_by          TEXT    DEFAULT '',
                updated_by          TEXT    DEFAULT ''
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS hold_bill_items (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                hold_bill_id        INTEGER NOT NULL REFERENCES hold_bills(id) ON DELETE CASCADE,
                item_id             INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
                item_name_snapshot  TEXT    DEFAULT '',
                batch_no            TEXT    NOT NULL,
                pack_size           TEXT    DEFAULT '',
                location            TEXT    DEFAULT '',
                expiry              TEXT    DEFAULT '',
                mrp                 REAL    DEFAULT 0.0,
                sale_qty            REAL    DEFAULT 0.0,
                discount_amount     REAL    DEFAULT 0.0,
                amount              REAL    DEFAULT 0.0,
                ordering            INTEGER DEFAULT 0
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def _generate_next_hold_number(conn: sqlite3.Connection) -> str:
    """Generate next HOLD-NNNN number."""
    row = conn.execute(
        "SELECT hold_number FROM hold_bills ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return "HOLD-0001"
    last = row[0] if isinstance(row, sqlite3.Row) else row["hold_number"]
    idx = last.rfind("-")
    if idx >= 0:
        prefix = last[: idx + 1]
        num_part = last[idx + 1:]
    else:
        prefix = "HOLD-"
        num_part = last
    try:
        num = int(num_part) + 1
    except ValueError:
        num = 1
    return f"{prefix}{num:04d}"


def create_hold(
    *,
    customer_id: int | None = None,
    patient_name: str = "",
    doctor_id: int | None = None,
    counter_no: str = "",
    remarks: str = "",
    total_amount_preview: float = 0.0,
    created_by: str = "",
    items: list[dict] | None = None,
) -> int:
    """Create a new held bill. Returns the hold_bill id.

    Each item dict must contain:
      item_id, item_name_snapshot, batch_no, pack_size, location, expiry,
      mrp, sale_qty, discount_amount, amount.
    """
    ensure_hold_tables()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("BEGIN")

        hold_number = _generate_next_hold_number(cur)

        cur.execute(
            """
            INSERT INTO hold_bills (
                hold_number, created_at, updated_at,
                customer_id, patient_name, doctor_id,
                counter_no, remarks, status,
                total_amount_preview, created_by, updated_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                hold_number, now, now,
                customer_id, patient_name, doctor_id,
                counter_no, remarks, STATUS_ACTIVE,
                total_amount_preview, created_by, created_by,
            ),
        )
        hold_bill_id = cur.lastrowid

        for idx, item in enumerate(items or []):
            cur.execute(
                """
                INSERT INTO hold_bill_items (
                    hold_bill_id, item_id, item_name_snapshot,
                    batch_no, pack_size, location, expiry, mrp,
                    sale_qty, discount_amount, amount, ordering
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    hold_bill_id,
                    item["item_id"],
                    item.get("item_name_snapshot", ""),
                    item["batch_no"],
                    item.get("pack_size", ""),
                    item.get("location", ""),
                    item.get("expiry", ""),
                    item.get("mrp", 0.0),
                    item.get("sale_qty", 0.0),
                    item.get("discount_amount", 0.0),
                    item.get("amount", 0.0),
                    idx,
                ),
            )

        conn.commit()
        return hold_bill_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_all(status: str | None = None) -> list[dict]:
    """Return all held bills, optionally filtered by status."""
    ensure_hold_tables()
    conn = get_connection()
    try:
        if status:
            cur = conn.execute(
                """
                SELECT hb.*, c.customer_name, d.doctor_name
                FROM hold_bills hb
                LEFT JOIN customers c ON c.id = hb.customer_id
                LEFT JOIN doctors d ON d.id = hb.doctor_id
                WHERE hb.status = ?
                ORDER BY hb.id DESC
                """,
                (status,),
            )
        else:
            cur = conn.execute(
                """
                SELECT hb.*, c.customer_name, d.doctor_name
                FROM hold_bills hb
                LEFT JOIN customers c ON c.id = hb.customer_id
                LEFT JOIN doctors d ON d.id = hb.doctor_id
                ORDER BY hb.id DESC
                """
            )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def get_by_id(hold_bill_id: int) -> dict | None:
    """Return a single held bill or None."""
    ensure_hold_tables()
    conn = get_connection()
    try:
        cur = conn.execute(
            """
            SELECT hb.*, c.customer_name, d.doctor_name
            FROM hold_bills hb
            LEFT JOIN customers c ON c.id = hb.customer_id
            LEFT JOIN doctors d ON d.id = hb.doctor_id
            WHERE hb.id = ?
            """,
            (hold_bill_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_hold_items(hold_bill_id: int) -> list[dict]:
    """Return items belonging to a held bill."""
    ensure_hold_tables()
    conn = get_connection()
    try:
        cur = conn.execute(
            """
            SELECT hbi.*, i.item_name
            FROM hold_bill_items hbi
            LEFT JOIN items i ON i.id = hbi.item_id
            WHERE hbi.hold_bill_id = ?
            ORDER BY hbi.ordering
            """,
            (hold_bill_id,),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def update_status(hold_bill_id: int, status: str, updated_by: str = "") -> None:
    """Update hold bill status (RESUMED / DISCARDED)."""
    ensure_hold_tables()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE hold_bills SET status = ?, updated_at = ?, updated_by = ? WHERE id = ?",
            (status, now, updated_by, hold_bill_id),
        )
        conn.commit()
    finally:
        conn.close()


def delete_hold(hold_bill_id: int) -> None:
    """Delete a held bill and its items. Cascade handles items."""
    ensure_hold_tables()
    conn = get_connection()
    try:
        conn.execute("DELETE FROM hold_bills WHERE id = ?", (hold_bill_id,))
        conn.commit()
    finally:
        conn.close()


def count_active() -> int:
    """Return count of active held bills."""
    ensure_hold_tables()
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM hold_bills WHERE status = ?",
            (STATUS_ACTIVE,),
        ).fetchone()
        return row[0]
    finally:
        conn.close()
