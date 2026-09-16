"""Profit & Loss report DAO — Phase 4C.

Reads the authoritative accounting source (account_ledgers +
ledger_transactions + account_groups) ONLY.  Source documents
(sales_invoices, purchase_invoices, customer_receipts, supplier_payments,
credit_notes, debit_notes, journal_entries) are never queried here.

The report covers a user-defined period (from_date .. to_date).  Opening
balances are excluded — only current-period transaction activity is
counted.  The active-net concept (same as PostingEngine / Trial Balance)
ensures reversal rows are never double-counted.

Classification is driven by account_groups.statement_type:
  INCOME  → revenue ledgers  (credit increases, debit reduces)
  EXPENSE → expense ledgers  (debit increases, credit reduces)

Unclassified ledgers (account_group_id IS NULL or statement_type not
INCOME/EXPENSE) are excluded from totals and reported separately.

Limitations (documented, not invented):
  - No COGS / Inventory valuation (periodic inventory posture).
  - No GST separation (Decision 4a — gross posting).
  - The P&L reflects configured ledger postings, not professional
    accounting advice.
"""

from __future__ import annotations

from typing import Optional

from database.connection import get_connection

EPSILON = 0.005


class ProfitLossDAO:
    """Profit & Loss built exclusively from ledger data."""

    # ── main report ──────────────────────────────────────────────────

    @staticmethod
    def get_profit_loss(
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> dict:
        """Full P&L report for the given period.

        Returns::

            {
                "from_date": ...,
                "to_date": ...,
                "income": [
                    {"ledger_id", "ledger_name", "account_group", "amount"},
                    ...
                ],
                "expenses": [
                    {"ledger_id", "ledger_name", "account_group", "amount"},
                    ...
                ],
                "unclassified": [
                    {"ledger_id", "ledger_name", "account_group", "amount"},
                    ...
                ],
                "totals": {
                    "total_income": ...,
                    "total_expenses": ...,
                    "net_result": ...,
                    "net_label": "Net Profit" | "Net Loss" | "No Profit / No Loss",
                    "has_unclassified": ...,
                    "has_cogs_limitation": True,
                    "has_gst_limitation": True,
                },
            }
        """
        conn = get_connection()
        try:
            rows = conn.execute(
                """
                SELECT
                    l.id            AS ledger_id,
                    l.ledger_name   AS ledger_name,
                    l.account_group AS account_group,
                    g.statement_type AS statement_type,
                    COALESCE(SUM(t.debit), 0.0)  AS txn_debit,
                    COALESCE(SUM(t.credit), 0.0) AS txn_credit
                FROM account_ledgers l
                LEFT JOIN account_groups g
                    ON l.account_group_id = g.id
                LEFT JOIN ledger_transactions t
                    ON t.ledger_id = l.id
                   AND (:from_date IS NULL OR t.transaction_date >= :from_date)
                   AND (:to_date   IS NULL OR t.transaction_date <= :to_date)
                GROUP BY
                    l.id, l.ledger_name, l.account_group,
                    g.statement_type
                HAVING txn_debit != 0 OR txn_credit != 0
                ORDER BY g.statement_type, l.ledger_name COLLATE NOCASE
                """,
                {"from_date": from_date, "to_date": to_date},
            ).fetchall()
        finally:
            conn.close()

        income_rows: list[dict] = []
        expense_rows: list[dict] = []
        unclassified_rows: list[dict] = []

        for r in rows:
            debit = r["txn_debit"] or 0.0
            credit = r["txn_credit"] or 0.0
            stmt = r["statement_type"]

            if stmt == "INCOME":
                amount = round(credit - debit, 2)
                if abs(amount) <= EPSILON:
                    continue
                income_rows.append(
                    {
                        "ledger_id": r["ledger_id"],
                        "ledger_name": r["ledger_name"],
                        "account_group": r["account_group"] or "",
                        "amount": amount,
                    }
                )
            elif stmt == "EXPENSE":
                amount = round(debit - credit, 2)
                if abs(amount) <= EPSILON:
                    continue
                expense_rows.append(
                    {
                        "ledger_id": r["ledger_id"],
                        "ledger_name": r["ledger_name"],
                        "account_group": r["account_group"] or "",
                        "amount": amount,
                    }
                )
            else:
                # Unclassified: no statement_type or not INCOME/EXPENSE
                net = round(debit - credit, 2)
                unclassified_rows.append(
                    {
                        "ledger_id": r["ledger_id"],
                        "ledger_name": r["ledger_name"],
                        "account_group": r["account_group"] or "",
                        "amount": net,
                    }
                )

        total_income = round(sum(r["amount"] for r in income_rows), 2)
        total_expenses = round(sum(r["amount"] for r in expense_rows), 2)
        net = round(total_income - total_expenses, 2)

        if net > EPSILON:
            net_label = "Net Profit"
        elif net < -EPSILON:
            net_label = "Net Loss"
        else:
            net_label = "No Profit / No Loss"

        return {
            "from_date": from_date,
            "to_date": to_date,
            "income": income_rows,
            "expenses": expense_rows,
            "unclassified": unclassified_rows,
            "totals": {
                "total_income": total_income,
                "total_expenses": total_expenses,
                "net_result": net,
                "net_label": net_label,
                "has_unclassified": len(unclassified_rows) > 0,
                "has_cogs_limitation": True,
                "has_gst_limitation": True,
            },
        }

    # ── convenience accessors ────────────────────────────────────────

    @staticmethod
    def get_income_ledgers(
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> list[dict]:
        """Income ledgers only."""
        return ProfitLossDAO.get_profit_loss(from_date, to_date)["income"]

    @staticmethod
    def get_expense_ledgers(
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> list[dict]:
        """Expense ledgers only."""
        return ProfitLossDAO.get_profit_loss(from_date, to_date)["expenses"]

    @staticmethod
    def get_unclassified(
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> list[dict]:
        """Unclassified ledgers only."""
        return ProfitLossDAO.get_profit_loss(from_date, to_date)["unclassified"]

    @staticmethod
    def get_totals(
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> dict:
        """Totals only."""
        return ProfitLossDAO.get_profit_loss(from_date, to_date)["totals"]
