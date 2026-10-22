from __future__ import annotations

from datetime import date, datetime, timedelta
from database.connection import get_connection
from database.expiry_report_dao import parse_expiry


class StockDAO:
    """Data access for stock inventory — reads from stock_batches joined with items."""

    _BASE_QUERY = """
        SELECT
            sb.id,
            sb.item_id,
            i.item_name,
            c.company_name,
            u.unit_name,
            sb.pack_size,
            sb.batch_no,
            sb.expiry,
            sb.mrp,
            sb.purchase_rate,
            sb.net_rate,
            sb.stock_qty,
            i.reorder_stock_level
        FROM stock_batches sb
        LEFT JOIN items i ON i.id = sb.item_id
        LEFT JOIN companies c ON c.id = i.company_id
        LEFT JOIN units u ON u.id = i.unit_id
    """

    @staticmethod
    def get_all() -> list[dict]:
        conn = get_connection()
        try:
            cur = conn.execute(
                StockDAO._BASE_QUERY + " ORDER BY i.item_name, sb.batch_no"
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def search(item_name: str = "", batch_no: str = "",
               company_id: int | None = None,
               expiry_from: str = "", expiry_to: str = "",
               stock_status: str = "All",
               include_zero_stock: bool = False) -> list[dict]:
        """Unified search with optional filters. stock_status: All|In Stock|Low Stock|Out of Stock|Expired."""
        clauses: list[str] = []
        params: list = []

        if item_name:
            clauses.append("i.item_name LIKE ?")
            params.append(f"%{item_name}%")
        if batch_no:
            clauses.append("sb.batch_no LIKE ?")
            params.append(f"%{batch_no}%")
        if company_id is not None:
            clauses.append("i.company_id = ?")
            params.append(company_id)
        if expiry_from:
            clauses.append("sb.expiry >= ?")
            params.append(expiry_from)
        if expiry_to:
            clauses.append("sb.expiry <= ?")
            params.append(expiry_to)

        if stock_status == "In Stock":
            clauses.append("sb.stock_qty > i.reorder_stock_level")
        elif stock_status == "Low Stock":
            clauses.append("sb.stock_qty > 0")
            clauses.append("sb.stock_qty <= i.reorder_stock_level")
        elif stock_status == "Out of Stock":
            clauses.append("sb.stock_qty <= 0")
        elif stock_status == "Expired":
            if not include_zero_stock:
                clauses.append("sb.stock_qty > 0")

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        query = StockDAO._BASE_QUERY + where + " ORDER BY i.item_name, sb.batch_no"

        conn = get_connection()
        try:
            cur = conn.execute(query, params)
            rows = [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

        if stock_status == "Expired":
            rows = [r for r in rows if StockDAO._is_expired(r.get("expiry", ""))]

        return rows

    @staticmethod
    def get_by_item(item_id: int) -> list[dict]:
        conn = get_connection()
        try:
            cur = conn.execute(
                StockDAO._BASE_QUERY + " WHERE sb.item_id = ? ORDER BY sb.batch_no",
                (item_id,),
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def get_expiring(within_months: int = 3) -> list[dict]:
        """Return batches expiring within N months from today (including already expired)."""
        today = date.today()
        cutoff = today + timedelta(days=within_months * 30)

        all_batches = StockDAO.get_all()
        result = []
        for b in all_batches:
            exp = b.get("expiry", "")
            if not exp:
                continue
            parsed = parse_expiry(exp)
            if parsed and parsed <= cutoff:
                result.append(b)
        return result

    @staticmethod
    def get_low_stock() -> list[dict]:
        """Return batches where stock_qty > 0 and stock_qty <= reorder_stock_level."""
        conn = get_connection()
        try:
            cur = conn.execute(
                StockDAO._BASE_QUERY + " WHERE sb.stock_qty > 0 AND sb.stock_qty <= i.reorder_stock_level ORDER BY i.item_name, sb.batch_no"
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def get_out_of_stock() -> list[dict]:
        """Return batches where stock_qty <= 0."""
        conn = get_connection()
        try:
            cur = conn.execute(
                StockDAO._BASE_QUERY + " WHERE sb.stock_qty <= 0 ORDER BY i.item_name, sb.batch_no"
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def get_summary(rows: list[dict]) -> dict:
        """Compute summary statistics from a list of stock batch rows.

        ``stock_qty`` holds loose units while ``purchase_rate`` is quoted
        per pack, so value is ``qty × rate / pack_size``.
        """
        from database.purchase_dao import pack_factor
        total_batches = len(rows)
        total_qty = sum(r.get("stock_qty", 0.0) for r in rows)
        total_value = sum(
            r.get("stock_qty", 0.0) * r.get("purchase_rate", 0.0)
            / pack_factor(r.get("pack_size", ""))
            for r in rows
        )
        return {
            "total_batches": total_batches,
            "total_qty": total_qty,
            "total_value": total_value,
        }

    @staticmethod
    def get_stock_batches_for_item(item_id: int, include_zero_stock: bool = False) -> list[dict]:
        """Return stock batches for an item.
        
        Set include_zero_stock=True for return transactions (credit notes)
        where a sold-out batch can be accepted back into inventory.
        """
        conn = get_connection()
        try:
            where_clause = "WHERE item_id = ?" if include_zero_stock else "WHERE item_id = ? AND stock_qty > 0"
            cur = conn.execute(
                f"""
                SELECT id, item_id, batch_no, expiry, pack_size,
                       mrp, purchase_rate, net_rate, stock_qty
                FROM stock_batches
                {where_clause}
                ORDER BY batch_no
                """,
                (item_id,),
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def get_stock_batch_by_id(batch_id: int) -> dict | None:
        conn = get_connection()
        try:
            cur = conn.execute(
                """
                SELECT id, item_id, batch_no, expiry, pack_size,
                       mrp, purchase_rate, net_rate, stock_qty
                FROM stock_batches
                WHERE id = ?
                """,
                (batch_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    @staticmethod
    def get_batches_for_adjustment(item_id: int) -> list[dict]:
        """Return all batches for an item for stock adjustment.

        Orders batches prioritizing available stock:
        1. Active unexpired batches with stock (FEFO: earliest expiry first).
        2. Expired batches with stock (for write-off / adjustment).
        3. Zero-stock and historical batches at the bottom.

        Includes actual stored rates, tax percent from purchase history,
        calculated net rate, and eligibility tags.
        """
        conn = get_connection()
        try:
            today_iso = date.today().isoformat()
            cur = conn.execute(
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
                WHERE sb.item_id = ?
                ORDER BY
                    CASE
                        WHEN sb.stock_qty > 0 AND (sb.expiry IS NULL OR sb.expiry >= ? OR sb.expiry = '') THEN 1
                        WHEN sb.stock_qty > 0 THEN 2
                        ELSE 3
                    END ASC,
                    CASE
                        WHEN sb.stock_qty > 0 AND (sb.expiry IS NULL OR sb.expiry >= ? OR sb.expiry = '') THEN sb.expiry
                        ELSE NULL
                    END ASC,
                    sb.expiry DESC,
                    sb.batch_no ASC
                """,
                (item_id, today_iso, today_iso),
            )
            rows = [dict(r) for r in cur.fetchall()]
            for r in rows:
                if not r.get("net_rate") and r.get("purchase_rate"):
                    tax = float(r.get("tax_percent") or 0.0)
                    r["net_rate"] = round(float(r["purchase_rate"]) * (1.0 + tax / 100.0), 2)
                r["is_expired"] = StockDAO._is_expired(r.get("expiry", ""))
                r["is_zero_stock"] = (float(r.get("stock_qty") or 0.0) <= 0.0)
                r["is_eligible"] = (not r["is_expired"] and not r["is_zero_stock"])
            return rows
        finally:
            conn.close()

    @staticmethod
    def get_item_stock_summary(item_id: int) -> dict:
        """Calculate authoritative item-level stock summary under verified unit conventions.

        - All stock quantities in stock_batches, sales_invoice_items, and credit_note_items
          are stored in LOOSE UNITS (e.g. individual tablets/capsules).
        - Purchases and debit notes are stored in PACKS and converted via pack_size.
        - eligible_stock: sum of stock_qty of active (unexpired) batches with stock_qty > 0.
        - expired_stock: sum of stock_qty of expired batches with stock_qty > 0.
        - total_book_stock: sum of all stock_batches.stock_qty for the item.
        """
        batches = StockDAO.get_batches_for_adjustment(item_id)
        eligible_stock = sum(
            float(b.get("stock_qty") or 0.0) for b in batches
            if not b.get("is_expired") and float(b.get("stock_qty") or 0.0) > 0.0
        )
        expired_stock = sum(
            float(b.get("stock_qty") or 0.0) for b in batches
            if b.get("is_expired") and float(b.get("stock_qty") or 0.0) > 0.0
        )
        total_book_stock = sum(float(b.get("stock_qty") or 0.0) for b in batches)

        active_batches = [b for b in batches if not b.get("is_expired") and float(b.get("stock_qty") or 0.0) > 0.0]
        expired_batches = [b for b in batches if b.get("is_expired") and float(b.get("stock_qty") or 0.0) > 0.0]
        zero_batches = [b for b in batches if float(b.get("stock_qty") or 0.0) <= 0.0]

        return {
            "item_id": item_id,
            "eligible_stock": eligible_stock,
            "expired_stock": expired_stock,
            "total_book_stock": total_book_stock,
            "batches": batches,
            "active_batches": active_batches,
            "expired_batches": expired_batches,
            "zero_batches": zero_batches,
            "active_batch_count": len(active_batches),
            "expired_batch_count": len(expired_batches),
            "total_batch_count": len(batches),
        }

    @staticmethod
    def get_batch_ledger_movement(item_id: int, stock_batch_id: int | None = None, batch_no: str | None = None) -> dict:
        """Trace movement ledger for a batch and reconcile against stock_batches.stock_qty.

        Movement formula:
          Purchases (loose) = (pay_qty + free_qty) * pack_size
          Sales (loose) = sale_qty
          Sales Returns (loose) = return_qty from credit_note_items
          Purchase Returns (loose) = return_qty * pack_size from debit_note_items
          Stock Adjustments (loose) = adjusted_qty from stock_adjustments
          Calculated Book Stock = Purchases - Sales + Sales Returns - Purchase Returns + Adjustments
        """
        from database.purchase_dao import pack_factor
        conn = get_connection()
        try:
            batch = None
            if stock_batch_id:
                cur = conn.execute("SELECT * FROM stock_batches WHERE id = ?", (stock_batch_id,))
                r = cur.fetchone()
                if r:
                    batch = dict(r)
            if not batch and batch_no:
                cur = conn.execute("SELECT * FROM stock_batches WHERE item_id = ? AND batch_no = ?", (item_id, batch_no))
                r = cur.fetchone()
                if r:
                    batch = dict(r)

            b_id = batch["id"] if batch else stock_batch_id
            b_no = (batch.get("batch_no") if batch else batch_no) or ""
            p_size = batch.get("pack_size") if batch else ""
            p_factor = pack_factor(p_size)

            # Purchases (loose)
            p_cur = conn.execute(
                """
                SELECT SUM((pay_qty + COALESCE(free_qty, 0)) * ?)
                FROM purchase_invoice_items
                WHERE item_id = ? AND batch_no = ?
                """,
                (p_factor, item_id, b_no),
            )
            pur_loose = float(p_cur.fetchone()[0] or 0.0)

            # Sales (loose)
            s_cur = conn.execute(
                """
                SELECT SUM(sale_qty)
                FROM sales_invoice_items
                WHERE item_id = ? AND (stock_batch_id = ? OR batch_no = ?)
                """,
                (item_id, b_id, b_no),
            )
            sale_loose = float(s_cur.fetchone()[0] or 0.0)

            # Credit Notes / Sales returns (loose)
            cn_cur = conn.execute(
                """
                SELECT SUM(return_qty)
                FROM credit_note_items
                WHERE item_id = ? AND (stock_batch_id = ? OR batch_no = ?)
                """,
                (item_id, b_id, b_no),
            )
            cn_loose = float(cn_cur.fetchone()[0] or 0.0)

            # Debit Notes / Purchase returns (respects is_pack_qty flag)
            dn_cur = conn.execute(
                """
                SELECT SUM(
                    CASE
                        WHEN is_pack_qty = 1 THEN (return_qty + COALESCE(free_qty, 0)) * ?
                        ELSE (return_qty + COALESCE(free_qty, 0))
                    END
                )
                FROM debit_note_items
                WHERE item_id = ? AND (stock_batch_id = ? OR batch_no = ?)
                """,
                (p_factor, item_id, b_id, b_no),
            )
            dn_loose = float(dn_cur.fetchone()[0] or 0.0)

            # Stock Adjustments (loose)
            adj_cur = conn.execute(
                """
                SELECT SUM(adjusted_qty)
                FROM stock_adjustments
                WHERE item_id = ? AND (stock_batch_id = ? OR batch_no = ?)
                """,
                (item_id, b_id, b_no),
            )
            adj_loose = float(adj_cur.fetchone()[0] or 0.0)

            calc_stock = pur_loose - sale_loose + cn_loose - dn_loose + adj_loose
            stored_stock = float(batch.get("stock_qty") or 0.0) if batch else 0.0

            return {
                "item_id": item_id,
                "batch_id": b_id,
                "batch_no": b_no,
                "pack_factor": p_factor,
                "purchased_loose": pur_loose,
                "sold_loose": sale_loose,
                "sales_returns_loose": cn_loose,
                "purchase_returns_loose": dn_loose,
                "adjustments_loose": adj_loose,
                "calculated_book_stock": calc_stock,
                "stored_stock": stored_stock,
                "variance": stored_stock - calc_stock,
            }
        finally:
            conn.close()

    @staticmethod
    def _is_expired(expiry: str) -> bool:
        """Check if expiry date (ISO YYYY-MM-DD or MM/YY) is before today."""
        if not expiry:
            return False
        parsed = parse_expiry(expiry)
        if not parsed:
            return False
        return parsed < date.today()

    @staticmethod
    def get_demand_order_items() -> list[dict]:
        """Identify items whose current stock is at or below their configured reorder level.

        Returns items where reorder_stock_level > 0 and current_stock <= reorder_stock_level,
        with associated suppliers and contact numbers from purchase history.
        Each associated supplier is listed without duplicating item stock quantities.
        """
        conn = get_connection()
        try:
            cur = conn.execute(
                """
                WITH item_stocks AS (
                    SELECT
                        i.id AS item_id,
                        i.item_name,
                        COALESCE(u.unit_name, '') AS unit_name,
                        COALESCE(SUM(sb.stock_qty), 0) AS current_stock,
                        i.reorder_stock_level
                    FROM items i
                    LEFT JOIN units u ON u.id = i.unit_id
                    LEFT JOIN stock_batches sb ON sb.item_id = i.id
                    WHERE i.reorder_stock_level > 0
                    GROUP BY i.id
                    HAVING current_stock <= i.reorder_stock_level
                ),
                item_suppliers AS (
                    SELECT DISTINCT
                        pii.item_id,
                        s.id AS supplier_id,
                        s.supplier_name,
                        COALESCE(s.contact_no, '') AS contact_no
                    FROM purchase_invoice_items pii
                    JOIN purchase_invoices pi ON pi.id = pii.purchase_invoice_id
                    JOIN suppliers s ON s.id = pi.supplier_id
                )
                SELECT
                    s_item.item_id,
                    s_item.item_name,
                    s_item.unit_name,
                    s_item.current_stock,
                    s_item.reorder_stock_level,
                    COALESCE(s_sup.supplier_name, '-') AS supplier_name,
                    COALESCE(s_sup.contact_no, '-') AS contact_no
                FROM item_stocks s_item
                LEFT JOIN item_suppliers s_sup ON s_sup.item_id = s_item.item_id
                ORDER BY s_item.item_name, s_sup.supplier_name
                """
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

