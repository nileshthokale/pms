from __future__ import annotations

from database.connection import get_connection


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
               stock_status: str = "All") -> list[dict]:
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
            # Expiry in MM/YY format — compare against today
            # We do the comparison in Python after fetching to keep the query simple,
            # but we still filter out obviously non-expired rows at SQL level when possible.
            # For robustness we fetch all and filter expired in Python.
            pass  # handled below after query

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
        """Return batches expiring within N months from today."""
        from datetime import datetime, timedelta
        today = datetime.now()
        cutoff = today + timedelta(days=within_months * 30)
        cutoff_str = cutoff.strftime("%m/%y")

        all_batches = StockDAO.get_all()
        result = []
        for b in all_batches:
            exp = b.get("expiry", "")
            if exp and StockDAO._is_expired(exp):
                # Already expired
                result.append(b)
            elif exp:
                # Check if expiring within N months
                try:
                    parts = exp.split("/")
                    exp_month, exp_year = int(parts[0]), int(parts[1])
                    exp_date = datetime(2000 + exp_year, exp_month, 1)
                    if exp_date <= cutoff:
                        result.append(b)
                except (ValueError, IndexError):
                    pass
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
        """Compute summary statistics from a list of stock batch rows."""
        total_batches = len(rows)
        total_qty = sum(r.get("stock_qty", 0.0) for r in rows)
        total_value = sum(
            r.get("stock_qty", 0.0) * r.get("purchase_rate", 0.0)
            for r in rows
        )
        return {
            "total_batches": total_batches,
            "total_qty": total_qty,
            "total_value": total_value,
        }

    @staticmethod
    def get_stock_batches_for_item(item_id: int) -> list[dict]:
        conn = get_connection()
        try:
            cur = conn.execute(
                """
                SELECT id, item_id, batch_no, expiry, pack_size,
                       mrp, purchase_rate, stock_qty
                FROM stock_batches
                WHERE item_id = ? AND stock_qty > 0
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
                       mrp, purchase_rate, stock_qty
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
    def _is_expired(expiry: str) -> bool:
        """Check if expiry in MM/YY format is before today."""
        if not expiry:
            return False
        try:
            from datetime import datetime
            parts = expiry.strip().split("/")
            month, year = int(parts[0]), int(parts[1])
            exp_date = datetime(2000 + year, month, 1)
            return exp_date < datetime.now()
        except (ValueError, IndexError):
            return False
