"""Schedule Reports Data Access Object.

Provides queries for Schedule H1 and NRX reports:
- Sales Datewise
- Sales Itemwise
- Sales All Items (grouped by item)
- Purchase Datewise
- Purchase Itemwise
- Purchase All Items (grouped by item)

All queries are strictly read-only and filter by items.scheduled:
- H1:  scheduled IN ('2', 'H1')
- NRX: scheduled IN ('4', 'NRX')
"""

from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional

from database.connection import get_connection
from core.doc_formatter import format_purchase_voucher_number


class ScheduleReportsDAO:
    """Read-only DAO for Schedule H1 and NRX sales & purchase reports."""

    @staticmethod
    def _schedule_clause(schedule_type: str, item_alias: str = "i") -> tuple[str, list[Any]]:
        st = (schedule_type or "H1").upper().strip()
        if st == "NRX":
            return f"{item_alias}.scheduled IN ('4', 'NRX')", []
        return f"{item_alias}.scheduled IN ('2', 'H1')", []

    @classmethod
    def get_scheduled_items(cls, schedule_type: str = "H1") -> List[Dict[str, Any]]:
        """Return all item records matching the specified schedule type."""
        sched_sql, _ = cls._schedule_clause(schedule_type, "i")
        sql = f"""
            SELECT id, item_name, pack_size, scheduled
            FROM items i
            WHERE {sched_sql}
            ORDER BY UPPER(TRIM(item_name)) ASC
        """
        conn = get_connection()
        try:
            cur = conn.execute(sql)
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    @classmethod
    def get_sales_schedule(
        cls,
        from_date: str,
        to_date: str,
        schedule_type: str = "H1",
        item_id: Optional[int] = None,
        grouped_by_item: bool = False,
    ) -> List[Dict[str, Any]]:
        """Fetch sales schedule records for the given date range and schedule type.

        If grouped_by_item is True, sorted by item name then sale date.
        If False, sorted by sale date then bill number.
        """
        sched_sql, _ = cls._schedule_clause(schedule_type, "i")
        item_filter = "AND sii.item_id = ?" if item_id else ""
        params: list[Any] = [from_date, to_date]
        if item_id:
            params.append(item_id)

        order_by = (
            "UPPER(TRIM(i.item_name)) ASC, i.id ASC, si.sale_date ASC, si.id ASC"
            if grouped_by_item
            else "si.sale_date ASC, si.id ASC, UPPER(TRIM(i.item_name)) ASC"
        )

        sql = f"""
            SELECT
                si.sale_date,
                si.bill_no,
                COALESCE(NULLIF(TRIM(si.patient_name), ''), 'WALKIN') AS patient_name,
                COALESCE(NULLIF(TRIM(c.address), ''), '') AS cust_address,
                COALESCE(u.unit_name, '') AS unit_name,
                COALESCE(NULLIF(TRIM(sii.pack_size), ''), i.pack_size, '') AS pack_size,
                i.item_name,
                COALESCE(sii.batch_no, '') AS batch_no,
                COALESCE(sii.expiry, '') AS expiry,
                COALESCE(sii.sale_qty, 0.0) AS qty,
                i.id AS item_id
            FROM sales_invoice_items sii
            JOIN sales_invoices si ON si.id = sii.sales_invoice_id
            JOIN items i ON i.id = sii.item_id
            LEFT JOIN units u ON u.id = i.unit_id
            LEFT JOIN customers c ON c.id = si.customer_id
            WHERE si.sale_date BETWEEN ? AND ?
              AND {sched_sql}
              {item_filter}
            ORDER BY {order_by}
        """
        conn = get_connection()
        try:
            cur = conn.execute(sql, params)
            rows = [dict(r) for r in cur.fetchall()]
            if not rows:
                return []

            # Accurately resolve patient addresses matching the bill date or patient latest record
            unique_names = list({
                r["patient_name"].strip().upper()
                for r in rows
                if r["patient_name"] and r["patient_name"].strip().upper() not in ("WALKIN", "WALKIN CUSTOMER")
            })
            addr_map: dict[str, dict[str, Any]] = {}
            if unique_names:
                for chunk_start in range(0, len(unique_names), 500):
                    chunk = unique_names[chunk_start:chunk_start + 500]
                    placeholders = ",".join(["?"] * len(chunk))
                    addr_sql = f"""
                        SELECT patient_name, address, date(updated_at) AS addr_date
                        FROM patient_addresses
                        WHERE UPPER(TRIM(patient_name)) IN ({placeholders})
                        ORDER BY updated_at DESC, id DESC
                    """
                    for p_name, addr, addr_date in conn.execute(addr_sql, chunk).fetchall():
                        norm = (p_name or "").strip().upper()
                        if norm not in addr_map:
                            addr_map[norm] = {"by_date": {}, "latest": addr or ""}
                        if addr_date and addr_date not in addr_map[norm]["by_date"]:
                            addr_map[norm]["by_date"][addr_date] = addr or ""

            for r in rows:
                p_norm = (r.get("patient_name") or "").strip().upper()
                info = addr_map.get(p_norm)
                if info:
                    resolved = info["by_date"].get(r.get("sale_date")) or info.get("latest") or ""
                else:
                    resolved = r.get("cust_address") or ""
                r["address"] = resolved
                r.pop("cust_address", None)

            return rows
        finally:
            conn.close()

    @classmethod
    def get_purchase_schedule(
        cls,
        from_date: str,
        to_date: str,
        schedule_type: str = "H1",
        item_id: Optional[int] = None,
        grouped_by_item: bool = False,
    ) -> List[Dict[str, Any]]:
        """Fetch purchase schedule records for the given date range and schedule type.

        If grouped_by_item is True, sorted by item name then voucher date.
        If False, sorted by voucher date.
        """
        sched_sql, _ = cls._schedule_clause(schedule_type, "i")
        item_filter = "AND pii.item_id = ?" if item_id else ""
        params: list[Any] = [from_date, to_date]
        if item_id:
            params.append(item_id)

        if grouped_by_item:
            order_by = "i.id ASC, pi.invoice_date ASC, pi.id ASC"
            qty_expr = """
                CASE
                    WHEN CAST(COALESCE(NULLIF(TRIM(pii.pack_size), ''), i.pack_size, '1') AS INTEGER) > 1
                    THEN (COALESCE(pii.pay_qty, 0.0) + COALESCE(pii.free_qty, 0.0)) * CAST(COALESCE(NULLIF(TRIM(pii.pack_size), ''), i.pack_size, '1') AS INTEGER)
                    ELSE (COALESCE(pii.pay_qty, 0.0) + COALESCE(pii.free_qty, 0.0))
                END
            """
            val_expr = """
                ROUND(
                    CASE
                        WHEN pii.net_rate > 0 THEN pii.net_rate * pii.pay_qty
                        ELSE pii.amount + COALESCE(pii.gst_amount, 0.0)
                    END,
                    2
                )
            """
        else:
            order_by = "pi.voucher_date ASC, pi.id ASC, UPPER(TRIM(i.item_name)) ASC"
            qty_expr = "(COALESCE(pii.pay_qty, 0.0) + COALESCE(pii.free_qty, 0.0))"
            val_expr = "COALESCE(pii.amount, 0.0)"

        sql = f"""
            SELECT
                COALESCE(pi.invoice_date, '') AS inv_date,
                COALESCE(pi.invoice_no, '') AS inv_no,
                COALESCE(s.supplier_name, '') AS supplier_name,
                COALESCE(pi.voucher_no, '') AS vh_no,
                COALESCE(pi.voucher_date, '') AS vh_date,
                COALESCE(pi.purchase_type, '') AS purchase_type,
                COALESCE(u.unit_name, '') AS unit_name,
                COALESCE(NULLIF(TRIM(pii.pack_size), ''), i.pack_size, '1') AS pack_size,
                i.item_name,
                COALESCE(pii.batch_no, '') AS batch_no,
                COALESCE(pii.expiry, '') AS expiry,
                {qty_expr} AS pur_qty,
                {val_expr} AS pur_value,
                i.id AS item_id
            FROM purchase_invoice_items pii
            JOIN purchase_invoices pi ON pi.id = pii.purchase_invoice_id
            JOIN items i ON i.id = pii.item_id
            LEFT JOIN units u ON u.id = i.unit_id
            LEFT JOIN suppliers s ON s.id = pi.supplier_id
            WHERE pi.voucher_date BETWEEN ? AND ?
              AND {sched_sql}
              {item_filter}
            ORDER BY {order_by}
        """
        conn = get_connection()
        try:
            cur = conn.execute(sql, params)
            rows = [dict(r) for r in cur.fetchall()]
            for r in rows:
                r["raw_voucher_no"] = r.get("vh_no", "")
                r["vh_no"] = format_purchase_voucher_number(
                    r.get("vh_no", ""),
                    purchase_type=r.get("purchase_type", ""),
                )
            return rows
        finally:
            conn.close()

