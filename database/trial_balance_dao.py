"""Trial Balance report DAO — Phase 3.

Reads the authoritative accounting source (account_ledgers +
ledger_transactions) ONLY. Source documents (sales_invoices,
purchase_invoices, customer_receipts, supplier_payments, credit_notes,
debit_notes, journal_entries) are never queried here — the Trial
Balance reports the ledger effects the PostingEngine has already
produced.

Active-net concept (consistent with PostingEngine._active_nets_cur):
a ledger's effective balance is the per-ledger NET of all its
transaction rows (reversal rows are real rows that offset their
originals naturally, so historical reversals are never double-counted)
plus its opening balance on the opening-balance side. A net within
EPSILON of zero is a zero balance — the same tolerance the engine
uses to decide whether a posting is active.

Date assumption: ledger_transactions.transaction_date is stored as ISO
'YYYY-MM-DD' TEXT, so as-of filtering uses string comparison
(transaction_date <= as_of_date), which is correct for ISO dates.

Rounding: per-ledger figures and totals are computed from raw sums; the
balance verdict uses the EPSILON tolerance. Values are rounded to 2
decimals only for presentation/return convenience — the global
difference is never silently rounded away: an imbalance within
EPSILON is float noise (BALANCED), anything larger is reported
unmodified as UNBALANCED.
"""

from __future__ import annotations

from typing import Optional

from database.connection import get_connection

# Same float tolerance as PostingEngine._EPSILON.
EPSILON = 0.005


class TrialBalanceDAO:
    """Trial Balance built exclusively from ledger data."""

    # ── main report ──────────────────────────────────────────────────
    @staticmethod
    def get_trial_balance(as_of_date: Optional[str] = None) -> dict:
        """Trial Balance for every account ledger.

        One grouped query over ledger_transactions joined with
        account_ledgers (no N+1). Opening balances are ALWAYS included
        regardless of the as-of date; transaction activity is included
        only for transaction_date <= as_of_date (when given).

        Returns:
            {
              "as_of_date": as_of_date or None,
              "rows": [
                  {"ledger_id", "ledger_name", "account_group",
                   "system_role", "debit", "credit", "is_zero"},
                  ...  # closing figures: exactly one of debit/credit
                  ...  # is non-zero (never both)
              ],
              "totals": {
                  "total_debit", "total_credit",
                  "difference", "balanced", "ledger_count",
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
                    l.system_role   AS system_role,
                    l.opening_balance      AS opening_balance,
                    l.opening_balance_type AS opening_balance_type,
                    COALESCE(SUM(t.debit), 0.0)  AS txn_debit,
                    COALESCE(SUM(t.credit), 0.0) AS txn_credit
                FROM account_ledgers l
                LEFT JOIN ledger_transactions t
                    ON t.ledger_id = l.id
                   AND (:as_of IS NULL OR t.transaction_date <= :as_of)
                GROUP BY
                    l.id, l.ledger_name, l.account_group, l.system_role,
                    l.opening_balance, l.opening_balance_type
                ORDER BY l.ledger_name COLLATE NOCASE
                """,
                {"as_of": as_of_date},
            ).fetchall()
        finally:
            conn.close()

        report_rows: list[dict] = []
        total_debit = 0.0
        total_credit = 0.0

        for r in rows:
            opening = r["opening_balance"] or 0.0
            ob_type = r["opening_balance_type"] or "Debit"

            debit_total = (r["txn_debit"] or 0.0) + (
                opening if ob_type == "Debit" else 0.0
            )
            credit_total = (r["txn_credit"] or 0.0) + (
                opening if ob_type == "Credit" else 0.0
            )

            net = debit_total - credit_total
            if net > EPSILON:
                debit, credit = net, 0.0
            elif net < -EPSILON:
                debit, credit = 0.0, -net
            else:
                debit, credit = 0.0, 0.0

            total_debit += debit
            total_credit += credit

            report_rows.append(
                {
                    "ledger_id": r["ledger_id"],
                    "ledger_name": r["ledger_name"],
                    "account_group": r["account_group"] or "",
                    "system_role": r["system_role"],
                    "debit": round(debit, 2),
                    "credit": round(credit, 2),
                    "is_zero": debit == 0.0 and credit == 0.0,
                }
            )

        difference = total_debit - total_credit
        return {
            "as_of_date": as_of_date,
            "rows": report_rows,
            "totals": {
                "total_debit": round(total_debit, 2),
                "total_credit": round(total_credit, 2),
                "difference": round(difference, 2),
                "balanced": abs(difference) <= EPSILON,
                "ledger_count": len(report_rows),
            },
        }

    @staticmethod
    def get_trial_balance_filtered(
        as_of_date: Optional[str] = None,
        include_zero: bool = True,
    ) -> dict:
        """Trial Balance with the zero-balance display option applied.

        include_zero=True  -> every ledger appears (Account Ledger
                              screen convention: all ledgers listed).
        include_zero=False -> ledgers whose closing net is zero are
                              hidden.
        Totals are unaffected by the filter (hidden ledgers are zero).
        """
        report = TrialBalanceDAO.get_trial_balance(as_of_date)
        if not include_zero:
            report["rows"] = [
                r for r in report["rows"] if not r["is_zero"]
            ]
        return report

    # ── convenience accessors ────────────────────────────────────────
    @staticmethod
    def get_totals(as_of_date: Optional[str] = None) -> dict:
        """Totals only: total_debit, total_credit, difference, balanced."""
        return TrialBalanceDAO.get_trial_balance(as_of_date)["totals"]

    @staticmethod
    def verify_balanced(as_of_date: Optional[str] = None) -> bool:
        """True when Total Debit equals Total Credit within EPSILON.

        Never adjusts or rounds away an imbalance — a False result is
        reported exactly as found (see totals.difference).
        """
        return TrialBalanceDAO.get_totals(as_of_date)["balanced"]
