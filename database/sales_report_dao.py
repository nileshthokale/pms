"""Sales Report DAO — Phase 5A.

Read-only report over the application's **source documents**:
sales_invoices + sales_invoice_items, joined with items, companies,
customers, doctors (and stock batch columns stored on the line).

This is explicitly NOT an accounting report: financial reports (Trial
Balance, Profit & Loss, Balance Sheet) read the ledger postings produced
by the PostingEngine, while this report reads the sales transactions
themselves. The report never writes to any table and never recalculates
business rules — it aggregates the stored sales values.

Date behavior: sale_date is ISO 'YYYY-MM-DD' TEXT; the filter is
inclusive (from_date <= sale_date <= to_date) via string comparison.
Empty/None filters are ignored (show all matching records).

Totals: computed in Python from a single detail query. Bill-level
amounts (discount, net_amount) are summed once per invoice even when
the invoice has multiple lines. Totals aggregate stored values:
    gross     = Σ line (amount + line discount_amount)
    discount  = Σ line discount_amount + Σ invoice discount (once per bill)
    net       = Σ invoice net_amount (once per bill)
Because net_amount = total_amount − bill discount + round_off, the
stored round_off may make gross − discount differ from net by that
stored rounding amount (not an error).
"""

from __future__ import annotations

from typing import Optional

from database.connection import get_connection


class SalesReportDAO:
    """Read-only Sales Report over sales source documents."""

    # ── main report ──────────────────────────────────────────────────
    @staticmethod
    def get_sales_report(
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        customer_id: Optional[int] = None,
        item_id: Optional[int] = None,
        company_id: Optional[int] = None,
        bill_no: Optional[str] = None,
        patient: Optional[str] = None,
        doctor_id: Optional[int] = None,
    ) -> dict:
        """Sales report rows + summary for the given filters.

        One detail query (invoice × line join); the summary is computed
        from those rows (no N+1, no second aggregate round-trip).

        Returns:
            {"rows": [ {bill_no, sale_date, customer_name, patient_name,
                        doctor_name, item_name, company_name, batch_no,
                        expiry, mrp, sale_qty, discount_amount, amount,
                        invoice_id, bill_discount, bill_net_amount}, ... ],
             "summary": {total_bills, total_lines, total_qty,
                         total_gross, total_discount, total_net}}
        """
        clauses: list[str] = []
        params: list = []

        if from_date:
            clauses.append("si.sale_date >= ?")
            params.append(from_date)
        if to_date:
            clauses.append("si.sale_date <= ?")
            params.append(to_date)
        if customer_id is not None:
            clauses.append("si.customer_id = ?")
            params.append(customer_id)
        if item_id is not None:
            clauses.append("sii.item_id = ?")
            params.append(item_id)
        if company_id is not None:
            clauses.append("i.company_id = ?")
            params.append(company_id)
        if bill_no:
            clauses.append("si.bill_no LIKE ?")
            params.append(f"%{bill_no}%")
        if patient:
            clauses.append("si.patient_name LIKE ?")
            params.append(f"%{patient}%")
        if doctor_id is not None:
            clauses.append("si.doctor_id = ?")
            params.append(doctor_id)

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""

        conn = get_connection()
        try:
            raw_rows = conn.execute(
                f"""
                SELECT
                    si.id            AS invoice_id,
                    si.bill_no       AS bill_no,
                    si.sale_date     AS sale_date,
                    c.customer_name  AS customer_name,
                    si.patient_name  AS patient_name,
                    d.doctor_name    AS doctor_name,
                    i.item_name      AS item_name,
                    co.company_name  AS company_name,
                    sii.batch_no     AS batch_no,
                    sii.expiry       AS expiry,
                    sii.mrp          AS mrp,
                    sii.sale_qty     AS sale_qty,
                    sii.discount_amount AS discount_amount,
                    sii.amount       AS amount,
                    si.discount      AS bill_discount,
                    si.net_amount    AS bill_net_amount
                FROM sales_invoices si
                JOIN sales_invoice_items sii ON sii.sales_invoice_id = si.id
                LEFT JOIN items i
                       ON i.id = sii.item_id
                LEFT JOIN companies co
                       ON co.id = i.company_id
                LEFT JOIN customers c
                       ON c.id = si.customer_id
                LEFT JOIN doctors d
                       ON d.id = si.doctor_id
                {where}
                ORDER BY si.sale_date, si.id, sii.id
                """,
                params,
            ).fetchall()
        finally:
            conn.close()

        rows = [dict(r) for r in raw_rows]
        return {"rows": rows, "summary": SalesReportDAO._summarize(rows)}

    @staticmethod
    def get_summary(
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        customer_id: Optional[int] = None,
        item_id: Optional[int] = None,
        company_id: Optional[int] = None,
        bill_no: Optional[str] = None,
        patient: Optional[str] = None,
        doctor_id: Optional[int] = None,
    ) -> dict:
        """Summary only (same filters as get_sales_report)."""
        return SalesReportDAO.get_sales_report(
            from_date=from_date, to_date=to_date, customer_id=customer_id,
            item_id=item_id, company_id=company_id, bill_no=bill_no,
            patient=patient, doctor_id=doctor_id,
        )["summary"]

    # ── summary math ─────────────────────────────────────────────────
    @staticmethod
    def _summarize(rows: list[dict]) -> dict:
        """Aggregate stored values; bill-level amounts once per invoice."""
        seen_invoices: dict[int, dict] = {}
        total_lines = 0
        total_qty = 0.0
        total_gross = 0.0
        total_line_discount = 0.0

        for r in rows:
            total_lines += 1
            total_qty += r["sale_qty"] or 0.0
            line_discount = r["discount_amount"] or 0.0
            total_gross += (r["amount"] or 0.0) + line_discount
            total_line_discount += line_discount
            if r["invoice_id"] not in seen_invoices:
                seen_invoices[r["invoice_id"]] = {
                    "bill_discount": r["bill_discount"] or 0.0,
                    "net_amount": r["bill_net_amount"] or 0.0,
                }

        total_bill_discount = sum(
            v["bill_discount"] for v in seen_invoices.values()
        )
        total_net = sum(v["net_amount"] for v in seen_invoices.values())

        return {
            "total_bills": len(seen_invoices),
            "total_lines": total_lines,
            "total_qty": round(total_qty, 2),
            "total_gross": round(total_gross, 2),
            "total_discount": round(
                total_line_discount + total_bill_discount, 2
            ),
            "total_net": round(total_net, 2),
        }

    # ── filter option data (UI combos) ───────────────────────────────
    @staticmethod
    def get_filter_options() -> dict:
        """Small master lookups for the report's filter combos."""
        conn = get_connection()
        try:
            customers = [
                dict(r) for r in conn.execute(
                    "SELECT id, customer_name FROM customers "
                    "ORDER BY customer_name COLLATE NOCASE"
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
            doctors = [
                dict(r) for r in conn.execute(
                    "SELECT id, doctor_name FROM doctors "
                    "ORDER BY doctor_name COLLATE NOCASE"
                ).fetchall()
            ]
        finally:
            conn.close()
        return {
            "customers": customers,
            "items": items,
            "companies": companies,
            "doctors": doctors,
        }
