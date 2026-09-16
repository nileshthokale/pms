from __future__ import annotations

from typing import Optional, List

from database.connection import get_connection


class LedgerDAO:

    # ── ledger CRUD ────────────────────────────────────────────────────
    @staticmethod
    def get_all_ledgers() -> List[dict]:
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM account_ledgers ORDER BY ledger_name"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    @staticmethod
    def get_ledger_by_id(ledger_id: int) -> Optional[dict]:
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM account_ledgers WHERE id = ?", (ledger_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    @staticmethod
    def ledger_name_exists(name: str, exclude_id: int | None = None) -> bool:
        conn = get_connection()
        try:
            if exclude_id is not None:
                row = conn.execute(
                    "SELECT 1 FROM account_ledgers WHERE ledger_name = ? AND id != ?",
                    (name, exclude_id),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT 1 FROM account_ledgers WHERE ledger_name = ?",
                    (name,),
                ).fetchone()
            return row is not None
        finally:
            conn.close()

    @staticmethod
    def search_ledgers(name: str) -> List[dict]:
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM account_ledgers WHERE ledger_name LIKE ? ORDER BY ledger_name",
                (f"%{name}%",),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    @staticmethod
    def insert_ledger(
        ledger_name: str,
        account_group: str = "",
        opening_balance: float = 0.0,
        opening_balance_type: str = "Debit",
        discount: float = 0.0,
        credit_limit: float = 0.0,
        credit_period: int = 0,
        address: str = "",
        city: str = "",
        state: str = "",
        contact_person: str = "",
        contact_no: str = "",
        tax_no: str = "",
        account_group_id: int | None = None,
    ) -> int:
        if not ledger_name or not ledger_name.strip():
            raise ValueError("Ledger Name is required.")
        conn = get_connection()
        try:
            cursor = conn.execute(
                """INSERT INTO account_ledgers (
                    ledger_name, account_group, opening_balance,
                    opening_balance_type, discount, credit_limit,
                    credit_period, address, city, state,
                    contact_person, contact_no, tax_no, account_group_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    ledger_name, account_group, opening_balance,
                    opening_balance_type, discount, credit_limit,
                    credit_period, address, city, state,
                    contact_person, contact_no, tax_no, account_group_id,
                ),
            )
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    @staticmethod
    def update_ledger(
        ledger_id: int,
        ledger_name: str,
        account_group: str = "",
        opening_balance: float = 0.0,
        opening_balance_type: str = "Debit",
        discount: float = 0.0,
        credit_limit: float = 0.0,
        credit_period: int = 0,
        address: str = "",
        city: str = "",
        state: str = "",
        contact_person: str = "",
        contact_no: str = "",
        tax_no: str = "",
        account_group_id: int | None = None,
    ) -> None:
        conn = get_connection()
        try:
            conn.execute(
                """UPDATE account_ledgers SET
                    ledger_name = ?,
                    account_group = ?,
                    opening_balance = ?,
                    opening_balance_type = ?,
                    discount = ?,
                    credit_limit = ?,
                    credit_period = ?,
                    address = ?,
                    city = ?,
                    state = ?,
                    contact_person = ?,
                    contact_no = ?,
                    tax_no = ?,
                    account_group_id = ?
                WHERE id = ?""",
                (
                    ledger_name, account_group, opening_balance,
                    opening_balance_type, discount, credit_limit,
                    credit_period, address, city, state,
                    contact_person, contact_no, tax_no,
                    account_group_id, ledger_id,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def delete_ledger(ledger_id: int) -> None:
        conn = get_connection()
        try:
            ledger = conn.execute(
                "SELECT system_role FROM account_ledgers WHERE id = ?",
                (ledger_id,),
            ).fetchone()
            if ledger and ledger["system_role"]:
                raise ValueError(
                    "This ledger is a system account "
                    f"(role: {ledger['system_role']}) and cannot be deleted. "
                    "Clear its system role first."
                )
            conn.execute("DELETE FROM account_ledgers WHERE id = ?", (ledger_id,))
            conn.commit()
        finally:
            conn.close()

    # ── system roles ───────────────────────────────────────────────────
    @staticmethod
    def get_by_system_role(role: str) -> Optional[dict]:
        """Return the ledger assigned to a system role, or None."""
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM account_ledgers WHERE system_role = ?", (role,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    @staticmethod
    def get_system_ledgers() -> List[dict]:
        """Return all ledgers that carry a system role, ordered by role."""
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM account_ledgers "
                "WHERE system_role IS NOT NULL ORDER BY system_role"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    @staticmethod
    def set_system_role(ledger_id: int, role: Optional[str]) -> None:
        """Assign (or clear, with role=None) a system role on a ledger.

        Refuses to assign a role that is already held by another ledger.
        Transactional.
        """
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("BEGIN")

            exists = cur.execute(
                "SELECT id FROM account_ledgers WHERE id = ?", (ledger_id,)
            ).fetchone()
            if not exists:
                raise ValueError(f"Ledger id {ledger_id} does not exist.")

            if role:
                conflict = cur.execute(
                    "SELECT id FROM account_ledgers WHERE system_role = ? AND id != ?",
                    (role, ledger_id),
                ).fetchone()
                if conflict:
                    raise ValueError(
                        f"System role '{role}' is already assigned to "
                        f"ledger id {conflict['id']}."
                    )

            cur.execute(
                "UPDATE account_ledgers SET system_role = ? WHERE id = ?",
                (role, ledger_id),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _ensure_system_ledger_cur(
        cur, role: str, name: str, account_group: str = ""
    ) -> tuple[int, str]:
        """Ensure a system ledger exists, using an OPEN cursor/transaction.

        Returns (ledger_id, outcome) where outcome is one of:
          'already_configured' — role already assigned, nothing written
          'reused'             — existing ledger with this exact name got the role
          'created'            — new ledger created with name, group and role

        Only the system_role column is written when reusing an existing
        ledger; its other fields are never modified.
        """
        row = cur.execute(
            "SELECT id FROM account_ledgers WHERE system_role = ?", (role,)
        ).fetchone()
        if row:
            return row["id"], "already_configured"

        row = cur.execute(
            "SELECT id FROM account_ledgers WHERE ledger_name = ?", (name,)
        ).fetchone()
        if row:
            cur.execute(
                "UPDATE account_ledgers SET system_role = ? WHERE id = ?",
                (role, row["id"]),
            )
            return row["id"], "reused"

        cur.execute(
            """
            INSERT INTO account_ledgers
                (ledger_name, account_group, opening_balance,
                 opening_balance_type, system_role)
            VALUES (?, ?, 0.0, 'Debit', ?)
            """,
            (name, account_group, role),
        )
        return cur.lastrowid, "created"

    @staticmethod
    def ensure_system_ledger(role: str, name: str, account_group: str = "") -> int:
        """Ensure a single system ledger exists and carries the given role.

        Idempotent, transactional. Returns the ledger id.
        See _ensure_system_ledger_cur for the reuse/creation rules.
        """
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("BEGIN")
            ledger_id, _outcome = LedgerDAO._ensure_system_ledger_cur(
                cur, role, name, account_group
            )
            conn.commit()
            return ledger_id
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ── transaction CRUD ───────────────────────────────────────────────
    @staticmethod
    def get_transactions(ledger_id: int) -> List[dict]:
        conn = get_connection()
        try:
            rows = conn.execute(
                """
                SELECT * FROM ledger_transactions
                WHERE ledger_id = ?
                ORDER BY transaction_date, transaction_time, id
                """,
                (ledger_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    @staticmethod
    def add_transaction(header: dict) -> int:
        conn = get_connection()
        try:
            cursor = conn.execute(
                """
                INSERT INTO ledger_transactions
                    (ledger_id, transaction_date, transaction_time,
                     voucher_type, voucher_no, reference_type,
                     reference_id, description, debit, credit)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    header["ledger_id"],
                    header["transaction_date"],
                    header.get("transaction_time", ""),
                    header["voucher_type"],
                    header["voucher_no"],
                    header.get("reference_type", ""),
                    header.get("reference_id"),
                    header.get("description", ""),
                    header.get("debit", 0.0),
                    header.get("credit", 0.0),
                ),
            )
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    @staticmethod
    def delete_transaction(transaction_id: int) -> None:
        conn = get_connection()
        try:
            conn.execute(
                "DELETE FROM ledger_transactions WHERE id = ?", (transaction_id,)
            )
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def get_balance(ledger_id: int) -> dict:
        """Calculate balance for a ledger (all activity, no date filter).

        Returns dict with: total_debit, total_credit, closing_balance, closing_balance_type.
        """
        return LedgerDAO.get_balance_as_of(ledger_id, None)

    @staticmethod
    def get_balance_as_of(ledger_id: int, as_of_date: Optional[str]) -> dict:
        """Calculate a ledger's balance as of an ISO date (YYYY-MM-DD).

        Shared balance logic (used by the Account Ledger detail and by
        Trial Balance consistency checks). Opening balance is always
        included on its opening_balance_type side; when as_of_date is
        given, only transactions with transaction_date <= as_of_date
        are counted (ISO strings compare correctly).

        Returns dict with: total_debit, total_credit, closing_balance,
        closing_balance_type.
        """
        conn = get_connection()
        try:
            ledger = conn.execute(
                "SELECT opening_balance, opening_balance_type FROM account_ledgers WHERE id = ?",
                (ledger_id,),
            ).fetchone()
            if not ledger:
                return {"total_debit": 0.0, "total_credit": 0.0,
                        "closing_balance": 0.0, "closing_balance_type": "Debit"}

            opening = ledger["opening_balance"] or 0.0
            ob_type = ledger["opening_balance_type"] or "Debit"

            cur = conn.execute(
                "SELECT COALESCE(SUM(debit), 0) as d, COALESCE(SUM(credit), 0) as c "
                "FROM ledger_transactions WHERE ledger_id = :ledger_id "
                "AND (:as_of IS NULL OR transaction_date <= :as_of)",
                {"ledger_id": ledger_id, "as_of": as_of_date},
            )
            row = cur.fetchone()
            total_debit_txn = row["d"]
            total_credit_txn = row["c"]

            # Opening balance contributes to its respective side
            if ob_type == "Debit":
                total_debit = total_debit_txn + opening
                total_credit = total_credit_txn
            else:
                total_debit = total_debit_txn
                total_credit = total_credit_txn + opening

            diff = total_debit - total_credit
            if diff >= 0:
                closing_balance = diff
                closing_balance_type = "Debit"
            else:
                closing_balance = -diff
                closing_balance_type = "Credit"

            return {
                "total_debit": round(total_debit, 2),
                "total_credit": round(total_credit, 2),
                "closing_balance": round(closing_balance, 2),
                "closing_balance_type": closing_balance_type,
            }
        finally:
            conn.close()
