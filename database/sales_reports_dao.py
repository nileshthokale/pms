"""Sales Reports DAO — Phase 6.

Read-only data access for all 6 Pharma-WINNER Sales Reports:
1. Daily Billwise Sales
2. Daily Itemwise Sales
3. Companywise Sales
4. Itemwise Sales
5. Daily Profit Calculation
6. Daily Profit Itemwise

Strictly read-only; aggregates stored source transactions without modifying
or recalculating ledger postings or stock.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from database.connection import get_connection
from database.purchase_dao import pack_factor


class SalesReportsDAO:
    """Read-only DAO for the 6 sales report types."""

    # ── Master filter lookups ──────────────────────────────────────────
    @staticmethod
    def get_filter_companies() -> List[Dict[str, Any]]:
        conn = get_connection()
        try:
            cur = conn.execute(
                """
                SELECT id, company_name, COALESCE(short_name, '') AS short_name
                FROM companies
                ORDER BY company_name COLLATE NOCASE ASC
                """
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def get_filter_items() -> List[Dict[str, Any]]:
        conn = get_connection()
        try:
            cur = conn.execute(
                """
                SELECT
                    i.id,
                    i.item_name,
                    COALESCE(u.unit_name, '') AS unit_name,
                    COALESCE(c.short_name, '') AS company_code,
                    COALESCE(c.company_name, '') AS company_name
                FROM items i
                LEFT JOIN units u ON u.id = i.unit_id
                LEFT JOIN companies c ON c.id = i.company_id
                ORDER BY i.item_name COLLATE NOCASE ASC
                """
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    # ── 1. Daily Billwise Sales ────────────────────────────────────────
    @staticmethod
    def get_daily_billwise_sales(sale_date: str) -> Dict[str, Any]:
        """Unique bills for a single date with bill-level totals.
        
        Returns:
            {"rows": [...], "summary": {total_bills, total_discount, total_bill_amount}}
        """
        conn = get_connection()
        try:
            cur = conn.execute(
                """
                SELECT
                    si.id AS invoice_id,
                    si.bill_no,
                    si.patient_name AS original_patient_name,
                    si.sale_date,
                    COALESCE(si.sale_time, '') AS sale_time,
                    COALESCE(si.sale_type, 'Cash') AS voucher_type,
                    COALESCE(NULLIF(si.patient_name, ''), c.customer_name, 'WALKIN') AS patient_name,
                    si.bill_no AS voucher_no,
                    COALESCE(si.discount, 0.0) AS discount,
                    COALESCE(si.net_amount, 0.0) AS bill_amount
                FROM sales_invoices si
                LEFT JOIN customers c ON c.id = si.customer_id
                WHERE si.sale_date = ?
                ORDER BY si.id ASC
                """,
                (sale_date,),
            )
            rows = [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

        total_discount = sum(float(r.get("discount") or 0.0) for r in rows)
        total_bill_amount = sum(float(r.get("bill_amount") or 0.0) for r in rows)

        summary = {
            "total_bills": len(rows),
            "total_discount": round(total_discount, 2),
            "total_bill_amount": round(total_bill_amount, 2),
        }
        return {"rows": rows, "summary": summary}

    # ── 2. Daily Itemwise Sales ────────────────────────────────────────
    @staticmethod
    def get_daily_itemwise_sales(sale_date: str) -> Dict[str, Any]:
        """All item lines for a single date.
        
        Note:
            Bill amount belongs to the parent invoice and may repeat across lines.
            Line amount is the actual sold item amount.
        """
        conn = get_connection()
        try:
            cur = conn.execute(
                """
                SELECT
                    si.id AS invoice_id,
                    si.bill_no,
                    si.patient_name AS patient_name,
                    COALESCE(si.sale_type, 'Cash') AS voucher_type,
                    COALESCE(i.item_name, 'Unknown Item') AS item_name,
                    COALESCE(sii.mrp, 0.0) AS mrp,
                    COALESCE(sii.sale_qty, 0.0) AS quantity,
                    COALESCE(sii.amount, 0.0) AS amount,
                    COALESCE(sii.batch_no, '') AS batch_no,
                    COALESCE(sii.expiry, '') AS expiry,
                    COALESCE(sii.discount_amount, 0.0) AS discount,
                    COALESCE(si.net_amount, 0.0) AS bill_amount
                FROM sales_invoices si
                JOIN sales_invoice_items sii ON sii.sales_invoice_id = si.id
                LEFT JOIN items i ON i.id = sii.item_id
                WHERE si.sale_date = ?
                ORDER BY si.id ASC, sii.id ASC
                """,
                (sale_date,),
            )
            rows = [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

        total_qty = sum(float(r.get("quantity") or 0.0) for r in rows)
        total_amount = sum(float(r.get("amount") or 0.0) for r in rows)
        total_discount = sum(float(r.get("discount") or 0.0) for r in rows)

        # Unique bills for bill_amount calculation
        unique_bills: Dict[int, float] = {}
        for r in rows:
            inv_id = r["invoice_id"]
            if inv_id not in unique_bills:
                unique_bills[inv_id] = float(r.get("bill_amount") or 0.0)

        total_bill_amount = sum(unique_bills.values())

        summary = {
            "total_lines": len(rows),
            "total_qty": round(total_qty, 2),
            "total_amount": round(total_amount, 2),
            "total_discount": round(total_discount, 2),
            "total_bills": len(unique_bills),
            "total_bill_amount": round(total_bill_amount, 2),
        }
        return {"rows": rows, "summary": summary}

    # ── 3. Companywise Sales ───────────────────────────────────────────
    @staticmethod
    def get_companywise_sales(
        from_date: str, to_date: str, company_id: int
    ) -> Dict[str, Any]:
        """Item & batch sales for a company in date range."""
        conn = get_connection()
        try:
            cur = conn.execute(
                """
                SELECT
                    i.id AS item_id,
                    i.item_name,
                    COALESCE(u.unit_name, '') AS unit_name,
                    COALESCE(NULLIF(sii.pack_size, ''), i.pack_size, '') AS pack_size,
                    COALESCE(sii.batch_no, '') AS batch_no,
                    COALESCE(sii.mrp, 0.0) AS mrp,
                    SUM(COALESCE(sii.sale_qty, 0.0)) AS sales_qty,
                    SUM(COALESCE(sii.amount, 0.0)) AS amount
                FROM sales_invoice_items sii
                JOIN sales_invoices si ON si.id = sii.sales_invoice_id
                JOIN items i ON i.id = sii.item_id
                LEFT JOIN units u ON u.id = i.unit_id
                WHERE i.company_id = ?
                  AND si.sale_date >= ?
                  AND si.sale_date <= ?
                GROUP BY i.id, i.item_name, u.unit_name, sii.batch_no, sii.mrp, COALESCE(NULLIF(sii.pack_size, ''), i.pack_size, '')
                ORDER BY i.item_name COLLATE NOCASE ASC, sii.batch_no ASC
                """,
                (company_id, from_date, to_date),
            )
            rows = [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

        total_qty = sum(float(r.get("sales_qty") or 0.0) for r in rows)
        total_amount = sum(float(r.get("amount") or 0.0) for r in rows)
        distinct_items = len({r["item_id"] for r in rows})

        summary = {
            "total_records": len(rows),
            "distinct_items": distinct_items,
            "total_qty": round(total_qty, 2),
            "total_amount": round(total_amount, 2),
        }
        return {"rows": rows, "summary": summary}

    # ── 4. Itemwise Sales ──────────────────────────────────────────────
    @staticmethod
    def get_itemwise_sales(
        from_date: str, to_date: str, item_id: int
    ) -> Dict[str, Any]:
        """Chronological sales transactions for a single item in date range."""
        conn = get_connection()
        try:
            cur = conn.execute(
                """
                SELECT
                    si.sale_date,
                    COALESCE(si.sale_type, 'Cash') AS voucher_type,
                    si.bill_no,
                    si.patient_name AS original_patient_name,
                    COALESCE(NULLIF(si.patient_name, ''), c.customer_name, 'WALKIN') AS patient_name,
                    COALESCE(sii.batch_no, '') AS batch_no,
                    COALESCE(sii.mrp, 0.0) AS mrp,
                    COALESCE(sii.sale_qty, 0.0) AS quantity,
                    COALESCE(sii.amount, 0.0) AS amount
                FROM sales_invoice_items sii
                JOIN sales_invoices si ON si.id = sii.sales_invoice_id
                LEFT JOIN customers c ON c.id = si.customer_id
                WHERE sii.item_id = ?
                  AND si.sale_date >= ?
                  AND si.sale_date <= ?
                ORDER BY si.sale_date ASC, si.id ASC, sii.id ASC
                """,
                (item_id, from_date, to_date),
            )
            rows = [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

        total_qty = sum(float(r.get("quantity") or 0.0) for r in rows)
        total_amount = sum(float(r.get("amount") or 0.0) for r in rows)

        summary = {
            "total_records": len(rows),
            "total_qty": round(total_qty, 2),
            "total_amount": round(total_amount, 2),
        }
        return {"rows": rows, "summary": summary}

    # ── 5. Daily Profit Calculation ────────────────────────────────────
    @staticmethod
    def get_daily_profit_calculation(
        from_date: str, to_date: str
    ) -> Dict[str, Any]:
        """Daily cash and trading profit calculation across the given date range.
        
        Columns:
            Voucher Date, Cash Receipt, Cash Sales, Total Cash Received,
            Cash Payment, Cash Sales Return, Net Cash Received,
            Bank Payment, Credit Sales, Net Sales, Net Purchase, Net Profit
        """
        conn = get_connection()
        try:
            # Collect all relevant dates in the range
            dates_query = """
                SELECT DISTINCT d FROM (
                    SELECT sale_date AS d FROM sales_invoices WHERE sale_date >= ? AND sale_date <= ?
                    UNION
                    SELECT voucher_date AS d FROM purchase_invoices WHERE voucher_date >= ? AND voucher_date <= ?
                    UNION
                    SELECT receipt_date AS d FROM customer_receipts WHERE receipt_date >= ? AND receipt_date <= ?
                    UNION
                    SELECT payment_date AS d FROM supplier_payments WHERE payment_date >= ? AND payment_date <= ?
                    UNION
                    SELECT voucher_date AS d FROM credit_notes WHERE voucher_date >= ? AND voucher_date <= ?
                ) ORDER BY d ASC
            """
            cur = conn.execute(
                dates_query,
                (from_date, to_date, from_date, to_date, from_date, to_date, from_date, to_date, from_date, to_date),
            )
            distinct_dates = [r[0] for r in cur.fetchall() if r[0]]

            # If no transaction dates found and from_date == to_date, include the single date with 0s
            if not distinct_dates and from_date == to_date:
                distinct_dates = [from_date]

            rows: List[Dict[str, Any]] = []
            for d in distinct_dates:
                # 1. Cash Receipt: customer receipts in Cash mode
                cr = conn.execute(
                    "SELECT COALESCE(SUM(amount), 0.0) FROM customer_receipts WHERE receipt_date = ? AND receipt_mode = 'Cash'",
                    (d,),
                ).fetchone()[0]

                # 2. Cash Sales: sales invoices with sale_type = 'Cash'
                cs = conn.execute(
                    "SELECT COALESCE(SUM(net_amount), 0.0) FROM sales_invoices WHERE sale_date = ? AND sale_type = 'Cash'",
                    (d,),
                ).fetchone()[0]

                # 3. Total Cash Received: Cash Receipt + Cash Sales
                tot_cr = cr + cs

                # 4. Cash Payment: supplier payments in Cash mode
                cp = conn.execute(
                    "SELECT COALESCE(SUM(amount), 0.0) FROM supplier_payments WHERE payment_date = ? AND payment_mode = 'Cash'",
                    (d,),
                ).fetchone()[0]

                # 5. Cash Sales Return: credit notes on that date
                csr = conn.execute(
                    "SELECT COALESCE(SUM(total_amount), 0.0) FROM credit_notes WHERE voucher_date = ?",
                    (d,),
                ).fetchone()[0]

                # 6. Net Cash Received: Total Cash Received - Cash Payment - Cash Sales Return
                net_cr = tot_cr - cp - csr

                # 7. Bank Payment: supplier payments in non-Cash mode (Bank/Cheque)
                bp = conn.execute(
                    "SELECT COALESCE(SUM(amount), 0.0) FROM supplier_payments WHERE payment_date = ? AND payment_mode != 'Cash'",
                    (d,),
                ).fetchone()[0]

                # 8. Credit Sales: sales invoices with sale_type != 'Cash'
                crs = conn.execute(
                    "SELECT COALESCE(SUM(net_amount), 0.0) FROM sales_invoices WHERE sale_date = ? AND sale_type != 'Cash'",
                    (d,),
                ).fetchone()[0]

                # 9. Net Sales: all sales invoices on that date
                ns = conn.execute(
                    "SELECT COALESCE(SUM(net_amount), 0.0) FROM sales_invoices WHERE sale_date = ?",
                    (d,),
                ).fetchone()[0]

                # 10. Net Purchase: purchase invoices on that date
                np = conn.execute(
                    "SELECT COALESCE(SUM(net_amount), 0.0) FROM purchase_invoices WHERE voucher_date = ?",
                    (d,),
                ).fetchone()[0]

                # 11. Net Profit: Net Sales - Net Purchase
                nprof = ns - np

                rows.append({
                    "voucher_date": d,
                    "cash_receipt": round(cr, 2),
                    "cash_sales": round(cs, 2),
                    "total_cash_received": round(tot_cr, 2),
                    "cash_payment": round(cp, 2),
                    "cash_sales_return": round(csr, 2),
                    "net_cash_received": round(net_cr, 2),
                    "bank_payment": round(bp, 2),
                    "credit_sales": round(crs, 2),
                    "net_sales": round(ns, 2),
                    "net_purchase": round(np, 2),
                    "net_profit": round(nprof, 2),
                })
        finally:
            conn.close()

        totals = {
            "cash_receipt": round(sum(r["cash_receipt"] for r in rows), 2),
            "cash_sales": round(sum(r["cash_sales"] for r in rows), 2),
            "total_cash_received": round(sum(r["total_cash_received"] for r in rows), 2),
            "cash_payment": round(sum(r["cash_payment"] for r in rows), 2),
            "cash_sales_return": round(sum(r["cash_sales_return"] for r in rows), 2),
            "net_cash_received": round(sum(r["net_cash_received"] for r in rows), 2),
            "bank_payment": round(sum(r["bank_payment"] for r in rows), 2),
            "credit_sales": round(sum(r["credit_sales"] for r in rows), 2),
            "net_sales": round(sum(r["net_sales"] for r in rows), 2),
            "net_purchase": round(sum(r["net_purchase"] for r in rows), 2),
            "net_profit": round(sum(r["net_profit"] for r in rows), 2),
        }
        return {"rows": rows, "summary": totals}

    # ── 6. Daily Profit Itemwise ───────────────────────────────────────
    @staticmethod
    def get_daily_profit_itemwise(
        from_date: str, to_date: str
    ) -> Dict[str, Any]:
        """Itemwise sales margin (Sales Amount vs Purchase Cost).
        
        Calculates item sales value and cost of goods sold based on the batch
        purchase rate normalized by pack factor:
            unit_cost = purchase_rate / pack_factor(pack_size)
            purchase_cost = sale_qty * unit_cost
            net_profit = sales_amount - purchase_cost
        """
        conn = get_connection()
        try:
            cur = conn.execute(
                """
                SELECT
                    i.id AS item_id,
                    i.item_name,
                    COALESCE(u.unit_name, '') AS unit_name,
                    COALESCE(NULLIF(sii.pack_size, ''), i.pack_size, '1') AS pack_size,
                    sii.sale_qty,
                    sii.amount,
                    COALESCE(NULLIF(sb.purchase_rate, 0), NULLIF(sb.net_rate, 0), i.rate, 0.0) AS purchase_rate
                FROM sales_invoice_items sii
                JOIN sales_invoices si ON si.id = sii.sales_invoice_id
                JOIN items i ON i.id = sii.item_id
                LEFT JOIN units u ON u.id = i.unit_id
                LEFT JOIN stock_batches sb ON sb.id = sii.stock_batch_id
                WHERE si.sale_date >= ? AND si.sale_date <= ?
                ORDER BY i.item_name COLLATE NOCASE ASC
                """,
                (from_date, to_date),
            )
            raw_rows = [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

        # Group and compute by item
        grouped: Dict[int, Dict[str, Any]] = {}
        for r in raw_rows:
            item_id = r["item_id"]
            qty = float(r.get("sale_qty") or 0.0)
            amt = float(r.get("amount") or 0.0)
            rate = float(r.get("purchase_rate") or 0.0)
            factor = pack_factor(r.get("pack_size", "1"))
            unit_cost = (rate / factor) if factor > 0 else rate
            cost = qty * unit_cost

            if item_id not in grouped:
                grouped[item_id] = {
                    "item_id": item_id,
                    "item_name": r["item_name"],
                    "unit_name": r["unit_name"],
                    "sales_qty": 0.0,
                    "sales_amount": 0.0,
                    "purchase_cost": 0.0,
                }
            grouped[item_id]["sales_qty"] += qty
            grouped[item_id]["sales_amount"] += amt
            grouped[item_id]["purchase_cost"] += cost

        rows: List[Dict[str, Any]] = []
        for g in sorted(grouped.values(), key=lambda x: str(x["item_name"]).upper()):
            sales_amt = round(g["sales_amount"], 2)
            purch_cost = round(g["purchase_cost"], 2)
            profit = round(sales_amt - purch_cost, 2)
            rows.append({
                "item_id": g["item_id"],
                "item_name": g["item_name"],
                "unit_name": g["unit_name"],
                "sales_qty": round(g["sales_qty"], 2),
                "sales": sales_amt,
                "purchase": purch_cost,
                "net_profit": profit,
            })

        summary = {
            "total_items": len(rows),
            "total_qty": round(sum(r["sales_qty"] for r in rows), 2),
            "total_sales": round(sum(r["sales"] for r in rows), 2),
            "total_purchase": round(sum(r["purchase"] for r in rows), 2),
            "total_net_profit": round(sum(r["net_profit"] for r in rows), 2),
        }
        return {"rows": rows, "summary": summary}

    # ── 7. Daily Profit Calculation (Unit Cost with Free Qty & Discount) ─
    @staticmethod
    def get_daily_profit_cost_calculation(
        from_date: str,
        to_date: str,
        item_id: Optional[int] = None,
        company_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Calculates actual medicine purchase cost per tablet/unit accounting for
        free quantities and purchase discounts, then computes profit on quantities sold.

        Columns:
            1. Sr. No.
            2. Medicine Name
            3. Company Name
            4. Batch Number
            5. Total Quantity Sold
            6. Actual Selling Rate
            7. Purchase Rate
            8. Free Quantity
            9. Purchase Discount
            10. Actual Net Purchase Cost Per Tablet
            11. Total Net Sales
            12. Total Purchase Cost of Sold Quantity
            13. Total Profit
        """
        conn = get_connection()
        try:
            query = """
                SELECT
                    sii.item_id,
                    i.item_name,
                    COALESCE(c.company_name, '') AS company_name,
                    COALESCE(sii.batch_no, sb.batch_no, '') AS batch_no,
                    COALESCE(NULLIF(sii.pack_size, ''), sb.pack_size, i.pack_size, '1') AS pack_size,
                    sii.sale_qty,
                    sii.amount AS sales_amount,
                    COALESCE(sb.purchase_rate, 0.0) AS sb_purchase_rate,
                    COALESCE(sb.net_rate, 0.0) AS sb_net_rate,
                    COALESCE(i.rate, 0.0) AS item_rate
                FROM sales_invoice_items sii
                JOIN sales_invoices si ON si.id = sii.sales_invoice_id
                JOIN items i ON i.id = sii.item_id
                LEFT JOIN companies c ON c.id = i.company_id
                LEFT JOIN stock_batches sb ON sb.id = sii.stock_batch_id
                WHERE si.sale_date >= ? AND si.sale_date <= ?
            """
            params: List[Any] = [from_date, to_date]
            if item_id:
                query += " AND sii.item_id = ?"
                params.append(item_id)
            if company_id:
                query += " AND i.company_id = ?"
                params.append(company_id)

            query += " ORDER BY i.item_name COLLATE NOCASE ASC, sii.batch_no ASC"
            cur = conn.execute(query, tuple(params))
            sales_rows = [dict(r) for r in cur.fetchall()]

            # Also check sales returns (credit notes) in this date range
            cn_query = """
                SELECT
                    cni.item_id,
                    COALESCE(cni.batch_no, '') AS batch_no,
                    SUM(COALESCE(cni.return_qty, 0.0)) AS return_qty,
                    SUM(COALESCE(cni.amount, 0.0)) AS return_amount
                FROM credit_note_items cni
                JOIN credit_notes cn ON cn.id = cni.credit_note_id
                WHERE cn.voucher_date >= ? AND cn.voucher_date <= ?
            """
            cn_params: List[Any] = [from_date, to_date]
            if item_id:
                cn_query += " AND cni.item_id = ?"
                cn_params.append(item_id)
            cn_query += " GROUP BY cni.item_id, cni.batch_no"
            cn_cur = conn.execute(cn_query, tuple(cn_params))
            returns_map: Dict[Tuple[int, str], Dict[str, float]] = {}
            for r in cn_cur.fetchall():
                key = (r["item_id"], r["batch_no"])
                returns_map[key] = {
                    "return_qty": float(r["return_qty"] or 0.0),
                    "return_amount": float(r["return_amount"] or 0.0),
                }

            # Group sales by (item_id, batch_no)
            grouped: Dict[Tuple[int, str], Dict[str, Any]] = {}
            for r in sales_rows:
                key = (r["item_id"], r["batch_no"])
                if key not in grouped:
                    grouped[key] = {
                        "item_id": r["item_id"],
                        "item_name": r["item_name"],
                        "company_name": r["company_name"],
                        "batch_no": r["batch_no"],
                        "pack_size": r["pack_size"],
                        "sb_purchase_rate": r["sb_purchase_rate"],
                        "sb_net_rate": r["sb_net_rate"],
                        "item_rate": r["item_rate"],
                        "sale_qty": 0.0,
                        "sales_amount": 0.0,
                    }
                grouped[key]["sale_qty"] += float(r.get("sale_qty") or 0.0)
                grouped[key]["sales_amount"] += float(r.get("sales_amount") or 0.0)

            # Deduct returns if any
            for key, ret in returns_map.items():
                if key in grouped:
                    grouped[key]["sale_qty"] = max(0.0, grouped[key]["sale_qty"] - ret["return_qty"])
                    grouped[key]["sales_amount"] = max(0.0, grouped[key]["sales_amount"] - ret["return_amount"])

            # Compute purchase cost and profit for each group
            rows: List[Dict[str, Any]] = []
            sr_no = 1
            for key in sorted(grouped.keys(), key=lambda k: (grouped[k]["item_name"].upper(), grouped[k]["batch_no"].upper())):
                g = grouped[key]
                sold_qty = round(g["sale_qty"], 2)
                net_sales = round(g["sales_amount"], 2)
                if sold_qty <= 0:
                    continue

                actual_selling_rate = round(net_sales / sold_qty, 2) if sold_qty > 0 else 0.0

                # Look up purchase invoice items for this batch
                p_cur = conn.execute(
                    """
                    SELECT
                        pii.pay_qty,
                        pii.free_qty,
                        pii.rate,
                        pii.discount,
                        pii.purchase_rate,
                        pii.net_rate,
                        COALESCE(NULLIF(pii.pack_size, ''), ?) AS pack_size
                    FROM purchase_invoice_items pii
                    JOIN purchase_invoices pi ON pi.id = pii.purchase_invoice_id
                    WHERE pii.item_id = ? AND pii.batch_no = ?
                    ORDER BY pi.voucher_date DESC, pii.id DESC
                    """,
                    (g["pack_size"], g["item_id"], g["batch_no"]),
                )
                p_records = [dict(pr) for pr in p_cur.fetchall()]

                factor = pack_factor(g.get("pack_size") or "1")

                if p_records:
                    total_gross = 0.0
                    total_discount_amt = 0.0
                    total_received_units = 0.0
                    total_pay_units = 0.0
                    total_free_units = 0.0

                    for pr in p_records:
                        p_factor = pack_factor(pr.get("pack_size") or g.get("pack_size") or "1")
                        pay_q = float(pr.get("pay_qty") or 0.0)
                        free_q = float(pr.get("free_qty") or 0.0)
                        pr_rate = float(pr.get("rate") or 0.0)
                        if pr_rate == 0.0:
                            pr_rate = float(pr.get("purchase_rate") or 0.0)
                        disc_pct = float(pr.get("discount") or 0.0)

                        gross = pay_q * pr_rate
                        disc_val = gross * (disc_pct / 100.0)

                        total_gross += gross
                        total_discount_amt += disc_val
                        total_received_units += (pay_q + free_q) * p_factor
                        total_pay_units += pay_q * p_factor
                        total_free_units += free_q * p_factor

                    if total_received_units > 0:
                        net_purchase = total_gross - total_discount_amt
                        actual_cost_per_tablet = round(net_purchase / total_received_units, 2)
                        purch_rate = round(total_gross / total_pay_units, 2) if total_pay_units > 0 else round(pr_rate / p_factor, 2)
                        purch_discount = round((total_discount_amt / total_gross) * 100.0, 2) if total_gross > 0 else 0.0
                        free_quantity = round(total_free_units, 2)
                    else:
                        pr_rate = float(p_records[0].get("rate") or p_records[0].get("purchase_rate") or 0.0)
                        purch_rate = round(pr_rate / factor, 2) if factor > 0 else round(pr_rate, 2)
                        actual_cost_per_tablet = purch_rate
                        purch_discount = 0.0
                        free_quantity = 0.0
                else:
                    # Fallback to stock_batch / item rate
                    sb_rate = float(g.get("sb_net_rate") or g.get("sb_purchase_rate") or g.get("item_rate") or 0.0)
                    purch_rate = round(sb_rate / factor, 2) if factor > 0 else round(sb_rate, 2)
                    actual_cost_per_tablet = purch_rate
                    purch_discount = 0.0
                    free_quantity = 0.0

                total_purch_cost = round(sold_qty * actual_cost_per_tablet, 2)
                profit = round(net_sales - total_purch_cost, 2)

                rows.append({
                    "sr_no": sr_no,
                    "item_id": g["item_id"],
                    "item_name": g["item_name"],
                    "company_name": g["company_name"],
                    "batch_no": g["batch_no"],
                    "total_sold_qty": sold_qty,
                    "actual_selling_rate": actual_selling_rate,
                    "purchase_rate": purch_rate,
                    "free_qty": free_quantity,
                    "purchase_discount": purch_discount,
                    "actual_cost_per_tablet": actual_cost_per_tablet,
                    "total_net_sales": net_sales,
                    "total_purchase_cost": total_purch_cost,
                    "total_profit": profit,
                })
                sr_no += 1

            summary = {
                "total_records": len(rows),
                "total_sold_qty": round(sum(r["total_sold_qty"] for r in rows), 2),
                "total_net_sales": round(sum(r["total_net_sales"] for r in rows), 2),
                "total_purchase_cost": round(sum(r["total_purchase_cost"] for r in rows), 2),
                "total_profit": round(sum(r["total_profit"] for r in rows), 2),
            }
            return {"rows": rows, "summary": summary}
        finally:
            conn.close()

