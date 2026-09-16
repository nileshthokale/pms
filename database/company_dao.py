from __future__ import annotations

from database.connection import get_connection


class CompanyDAO:
    """Data access object for the companies table."""

    @staticmethod
    def get_all() -> list[dict]:
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT id, company_name, short_name FROM companies ORDER BY company_name"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    @staticmethod
    def get_by_id(company_id: int) -> dict | None:
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT id, company_name, short_name FROM companies WHERE id = ?",
                (company_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    @staticmethod
    def name_exists(name: str, exclude_id: int | None = None) -> bool:
        conn = get_connection()
        try:
            if exclude_id is not None:
                row = conn.execute(
                    "SELECT 1 FROM companies WHERE company_name = ? AND id != ?",
                    (name, exclude_id),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT 1 FROM companies WHERE company_name = ?",
                    (name,),
                ).fetchone()
            return row is not None
        finally:
            conn.close()

    @staticmethod
    def insert(company_name: str, short_name: str) -> int:
        conn = get_connection()
        try:
            cursor = conn.execute(
                "INSERT INTO companies (company_name, short_name) VALUES (?, ?)",
                (company_name, short_name),
            )
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    @staticmethod
    def update(company_id: int, company_name: str, short_name: str) -> None:
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE companies SET company_name = ?, short_name = ? WHERE id = ?",
                (company_name, short_name, company_id),
            )
            conn.commit()
        finally:
            conn.close()
