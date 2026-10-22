"""Doctor's Reports DAO.

Provides strictly read-only data access for Doctor's Reports:
1. Doctorwise Item Sale (Aggregated sales, purchase cost, and net profit per item)
2. Doctorwise Item Sale Details (Grouped transaction details per item with patient and bill info)

Adheres strictly to the application's established costing rules:
    unit_cost = purchase_rate / pack_factor(pack_size)
    purchase_cost = sale_qty * unit_cost
    net_profit = sales_amount - purchase_cost
where purchase_rate prioritizes batch net_rate (effective landing cost) then purchase_rate then item.rate.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from core.doc_formatter import format_sales_bill_number
from database.connection import get_connection
from database.purchase_dao import pack_factor


class DoctorReportsDAO:
    """Read-only DAO for Doctor's Reports."""

    @staticmethod
    def get_doctors_list() -> List[Dict[str, Any]]:
        """Return all active doctors from doctor master for selection filters."""
        conn = get_connection()
        try:
            cur = conn.execute(
                """
                SELECT id, doctor_name, COALESCE(city, '') AS city,
                       COALESCE(specialty, '') AS specialty,
                       COALESCE(phone_no, '') AS phone_no
                FROM doctors
                ORDER BY doctor_name COLLATE NOCASE ASC
                """
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def get_all_master_items() -> List[Dict[str, Any]]:
        """Return all items from item master for the item selection tree."""
        conn = get_connection()
        try:
            cur = conn.execute(
                """
                SELECT i.id, i.item_name, COALESCE(u.unit_name, '') AS unit_name
                FROM items i
                LEFT JOIN units u ON u.id = i.unit_id
                ORDER BY i.item_name COLLATE NOCASE ASC
                """
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def get_items_for_doctor(
        from_date: str, to_date: str, doctor_id: int
    ) -> List[Dict[str, Any]]:
        """Return distinct items sold attributed to the selected doctor in the date range."""
        conn = get_connection()
        try:
            cur = conn.execute(
                """
                SELECT DISTINCT i.id, i.item_name, COALESCE(u.unit_name, '') AS unit_name
                FROM sales_invoice_items sii
                JOIN sales_invoices si ON si.id = sii.sales_invoice_id
                JOIN items i ON i.id = sii.item_id
                LEFT JOIN units u ON u.id = i.unit_id
                WHERE si.doctor_id = ?
                  AND si.sale_date >= ?
                  AND si.sale_date <= ?
                ORDER BY i.item_name COLLATE NOCASE ASC
                """,
                (doctor_id, from_date, to_date),
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def get_doctorwise_item_sale(
        from_date: str, to_date: str, doctor_id: int
    ) -> Dict[str, Any]:
        """Report 1: Doctorwise Item Sale summary.

        Aggregates sold items for the selected doctor across the date range.
        Columns:
            SrNo, Item Name, Unit, SalesQty, Sales, Purchase, NetProfit
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
                    COALESCE(NULLIF(sb.net_rate, 0), NULLIF(sb.purchase_rate, 0), i.rate, 0.0) AS effective_rate
                FROM sales_invoice_items sii
                JOIN sales_invoices si ON si.id = sii.sales_invoice_id
                JOIN items i ON i.id = sii.item_id
                LEFT JOIN units u ON u.id = i.unit_id
                LEFT JOIN stock_batches sb ON sb.id = sii.stock_batch_id
                WHERE si.doctor_id = ?
                  AND si.sale_date >= ?
                  AND si.sale_date <= ?
                ORDER BY i.item_name COLLATE NOCASE ASC, sii.id ASC
                """,
                (doctor_id, from_date, to_date),
            )
            raw_rows = [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

        grouped: Dict[int, Dict[str, Any]] = {}
        for r in raw_rows:
            item_id = r["item_id"]
            qty = float(r.get("sale_qty") or 0.0)
            amt = float(r.get("amount") or 0.0)
            rate = float(r.get("effective_rate") or 0.0)
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

    @staticmethod
    def get_doctorwise_item_sale_details(
        from_date: str,
        to_date: str,
        doctor_id: int,
        item_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Report 2: Doctorwise Item Sale Details.

        Returns sales transactions for the selected doctor and date range,
        optionally filtered by a single item_id.
        Grouped by item, with each line containing:
            SrNo, Voucher Type, Bill No, Patient Name, Address, MRP, Sales Qty, Total Sales Amount
        """
        conn = get_connection()
        try:
            params: list[Any] = [doctor_id, from_date, to_date]
            item_clause = ""
            if item_id is not None:
                item_clause = "AND sii.item_id = ?"
                params.append(item_id)

            cur = conn.execute(
                f"""
                SELECT
                    si.id AS invoice_id,
                    si.bill_no,
                    si.sale_date,
                    COALESCE(si.sale_type, 'Cash') AS voucher_type,
                    si.patient_name AS original_patient_name,
                    COALESCE(NULLIF(si.patient_name, ''), c.customer_name, 'WALKIN') AS patient_name,
                    COALESCE(NULLIF(c.address, ''), c.city, '') AS address,
                    sii.id AS item_line_id,
                    sii.item_id,
                    i.item_name,
                    COALESCE(u.unit_name, '') AS unit_name,
                    COALESCE(sii.mrp, 0.0) AS mrp,
                    COALESCE(sii.sale_qty, 0.0) AS sale_qty,
                    COALESCE(sii.amount, 0.0) AS amount
                FROM sales_invoice_items sii
                JOIN sales_invoices si ON si.id = sii.sales_invoice_id
                JOIN items i ON i.id = sii.item_id
                LEFT JOIN units u ON u.id = i.unit_id
                LEFT JOIN customers c ON c.id = si.customer_id
                WHERE si.doctor_id = ?
                  AND si.sale_date >= ?
                  AND si.sale_date <= ?
                  {item_clause}
                ORDER BY i.item_name COLLATE NOCASE ASC, si.sale_date ASC, si.id ASC, sii.id ASC
                """,
                params,
            )
            raw_lines = [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

        # Group lines by item
        groups: List[Dict[str, Any]] = []
        item_map: Dict[int, Dict[str, Any]] = {}

        for line in raw_lines:
            i_id = line["item_id"]
            if i_id not in item_map:
                item_entry: Dict[str, Any] = {
                    "item_id": i_id,
                    "item_name": line["item_name"],
                    "unit_name": line["unit_name"],
                    "lines": [],
                    "subtotal_qty": 0.0,
                    "subtotal_amount": 0.0,
                }
                item_map[i_id] = item_entry
                groups.append(item_entry)

            display_bill = format_sales_bill_number(
                line["bill_no"], patient_name=line["original_patient_name"]
            )
            qty = float(line.get("sale_qty") or 0.0)
            amt = float(line.get("amount") or 0.0)

            line_data = {
                "invoice_id": line["invoice_id"],
                "bill_no": line["bill_no"],
                "bill_no_display": display_bill,
                "sale_date": line["sale_date"],
                "voucher_type": line["voucher_type"],
                "patient_name": line["patient_name"],
                "address": line["address"],
                "mrp": float(line.get("mrp") or 0.0),
                "sale_qty": qty,
                "amount": amt,
            }
            item_map[i_id]["lines"].append(line_data)
            item_map[i_id]["subtotal_qty"] += qty
            item_map[i_id]["subtotal_amount"] += amt

        # Round subtotals
        for g in groups:
            g["subtotal_qty"] = round(g["subtotal_qty"], 2)
            g["subtotal_amount"] = round(g["subtotal_amount"], 2)

        grand_qty = round(sum(g["subtotal_qty"] for g in groups), 2)
        grand_amt = round(sum(g["subtotal_amount"] for g in groups), 2)

        summary = {
            "total_items": len(groups),
            "total_lines": len(raw_lines),
            "grand_total_qty": grand_qty,
            "grand_total_amount": grand_amt,
        }
        return {"groups": groups, "summary": summary}

