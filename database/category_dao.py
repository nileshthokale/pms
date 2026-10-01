"""SQLite data access for the normal master-data Category feature."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from database.connection import get_connection


class CategoryError(ValueError):
    """Raised for a user-correctable category validation or safety error."""


def _normalise_name(value: str) -> str:
    return " ".join(str(value or "").strip().split())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CategoryDAO:
    """Data access for categories; all writes use parameterized SQLite SQL."""

    @staticmethod
    def create_category(category_name: str, description: str | None = None, is_active: bool = True) -> int:
        name = _normalise_name(category_name)
        if not name:
            raise CategoryError("Category Name is required.")
        if CategoryDAO.category_exists(name):
            raise CategoryError("A category with this name already exists.")
        conn = get_connection()
        try:
            cursor = conn.execute(
                """INSERT INTO categories
                   (category_name, description, is_active, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (name, _normalise_name(description or "") or None, int(bool(is_active)), _now(), _now()),
            )
            conn.commit()
            return int(cursor.lastrowid)
        except sqlite3.IntegrityError as exc:
            raise CategoryError("A category with this name already exists.") from exc
        finally:
            conn.close()

    @staticmethod
    def get_category(category_id: int) -> dict | None:
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT id, category_name, description, is_active, created_at, updated_at "
                "FROM categories WHERE id = ?", (category_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    @staticmethod
    def get_all_categories(include_inactive: bool = True) -> list[dict]:
        conn = get_connection()
        try:
            query = "SELECT id, category_name, description, is_active, created_at, updated_at FROM categories"
            if not include_inactive:
                query += " WHERE is_active = 1"
            query += " ORDER BY lower(category_name), id"
            return [dict(row) for row in conn.execute(query).fetchall()]
        finally:
            conn.close()

    @staticmethod
    def update_category(category_id: int, category_name: str, description: str | None = None, is_active: bool | None = None) -> None:
        name = _normalise_name(category_name)
        if not name:
            raise CategoryError("Category Name is required.")
        if CategoryDAO.category_exists(name, exclude_id=category_id):
            raise CategoryError("A category with this name already exists.")
        conn = get_connection()
        try:
            current = conn.execute("SELECT is_active FROM categories WHERE id = ?", (category_id,)).fetchone()
            if not current:
                raise CategoryError("Category not found.")
            conn.execute(
                """UPDATE categories SET category_name = ?, description = ?, is_active = ?, updated_at = ?
                   WHERE id = ?""",
                (name, _normalise_name(description or "") or None,
                 int(bool(current["is_active"])) if is_active is None else int(bool(is_active)), _now(), category_id),
            )
            conn.commit()
        except sqlite3.IntegrityError as exc:
            raise CategoryError("A category with this name already exists.") from exc
        finally:
            conn.close()

    @staticmethod
    def deactivate_category(category_id: int) -> None:
        CategoryDAO._set_active(category_id, False)

    @staticmethod
    def activate_category(category_id: int) -> None:
        CategoryDAO._set_active(category_id, True)

    @staticmethod
    def _set_active(category_id: int, active: bool) -> None:
        conn = get_connection()
        try:
            cursor = conn.execute(
                "UPDATE categories SET is_active = ?, updated_at = ? WHERE id = ?",
                (int(active), _now(), category_id),
            )
            if cursor.rowcount == 0:
                raise CategoryError("Category not found.")
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def search_categories(search_text: str, include_inactive: bool = True) -> list[dict]:
        term = _normalise_name(search_text)
        conn = get_connection()
        try:
            query = """SELECT id, category_name, description, is_active, created_at, updated_at
                       FROM categories WHERE (category_name LIKE ? OR coalesce(description, '') LIKE ?)"""
            params: list[object] = [f"%{term}%", f"%{term}%"]
            if not include_inactive:
                query += " AND is_active = 1"
            query += " ORDER BY lower(category_name), id"
            return [dict(row) for row in conn.execute(query, params).fetchall()]
        finally:
            conn.close()

    @staticmethod
    def category_exists(category_name: str, exclude_id: int | None = None) -> bool:
        name = _normalise_name(category_name)
        if not name:
            return False
        conn = get_connection()
        try:
            query = "SELECT 1 FROM categories WHERE lower(trim(category_name)) = lower(trim(?))"
            params: list[object] = [name]
            if exclude_id is not None:
                query += " AND id != ?"
                params.append(exclude_id)
            return conn.execute(query, params).fetchone() is not None
        finally:
            conn.close()

    @staticmethod
    def get_items_using_category(category_id: int) -> list[dict]:
        conn = get_connection()
        try:
            rows = conn.execute(
                """SELECT i.id, i.item_name, i.category_id, c.category_name
                   FROM items i LEFT JOIN categories c ON c.id = i.category_id
                   WHERE i.category_id = ? ORDER BY i.item_name""",
                (category_id,),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()


# Function aliases make the small master API convenient to use without
# bypassing the DAO, while retaining the project's class-based DAO convention.
create_category = CategoryDAO.create_category
get_category = CategoryDAO.get_category
get_all_categories = CategoryDAO.get_all_categories
update_category = CategoryDAO.update_category
deactivate_category = CategoryDAO.deactivate_category
activate_category = CategoryDAO.activate_category
search_categories = CategoryDAO.search_categories
category_exists = CategoryDAO.category_exists
get_items_using_category = CategoryDAO.get_items_using_category

