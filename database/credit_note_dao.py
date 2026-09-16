from __future__ import annotations

import sqlite3
from typing import Optional, List

from database.connection import get_connection
from database.accounting_posting import (
    SOURCE_CREDIT_NOTE,
    posting_engine,
)


class CreditNoteDAO:

    # ── helpers ────────────────────────────────────────────────────────
    @staticmethod
    def generate_next_voucher_no(conn: sqlite3.Connection) -> str:
        cur = conn.execute(
            "SELECT voucher_no FROM credit_notes ORDER BY id DESC LIMIT 1"
        )
        row = cur.fetchone()
        if row is None:
            return "CN-0001"
        last_num = int(row[0].split("-")[1])
        return f"CN-{last_num + 1:04d}"

    # ── read ───────────────────────────────────────────────────────────
    @staticmethod
    def get_all() -> List[dict]:
        conn = get_connection()
        try:
            rows = conn.execute(
                """
                SELECT c.id, c.voucher_no, c.voucher_date, c.cn_date,
                       c.cn_type, c.customer_id,
                       cu.customer_name AS customer_name,
                       c.total_amount, c.ledger_amount, c.remarks
                FROM credit_notes c
                LEFT JOIN customers cu ON cu.id = c.customer_id
                ORDER BY c.id DESC
                """
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    @staticmethod
    def get_by_id(cn_id: int) -> Optional[dict]:
        conn = get_connection()
        try:
            cur = conn.execute(
                """
                SELECT c.id, c.voucher_no, c.voucher_date, c.voucher_time,
                       c.cn_date, c.cn_type, c.customer_id,
                       cu.customer_name AS customer_name,
                       c.total_amount, c.ledger_amount, c.remarks
                FROM credit_notes c
                LEFT JOIN customers cu ON cu.id = c.customer_id
                WHERE c.id = ?
                """,
                (cn_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    @staticmethod
    def get_invoice_items(cn_id: int) -> List[dict]:
        conn = get_connection()
        try:
            rows = conn.execute(
                """
                SELECT ci.id, ci.credit_note_id, ci.item_id,
                       i.item_name AS item_name,
                       ci.stock_batch_id, ci.batch_no, ci.expiry,
                       ci.pack_size, ci.rate, ci.mrp,
                       ci.return_qty, ci.less_amount, ci.amount,
                       ci.return_reason, ci.price_factor
                FROM credit_note_items ci
                LEFT JOIN items i ON i.id = ci.item_id
                WHERE ci.credit_note_id = ?
                """,
                (cn_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    @staticmethod
    def get_all_filtered(
        voucher_from: str = "",
        voucher_to: str = "",
        party: str = "",
        voucher_no: str = "",
    ) -> List[dict]:
        conn = get_connection()
        try:
            clauses: list[str] = []
            params: list = []
            if voucher_from:
                clauses.append("c.voucher_date >= ?")
                params.append(voucher_from)
            if voucher_to:
                clauses.append("c.voucher_date <= ?")
                params.append(voucher_to)
            if party:
                clauses.append("cu.customer_name LIKE ?")
                params.append(f"%{party}%")
            if voucher_no:
                clauses.append("c.voucher_no LIKE ?")
                params.append(f"%{voucher_no}%")
            where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
            sql = f"""
                SELECT c.id, c.voucher_no, c.voucher_date, c.cn_date,
                       c.cn_type, c.customer_id,
                       cu.customer_name AS customer_name,
                       c.total_amount, c.ledger_amount, c.remarks
                FROM credit_notes c
                LEFT JOIN customers cu ON cu.id = c.customer_id
                {where}
                ORDER BY c.id DESC
            """
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ── write (single transaction) ─────────────────────────────────────
    @staticmethod
    def insert_credit_note(header: dict, items: list[dict]) -> int:
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("BEGIN")
            cur.execute("PRAGMA journal_mode = WAL")

            voucher_no = CreditNoteDAO.generate_next_voucher_no(conn)

            cur.execute(
                """
                INSERT INTO credit_notes
                    (voucher_no, voucher_date, cn_date, cn_type,
                     customer_id, total_amount, ledger_amount, remarks)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    voucher_no,
                    header["voucher_date"],
                    header.get("cn_date", ""),
                    header.get("cn_type", "Customer"),
                    header["customer_id"],
                    header.get("total_amount", 0.0),
                    header.get("ledger_amount", 0.0),
                    header.get("remarks", ""),
                ),
            )
            cn_id = cur.lastrowid

            for item in items:
                cur.execute(
                    """
                    INSERT INTO credit_note_items
                        (credit_note_id, item_id, stock_batch_id, batch_no,
                         expiry, pack_size, rate, mrp, return_qty,
                         less_amount, amount, return_reason, price_factor)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        cn_id,
                        item["item_id"],
                        item["stock_batch_id"],
                        item["batch_no"],
                        item.get("expiry", ""),
                        item.get("pack_size", ""),
                        item.get("rate", 0.0),
                        item.get("mrp", 0.0),
                        item.get("return_qty", 0.0),
                        item.get("less_amount", 0.0),
                        item.get("amount", 0.0),
                        item.get("return_reason", ""),
                        item.get("price_factor", 1.0),
                    ),
                )
                # Credit note RESTORES stock (opposite of sale)
                cur.execute(
                    """
                    UPDATE stock_batches
                    SET stock_qty = stock_qty + ?
                    WHERE id = ?
                    """,
                    (item.get("return_qty", 0), item["stock_batch_id"]),
                )

            # Accounting posting joins THIS transaction (atomic with save).
            posting_engine.post_credit_note(cn_id, cur=cur)

            conn.commit()
            return cn_id
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def update_credit_note(cn_id: int, header: dict, items: list[dict]) -> bool:
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("BEGIN")

            # Reverse previous accounting posting inside THIS transaction
            posting_engine.reverse(SOURCE_CREDIT_NOTE, cn_id, cur=cur)

            # Reverse old stock increases
            old_items = cur.execute(
                "SELECT stock_batch_id, return_qty FROM credit_note_items WHERE credit_note_id = ?",
                (cn_id,),
            ).fetchall()
            for oi in old_items:
                cur.execute(
                    "UPDATE stock_batches SET stock_qty = stock_qty - ? WHERE id = ?",
                    (oi["return_qty"], oi["stock_batch_id"]),
                )

            cur.execute(
                "DELETE FROM credit_note_items WHERE credit_note_id = ?",
                (cn_id,),
            )
            cur.execute(
                """
                UPDATE credit_notes SET
                    voucher_date = ?, cn_date = ?, cn_type = ?,
                    customer_id = ?, total_amount = ?, ledger_amount = ?,
                    remarks = ?
                WHERE id = ?
                """,
                (
                    header["voucher_date"],
                    header.get("cn_date", ""),
                    header.get("cn_type", "Customer"),
                    header["customer_id"],
                    header.get("total_amount", 0.0),
                    header.get("ledger_amount", 0.0),
                    header.get("remarks", ""),
                    cn_id,
                ),
            )
            for item in items:
                cur.execute(
                    """
                    INSERT INTO credit_note_items
                        (credit_note_id, item_id, stock_batch_id, batch_no,
                         expiry, pack_size, rate, mrp, return_qty,
                         less_amount, amount, return_reason, price_factor)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        cn_id,
                        item["item_id"],
                        item["stock_batch_id"],
                        item["batch_no"],
                        item.get("expiry", ""),
                        item.get("pack_size", ""),
                        item.get("rate", 0.0),
                        item.get("mrp", 0.0),
                        item.get("return_qty", 0.0),
                        item.get("less_amount", 0.0),
                        item.get("amount", 0.0),
                        item.get("return_reason", ""),
                        item.get("price_factor", 1.0),
                    ),
                )
                # Re-apply stock increase
                cur.execute(
                    "UPDATE stock_batches SET stock_qty = stock_qty + ? WHERE id = ?",
                    (item.get("return_qty", 0), item["stock_batch_id"]),
                )

            # Post new accounting effect inside THIS transaction
            posting_engine.post_credit_note(cn_id, cur=cur)

            conn.commit()
            return True
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def delete_credit_note(cn_id: int) -> bool:
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("BEGIN")

            # Reverse the accounting posting inside THIS transaction
            posting_engine.reverse(SOURCE_CREDIT_NOTE, cn_id, cur=cur)

            # Reverse stock increases
            items = cur.execute(
                "SELECT stock_batch_id, return_qty FROM credit_note_items WHERE credit_note_id = ?",
                (cn_id,),
            ).fetchall()
            for it in items:
                cur.execute(
                    "UPDATE stock_batches SET stock_qty = stock_qty - ? WHERE id = ?",
                    (it["return_qty"], it["stock_batch_id"]),
                )
            cur.execute(
                "DELETE FROM credit_note_items WHERE credit_note_id = ?",
                (cn_id,),
            )
            cur.execute("DELETE FROM credit_notes WHERE id = ?", (cn_id,))
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
