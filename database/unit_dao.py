from __future__ import annotations

from database.connection import get_connection


class UnitDAO:
    """Data access object for the units table."""

    @staticmethod
    def get_all() -> list[dict]:
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT id, unit_name FROM units ORDER BY unit_name"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    @staticmethod
    def get_by_id(unit_id: int) -> dict | None:
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT id, unit_name FROM units WHERE id = ?",
                (unit_id,),
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
                    "SELECT 1 FROM units WHERE unit_name = ? AND id != ?",
                    (name, exclude_id),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT 1 FROM units WHERE unit_name = ?",
                    (name,),
                ).fetchone()
            return row is not None
        finally:
            conn.close()

    @staticmethod
    def insert(unit_name: str) -> int:
        conn = get_connection()
        try:
            cursor = conn.execute(
                "INSERT INTO units (unit_name) VALUES (?)",
                (unit_name,),
            )
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    @staticmethod
    def update(unit_id: int, unit_name: str) -> None:
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE units SET unit_name = ? WHERE id = ?",
                (unit_name, unit_id),
            )
            conn.commit()
        finally:
            conn.close()
