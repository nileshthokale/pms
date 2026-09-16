"""Purchase Report DAO — Phase 5B.

Read-only report over the application's **source documents**:
purchase_invoices + purchase_invoice_items, joined with items,
companies and suppliers. The report never writes to any table and
never recalculates business rules — it aggregates the stored values.

Date behavior (same as the existing Purchase History):
    purchase filters on `voucher_date` (the purchase transaction date),
    inclusive: from_date <= voucher_date <= to_date.
    `invoice_date` (the supplier's bill date) is displayed as stored but
    is not used for filtering — the existing application does not filter
    on it, and no new date semantics are invented here.

Stored purchase calculation (as recorded by PurchaseDAO/screens, shown,
NOT recalculated):
    line.amount   = (pay_qty + free_qty) × rate      # free qty costed;
                                                     # line discount stored
                                                     # but not applied
    line.gst_amount = round(line.amount × gst_percent / 100)
    header.total_amount    = Σ line.amount
    header.gst_amount      = Σ line.gst_amount
    header.net_amount      = total_amount + gst_amount − bill_discount
                             − debit_note_amount + other_amount + round_off

Summary totals aggregate stored fields; bill-level amounts (bill
discount, net_amount) are counted once per invoice even when the
invoice has multiple lines.
"""

from __future__ import annotations

from typing import Optional

from database.connection import get_connection


class PurchaseReportDAO:
    """Read-only Purchase Report over purchase source documents."""

    # ── main report ──────────────────────────────────────────────────
    @staticmethod
    def get_purchase_report(
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        supplier_id: Optional[int] = None,
        item_id: Optional[int] = None,
        company_id: Optional[int] = None,
        invoice_no: Optional[str] = None,
        voucher_no: Optional[str] = None,
        batch_no: Optional[str] = None,
    ) -> dict:
        """Purchase report rows + summary for the given filters.

        One detail query (invoice × line join); the summary is computed
        from those rows (no N+1).

        Returns:
            {"rows": [ {voucher_no, voucher_date, invoice_no, invoice_date,
                        supplier_name, item_name, company_name, pack_size,
                        batch_no, expiry, pay_qty, free_qty, rate, mrp,
                        discount, gst_percent, gst_amount, amount,
                        purchase_rate, net_rate, pp,
                        purchase_id, bill_discount, bill_net_amount}, ... ],
             "summary": {total_bills, total_lines, total_pay_qty,
                         total_free_qty, total_qty, total_gross,
                         total_gst, total_discount, total_net}}
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
        if batch_no:
            clauses.append("pii.batch_no LIKE ?")
            params.append(f"%{batch_no}%")

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
                    pii.pack_size    AS pack_size,
                    pii.batch_no     AS batch_no,
                    pii.expiry       AS expiry,
                    pii.pay_qty      AS pay_qty,
                    pii.free_qty     AS free_qty,
                    pii.rate         AS rate,
                    pii.mrp          AS mrp,
                    pii.discount     AS discount,
                    pii.gst_percent  AS gst_percent,
                    pii.gst_amount   AS gst_amount,
                    pii.amount       AS amount,
                    pii.purchase_rate AS purchase_rate,
                    pii.net_rate     AS net_rate,
                    pii.pp           AS pp,
                    pi.bill_discount AS bill_discount,
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
        return {"rows": rows, "summary": PurchaseReportDAO._summarize(rows)}

    @staticmethod
    def get_summary(
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        supplier_id: Optional[int] = None,
        item_id: Optional[int] = None,
        company_id: Optional[int] = None,
        invoice_no: Optional[str] = None,
        voucher_no: Optional[str] = None,
        batch_no: Optional[str] = None,
    ) -> dict:
        """Summary only (same filters as get_purchase_report)."""
        return PurchaseReportDAO.get_purchase_report(
            from_date=from_date, to_date=to_date, supplier_id=supplier_id,
            item_id=item_id, company_id=company_id, invoice_no=invoice_no,
            voucher_no=voucher_no, batch_no=batch_no,
        )["summary"]

    # ── summary math ─────────────────────────────────────────────────
    @staticmethod
    def _summarize(rows: list[dict]) -> dict:
        """Aggregate stored values; bill-level amounts once per invoice."""
        seen_invoices: dict[int, dict] = {}
        total_lines = 0
        total_pay_qty = 0.0
        total_free_qty = 0.0
        total_gross = 0.0
        total_gst = 0.0
        total_line_discount = 0.0

        for r in rows:
            total_lines += 1
            total_pay_qty += r["pay_qty"] or 0.0
            total_free_qty += r["free_qty"] or 0.0
            total_gross += r["amount"] or 0.0
            total_gst += r["gst_amount"] or 0.0
            total_line_discount += r["discount"] or 0.0
            if r["purchase_id"] not in seen_invoices:
                seen_invoices[r["purchase_id"]] = {
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
            "total_pay_qty": round(total_pay_qty, 2),
            "total_free_qty": round(total_free_qty, 2),
            "total_qty": round(total_pay_qty + total_free_qty, 2),
            "total_gross": round(total_gross, 2),
            "total_gst": round(total_gst, 2),
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
        finally:
            conn.close()
        return {
            "suppliers": suppliers,
            "items": items,
            "companies": companies,
        }
