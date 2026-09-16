from __future__ import annotations

import sqlite3
from typing import Optional, List

from database.connection import get_connection
from database.accounting_posting import (
    SOURCE_DEBIT_NOTE,
    posting_engine,
)


class DebitNoteDAO:

    # ── helpers ────────────────────────────────────────────────────────
    @staticmethod
    def generate_next_voucher_no(conn: sqlite3.Connection) -> str:
        cur = conn.execute(
            "SELECT voucher_no FROM debit_notes ORDER BY id DESC LIMIT 1"
        )
        row = cur.fetchone()
        if row is None:
            return "DN-0001"
        last_num = int(row[0].split("-")[1])
        return f"DN-{last_num + 1:04d}"

    # ── read ───────────────────────────────────────────────────────────
    @staticmethod
    def get_all() -> List[dict]:
        conn = get_connection()
        try:
            rows = conn.execute(
                """
                SELECT d.id, d.voucher_no, d.voucher_date, d.voucher_time,
                       d.dn_date, d.dn_type, d.supplier_id,
                       s.supplier_name,
                       d.total_amount, d.ledger_amount, d.remarks
                FROM debit_notes d
                LEFT JOIN suppliers s ON s.id = d.supplier_id
                ORDER BY d.id DESC
                """
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    @staticmethod
    def get_by_id(dn_id: int) -> Optional[dict]:
        conn = get_connection()
        try:
            cur = conn.execute(
                """
                SELECT d.id, d.voucher_no, d.voucher_date, d.voucher_time,
                       d.dn_date, d.dn_type, d.supplier_id,
                       s.supplier_name,
                       d.total_amount, d.ledger_amount, d.remarks
                FROM debit_notes d
                LEFT JOIN suppliers s ON s.id = d.supplier_id
                WHERE d.id = ?
                """,
                (dn_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    @staticmethod
    def get_items(dn_id: int) -> List[dict]:
        conn = get_connection()
        try:
            rows = conn.execute(
                """
                SELECT di.id, di.debit_note_id, di.item_id,
                       i.item_name,
                       di.stock_batch_id, di.batch_no, di.expiry,
                       di.pack_size, di.rate, di.mrp,
                       di.return_qty, di.less_amount, di.amount,
                       di.return_reason, di.price_factor
                FROM debit_note_items di
                LEFT JOIN items i ON i.id = di.item_id
                WHERE di.debit_note_id = ?
                """,
                (dn_id,),
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
                clauses.append("d.voucher_date >= ?")
                params.append(voucher_from)
            if voucher_to:
                clauses.append("d.voucher_date <= ?")
                params.append(voucher_to)
            if party:
                clauses.append("s.supplier_name LIKE ?")
                params.append(f"%{party}%")
            if voucher_no:
                clauses.append("d.voucher_no LIKE ?")
                params.append(f"%{voucher_no}%")
            where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
            sql = f"""
                SELECT d.id, d.voucher_no, d.voucher_date, d.voucher_time,
                       d.dn_date, d.dn_type, d.supplier_id,
                       s.supplier_name,
                       d.total_amount, d.ledger_amount, d.remarks
                FROM debit_notes d
                LEFT JOIN suppliers s ON s.id = d.supplier_id
                {where}
                ORDER BY d.id DESC
            """
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ── write (single transaction) ─────────────────────────────────────
    @staticmethod
    def insert_debit_note(header: dict, items: list[dict]) -> int:
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("BEGIN")

            voucher_no = DebitNoteDAO.generate_next_voucher_no(conn)

            cur.execute(
                """
                INSERT INTO debit_notes
                    (voucher_no, voucher_date, voucher_time, dn_date, dn_type,
                     supplier_id, total_amount, ledger_amount, remarks)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    voucher_no,
                    header["voucher_date"],
                    header.get("voucher_time", ""),
                    header.get("dn_date", ""),
                    header.get("dn_type", "Supplier"),
                    header["supplier_id"],
                    header.get("total_amount", 0.0),
                    header.get("ledger_amount", 0.0),
                    header.get("remarks", ""),
                ),
            )
            dn_id = cur.lastrowid

            for item in items:
                # Validate stock before deducting
                cur.execute(
                    "SELECT stock_qty FROM stock_batches WHERE id = ?",
                    (item["stock_batch_id"],),
                )
                batch = cur.fetchone()
                if batch is None:
                    raise ValueError(f"Stock batch {item['stock_batch_id']} not found")
                available = batch["stock_qty"]
                return_qty = item.get("return_qty", 0)
                if return_qty <= 0:
                    raise ValueError("Return quantity must be greater than 0")
                if return_qty > available:
                    raise ValueError(
                        f"Insufficient stock: batch has {available:.0f}, "
                        f"cannot return {return_qty:.0f}"
                    )

                cur.execute(
                    """
                    INSERT INTO debit_note_items
                        (debit_note_id, item_id, stock_batch_id, batch_no,
                         expiry, pack_size, rate, mrp, return_qty,
                         less_amount, amount, return_reason, price_factor)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        dn_id,
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
                # Debit note DECREASES stock (goods returned to supplier)
                cur.execute(
                    """
                    UPDATE stock_batches
                    SET stock_qty = stock_qty - ?
                    WHERE id = ?
                    """,
                    (item.get("return_qty", 0), item["stock_batch_id"]),
                )

            # Accounting posting joins THIS transaction (atomic with save).
            posting_engine.post_debit_note(dn_id, cur=cur)

            conn.commit()
            return dn_id
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def update_debit_note(dn_id: int, header: dict, items: list[dict]) -> bool:
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("BEGIN")

            # Reverse previous accounting posting inside THIS transaction
            posting_engine.reverse(SOURCE_DEBIT_NOTE, dn_id, cur=cur)

            # Reverse old stock deductions
            old_items = cur.execute(
                "SELECT stock_batch_id, return_qty FROM debit_note_items WHERE debit_note_id = ?",
                (dn_id,),
            ).fetchall()
            for oi in old_items:
                cur.execute(
                    "UPDATE stock_batches SET stock_qty = stock_qty + ? WHERE id = ?",
                    (oi["return_qty"], oi["stock_batch_id"]),
                )

            cur.execute(
                "DELETE FROM debit_note_items WHERE debit_note_id = ?",
                (dn_id,),
            )
            cur.execute(
                """
                UPDATE debit_notes SET
                    voucher_date = ?, voucher_time = ?, dn_date = ?,
                    dn_type = ?, supplier_id = ?, total_amount = ?,
                    ledger_amount = ?, remarks = ?
                WHERE id = ?
                """,
                (
                    header["voucher_date"],
                    header.get("voucher_time", ""),
                    header.get("dn_date", ""),
                    header.get("dn_type", "Supplier"),
                    header["supplier_id"],
                    header.get("total_amount", 0.0),
                    header.get("ledger_amount", 0.0),
                    header.get("remarks", ""),
                    dn_id,
                ),
            )
            for item in items:
                # Validate stock before deducting
                cur.execute(
                    "SELECT stock_qty FROM stock_batches WHERE id = ?",
                    (item["stock_batch_id"],),
                )
                batch = cur.fetchone()
                if batch is None:
                    raise ValueError(f"Stock batch {item['stock_batch_id']} not found")
                available = batch["stock_qty"]
                return_qty = item.get("return_qty", 0)
                if return_qty <= 0:
                    raise ValueError("Return quantity must be greater than 0")
                if return_qty > available:
                    raise ValueError(
                        f"Insufficient stock: batch has {available:.0f}, "
                        f"cannot return {return_qty:.0f}"
                    )

                cur.execute(
                    """
                    INSERT INTO debit_note_items
                        (debit_note_id, item_id, stock_batch_id, batch_no,
                         expiry, pack_size, rate, mrp, return_qty,
                         less_amount, amount, return_reason, price_factor)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        dn_id,
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
                # Re-apply stock deduction
                cur.execute(
                    "UPDATE stock_batches SET stock_qty = stock_qty - ? WHERE id = ?",
                    (item.get("return_qty", 0), item["stock_batch_id"]),
                )

            # Post new accounting effect inside THIS transaction
            posting_engine.post_debit_note(dn_id, cur=cur)

            conn.commit()
            return True
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def delete_debit_note(dn_id: int) -> bool:
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("BEGIN")

            # Reverse the accounting posting inside THIS transaction
            posting_engine.reverse(SOURCE_DEBIT_NOTE, dn_id, cur=cur)

            # Restore stock
            items = cur.execute(
                "SELECT stock_batch_id, return_qty FROM debit_note_items WHERE debit_note_id = ?",
                (dn_id,),
            ).fetchall()
            for it in items:
                cur.execute(
                    "UPDATE stock_batches SET stock_qty = stock_qty + ? WHERE id = ?",
                    (it["return_qty"], it["stock_batch_id"]),
                )
            cur.execute(
                "DELETE FROM debit_note_items WHERE debit_note_id = ?",
                (dn_id,),
            )
            cur.execute("DELETE FROM debit_notes WHERE id = ?", (dn_id,))
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
