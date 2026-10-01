"""Read-only Bank Book report over the authoritative BANK ledger."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from database.connection import get_connection
from database.financial_year import active_date_range
from database.ledger_dao import LedgerDAO


class BankBookError(ValueError):
    pass


def _validate_dates(from_date: str, to_date: str) -> None:
    try:
        start = datetime.strptime(from_date, "%Y-%m-%d")
        end = datetime.strptime(to_date, "%Y-%m-%d")
    except (TypeError, ValueError) as exc:
        raise BankBookError("Dates must use YYYY-MM-DD format.") from exc
    if start > end:
        raise BankBookError("From Date must be on or before To Date.")


class BankBookDAO:
    """Bank Book reads only ledger_transactions for the BANK system ledger."""

    @staticmethod
    def get_bank_ledger() -> dict[str, Any] | None:
        return LedgerDAO.get_by_system_role("BANK")

    @staticmethod
    def get_opening_balance(from_date: str) -> float:
        ledger = BankBookDAO.get_bank_ledger()
        if not ledger:
            return 0.0
        try:
            datetime.strptime(from_date, "%Y-%m-%d")
        except (TypeError, ValueError) as exc:
            raise BankBookError("From Date must use YYYY-MM-DD format.") from exc
        conn = get_connection()
        try:
            row = conn.execute(
                """SELECT COALESCE(SUM(debit), 0.0) AS debit,
                          COALESCE(SUM(credit), 0.0) AS credit
                   FROM ledger_transactions
                   WHERE ledger_id = ? AND transaction_date < ?""",
                (ledger["id"], from_date),
            ).fetchone()
            opening = ledger.get("opening_balance", 0.0) or 0.0
            if (ledger.get("opening_balance_type") or "Debit") == "Credit":
                opening = -opening
            return round(opening + (row["debit"] or 0.0) - (row["credit"] or 0.0), 2)
        finally:
            conn.close()

    @staticmethod
    def get_bank_book(from_date: str, to_date: str) -> dict[str, Any]:
        _validate_dates(from_date, to_date)
        ledger = BankBookDAO.get_bank_ledger()
        opening = BankBookDAO.get_opening_balance(from_date)
        if not ledger:
            return {"ledger": None, "opening_balance": opening, "rows": [], "summary": {"total_debit": 0.0, "total_credit": 0.0, "net_movement": 0.0, "closing_balance": opening}}
        conn = get_connection()
        try:
            rows = conn.execute(
                """SELECT id, transaction_date, transaction_time,
                          voucher_no, voucher_type, reference_type,
                          reference_id, description, debit, credit, ledger_id
                   FROM ledger_transactions
                   WHERE ledger_id = ? AND transaction_date >= ?
                     AND transaction_date <= ?
                   ORDER BY transaction_date, transaction_time, id""",
                (ledger["id"], from_date, to_date),
            ).fetchall()
            result = []
            running = opening
            total_debit = total_credit = 0.0
            for row in rows:
                debit = row["debit"] or 0.0; credit = row["credit"] or 0.0
                total_debit += debit; total_credit += credit; running += debit - credit
                item = dict(row); item["balance"] = round(running, 2); result.append(item)
            summary = {"total_debit": round(total_debit, 2), "total_credit": round(total_credit, 2), "net_movement": round(total_debit - total_credit, 2), "closing_balance": round(running, 2)}
            return {"ledger": ledger, "opening_balance": round(opening, 2), "rows": result, "summary": summary}
        finally:
            conn.close()

    @staticmethod
    def get_summary(from_date: str, to_date: str) -> dict[str, Any]:
        return BankBookDAO.get_bank_book(from_date, to_date)["summary"]

    @staticmethod
    def get_closing_balance(from_date: str, to_date: str) -> float:
        return BankBookDAO.get_summary(from_date, to_date)["closing_balance"]

    @staticmethod
    def get_filter_options() -> dict[str, str]:
        start, end = active_date_range()
        return {"from_date": start, "to_date": end}
