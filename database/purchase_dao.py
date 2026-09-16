from __future__ import annotations

import sqlite3
from database.connection import get_connection
from database.accounting_posting import (
    SOURCE_PURCHASE_INVOICE,
    posting_engine,
)


class PurchaseDAO:
    """Data access for purchase invoices, invoice items, and stock batches."""

    # ------------------------------------------------------------------
    # Voucher number
    # ------------------------------------------------------------------

    @staticmethod
    def generate_next_voucher_no() -> str:
        conn = get_connection()
        try:
            cur = conn.execute(
                "SELECT voucher_no FROM purchase_invoices ORDER BY id DESC LIMIT 1"
            )
            row = cur.fetchone()
            if row is None:
                return "PV-0001"
            last = row["voucher_no"]
            # Extract numeric part after the last '-'
            idx = last.rfind("-")
            if idx >= 0:
                prefix = last[: idx + 1]
                num_part = last[idx + 1 :]
            else:
                prefix = "PV-"
                num_part = last
            try:
                num = int(num_part) + 1
            except ValueError:
                num = 1
            return f"{prefix}{num:04d}"
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Invoice CRUD
    # ------------------------------------------------------------------

    @staticmethod
    def get_all() -> list[dict]:
        conn = get_connection()
        try:
            cur = conn.execute(
                """
                SELECT pi.*, s.supplier_name
                FROM purchase_invoices pi
                LEFT JOIN suppliers s ON s.id = pi.supplier_id
                ORDER BY pi.id DESC
                """
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def get_by_id(invoice_id: int) -> dict | None:
        conn = get_connection()
        try:
            cur = conn.execute(
                """
                SELECT pi.*, s.supplier_name
                FROM purchase_invoices pi
                LEFT JOIN suppliers s ON s.id = pi.supplier_id
                WHERE pi.id = ?
                """,
                (invoice_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    @staticmethod
    def get_all_filtered(start_date: str = "", end_date: str = "",
                         supplier_id: int | None = None) -> list[dict]:
        conn = get_connection()
        try:
            clauses: list[str] = []
            params: list = []
            if start_date:
                clauses.append("pi.voucher_date >= ?")
                params.append(start_date)
            if end_date:
                clauses.append("pi.voucher_date <= ?")
                params.append(end_date)
            if supplier_id is not None:
                clauses.append("pi.supplier_id = ?")
                params.append(supplier_id)
            where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
            cur = conn.execute(
                f"""
                SELECT pi.*, s.supplier_name
                FROM purchase_invoices pi
                LEFT JOIN suppliers s ON s.id = pi.supplier_id
                {where}
                ORDER BY pi.id DESC
                """,
                params,
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def insert_invoice(*, voucher_no: str, voucher_date: str, voucher_time: str,
                       purchase_type: str, supplier_id: int | None,
                       invoice_no: str, invoice_date: str,
                       invoice_net_amount: float, bill_discount: float,
                       due_date: str, total_amount: float, gst_amount: float,
                       debit_note_amount: float, other_amount: float,
                       paid_amount: float, round_off: float, net_amount: float,
                       remarks: str, items: list[dict]) -> int:
        """Insert invoice + items + stock in a single transaction.

        Each dict in *items* must contain at least: item_id, batch_no,
        pay_qty, free_qty, rate, mrp, discount, gst_percent, amount,
        purchase_rate, net_rate, pp, pack_size, expiry, gst_amount.
        Returns the new invoice id.
        """
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("BEGIN")
            cur.execute(
                """
                INSERT INTO purchase_invoices (
                    voucher_no, voucher_date, voucher_time, purchase_type,
                    supplier_id, invoice_no, invoice_date, invoice_net_amount,
                    bill_discount, due_date, total_amount, gst_amount,
                    debit_note_amount, other_amount, paid_amount, round_off,
                    net_amount, remarks
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    voucher_no, voucher_date, voucher_time, purchase_type,
                    supplier_id, invoice_no, invoice_date, invoice_net_amount,
                    bill_discount, due_date, total_amount, gst_amount,
                    debit_note_amount, other_amount, paid_amount, round_off,
                    net_amount, remarks,
                ),
            )
            invoice_id = cur.lastrowid

            for item in items:
                cur.execute(
                    """
                    INSERT INTO purchase_invoice_items (
                        purchase_invoice_id, item_id, pack_size, pay_qty,
                        free_qty, batch_no, expiry, rate, mrp, discount,
                        gst_percent, gst_amount, amount, purchase_rate,
                        net_rate, pp
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        invoice_id, item["item_id"], item.get("pack_size", ""),
                        item["pay_qty"], item["free_qty"], item["batch_no"],
                        item["expiry"], item["rate"], item["mrp"],
                        item["discount"], item["gst_percent"], item["gst_amount"],
                        item["amount"], item["purchase_rate"], item["net_rate"],
                        item["pp"],
                    ),
                )

                # Stock batch: find existing or create new
                cur.execute(
                    """
                    SELECT id, stock_qty FROM stock_batches
                    WHERE item_id = ? AND batch_no = ?
                    """,
                    (item["item_id"], item["batch_no"]),
                )
                batch = cur.fetchone()
                qty_to_add = item["pay_qty"] + item["free_qty"]
                if batch:
                    cur.execute(
                        "UPDATE stock_batches SET stock_qty = stock_qty + ? WHERE id = ?",
                        (qty_to_add, batch["id"]),
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO stock_batches (
                            item_id, batch_no, expiry, pack_size, mrp,
                            purchase_rate, net_rate, stock_qty
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            item["item_id"], item["batch_no"], item["expiry"],
                            item.get("pack_size", ""), item["mrp"],
                            item["purchase_rate"], item["net_rate"], qty_to_add,
                        ),
                    )

            # Accounting posting joins THIS transaction (atomic with save).
            posting_engine.post_purchase_invoice(invoice_id, cur=cur)

            conn.commit()
            return invoice_id
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def update_invoice(*, invoice_id: int, voucher_no: str, voucher_date: str,
                       voucher_time: str, purchase_type: str,
                       supplier_id: int | None, invoice_no: str,
                       invoice_date: str, invoice_net_amount: float,
                       bill_discount: float, due_date: str,
                       total_amount: float, gst_amount: float,
                       debit_note_amount: float, other_amount: float,
                       paid_amount: float, round_off: float,
                       net_amount: float, remarks: str,
                       items: list[dict]) -> None:
        """Update invoice + replace items + adjust stock in a single transaction.

        Stock from old items is reversed; stock from new items is applied.
        """
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("BEGIN")

            # Reverse previous accounting posting inside THIS transaction
            posting_engine.reverse(SOURCE_PURCHASE_INVOICE, invoice_id, cur=cur)

            # Reverse old stock
            cur.execute(
                "SELECT item_id, batch_no, pay_qty, free_qty FROM purchase_invoice_items WHERE purchase_invoice_id = ?",
                (invoice_id,),
            )
            for old in cur.fetchall():
                qty_to_sub = old["pay_qty"] + old["free_qty"]
                cur.execute(
                    """
                    UPDATE stock_batches
                    SET stock_qty = MAX(stock_qty - ?, 0)
                    WHERE item_id = ? AND batch_no = ?
                    """,
                    (qty_to_sub, old["item_id"], old["batch_no"]),
                )

            # Delete old items
            cur.execute(
                "DELETE FROM purchase_invoice_items WHERE purchase_invoice_id = ?",
                (invoice_id,),
            )

            # Update invoice header
            cur.execute(
                """
                UPDATE purchase_invoices SET
                    voucher_no = ?, voucher_date = ?, voucher_time = ?,
                    purchase_type = ?, supplier_id = ?, invoice_no = ?,
                    invoice_date = ?, invoice_net_amount = ?,
                    bill_discount = ?, due_date = ?, total_amount = ?,
                    gst_amount = ?, debit_note_amount = ?, other_amount = ?,
                    paid_amount = ?, round_off = ?, net_amount = ?, remarks = ?
                WHERE id = ?
                """,
                (
                    voucher_no, voucher_date, voucher_time, purchase_type,
                    supplier_id, invoice_no, invoice_date, invoice_net_amount,
                    bill_discount, due_date, total_amount, gst_amount,
                    debit_note_amount, other_amount, paid_amount, round_off,
                    net_amount, remarks, invoice_id,
                ),
            )

            # Insert new items + apply stock
            for item in items:
                cur.execute(
                    """
                    INSERT INTO purchase_invoice_items (
                        purchase_invoice_id, item_id, pack_size, pay_qty,
                        free_qty, batch_no, expiry, rate, mrp, discount,
                        gst_percent, gst_amount, amount, purchase_rate,
                        net_rate, pp
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        invoice_id, item["item_id"], item.get("pack_size", ""),
                        item["pay_qty"], item["free_qty"], item["batch_no"],
                        item["expiry"], item["rate"], item["mrp"],
                        item["discount"], item["gst_percent"], item["gst_amount"],
                        item["amount"], item["purchase_rate"], item["net_rate"],
                        item["pp"],
                    ),
                )

                cur.execute(
                    """
                    SELECT id, stock_qty FROM stock_batches
                    WHERE item_id = ? AND batch_no = ?
                    """,
                    (item["item_id"], item["batch_no"]),
                )
                batch = cur.fetchone()
                qty_to_add = item["pay_qty"] + item["free_qty"]
                if batch:
                    cur.execute(
                        "UPDATE stock_batches SET stock_qty = stock_qty + ? WHERE id = ?",
                        (qty_to_add, batch["id"]),
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO stock_batches (
                            item_id, batch_no, expiry, pack_size, mrp,
                            purchase_rate, net_rate, stock_qty
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            item["item_id"], item["batch_no"], item["expiry"],
                            item.get("pack_size", ""), item["mrp"],
                            item["purchase_rate"], item["net_rate"], qty_to_add,
                        ),
                    )

            # Post new accounting effect inside THIS transaction
            posting_engine.post_purchase_invoice(invoice_id, cur=cur)

            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def get_invoice_items(invoice_id: int) -> list[dict]:
        conn = get_connection()
        try:
            cur = conn.execute(
                """
                SELECT pii.*, i.item_name
                FROM purchase_invoice_items pii
                LEFT JOIN items i ON i.id = pii.item_id
                WHERE pii.purchase_invoice_id = ?
                ORDER BY pii.id
                """,
                (invoice_id,),
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def delete_invoice(invoice_id: int) -> None:
        """Delete invoice, reverse stock, and reverse accounting in a single transaction."""
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("BEGIN")

            # Reverse the accounting posting inside THIS transaction
            posting_engine.reverse(SOURCE_PURCHASE_INVOICE, invoice_id, cur=cur)

            # Reverse stock
            cur.execute(
                "SELECT item_id, batch_no, pay_qty, free_qty FROM purchase_invoice_items WHERE purchase_invoice_id = ?",
                (invoice_id,),
            )
            for old in cur.fetchall():
                qty_to_sub = old["pay_qty"] + old["free_qty"]
                cur.execute(
                    """
                    UPDATE stock_batches
                    SET stock_qty = MAX(stock_qty - ?, 0)
                    WHERE item_id = ? AND batch_no = ?
                    """,
                    (qty_to_sub, old["item_id"], old["batch_no"]),
                )

            # Delete items (CASCADE should handle, but explicit is safer)
            cur.execute(
                "DELETE FROM purchase_invoice_items WHERE purchase_invoice_id = ?",
                (invoice_id,),
            )
            # Delete invoice
            cur.execute("DELETE FROM purchase_invoices WHERE id = ?", (invoice_id,))

            # Clean up empty stock batches
            cur.execute("DELETE FROM stock_batches WHERE stock_qty <= 0")

            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Stock / Batch helpers
    # ------------------------------------------------------------------

    @staticmethod
    def get_stock_batches_for_item(item_id: int) -> list[dict]:
        conn = get_connection()
        try:
            cur = conn.execute(
                """
                SELECT * FROM stock_batches
                WHERE item_id = ? AND stock_qty > 0
                ORDER BY batch_no
                """,
                (item_id,),
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def get_all_stock_batches() -> list[dict]:
        conn = get_connection()
        try:
            cur = conn.execute(
                """
                SELECT sb.*, i.item_name
                FROM stock_batches sb
                LEFT JOIN items i ON i.id = sb.item_id
                WHERE sb.stock_qty > 0
                ORDER BY i.item_name, sb.batch_no
                """
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()
