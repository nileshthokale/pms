from __future__ import annotations

import sqlite3
from typing import Optional, List

from database.connection import get_connection
from database.accounting_posting import (
    SOURCE_CUSTOMER_RECEIPT,
    posting_engine,
)


class CustomerReceiptDAO:

    # ── helpers ────────────────────────────────────────────────────────
    @staticmethod
    def generate_next_voucher_no(conn: sqlite3.Connection) -> str:
        cur = conn.execute(
            "SELECT voucher_no FROM customer_receipts ORDER BY id DESC LIMIT 1"
        )
        row = cur.fetchone()
        if row is None:
            return "CR-0001"
        last_num = int(row[0].split("-")[1])
        return f"CR-{last_num + 1:04d}"

    # ── read ───────────────────────────────────────────────────────────
    @staticmethod
    def get_all() -> List[dict]:
        conn = get_connection()
        try:
            rows = conn.execute(
                """
                SELECT cr.id, cr.voucher_no, cr.receipt_date, cr.receipt_time,
                       cr.customer_id, c.customer_name,
                       cr.receipt_mode, cr.amount, cr.reference_no, cr.remarks
                FROM customer_receipts cr
                LEFT JOIN customers c ON c.id = cr.customer_id
                ORDER BY cr.id DESC
                """
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    @staticmethod
    def get_by_id(receipt_id: int) -> Optional[dict]:
        conn = get_connection()
        try:
            cur = conn.execute(
                """
                SELECT cr.id, cr.voucher_no, cr.receipt_date, cr.receipt_time,
                       cr.customer_id, c.customer_name,
                       cr.receipt_mode, cr.amount, cr.reference_no, cr.remarks
                FROM customer_receipts cr
                LEFT JOIN customers c ON c.id = cr.customer_id
                WHERE cr.id = ?
                """,
                (receipt_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    @staticmethod
    def get_all_filtered(
        date_from: str = "",
        date_to: str = "",
        customer_id: Optional[int] = None,
    ) -> List[dict]:
        conn = get_connection()
        try:
            clauses: list[str] = []
            params: list = []
            if date_from:
                clauses.append("cr.receipt_date >= ?")
                params.append(date_from)
            if date_to:
                clauses.append("cr.receipt_date <= ?")
                params.append(date_to)
            if customer_id is not None:
                clauses.append("cr.customer_id = ?")
                params.append(customer_id)
            where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
            sql = f"""
                SELECT cr.id, cr.voucher_no, cr.receipt_date, cr.receipt_time,
                       cr.customer_id, c.customer_name,
                       cr.receipt_mode, cr.amount, cr.reference_no, cr.remarks
                FROM customer_receipts cr
                LEFT JOIN customers c ON c.id = cr.customer_id
                {where}
                ORDER BY cr.id DESC
            """
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    @staticmethod
    def get_customer_balance(customer_id: int) -> float:
        """Calculate outstanding balance for a customer.

        Balance = total sales net_amount - total credit notes - total receipts.
        Uses existing project transaction data only.

        LEGACY (Phase 2C): this method predates automatic ledger posting and
        is retained for compatibility. The Account Ledger
        (LedgerDAO.get_balance on the customer's linked ledger) is the
        future authoritative accounting source once all transaction types
        are posted. Do not extend this method — new reporting should read
        from the ledger.
        """
        conn = get_connection()
        try:
            # Total sales (amount owed by customer)
            cur = conn.execute(
                "SELECT COALESCE(SUM(net_amount), 0) FROM sales_invoices WHERE customer_id = ?",
                (customer_id,),
            )
            total_sales = cur.fetchone()[0]

            # Total credit notes (returns from customer, reduce what they owe)
            cur = conn.execute(
                "SELECT COALESCE(SUM(total_amount), 0) FROM credit_notes WHERE customer_id = ?",
                (customer_id,),
            )
            total_credit_notes = cur.fetchone()[0]

            # Total receipts already received
            cur = conn.execute(
                "SELECT COALESCE(SUM(amount), 0) FROM customer_receipts WHERE customer_id = ?",
                (customer_id,),
            )
            total_receipts = cur.fetchone()[0]

            balance = total_sales - total_credit_notes - total_receipts
            return round(balance, 2)
        finally:
            conn.close()

    # ── write (single transaction: source + accounting posting) ────────
    @staticmethod
    def insert_receipt(header: dict) -> int:
        amount = header.get("amount", 0.0)
        if amount <= 0:
            raise ValueError("Amount must be greater than 0.")
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("BEGIN")

            voucher_no = CustomerReceiptDAO.generate_next_voucher_no(conn)

            cur.execute(
                """
                INSERT INTO customer_receipts
                    (voucher_no, receipt_date, receipt_time, customer_id,
                     receipt_mode, amount, reference_no, remarks)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    voucher_no,
                    header["receipt_date"],
                    header.get("receipt_time", ""),
                    header["customer_id"],
                    header.get("receipt_mode", "Cash"),
                    header.get("amount", 0.0),
                    header.get("reference_no", ""),
                    header.get("remarks", ""),
                ),
            )
            receipt_id = cur.lastrowid

            # Accounting posting joins THIS transaction (atomic with save).
            posting_engine.post_customer_receipt(receipt_id, cur=cur)

            conn.commit()
            return receipt_id
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def update_receipt(receipt_id: int, header: dict) -> bool:
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("BEGIN")

            cur.execute(
                """
                UPDATE customer_receipts SET
                    receipt_date = ?, receipt_time = ?, customer_id = ?,
                    receipt_mode = ?, amount = ?, reference_no = ?, remarks = ?
                WHERE id = ?
                """,
                (
                    header["receipt_date"],
                    header.get("receipt_time", ""),
                    header["customer_id"],
                    header.get("receipt_mode", "Cash"),
                    header.get("amount", 0.0),
                    header.get("reference_no", ""),
                    header.get("remarks", ""),
                    receipt_id,
                ),
            )

            # Re-post inside THIS transaction: reverse previous posting,
            # post the updated receipt. Atomic with the edit.
            posting_engine.repost_customer_receipt(receipt_id, cur=cur)

            conn.commit()
            return True
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def delete_receipt(receipt_id: int) -> bool:
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("BEGIN")

            # Reverse the accounting posting inside THIS transaction, so
            # no active accounting effect survives the deletion.
            posting_engine.reverse(SOURCE_CUSTOMER_RECEIPT, receipt_id, cur=cur)

            cur.execute("DELETE FROM customer_receipts WHERE id = ?", (receipt_id,))

            conn.commit()
            return True
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
