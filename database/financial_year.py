"""Centralized financial-year configuration for the SQLite application."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from database.connection import get_connection

DEFAULT_NAME = "2026-2027"
DEFAULT_START = "2026-04-01"
DEFAULT_END = "2027-03-31"


class FinancialYearError(ValueError):
    """Raised when a financial-year operation is invalid."""


def _parse(value: str) -> date:
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except (TypeError, ValueError) as exc:
        raise FinancialYearError("Dates must use YYYY-MM-DD format.") from exc


def validate_financial_year(name: str, start_date: str, end_date: str, *, conn=None, exclude_id: int | None = None) -> dict[str, str]:
    name = str(name or "").strip()
    start = _parse(start_date)
    end = _parse(end_date)
    if not name:
        raise FinancialYearError("Financial year name is required.")
    if start >= end:
        raise FinancialYearError("Financial year start date must be before end date.")
    own = conn is None
    conn = conn or get_connection()
    try:
        clauses = ["NOT (end_date < ? OR start_date > ?)"]
        params: list[Any] = [start.isoformat(), end.isoformat()]
        if exclude_id is not None:
            clauses.append("id != ?"); params.append(exclude_id)
        overlap = conn.execute(f"SELECT name FROM financial_years WHERE {' AND '.join(clauses)}", params).fetchone()
        if overlap:
            raise FinancialYearError(f"Financial year overlaps existing year: {overlap['name']}.")
        duplicate = conn.execute("SELECT 1 FROM financial_years WHERE name = ?", (name,)).fetchone()
        if duplicate and exclude_id is None:
            raise FinancialYearError("Financial year name already exists.")
        return {"name": name, "start_date": start.isoformat(), "end_date": end.isoformat()}
    finally:
        if own:
            conn.close()


def ensure_financial_year_schema() -> None:
    conn = get_connection()
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS financial_years (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )""")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_financial_year_active ON financial_years(is_active) WHERE is_active = 1")
        conn.commit()
    finally:
        conn.close()


def create_financial_year(name: str, start_date: str, end_date: str, *, activate: bool = False, actor=None) -> dict[str, Any]:
    ensure_financial_year_schema()
    if actor is not None:
        from database.auth import PERM_FINANCIAL_YEAR_MANAGEMENT, PermissionDenied, has_permission
        if not has_permission(actor, PERM_FINANCIAL_YEAR_MANAGEMENT):
            raise PermissionDenied("Permission required: financial_year_management")
    conn = get_connection()
    try:
        values = validate_financial_year(name, start_date, end_date, conn=conn)
        if activate:
            conn.execute("UPDATE financial_years SET is_active = 0")
        cursor = conn.execute("INSERT INTO financial_years (name, start_date, end_date, is_active, created_at) VALUES (?, ?, ?, ?, ?)", (values["name"], values["start_date"], values["end_date"], int(activate), datetime.now(timezone.utc).isoformat()))
        conn.commit()
        return get_financial_year_by_id(cursor.lastrowid)
    except Exception:
        conn.rollback(); raise
    finally:
        conn.close()


def get_financial_years() -> list[dict[str, Any]]:
    ensure_financial_year_schema()
    conn = get_connection()
    try:
        return [dict(row) for row in conn.execute("SELECT * FROM financial_years ORDER BY start_date").fetchall()]
    finally:
        conn.close()


def get_financial_year_by_id(year_id: int) -> dict[str, Any] | None:
    ensure_financial_year_schema()
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM financial_years WHERE id = ?", (year_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_active_financial_year() -> dict[str, Any] | None:
    ensure_financial_year_schema()
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM financial_years WHERE is_active = 1").fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def ensure_default_financial_year() -> dict[str, Any]:
    ensure_financial_year_schema()
    active = get_active_financial_year()
    if active:
        return active
    years = get_financial_years()
    if years:
        return set_active_financial_year(years[0]["id"])
    return create_financial_year(DEFAULT_NAME, DEFAULT_START, DEFAULT_END, activate=True)


def set_active_financial_year(year_id: int, *, actor=None) -> dict[str, Any]:
    ensure_financial_year_schema()
    if actor is not None:
        from database.auth import PERM_FINANCIAL_YEAR_MANAGEMENT, PermissionDenied, has_permission
        if not has_permission(actor, PERM_FINANCIAL_YEAR_MANAGEMENT):
            raise PermissionDenied("Permission required: financial_year_management")
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM financial_years WHERE id = ?", (year_id,)).fetchone()
        if not row:
            raise FinancialYearError("Financial year was not found.")
        conn.execute("UPDATE financial_years SET is_active = 0")
        conn.execute("UPDATE financial_years SET is_active = 1 WHERE id = ?", (year_id,))
        conn.commit()
        return dict(row)
    except Exception:
        conn.rollback(); raise
    finally:
        conn.close()


def get_financial_year_for_date(value: str) -> dict[str, Any] | None:
    point = _parse(value)
    ensure_financial_year_schema()
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM financial_years WHERE start_date <= ? AND end_date >= ?", (point.isoformat(), point.isoformat())).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def validate_transaction_date(value: str) -> None:
    active = ensure_default_financial_year()
    point = _parse(value)
    if not (_parse(active["start_date"]) <= point <= _parse(active["end_date"])):
        raise FinancialYearError(f"Transaction date {value} is outside active financial year {active['name']}.")


def active_date_range() -> tuple[str, str]:
    active = ensure_default_financial_year()
    return active["start_date"], active["end_date"]
