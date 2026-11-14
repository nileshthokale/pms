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
                       COALESCE(c.added_to_ledger, 'N') AS added_to_ledger,
                       COALESCE(c.settled_amount, 0.0) AS settled_amount,
                       COALESCE(c.settlement_status, 'UNSETTLED') AS settlement_status
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
                       COALESCE(c.added_to_ledger, 'N') AS added_to_ledger,
                       COALESCE(c.settled_amount, 0.0) AS settled_amount,
                       COALESCE(c.settlement_status, 'UNSETTLED') AS settlement_status
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
                       COALESCE(c.added_to_ledger, 'N') AS added_to_ledger,
                       COALESCE(c.settled_amount, 0.0) AS settled_amount,
                       COALESCE(c.settlement_status, 'UNSETTLED') AS settlement_status
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
                        float(item["price_factor_num"]) if "price_factor_num" in item and str(item["price_factor_num"]).replace(".", "", 1).isdigit() else (float(item["price_factor"]) if str(item.get("price_factor", "")).replace(".", "", 1).isdigit() else 1.0),
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
                        float(item["price_factor_num"]) if "price_factor_num" in item and str(item["price_factor_num"]).replace(".", "", 1).isdigit() else (float(item["price_factor"]) if str(item.get("price_factor", "")).replace(".", "", 1).isdigit() else 1.0),
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

    # ── settlements & adjustments ──────────────────────────────────────
    @staticmethod
    def get_unsettled_by_customer(
        customer_id: int | None = None,
        customer_name: str | None = None,
    ) -> list[dict]:
        """Fetch unsettled or partially settled credit notes for a customer.

        If customer is Walk-in (or customer_id is None/0), matches walk-in
        records. Excludes notes already posted to ledger, since those are
        already accounted for in the customer's ledger balance.
        """
        conn = get_connection()
        try:
            clauses = [
                "(c.total_amount - COALESCE(c.settled_amount, 0.0)) > 0.001",
                "COALESCE(c.added_to_ledger, 'N') != 'Y'",
            ]
            params: list = []

            is_walkin = False
            if customer_name and customer_name.strip().upper() in ("WALKIN", "WALK-IN", "WALK IN"):
                is_walkin = True

            if customer_id and not is_walkin:
                clauses.append("c.customer_id = ?")
                params.append(customer_id)
            else:
                # Walk-in: match by customer_id or customer name
                clauses.append(
                    "(cu.customer_name LIKE '%WALK%' OR c.customer_id IS NULL OR c.customer_id = 0)"
                )

            where_str = " AND ".join(clauses)
            sql = f"""
                SELECT c.id, c.voucher_no, c.voucher_date, c.voucher_time,
                       c.total_amount,
                       COALESCE(c.settled_amount, 0.0) AS settled_amount,
                       ROUND(c.total_amount - COALESCE(c.settled_amount, 0.0), 2) AS unsettled_amount,
                       COALESCE(c.settlement_status, 'UNSETTLED') AS settlement_status,
                       cu.customer_name
                FROM credit_notes c
                LEFT JOIN customers cu ON cu.id = c.customer_id
                WHERE {where_str}
                ORDER BY c.voucher_date ASC, c.id ASC
            """
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    @staticmethod
    def settle_credit_notes(
        settlements: list[dict],
        sales_invoice_id: int,
        cur: sqlite3.Cursor | None = None,
        settlement_date: str | None = None,
        settlement_time: str | None = None,
    ) -> None:
        """Apply credit note settlements against a sales invoice.

        Can run inside an existing cursor/transaction (from SalesDAO).
        """
        from datetime import datetime
        now = datetime.now()
        s_date = settlement_date or now.strftime("%Y-%m-%d")
        s_time = settlement_time or now.strftime("%H:%M:%S")

        should_commit = False
        conn = None
        if cur is None:
            conn = get_connection()
            cur = conn.cursor()
            cur.execute("BEGIN")
            should_commit = True

        try:
            for s in settlements:
                cn_id = int(s["credit_note_id"])
                credit_amt = round(float(s.get("credit_amount", 0.0)), 2)
                disc_amt = round(float(s.get("discount_amount", 0.0)), 2)

                if credit_amt <= 0:
                    continue

                # 1. Record settlement row
                cur.execute(
                    """
                    INSERT INTO credit_note_settlements
                        (credit_note_id, sales_invoice_id, settled_amount,
                         discount_amount, settlement_date, settlement_time)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (cn_id, sales_invoice_id, credit_amt, disc_amt, s_date, s_time),
                )

                # 2. Update credit note settled balance and status
                cur.execute(
                    """
                    UPDATE credit_notes
                    SET settled_amount = ROUND(COALESCE(settled_amount, 0.0) + ?, 2),
                        settlement_status = CASE
                            WHEN ROUND(COALESCE(settled_amount, 0.0) + ?, 2) >= total_amount - 0.01
                            THEN 'SETTLED'
                            ELSE 'PARTIAL'
                        END
                    WHERE id = ?
                    """,
                    (credit_amt, credit_amt, cn_id),
                )

            if should_commit and conn:
                conn.commit()
        except Exception:
            if should_commit and conn:
                conn.rollback()
            raise
        finally:
            if should_commit and conn:
                conn.close()

    @staticmethod
    def reverse_settlements_for_invoice(
        sales_invoice_id: int,
        cur: sqlite3.Cursor | None = None,
    ) -> None:
        """Reverse all credit note settlements linked to a sales invoice."""
        should_commit = False
        conn = None
        if cur is None:
            conn = get_connection()
            cur = conn.cursor()
            cur.execute("BEGIN")
            should_commit = True

        try:
            rows = cur.execute(
                """
                SELECT credit_note_id, settled_amount
                FROM credit_note_settlements
                WHERE sales_invoice_id = ?
                """,
                (sales_invoice_id,),
            ).fetchall()

            for r in rows:
                cn_id = r["credit_note_id"]
                s_amt = r["settled_amount"]
                cur.execute(
                    """
                    UPDATE credit_notes
                    SET settled_amount = ROUND(MAX(0.0, COALESCE(settled_amount, 0.0) - ?), 2),
                        settlement_status = CASE
                            WHEN ROUND(MAX(0.0, COALESCE(settled_amount, 0.0) - ?), 2) <= 0.001
                            THEN 'UNSETTLED'
                            ELSE 'PARTIAL'
                        END
                    WHERE id = ?
                    """,
                    (s_amt, s_amt, cn_id),
                )

            cur.execute(
                "DELETE FROM credit_note_settlements WHERE sales_invoice_id = ?",
                (sales_invoice_id,),
            )

            if should_commit and conn:
                conn.commit()
        except Exception:
            if should_commit and conn:
                conn.rollback()
            raise
        finally:
            if should_commit and conn:
                conn.close()

    @staticmethod
    def get_settlements_for_invoice(sales_invoice_id: int) -> list[dict]:
        """Fetch all credit note settlements applied to a sales invoice."""
        conn = get_connection()
        try:
            sql = """
                SELECT cns.id, cns.credit_note_id, cns.sales_invoice_id,
                       cns.settled_amount, cns.discount_amount,
                       cns.settlement_date, cns.settlement_time,
                       cn.voucher_no, cn.total_amount
                FROM credit_note_settlements cns
                JOIN credit_notes cn ON cn.id = cns.credit_note_id
                WHERE cns.sales_invoice_id = ?
                ORDER BY cns.id ASC
            """
            rows = conn.execute(sql, (sales_invoice_id,)).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
