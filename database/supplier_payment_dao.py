from __future__ import annotations

import sqlite3
from typing import Optional, List

from database.connection import get_connection
from database.accounting_posting import (
    SOURCE_SUPPLIER_PAYMENT,
    posting_engine,
)


class SupplierPaymentDAO:

    # ── helpers ────────────────────────────────────────────────────────
    @staticmethod
    def generate_next_voucher_no(conn: sqlite3.Connection) -> str:
        cur = conn.execute(
            "SELECT voucher_no FROM supplier_payments ORDER BY id DESC LIMIT 1"
        )
        row = cur.fetchone()
        if row is None:
            return "SP-0001"
        last_num = int(row[0].split("-")[1])
        return f"SP-{last_num + 1:04d}"

    # ── read ───────────────────────────────────────────────────────────
    @staticmethod
    def get_all() -> List[dict]:
        conn = get_connection()
        try:
            rows = conn.execute(
                """
                SELECT sp.id, sp.voucher_no, sp.payment_date, sp.payment_time,
                       sp.supplier_id, s.supplier_name,
                       sp.payment_mode, sp.amount, sp.reference_no, sp.remarks
                FROM supplier_payments sp
                LEFT JOIN suppliers s ON s.id = sp.supplier_id
                ORDER BY sp.id DESC
                """
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    @staticmethod
    def get_by_id(payment_id: int) -> Optional[dict]:
        conn = get_connection()
        try:
            cur = conn.execute(
                """
                SELECT sp.id, sp.voucher_no, sp.payment_date, sp.payment_time,
                       sp.supplier_id, s.supplier_name,
                       sp.payment_mode, sp.amount, sp.reference_no, sp.remarks
                FROM supplier_payments sp
                LEFT JOIN suppliers s ON s.id = sp.supplier_id
                WHERE sp.id = ?
                """,
                (payment_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    @staticmethod
    def get_all_filtered(
        date_from: str = "",
        date_to: str = "",
        supplier_id: Optional[int] = None,
    ) -> List[dict]:
        conn = get_connection()
        try:
            clauses: list[str] = []
            params: list = []
            if date_from:
                clauses.append("sp.payment_date >= ?")
                params.append(date_from)
            if date_to:
                clauses.append("sp.payment_date <= ?")
                params.append(date_to)
            if supplier_id is not None:
                clauses.append("sp.supplier_id = ?")
                params.append(supplier_id)
            where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
            sql = f"""
                SELECT sp.id, sp.voucher_no, sp.payment_date, sp.payment_time,
                       sp.supplier_id, s.supplier_name,
                       sp.payment_mode, sp.amount, sp.reference_no, sp.remarks
                FROM supplier_payments sp
                LEFT JOIN suppliers s ON s.id = sp.supplier_id
                {where}
                ORDER BY sp.id DESC
            """
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    @staticmethod
    def get_supplier_balance(supplier_id: int) -> float:
        """Calculate outstanding balance for a supplier.

        Balance = total purchase net_amount - total debit notes - total payments.
        If data is insufficient, returns 0 (not calculated).

        LEGACY (Phase 2D): this method predates automatic ledger posting and
        is retained for compatibility. The Account Ledger
        (LedgerDAO.get_balance on the supplier's linked ledger) is the
        future authoritative accounting source once all transaction types
        are posted. Do not extend this method — new reporting should read
        from the ledger.
        """
        conn = get_connection()
        try:
            # Total purchases (net_amount owed to supplier)
            cur = conn.execute(
                "SELECT COALESCE(SUM(net_amount), 0) FROM purchase_invoices WHERE supplier_id = ?",
                (supplier_id,),
            )
            total_purchases = cur.fetchone()[0]

            # Total debit notes (returns to supplier, reduce what we owe)
            cur = conn.execute(
                "SELECT COALESCE(SUM(total_amount), 0) FROM debit_notes WHERE supplier_id = ?",
                (supplier_id,),
            )
            total_debit_notes = cur.fetchone()[0]

            # Total payments already made
            cur = conn.execute(
                "SELECT COALESCE(SUM(amount), 0) FROM supplier_payments WHERE supplier_id = ?",
                (supplier_id,),
            )
            total_payments = cur.fetchone()[0]

            balance = total_purchases - total_debit_notes - total_payments
            return round(balance, 2)
        finally:
            conn.close()

    # ── write (single transaction: source + accounting posting) ────────
    @staticmethod
    def insert_payment(header: dict) -> int:
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("BEGIN")

            voucher_no = SupplierPaymentDAO.generate_next_voucher_no(conn)

            cur.execute(
                """
                INSERT INTO supplier_payments
                    (voucher_no, payment_date, payment_time, supplier_id,
                     payment_mode, amount, reference_no, remarks)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    voucher_no,
                    header["payment_date"],
                    header.get("payment_time", ""),
                    header["supplier_id"],
                    header.get("payment_mode", "Cash"),
                    header.get("amount", 0.0),
                    header.get("reference_no", ""),
                    header.get("remarks", ""),
                ),
            )
            payment_id = cur.lastrowid

            # Accounting posting joins THIS transaction (atomic with save).
            posting_engine.post_supplier_payment(payment_id, cur=cur)

            conn.commit()
            return payment_id
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def update_payment(payment_id: int, header: dict) -> bool:
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("BEGIN")

            cur.execute(
                """
                UPDATE supplier_payments SET
                    payment_date = ?, payment_time = ?, supplier_id = ?,
                    payment_mode = ?, amount = ?, reference_no = ?, remarks = ?
                WHERE id = ?
                """,
                (
                    header["payment_date"],
                    header.get("payment_time", ""),
                    header["supplier_id"],
                    header.get("payment_mode", "Cash"),
                    header.get("amount", 0.0),
                    header.get("reference_no", ""),
                    header.get("remarks", ""),
                    payment_id,
                ),
            )

            # Re-post inside THIS transaction: reverse previous posting,
            # post the updated payment. Atomic with the edit.
            posting_engine.repost_supplier_payment(payment_id, cur=cur)

            conn.commit()
            return True
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def delete_payment(payment_id: int) -> bool:
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("BEGIN")

            # Reverse the accounting posting inside THIS transaction, so
            # no active accounting effect survives the deletion.
            posting_engine.reverse(SOURCE_SUPPLIER_PAYMENT, payment_id, cur=cur)

            cur.execute("DELETE FROM supplier_payments WHERE id = ?", (payment_id,))

            conn.commit()
            return True
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
