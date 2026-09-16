from __future__ import annotations

from database.connection import get_connection


class SupplierDAO:

    @staticmethod
    def get_all() -> list[dict]:
        conn = get_connection()
        try:
            rows = conn.execute(
                """SELECT s.*, al.ledger_name
                   FROM suppliers s
                   LEFT JOIN account_ledgers al ON al.id = s.ledger_id
                   ORDER BY s.supplier_name"""
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    @staticmethod
    def get_by_id(supplier_id: int) -> dict | None:
        conn = get_connection()
        try:
            row = conn.execute(
                """SELECT s.*, al.ledger_name
                   FROM suppliers s
                   LEFT JOIN account_ledgers al ON al.id = s.ledger_id
                   WHERE s.id = ?""",
                (supplier_id,),
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
                    "SELECT 1 FROM suppliers WHERE supplier_name = ? AND id != ?",
                    (name, exclude_id),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT 1 FROM suppliers WHERE supplier_name = ?",
                    (name,),
                ).fetchone()
            return row is not None
        finally:
            conn.close()

    # ── ledger mapping helpers ──────────────────────────────────────
    @staticmethod
    def get_ledger_id(supplier_id: int) -> int | None:
        """Return the ledger_id linked to this supplier, or None."""
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT ledger_id FROM suppliers WHERE id = ?",
                (supplier_id,),
            ).fetchone()
            return row["ledger_id"] if row else None
        finally:
            conn.close()

    @staticmethod
    def get_supplier_by_ledger(ledger_id: int) -> dict | None:
        """Return the supplier linked to this ledger, or None."""
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM suppliers WHERE ledger_id = ?",
                (ledger_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    # ── create / update ─────────────────────────────────────────────
    @staticmethod
    def insert(
        supplier_name: str,
        sales_tax_no: str = "",
        vat_or_tin: str = "",
        city: str = "",
        contact_person: str = "",
        contact_no: str = "",
        address: str = "",
        state: str = "",
        discount: float = 0.0,
        credit_limit: float = 0.0,
        credit_period: int = 0,
        vat_tin: str = "",
        opening_balance: float = 0.0,
    ) -> int:
        """Insert a new supplier and automatically create + link an Account Ledger.

        Returns the new supplier id.
        """
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("BEGIN")

            # 1. Create the supplier
            cur.execute(
                """INSERT INTO suppliers (
                    supplier_name, sales_tax_no, vat_or_tin, city,
                    contact_person, contact_no, address, state,
                    discount, credit_limit, credit_period, vat_tin, opening_balance
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    supplier_name, sales_tax_no, vat_or_tin, city,
                    contact_person, contact_no, address, state,
                    discount, credit_limit, credit_period, vat_tin, opening_balance,
                ),
            )
            supplier_id = cur.lastrowid

            # 2. Create linked Account Ledger (idempotent: reuse if name exists)
            ledger_name = f"Supplier - {supplier_name}"
            ob_type = "Credit" if opening_balance >= 0 else "Debit"
            ob_amount = abs(opening_balance)

            existing = cur.execute(
                "SELECT id FROM account_ledgers WHERE ledger_name = ?",
                (ledger_name,),
            ).fetchone()

            if existing:
                ledger_id = existing["id"]
            else:
                cur.execute(
                    """INSERT INTO account_ledgers
                        (ledger_name, account_group, opening_balance,
                         opening_balance_type, credit_limit, credit_period,
                         address, city, state, contact_person, contact_no)
                    VALUES (?, 'Sundry Creditors', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        ledger_name, ob_amount, ob_type,
                        credit_limit, credit_period,
                        address, city, state, contact_person, contact_no,
                    ),
                )
                ledger_id = cur.lastrowid

            # 3. Link supplier to ledger
            cur.execute(
                "UPDATE suppliers SET ledger_id = ? WHERE id = ?",
                (ledger_id, supplier_id),
            )

            conn.commit()
            return supplier_id
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def update(
        supplier_id: int,
        supplier_name: str,
        sales_tax_no: str = "",
        vat_or_tin: str = "",
        city: str = "",
        contact_person: str = "",
        contact_no: str = "",
        address: str = "",
        state: str = "",
        discount: float = 0.0,
        credit_limit: float = 0.0,
        credit_period: int = 0,
        vat_tin: str = "",
        opening_balance: float = 0.0,
    ) -> None:
        """Update supplier and sync the linked ledger name/details.

        Does NOT create a second ledger. If no ledger exists yet, creates one.
        """
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("BEGIN")

            # 1. Update the supplier record
            cur.execute(
                """UPDATE suppliers SET
                    supplier_name = ?,
                    sales_tax_no = ?,
                    vat_or_tin = ?,
                    city = ?,
                    contact_person = ?,
                    contact_no = ?,
                    address = ?,
                    state = ?,
                    discount = ?,
                    credit_limit = ?,
                    credit_period = ?,
                    vat_tin = ?,
                    opening_balance = ?
                WHERE id = ?""",
                (
                    supplier_name, sales_tax_no, vat_or_tin, city,
                    contact_person, contact_no, address, state,
                    discount, credit_limit, credit_period, vat_tin,
                    opening_balance,
                    supplier_id,
                ),
            )

            # 2. Sync linked ledger (create if missing)
            row = cur.execute(
                "SELECT ledger_id FROM suppliers WHERE id = ?",
                (supplier_id,),
            ).fetchone()
            ledger_id = row["ledger_id"] if row else None

            if ledger_id:
                # Update existing ledger
                ledger_name = f"Supplier - {supplier_name}"
                cur.execute(
                    """UPDATE account_ledgers SET
                        ledger_name = ?,
                        credit_limit = ?,
                        credit_period = ?,
                        address = ?,
                        city = ?,
                        state = ?,
                        contact_person = ?,
                        contact_no = ?,
                        tax_no = ?
                    WHERE id = ?""",
                    (
                        ledger_name, credit_limit, credit_period,
                        address, city, state, contact_person, contact_no,
                        sales_tax_no,
                        ledger_id,
                    ),
                )
            else:
                # Create new ledger and link
                ledger_name = f"Supplier - {supplier_name}"
                ob_type = "Credit" if opening_balance >= 0 else "Debit"
                ob_amount = abs(opening_balance)

                cur.execute(
                    """INSERT INTO account_ledgers
                        (ledger_name, account_group, opening_balance,
                         opening_balance_type, credit_limit, credit_period,
                         address, city, state, contact_person, contact_no, tax_no)
                    VALUES (?, 'Sundry Creditors', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        ledger_name, ob_amount, ob_type,
                        credit_limit, credit_period,
                        address, city, state, contact_person, contact_no,
                        sales_tax_no,
                    ),
                )
                ledger_id = cur.lastrowid
                cur.execute(
                    "UPDATE suppliers SET ledger_id = ? WHERE id = ?",
                    (ledger_id, supplier_id),
                )

            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def delete(supplier_id: int) -> bool:
        """Delete supplier. Does NOT delete the linked ledger if it has transactions.

        Returns True if deleted, False if blocked (ledger has transactions).
        """
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("BEGIN")

            # Check if linked ledger has transactions
            row = cur.execute(
                "SELECT ledger_id FROM suppliers WHERE id = ?",
                (supplier_id,),
            ).fetchone()

            if row and row["ledger_id"]:
                txn_count = cur.execute(
                    "SELECT COUNT(*) FROM ledger_transactions WHERE ledger_id = ?",
                    (row["ledger_id"],),
                ).fetchone()[0]
                if txn_count > 0:
                    conn.rollback()
                    return False

            cur.execute("DELETE FROM suppliers WHERE id = ?", (supplier_id,))
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
