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

        Reads from linked ledger (authoritative accounting balance) when available.
        Falls back to transaction calculation if unlinked.
        """
        conn = get_connection()
        try:
            cust = conn.execute(
                "SELECT ledger_id FROM customers WHERE id = ?",
                (customer_id,),
            ).fetchone()
            if cust and cust["ledger_id"]:
                from database.ledger_dao import LedgerDAO
                bal_dict = LedgerDAO.get_balance(cust["ledger_id"])
                cb = round(bal_dict.get("closing_balance", 0.0), 2)
                return -cb if bal_dict.get("closing_balance_type") == "Credit" else cb

            cur = conn.execute(
                "SELECT COALESCE(SUM(net_amount), 0) FROM sales_invoices WHERE customer_id = ?",
                (customer_id,),
            )
            total_sales = cur.fetchone()[0]

            cur = conn.execute(
                "SELECT COALESCE(SUM(total_amount), 0) FROM credit_notes WHERE customer_id = ?",
                (customer_id,),
            )
            total_credit_notes = cur.fetchone()[0]

            cur = conn.execute(
                "SELECT COALESCE(SUM(amount), 0) FROM customer_receipts WHERE customer_id = ?",
                (customer_id,),
            )
            total_receipts = cur.fetchone()[0]

            balance = total_sales - total_credit_notes - total_receipts
            return round(balance, 2)
        finally:
            conn.close()

    # ── sales bill allocations & outstanding balance ──────────────────
    @staticmethod
    def get_outstanding_bills(
        customer_id: int,
        exclude_receipt_id: Optional[int] = None,
    ) -> List[dict]:
        """Fetch all sales bills for customer with remaining unpaid balance.

        Ordered by sale_date ASC, id ASC (FIFO order).

        Legacy handling: customer_receipts imported from Pharma-WINNER may have
        no rows in customer_receipt_allocations even though they were posted to
        the ledger.  To keep the displayed outstanding consistent with the
        authoritative ledger balance we:
          1. Compute per-bill outstanding = net_amount - paid_amount - SUM(allocations).
          2. Compute total_unallocated_receipts = SUM(customer_receipts.amount) - SUM(all_allocations).
          3. Distribute total_unallocated_receipts in FIFO order across
             bills that still show outstanding, reducing each to 0 when
             the unallocated amount covers it.
        This makes Total Outstanding == customer ledger balance (debit balance).
        """
        conn = get_connection()
        try:
            sql = """
                SELECT si.id, si.bill_no, si.sale_date, si.sale_time,
                       si.sale_type, si.net_amount, si.paid_amount,
                       COALESCE((
                           SELECT SUM(cra.allocated_amount)
                           FROM customer_receipt_allocations cra
                           WHERE cra.sales_invoice_id = si.id
                             AND (cra.customer_receipt_id != ? OR ? IS NULL)
                       ), 0.0) AS prior_allocated
                FROM sales_invoices si
                WHERE si.customer_id = ?
                ORDER BY si.sale_date ASC, si.id ASC
            """
            cur = conn.execute(sql, (exclude_receipt_id, exclude_receipt_id, customer_id))
            rows = cur.fetchall()

            # ------------------------------------------------------------------
            # Compute total unallocated receipt amount for this customer.
            # Receipts posted to the ledger but without allocation table rows
            # (legacy imports) still reduce the outstanding balance.  We must
            # distribute their sum in FIFO order so the total outstanding shown
            # in the dialog matches the authoritative customer ledger balance.
            # ------------------------------------------------------------------
            if exclude_receipt_id is not None:
                total_receipts = float(conn.execute(
                    "SELECT COALESCE(SUM(amount), 0.0) FROM customer_receipts "
                    "WHERE customer_id = ? AND id != ?",
                    (customer_id, exclude_receipt_id),
                ).fetchone()[0] or 0.0)
                total_allocated_in_table = float(conn.execute(
                    """SELECT COALESCE(SUM(cra.allocated_amount), 0.0)
                       FROM customer_receipt_allocations cra
                       JOIN customer_receipts cr ON cr.id = cra.customer_receipt_id
                       WHERE cr.customer_id = ? AND cr.id != ?""",
                    (customer_id, exclude_receipt_id),
                ).fetchone()[0] or 0.0)
            else:
                total_receipts = float(conn.execute(
                    "SELECT COALESCE(SUM(amount), 0.0) FROM customer_receipts WHERE customer_id = ?",
                    (customer_id,),
                ).fetchone()[0] or 0.0)
                total_allocated_in_table = float(conn.execute(
                    """SELECT COALESCE(SUM(cra.allocated_amount), 0.0)
                       FROM customer_receipt_allocations cra
                       JOIN customer_receipts cr ON cr.id = cra.customer_receipt_id
                       WHERE cr.customer_id = ?""",
                    (customer_id,),
                ).fetchone()[0] or 0.0)

            # Unallocated = receipts posted to ledger with no matching allocation rows
            unallocated_pool = round(max(0.0, total_receipts - total_allocated_in_table), 2)

            results: List[dict] = []
            for r in rows:
                net = float(r["net_amount"] or 0.0)
                init_paid = float(r["paid_amount"] or 0.0)
                prior = float(r["prior_allocated"] or 0.0)
                outstanding = round(net - init_paid - prior, 2)

                # Distribute unallocated legacy receipts FIFO
                if outstanding > 0.0001 and unallocated_pool > 0.0001:
                    reduction = round(min(outstanding, unallocated_pool), 2)
                    outstanding = round(outstanding - reduction, 2)
                    unallocated_pool = round(unallocated_pool - reduction, 2)

                current_alloc = 0.0
                if exclude_receipt_id is not None:
                    row_alloc = conn.execute(
                        "SELECT allocated_amount FROM customer_receipt_allocations "
                        "WHERE customer_receipt_id = ? AND sales_invoice_id = ?",
                        (exclude_receipt_id, r["id"]),
                    ).fetchone()
                    if row_alloc:
                        current_alloc = float(row_alloc[0] or 0.0)

                if outstanding > 0.0001 or current_alloc > 0.0001:
                    results.append({
                        "id": r["id"],
                        "bill_no": r["bill_no"],
                        "sale_date": r["sale_date"],
                        "sale_time": r["sale_time"] or "",
                        "sale_type": r["sale_type"] or "Credit",
                        "bill_amount": net,
                        "paid_initial": init_paid,
                        "prior_allocated": prior,
                        "outstanding_balance": outstanding,
                        "current_allocated": current_alloc,
                    })
            return results
        finally:
            conn.close()

    @staticmethod
    def calculate_fifo_allocation(
        bills: List[dict],
        receipt_amount: float,
    ) -> List[dict]:
        """Allocate receipt_amount across bills in FIFO order."""
        rem = round(max(0.0, receipt_amount), 2)
        allocations: List[dict] = []
        for bill in bills:
            out = float(bill["outstanding_balance"])
            alloc = min(out, rem)
            alloc = round(alloc, 2)
            rem = round(rem - alloc, 2)
            remaining_bal = round(out - alloc, 2)
            allocations.append({
                "sales_invoice_id": bill["id"],
                "allocated_amount": alloc,
                "remaining_balance": remaining_bal,
            })
        return allocations

    @staticmethod
    def get_receipt_allocations(receipt_id: int) -> List[dict]:
        conn = get_connection()
        try:
            sql = """
                SELECT cra.id, cra.customer_receipt_id, cra.sales_invoice_id,
                       cra.allocated_amount, cra.discount_amount,
                       si.bill_no, si.sale_date, si.net_amount
                FROM customer_receipt_allocations cra
                JOIN sales_invoices si ON si.id = cra.sales_invoice_id
                WHERE cra.customer_receipt_id = ?
                ORDER BY cra.id ASC
            """
            rows = conn.execute(sql, (receipt_id,)).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ── write (single transaction: source + accounting posting + allocations) ────────
    @staticmethod
    def insert_receipt(header: dict, allocations: Optional[List[dict]] = None) -> int:
        amount = float(header.get("amount", 0.0) or 0.0)
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
                    amount,
                    header.get("reference_no", ""),
                    header.get("remarks", ""),
                ),
            )
            receipt_id = cur.lastrowid

            # If allocations not provided explicitly, auto-allocate FIFO if bills exist
            effective_allocs = allocations
            if effective_allocs is None:
                outstanding_bills = CustomerReceiptDAO.get_outstanding_bills(header["customer_id"])
                if outstanding_bills:
                    effective_allocs = CustomerReceiptDAO.calculate_fifo_allocation(outstanding_bills, amount)

            if effective_allocs:
                for alloc in effective_allocs:
                    alloc_amt = float(alloc.get("allocated_amount", 0.0) or 0.0)
                    if alloc_amt > 0:
                        cur.execute(
                            """
                            INSERT INTO customer_receipt_allocations
                                (customer_receipt_id, sales_invoice_id, allocated_amount, discount_amount)
                            VALUES (?, ?, ?, ?)
                            """,
                            (
                                receipt_id,
                                alloc["sales_invoice_id"],
                                alloc_amt,
                                float(alloc.get("discount_amount", 0.0) or 0.0),
                            ),
                        )

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
    def update_receipt(
        receipt_id: int, header: dict, allocations: Optional[List[dict]] = None
    ) -> bool:
        amount = float(header.get("amount", 0.0) or 0.0)
        if amount <= 0:
            raise ValueError("Amount must be greater than 0.")
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
                    amount,
                    header.get("reference_no", ""),
                    header.get("remarks", ""),
                    receipt_id,
                ),
            )

            # Re-post inside THIS transaction: reverse previous posting,
            # post the updated receipt. Atomic with the edit.
            posting_engine.repost_customer_receipt(receipt_id, cur=cur)

            cur.execute(
                "DELETE FROM customer_receipt_allocations WHERE customer_receipt_id = ?",
                (receipt_id,),
            )

            effective_allocs = allocations
            if effective_allocs is None:
                outstanding_bills = CustomerReceiptDAO.get_outstanding_bills(
                    header["customer_id"], exclude_receipt_id=receipt_id
                )
                if outstanding_bills:
                    effective_allocs = CustomerReceiptDAO.calculate_fifo_allocation(outstanding_bills, amount)

            if effective_allocs:
                for alloc in effective_allocs:
                    alloc_amt = float(alloc.get("allocated_amount", 0.0) or 0.0)
                    if alloc_amt > 0:
                        cur.execute(
                            """
                            INSERT INTO customer_receipt_allocations
                                (customer_receipt_id, sales_invoice_id, allocated_amount, discount_amount)
                            VALUES (?, ?, ?, ?)
                            """,
                            (
                                receipt_id,
                                alloc["sales_invoice_id"],
                                alloc_amt,
                                float(alloc.get("discount_amount", 0.0) or 0.0),
                            ),
                        )

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

            cur.execute(
                "DELETE FROM customer_receipt_allocations WHERE customer_receipt_id = ?",
                (receipt_id,),
            )
            cur.execute("DELETE FROM customer_receipts WHERE id = ?", (receipt_id,))

            conn.commit()
            return True
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
