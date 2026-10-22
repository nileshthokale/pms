"""Data Access Object for Stock Adjustments.

Provides atomic, audit-safe stock adjustments:
- Updates stock_batches.stock_qty by loose units (+/-)
- Creates an audit record in stock_adjustments
- Validates batch-to-item integrity, non-zero adjustment, and non-negative resulting stock
- Atomic SQLite transaction: rolls back fully on any error
- History queries with date range and item filtering for Adjusted Stock List
- Atomic edit reconciliation: computes delta and updates batch stock without double-counting
"""

from __future__ import annotations

from datetime import datetime
import sqlite3
from typing import Any

from database.connection import get_connection


class StockAdjustmentError(Exception):
    """Base exception for stock adjustment operations."""
    pass


class StockAdjustmentDAO:
    """Manages stock adjustment operations and audit records."""

    @staticmethod
    def record_adjustment(
        item_id: int,
        stock_batch_id: int,
        adjusted_qty: float,
        reason: str = "",
        user_name: str = "",
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        """Atomically record a stock adjustment and update the batch stock.

        Args:
            item_id: Database ID of the medicine.
            stock_batch_id: Database ID of the target batch in stock_batches.
            adjusted_qty: Change in loose units (e.g. +2.0 or -1.0). Must not be 0.
            reason: Optional explanation (e.g. 'Physical inventory count', 'Breakage').
            user_name: Name/login of the user making the adjustment.
            conn: Optional existing connection for caller-managed transactions.

        Returns:
            dict containing the created audit record details.

        Raises:
            StockAdjustmentError: on validation failure or database error.
        """
        try:
            adj_val = float(adjusted_qty)
        except (ValueError, TypeError):
            raise StockAdjustmentError(f"Adjustment quantity '{adjusted_qty}' is not a valid number.")

        if adj_val == 0.0:
            raise StockAdjustmentError("Adjustment quantity cannot be zero.")

        close_conn = False
        if conn is None:
            conn = get_connection()
            close_conn = True

        try:
            cur = conn.cursor()

            # Read target batch with fresh locked values
            cur.execute(
                """
                SELECT
                    sb.id,
                    sb.item_id,
                    i.item_name,
                    sb.batch_no,
                    sb.expiry,
                    COALESCE(NULLIF(sb.pack_size, ''), i.pack_size, '1') AS pack_size,
                    COALESCE(sb.mrp, 0.0) AS mrp,
                    COALESCE(sb.purchase_rate, 0.0) AS purchase_rate,
                    COALESCE(sb.net_rate, 0.0) AS net_rate,
                    COALESCE(sb.stock_qty, 0.0) AS stock_qty,
                    COALESCE(
                        (
                            SELECT pii.gst_percent
                            FROM purchase_invoice_items pii
                            WHERE pii.item_id = sb.item_id AND pii.batch_no = sb.batch_no
                            ORDER BY pii.id DESC
                            LIMIT 1
                        ),
                        0.0
                    ) AS tax_percent
                FROM stock_batches sb
                JOIN items i ON i.id = sb.item_id
                WHERE sb.id = ?
                """,
                (stock_batch_id,),
            )
            batch = cur.fetchone()
            if not batch:
                raise StockAdjustmentError(f"Stock batch ID {stock_batch_id} does not exist.")

            batch_dict = dict(batch)
            if int(batch_dict["item_id"]) != int(item_id):
                raise StockAdjustmentError(
                    f"Selected batch '{batch_dict.get('batch_no')}' (item {batch_dict.get('item_id')}) "
                    f"does not belong to item ID {item_id}."
                )

            prev_qty = float(batch_dict.get("stock_qty") or 0.0)
            res_qty = round(prev_qty + adj_val, 4)

            if res_qty < 0.0:
                raise StockAdjustmentError(
                    f"Adjustment of {adj_val:+g} would result in negative stock "
                    f"({res_qty:g}). Current stock is {prev_qty:g}."
                )

            tax_percent = float(batch_dict.get("tax_percent") or 0.0)
            purchase_rate = float(batch_dict.get("purchase_rate") or 0.0)
            net_rate = float(batch_dict.get("net_rate") or 0.0)
            if not net_rate and purchase_rate:
                net_rate = round(purchase_rate * (1.0 + tax_percent / 100.0), 2)

            now = datetime.now()
            adj_date = now.strftime("%Y-%m-%d")
            adj_time = now.strftime("%H:%M:%S")

            # 1. Update stock_batches table
            cur.execute(
                "UPDATE stock_batches SET stock_qty = ? WHERE id = ?",
                (res_qty, stock_batch_id),
            )

            # 2. Insert audit record into stock_adjustments table
            cur.execute(
                """
                INSERT INTO stock_adjustments (
                    adjustment_date,
                    adjustment_time,
                    item_id,
                    stock_batch_id,
                    batch_no,
                    expiry,
                    pack_size,
                    previous_qty,
                    adjusted_qty,
                    resulting_qty,
                    mrp,
                    rate,
                    tax_percent,
                    net_rate,
                    reason,
                    user_name
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    adj_date,
                    adj_time,
                    int(item_id),
                    int(stock_batch_id),
                    str(batch_dict.get("batch_no") or ""),
                    str(batch_dict.get("expiry") or ""),
                    str(batch_dict.get("pack_size") or "1"),
                    prev_qty,
                    adj_val,
                    res_qty,
                    float(batch_dict.get("mrp") or 0.0),
                    purchase_rate,
                    tax_percent,
                    net_rate,
                    str(reason or "").strip(),
                    str(user_name or "").strip(),
                ),
            )
            adj_id = cur.lastrowid

            if close_conn:
                conn.commit()

            return {
                "id": adj_id,
                "adjustment_date": adj_date,
                "adjustment_time": adj_time,
                "item_id": int(item_id),
                "item_name": batch_dict.get("item_name") or "",
                "stock_batch_id": int(stock_batch_id),
                "batch_no": batch_dict.get("batch_no") or "",
                "expiry": batch_dict.get("expiry") or "",
                "pack_size": batch_dict.get("pack_size") or "1",
                "previous_qty": prev_qty,
                "adjusted_qty": adj_val,
                "resulting_qty": res_qty,
                "mrp": float(batch_dict.get("mrp") or 0.0),
                "rate": purchase_rate,
                "tax_percent": tax_percent,
                "net_rate": net_rate,
                "reason": reason,
                "user_name": user_name,
            }
        except Exception:
            if close_conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            raise
        finally:
            if close_conn:
                conn.close()

    @staticmethod
    def update_adjustment(
        adjustment_id: int,
        new_adjusted_qty: float,
        reason: str = "",
        user_name: str = "",
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        """Atomically reconcile and update an existing stock adjustment.

        Calculates delta = new_adjusted_qty - old_adjusted_qty.
        Adjusts stock_batches.stock_qty by delta, ensuring stock does not become negative.
        Updates the stock_adjustments audit record.
        """
        try:
            new_qty = float(new_adjusted_qty)
        except (ValueError, TypeError):
            raise StockAdjustmentError(f"Adjustment quantity '{new_adjusted_qty}' is not a valid number.")

        if new_qty == 0.0:
            raise StockAdjustmentError("Adjustment quantity cannot be zero.")

        close_conn = False
        if conn is None:
            conn = get_connection()
            close_conn = True

        try:
            cur = conn.cursor()

            # Read existing adjustment
            cur.execute(
                """
                SELECT id, item_id, stock_batch_id, adjusted_qty, previous_qty, resulting_qty
                FROM stock_adjustments
                WHERE id = ?
                """,
                (adjustment_id,),
            )
            adj = cur.fetchone()
            if not adj:
                raise StockAdjustmentError(f"Stock adjustment ID {adjustment_id} not found.")

            adj_dict = dict(adj)
            batch_id = int(adj_dict["stock_batch_id"])
            old_qty = float(adj_dict["adjusted_qty"])
            delta = round(new_qty - old_qty, 4)

            # Read current stock for the batch
            cur.execute(
                "SELECT id, item_id, batch_no, stock_qty FROM stock_batches WHERE id = ?",
                (batch_id,),
            )
            batch = cur.fetchone()
            if not batch:
                raise StockAdjustmentError(f"Stock batch ID {batch_id} no longer exists.")

            batch_dict = dict(batch)
            current_stock = float(batch_dict.get("stock_qty") or 0.0)
            new_batch_stock = round(current_stock + delta, 4)

            if new_batch_stock < 0.0:
                raise StockAdjustmentError(
                    f"Editing adjustment by {delta:+g} would result in negative stock "
                    f"({new_batch_stock:g}). Current batch stock is {current_stock:g}."
                )

            # 1. Update stock_batches
            cur.execute(
                "UPDATE stock_batches SET stock_qty = ? WHERE id = ?",
                (new_batch_stock, batch_id),
            )

            # 2. Update stock_adjustments
            cur.execute(
                """
                UPDATE stock_adjustments
                SET adjusted_qty = ?,
                    resulting_qty = previous_qty + ?,
                    reason = ?,
                    user_name = CASE WHEN ? <> '' THEN ? ELSE user_name END
                WHERE id = ?
                """,
                (
                    new_qty,
                    new_qty,
                    str(reason or "").strip(),
                    str(user_name or "").strip(),
                    str(user_name or "").strip(),
                    adjustment_id,
                ),
            )

            if close_conn:
                conn.commit()

            res = StockAdjustmentDAO.get_by_id(adjustment_id)
            if not res:
                raise StockAdjustmentError(f"Failed to reload adjustment {adjustment_id} after update.")
            return res
        except Exception:
            if close_conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            raise
        finally:
            if close_conn:
                conn.close()

    @staticmethod
    def get_by_id(adjustment_id: int) -> dict[str, Any] | None:
        """Fetch a single adjustment record by its ID with item and batch details."""
        conn = get_connection()
        try:
            cur = conn.execute(
                """
                SELECT
                    sa.*,
                    i.item_name,
                    sb.stock_qty AS current_batch_stock
                FROM stock_adjustments sa
                JOIN items i ON i.id = sa.item_id
                LEFT JOIN stock_batches sb ON sb.id = sa.stock_batch_id
                WHERE sa.id = ?
                """,
                (adjustment_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            d = dict(row)
            rate = float(d.get("rate") or 0.0)
            tax_pct = float(d.get("tax_percent") or 0.0)
            d["tax_amount"] = round(rate * tax_pct / 100.0, 2)
            return d
        finally:
            conn.close()

    @staticmethod
    def get_all_filtered(
        from_date: str = "",
        to_date: str = "",
        item_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return stock adjustment history filtered by date range and/or item.

        Calculates tax_amount = round(rate * tax_percent / 100.0, 2).
        """
        conn = get_connection()
        try:
            clauses = []
            params = []
            if from_date:
                clauses.append("sa.adjustment_date >= ?")
                params.append(from_date)
            if to_date:
                clauses.append("sa.adjustment_date <= ?")
                params.append(to_date)
            if item_id is not None:
                clauses.append("sa.item_id = ?")
                params.append(item_id)

            where_sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""
            sql = f"""
                SELECT
                    sa.*,
                    i.item_name
                FROM stock_adjustments sa
                JOIN items i ON i.id = sa.item_id
                {where_sql}
                ORDER BY sa.adjustment_date DESC, sa.id DESC
            """
            cur = conn.execute(sql, params)
            rows = []
            for r in cur.fetchall():
                d = dict(r)
                rate = float(d.get("rate") or 0.0)
                tax_pct = float(d.get("tax_percent") or 0.0)
                d["tax_amount"] = round(rate * tax_pct / 100.0, 2)
                rows.append(d)
            return rows
        finally:
            conn.close()

    @staticmethod
    def get_distinct_adjusted_items() -> list[dict[str, Any]]:
        """Return distinct items that have stock adjustments for filter dropdown."""
        conn = get_connection()
        try:
            cur = conn.execute(
                """
                SELECT DISTINCT
                    i.id,
                    i.item_name
                FROM stock_adjustments sa
                JOIN items i ON i.id = sa.item_id
                ORDER BY i.item_name COLLATE NOCASE ASC
                """
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def get_adjustments_for_item(item_id: int) -> list[dict[str, Any]]:
        """Return all adjustment records for a medicine ordered newest first."""
        conn = get_connection()
        try:
            cur = conn.execute(
                """
                SELECT
                    sa.*,
                    i.item_name
                FROM stock_adjustments sa
                JOIN items i ON i.id = sa.item_id
                WHERE sa.item_id = ?
                ORDER BY sa.adjustment_date DESC, sa.id DESC
                """,
                (item_id,),
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def get_adjustments_for_batch(stock_batch_id: int) -> list[dict[str, Any]]:
        """Return all adjustment records for a specific batch ordered newest first."""
        conn = get_connection()
        try:
            cur = conn.execute(
                """
                SELECT
                    sa.*,
                    i.item_name
                FROM stock_adjustments sa
                JOIN items i ON i.id = sa.item_id
                WHERE sa.stock_batch_id = ?
                ORDER BY sa.adjustment_date DESC, sa.id DESC
                """,
                (stock_batch_id,),
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def get_recent_adjustments(limit: int = 50) -> list[dict[str, Any]]:
        """Return recently recorded adjustments across all items."""
        return StockAdjustmentDAO.get_all_filtered()[:limit]
