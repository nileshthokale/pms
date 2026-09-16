"""Party Wise Report DAO — Phase 5D.

Provides customer and supplier transaction summaries with accounting
balances sourced from the mapped Account Ledger (authoritative).

Operational totals (sales, purchases, credit notes, debit notes,
receipts, payments) come from source transaction tables.
Outstanding balance comes from the mapped Account Ledger via
LedgerDAO.get_balance().  Legacy balance methods are NOT used.

Date filtering behavior:
- No date filter: all parties are returned (even with zero transactions).
- Date filter applied: only parties with at least one transaction in the
  period are returned.  Outstanding balance is always CURRENT (not
  period-end) — this is documented Option B behavior.
"""

from __future__ import annotations

from typing import Optional

from database.connection import get_connection
from database.ledger_dao import LedgerDAO


class PartyWiseReportDAO:

    # ── customer report ────────────────────────────────────────────
    @staticmethod
    def get_customer_report(
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        party_name: Optional[str] = None,
    ) -> list[dict]:
        """Return customer summary rows using a single grouped query.

        When from_date/to_date are provided, only customers with at
        least one matching transaction are included.  Without date
        filters, all customers are returned.

        Outstanding balance uses the mapped Account Ledger as the
        authoritative source — it reflects the CURRENT balance
        regardless of the report period.
        """
        conn = get_connection()
        try:
            name_cond = ""
            name_params: list = []
            if party_name:
                name_cond = "AND c.customer_name LIKE ?"
                name_params.append(f"%{party_name}%")

            if from_date and to_date:
                cte = f"""
                WITH filtered_customers AS (
                    SELECT DISTINCT c.id
                    FROM customers c
                    WHERE c.id IN (
                        SELECT si.customer_id FROM sales_invoices si
                        WHERE si.sale_date >= ? AND si.sale_date <= ?
                    ) OR c.id IN (
                        SELECT cn.customer_id FROM credit_notes cn
                        WHERE cn.voucher_date >= ? AND cn.voucher_date <= ?
                    ) OR c.id IN (
                        SELECT cr.customer_id FROM customer_receipts cr
                        WHERE cr.receipt_date >= ? AND cr.receipt_date <= ?
                    ) {name_cond}
                )
                """
                cte_params = [from_date, to_date] * 3
                sales_where = "WHERE sale_date >= ? AND sale_date <= ?"
                cn_where = "WHERE voucher_date >= ? AND voucher_date <= ?"
                cr_where = "WHERE receipt_date >= ? AND receipt_date <= ?"
                sub_params = [from_date, to_date]
            elif from_date:
                cte = f"""
                WITH filtered_customers AS (
                    SELECT DISTINCT c.id
                    FROM customers c
                    WHERE c.id IN (
                        SELECT si.customer_id FROM sales_invoices si
                        WHERE si.sale_date >= ?
                    ) OR c.id IN (
                        SELECT cn.customer_id FROM credit_notes cn
                        WHERE cn.voucher_date >= ?
                    ) OR c.id IN (
                        SELECT cr.customer_id FROM customer_receipts cr
                        WHERE cr.receipt_date >= ?
                    ) {name_cond}
                )
                """
                cte_params = [from_date] * 3
                sales_where = "WHERE sale_date >= ?"
                cn_where = "WHERE voucher_date >= ?"
                cr_where = "WHERE receipt_date >= ?"
                sub_params = [from_date]
            elif to_date:
                cte = f"""
                WITH filtered_customers AS (
                    SELECT DISTINCT c.id
                    FROM customers c
                    WHERE c.id IN (
                        SELECT si.customer_id FROM sales_invoices si
                        WHERE si.sale_date <= ?
                    ) OR c.id IN (
                        SELECT cn.customer_id FROM credit_notes cn
                        WHERE cn.voucher_date <= ?
                    ) OR c.id IN (
                        SELECT cr.customer_id FROM customer_receipts cr
                        WHERE cr.receipt_date <= ?
                    ) {name_cond}
                )
                """
                cte_params = [to_date] * 3
                sales_where = "WHERE sale_date <= ?"
                cn_where = "WHERE voucher_date <= ?"
                cr_where = "WHERE receipt_date <= ?"
                sub_params = [to_date]
            else:
                cte = f"""
                WITH filtered_customers AS (
                    SELECT DISTINCT c.id
                    FROM customers c
                    WHERE 1=1 {name_cond}
                )
                """
                cte_params = []
                sales_where = ""
                cn_where = ""
                cr_where = ""
                sub_params = []

            sql = f"""
            {cte}
            SELECT
                c.id AS customer_id,
                c.customer_name,
                c.city,
                c.contact_no,
                c.ledger_id,
                COALESCE(s.total_sales, 0) AS total_sales,
                COALESCE(cn.total_credit_notes, 0) AS total_credit_notes,
                COALESCE(cr.total_receipts, 0) AS total_receipts
            FROM customers c
            INNER JOIN filtered_customers fc ON fc.id = c.id
            LEFT JOIN (
                SELECT customer_id, SUM(net_amount) AS total_sales
                FROM sales_invoices
                {sales_where}
                GROUP BY customer_id
            ) s ON s.customer_id = c.id
            LEFT JOIN (
                SELECT customer_id, SUM(total_amount) AS total_credit_notes
                FROM credit_notes
                {cn_where}
                GROUP BY customer_id
            ) cn ON cn.customer_id = c.id
            LEFT JOIN (
                SELECT customer_id, SUM(amount) AS total_receipts
                FROM customer_receipts
                {cr_where}
                GROUP BY customer_id
            ) cr ON cr.customer_id = c.id
            ORDER BY c.customer_name
            """

            all_params = cte_params + name_params + sub_params * 3
            rows = conn.execute(sql, all_params).fetchall()

            result = []
            for r in rows:
                row = dict(r)
                if row["ledger_id"]:
                    bal = LedgerDAO.get_balance(row["ledger_id"])
                    row["ledger_balance"] = bal["closing_balance"]
                    row["ledger_balance_type"] = bal["closing_balance_type"]
                else:
                    row["ledger_balance"] = 0.0
                    row["ledger_balance_type"] = "Debit"
                result.append(row)
            return result
        finally:
            conn.close()

    # ── supplier report ────────────────────────────────────────────
    @staticmethod
    def get_supplier_report(
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        party_name: Optional[str] = None,
    ) -> list[dict]:
        """Return supplier summary rows using a single grouped query.

        When from_date/to_date are provided, only suppliers with at
        least one matching transaction are included.  Without date
        filters, all suppliers are returned.

        Outstanding balance uses the mapped Account Ledger as the
        authoritative source — CURRENT balance regardless of period.
        """
        conn = get_connection()
        try:
            name_cond = ""
            name_params: list = []
            if party_name:
                name_cond = "AND s.supplier_name LIKE ?"
                name_params.append(f"%{party_name}%")

            if from_date and to_date:
                cte = f"""
                WITH filtered_suppliers AS (
                    SELECT DISTINCT s.id
                    FROM suppliers s
                    WHERE s.id IN (
                        SELECT pi.supplier_id FROM purchase_invoices pi
                        WHERE pi.voucher_date >= ? AND pi.voucher_date <= ?
                    ) OR s.id IN (
                        SELECT dn.supplier_id FROM debit_notes dn
                        WHERE dn.voucher_date >= ? AND dn.voucher_date <= ?
                    ) OR s.id IN (
                        SELECT sp.supplier_id FROM supplier_payments sp
                        WHERE sp.payment_date >= ? AND sp.payment_date <= ?
                    ) {name_cond}
                )
                """
                cte_params = [from_date, to_date] * 3
                sub_date = ">= ? AND voucher_date <= ?"
                sub_params = [from_date, to_date]
            elif from_date:
                cte = f"""
                WITH filtered_suppliers AS (
                    SELECT DISTINCT s.id
                    FROM suppliers s
                    WHERE s.id IN (
                        SELECT pi.supplier_id FROM purchase_invoices pi
                        WHERE pi.voucher_date >= ?
                    ) OR s.id IN (
                        SELECT dn.supplier_id FROM debit_notes dn
                        WHERE dn.voucher_date >= ?
                    ) OR s.id IN (
                        SELECT sp.supplier_id FROM supplier_payments sp
                        WHERE sp.payment_date >= ?
                    ) {name_cond}
                )
                """
                cte_params = [from_date] * 3
                sub_date = ">= ?"
                sub_params = [from_date]
            elif to_date:
                cte = f"""
                WITH filtered_suppliers AS (
                    SELECT DISTINCT s.id
                    FROM suppliers s
                    WHERE s.id IN (
                        SELECT pi.supplier_id FROM purchase_invoices pi
                        WHERE pi.voucher_date <= ?
                    ) OR s.id IN (
                        SELECT dn.supplier_id FROM debit_notes dn
                        WHERE dn.voucher_date <= ?
                    ) OR s.id IN (
                        SELECT sp.supplier_id FROM supplier_payments sp
                        WHERE sp.payment_date <= ?
                    ) {name_cond}
                )
                """
                cte_params = [to_date] * 3
                sub_date = "<= ?"
                sub_params = [to_date]
            else:
                cte = f"""
                WITH filtered_suppliers AS (
                    SELECT DISTINCT s.id
                    FROM suppliers s
                    WHERE 1=1 {name_cond}
                )
                """
                cte_params = []
                sub_date = ""
                sub_params = []

            # For purchase subqueries, the date column is voucher_date.
            # For debit_notes and supplier_payments, also voucher_date / payment_date.
            # We need separate date handling for each subquery.
            if from_date and to_date:
                pi_date = ">= ? AND voucher_date <= ?"
                dn_date = ">= ? AND voucher_date <= ?"
                sp_date = ">= ? AND payment_date <= ?"
                pi_params = [from_date, to_date]
                dn_params = [from_date, to_date]
                sp_params = [from_date, to_date]
            elif from_date:
                pi_date = ">= ?"
                dn_date = ">= ?"
                sp_date = ">= ?"
                pi_params = [from_date]
                dn_params = [from_date]
                sp_params = [from_date]
            elif to_date:
                pi_date = "<= ?"
                dn_date = "<= ?"
                sp_date = "<= ?"
                pi_params = [to_date]
                dn_params = [to_date]
                sp_params = [to_date]
            else:
                pi_date = ""
                dn_date = ""
                sp_date = ""
                pi_params = []
                dn_params = []
                sp_params = []

            sql = f"""
            {cte}
            SELECT
                s.id AS supplier_id,
                s.supplier_name,
                s.city,
                s.contact_no,
                s.ledger_id,
                COALESCE(p.total_purchases, 0) AS total_purchases,
                COALESCE(dn.total_debit_notes, 0) AS total_debit_notes,
                COALESCE(pm.total_payments, 0) AS total_payments
            FROM suppliers s
            INNER JOIN filtered_suppliers fs ON fs.id = s.id
            LEFT JOIN (
                SELECT supplier_id, SUM(net_amount) AS total_purchases
                FROM purchase_invoices
                {"WHERE voucher_date " + pi_date if pi_date else ""}
                GROUP BY supplier_id
            ) p ON p.supplier_id = s.id
            LEFT JOIN (
                SELECT supplier_id, SUM(total_amount) AS total_debit_notes
                FROM debit_notes
                {"WHERE voucher_date " + dn_date if dn_date else ""}
                GROUP BY supplier_id
            ) dn ON dn.supplier_id = s.id
            LEFT JOIN (
                SELECT supplier_id, SUM(amount) AS total_payments
                FROM supplier_payments
                {"WHERE payment_date " + sp_date if sp_date else ""}
                GROUP BY supplier_id
            ) pm ON pm.supplier_id = s.id
            ORDER BY s.supplier_name
            """

            all_params = cte_params + name_params + pi_params + dn_params + sp_params
            rows = conn.execute(sql, all_params).fetchall()

            result = []
            for r in rows:
                row = dict(r)
                if row["ledger_id"]:
                    bal = LedgerDAO.get_balance(row["ledger_id"])
                    row["ledger_balance"] = bal["closing_balance"]
                    row["ledger_balance_type"] = bal["closing_balance_type"]
                else:
                    row["ledger_balance"] = 0.0
                    row["ledger_balance_type"] = "Credit"
                result.append(row)
            return result
        finally:
            conn.close()

    # ── summaries ──────────────────────────────────────────────────
    @staticmethod
    def get_customer_summary(
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        party_name: Optional[str] = None,
    ) -> dict:
        """Aggregate totals across all matching customers.

        Returns: total_customers, total_sales, total_returns,
        total_receipts, total_outstanding
        """
        rows = PartyWiseReportDAO.get_customer_report(
            from_date=from_date, to_date=to_date, party_name=party_name
        )
        total_outstanding = 0.0
        for r in rows:
            sign = 1.0 if r["ledger_balance_type"] == "Debit" else -1.0
            total_outstanding += r["ledger_balance"] * sign

        return {
            "total_customers": len(rows),
            "total_sales": round(sum(r["total_sales"] for r in rows), 2),
            "total_returns": round(
                sum(r["total_credit_notes"] for r in rows), 2
            ),
            "total_receipts": round(
                sum(r["total_receipts"] for r in rows), 2
            ),
            "total_outstanding": round(total_outstanding, 2),
        }

    @staticmethod
    def get_supplier_summary(
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        party_name: Optional[str] = None,
    ) -> dict:
        """Aggregate totals across all matching suppliers.

        Returns: total_suppliers, total_purchases, total_returns,
        total_payments, total_outstanding
        """
        rows = PartyWiseReportDAO.get_supplier_report(
            from_date=from_date, to_date=to_date, party_name=party_name
        )
        total_outstanding = 0.0
        for r in rows:
            sign = 1.0 if r["ledger_balance_type"] == "Credit" else -1.0
            total_outstanding += r["ledger_balance"] * sign

        return {
            "total_suppliers": len(rows),
            "total_purchases": round(
                sum(r["total_purchases"] for r in rows), 2
            ),
            "total_returns": round(
                sum(r["total_debit_notes"] for r in rows), 2
            ),
            "total_payments": round(
                sum(r["total_payments"] for r in rows), 2
            ),
            "total_outstanding": round(total_outstanding, 2),
        }

    # ── party detail ───────────────────────────────────────────────
    @staticmethod
    def get_party_detail(
        party_type: str, party_id: int
    ) -> Optional[dict]:
        """Return detailed info for one party with transaction history.

        party_type: 'customer' or 'supplier'

        Returns dict with:
            party_info   — party master fields
            ledger_info  — ledger name, opening balance, group
            opening_balance, opening_balance_type
            closing_balance, closing_balance_type
            transactions — list of ledger_transactions for this party
        Or None if the party is not found.
        """
        conn = get_connection()
        try:
            if party_type == "customer":
                party = conn.execute(
                    """
                    SELECT c.*, al.ledger_name
                    FROM customers c
                    LEFT JOIN account_ledgers al ON al.id = c.ledger_id
                    WHERE c.id = ?
                    """,
                    (party_id,),
                ).fetchone()
            elif party_type == "supplier":
                party = conn.execute(
                    """
                    SELECT s.*, al.ledger_name
                    FROM suppliers s
                    LEFT JOIN account_ledgers al ON al.id = s.ledger_id
                    WHERE s.id = ?
                    """,
                    (party_id,),
                ).fetchone()
            else:
                return None

            if not party:
                return None

            party_dict = dict(party)
            ledger_id = party_dict.get("ledger_id")

            ledger_info = None
            opening_balance = 0.0
            opening_balance_type = "Debit"
            closing_balance = 0.0
            closing_balance_type = "Debit"
            transactions: list[dict] = []

            if ledger_id:
                ledger_row = conn.execute(
                    "SELECT * FROM account_ledgers WHERE id = ?",
                    (ledger_id,),
                ).fetchone()
                if ledger_row:
                    ledger_info = dict(ledger_row)
                    opening_balance = ledger_info.get(
                        "opening_balance", 0.0
                    ) or 0.0
                    opening_balance_type = ledger_info.get(
                        "opening_balance_type", "Debit"
                    ) or "Debit"

                bal = LedgerDAO.get_balance(ledger_id)
                closing_balance = bal["closing_balance"]
                closing_balance_type = bal["closing_balance_type"]

                txn_rows = conn.execute(
                    """
                    SELECT * FROM ledger_transactions
                    WHERE ledger_id = ?
                    ORDER BY transaction_date, transaction_time, id
                    """,
                    (ledger_id,),
                ).fetchall()
                transactions = [dict(r) for r in txn_rows]

            return {
                "party_info": party_dict,
                "ledger_info": ledger_info,
                "opening_balance": opening_balance,
                "opening_balance_type": opening_balance_type,
                "closing_balance": closing_balance,
                "closing_balance_type": closing_balance_type,
                "transactions": transactions,
            }
        finally:
            conn.close()

    # ── balances (convenience) ─────────────────────────────────────
    @staticmethod
    def get_customer_balances(
        party_name: Optional[str] = None,
    ) -> list[dict]:
        """Return all customer ledger balances (current, no date filter).

        Uses the mapped Account Ledger as the authoritative source.
        """
        conn = get_connection()
        try:
            if party_name:
                rows = conn.execute(
                    """
                    SELECT c.id AS customer_id, c.customer_name,
                           c.city, c.contact_no, c.ledger_id
                    FROM customers c
                    WHERE c.customer_name LIKE ?
                    ORDER BY c.customer_name
                    """,
                    (f"%{party_name}%",),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT c.id AS customer_id, c.customer_name,
                           c.city, c.contact_no, c.ledger_id
                    FROM customers c
                    ORDER BY c.customer_name
                    """,
                ).fetchall()

            result = []
            for r in rows:
                row = dict(r)
                if row["ledger_id"]:
                    bal = LedgerDAO.get_balance(row["ledger_id"])
                    row["ledger_balance"] = bal["closing_balance"]
                    row["ledger_balance_type"] = bal["closing_balance_type"]
                else:
                    row["ledger_balance"] = 0.0
                    row["ledger_balance_type"] = "Debit"
                result.append(row)
            return result
        finally:
            conn.close()

    @staticmethod
    def get_supplier_balances(
        party_name: Optional[str] = None,
    ) -> list[dict]:
        """Return all supplier ledger balances (current, no date filter).

        Uses the mapped Account Ledger as the authoritative source.
        """
        conn = get_connection()
        try:
            if party_name:
                rows = conn.execute(
                    """
                    SELECT s.id AS supplier_id, s.supplier_name,
                           s.city, s.contact_no, s.ledger_id
                    FROM suppliers s
                    WHERE s.supplier_name LIKE ?
                    ORDER BY s.supplier_name
                    """,
                    (f"%{party_name}%",),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT s.id AS supplier_id, s.supplier_name,
                           s.city, s.contact_no, s.ledger_id
                    FROM suppliers s
                    ORDER BY s.supplier_name
                    """,
                ).fetchall()

            result = []
            for r in rows:
                row = dict(r)
                if row["ledger_id"]:
                    bal = LedgerDAO.get_balance(row["ledger_id"])
                    row["ledger_balance"] = bal["closing_balance"]
                    row["ledger_balance_type"] = bal["closing_balance_type"]
                else:
                    row["ledger_balance"] = 0.0
                    row["ledger_balance_type"] = "Credit"
                result.append(row)
            return result
        finally:
            conn.close()
