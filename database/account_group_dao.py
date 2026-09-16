"""Structured Account Group DAO — Phase 4A.

Manages the ``account_groups`` table that provides hierarchical,
statement-ready classification for every account ledger.

The group hierarchy is used by future financial-statement reports
(P&L, Balance Sheet) to query ledgers by statement type.
"""

from __future__ import annotations

from typing import Optional, List

from database.connection import get_connection


class AccountGroupDAO:

    # ── read ──────────────────────────────────────────────────────────

    @staticmethod
    def get_all() -> List[dict]:
        """Return every group ordered by statement_type then group_name."""
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM account_groups "
                "ORDER BY statement_type, group_name"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    @staticmethod
    def get_by_id(group_id: int) -> Optional[dict]:
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM account_groups WHERE id = ?", (group_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    @staticmethod
    def get_by_name(name: str) -> Optional[dict]:
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM account_groups WHERE group_name = ?",
                (name,),
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
                    "SELECT 1 FROM account_groups "
                    "WHERE group_name = ? AND id != ?",
                    (name, exclude_id),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT 1 FROM account_groups WHERE group_name = ?",
                    (name,),
                ).fetchone()
            return row is not None
        finally:
            conn.close()

    @staticmethod
    def get_children(parent_id: int) -> List[dict]:
        """Return direct children of *parent_id*."""
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM account_groups "
                "WHERE parent_group_id = ? "
                "ORDER BY group_name",
                (parent_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    @staticmethod
    def get_tree() -> List[dict]:
        """Return all groups organised as a tree.

        Each root group (parent_group_id IS NULL) carries a ``children``
        list.  Only one level of nesting is required by the current
        project but the structure supports deeper hierarchies.
        """
        all_groups = AccountGroupDAO.get_all()
        by_id: dict[int, dict] = {}
        for g in all_groups:
            g["children"] = []
            by_id[g["id"]] = g

        roots: list[dict] = []
        for g in all_groups:
            pid = g["parent_group_id"]
            if pid and pid in by_id:
                by_id[pid]["children"].append(g)
            else:
                roots.append(g)
        return roots

    # ── write ─────────────────────────────────────────────────────────

    @staticmethod
    def insert(
        group_name: str,
        parent_group_id: int | None = None,
        statement_type: str = "",
        normal_balance: str = "",
        is_system: bool = False,
    ) -> int:
        """Create a new account group.  Returns the new row id.

        Raises ValueError on duplicate name or circular parent.
        """
        if not group_name or not group_name.strip():
            raise ValueError("Group Name is required.")

        name = group_name.strip()

        if AccountGroupDAO.name_exists(name):
            raise ValueError(f"Account group '{name}' already exists.")

        if parent_group_id is not None:
            if AccountGroupDAO._is_circular(parent_group_id, None):
                raise ValueError(
                    "Cannot set parent — it would create a circular "
                    "relationship."
                )

        conn = get_connection()
        try:
            cursor = conn.execute(
                """INSERT INTO account_groups
                    (group_name, parent_group_id, statement_type,
                     normal_balance, is_system)
                VALUES (?, ?, ?, ?, ?)""",
                (
                    name,
                    parent_group_id,
                    statement_type.strip(),
                    normal_balance.strip(),
                    1 if is_system else 0,
                ),
            )
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    @staticmethod
    def update(
        group_id: int,
        group_name: str,
        parent_group_id: int | None = None,
        statement_type: str = "",
        normal_balance: str = "",
        is_system: bool = False,
    ) -> None:
        """Update an existing group.

        Raises ValueError on duplicate name, circular parent, or
        attempting to change is_system from True to False.
        """
        if not group_name or not group_name.strip():
            raise ValueError("Group Name is required.")

        name = group_name.strip()
        existing = AccountGroupDAO.get_by_id(group_id)
        if not existing:
            raise ValueError(f"Account group id {group_id} does not exist.")

        if AccountGroupDAO.name_exists(name, exclude_id=group_id):
            raise ValueError(f"Account group '{name}' already exists.")

        if parent_group_id is not None:
            if parent_group_id == group_id:
                raise ValueError("A group cannot be its own parent.")
            if AccountGroupDAO._is_circular(parent_group_id, group_id):
                raise ValueError(
                    "Cannot set parent — it would create a circular "
                    "relationship."
                )

        conn = get_connection()
        try:
            conn.execute(
                """UPDATE account_groups SET
                    group_name = ?,
                    parent_group_id = ?,
                    statement_type = ?,
                    normal_balance = ?,
                    is_system = ?
                WHERE id = ?""",
                (
                    name,
                    parent_group_id,
                    statement_type.strip(),
                    normal_balance.strip(),
                    1 if is_system else 0,
                    group_id,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def can_delete(group_id: int) -> tuple[bool, str]:
        """Check whether a group may be deleted.

        Returns (ok, reason).  Blocks deletion when:
        - the group is marked is_system
        - one or more ledgers reference this group
        """
        group = AccountGroupDAO.get_by_id(group_id)
        if not group:
            return False, "Group does not exist."

        if group["is_system"]:
            return False, "System groups cannot be deleted."

        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM account_ledgers "
                "WHERE account_group_id = ?",
                (group_id,),
            ).fetchone()
            if row["cnt"] > 0:
                return (
                    False,
                    f"This group is used by {row['cnt']} ledger(s) "
                    "and cannot be deleted.",
                )
        finally:
            conn.close()

        return True, ""

    @staticmethod
    def delete(group_id: int) -> None:
        """Delete a group.  Raises ValueError if cannot_delete fails."""
        ok, reason = AccountGroupDAO.can_delete(group_id)
        if not ok:
            raise ValueError(reason)

        conn = get_connection()
        try:
            conn.execute(
                "DELETE FROM account_groups WHERE id = ?", (group_id,)
            )
            conn.commit()
        finally:
            conn.close()

    # ── internal helpers ──────────────────────────────────────────────

    @staticmethod
    def _is_circular(
        candidate_parent_id: int, exclude_id: int | None
    ) -> bool:
        """Return True if setting *candidate_parent_id* as parent would
        create a cycle (walking up the ancestor chain).

        If *exclude_id* is given, it is the group being reparented
        (which we are about to update).  We must detect whether
        candidate_parent_id is a descendant of exclude_id.
        """
        # Walk from candidate_parent up to root.
        # If we encounter exclude_id, that means candidate_parent
        # is a descendant of exclude_id → cycle.
        visited: set[int] = set()
        current = candidate_parent_id
        while current is not None:
            if current in visited:
                return True
            visited.add(current)
            if exclude_id is not None and current == exclude_id:
                return True
            group = AccountGroupDAO.get_by_id(current)
            if not group:
                break
            current = group["parent_group_id"]
        return False
