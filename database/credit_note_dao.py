from __future__ import annotations

import sqlite3
from typing import Optional, List

from database.connection import get_connection
from database.accounting_posting import (
    SOURCE_CREDIT_NOTE,
    posting_engine,
)
from database.sales_dao import SalesDAO


class CreditNoteDAO:

    # ── helpers ────────────────────────────────────────────────────────
    @staticmethod
    def generate_next_voucher_no(conn: sqlite3.Connection | None = None) -> str:
        should_close = False
        if conn is None:
            conn = get_connection()
            should_close = True
        try:
            from database import financial_year
            fy = financial_year.get_active_financial_year()
            fy_name = fy["name"] if fy else None

            if fy_name:
                prefix = f"{fy_name}-CreditNote-"
                cur = conn.execute(
                    "SELECT voucher_no FROM credit_notes WHERE voucher_no LIKE ? ORDER BY id DESC",
                    (f"{prefix}%",),
                )
                rows = cur.fetchall()
                max_num = 0
                for r in rows:
                    vno = r["voucher_no"]
                    tail = vno.rsplit("-", 1)[-1].strip()
                    if "#" in tail:
                        tail = tail.split("#")[0]
                    if tail.isdigit():
                        max_num = max(max_num, int(tail))
                if max_num > 0:
                    return f"{prefix}{max_num + 1}"
                return f"{prefix}1"

            # Fallback when no active financial year is configured
            cur = conn.execute(
                "SELECT voucher_no FROM credit_notes ORDER BY id DESC"
            )
            rows = cur.fetchall()
            max_num = 0
            for r in rows:
                vno = r["voucher_no"]
                tail = vno.rsplit("-", 1)[-1].strip()
                if tail.isdigit():
                    max_num = max(max_num, int(tail))
            if max_num > 0:
                return f"CN-{max_num + 1:04d}"
            return "CN-0001"
        finally:
            if should_close:
                conn.close()

    # ── read ───────────────────────────────────────────────────────────
    @staticmethod
    def get_all() -> List[dict]:
        conn = get_connection()
        try:
            rows = conn.execute(
                """
                SELECT c.id, c.voucher_no, c.voucher_date, c.voucher_time,
                       c.cn_date, c.cn_type, c.customer_id,
                       cu.customer_name AS customer_name,
                       c.total_amount, c.ledger_amount, c.remarks,
                       COALESCE(c.added_to_ledger, 'N') AS added_to_ledger
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
                       c.total_amount, c.ledger_amount, c.remarks,
                       COALESCE(c.added_to_ledger, 'N') AS added_to_ledger
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
    def get_items(cn_id: int) -> List[dict]:
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
                ORDER BY ci.id ASC
                """,
                (cn_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    get_invoice_items = get_items

    @staticmethod
    def get_all_filtered(
        voucher_from: str = "",
        voucher_to: str = "",
        party: str = "",
        voucher_no: str = "",
        customer_id: int | None = None,
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
            if customer_id:
                clauses.append("c.customer_id = ?")
                params.append(customer_id)
            where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
            sql = f"""
                SELECT c.id, c.voucher_no, c.voucher_date, c.voucher_time,
                       c.cn_date, c.cn_type, c.customer_id,
                       cu.customer_name AS customer_name,
                       c.total_amount, c.ledger_amount, c.remarks,
                       COALESCE(c.added_to_ledger, 'N') AS added_to_ledger
                FROM credit_notes c
                LEFT JOIN customers cu ON cu.id = c.customer_id
                {where}
                ORDER BY c.id DESC
            """
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    @staticmethod
    def get_batches_for_customer_item(
        customer_id: int | None, item_id: int
    ) -> list[dict]:
        """Fetch stock batches for an item, annotated with whether purchased/sold."""
        conn = get_connection()
        try:
            cur = conn.execute(
                """
                SELECT sb.id, sb.item_id, sb.batch_no, sb.expiry,
                       sb.pack_size, sb.mrp, sb.purchase_rate, sb.net_rate,
                       sb.stock_qty
                FROM stock_batches sb
                WHERE sb.item_id = ?
                ORDER BY sb.expiry ASC, sb.id ASC
                """,
                (item_id,),
            )
            rows = [dict(r) for r in cur.fetchall()]
            for b in rows:
                b["is_expired"] = SalesDAO.is_expired(b.get("expiry") or "")
            return rows
        finally:
            conn.close()

    # ── write (single transaction) ─────────────────────────────────────
    @staticmethod
    def insert_credit_note(header: dict, items: list[dict]) -> int:
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("BEGIN")

            voucher_no = header.get("voucher_no")
            if not voucher_no:
                voucher_no = CreditNoteDAO.generate_next_voucher_no(conn)

            if "add_to_ledger" in header:
                add_to_ledger = bool(header["add_to_ledger"])
            elif "added_to_ledger" in header:
                add_to_ledger = header["added_to_ledger"] in ("Y", True, 1)
            else:
                add_to_ledger = float(header.get("ledger_amount", 0.0)) > 0

            added_to_ledger = "Y" if add_to_ledger else "N"
            total_amount = round(float(header.get("total_amount", 0.0)), 2)
            ledger_amount = total_amount if add_to_ledger else 0.0

            cur.execute(
                """
                INSERT INTO credit_notes
                    (voucher_no, voucher_date, voucher_time, cn_date, cn_type,
                     customer_id, total_amount, ledger_amount, remarks, added_to_ledger)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    voucher_no,
                    header["voucher_date"],
                    header.get("voucher_time", ""),
                    header.get("cn_date", ""),
                    header.get("cn_type", "Customer"),
                    header["customer_id"],
                    total_amount,
                    ledger_amount,
                    header.get("remarks", ""),
                    added_to_ledger,
                ),
            )
            cn_id = cur.lastrowid

            for item in items:
                stock_batch_id = item["stock_batch_id"]
                ret_qty = float(item.get("return_qty", 0.0))
                if ret_qty < 0:
                    raise ValueError("Return quantity cannot be negative")

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
                        stock_batch_id,
                        item["batch_no"],
                        item.get("expiry", ""),
                        item.get("pack_size", ""),
                        float(item.get("rate", 0.0)),
                        float(item.get("mrp", 0.0)),
                        ret_qty,
                        float(item.get("less_amount", 0.0)),
                        round(float(item.get("amount", 0.0)), 2),
                        item.get("return_reason", "Sales Return"),
                        float(item.get("price_factor", 1.0)),
                    ),
                )

                # Inventory safety: Do NOT restore expired or damaged items to saleable stock
                is_expired = SalesDAO.is_expired(item.get("expiry") or "")
                reason = (item.get("return_reason") or "").strip()
                is_unsellable = (
                    bool(item.get("unsellable"))
                    or reason in ("Breakage/Damage", "Expiry Return", "Quarantine")
                    or is_expired
                )

                if ret_qty > 0 and not is_unsellable:
                    # Credit note RESTORES stock (opposite of sale) in loose units
                    cur.execute(
                        """
                        UPDATE stock_batches
                        SET stock_qty = stock_qty + ?
                        WHERE id = ?
                        """,
                        (ret_qty, stock_batch_id),
                    )

            # Accounting posting joins THIS transaction only if requested
            if add_to_ledger:
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

            # Reverse old stock increases (only for lines that were actually restored)
            old_items = cur.execute(
                """
                SELECT stock_batch_id, return_qty, expiry, return_reason
                FROM credit_note_items WHERE credit_note_id = ?
                """,
                (cn_id,),
            ).fetchall()
            for oi in old_items:
                is_exp = SalesDAO.is_expired(oi["expiry"] or "")
                reason_lower = (oi["return_reason"] or "").lower()
                is_dmg = any(
                    w in reason_lower
                    for w in ["damage", "breakage", "defect", "expired", "waste"]
                )
                if not (is_exp or is_dmg):
                    cur.execute(
                        "UPDATE stock_batches SET stock_qty = stock_qty - ? WHERE id = ?",
                        (oi["return_qty"], oi["stock_batch_id"]),
                    )

            cur.execute(
                "DELETE FROM credit_note_items WHERE credit_note_id = ?",
                (cn_id,),
            )

            if "add_to_ledger" in header:
                add_to_ledger = bool(header["add_to_ledger"])
            elif "added_to_ledger" in header:
                add_to_ledger = header["added_to_ledger"] in ("Y", True, 1)
            else:
                add_to_ledger = float(header.get("ledger_amount", 0.0)) > 0

            added_to_ledger = "Y" if add_to_ledger else "N"
            total_amount = round(float(header.get("total_amount", 0.0)), 2)
            ledger_amount = total_amount if add_to_ledger else 0.0

            cur.execute(
                """
                UPDATE credit_notes SET
                    voucher_date = ?, voucher_time = ?, cn_date = ?,
                    cn_type = ?, customer_id = ?, total_amount = ?,
                    ledger_amount = ?, remarks = ?, added_to_ledger = ?
                WHERE id = ?
                """,
                (
                    header["voucher_date"],
                    header.get("voucher_time", ""),
                    header.get("cn_date", ""),
                    header.get("cn_type", "Customer"),
                    header["customer_id"],
                    total_amount,
                    ledger_amount,
                    header.get("remarks", ""),
                    added_to_ledger,
                    cn_id,
                ),
            )

            for item in items:
                stock_batch_id = item["stock_batch_id"]
                ret_qty = float(item.get("return_qty", 0.0))
                if ret_qty < 0:
                    raise ValueError("Return quantity cannot be negative")

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
                        stock_batch_id,
                        item["batch_no"],
                        item.get("expiry", ""),
                        item.get("pack_size", ""),
                        float(item.get("rate", 0.0)),
                        float(item.get("mrp", 0.0)),
                        ret_qty,
                        float(item.get("less_amount", 0.0)),
                        round(float(item.get("amount", 0.0)), 2),
                        item.get("return_reason", "Sales Return"),
                        float(item.get("price_factor", 1.0)),
                    ),
                )

                # Re-apply stock increase if not expired/damaged
                is_expired = SalesDAO.is_expired(item.get("expiry") or "")
                reason_lower = (item.get("return_reason") or "").lower()
                is_damaged = any(
                    w in reason_lower
                    for w in ["damage", "breakage", "defect", "expired", "waste"]
                )
                if ret_qty > 0 and not (is_expired or is_damaged):
                    cur.execute(
                        "UPDATE stock_batches SET stock_qty = stock_qty + ? WHERE id = ?",
                        (ret_qty, stock_batch_id),
                    )

            # Post new accounting effect only if requested
            if add_to_ledger:
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

            # Reverse stock increases (deduct stock) for saleable items
            items = cur.execute(
                """
                SELECT stock_batch_id, return_qty, expiry, return_reason
                FROM credit_note_items WHERE credit_note_id = ?
                """,
                (cn_id,),
            ).fetchall()
            for it in items:
                is_exp = SalesDAO.is_expired(it["expiry"] or "")
                reason = (it["return_reason"] or "").strip()
                is_unsellable = (
                    reason in ("Breakage/Damage", "Expiry Return", "Quarantine")
                    or is_exp
                )
                if not is_unsellable:
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
