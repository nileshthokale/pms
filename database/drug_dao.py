from __future__ import annotations

from database.connection import get_connection


class DrugDAO:
    """Data access object for the drugs table."""

    @staticmethod
    def get_all() -> list[dict]:
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT id, drug_name FROM drugs ORDER BY drug_name"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    @staticmethod
    def get_by_id(drug_id: int) -> dict | None:
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT id, drug_name FROM drugs WHERE id = ?",
                (drug_id,),
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
                    "SELECT 1 FROM drugs WHERE drug_name = ? AND id != ?",
                    (name, exclude_id),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT 1 FROM drugs WHERE drug_name = ?",
                    (name,),
                ).fetchone()
            return row is not None
        finally:
            conn.close()

    @staticmethod
    def insert(drug_name: str) -> int:
        conn = get_connection()
        try:
            cursor = conn.execute(
                "INSERT INTO drugs (drug_name) VALUES (?)",
                (drug_name,),
            )
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    @staticmethod
    def update(drug_id: int, drug_name: str) -> None:
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE drugs SET drug_name = ? WHERE id = ?",
                (drug_name, drug_id),
            )
            conn.commit()
        finally:
            conn.close()
