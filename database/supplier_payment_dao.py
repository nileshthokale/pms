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

        Reads from linked ledger (authoritative accounting balance) when available.
        Falls back to transaction calculation if unlinked.
        """
        conn = get_connection()
        try:
            sup = conn.execute(
                "SELECT ledger_id FROM suppliers WHERE id = ?",
                (supplier_id,),
            ).fetchone()
            if sup and sup["ledger_id"]:
                from database.ledger_dao import LedgerDAO
                bal_dict = LedgerDAO.get_balance(sup["ledger_id"])
                cb = round(bal_dict.get("closing_balance", 0.0), 2)
                return -cb if bal_dict.get("closing_balance_type") == "Debit" else cb

            cur = conn.execute(
                "SELECT COALESCE(SUM(net_amount), 0) FROM purchase_invoices WHERE supplier_id = ?",
                (supplier_id,),
            )
            total_purchases = cur.fetchone()[0]

            cur = conn.execute(
                "SELECT COALESCE(SUM(total_amount), 0) FROM debit_notes WHERE supplier_id = ?",
                (supplier_id,),
            )
            total_debit_notes = cur.fetchone()[0]

            cur = conn.execute(
                "SELECT COALESCE(SUM(amount), 0) FROM supplier_payments WHERE supplier_id = ?",
                (supplier_id,),
            )
            total_payments = cur.fetchone()[0]

            balance = total_purchases - total_debit_notes - total_payments
            return round(balance, 2)
        finally:
            conn.close()

    # ── invoice allocations & outstanding balance ─────────────────────
    @staticmethod
    def get_outstanding_invoices(
        supplier_id: int,
        exclude_payment_id: Optional[int] = None,
    ) -> List[dict]:
        """Fetch all purchase invoices for supplier with remaining unpaid balance.

        Ordered by voucher_date ASC, id ASC (FIFO order).

        Legacy handling: supplier_payments imported from Pharma-WINNER may have
        no rows in supplier_payment_allocations even though they were posted to
        the ledger.  To keep the displayed outstanding consistent with the
        authoritative ledger balance we:
          1. Compute per-invoice outstanding = net_amount - paid_amount - SUM(allocations).
          2. Compute total_unallocated_payments = SUM(supplier_payments.amount) - SUM(all_allocations).
          3. Distribute total_unallocated_payments in FIFO order across
             invoices that still show outstanding, reducing each to 0 when
             the unallocated amount covers it.
        This makes Total Outstanding == supplier ledger balance (credit balance).
        """
        conn = get_connection()
        try:
            sql = """
                SELECT pi.id, pi.voucher_no, pi.voucher_date, pi.voucher_time,
                       pi.purchase_type, pi.invoice_no, pi.invoice_date,
                       pi.net_amount, pi.paid_amount,
                       COALESCE((
                           SELECT SUM(spa.allocated_amount)
                           FROM supplier_payment_allocations spa
                           WHERE spa.purchase_invoice_id = pi.id
                             AND (spa.supplier_payment_id != ? OR ? IS NULL)
                       ), 0.0) AS prior_allocated
                FROM purchase_invoices pi
                WHERE pi.supplier_id = ?
                ORDER BY pi.voucher_date ASC, pi.id ASC
            """
            cur = conn.execute(sql, (exclude_payment_id, exclude_payment_id, supplier_id))
            rows = cur.fetchall()

            # ------------------------------------------------------------------
            # Compute total unallocated payment amount for this supplier.
            # Payments posted to the ledger but without allocation table rows
            # (legacy imports) still reduce the outstanding balance.  We must
            # distribute their sum in FIFO order so the total outstanding shown
            # in the dialog matches the authoritative supplier ledger balance.
            # ------------------------------------------------------------------
            if exclude_payment_id is not None:
                total_payments = float(conn.execute(
                    "SELECT COALESCE(SUM(amount), 0.0) FROM supplier_payments "
                    "WHERE supplier_id = ? AND id != ?",
                    (supplier_id, exclude_payment_id),
                ).fetchone()[0] or 0.0)
                total_allocated_in_table = float(conn.execute(
                    """SELECT COALESCE(SUM(spa.allocated_amount), 0.0)
                       FROM supplier_payment_allocations spa
                       JOIN supplier_payments sp ON sp.id = spa.supplier_payment_id
                       WHERE sp.supplier_id = ? AND sp.id != ?""",
                    (supplier_id, exclude_payment_id),
                ).fetchone()[0] or 0.0)
            else:
                total_payments = float(conn.execute(
                    "SELECT COALESCE(SUM(amount), 0.0) FROM supplier_payments WHERE supplier_id = ?",
                    (supplier_id,),
                ).fetchone()[0] or 0.0)
                total_allocated_in_table = float(conn.execute(
                    """SELECT COALESCE(SUM(spa.allocated_amount), 0.0)
                       FROM supplier_payment_allocations spa
                       JOIN supplier_payments sp ON sp.id = spa.supplier_payment_id
                       WHERE sp.supplier_id = ?""",
                    (supplier_id,),
                ).fetchone()[0] or 0.0)

            # Unallocated = payments posted to ledger with no matching allocation rows
            unallocated_pool = round(max(0.0, total_payments - total_allocated_in_table), 2)

            results: List[dict] = []
            for r in rows:
                net = float(r["net_amount"] or 0.0)
                init_paid = float(r["paid_amount"] or 0.0)
                prior = float(r["prior_allocated"] or 0.0)
                outstanding = round(net - init_paid - prior, 2)

                # Distribute unallocated legacy payments FIFO
                if outstanding > 0.0001 and unallocated_pool > 0.0001:
                    reduction = round(min(outstanding, unallocated_pool), 2)
                    outstanding = round(outstanding - reduction, 2)
                    unallocated_pool = round(unallocated_pool - reduction, 2)

                current_alloc = 0.0
                if exclude_payment_id is not None:
                    row_alloc = conn.execute(
                        "SELECT allocated_amount FROM supplier_payment_allocations "
                        "WHERE supplier_payment_id = ? AND purchase_invoice_id = ?",
                        (exclude_payment_id, r["id"]),
                    ).fetchone()
                    if row_alloc:
                        current_alloc = float(row_alloc[0] or 0.0)

                if outstanding > 0.0001 or current_alloc > 0.0001:
                    results.append({
                        "id": r["id"],
                        "voucher_no": r["voucher_no"],
                        "voucher_date": r["voucher_date"],
                        "voucher_time": r["voucher_time"] or "",
                        "purchase_type": r["purchase_type"] or "Credit",
                        "invoice_no": r["invoice_no"] or "",
                        "invoice_date": r["invoice_date"] or "",
                        "invoice_amount": net,
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
        invoices: List[dict],
        payment_amount: float,
    ) -> List[dict]:
        """Allocate payment_amount across invoices in FIFO order."""
        rem = round(max(0.0, payment_amount), 2)
        allocations: List[dict] = []
        for inv in invoices:
            out = float(inv["outstanding_balance"])
            alloc = min(out, rem)
            alloc = round(alloc, 2)
            rem = round(rem - alloc, 2)
            remaining_bal = round(out - alloc, 2)
            allocations.append({
                "purchase_invoice_id": inv["id"],
                "allocated_amount": alloc,
                "remaining_balance": remaining_bal,
            })
        return allocations

    @staticmethod
    def get_payment_allocations(payment_id: int) -> List[dict]:
        conn = get_connection()
        try:
            sql = """
                SELECT spa.id, spa.supplier_payment_id, spa.purchase_invoice_id,
                       spa.allocated_amount, spa.discount_amount,
                       pi.voucher_no, pi.invoice_no, pi.invoice_date, pi.net_amount
                FROM supplier_payment_allocations spa
                JOIN purchase_invoices pi ON pi.id = spa.purchase_invoice_id
                WHERE spa.supplier_payment_id = ?
                ORDER BY spa.id ASC
            """
            rows = conn.execute(sql, (payment_id,)).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ── write (single transaction: source + accounting posting + allocations) ────────
    @staticmethod
    def insert_payment(header: dict, allocations: Optional[List[dict]] = None) -> int:
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("BEGIN")

            voucher_no = SupplierPaymentDAO.generate_next_voucher_no(conn)
            amount = float(header.get("amount", 0.0) or 0.0)

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
                    amount,
                    header.get("reference_no", ""),
                    header.get("remarks", ""),
                ),
            )
            payment_id = cur.lastrowid

            # If allocations not provided explicitly, auto-allocate FIFO if invoices exist
            effective_allocs = allocations
            if effective_allocs is None:
                outstanding_invs = SupplierPaymentDAO.get_outstanding_invoices(header["supplier_id"])
                if outstanding_invs:
                    effective_allocs = SupplierPaymentDAO.calculate_fifo_allocation(outstanding_invs, amount)

            if effective_allocs:
                for alloc in effective_allocs:
                    alloc_amt = float(alloc.get("allocated_amount", 0.0) or 0.0)
                    if alloc_amt > 0:
                        cur.execute(
                            """
                            INSERT INTO supplier_payment_allocations
                                (supplier_payment_id, purchase_invoice_id, allocated_amount, discount_amount)
                            VALUES (?, ?, ?, ?)
                            """,
                            (
                                payment_id,
                                alloc["purchase_invoice_id"],
                                alloc_amt,
                                float(alloc.get("discount_amount", 0.0) or 0.0),
                            ),
                        )

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
    def update_payment(
        payment_id: int, header: dict, allocations: Optional[List[dict]] = None
    ) -> bool:
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("BEGIN")

            amount = float(header.get("amount", 0.0) or 0.0)

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
                    amount,
                    header.get("reference_no", ""),
                    header.get("remarks", ""),
                    payment_id,
                ),
            )

            # Re-post inside THIS transaction: reverse previous posting,
            # post the updated payment. Atomic with the edit.
            posting_engine.repost_supplier_payment(payment_id, cur=cur)

            cur.execute(
                "DELETE FROM supplier_payment_allocations WHERE supplier_payment_id = ?",
                (payment_id,),
            )

            effective_allocs = allocations
            if effective_allocs is None:
                outstanding_invs = SupplierPaymentDAO.get_outstanding_invoices(
                    header["supplier_id"], exclude_payment_id=payment_id
                )
                if outstanding_invs:
                    effective_allocs = SupplierPaymentDAO.calculate_fifo_allocation(outstanding_invs, amount)

            if effective_allocs:
                for alloc in effective_allocs:
                    alloc_amt = float(alloc.get("allocated_amount", 0.0) or 0.0)
                    if alloc_amt > 0:
                        cur.execute(
                            """
                            INSERT INTO supplier_payment_allocations
                                (supplier_payment_id, purchase_invoice_id, allocated_amount, discount_amount)
                            VALUES (?, ?, ?, ?)
                            """,
                            (
                                payment_id,
                                alloc["purchase_invoice_id"],
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
    def delete_payment(payment_id: int) -> bool:
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("BEGIN")

            # Reverse the accounting posting inside THIS transaction, so
            # no active accounting effect survives the deletion.
            posting_engine.reverse(SOURCE_SUPPLIER_PAYMENT, payment_id, cur=cur)

            cur.execute(
                "DELETE FROM supplier_payment_allocations WHERE supplier_payment_id = ?",
                (payment_id,),
            )
            cur.execute("DELETE FROM supplier_payments WHERE id = ?", (payment_id,))

            conn.commit()
            return True
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
