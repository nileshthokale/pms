from __future__ import annotations

import sqlite3
from typing import Optional, List

from database.connection import get_connection
from database.accounting_posting import (
    SOURCE_JOURNAL_ENTRY,
    posting_engine,
)


class JournalDAO:

    # ── helpers ────────────────────────────────────────────────────────
    @staticmethod
    def generate_next_voucher_no(conn: sqlite3.Connection) -> str:
        cur = conn.execute(
            "SELECT voucher_no FROM journal_entries ORDER BY id DESC LIMIT 1"
        )
        row = cur.fetchone()
        if row is None:
            return "JV-0001"
        last_num = int(row[0].split("-")[1])
        return f"JV-{last_num + 1:04d}"

    # ── read ───────────────────────────────────────────────────────────
    @staticmethod
    def get_all() -> List[dict]:
        conn = get_connection()
        try:
            rows = conn.execute(
                """
                SELECT je.id, je.voucher_no, je.entry_date, je.entry_time,
                       je.narration,
                       COALESCE(SUM(jei.debit), 0) as total_debit,
                       COALESCE(SUM(jei.credit), 0) as total_credit
                FROM journal_entries je
                LEFT JOIN journal_entry_items jei ON jei.journal_entry_id = je.id
                GROUP BY je.id
                ORDER BY je.id DESC
                """
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    @staticmethod
    def get_by_id(entry_id: int) -> Optional[dict]:
        conn = get_connection()
        try:
            cur = conn.execute(
                """
                SELECT je.id, je.voucher_no, je.entry_date, je.entry_time,
                       je.narration,
                       COALESCE(SUM(jei.debit), 0) as total_debit,
                       COALESCE(SUM(jei.credit), 0) as total_credit
                FROM journal_entries je
                LEFT JOIN journal_entry_items jei ON jei.journal_entry_id = je.id
                WHERE je.id = ?
                GROUP BY je.id
                """,
                (entry_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    @staticmethod
    def get_items(entry_id: int) -> List[dict]:
        conn = get_connection()
        try:
            rows = conn.execute(
                """
                SELECT jei.id, jei.journal_entry_id, jei.ledger_id,
                       al.ledger_name, jei.description, jei.debit, jei.credit
                FROM journal_entry_items jei
                LEFT JOIN account_ledgers al ON al.id = jei.ledger_id
                WHERE jei.journal_entry_id = ?
                ORDER BY jei.id
                """,
                (entry_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    @staticmethod
    def get_all_filtered(
        date_from: str = "",
        date_to: str = "",
        voucher_no: str = "",
    ) -> List[dict]:
        conn = get_connection()
        try:
            clauses: list[str] = []
            params: list = []
            if date_from:
                clauses.append("je.entry_date >= ?")
                params.append(date_from)
            if date_to:
                clauses.append("je.entry_date <= ?")
                params.append(date_to)
            if voucher_no:
                clauses.append("je.voucher_no = ?")
                params.append(voucher_no)
            where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
            sql = f"""
                SELECT je.id, je.voucher_no, je.entry_date, je.entry_time,
                       je.narration,
                       COALESCE(SUM(jei.debit), 0) as total_debit,
                       COALESCE(SUM(jei.credit), 0) as total_credit
                FROM journal_entries je
                LEFT JOIN journal_entry_items jei ON jei.journal_entry_id = je.id
                {where}
                GROUP BY je.id
                ORDER BY je.id DESC
            """
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ── write (single transaction) ─────────────────────────────────────
    @staticmethod
    def insert_entry(header: dict, items: List[dict]) -> int:
        """Insert journal entry + items + accounting posting in a single transaction."""
        if len(items) < 2:
            raise ValueError("At least 2 journal lines are required.")

        for i, it in enumerate(items):
            if not it.get("ledger_id"):
                raise ValueError(f"Line {i+1}: Ledger is required.")
            d = it.get("debit", 0.0)
            c = it.get("credit", 0.0)
            if d < 0 or c < 0:
                raise ValueError(f"Line {i+1}: Debit and Credit amounts must be >= 0.")
            if d > 0 and c > 0:
                raise ValueError(f"Line {i+1}: A line cannot have both Debit and Credit.")
            if d == 0 and c == 0:
                raise ValueError(f"Line {i+1}: A line must have either Debit or Credit.")

        total_debit = sum(it.get("debit", 0.0) for it in items)
        total_credit = sum(it.get("credit", 0.0) for it in items)

        if total_debit <= 0:
            raise ValueError("Total Debit must be greater than 0.")
        if abs(total_debit - total_credit) > 0.001:
            raise ValueError(
                f"Debit and Credit are not balanced. "
                f"Debit: {total_debit:.2f}, Credit: {total_credit:.2f}, "
                f"Difference: {abs(total_debit - total_credit):.2f}"
            )

        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("BEGIN")

            voucher_no = JournalDAO.generate_next_voucher_no(conn)

            cur.execute(
                """
                INSERT INTO journal_entries (voucher_no, entry_date, entry_time, narration)
                VALUES (?, ?, ?, ?)
                """,
                (
                    voucher_no,
                    header["entry_date"],
                    header.get("entry_time", ""),
                    header.get("narration", ""),
                ),
            )
            entry_id = cur.lastrowid

            for it in items:
                cur.execute(
                    """
                    INSERT INTO journal_entry_items
                        (journal_entry_id, ledger_id, description, debit, credit)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        entry_id,
                        it["ledger_id"],
                        it.get("description", ""),
                        it.get("debit", 0.0),
                        it.get("credit", 0.0),
                    ),
                )

            # Accounting posting joins THIS transaction (atomic with save).
            posting_engine.post_journal_entry(entry_id, cur=cur)

            conn.commit()
            return entry_id
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def update_entry(entry_id: int, header: dict, items: List[dict]) -> bool:
        """Update journal entry header + replace all items + re-post accounting in a single transaction."""
        if len(items) < 2:
            raise ValueError("At least 2 journal lines are required.")

        for i, it in enumerate(items):
            if not it.get("ledger_id"):
                raise ValueError(f"Line {i+1}: Ledger is required.")
            d = it.get("debit", 0.0)
            c = it.get("credit", 0.0)
            if d < 0 or c < 0:
                raise ValueError(f"Line {i+1}: Debit and Credit amounts must be >= 0.")
            if d > 0 and c > 0:
                raise ValueError(f"Line {i+1}: A line cannot have both Debit and Credit.")
            if d == 0 and c == 0:
                raise ValueError(f"Line {i+1}: A line must have either Debit or Credit.")

        total_debit = sum(it.get("debit", 0.0) for it in items)
        total_credit = sum(it.get("credit", 0.0) for it in items)

        if total_debit <= 0:
            raise ValueError("Total Debit must be greater than 0.")
        if abs(total_debit - total_credit) > 0.001:
            raise ValueError(
                f"Debit and Credit are not balanced. "
                f"Debit: {total_debit:.2f}, Credit: {total_credit:.2f}, "
                f"Difference: {abs(total_debit - total_credit):.2f}"
            )

        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("BEGIN")

            # Reverse previous accounting posting inside THIS transaction
            posting_engine.reverse(SOURCE_JOURNAL_ENTRY, entry_id, cur=cur)

            cur.execute(
                """
                UPDATE journal_entries SET
                    entry_date = ?, entry_time = ?, narration = ?
                WHERE id = ?
                """,
                (
                    header["entry_date"],
                    header.get("entry_time", ""),
                    header.get("narration", ""),
                    entry_id,
                ),
            )

            cur.execute(
                "DELETE FROM journal_entry_items WHERE journal_entry_id = ?",
                (entry_id,),
            )

            for it in items:
                cur.execute(
                    """
                    INSERT INTO journal_entry_items
                        (journal_entry_id, ledger_id, description, debit, credit)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        entry_id,
                        it["ledger_id"],
                        it.get("description", ""),
                        it.get("debit", 0.0),
                        it.get("credit", 0.0),
                    ),
                )

            # Post new accounting effect inside THIS transaction
            posting_engine.post_journal_entry(entry_id, cur=cur)

            conn.commit()
            return True
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def delete_entry(entry_id: int) -> bool:
        """Delete journal entry + reverse accounting posting in a single transaction."""
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("BEGIN")

            # Reverse the accounting posting inside THIS transaction
            posting_engine.reverse(SOURCE_JOURNAL_ENTRY, entry_id, cur=cur)

            cur.execute(
                "DELETE FROM journal_entry_items WHERE journal_entry_id = ?",
                (entry_id,),
            )
            cur.execute(
                "DELETE FROM journal_entries WHERE id = ?",
                (entry_id,),
            )

            conn.commit()
            return True
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
