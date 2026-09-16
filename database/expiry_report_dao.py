"""Expiry Report DAO — Phase 5C.

Read-only report over the current batch-wise stock (stock_batches
joined with items, companies, units). Source invoices are never
queried: current availability is exactly `stock_batches.stock_qty`.

Expiry formats (as actually produced/found in the application):
  - "MM/YY"    e.g. "12/27" — the application's format (purchase and
               sales screens store this; StockDAO parses this).
  Defensively supported at parse time (not currently produced by the
  app, kept so pre-existing/hand-entered data cannot crash the report):
  - "MM/YYYY"  e.g. "12/2027"
  - "YYYY-MM-DD" ISO date, e.g. "2027-12-31"

Normalized expiry date: for month formats the FIRST day of the expiry
month — exactly the convention in StockDAO._is_expired
(datetime(2000+yy, mm, 1)), so this report agrees with the Stock
Master's Expired filter. ISO values keep their exact date.

Classification (today defaults to the current date; never hardcoded):
  invalid       — empty / NULL / unparseable
  expired       — expiry_date < today
  expiring_soon — today <= expiry_date <= today + within_days
  ok            — later than the selected period

IMPORTANT: The report never writes anything. Batch expiry values are
parsed at read time only and are never rewritten.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from database.connection import get_connection

# Status keys and user-facing labels
STATUS_ALL = "all"
STATUS_EXPIRED = "expired"
STATUS_EXPIRING_SOON = "expiring_soon"

STATUS_LABELS = {
    STATUS_EXPIRED: "Expired",
    STATUS_EXPIRING_SOON: "Expiring Soon",
    "ok": "OK",
    "invalid": "Invalid",
}


def parse_expiry(expiry) -> Optional[date]:
    """Parse a stored expiry value into a normalized date.

    Returns None for empty / NULL / malformed values (never raises).
    """
    if expiry is None:
        return None
    text = str(expiry).strip()
    if not text:
        return None

    try:
        if "/" in text:
            parts = text.split("/")
            if len(parts) != 2:
                return None
            month = int(parts[0].strip())
            year = int(parts[1].strip())
            if month < 1 or month > 12:
                return None
            if year < 100:
                year += 2000
            return date(year, month, 1)

        if "-" in text:
            parts = text.split("-")
            if len(parts) != 3:
                return None
            year, month, day = (int(p) for p in parts)
            return date(year, month, day)
    except (ValueError, TypeError):
        return None

    return None


def _classify(expiry_date: Optional[date], today: date,
              within_days: int) -> str:
    if expiry_date is None:
        return "invalid"
    if expiry_date < today:
        return STATUS_EXPIRED
    if expiry_date <= today + timedelta(days=within_days):
        return STATUS_EXPIRING_SOON
    return "ok"


class ExpiryReportDAO:
    """Read-only Expiry Report over current stock batches."""

    # ── main report ──────────────────────────────────────────────────
    @staticmethod
    def get_expiry_report(
        status: str = STATUS_EXPIRING_SOON,
        within_days: int = 90,
        item_name: Optional[str] = None,
        company_id: Optional[int] = None,
        batch_no: Optional[str] = None,
        include_zero: bool = False,
        today: Optional[date] = None,
    ) -> dict:
        """Expiry report rows + summary.

        status: 'expired' | 'expiring_soon' | 'all'
        include_zero: when False (default) batches with stock_qty <= 0
        are excluded.

        One parameterized query; classification and sorting happen in
        Python on the parsed expiry dates (no N+1).

        Returns:
            {"rows": [ {item_name, company_name, unit_name, pack_size,
                        batch_no, expiry, expiry_date, status,
                        status_label, mrp, purchase_rate, net_rate,
                        stock_qty, reorder_stock_level}, ... ],
             "summary": {expired_count, expiring_soon_count,
                         invalid_count, total_batches, total_qty,
                         estimated_value}}
        """
        if status not in (STATUS_ALL, STATUS_EXPIRED, STATUS_EXPIRING_SOON):
            raise ValueError(f"Unknown expiry status filter '{status}'.")
        if within_days < 0:
            raise ValueError("within_days must be >= 0.")
        today = today or date.today()

        clauses: list[str] = []
        params: list = []
        if item_name:
            clauses.append("i.item_name LIKE ?")
            params.append(f"%{item_name}%")
        if company_id is not None:
            clauses.append("i.company_id = ?")
            params.append(company_id)
        if batch_no:
            clauses.append("sb.batch_no LIKE ?")
            params.append(f"%{batch_no}%")
        if not include_zero:
            clauses.append("sb.stock_qty > 0")

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""

        conn = get_connection()
        try:
            raw_rows = conn.execute(
                f"""
                SELECT
                    sb.id           AS batch_id,
                    sb.item_id      AS item_id,
                    i.item_name     AS item_name,
                    c.company_name  AS company_name,
                    u.unit_name     AS unit_name,
                    sb.pack_size    AS pack_size,
                    sb.batch_no     AS batch_no,
                    sb.expiry       AS expiry,
                    sb.mrp          AS mrp,
                    sb.purchase_rate AS purchase_rate,
                    sb.net_rate     AS net_rate,
                    sb.stock_qty    AS stock_qty,
                    i.reorder_stock_level AS reorder_stock_level
                FROM stock_batches sb
                LEFT JOIN items i ON i.id = sb.item_id
                LEFT JOIN companies c ON c.id = i.company_id
                LEFT JOIN units u ON u.id = i.unit_id
                {where}
                """,
                params,
            ).fetchall()
        finally:
            conn.close()

        rows: list[dict] = []
        for r in raw_rows:
            row = dict(r)
            row["stock_qty"] = row["stock_qty"] or 0.0
            parsed = parse_expiry(row["expiry"])
            row["expiry_date"] = parsed.isoformat() if parsed else None
            row["status"] = _classify(parsed, today, within_days)
            row["status_label"] = STATUS_LABELS[row["status"]]

            if status != STATUS_ALL and row["status"] != status:
                continue
            rows.append(row)

        # Default sort: expiry ascending (most urgent first); invalid
        # values last; secondary by item name, then batch no.
        rows.sort(
            key=lambda r: (
                r["expiry_date"] is None,
                r["expiry_date"] or "",
                (r["item_name"] or "").lower(),
                r["batch_no"] or "",
            )
        )

        return {"rows": rows, "summary": ExpiryReportDAO._summarize(rows)}

    # ── convenience wrappers ─────────────────────────────────────────
    @staticmethod
    def get_expired(**kwargs) -> list[dict]:
        kwargs.pop("status", None)
        return ExpiryReportDAO.get_expiry_report(
            status=STATUS_EXPIRED, **kwargs
        )["rows"]

    @staticmethod
    def get_expiring_soon(**kwargs) -> list[dict]:
        kwargs.pop("status", None)
        return ExpiryReportDAO.get_expiry_report(
            status=STATUS_EXPIRING_SOON, **kwargs
        )["rows"]

    @staticmethod
    def get_summary(**kwargs) -> dict:
        return ExpiryReportDAO.get_expiry_report(**kwargs)["summary"]

    # ── summary math ─────────────────────────────────────────────────
    @staticmethod
    def _summarize(rows: list[dict]) -> dict:
        """Summary over the returned (filtered) rows.

        estimated_value = Σ stock_qty × purchase_rate — the same
        informational stock-value formula the Stock screen uses. It is
        NOT an accounting/inventory valuation.
        """
        expired = sum(1 for r in rows if r["status"] == STATUS_EXPIRED)
        soon = sum(1 for r in rows if r["status"] == STATUS_EXPIRING_SOON)
        invalid = sum(1 for r in rows if r["status"] == "invalid")
        total_qty = sum(r["stock_qty"] for r in rows)
        estimated_value = sum(
            r["stock_qty"] * (r["purchase_rate"] or 0.0) for r in rows
        )
        return {
            "expired_count": expired,
            "expiring_soon_count": soon,
            "invalid_count": invalid,
            "total_batches": len(rows),
            "total_qty": round(total_qty, 2),
            "estimated_value": round(estimated_value, 2),
        }

    # ── filter option data (UI combos) ───────────────────────────────
    @staticmethod
    def get_filter_options() -> dict:
        """Small master lookups for the report's filter combos."""
        conn = get_connection()
        try:
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
        return {"items": items, "companies": companies}
