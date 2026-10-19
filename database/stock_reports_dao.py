"""Stock Reports DAO.

Read-only reporting over stock inventory, batches, purchases, and sales.
Supports:
1. Items (All) Stock Report
2. Companywise Item Stock Report
3. Expired Item List Report
4. Item List Report
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from database.connection import get_connection
from database.expiry_report_dao import parse_expiry
from database.purchase_dao import pack_factor


def fmt_expiry_display(expiry_val: Any) -> str:
    """Format stored expiry value into DD/MM/YYYY for Crystal Reports."""
    if not expiry_val:
        return ""
    text = str(expiry_val).strip()
    if not text:
        return ""

    parsed = parse_expiry(text)
    if not parsed:
        return text

    # If original text had day specified in ISO (YYYY-MM-DD), use exact day
    if "-" in text and len(text.split("-")) == 3:
        return parsed.strftime("%d/%m/%Y")

    # If original text was MM/YY or MM/YYYY, end-of-month is the true expiry date
    last_day = calendar.monthrange(parsed.year, parsed.month)[1]
    return f"{last_day:02d}/{parsed.month:02d}/{parsed.year:04d}"


def get_expiry_date(expiry_val: Any) -> Optional[date]:
    """Return normalized date object for filtering."""
    if not expiry_val:
        return None
    text = str(expiry_val).strip()
    parsed = parse_expiry(text)
    if not parsed:
        return None
    if "-" in text and len(text.split("-")) == 3:
        return parsed
    last_day = calendar.monthrange(parsed.year, parsed.month)[1]
    return date(parsed.year, parsed.month, last_day)


class StockReportsDAO:
    """Read-only DAO for the 4 Crystal Reports-style Stock Reports."""

    # ──────────────────────────────────────────────────────────────────
    # 1. Items (All) Stock Report
    # ──────────────────────────────────────────────────────────────────
    @staticmethod
    def get_items_all_stock(
        near_expiry_days: int = 0,
        include_expired: bool = False,
        as_of_date: Optional[date] = None,
    ) -> List[dict]:
        """Fetch batch-wise stock rows with purchase, sales, and balance quantities."""
        today = as_of_date or date.today()

        conn = get_connection()
        try:
            query = """
                SELECT
                    sb.id as batch_id,
                    sb.item_id,
                    i.item_name,
                    COALESCE(u.unit_name, '') as unit_name,
                    COALESCE(c.company_name, '') as company_name,
                    sb.batch_no,
                    sb.expiry,
                    sb.pack_size,
                    COALESCE(sb.mrp, i.mrp, 0.0) as mrp,
                    COALESCE(NULLIF(sb.net_rate, 0), sb.purchase_rate, i.rate, 0.0) as net_rate,
                    sb.stock_qty as bal_qty,
                    COALESCE(pur.total_pur, 0.0) as raw_pur_qty,
                    COALESCE(sale.total_sale, 0.0) as raw_sale_qty
                FROM stock_batches sb
                JOIN items i ON i.id = sb.item_id
                LEFT JOIN units u ON u.id = i.unit_id
                LEFT JOIN companies c ON c.id = i.company_id
                LEFT JOIN (
                    SELECT
                        item_id,
                        batch_no,
                        SUM((pay_qty + COALESCE(free_qty, 0)) * CASE WHEN pack_size > 0 THEN pack_size ELSE 1 END) as total_pur
                    FROM purchase_invoice_items
                    GROUP BY item_id, batch_no
                ) pur ON pur.item_id = sb.item_id AND pur.batch_no = sb.batch_no
                LEFT JOIN (
                    SELECT
                        item_id,
                        batch_no,
                        SUM(sale_qty) as total_sale
                    FROM sales_invoice_items
                    GROUP BY item_id, batch_no
                ) sale ON sale.item_id = sb.item_id AND sale.batch_no = sb.batch_no
                WHERE sb.stock_qty > 0
                ORDER BY i.item_name COLLATE NOCASE, sb.expiry, sb.batch_no
            """
            cur = conn.execute(query)
            raw_rows = [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

        filtered_rows: List[dict] = []
        for r in raw_rows:
            exp_date = get_expiry_date(r.get("expiry"))
            is_expired = (exp_date < today) if exp_date else False

            # Expiry filter
            if is_expired and not include_expired:
                continue

            if near_expiry_days > 0 and exp_date:
                cutoff = today + timedelta(days=near_expiry_days)
                if exp_date > cutoff:
                    continue

            # Reconcile quantities: PurQty - SaleQty = BalQty
            bal_qty = float(r.get("bal_qty") or 0.0)
            raw_pur = float(r.get("raw_pur_qty") or 0.0)
            raw_sale = float(r.get("raw_sale_qty") or 0.0)

            if raw_pur <= 0:
                # If purchase invoice not found in DB (migrated/opening stock)
                sale_qty = raw_sale
                pur_qty = bal_qty + sale_qty
            else:
                sale_qty = max(0.0, raw_pur - bal_qty) if raw_sale <= 0 else raw_sale
                pur_qty = raw_pur

            p_size = r.get("pack_size")
            factor = pack_factor(p_size)
            net_rate = float(r.get("net_rate") or 0.0)
            pur_value = round((bal_qty * net_rate) / factor, 2)

            r["pur_qty"] = pur_qty
            r["sale_qty"] = sale_qty
            r["bal_qty"] = bal_qty
            r["net_rate"] = net_rate
            r["pur_value"] = pur_value
            r["expiry_formatted"] = fmt_expiry_display(r.get("expiry"))
            filtered_rows.append(r)

        return filtered_rows

    # ──────────────────────────────────────────────────────────────────
    # 2. Companywise Item Stock Report
    # ──────────────────────────────────────────────────────────────────
    @staticmethod
    def get_companywise_item_stock(company_id: int) -> List[dict]:
        """Fetch stock batches grouped by item for a specific company."""
        conn = get_connection()
        try:
            query = """
                SELECT
                    sb.id as batch_id,
                    sb.item_id,
                    i.item_name,
                    COALESCE(u.unit_name, '') as unit_name,
                    c.company_name,
                    i.company_id as company_id,
                    sb.batch_no,
                    sb.expiry,
                    sb.pack_size,
                    COALESCE(sb.mrp, i.mrp, 0.0) as mrp,
                    COALESCE(NULLIF(sb.net_rate, 0), sb.purchase_rate, i.rate, 0.0) as net_rate,
                    sb.stock_qty as stock_qty
                FROM stock_batches sb
                JOIN items i ON i.id = sb.item_id
                JOIN companies c ON c.id = i.company_id
                LEFT JOIN units u ON u.id = i.unit_id
                WHERE i.company_id = ? AND sb.stock_qty > 0
                ORDER BY i.item_name COLLATE NOCASE, sb.expiry, sb.batch_no
            """
            cur = conn.execute(query, (company_id,))
            raw_rows = [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

        processed_rows: List[dict] = []
        for r in raw_rows:
            stock = float(r.get("stock_qty") or 0.0)
            factor = pack_factor(r.get("pack_size"))
            net_rate = float(r.get("net_rate") or 0.0)
            mrp = float(r.get("mrp") or 0.0)

            pur_value = round((stock * net_rate) / factor, 2)
            sales_value = round((stock * mrp) / factor, 2)

            r["stock_qty"] = stock
            r["net_rate"] = net_rate
            r["pur_value"] = pur_value
            r["mrp"] = mrp
            r["sales_value"] = sales_value
            r["expiry_formatted"] = fmt_expiry_display(r.get("expiry"))
            processed_rows.append(r)

        return processed_rows

    # ──────────────────────────────────────────────────────────────────
    # 3. Expired Item List
    # ──────────────────────────────────────────────────────────────────
    @staticmethod
    def get_expired_item_list(
        expired_days: int = 0,
        as_of_date: Optional[date] = None,
    ) -> List[dict]:
        """Fetch stock batches that are expired as of today (or within the last N days)."""
        today = as_of_date or date.today()

        conn = get_connection()
        try:
            query = """
                SELECT
                    sb.id as batch_id,
                    sb.item_id,
                    i.item_name,
                    COALESCE(u.unit_name, '') as unit_name,
                    COALESCE(c.company_name, '') as company_name,
                    sb.batch_no,
                    sb.expiry,
                    sb.pack_size,
                    COALESCE(sb.mrp, i.mrp, 0.0) as mrp,
                    COALESCE(NULLIF(sb.net_rate, 0), sb.purchase_rate, i.rate, 0.0) as net_rate,
                    sb.stock_qty as bal_qty,
                    COALESCE(pur.total_pur, 0.0) as raw_pur_qty,
                    COALESCE(sale.total_sale, 0.0) as raw_sale_qty
                FROM stock_batches sb
                JOIN items i ON i.id = sb.item_id
                LEFT JOIN units u ON u.id = i.unit_id
                LEFT JOIN companies c ON c.id = i.company_id
                LEFT JOIN (
                    SELECT
                        item_id,
                        batch_no,
                        SUM((pay_qty + COALESCE(free_qty, 0)) * CASE WHEN pack_size > 0 THEN pack_size ELSE 1 END) as total_pur
                    FROM purchase_invoice_items
                    GROUP BY item_id, batch_no
                ) pur ON pur.item_id = sb.item_id AND pur.batch_no = sb.batch_no
                LEFT JOIN (
                    SELECT
                        item_id,
                        batch_no,
                        SUM(sale_qty) as total_sale
                    FROM sales_invoice_items
                    GROUP BY item_id, batch_no
                ) sale ON sale.item_id = sb.item_id AND sale.batch_no = sb.batch_no
                WHERE sb.stock_qty > 0
                ORDER BY i.item_name COLLATE NOCASE, sb.expiry, sb.batch_no
            """
            cur = conn.execute(query)
            raw_rows = [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

        expired_rows: List[dict] = []
        for r in raw_rows:
            exp_date = get_expiry_date(r.get("expiry"))
            if not exp_date or exp_date >= today:
                continue

            # If expired_days > 0, batch expired within the last N days
            if expired_days > 0:
                cutoff = today - timedelta(days=expired_days)
                if exp_date < cutoff:
                    continue

            bal_qty = float(r.get("bal_qty") or 0.0)
            raw_pur = float(r.get("raw_pur_qty") or 0.0)
            raw_sale = float(r.get("raw_sale_qty") or 0.0)

            if raw_pur <= 0:
                sale_qty = raw_sale
                pur_qty = bal_qty + sale_qty
            else:
                sale_qty = max(0.0, raw_pur - bal_qty) if raw_sale <= 0 else raw_sale
                pur_qty = raw_pur

            p_size = r.get("pack_size")
            factor = pack_factor(p_size)
            net_rate = float(r.get("net_rate") or 0.0)
            pur_value = round((bal_qty * net_rate) / factor, 2)

            r["pur_qty"] = pur_qty
            r["sale_qty"] = sale_qty
            r["bal_qty"] = bal_qty
            r["net_rate"] = net_rate
            r["pur_value"] = pur_value
            r["expiry_formatted"] = fmt_expiry_display(r.get("expiry"))
            expired_rows.append(r)

        return expired_rows

    # ──────────────────────────────────────────────────────────────────
    # 4. Item List Report
    # ──────────────────────────────────────────────────────────────────
    @staticmethod
    def get_item_list(company_id: Optional[int] = None) -> List[dict]:
        """Fetch all item master records with Rate, MRP, and current Balance Qty."""
        conn = get_connection()
        try:
            where_clause = "WHERE i.company_id = ?" if company_id is not None else ""
            params = (company_id,) if company_id is not None else ()

            query = f"""
                SELECT
                    i.id,
                    i.item_name,
                    COALESCE(NULLIF(i.rate, 0), sb_rate.purchase_rate, 0.0) as rate,
                    COALESCE(NULLIF(i.mrp, 0), sb_rate.mrp, 0.0) as mrp,
                    COALESCE(sb_totals.total_stock, 0.0) as bal_qty
                FROM items i
                LEFT JOIN (
                    SELECT item_id, SUM(stock_qty) as total_stock
                    FROM stock_batches
                    GROUP BY item_id
                ) sb_totals ON sb_totals.item_id = i.id
                LEFT JOIN (
                    SELECT sb1.item_id, sb1.purchase_rate, sb1.mrp
                    FROM stock_batches sb1
                    INNER JOIN (
                        SELECT item_id, MAX(id) as max_id
                        FROM stock_batches
                        GROUP BY item_id
                    ) sb2 ON sb1.id = sb2.max_id
                ) sb_rate ON sb_rate.item_id = i.id
                {where_clause}
                ORDER BY i.item_name COLLATE NOCASE
            """
            cur = conn.execute(query, params)
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    # ──────────────────────────────────────────────────────────────────
    # Master Lookups
    # ──────────────────────────────────────────────────────────────────
    @staticmethod
    def get_companies() -> List[dict]:
        """Fetch all companies for dropdown filters."""
        conn = get_connection()
        try:
            cur = conn.execute(
                "SELECT id, company_name FROM companies ORDER BY company_name COLLATE NOCASE"
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

