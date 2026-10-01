from __future__ import annotations

import sqlite3
from datetime import datetime
from database.connection import get_connection
from database.accounting_posting import SOURCE_COUNTER_SALE, posting_engine


class SalesDAO:
    """Data access for sales invoices, invoice items, and stock deduction."""

    # ------------------------------------------------------------------
    # Bill number generation
    # ------------------------------------------------------------------

    @staticmethod
    def generate_next_bill_no() -> str:
        conn = get_connection()
        try:
            cur = conn.execute(
                "SELECT bill_no FROM sales_invoices ORDER BY id DESC LIMIT 1"
            )
            row = cur.fetchone()
            if row is None:
                return "CS-0001"
            last = row["bill_no"]
            idx = last.rfind("-")
            if idx >= 0:
                prefix = last[: idx + 1]
                num_part = last[idx + 1:]
            else:
                prefix = "CS-"
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
                SELECT si.*, c.customer_name, d.doctor_name
                FROM sales_invoices si
                LEFT JOIN customers c ON c.id = si.customer_id
                LEFT JOIN doctors d ON d.id = si.doctor_id
                ORDER BY si.id DESC
                """
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def get_history_page(*, limit: int, offset: int = 0) -> list[dict]:
        """Return bill-history rows for a page of invoices and all their items."""
        conn = get_connection()
        try:
            rows = conn.execute(
                """
                SELECT
                    si.id AS invoice_id,
                    si.bill_no,
                    si.sale_type,
                    si.patient_name,
                    si.sale_time,
                    si.net_amount,
                    sii.item_id,
                    i.item_name,
                    sii.mrp,
                    sii.sale_qty,
                    sii.amount,
                    sii.pack_size,
                    sii.batch_no,
                    sii.expiry,
                    sii.discount_amount
                FROM sales_invoices si
                LEFT JOIN sales_invoice_items sii
                    ON sii.sales_invoice_id = si.id
                LEFT JOIN items i ON i.id = sii.item_id
                WHERE si.id IN (
                    SELECT id FROM sales_invoices
                    ORDER BY id DESC LIMIT ? OFFSET ?
                )
                ORDER BY si.id DESC, sii.id
                """,
                (limit, offset),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    @staticmethod
    def get_by_id(invoice_id: int) -> dict | None:
        conn = get_connection()
        try:
            cur = conn.execute(
                """
                SELECT si.*, c.customer_name, d.doctor_name
                FROM sales_invoices si
                LEFT JOIN customers c ON c.id = si.customer_id
                LEFT JOIN doctors d ON d.id = si.doctor_id
                WHERE si.id = ?
                """,
                (invoice_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    @staticmethod
    def get_invoice_items(invoice_id: int) -> list[dict]:
        conn = get_connection()
        try:
            cur = conn.execute(
                """
                SELECT sii.*, i.item_name
                FROM sales_invoice_items sii
                LEFT JOIN items i ON i.id = sii.item_id
                WHERE sii.sales_invoice_id = ?
                ORDER BY sii.id
                """,
                (invoice_id,),
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def get_all_filtered(start_date: str = "", end_date: str = "",
                         customer_id: int | None = None) -> list[dict]:
        conn = get_connection()
        try:
            clauses: list[str] = []
            params: list = []
            if start_date:
                clauses.append("si.sale_date >= ?")
                params.append(start_date)
            if end_date:
                clauses.append("si.sale_date <= ?")
                params.append(end_date)
            if customer_id is not None:
                clauses.append("si.customer_id = ?")
                params.append(customer_id)
            where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
            cur = conn.execute(
                f"""
                SELECT si.*, c.customer_name, d.doctor_name
                FROM sales_invoices si
                LEFT JOIN customers c ON c.id = si.customer_id
                LEFT JOIN doctors d ON d.id = si.doctor_id
                {where}
                ORDER BY si.id DESC
                """,
                params,
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def insert_invoice(*, bill_no: str, sale_date: str, sale_time: str,
                       sale_type: str, customer_id: int | None,
                       patient_name: str, doctor_id: int | None,
                       discount: float, paid_amount: float,
                       total_amount: float, round_off: float,
                       net_amount: float, remarks: str,
                       items: list[dict]) -> int:
        """Insert sales invoice + items + stock deduction in a single transaction.

        Each dict in *items* must contain:
        item_id, stock_batch_id, pack_size, location, batch_no, expiry,
        mrp, sale_qty, discount_amount, amount.
        Returns the new invoice id.
        """
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("BEGIN")

            # Insert invoice header
            cur.execute(
                """
                INSERT INTO sales_invoices (
                    bill_no, sale_date, sale_time, sale_type,
                    customer_id, patient_name, doctor_id,
                    discount, paid_amount, total_amount, round_off,
                    net_amount, remarks
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    bill_no, sale_date, sale_time, sale_type,
                    customer_id, patient_name, doctor_id,
                    discount, paid_amount, total_amount, round_off,
                    net_amount, remarks,
                ),
            )
            invoice_id = cur.lastrowid

            # Insert items and deduct stock
            for item in items:
                cur.execute(
                    """
                    INSERT INTO sales_invoice_items (
                        sales_invoice_id, item_id, stock_batch_id,
                        pack_size, location, batch_no, expiry,
                        mrp, sale_qty, discount_amount, amount
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        invoice_id, item["item_id"], item["stock_batch_id"],
                        item.get("pack_size", ""), item.get("location", ""),
                        item["batch_no"], item.get("expiry", ""),
                        item["mrp"], item["sale_qty"],
                        item.get("discount_amount", 0.0), item["amount"],
                    ),
                )

                # Verify stock and deduct
                cur.execute(
                    "SELECT id, stock_qty FROM stock_batches WHERE id = ?",
                    (item["stock_batch_id"],),
                )
                batch = cur.fetchone()
                if not batch:
                    raise ValueError(
                        f"Stock batch id {item['stock_batch_id']} not found."
                    )
                if batch["stock_qty"] < item["sale_qty"]:
                    raise ValueError(
                        f"Insufficient stock for batch {item['batch_no']}. "
                        f"Available: {batch['stock_qty']}, Requested: {item['sale_qty']}"
                    )
                cur.execute(
                    "UPDATE stock_batches SET stock_qty = stock_qty - ? WHERE id = ?",
                    (item["sale_qty"], item["stock_batch_id"]),
                )

            # Accounting posting joins THIS transaction (atomic with save).
            posting_engine.post_counter_sale(invoice_id, cur=cur)

            conn.commit()
            return invoice_id
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def update_invoice(*, invoice_id: int, bill_no: str, sale_date: str,
                       sale_time: str, sale_type: str,
                       customer_id: int | None, patient_name: str,
                       doctor_id: int | None, discount: float,
                       paid_amount: float, total_amount: float,
                       round_off: float, net_amount: float, remarks: str,
                       items: list[dict]) -> None:
        """Update sale header/items, adjust stock, and repost accounting.

        Runs in ONE transaction:
            1. Reverse the previous accounting posting (no-op if the
               sale was never posted).
            2. Reverse the previous stock deduction.
            3. Replace the item rows.
            4. Update the header.
            5. Insert new items and deduct stock (same checks as
               insert_invoice).
            6. Post the updated accounting effect.
        Any failure rolls back everything (sale, stock, accounting).
        """
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("BEGIN")

            # Reverse previous accounting posting inside THIS transaction
            posting_engine.reverse(SOURCE_COUNTER_SALE, invoice_id, cur=cur)

            # Reverse previous stock deduction
            cur.execute(
                "SELECT stock_batch_id, sale_qty FROM sales_invoice_items "
                "WHERE sales_invoice_id = ?",
                (invoice_id,),
            )
            for old in cur.fetchall():
                cur.execute(
                    "UPDATE stock_batches SET stock_qty = stock_qty + ? "
                    "WHERE id = ?",
                    (old["sale_qty"], old["stock_batch_id"]),
                )

            # Replace item rows
            cur.execute(
                "DELETE FROM sales_invoice_items WHERE sales_invoice_id = ?",
                (invoice_id,),
            )

            # Update header
            cur.execute(
                """
                UPDATE sales_invoices SET
                    bill_no = ?, sale_date = ?, sale_time = ?, sale_type = ?,
                    customer_id = ?, patient_name = ?, doctor_id = ?,
                    discount = ?, paid_amount = ?, total_amount = ?,
                    round_off = ?, net_amount = ?, remarks = ?
                WHERE id = ?
                """,
                (
                    bill_no, sale_date, sale_time, sale_type,
                    customer_id, patient_name, doctor_id,
                    discount, paid_amount, total_amount, round_off,
                    net_amount, remarks, invoice_id,
                ),
            )

            # Insert new items and deduct stock (same checks as insert)
            for item in items:
                cur.execute(
                    """
                    INSERT INTO sales_invoice_items (
                        sales_invoice_id, item_id, stock_batch_id,
                        pack_size, location, batch_no, expiry,
                        mrp, sale_qty, discount_amount, amount
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        invoice_id, item["item_id"], item["stock_batch_id"],
                        item.get("pack_size", ""), item.get("location", ""),
                        item["batch_no"], item.get("expiry", ""),
                        item["mrp"], item["sale_qty"],
                        item.get("discount_amount", 0.0), item["amount"],
                    ),
                )
                cur.execute(
                    "SELECT id, stock_qty FROM stock_batches WHERE id = ?",
                    (item["stock_batch_id"],),
                )
                batch = cur.fetchone()
                if not batch:
                    raise ValueError(
                        f"Stock batch id {item['stock_batch_id']} not found."
                    )
                if batch["stock_qty"] < item["sale_qty"]:
                    raise ValueError(
                        f"Insufficient stock for batch {item['batch_no']}. "
                        f"Available: {batch['stock_qty']}, Requested: {item['sale_qty']}"
                    )
                cur.execute(
                    "UPDATE stock_batches SET stock_qty = stock_qty - ? WHERE id = ?",
                    (item["sale_qty"], item["stock_batch_id"]),
                )

            # Post the updated accounting effect inside THIS transaction
            posting_engine.post_counter_sale(invoice_id, cur=cur)

            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def delete_invoice(invoice_id: int) -> None:
        """Delete sales invoice, restore stock, and clean up empty batches."""
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("BEGIN")

            # Restore stock for each item
            cur.execute(
                "SELECT stock_batch_id, sale_qty FROM sales_invoice_items WHERE sales_invoice_id = ?",
                (invoice_id,),
            )
            for old in cur.fetchall():
                cur.execute(
                    "UPDATE stock_batches SET stock_qty = stock_qty + ? WHERE id = ?",
                    (old["sale_qty"], old["stock_batch_id"]),
                )

            # Reverse the accounting posting inside THIS transaction so no
            # active accounting effect survives the deletion (no-op for
            # sales that were never posted).
            posting_engine.reverse(SOURCE_COUNTER_SALE, invoice_id, cur=cur)

            # Delete items
            cur.execute(
                "DELETE FROM sales_invoice_items WHERE sales_invoice_id = ?",
                (invoice_id,),
            )
            # Delete invoice
            cur.execute("DELETE FROM sales_invoices WHERE id = ?", (invoice_id,))

            # Clean up empty stock batches
            cur.execute("DELETE FROM stock_batches WHERE stock_qty <= 0")

            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Stock batch helpers (for item selection in counter sale)
    # ------------------------------------------------------------------

    @staticmethod
    def get_stock_batches_for_item(item_id: int) -> list[dict]:
        """Return available (stock_qty > 0) batches for an item.

        Sellable batches keep the original expiry order and are listed
        first; expired batches follow them.  Nothing is filtered out or
        changed — only the order — so keyboard selection (Down, Enter) and
        the batch popup always reach a batch that can actually be sold.
        """
        conn = get_connection()
        try:
            cur = conn.execute(
                """
                SELECT sb.*, i.item_name, i.location
                FROM stock_batches sb
                LEFT JOIN items i ON i.id = sb.item_id
                WHERE sb.item_id = ? AND sb.stock_qty > 0
                ORDER BY sb.expiry, sb.batch_no
                """,
                (item_id,),
            )
            batches = [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()
        batches.sort(
            key=lambda b: (
                SalesDAO.is_expired(b.get("expiry") or ""),
                b.get("expiry") or "",
                b.get("batch_no") or "",
            )
        )
        return batches

    @staticmethod
    def get_all_stock_batches() -> list[dict]:
        conn = get_connection()
        try:
            cur = conn.execute(
                """
                SELECT sb.*, i.item_name, i.location
                FROM stock_batches sb
                LEFT JOIN items i ON i.id = sb.item_id
                WHERE sb.stock_qty > 0
                ORDER BY i.item_name, sb.batch_no
                """
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def is_expired(expiry: str) -> bool:
        """Check migrated YYYY-MM-DD and legacy MM/YY expiry values."""
        if not expiry:
            return False
        value = expiry.strip()
        try:
            expiry_date = datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            try:
                month_text, year_text = value.split("/", 1)
                expiry_date = datetime(
                    2000 + int(year_text), int(month_text), 1
                ).date()
            except (ValueError, IndexError):
                return False
        return expiry_date < datetime.now().date()

    @staticmethod
    def get_total_stock_for_item(item_id: int) -> float:
        """Return total stock across all batches for an item."""
        conn = get_connection()
        try:
            cur = conn.execute(
                "SELECT COALESCE(SUM(stock_qty), 0) as total FROM stock_batches WHERE item_id = ?",
                (item_id,),
            )
            row = cur.fetchone()
            return float(row["total"]) if row else 0.0
        finally:
            conn.close()

    @staticmethod
    def get_batch_by_id(batch_id: int) -> dict | None:
        conn = get_connection()
        try:
            cur = conn.execute(
                "SELECT * FROM stock_batches WHERE id = ?", (batch_id,)
            )
            row = cur.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    @staticmethod
    def get_batch_by_item_and_batch_no(item_id: int, batch_no: str) -> dict | None:
        """Find a stock batch by item_id and batch_no (for hold bill resume)."""
        conn = get_connection()
        try:
            cur = conn.execute(
                "SELECT * FROM stock_batches WHERE item_id = ? AND batch_no = ?",
                (item_id, batch_no),
            )
            row = cur.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()
