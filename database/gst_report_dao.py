"""GST Report DAO — Phase 5E.

Read-only report over the application's **purchase GST data** stored in
purchase_invoices + purchase_invoice_items. Sales schema does not contain
reliable GST fields; Credit/Debit Notes also lack GST fields.

Therefore this report shows **Purchase GST only**. No GST values are
invented or recalculated — the report aggregates the stored values.

Date behavior (same as the existing Purchase Report):
    Purchase filters on `voucher_date` (the purchase transaction date),
    inclusive: from_date <= voucher_date <= to_date.
    `invoice_date` is displayed but not used for filtering.

Stored purchase calculation (as recorded by PurchaseDAO, shown NOT recalculated):
    line.amount     = (pay_qty + free_qty) × rate
    line.gst_amount = round(line.amount × gst_percent / 100)
    header.gst_amount = Σ line.gst_amount
    header.net_amount = total + gst_amount − bill_discount − debit_note
                        + other_amount + round_off

Taxable amount for the report uses the stored `line.amount` field.
"""

from __future__ import annotations

from typing import Optional

from database.connection import get_connection


class GSTReportDAO:
    """Read-only GST Report over purchase source documents."""

    # ── Purchase GST detail rows ────────────────────────────────────
    @staticmethod
    def get_purchase_gst_report(
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        supplier_id: Optional[int] = None,
        item_id: Optional[int] = None,
        company_id: Optional[int] = None,
        gst_percent: Optional[float] = None,
        invoice_no: Optional[str] = None,
        voucher_no: Optional[str] = None,
    ) -> dict:
        """Purchase GST report rows + summary for the given filters.

        Returns:
            {"rows": [ {voucher_no, voucher_date, invoice_no, invoice_date,
                        supplier_name, item_name, company_name, batch_no,
                        pay_qty, free_qty, gst_percent, taxable_amount,
                        gst_amount, amount, bill_discount,
                        bill_gst_amount, bill_net_amount}, ... ],
             "summary": {total_bills, total_lines, total_taxable,
                         total_gst, total_bill_discount, total_net}}
        """
        clauses: list[str] = []
        params: list = []

        if from_date:
            clauses.append("pi.voucher_date >= ?")
            params.append(from_date)
        if to_date:
            clauses.append("pi.voucher_date <= ?")
            params.append(to_date)
        if supplier_id is not None:
            clauses.append("pi.supplier_id = ?")
            params.append(supplier_id)
        if item_id is not None:
            clauses.append("pii.item_id = ?")
            params.append(item_id)
        if company_id is not None:
            clauses.append("i.company_id = ?")
            params.append(company_id)
        if gst_percent is not None:
            clauses.append("pii.gst_percent = ?")
            params.append(gst_percent)
        if invoice_no:
            clauses.append("pi.invoice_no LIKE ?")
            params.append(f"%{invoice_no}%")
        if voucher_no:
            clauses.append("pi.voucher_no LIKE ?")
            params.append(f"%{voucher_no}%")

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""

        conn = get_connection()
        try:
            raw_rows = conn.execute(
                f"""
                SELECT
                    pi.id            AS purchase_id,
                    pi.voucher_no    AS voucher_no,
                    pi.voucher_date  AS voucher_date,
                    pi.invoice_no    AS invoice_no,
                    pi.invoice_date  AS invoice_date,
                    s.supplier_name  AS supplier_name,
                    i.item_name      AS item_name,
                    co.company_name  AS company_name,
                    pii.batch_no     AS batch_no,
                    pii.pay_qty      AS pay_qty,
                    pii.free_qty     AS free_qty,
                    pii.gst_percent  AS gst_percent,
                    pii.amount       AS taxable_amount,
                    pii.gst_amount   AS gst_amount,
                    pii.amount       AS amount,
                    pi.bill_discount AS bill_discount,
                    pi.gst_amount    AS bill_gst_amount,
                    pi.net_amount    AS bill_net_amount
                FROM purchase_invoices pi
                JOIN purchase_invoice_items pii
                     ON pii.purchase_invoice_id = pi.id
                LEFT JOIN items i
                       ON i.id = pii.item_id
                LEFT JOIN companies co
                       ON co.id = i.company_id
                LEFT JOIN suppliers s
                       ON s.id = pi.supplier_id
                {where}
                ORDER BY pi.voucher_date, pi.id, pii.id
                """,
                params,
            ).fetchall()
        finally:
            conn.close()

        rows = [dict(r) for r in raw_rows]
        return {"rows": rows, "summary": GSTReportDAO._summarize(rows)}

    # ── GST Rate Summary (grouped by gst_percent) ───────────────────
    @staticmethod
    def get_gst_rate_summary(
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        supplier_id: Optional[int] = None,
        item_id: Optional[int] = None,
        company_id: Optional[int] = None,
        invoice_no: Optional[str] = None,
        voucher_no: Optional[str] = None,
    ) -> list[dict]:
        """GST Rate Summary: group by gst_percent, sum taxable + GST.

        Returns list of dicts sorted by gst_percent:
            [{"gst_percent": float, "taxable_amount": float,
              "gst_amount": float}, ...]
        """
        clauses: list[str] = []
        params: list = []

        if from_date:
            clauses.append("pi.voucher_date >= ?")
            params.append(from_date)
        if to_date:
            clauses.append("pi.voucher_date <= ?")
            params.append(to_date)
        if supplier_id is not None:
            clauses.append("pi.supplier_id = ?")
            params.append(supplier_id)
        if item_id is not None:
            clauses.append("pii.item_id = ?")
            params.append(item_id)
        if company_id is not None:
            clauses.append("i.company_id = ?")
            params.append(company_id)
        if invoice_no:
            clauses.append("pi.invoice_no LIKE ?")
            params.append(f"%{invoice_no}%")
        if voucher_no:
            clauses.append("pi.voucher_no LIKE ?")
            params.append(f"%{voucher_no}%")

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""

        conn = get_connection()
        try:
            raw = conn.execute(
                f"""
                SELECT
                    pii.gst_percent  AS gst_percent,
                    SUM(pii.amount)  AS taxable_amount,
                    SUM(pii.gst_amount) AS gst_amount
                FROM purchase_invoices pi
                JOIN purchase_invoice_items pii
                     ON pii.purchase_invoice_id = pi.id
                LEFT JOIN items i
                       ON i.id = pii.item_id
                {where}
                GROUP BY pii.gst_percent
                ORDER BY pii.gst_percent
                """,
                params,
            ).fetchall()
        finally:
            conn.close()

        return [
            {
                "gst_percent": r["gst_percent"],
                "taxable_amount": round(r["taxable_amount"] or 0.0, 2),
                "gst_amount": round(r["gst_amount"] or 0.0, 2),
            }
            for r in raw
        ]

    # ── Summary only ────────────────────────────────────────────────
    @staticmethod
    def get_summary(
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        supplier_id: Optional[int] = None,
        item_id: Optional[int] = None,
        company_id: Optional[int] = None,
        gst_percent: Optional[float] = None,
        invoice_no: Optional[str] = None,
        voucher_no: Optional[str] = None,
    ) -> dict:
        """Summary only (same filters as get_purchase_gst_report)."""
        return GSTReportDAO.get_purchase_gst_report(
            from_date=from_date, to_date=to_date, supplier_id=supplier_id,
            item_id=item_id, company_id=company_id, gst_percent=gst_percent,
            invoice_no=invoice_no, voucher_no=voucher_no,
        )["summary"]

    # ── Filter option data (UI combos) ──────────────────────────────
    @staticmethod
    def get_filter_options() -> dict:
        """Small master lookups + distinct GST % values for combos."""
        conn = get_connection()
        try:
            suppliers = [
                dict(r) for r in conn.execute(
                    "SELECT id, supplier_name FROM suppliers "
                    "ORDER BY supplier_name COLLATE NOCASE"
                ).fetchall()
            ]
            items = [
                dict(r) for r in conn.execute(
                    "SELECT id, item_name FROM items "
                    "ORDER BY item_name COLLATE NOCASE"
                ).fetchall()
            ]
            companies = [
                dict(r) for r in conn.execute(
                    "SELECT id, company_name FROM companies "
                    "ORDER BY company_name COLLATE NOCASE"
                ).fetchall()
            ]
            gst_percents = [
                dict(r) for r in conn.execute(
                    "SELECT DISTINCT gst_percent FROM purchase_invoice_items "
                    "WHERE gst_percent > 0 "
                    "ORDER BY gst_percent"
                ).fetchall()
            ]
        finally:
            conn.close()
        return {
            "suppliers": suppliers,
            "items": items,
            "companies": companies,
            "gst_percents": gst_percents,
        }

    # ── summary math ────────────────────────────────────────────────
    @staticmethod
    def _summarize(rows: list[dict]) -> dict:
        """Aggregate stored values; bill-level amounts once per invoice."""
        seen_invoices: dict[int, dict] = {}
        total_lines = 0
        total_taxable = 0.0
        total_gst = 0.0

        for r in rows:
            total_lines += 1
            total_taxable += r["taxable_amount"] or 0.0
            total_gst += r["gst_amount"] or 0.0
            if r["purchase_id"] not in seen_invoices:
                seen_invoices[r["purchase_id"]] = {
                    "bill_discount": r["bill_discount"] or 0.0,
                    "bill_net_amount": r["bill_net_amount"] or 0.0,
                }

        total_bill_discount = sum(
            v["bill_discount"] for v in seen_invoices.values()
        )
        total_net = sum(v["bill_net_amount"] for v in seen_invoices.values())

        return {
            "total_bills": len(seen_invoices),
            "total_lines": total_lines,
            "total_taxable": round(total_taxable, 2),
            "total_gst": round(total_gst, 2),
            "total_bill_discount": round(total_bill_discount, 2),
            "total_net": round(total_net, 2),
        }
