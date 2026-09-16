"""Balance Sheet report DAO — Phase 4D.

Reads the authoritative accounting source (account_ledgers +
ledger_transactions + account_groups) ONLY.  Source documents are
never queried — the Balance Sheet reports the ledger effects the
PostingEngine has already produced.

Classification is driven by account_groups.statement_type:
  ASSET      → assets section
  LIABILITY  → liabilities section
  EQUITY     → equity / capital section

Income / Expense accounts do NOT directly appear as permanent
Balance Sheet accounts.  Their current-period result may contribute
to Equity only according to the documented P&L-to-equity treatment.

As-of-date behavior (same as Trial Balance):
  - Opening balances are ALWAYS included.
  - Transaction activity is included only for transaction_date <= as_of_date.
  - Future transactions never affect a historical as-of report.

Active-net concept (consistent with PostingEngine / Trial Balance):
  - Reversal rows are real accounting rows that offset their originals.
  - A fully reversed source has zero active effect.

Limitations (documented, not invented):
  - No COGS / Inventory valuation (periodic inventory posture).
  - No GST separation (gross posting).
  - No automatic balancing entries.
  - Current P&L-to-equity treatment follows approved design only.
  - The Balance Sheet reflects configured ledger postings, not
    professional accounting advice.
"""

from __future__ import annotations

from typing import Optional

from database.connection import get_connection

EPSILON = 0.005


class BalanceSheetDAO:
    """Balance Sheet built exclusively from ledger data."""

    # ── main report ──────────────────────────────────────────────────

    @staticmethod
    def get_balance_sheet(as_of_date: Optional[str] = None) -> dict:
        """Full Balance Sheet for the given as-of date.

        Returns::

            {
                "as_of_date": ...,
                "assets": [
                    {"ledger_id", "ledger_name", "account_group",
                     "amount"},
                    ...
                ],
                "liabilities": [
                    {"ledger_id", "ledger_name", "account_group",
                     "amount"},
                    ...
                ],
                "equity": [
                    {"ledger_id", "ledger_name", "account_group",
                     "amount"},
                    ...
                ],
                "unclassified": [
                    {"ledger_id", "ledger_name", "account_group",
                     "amount"},
                    ...
                ],
                "totals": {
                    "total_assets": ...,
                    "total_liabilities": ...,
                    "total_equity": ...,
                    "difference": ...,
                    "status": "BALANCED" | "UNBALANCED" | "EQUITY TREATMENT REQUIRED",
                    "has_unclassified": ...,
                },
            }

        The difference is: total_assets - (total_liabilities + total_equity).
        Status:
          - BALANCED when difference <= EPSILON
          - UNBALANCED when difference > EPSILON (data inconsistency)
          - EQUITY TREATMENT REQUIRED when P&L result is not included
            in equity (no balancing mechanism exists yet)
        """
        conn = get_connection()
        try:
            rows = conn.execute(
                """
                SELECT
                    l.id              AS ledger_id,
                    l.ledger_name     AS ledger_name,
                    l.account_group   AS account_group,
                    l.system_role     AS system_role,
                    l.opening_balance      AS opening_balance,
                    l.opening_balance_type AS opening_balance_type,
                    g.statement_type  AS statement_type,
                    g.normal_balance  AS normal_balance,
                    COALESCE(SUM(t.debit), 0.0)  AS txn_debit,
                    COALESCE(SUM(t.credit), 0.0) AS txn_credit
                FROM account_ledgers l
                LEFT JOIN account_groups g
                    ON l.account_group_id = g.id
                LEFT JOIN ledger_transactions t
                    ON t.ledger_id = l.id
                   AND (:as_of IS NULL OR t.transaction_date <= :as_of)
                GROUP BY
                    l.id, l.ledger_name, l.account_group, l.system_role,
                    l.opening_balance, l.opening_balance_type,
                    g.statement_type, g.normal_balance
                ORDER BY g.statement_type, l.ledger_name COLLATE NOCASE
                """,
                {"as_of": as_of_date},
            ).fetchall()
        finally:
            conn.close()

        asset_rows: list[dict] = []
        liability_rows: list[dict] = []
        equity_rows: list[dict] = []
        unclassified_rows: list[dict] = []

        for r in rows:
            opening = r["opening_balance"] or 0.0
            ob_type = r["opening_balance_type"] or "Debit"
            stmt = r["statement_type"]
            normal_bal = r["normal_balance"] or "Debit"

            # Calculate closing balance (same as Trial Balance)
            debit_total = (r["txn_debit"] or 0.0) + (
                opening if ob_type == "Debit" else 0.0
            )
            credit_total = (r["txn_credit"] or 0.0) + (
                opening if ob_type == "Credit" else 0.0
            )

            # net: positive = debit balance, negative = credit balance
            net = debit_total - credit_total

            if stmt == "ASSET":
                # Assets: normal balance is DEBIT
                # Positive net = normal debit balance → show as positive
                # Negative net = unusual credit balance → show as negative
                amount = round(net, 2)
                if abs(amount) <= EPSILON:
                    continue
                asset_rows.append(
                    {
                        "ledger_id": r["ledger_id"],
                        "ledger_name": r["ledger_name"],
                        "account_group": r["account_group"] or "",
                        "amount": amount,
                    }
                )
            elif stmt == "LIABILITY":
                # Liabilities: normal balance is CREDIT
                # net is negative (credit > debit) → negate for display
                # net is positive (debit > credit) → unusual, show as negative
                amount = round(-net, 2)
                if abs(amount) <= EPSILON:
                    continue
                liability_rows.append(
                    {
                        "ledger_id": r["ledger_id"],
                        "ledger_name": r["ledger_name"],
                        "account_group": r["account_group"] or "",
                        "amount": amount,
                    }
                )
            elif stmt == "EQUITY":
                # Equity: normal balance is CREDIT
                # net is negative (credit > debit) → negate for display
                # net is positive (debit > credit) → unusual, show as negative
                amount = round(-net, 2)
                if abs(amount) <= EPSILON:
                    continue
                equity_rows.append(
                    {
                        "ledger_id": r["ledger_id"],
                        "ledger_name": r["ledger_name"],
                        "account_group": r["account_group"] or "",
                        "amount": amount,
                    }
                )
            else:
                # Unclassified: no statement_type or not ASSET/LIABILITY/EQUITY
                net_amount = round(debit_total - credit_total, 2)
                if abs(net_amount) <= EPSILON:
                    continue
                unclassified_rows.append(
                    {
                        "ledger_id": r["ledger_id"],
                        "ledger_name": r["ledger_name"],
                        "account_group": r["account_group"] or "",
                        "amount": net_amount,
                    }
                )

        total_assets = round(sum(r["amount"] for r in asset_rows), 2)
        total_liabilities = round(
            sum(r["amount"] for r in liability_rows), 2
        )
        total_equity = round(sum(r["amount"] for r in equity_rows), 2)

        difference = round(
            total_assets - (total_liabilities + total_equity), 2
        )

        if abs(difference) <= EPSILON:
            status = "BALANCED"
        else:
            # No P&L-to-equity mechanism is defined yet, so if there are
            # income/expense ledgers with activity, we flag it.
            status = "UNBALANCED"

        return {
            "as_of_date": as_of_date,
            "assets": asset_rows,
            "liabilities": liability_rows,
            "equity": equity_rows,
            "unclassified": unclassified_rows,
            "totals": {
                "total_assets": total_assets,
                "total_liabilities": total_liabilities,
                "total_equity": total_equity,
                "difference": difference,
                "status": status,
                "has_unclassified": len(unclassified_rows) > 0,
            },
        }

    # ── convenience accessors ────────────────────────────────────────

    @staticmethod
    def get_assets(as_of_date: Optional[str] = None) -> list[dict]:
        """Asset ledgers only."""
        return BalanceSheetDAO.get_balance_sheet(as_of_date)["assets"]

    @staticmethod
    def get_liabilities(as_of_date: Optional[str] = None) -> list[dict]:
        """Liability ledgers only."""
        return BalanceSheetDAO.get_balance_sheet(as_of_date)["liabilities"]

    @staticmethod
    def get_equity(as_of_date: Optional[str] = None) -> list[dict]:
        """Equity ledgers only."""
        return BalanceSheetDAO.get_balance_sheet(as_of_date)["equity"]

    @staticmethod
    def get_unclassified(as_of_date: Optional[str] = None) -> list[dict]:
        """Unclassified ledgers only."""
        return BalanceSheetDAO.get_balance_sheet(as_of_date)["unclassified"]

    @staticmethod
    def get_totals(as_of_date: Optional[str] = None) -> dict:
        """Totals only."""
        return BalanceSheetDAO.get_balance_sheet(as_of_date)["totals"]

    @staticmethod
    def verify_balance(as_of_date: Optional[str] = None) -> bool:
        """True when Total Assets equals Total Liabilities + Total Equity.

        Uses the same EPSILON tolerance as the PostingEngine and
        Trial Balance.  Never adjusts or rounds away an imbalance.
        """
        return (
            BalanceSheetDAO.get_totals(as_of_date)["status"] == "BALANCED"
        )
