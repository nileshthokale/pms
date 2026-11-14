from __future__ import annotations

import sqlite3
from typing import Optional, List

from database.connection import get_connection
from database.accounting_posting import (
    SOURCE_DEBIT_NOTE,
    posting_engine,
)
from database.purchase_dao import pack_factor
from database.sales_dao import SalesDAO


class DebitNoteDAO:

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
                prefix = f"{fy_name}-DebitNote-"
                cur = conn.execute(
                    "SELECT voucher_no FROM debit_notes WHERE voucher_no LIKE ? ORDER BY id DESC",
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
                "SELECT voucher_no FROM debit_notes ORDER BY id DESC"
            )
            rows = cur.fetchall()
            max_num = 0
            for r in rows:
                vno = r["voucher_no"]
                tail = vno.rsplit("-", 1)[-1].strip()
                if tail.isdigit():
                    max_num = max(max_num, int(tail))
            if max_num > 0:
                return f"DN-{max_num + 1:04d}"
            return "DN-0001"
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
                SELECT d.id, d.voucher_no, d.voucher_date, d.voucher_time,
                       d.dn_date, d.dn_type, d.supplier_id,
                       s.supplier_name,
                       d.total_amount, d.ledger_amount, d.remarks,
                       COALESCE(d.added_to_ledger, 'N') AS added_to_ledger,
                       COALESCE(d.settled_amount, 0.0) AS settled_amount,
                       COALESCE(d.settlement_status, 'UNSETTLED') AS settlement_status
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
                       d.total_amount, d.ledger_amount, d.remarks,
                       COALESCE(d.added_to_ledger, 'N') AS added_to_ledger,
                       COALESCE(d.settled_amount, 0.0) AS settled_amount,
                       COALESCE(d.settlement_status, 'UNSETTLED') AS settlement_status
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
                       di.return_qty, COALESCE(di.free_qty, 0.0) AS free_qty,
                       di.less_amount, di.amount,
                       di.return_reason, di.price_factor,
                       COALESCE(di.is_pack_qty, 0) AS is_pack_qty
                FROM debit_note_items di
                LEFT JOIN items i ON i.id = di.item_id
                WHERE di.debit_note_id = ?
                ORDER BY di.id ASC
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
        supplier_id: int | None = None,
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
            if supplier_id:
                clauses.append("d.supplier_id = ?")
                params.append(supplier_id)
            where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
            sql = f"""
                SELECT d.id, d.voucher_no, d.voucher_date, d.voucher_time,
                       d.dn_date, d.dn_type, d.supplier_id,
                       s.supplier_name,
                       d.total_amount, d.ledger_amount, d.remarks,
                       COALESCE(d.added_to_ledger, 'N') AS added_to_ledger,
                       COALESCE(d.settled_amount, 0.0) AS settled_amount,
                       COALESCE(d.settlement_status, 'UNSETTLED') AS settlement_status
                FROM debit_notes d
                LEFT JOIN suppliers s ON s.id = d.supplier_id
                {where}
                ORDER BY d.id DESC
            """
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    @staticmethod
    def get_batches_for_supplier_item(
        supplier_id: int | None, item_id: int, expired_only: bool = False
    ) -> list[dict]:
        """Fetch stock batches for an item, optionally filtered by supplier and expiry."""
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

            # Determine which batches were purchased from this supplier
            supplier_batches = set()
            if supplier_id:
                sp_rows = conn.execute(
                    """
                    SELECT DISTINCT pii.batch_no
                    FROM purchase_invoice_items pii
                    JOIN purchase_invoices pi ON pi.id = pii.purchase_invoice_id
                    WHERE pi.supplier_id = ? AND pii.item_id = ?
                    """,
                    (supplier_id, item_id),
                ).fetchall()
                supplier_batches = {r["batch_no"].strip().upper() for r in sp_rows if r["batch_no"]}

            results = []
            for b in rows:
                b_no = (b.get("batch_no") or "").strip().upper()
                is_from_supplier = (b_no in supplier_batches) if supplier_id else True
                b["is_from_supplier"] = is_from_supplier
                b["is_expired"] = SalesDAO.is_expired(b.get("expiry") or "")

                if expired_only and not b["is_expired"]:
                    continue

                results.append(b)

            return results
        finally:
            conn.close()

    # ── write (single transaction) ─────────────────────────────────────
    @staticmethod
    def insert_debit_note(header: dict, items: list[dict]) -> int:
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("BEGIN")

            voucher_no = header.get("voucher_no")
            if not voucher_no:
                voucher_no = DebitNoteDAO.generate_next_voucher_no(conn)

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
                INSERT INTO debit_notes
                    (voucher_no, voucher_date, voucher_time, dn_date, dn_type,
                     supplier_id, total_amount, ledger_amount, remarks, added_to_ledger)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    voucher_no,
                    header["voucher_date"],
                    header.get("voucher_time", ""),
                    header.get("dn_date", ""),
                    header.get("dn_type", "Supplier"),
                    header["supplier_id"],
                    total_amount,
                    ledger_amount,
                    header.get("remarks", ""),
                    added_to_ledger,
                ),
            )
            dn_id = cur.lastrowid

            for item in items:
                stock_batch_id = item["stock_batch_id"]
                cur.execute(
                    "SELECT id, stock_qty, pack_size FROM stock_batches WHERE id = ?",
                    (stock_batch_id,),
                )
                batch = cur.fetchone()
                if batch is None:
                    raise ValueError(f"Stock batch {stock_batch_id} not found")

                pack_sz = item.get("pack_size") or batch["pack_size"] or "1"
                p_factor = pack_factor(pack_sz)
                is_pack = bool(item.get("is_pack_qty", False))
                ret_qty = float(item.get("return_qty", 0.0))
                free_qty = float(item.get("free_qty", 0.0))

                if ret_qty < 0 or free_qty < 0:
                    raise ValueError("Return quantity cannot be negative")
                if (ret_qty + free_qty) <= 0:
                    raise ValueError("Return quantity must be greater than 0")

                available = float(batch["stock_qty"])
                pack_loose = (ret_qty + free_qty) * p_factor
                direct_loose = (ret_qty + free_qty)
                loose_deduction = pack_loose if is_pack else direct_loose

                if loose_deduction > available or pack_loose > available:
                    raise ValueError(
                        f"Insufficient stock: batch has {available:.0f}, "
                        f"cannot return {max(loose_deduction, pack_loose):.0f}"
                    )

                cur.execute(
                    """
                    INSERT INTO debit_note_items
                        (debit_note_id, item_id, stock_batch_id, batch_no,
                         expiry, pack_size, rate, mrp, return_qty, free_qty,
                         less_amount, amount, return_reason, price_factor, is_pack_qty)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        dn_id,
                        item["item_id"],
                        stock_batch_id,
                        item["batch_no"],
                        item.get("expiry", ""),
                        pack_sz,
                        float(item.get("rate", 0.0)),
                        float(item.get("mrp", 0.0)),
                        ret_qty,
                        free_qty,
                        float(item.get("less_amount", 0.0)),
                        round(float(item.get("amount", 0.0)), 2),
                        item.get("return_reason", "Purchase Return"),
                        float(item.get("price_factor", 1.0)),
                        1 if is_pack else 0,
                    ),
                )

                # Debit note DECREASES stock (goods returned to supplier)
                cur.execute(
                    """
                    UPDATE stock_batches
                    SET stock_qty = stock_qty - ?
                    WHERE id = ?
                    """,
                    (loose_deduction, stock_batch_id),
                )

            # Accounting posting joins THIS transaction only if requested
            if add_to_ledger:
                posting_engine.post_debit_note(dn_id, cur=cur)

            conn.commit()
            return dn_id
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    create_debit_note = insert_debit_note

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
                """
                SELECT stock_batch_id, return_qty, COALESCE(free_qty, 0.0) AS free_qty,
                       pack_size, COALESCE(is_pack_qty, 0) AS is_pack_qty
                FROM debit_note_items WHERE debit_note_id = ?
                """,
                (dn_id,),
            ).fetchall()
            for oi in old_items:
                factor = pack_factor(oi["pack_size"]) if oi["is_pack_qty"] else 1.0
                restore_loose = (float(oi["return_qty"]) + float(oi["free_qty"])) * factor
                cur.execute(
                    "UPDATE stock_batches SET stock_qty = stock_qty + ? WHERE id = ?",
                    (restore_loose, oi["stock_batch_id"]),
                )

            cur.execute(
                "DELETE FROM debit_note_items WHERE debit_note_id = ?",
                (dn_id,),
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
                UPDATE debit_notes SET
                    voucher_date = ?, voucher_time = ?, dn_date = ?,
                    dn_type = ?, supplier_id = ?, total_amount = ?,
                    ledger_amount = ?, remarks = ?, added_to_ledger = ?
                WHERE id = ?
                """,
                (
                    header["voucher_date"],
                    header.get("voucher_time", ""),
                    header.get("dn_date", ""),
                    header.get("dn_type", "Supplier"),
                    header["supplier_id"],
                    total_amount,
                    ledger_amount,
                    header.get("remarks", ""),
                    added_to_ledger,
                    dn_id,
                ),
            )

            for item in items:
                stock_batch_id = item["stock_batch_id"]
                cur.execute(
                    "SELECT id, stock_qty, pack_size FROM stock_batches WHERE id = ?",
                    (stock_batch_id,),
                )
                batch = cur.fetchone()
                if batch is None:
                    raise ValueError(f"Stock batch {stock_batch_id} not found")

                pack_sz = item.get("pack_size") or batch["pack_size"] or "1"
                p_factor = pack_factor(pack_sz)
                is_pack = bool(item.get("is_pack_qty", False))
                ret_qty = float(item.get("return_qty", 0.0))
                free_qty = float(item.get("free_qty", 0.0))

                if ret_qty < 0 or free_qty < 0:
                    raise ValueError("Return quantity cannot be negative")
                if (ret_qty + free_qty) <= 0:
                    raise ValueError("Return quantity must be greater than 0")

                available = float(batch["stock_qty"])
                pack_loose = (ret_qty + free_qty) * p_factor
                direct_loose = (ret_qty + free_qty)
                loose_deduction = pack_loose if is_pack else direct_loose

                if loose_deduction > available or pack_loose > available:
                    raise ValueError(
                        f"Insufficient stock: batch has {available:.0f}, "
                        f"cannot return {max(loose_deduction, pack_loose):.0f}"
                    )

                cur.execute(
                    """
                    INSERT INTO debit_note_items
                        (debit_note_id, item_id, stock_batch_id, batch_no,
                         expiry, pack_size, rate, mrp, return_qty, free_qty,
                         less_amount, amount, return_reason, price_factor, is_pack_qty)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        dn_id,
                        item["item_id"],
                        stock_batch_id,
                        item["batch_no"],
                        item.get("expiry", ""),
                        pack_sz,
                        float(item.get("rate", 0.0)),
                        float(item.get("mrp", 0.0)),
                        ret_qty,
                        free_qty,
                        float(item.get("less_amount", 0.0)),
                        round(float(item.get("amount", 0.0)), 2),
                        item.get("return_reason", "Purchase Return"),
                        float(item.get("price_factor", 1.0)),
                        1 if is_pack else 0,
                    ),
                )

                # Re-apply stock deduction
                cur.execute(
                    "UPDATE stock_batches SET stock_qty = stock_qty - ? WHERE id = ?",
                    (loose_deduction, stock_batch_id),
                )

            # Post new accounting effect only if requested
            if add_to_ledger:
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
                """
                SELECT stock_batch_id, return_qty, COALESCE(free_qty, 0.0) AS free_qty,
                       pack_size, COALESCE(is_pack_qty, 0) AS is_pack_qty
                FROM debit_note_items WHERE debit_note_id = ?
                """,
                (dn_id,),
            ).fetchall()
            for it in items:
                factor = pack_factor(it["pack_size"]) if it["is_pack_qty"] else 1.0
                restore_loose = (float(it["return_qty"]) + float(it["free_qty"])) * factor
                cur.execute(
                    "UPDATE stock_batches SET stock_qty = stock_qty + ? WHERE id = ?",
                    (restore_loose, it["stock_batch_id"]),
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

    # ── settlements & adjustments ──────────────────────────────────────
    @staticmethod
    def get_unsettled_by_supplier(
        supplier_id: int | None = None,
        supplier_name: str | None = None,
    ) -> list[dict]:
        """Fetch unsettled or partially settled debit notes for a supplier.

        Excludes notes already posted to ledger (added_to_ledger='Y'), since those
        are credited to the supplier's balance directly.
        """
        conn = get_connection()
        try:
            clauses = [
                "(d.total_amount - COALESCE(d.settled_amount, 0.0)) > 0.001",
                "COALESCE(d.added_to_ledger, 'N') != 'Y'",
            ]
            params: list = []
            if supplier_id:
                clauses.append("d.supplier_id = ?")
                params.append(supplier_id)
            elif supplier_name:
                clauses.append("s.supplier_name LIKE ?")
                params.append(f"%{supplier_name.strip()}%")

            where = "WHERE " + " AND ".join(clauses)
            sql = f"""
                SELECT d.id, d.voucher_no, d.voucher_date, d.voucher_time,
                       d.total_amount,
                       COALESCE(d.settled_amount, 0.0) AS settled_amount,
                       ROUND(d.total_amount - COALESCE(d.settled_amount, 0.0), 2) AS unsettled_amount,
                       COALESCE(d.settlement_status, 'UNSETTLED') AS settlement_status,
                       s.supplier_name
                FROM debit_notes d
                LEFT JOIN suppliers s ON s.id = d.supplier_id
                {where}
                ORDER BY d.id ASC
            """
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    @staticmethod
    def settle_debit_notes(
        settlements: list[dict],
        purchase_invoice_id: int,
        cur: sqlite3.Cursor | None = None,
        settlement_date: str = "",
        settlement_time: str = "",
    ) -> None:
        """Apply debit note settlements against a purchase invoice atomically."""
        should_commit = False
        conn = None
        if cur is None:
            conn = get_connection()
            cur = conn.cursor()
            cur.execute("BEGIN")
            should_commit = True

        try:
            for s in settlements:
                dn_id = s.get("debit_note_id") or s.get("id")
                debit_amt = round(float(s.get("debit_amount", 0.0) or s.get("settled_amount", 0.0)), 2)
                disc_amt = round(float(s.get("discount_amount", 0.0)), 2)
                if debit_amt <= 0:
                    continue

                # 1. Insert settlement row
                cur.execute(
                    """
                    INSERT INTO debit_note_settlements (
                        debit_note_id, purchase_invoice_id,
                        settled_amount, discount_amount,
                        settlement_date, settlement_time
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (dn_id, purchase_invoice_id, debit_amt, disc_amt, settlement_date, settlement_time),
                )

                # 2. Update debit note settled balance and status
                cur.execute(
                    """
                    UPDATE debit_notes
                    SET settled_amount = ROUND(COALESCE(settled_amount, 0.0) + ?, 2),
                        settlement_status = CASE
                            WHEN ROUND(COALESCE(settled_amount, 0.0) + ?, 2) >= total_amount - 0.01
                            THEN 'SETTLED'
                            ELSE 'PARTIAL'
                        END
                    WHERE id = ?
                    """,
                    (debit_amt, debit_amt, dn_id),
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
        purchase_invoice_id: int,
        cur: sqlite3.Cursor | None = None,
    ) -> None:
        """Reverse all debit note settlements linked to a purchase invoice."""
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
                SELECT debit_note_id, settled_amount
                FROM debit_note_settlements
                WHERE purchase_invoice_id = ?
                """,
                (purchase_invoice_id,),
            ).fetchall()

            for r in rows:
                dn_id = r["debit_note_id"]
                s_amt = r["settled_amount"]
                cur.execute(
                    """
                    UPDATE debit_notes
                    SET settled_amount = ROUND(MAX(0.0, COALESCE(settled_amount, 0.0) - ?), 2),
                        settlement_status = CASE
                            WHEN ROUND(MAX(0.0, COALESCE(settled_amount, 0.0) - ?), 2) <= 0.001
                            THEN 'UNSETTLED'
                            ELSE 'PARTIAL'
                        END
                    WHERE id = ?
                    """,
                    (s_amt, s_amt, dn_id),
                )

            cur.execute(
                "DELETE FROM debit_note_settlements WHERE purchase_invoice_id = ?",
                (purchase_invoice_id,),
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
    def get_settlements_for_invoice(purchase_invoice_id: int) -> list[dict]:
        """Fetch all debit note settlements applied to a purchase invoice."""
        conn = get_connection()
        try:
            sql = """
                SELECT dns.id, dns.debit_note_id, dns.purchase_invoice_id,
                       dns.settled_amount, dns.discount_amount,
                       dns.settlement_date, dns.settlement_time,
                       dn.voucher_no, dn.total_amount
                FROM debit_note_settlements dns
                JOIN debit_notes dn ON dn.id = dns.debit_note_id
                WHERE dns.purchase_invoice_id = ?
                ORDER BY dns.id ASC
            """
            rows = conn.execute(sql, (purchase_invoice_id,)).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
