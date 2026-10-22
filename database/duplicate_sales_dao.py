"""DAO and schema management for Duplicate Sales Bills.

These records are completely isolated and print-only:
- They NEVER touch stock, inventory batches, ledger postings, customer balances,
  cash book, bank book, VAT/GST reports, or sales reports.
- They have their own independent voucher number sequence.
- All values are stored as plain text and numbers.
"""

from __future__ import annotations

from typing import Any
from database.connection import get_connection


def ensure_duplicate_sales_schema() -> None:
    """Create the two duplicate sales bill tables if they do not exist."""
    conn = get_connection()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS dup_sales_bill_head (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                voucher_no          INTEGER NOT NULL,
                financial_year      TEXT NOT NULL DEFAULT '',
                vh_date             TEXT NOT NULL DEFAULT '',
                vh_time             TEXT NOT NULL DEFAULT '',
                cnt_no              TEXT DEFAULT '',
                bill_type           TEXT DEFAULT 'Cash',
                customer_name       TEXT DEFAULT 'WALKIN',
                patient_name        TEXT DEFAULT '',
                bill_no             TEXT DEFAULT '',
                address             TEXT DEFAULT '',
                doctor_name         TEXT DEFAULT '',
                discount            REAL DEFAULT 0.0,
                paid_amount         REAL DEFAULT 0.0,
                total_items         INTEGER DEFAULT 0,
                remarks             TEXT DEFAULT '',
                total_amount        REAL DEFAULT 0.0,
                less_bill_discount  REAL DEFAULT 0.0,
                less_cn_amt         REAL DEFAULT 0.0,
                add_dr_amt          REAL DEFAULT 0.0,
                round_off           REAL DEFAULT 0.0,
                net_amount          REAL DEFAULT 0.0,
                created_on          TEXT DEFAULT (datetime('now', 'localtime')),
                created_by          TEXT DEFAULT 'admin',
                last_edited_on      TEXT DEFAULT ''
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS dup_sales_bill_item (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                dup_bill_id         INTEGER NOT NULL,
                sr_no               INTEGER DEFAULT 1,
                item_name           TEXT DEFAULT '',
                pack_size           TEXT DEFAULT '',
                location            TEXT DEFAULT '',
                batch_no            TEXT DEFAULT '',
                expiry              TEXT DEFAULT '',
                mrp                 REAL DEFAULT 0.0,
                sales_date          TEXT DEFAULT '',
                sales_qty           REAL DEFAULT 0.0,
                disc                REAL DEFAULT 0.0,
                disc_amt            REAL DEFAULT 0.0,
                amount              REAL DEFAULT 0.0
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_dup_sales_vh_date ON dup_sales_bill_head(vh_date);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_dup_sales_fy ON dup_sales_bill_head(financial_year);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_dup_sales_items_bill ON dup_sales_bill_item(dup_bill_id);")
        conn.commit()
    finally:
        conn.close()


class DuplicateSalesDAO:
    """Data Access Object for separate print-only Duplicate Sales Bills."""

    @staticmethod
    def get_next_voucher_no() -> int:
        """Return the next sequential voucher number for duplicate sales bills."""
        ensure_duplicate_sales_schema()
        conn = get_connection()
        try:
            cur = conn.execute("SELECT COALESCE(MAX(voucher_no), 0) + 1 FROM dup_sales_bill_head")
            row = cur.fetchone()
            return int(row[0]) if row and row[0] else 1
        finally:
            conn.close()

    @staticmethod
    def insert_bill(head: dict[str, Any], items: list[dict[str, Any]]) -> int:
        """Insert a new duplicate sales bill header and its item rows."""
        ensure_duplicate_sales_schema()
        conn = get_connection()
        try:
            voucher_no = head.get("voucher_no")
            if not voucher_no:
                cur = conn.execute("SELECT COALESCE(MAX(voucher_no), 0) + 1 FROM dup_sales_bill_head")
                voucher_no = cur.fetchone()[0]

            cur = conn.execute(
                """
                INSERT INTO dup_sales_bill_head (
                    voucher_no, financial_year, vh_date, vh_time, cnt_no,
                    bill_type, customer_name, patient_name, bill_no, address,
                    doctor_name, discount, paid_amount, total_items, remarks,
                    total_amount, less_bill_discount, less_cn_amt, add_dr_amt,
                    round_off, net_amount, created_by
                ) VALUES (
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?
                )
                """,
                (
                    int(voucher_no),
                    str(head.get("financial_year") or ""),
                    str(head.get("vh_date") or ""),
                    str(head.get("vh_time") or ""),
                    str(head.get("cnt_no") or ""),
                    str(head.get("bill_type") or "Cash"),
                    str(head.get("customer_name") or "WALKIN"),
                    str(head.get("patient_name") or ""),
                    str(head.get("bill_no") or ""),
                    str(head.get("address") or ""),
                    str(head.get("doctor_name") or ""),
                    float(head.get("discount") or 0.0),
                    float(head.get("paid_amount") or 0.0),
                    len(items),
                    str(head.get("remarks") or ""),
                    float(head.get("total_amount") or 0.0),
                    float(head.get("less_bill_discount") or 0.0),
                    float(head.get("less_cn_amt") or 0.0),
                    float(head.get("add_dr_amt") or 0.0),
                    float(head.get("round_off") or 0.0),
                    float(head.get("net_amount") or 0.0),
                    str(head.get("created_by") or "admin"),
                ),
            )
            dup_id = cur.lastrowid
            if not dup_id:
                raise RuntimeError("Failed to obtain lastrowid for duplicate sales bill.")

            for idx, itm in enumerate(items, start=1):
                conn.execute(
                    """
                    INSERT INTO dup_sales_bill_item (
                        dup_bill_id, sr_no, item_name, pack_size, location,
                        batch_no, expiry, mrp, sales_date, sales_qty,
                        disc, disc_amt, amount
                    ) VALUES (
                        ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?,
                        ?, ?, ?
                    )
                    """,
                    (
                        dup_id,
                        idx,
                        str(itm.get("item_name") or ""),
                        str(itm.get("pack_size") or ""),
                        str(itm.get("location") or ""),
                        str(itm.get("batch_no") or ""),
                        str(itm.get("expiry") or ""),
                        float(itm.get("mrp") or 0.0),
                        str(itm.get("sales_date") or head.get("vh_date") or ""),
                        float(itm.get("sales_qty") or 0.0),
                        float(itm.get("disc") or 0.0),
                        float(itm.get("disc_amt") or 0.0),
                        float(itm.get("amount") or 0.0),
                    ),
                )

            conn.commit()
            return dup_id
        finally:
            conn.close()

    @staticmethod
    def update_bill(dup_id: int, head: dict[str, Any], items: list[dict[str, Any]]) -> bool:
        """Update an existing duplicate sales bill, preserving created_on."""
        ensure_duplicate_sales_schema()
        conn = get_connection()
        try:
            conn.execute(
                """
                UPDATE dup_sales_bill_head SET
                    financial_year = ?,
                    vh_date = ?,
                    vh_time = ?,
                    cnt_no = ?,
                    bill_type = ?,
                    customer_name = ?,
                    patient_name = ?,
                    bill_no = ?,
                    address = ?,
                    doctor_name = ?,
                    discount = ?,
                    paid_amount = ?,
                    total_items = ?,
                    remarks = ?,
                    total_amount = ?,
                    less_bill_discount = ?,
                    less_cn_amt = ?,
                    add_dr_amt = ?,
                    round_off = ?,
                    net_amount = ?,
                    last_edited_on = datetime('now', 'localtime')
                WHERE id = ?
                """,
                (
                    str(head.get("financial_year") or ""),
                    str(head.get("vh_date") or ""),
                    str(head.get("vh_time") or ""),
                    str(head.get("cnt_no") or ""),
                    str(head.get("bill_type") or "Cash"),
                    str(head.get("customer_name") or "WALKIN"),
                    str(head.get("patient_name") or ""),
                    str(head.get("bill_no") or ""),
                    str(head.get("address") or ""),
                    str(head.get("doctor_name") or ""),
                    float(head.get("discount") or 0.0),
                    float(head.get("paid_amount") or 0.0),
                    len(items),
                    str(head.get("remarks") or ""),
                    float(head.get("total_amount") or 0.0),
                    float(head.get("less_bill_discount") or 0.0),
                    float(head.get("less_cn_amt") or 0.0),
                    float(head.get("add_dr_amt") or 0.0),
                    float(head.get("round_off") or 0.0),
                    float(head.get("net_amount") or 0.0),
                    dup_id,
                ),
            )

            conn.execute("DELETE FROM dup_sales_bill_item WHERE dup_bill_id = ?", (dup_id,))

            for idx, itm in enumerate(items, start=1):
                conn.execute(
                    """
                    INSERT INTO dup_sales_bill_item (
                        dup_bill_id, sr_no, item_name, pack_size, location,
                        batch_no, expiry, mrp, sales_date, sales_qty,
                        disc, disc_amt, amount
                    ) VALUES (
                        ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?,
                        ?, ?, ?
                    )
                    """,
                    (
                        dup_id,
                        idx,
                        str(itm.get("item_name") or ""),
                        str(itm.get("pack_size") or ""),
                        str(itm.get("location") or ""),
                        str(itm.get("batch_no") or ""),
                        str(itm.get("expiry") or ""),
                        float(itm.get("mrp") or 0.0),
                        str(itm.get("sales_date") or head.get("vh_date") or ""),
                        float(itm.get("sales_qty") or 0.0),
                        float(itm.get("disc") or 0.0),
                        float(itm.get("disc_amt") or 0.0),
                        float(itm.get("amount") or 0.0),
                    ),
                )

            conn.commit()
            return True
        finally:
            conn.close()

    @staticmethod
    def get_bill_by_id(dup_id: int) -> dict[str, Any] | None:
        """Fetch header dict for a given duplicate bill ID."""
        ensure_duplicate_sales_schema()
        conn = get_connection()
        try:
            cur = conn.execute("SELECT * FROM dup_sales_bill_head WHERE id = ?", (dup_id,))
            row = cur.fetchone()
            if not row:
                return None
            cols = [desc[0] for desc in cur.description]
            return dict(zip(cols, row))
        finally:
            conn.close()

    @staticmethod
    def get_bill_items(dup_id: int) -> list[dict[str, Any]]:
        """Fetch item rows for a given duplicate bill ID."""
        ensure_duplicate_sales_schema()
        conn = get_connection()
        try:
            cur = conn.execute(
                "SELECT * FROM dup_sales_bill_item WHERE dup_bill_id = ? ORDER BY sr_no ASC, id ASC",
                (dup_id,),
            )
            cols = [desc[0] for desc in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def search_bills(
        from_date: str = "",
        to_date: str = "",
        search_text: str = "",
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Search duplicate sales bills sorted by vh_date DESC, voucher_no DESC."""
        ensure_duplicate_sales_schema()
        conn = get_connection()
        try:
            clauses = []
            params: list[Any] = []

            if from_date:
                clauses.append("vh_date >= ?")
                params.append(from_date)
            if to_date:
                clauses.append("vh_date <= ?")
                params.append(to_date)
            if search_text and search_text.strip():
                clean = search_text.strip()
                clauses.append(
                    "(customer_name LIKE ? OR bill_no LIKE ? OR CAST(voucher_no AS TEXT) LIKE ? OR patient_name LIKE ?)"
                )
                p_wild = f"%{clean}%"
                params.extend([p_wild, p_wild, p_wild, p_wild])

            where_sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""
            sql = f"""
                SELECT * FROM dup_sales_bill_head
                {where_sql}
                ORDER BY vh_date DESC, voucher_no DESC
                LIMIT ?
            """
            params.append(limit)
            cur = conn.execute(sql, params)
            cols = [desc[0] for desc in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def get_item_name_suggestions(query: str = "", limit: int = 25) -> list[str]:
        """Read-only autocomplete suggestions from items table for convenient typing."""
        conn = get_connection()
        try:
            if query and query.strip():
                cur = conn.execute(
                    """
                    SELECT DISTINCT item_name FROM items
                    WHERE item_name LIKE ? AND item_name IS NOT NULL AND item_name != ''
                    ORDER BY item_name ASC LIMIT ?
                    """,
                    (f"%{query.strip()}%", limit),
                )
            else:
                cur = conn.execute(
                    """
                    SELECT DISTINCT item_name FROM items
                    WHERE item_name IS NOT NULL AND item_name != ''
                    ORDER BY item_name ASC LIMIT ?
                    """,
                    (limit,),
                )
            return [r[0] for r in cur.fetchall() if r[0]]
        except Exception:
            return []
        finally:
            conn.close()

